"""
repo.py — repositorio fino sobre la DB de Fase 0 (platform/db, Postgres `puppet_ai`).

Microtask (a): endpoints sobre la DB de Fase 0 (auth, catálogo, workshop/config, storage,
BYOK) usando platform/db. Este módulo es la CAPA DE DATOS; el router (router.py) expone
los endpoints. NO reinventa la conexión ni el cifrado: carga platform/db/db.py por ruta
de archivo (mismo patrón que main.py usa para vault.py / session.py) y usa get_conn /
encrypt_secret / decrypt_secret tal cual.

Cubre:
  - users:   get_or_create_user (auth mínima por email), get_user, set_tier
  - puppets: create_puppet (workshop guarda receta validada), get_puppet, list_puppets,
             update_config (taller edita → version++), set_status
  - runs:    create_run, finish_run, get_run
  - keys:    upsert_key (BYOK cifrada at-rest — NUNCA plaintext), get_key (descifra),
             list_keys (solo metadatos: provider/last4, JAMÁS el secreto), delete_key

Contrato BYOK (Fase 0): keys.ciphertext es un token Fernet; el plaintext nunca toca
Postgres. list_keys/return de upsert SOLO devuelven last4 + provider, jamás el valor.

Todo recibe la conexión por parámetro (el caller maneja el ciclo de vida) o abre una corta
con `with`. psycopg2 con autocommit explícito por método (idempotente, sin transacción
colgada). Stdlib + psycopg2 (vía platform/db).
"""

from __future__ import annotations

import importlib.util
import json
import os
import uuid as _uuid
from pathlib import Path
from typing import Any, Optional

from app.phase1 import agent_catalog

# repo.py: product/backend/app/phase1 -> repo root = parents[4]
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DB_PY = _REPO_ROOT / "platform" / "db" / "db.py"


def _load_db_module():
    """Carga platform/db/db.py por ruta (el backend no asume que platform sea paquete)."""
    import aleph_paths
    return aleph_paths.load_module_by_path("puppet_db", _DB_PY)


# Carga perezosa única (psycopg2 solo se importa cuando se usa la DB real).
_db = None


def _dbmod():
    global _db
    if _db is None:
        _db = _load_db_module()
    return _db


def get_conn(dbname: Optional[str] = None):
    """Conexión psycopg2 a puppet_ai (reexporta la de Fase 0)."""
    return _dbmod().get_conn(dbname)


def asegurar_schema_cliente():
    """Bootstrap del schema SQLite en rol client; no-op en control (reexporta db.py).
    Lo llama el boot (app/infra/db_boot.py) ANTES de arrancar workers/purga."""
    return _dbmod().asegurar_schema_cliente()


def encrypt_secret(plaintext: str) -> bytes:
    return _dbmod().encrypt_secret(plaintext)


def decrypt_secret(token: bytes, ttl: Optional[int] = None) -> str:
    return _dbmod().decrypt_secret(token, ttl=ttl)


# ── sesión Fernet legacy (tamper-proof, expirable y revocable) ──────────────────
# Reusa el Fernet del org y liga user_id + generación de users. Cada validación
# comprueba autenticidad, TTL y generación; password/logout incrementan la generación.
# El cliente lo manda como `Authorization: Bearer`; inválido/expirado → None → 401.
_SESSION_PREFIX_V1 = "alephsess:v1:"
_SESSION_PREFIX = "alephsess:v2:"
_SESSION_TTL_DEFAULT = 12 * 60 * 60
_SESSION_TTL_MAX = 7 * 24 * 60 * 60


def _session_ttl() -> int:
    """TTL positivo y acotado; una configuración mala nunca vuelve eterna la sesión."""
    try:
        configured = int(os.environ.get("ALEPH_LEGACY_SESSION_TTL_SECONDS", ""))
    except (TypeError, ValueError):
        configured = _SESSION_TTL_DEFAULT
    if configured <= 0:
        configured = _SESSION_TTL_DEFAULT
    return min(configured, _SESSION_TTL_MAX)


def _session_version(conn, user_id: str) -> Optional[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT session_version FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return int(row[0]) if row is not None else None


def mint_session(user_id: str, conn=None) -> str:
    """Emite una sesión opaca, finita y ligada a la generación actual del usuario."""
    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    try:
        version = _session_version(conn, str(user_id))
        if version is None:
            raise ValueError("no_user")
        payload = json.dumps([str(user_id), version], separators=(",", ":"))
        return encrypt_secret(_SESSION_PREFIX + payload).decode("ascii")
    finally:
        if own_conn:
            conn.close()


def session_owner(token: Optional[str]) -> Optional[str]:
    """Devuelve el user_id dueño del token, o None si es inválido/forjado/ausente.

    ❄️ LA COSTURA DEL CONTRATO. La firma `token → user_id | None` es lo único que el
    resto del árbol conoce: TODO el backend autoriza llamando acá, no reimplementando
    el parseo (invariante §4.5 de v1). Por eso v2 pudo cambiar QUIÉN emite el token sin
    tocar un solo endpoint.

    [CONTRACT-AUTH-v2] Acepta DOS formatos:
      1. Fernet opaco (v1/v2) — TTL finito + generación revocable en users.
      2. JWT de Supabase (v2) — caduca (~1h); `sub` = auth.users.id, que se traduce a
         nuestro users.id por la columna puente `auth_uid` (migración 0015).

    Fernet PRIMERO a propósito: es local y de microsegundos, mientras que el JWT puede
    implicar traer el JWKS por red. Probar lo barato antes evita pagar red por cada
    request de un CLI que ni usa Supabase.

    Estricto con el Fernet: rechaza cualquier token que no sea base64 url-safe CANÓNICO
    (p.ej. con basura al final que el decoder toleraría) re-codificando y comparando —
    así un `<token-válido>+'x'` no pasa. Esto no afecta el threat model (un token
    forjado de OTRO user ya falla por el HMAC de Fernet) pero deja la invariante sin
    grietas.

    ⚠️ Lo que NO hace, ni en v1 ni en v2: decir qué PLAN tiene la cuenta. El token dice
    quién sos; el tier lo resuelve el servidor contra `users.tier`. Si el plan viajara
    en el token, el cliente declararía su propio tier y la muralla entera se cae.
    """
    if not token:
        return None

    fernet_owner = _session_owner_fernet(token)
    if fernet_owner is not None:
        return fernet_owner
    return _session_owner_supabase(token)


def _session_owner_fernet(token: str) -> Optional[str]:
    """Sesión local: autenticidad + TTL + usuario existente + generación vigente."""
    import base64
    try:
        raw = base64.urlsafe_b64decode(token)
        if base64.urlsafe_b64encode(raw).decode("ascii") != token:
            return None  # no es la forma canónica → forjado/manipulado
    except Exception:
        return None
    try:
        plain = decrypt_secret(token.encode("ascii"), ttl=_session_ttl())
    except Exception:
        return None

    if plain.startswith(_SESSION_PREFIX_V1):
        user_id, token_version = plain[len(_SESSION_PREFIX_V1):], 0
    elif plain.startswith(_SESSION_PREFIX):
        try:
            payload = json.loads(plain[len(_SESSION_PREFIX):])
            if (not isinstance(payload, list) or len(payload) != 2 or
                    not isinstance(payload[0], str) or not payload[0] or
                    type(payload[1]) is not int or payload[1] < 0):
                return None
            user_id, token_version = payload
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    else:
        return None

    conn = None
    try:
        conn = get_conn()
        current = _session_version(conn, user_id)
        return user_id if current is not None and current == token_version else None
    except Exception:
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def revoke_legacy_session(token: str) -> bool:
    """Revoca la generación del token Fernet vigente; JWTs/invalidos son no-op."""
    owner = _session_owner_fernet(token)
    if owner is None:
        return False
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET session_version = session_version + 1, updated_at = now() "
                "WHERE id = %s", (owner,),
            )
            changed = cur.rowcount == 1
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _session_owner_supabase(token: str) -> Optional[str]:
    """Camino v2: JWT de Supabase → auth_uid → nuestro users.id.

    Devuelve None ante CUALQUIER problema (firma mala, vencido, emisor ajeno, capa
    ausente, base caída). None significa "no sé quién sos" — el llamador responde 401,
    y el cliente ya sabe que un 401 NO es "sos free" (política del cache, P6).
    """
    import sys as _sys
    _plat = str(_REPO_ROOT / "platform")
    if _plat not in _sys.path:
        _sys.path.insert(0, _plat)
    try:
        from auth import supabase_jwt as _sj
    except Exception:
        return None                      # capa ausente → fail-closed

    if not _sj.es_jwt(token):
        return None                      # ni Fernet ni JWT: no es un token nuestro
    try:
        auth_uid = _sj.verificar(token)
    except Exception:
        return None                      # firma inválida / vencido / emisor ajeno

    # El email va en el JWT y sirve para el alta perezosa del primer login.
    email = None
    try:
        import base64 as _b64, json as _json
        payload = _json.loads(_b64.urlsafe_b64decode(
            token.split(".")[1] + "=" * (-len(token.split(".")[1]) % 4)))
        email = (payload.get("email") or "").strip().lower() or None
    except Exception:
        pass

    conn = None
    try:
        conn = get_conn()
        return _sj.resolver_cuenta(conn, auth_uid, _sys.modules[__name__], email=email)
    except Exception:
        return None                      # base caída → no se inventa identidad
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _last4(secret: str) -> str:
    return secret[-4:] if len(secret) >= 4 else secret


# ── password hashing (scrypt, stdlib — sin dependencia nueva) ────────────────────
# Formato almacenado: "scrypt$<salt_hex>$<dk_hex>". El password en claro NUNCA se guarda
# ni se loguea; password_hash NUNCA sale al cliente (ver _public_user).

def hash_password(password: str) -> str:
    import hashlib, os
    if not password or len(password) < 6:
        raise ValueError("password_too_short")
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$" + salt.hex() + "$" + dk.hex()


