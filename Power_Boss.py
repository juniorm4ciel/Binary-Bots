import tkinter as tk
from tkinter import ttk
import threading
import datetime
import sv_ttk
import time
import os
import json
import sys
from collections import deque

DEFAULT_SOUNDS = {
    "entry": "sounds/entrada.wav",
    "win":   "sounds/win.wav",
    "loss":  "sounds/loss.wav",
    "limit": "sounds/limit.wav",
    "conexao": "sounds/conexao.wav",
    "conexao_erro": "sounds/conexao_erro.wav"
}

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def play_sound(sound_file=None, freq=None, dur=None):
    if sound_file:
        sound_file = resource_path(sound_file)
        ext = os.path.splitext(sound_file)[1].lower()
        if ext == ".wav":
            try:
                import winsound
                winsound.PlaySound(sound_file, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            except Exception:
                pass
        try:
            import playsound
            playsound.playsound(sound_file, False)
        except Exception:
            pass
    elif freq and dur:
        try:
            import winsound
            winsound.Beep(freq, dur)
        except Exception:
            pass

def format_money(valor):
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")

def set_azure_theme(root, mode="dark"):
    try:
        sv_ttk.set_theme("dark" if mode == "dark" else "light")
    except ImportError:
        root.configure(bg="#222" if mode == "dark" else "#F5F6FA")

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
        self.api = None
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

    # Função para pegar ADX das velas (helper)
    def get_adx(self, ativo, period=14, size=60):
        try:
            import numpy as np
        except ImportError:
            return None
        n_candles = period + 2
        candles = self.get_candles(ativo, size, n_candles)
        if len(candles) < period + 1:
            return None
        closes = [c['close'] for c in candles]
        highs = [c['max'] for c in candles]
        lows = [c['min'] for c in candles]
        closes = list(closes)
        highs = list(highs)
        lows = list(lows)
        closes = np.array(closes)
        highs = np.array(highs)
        lows = np.array(lows)
        plus_dm = highs[1:] - highs[:-1]
        minus_dm = lows[:-1] - lows[1:]
        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)
        tr = np.maximum.reduce([
            highs[1:] - lows[1:],
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        ])
        period = min(period, len(tr))
        atr = np.zeros_like(tr)
        atr[0] = tr[:period].mean()
        for i in range(1, len(tr)):
            atr[i] = (atr[i-1]*(period-1) + tr[i])/period
        plus_di = 100 * (plus_dm/atr)
        minus_di = 100 * (minus_dm/atr)
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
        adx = np.zeros_like(dx)
        adx[0] = dx[:period].mean()
        for i in range(1, len(dx)):
            adx[i] = (adx[i-1]*(period-1) + dx[i])/period
        # Retornar o ADX da última vela fechada (ignorar vela em formação)
        return float(adx[-2]) if len(adx) >= 2 else float(adx[-1])

def get_direction(candle):
    if candle['close'] > candle['open']:
        return 'call'
    elif candle['close'] < candle['open']:
        return 'put'
    else:
        return 'doji' # Alterado para retornar 'doji'

def traduzir_erro(reason):
    if isinstance(reason, dict):
        code = reason.get("code", "")
        message = reason.get("message", "")
    else:
        code = ""
        message = str(reason)

    if code == "invalid_credentials" or "wrong credentials" in message.lower():
        return "Você digitou as credenciais erradas. Por favor, confira seu login e senha."
    if code == "too_many_attempts" or "too many attempts" in message.lower():
        return "Muitas tentativas de login. Aguarde alguns minutos antes de tentar novamente."
    if code == "invalid_request" or "invalid request" in message.lower():
        return "Requisição inválida. Tente novamente mais tarde."
    if code == "invalid_login" or "invalid login" in message.lower():
        return "Login inválido. Por favor, confira seu login."
    if code == "banned":
        return "Sua conta foi banida. Entre em contato com o suporte."
    if code == "not_available" or "not available" in message.lower():
        return "Serviço da corretora indisponível no momento. Tente novamente mais tarde."
    if code == "timeout" or "timeout" in message.lower():
        return "Tempo de conexão esgotado. Verifique sua internet e tente novamente."
    if "network" in message.lower() or "connection" in message.lower():
        return "Problema de conexão com a internet ou com a corretora."
    if code == "account_blocked":
        return "Sua conta está bloqueada. Entre em contato com o suporte da corretora."
    if code == "account_not_activated":
        return "Sua conta não está ativada. Ative a conta para continuar."
    if message:
        return f"Erro: {message}"
    return "Ocorreu um erro desconhecido na corretora."

