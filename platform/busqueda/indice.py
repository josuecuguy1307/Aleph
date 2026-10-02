"""indice.py — el índice de búsqueda de la casa. [Convergencia · Superficie 5]

Una consulta, tres grupos: **hilos · mensajes · artefactos**. Es el alcance que se midió
en OpenScience (`backend/cli/src/server/routes/search.ts:44-84`, que devuelve
`{sessions, messages, artifacts}` en una sola respuesta) sobre el motor que ya tiene la
casa: **FTS5 de SQLite**, que viene con la DB y no agrega una sola dependencia.

    from platform.busqueda import indice
    indice.reconstruir(conn, user_id)                 # el índice de ESE dueño
    res = indice.buscar(user_id, "año fiscal")        # {"hilos": [...], "mensajes": [...], ...}

## Lo que este archivo NO indexa, y no es un olvido

- **Los chunks del matter de Legal.** Su aislamiento es por *matter* y es una obligación
  profesional, no una preferencia de producto: su propio código lo declara — *«retrieval is
  naturally scoped to the active matter and never crosses into another matter's privileged
  material»* (`dochaus/tool/search-document.ts:13-15`). Un índice transversal no tiene ese
  scope, así que **no los toca ni con dueño**.
- **El knowledge de Educación** — RAG del oficio, con su propio ciclo de embeddings.
- **Los `sessions.db` y stores internos de los stacks.** Medido: no tienen columna de dueño
  ni path por usuario, así que heredarlos sería heredar el defecto.

Cada workspace conserva su búsqueda intacta. Ésta se suma encima; no reemplaza ninguna.

## El scope es un TOKEN, no un filtro

`buscar()` no arma `… MATCH ? AND user_id = ?`. Arma `MATCH 'alcance:uidXXX AND (…)'`.

La diferencia es la que importa: un `AND` en el `WHERE` es una línea que la próxima ruta
puede olvidar, y el día que se olvide la fuga es silenciosa. Un token obligatorio del MATCH
hace que **una consulta sin dueño no se pueda construir** — `buscar()` levanta antes de
tocar la base. Es la misma doctrina que `_owner_or_401` y que el fail-closed del gate.

Y esto importa más que en una pantalla: en Finanzas la búsqueda es una **tool que el modelo
llama solo** (`session_search`, `repeatable=True`), así que el scope no puede vivir en la UI.

**La inyección se corta en la tokenización, no con una lista negra.** La consulta del
usuario nunca llega cruda al MATCH: se parte en tokens de letras y números y cada uno se
entrecomilla. Un `alcance:uidAJENO` escrito a mano sobrevive como `"alcance" OR "uidAJENO"`
— dos palabras que se buscan en el texto. Los `:` no llegan a existir para FTS5.

## Por qué se RECONSTRUYE y no se mantiene con triggers

Porque medí lo que pasa cuando se mantiene: el índice de Finanzas tiene trigger de INSERT y
de DELETE y **le falta el de UPDATE** (`vibetrading/agent/src/session/search.py:120-135`),
y su tabla es external-content — así que FTS5 no relee la fuente y `snippet()` puede
devolver texto que ya no existe. Y acá el UPDATE **no es hipotético**: `chats_repo.py:132`
reescribe el mensaje del agente cuando un turno se re-emite con el mismo `client_turn_id`,
y `artifact_store.edit_artifact` reescribe el artefacto.

Reconstruir el índice de UN dueño no puede desincronizarse por construcción. El costo está
medido en el acta; el gatillo para cambiar de estrategia, también: el día que reconstruir
pase de ~1 s para un dueño real, esto pide índice incremental con huella por documento.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Optional

# ── el archivo ──────────────────────────────────────────────────────────────────────
# Va aparte de `aleph.db` a propósito: un índice es DERIVADO y reconstruible, y mezclarlo
# con la fuente de verdad convierte un borrado de mantenimiento en un incidente. Además
# crece por otro motivo y a otro ritmo (~1,5× el texto indexado).
_NOMBRE = "indice.db"


def ruta_indice() -> Path:
    import aleph_paths as _ap    # perezoso y sin prefijo: `platform/` va en sys.path, y así
                                 # el módulo se puede medir sin montar el backend entero
    d = _ap.data_root() / "busqueda"
    d.mkdir(parents=True, exist_ok=True)
    return d / _NOMBRE


# ── tokenización ────────────────────────────────────────────────────────────────────
# `[^\W_]` es «carácter de palabra que no sea guion bajo» con re.UNICODE: letras y dígitos
# de CUALQUIER alfabeto, acentos y eñe incluidos. Es la forma que usa el canal léxico de
# Legal (`/[\p{L}\p{N}]/u`, `search-document.ts:83-88`) y la razón por la que su búsqueda
# responde 6 de 6 en castellano donde la de Finanzas respondía 2 de 6.
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

#: Tope de tokens por consulta. Una consulta de mil palabras no es una búsqueda: es una
#: forma barata de hacer trabajar a la base.
_MAX_TOKENS = 24


def _tokens(texto: str) -> list[str]:
    return [t for t in _TOKEN.findall(texto or "") if t][:_MAX_TOKENS]


def _frase(tokens: list[str]) -> str:
    return '"' + " ".join(tokens) + '"'


def _o(tokens: list[str]) -> str:
    return " OR ".join(f'"{t}"' for t in tokens)


# ── los tokens de scope ─────────────────────────────────────────────────────────────
# Se derivan del id, no se escriben a mano, y pasan por el mismo filtro que todo lo demás:
# un `user_id` con un guion (los UUID los tienen) se partiría en varios tokens y el scope
# dejaría de ser una unidad. Por eso se aplana a alfanumérico y se le pone prefijo.

def _tok_scope(prefijo: str, valor: Any) -> str:
    # `str(valor)` a secas NO alcanza, y lo destapó medir el fail-closed con `None`:
    # `str(None)` es `"None"`, que es alfanumérico, así que pasaba el filtro y devolvía un
    # scope perfectamente válido — `uidNone`. Eso es un balde común: todo lo que se indexe
    # sin dueño cae ahí y cualquiera que llegue con `None` lo lee. Un id ausente tiene que
    # levantar, no convertirse en un dueño llamado «None».
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{prefijo}: se necesita un id de texto no vacío, llegó {valor!r}")
    plano = "".join(c for c in unicodedata.normalize("NFKD", valor) if c.isalnum())
    if not plano:
        raise ValueError(f"{prefijo}: el id no deja un solo carácter alfanumérico: {valor!r}")
    return f"{prefijo}{plano}"


def _alcance(user_id: str, space_id: Optional[str]) -> str:
    """El texto de la columna `alcance` de un documento."""
    partes = [_tok_scope("uid", user_id)]
    if space_id:
        partes.append(_tok_scope("spc", space_id))
    return " ".join(partes)


# ── el esquema ──────────────────────────────────────────────────────────────────────
# `alcance` es una columna indexada más, para poder decir `alcance:uidXXX` en el MATCH.
# `tipo`/`ref`/`ref2`/`fecha` son UNINDEXED: viajan con la fila para no volver a la DB, y
# no ensucian el ranking ni el vocabulario.
_ESQUEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS doc USING fts5(
    alcance,
    titulo,
    cuerpo,
    tipo   UNINDEXED,
    ref    UNINDEXED,
    ref2   UNINDEXED,
    rotulo UNINDEXED,
    fecha  UNINDEXED,
    tokenize = 'unicode61'
);
"""

