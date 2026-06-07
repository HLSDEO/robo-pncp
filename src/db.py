import logging
from contextlib import contextmanager

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import DB, WORKERS, UNIDADES_PF

log = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def _conninfo() -> str:
    return (
        f"host={DB['host']} port={DB['port']} dbname={DB['dbname']} "
        f"user={DB['user']} password={DB['password']}"
    )


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        # WORKERS + 2 = folga para meta_execucao e seed rodando em paralelo
        max_size = WORKERS + 2
        _pool = ConnectionPool(
            conninfo=_conninfo(),
            min_size=1,
            max_size=max_size,
            kwargs={"autocommit": False},
        )
        _pool.wait()
        log.info("pool inicializado size=%d", max_size)
    return _pool


@contextmanager
def cursor():
    """Pega conexao do pool, commit no sucesso, rollback no erro."""
    with pool().connection() as conn:
        try:
            with conn.cursor() as cur:
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def seed_unidades():
    with cursor() as cur:
        for sigla, codigo in UNIDADES_PF.items():
            cur.execute(
                """
                INSERT INTO meta_unidades_pf (sigla, codigo_unidade)
                VALUES (%s, %s)
                ON CONFLICT (sigla) DO UPDATE SET codigo_unidade = EXCLUDED.codigo_unidade
                """,
                (sigla, codigo),
            )


def iniciar_execucao() -> int:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO meta_execucao (status) VALUES ('rodando') RETURNING id"
        )
        return cur.fetchone()[0]


def finalizar_execucao(exec_id: int, status: str, contadores: dict, erro: str | None = None):
    with cursor() as cur:
        cur.execute(
            """
            UPDATE meta_execucao
               SET finalizado_em = now(),
                   status = %s,
                   contadores = %s,
                   erro = %s
             WHERE id = %s
            """,
            (status, Jsonb(contadores), erro, exec_id),
        )


def upsert(table: str, pk_cols: list[str], row: dict):
    """Upsert generico. row deve conter 'raw_json' como dict (sera convertido para Jsonb)."""
    cols = list(row.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in cols if c not in pk_cols
    )
    pk_list = ", ".join(pk_cols)
    on_conflict = (
        f"ON CONFLICT ({pk_list}) DO UPDATE SET {updates}"
        if updates
        else f"ON CONFLICT ({pk_list}) DO NOTHING"
    )
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) {on_conflict}"
    values = []
    for c in cols:
        v = row[c]
        if c == "raw_json" or isinstance(v, (dict, list)):
            values.append(Jsonb(v))
        else:
            values.append(v)
    with cursor() as cur:
        cur.execute(sql, values)


def listar_editais_para_drilldown() -> list[tuple[str, str, str, str]]:
    """Retorna (orgao_cnpj, ano, numero_sequencial, numero_controle_pncp) de todos os editais."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT orgao_cnpj, ano, numero_sequencial, numero_controle_pncp
              FROM pncp_editais
             WHERE orgao_cnpj IS NOT NULL AND ano IS NOT NULL AND numero_sequencial IS NOT NULL
            """
        )
        return cur.fetchall()


def listar_itens_com_resultado() -> list[tuple[str, str, str, int]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT orgao_cnpj, ano, numero_sequencial, numero_item
              FROM pncp_edital_itens
             WHERE tem_resultado IS TRUE
            """
        )
        return cur.fetchall()


def buscar_edital_pncp(
    unidade_compra: str | None,
    modalidade: str | None,
    licitacao_numero: str | None,
) -> str | None:
    """Encontra o numero_controle_pncp em pncp_editais por (unidade_codigo,
    ano, numero_sequencial, modalidade_nome com prefix). Retorna None se nao
    achou ou se algum dos 3 campos esta vazio."""
    if not (unidade_compra and modalidade and licitacao_numero):
        return None
    if "/" not in licitacao_numero:
        return None
    seq_raw, ano_raw = licitacao_numero.split("/", 1)
    seq_raw, ano_raw = seq_raw.strip(), ano_raw.strip()
    if not (seq_raw.isdigit() and ano_raw.isdigit()):
        return None
    seq = str(int(seq_raw))   # remove zeros a esquerda ("00018" -> "18")
    ano = str(int(ano_raw))
    with cursor() as cur:
        cur.execute(
            """
            SELECT numero_controle_pncp
              FROM pncp_editais
             WHERE unidade_codigo = %s
               AND ano = %s
               AND numero_sequencial = %s
               AND modalidade_nome ILIKE %s
             LIMIT 1
            """,
            (unidade_compra, ano, seq, f"{modalidade}%"),
        )
        r = cur.fetchone()
        return r[0] if r else None
