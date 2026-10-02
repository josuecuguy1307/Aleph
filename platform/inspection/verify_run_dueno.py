#!/usr/bin/env python3
"""verify_run_dueno.py — EL RUN LE PIDE AL DUEÑO (D4).

Lo que esta vara mide, en orden de consecuencia:

  1. el pool del run da EL MISMO `parte()` con el dueño encendido y apagado;
  2. el préstamo se devuelve en TODOS los caminos de salida — incluido el error;
  3. la LÁPIDA se respeta durante el run: una entidad apagada no se levanta, y apagarla con
     el run vivo le mata la conexión aunque esté prestada;
  4. cero huérfanos;
  5. **y el gate del §6: cuántos SPAWNS paga el run sobre un cinturón ya calentado.**
     El gate son los spawns, nunca el reloj — la lección de D3.

⚠️ EL PUNTO 5 ES EL QUE NO DA LO ESPERADO, Y ESTA VARA LO DICE EN VOZ ALTA en vez de
adornarlo. Ver la sección 5.

    product/backend/.venv/bin/python platform/inspection/verify_run_dueno.py
"""
from __future__ import annotations

import json
import os
import sys
import time
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

RA = aleph_paths.load_module_by_path(
    "ra_vara_run", _RAIZ / "platform/assembler/recipe_assembler.py")
R = aleph_paths.load_module_by_path(
    "restaurador_vara_run", _RAIZ / "platform/assembler/restaurador.py")

#: Piezas reales del registro: dos que arrancan y una que no.
PIEZAS = ["sqlite", "fetch", "time"]

_fallos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f" — {detalle}" if detalle else ""))


_bloqueos = 0


def bloqueo(t):
    """Un objetivo QUE NO SE ALCANZA por una decisión pendiente, no por algo roto.

    No cuenta como fallo —nada regresionó— pero se grita. Un gate que no puede ponerse
    verde hasta que alguien tome una decisión de producto se vuelve una vara que se ignora,
    y una vara ignorada es peor que no tenerla."""
    global _bloqueos
    _bloqueos += 1
    print(f"  ⛔ {t}")


def nota(t):
    print(f"  · {t}")


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 72 - len(t)))


def _limpiar():
    for n in list(sys.modules):
        if n.split(".")[0] in {"transporte", "transporte_sdk", "byo_mcp", "traductor_errores"}:
            sys.modules.pop(n, None)


def _contexto():
    from app.phase1 import conexiones_repo as CR            # noqa: E402
    from app.phase1 import repo                             # noqa: E402
    conn = repo.get_conn()
    try:
        with conn.cursor() as cur:
            # EL DUEÑO DEL REGISTRO ES EL QUE TIENE CONEXIONES, no el que tiene una llave.
            # Antes era `SELECT user_id FROM keys LIMIT 1`, y eso se rompió apenas la tabla
            # `keys` juntó usuarios de PRUEBA: las propias varas crean varios con llave
            # propia (broker-test-a/b, zotero-inject-a, cowork-approve-test), así que el
            # `LIMIT 1` sin orden devolvía cualquiera. Con un usuario de prueba, `filas`
            # sale vacío, el pool arranca 0 piezas y la vara moría en `piezas[0]` con un
            # IndexError — que además NO es un veredicto: es la vara sin poder medir.
            cur.execute("SELECT user_id FROM conexiones GROUP BY user_id "
                        "ORDER BY COUNT(*) DESC, user_id LIMIT 1")
            fila = cur.fetchone()
        if not fila:
            raise SystemExit("no hay ningún usuario con conexiones en el registro: "
                             "esta vara mide el pool de un run real y no tiene qué medir.")
        owner = fila[0]
        filas = {e["entity_id"]: e for e in CR.listar_entidades(conn, owner)}
    finally:
        conn.close()
    if not any(n in filas for n in PIEZAS):
        raise SystemExit(f"el usuario {owner[:8]}… no tiene ninguna de {PIEZAS} equipada.")
    return owner, filas, CR


def _pool(owner, filas, CR, *, piezas=None, base_env=None):
    """Levanta el pool del run como lo levanta `assemble_and_run`, con el MISMO expansor."""
    presentes = [n for n in (piezas or PIEZAS) if n in filas]
    servers_raw = {n: {"command": filas[n].get("command") or "",
                       "args": list(filas[n].get("args") or [])} for n in presentes}
    env = base_env if base_env is not None else RA._puppet_run_env(
        str(aleph_paths.resource_root()), dict(os.environ))
    res = R.restaurar_servers(
        servers_raw, env,
        expandir=RA._expand_server_cfg,
        mcp_server_cls=RA._servidor_stdio(owner),
        leer_entidad=lambda n: filas.get(n),
        env_efectivo=CR.env_efectivo,
    )
    return res, presentes