def verify_password(password: str, stored: Optional[str]) -> bool:
    import hashlib, hmac
    if not stored or not stored.startswith("scrypt$"):
        return False
    try:
        _, salt_hex, hash_hex = stored.split("$", 2)
        dk = hashlib.scrypt((password or "").encode("utf-8"),
                            salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _public_user(d: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Devuelve el user SIN el password_hash (nunca sale del backend a un cliente)."""
    if d is None:
        return None
    d = dict(d)
    d.pop("password_hash", None)
    d.pop("session_version", None)
    return d


# ── helpers de fila → dict ──────────────────────────────────────────────────────

def _row_to_dict(cur, row) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    out = dict(zip(cols, row))
    # normaliza UUID/timestamp a str para serializar a JSON sin sorpresas
    for k, v in list(out.items()):
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif v is not None and type(v).__name__ == "UUID":
            out[k] = str(v)
    return out


# ── users (auth mínima) ───────────────────────────────────────────────────────

# LOGIN SUAVE — identidad LOCAL anónima (device user). La app free funciona 100%
# local SIN cuenta: la identidad es una fila users con email CENTINELA no-email
# ("device::<nonce>", sin '@' y con nonce no adivinable → register/login jamás la
# reclaman ni la alcanzan). El login real se OFRECE recién cuando el dato sale de
# la máquina; al ingresar, merge_local_into_account() liga todo lo creado bajo el
# device user a la cuenta (el trabajo previo no se pierde).
DEVICE_EMAIL_PREFIX = "device::"


def is_device_email(email: Optional[str]) -> bool:
    return bool(email) and str(email).startswith(DEVICE_EMAIL_PREFIX)


def is_device_user(user: Optional[dict[str, Any]]) -> bool:
    return bool(user) and is_device_email(user.get("email"))


def get_or_create_device_user(conn) -> dict[str, Any]:
    """La identidad de ESTE equipo: una sola fila device:: por instalación
    (la más vieja si hubiera más de una por carrera de arranque). Sin red,
    sin contraseña, tier free — el muro premium no la reconoce como cuenta."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM users WHERE email LIKE %s ORDER BY created_at ASC LIMIT 1",
            (DEVICE_EMAIL_PREFIX + "%",),
        )
        row = _row_to_dict(cur, cur.fetchone())
        if row is None:
            import uuid
            cur.execute(
                "INSERT INTO users (email, display_name, tier) VALUES (%s, %s, %s) RETURNING *",
                (DEVICE_EMAIL_PREFIX + uuid.uuid4().hex, "Este equipo", "free"),
            )
            row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return _public_user(row)


def get_or_create_user(conn, email: str, display_name: Optional[str] = None,
                       tier: str = "free") -> dict[str, Any]:
    """
    Auth mínima por email (idempotente): devuelve el usuario; lo crea si no existe.
    No es OAuth — es el ancla de identidad para puppets/runs/keys de Fase 0.
    """
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("email requerido")
    if is_device_email(email):
        # la identidad de equipo NUNCA se alcanza por email (ni por el legacy
        # get-or-create): solo /auth/local la entrega, en la máquina del dueño.
        raise ValueError("bad_email")
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing = _row_to_dict(cur, cur.fetchone())
        if existing:
            return _public_user(existing)
        cur.execute(
            "INSERT INTO users (email, display_name, tier) VALUES (%s, %s, %s) RETURNING *",
            (email, display_name, tier),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return _public_user(row)


def register_user(conn, email: str, password: str, display_name: Optional[str] = None,
                  tier: str = "free") -> dict[str, Any]:
    """Crea cuenta con contraseña (hash scrypt). Errores tipados:
      - 'bad_email'        email inválido
      - 'password_too_short' (<6) — lo lanza hash_password
      - 'email_taken'      ya existe una cuenta CON contraseña para ese email
    Si el email existe SIN contraseña (user legacy passwordless), lo RECLAMA (set password)."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("bad_email")
    ph = hash_password(password)  # valida largo mínimo
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing = _row_to_dict(cur, cur.fetchone())
        if existing:
            if existing.get("password_hash"):
                raise ValueError("email_taken")
            if existing.get("deleted_at"):
                # cuenta passwordless CONGELADA en ventana de borrado: reclamarla acá
                # resucitaría sus datos para quien tipee el email (register no verifica
                # posesión). El dueño real reactiva re-logueando (ticket 2).
                raise ValueError("email_taken")
            cur.execute(
                "UPDATE users SET password_hash = %s, display_name = COALESCE(display_name, %s),"
                " session_version = session_version + 1, updated_at = now() "
                "WHERE id = %s RETURNING *",
                (ph, display_name, existing["id"]),
            )
            row = _row_to_dict(cur, cur.fetchone())
        else:
            cur.execute(
                "INSERT INTO users (email, display_name, tier, password_hash)"
                " VALUES (%s, %s, %s, %s) RETURNING *",
                (email, display_name or email.split("@")[0], tier, ph),
            )
            row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return _public_user(row)


def login_user(conn, email: str, password: str) -> Optional[dict[str, Any]]:
    """Verifica email + contraseña. Devuelve el user público, o None si las credenciales
    no coinciden (o el user no tiene contraseña seteada — legacy passwordless)."""
    email = (email or "").strip().lower()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        row = _row_to_dict(cur, cur.fetchone())
    if not row or not verify_password(password, row.get("password_hash")):
        return None
    return _public_user(row)


def get_user(conn, user_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return _public_user(_row_to_dict(cur, cur.fetchone()))


def change_password(conn, user_id: str, current_password: str, new_password: str) -> dict[str, Any]:
    """Cambia la contraseña: verifica la ACTUAL contra el hash y setea la nueva (scrypt).
    Errores tipados:
      - 'no_user'           el id no existe
      - 'no_password_set'   cuenta legacy sin contraseña (no hay actual que verificar)
      - 'bad_current'       la contraseña actual no coincide
      - 'password_too_short' (<6) — lo lanza hash_password"""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = _row_to_dict(cur, cur.fetchone())
    if not row:
        raise ValueError("no_user")
    if not row.get("password_hash"):
        raise ValueError("no_password_set")
    if not verify_password(current_password, row.get("password_hash")):
        raise ValueError("bad_current")
    ph = hash_password(new_password)  # valida largo mínimo (>=6) y vuelve a lanzar si no
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s, session_version = session_version + 1, "
            "updated_at = now() WHERE id = %s RETURNING *",
            (ph, user_id),
        )
        out = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return _public_user(out)


# ── Step 5 · P1 · EL ESCRITOR DE TIER ────────────────────────────────────────
# Hasta el Step 5 este archivo tenía un set_tier sin validación cuyos únicos
# call-sites eran qa/* y tests: NINGUNA ruta de producción escribía users.tier
# (auditado en reports/STEP5-AUDIT-0.md §0.2). Ahora es la puerta por la que entra
# el premium, así que valida y deja rastro.

#: Los únicos tiers que pueden escribirse. La columna es TEXT sin CHECK, así que la
#: validación vive acá: un tier mal escrito ('basicoo') no bloquearía — los muros lo
#: leerían como desconocido → free — pero dejaría una cuenta paga sin servicio y sin
#: explicación. Se rechaza en la escritura, no se descubre en el reclamo.
WRITABLE_TIERS = frozenset({"free", "basico", "tecnico"})


def set_tier(conn, user_id: str, tier: str, *,
             reason: str = "manual:unspecified",
             webhook_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Escribe users.tier y registra POR QUÉ en tier_audit (misma transacción).

    `reason` es obligatorio de facto: 'webhook:<tipo>' | 'reconciliation' |
    'manual:<quien>' | 'test'. users.tier es un único campo mutable — sin auditoría,
    un ascenso indebido no tiene rastro y no hay forma de reconstruir qué lo causó.

    Lanza ValueError ante un tier no escribible: fallar ruidoso en la escritura es
    preferible a persistir un valor que después degrada silencioso a free.
    """
    if tier not in WRITABLE_TIERS:
        raise ValueError(f"tier no escribible: {tier!r} (permitidos: {sorted(WRITABLE_TIERS)})")

    with conn.cursor() as cur:
        cur.execute("SELECT tier FROM users WHERE id = %s", (user_id,))
        prev = cur.fetchone()
        if prev is None:
            return None  # cuenta inexistente: nada que auditar
        tier_before = prev[0]

        cur.execute(
            "UPDATE users SET tier = %s, updated_at = now() WHERE id = %s RETURNING *",
            (tier, user_id),
        )
        row = _row_to_dict(cur, cur.fetchone())

        # La auditoría va en la MISMA transacción que el UPDATE: o quedan las dos,
        # o ninguna. Un tier cambiado sin su fila de auditoría es exactamente el
        # rastro que esta tabla existe para impedir.
        cur.execute(
            "INSERT INTO tier_audit (account_id, tier_before, tier_after, reason, webhook_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, tier_before, tier, reason, webhook_id),
        )
    conn.commit()
    return _public_user(row)


# ── Step 5 · P1 · suscripciones (el LIBRO CONTABLE que decide el tier) ────────
# Ningún gate lee estas tablas: leen users.tier. Acá vive el porqué de ese valor.

def upsert_subscription(conn, *, account_id: str, processor: str, external_id: str,
                        plan: str, status: str,
                        current_period_end=None, grace_until=None,
                        event_at=None) -> dict[str, Any]:
    """Inserta o actualiza una suscripción por (processor, external_id).

    ANTI-DESORDEN (regla 4 del §2 — los webhooks no llegan en orden): si la fila ya
    tiene un `last_event_at` MÁS NUEVO que el `event_at` de este evento, el UPDATE no
    se aplica y se devuelve la fila vigente. Sin esto, un `cancelled` demorado que
    llega después de un `renewed` degradaría a un cliente que acaba de pagar.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO subscriptions
                (account_id, processor, external_id, plan, status,
                 current_period_end, grace_until, last_event_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (processor, external_id) DO UPDATE SET
                plan               = EXCLUDED.plan,
                status             = EXCLUDED.status,
                current_period_end = EXCLUDED.current_period_end,
                grace_until        = EXCLUDED.grace_until,
                last_event_at      = EXCLUDED.last_event_at,
                updated_at         = now()
            WHERE subscriptions.last_event_at IS NULL
               OR EXCLUDED.last_event_at IS NULL
               OR EXCLUDED.last_event_at >= subscriptions.last_event_at
            RETURNING *
            """,
            (account_id, processor, external_id, plan, status,
             current_period_end, grace_until, event_at),
        )
        row = _row_to_dict(cur, cur.fetchone())
        if row is None:
            # El WHERE del DO UPDATE lo rechazó por viejo: devolvemos lo vigente.
            cur.execute(
                "SELECT * FROM subscriptions WHERE processor = %s AND external_id = %s",
                (processor, external_id),
            )
            row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def list_subscriptions(conn, account_id: str) -> list[dict[str, Any]]:
    """TODAS las suscripciones de una cuenta — el tier se deriva del conjunto
    (una cuenta puede tener un lifetime pagado y un mensual cancelado)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM subscriptions WHERE account_id = %s", (account_id,))
        rows = cur.fetchall()
        return [_row_to_dict(cur, r) for r in rows]


def claim_webhook_event(conn, *, webhook_id: str, processor: str, event_type: str,
                        payload: str, event_at=None) -> bool:
    """LA IDEMPOTENCIA, decidida por el motor. True = este proceso es el primero.

    Dodo reintenta 8 veces hasta ~28h si no recibe 2xx, así que el mismo evento llega
    repetido. El INSERT ... ON CONFLICT DO NOTHING RETURNING resuelve la carrera sin
    lock ni chequeo previo: si no devuelve fila, otro ya lo tomó → no reprocesar
    (pero ACKear igual, o Dodo sigue reintentando).
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_webhook_events "
            "  (webhook_id, processor, event_type, payload, event_at) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (webhook_id) DO NOTHING RETURNING webhook_id",
            (webhook_id, processor, event_type, payload, event_at),
        )
        first = cur.fetchone() is not None
    conn.commit()
    return first


def close_webhook_event(conn, webhook_id: str, outcome: str) -> None:
    """Marca un evento como procesado y con qué desenlace
    ('applied' | 'ignored_unknown' | 'stale' | 'error:<motivo>')."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE payment_webhook_events SET processed_at = now(), outcome = %s "
            "WHERE webhook_id = %s",
            (outcome, webhook_id),
        )
    conn.commit()


def resync_account_tier(conn, account_id: str, *, reason: str,
                        webhook_id: Optional[str] = None) -> str:
    """Recalcula el tier de una cuenta desde sus suscripciones y lo persiste si cambió.

    ES EL ÚNICO CAMINO por el que el pago se convierte en tier. El veredicto lo da la
    función pura (platform/payments/effects.apply_tier_effect); acá sólo se persiste.
    No escribe si el tier ya es el correcto — así el audit log registra cambios reales
    y no una fila por cada webhook de un cliente estable.
    """
    import sys as _sys
    _plat = str(_REPO_ROOT / "platform")
    if _plat not in _sys.path:
        _sys.path.insert(0, _plat)
    from payments.effects import apply_tier_effect

    subs = list_subscriptions(conn, account_id)
    target = apply_tier_effect(subs)

    with conn.cursor() as cur:
        cur.execute("SELECT tier FROM users WHERE id = %s", (account_id,))
        row = cur.fetchone()
    if row is None:
        return target
    if row[0] == target:
        return target

    set_tier(conn, account_id, target, reason=reason, webhook_id=webhook_id)
    return target


# ── borrado de cuenta · soft-delete con ventana (ticket 2 · migración 0011) ─────
# El middleware consulta user_deleted_state por request autenticada y bloquea con 401
# account_deleted, además de la revocación generacional de credenciales. Estas funciones
# son el estado; la orquestación
# (revocación OAuth instantánea, outbox, purga) vive en account_deletion.py.

DELETION_WINDOW_DAYS = 30


def soft_delete_user(conn, user_id: str,
                     window_days: int = DELETION_WINDOW_DAYS) -> Optional[dict[str, Any]]:
    """Marca la cuenta borrada: acceso muere YA, datos congelados hasta purge_after.
    Idempotente: si ya estaba en ventana, devuelve las fechas EXISTENTES (la fecha
    prometida en el primer mail no se corre). None si el user no existe."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
               SET deleted_at  = COALESCE(deleted_at, now()),
                   purge_after = COALESCE(purge_after,
                                          now() + (%s || ' days')::interval),
                   updated_at  = now()
             WHERE id = %s
            RETURNING id, email, deleted_at, purge_after
            """,
            (str(int(window_days)), user_id),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def reactivate_user(conn, user_id: str) -> Optional[dict[str, Any]]:
    """Reversa del soft-delete (re-login dentro de la ventana): la cuenta vuelve
    INTACTA — los datos nunca se tocaron. Las conexiones OAuth NO vuelven (se
    revocaron al pedir el borrado; el usuario re-conecta)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET deleted_at = NULL, purge_after = NULL, updated_at = now()"
            " WHERE id = %s RETURNING *",
            (user_id,),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return _public_user(row)


def user_deleted_state(conn, user_id: str) -> Optional[dict[str, Any]]:
    """Estado de borrado para el choke point de acceso y el panel.
    Devuelve {deleted_at, purge_after} (None-None si la cuenta está activa),
    o None si el user_id no existe."""
    with conn.cursor() as cur:
        cur.execute("SELECT deleted_at, purge_after FROM users WHERE id = %s", (user_id,))
        return _row_to_dict(cur, cur.fetchone())


