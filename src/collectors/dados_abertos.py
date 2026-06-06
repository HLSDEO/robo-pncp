"""Coletores Dados Abertos Comprasgov (dadosabertos.compras.gov.br).

Hierarquia de materiais/servicos e ARPs (itens, empenhos, adesoes).
Os paths de endpoint estao em constantes no topo do arquivo: se o swagger
mudar, ajuste ali.
"""
import logging

from ..config import DADOSABERTOS_BASE, PAGE_SIZE
from ..http_client import get_json
from ..db import upsert, cursor

log = logging.getLogger(__name__)

# -------- endpoints (ajuste se o swagger divergir) --------
MAT_GRUPO_URL   = f"{DADOSABERTOS_BASE}/modulo-material/4_consultarGrupoMaterial"
MAT_CLASSE_URL  = f"{DADOSABERTOS_BASE}/modulo-material/3_consultarClasseMaterial"
MAT_PDM_URL     = f"{DADOSABERTOS_BASE}/modulo-material/2_consultarPdm"
MAT_URL         = f"{DADOSABERTOS_BASE}/modulo-material/1_consultarMaterial"

SVC_GRUPO_URL   = f"{DADOSABERTOS_BASE}/modulo-servicos/3_consultarGrupoServico"
SVC_CLASSE_URL  = f"{DADOSABERTOS_BASE}/modulo-servicos/2_consultarClasseServico"
SVC_URL         = f"{DADOSABERTOS_BASE}/modulo-servicos/1_consultarServico"

ARP_URL         = f"{DADOSABERTOS_BASE}/modulo-contratacoes/5_consultarAtasRegistroPreco"
ARP_ITENS_URL   = f"{DADOSABERTOS_BASE}/modulo-contratacoes/6_consultarItensAtasRegistroPreco"
ARP_EMP_URL     = f"{DADOSABERTOS_BASE}/modulo-contratacoes/7_consultarEmpenhosItensAtasRegistroPreco"
ARP_ADESAO_URL  = f"{DADOSABERTOS_BASE}/modulo-contratacoes/8_consultarAdesoesItensAtasRegistroPreco"


def _paginar_dadosabertos(url: str, extra: dict | None = None):
    """Pagina endpoints do dadosabertos. Aceita varios formatos de resposta."""
    pagina = 1
    while True:
        params = {"pagina": pagina, "tamanhoPagina": PAGE_SIZE}
        if extra:
            params.update(extra)
        try:
            data = get_json(url, params=params)
        except Exception as e:
            log.warning("falha em %s (pagina %d): %s", url, pagina, e)
            return
        if data is None:
            return
        if isinstance(data, list):
            items = data
        else:
            items = data.get("resultado") or data.get("data") or data.get("_embedded") or []
            if isinstance(items, dict):
                # _embedded.{key}
                items = next(iter(items.values()), [])
        if not items:
            return
        for it in items:
            yield it
        if len(items) < PAGE_SIZE:
            return
        pagina += 1


