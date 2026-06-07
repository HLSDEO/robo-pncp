"""Coletores do PNCP (pncp.gov.br)."""
import logging
from typing import Iterable

from ..config import PNCP_BASE, PAGE_SIZE, UNIDADES_PF
from ..http_client import get_json
from ..db import upsert, listar_editais_para_drilldown, listar_itens_com_resultado
from ..parallel import map_workers, sum_int
from .. import obs_logger

log = logging.getLogger(__name__)

SEARCH_URL = f"{PNCP_BASE}/api/search/"
PNCP_V1 = f"{PNCP_BASE}/api/pncp/v1"


def _sigla_da_unidade(codigo: str) -> str | None:
    for sigla, c in UNIDADES_PF.items():
        if c == codigo:
            return sigla
    return None


# ---------------------------------------------------------------------
# 1) EDITAIS  - paraleliza por unidade
# ---------------------------------------------------------------------

def coletar_editais() -> int:
    """Itera todas as unidades da PF em paralelo, busca editais no /api/search/ e grava."""
    def _run(par: tuple[str, str]) -> int:
        sigla, codigo = par
        log.info("editais [%s / %s]", sigla, codigo)
        with obs_logger.step("UNIDADE", identifier_2=sigla, identifier_3=codigo,
                             location="pncp.coletar_editais"):
            return _coletar_editais_unidade(sigla, codigo)

    total = map_workers(_run, list(UNIDADES_PF.items()), desc="editais", reducer=sum_int)
    log.info("editais coletados: %d", total)
    return total


def _coletar_editais_unidade(sigla: str, codigo: str) -> int:
    total_unidade = 0
    pagina = 1
    while True:
        params = {
            "q": codigo,
            "tipos_documento": "edital",
            "ordenacao": "-data",
            "pagina": pagina,
            "tam_pagina": PAGE_SIZE,
            "status": "todos",
            "esferas": "F",
        }
        data = get_json(SEARCH_URL, params=params)
        if not data:
            break
        items = data.get("items") or []
        if not items:
            break
        for it in items:
            ncp = it.get("numero_controle_pncp")
            if not ncp:
                continue
            if it.get("unidade_codigo") and it["unidade_codigo"] != codigo:
                continue
            row = {
                "numero_controle_pncp": ncp,
                "orgao_cnpj": it.get("orgao_cnpj"),
                "orgao_nome": it.get("orgao_nome"),
                "unidade_codigo": it.get("unidade_codigo"),
                "unidade_nome": it.get("unidade_nome"),
                "unidade_sigla_pf": sigla,
                "ano": it.get("ano"),
                "numero_sequencial": it.get("numero_sequencial"),
                "title": it.get("title"),
                "description": it.get("description"),
                "item_url": it.get("item_url"),
                "document_type": it.get("document_type"),
                "modalidade_id": it.get("modalidade_licitacao_id"),
                "modalidade_nome": it.get("modalidade_licitacao_nome"),
                "situacao_id": it.get("situacao_id"),
                "situacao_nome": it.get("situacao_nome"),
                "tipo_id": it.get("tipo_id"),
                "tipo_nome": it.get("tipo_nome"),
                "data_publicacao_pncp": it.get("data_publicacao_pncp"),
                "data_atualizacao_pncp": it.get("data_atualizacao_pncp"),
                "data_inicio_vigencia": it.get("data_inicio_vigencia"),
                "data_fim_vigencia": it.get("data_fim_vigencia"),
                "created_at_api": it.get("createdAt"),
                "fonte": "pncp_search",
                "fonte_url": str(SEARCH_URL) + f"?q={codigo}&pagina={pagina}",
                "raw_json": it,
            }
            upsert("pncp_editais", ["numero_controle_pncp"], row)
            total_unidade += 1
            obs_logger.send(
                identifier="EDITAL",
                identifier_2=sigla,
                identifier_3=ncp,
                data=it.get("title") or "",
                type_="success",
                location="pncp.coletar_editais",
            )
        if len(items) < PAGE_SIZE:
            break
        pagina += 1
    return total_unidade


