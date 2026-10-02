"""
jobs.py — cola de trabajo DURABLE. Postgres en el plano de control, SQLite en el
cliente (tabla job_queue: migración 0002 · schema_sqlite.sql §17).

API pura de cola: cada función recibe una conexión y hace COMMIT explícito por
operación (idempotente, sin transacción colgada — mismo patrón que phase1/repo.py).

Estados: queued → running → (done | error). Un job 'running' cuyo worker murió
(heartbeat viejo) se RECLAMA: vuelve a 'queued' si le quedan intentos, o cae a 'error'
(agotado). Eso es lo que hace que un reinicio no pierda trabajo.

⚠️ EL DEQUEUE ES LO ÚNICO QUE NO ES EL MISMO SQL EN LOS DOS DIALECTOS. [Casa 2 · 2.3]

    control (Postgres)  UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1)
    client  (SQLite)    UPDATE … WHERE id = (SELECT … LIMIT 1) AND status='queued'

`SKIP LOCKED` no existe en SQLite, y `platform/db/dialect.py` lo RECHAZA en vez de
traducirlo (un SQL plausible y equivocado es peor que uno que no corre). El reemplazo
es un guard optimista en el propio UPDATE: SQLite serializa escritores, así que el
que llega segundo matchea 0 filas y reintenta.

**Postgres se queda con `SKIP LOCKED` a propósito.** El guard solo NO es equivalente
ahí: bajo READ COMMITTED el worker B ve el row todavía 'queued', se bloquea en el lock
de fila de A, y cuando A commitea re-evalúa el WHERE, falla el guard y devuelve 0 filas
— o sea B no toma NADA aunque haya 500 jobs esperando. Eso es exactamente el problema
que `SKIP LOCKED` existe para resolver. (Razonamiento, no medición: no corrí el caso
concurrente contra PG. Lo que sí está medido es que el camino de control no cambia,
porque el SQL que emite es byte por byte el de antes.)

Qué está MEDIDO del lado SQLite (8 hilos · 500 jobs, schema real):
  · sentencia única con guard      → 500 reclamos, 500 jobs distintos, 0 doble-claim, 0 errores
  · dos sentencias SIN guard       → 297 de 300 jobs DOBLE-CLAIMEADOS (attempts hasta 8)
  · dos sentencias CON guard       → 0 doble-claim
  · sentencia única SIN guard      → 0 doble-claim (el subquery ya filtra por status)
El guard es load-bearing cuando el claim se parte en dos pasos, que es la traducción
ingenua a la que cualquiera llega al sacar `SKIP LOCKED`. En la forma de una sola
sentencia es redundante — se conserva igual: cuesta cero y ancla la garantía en la
sentencia en vez de depender del orden de evaluación de SQLite.

⚠️ Y EL CLAIM TIENE QUE SER LA PRIMERA SENTENCIA DE SU TRANSACCIÓN. Medido: si la
conexión ya abrió un snapshot de lectura, el UPDATE da `SQLITE_BUSY_SNAPSHOT` —
`database is locked`, 600 veces en 200 jobs — y `busy_timeout` NO lo cubre (no es
contención de lock, es un snapshot viejo que no se puede promover). Por eso el
reintento commitea después de CADA intento en vez de encadenarlos en una transacción.
"""

from __future__ import annotations

import json
import socket
import os
import sys
from pathlib import Path
from typing import Any, Optional

# El selector de rol vive en platform/db/db.py — una decisión, un lugar (2.2b). Se
# carga por ruta porque `platform/` no es un paquete importable desde acá; es el mismo
# patrón que ya usan worker.py y platform/db/pool.py.
_PLATFORM_DB = Path(__file__).resolve().parents[4] / "platform" / "db"
if str(_PLATFORM_DB) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DB))

# columnas devueltas (orden estable para los SELECT *)
_COLS = (
    "id, kind, status, priority, payload, result, error, run_id, user_id, "
    "attempts, max_attempts, locked_by, locked_at, heartbeat_at, available_at, "
    "created_at, started_at, finished_at"
)

#: Columnas JSON de job_queue. En Postgres son JSONB y psycopg2 las devuelve ya
#: decodificadas; en SQLite son TEXT y vuelven como str.
_COLS_JSON = ("payload", "result")

#: Cuántas veces reintenta el claim del cliente antes de ceder el turno. Cada vuelta
#: cuesta un UPDATE que matcheó 0 filas + un SELECT de existencia, y sólo se dan
#: cuando otro worker ganó la carrera. Ceder no pierde trabajo: el job sigue 'queued'
#: y el siguiente poll lo toma.
_CLAIM_REINTENTOS = 8


def _es_cliente() -> bool:
    """El rol, vía la capa canónica (no se duplica la lógica del selector)."""
    from db import es_cliente          # platform/db/db.py
    return es_cliente()


def worker_identity(suffix: str = "") -> str:
    """Id legible y único de un worker: host:pid[:suffix]."""
    base = f"{socket.gethostname()}:{os.getpid()}"
    return f"{base}:{suffix}" if suffix else base


