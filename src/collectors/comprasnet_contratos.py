"""Coletor de contratos do contratos.comprasnet.gov.br.

Estrategia:
  1) Para cada UG da PF (UNIDADES_PF), busca contratos em /api/contrato/ug/{ug}.
  2) Para cada contrato, tenta casar com pncp_editais por
     (unidade_compra, modalidade prefix, licitacao_numero='seq/ano') e grava
     o numero_controle_pncp em id_contrato_edital_pncp (NULL se nao achou).
  3) Para cada contrato coleta 4 sub-rotas, cada uma em sua propria tabela
     tipada:
       /historico -> comprasnet_contrato_historico
       /empenhos  -> comprasnet_contrato_empenhos
       /itens     -> comprasnet_contrato_itens
       /faturas   -> comprasnet_contrato_faturas

O endpoint /api/contrato/ug/{ug} pode levar ~40s, por isso usamos
COMPRASNET_TIMEOUT (default 180s) ao chama-lo.
"""
import logging

from ..config import COMPRASNET_CONTRATOS_BASE, COMPRASNET_TIMEOUT, UNIDADES_PF
from ..http_client import get_json
from ..db import buscar_edital_pncp, upsert
from ..parallel import map_workers, sum_tuple
from .. import obs_logger

log = logging.getLogger(__name__)


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


def _date(v):
    """Pega os 10 primeiros chars de uma data/timestamp: '2017-07-07T...' -> '2017-07-07'."""
    if not v:
        return None
    s = str(v)
    return s[:10] if len(s) >= 10 else None


def _datetime_from_obj(v):
    """data_inicio_item vem como {date:'2021-01-01 20:49:18.000000', timezone_type:3, timezone:'America/Sao_Paulo'}.
    Retorna o campo 'date' como string ISO; psycopg cuida do cast para TIMESTAMPTZ."""
    if not v:
        return None
    if isinstance(v, dict):
        return v.get("date")
    return str(v)


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
            "numero": c.get("numero"),
            "codigo_tipo": c.get("codigo_tipo"),
            "tipo": c.get("tipo"),
            "situacao": c.get("situacao"),
            "justificativa_inativo": c.get("justificativa_inativo"),
            "categoria": c.get("categoria"),
            "processo": c.get("processo"),
            "objeto": c.get("objeto"),
            "amparo_legal": c.get("amparo_legal"),
            "codigo_modalidade": c.get("codigo_modalidade"),
            "modalidade": c.get("modalidade"),
            "unidade_compra": c.get("unidade_compra"),
            "licitacao_numero": c.get("licitacao_numero"),
            "orgao_origem_codigo": org_orig.get("codigo"),
            "orgao_origem_nome": org_orig.get("nome"),
            "ug_origem_codigo": ug_orig.get("codigo"),
            "ug_origem_nome": ug_orig.get("nome"),
            "ug_origem_nome_resumido": ug_orig.get("nome_resumido"),
            "fornecedor_tipo": forn.get("tipo"),
            "fornecedor_cnpj_cpf": forn.get("cnpj_cpf_idgener"),
            "fornecedor_nome": forn.get("nome"),
            "data_assinatura": c.get("data_assinatura"),
            "data_publicacao": c.get("data_publicacao"),
            "vigencia_inicio": c.get("vigencia_inicio"),
            "vigencia_fim": c.get("vigencia_fim"),
            "valor_inicial": _br_to_decimal(c.get("valor_inicial")),
            "valor_global": _br_to_decimal(c.get("valor_global")),
            "valor_parcela": _br_to_decimal(c.get("valor_parcela")),
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


SUBROTA_HANDLERS = {
    "historico": ("comprasnet_contrato_historico", lambda cid, i, url: _row_historico(cid, i, url)),
    "empenhos":  ("comprasnet_contrato_empenhos",  lambda cid, i, url: _row_empenho(cid, i, url)),
    "itens":     ("comprasnet_contrato_itens",     lambda cid, i, url: _row_item(cid, i, url)),
    "faturas":   ("comprasnet_contrato_faturas",   lambda cid, i, url: _row_fatura(cid, i, url)),
}


