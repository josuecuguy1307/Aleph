"""red.py — LA SONDA DE INTERNET (FIX-P9 · §6c). UNA, en el sidecar, con cache corta.

EL BUG QUE ESTO CIERRA — la mentira de `motor_verdad.py`. Hasta acá, cualquier error de
transporte se traducía directo a `sin_red`:

    if kind == "net":  return _resultado(..., causa=SIN_RED)      # ← la mentira

Eso hacía que la UI dijera «Sin conexión» cuando lo que había pasado era, casi siempre,
otra cosa:
  · un MCP stdio local que no arrancó (jamás tocó la red),
  · un server en 127.0.0.1 que no estaba levantado (jamás tocó la red),
  · el DNS de UN proveedor caído mientras el resto de internet andaba perfecto,
  · un certificado vencido de UN host.
Y el costo no es cosmético: «sin internet» manda a la persona a revisar su WiFi —que está
bien— en vez de al arreglo real. Es un cartel que apunta al lado equivocado.

LA REGLA, y es dura:

    NADIE ESCRIBE `sin_red` SIN QUE ESTA SONDA HAYA DICHO QUE NO.

Un fallo de transporte es, por sí solo, evidencia de que *ese destino* no respondió. Para
afirmar que INTERNET está caído hace falta una segunda medición, independiente del destino
que falló. Eso es lo que hace este módulo, y por eso vive acá y no adentro del motor: lo
comparten `motor_verdad`, `centro_conexiones` y `centro_modelos` — una sola verdad de red
para las tres superficies, con una sola cache.

CÓMO MIDE (y por qué así):
  · VARIOS destinos de ORGANIZACIONES DISTINTAS (Google · Microsoft · Cloudflare). Con uno
    solo, «Cloudflare caído» se leería como «no tenés internet» — el mismo error de
    atribución que estamos matando, movido un escalón más arriba.
  · En PARALELO, y gana el primero que contesta: el caso feliz cuesta ~1 RTT, no N.
  · Respuestas MÍNIMAS (204 / un txt de 20 bytes): no descarga nada.
  · Si CUALQUIERA contesta → hay internet. Si TODOS fallan por transporte → no hay.
  · Un HTTP raro (403 de un portal cautivo, un 500) cuenta como CONTESTÓ: hubo diálogo con
    algo del otro lado. Lo que se está midiendo es «¿sale un paquete y vuelve?», no «¿está
    sano ese endpoint?».

CACHE: TTL corto (30 s por defecto, el mismo orden que el motor). El estado de la red
cambia despacio comparado con una ráfaga de pruebas; sin cache, probar 8 piezas rotas
disparaba 24 requests de sonda. SINGLE-FLIGHT: si diez hilos preguntan a la vez mientras la
sonda corre, la corren UNA vez y los diez leen ese resultado.

HONESTIDAD DEL PROPIO MÓDULO: si la sonda no se puede correr (la apagaron por env, no hay
destinos configurados), devuelve `online=None` — DESCONOCIDO, que NO es `False`. Y quien
consulta tiene prohibido convertir un desconocido en `sin_red`: sin un NO explícito, la
causa honesta es la del proveedor que falló, no la de la red de la persona.
"""
from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

# ── Destinos por defecto: tres organizaciones distintas, endpoints de "connectivity check"
#    pensados justamente para esto (existen hace más de una década y devuelven casi nada).
_DEFAULT_TARGETS = (
    "https://connectivitycheck.gstatic.com/generate_204",   # Google  → 204, cero body
    "https://www.msftconnecttest.com/connecttest.txt",      # MSFT    → 22 bytes
    "https://cloudflare.com/cdn-cgi/trace",                 # CF      → ~200 bytes
)

ONLINE = "online"
OFFLINE = "offline"
DESCONOCIDO = "desconocido"


def _targets() -> list[str]:
    raw = (os.environ.get("PUPPET_RED_TARGETS") or "").strip()
    if raw:
        return [t.strip() for t in raw.split(",") if t.strip()]
    return list(_DEFAULT_TARGETS)


def _ttl() -> float:
    return float(os.environ.get("PUPPET_RED_TTL", "30"))


def _timeout() -> float:
    return float(os.environ.get("PUPPET_RED_TIMEOUT", "2.5"))


# ── cache + single-flight ──────────────────────────────────────────────────────────
_LOCK = threading.Lock()
_ESTADO: Optional[dict] = None
_CORRIENDO: Optional[threading.Event] = None


def invalidar() -> None:
    """Tira la cache (lo usa la vara y el 'reintentar' explícito del humano)."""
    global _ESTADO
    with _LOCK:
        _ESTADO = None