def _g(d: dict, *keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def coletar_hierarquia_material() -> int:
    total = 0
    for g in _paginar_dadosabertos(MAT_GRUPO_URL):
        cod = _g(g, "codigoGrupo", "codigo")
        if not cod:
            continue
        upsert("dadosabertos.material_grupo", ["codigo_grupo"], {
            "codigo_grupo": str(cod),
            "nome_grupo": _g(g, "nomeGrupo", "nome"),
            "fonte": "dadosabertos_material_grupo",
            "fonte_url": MAT_GRUPO_URL,
            "raw_json": g,
        })
        total += 1
    for c in _paginar_dadosabertos(MAT_CLASSE_URL):
        cod = _g(c, "codigoClasse", "codigo")
        if not cod:
            continue
        upsert("dadosabertos.material_classe", ["codigo_classe"], {
            "codigo_classe": str(cod),
            "codigo_grupo": str(_g(c, "codigoGrupo") or ""),
            "nome_classe": _g(c, "nomeClasse", "nome"),
            "fonte": "dadosabertos_material_classe",
            "fonte_url": MAT_CLASSE_URL,
            "raw_json": c,
        })
        total += 1
    for p in _paginar_dadosabertos(MAT_PDM_URL):
        cod = _g(p, "codigoPdm", "codigo")
        if not cod:
            continue
        upsert("dadosabertos.material_pdm", ["codigo_pdm"], {
            "codigo_pdm": str(cod),
            "codigo_classe": str(_g(p, "codigoClasse") or ""),
            "nome_pdm": _g(p, "nomePdm", "nome"),
            "fonte": "dadosabertos_material_pdm",
            "fonte_url": MAT_PDM_URL,
            "raw_json": p,
        })
        total += 1
    for m in _paginar_dadosabertos(MAT_URL):
        cod = _g(m, "codigoMaterial", "codigo")
        if not cod:
            continue
        upsert("dadosabertos.material", ["codigo_material"], {
            "codigo_material": str(cod),
            "codigo_pdm": str(_g(m, "codigoPdm") or ""),
            "codigo_classe": str(_g(m, "codigoClasse") or ""),
            "codigo_grupo": str(_g(m, "codigoGrupo") or ""),
            "nome_material": _g(m, "nomeMaterial", "nome", "descricao"),
            "fonte": "dadosabertos_material",
            "fonte_url": MAT_URL,
            "raw_json": m,
        })
        total += 1
    log.info("hierarquia material=%d", total)
    return total


def coletar_hierarquia_servico() -> int:
    total = 0
    for g in _paginar_dadosabertos(SVC_GRUPO_URL):
        cod = _g(g, "codigoGrupo", "codigo")
        if not cod:
            continue
        upsert("dadosabertos.servico_grupo", ["codigo_grupo"], {
            "codigo_grupo": str(cod),
            "nome_grupo": _g(g, "nomeGrupo", "nome"),
            "fonte": "dadosabertos_servico_grupo",
            "fonte_url": SVC_GRUPO_URL,
            "raw_json": g,
        })
        total += 1
    for c in _paginar_dadosabertos(SVC_CLASSE_URL):
        cod = _g(c, "codigoClasse", "codigo")
        if not cod:
            continue
        upsert("dadosabertos.servico_classe", ["codigo_classe"], {
            "codigo_classe": str(cod),
            "codigo_grupo": str(_g(c, "codigoGrupo") or ""),
            "nome_classe": _g(c, "nomeClasse", "nome"),
            "fonte": "dadosabertos_servico_classe",
            "fonte_url": SVC_CLASSE_URL,
            "raw_json": c,
        })
        total += 1
    for s in _paginar_dadosabertos(SVC_URL):
        cod = _g(s, "codigoServico", "codigo")
        if not cod:
            continue
        upsert("dadosabertos.servico", ["codigo_servico"], {
            "codigo_servico": str(cod),
            "codigo_classe": str(_g(s, "codigoClasse") or ""),
            "codigo_grupo": str(_g(s, "codigoGrupo") or ""),
            "nome_servico": _g(s, "nomeServico", "nome", "descricao"),
            "fonte": "dadosabertos_servico",
            "fonte_url": SVC_URL,
            "raw_json": s,
        })
        total += 1
    log.info("hierarquia servico=%d", total)
    return total


def _arp_a_buscar():
    """ARPs partem dos editais/atas ja coletados. Buscamos por CNPJ do orgao."""
    with cursor() as cur:
        cur.execute("SELECT DISTINCT orgao_cnpj FROM pncp.editais WHERE orgao_cnpj IS NOT NULL")
        cnpjs = [r[0] for r in cur.fetchall()]
        cur.execute(
            """
            SELECT DISTINCT a.numero_controle_pncp, a.orgao_cnpj
              FROM pncp.atas a
             WHERE a.numero_controle_pncp IS NOT NULL
            """
        )
        atas_pncp = cur.fetchall()
    return cnpjs, atas_pncp


def coletar_arp_e_dependentes() -> tuple[int, int, int, int]:
    tot_arp = tot_itens = tot_emp = tot_ades = 0
    cnpjs, atas_pncp = _arp_a_buscar()

    for cnpj in cnpjs:
        for a in _paginar_dadosabertos(ARP_URL, {"cnpjOrgao": cnpj}):
            ncp = _g(a, "numeroControlePNCPAta", "numeroControlePNCP")
            if not ncp:
                continue
            upsert("dadosabertos.arp", ["numero_controle_pncp_ata"], {
                "numero_controle_pncp_ata": ncp,
                "numero_controle_pncp_compra": _g(a, "numeroControlePNCPCompra"),
                "orgao_cnpj": _g(a, "cnpjOrgao") or cnpj,
                "unidade_codigo": _g(a, "codigoUnidade"),
                "numero_ata": _g(a, "numeroAtaRegistroPreco", "numeroAta"),
                "ano_ata": _g(a, "anoAta"),
                "sequencial_ata": _g(a, "sequencialAta"),
                "data_assinatura": _g(a, "dataAssinatura"),
                "data_vigencia_inicio": _g(a, "dataVigenciaInicio"),
                "data_vigencia_fim": _g(a, "dataVigenciaFim"),
                "cancelado": _g(a, "cancelado"),
                "fonte": "dadosabertos_arp",
                "fonte_url": ARP_URL,
                "raw_json": a,
            })
            tot_arp += 1

    # Itens, empenhos, adesoes por ARP coletada (e tambem pelas atas vindas do PNCP)
    with cursor() as cur:
        cur.execute("SELECT numero_controle_pncp_ata FROM dadosabertos.arp")
        arp_ncps = {r[0] for r in cur.fetchall()}
    arp_ncps |= {a[0] for a in atas_pncp}

    for ncp in arp_ncps:
        for it in _paginar_dadosabertos(ARP_ITENS_URL, {"numeroControlePNCPAta": ncp}):
            num = _g(it, "numeroItem")
            if num is None:
                continue
            upsert(
                "dadosabertos.arp_itens",
                ["numero_controle_pncp_ata", "numero_item"],
                {
                    "numero_controle_pncp_ata": ncp,
                    "numero_item": num,
                    "descricao": _g(it, "descricao"),
                    "material_ou_servico": _g(it, "materialOuServico"),
                    "quantidade_registrada": _g(it, "quantidadeRegistrada", "quantidade"),
                    "valor_unitario_registrado": _g(it, "valorUnitarioRegistrado", "valorUnitario"),
                    "unidade_medida": _g(it, "unidadeMedida"),
                    "ni_fornecedor": _g(it, "niFornecedor", "cnpjFornecedor"),
                    "nome_razao_social": _g(it, "nomeRazaoSocialFornecedor", "razaoSocial"),
                    "fonte": "dadosabertos_arp_itens",
                    "fonte_url": ARP_ITENS_URL,
                    "raw_json": it,
                },
            )
            tot_itens += 1

        for emp in _paginar_dadosabertos(ARP_EMP_URL, {"numeroControlePNCPAta": ncp}):
            num_item = _g(emp, "numeroItem")
            num_emp = _g(emp, "numeroEmpenho")
            if num_item is None or not num_emp:
                continue
            upsert(
                "dadosabertos.arp_item_empenhos",
                ["numero_controle_pncp_ata", "numero_item", "numero_empenho"],
                {
                    "numero_controle_pncp_ata": ncp,
                    "numero_item": num_item,
                    "numero_empenho": str(num_emp),
                    "ug_empenho": _g(emp, "ugEmpenho", "codigoUg"),
                    "data_empenho": _g(emp, "dataEmpenho"),
                    "valor_empenhado": _g(emp, "valorEmpenhado"),
                    "quantidade_empenhada": _g(emp, "quantidadeEmpenhada"),
                    "fonte": "dadosabertos_arp_empenhos",
                    "fonte_url": ARP_EMP_URL,
                    "raw_json": emp,
                },
            )
            tot_emp += 1

        for ad in _paginar_dadosabertos(ARP_ADESAO_URL, {"numeroControlePNCPAta": ncp}):
            num_item = _g(ad, "numeroItem")
            seq = _g(ad, "sequencialAdesao", "sequencial") or 1
            if num_item is None:
                continue
            upsert(
                "dadosabertos.arp_item_adesoes",
                ["numero_controle_pncp_ata", "numero_item", "sequencial_adesao"],
                {
                    "numero_controle_pncp_ata": ncp,
                    "numero_item": num_item,
                    "sequencial_adesao": seq,
                    "cnpj_aderente": _g(ad, "cnpjAderente", "cnpjOrgaoAderente"),
                    "nome_aderente": _g(ad, "nomeAderente", "razaoSocialAderente"),
                    "quantidade_aderida": _g(ad, "quantidadeAderida"),
                    "valor_aderido": _g(ad, "valorAderido"),
                    "data_adesao": _g(ad, "dataAdesao"),
                    "fonte": "dadosabertos_arp_adesoes",
                    "fonte_url": ARP_ADESAO_URL,
                    "raw_json": ad,
                },
            )
            tot_ades += 1
    log.info("arp=%d itens=%d emp=%d ades=%d", tot_arp, tot_itens, tot_emp, tot_ades)
    return tot_arp, tot_itens, tot_emp, tot_ades
