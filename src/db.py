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
    """Upsert generico. row deve conter 'raw_json' como dict (sera convertido para Jsonb).

    coletado_em fica so no INSERT (DEFAULT now()); atualizado_em e marcado com
    now() sempre que o caminho ON CONFLICT DO UPDATE e executado."""
    cols = list(row.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in cols if c not in pk_cols
    )
    update_set = f"{updates}, atualizado_em = now()" if updates else "atualizado_em = now()"
    pk_list = ", ".join(pk_cols)
    on_conflict = f"ON CONFLICT ({pk_list}) DO UPDATE SET {update_set}"
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