def _resumen(res):
    p = res.parte()
    return {k: p.get(k) for k in ("total", "arrancadas", "caidas")}


def _apagar_pool(res):
    for pieza in res.piezas:
        if pieza.servidor is not None:
            try:
                pieza.servidor.stop()
            except Exception:                               # noqa: BLE001
                pass


def _vivos_de(res):
    fuera = []
    for pieza in res.piezas:
        srv = pieza.servidor
        pr = getattr(srv, "_prestamo", None)
        if pr is not None:
            fuera += list(pr.pids)
    return fuera


owner, filas, CR = _contexto()
print(f"EL RUN LE PIDE AL DUEÑO · owner={owner[:8]}… · piezas={PIEZAS}")


# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 · EL POOL DA EL MISMO PARTE CON DUEÑO Y SIN DUEÑO")
os.environ.pop("ALEPH_DUENO", None)
_limpiar()
res_sin, presentes = _pool(owner, filas, CR)
r_sin = _resumen(res_sin)
_apagar_pool(res_sin)

os.environ["ALEPH_DUENO"] = "on"
_limpiar()
D._reset_para_tests()
res_con, _ = _pool(owner, filas, CR)
r_con = _resumen(res_con)
print(f"      sin dueño  {json.dumps(r_sin, ensure_ascii=False)}")
print(f"      con dueño  {json.dumps(r_con, ensure_ascii=False)}")
ok(r_sin == r_con, "MISMO `parte()`: mismas arrancadas, mismas caídas")
# El adaptador vive en el dueño (`dueno.ServidorPrestado`) desde D5: era de
# `recipe_assembler` mientras el run fue su único consumidor, y se movió al aparecer el
# segundo (la Sesión VIVA). Que haya UNO SOLO lo fija `test_frontera_dueno.py`.
ok(any(isinstance(p.servidor, D.ServidorPrestado) for p in res_con.piezas),
   "y las conexiones del run son PRÉSTAMOS del dueño, no procesos propios")
vivos_run = _vivos_de(res_con)
ok(len(vivos_run) > 0, f"el dueño tiene {len(vivos_run)} pid(s) anotados del pool")


seccion("2 · UNA PRESTADA AL RUN NO ENVEJECE NI LA EXPULSA EL LRU")
est = D.actual().estado()
prestadas = [v for v in est["vivas"] if v["refcount"] > 0]
ok(len(prestadas) == len([p for p in res_con.piezas if p.arrancado]),
   f"las {len(prestadas)} conexiones del run están PRESTADAS (refcount > 0)")
# el cosechador no las toca aunque se lo pida a mano con la ociosidad vencida
_ant = D.actual()._retencion_s
D.actual()._retencion_s = 0.001
time.sleep(0.05)
n = D.actual().cosechar()
D.actual()._retencion_s = _ant
ok(n == 0 and _vivos_de(res_con) == vivos_run,
   "con la ociosidad VENCIDA, el cosechador no cierra ninguna prestada", f"cerró {n}")
# y el techo tampoco: se fuerza a 1 y se pide otra
_tope = D.actual()._max_vivas
D.actual()._max_vivas = 1
_spec_intruso = dict(RA._puppet_run_env(str(aleph_paths.resource_root()), dict(os.environ)))
_spec_intruso["UNA_VAR_PARA_OTRA_HUELLA"] = "1"
_cmd_i, _args_i, _env_i = RA._expand_server_cfg(
    {"command": filas[presentes[0]].get("command"),
     "args": list(filas[presentes[0]].get("args") or [])}, _spec_intruso)
with D.actual().pedir("intruso", spec={"command": _cmd_i, "args": _args_i, "env": _env_i,
                                       "rpc_timeout": 30}, motivo="intruso"):
    pass
D.actual()._max_vivas = _tope
ok(_vivos_de(res_con) == vivos_run,
   "con el tope en 1, el LRU NO desalojó ninguna prestada al run (§4.3)",
   f"{_vivos_de(res_con)} vs {vivos_run}")
ok(D.actual().estado()["eventos"]["sobrecupo"] >= 1,
   "…y el techo CEDIÓ con evento de sobrecupo en vez de bloquear")


