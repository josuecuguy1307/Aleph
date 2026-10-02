"""
conftest.py — Shared fixtures for puppet-ai-core tests

Key design decisions:
- REAL catalog: tests use the actual finanzas catalog (no mocks of own pieces)
- ISOLATED accounts DB: tests use tmp_path SQLite, never touching production

Migración 2026-06-15: el validador PLANO (config_validator) y el agents-store
SQLite/JSONL fueron retirados. El path canónico (validador ANIDADO + Postgres)
se prueba en tests/phase1/. Estos tests legacy cubren catálogo, salud, espacios,
conexiones y cuentas — las piezas que SOBREVIVEN sobre el cliente legacy.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Resolve repo root and add platform dirs to path
REPO_ROOT = Path(__file__).resolve().parents[3]  # tests/ -> backend/ -> product/ -> puppet-ai/
PLATFORM_FLYWHEEL = REPO_ROOT / "platform" / "flywheel"
CATALOG_ROOT = REPO_ROOT / "catalog" / "templates"
BELT_FINANZAS = CATALOG_ROOT / "finanzas" / "belt-finanzas.mcp.json"


@pytest.fixture(scope="session", autouse=True)
def ensure_platform_on_path():
    """Add platform/flywheel to sys.path once for the session."""
    fw_str = str(PLATFORM_FLYWHEEL)
    if fw_str not in sys.path:
        sys.path.insert(0, fw_str)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """A temporary SQLite database path."""
    return tmp_path / "users_test.db"


@pytest.fixture
def tmp_espacios(tmp_path: Path) -> Path:
    """A temporary espacios root dir (never touches production data/espacios/)."""
    d = tmp_path / "espacios"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def tmp_vault(tmp_path: Path):
    """
    An isolated CredentialVault on tmp_path (never touches production vault.enc).
    Loaded by file path the same way main.py does — the backend doesn't assume
    platform is a package. Returns a real CredentialVault (Fernet-encrypted).
    """
    import importlib.util

    vault_py = REPO_ROOT / "platform" / "gates" / "vault.py"
    spec = importlib.util.spec_from_file_location("puppet_vault_test", vault_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    store_path = tmp_path / "vault.enc"
    return mod.CredentialVault(str(store_path), master_secret="test-master-secret-xyz")


class FakeSession:
    """
    Stub of platform/assembler/session.py:Session for tests. NEVER runs an LLM and
    NEVER boots a real MCP belt — it only records calls and exposes the same
    gate surface (.approve/.reject/.pending_approval) the backend consumes.

    A pending gate can be primed via prime_gate() so the aprobaciones endpoint has
    something real to resolve, all without inference.
    """

    def __init__(self, config: dict, events_path):
        self.config = config
        self.events_path = events_path
        self.sent = []
        self.approved = []
        self.rejected = []
        self._pending = None
        self.closed = False

    # --- surface the backend uses -------------------------------------------------
    @property
    def pending_approval(self):
        return self._pending

    def prime_gate(self, payload: dict) -> None:
        self._pending = payload

    def approve(self, reason: str = "") -> None:
        self.approved.append(reason)
        self._pending = None

    def reject(self, reason: str = "") -> None:
        self.rejected.append(reason)
        self._pending = None

    def send(self, message: str) -> str:
        # No LLM. Record only — the live loop is exercised by session.py's own tests.
        self.sent.append(message)
        return "[stub]"

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_session_factory():
    """
    Factory that returns FakeSession instances and keeps a registry so tests can
    reach the created session (e.g. to prime a pending gate). Signature matches the
    SessionFactory contract: (config, events_path) -> session.
    """
    created = {}

    def factory(config, events_path):
        sess = FakeSession(config, events_path)
        # key by events_path's parent name = espacio id
        created[Path(events_path).parent.name] = sess
        return sess

    factory.created = created  # type: ignore[attr-defined]
    return factory


@pytest.fixture
def client(tmp_db: Path, tmp_espacios: Path, tmp_vault, fake_session_factory):
    """Test client with isolated stores and a stubbed (no-LLM) session factory.

    NOTA migración 2026-06-15: el agents-store SQLite/JSONL y el flywheel-path del
    backend fueron retirados (el path canónico vive en /v1 sobre Postgres). El
    cliente legacy solo monta los stores que SOBREVIVEN: cuentas (tier-gating de
    /catalog), espacios y vault. Los endpoints /v1/* se prueban en tests/phase1/.
    """
    from app.main import (
        app,
        set_espacios_store, set_session_factory, set_vault, reset_stores,
    )

    from app.espacios import EspaciosStore

    reset_stores()

    set_espacios_store(EspaciosStore(tmp_espacios))
    set_vault(tmp_vault)  # isolated, never touches production vault.enc
    # Stub the session factory so /mensajes and /aprobaciones never run an LLM.
    set_session_factory(fake_session_factory)

    with TestClient(app) as c:
        yield c

    reset_stores()


@pytest.fixture
def stream_client(tmp_espacios: Path, fake_session_factory):
    """
    A dedicated client whose espacios router uses a tiny heartbeat and a finite
    idle limit so the SSE generator TERMINATES in tests (no hang, no LLM). It
    shares the same tmp espacios store as the main client via a local store.
    Returns (TestClient, EspaciosStore) so the test can seed a fixture events.jsonl.
    """
    from fastapi import FastAPI
    from app.espacios import (
        EspaciosStore, SessionManager, build_espacios_router,
    )

    store = EspaciosStore(tmp_espacios)
    manager = SessionManager(factory=fake_session_factory)

    def _no_arrancador(nicho, arrancador_id):
        return None

    test_app = FastAPI()
    test_app.include_router(
        build_espacios_router(
            get_store=lambda: store,
            get_manager=lambda: manager,
            load_arrancador_config=_no_arrancador,
            heartbeat_s=0.01,        # fast heartbeats so the test runs quickly
            stream_idle_limit=2,     # close after 2 idle cycles → generator ends
        )
    )
    with TestClient(test_app) as c:
        yield c, store
