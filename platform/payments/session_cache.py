"""session_cache.py — LA IDENTIDAD SOBREVIVE A LA RED. CONTRACT-AUTH-v2 · criterio duro.

    "JWT vencido + sin red JAMÁS mata al cliente. Si eso no aguanta, rompiste el
     local-first que es la tesis del producto." — persona usuaria, criterio NO NEGOCIABLE de v2.

EL PROBLEMA QUE V2 INTRODUCE. El token Fernet de v1 no caducaba nunca: sin red, el
cliente seguía siendo él mismo para siempre. El JWT de Supabase caduca en ~1 h y
renovarlo EXIGE RED. Sin cuidado, la secuencia es:

    se corta internet → pasa una hora → el token vence → no hay red para refrescar
    → el cliente que pagó se queda afuera de su propio agente

Eso no es un bug de borde: es el producto dejando de funcionar por algo que el usuario
no hizo y no puede arreglar.

LA POLÍTICA, hermana de la del tier (tier_cache.py) y por las mismas razones:

  1. Nunca supimos quién sos  →  anónimo.
     Fail-closed donde no lastima: alguien que nunca entró no pierde nada.

  2. Te CONOCIMOS y el token venció SIN RED  →  seguís siendo vos, marcado honesto.
     La caducidad de un JWT dice "hay que revalidar", NO "esta persona es un impostor".
     Tratarla como lo segundo es el error que rompe el local-first.

  3. El servidor dice que la sesión NO vale  →  afuera, en el acto.
     Un 401 CON RED es una respuesta: se obedece y se borra la sesión. Sólo el SILENCIO
     de la red preserva.

LA DISTINCIÓN QUE LO SOSTIENE TODO: "no pude preguntar" ≠ "me dijeron que no".
Confundirlas en un sentido deja entrar a cualquiera; en el otro, echa al que pagó.

⚠️ ESTO NO ES UNA FUENTE DE AUTORIDAD. El servidor revalida SIEMPRE: un cliente que se
cree logueado sin token válido no logra nada server-side (construir, exportar, memoria
compartida) porque el server no lo reconoce. Este cache sostiene la EXPERIENCIA LOCAL —
seguir viendo tus agentes, seguir trabajando offline — no los permisos.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

#: Ventana en la que la sesión se da por fresca sin revalidar. Corta a propósito: si hay
#: red, revalidar es barato y conviene enterarse pronto de un logout remoto.
FRESCA_S = int(os.environ.get("ALEPH_SESSION_FRESH_S", str(15 * 60)))


def _dir() -> Path:
    d = Path(os.environ.get("ALEPH_SESSION_CACHE_DIR")
             or (Path.home() / ".aleph" / "session"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _archivo() -> Path:
    return _dir() / "sesion.json"


@dataclass(frozen=True)
class Identidad:
    """Quién es el usuario AHORA, y con cuánta confianza."""

    account_id: Optional[str]
    email: Optional[str] = None
    fuente: str = "sin_dato"      # 'remoto' | 'cache' | 'cache_offline' | 'sin_dato'
    degraded: bool = False
    edad_s: Optional[int] = None
    mensaje: Optional[str] = None

    @property
    def hay_sesion(self) -> bool:
        return bool(self.account_id)


def guardar(account_id: str, *, email: Optional[str] = None,
            token: Optional[str] = None,
            ahora: Optional[_dt.datetime] = None) -> None:
    """Persiste la última identidad CONFIRMADA por el servidor.

    Escritura atómica: un corte a mitad de escritura dejaría un JSON roto que se leería
    como "sin dato" — o sea, desloguearía al usuario por un corte de luz.
    """
    ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
    destino = _archivo()
    datos = {"account_id": str(account_id), "email": email, "token": token,
             "confirmado_at": ahora.isoformat()}
    fd, tmp = tempfile.mkstemp(dir=str(destino.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(datos, f)
        os.chmod(tmp, 0o600)      # el token es una credencial: no legible por otros
        os.replace(tmp, destino)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def leer() -> Optional[dict]:
    try:
        d = json.loads(_archivo().read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("account_id") else None


def olvidar() -> None:
    """Logout: borra la sesión local. Sin esto, la próxima apertura reviviría al
    usuario anterior — y en una máquina compartida eso es entrar a la cuenta ajena."""
    try:
        _archivo().unlink()
    except OSError:
        pass


def _edad_s(d: dict, ahora: _dt.datetime) -> Optional[int]:
    try:
        t = _dt.datetime.fromisoformat(str(d.get("confirmado_at")))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return int((ahora - t).total_seconds())


def resolver_identidad(revalidar: Optional[Callable[[], Any]] = None, *,
                       ahora: Optional[_dt.datetime] = None,
                       forzar: bool = False) -> Identidad:
    """EL punto de entrada. Aplica las tres reglas de la cabecera.

    `revalidar()` debe devolver:
      · un `account_id` (str) → el servidor CONFIRMA la sesión;
      · `False`               → el servidor NIEGA la sesión (401 con red): se cierra;
      · lanzar / `None`       → NO SE PUDO PREGUNTAR: se preserva lo conocido.

    Esa distinción es el corazón del criterio. `None` y `False` NO son lo mismo: uno es
    silencio y el otro es una respuesta.
    """
    ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
    cacheada = leer()
    edad = _edad_s(cacheada, ahora) if cacheada else None

    fresca = (cacheada is not None and edad is not None and edad < FRESCA_S)
    if fresca and not forzar:
        return Identidad(account_id=cacheada["account_id"], email=cacheada.get("email"),
                         fuente="cache", edad_s=edad)

    if revalidar is not None:
        try:
            r = revalidar()
        except Exception:
            r = None                      # silencio de la red
        if r is False:
            # REGLA 3 · el servidor NEGÓ con red de por medio. Se obedece y se cierra.
            olvidar()
            return Identidad(account_id=None, fuente="remoto",
                             mensaje="Tu sesión ya no es válida. Inicia sesión otra vez.")
        if isinstance(r, str) and r:
            guardar(r, email=(cacheada or {}).get("email"), ahora=ahora)
            return Identidad(account_id=r, email=(cacheada or {}).get("email"),
                             fuente="remoto", edad_s=0)

    if cacheada is None:
        # REGLA 1 · nunca supimos nada.
        return Identidad(account_id=None, fuente="sin_dato", degraded=True,
                         mensaje="No hay una sesión guardada en este equipo.")

    # REGLA 2 · EL CRITERIO NO NEGOCIABLE. Token vencido + sin red → seguís siendo vos.
    return Identidad(
        account_id=cacheada["account_id"], email=cacheada.get("email"),
        fuente="cache_offline", degraded=True, edad_s=edad,
        mensaje="Estás trabajando sin conexión. Sigues con tu sesión guardada; "
                "revalidamos cuando vuelva internet.")