seccion("3 · EL PRÉSTAMO SE DEVUELVE EN TODOS LOS CAMINOS DE SALIDA")
_apagar_pool(res_con)
ok(all(v["refcount"] == 0 for v in D.actual().estado()["vivas"]),
   "tras el `finally` del run, ningún refcount queda colgado")
ok(_vivos_de(res_con) == vivos_run,
   "…y los procesos SIGUEN VIVOS: soltar no mata, sostiene (D2)")

# el camino del ERROR: el `finally` corre igual
_limpiar()
res_err, _ = _pool(owner, filas, CR)
refs_antes = {v["clave"]: v["refcount"] for v in D.actual().estado()["vivas"]}
try:
    try:
        raise RuntimeError("el run explotó a mitad")
    finally:
        _apagar_pool(res_err)                               # el `finally` de assemble_and_run
except RuntimeError:
    pass
ok(all(v["refcount"] == 0 for v in D.actual().estado()["vivas"]),
   "un run que EXPLOTA devuelve igual sus préstamos (refcount a 0)",
   str({v["clave"][:24]: v["refcount"] for v in D.actual().estado()["vivas"]}))
ok(any(r > 0 for r in refs_antes.values()), "…y antes del error sí estaban prestadas")

# EL POOL ESTÁ DENTRO DEL `try` — la garantía estructural, no una coincidencia
_fuente = (_RAIZ / "platform/assembler/recipe_assembler.py").read_text()
_i_try = _fuente.find("    started: list = []\n    try:")
_i_pool = _fuente.find("_restauracion = _restaurador.restaurar_servers")
_i_fin = _fuente.find("    finally:\n        for srv in started:")
ok(0 < _i_try < _i_pool < _i_fin,
   "el pool se levanta DENTRO del `try` que lo apaga (§D4), no antes")

# soltar dos veces no descuenta dos veces
_limpiar()
res_dos, _ = _pool(owner, filas, CR)
_apagar_pool(res_dos)
_apagar_pool(res_dos)
ok(all(v["refcount"] == 0 for v in D.actual().estado()["vivas"]),
   "soltar dos veces es idempotente: no deja el refcount en negativo ni cierra de más")


seccion("4 · LA LÁPIDA MANDA DURANTE EL RUN")
_limpiar()
res_lap, _ = _pool(owner, filas, CR)
viva = next((p for p in res_lap.piezas if p.arrancado), None)
ok(viva is not None, "hay una pieza viva para probar la lápida")
if viva is not None:
    pids_lap = list(viva.servidor._prestamo.pids)
    n = D.actual().apagar_entidad(viva.nombre, motivo="lápida durante el run")
    time.sleep(0.8)
    ok(n >= 1, f"apagar «{viva.nombre}» con el run VIVO cierra su conexión", str(n))
    ok([p for p in pids_lap if D._vive(p)] == [],
       "y el proceso muere de verdad, aunque estuviera prestado (§1.1)",
       str([p for p in pids_lap if D._vive(p)]))
    # el run se entera por el camino de siempre: la llamada falla, no devuelve basura
    salida = viva.servidor.call_tool("cualquiera", {})
    ok(isinstance(salida, str) and salida.startswith("[MCP error"),
       "el run se entera EN LA LLAMADA, con el string de error de siempre",
       str(salida)[:80])
_apagar_pool(res_lap)


seccion("5 · EL GATE DEL §6 · ¿el primer mensaje REUSA el cinturón calentado?")
# EL GATE ES POR PIEZA, NO UN CONTADOR GLOBAL, y el criterio no es «cero spawns».
#
# Desde §9.2 la huella mira el env DECLARADO en la receta. Con eso, una pieza que no
# depende de `PUPPET_WORKDIR` TIENE que reusarse. Una que SÍ depende no puede — y no debe:
# `sqlite` lleva `${PUPPET_WORKDIR}/…` en sus ARGS, y los args entran a la huella por su
# cuenta (no son env). Su workdir es parte de su identidad de verdad, así que dos workdirs
# son dos procesos y compartirlos sería el bug, no el objetivo.
#
# Un `sp_run == 0` global metía a las tres en la misma bolsa y no se podía poner verde
# jamás: exigía que `sqlite` compartiera proceso entre dos workdirs distintos.
D.actual().apagar_todo(motivo="antes de medir")
_limpiar()


