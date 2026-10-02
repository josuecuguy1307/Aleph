#!/usr/bin/env python3
"""
oauth_flow.py — Caso A (OAuth Authorization Code) GENÉRICO, data-driven.

Cero proveedor hardcodeado: toda la config vive en el onboarding object bajo `oauth`
(authorize_url, token_url, scope, client_id_env, client_secret_env, identity_field).
El router lo cablea al broker (repo.encrypt_secret/decrypt_secret + upsert_key) y al env.

SEGURIDAD:
  • CSRF: el `state` es un token Fernet (mismo secreto maestro del org, vía
    repo.encrypt_secret) que liga {user_id, provider, exp, nonce}. Un state ausente,
    manipulado, expirado o de OTRO provider no descifra/valida → callback rechazado.
    Mismo patrón tamper-proof que el token de sesión (repo.mint_session).
  • El client_secret JAMÁS sale al browser: el intercambio code→token es 100% server-side.
  • El access_token nunca se loguea ni se serializa a una respuesta — solo se entrega al
    broker (repo.upsert_key) que lo guarda cifrado; las respuestas exponen a lo sumo last4.

Las dos mitades testeables sin proveedor real (mint/read state, build URL, parse token)
viven acá puras; el HTTP del intercambio es inyectable (`http_post`) para el harness.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

_STATE_PREFIX = "alephoauth:v1:"
# [TEST-FIX step-4.5] TTL del state CSRF env-configurable. DEFAULT PROD = 600s (10 min, correcto).
# El test E2E lo sube (PUPPET_OAUTH_STATE_TTL=3600) para el consent manual sin pelear el reloj.
# NO mergear un default largo a prod (10 min es lo seguro para un CSRF state).
_DEFAULT_TTL = int(os.environ.get("PUPPET_OAUTH_STATE_TTL", "600"))  # 10 min — ventana para completar el consentimiento


# ── STATE / CSRF ────────────────────────────────────────────────────────────────

def mint_state(encrypt: Callable[[str], bytes], *, user_id: str, provider: str,
               ttl: int = _DEFAULT_TTL, now: Optional[float] = None) -> str:
    """Emite el `state` opaco que liga {user_id, provider} (cifrado+autenticado)."""
    now = time.time() if now is None else now
    payload = {"u": str(user_id), "p": provider, "exp": now + ttl,
               "n": secrets.token_urlsafe(8)}
    return encrypt(_STATE_PREFIX + json.dumps(payload)).decode("ascii")


def read_state(decrypt: Callable[[bytes], str], state: Optional[str], *,
               provider: str, now: Optional[float] = None) -> Optional[str]:
    """user_id si el state es VÁLIDO para este provider y no expiró; si no, None.

    None cubre: ausente · no descifra (forjado/manipulado, HMAC Fernet) · prefijo
    equivocado · JSON roto · provider distinto · expirado. El callback trata None
    como rechazo (no hay Caso A sin un state válido).
    """
    if not state:
        return None
    now = time.time() if now is None else now
    try:
        plain = decrypt(state.encode("ascii"))
    except Exception:
        return None
    if not plain.startswith(_STATE_PREFIX):
        return None
    try:
        data = json.loads(plain[len(_STATE_PREFIX):])
    except Exception:
        return None
    if data.get("p") != provider:
        return None
    try:
        if float(data.get("exp", 0)) < now:
            return None
    except (TypeError, ValueError):
        return None
    return data.get("u")


# ── CONFIG (del onboarding object + env) ──────────────────────────────────────────

def oauth_cfg(obj: dict) -> dict:
    return obj.get("oauth") or {}


def requested_scopes(cfg: dict) -> list[str]:
    """Scopes pedidos por el descriptor, en orden.

    Contrato nuevo: ``oauth.scopes`` es una lista de objetos ``{id, requested,
    tools}``. ``requested:false`` permite describir una capacidad que el proveedor
    conoce (por ejemplo compra) sin pedirla en esta app. El string ``scope`` legacy
    sigue funcionando para los conectores existentes.
    """
    entries = (cfg or {}).get("scopes")
    if isinstance(entries, list):
        out: list[str] = []
        for entry in entries:
            if isinstance(entry, str):
                value, enabled = entry, True
            elif isinstance(entry, dict):
                value, enabled = entry.get("id"), entry.get("requested", True) is not False
            else:
                continue
            value = str(value or "").strip()
            if enabled and value and value not in out:
                out.append(value)
        return out
    scope = (cfg or {}).get("scope", "")
    values = scope if isinstance(scope, (list, tuple)) else str(scope or "").split()
    return [str(v).strip() for v in values if str(v).strip()]


def normalize_granted_scopes(value: Any) -> list[str]:
    """Normaliza ÚNICAMENTE el scope devuelto por el token endpoint.

    No cae al scope solicitado: si el proveedor no declara qué concedió, devolvemos
    ``[]`` y la superficie de tools queda cerrada. Eso evita fabricar permisos.
    """
    if isinstance(value, (list, tuple, set)):
        raw = [str(v) for v in value]
    elif isinstance(value, str):
        raw = value.replace(",", " ").split()
    else:
        raw = []
    out: list[str] = []
    for item in raw:
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return out


def tools_for_granted_scopes(cfg: dict, granted: Any) -> list[str]:
    """Tools cuya entrada de catálogo está respaldada por un scope CONCEDIDO."""
    allowed = set(normalize_granted_scopes(granted))
    out: list[str] = []
    for entry in (cfg or {}).get("scopes") or []:
        if not isinstance(entry, dict) or str(entry.get("id") or "") not in allowed:
            continue
        for tool in entry.get("tools") or []:
            tool = str(tool or "").strip()
            if tool and tool not in out:
                out.append(tool)
    return out


def pkce_required(cfg: dict) -> bool:
    value = (cfg or {}).get("pkce")
    if isinstance(value, dict):
        return value.get("required", True) is not False
    return value is True


def pkce_pair() -> tuple[str, str]:
    """Devuelve ``(verifier, challenge)`` RFC 7636, siempre S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def wants_offline(cfg: dict) -> bool:
    """¿El flujo PIDIÓ acceso de larga duración (refresh_token)? True si el descriptor declara
    `access_type=offline` (estilo Google/OAuth2) o incluye el scope `offline_access` (OIDC/Xero).

    Es la señal para el gate A3: si se pidió offline y el proveedor NO devolvió refresh_token,
    la conexión es PARCIAL (el access_token muere a la ~1h sin poder renovarse sin re-consent)."""
    if not isinstance(cfg, dict):
        return False
    params = cfg.get("authorize_params") or {}
    if isinstance(params, dict) and str(params.get("access_type", "")).lower() == "offline":
        return True
    # scope suele ser string separado por espacios, pero un descriptor podría traerlo como lista;
    # normalizamos a tokens en ambos casos (una lista mal parseada por str() escondería un parcial
    # como "Conectado" completo → false-green). Matcheamos el token EXACTO `offline_access`.
    scope = cfg.get("scope", "")
    tokens = scope if isinstance(scope, (list, tuple)) else str(scope or "").split()
    return "offline_access" in tokens


