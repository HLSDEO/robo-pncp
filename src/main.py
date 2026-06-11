"""Orquestrador do robo de coleta.

Modos:
  RUN_MODE=once  -> roda uma vez e sai
  RUN_MODE=loop  -> roda em loop a cada LOOP_INTERVAL_SECONDS
"""
import logging
import sys
import time
import traceback
from datetime import datetime, timezone

from .config import LOG_LEVEL, RUN_MODE, LOOP_INTERVAL_SECONDS
from . import db, obs_logger
from .collectors import pncp, dados_abertos

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("robo-pncp")


def _etapa(nome: str, fn):
    """Roda uma etapa instrumentada com obs_logger.step."""
    with obs_logger.step("ETAPA", identifier_2=nome, location=f"main.{nome}"):
        return fn()


def rodar_uma_vez() -> dict:
    exec_id = db.iniciar_execucao()
    contadores: dict = {}
    started = datetime.now(timezone.utc)
    try:
        db.seed_unidades()

        log.info(">>> 1/2 PNCP por UG (editais -> itens/resultados -> atas, sequencial por UG)")
        cont_pncp = _etapa("pncp_ug", pncp.coletar_pncp_por_ug)
        contadores.update(cont_pncp)

        log.info(">>> 2/2 ARP + hierarquia material/servico (dados abertos)")
        arp_contadores = _etapa("arp", dados_abertos.coletar_arp_e_dependentes)
        contadores.update(arp_contadores)
        hier_contadores = _etapa("hierarquia_itens", dados_abertos.coletar_hierarquia_itens)
        contadores.update(hier_contadores)

        db.finalizar_execucao(exec_id, "ok", contadores)
        log.info("execucao OK: %s", contadores)
        obs_logger.send(
            identifier="EXECUCAO",
            identifier_2=str(exec_id),
            data=f"contadores={contadores}",
            type_="success",
            start_at=started,
            location="main.rodar_uma_vez",
        )
    except Exception as e:
        tb = traceback.format_exc()
        log.error("execucao falhou: %s\n%s", e, tb)
        db.finalizar_execucao(exec_id, "erro", contadores, erro=tb[-4000:])
        obs_logger.send(
            identifier="EXECUCAO",
            identifier_2=str(exec_id),
            data=f"{type(e).__name__}: {e}",
            type_="error",
            start_at=started,
            location="main.rodar_uma_vez",
        )
    return contadores


def main():
    log.info("robo-pncp inicializando (modo=%s)", RUN_MODE)
    obs_logger.start()
    try:
        if RUN_MODE == "once":
            rodar_uma_vez()
            return 0
        while True:
            rodar_uma_vez()
            log.info("dormindo %ds ate proxima rodada", LOOP_INTERVAL_SECONDS)
            time.sleep(LOOP_INTERVAL_SECONDS)
    finally:
        obs_logger.stop()


if __name__ == "__main__":
    sys.exit(main() or 0)
