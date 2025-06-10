import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import time
from datetime import datetime, timedelta
from iqoptionapi.stable_api import IQ_Option
import logging
import sys
import threading
import numpy as np
from queue import Queue
import re

from telethon import TelegramClient, events

# ==== Logger global ====
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === PREENCHA SEUS DADOS DO TELEGRAM ===
API_ID = 24198120         # Substitua pelo seu api_id
API_HASH = '7d3fedaac2448f4650d760af0dc51393'  # Substitua pelo seu api_hash
TELEGRAM_CHAT = 'ok'  # Ex: '@canalsinaisbinarias' ou 'grupo_sinais'

def parse_telegram_signal(message):
    ativo_match = re.search(r'Ativo:\s*([A-Z/]+)', message, re.IGNORECASE)
    ativo = None
    if ativo_match:
        ativo_raw = ativo_match.group(1).replace("/", "")
        # Garante que sempre terá o sufixo -OTC
        if not ativo_raw.endswith("-OTC"):
            ativo = ativo_raw + "-OTC"
        else:
            ativo = ativo_raw

    # Direção
    direcao = None
    if "VENDA" in message.upper():
        direcao = "put"
    elif "COMPRA" in message.upper():
        direcao = "call"

    # Expiração
    expiracao_match = re.search(r'Expira\w*:\s*M(\d+)', message, re.IGNORECASE)
    expiracao = None
    if expiracao_match:
        expiracao = int(expiracao_match.group(1))

    # Horário de entrada (formato HH:MM)
    hora_match = re.search(r'Entrada:\s*(\d{2}:\d{2})', message)
    hora_entrada = hora_match.group(1) if hora_match else None

    return ativo, direcao, expiracao, hora_entrada

