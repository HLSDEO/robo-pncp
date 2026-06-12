"""Coletores Dados Abertos Comprasgov (dadosabertos.compras.gov.br).

Paths confirmados via /v3/api-docs (swagger). Envelope de resposta:
    {resultado:[...], totalRegistros, totalPaginas, paginasRestantes}

Hierarquias (coletadas SOB DEMANDA - so para os itens vistos nos editais/atas):
  Material: Grupo > Classe > PDM > Item
  Servico : Secao > Divisao > Grupo > Classe > SubClasse > Item

ARP (modulo-arp): chave natural (numero_ata, unidade_gerenciadora).
  1 lista de ARPs (filtro por unidade gerenciadora + janela de vigencia <= 365d)
  2 itens da ARP
  3 unidades do item
  4 empenhos/saldo do item
  5 adesoes do item
"""
import logging
from datetime import date, timedelta

import httpx

from ..config import (
    DADOSABERTOS_BASE,
    DA_PAGE_SIZE,
    ARP_ANO_INICIAL,
    UNIDADES_PF,
)
from ..http_client import get_json
from ..db import upsert, cursor
from ..parallel import map_workers, sum_int, sum_tuple

log = logging.getLogger(__name__)

# -------- endpoints --------
MAT = f"{DADOSABERTOS_BASE}/modulo-material"
MAT_ITEM = f"{MAT}/4_consultarItemMaterial"

SVC = f"{DADOSABERTOS_BASE}/modulo-servico"
SVC_ITEM = f"{SVC}/6_consultarItemServico"

ARP = f"{DADOSABERTOS_BASE}/modulo-arp"
ARP_LIST = f"{ARP}/1_consultarARP"
ARP_ITENS = f"{ARP}/2_consultarARPItem"
ARP_EMPENHOS = f"{ARP}/4_consultarEmpenhosSaldoItem"


# =====================================================================
# Helpers
# =====================================================================

def _paginar_com_url(url: str, extra: dict | None = None):
    """Pagina o envelope {resultado, totalPaginas, paginasRestantes} e devolve
    (item, url_da_pagina) - a URL completa (com todos os params, incl. pagina)
    que retornou aquele item, para gravar em fonte_url a consulta real."""
    pagina = 1
    while True:
        params = {"pagina": pagina, "tamanhoPagina": DA_PAGE_SIZE}
        if extra:
            params.update(extra)
        page_url = str(httpx.URL(url, params=params))
        try:
            data = get_json(url, params=params)
        except Exception as e:
            log.warning("falha %s (pag %d): %s", url, pagina, e)
            return
        if not data:
            return
        items = data if isinstance(data, list) else (data.get("resultado") or [])
        if not items:
            return
        for it in items:
            yield it, page_url
        if isinstance(data, dict):
            restantes = data.get("paginasRestantes")
            total_pag = data.get("totalPaginas")
            if restantes is not None and restantes <= 0:
                return
            if total_pag is not None and pagina >= total_pag:
                return
        if len(items) < DA_PAGE_SIZE:
            return
        pagina += 1


def _s(v):
    return str(v) if v is not None else None


def _d(v):
    """Normaliza data: pega os 10 primeiros chars ('2026-03-27T00:00:00' -> '2026-03-27')."""
    if not v:
        return None
    s = str(v)
    return s[:10] if len(s) >= 10 else None


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _janelas(ano_inicial: int) -> list[tuple[str, str]]:
    """Janelas de <=365 dias de 01/01/ano_inicial ate 31/12 do ano que vem."""
    start = date(ano_inicial, 1, 1)
    end_limit = date(date.today().year + 1, 12, 31)
    janelas = []
    cur = start
    while cur <= end_limit:
        w_end = min(cur + timedelta(days=364), end_limit)
        janelas.append((cur.isoformat(), w_end.isoformat()))
        cur = w_end + timedelta(days=1)
    return janelas


