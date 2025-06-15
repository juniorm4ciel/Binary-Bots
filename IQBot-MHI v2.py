import sys
import time
import datetime
import threading
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QCheckBox, QListWidget,
    QPlainTextEdit, QMessageBox, QFrame, QListWidgetItem
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QPalette, QColor, QFont

from iqoptionapi.stable_api import IQ_Option

def calculate_adx(candles, period=14):
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

class WorkerSignals(QObject):
    log_signal = pyqtSignal(str)
    stats_signal = pyqtSignal(int, int, int, float)

class RoboThread(threading.Thread):
    def __init__(self, parent, api, signals):
        super().__init__()
        self.parent = parent
        self.api = api
        self.signals = signals
        self.stop_flag = False
        self.last_signal_time = {}
        self.martingale_status = {}

    def catalogar_mhi_classico(self, candles, ativo):
        """
        Catalogação clássica MHI:
        - Taxa de acerto MHI (entrada minoria)
        - Taxa de repetição (próxima vela repete a maioria)
        Considera os últimos 60 minutos (60 velas)
        """
        if len(candles) < 61:
            self.signals.log_signal.emit(f"{ativo}: Não há candles suficientes para catalogação MHI.")
            return

        acertou_mhi = 0
        repetiu_maj = 0
        total = 0

        for i in range(0, 60, 3):
            grupo = candles[i:i+3]
            if len(grupo) < 3:
                break
            proxima = candles[i+3] if i+3 < len(candles) else None
            if not proxima:
                continue
            up = sum(1 for c in grupo if c['close'] > c['open'])
            down = sum(1 for c in grupo if c['close'] < c['open'])
            # ignora grupo com doji
            if any(c['close'] == c['open'] for c in grupo):
                continue
            # maioria/minoria
            if up > down:
                maj = 'alta'
                mino = 'baixa'
            elif down > up:
                maj = 'baixa'
                mino = 'alta'
            else:
                continue  # empate, ignora

            # próxima vela é de alta ou baixa?
            if proxima['close'] == proxima['open']:
                continue  # doji, ignora

            if maj == 'alta' and proxima['close'] > proxima['open']:
                repetiu_maj += 1
            if maj == 'baixa' and proxima['close'] < proxima['open']:
                repetiu_maj += 1

            # MHI: entrada na minoria
            if mino == 'alta' and proxima['close'] > proxima['open']:
                acertou_mhi += 1
            if mino == 'baixa' and proxima['close'] < proxima['open']:
                acertou_mhi += 1

            total += 1

        if total == 0:
            self.signals.log_signal.emit(f"{ativo}: Não foi possível calcular catálogo MHI (sem grupos válidos).")
            return

        taxa_mhi = (acertou_mhi / total) * 100
        taxa_rep = (repetiu_maj / total) * 100
        msg = (
            f"{ativo} | Catálogo MHI 60min: "
            f"MHI Acerto: {acertou_mhi}/{total} ({taxa_mhi:.1f}%) | "
            f"Repetição: {repetiu_maj}/{total} ({taxa_rep:.1f}%)"
        )
        self.signals.log_signal.emit(msg)

    def run(self):
        parent = self.parent
        adx_period = 14
        adx_limiar = 20
        max_entradas = parent.entradas_spinbox.value()
        lucro_alvo = float(parent.lucro_entry.text()) if parent.lucro_entry.text() else float('inf')
        perda_alvo = float(parent.perda_entry.text()) if parent.perda_entry.text() else float('inf')
        saldo_inicial = self.api.get_balance() if self.api else 1000
        ativos = parent.get_selected_ativos()
        total_ops = 0
        wins = 0
        losses = 0
        self.operacoes_realizadas = {a: 0 for a in ativos}

        while not self.stop_flag:
            if parent.lucro_stop_loss_check.isChecked():
                saldo_atual = self.api.get_balance() if self.api else 0
                if saldo_atual >= saldo_inicial + lucro_alvo:
                    self.signals.log_signal.emit(f"Lucro alvo de ${lucro_alvo:.2f} atingido. Parando operações.")
                    parent.stop_robo()
                    return
                elif saldo_atual <= saldo_inicial - perda_alvo:
                    self.signals.log_signal.emit(f"Perda alvo de ${perda_alvo:.2f} atingido. Parando operações.")
                    parent.stop_robo()
                    return
            all_ativos_limitados = all(self.operacoes_realizadas.get(ativo, 0) >= max_entradas for ativo in ativos)
            if not parent.lucro_stop_loss_check.isChecked() and all_ativos_limitados:
                self.signals.log_signal.emit("Número máximo de entradas atingido em todos os ativos. Parando o robô.")
                parent.stop_robo()
                return

            for ativo in ativos:
                if self.stop_flag:
                    break

                # 1. Executar Martingale se necessário, SEM checar ADX
                mg = self.martingale_status.get(ativo)
                if mg:
                    now = datetime.datetime.now()
                    if now.second == 0:
                        self.signals.log_signal.emit(f"Executando MARTINGALE {mg['nivel']} em {ativo}, direção {mg['direcao'].upper()}, valor ${mg['valor']:.2f}")
                        saldo = self.api.get_balance()
                        if saldo < mg['valor']:
                            self.signals.log_signal.emit(f"Erro: Saldo insuficiente para Martingale em {ativo}.")
                            self.martingale_status.pop(ativo, None)
                            continue
                        check, operation_id = self.api.buy(mg['valor'], ativo, mg['direcao'], mg['exp'])
                        if check:
                            self.operacoes_realizadas[ativo] += 1
                            self.last_signal_time[ativo] = (now.hour, now.minute)
                            self.signals.log_signal.emit(f"Martingale iniciado: {mg['direcao'].upper()} em {ativo} valor ${mg['valor']:.2f} expiração {mg['exp']}min. ID: {operation_id}")
                            # Espera resultado do MG
                            for _ in range(60):
                                if self.stop_flag:
                                    break
                                try:
                                    result = self.api.check_win_v3(operation_id)
                                    if result is not None and result != operation_id:
                                        break
                                except Exception:
                                    pass
                                time.sleep(1)
                            try:
                                result = self.api.check_win_v3(operation_id)
                            except Exception:
                                result = None
                            total_ops += 1
                            if result is not None and result > 0:
                                wins += 1
                                self.signals.log_signal.emit(f"Martingale {operation_id} em {ativo}: WIN (lucro: ${result:.2f})")
                                self.martingale_status.pop(ativo, None)
                            else:
                                losses += 1
                                self.signals.log_signal.emit(f"Martingale {operation_id} em {ativo}: LOSS (valor: ${mg['valor']:.2f})")
                                self.martingale_status.pop(ativo, None)
                            taxa = (wins / total_ops) * 100 if total_ops > 0 else 0
                            self.signals.stats_signal.emit(total_ops, wins, losses, taxa)
                        else:
                            self.signals.log_signal.emit(f"Falha ao executar Martingale em {ativo}: {operation_id}")
                            self.martingale_status.pop(ativo, None)
                    continue  # Não faz entrada normal se MG pendente

                now = datetime.datetime.now()
                current_cycle = (now.hour, now.minute // 5)
                if self.last_signal_time.get(ativo) == current_cycle:
                    continue  # já operou neste quadrante MHI para este ativo

                try:
                    candles = self.api.get_candles(ativo, 60, 61, int(time.time()))
                except Exception as e:
                    self.signals.log_signal.emit(f"Erro ao obter candles ({ativo}): {e}")
                    continue
                if not candles or len(candles) < 61:
                    self.signals.log_signal.emit(f"{ativo}: Não foi possível obter candles suficientes para operação/catalogação.")
                    continue

                candles = sorted(candles, key=lambda x: x['from'], reverse=True)
                self.catalogar_mhi_classico(candles, ativo)

                # ADX e operação, segue o padrão anterior
                candles = sorted(candles, key=lambda x: x['from'])
                adx, _, _ = calculate_adx(candles[-(adx_period+1):], period=adx_period)
                self.signals.log_signal.emit(f"{ativo}: ADX={adx:.2f} (limite: {adx_limiar})")
                if adx is None:
                    self.signals.log_signal.emit(f"{ativo}: Não foi possível calcular ADX (insuficiente candles). Pulando operação.")
                    continue
                if adx > adx_limiar:
                    self.signals.log_signal.emit(f"{ativo}: Mercado com tendência (ADX>{adx_limiar}), aguardando lateralização para operar.")
                    time.sleep(1)
                    continue
                sinal = self.get_mhi_signal(candles)
                if not sinal:
                    continue

                self.signals.log_signal.emit(f"MHI+ADX: Sinal {sinal.upper()} em {ativo} (ADX={adx:.2f}), tentando executar operação")
                valor = float(parent.valor_entry.text())
                exp = int(parent.expiry_combobox.currentText())
                saldo = self.api.get_balance()
                if saldo < valor:
                    self.signals.log_signal.emit(f"Erro: Saldo insuficiente para operação em {ativo}.")
                    continue
                check, operation_id = self.api.buy(valor, ativo, sinal, exp)
                if check:
                    self.operacoes_realizadas[ativo] += 1
                    self.last_signal_time[ativo] = current_cycle
                    self.signals.log_signal.emit(f"Operação iniciada: {sinal.upper()} em {ativo} com valor ${valor:.2f} e expiração {exp} minutos. ID: {operation_id}")
                    # Espera resultado
                    for _ in range(60):
                        if self.stop_flag:
                            break
                        try:
                            result = self.api.check_win_v3(operation_id)
                            if result is not None and result != operation_id:
                                break
                        except Exception:
                            pass
                        time.sleep(1)
                    try:
                        result = self.api.check_win_v3(operation_id)
                    except Exception:
                        result = None
                    total_ops += 1
                    if result is not None and result > 0:
                        wins += 1
                        self.signals.log_signal.emit(f"Operação {operation_id} em {ativo} finalizada: WIN (lucro: ${result:.2f})")
                    else:
                        losses += 1
                        self.signals.log_signal.emit(f"Operação {operation_id} em {ativo} finalizada: LOSS (valor: ${valor:.2f})")
                        # Prepara Martingale
                        self.martingale_status[ativo] = {
                            'nivel': 1,
                            'direcao': sinal,
                            'valor': valor*2,
                            'exp': exp
                        }
                    taxa = (wins / total_ops) * 100 if total_ops > 0 else 0
                    self.signals.stats_signal.emit(total_ops, wins, losses, taxa)
                    if self.operacoes_realizadas[ativo] >= max_entradas:
                        self.signals.log_signal.emit("Número máximo de entradas atingido. Parando o robô.")
                        parent.stop_robo()
                        return
                else:
                    self.signals.log_signal.emit(f"Falha ao executar operação em {ativo}: {operation_id}")
                time.sleep(2)
            time.sleep(1)
        self.signals.log_signal.emit("Robô parado (thread finalizada).")

    def get_mhi_signal(self, candles):
        if len(candles) < 5:
            return None
        group = candles[-5:]
        last_three = group[2:5]
        directions = []
        for c in last_three:
            if c['close'] > c['open']:
                directions.append('alta')
            elif c['close'] < c['open']:
                directions.append('baixa')
            else:
                directions.append('doji')
        if 'doji' in directions:
            return None
        count_alta = directions.count('alta')
        count_baixa = directions.count('baixa')
        minoria = 'alta' if count_alta < count_baixa else 'baixa'
        return 'call' if minoria == 'alta' else 'put'

class ModernMHI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Robô MHI PyQt5 - Moderno")
        self.setGeometry(100, 100, 1100, 820)
        self.thread_robo = None
        self.api = None
        self.operacoes_realizadas = {}
        self.init_ui()
        self.apply_theme("light")

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout()
        central.setLayout(main_layout)
        conn_theme = QHBoxLayout()
        main_layout.addLayout(conn_theme)
        conn_form = QFormLayout()
        conn_theme.addLayout(conn_form)
        self.email_entry = QLineEdit()
        conn_form.addRow("Email:", self.email_entry)
        self.senha_entry = QLineEdit()
        self.senha_entry.setEchoMode(QLineEdit.Password)
        conn_form.addRow("Senha:", self.senha_entry)
        self.conta_combobox = QComboBox()
        self.conta_combobox.addItems(["PRACTICE", "REAL"])
        conn_form.addRow("Conta:", self.conta_combobox)
        self.connect_button = QPushButton("Conectar")
        self.disconnect_button = QPushButton("Desconectar")
        self.disconnect_button.setEnabled(False)
        btns = QHBoxLayout()
        btns.addWidget(self.connect_button)
        btns.addWidget(self.disconnect_button)
        conn_form.addRow("", btns)
        self.theme_button = QPushButton("🌙 Modo Escuro")
        self.theme_button.setCheckable(True)
        self.theme_button.clicked.connect(self.toggle_theme)
        conn_theme.addWidget(self.theme_button)
        conn_theme.addStretch()
        config_frame = QFrame()
        config_frame.setFrameShape(QFrame.StyledPanel)
        config_layout = QHBoxLayout()
        config_frame.setLayout(config_layout)
        ativos_box = QVBoxLayout()
        ativos_label = QLabel("Ativos Disponíveis:")
        self.ativos_list = QListWidget()
        ativos_box.addWidget(ativos_label)
        ativos_box.addWidget(self.ativos_list)
        config_layout.addLayout(ativos_box)
        config_form = QFormLayout()
        self.valor_entry = QLineEdit("25")
        config_form.addRow("Valor ($):", self.valor_entry)
        self.expiry_combobox = QComboBox()
        self.expiry_combobox.addItems(["1"])
        config_form.addRow("Expiração (min):", self.expiry_combobox)
        self.entradas_spinbox = QSpinBox()
        self.entradas_spinbox.setRange(1, 100)
        self.entradas_spinbox.setValue(3)
        config_form.addRow("Entradas:", self.entradas_spinbox)
        self.soros_spinbox = QSpinBox()
        self.soros_spinbox.setRange(0, 100)
        self.soros_spinbox.setValue(50)
        config_form.addRow("Soros (%):", self.soros_spinbox)
        self.otc_check = QCheckBox("Incluir OTC")
        self.otc_check.setChecked(True)
        config_form.addRow(self.otc_check)
        self.martingale_check = QCheckBox("Ativar Martingale")
        self.martingale_check.setChecked(True)
        config_form.addRow(self.martingale_check)
        self.martingale_levels = QComboBox()
        self.martingale_levels.addItems(["1"])
        config_form.addRow("Níveis de Martingale:", self.martingale_levels)
        self.lucro_stop_loss_check = QCheckBox("Operar por Lucro/Stop Loss")
        config_form.addRow(self.lucro_stop_loss_check)
        self.lucro_entry = QLineEdit()
        config_form.addRow("Limite de Lucro ($):", self.lucro_entry)
        self.perda_entry = QLineEdit()
        config_form.addRow("Limite de Perda ($):", self.perda_entry)
        self.saldo_label = QLabel("0")
        config_form.addRow("Saldo Disponível:", self.saldo_label)
        self.update_saldo_button = QPushButton("Atualizar Saldo")
        config_form.addRow(self.update_saldo_button)
        config_layout.addLayout(config_form)
        main_layout.addWidget(config_frame)
        control_layout = QHBoxLayout()
        self.start_button = QPushButton("Iniciar Robô")
        self.stop_button = QPushButton("Parar Robô")
        self.stop_button.setEnabled(False)
        self.status_label = QLabel("Desconectado")
        self.status_label.setStyleSheet("color: red;")
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.status_label)
        control_layout.addStretch()
        main_layout.addLayout(control_layout)
        stats_layout = QHBoxLayout()
        self.ops_label = QLabel("0")
        self.acertos_label = QLabel("0")
        self.erros_label = QLabel("0")
        self.taxa_label = QLabel("0%")
        stats_layout.addWidget(QLabel("Operações:")); stats_layout.addWidget(self.ops_label)
        stats_layout.addWidget(QLabel("Acertos:")); stats_layout.addWidget(self.acertos_label)
        stats_layout.addWidget(QLabel("Erros:")); stats_layout.addWidget(self.erros_label)
        stats_layout.addWidget(QLabel("Taxa:")); stats_layout.addWidget(self.taxa_label)
        stats_layout.addStretch()
        main_layout.addLayout(stats_layout)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(500)
        font = QFont("Consolas", 10)
        self.log_text.setFont(font)
        main_layout.addWidget(self.log_text, 1)
        self.connect_button.clicked.connect(self.conectar)
        self.disconnect_button.clicked.connect(self.desconectar)
        self.update_saldo_button.clicked.connect(self.atualizar_saldo)
        self.start_button.clicked.connect(self.start_robo)
        self.stop_button.clicked.connect(self.stop_robo)

    def toggle_theme(self):
        if self.theme_button.isChecked():
            self.apply_theme("dark")
            self.theme_button.setText("☀️ Modo Claro")
        else:
            self.apply_theme("light")
            self.theme_button.setText("🌙 Modo Escuro")

    def apply_theme(self, mode):
        palette = QPalette()
        if mode == "dark":
            palette.setColor(QPalette.Window, QColor(30, 30, 30))
            palette.setColor(QPalette.WindowText, Qt.white)
            palette.setColor(QPalette.Base, QColor(25, 25, 25))
            palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
            palette.setColor(QPalette.ToolTipBase, Qt.white)
            palette.setColor(QPalette.ToolTipText, Qt.white)
            palette.setColor(QPalette.Text, Qt.white)
            palette.setColor(QPalette.Button, QColor(40, 40, 40))
            palette.setColor(QPalette.ButtonText, Qt.white)
            palette.setColor(QPalette.BrightText, Qt.red)
            palette.setColor(QPalette.Link, QColor(42, 130, 218))
            palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.HighlightedText, Qt.black)
        else:
            palette = QApplication.style().standardPalette()
        QApplication.instance().setPalette(palette)

    def conectar(self):
        email = self.email_entry.text().strip()
        senha = self.senha_entry.text().strip()
        if not email or not senha:
            QMessageBox.critical(self, "Erro", "Email e senha obrigatórios.")
            return
        self.log(f"Conectando como {email}...")
        try:
            self.api = IQ_Option(email, senha)
            check, reason = self.api.connect()
            if check:
                conta_tipo = self.conta_combobox.currentText()
                self.api.change_balance(conta_tipo)
                self.status_label.setText("Conectado")
                self.status_label.setStyleSheet("color: green;")
                self.connect_button.setEnabled(False)
                self.disconnect_button.setEnabled(True)
                self.start_button.setEnabled(True)
                self.log(f"Conectado com sucesso! Conta: {conta_tipo}")
                self.atualizar_ativos()
                self.atualizar_saldo()
            else:
                self.log(f"Falha na conexão: {reason}")
                QMessageBox.critical(self, "Erro", f"Falha na conexão: {reason}")
        except Exception as e:
            self.log(f"Erro na conexão: {str(e)}")
            QMessageBox.critical(self, "Erro", f"Falha na conexão: {str(e)}")

    def desconectar(self):
        if self.api:
            try:
                self.api.close()
            except Exception:
                pass
        self.api = None
        self.status_label.setText("Desconectado")
        self.status_label.setStyleSheet("color: red;")
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.log("Desconectado da corretora.")

    def atualizar_ativos(self):
        try:
            if not self.api:
                self.log("Erro: API não inicializada.")
                return
            ativos_all = self.api.get_all_ACTIVES_OPCODE()
            if self.otc_check.isChecked():
                ativos = [a for a in ativos_all if True]
            else:
                ativos = [a for a in ativos_all if not a.endswith('-OTC')]
            self.ativos_list.clear()
            for ativo in sorted(ativos):
                self.ativos_list.addItem(ativo)
        except Exception as e:
            self.log(f"Erro ao atualizar ativos: {e}")

    def atualizar_saldo(self):
        try:
            if self.api:
                saldo = self.api.get_balance()
                self.saldo_label.setText(f"{saldo:.2f}")
        except Exception as e:
            self.log(f"Erro ao atualizar saldo: {e}")

    def get_selected_ativos(self):
        return [
            self.ativos_list.item(i).text() for i in range(self.ativos_list.count())
            if self.ativos_list.item(i).isSelected()
        ]

    def start_robo(self):
        ativos = self.get_selected_ativos()
        if not ativos:
            QMessageBox.warning(self, "Seleção", "Selecione pelo menos um ativo.")
            return
        if not self.api:
            QMessageBox.critical(self, "Erro", "Conecte-se à corretora antes de iniciar o robô.")
            return
        self.log("Robô iniciado.")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Operando")
        self.status_label.setStyleSheet("color: green;")
        self.reset_stats()
        self.operacoes_realizadas = {a: 0 for a in ativos}
        self.signals = WorkerSignals()
        self.signals.log_signal.connect(self.log)
        self.signals.stats_signal.connect(self.update_stats)
        self.thread_robo = RoboThread(self, self.api, self.signals)
        self.thread_robo.start()

    def stop_robo(self):
        if hasattr(self, "thread_robo") and self.thread_robo and self.thread_robo.is_alive():
            self.thread_robo.stop_flag = True
            self.thread_robo.join()
            self.log("Robô parado.")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Parado")
        self.status_label.setStyleSheet("color: red;")

    def update_stats(self, ops, wins, losses, taxa):
        self.ops_label.setText(str(ops))
        self.acertos_label.setText(str(wins))
        self.erros_label.setText(str(losses))
        self.taxa_label.setText(f"{taxa:.1f}%")

    def reset_stats(self):
        self.ops_label.setText("0")
        self.acertos_label.setText("0")
        self.erros_label.setText("0")
        self.taxa_label.setText("0%")

    def log(self, msg):
        self.log_text.appendPlainText(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernMHI()
    window.show()
    sys.exit(app.exec_())