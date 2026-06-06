"""Coletores do contratos.comprasnet.gov.br.

Usa os contratos ja gravados em pncp.contratos para descobrir UG e numero,
busca em /api/contrato/ugorigem/{UG}/numeroano/{NUMEROANO}, grava a base e
percorre todas as sub-rotas do campo 'links' (historico, empenhos, cronograma,
garantias, itens, prepostos, responsaveis, despesas_acessorias, faturas,
ocorrencias, terceirizados, arquivos).
"""
import hashlib
import logging

from ..config import COMPRASNET_CONTRATOS_BASE
from ..http_client import get_json
from ..db import cursor, upsert
from ..parallel import map_workers, sum_tuple

log = logging.getLogger(__name__)

SUBROTAS = [
    "historico",
    "empenhos",
    "cronograma",
    "garantias",
    "itens",
    "prepostos",
    "responsaveis",
    "despesas_acessorias",
    "faturas",
    "ocorrencias",
    "terceirizados",
    "arquivos",
]


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


def _normalizar_numeroano(numero_contrato: str | None, ano: int | None) -> str | None:
    """Converte ('00002', 2026) -> '000022026' (9 chars contrato) ou '000000022026' (12 empenho)."""
    if not numero_contrato or not ano:
        return None
    n = "".join(ch for ch in str(numero_contrato) if ch.isdigit())
    if not n:
        return None
    # tenta 5 digitos + ano = 9 chars (contrato)
    return f"{int(n):05d}{int(ano):04d}"


def _normalizar_numeroano_12(numero_contrato: str, ano: int) -> str:
    n = "".join(ch for ch in str(numero_contrato) if ch.isdigit())
    return f"{int(n):08d}{int(ano):04d}"


def _pncp_contratos_para_buscar():
    with cursor() as cur:
        cur.execute(
            """
            SELECT numero_controle_pncp, unidade_codigo, numero_contrato_empenho, ano_contrato, tipo_contrato_id
              FROM pncp.contratos
             WHERE unidade_codigo IS NOT NULL
               AND numero_contrato_empenho IS NOT NULL
               AND ano_contrato IS NOT NULL
            """
        )
        return cur.fetchall()


def coletar_contratos_e_subrotas() -> tuple[int, int]:
    pncp_contratos = _pncp_contratos_para_buscar()
    total, total_sub = map_workers(
        _coletar_um_contrato_comprasnet,
        pncp_contratos,
        desc="comprasnet",
        reducer=sum_tuple(2),
    )
    log.info("comprasnet contratos=%d subrotas=%d", total, total_sub)
    return total, total_sub


def _coletar_um_contrato_comprasnet(pncp_row) -> tuple[int, int]:
    ncp, ug, numero, ano, tipo_id = pncp_row
    numeroano = _normalizar_numeroano(numero, ano)
    if not numeroano:
        return 0, 0
    url = f"{COMPRASNET_CONTRATOS_BASE}/contrato/ugorigem/{ug}/numeroano/{numeroano}"
    data = get_json(url)
    if not data and tipo_id and int(tipo_id) != 1:
        numeroano12 = _normalizar_numeroano_12(numero, ano)
        url = f"{COMPRASNET_CONTRATOS_BASE}/contrato/ugorigem/{ug}/numeroano/{numeroano12}"
        data = get_json(url)
    if not data:
        return 0, 0
    total = 0
    total_sub = 0
    registros = data if isinstance(data, list) else [data]
    for c in registros:
            cid = c.get("id")
            if not cid:
                continue
            contratante = c.get("contratante") or {}
            org_orig = contratante.get("orgao_origem") or {}
            ug_orig = (org_orig.get("unidade_gestora_origem") or {})
            org = contratante.get("orgao") or {}
            ug_atu = (org.get("unidade_gestora") or {})
            forn = c.get("fornecedor") or {}
            row = {
                "id": cid,
                "numero": c.get("numero"),
                "numero_norm": numeroano,
                "receita_despesa": c.get("receita_despesa"),
                "situacao": c.get("situacao"),
                "categoria": c.get("categoria"),
                "subcategoria": c.get("subcategoria"),
                "tipo": c.get("tipo"),
                "codigo_tipo": c.get("codigo_tipo"),
                "subtipo": c.get("subtipo"),
                "prorrogavel": c.get("prorrogavel"),
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
                "orgao_codigo": org.get("codigo"),
                "orgao_nome": org.get("nome"),
                "ug_codigo": ug_atu.get("codigo"),
                "ug_nome": ug_atu.get("nome"),
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
                "fonte": "comprasnet_contratos",
                "fonte_url": url,
                "raw_json": c,
            }
            upsert("comprasnet.contratos", ["id"], row)
            total += 1
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
                "comprasnet.contrato_subrota",
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
