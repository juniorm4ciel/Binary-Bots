import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import datetime
import numpy as np

# ================================ UTILS ================================
def format_money(valor):
    # Corrige para formato brasileiro: 60830.35 -> 60.830,35
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")

def set_azure_theme(root, mode="dark"):
    try:
        import sv_ttk
        if mode == "dark":
            sv_ttk.set_theme("dark")
        else:
            sv_ttk.set_theme("light")
    except ImportError:
        root.configure(bg="#222" if mode == "dark" else "#F5F6FA")

# ================================ API WRAPPER ================================
class IQOptionAPI:
    def __init__(self, email, password):
        from iqoptionapi.stable_api import IQ_Option
        self.api = IQ_Option(email, password)
        self.connected = False

    def connect(self):
        status, reason = self.api.connect()
        self.connected = status
        return status, reason

    def disconnect(self):
        self.connected = False

    def change_balance(self, tipo):
        self.api.change_balance(tipo)

    def get_balance(self):
        return self.api.get_balance()

    def get_all_open_time(self):
        return self.api.get_all_open_time()

    def get_candles(self, ativo, interval, n, now=None):
        now = now or time.time()
        candles = self.api.get_candles(ativo, interval, n, now)
        return sorted(candles, key=lambda x: x['from'])

    def buy(self, valor, ativo, direcao, exp):
        return self.api.buy(valor, ativo, direcao, exp)

    def check_win_v4(self, order_id):
        return self.api.check_win_v4(order_id)

    def catalogar_mhi(self, ativo, minutos=50):
        candles = self.get_candles(ativo, 60, minutos+6)
        win = mg1 = loss = 0
        total = 0
        for i in range(5, minutos+5):
            ultimos = candles[i-5:i]
            if any(c['close'] == c['open'] for c in ultimos):
                continue
            cores = ['c' if c['close'] > c['open'] else 'p' for c in ultimos]
            maioria = 'put' if cores.count('c') > cores.count('p') else 'call'
            entrada = candles[i]
            resultado = entrada['close'] > entrada['open'] if maioria == 'call' else entrada['close'] < entrada['open']
            total += 1
            if resultado:
                win += 1
                continue
            entrada_mg1 = candles[i+1]
            resultado_mg1 = entrada_mg1['close'] > entrada_mg1['open'] if maioria == 'call' else entrada_mg1['close'] < entrada_mg1['open']
            if resultado_mg1:
                mg1 += 1
            else:
                loss += 1
        assertividade = ((win + mg1) / total * 100) if total else 0
        rep, total_rep = 0, 0
        for i in range(5, minutos+5):
            ultimos = candles[i-5:i]
            if any(c['close'] == c['open'] for c in ultimos):
                continue
            cores = ['c' if c['close'] > c['open'] else 'p' for c in ultimos]
            maioria = 'c' if cores.count('c') > cores.count('p') else 'p'
            sexta = candles[i]
            cor_sexta = 'c' if sexta['close'] > sexta['open'] else 'p' if sexta['close'] < sexta['open'] else 'd'
            if cor_sexta == maioria:
                rep += 1
            total_rep += 1
        indice = (rep / total_rep * 100) if total_rep else 0
        resumo = (f"Resumo catalogação [{ativo}]: Wins: {win} | MG1: {mg1} | Loss: {loss} | "
                  f"Assertividade: {assertividade:.2f}% | Total: {total}")
        repeticao = (f"Índice de repetição: {indice:.2f}% ({rep}/{total_rep})")
        return resumo, repeticao

# ================================ LOGICA MHI ================================
ADX_PERIOD = 14
ADX_LIMIAR = 21

