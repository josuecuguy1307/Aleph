"""supabase_jwt.py — verificación de JWT de Supabase. CONTRACT-AUTH-v2 · Step 5.

LA COSTURA: `repo.session_owner(token) -> user_id | None` no cambia de firma. Todo el
backend autoriza LLAMANDO a esa función (invariante §4.5 del contrato v1, respetada en
todo el árbol), así que si v2 respeta el contrato, el resto del árbol no se entera.
Este módulo es lo que esa función usa por dentro cuando el token es un JWT.

DOS FORMATOS CONVIVEN durante la transición:
  · Fernet opaco (v1) — `alephsess:v1:<uuid>`, no caduca nunca. Sigue vivo para el CLI
    local y los harnesses.
  · JWT de Supabase (v2) — firmado por ellos, CADUCA (~1h), con `sub` = auth.users.id.

El orden importa y es deliberado: **Fernet primero**. Es una operación local de
microsegundos; el JWT implica parseo y, la primera vez, traer el JWKS por red. Probar
lo barato antes evita pagar red por cada request de un CLI local.

⚠️ LO QUE ESTE MÓDULO NO HACE: decidir el tier. El JWT dice QUIÉN sos, jamás QUÉ PLAN
tenés. El tier vive en `users.tier` y lo resuelve el servidor contra la base — si
alguna vez alguien mete el tier en el JWT, el cliente pasa a declarar su propio plan y
toda la muralla se cae. Esa frontera es la razón de la Opción A.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any, Optional

#: Cache del JWKS. Traerlo en cada request sería una llamada de red por request —
#: y, peor, un punto donde la caída de Supabase tumbaría TODA autenticación.
_JWKS: dict[str, Any] = {"keys": None, "at": 0.0}
_JWKS_TTL_S = int(os.environ.get("SUPABASE_JWKS_TTL_S", str(6 * 3600)))


class JWTInvalido(Exception):
    """El token no verifica. Se trata como 'no sé quién sos', jamás como 'sos free'."""


def _b64url(data: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _proyecto_url() -> str:
    return (os.environ.get("SUPABASE_URL") or "").rstrip("/")


def _traer_jwks(forzar: bool = False) -> Optional[list]:
    """JWKS del proyecto, cacheado. None si no se pudo traer (≠ 'la firma es mala')."""
    ahora = time.time()
    if not forzar and _JWKS["keys"] is not None and (ahora - _JWKS["at"]) < _JWKS_TTL_S:
        return _JWKS["keys"]
    base = _proyecto_url()
    if not base:
        return None
    try:
        req = urllib.request.Request(f"{base}/auth/v1/.well-known/jwks.json",
                                     headers={"apikey": os.environ.get("SUPABASE_ANON_KEY", "")})
        with urllib.request.urlopen(req, timeout=6) as r:
            keys = json.loads(r.read()).get("keys") or []
        _JWKS["keys"], _JWKS["at"] = keys, ahora
        return keys
    except Exception:
        # Red caída: se devuelve lo viejo si hay. Un JWKS vencido sigue siendo mejor
        # que rechazar a todo el mundo — las claves rotan raras veces.
        return _JWKS["keys"]


def es_jwt(token: str) -> bool:
    """¿Tiene forma de JWT? Barato y sin criptografía: sirve para decidir QUÉ camino
    intentar, nunca para confiar en el token."""
    if not token or token.count(".") != 2:
        return False
    return token.startswith("eyJ")


def verificar(token: str, *, ahora: Optional[float] = None) -> str:
    """JWT de Supabase → `sub` (el auth.users.id). Lanza JWTInvalido si no verifica.

    Verifica: firma (HS256 con el secreto del proyecto, o RS256/ES256 contra el JWKS),
    expiración, y que el emisor sea NUESTRO proyecto — un JWT válido de OTRO proyecto
    de Supabase no puede autenticar acá.
    """
    ahora = ahora or time.time()
    try:
        h_raw, p_raw, _ = token.split(".")
        header = json.loads(_b64url(h_raw))
        payload = json.loads(_b64url(p_raw))
    except Exception as e:
        raise JWTInvalido(f"no parsea: {type(e).__name__}") from e

    alg = str(header.get("alg") or "")
    # `alg: none` es el ataque clásico contra verificadores ingenuos: un token sin firma
    # que el parser acepta porque el header lo pide. Se rechaza explícitamente.
    if alg.lower() in ("none", ""):
        raise JWTInvalido("alg none / ausente")

    try:
        import jwt as _pyjwt
    except ImportError as e:
        # Fail-CLOSED: sin la librería no se puede verificar nada, y "no puedo verificar"
        # NUNCA puede significar "adelante".
        raise JWTInvalido("PyJWT no instalado: imposible verificar") from e

    emisor = f"{_proyecto_url()}/auth/v1"
    opciones = {"require": ["exp", "sub"], "verify_aud": False}

    if alg.startswith("HS"):
        secreto = os.environ.get("SUPABASE_JWT_SECRET")
        if not secreto:
            raise JWTInvalido("falta SUPABASE_JWT_SECRET para verificar HS256")
        try:
            datos = _pyjwt.decode(token, secreto, algorithms=["HS256", "HS384", "HS512"],
                                  issuer=emisor, options=opciones)
        except Exception as e:
            raise JWTInvalido(str(e)) from e
    else:
        keys = _traer_jwks()
        if not keys:
            raise JWTInvalido("no se pudo obtener el JWKS")
        kid = header.get("kid")
        clave = next((k for k in keys if k.get("kid") == kid), None)
        if clave is None:
            # kid desconocido: puede ser rotación reciente → un reintento forzando el
            # refresco del JWKS. Si sigue sin aparecer, es inválido de verdad.
            keys = _traer_jwks(forzar=True) or []
            clave = next((k for k in keys if k.get("kid") == kid), None)
        if clave is None:
            raise JWTInvalido(f"kid desconocido: {kid}")
        try:
            from jwt import PyJWK
            datos = _pyjwt.decode(token, PyJWK(clave).key,
                                  algorithms=[alg], issuer=emisor, options=opciones)
        except Exception as e:
            raise JWTInvalido(str(e)) from e

    sub = str(datos.get("sub") or "").strip()
    if not sub:
        raise JWTInvalido("sin sub")
    return sub


def resolver_cuenta(conn, auth_uid: str, repo, *, email: Optional[str] = None) -> Optional[str]:
    """auth.users.id → users.id NUESTRO. Crea la cuenta local si es el primer login.

    El alta perezosa (en vez de un trigger en la base) mantiene la creación de cuentas
    en UN solo lugar del código, donde ya vive `get_or_create_user`. Un trigger en
    `auth.users` sería invisible desde el repo y se descubriría el día que falle.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE auth_uid = %s::uuid", (auth_uid,))
        fila = cur.fetchone()
    if fila:
        return str(fila[0])

    if not email:
        # Sin email no se puede ligar ni crear: se devuelve None y el caller trata la
        # sesión como desconocida. Nunca se inventa una cuenta.
        return None

    # ── ⛔ ANTI PRE-HIJACKING ──────────────────────────────────────────────────
    # Reclamar una cuenta existente por EMAIL es cómodo (evita duplicados) pero abre un
    # ataque real si esa cuenta pudo crearse con un email NO VERIFICADO:
    #
    #   1. el atacante registra victima@gmail.com por /v1/auth/register (que no verifica
    #      el email) con una contraseña suya;
    #   2. la víctima entra con Google con su dirección real;
    #   3. si reclamáramos a ciegas, el auth_uid de la víctima quedaría ligado a la
    #      cuenta del atacante — que sigue sabiendo la contraseña y entra cuando quiera.
    #
    # Por eso sólo se reclama una cuenta SIN password_hash: ésas no pudieron ser
    # creadas por auto-registro, así que no hay nadie con credenciales previas sobre
    # ellas. Una cuenta CON contraseña se deja intacta y la sesión se rechaza con un
    # camino honesto (entrar con la contraseña y vincular desde ajustes).
    #
    # El proveedor (Google/GitHub) SÍ verifica el email de su lado; el problema no es
    # esa punta, es la nuestra.
    with conn.cursor() as cur:
        cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,))
        existente = cur.fetchone()

    if existente is not None:
        if existente[1]:
            # Cuenta con contraseña: NO se reclama. Fail-closed — mejor un login que
            # pide un paso más que una cuenta entregada al que llegó primero.
            return None
        return _ligar(conn, existente[0], auth_uid)

    # No existe: alta limpia, ya ligada al proveedor.
    usuario = repo.get_or_create_user(conn, email)
    return _ligar(conn, usuario["id"], auth_uid)