def _coletar_subrotas(contrato_id: int, links: dict) -> int:
    """Para cada uma das 4 sub-rotas, busca a lista e faz upsert na tabela
    tipada correspondente. Pula sub-rota sem id na resposta (sem PK)."""
    total = 0
    for nome, (tabela, builder) in SUBROTA_HANDLERS.items():
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
        for item in registros:
            if not item.get("id"):
                # sem PK natural - ignora
                continue
            row = builder(contrato_id, item, url)
            upsert(tabela, ["id"], row)
            total += 1
    return total


def _row_historico(contrato_id: int, h: dict, url: str) -> dict:
    forn = h.get("fornecedor") or {}
    return {
        "id": h["id"],
        "contrato_id": contrato_id,
        "receita_despesa": h.get("receita_despesa"),
        "numero": h.get("numero"),
        "observacao": h.get("observacao"),
        "ug": h.get("ug"),
        "gestao": h.get("gestao"),
        "codigo_tipo": h.get("codigo_tipo"),
        "tipo": h.get("tipo"),
        "categoria": h.get("categoria"),
        "qualificacao_termo": h.get("qualificacao_termo"),
        "processo": h.get("processo"),
        "objeto": h.get("objeto"),
        "fundamento_legal_aditivo": h.get("fundamento_legal_aditivo"),
        "informacao_complementar": h.get("informacao_complementar"),
        "modalidade": h.get("modalidade"),
        "licitacao_numero": h.get("licitacao_numero"),
        "codigo_unidade_origem": h.get("codigo_unidade_origem"),
        "nome_unidade_origem": h.get("nome_unidade_origem"),
        "fornecedor_tipo": forn.get("tipo"),
        "fornecedor_cnpj_cpf": forn.get("cnpj_cpf_idgener"),
        "fornecedor_nome": forn.get("nome"),
        "data_assinatura": _date(h.get("data_assinatura")),
        "data_publicacao": _date(h.get("data_publicacao")),
        "data_proposta_comercial": _date(h.get("data_proposta_comercial")),
        "vigencia_inicio": _date(h.get("vigencia_inicio")),
        "vigencia_fim": _date(h.get("vigencia_fim")),
        "valor_inicial": _br_to_decimal(h.get("valor_inicial")),
        "valor_global": _br_to_decimal(h.get("valor_global")),
        "num_parcelas": h.get("num_parcelas"),
        "valor_parcela": _br_to_decimal(h.get("valor_parcela")),
        "novo_valor_global": _br_to_decimal(h.get("novo_valor_global")),
        "novo_num_parcelas": h.get("novo_num_parcelas"),
        "novo_valor_parcela": _br_to_decimal(h.get("novo_valor_parcela")),
        "data_inicio_novo_valor": _date(h.get("data_inicio_novo_valor")),
        "retroativo": h.get("retroativo"),
        "retroativo_mesref_de": h.get("retroativo_mesref_de"),
        "retroativo_anoref_de": h.get("retroativo_anoref_de"),
        "retroativo_mesref_ate": h.get("retroativo_mesref_ate"),
        "retroativo_anoref_ate": h.get("retroativo_anoref_ate"),
        "retroativo_vencimento": _date(h.get("retroativo_vencimento")),
        "retroativo_valor": _br_to_decimal(h.get("retroativo_valor")),
        "situacao_contrato": h.get("situacao_contrato"),
        "criado_em": h.get("criado_em"),
        "alterado_em": h.get("alterado_em"),
        "fonte": "comprasnet_contrato_historico",
        "fonte_url": url,
        "raw_json": h,
    }


