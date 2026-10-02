"""
credential_broker.py — EL BROKER DE CREDENCIALES POR END-USER (Fase 4 · B4, Tier A).

PROBLEMA QUE RESUELVE (held ≠ wired):
  El OAuth de claude.ai es de la cuenta del operador. El motor de PRODUCTO necesita
  la PROPIA credencial de CADA end-user (Gmail/Calendar/Drive/M365/Slack/Exa/...): la
  credencial que el usuario guardó vía `POST /v1/keys`, cifrada Fernet at-rest en la
  tabla `keys` (Fase 0). Tier A = conectores que requieren credencial POR USUARIO.

  El assembler ya acepta un `byok_resolver: byok_ref -> cleartext` y arma el child_env
  de los MCP servers POR referencia (recipe_assembler._resolve_keys). Lo que faltaba era
  el PUENTE: un resolver LIGADO al `user_id` del run que:
    - tome el byok_ref de la receta (keys.<provider>.byok_ref),
    - busque la fila cifrada de ESE usuario (repo.get_key descifra solo en memoria),
    - devuelva el cleartext SOLO al child_env del belt — nunca a logs/run-record/HTTP.

CONTRATO DEL byok_ref (Tier A):
  Forma canónica:  "keys.<provider>.byok_ref" == "user:<user_id>/<provider>"  o, más
  simple, el resolver se CONSTRUYE ya ligado a un user_id (make_user_resolver) y el
  byok_ref solo necesita nombrar el provider. Soportamos AMBAS:
    1) ref = "<provider>"                    -> usa el user_id con el que se hizo el broker
    2) ref = "user:<user_id>/<provider>"     -> ref auto-contenido (aislamiento explícito)
  Si un ref nombra OTRO user_id distinto del dueño del run, el broker lo RECHAZA
  (aislamiento por usuario: un run de A jamás resuelve una credencial de B).

SEGURIDAD (lente de cierre):
  - El cleartext vive solo en memoria, el tiempo del run. Nunca se persiste de vuelta.
  - El broker NUNCA loguea el valor (ni truncado). Si falla descifrar / no hay key,
    devuelve "" (el server del belt entonces no arranca / degrada — señal BYOK aparte).
  - get_key abre/cierra su propia conexión por defecto (no comparte la del run, que
    podría estar en una transacción a medio camino).

Stdlib + repo (que ya sabe descifrar Fernet). NO reinventa cifrado ni DB.
"""

from __future__ import annotations

import importlib.util
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from app.phase1 import repo as _repo

# byok_ref auto-contenido: "user:<uuid>/<provider>". El uuid es laxo (Postgres valida).
_REF_USER_PROVIDER = re.compile(r"^user:(?P<uid>[^/]+)/(?P<prov>[A-Za-z0-9_.\-]+)$")

# [ticket 9] oauth_flow vive fuera del paquete backend (platform/connectors). Lo cargamos
# perezosamente por ruta — mismo patrón que connectors_router._oauth() — y cacheamos el
# módulo. Si no se puede cargar (layout raro), el refresh se salta silenciosamente (el token
# viejo se entrega tal cual; el belt degrada a 401 honesto si ya venció). NUNCA rompe el run.
_OAUTH_PY = Path(__file__).resolve().parents[4] / "platform" / "connectors" / "oauth_flow.py"
_oauth_mod: Any = None
_oauth_load_failed = False


def _oauth_flow():
    global _oauth_mod, _oauth_load_failed
    if _oauth_mod is not None or _oauth_load_failed:
        return _oauth_mod
    try:
        try:
            import aleph_paths
            _oauth_mod = aleph_paths.load_module_by_path(
                "puppet_oauth_flow_broker", _OAUTH_PY)
        except ImportError:
            spec = importlib.util.spec_from_file_location(
                "puppet_oauth_flow_broker", _OAUTH_PY)
            if spec is None or spec.loader is None:
                raise ImportError("oauth_flow sin loader")
            _oauth_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_oauth_mod)
    except Exception:
        _oauth_load_failed = True
    return _oauth_mod


