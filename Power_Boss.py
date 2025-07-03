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
    
    def get_all_profit(self):
        return self.api.get_all_profit()

    def get_candles(self, ativo, interval, n, now=None):
        now = now or time.time()
        candles = self.api.get_candles(ativo, interval, n, now)
        return sorted(candles, key=lambda x: x['from'])

    def buy(self, valor, ativo, direcao, exp):
        return self.api.buy(valor, ativo, direcao, exp)

    def check_win_v4(self, order_id):
        return self.api.check_win_v4(order_id)

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
        return float(adx[-2]) if len(adx) >= 2 else float(adx[-1])

# NOVO: Função de direção com filtro de Doji
def get_direction(candle, use_doji_filter=False, doji_sensitivity_percent=5.0):
    if use_doji_filter:
        body = abs(candle['close'] - candle['open'])
        range_ = candle['max'] - candle['min']
        if range_ == 0: return 'doji'
        body_percent_of_range = (body / range_) * 100
        if body_percent_of_range < doji_sensitivity_percent:
            return 'doji'
            
    if candle['close'] > candle['open']:
        return 'call'
    elif candle['close'] < candle['open']:
        return 'put'
    else:
        return 'doji'

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
        self.consecutive_losses = {}
        self.apto_para_operar = {}
        self.last_analysis_time = {ativo: None for ativo in config.get('ativos', [])}


    def get_candles(self, ativo, n=10, size=60):
        try:
            return self.api.get_candles(ativo, size, n, time.time())
        except Exception:
            return []

    def buy(self, ativo, valor, direcao, exp):
        if self.sound_callback:
            self.sound_callback("entry")
        
        if not self.api or not self.api.connected:
            self.log(f"Operação cancelada em {ativo}: API desconectada.", "#FF4040")
            return None, 0.0

        try:
            _, order_id = self.api.buy(valor, ativo, direcao, exp)
            if not order_id:
                self.log(f"Falha ao enviar ordem para {ativo}. A corretora não retornou um ID.", "#FF4040")
                return None, 0.0
            
            max_wait = 120
            check_interval = 0.5
            max_checks = int(max_wait / check_interval)
            
            for i in range(max_checks):
                if self.stop_event.is_set():
                    self.log("Verificação de resultado cancelada pelo usuário.", "#FF8000")
                    return None, 0.0
                
                try:
                    status, lucro = self.api.check_win_v4(order_id)
                except Exception as e:
                    self.log(f"Erro ao verificar resultado da ordem: {e}. Tentando novamente...", "#FF8000")
                    time.sleep(check_interval)
                    continue

                if status is not None:
                    if self.update_saldo_callback: self.update_saldo_callback()
                    if status == 'win' or status is True:
                        if self.sound_callback: self.sound_callback("win")
                        return True, lucro
                    elif status == 'loose' or status is False:
                        if self.sound_callback: self.sound_callback("loss")
                        return False, lucro
                    elif status == 'equal':
                        return None, lucro
                    else:
                        self.log(f"Status desconhecido retornado: {status}. Finalizando checagem.", "#FF8000")
                        return None, lucro
                
                time.sleep(check_interval)

            self.log(f"Timeout ao obter resultado da ordem {order_id} em {ativo}!", "#FF4040")
            return None, 0.0

        except Exception as e:
            self.log(f"Erro crítico na função de compra: {e}", "#FF4040")
            return None, 0.0


    def get_consecutive_candles_count(self, ativo):
        candles = self.get_candles(ativo, n=10, size=60)
        if not candles: return 0
        
        last_direction = None
        count = 0
        for candle in reversed(candles):
            direction = get_direction(candle, use_doji_filter=self.config.get("doji_filter", False))
            if direction == 'doji': continue
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
            if self.finish_callback: self.finish_callback()
            return

        self.lucro_acumulado = 0.0
        self.entradas_realizadas = 0
        self.result_stats = {'ops': 0, 'wins': 0, 'losses': 0}
        self.lucro_callback(self.lucro_acumulado)
        self.stats_callback({'ops': 0, 'wins': 0, 'losses': 0, 'taxa': "0%"})
        mg_nivel_max = int(self.config.get('mg_niveis', 1))
        
        soros_percent = self.config.get('soros', 0)
        soros_ativo = soros_percent > 0
        soros_em_mg = self.config.get('soros_em_mg', False)
        prox_soros = None
        
        filtro_loss_ativo = self.config.get('filtro_loss_seguidos', False)
        qtd_loss_necessarios = self.config.get('qtd_loss_seguidos', 2)
        esperar_novo_loss_apos_win = self.config.get('esperar_novo_loss', False)
        
        self.consecutive_losses = {ativo: 0 for ativo in ativos}
        initial_apt_status = not filtro_loss_ativo
        self.apto_para_operar = {ativo: initial_apt_status for ativo in ativos}
        self.last_analysis_time = {ativo: None for ativo in ativos}

        if filtro_loss_ativo:
            self.log(f"Filtro de Loss ativado. Aguardando {qtd_loss_necessarios} loss seguidos para cada ativo individualmente.", "#FFA500")

        ativo_idx = 0
        while not self.stop_event.is_set():
            agora = datetime.datetime.now()
            
            if agora.second > 5:
                time.sleep(1)
                continue

            ativo = ativos[ativo_idx]
            ativo_idx = (ativo_idx + 1) % len(ativos)

            minuto_atual = agora.minute
            if minuto_atual % 5 == 0:
                horario_analise = agora.replace(second=0, microsecond=0)
                if self.last_analysis_time.get(ativo) == horario_analise:
                    time.sleep(1)
                    continue
                self.last_analysis_time[ativo] = horario_analise

                velas_necessarias = 5 + mg_nivel_max + 5 
                candles = self.get_candles(ativo, n=velas_necessarias, size=60)
                if not candles or len(candles) < 5 + mg_nivel_max + 1:
                    time.sleep(1)
                    continue
                
                quadrante_analise_passado = candles[-(5 + mg_nivel_max + 5):-(5 + mg_nivel_max)]
                
                ultimas_tres_velas_passado = quadrante_analise_passado[-3:]
                directions_passado = [get_direction(c, use_doji_filter=self.config.get("doji_filter", False)) for c in ultimas_tres_velas_passado]

                if 'doji' in directions_passado or directions_passado.count('call') == directions_passado.count('put'):
                    time.sleep(1)
                    continue
                
                direcao_sinal_passado = 'put' if directions_passado.count('call') > directions_passado.count('put') else 'call'
                
                if filtro_loss_ativo:
                    vitoria_no_ciclo = False
                    for mg_check in range(mg_nivel_max + 1):
                        vela_resultado = candles[-(5 + mg_nivel_max) + mg_check]
                        if get_direction(vela_resultado, use_doji_filter=self.config.get("doji_filter", False)) == direcao_sinal_passado:
                            vitoria_no_ciclo = True
                            break
                    
                    if vitoria_no_ciclo:
                        if self.consecutive_losses.get(ativo, 0) > 0:
                            self.log(f"Ciclo de WIN no passado em {ativo}. Sequência de loss zerada.", "#2DC937")
                        self.consecutive_losses[ativo] = 0
                    else:
                        self.consecutive_losses[ativo] = self.consecutive_losses.get(ativo, 0) + 1
                        self.log(f"Ciclo de LOSS no passado em {ativo}. Total {self.consecutive_losses[ativo]}/{qtd_loss_necessarios} loss.", "#FF4040")

                    if self.consecutive_losses.get(ativo, 0) >= qtd_loss_necessarios:
                        if not self.apto_para_operar.get(ativo):
                            self.log(f"Condição ATINGIDA! {ativo} está APTO para operar.", "#00FF00")
                        self.apto_para_operar[ativo] = True
                
                if not self.apto_para_operar.get(ativo):
                    time.sleep(1)
                    continue
                
                self.log(f"[ENTRADA AUTORIZADA] Analisando quadrante atual para {ativo}", "#FFD700")

                quadrante_atual = candles[-5:]
                ultimas_tres_atuais = quadrante_atual[-3:]
                directions_atuais = [get_direction(c, use_doji_filter=self.config.get("doji_filter", False)) for c in ultimas_tres_atuais]

                if 'doji' in directions_atuais or directions_atuais.count('call') == directions_atuais.count('put'):
                    self.log(f"Entrada em {ativo} CANCELADA: Sinal atual inválido (doji/empate).", "#FF8000")
                    time.sleep(1)
                    continue

                direcao_entrada_real = 'put' if directions_atuais.count('call') > directions_atuais.count('put') else 'call'

                if self.config.get("filtro_velas_consecutivas", False):
                    if self.get_consecutive_candles_count(ativo) >= 4:
                        self.log(f"Entrada BLOQUEADA em {ativo} (filtro de velas).", "#FFA500")
                        time.sleep(1)
                        continue
                if self.config.get("adx", False):
                    adx_val = self.api.get_adx(ativo, period=14, size=60)
                    if adx_val is not None and adx_val >= 21:
                        self.log(f"Entrada BLOQUEADA em {ativo} (ADX >= 21).", "#FFA500")
                        time.sleep(1)
                        continue
                
                self.log(f"Análise {ativo}: {directions_atuais} -> ENTRANDO para MINORIA: {direcao_entrada_real.upper()}", "#00FFFF")
                
                mg_nivel = 0
                valor_base = self.config['valor']
                valor_entrada = prox_soros if soros_ativo and prox_soros is not None else valor_base
                prox_soros = None

                while mg_nivel <= mg_nivel_max and not self.stop_event.is_set():
                    if mg_nivel > 0: valor_entrada *= 2
                    self.result_stats['ops'] += 1
                    self.entradas_realizadas += 1
                    self.stats_callback(self._stats())
                    labelmg = "" if mg_nivel == 0 else f"(MG{mg_nivel})"
                    self.log(f"Entrando em {ativo} | {direcao_entrada_real.upper()} {labelmg} | Valor: {valor_entrada:.2f}", "#00FFFF")
                    
                    resultado, lucro_op = self.buy(ativo, valor_entrada, direcao_entrada_real, self.config['expiracao'])
                    self.lucro_acumulado += lucro_op
                    self.lucro_callback(self.lucro_acumulado)

                    if resultado is None:
                        self.log(f"EMPATE em {ativo}. Valor devolvido.", "#FFD700")
                        prox_soros = None
                        break
                    elif resultado is True:
                        self.result_stats['wins'] += 1
                        self.log(f"WIN em {ativo} {labelmg} | Lucro: {lucro_op:.2f}", "#2DC937")
                        if soros_ativo and (soros_em_mg or mg_nivel == 0):
                            prox_soros = valor_base + (lucro_op * (soros_percent / 100))
                        if filtro_loss_ativo and esperar_novo_loss_apos_win:
                            self.apto_para_operar[ativo] = False
                            self.consecutive_losses[ativo] = 0
                            self.log(f"WIN! O ativo {ativo} aguardará um novo ciclo de loss.", "#FFA500")
                        break
                    else:
                        self.result_stats['losses'] += 1
                        if mg_nivel < mg_nivel_max:
                            self.log(f"LOSS em {ativo} | Indo para Martingale {mg_nivel+1}", "#FF8000")
                            mg_nivel += 1
                            continue
                        else:
                            self.log(f"LOSS em {ativo} {labelmg} | Perda: {lucro_op:.2f}", "#FF4040")
                            prox_soros = None
                            if filtro_loss_ativo:
                                self.apto_para_operar[ativo] = False
                                self.consecutive_losses[ativo] = 0
                                self.log(f"LOSS no ciclo! O ativo {ativo} aguardará um novo ciclo de loss.", "#FF4040")
                            break
                
                self.stats_callback(self._stats())
                if self.verificar_condicoes_parada():
                    if self.sound_callback: self.sound_callback("limit")
                    if self.finish_callback: self.finish_callback()
                    return
                
            time.sleep(1)
        
        self.log("Robô finalizado pelo usuário.", "#FFA500")
        if self.finish_callback: self.finish_callback()

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

