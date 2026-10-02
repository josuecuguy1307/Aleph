"""Varas quirúrgicas de Sala: lock fence, WAL e idempotencia del transcript."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "product" / "backend"
DB_DIR = ROOT / "platform" / "db"
for path in (str(BACKEND), str(DB_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import sqlite_db  # noqa: E402
from app.phase1 import chats_repo, executor, knowledge_store, repo, router  # noqa: E402


def _seed_chat(conn) -> tuple[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("sala-e2e@local.test",),
        )
        user_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO chats (user_id, title) VALUES (%s,'') RETURNING id",
            (user_id,),
        )
        chat_id = cur.fetchone()[0]
    conn.commit()
    return str(user_id), str(chat_id)


def test_chat_gate_projection_is_idempotent_by_client_turn(tmp_path):
    db = str(tmp_path / "aleph.db")
    sqlite_db.asegurar_schema(db)
    conn = sqlite_db.conectar(db)
    try:
        _, chat_id = _seed_chat(conn)
        turn_id = "sala-double-submit-1"
        first = chats_repo.append_message(
            conn, chat_id=chat_id, role="user", content="Dame el ejemplo",
            client_turn_id=turn_id,
        )
        replay = chats_repo.append_message(
            conn, chat_id=chat_id, role="user", content="Dame el ejemplo",
            client_turn_id=turn_id,
        )
        chats_repo.append_message(
            conn, chat_id=chat_id, role="agent", content="parcial",
            client_turn_id=turn_id,
        )
        chats_repo.append_message(
            conn, chat_id=chat_id, role="agent", content="respuesta final",
            client_turn_id=turn_id,
        )

        transcript = chats_repo.list_messages(conn, chat_id)
        assert first["id"] == replay["id"]
        assert [(m["role"], m["content"]) for m in transcript] == [
            ("user", "Dame el ejemplo"),
            ("agent", "respuesta final"),
        ]
        assert chats_repo.build_history_block(
            conn, chat_id, exclude_client_turn_id=turn_id
        ) == ""
    finally:
        conn.close()
        sqlite_db.cerrar_almacen()


def test_existing_v1_client_db_migrates_turn_id_and_unique_index(tmp_path):
    db = tmp_path / "aleph-v1.db"
    raw = sqlite3.connect(db)
    raw.executescript((DB_DIR / "schema_sqlite.sql").read_text(encoding="utf-8"))
    raw.execute("DROP INDEX uq_chat_messages_turn_role")
    raw.execute("ALTER TABLE chat_messages DROP COLUMN client_turn_id")
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    raw.close()

    info = sqlite_db.asegurar_schema(str(db))
    assert info["version"] == sqlite_db.VERSION_SCHEMA_CLIENTE
    check = sqlite3.connect(db)
    try:
        cols = {r[1] for r in check.execute("PRAGMA table_info(chat_messages)")}
        indexes = {r[1] for r in check.execute("PRAGMA index_list(chat_messages)")}
    finally:
        check.close()
        sqlite_db.cerrar_almacen()
    assert "client_turn_id" in cols
    assert "uq_chat_messages_turn_role" in indexes


def test_preversioned_v0_client_db_with_old_chat_table_is_healed(tmp_path):
    db = tmp_path / "aleph-v0.db"
    raw = sqlite3.connect(db)
    raw.executescript((DB_DIR / "schema_sqlite.sql").read_text(encoding="utf-8"))
    raw.execute("DROP INDEX uq_chat_messages_turn_role")
    raw.execute("ALTER TABLE chat_messages DROP COLUMN client_turn_id")
    raw.execute("PRAGMA user_version = 0")
    raw.commit()
    raw.close()

    info = sqlite_db.asegurar_schema(str(db))
    assert info["version"] == sqlite_db.VERSION_SCHEMA_CLIENTE
    check = sqlite3.connect(db)
    try:
        cols = {r[1] for r in check.execute("PRAGMA table_info(chat_messages)")}
        indexes = {r[1] for r in check.execute("PRAGMA index_list(chat_messages)")}
    finally:
        check.close()
        sqlite_db.cerrar_almacen()
    assert "client_turn_id" in cols
    assert "uq_chat_messages_turn_role" in indexes


def test_calibracion_roja_lock_largo_y_verde_con_fence(tmp_path):
    """Sin la frontera, el segundo writer falla; con ella entra de inmediato."""
    db = tmp_path / "fence.db"
    holder = sqlite3.connect(db)
    holder.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
    holder.commit()
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("INSERT INTO t(value) VALUES ('holder')")

    blocked = sqlite3.connect(db, timeout=0.05)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        blocked.execute("INSERT INTO t(value) VALUES ('red')")
    blocked.close()

    executor._commit_before_external_io(holder, "calibration")
    writer = sqlite3.connect(db, timeout=0.05)
    writer.execute("INSERT INTO t(value) VALUES ('green')")
    writer.commit()
    writer.close()
    holder.close()

    check = sqlite3.connect(db)
    try:
        assert [r[0] for r in check.execute("SELECT value FROM t ORDER BY id")] == [
            "holder", "green"
        ]
    finally:
        check.close()


def _sala_api(db: str) -> TestClient:
    app = FastAPI()
    app.include_router(router.build_phase1_router(
        get_conn=lambda: sqlite_db.conectar(db, timeout=0.05),
        events_dir=lambda: Path(db).parent / "events",
    ))
    return TestClient(app)


def test_chat_gate_replay_never_executes_model_twice(tmp_path, monkeypatch):
    db = str(tmp_path / "aleph.db")
    sqlite_db.asegurar_schema(db)
    conn = sqlite_db.conectar(db)
    try:
        user_id, chat_id = _seed_chat(conn)
        chats_repo.append_message(
            conn, chat_id=chat_id, role="user", content="una sola vez",
            client_turn_id="turn-stable",
        )
    finally:
        conn.close()

    monkeypatch.setattr(repo, "session_owner", lambda _token: user_id)
    called = {"runs": 0}

    def forbidden_run(*_args, **_kwargs):
        called["runs"] += 1
        raise AssertionError("un replay no puede llegar al modelo")

    monkeypatch.setattr(executor, "run_puppet_e2e", forbidden_run)
    body = {
        "chat_id": chat_id, "client_turn_id": "turn-stable",
        "prompt": "una sola vez", "recipe": {"schema_version": "v1"},
    }
    with _sala_api(db) as client:
        live = client.post("/v1/puppets/run", json=body,
                           headers={"Authorization": "Bearer fixture"})
        assert live.status_code == 409
        assert live.json()["detail"]["error"] == "turn_in_progress"

        conn = sqlite_db.conectar(db)
        try:
            chats_repo.append_message(
                conn, chat_id=chat_id, role="agent", content="respuesta estable",
                client_turn_id="turn-stable",
            )
        finally:
            conn.close()

        closed = client.post("/v1/puppets/run", json=body,
                             headers={"Authorization": "Bearer fixture"})
        assert closed.status_code == 201
        assert closed.json()["answer"] == "respuesta estable"
        assert closed.json()["idempotent_replay"] is True

    assert called["runs"] == 0
    conn = sqlite_db.conectar(db)
    try:
        transcript = chats_repo.list_messages(conn, chat_id)
        assert [m["role"] for m in transcript] == ["user", "agent"]
    finally:
        conn.close()
        sqlite_db.cerrar_almacen()


def test_chat_gate_reports_database_locked_with_typed_path(tmp_path, monkeypatch):
    db = str(tmp_path / "aleph.db")
    sqlite_db.asegurar_schema(db)
    conn = sqlite_db.conectar(db)
    try:
        user_id, chat_id = _seed_chat(conn)
    finally:
        conn.close()
    monkeypatch.setattr(repo, "session_owner", lambda _token: user_id)
    # El bootstrap dejó una conexión de 30 s en el pool. La calibración usa 50 ms
    # deliberadamente para probar el mismo empate sin cobrar 30 s a la suite.
    sqlite_db.cerrar_almacen()

    holder = sqlite3.connect(db)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("UPDATE chats SET title='holder' WHERE id=?", (chat_id,))
    try:
        with _sala_api(db) as client:
            response = client.post("/v1/puppets/run", json={
                "chat_id": chat_id, "client_turn_id": "turn-locked",
                "prompt": "no aceptes a medias",
                "recipe": {"schema_version": "v1"},
            }, headers={"Authorization": "Bearer fixture"})
        assert response.status_code == 503
        assert response.json()["detail"]["error"] == "database_locked"
        assert "vuelve a intentarlo" in response.json()["detail"]["detail"]
    finally:
        holder.rollback()
        holder.close()
        sqlite_db.cerrar_almacen()


def test_both_local_sqlite_stores_use_wal_and_30s_busy_timeout(tmp_path):
    main_db = str(tmp_path / "aleph.db")
    main = sqlite_db.conectar(main_db)
    try:
        assert main.raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert main.raw.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    finally:
        main.close()
        sqlite_db.cerrar_almacen()

    store = knowledge_store.SelfHostedStore(str(tmp_path / "rag"), "composition-1")
    with store._conn() as knowledge:
        assert knowledge.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert knowledge.execute("PRAGMA busy_timeout").fetchone()[0] == 30000


def test_sala_client_contract_is_wired_in_source():
    sala = (ROOT / "product/app/design/sala/sala.html").read_text(encoding="utf-8")
    chat = (ROOT / "product/app/design/chat/aleph-chat.js").read_text(encoding="utf-8")
    shell = (
        ROOT / "deploy/fase4/aleph-shell/src-tauri/src/lib.rs"
    ).read_text(encoding="utf-8")

    assert "var API_TIMEOUT_MS=45000" in sala
    assert "client_turn_id:ST.clientTurnId||undefined" in sala
    assert 'introChrome: true' in sala and 'showAiName: false' in sala
    assert ".chat-h #agentName{ display:none; }" in sala
    assert 'class="hero-sub"' not in sala
    assert 'id="agentSub"' not in sala
    assert "r.collapse(false)" in sala
    assert "_chatHydration=rehydrateChat()" in sala
    assert "Promise.resolve(_chatHydration)" in sala
    assert "deep-chat-temporary-message ac-noop" in chat
    assert "discardLastUser" in chat
    assert 'data-ac-discarded' in chat
    assert 'box.insertBefore(intro, box.firstChild)' in chat
    assert 'dir.join("Aleph.log")' in shell
    assert 'dir.join("Aleph.log.1")' in shell
    assert ".stdout(Stdio::from(stdout_file))" in shell
