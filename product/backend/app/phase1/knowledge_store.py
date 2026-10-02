"""
STEP 2 · C1 — knowledge_store: abstracción de ALMACENAMIENTO del corpus RAG por composición.

El corte NO es free/premium: es DÓNDE VIVE EL ÍNDICE, expresado como `storage_mode` runtime
(PUPPET_RAG_STORAGE_MODE, leído por recipe_enforcer.rag_storage_mode() — NO editable por receta):

  • self_hosted  (DEFAULT, el path de prod local-first): el índice es un ARCHIVO sqlite REAL en el
    disco del propio usuario, UNO por composición (<rag_dir>/<composition_id>/knowledge.db). Los
    documentos NUNCA salen de su equipo (tesis de privacidad). Recuperación local en Python puro
    (coseno de rag_index.top_k). SIN cap (enforcer = None → no-op). Generoso/ilimitado.

  • hosted  (LATENTE, cableado+testeado, no el path por defecto): el índice vive en el Postgres de
    Aleph vía el DAO knowledge_* de repo.py (multi-tenant futuro → Aleph paga storage → cap por MB
    sobre el tier de la CUENTA). Mismas tablas, mismo anti-IDOR/CASCADE ya probados en B2.

AISLAMIENTO estructural: la instancia queda ligada a UN composition_id resuelto server-side desde un
puppet PROPIO (nunca lo aporta el cliente); en self_hosted la ruta del .db se DERIVA de ese id →
dos composiciones = dos archivos distintos. En hosted el FK composition_id → puppets aísla las filas.

NOTA (reconciliación con la tesis de persona usuaria): imaginó un archivo sqlite-vec; ground-truth = sqlite-vec
(la EXTENSIÓN) ausente+frágil en este venv, pero sqlite3 es stdlib. La realización fiel = archivo
sqlite3 plano + coseno en Python puro (misma garantía de "archivo-en-disco"; sqlite-vec = optimización
drop-in a futuro). numpy/pgvector ausentes → coseno puro confirmado.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from app.phase1 import rag_index


def _lock_vfs(que: str):
    """El serializador de apertura/cierre de `platform/db/sqlite_db` (ver `_conn` abajo).

    Import PEREZOSO y con red: este módulo es el corpus RAG y no puede caerse porque la
    capa de DB del cliente no viaje (rol control empaquetado, un test que importa suelto).
    Si `sqlite_db` no está, se devuelve un contexto vacío: se vuelve al comportamiento de
    antes —correcto, sólo sin la protección— en vez de romper el RAG entero.
    """
    try:
        import sqlite_db                                   # noqa: PLC0415 — perezoso a propósito
        return sqlite_db.lock_vfs(que)
    except Exception:                                      # noqa: BLE001 — ver docstring
        from contextlib import nullcontext
        return nullcontext()


# repo root = .../aleph-step2-c1 ; backend root = .../product/backend (para el rag_dir por defecto).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# composition_id se resuelve SIEMPRE server-side desde un puppet propio (UUID). Igual validamos el
# token antes de convertirlo en ruta de archivo: defensa-en-profundidad contra path-traversal.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _safe_composition_id(composition_id: str) -> str:
    """Valida que composition_id sea un token seguro para usar como nombre de carpeta (sin
    separadores de ruta ni '..'). Lanza ValueError si no lo es — el cliente NUNCA aporta rutas."""
    cid = str(composition_id or "").strip()
    if not _SAFE_ID_RE.match(cid) or cid in (".", ".."):
        raise ValueError("unsafe_composition_id")
    return cid


def rag_dir_root() -> str:
    """Raíz en disco de los índices self-hosted: env PUPPET_RAG_DIR, o el dir de datos del
    usuario. Crea el árbol (mkdir -p) y devuelve la ruta absoluta.

    ⚠️ TERCER CASO DE LA MISMA CLASE. Esto apuntaba a `<backend>/data/rag` vía
    `parents[2]`, que bajo PyInstaller cae dentro de `_MEIPASS` — el temp del bundle, que
    se borra al cerrar. Era un SEGUNDO resolvedor de la raíz RAG, independiente del de
    `rag_store`: dos módulos calculando la misma ruta por su cuenta es cómo se llega a que
    uno se arregle y el otro no. Ahora los dos leen `aleph_paths.rag_dir()`.
    """
    root = os.getenv("PUPPET_RAG_DIR")
    if not root:
        try:
            import aleph_paths
            root = str(aleph_paths.rag_dir())
        except Exception:                # noqa: BLE001 — dev sin platform en el path
            root = str(_BACKEND_ROOT / "data" / "rag")
    os.makedirs(root, exist_ok=True)
    return root


def _corpus_embed_from_rows(triples: list[tuple]) -> dict[str, Any]:
    """STEP 2·C1 · Finding #2 — reduce las tuplas (embed_provider, embed_model, embed_dim) de los
    docs INDEXADOS a la FIRMA de embeddings del corpus, para que la RECUPERACIÓN siga al corpus (no
    a la receta) y jamás caiga en un empty silencioso por drift:
      • {}                       → no hay corpus indexado con proveedor conocido (nada que seguir).
      • {'mixed': True}          → los docs indexados NO concuerdan (distinto provider/model/dim) →
                                   el caller degrada honesto ('rag_needs_reindex').
      • {provider, model, dim}   → firma única → embeber la query con EXACTAMENTE ese provider/model.
    Normaliza el provider a minúsculas y compara la terna completa (provider, model, dim)."""
    seen: set = set()
    info: dict[str, Any] = {}
    for prov, model, dim in triples:
        p = str(prov).strip().lower() if prov else ""
        if not p:
            continue
        d = int(dim) if dim is not None else None
        key = (p, model, d)
        if key not in seen:
            seen.add(key)
            info = {"provider": p, "model": model, "dim": d}
    if not seen:
        return {}
    if len(seen) > 1:
        return {"mixed": True}
    return info


def _with_provenance(hits: list[tuple[dict, float]]) -> list[tuple[dict, float]]:
    """Adjunta a cada chunk recuperado un dict `provenance` = {doc_name, chunk_ix} SIN quitar las
    claves planas (id/doc_id/doc_name/chunk_ix/content/embedding/meta) que consume el executor para
    armar el tag [doc#chunk]. Mismo shape en ambos backends → el read-path es agnóstico al modo."""
    out: list[tuple[dict, float]] = []
    for ch, score in hits:
        if isinstance(ch, dict):
            ch["provenance"] = {
                "doc_name": ch.get("doc_name"),
                "chunk_ix": ch.get("chunk_ix"),
            }
        out.append((ch, score))
    return out


# ─────────────────────────── Interfaz (composition-scoped) ───────────────────────────


class KnowledgeStore(ABC):
    """Corpus RAG de UNA composición. Todas las lecturas/escrituras quedan ligadas al
    composition_id de construcción — el aislamiento no es un parámetro, es la frontera del objeto."""

    composition_id: str

    @abstractmethod
    def add_doc(self, *, doc_name: str, mime: Optional[str] = None, bytes: int = 0,
                sha256: Optional[str] = None,
                meta: Optional[dict[str, Any]] = None) -> Optional[str]:
        """Registra un doc en estado 'pending'. Devuelve el doc_id."""

    @abstractmethod
    def set_status(self, doc_id: str, status: str, *, error: Optional[str] = None,
                   embed_provider: Optional[str] = None, embed_model: Optional[str] = None,
                   embed_dim: Optional[int] = None,
                   n_chunks: Optional[int] = None) -> Optional[dict[str, Any]]:
        """Transiciona el status honesto (pending|indexed|error_no_key|error) + guardia de drift."""

    @abstractmethod
    def add_chunk(self, *, doc_id: str, chunk_ix: int, content: str, bytes: int = 0,
                  embedding: Optional[list] = None,
                  meta: Optional[dict[str, Any]] = None) -> Optional[str]:
        """Agrega un chunk indexado (embedding = array de floats o None)."""

    @abstractmethod
    def list_docs(self) -> list[dict[str, Any]]:
        """Docs del corpus para el PANEL: sin embeddings ni cuerpos (sólo metadata)."""

    @abstractmethod
    def get_doc(self, doc_id: str) -> Optional[dict[str, Any]]:
        """Un doc por id (incluye composition_id para el cross-check anti-IDOR del router)."""

    @abstractmethod
    def delete_doc(self, doc_id: str) -> bool:
        """Borra un doc y CASCADEA sus chunks. True si borró algo."""

    @abstractmethod
    def usage(self) -> dict[str, int]:
        """{doc_count, total_bytes, indexed_count} del corpus. `indexed_count` = chunks con embedding
        (los ÚNICOS recuperables) → el read-path sólo paga un embed BYOK cuando hay algo que traer."""

    @abstractmethod
    def corpus_embed_info(self) -> dict[str, Any]:
        """STEP 2·C1 · Finding #2 · firma de embeddings de los docs INDEXADOS: {} (nada indexado),
        {'mixed': True} (docs en conflicto) o {provider, model, dim} único. La recuperación embebe la
        query SIGUIENDO esta firma (no la receta) → cero empty silencioso por drift de proveedor."""

    @abstractmethod
    def retrieve_topk(self, query_vec: list[float], k: int = 5) -> list[tuple[dict, float]]:
        """Top-k chunks por coseno contra query_vec, con provenance {doc_name, chunk_ix}."""

    @abstractmethod
    def enforce_caps(self, max_docs: int, max_bytes: int) -> int:
        """Frontera del corpus (sólo hosted). En self_hosted es no-op (cap=None). Devuelve #desalojados."""


# ─────────────────────────── SelfHostedStore (DEFAULT · sqlite FILE) ───────────────────────────


_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
  id             TEXT PRIMARY KEY,
  doc_name       TEXT NOT NULL,
  mime           TEXT,
  bytes          INTEGER NOT NULL DEFAULT 0,
  sha256         TEXT,
  status         TEXT NOT NULL DEFAULT 'pending',
  error          TEXT,
  embed_provider TEXT,
  embed_model    TEXT,
  embed_dim      INTEGER,
  n_chunks       INTEGER NOT NULL DEFAULT 0,
  meta           TEXT NOT NULL DEFAULT '{}',
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
CREATE TABLE IF NOT EXISTS chunks (
  id         TEXT PRIMARY KEY,
  doc_id     TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  chunk_ix   INTEGER NOT NULL,
  content    TEXT NOT NULL,
  bytes      INTEGER NOT NULL DEFAULT 0,
  embedding  TEXT,
  meta       TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
"""


class SelfHostedStore(KnowledgeStore):
    """DEFAULT — un archivo sqlite por composición en el disco del usuario. EL ARCHIVO es la frontera
    de aislamiento: dos composiciones abren dos .db distintos. stdlib sqlite3, SQL parametrizado,
    embeddings serializados como texto JSON. Schema on-first-use."""

    def __init__(self, rag_dir: str, composition_id: str):
        self.composition_id = _safe_composition_id(composition_id)
        comp_dir = os.path.join(rag_dir, self.composition_id)
        os.makedirs(comp_dir, exist_ok=True)
        self.db_path = os.path.join(comp_dir, "knowledge.db")
        with self._conn() as c:               # crea el schema la primera vez
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        """Conexión efímera por operación, con la apertura y el cierre SERIALIZADOS.

        ⚠️ CORRECCIÓN [Integración #5 · auditoría (a)]. Este docstring decía "sqlite es
        barato de abrir → sin problemas de hilos", y `pool.py` citaba justamente a este
        método como el precedente que probaba el patrón. Resultó FALSO y era el cuelgue
        de escritura del sidecar: abrir y cerrar por operación, con varios pools de hilos
        en el proceso, traba el mutex de la tabla de inodos del VFS de SQLite y el proceso
        no vuelve nunca (stacks y repro en `platform/db/sqlite_db.py` §EL DEADLOCK DEL VFS).

        Ese mutex es global al PROCESO, **no por archivo**: que este store use su propio
        `knowledge.db` no lo salva — su `close()` compite contra el `open()` de `aleph.db`.
        Y como acá se abre por fuera de `conectar()`, el almacén de conexiones de W no lo
        cubre; sin esto, un solo módulo desalineado anulaba la capa 2 para todos.

        Se aplica la capa 2 (serializar), no la 1 (reusar): el corpus RAG hace pocas
        operaciones grandes, así que la fila del lock no cuesta nada y se conserva el
        aislamiento por archivo. Como en `platform/db/sqlite_db`, TODA conexión activa
        foreign_keys + WAL + busy_timeout=30s; el segundo archivo SQLite no puede quedar
        con una disciplina distinta a `aleph.db`.
        """
        with _lock_vfs(f"abrir {os.path.basename(self.db_path)}"):
            conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 30000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            with _lock_vfs("cerrar knowledge.db"):
                conn.close()

    def add_doc(self, *, doc_name: str, mime: Optional[str] = None, bytes: int = 0,
                sha256: Optional[str] = None,
                meta: Optional[dict[str, Any]] = None) -> Optional[str]:
        doc_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute(
                "INSERT INTO docs (id, doc_name, mime, bytes, sha256, status, meta) "
                "VALUES (?,?,?,?,?,'pending',?)",
                (doc_id, doc_name, mime, int(bytes or 0), sha256,
                 json.dumps(meta if meta is not None else {})),
            )
        return doc_id

    def set_status(self, doc_id: str, status: str, *, error: Optional[str] = None,
                   embed_provider: Optional[str] = None, embed_model: Optional[str] = None,
                   embed_dim: Optional[int] = None,
                   n_chunks: Optional[int] = None) -> Optional[dict[str, Any]]:
        # COALESCE(?, col): si el caller NO pasa el campo (None), conserva lo existente — misma
        # semántica que repo.set_doc_status (el path de error no borra provider/dim/n_chunks).
        with self._conn() as c:
            c.execute(
                "UPDATE docs SET status = ?, error = ?, "
                "embed_provider = COALESCE(?, embed_provider), "
                "embed_model = COALESCE(?, embed_model), "
                "embed_dim = COALESCE(?, embed_dim), "
                "n_chunks = COALESCE(?, n_chunks) WHERE id = ?",
                (status, error, embed_provider, embed_model, embed_dim, n_chunks, doc_id),
            )
        return self.get_doc(doc_id)

    def add_chunk(self, *, doc_id: str, chunk_ix: int, content: str, bytes: int = 0,
                  embedding: Optional[list] = None,
                  meta: Optional[dict[str, Any]] = None) -> Optional[str]:
        chunk_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute(
                "INSERT INTO chunks (id, doc_id, chunk_ix, content, bytes, embedding, meta) "
                "VALUES (?,?,?,?,?,?,?)",
                (chunk_id, doc_id, int(chunk_ix), content, int(bytes or 0),
                 json.dumps(embedding) if embedding is not None else None,
                 json.dumps(meta if meta is not None else {})),
            )
        return chunk_id

    def list_docs(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, doc_name, mime, bytes, status, error, n_chunks, created_at "
                "FROM docs ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_doc(self, doc_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as c:
            row = c.execute(
                "SELECT id, doc_name, mime, bytes, sha256, status, error, embed_provider, "
                "embed_model, embed_dim, n_chunks, meta, created_at FROM docs WHERE id = ?",
                (doc_id,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["meta"] = json.loads(d["meta"]) if d.get("meta") else {}
        # composition_id sintético: en self_hosted el ARCHIVO es la frontera, pero el router hace el
        # cross-check uniforme doc.composition_id != cid → 404 en ambos modos, así que lo aportamos.
        d["composition_id"] = self.composition_id
        return d

    def delete_doc(self, doc_id: str) -> bool:
        with self._conn() as c:
            # FK ON DELETE CASCADE + foreign_keys=ON arrastra los chunks; borramos explícito además
            # (idempotente) por si el pragma no aplicara en algún build de sqlite.
            c.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            cur = c.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
            deleted = cur.rowcount > 0
        return deleted

    def usage(self) -> dict[str, int]:
        # indexed_count = chunks CON embedding (los recuperables por retrieve_topk) — separado del
        # doc_count (que cuenta TODO doc, incl. pending/error/error_no_key). El read-path gatea el
        # embed BYOK sobre indexed_count → no paga una llamada que nunca traería nada (Finding #4).
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM docs"
            ).fetchone()
            ir = c.execute(
                "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
            ).fetchone()
        return {"doc_count": int(row[0] or 0), "total_bytes": int(row[1] or 0),
                "indexed_count": int(ir[0] or 0)}

    def corpus_embed_info(self) -> dict[str, Any]:
        # STEP 2·C1 · Finding #2 — la firma de embeddings de los docs INDEXADOS de ESTE archivo.
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT embed_provider, embed_model, embed_dim FROM docs "
                "WHERE status = 'indexed' AND embed_provider IS NOT NULL"
            ).fetchall()
        return _corpus_embed_from_rows(
            [(r["embed_provider"], r["embed_model"], r["embed_dim"]) for r in rows])

    def retrieve_topk(self, query_vec: list[float], k: int = 5) -> list[tuple[dict, float]]:
        # Carga los chunks INDEXADOS (embedding no nulo) de ESTE archivo, con doc_name (JOIN) para la
        # procedencia, deserializa el embedding JSON → coseno en Python puro (rag_index.top_k).
        with self._conn() as c:
            rows = c.execute(
                "SELECT c.id, c.doc_id, d.doc_name, c.chunk_ix, c.content, c.embedding, c.meta "
                "FROM chunks c JOIN docs d ON d.id = c.doc_id "
                "WHERE c.embedding IS NOT NULL ORDER BY c.doc_id, c.chunk_ix"
            ).fetchall()
        chunks: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["embedding"] = json.loads(d["embedding"]) if d.get("embedding") else None
            except (ValueError, TypeError):
                d["embedding"] = None
            try:
                d["meta"] = json.loads(d["meta"]) if d.get("meta") else {}
            except (ValueError, TypeError):
                d["meta"] = {}
            chunks.append(d)
        return _with_provenance(rag_index.top_k(query_vec, chunks, k))

    def enforce_caps(self, max_docs: int, max_bytes: int) -> int:
        # self_hosted NO tiene cap (el índice vive en el disco del propio usuario). No-op honesto:
        # el router ni siquiera llama esto cuando caps is None; lo dejamos inerte por contrato.
        return 0


# ─────────────────────────── HostedStore (LATENTE · Postgres/repo.py) ───────────────────────────


class HostedStore(KnowledgeStore):
    """LATENTE — corpus en el Postgres de Aleph vía el DAO knowledge_* de repo.py. Delegación pura:
    reusa el anti-IDOR (FK composition_id → puppets), CASCADE y el idiom de commit ya probados en B2.
    El aislamiento lo da el scope estricto por composition_id en cada query del DAO."""

    def __init__(self, conn, composition_id: str):
        if conn is None:
            raise ValueError("HostedStore requiere una conexión Postgres (conn=None)")
        self.conn = conn
        self.composition_id = str(composition_id)
        from app.phase1 import repo as _repo   # lazy: no acopla la DB al import base
        self._repo = _repo

    def add_doc(self, *, doc_name: str, mime: Optional[str] = None, bytes: int = 0,
                sha256: Optional[str] = None,
                meta: Optional[dict[str, Any]] = None) -> Optional[str]:
        return self._repo.add_knowledge_doc(
            self.conn, composition_id=self.composition_id, doc_name=doc_name,
            mime=mime, bytes=bytes, sha256=sha256, meta=meta)

    def set_status(self, doc_id: str, status: str, *, error: Optional[str] = None,
                   embed_provider: Optional[str] = None, embed_model: Optional[str] = None,
                   embed_dim: Optional[int] = None,
                   n_chunks: Optional[int] = None) -> Optional[dict[str, Any]]:
        return self._repo.set_knowledge_doc_status(
            self.conn, doc_id, status, error=error, embed_provider=embed_provider,
            embed_model=embed_model, embed_dim=embed_dim, n_chunks=n_chunks)

    def add_chunk(self, *, doc_id: str, chunk_ix: int, content: str, bytes: int = 0,
                  embedding: Optional[list] = None,
                  meta: Optional[dict[str, Any]] = None) -> Optional[str]:
        return self._repo.add_knowledge_chunk(
            self.conn, composition_id=self.composition_id, doc_id=doc_id, chunk_ix=chunk_ix,
            content=content, bytes=bytes, embedding=embedding, meta=meta)

    def list_docs(self) -> list[dict[str, Any]]:
        return self._repo.list_knowledge_docs(self.conn, self.composition_id)

    def get_doc(self, doc_id: str) -> Optional[dict[str, Any]]:
        return self._repo.get_knowledge_doc(self.conn, doc_id)

    def delete_doc(self, doc_id: str) -> bool:
        return self._repo.delete_knowledge_doc(self.conn, doc_id)

    def usage(self) -> dict[str, int]:
        # doc_count/total_bytes vienen del DAO; indexed_count = chunks CON embedding (recuperables) →
        # el read-path sólo paga el embed BYOK cuando hay algo que traer (Finding #4). Query inline
        # por la misma conn (mismo scope anti-IDOR por composition_id que list_chunks_for_retrieval).
        u = dict(self._repo.knowledge_usage(self.conn, self.composition_id))
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM knowledge_chunks "
                "WHERE composition_id = %s AND embedding IS NOT NULL", (self.composition_id,))
            row = cur.fetchone()
        u["indexed_count"] = int(row[0] or 0) if row else 0
        return u

    def corpus_embed_info(self) -> dict[str, Any]:
        # STEP 2·C1 · Finding #2 — firma de embeddings de los docs INDEXADOS de ESTA composición
        # (scope estricto por composition_id, mismo anti-IDOR que el resto del DAO hosted).
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT embed_provider, embed_model, embed_dim FROM knowledge_docs "
                "WHERE composition_id = %s AND status = 'indexed' AND embed_provider IS NOT NULL",
                (self.composition_id,))
            rows = cur.fetchall()
        return _corpus_embed_from_rows([(r[0], r[1], r[2]) for r in rows])

    def retrieve_topk(self, query_vec: list[float], k: int = 5) -> list[tuple[dict, float]]:
        chunks = self._repo.list_chunks_for_retrieval(self.conn, self.composition_id)
        return _with_provenance(rag_index.top_k(query_vec, chunks, k))

    def enforce_caps(self, max_docs: int, max_bytes: int) -> int:
        return self._repo.enforce_knowledge_caps(
            self.conn, self.composition_id, max_docs, max_bytes)


# ─────────────────────────── Selección de backend ───────────────────────────


def _rag_storage_mode() -> str:
    """Lee el modo de almacenamiento de recipe_enforcer (env PUPPET_RAG_STORAGE_MODE, default
    self_hosted). Import por-ruta como el resto del backend: platform no es un paquete asumido."""
    try:
        _pd = str(_REPO_ROOT / "platform")
        if _pd not in sys.path:
            sys.path.insert(0, _pd)
        from gates.recipe_enforcer import rag_storage_mode
        return rag_storage_mode()
    except Exception:
        return "self_hosted"   # fail-safe al path de prod local-first


def get_store(storage_mode: Optional[str] = None, *, conn=None,
              composition_id: str) -> KnowledgeStore:
    """Devuelve el KnowledgeStore del composition_id según storage_mode (o el runtime del enforcer):
      • 'hosted'  → HostedStore(conn, cid)         — corpus en el Postgres de Aleph (latente)
      • otro/None → SelfHostedStore(rag_dir, cid)  — archivo sqlite en el disco del usuario (default)
    El composition_id se resuelve SIEMPRE server-side desde un puppet propio; el cliente NUNCA aporta
    ni ruta ni conexión."""
    mode = (storage_mode or _rag_storage_mode() or "").strip().lower()
    if mode == "hosted":
        return HostedStore(conn, composition_id)
    return SelfHostedStore(rag_dir_root(), composition_id)


__all__ = [
    "KnowledgeStore",
    "SelfHostedStore",
    "HostedStore",
    "rag_dir_root",
    "get_store",
]