def _cursor_dict(conn):
    """Cursor con filas por NOMBRE en los dos dialectos.

    En SQLite ya vienen por nombre (`sqlite3.Row`, ver platform/db/sqlite_db.py) y
    `RealDictCursor` ni siquiera se podría importar sin psycopg2 instalado. En
    Postgres hace falta sí o sí: sin él psycopg2 devuelve tuplas y `_row()` —que hace
    `dict(r)`— levantaría un dict de índices en vez de columnas.
    """
    if _es_cliente():
        return conn.cursor()
    from psycopg2.extras import RealDictCursor
    return conn.cursor(cursor_factory=RealDictCursor)


def _decodificar(fila: dict) -> dict:
    """JSON de texto → objeto Python. SÓLO en el cliente.

    Sin esto la cola arranca, reclama y no doble-claimea… y después `run_handler`
    hace `payload.get('recipe')` sobre un str y muere con AttributeError en CADA job
    (medido). Es el fallo a un módulo de distancia de su causa: "la cola anda" sería
    verdad y el producto estaría roto igual.

    El `if` de rol no es defensivo, es la garantía de que el plano de control no
    cambia: contra Postgres esta función no toca nada y devuelve la fila tal cual.
    """
    if not _es_cliente():
        return fila
    for col in _COLS_JSON:
        v = fila.get(col)
        if isinstance(v, str):
            try:
                fila[col] = json.loads(v)
            except ValueError as exc:
                # La columna es NOT NULL DEFAULT '{}' y sólo la escribe json.dumps: si
                # no parsea, la fila está corrupta. Ruidoso y con el job señalado.
                raise ValueError(
                    f"job_queue.{col} no es JSON válido (job {fila.get('id')}): {exc}"
                ) from exc
    return fila


def _row(cur) -> Optional[dict]:
    r = cur.fetchone()
    return _decodificar(dict(r)) if r else None


# ── escritura ──────────────────────────────────────────────────────────────────

def enqueue(
    conn,
    kind: str,
    payload: dict,
    *,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    priority: int = 0,
    max_attempts: int = 1,
    delay_s: float = 0.0,
) -> dict:
    """Encola un job. Devuelve el row creado (status='queued')."""
    with _cursor_dict(conn) as cur:
        cur.execute(
            f"""
            INSERT INTO job_queue (kind, payload, user_id, run_id, priority,
                                   max_attempts, available_at)
            VALUES (%s, %s, %s, %s, %s, %s, now() + (%s || ' seconds')::interval)
            RETURNING {_COLS};
            """,
            (kind, json.dumps(payload), user_id, run_id, priority, max_attempts,
             str(delay_s)),
        )
        row = _row(cur)
    conn.commit()
    return row


# ── el dequeue: un SQL por dialecto (ver la cabecera) ──────────────────────────

_SET_CLAIM = """
                status       = 'running',
                locked_by    = %s,
                locked_at    = now(),
                heartbeat_at = now(),
                started_at   = COALESCE(started_at, now()),
                attempts     = attempts + 1"""

#: Postgres: intacto desde T8-infra. El lock pesimista lo pone la base.
_SQL_CLAIM_CONTROL = f"""
            UPDATE job_queue SET {_SET_CLAIM}
            WHERE id = (
                SELECT id FROM job_queue
                WHERE status = 'queued' AND available_at <= now()
                ORDER BY priority DESC, available_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING {_COLS};
            """

#: SQLite: el guard `AND status='queued'` ocupa el lugar del lock de fila.
_SQL_CLAIM_CLIENTE = f"""
            UPDATE job_queue SET {_SET_CLAIM}
            WHERE id = (
                SELECT id FROM job_queue
                WHERE status = 'queued' AND available_at <= now()
                ORDER BY priority DESC, available_at ASC
                LIMIT 1
            )
              AND status = 'queued'
            RETURNING {_COLS};
            """


def _claim(conn, sql: str, worker_id: str) -> Optional[dict]:
    """Un intento de claim. Commitea SIEMPRE — incluso si matcheó 0 filas — para no
    dejar abierta una transacción de escritura que serialice a los otros workers."""
    with _cursor_dict(conn) as cur:
        cur.execute(sql, (worker_id,))
        row = _row(cur)
    conn.commit()
    return row


