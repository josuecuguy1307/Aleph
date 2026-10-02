"""multiagente_repo.py — el ENLACE POR CAMPO de los saltos de una cadena.

Spec: `docs/multiagente.md` §4.

── POR QUÉ ESTO NO VIVE EN repo.py ──────────────────────────────────────────────
Porque el invariante del multiagente es que **no toca el ciclo de vida del run**. Cada
salto nace por `repo.create_run`, late en `run_lifecycle._VIVOS` y muere por
`repo.finish_run`, exactamente igual que cualquier otro run. Lo único que este módulo hace
es un `UPDATE` de cuatro columnas NULABLES **después** de que el run cerró.

Meterlo en `repo.create_run` habría significado cambiar el INSERT del choke point del que
cuelga TODO run del producto — para un dato que ni siquiera se conoce en el momento del
INSERT (la latencia se mide cuando el salto TERMINA). Un módulo aparte deja el choke point
intacto y hace evidente, al leer el árbol, que el multiagente es una capa ENCIMA del run y
no una variante de él.

── DIALECTOS ────────────────────────────────────────────────────────────────────
Se escribe SQL de Postgres con `%s`, igual que `repo.py`: en el cliente, `sqlite_db`
traduce al vuelo (`dialect.traducir`). Un solo texto, las dos bases.
"""

from __future__ import annotations

from typing import Any, Optional


def _row_to_dict(cur, row) -> Optional[dict[str, Any]]:
    """Espejo de `repo._row_to_dict` (UUID/timestamp → str para serializar sin sorpresas).
    Se replica en vez de importarse para no acoplar este módulo al orden de imports de
    repo.py, que es el archivo más disputado del árbol."""
    if row is None:
        return None
    out = dict(zip([d[0] for d in cur.description], row))
    for k, v in list(out.items()):
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif v is not None and type(v).__name__ == "UUID":
            out[k] = str(v)
    return out


def marcar_padre(conn, run_id: str, modo: str) -> None:
    """Sella el CONTRATO DE EJECUCIÓN sobre la fila del run padre (el globo).

    `runs.modo` es lo que hace identificable a un padre sin salir a contar hijos. Un run
    normal lo deja en NULL, que es lo que valía antes de que la columna existiera."""
    with conn.cursor() as cur:
        cur.execute("UPDATE runs SET modo = %s WHERE id = %s", (modo, run_id))
    conn.commit()


def enlazar_salto(conn, run_id: str, *, parent_run_id: str, hop_index: int,
                  hop_latency_ms: int) -> None:
    """Estampa el enlace del salto SOBRE SU FILA YA CERRADA.

    Corre DESPUÉS de que el run del salto terminó — por eso puede llevar la latencia
    MEDIDA, que no existe hasta que el salto termina. No cambia `status` ni
    `finished_at`: el estado terminal lo puso `finish_run` y acá no se lo discute."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE runs SET parent_run_id = %s, hop_index = %s, hop_latency_ms = %s "
            "WHERE id = %s",
            (parent_run_id, int(hop_index), int(hop_latency_ms), run_id),
        )
    conn.commit()


def saltos_de(conn, parent_run_id: str) -> list[dict]:
    """Los saltos de un padre, EN ORDEN. Es la lectura que la fase 2 va a necesitar para
    rehidratar el transcript de una cadena sin re-correrla."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, intent, status, hop_index, hop_latency_ms, started_at, finished_at "
            "FROM runs WHERE parent_run_id = %s ORDER BY hop_index",
            (parent_run_id,),
        )
        return [_row_to_dict(cur, r) for r in cur.fetchall()]


def run_padre(conn, run_id: str) -> Optional[dict]:
    """La fila del padre + sus saltos. None si no existe o si no es un padre
    (`modo IS NULL` = run normal: no hay cadena que contar)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, intent, status, modo, started_at, finished_at FROM runs "
            "WHERE id = %s AND modo IS NOT NULL", (run_id,))
        fila = _row_to_dict(cur, cur.fetchone())
    if fila is None:
        return None
    fila["saltos"] = saltos_de(conn, run_id)
    return fila


__all__ = ["marcar_padre", "enlazar_salto", "saltos_de", "run_padre"]