class PowerBossRobot:
    def __init__(self, api, config, log_callback, stats_callback, lucro_callback, stop_event, sound_callback=None, finish_callback=None, update_saldo_callback=None):
        self.api = api
        self.config = config
        self.log = log_callback
        self.stats_callback = stats_callback
        self.lucro_callback = lucro_callback
        self.stop_event = stop_event
        self.result_stats = {'ops': 0, 'wins': 0, 'losses': 0}
        self.lucro_acumulado = 0.0
        self.entradas_realizadas = 0
        self.sound_callback = sound_callback
        self.finish_callback = finish_callback
        self.update_saldo_callback = update_saldo_callback

    def get_candles(self, ativo, n=10, size=60):
        try:
            return self.api.get_candles(ativo, size, n, time.time())
        except Exception:
            return []

    def buy(self, ativo, valor, direcao, exp):
        if self.sound_callback:
            self.sound_callback("entry")
        try:
            _, order_id = self.api.buy(valor, ativo, direcao, exp)
            if not order_id:
                self.log(f"Falha ao enviar ordem para {ativo}.", "#FF4040")
                return None, 0.0
            max_wait = 120
            start = time.time()
            while True:
                status, lucro = self.api.check_win_v4(order_id)
                if status is not None:
                    if self.update_saldo_callback:
                        self.update_saldo_callback()
                    if status == 'win' or status is True:
                        if self.sound_callback:
                            self.sound_callback("win")
                        return True, lucro
                    elif status == 'loose' or status is False:
                        if self.sound_callback:
                            self.sound_callback("loss")
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

    def get_consecutive_candles_count(self, ativo):
        candles = self.get_candles(ativo, n=10, size=60)
        if not candles:
            return 0
        
        last_direction = None
        count = 0
        for candle in reversed(candles):
            direction = get_direction(candle)
            if direction == 'doji':
                continue
            if last_direction is None:
                last_direction = direction
                count = 1
            elif direction == last_direction:
                count += 1
            else:
                break
        return count

    def run(self):
        ativos = list(self.config['ativos'])
        if not ativos:
            self.log("Nenhum ativo selecionado!", "#FF4040")
            if self.finish_callback:
                self.finish_callback()
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
        prox_soros = None

        self.log("Robô iniciado! (Estratégia MHI - Minoria 3 últimas velas)", "#FFD700")
        while not self.stop_event.is_set():
            agora = datetime.datetime.now()
            # Ponto de entrada é o início do quadrante (minutos 0, 5, 10, ...)
            if agora.minute % 5 == 0 and agora.second < 2:
                ativo = ativos[ativo_idx % len(ativos)]
                ativo_idx += 1
                self.log(f"[QUADRANTE NOVO] Minuto {agora.minute:02d} - Analisando ativo: {ativo}", "#FFD700")

                # FILTRO DE VELAS CONSECUTIVAS
                if self.config.get("filtro_velas_consecutivas", False):
                    consecutive_count = self.get_consecutive_candles_count(ativo)
                    if consecutive_count >= 5:
                        self.log(f"Entrada BLOQUEADA pelo filtro de velas! {consecutive_count} velas consecutivas da mesma cor.", "#FFA500")
                        time.sleep(2) # Pausa para evitar re-análise no mesmo segundo
                        continue

                # FILTRO ADX
                if self.config.get("adx", False):
                    adx_val = self.api.get_adx(ativo, period=14, size=60)
                    if adx_val is not None and adx_val >= 21:
                        self.log(f"Entrada BLOQUEADA pelo ADX! ADX atual = {adx_val:.2f} (>= 21)", "#FFA500")
                        time.sleep(2)
                        continue

                # Pega as 5 velas do quadrante anterior para análise
                candles = self.get_candles(ativo, n=5, size=60)
                if len(candles) < 5:
                    self.log(f"Não foi possível obter as 5 velas do quadrante para {ativo}.", "#FF4040")
                    time.sleep(3)
                    continue

                ultimas_tres_velas = candles[-3:]
                directions = [get_direction(c) for c in ultimas_tres_velas]

                if 'doji' in directions:
                    self.log(f"Quadrante ignorado em {ativo} devido a um DOJI nas 3 últimas velas.", "#FF8000")
                    time.sleep(2)
                    continue
                
                # Lógica da Minoria
                call_count = directions.count('call')
                put_count = directions.count('put')

                if call_count == put_count: # Improvável com 3 velas, mas para segurança
                    self.log(f"Quadrante ignorado em {ativo}: empate de direções.", "#FF8000")
                    time.sleep(2)
                    continue

                if call_count > put_count:
                    direcao_entrada = 'put' # Minoria é PUT
                else:
                    direcao_entrada = 'call' # Minoria é CALL
                
                self.log(f"Análise {ativo}: {directions} -> Entrada para MINORIA: {direcao_entrada.upper()}", "#00FFFF")
                
                mg_nivel = 0
                valor_base = self.config['valor']
                if soros_ativo and prox_soros is not None:
                    valor_entrada = prox_soros
                    prox_soros = None
                else:
                    valor_entrada = valor_base

                while mg_nivel <= mg_nivel_max and not self.stop_event.is_set():
                    if mg_nivel > 0:
                        valor_entrada *= 2
                    self.result_stats['ops'] += 1
                    self.entradas_realizadas += 1
                    self.stats_callback(self._stats())
                    labelmg = "" if mg_nivel == 0 else f"(MG{mg_nivel})"
                    self.log(f"Entrando em {ativo} | {direcao_entrada.upper()} {labelmg} | Valor: {valor_entrada:.2f}", "#00FFFF")
                    
                    resultado, lucro_op = self.buy(ativo, valor_entrada, direcao_entrada, self.config['expiracao'])
                    self.lucro_acumulado += lucro_op
                    self.lucro_callback(self.lucro_acumulado)

                    if resultado is None and lucro_op == 0.0:
                        self.log(f"EMPATE (doji) em {ativo} | Valor devolvido.", "#FFD700")
                        self.stats_callback(self._stats())
                        prox_soros = None
                        break
                    elif resultado is True:
                        self.result_stats['wins'] += 1
                        self.log(f"WIN em {ativo} com {direcao_entrada.upper()} {labelmg} | Lucro: {lucro_op:.2f}", "#2DC937")
                        if soros_ativo and mg_nivel == 0:
                            prox_soros = valor_base + (lucro_op * (soros_percent / 100))
                        else:
                            prox_soros = None
                        self.stats_callback(self._stats())
                        break
                    else: # Loss
                        self.result_stats['losses'] += 1
                        if mg_nivel < mg_nivel_max:
                            self.log(f"LOSS em {ativo} | Indo para Martingale {mg_nivel+1}", "#FF8000")
                            mg_nivel += 1
                            self.stats_callback(self._stats())
                            continue
                        else:
                            self.log(f"LOSS em {ativo} com {direcao_entrada.upper()} {labelmg} | Perda: {lucro_op:.2f}", "#FF4040")
                            prox_soros = None
                            self.stats_callback(self._stats())
                            break

                if self.verificar_condicoes_parada():
                    if self.sound_callback:
                        self.sound_callback("limit")
                    if self.finish_callback:
                        self.finish_callback()
                    return
                
                # *** CORREÇÃO APLICADA: Pausa estática removida ***
                time.sleep(2) # Pequena pausa para garantir que saia da janela de entrada
            else:
                time.sleep(0.5)
        
        self.log("Robô finalizado pelo usuário.", "#FFA500")
        if self.finish_callback:
            self.finish_callback()

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
        taxa = (wins / ops * 100) if ops else 0
        return {'ops': ops, 'wins': wins, 'losses': self.result_stats['losses'], 'taxa': f"{taxa:.1f}%"}

