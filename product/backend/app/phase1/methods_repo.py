"""
methods_repo.py — capa de datos de la pieza MÉTODO (workflows · ORDEN_METODO.md).

Dos tablas (migración 0011):
  · methods      — la BIBLIOTECA de la cuenta: el OBJETO Method (steps planos con
    campo `phase` + `phases[]` aditivo del editor). El vínculo método↔agente NO
    vive acá: es belt.method_refs[] dentro del recipe (referencia, no copia).
  · method_runs  — estado externo del arnés por run + control-plane durable
    (pause/resume/remedy/checkpoint) que el loop pollea entre turnos.

Contrato del objeto Method = el que el front round-trippea (metodo.api.js
normalizeMethod): campos desconocidos se PRESERVAN; steps normalizados con
defaults {id, text, phase, checkpoint, executor, evidence_hint, timeout, retries}.
Anti-IDOR: todo el SQL scoped por user_id (ajeno == inexistente).
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from typing import Any, Optional

from app.phase1.repo import _row_to_dict

# Caps de SANIDAD (iguales para todos los tiers — crear métodos es ilimitado por
# diseño §7; esto solo frena specs basura/abuso, no limita el plan).
MAX_STEPS = 80
MAX_SPEC_BYTES = 65536
MAX_NAMED_PHASES = 6          # ORDEN §2: fases 4-6 máx — el server avisa, el editor fusiona

# Claves que el SERVER es dueño y no se persisten dentro de spec (el front las
# round-trippea de vuelta en el PUT porque normalizeMethod preserva extras).
_SERVER_KEYS = ("id", "user_id", "owner_id", "bytes", "run_count",
                "last_run_at", "created_at", "updated_at")

_STEP_DEFAULTS = {
    "text": "", "phase": "", "checkpoint": False, "executor": None,
    "evidence_hint": None, "timeout": None, "retries": 3,
}


def normalize_requires(raw: Any) -> Optional[list[str]]:
    """Lista de capacidades tal como la publica 5a.

    None se conserva para poder detectar un método legado y pasarlo UNA vez por
    el extractor. Convertir None a [] acá borraría esa diferencia y fabricaría
    un método «sin requisitos».
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        # Una forma inválida no puede mutar silenciosamente a «no requiere nada»:
        # None hace que la validación/backfill falle o clasifique pendiente.
        return None
    out: list[str] = []
    for value in raw:
        capability = str(value or "").strip()
        if capability and capability not in out:
            out.append(capability)
    return out


def _new_step_id() -> str:
    return "s-" + uuid.uuid4().hex[:8]


def normalize_step(raw: Any) -> dict[str, Any]:
    """Espejo server-side de newStep/normalizeMethod del front: defaults + coerción
    de tipos, campos extra PRESERVADOS."""
    s = dict(raw) if isinstance(raw, dict) else {}
    out = dict(s)  # extras primero; los conocidos se pisan normalizados
    out["id"] = str(s.get("id") or _new_step_id())
    out["text"] = str(s.get("text") or "").strip()
    out["phase"] = str(s.get("phase") or "").strip()
    out["checkpoint"] = bool(s.get("checkpoint"))
    ex = s.get("executor")
    out["executor"] = (str(ex).strip() or None) if isinstance(ex, str) else None
    eh = s.get("evidence_hint")
    out["evidence_hint"] = (str(eh).strip() or None) if isinstance(eh, str) else None
    t = s.get("timeout")
    out["timeout"] = t if isinstance(t, (int, float)) and not isinstance(t, bool) else None
    r = s.get("retries")
    out["retries"] = int(r) if isinstance(r, (int, float)) and not isinstance(r, bool) else 3
    return out


def normalize_method(raw: Any) -> dict[str, Any]:
    """Method normalizado: name/steps coercionados, TODO campo extra preservado
    (id, phases, equipped_by, lo que el front agregue)."""
    m = dict(raw) if isinstance(raw, dict) else {}
    out = dict(m)
    out["name"] = str(m.get("name") or "").strip()
    steps = m.get("steps")
    out["steps"] = [normalize_step(s) for s in steps] if isinstance(steps, list) else []
    if "requires" in m:
        out["requires"] = normalize_requires(m.get("requires"))
    if "phases" in m and not isinstance(m.get("phases"), list):
        out["phases"] = []
    return out


