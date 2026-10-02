"""
test_t3_registry_down.py — REQUISITO C (T-3): el registro caído JAMÁS se muestra como
"no existe" / lista vacía. Prueba la cadena honesta completa en sus 3 capas:

  1. RESOLVER   (platform/inspection/mcp_resolver.py): registro caído + sin cache →
                 RegistryUnavailable (tipo DISTINTO), NO NotFound.
  2. DISPATCH   (app/phase1/dispatch_router.py):
                 · _resolve_decision → _Decision(found=False, registry_down=True, error=True)
                 · el stream SSE emite `resolver.registry_down` + `cerrado{path:registry_down}`
                   y CORTA — nunca `dispatch.forjando` (cero auto-construcción a ciegas).
  3. RESOLVE    (app/phase1/resolve_router.py): GET /v1/resolve/preview → 503
                 `registry_unreachable` (reintentá), NUNCA 404 `no_encontrado`.

CONTRASTE (para probar que NO rompimos el miss legítimo):
  · registro VIVO sin candidatos → NotFound / miss / 404 → SÍ ofrece construcción de MCP.

El registro público se MOCKEA (RegistryError vs []): cero red, determinista.
"""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# platform en path para `from inspection import ...` (dispatch_router lo hace al importarse,
# pero los unit-tests tocan el módulo directo antes de eso).
_REPO = Path(__file__).resolve().parents[4]
_PLATFORM = _REPO / "platform"
for p in (str(_PLATFORM), str(_REPO / "product" / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from inspection import mcp_registry, mcp_resolver  # noqa: E402
from app.phase1.dispatch_router import _resolve_decision, build_dispatch_router  # noqa: E402
from app.phase1.resolve_router import build_resolve_router  # noqa: E402


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """Aísla del rate-limiter de dispatch, que es PERSISTENTE (keyed por subject 'anon',
    compartido entre corridas de pytest) — no es lo que este archivo prueba, y si no se
    bypassa, varias corridas acumulan hits y disparan 429 espurios."""
    try:
        from safety import rate_limit
        monkeypatch.setattr(rate_limit, "check_and_consume", lambda *a, **k: (True, {}))
    except Exception:
        pass


def _kill_registry(monkeypatch):
    """El registro público NO responde (timeout) y no hay cache ni curado."""
    def _boom(*a, **k):
        raise mcp_registry.RegistryError("registro MCP inalcanzable: timed out")
    monkeypatch.setattr(mcp_registry, "search", _boom)
    monkeypatch.setattr(mcp_registry, "curated_entry", lambda *a, **k: None)
    monkeypatch.setattr(mcp_registry, "cache_get", lambda *a, **k: None)


def _alive_but_empty(monkeypatch):
    """El registro RESPONDE pero no hay candidatos (miss legítimo)."""
    monkeypatch.setattr(mcp_registry, "search", lambda *a, **k: [])
    monkeypatch.setattr(mcp_registry, "curated_entry", lambda *a, **k: None)
    monkeypatch.setattr(mcp_registry, "cache_get", lambda *a, **k: None)


def _cache_rec(vendor_kind="dns"):
    """Una resolución previa VALIDADA guardada en cache (como la persiste cache_put)."""
    return {"server_name": "com.stripe/mcp", "vendor_kind": vendor_kind, "source": "registry",
            "spec": {"transport": "http", "url": "https://mcp.stripe.com",
                     "needs_credential": True, "header_name": "Authorization",
                     "header_template": "Bearer {key}"},
            "stale": False}


def _kill_registry_with_cache(monkeypatch, vendor_kind="dns"):
    """Registro caído PERO con cache tibia (degradación graceful)."""
    def _boom(*a, **k):
        raise mcp_registry.RegistryError("registro MCP inalcanzable: timed out")
    monkeypatch.setattr(mcp_registry, "search", _boom)
    monkeypatch.setattr(mcp_registry, "curated_entry", lambda *a, **k: None)
    monkeypatch.setattr(mcp_registry, "cache_get", lambda *a, **k: _cache_rec(vendor_kind))


# ── CAPA 1 · RESOLVER ────────────────────────────────────────────────────────────

def test_registry_down_raises_registry_unavailable_not_notfound(monkeypatch):
    _kill_registry(monkeypatch)
    with pytest.raises(mcp_resolver.RegistryUnavailable):
        mcp_resolver.resolve_service("stripe")
    # y CRUCIAL: no es un NotFound (que afirmaría inexistencia)
    try:
        mcp_resolver.resolve_service("stripe")
    except mcp_resolver.RegistryUnavailable as e:
        assert not isinstance(e, mcp_resolver.NotFound), \
            "registro caído NO debe ser NotFound (mentiría: 'no existe')"


def test_legit_miss_raises_notfound(monkeypatch):
    _alive_but_empty(monkeypatch)
    with pytest.raises(mcp_resolver.NotFound):
        mcp_resolver.resolve_service("servicio-que-no-existe-xyz")


# ── CAPA 2 · DISPATCH · decisión ──────────────────────────────────────────────────

def test_decision_registry_down_sets_flag(monkeypatch):
    _kill_registry(monkeypatch)
    d = _resolve_decision("stripe", seed_candidates=None, seed_spec=None, seed_enabled=False)
    assert d.found is False
    assert d.registry_down is True, "registro caído debe marcar registry_down"
    assert d.error is True


def test_decision_legit_miss_no_registry_down(monkeypatch):
    _alive_but_empty(monkeypatch)
    d = _resolve_decision("servicio-que-no-existe-xyz",
                          seed_candidates=None, seed_spec=None, seed_enabled=False)
    assert d.found is False
    assert d.registry_down is False, "un miss legítimo NO es registro caído"


# ── CAPA 2 · DISPATCH · stream SSE ─────────────────────────────────────────────────

def _dispatch_client():
    app = FastAPI()
    app.include_router(build_dispatch_router(get_conn=None))
    return TestClient(app)


def test_stream_registry_down_stops_never_forges(monkeypatch):
    _kill_registry(monkeypatch)
    c = _dispatch_client()
    # damos `url` a propósito: aún con URL, un registro caído NO debe caer a construcción.
    r = c.post("/v1/inspect/dispatch",
               json={"service": "stripe", "url": "https://api.stripe.com", "credential": "x"})
    body = r.text
    assert "resolver.registry_down" in body
    assert '"path": "registry_down"' in body or '"path":"registry_down"' in body
    assert '"retry": true' in body or '"retry":true' in body
    # CERO auto-construcción a ciegas:
    assert "dispatch.forjando" not in body, "registro caído NO debe forjar"
    assert "mcp.forjado" not in body
    # y NO se disfraza de miss legítimo:
    assert "resolver.miss" not in body


def test_stream_legit_miss_offers_construction(monkeypatch):
    # [Step 5 · P7] Este test se escribió cuando el muro de construcción venía APAGADO
    # por default: hacía un dispatch ANÓNIMO y afirmaba que se ofrece construir. Con el
    # muro activo por default, un anónimo recibe `dispatch.denied` — que es lo CORRECTO.
    # Lo que este test cubre es el ruteo del resolver (miss legítimo ≠ registro caído),
    # no la frontera de tier; así que se pide el opt-out y se prueba lo que vino a probar.
    # La frontera premium tiene sus propios tests: test_construction_premium_gate.py y
    # test_muros_default_on.py.
    monkeypatch.setenv("PUPPET_ENFORCE_MCP_CONSTRUCTION", "0")
    _alive_but_empty(monkeypatch)

    async def _fake_forge_stream(**kwargs):
        # stub: probamos que el stream LLEGA a construir, sin correr el Motor B real.
        from app.phase1.forge_router import _sse
        yield _sse({"type": "cerrado", "path": "forged", "ok": True})

    # [Casa 2 · Fase 4 · 4.2.a] run_forge_stream ya NO se importa top-level en dispatch_router
    # (es FORGE → import LAZY en la rama miss, para poder EXCLUIR forge_router del cliente). Se
    # parchea en su ORIGEN (forge_router); el `from forge_router import run_forge_stream` de la
    # rama miss levanta el fake.
    monkeypatch.setattr("app.phase1.forge_router.run_forge_stream", _fake_forge_stream)
    c = _dispatch_client()
    r = c.post("/v1/inspect/dispatch",
               json={"service": "servicio-que-no-existe-xyz",
                     "url": "https://mi-api.example.com", "credential": "x", "forma": "token",
                     "auth_in": "header"})
    body = r.text
    assert "resolver.miss" in body, "miss legítimo debe emitir resolver.miss"
    assert "registry_down" not in body
    assert "dispatch.forjando" in body, "miss legítimo SÍ ofrece construcción de MCP"


# ── CAPA 3 · RESOLVE · /v1/resolve/preview ────────────────────────────────────────

def _resolve_client():
    app = FastAPI()
    app.include_router(build_resolve_router(get_conn=None))
    return TestClient(app)


def test_preview_registry_down_503_not_404(monkeypatch):
    _kill_registry(monkeypatch)
    c = _resolve_client()
    r = c.get("/v1/resolve/preview", params={"service": "stripe"})
    assert r.status_code == 503, "registro caído → 503 registry_unreachable, NUNCA 404"
    body = r.json()
    assert body["detail"]["error"] == "registry_unreachable"
    assert body["detail"].get("retry") is True


def test_preview_legit_miss_404(monkeypatch):
    _alive_but_empty(monkeypatch)
    c = _resolve_client()
    r = c.get("/v1/resolve/preview", params={"service": "servicio-que-no-existe-xyz"})
    assert r.status_code == 404, "miss legítimo → 404 no_encontrado (sí ofrece construir)"
    assert r.json()["detail"]["error"] == "no_encontrado"


# ── CACHE durante outage · degradación graceful HONESTA (residual que cerró PR-1) ─────────

def test_registry_down_warm_cache_equips_preserves_vendor_kind(monkeypatch):
    """Registro caído + cache tibia → found=True, from_cache, vendor_kind ORIGINAL (no 'cache')."""
    _kill_registry_with_cache(monkeypatch, vendor_kind="dns")
    r = mcp_resolver.resolve_service("stripe")
    assert r["found"] is True
    assert r["from_cache"] is True
    assert r["registry_down"] is True
    assert r["vendor_kind"] == "dns", "el vendor_kind original se preserva (antes se pisaba con 'cache')"
    assert r["source"] == "registry"


def test_decision_registry_down_verified_cache_is_confiable(monkeypatch):
    """Cache VERIFICADA durante outage → equipar de cache (confiable), NO forjar."""
    _kill_registry_with_cache(monkeypatch, vendor_kind="dns")
    d = _resolve_decision("stripe", seed_candidates=None, seed_spec=None, seed_enabled=False)
    assert d.found is True and d.confiable is True
    assert d.from_cache is True


def test_decision_registry_down_unverified_cache_is_registry_down_not_forge(monkeypatch):
    """Cache NO verificada durante outage → registry_down honesto, NUNCA construcción a ciegas."""
    _kill_registry_with_cache(monkeypatch, vendor_kind="unknown")
    d = _resolve_decision("stripe", seed_candidates=None, seed_spec=None, seed_enabled=False)
    assert d.found is False
    assert d.registry_down is True, "cache no verificada + outage → registry_down, no forja"
    assert d.from_cache is True


def test_stream_registry_down_cache_equips_never_forges(monkeypatch):
    """El stream equipa de cache (resolver.encontrado from_cache) y NO forja."""
    _kill_registry_with_cache(monkeypatch, vendor_kind="dns")

    def _fake_equip(decision, body, principal, user_id, *, get_conn=None):
        # stub: no arrancamos un MCP real; probamos el ORDEN del stream (equipa, no forja).
        return ({"tools": [{"name": "charge", "description": "cobra"}]},
                {"server": decision.server_name, "tools": ["charge"],
                 "belt_ref": "x", "registered": False})

    monkeypatch.setattr("app.phase1.dispatch_router._equip_found", _fake_equip)
    c = _dispatch_client()
    r = c.post("/v1/inspect/dispatch", json={"service": "stripe", "credential": "x"})
    body = r.text
    assert "resolver.encontrado" in body
    assert '"from_cache": true' in body or '"from_cache":true' in body
    assert "mcp.equipado" in body
    assert "dispatch.forjando" not in body, "cache verificada → equipa, NO forja"
    assert "resolver.registry_down" not in body, "es un found (from_cache), no el corte"


def test_preview_registry_down_warm_cache_200_from_cache(monkeypatch):
    """preview con cache tibia → 200 found+from_cache (no 404 ni 503): degradación honesta."""
    _kill_registry_with_cache(monkeypatch, vendor_kind="dns")
    c = _resolve_client()
    r = c.get("/v1/resolve/preview", params={"service": "stripe"})
    assert r.status_code == 200
    b = r.json()
    assert b["found"] is True
    assert b["from_cache"] is True
    assert b["registry_down"] is True
    assert b["vendor_kind"] == "dns"


def test_equip_from_cache_always_revalidates_live(monkeypatch):
    """SEGURIDAD (anti-impostor intacto): equipar de cache SIEMPRE revalida el server MCP vivo
    (validate_live) antes de materializar la pieza — el registro caído no relaja el candado."""
    from types import SimpleNamespace
    from app.phase1 import dispatch_router as DR
    called = {}

    def _spy_validate(spec, secret, *a, **k):
        called["validate_live"] = True
        return {"tools": [{"name": "charge", "description": "cobra"}], "server_info": {}}

    monkeypatch.setattr(mcp_resolver, "validate_live", _spy_validate)
    monkeypatch.setattr(mcp_resolver, "equip_resolved",
                        lambda *a, **k: {"server": "com.stripe/mcp", "tools": ["charge"],
                                         "belt_ref": "x", "registered": False})
    dec = DR._Decision(found=True, confiable=True, server_name="com.stripe/mcp",
                       spec={"transport": "http", "url": "https://mcp.stripe.com",
                             "needs_credential": True, "header_name": "Authorization",
                             "header_template": "Bearer {key}"},
                       vendor_kind="dns", source="registry", from_cache=True)
    body = SimpleNamespace(credential="x", service="stripe", puppet_id=None)
    probe, equipped = DR._equip_found(dec, body, object(), None, get_conn=None)
    assert called.get("validate_live") is True, "equipar de cache DEBE revalidar el server vivo"
    assert equipped["server"] == "com.stripe/mcp"