def calculate_adx(candles, period=ADX_PERIOD):
    if len(candles) < period + 1:
        return None, None, None
    highs = np.array([c['max'] for c in candles])
    lows = np.array([c['min'] for c in candles])
    closes = np.array([c['close'] for c in candles])
    plus_dm = highs[1:] - highs[:-1]
    minus_dm = lows[:-1] - lows[1:]
    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)
    tr = np.maximum.reduce([
        highs[1:] - lows[1:],
        np.abs(highs[1:] - closes[:-1]),
        np.abs(lows[1:] - closes[:-1])
    ])
    atr = np.zeros_like(tr)
    atr[0] = np.mean(tr[:period])
    for i in range(1, len(tr)):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
    plus_dm_ema = np.zeros_like(plus_dm)
    minus_dm_ema = np.zeros_like(minus_dm)
    plus_dm_ema[0] = np.mean(plus_dm[:period])
    minus_dm_ema[0] = np.mean(minus_dm[:period])
    for i in range(1, len(plus_dm)):
        plus_dm_ema[i] = (plus_dm_ema[i-1] * (period-1) + plus_dm[i]) / period
        minus_dm_ema[i] = (minus_dm_ema[i-1] * (period-1) + minus_dm[i]) / period
    plus_di = 100 * (plus_dm_ema / (atr + 1e-10))
    minus_di = 100 * (minus_dm_ema / (atr + 1e-10))
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = np.zeros_like(dx)
    adx[0] = np.mean(dx[:period])
    for i in range(1, len(dx)):
        adx[i] = (adx[i-1] * (period-1) + dx[i]) / period
    return adx[-1], plus_di[-1], minus_di[-1]

