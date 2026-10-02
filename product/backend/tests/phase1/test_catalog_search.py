"""
test_catalog_search.py — PR-2: GET /v1/catalog/search (catálogo visible = interno + registro).

Prueba la fusión con fixtures DETERMINISTAS (monkeypatch de collect_atoms + mcp_registry.search):
  · badge por vendor_kind (dns → ✓ oficial · github_org → ✓ oficial github · unknown → ⚠ community)
  · badge interno "listo" (curado)
  · dedup: servicio en ambas fuentes aparece 1 vez (gana interno, hereda badge oficial)
  · verified_only filtra los ⚠ community
  · source=internal|registry saltea la otra fuente
  · [T-3 · OBLIGATORIO] registro caído → registry_status:"unreachable" + notice + ítems internos,
    HTTP 200, NUNCA lista vacía fingida.
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

from inspection import mcp_registry  # noqa: E402
from app.phase1 import catalog_search_router as CSR  # noqa: E402


#: ⚠️ `owner` NO ES DECORATIVO EN LOS FAKES (A1 · la fuga entre cuentas). `collect_atoms`
#: pasó a filtrar el `synth_belts` por cuenta, y un doble que no acepte el argumento
#: convierte un cableado roto en un `TypeError` sin diagnóstico. Se acepta Y SE ANOTA: los
#: tests de abajo comprueban que el buscador propague el dueño, que es lo que impide que
#: «buscar en lo interno» vuelva a mirar lo de todas las cuentas de la máquina.
VISTOS: list = []


def _fake_atoms(connected=None, *, owner=None):
    VISTOS.append(owner)
    return [
        {"id": "gmail", "label": "Gmail", "sub": "correo", "atom": "conexion", "zone": "entrega",
         "server": "gmail-mcp", "tools": ["send_email"], "belt_ref": "b", "auth": "oauth",
         "connector": "gmail", "armario": "apps", "criticality": "low",
         "state": "connectable", "badge": "Conectar", "connectable": True, "requirements": {}},
        {"id": "yf", "label": "Yahoo Finance", "sub": "precios de acciones", "atom": "tool",
         "zone": "fuentes", "server": "yfinance", "tools": ["get_quote"], "belt_ref": "b",
         "auth": "keyless", "connector": None, "armario": "datos", "criticality": "low",
         "state": "ready", "badge": "sin llave", "requirements": {}},
    ]


def _reg_cand(name, ns, leaf, vendor, vk, title="", desc=""):
    raw = {"server": {"name": name, "title": title, "description": desc,
                      "remotes": [{"type": "streamable-http", "url": "https://x"}]}}
    return {"name": name, "namespace": ns, "leaf": leaf, "vendor": vendor, "vendor_kind": vk,
            "title": title, "description": desc, "status": "active", "is_latest": True,
            "remotes": [{"type": "streamable-http", "url": "https://x"}], "packages": [],
            "repository": {"url": "https://github.com/x"}, "source": "registry",
            "_manifest_raw": raw}


def _fake_search_ok(q, **k):
    return [
        _reg_cand("com.stripe/mcp", "com.stripe", "mcp", "stripe", "dns", "Stripe", "Pagos y cobros"),
        _reg_cand("io.github.acme/tool", "io.github.acme", "tool", "acme", "github_org", "Acme", "d"),
        _reg_cand("weird-thing", "", "weird-thing", "", "unknown", "Weird", "algo community"),
    ]


def _fake_search_boom(q, **k):
    raise mcp_registry.RegistryError("registro MCP inalcanzable: timed out")


@pytest.fixture(autouse=True)
def _patch_sources(monkeypatch):
    monkeypatch.setattr(CSR, "collect_atoms", _fake_atoms)
    monkeypatch.setattr(mcp_registry, "search", _fake_search_ok)


def _client():
    app = FastAPI()
    app.include_router(CSR.build_catalog_search_router(get_conn=None))
    return TestClient(app)


def _by_id(items):
    return {it["id"]: it for it in items}


# ── FUSIÓN + BADGES ───────────────────────────────────────────────────────────────

def test_el_sello_sale_del_pin_no_del_vendor_kind():
    c = _client()
    r = c.get("/v1/catalog/search", params={"q": "pagos"})
    assert r.status_code == 200
    b = r.json()
    assert b["registry_status"] == "ok"
    items = _by_id(b["items"])
    # Stripe está pineado; Acme sólo trae identidad del publicador.
    assert items["com.stripe/mcp"]["badge"]["kind"] == "official_dns"
    assert items["com.stripe/mcp"]["badge"]["label"].startswith("✓ oficial (com.stripe")
    assert items["com.stripe/mcp"]["badge"]["verified"] is True
    assert items["io.github.acme/tool"]["badge"]["kind"] == "registry_publisher"
    assert items["io.github.acme/tool"]["badge"]["label"] == "publicado por github: acme"
    assert items["io.github.acme/tool"]["badge"]["verified"] is False
    assert items["weird-thing"]["badge"]["kind"] == "community_unverified"
    assert items["weird-thing"]["badge"]["verified"] is False


def test_internal_badges_listo():
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "", "source": "internal"}).json()
    items = _by_id(b["items"])
    assert items["gmail"]["badge"]["kind"] == "internal_ready"
    assert items["yf"]["badge"]["label"] == "listo · sin llave"


def test_internal_first_ordering():
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "gmail"}).json()
    sources = [it["source"] for it in b["items"]]
    assert "internal" in sources and "registry" in sources
    # todos los internos preceden a los de registro
    assert sources == sorted(sources, key=lambda s: 0 if s == "internal" else 1)


# ── DEDUP ───────────────────────────────────────────────────────────────────────

def test_dedup_internal_wins_inherits_official_badge(monkeypatch):
    # registro trae un gmail oficial (dns) que coincide con el interno gmail.
    # vendor='google' es lo que vendor_of() saca del namespace 'com.google.gmail' (el DUEÑO del
    # dominio, no el producto). leaf='mcp' es el leaf REAL (genérico → aporta {}), así el token
    # {gmail} que dispara el dedup viene SÓLO de parsear el último segmento del namespace: si la
    # lógica regresara a matchear por owner ({google}) este test FALLA (no un falso-verde por el leaf).
    def _search_with_gmail(q, **k):
        return [_reg_cand("com.google.gmail/mcp", "com.google.gmail", "mcp", "google", "dns",
                          "Gmail", "correo de google")]
    monkeypatch.setattr(mcp_registry, "search", _search_with_gmail)
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "gmail"}).json()
    gmails = [it for it in b["items"] if (it.get("connector") == "gmail"
                                          or it.get("id") == "com.google.gmail/mcp")]
    assert len(gmails) == 1, "gmail aparece UNA vez (dedup por identidad de servicio, no por vendor)"
    g = gmails[0]
    assert g["source"] == "internal", "gana el interno (accionable)"
    assert g["id"] == "gmail", "el que sobrevive es el interno, no el registro"
    assert g["badge"].get("verified") is True  # listo interno, no sello del registro
    assert g["badge"]["label"] == "listo · conecta tu cuenta"


def test_dedup_two_servers_same_owner_not_collapsed(monkeypatch):
    # dos servers DISTINTOS del mismo dueño (io.github.acme) NO deben colapsarse en uno: sólo
    # comparten el owner 'acme', no la identidad de producto. El dedup absorbe A LO SUMO un gemelo
    # por interno, y como ninguno matchea un connector interno, ambos quedan visibles.
    def _two_acme(q, **k):
        return [_reg_cand("io.github.acme/alpha", "io.github.acme", "alpha", "acme", "github_org", "Alpha", "a"),
                _reg_cand("io.github.acme/beta", "io.github.acme", "beta", "acme", "github_org", "Beta", "b")]
    monkeypatch.setattr(mcp_registry, "search", _two_acme)
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "acme"}).json()
    ids = [it["id"] for it in b["items"] if it["source"] == "registry"]
    assert "io.github.acme/alpha" in ids and "io.github.acme/beta" in ids, \
        "dos productos del mismo owner sobreviven separados (no se colapsan por dueño común)"


def test_registry_duplicate_name_appears_once(monkeypatch):
    duplicate = _reg_cand(
        "io.github.acme/postgres", "io.github.acme", "postgres",
        "acme", "github_org", "Postgres", "base de datos",
    )
    monkeypatch.setattr(mcp_registry, "search", lambda q, **k: [duplicate, dict(duplicate), dict(duplicate)])
    b = _client().get("/v1/catalog/search", params={"q": "postgres", "source": "registry"}).json()
    assert [it["id"] for it in b["items"]] == ["io.github.acme/postgres"]
    assert b["counts"]["registry"] == 1


def test_dedup_absorbs_at_most_one_twin(monkeypatch):
    """El invariante DURO de _dedup_merge (rama no-trivial): un interno cuyo _ident matchea a DOS
    candidatos de registro (ambos comparten el token del owner en el namespace-tail) absorbe SÓLO
    al primero; el segundo NO se pierde ni se colapsa — sobrevive como fila de registro aparte.
    Sin el candado `absorbed`, el 2º gemelo se dropearía (el bug original 'github droppeado')."""
    def _atoms_acme(connected=None, *, owner=None):
        return [{"id": "acme", "label": "Acme", "sub": "suite acme", "atom": "conexion",
                 "zone": "apps", "server": "acme-mcp", "tools": ["do"], "belt_ref": "b",
                 "auth": "oauth", "connector": "acme", "armario": "apps", "criticality": "low",
                 "state": "connectable", "badge": "Conectar", "connectable": True, "requirements": {}}]
    def _two_acme(q, **k):
        return [_reg_cand("io.github.acme/alpha", "io.github.acme", "alpha", "acme", "github_org", "Alpha", "a"),
                _reg_cand("io.github.acme/beta", "io.github.acme", "beta", "acme", "github_org", "Beta", "b")]
    monkeypatch.setattr(CSR, "collect_atoms", _atoms_acme)
    monkeypatch.setattr(mcp_registry, "search", _two_acme)
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "acme"}).json()
    internal = [it for it in b["items"] if it["source"] == "internal"]
    registry = [it for it in b["items"] if it["source"] == "registry"]
    assert len(internal) == 1, "el interno acme aparece una vez"
    assert len(registry) == 1, "absorbió UN gemelo; el segundo sobrevive (no se dropea ni colapsa)"
    assert registry[0]["id"] in ("io.github.acme/alpha", "io.github.acme/beta")


def test_dedup_notion_multitoken_namespace(monkeypatch):
    """Namespace multi-token real: io.github.makenotion/notion-mcp → _registry_ident = {makenotion,
    notion} (tail 'makenotion' ∪ leaf 'notion', 'mcp' es genérico). El interno 'notion' dedupa por
    el token 'notion' compartido. Ejercita el path de leaf multi-palabra, no sólo el namespace-tail."""
    def _atoms_notion(connected=None, *, owner=None):
        return [{"id": "notion", "label": "Notion", "sub": "notas y docs", "atom": "conexion",
                 "zone": "apps", "server": "notion-mcp", "tools": ["query"], "belt_ref": "b",
                 "auth": "oauth", "connector": "notion", "armario": "apps", "criticality": "low",
                 "state": "connectable", "badge": "Conectar", "connectable": True, "requirements": {}}]
    def _search_notion(q, **k):
        return [_reg_cand("io.github.makenotion/notion-mcp", "io.github.makenotion", "notion-mcp",
                          "makenotion", "github_org", "Notion", "official notion mcp")]
    monkeypatch.setattr(CSR, "collect_atoms", _atoms_notion)
    monkeypatch.setattr(mcp_registry, "search", _search_notion)
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "notion"}).json()
    notions = [it for it in b["items"] if it["source"] == "registry"]
    assert notions == [], "el notion de registro se absorbió en el interno (no queda fila duplicada)"
    internal = [it for it in b["items"] if it["source"] == "internal"]
    assert len(internal) == 1 and internal[0]["id"] == "notion"
    assert internal[0]["badge"].get("verified") is True and "listo" in internal[0]["badge"]["label"]


# ── verified_only ─────────────────────────────────────────────────────────────────

def test_verified_only_drops_community():
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "gmail", "verified_only": "true"}).json()
    ids = {it["id"] for it in b["items"]}
    assert "weird-thing" not in ids, "verified_only descarta ⚠ community"
    assert "com.stripe/mcp" in ids and "gmail" in ids


def test_rojo_sin_pin_ni_stripe_lleva_sello(monkeypatch):
    curated = mcp_registry.load_curated()
    curated["services"].pop("stripe")
    monkeypatch.setattr(mcp_registry, "load_curated", lambda: curated)
    items = _by_id(_client().get(
        "/v1/catalog/search", params={"q": "stripe", "source": "registry"}
    ).json()["items"])
    badge = items["com.stripe/mcp"]["badge"]
    assert badge["verified"] is False
    assert badge["label"] == "publicado por stripe"


@pytest.mark.parametrize("service,pin,alias", [
    ("exa", "ai.exa/exa", "exa search"),
    ("alphavantage", "io.github.alphavantage/alpha_vantage_mcp", "alpha vantage"),
    ("context7", "io.github.upstash/context7", "context 7"),
])
def test_pin_nuevo_nombre_alias_y_remocion(monkeypatch, service, pin, alias):
    assert mcp_registry.curated_entry(alias)["service"] == service
    assert mcp_registry.pinned_servers()[pin] == service
    cand = _reg_cand(pin, pin.split("/")[0], pin.split("/")[1], service, "dns")
    assert CSR._registry_badge(cand)["verified"] is True
    curated = mcp_registry.load_curated()
    curated["services"].pop(service)
    monkeypatch.setattr(mcp_registry, "load_curated", lambda: curated)
    assert CSR._registry_badge(cand)["verified"] is False


def test_search_entrega_escrutinio_y_raw_solo_bajo_pedido(monkeypatch):
    c = _client()
    body = c.get("/v1/catalog/search", params={"q": "stripe", "source": "registry"}).json()
    stripe = _by_id(body["items"])["com.stripe/mcp"]
    assert stripe["requisito"] == "click"
    assert isinstance(stripe["confianza"], float)
    assert stripe["consecuencias"] == "se_sabra_al_conectar"
    assert stripe["referencia_crudo"].startswith("/v1/catalog/raw?")
    assert "manifest" not in stripe and "manifest_crudo" not in stripe
    candidate = _fake_search_ok("stripe")[0]
    monkeypatch.setattr(mcp_registry, "get_by_name", lambda name: candidate)
    raw = c.get("/v1/catalog/raw", params={"catalog_id": candidate["name"]})
    assert raw.status_code == 200
    assert raw.json()["manifest"] == candidate["_manifest_raw"]


# ── source filter ─────────────────────────────────────────────────────────────────

def test_source_internal_skips_registry():
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "gmail", "source": "internal"}).json()
    assert b["registry_status"] == "skipped"
    assert all(it["source"] == "internal" for it in b["items"])


def test_source_registry_skips_internal():
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "stripe", "source": "registry"}).json()
    assert all(it["source"] == "registry" for it in b["items"])


# ── [T-3] REGISTRO CAÍDO — el requisito obligatorio ───────────────────────────────

def test_t3_registry_down_internal_survives(monkeypatch):
    """Registro caído + hay match interno → los internos siguen, registry marcado unreachable."""
    monkeypatch.setattr(mcp_registry, "search", _fake_search_boom)
    c = _client()
    r = c.get("/v1/catalog/search", params={"q": "gmail"})
    assert r.status_code == 200, "outage del registro → 200 honesto, no error 5xx crudo"
    b = r.json()
    assert b["registry_status"] == "unreachable"
    assert b["notice"] and "no responde" in b["notice"]
    assert b["counts"]["registry"] == 0
    ids = {it["id"] for it in b["items"]}
    assert "gmail" in ids, "el match interno sobrevive el outage; jamás se oculta"
    assert all(it["source"] == "internal" for it in b["items"])


def test_t3_registry_down_no_internal_match_still_honest(monkeypatch):
    """Registro caído SIN match interno → items puede quedar vacío, PERO registry_status +
    notice comunican el outage: el frontend nunca debe leerlo como 'no existe' (lee el status,
    no la vacuidad). Éste es el corazón del requisito T-3."""
    monkeypatch.setattr(mcp_registry, "search", _fake_search_boom)
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "stripe"}).json()  # 'stripe' no matchea interno
    assert b["registry_status"] == "unreachable", "el outage SIEMPRE se señaliza"
    assert b["notice"] and "no responde" in b["notice"]
    # el false-empty se evita por la SEÑAL (status+notice), no fingiendo resultados


def test_empty_query_browses_internal_with_notice():
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": ""}).json()
    assert b["registry_status"] == "skipped"
    assert b["notice"] and "registro público" in b["notice"]
    assert len(b["items"]) == 2  # los dos internos, sin tocar el registro


def test_facet_filter_internal():
    c = _client()
    b = c.get("/v1/catalog/search", params={"q": "", "facet": "datos"}).json()
    ids = {it["id"] for it in b["items"]}
    assert ids == {"yf"}, "facet 'datos' deja solo el átomo de armario datos"


# ══ A1 · LA FUGA ENTRE CUENTAS · el buscador propaga el dueño ═════════════════════════

def test_buscar_en_lo_interno_propaga_el_dueno(monkeypatch):
    """«Lo interno» tiene que ser LO TUYO, no lo de todas las cuentas de la máquina.

    ⚠️ EL BUSCADOR ERA LA TERCERA PUERTA. `collect_atoms` filtra por cuenta desde A1, pero
    el filtro no sirve de nada si un llamador olvida pasar el dueño: seguiría llamando sin
    él y —fail-closed— dejaría de mostrarle al usuario sus propias piezas, en silencio y en
    verde. Este testigo mira el argumento que llega al walk, no el resultado.
    """
    from app.phase1 import atoms_router
    monkeypatch.setattr(atoms_router, "_owner_from_session", lambda _a: "cuenta-de-prueba")
    VISTOS.clear()
    r = _client().get("/v1/catalog/search", params={"q": "correo"},
                      headers={"Authorization": "Bearer lo-que-sea"})
    assert r.status_code == 200
    assert VISTOS and VISTOS[-1] == "cuenta-de-prueba"


def test_sin_sesion_el_buscador_no_pide_las_piezas_de_nadie(monkeypatch):
    """NEGATIVO/discriminante. Sin sesión el dueño es `None`, y `collect_atoms` no sirve
    ningún `synth_belts`. Sin este testigo, el de arriba se cumpliría con un endpoint que
    manda siempre el mismo id fijo."""
    from app.phase1 import atoms_router
    monkeypatch.setattr(atoms_router, "_owner_from_session", lambda _a: None)
    VISTOS.clear()
    r = _client().get("/v1/catalog/search", params={"q": "correo"})
    assert r.status_code == 200
    assert VISTOS and VISTOS[-1] is None
