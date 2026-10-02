"""
forge_router.py — LA COSTURA · la entrada HTTP al MOTOR B (Ola 0, cimiento secuencial).

`POST /v1/inspect/forge` es el cable que faltaba: hasta hoy el Motor B real (6 capas:
identificar→sesión→observar→sintetizar→validar→emitir, en platform/inspection/) sólo
se alcanzaba por CLI/selftests; NINGÚN archivo de product/ lo importaba. Este endpoint
lo invoca de verdad y emite, por SSE, el STREAM DE EVENTOS DEL CONTRATO capa por capa,
cada uno con su payload de evidencia CRUDA:

    sesion.ok → observando{url,…} → tool.propuesta{nombre,params,…}(×N)
      → tool.validando{nombre,request} → tool.validada{nombre,status,payload}
                                       / tool.descartada{nombre,motivo}
      → mcp.forjado{server,tools[],belt_ref,puppet_id}

CERO-TEATRO: cada evento mapea 1:1 a una acción REAL de una capa del motor (la traducción
vive en `_translate`, que SOLO lee lo que la capa ya produjo — engine emite los detalles
crudos vía `on_event`; ver el enrich aditivo [ola0-costura] en loop/engine.py). Si una tool
cae, sale `tool.descartada` con el motivo REAL (404/422/sobre-en-banda/lo que sea), no un
genérico. El SSRF guard (Capa 0) y el split read/write (§7) del motor se respetan tal cual
— este router NO los puentea: corre `run_internal_loop` con su guard y su candado intactos.

NO reemplaza a `/v1/inspect` (Motor A · recon-demo): corre en PARALELO. Esta ola implementa
SOLO forma="token" (Forma 1: token en query [TMDB] o header). El campo `forma` se ACEPTA
desde ya; las otras formas se rutearán al SessionProvider existente en olas posteriores.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# El Motor B vive en platform/inspection/ — asegurar que el backend pueda importarlo.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLATFORM = _REPO_ROOT / "platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

# [Casa 2 · Fase 4 · 4.2.a] _sse/_slug se mudaron a inspection/sse_util.py (zona SHARED) para
# poder EXCLUIR forge_router del cliente sin romper el import del dispatcher. Ver zones.py.
from inspection.sse_util import _sse, _slug  # noqa: E402


def _fingerprint(secret: str) -> str:
    """Huella NO reversible del token, para loggear/emitir sin filtrarlo."""
    import hashlib
    if not secret:
        return "∅"
    last4 = secret[-4:] if len(secret) >= 4 else "****"
    return f"sha256:{hashlib.sha256(secret.encode()).hexdigest()[:8]}…{last4}"


# ── MURALLA PREMIUM · gate server-side de la CONSTRUCCIÓN de un MCP NUEVO (el MOAT) ──────────
# CRITERIO DE LA FRONTERA (persona usuaria): SINTETIZAR-LO-INEXISTENTE = premium · REVALIDAR-LO-EXISTENTE = libre.
#   · Construir un conector NUEVO = invocar el Motor B (6 capas) sobre software que NO está en el
#     catálogo → PREMIUM (llama acá). Endpoints: /v1/inspect/forge y la rama forge de /dispatch.
#   · Conectar/usar/equipar los que YA existen (catálogo, registro, /byo, OAuth, sesión browser)
#     y CURAR uno del catálogo (revalidar tools, refrescar manifest, dropear tools rotas — el
#     health-check de drift, /v1/inspect/healthcheck) = GRATIS, server-side, y NO llama acá.
#   · "Un nivel más adentro": si una CURA ESCALA a sintetizar tools NUEVAS desde cero (una
#     capacidad que no existía), ESA síntesis-de-nuevo cae en ESTE gate (mismo principio). La
#     cura entrega al cliente SÓLO el resultado curado, nunca trazas del proceso (capas/prompts).
# El tier SIEMPRE sale de la CUENTA (sesión→users.tier), nunca del cliente; anónimo/desconocido →
# no-premium → rechazo (fail-closed).
_ENFORCE_CONSTRUCTION_ENV = "PUPPET_ENFORCE_MCP_CONSTRUCTION"


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    a = authorization.strip()
    return a[7:].strip() if a.lower().startswith("bearer ") else a


def enforce_construction_premium(authorization: Optional[str]) -> Optional[dict]:
    """None si se permite construir; rechazo honesto {error, feature, min_tier, tier_gated} si no.

    [Step 5 · P7] EL MURO ESTÁ ACTIVO POR DEFAULT. Hasta acá era "staged": el default era
    APAGADO y sólo lo prendía `start_caso3_stack.sh`, así que un build público donde nadie
    exportara la env corría SIN MURO — fail-open por omisión, marcado en el audit §0 del
    Step 5. El default de una capa de seguridad tiene que ser el seguro; la comodidad de dev
    se compra con una variable explícita, no al revés.

    Apagarlo exige `PUPPET_ENFORCE_MCP_CONSTRUCTION=0` (o false/no/off): opt-out para dev/CI
    y los verificadores manuales. Cualquier otro valor —o su AUSENCIA— deja el muro puesto.
    Activo: el tier sale de la CUENTA; free/anónimo/desconocido → rechazo. Ante cualquier
    falla resolviendo el tier o cargando la capa → NIEGA (fail-closed: mejor construir
    bloqueado-por-error que abierto-por-error — se te vacía el moat)."""
    # [4.4.3] founder = build TODO DESBLOQUEADO → muro OFF. Seguro: is_founder() lee el build
    # HORNEADO (ALEPH_BUILD=founder), que sólo existe en el artefacto privado del dueño (nunca
    # distribuido) y NO es override-able por env en un build shipped (baked gana). Un tier
    # 'founder' falsificado NO lo activa (esto no mira el tier). El artefacto public → is_founder
    # False → muro intacto.
    try:
        import build_id as _build
        if _build.is_founder():
            return None
    except Exception:
        pass  # ante duda, seguir al muro (fail-closed)
    if str(os.environ.get(_ENFORCE_CONSTRUCTION_ENV, "1")).strip().lower() in ("0", "false", "no", "off"):
        return None  # OPT-OUT EXPLÍCITO (dev/CI). La AUSENCIA de la env NO apaga el muro.
    try:
        from gates import tier_gate as _tg
    except Exception:
        return {"error": ("No pudimos verificar tu plan para construir un conector nuevo ahora. "
                          "Prueba de nuevo en un momento."),
                "feature": "mcp_construction", "min_tier": "basico", "tier_gated": True}
    tier = None
    try:
        from app.phase1 import repo as _repo
        tok = _bearer_token(authorization)
        user_id = _repo.session_owner(tok) if tok else None
        if user_id:
            conn = _repo.get_conn()
            try:
                tier = (_repo.get_user(conn, user_id) or {}).get("tier")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    except Exception:
        tier = None  # no se pudo resolver el tier → tratamos como no-premium (fail-closed)
    return _tg.require_feature("mcp_construction", tier)


class ForgeRequest(BaseModel):
    """El REQUEST del contrato. Núcleo: {url, cred, forma, puppet_id}. El resto son
    perillas OPCIONALES de colocación del token (default = TMDB · Forma 1 query); el
    verify sólo manda el núcleo."""
    url: str
    cred: Optional[str] = None          # el token (Forma 1)
    forma: str = "token"                # "abierto" | "token" | "login" (navegador/OAuth = Ola 3)
    puppet_id: Optional[str] = None     # se ECHA tal cual en mcp.forjado

    # ── [ssrf-consent] OPT-IN del usuario: "este es MI servidor self-hosted (loopback/red
    # privada)". Default False = guard estricto público-solo de siempre. En True, el guard
    # SSRF deja pasar http + el host:port EXACTO que el usuario declaró en `url` (y SÓLO ese;
    # todo lo demás sigue estricto → sin pivote a metadata ni a otros servicios internos).
    # El SSRF protege contra que el AGENTE sea engañado, no contra que el usuario apunte a lo suyo.
    local_target: bool = False

    # perillas opcionales (colocación/validación del token) — defaults = TMDB
    auth_in: str = "query"              # "query" | "header"
    auth_param: str = "api_key"         # query: nombre del param
    auth_header: str = "Authorization"  # header: nombre del header
    auth_template: str = "Bearer {token}"  # header: template ({token} = el secreto)
    validate_path: str = "/configuration"  # endpoint "describite" para validar la sesión
    validate_query: Optional[dict] = None
    slug: Optional[str] = None
    max_rounds: int = 3
    max_calls: int = 30
    max_tokens: int = 300_000
    # cerebro del sintetizador (§3). Default "oss" = Groq gpt-oss-120b (forja real; el shim
    # :8923 no forja). "oss-weak" (llama-8b) alucina más; ambos viven en Groq.
    synth_alias: str = "oss"
    # EDGE PROBES opcionales (§3 pide "sondear el borde"): endpoints candidatos que el caller
    # siembra y que pasan por el MISMO candado contra el target vivo. Útil cuando el cerebro
    # es demasiado conservador (TMDB es tan conocido que ni gpt-oss-120b alucina) y querés
    # EJERCITAR el camino tool.descartada con un 404 REAL. Cada item: {name, endpoint,
    # path_params?, query?, kind?}. Si existen → verifican; si 404ean → drop real.
    seed_probes: Optional[list[dict]] = None

    # ── [2f-formas] pista de forma (opcional) para guiar al sintetizador en APIs no-TMDB.
    # NO es teatro: el validador (Capa 4) igual golpea el target VIVO; la pista sólo orienta
    # QUÉ endpoints proponer (el motor ya la consume vía `api_shape_hint`). Default "" = sin pista.
    api_shape_hint: str = ""

    # ── [2f-formas] FORMA 2 (login API) · campos del login; SÓLO se usan con forma="login".
    # Rutean DIRECTO al LoginAPISession del Motor B (no se reimplementa la lógica de sesión).
    login_path: str = "/login"
    login_credentials: Optional[dict] = None      # {"username":…, "password":…} | {"client_id":…, …}
    login_token_where: str = "json"               # de DÓNDE sale el token de la respuesta: json|header|cookie
    login_token_key: str = "access_token"         # path/clave del token en esa respuesta
    login_inject_where: str = "header"            # CÓMO se inyecta luego en cada request: header|cookie|query
    login_inject_name: str = "Authorization"
    login_inject_template: str = "Bearer {token}"
    login_body_format: str = "json"               # cuerpo del POST de login: json|form

    # ── [3-browser-oauth] FORMA 3 (navegador · OAuth+2FA) · SÓLO se usa con forma="browser-oauth".
    # La sesión la capturó ANTES el HUMANO vía POST /v1/inspect/session/browser (abre un navegador
    # instrumentado, el humano hace login+2FA, se guarda el storage_state CIFRADO). Acá el forge
    # NO reabre el navegador: REUSA esa sesión por su `session_key` (línea roja §2: el motor nunca
    # resuelve 2FA). Sin sesión capturada para esa key → el provider corta honesto (no hay sesión).
    session_key: Optional[str] = None             # capability devuelta por la captura (reuse-only)
    login_url: Optional[str] = None               # informativo; el guard lo revalida


# ── [ssrf-consent] el guard SSRF de la sesión ─────────────────────────────────────────
def _guard_for(body: "ForgeRequest"):
    """Default = PublicHTTPGuard (estricto público-solo, el de siempre). Con el opt-in
    `local_target`, devuelve un guard que afloja SÓLO el host:port EXACTO declarado en `body.url`
    (self-hosted: http + loopback/privado) y deja TODO lo demás estricto — sin pivote SSRF."""
    from inspection.loop.guard import PublicHTTPGuard, declared_target_guard
    if getattr(body, "local_target", False):
        return declared_target_guard(body.url)
    return PublicHTTPGuard()


# ── Provider Forma 1 · token en HEADER (el de query lo da el motor por default) ──────
def _build_header_provider(body: "ForgeRequest", principal, slug: str):
    """Forma 1 con el token en un header (p.ej. `Authorization: Bearer …`). Espeja la
    puerta del motor (TMDBTokenSession, que es token-en-query): guard SSRF → cifra la
    credencial en el vault Fernet por-principal → valida la sesión VIVA → Session con el
    header inyectado. Vive en el backend (la costura traduce el request a una invocación
    del motor); NO modifica platform/inspection/."""
    from inspection import contracts as C
    from inspection.loop.guard import PublicHTTPGuard
    from inspection.loop.live_http import LiveHTTP

    class _HeaderTokenSession(C.SessionProvider):
        form = C.AuthForm.TOKEN

        def __init__(self):
            self.base_url = body.url.rstrip("/")
            self._token = body.cred or ""
            self.principal = principal
            self.slug = slug
            self._guard = _guard_for(body)
            self._store = C.FernetCredentialStore(principal, slug, root=C.SYNTH_BELTS_DIR)

        @property
        def secret(self) -> str:
            return self._token

        @property
        def store(self):
            return self._store

        def acquire(self) -> "C.Session":
            verdict = self._guard.check(self.base_url)
            if not verdict:
                raise C.SessionError(f"guard SSRF bloqueó {self.base_url}: {verdict.reason}")
            self._store.put("API_KEY", self._token)
            headers = {body.auth_header: body.auth_template.format(token=self._token)}
            http = LiveHTTP(secret="", auth_param="", headers=headers)
            res = http.get(self.base_url + body.validate_path, body.validate_query or None)
            if res.status in (401, 403):
                raise C.SessionError(
                    f"token inválido ({res.status}) en {body.validate_path} — la puerta no miente")
            if res.status == 0:
                raise C.SessionError(f"target inalcanzable: {res.reason}")
            if not res.ok:
                raise C.SessionError(f"validación devolvió {res.status} en {body.validate_path}")
            return C.Session(
                form=self.form, base_url=self.base_url, headers=headers, cookies={},
                meta={
                    "auth_form": "token_header", "auth_header": body.auth_header,
                    "key_fingerprint": _fingerprint(self._token),
                    "validated_by": body.validate_path, "validate_status": res.status,
                    "cred_ref": f"{C.credential_namespace(self.principal)}/{self.slug}#API_KEY",
                },
            )

    return _HeaderTokenSession()


# ── Provider Forma ABIERTO (open) · software que se autodescribe SIN credencial ──────
def _build_open_provider(body: "ForgeRequest", principal, slug: str):
    """Forma ABIERTO (§2): el target se AUTODESCRIBE sin login. No hay credencial que cifrar;
    la puerta sólo confirma que el target responde (2xx) en el endpoint de descripción. CERO-
    TEATRO: si el target en realidad pide credencial (401/403), la sesión NO vale — la puerta
    no miente. Vive en el backend (espeja `_HeaderTokenSession`); NO modifica platform/inspection/."""
    from inspection import contracts as C
    from inspection.loop.guard import PublicHTTPGuard
    from inspection.loop.live_http import LiveHTTP

    class _OpenSession(C.SessionProvider):
        form = C.AuthForm.OPEN

        def __init__(self):
            self.base_url = body.url.rstrip("/")
            self.principal = principal
            self.slug = slug
            self._guard = _guard_for(body)

        @property
        def secret(self) -> str:
            return ""   # abierto = sin credencial (el loop no inyecta nada)

        def acquire(self) -> "C.Session":
            verdict = self._guard.check(self.base_url)
            if not verdict:
                raise C.SessionError(f"guard SSRF bloqueó {self.base_url}: {verdict.reason}")
            http = LiveHTTP(secret="", auth_param="", headers={})   # sin auth
            res = http.get(self.base_url + body.validate_path, body.validate_query or None)
            if res.status in (401, 403):
                raise C.SessionError(
                    f"este target NO es abierto: pide credencial ({res.status}) en "
                    f"{body.validate_path} — usa forma='token' o 'login'")
            if res.status == 0:
                raise C.SessionError(f"target inalcanzable: {res.reason}")
            if not res.ok:
                raise C.SessionError(
                    f"validación devolvió {res.status} (no 2xx) en {body.validate_path}")
            return C.Session(
                form=self.form, base_url=self.base_url, headers={}, cookies={},
                meta={"auth_form": "open", "validated_by": body.validate_path,
                      "validate_status": res.status, "cred_ref": ""},
            )

    return _OpenSession()


# ── Provider Forma 2 (login API) · RUTEO al LoginAPISession del Motor B (no se reimplementa) ─
def _build_login_provider(body: "ForgeRequest", principal, slug: str):
    """Forma 2 (login definido por la API). NO reimplementa la lógica de login: instancia el
    `LoginAPISession` REAL del Motor B (platform/inspection/loop/session_login.py) con los campos
    del request. El motor POSTea las credenciales, extrae la sesión que la API devuelve, la
    inyecta uniforme y la valida viva; la LÍNEA ROJA (2FA/MFA → Forma 3) vive en ESE provider."""
    from inspection.loop.session_login import (
        AuthInjection, LoginAPISession, TokenSource)
    creds = dict(body.login_credentials or {})
    if not creds:
        raise ValueError("forma='login' necesita credenciales (login_credentials).")
    return LoginAPISession(
        body.url, body.login_path, creds, principal, slug,
        token_source=TokenSource(body.login_token_where, body.login_token_key),
        inject_as=AuthInjection(body.login_inject_where, body.login_inject_name,
                                body.login_inject_template),
        body_format=body.login_body_format,
        validate_path=body.validate_path,
        guard=_guard_for(body),
    )


# ── Provider Forma 3 (navegador · OAuth+2FA) · REUSO de la sesión que capturó el HUMANO ──────
def _build_browser_oauth_provider(body: "ForgeRequest", principal, slug: str):
    """Forma 3 (navegador/OAuth+2FA). El HUMANO ya hizo login+2FA en un navegador instrumentado
    (POST /v1/inspect/session/browser) y su sesión quedó CIFRADA bajo `session_key`. Acá NO se
    reabre el navegador: se construye un `HumanBrowserSession` REUSE-ONLY (sin ready_when ni
    wait_human) → su `acquire()` SÓLO carga la sesión guardada por esa key; si no existe, corta
    honesto (SessionError) → el motor emite session.error (cero-teatro, sin sesión fantasma).

    LÍNEA ROJA §2: el motor NUNCA resuelve el 2FA — eso ya lo hizo el humano en la captura. Acá
    no hay dónde meter un secreto ni se toca el segundo factor; sólo se reusa la cookie/sesión."""
    from inspection.loop.session_browser import HumanBrowserSession
    key = (body.session_key or "").strip()
    if not key:
        raise ValueError("forma='browser-oauth' necesita 'session_key' (captura la sesión primero "
                         "con POST /v1/inspect/session/browser).")
    # reuse-only POR CONSTRUCCIÓN: sin ready_when ni wait_human → no abre navegador. Si la key no
    # tiene sesión guardada, acquire() levanta SessionError ("sin señal de fin de login").
    return HumanBrowserSession(
        body.url, principal, slug,
        login_url=body.login_url or body.url,
        storage_key=key,
    )


# ── Normalización de la FORMA + selección del provider (compartido con el dispatcher) ─
_FORMA_ALIASES = {"abierto": "open", "open": "open", "token": "token",
                  "login": "login", "login_api": "login", "login-api": "login"}
# Forma 3 (navegador / OAuth+2FA) — la hace el HUMANO en un navegador instrumentado; el forge
# REUSA la sesión capturada. [3-browser-oauth] reemplaza el 501 que dejó 2f-formas.
_FORMA_BROWSER = {"browser", "browser-oauth", "browser_oauth", "oauth", "oauth-2fa",
                  "human", "human_session", "navegador", "2fa", "mfa"}
# (ya no queda ninguna forma "sin implementar"; el set se conserva vacío por compat de import.)
_FORMA_OLA3: set[str] = set()


def resolve_forma(forma: str) -> str:
    """Normaliza la forma a {open|token|login|browser}; HTTPException 400 si es desconocida.
    [3-browser-oauth] 'navegador/OAuth+2FA' YA NO es 501 — se ruteó a la Forma 3 real (reuso)."""
    f = (forma or "token").strip().lower()
    if f in _FORMA_BROWSER:
        return "browser"
    if f in _FORMA_OLA3:  # defensivo: nada cae acá hoy (set vacío)
        raise HTTPException(status_code=501, detail={
            "error": "forma_no_implementada", "detail": f"forma='{forma}' aún no implementada."})
    norm = _FORMA_ALIASES.get(f)
    if norm is None:
        raise HTTPException(status_code=400, detail={
            "error": "forma_desconocida",
            "detail": f"forma='{forma}' no reconocida; usa 'abierto', 'token', 'login' o 'browser-oauth'."})
    return norm


def provider_and_auth(forma: str, body: "ForgeRequest", principal, slug: str):
    """Dada la forma YA normalizada, devuelve (provider, auth_param_efectivo) para el Motor B.
    token-query → provider None (el engine arma el default Forma 1); el resto → provider real."""
    if forma == "token":
        prov = _build_header_provider(body, principal, slug) if body.auth_in == "header" else None
        return prov, body.auth_param
    if forma == "open":
        return _build_open_provider(body, principal, slug), ""
    if forma == "login":
        prov = _build_login_provider(body, principal, slug)
        ap = body.login_inject_name if body.login_inject_where == "query" else body.auth_param
        return prov, ap
    if forma == "browser":
        # la auth de Forma 3 viaja en cookies/storage_state de la Session (no en query). El loop
        # las lee de la Session uniforme (engine: inline_auth por session.cookies) → auth_param "".
        return _build_browser_oauth_provider(body, principal, slug), ""
    raise HTTPException(status_code=400, detail={"error": "forma_desconocida", "detail": forma})


# ── Traducción engine-event → evento(s) del contrato (CERO-TEATRO) ──────────────────
def _request_of(params: dict, endpoint: str, method: str) -> dict:
    """Reconstruye el `request` REAL que el candado usó, desde el sample-call que el
    cerebro propuso (lo mismo que el validador resuelve y llama). Forma, no teatro."""
    sample = (params or {}).get("x-sample-call") or {}
    return {
        "method": method,
        "endpoint": endpoint,
        "path_params": sample.get("path_params") or {},
        "query": {k: v for k, v in (sample.get("query") or {}).items() if v not in (None, "")},
    }


def _status_of(verified_by: str) -> Optional[int]:
    """El status HTTP REAL detrás del veredicto del candado. Reads vivos → 200. Writes
    (verificados por forma: OPTIONS/schema/dry-run) NO se ejecutaron → sin status HTTP
    (None, honesto); el método de verificación viaja en `verified_by`."""
    vb = (verified_by or "").lower()
    if vb.startswith("200") or "dry-run" in vb:
        return 200
    return None


def _translate(ev: dict, *, target_url: str, puppet_id: Optional[str]) -> Iterable[dict]:
    """Un evento del motor → 0..N eventos del contrato. Cada uno mapea a una acción real."""
    t = ev.get("type")

    if t == "session.error":
        yield {"type": "error", "stage": "sesion", "detail": ev.get("detail", "")}

    elif t == "session.acquired":
        meta = ev.get("meta") or {}
        out = {"type": "sesion.ok", "form": ev.get("form"),
               "auth_form": meta.get("auth_form"),
               "key_fingerprint": meta.get("key_fingerprint"),
               "validated_by": meta.get("validated_by"),
               "validate_status": meta.get("validate_status"),
               "cred_ref": meta.get("cred_ref")}
        # [3-browser-oauth] Forma 3: prueba CRUDA de que la sesión humana se REUSÓ (cero-teatro).
        # Otras formas no fijan estas claves → None (no cambia su evento).
        for k in ("reused_session", "cookie_count", "origins_count", "red_line"):
            if k in meta:
                out[k] = meta.get(k)
        yield out

    elif t == "observe":
        yield {"type": "observando", "url": target_url, "round": ev.get("round"),
               "passive": ev.get("passive"), "mode": ev.get("mode"),
               "probed": ev.get("probed"), "new_confirmed": ev.get("new_confirmed") or []}

    elif t == "synth.start":
        # narración de Capa 3: el cerebro está pensando (puede sostener ~90s de silencio)
        yield {"type": "sintetizando", "round": ev.get("round"),
               "cerebro": f"alias:{ev.get('alias', '')}"}

    elif t == "synth":
        if ev.get("degraded"):
            # el cerebro (Groq) no respondió → corte honesto, sin fingir candidatas.
            yield {"type": "error", "stage": "sintesis", "degraded": True,
                   "detail": ev.get("reason", ""), "model": ev.get("model")}
        else:
            for c in ev.get("fresh_detail") or []:
                yield {"type": "tool.propuesta", "nombre": c.get("name"),
                       "endpoint": c.get("endpoint"), "method": c.get("method"),
                       "kind": c.get("kind"), "params": c.get("params") or {},
                       "description": c.get("description"), "round": ev.get("round"),
                       "model": ev.get("model")}

    elif t == "validate":
        # VERIFICADAS: validando (la llamada real) → validada (status + payload reales).
        for v in ev.get("verified_detail") or []:
            params = v.get("params") or {}
            yield {"type": "tool.validando", "nombre": v.get("name"), "round": ev.get("round"),
                   "request": _request_of(params, v.get("endpoint"), v.get("method"))}
            yield {"type": "tool.validada", "nombre": v.get("name"),
                   "status": _status_of(v.get("verified_by")),
                   "verified_by": v.get("verified_by"),
                   "payload": v.get("sample_response")}
        # DESCARTADAS: validando (también se llamaron) → descartada con el MOTIVO real.
        for f in ev.get("failed") or []:
            params = f.get("params") or {}
            yield {"type": "tool.validando", "nombre": f.get("name"), "round": ev.get("round"),
                   "request": _request_of(params, f.get("endpoint"), f.get("method"))}
            yield {"type": "tool.descartada", "nombre": f.get("name"),
                   "motivo": f.get("detail") or f.get("symptom"),
                   "symptom": f.get("symptom"), "clase": f.get("class"),
                   "move": f.get("move")}

    elif t == "forged":
        # la Capa 5 forjó el MCP desde las VERIFIED. server≠null, belt_ref real, y el
        # puppet_id ECHADO del request (el contrato lo exige no-hueco).
        # [forja-agentes] DUAL-MODE: `agents` lleva los sub-agentes equipados (agent_refs[]),
        # ADEMÁS de `tools`. Aditivo — un lector que sólo mira `tools` no se entera.
        yield {"type": "mcp.forjado", "server": ev.get("server_name"),
               "tools": ev.get("tools") or [], "belt_ref": ev.get("belt_ref"),
               "agents": ev.get("agents") or [],
               "puppet_id": puppet_id}

    elif t == "closed":
        yield {"type": "cerrado", "convergence": ev.get("convergence"),
               "verified": ev.get("verified"), "dropped": ev.get("dropped"),
               "degraded": ev.get("degraded"), "budget": ev.get("budget")}


# [4.2.a] _sse vive ahora en inspection/sse_util.py (importado arriba).


# ── El MOTOR B como stream reusable ───────────────────────────────────────────────────
# Extraído del endpoint para que OTRO caller (el dispatcher §0.5 / search-before-forge)
# pueda disparar la MISMA forja en su camino "miss" sin reimplementar el Motor B. El
# endpoint `/v1/inspect/forge` de abajo lo consume tal cual (comportamiento byte-equivalente);
# el dispatcher lo reusa con `emit_open=False` para anteponer sus propios frames de orden.
async def run_forge_stream(
    *, url: str, cred: Optional[str], forma: str, puppet_id: Optional[str], slug: str,
    principal: Any, budget: Any, provider: Any, seed_candidates: tuple,
    synth_alias: str, auth_param: str, validate_path: str,
    validate_query: Optional[dict], emit_open: bool = True, api_shape_hint: str = "",
    guard: Any = None,   # [ssrf-consent] guard para el default token-query (provider None); None = estricto
):
    """Corre `run_internal_loop` en un thread y emite, por SSE, el stream de eventos del
    contrato (sesion.ok → … → mcp.forjado → cerrado). NO puentea el guard/candado del motor."""
    from inspection.loop.engine import run_internal_loop

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    _DONE = object()

    def on_event(ev: dict) -> None:
        # corre en el thread del motor; reinyecta al event-loop de forma segura.
        loop.call_soon_threadsafe(q.put_nowait, ev)

    def run() -> None:
        try:
            run_internal_loop(
                url, cred, principal, slug=slug, budget=budget,
                on_event=on_event, synth_alias=synth_alias,  # default "oss" = Groq gpt-oss-120b
                auth_param=auth_param, validate_path=validate_path,
                validate_query=validate_query, provider=provider, guard=guard,
                seed_candidates=seed_candidates, api_shape_hint=api_shape_hint,
            )
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(
                q.put_nowait, {"type": "session.error", "detail": f"{type(exc).__name__}: {exc}"})
        finally:
            loop.call_soon_threadsafe(q.put_nowait, _DONE)

    threading.Thread(target=run, name=f"forge-{slug}", daemon=True).start()

    # frame de apertura (no es del contrato; marca el inicio del stream real).
    if emit_open:
        yield _sse({"type": "forge.iniciado", "url": url, "forma": forma,
                    "puppet_id": puppet_id, "cerebro": f"alias:{synth_alias}", "slug": slug})
    # LATIDO: si el motor calla (cerebro pensando, target lento) el stream narra igual —
    # un frame de transporte cada PUPPET_FORGE_HEARTBEAT_S. Solo dispara con la cola VACÍA,
    # jamás dentro de un batch de _translate (validando→validada quedan contiguos). hb=0
    # restaura el loop anterior exacto.
    hb = float(os.environ.get("PUPPET_FORGE_HEARTBEAT_S", "5") or 0)
    t0 = time.monotonic()
    last_stage: str = "forge.iniciado"
    last_round: Optional[int] = None
    while True:
        if hb > 0:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=hb)
            except asyncio.TimeoutError:
                yield _sse({"type": "forge.latido", "elapsed_s": int(time.monotonic() - t0),
                            "stage": last_stage, "round": last_round})
                continue
        else:
            ev = await q.get()
        if ev is _DONE:
            break
        for contract_ev in _translate(ev, target_url=url, puppet_id=puppet_id):
            last_stage = contract_ev.get("type") or last_stage
            if contract_ev.get("round") is not None:
                last_round = contract_ev.get("round")
            yield _sse(contract_ev)


def build_seed_candidates(seed_probes: Optional[list[dict]]) -> tuple:
    """EDGE PROBES (request) → CandidateTool, GATEADO por env (verification-only). En producto
    la env NO existe → devuelve () → la forja real nunca recibe sondas. Reusable por el
    dispatcher para pasar las mismas sondas a su camino de forja."""
    enabled = os.environ.get("PUPPET_FORGE_ALLOW_SEED_PROBES", "") not in ("", "0", "false", "no")
    if not (seed_probes and enabled):
        return ()
    from inspection import contracts as C
    return tuple(
        C.CandidateTool(
            name=p.get("name") or _slug(p.get("endpoint", "probe")),
            kind=C.ToolKind.WRITE if (p.get("kind") == "write") else C.ToolKind.READ,
            endpoint=p.get("endpoint", ""),
            method=(p.get("method") or "GET").upper(),
            input_schema={"type": "object", "x-sample-call": {
                "path_params": p.get("path_params") or {},
                "query": p.get("query") or {}}},
            description=p.get("description") or "edge probe sembrada por el caller (verification-only)",
        )
        for p in seed_probes if p.get("endpoint")
    )


# ── El endpoint ─────────────────────────────────────────────────────────────────────
def build_forge_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["forge"])

    # NOTA: el path /v1/forge YA está tomado por "LA FORJA" de recetas (phase1.router,
    # propone una receta desde intent+canvas). Esta costura es OTRA cosa — la entrada al
    # MOTOR B de inspección — así que vive en la familia /v1/inspect/* (junto a /v1/inspect
    # [Motor A] y /v1/inspect/byo). El nombre del método sigue siendo "forge": forja un MCP.
    @router.post("/inspect/forge")
    def forge(body: ForgeRequest, authorization: Optional[str] = Header(default=None)):
        # [2f-formas] la FORMA rutea al SessionProvider del Motor B. Ola 0 dejó "token" andando;
        # esta ola suma "abierto" (autodescriptivo, sin cred) y "login" (Forma 2 · login API).
        # "navegador/OAuth+2FA" = Forma 3 = Ola 3 → resolve_forma corta con 501 (hueco marcado).
        forma = resolve_forma(body.forma)
        if not (body.url or "").strip():
            raise HTTPException(status_code=400, detail={"error": "url_requerida"})
        if forma == "token" and not (body.cred or "").strip():
            raise HTTPException(status_code=400, detail={
                "error": "cred_requerida",
                "detail": "forma='token' necesita el token en 'cred'."})
        if forma == "login" and not (body.login_credentials or {}):
            raise HTTPException(status_code=400, detail={
                "error": "login_credentials_requeridas",
                "detail": "forma='login' necesita 'login_credentials' (p.ej. {username, password})."})
        if forma == "browser" and not (body.session_key or "").strip():
            # cero-teatro: sin sesión capturada NO hay forja. Primero la captura (browser+2FA humano).
            raise HTTPException(status_code=400, detail={
                "error": "session_key_requerida",
                "detail": ("forma='browser-oauth' necesita 'session_key' — captura la sesión primero "
                           "con POST /v1/inspect/session/browser (el HUMANO hace login+2FA).")})

        # MURALLA PREMIUM · construir un MCP NUEVO es el MOAT (Premium). Server-side; el frontend
        # puede mostrar "🔒 Premium", pero el que NIEGA es acá. 402 = mejorá tu plan. (Conectar/usar
        # los que YA existen NO llega a este endpoint.)
        _rej = enforce_construction_premium(authorization)
        if _rej is not None:
            raise HTTPException(status_code=402, detail=_rej)

        # [borde · defense-in-depth] rate-limit por sujeto + guard anti-SSRF de la URL —
        # el motor REVALIDA en su Capa 0, pero el borde no espera a llegar ahí. Honesto:
        # 429/400. (El guard del motor sigue siendo la autoridad; esto NO lo puentea.)
        subject = (body.puppet_id or "anon")
        try:
            from safety import rate_limit, url_guard
            allowed, info = rate_limit.check_and_consume(subject, bucket="recon")
            if not allowed:
                raise HTTPException(status_code=429, detail={"error": "rate-limit de forge", **info})
            # [ssrf-consent] con el opt-in local_target, el pre-filtro T9 del borde deja pasar el
            # loopback DECLARADO (allow_local_fixture — mecanismo tight ya existente: metadata/link-
            # local/multicast siguen bloqueados y desenvuelve v4-mapped). El guard del Motor B (Capa 0,
            # DeclaredLocalTargetGuard) sigue siendo la AUTORIDAD y acota al host:port exacto. Espeja
            # el camino /dispatch (que ya no pasa por este pre-filtro y llega directo a Capa 0).
            ok, reason = url_guard.is_safe(body.url.strip(),
                                          allow_local_fixture=bool(getattr(body, "local_target", False)))
            if not ok:
                raise HTTPException(status_code=400,
                                    detail={"error": "target sin derecho a inspección", "reason": reason})
        except ImportError:
            pass  # capa de safety ausente: el guard del motor (Capa 0) sigue mandando.

        from inspection import contracts as C
        from inspection.loop.budget import Budget

        host = re.sub(r"^https?://", "", body.url).split("/")[0]
        slug = body.slug or f"forge-{_slug(host)}"
        # Principal anónimo ÚNICO (no colisiona): el namespace del vault sale del anon_id.
        principal = C.Principal(anon_id=f"forge-{body.puppet_id or 'anon'}-{uuid.uuid4().hex[:12]}")
        budget = Budget(max_rounds=body.max_rounds, max_live_calls=body.max_calls,
                        max_synth_tokens=body.max_tokens)
        # provider según la FORMA: token-query → None (default Forma 1); token-header/abierto/login → real.
        try:
            provider, eff_auth_param = provider_and_auth(forma, body, principal, slug)
        except ValueError as e:
            raise HTTPException(status_code=400, detail={"error": "forma_invalida", "detail": str(e)})

        # EDGE PROBES → CandidateTool (read GET). Pasan por el candado real; cero atajo.
        # ⚠️ VERIFICATION-ONLY: sembrar endpoints-fantasma en la forja REAL de un usuario
        # sería cero-teatro al revés. Por eso el gancho está GATEADO por env
        # (PUPPET_FORGE_ALLOW_SEED_PROBES, ver build_seed_candidates): en producto la env NO
        # existe → seed_probes se IGNORA aunque venga en el request.
        seed_candidates = build_seed_candidates(body.seed_probes)

        return StreamingResponse(
            run_forge_stream(
                url=body.url, cred=body.cred, forma=forma, puppet_id=body.puppet_id,
                slug=slug, principal=principal, budget=budget, provider=provider,
                seed_candidates=seed_candidates, synth_alias=body.synth_alias,
                auth_param=eff_auth_param, validate_path=body.validate_path,
                validate_query=body.validate_query, api_shape_hint=body.api_shape_hint,
                guard=_guard_for(body)),   # [ssrf-consent] cubre el default token-query (provider None)
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router