def list_purge_due(conn) -> list[dict[str, Any]]:
    """Cuentas cuya ventana venció (purge_after <= now): candidatas a purga total."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, deleted_at, purge_after FROM users"
            " WHERE deleted_at IS NOT NULL AND purge_after <= now()"
        )
        return [_row_to_dict(cur, r) for r in cur.fetchall()]


def merge_local_into_account(conn, device_user_id: str, account_user_id: str) -> dict[str, int]:
    """FUSIÓN (login suave): TODO lo creado bajo el device user pasa a la cuenta —
    puppets, runs (y con ellos outputs/instrumentation/spaces), historial, acciones
    retenidas, jobs y keys BYOK. Reglas explícitas:
      - keys duplicadas (mismo provider en ambos lados) → GANA la de la cuenta;
        la del equipo muere con el device user (cascada), se reporta en `keys_omitidas`.
      - el metering/billing del device user NO se transfiere: el uso local libre no
        se factura retroactivamente (billing_ledger/quota mueren en cascada).
      - al final el device user se BORRA → el próximo arranque anónimo es virgen.
    Solo fusiona DESDE un device user HACIA una cuenta real (jamás cuenta→cuenta ni
    hacia otro device). Una transacción: o pasa todo, o no pasa nada.
    Errores tipados: 'no_device_user' · 'not_a_device_user' · 'no_account' ·
    'account_is_device'."""
    dev, acc = str(device_user_id), str(account_user_id)
    moved: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE id = %s", (dev,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("no_device_user")
        if not is_device_email(row[0]):
            raise ValueError("not_a_device_user")
        cur.execute("SELECT email FROM users WHERE id = %s", (acc,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("no_account")
        if is_device_email(row[0]):
            raise ValueError("account_is_device")

        cur.execute("UPDATE puppets SET owner_id = %s WHERE owner_id = %s", (acc, dev))
        moved["puppets"] = cur.rowcount
        cur.execute("UPDATE runs SET user_id = %s WHERE user_id = %s", (acc, dev))
        moved["runs"] = cur.rowcount
        cur.execute("UPDATE historial SET user_id = %s WHERE user_id = %s", (acc, dev))
        moved["historial"] = cur.rowcount
        cur.execute("UPDATE held_actions SET user_id = %s WHERE user_id = %s", (acc, dev))
        moved["held_actions"] = cur.rowcount
        cur.execute("UPDATE job_queue SET user_id = %s WHERE user_id = %s", (acc, dev))
        moved["jobs"] = cur.rowcount
        cur.execute(
            "UPDATE keys SET user_id = %s WHERE user_id = %s AND provider NOT IN "
            "(SELECT provider FROM keys WHERE user_id = %s)",
            (acc, dev, acc),
        )
        moved["keys"] = cur.rowcount
        cur.execute("SELECT count(*) FROM keys WHERE user_id = %s", (dev,))
        moved["keys_omitidas"] = int(cur.fetchone()[0])
        cur.execute("DELETE FROM users WHERE id = %s", (dev,))
    conn.commit()
    return moved


# ── puppets (recetas; el taller guarda la receta YA validada) ──────────────────

def create_puppet(conn, *, owner_id: str, name: str, nicho: str, config: dict,
                  recipe_schema_version: str = "v1", status: str = "draft",
                  commit: bool = True) -> dict[str, Any]:
    """
    Persiste una receta validada en puppets.config (JSONB). El CALLER (router) ya
    validó con recipe_validator ANTES de llegar acá — la DB es el último eslabón,
    no el validador.

    `commit=False` deja la fila en la transacción abierta (para un import atómico que
    crea métodos + puppet en UNA sola txn y hace rollback si algo falla).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO puppets (owner_id, name, nicho, config, recipe_schema_version, status)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING *
            """,
            (owner_id, name, nicho, json.dumps(config), recipe_schema_version, status),
        )
        row = _row_to_dict(cur, cur.fetchone())
    if commit:
        conn.commit()
    return row


def get_puppet(conn, puppet_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM puppets WHERE id = %s", (puppet_id,))
        return _row_to_dict(cur, cur.fetchone())


def delete_puppet(conn, puppet_id: str, *, owner_id: str) -> bool:
    """Delete one persisted agent, scoped atomically to its owner.

    Child data follows the schema's existing FK policy (agent-owned memory and chats
    cascade; historical runs retain their row with a null puppet_id).
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM puppets WHERE id = %s AND owner_id = %s",
                    (puppet_id, owner_id))
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


def list_puppets(conn, owner_id: str, *, nicho: Optional[str] = None,
                 status: Optional[str] = None) -> list[dict[str, Any]]:
    """Los agentes del dueño, **ordenados por lo último que usó**.

    [rediseño · fase 2 · 2.2] El orden era `created_at DESC` y la pantalla decía «Ordenados
    por lo último que usaste»: dos cosas distintas. La tabla `puppets` no tiene columna de
    último uso y no hace falta inventarla — el dato ya está en `runs.started_at` (1.225 filas
    con dato sobre 2.484 runs) y nadie hacía ese JOIN. Se hace acá, con `LEFT JOIN` y no
    `JOIN`, para que un agente sin usar no DESAPAREZCA de la lista: cae al final, que es
    donde va lo que nunca se usó. `usado_at` sale en la fila, así que la cara puede decir
    «hace 3 días» sin pedir nada más.
    """
    q = ("SELECT p.*, u.usado_at FROM puppets p "
         "LEFT JOIN (SELECT puppet_id, MAX(started_at) AS usado_at FROM runs "
         "           WHERE puppet_id IS NOT NULL GROUP BY puppet_id) u "
         "  ON u.puppet_id = p.id "
         "WHERE p.owner_id = %s")
    args: list[Any] = [owner_id]
    if nicho:
        q += " AND p.nicho = %s"
        args.append(nicho)
    if status:
        q += " AND p.status = %s"
        args.append(status)
    # NULLS LAST a mano: `usado_at IS NULL` da 0/1 en sqlite y false/true en Postgres, y los
    # dos ordenan igual con ASC — el que nunca se usó queda último en las dos bases.
    q += " ORDER BY (u.usado_at IS NULL) ASC, u.usado_at DESC, p.created_at DESC"
    with conn.cursor() as cur:
        cur.execute(q, tuple(args))
        rows = cur.fetchall()
        return [_row_to_dict(cur, r) for r in rows]


def backfill_human_name(conn, puppet: dict[str, Any]) -> dict[str, Any]:
    """Migrate an old technical label to a safe visible name, idempotently.

    Old rows predate the naming flow and can carry a UUID, an export path or a
    numeric generated label in either ``puppets.name`` or ``config.meta.name``.
    Keep their stable ID untouched, but persist the display fallback so every
    future load sees the same human-facing identity.
    """
    current_config = puppet.get("config") if isinstance(puppet.get("config"), dict) else {}
    name = agent_catalog.display_name(puppet.get("name"), current_config)
    config = agent_catalog.config_with_display_name(current_config, name)
    if puppet.get("name") == name and config == current_config:
        return puppet
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE puppets SET name = %s, config = %s WHERE id = %s RETURNING *",
            (name, json.dumps(config), puppet["id"]),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row or puppet


def update_config(conn, puppet_id: str, config: dict) -> Optional[dict[str, Any]]:
    """El taller edita la receta → sube `version` (versión de ESTA receta, schema.sql §2).
    [botón Mesa] SINCRONIZA las columnas name/nicho desde config.meta: el rename del agente vive
    en la receta (meta.name/meta.nicho), y sin esto la columna quedaba STALE → "Mis agentes" (que
    lee la columna vía list_puppets) mostraba el nombre viejo tras renombrar. COALESCE: si la receta
    no trae meta.name/nicho no-vacío (ej. un equip/desequip que preserva el config), se conserva el
    valor actual de la columna."""
    _meta = (config or {}).get("meta") or {}
    _mn = _meta.get("name"); _nm = _mn.strip() if isinstance(_mn, str) and _mn.strip() else None
    _mc = _meta.get("nicho"); _ni = _mc.strip() if isinstance(_mc, str) and _mc.strip() else None
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE puppets
               SET config = %s, version = version + 1, updated_at = now(),
                   name = COALESCE(%s, name), nicho = COALESCE(%s, nicho)
             WHERE id = %s
             RETURNING *
            """,
            (json.dumps(config), _nm, _ni, puppet_id),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def backfill_config(conn, puppet_id: str, config: dict) -> bool:
    """MIGRACIÓN SILENCIOSA de la receta — NO es una edición del usuario.

    Usada por el completado del KIT BASE (kit_base.ensure_kit) al CARGAR un agente viejo:
    escribe el config normalizado sin subir `version` y sin tocar name/nicho. `version` es
    la versión de la receta que el usuario editó (schema.sql §2): subirla acá le mostraría
    "v4" a alguien que no tocó nada. `updated_at` tampoco se mueve — un backfill no es
    actividad del dueño y "Mis agentes" ordena por created_at.

    Es idempotente por construcción: el caller sólo llega acá cuando ensure_kit devolvió
    cambió=True, y la segunda carga ya no cambia nada. Devuelve True si escribió una fila."""
    with conn.cursor() as cur:
        cur.execute("UPDATE puppets SET config = %s WHERE id = %s",
                    (json.dumps(config), puppet_id))
        tocadas = cur.rowcount
    conn.commit()
    return bool(tocadas)


def set_status(conn, puppet_id: str, status: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE puppets SET status = %s, updated_at = now() WHERE id = %s RETURNING *",
            (status, puppet_id),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def marcar_usado(conn, puppet_id: str) -> bool:
    """`draft` → `active` la PRIMERA vez que un agente se usa. Devuelve si cambió algo.

    [rediseño · fase 2 · 2.2 · decisión del dueño 2026-09-07]

    QUÉ ESTABA ROTO, MEDIDO ANTES DE ESCRIBIR ESTO. El mecanismo del estado estaba ENTERO y
    sin un solo llamante: la columna existe (`schema.sql`: `draft|active|archived`),
    `list_puppets` filtra por ella, `GET /v1/users/{id}/puppets` acepta `?status=`, y
    `set_status` está definida y exportada. Contra la `aleph.db` real: **1.625 de 1.625 en
    `draft`**. O sea que el filtro «Listos / Borradores» que pide el diseño habría mostrado
    Listos = 0 para siempre. Es el defecto nº12 de esta casa: el cable tendido y la luz
    apagada.

    LA REGLA LA ELIGIÓ EL DUEÑO entre tres medidas contra la DB real:
        usado al menos una vez (≥1 run o chat) → 877 listos / 748 borradores   ← ÉSTA
        su receta tiene herramientas           → 1.284 / 341
        un botón explícito de publicar         → 0 / 1.625
    «Borrador» pasa a significar «lo armaste y nunca lo usaste», que es lo que el mockup
    sugiere, y el filtro nace con datos reales el primer día.

    ⚠️ POR QUÉ UN `UPDATE … WHERE status='draft'` Y NO `set_status`. Dos motivos, los dos
    importan: es IDEMPOTENTE (se llama en cada run y sólo escribe la primera vez) y **jamás
    resucita un `archived`**. Llamar a `set_status(…, 'active')` a ciegas desde el camino
    caliente desarchivaría cualquier agente que el dueño hubiera archivado, en silencio.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE puppets SET status = 'active', updated_at = now() "
            "WHERE id = %s AND status = 'draft'",
            (puppet_id,),
        )
        cambio = cur.rowcount
    conn.commit()
    return bool(cambio)


