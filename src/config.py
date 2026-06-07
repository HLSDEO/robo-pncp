import os

DB = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "user": os.getenv("DB_USER", "pncp"),
    "password": os.getenv("DB_PASSWORD", "pncp"),
    "dbname": os.getenv("DB_NAME", "pncp"),
}

RUN_MODE = os.getenv("RUN_MODE", "loop").lower()
LOOP_INTERVAL_SECONDS = int(os.getenv("LOOP_INTERVAL_SECONDS", "21600"))
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "50"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "60"))
# Timeout so para abrir a conexao (handshake). Separado do read timeout
# para detectar rapido um servidor recusando conexao (Connection refused).
HTTP_CONNECT_TIMEOUT = float(os.getenv("HTTP_CONNECT_TIMEOUT", "10"))
# contratos.comprasnet.gov.br/api/contrato/ug/{ug} pode levar ~40s -
# usamos timeout maior so para esses endpoints.
COMPRASNET_TIMEOUT = float(os.getenv("COMPRASNET_TIMEOUT", "180"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
WORKERS = int(os.getenv("WORKERS", "4"))

# ----- Retry / resiliencia HTTP -----
# O PNCP rate-limita em rajadas (Connection refused / Server disconnected).
# Mais tentativas + backoff COM JITTER dessincroniza os workers e absorve
# janelas de bloqueio temporario.
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "6"))
HTTP_BACKOFF_MAX = float(os.getenv("HTTP_BACKOFF_MAX", "60"))
# Pool de conexoes. keepalive_expiry baixo evita reusar conexao que o
# servidor ja fechou (causa do "Server disconnected without sending a response").
HTTP_MAX_CONNECTIONS = int(os.getenv("HTTP_MAX_CONNECTIONS", "10"))
HTTP_MAX_KEEPALIVE = int(os.getenv("HTTP_MAX_KEEPALIVE", "5"))
HTTP_KEEPALIVE_EXPIRY = float(os.getenv("HTTP_KEEPALIVE_EXPIRY", "5"))

# ----- Dados Abertos Comprasgov -----
# tamanhoPagina aceito pela API: 10..500
DA_PAGE_SIZE = int(os.getenv("DA_PAGE_SIZE", "500"))
# Ano inicial para varrer ARPs (janelas de 365 dias ate hoje+1ano).
ARP_ANO_INICIAL = int(os.getenv("ARP_ANO_INICIAL", "2023"))

PNCP_BASE = "https://pncp.gov.br"
COMPRASNET_CONTRATOS_BASE = "https://contratos.comprasnet.gov.br/api"
DADOSABERTOS_BASE = "https://dadosabertos.compras.gov.br"

# Codigos das unidades gestoras da Policia Federal (sigla -> codigo)
UNIDADES_PF: dict[str, str] = {
    "SR/PF/AC": "200380",
    "SR/PF/AL": "200358",
    "SR/PF/AM": "200382",
    "SR/PF/AP": "200402",
    "SR/PF/BA": "200346",
    "SR/PF/CE": "200392",
    "SR/PF/DF": "200338",
    "SR/PF/ES": "200352",
    "SR/PF/GO": "200376",
    "SR/PF/MA": "200388",
    "SR/PF/MG": "200350",
    "SR/PF/MS": "200354",
    "SR/PF/MT": "200374",
    "SR/PF/PA": "200386",
    "SR/PF/PB": "200396",
    "SR/PF/PE": "200398",
    "SR/PF/PI": "200390",
    "SR/PF/PR": "200364",
    "SR/PF/RJ": "200356",
    "SR/PF/RN": "200394",
    "SR/PF/RO": "200378",
    "SR/PF/RR": "200384",
    "SR/PF/TO": "200404",
    "DTI/PF": "200342",
    "DLOG/PF": "200334",
    "DCI/PF": "200434",
    "DIP/PF": "200430",
    "DIREN-ANP/PF": "200340",
    "DITEC/PF": "200406",
    "DPF/CAS/SP": "200416",
    "DPF/FIG/PR": "200366",
    "DPF/LDA/PR": "200368",
    "DPF/STS/SP": "200362",
}