def catalogar_powerboss(api, ativo, minutos=60, mg_niveis=1):
    # Pega velas suficientes para analisar os quadrantes e os martingales
    total_velas_necessarias = minutos + (mg_niveis + 1)
    candles = api.get_candles(ativo, 60, total_velas_necessarias)
    if not candles or len(candles) < 5:
        return None

    win_niveis = [0] * (mg_niveis + 1)
    loss = 0
    total_ciclos = 0
    
    max_consecutive_count = 0

    # Verifica velas consecutivas nos dados históricos
    consecutive_count = 0
    last_dir = None
    for c in candles:
        current_dir = get_direction(c)
        if current_dir != 'doji':
            if current_dir == last_dir:
                consecutive_count += 1
            else:
                last_dir = current_dir
                consecutive_count = 1
            if consecutive_count > max_consecutive_count:
                 max_consecutive_count = consecutive_count

    # Itera pelos quadrantes
    for i in range(0, len(candles) - 5 - mg_niveis, 5):
        quadrante_analise = candles[i : i+5]
        
        ultimas_tres = quadrante_analise[-3:]
        directions = [get_direction(c) for c in ultimas_tres]

        if 'doji' in directions:
            continue

        call_count = directions.count('call')
        put_count = directions.count('put')

        if call_count == put_count:
            continue

        direcao_entrada = 'put' if call_count > put_count else 'call'
        total_ciclos += 1
        
        # Verifica resultado na vela de entrada e nos martingales
        resultado_encontrado = False
        for mg in range(mg_niveis + 1):
            idx_vela_entrada = i + 5 + mg
            if idx_vela_entrada >= len(candles):
                break
            
            vela_entrada = candles[idx_vela_entrada]
            resultado_vela = get_direction(vela_entrada)

            if resultado_vela == 'doji':
                # Empate no MG, considera loss do ciclo
                break
            
            if resultado_vela == direcao_entrada:
                win_niveis[mg] += 1
                resultado_encontrado = True
                break
        
        if not resultado_encontrado:
            loss += 1

    if total_ciclos == 0:
        return None

    total_wins = sum(win_niveis)
    assertividade = (total_wins / total_ciclos * 100) if total_ciclos else 0
    adx_val = api.get_adx(ativo, period=14, size=60)

    return {
        'ativo': ativo,
        'wins': win_niveis,
        'loss': loss,
        'total': total_ciclos,
        'assertividade': assertividade,
        'mg_niveis': mg_niveis,
        'adx': adx_val,
        'velas_consecutivas': max_consecutive_count
    }

