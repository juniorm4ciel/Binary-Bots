import PySimpleGUI as sg
import threading
import time
import datetime
import numpy as np
from iqoptionapi.stable_api import IQ_Option

# ===================== Funções auxiliares =========================

ADX_PERIOD = 14
ADX_LIMIAR = 21  # Opera até 20, bloqueia se ADX >= 21

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

def catalogar_mhi(api, ativo, minutos=50):
    n_candles = minutos + 6
    candles = api.get_candles(ativo, 60, n_candles, time.time())
    candles = sorted(candles, key=lambda x: x['from'])
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
    return (f"Resumo da catalogação última hora [{ativo}]:\n"
            f"Wins de primeira: {win}\n"
            f"Wins com gale: {mg1}\n"
            f"Loss: {loss}\n"
            f"Assertividade: {assertividade:.2f}%\n"
            f"Total operações simuladas: {total}")

def calcular_repeticao_velas(api, ativo, minutos=50):
    n_candles = minutos + 6
    candles = api.get_candles(ativo, 60, n_candles, time.time())
    candles = sorted(candles, key=lambda x: x['from'])
    repeticoes = 0
    total = 0
    for i in range(5, minutos+5):
        ultimos = candles[i-5:i]
        if any(c['close'] == c['open'] for c in ultimos):
            continue
        cores = ['c' if c['close'] > c['open'] else 'p' for c in ultimos]
        maioria = 'c' if cores.count('c') > cores.count('p') else 'p'
        sexta = candles[i]
        cor_sexta = 'c' if sexta['close'] > sexta['open'] else 'p' if sexta['close'] < sexta['open'] else 'd'
        if cor_sexta == maioria:
            repeticoes += 1
        total += 1
    indice = (repeticoes / total * 100) if total else 0
    return indice, repeticoes, total

