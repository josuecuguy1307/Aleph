"""
authz.py — EL CONTRATO AUTH/SESSION (§4.5) hecho código · owner: T6.

Una sola fuente de verdad para "¿quién es el dueño de esta request y puede tocar
este recurso?". El resto del backend (router, otros tracks) autoriza LLAMANDO acá,
no reimplementando el parseo del token ni la comparación de dueño.

INVARIANTE MADRE (§4.5):  toda llamada /v1 con identidad lleva una SESIÓN → user_id.
                          user_id scopea TODO. Nadie lee/escribe data de otro.

Capas:
  1. TOKEN — `repo.mint_session(user_id)` emite un token opaco Fernet con user_id y
     generación, cifrado+autenticado, con TTL. `repo.session_owner` lo abre y compara
     contra users.session_version. Ausente/expirado/revocado/manipulado → owner=None.
  2. TRANSPORTE — el cliente manda el token como `Authorization: Bearer <tok>`.
     EXCEPCIÓN SSE: el `EventSource` del browser NO puede setear headers → para los
     GET de streaming se acepta TAMBIÉN `?token=<tok>` (query). `pick_token` unifica.
  3. DECISIÓN — `decide(expected_owner, token)`:
        ("no_session", None)  → no hay token válido           → el router da 401
        ("forbidden", owner)  → token válido pero de OTRO user → el router da 403
        ("ok", owner)         → token válido y == expected     → adelante
     REGLA "owner-gated cuando hay dueño": si `expected_owner is None` el recurso es
     anónimo (sin dueño) y la lectura es ABIERTA — devuelve ("ok", owner_or_None).
     Esto NO afloja nada: un recurso sin dueño no es data privada de nadie.

Este módulo es PURO (no importa FastAPI): el router mapea el veredicto a HTTPException;
los tests lo ejercitan sin levantar el server. El crypto real vive en repo (db.py Fernet).
"""
from __future__ import annotations

from typing import Optional, Tuple

from app.phase1 import repo


def parse_bearer(authorization: Optional[str]) -> Optional[str]:
    """Extrae el token de un header Authorization. Acepta 'Bearer <tok>' (case-insensitive)
    o el token pelado. None si está vacío."""
    if not authorization:
        return None
    a = authorization.strip()
    if a.lower().startswith("bearer "):
        a = a[7:].strip()
    return a or None


def pick_token(authorization: Optional[str], query_token: Optional[str] = None) -> Optional[str]:
    """El token efectivo: header Authorization primero; si no, el ?token= (sólo el camino
    SSE lo usa, porque EventSource no manda headers). El header gana si están ambos."""
    return parse_bearer(authorization) or ((query_token or "").strip() or None)


def session_owner(token: Optional[str]) -> Optional[str]:
    """user_id dueño del token, o None si inválido/forjado/ausente (re-exporta repo)."""
    return repo.session_owner(token)


def decide(expected_owner: Optional[str], token: Optional[str]) -> Tuple[str, Optional[str]]:
    """Veredicto de autorización. Ver el docstring del módulo para la semántica.

    - expected_owner None  → recurso anónimo → ("ok", owner_of_token_or_None) [lectura abierta]
    - token inválido       → ("no_session", None)            [→ 401]
    - owner != expected    → ("forbidden", owner)            [→ 403]
    - owner == expected    → ("ok", owner)                   [→ adelante]
    """
    owner = session_owner(token)
    if expected_owner is None:
        # recurso sin dueño: no es data privada de nadie → abierto (no rompe inspect/demo)
        return ("ok", owner)
    if owner is None:
        return ("no_session", None)
    if str(owner) != str(expected_owner):
        return ("forbidden", owner)
    return ("ok", owner)


