import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import time
import datetime
from iqoptionapi.stable_api import IQ_Option
import logging
import sys
import threading
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def calculate_adx(candles, period=14):
    """
    Calcula o indicador ADX a partir de uma lista de candles (dicionários com os campos 'max', 'min', 'close').
    Retorna:
        - adx: valor do ADX mais recente
        - plus_di: valor +DI mais recente
        - minus_di: valor -DI mais recente
    """
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

    # Para suavizar os DMs, usamos média móvel exponencial (EMA)
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

class IQFimatheBot:
    def __init__(self, root):
        self.root = root
        self.root.title("Robô MHI v1.0 - Junior Maciel")
        self.root.geometry("1000x800")
        self.root.resizable(False, False)
        self.api = None
        self.connected = False
        self.running = False
        self.conta_tipo = "PRACTICE"
        self.operacoes_realizadas = {}
        self.total_acertos = 0
        self.total_erros = 0
        self.ativos_selecionados = []
        self.ativos_disponiveis = []
        self.active_operations = {}
        self.operacoes_per_ativo = {}
        self.suspended_assets = set()
        self.last_signal_bar = {}
        self.last_candles = {}
        self.custom_assets = {}
        self.martingale_status = {}
        self.market_status = {}
        self.mhi_catalog_info = {}
        self.processed_ops = set()
        self.lock_ops = threading.Lock()
        self.ativo_locks = {}
        self.last_suspended_check = {}
        # ADX parameters
        self.adx_period = 14
        self.adx_limiar = 25
        self.setup_ui()
        self.setup_styles()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#f5f5f5')
        style.configure('TLabel', background='#f5f5f5', font=('Arial', 9))
        style.configure('TButton', font=('Arial', 9), padding=5)
        style.configure('TEntry', font=('Arial', 9))
        style.configure('TCombobox', font=('Arial', 9))
        style.configure('TCheckbutton', font=('Arial', 9))
        style.map('TButton',
                  foreground=[('active', 'black'), ('!disabled', 'black')],
                  background=[('active', '#e1e1e1'), ('!disabled', '#f0f0f0')])

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        conn_frame = ttk.LabelFrame(main_frame, text=" Conexão ", padding="10")
        conn_frame.grid(row=0, column=0, sticky="ew", pady=5, padx=5)
        ttk.Label(conn_frame, text="Email:").grid(row=0, column=0, sticky="e", padx=5)
        self.email_entry = ttk.Entry(conn_frame, width=30)
        self.email_entry.grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(conn_frame, text="Senha:").grid(row=0, column=2, sticky="e", padx=5)
        self.senha_entry = ttk.Entry(conn_frame, width=20, show="*")
        self.senha_entry.grid(row=0, column=3, sticky="w", padx=5)
        ttk.Label(conn_frame, text="Conta:").grid(row=0, column=4, sticky="e", padx=5)
        self.conta_combobox = ttk.Combobox(conn_frame, values=["PRACTICE", "REAL"], width=8, state="readonly")
        self.conta_combobox.current(0)
        self.conta_combobox.grid(row=0, column=5, sticky="w", padx=5)
        self.connect_button = ttk.Button(conn_frame, text="Conectar", command=self.conectar)
        self.connect_button.grid(row=0, column=6, padx=(10, 2))
        self.disconnect_button = ttk.Button(conn_frame, text="Desconectar", command=self.desconectar, state=tk.DISABLED)
        self.disconnect_button.grid(row=0, column=7, padx=(2, 10))
        config_frame = ttk.LabelFrame(main_frame, text=" Configurações ", padding="10")
        config_frame.grid(row=1, column=0, sticky="ew", pady=5, padx=5)
        ttk.Label(config_frame, text="Ativos Disponíveis:").grid(row=0, column=0, sticky="w", pady=2)
        self.ativos_listbox = tk.Listbox(config_frame, selectmode=tk.MULTIPLE, height=10, width=25,
                                       bg="white", fg="black", selectbackground="#0078d7",
                                       font=('Arial', 9))
        self.ativos_listbox.grid(row=1, column=0, rowspan=6, sticky="ns", padx=5)
        scrollbar = ttk.Scrollbar(config_frame, orient="vertical", command=self.ativos_listbox.yview)
        scrollbar.grid(row=1, column=1, rowspan=6, sticky="ns")
        self.ativos_listbox.config(yscrollcommand=scrollbar.set)
        ttk.Label(config_frame, text="Valor ($):").grid(row=1, column=2, sticky="e", pady=2)
        self.valor_entry = ttk.Entry(config_frame, width=10)
        self.valor_entry.insert(0, "25")
        self.valor_entry.grid(row=1, column=3, sticky="w", pady=2)
        ttk.Label(config_frame, text="Expiração (min):").grid(row=2, column=2, sticky="e", pady=2)
        self.expiry_combobox = ttk.Combobox(config_frame, values=["1"], width=5, state="readonly")
        self.expiry_combobox.current(0)
        self.expiry_combobox.grid(row=2, column=3, sticky="w", pady=2)
        ttk.Label(config_frame, text="Entradas:").grid(row=3, column=2, sticky="e", pady=2)
        self.entradas_spinbox = ttk.Spinbox(config_frame, from_=1, to=100, width=5)
        self.entradas_spinbox.delete(0, tk.END)
        self.entradas_spinbox.insert(0, "3")
        self.entradas_spinbox.grid(row=3, column=3, sticky="w", pady=2)
        ttk.Label(config_frame, text="Soros (%):").grid(row=4, column=2, sticky="e", pady=2)
        self.soros_spinbox = ttk.Spinbox(config_frame, from_=0, to=100, width=5)
        self.soros_spinbox.delete(0, tk.END)
        self.soros_spinbox.insert(0, "50")
        self.soros_spinbox.grid(row=4, column=3, sticky="w", pady=2)
        self.operar_otc = tk.BooleanVar(value=True)
        self.otc_check = ttk.Checkbutton(config_frame, text="Incluir OTC", variable=self.operar_otc)
        self.otc_check.grid(row=5, column=2, columnspan=2, sticky="w", pady=2)
        self.martingale_var = tk.BooleanVar(value=True)
        self.martingale_check = ttk.Checkbutton(config_frame, text="Ativar Martingale", variable=self.martingale_var)
        self.martingale_check.grid(row=6, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(config_frame, text="Níveis de Martingale:").grid(row=7, column=0, sticky="e", pady=2)
        self.martingale_levels = ttk.Combobox(config_frame, values=["1"], width=5, state="readonly")
        self.martingale_levels.current(0)
        self.martingale_levels.grid(row=7, column=1, sticky="w", pady=2)
        self.lucro_stop_loss_var = tk.BooleanVar(value=False)
        self.lucro_stop_loss_check = ttk.Checkbutton(config_frame, text="Operar por Lucro/Stop Loss", variable=self.lucro_stop_loss_var)
        self.lucro_stop_loss_check.grid(row=8, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(config_frame, text="Limite de Lucro ($):").grid(row=9, column=0, sticky="e", pady=2)
        self.lucro_entry = ttk.Entry(config_frame, width=10)
        self.lucro_entry.grid(row=9, column=1, sticky="w", pady=2)
        ttk.Label(config_frame, text="Limite de Perda ($):").grid(row=10, column=0, sticky="e", pady=2)
        self.perda_entry = ttk.Entry(config_frame, width=10)
        self.perda_entry.grid(row=10, column=1, sticky="w", pady=2)
        ttk.Label(config_frame, text="Saldo Disponível:").grid(row=11, column=0, sticky="e", pady=2)
        self.saldo_label = ttk.Label(config_frame, text="0", width=10)
        self.saldo_label.grid(row=11, column=1, sticky="w", pady=2)
        self.update_saldo_button = ttk.Button(config_frame, text="Atualizar Saldo", command=self.atualizar_saldo)
        self.update_saldo_button.grid(row=11, column=2, sticky="w", padx=5)
        # ---- Parâmetros do ADX na interface ----
        adx_frame = ttk.LabelFrame(main_frame, text=" Indicador ADX ", padding="10")
        adx_frame.grid(row=1, column=1, sticky="ns", pady=5, padx=5, rowspan=2)
        ttk.Label(adx_frame, text="Período ADX:").grid(row=0, column=0, sticky="e", pady=2)
        self.adx_period_entry = ttk.Entry(adx_frame, width=5)
        self.adx_period_entry.insert(0, str(self.adx_period))
        self.adx_period_entry.grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(adx_frame, text="ADX Máximo (lateral):").grid(row=1, column=0, sticky="e", pady=2)
        self.adx_limiar_entry = ttk.Entry(adx_frame, width=5)
        self.adx_limiar_entry.insert(0, str(self.adx_limiar))
        self.adx_limiar_entry.grid(row=1, column=1, sticky="w", pady=2)
        # -----------------------------------------
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=2, column=0, pady=10)
        self.start_button = ttk.Button(control_frame, text="Iniciar Robô", command=self.iniciar_robo, state=tk.DISABLED)
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = ttk.Button(control_frame, text="Parar Robô", command=self.parar_robo, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(control_frame, text="Desconectado", foreground="red")
        self.status_label.pack(side=tk.LEFT, padx=10)
        stats_frame = ttk.LabelFrame(main_frame, text=" Estatísticas ", padding="10")
        stats_frame.grid(row=3, column=0, sticky="ew", pady=5, padx=5)
        stats = [
            ("Operações:", "ops_label"),
            ("Acertos:", "acertos_label"),
            ("Erros:", "erros_label"),
            ("Taxa:", "taxa_label")
        ]
        for i, (text, var) in enumerate(stats):
            ttk.Label(stats_frame, text=text).grid(row=0, column=i*2, sticky="e", padx=2)
            setattr(self, var, ttk.Label(stats_frame, text="0", width=7))
            getattr(self, var).grid(row=0, column=i*2+1, sticky="w", padx=2)
        log_frame = ttk.LabelFrame(main_frame, text=" Log ", padding="10")
        log_frame.grid(row=4, column=0, sticky="nsew", pady=5, padx=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, state=tk.DISABLED,
                                                wrap=tk.WORD, bg="black", fg="white",
                                                insertbackground="white", font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)

    # --- DEMAIS MÉTODOS ORIGINAIS ABAIXO ---

    def atualizar_saldo(self):
        try:
            if not self.api or not self.connected:
                self.log("API não conectada.")
                return
            saldo = self.api.get_balance()
            self.saldo_label.config(text=f"${saldo:.2f}")
        except Exception as e:
            self.log(f"Erro ao atualizar saldo: {str(e)}")

    def reconnect_api(self):
        try:
            if not self.api or not self.verificar_conexao():
                self.log("Reconectando à API...")
                email = self.email_entry.get().strip()
                senha = self.senha_entry.get().strip()
                self.api = IQ_Option(email, senha)
                check, reason = self.api.connect()
                if check:
                    self.api.change_balance(self.conta_tipo)
                    self.custom_assets = self.api.get_all_ACTIVES_OPCODE()
                    self.custom_assets["EURAUD-OTC"] = 77
                    self.custom_assets["EURCAD-OTC"] = 78
                    self.connected = True
                    self.log("Reconexão bem-sucedida")
                    time.sleep(1)
                else:
                    self.log(f"Falha na reconexão: {reason}")
                    self.connected = False
                    return False
            return True
        except Exception as e:
            self.log(f"Erro ao reconectar: {str(e)}")
            self.connected = False
            return False

    def verificar_conexao(self):
        if self.api and self.connected:
            return self.api.check_connect()
        return False

    def desconectar(self):
        if self.api:
            try:
                self.api.close()
            except Exception:
                pass
        self.api = None
        self.connected = False
        self.status_label.config(text="Desconectado", foreground="red")
        self.connect_button.config(state=tk.NORMAL)
        self.disconnect_button.config(state=tk.DISABLED)
        self.start_button.config(state=tk.DISABLED)
        self.log("Desconectado da corretora.")

    def get_candles_last_hour(self, ativo):
        try:
            current_time = self.api.get_server_timestamp() if self.api else int(time.time())
            candles = self.api.get_candles(ativo, 60, 60, current_time)
            if candles is None or len(candles) < 60:
                self.log(f"{ativo}: Não foi possível obter 60 velas para catalogação.")
                return []
            candles = sorted(candles, key=lambda x: x['from'])
            return candles
        except Exception as e:
            self.log(f"{ativo}: Erro ao buscar candles para catalogação: {e}")
            return []

    def direction(self, c):
        if c['close'] > c['open']:
            return 'alta'
        elif c['close'] < c['open']:
            return 'baixa'
        else:
            return 'doji'

    def calcular_indice_repeticao(self, candles):
        if len(candles) < 2:
            return 0, 0, 0
        repete = 0
        total = 0
        for i in range(1, len(candles)):
            prev = self.direction(candles[i-1])
            curr = self.direction(candles[i])
            if prev == 'doji' or curr == 'doji':
                continue
            if prev == curr:
                repete += 1
            total += 1
        percentual = (repete / total * 100) if total > 0 else 0
        return percentual, total, repete

    def mhi_catalog_and_log(self, ativo):
        candles = self.get_candles_last_hour(ativo)
        if not candles or len(candles) < 7:
            self.log(f"{ativo}: Não há candles suficientes para catalogação MHI.")
            return
        logs = []
        win_first = 0
        win_gale = 0
        loss = 0
        for i in range(0, len(candles) - 5 - 1):
            group = candles[i:i+5]
            if len(group) < 5:
                continue
            last_three = group[2:5]
            directions = [self.direction(c) for c in last_three]
            if 'doji' in directions:
                continue
            count_alta = directions.count('alta')
            count_baixa = directions.count('baixa')
            minoria = 'alta' if count_alta < count_baixa else 'baixa'
            candle6_idx = i+5
            candle7_idx = i+6
            if candle6_idx >= len(candles):
                break
            candle6_dir = self.direction(candles[candle6_idx])
            if candle6_dir == minoria:
                win_first += 1
                logs.append(f"[{datetime.datetime.fromtimestamp(candles[candle6_idx]['from']).strftime('%H:%M')}] WIN de primeira | Minoria: {minoria} | Direções: {directions}")
            else:
                if candle7_idx < len(candles):
                    candle7_dir = self.direction(candles[candle7_idx])
                    if candle7_dir == minoria:
                        win_gale += 1
                        logs.append(f"[{datetime.datetime.fromtimestamp(candles[candle7_idx]['from']).strftime('%H:%M')}] WIN com Gale | Minoria: {minoria} | Direções: {directions}")
                    else:
                        loss += 1
                        logs.append(f"[{datetime.datetime.fromtimestamp(candles[candle7_idx]['from']).strftime('%H:%M')}] LOSS | Minoria: {minoria} | Direções: {directions}")
                else:
                    loss += 1
                    logs.append(f"[{datetime.datetime.fromtimestamp(candles[candle6_idx]['from']).strftime('%H:%M')}] LOSS (sem gale possível) | Minoria: {minoria} | Direções: {directions}")
        total = win_first + win_gale + loss
        assertividade = (win_first + win_gale) / total * 100 if total > 0 else 0
        resumo = (
            f"\nResumo da catalogação última hora [{ativo}]:\n"
            f"Wins de primeira: {win_first}\n"
            f"Wins com gale: {win_gale}\n"
            f"Loss: {loss}\n"
            f"Assertividade: {assertividade:.2f}%\n"
            f"Total operações simuladas: {total}\n"
        )
        for logmsg in logs:
            self.log(logmsg)
        self.log(resumo)
        percent_rept, total_rept, repete = self.calcular_indice_repeticao(candles)
        self.log(f"[{ativo}] Índice de repetição de velas: {percent_rept:.2f}% ({repete}/{total_rept})")
        self.mhi_catalog_info[ativo] = {
            'win_first': win_first,
            'win_gale': win_gale,
            'loss': loss,
            'assertividade': assertividade,
            'indice_repeticao': percent_rept
        }

    def mhi_get_entry_signal(self, candles):
        if len(candles) < 5:
            return None
        group = candles[-5:]
        last_three = group[2:5]
        directions = [self.direction(c) for c in last_three]
        if 'doji' in directions:
            return None
        count_alta = directions.count('alta')
        count_baixa = directions.count('baixa')
        minoria = 'alta' if count_alta < count_baixa else 'baixa'
        return 'call' if minoria == 'alta' else 'put'

    def executar_operacao(self, ativo, sinal):
        try:
            if not self.api or not self.connected:
                self.log("API não inicializada.")
                return False
            if ativo in self.suspended_assets:
                self.log(f"{ativo}: Ativo suspenso para operações.")
                return False
            valor = self.get_current_value(ativo)
            exp = int(self.expiry_combobox.get())
            saldo = self.api.get_balance()
            if saldo < valor:
                self.log(f"Erro: Saldo insuficiente para operação em {ativo}.")
                return False
            check, operation_id = self.api.buy(valor, ativo, sinal, exp)
            if check:
                with self.lock_ops:
                    self.active_operations[operation_id] = {'ativo': ativo, 'sinal': sinal, 'valor': valor}
                self.operacoes_realizadas[ativo] = self.operacoes_realizadas.get(ativo, 0) + 1
                self.atualizar_estatisticas()
                self.log(f"Operação iniciada: {sinal.upper()} em {ativo} com valor ${valor:.2f} e expiração {exp} minutos. ID: {operation_id}")
                return True
            else:
                self.log(f"Falha ao executar operação em {ativo}: {operation_id}")
                if operation_id and "active is suspended" in str(operation_id).lower():
                    self.suspended_assets.add(ativo)
                    self.last_suspended_check[ativo] = time.time()
                return False
        except Exception as e:
            self.log(f"Erro ao executar operação em {ativo}: {str(e)}")
            return False

    def existe_operacao_pendente(self, ativo):
        with self.lock_ops:
            for op in self.active_operations.values():
                if op['ativo'] == ativo:
                    return True
        return False

    def check_finished_operations_loop(self):
        while self.running:
            self.check_finished_operations()
            time.sleep(1)

    def check_finished_operations(self):
        try:
            if not self.api or not self.reconnect_api():
                return
            op_ids = []
            with self.lock_ops:
                op_ids = list(self.active_operations.keys())
            for op_id in op_ids:
                with self.lock_ops:
                    if op_id in self.processed_ops:
                        continue
                resultado_finalizado = False
                for attempt in range(60):
                    try:
                        result = self.api.check_win_v3(op_id)
                        if result is not None and result != op_id:
                            with self.lock_ops:
                                if op_id in self.processed_ops:
                                    break
                                ativo = self.active_operations[op_id]['ativo']
                                if result > 0:
                                    self.total_acertos += 1
                                    last_result = 'win'
                                    self.log(f"Operação {op_id} em {ativo} finalizada: WIN (lucro: ${result:.2f})")
                                else:
                                    self.total_erros += 1
                                    last_result = 'loss'
                                    self.log(f"Operação {op_id} em {ativo} finalizada: LOSS (valor: ${self.active_operations[op_id]['valor']:.2f})")
                                self.update_operation_status(ativo, last_result, op_id)
                                self.atualizar_estatisticas()
                                self.processed_ops.add(op_id)
                                del self.active_operations[op_id]
                            resultado_finalizado = True
                            break
                        result_alt = self.api.check_win(op_id)
                        if result_alt is not None and result_alt != op_id:
                            with self.lock_ops:
                                if op_id in self.processed_ops:
                                    break
                                ativo = self.active_operations[op_id]['ativo']
                                if result_alt > 0:
                                    self.total_acertos += 1
                                    last_result = 'win'
                                    self.log(f"Operação {op_id} em {ativo} finalizada: WIN (lucro: ${result_alt:.2f})")
                                else:
                                    self.total_erros += 1
                                    last_result = 'loss'
                                    self.log(f"Operação {op_id} em {ativo} finalizada: LOSS (valor: ${self.active_operations[op_id]['valor']:.2f})")
                                self.update_operation_status(ativo, last_result, op_id)
                                self.atualizar_estatisticas()
                                self.processed_ops.add(op_id)
                                del self.active_operations[op_id]
                            resultado_finalizado = True
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)
                if not resultado_finalizado:
                    with self.lock_ops:
                        if op_id in self.active_operations:
                            ativo = self.active_operations[op_id]['ativo']
                            self.log(f"Operação {op_id} em {ativo} não finalizada após 60 tentativas. Removendo da fila de pendentes para não travar o robô.")
                            self.processed_ops.add(op_id)
                            del self.active_operations[op_id]
        except Exception as e:
            self.log(f"Erro ao verificar operações finalizadas: {str(e)}")

    def get_current_value(self, ativo):
        return self.operacoes_per_ativo.get(ativo, {'current_value': float(self.valor_entry.get())})['current_value']

    def parar_robo(self):
        motivo = "Manual" if self.running else "Automático"
        self.running = False
        try:
            self.check_finished_operations()
        except Exception as e:
            self.log(f"Erro ao verificar operações pendentes: {str(e)}")
        with self.lock_ops:
            if self.active_operations:
                self.log(f"Operações pendentes não finalizadas: {list(self.active_operations.keys())}")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_label.config(text="Parado", foreground="red")
        self.log(f"=== OPERAÇÃO ENCERRADA === Motivo: {motivo}")

    def conectar(self):
        email = self.email_entry.get().strip()
        senha = self.senha_entry.get().strip()
        if not email or not senha:
            messagebox.showerror("Erro", "Email e senha são obrigatórios")
            return
        self.log(f"Conectando como {email}...")
        try:
            self.api = IQ_Option(email, senha)
            check, reason = self.api.connect()
            if check:
                self.conta_tipo = self.conta_combobox.get()
                self.api.change_balance(self.conta_tipo)
                self.connected = True
                self.status_label.config(text="Conectado", foreground="green")
                self.connect_button.config(state=tk.DISABLED)
                self.disconnect_button.config(state=tk.NORMAL)
                self.start_button.config(state=tk.NORMAL)
                self.log(f"Conectado com sucesso! Conta: {self.conta_tipo}")
                self.custom_assets = self.api.get_all_ACTIVES_OPCODE()
                self.custom_assets["EURAUD-OTC"] = 77
                self.custom_assets["EURCAD-OTC"] = 78
                time.sleep(1)
                self.atualizar_ativos_disponiveis()
            else:
                self.log(f"Falha na conexão: {reason}")
                messagebox.showerror("Erro", f"Falha na conexão: {reason}")
                self.connected = False
                self.connect_button.config(state=tk.NORMAL)
                self.disconnect_button.config(state=tk.DISABLED)
        except Exception as e:
            self.log(f"Erro na conexão: {str(e)}")
            messagebox.showerror("Erro", f"Falha na conexão: {str(e)}")
            self.connected = False
            self.connect_button.config(state=tk.NORMAL)
            self.disconnect_button.config(state=tk.DISABLED)

    def atualizar_ativos_disponiveis(self):
        try:
            if not self.api:
                self.log("Erro: API não inicializada.")
                return
            if not self.connected:
                self.log("Erro: API não conectada.")
                return
            if not self.api.check_connect():
                self.log("Erro: Conexão com a API perdida.")
                return
            try:
                activos = self.api.get_all_ACTIVES_OPCODE()
                if activos:
                    novos_ativos = [ativo for ativo in activos.keys() if self.operar_otc.get() or not ativo.endswith('-OTC')]
                else:
                    novos_ativos = ["EURUSD-OTC"] if self.operar_otc.get() else []
            except Exception as fallback_error:
                novos_ativos = ["EURUSD-OTC"] if self.operar_otc.get() else []
            self.ativos_disponiveis = sorted(novos_ativos)
            self.ativos_selecionados = [a for a in self.ativos_selecionados if a in self.ativos_disponiveis]
            if not self.ativos_selecionados and "EURUSD-OTC" in self.ativos_disponiveis:
                self.ativos_selecionados = ["EURUSD-OTC"]
                self.log("Selecionado EURUSD-OTC como padrão")
            self.carregar_ativos()
            self.log(f"Ativos atualizados: {len(self.ativos_disponiveis)} disponíveis")
            self.log(f"Ativos disponíveis: {self.ativos_disponiveis}")
        except Exception as e:
            self.log(f"Erro ao atualizar ativos: {str(e)}")
            if self.reconnect_api():
                time.sleep(5)
                self.atualizar_ativos_disponiveis()

    def carregar_ativos(self):
        self.ativos_listbox.delete(0, tk.END)
        for ativo in sorted(self.ativos_disponiveis):
            self.ativos_listbox.insert(tk.END, ativo)

    def obter_ativos_selecionados(self):
        selecionados = [self.ativos_listbox.get(i) for i in self.ativos_listbox.curselection()]
        return selecionados

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"
        try:
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, log_message)
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
            logger.info(message)
        except Exception as e:
            print(f"Erro no log: {e}\n{log_message}")

    def atualizar_estatisticas(self):
        total_ops = sum(self.operacoes_realizadas.values())
        self.ops_label.config(text=str(total_ops))
        self.acertos_label.config(text=str(self.total_acertos))
        self.erros_label.config(text=str(self.total_erros))
        if total_ops > 0:
            taxa = (self.total_acertos / total_ops) * 100
            self.taxa_label.config(text=f"{taxa:.1f}%")
        else:
            self.taxa_label.config(text="0%")

    def update_operation_status(self, ativo, last_result, opid=None):
        initial_value = float(self.valor_entry.get())
        info = self.operacoes_per_ativo[ativo]
        if last_result == 'win':
            if info['martingale_level'] > 0:
                info['current_value'] = info['soros_base_value']
                info['martingale_level'] = 0
                self.martingale_status.pop(ativo, None)
                self.log(f"Martingale WIN em {ativo}. Voltando valor para base do Soros (${info['current_value']:.2f})")
            if self.soros_spinbox.get() and float(self.soros_spinbox.get()) > 0:
                soros_percent = float(self.soros_spinbox.get())
                info['current_value'] *= (1 + soros_percent / 100)
                info['soros_base_value'] = info['current_value']
                self.log(f"Soros aplicado em {ativo}: Novo valor base do Soros ${info['current_value']:.2f}")
            else:
                info['soros_base_value'] = info['current_value']
            info['martingale_level'] = 0
            self.martingale_status.pop(ativo, None)
        elif last_result == 'loss' and self.martingale_var.get():
            max_levels = 1
            if info['martingale_level'] < max_levels:
                info['current_value'] *= 2
                info['martingale_level'] += 1
                self.log(f"Martingale aplicado em {ativo}: Nível {info['martingale_level']}, Novo valor ${info['current_value']:.2f}")
                last_op = None
                if opid and opid in self.active_operations:
                    last_op = self.active_operations[opid]
                else:
                    for _opid, opdata in self.active_operations.items():
                        if opdata['ativo'] == ativo:
                            last_op = opdata
                if last_op:
                    self.martingale_status[ativo] = {
                        'direcao': last_op['sinal'],
                        'nivel': info['martingale_level'],
                        'ciclo_mg': None
                    }
            else:
                info['current_value'] = initial_value
                info['soros_base_value'] = initial_value
                info['martingale_level'] = 0
                self.martingale_status.pop(ativo, None)
                self.log(f"Martingale resetado em {ativo}: Novo valor ${initial_value:.2f}")
        else:
            info['current_value'] = initial_value
            info['soros_base_value'] = initial_value
            info['martingale_level'] = 0
            self.martingale_status.pop(ativo, None)

    def on_closing(self):
        if messagebox.askokcancel("Sair", "Deseja realmente sair?"):
            self.running = False
            self.parar_robo()
            self.desconectar()
            self.root.destroy()
            sys.exit()

    def iniciar_robo(self):
        if not self.connected:
            messagebox.showerror("Erro", "Conecte-se primeiro")
            return
        self.ativos_selecionados = self.obter_ativos_selecionados()
        if not self.ativos_selecionados:
            messagebox.showerror("Erro", "Selecione pelo menos um ativo")
            return
        self.ativos_selecionados = [a for a in self.ativos_selecionados if a in self.ativos_disponiveis]
        if not self.ativos_selecionados:
            self.ativos_selecionados = ["EURUSD-OTC"]
            self.log("Nenhum ativo válido selecionado. Usando EURUSD-OTC como padrão.")
        initial_value = float(self.valor_entry.get())
        self.operacoes_per_ativo = {
            ativo: {
                'current_value': initial_value,
                'martingale_level': 0,
                'soros_base_value': initial_value
            }
            for ativo in self.ativos_selecionados
        }
        self.operacoes_realizadas = {ativo: 0 for ativo in self.ativos_selecionados}
        self.suspended_assets.clear()
        self.last_signal_bar.clear()
        self.last_candles.clear()
        self.total_acertos = 0
        self.total_erros = 0
        self.running = True
        self.ativo_locks = {ativo: threading.Lock() for ativo in self.ativos_selecionados}
        self.last_suspended_check = {}
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_label.config(text="Operando", foreground="green")
        self.log("\n=== INÍCIO DA OPERAÇÃO (MHI) ===")
        self.log(f"Conta: {'DEMO' if self.conta_tipo == 'PRACTICE' else 'REAL'}")
        self.log(f"Ativos: {', '.join(self.ativos_selecionados)}")
        self.log(f"Valor: ${float(self.valor_entry.get()):.2f}")
        self.log(f"Expiração: {self.expiry_combobox.get()} min")
        self.log(f"Entradas: {self.entradas_spinbox.get()}")
        self.log(f"Soros: {self.soros_spinbox.get()}%")
        self.log(f"OTC: {'SIM' if self.operar_otc.get() else 'NÃO'}")
        self.log("========================")
        for ativo in self.ativos_selecionados:
            self.log(f"Iniciando catalogação MHI para {ativo}...")
            self.mhi_catalog_and_log(ativo)
        self.log("Aguardando fechamento do próximo quadrante de 5 velas para iniciar operações...")
        max_wait = 360
        delays = []
        for ativo in self.ativos_selecionados:
            candles = self.get_candles_last_hour(ativo)
            if not candles:
                delays.append(60)
                continue
            last_candle_time = candles[-1]['from']
            last_minute = datetime.datetime.fromtimestamp(last_candle_time).minute
            wait_min = (5 - (last_minute % 5)) % 5
            if wait_min == 0:
                wait_min = 5
            now = datetime.datetime.now(datetime.timezone.utc)
            seconds_past = now.second
            delay = wait_min * 60 - seconds_past
            delays.append(max(10, min(delay, max_wait)))
        wait_time = max(delays) if delays else 60
        self.log(f"Aguardando {int(wait_time/60)}min {wait_time%60:.0f}s para começar a operar no próximo quadrante.")
        self.root.after(int(wait_time * 1000), self._iniciar_threads_operacao)

    def _iniciar_threads_operacao(self):
        threading.Thread(target=self.loop_operacoes_primeiro_ciclo, daemon=True).start()
        threading.Thread(target=self.check_finished_operations_loop, daemon=True).start()

    def loop_operacoes_primeiro_ciclo(self):
        self.loop_operacoes(ciclo_rapido=True)

    def loop_operacoes(self, ciclo_rapido=False):
        try:
            self.adx_period = int(self.adx_period_entry.get())
            self.adx_limiar = float(self.adx_limiar_entry.get())
        except Exception:
            self.adx_period = 14
            self.adx_limiar = 25

        max_entradas = int(self.entradas_spinbox.get())
        lucro_alvo = float(self.lucro_entry.get()) if self.lucro_entry.get() else float('inf')
        perda_alvo = float(self.perda_entry.get()) if self.perda_entry.get() else float('inf')
        saldo_inicial = self.api.get_balance() if self.api else 0

        last_cycle = {ativo: None for ativo in self.ativos_selecionados}
        ultimo_sinal_operado = {}

        while self.running:
            if self.lucro_stop_loss_var.get():
                saldo_atual = self.api.get_balance() if self.api else 0
                if saldo_atual >= saldo_inicial + lucro_alvo:
                    self.log(f"Lucro alvo de ${lucro_alvo:.2f} atingido. Parando operações.")
                    self.parar_robo()
                    return
                elif saldo_atual <= saldo_inicial - perda_alvo:
                    self.log(f"Perda alvo de ${perda_alvo:.2f} atingido. Parando operações.")
                    self.parar_robo()
                    return
            all_ativos_limitados = all(self.operacoes_realizadas.get(ativo, 0) >= max_entradas for ativo in self.ativos_selecionados)
            if not self.lucro_stop_loss_var.get() and all_ativos_limitados:
                self.log("Número máximo de entradas atingido em todos os ativos. Parando o robô.")
                self.parar_robo()
                return

            for ativo in self.ativos_selecionados:
                if not self.running:
                    break
                with self.ativo_locks[ativo]:
                    now = datetime.datetime.now(datetime.timezone.utc)
                    now_ts = time.time()
                    if ativo in self.suspended_assets:
                        last_try = self.last_suspended_check.get(ativo, 0)
                        if now_ts - last_try > 60:
                            open_times = self.api.get_all_open_time()
                            ativo_type = 'turbo' if "-OTC" in ativo else 'binary'
                            ativo_base = ativo.replace("-OTC", "")
                            is_open = False
                            if ativo in open_times.get(ativo_type, {}):
                                is_open = open_times[ativo_type][ativo]["open"]
                            elif ativo_base in open_times.get(ativo_type, {}):
                                is_open = open_times[ativo_type][ativo_base]["open"]
                            if is_open:
                                self.suspended_assets.remove(ativo)
                                self.log(f"{ativo}: Ativo reaberto, liberando operações.")
                            else:
                                self.log(f"{ativo}: Ainda suspenso para operações, aguardando liberação...")
                            self.last_suspended_check[ativo] = now_ts
                        continue

                    if not self.lucro_stop_loss_var.get() and self.operacoes_realizadas.get(ativo, 0) >= max_entradas:
                        continue

                    # Otimizado para operar a cada minuto (M1)
                    if now.second != 0:
                        continue

                    # Usa pelo menos 20 candles para cálculo do ADX mais confiável (mínimo adx_period+6)
                    num_candles = max(20, self.adx_period + 6)
                    candles = self.api.get_candles(ativo, 60, num_candles, int(time.time()))
                    if not candles or len(candles) < self.adx_period + 5:
                        self.log(f"{ativo}: Não foi possível obter candles suficientes para operação MHI+ADX.")
                        continue

                    candles = sorted(candles, key=lambda x: x['from'])
                    # Calcula ADX usando os últimos candles
                    adx, plus_di, minus_di = calculate_adx(candles[-(self.adx_period+1):], period=self.adx_period)
                    if adx is None:
                        self.log(f"{ativo}: Não foi possível calcular ADX (insuficiente candles). Pulando operação.")
                        continue

                    self.log(f"{ativo}: ADX={adx:.2f}, +DI={plus_di:.2f}, -DI={minus_di:.2f}")

                    if adx > self.adx_limiar:
                        self.log(f"{ativo}: Mercado com tendência (ADX>{self.adx_limiar}), aguardando lateralização para operar.")
                        continue  # Só opera se mercado lateral

                    # Segue lógica MHI para entrada
                    sinal = self.mhi_get_entry_signal(candles)
                    if not sinal:
                        continue

                    ciclo_operado = ultimo_sinal_operado.get((ativo, sinal))
                    current_cycle = (now.hour, now.minute)
                    if ciclo_operado == current_cycle:
                        continue

                    if self.existe_operacao_pendente(ativo):
                        continue

                    self.log(f"MHI+ADX: Sinal {sinal.upper()} em {ativo} (ADX={adx:.2f}), tentando executar operação")
                    if self.executar_operacao(ativo, sinal):
                        self.martingale_status.pop(ativo, None)
                        last_cycle[ativo] = current_cycle
                        ultimo_sinal_operado[(ativo, sinal)] = current_cycle
                        time.sleep(1 if ciclo_rapido else 5)
                    time.sleep(0.2 if ciclo_rapido else 0.5)

            time.sleep(0.2 if ciclo_rapido else 2)
            ciclo_rapido = False

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = IQFimatheBot(root)
        root.mainloop()
    except Exception as e:
        logger.error(f"Erro fatal: {str(e)}")
        sys.exit(1)