#: bm25 pondera por columna, best-first ascendente. Copiado en forma del canal léxico de
#: Legal (`ORDER BY bm25(chunks_fts, 1.0, 2.0, 2.0)`), donde el rótulo y el nombre del
#: documento pesan más que el cuerpo: acá el equivalente es el TÍTULO del hilo o del
#: artefacto. `alcance` va en 0.0 — es scope, no relevancia: si contara, un dueño con
#: muchos documentos rankearía distinto que otro, que es exactamente lo que no queremos.
_BM25 = "bm25(doc, 0.0, 2.0, 1.0)"

_TIPOS = ("hilo", "mensaje", "artefacto")


def abrir(ruta: Optional[Path] = None) -> sqlite3.Connection:
    """Abre (y crea si hace falta) el índice. Sin `try/except` alrededor del CREATE.

    El índice de Finanzas envuelve su `CREATE VIRTUAL TABLE` en un `except: pass` con el
    comentario «already exists or FTS5 not available». Medido, eso no degrada: los triggers
    se crean igual porque SQLite no valida la referencia, y el INSERT siguiente muere con
    `no such table` — o sea que sin FTS5 no se pierde la búsqueda, se pierde la ESCRITURA.
    Acá, si FTS5 no está, esta línea levanta y se ve.
    """
    p = Path(ruta) if ruta else ruta_indice()
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(str(p), check_same_thread=False)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode = WAL")
    cx.executescript(_ESQUEMA)
    return cx


