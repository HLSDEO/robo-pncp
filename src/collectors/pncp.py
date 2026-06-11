"""Coletores do PNCP (pncp.gov.br).

Abordagem: 1 THREAD POR UG. Dentro de cada UG tudo roda SEQUENCIAL:
  1) editais (paginado em /api/search/)
  2) itens + resultados de cada edital
  3) atas de cada edital

A concorrencia fica limitada ao numero de UGs rodando em paralelo (WORKERS),
cada uma fazendo UMA requisicao por vez. Isso e bem mais gentil com o
rate-limit do PNCP do que espalhar threads por edital/item (que gerava
rajadas e 'Connection refused').
"""
import logging
from typing import Iterable

from ..config import PNCP_BASE, PAGE_SIZE, UNIDADES_PF
from ..http_client import get_json
from ..db import upsert
from ..parallel import map_workers
from .. import obs_logger

log = logging.getLogger(__name__)

SEARCH_URL = f"{PNCP_BASE}/api/search/"
PNCP_V1 = f"{PNCP_BASE}/api/pncp/v1"


# ---------------------------------------------------------------------
# Orquestracao: 1 thread por UG, sub-etapas sequenciais
# ---------------------------------------------------------------------

def coletar_pncp_por_ug() -> dict:
    """Itera as UGs da PF em paralelo (1 thread por UG). Dentro de cada UG
    roda editais -> itens/resultados -> atas SEQUENCIALMENTE.
    Retorna contadores agregados."""
    def _run(par: tuple[str, str]) -> dict:
        sigla, codigo = par
        log.info("PNCP UG [%s / %s]", sigla, codigo)
        with obs_logger.step("UNIDADE", identifier_2=sigla, identifier_3=codigo,
                             location="pncp.coletar_pncp_por_ug"):
            return _coletar_ug_completa(sigla, codigo)

    parciais = map_workers(_run, list(UNIDADES_PF.items()), desc="pncp_ug")
    total = {"editais": 0, "edital_itens": 0, "edital_item_resultados": 0, "atas": 0}
    for d in parciais:
        for k, v in d.items():
            total[k] = total.get(k, 0) + v
    log.info("PNCP por UG: %s", total)
    return total


def _coletar_ug_completa(sigla: str, codigo: str) -> dict:
    """Pipeline sequencial de uma UG."""
    cont = {"editais": 0, "edital_itens": 0, "edital_item_resultados": 0, "atas": 0}

    # 1) editais da UG (paginado)
    editais = _coletar_editais_unidade(sigla, codigo)
    cont["editais"] = len(editais)

    # drilldown precisa de cnpj + ano + seq
    drill = [(c, a, s) for (c, a, s, _ncp) in editais if c and a and s]

    # 2) itens + resultados de cada edital (sequencial)
    for cnpj, ano, seq in drill:
        n_itens, itens_com_resultado = _coletar_itens_um_edital(cnpj, ano, seq)
        cont["edital_itens"] += n_itens
        for numero_item in itens_com_resultado:
            cont["edital_item_resultados"] += _coletar_resultados_um_item(
                cnpj, ano, seq, numero_item
            )

    # 3) atas de cada edital (sequencial)
    for cnpj, ano, seq in drill:
        cont["atas"] += _coletar_atas_um_edital(cnpj, ano, seq)

    return cont


# ---------------------------------------------------------------------
# 1) EDITAIS
# ---------------------------------------------------------------------

def _coletar_editais_unidade(sigla: str, codigo: str) -> list[tuple[str, str, str, str]]:
    """Pagina /api/search/ da UG, grava cada edital e devolve a lista de
    chaves (orgao_cnpj, ano, numero_sequencial, numero_controle_pncp) para o
    drilldown sequencial subsequente."""
    editais: list[tuple[str, str, str, str]] = []
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
            editais.append(
                (it.get("orgao_cnpj"), it.get("ano"), it.get("numero_sequencial"), ncp)
            )
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
    return editais


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
# 2) ITENS + RESULTADOS
# ---------------------------------------------------------------------

def _coletar_itens_um_edital(orgao_cnpj: str, ano: str, seq: str) -> tuple[int, list[int]]:
    """Grava os itens do edital e devolve (qtd_itens, [numero_item com resultado]).
    A lista de itens-com-resultado vem em memoria - dispensa reconsulta no banco."""
    base = f"{PNCP_V1}/orgaos/{orgao_cnpj}/compras/{ano}/{seq}/itens"
    n = 0
    com_resultado: list[int] = []
    for it in _paginar_pncp_v1(base):
        numero_item = it.get("numeroItem")
        if numero_item is None:
            continue
        row = {
            "orgao_cnpj": orgao_cnpj,
            "ano": ano,
            "numero_sequencial": seq,
            "numero_item": numero_item,
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
        if it.get("temResultado"):
            com_resultado.append(numero_item)
    return n, com_resultado


def _coletar_resultados_um_item(orgao_cnpj: str, ano: str, seq: str, numero_item: int) -> int:
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
# 3) ATAS
# ---------------------------------------------------------------------

def _coletar_atas_um_edital(orgao_cnpj: str, ano: str, seq: str) -> int:
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
