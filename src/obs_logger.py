"""Cliente do servico de observabilidade (POST /api/logs).

Fila em memoria + worker em thread: o codigo de coleta nunca espera pela
observabilidade. Se a API estiver fora, os eventos sao descartados depois de
algumas tentativas (nao paramos a coleta por causa de telemetria).
"""
import logging
import os
import queue
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

OBS_URL = os.getenv("OBS_URL", "http://backend:8000/api/logs")
OBS_ENVIRONMENT = os.getenv("OBS_ENVIRONMENT", "prod")
OBS_SOURCE = os.getenv("OBS_SOURCE", "robo-pncp")
OBS_TIMEOUT = float(os.getenv("OBS_TIMEOUT", "5"))
OBS_ENABLED = os.getenv("OBS_ENABLED", "true").lower() not in {"0", "false", "no"}
OBS_QUEUE_MAX = int(os.getenv("OBS_QUEUE_MAX", "5000"))

_q: queue.Queue[dict] = queue.Queue(maxsize=OBS_QUEUE_MAX)
_worker: threading.Thread | None = None
_client: httpx.Client | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=OBS_TIMEOUT)
    return _client


def _worker_loop():
    while True:
        payload = _q.get()
        if payload is None:
            return
        for tentativa in range(3):
            try:
                r = _http().post(OBS_URL, json=payload)
                if r.status_code < 400:
                    break
                log.debug("obs: %s -> %s", OBS_URL, r.status_code)
            except Exception as e:
                log.debug("obs falhou (tentativa %d): %s", tentativa + 1, e)
                time.sleep(1 + tentativa)
        _q.task_done()


def start():
    global _worker
    if not OBS_ENABLED:
        log.info("obs desabilitado (OBS_ENABLED=false)")
        return
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_worker_loop, daemon=True, name="obs-worker")
        _worker.start()
        log.info("obs worker iniciado -> %s", OBS_URL)


def stop(drain_timeout: float = 5.0):
    if not OBS_ENABLED or _worker is None:
        return
    try:
        _q.join_with_timeout = drain_timeout  # type: ignore[attr-defined]
        deadline = time.time() + drain_timeout
        while not _q.empty() and time.time() < deadline:
            time.sleep(0.1)
    except Exception:
        pass


def send(
    *,
    identifier: str,
    data: str,
    type_: str = "info",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    location: str | None = None,
    status_code: str | None = None,
    identifier_2: str | None = None,
    identifier_3: str | None = None,
):
    if not OBS_ENABLED:
        return
    end = end_at or _now()
    start_ = start_at or end
    payload = {
        "start": start_.isoformat(),
        "end": end.isoformat(),
        "source": OBS_SOURCE,
        "type": type_,
        "identifier": identifier,
        "data": data[:8000] if data else "",
        "location": location,
        "environment": OBS_ENVIRONMENT,
        "status_code": status_code,
        "identifier_2": identifier_2,
        "identifier_3": identifier_3,
    }
    try:
        _q.put_nowait(payload)
    except queue.Full:
        log.warning("obs: fila cheia, descartando evento %s/%s", identifier, identifier_2)


@contextmanager
def step(
    identifier: str,
    *,
    identifier_2: str | None = None,
    identifier_3: str | None = None,
    location: str | None = None,
    data_ok: str | None = None,
):
    """Context manager: mede duracao e emite success/error automaticamente."""
    started = _now()
    try:
        yield
    except Exception as e:
        send(
            identifier=identifier,
            identifier_2=identifier_2,
            identifier_3=identifier_3,
            location=location,
            data=f"{type(e).__name__}: {e}"[:8000],
            type_="error",
            start_at=started,
            end_at=_now(),
        )
        raise
    else:
        send(
            identifier=identifier,
            identifier_2=identifier_2,
            identifier_3=identifier_3,
            location=location,
            data=data_ok or "ok",
            type_="success",
            start_at=started,
            end_at=_now(),
        )