def named_phases(method: dict) -> list[str]:
    """Fases nombradas en orden de aparición (steps primero, phases[] aditivo después)."""
    seen: list[str] = []
    for s in method.get("steps") or []:
        p = (s.get("phase") or "").strip()
        if p and p not in seen:
            seen.append(p)
    for p in method.get("phases") or []:
        p = str(p or "").strip()
        if p and p not in seen:
            seen.append(p)
    return seen


def validate_method(method: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings) — espejo de validateMethod del front + caps de sanidad.
    errors ⇒ 422; warnings viajan informativos (el editor ya fusiona/avisa)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not (method.get("name") or "").strip():
        errors.append("el método necesita un nombre")
    # La ausencia identifica un registro legado: el borde HTTP lo pasa UNA vez por el
    # extractor y lo persiste. El repo no puede hacerlo (no conoce cerebro ni sesión) y
    # debe seguir pudiendo LEER esos registros para que el backfill sea posible.
    if "requires" in method and not isinstance(method.get("requires"), list):
        errors.append("requires debe ser una lista")
    elif "requires" in method and any(
            not isinstance(c, str) or not c.strip() for c in method.get("requires") or []):
        errors.append("requires contiene una capacidad vacía o inválida")
    # NUL/caracteres de control: psycopg2 revienta con \x00 en un parámetro text →
    # un input validator-clean pero storage-hostil no debe llegar a la DB.
    if _has_control_chars(method.get("name")) or any(
            _has_control_chars(s.get("text")) or _has_control_chars(s.get("phase"))
            for s in (method.get("steps") or []) if isinstance(s, dict)):
        errors.append("el método contiene caracteres de control no permitidos")
    steps = method.get("steps")
    if not isinstance(steps, list):
        errors.append("steps debe ser una lista")
        steps = []
    if len(steps) > MAX_STEPS:
        errors.append(f"demasiados pasos ({len(steps)} > {MAX_STEPS})")
    for i, s in enumerate(steps):
        if not (s.get("text") or "").strip():
            errors.append(f"el paso {i + 1} está vacío")
        t = s.get("timeout")
        if t is not None and (not isinstance(t, (int, float)) or isinstance(t, bool) or t <= 0):
            errors.append(f"timeout inválido en el paso {i + 1}")
        r = s.get("retries")
        if not isinstance(r, int) or isinstance(r, bool) or r < 0:
            errors.append(f"retries inválido en el paso {i + 1}")
    if len(json.dumps(method, ensure_ascii=False).encode("utf-8")) > MAX_SPEC_BYTES:
        errors.append(f"el método excede el tamaño máximo ({MAX_SPEC_BYTES} bytes)")
    ph = named_phases(method)
    if len(ph) > MAX_NAMED_PHASES:
        warnings.append(f"{len(ph)} fases nombradas (recomendado ≤ {MAX_NAMED_PHASES})")
    return errors, warnings


def steps_by_id(method: dict) -> dict[str, dict]:
    return {s.get("id"): s for s in (method.get("steps") or []) if s.get("id")}


def _has_control_chars(s: Any) -> bool:
    """NUL o caracteres de control (excepto \\t\\n\\r) — hostiles al storage."""
    if not isinstance(s, str):
        return False
    return any(ord(c) < 0x20 and c not in "\t\n\r" for c in s)


# ── match léxico DETERMINISTA (la propuesta contextual de la Sala exige <1.2s:
#    cero LLM en el camino caliente — fail-open honesto {match: null}) ──────────

_TOKEN_RE = re.compile(r"[a-z0-9áéíóúüñ]{4,}")
_STOP = frozenset((
    "para", "como", "este", "esta", "estos", "estas", "sobre", "donde", "cuando",
    "quiero", "necesito", "hacer", "haceme", "hacme", "dame", "decime", "porfa",
    "favor", "puede", "podes", "podrias", "with", "this", "that", "from", "have",
    "want", "need", "make", "please", "could", "would", "into", "about",
))


def _tokens(text: str) -> set[str]:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {w for w in _TOKEN_RE.findall(t) if w not in _STOP}


