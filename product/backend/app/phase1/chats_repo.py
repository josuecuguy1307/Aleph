"""
chats_repo.py — capa de datos de los CHATS de la Sala (Ola UX-UNIVERSAL · A1/A2/A3).

Un chat = una conversación persistente con UNA composición (puppet) o con el agente
inline (puppet_id NULL). Sus mensajes son los turnos REALES: texto del usuario y
respuesta del agente. Los turnos-obra guardan además space_id (→ events.jsonl del run,
de donde la Sala re-proyecta narrativa/evidencia — acá no se duplica nada) y run_id.

REGLA ARTIFACTS-POR-HANDLE: content es SIEMPRE texto (prompt/answer). Bytes de
artifacts jamás entran a esta tabla ni al bloque de historial que va al cerebro.

ANTI-IDOR: todas las lecturas/escrituras van scoped por user_id (el router resuelve el
owner de la SESIÓN — mismo patrón _mem_gate de A3 — y este módulo filtra por él en SQL;
un chat ajeno es indistinguible de uno inexistente).

Mismo estilo que repo.py: conexión por parámetro, commit explícito, _row_to_dict.
"""

from __future__ import annotations

from typing import Any, Optional

from app.phase1.repo import _row_to_dict

# Presupuesto del bloque de historial que se antepone al prompt del cerebro.
# Acotado para que la conversación previa NUNCA domine el contexto del run
# (mismo espíritu que el cap de memoria A3). Se llena de más-reciente hacia atrás.
HISTORY_BUDGET_CHARS = 6000
# Un mensaje individual gigante no puede comerse el presupuesto entero.
HISTORY_PER_MSG_CHARS = 1500


# ── CRUD de chats ────────────────────────────────────────────────────────────────

