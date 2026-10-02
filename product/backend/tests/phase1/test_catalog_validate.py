"""
test_catalog_validate.py — PR-3: GET /v1/catalog/validate (RESOLVER-AL-ELEGIR).

Prueba el clasificador de confianza de 3 valores (mcp_resolver.classify_service) y el endpoint que
lo expone, con fixtures DETERMINISTAS (monkeypatch de mcp_registry.search / curated_entry / cache_get
/ get_by_name y, donde hace falta, mcp_matcher.best_match):

  · confiable — namespace DNS verificado / GitHub org verificado / curado.manual.
  · dudoso    — candidatos existen pero ninguno con ownership verificado (caso real: no pasan el
                umbral estricto 0.80 sin señal de vendor) + rama found-pero-no-verificado (forzada).
  · nada      — el registro no devuelve candidatos → construye un MCP.
  · [T-3] registro caído → registry_status:"unreachable" + verdict:null (o confiable-from-cache),
    HTTP 200, NUNCA verdict:"nada" ni 404 (inalcanzable ≠ inexistente).
  · anti-impostor al elegir: picked_is_trusted False cuando el server elegido ≠ el oficial verificado.
"""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_REPO = Path(__file__).resolve().parents[4]
for p in (str(_REPO / "platform"), str(_REPO / "product" / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from inspection import mcp_matcher, mcp_registry, mcp_resolver  # noqa: E402
from app.phase1 import catalog_validate_router as CVR  # noqa: E402


def _cand(name, ns, leaf, vendor, vk, title="", desc="", *, active=True, latest=True):
    return {"name": name, "namespace": ns, "leaf": leaf, "vendor": vendor, "vendor_kind": vk,
            "title": title or leaf, "description": desc,
            "status": "active" if active else "deprecated", "is_latest": latest,
            "remotes": [{"type": "streamable-http", "url": "https://x"}], "packages": [],
            "repository": {"url": "https://github.com/x"}, "source": "registry"}


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    # por defecto: sin curado, sin cache → cada test controla search explícitamente
    monkeypatch.setattr(mcp_registry, "curated_entry", lambda s: None)
    monkeypatch.setattr(mcp_registry, "cache_get", lambda s, **k: None)
    # el rate-limit es persistente por-sujeto (disco); sin bypass el sujeto 'anon' se agota entre
    # tests y devuelve 429. Lo neutralizamos (la cobertura del rate-limit es de integración/T9).
    try:
        from safety import rate_limit
        monkeypatch.setattr(rate_limit, "check_and_consume", lambda subject, **k: (True, {}))
    except ImportError:
        pass


def _client():
    app = FastAPI()
    app.include_router(CVR.build_catalog_validate_router())
    return TestClient(app)


# ── classify_service directo ──────────────────────────────────────────────────────

def test_confiable_dns(monkeypatch):
    monkeypatch.setattr(mcp_registry, "search",
                        lambda q, **k: [_cand("com.stripe/mcp", "com.stripe", "mcp", "stripe", "dns",
                                              "Stripe", "pagos y cobros")])
    v = mcp_resolver.classify_service("stripe")
    assert v["verdict"] == "confiable"
    assert v["verified"] is True
    assert v["server_name"] == "com.stripe/mcp"
    assert v["vendor_kind"] == "dns"
    assert v["registry_status"] == "ok"


def test_confiable_github_org(monkeypatch):
    monkeypatch.setattr(mcp_registry, "search",
                        lambda q, **k: [_cand("io.github.acme/tool", "io.github.acme", "tool", "acme",
                                              "github_org", "Acme", "acme tools")])
    v = mcp_resolver.classify_service("acme")
    assert v["verdict"] == "confiable"
    assert v["verified"] is True
    assert v["vendor_kind"] == "github_org"


def test_confiable_curated_manual(monkeypatch):
    # curado.manual = server oficial no publicado en el registro → confiable sin tocar el registro
    monkeypatch.setattr(mcp_registry, "curated_entry",
                        lambda s: {"manual": {"display_name": "GitHub MCP", "command": "gh-mcp",
                                              "env_var": "GITHUB_TOKEN"}})
    called = {"n": 0}
    monkeypatch.setattr(mcp_registry, "search",
                        lambda q, **k: (called.__setitem__("n", called["n"] + 1), [])[1])
    v = mcp_resolver.classify_service("github")
    assert v["verdict"] == "confiable" and v["verified"] is True
    assert v["vendor_kind"] == "curated_manual"
    assert called["n"] == 0, "curado.manual corta antes de consultar el registro"


def test_dudoso_candidates_but_none_verified(monkeypatch):
    # caso REAL de 'dudoso': hay candidatos comunitarios pero ninguno pasa el umbral estricto (0.80)
    # sin señal de vendor verificado → best_match found=False, ranked no-vacío.
    monkeypatch.setattr(mcp_registry, "search",
                        lambda q, **k: [_cand("io.github.rando/notitas", "io.github.rando", "notitas",
                                              "rando", "unknown", "Notitas", "una app de notas")])
    v = mcp_resolver.classify_service("notas")
    assert v["verdict"] == "dudoso"
    assert v["verified"] is False
    assert v["server_name"] is None, "no hay un ganador confiable que ofrecer"
    assert len(v["ranked"]) >= 1, "pero SÍ hay candidatos (no es 'nada')"


def test_dudoso_found_but_unverified_branch(monkeypatch):
    # rama found-pero-no-verificado: inalcanzable con los pesos reales (0.80 sin vendor es imposible),
    # así que forzamos best_match para cubrir el branch de classify.
    cand = _cand("io.github.rando/foo", "io.github.rando", "foo", "rando", "unknown", "Foo", "d")
    monkeypatch.setattr(mcp_registry, "search", lambda q, **k: [cand])
    monkeypatch.setattr(mcp_matcher, "best_match",
                        lambda q, cs, **k: {"found": True, "reason": "match fuerte sin vendor",
                                            "winner": {"candidate": cand, "score": 0.83,
                                                       "verified_vendor": False},
                                            "ranked": [{"name": cand["name"], "score": 0.83,
                                                        "verified_vendor": False, "candidate": cand}]})
    v = mcp_resolver.classify_service("foo")
    assert v["verdict"] == "dudoso"
    assert v["server_name"] == "io.github.rando/foo", "hay un winner accionable, pero no verificado"
    assert v["verified"] is False


def test_impostor_verified_kind_but_wrong_owner_is_NOT_confiable(monkeypatch):
    """REGRESIÓN anti-impostor (hallazgo de seguridad): un candidato con vendor_kind='github_org'
    (namespace 'verificado' por el registro) PERO cuyo dueño NO es el servicio ('evil'≠'stripe')
    tiene winner['verified_vendor']=False. classify NO debe elevarlo a 'confiable' por el kind solo:
    io.github.evil/stripe-mcp es el vector clásico. Debe caer a 'dudoso'."""
    evil = _cand("io.github.evil/stripe-mcp", "io.github.evil", "stripe-mcp", "evil", "github_org",
                 "Stripe (community)", "unofficial stripe")
    monkeypatch.setattr(mcp_registry, "search", lambda q, **k: [evil])
    # forzamos que el impostor SEA el winner con verified_vendor=False (best_match ya lo haría, pero
    # lo fijamos para que el test no dependa del umbral aritmético que hoy lo mantiene muerto).
    monkeypatch.setattr(mcp_matcher, "best_match",
                        lambda q, cs, **k: {"found": True, "reason": "nombre parecido, dueño ajeno",
                                            "winner": {"candidate": evil, "score": 0.9,
                                                       "verified_vendor": False},
                                            "ranked": [{"name": evil["name"], "score": 0.9,
                                                        "verified_vendor": False, "candidate": evil}]})
    v = mcp_resolver.classify_service("stripe")
    assert v["verdict"] == "dudoso", "kind github_org SIN match dueño↔servicio NO es confiable"
    assert v["verified"] is False, "jamás verified=True para un impostor con namespace ajeno"


def test_nada_registry_empty(monkeypatch):
    monkeypatch.setattr(mcp_registry, "search", lambda q, **k: [])
    v = mcp_resolver.classify_service("servicioinexistentexyz")
    assert v["verdict"] == "nada"
    assert v["server_name"] is None and v["ranked"] == []


# ── [T-3] registro caído ────────────────────────────────────────────────────────────

def _boom(q, **k):
    raise mcp_registry.RegistryError("registro MCP inalcanzable: timed out")


def test_t3_unreachable_no_cache(monkeypatch):
    monkeypatch.setattr(mcp_registry, "search", _boom)
    v = mcp_resolver.classify_service("stripe")
    assert v["registry_status"] == "unreachable"
    assert v["verdict"] is None, "outage → veredicto INDETERMINADO, jamás 'nada'"
    assert v["retry"] is True


def test_t3_unreachable_with_validated_cache(monkeypatch):
    monkeypatch.setattr(mcp_registry, "search", _boom)
    monkeypatch.setattr(mcp_registry, "cache_get",
                        lambda s, **k: {"spec": {"transport": "http", "url": "https://x"},
                                        "server_name": "com.stripe/mcp", "vendor_kind": "dns",
                                        "source": "registry"})
    v = mcp_resolver.classify_service("stripe")
    assert v["registry_status"] == "unreachable"
    assert v["verdict"] == "confiable", "resolución cacheada validada = confiable-degradada"
    assert v["from_cache"] is True and v["verified"] is True


# ── endpoint GET /v1/catalog/validate ──────────────────────────────────────────────

def test_endpoint_empty_service_400():
    c = _client()
    r = c.get("/v1/catalog/validate", params={"service": ""})
    assert r.status_code == 400


def test_endpoint_confiable_picked_is_trusted(monkeypatch):
    monkeypatch.setattr(mcp_registry, "search",
                        lambda q, **k: [_cand("com.stripe/mcp", "com.stripe", "mcp", "stripe", "dns",
                                              "Stripe", "pagos")])
    c = _client()
    b = c.get("/v1/catalog/validate",
              params={"service": "stripe", "server_name": "com.stripe/mcp"}).json()
    assert b["verdict"] == "confiable"
    assert b["picked_is_trusted"] is True
    assert "conectar" in b["message"] or "verificado" in b["message"]


def test_endpoint_impostor_pick_flagged(monkeypatch):
    # el usuario eligió un server DISTINTO del oficial verificado (vector impostor) → picked_is_trusted False
    monkeypatch.setattr(mcp_registry, "search",
                        lambda q, **k: [_cand("com.stripe/mcp", "com.stripe", "mcp", "stripe", "dns",
                                              "Stripe", "pagos")])
    c = _client()
    b = c.get("/v1/catalog/validate",
              params={"service": "stripe", "server_name": "io.github.evil/stripe-mcp"}).json()
    # ⚠️ [OBRA 6c] CAMBIO DE CONTRATO DECLARADO, y sólo en QUÉ describe cada campo:
    #
    #   · `verdict` era del SERVICIO buscado («existe un oficial confiable para stripe») y
    #     ahora es de LA PIEZA QUE SE ELIGIÓ. Un impostor no es «confiable»: es `dudoso`.
    #     Decir `confiable` sobre él era lo que obligaba a la ficha a llevar el parche
    #     «confiable + picked_is_trusted false» para no pintarle un ✓ al impostor.
    #   · `server_name` era el ganador de re-descubrir el servicio; ahora es la pieza juzgada,
    #     y el oficial viaja en `trusted_server`, su campo propio.
    #
    # LO QUE ESTE TEST PROTEGE NO CAMBIÓ NADA: el usuario que elige el impostor sigue
    # recibiendo `picked_is_trusted False`, el nombre del bueno y la frase que lo dice. De
    # hecho ahora LLEGA A LA PANTALLA, que antes no pasaba: medido contra el registro real,
    # ninguna pieza alcanzaba `verdict:"confiable"` con el título que la UI mandaba, así que
    # esta advertencia estaba escrita y era inalcanzable.
    assert b["verdict"] == "dudoso"                      # la PIEZA elegida no es de fiar...
    assert b["picked_is_trusted"] is False               # ...porque no es la oficial
    assert b["picked"] == "io.github.evil/stripe-mcp"    # se juzgó la que tocó
    assert b["trusted_server"] == "com.stripe/mcp"       # y se nombra la buena
    assert "no el que elegiste" in b["message"] or "distinto" in b["message"]


def test_endpoint_no_pick_trusted_is_null(monkeypatch):
    monkeypatch.setattr(mcp_registry, "search",
                        lambda q, **k: [_cand("com.stripe/mcp", "com.stripe", "mcp", "stripe", "dns")])
    c = _client()
    b = c.get("/v1/catalog/validate", params={"service": "stripe"}).json()
    assert b["picked"] is None
    assert b["picked_is_trusted"] is None, "sin server_name no hay elección que juzgar"


def test_endpoint_nada_is_200(monkeypatch):
    monkeypatch.setattr(mcp_registry, "search", lambda q, **k: [])
    c = _client()
    r = c.get("/v1/catalog/validate", params={"service": "servicioxyz"})
    assert r.status_code == 200, "'nada' es un DATO, no un error"
    assert r.json()["verdict"] == "nada"
    assert "construir un MCP" in r.json()["message"]


def test_endpoint_t3_is_200_not_404(monkeypatch):
    monkeypatch.setattr(mcp_registry, "search", _boom)
    c = _client()
    r = c.get("/v1/catalog/validate", params={"service": "stripe"})
    assert r.status_code == 200, "outage → 200 honesto (el front lee registry_status), NUNCA 404/500"
    b = r.json()
    assert b["registry_status"] == "unreachable" and b["verdict"] is None
    assert b["retry"] is True


def test_endpoint_service_length_cap(monkeypatch):
    # [T9] `service` va a la búsqueda de red → cota de longitud contra queries-basura
    monkeypatch.setattr(mcp_registry, "search", lambda q, **k: [])
    c = _client()
    r = c.get("/v1/catalog/validate", params={"service": "x" * 201})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "service_muy_largo"


def test_endpoint_rate_limited_429(monkeypatch):
    # [T9] rate-limit defense-in-depth: el limiter dice basta → 429 (no 200 amplificando la red)
    monkeypatch.setattr(mcp_registry, "search", lambda q, **k: [])
    from safety import rate_limit
    monkeypatch.setattr(rate_limit, "check_and_consume",
                        lambda subject, **k: (False, {"retry_after": 30}))
    c = _client()
    r = c.get("/v1/catalog/validate", params={"service": "stripe"})
    assert r.status_code == 429
