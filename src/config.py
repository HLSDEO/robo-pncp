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
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

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
