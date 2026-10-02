#!/usr/bin/env python3
"""verify_cli_stopturn.py — LA VARA DE F2d (Gate 2 · detener un turno · cierre · huérfanos).

Lo que esta vara exige que quede verde:

    un turno REAL en vuelo → `stop` → el proceso está MUERTO (evidencia `ps`), el slot de
    F2b quedó libre (el turno siguiente entra) y la respuesta es TIPADA ·
    `stop` sin turno → `no_habia_turno`, y nada muere ·
    un proceso que IGNORA SIGTERM → SIGKILL a los 5 s → y el deadline resuelve SIEMPRE ·
    matar el sidecar con un turno vivo → `cli_procesos.jsonl` lo registra →
    `barrer_cli_al_arrancar()` lo caza verificando identidad → el jsonl queda limpio ·
    el barrido JAMÁS mata un pid reciclado ni un `claude` ajeno ·
    la fase crítica del cierre tiene deadline y DICE qué paso quedó colgado ·
    las cinco varas previas siguen verdes.

CÓMO SE PRUEBA UN PROCESO QUE NO SE QUIERE MORIR: con un stub. El `claude` real termina
cuando se le pide, así que con él NUNCA se ejercitaría la escalada a SIGKILL ni el
deadline — o sea, no se probaría nada de lo que esta fase agrega. El stub se llama
`claude`, se lanza por el `build_argv` de verdad (con toda la huella real) y sabe atrapar
SIGTERM. La sección 8 repite lo esencial contra el CLI REAL, que es donde el contrato vale.

El muestreo de `ps` filtra por un MARCADOR único, jamás por el nombre del binario: la
máquina que corre esta vara tiene otras sesiones de `claude` abiertas —la del operador, sin
ir más lejos— y contarlas, o peor, matarlas, sería exactamente el fallo que la sección 6
existe para prohibir.

El registro persistente de esta corrida vive en un temporal (`PUPPET_CLI_PROCESOS`): la
vara **no toca el `cli_procesos.jsonl` del usuario**.

    product/backend/.venv/bin/python platform/assembler/cli_brain/verify_cli_stopturn.py
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_ASM = _AQUI.parent
_RAIZ = _ASM.parents[1]
for _p in (str(_ASM), str(_RAIZ / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# El registro de ESTA corrida, en un temporal propio. Se setea ANTES de importar nada del
# paquete para que la ruta por defecto ni se calcule contra el data_root real.
_TMP = Path(tempfile.mkdtemp(prefix="vara-f2d-"))
os.environ["PUPPET_CLI_PROCESOS"] = str(_TMP / "cli_procesos.jsonl")

from cli_brain import base as B                       # noqa: E402
from cli_brain import detect as _detect               # noqa: E402
from cli_brain import lifecycle as L                  # noqa: E402
from cli_brain import registro as R                   # noqa: E402
from cli_brain import slots as S                      # noqa: E402
from cli_brain.claude_cli import ClaudeCliProvider    # noqa: E402
from cli_brain.server import create_server            # noqa: E402

sys.path.insert(0, str(_RAIZ / "qa" / "lib"))
import higiene_store as _HIG                          # noqa: E402

# [H1] El `mkdtemp` de `base.invoke` se borra solo; el ESPEJO que el CLI crea en
# `~/.claude/projects/` no. Barrido al salir, y sólo de lo que apareció acá.
_HIG.vigilar()

_fallos = 0
_salteados = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))


def saltear(nombre, motivo):
    global _salteados
    _salteados += 1
    print(f"  ⊘ {nombre}  →  SALTEADO: {motivo}")


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


print("=" * 80)
print("VARA F2d · DETENER UN TURNO · CIERRE CON DEADLINE · HUÉRFANOS")
print("=" * 80)

# ══ EL STUB ════════════════════════════════════════════════════════════════════════
# Se llama `claude` a propósito: la identidad del barrido mira el basename del binario
# anotado, y un stub llamado `stub.py` no probaría ese chequeo.
_STUB = r'''#!/usr/bin/env python3
"""Stub de `claude -p --output-format stream-json`. Emite eventos MEDIDOS (mismas formas
que el binario 2.1.220) y obedece al prompt: RAPIDO termina ya; TRAMPA atrapa SIGTERM.