def build_layout():
    sg.theme('DarkAmber')
    col_ativos = [
        [sg.Text('Buscar ativo:'), sg.Input('', key='busca_ativo', size=(18,1), enable_events=True)],
        [sg.Text('Ativos Disponíveis')],
        [sg.Listbox(values=[], select_mode=sg.LISTBOX_SELECT_MODE_MULTIPLE, size=(22,8), key='ativos', enable_events=True)],
        [sg.Button('Atualizar Ativos', key='atualizar_ativos')],
    ]
    col_conexao = [
        [sg.Text('Email', size=(7,1)), sg.Input(key='email', size=(22,1))],
        [sg.Text('Senha', size=(7,1)), sg.Input(key='senha', password_char='*', size=(22,1))],
        [sg.Text('Conta', size=(7,1)), sg.Combo(['PRACTICE', 'REAL'], default_value='PRACTICE', key='conta', readonly=True, size=(10,1))],
        [sg.Button('Conectar', key='conectar', size=(10,1)), sg.Button('Desconectar', key='desconectar', size=(10,1), disabled=True)],
        [sg.Text('Saldo:'), sg.Text('0.00', key='saldo', size=(10,1)), sg.Button('Atualizar Saldo', key='atualizar_saldo', size=(15,1))],
    ]
    col_config = [
        [sg.Text('Valor ($):'), sg.Input('25', key='valor', size=(7,1)),
         sg.Text('Expiração (min):'), sg.Combo(['1','2','3','4','5'], default_value='1', key='expiracao', size=(4,1)),
         sg.Text('Entradas:'), sg.Spin([i for i in range(1, 21)], initial_value=3, key='entradas', size=(3,1))
         ],
        [sg.Text('Soros (%):'), sg.Spin([i for i in range(0,101,5)], initial_value=0, key='soros', size=(4,1)),
         sg.Checkbox('Incluir OTC', key='otc', default=True),
         sg.Checkbox('Martingale', key='martingale', default=True), 
         sg.Text('Níveis:'), sg.Combo(['1','2','3','4','5'], default_value='1', key='mg_niveis', size=(3,1), readonly=True)
         ],
        [sg.Checkbox('Usar ADX', key='adx', default=True),
         sg.Text(f'Período: {ADX_PERIOD}', size=(12,1)),
         sg.Text(f'Limiar: {ADX_LIMIAR-1}', size=(12,1))
         ],
        [sg.Checkbox('Operar por Lucro/Stop Loss', key='stop_lucro', default=False),
         sg.Text('Lucro ($):'), sg.Input('', key='lucro', size=(7,1)),
         sg.Text('Perda ($):'), sg.Input('', key='perda', size=(7,1))]
    ]
    col_controle = [
        [sg.Button('Iniciar Robô', key='start', button_color=('white', 'green'), size=(12,1)),
         sg.Button('Parar Robô', key='stop', button_color=('white', 'red'), size=(12,1), disabled=True),
         sg.Text('Status:', size=(6,1)), sg.Text('Desconectado', key='status', size=(13,1), text_color='red')]
    ]
    col_stats = [
        [sg.Text('Op.:', size=(4,1)), sg.Text('0', key='ops', size=(4,1)),
         sg.Text('Wins:', size=(5,1)), sg.Text('0', key='wins', size=(4,1)),
         sg.Text('Losses:', size=(7,1)), sg.Text('0', key='losses', size=(4,1)),
         sg.Text('Taxa:', size=(5,1)), sg.Text('0%', key='taxa', size=(5,1))]
    ]
    layout = [
        [sg.Frame('Conexão', col_conexao), sg.Frame('Configuração', col_config), sg.Frame('Ativos', col_ativos)],
        [sg.HorizontalSeparator()],
        col_controle,
        col_stats,
        [sg.HorizontalSeparator()],
        [sg.Text('Horário:', font='Any 12 bold'), sg.Text('', key='relogio', font='Any 13 bold', text_color='#00FF00')],
        [sg.Text('Logs:', font='Any 10 bold')],
        [
            sg.Multiline('', key='logs', size=(100,18), autoscroll=True, disabled=True, text_color='#FFD700', background_color='#222222'),
            sg.Button('Limpar Log', key='clear_log', size=(12,1))
        ],
        [sg.Button('Tema Claro/Escuro', key='tema')]
    ]
    return layout

def is_mhi_entry_time():
    agora = datetime.datetime.now()
    return (agora.minute % 5 == 0) and (agora.second == 0)