# ═══════════════════════════════════════════════════════════════════════════════
# BLINDAJE SISTÉMICO (hallazgo #1 · "identidad del cliente") — default CERRADO
# ═══════════════════════════════════════════════════════════════════════════════
#
# El sistema nació MONO-USUARIO: muchos endpoints derivaban la identidad del CLIENTE
# (`body.user_id`, `?user_id=`) de forma condicional (`if body.user_id:`), así que
# OMITIR el campo salteaba el control — correr anónimo, gastar cognición, o (peor)
# tocar el recurso de otro. El patrón apareció 13+ veces. Cerrar de a uno es jugar al
# topo sin fondo.
#
# ESTE es el fondo: un middleware que EXIGE SESIÓN para toda mutación /v1 por DEFAULT.
# Un endpoint nuevo, sin hacer nada, queda cerrado — es IMPOSIBLE olvidarse. Lo público
# legítimo se declara EXPLÍCITAMENTE acá (opt-in), no al revés.

#: Rutas /v1 públicas por DISEÑO (no requieren sesión). Prefijo-match. Mínima y auditada:
#: cada entrada es una decisión, no un olvido. Si algo no está acá, exige sesión.
_PUBLIC_V1_EXACT = {
    "/v1/auth/login",          # la puerta
    "/v1/auth/register",       # (gateado aparte por PUPPET_ALLOW_PASSWORD_AUTH)
    "/v1/auth/local",          # login suave: la sesión LOCAL anónima se minta SIN sesión previa
                               # (catch-22 si no fuera pública); el endpoint se auto-gatea por rol
                               # (_es_control_plane → 404 en control).
    "/v1/auth/merge-local",    # login suave: capability-based (exige el Bearer de la cuenta EN el
                               # endpoint → 401 propio si falta; jamás IDOR). Público acá para que
                               # el chequeo de rol del endpoint gane (404 honesto en control) en vez
                               # de que la muralla lo tape con un 401 genérico.
    "/v1/payments/status",     # diagnóstico (gateado por PUPPET_DIAG)
    "/v1/brains/status",       # estado del host, info nula (BYO-CLI es desktop-only)
    "/v1/catalog/ingest",      # lectura/limpieza del registro público; sólo persiste el
                               # catálogo local del cliente, sin tocar recursos de cuenta
}
_PUBLIC_V1_PREFIX = (
    "/v1/payments/webhook/",   # se autentica por FIRMA, no por sesión
    "/v1/icons/",              # favicons cacheados — público, sin datos de usuario
)

#: Lecturas (GET) /v1 públicas: el catálogo es navegable sin loguearse (onboarding) y NO
#: expone datos de usuario (el estado `connected` sale de la sesión desde P8; sin sesión
#: aparece vacío). Las MUTACIONES nunca son públicas por acá.
_PUBLIC_V1_GET_PREFIX = (
    "/v1/catalog/",            # search/validate — navegación del catálogo
)


def is_public_v1(path: str, method: str) -> bool:
    """¿Esta ruta /v1 es pública por diseño? Default: NO (cerrado)."""
    if path in _PUBLIC_V1_EXACT:
        return True
    if any(path.startswith(p) for p in _PUBLIC_V1_PREFIX):
        return True
    if method.upper() in ("GET", "HEAD", "OPTIONS") and \
            any(path.startswith(p) for p in _PUBLIC_V1_GET_PREFIX):
        return True
    return False


def require_actor(authorization: Optional[str], query_token: Optional[str] = None):
    """El actor SALE DE LA SESIÓN, incondicional. Nunca de un `body.user_id`/`?user_id=`.

    Devuelve el owner (user_id) o None si no hay sesión válida. El caller que EXIGE
    sesión hace `owner = require_actor(...); if not owner: raise 401`. Es el reemplazo
    canónico del patrón inseguro `if body.user_id: _authorize(body.user_id, ...)` —
    con éste, omitir un campo del body no cambia NADA: la identidad es la del token.
    """
    return session_owner(pick_token(authorization, query_token))


__all__ = ["parse_bearer", "pick_token", "session_owner", "decide",
           "is_public_v1", "require_actor"]
