"""Helper de paralelismo: ThreadPoolExecutor com tratamento de erro por item."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

from .config import WORKERS

log = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def map_workers(
    fn: Callable[[T], R],
    items: Iterable[T],
    *,
    desc: str,
    workers: int | None = None,
    reducer: Callable[[list[R]], R] | None = None,
) -> R | list[R]:
    """Roda fn(item) em paralelo. Excecoes sao logadas por item, nao derrubam o resto.

    Se reducer for fornecido, agrega os resultados; senao retorna a lista.
    Resultados de itens que falharam sao omitidos.
    """
    n = workers or WORKERS
    items_list = list(items)
    if not items_list:
        return reducer([]) if reducer else []
    if n <= 1 or len(items_list) == 1:
        results: list[R] = []
        for it in items_list:
            try:
                results.append(fn(it))
            except Exception as e:
                log.exception("[%s] falha em item: %s", desc, e)
        return reducer(results) if reducer else results

    results = []
    with ThreadPoolExecutor(max_workers=n, thread_name_prefix=desc) as ex:
        futures = {ex.submit(fn, it): it for it in items_list}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                log.exception("[%s] falha em item %r: %s", desc, futures[fut], e)
    return reducer(results) if reducer else results


def sum_int(rs: list[int]) -> int:
    return sum(rs)


def sum_tuple(width: int) -> Callable[[list[tuple]], tuple]:
    """Reducer que soma tuplas de N inteiros componente a componente."""
    def _r(rs: list[tuple]) -> tuple:
        acc = [0] * width
        for t in rs:
            for i, v in enumerate(t):
                acc[i] += v or 0
        return tuple(acc)
    return _r
