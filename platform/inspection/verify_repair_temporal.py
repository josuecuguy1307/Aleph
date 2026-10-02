#!/usr/bin/env python3
"""verify_repair_temporal.py — R3 · EL CAMINO TEMPORAL, CON PROCESOS DE VERDAD.

`test_repair.py` mide la política con un reloj falso: conteos exactos, cero sleeps. Esta
vara mide lo otro — que **enganchada al dueño real, con procesos reales, hace lo que dice**.

  1. sin la perilla, el dueño levanta como siempre y repair no decide nada;
  2. con la perilla, un server que muere y revive se arregla **CALLADO**: el pedido siguiente
     levanta un proceso nuevo y nadie pidió una credencial;
  3. el que muere SIEMPRE agota el ciclo y termina BLOQUEADO — con un `DuenoError` que el
     llamante ya sabe leer, no con una excepción que tumbe el loop;
  4. el breaker abre y corta pedidos de OTRAS huellas de la misma entidad;
  5. la lápida cierra el breaker;
  6. cero huérfanos por `ps`.

⏱ EL RELOJ SE REPORTA, NO GATEA. Lo único que se gatea son hechos deterministas —conteos de
intentos, aperturas del breaker, procesos vivos por `ps`—. Es la trampa 8 del acta y la
lección que `verify_calentador_restore_sdk` ya pagó: el reloj está dominado por la máquina
del momento, y una vara que cría lobos deja de leerse.

    product/backend/.venv/bin/python platform/inspection/verify_repair_temporal.py
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "platform/inspection",
           _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("ALEPH_ROLE", "client")
os.environ["ALEPH_DUENO"] = "on"
#: LA CURVA, ACORTADA POR SU PERILLA REAL. `test_repair.py` ya prueba que la curva es
#: 1·2·4·8·16 con jitter acotado; lo que esta vara mide es el CABLEADO con procesos de
#: verdad, y esperar 23 s de backoff para eso sería pagar dos veces por lo mismo. Se usa la
#: perilla que el módulo ya expone, no un monkeypatch: si la perilla dejara de funcionar,
#: esta vara se entera.
os.environ["ALEPH_REPAIR_BASE_S"] = "0.05"

import dueno as D                                           # noqa: E402
import repair as R                                          # noqa: E402

_fallos = 0


def _reloj_de_la_vara():
    time.sleep(180)
    print("\n⛔ LA VARA SE COLGÓ (180 s).", flush=True)
    os._exit(9)


threading.Thread(target=_reloj_de_la_vara, daemon=True).start()


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f" — {detalle}" if detalle else ""))


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 72 - len(t)))


_SERVER = _AQUI / "fixtures_vara_r1_server.py"


def _spec(modo="normal", rpc_timeout=30.0):
    return {"command": sys.executable, "args": [str(_SERVER)],
            "env": dict(os.environ, ALEPH_VARA_MODO=modo),
            "cwd": None, "rpc_timeout": rpc_timeout}


def _vivos() -> list:
    out = subprocess.run(["ps", "-eo", "pid=,command="], capture_output=True, text=True).stdout
    return [int(l.split(None, 1)[0]) for l in out.splitlines()
            if "fixtures_vara_r1_server.py" in l and "verify_repair" not in l]


def _esperar_evento(rp, n=1, seg=6.0):
    """El evento viaja por el hilo drenador del transporte: se le da tiempo, sin gatear."""
    t0 = time.time()
    while time.time() - t0 < seg:
        if rp.estado()["eventos"]["observadas"] >= n:
            return True
        time.sleep(0.05)
    return False


def _enganchar(**kw):
    D._reset_para_tests()
    rp = R._reset_para_tests(**kw)
    d = D.actual()
    d.suscribir(rp.observar)
    d.poner_guardia(rp.permitir)
    return d, rp


print("R3 · EL CAMINO TEMPORAL, CON PROCESOS DE VERDAD")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 · SIN PERILLA, REPAIR NO DECIDE NADA")
previo = os.environ.pop("ALEPH_REPAIR", None)
D._reset_para_tests()
R._reset_para_tests()
ok(R.encendido() is False, "la perilla está apagada por default")
ok(R.cablear(D) is False, "`cablear` no engancha nada")
ok(D.actual()._guardia is None, "el dueño queda SIN guardia")
p = D.actual().pedir("libre", spec=_spec(), motivo="sin repair")
ok(bool(p.pids), "y levanta como siempre")
p.soltar()
D.actual().apagar_todo(motivo="limpieza")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("2 · MUERE Y REVIVE · SE ARREGLA CALLADO")
os.environ["ALEPH_REPAIR"] = "on"
d, rp = _enganchar()
t0 = time.time()
p = d.pedir("vivo", spec=_spec(), motivo="1er uso")
pid1 = p.pids[0]
p.soltar()
os.kill(pid1, signal.SIGKILL)
ok(_esperar_evento(rp), "el dueño avisó la muerte y repair la observó")
est = rp.estado()
ok(est["eventos"]["temporales"] >= 1,
   f"repair la clasificó TEMPORAL ({est['eventos']['temporales']})")
ok(est["eventos"]["permanentes"] == 0, "y ninguna permanente: no hay botón que mostrar")

p2 = d.pedir("vivo", spec=_spec(), motivo="2º uso")          # el reintento REAL
pid2 = p2.pids[0]
ok(pid2 != pid1 and pid2 in _vivos(), f"levantó un proceso NUEVO y vivo (pid {pid2})")
ok(p2.call_tool("echo", {"text": "anda"}) == "anda", "y contesta: se arregló")
ms = int((time.time() - t0) * 1000)
print(f"    ⏱  ciclo completo en {ms} ms (REPORTE, no gate)")
p2.soltar()
d.apagar_todo(motivo="limpieza")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("3 · EL QUE MUERE SIEMPRE · AGOTA Y BLOQUEA")
# jitter fijo en el mínimo para que la vara no dependa del azar; la curva ya la mide el test
d, rp = _enganchar(jitter=lambda a, b: -0.25)
clave = None
bloqueado = None
for i in range(R.MAX_INTENTOS * 3 + 6):
    try:
        pr = d.pedir("mortal", spec=_spec(), motivo=f"intento {i}")
    except D.DuenoError as e:
        # ⚠️ ESPERAR y BLOQUEADO llegan los dos como `DuenoError` (los dos tienen
        # `pasa == False`), y son cosas distintas: uno es «todavía no», el otro es «no más».
        # Distinguirlos por el MOTIVO, que es el dato que repair puso ahí a propósito.
        if "backoff en curso" in str(e):
            time.sleep(0.2)
            continue
        bloqueado = str(e)
        break
    clave = pr.clave
    pid = pr.pids[0]
    pr.soltar()
    os.kill(pid, signal.SIGKILL)
    _esperar_evento(rp, n=i + 1)
    # ⚠️ EL BACKOFF SE ESPERA MIRANDO EL CICLO, NO PIDIENDO PERMISO. Una versión anterior
    # llamaba a `rp.permitir(...)` acá sólo para leer `faltan_s`, y eso CONSUMÍA un intento
    # — la vara gastaba el ciclo por su cuenta y después medía mal lo que quedaba. Consultar
    # un permiso no es gratis: es la decisión.
    c = rp.estado()["ciclos"].get(clave)
    if c is not None and not c["agotado"]:
        time.sleep(rp.espera(max(1, c["intentos"])) + 0.02)

est = rp.estado()
print(f"    intentos permitidos={est['eventos']['intentos_permitidos']} · "
      f"ciclos agotados={est['eventos']['ciclos_agotados']} · "
      f"bloqueos={est['eventos']['bloqueos']}")
ok(bloqueado is not None, "terminó BLOQUEADO", f"nunca bloqueó tras {R.MAX_INTENTOS + 3} vueltas")
ok(bloqueado is None or "no se levanta ahora" in bloqueado,
   "y con un `DuenoError` que el llamante ya sabe leer", f"dijo: {bloqueado!r}")
ok(est["eventos"]["ciclos_agotados"] >= 1, "el ciclo se agotó de verdad")
ok("llave" not in (bloqueado or "") and "credencial" not in (bloqueado or ""),
   "JAMÁS pidió una credencial por un temporal (§3.5)")
d.apagar_todo(motivo="limpieza")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("4 · EL BREAKER CORTA OTRAS HUELLAS DE LA MISMA ENTIDAD")
rp.cerrar_breaker(None, "mortal", motivo="reset de la vara")
for i in range(R.CICLOS_PARA_ABRIR):
    rp.observar({"clave": f"-|mortal|h{i}", "user_id": None, "entity_id": "mortal",
                 "huella": f"h{i}", "disparador": "EOF", "murio_por_eof": True})
    for _ in range(R.MAX_INTENTOS + 1):
        perm = rp.permitir(None, "mortal", f"-|mortal|h{i}")
        if perm.decision == R.BLOQUEADO:
            break
        # se salta el backoff moviendo el ciclo, no el reloj: la política es la que se mide
        rp._ciclos[f"-|mortal|h{i}"].proximo_t = 0
est = rp.estado()
abierto = est["breakers"].get("-|mortal", {})
ok(abierto.get("estado") == R.ABIERTO,
   f"el breaker de «mortal» quedó ABIERTO ({abierto.get('estado')})")
otra = rp.permitir(None, "mortal", "-|mortal|OTRA-HUELLA")
ok(otra.decision == R.BLOQUEADO, "y corta una huella NUEVA de la misma entidad")
ok(rp.permitir(None, "otra_entidad", "-|otra_entidad|x").pasa,
   "pero NO toca a otra entidad")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("5 · LA LÁPIDA CIERRA EL BREAKER")
rp.observar({"clave": "-|mortal|h0", "user_id": None, "entity_id": "mortal",
             "disparador": "LAPIDA", "murio_por_eof": True})
ok("-|mortal" not in rp.estado()["breakers"],
   "el breaker se cerró: una entidad desconectada no queda con uno esperándola")
ok(rp.permitir(None, "mortal", "-|mortal|z").pasa, "y vuelve a pasar")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("6 · CERO HUÉRFANOS")
D.actual().apagar_todo(motivo="fin de la vara")
ok(not _vivos(), "no queda ningún server de la vara vivo", f"quedaron {_vivos()}")
ok(not D.actual().estado()["vivas"], "y la tabla del dueño queda vacía")

if previo is None:
    os.environ.pop("ALEPH_REPAIR", None)
else:
    os.environ["ALEPH_REPAIR"] = previo

print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
sys.exit(0 if _fallos == 0 else 1)