# ---------------------------------------------------------------------
# Paginacao generica PNCP v1
# ---------------------------------------------------------------------

def _paginar_pncp_v1(url: str) -> Iterable[dict]:
    """Pagina endpoints v1 que retornam {data: [...], totalPaginas, ...} OU lista direta."""
    pagina = 1
    while True:
        params = {"pagina": pagina, "tamanhoPagina": PAGE_SIZE}
        data = get_json(url, params=params)
        if data is None:
            return
        if isinstance(data, list):
            for item in data:
                yield item
            if len(data) < PAGE_SIZE:
                return
            pagina += 1
            continue
        items = data.get("data") or []
        for item in items:
            yield item
        total_paginas = data.get("totalPaginas") or 1
        if pagina >= total_paginas or not items:
            return
        pagina += 1


# ---------------------------------------------------------------------
# 2) ITENS + RESULTADOS  - paraleliza por edital e por item
# ---------------------------------------------------------------------

def coletar_itens_e_resultados() -> tuple[int, int]:
    editais = listar_editais_para_drilldown()
    tot_itens = map_workers(
        _coletar_itens_um_edital, editais, desc="itens", reducer=sum_int
    )
    itens_com_res = listar_itens_com_resultado()
    tot_resultados = map_workers(
        _coletar_resultados_um_item, itens_com_res, desc="resultados", reducer=sum_int
    )
    log.info("itens=%d resultados=%d", tot_itens, tot_resultados)
    return tot_itens, tot_resultados


def _coletar_itens_um_edital(edital: tuple[str, str, str, str]) -> int:
    orgao_cnpj, ano, seq, _ncp = edital
    base = f"{PNCP_V1}/orgaos/{orgao_cnpj}/compras/{ano}/{seq}/itens"
    n = 0
    for it in _paginar_pncp_v1(base):
        if it.get("numeroItem") is None:
            continue
        row = {
            "orgao_cnpj": orgao_cnpj,
            "ano": ano,
            "numero_sequencial": seq,
            "numero_item": it.get("numeroItem"),
            "descricao": it.get("descricao"),
            "material_ou_servico": it.get("materialOuServico"),
            "material_ou_servico_nome": it.get("materialOuServicoNome"),
            "valor_unitario_estimado": it.get("valorUnitarioEstimado"),
            "quantidade": it.get("quantidade"),
            "unidade_medida": it.get("unidadeMedida"),
            "situacao_id": it.get("situacaoCompraItem"),
            "situacao_nome": it.get("situacaoCompraItemNome"),
            "tem_resultado": it.get("temResultado"),
            "data_inclusao": it.get("dataInclusao"),
            "data_atualizacao": it.get("dataAtualizacao"),
            "fonte": "pncp_v1_itens",
            "fonte_url": base,
            "raw_json": it,
        }
        upsert(
            "pncp_edital_itens",
            ["orgao_cnpj", "ano", "numero_sequencial", "numero_item"],
            row,
        )
        n += 1
    return n