def _row_empenho(contrato_id: int, e: dict, url: str) -> dict:
    cred = e.get("credor_obj") or {}
    return {
        "id": e["id"],
        "contrato_id": contrato_id,
        "unidade_gestora": e.get("unidade_gestora"),
        "gestao": e.get("gestao"),
        "numero": e.get("numero"),
        "data_emissao": _date(e.get("data_emissao")),
        "credor": e.get("credor"),
        "credor_tipo": cred.get("tipo"),
        "credor_cnpj_cpf": cred.get("cnpj_cpf_idgener"),
        "credor_nome": cred.get("nome"),
        "fonte_recurso": e.get("fonte_recurso"),
        "programa_trabalho": e.get("programa_trabalho"),
        "planointerno": e.get("planointerno"),
        "naturezadespesa": e.get("naturezadespesa"),
        "empenhado": _br_to_decimal(e.get("empenhado")),
        "aliquidar": _br_to_decimal(e.get("aliquidar")),
        "liquidado": _br_to_decimal(e.get("liquidado")),
        "pago": _br_to_decimal(e.get("pago")),
        "rpinscrito": _br_to_decimal(e.get("rpinscrito")),
        "rpaliquidar": _br_to_decimal(e.get("rpaliquidar")),
        "rpliquidado": _br_to_decimal(e.get("rpliquidado")),
        "rppago": _br_to_decimal(e.get("rppago")),
        "informacao_complementar": e.get("informacao_complementar"),
        "sistema_origem": e.get("sistema_origem"),
        "links": e.get("links"),
        "fonte": "comprasnet_contrato_empenhos",
        "fonte_url": url,
        "raw_json": e,
    }


def _row_item(contrato_id: int, it: dict, url: str) -> dict:
    return {
        "id": it["id"],
        "contrato_id": contrato_id,
        "tipo_id": it.get("tipo_id"),
        "catmatseritem_id": it.get("catmatseritem_id"),
        "descricao_complementar": it.get("descricao_complementar"),
        "quantidade": _br_to_decimal(it.get("quantidade")),
        "valorunitario": _br_to_decimal(it.get("valorunitario")),
        "valortotal": _br_to_decimal(it.get("valortotal")),
        "numero_item_compra": it.get("numero_item_compra"),
        "data_inicio_item": _datetime_from_obj(it.get("data_inicio_item")),
        "historico_item": it.get("historico_item"),
        "fonte": "comprasnet_contrato_itens",
        "fonte_url": url,
        "raw_json": it,
    }


def _row_fatura(contrato_id: int, f: dict, url: str) -> dict:
    return {
        "id": f["id"],
        "contrato_id": contrato_id,
        "tipolistafatura_id": f.get("tipolistafatura_id"),
        "tipo_instrumento_cobranca": f.get("tipo_instrumento_cobranca"),
        "justificativafatura_id": f.get("justificativafatura_id"),
        "sfadrao_id": f.get("sfadrao_id"),
        "numero": f.get("numero"),
        "emissao": _date(f.get("emissao")),
        "prazo": _date(f.get("prazo")),
        "vencimento": _date(f.get("vencimento")),
        "valor": _br_to_decimal(f.get("valor")),
        "juros": _br_to_decimal(f.get("juros")),
        "multa": _br_to_decimal(f.get("multa")),
        "glosa": _br_to_decimal(f.get("glosa")),
        "valorliquido": _br_to_decimal(f.get("valorliquido")),
        "processo": f.get("processo"),
        "protocolo": _date(f.get("protocolo")),
        "ateste": _date(f.get("ateste")),
        "repactuacao": f.get("repactuacao"),
        "infcomplementar": f.get("infcomplementar"),
        "mesref": f.get("mesref"),
        "anoref": f.get("anoref"),
        "situacao": f.get("situacao"),
        "chave_nfe": f.get("chave_nfe"),
        "dados_empenho": f.get("dados_empenho"),
        "dados_referencia": f.get("dados_referencia"),
        "dados_item_faturado": f.get("dados_item_faturado"),
        "fonte": "comprasnet_contrato_faturas",
        "fonte_url": url,
        "raw_json": f,
    }
