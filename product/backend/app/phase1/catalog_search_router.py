"""
catalog_search_router.py — GET /v1/catalog/search : el CATÁLOGO VISIBLE de conectores.

Invierte el descubrimiento: el usuario BUSCA y VE qué conectores existen (catálogo INTERNO
curado + registro PÚBLICO), cada uno con su BADGE DE CONFIANZA, en vez de que el resolver
adivine en la sombra. El resolver pasa a ser la VALIDACIÓN que se aplica al ELEGIR (PR-3,
GET /v1/resolve/preview) — acá sólo se NAVEGA.

Fusiona dos fuentes:
  · INTERNO  — collect_atoms() (cards de belts, cero-theater) enriquecido con el onboarding
               JSON del conector (capability_line, tier). Badge "listo" (curado, ya funciona).
  · REGISTRO — mcp_registry.search(q) → mcp_matcher.rank(q). El sello de procedencia sale
               únicamente de `mcp_registry.pinned_servers()`. DNS/GitHub sin pin identifican
               al publicador con "publicado por X", pero no reciben ✓.

DEDUP: un servicio que está en AMBAS fuentes aparece UNA vez — gana el interno (es accionable,
ya conectable) y HEREDA el badge oficial del registro sólo si la pieza está pineada.

[T-3 · REQUISITO OBLIGATORIO] Si el registro público no responde (RegistryError), la respuesta
es HTTP 200 con `registry_status:"unreachable"` + `notice` + los ítems INTERNOS que sí cargaron —
JAMÁS una lista vacía fingiendo que no hay resultados. Ese false-empty le mentiría al usuario
diciéndole que su conector no existe (el peor bug de esta superficie).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException

# [4.1 frozen-aware] resource_root() da _MEIPASS en el bundle y la raíz del repo en dev
# (byte-idéntico). `Path(__file__).parents[4]` rompía en frozen (sobrepasa _MEIPASS) → _ONB
# inexistente → enriquecimiento MUERTO (tier/capability_line = None en la .app). Mismo patrón
# frozen-aware que atoms_router (import guardado: aleph_paths ya viaja en el bundle; en dev
# cae al parents[4]/platform).
try:
    import aleph_paths as _ap
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap
_REPO = _ap.resource_root()
_ONB = _REPO / "catalog" / "connectors" / "onboarding"
_PLATFORM = _REPO / "platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from app.phase1.atoms_router import collect_atoms, _connected_for  # noqa: E402


# tokens genéricos que NO identifican un servicio (no dedupar por ellos)
_GENERIC_TOK = {"mcp", "server", "servers", "io", "com", "org", "net", "app", "apps", "api",
                "official", "the", "co", "inc", "cloud", "tool", "tools", "connector"}


def _tok(s: Optional[str]) -> set[str]:
    """Tokens identitarios de un string (minúscula, sin genéricos, len>1)."""
    return {t for t in re.split(r"[^a-z0-9]+", (s or "").lower())
            if t and t not in _GENERIC_TOK and len(t) > 1}


def _internal_ident(connector: Optional[str]) -> set[str]:
    """Identidad de un átomo interno = tokens de su CONNECTOR (identidad precisa del servicio).
    Los tools keyless SIN connector (yfinance, sql, fem…) no tienen identidad de servicio → set
    vacío → nunca dedupan (son internos-only, no colisionan con el registro)."""
    return _tok(connector)


def _registry_ident(cand: dict) -> set[str]:
    """Identidad de un candidato del registro = ÚLTIMO segmento del namespace (el PRODUCTO, no el
    dueño) + tokens del leaf. `com.google.gmail/mcp` → {gmail} (no {google}); `io.github.makenotion/
    notion-mcp` → {makenotion, notion}. Así el interno 'gmail'/'notion' dedupa con el server real,
    y dos servicios distintos del mismo dueño (io.github.github/a, /b) NO se colapsan en uno."""
    ns = cand.get("namespace") or ""
    last = ns.split(".")[-1] if ns else ""
    return _tok(last) | _tok(cand.get("leaf"))


_ONB_CACHE: dict[str, Optional[dict]] = {}


def _onboarding(connector: Optional[str]) -> Optional[dict]:
    if not connector:
        return None
    if connector in _ONB_CACHE:
        return _ONB_CACHE[connector]
    p = _ONB / f"{connector}.json"
    d = None
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            d = None
    _ONB_CACHE[connector] = d
    return d


# ── BADGES ──────────────────────────────────────────────────────────────────────

def _registry_badge(cand: dict) -> dict:
    """El sello sale sólo del pin; el namespace identifica al publicador."""
    from inspection import mcp_registry
    vk = cand.get("vendor_kind") or "unknown"
    ns = cand.get("namespace")
    vendor = cand.get("vendor")
    pinned_as = mcp_registry.pinned_servers().get(str(cand.get("name") or ""))
    if pinned_as:
        label = f"✓ oficial (github: {vendor})" if vk == "github_org" else f"✓ oficial ({ns})"
        return {"kind": "official_github" if vk == "github_org" else "official_dns",
                "label": label, "verified": True, "vendor_kind": vk, "namespace": ns,
                "publisher": vendor, "pinned_as": pinned_as}
    if vk in {"dns", "github_org"}:
        label = f"publicado por github: {vendor}" if vk == "github_org" else f"publicado por {vendor}"
        return {"kind": "registry_publisher", "label": label, "verified": False,
                "vendor_kind": vk, "namespace": ns, "publisher": vendor}
    return {"kind": "community_unverified", "label": "origen no verificable",
            "verified": False, "vendor_kind": vk, "namespace": ns, "publisher": vendor}


def _internal_badge(atom: dict) -> dict:
    """Badge de un átomo INTERNO curado: 'listo' (ya funciona). Verified=True en el sentido de
    'lo que ves es lo que hay' — es una pieza que construimos y probamos (cero theater)."""
    if atom.get("auth", "keyless") == "keyless":
        return {"kind": "internal_ready", "label": "listo · sin llave",
                "verified": True, "vendor_kind": None, "namespace": None}
    state = atom.get("state")
    label = "conectado · listo" if state == "connected" else "listo · conecta tu cuenta"
    return {"kind": "internal_ready", "label": label,
            "verified": True, "vendor_kind": None, "namespace": None}


# ── FUENTES ─────────────────────────────────────────────────────────────────────

def _internal_items(q: str, facet: Optional[str], connected: set,
                    owner: Optional[str] = None) -> list[dict]:
    """Ítems del catálogo INTERNO (collect_atoms) filtrados por q + facet, enriquecidos con el
    onboarding (capability_line/tier)."""
    ql = (q or "").strip().lower()
    fl = (facet or "").strip().lower()
    out: list[dict] = []
    for a in collect_atoms(connected, owner=owner):
        hay = " ".join(str(x) for x in (
            a.get("label"), a.get("sub"), a.get("server"), a.get("connector"),
            a.get("armario"), " ".join(a.get("tools") or []))).lower()
        if ql and ql not in hay:
            continue
        if fl and fl != (a.get("armario") or "").lower() and fl != (a.get("zone") or "").lower():
            continue
        onb = _onboarding(a.get("connector"))
        desc = (onb or {}).get("capability_line") or a.get("sub") or ""
        out.append({
            "id": a.get("id"), "name": a.get("label") or a.get("id"),
            "description": desc, "source": "internal", "badge": _internal_badge(a),
            "score": None, "facet": a.get("armario") or a.get("zone"),
            "connector": a.get("connector"), "auth": a.get("auth"),
            "server_name": a.get("server"), "state": a.get("state"),
            "belt_ref": a.get("belt_ref"), "zone": a.get("zone"),
            "tier": (onb or {}).get("tier"),
            "requisito": "ninguno" if a.get("auth", "keyless") == "keyless" else "llave",
            "fecha_ingesta": None, "confianza": 1.0,
            "consecuencias": "se_sabra_al_conectar", "referencia_crudo": None,
            "_ident": _internal_ident(a.get("connector")),
        })
    return out


def _registry_items(q: str, limit: int, local_by_id: Optional[dict] = None) -> tuple[list[dict], str]:
    """Ítems del REGISTRO público (search → rank). Devuelve (items, status) donde status es
    'ok' o 'unreachable' (T-3: NUNCA convierte un outage en lista vacía silenciosa)."""
    from inspection import mcp_matcher, mcp_registry
    try:
        candidates = mcp_registry.search(q, limit=limit)
        ranked = mcp_matcher.rank(q, candidates)
    except mcp_registry.RegistryError:
        return [], "unreachable"      # [T-3] el caller lo surfacea; jamás como "no hay resultados"
    except mcp_registry.CuradoAusenteError:
        # [OBRA 6a] DEFECTO DE BUILD, NO OUTAGE. Degradarlo a "unreachable" le diría al
        # usuario que el catálogo público no contesta cuando lo que falta es un archivo
        # NUESTRO. Esa mentira es peor que el 500: manda a mirar la red ajena por un bug
        # propio. Se deja subir para que se vea con su nombre. En un build que pasó por
        # `qa/gate_bundle_aleph.py` esto no puede ocurrir.
        raise
    except Exception:
        # [T-3] cualquier OTRA falla del registro/rank NO debe 500ear el endpoint (tumbaría también
        # los internos): degradamos a solo-internos + status honesto. Nunca false-empty silencioso.
        return [], "unreachable"
    out: list[dict] = []
    local_by_id = local_by_id or {}
    seen_names: set[str] = set()
    for scored in ranked:
        cand = scored["candidate"]
        # El registro puede devolver la misma versión más de una vez. La identidad pública
        # estable es `name`; deduplicar acá protege cualquier UI y también futuros catálogos.
        name = str(cand.get("name") or "").strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        from app.phase1.catalog_ingest_router import scrutiny_consequences, scrutiny_requirements
        local = local_by_id.get(name) or {}
        out.append({
            "id": name,
            "name": cand.get("title") or cand.get("leaf") or cand.get("name"),
            "description": cand.get("description") or "", "source": "registry",
            "badge": _registry_badge(cand), "score": scored.get("score"),
            "facet": None, "connector": None, "auth": None,
            "server_name": cand.get("name"), "namespace": cand.get("namespace"),
            "vendor": cand.get("vendor"),
            "requisito": scrutiny_requirements(cand)["requisito"],
            "fecha_ingesta": local.get("fecha_ingesta"),
            "confianza": float(scored.get("score") or 0),
            "consecuencias": scrutiny_consequences(cand),
            "referencia_crudo": (
                "/v1/catalog/raw?catalog_id=" + urllib.parse.quote(name, safe="")
            ),
            "_ident": _registry_ident(cand),
        })
        if len(out) >= limit:
            break
    return out, "ok"


def _dedup_merge(internal: list[dict], registry: list[dict]) -> list[dict]:
    """Un servicio en AMBAS fuentes aparece UNA vez: gana el interno (accionable) y HEREDA el
    badge oficial del registro si el registro lo tiene verificado.

    Match por INTERSECCIÓN de identidad (connector interno ∩ {producto del namespace, leaf}). Cada
    interno absorbe A LO SUMO UN gemelo (el primero, ya ordenado por score): dos servers DISTINTOS
    del mismo dueño (io.github.github/a, /b) NO se colapsan — el 2º sigue visible aparte."""
    fused = list(internal)
    absorbed: set[int] = set()   # object-ids de internos que YA absorbieron un gemelo
    for rg in registry:
        rid = rg.get("_ident") or set()
        twin = None
        if rid:
            for it in internal:
                if id(it) in absorbed:
                    continue
                if rid & (it.get("_ident") or set()):
                    twin = it
                    break
        if twin is not None:
            absorbed.add(id(twin))
            # el interno gana; hereda el badge oficial del registro (mejor provenance) UNA vez
            if rg["badge"].get("verified") and not twin["badge"].get("verified_upgraded"):
                twin["badge"] = {**rg["badge"],
                                 "label": f"{rg['badge']['label']} · listo",
                                 "verified_upgraded": True}
                twin["namespace"] = rg["badge"].get("namespace")
            continue
        fused.append(rg)
    return fused


# ── ENDPOINT ──────────────────────────────────────────────────────────────────────

def build_catalog_search_router(*, get_conn: Optional[Callable[[], Any]] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/catalog", tags=["catalog"])

    @router.get("/search")
    def catalog_search(q: str = "", source: str = "all", verified_only: bool = False,
                       facet: str = "", limit: int = 20,
                       authorization: Optional[str] = Header(default=None)):
        source = (source or "all").strip().lower()
        if source not in ("all", "internal", "registry"):
            source = "all"
        q = (q or "").strip()

        # INTERNO
        internal: list[dict] = []
        if source in ("all", "internal"):
            # T-S5-03: qué tiene CONECTADO sale de la sesión, no de un parámetro.
            from app.phase1.atoms_router import _owner_from_session
            dueno = _owner_from_session(authorization)
            connected = _connected_for(dueno, get_conn)
            # EL DUEÑO TAMBIÉN VIAJA: buscar en «lo interno» tiene que buscar en lo TUYO,
            # no en lo de todas las cuentas de la máquina.
            internal = _internal_items(q, facet, connected, owner=dueno)

        # REGISTRO — sólo con query no vacía (search vacío no navega el registro completo)
        registry: list[dict] = []
        registry_status = "skipped"
        notice = None
        if source in ("all", "registry") and q:
            from app.phase1.catalog_ingest_router import local_scrutiny_index
            local_by_id = local_scrutiny_index()
            registry, registry_status = _registry_items(q, limit, local_by_id)
            if registry_status == "unreachable":
                # [T-3] NUNCA lista vacía fingida: avisamos y mostramos lo interno que sí cargó.
                notice = ("el catálogo público no responde ahora mismo; te muestro solo los "
                          "conectores internos (listos). Reintenta.")
        elif source in ("all", "registry") and not q:
            notice = "escribe un nombre o rubro para buscar también en el registro público."

        # FUSIÓN + DEDUP
        items = _dedup_merge(internal, registry) if source == "all" else (internal or registry)

        if verified_only:
            items = [it for it in items if it["badge"].get("verified")]

        # ORDEN: internos primero (accionables/listos), luego registro por score desc
        items.sort(key=lambda it: (0 if it["source"] == "internal" else 1,
                                   -(it.get("score") or 0.0), (it.get("name") or "").lower()))
        for it in items:
            it.pop("_ident", None)

        n_int = sum(1 for it in items if it["source"] == "internal")
        n_reg = sum(1 for it in items if it["source"] == "registry")
        return {
            "query": q, "source": source, "items": items,
            "registry_status": registry_status, "internal_status": "ok",
            "counts": {"internal": n_int, "registry": n_reg, "total": len(items)},
            "notice": notice,
        }

    @router.get("/raw")
    def catalog_raw(catalog_id: str):
        """Entrega el manifest de una sola pieza; la lista nunca incluye manifests crudos."""
        from app.phase1.catalog_ingest_router import list_local, local_scrutiny_index
        from inspection import mcp_registry
        wanted = str(catalog_id or "").strip()
        if not wanted:
            raise HTTPException(status_code=400, detail={"error": "catalog_id_requerido"})
        local = local_scrutiny_index().get(wanted)
        if local is None:
            local = next((entry for entry in list_local() if entry["id"] == wanted), None)
        if local and isinstance(local.get("manifest_crudo"), dict):
            return {"id": wanted, "manifest": local["manifest_crudo"], "source": "local"}
        try:
            candidate = mcp_registry.get_by_name(wanted)
        except mcp_registry.RegistryError:
            raise HTTPException(status_code=503, detail={"error": "registro_no_disponible"})
        raw = candidate.get("_manifest_raw") if isinstance(candidate, dict) else None
        if not isinstance(raw, dict):
            raise HTTPException(status_code=404, detail={"error": "manifest_no_encontrado"})
        return {"id": wanted, "manifest": raw, "source": "registry"}

    return router


__all__ = ["build_catalog_search_router"]