def _development_secret(cfg: dict) -> Optional[str]:
    """Lee el secreto de desarrollo desde un JSON privado fuera del bundle.

    Un descriptor puede nombrar archivo/campo, nunca el valor. Rechazamos permisos
    de grupo/otros y archivos cuyo dueño no sea el proceso. Un paquete distribuido
    no trae este archivo, por lo que cae honestamente a ``account_required``.
    """
    spec = (cfg or {}).get("development_client_secret")
    if not isinstance(spec, dict) or not spec.get("file"):
        return None
    path = Path(os.path.expanduser(str(spec["file"]))).resolve()
    try:
        info = path.stat()
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o077:
            return None
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    field = str(spec.get("field") or "client_secret")
    value = data.get(field) if isinstance(data, dict) else None
    return str(value).strip() or None if value is not None else None


def client_creds(cfg: dict, env: Optional[dict] = None) -> tuple[Optional[str], Optional[str]]:
    """Resuelve ``(client_id, client_secret)`` sin aceptar secretos embebidos.

    El contrato moderno exige ``client_id`` literal en el catálogo (sumar proveedor
    no requiere deploy). Se conserva el par de env-vars legacy. El secreto moderno
    sólo puede venir del archivo privado de desarrollo nombrado por el descriptor.
    """
    env = os.environ if env is None else env
    cid = str((cfg or {}).get("client_id") or "").strip() or None
    if not cid:
        cid = (env.get((cfg or {}).get("client_id_env", "")) or "").strip() or None
    csec = (env.get(cfg.get("client_secret_env", "")) or "").strip() or None
    if not csec:
        csec = _development_secret(cfg)
    return cid, csec