def backfill_usados(conn, owner_id: str) -> int:
    """Promueve a `active` los agentes de este dueño que YA tienen huella de uso.

    [rediseño · fase 2 · 2.2] `marcar_usado` cubre de acá en adelante; esto cubre el pasado.
    Sin esto, el día que se estrene el filtro «Listos» mostraría 0 y todo el historial del
    usuario aparecería como borrador — que es exactamente el defecto que esta obra vino a
    cerrar, servido al revés.

    Medido sobre la `aleph.db` real: 875 puppets con al menos un run, 18 con al menos un
    chat, **877 con uno u otro** (los dos conjuntos casi se solapan). Por eso la huella es
    `runs ∪ chats` y no sólo runs: 2 agentes que sólo se hablaron por la Sala también fueron
    usados, y decirles «borrador» sería mentir por dos.

    ES BARATO Y ES IDEMPOTENTE: un solo UPDATE acotado al dueño, que sólo toca filas en
    `draft`. La segunda corrida escribe 0 filas. Por eso puede vivir en el camino de lectura
    de la lista, igual que el `ensure_kit` que ya está ahí.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE puppets SET status = 'active', updated_at = now() "
            "WHERE owner_id = %s AND status = 'draft' AND id IN ("
            "  SELECT puppet_id FROM runs  WHERE puppet_id IS NOT NULL "
            "  UNION "
            "  SELECT puppet_id FROM chats WHERE puppet_id IS NOT NULL)",
            (owner_id,),
        )
        n = cur.rowcount
    conn.commit()
    return int(n or 0)


# ── runs ──────────────────────────────────────────────────────────────────────

def create_run(conn, *, puppet_id: Optional[str], user_id: Optional[str],
               space_id: Optional[str] = None, intent: Optional[str] = None) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO runs (puppet_id, user_id, space_id, intent)
            VALUES (%s, %s, %s, %s) RETURNING *
            """,
            (puppet_id, user_id, space_id, intent),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    # [FIX-P10 §1] EL LATIDO DEL MOTOR. Este proceso pasa a ser el testigo de que el run
    # está vivo. Va acá y no en el executor porque create_run es EL choke point: cubre al
    # executor, a la continuación de métodos y a la inspección con una sola línea.
    # [rediseño · fase 2 · 2.2] Y EL AGENTE DEJA DE SER UN BORRADOR. Va en el MISMO choke
    # point que el latido, y por el mismo motivo que dice el comentario de arriba: cubre al
    # executor, a la continuación de métodos y a la inspección con una sola línea. Es
    # idempotente y no toca un `archived`. Como el latido, jamás puede tumbar un run.
    try:
        if puppet_id:
            marcar_usado(conn, puppet_id)
    except Exception:  # noqa: BLE001 — que un agente siga diciendo «borrador» es peor que nada,
        _log_usado = None                 # pero MUCHO menos peor que perder el run
    try:
        from app.phase1 import run_lifecycle as _rl
        _rl.marcar_vivo(row and row.get("id"))
    except Exception:  # noqa: BLE001 — el registro del latido jamás tumba un run
        pass
    return row


def finish_run(conn, run_id: str, status: str = "done") -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE runs SET status = %s, finished_at = now() WHERE id = %s RETURNING *",
            (status, run_id),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    # [FIX-P10 §1] el turno terminó (bien o mal) ⇒ se apaga el latido. Si el proceso muere
    # antes de llegar acá, el reaper del boot marca el run huérfano (run_lifecycle).
    try:
        from app.phase1 import run_lifecycle as _rl
        _rl.marcar_cerrado(run_id)
    except Exception:  # noqa: BLE001
        pass
    return row


def get_run(conn, run_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
        return _row_to_dict(cur, cur.fetchone())


def runs_exist(conn, run_ids) -> set[str]:
    """TICKET 26 · VERIFICACIÓN DE LA CITA AL LEER. Dado un conjunto de run_ids (los que
    citan las memorias), devuelve el subconjunto que EXISTE en la tabla runs — en UNA sola
    query (no N). El read-path de la memoria lo usa para marcar cada cita como verificada
    (resuelve a un run real) o colgada (el run que la 'originó' no existe / fue borrado).
    Es la mitad backend del patrón Copilot: una cita no es texto guardado, es una fuente
    auditable. Fail-safe: entrada vacía → set vacío; ids no-UUID se ignoran sin romper."""
    ids = {str(r).strip() for r in (run_ids or []) if r and str(r).strip()}
    if not ids:
        return set()
    with conn.cursor() as cur:
        # id::text = ANY(...) evita el casteo a uuid[] (un id basura no rompe la query entera).
        cur.execute("SELECT id::text FROM runs WHERE id::text = ANY(%s)", (list(ids),))
        return {row[0] for row in cur.fetchall()}


# ── ownership lookups (authz · T6) ─────────────────────────────────────────────
# El contrato AUTH (§4.5): user_id scopea TODO. Estos lookups resuelven el DUEÑO de
# un recurso por su id (sin exponer el resto del recurso) para que el router autorice
# session.owner == dueño. Devuelven None si el recurso no existe o no tiene dueño
# (recurso anónimo); el router decide "owner-gated cuando hay dueño, abierto si no".

def puppet_owner(conn, puppet_id: str) -> Optional[str]:
    """owner_id (str) del agente, o None si no existe."""
    with conn.cursor() as cur:
        cur.execute("SELECT owner_id FROM puppets WHERE id = %s", (puppet_id,))
        row = cur.fetchone()
    return str(row[0]) if row and row[0] is not None else None


def run_owner(conn, run_id: str) -> Optional[str]:
    """user_id (str) dueño del run, o None si no existe o es anónimo (user_id NULL)."""
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    return str(row[0]) if row and row[0] is not None else None


def space_owner(conn, space_id: str) -> Optional[str]:
    """user_id (str) dueño de un space (vía el run más reciente con dueño que lo emitió),
    o None si ningún run dueño usó ese space (space anónimo: inspect/demo) → lectura abierta."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT user_id FROM runs WHERE space_id = %s AND user_id IS NOT NULL "
            "ORDER BY started_at DESC LIMIT 1",
            (space_id,),
        )
        row = cur.fetchone()
    return str(row[0]) if row and row[0] is not None else None


# ── held_actions (send/money RETENIDO esperando OK por HTTP — approve-by-HTTP) ──

def create_held_action(conn, *, run_id: str, user_id: Optional[str], recipe: dict,
                       server: str, tool: str, args: dict,
                       level: Optional[str] = None,
                       agent_path: Optional[list] = None,
                       via_delegation: bool = False,
                       depth: Optional[int] = None,
                       turn_text: Optional[str] = None) -> dict[str, Any]:
    """Persiste una acción de alta consecuencia RETENIDA por el gate. Devuelve la fila
    con `id` = approval_id. Guarda la receta para poder re-armar el belt al aprobar.

    STEP 2·B1 · PROVENANCE del árbol de delegación: `agent_path` (raíz→hoja: qué sub-agente
    pidió el OK), `via_delegation` (si subió de un hijo) y `depth` se PERSISTEN — antes vivían
    sólo en la respuesta efímera → un re-read del DB (recarga de página, listado de pendientes
    tras reinicio) perdía a QUÉ sub-agente atribuir la acción retenida. La columna money-invariant
    (la held sigue gateada y aprobable) ya estaba cubierta por recipe/server/tool/args."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO held_actions
                (run_id, user_id, recipe, server, tool, args, level,
                 agent_path, via_delegation, depth, turn_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, run_id, user_id, server, tool, args, level, status, created_at,
                      agent_path, via_delegation, depth, turn_text
            """,
            (run_id, user_id, json.dumps(recipe), server, tool, json.dumps(args), level,
             json.dumps(agent_path) if agent_path is not None else None,
             bool(via_delegation), depth,
             (turn_text or None)),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def get_held_action(conn, approval_id: str) -> Optional[dict[str, Any]]:
    """Recupera una acción retenida por approval_id (incluye la receta para ejecutarla)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM held_actions WHERE id = %s", (approval_id,))
        return _row_to_dict(cur, cur.fetchone())


def decide_held_action(conn, approval_id: str, *, status: str,
                       result: Optional[str] = None,
                       expect: str = "held") -> Optional[dict[str, Any]]:
    """Transiciona la acción a `status` SOLO si está en `expect` (compare-and-set atómico).
    Default `expect='held'` (compat). Tras un claim, el caller pasa `expect='executing'` para
    cerrar la transición executing→executed (o revertir executing→held en retry). rowcount 0 →
    None (otro thread ya transicionó) → el caller NO re-ejecuta."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE held_actions
               SET status = %s, result = %s, decided_at = now()
             WHERE id = %s AND status = %s
            RETURNING id, run_id, user_id, server, tool, level, status, result, decided_at
            """,
            (status, result, approval_id, expect),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def claim_held_action(conn, approval_id: str) -> Optional[dict[str, Any]]:
    """CLAIM ATÓMICO antes de ejecutar — CIERRE DEL DOBLE-GASTO (deuda #1, hallazgo del
    security-reviewer). Pasa la acción de `held`→`executing` en UN ÚNICO UPDATE condicional.

    Bajo N requests concurrentes al mismo approval_id, el row-lock de Postgres serializa los
    UPDATE: el PRIMER thread setea `executing` y commitea; el resto re-evalúa el WHERE (ahora
    status≠'held') y matchea 0 filas → recibe None. Así SOLO el ganador del claim ejecuta el
    efecto externo (send/pago) → exactamente-una-vez. (READ COMMITTED basta: el bloqueado
    re-lee la fila ya committeada como 'executing'.)

    Devuelve la fila reclamada (con recipe+args para ejecutar) o None si ya no estaba en `held`.
    Setea `decided_at=now()` como marca temporal del claim (la usa el recovery-sweep)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE held_actions
               SET status = 'executing', decided_at = now()
             WHERE id = %s AND status = 'held'
            RETURNING id, run_id, user_id, recipe, server, tool, args, level, status, created_at
            """,
            (approval_id,),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def recover_stuck_executing(conn, *, ttl_seconds: int = 600) -> int:
    """RECOVERY-SWEEP (caveat #2 del security-reviewer): una fila en `executing` cuyo
    `decided_at` quedó viejo (> ttl) ⇒ el proceso murió DESPUÉS del claim pero antes de cerrar
    la transición — quedaría colgada para siempre. La devolvemos a `held` para que el dueño
    pueda re-aprobar. TTL GENEROSO (default 10 min, >> cualquier send real) para NO tocar
    approves concurrentes en vuelo (esos tienen `decided_at` de hace milisegundos). Devuelve
    cuántas recuperó.

    Honestidad (riesgo residual, NO maquillado): si el proceso murió en la ventana de ~ms entre
    que el send EXTERNO completó y el UPDATE a `executed`, recuperar→reintentar PODRÍA re-enviar.
    Es una ventana de crash diminuta; la alternativa (acción colgada para siempre) es peor para
    el usuario. El cierre robusto definitivo = idempotency-key en el send externo (follow-up
    mayor, fuera de esta tanda)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE held_actions
               SET status = 'held',
                   result = 'recovered: estaba colgada en executing (proceso caído mid-send)'
             WHERE status = 'executing'
               AND decided_at < now() - make_interval(secs => %s)
            """,
            (ttl_seconds,),
        )
        n = cur.rowcount
    conn.commit()
    return n


# ── keys (BYOK cifrada at-rest — NUNCA plaintext) ──────────────────────────────

def upsert_key(conn, *, user_id: str, provider: str, secret: str) -> dict[str, Any]:
    """
    Guarda/actualiza una credencial BYOK CIFRADA (Fernet). El plaintext nunca toca
    Postgres: se cifra acá y se guarda el token en BYTEA. Devuelve SOLO metadatos
    (provider/last4), JAMÁS el secreto.
    """
    if not secret:
        raise ValueError("secret vacío")
    ciphertext = encrypt_secret(secret)
    last4 = _last4(secret)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO keys (user_id, provider, ciphertext, last4)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, provider)
            DO UPDATE SET ciphertext = EXCLUDED.ciphertext,
                          last4      = EXCLUDED.last4
            RETURNING id, user_id, provider, last4, enc_scheme, created_at
            """,
            (user_id, provider, psy_bytea(ciphertext), last4),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row  # sin ciphertext ni plaintext


def get_key(conn, user_id: str, provider: str) -> Optional[str]:
    """
    Descifra y devuelve el secreto BYOK (uso INTERNO del runtime al cablear una tool).
    NUNCA se serializa a una respuesta HTTP. Devuelve None si no hay key.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ciphertext FROM keys WHERE user_id = %s AND provider = %s",
            (user_id, provider),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return decrypt_secret(row[0])


