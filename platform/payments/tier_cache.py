"""tier_cache.py — el tier en el cliente, con la RED COMO OPCIONAL. Step 5 · P6.

    "El local-first NO se negocia. Si la sesión de Supabase vence a la hora y sin red
     el cliente muere, rompiste la tesis central del producto." — persona usuaria, 2026-07-20

LA POLÍTICA, en tres reglas. Todo lo demás se deduce de acá:

  1. NUNCA supimos que sos premium  →  free.
     Fail-closed en la única dirección que no lastima: alguien recién instalado y sin
     red no pierde nada que haya tenido.

  2. Te CONOCIMOS premium y ahora no hay red  →  seguís premium, marcado honesto.
     Un fallo de red JAMÁS revoca. Cortarle el producto a alguien que pagó porque se
     le cayó el wifi es el peor error posible: es el que se siente como estafa.

  3. El servidor dice free  →  free, en el acto.
     Una respuesta EXITOSA es autoritativa y degrada al instante. Sólo el silencio de
     la red preserva el estado anterior; una respuesta clara nunca se ignora.

Corolario que parece un agujero y NO lo es: sin red, el último tier conocido vale
indefinidamente (no hay caducidad dura que te tire a free). Por qué es seguro:
  · Lo caro es SERVER-SIDE. Construir un MCP (el MOAT, Motor B) no ocurre sin red, y
    el servidor gatea por su cuenta sin confiar en este cache. Quedarse offline no
    desbloquea nada de lo que protege el negocio.
  · Lo que sí queda accesible offline son capacidades LOCALES (export total). El techo
    del abuso es "alguien cancela y se queda sin internet a propósito para exportar".
    Cambiar eso por el riesgo de la regla 2 sería un pésimo negocio.
  · En cuanto hay red, se corrige solo (y la reconciliación de P5 respalda).

PRECEDENTE: el patrón de `mcp_registry.cache_get` — el único del árbol que ya
distingue "el remoto se cayó" de "el remoto dijo que no". Es exactamente la distinción
que un check de tier necesita, y confundirla es el bug clásico de esta feature.

⚠ ESTE CACHE NO ES UNA FUENTE DE VERDAD. Los muros server-side siguen resolviendo el
tier desde la CUENTA en cada request (tier_gate.resolve_account_tier). Esto es para que
el cliente sepa qué mostrar y qué permitir localmente sin quedar rehén de la red.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

#: Ventana en la que el dato se considera FRESCO y ni se intenta la red.
#: Generoso a propósito: el tier de alguien cambia como mucho una vez por ciclo de
#: facturación, no cada hora.
FRESCO_S = int(os.environ.get("ALEPH_TIER_CACHE_TTL_S", str(24 * 3600)))

FREE = "free"


def _dir_cache() -> Path:
    d = Path(os.environ.get("ALEPH_TIER_CACHE_DIR")
             or (Path.home() / ".aleph" / "tier_cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class Veredicto:
    """Qué tier vale AHORA para este cliente, y con cuánta confianza.

    `degraded` es la honestidad hecha campo: True significa "esto es lo último que
    supimos, no pudimos confirmarlo". La UI tiene que poder decirlo — el producto no
    finge certeza que no tiene.
    """

    tier: str
    fuente: str            # 'remoto' | 'cache' | 'cache_offline' | 'sin_dato'
    degraded: bool = False
    edad_s: Optional[int] = None
    mensaje: Optional[str] = None

    @property
    def es_premium(self) -> bool:
        return self.tier in ("basico", "tecnico")


def _archivo(account_id: str) -> Path:
    # el account_id puede ser un uuid o un email; se sanea para nombre de archivo
    seguro = "".join(c for c in str(account_id) if c.isalnum() or c in "-_")[:80]
    return _dir_cache() / f"{seguro or 'anon'}.json"


def guardar(account_id: str, tier: str, *, ahora: Optional[_dt.datetime] = None) -> None:
    """Persiste el último tier CONFIRMADO por el servidor. Escritura atómica: un
    corte a mitad de escritura no puede dejar un JSON roto que después se lea como
    'sin dato' y degrade a alguien a free."""
    ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
    destino = _archivo(account_id)
    datos = {"account_id": str(account_id), "tier": tier,
             "confirmado_at": ahora.isoformat()}
    fd, tmp = tempfile.mkstemp(dir=str(destino.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(datos, f)
        os.replace(tmp, destino)          # atómico en POSIX
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def leer(account_id: str) -> Optional[dict]:
    """El último tier confirmado, o None si nunca supimos nada de esta cuenta."""
    try:
        d = json.loads(_archivo(account_id).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not d.get("tier"):
        return None
    return d


def olvidar(account_id: str) -> None:
    """Borra el dato cacheado (logout, o cambio de cuenta en la misma máquina).
    Un logout que dejara el tier del anterior filtraría plan entre cuentas."""
    try:
        _archivo(account_id).unlink()
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


def resolver_tier(account_id: str,
                  consultar_remoto: Optional[Callable[[], Any]] = None,
                  *, ahora: Optional[_dt.datetime] = None,
                  forzar_remoto: bool = False) -> Veredicto:
    """EL punto de entrada. Aplica las tres reglas de la cabecera.

    `consultar_remoto()` debe devolver el tier (str) si el servidor respondió, o
    lanzar / devolver None si no se pudo llegar. LA DISTINCIÓN ES TODO: una excepción
    significa "no sé" (preserva), un string significa "sé" (manda, aunque sea free).
    """
    ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
    cacheado = leer(account_id)
    edad = _edad_s(cacheado, ahora) if cacheado else None

    # ── Regla implícita de eficiencia: si está fresco, ni molestamos a la red ──
    fresco = (cacheado is not None and edad is not None and edad < FRESCO_S)
    if fresco and not forzar_remoto:
        return Veredicto(tier=cacheado["tier"], fuente="cache", edad_s=edad)

    # ── Intento de confirmación remota ──────────────────────────────────────────
    if consultar_remoto is not None:
        try:
            remoto = consultar_remoto()
        except Exception:
            remoto = None          # no sé ≠ dijo que no
        if isinstance(remoto, str) and remoto:
            # REGLA 3 · respuesta exitosa: manda, incluso para degradar.
            guardar(account_id, remoto, ahora=ahora)
            return Veredicto(tier=remoto, fuente="remoto", edad_s=0)

    # ── No hubo confirmación ────────────────────────────────────────────────────
    if cacheado is None:
        # REGLA 1 · nunca supimos nada → free (fail-closed donde no duele).
        return Veredicto(
            tier=FREE, fuente="sin_dato", degraded=True,
            mensaje="No pudimos verificar tu plan y no tenemos uno guardado en este "
                    "equipo. Vas a funcionar con el plan gratuito hasta que haya "
                    "conexión.")

    # REGLA 2 · lo conocimos → se le respeta, marcado honesto. Sin caducidad dura:
    # un fallo de red NUNCA revoca.
    return Veredicto(
        tier=cacheado["tier"], fuente="cache_offline", degraded=True, edad_s=edad,
        mensaje="No pudimos verificar tu plan ahora mismo; sigues con el último "
                "confirmado. Lo revalidamos solo cuando vuelva la conexión.")