def catalogar_powerboss(api, ativo, minutos=60, mg_niveis=1, qtd_loss_seguidos_analise=2, use_doji_filter=False):
    total_velas_necessarias = minutos + (mg_niveis * 5) + 20 
    candles = api.get_candles(ativo, 60, total_velas_necessarias)
    if not candles or len(candles) < 5 + mg_niveis:
        return None

    win_niveis = [0] * (mg_niveis + 1)
    loss = 0
    total_ciclos = 0
    max_consecutive_count = 0
    
    consecutive_loss_counter = 0
    wins_pos_sequencia = 0
    oportunidades_pos_sequencia = 0
    
    consecutive_count = 0
    last_dir = None
    for c in candles:
        current_dir = get_direction(c, use_doji_filter=use_doji_filter)
        if current_dir != 'doji':
            if current_dir == last_dir:
                consecutive_count += 1
            else:
                last_dir = current_dir
                consecutive_count = 1
            if consecutive_count > max_consecutive_count:
                 max_consecutive_count = consecutive_count

    ciclos_passados = []
    for i in range(0, len(candles) - 5 - mg_niveis, 5):
        quadrante_analise = candles[i : i+5]
        ultimas_tres = quadrante_analise[-3:]
        directions = [get_direction(c, use_doji_filter=use_doji_filter) for c in ultimas_tres]

        if 'doji' in directions or directions.count('call') == directions.count('put'):
            ciclos_passados.append({'resultado': 'invalido'})
            continue

        direcao_entrada = 'put' if directions.count('call') > directions.count('put') else 'call'
        total_ciclos += 1
        
        resultado_encontrado = False
        vitoria_de_primeira = False
        for mg in range(mg_niveis + 1):
            idx_vela_entrada = i + 5 + mg
            if idx_vela_entrada >= len(candles): break
            
            resultado_vela = get_direction(candles[idx_vela_entrada], use_doji_filter=use_doji_filter)
            if resultado_vela == 'doji': break
            
            if resultado_vela == direcao_entrada:
                win_niveis[mg] += 1
                if mg == 0: vitoria_de_primeira = True
                resultado_encontrado = True
                break
        
        if not resultado_encontrado: loss += 1
        ciclos_passados.append({'resultado': 'win' if resultado_encontrado else 'loss', 'win_primeira': vitoria_de_primeira})

    for i in range(len(ciclos_passados)):
        if ciclos_passados[i]['resultado'] == 'loss':
            consecutive_loss_counter += 1
        else:
            consecutive_loss_counter = 0

        if consecutive_loss_counter == qtd_loss_seguidos_analise:
            if (i + 1) < len(ciclos_passados) and ciclos_passados[i+1]['resultado'] != 'invalido':
                oportunidades_pos_sequencia += 1
                if ciclos_passados[i+1]['win_primeira']:
                    wins_pos_sequencia += 1
            consecutive_loss_counter = 0

    if total_ciclos == 0: return None

    total_wins = sum(win_niveis)
    assertividade = (total_wins / total_ciclos * 100) if total_ciclos else 0
    adx_val = api.get_adx(ativo, period=14, size=60)
    
    prob_loss = 1.0 - (assertividade / 100.0)
    prob_2_losses = prob_loss * prob_loss
    
    acerto_pos_loss = (wins_pos_sequencia / oportunidades_pos_sequencia * 100) if oportunidades_pos_sequencia > 0 else 0

    return {
        'ativo': ativo,
        'wins': win_niveis,
        'loss': loss,
        'total': total_ciclos,
        'assertividade': assertividade,
        'mg_niveis': mg_niveis,
        'adx': adx_val,
        'velas_consecutivas': max_consecutive_count,
        'prob_2_losses': prob_2_losses,
        'acerto_pos_loss': acerto_pos_loss,
        'oportunidades_pos_loss': oportunidades_pos_sequencia,
        'wins_pos_loss': wins_pos_sequencia
    }

