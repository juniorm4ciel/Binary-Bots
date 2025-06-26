import tkinter as tk
from tkinter import ttk
import threading
import datetime
import time
import numpy as np

# ================== UTILS ==================
def format_money(valor):
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")

def set_azure_theme(root, mode="dark"):
    try:
        import sv_ttk
        sv_ttk.set_theme("dark" if mode == "dark" else "light")
    except ImportError:
        root.configure(bg="#222" if mode == "dark" else "#F5F6FA")

# ================== API WRAPPER ==================
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

# ================== QUADRANTE LOGIC ==================
def get_direction(candle):
    if candle['close'] > candle['open']:
        return 'call'
    elif candle['close'] < candle['open']:
        return 'put'
    else:
        return None

class PowerBossRobot:
    def __init__(self, api, config, log_callback, stats_callback, lucro_callback, stop_event, direction_mode="favor", on_finish=None):
        self.api = api
        self.config = config
        self.log = log_callback
        self.stats_callback = stats_callback
        self.lucro_callback = lucro_callback
        self.stop_event = stop_event
        self.result_stats = {'ops': 0, 'wins': 0, 'losses': 0}
        self.lucro_acumulado = 0.0
        self.entradas_realizadas = 0
        self.direction_mode = direction_mode
        self.on_finish = on_finish

    def get_candles(self, ativo, n=10, size=60):
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
                    if status == 'win' or status is True:
                        return True, lucro
                    elif status == 'loose' or status is False:
                        return False, lucro
                    elif status == 'equal' or status is None:
                        return None, lucro
                    else:
                        self.log(f"Status desconhecido retornado pela API: {status}", "#FF4040")
                        return None, lucro
                if (time.time() - start) > max_wait or self.stop_event.is_set():
                    self.log("Timeout ao obter resultado da ordem!", "#FF4040")
                    return None, 0.0
                time.sleep(0.2)
        except Exception as e:
            self.log(f"Erro na ordem: {e}", "#FF4040")
            return None, 0.0

    def run(self):
        ativos = list(self.config['ativos'])
        if not ativos:
            self.log("Nenhum ativo selecionado!", "#FF4040")
            if self.on_finish:
                self.on_finish()
            return

        self.lucro_acumulado = 0.0
        self.entradas_realizadas = 0
        self.result_stats = {'ops': 0, 'wins': 0, 'losses': 0}
        self.lucro_callback(self.lucro_acumulado)
        self.stats_callback({'ops': 0, 'wins': 0, 'losses': 0, 'taxa': "0%"})
        mg_nivel_max = int(self.config.get('mg_niveis', 1))
        ativo_idx = 0

        soros_percent = self.config.get('soros', 0)
        soros_ativo = soros_percent > 0
        soros_valor = 0
        soros_nivel = 0

        self.log("Robô Quadrante (segunda vela do quadrante) iniciado!", "#FFD700")
        while not self.stop_event.is_set():
            agora = datetime.datetime.now()
            if agora.minute % 5 == 0 and agora.second < 2:
                ativo = ativos[ativo_idx % len(ativos)]
                ativo_idx += 1
                self.log(f"[QUADRANTE NOVO] Minuto {agora.minute:02d} - Ativo: {ativo}", "#FFD700")

                candles = self.get_candles(ativo, n=2, size=60)
                if len(candles) < 2:
                    self.log(f"Não foi possível obter as 2 velas do quadrante para {ativo}.", "#FF4040")
                    time.sleep(3)
                    continue

                primeira_vela = candles[-2]
                direcao_primeira = get_direction(primeira_vela)
                if not direcao_primeira:
                    self.log(f"Primeira vela neutra/doji ({primeira_vela['open']}-{primeira_vela['close']}), pulando quadrante.", "#FF8000")
                    time.sleep(3)
                    continue

                if self.direction_mode == "favor":
                    direcao_entrada = direcao_primeira
                else:
                    direcao_entrada = 'put' if direcao_primeira == 'call' else 'call'

                self.log(f"Primeira vela: {direcao_primeira.upper()} | Entrada na 2ª vela: {('A FAVOR' if self.direction_mode == 'favor' else 'CONTRA')} ({direcao_entrada.upper()})", "#00FFFF")

                alvo_minuto = (agora.minute // 5) * 5 + 1
                while datetime.datetime.now().minute != alvo_minuto:
                    if self.stop_event.is_set():
                        self.log("Robô parado pelo usuário.", "#FFA500")
                        if self.on_finish:
                            self.on_finish()
                        return
                    time.sleep(0.5)

                mg_nivel = 0
                valor_base = self.config['valor']
                valor_entrada = 0

                while mg_nivel <= mg_nivel_max and not self.stop_event.is_set():
                    # ----------- SOROS + MG LOGIC CORRIGIDA -----------
                    if mg_nivel == 0:
                        if soros_ativo and soros_nivel > 0:
                            valor_entrada = soros_valor
                        else:
                            valor_entrada = valor_base
                    else:
                        valor_entrada = valor_entrada * 2

                    self.result_stats['ops'] += 1
                    self.entradas_realizadas += 1
                    self.stats_callback(self._stats())
                    labelmg = "" if mg_nivel == 0 else f"(MG{mg_nivel})"
                    self.log(f"Entrando no ativo {ativo} | Entrada: {mg_nivel+1}/{mg_nivel_max+1} | {direcao_entrada.upper()} {labelmg} | Valor: {valor_entrada:.2f}", "#00FFFF")
                    resultado, lucro_op = self.buy(ativo, valor_entrada, direcao_entrada, self.config['expiracao'])
                    self.lucro_acumulado += lucro_op
                    self.lucro_callback(self.lucro_acumulado)

                    if resultado is None and lucro_op == 0.0:
                        self.log(f"EMPATE (doji) em {ativo} | Valor devolvido.", "#FFD700")
                        self.stats_callback(self._stats())
                        break
                    elif resultado is True:
                        self.result_stats['wins'] += 1
                        self.log(f"WIN no {ativo} com {direcao_entrada.upper()} {labelmg} | Lucro: {lucro_op:.2f}", "#2DC937")
                        if soros_ativo:
                            if mg_nivel == 0:
                                soros_nivel += 1
                                soros_valor = valor_entrada + (lucro_op * (soros_percent / 100))
                            else:
                                soros_nivel = 0
                                soros_valor = 0
                        self.stats_callback(self._stats())
                        break
                    else:
                        if mg_nivel < mg_nivel_max:
                            self.log(f"LOSS no {ativo} | Indo para Martingale {mg_nivel+1}", "#FF8000")
                            mg_nivel += 1
                            self.stats_callback(self._stats())
                            continue
                        else:
                            self.result_stats['losses'] += 1
                            self.log(f"LOSS no {ativo} com {direcao_entrada.upper()} {labelmg} | Perda: {lucro_op:.2f}", "#FF4040")
                            if soros_ativo:
                                soros_nivel = 0
                                soros_valor = 0
                            self.stats_callback(self._stats())
                            break

                if self.verificar_condicoes_parada():
                    if self.on_finish:
                        self.on_finish()
                    return
                time.sleep(3)
            else:
                time.sleep(0.5)
        self.log("Robô finalizado pelo usuário.", "#FFA500")
        if self.on_finish:
            self.on_finish()

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

# ================== ASSERTIVIDADE QUADRANTE ==================
def catalogar_powerboss(api, ativo, minutos=50, mg_niveis=1, direction_mode="favor", use_adx=True):
    candles = api.get_candles(ativo, 60, minutos + (mg_niveis + 2) * 5)
    if not candles or len(candles) < (mg_niveis + 2) * 5:
        return None
    win_niveis = [0] * (mg_niveis+1)
    loss = 0
    total = 0
    for idx in range(0, len(candles) - (mg_niveis + 1), 5):
        ciclo = candles[idx:idx+5+mg_niveis]
        if len(ciclo) < 5 + mg_niveis:
            continue
        primeira = ciclo[0]
        direcao_primeira = get_direction(primeira)
        if not direcao_primeira:
            continue
        if direction_mode == "favor":
            direcao_entrada = direcao_primeira
        else:
            direcao_entrada = 'put' if direcao_primeira == 'call' else 'call'
        resultado = None
        for mg in range(mg_niveis+1):
            candle_ent = ciclo[1+mg]
            if candle_ent['close'] == candle_ent['open']:
                resultado = None
                break
            win = (
                (direcao_entrada == 'call' and candle_ent['close'] > candle_ent['open']) or
                (direcao_entrada == 'put' and candle_ent['close'] < candle_ent['open'])
            )
            if win:
                resultado = mg
                break
        if resultado is not None:
            win_niveis[resultado] += 1
        else:
            loss += 1
        total += 1
    total_wins = sum(win_niveis)
    assertividade = (total_wins / total * 100) if total else 0
    return {
        'ativo': ativo,
        'wins': win_niveis,
        'loss': loss,
        'total': total,
        'assertividade': assertividade,
        'mg_niveis': mg_niveis
    }

# ================== TKINTER APP ==================
class BotFullApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Robô Power Boss - Tkinter Azure Full")
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
        self.direction_mode = tk.StringVar(value="favor")
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
        ttk.Label(frame_config, text="Modo Direção:").grid(row=row, column=2, padx=4, pady=3, sticky="e")
        rb_favor = ttk.Radiobutton(frame_config, text="A favor", variable=self.direction_mode, value="favor")
        rb_contra = ttk.Radiobutton(frame_config, text="Contra", variable=self.direction_mode, value="contra")
        rb_favor.grid(row=row, column=3, padx=4, pady=3)
        rb_contra.grid(row=row, column=4, padx=4, pady=3)

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
        log_btns = ttk.Frame(log_frame)
        log_btns.pack(anchor="e", padx=0, pady=0)
        ttk.Button(log_btns, text="Limpar Log", command=self.clear_log).pack(side="right", padx=8, pady=2)
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

    def clear_log(self):
        self.text_log.config(state="normal")
        self.text_log.delete(1.0, tk.END)
        self.text_log.config(state="disabled")

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
        # Ajuste de cor do log para melhor visualização no tema claro
        if self.theme_mode == "dark":
            bg = "#222"
            fg = "#FFD700"
        else:
            bg = "#000"   # Preto para o log no tema claro
            fg = "#FFD700"
        self.text_log.config(bg=bg, fg=fg)
        self.configure(bg="#222" if self.theme_mode == "dark" else "#F5F6FA")

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
        use_adx = self.var_adx.get()
        try:
            mg_niveis = int(self.combo_mg_niveis.get()) if self.combo_mg_niveis.get() else 1
        except Exception:
            mg_niveis = 1
        direction_mode = self.direction_mode.get()
        if selecionados:
            ativos_analisar = selecionados
        else:
            ativos_analisar = self.ativos
        resultados = []
        self.log_event("Analisando assertividade dos ativos...", "#FFA500")
        for ativo in ativos_analisar:
            try:
                res = catalogar_powerboss(
                    self.api, ativo, minutos=50,
                    mg_niveis=mg_niveis,
                    direction_mode=direction_mode,
                    use_adx=use_adx
                )
                if res:
                    resultados.append(res)
            except Exception as e:
                self.log_event(f"Erro ao catalogar {ativo}: {e}", "#FF4040")
        if not resultados:
            self.log_event("Nenhum ativo pôde ser analisado.", "#FF4040")
            return
        melhores = sorted(resultados, key=lambda x: x['assertividade'], reverse=True)[:3]
        for r in melhores:
            wins_str = " | ".join(
                [f"Wins 1ª: {r['wins'][0]}"] +
                [f"Wins MG{mg}: {r['wins'][mg]}" for mg in range(1, len(r['wins']))]
            )
            msg = (
                f"{r['ativo']} -> {wins_str} | Loss: {r['loss']} | "
                f"Assertividade: {r['assertividade']:.2f}% | Total: {r['total']}"
            )
            self.log_event(msg, "#FFD700")

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
                "mg_niveis": int(self.combo_mg_niveis.get()) if self.combo_mg_niveis.get() else 1,
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

        def on_robot_finish():
            self.robot_thread = None
            self.lbl_robostatus.config(text="Parado", foreground="red")
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")

        self.robot = PowerBossRobot(
            api=self.api,
            config=config,
            log_callback=self.log_event,
            stats_callback=self.update_stats,
            lucro_callback=self.update_lucro,
            stop_event=self.robot_stop,
            direction_mode=self.direction_mode.get(),
            on_finish=on_robot_finish
        )
        self.log_event("Robô iniciado! Aguardando próximo ciclo para operar...", "#2DC937")
        self.robot_thread = threading.Thread(target=self.robot.run, daemon=True)
        self.robot_thread.start()

    def stop_robot(self):
        if self.robot_stop:
            self.robot_stop.set()
        if self.robot_thread and self.robot_thread.is_alive():
            self.robot_thread.join(timeout=2)
        self.robot_thread = None
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
    app = BotFullApp()
    app.mainloop()