def _coletar_resultados_um_item(item: tuple[str, str, str, int]) -> int:
    orgao_cnpj, ano, seq, numero_item = item
    url = f"{PNCP_V1}/orgaos/{orgao_cnpj}/compras/{ano}/{seq}/itens/{numero_item}/resultados"
    data = get_json(url)
    if not data:
        return 0
    results = data if isinstance(data, list) else data.get("data") or []
    n = 0
    for r in results:
        seq_res = r.get("sequencialResultado") or 1
        row = {
            "orgao_cnpj": orgao_cnpj,
            "ano": ano,
            "numero_sequencial": seq,
            "numero_item": numero_item,
            "sequencial_resultado": seq_res,
            "ni_fornecedor": r.get("niFornecedor"),
            "tipo_pessoa": r.get("tipoPessoa"),
            "nome_razao_social": r.get("nomeRazaoSocialFornecedor"),
            "codigo_pais": r.get("codigoPais"),
            "porte_fornecedor_id": r.get("porteFornecedorId"),
            "porte_fornecedor_nome": r.get("porteFornecedorNome"),
            "natureza_juridica_id": r.get("naturezaJuridicaId"),
            "natureza_juridica_nome": r.get("naturezaJuridicaNome"),
            "quantidade_homologada": r.get("quantidadeHomologada"),
            "valor_unitario_homologado": r.get("valorUnitarioHomologado"),
            "ordem_classificacao_srp": r.get("ordemClassificacaoSrp"),
            "data_resultado": r.get("dataResultado"),
            "situacao_id": r.get("situacaoCompraItemResultadoId"),
            "situacao_nome": r.get("situacaoCompraItemResultadoNome"),
            "numero_controle_pncp_compra": r.get("numeroControlePNCPCompra"),
            "data_inclusao": r.get("dataInclusao"),
            "data_atualizacao": r.get("dataAtualizacao"),
            "fonte": "pncp_v1_resultados",
            "fonte_url": url,
            "raw_json": r,
        }
        upsert(
            "pncp_edital_item_resultados",
            ["orgao_cnpj", "ano", "numero_sequencial", "numero_item", "sequencial_resultado"],
            row,
        )
        n += 1
    return n


# ---------------------------------------------------------------------
# 3) ATAS  - paraleliza por edital
# ---------------------------------------------------------------------

def coletar_atas() -> int:
    editais = listar_editais_para_drilldown()
    total = map_workers(_coletar_atas_um_edital, editais, desc="atas", reducer=sum_int)
    log.info("atas=%d", total)
    return total


def _coletar_atas_um_edital(edital: tuple[str, str, str, str]) -> int:
    orgao_cnpj, ano, seq, _ncp = edital
    url = f"{PNCP_V1}/orgaos/{orgao_cnpj}/compras/{ano}/{seq}/atas"
    n = 0
    for a in _paginar_pncp_v1(url):
        ncp = a.get("numeroControlePNCP")
        if not ncp:
            continue
        orgao = a.get("orgaoEntidade") or {}
        uni = a.get("unidadeOrgao") or {}
        row = {
            "numero_controle_pncp": ncp,
            "numero_controle_pncp_compra": a.get("numeroControlePNCPCompra"),
            "orgao_cnpj": orgao.get("cnpj") or orgao_cnpj,
            "orgao_razao_social": orgao.get("razaoSocial"),
            "unidade_codigo": uni.get("codigoUnidade"),
            "unidade_nome": uni.get("nomeUnidade"),
            "numero_ata": a.get("numeroAtaRegistroPreco"),
            "ano_ata": a.get("anoAta"),
            "sequencial_ata": a.get("sequencialAta"),
            "data_assinatura": a.get("dataAssinatura"),
            "data_vigencia_inicio": a.get("dataVigenciaInicio"),
            "data_vigencia_fim": a.get("dataVigenciaFim"),
            "data_cancelamento": a.get("dataCancelamento"),
            "cancelado": a.get("cancelado"),
            "data_publicacao_pncp": a.get("dataPublicacaoPncp"),
            "data_inclusao": a.get("dataInclusao"),
            "data_atualizacao": a.get("dataAtualizacao"),
            "data_atualizacao_global": a.get("dataAtualizacaoGlobal"),
            "modalidade_nome": a.get("modalidadeNome"),
            "objeto_compra": a.get("objetoCompra"),
            "informacao_complementar": a.get("informacaoComplementarCompra"),
            "fonte": "pncp_v1_atas",
            "fonte_url": url,
            "raw_json": a,
        }
        upsert("pncp_atas", ["numero_controle_pncp"], row)
        n += 1
        obs_logger.send(
            identifier="ATA",
            identifier_2=row["orgao_cnpj"],
            identifier_3=ncp,
            data=row.get("numero_ata") or "",
            type_="success",
            location="pncp.coletar_atas",
        )
    return n


