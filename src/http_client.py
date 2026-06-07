import logging
from datetime import datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import HTTP_TIMEOUT
from . import obs_logger

log = logging.getLogger(__name__)

_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={
                "User-Agent": "robo-pncp/1.0 (+coleta de dados publicos)",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )
    return _client


class HttpRetryable(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


def _api_tag(url: str) -> str:
    if "pncp.gov.br/api/search" in url:
        return "PNCP_EDITAIS"
    if "pncp.gov.br/api/pncp/v1" in url:
        if "/itens/" in url and "/resultados" in url:
            return "PNCP_DETALHE_ITEM"
        if "/itens" in url:
            return "PNCP_ITENS"
        if "/atas" in url:
            return "PNCP_ATAS"
        return "PNCP_V1"
    if "contratos.comprasnet.gov.br" in url:
        if "/contrato/ug/" in url:
            return "COMPRASNET_CONTRATOS_UG"
        for sub in ("historico", "empenhos", "itens", "faturas"):
            if url.endswith(f"/{sub}"):
                return f"COMPRASNET_CONTRATO_{sub.upper()}"
        return "COMPRASNET_CONTRATO"
    if "dadosabertos.compras.gov.br" in url:
        if "modulo-material" in url:
            return "DADOSABERTOS_MATERIAL"
        if "modulo-servico" in url:
            return "DADOSABERTOS_SERVICO"
        if "modulo-arp" in url:
            return "DADOSABERTOS_ARP"
        return "DADOSABERTOS"
    return "HTTP"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((HttpRetryable, httpx.TransportError)),
    reraise=True,
)
def _get_json_attempt(
    url: str,
    params: dict | None,
    full_url: str,
    tag: str,
    started: datetime,
    timeout: float | None,
):
    """Uma tentativa. Loga em observabilidade apenas eventos terminais
    (404, resposta vazia, ok). Erros retryaveis (transport / HTTP 429/5xx)
    sao apenas relevantados pra o tenacity tentar de novo - o log de 'error'
    fica por conta do wrapper get_json, que so dispara depois de esgotadas
    as tentativas."""
    try:
        if timeout is not None:
            r = client().get(url, params=params, timeout=timeout)
        else:
            r = client().get(url, params=params)
    except httpx.TransportError as e:
        log.warning("transporte falhou %s: %s", full_url, e)
        raise
    if r.status_code == 404:
        obs_logger.send(
            identifier="API",
            identifier_2=tag,
            identifier_3=full_url,
            data="404 not found",
            type_="warning",
            status_code="404",
            start_at=started,
            location="http_client.get_json",
        )
        return None
    if r.status_code in (429, 500, 502, 503, 504):
        log.warning("retryavel %s -> %s", full_url, r.status_code)
        raise HttpRetryable(r.status_code)
    r.raise_for_status()
    if not r.content:
        obs_logger.send(
            identifier="API",
            identifier_2=tag,
            identifier_3=full_url,
            data="resposta vazia",
            type_="success",
            status_code=str(r.status_code),
            start_at=started,
            location="http_client.get_json",
        )
        return None
    obs_logger.send(
        identifier="API",
        identifier_2=tag,
        identifier_3=full_url,
        data="ok",
        type_="success",
        status_code=str(r.status_code),
        start_at=started,
        location="http_client.get_json",
    )
    return r.json()


def get_json(url: str, params: dict | None = None, timeout: float | None = None):
    """GET com retries. Retorna None em 404, raise em demais erros.

    `timeout` (segundos) sobrescreve o HTTP_TIMEOUT padrao para esta chamada -
    util para endpoints lentos (ex: contratos.comprasnet leva ~40s).

    Log de erro em observabilidade so e enviado apos tenacity esgotar as
    tentativas - tentativas intermediarias que falham e depois se recuperam
    nao poluem o canal de logs."""
    started = _now()
    full_url = str(httpx.URL(url, params=params)) if params else url
    tag = _api_tag(url)
    try:
        return _get_json_attempt(url, params, full_url, tag, started, timeout)
    except Exception as e:
        if isinstance(e, HttpRetryable):
            status_code = str(e.status_code)
            data = f"retryavel HTTP {e.status_code} apos retries esgotados"
        elif isinstance(e, httpx.TransportError):
            status_code = None
            data = f"transport error apos retries esgotados: {e}"
        elif isinstance(e, httpx.HTTPStatusError):
            status_code = str(e.response.status_code)
            data = f"{type(e).__name__}: HTTP {e.response.status_code}"
        else:
            status_code = None
            data = f"{type(e).__name__}: {e}"
        obs_logger.send(
            identifier="API",
            identifier_2=tag,
            identifier_3=full_url,
            data=data,
            type_="error",
            status_code=status_code,
            start_at=started,
            location="http_client.get_json",
        )
        raise
