import time

try:
    from api_iqoption_faria.stable_api import IQ_Option
    print("Usando api-iqoption-faria")
except ImportError:
    print("A biblioteca api-iqoption-faria não está instalada.")
    print("Instale com: pip install api-iqoption-faria")
    exit(1)

EMAIL = "juniorm4ciel@hotmail.com"
SENHA = "053218Lucas"

ATIVO = "EURUSD"
VALOR = 1
DIRECAO = "call"  # ou "put"
EXPIRACAO = 1     # minutos

def main():
    print("Conectando...")
    Iq = IQ_Option(EMAIL, SENHA)
    check, reason = Iq.connect()
    print("Conectado?", check)
    print("Motivo:", reason)
    if not check:
        print("Falha ao conectar. Corrija os dados e tente novamente.")
        return

    Iq.change_balance("PRACTICE")
    saldo = Iq.get_balance()
    print("Saldo DEMO:", saldo)

    print(f"Enviando operação de {VALOR} {ATIVO} {DIRECAO} {EXPIRACAO}min...")
    status, id_ordem = Iq.buy(VALOR, ATIVO, DIRECAO, EXPIRACAO)
    print("Ordem enviada:", status, id_ordem)

    print("Aguardando resultado da operação...")
    resultado = Iq.check_win_v3(id_ordem)
    print("Resultado:", resultado)

    Iq.close()
    print("Sessão encerrada.")

if __name__ == "__main__":
    main()