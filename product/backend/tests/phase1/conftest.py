import os as _os
def pytest_configure(config):
    # [hallazgo #1] La suite corre con el opt-out de anon-v1 (los harnesses hacen
    # mutaciones anónimas). Los tests que prueban el RECHAZO del middleware lo apagan
    # con monkeypatch.delenv. Producción nunca setea esto → cerrado por default.
    _os.environ.setdefault("PUPPET_ALLOW_ANON_V1", "1")

"""
conftest.py — fixtures de los tests de Fase 1 (backend).

- Pone product/backend en sys.path para que `from app.phase1 import ...` resuelva,
  corriendo desde cualquier cwd (los threads resetean cwd).
- Una receta v1 anidada VÁLIDA de referencia (finanzas), reusable por los tests.
- Detección de la DB real puppet_ai: si no está, los tests marcados @pytest.mark.db
  se SALTAN (skip honesto) en vez de fallar — la evidencia DB se corre aparte.
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]  # tests/phase1 -> tests -> backend
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def valid_recipe() -> dict:
    """Receta v1 ANIDADA válida (finanzas), alineada con RECIPE-SCHEMA.md §2."""
    return {
        "schema_version": "v1",
        "meta": {"name": "Agente Finanzas", "nicho": "finanzas",
                 "descripcion": "analiza financials"},
        "model": {
            "primary": "gpt-oss-120b",
            "fallback": "llama-3.3-70b",
            "base_url": "http://127.0.0.1:4000/v1",
            "temperature": 0,
            "max_tokens": 2048,
            "max_turns": 8,
        },
        "belt": {
            "belt_ref": "catalog/belts/finanzas.md",
            "tool_filters": {
                "excel": ["apply_formula", "read_data_from_excel"],
                "secedgar": ["get_cik_by_ticker", "get_financials"],
            },
        },
        "framing": {"ref": "framing/finanzas.md", "inline": None},
        "rag": {"enabled": True, "mode": "manual", "dir": "rag/finanzas"},
        "keys": {
            "fred": {"byok_ref": "keys:fred"},
            "alpha_vantage": {"byok_ref": "keys:alpha_vantage"},
        },
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }


def _db_available() -> bool:
    try:
        from app.phase1 import repo
        conn = repo.get_conn()
        conn.close()
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()


@pytest.fixture
def db_conn():
    """Conexión real a puppet_ai; salta el test si la DB no está disponible."""
    if not DB_AVAILABLE:
        pytest.skip("Postgres puppet_ai no disponible — evidencia DB se corre aparte")
    from app.phase1 import repo
    conn = repo.get_conn()
    yield conn
    conn.close()