def _ncp_from_links(link_ata: str | None, link_compra: str | None) -> tuple[str | None, str | None]:
    """Deriva (numero_controle_pncp_ata, numero_controle_pncp_edital) a partir
    dos links do PNCP que a ARP retorna. Formato do controle PNCP:
        edital = {cnpj}-1-{seqCompra:06d}/{ano}
        ata    = {edital}-{seqAta:06d}
    Links:
        link_ata    = .../app/atas/{cnpj}/{ano}/{seqCompra}/{seqAta}
        link_compra = .../app/editais/{cnpj}/{ano}/{seqCompra}
    """
    ata = edital = None
    if link_ata:
        p = link_ata.rstrip("/").split("/")
        try:
            i = p.index("atas")
            cnpj, ano, seq_compra, seq_ata = p[i + 1], p[i + 2], p[i + 3], p[i + 4]
            edital = f"{cnpj}-1-{int(seq_compra):06d}/{ano}"
            ata = f"{edital}-{int(seq_ata):06d}"
        except (ValueError, IndexError):
            pass
    if edital is None and link_compra:
        p = link_compra.rstrip("/").split("/")
        try:
            i = p.index("editais")
            cnpj, ano, seq_compra = p[i + 1], p[i + 2], p[i + 3]
            edital = f"{cnpj}-1-{int(seq_compra):06d}/{ano}"
        except (ValueError, IndexError):
            pass
    return ata, edital


def _referencia_codigo_item(tipo_item: str | None, codigo_item: str | None) -> str | None:
    """Indica de qual nivel/tipo do catalogo o codigo_item e. Nos itens de ARP
    o codigo e sempre o ITEM do catalogo (CATMAT p/ material, CATSER p/ servico) -
    a API so resolve por codigoItem - entao retorna 'item_material' /
    'item_servico' conforme o tipo_item."""
    if not codigo_item or not tipo_item:
        return None
    t = tipo_item.strip().lower()
    if t.startswith("mat"):
        return "item_material"
    if t.startswith("ser"):
        return "item_servico"
    return None


# =====================================================================
# Hierarquia SOB DEMANDA - so dos itens coletados (editais + ARPs)
# =====================================================================

def coletar_hierarquia_itens() -> dict:
    """Resolve a hierarquia (material/servico) apenas dos codigos de catalogo
    que apareceram nos itens coletados (edital_itens + arp_itens)."""
    materiais, servicos = _codigos_coletados()
    log.info("hierarquia sob demanda: %d materiais, %d servicos", len(materiais), len(servicos))
    tm = map_workers(_lookup_material, sorted(materiais), desc="hier_mat", reducer=sum_int)
    ts = map_workers(_lookup_servico, sorted(servicos), desc="hier_svc", reducer=sum_int)
    contadores = {"hierarquia_material": tm, "hierarquia_servico": ts}
    log.info("hierarquia itens %s", contadores)
    return contadores


def _codigos_coletados() -> tuple[set[str], set[str]]:
    """Codigos de catalogo (CATMAT/CATSER) vistos nos itens coletados.
    Fontes: pncp_edital_itens.catalogo_codigo_item (+ material_ou_servico)
            dadosabertos_arp_itens.codigo_item (+ tipo_item)
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT cod, ms FROM (
                SELECT DISTINCT catalogo_codigo_item AS cod,
                       upper(left(coalesce(material_ou_servico,''),1)) AS ms
                  FROM pncp_edital_itens
                 WHERE catalogo_codigo_item IS NOT NULL
                UNION
                SELECT DISTINCT codigo_item AS cod,
                       CASE WHEN tipo_item ILIKE 'mat%' THEN 'M'
                            WHEN tipo_item ILIKE 'ser%' THEN 'S' END AS ms
                  FROM dadosabertos_arp_itens
                 WHERE codigo_item IS NOT NULL
            ) t
            WHERE cod IS NOT NULL AND cod <> ''
            """
        )
        rows = cur.fetchall()
    materiais = {c for c, ms in rows if ms == "M"}
    servicos = {c for c, ms in rows if ms == "S"}
    # codigos sem tipo definido: tenta nos dois (a API simplesmente nao acha em um)
    indefinidos = {c for c, ms in rows if ms not in ("M", "S")}
    materiais |= indefinidos
    servicos |= indefinidos
    return materiais, servicos


def _lookup_material(codigo: str) -> int:
    got = 0
    for i, page_url in _paginar_com_url(MAT_ITEM, {"codigoItem": codigo}):
        _upsert_material_chain(i, page_url)
        got = 1
    return got