def build_authorize_url(cfg: dict, *, client_id: str, redirect_uri: str, state: str,
                        code_challenge: Optional[str] = None) -> str:
    if pkce_required(cfg) and not code_challenge:
        raise ValueError("pkce_required: falta code_challenge S256")
    q = {
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(requested_scopes(cfg)) or cfg.get("scope", "/authenticate"),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if code_challenge:
        q["code_challenge"] = code_challenge
        q["code_challenge_method"] = "S256"
    # [TEST-FIX step-4.5 · T-8] Parámetros extra data-driven del descriptor (p.ej. Google:
    # access_type=offline + prompt=consent → fuerza que devuelva refresh_token). Provider-
    # agnóstico: cada onboarding object nombra lo suyo bajo `oauth.authorize_params`.
    extra = cfg.get("authorize_params") or {}
    if isinstance(extra, dict):
        q.update({str(k): str(v) for k, v in extra.items()})
    sep = "&" if "?" in cfg["authorize_url"] else "?"
    return cfg["authorize_url"] + sep + urllib.parse.urlencode(q)


# ── INTERCAMBIO code → token (server-side) ────────────────────────────────────────

def _http_post_form(url: str, form: dict, timeout: int = 20) -> tuple[Optional[int], Any]:
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, str(e)


def _oauth_failure(status: Optional[int], body: Any) -> dict:
    """Error accionable y acotado; nunca devuelve bodies arbitrarios ni secretos."""
    error = body.get("error") if isinstance(body, dict) else None
    description = body.get("error_description") if isinstance(body, dict) else None
    if not description and isinstance(body, str):
        description = body
    return {
        "ok": False,
        "status": status,
        "error": str(error or "oauth_exchange_failed")[:80],
        "error_description": str(description or "El proveedor rechazó el intercambio OAuth.")[:240],
    }


def exchange_code(cfg: dict, *, client_id: str, client_secret: Optional[str], code: str,
                  redirect_uri: str, code_verifier: Optional[str] = None,
                  http_post: Callable = _http_post_form) -> dict:
    """Intercambia el code por token, con secreto opcional y PKCE data-driven."""
    if pkce_required(cfg) and not code_verifier:
        return {"ok": False, "status": None, "error": "pkce_required",
                "error_description": "Falta el code_verifier PKCE; intercambio cancelado."}
    form = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if client_secret:
        form["client_secret"] = client_secret
    if code_verifier:
        form["code_verifier"] = code_verifier
    status, body = http_post(cfg["token_url"], form)
    if status != 200 or not isinstance(body, dict):
        return _oauth_failure(status, body)
    token = body.get("access_token")
    if not token:
        return {"ok": False, "status": status, "error": "missing_access_token",
                "error_description": "El proveedor respondió sin access_token."}
    idf = cfg.get("identity_field", "orcid")
    # [TEST-FIX step-4.5 · T-8] Capturamos refresh_token + expires_in (Google los devuelve
    # sólo con access_type=offline). El refresh_token se guarda CIFRADO en el vault (companion)
    # para renovar el access_token sin re-consent. Ninguno vuelve al browser/caller en claro.
    return {
        "ok": True, "access_token": token, "identity": body.get(idf), "status": 200,
        "refresh_token": body.get("refresh_token"), "expires_in": body.get("expires_in"),
        "token_type": body.get("token_type"),
        # Scope CONCEDIDO: sólo lo que devolvió el token endpoint; nunca lo solicitado.
        "granted_scopes": normalize_granted_scopes(body.get("scope")),
        "scope_source": "token_response" if body.get("scope") is not None else "missing",
    }


def refresh_access_token(cfg: dict, *, client_id: str, client_secret: Optional[str],
                         refresh_token: str,
                         http_post: Callable = _http_post_form) -> dict:
    """[TEST-FIX step-4.5 · T-8] Renueva el access_token con el refresh_token
    (grant_type=refresh_token), 100% server-side. Devuelve
    {ok, access_token, expires_in, refresh_token, status, raw}.
    Google normalmente NO re-emite refresh_token en el refresh → conservamos el original.
    Un refresh_token revocado/expirado da ok=False → el llamador cae a 401 honesto (jamás
    finge éxito)."""
    form = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if client_secret:
        form["client_secret"] = client_secret
    status, body = http_post(cfg["token_url"], form)
    if status != 200 or not isinstance(body, dict):
        return _oauth_failure(status, body)
    token = body.get("access_token")
    if not token:
        return {"ok": False, "status": status, "error": "missing_access_token",
                "error_description": "El proveedor respondió sin access_token."}
    return {"ok": True, "access_token": token, "expires_in": body.get("expires_in"),
            "refresh_token": body.get("refresh_token") or refresh_token, "status": 200,
            "granted_scopes": normalize_granted_scopes(body.get("scope")),
            "scope_source": "token_response" if body.get("scope") is not None else "unchanged"}


# [ticket 9 · refresh cableado] Renovamos ANTES de que el access_token venza, no cuando ya
# murió: si entregamos uno que expira a mitad del run, el belt cae a 401 igual. El skew (s)
# es el colchón. Env-configurable por si un proveedor tiene relojes raros.
_REFRESH_SKEW = int(os.environ.get("PUPPET_OAUTH_REFRESH_SKEW", "120"))
# review F1 · TTL por defecto cuando el proveedor NO re-emite expires_in en el refresh (válido
# per RFC 6749: expires_in es OPCIONAL y muchos IdP lo omiten en grant_type=refresh_token). Sin
# esto, el companion guardaría expires_in=None → token_expired(float(None))→TypeError→True → se
# renovaría en CADA resolve (renew-loop, riesgo de 429/bloqueo del IdP). Google SÍ lo devuelve.
_DEFAULT_REFRESH_TTL = 3600


def token_expired(companion: dict, *, now: Optional[float] = None,
                  skew: int = _REFRESH_SKEW) -> bool:
    """¿El access_token guardado ya venció (o vence dentro de `skew` s)?

    Lee obtained_at + expires_in del companion (lo que el callback guardó al conectar).
    Si falta cualquiera de los dos, o expires_in<=0, devuelve True: es más seguro intentar
    renovar de más (el refresh es idempotente y barato) que entregar un token muerto que
    hace fallar el run con 401. Nunca lanza."""
    now = time.time() if now is None else now
    # EL ABSOLUTO MANDA cuando está. `expira_en` se guarda al recibir el token y no depende
    # de que `obtained_at` sobreviva: un companion al que alguien le saque el timestamp de
    # origen sigue sabiendo cuándo vence. El par relativo queda como camino de compatibilidad
    # para los companions escritos antes de que existiera el absoluto.
    absoluto = companion.get("expira_en")
    if absoluto is not None:
        try:
            return now >= (float(absoluto) - skew)
        except (TypeError, ValueError):
            return True
    try:
        obtained = float(companion.get("obtained_at"))
        ttl = float(companion.get("expires_in"))
    except (TypeError, ValueError):
        return True
    if ttl <= 0:
        return True
    return now >= (obtained + ttl - skew)


def maybe_refresh(companion: dict, *, cfg: Optional[dict] = None, env: Optional[dict] = None,
                  now: Optional[float] = None,
                  http_post: Callable = _http_post_form) -> dict:
    """[ticket 9] Renueva el access_token SI el companion indica expiración y hay con qué.

    El companion (guardado cifrado por el callback bajo "<provider>__oauth") trae
    {refresh_token, expires_in, obtained_at, token_url, client_id_env, client_secret_env}.
    Este helper es PURO respecto de la DB: no lee ni escribe el vault (eso lo hace el broker);
    sólo decide y ejecuta el intercambio HTTP server-side. Así se testea sin Postgres.

    Devuelve:
      {"refreshed": False, "reason": ...}                      # no hacía falta / no se pudo
      {"refreshed": True, access_token, expires_in,
       refresh_token, obtained_at}                             # token nuevo listo para persistir

    Nunca devuelve un token en un `reason` ni lo loguea. Ante refresh fallido (refresh_token
    revocado/expirado) devuelve refreshed=False: el caller conserva el token viejo y el belt
    degrada a un 401 honesto — jamás finge éxito."""
    if not isinstance(companion, dict):
        return {"refreshed": False, "reason": "no_companion"}
    rtok = companion.get("refresh_token")
    if not rtok:
        return {"refreshed": False, "reason": "no_refresh_token"}
    now = time.time() if now is None else now
    if not token_expired(companion, now=now):
        return {"refreshed": False, "reason": "still_valid"}
    cfg = dict(cfg or {})
    token_url = cfg.get("token_url") or companion.get("token_url")
    if not token_url:
        return {"refreshed": False, "reason": "no_token_url"}
    cfg["token_url"] = token_url
    env = os.environ if env is None else env
    # Descriptor moderno primero; companion legacy como compatibilidad.
    cid, csec = client_creds(cfg, env)
    if not cid:
        cid = (env.get(companion.get("client_id_env", "")) or "").strip() or None
    if not csec:
        csec = (env.get(companion.get("client_secret_env", "")) or "").strip() or None
    if not cid or (cfg.get("client_auth") == "secret_post" and not csec):
        return {"refreshed": False, "reason": "no_client_creds"}
    res = refresh_access_token(cfg, client_id=cid, client_secret=csec,
                               refresh_token=rtok, http_post=http_post)
    if not res.get("ok"):
        # RFC 6749 invalid_grant es la señal inequívoca de refresh revocado/expirado.
        reason = "oauth_revoked" if res.get("error") == "invalid_grant" else "refresh_failed"
        return {"refreshed": False, "reason": reason, "status": res.get("status"),
                "error": res.get("error")}
    # review F1 · si el proveedor omite expires_in, caemos a un TTL sano (no None): así el
    # companion re-persistido siempre tiene un número y token_expired no entra en renew-loop.
    #
    # ⚠️ PORTE onshape · el absoluto se calcula ACÁ, de este `ttl` y no de otro. La versión
    # que venía de main decía `(now + float(ttl)) if ttl else None` con un `ttl` que en esta
    # función NO EXISTE —es una local de `token_expired`, treinta líneas más arriba—, así que
    # todo refresh EXITOSO moría con NameError. El broker lo tragaba en su `except Exception`
    # y devolvía el token viejo: el refresh OAuth no funcionaba y no se quejaba. Medido con
    # `maybe_refresh` y un `http_post` que devuelve 200.
    ttl = res.get("expires_in") or _DEFAULT_REFRESH_TTL
    return {"refreshed": True, "access_token": res["access_token"],
            "expires_in": ttl,
            "refresh_token": res.get("refresh_token") or rtok,
            "obtained_at": now,
            # EL ABSOLUTO, re-calculado en cada refresh. Si se re-persistiera el `expira_en`
            # del grant original, `token_expired` (que le da prioridad al absoluto) lo vería
            # vencido para siempre y renovaría en CADA lookup.
            "expira_en": now + float(ttl),
            "granted_scopes": (res.get("granted_scopes")
                               or normalize_granted_scopes(companion.get("granted_scopes")))}


def revoke_token(cfg: dict, *, token: str, client_id: Optional[str] = None,
                 client_secret: Optional[str] = None,
                 http_post: Callable = _http_post_form) -> dict:
    """[ticket 2 · borrado de cuenta] Revoca un token CONTRA EL PROVEEDOR, data-driven:
    usa `oauth.revoke_url` del onboarding object (Google: https://oauth2.googleapis.com/revoke;
    Slack: https://slack.com/api/auth.revoke). Sin revoke_url declarado → {ok:False,
    reason:'no_revoke_url'} (el proveedor no expone revocación, p.ej. ORCID) — el caller
    igual borra la credencial local; esto es best-effort y JAMÁS bloquea el borrado.

    Se manda token + client creds si existen (Google ignora las creds; otros las piden).
    Devuelve {ok, status, reason?}. 200 = revocado; Google también responde 200 para
    tokens ya inválidos (idempotente, nos sirve)."""
    revoke_url = (cfg or {}).get("revoke_url")
    if not revoke_url:
        return {"ok": False, "reason": "no_revoke_url", "status": None}
    form = {"token": token}
    if client_id:
        form["client_id"] = client_id
    if client_secret:
        form["client_secret"] = client_secret
    # timeout ACOTADO (review): la revocación corre en el request de borrado; un proveedor lento
    # no debe demorar el pedido. El acceso local ya murió (soft-delete previo), esto es best-effort.
    try:
        status, body = http_post(revoke_url, form, timeout=8)
    except TypeError:
        status, body = http_post(revoke_url, form)   # http_post stub sin kwarg timeout (tests)
    if status != 200:
        return {"ok": False, "status": status,
                "reason": body if isinstance(body, str) else "provider_error"}
    # HONESTIDAD (review): un 200 NO siempre es éxito. Slack (auth.revoke) responde 200 con
    # {"ok": false} cuando falla → NO lo declaramos revocado. Google/otros devuelven cuerpo vacío
    # en éxito → ok=True. Sólo un {"ok": false} explícito marca fallo.
    if isinstance(body, dict) and body.get("ok") is False:
        return {"ok": False, "status": 200, "reason": body.get("error") or "provider_declined"}
    return {"ok": True, "status": 200}


__all__ = [
    "mint_state", "read_state", "oauth_cfg", "client_creds",
    "requested_scopes", "normalize_granted_scopes", "tools_for_granted_scopes",
    "pkce_required", "pkce_pair",
    "build_authorize_url", "exchange_code", "refresh_access_token",
    "token_expired", "maybe_refresh", "revoke_token",
]