# ── escritura ───────────────────────────────────────────────────────────────────────

def _borrar_dueno(cx: sqlite3.Connection, user_id: str) -> int:
    tok = _tok_scope("uid", user_id)
    n = cx.execute("SELECT count(*) FROM doc WHERE doc MATCH ?",
                   (f"alcance:{tok}",)).fetchone()[0]
    if n:
        cx.execute("DELETE FROM doc WHERE rowid IN "
                   "(SELECT rowid FROM doc WHERE doc MATCH ?)", (f"alcance:{tok}",))
    return n


def _poner(cx: sqlite3.Connection, *, user_id: str, space_id: Optional[str],
           titulo: str, cuerpo: str, tipo: str, ref: str,
           ref2: str = "", rotulo: str = "", fecha: str = "") -> None:
    """`titulo` se INDEXA y pesa doble; `rotulo` sólo viaja para la pantalla.

    La distinción la destapó medir: al principio el mensaje se indexaba con el título de
    su hilo y buscar «diseño» devolvía los CUARENTA mensajes de un hilo llamado «Notas de
    diseño», cada uno con un snippet que no contenía la palabra. Un resultado que no puede
    explicar por qué está es ruido. Ahora el título del hilo sólo hace matchear al HILO
    —que ya es un grupo propio de la respuesta— y el mensaje matchea por su texto.
    """
    if tipo not in _TIPOS:
        raise ValueError(f"tipo desconocido: {tipo!r} (esperaba uno de {_TIPOS})")
    cx.execute(
        "INSERT INTO doc (alcance, titulo, cuerpo, tipo, ref, ref2, rotulo, fecha) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (_alcance(user_id, space_id), titulo or "", cuerpo or "", tipo,
         str(ref), str(ref2 or ""), str(rotulo or ""), str(fecha or "")),
    )


def reconstruir(conn_aleph: Any, user_id: str, *,
                cx: Optional[sqlite3.Connection] = None,
                artefactos: Optional[Iterable[dict]] = None) -> dict:
    """Rehace el índice **de este dueño**, entero. Devuelve la cuenta por tipo.

    `conn_aleph` es la conexión de la casa (la que habla Postgres y baja a SQLite por
    `dialect`). `artefactos` es opcional para poder medir sin el store en disco; si no
    viene, se lee de `artifact_store`.

    Sólo se borra y se reescribe lo de ESTE dueño: el índice de otro no se toca, así que
    dos reconstrucciones concurrentes de dueños distintos no se pisan.
    """
    propio = cx is None
    cx = cx or abrir()
    try:
        _borrar_dueno(cx, user_id)
        cuenta = {"hilos": 0, "mensajes": 0, "artefactos": 0}

        with conn_aleph.cursor() as cur:
            cur.execute(
                "SELECT id, title, created_at FROM chats WHERE user_id = %s", (user_id,))
            hilos = [dict(zip(("id", "title", "created_at"), r)) for r in cur.fetchall()]
        for h in hilos:
            _poner(cx, user_id=user_id, space_id=None, titulo=h["title"] or "",
                   cuerpo="", tipo="hilo", ref=h["id"], fecha=h["created_at"] or "")
            cuenta["hilos"] += 1

        with conn_aleph.cursor() as cur:
            # El JOIN por `c.user_id` es el MISMO scope que ya tiene `/v1/chats/search`:
            # el índice no puede ver más de lo que el endpoint con dueño veía.
            cur.execute(
                "SELECT m.id, m.chat_id, m.content, m.space_id, m.created_at, c.title "
                "FROM chat_messages m JOIN chats c ON c.id = m.chat_id "
                "WHERE c.user_id = %s", (user_id,))
            msgs = [dict(zip(("id", "chat_id", "content", "space_id", "created_at", "title"), r))
                    for r in cur.fetchall()]
        for m in msgs:
            if not (m["content"] or "").strip():
                continue
            _poner(cx, user_id=user_id, space_id=m["space_id"], titulo="",
                   cuerpo=m["content"], tipo="mensaje", ref=str(m["id"]),
                   ref2=m["chat_id"] or "", rotulo=m["title"] or "",
                   fecha=m["created_at"] or "")
            cuenta["mensajes"] += 1

        for a in (artefactos if artefactos is not None else _artefactos_de(user_id)):
            _poner(cx, user_id=user_id, space_id=a.get("space_id"),
                   titulo=a.get("title") or "", cuerpo=a.get("content") or "",
                   tipo="artefacto", ref=a.get("id") or "", ref2=a.get("sid") or "",
                   fecha=a.get("updated_at") or a.get("created_at") or "")
            cuenta["artefactos"] += 1

        cx.commit()
        return cuenta
    finally:
        if propio:
            cx.close()