def _upsert_material_chain(i: dict, fonte_url: str) -> None:
    g = i.get("codigoGrupo")
    if g is not None:
        upsert("dadosabertos_material_grupo", ["codigo_grupo"], {
            "codigo_grupo": _s(g),
            "nome_grupo": i.get("nomeGrupo"),
            "status_grupo": None,
            "data_atualizacao": None,
            "fonte": "dadosabertos_material_grupo",
            "fonte_url": fonte_url,
            "raw_json": {"codigoGrupo": g, "nomeGrupo": i.get("nomeGrupo")},
        })
    c = i.get("codigoClasse")
    if c is not None:
        upsert("dadosabertos_material_classe", ["codigo_classe"], {
            "codigo_classe": _s(c),
            "codigo_grupo": _s(g),
            "nome_grupo": i.get("nomeGrupo"),
            "nome_classe": i.get("nomeClasse"),
            "status_classe": None,
            "data_atualizacao": None,
            "fonte": "dadosabertos_material_classe",
            "fonte_url": fonte_url,
            "raw_json": {"codigoClasse": c, "nomeClasse": i.get("nomeClasse"),
                         "codigoGrupo": g, "nomeGrupo": i.get("nomeGrupo")},
        })
    p = i.get("codigoPdm")
    if p is not None:
        upsert("dadosabertos_material_pdm", ["codigo_pdm"], {
            "codigo_pdm": _s(p),
            "codigo_classe": _s(c),
            "nome_classe": i.get("nomeClasse"),
            "codigo_grupo": _s(g),
            "nome_grupo": i.get("nomeGrupo"),
            "nome_pdm": i.get("nomePdm"),
            "status_pdm": None,
            "data_atualizacao": None,
            "fonte": "dadosabertos_material_pdm",
            "fonte_url": fonte_url,
            "raw_json": {"codigoPdm": p, "nomePdm": i.get("nomePdm"),
                         "codigoClasse": c, "codigoGrupo": g},
        })
    cod = i.get("codigoItem")
    if cod is not None:
        upsert("dadosabertos_material_item", ["codigo_item"], {
            "codigo_item": _s(cod),
            "codigo_pdm": _s(p),
            "nome_pdm": i.get("nomePdm"),
            "codigo_classe": _s(c),
            "nome_classe": i.get("nomeClasse"),
            "codigo_grupo": _s(g),
            "nome_grupo": i.get("nomeGrupo"),
            "descricao_item": i.get("descricaoItem"),
            "status_item": i.get("statusItem"),
            "item_sustentavel": i.get("itemSustentavel"),
            "codigo_ncm": i.get("codigo_ncm"),
            "descricao_ncm": i.get("descricao_ncm"),
            "fonte": "dadosabertos_material_item",
            "fonte_url": fonte_url,
            "raw_json": i,
        })


def _lookup_servico(codigo: str) -> int:
    got = 0
    for i, page_url in _paginar_com_url(SVC_ITEM, {"codigoServico": codigo}):
        _upsert_servico_chain(i, page_url)
        got = 1
    return got