# =============================== MHIRobot ================================
class MHIRobot:
    def __init__(self, api, config, log_callback, stats_callback, lucro_callback, stop_event):
        self.api = api
        self.config = config
        self.log = log_callback
        self.stats_callback = stats_callback
        self.lucro_callback = lucro_callback
        self.stop_event = stop_event
        self.result_stats = {'ops': 0, 'wins': 0, 'losses': 0}
        self.lucro_acumulado = 0.0
        self.entradas_realizadas = 0
        self.ultimo_ciclo_operado = {}
        self.lock = threading.Lock()

    def get_candles(self, ativo, n=5, size=60):
        try:
            return self.api.get_candles(ativo, size, n, time.time())
        except Exception:
            return []

    def buy(self, ativo, valor, direcao, exp):
        try:
            _, id = self.api.buy(valor, ativo, direcao, exp)
            if not id:
                self.log("Falha ao enviar ordem para {}.".format(ativo), "#FF4040")
                return None, 0.0
            max_wait = 120
            start = time.time()
            while True:
                status, lucro = self.api.check_win_v4(id)
                if status is not None:
                    return status, lucro
                if (time.time() - start) > max_wait or self.stop_event.is_set():
                    self.log("Timeout ao obter resultado da ordem!", "#FF4040")
                    return None, 0.0
                time.sleep(0.2)
        except Exception as e:
            self.log(f"Erro na ordem: {e}", "#FF4040")
            return None, 0.0

    def sinal_mhi(self, ativo):
        candles = self.get_candles(ativo, n=5, size=60)
        if not candles or len(candles) < 5:
            return None
        ultimas_tres = candles[-3:]
        if any(c['close'] == c['open'] for c in ultimas_tres):
            return None
        cores = ['c' if c['close'] > c['open'] else 'p' for c in ultimas_tres]
        if cores.count('c') > cores.count('p'):
            return 'put'
        elif cores.count('p') > cores.count('c'):
            return 'call'
        else:
            return None

    def get_cycle_key(self, dt=None):
        if dt is None:
            dt = datetime.datetime.now()
        return f"{dt.year}-{dt.month}-{dt.day} {dt.hour}:{(dt.minute // 5) * 5:02d}"

    def run(self):
        ativos = list(self.config['ativos'])
        if not ativos:
            self.log("Nenhum ativo selecionado!", "#FF4040")
            return
        self.ultimo_ciclo_operado = {ativo: None for ativo in ativos}
        self.lucro_acumulado = 0.0
        self.entradas_realizadas = 0
        self.result_stats = {'ops': 0, 'wins': 0, 'losses': 0}
        self.lucro_callback(self.lucro_acumulado)
        self.stats_callback({'ops': 0, 'wins': 0, 'losses': 0, 'taxa': "0%"})
        mg_nivel_max = int(self.config.get('mg_niveis', 1))
        self.log("Robô: aguardando próximo quadrante para operar.", "#FFD700")

        while not self.stop_event.is_set():
            agora = datetime.datetime.now()
            # Só opera no exato início do quadrante
            if not (agora.minute % 5 == 0 and agora.second == 0):
                time.sleep(0.2)
                continue

            quadrante_key = f"{agora.year}-{agora.month}-{agora.day} {agora.hour}:{(agora.minute // 5) * 5:02d}"
            for ativo in ativos:
                with self.lock:
                    # Se já operou neste quadrante para este ativo, pula
                    if self.ultimo_ciclo_operado.get(ativo) == quadrante_key:
                        continue
                    # Marca como já operado para o ativo neste quadrante, ANTES de operar!
                    self.ultimo_ciclo_operado[ativo] = quadrante_key

                    if self.stop_event.is_set():
                        return
                    if self.verificar_condicoes_parada():
                        return

                    self.log(f"Analisando velas do ativo {ativo}...", "#FFD700")
                    direcao = self.sinal_mhi(ativo)

                    if direcao is None:
                        self.log(f"Operação bloqueada no {ativo}: Detecção de doji ou empate nas velas.", "#FF8000")
                        continue

                    if self.config['adx']:
                        candles = self.get_candles(ativo, n=ADX_PERIOD+1, size=60)
                        adx, _, _ = calculate_adx(candles)
                        if adx is not None and adx >= ADX_LIMIAR:
                            self.log(f"Operação bloqueada no {ativo}: ADX acima do limiar (valor atual: {adx:.2f}).", "#FF8000")
                            continue

                    valor = self.config['valor']
                    exp = self.config['expiracao']
                    mg_nivel = 0
                    operou = False  # Flag para só contar uma operação por ciclo por ativo

                    while mg_nivel <= mg_nivel_max and not self.stop_event.is_set():
                        # Só conta operação na primeira entrada do ciclo
                        if not operou:
                            self.result_stats['ops'] += 1
                            self.entradas_realizadas += 1
                            operou = True

                        self.stats_callback(self._stats())
                        self.log(f"Entrando no ativo {ativo} | Entrada: {mg_nivel+1}/{mg_nivel_max+1} | {direcao.upper()} | Valor: {valor:.2f}", "#00FFFF")
                        resultado, lucro_op = self.buy(ativo, valor, direcao, exp)
                        self.lucro_acumulado += lucro_op
                        self.lucro_callback(self.lucro_acumulado)

                        if resultado is None and lucro_op == 0.0:
                            self.log(f"EMPATE (doji) em {ativo} | Valor devolvido.", "#FFD700")
                            self.stats_callback(self._stats())
                            break
                        elif resultado is True:
                            self.result_stats['wins'] += 1
                            self.log(f"WIN no {ativo} com {direcao.upper()} | Lucro: {lucro_op:.2f}", "#2DC937")
                            self.stats_callback(self._stats())
                            break  # <-- Sai do loop MG após WIN
                        else:  # resultado is False
                            if mg_nivel < mg_nivel_max:
                                self.log(f"LOSS no {ativo} | Indo para Martingale {mg_nivel+1}", "#FF8000")
                                mg_nivel += 1
                                valor *= 2
                                # NÃO incrementa losses aqui!
                                self.stats_callback(self._stats())
                                continue
                            else:
                                self.result_stats['losses'] += 1
                                self.log(f"LOSS no {ativo} com {direcao.upper()} | Perda: {lucro_op:.2f}", "#FF4040")
                                self.stats_callback(self._stats())
                                break

                        # Soros só ativa se for WIN (resultado is True)
                        if self.config['soros'] > 0 and resultado is True:
                            aumento = lucro_op * (self.config['soros']/100)
                            valor += aumento
                            self.log(f"Soros ativado: próxima entrada {valor:.2f} (+{aumento:.2f})", "#00BFFF")

                    if self.verificar_condicoes_parada():
                        return

            # Aguarda sair do início do quadrante para não operar mais de uma vez
            while True:
                agora2 = datetime.datetime.now()
                if not (agora2.minute % 5 == 0 and agora2.second == 0):
                    break
                time.sleep(0.2)

        self.log("Robô finalizado pelo usuário.", "#FFA500")

    def verificar_condicoes_parada(self):
        if not self.config['stop_lucro']:
            if self.entradas_realizadas >= self.config['entradas']:
                self.log(f"Robô parou: número máximo de entradas atingido ({self.entradas_realizadas}).", "#FF8000")
                return True
        if self.config['stop_lucro']:
            alvo_lucro = self.config['lucro']
            alvo_perda = self.config['perda']
            if alvo_lucro > 0 and self.lucro_acumulado >= alvo_lucro:
                self.log(f"Stop WIN atingido! Lucro: {self.lucro_acumulado:.2f}", "#00BFFF")
                return True
            if alvo_perda > 0 and abs(self.lucro_acumulado) >= alvo_perda:
                self.log(f"Stop LOSS atingido! Prejuízo: {self.lucro_acumulado:.2f}", "#FF4040")
                return True
        return False

    def _stats(self):
        ops = self.result_stats['ops']
        wins = self.result_stats['wins']
        losses = self.result_stats['losses']
        taxa = (wins / ops * 100) if ops else 0
        return {'ops': ops, 'wins': wins, 'losses': losses, 'taxa': f"{taxa:.1f}%"}

