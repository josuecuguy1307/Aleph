"""
dispatch_router.py — EL DESPACHADOR §0.5 · BUSCÁ-ANTES-DE-FORJAR (rama 1c-resolver).

`POST /v1/inspect/dispatch` es el "if que ordena" que faltaba cablear: cuando el usuario
apunta a un software, PRIMERO se consulta el RESOLVER (¿ya existe un MCP verificado para esto
en el registry oficial?) y SOLO si no existe se dispara el MOTOR B (la forja cara desde cero).

    ┌─ resolver.buscando ─────────────────────────────────────────────────────────┐
    │  resolve_service(service)  [registry + matcher anti-impostor DNS, SIN tocar]  │
    └──────────────────────────────────────────────────────────────────────────────┘
         │                                              │
         ▼ encontrado + VERIFICADO                      ▼ miss / no-verificado / impostor
    resolver.encontrado{origin:registry}          resolver.miss{reason, rechazado?}
    → validate_live + equip_resolved (PATH 1-B)   → run_forge_stream (MOTOR B / loop §3)
    → mcp.equipado{origin:registry}               → sesion.ok…tool.validada…mcp.forjado{forged}
    → cerrado{path:registry}                       → cerrado{path:forged}

INVARIANTES (lo que NO hace):
  • NO reescribe el resolver ni el Motor B — los ORDENA. El "encontrado" usa el MISMO equip
    1-B que `/v1/resolve` (validate_live + equip_resolved); el "miss" usa el MISMO Motor B que
    `/v1/inspect/forge` (run_forge_stream → run_internal_loop). Cero segundo camino de equip.
  • NO puentea el anti-impostor DNS: la decisión found/miss SALE de resolve_service (prod) o
    del MISMO mcp_matcher.best_match (verificación) — un impostor sin namespace verificado se
    rechaza ahí, jamás se equipa.
  • CERO-TEATRO: "encontrado" solo si el resolver lo CONFIRMA (vendor_kind verificado o curado).
    Un match de comunidad SIN ownership NO cuenta como "verificado" → cae al Motor B.

VERIFICACIÓN (env-gated, igual patrón que seed_probes de forge_router):
  Con `PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES=1` el endpoint acepta `seed_candidates` (dicts con
  forma de registry-candidate) y los arbitra con el MATCHER REAL — así Playwright maneja
  found/miss/impostor sin pegarle al registro vivo, pero la confirmación sigue siendo del
  resolver de verdad (no cache optimista). `seed_spec` apunta el equip a un MCP LOCAL real
  (stdio fixture) → la pieza forjada es REAL. En producto la env NO existe → seed_* se ignora.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLATFORM = _REPO_ROOT / "platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection.sse_util import _sse, _slug  # noqa: E402  [4.2.a] neutro (SHARED)
# [4.2.a] build_seed_candidates/run_forge_stream/enforce_construction_premium = FORGE → import
# LAZY en la rama miss (abajo), para que dispatch_router NO importe forge_router (EXCLUIDO del
# cliente por D-A). Sin forge (cliente sin puente) → honest-fail, nunca crash.


# vendor_kind / source que cuentan como "VERIFICADO" (anti-impostor): namespace probado por
# DNS o cuenta de GitHub, o un override curado (pin/manual, lock duro). Lo demás (comunidad
# sin ownership, cache) NO es prueba de identidad → cae a la forja.
_VERIFIED_KINDS = {"dns", "github_org", "curated_manual"}
_VERIFIED_SOURCES = {"curated", "curated_pin"}

_URL_RE = re.compile(r"^(https?://|ftp://)", re.I)


def _looks_like_url(s: str) -> bool:
    return bool(_URL_RE.match((s or "").strip()))


def _relay_forge_to_control(body, authorization):
    """[Casa 2 · Fase 4 · 4.2.d.1] EL PUENTE: el cliente (sin forge/) relaya la FORJA al plano
    de control. POST streaming a `${control_url}/v1/inspect/forge` reenviando el Bearer; yield-ea
    el SSE de control verbatim. Bordes honestos (402/401/inalcanzable), NUNCA crash.

    Propiedad de seguridad (D1): el payload NO lleva NINGÚN tier — el cliente no puede autorizar
    construcción; el control lee su tier AUTORITATIVO (users.tier del webhook de Dodo) y decide.
    La rama miss del dispatcher lo consume con `yield from`.
    """
    import json as _json
    import urllib.error as _uerr
    import urllib.request as _ureq
    try:
        import aleph_paths as _ap
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
        import aleph_paths as _ap

    # DispatchRequest → ForgeRequest (mismos campos salvo url/cred). Sin tier: ver docstring.
    payload = {
        "url": body.url or body.service, "cred": body.credential, "forma": body.forma,
        "puppet_id": body.puppet_id, "slug": body.slug, "local_target": body.local_target,
        "auth_in": body.auth_in, "auth_param": body.auth_param, "auth_header": body.auth_header,
        "auth_template": body.auth_template, "validate_path": body.validate_path,
        "validate_query": body.validate_query, "api_shape_hint": body.api_shape_hint,
        "login_path": body.login_path, "login_credentials": body.login_credentials,
        "login_token_where": body.login_token_where, "login_token_key": body.login_token_key,
        "login_inject_where": body.login_inject_where, "login_inject_name": body.login_inject_name,
        "login_inject_template": body.login_inject_template, "login_body_format": body.login_body_format,
        "session_key": body.session_key, "login_url": body.login_url,
        "max_rounds": body.max_rounds, "max_calls": body.max_calls, "max_tokens": body.max_tokens,
        "synth_alias": body.synth_alias, "seed_probes": body.seed_probes,
    }
    req = _ureq.Request(
        _ap.control_url() + "/v1/inspect/forge", data=_json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": authorization or "",
                 "Accept": "text/event-stream"}, method="POST")
    try:
        resp = _ureq.urlopen(req, timeout=300)
    except _uerr.HTTPError as e:
        detail = {}
        try:
            detail = _json.loads(e.read().decode("utf-8", "ignore")) or {}
        except Exception:  # noqa: BLE001
            detail = {}
        if e.code == 402:      # el control NIEGA por tier (el muro AUTORITATIVO) → relay honesto
            d = detail.get("detail", detail)
            yield _sse({"type": "dispatch.denied", "origin": "forged", "tier_gated": True,
                        **(d if isinstance(d, dict) else {}), "reason": "forjar = premium"})
            yield _sse({"type": "cerrado", "path": "premium", "encontrado": False,
                        "forjado": False, "ok": False, "tier_gated": True})
        elif e.code == 401:
            yield _sse({"type": "error", "stage": "forjar", "origin": "forged",
                        "detail": "sesión inválida contra el control-plane (reconecta tu cuenta)"})
            yield _sse({"type": "cerrado", "path": "miss", "encontrado": False, "forjado": False, "ok": False})
        else:
            yield _sse({"type": "error", "stage": "forjar", "origin": "forged",
                        "detail": f"el control-plane devolvió {e.code}"})
            yield _sse({"type": "cerrado", "path": "miss", "encontrado": False, "forjado": False, "ok": False})
        return
    except (_uerr.URLError, OSError):
        yield _sse({"type": "error", "stage": "forjar", "origin": "forged",
                    "detail": "control-plane no disponible — reintenta en un momento"})
        yield _sse({"type": "cerrado", "path": "miss", "encontrado": False, "forjado": False, "ok": False})
        return

    try:                       # OK: relay del SSE de control, verbatim (ya viene framed)
        with resp:
            for raw in resp:
                yield raw.decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        yield _sse({"type": "error", "stage": "forjar", "origin": "forged",
                    "detail": "el stream con el control-plane se cortó"})
        yield _sse({"type": "cerrado", "path": "miss", "encontrado": False, "forjado": False, "ok": False})


class DispatchRequest(BaseModel):
    """El usuario apunta a un software por NOMBRE (resolver) y trae su credencial. `url` es la
    base REST para el Motor B si el resolver da miss (default: `service` si ya es una URL)."""
    service: str
    credential: Optional[str] = None
    url: Optional[str] = None
    puppet_id: Optional[str] = None
    # [ssrf-consent] opt-in "es mi servidor self-hosted": viaja al Motor B en el camino MISS (forja).
    local_target: bool = False
    # perillas del Motor B (camino miss) — idénticas a ForgeRequest (defaults = Forma 1 / TMDB)
    forma: str = "token"
    auth_in: str = "query"
    auth_param: str = "api_key"
    auth_header: str = "Authorization"
    auth_template: str = "Bearer {token}"
    validate_path: str = "/configuration"
    validate_query: Optional[dict] = None
    slug: Optional[str] = None
    max_rounds: int = 3
    max_calls: int = 30
    max_tokens: int = 300_000
    synth_alias: str = "oss"
    seed_probes: Optional[list[dict]] = None
    # ── [2f-formas] pista de forma (opcional) + campos de FORMA 2 (login API) ────────
    # Idénticos a ForgeRequest; sólo viajan al Motor B en el camino MISS (forja).
    api_shape_hint: str = ""
    login_path: str = "/login"
    login_credentials: Optional[dict] = None
    login_token_where: str = "json"
    login_token_key: str = "access_token"
    login_inject_where: str = "header"
    login_inject_name: str = "Authorization"
    login_inject_template: str = "Bearer {token}"
    login_body_format: str = "json"
    # ── [3-browser-oauth] FORMA 3 (navegador · OAuth+2FA) ────────────────────────────
    # La sesión la capturó el HUMANO (browser instrumentado + 2FA) vía /v1/inspect/session/browser;
    # acá sólo viaja su `session_key` para que el Motor B la REUSE en el camino de forja.
    session_key: Optional[str] = None
    login_url: Optional[str] = None
    # ── verificación (env-gated) ───────────────────────────────────────────────────
    seed_candidates: Optional[list[dict]] = None   # arbitrados por el matcher REAL
    seed_spec: Optional[dict] = None               # run-spec del equip (MCP local real)


class _Decision:
    """El resultado de consultar el resolver: confiable | con reserva | miss.

    ``scrutiny`` contiene únicamente material que el registro y el matcher ya midieron.
    Es el insumo para la reserva persistida; no es una segunda clasificación.
    """
    def __init__(self, *, found: bool, confiable: bool = False, server_name: str = "",
                 spec: Optional[dict] = None, vendor_kind: str = "", source: str = "",
                 ranked: Optional[list] = None, reason: str = "", verified: bool = False,
                 rejected_impostor: bool = False, error: bool = False,
                 registry_down: bool = False, from_cache: bool = False,
                 scrutiny: Optional[dict] = None, trusted_server: str = ""):
        self.found = found
        self.confiable = confiable
        self.server_name = server_name
        self.spec = spec
        self.vendor_kind = vendor_kind
        self.source = source
        self.ranked = ranked or []
        self.reason = reason
        self.verified = verified
        self.rejected_impostor = rejected_impostor
        self.error = error
        # [T-3] el registro público no respondió: NO es un miss (inexistencia). El caller NO debe
        # forjar a ciegas — debe pedir reintentar. Distinto de found=False por miss legítimo.
        self.registry_down = registry_down
        # [T-3] la resolución vino de CACHE durante un outage del registro (degradación graceful):
        # found=True pero el caller debe SURFACEARLO honesto ("traje lo guardado, catálogo caído").
        self.from_cache = from_cache
        self.scrutiny = scrutiny or {}
        # [OBRA 6c] CUÁL ERA LA BUENA, cuando sabemos que la elegida no lo es. Antes esa
        # comparación vivía en el router, que confrontaba el `server_name` elegido contra el
        # ganador de re-descubrir el servicio; resolviendo por la pieza tocada el ganador ES el
        # elegido, así que la señal tenía que mudarse a la decisión o se perdía.
        self.trusted_server = trusted_server


def _is_verified(vendor_kind: str, source: str) -> bool:
    return (vendor_kind in _VERIFIED_KINDS) or (source in _VERIFIED_SOURCES)


def _ranked_brief(ranked: list) -> list:
    out = []
    for r in (ranked or [])[:5]:
        cand = r.get("candidate") if isinstance(r, dict) else None
        out.append({
            "name": (cand or {}).get("name") if cand else r.get("name"),
            "score": round(float(r.get("score", 0.0)), 4),
            "verified": bool(r.get("verified_vendor", r.get("verified", False))),
        })
    return out


def _scrutiny_material(candidate: Optional[dict], scored: Optional[dict]) -> dict:
    """Material de escrutinio, sin reinterpretar ni inventar requisitos.

    La ingesta ya tiene los extractores que leen headers/env declarados y las tools del
    manifest. Reusarlos mantiene una sola semántica entre el catálogo y el consentimiento.
    """
    candidate = candidate if isinstance(candidate, dict) else {}
    scored = scored if isinstance(scored, dict) else {}
    try:
        from app.phase1.catalog_ingest_router import scrutiny_consequences, scrutiny_requirements
        requisitos = scrutiny_requirements(candidate)
        consecuencias = scrutiny_consequences(candidate)
    except Exception:  # la reserva nunca inventa datos si un extractor no está disponible
        requisitos = {"requisito": "ninguno", "headers": [], "entorno": [],
                       "paquetes": [], "remotos": [], "medido": False}
        consecuencias = "se_sabra_al_conectar"
    return {
        "requisitos": requisitos,
        "senales": {
            "score": round(float(scored.get("score") or 0.0), 4),
            "verified_vendor": bool(scored.get("verified_vendor")),
            "signals": dict(scored.get("signals") or {}),
        },
        "consecuencias": consecuencias,
    }


def _dudoso_desde_ranked(service: str, ranked: list, spec: Optional[dict] = None) -> Optional[_Decision]:
    """El mejor candidato ejecutable sin ownership probado es *dudoso*, no inexistente.

    El matcher conserva el umbral estricto para marcar algo confiable. El consentimiento no
    lo rebaja: sólo permite que el usuario elija una pieza concreta y activa cuyo contrato
    de ejecución el registro sí publicó. Sin pieza ejecutable sigue siendo miss duro.
    """
    for scored in ranked or []:
        cand = scored.get("candidate") if isinstance(scored, dict) else None
        if not isinstance(cand, dict):
            continue
        if cand.get("status") != "active" or not cand.get("is_latest"):
            continue
        return _Decision(
            found=True, confiable=False, server_name=cand.get("name") or service,
            spec=spec, vendor_kind=cand.get("vendor_kind", ""),
            source=cand.get("source", "registry"), ranked=_ranked_brief(ranked),
            reason="candidato activo sin prueba de ownership", verified=False,
            scrutiny=_scrutiny_material(cand, scored))
    return None


def _decision_por_pieza(server_name: str, intent: str) -> _Decision:
    """[OBRA 6c] LA DECISIÓN SOBRE LA PIEZA QUE EL USUARIO TOCÓ, no sobre lo que tecleó.

    El equip tenía el mismo defecto que la ficha —re-adivinaba la identidad desde un string de
    presentación—, y del lado que ESCRIBE en el registro del usuario, que es peor: podía traer
    una pieza distinta de la que se eligió. Acá la identidad llega dada y sólo se resuelve
    CÓMO correr esa pieza, reusando el mismo `_exec_spec` del resolver.
    """
    from inspection import mcp_registry, mcp_resolver

    v = mcp_resolver.classify_server(server_name, intent=intent)
    if v.get("registry_status") == "unreachable":
        # [T-3] inalcanzable ≠ inexistente: no forjar a ciegas, pedir reintento.
        return _Decision(found=False, reason=v.get("reason", ""), error=True, registry_down=True)

    # EL IMPOSTOR SE FRENA ANTES DE MIRAR EL CANDIDATO, y el orden no es cosmético: el
    # clasificador corta por el pin curado sin llegar a pedirle la pieza al registro, así que
    # en ese camino `_candidate` viene vacío. Con el chequeo abajo, un impostor pineado caía
    # en «no la encontré» y perdía su causa literal — medido por la vara, no supuesto.
    trusted = v.get("trusted_server") or ""
    if v.get("picked_is_trusted") is False and trusted:
        return _Decision(found=False, rejected_impostor=True, trusted_server=trusted,
                         server_name=server_name, reason=v.get("reason", ""))

    cand = v.get("_candidate")
    if cand is None:
        return _Decision(found=False, reason=v.get("reason", ""))

    try:
        spec = mcp_resolver._exec_spec(cand, mcp_registry.curated_entry(intent or server_name))
    except mcp_resolver.ResolveError as e:
        # La pieza existe pero el registro no publicó con qué correrla. Es un miss honesto con
        # su causa real, no un "no la encontré".
        return _Decision(found=False, reason=str(e), server_name=cand.get("name") or server_name)

    confiable = v.get("verdict") == mcp_resolver.VERDICT_TRUSTED
    return _Decision(
        found=True, confiable=confiable, server_name=cand.get("name") or server_name,
        spec=spec, vendor_kind=cand.get("vendor_kind", ""), source=cand.get("source", "registry"),
        ranked=[], reason=v.get("reason", ""), verified=bool(v.get("verified")),
        scrutiny=_scrutiny_material(cand, v.get("_scored") or {}))


def _resolve_decision(service: str, *, seed_candidates, seed_spec, seed_enabled: bool,
                      server_name: str = "") -> _Decision:
    """Consulta el resolver y DERIVA found-confiable | miss. No toca credenciales ni equipa.

    Anti-impostor: la decisión sale SIEMPRE del matcher real (best_match) — sembrado o vivo.

    [OBRA 6c] Con `server_name` la identidad ya está dada y se resuelve ESA pieza. La
    verificación sembrada conserva su camino intacto: es el banco offline del anti-impostor y
    no debe depender de la red."""
    from inspection import mcp_matcher, mcp_resolver

    # ── verificación: el matcher REAL arbitra los candidatos sembrados ──────────────
    if seed_enabled and seed_candidates is not None:
        ranked = mcp_matcher.rank(service, seed_candidates) if seed_candidates else []
        decision = mcp_matcher.best_match(service, seed_candidates)
        if decision["found"]:
            winner = decision["winner"]
            cand = winner["candidate"]
            vk = cand.get("vendor_kind", "")
            verified = bool(winner["verified_vendor"]) and _is_verified(vk, cand.get("source", ""))
            if verified:
                return _Decision(
                    found=True, confiable=True, server_name=cand.get("name") or service,
                    spec=seed_spec, vendor_kind=vk, source=cand.get("source", "registry"),
                    ranked=_ranked_brief(ranked), reason=decision["reason"], verified=True,
                    scrutiny=_scrutiny_material(cand, winner))
            # Encontrado sin ownership probado: es dudoso, no inexistente. El catálogo puede
            # abrirlo sólo con consentimiento explícito; el dispatcher común sigue en miss.
            return _Decision(
                found=True, confiable=False, server_name=cand.get("name") or service,
                spec=seed_spec, vendor_kind=vk, source=cand.get("source", "registry"),
                ranked=_ranked_brief(ranked), reason=decision["reason"], verified=False,
                scrutiny=_scrutiny_material(cand, winner))
        dudoso = _dudoso_desde_ranked(service, ranked, seed_spec)
        if dudoso is not None:
            return dudoso
        # Sin candidato activo ejecutable, no hay nada que el consentimiento pueda abrir.
        return _Decision(found=False, rejected_impostor=bool(seed_candidates),
                         reason=decision["reason"], ranked=_ranked_brief(ranked))

    # ── producción · la pieza elegida manda sobre la intención ──────────────────────
    if server_name:
        return _decision_por_pieza(server_name, service)

    # ── producción: el resolver vivo (registry + matcher + curado) ──────────────────
    try:
        r = mcp_resolver.resolve_service(service)
    except mcp_resolver.RegistryUnavailable as e:
        # [T-3] registro caído ≠ inexistente. Bandera propia → el stream corta honesto (reintentá),
        # NUNCA cae a la construcción de MCP ni afirma "no existe". DEBE ir ANTES de NotFound/
        # ResolveError (subclase de ResolveError; NotFound es hermana, no lo captura).
        return _Decision(found=False, reason=str(e), error=True, registry_down=True)
    except mcp_resolver.NotFound as e:
        # `resolve_service` colapsa «no confiable» y «nada» en NotFound. Para el catálogo
        # necesitamos conservar el tercer estado sin cambiar ese resolver sellado: repetimos
        # sólo la lectura pública, elegimos un candidato activo y reutilizamos SU _exec_spec.
        try:
            from inspection import mcp_registry
            candidates = mcp_registry.search(service)
            ranked = mcp_matcher.rank(service, candidates)
            decision = _dudoso_desde_ranked(service, ranked)
            if decision is not None:
                candidate = next(r["candidate"] for r in ranked
                                 if isinstance(r.get("candidate"), dict)
                                 and r["candidate"].get("status") == "active"
                                 and r["candidate"].get("is_latest"))
                decision.spec = mcp_resolver._exec_spec(  # mismo normalizador del resolver
                    candidate, mcp_registry.curated_entry(service))
                if decision.spec:
                    return decision
        except mcp_registry.RegistryError:
            return _Decision(found=False, reason="registro público inalcanzable", error=True,
                             registry_down=True)
        except Exception:
            pass
        return _Decision(found=False, reason=str(e))
    except mcp_resolver.ResolveError as e:
        return _Decision(found=False, reason=str(e), error=True)
    vk, src = r.get("vendor_kind", ""), r.get("source", "")
    from_cache = bool(r.get("from_cache"))
    verified = _is_verified(vk, src)
    if not verified:
        # [T-3] si esto vino de CACHE durante un outage y NO quedó verificado, NO forjamos a
        # ciegas (mismo daño de T-3): cortamos honesto como registro caído (reintentá). Sólo el
        # miss legítimo con registro VIVO cae a la construcción de MCP.
        if from_cache:
            return _Decision(found=False, registry_down=True, from_cache=True, error=True,
                             reason=r.get("reason") or "registro caído; la cache no está verificada")
        match = r.get("match") if isinstance(r.get("match"), dict) else {}
        candidate = match.get("candidate") if isinstance(match.get("candidate"), dict) else {}
        return _Decision(
            found=True, confiable=False, server_name=r.get("server_name") or service,
            spec=r.get("spec"), vendor_kind=vk, source=src,
            ranked=r.get("ranked", []), reason=(
                f"el resolver encontró {r['server_name']} pero su namespace no está verificado "
                f"({vk or 'desconocido'})"),
            scrutiny=_scrutiny_material(candidate, match))
    match = r.get("match") if isinstance(r.get("match"), dict) else {}
    candidate = match.get("candidate") if isinstance(match.get("candidate"), dict) else {}
    return _Decision(found=True, confiable=True, server_name=r["server_name"], spec=r["spec"],
                     vendor_kind=vk, source=src, ranked=r.get("ranked", []),
                     reason=r.get("reason", ""), verified=True, from_cache=from_cache,
                     scrutiny=_scrutiny_material(candidate, match))


def build_dispatch_router(*, get_conn=None) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["dispatch"])

    @router.post("/inspect/dispatch")
    def dispatch(body: DispatchRequest, authorization: Optional[str] = Header(default=None)):
        service = (body.service or "").strip()
        if not service:
            raise HTTPException(status_code=400, detail={"error": "service_requerido"})

        seed_enabled = os.environ.get(
            "PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES", "") not in ("", "0", "false", "no")

        # sesión (para equipar en el puppet del usuario, anti-IDOR) — opcional (anon equipa anon)
        user_id = None
        try:
            from app.phase1 import repo
            a = (authorization or "").strip()
            tok = a[7:].strip() if a.lower().startswith("bearer ") else (a or None)
            user_id = repo.session_owner(tok) if tok else None
        except Exception:
            user_id = None

        # [defense-in-depth] rate-limit por sujeto (el resolver y el motor REVALIDAN igual)
        subject = (body.puppet_id or "anon")
        try:
            from safety import rate_limit
            allowed, info = rate_limit.check_and_consume(subject, bucket="recon")
            if not allowed:
                raise HTTPException(status_code=429, detail={"error": "rate-limit de dispatch", **info})
        except ImportError:
            pass

        from inspection import contracts as C

        principal = C.Principal(
            user_id=user_id) if user_id else C.Principal(
            anon_id=f"disp-{body.puppet_id or 'anon'}-{uuid.uuid4().hex[:12]}")

        from app.phase1.forge_router import _FORMA_BROWSER  # noqa: E402
        is_browser = (body.forma or "token").strip().lower() in _FORMA_BROWSER

        async def stream():
            loop = asyncio.get_running_loop()
            target = body.url or (service if _looks_like_url(service) else "")
            yield _sse({"type": "dispatch.iniciado", "service": service, "target": target,
                        "puppet_id": body.puppet_id})

            # ── [3-browser-oauth] FORMA 3: un target detrás de OAuth+2FA NO es un MCP de registry
            # (la sesión la capturó el HUMANO). Saltamos el resolver y forjamos directo reusando la
            # sesión (session_key). Sin sesión capturada → corte honesto (cero-teatro).
            if is_browser:
                if not (body.session_key or "").strip():
                    for fr_ in [_sse({"type": "error", "stage": "forjar", "origin": "forged",
                                      "detail": ("forma='browser-oauth' necesita 'session_key' — "
                                                 "captura la sesión primero (browser + 2FA humano)")}),
                                _sse({"type": "cerrado", "path": "miss", "encontrado": False,
                                      "forjado": False, "ok": False})]:
                        yield fr_
                    return
                yield _sse({"type": "resolver.miss", "browser_oauth": True, "rejected_impostor": False,
                            "reason": ("forma navegador/OAuth: la sesión ya la capturó el humano "
                                       "(login+2FA) — forjo directo reusando la sesión, sin registry")})
            else:
                yield _sse({"type": "resolver.buscando", "service": service,
                            "registry": "registry.modelcontextprotocol.io"})

                # ── 1 · CONSULTAR EL RESOLVER (anti-impostor, sin tocar) ────────────────
                decision = await loop.run_in_executor(None, lambda: _resolve_decision(
                    service, seed_candidates=body.seed_candidates, seed_spec=body.seed_spec,
                    seed_enabled=seed_enabled))

                # ── 2·T-3 · REGISTRO CAÍDO → honesto: no forjamos a ciegas ni afirmamos inexistencia.
                # El false-empty (registro no responde → "no existe" → construyo desde cero) sería el
                # peor bug de esta superficie: le mentiría al usuario que su conector no existe. ──
                if decision.registry_down:
                    yield _sse({"type": "resolver.registry_down", "reason": decision.reason,
                                "registry": "registry.modelcontextprotocol.io", "retry": True})
                    yield _sse({"type": "cerrado", "path": "registry_down", "encontrado": False,
                                "forjado": False, "ok": False, "retry": True})
                    return

                # ── 2A · ENCONTRADO + VERIFICADO → equipar por el PATH 1-B (sin forjar) ──
                if decision.found and decision.confiable:
                    yield _sse({"type": "resolver.encontrado", "origin": "registry",
                                "server_name": decision.server_name, "vendor_kind": decision.vendor_kind,
                                "source": decision.source, "verified": decision.verified,
                                "from_cache": decision.from_cache, "reason": decision.reason,
                                "ranked": decision.ranked})
                    try:
                        probe, equipped = await loop.run_in_executor(
                            None, lambda: _equip_found(decision, body, principal, user_id,
                                                       get_conn=get_conn))
                    except Exception as exc:  # noqa: BLE001
                        yield _sse({"type": "error", "stage": "equipar", "origin": "registry",
                                    "detail": f"{type(exc).__name__}: {exc}"})
                        yield _sse({"type": "cerrado", "path": "registry", "encontrado": True,
                                    "forjado": False, "ok": False})
                        return
                    yield _sse({"type": "mcp.equipado", "origin": "registry",
                                "server": equipped.get("server"), "tools": equipped.get("tools", []),
                                "belt_ref": equipped.get("belt_ref"),
                                "puppet_id": body.puppet_id, "registered": equipped.get("registered"),
                                "tools_detail": [{"name": t["name"], "description": t.get("description", "")[:120]}
                                                 for t in probe.get("tools", [])]})
                    yield _sse({"type": "cerrado", "path": "registry", "encontrado": True,
                                "forjado": False, "ok": True, "server": equipped.get("server")})
                    return

                # ── 2B · MISS / NO-VERIFICADO / IMPOSTOR → recién acá, el MOTOR B ────────
                yield _sse({"type": "resolver.miss", "reason": decision.reason,
                            "rejected_impostor": decision.rejected_impostor,
                            "ranked": decision.ranked})

            forge_url = body.url or (service if _looks_like_url(service) else "")
            if not forge_url:
                # sin MCP en registry y sin URL para forjar desde cero → corte honesto.
                yield _sse({"type": "error", "stage": "forjar", "origin": "forged",
                            "detail": ("no hay MCP verificado en el registry y no diste una URL "
                                       "(`url`) para forjar desde cero")})
                yield _sse({"type": "cerrado", "path": "miss", "encontrado": False,
                            "forjado": False, "ok": False})
                return

            # [2f-formas] la FORMA rutea al SessionProvider del Motor B. Acá (stream ya abierto) NO
            # podemos levantar HTTPException, así que normalizamos en banda: Ola 3 / desconocida → error
            # honesto + cerrado (sin forjar). token→cred · login→login_credentials · abierto→sin cred.
            # [4.2.a · D-A] forge_router (Motor B) NO viaja al cliente. Import LAZY acá: en
            # dev/control resuelve local (forja in-process, byte-idéntico). En el cliente sin
            # forge → [4.2.d.1] RELAY al control plane (el moat vive server-side).
            try:
                from app.phase1.forge_router import (  # noqa: E402
                    ForgeRequest, _FORMA_ALIASES, provider_and_auth,
                    build_seed_candidates, run_forge_stream, enforce_construction_premium)
            except ImportError:
                # forge_router ausente (cliente) → el puente: relaya la forja al control, que
                # valida el Bearer + el tier AUTORITATIVO y forja. El cliente NO manda tier.
                # (relay síncrono: en el cliente local-first single-user está bien; async-hygiene
                # = follow-up. `async def` no admite `yield from`, así que loop explícito.)
                for _relay_frame in _relay_forge_to_control(body, authorization):
                    yield _relay_frame
                return
            fnorm = (body.forma or "token").strip().lower()

            def _cut(detail: str):
                return [_sse({"type": "error", "stage": "forjar", "origin": "forged", "detail": detail}),
                        _sse({"type": "cerrado", "path": "miss", "encontrado": False,
                              "forjado": False, "ok": False})]

            # [3-browser-oauth] navegador/OAuth+2FA → Forma 3 (reuso de la sesión humana capturada).
            if is_browser:
                forma = "browser"
                if not (body.session_key or "").strip():
                    for fr_ in _cut("forma='browser-oauth' necesita 'session_key' (captura la sesión primero)"):
                        yield fr_
                    return
            else:
                forma = _FORMA_ALIASES.get(fnorm)
                if forma is None:
                    for fr_ in _cut(f"forma='{body.forma}' no reconocida; usa 'abierto', 'token', 'login' o 'browser-oauth'"):
                        yield fr_
                    return
                if forma == "token" and not (body.credential or "").strip():
                    for fr_ in _cut("forma='token' necesita la credencial para forjar"):
                        yield fr_
                    return
                if forma == "login" and not (body.login_credentials or {}):
                    for fr_ in _cut("forma='login' necesita 'login_credentials' (p.ej. {username, password})"):
                        yield fr_
                    return

            # MURALLA PREMIUM · llegado acá el dispatcher NO encontró un MCP existente y va a
            # CONSTRUIR uno nuevo (Motor B) → es el MOAT (Premium). La búsqueda / equipar-existente
            # de arriba fue GRATIS; sólo la construcción cae. El stream ya está abierto, así que
            # negamos EN BANDA (SSE), no con HTTP. Server-side; anónimo/free/desconocido → rechazo.
            _rej = enforce_construction_premium(authorization)
            if _rej is not None:
                yield _sse({"type": "dispatch.denied", "tier_gated": True, "origin": "forged", **_rej})
                yield _sse({"type": "cerrado", "path": "premium", "encontrado": False,
                            "forjado": False, "ok": False, "tier_gated": True})
                return

            # marca de orden: lo que sigue es la FORJA (Motor B), no un MCP traído del registry.
            yield _sse({"type": "dispatch.forjando", "origin": "forged", "url": forge_url,
                        "forma": forma, "cerebro": f"alias:{body.synth_alias}"})

            host = re.sub(r"^https?://", "", forge_url).split("/")[0]
            slug = body.slug or f"disp-{_slug(host)}"
            from inspection.loop.budget import Budget
            budget = Budget(max_rounds=body.max_rounds, max_live_calls=body.max_calls,
                            max_synth_tokens=body.max_tokens)
            # el MISMO selector de provider que /v1/inspect/forge (provider_and_auth), vía un ForgeRequest
            # armado con las perillas del dispatch — token-query→None, token-header/abierto/login→real.
            fr = ForgeRequest(
                url=forge_url, cred=body.credential, forma=forma, puppet_id=body.puppet_id,
                local_target=body.local_target,  # [ssrf-consent] opt-in self-hosted → guard afloja SOLO este host
                auth_in=body.auth_in, auth_param=body.auth_param, auth_header=body.auth_header,
                auth_template=body.auth_template, validate_path=body.validate_path,
                validate_query=body.validate_query, api_shape_hint=body.api_shape_hint,
                login_path=body.login_path, login_credentials=body.login_credentials,
                login_token_where=body.login_token_where, login_token_key=body.login_token_key,
                login_inject_where=body.login_inject_where, login_inject_name=body.login_inject_name,
                login_inject_template=body.login_inject_template, login_body_format=body.login_body_format,
                session_key=body.session_key, login_url=body.login_url)  # [3-browser-oauth] reuso Forma 3
            # provider_and_auth SÓLO construye el provider (barato, sin red); el acquire() real
            # (login POST / validación abierta / guard SSRF) corre dentro del Motor B y, si la puerta
            # no abre, emite session.error → frame `error` (cero-teatro). Acá sólo cae un mal-armado.
            try:
                provider, eff_auth_param = provider_and_auth(forma, fr, principal, slug)
            except Exception as exc:  # noqa: BLE001
                for fr_ in _cut(f"no pude armar la sesión ({forma}): {type(exc).__name__}: {exc}"):
                    yield fr_
                return
            seed_candidates_forge = build_seed_candidates(body.seed_probes)

            # el MISMO Motor B que /v1/inspect/forge (run_internal_loop), sin reimplementar.
            from app.phase1.forge_router import _guard_for  # [ssrf-consent]
            async for frame in run_forge_stream(
                url=forge_url, cred=body.credential, forma=forma, puppet_id=body.puppet_id,
                slug=slug, principal=principal, budget=budget, provider=provider,
                seed_candidates=seed_candidates_forge, synth_alias=body.synth_alias,
                auth_param=eff_auth_param, validate_path=body.validate_path,
                validate_query=body.validate_query, emit_open=True,
                api_shape_hint=body.api_shape_hint,
                guard=_guard_for(fr),   # cubre el default token-query (provider None) del camino UI
            ):
                yield frame
            # el `cerrado` del contrato del motor ya cerró el stream del camino forjado.

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router


def _probe_pendiente(decision: _Decision) -> dict:
    """Probe declarativo para registrar una fila que espera una credencial.

    No suplanta la curación: no afirma que el servidor vive ni que sus tools respondieron.
    Sólo conserva la receta y los nombres de tool que el manifest ya declaró, para que la
    misma fila pueda entrar a la aduana y verificarse por el camino normal al recibir llave.
    """
    spec = decision.spec or {}
    consequences = (decision.scrutiny or {}).get("consecuencias")
    declared = consequences.get("declaradas") if isinstance(consequences, dict) else []
    tools = [{"name": str(name), "description": "declarada por el manifest"}
             for name in (declared or []) if str(name).strip()]
    probe = {"transport": spec.get("transport"), "tools": tools,
             "server_info": {"name": decision.server_name}}
    if spec.get("transport") == "http":
        probe["url"] = spec.get("url")
        probe["headers"] = {}
    else:
        probe["command"] = spec.get("command")
        probe["args"] = list(spec.get("args") or [])
        probe["env"] = {}
    return probe


def _equip_found(decision: _Decision, body: "DispatchRequest", principal: Any,
                 user_id: Optional[str], *, get_conn=None, reserva: Optional[dict] = None,
                 permitir_pendiente: bool = False):
    """PATH 1-B (el MISMO que /v1/resolve): vault round-trip → validate_live → equip_resolved.
    Devuelve (probe, equipped). Bloqueante → el caller lo corre en executor."""
    from inspection import mcp_resolver

    spec = decision.spec or {}
    needs = spec.get("needs_credential", True)
    secret = body.credential or ""

    # producción: la credencial del request → VAULT cifrado → se LEE de vuelta del vault para
    # validar (round-trip, no el request). Anon/verificación (sin user): se valida directo (el
    # MCP local fixture es keyless). equip_resolved persiste SIEMPRE un placeholder, no el secreto.
    conn = None
    if needs and secret and user_id:
        from app.phase1 import repo as _repo, credential_broker
        provider = mcp_resolver.provider_for(decision.server_name or body.service)
        _get_conn = get_conn or _repo.get_conn
        conn0 = _get_conn()
        try:
            _repo.upsert_key(conn0, user_id=user_id, provider=provider, secret=secret)
        finally:
            conn0.close()
        secret = credential_broker.make_user_resolver(user_id, get_conn=_get_conn)(f"keys:{provider}")
    if user_id:
        from app.phase1 import repo as _repo
        _get_conn = get_conn or _repo.get_conn
        conn = _get_conn()

    pendiente_credencial = bool(needs and not secret)
    if pendiente_credencial and not permitir_pendiente:
        raise mcp_resolver.ResolveError(
            f"{decision.server_name} requiere credencial pero no llegó ninguna")

    try:
        probe = (_probe_pendiente(decision) if pendiente_credencial
                 else mcp_resolver.validate_live(spec, secret, label=decision.server_name))
        resolution = {"spec": spec, "server_name": decision.server_name,
                      "source": decision.source, "vendor_kind": decision.vendor_kind}
        # [Ola 1 · seam] el Cuarto MANDA SIEMPRE un puppet_id (puppetIdOf), pero un usuario ANON no
        # tiene puppet en la DB ni conn → registrar server-side reventaría (_register_resolved →
        # get_puppet). El registro a la receta es BEST-EFFORT: sólo cuando hay conn real (usuario
        # autenticado). Sin conn → equip_resolved emite el MCP igual (registered:False) y el CLIENTE
        # lo equipa (equipResolvedMcp), SIMÉTRICO con el camino forja (mcp.forjado→placeTile). El
        # contrato de mcp.equipado NO cambia; el camino autenticado queda byte-idéntico.
        # [OBRA 6c] LA IDENTIDAD PRIMERO, Y NO ES CosmÉTICO: `equip_resolved` deriva de este
        # string el `provider` de la credencial (`provider_for`) y la clave de la cache. Con
        # `body.service` adelante, el nombre de la llave salía del TÍTULO del publicador —un
        # texto editable— mientras :662 la GUARDABA en el vault bajo `provider_for(server_name)`.
        # Medido en la DB real: la fila `byo-com-apify-apify-mcp-server` quedó con
        # `credencial_ref=resolver_apify_mcp_server` y en `keys` no hay ningún `resolver_*`.
        # Nadie perdió una llave todavía porque nadie llegó a pegar una; la próxima se habría
        # guardado con un nombre que la receta no busca.
        equipped = mcp_resolver.equip_resolved(
            resolution, probe, user_id=user_id,
            puppet_id=(body.puppet_id if conn is not None else None),
            service=(decision.server_name or body.service), conn=conn)
        if user_id:
            _mirror_equipped_connection(
                conn, user_id=user_id, equipped=equipped, probe=probe,
                credential_ref=(equipped.get("provider") if needs else None),
                reserva=reserva, pendiente_credencial=pendiente_credencial)
    finally:
        if conn is not None:
            conn.close()
    return probe, equipped


def _mirror_equipped_connection(conn, *, user_id: str, equipped: dict,
                                probe: dict, credential_ref: Optional[str],
                                reserva: Optional[dict] = None,
                                pendiente_credencial: bool = False) -> dict:
    """Pieza equipada → fila canónica de ``conexiones``.

    La primera escritura es INSERT; una medición posterior es UPDATE sobre la misma clave.
    Se reutilizan los traductores del backfill para que env/headers/transporte tengan la
    misma forma que las 41 existentes. No se levanta una lápida al re-verificar.
    """
    from app.phase1 import conexiones_backfill as BF
    from app.phase1 import conexiones_repo as CR

    entity_id = str(equipped.get("server") or "").strip()
    if not entity_id:
        raise ValueError("el equipado no trajo entity_id para conexiones")
    cfg = dict(equipped.get("cfg") or {})
    template, public = CR.repartir_env(cfg.get("env"))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    tools = list(probe.get("tools") or [])
    conexion = {
        "estado": "sin_sondear" if pendiente_credencial else "viva",
        "causa": None,
        "tool_usada": None,
        "belt_ref": equipped.get("belt_ref"),
        "evidencia": ({"esperando": "credencial",
                       "belt_ref": equipped.get("belt_ref"),
                       "tools_declaradas": [t.get("name") for t in tools if t.get("name")]}
                      if pendiente_credencial else
                      {"belt_ref": equipped.get("belt_ref"),
                       "tools_listadas": [t.get("name") for t in tools if t.get("name")]}),
        "ts": now,
    }
    fields = {
        "nombre_visible": equipped.get("label") or entity_id,
        "transporte": BF._transporte_de(cfg),
        "command": cfg.get("command") or None,
        "args": cfg.get("args") or None,
        "env_template": template or None,
        "env_publico": public or None,
        "recipe_version": "v1",
        "tools_snapshot": tools or None,
        "server_info": probe.get("server_info") or None,
        # ⚠️ [OBRA 6b · #7] ACÁ **NO** VA `ultimo_veredicto`, y su ausencia es el arreglo.
        #
        # Esa columna es MEMORIA DE LARGO PLAZO —«esta pieza ANDUVO alguna vez»— con un solo
        # valor con significado, `probado`, y una regla estricta: exige haber **INVOCADO**
        # una tool (`centro_conexiones.py:2010-2020`). El equip escribía ahí
        # `"viva"`/`"sin_sondear"`, que es vocabulario de medición VIVA, y el efecto medido
        # era doble y silencioso:
        #
        #   · `estuvo_completa` daba False sobre una pieza que Aleph había probado, porque
        #     `"viva" != "probado"`. Si esa pieza fallaba después, el clasificador la mandaba
        #     a la ADUANA como «nunca estuvo completa» en vez de tratarla como REGRESIÓN en
        #     el local: el yo-yo exacto que esa memoria existe para impedir.
        #   · y dejaba a las piezas traídas marcadas para siempre: `WHERE ultimo_veredicto
        #     <> ''` las separaba de las 41 con una sola consulta.
        #
        # Tampoco se escribe `probado`: sería OVERCLAIM. La curación conecta y LISTA las
        # tools; no invoca ninguna. Quien invoca es el barrido, y el barrido tiene prohibido
        # por contrato tocar el veredicto (`centro_conexiones.py:1902-1910`). Así que hoy
        # NADIE corona una conexión —medido: 0 filas con `probado` sobre 44— y esa deuda
        # queda NOMBRADA, no tapada: darle su verbo a la coronación es una decisión, no un
        # parche, y necesita su propia obra.
        #
        # El estado vivo no se pierde: `sin_sondear`/`viva` ya viven en `conexion.estado`,
        # que es su lugar y de donde la superficie los lee.
        "causa": None,
        "ultima_verificacion": now,
        "conexion": conexion,
    }
    fields.update(BF._receta_http_de(cfg))
    if credential_ref:
        fields["credencial_ref"] = credential_ref
    if pendiente_credencial:
        # No es un veredicto de llave: nombra honestamente que aún no se pudo medir porque
        # falta el único insumo del usuario. Sin esta marca el adaptador interpreta un vacío
        # como contradicción estructural y escondería la fila en vez de abrir su aduana.
        fields["credencial"] = {
            "estado": "sin_medir", "tool_prueba": None, "ts": now,
            "evidencia": "esperando la credencial declarada para verificar esta pieza",
        }
    if reserva is not None:
        fields["reserva"] = reserva

    # Los guards y la serialización son los del dueño común; sólo la elección explícita
    # INSERT/UPDATE vive acá porque el API público existente es un upsert y esta obra lo
    # prohíbe para distinguir nacimiento de re-verificación.
    for ref_field, public_field in CR._PARES_REPARTIDOS:
        if ref_field in fields:
            CR._sin_secretos(fields[ref_field], ref_field, public_field)
    if fields.get("transporte") not in CR.TRANSPORTES:
        raise ValueError(f"transporte de conexión inválido: {fields.get('transporte')!r}")
    columns = [name for name in CR._CAMPOS if name in fields]
    values = [CR._a_columna(name, fields[name]) for name in columns]
    existed = CR.leer_entidad(conn, user_id, entity_id) is not None
    with conn.cursor() as cur:
        if existed:
            assignments = ", ".join(f"{name} = %s" for name in columns)
            cur.execute(
                f"UPDATE conexiones SET {assignments}, updated_at = now() "
                "WHERE user_id = %s AND entity_id = %s RETURNING *",
                (*values, user_id, entity_id),
            )
        else:
            insert_fields = {**fields, "habilitado": True}
            columns = [name for name in CR._CAMPOS if name in insert_fields]
            values = [CR._a_columna(name, insert_fields[name]) for name in columns]
            cur.execute(
                f"INSERT INTO conexiones (user_id, entity_id, {', '.join(columns)}) "
                f"VALUES ({', '.join(['%s'] * (len(columns) + 2))}) RETURNING *",
                (user_id, entity_id, *values),
            )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        raise RuntimeError("conexiones no devolvió la fila escrita")
    equipped["connection_write"] = "update" if existed else "insert"
    return CR.leer_entidad(conn, user_id, entity_id) or {}
