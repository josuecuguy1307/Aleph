"""SQLite FTS5 session search index for cross-session full-text search.

Stores an inverted index of all conversation messages. The primary data
remains in the file-based SessionStore; this module provides a fast search
layer on top.

Database location: ``sessions.db`` under the runtime root (default
``~/.vibe-trading``; WAL mode for concurrent reads).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.config.paths import get_runtime_root

logger = logging.getLogger(__name__)

_DB_PATH = get_runtime_root() / "sessions.db"


@dataclass(frozen=True)
class SearchMatch:
    """A single search result from the FTS5 index.

    Attributes:
        session_id: Session ID.
        title: Session title.
        started_at: Human-readable start time.
        message_count: Total messages in the session.
        snippet: FTS5 snippet with match highlights (>>> <<<).
        rank: FTS5 relevance rank (lower is better).
    """

    session_id: str
    title: str
    started_at: str
    message_count: int
    snippet: str
    rank: float

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict."""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "started_at": self.started_at,
            "message_count": self.message_count,
            "snippet": self.snippet,
        }


class SessionSearchIndex:
    """SQLite FTS5 index for cross-session search.

    Supports:
        - Indexing individual messages as they arrive
        - Full-text search with relevance ranking
        - Bulk reindex from the file-based SessionStore
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        """Initialize the search index.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create the SQLite connection (WAL mode)."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self) -> None:
        """Create tables and FTS5 virtual table if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                started_at REAL NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_name TEXT,
                timestamp REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id);
        """)
        # FTS5 virtual table — create separately (not inside executescript with IF NOT EXISTS
        # because FTS5 syntax varies across SQLite versions)
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                USING fts5(content, content=messages, content_rowid=id)
            """)
        except sqlite3.OperationalError:
            pass  # already exists or FTS5 not available

        # Auto-sync triggers
        for trigger_sql in [
            """CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END""",
            """CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
            END""",
        ]:
            try:
                conn.execute(trigger_sql)
            except sqlite3.OperationalError:
                pass
        conn.commit()

    def index_session(
        self,
        session_id: str,
        title: str = "",
        ts: Optional[float] = None,
    ) -> None:
        """Upsert a session record.

        Args:
            session_id: Session ID.
            title: Session title.
            ts: Session start time as a Unix epoch. When ``None``, an
                existing row keeps its ``started_at`` and a new row is
                stamped with ``time.time()``. Passing an explicit value
                (e.g. parsed from the on-disk ``created_at``) overwrites
                the stored timestamp so that bulk reindex restores the
                true session start time rather than the reindex moment.
        """
        conn = self._get_conn()
        # Preserve the existing started_at when the caller does not supply
        # one — otherwise INSERT OR REPLACE would overwrite the original
        # session start time on every re-upsert, breaking date-sort/filter.
        conn.execute(
            "INSERT OR REPLACE INTO sessions (id, title, started_at, message_count) "
            "VALUES ("
            "  ?, ?,"
            "  COALESCE(?, (SELECT started_at FROM sessions WHERE id = ?), ?),"
            "  COALESCE((SELECT message_count FROM sessions WHERE id = ?), 0)"
            ")",
            (session_id, title, ts, session_id, time.time(), session_id),
        )
        conn.commit()

    def index_message(self, session_id: str, role: str, content: str,
                      tool_name: Optional[str] = None) -> None:
        """Index a single message.

        Args:
            session_id: Session ID.
            role: Message role (user/assistant/tool).
            content: Message text.
            tool_name: Tool name if this is a tool result.
        """
        if not content or not content.strip():
            return
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_name, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content[:50_000], tool_name, time.time()),
        )
        conn.execute(
            "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
            (session_id,),
        )
        conn.commit()

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize a user query for FTS5 MATCH syntax.

        - Splits on non-alphanumeric/CJK to extract tokens
        - Joins with OR so any-word-matches (not all-words-required)
        - Quotes each token to prevent FTS5 operator interpretation

        Args:
            query: Raw user query string.

        Returns:
            FTS5-safe MATCH expression.
        """
        import re as _re
        # [Aleph \u00b7 Convergencia \u00b7 Superficie 5 \u00b7 B\u00daSQUEDA] EL TOKENIZADOR VE EL ESPA\u00d1OL.
        #
        # El alternador era `[a-zA-Z0-9_]{2,}` \u2014 ASCII y CJK, sin acentos ni e\u00f1e. Aleph
        # corre en espa\u00f1ol y eso no devolv\u00eda de menos: devolv\u00eda CERO, o peor, ruido.
        # MEDIDO corriendo esta misma funci\u00f3n y llevando su salida a un FTS5 real:
        #     'a\u00f1o fiscal'      -> "fiscal"                \u2190 la palabra \u00aba\u00f1o\u00bb DESAPARECE
        #     'p\u00e9rdida m\u00e1xima'  -> "rdida" OR "xima"       \u2190 dos tokens que no existen: 0 hits
        #     'sesi\u00f3n'          -> "sesi"                  \u2190 0 hits
        #     'se\u00f1al'           -> "se" OR "al"            \u2190 matchea fragmentos: ruido
        # Sobre un corpus en castellano: 4 de 6 consultas daban 0, y de las 2 que
        # respond\u00edan, una era falso positivo. El ingl\u00e9s y el chino andaban bien.
        #
        # \u26a0\ufe0f NO es culpa de FTS5, y conviene dejarlo escrito para que nadie cambie de motor
        # por esto: con `unicode61` (el tokenizador por defecto) las mismas 6 consultas dan
        # 6 de 6. El texto se romp\u00eda AC\u00c1, antes de que FTS5 lo viera.
        #
        # Se arregla SIGUIENDO LA MISMA FORMA que ya ten\u00eda, no una m\u00e1s laxa: los tokens
        # siguen pidiendo 2+ caracteres y cada ideograma CJK sigue siendo un token de uno.
        # La rama CJK va PRIMERA porque la alternancia toma el primer match: con la gen\u00e9rica
        # adelante, \u00ab\u65e5\u672c\u00bb se habr\u00eda tomado como UN token de dos.
        #
        # \u26a0\ufe0f LA EXCLUSI\u00d3N DE KANA ES LOAD-BEARING, y la destap\u00f3 medir el caso que este
        # arreglo promet\u00eda no tocar. Un primer intento us\u00f3 `\w{2,}` a secas y rompi\u00f3 el
        # japon\u00e9s: \u00ab\u65e5\u672c\u306e\u682a\u5f0f\u00bb daba `"\u65e5" OR "\u672c" OR "\u306e\u682a\u5f0f"` en vez de los cuatro tokens de
        # antes, porque \u00ab\u306e\u00bb es hiragana (U+306E) \u2014 NO entra en los rangos CJK, as\u00ed que la
        # rama gen\u00e9rica se lo com\u00eda pegado al kanji siguiente. Antes el kana suelto se
        # descartaba, y tiene que seguir descart\u00e1ndose: por eso la clase gen\u00e9rica es
        # \u00abcar\u00e1cter de palabra que NO sea kana ni ideograma\u00bb.
        # (Mismo criterio y misma casa que `agent/src/agent/grounding.py:157`, donde este
        # stack ya recibi\u00f3 las anclas del espa\u00f1ol por la misma raz\u00f3n \u2014 ver
        # `HALLAZGO-GATE-IDIOMA.md`.)
        tokens = _re.findall(
            r"[\u4e00-\u9fff\u3400-\u4dbf]|[^\W\u3040-\u30ff\u4e00-\u9fff\u3400-\u4dbf]{2,}",
            query, _re.UNICODE)
        if not tokens:
            return '""'
        # Quote each token and join with OR for broader matching
        return " OR ".join(f'"{t}"' for t in tokens)

    def search(self, query: str, max_sessions: int = 3) -> List[SearchMatch]:
        """Full-text search across all sessions.

        Args:
            query: Search query (keywords or phrase).
            max_sessions: Maximum number of distinct sessions to return.

        Returns:
            List of SearchMatch results, grouped by session, ranked by relevance.
        """
        conn = self._get_conn()
        fts_query = self._sanitize_fts_query(query)
        try:
            cursor = conn.execute(
                """
                SELECT
                    m.session_id,
                    s.title,
                    s.started_at,
                    s.message_count,
                    snippet(messages_fts, 0, '>>>', '<<<', '...', 64) AS snippet,
                    rank
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                JOIN sessions s ON s.id = m.session_id
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, max_sessions * 5),
            )
        except sqlite3.OperationalError as exc:
            logger.warning("FTS5 search failed: %s", exc)
            return []

        seen: dict[str, SearchMatch] = {}
        for row in cursor.fetchall():
            sid = row[0]
            if sid in seen:
                continue
            seen[sid] = SearchMatch(
                session_id=row[0],
                title=row[1] or "(untitled)",
                started_at=self._format_time(row[2]),
                message_count=row[3],
                snippet=row[4],
                rank=row[5],
            )
            if len(seen) >= max_sessions:
                break

        return list(seen.values())

    def reindex_from_store(self, store_base_dir: Path) -> int:
        """Rebuild the entire index from file-based session store.

        Args:
            store_base_dir: Root directory of the SessionStore (contains session subdirs).

        Returns:
            Number of messages indexed.
        """
        if not store_base_dir.exists():
            return 0

        conn = self._get_conn()
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM sessions")
        try:
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
        except sqlite3.OperationalError:
            pass
        conn.commit()

        count = 0
        for session_dir in store_base_dir.iterdir():
            if not session_dir.is_dir():
                continue

            session_file = session_dir / "session.json"
            messages_file = session_dir / "messages.jsonl"

            if not session_file.exists():
                continue

            try:
                session_data = json.loads(session_file.read_text(encoding="utf-8"))
                sid = session_data.get("session_id", session_dir.name)
                title = session_data.get("title", "")

                try:
                    ts = datetime.fromisoformat(session_data.get("created_at", "")).timestamp()
                except (ValueError, TypeError):
                    ts = time.time()

                self.index_session(sid, title, ts=ts)

                if messages_file.exists():
                    for line in messages_file.read_text(encoding="utf-8").strip().splitlines():
                        if not line.strip():
                            continue
                        try:
                            msg = json.loads(line)
                            role = msg.get("role", "")
                            content = msg.get("content", "")
                            if content and role in ("user", "assistant"):
                                self.index_message(sid, role, content)
                                count += 1
                        except json.JSONDecodeError:
                            continue
            except Exception as exc:
                logger.warning("Failed to index session %s: %s", session_dir.name, exc)

        return count

    @staticmethod
    def _format_time(epoch: float) -> str:
        """Format epoch timestamp to human-readable string."""
        try:
            return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            return "unknown"

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


import threading as _threading

_shared_index: Optional[SessionSearchIndex] = None
_shared_lock = _threading.Lock()


def get_shared_index() -> SessionSearchIndex:
    """Return a process-wide singleton SessionSearchIndex.

    Thread-safe via double-checked locking. Used by both
    SessionService (indexing) and SessionSearchTool (searching)
    so they share one SQLite connection.
    """
    global _shared_index
    if _shared_index is None:
        with _shared_lock:
            if _shared_index is None:
                _shared_index = SessionSearchIndex()
    return _shared_index
