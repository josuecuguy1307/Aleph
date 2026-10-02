"""
db.py — capa de conexión a Postgres + cifrado BYOK at-rest para Puppet AI.

Conecta al Postgres EXISTENTE de persona usuaria (postgresql@17 :5432), base lógica
`puppet_ai`. NO inventa un servidor nuevo.

Conexión:
  - host/port/user/db se leen de env (PG_HOST, PG_PORT, PG_USER, PG_DB) con
    defaults locales (127.0.0.1:5432, user=$USER, db=puppet_ai).
  - password de PG_PASSWORD si está; si no, trust local (así está el Postgres
    de persona usuaria en localhost).

Cifrado BYOK (keys.ciphertext):
  - Fernet (AES-128-CBC + HMAC-SHA256) de `cryptography`.
  - La clave de cifrado vive FUERA de la DB: env PUPPET_DB_ENC_KEY, o el
    archivo platform/db/secrets/enc.key (auto-generado, gitignored).
  - encrypt_secret() devuelve bytes (token Fernet) para guardar en BYTEA.
  - decrypt_secret() lo revierte. La DB nunca ve el plaintext.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from cryptography.fernet import Fernet

_DB_DIR = Path(__file__).resolve().parent
_SECRETS_DIR = _DB_DIR / "secrets"
_KEYFILE = _SECRETS_DIR / "enc.key"

DEFAULT_DB = "puppet_ai"


# ── EL SELECTOR DE BACKEND [Casa 2 · Fase 2 · 2.2b] ──────────────────────────
# `get_conn()` es EL EMBUDO: los 14 routers que la reciben inyectada
# (`main.py:_phase1_get_conn`) y los ~20 que llaman `repo.get_conn()` directo
# terminan todos acá. Por eso el selector vive en este archivo y en ningún otro —
# mismo criterio que la frontera del 2.0: una decisión, un lugar.
#
#     ALEPH_ROLE=control  →  Postgres (psycopg2), exactamente como antes
#     ALEPH_ROLE=client   →  el SQLite del usuario (platform/db/sqlite_db.py)
#
# ⚠️ El default de `role.current()` es `client` (fail-closed, ver platform/role.py).
# Para el plano de control eso NO es un detalle: si `ALEPH_ROLE=control` no llega al
# contenedor, este selector manda producción a un SQLite vacío y los pagos caen. Es
# el mismo riesgo que el 2.0 ya documentó para el webhook, ahora con la base atrás.
# `render.yaml` lo declara y `describe()` lo loguea en la primera línea del arranque.


def _rol() -> str:
    """El rol de este proceso, sin asumir que `platform/` esté en el sys.path.

    `db.py` se carga de tres formas distintas en el árbol (import normal, `from db
    import ...` con `platform/db` en el path, y `spec_from_file_location` desde
    `repo.py`), así que no se puede confiar en que un import de paquete resuelva.
    """
    try:
        import role                                   # platform/ ya en el path
    except ImportError:
        plat = str(_DB_DIR.parent)
        if plat not in sys.path:
            sys.path.insert(0, plat)
        try:
            import role
        except ImportError:
            # ⚠️ Acá el fallback es "control", al REVÉS del default de `role.current()`,
            # y es deliberado: son dos ejes fail-closed distintos.
            #   role.py    protege la SUPERFICIE: ante la duda no expongas pagos → client.
            #   este       protege LOS DATOS:     ante la duda no cambies de base → Postgres.
            # Si `role.py` no se puede importar, un cliente que intente Postgres falla al
            # conectar (ruidoso, sin pérdida); un plano de control que caiga a SQLite
            # escribiría los cobros en un archivo local (callado, y son plata). Entre las
            # dos, se rompe ruidoso. En la práctica este camino sólo lo tocan los CLI
            # (migrate/backup/init_db), que son herramientas del plano de control:
            # `main.py:259` importa `role` al arrancar, así que el server ya habría muerto.
            return "control"
    return role.current()


def es_cliente() -> bool:
    return _rol() == "client"


def _sqlite():
    """El módulo `sqlite_db`, cargado perezoso y sin asumir el sys.path.

    Perezoso a propósito: el plano de control nunca lo importa, y así el cliente
    empaquetado tampoco arrastra psycopg2 por este camino.
    """
    try:
        import sqlite_db
    except ImportError:
        if str(_DB_DIR) not in sys.path:
            sys.path.insert(0, str(_DB_DIR))
        import sqlite_db
    return sqlite_db


# ── conexión ────────────────────────────────────────────────────────────────
def conn_params(dbname: str | None = None) -> dict:
    """Parámetros de conexión al Postgres (env con defaults locales).

    [Step 5 · P11] Acepta TAMBIÉN una URL entera vía `DATABASE_URL` (o `SUPABASE_DB_URL`),
    que es como las entrega cualquier PaaS y como la da Supabase. Sin esto, un deploy
    tenía que cargar cinco variables sueltas en un panel web: cinco oportunidades de
    escribir mal una, y el síntoma sería "connection refused a 127.0.0.1" — que parece
    un problema de red y es un typo.

    Precedencia: la URL gana si está. Las PG_* siguen funcionando igual (es el camino
    de dev y no se toca).
    """
    url = (os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or "").strip()
    if url:
        from urllib.parse import unquote, urlparse
        u = urlparse(url)
        # `dbname` explícito (lo usa migrate.py) gana sobre el de la URL: el caller sabe
        # a qué base quiere ir.
        base = dbname or (u.path.lstrip("/") or DEFAULT_DB)
        params = {
            "host": u.hostname,
            "port": u.port or 5432,
            "user": unquote(u.username or "postgres"),
            "dbname": base,
        }
        if u.password:
            params["password"] = unquote(u.password)
        # Supabase (y casi todo Postgres gestionado) exige TLS. Sin esto la conexión
        # es rechazada con un error que no menciona TLS por ningún lado.
        params["sslmode"] = os.environ.get("PGSSLMODE", "require")
        return params

    params = {
        "host": os.environ.get("PG_HOST", "127.0.0.1"),
        "port": int(os.environ.get("PG_PORT", "5432")),
        "user": os.environ.get("PG_USER", os.environ.get("USER", "postgres")),
        "dbname": dbname or os.environ.get("PG_DB", DEFAULT_DB),
    }
    pw = os.environ.get("PG_PASSWORD")
    if pw:
        params["password"] = pw
    return params


def get_conn(dbname: str | None = None):
    """Una conexión a la base de ESTE rol. Postgres en control, SQLite en el cliente.

    El caller no se entera: la conexión del cliente responde a la misma superficie
    (`cursor()`, `execute(sql, params)`, `commit()`, `rowcount`…) y traduce el SQL de
    Postgres al vuelo. Ver `platform/db/sqlite_db.py` y `platform/db/dialect.py`.

    `dbname` sólo tiene sentido en Postgres (el cliente tiene UN archivo). Se ignora en
    client salvo que sea una ruta explícita, que es como los tests apuntan a un .db
    temporal.
    """
    if es_cliente():
        return _sqlite().conectar(dbname if dbname and dbname != DEFAULT_DB else None)
    return psycopg2.connect(**conn_params(dbname))


def asegurar_schema_cliente():
    """Bootstrap idempotente+versionado del schema SQLite del CLIENTE; no-op (None) en
    control (Postgres migra con `migrate.py`, herramienta del plano de control).

    Lo llama el boot del cliente (`app/infra/db_boot.py`): GAP-DEV-DESKTOP §2.1 — la
    .app corría con una DB de CERO tablas porque a `crear_schema` no lo llamaba nadie.
    Vive acá porque este archivo es EL selector por rol (mismo criterio que get_conn).
    Devuelve el resumen {"path","version","tablas"} de `sqlite_db.asegurar_schema`.
    """
    if not es_cliente():
        return None
    return _sqlite().asegurar_schema()


# ── cifrado BYOK ──────────────────────────────────────────────────────────────
def _keyfile() -> Path:
    """Dónde vive la enc.key auto-generada. [Casa 2 · Fase 3 · B3]

    CLIENTE → dir de datos del usuario (fuera del árbol de código, que bajo bundle
    es read-only). CONTROL → el histórico platform/db/secrets/enc.key. Fail-safe al
    histórico si aleph_paths no resuelve, sin asumir que platform/ esté en el path.
    """
    try:
        import aleph_paths
    except ImportError:
        plat = str(_DB_DIR.parent)  # platform/
        if plat not in sys.path:
            sys.path.insert(0, plat)
        try:
            import aleph_paths
        except Exception:
            return _KEYFILE
    try:
        return aleph_paths.enc_key_path()
    except Exception:
        return _KEYFILE


def _load_or_create_key() -> bytes:
    """Carga la clave Fernet de env o de keyfile; la crea si no existe."""
    env_key = os.environ.get("PUPPET_DB_ENC_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key
    keyfile = _keyfile()
    if keyfile.exists():
        return keyfile.read_bytes().strip()
    # Auto-generar y persistir (modo local/cliente). En prod: inyectar PUPPET_DB_ENC_KEY.
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    keyfile.write_bytes(key)
    os.chmod(keyfile, 0o600)
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def encrypt_secret(plaintext: str) -> bytes:
    """Cifra un secreto BYOK. Devuelve el token Fernet (bytes) para BYTEA."""
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(token: bytes, ttl: Optional[int] = None) -> str:
    """Revierte encrypt_secret; ``ttl`` limita edad cuando el caller lo exige."""
    if isinstance(token, memoryview):
        token = token.tobytes()
    return _fernet().decrypt(bytes(token), ttl=ttl).decode("utf-8")
