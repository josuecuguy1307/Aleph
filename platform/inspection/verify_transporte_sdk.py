#!/usr/bin/env python3
"""verify_transporte_sdk.py — LA VARA DEL PUENTE (Fase 1 · sesión 1 del SDK).

Cero mocks de lo que se está probando: cada aserción corre contra un proceso real. El
server de laboratorio es un MCP stdio de verdad —habla JSON-RPC por stdin/stdout— escrito
acá abajo, y el server REAL es `fetch` (`uvx mcp-server-fetch`), el mismo que el registro
tiene equipado con sonda declarada.

Lo que se prueba, en orden de consecuencia:
  1. el pin: sin `mcp==2.0.0` esto no corre, y lo dice — no se prueba contra otra versión
  2. el ENTORNO del hijo es nuestro: el PATH sale de Aleph y el default del SDK no se cuela
  3. el stderr del hijo se captura, acotado, como hoy — los diagnósticos viven de eso
  4. contra un server REAL: initialize + list_tools + call_tool dan lo mismo que el registro
  5. EL CIERRE: el árbol muere. Con el caso que DISCRIMINA (un nieto que ignora SIGTERM),
     medido contra el cliente viejo en la misma corrida
  6. el async no se escapa: la interfaz pública no tiene una sola corrutina

Correr (el pin importa — este árbol trae mcp 1.x por otro lado):
    /ruta/al/venv-con-mcp-2.0.0/bin/python platform/inspection/verify_transporte_sdk.py
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
if str(_AQUI) not in sys.path:
    sys.path.append(str(_AQUI))

_fallos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f" — {detalle}" if detalle else ""))


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


# ── 1 · EL PIN ──────────────────────────────────────────────────────────────────────
seccion("1 · el pin exacto")
try:
    import importlib.metadata as _md
    _VER = _md.version("mcp")
except Exception as e:                                     # noqa: BLE001
    print(f"✗ el SDK no está instalado: {e}")
    sys.exit(1)
ok(_VER == "2.0.0", f"mcp=={_VER} (se pineó 2.0.0)",
   "esta vara mide el puente CONTRA ESA versión; con otra, lo medido no es lo pineado")
if _VER != "2.0.0":
    print("\nNo sigo: probar contra una versión distinta de la pineada es reportar otra cosa.")
    sys.exit(1)

import transporte_sdk as T                                 # noqa: E402

hay, motivo = T.sdk_disponible()
ok(hay, "el puente ve el SDK", motivo)


# ── 2 · EL ENTORNO DEL HIJO ES NUESTRO ──────────────────────────────────────────────
seccion("2 · el entorno del hijo")
_env_none = T.entorno_hijo(None)
ok(_env_none.get("PATH") == T.path_de_aleph(),
   "sin `env`, el hijo obtiene sólo baseline mínimo y PATH de Aleph")
ok(_env_none.get("HOME", "").startswith(tempfile.gettempdir() + os.sep + "aleph-mcp-runtime-"),
   "sin `env`, HOME es scratch privado y no el del sidecar")

# El llamante manda sólo variables declaradas para ese server. Tienen que llegar enteras.
_pedido = {"PUPPET_BELTS": "/belts", "SECRETO_DE_PRUEBA": "abc", "PATH": "/solo/esto"}
_final = T.entorno_hijo(_pedido)
ok(_final.get("PUPPET_BELTS") == "/belts" and _final.get("SECRETO_DE_PRUEBA") == "abc",
   "con `env`, el entorno del llamante llega entero al hijo")
ok(_final.get("PATH") == T.path_de_aleph(),
   "y el PATH lo pisa Aleph SIEMPRE — nunca el del llamante ni el del SDK",
   f"quedó {_final.get('PATH','')[:60]}")
ok("/usr/bin" in _final.get("PATH", "").split(os.pathsep),
   "el PATH de Aleph sólo AGREGA: /usr/bin sigue estando (no puede angostar a nadie)")

# `stdio_client` arma el env como `get_default_environment() | nuestro`. Lo único que se
# cuela son las claves AUSENTES del nuestro. Cubrimos todo el baseline del SDK.
ok(T.fugas_del_sdk(_env_none) == [],
   "con el entorno mínimo, el default del SDK no inyecta NADA",
   str(T.fugas_del_sdk(_env_none)))
# Y con uno mínimo a mano, la fuga se ve en vez de esconderse.
_fugas_min = T.fugas_del_sdk({"PATH": "/bin"})
ok(len(_fugas_min) > 0 and "HOME" in _fugas_min,
   "con un entorno mínimo, las que el SDK inyectaría quedan REPORTADAS, no ocultas",
   str(_fugas_min))


# ── el server de laboratorio ────────────────────────────────────────────────────────
# Un MCP stdio real, mínimo y honesto: habla el handshake, publica una tool, escribe a
# stderr (para probar la captura) y —si se lo piden— deja un NIETO que ignora SIGTERM.
_LAB = textwrap.dedent('''
    import json, os, subprocess, sys, signal, time
    RUIDO = os.environ.get("LAB_STDERR_LINEAS")
    if RUIDO:
        for i in range(int(RUIDO)):
            print(f"lab: linea de stderr {i}", file=sys.stderr, flush=True)
    PIDS = os.environ.get("LAB_PIDFILE")
    CUELGA = os.environ.get("LAB_CUELGA")
    if CUELGA:
        # El server NO se muere solo: ignora SIGTERM y no sale cuando le cierran stdin.
        # Es el ÚNICO caso que hace que un cliente TENGA que escalar.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if PIDS:
        # Un nieto que IGNORA SIGTERM y sobrevive a la muerte de su padre: es lo que separa
        # «matar al hijo» de «matar al árbol».
        n = subprocess.Popen([sys.executable, "-c",
            "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(600)"])
        open(PIDS, "w").write(f"{os.getpid()} {n.pid}")
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            msg = json.loads(linea)
        except Exception:
            continue
        m, rid = msg.get("method"), msg.get("id")
        if rid is None:
            continue
        if m == "initialize":
            r = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-11-25"),
                 "capabilities": {"tools": {}},
                 "serverInfo": {"name": "lab-aleph", "version": "0.0.1"}}
        elif m == "tools/list":
            r = {"tools": [{"name": "eco", "description": "devuelve lo que le den",
                            "inputSchema": {"type": "object",
                                            "properties": {"texto": {"type": "string"}}}}]}
        elif m == "tools/call":
            a = msg.get("params", {}).get("arguments", {})
            r = {"content": [{"type": "text", "text": "eco:" + str(a.get("texto", ""))}],
                 "isError": False}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": rid,
                              "error": {"code": -32601, "message": "method not found"}}),
                  flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": r}), flush=True)
    if CUELGA:
        time.sleep(600)      # stdin cerrado y acá seguimos: un server colgado de verdad
''')

_TMP = Path(tempfile.mkdtemp(prefix="aleph-puente-"))
_LAB_PY = _TMP / "lab_mcp.py"
_LAB_PY.write_text(_LAB)


def _vivos(marca: str) -> list:
    r = subprocess.run(["ps", "-eo", "pid,ppid,pgid,command"], capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if marca in l and "ps -eo" not in l]


# ── 3 · STDERR CAPTURADO Y ACOTADO ──────────────────────────────────────────────────
seccion("3 · el stderr del hijo")
env_ruido = dict(os.environ, LAB_STDERR_LINEAS="5")
srv = T.ServidorSDK("lab-stderr", sys.executable, [str(_LAB_PY)], env=env_ruido, rpc_timeout=20)
ok(srv.start(), "el server de laboratorio arranca por el puente", srv.diagnostico().get("detail", ""))
time.sleep(0.4)
d = srv.diagnostico()
ok(d["stderr_lineas"] == 5 and "linea de stderr 4" in d["stderr"],
   "las 5 líneas de stderr del hijo llegan a `diagnostico()`",
   f"lineas={d['stderr_lineas']} texto={d['stderr'][:80]!r}")
ok(d["stderr_cap_bytes"] == 32 * 1024 and d["stderr_cap_lineas"] == 80,
   "con los MISMOS caps que MCPServer (32 KB · 80 líneas)")
ok(d["exit_code"] is None and "no expuesto" in d.get("exit_code_fuente", ""),
   "`exit_code` es None y DICE por qué — jamás un cero inventado")
srv.stop()

# El cap se respeta: 300 líneas entran, 80 quedan.
srv2 = T.ServidorSDK("lab-cap", sys.executable, [str(_LAB_PY)],
                     env=dict(os.environ, LAB_STDERR_LINEAS="300"), rpc_timeout=20)
srv2.start()
time.sleep(0.8)
d2 = srv2.diagnostico()
ok(d2["stderr_lineas"] <= 80 and "linea de stderr 299" in d2["stderr"],
   "300 líneas → se conservan las ÚLTIMAS 80 (la cola acotada, no las primeras)",
   f"lineas={d2['stderr_lineas']}")
srv2.stop()
ok(srv2.diagnostico()["murio"] is True,
   "tras stop(), `murio` = True (EOF del pipe: ya no queda nadie del árbol)")


# ── 4 · CONTRA UN SERVER REAL ───────────────────────────────────────────────────────
seccion("4 · contra `fetch`, el server real del registro")
real = T.ServidorSDK("fetch", "uvx", ["--with", "mcp==1.29.0", "mcp-server-fetch"],
                     rpc_timeout=90)
arranco = real.start()
ok(arranco, "fetch arranca por el puente", real.diagnostico().get("detail", ""))
if arranco:
    dr = real.diagnostico()
    tools = real.list_tools()
    ok([t["name"] for t in tools] == ["fetch"],
       "publica exactamente la tool que el registro dice: `fetch`", str([t["name"] for t in tools]))
    # La sonda DECLARADA del catálogo: constante neutra reservada por la IANA (CLAUDE.md §1b).
    salida = real.call_tool("fetch", {"url": "https://example.com"})
    ok("This domain is for use in documentation examples" in salida,
       "la sonda declarada devuelve el MISMO contenido que el registro persistió",
       salida[:100])
    ok(not salida.startswith("[MCP error") and not salida.startswith("[tool error]"),
       "y `call_tool` devuelve el texto pelado, con la forma de string de MCPServer")
    ok((dr.get("protocolo") or {}).get("negociacion") == "aceptada",
       "el handshake queda registrado como aceptado",
       str(dr.get("protocolo")))
    ok(dr["entorno"]["inyectadas_por_el_sdk"] == [],
       "y el SDK no le inyectó una sola variable al hijo")
    real.stop()
    time.sleep(0.8)
    ok(len(_vivos("mcp-server-fetch")) == 0,
       "tras stop(), no queda NINGÚN proceso de fetch vivo (uv + su python)",
       str(_vivos("mcp-server-fetch")))


# ── 5 · EL CIERRE: EL CASO QUE DISCRIMINA ───────────────────────────────────────────
seccion("5 · el cierre del árbol — puente vs cliente viejo")
# DOS casos, porque el cierre del SDK tiene una condición que hay que decir en voz alta:
# `_stop_server_process` cierra stdin, ESPERA 2 s y sólo SI EL HIJO NO SALIÓ manda SIGTERM
# al grupo. Un server que se muere solo al cerrarse stdin nunca llega a la escalada — y sus
# nietos quedan huérfanos igual que con el cliente viejo. Medido acá abajo, no supuesto.


def _mide_arbol(quien: str, hacer, cuelga: bool) -> tuple:
    """Devuelve (pid_padre, pid_nieto, [los que sobrevivieron])."""
    pidfile = _TMP / f"pids-{quien}.txt"
    env = dict(os.environ, LAB_PIDFILE=str(pidfile))
    if cuelga:
        env["LAB_CUELGA"] = "1"
    hacer(env)                                 # arranca, deja al nieto, y cierra
    crudo = pidfile.read_text().split() if pidfile.exists() else []
    padre, nieto = (int(crudo[0]), int(crudo[1])) if len(crudo) == 2 else (0, 0)
    time.sleep(1.5)                            # margen sobre SIGTERM(2s)+SIGKILL del SDK

    def _vive(pid):
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except Exception:                      # noqa: BLE001
            return False

    sobreviven = [p for p in (padre, nieto) if _vive(p)]
    for p in sobreviven:                       # limpieza: la prueba no deja basura
        try:
            os.kill(p, 9)
        except Exception:                      # noqa: BLE001
            pass
    return padre, nieto, sobreviven


def _con_puente(env):
    s = T.ServidorSDK("lab-arbol", sys.executable, [str(_LAB_PY)], env=env, rpc_timeout=20)
    s.start()
    time.sleep(0.5)
    s.stop()


def _con_viejo(env):
    import importlib.util
    ruta = _AQUI.parent / "assembler" / "assembler.py"
    sp = importlib.util.spec_from_file_location("asm_vara", str(ruta))
    asm = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(asm)
    s = asm.MCPServer("lab-arbol", sys.executable, [str(_LAB_PY)], env=env, rpc_timeout=20)
    s.start()
    time.sleep(0.5)
    s.stop()


print("\n  [a] server COLGADO (no sale al cerrarse stdin, ignora SIGTERM) — hay escalada")
_pp, _np, viven_p = _mide_arbol("puente-cuelga", _con_puente, cuelga=True)
_pv, _nv, viven_v = _mide_arbol("viejo-cuelga", _con_viejo, cuelga=True)
ok(viven_p == [],
   f"PUENTE: mueren el server ({_pp}) Y su nieto terco ({_np}) — SIGTERM al GRUPO, luego SIGKILL",
   f"sobrevivieron {viven_p}")
ok(viven_v == [_nv],
   f"CLIENTE VIEJO: mata al hijo directo ({_pv}) y DEJA HUÉRFANO al nieto ({_nv})",
   f"sobrevivieron {viven_v} (esperado exactamente [{_nv}])")

print("\n  [b] server BIEN EDUCADO (sale solo al cerrarse stdin) — NO hay escalada")
_pp2, _np2, viven_p2 = _mide_arbol("puente-limpio", _con_puente, cuelga=False)
_pv2, _nv2, viven_v2 = _mide_arbol("viejo-limpio", _con_viejo, cuelga=False)
ok(viven_p2 == [_np2] and viven_v2 == [_nv2],
   "los DOS dejan huérfano al nieto: el SDK no escala porque el hijo ya salió solo",
   f"puente={viven_p2} viejo={viven_v2}")
ok(True,
   "→ el cierre del SDK es más riguroso SÓLO cuando el server no se muere solo. "
   "No es una red que atrape todo huérfano.")


# ── 6 · EL ASYNC NO SE ESCAPA ───────────────────────────────────────────────────────
seccion("6 · el async no sale del puente")
publicas = []
for clase in (T.ServidorSDK, T.ClienteSdkHttp):
    for nombre, miembro in inspect.getmembers(clase, predicate=inspect.isfunction):
        if not nombre.startswith("_"):
            publicas.append((clase.__name__, nombre, inspect.iscoroutinefunction(miembro)))
ok(publicas and not any(c for _k, _n, c in publicas),
   f"ninguno de los {len(publicas)} métodos públicos del puente es una corrutina",
   str([f"{k}.{n}" for k, n, c in publicas if c]))
fuente = (_AQUI / "transporte_sdk.py").read_text()
ok("async def" in fuente,
   "…y sí hay `async def` ADENTRO (si no, no habría nada que puentear)")


print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
sys.exit(0 if _fallos == 0 else 1)