def list_keys(conn, user_id: str) -> list[dict[str, Any]]:
    """Metadatos de las keys del usuario: provider + last4. JAMÁS el secreto."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT provider, last4, enc_scheme, created_at FROM keys "
            "WHERE user_id = %s ORDER BY provider",
            (user_id,),
        )
        rows = cur.fetchall()
        return [_row_to_dict(cur, r) for r in rows]


def delete_key(conn, user_id: str, provider: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM keys WHERE user_id = %s AND provider = %s", (user_id, provider)
        )
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


# ── STEP 2·A3 · clasificación de conexiones (FUENTE ÚNICA para todas las superficies) ──
# El vault guarda, además del conector base, filas companion: "<name>__oauth" (refresh_token
# cifrado, presente = conexión durable) y "<name>__oauth_partial" (marcador NO secreto = se pidió
# offline pero NO vino refresh → el access token caduca ~1h). TODA superficie que pinte "Conectado"
# (Conectar, El Cuarto/atoms, cards de belt, export) DEBE clasificar con esta función — si lee los
# providers crudos de list_keys, (a) muestra los companion como si fueran conectores y (b) pinta un
# conector PARCIAL como verde "Conectado" (false-green que mata a la hora, en medio de un run).
_OAUTH_PARTIAL_SUFFIX = "__oauth_partial"
_OAUTH_COMPANION_SUFFIX = "__oauth"


def classify_key_providers(providers) -> tuple[set, set]:
    """De un iterable de provider names (de list_keys) devuelve (connected, partial):
      - connected: conectores base con credencial guardada (SIN las filas companion __oauth*).
      - partial:   bases con marcador '__oauth_partial' (offline sin refresh; caduca ~1h).
    Un base parcial está en AMBOS (tiene access token pero es incompleto) → el consumidor debe
    chequear `partial` ANTES que `connected`."""
    connected: set = set()
    partial: set = set()
    for p in providers:
        if not p:
            continue
        if p.endswith(_OAUTH_PARTIAL_SUFFIX):
            partial.add(p[: -len(_OAUTH_PARTIAL_SUFFIX)])
            continue
        if p.endswith(_OAUTH_COMPANION_SUFFIX):
            continue   # companion de refresh: plumbing, no es un conector propio
        connected.add(p)
    return connected, partial


def is_companion_provider(provider: str) -> bool:
    """True si el provider es una fila de plumbing OAuth (__oauth / __oauth_partial), no un conector."""
    return bool(provider) and (provider.endswith(_OAUTH_COMPANION_SUFFIX)
                               or provider.endswith(_OAUTH_PARTIAL_SUFFIX))


def psy_bytea(b: bytes):
    """Envuelve bytes para el BYTEA de psycopg2. En el cliente, los devuelve crudos.

    [Casa 2 · 2.2b] Es la única fuga de driver fuera de `platform/db/` (un uso: el
    INSERT de la BYOK cifrada, arriba). `psycopg2.Binary` es un adaptador de psycopg2:
    pasárselo a SQLite guardaría el objeto envuelto, no los bytes. SQLite toma `bytes`
    directo para una columna BLOB — verificado.
    """
    if _dbmod().es_cliente():
        return b
    import psycopg2
    return psycopg2.Binary(b)


__all__ = [
    "get_conn", "encrypt_secret", "decrypt_secret",
    "get_or_create_user", "get_user", "set_tier",
    "DEVICE_EMAIL_PREFIX", "is_device_email", "is_device_user",
    "get_or_create_device_user", "merge_local_into_account",
    "create_puppet", "get_puppet", "list_puppets", "delete_puppet", "backfill_human_name", "update_config", "set_status",
    "marcar_usado", "backfill_usados",
    "create_run", "finish_run", "get_run",
    "puppet_owner", "run_owner", "space_owner",
    "mint_session", "session_owner",
    "upsert_key", "get_key", "list_keys", "delete_key",
    "classify_key_providers", "is_companion_provider",
    # Step 2 · A3 — memoria del agente (por puppet_id, cross-run)
    "list_memories", "add_memory", "get_memory", "memory_owner",
    "update_memory", "delete_memory", "clear_memories",
    "memory_usage", "enforce_memory_caps",
    # Step 2 · B2 — memoria COMPARTIDA (por composition_id = Cuarto, con autoría)
    "list_shared_memories", "add_shared_memory", "get_shared_memory",
    "shared_memory_owner", "update_shared_memory", "delete_shared_memory",
    "clear_shared_memories", "shared_memory_usage", "enforce_shared_memory_caps",
    "seed_shared_bus",   # ORDEN 4 · composición — sembrar el bus desde piezas elegidas
    # ORDEN 2 · Sistema 2 — memoria de CUENTA (por owner_id = users.id, cruza todo)
    "list_owner_memories",
    "list_account_memories", "add_account_memory", "get_account_memory",
    "account_memory_owner", "update_account_memory", "delete_account_memory",
    "clear_account_memories", "account_memory_usage", "enforce_account_memory_caps",
    # ORDEN 5 · gate de propuesta de cuenta (inerte pinned=FALSE → confirmar/rechazar)
    "add_account_proposal", "list_account_proposals", "confirm_account_proposal",
    "reject_account_proposal",
    # Step 2 · C1 — CONOCIMIENTO / RAG (por composition_id = Cuarto)
    "add_knowledge_doc", "set_doc_status", "set_knowledge_doc_status",
    "add_knowledge_chunk", "list_knowledge_docs", "get_knowledge_doc",
    "delete_knowledge_doc", "knowledge_doc_owner", "list_chunks_for_retrieval",
    "knowledge_usage", "enforce_knowledge_caps",
]


# ── Fase 4 · listados para Biblioteca (outputs) + Historial (runs) ──────────────

def create_output(conn, *, run_id: str, kind: str, content: Optional[str] = None,
                  uri: Optional[str] = None, mime: Optional[str] = None,
                  bytes_: Optional[int] = None) -> Optional[dict[str, Any]]:
    """Persiste un output de un run (Biblioteca = 'Su obra'). El run lo produce."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO outputs (run_id, kind, mime, uri, content, bytes) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
            (run_id, kind, mime, uri, content, bytes_),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def list_runs(conn, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Historial de sesiones del usuario + costo real (de instrumentation_logs)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT r.id, r.puppet_id, r.space_id, r.intent, r.status, r.started_at, "
            "r.finished_at, p.name AS puppet_name, "
            "il.costo->>'usd_total' AS usd_total, il.costo->>'total_tokens' AS total_tokens "
            "FROM runs r LEFT JOIN puppets p ON p.id = r.puppet_id "
            "LEFT JOIN instrumentation_logs il ON il.run_id = r.id "
            "WHERE r.user_id = %s ORDER BY r.started_at DESC LIMIT %s",
            (user_id, limit),
        )
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def get_output_owned(conn, output_id: str) -> Optional[dict[str, Any]]:
    """Un output + el user_id DUEÑO (vía su run). Para authz de descarga en Biblioteca:
    solo el dueño puede bajar su obra. user_id queda None si el run fue anónimo (no
    descargable por nadie autenticado, lado seguro)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT o.id, o.run_id, o.kind, o.mime, o.uri, o.bytes, o.created_at, "
            "r.user_id "
            "FROM outputs o JOIN runs r ON r.id = o.run_id WHERE o.id = %s",
            (output_id,),
        )
        return _row_to_dict(cur, cur.fetchone())


def list_outputs(conn, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """La obra del usuario (Biblioteca): outputs ligados a sus runs."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT o.id, o.run_id, o.kind, o.mime, o.uri, o.content, o.bytes, o.created_at, "
            "r.puppet_id, r.intent, p.name AS puppet_name "
            "FROM outputs o JOIN runs r ON r.id = o.run_id "
            "LEFT JOIN puppets p ON p.id = r.puppet_id "
            "WHERE r.user_id = %s ORDER BY o.created_at DESC LIMIT %s",
            (user_id, limit),
        )
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


# ── Step 2 · A3 · Memoria del agente (por puppet_id, PERSISTENTE entre runs) ─────
# Idiom del repo: cursor de tuplas + _row_to_dict + commit explícito por método.
# La FRONTERA (cuántas entradas/bytes por agente) la impone el runtime por TIER
# (recipe_enforcer.TIER_MEMORY_CAPS) vía enforce_memory_caps — NO editable por receta.

def _content_bytes(content: str) -> int:
    """Tamaño real en bytes UTF-8 de una memoria (contabilidad de caps)."""
    return len((content or "").encode("utf-8"))


def _is_uuid(s: Any) -> bool:
    """¿`s` es un UUID sintácticamente válido? Guard ANTES de tocar columnas uuid de Postgres: un
    string no-UUID en 'WHERE id = %s' contra una columna uuid revienta con DataError (aborta la txn).
    Clasificar el id malformado como skip honesto en vez de dejar que explote."""
    try:
        _uuid.UUID(str(s))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _truncate_bytes(content: str, max_bytes: int) -> str:
    """Trunca `content` a `max_bytes` en frontera UTF-8 válida (nunca parte un multibyte). Espeja el
    truncado del panel (router._truncate_bytes) para que una sola pieza no exceda el techo del bus."""
    b = (content or "").encode("utf-8")
    if len(b) <= max_bytes:
        return content or ""
    return b[:max(0, max_bytes)].decode("utf-8", "ignore")


def list_memories(conn, puppet_id: str, *, limit: Optional[int] = None,
                  pinned_only: bool = False) -> list[dict[str, Any]]:
    """Las memorias de UN agente, más-reciente-primero. Lo que se ve = lo que hay
    (cero memoria oculta): el panel muestra exactamente esta lista."""
    sql = ("SELECT id, puppet_id, source, content, bytes, pinned, uri, meta, "
           "created_at, updated_at FROM agent_memories WHERE puppet_id = %s")
    args: list[Any] = [puppet_id]
    if pinned_only:
        sql += " AND pinned = TRUE"
    sql += " ORDER BY created_at DESC"
    if limit is not None:
        sql += " LIMIT %s"
        args.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def list_owner_memories(conn, owner_id: str, *, limit: Optional[int] = None) -> list[dict[str, Any]]:
    """TODA la memoria de agente de UN DUEÑO, con el nombre del agente al lado.

    POR QUÉ EXISTE, y por qué no alcanzaba con lo que ya había. `list_memories` es por
    AGENTE, y así estaba bien para el estante y para la herencia. Pero el panel de memoria
    contesta otra pregunta —«¿qué se acuerda Aleph DE MÍ?»— y esa no es de un agente: en
    esta máquina el dueño real tiene **190 agentes** y sus recuerdos reales están repartidos
    en decenas de ellos, porque el `puppet_id` de la Sala sale de `?puppet=` y por defecto
    es `null`, así que cada corrida acuñó el suyo. Un panel que preguntara agente por agente
    serían 190 pedidos para pintar una lista.

    JOIN CONTRA `puppets`, Y NO ES DECORACIÓN: `agent_memories` **no tiene columna de
    dueño** —el scope vive en el agente— así que el filtro por dueño SÓLO puede salir de la
    tabla de agentes. Sin el join no hay forma de scopear, y sin scope el panel le mostraría
    a un usuario la memoria de otro. Es el mismo criterio de `memory_owner()`, en lote.

    Devuelve las MISMAS columnas que `list_memories` más `puppet_name`, para que el panel
    pueda decir de qué agente es cada recuerdo y llamar a su DELETE (que es por agente).
    Lo que se ve = lo que hay: cero memoria oculta, igual que el panel por agente.
    """
    sql = ("SELECT m.id, m.puppet_id, m.source, m.content, m.bytes, m.pinned, m.uri, "
           "m.meta, m.created_at, m.updated_at, p.name AS puppet_name "
           "FROM agent_memories m JOIN puppets p ON p.id = m.puppet_id "
           "WHERE p.owner_id = %s ORDER BY m.created_at DESC")
    args: list[Any] = [owner_id]
    if limit is not None:
        sql += " LIMIT %s"
        args.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def add_memory(conn, *, puppet_id: str, content: str, source: str = "agent",
               pinned: bool = True, uri: Optional[str] = None,
               meta: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Agrega UNA memoria a un agente. `bytes` se calcula del content (para los caps).
    Dos vías la usan: el DESTILADO al cierre del run (source='agent') y el WRITE directo
    del panel (source='user'). Ninguna pasa por el gate: es estado LOCAL del usuario."""
    b = _content_bytes(content)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO agent_memories (puppet_id, source, content, bytes, pinned, uri, meta) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (puppet_id, source, content, b, pinned, uri,
             json.dumps(meta) if meta is not None else None),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def get_memory(conn, memory_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, puppet_id, source, content, bytes, pinned, uri, meta, "
            "created_at, updated_at FROM agent_memories WHERE id = %s", (memory_id,),
        )
        return _row_to_dict(cur, cur.fetchone())


def memory_owner(conn, memory_id: str) -> Optional[str]:
    """El user_id DUEÑO de una memoria (vía el agente). Para authz anti-IDOR de
    edición/borrado de UNA entrada. None si la memoria no existe."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.owner_id FROM agent_memories m JOIN puppets p ON p.id = m.puppet_id "
            "WHERE m.id = %s", (memory_id,),
        )
        row = cur.fetchone()
    return str(row[0]) if row and row[0] is not None else None