# =============================== MHIApp ================================
class MHIApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Robô MHI - Tkinter Azure")
        self.geometry("1050x680")
        self.resizable(True, True)
        self.theme_mode = "dark"
        set_azure_theme(self, self.theme_mode)
        self.api = None
        self.connected = False
        self.robot = None
        self.robot_thread = None
        self.robot_stop = threading.Event()
        self.ativos = []
        self.create_widgets()
        self.after(1000, self.update_clock)

    def create_widgets(self):
        frame_conn = ttk.LabelFrame(self, text="Conexão")
        frame_conn.pack(fill="x", padx=10, pady=8)
        ttk.Label(frame_conn, text="Email:").grid(row=0, column=0, padx=6, pady=4, sticky="e")
        self.entry_email = ttk.Entry(frame_conn, width=29)
        self.entry_email.grid(row=0, column=1, padx=6, pady=4)
        ttk.Label(frame_conn, text="Senha:").grid(row=0, column=2, padx=6, pady=4, sticky="e")
        self.entry_senha = ttk.Entry(frame_conn, width=16, show="*")
        self.entry_senha.grid(row=0, column=3, padx=6, pady=4)
        ttk.Label(frame_conn, text="Conta:").grid(row=0, column=4, padx=6, pady=4, sticky="e")
        self.combo_conta = ttk.Combobox(frame_conn, values=["PRACTICE", "REAL"], width=8, state="readonly")
        self.combo_conta.current(0)
        self.combo_conta.grid(row=0, column=5, padx=6, pady=4)
        self.btn_connect = ttk.Button(frame_conn, text="Conectar", command=self.connect_api)
        self.btn_connect.grid(row=0, column=6, padx=6, pady=4)
        self.btn_disconnect = ttk.Button(frame_conn, text="Desconectar", command=self.disconnect_api, state="disabled")
        self.btn_disconnect.grid(row=0, column=7, padx=6, pady=4)
        self.lbl_status = ttk.Label(frame_conn, text="Desconectado", foreground="red")
        self.lbl_status.grid(row=0, column=8, padx=10, pady=4)
        self.lbl_saldo = ttk.Label(frame_conn, text="Saldo: --")
        self.lbl_saldo.grid(row=0, column=9, padx=10, pady=4)
        self.btn_theme = ttk.Button(frame_conn, text="🌙 Modo Escuro", command=self.toggle_theme)
        self.btn_theme.grid(row=0, column=10, padx=10, pady=4)

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=10, pady=5)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=2)
        main.columnconfigure(2, weight=2)
        main.rowconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        frame_ativos = ttk.LabelFrame(main, text="Ativos")
        frame_ativos.grid(row=0, column=0, rowspan=2, sticky="nswe", padx=6, pady=4)
        self.entry_busca_ativo = ttk.Entry(frame_ativos, width=17)
        self.entry_busca_ativo.pack(padx=5, pady=3)
        self.entry_busca_ativo.bind("<KeyRelease>", self.filter_ativos)
        self.list_ativos = tk.Listbox(frame_ativos, width=22, height=14, selectmode="multiple")
        self.list_ativos.pack(padx=5, pady=3, fill="y")
        btns_ativos = ttk.Frame(frame_ativos)
        btns_ativos.pack(pady=2)
        ttk.Button(btns_ativos, text="Atualizar Ativos", command=self.atualiza_ativos).pack(side="left", padx=3)
        ttk.Button(btns_ativos, text="Analisar Assertividade", command=self.catalogar_ativo).pack(side="left", padx=3)

        frame_config = ttk.LabelFrame(main, text="Configuração do Robô")
        frame_config.grid(row=0, column=1, sticky="nswe", padx=6, pady=4)
        row = 0
        ttk.Label(frame_config, text="Valor $:").grid(row=row, column=0, padx=4, pady=3, sticky="e")
        self.entry_valor = ttk.Entry(frame_config, width=6)
        self.entry_valor.insert(0, "25")
        self.entry_valor.grid(row=row, column=1, padx=4, pady=3)
        ttk.Label(frame_config, text="Expiração (min):").grid(row=row, column=2, padx=4, pady=3, sticky="e")
        self.combo_exp = ttk.Combobox(frame_config, values=["1", "2", "3", "4", "5"], width=4, state="readonly")
        self.combo_exp.current(0)
        self.combo_exp.grid(row=row, column=3, padx=4, pady=3)
        ttk.Label(frame_config, text="Entradas:").grid(row=row, column=4, padx=4, pady=3, sticky="e")
        self.spin_entradas = ttk.Spinbox(frame_config, from_=1, to=50, width=5)
        self.spin_entradas.set(3)
        self.spin_entradas.grid(row=row, column=5, padx=4, pady=3)
        row += 1
        ttk.Label(frame_config, text="Soros (%):").grid(row=row, column=0, padx=4, pady=3, sticky="e")
        self.spin_soros = ttk.Spinbox(frame_config, from_=0, to=100, increment=5, width=5)
        self.spin_soros.set(0)
        self.spin_soros.grid(row=row, column=1, padx=4, pady=3)
        self.var_otc = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame_config, text="Incluir OTC", variable=self.var_otc).grid(row=row, column=2, padx=4, pady=3)
        self.var_martingale = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame_config, text="Martingale", variable=self.var_martingale).grid(row=row, column=3, padx=4, pady=3)
        ttk.Label(frame_config, text="Níveis MG:").grid(row=row, column=4, padx=4, pady=3, sticky="e")
        self.combo_mg_niveis = ttk.Combobox(frame_config, values=["1", "2", "3", "4", "5"], width=4, state="readonly")
        self.combo_mg_niveis.current(0)
        self.combo_mg_niveis.grid(row=row, column=5, padx=4, pady=3)
        row += 1
        self.var_adx = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame_config, text="Usar ADX (<21)", variable=self.var_adx).grid(row=row, column=0, padx=4, pady=3)
        ttk.Label(frame_config, text="Stop Win $:").grid(row=row, column=2, padx=4, pady=3, sticky="e")
        self.entry_stopwin = ttk.Entry(frame_config, width=7)
        self.entry_stopwin.grid(row=row, column=3, padx=4, pady=3)
        ttk.Label(frame_config, text="Stop Loss $:").grid(row=row, column=4, padx=4, pady=3, sticky="e")
        self.entry_stoploss = ttk.Entry(frame_config, width=7)
        self.entry_stoploss.grid(row=row, column=5, padx=4, pady=3)
        row += 1
        self.var_stop = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_config, text="Operar por Lucro/Stop Loss", variable=self.var_stop).grid(row=row, column=0, padx=4, pady=3)

        frame_ctrl = ttk.LabelFrame(main, text="Controle")
        frame_ctrl.grid(row=1, column=1, sticky="nswe", padx=6, pady=4)
        self.btn_start = ttk.Button(frame_ctrl, text="▶️ Iniciar Robô", command=self.start_robot)
        self.btn_start.grid(row=0, column=0, padx=8, pady=9)
        self.btn_stop = ttk.Button(frame_ctrl, text="⏹️ Parar Robô", command=self.stop_robot, state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=8, pady=9)
        ttk.Label(frame_ctrl, text="Status:").grid(row=0, column=2, padx=8, pady=9)
        self.lbl_robostatus = ttk.Label(frame_ctrl, text="Inativo", foreground="red")
        self.lbl_robostatus.grid(row=0, column=3, padx=6, pady=9)
        stats = ttk.LabelFrame(main, text="Estatísticas")
        stats.grid(row=1, column=2, sticky="nswe", padx=6, pady=4)
        ttk.Label(stats, text="Op.:").grid(row=0, column=0, padx=4, pady=2)
        self.lbl_ops = ttk.Label(stats, text="0")
        self.lbl_ops.grid(row=0, column=1)
        ttk.Label(stats, text="Wins:").grid(row=0, column=2, padx=4, pady=2)
        self.lbl_wins = ttk.Label(stats, text="0")
        self.lbl_wins.grid(row=0, column=3)
        ttk.Label(stats, text="Losses:").grid(row=0, column=4, padx=4, pady=2)
        self.lbl_losses = ttk.Label(stats, text="0")
        self.lbl_losses.grid(row=0, column=5)
        ttk.Label(stats, text="Taxa:").grid(row=0, column=6, padx=4, pady=2)
        self.lbl_taxa = ttk.Label(stats, text="0%")
        self.lbl_taxa.grid(row=0, column=7)
        frame_lucro = ttk.LabelFrame(main, text="Lucro Atual")
        frame_lucro.grid(row=0, column=2, sticky="nswe", padx=6, pady=4)
        self.lbl_lucro = ttk.Label(frame_lucro, text="R$ 0,00", font=("Arial", 22, "bold"), foreground="green")
        self.lbl_lucro.pack(padx=3, pady=6)

        log_frame = ttk.LabelFrame(self, text="Log de eventos principais")
        log_frame.pack(fill="both", expand=True, padx=10, pady=4)
        self.text_log = tk.Text(log_frame, height=11, state="disabled", bg="#222", fg="#FFD700", font=("Consolas", 10))
        self.text_log.pack(fill="both", expand=True, padx=4, pady=4)

        clockf = ttk.Frame(self)
        clockf.pack(anchor="e", padx=14)
        ttk.Label(clockf, text="Horário:").pack(side="left")
        self.lbl_clock = ttk.Label(clockf, text="")
        self.lbl_clock.pack(side="left")

    def update_clock(self):
        from datetime import datetime
        self.lbl_clock.config(text=datetime.now().strftime("%H:%M:%S"))
        self.after(1000, self.update_clock)

    def log_event(self, msg, color="#FFD700"):
        now = datetime.datetime.now().strftime('%H:%M:%S')
        msg = f"[{now}] {msg}"
        self.text_log.config(state="normal")
        self.text_log.insert("end", f"{msg}\n")
        self.text_log.tag_add(color, "end-2l linestart", "end-2l lineend")
        self.text_log.tag_config(color, foreground=color)
        self.text_log.config(state="disabled")
        self.text_log.see("end")

    def connect_api(self):
        email = self.entry_email.get().strip()
        senha = self.entry_senha.get().strip()
        conta = self.combo_conta.get().upper()
        if not email or not senha:
            self.log_event("Preencha email e senha para conectar.", "#FF4040")
            return
        self.log_event("Tentando conectar à corretora...", "#00BFFF")
        self.update()
        try:
            self.api = IQOptionAPI(email, senha)
            status, reason = self.api.connect()
            if status:
                self.api.change_balance(conta)
                saldo = self.api.get_balance()
                self.connected = True
                self.lbl_status.config(text="Conectado", foreground="#2DC937")
                self.btn_connect.config(state="disabled")
                self.btn_disconnect.config(state="normal")
                self.log_event(f"Conectado! Saldo: R$ {format_money(saldo)}", "#2DC937")
                self.lbl_saldo.config(text=f"Saldo: R$ {format_money(saldo)}")
            else:
                self.connected = False
                self.lbl_status.config(text="Desconectado", foreground="red")
                self.log_event(f"Erro ao conectar: {reason}", "#FF4040")
        except Exception as e:
            self.connected = False
            self.lbl_status.config(text="Desconectado", foreground="red")
            self.log_event(f"Erro ao conectar: {str(e)}", "#FF4040")

    def disconnect_api(self):
        if self.api:
            try:
                self.api.disconnect()
            except Exception:
                pass
        self.api = None
        self.connected = False
        self.lbl_status.config(text="Desconectado", foreground="red")
        self.btn_connect.config(state="normal")
        self.btn_disconnect.config(state="disabled")
        self.lbl_saldo.config(text="Saldo: --")
        self.log_event("Desconectado da corretora.", "#FF4040")

    def toggle_theme(self):
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        set_azure_theme(self, self.theme_mode)
        icon = "🌙" if self.theme_mode == "dark" else "☀️"
        label = "Modo Escuro" if self.theme_mode == "dark" else "Modo Claro"
        self.btn_theme.config(text=f"{icon} {label}")
        bg = "#222" if self.theme_mode == "dark" else "#F5F6FA"
        fg = "#FFD700" if self.theme_mode == "dark" else "#333"
        self.text_log.config(bg=bg, fg=fg)
        self.configure(bg=bg)

    def atualiza_ativos(self):
        if not self.api or not self.connected:
            self.log_event("Conecte-se para buscar ativos.", "#FF4040")
            return
        self.log_event("Buscando lista de ativos...", "#00BFFF")
        self.update()
        try:
            ativos_all = self.api.get_all_open_time()
            ativos = []
            for tipo in ['turbo', 'binary']:
                for ativo, status_ativo in ativos_all[tipo].items():
                    if status_ativo['open']:
                        if tipo == "turbo" and (not self.var_otc.get() and '-OTC' in ativo):
                            continue
                        ativos.append(ativo)
            self.ativos = sorted(ativos)
            self.update_ativos_list()
            self.log_event(f"Ativos atualizados ({len(self.ativos)} ativos abertos).", "#2DC937")
        except Exception as e:
            self.log_event(f"Erro ao buscar ativos: {e}", "#FF4040")

    def update_ativos_list(self, filtrar=""):
        self.list_ativos.delete(0, tk.END)
        for ativo in self.ativos:
            if not filtrar or filtrar.lower() in ativo.lower():
                self.list_ativos.insert(tk.END, ativo)

    def filter_ativos(self, event):
        texto = self.entry_busca_ativo.get().strip()
        self.update_ativos_list(filtrar=texto)

    def get_selected_ativos(self):
        indices = self.list_ativos.curselection()
        return [self.list_ativos.get(i) for i in indices]

    def catalogar_ativo(self):
        if not self.api or not self.connected:
            self.log_event("Conecte-se para analisar assertividade.", "#FF4040")
            return
        selecionados = self.get_selected_ativos()
        if selecionados:
            for ativo in selecionados:
                try:
                    cat, rep = self.api.catalogar_mhi(ativo, minutos=50)
                    self.log_event(cat, "#FFD700")
                    self.log_event(rep, "#FFA500")
                except Exception as e:
                    self.log_event(f"Erro ao catalogar {ativo}: {e}", "#FF4040")
        else:
            melhor = {"ativo": None, "cat": "", "rep": "", "assertividade": -1}
            for ativo in self.ativos:
                try:
                    cat, rep = self.api.catalogar_mhi(ativo, minutos=50)
                    perc = float(cat.split("Assertividade:")[1].split("%")[0])
                    if perc > melhor["assertividade"]:
                        melhor = {"ativo": ativo, "cat": cat, "rep": rep, "assertividade": perc}
                except Exception:
                    continue
            if melhor["ativo"]:
                self.log_event(melhor["cat"], "#FFD700")
                self.log_event(melhor["rep"], "#FFA500")
            else:
                self.log_event("Nenhum ativo pôde ser analisado.", "#FF4040")

    def start_robot(self):
        if self.robot_thread and self.robot_thread.is_alive():
            self.log_event("Já está rodando!", "#FF8000")
            return
        if not self.api or not self.connected:
            self.log_event("Conecte-se antes de iniciar o robô.", "#FF4040")
            return
        ativos = self.get_selected_ativos() or self.ativos
        if not ativos:
            self.log_event("Selecione ao menos um ativo ou atualize a lista.", "#FF8000")
            return
        try:
            config = {
                "valor": float(self.entry_valor.get().replace(",", ".")),
                "expiracao": int(self.combo_exp.get()),
                "entradas": int(self.spin_entradas.get()),
                "soros": int(self.spin_soros.get()),
                "otc": self.var_otc.get(),
                "martingale": self.var_martingale.get(),
                "mg_niveis": int(self.combo_mg_niveis.get()),
                "adx": self.var_adx.get(),
                "stop_lucro": self.var_stop.get(),
                "lucro": float(self.entry_stopwin.get().replace(",", ".")) if self.entry_stopwin.get() else 0.0,
                "perda": float(self.entry_stoploss.get().replace(",", ".")) if self.entry_stoploss.get() else 0.0,
                "ativos": ativos
            }
        except Exception:
            self.log_event("Preencha corretamente as configurações.", "#FF4040")
            return
        self.robot_stop.clear()
        self.lbl_robostatus.config(text="Operando", foreground="#FFB000")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.robot = MHIRobot(
            api=self.api,
            config=config,
            log_callback=self.log_event,
            stats_callback=self.update_stats,
            lucro_callback=self.update_lucro,
            stop_event=self.robot_stop
        )
        self.log_event("Robô iniciado! Aguardando próximo quadrante para operar...", "#2DC937")
        self.robot_thread = threading.Thread(target=self.robot.run, daemon=True)
        self.robot_thread.start()

    def stop_robot(self):
        if self.robot_stop:
            self.robot_stop.set()
        self.lbl_robostatus.config(text="Parado", foreground="red")
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.log_event("Robô parado.", "#FF8000")

    def update_stats(self, stats):
        self.lbl_ops.config(text=str(stats['ops']))
        self.lbl_wins.config(text=str(stats['wins']))
        self.lbl_losses.config(text=str(stats['losses']))
        self.lbl_taxa.config(text=stats['taxa'])

    def update_lucro(self, valor):
        cor = "green" if valor >= 0 else "red"
        sinal = "" if valor >= 0 else "-"
        valor_abs = abs(valor)
        texto = f"R${sinal}{valor_abs:,.2f}".replace('.', ',')
        self.lbl_lucro.config(text=texto, foreground=cor)

if __name__ == "__main__":
    app = MHIApp()
    app.mainloop()