def match_method(methods: list[dict], prompt: str) -> Optional[dict]:
    """El mejor método (de los EQUIPADOS del puppet) que 'hace eco' en el prompt.
    Léxico puro: tokens del prompt vs nombre (peso 3) + fases (2) + pasos (1).
    Umbral conservador (score ≥ 3): mejor cero card que una card ruidosa.
    Devuelve el dict del método o None."""
    ptoks = _tokens(prompt)
    if not ptoks:
        return None
    best, best_score = None, 0
    for m in methods:
        score = 3 * len(ptoks & _tokens(m.get("name") or ""))
        score += 2 * len(ptoks & _tokens(" ".join(named_phases(m))))
        step_toks: set[str] = set()
        for s in m.get("steps") or []:
            step_toks |= _tokens(s.get("text") or "")
        score += len(ptoks & step_toks)
        if score > best_score:
            best, best_score = m, score
    return best if best_score >= 3 else None


# ── biblioteca (tabla methods) ────────────────────────────────────────────────

def _spec_for_storage(method: dict) -> tuple[dict, int]:
    spec = {k: v for k, v in method.items() if k not in _SERVER_KEYS}
    return spec, len(json.dumps(spec, ensure_ascii=False).encode("utf-8"))


def _row_to_method(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    spec = row.get("spec") or {}
    out = dict(spec if isinstance(spec, dict) else {})
    out["id"] = str(row["id"])
    out["name"] = row.get("name") or out.get("name") or ""
    out["run_count"] = int(row.get("run_count") or 0)
    out["last_run_at"] = row.get("last_run_at")
    out["created_at"] = row.get("created_at")
    out["updated_at"] = row.get("updated_at")
    return out


def list_methods(conn, user_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM methods WHERE user_id = %s ORDER BY created_at DESC",
                    (user_id,))
        return [_row_to_method(_row_to_dict(cur, r)) for r in cur.fetchall()]


def get_method(conn, method_id: str, user_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM methods WHERE id = %s AND user_id = %s",
                    (method_id, user_id))
        return _row_to_method(_row_to_dict(cur, cur.fetchone()))


def create_method(conn, *, user_id: str, method: dict, commit: bool = True) -> dict[str, Any]:
    spec, nbytes = _spec_for_storage(method)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO methods (user_id, name, spec, bytes) "
            "VALUES (%s,%s,%s,%s) RETURNING *",
            (user_id, method.get("name") or "", json.dumps(spec, ensure_ascii=False), nbytes),
        )
        row = _row_to_dict(cur, cur.fetchone())
    if commit:   # commit=False → import atómico (métodos + puppet en UNA txn)
        conn.commit()
    return _row_to_method(row)


def update_method(conn, method_id: str, user_id: str, method: dict) -> Optional[dict[str, Any]]:
    spec, nbytes = _spec_for_storage(method)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE methods SET name = %s, spec = %s, bytes = %s, updated_at = now() "
            "WHERE id = %s AND user_id = %s RETURNING *",
            (method.get("name") or "", json.dumps(spec, ensure_ascii=False), nbytes,
             method_id, user_id),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return _row_to_method(row)


def delete_method(conn, method_id: str, user_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM methods WHERE id = %s AND user_id = %s",
                    (method_id, user_id))
        n = cur.rowcount
    conn.commit()
    return n > 0


def touch_method_run(conn, method_id: str, user_id: Optional[str]) -> None:
    """Maduración local básica: el arnés marca que el método corrió (no viaja en exports)."""
    with conn.cursor() as cur:
        if user_id:
            cur.execute("UPDATE methods SET run_count = run_count + 1, last_run_at = now() "
                        "WHERE id = %s AND user_id = %s", (method_id, user_id))
        else:
            cur.execute("UPDATE methods SET run_count = run_count + 1, last_run_at = now() "
                        "WHERE id = %s", (method_id,))
    conn.commit()


# ── estado del arnés (tabla method_runs) ─────────────────────────────────────
#
# state = {spec, current, step_status{id→pending|active|done|skipped|failed},
#          attempts{id→int}, skipped[{step_id, reason, turn, by}], evidence{id→[...]},
#          adjust, free_notes[]}
# control = {pause: bool, resume_spec: Method, remedy: {step_id, action, minutes, text},
#            checkpoint: {approval_id, ok}}  — lo escriben los endpoints, lo consume
#            (y limpia) el arnés entre turnos.