def _ligar(conn, user_id, auth_uid: str) -> Optional[str]:
    """Liga la cuenta al proveedor y devuelve su id — o None si ya tiene OTRO dueño.

    ⛔ EL `rowcount` NO ES OPCIONAL. El `WHERE auth_uid IS NULL` es lo que impide robar
    una cuenta ya ligada, pero un UPDATE que no matchea nada **no lanza**: devuelve 0
    filas y sigue. Devolver el id igual convertía esa guarda en decorativa y dejaba vivo
    el pre-hijacking incluso con el gate de `password_hash` puesto:

      1. el atacante entra a Supabase con `victima@gmail.com` (Supabase emite JWT aunque
         el email no esté confirmado) → se crea la fila local ligada a SU auth_uid, y
         SIN password_hash, así que el gate de arriba la deja pasar;
      2. la víctima entra con Google; su auth_uid no matchea, cae al lookup por email y
         encuentra la fila del atacante;
      3. el UPDATE no toca nada (auth_uid ya no es NULL) — y antes devolvíamos ese id
         igual. La víctima quedaba adentro de la cuenta del ATACANTE.

    Por eso 0 filas ⇒ None. La única excepción legítima es que el dueño seamos NOSOTROS
    MISMOS: dos requests concurrentes del mismo primer login corren el UPDATE a la vez,
    uno gana y el otro ve 0 filas. Ahí devolver None sería un 401 intermitente y
    fantasma, así que se re-lee y se compara el auth_uid antes de decidir.
    """
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET auth_uid = %s::uuid, updated_at = now() "
                    "WHERE id = %s::uuid AND auth_uid IS NULL", (auth_uid, user_id))
        filas = cur.rowcount
    conn.commit()
    if filas:
        return str(user_id)

    # 0 filas: la cuenta ya tiene dueño. ¿Nosotros, o alguien más?
    with conn.cursor() as cur:
        cur.execute("SELECT auth_uid FROM users WHERE id = %s::uuid", (user_id,))
        fila = cur.fetchone()
    duenio = str(fila[0]) if fila and fila[0] else None
    if duenio == auth_uid:
        return str(user_id)     # carrera con nuestro propio login: es nuestra
    return None                 # ligada a OTRA identidad → no se entrega
