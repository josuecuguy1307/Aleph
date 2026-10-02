#!/usr/bin/env python3
"""verify_sesion_dueno.py — D5 · LA SESIÓN VIVA LE PIDE AL DUEÑO.

El paso 4 del §7 del diseño, el último consumidor. Lo que tiene que quedar cierto:

  1. con `ALEPH_DUENO=on` la Sesión NO spawnea: pide. Sin la perilla, spawnea como siempre,
     y el belt queda IGUAL por los dos caminos (la regla madre de toda la migración);
  2. `close()` **suelta, no mata**: si otro la tiene prestada, el proceso sigue vivo — que es
     el objetivo textual del §7 paso 4 («al cerrar no mata una conexión que otro tiene
     prestada»);
  3. la **LÁPIDA** manda por encima del refcount: desconectar mata aunque esté prestada, y la
     Sesión **se entera EN LA LLAMADA** (string `[MCP error: …]`, no una excepción que tumbe
     el loop);
  4. si el boot explota a mitad, lo ya arrancado se SUELTA (si no, quedan prestados para
     siempre y el cosechador no los toca);
  5. gate sobre SPAWNS **por pieza**: la segunda Sesión con la misma huella no paga spawn;
  6. cero huérfanos por `ps` al final.

    product/backend/.venv/bin/python platform/inspection/verify_sesion_dueno.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "platform/inspection",
           _RAIZ / "platform/assembler", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("ALEPH_ROLE", "client")

import aleph_paths                                          # noqa: E402
import dueno as D                                           # noqa: E402

S = aleph_paths.load_module_by_path(
    "sesion_vara_d5", _RAIZ / "platform/assembler/session.py")

_fallos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f" — {detalle}" if detalle else ""))


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 72 - len(t)))


def _pids_vivos() -> set:
    """Los pids de echo_server.py vivos AHORA. `Popen` y no `os.system`: `ps` es hijo
    nuestro y saldría en su propia salida (trampa 4 del acta)."""
    out = subprocess.run(["ps", "-eo", "pid=,command="], capture_output=True, text=True).stdout
    fuera = set()
    for linea in out.splitlines():
        if "echo_server.py" in linea and "verify_sesion" not in linea:
            try:
                fuera.add(int(linea.split(None, 1)[0]))
            except ValueError:
                pass
    return fuera


_TMP = Path(tempfile.mkdtemp(prefix="vara-d5-"))
_BELT = _TMP / "belt-echo.mcp.json"
_BELT.write_text(json.dumps({"mcpServers": {"echo": {
    "command": sys.executable,
    "args": [str(_RAIZ / "platform/assembler/fixtures/echo_server.py")],
}}}), encoding="utf-8")

_CFG = {"belt_path": str(_BELT)}


def _sesion(**kw):
    return S.Session(dict(_CFG), repo_root=_RAIZ, workdir=_TMP / f"w{len(list(_TMP.iterdir()))}",
                     **kw)


print(f"LA SESIÓN VIVA LE PIDE AL DUEÑO · belt={_BELT.name}")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 · EL MISMO BELT CON DUEÑO Y SIN DUEÑO")
os.environ.pop("ALEPH_DUENO", None)
s_sin = _sesion()
s_sin._boot()
tools_sin = sorted(s_sin._registry.tool_names())
clase_sin = type(s_sin._servers[0]).__name__
s_sin.close()

os.environ["ALEPH_DUENO"] = "on"
D._reset_para_tests()
s_con = _sesion(user_id="u-vara")
s_con._boot()
tools_con = sorted(s_con._registry.tool_names())
clase_con = type(s_con._servers[0]).__name__
print(f"      sin dueño: {clase_sin:<22} tools={tools_sin}")
print(f"      con dueño: {clase_con:<22} tools={tools_con}")
ok(tools_sin == tools_con, "MISMAS tools por los dos caminos (la regla madre)")
ok(clase_con == "ServidorPrestado", "con la perilla, la Sesión PIDE (no spawnea)",
   f"clase={clase_con}")
ok(clase_sin != "ServidorPrestado", "sin la perilla, spawnea como siempre",
   f"clase={clase_sin}")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("2 · close() SUELTA, NO MATA (§7 paso 4)")
# Un segundo pedido de la MISMA huella: mismo proceso, refcount 2.
otra = D.actual().pedir("echo", spec=dict(s_con._servers[0]._spec),
                        user_id="u-vara", motivo="otro agente")
vivas = D.actual().estado()["vivas"]
ok(len(vivas) == 1, f"un solo proceso para los dos pedidos (vivas={len(vivas)})")
ok(vivas[0]["refcount"] == 2, f"refcount 2 (el de la Sesión + el del otro)",
   f"refcount={vivas[0].get('refcount')}")
pids_antes = set(otra.pids)
s_con.close()                                   # la Sesión cierra…
est = D.actual().estado()
ok(len(est["vivas"]) == 1, "…y el proceso SIGUE VIVO: otro lo tiene prestado")
ok(est["vivas"][0]["refcount"] == 1, "refcount bajó a 1, no a 0")
ok(pids_antes and pids_antes.issubset(_pids_vivos()),
   f"los pids siguen ahí de verdad ({sorted(pids_antes)})")
ok(otra.call_tool("echo", {"text": "sigo vivo"}) is not None,
   "y el otro puede seguir usándola después de que la Sesión cerró")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("3 · LA LÁPIDA MATA AUNQUE ESTÉ PRESTADA · y se entera EN LA LLAMADA")
s2 = _sesion(user_id="u-vara")
s2._boot()
srv = s2._servers[0]
ok(srv.call_tool("echo", {"text": "hola"}).find("MCP error") == -1,
   "antes de la lápida, la tool responde normal")
pids_lapida = set(D.actual().estado()["vivas"][0]["pids"])
n = D.actual().apagar_entidad("echo", user_id="u-vara", motivo="lápida del usuario")
ok(n >= 1, f"la lápida apagó {n} conexión(es) AUNQUE estaban prestadas (refcount>0)")
ok(not (pids_lapida & _pids_vivos()),
   f"los procesos murieron de verdad ({sorted(pids_lapida)})")
r = srv.call_tool("echo", {"text": "y ahora?"})
ok(isinstance(r, str) and r.startswith("[MCP error:"),
   "la Sesión se entera EN LA LLAMADA, con el string que el loop sabe leer",
   f"devolvió {r!r}")
ok("DuenoError" in r or "no está viva" in r,
   "y el motivo viaja adentro (no un error mudo)", f"devolvió {r!r}")
s2.close()                                      # cerrar después de la lápida no rompe
ok(True, "close() después de la lápida es idempotente y no levanta")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("4 · UN BOOT QUE EXPLOTA NO DEJA PRÉSTAMOS COLGADOS")
D._reset_para_tests()
s3 = _sesion(user_id="u-vara")
_orig = S._SessionRegistry
try:
    def _explota(*a, **k):
        raise RuntimeError("boom a propósito: el registry no se pudo armar")
    S._SessionRegistry = _explota
    try:
        s3._boot()
        ok(False, "el boot tenía que levantar")
    except RuntimeError as e:
        ok("boom a propósito" in str(e), "el boot levantó, como se pidió")
finally:
    S._SessionRegistry = _orig
est = D.actual().estado()
prestadas = [v for v in est["vivas"] if v["refcount"] > 0]
ok(not prestadas,
   "NADA quedó prestado: lo que arrancó antes del error se soltó",
   f"quedaron {[(v['entity_id'], v['refcount']) for v in prestadas]}")
ok(s3._servers == [] and s3._registry is None,
   "y la Sesión no quedó con punteros a servers que no puede soltar")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("5 · GATE POR PIEZA · la segunda Sesión no paga spawn")
D.actual().apagar_todo(motivo="antes de medir")
D._reset_para_tests()
sp0 = D.actual().estado()["eventos"]["spawns"]
sA = _sesion(user_id="u-gate")
sA._boot()
sp_A = D.actual().estado()["eventos"]["spawns"] - sp0
hA = {s.name: s._prestamo.clave.rsplit("|", 1)[-1] for s in sA._servers}
sB = _sesion(user_id="u-gate")                  # MISMO usuario, MISMO belt
sB._boot()
sp_B = D.actual().estado()["eventos"]["spawns"] - sp0 - sp_A
hB = {s.name: s._prestamo.clave.rsplit("|", 1)[-1] for s in sB._servers}
print(f"      {'pieza':<10} {'h(sesión A)':<14} {'h(sesión B)':<14} reusó")
for n_ in sorted(hA):
    print(f"      {n_:<10} {hA[n_]:<14} {hB.get(n_, '—'):<14} "
          f"{'SÍ' if hA[n_] == hB.get(n_) else 'no'}")
print(f"      spawns: sesión A = {sp_A} · sesión B = {sp_B}")
ok(sp_A >= 1, "la primera Sesión sí paga el spawn")
ok(sp_B == 0 and hA == hB,
   "la SEGUNDA Sesión del mismo usuario REUSA: cero spawns, misma huella",
   f"spawns={sp_B} huellas A={hA} B={hB}")

# y dos usuarios DISTINTOS no comparten, que es la otra mitad
sC = _sesion(user_id="u-otro")
sC._boot()
hC = {s.name: s._prestamo.clave.rsplit("|", 1)[-1] for s in sC._servers}
claves = {v["entity_id"] + "|" + str(v["refcount"]) for v in D.actual().estado()["vivas"]}
ok(len(D.actual().estado()["vivas"]) == 2,
   "otro USUARIO levanta su propio proceso (la clave lleva el user_id)",
   f"vivas={len(D.actual().estado()['vivas'])} · {claves}")
ok(hC == hA, "…con la misma HUELLA (lo que separa es el usuario, no la receta)")
for s_ in (sA, sB, sC):
    s_.close()

# ══════════════════════════════════════════════════════════════════════════════════
seccion("6 · CERO HUÉRFANOS")
antes = _pids_vivos()
n = D.actual().apagar_todo(motivo="fin de la vara")
ok(not _pids_vivos(), f"apagadas {n}; no queda NINGÚN echo_server vivo (evidencia ps)",
   f"quedaron {sorted(_pids_vivos())}")
ok(not D.actual().estado()["vivas"], "y la tabla del dueño queda vacía")

print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
sys.exit(0 if _fallos == 0 else 1)
