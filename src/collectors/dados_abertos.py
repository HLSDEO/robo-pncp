"""Coletores Dados Abertos Comprasgov (dadosabertos.compras.gov.br).

Paths confirmados via /v3/api-docs (swagger). Envelope de resposta:
    {resultado:[...], totalRegistros, totalPaginas, paginasRestantes}

Hierarquias:
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

from ..config import (
    DADOSABERTOS_BASE,
    DA_PAGE_SIZE,
    DA_MATERIAL_ITENS,
    ARP_ANO_INICIAL,
    UNIDADES_PF,
)
from ..http_client import get_json
from ..db import upsert, cursor
from ..parallel import map_workers, sum_int, sum_tuple

log = logging.getLogger(__name__)

# -------- endpoints --------
MAT = f"{DADOSABERTOS_BASE}/modulo-material"
MAT_GRUPO = f"{MAT}/1_consultarGrupoMaterial"
MAT_CLASSE = f"{MAT}/2_consultarClasseMaterial"
MAT_PDM = f"{MAT}/3_consultarPdmMaterial"
MAT_ITEM = f"{MAT}/4_consultarItemMaterial"

SVC = f"{DADOSABERTOS_BASE}/modulo-servico"
SVC_SECAO = f"{SVC}/1_consultarSecaoServico"
SVC_DIVISAO = f"{SVC}/2_consultarDivisaoServico"
SVC_GRUPO = f"{SVC}/3_consultarGrupoServico"
SVC_CLASSE = f"{SVC}/4_consultarClasseServico"
SVC_SUBCLASSE = f"{SVC}/5_consultarSubClasseServico"
SVC_ITEM = f"{SVC}/6_consultarItemServico"

ARP = f"{DADOSABERTOS_BASE}/modulo-arp"
ARP_LIST = f"{ARP}/1_consultarARP"
ARP_ITENS = f"{ARP}/2_consultarARPItem"
ARP_UNIDADES = f"{ARP}/3_consultarUnidadesItem"
ARP_EMPENHOS = f"{ARP}/4_consultarEmpenhosSaldoItem"
ARP_ADESOES = f"{ARP}/5_consultarAdesoesItem"


# =====================================================================
# Helpers
# =====================================================================

def _paginar(url: str, extra: dict | None = None):
    """Pagina o envelope {resultado, totalPaginas, paginasRestantes}."""
    pagina = 1
    while True:
        params = {"pagina": pagina, "tamanhoPagina": DA_PAGE_SIZE}
        if extra:
            params.update(extra)
        try:
            data = get_json(url, params=params)
        except Exception as e:
            log.warning("falha %s (pag %d): %s", url, pagina, e)
            return
        if not data:
            return
        if isinstance(data, list):
            items = data
        else:
            items = data.get("resultado") or []
        if not items:
            return
        for it in items:
            yield it
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


# =====================================================================
# Hierarquia de Material
# =====================================================================

def _mat_grupo() -> int:
    n = 0
    for g in _paginar(MAT_GRUPO):
        cod = g.get("codigoGrupo")
        if cod is None:
            continue
        upsert("dadosabertos.material_grupo", ["codigo_grupo"], {
            "codigo_grupo": _s(cod),
            "nome_grupo": g.get("nomeGrupo"),
            "status_grupo": g.get("statusGrupo"),
            "data_atualizacao": g.get("dataHoraAtualizacao"),
            "fonte": "dadosabertos_material_grupo",
            "fonte_url": MAT_GRUPO,
            "raw_json": g,
        })
        n += 1
    return n


def _mat_classe() -> int:
    n = 0
    for c in _paginar(MAT_CLASSE):
        cod = c.get("codigoClasse")
        if cod is None:
            continue
        upsert("dadosabertos.material_classe", ["codigo_classe"], {
            "codigo_classe": _s(cod),
            "codigo_grupo": _s(c.get("codigoGrupo")),
            "nome_grupo": c.get("nomeGrupo"),
            "nome_classe": c.get("nomeClasse"),
            "status_classe": c.get("statusClasse", c.get("statusGrupo")),
            "data_atualizacao": c.get("dataHoraAtualizacao"),
            "fonte": "dadosabertos_material_classe",
            "fonte_url": MAT_CLASSE,
            "raw_json": c,
        })
        n += 1
    return n


def _mat_pdm() -> int:
    n = 0
    for p in _paginar(MAT_PDM):
        cod = p.get("codigoPdm")
        if cod is None:
            continue
        upsert("dadosabertos.material_pdm", ["codigo_pdm"], {
            "codigo_pdm": _s(cod),
            "codigo_classe": _s(p.get("codigoClasse")),
            "nome_classe": p.get("nomeClasse"),
            "codigo_grupo": _s(p.get("codigoGrupo")),
            "nome_grupo": p.get("nomeGrupo"),
            "nome_pdm": p.get("nomePdm"),
            "status_pdm": p.get("statusPdm"),
            "data_atualizacao": p.get("dataHoraAtualizacao"),
            "fonte": "dadosabertos_material_pdm",
            "fonte_url": MAT_PDM,
            "raw_json": p,
        })
        n += 1
    return n


def _mat_item() -> int:
    if not DA_MATERIAL_ITENS:
        log.info("material_item desabilitado (DA_MATERIAL_ITENS=false)")
        return 0
    n = 0
    for it in _paginar(MAT_ITEM):
        cod = it.get("codigoItem")
        if cod is None:
            continue
        upsert("dadosabertos.material_item", ["codigo_item"], {
            "codigo_item": _s(cod),
            "codigo_pdm": _s(it.get("codigoPdm")),
            "nome_pdm": it.get("nomePdm"),
            "codigo_classe": _s(it.get("codigoClasse")),
            "nome_classe": it.get("nomeClasse"),
            "codigo_grupo": _s(it.get("codigoGrupo")),
            "nome_grupo": it.get("nomeGrupo"),
            "descricao_item": it.get("descricaoItem"),
            "status_item": it.get("statusItem"),
            "item_sustentavel": it.get("itemSustentavel"),
            "codigo_ncm": it.get("codigo_ncm"),
            "descricao_ncm": it.get("descricao_ncm"),
            "fonte": "dadosabertos_material_item",
            "fonte_url": MAT_ITEM,
            "raw_json": it,
        })
        n += 1
        if n % 5000 == 0:
            log.info("material_item: %d coletados...", n)
    return n


def coletar_hierarquia_material() -> int:
    total = map_workers(
        lambda f: f(),
        [_mat_grupo, _mat_classe, _mat_pdm, _mat_item],
        desc="mat_hier",
        reducer=sum_int,
    )
    log.info("hierarquia material=%d", total)
    return total


# =====================================================================
# Hierarquia de Servico
# =====================================================================

def _svc_secao() -> int:
    n = 0
    for s in _paginar(SVC_SECAO):
        cod = s.get("codigoSecao")
        if cod is None:
            continue
        upsert("dadosabertos.servico_secao", ["codigo_secao"], {
            "codigo_secao": _s(cod),
            "nome_secao": s.get("nomeSecao"),
            "status_secao": s.get("statusSecao"),
            "data_atualizacao": s.get("dataHoraAtualizacao"),
            "fonte": "dadosabertos_servico_secao",
            "fonte_url": SVC_SECAO,
            "raw_json": s,
        })
        n += 1
    return n


def _svc_divisao() -> int:
    n = 0
    for d in _paginar(SVC_DIVISAO):
        cod = d.get("codigoDivisao")
        if cod is None:
            continue
        upsert("dadosabertos.servico_divisao", ["codigo_divisao"], {
            "codigo_divisao": _s(cod),
            "codigo_secao": _s(d.get("codigoSecao")),
            "nome_secao": d.get("nomeSecao"),
            "nome_divisao": d.get("nomeDivisao"),
            "status_divisao": d.get("statusDivisao"),
            "data_atualizacao": d.get("dataHoraAtualizacao"),
            "fonte": "dadosabertos_servico_divisao",
            "fonte_url": SVC_DIVISAO,
            "raw_json": d,
        })
        n += 1
    return n


def _svc_grupo() -> int:
    n = 0
    for g in _paginar(SVC_GRUPO):
        cod = g.get("codigoGrupo")
        if cod is None:
            continue
        upsert("dadosabertos.servico_grupo", ["codigo_grupo"], {
            "codigo_grupo": _s(cod),
            "codigo_divisao": _s(g.get("codigoDivisao")),
            "nome_divisao": g.get("nomeDivisao"),
            "nome_secao": g.get("nomeSecao"),
            "nome_grupo": g.get("nomeGrupo"),
            "status_grupo": g.get("statusGrupo"),
            "data_atualizacao": g.get("dataHoraAtualizacao"),
            "fonte": "dadosabertos_servico_grupo",
            "fonte_url": SVC_GRUPO,
            "raw_json": g,
        })
        n += 1
    return n


def _svc_classe() -> int:
    n = 0
    for c in _paginar(SVC_CLASSE):
        cod = c.get("codigoClasse")
        if cod is None:
            continue
        upsert("dadosabertos.servico_classe", ["codigo_classe"], {
            "codigo_classe": _s(cod),
            "codigo_grupo": _s(c.get("codigoGrupo")),
            "nome_grupo": c.get("nomeGrupo"),
            "nome_classe": c.get("nomeClasse"),
            "status_classe": c.get("statusClasse", c.get("statusGrupo")),
            "data_atualizacao": c.get("dataHoraAtualizacao"),
            "fonte": "dadosabertos_servico_classe",
            "fonte_url": SVC_CLASSE,
            "raw_json": c,
        })
        n += 1
    return n


def _svc_subclasse() -> int:
    n = 0
    for sc in _paginar(SVC_SUBCLASSE):
        cod = sc.get("codigoSubclasse")
        if cod is None:
            continue
        upsert("dadosabertos.servico_subclasse", ["codigo_subclasse"], {
            "codigo_subclasse": _s(cod),
            "codigo_classe": _s(sc.get("codigoClasse")),
            "nome_classe": sc.get("nomeClasse"),
            "nome_subclasse": sc.get("nomeSubclasse"),
            "status_subclasse": sc.get("statusSubclasse"),
            "data_atualizacao": sc.get("dataHoraAtualizacao"),
            "fonte": "dadosabertos_servico_subclasse",
            "fonte_url": SVC_SUBCLASSE,
            "raw_json": sc,
        })
        n += 1
    return n


def _svc_item() -> int:
    n = 0
    for it in _paginar(SVC_ITEM):
        cod = it.get("codigoServico")
        if cod is None:
            continue
        upsert("dadosabertos.servico_item", ["codigo_servico"], {
            "codigo_servico": _s(cod),
            "codigo_subclasse": _s(it.get("codigoSubclasse")),
            "nome_subclasse": it.get("nomeSubclasse"),
            "codigo_classe": _s(it.get("codigoClasse")),
            "nome_classe": it.get("nomeClasse"),
            "codigo_grupo": _s(it.get("codigoGrupo")),
            "nome_grupo": it.get("nomeGrupo"),
            "codigo_divisao": _s(it.get("codigoDivisao")),
            "nome_divisao": it.get("nomeDivisao"),
            "codigo_secao": _s(it.get("codigoSecao")),
            "nome_secao": it.get("nomeSecao"),
            "nome_servico": it.get("nomeServico"),
            "codigo_cpc": _s(it.get("codigoCpc")),
            "status_servico": it.get("statusServico"),
            "data_atualizacao": it.get("dataHoraAtualizacao"),
            "fonte": "dadosabertos_servico_item",
            "fonte_url": SVC_ITEM,
            "raw_json": it,
        })
        n += 1
    return n


def coletar_hierarquia_servico() -> int:
    total = map_workers(
        lambda f: f(),
        [_svc_secao, _svc_divisao, _svc_grupo, _svc_classe, _svc_subclasse, _svc_item],
        desc="svc_hier",
        reducer=sum_int,
    )
    log.info("hierarquia servico=%d", total)
    return total


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
    ata_itens = _listar_ata_itens()

    tot_emp = map_workers(_coletar_empenho_saldo, atas, desc="arp_emp", reducer=sum_int)
    tot_unid, tot_ades = map_workers(
        _coletar_unid_adesao, ata_itens, desc="arp_det", reducer=sum_tuple(2)
    )

    contadores = {
        "arp": tot_arp,
        "arp_itens": tot_itens,
        "arp_empenho_saldo": tot_emp,
        "arp_unidades": tot_unid,
        "arp_adesoes": tot_ades,
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
    for a in _paginar(ARP_LIST, base_params):
        num = a.get("numeroAtaRegistroPreco")
        ug = _s(a.get("codigoUnidadeGerenciadora")) or unidade
        if not num:
            continue
        upsert("dadosabertos.arp", ["numero_ata", "unidade_gerenciadora"], {
            "numero_ata": num,
            "unidade_gerenciadora": ug,
            "nome_unidade_gerenciadora": a.get("nomeUnidadeGerenciadora"),
            "codigo_orgao": _s(a.get("codigoOrgao")),
            "nome_orgao": a.get("nomeOrgao"),
            "link_ata_pncp": a.get("linkAtaPNCP"),
            "link_compra_pncp": a.get("linkCompraPNCP"),
            "numero_compra": _s(a.get("numeroCompra")),
            "ano_compra": _s(a.get("anoCompra")),
            "codigo_modalidade": _s(a.get("codigoModalidadeCompra")),
            "nome_modalidade": a.get("nomeModalidadeCompra"),
            "data_assinatura": _d(a.get("dataAssinatura")),
            "data_vigencia_inicial": _d(a.get("dataVigenciaInicial")),
            "data_vigencia_final": _d(a.get("dataVigenciaFinal")),
            "valor_total": _num(a.get("valorTotal")),
            "status_ata": a.get("statusAta"),
            "objeto": a.get("objeto"),
            "fonte": "dadosabertos_arp",
            "fonte_url": ARP_LIST,
            "raw_json": a,
        })
        tot_arp += 1

    tot_itens = 0
    for it in _paginar(ARP_ITENS, base_params):
        num = it.get("numeroAtaRegistroPreco")
        ug = _s(it.get("codigoUnidadeGerenciadora")) or unidade
        numero_item = _s(it.get("numeroItem"))
        if not num or numero_item is None:
            continue
        upsert(
            "dadosabertos.arp_itens",
            ["numero_ata", "unidade_gerenciadora", "numero_item", "ni_fornecedor"],
            {
                "numero_ata": num,
                "unidade_gerenciadora": ug,
                "numero_item": numero_item,
                "ni_fornecedor": _s(it.get("niFornecedor")) or "",
                "codigo_item": _s(it.get("codigoItem")),
                "descricao_item": it.get("descricaoItem"),
                "tipo_item": it.get("tipoItem"),
                "quantidade_homologada": _num(it.get("quantidadeHomologadaItem")),
                "classificacao_fornecedor": _s(it.get("classificacaoFornecedor")),
                "nome_fornecedor": it.get("nomeRazaoSocialFornecedor"),
                "numero_compra": _s(it.get("numeroCompra")),
                "ano_compra": _s(it.get("anoCompra")),
                "codigo_modalidade": _s(it.get("codigoModalidadeCompra")),
                "data_vigencia_inicial": _d(it.get("dataVigenciaInicial")),
                "data_vigencia_final": _d(it.get("dataVigenciaFinal")),
                "fonte": "dadosabertos_arp_itens",
                "fonte_url": ARP_ITENS,
                "raw_json": it,
            },
        )
        tot_itens += 1
    return tot_arp, tot_itens


def _listar_atas() -> list[tuple[str, str]]:
    with cursor() as cur:
        cur.execute("SELECT numero_ata, unidade_gerenciadora FROM dadosabertos.arp")
        return cur.fetchall()


def _listar_ata_itens() -> list[tuple[str, str, str]]:
    with cursor() as cur:
        cur.execute(
            "SELECT DISTINCT numero_ata, unidade_gerenciadora, numero_item FROM dadosabertos.arp_itens"
        )
        return cur.fetchall()


def _coletar_empenho_saldo(ata: tuple[str, str]) -> int:
    numero_ata, ug = ata
    params = {"numeroAta": numero_ata, "unidadeGerenciadora": ug}
    n = 0
    for e in _paginar(ARP_EMPENHOS, params):
        numero_item = _s(e.get("numeroItem"))
        if numero_item is None:
            continue
        upsert(
            "dadosabertos.arp_item_empenho_saldo",
            ["numero_ata", "unidade_gerenciadora", "numero_item", "unidade", "tipo"],
            {
                "numero_ata": numero_ata,
                "unidade_gerenciadora": ug,
                "numero_item": numero_item,
                "unidade": _s(e.get("unidade")) or "",
                "tipo": _s(e.get("tipo")) or "",
                "quantidade_registrada": _num(e.get("quantidadeRegistrada")),
                "quantidade_empenhada": _num(e.get("quantidadeEmpenhada")),
                "saldo_empenho": _num(e.get("saldoEmpenho")),
                "data_atualizacao": e.get("dataHoraAtualizacao"),
                "fonte": "dadosabertos_arp_empenho_saldo",
                "fonte_url": ARP_EMPENHOS,
                "raw_json": e,
            },
        )
        n += 1
    return n


def _coletar_unid_adesao(ata_item: tuple[str, str, str]) -> tuple[int, int]:
    numero_ata, ug, numero_item = ata_item
    params = {"numeroAta": numero_ata, "unidadeGerenciadora": ug, "numeroItem": numero_item}

    tot_unid = 0
    for seq, u in enumerate(_paginar(ARP_UNIDADES, params), start=1):
        upsert(
            "dadosabertos.arp_item_unidades",
            ["numero_ata", "unidade_gerenciadora", "numero_item", "seq"],
            {
                "numero_ata": numero_ata,
                "unidade_gerenciadora": ug,
                "numero_item": numero_item,
                "seq": seq,
                "codigo_pdm": _s(u.get("codigoPdm")),
                "descricao_item": u.get("descricaoItem"),
                "fornecedor": u.get("fornecedor"),
                "quantidade_registrada": _num(u.get("quantidadeRegistrada")),
                "saldo_adesoes": _num(u.get("saldoAdesoes")),
                "fonte": "dadosabertos_arp_unidades",
                "fonte_url": ARP_UNIDADES,
                "raw_json": u,
            },
        )
        tot_unid += 1

    tot_ades = 0
    for seq, ad in enumerate(_paginar(ARP_ADESOES, params), start=1):
        upsert(
            "dadosabertos.arp_item_adesoes",
            ["numero_ata", "unidade_gerenciadora", "numero_item", "seq"],
            {
                "numero_ata": numero_ata,
                "unidade_gerenciadora": ug,
                "numero_item": numero_item,
                "seq": seq,
                "fonte": "dadosabertos_arp_adesoes",
                "fonte_url": ARP_ADESOES,
                "raw_json": ad,
            },
        )
        tot_ades += 1
    return tot_unid, tot_ades