class IQFimatheBot:
    def __init__(self, root):
        self.root = root
        self.root.title("Robô Power Boss - Telegram Signals")
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
        self.martingale_status = {}
        self.signal_queue = Queue()
        self.setup_ui()
        self.setup_styles()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Inicia o listener do Telegram em uma thread separada, com event loop próprio
        threading.Thread(target=self.start_telegram_listener, daemon=True).start()

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

    def executar_operacao(self, ativo, sinal, expiracao=None):
        try:
            if not self.api or not self.connected:
                self.log("API não inicializada.")
                return False
            # Garante o sufixo -OTC
            if not ativo.endswith("-OTC"):
                ativo += "-OTC"
            valor = self.get_current_value(ativo)
            exp = int(self.expiry_combobox.get()) if expiracao is None else expiracao
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
        # Garante o sufixo -OTC
        if not ativo.endswith("-OTC"):
            ativo += "-OTC"
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
        # Garante o sufixo -OTC
        if not ativo.endswith("-OTC"):
            ativo += "-OTC"
        return self.operacoes_per_ativo.get(ativo, {'current_value': float(self.valor_entry.get())})['current_value']

    def iniciar_robo(self):
        if not self.connected:
            messagebox.showerror("Erro", "Conecte-se primeiro")
            return
        initial_value = float(self.valor_entry.get())
        self.operacoes_per_ativo = {}
        self.operacoes_realizadas = {}
        self.suspended_assets.clear()
        self.total_acertos = 0
        self.total_erros = 0
        self.running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_label.config(text="Operando", foreground="green")
        self.log("\n=== INÍCIO DA OPERAÇÃO POR SINAIS DO TELEGRAM ===")
        self.log(f"Conta: {'DEMO' if self.conta_tipo == 'PRACTICE' else 'REAL'}")
        self.log(f"Valor: ${float(self.valor_entry.get()):.2f}")
        self.log(f"Expiração: {self.expiry_combobox.get()} min")
        self.log(f"Entradas: {self.entradas_spinbox.get()}")
        self.log(f"Soros: {self.soros_spinbox.get()}%")
        self.log("========================")
        threading.Thread(target=self.loop_operacoes_telegram, daemon=True).start()
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
                self.disconnect_button.config(state=tk.NORMAL)
                self.start_button.config(state=tk.NORMAL)
                self.log(f"Conectado com sucesso! Conta: {self.conta_tipo}")
                time.sleep(1)
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
        # Garante o sufixo -OTC
        if not ativo.endswith("-OTC"):
            ativo += "-OTC"
        info = self.operacoes_per_ativo.get(ativo, {
            'current_value': initial_value,
            'martingale_level': 0,
            'soros_base_value': initial_value
        })
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
            max_levels = int(self.martingale_levels.get())
            if info['martingale_level'] < max_levels:
                info['current_value'] *= 2
                info['martingale_level'] += 1
                self.log(f"Martingale aplicado em {ativo}: Nível {info['martingale_level']}, Novo valor ${info['current_value']:.2f}")
                self.martingale_status[ativo] = {
                    'direcao': self.active_operations.get(opid, {}).get('sinal', 'call'),
                    'nivel': info['martingale_level'],
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
        self.operacoes_per_ativo[ativo] = info

    def loop_operacoes_telegram(self):
        initial_value = float(self.valor_entry.get())
        saldo_inicial = self.api.get_balance() if self.api else 0
        max_entradas = int(self.entradas_spinbox.get())
        lucro_alvo = float(self.lucro_entry.get()) if self.lucro_entry.get() else float('inf')
        perda_alvo = float(self.perda_entry.get()) if self.perda_entry.get() else float('inf')
        while self.running:
            try:
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

                # Aguarda sinal do Telegram na fila
                try:
                    ativo, direcao, expiracao, hora_entrada = self.signal_queue.get(timeout=1)
                except:
                    continue
                if not ativo or not direcao or not hora_entrada:
                    self.log("Sinal inválido ou sem horário de entrada, ignorando.")
                    continue
                ops = self.operacoes_realizadas.get(ativo, 0)
                if ops >= max_entradas:
                    self.log(f"Número máximo de entradas para {ativo} atingido. Ignorando sinal.")
                    continue
                # Inicializa estrutura para o ativo se necessário
                if ativo not in self.operacoes_per_ativo:
                    self.operacoes_per_ativo[ativo] = {
                        'current_value': initial_value,
                        'martingale_level': 0,
                        'soros_base_value': initial_value
                    }
                # == Espera até o horário de entrada ==
                now = datetime.now()
                hora, minuto = map(int, hora_entrada.split(":"))
                entrada_dt = now.replace(hour=hora, minute=minuto, second=0, microsecond=0)
                if entrada_dt < now:
                    self.log(f"Horário do sinal {hora_entrada} já passou, ignorando.")
                    continue
                segundos = (entrada_dt - now).total_seconds()
                self.log(f"Aguardando {int(segundos)} segundos até o horário de entrada {hora_entrada} para {ativo}...")
                while segundos > 0:
                    if not self.running:
                        return
                    if segundos > 10:
                        time.sleep(10)
                        segundos -= 10
                    else:
                        time.sleep(segundos)
                        break

                self.log(f"Sinal do Telegram: {direcao.upper()} em {ativo} (expiração: {expiracao if expiracao else self.expiry_combobox.get()} min)")

                if not self.existe_operacao_pendente(ativo):
                    if ativo in self.martingale_status:
                        mg = self.martingale_status[ativo]
                        self.log(f"Entrando em Martingale Nível {mg['nivel']} para {ativo} na direção {mg['direcao'].upper()}")
                        if self.executar_operacao(ativo, mg['direcao'], expiracao):
                            self.operacoes_per_ativo[ativo]['martingale_level'] = mg['nivel']
                        else:
                            self.log(f"Falha ao executar martingale para {ativo}")
                    else:
                        self.executar_operacao(ativo, direcao, expiracao)
                time.sleep(0.5)
            except Exception as e:
                self.log(f"Erro no loop de sinais do Telegram: {str(e)}")
                time.sleep(1)

    def start_telegram_listener(self):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = TelegramClient('anon', API_ID, API_HASH, loop=loop)
        @client.on(events.NewMessage(chats=TELEGRAM_CHAT))
        async def handler(event):
            text = event.raw_text.strip()
            ativo, direcao, expiracao, hora_entrada = parse_telegram_signal(text)
            if ativo and direcao and hora_entrada:
                self.signal_queue.put((ativo, direcao, expiracao, hora_entrada))
                self.log(f"Sinal adicionado à fila: {ativo} {direcao} exp:{expiracao} hora:{hora_entrada}")
        client.start()
        client.run_until_disconnected()

    def on_closing(self):
        if messagebox.askokcancel("Sair", "Deseja realmente sair?"):
            self.running = False
            self.parar_robo()
            self.desconectar()
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