def create_chat(conn, *, user_id: str, puppet_id: Optional[str] = None,
                title: str = "") -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO chats (user_id, puppet_id, title) VALUES (%s,%s,%s) RETURNING *",
            (user_id, puppet_id, title),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def get_chat_owned(conn, chat_id: str, user_id: str) -> Optional[dict[str, Any]]:
    """El chat SOLO si pertenece a user_id (anti-IDOR en el WHERE: ajeno == inexistente)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM chats WHERE id = %s AND user_id = %s",
            (chat_id, user_id),
        )
        return _row_to_dict(cur, cur.fetchone())


def list_chats(conn, user_id: str, *, puppet_id: Optional[str] = None,
               puppet_scope: str = "all", limit: int = 100,
               ws_por_chat: Optional[dict[str, str]] = None,
               workspace_scope: str = "all",
               workspace: Optional[str] = None) -> list[dict[str, Any]]:
    """Lista de chats del usuario, más recientes primero, con preview del último mensaje.

    puppet_scope: 'all' (todos los del usuario) · 'inline' (puppet_id IS NULL) ·
    'puppet' (== puppet_id). El front de la Sala pide el scope de SU composición.

    EL WORKSPACE NO ES UNA COLUMNA, Y POR ESO ENTRA POR PARÁMETRO. La tabla `chats` es
    `id · user_id · puppet_id · title · created_at · updated_at`: no tiene dónde llevar un
    workspace, y agregarle una columna sería un segundo lugar donde vive la verdad. Quién
    es el hilo de qué espacio ya lo sabe `workspaces/memoria.py` —el mapa `(dueño,
    workspace) → chat_id` de la ley técnica 4—, así que el router lo lee y lo baja acá
    invertido (`{chat_id: ws}`). Este módulo sigue siendo SQL puro: no lee archivos.

    workspace_scope: 'all' (todos, como hasta hoy) · 'casa' (los que NO son de ningún
    workspace: los de La Sala) · 'ws' (sólo el hilo de `workspace`).
    """
    mapa = ws_por_chat or {}
    where = "c.user_id = %s"
    params: list[Any] = [user_id]
    if puppet_scope == "inline":
        where += " AND c.puppet_id IS NULL"
    elif puppet_scope == "puppet":
        where += " AND c.puppet_id = %s"
        params.append(puppet_id)
    # El recorte va en el WHERE y no sobre la lista ya traída: filtrar después del LIMIT
    # devolvería menos filas de las pedidas —y con 6 hilos de workspace arriba de todo por
    # ser los más recientes, un `limit=6` podía volver VACÍO.
    if workspace_scope == "casa" and mapa:
        where += " AND c.id NOT IN (" + ",".join(["%s"] * len(mapa)) + ")"
        params.extend(sorted(mapa))
    elif workspace_scope == "ws":
        suyos = sorted(cid for cid, ws in mapa.items() if ws == workspace)
        if not suyos:
            return []                      # un espacio donde todavía no entró nadie
        where += " AND c.id IN (" + ",".join(["%s"] * len(suyos)) + ")"
        params.extend(suyos)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.user_id, c.puppet_id, c.title, c.created_at, c.updated_at, "
            "  (SELECT COUNT(*) FROM chat_messages m WHERE m.chat_id = c.id) AS n_messages, "
            "  (SELECT LEFT(m.content, 140) FROM chat_messages m WHERE m.chat_id = c.id "
            "   ORDER BY m.id DESC LIMIT 1) AS preview "
            f"FROM chats c WHERE {where} "
            "ORDER BY c.updated_at DESC LIMIT %s",
            tuple(params),
        )
        filas = [_row_to_dict(cur, row) for row in cur.fetchall()]
    # El campo viaja SIEMPRE, incluso sin scope: una fila que no dice de qué espacio es
    # obliga a cada pantalla a re-derivarlo, y la que se olvide vuelve a mezclar.
    for f in filas:
        f["workspace"] = mapa.get(str(f.get("id")))
    return filas


def rename_chat(conn, chat_id: str, user_id: str, title: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE chats SET title = %s, updated_at = now() "
            "WHERE id = %s AND user_id = %s",
            (title[:200], chat_id, user_id),
        )
        n = cur.rowcount
    conn.commit()
    return n > 0


def delete_chat(conn, chat_id: str, user_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chats WHERE id = %s AND user_id = %s",
                    (chat_id, user_id))
        n = cur.rowcount
    conn.commit()
    return n > 0


# ── mensajes ─────────────────────────────────────────────────────────────────────

def append_message(conn, *, chat_id: str, role: str, content: str,
                   kind: str = "chat", space_id: Optional[str] = None,
                   run_id: Optional[str] = None,
                   client_turn_id: Optional[str] = None) -> dict[str, Any]:
    """Persiste un turno y toca updated_at del chat. Si es el PRIMER mensaje user y el
    chat no tiene título, el título nace del contenido (como el reel: sin ceremonia).

    Si llega `client_turn_id`, la proyección es idempotente por (chat, turno, rol).
    En un retry, la respuesta del agente se actualiza en sitio para reemplazar una
    respuesta parcial; el mensaje humano original jamás se duplica ni se reescribe."""
    with conn.cursor() as cur:
        inserted = True
        if client_turn_id:
            cur.execute(
                "INSERT INTO chat_messages "
                "(chat_id, client_turn_id, role, kind, content, space_id, run_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING RETURNING *",
                (chat_id, client_turn_id, role, kind, content, space_id, run_id),
            )
            row = _row_to_dict(cur, cur.fetchone())
            inserted = row is not None
            if row is None and role == "agent" and content.strip():
                cur.execute(
                    "UPDATE chat_messages SET kind=%s, content=%s, space_id=%s, run_id=%s "
                    "WHERE chat_id=%s AND client_turn_id=%s AND role='agent' RETURNING *",
                    (kind, content, space_id, run_id, chat_id, client_turn_id),
                )
                row = _row_to_dict(cur, cur.fetchone())
            if row is None:
                cur.execute(
                    "SELECT * FROM chat_messages "
                    "WHERE chat_id=%s AND client_turn_id=%s AND role=%s",
                    (chat_id, client_turn_id, role),
                )
                row = _row_to_dict(cur, cur.fetchone())
        else:
            cur.execute(
                "INSERT INTO chat_messages (chat_id, role, kind, content, space_id, run_id) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                (chat_id, role, kind, content, space_id, run_id),
            )
            row = _row_to_dict(cur, cur.fetchone())
        cur.execute("UPDATE chats SET updated_at = now() WHERE id = %s", (chat_id,))
        if role == "user":
            cur.execute(
                "UPDATE chats SET title = LEFT(%s, 80) "
                "WHERE id = %s AND title = ''",
                (content.strip().splitlines()[0] if content.strip() else "", chat_id),
            )
    conn.commit()
    if row is not None and client_turn_id:
        # Metadato efímero: permite cortar el replay antes del modelo. No es columna
        # ni aparece al listar el transcript.
        row["_idempotent_inserted"] = inserted
    return row


def get_turn_message(conn, *, chat_id: str, client_turn_id: str,
                     role: str) -> Optional[dict[str, Any]]:
    """Devuelve la proyección estable de un turno para responder un replay sin correr."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM chat_messages "
            "WHERE chat_id=%s AND client_turn_id=%s AND role=%s",
            (chat_id, client_turn_id, role),
        )
        return _row_to_dict(cur, cur.fetchone())


