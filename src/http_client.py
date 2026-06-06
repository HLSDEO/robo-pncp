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
    pass


def _api_tag(url: str) -> str:
    if "pncp.gov.br/api/search" in url:
        return "PNCP_SEARCH"
    if "pncp.gov.br/api/pncp/v1" in url:
        if "/itens/" in url and "/resultados" in url:
            return "PNCP_V1_RESULTADOS"
        if "/itens" in url:
            return "PNCP_V1_ITENS"
        if "/atas" in url:
            return "PNCP_V1_ATAS"
        if "/contratos/" in url:
            return "PNCP_V1_CONTRATOS"
        return "PNCP_V1"
    if "contratos.comprasnet.gov.br" in url:
        if "/contrato/ugorigem/" in url:
            return "COMPRASNET_CONTRATOS"
        return "COMPRASNET_SUBROTA"
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
def get_json(url: str, params: dict | None = None):
    """GET com retries. Retorna None em 404, raise em demais erros."""
    started = _now()
    tag = _api_tag(url)
    try:
        try:
            r = client().get(url, params=params)
        except httpx.TransportError as e:
            log.warning("transporte falhou %s: %s", url, e)
            obs_logger.send(
                identifier="API",
                identifier_2=tag,
                identifier_3=url,
                data=f"transport error: {e}",
                type_="error",
                start_at=started,
                location="http_client.get_json",
            )
            raise
        if r.status_code == 404:
            obs_logger.send(
                identifier="API",
                identifier_2=tag,
                identifier_3=url,
                data="404 not found",
                type_="warning",
                status_code="404",
                start_at=started,
                location="http_client.get_json",
            )
            return None
        if r.status_code in (429, 500, 502, 503, 504):
            log.warning("retryavel %s -> %s", url, r.status_code)
            obs_logger.send(
                identifier="API",
                identifier_2=tag,
                identifier_3=url,
                data=f"retryavel HTTP {r.status_code}",
                type_="warning",
                status_code=str(r.status_code),
                start_at=started,
                location="http_client.get_json",
            )
            raise HttpRetryable(f"{r.status_code} em {url}")
        r.raise_for_status()
        if not r.content:
            obs_logger.send(
                identifier="API",
                identifier_2=tag,
                identifier_3=url,
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
            identifier_3=url,
            data="ok",
            type_="success",
            status_code=str(r.status_code),
            start_at=started,
            location="http_client.get_json",
        )
        return r.json()
    except HttpRetryable:
        raise
    except Exception as e:
        obs_logger.send(
            identifier="API",
            identifier_2=tag,
            identifier_3=url,
            data=f"{type(e).__name__}: {e}",
            type_="error",
            start_at=started,
            location="http_client.get_json",
        )
        raise
