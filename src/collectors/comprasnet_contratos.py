"""Coletor de contratos do contratos.comprasnet.gov.br.

Estrategia:
  1) Para cada UG da PF (UNIDADES_PF), busca contratos em /api/contrato/ug/{ug}.
  2) Para cada contrato, tenta casar com pncp_editais por
     (unidade_compra, modalidade prefix, licitacao_numero='seq/ano') e grava
     o numero_controle_pncp em id_contrato_edital_pncp (NULL se nao achou).
  3) Coleta apenas 4 sub-rotas: historico, empenhos, itens, faturas.

O endpoint /api/contrato/ug/{ug} pode levar ~40s, por isso usamos
COMPRASNET_TIMEOUT (default 180s) ao chama-lo.
"""
import hashlib
import logging

from ..config import COMPRASNET_CONTRATOS_BASE, COMPRASNET_TIMEOUT, UNIDADES_PF
from ..http_client import get_json
from ..db import buscar_edital_pncp, upsert
from ..parallel import map_workers, sum_tuple
from .. import obs_logger

log = logging.getLogger(__name__)

SUBROTAS = ["historico", "empenhos", "itens", "faturas"]


def _br_to_decimal(v):
    """Converte '152.386,80' -> 152386.80. None se vazio."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def coletar_contratos_e_subrotas() -> tuple[int, int]:
    """Itera UGs da PF em paralelo. Retorna (total_contratos, total_subrotas)."""
    ugs = list(UNIDADES_PF.items())
    total, total_sub = map_workers(
        _coletar_uma_ug,
        ugs,
        desc="comprasnet",
        reducer=sum_tuple(2),
    )
    log.info("comprasnet contratos=%d subrotas=%d", total, total_sub)
    return total, total_sub


def _coletar_uma_ug(par: tuple[str, str]) -> tuple[int, int]:
    sigla, ug = par
    url = f"{COMPRASNET_CONTRATOS_BASE}/contrato/ug/{ug}"
    with obs_logger.step(
        "UG_COMPRASNET",
        identifier_2=sigla,
        identifier_3=ug,
        location="comprasnet_contratos.coletar",
    ):
        data = get_json(url, timeout=COMPRASNET_TIMEOUT)
    if not data:
        return 0, 0
    registros = data if isinstance(data, list) else [data]
    total = 0
    total_sub = 0
    for c in registros:
        cid = c.get("id")
        if not cid:
            continue
        contratante = c.get("contratante") or {}
        org_orig = contratante.get("orgao_origem") or {}
        ug_orig = org_orig.get("unidade_gestora_origem") or {}
        org = contratante.get("orgao") or {}
        ug_atu = org.get("unidade_gestora") or {}
        forn = c.get("fornecedor") or {}

        # match com edital PNCP (NULL se nao bateu os 3)
        id_edital = buscar_edital_pncp(
            unidade_compra=c.get("unidade_compra"),
            modalidade=c.get("modalidade"),
            licitacao_numero=c.get("licitacao_numero"),
        )

        row = {
            "id": cid,
            "id_contrato_edital_pncp": id_edital,
            "receita_despesa": c.get("receita_despesa"),
            "numero": c.get("numero"),
            "codigo_tipo": c.get("codigo_tipo"),
            "tipo": c.get("tipo"),
            "subtipo": c.get("subtipo"),
            "prorrogavel": c.get("prorrogavel"),
            "situacao": c.get("situacao"),
            "justificativa_inativo": c.get("justificativa_inativo"),
            "categoria": c.get("categoria"),
            "subcategoria": c.get("subcategoria"),
            "unidades_requisitantes": c.get("unidades_requisitantes"),
            "processo": c.get("processo"),
            "objeto": c.get("objeto"),
            "amparo_legal": c.get("amparo_legal"),
            "informacao_complementar": c.get("informacao_complementar"),
            "codigo_modalidade": c.get("codigo_modalidade"),
            "modalidade": c.get("modalidade"),
            "unidade_compra": c.get("unidade_compra"),
            "licitacao_numero": c.get("licitacao_numero"),
            "sistema_origem_licitacao": c.get("sistema_origem_licitacao"),
            "orgao_origem_codigo": org_orig.get("codigo"),
            "orgao_origem_nome": org_orig.get("nome"),
            "ug_origem_codigo": ug_orig.get("codigo"),
            "ug_origem_nome": ug_orig.get("nome"),
            "ug_origem_nome_resumido": ug_orig.get("nome_resumido"),
            "orgao_codigo": org.get("codigo"),
            "orgao_nome": org.get("nome"),
            "ug_codigo": ug_atu.get("codigo"),
            "ug_nome": ug_atu.get("nome"),
            "ug_nome_resumido": ug_atu.get("nome_resumido"),
            "fornecedor_tipo": forn.get("tipo"),
            "fornecedor_cnpj_cpf": forn.get("cnpj_cpf_idgener"),
            "fornecedor_nome": forn.get("nome"),
            "data_assinatura": c.get("data_assinatura"),
            "data_publicacao": c.get("data_publicacao"),
            "data_proposta_comercial": c.get("data_proposta_comercial"),
            "vigencia_inicio": c.get("vigencia_inicio"),
            "vigencia_fim": c.get("vigencia_fim"),
            "valor_inicial": _br_to_decimal(c.get("valor_inicial")),
            "valor_global": _br_to_decimal(c.get("valor_global")),
            "valor_parcela": _br_to_decimal(c.get("valor_parcela")),
            "valor_acumulado": _br_to_decimal(c.get("valor_acumulado")),
            "num_parcelas": c.get("num_parcelas"),
            "fonte": "comprasnet_contratos_ug",
            "fonte_url": url,
            "raw_json": c,
        }
        upsert("comprasnet_contratos", ["id"], row)
        total += 1

        # CONTRATO: identifier_2 = sigla (PF) p/ agregacao no painel,
        # identifier_3 = id do contrato
        obs_logger.send(
            identifier="CONTRATO",
            identifier_2=sigla,
            identifier_3=str(cid),
            data=(row.get("objeto") or "")[:200],
            type_="success",
            location="comprasnet_contratos.coletar",
        )

        # MATCH_EDITAL_PNCP: identifier_2 = 'com' / 'sem' p/ agregar taxa de match
        # identifier_3 = id_edital se achou, str(cid) caso contrario
        obs_logger.send(
            identifier="MATCH_EDITAL_PNCP",
            identifier_2="com" if id_edital else "sem",
            identifier_3=id_edital or str(cid),
            data=id_edital or "",
            type_="success",
            location="comprasnet_contratos.matching",
        )

        total_sub += _coletar_subrotas(cid, c.get("links") or {})
    return total, total_sub


def _id_item(item: dict, pos: int) -> str:
    for k in ("id", "numero", "sequencial", "codigo"):
        if item.get(k) is not None:
            return str(item[k])
    blob = str(sorted(item.items()))
    return f"pos{pos}_{hashlib.md5(blob.encode()).hexdigest()[:10]}"


def _coletar_subrotas(contrato_id: int, links: dict) -> int:
    total = 0
    for nome in SUBROTAS:
        url = links.get(nome)
        if not url:
            continue
        data = get_json(url)
        if data is None:
            continue
        if isinstance(data, dict) and "data" in data:
            registros = data["data"]
        elif isinstance(data, list):
            registros = data
        else:
            registros = [data]
        for i, item in enumerate(registros):
            item_id = _id_item(item, i)
            upsert(
                "comprasnet_contrato_subrota",
                ["contrato_id", "subrota", "item_id"],
                {
                    "contrato_id": contrato_id,
                    "subrota": nome,
                    "item_id": item_id,
                    "fonte": f"comprasnet_contrato_{nome}",
                    "fonte_url": url,
                    "raw_json": item,
                },
            )
            total += 1
    return total