def update_memory(conn, memory_id: str, *, content: str) -> Optional[dict[str, Any]]:
    """Edita el texto de una memoria (recalcula bytes + updated_at)."""
    b = _content_bytes(content)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE agent_memories SET content = %s, bytes = %s, updated_at = now() "
            "WHERE id = %s RETURNING *",
            (content, b, memory_id),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def reclassify_memory(conn, memory_id: str, kind: str) -> Optional[dict[str, Any]]:
    """RECLASIFICAR (op 3 del MD de memoria): mueve una entrada skill↔episodica tocando
    SOLO meta.kind (jsonb_set NULL-safe) + updated_at — el contenido/procedencia no se
    tocan. La frontera pericia/episódica es difusa por diseño; esto es el usuario
    corrigiéndola cuando importa. El caller valida kind y la pertenencia (anti-IDOR).

    [Casa 2 · 2.4] `jsonb_set`/`to_jsonb` los RECHAZA la capa de dialecto (en SQLite
    devuelven JSONB BINARIO, no texto — corromperían la columna TEXT). El equivalente
    exacto es `json_set`: NULL-safe igual, preserva el resto del objeto, no anida y
    auto-cita el valor de texto (medido). `now()` sí lo traduce el dialecto → sólo diverge
    la función JSON, no el statement entero. Mismo patrón de rama-por-rol que pop_control."""
    if _dbmod().es_cliente():
        sql = ("UPDATE agent_memories SET "
               "meta = json_set(coalesce(meta, '{}'), '$.kind', %s), "
               "updated_at = now() WHERE id = %s RETURNING *")
    else:
        sql = ("UPDATE agent_memories SET "
               "meta = jsonb_set(coalesce(meta, '{}'::jsonb), '{kind}', to_jsonb(%s::text)), "
               "updated_at = now() WHERE id = %s RETURNING *")
    with conn.cursor() as cur:
        cur.execute(sql, (kind, memory_id))
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def delete_memory(conn, memory_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM agent_memories WHERE id = %s", (memory_id,))
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


def touch_memory(conn, memory_id: str) -> None:
    """REFUERZO (dedupe en captura): una memoria nueva equivalente a una existente NO se duplica;
    se 'refuerza' la existente bumpeando updated_at (queda más reciente = más viva en el recall).
    No cambia contenido ni kind. Sin commit propio: el caller (destilado) commitea el batch."""
    with conn.cursor() as cur:
        cur.execute("UPDATE agent_memories SET updated_at = now() WHERE id = %s", (memory_id,))


def count_agent_memories_today(conn, puppet_id: str) -> int:
    """Cuántas memorias DESTILADAS (source='agent') capturó este agente HOY — para el cap diario
    del distilador (mata el 273/día). No cuenta las source='user' (captura explícita, sin techo)."""
    with conn.cursor() as cur:
        cur.execute(
            # el cap es del DESTILADO (volumen de captura por turno) — las HEREDADAS al nacer
            # (meta.inherited) NO son captura del día, no cuentan (si no, heredar floodea el cap).
            "SELECT count(*) FROM agent_memories WHERE puppet_id = %s AND source = 'agent' "
            "AND created_at::date = CURRENT_DATE AND (meta->>'inherited') IS DISTINCT FROM 'true'",
            (puppet_id,),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


def inherit_memories(conn, *, source_puppet_id: str, dest_puppet_id: str,
                     policy: Any = "skill_only", commit: bool = True) -> int:
    """TICKET 27 · HERENCIA DE MEMORIA AL NACER. Copia el estante del agente `source` al `dest`
    con PROVENANCE (cada entrada marca su origen). `apply_inheritance` acota por política
    (skill_only default / {projects|entries}) y EXCLUYE lo confidencial (invariante del MD).
    El CALLER (router) ya validó que source y dest son del MISMO dueño (anti-IDOR). Distinto del
    bus B2 (compartir en runtime): esto es una COPIA-al-nacer, independiente del origen a futuro.
    Devuelve cuántas entradas se heredaron. `commit=False` para atomicidad con create_puppet."""
    from app.phase1 import memory_recall as _mrec
    src = list_memories(conn, source_puppet_id)                 # DESC
    elegibles = _mrec.apply_inheritance(src, policy)            # acota + saca confidencial
    n = 0
    with conn.cursor() as cur:
        for m in elegibles:
            content = m.get("content") or ""
            if not content:
                continue
            _meta = dict(m.get("meta") or {})
            _meta.update({
                "inherited": True,
                "origin_puppet": str(source_puppet_id),
                "origin_memory_id": str(m.get("id")),
                # provenance/kind del origen se conservan; run_id del origen queda como traza.
            })
            cur.execute(
                "INSERT INTO agent_memories (puppet_id, source, content, bytes, pinned, meta) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (dest_puppet_id, "agent", content, _content_bytes(content), True, json.dumps(_meta)),
            )
            n += 1
    if commit:
        conn.commit()
    return n


def clear_memories(conn, puppet_id: str) -> int:
    """Borra TODA la memoria de un agente (botón 'limpiar' del panel). Devuelve cuántas."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM agent_memories WHERE puppet_id = %s", (puppet_id,))
        n = cur.rowcount
    conn.commit()
    return n


def memory_usage(conn, puppet_id: str) -> dict[str, int]:
    """{entries, bytes} usados por un agente — para mostrar el cap y para enforzarlo."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM agent_memories WHERE puppet_id = %s",
            (puppet_id,),
        )
        row = cur.fetchone()
    return {"entries": int(row[0] or 0), "bytes": int(row[1] or 0)}


def enforce_memory_caps(conn, puppet_id: str, *, max_entries: int,
                        max_bytes: int) -> int:
    """FRONTERA de memoria: recorta el agente para que quepa en el techo de su TIER.
    Preserva lo más valioso (entradas del USUARIO y las más nuevas); DESALOJA primero
    las 'agent' (destiladas) más viejas — 'destilado de las viejas'. Devuelve cuántas
    entradas desalojó. El techo lo resuelve el runtime (memory_caps_for_tier), la receta
    NO puede subirlo. Se llama en TODO write-path (destilado + panel)."""
    with conn.cursor() as cur:
        # orden de RETENCIÓN: user antes que agent, y dentro de cada uno lo más nuevo primero.
        cur.execute(
            "SELECT id, bytes FROM agent_memories WHERE puppet_id = %s "
            "ORDER BY (source = 'user') DESC, created_at DESC", (puppet_id,),
        )
        rows = cur.fetchall()
        # Semántica de CORTE (no greedy first-fit): en cuanto una entrada no entra (por nº o por
        # bytes), se desaloja ELLA y TODO lo que sigue. Como el orden es prioridad-estricta
        # (user>agent, nuevo>viejo), esto conserva el PREFIJO de mayor valor sin invertir
        # prioridad/recencia (no keepea una 'agent'/vieja chica salteando una 'user'/nueva grande).
        kept_n = 0
        kept_bytes = 0
        evict_ids: list = []
        cut = False
        for mem_id, b in rows:
            b = int(b or 0)
            if not cut and kept_n + 1 <= max_entries and kept_bytes + b <= max_bytes:
                kept_n += 1
                kept_bytes += b
            else:
                cut = True
                evict_ids.append(mem_id)
        if evict_ids:
            cur.execute("DELETE FROM agent_memories WHERE id = ANY(%s::uuid[])",
                        ([str(i) for i in evict_ids],))
    conn.commit()
    return len(evict_ids)


# ── Step 2 · B2 · Memoria COMPARTIDA (por composition_id = Cuarto, con AUTORÍA) ──
# Mismo idiom que A3, pero keyed por la COMPOSICIÓN (puppets.id del Cuarto top-level) en vez de
# por-agente, y cada entrada lleva author_agent_id/author_label (QUIÉN escribió). El acceso
# (quién LEE) lo decide la línea teal en el runtime (recipe.memory.members), no esta capa. La
# escritura es server-side (no tool-call) → sidestepa el gate A2, como A3. AISLAMIENTO por
# composition_id: dos Cuartos = dos memorias; el dueño se resuelve por puppets.owner_id.

def list_shared_memories(conn, composition_id: str, *, limit: Optional[int] = None,
                         pinned_only: bool = False) -> list[dict[str, Any]]:
    """Las notas compartidas de UN Cuarto, más-reciente-primero (last-write-wins por orden).
    Lo que se ve = lo que hay: el panel del cilindro muestra exactamente esta lista, con autor."""
    sql = ("SELECT id, composition_id, author_agent_id, author_label, source, content, bytes, "
           "pinned, uri, meta, created_at, updated_at FROM shared_memories "
           "WHERE composition_id = %s")
    args: list[Any] = [composition_id]
    if pinned_only:
        sql += " AND pinned = TRUE"
    sql += " ORDER BY created_at DESC"
    if limit is not None:
        sql += " LIMIT %s"
        args.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def add_shared_memory(conn, *, composition_id: str, content: str,
                      author_agent_id: Optional[str] = None,
                      author_label: Optional[str] = None, source: str = "agent",
                      pinned: bool = True, uri: Optional[str] = None,
                      meta: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Agrega UNA nota compartida al Cuarto, atribuida a su autor. Dos vías: el DESTILADO al
    cierre del run de un agente conectado (source='agent', author=agente) y el WRITE del panel
    (source='user', author='Vos'). Ninguna pasa por el gate: es op server-side sobre estado del
    dueño de la composición."""
    b = _content_bytes(content)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO shared_memories (composition_id, author_agent_id, author_label, "
            "source, content, bytes, pinned, uri, meta) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (composition_id, author_agent_id, author_label, source, content, b, pinned, uri,
             json.dumps(meta) if meta is not None else None),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def get_shared_memory(conn, memory_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, composition_id, author_agent_id, author_label, source, content, bytes, "
            "pinned, uri, meta, created_at, updated_at FROM shared_memories WHERE id = %s",
            (memory_id,),
        )
        return _row_to_dict(cur, cur.fetchone())


def shared_memory_owner(conn, memory_id: str) -> Optional[str]:
    """El user_id DUEÑO de una nota compartida (vía la composición/Cuarto). Para authz
    anti-IDOR de edición/borrado de UNA entrada. None si no existe."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.owner_id FROM shared_memories m JOIN puppets p ON p.id = m.composition_id "
            "WHERE m.id = %s", (memory_id,),
        )
        row = cur.fetchone()
    return str(row[0]) if row and row[0] is not None else None


def update_shared_memory(conn, memory_id: str, *, content: str) -> Optional[dict[str, Any]]:
    """Edita el texto de una nota compartida (recalcula bytes + updated_at)."""
    b = _content_bytes(content)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE shared_memories SET content = %s, bytes = %s, updated_at = now() "
            "WHERE id = %s RETURNING *",
            (content, b, memory_id),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def delete_shared_memory(conn, memory_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM shared_memories WHERE id = %s", (memory_id,))
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


def clear_shared_memories(conn, composition_id: str) -> int:
    """Borra TODA la memoria compartida de un Cuarto (botón 'limpiar'). Devuelve cuántas."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM shared_memories WHERE composition_id = %s", (composition_id,))
        n = cur.rowcount
    conn.commit()
    return n


def shared_memory_usage(conn, composition_id: str) -> dict[str, int]:
    """{entries, bytes} usados por un Cuarto — para mostrar el cap y para enforzarlo."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM shared_memories WHERE composition_id = %s",
            (composition_id,),
        )
        row = cur.fetchone()
    return {"entries": int(row[0] or 0), "bytes": int(row[1] or 0)}


def enforce_shared_memory_caps(conn, composition_id: str, *, max_entries: int,
                               max_bytes: int) -> int:
    """FRONTERA de la memoria compartida: recorta el Cuarto para que quepa en el techo de su
    TIER. Misma semántica de CORTE que A3: conserva el PREFIJO de mayor valor (entradas del
    USUARIO y las más nuevas primero); desaloja ELLA y todo lo que sigue en cuanto una no entra.
    Multi-autor: la política v1 es idéntica a A3 (user>agent, nuevo>viejo) — no hay cuota
    por-autor todavía. Devuelve cuántas desalojó. Se llama en TODO write-path."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, bytes FROM shared_memories WHERE composition_id = %s "
            "ORDER BY (source = 'user') DESC, created_at DESC", (composition_id,),
        )
        rows = cur.fetchall()
        kept_n = 0
        kept_bytes = 0
        evict_ids: list = []
        cut = False
        for mem_id, b in rows:
            b = int(b or 0)
            if not cut and kept_n + 1 <= max_entries and kept_bytes + b <= max_bytes:
                kept_n += 1
                kept_bytes += b
            else:
                cut = True
                evict_ids.append(mem_id)
        if evict_ids:
            cur.execute("DELETE FROM shared_memories WHERE id = ANY(%s::uuid[])",
                        ([str(i) for i in evict_ids],))
    conn.commit()
    return len(evict_ids)


# ── ORDEN 4 · COMPOSICIÓN · SEED del BUS desde piezas ELEGIDAS de agentes miembro ──────────────
# "¿Qué trae cada uno a esta mesa?": el usuario elige memorias de sus agentes y las VUELCA al bus de
# una composición nueva (semi-memoria compartida construida a mano). Es PRÉSTAMO con procedencia, NO
# transfusión: el origen sólo se LEE, jamás se toca. Reglas duras enforced acá:
#   • sólo agent_memories del DUEÑO (anti-IDOR: memory_owner == owner_id). Una id de account_memories
#     NO existe en agent_memories (get_memory consulta SÓLO esa tabla) → 'not_found' → la memoria de
#     CUENTA jamás se puede sembrar a un bus (que otros agentes —incluso de otro Cuarto compartido—
#     leerían). Invariante #4 estructural, no por chequeo frágil.
#   • lo CONFIDENCIAL (meta.confidential) NO es mezclable → 'confidential'.
#   • cada nota sembrada lleva procedencia: origin_agent_id/origin_memory_id/kind/provenance +
#     author_label = nombre del agente origen; source='user' (acto explícito del usuario).

def seed_shared_bus(conn, *, composition_id: str, owner_id: str, memory_ids: list,
                    max_entries: Optional[int] = None,
                    max_bytes: Optional[int] = None) -> dict[str, Any]:
    """Siembra en el bus (shared_memories) de `composition_id` las memorias de agente `memory_ids`,
    validando UUID + dueño + confidencialidad + existencia. Cada id se clasifica y NUNCA tira 500:

      {seeded:[ids B2 vivos], skipped:[{id,reason}], evicted_seeded:[ids sembrados que el cap desalojó],
       evicted_total:N}

    reasons de skip: 'not_found' (no existe en agent_memories — INCL. ids de cuenta: otra tabla),
    'not_owned' (anti-IDOR), 'confidential' (no mezclable), 'already_seeded' (idempotencia por
    procedencia), 'malformed' (no-UUID → nunca toca la DB), 'error' (fallo DB por-id → rollback +
    sigue). El origen NO se modifica. Cada pieza se trunca al techo de bytes del bus (como el panel).
    Tras insertar, enforce_shared_memory_caps puede desalojar; RECONCILIAMOS la respuesta con lo que
    sobrevive (seeded = vivos) y reportamos evicted (no mentir: una pieza sembrada que el cap borró
    NO va en 'seeded'; se avisa evicted_total = cuántas del bus, incl. viejas, desalojó el cap)."""
    seeded: list = []          # (b2_id, origin_mid)
    skipped: list = []
    # procedencias ya presentes en el bus (para no duplicar en re-seed)
    _already: set = set()
    for _row in list_shared_memories(conn, composition_id):
        _om = ((_row.get("meta") or {}).get("origin_memory_id"))
        if _om:
            _already.add(str(_om))
    for raw in (memory_ids or []):
        mid = str(raw or "").strip()
        if not mid:
            continue
        if not _is_uuid(mid):
            skipped.append({"id": mid, "reason": "malformed"})   # no-UUID → jamás toca la DB (no 500)
            continue
        if mid in _already:
            skipped.append({"id": mid, "reason": "already_seeded"})
            continue
        try:
            m = get_memory(conn, mid)                       # SÓLO agent_memories
            if not m:
                skipped.append({"id": mid, "reason": "not_found"})   # incl. ids de account_memories
                continue
            if str(memory_owner(conn, mid) or "") != str(owner_id):
                skipped.append({"id": mid, "reason": "not_owned"})   # anti-IDOR: no es tu agente
                continue
            meta = m.get("meta") or {}
            if meta.get("confidential"):
                skipped.append({"id": mid, "reason": "confidential"})   # no mezclable
                continue
            origin_pid = str(m.get("puppet_id") or "")
            try:
                _op = get_puppet(conn, origin_pid)
                author_label = (_op.get("name") if _op else None) or "agente"
            except Exception:
                author_label = "agente"
            content = m.get("content") or ""
            if max_bytes is not None:
                content = _truncate_bytes(content, int(max_bytes))   # una pieza no excede el techo
            row = add_shared_memory(
                conn, composition_id=composition_id, content=content,
                author_agent_id=origin_pid, author_label=author_label, source="user", pinned=True,
                meta={"seeded": True, "origin_memory_id": mid, "origin_agent_id": origin_pid,
                      "kind": meta.get("kind"), "provenance": meta.get("provenance")})
            if row:
                seeded.append((str(row.get("id")), mid))
                _already.add(mid)
        except Exception:
            # fallo de DB tocando ESTE id (conn caída, serialization, etc.): rollback para no dejar la
            # txn abortada (crashearía el resto) + clasificá honesto y seguí con los demás ids.
            try:
                conn.rollback()
            except Exception:
                pass
            skipped.append({"id": mid, "reason": "error"})
            continue

    evicted_total = 0
    seeded_ids = [sid for sid, _ in seeded]
    evicted_seeded: list = []
    if seeded and max_entries is not None and max_bytes is not None:
        try:
            evicted_total = enforce_shared_memory_caps(
                conn, composition_id, max_entries=int(max_entries), max_bytes=int(max_bytes))
            if evicted_total:
                # reconciliá: qué de lo recién sembrado SOBREVIVIÓ al cap (no mentir en 'seeded').
                survivors = {str(r.get("id")) for r in list_shared_memories(conn, composition_id)}
                evicted_seeded = [sid for sid in seeded_ids if sid not in survivors]
                seeded_ids = [sid for sid in seeded_ids if sid in survivors]
        except Exception:
            pass
    return {"seeded": seeded_ids, "skipped": skipped,
            "evicted_seeded": evicted_seeded, "evicted_total": int(evicted_total)}


# ── ORDEN 2 · Sistema 2 · MEMORIA DE CUENTA (por owner_id = users.id, cruza agentes y Cuartos) ──
# Mismo idiom estricto que A3/B2 (cursor por tupla + _row_to_dict + conn.commit() en las mutantes).
# Keyed por owner_id = users(id) = la PERSONA: TODO agente del dueño la lee al armar framing (Sistema
# 2 del MD). El dueño ES el usuario → authz anti-IDOR directa por _authorize(user_id, ...) (sin la
# indirección puppet_owner de A3/B2). AISLAMIENTO cross-cuenta: dos users = dos memorias; la lectura
# filtra estrictamente por owner_id. La ESCRITURA es server-side, pero en ORDEN 2 el run NO auto-
# escribe cuenta (el ascenso proyecto→cuenta es propuesta-con-OK = gate orden 5): esta CRUD la usan
# el gate (orden 5), el panel (orden 6) y la captura explícita del usuario. CAPS por TIER las impone
# el runtime (recipe_enforcer.TIER_ACCOUNT_MEMORY_CAPS), no la receta.

def list_account_memories(conn, owner_id: str, *, limit: Optional[int] = None,
                          pinned_only: bool = False) -> list[dict[str, Any]]:
    """Los hechos de cuenta de UN usuario, más-reciente-primero. Lo que se ve = lo que hay:
    el panel de cuenta muestra exactamente esta lista, y el framing lee de acá (pinned_only)."""
    sql = ("SELECT id, owner_id, source, content, bytes, pinned, uri, meta, "
           "created_at, updated_at FROM account_memories WHERE owner_id = %s")
    args: list[Any] = [owner_id]
    if pinned_only:
        sql += " AND pinned = TRUE"
    sql += " ORDER BY created_at DESC"
    if limit is not None:
        sql += " LIMIT %s"
        args.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def add_account_memory(conn, *, owner_id: str, content: str, source: str = "user",
                       pinned: bool = True, uri: Optional[str] = None,
                       meta: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Agrega UN hecho de cuenta a un usuario. `bytes` se calcula del content (para los caps).
    source DEFAULT 'user': el ascenso a cuenta es acto del usuario (propuesta-con-OK, orden 5) —
    lo destilado por un agente (source='agent') sólo llega acá VÍA ese gate, nunca solo. No pasa
    por el gate de tools (op server-side): la autoridad la da el gate de propuesta, no esta capa."""
    b = _content_bytes(content)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO account_memories (owner_id, source, content, bytes, pinned, uri, meta) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (owner_id, source, content, b, pinned, uri,
             json.dumps(meta) if meta is not None else None),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def get_account_memory(conn, memory_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, owner_id, source, content, bytes, pinned, uri, meta, "
            "created_at, updated_at FROM account_memories WHERE id = %s", (memory_id,),
        )
        return _row_to_dict(cur, cur.fetchone())


def account_memory_owner(conn, memory_id: str) -> Optional[str]:
    """El user_id DUEÑO de un hecho de cuenta. Para authz anti-IDOR de edición/borrado de UNA
    entrada. Directo: owner_id ES el user (sin join). None si la memoria no existe."""
    with conn.cursor() as cur:
        cur.execute("SELECT owner_id FROM account_memories WHERE id = %s", (memory_id,))
        row = cur.fetchone()
    return str(row[0]) if row and row[0] is not None else None


def update_account_memory(conn, memory_id: str, *, content: str) -> Optional[dict[str, Any]]:
    """Edita el texto de un hecho de cuenta (recalcula bytes + updated_at)."""
    b = _content_bytes(content)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE account_memories SET content = %s, bytes = %s, updated_at = now() "
            "WHERE id = %s RETURNING *",
            (content, b, memory_id),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def delete_account_memory(conn, memory_id: str, *, owner_id: Optional[str] = None) -> bool:
    """Borra un hecho de cuenta. Con `owner_id`: borrado ATÓMICO scopeado por dueño (anti-IDOR sin
    TOCTOU) — la entrada de OTRO usuario == inexistente (rowcount 0 → False), sin oráculo de existencia.
    UUID guard: un id malformado → False (jamás DataError/500). Sin `owner_id`: borrado directo por id
    (uso interno/tests). El panel (orden 6) SIEMPRE pasa owner_id."""
    if owner_id is not None and not _is_uuid(memory_id):
        return False
    sql = "DELETE FROM account_memories WHERE id = %s"
    args: list[Any] = [memory_id]
    if owner_id is not None:
        sql += " AND owner_id = %s"
        args.append(owner_id)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


def clear_account_memories(conn, owner_id: str) -> int:
    """Borra TODA la memoria de cuenta de un usuario (botón 'limpiar' del panel). Devuelve cuántas."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM account_memories WHERE owner_id = %s", (owner_id,))
        n = cur.rowcount
    conn.commit()
    return n


def account_memory_usage(conn, owner_id: str) -> dict[str, int]:
    """{entries, bytes} usados por un usuario — para mostrar el cap y para enforzarlo."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM account_memories WHERE owner_id = %s",
            (owner_id,),
        )
        row = cur.fetchone()
    return {"entries": int(row[0] or 0), "bytes": int(row[1] or 0)}


