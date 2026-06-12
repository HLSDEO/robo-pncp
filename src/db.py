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

    coletado_em fica so no INSERT (DEFAULT now()).
    atualizado_em e marcado com now() APENAS quando o registro ja existe E algum
    dado realmente mudou em relacao ao que esta no banco. A comparacao usa
    `IS DISTINCT FROM` sobre as colunas de dados (ignora fonte/fonte_url, que sao
    procedencia e nao 'dado'). Se a API devolveu exatamente o mesmo conteudo, o
    ON CONFLICT cai num WHERE falso -> nenhuma linha e tocada e atualizado_em
    permanece como estava."""
    cols = list(row.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    pk_list = ", ".join(pk_cols)
    non_pk = [c for c in cols if c not in pk_cols]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in non_pk)
    # colunas de dados comparadas p/ decidir se houve mudanca (exclui procedencia:
    # fonte e constante; fonte_url muda so pela paginacao, nao e 'dado')
    cmp_cols = [c for c in non_pk if c not in ("fonte", "fonte_url")]
    if updates and cmp_cols:
        distinct = " OR ".join(
            f"{table}.{c} IS DISTINCT FROM EXCLUDED.{c}" for c in cmp_cols
        )
        on_conflict = (
            f"ON CONFLICT ({pk_list}) DO UPDATE SET {updates}, atualizado_em = now() "
            f"WHERE {distinct}"
        )
    else:
        # so PK (+ procedencia): nada de dado pra comparar -> nunca atualiza
        on_conflict = f"ON CONFLICT ({pk_list}) DO NOTHING"
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


