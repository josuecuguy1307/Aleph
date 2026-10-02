"""
pool.py — pool de conexiones psycopg2 para la INFRA (T8).

POR QUÉ existe aparte de db.get_conn(): el código de features abre una conexión
fresca por request y la cierra (patrón `conn = _conn(); try: ...; finally: conn.close()`).
Eso es seguro pero, bajo carga concurrente (el worker pool corriendo N runs a la vez +
los requests), abrir/cerrar conexiones constantemente cuesta y puede acercarse al tope
`max_connections` de Postgres. Este pool lo usa la INFRA (worker pool, health checks)
SIN tocar el contrato de db.get_conn() — la adopción es opt-in y reversible.

Contrato:
    with pooled_conn() as conn:
        with conn.cursor() as cur: ...
        conn.commit()
La conexión se DEVUELVE al pool al salir del `with` (no se cierra). Si el bloque
lanza una excepción, la conexión se descarta (putconn close=True) por si quedó en
estado sucio — el pool abre una nueva la próxima vez.

Tamaño: PUPPET_DB_POOL_MIN (default 1) .. PUPPET_DB_POOL_MAX (default 10). El máximo
acota cuántas conexiones de infra pueden estar vivas a la vez — la primera línea de
defensa contra agotar Postgres bajo concurrencia.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import sys

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from db import conn_params  # noqa: E402

_pool = None
_pool_lock = threading.Lock()


def _pool_size() -> tuple[int, int]:
    mn = int(os.environ.get("PUPPET_DB_POOL_MIN", "1"))
    mx = int(os.environ.get("PUPPET_DB_POOL_MAX", "10"))
    return mn, max(mx, mn)


def get_pool(dbname: Optional[str] = None):
    """Singleton del ThreadedConnectionPool (thread-safe lazy init).

    Sólo existe en el plano de control: en el cliente no hay pool (ver `pooled_conn`).
    """
    if _es_cliente():
        raise RuntimeError(
            "get_pool() no aplica en el cliente: SQLite no se poolea. Usa pooled_conn().")
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg2.pool import ThreadedConnectionPool
                mn, mx = _pool_size()
                _pool = ThreadedConnectionPool(mn, mx, **conn_params(dbname))
    return _pool


def _es_cliente() -> bool:
    """El rol, vía la capa canónica (no se duplica la lógica del selector)."""
    from db import es_cliente
    return es_cliente()


@contextmanager
def _conn_cliente(dbname: Optional[str] = None) -> Iterator[object]:
    """El equivalente del pool en el cliente: `conectar()` + `close()` por uso.

    ⚠️ CORRECCIÓN [fix/wedge-escritura]. Este docstring decía que en el cliente "no hay
    pool, se abre y se cierra por operación, y poolear no compra nada". **Eso resultó
    FALSO y era el bug**: abrir y cerrar por operación, con varios pools de hilos contra
    el mismo .db, traba el proceso ENTERO para siempre en el mutex del VFS de SQLite
    (stacks, repro mínimo y medición en `sqlite_db.py` §EL DEADLOCK DEL VFS). Lo que
    poolear compra no es velocidad: es que el open y el close dejen de pisarse.

    Hoy `sqlite_db.conectar()` REUSA conexiones y `close()` las devuelve, así que este
    contextmanager sigue siendo correcto tal cual está escrito — pero ya no describe
    conexiones efímeras. Se conserva el razonamiento original, corregido, porque el
    argumento equivocado es más peligroso que el código equivocado:

    - "abrir en SQLite es sólo un `open()` de archivo y no hay servidor que agotar" —
      cierto, y aun así el costo estaba en otro lado: el mutex de la tabla de inodos.
    - "`sqlite3` no comparte conexiones entre hilos con seguridad" — cierto para uso
      SIMULTÁNEO. El almacén presta una conexión a UN caller por vez (`check_same_thread
      =False` ya estaba puesto justamente para eso), que no es compartir.

    ⚠️ Y ES POR ACÁ QUE ENTRA EL PRAGMA DE FK EN LA COLA. `conectar()` aplica
    `foreign_keys=ON`, `journal_mode=WAL` y `busy_timeout` en cada conexión que devuelve.
    El worker pool corre 4 hilos + un heartbeat por job en curso: sin WAL y sin
    busy_timeout, dos escrituras simultáneas dan `database is locked` en vez de esperar
    turno; sin el pragma, los CASCADE de `job_queue` hacia `runs`/`users` no existen.
    """
    from db import get_conn
    conn = get_conn(dbname)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def pooled_conn(dbname: Optional[str] = None) -> Iterator[object]:
    """Toma una conexión del pool y la devuelve al salir. Descarta la conexión si
    el bloque falló (puede haber quedado en transacción abortada).

    En el cliente no hay pool: devuelve una conexión SQLite fresca (ver `_conn_cliente`).
    El contrato `with pooled_conn() as conn:` es el mismo en los dos roles.
    """
    if _es_cliente():
        with _conn_cliente(dbname) as c:
            yield c
        return
    pool = get_pool(dbname)
    conn = pool.getconn()
    broken = False
    try:
        yield conn
    except Exception:
        broken = True
        raise
    finally:
        try:
            if broken:
                pool.putconn(conn, close=True)
            else:
                # devolver limpia: si el caller dejó una tx abierta, la cerramos.
                if getattr(conn, "closed", 1) == 0:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                pool.putconn(conn)
        except Exception:
            pass


def close_pool() -> None:
    """Cierra todas las conexiones del pool (shutdown del proceso).

    En el cliente es un no-op: no hay pool que cerrar, cada conexión ya se cierra al
    salir de su `with`. Se deja llamable para que el shutdown sea el mismo en los dos
    roles y el caller no tenga que preguntar por el rol.
    """
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            finally:
                _pool = None