SOBREVIVE A LA MUERTE DE SU PADRE, y no es un detalle del stub: es la condición que hace
existir al huérfano. Cuando el sidecar muere, el extremo de lectura del pipe se cierra y
la próxima escritura da EPIPE. Un proceso que se cae ahí no llega a ser huérfano nunca —
pero uno que ignora el error, o que simplemente estaba pensando sin escribir, sí. Ése es
el que el registro persistente existe para poder cazar, y por eso el stub lo modela.
"""
import json, signal, sys, time

argv = sys.argv[1:]
prompt = ""
for i, a in enumerate(argv):
    if a == "-p" and i + 1 < len(argv):
        prompt = argv[i + 1]

if "TRAMPA" in prompt:
    signal.signal(signal.SIGTERM, lambda *a: None)   # el que no se quiere morir

segundos = 0.0 if "RAPIDO" in prompt else 120.0


def emitir(o):
    try:
        sys.stdout.write(json.dumps(o) + "\n")
        sys.stdout.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass                                          # el padre murió; yo sigo (soy el huérfano)


emitir({"type": "system", "subtype": "init", "model": "claude-stub-real"})
emitir({"type": "stream_event", "event": {"type": "content_block_delta",
        "delta": {"type": "text_delta", "text": "OK"}}})
t0 = time.time()
while time.time() - t0 < segundos:
    time.sleep(0.2)
    emitir({"type": "stream_event", "event": {"type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "."}}})
emitir({"type": "result", "is_error": False, "subtype": "success", "result": "OK",
        "usage": {"input_tokens": 7, "output_tokens": 3},
        "modelUsage": {"claude-stub-real": {"inputTokens": 7, "outputTokens": 3}},
        "num_turns": 1})
'''

_BIN = _TMP / "claude"
_BIN.write_text(_STUB, encoding="utf-8")
_BIN.chmod(0o755)

# El hijo de la sección 5: hace UN turno real y se deja matar a la mitad.
_HIJO = _TMP / "hijo_turno.py"
_HIJO.write_text(f'''import os, sys
sys.path.insert(0, {str(_ASM)!r})
sys.path.insert(0, {str(_RAIZ / "platform")!r})
from cli_brain.claude_cli import ClaudeCliProvider
ClaudeCliProvider().invoke(os.environ["VARA_PROMPT"], turno_id=os.environ["VARA_TURNO"])
''', encoding="utf-8")

os.environ["PUPPET_CLAUDE_BIN"] = str(_BIN)


def marca_nueva(tag: str) -> str:
    return f"VARA-F2D-{tag}-" + uuid.uuid4().hex[:10]


def pids_con(marca: str) -> list:
    """Los pids cuya línea de comando lleva el marcador. `-ww` para que no trunque."""
    try:
        out = subprocess.run(["ps", "-ww", "-eo", "pid=,command="],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    fuera = []
    for linea in out.splitlines():
        if marca not in linea:
            continue
        cab = linea.strip().split(None, 1)
        if cab and cab[0].isdigit():
            fuera.append(int(cab[0]))
    return fuera


def esperar_pid(marca: str, *, tope: float = 30.0) -> list:
    fin = time.monotonic() + tope
    while time.monotonic() < fin:
        p = pids_con(marca)
        if p:
            return p
        time.sleep(0.1)
    return []


def esperar_muerte(marca: str, *, tope: float = 10.0) -> bool:
    fin = time.monotonic() + tope
    while time.monotonic() < fin:
        if not pids_con(marca):
            return True
        time.sleep(0.1)
    return not pids_con(marca)


def post(puerto, ruta, cuerpo, *, timeout=90):
    conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=timeout)
    conn.request("POST", ruta, json.dumps(cuerpo),
                 {"Content-Type": "application/json", "Host": f"127.0.0.1:{puerto}"})
    r = conn.getresponse()
    crudo = r.read().decode("utf-8", "replace")
    conn.close()
    try:
        return r.status, json.loads(crudo)
    except (json.JSONDecodeError, ValueError):
        return r.status, {"_crudo": crudo[:300]}


def get(puerto, ruta, *, timeout=20):
    conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=timeout)
    conn.request("GET", ruta, headers={"Host": f"127.0.0.1:{puerto}"})
    r = conn.getresponse()
    crudo = r.read().decode("utf-8", "replace")
    conn.close()
    try:
        return r.status, json.loads(crudo)
    except (json.JSONDecodeError, ValueError):
        return r.status, {"_crudo": crudo[:300]}


REG = R.RegistroCli(Path(os.environ["PUPPET_CLI_PROCESOS"]))

srv = create_server(0)
PUERTO = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
_guardado = dict(_detect._BY_MODEL_ID)
_detect._BY_MODEL_ID["claude-code-cli"] = ClaudeCliProvider()

try:
    # ══ 1 · TURNO REAL EN VUELO → STOP ═════════════════════════════════════════════
    seccion("1 · turno en vuelo → stop → muerto (ps) · slot libre · respuesta tipada")
    S.SLOTS.reiniciar()
    MARCA = marca_nueva("VUELO")
    TID = "turno-vara-" + uuid.uuid4().hex[:8]
    resp = {}

    def _turno_largo():
        resp["r"] = post(PUERTO, "/v1/chat/completions",
                         {"model": "claude-code-cli", "turno_id": TID,
                          "messages": [{"role": "user", "content": f"{MARCA} contá despacio"}]},
                         timeout=200)

    h = threading.Thread(target=_turno_largo, daemon=True)
    h.start()
    pids = esperar_pid(MARCA)
    ok(len(pids) == 1, f"el turno spawneó UN proceso con el marcador (pids={pids})", str(pids))

    st_l, cuerpo_l = get(PUERTO, "/v1/turnos")
    vivos = (cuerpo_l.get("turnos") or []) if st_l == 200 else []
    ok(any(t.get("turno_id") == TID and t.get("pid") for t in vivos),
       "GET /v1/turnos lo lista EN VUELO, con su pid", str(vivos))

    filas = REG.leer()
    ok(any(f.get("turno_id") == TID and f.get("estado") == "vivo" and f.get("pids")
           for f in filas),
       "y el registro persistente tiene su fila `vivo` con el pid", str(filas))
    fila_viva = next((f for f in filas if f.get("turno_id") == TID), {})
    ok(fila_viva.get("huella") and "--strict-mcp-config" in fila_viva["huella"],
       "con la HUELLA de flags nuestros (lo que después prueba la identidad)",
       str(fila_viva.get("huella")))
    ok(all(MARCA not in json.dumps(f) for f in filas),
       "y SIN una palabra del prompt: el registro guarda flags nuestros, no lo que el "
       "usuario escribió")

    st, r = post(PUERTO, "/v1/turnos/detener", {"turno_id": TID}, timeout=30)
    ok(st == 200, f"POST /v1/turnos/detener contesta 200 (dio {st})", str(r)[:120])
    ok(r.get("resultado") == B.TURNO_DETENIDO,
       "con el resultado TIPADO `turno_detenido`", str(r.get("resultado")))
    ok(r.get("senal") == "SIGTERM",
       "que murió con SIGTERM (no hizo falta escalar)", str(r.get("senal")))
    ok(r.get("vivo") is False and r.get("deadline_vencido") is False,
       "y el proceso está muerto, sin que venciera el deadline", str(r))
    ok(r.get("pid") in pids, "el pid que reporta es EL que estaba corriendo", str(r.get("pid")))
    ok(isinstance(r.get("esperado_s"), (int, float)) and r["esperado_s"] < 3,
       f"y contestó rápido ({r.get('esperado_s')}s): un SIGTERM obedecido no espera 5 s",
       str(r.get("esperado_s")))

    ok(esperar_muerte(MARCA), "EVIDENCIA ps: ya no queda ningún proceso con el marcador",
       str(pids_con(MARCA)))

    h.join(timeout=60)
    st_t, cuerpo_t = resp.get("r", (0, {}))
    ok(st_t == 409, f"el turno detenido responde 409, no 502 (dio {st_t})", str(cuerpo_t)[:150])
    err = cuerpo_t.get("error") or {}
    ok(err.get("error_kind") == B.ERR_DETENIDO and err.get("type") == "turno_detenido",
       "con `error_kind: detenido` y `type: turno_detenido` — el CLI no rechazó nada",
       str(err)[:150])
    ok(err.get("turno_id") == TID, "y el turno_id, para que se sepa cuál fue", str(err.get("turno_id")))
    # F1c · CAMBIO DE VEREDICTO DECLARADO. Salía SIN causa, y el motivo era no mentir:
    # el vocabulario sellado no tenía `turno_detenido`. Ahora lo tiene, así que sale CON
    # causa — un `causa: null` en un 409 le deja a la UI un rojo sin explicación, que es
    # la otra forma del fallo mudo.
    _cd = err.get("causa") or {}
    ok(_cd.get("causa") == "turno_detenido" and _cd.get("estado") == "roto",
       "CON causa tipada `turno_detenido` (F1c: antes salía sin causa)", str(_cd)[:150])
    ok(_cd.get("reintentable") is False,
       "y NO reintentable: reintentar lo que alguien paró es deshacer su decisión",
       str(_cd.get("reintentable")))
    ok((_cd.get("evidencia") or {}).get("detenido_por") == "usuario",
       "y la evidencia dice quién lo paró — no fue el proveedor ni el CLI",
       str(_cd.get("evidencia")))

    ok(S.SLOTS.estado()["activos"] == 0, "el slot de F2b quedó libre en el contador",
       str(S.SLOTS.estado()))
    ok(REG.leer() == [], "y el registro persistente quedó limpio", str(REG.leer()))

    # LA PRUEBA DE QUE EL SLOT ESTÁ LIBRE DE VERDAD: el turno siguiente entra.
    st2, c2 = post(PUERTO, "/v1/chat/completions",
                   {"model": "claude-code-cli",
                    "messages": [{"role": "user", "content": "RAPIDO"}]}, timeout=60)
    ok(st2 == 200, f"y el TURNO SIGUIENTE entra (200) — el slot se liberó de verdad", str(st2))
    ok((c2.get("choices") or [{}])[0].get("message", {}).get("content") == "OK",
       "devolviendo su respuesta normal", str(c2.get("choices"))[:100])
    ok((c2.get("aleph_cli_brain") or {}).get("turno_id"),
       "y el annex reporta el turno_id con el que se lo podía detener",
       str(c2.get("aleph_cli_brain")))

    # ══ 2 · STOP SIN TURNO ═════════════════════════════════════════════════════════
    seccion("2 · stop sin turno → no_habia_turno, y nada muere")
    MARCA_AJENO = marca_nueva("AJENO")
    ajeno = subprocess.Popen([str(_BIN), "-p", f"{MARCA_AJENO} soy de otro"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    esperar_pid(MARCA_AJENO)
    st, r = post(PUERTO, "/v1/turnos/detener", {"turno_id": "no-existe-este-turno"}, timeout=20)
    ok(st == 200 and r.get("resultado") == B.NO_HABIA_TURNO,
       "`no_habia_turno`, y con 200: pedir detener algo que ya terminó NO es un error",
       f"{st} {r}")
    ok(ajeno.poll() is None and pids_con(MARCA_AJENO),
       "y el proceso ajeno que estaba corriendo sigue VIVO", str(pids_con(MARCA_AJENO)))
    st, r = post(PUERTO, "/v1/turnos/detener", {}, timeout=20)
    ok(st == 400, "un `stop` sin `turno_id` es un 400, no un stop mudo", str(st))

    # ══ 3 · EL QUE IGNORA SIGTERM ══════════════════════════════════════════════════
    seccion("3 · proceso que atrapa SIGTERM → SIGKILL a los 5 s")
    S.SLOTS.reiniciar()
    MARCA_T = marca_nueva("TRAMPA")
    TID_T = "turno-trampa-" + uuid.uuid4().hex[:8]
    resp_t = {}

    def _turno_trampa():
        resp_t["r"] = post(PUERTO, "/v1/chat/completions",
                           {"model": "claude-code-cli", "turno_id": TID_T,
                            "messages": [{"role": "user", "content": f"{MARCA_T} TRAMPA"}]},
                           timeout=200)

    ht = threading.Thread(target=_turno_trampa, daemon=True)
    ht.start()
    pids_t = esperar_pid(MARCA_T)
    ok(len(pids_t) == 1, f"el stub que atrapa SIGTERM está corriendo (pids={pids_t})", str(pids_t))
    t0 = time.monotonic()
    st, r = post(PUERTO, "/v1/turnos/detener", {"turno_id": TID_T}, timeout=30)
    dt = time.monotonic() - t0
    ok(r.get("senal") == "SIGKILL",
       "el SIGTERM no alcanzó y se escaló a SIGKILL", str(r.get("senal")))
    ok(B.STOP_KILL_S <= dt < B.STOP_DEADLINE_S + 1.0,
       f"la escalada tardó {dt:.1f}s — después de los {B.STOP_KILL_S:.0f}s de SIGTERM y "
       f"antes del deadline de {B.STOP_DEADLINE_S:.0f}s", f"{dt:.2f}s")
    ok(r.get("vivo") is False and r.get("resultado") == B.TURNO_DETENIDO,
       "y el proceso está muerto igual", str(r))
    ok(esperar_muerte(MARCA_T), "EVIDENCIA ps: no quedó nada del stub", str(pids_con(MARCA_T)))
    ht.join(timeout=60)
    ok((resp_t.get("r") or (0, {}))[0] == 409, "el turno también vuelve 409",
       str(resp_t.get("r", (0, {}))[0]))
    ok(S.SLOTS.estado()["activos"] == 0, "sin slots colgados", str(S.SLOTS.estado()))

    # ── EL DEADLINE RESUELVE SIEMPRE ─────────────────────────────────────────────
    seccion("3b · el deadline resuelve SIEMPRE, aunque el proceso no se muera")
    MARCA_D = marca_nueva("DEADLINE")
    TID_D = "turno-deadline-" + uuid.uuid4().hex[:8]
    t_d = B.abrir_turno(TID_D, "claude_cli")
    proc_d = subprocess.Popen([str(_BIN), "-p", f"{MARCA_D} TRAMPA"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True)
    B._atar_proceso(t_d, proc_d)
    esperar_pid(MARCA_D)
    # SIGKILL "a los 99 s" = nunca dentro de este stop: sólo queda el deadline.
    t0 = time.monotonic()
    r = B.stop_turn(TID_D, kill_tras_s=99.0, deadline_s=1.0)
    dt = time.monotonic() - t0
    ok(dt < 2.0, f"con un deadline de 1 s, el stop volvió en {dt:.2f}s — jamás se cuelga",
       f"{dt:.2f}s")
    ok(r.get("resultado") == B.TURNO_DETENIDO and r.get("vivo") is True,
       "y NO miente: dice que el proceso sigue vivo", str(r))
    ok(r.get("deadline_vencido") is True,
       "declarando que lo que venció fue el deadline (no un false green)",
       str(r.get("deadline_vencido")))
    r2 = B.stop_turn(TID_D)                      # ahora sí, con los relojes de verdad
    ok(r2.get("vivo") is False, "y un segundo stop, con los relojes reales, sí lo mata",
       str(r2))
    B.cerrar_turno(TID_D)
    esperar_muerte(MARCA_D)

    # ── LA TRAMPA DEL FANTASMA ───────────────────────────────────────────────────
    seccion("3c · trampa del fantasma: detener un turno que todavía no spawneó")
    TID_F = "turno-fantasma-" + uuid.uuid4().hex[:8]
    t_f = B.abrir_turno(TID_F, "claude_cli")
    rf = B.stop_turn(TID_F)
    ok(rf.get("resultado") == B.TURNO_DETENIDO and rf.get("pid") is None,
       "el stop resuelve aunque no haya proceso al que matar", str(rf))
    ok(t_f.detener_pedido is True, "dejando el turno MARCADO")
    MARCA_F = marca_nueva("FANTASMA")
    proc_f = subprocess.Popen([str(_BIN), "-p", f"{MARCA_F} nazco tarde"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True)
    B._atar_proceso(t_f, proc_f)                 # es lo que hace `_run_streaming` al nacer
    ok(esperar_muerte(MARCA_F, tope=8.0),
       "y el proceso que nace después MUERE AL NACER (sin esto, el turno seguiría 180 s "
       "después de que el usuario apretó «detener»)", str(pids_con(MARCA_F)))
    B.cerrar_turno(TID_F)

    # ══ 4 · EL CIERRE CON DEADLINE ═════════════════════════════════════════════════
    seccion("4 · cierre de la app: fase crítica acotada, y DICE qué quedó colgado")

    class _ServerColgado:
        """`shutdown()` que no vuelve. Es el caso real: un handler bloqueado leyendo un
        CLI colgado no deja salir al loop de `serve_forever`."""

        def __init__(self):
            self.cerrado = False

        def shutdown(self):
            time.sleep(60)

        def server_close(self):
            self.cerrado = True

    lc = L.CliBrainLifecycle(0)
    lc._server, lc._thread, lc._mode = _ServerColgado(), None, "managed"
    t0 = time.monotonic()
    parte = lc.stop_detallado()
    dt = time.monotonic() - t0
    ok(dt < L.CIERRE_CRITICO_S + 2.0,
       f"un `shutdown()` eterno YA NO cuelga el cierre: volvió en {dt:.1f}s "
       f"(deadline {L.CIERRE_CRITICO_S:.0f}s)", f"{dt:.2f}s")
    ok(parte.get("colgado") == "server.shutdown",
       "y NOMBRA el paso colgado — sin eso, depurar un cierre eterno no tiene por dónde "
       "empezar", str(parte))

    lc2 = L.CliBrainLifecycle(0)
    parte2 = lc2.stop_detallado()
    ok(parte2.get("colgado") is None and isinstance(parte2.get("matados"), int),
       "un cierre normal no reporta nada colgado y devuelve cuántos CLI mató", str(parte2))
    ok(lc2.stop() == parte2["matados"] or isinstance(lc2.stop(), int),
       "y `stop()` sigue devolviendo un int (contrato que usa sidecar_serve)")

    # ══ 5 · MATAR EL SIDECAR CON UN TURNO VIVO ═════════════════════════════════════
    seccion("5 · sidecar muerto con un turno vivo → el jsonl lo registra → barrido")
    MARCA_H = marca_nueva("HUERFANO")
    TID_H = "turno-huerfano-" + uuid.uuid4().hex[:8]
    env_hijo = dict(os.environ)
    env_hijo["VARA_PROMPT"] = f"{MARCA_H} me van a dejar huérfano"
    env_hijo["VARA_TURNO"] = TID_H
    hijo = subprocess.Popen([sys.executable, str(_HIJO)], env=env_hijo,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    pids_h = esperar_pid(MARCA_H)
    ok(len(pids_h) == 1, f"el hijo lanzó su turno (pids={pids_h})", str(pids_h))
    filas = REG.leer()
    fila_h = next((f for f in filas if f.get("turno_id") == TID_H), None)
    ok(fila_h is not None and fila_h.get("pids") == pids_h,
       "el `cli_procesos.jsonl` tiene su fila con el pid REAL", str(filas))

    hijo.kill()                                  # el sidecar muere de golpe: sin finally
    hijo.wait(timeout=10)
    time.sleep(0.5)
    ok(pids_con(MARCA_H) == pids_h,
       "muerto el sidecar, el CLI queda HUÉRFANO y sigue vivo (el agujero de la fase)",
       str(pids_con(MARCA_H)))
    ok(REG.leer(), "y su fila sigue en el registro: es lo único que queda para encontrarlo",
       str(REG.leer()))

    parte = R.barrer_cli_al_arrancar(registro=REG)
    ok(parte.get("matados") == 1,
       "`barrer_cli_al_arrancar()` lo caza (identidad verificada)", str(parte))
    ok(esperar_muerte(MARCA_H), "EVIDENCIA ps: el huérfano murió", str(pids_con(MARCA_H)))
    ok(REG.leer() == [], "y el jsonl queda LIMPIO", str(REG.leer()))

    # ══ 6 · EL BARRIDO NO MATA A UN TERCERO ════════════════════════════════════════
    seccion("6 · el barrido JAMÁS mata un pid reciclado ni un `claude` ajeno")

    # (a) PID RECICLADO: el pid existe y el proceso es nuestro stub, pero arrancó MUCHO
    #     después de lo que dice el registro. Es el caso que la ventana de tiempo existe
    #     para descartar — y el que la primera versión del barrido del dueño dejaba pasar.
    MARCA_RE = marca_nueva("RECICLADO")
    reciclado = subprocess.Popen([str(_BIN), "-p", f"{MARCA_RE} --strict-mcp-config"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
    esperar_pid(MARCA_RE)
    REG.escribir([{"turno_id": "fantasma-viejo", "provider": "claude_cli", "estado": "vivo",
                   "binario": str(_BIN), "huella": ["--strict-mcp-config"],
                   "pids": [reciclado.pid], "pgid": reciclado.pid,
                   "nacido_en": time.time() - 3600}])
    parte = R.barrer_cli_al_arrancar(registro=REG)
    ok(parte.get("matados") == 0 and parte.get("ajenos") == 1,
       "un pid RECICLADO no se toca", str(parte))
    ok(parte.get("motivos", {}).get("pid_reciclado") == 1,
       "y el motivo queda por escrito: `pid_reciclado`", str(parte.get("motivos")))
    ok(reciclado.poll() is None and pids_con(MARCA_RE),
       "el proceso de ese pid sigue VIVO — matarlo sería matar a un tercero",
       str(pids_con(MARCA_RE)))

    # (b) UN `claude` AJENO: mismo binario, mismo nombre, hora correcta… pero sin nuestra
    #     huella de flags. Es la sesión que el usuario tiene abierta en otra terminal.
    MARCA_OTRO = marca_nueva("OTROCLAUDE")
    otro = subprocess.Popen([str(_BIN), "-p", f"{MARCA_OTRO} sesión de la persona"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    esperar_pid(MARCA_OTRO)
    REG.escribir([{"turno_id": "otro", "provider": "claude_cli", "estado": "vivo",
                   "binario": str(_BIN), "huella": ["--strict-mcp-config"],
                   "pids": [otro.pid], "pgid": otro.pid, "nacido_en": time.time()}])
    parte = R.barrer_cli_al_arrancar(registro=REG)
    ok(parte.get("matados") == 0 and parte.get("motivos", {}).get("otra_huella") == 1,
       "un `claude` AJENO (mismo binario y hora, sin nuestros flags) tampoco se toca",
       str(parte))
    ok(otro.poll() is None, "y sigue vivo: la sesión del usuario no se mata")

    # (c) SIN HUELLA: el basename solo NUNCA alcanza. `claude` es un nombre que la persona
    #     también usa; sin flags nuestros no hay identidad y no se mata.
    REG.escribir([{"turno_id": "sin-huella", "provider": "claude_cli", "estado": "vivo",
                   "binario": str(_BIN), "huella": [],
                   "pids": [otro.pid], "pgid": otro.pid, "nacido_en": time.time()}])
    parte = R.barrer_cli_al_arrancar(registro=REG)
    ok(parte.get("matados") == 0 and parte.get("motivos", {}).get("sin_huella") == 1,
       "una fila SIN huella no habilita a matar por nombre", str(parte))
    ok(otro.poll() is None, "y el proceso sigue vivo")

    # (d) FILA `naciendo` (sin pid): se REPORTA, no se inventa a quién matar.
    REG.escribir([{"turno_id": "naciendo", "provider": "claude_cli", "estado": "naciendo",
                   "binario": str(_BIN), "huella": ["--strict-mcp-config"], "pids": [],
                   "nacido_en": time.time()}])
    parte = R.barrer_cli_al_arrancar(registro=REG)
    ok(parte.get("sin_pid") == 1 and parte.get("matados") == 0,
       "una fila `naciendo` (sin pid) se REPORTA y no se barre", str(parte))

    for p in (reciclado, otro, ajeno):
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    # ══ 7 · IDENTIDAD, EN FRÍO ═════════════════════════════════════════════════════
    seccion("7 · `identidad_ok` — las tres condiciones, sin procesos de por medio")
    ahora = time.time()
    fila = {"binario": "/x/claude", "huella": ["--strict-mcp-config"], "nacido_en": ahora}
    linea = "claude -p hola --strict-mcp-config --no-session-persistence"
    ok(R.identidad_ok(fila, linea, ahora)[0] is True, "las tres condiciones juntas → sí")
    ok(R.identidad_ok(fila, linea, ahora + R.TOLERANCIA_S + 1)[1] == "pid_reciclado",
       "arrancó DESPUÉS de la ventana → pid_reciclado")
    ok(R.identidad_ok(fila, linea, ahora - R.TOLERANCIA_S - 1)[1] == "pid_reciclado",
       "y ANTES también: es una VENTANA, no un umbral (si fuera umbral, todo lo que "
       "arrancó después pasaría — que es justo el pid reciclado)")
    ok(R.identidad_ok(fila, "claude -p hola", ahora)[1] == "otra_huella",
       "sin nuestros flags → otra_huella (la sesión del usuario)")
    ok(R.identidad_ok(fila, "codex exec --strict-mcp-config", ahora)[1] == "otro_binario",
       "otro binario → otro_binario")
    ok(R.identidad_ok(fila, linea, None)[1] == "sin_hora_de_ps",
       "sin hora de `ps` no se mata: «no sé» es una respuesta, y del lado seguro")
    ok(R.identidad_ok({**fila, "huella": []}, linea, ahora)[1] == "sin_huella",
       "sin huella anotada tampoco")
    ok(R.huella_de(["/x/claude", "-p", "borrá --strict-mcp-config de tu vida",
                    "--strict-mcp-config", "--tools", ""]) == ["--strict-mcp-config"],
       "`huella_de` es una INTERSECCIÓN contra constantes nuestras: el prompt no se cuela",
       str(R.huella_de(["/x/claude", "-p", "borrá --strict-mcp-config de tu vida"])))

    # ══ 8 · EL CLI REAL ════════════════════════════════════════════════════════════
    seccion("8 · CLI REAL — un `claude -p` de verdad, detenido con evidencia `ps`")
    os.environ.pop("PUPPET_CLAUDE_BIN", None)
    if os.environ.get("SIN_CLI"):
        saltear("el stop contra el CLI real", "SIN_CLI=1")
    else:
        prov = ClaudeCliProvider()
        if not prov.binary():
            saltear("el stop contra el CLI real", "`claude` no está instalado")
        elif prov.detect().state != B.STATE_READY:
            saltear("el stop contra el CLI real", f"detect() = {prov.detect().state}")
        else:
            S.SLOTS.reiniciar()
            _detect._BY_MODEL_ID["claude-code-cli"] = prov
            os.environ["PUPPET_CLAUDE_CLI_MODEL"] = os.environ.get("VARA_CLI_MODELO", "haiku")
            MARCA_R = marca_nueva("REAL")
            TID_R = "turno-real-" + uuid.uuid4().hex[:8]
            resp_r = {}

            def _real():
                resp_r["r"] = post(
                    PUERTO, "/v1/chat/completions",
                    {"model": "claude-code-cli", "turno_id": TID_R, "stream": True,
                     "messages": [{"role": "user", "content":
                                   f"{MARCA_R} Escribí los números del 1 al 400, "
                                   f"uno por línea, sin comentar nada."}]},
                    timeout=300)

            hr = threading.Thread(target=_real, daemon=True)
            hr.start()
            pr = esperar_pid(MARCA_R, tope=60)
            ok(len(pr) >= 1, f"el `claude` real está en vuelo (pids={pr})", str(pr))
            if pr:
                time.sleep(2.0)          # que llegue a emitir de verdad
                filas_r = REG.leer()
                ok(any(f.get("turno_id") == TID_R and f.get("pids") for f in filas_r),
                   "el registro persistente lo tiene anotado", str(filas_r))
                t0 = time.monotonic()
                st, r = post(PUERTO, "/v1/turnos/detener", {"turno_id": TID_R}, timeout=30)
                dt = time.monotonic() - t0
                ok(r.get("resultado") == B.TURNO_DETENIDO and r.get("vivo") is False,
                   f"el stop lo mató de verdad en {dt:.1f}s", str(r))
                ok(esperar_muerte(MARCA_R, tope=15),
                   "EVIDENCIA ps: no queda ni un proceso `claude` de esta vara",
                   str(pids_con(MARCA_R)))
                hr.join(timeout=120)
                ok(S.SLOTS.estado()["activos"] == 0, "y el slot quedó libre",
                   str(S.SLOTS.estado()))
                st_n, c_n = post(PUERTO, "/v1/chat/completions",
                                 {"model": "claude-code-cli",
                                  "messages": [{"role": "user",
                                                "content": "Respondé exactamente: OK"}]},
                                 timeout=200)
                ok(st_n == 200, f"el turno siguiente contra el CLI real entra (dio {st_n})",
                   str(c_n)[:150])
                # LA COLA (2026-08-25) · esta aserción medía el registro EN EL INSTANTE en
                # que el turno devolvía, y eso dejó de ser el instante en que el CLI muere.
                # Desde que el turno cierra por evento terminal, el proceso vive ~0,5 s más
                # y **su fila tiene que vivir con él**: mientras el pid exista, esa fila es
                # el único rastro que un barrido de arranque podría seguir. La borra el
                # cosechador. La aserción no se afloja —el registro TIENE que quedar
                # limpio— sino que se le da el plazo de la agonía, con tope.
                _lim = time.monotonic() + 10.0
                while REG.leer() != [] and time.monotonic() < _lim:
                    time.sleep(0.05)
                ok(REG.leer() == [], "y el registro vuelve a quedar limpio (tras la cosecha)",
                   str(REG.leer()))
finally:
    _detect._BY_MODEL_ID.clear()
    _detect._BY_MODEL_ID.update(_guardado)
    S.SLOTS.reiniciar()
    for t in B.turnos_vivos():
        B.stop_turn(t.id)
        B.cerrar_turno(t.id)
    srv.shutdown()
    srv.server_close()
    shutil.rmtree(_TMP, ignore_errors=True)

# ══ 9 · LAS CINCO VARAS PREVIAS SIGUEN VERDES ══════════════════════════════════════
seccion("9 · las cinco varas previas de Gate 2 siguen verdes")
for nombre, ruta in (("verify_traductor", _ASM / "verify_traductor.py"),
                     ("verify_cli_streaming", _AQUI / "verify_cli_streaming.py"),
                     ("verify_cli_slots", _AQUI / "verify_cli_slots.py"),
                     ("verify_cli_usage", _AQUI / "verify_cli_usage.py"),
                     ("verify_adaptador_litellm", _ASM / "verify_adaptador_litellm.py")):
    env = dict(os.environ)
    env.pop("PUPPET_CLAUDE_BIN", None)           # que corran contra el CLI de verdad
    if os.environ.get("SIN_CLI"):
        env["SIN_CLI"] = "1"
    r = subprocess.run([sys.executable, str(ruta)], capture_output=True, text=True,
                       timeout=1800, env=env)
    ok(r.returncode == 0, f"{nombre}.py sale con exit 0",
       (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "")

# [H4a] El cierre pasa por `qa/lib/veredicto.py`: con salteos declarados la última
# línea ya NO es el string pelado `TODO VERDE`. La regla vive en un solo lugar.
sys.path.insert(0, str(_RAIZ / "qa" / "lib"))
import veredicto as _V  # noqa: E402

print(f"\n{_V.texto(_fallos, _salteados)}")
sys.exit(0 if _fallos == 0 else 1)