def _artefactos_de(user_id: str) -> list[dict]:
    """Los artefactos del dueño, del store en disco.

    Camina las sesiones y se queda con las que declaran `owner == user_id`. Una sesión
    **sin dueño** NO entra: el store las trata como abiertas por compatibilidad con lo
    viejo (`artifact_store.get_owner`), y un índice transversal no es lugar para heredar
    esa apertura — sin dueño no hay token de scope, y sin token no hay fila.
    """
    import json
    from app.phase1 import artifact_store as store
    out: list[dict] = []
    root = store.art_root()
    if not root.is_dir():
        return out
    for p in sorted(root.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue                      # una sesión ilegible no rompe el resto
        if not isinstance(data, dict) or str(data.get("owner") or "") != str(user_id):
            continue
        for a in data.get("artifacts", []) or []:
            versiones = a.get("versions") or []
            cuerpo = ""
            if versiones and isinstance(versiones[-1], dict):
                cuerpo = versiones[-1].get("content") or ""
            out.append({"id": a.get("id"), "sid": p.stem, "title": a.get("title"),
                        "content": cuerpo, "created_at": a.get("created_at"),
                        "updated_at": a.get("updated_at"),
                        "space_id": data.get("space_id")})
    return out


# ── lectura ─────────────────────────────────────────────────────────────────────────

#: Constante de la fusión por rango recíproco, con el valor de Legal
#: (`search-document.ts:47`). RRF trabaja sobre RANGOS, así que las escalas incomparables
#: de los dos canales nunca hay que normalizarlas.
_RRF_K = 60
_CANDIDATOS = 40


def _canal(cx: sqlite3.Connection, match: str, tipo: Optional[str]) -> list[sqlite3.Row]:
    sql = (f"SELECT rowid, titulo, cuerpo, tipo, ref, ref2, rotulo, fecha, {_BM25} AS r "
           "FROM doc WHERE doc MATCH ?")
    args: list[Any] = [match]
    if tipo:
        sql += " AND tipo = ?"
        args.append(tipo)
    sql += f" ORDER BY {_BM25} LIMIT ?"
    args.append(_CANDIDATOS)
    try:
        return list(cx.execute(sql, tuple(args)).fetchall())
    except sqlite3.OperationalError:
        # Una consulta que FTS5 rechaza es un canal vacío, no una búsqueda rota: el otro
        # canal puede tener resultados. Lo que NO se hace es tragarse un fallo de esquema
        # — para eso está `abrir()`, que levanta.
        return []


def buscar(user_id: str, q: str, *, space_id: Optional[str] = None,
           limite: int = 20, cx: Optional[sqlite3.Connection] = None) -> dict:
    """Una consulta → `{"q", "hilos", "mensajes", "artefactos", "total", "recortado"}`.

    **Sin dueño no hay búsqueda**: `_tok_scope` levanta `ValueError` antes de tocar la
    base. No devuelve vacío — no se puede ni construir la consulta.
    """
    tok_uid = _tok_scope("uid", user_id)          # ← el fail-closed, antes que nada
    alcance = f"alcance:{tok_uid}"
    if space_id:
        alcance += f" AND alcance:{_tok_scope('spc', space_id)}"

    tokens = _tokens(q)
    if not tokens:
        return {"q": q, "hilos": [], "mensajes": [], "artefactos": [],
                "total": 0, "recortado": False}

    propio = cx is None
    cx = cx or abrir()
    try:
        salida: dict[str, list] = {"hilos": [], "mensajes": [], "artefactos": []}
        grupo = {"hilo": "hilos", "mensaje": "mensajes", "artefacto": "artefactos"}
        recortado = False

        for tipo, clave in grupo.items():
            # Dos canales, como Legal. El léxico (OR) deja que bm25 haga su trabajo: un
            # token raro domina el ranking y una casi-stopword no aporta casi nada. El de
            # frase sólo matchea la secuencia literal — un nombre de artefacto, un id —, y
            # está vacío para una consulta parafraseada. Sin él, el documento que contiene
            # la frase exacta puede quedar debajo de los que los dos canales difusos
            # quieren, que es justo lo que la búsqueda híbrida existe para evitar.
            canales = [_canal(cx, f"{alcance} AND ({_o(tokens)})", tipo)]
            if len(tokens) > 1:
                canales.append(_canal(cx, f"{alcance} AND {_frase(tokens)}", tipo))

            puntos: dict[int, float] = {}
            filas: dict[int, sqlite3.Row] = {}
            for canal in canales:
                for rango, fila in enumerate(canal):
                    puntos[fila["rowid"]] = puntos.get(fila["rowid"], 0.0) + 1.0 / (_RRF_K + rango + 1)
                    filas[fila["rowid"]] = fila
            orden = sorted(puntos, key=lambda rid: -puntos[rid])
            if len(orden) > limite:
                recortado = True
            for rid in orden[:limite]:
                salida[clave].append(_fila(filas[rid], tokens))

        total = sum(len(v) for v in salida.values())
        # `recortado` viaja porque un total que calla su tope miente. Es la misma
        # enfermedad que `isExporterReady()` devolviendo siempre `true`.
        return {"q": q, **salida, "total": total, "recortado": recortado}
    finally:
        if propio:
            cx.close()


def _fila(f: sqlite3.Row, tokens: list[str]) -> dict:
    d = {"tipo": f["tipo"], "ref": f["ref"],
         "titulo": f["titulo"] or f["rotulo"], "fecha": f["fecha"]}
    if f["ref2"]:
        d["ref2"] = f["ref2"]
    if f["tipo"] != "hilo":
        d["snippet"] = _snippet(f["cuerpo"], tokens)
    return d


def _snippet(cuerpo: str, tokens: list[str], ancho: int = 160) -> str:
    """Fragmento centrado en el primer token que aparezca.

    A mano y no con `snippet()` de FTS5 a propósito: la función de SQLite trabaja sobre el
    texto TOKENIZADO y devuelve el fragmento con sus propias marcas; acá el cuerpo original
    ya está en la fila y lo que la pantalla necesita es texto plano, sin marcas que después
    haya que limpiar.
    """
    cuerpo = cuerpo or ""
    plano = cuerpo.lower()
    pos = -1
    for t in tokens:
        pos = plano.find(t.lower())
        if pos >= 0:
            break
    if pos < 0:
        return cuerpo[:ancho] + ("…" if len(cuerpo) > ancho else "")
    ini = max(0, pos - ancho // 3)
    fin = min(len(cuerpo), ini + ancho)
    return ("…" if ini > 0 else "") + cuerpo[ini:fin].strip() + ("…" if fin < len(cuerpo) else "")


__all__ = ["abrir", "buscar", "reconstruir", "ruta_indice"]