def _oauth_catalog_cfg(provider: str) -> dict:
    """Descriptor OAuth data-driven; el broker no hardcodea endpoints ni client_id."""
    try:
        import aleph_paths
        root = aleph_paths.resource_root()
    except Exception:
        root = Path(__file__).resolve().parents[4]
    path = root / "catalog" / "connectors" / "onboarding" / f"{provider}.json"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        cfg = obj.get("oauth") or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _maybe_refresh_oauth(conn: Any, user_id: str, provider: str, access_token: str) -> str:
    """[ticket 9] Si `provider` tiene un companion "<provider>__oauth" con refresh_token y el
    access_token guardado ya venció, lo RENUEVA server-side ahora y re-persiste el token nuevo
    cifrado (+ actualiza obtained_at/expires_in en el companion). Sin esto, el access_token de
    Google muere a la ~1h y el belt cae a 401 a mitad del run.

    Best-effort y fail-open: ante CUALQUIER fallo (sin companion, oauth_flow no carga, refresh
    rechazado, no se pudo re-persistir) devuelve el token ACTUAL — puede seguir vivo, y si no,
    el belt reporta un 401 honesto. Jamás lanza ni loguea el valor del token.

    Sólo se invoca con los accessors REALES del repo (get_key is None en make_user_resolver);
    los tests que inyectan get_key no pasan por acá."""
    mod = _oauth_flow()
    if mod is None:
        return access_token
    try:
        raw = _repo.get_key(conn, user_id, f"{provider}__oauth")
    except Exception:
        return access_token
    if not raw:
        return access_token
    try:
        companion = json.loads(raw)
    except Exception:
        return access_token
    try:
        res = mod.maybe_refresh(companion, cfg=_oauth_catalog_cfg(provider))
    except Exception:
        return access_token
    if not res.get("refreshed"):
        reason = res.get("reason")
        if reason in ("oauth_revoked", "refresh_failed"):
            # Estado propio y cifrado en el mismo companion. El diagnosticador y la
            # card lo leen sin tener que reinterpretar un 401 como "llave mala".
            companion["state"] = reason
            companion["refresh_error_at"] = time.time()
            try:
                _repo.upsert_key(conn, user_id=user_id,
                                 provider=f"{provider}__oauth",
                                 secret=json.dumps(companion))
            except Exception:
                pass
            if reason == "oauth_revoked":
                return ""  # no entregamos un token ya refutado al subprocess
        return access_token
    new_token = res.get("access_token")
    if not new_token:
        return access_token
    # Re-persistir: primero el access_token nuevo (lo que resuelve el broker), luego el
    # companion actualizado (obtained_at/expires_in/refresh_token) para que el PRÓXIMO lookup
    # vea "still_valid" y no re-renueve. Si el update del companion falla, igual entregamos el
    # token fresco de ESTE run (el peor caso: se re-renueva de más la próxima vez).
    try:
        _repo.upsert_key(conn, user_id=user_id, provider=provider, secret=new_token)
    except Exception:
        return access_token  # no se pudo persistir el nuevo → devolvemos el viejo (aún en DB)
    try:
        companion["obtained_at"] = res.get("obtained_at")
        # review F1 · nunca re-persistir expires_in=None (dispararía renew-loop): preservamos el
        # último TTL conocido si el refresh no trajo uno. maybe_refresh ya cae a un default sano,
        # esto es cinturón-y-tiradores por si el companion se arma por otra vía.
        companion["expires_in"] = res.get("expires_in") or companion.get("expires_in")
        # EL ABSOLUTO TAMBIÉN se re-persiste. `token_expired` le da prioridad a `expira_en`
        # sobre el par relativo: dejar el del grant original acá deja al companion vencido
        # para siempre y renueva en CADA lookup. Si el refresh no trajo absoluto (companion
        # viejo), se BORRA en vez de conservarse rancio, y manda el par relativo.
        if res.get("expira_en") is not None:
            companion["expira_en"] = res["expira_en"]
        else:
            companion.pop("expira_en", None)
        companion["refresh_token"] = res.get("refresh_token") or companion.get("refresh_token")
        companion["granted_scopes"] = (res.get("granted_scopes")
                                         or companion.get("granted_scopes") or [])
        companion["state"] = "connected"
        companion.pop("refresh_error_at", None)
        _repo.upsert_key(conn, user_id=user_id, provider=f"{provider}__oauth",
                         secret=json.dumps(companion))
    except Exception:
        pass
    return new_token