class BotFullApp(tk.Tk):
    LOG_COLORS = {
        "dark": {
            "#FFD700": "#FFD700", "#00BFFF": "#00BFFF", "#2DC937": "#00FF00",
            "#FF4040": "#FF3030", "#FF8000": "#FFA500", "#FFA500": "#FFD700",
            "#00FFFF": "#00FFFF", "#FFFFFF": "#FFFFFF", "#00FF00": "#00FF00"
        },
        "light": {
            "#FFD700": "#FFD700", "#00BFFF": "#00BFFF", "#2DC937": "#00FF00",
            "#FF4040": "#FF3030", "#FF8000": "#FFA500", "#FFA500": "#FFD700",
            "#00FFFF": "#00FFFF", "#FFFFFF": "#000000", "#00FF00": "#00C800"
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
        
        self.asset_vars = {}
        self.asset_checkboxes = {}

        self.sound_files = {
            "entry": "", "win": "", "loss": "", "limit": "",
            "conexao": "", "conexao_erro": ""
        }
        self.sons_ativos = tk.BooleanVar(value=True)

        self.load_sound_config()
        self.spinner_running = False
        self.create_widgets()
        self.load_login()
        self.after(1000, self.update_clock)

    def _on_mousewheel(self, event):
        self.asset_canvas.yview_scroll(-1 * (event.delta // 120), "units")

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
        frame_ativos.rowconfigure(1, weight=1)
        frame_ativos.columnconfigure(0, weight=1)

        self.entry_busca_ativo = ttk.Entry(frame_ativos)
        self.entry_busca_ativo.grid(row=0, column=0, sticky="ew", padx=5, pady=(5,0))
        self.entry_busca_ativo.bind("<KeyRelease>", self.filter_ativos)

        canvas_frame = ttk.Frame(frame_ativos)
        canvas_frame.grid(row=1, column=0, sticky='nsew', pady=(5,0))
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.asset_canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        self.asset_canvas.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.asset_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.asset_canvas.configure(yscrollcommand=scrollbar.set)

        self.checkbox_frame = ttk.Frame(self.asset_canvas)
        self.asset_canvas.create_window((0, 0), window=self.checkbox_frame, anchor="nw")
        
        self.asset_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.checkbox_frame.bind("<MouseWheel>", self._on_mousewheel)
        
        self.checkbox_frame.bind("<Configure>", lambda e: self.asset_canvas.configure(scrollregion=self.asset_canvas.bbox("all")))
        
        btns_ativos = ttk.Frame(frame_ativos)
        btns_ativos.grid(row=2, column=0, pady=5)
        ttk.Button(btns_ativos, text="Listar Ativos", command=self.atualiza_ativos).pack(side="left", padx=3)
        ttk.Button(btns_ativos, text="Analisar Assertividade", command=self.catalogar_ativo).pack(side="left", padx=3)
        self.lbl_clock = tk.Label(frame_ativos, text="", font=("Arial", 28, "bold"), fg="#FFD700", bg="#222")
        self.lbl_clock.grid(row=3, column=0, pady=(12, 6))

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
        ttk.Checkbutton(frame_config, text="Filtro Velas (>=4)", variable=self.var_filtro_velas).grid(row=row, column=1, columnspan=2, padx=4, pady=3, sticky="w")
        
        # NOVO: Filtro de Doji
        self.var_doji_filter = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame_config, text="Filtro de Doji (vela sem corpo)", variable=self.var_doji_filter).grid(row=row, column=3, columnspan=3, padx=4, pady=3, sticky="w")
        row += 1

        ttk.Label(frame_config, text="Stop Win $:").grid(row=row, column=0, padx=4, pady=3, sticky="e")
        self.entry_stopwin = ttk.Entry(frame_config, width=7)
        self.entry_stopwin.grid(row=row, column=1, padx=4, pady=3)
        ttk.Label(frame_config, text="Stop Loss $:").grid(row=row, column=2, padx=4, pady=3, sticky="e")
        self.entry_stoploss = ttk.Entry(frame_config, width=7)
        self.entry_stoploss.grid(row=row, column=3, padx=4, pady=3)
        self.var_stop = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_config, text="Stop por Lucro", variable=self.var_stop).grid(row=row, column=4, columnspan=2, padx=4, pady=3, sticky="w")
        row += 1

        self.var_filtro_loss_seguidos = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_config, text="Filtro de Loss Seguidos", variable=self.var_filtro_loss_seguidos).grid(row=row, column=0, columnspan=2, padx=4, pady=3, sticky="w")
        ttk.Label(frame_config, text="Qtd Loss:").grid(row=row, column=2, padx=4, pady=3, sticky="e")
        self.spin_loss_seguidos = ttk.Spinbox(frame_config, from_=1, to=10, width=5)
        self.spin_loss_seguidos.set(2)
        self.spin_loss_seguidos.grid(row=row, column=3, padx=4, pady=3)
        row += 1
        self.var_esperar_novo_loss = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_config, text="Aguardar novo ciclo de loss após WIN", variable=self.var_esperar_novo_loss).grid(row=row, column=0, columnspan=3, padx=4, pady=3, sticky="w")
        
        row += 1
        self.var_soros_em_mg = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_config, text="Aplicar Soros após Win no Martingale", variable=self.var_soros_em_mg).grid(row=row, column=0, columnspan=3, padx=4, pady=3, sticky="w")

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
        self.text_log.config(state="normal")
        self.text_log.insert("end", f"{base_message} \n", message_tag)
        self.text_log.config(state="disabled")
        self.text_log.see("end")
        
        def update_spinner(tag, state=0):
            if not getattr(self, "_log_spinner_running", False):
                return
            frames = ["⏳", "⌛"]
            spin = frames[state % len(frames)]
            self.text_log.config(state="normal")
            try:
                line_start = self.text_log.index(f"{tag}.first")
                line_end = f"{line_start} lineend"
                self.text_log.delete(line_start, line_end)
                self.text_log.insert(line_start, f"{base_message} {spin}", tag)
            except tk.TclError:
                return 
            self.text_log.config(state="disabled")
            self.after(500, update_spinner, tag, state + 1)
        
        self.after(500, update_spinner, message_tag)

    def stop_log_spinner(self, tag, final_message, color="#FFD700"):
        self._log_spinner_running = False
        self.text_log.config(state="normal")
        try:
            line_start = self.text_log.index(f"{tag}.first")
            line_end = f"{line_start} lineend"
            self.text_log.delete(line_start, line_end)
            self.text_log.insert(line_start, final_message, f"FINAL_{tag}")
            tag_color = self.get_log_color(color)
            self.text_log.tag_config(f"FINAL_{tag}", foreground=tag_color)
        except tk.TclError:
            self.log_event(final_message, color)
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
            if event == "entry": play_sound(freq=880, dur=180)
            elif event == "win": play_sound(freq=1200, dur=250)
            elif event == "loss": play_sound(freq=400, dur=300)
            elif event == "limit": play_sound(freq=500, dur=180); play_sound(freq=800, dur=220); play_sound(freq=500, dur=180)
            elif event == "conexao_erro": play_sound(freq=200, dur=500); play_sound(freq=120, dur=350)

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
        theme_colors = self.LOG_COLORS.get(self.theme_mode, self.LOG_COLORS["dark"])
        return theme_colors.get(color, self.LOG_COLORS["default"])

    def clear_log(self):
        self.text_log.config(state="normal")
        self.text_log.delete(1.0, tk.END)
        self.text_log.config(state="disabled")

    def atualiza_ativos(self):
        if not self.api or not self.connected:
            self.log_event("Conecte-se para buscar ativos.", "#FF4040")
            return
        self.start_log_spinner("SPINNER_ATIVOS", "Listando ativos, aguarde!")
        def do_update():
            try:
                ativos_all = self.api.get_all_open_time()
                if ativos_all is None:
                    self.after(0, lambda: self.stop_log_spinner("SPINNER_ATIVOS", "Falha ao buscar ativos.", "#FF4040"))
                    return
                ativos = set()
                for tipo_ativo in ['digital', 'turbo']:
                    if tipo_ativo in ativos_all and isinstance(ativos_all[tipo_ativo], dict):
                        for ativo, status_ativo in ativos_all[tipo_ativo].items():
                            if isinstance(status_ativo, dict) and status_ativo.get('open'):
                                if not self.var_otc.get() and '-OTC' in ativo: continue
                                ativos.add(ativo)
                self.ativos = sorted(ativos)
                self.after(0, self.populate_asset_list)
                msg = f"Ativos atualizados ({len(self.ativos)})."
                self.after(0, lambda: self.stop_log_spinner("SPINNER_ATIVOS", msg, "#2DC937"))
            except Exception as e:
                self.after(0, lambda: self.stop_log_spinner("SPINNER_ATIVOS", f"Erro ao buscar ativos: {e}", "#FF4040"))
        threading.Thread(target=do_update, daemon=True).start()

    def populate_asset_list(self):
        for widget in self.checkbox_frame.winfo_children(): widget.destroy()
        self.asset_checkboxes.clear()
        for asset in self.ativos:
            if asset not in self.asset_vars: self.asset_vars[asset] = tk.BooleanVar()
            var = self.asset_vars[asset]
            cb = ttk.Checkbutton(self.checkbox_frame, text=asset, variable=var)
            self.asset_checkboxes[asset] = cb
            cb.pack(anchor="w", padx=5, pady=2)
            cb.bind("<MouseWheel>", self._on_mousewheel)
        self.asset_canvas.yview_moveto(0)

    def filter_ativos(self, event=None):
        texto = self.entry_busca_ativo.get().strip().lower()
        for asset, checkbox in self.asset_checkboxes.items():
            if texto in asset.lower():
                if not checkbox.winfo_ismapped(): checkbox.pack(anchor="w", padx=5, pady=2)
            else:
                checkbox.pack_forget()

    def get_selected_ativos(self):
        return [asset for asset, var in self.asset_vars.items() if var.get()]

    def catalogar_ativo(self):
        if not self.api or not self.connected:
            self.log_event("Conecte-se para analisar assertividade.", "#FF4040"); return
        selecionados = self.get_selected_ativos()
        try: mg_niveis = int(self.combo_mg_niveis.get()) if self.combo_mg_niveis.get() else 1
        except Exception: mg_niveis = 1
        try: qtd_loss_analise = int(self.spin_loss_seguidos.get())
        except Exception: qtd_loss_analise = 2
            
        ativos_analisar = selecionados or self.ativos
        if not ativos_analisar: self.log_event("Nenhum ativo para analisar.", "#FF8000"); return
        
        resultados = []
        self.start_log_spinner("SPINNER_ASSERT", f"Analisando assertividade de {len(ativos_analisar)} ativo(s)...")
        
        def do_catalog():
            try: payouts = self.api.get_all_profit()
            except Exception: payouts = {}; self.after(0, lambda: self.log_event("Não foi possível obter os payouts.", "#FF8000"))

            for ativo in ativos_analisar:
                try:
                    res = catalogar_powerboss(self.api, ativo, minutos=60, mg_niveis=mg_niveis, qtd_loss_seguidos_analise=qtd_loss_analise, use_doji_filter=self.var_doji_filter.get())
                    if res:
                        payout_info = payouts.get(ativo, {})
                        payout = payout_info.get('turbo') or payout_info.get('binary')
                        res['payout'] = payout
                        resultados.append(res)
                except Exception as e: print(f"Erro catalogando {ativo}: {e}")
            
            if not resultados: self.after(0, lambda: self.stop_log_spinner("SPINNER_ASSERT", "Nenhum ativo pôde ser analisado.", "#FF4040")); return
            
            melhores = sorted(resultados, key=lambda x: x['assertividade'], reverse=True)
            
            self.after(0, lambda: self.stop_log_spinner("SPINNER_ASSERT", f"Melhores Ativos (Análise Pós-{qtd_loss_analise} Loss):", "#FFD700"))
            for r in melhores[:5]:
                wins_str_parts = [f"W0: {r['wins'][0]}"]
                for mg in range(1, len(r['wins'])): wins_str_parts.append(f"MG{mg}: {r['wins'][mg]}")
                wins_str = " | ".join(wins_str_parts)
                payout_val = r.get('payout')
                payout_str = f" | Payout: {payout_val*100:.0f}%" if isinstance(payout_val, float) else ""
                
                acerto_pos_loss_str = ""
                if r['oportunidades_pos_loss'] > 0:
                    acerto_pos_loss_str = f" | Acerto Pós-Loss (1ª Vela): {r['acerto_pos_loss']:.0f}% ({r['wins_pos_loss']}/{r['oportunidades_pos_loss']})"
                
                msg = f"{r['ativo']} -> {r['assertividade']:.2f}%{payout_str} | {wins_str} | Loss: {r['loss']}{acerto_pos_loss_str}"
                self.after(0, lambda m=msg: self.log_event(m, "#FFD700"))
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
                fg = "#FF4040" if saldo < 0 else ("#00FF00" if self.theme_mode == "dark" else "#006400")
                self.lbl_saldo.config(text=f"Saldo: R$ {format_money(saldo)}", fg=fg, bg="#222" if self.theme_mode == "dark" else "#F5F6FA")
            except Exception: pass

    def start_robot(self):
        if self.robot_thread and self.robot_thread.is_alive(): self.log_event("Robô já está rodando!", "#FF8000"); return
        if not self.api or not self.connected: self.log_event("Conecte-se antes de iniciar o robô.", "#FF4040"); return
        ativos = self.get_selected_ativos()
        if not ativos: self.log_event("Selecione ao menos um ativo.", "#FF8000"); return
        
        self.log_event("Iniciando robô para os seguintes ativos:", "#00BFFF")
        try:
            payouts = self.api.get_all_profit()
            for ativo in ativos:
                payout_info = payouts.get(ativo, {})
                payout = payout_info.get('turbo') or payout_info.get('binary')
                payout_str = f"{payout*100:.0f}%" if isinstance(payout, float) else "N/A"
                self.log_event(f"-> {ativo} (Payout: {payout_str})", self.get_log_color("#FFFFFF"))
        except Exception as e:
            self.log_event(f"Não foi possível obter os payouts atuais: {e}", "#FF8000")

        try:
            config = {
                "valor": float(self.entry_valor.get().replace(",", ".")), "expiracao": int(self.combo_exp.get()),
                "entradas": int(self.spin_entradas.get()), "soros": int(self.spin_soros.get()),
                "otc": self.var_otc.get(), "martingale": self.var_martingale.get(),
                "mg_niveis": int(self.combo_mg_niveis.get()) if self.combo_mg_niveis.get() else 1,
                "adx": self.var_adx.get(), "filtro_velas_consecutivas": self.var_filtro_velas.get(),
                "doji_filter": self.var_doji_filter.get(), # NOVO
                "stop_lucro": self.var_stop.get(),
                "lucro": float(self.entry_stopwin.get().replace(",", ".")) if self.entry_stopwin.get() else 0.0,
                "perda": float(self.entry_stoploss.get().replace(",", ".")) if self.entry_stoploss.get() else 0.0,
                "ativos": ativos,
                "filtro_loss_seguidos": self.var_filtro_loss_seguidos.get(),
                "qtd_loss_seguidos": int(self.spin_loss_seguidos.get()),
                "esperar_novo_loss": self.var_esperar_novo_loss.get(),
                "soros_em_mg": self.var_soros_em_mg.get()
            }
        except Exception as e: self.log_event(f"Preencha corretamente as configurações. Erro: {e}", "#FF4040"); return
            
        self.robot_stop.clear()
        self.robot_stopped_manual = False
        self.lbl_robostatus.config(text="Operando", foreground="#FFB000")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.robot = PowerBossRobot(api=self.api, config=config, log_callback=self.log_event, stats_callback=self.update_stats,
            lucro_callback=self.update_lucro, stop_event=self.robot_stop, sound_callback=self.robot_sound,
            finish_callback=self.robot_finished, update_saldo_callback=self.app_update_saldo)
        self.robot_thread = threading.Thread(target=self.robot.run, daemon=True)
        self.robot_thread.start()

    def stop_robot(self):
        if self.robot_stop: self.robot_stop.set()
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
        cor = "#FF4040" if valor < 0 else ("#00FF00" if self.theme_mode == "dark" else "#006400")
        sinal = "" if valor >= 0 else "-"
        texto = f"R${sinal}{abs(valor):,.2f}".replace('.', ',')
        self.lbl_lucro.config(text=texto, foreground=cor)

    def reset_lucro(self):
        self.lucro_acumulado_display = 0.0
        self.update_lucro(self.lucro_acumulado_display)
        self.log_event("Lucro/Prejuízo zerado manualmente.", "#FFA500")

if __name__ == "__main__":
    app = BotFullApp()
    app.mainloop()