def _hay_candidato(conn) -> bool:
    """¿Queda algún job reclamable? Distingue las dos causas de un claim de 0 filas:
    cola vacía (devolver None y dormir) vs. carrera perdida (reintentar)."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM job_queue WHERE status = 'queued' "
                    "AND available_at <= now() LIMIT 1;")
        return cur.fetchone() is not None


def claim_one(conn, worker_id: str) -> Optional[dict]:
    """Toma EL siguiente job disponible de forma atómica. Lo marca 'running', sube
    attempts, fija lock + heartbeat. Devuelve el job o None si no hay trabajo.

    Postgres lo resuelve en una sentencia (`SKIP LOCKED`). SQLite reintenta: un claim
    de 0 filas puede ser "no hay nada" o "otro worker ganó", y la diferencia importa
    —devolver None con la cola llena haría dormir al worker un poll entero. Ver la
    cabecera del módulo para por qué son dos SQL distintos y qué se midió de cada uno.
    """
    if not _es_cliente():
        return _claim(conn, _SQL_CLAIM_CONTROL, worker_id)

    for _ in range(_CLAIM_REINTENTOS):
        row = _claim(conn, _SQL_CLAIM_CLIENTE, worker_id)
        if row is not None:
            return row
        if not _hay_candidato(conn):
            return None
    return None


def heartbeat(conn, job_id: str, worker_id: str) -> bool:
    """Marca vivo el job (lo llama el worker periódicamente durante la ejecución)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE job_queue SET heartbeat_at = now() "
            "WHERE id = %s AND locked_by = %s AND status = 'running';",
            (job_id, worker_id),
        )
        ok = cur.rowcount > 0
    conn.commit()
    return ok


def mark_done(conn, job_id: str, result: Any, *, run_id: Optional[str] = None) -> None:
    """Cierra un job OK. Liga el run_id producido (si lo hubo)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE job_queue SET status='done', result=%s, finished_at=now(), "
            "run_id=COALESCE(%s, run_id), locked_by=NULL "
            "WHERE id=%s;",
            (json.dumps(result), run_id, job_id),
        )
    conn.commit()


def mark_error(
    conn, job_id: str, error: str, *, retry_backoff_s: float = 30.0
) -> str:
    """Falla un job. Si le quedan intentos → vuelve a 'queued' con backoff (retry).
    Si los agotó → queda 'error' (terminal). Devuelve el estado resultante."""
    with _cursor_dict(conn) as cur:
        cur.execute("SELECT attempts, max_attempts FROM job_queue WHERE id=%s;", (job_id,))
        row = _row(cur)
        if row is None:
            conn.commit()
            return "missing"
        will_retry = row["attempts"] < row["max_attempts"]
        if will_retry:
            cur.execute(
                "UPDATE job_queue SET status='queued', locked_by=NULL, locked_at=NULL, "
                "heartbeat_at=NULL, error=%s, "
                "available_at = now() + (%s || ' seconds')::interval "
                "WHERE id=%s;",
                (error[:4000], str(retry_backoff_s), job_id),
            )
            new_status = "queued"
        else:
            cur.execute(
                "UPDATE job_queue SET status='error', error=%s, finished_at=now(), "
                "locked_by=NULL WHERE id=%s;",
                (error[:4000], job_id),
            )
            new_status = "error"
    conn.commit()
    return new_status


def reclaim_stale(conn, older_than_s: float = 120.0) -> dict:
    """Reclama jobs 'running' cuyo worker murió (heartbeat más viejo que el umbral, o
    nunca latió). Con intentos restantes → 'queued'; agotados → 'error'. Lo llama el
    boot (recupera lo que estaba corriendo cuando el proceso cayó) y el reaper periódico.
    Devuelve {requeued, failed}."""
    with conn.cursor() as cur:
        # con intentos restantes → re-encolar
        cur.execute(
            """
            UPDATE job_queue SET status='queued', locked_by=NULL, locked_at=NULL,
                                 heartbeat_at=NULL, available_at=now()
            WHERE status='running'
              AND attempts < max_attempts
              AND COALESCE(heartbeat_at, locked_at, started_at) < now() - (%s || ' seconds')::interval;
            """,
            (str(older_than_s),),
        )
        requeued = cur.rowcount
        # agotados → terminal
        cur.execute(
            """
            UPDATE job_queue SET status='error', finished_at=now(), locked_by=NULL,
                error = COALESCE(error, 'worker murió y se agotaron los intentos (reclaim)')
            WHERE status='running'
              AND attempts >= max_attempts
              AND COALESCE(heartbeat_at, locked_at, started_at) < now() - (%s || ' seconds')::interval;
            """,
            (str(older_than_s),),
        )
        failed = cur.rowcount
    conn.commit()
    return {"requeued": requeued, "failed": failed}


# ── lectura ──────────────────────────────────────────────────────────────────

def get(conn, job_id: str) -> Optional[dict]:
    with _cursor_dict(conn) as cur:
        cur.execute(f"SELECT {_COLS} FROM job_queue WHERE id=%s;", (job_id,))
        return _row(cur)


def list_for_user(conn, user_id: str, limit: int = 50) -> list[dict]:
    with _cursor_dict(conn) as cur:
        cur.execute(
            f"SELECT {_COLS} FROM job_queue WHERE user_id=%s "
            f"ORDER BY created_at DESC LIMIT %s;",
            (user_id, limit),
        )
        return [_decodificar(dict(r)) for r in cur.fetchall()]


def stats(conn) -> dict:
    """Conteo por estado — para health/deep y para detectar cola creciente (alerting)."""
    with conn.cursor() as cur:
        cur.execute("SELECT status, count(*) FROM job_queue GROUP BY status;")
        out = {"queued": 0, "running": 0, "done": 0, "error": 0}
        for status, n in cur.fetchall():
            out[status] = n
    return out