def _upsert_servico_chain(i: dict, fonte_url: str) -> None:
    secao = i.get("codigoSecao")
    if secao is not None:
        upsert("dadosabertos_servico_secao", ["codigo_secao"], {
            "codigo_secao": _s(secao),
            "nome_secao": i.get("nomeSecao"),
            "status_secao": None,
            "data_atualizacao": None,
            "fonte": "dadosabertos_servico_secao",
            "fonte_url": fonte_url,
            "raw_json": {"codigoSecao": secao, "nomeSecao": i.get("nomeSecao")},
        })
    div = i.get("codigoDivisao")
    if div is not None:
        upsert("dadosabertos_servico_divisao", ["codigo_divisao"], {
            "codigo_divisao": _s(div),
            "codigo_secao": _s(secao),
            "nome_secao": i.get("nomeSecao"),
            "nome_divisao": i.get("nomeDivisao"),
            "status_divisao": None,
            "data_atualizacao": None,
            "fonte": "dadosabertos_servico_divisao",
            "fonte_url": fonte_url,
            "raw_json": {"codigoDivisao": div, "nomeDivisao": i.get("nomeDivisao"),
                         "codigoSecao": secao},
        })
    g = i.get("codigoGrupo")
    if g is not None:
        upsert("dadosabertos_servico_grupo", ["codigo_grupo"], {
            "codigo_grupo": _s(g),
            "codigo_divisao": _s(div),
            "nome_divisao": i.get("nomeDivisao"),
            "nome_secao": i.get("nomeSecao"),
            "nome_grupo": i.get("nomeGrupo"),
            "status_grupo": None,
            "data_atualizacao": None,
            "fonte": "dadosabertos_servico_grupo",
            "fonte_url": fonte_url,
            "raw_json": {"codigoGrupo": g, "nomeGrupo": i.get("nomeGrupo"),
                         "codigoDivisao": div},
        })
    c = i.get("codigoClasse")
    if c is not None:
        upsert("dadosabertos_servico_classe", ["codigo_classe"], {
            "codigo_classe": _s(c),
            "codigo_grupo": _s(g),
            "nome_grupo": i.get("nomeGrupo"),
            "nome_classe": i.get("nomeClasse"),
            "status_classe": None,
            "data_atualizacao": None,
            "fonte": "dadosabertos_servico_classe",
            "fonte_url": fonte_url,
            "raw_json": {"codigoClasse": c, "nomeClasse": i.get("nomeClasse"),
                         "codigoGrupo": g},
        })
    sub = i.get("codigoSubclasse")
    if sub is not None:
        upsert("dadosabertos_servico_subclasse", ["codigo_subclasse"], {
            "codigo_subclasse": _s(sub),
            "codigo_classe": _s(c),
            "nome_classe": i.get("nomeClasse"),
            "nome_subclasse": i.get("nomeSubclasse"),
            "status_subclasse": None,
            "data_atualizacao": None,
            "fonte": "dadosabertos_servico_subclasse",
            "fonte_url": fonte_url,
            "raw_json": {"codigoSubclasse": sub, "nomeSubclasse": i.get("nomeSubclasse"),
                         "codigoClasse": c},
        })
    cod = i.get("codigoServico")
    if cod is not None:
        upsert("dadosabertos_servico_item", ["codigo_servico"], {
            "codigo_servico": _s(cod),
            "codigo_subclasse": _s(sub),
            "nome_subclasse": i.get("nomeSubclasse"),
            "codigo_classe": _s(c),
            "nome_classe": i.get("nomeClasse"),
            "codigo_grupo": _s(g),
            "nome_grupo": i.get("nomeGrupo"),
            "codigo_divisao": _s(div),
            "nome_divisao": i.get("nomeDivisao"),
            "codigo_secao": _s(secao),
            "nome_secao": i.get("nomeSecao"),
            "nome_servico": i.get("nomeServico"),
            "codigo_cpc": _s(i.get("codigoCpc")),
            "status_servico": i.get("statusServico"),
            "data_atualizacao": i.get("dataHoraAtualizacao"),
            "fonte": "dadosabertos_servico_item",
            "fonte_url": fonte_url,
            "raw_json": i,
        })


# =====================================================================
# ARP
# =====================================================================

def coletar_arp_e_dependentes() -> dict:
    unidades = sorted(set(UNIDADES_PF.values()))
    janelas = _janelas(ARP_ANO_INICIAL)
    tarefas = [(u, w) for u in unidades for w in janelas]

    tot_arp, tot_itens = map_workers(
        _coletar_arp_unidade_janela, tarefas, desc="arp_list", reducer=sum_tuple(2)
    )

    atas = _listar_atas()
    tot_emp = map_workers(_coletar_empenho_saldo, atas, desc="arp_emp", reducer=sum_int)

    contadores = {
        "arp": tot_arp,
        "arp_itens": tot_itens,
        "arp_empenho_saldo": tot_emp,
    }
    log.info("arp %s", contadores)
    return contadores


