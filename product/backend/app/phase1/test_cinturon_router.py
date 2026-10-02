"""test_cinturon_router.py — la ruta que dispara el calentado. Llama, no decide.

  1. sin sesión no calienta nada (anti-IDOR: el owner sale de la sesión, no del body)
  2. UN calentado por agente: el segundo llamado concurrente devuelve `en_curso`
  3. el guard se limpia SIEMPRE — si no, el agente no podría calentarse nunca más
  4. un fallo del calentado NO queda mudo: 500 con causa
  5. el resumen viaja entero, incluido lo que quedó sobre el tope

Correr: pytest product/backend/app/phase1/test_cinturon_router.py -v
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[4]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.phase1 import cinturon_router as CRT  # noqa: E402
from app.phase1 import motor_verdad as MV  # noqa: E402


def _app(get_conn=lambda: None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    a = FastAPI()
    a.include_router(CRT.build_cinturon_router(get_conn=get_conn))
    return TestClient(a)


@pytest.fixture(autouse=True)
def _limpio():
    CRT._EN_CURSO.clear()
    yield
    CRT._EN_CURSO.clear()


def _calentar_falso(monkeypatch, fn):
    from app.phase1 import calentar_cinturon as CAL
    monkeypatch.setattr(CAL, "calentar", fn)


RESUMEN = {"piezas": [{"server": "exa", "conexion": "viva", "causa": None,
                       "credencial": "verde", "era": "handshake", "tool": "web_search_exa"}],
           "apagadas": ["markitdown"], "sin_registro": ["ajena"],
           "sin_medir": ["s13", "s14"], "ms": 1234}


def test_sin_sesion_no_calienta(monkeypatch):
    """El owner sale de la SESIÓN, jamás del body: si no, cualquiera calienta el agente
    de cualquiera y le gasta el rate limit."""
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: None)
    assert _app().post("/v1/cinturon/calentar", json={"puppet_id": "p"}).status_code == 401


def test_sin_puppet_id_es_422(monkeypatch):
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: "u")
    assert _app().post("/v1/cinturon/calentar", json={}).status_code == 422
    assert _app().post("/v1/cinturon/calentar", json={"puppet_id": "  "}).status_code == 422


def test_el_resumen_viaja_entero(monkeypatch):
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: "u")
    _calentar_falso(monkeypatch, lambda pid, **k: dict(RESUMEN))
    d = _app().post("/v1/cinturon/calentar", json={"puppet_id": "p"}).json()
    assert d["ok"] is True and d["en_curso"] is False
    assert d["piezas"][0]["server"] == "exa"
    assert d["apagadas"] == ["markitdown"], "la lápida se reporta"
    assert d["sin_medir"] == ["s13", "s14"], "lo que quedó sobre el tope se NOMBRA"
    assert d["sin_registro"] == ["ajena"]


def test_UN_calentado_por_agente(monkeypatch):
    """Abrir dos veces rápido el mismo agente spawnearía las mismas piezas en paralelo:
    el doble de procesos MCP, el doble de rate limit y dos escrituras compitiendo por la
    misma fila. El segundo no espera ni falla — el primero ya está haciendo eso."""
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: "u")
    entro = threading.Event()
    seguir = threading.Event()
    veces = []

    def _lento(pid, **k):
        veces.append(pid)
        entro.set()
        seguir.wait(timeout=5)
        return dict(RESUMEN)

    _calentar_falso(monkeypatch, _lento)
    c = _app()
    r1 = {}
    t = threading.Thread(target=lambda: r1.update(
        c.post("/v1/cinturon/calentar", json={"puppet_id": "p"}).json()))
    t.start()
    assert entro.wait(timeout=5), "el primero no arrancó"
    r2 = c.post("/v1/cinturon/calentar", json={"puppet_id": "p"}).json()
    seguir.set(); t.join(timeout=5)

    assert r2["en_curso"] is True, "el segundo tenía que rebotar"
    assert veces == ["p"], "calentar corrió UNA sola vez"
    assert r1.get("en_curso") is False


def test_otro_agente_SI_puede_calentar_en_paralelo(monkeypatch):
    """El guard es por puppet_id, no global: dos agentes distintos no se estorban."""
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: "u")
    _calentar_falso(monkeypatch, lambda pid, **k: dict(RESUMEN))
    CRT._EN_CURSO.add("otro")
    d = _app().post("/v1/cinturon/calentar", json={"puppet_id": "p"}).json()
    assert d["en_curso"] is False


def test_el_guard_se_limpia_aunque_calentar_reviente(monkeypatch):
    """Si no se limpiara, ese agente no podría calentarse NUNCA MÁS en este proceso."""
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: "u")
    def _revienta(pid, **k):
        raise RuntimeError("se cayó")
    _calentar_falso(monkeypatch, _revienta)
    r = _app().post("/v1/cinturon/calentar", json={"puppet_id": "p"})
    assert r.status_code == 500 and "no pude calentar" in r.json()["detail"]
    assert "p" not in CRT._EN_CURSO, "el guard quedó sucio"


def test_el_fallo_NO_queda_mudo(monkeypatch):
    """FALLO VISIBLE: la Sala muestra el aviso con esta causa y el agente sigue usable."""
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: "u")
    _calentar_falso(monkeypatch, lambda pid, **k: (_ for _ in ()).throw(ValueError("x")))
    d = _app().post("/v1/cinturon/calentar", json={"puppet_id": "p"}).json()
    assert "ValueError" in d["detail"]