def _huellas_de(res):
    """`{pieza: huella}` de las que consiguieron préstamo. La que no arranca no aparece."""
    fuera = {}
    for pieza in res.piezas:
        pr = getattr(pieza.servidor, "_prestamo", None)
        if pr is not None:
            fuera[pieza.nombre] = pr.clave.rsplit("|", 1)[-1]
    return fuera


def _depende_del_workdir(nombre):
    """¿La receta de esa pieza referencia `PUPPET_WORKDIR`? En env O en args: los dos
    cuelgan del workdir y los dos entran a la huella."""
    fila = filas.get(nombre) or {}
    return "PUPPET_WORKDIR" in json.dumps(
        {"args": fila.get("args"), "env": CR.env_efectivo(fila)}, ensure_ascii=False)


# (a) calentar como lo hace la Sala al abrir
from app.phase1 import motor_verdad as MV                   # noqa: E402
ent_cal = MV._entorno_de_belts()
res_cal, _ = _pool(owner, filas, CR, base_env=ent_cal)      # el cinturón "caliente"
h_cal = _huellas_de(res_cal)
_apagar_pool(res_cal)
sp_cal = D.actual().estado()["eventos"]["spawns"]
vivas_cal = len(D.actual().estado()["vivas"])
ok(vivas_cal > 0, f"el calentado dejó {vivas_cal} conexión(es) sostenida(s)")

# (b) el "primer mensaje": el run arma su pool con su `mkdtemp` propio
res_run, _ = _pool(owner, filas, CR)
h_run = _huellas_de(res_run)
sp_run = D.actual().estado()["eventos"]["spawns"] - sp_cal
ent_run = RA._puppet_run_env(str(aleph_paths.resource_root()), dict(os.environ))
nota(f"workdir del calentador : {ent_cal['PUPPET_WORKDIR']}")
nota(f"workdir del run        : {ent_run['PUPPET_WORKDIR']}")
print(f"      spawns del calentado: {sp_cal}   ·   spawns del primer mensaje: {sp_run}"
      f"   ·   reusos: {D.actual().estado()['eventos']['compartidas']}")
print(f"      {'pieza':<10} {'¿depende del workdir?':<22} {'h(calentado)':<14} {'h(run)':<14} reusó")

deben, no_reusaron, excluidas = [], [], []
for n in presentes:
    dep = _depende_del_workdir(n)
    hc, hr = h_cal.get(n), h_run.get(n)
    reuso = hc is not None and hc == hr
    print(f"      {n:<10} {('SÍ (args/env)' if dep else 'no'):<22} {str(hc or '—'):<14} "
          f"{str(hr or '—'):<14} {'SÍ' if reuso else 'no'}")
    if hc is None or hr is None:
        excluidas.append(n)                 # no arranca: no hay nada que reusar
    elif dep:
        continue                            # spawnea con razón: su workdir ES su identidad
    else:
        deben.append(n)
        if not reuso:
            no_reusaron.append(n)

for n in excluidas:
    nota(f"`{n}` no arranca en esta máquina — queda FUERA del gate (no es un reuso fallido; "
         f"su veredicto es el mismo que en main).")
ok(bool(deben), f"hay al menos una pieza que no depende del workdir para medir "
                f"({', '.join(deben) or 'ninguna'})")
ok(not no_reusaron,
   f"TODA pieza que no depende del workdir se REUSÓ ({', '.join(deben)}) — §9.2 en pie",
   f"no reusaron: {', '.join(no_reusaron)}")
if no_reusaron:
    nota("La huella mira el env DECLARADO (§9.2). Si una de ésas no reusa, o la marca")
    nota("  `dueno.EnvDelHijo` se perdió en el camino (cualquier `dict(env)` la borra) o")
    nota("  su receta declara algo que cambia entre el calentado y el run.")
_apagar_pool(res_run)


seccion("6 · CERO HUÉRFANOS")
todos = [pid for v in D.actual().estado()["vivas"] for pid in v["pids"]]
n = D.actual().apagar_todo(motivo="fin de la vara")
time.sleep(1.0)
ok([p for p in todos if D._vive(p)] == [],
   f"apagadas {n}; no queda NINGÚN proceso vivo (evidencia ps)",
   str([p for p in todos if D._vive(p)]))
ok(D.actual().estado()["vivas"] == [], "y la tabla del dueño queda vacía")
os.environ.pop("ALEPH_DUENO", None)

print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}"
      + (f" · {_bloqueos} BLOQUEO(S) DECLARADO(S) — ver §5" if _bloqueos else ""))
sys.exit(0 if _fallos == 0 else 1)