def enforce_account_memory_caps(conn, owner_id: str, *, max_entries: int,
                                max_bytes: int) -> int:
    """FRONTERA de la memoria de cuenta: recorta para que quepa en el techo del TIER. Semántica de
    CORTE (como A3), conservando el PREFIJO de mayor valor. Orden de RETENCIÓN (review orden-5):
      1. pinned DESC — un hecho ACTIVO (confirmado o escrito por el usuario, pinned=TRUE) NUNCA lo
         desaloja una PROPUESTA pendiente (source='agent', pinned=FALSE): las pendientes son lo más
         expendable y van al final (se cortan primero).
      2. (source='user') DESC — entre los activos, lo que el usuario ESCRIBIÓ a mano antes que lo
         destilado-y-confirmado (source='agent', pinned=TRUE).
      3. created_at DESC — dentro de cada grupo, lo más nuevo primero.
    Devuelve cuántas desalojó. Pensado para el write-path de cuenta (el cableado de enforce en el
    confirm/panel es orden 6)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, bytes FROM account_memories WHERE owner_id = %s "
            "ORDER BY pinned DESC, (source = 'user') DESC, created_at DESC", (owner_id,),
        )
        rows = cur.fetchall()
        kept_n = 0
        kept_bytes = 0
        evict_ids: list = []
        cut = False
        for mem_id, b in rows:
            b = int(b or 0)
            if not cut and kept_n + 1 <= max_entries and kept_bytes + b <= max_bytes:
                kept_n += 1
                kept_bytes += b
            else:
                cut = True
                evict_ids.append(mem_id)
        if evict_ids:
            cur.execute("DELETE FROM account_memories WHERE id = ANY(%s::uuid[])",
                        ([str(i) for i in evict_ids],))
    conn.commit()
    return len(evict_ids)


# ── ORDEN 5 · GATE de PROPUESTA de cuenta · una propuesta nace INERTE (pinned=FALSE) ────────────
# El ascenso de un hecho a cuenta es propuesta-con-OK: el run NO auto-escribe. Una propuesta =
# source='agent' + pinned=FALSE → la lectura del framing (list_account_memories(pinned_only=True))
# NO la ve hasta que el humano la CONFIRME (pinned=TRUE). Reusa el mismo idiom que el gate de
# instrucciones (add_proposal): cap anti-spam por owner con advisory-lock TRANSACCIONAL (TOCTOU-safe
# entre runs concurrentes). El filtro auth-never-persist vive en account_proposal.py (afuera de la DB).
MAX_PENDING_ACCOUNT_PROPOSALS = 3


def add_account_proposal(conn, *, owner_id: str, content: str, run_id: Optional[str] = None,
                         provenance: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Propuesta INERTE de hecho de cuenta (source='agent', pinned=FALSE). Cap anti-spam: con
    MAX_PENDING_ACCOUNT_PROPOSALS pendientes, la nueva se descarta (None). El COUNT+INSERT corren
    bajo pg_advisory_xact_lock por owner (se suelta al commit) → dos runs del mismo usuario se
    SERIALIZAN y el cap no se supera por carrera. Devuelve la fila o None."""
    scope_key = f"acct_prop:{owner_id}"
    b = _content_bytes(content)
    count_sql = ("SELECT COUNT(*) FROM account_memories "
                 "WHERE owner_id = %s AND source = 'agent' AND NOT pinned")
    insert_sql = (
        "INSERT INTO account_memories (owner_id, source, content, bytes, pinned, meta) "
        "VALUES (%s,'agent',%s,%s,FALSE,%s) RETURNING *")
    insert_params = (owner_id, content, b,
                     json.dumps({"run_id": run_id, "proposed": True, "provenance": provenance}))

    # [Casa 2 · 2.4] SQLite no tiene advisory locks; BEGIN IMMEDIATE toma el write lock
    # antes del COUNT → misma serialización anti-TOCTOU que pg_advisory_xact_lock
    # (ver instructions_repo.add_proposal, mismo patrón).
    if _dbmod().es_cliente():
        conn.raw.execute("BEGIN IMMEDIATE")
        try:
            with conn.cursor() as cur:
                cur.execute(count_sql, (owner_id,))
                if int(cur.fetchone()[0]) >= MAX_PENDING_ACCOUNT_PROPOSALS:
                    conn.commit()
                    return None
                cur.execute(insert_sql, insert_params)
                row = _row_to_dict(cur, cur.fetchone())
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return row

    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", (scope_key,))
        cur.execute(count_sql, (owner_id,))
        if int(cur.fetchone()[0]) >= MAX_PENDING_ACCOUNT_PROPOSALS:
            conn.commit()              # cierra la tx (suelta el lock); no hubo escrituras
            return None
        cur.execute(insert_sql, insert_params)
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def list_account_proposals(conn, owner_id: str) -> list[dict[str, Any]]:
    """Las propuestas PENDIENTES (source='agent', NOT pinned) del usuario, más-nueva-primero.
    Es lo que el panel muestra para confirmar/rechazar; NO entran al framing hasta confirmarse."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, owner_id, source, content, bytes, pinned, uri, meta, created_at, updated_at "
            "FROM account_memories WHERE owner_id = %s AND source = 'agent' AND NOT pinned "
            "ORDER BY created_at DESC", (owner_id,),
        )
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def confirm_account_proposal(conn, memory_id: str, owner_id: str) -> Optional[dict[str, Any]]:
    """EL GATE: el humano CONFIRMA → pinned=TRUE + meta.approved (queda la proveniencia source=agent).
    Sólo una propuesta PENDIENTE y PROPIA (anti-IDOR por owner_id + source='agent' + NOT pinned) — la
    de otro usuario o ya confirmada no matchea. UUID guard (no-UUID → None, jamás DataError). Devuelve
    la fila confirmada o None."""
    if not _is_uuid(memory_id):
        return None
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE account_memories SET pinned = TRUE, updated_at = now(), "
            "meta = COALESCE(meta, '{}'::jsonb) || '{\"approved\": true}'::jsonb "
            "WHERE id = %s AND owner_id = %s AND source = 'agent' AND NOT pinned RETURNING *",
            (memory_id, owner_id),
        )
        row = cur.fetchone()
        result = _row_to_dict(cur, row) if row else None
    conn.commit()
    return result


def reject_account_proposal(conn, memory_id: str, owner_id: str) -> bool:
    """Rechaza (borra) una propuesta PENDIENTE y PROPIA (anti-IDOR + source='agent' + NOT pinned).
    NO borra un hecho ya CONFIRMADO (pinned) — eso es podar, del panel (orden 6). UUID guard."""
    if not _is_uuid(memory_id):
        return False
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM account_memories WHERE id = %s AND owner_id = %s "
            "AND source = 'agent' AND NOT pinned", (memory_id, owner_id),
        )
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


# ── Step 2 · C1 · CONOCIMIENTO del agente (RAG · átomo Conocimiento, por composition_id) ──
# Mismo idiom estricto que A3/B2 (cursor por tupla + _row_to_dict + conn.commit() explícito en
# las mutantes, ninguno en las lecturas). Keyed por la COMPOSICIÓN (puppets.id del Cuarto
# top-level): dos Cuartos = dos corpus AISLADOS; el dueño se resuelve por puppets.owner_id
# (authz anti-IDOR). La ESCRITURA es server-side (ingestar/indexar NO pasa por tool-call) →
# sidestepa el gate A2, como A3/B2. El ÍNDICE es $0: el embedding se guarda como array de
# floats en JSONB (columna nullable: un chunk puede existir pre-embed o en error_no_key) y el
# ranking es coseno en Python puro sobre los chunks de la composición — NO pgvector, NO
# sqlite-vec. composition_id va DENORMALIZADO en knowledge_chunks para escanear+aislar sin JOIN;
# los writes SIEMPRE setean composition_id Y doc_id consistentes. embed_provider/embed_model/
# embed_dim se persisten por doc como guardia de drift (mismatch de dimensión query↔chunk).

def add_knowledge_doc(conn, *, composition_id: str, doc_name: str,
                      mime: Optional[str] = None, bytes: int = 0,
                      sha256: Optional[str] = None,
                      meta: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Registra UN documento del corpus de una composición en estado 'pending'. Devuelve el
    doc_id (str) para luego trocearlo/indexarlo. Op server-side sobre el estado del dueño del
    Cuarto (no pasa por el gate). El contenido/embedding NO viven acá: sólo la metadata del doc."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO knowledge_docs (composition_id, doc_name, mime, bytes, sha256, "
            "status, meta) VALUES (%s,%s,%s,%s,%s,'pending',%s) RETURNING id",
            (composition_id, doc_name, mime, int(bytes or 0), sha256,
             json.dumps(meta if meta is not None else {})),
        )
        row = cur.fetchone()
    conn.commit()
    return str(row[0]) if row and row[0] is not None else None


def set_doc_status(conn, doc_id: str, status: str, *, error: Optional[str] = None,
                   embed_provider: Optional[str] = None, embed_model: Optional[str] = None,
                   embed_dim: Optional[int] = None,
                   n_chunks: Optional[int] = None) -> Optional[dict[str, Any]]:
    """Transiciona el status honesto de un doc (pending|indexed|error_no_key|error) y persiste
    la guardia de drift (embed_provider/embed_model/embed_dim) + n_chunks al indexar. `error` se
    setea directo (None al pasar a 'indexed' lo limpia); los campos de embedding/n_chunks usan
    COALESCE → conservan lo existente si el caller no los pasa (p.ej. en el path de error)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE knowledge_docs SET status = %s, error = %s, "
            "embed_provider = COALESCE(%s, embed_provider), "
            "embed_model = COALESCE(%s, embed_model), "
            "embed_dim = COALESCE(%s, embed_dim), "
            "n_chunks = COALESCE(%s, n_chunks) "
            "WHERE id = %s RETURNING *",
            (status, error, embed_provider, embed_model,
             embed_dim, n_chunks, doc_id),
        )
        row = _row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


