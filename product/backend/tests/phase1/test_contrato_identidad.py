"""test_contrato_identidad.py — CONGELA la clase "identidad del cliente". Hallazgo #1.

El patrón apareció 13+ veces porque nada impedía re-introducirlo. Este test lo impide:
barre TODO handler de FastAPI y falla la suite si alguien vuelve a declarar identidad
como parámetro del CLIENTE (query/body), o si la allowlist pública del middleware crece
sin revisión. Es el lint que persona usuaria pidió, corriendo en cada build.

Base del lint automático post-launch (hallazgo #1 del proyecto).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
for p in (REPO_ROOT / "product" / "backend",):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

APP = REPO_ROOT / "product" / "backend" / "app"
_HANDLER = re.compile(r'@(?:router|app)\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']')
_IDENT_PARAM = re.compile(r'\b(user_id|account_id|owner_id)\b\s*:\s*(?:Optional\[)?str')

#: Excepciones JUSTIFICADAS a "no declares identidad como param". Cada una con motivo.
#: Path params {user_id} owner-gated NO entran acá (se comparan contra la sesión y son
#: el patrón correcto). Esta lista es para params query/body que sobreviven por una razón.
_EXCEPCIONES_IDENT_PARAM = {
    # (ninguna hoy — A=0 tras cerrar H4. Si aparece una, va acá CON motivo, o se arregla.)
}


def _handlers():
    """(archivo, linea, metodo, path, firma) por cada handler del backend."""
    for f in sorted(APP.rglob("*.py")):
        L = f.read_text(errors="ignore").splitlines()
        for i, ln in enumerate(L):
            m = _HANDLER.search(ln)
            if not m:
                continue
            sig = ""
            j = i + 1
            while j < len(L) and j < i + 12:
                sig += L[j] + "\n"
                if re.search(r"\)\s*(->|:)", L[j]):
                    break
                j += 1
            yield (str(f.relative_to(APP)), i + 1, m.group(1).upper(), m.group(2), sig)


def test_ningun_handler_declara_identidad_como_param_del_cliente():
    """Dirección A del patrón: `user_id: str = None` / `?user_id=` en la firma. La
    identidad SALE DE LA SESIÓN (authz.require_actor), nunca de un param que el cliente
    controla. Un path param `{user_id}` owner-gated es otra cosa y no cae acá."""
    infractores = []
    for rel, linea, meth, path, sig in _handlers():
        if _IDENT_PARAM.search(sig):
            # path param {user_id} es legítimo (owner-gated) — no es el param del body/query
            if any("{" + p + "}" in path for p in ("user_id", "account_id", "owner_id")):
                continue
            if f"{rel}:{linea}" in _EXCEPCIONES_IDENT_PARAM:
                continue
            infractores.append(f"{rel}:{linea}  {meth} {path}")
    assert not infractores, (
        "CLASE 'identidad del cliente' RE-INTRODUCIDA — un handler declara la identidad "
        "como parámetro que el cliente controla. Sacala de la sesión (authz.require_actor):\n  "
        + "\n  ".join(infractores))


def test_la_allowlist_publica_no_creció_sin_revision():
    """El middleware es default-cerrado; su allowlist pública es la única puerta. Si
    crece, tiene que ser una DECISIÓN revisada — no un olvido. Este test la congela: al
    agregar una ruta pública, actualizás esta lista, y ese diff es la revisión."""
    from app.phase1 import authz
    esperado_exact = {
        "/v1/auth/login", "/v1/auth/register",
        "/v1/payments/status", "/v1/brains/status",
        # [login suave] REVISADO: ambos NO exponen datos de usuario y se auto-gatean.
        # /v1/auth/local minta la sesión LOCAL anónima (device user) — pública por
        # necesidad (se llama SIN sesión); 404 en control (_es_control_plane).
        # /v1/auth/merge-local es capability-based (exige el Bearer de la cuenta EN el
        # endpoint → 401 propio si falta); pública para que su chequeo de rol dé el 404
        # honesto en control en vez de que la muralla lo tape con un 401 genérico.
        "/v1/auth/local", "/v1/auth/merge-local",
        # [5a] REVISADO: consulta el registro público y sólo persiste el catálogo local
        # del cliente. No recibe identidad ni expone recursos de una cuenta.
        "/v1/catalog/ingest",
    }
    esperado_prefix = ("/v1/payments/webhook/", "/v1/icons/")
    esperado_get = ("/v1/catalog/",)
    assert authz._PUBLIC_V1_EXACT == esperado_exact, (
        "la allowlist pública EXACTA cambió — revisá que cada ruta nueva NO exponga datos "
        f"de usuario. Actual: {authz._PUBLIC_V1_EXACT}")
    assert authz._PUBLIC_V1_PREFIX == esperado_prefix, \
        f"los prefijos públicos cambiaron: {authz._PUBLIC_V1_PREFIX}"
    assert authz._PUBLIC_V1_GET_PREFIX == esperado_get, \
        f"los prefijos GET públicos cambiaron: {authz._PUBLIC_V1_GET_PREFIX}"


def test_require_actor_saca_identidad_de_la_sesion_no_del_arg():
    """El helper canónico: la identidad viene del TOKEN, no de un user_id que se le pase.
    (No hay forma de pasarle un user_id declarado — su única fuente es el token.)"""
    import inspect
    from app.phase1 import authz
    params = list(inspect.signature(authz.require_actor).parameters)
    assert "user_id" not in params and "account_id" not in params, (
        "require_actor acepta un user_id/account_id como argumento — eso reabre la puerta "
        "a pasar identidad del cliente")
    assert params[0] == "authorization", "require_actor debe derivar del header, primero"