def list_messages(conn, chat_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    """Los últimos `limit` mensajes del hilo, en orden cronológico (los más viejos
    se omiten si el hilo excede el límite — el registro completo sigue en la tabla)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM (SELECT * FROM chat_messages WHERE chat_id = %s "
            "ORDER BY id DESC LIMIT %s) sub ORDER BY id ASC",
            (chat_id, limit),
        )
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


# ── búsqueda (A2 — texto simple primero, sin vectores) ──────────────────────────

def search_messages(conn, user_id: str, q: str, *,
                    puppet_id: Optional[str] = None, puppet_scope: str = "all",
                    chat_id: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
    """ILIKE sobre chat_messages.content, SIEMPRE scoped al dueño (JOIN chats por
    user_id). Devuelve snippet centrado en el hit + metadata para saltar al hilo."""
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    where = "c.user_id = %s AND m.content ILIKE %s"
    params: list[Any] = [user_id, like]
    if chat_id:
        where += " AND m.chat_id = %s"
        params.append(chat_id)
    elif puppet_scope == "inline":
        where += " AND c.puppet_id IS NULL"
    elif puppet_scope == "puppet":
        where += " AND c.puppet_id = %s"
        params.append(puppet_id)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT m.id AS message_id, m.chat_id, m.role, m.kind, m.created_at, "
            "c.title AS chat_title, c.puppet_id, "
            "LEFT(m.content, 4000) AS content "
            "FROM chat_messages m JOIN chats c ON c.id = m.chat_id "
            f"WHERE {where} ORDER BY m.id DESC LIMIT %s",
            tuple(params),
        )
        rows = [_row_to_dict(cur, row) for row in cur.fetchall()]
    ql = q.lower()
    for r in rows:
        body = r.pop("content", "") or ""
        pos = body.lower().find(ql)
        start = max(0, pos - 70) if pos >= 0 else 0
        snippet = body[start:start + 160]
        r["snippet"] = ("…" if start > 0 else "") + snippet + ("…" if start + 160 < len(body) else "")
    return rows


# ── rehidratación: el bloque de historial que va al cerebro ─────────────────────

def build_history_block(conn, chat_id: str, *, budget: int = HISTORY_BUDGET_CHARS,
                        exclude_client_turn_id: Optional[str] = None) -> str:
    """Arma el CONTEXTO de la conversación previa para el prompt del cerebro, del
    registro real (chat_messages). Más-reciente-primero hasta agotar el presupuesto,
    luego se re-ordena cronológico. Turnos obra: answer + descriptor del space —
    JAMÁS bytes de artifacts (regla handle). Devuelve '' si no hay turnos previos."""
    with conn.cursor() as cur:
        if exclude_client_turn_id:
            cur.execute(
                "SELECT role, kind, content, space_id FROM chat_messages "
                "WHERE chat_id = %s "
                "AND (client_turn_id IS NULL OR client_turn_id <> %s) "
                "ORDER BY id DESC LIMIT 60",
                (chat_id, exclude_client_turn_id),
            )
        else:
            cur.execute(
                "SELECT role, kind, content, space_id FROM chat_messages "
                "WHERE chat_id = %s ORDER BY id DESC LIMIT 60",
                (chat_id,),
            )
        rows = [_row_to_dict(cur, row) for row in cur.fetchall()]
    if not rows:
        return ""
    picked: list[str] = []
    used = 0
    truncated = False
    for r in rows:  # más reciente → más viejo
        who = "Usuario" if r["role"] == "user" else "Agente"
        body = (r["content"] or "").strip()
        if len(body) > HISTORY_PER_MSG_CHARS:
            body = body[:HISTORY_PER_MSG_CHARS] + " …(recortado)"
        line = f"{who}: {body}"
        if r["kind"] == "obra" and r["role"] == "agent" and r.get("space_id"):
            line += f"\n[obra de ese turno registrada en el espacio {r['space_id']}]"
        if used + len(line) > budget:
            truncated = True
            break
        picked.append(line)
        used += len(line)
    picked.reverse()  # cronológico para el cerebro
    header = "[CONVERSACIÓN PREVIA de este chat — registro real; úsala como contexto]"
    if truncated:
        header += "\n(… turnos más viejos omitidos por espacio …)"
    return header + "\n" + "\n\n".join(picked) + "\n[FIN DE LA CONVERSACIÓN PREVIA]"