def parse_byok_ref(ref: str) -> tuple[Optional[str], str]:
    """
    Parsea un byok_ref a (user_id|None, provider).

    FORMA CANÓNICA (la que valida recipe_validator §3.4, prefijo 'keys:'):
      "keys:exa"                     -> (None, "exa")        # recomendada: user-agnóstica
      "keys:user:<uuid>/exa"         -> ("<uuid>", "exa")    # con user explícito (raro)

    Formas toleradas (compat / inyección directa en tests):
      "exa"                          -> (None, "exa")        # provider suelto
      "user:<uuid>/exa"              -> ("<uuid>", "exa")    # auto-contenido sin 'keys:'
      "keys.exa.byok_ref"            -> (None, "exa")        # forma de path

    Diseño del aislamiento: el byok_ref CANÓNICO NO lleva user_id — el user_id se liga
    en make_user_resolver(user_id) (el run sabe de quién es la credencial; la receta es
    portable/user-agnóstica). El soporte de "user:<uuid>/" es defensivo (si alguna vez
    llega, se exige que coincida con el dueño del run). Nunca lanza.
    """
    ref = (ref or "").strip()
    if not ref:
        return (None, "")
    # canónica: pelar el prefijo 'keys:' y reparsear el resto
    if ref.startswith("keys:"):
        ref = ref[len("keys:"):].strip()
        if not ref:
            return (None, "")
    m = _REF_USER_PROVIDER.match(ref)
    if m:
        return (m.group("uid"), m.group("prov"))
    # tolerante: "keys.<provider>.byok_ref" → provider
    if ref.startswith("keys.") and ref.endswith(".byok_ref"):
        mid = ref[len("keys."): -len(".byok_ref")]
        return (None, mid)
    # provider suelto
    return (None, ref)


def make_user_resolver(
    user_id: Optional[str],
    *,
    get_conn: Optional[Callable[[], Any]] = None,
    get_key: Optional[Callable[..., Optional[str]]] = None,
) -> Callable[[str], str]:
    """
    Construye un `byok_resolver` LIGADO a `user_id` para pasarle al assembler/executor.

    El resolver resultante mapea  byok_ref -> cleartext  buscando la credencial CIFRADA
    de ESTE usuario en la tabla `keys` y descifrándola en memoria. Aislamiento por
    usuario garantizado: un ref que nombra OTRO user_id se rechaza (devuelve "").

    Args:
      user_id:  el dueño del run. Si None, solo resuelven refs auto-contenidos
                ("user:<uuid>/<prov>"); un provider suelto no tiene a quién atribuirse → "".
      get_conn: factory de conexión (default: repo.get_conn). Inyectable para tests.
      get_key:  función (conn, user_id, provider) -> cleartext|None (default repo.get_key).
                Inyectable para tests sin Postgres.

    El resolver:
      - abre una conexión corta por lookup (no comparte la transacción del run),
      - NUNCA loguea el valor,
      - devuelve "" ante cualquier fallo (sin key / descifrado roto / cross-user).
    """
    _get_conn = get_conn or _repo.get_conn
    _get_key = get_key or _repo.get_key

    def _resolve(ref: str) -> str:
        ref_uid, provider = parse_byok_ref(ref)
        if not provider:
            return ""
        # AISLAMIENTO: si el ref nombra un user_id, debe ser EL del run. Cruzar usuarios
        # está prohibido (un run de A no puede leer la credencial de B).
        if ref_uid is not None and ref_uid != user_id:
            return ""
        target_uid = ref_uid or user_id
        if not target_uid:
            return ""  # provider suelto sin dueño → no resolvemos a ciegas
        conn = None
        try:
            conn = _get_conn()
            # BORRADO DE CUENTA (ticket 2): una cuenta en soft-delete no RE-resuelve
            # credenciales. Cubre la resolución perezosa (nuevos assembles). NO detiene un
            # subprocess MCP ya vivo cuyo env se resolvió antes del borrado (las creds ya
            # inyectadas siguen hasta que el run termina — limitación inherente, ver el guard
            # de arranque en run_puppet_e2e). Solo aplica con los accessors reales (los tests
            # inyectan get_key sin este campo).
            if get_key is None:
                state = _repo.user_deleted_state(conn, target_uid)
                if state is not None and state.get("deleted_at"):
                    return ""
            secret = _get_key(conn, target_uid, provider)
            if not secret:
                return ""
            # OAUTH REFRESH (ticket 9): si el access_token de este provider ya venció y hay
            # refresh_token en el companion, lo renovamos AHORA (server-side) y re-persistimos.
            # Sólo con accessors reales (los tests inyectan get_key y no tienen companion/DB).
            if get_key is None and not provider.endswith("__oauth") \
                    and not provider.endswith("__oauth_partial"):
                secret = _maybe_refresh_oauth(conn, target_uid, provider, secret)
            return secret or ""
        except Exception:
            # jamás propagamos el detalle (podría arrastrar contexto sensible)
            return ""
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    return _resolve


__all__ = ["make_user_resolver", "parse_byok_ref"]
