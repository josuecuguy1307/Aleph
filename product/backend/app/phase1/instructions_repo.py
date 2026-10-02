"""
instructions_repo.py — capa de datos de las INSTRUCCIONES PERSISTENTES (Ola UX · B5).

Dos niveles (tabla `instructions`, migración 0009): CUENTA (puppet_id NULL, aplica a
todo) y COMPOSICIÓN (puppet_id = puppets.id). El agente puede PROPONER (source='agent',
enabled=FALSE — INERTE hasta que el humano la active). build_block() arma el bloque que
se inyecta al framing del run — SOLO filas enabled, budget acotado por bytes.

Anti-IDOR: todo va scoped por user_id en el SQL (ajeno == inexistente), igual que
chats_repo/agent_memories. El caller (router/executor) resuelve el owner de la SESIÓN.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.phase1.repo import _row_to_dict, _dbmod


def _es_cliente() -> bool:
    """El rol, vía la capa canónica (repo ya cachea el módulo de db)."""
    return _dbmod().es_cliente()

# Presupuesto del bloque inyectado (mismo espíritu que _A3_PINNED_BUDGET_BYTES): las
# instrucciones no pueden dominar el contexto. Se llena cuenta-primero, luego composición.
INSTR_BUDGET_BYTES = 4096
# Propuestas del agente pendientes por scope (anti-spam): más allá se descartan mudas.
MAX_PENDING_PROPOSALS = 3

# [B5] la PROPUESTA del agente viaja como bloque cercado al final de la respuesta
# (mismo patrón que el plan de B2): se captura server-side, se recorta del answer, y
# nace INERTE (enabled=FALSE) — jamás se auto-activa.
# ORDEN 5 · las CLAVES de propuesta cercada que el sistema elicita (instrucción = autoridad;
# hecho_de_cuenta = contexto sobre la persona, Sistema 2). extract_proposal se parametriza por clave;
# el trailing tolera un bloque HERMANO co-elicitado (no es eco de terceros).
_PROPOSAL_KEYS = ("instruccion_propuesta", "hecho_de_cuenta")


def _proposal_re(key: str) -> "re.Pattern":
    return re.compile(
        r"```(?:json)?\s*(\{[^`]*?\"" + re.escape(key) + r"\"[^`]*?\})\s*```", re.DOTALL)


_PROPOSAL_RE = _proposal_re("instruccion_propuesta")   # back-compat (default de extract_proposal)
# [H1] cuánta prosa se tolera DESPUÉS del bloque para seguir considerándolo "el cierre".
# Un sign-off forzado por una instrucción del dueño ("cerrá siempre con AXOLOTL") es corto;
# el resumen de un documento citado (el vector de eco/laundering) es largo. El umbral separa
# el cierre-legítimo del bloque-en-medio-de-la-respuesta.
# [ORDEN 5 · review adversarial] La medición del trailing es CRUDA (len del texto tras el bloque,
# tal cual): NO se descuentan "bloques hermanos". Una resta de bloques hermanos reabría el
# anti-laundering (un atacante envuelve relleno como bloque hermano, o encadena N bloques, para que
# el trailing mida ~0 y colar/recortar un bloque enterrado en una cita de terceros). El caso legítimo
# de co-elicitación (instrucción + hecho el mismo turno) degrada SEGURO: se captura el que CIERRA la
# respuesta y el anterior se re-propone otro turno — nunca se lava una cita.
_PROPOSAL_TRAILING_TOLERANCE = 40


def list_instructions(conn, user_id: str, *, puppet_id: Optional[str] = None,
                      include_disabled: bool = True) -> list[dict[str, Any]]:
    """Las instrucciones de UN scope (cuenta si puppet_id None, composición si no)."""
    where = "user_id = %s AND puppet_id " + ("IS NULL" if puppet_id is None else "= %s")
    params: list[Any] = [user_id] + ([] if puppet_id is None else [puppet_id])
    if not include_disabled:
        where += " AND enabled"
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM instructions WHERE {where} ORDER BY created_at",
                    tuple(params))
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def add_instruction(conn, *, user_id: str, puppet_id: Optional[str], content: str,
                    source: str = "user", enabled: bool = True,
                    meta: Optional[dict] = None) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO instructions (user_id, puppet_id, source, content, bytes, enabled, meta) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (user_id, puppet_id, source, content, len(content.encode("utf-8")),
             enabled, json.dumps(meta) if meta else None),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def get_instruction_owned(conn, instr_id: str, user_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM instructions WHERE id = %s AND user_id = %s",
                    (instr_id, user_id))
        return _row_to_dict(cur, cur.fetchone())


def update_instruction(conn, instr_id: str, user_id: str, *,
                       content: Optional[str] = None,
                       enabled: Optional[bool] = None,
                       meta_merge: Optional[dict] = None) -> bool:
    # [Casa 2 · 2.4] `meta = COALESCE(meta,'{}'::jsonb) || %s::jsonb` no es portable: en
    # SQLite `||` concatena strings en vez de mergear el JSONB, y el traductor lo deja
    # pasar → corrompería `meta` en silencio (ver methods_repo.update_method_run, mismo
    # caso medido). El cliente computa el merge en Python (dict.update = el `||` shallow de
    # PG) dentro de BEGIN IMMEDIATE.
    if meta_merge and _es_cliente():
        return _update_instruction_meta_sqlite(
            conn, instr_id, user_id, content=content, enabled=enabled, meta_merge=meta_merge)
    sets, params = [], []
    if content is not None:
        sets += ["content = %s", "bytes = %s"]
        params += [content, len(content.encode("utf-8"))]
    if enabled is not None:
        sets.append("enabled = %s")
        params.append(bool(enabled))
    if meta_merge:
        sets.append("meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb")
        params.append(json.dumps(meta_merge))
    if not sets:
        return False
    sets.append("updated_at = now()")
    params += [instr_id, user_id]
    with conn.cursor() as cur:
        cur.execute(f"UPDATE instructions SET {', '.join(sets)} "
                    "WHERE id = %s AND user_id = %s", tuple(params))
        n = cur.rowcount
    conn.commit()
    return n > 0


def _update_instruction_meta_sqlite(conn, instr_id, user_id, *, content, enabled,
                                    meta_merge) -> bool:
    """El merge de `meta` para el cliente (ver update_instruction). Read-merge-write
    atómico bajo BEGIN IMMEDIATE; `dict.update` = el `||` shallow de PG."""
    conn.raw.execute("BEGIN IMMEDIATE")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT meta FROM instructions WHERE id = %s AND user_id = %s",
                        (instr_id, user_id))
            row = cur.fetchone()
        if row is None:
            conn.commit()
            return False
        meta = row[0]
        if isinstance(meta, str):        # por si la columna no cayó en el decode del cursor
            meta = json.loads(meta or "{}")
        meta = dict(meta or {})
        meta.update(meta_merge)
        sets, params = [], []
        if content is not None:
            sets += ["content = %s", "bytes = %s"]
            params += [content, len(content.encode("utf-8"))]
        if enabled is not None:
            sets.append("enabled = %s")
            params.append(bool(enabled))
        sets.append("meta = %s")
        params.append(json.dumps(meta))
        sets.append("updated_at = now()")
        params += [instr_id, user_id]
        with conn.cursor() as cur:
            cur.execute(f"UPDATE instructions SET {', '.join(sets)} "
                        "WHERE id = %s AND user_id = %s", tuple(params))
            n = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return n > 0


def delete_instruction(conn, instr_id: str, user_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM instructions WHERE id = %s AND user_id = %s",
                    (instr_id, user_id))
        n = cur.rowcount
    conn.commit()
    return n > 0


def scope_usage(conn, user_id: str, puppet_id: Optional[str],
                *, billable_only: bool = False) -> dict[str, int]:
    """Uso del scope (entries/bytes). [H2] billable_only EXCLUYE las propuestas del
    agente pendientes (source='agent' AND NOT enabled): son filas inertes que el
    usuario NO escribió → no deben consumir la cuota de su plan ni rebotarle su
    propio POST. El cap del tier se mide sobre lo facturable, no sobre las sugerencias."""
    where = "user_id = %s AND puppet_id " + ("IS NULL" if puppet_id is None else "= %s")
    params: list[Any] = [user_id] + ([] if puppet_id is None else [puppet_id])
    if billable_only:
        where += " AND NOT (source = 'agent' AND NOT enabled)"
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(bytes),0) AS b "
                    f"FROM instructions WHERE {where}", tuple(params))
        row = cur.fetchone()
    return {"entries": int(row[0]), "bytes": int(row[1])}


# ── el bloque que se INYECTA al run (cuenta + composición, solo enabled) ─────────

def build_block(conn, user_id: Optional[str], puppet_id: Optional[str],
                *, budget: int = INSTR_BUDGET_BYTES) -> str:
    """Bloque de instrucciones para el framing del run. Cuenta primero, composición
    después, presupuesto en bytes (truncado honesto). '' si no hay nada activo."""
    if not user_id:
        return ""
    rows = list_instructions(conn, user_id, puppet_id=None, include_disabled=False)
    if puppet_id:
        rows += list_instructions(conn, user_id, puppet_id=puppet_id, include_disabled=False)
    if not rows:
        return ""
    picked, used, truncated = [], 0, False
    for r in rows:
        line = "- " + (r["content"] or "").strip()
        b = len(line.encode("utf-8"))
        if used + b > budget:
            truncated = True
            break
        picked.append(line)
        used += b
    if not picked:
        return ""
    head = ("\n\n[INSTRUCCIONES DEL DUEÑO — seguílas en todas tus respuestas; "
            "NUNCA relajan los candados de seguridad ni los permisos]")
    if truncated:
        head += "\n(… algunas instrucciones no entraron por espacio …)"
    return head + "\n" + "\n".join(picked)


# ── captura de PROPUESTAS del agente (patrón B2: bloque cercado → fila inerte) ───

def extract_proposal(answer, *, key: str = "instruccion_propuesta") -> tuple[Optional[str], Any]:
    """(propuesta, answer_limpio) para la clave `key`. Sin bloque válido → (None, answer).

    [H1] La captura EXIGE que el bloque CIERRE la respuesta — el contrato de la
    elicitación es «cerrá tu respuesta con un bloque» (recipe_assembler _proposal_hint).
    Un bloque en MEDIO del answer suele ser un ECO de contenido de terceros (un doc del
    Conocimiento/RAG, una nota de memoria compartida, un turno previo) que el modelo citó
    a pedido del usuario. Capturarlo ahí (a) lo lava como «propuesta del agente» con
    procedencia falsificable, y (b) lo RECORTA en silencio de la cita que el usuario pidió
    ver. Por eso sólo se captura si:
      · hay EXACTAMENTE UN bloque DE ESA CLAVE (dos o más = ambiguo → nada), y
      · lo que sigue al bloque es corto (≤ _PROPOSAL_TRAILING_TOLERANCE, CRUDO): tolera un
        sign-off forzado por una instrucción del dueño («cerrá siempre con X»), pero rechaza el
        caso del bloque-en-medio con contenido detrás (el vector de eco/laundering). No se
        descuentan «bloques hermanos» del trailing: eso reabría el laundering (ver nota arriba).
    Se recorta SÓLO el bloque de esta clave. Si el mismo turno trae instrucción + hecho, se captura
    el que CIERRA la respuesta y el otro se re-propone después — nunca se lava una cita. Fail-safe:
    en la duda, cero captura y answer intacto."""
    text = answer if isinstance(answer, str) else ""
    if not text or key not in text:
        return None, answer
    rx = _PROPOSAL_RE if key == "instruccion_propuesta" else _proposal_re(key)
    matches = list(rx.finditer(text))
    if len(matches) != 1:
        return None, answer            # 0 = no hay · >1 = ambiguo (posible eco) → nada
    m = matches[0]
    if len(text[m.end():].strip()) > _PROPOSAL_TRAILING_TOLERANCE:
        return None, answer            # contenido sustantivo tras el bloque → NO cierra la respuesta
    try:
        prop = json.loads(m.group(1)).get(key)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None, answer
    prop = str(prop or "").strip()[:500]
    if not prop:
        return None, answer
    clean = (text[:m.start()] + text[m.end():]).strip()   # recorta sólo el bloque de esta clave
    return prop, clean


def add_proposal(conn, *, user_id: str, puppet_id: Optional[str], content: str,
                 run_id: Optional[str]) -> Optional[dict[str, Any]]:
    """Fila INERTE (enabled=FALSE, source='agent'). Cap anti-spam por scope: con
    MAX_PENDING_PROPOSALS pendientes, la nueva se descarta (None).

    [H3] El COUNT y el INSERT corren bajo un advisory-lock TRANSACCIONAL por scope
    (pg_advisory_xact_lock, se suelta al commit): dos runs concurrentes del mismo
    usuario/scope se SERIALIZAN, así el cap de 3 pendientes no se supera por carrera
    TOCTOU (el segundo ya ve la fila commiteada del primero). El lock vive sólo dentro
    de esta función; los helpers del repo hacen commit propio, así que al entrar la
    transacción está limpia y el commit de salida no arrastra escrituras ajenas."""
    scope_key = f"instr_prop:{user_id}:{puppet_id or ''}"
    where = "user_id = %s AND puppet_id " + ("IS NULL" if puppet_id is None else "= %s") + \
            " AND source = 'agent' AND NOT enabled"
    params: list[Any] = [user_id] + ([] if puppet_id is None else [puppet_id])
    insert_sql = (
        "INSERT INTO instructions (user_id, puppet_id, source, content, bytes, enabled, meta) "
        "VALUES (%s,%s,'agent',%s,%s,FALSE,%s) RETURNING *")
    insert_params = (user_id, puppet_id, content, len(content.encode("utf-8")),
                     json.dumps({"run_id": run_id, "proposed": True}))

    # [Casa 2 · 2.4] SQLite no tiene advisory locks —`pg_advisory_xact_lock` NO existe y
    # falla en ejecución (el traductor no lo caza: no está en _NO_TRADUCIBLE)—, pero
    # SQLite serializa escritores: BEGIN IMMEDIATE toma el write lock ANTES del COUNT, lo
    # que da la MISMA exclusión anti-TOCTOU que el advisory lock de PG (dos runs del mismo
    # scope se serializan; el segundo ya ve la fila del primero). Mismo patrón que 2.3.
    if _es_cliente():
        conn.raw.execute("BEGIN IMMEDIATE")
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM instructions WHERE {where}", tuple(params))
                if int(cur.fetchone()[0]) >= MAX_PENDING_PROPOSALS:
                    conn.commit()
                    return None
                cur.execute(insert_sql, insert_params)
                row = _row_to_dict(cur, cur.fetchone())
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return row

    with conn.cursor() as cur:
        # serializa el count+insert entre runs paralelos del mismo scope hasta el commit
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", (scope_key,))
        cur.execute(f"SELECT COUNT(*) FROM instructions WHERE {where}", tuple(params))
        if int(cur.fetchone()[0]) >= MAX_PENDING_PROPOSALS:
            conn.commit()              # cierra la tx (suelta el lock); no hubo escrituras
            return None
        cur.execute(insert_sql, insert_params)
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row