class BotFullApp(tk.Tk):
    LOG_COLORS = {
        "dark": {
            "#FFD700": "#FFD700",
            "#00BFFF": "#00BFFF",
            "#2DC937": "#00FF00",
            "#FF4040": "#FF3030",
            "#FF8000": "#FFA500",
            "#FFA500": "#FFD700",
            "#00FFFF": "#00FFFF",
        },
        "light": {
            "#FFD700": "#FFD700",
            "#00BFFF": "#00BFFF",
            "#2DC937": "#00FF00",
            "#FF4040": "#FF3030",
            "#FF8000": "#FFA500",
            "#FFA500": "#FFD700",
            "#00FFFF": "#00FFFF",
        },
        "default": "#FFFFFF"
    }

    def __init__(self):
        super().__init__()
        self.title("Robô Power Boss - By Junior Maciel")
        self.geometry("1050x720")
        self.resizable(True, True)
        self.theme_mode = "dark"
        set_azure_theme(self, self.theme_mode)
        self.api = None
        self.connected = False
        self.robot = None
        self.robot_thread = None
        self.robot_stop = threading.Event()
        self.ativos = []
        self.lucro_acumulado_display = 0.0
        self.robot_stopped_manual = False

        self.sound_files = {
            "entry": "",
            "win": "",
            "loss": "",
            "limit": "",
            "conexao": "",
            "conexao_erro": ""
        }
        self.sons_ativos = tk.BooleanVar(value=True)

        self.load_sound_config()
        self.spinner_running = False
        self.create_widgets()
        self.load_login()
        self.after(1000, self.update_clock)

    def create_widgets(self):
        frame_conn = ttk.LabelFrame(self, text="Conexão")
        frame_conn.pack(fill="x", padx=10, pady=8)
        ttk.Label(frame_conn, text="Email:").grid(row=0, column=0, padx=6, pady=4, sticky="e")
        self.entry_email = ttk.Entry(frame_conn, width=29)
        self.entry_email.grid(row=0, column=1, padx=6, pady=4)
        self.entry_email.bind("<Return>", lambda event: self.connect_api())
        ttk.Label(frame_conn, text="Senha:").grid(row=0, column=2, padx=6, pady=4, sticky="e")
        self.entry_senha = ttk.Entry(frame_conn, width=16, show="*")
        self.entry_senha.grid(row=0, column=3, padx=6, pady=4)
        self.entry_senha.bind("<Return>", lambda event: self.connect_api())
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
        self.lbl_saldo = tk.Label(frame_conn, text="Saldo: --", font=("Arial", 22, "bold"), fg="#00FF00", bg="#222")
        self.lbl_saldo.grid(row=0, column=9, padx=10, pady=4)
        self.btn_theme = ttk.Button(frame_conn, text="🌙 Modo Escuro", command=self.toggle_theme)
        self.btn_theme.grid(row=0, column=10, padx=10, pady=4)
        self.var_save_login = tk.BooleanVar(value=False)
        self.check_save_login = ttk.Checkbutton(frame_conn, text="Salvar credenciais", variable=self.var_save_login)
        self.check_save_login.grid(row=1, column=1, columnspan=2, padx=6, pady=4, sticky="w")
        self.check_sons = ttk.Checkbutton(frame_conn, text="Sons ativados", variable=self.sons_ativos, command=self.update_check_sons_label)
        self.check_sons.grid(row=1, column=3, padx=8, pady=4, sticky="w")

        self.main = ttk.Frame(self)
        self.main.pack(fill="both", expand=True, padx=10, pady=5)
        self.main.columnconfigure(0, weight=1)
        self.main.columnconfigure(1, weight=2)
        self.main.columnconfigure(2, weight=2)
        self.main.rowconfigure(0, weight=1)
        self.main.rowconfigure(1, weight=1)

        frame_ativos = ttk.LabelFrame(self.main, text="Ativos")
        frame_ativos.grid(row=0, column=0, rowspan=2, sticky="nswe", padx=6, pady=4)
        self.entry_busca_ativo = ttk.Entry(frame_ativos, width=17)
        self.entry_busca_ativo.pack(padx=5, pady=3)
        self.entry_busca_ativo.bind("<KeyRelease>", self.filter_ativos)
        self.list_ativos = tk.Listbox(frame_ativos, width=22, height=14, selectmode="multiple")
        self.list_ativos.pack(padx=5, pady=3, fill="y")
        btns_ativos = ttk.Frame(frame_ativos)
        btns_ativos.pack(pady=2)
        ttk.Button(btns_ativos, text="Listar Ativos", command=self.atualiza_ativos).pack(side="left", padx=3)
        ttk.Button(btns_ativos, text="Analisar Assertividade", command=self.catalogar_ativo).pack(side="left", padx=3)
        self.lbl_clock = tk.Label(frame_ativos, text="", font=("Arial", 28, "bold"), fg="#FFD700", bg="#222")
        self.lbl_clock.pack(pady=(12, 6))

        frame_config = ttk.LabelFrame(self.main, text="Configuração do Robô")
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
        self.spin_entradas.set(10)
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
        ttk.Checkbutton(frame_config, text="Filtro ADX (<21)", variable=self.var_adx).grid(row=row, column=0, padx=4, pady=3)
        self.var_filtro_velas = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame_config, text="Filtro Velas (>=5)", variable=self.var_filtro_velas).grid(row=row, column=1, columnspan=2, padx=4, pady=3, sticky="w")
        ttk.Label(frame_config, text="Stop Win $:").grid(row=row, column=2, padx=4, pady=3, sticky="e")
        self.entry_stopwin = ttk.Entry(frame_config, width=7)
        self.entry_stopwin.grid(row=row, column=3, padx=4, pady=3)
        ttk.Label(frame_config, text="Stop Loss $:").grid(row=row, column=4, padx=4, pady=3, sticky="e")
        self.entry_stoploss = ttk.Entry(frame_config, width=7)
        self.entry_stoploss.grid(row=row, column=5, padx=4, pady=3)
        row += 1
        self.var_stop = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_config, text="Operar por Lucro/Stop Loss", variable=self.var_stop).grid(row=row, column=0, columnspan=2, padx=4, pady=3, sticky="w")

        frame_ctrl = ttk.LabelFrame(self.main, text="Controle")
        frame_ctrl.grid(row=1, column=1, sticky="nswe", padx=6, pady=4)
        self.btn_start = ttk.Button(frame_ctrl, text="▶️ Iniciar Robô", command=self.start_robot)
        self.btn_start.grid(row=0, column=0, padx=8, pady=9)
        self.btn_stop = ttk.Button(frame_ctrl, text="⏹️ Parar Robô", command=self.stop_robot, state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=8, pady=9)
        ttk.Label(frame_ctrl, text="Status:").grid(row=0, column=2, padx=8, pady=9)
        self.lbl_robostatus = ttk.Label(frame_ctrl, text="Inativo", foreground="red")
        self.lbl_robostatus.grid(row=0, column=3, padx=6, pady=9)

        stats = ttk.LabelFrame(self.main, text="Estatísticas")
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
        frame_lucro = ttk.LabelFrame(self.main, text="Lucro/Prejuízo Atual")
        frame_lucro.grid(row=0, column=2, sticky="nswe", padx=6, pady=4)
        self.lbl_lucro = ttk.Label(frame_lucro, text="R$ 0,00", font=("Arial", 22, "bold"), foreground="#2DC937")
        self.lbl_lucro.pack(side="left", padx=3, pady=6)
        self.btn_lucro_reset = ttk.Button(frame_lucro, text="🔄 Reset", command=self.reset_lucro)
        self.btn_lucro_reset.pack(side="left", padx=8, pady=6)

        log_frame = ttk.LabelFrame(self, text="Log de eventos principais")
        log_frame.pack(fill="both", expand=True, padx=10, pady=4)
        log_and_btn_frame = ttk.Frame(log_frame)
        log_and_btn_frame.pack(fill="both", expand=True, padx=0, pady=0)
        btn_clear_log = ttk.Button(log_and_btn_frame, text="🧹 Limpar Log", command=self.clear_log)
        btn_clear_log.pack(side="right", padx=6, pady=4)
        self.text_log = tk.Text(log_and_btn_frame, height=11, state="disabled", bg="#000000", fg="#FFD700", font=("Consolas", 10))
        self.text_log.pack(side="left", fill="both", expand=True, padx=4, pady=4)

    def update_check_sons_label(self):
        if self.sons_ativos.get():
            self.check_sons.config(text="Sons ativados")
        else:
            self.check_sons.config(text="Sons desativados")

    def start_log_spinner(self, message_tag, base_message):
        self._log_spinner_running = True
        self._log_spinner_state = 0
        self._log_spinner_tag = message_tag
        self._log_spinner_base = base_message
        self._log_spinner_frames = ["⏳", "⌛"]
        self._log_spinner_after_id = None

        def update_spinner():
            if not getattr(self, "_log_spinner_running", False):
                return
            spin = self._log_spinner_frames[self._log_spinner_state % len(self._log_spinner_frames)]
            msg = f"{self._log_spinner_base} {spin}"
            self.text_log.config(state="normal")
            last_line_idx = self.text_log.index("end-2l linestart")
            self.text_log.delete(last_line_idx, "end-1l lineend")
            self.text_log.insert(last_line_idx, msg + "\n")
            self.text_log.tag_add(self._log_spinner_tag, last_line_idx, f"{last_line_idx} lineend")
            self.text_log.tag_config(self._log_spinner_tag, foreground="#FFA500")
            self.text_log.config(state="disabled")
            self.text_log.see("end")
            self._log_spinner_state += 1
            self._log_spinner_after_id = self.after(500, update_spinner)
        self.text_log.config(state="normal")
        self.text_log.insert("end", f"{self._log_spinner_base} {self._log_spinner_frames[0]}\n")
        last_line_idx = self.text_log.index("end-2l linestart")
        self.text_log.tag_add(self._log_spinner_tag, last_line_idx, f"{last_line_idx} lineend")
        self.text_log.tag_config(self._log_spinner_tag, foreground="#FFA500")
        self.text_log.config(state="disabled")
        self.text_log.see("end")
        self._log_spinner_state = 1
        self.text_log.update_idletasks()
        update_spinner()

    def stop_log_spinner(self, final_message, color="#FFD700"):
        self._log_spinner_running = False
        if getattr(self, "_log_spinner_after_id", None):
            self.after_cancel(self._log_spinner_after_id)
            self._log_spinner_after_id = None
        self.text_log.config(state="normal")
        last_line_idx = self.text_log.index("end-2l linestart")
        self.text_log.delete(last_line_idx, "end-1l lineend")
        self.text_log.insert(last_line_idx, final_message + "\n")
        tag_color = self.get_log_color(color)
        self.text_log.tag_add("SPINNER_FINAL", last_line_idx, f"{last_line_idx} lineend")
        self.text_log.tag_config("SPINNER_FINAL", foreground=tag_color)
        self.text_log.config(state="disabled")
        self.text_log.see("end")

    def save_login(self):
        if self.var_save_login.get():
            with open("login.json", "w") as f:
                json.dump({
                    "email": self.entry_email.get(),
                    "senha": self.entry_senha.get()
                }, f)
        else:
            if os.path.exists("login.json"):
                os.remove("login.json")

    def load_login(self):
        if os.path.exists("login.json"):
            try:
                with open("login.json", "r") as f:
                    data = json.load(f)
                    self.entry_email.delete(0, tk.END)
                    self.entry_email.insert(0, data.get("email", ""))
                    self.entry_senha.delete(0, tk.END)
                    self.entry_senha.insert(0, data.get("senha", ""))
                self.var_save_login.set(True)
            except Exception:
                self.entry_email.delete(0, tk.END)
                self.entry_senha.delete(0, tk.END)
                self.var_save_login.set(False)
        else:
            self.entry_email.delete(0, tk.END)
            self.entry_senha.delete(0, tk.END)
            self.var_save_login.set(False)

    def save_sound_config(self):
        try:
            with open("sons.json", "w") as f:
                json.dump(self.sound_files, f)
        except Exception:
            pass

    def load_sound_config(self):
        if os.path.exists("sons.json"):
            try:
                with open("sons.json", "r") as f:
                    arquivos = json.load(f)
                    for k in self.sound_files:
                        if k in arquivos:
                            self.sound_files[k] = arquivos[k]
            except Exception:
                pass

    def update_clock(self):
        from datetime import datetime
        self.lbl_clock.config(text=datetime.now().strftime("%H:%M:%S"))
        self.after(1000, self.update_clock)

    def toggle_theme(self):
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        set_azure_theme(self, self.theme_mode)
        icon = "🌙" if self.theme_mode == "dark" else "☀️"
        label = "Modo Escuro" if self.theme_mode == "dark" else "Modo Claro"
        self.btn_theme.config(text=f"{icon} {label}")
        bg = "#222" if self.theme_mode == "dark" else "#F5F6FA"
        self.text_log.config(bg="#000000", fg="#FFD700")
        self.configure(bg=bg)
        if self.theme_mode == "dark":
            self.lbl_clock.config(fg="#FFD700", bg="#222")
            self.lbl_saldo.config(fg="#00FF00" if self.lucro_acumulado_display >= 0 else "#FF4040", bg="#222")
        else:
            self.lbl_clock.config(fg="#003366", bg="#F5F6FA")
            self.lbl_saldo.config(fg="#006400" if self.lucro_acumulado_display >= 0 else "#FF4040", bg="#F5F6FA")
        self.update_lucro(self.lucro_acumulado_display)

    def connect_api(self):
        email = self.entry_email.get().strip()
        senha = self.entry_senha.get().strip()
        conta = self.combo_conta.get().upper()
        self.api = None
        self.connected = False
        self.lbl_status.config(text="Desconectado", foreground="red")
        self.btn_connect.config(state="normal")
        self.btn_disconnect.config(state="disabled")
        self.lbl_saldo.config(text="Saldo: --")
        if not email or not senha:
            self.log_event("Preencha email e senha para conectar.", "#FF4040")
            self.robot_sound("conexao_erro")
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
                self.lbl_saldo.config(text=f"Saldo: R$ {format_money(saldo)}")
                if self.theme_mode == "dark":
                    self.lbl_saldo.config(fg="#00FF00", bg="#222")
                else:
                    self.lbl_saldo.config(fg="#006400", bg="#F5F6FA")
                self.log_event(f"Conectado! Saldo: R$ {format_money(saldo)}", "#2DC937")
                self.robot_sound("conexao")
                self.save_login()
            else:
                self.api = None
                self.connected = False
                self.lbl_status.config(text="Desconectado", foreground="red")
                self.btn_connect.config(state="normal")
                self.btn_disconnect.config(state="disabled")
                self.lbl_saldo.config(text="Saldo: --")
                msg = traduzir_erro(reason)
                self.log_event(f"Erro ao conectar: {msg}", "#FF4040")
                self.robot_sound("conexao_erro")
        except Exception as e:
            self.api = None
            self.connected = False
            self.lbl_status.config(text="Desconectado", foreground="red")
            self.btn_connect.config(state="normal")
            self.btn_disconnect.config(state="disabled")
            self.lbl_saldo.config(text="Saldo: --")
            msg = traduzir_erro(str(e))
            self.log_event(f"Erro ao conectar: {msg}", "#FF4040")
            self.robot_sound("conexao_erro")

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
        self.lucro_acumulado_display = 0.0
        self.update_lucro(self.lucro_acumulado_display)
        self.log_event("Desconectado da corretora.", "#FF4040")
        self.save_login()

    def robot_sound(self, event):
        if not self.sons_ativos.get():
            return
        file = self.sound_files.get(event)
        if not file:
            file = DEFAULT_SOUNDS.get(event)
        if file and os.path.exists(resource_path(file)):
            play_sound(sound_file=file)
        else:
            if event == "entry":
                play_sound(freq=880, dur=180)
            elif event == "win":
                play_sound(freq=1200, dur=250)
            elif event == "loss":
                play_sound(freq=400, dur=300)
            elif event == "limit":
                play_sound(freq=500, dur=180)
                play_sound(freq=800, dur=220)
                play_sound(freq=500, dur=180)
            elif event == "conexao_erro":
                play_sound(freq=200, dur=500)
                play_sound(freq=120, dur=350)

    def log_event(self, msg, color="#FFD700"):
        now = datetime.datetime.now().strftime('%H:%M:%S')
        msg = f"[{now}] {msg}"
        self.text_log.config(state="normal")
        self.text_log.insert("end", f"{msg}\n")
        tag_color = self.get_log_color(color)
        self.text_log.tag_add(tag_color, "end-2l linestart", "end-2l lineend")
        self.text_log.tag_config(tag_color, foreground=tag_color)
        self.text_log.config(state="disabled")
        self.text_log.see("end")

    def get_log_color(self, color):
        if self.theme_mode == "dark":
            return self.LOG_COLORS["dark"].get(color, self.LOG_COLORS["default"])
        else:
            return self.LOG_COLORS["light"].get(color, self.LOG_COLORS["default"])

    def clear_log(self):
        self.text_log.config(state="normal")
        self.text_log.delete(1.0, tk.END)
        self.text_log.config(state="disabled")

    def atualiza_ativos(self):
        if not self.api or not self.connected:
            self.log_event("Conecte-se para buscar ativos.", "#FF4040")
            return
        self.start_log_spinner("SPINNER_ATIVOS", "Listando ativos, aguarde!")
        self.text_log.update_idletasks()
        def do_update():
            try:
                ativos_all = self.api.get_all_open_time()
                
                if ativos_all is None:
                    self.after(0, lambda: self.stop_log_spinner("Falha ao buscar ativos. A corretora não respondeu a tempo.", "#FF4040"))
                    self.after(0, lambda: self.log_event("Verifique sua conexão ou tente novamente mais tarde.", "#FF8000"))
                    return

                ativos = set()
                for tipo_ativo in ['digital', 'turbo']:
                    if tipo_ativo in ativos_all and isinstance(ativos_all[tipo_ativo], dict):
                        for ativo, status_ativo in ativos_all[tipo_ativo].items():
                            if isinstance(status_ativo, dict) and status_ativo.get('open'):
                                if not self.var_otc.get() and '-OTC' in ativo:
                                    continue
                                ativos.add(ativo)

                self.ativos = sorted(ativos)
                self.update_ativos_list()
                msg = f"Ativos atualizados ({len(self.ativos)} ativos abertos)."
                self.after(0, lambda: self.stop_log_spinner(msg, "#2DC937"))
            
            except TypeError:
                self.after(0, lambda: self.stop_log_spinner("Erro interno da API ao processar ativos.", "#FF4040"))
                self.after(0, lambda: self.log_event("A biblioteca da IQ Option falhou. Tente listar os ativos novamente.", "#FF8000"))
            except Exception as e:
                self.after(0, lambda: self.stop_log_spinner(f"Erro ao buscar ativos: {e}", "#FF4040"))
                self.after(0, lambda: self.log_event("Pode ser um problema de conexão ou da API da corretora.", "#FF8000"))
        
        threading.Thread(target=do_update, daemon=True).start()

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
        try:
            mg_niveis = int(self.combo_mg_niveis.get()) if self.combo_mg_niveis.get() else 1
        except Exception:
            mg_niveis = 1
        
        if selecionados:
            ativos_analisar = selecionados
        else:
            ativos_analisar = self.ativos
        
        resultados = []
        self.start_log_spinner("SPINNER_ASSERT", "Analisando assertividade, aguarde!")
        
        def do_catalog():
            for ativo in ativos_analisar:
                try:
                    res = catalogar_powerboss(self.api, ativo, minutos=60, mg_niveis=mg_niveis)
                    if res:
                        resultados.append(res)
                except Exception as e:
                    print(f"Erro catalogando {ativo}: {e}") # debug
                    pass
            
            if not resultados:
                self.after(0, lambda: self.stop_log_spinner("Nenhum ativo pôde ser analisado.", "#FF4040"))
                return
            
            melhores = sorted(resultados, key=lambda x: x['assertividade'], reverse=True)
            
            if melhores:
                self.after(0, lambda: self.stop_log_spinner(f"Melhores Ativos ({len(melhores[:5])} de {len(melhores)}):", "#FFD700"))
                for r in melhores[:5]: # Mostra os 5 melhores
                    wins_str_parts = [f"WIN: {r['wins'][0]}"]
                    for mg in range(1, len(r['wins'])):
                        wins_str_parts.append(f"MG{mg}: {r['wins'][mg]}")
                    wins_str = " | ".join(wins_str_parts)
                    
                    adx_str = f" | ADX: {r['adx']:.2f}" if r.get('adx') is not None else ""
                    
                    velas_count = r.get('velas_consecutivas', 0)
                    velas_str = f" | Velas Repetitivas: {velas_count}" if velas_count >= 5 else ""
                    
                    msg = (
                        f"{r['ativo']} -> {r['assertividade']:.2f}% | {wins_str} | Loss: {r['loss']}{adx_str}{velas_str}"
                    )
                    self.after(0, lambda m=msg: self.log_event(m, "#FFD700"))

            else:
                self.after(0, lambda: self.stop_log_spinner("Nenhum resultado de catalogação.", "#FF8000"))

        threading.Thread(target=do_catalog, daemon=True).start()


    def robot_finished(self):
        self.lbl_robostatus.config(text="Parado", foreground="red")
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        if not self.robot_stopped_manual:
            self.log_event("Robô finalizado (limite atingido ou usuário parou).", "#FFA500")
        self.robot_stopped_manual = False

    def app_update_saldo(self):
        if self.api and self.connected:
            try:
                saldo = self.api.get_balance()
                if saldo < 0:
                    fg = "#FF4040"
                else:
                    fg = "#00FF00" if self.theme_mode == "dark" else "#006400"
                self.lbl_saldo.config(text=f"Saldo: R$ {format_money(saldo)}", fg=fg, bg="#222" if self.theme_mode == "dark" else "#F5F6FA")
            except Exception:
                pass

    def start_robot(self):
        if self.robot_thread and self.robot_thread.is_alive():
            self.log_event("Robô já está rodando!", "#FF8000")
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
                "filtro_velas_consecutivas": self.var_filtro_velas.get(),
                "stop_lucro": self.var_stop.get(),
                "lucro": float(self.entry_stopwin.get().replace(",", ".")) if self.entry_stopwin.get() else 0.0,
                "perda": float(self.entry_stoploss.get().replace(",", ".")) if self.entry_stoploss.get() else 0.0,
                "ativos": ativos
            }
        except Exception as e:
            self.log_event(f"Preencha corretamente as configurações. Erro: {e}", "#FF4040")
            return
            
        self.robot_stop.clear()
        self.robot_stopped_manual = False
        self.lbl_robostatus.config(text="Operando", foreground="#FFB000")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.robot = PowerBossRobot(
            api=self.api,
            config=config,
            log_callback=self.log_event,
            stats_callback=self.update_stats,
            lucro_callback=self.update_lucro,
            stop_event=self.robot_stop,
            sound_callback=self.robot_sound,
            finish_callback=self.robot_finished,
            update_saldo_callback=self.app_update_saldo
        )
        self.log_event("Robô iniciado! Aguardando próximo ciclo para operar...", "#2DC937")
        self.robot_thread = threading.Thread(target=self.robot.run, daemon=True)
        self.robot_thread.start()

    def stop_robot(self):
        if self.robot_stop:
            self.robot_stop.set()
        self.robot_stopped_manual = True
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
        self.lucro_acumulado_display = valor
        if valor < 0:
            cor = "#FF4040"
        else:
            cor = "#00FF00" if self.theme_mode == "dark" else "#006400"
        sinal = "" if valor >= 0 else "-"
        valor_abs = abs(valor)
        texto = f"R${sinal}{valor_abs:,.2f}".replace('.', ',')
        self.lbl_lucro.config(text=texto, foreground=cor)

    def reset_lucro(self):
        self.lucro_acumulado_display = 0.0
        self.update_lucro(self.lucro_acumulado_display)
        self.log_event("Lucro/Prejuízo zerado manualmente.", "#FFA500")

if __name__ == "__main__":
    app = BotFullApp()
    app.mainloop()