def _tocar(url: str, timeout: float) -> dict:
    """UN destino. `ok=True` significa CONTESTÓ ALGO (incluso un 4xx/5xx): hubo ida y vuelta.
    `ok=False` sólo cuando el transporte murió — DNS, ruta, TLS, timeout."""
    req = urllib.request.Request(url, method="GET",
                                 headers={"User-Agent": "puppet-sonda-red/1.0",
                                          "Cache-Control": "no-cache"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(64)
            return {"ok": True, "url": url, "http": getattr(resp, "status", 200),
                    "ms": int((time.perf_counter() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        # Contestó. Un portal cautivo que devuelve 403 es INTERNET (degradado, pero hay
        # paquetes yendo y volviendo). No es el caso «tu WiFi está muerto».
        return {"ok": True, "url": url, "http": e.code, "portal": True,
                "ms": int((time.perf_counter() - t0) * 1000)}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", None) or e
        return {"ok": False, "url": url, "err": str(reason)[:160],
                "ms": int((time.perf_counter() - t0) * 1000)}


def _medir() -> dict:
    """Corre TODOS los destinos en paralelo y devuelve apenas uno conteste."""
    forzado = (os.environ.get("PUPPET_RED_FORZAR") or "").strip().lower()
    if forzado in (ONLINE, OFFLINE, DESCONOCIDO):
        # Palanca de LABORATORIO (la usan las varas para fabricar un 'sin internet' real sin
        # apagarle el WiFi a nadie). Se declara en la evidencia: un verde forzado se ve.
        return {"online": True if forzado == ONLINE else (False if forzado == OFFLINE else None),
                "via": "forzado:" + forzado, "ts": time.time(), "destinos": []}

    targets = _targets()
    if not targets:
        return {"online": None, "via": "sin-destinos", "ts": time.time(), "destinos": []}

    timeout = _timeout()
    resultados: list[dict] = []
    res_lock = threading.Lock()
    gano = threading.Event()

    def corre(u: str) -> None:
        r = _tocar(u, timeout)
        with res_lock:
            resultados.append(r)
        if r["ok"]:
            gano.set()

    hilos = [threading.Thread(target=corre, args=(u,), daemon=True) for u in targets]
    for h in hilos:
        h.start()
    # Espera al primer éxito, o a que se agote el presupuesto de todos.
    gano.wait(timeout + 0.5)
    if not gano.is_set():
        for h in hilos:
            h.join(0.25)

    with res_lock:
        vistos = list(resultados)
    exitos = [r for r in vistos if r.get("ok")]
    if exitos:
        g = min(exitos, key=lambda r: r.get("ms", 10 ** 9))
        return {"online": True, "via": g["url"], "latencia_ms": g.get("ms"),
                "ts": time.time(), "destinos": vistos}
    if len(vistos) < len(targets):
        # Ni un éxito, y encima no todos alcanzaron a terminar → NO alcanza para afirmar
        # «no hay internet». Desconocido honesto.
        return {"online": None, "via": "incompleta", "ts": time.time(), "destinos": vistos}
    return {"online": False, "via": "todos-fallaron", "ts": time.time(), "destinos": vistos}


def sonda(force: bool = False) -> dict:
    """LA sonda. → {online: True|False|None, via, ts, cacheado, latencia_ms?, destinos}

    `online is None` = DESCONOCIDO. Quien lea esto NO puede escribir `sin_red`: sólo un
    `False` explícito autoriza esa causa (§6c)."""
    global _ESTADO, _CORRIENDO
    ttl = _ttl()
    with _LOCK:
        if not force and _ESTADO is not None and (time.time() - _ESTADO["ts"]) < ttl:
            return {**_ESTADO, "cacheado": True}
        if _CORRIENDO is not None:
            # Otro hilo ya la está corriendo: esperamos SU resultado en vez de disparar otra.
            esperando = _CORRIENDO
        else:
            esperando = None
            _CORRIENDO = threading.Event()
            mio = _CORRIENDO

    if esperando is not None:
        esperando.wait(_timeout() + 2.0)
        with _LOCK:
            if _ESTADO is not None:
                return {**_ESTADO, "cacheado": True}
        return {"online": None, "via": "espera-agotada", "ts": time.time(),
                "cacheado": False, "destinos": []}

    try:
        medido = _medir()
    except Exception as e:  # noqa: BLE001  — la sonda JAMÁS puede tumbar a quien la llama
        medido = {"online": None, "via": f"sonda-rota:{e}", "ts": time.time(), "destinos": []}
    with _LOCK:
        _ESTADO = medido
        _CORRIENDO = None
    mio.set()          # recién acá: los que esperaban ya encuentran el resultado en la cache
    return {**medido, "cacheado": False}


def hay_internet(force: bool = False) -> Optional[bool]:
    """Atajo: True | False | None(desconocido). El azúcar que consumen los motores."""
    return sonda(force=force).get("online")


__all__ = ["sonda", "hay_internet", "invalidar", "ONLINE", "OFFLINE", "DESCONOCIDO"]
