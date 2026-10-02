#!/usr/bin/env python3
"""verify_repair_e2e.py — R5 · EL CICLO COMPLETO, CON UN SERVER ROTO DE VERDAD.

El cierre de repair. Con la perilla encendida y procesos reales, se recorre el ciclo entero
y se deja **evidencia por paso**:

    el dueño DETECTA  →  R2 CLASIFICA  →  R3 DECIDE  →  R4/R5 ACTÚAN o ESCALAN

Tres corridas, cada una con su server:

  A · TEMPORAL      muere y revive        → se arregla CALLADO, sin card ni botón
  B · AUTO-AJUSTE   `servidor_incompatible` con versión buena conocida
                    → repair CORRIGE LA RECETA SOLO y queda la nota del [?]
  C · ESCALADA      el mismo, sin versión buena → card + traza, y la traza NO filtra la llave

Y la **trampa del fantasma** (§6) revisada en cada muerte: si el cierre-solo aparece, la
traza tiene que nombrarlo — instante del EOF, cuánto vivió, y si hubo un timeout antes y de
cuál de los dos relojes.

    product/backend/.venv/bin/python platform/inspection/verify_repair_e2e.py
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
           _RAIZ / "platform/gates", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("ALEPH_ROLE", "client")
os.environ["ALEPH_DUENO"] = "on"
os.environ["ALEPH_REPAIR"] = "on"
os.environ["ALEPH_REPAIR_BASE_S"] = "0.05"     # la curva ya la prueba test_repair.py

import dueno as D                                           # noqa: E402
import repair as R                                          # noqa: E402
import repair_clasificar as RC                              # noqa: E402

_fallos = 0
_muertes: list = []


def _reloj():
    time.sleep(240)
    print("\n⛔ EL E2E SE COLGÓ (240 s).", flush=True)
    os._exit(9)


threading.Thread(target=_reloj, daemon=True).start()


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f" — {detalle}" if detalle else ""))


def paso(n, t):
    print(f"\n  ▸ paso {n} · {t}")


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 72 - len(t)))


_SERVER = _AQUI / "fixtures_vara_r1_server.py"


def _spec(modo="normal", rpc_timeout=30.0):
    return {"command": sys.executable, "args": [str(_SERVER)],
            "env": dict(os.environ, ALEPH_VARA_MODO=modo),
            "cwd": None, "rpc_timeout": rpc_timeout}


def _vivos():
    out = subprocess.run(["ps", "-eo", "pid=,command="], capture_output=True, text=True).stdout
    return [int(l.split(None, 1)[0]) for l in out.splitlines()
            if "fixtures_vara_r1_server.py" in l and "verify_repair" not in l]


class _RegistroFalso:
    """El registro, en memoria. El E2E NO toca `aleph.db`: la vara mide el ciclo, no le
    reescribe la receta al usuario."""

    def __init__(self, version=None):
        self.filas = {"e2e": {"entity_id": "e2e", "command": "npx",
                              "args": ["-y", "@fixture/paquete"],
                              "server_info": ({"version": version} if version else None)}}
        self.escrituras = []

    def leer(self, user_id, entity_id):
        f = self.filas.get(entity_id)
        return dict(f) if f else None

    def escribir(self, user_id, entity_id, args, nota):
        self.escrituras.append({"entity_id": entity_id, "args": list(args), "nota": dict(nota)})
        self.filas[entity_id]["args"] = list(args)


def _enganchar(reg=None):
    D._reset_para_tests()
    rp = R._reset_para_tests()
    d = D.actual()
    d.suscribir(lambda ev: (_muertes.append(ev), rp.observar(ev))[1])
    d.poner_guardia(rp.permitir)
    if reg is not None:
        rp.poner_ganchos_de_receta(reg.leer, reg.escribir)
    return d, rp


def _esperar(rp, n=1, seg=8.0):
    t0 = time.time()
    while time.time() - t0 < seg:
        if rp.estado()["eventos"]["observadas"] >= n:
            return True
        time.sleep(0.05)
    return False


print("R5 · EL CICLO COMPLETO DE REPAIR, EXTREMO A EXTREMO")
ok(R.encendido() and D.encendido(), "las dos perillas encendidas para esta corrida")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("A · TEMPORAL · muere y revive, se arregla CALLADO")
d, rp = _enganchar()

paso(1, "el dueño DETECTA")
p = d.pedir("e2e", spec=_spec(), motivo="e2e")
pid1 = p.pids[0]
p.soltar()
os.kill(pid1, signal.SIGKILL)
ok(_esperar(rp), f"muerte detectada del pid {pid1}")
ev = _muertes[-1]
print(f"      evidencia: disparador={ev['disparador']} · vivio_s={ev['vivio_s']} · "
      f"stderr={len(ev['stderr'])}B · t_eof={'sí' if ev.get('t_eof') else 'no'}")

paso(2, "R2 CLASIFICA")
v = RC.clasificar_muerte(ev)
ok(v.es_temporal, f"clasificada TEMPORAL · {v.razon}")
print(f"      evidencia: causa={v.causa} · desempate={v.desempate} · señales={v.señales}")

paso(3, "R3 DECIDE")
est = rp.estado()
ok(est["eventos"]["temporales"] >= 1, "repair abrió ciclo temporal")
ok(est["eventos"]["permanentes"] == 0, "sin permanentes: no hay botón que mostrar")

paso(4, "el siguiente pedido PASA — se arregló solo")
p2 = d.pedir("e2e", spec=_spec(), motivo="e2e otra vez")
ok(p2.pids and p2.pids[0] != pid1, f"proceso nuevo (pid {p2.pids[0] if p2.pids else '—'})")
ok(p2.call_tool("echo", {"text": "anda"}) == "anda", "y contesta")
ok(rp.escalacion_de(None, "e2e") is None, "CERO escaladas: el usuario no vio nada")
ok(rp.nota_de_ajuste(None, "e2e") is None, "y cero notas: no se tocó ninguna receta")
p2.soltar()
d.apagar_todo(motivo="fin A")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("B · AUTO-AJUSTE · la receta es territorio de Aleph")
reg = _RegistroFalso(version="1.4.0")
d, rp = _enganchar(reg)

paso(1, "un server que revienta como `servidor_incompatible`")
try:
    pr = d.pedir("e2e", spec=_spec("incompatible"), motivo="e2e")
    pid = pr.pids[0] if pr.pids else None
    pr.call_tool("echo", {"text": "x"})              # acá se mata solo
    pr.soltar()
except D.DuenoError:
    pid = None
_esperar(rp, seg=6.0)
ok(bool(_muertes), "el dueño detectó la muerte")
ev = _muertes[-1]
print(f"      evidencia: stderr={ev['stderr'][:60]!r}…")

paso(2, "R2 lo tipa, R5 CORRIGE LA RECETA SOLO")
# el veredicto del transporte no tipa la causa: la pone quien mide. Se inyecta como lo haría
# el verificador, que es el que corre `diagnostico_conectores`.
rp.observar(dict(ev, causa="servidor_incompatible"))
ok(len(reg.escrituras) == 1, f"repair corrigió la receta ({len(reg.escrituras)} escritura)")
if reg.escrituras:
    e = reg.escrituras[0]
    print(f"      evidencia: args → {e['args']} · nota: {e['nota']['de']} → {e['nota']['a']}")
    ok(e["args"] == ["-y", "@fixture/paquete@1.4.0"], "pineó a la última versión que anduvo")
    ok(set(e) == {"entity_id", "args", "nota"}, "sólo args + nota: nada más se tocó")

paso(3, "el usuario NO ve card ni botón")
ok(rp.escalacion_de(None, "e2e") is None, "cero escaladas: se arregló sin trámite")
nota = rp.nota_de_ajuste(None, "e2e")
ok(nota and nota["a"] == "1.4.0", f"y queda la nota del [?]: {nota}")

paso(4, "UN intento, sin loops")
rp.observar(dict(ev, causa="servidor_incompatible", clave="-|e2e|otra"))
ok(len(reg.escrituras) == 1, f"no volvió a ajustar ({len(reg.escrituras)})")
ok(rp.escalacion_de(None, "e2e") is not None, "la segunda vez ESCALA, no reajusta")
d.apagar_todo(motivo="fin B")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("C · ESCALADA · cuando el ajuste no alcanza")
reg2 = _RegistroFalso(version=None)            # sin versión buena conocida
d, rp = _enganchar(reg2)
_LLAVE = "sk-ant-api03-" + "Q" * 40

paso(1, "la misma rotura, pero sin a qué versión volver")
rp.observar({"clave": "-|e2e|h", "user_id": None, "entity_id": "e2e",
             "disparador": "EOF", "murio_por_eof": True, "causa": "servidor_incompatible",
             "stderr": f"ANTHROPIC_API_KEY={_LLAVE}\nModuleNotFoundError: falta",
             "exit_code": None, "exit_code_fuente": "no expuesto: stdio_client",
             "vivio_s": 0.31, "timeouts": [], "rpc_timeout_s": 30.0})
ok(reg2.escrituras == [], "NO tocó la receta: no hay a qué volver")

paso(2, "escala con la traza completa")
esc = rp.escalacion_de(None, "e2e")
ok(esc is not None, "hay escalada")
if esc:
    print(f"      por qué empezó : {esc['por_que_empezo'][:64]}")
    print(f"      por qué paró   : {esc['por_que_paro'][:64]}")
    print(f"      ajuste         : intentado={esc['ajuste_automatico']['intentado']} "
          f"aplicado={esc['ajuste_automatico']['aplicado']}")
    print(f"      crudo          : vivio_s={esc['crudo']['vivio_s']} · "
          f"exit_code={esc['crudo']['exit_code']} ({esc['crudo']['exit_code_fuente'][:28]}…)")
    ok(esc["boton"] is None or esc["clase"] == RC.PERMANENTE,
       "es un permanente sin botón: cuando el usuario lo ve, ya se probó lo que se podía")

paso(3, "la traza NO filtra la llave")
limpio = esc["crudo"]["stderr"] if esc else ""
ok(isinstance(limpio, str), f"el stderr es texto ({type(limpio).__name__})")
ok(_LLAVE not in str(esc), "la llave NO está en la traza")
ok("ModuleNotFoundError" in limpio, "y la traza sigue sirviendo para diagnosticar")
print(f"      scrubber: {esc['crudo'].get('scrubber')}")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("D · LA TRAMPA DEL FANTASMA (§6), revisada sobre estas corridas")
# El histograma de `vivio_s` de TODAS las muertes de este E2E. Lo que se busca: un pico en
# 30-45 s señalaría uno de NUESTROS relojes (rpc 30 s · sonda 45 s); disperso y corto señala
# al server. Es la instrumentación que el §6.3 pedía, sobre datos reales.
vs = sorted(round(float(m.get("vivio_s") or 0), 3) for m in _muertes)
con_timeout = [m for m in _muertes if (m.get("timeouts") or [])]
print(f"      muertes observadas : {len(_muertes)}")
print(f"      vivio_s            : {vs}")
print(f"      con timeout previo : {len(con_timeout)}")
sospechosas = [v for v in vs if 30.0 <= v <= 45.0]
# ⚠️ `t_eof` SÓLO EXISTE PARA LAS MUERTES POR EOF, y eso es correcto: una conexión que el
# dueño CIERRA estando viva (fin de sesión, lápida, ociosidad) todavía no murió sola, así
# que no hay instante de EOF que anotar. La primera versión de esta vara lo exigía para
# TODAS y se ponía roja por un cierre limpio — pedirle a un cierre ordenado el timestamp de
# una muerte que no ocurrió.
_por_eof = [m for m in _muertes if m.get("disparador") in ("EOF", "VIGIA")]
_cerradas = [m for m in _muertes if m.get("disparador") not in ("EOF", "VIGIA")]
print(f"      por EOF/vigía      : {len(_por_eof)} · cerradas por el dueño: {len(_cerradas)}")
ok(_por_eof and all(m.get("t_eof") for m in _por_eof),
   f"toda muerte POR EOF trae su instante ({len(_por_eof)}) — sin eso no hay correlación")
ok(all(m.get("t_eof") is None for m in _cerradas),
   "y un cierre ordenado NO inventa un instante de muerte que no ocurrió")
ok(all("vivio_s" in m for m in _muertes), "todas traen cuánto vivió")
if sospechosas:
    print(f"      ⚠️ {len(sospechosas)} muerte(s) en la ventana 30-45 s: "
          f"{sospechosas} — REVISAR, coincide con rpc_timeout(30) / sonda(45)")
    for m in _muertes:
        if 30.0 <= float(m.get("vivio_s") or 0) <= 45.0:
            print(f"         {m['entity_id']} · timeouts={m.get('timeouts')} · "
                  f"rpc_timeout_s={m.get('rpc_timeout_s')}")
else:
    print("      sin muertes en la ventana 30-45 s: el fantasma NO apareció en esta corrida")
ok(True, "el fantasma quedaría NOMBRADO si apareciera (histograma + timeouts + t_eof)")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("E · CERO HUÉRFANOS")
D.actual().apagar_todo(motivo="fin del E2E")
ok(not _vivos(), "no queda ningún server de la vara vivo", f"quedaron {_vivos()}")
ok(not D.actual().estado()["vivas"], "y la tabla del dueño queda vacía")

print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
sys.exit(0 if _fallos == 0 else 1)