def create_method_run(conn, *, run_id: str, method_id: Optional[str], user_id: Optional[str],
                      puppet_id: Optional[str], space_id: Optional[str],
                      state: dict, status: str = "active") -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO method_runs (run_id, method_id, user_id, puppet_id, space_id, status, state) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (run_id) DO UPDATE SET method_id = EXCLUDED.method_id, "
            "  state = EXCLUDED.state, status = EXCLUDED.status, updated_at = now() "
            "RETURNING *",
            (run_id, method_id, user_id, puppet_id, space_id, status,
             json.dumps(state, ensure_ascii=False)),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def get_method_run(conn, run_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM method_runs WHERE run_id = %s", (run_id,))
        return _row_to_dict(cur, cur.fetchone())


def update_method_run(conn, run_id: str, *, state: Optional[dict] = None,
                      status: Optional[str] = None,
                      control_merge: Optional[dict] = None,
                      control_clear: Optional[list[str]] = None) -> bool:
    # [Casa 2 · 2.4] El merge/clear de `control` NO es portable: Postgres lo hace con
    # `||` (merge shallow, la derecha gana) y `- key` (borra la clave), y en SQLite esos
    # operadores EXISTEN pero significan otra cosa —`||` concatena strings, `- key` resta—
    # así que el traductor los deja pasar y corromperían `control` EN SILENCIO (medido:
    # `'{"a":1}' || '{"b":2}'` = `'{"a":1}{"b":2}'`, JSON inválido; `... - 'a'` = `0`).
    # `json_patch` tampoco sirve (merge recursivo + borra los null → diverge justo en
    # `{"remedy": {...}}`). Por eso el cliente computa el merge en Python, que ES el
    # shallow-merge de PG, dentro de BEGIN IMMEDIATE para que sea atómico igual que el
    # UPDATE único de PG.
    if (control_merge or control_clear) and _es_cliente():
        return _update_method_run_control_sqlite(
            conn, run_id, state=state, status=status,
            control_merge=control_merge, control_clear=control_clear)
    sets, params = [], []
    if state is not None:
        sets.append("state = %s")
        params.append(json.dumps(state, ensure_ascii=False))
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    # merge + clears van en UNA sola expresión (Postgres rechaza asignar la
    # misma columna dos veces en un UPDATE)
    control_expr = None
    if control_merge:
        control_expr = "COALESCE(control, '{}'::jsonb) || %s::jsonb"
        params.append(json.dumps(control_merge, ensure_ascii=False))
    for key in control_clear or []:
        control_expr = (control_expr or "COALESCE(control, '{}'::jsonb)") + " - %s"
        params.append(key)
    if control_expr:
        sets.append(f"control = {control_expr}")
    if not sets:
        return False
    sets.append("updated_at = now()")
    params.append(run_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE method_runs SET {', '.join(sets)} WHERE run_id = %s",
                    tuple(params))
        n = cur.rowcount
    conn.commit()
    return n > 0


def _update_method_run_control_sqlite(conn, run_id, *, state, status,
                                      control_merge, control_clear) -> bool:
    """El merge/clear de `control` para el cliente (ver update_method_run). `dict.update`
    replica el `||` shallow de PG (la derecha gana) y `pop` el `- key`. Read-merge-write
    atómico bajo BEGIN IMMEDIATE (mismo patrón que _pop_control_sqlite, 2.3): el lock de
    escritura se toma ANTES del SELECT, así dos merges concurrentes sobre el mismo run se
    serializan en vez de pisarse."""
    conn.raw.execute("BEGIN IMMEDIATE")
    try:
        ctl = read_control(conn, run_id)         # SELECT dentro del write lock
        if control_merge:
            ctl.update(control_merge)
        for key in control_clear or []:
            ctl.pop(key, None)
        sets, params = [], []
        if state is not None:
            sets.append("state = %s")
            params.append(json.dumps(state, ensure_ascii=False))
        if status is not None:
            sets.append("status = %s")
            params.append(status)
        sets.append("control = %s")
        params.append(json.dumps(ctl, ensure_ascii=False))
        sets.append("updated_at = now()")
        params.append(run_id)
        with conn.cursor() as cur:
            cur.execute(f"UPDATE method_runs SET {', '.join(sets)} WHERE run_id = %s",
                        tuple(params))
            n = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return n > 0


def _es_cliente() -> bool:
    """El rol, vía la capa canónica (repo ya cachea el módulo de db)."""
    from app.phase1.repo import _dbmod
    return _dbmod().es_cliente()


def _control_dict(v) -> dict[str, Any]:
    """`method_runs.control` → dict. JSONB en Postgres (psycopg2 ya lo decodifica),
    TEXT en SQLite (vuelve como str). Un dict pasa de largo: el plano de control no
    cambia de comportamiento."""
    if isinstance(v, str):
        v = json.loads(v or "{}")
    return v or {}


def read_control(conn, run_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT control FROM method_runs WHERE run_id = %s", (run_id,))
        row = cur.fetchone()
    return _control_dict(row[0]) if row else {}


def _pop_control_sqlite(conn, run_id: str) -> dict[str, Any]:
    """El equivalente SQLite del CTE con FOR UPDATE. [Casa 2 · Fase 2 · 2.3]

    SQLite no tiene `FOR UPDATE` (`platform/db/dialect.py` lo rechaza ruidoso) y su
    `RETURNING` devuelve los valores NUEVOS, así que no hay forma de leer el control
    viejo y limpiarlo en una sola sentencia. Van dos, dentro de `BEGIN IMMEDIATE`:
    eso toma el lock de escritura ANTES del SELECT, que es exactamente lo que compra
    el `FOR UPDATE` de Postgres.

    Sin el IMMEDIATE la transacción sería DIFERIDA: el SELECT abriría un snapshot de
    lectura y el UPDATE tendría que promoverlo, que es el caso que da
    `SQLITE_BUSY_SNAPSHOT` y que `busy_timeout` NO cubre (medido en 2.3). O sea: sin
    él no se pierde el remedy en silencio, se rompe con `database is locked` — pero
    romper tampoco es la idea, y el lock temprano evita las dos cosas.

    El SQL sigue escrito en Postgres y lo traduce la capa de dialecto: `now()` y
    `::jsonb` no se hardcodean acá (una decisión, un lugar).
    """
    conn.raw.execute("BEGIN IMMEDIATE")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT control FROM method_runs WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
            cur.execute("UPDATE method_runs SET control = '{}'::jsonb, "
                        "updated_at = now() WHERE run_id = %s", (run_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _control_dict(row[0]) if row else {}


def pop_control(conn, run_id: str) -> dict[str, Any]:
    """Lee Y limpia el control-plane atómicamente (cierra la carrera read→clear: un
    segundo remedy que llega entre lectura y limpieza no se pierde — o entra en este
    pop, o queda para el siguiente).

    Postgres: CTE que captura el control VIEJO con FOR UPDATE y lo limpia en la misma
    sentencia (el RETURNING del UPDATE da el valor nuevo, así que el viejo se lee en
    la CTE antes del SET). SQLite: ver `_pop_control_sqlite`."""
    if _es_cliente():
        return _pop_control_sqlite(conn, run_id)
    with conn.cursor() as cur:
        cur.execute(
            "WITH old AS (SELECT control AS c FROM method_runs WHERE run_id = %s FOR UPDATE) "
            "UPDATE method_runs SET control = '{}'::jsonb, updated_at = now() "
            "FROM old WHERE method_runs.run_id = %s "
            "RETURNING old.c",
            (run_id, run_id))
        row = cur.fetchone()
    conn.commit()
    return _control_dict(row[0]) if (row and row[0]) else {}


def claim_continuation(conn, run_id: str, resumable: list[str]) -> bool:
    """Claim ATÓMICO para reanudar un run cortado: sella 'abandoned' SOLO si el
    status sigue en `resumable`. El ganador reanuda; un segundo request concurrente
    (doble-click en Reanudar) ve 0 filas → 409. Cierra la doble-continuación."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE method_runs SET status = 'abandoned', control = '{}'::jsonb, "
            "updated_at = now() WHERE run_id = %s AND status = ANY(%s) RETURNING run_id",
            (run_id, list(resumable)))
        won = cur.fetchone() is not None
    conn.commit()
    return won
