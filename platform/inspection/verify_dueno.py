#!/usr/bin/env python3
"""verify_dueno.py — LA VARA DE D1, literal del `DISEÑO-DUEÑO-v1.md` §10.

Lo que el plan exige que esta sesión deje verde:

    dos pedidos de la misma huella dan UN proceso · huellas distintas dan DOS · el préstamo
    bloquea el desalojo · matar el proceso a mano deja la entrada muerta y emite el evento ·
    el archivo tiene la línea `naciendo` ANTES de que exista el pid (verificable matando
    entre medio).

Cero mocks del transporte: se levantan servers MCP de laboratorio de verdad —un script
stdio que habla JSON-RPC— y se los mira con `ps`. El archivo de procesos se apunta a un
temporal, así que esta vara **no toca el `procesos.jsonl` del usuario**.

    product/backend/.venv/bin/python platform/inspection/verify_dueno.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/inspection"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import dueno as D  # noqa: E402

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


# ── el server de laboratorio: un MCP stdio de verdad ────────────────────────────────
_LAB = textwrap.dedent('''
    import json, os, sys, time
    LENTO = float(os.environ.get("LAB_LENTO_S") or 0)
    MARCA = os.environ.get("LAB_MARCA", "")
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            m = json.loads(linea)
        except Exception:
            continue
        meth, rid = m.get("method"), m.get("id")
        if rid is None:
            continue
        if meth == "initialize":
            r = {"protocolVersion": m.get("params", {}).get("protocolVersion", "2025-11-25"),
                 "capabilities": {"tools": {}},
                 "serverInfo": {"name": "lab-dueno", "version": "1"}}
        elif meth == "tools/list":
            r = {"tools": [{"name": "eco", "inputSchema": {"type": "object"}}]}
        elif meth == "tools/call":
            if LENTO:
                time.sleep(LENTO)
            r = {"content": [{"type": "text", "text": "eco:" + MARCA}], "isError": False}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": rid,
                              "error": {"code": -32601, "message": "nope"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": r}), flush=True)
''')

_TMP = Path(tempfile.mkdtemp(prefix="aleph-dueno-vara-"))
_LAB_PY = _TMP / "lab_mcp.py"
_LAB_PY.write_text(_LAB)


def _spec(marca="a", extra_env=None, lento=0.0):
    env = dict(os.environ)
    env["LAB_MARCA"] = marca
    if lento:
        env["LAB_LENTO_S"] = str(lento)
    env.update(extra_env or {})
    return {"command": sys.executable, "args": [str(_LAB_PY)], "env": env,
            "cwd": None, "rpc_timeout": 20}


def _dueno_de_vara(retencion_s=0.0):
    """Un dueño con su PROPIO libro en un temporal: la vara no toca el archivo del usuario."""
    libro = D._Libro(ruta=_TMP / f"procesos-{time.time_ns()}.jsonl")
    return D.Dueno(libro=libro, retencion_s=retencion_s), libro


def _vivos(pids):
    return [p for p in pids if D._vive(p)]


# ══════════════════════════════════════════════════════════════════════════════════
seccion("0 · la perilla y el default de D1")
previo = os.environ.pop("ALEPH_DUENO", None)
# EL DEFAULT SE DIO VUELTA, y es una decisión, no un descuido. En D1 el dueño nacía
# apagado porque sostener no servía de nada: el workdir cambiaba en cada turno y ninguna
# pieza calentada se reusaba jamás (medido: 4 de 8 con huella nueva por turno). Con la
# carpeta estable por hilo el reuso existe y está medido —`asm.restaurar` 2.5 s en el t1 →
# 26-36 ms de t2 en adelante— así que el default útil es `on`. La perilla queda para
# apagarlo, que es la dirección en la que ahora hace falta una perilla.
ok(D.encendido() is True, "sin la perilla, el dueño está ENCENDIDO (default desde el workdir del hilo)")
os.environ["ALEPH_DUENO"] = "off"
ok(D.encendido() is False, "`ALEPH_DUENO=off` lo apaga")
os.environ["ALEPH_DUENO"] = "on"
ok(D.encendido() is True, "`ALEPH_DUENO=on` lo enciende")
os.environ.pop("ALEPH_DUENO", None)
if previo is not None:
    os.environ["ALEPH_DUENO"] = previo
ok(D.OCIOSIDAD_S == 600, "OCIOSIDAD_S = 600 — **desde D2 el dueño SOSTIENE**",
   f"vale {D.OCIOSIDAD_S}")
# 8 ERA EL TAMAÑO EXACTO DEL KIT, así que un solo hilo llenaba el techo y el siguiente
# desalojaba al anterior: volver a la conversación de antes costaba ~4 s de re-spawn.
# Medido con 24: la vuelta sale en 87,8 ms. 24 = 4 compartidas + 4 × 5 hilos calientes.
#
# ⚠️ Y LOS 113 MB NO APLICAN A ESTE CINTURÓN. Ese número salió de otra medición y se
# respeta; el kit de la Sala es `uv`, `npm` y pythons chicos: RSS real sobre 20 conexiones
# vivas = 379 MB, o sea ~19 MB cada una. 24 conexiones son ~455 MB.
ok(D.MAX_VIVAS == 24, "MAX_VIVAS = 24 (~455 MB con los ~19 MB medidos en el kit)",
   f"vale {D.MAX_VIVAS}")


seccion("1 · LA HUELLA · misma huella ⇒ UN proceso · distinta ⇒ DOS")
# EL SPEC SE TOMA UNA VEZ, que es lo que hace un llamante real: el verificador arma su
# entorno con `_entorno_de_belts()` una vez por medición y lo reusa. Tomarlo dos veces
# expondría el caso documentado en `huella()` —un import que muta `os.environ` entre medio—
# que se prueba aparte, abajo, justamente porque su modo de fallo es el SEGURO.
d, libro = _dueno_de_vara(retencion_s=0)   # sin sostener: se mide el refcount solo
_SPEC_A = _spec("a")
with d.pedir("lab", spec=_SPEC_A, user_id="u1", motivo="p1") as p1:
    pids1 = p1.pids
    ok(len(pids1) >= 1, f"el primer pedido levantó un proceso ({pids1})")
    with d.pedir("lab", spec=_SPEC_A, user_id="u1", motivo="p2") as p2:
        ok(p1.clave == p2.clave, "misma huella ⇒ MISMA clave")
        ok(sorted(p2.pids) == sorted(pids1), "misma huella ⇒ EL MISMO proceso, no otro",
           f"{pids1} vs {p2.pids}")
        est = d.estado()
        ok(len(est["vivas"]) == 1, "una sola entrada en la tabla",
           str([v["clave"] for v in est["vivas"]]))
        ok(est["vivas"][0]["refcount"] == 2, "refcount = 2",
           str(est["vivas"][0]["refcount"]))
        # ── huella distinta: el env cambia (es lo que le pasa a `filesystem` por run)
        with d.pedir("lab", spec=_spec("b"), user_id="u1", motivo="p3") as p3:
            ok(p3.clave != p1.clave, "env distinto ⇒ OTRA huella ⇒ otra clave")
            ok(set(p3.pids).isdisjoint(set(pids1)),
               "…y OTRO proceso, no el mismo compartido", f"{pids1} vs {p3.pids}")
            ok(len(d.estado()["vivas"]) == 2, "dos entradas en la tabla")
        # ── y el usuario también parte la clave (la fuga BYOK del §2.1)
        with d.pedir("lab", spec=_SPEC_A, user_id="u2", motivo="p4") as p4:
            ok(p4.clave != p1.clave, "MISMO spec, OTRO usuario ⇒ otra clave (§2.1)")
            ok(set(p4.pids).isdisjoint(set(pids1)),
               "…y otro proceso: la credencial de u1 no se comparte con u2")
    ok(d.estado()["vivas"][0]["refcount"] == 1,
       "al salir el segundo `with`, el refcount baja a 1")
    ok(_vivos(pids1) == pids1, "…y el proceso SIGUE VIVO mientras haya un préstamo")
ok(_vivos(pids1) == [], "con ociosidad 0, soltar el último préstamo cierra ya",
   str(_vivos(pids1)))
ok(d.estado()["vivas"] == [], "y la tabla queda vacía")


seccion("1bis · EL MODO DE FALLO DE LA HUELLA ES EL SEGURO")
# Como entra el env COMPLETO, una variable ambiente que cambie parte la huella. Eso cuesta
# un proceso de más (113 MB) — nunca compartir dos que no debían compartirse, que es la
# fuga BYOK del §2.1. Se prueba la DIRECCIÓN, que es lo que importa.
_base = dict(os.environ)
h1 = D.huella(sys.executable, ["x.py"], _base, None)
h2 = D.huella(sys.executable, ["x.py"], {**_base, "UNA_VAR_CUALQUIERA": "1"}, None)
ok(h1 != h2, "una variable de más en el env ⇒ OTRA huella (se parte, no se funde)")
h3 = D.huella(sys.executable, ["x.py"], {**_base, "OPENAI_API_KEY": "sk-de-otro"}, None)
ok(h3 not in (h1, h2),
   "una CREDENCIAL distinta ⇒ otra huella — es el invariante del §2.1, no una optimización")
ok(D.huella(sys.executable, ["x.py"], _base, None) == h1,
   "y con el MISMO env la huella es estable (si no, nada compartiría nunca)")
ok(len(h1) == 12 and all(c in "0123456789abcdef" for c in h1),
   "la huella es un digest de 12 hex: publicable sin filtrar un solo valor")


seccion("2 · EL PRÉSTAMO BLOQUEA EL DESALOJO")
d, libro = _dueno_de_vara(retencion_s=600)          # simula D2: el dueño SÍ sostiene
with d.pedir("lab", spec=_spec("a"), motivo="run") as p:
    pids = p.pids
    ok(d.estado()["vivas"][0]["refcount"] == 1, "prestada: refcount 1")
    ok(d.estado()["sostiene"] is True, "con retención > 0 el dueño declara que sostiene")
ok(_vivos(pids) == pids, "con retención, soltar NO mata (eso es D2 funcionando)")
ok(d.estado()["vivas"][0]["refcount"] == 0, "…y el refcount quedó en 0")
# la lápida manda igual, por encima del refcount y de la retención
d2, _l = _dueno_de_vara(retencion_s=600)
with d2.pedir("lab", spec=_spec("z"), motivo="run") as p:
    pids_lapida = p.pids
    n = d2.apagar_entidad("lab", motivo="lápida")
    ok(n == 1, "la LÁPIDA apaga aunque esté PRESTADA (§1.1: manda siempre)")
time.sleep(0.6)
ok(_vivos(pids_lapida) == [], "y el proceso muere de verdad", str(_vivos(pids_lapida)))
d.apagar_entidad("lab", motivo="limpieza de vara")


seccion("3 · MUERTE DEL PROCESO · la entrada se marca y se cuenta")
d, libro = _dueno_de_vara(retencion_s=600)
with d.pedir("lab", spec=_spec("a"), motivo="run") as p:
    pids = list(p.pids)
ok(_vivos(pids) == pids, "la conexión quedó viva (retención)")
for pid in pids:                                     # lo matamos A MANO, por fuera
    try:
        os.kill(pid, 9)
    except Exception:                                # noqa: BLE001
        pass
time.sleep(0.6)
ok(_vivos(pids) == [], "el proceso está muerto por fuera del dueño")
antes = d.estado()["eventos"]["muertes"]
with d.pedir("lab", spec=_spec("a"), motivo="run2") as p2:
    ok(d.estado()["eventos"]["muertes"] == antes + 1,
       "al pedirla de nuevo, el dueño CUENTA la muerte")
    ok(set(p2.pids).isdisjoint(set(pids)) and p2.pids,
       "y la re-levanta (reconnect-once del §5.3, en el dueño y no en repair)",
       f"{pids} vs {p2.pids}")
    ok(p2.call_tool("eco", {}) == "eco:a", "la conexión nueva funciona")
d.apagar_entidad("lab", motivo="limpieza de vara")


seccion("4 · EL LIBRO · `naciendo` ANTES de que exista el pid")
# Se intercepta la clase de transporte para congelar el mundo JUSTO entre el volcado y el
# spawn — que es la ventana que el §3.2 existe para cubrir.
visto: dict = {}


class _ServidorQueEspia:
    def __init__(self, nombre, comando, args, env=None, rpc_timeout=30.0, cwd=None):
        # En este instante el dueño YA escribió la línea. Se lee el archivo desde acá.
        visto["filas"] = libro_espia.leer()
        self._real = D.Dueno(libro=libro_espia)._cls()(nombre, comando, args, env=env,
                                                       rpc_timeout=rpc_timeout, cwd=cwd)

    def start(self):
        return self._real.start()

    def list_tools(self):
        return self._real.list_tools()

    def call_tool(self, *a):
        return self._real.call_tool(*a)

    def stop(self):
        return self._real.stop()

    def diagnostico(self):
        return self._real.diagnostico()


libro_espia = D._Libro(ruta=_TMP / "procesos-espia.jsonl")
d = D.Dueno(libro=libro_espia, servidor_cls=_ServidorQueEspia, retencion_s=0)
with d.pedir("lab", spec=_spec("a"), user_id="u1", motivo="run") as p:
    filas = visto.get("filas") or []
    ok(len(filas) == 1, "hay UNA línea en el archivo antes de que se spawnee nada",
       str(filas))
    if filas:
        f = filas[0]
        ok(f.get("estado") == "naciendo", "…y está en estado `naciendo`", str(f.get("estado")))
        ok(f.get("pids") == [], "…SIN pid, porque todavía no existe", str(f.get("pids")))
        ok(bool(f.get("comando")) and f.get("nacido_en"),
           "…pero CON comando y hora: alcanza para barrer aunque nunca sepamos el pid")
    despues = libro_espia.leer()
    ok(len(despues) == 1 and despues[0].get("estado") == "vivo" and despues[0].get("pids"),
       "tras el spawn, la misma línea pasa a `vivo` con sus pids",
       str(despues))
ok(libro_espia.leer() == [], "al cerrar, la línea se va del archivo")


seccion("5 · EL BARRIDO DE ARRANQUE · los DOS discriminadores, por separado")
# Los dos chequeos de identidad se prueban AISLADOS: uno que falla por comando y otro que
# falla por hora. Un test que los mezclara podría dar verde con uno solo funcionando.
libro_barrido = D._Libro(ruta=_TMP / "procesos-barrido.jsonl")


def _proc():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    time.sleep(0.35)
    return p


huerfano = _proc()          # a) nuestro: comando y hora coinciden      → SE MATA
ajeno_cmd = _proc()         # b) el comando anotado es otro             → NO SE TOCA
ajeno_hora = _proc()        # c) el comando coincide, la hora NO        → NO SE TOCA
ahora = time.time()
libro_barrido.escribir([
    {"clave": "u|huerfano|h1", "entity_id": "huerfano", "user_id": "u",
     "comando": sys.executable, "args": [], "cwd": None,
     "nacido_en": ahora, "pids": [huerfano.pid], "estado": "vivo"},
    {"clave": "u|otro-comando|h2", "entity_id": "otro-comando", "user_id": "u",
     "comando": "/binario/que/nunca/existio", "args": [], "cwd": None,
     "nacido_en": ahora, "pids": [ajeno_cmd.pid], "estado": "vivo"},
    {"clave": "u|otra-hora|h3", "entity_id": "otra-hora", "user_id": "u",
     "comando": sys.executable, "args": [], "cwd": None,
     "nacido_en": ahora - 3600, "pids": [ajeno_hora.pid], "estado": "vivo"},
    {"clave": "u|naciendo|h4", "entity_id": "naciendo", "user_id": "u",
     "comando": sys.executable, "args": [], "cwd": None,
     "nacido_en": ahora, "pids": [], "estado": "naciendo"},
])
d = D.Dueno(libro=libro_barrido)
parte = d.barrer_al_arrancar()
time.sleep(1.2)
ok(parte["matadas"] == 1, "barrió UNO: el único que coincide en comando Y hora", str(parte))
ok(not D._vive(huerfano.pid), "el huérfano nuestro está muerto")
ok(D._vive(ajeno_cmd.pid),
   "el de OTRO COMANDO no se tocó — matarlo sería matar a un tercero")
ok(D._vive(ajeno_hora.pid),
   "el de OTRA HORA no se tocó — es el pid reciclado, y arrancó después de nuestro registro",
   "si esto se pone rojo, la ventana de tiempo volvió a ser un umbral")
ok(parte["recicladas"] == 2, "…y los dos se contaron como recicladas", str(parte))
ok(parte["sin_pid"] == 1, "la entrada `naciendo` sin pid se reporta y no se inventa nada")
ok(libro_barrido.leer() == [], "el archivo queda vacío tras barrer")
ajeno_cmd.kill()
ajeno_hora.kill()


seccion("6 · EL CONTRATO DEL PRÉSTAMO")
d, _l = _dueno_de_vara(retencion_s=0)
with d.pedir("lab", spec=_spec("a"), motivo="run") as p:
    ok(not hasattr(p, "stop"), "el préstamo NO expone `stop()`: quien pide no mata (§6.1)")
    ok(p.call_tool("eco", {}) == "eco:a", "`call_tool` devuelve lo mismo de siempre")
    ok([t["name"] for t in p.list_tools()] == ["eco"], "`list_tools` idem")
    ok(isinstance(p.diagnostico(), dict), "`diagnostico()` sigue disponible")
    guardado = p
try:
    guardado.call_tool("eco", {})
    ok(False, "usar un préstamo ya soltado tiene que fallar")
except D.DuenoError:
    ok(True, "usar un préstamo ya soltado levanta `DuenoError` — no devuelve basura")
guardado.soltar()
ok(True, "`soltar()` es idempotente (no revienta al segundo)")


seccion("7 · UN ARRANQUE FALLIDO NO DEJA ENTRADA NI PROCESO")
d, libro_f = _dueno_de_vara(retencion_s=0)
try:
    d.pedir("nope", spec={"command": "comando-que-no-existe-jamas", "args": [],
                          "env": dict(os.environ), "rpc_timeout": 5}, motivo="run")
    ok(False, "un comando inexistente tiene que levantar DuenoError")
except D.DuenoError as e:
    ok("no pude levantar" in str(e) or "no completó el saludo" in str(e),
       "un arranque fallido levanta `DuenoError` con el motivo", str(e)[:80])
ok(d.estado()["vivas"] == [], "y NO deja una entrada colgada en la tabla")
ok(libro_f.leer() == [], "ni una línea colgada en el archivo")



# ══════════════════════════════════════════════════════════════════════════════════
# D2 · LO QUE SOSTENER AGREGA
# ══════════════════════════════════════════════════════════════════════════════════

seccion("8 · EL RELOJ DE OCIOSIDAD · una PRESTADA no envejece")
d, _l = _dueno_de_vara(retencion_s=1.0)
_SPEC_C = _spec("c")
with d.pedir("lab", spec=_SPEC_C, motivo="run") as p:
    pids_ocio = list(p.pids)
    ok(d.estado()["cosechador_vivo"] is True,
       "al primer pedido arranca el cosechador (perezoso: sin pedidos, sin hilo)")
    # EL INVARIANTE: prestada, el reloj NO corre. Se espera MÁS del doble de la ociosidad.
    time.sleep(2.5)
    d.cosechar()                                       # y encima se lo pide a mano
    ok(_vivos(pids_ocio) == pids_ocio,
       "tras 2,5× la ociosidad, la conexión PRESTADA sigue viva — no envejece (§1.3)",
       str(_vivos(pids_ocio)))
    ok(p.call_tool("eco", {}) == "eco:c", "…y sigue sirviendo llamadas")
# soltada: ahora sí empieza a correr
ok(_vivos(pids_ocio) == pids_ocio,
   "al soltar NO se cierra: **el dueño SOSTIENE** (esto es D2, no D1)")
ok(d.estado()["vivas"][0]["refcount"] == 0, "…con refcount 0 y el reloj corriendo")
d.cosechar()
ok(_vivos(pids_ocio) == pids_ocio,
   "cosechar ANTES de que venza no cierra nada (el umbral es un umbral)")
time.sleep(1.3)
d.cosechar()          # y si el hilo ya se le adelantó, mejor: lo que importa es el efecto
# Se afirma el EFECTO, no quién lo produjo: el hilo de fondo y esta llamada hacen lo mismo,
# y exigir que cierre justo esta llamada haría la vara dependiente de quién llegue primero.
ok(_vivos(pids_ocio) == [], "vencida la ociosidad, la conexión se cierra",
   f"vivos {_vivos(pids_ocio)}")
ok(d.estado()["eventos"]["cerradas_por_ociosidad"] == 1,
   "…exactamente una vez, y contada")
ok(d.estado()["vivas"] == [], "la tabla queda vacía")


seccion("9 · EL COSECHADOR SOLO, sin que nadie lo llame a mano")
d, _l = _dueno_de_vara(retencion_s=0.6)
with d.pedir("lab", spec=_spec("d"), motivo="run") as p:
    pids_auto = list(p.pids)
# nadie llama a `cosechar()`: lo tiene que hacer el hilo
espera = 0.0
while espera < 8.0 and _vivos(pids_auto):
    time.sleep(0.3)
    espera += 0.3
ok(_vivos(pids_auto) == [],
   f"el hilo cerró la ociosa solo, sin que nadie se lo pidiera ({espera:.1f}s)",
   str(_vivos(pids_auto)))


seccion("10 · EL TECHO · desaloja por LRU y NUNCA a una prestada")
d, _l = _dueno_de_vara(retencion_s=600)
d._max_vivas = 2
with d.pedir("lab", spec=_spec("t1"), motivo="r1") as p1:
    pids_t1 = list(p1.pids)
with d.pedir("lab", spec=_spec("t2"), motivo="r2") as p2:
    pids_t2 = list(p2.pids)
ok(len(d.estado()["vivas"]) == 2, "dos vivas, tope lleno")
ok(_vivos(pids_t1) == pids_t1 and _vivos(pids_t2) == pids_t2, "las dos siguen vivas")
time.sleep(0.05)
with d.pedir("lab", spec=_spec("t3"), motivo="r3") as p3:
    pids_t3 = list(p3.pids)
    ok(len(d.estado()["vivas"]) == 2, "sigue habiendo dos: entró una y salió una")
    ok(_vivos(pids_t1) == [], "la desalojada es la MENOS recientemente usada (t1)",
       f"t1 vivos: {_vivos(pids_t1)}")
    ok(_vivos(pids_t2) == pids_t2, "…y t2, la más reciente, sobrevive")
    ok(d.estado()["eventos"]["desalojos_lru"] == 1, "el desalojo se cuenta")
d.apagar_todo(motivo="limpieza de vara")

# la exclusión dura: una PRESTADA no se desaloja aunque sea la más vieja
d, _l = _dueno_de_vara(retencion_s=600)
d._max_vivas = 2
p_viva = d.pedir("lab", spec=_spec("v1"), motivo="sostenida")   # queda PRESTADA
pids_v1 = list(p_viva.pids)
time.sleep(0.05)
with d.pedir("lab", spec=_spec("v2"), motivo="r2") as _p2:
    pass                                                # soltada: candidata a LRU
with d.pedir("lab", spec=_spec("v3"), motivo="r3") as _p3:
    ok(_vivos(pids_v1) == pids_v1,
       "la PRESTADA no se desaloja aunque sea la más vieja (§4.3, exclusión dura)",
       str(_vivos(pids_v1)))
    ok(len(d.estado()["vivas"]) == 2, "y el tope se respetó desalojando a la otra")
p_viva.soltar()
d.apagar_todo(motivo="limpieza de vara")


seccion("11 · SOBRECUPO · el techo CEDE antes que hacer esperar a nadie")
d, _l = _dueno_de_vara(retencion_s=600)
d._max_vivas = 1
p_a = d.pedir("lab", spec=_spec("s1"), motivo="r1")     # la única, y PRESTADA
with d.pedir("lab", spec=_spec("s2"), motivo="r2") as p_b:
    ok(len(d.estado()["vivas"]) == 2,
       "con todas prestadas, el tope CEDE y se levanta igual — no hay deadlock (§4.3)")
    ok(d.estado()["eventos"]["sobrecupo"] == 1, "…y queda contado como sobrecupo")
    ok(_vivos(p_a.pids) == p_a.pids and _vivos(p_b.pids) == p_b.pids,
       "las dos vivas de verdad")
p_a.soltar()
d.apagar_todo(motivo="limpieza de vara")


seccion("12 · APAGAR TODO · lo que el lifespan llama al cerrar")
d, libro_cierre = _dueno_de_vara(retencion_s=600)
todos = []
for marca in ("c1", "c2", "c3"):
    with d.pedir("lab", spec=_spec(marca), motivo="run") as p:
        todos += list(p.pids)
ok(len(d.estado()["vivas"]) == 3 and _vivos(todos) == todos,
   "tres conexiones sostenidas y vivas", f"{len(todos)} pids")
t0 = time.perf_counter()
n = d.apagar_todo(motivo="cierre del sidecar")
ms = int((time.perf_counter() - t0) * 1000)
ok(n == 3, "apagó las tres", str(n))
time.sleep(0.8)
ok(_vivos(todos) == [], "EVIDENCIA ps: no queda NINGÚN proceso vivo", str(_vivos(todos)))
ok(d.estado()["vivas"] == [], "la tabla queda vacía")
ok(libro_cierre.leer() == [], "y el `procesos.jsonl` también")
ok(ms < 4000, f"y cerró EN PARALELO ({ms} ms; en serie serían 3× la escalada del SDK)",
   f"{ms} ms")
ok(d.estado()["cosechador_vivo"] is False, "el cosechador se detuvo con el apagado")


seccion("13 · EL LIFESPAN LO LLAMA DE VERDAD")
_main = (_RAIZ / "product/backend/app/main.py").read_text()
ok("apagar_todo" in _main, "`main.py` llama `apagar_todo()` — antes no sabía qué matar")
ok("barrer_al_arrancar" in _main, "…y `barrer_al_arrancar()` al bootear")
_i_yield = _main.find("        yield")
ok(0 < _i_yield < _main.find("apagar_todo"),
   "el `apagar_todo` va DESPUÉS del `yield`, o sea en el `finally` del cierre")
ok(_main.find("barrer_al_arrancar") < _i_yield,
   "y el barrido ANTES, en el arranque")


seccion("12bis · EFÍMERAS (D3) · lo que no se va a reusar no se sostiene")
# La sonda de credencial del verificador corre con `clave-falsa-de-prueba-0000` en el env:
# ningún run va a pedir jamás esa huella, así que sostenerla son 113 MB que nadie reusa.
# Medido en el agente real: DOS de las siete conexiones sostenidas eran esa sonda.
d, _l = _dueno_de_vara(retencion_s=600)
with d.pedir("lab", spec=_spec("ef"), motivo="sonda", efimero=True) as p:
    pids_ef = list(p.pids)
    ok(d.estado()["vivas"][0]["efimera"] is True, "la conexión queda marcada efímera")
ok(_vivos(pids_ef) == [],
   "al soltarla se cierra YA, aunque la ociosidad sea 600 s", str(_vivos(pids_ef)))
ok(d.estado()["eventos"]["efimeras_cerradas"] == 1, "…y se cuenta aparte")
ok(d.estado()["vivas"] == [], "no queda en la tabla")

# y una NO efímera con la misma ociosidad sí se sostiene: la diferencia es el flag, no otra cosa
with d.pedir("lab", spec=_spec("noef"), motivo="run") as p2:
    pids_noef = list(p2.pids)
ok(_vivos(pids_noef) == pids_noef,
   "la misma conexión SIN el flag sí se sostiene — la diferencia es el flag y nada más")

# un pedido NO efímero PROMUEVE: si alguien la va a reusar, deja de ser descartable
with d.pedir("lab", spec=_spec("promo"), motivo="sonda", efimero=True) as p3:
    clave_promo = p3.clave
    with d.pedir("lab", spec=_spec("promo"), motivo="run") as p4:
        ok(p4.clave == clave_promo, "misma huella: es la misma conexión")
        ok(d.estado()["vivas"][0]["efimera"] is False,
           "un pedido NO efímero la PROMUEVE — ya no es descartable")
ok([v for v in d.estado()["vivas"] if v["clave"] == clave_promo],
   "…y por eso sobrevive al soltar los dos préstamos")
d.apagar_todo(motivo="limpieza de vara")


seccion("13bis · UN SOLO DUEÑO, SE LO IMPORTE COMO SE LO IMPORTE")
# `main.py` hace `from inspection import dueno`; `conexiones_verificador` hace `import
# dueno`. Sin el alias en `sys.modules` son DOS módulos con DOS tablas — y `apagar_todo()`
# barría una y dejaba viva la otra. Lo cazó la sección 14.
from inspection import dueno as _D2                        # noqa: E402
ok(_D2 is D, "los dos estilos de import dan EL MISMO módulo")
ok(_D2.actual() is D.actual(), "…y por lo tanto EL MISMO singleton")
D._reset_para_tests()


seccion("14 · EL LIFESPAN DE VERDAD · se levanta la app y se la cierra")
# Leer el archivo prueba que la llamada está escrita. Esto prueba que CORRE: se bootea la
# app real (el `TestClient` ejecuta el lifespan entero), se le hace sostener una conexión
# al dueño singleton, y se mira con `ps` qué queda cuando el contexto se cierra.
try:
    sys.path.insert(0, str(_RAIZ / "product/backend"))
    os.environ.setdefault("ALEPH_ROLE", "client")
    from fastapi.testclient import TestClient

    from app.main import app                              # noqa: E402
    D._reset_para_tests()
    dueno_real = D.actual()
    dueno_real._retencion_s = 600                         # que sostenga, como en producción
    pids_lifespan: list = []
    with TestClient(app):
        with dueno_real.pedir("lab", spec=_spec("lifespan"), motivo="vara") as p:
            pids_lifespan = list(p.pids)
        ok(_vivos(pids_lifespan) == pids_lifespan,
           "con la app arriba, el dueño SOSTIENE la conexión tras soltarla",
           str(_vivos(pids_lifespan)))
    # salido el `with`, el lifespan corrió su `finally`
    time.sleep(1.0)
    ok(_vivos(pids_lifespan) == [],
       "EVIDENCIA ps: al cerrarse el lifespan NO queda ningún proceso MCP vivo",
       str(_vivos(pids_lifespan)))
    ok(dueno_real.estado()["vivas"] == [], "y el dueño no sostiene nada")
except ImportError as e:
    print(f"  · (se saltea: no se pudo importar la app — {e})")
except Exception as e:                                    # noqa: BLE001
    ok(False, "el lifespan real corrió sin explotar", f"{type(e).__name__}: {e}")
finally:
    try:
        D._reset_para_tests()
    except Exception:                                     # noqa: BLE001
        pass

print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
sys.exit(0 if _fallos == 0 else 1)
