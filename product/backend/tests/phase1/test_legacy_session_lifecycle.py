from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "product" / "backend"
PLATFORM_DB = ROOT / "platform" / "db"
for path in (BACKEND, PLATFORM_DB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import sqlite_db  # noqa: E402
from app.phase1 import repo  # noqa: E402
from app.phase1.router import build_phase1_router  # noqa: E402


@pytest.fixture()
def session_db(tmp_path, monkeypatch):
    path = tmp_path / "sessions.sqlite"
    conn = sqlite_db.conectar(str(path))
    sqlite_db.crear_schema(conn)
    fernet = Fernet(Fernet.generate_key())

    monkeypatch.setattr(repo, "get_conn", lambda dbname=None: sqlite_db.conectar(str(path)))
    monkeypatch.setattr(repo, "encrypt_secret", lambda plain: fernet.encrypt(plain.encode()))
    monkeypatch.setattr(
        repo, "decrypt_secret",
        lambda token, ttl=None: fernet.decrypt(token, ttl=ttl).decode(),
    )
    monkeypatch.setenv("ALEPH_LEGACY_SESSION_TTL_SECONDS", "60")
    yield conn, fernet
    conn.close()


def _user(conn, email: str, password: str = "secreto-inicial") -> str:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
            (email, repo.hash_password(password)),
        )
        user_id = str(cur.fetchone()[0])
    conn.commit()
    return user_id


def test_password_change_revokes_old_token_and_new_login_still_works(session_db):
    conn, _ = session_db
    user_id = _user(conn, "password@example.test")
    stolen = repo.mint_session(user_id, conn=conn)
    assert repo.session_owner(stolen) == user_id

    with pytest.raises(ValueError, match="bad_current"):
        repo.change_password(conn, user_id, "incorrecta", "otro-secreto")
    assert repo.session_owner(stolen) == user_id

    repo.change_password(conn, user_id, "secreto-inicial", "secreto-nuevo")

    assert repo.session_owner(stolen) is None
    assert repo.login_user(conn, "password@example.test", "secreto-inicial") is None
    assert repo.login_user(conn, "password@example.test", "secreto-nuevo")["id"] == user_id
    replacement = repo.mint_session(user_id, conn=conn)
    assert repo.session_owner(replacement) == user_id


def test_logout_revokes_generation_and_expired_or_old_generation_tokens_fail(session_db):
    conn, fernet = session_db
    user_id = _user(conn, "logout@example.test")
    active = repo.mint_session(user_id, conn=conn)

    assert repo.revoke_legacy_session(active) is True
    assert repo.session_owner(active) is None

    current = repo.mint_session(user_id, conn=conn)
    assert repo.session_owner(current) == user_id
    payload = repo._SESSION_PREFIX + '["' + user_id + '",1]'
    expired = fernet.encrypt_at_time(payload.encode(), int(time.time()) - 61).decode()
    assert repo.session_owner(expired) is None


def test_deployed_v1_token_has_bounded_compatibility_then_is_revoked(session_db):
    conn, fernet = session_db
    user_id = _user(conn, "legacy@example.test")
    deployed_v1 = fernet.encrypt((repo._SESSION_PREFIX_V1 + user_id).encode()).decode()

    assert repo.session_owner(deployed_v1) == user_id
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET session_version = session_version + 1 WHERE id = %s",
            (user_id,),
        )
    conn.commit()
    assert repo.session_owner(deployed_v1) is None


def test_missing_user_database_failure_and_malformed_payload_fail_closed(session_db, monkeypatch):
    conn, fernet = session_db
    missing = fernet.encrypt((repo._SESSION_PREFIX + '["missing",0]').encode()).decode()
    malformed = fernet.encrypt((repo._SESSION_PREFIX + '{"id":"x"}').encode()).decode()
    assert repo.session_owner(missing) is None
    assert repo.session_owner(malformed) is None

    user_id = _user(conn, "dbdown@example.test")
    token = repo.mint_session(user_id, conn=conn)
    monkeypatch.setattr(repo, "get_conn", lambda dbname=None: (_ for _ in ()).throw(RuntimeError("down")))
    assert repo.session_owner(token) is None


def test_http_password_rotation_and_logout_reject_replayed_tokens(
        session_db, tmp_path, monkeypatch):
    monkeypatch.setenv("PUPPET_ALLOW_PASSWORD_AUTH", "1")
    app = FastAPI()
    app.include_router(build_phase1_router(
        get_conn=repo.get_conn, events_dir=lambda: tmp_path / "events"))
    client = TestClient(app)

    registered = client.post("/v1/auth/register", json={
        "email": "http@example.test", "password": "secreto-inicial",
    })
    assert registered.status_code == 201
    user = registered.json()
    stolen = user["session_token"]
    headers = {"Authorization": "Bearer " + stolen}

    changed = client.post(f"/v1/users/{user['id']}/password", headers=headers, json={
        "current_password": "secreto-inicial", "new_password": "secreto-nuevo",
    })
    assert changed.status_code == 200
    replacement = changed.json()["session_token"]

    assert client.get(f"/v1/users/{user['id']}/puppets", headers=headers).status_code == 401
    replacement_headers = {"Authorization": "Bearer " + replacement}
    assert client.get(
        f"/v1/users/{user['id']}/puppets", headers=replacement_headers).status_code == 200

    assert client.post("/v1/auth/logout", headers=replacement_headers).status_code == 204
    assert client.get(
        f"/v1/users/{user['id']}/puppets", headers=replacement_headers).status_code == 401
