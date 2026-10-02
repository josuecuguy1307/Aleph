#!/usr/bin/env python3
"""verify_evento_muerte.py — R1 · EL EVENTO DE MUERTE, Y NADA MÁS.

Primera sesión de construcción de `DISEÑO-REPAIR-v1.md`. **No hay repair todavía**: acá se
construye el dato que repair va a consumir, y el suscriptor de esta vara sólo ANOTA.

Lo que se fija:

  1. **sin suscriptor, el dueño se comporta EXACTAMENTE como antes de R1** — es lo que
     mantiene verde a `verify_dueno.py` sin tocarlo;
  2. matar un hijo a mano produce **UN** evento, con `stderr` no vacío, `vivio_s` coherente
     y la clave correcta;
  3. **una muerte SIN QUE NADIE PIDA también lo produce** — es LO QUE HOY NO PASABA: antes
     de R1 `_parece_muerta` sólo se consultaba dentro de `pedir()`, así que una muerte con
     nadie mirando no la veía nadie. Y el fantasma del §6 es exactamente eso;
  4. **la trampa del fantasma**: un timeout que vence queda anotado con CUÁNDO, QUIÉN, cuál
     de los dos relojes (30 s del run · 45 s de la sonda) y cuánto tardó, y el evento de
     muerte lo lleva encima — para poder decir si la muerte siguió a un timeout y a cuál;
  5. el evento sale **UNA sola vez** aunque la muerte llegue por dos caminos;
  6. el suscriptor se llama **FUERA del lock** (si no, un reintento re-entraría el `RLock`);
  7. un suscriptor que explota **no tumba al dueño** ni se come los eventos de los otros.

    product/backend/.venv/bin/python platform/inspection/verify_evento_muerte.py
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
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

import dueno as D                                           # noqa: E402

_fallos = 0

#: RELOJ DE LA PROPIA VARA. Si algo se cuelga —un saludo que no completa, un lock mal
#: tomado— esto sale con diagnóstico en vez de dejar la sesión colgada para siempre.
#: Una vara que puede colgarse indefinidamente no es una vara: es una apuesta.
def _reloj_de_la_vara():
    time.sleep(180)
    print("\n⛔ LA VARA SE COLGÓ (180 s) — algo no completó. Ver la última sección impresa.",
          flush=True)
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


#: EL SERVER DE LA VARA es un CALCO de `platform/assembler/fixtures/echo_server.py` —el
#: fixture que ya funciona con el puente— más un modo `colgar` que NO contesta, para que el
#: reloj del transporte venza de verdad. Calcado y no escrito de cero por una medición: un
#: server propio que devolvía la `protocolVersion` negociada en vez de una fija no completaba
#: el saludo y colgaba el arranque. El fixture bueno ya resolvió eso.
_SERVER = _AQUI / "fixtures_vara_r1_server.py"


def _spec(modo="normal", rpc_timeout=30.0):
    return {"command": sys.executable, "args": [str(_SERVER)],
            "env": dict(os.environ, ALEPH_VARA_MODO=modo),
            "cwd": None, "rpc_timeout": rpc_timeout}


def _vivo(pid: int) -> bool:
    out = subprocess.run(["ps", "-o", "state=", "-p", str(pid)],
                         capture_output=True, text=True).stdout.strip()
    return bool(out) and not out.startswith("Z")


print(f"R1 · EL EVENTO DE MUERTE · server de vara en {_SERVER.name}")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 · SIN SUSCRIPTOR, EL DUEÑO ES EL DE ANTES DE R1")
D._reset_para_tests()
d = D.actual()
ok(d._suscriptores == [], "arranca sin suscriptores")
p = d.pedir("vara", spec=_spec(), motivo="sin-suscriptor")
pid = p.pids[0]
p.soltar()
d.apagar_entidad("vara", motivo="limpieza")
ok(d._pendientes == [], "sin suscriptor no se encola NADA (cero costo, cero cambio)")
ok(not _vivo(pid), "y el proceso murió igual que siempre")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("2 · MATAR UN HIJO A MANO PRODUCE **UN** EVENTO")
D._reset_para_tests()
d = D.actual()
vistos: list = []
d.suscribir(vistos.append)

p = d.pedir("vara", spec=_spec(), motivo="prueba")
clave, pid, t0 = p.clave, p.pids[0], time.time()
time.sleep(0.4)
os.kill(pid, signal.SIGKILL)
# el push llega por el EOF del pipe de stderr; se le da un momento al hilo drenador
for _ in range(50):
    if vistos:
        break
    time.sleep(0.1)

ok(len(vistos) == 1, f"salió UN evento (salieron {len(vistos)})")
ev = vistos[0] if vistos else {}
ok(ev.get("clave") == clave, "la clave es la correcta", f"{ev.get('clave')!r} vs {clave!r}")
ok(ev.get("entity_id") == "vara", "trae entity_id")
ok(ev.get("huella") and len(ev["huella"]) == 12, f"trae la huella ({ev.get('huella')})")
ok(bool(ev.get("stderr")), "el stderr NO viene vacío (es lo que hace útil la traza)",
   f"stderr={ev.get('stderr')!r}")
ok("server_vara arrancando" in (ev.get("stderr") or ""),
   "…y es el stderr DE ESE hijo")
ok(ev.get("murio_por_eof") is True, "murio_por_eof=True")
ok(isinstance(ev.get("t_eof"), float), "trae el INSTANTE del EOF")
v = ev.get("vivio_s")
ok(isinstance(v, float) and 0.3 <= v <= 15.0, f"vivio_s coherente ({v} s)")
ok(ev.get("exit_code") is None and ev.get("exit_code_fuente"),
   "exit_code=None Y con su motivo declarado (no se inventa un cero)")
ok(pid in (ev.get("pids") or []), "trae los pids anotados")
d.apagar_entidad("vara", motivo="limpieza")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("3 · UNA MUERTE **SIN QUE NADIE PIDA** — lo que hoy no pasaba")
D._reset_para_tests()
d = D.actual()
vistos = []
d.suscribir(vistos.append)
p = d.pedir("vara", spec=_spec(), motivo="prueba")
pid = p.pids[0]
p.soltar()                                   # NADIE la tiene prestada y NADIE va a pedir
os.kill(pid, signal.SIGKILL)
for _ in range(50):
    if vistos:
        break
    time.sleep(0.1)
ok(len(vistos) >= 1, "el dueño se enteró SIN que nadie pidiera nada",
   f"eventos={len(vistos)}")
ok(vistos and vistos[0]["disparador"] in ("EOF", "VIGIA"),
   f"y el disparador lo dice: {vistos[0]['disparador'] if vistos else '—'}")
ok(d.estado()["eventos"]["muertes_avisadas"] >= 1,
   "queda contado en `estado()['eventos']['muertes_avisadas']`")
# la red de seguridad: el vigía no duplica lo que el push ya avisó
antes = len(vistos)
d._vigilar()
ok(len(vistos) == antes, "el vigía NO duplica lo que el push ya avisó")
d.apagar_entidad("vara", motivo="limpieza")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("4 · LA TRAMPA DEL FANTASMA · el timeout queda anotado con quién y cuál reloj")
D._reset_para_tests()
d = D.actual()
vistos = []
d.suscribir(vistos.append)
RELOJ = 1.5                                  # el mismo mecanismo que 30 s y 45 s, en chico
p = d.pedir("fantasma", spec=_spec("colgar", rpc_timeout=RELOJ), motivo="prueba")
t0 = time.monotonic()
r = p.call_tool("eco", {})                   # el server duerme: el reloj TIENE que vencer
tardo = time.monotonic() - t0
print(f"      la llamada tardó {tardo:.2f} s con un reloj de {RELOJ} s")
ok(tardo >= RELOJ * 0.9, "la llamada esperó al reloj (no falló por otra cosa)")
diag = p.diagnostico()
ts = diag.get("timeouts") or []
ok(len(ts) >= 1, f"quedó anotado el disparo ({len(ts)})")
t = ts[-1] if ts else {}
ok(t.get("quien") == "fantasma", f"QUIÉN: {t.get('quien')!r}")
ok(t.get("timeout_s") == RELOJ, f"CUÁL RELOJ: {t.get('timeout_s')} s")
ok(isinstance(t.get("ts"), float), "CUÁNDO: timestamp")
ok(t.get("vencio_el_reloj") is True, "y dice que venció el reloj, no que falló distinto")
ok(t.get("operacion", "").startswith("call_tool:"), f"y en qué operación: {t.get('operacion')}")
pid = p.pids[0]
p.soltar()
os.kill(pid, signal.SIGKILL)                 # ahora sí se muere, DESPUÉS del timeout
for _ in range(50):
    if vistos:
        break
    time.sleep(0.1)
ok(vistos and (vistos[0].get("timeouts") or []),
   "EL EVENTO DE MUERTE LLEVA LOS TIMEOUTS ENCIMA — se puede decir cuál de los dos fue",
   f"timeouts en el evento: {len(vistos[0].get('timeouts') or []) if vistos else 0}")
if vistos and vistos[0].get("timeouts"):
    ult = vistos[0]["timeouts"][-1]
    eof = vistos[0].get("t_eof") or 0
    print(f"      timeout a los {ult['ts']:.3f} · EOF a los {eof:.3f} · "
          f"Δ = {eof - ult['ts']:.2f} s")
    ok(eof >= ult["ts"], "y el EOF es POSTERIOR al timeout: la correlación se puede leer")
ok(vistos and vistos[0].get("rpc_timeout_s") == RELOJ,
   "el evento dice con qué reloj corría esa conexión")
d.apagar_entidad("fantasma", motivo="limpieza")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("5 · UN SOLO EVENTO AUNQUE LA MUERTE LLEGUE POR DOS CAMINOS")
D._reset_para_tests()
d = D.actual()
vistos = []
d.suscribir(vistos.append)
p = d.pedir("vara", spec=_spec(), motivo="prueba")
pid = p.pids[0]
p.soltar()
os.kill(pid, signal.SIGKILL)
for _ in range(50):
    if vistos:
        break
    time.sleep(0.1)
n_push = len(vistos)
d._vigilar()                                 # camino 2
try:
    p2 = d.pedir("vara", spec=_spec(), motivo="otra vez")   # camino 3: reconnect-once
    p2.soltar()
    d.apagar_entidad("vara", motivo="limpieza")
except Exception:                                          # noqa: BLE001
    pass
muertes_de_esa = [e for e in vistos if e["entity_id"] == "vara"
                  and e["disparador"] in ("EOF", "VIGIA", "R1")]
ok(n_push == 1 and len(muertes_de_esa) == 1,
   f"UNA sola muerte anunciada para esa conexión (fueron {len(muertes_de_esa)})",
   f"disparadores: {[e['disparador'] for e in muertes_de_esa]}")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("6 · EL SUSCRIPTOR SE LLAMA FUERA DEL LOCK")
D._reset_para_tests()
d = D.actual()
tenia_lock: list = []


def _mirar(ev):
    # Si esto corriera CON el lock tomado, `_lock` sería un RLock ya adquirido por ESTE
    # hilo y `acquire(blocking=False)` daría True igual (es reentrante). Lo que se prueba
    # es lo que de verdad importa: que desde el suscriptor se pueda PEDIR sin colgarse.
    p2 = d.pedir("reentrante", spec=_spec(), motivo="desde el suscriptor")
    tenia_lock.append(bool(p2.pids))
    p2.soltar()


d.suscribir(_mirar)
p = d.pedir("vara", spec=_spec(), motivo="prueba")
pid = p.pids[0]
p.soltar()
os.kill(pid, signal.SIGKILL)
for _ in range(60):
    if tenia_lock:
        break
    time.sleep(0.1)
ok(tenia_lock and tenia_lock[0],
   "el suscriptor pudo llamar a `pedir()` sin colgarse (entrega fuera del lock)")
d.apagar_todo(motivo="limpieza")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("7 · UN SUSCRIPTOR QUE EXPLOTA NO TUMBA AL DUEÑO")
D._reset_para_tests()
d = D.actual()
buenos: list = []


def _explota(ev):
    raise RuntimeError("boom a propósito")


d.suscribir(_explota)
d.suscribir(buenos.append)
p = d.pedir("vara", spec=_spec(), motivo="prueba")
pid = p.pids[0]
p.soltar()
os.kill(pid, signal.SIGKILL)
for _ in range(50):
    if buenos:
        break
    time.sleep(0.1)
ok(len(buenos) == 1, "el otro suscriptor recibió su evento igual")
ok(d.pedir("vara", spec=_spec(), motivo="sigue viva").pids != [],
   "y el dueño sigue funcionando después del suscriptor roto")
d.apagar_todo(motivo="fin de la vara")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("8 · CERO HUÉRFANOS")
vivos = [pid for pid in
         [int(l.split(None, 1)[0]) for l in
          subprocess.run(["ps", "-eo", "pid=,command="], capture_output=True,
                         text=True).stdout.splitlines()
          if "server_vara.py" in l]]
ok(not vivos, f"no queda ningún server de la vara vivo", f"quedaron {vivos}")
ok(not D.actual().estado()["vivas"], "y la tabla del dueño queda vacía")

print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
sys.exit(0 if _fallos == 0 else 1)