def _coletar_arp_unidade_janela(tarefa: tuple[str, tuple[str, str]]) -> tuple[int, int]:
    unidade, (dmin, dmax) = tarefa
    base_params = {
        "codigoUnidadeGerenciadora": unidade,
        "dataVigenciaInicialMin": dmin,
        "dataVigenciaInicialMax": dmax,
    }
    tot_arp = 0
    for a, page_url in _paginar_com_url(ARP_LIST, base_params):
        num = a.get("numeroAtaRegistroPreco")
        ug = _s(a.get("codigoUnidadeGerenciadora")) or unidade
        if not num:
            continue
        ncp_ata, ncp_edital = _ncp_from_links(a.get("linkAtaPNCP"), a.get("linkCompraPNCP"))
        upsert("dadosabertos_arp", ["numero_ata", "unidade_gerenciadora"], {
            "numero_ata": num,
            "unidade_gerenciadora": ug,
            "numero_controle_pncp_ata": ncp_ata,
            "numero_controle_pncp_edital": ncp_edital,
            "codigo_orgao": _s(a.get("codigoOrgao")),
            "nome_orgao": a.get("nomeOrgao"),
            "link_ata_pncp": a.get("linkAtaPNCP"),
            "link_compra_pncp": a.get("linkCompraPNCP"),
            "numero_compra": _s(a.get("numeroCompra")),
            "ano_compra": _s(a.get("anoCompra")),
            "data_assinatura": _d(a.get("dataAssinatura")),
            "data_vigencia_inicial": _d(a.get("dataVigenciaInicial")),
            "data_vigencia_final": _d(a.get("dataVigenciaFinal")),
            "status_ata": a.get("statusAta"),
            "objeto": a.get("objeto"),
            "fonte": "dadosabertos_arp",
            "fonte_url": page_url,
        })
        tot_arp += 1

    tot_itens = 0
    for it, page_url in _paginar_com_url(ARP_ITENS, base_params):
        num = it.get("numeroAtaRegistroPreco")
        ug = _s(it.get("codigoUnidadeGerenciadora")) or unidade
        numero_item = _s(it.get("numeroItem"))
        if not num or numero_item is None:
            continue
        cod_item = _s(it.get("codigoItem"))
        upsert(
            "dadosabertos_arp_itens",
            ["numero_ata", "unidade_gerenciadora", "numero_item", "ni_fornecedor"],
            {
                "numero_ata": num,
                "unidade_gerenciadora": ug,
                "numero_item": numero_item,
                "ni_fornecedor": _s(it.get("niFornecedor")) or "",
                "codigo_item": cod_item,
                "referencia_codigo_item": _referencia_codigo_item(it.get("tipoItem"), cod_item),
                "descricao_item": it.get("descricaoItem"),
                "tipo_item": it.get("tipoItem"),
                "codigo_pdm": _s(it.get("codigoPdm")),
                "nome_pdm": it.get("nomePdm"),
                "quantidade_homologada": _num(it.get("quantidadeHomologadaItem")),
                "valor_unitario": _num(it.get("valorUnitario")),
                "classificacao_fornecedor": _s(it.get("classificacaoFornecedor")),
                "nome_fornecedor": it.get("nomeRazaoSocialFornecedor"),
                "numero_compra": _s(it.get("numeroCompra")),
                "ano_compra": _s(it.get("anoCompra")),
                "codigo_modalidade": _s(it.get("codigoModalidadeCompra")),
                "numero_controle_pncp_ata": _s(it.get("numeroControlePncpAta")),
                "numero_controle_pncp_edital": _s(it.get("numeroControlePncpCompra")),
                "data_vigencia_inicial": _d(it.get("dataVigenciaInicial")),
                "data_vigencia_final": _d(it.get("dataVigenciaFinal")),
                "fonte": "dadosabertos_arp_itens",
                "fonte_url": page_url,
                "raw_json": it,
            },
        )
        tot_itens += 1
    return tot_arp, tot_itens


def _listar_atas() -> list[tuple[str, str]]:
    with cursor() as cur:
        cur.execute("SELECT numero_ata, unidade_gerenciadora FROM dadosabertos_arp")
        return cur.fetchall()


def _split_unidade_empenho(valor: str | None) -> tuple[str | None, str | None]:
    """'200334 - CGAD/DLOG/PF' -> (codigo, nome). Split so no PRIMEIRO ' - '
    porque o nome pode conter ' - ' (ex: '... PUBLICA - SENASP').
    Sem separador: codigo None, nome = valor inteiro."""
    if not valor:
        return None, None
    if " - " in valor:
        cod, nome = valor.split(" - ", 1)
        return (cod.strip() or None), (nome.strip() or None)
    return None, valor.strip() or None


def _coletar_empenho_saldo(ata: tuple[str, str]) -> int:
    numero_ata, ug = ata
    params = {"numeroAta": numero_ata, "unidadeGerenciadora": ug}
    n = 0
    for e, page_url in _paginar_com_url(ARP_EMPENHOS, params):
        numero_item = _s(e.get("numeroItem"))
        if numero_item is None:
            continue
        cod_unid, nome_unid = _split_unidade_empenho(_s(e.get("unidade")))
        upsert(
            "dadosabertos_arp_item_empenho_saldo",
            ["numero_ata", "unidade_gerenciadora", "numero_item", "unidade_empenho", "tipo"],
            {
                "numero_ata": numero_ata,
                "unidade_gerenciadora": ug,
                "numero_item": numero_item,
                "codigo_unidade_empenho": cod_unid,
                "unidade_empenho": nome_unid or "",
                "tipo": _s(e.get("tipo")) or "",
                "quantidade_registrada": _num(e.get("quantidadeRegistrada")),
                "quantidade_empenhada": _num(e.get("quantidadeEmpenhada")),
                "saldo_empenho": _num(e.get("saldoEmpenho")),
                "data_atualizacao": e.get("dataHoraAtualizacao"),
                "fonte": "dadosabertos_arp_empenho_saldo",
                "fonte_url": page_url,
            },
        )
        n += 1
    return n
