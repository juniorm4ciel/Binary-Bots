import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import time
from datetime import datetime
from iqoptionapi.stable_api import IQ_Option
import logging
import sys
import threading
import traceback
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class IQFimatheBot:
    def __init__(self, root):
        self.root = root
        self.root.title("Robô Power Boss ADX v1.0")
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

        # Conexão
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
        self.connect_button.grid(row=0, column=6, padx=10)

        # Configuração
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
        self.expiry_combobox = ttk.Combobox(config_frame, values=["1", "2", "5"], width=5, state="readonly")
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
        self.martingale_levels = ttk.Combobox(config_frame, values=["1", "2", "3"], width=5, state="readonly")
        self.martingale_levels.current(1)
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

        # Controle
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=2, column=0, pady=10)
        self.start_button = ttk.Button(control_frame, text="Iniciar Robô", command=self.iniciar_robo, state=tk.DISABLED)
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = ttk.Button(control_frame, text="Parar Robô", command=self.parar_robo, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(control_frame, text="Desconectado", foreground="red")
        self.status_label.pack(side=tk.LEFT, padx=10)

        # Estatísticas
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

        # Log
        log_frame = ttk.LabelFrame(main_frame, text=" Log ", padding="10")
        log_frame.grid(row=4, column=0, sticky="nsew", pady=5, padx=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, state=tk.DISABLED,
                                                wrap=tk.WORD, bg="black", fg="white",
                                                insertbackground="white", font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)

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

    # ---------------- POWER BOSS ADX LOGIC -----------------

    def compute_adx(self, candles, length=14):
        highs = np.array([c['max'] for c in candles])
        lows = np.array([c['min'] for c in candles])
        closes = np.array([c['close'] for c in candles])

        plus_dm = np.zeros_like(highs)
        minus_dm = np.zeros_like(highs)
        tr = np.zeros_like(highs)

        for i in range(1, len(highs)):
            up_move = highs[i] - highs[i-1]
            down_move = lows[i-1] - lows[i]
            plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0
            minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )

        plus_di = np.zeros_like(highs)
        minus_di = np.zeros_like(highs)
        adx = np.zeros_like(highs)

        for i in range(length, len(highs)):
            sum_tr = np.sum(tr[i-length+1:i+1])
            sum_plus_dm = np.sum(plus_dm[i-length+1:i+1])
            sum_minus_dm = np.sum(minus_dm[i-length+1:i+1])
            plus_di[i] = 100 * (sum_plus_dm / sum_tr) if sum_tr != 0 else 0
            minus_di[i] = 100 * (sum_minus_dm / sum_tr) if sum_tr != 0 else 0
            dxs = []
            for j in range(i-length+1, i+1):
                den = plus_di[j] + minus_di[j]
                dxs.append(abs(plus_di[j] - minus_di[j]) / den * 100 if den != 0 else 0)
            adx[i] = np.mean(dxs)
        adx_val = adx[-1] if len(adx) > 0 else 0
        return adx_val

    def is_doji(self, c):
        corpo = abs(c['close'] - c['open'])
        total = c['max'] - c['min']
        if total == 0:
            return True
        return corpo <= total * 0.1

    def check_tiebreaker(self, candles):
        c = lambda i: candles[i]['close']
        o = lambda i: candles[i]['open']
        # Os principais padrões do script, pode expandir conforme necessário
        # Os índices: candles[0] é a mais antiga, candles[5] é a mais recente
        padroes = [
            # Exemplo: 3 altas, 3 baixas
            (lambda: c(0)>o(0) and c(1)>o(1) and c(2)>o(2) and c(3)<o(3) and c(4)<o(4) and c(5)<o(5), -1),
            (lambda: c(0)>o(0) and c(1)>o(1) and c(2)<o(2) and c(3)>o(3) and c(4)<o(4) and c(5)<o(5), -1),
            (lambda: c(0)>o(0) and c(1)>o(1) and c(2)<o(2) and c(3)<o(3) and c(4)>o(4) and c(5)<o(5), -1),
            (lambda: c(0)>o(0) and c(1)>o(1) and c(2)<o(2) and c(3)<o(3) and c(4)<o(4) and c(5)>o(5), 1),
            (lambda: c(0)>o(0) and c(1)<o(1) and c(2)>o(2) and c(3)>o(3) and c(4)<o(4) and c(5)<o(5), -1),
            (lambda: c(0)>o(0) and c(1)<o(1) and c(2)>o(2) and c(3)<o(3) and c(4)>o(4) and c(5)<o(5), -1),
            (lambda: c(0)>o(0) and c(1)<o(1) and c(2)>o(2) and c(3)<o(3) and c(4)<o(4) and c(5)>o(5), 1),
            (lambda: c(0)>o(0) and c(1)<o(1) and c(2)<o(2) and c(3)>o(3) and c(4)>o(4) and c(5)<o(5), -1),
            (lambda: c(0)>o(0) and c(1)<o(1) and c(2)<o(2) and c(3)>o(3) and c(4)<o(4) and c(5)>o(5), 1),
            (lambda: c(0)>o(0) and c(1)<o(1) and c(2)<o(2) and c(3)<o(3) and c(4)>o(4) and c(5)>o(5), 1)
            # ... e assim por diante, conforme script
        ]
        for cond, direcao in padroes:
            try:
                if cond():
                    return direcao
            except Exception:
                continue
        return 0

    def verificar_sinais_powerboss(self, ativo):
        try:
            if not self.api or not self.connected:
                self.log("API não inicializada.")
                return None

            current_time = self.api.get_server_timestamp() if self.api else time.time()
            candles = self.api.get_candles(ativo, 60, 20, current_time)
            if candles is None or len(candles) < 20:
                return None
            candles = sorted(candles, key=lambda x: x['from'])
            adx_len = 14
            adx_thresh = 25.0
            adx_val = self.compute_adx(candles, length=adx_len)
            if adx_val >= adx_thresh:
                return None

            last_bar = self.last_signal_bar.get(ativo, -100)
            current_bar = candles[-1]['from'] // 60
            if current_bar - last_bar < 12:
                return None

            last6 = candles[-6:]
            if any(self.is_doji(c) for c in last6):
                return None

            up = sum(1 for c in last6 if c['close'] > c['open'])
            down = sum(1 for c in last6 if c['close'] < c['open'])

            direction = 0
            if up > down:
                direction = 1
            elif down > up:
                direction = -1
            else:
                direction = self.check_tiebreaker(last6)

            if direction != 0:
                self.last_signal_bar[ativo] = current_bar
                return 'call' if direction == 1 else 'put'
            return None
        except Exception as e:
            self.log(f"Erro ao verificar sinais Power Boss ADX para {ativo}: {str(e)}")
            return None

    # --------------------------------------------------------

    def executar_operacao(self, ativo, sinal):
        try:
            if not self.api or not self.connected:
                self.log("API não inicializada.")
                return False
            if ativo in self.suspended_assets:
                return False
            valor = self.get_current_value(ativo)
            exp = int(self.expiry_combobox.get())
            saldo = self.api.get_balance()
            if saldo < valor:
                self.log(f"Erro: Saldo insuficiente para operação em {ativo}.")
                return False
            check, operation_id = self.api.buy(valor, ativo, sinal, exp)
            if check:
                self.active_operations[operation_id] = {'ativo': ativo, 'sinal': sinal, 'valor': valor}
                self.operacoes_realizadas[ativo] = self.operacoes_realizadas.get(ativo, 0) + 1
                self.atualizar_estatisticas()
                self.log(f"Operação iniciada: {sinal.upper()} em {ativo} com valor ${valor:.2f} e expiração {exp} minutos. ID: {operation_id}")
                return True
            else:
                if 'active is suspended' in str(operation_id).lower():
                    self.suspended_assets.add(ativo)
                return False
        except Exception as e:
            self.log(f"Erro ao executar operação em {ativo}: {str(e)}")
            return False

    def existe_operacao_pendente(self, ativo):
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
            for op_id in list(self.active_operations.keys()):
                for attempt in range(60):
                    try:
                        result = self.api.check_win_v3(op_id)
                        if result is not None:
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
                            del self.active_operations[op_id]
                            break
                        result_alt = self.api.check_win(op_id)
                        if result_alt is not None:
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
                            del self.active_operations[op_id]
                            break
                    except Exception as e:
                        self.log(f"Erro ao verificar operação {op_id} na tentativa {attempt + 1}: {str(e)}")
                    time.sleep(0.5)
                else:
                    self.log(f"Operação {op_id} não finalizada após 60 tentativas")
        except Exception as e:
            self.log(f"Erro ao verificar operações finalizadas: {str(e)}")

    def get_current_value(self, ativo):
        return self.operacoes_per_ativo.get(ativo, {'current_value': float(self.valor_entry.get())})['current_value']

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
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_label.config(text="Operando", foreground="green")
        self.log("\n=== INÍCIO DA OPERAÇÃO ===")
        self.log(f"Conta: {'DEMO' if self.conta_tipo == 'PRACTICE' else 'REAL'}")
        self.log(f"Ativos: {', '.join(self.ativos_selecionados)}")
        self.log(f"Valor: ${float(self.valor_entry.get()):.2f}")
        self.log(f"Expiração: {self.expiry_combobox.get()} min")
        self.log(f"Entradas: {self.entradas_spinbox.get()}")
        self.log(f"Soros: {self.soros_spinbox.get()}%")
        self.log(f"OTC: {'SIM' if self.operar_otc.get() else 'NÃO'}")
        self.log("========================")
        threading.Thread(target=self.loop_operacoes, daemon=True).start()
        threading.Thread(target=self.check_finished_operations_loop, daemon=True).start()

    def parar_robo(self):
        motivo = "Manual" if self.running else "Automático"
        self.running = False
        self.log(f"Encerrando operação: {motivo}. Verificando operações pendentes...")
        try:
            self.check_finished_operations()
        except Exception as e:
            self.log(f"Erro ao verificar operações pendentes: {str(e)}")
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
        except Exception as e:
            self.log(f"Erro na conexão: {str(e)}")
            messagebox.showerror("Erro", f"Falha na conexão: {str(e)}")
            self.connected = False

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
        timestamp = datetime.now().strftime("%H:%M:%S")
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
        # Se ganhou:
        if last_result == 'win':
            # Se estava em martingale, reseta para o valor base do Soros ANTES do gale
            if info['martingale_level'] > 0:
                info['current_value'] = info['soros_base_value']
                info['martingale_level'] = 0
                self.martingale_status.pop(ativo, None)
                self.log(f"Martingale WIN em {ativo}. Voltando valor para base do Soros (${info['current_value']:.2f})")
            # Aplica Soros SEMPRE sobre o valor base, nunca sobre o valor do gale
            if self.soros_spinbox.get() and float(self.soros_spinbox.get()) > 0:
                soros_percent = float(self.soros_spinbox.get())
                info['current_value'] *= (1 + soros_percent / 100)
                info['soros_base_value'] = info['current_value']  # Atualiza a base do Soros
                self.log(f"Soros aplicado em {ativo}: Novo valor base do Soros ${info['current_value']:.2f}")
            else:
                info['soros_base_value'] = info['current_value']
            # Garante que martingale está zerado
            info['martingale_level'] = 0
            self.martingale_status.pop(ativo, None)
        # Se perdeu:
        elif last_result == 'loss' and self.martingale_var.get():
            max_levels = int(self.martingale_levels.get())
            if info['martingale_level'] < max_levels:
                # Só dobra para o próximo martingale, NÃO mexe no soros_base_value!
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
                    }
            else:
                # Se perdeu tudo, reseta para o valor base do Soros
                info['current_value'] = initial_value
                info['soros_base_value'] = initial_value
                info['martingale_level'] = 0
                self.martingale_status.pop(ativo, None)
                self.log(f"Martingale resetado em {ativo}: Novo valor ${initial_value:.2f}")
        else:
            # Em qualquer outro caso, volta para o valor inicial
            info['current_value'] = initial_value
            info['soros_base_value'] = initial_value
            info['martingale_level'] = 0
            self.martingale_status.pop(ativo, None)

    def loop_operacoes(self):
        max_entradas = int(self.entradas_spinbox.get())
        lucro_alvo = float(self.lucro_entry.get()) if self.lucro_entry.get() else float('inf')
        perda_alvo = float(self.perda_entry.get()) if self.perda_entry.get() else float('inf')
        saldo_inicial = self.api.get_balance() if self.api else 0
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

            if not self.verificar_conexao():
                self.log("Aguardando reconexão...")
                time.sleep(5)
                continue

            all_ativos_limitados = all(self.operacoes_realizadas.get(ativo, 0) >= max_entradas for ativo in self.ativos_selecionados)
            if not self.lucro_stop_loss_var.get() and all_ativos_limitados:
                self.log("Número máximo de entradas atingido em todos os ativos. Parando o robô.")
                self.parar_robo()
                return

            for ativo in self.ativos_selecionados:
                if not self.running:
                    break
                if not self.lucro_stop_loss_var.get() and self.operacoes_realizadas.get(ativo, 0) >= max_entradas:
                    continue
                if ativo in self.martingale_status:
                    if not self.existe_operacao_pendente(ativo):
                        mg = self.martingale_status[ativo]
                        self.log(f"Entrando em Martingale Nível {mg['nivel']} para {ativo} na direção {mg['direcao'].upper()}")
                        if self.executar_operacao(ativo, mg['direcao']):
                            self.operacoes_per_ativo[ativo]['martingale_level'] = mg['nivel']
                        else:
                            self.log(f"Falha ao executar martingale para {ativo}")
                        time.sleep(5)
                    continue
                if not self.existe_operacao_pendente(ativo):
                    sinal = self.verificar_sinais_powerboss(ativo)
                    if sinal:
                        self.log(f"Sinal {sinal.upper()} em {ativo}, tentando executar operação")
                        if self.executar_operacao(ativo, sinal):
                            self.martingale_status.pop(ativo, None)
                            time.sleep(5)
                time.sleep(0.5)
            time.sleep(2)

    def on_closing(self):
        if messagebox.askokcancel("Sair", "Deseja realmente sair?"):
            self.running = False
            self.parar_robo()
            self.root.destroy()
            sys.exit()

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = IQFimatheBot(root)
        root.mainloop()
    except Exception as e:
        logger.error(f"Erro fatal: {str(e)}")
        sys.exit(1)