class RoboThread(threading.Thread):
    def __init__(self, window, config, api=None):
        super().__init__()
        self.window = window
        self.config = config
        self.stop_event = threading.Event()
        self.result_stats = {'ops': 0, 'wins': 0, 'losses': 0}
        self.api = api
        self.lucro_acumulado = 0.0
        self.entradas_realizadas = 0

    def log(self, msg, cor='white'):
        now = datetime.datetime.now().strftime('%H:%M:%S')
        self.window.write_event_value('-LOG-', (now, msg, cor))

    def get_saldo(self):
        try:
            return self.api.get_balance()
        except Exception:
            return 0.0

    def get_candles(self, ativo, n=5, size=60):
        try:
            candles = self.api.get_candles(ativo, size, n, time.time())
            candles = sorted(candles, key=lambda x: x['from'])
            return candles
        except Exception:
            return []

    def buy(self, ativo, valor, direcao, exp):
        try:
            _, id = self.api.buy(valor, ativo, direcao, exp)
            if not id:
                self.log(f"Falha ao enviar ordem para {ativo}.", 'red')
                return None, 0.0
            max_wait = 120
            start = time.time()
            while True:
                status, lucro = self.api.check_win_v4(id)
                if status is not None:
                    return status, lucro
                if (time.time() - start) > max_wait:
                    self.log("Timeout ao obter resultado da ordem!", 'red')
                    return None, 0.0
                if self.stop_event.is_set():
                    return None, 0.0
                time.sleep(0.2)
        except Exception as e:
            self.log(f"Erro na ordem: {e}", 'red')
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

    def aguardar_ate_proxima_entrada(self):
        while not self.stop_event.is_set():
            agora = datetime.datetime.now()
            if agora.minute % 5 == 0 and agora.second == 0:
                break
            time.sleep(0.2)

    def verificar_condicoes_parada(self):
        if not self.config['stop_lucro']:
            if self.entradas_realizadas >= self.config['entradas']:
                self.log(f"Robô parou: número máximo de entradas atingido ({self.entradas_realizadas}).", 'yellow')
                self.window.write_event_value('-FIM-', None)
                return True
        if self.config['stop_lucro']:
            alvo_lucro = self.config['lucro']
            alvo_perda = self.config['perda']
            if alvo_lucro > 0 and self.lucro_acumulado >= alvo_lucro:
                self.log(f"Stop WIN atingido! Lucro: {self.lucro_acumulado:.2f}", 'yellow')
                self.window.write_event_value('-FIM-', None)
                return True
            if alvo_perda > 0 and abs(self.lucro_acumulado) >= alvo_perda:
                self.log(f"Stop LOSS atingido! Prejuízo: {self.lucro_acumulado:.2f}", 'yellow')
                self.window.write_event_value('-FIM-', None)
                return True
        return False

    def run(self):
        self.log("Robô iniciado! Aguarde análise dos ativos...", 'yellow')
        ativos = list(self.config['ativos'])
        if not ativos:
            self.log("Nenhum ativo selecionado!", 'red')
            self.window.write_event_value('-FIM-', None)
            return
        for ativo in ativos:
            try:
                cat = catalogar_mhi(self.api, ativo, minutos=50)
                self.log(cat, 'yellow')
                indice, rep, tot = calcular_repeticao_velas(self.api, ativo, minutos=50)
                self.log(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [{ativo}] Índice de repetição de velas: {indice:.2f}% ({rep}/{tot})", 'orange')
            except Exception as e:
                self.log(f"Erro ao catalogar {ativo}: {e}", 'red')

        saldo_inicial = self.get_saldo()
        self.window.write_event_value('-SALDO-', saldo_inicial)
        self.log(f"Saldo inicial: {saldo_inicial:.2f}", '#dddddd')

        self.aguardar_ate_proxima_entrada()

        self.lucro_acumulado = 0.0
        self.entradas_realizadas = 0
        self.window.write_event_value('-LUCRO-', self.lucro_acumulado)

        mg_nivel_max = int(self.config.get('mg_niveis', 1))

        while not self.stop_event.is_set():
            if self.verificar_condicoes_parada():
                return

            agora = datetime.datetime.now()
            if agora.minute % 5 == 0 and agora.second == 0:
                for ativo in ativos:
                    if self.stop_event.is_set():
                        break
                    if self.verificar_condicoes_parada():
                        return

                    direcao = self.sinal_mhi(ativo)
                    if direcao is None:
                        self.log(f"[{ativo}] Sem sinal MHI (doji/quadrante indefinido ou empate), pulando ciclo.", 'orange')
                        continue

                    # Filtro ADX: opera se ADX < 21 (até 20)
                    if self.config['adx']:
                        candles = self.get_candles(ativo, n=ADX_PERIOD+1, size=60)
                        adx, plus_di, minus_di = calculate_adx(candles)
                        if adx is not None and adx >= ADX_LIMIAR:
                            self.log(f"[{ativo}] ADX ({adx:.2f} >= {ADX_LIMIAR}), operação ignorada.", 'orange')
                            continue

                    valor = self.config['valor']
                    exp = self.config['expiracao']
                    mg_nivel = 0
                    operacao_feita = False
                    while mg_nivel <= mg_nivel_max and not self.stop_event.is_set():
                        self.log(f"Ativo: {ativo} | Entrada: {mg_nivel+1}/{mg_nivel_max+1} | {direcao.upper()} | Valor: {valor:.2f}", '#00FFFF')
                        resultado, lucro_op = self.buy(ativo, valor, direcao, exp)
                        self.result_stats['ops'] += 1
                        if resultado is None and lucro_op == 0.0:
                            self.log(f"EMPATE ou erro na operação em {ativo} | Valor devolvido.", 'yellow')
                            break
                        self.lucro_acumulado += lucro_op
                        self.window.write_event_value('-LUCRO-', self.lucro_acumulado)
                        if self.verificar_condicoes_parada():
                            return
                        if resultado is True:
                            operacao_feita = True
                            self.result_stats['wins'] += 1
                            self.log(f"WIN no {ativo} com {direcao.upper()} | Lucro: {lucro_op:.2f}", 'green')
                            break
                        elif resultado is False:
                            if mg_nivel < mg_nivel_max:
                                self.log(f"LOSS no {ativo} | Indo para Martingale {mg_nivel+1}", 'orange')
                                mg_nivel += 1
                                valor *= 2
                                continue
                            else:
                                operacao_feita = True
                                self.result_stats['losses'] += 1
                                self.log(f"LOSS no {ativo} com {direcao.upper()} | Perda: {lucro_op:.2f}", 'red')
                                break
                        taxa = (self.result_stats['wins']/self.result_stats['ops']*100) if self.result_stats['ops'] else 0
                        self.window.write_event_value('-STATS-', {
                            'ops': self.result_stats['ops'],
                            'wins': self.result_stats['wins'],
                            'losses': self.result_stats['losses'],
                            'taxa': f"{taxa:.1f}%"
                        })
                    taxa = (self.result_stats['wins']/self.result_stats['ops']*100) if self.result_stats['ops'] else 0
                    self.window.write_event_value('-STATS-', {
                        'ops': self.result_stats['ops'],
                        'wins': self.result_stats['wins'],
                        'losses': self.result_stats['losses'],
                        'taxa': f"{taxa:.1f}%"
                    })
                    if operacao_feita and not self.config['stop_lucro']:
                        self.entradas_realizadas += 1
                        if self.verificar_condicoes_parada():
                            return
                self.aguardar_ate_proxima_entrada()
            else:
                time.sleep(0.2)

        self.log("Robô finalizado pelo usuário.", 'orange')
        self.window.write_event_value('-FIM-', None)

def main():
    layout = build_layout()
    window = sg.Window('Robô MHI IQ Option - PySimpleGUI', layout, finalize=True, resizable=True)
    robo_thread = None
    tema_claro = False
    ativos_cache = []
    ativos_mostrados = []
    api_iq = None

    relogio_atual = datetime.datetime.now().strftime('%H:%M:%S')
    window['relogio'].update(relogio_atual)

    while True:
        event, values = window.read(timeout=200)
        try:
            window['relogio'].update(datetime.datetime.now().strftime('%H:%M:%S'))
        except Exception:
            pass

        if event == sg.WIN_CLOSED:
            if robo_thread:
                robo_thread.stop_event.set()
            break

        if event == 'tema':
            tema_claro = not tema_claro
            sg.theme('DefaultNoMoreNagging' if tema_claro else 'DarkAmber')
            window.close()
            window = sg.Window('Robô MHI IQ Option - PySimpleGUI', build_layout(), finalize=True, resizable=True)
            continue

        if event == 'atualizar_ativos':
            if not api_iq:
                window['logs'].print(f"Conecte-se para buscar ativos.", text_color='red')
                continue
            try:
                ativos_all = api_iq.get_all_open_time()
                if not ativos_all:
                    window['logs'].print("Falha ao obter lista de ativos. Tente novamente mais tarde.", text_color='red')
                    continue
                ativos = []
                for tipo in ['turbo', 'binary']:
                    for ativo, status_ativo in ativos_all[tipo].items():
                        if status_ativo['open']:
                            if tipo == "turbo" and (not values['otc'] and '-OTC' in ativo):
                                continue
                            ativos.append(ativo)
                ativos_cache = sorted(ativos)
                ativos_mostrados = ativos_cache.copy()
                window['ativos'].update(ativos_mostrados)
                window['busca_ativo'].update('')
                window['logs'].print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Lista de ativos atualizada ({len(ativos_cache)}).", text_color='#00FF00')
                # Análise automática dos melhores ativos
                best_assert = None
                min_rep = None
                best_ativo = None
                min_rep_ativo = None
                resumo_catalogacao = {}
                resumo_repeticao = {}
                for ativo in ativos_cache:
                    try:
                        cat = catalogar_mhi(api_iq, ativo, minutos=50)
                        indice, rep, tot = calcular_repeticao_velas(api_iq, ativo, minutos=50)
                        assertiv = float(cat.split('Assertividade: ')[1].split('%')[0].replace(',', '.'))
                        resumo_catalogacao[ativo] = (cat, assertiv)
                        resumo_repeticao[ativo] = (indice, rep, tot)
                        if (best_assert is None) or (assertiv > best_assert):
                            best_assert = assertiv
                            best_ativo = ativo
                        if (min_rep is None) or (indice < min_rep):
                            min_rep = indice
                            min_rep_ativo = ativo
                    except Exception as e:
                        window['logs'].print(f"Erro ao catalogar {ativo}: {e}", text_color='red')
                if best_ativo:
                    cat, assertiv = resumo_catalogacao[best_ativo]
                    window['logs'].print(cat, text_color="yellow")
                    indice, rep, tot = resumo_repeticao[best_ativo]
                    now = datetime.datetime.now().strftime('%H:%M:%S')
                    window['logs'].print(f"[{now}] [{best_ativo}] Índice de repetição de velas: {indice:.2f}% ({rep}/{tot})", text_color="orange")
                if min_rep_ativo and min_rep_ativo != best_ativo:
                    cat, assertiv = resumo_catalogacao[min_rep_ativo]
                    window['logs'].print(cat, text_color="#44FF44")
                    indice, rep, tot = resumo_repeticao[min_rep_ativo]
                    now = datetime.datetime.now().strftime('%H:%M:%S')
                    window['logs'].print(f"[{now}] [{min_rep_ativo}] Índice de repetição de velas: {indice:.2f}% ({rep}/{tot})", text_color="#44FF44")
            except Exception as e:
                window['logs'].print(f"Erro ao buscar ativos: {e}", text_color='red')

        if event == 'busca_ativo':
            texto_busca = values['busca_ativo'].strip().upper()
            if ativos_cache:
                if texto_busca:
                    ativos_mostrados = [a for a in ativos_cache if texto_busca in a.upper()]
                else:
                    ativos_mostrados = ativos_cache.copy()
                window['ativos'].update(ativos_mostrados)

        if event == "ativos":
            if api_iq and values["ativos"]:
                ativo = values["ativos"][0]
                try:
                    cat = catalogar_mhi(api_iq, ativo, minutos=50)
                    window["logs"].print(cat, text_color="yellow")
                    indice, rep, tot = calcular_repeticao_velas(api_iq, ativo, minutos=50)
                    now = datetime.datetime.now().strftime('%H:%M:%S')
                    window["logs"].print(f"[{now}] [{ativo}] Índice de repetição de velas: {indice:.2f}% ({rep}/{tot})", text_color="orange")
                except Exception as e:
                    window["logs"].print(f"Erro ao catalogar {ativo}: {e}", text_color="red")
            elif not api_iq:
                window["logs"].print("Conecte-se para analisar ativos.", text_color="red")

        if event == 'conectar':
            email = values['email']
            senha = values['senha']
            conta = values['conta'].upper()
            if not email or not senha:
                window['logs'].print(f"Preencha email e senha.", text_color='red')
                continue
            try:
                api = IQ_Option(email, senha)
                status, reason = api.connect()
                if status:
                    api.change_balance(conta)
                    saldo = api.get_balance()
                    window['status'].update('Conectado', text_color='green')
                    window['conectar'].update(disabled=True)
                    window['desconectar'].update(disabled=False)
                    window['start'].update(disabled=False)
                    window['saldo'].update(f"{saldo:.2f}")
                    window['logs'].print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Conectado com sucesso! Saldo: {saldo:.2f}", text_color='green')
                    api_iq = api
                else:
                    window['status'].update('Desconectado', text_color='red')
                    window['logs'].print(f"Erro ao conectar: {reason}", text_color='red')
                    api_iq = None
            except Exception as e:
                window['logs'].print(f"Exceção: {e}", text_color='red')
                api_iq = None

        if event == 'desconectar':
            if robo_thread:
                robo_thread.stop_event.set()
            window['status'].update('Desconectado', text_color='red')
            window['conectar'].update(disabled=False)
            window['desconectar'].update(disabled=True)
            window['start'].update(disabled=True)
            window['logs'].print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Desconectado.", text_color='red')
            api_iq = None

        if event == 'atualizar_saldo':
            if not api_iq:
                window['logs'].print(f"Conecte-se para buscar saldo.", text_color='red')
                continue
            try:
                saldo = api_iq.get_balance()
                window['saldo'].update(f"{saldo:.2f}")
                window['logs'].print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Saldo atualizado: {saldo:.2f}", text_color='#00FF00')
            except Exception as e:
                window['logs'].print(f"Erro ao buscar saldo: {e}", text_color='red')

        if event == 'start':
            if robo_thread and robo_thread.is_alive():
                window['logs'].print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Já está rodando!", text_color='orange')
                continue
            if not api_iq:
                window['logs'].print(f"Conecte-se antes de iniciar o robô.", text_color='red')
                continue
            config = {
                'email': values['email'],
                'senha': '*****',
                'conta': values['conta'],
                'valor': float(values['valor']),
                'expiracao': int(values['expiracao']),
                'entradas': int(values['entradas']),
                'soros': int(values['soros']),
                'otc': values['otc'],
                'martingale': values['martingale'],
                'mg_niveis': int(values['mg_niveis']),
                'adx': values['adx'],
                'stop_lucro': values['stop_lucro'],
                'lucro': float(values['lucro']) if values['lucro'] else 0.0,
                'perda': float(values['perda']) if values['perda'] else 0.0,
                'ativos': values['ativos'] if values['ativos'] else ativos_cache
            }
            config_log = dict(config)
            config_log['senha'] = '*****'
            window['logs'].print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Robô iniciado com config: {config_log}", text_color='#00FFFF')
            window['start'].update(disabled=True)
            window['stop'].update(disabled=False)
            window['status'].update('Operando', text_color='yellow')
            window['ops'].update('0')
            window['wins'].update('0')
            window['losses'].update('0')
            window['taxa'].update('0%')
            robo_thread = RoboThread(window, config, api=api_iq)
            robo_thread.start()

        if event == 'stop':
            if robo_thread:
                robo_thread.stop_event.set()
            window['logs'].print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Robô parado.", text_color='orange')
            window['start'].update(disabled=False)
            window['stop'].update(disabled=True)
            window['status'].update('Parado', text_color='orange')

        if event == '-LOG-':
            hora, msg, cor = values[event]
            window['logs'].print(f"[{hora}] {msg}", text_color=cor)

        if event == '-STATS-':
            stats = values[event]
            window['ops'].update(str(stats['ops']))
            window['wins'].update(str(stats['wins']))
            window['losses'].update(str(stats['losses']))
            window['taxa'].update(stats['taxa'])

        if event == '-SALDO-':
            saldo = values[event]
            window['saldo'].update(f"{saldo:.2f}")

        if event == '-FIM-':
            if robo_thread:
                robo_thread.join(timeout=1)
                robo_thread = None
            window['logs'].print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Thread do robô finalizada!", text_color='red')
            window['start'].update(disabled=False)
            window['stop'].update(disabled=True)
            window['status'].update('Parado', text_color='orange')

        if event == 'clear_log':
            window['logs'].update('')

    window.close()

if __name__ == '__main__':
    main()