# Nombre que consume la interfaz KnowledgeStore (C1 · knowledge_store.HostedStore.set_status):
# la transición de status del knowledge_doc YA la implementa set_doc_status con el idiom del DAO
# (cursor por tupla + conn.commit()); exponemos el alias explícito para no duplicar el SQL.
set_knowledge_doc_status = set_doc_status


def add_knowledge_chunk(conn, *, composition_id: str, doc_id: str, chunk_ix: int,
                        content: str, bytes: int = 0,
                        embedding: Optional[list] = None,
                        meta: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Agrega UN chunk indexado de un doc. embedding = array de floats (se guarda como JSONB;
    columna nullable → un chunk puede quedar sin embedding en error_no_key). Setea SIEMPRE
    composition_id Y doc_id consistentes (composition_id denormalizado para el escaneo aislado)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO knowledge_chunks (composition_id, doc_id, chunk_ix, content, "
            "bytes, embedding, meta) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (composition_id, doc_id, int(chunk_ix), content, int(bytes or 0),
             json.dumps(embedding) if embedding is not None else None,
             json.dumps(meta if meta is not None else {})),
        )
        row = cur.fetchone()
    conn.commit()
    return str(row[0]) if row and row[0] is not None else None


def list_knowledge_docs(conn, composition_id: str) -> list[dict[str, Any]]:
    """Los documentos del corpus de un Cuarto, más-reciente-primero — DATOS DEL PANEL. NO trae
    embeddings NI el cuerpo del contenido (viven en los chunks): sólo lo que la UI muestra
    (nombre, tamaño, status honesto, error, n_chunks)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, doc_name, mime, bytes, status, error, n_chunks, created_at "
            "FROM knowledge_docs WHERE composition_id = %s ORDER BY created_at DESC",
            (composition_id,),
        )
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def get_knowledge_doc(conn, doc_id: str) -> Optional[dict[str, Any]]:
    """Un doc completo por id — incluye composition_id para el cross-check anti-IDOR del router
    (doc.composition_id != cid → 404)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, composition_id, doc_name, mime, bytes, sha256, status, error, "
            "embed_provider, embed_model, embed_dim, n_chunks, meta, created_at "
            "FROM knowledge_docs WHERE id = %s", (doc_id,),
        )
        return _row_to_dict(cur, cur.fetchone())


def delete_knowledge_doc(conn, doc_id: str) -> bool:
    """Borra un doc del corpus; el FK ON DELETE CASCADE arrastra TODOS sus chunks."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge_docs WHERE id = %s", (doc_id,))
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


def knowledge_doc_owner(conn, doc_id: str) -> Optional[str]:
    """El user_id DUEÑO de un doc (vía la composición/Cuarto). Para authz anti-IDOR de
    borrado/lectura de UN doc. None si no existe. (clon de shared_memory_owner)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.owner_id FROM knowledge_docs d JOIN puppets p ON p.id = d.composition_id "
            "WHERE d.id = %s", (doc_id,),
        )
        row = cur.fetchone()
    return str(row[0]) if row and row[0] is not None else None


def list_chunks_for_retrieval(conn, composition_id: str) -> list[dict[str, Any]]:
    """Carga los chunks INDEXADOS (embedding no nulo) de UNA composición para el ranking coseno
    en Python puro. Scope ESTRICTO por composition_id (el índice idx_knowledge_chunks_comp
    soporta el escaneo) — AISLAMIENTO: otra composición nunca ve este corpus. Trae doc_name
    (JOIN) para el tag de procedencia [doc#chunk] que se inyecta como APUNTE al runtime."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.doc_id, d.doc_name, c.chunk_ix, c.content, c.embedding, c.meta "
            "FROM knowledge_chunks c JOIN knowledge_docs d ON d.id = c.doc_id "
            "WHERE c.composition_id = %s AND c.embedding IS NOT NULL "
            "ORDER BY c.doc_id, c.chunk_ix", (composition_id,),
        )
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def knowledge_usage(conn, composition_id: str) -> dict[str, int]:
    """{doc_count, total_bytes} usados por el corpus de un Cuarto — para mostrar el cap (modo
    hosted) y para enforzarlo. En self_hosted es informativo (no hay cap)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM knowledge_docs WHERE composition_id = %s",
            (composition_id,),
        )
        row = cur.fetchone()
    return {"doc_count": int(row[0] or 0), "total_bytes": int(row[1] or 0)}


def enforce_knowledge_caps(conn, composition_id: str, max_docs: int, max_bytes: int) -> int:
    """FRONTERA del corpus (SÓLO modo hosted: self_hosted pasa None → el caller no llama esto).
    Misma semántica de CORTE por PREFIJO que A3/B2: conserva el prefijo de mayor valor (docs más
    nuevos primero) y desaloja ÉL y todo lo que sigue en cuanto uno no entra en el techo del
    TIER. Borrar un doc arrastra sus chunks (CASCADE). Devuelve cuántos docs desalojó."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, bytes FROM knowledge_docs WHERE composition_id = %s "
            "ORDER BY created_at DESC", (composition_id,),
        )
        rows = cur.fetchall()
        kept_n = 0
        kept_bytes = 0
        evict_ids: list = []
        cut = False
        for doc_id, b in rows:
            b = int(b or 0)
            if not cut and kept_n + 1 <= max_docs and kept_bytes + b <= max_bytes:
                kept_n += 1
                kept_bytes += b
            else:
                cut = True
                evict_ids.append(doc_id)
        if evict_ids:
            cur.execute("DELETE FROM knowledge_docs WHERE id = ANY(%s::uuid[])",
                        ([str(i) for i in evict_ids],))
    conn.commit()
    return len(evict_ids)
