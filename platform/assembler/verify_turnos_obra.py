#!/usr/bin/env python3
"""Vara única Gate 4 · Fase 5 · obra 5.2: PARAR UNA OBRA CON UNA TOOL CORRIENDO.

    python3 platform/assembler/verify_turnos_obra.py
    python3 platform/assembler/verify_turnos_obra.py --caer     # la prueba de caída

── QUÉ CIERRA ──────────────────────────────────────────────────────────────────────
El botón ⏹ **era decorativo en las obras**, y no fallaba: no existía. Medido:
`grep -n "turnos_http" executor.py recipe_assembler.py` → **0**, y en la cara
`pararTurno()` salía en su primera línea porque `ST.turnoId` sólo se llenaba desde el SSE
del CHAT. El usuario apretaba, la pantalla cerraba el turno, y del otro lado el motor
seguía: llamaba al modelo, ejecutaba tools, tocaba el mundo y cobraba.

── LO QUE MIDE, Y CÓMO ─────────────────────────────────────────────────────────────
A · el registro PURO: alias, hilo, la marca que sobrevive al cierre, la limpieza.
B · el CORTE FIRMADO: `origen: usuario` (D5) — distinguible de un deadline, de un
    `budget_exhausted` y de una caída de red. Un corte sin firma es un corte anónimo.
C · EL SOCKET DEL MODELO: un proveedor falso que se queda callado, un stop desde OTRO
    hilo, y la lectura que muere. Se mide que el socket se CIERRA, no que lo digamos.
D · EL LOOP REAL con el belt calc por stdio: la tool que ya arrancó TERMINA y queda
    registrada; la SIGUIENTE no arranca. El único stub es el LLM.
E · CERO HUÉRFANOS: se cuentan los procesos del MCP antes y después, con `ps`.
F · EL EXECUTOR con una DB SQLite TEMPORAL (jamás la del usuario): `runs.status` termina
    en `cancelado`, las `held_actions` NO quedan aprobables, el registro queda limpio.
G · D7 · el reloj de la tool: `call_tool` honra `rpc_timeout` (era 30 s inamovibles).
H · parar algo que YA terminó → `no_habia_turno`, sin cartel rojo.

── LA DB ES TEMPORAL, Y ESO NO ES UN DETALLE ───────────────────────────────────────
`PUPPET_SQLITE_PATH` apunta a un archivo de /tmp que esta vara crea y borra. Ya pasó dos
veces que una vara escribiera en la `aleph.db` REAL del usuario (`correr_varas.py`,
`suite_instalada.mjs`): acá se aísla explícito y se afirma que se aisló.

── LA PRUEBA DE CAÍDA ──────────────────────────────────────────────────────────────
`--caer` neutraliza el registro (`fue_detenido` siempre False, que es literalmente el
estado de main antes de esta obra) y EXIGE que las aserciones del corte se pongan rojas.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

import errores_modelo as E        # noqa: E402
import tool_result as TR          # noqa: E402
import turnos_obra as TO          # noqa: E402
import recipe_assembler as ra     # noqa: E402

REPO_ROOT = _THIS.parents[1]
CALC_BELT_REF = "platform/assembler/fixtures/belt-calc.mcp.json"

CAER = "--caer" in sys.argv

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if cond:
        _passed += 1
    else:
        _failed += 1


def caediza(name: str, cond: bool, detail: str = "") -> None:
    if CAER:
        check(f"[caída] NO se cumple sin el registro · {name}", not cond, detail)
    else:
        check(name, cond, detail)


def _neutralizar_registro():
    """La prueba de caída deja el motor EXACTAMENTE como estaba antes de esta obra.

    Son DOS cosas, y la primera versión sólo tapaba una: además de que nadie pueda decir
    que lo pararon (`fue_detenido`), en main **el socket del modelo no estaba atado a
    nada** — `_chat` hacía su `urlopen` y listo. Con sólo la primera, `detener()` seguía
    cerrando el socket y la aserción del tiempo seguía verde: la caída medía a medias y lo
    dijo (C1 cortaba igual a los 0,71 s).
    """
    orig = (TO.fue_detenido, TO.atar_socket)
    TO.fue_detenido = lambda *_a, **_k: False
    TO.atar_socket = lambda *_a, **_k: None
    return orig


# ══ A · EL REGISTRO, PURO ══════════════════════════════════════════════════════════

def bloque_A() -> None:
    TO.abrir("sp-A")
    check("A1 una obra abierta figura viva y NO detenida",
          any(o["handle"] == "sp-A" and not o["detenido"] for o in TO.vivas()))
    TO.ligar("sp-A", "run-A")
    check("A2 parar por `run_id` y parar por `space_id` son EL MISMO acto",
          TO.detener("run-A")["resultado"] == TO.TURNO_DETENIDO)
    check("A3 …y la marca se ve por las DOS llaves",
          TO.fue_detenido("sp-A") and TO.fue_detenido("run-A"))
    TO.cerrar("sp-A")
    check("A4 LA MARCA SOBREVIVE AL CIERRE (el motor puede enterarse tarde)",
          TO.fue_detenido("sp-A"))
    check("A5 …y el registro quedó limpio (un handle reusado no para una obra ajena)",
          all(o["handle"] != "sp-A" for o in TO.vivas()))
    check("A6 parar algo que nunca existió NO es un error",
          TO.detener("sp-que-no-existe")["resultado"] == TO.NO_HABIA_TURNO)
    check("A7 sin handle, todo es no-op (una vara o el CLI no se paran desde afuera)",
          TO.abrir(None) is None and TO.fue_detenido(None) is False)

    # el hilo se adueña
    TO.abrir("sp-hilo")
    TO.tomar("sp-hilo")
    check("A8 el motor pregunta SIN argumentos: el hilo sabe qué obra corre",
          TO.handle_del_hilo() == "sp-hilo" and TO.fue_detenido() is False)
    visto = {}

    def _otro_hilo():
        visto["desde_otro"] = TO.fue_detenido()      # sin handle propio → False
        TO.detener("sp-hilo")

    h = threading.Thread(target=_otro_hilo)
    h.start()
    h.join()
    check("A9 OTRO hilo puede pararla, y el hilo dueño se entera",
          visto["desde_otro"] is False and TO.fue_detenido() is True)
    TO.cerrar("sp-hilo")
    TO.soltar()


# ══ B · EL CORTE, FIRMADO ══════════════════════════════════════════════════════════

def bloque_B() -> None:
    check("B1 `usuario` es un origen VÁLIDO de la costura (D5)",
          TR.ORIGEN_USUARIO in TR._ORIGENES)
    firma = TR.CausaCostura(causa=E.TURNO_DETENIDO, origen=TR.ORIGEN_USUARIO,
                            reintentable=True, timeout_s=None, vencio_el_reloj=False,
                            detalle="Paraste este turno.")
    d = firma.como_dict()
    check("B2 el corte del usuario se firma con SU origen, no con `aleph`",
          d["origen"] == "usuario")
    check("B3 …y dice explícitamente que NO venció ningún reloj",
          d["vencio_el_reloj"] is False)
    check("B4 …con una causa del vocabulario CERRADO (cero causa nueva)",
          d["causa"] == "turno_detenido" and d["causa"] in E.CAUSAS)
    check("B5 …y reintentable: el turno no falló, lo pararon",
          d["reintentable"] is True)
    # y es distinguible de un deadline, que es la otra forma de cortar un run
    dl = TR.clasificar_error_de_tool(None, stop_reason="deadline").como_dict()
    check("B6 un DEADLINE se firma distinto — los dos cortes no se confunden",
          dl.get("origen") != "usuario" or dl.get("causa") != "turno_detenido",
          json.dumps(dl))
    check("B7 un origen inventado NO entra (el vocabulario sigue cerrado)",
          _levanta(lambda: TR.CausaCostura(causa=E.TURNO_DETENIDO, origen="cualquiera",
                                           reintentable=True, timeout_s=None,
                                           vencio_el_reloj=False, detalle="x")))


def _levanta(fn) -> bool:
    try:
        fn()
        return False
    except Exception:                                # noqa: BLE001
        return True


# ══ C · EL SOCKET DEL MODELO ═══════════════════════════════════════════════════════

class _Lento(BaseHTTPRequestHandler):
    """Manda las cabeceras y se queda callado: el `read()` del cliente queda esperando."""

    def do_POST(self):                                        # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "4096")            # promete cuerpo y no lo manda
        self.end_headers()
        try:
            self.wfile.flush()
            time.sleep(8)                                     # el stop tiene que llegar antes
        except Exception:                                     # noqa: BLE001
            pass

    def log_message(self, *_a):
        return


def bloque_C() -> None:
    srv = HTTPServer(("127.0.0.1", 0), _Lento)                # puerto 0: jamás uno fijo
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    TO.abrir("sp-socket")
    TO.tomar("sp-socket")

    def _parar():
        time.sleep(0.7)
        TO.detener("sp-socket")

    threading.Thread(target=_parar, daemon=True).start()
    t0 = time.monotonic()
    try:
        ra._asm._chat([{"role": "user", "content": "x"}], [], base, "m", "k", 32, 0.0)
        caediza("C1 la lectura se corta cuando paran la obra", False, "no cortó")
    except Exception as exc:                                  # noqa: BLE001
        dt = time.monotonic() - t0
        c = E.causa_de_excepcion(exc)
        caediza("C1 el socket del modelo SE CIERRA al parar (medido, no declarado)",
                dt < 5.0, f"cortó a los {dt:.2f}s (el server iba a callar 8s)")
        caediza("C2 …y el corte se lee `turno_detenido`, JAMÁS «se cayó la red»",
                c is not None and c.causa == E.TURNO_DETENIDO,
                getattr(c, "causa", type(exc).__name__))
    finally:
        TO.cerrar("sp-socket")
        TO.soltar()
        srv.shutdown()


# ══ D-E · EL LOOP REAL ═════════════════════════════════════════════════════════════

def _recipe() -> dict:
    return {
        "schema_version": "v1",
        "meta": {"name": "F5 corte", "nicho": "test"},
        "model": {"primary": "stub", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 128, "max_turns": 3},
        "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": ["add", "mul"]}},
        "framing": {"inline": "Sos un test."},
        "rag": {"enabled": False}, "keys": {}, "gates": {},
    }


def _tc(name, args, cid):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _procesos_calc() -> int:
    out = subprocess.run(["ps", "-Ao", "command"], capture_output=True, text=True)
    return sum(1 for l in out.stdout.splitlines() if "calc_server.py" in l)


def bloque_DE() -> None:
    antes = _procesos_calc()
    handle = "sp-loop"
    TO.abrir(handle)
    TO.tomar(handle)
    eventos: list = []

    def fake_chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kw):
        # UN turno con DOS tool-calls: la primera corre, y entre una y otra llega el stop.
        return {"choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": "",
            "tool_calls": [_tc("add", {"a": 2, "b": 3}, "c1"),
                           _tc("mul", {"a": 4, "b": 5}, "c2")]}}]}

    llamadas: list = []
    orig_call = ra.LazyToolRegistry.call
    orig_chat = ra._asm._chat

    def call_espia(self, tool_name, arguments):
        llamadas.append(tool_name)
        r = orig_call(self, tool_name, arguments)
        # El stop llega JUSTO DESPUÉS de que la primera tool terminó. Determinista a
        # propósito: con un `sleep` esto sería una carrera y una vara que a veces mide.
        if len(llamadas) == 1:
            TO.detener(handle)
        return r

    ra.LazyToolRegistry.call = call_espia
    ra._asm._chat = fake_chat
    try:
        # `approve` en True a propósito: sin `base_matrix` el gate retiene TODO por
        # fail-closed, y una tool retenida nunca llega a `registry.call`. Con el OK dado,
        # la aserción se vuelve la fuerte de verdad: **el corte le gana a la aprobación**
        # — la segunda tool estaba autorizada y aun así no arranca.
        out = ra.assemble_and_run(_recipe(), "sumá y multiplicá", repo_root=REPO_ROOT,
                                  approve=lambda _s, _t, _p: True,
                                  on_event=lambda e: eventos.append(e))
    finally:
        ra.LazyToolRegistry.call = orig_call
        ra._asm._chat = orig_chat
        TO.cerrar(handle)
        TO.soltar()

    check("D1 la tool que YA ARRANCÓ termina — parar no la deja a mitad "
          "(no depende del corte: se afirma que el corte NO la interrumpe)",
            llamadas[:1] == ["add"] and any(
                c.get("tool") == "add" and c.get("executed") for c in out["tool_calls"]),
            str(llamadas))
    caediza("D2 **la SIGUIENTE no arranca**: parar es una promesa cumplida",
            "mul" not in llamadas, str(llamadas))
    caediza("D3 el run cierra con la causa del vocabulario, no con un corte mudo",
            (out.get("causa") or {}).get("causa") == E.TURNO_DETENIDO,
            str((out.get("causa") or {}).get("causa")))
    caediza("D4 el corte va FIRMADO con origen `usuario` y dónde ocurrió",
            (out.get("corte") or {}).get("origen") == "usuario"
            and (out.get("corte") or {}).get("donde") == "antes_de_la_tool",
            json.dumps(out.get("corte")))
    caediza("D5 …y con la firma de costura, que dice que no venció ningún reloj",
            (out.get("stop_causa") or {}).get("vencio_el_reloj") is False)
    caediza("D6 la respuesta NO es un vacío opaco: dice lo que pasó",
            "araste" in (out.get("answer") or ""), repr(out.get("answer"))[:60])
    caediza("D7 el run NO gasta otra llamada al modelo para «cerrar honesto» "
            "después del botón",
          len([r for r in out["model_route"] if r.get("ok")]) == 1,
          json.dumps(out["model_route"]))

    # ── E · CERO HUÉRFANOS ────────────────────────────────────────────────────────
    time.sleep(0.6)                                   # que el `terminate` aterrice
    despues = _procesos_calc()
    check("E1 CERO procesos MCP huérfanos tras el corte (medido con `ps`, no declarado)",
          despues <= antes, f"antes={antes} después={despues}")
    check("E2 el espacio recibió eventos reales del turno (la línea no queda muda)",
          any(e.get("type") == "tool_call_finished" for e in eventos))


# ══ F · EL EXECUTOR, CON UNA DB TEMPORAL ═══════════════════════════════════════════

def bloque_F() -> None:
    tmp = tempfile.mkdtemp(prefix="f5-vara-")
    dbp = str(Path(tmp) / "aleph-vara.db")
    real = None
    try:
        real = _ap_user_db()
    except Exception:                                          # noqa: BLE001
        real = None
    prev = {k: os.environ.get(k) for k in ("PUPPET_SQLITE_PATH", "ALEPH_ROLE")}
    os.environ["PUPPET_SQLITE_PATH"] = dbp
    os.environ["ALEPH_ROLE"] = "client"
    sys.path.insert(0, str(REPO_ROOT / "product" / "backend"))
    try:
        from app.phase1 import repo as _repo, executor as _ex
        check("F0 la vara NO escribe en la DB del usuario (aislada en /tmp)",
              real is None or os.path.abspath(dbp) != os.path.abspath(real),
              f"vara={dbp}")
        _repo.asegurar_schema_cliente()

        handle = "sp-exec"
        eventos: list = []
        llamadas: list = []
        # ⚠️ EL EXECUTOR CARGA SU PROPIA COPIA del assembler (`load_module_by_path` crea un
        # módulo nuevo: `puppet_recipe_assembler` + `puppet_assembler_base`), así que
        # parchar el `ra` de esta vara NO lo tocaría y el stub no tomaría — la corrida
        # anterior lo midió con `tool_calls: []`. Se parcha SU árbol.
        # El registro de turnos, en cambio, SÍ es compartido: los dos hacen `import
        # turnos_obra` a secas y eso resuelve por `sys.modules`. Que sean dos assemblers y
        # UN registro es justo lo que esta obra necesita, y acá queda medido.
        _ra = _ex._asm()
        check("F0b el executor y esta vara comparten EL MISMO registro de turnos "
              "(dos copias del motor, un solo registro)",
              _ra.__dict__.get("_turnos_obra") is TO and _ex._turnos_obra is TO)
        orig_call = _ra.LazyToolRegistry.call
        orig_chat = _ra._asm._chat

        def fake_chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kw):
            return {"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": "",
                "tool_calls": [_tc("add", {"a": 1, "b": 1}, "c1"),
                               _tc("mul", {"a": 2, "b": 2}, "c2")]}}]}

        def call_espia(self, tool_name, arguments):
            llamadas.append(tool_name)
            r = orig_call(self, tool_name, arguments)
            if len(llamadas) == 1:
                _ex._turnos_obra.detener(handle)
            return r

        _ra.LazyToolRegistry.call = call_espia
        _ra._asm._chat = fake_chat
        try:
            out = _ex.run_puppet_e2e(_recipe(), "sumá", space_id=handle,
                                     deadline_s=60.0,
                                     approve=lambda _s, _t, _p: True,
                                     on_event=lambda e: eventos.append(e))
        finally:
            _ra.LazyToolRegistry.call = orig_call
            _ra._asm._chat = orig_chat

        caediza("F1 el executor marca el run como CANCELADO", bool(out.get("cancelado")))
        rid = out.get("run_id")
        estado = None
        c = _repo.get_conn()
        try:
            with c.cursor() as cur:
                cur.execute("SELECT status FROM runs WHERE id = %s", (str(rid),))
                fila = cur.fetchone()
                estado = (dict(fila) if not isinstance(fila, (list, tuple)) else fila)
                estado = estado["status"] if isinstance(estado, dict) else fila[0]
        finally:
            c.close()
        caediza("F2 `runs.status` TERMINA — y termina en `cancelado`, no en `error` "
                "(que mentiría) ni en `running` (que es el bug)",
                estado == "cancelado", f"status={estado}")
        check("F3 el registro quedó limpio: cero obras vivas tras el run",
              all(o["handle"] != handle for o in _ex._turnos_obra.vivas()))
        cerrados = [e for e in eventos if e.get("type") == "closed"]
        check("F4 el espacio CIERRA (sin terminal, todo artefacto del turno queda colgado)",
              len(cerrados) == 1)
        caediza("F5 …y el terminal lleva la causa firmada, no un rojo anónimo",
                bool(cerrados) and cerrados[0].get("cancelado") is True
                and (cerrados[0].get("causa") or {}).get("causa") == E.TURNO_DETENIDO)

        # ── H6 · LAS HELD DE UN RUN PARADO, con su propio run ────────────────────
        # El escenario real, y el peor de los estados falsos que la auditoría inventarió:
        # el gate RETIENE una acción y le muestra la tarjeta al dueño… y el dueño, en vez
        # de aprobarla, **aprieta parar**. Si esa held se persiste igual, queda un botón
        # vivo que puede ejecutarla media hora después — mandar el correo que el usuario
        # canceló, con un OK sobre un turno que ya no existe.
        # Sin `approve` el gate retiene todo por fail-closed, así que acá no hace falta
        # fabricar nada: el corte llega en el PRIMER `gate_waiting`, que es exactamente
        # cuando la persona ve la tarjeta.
        h2 = "sp-held"
        ev2: list = []

        def _al_evento(e):
            ev2.append(e)
            if e.get("type") == "gate_waiting":
                _ex._turnos_obra.detener(h2)

        _ra._asm._chat = fake_chat
        try:
            out2 = _ex.run_puppet_e2e(_recipe(), "sumá", space_id=h2, deadline_s=60.0,
                                      on_event=_al_evento)
        finally:
            _ra._asm._chat = orig_chat

        check("F6a el gate SÍ retuvo (sin retención no habría nada que medir)",
              any(e.get("type") == "gate_waiting" for e in ev2)
              and bool((out2.get("record") or {}).get("held_actions")),
              f"gate_waiting={sum(1 for e in ev2 if e.get('type')=='gate_waiting')}")
        c = _repo.get_conn()
        try:
            with c.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM held_actions WHERE run_id = %s",
                            (str(out2.get("run_id")),))
                n = list(cur.fetchone())[0]
        finally:
            c.close()
        caediza("F6b una obra parada NO deja acciones aprobables en la DB "
                "(un OK posterior ejecutaría lo que el usuario canceló)",
                int(n) == 0, f"held persistidas={n}")
        caediza("F6c …y se dice CUÁLES no se persistieron (nada desaparece en silencio)",
                bool(out2.get("held_no_persistidas")),
                json.dumps(out2.get("held_no_persistidas"))[:120])

        # H · parar lo que ya terminó
        r = _ex._turnos_obra.detener(handle)
        check("H1 parar un turno que ya terminó → `no_habia_turno` (no es un error)",
              r["resultado"] == _ex._turnos_obra.NO_HABIA_TURNO)
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            for f in Path(tmp).glob("*"):
                f.unlink()
            Path(tmp).rmdir()
        except Exception:                                      # noqa: BLE001
            pass


def _ap_user_db() -> str:
    sys.path.insert(0, str(REPO_ROOT / "platform"))
    import aleph_paths
    return str(aleph_paths.user_data_dir() / "aleph.db")


# ══ G · D7 · EL RELOJ DE LA TOOL ═══════════════════════════════════════════════════

def bloque_G() -> None:
    src = (REPO_ROOT / "platform" / "assembler" / "assembler.py").read_text()
    i = src.find("def call_tool(")
    cuerpo = src[i:i + 1400]
    check("G1 `call_tool` le pasa `self._rpc_timeout` a `_rpc` (antes: 30 s inamovibles)",
          "timeout=self._rpc_timeout" in cuerpo)
    # …y se mide de verdad: un server que tarda 1,2 s con un reloj de 0,3 s no contesta,
    # y con uno de 5 s sí. Si el parámetro no gobernara, los dos casos darían lo mismo.
    lento = _THIS / "fixtures" / "_f5_tool_lenta.py"
    lento.write_text(
        "import json,sys,time\n"
        "def s(o):sys.stdout.write(json.dumps(o)+'\\n');sys.stdout.flush()\n"
        "for line in sys.stdin:\n"
        "    r=json.loads(line);m=r.get('method')\n"
        "    if m=='initialize': s({'jsonrpc':'2.0','id':r['id'],'result':"
        "{'protocolVersion':'2024-11-05','capabilities':{'tools':{}},"
        "'serverInfo':{'name':'lenta','version':'1'}}})\n"
        "    elif m=='tools/list': s({'jsonrpc':'2.0','id':r['id'],'result':{'tools':"
        "[{'name':'dormir','description':'d','inputSchema':{'type':'object','properties':{}}}]}})\n"
        "    elif m=='tools/call':\n"
        "        time.sleep(1.2)\n"
        "        s({'jsonrpc':'2.0','id':r['id'],'result':{'content':[{'type':'text','text':'desperté'}]}})\n",
        encoding="utf-8")
    try:
        for reloj, espera in ((0.3, False), (5.0, True)):
            srv = ra._asm.MCPServer("lenta", "python3", [str(lento)], rpc_timeout=reloj)
            try:
                srv.start()
                r = srv.call_tool("dormir", {})
                ok = ("desperté" in r)
                check(f"G{2 if not espera else 3} con reloj de {reloj}s la tool de 1,2s "
                      + ("NO contesta" if not espera else "SÍ contesta"),
                      ok is espera, r[:60])
            finally:
                srv.stop()
    finally:
        try:
            lento.unlink()
        except Exception:                                      # noqa: BLE001
            pass


def main() -> int:
    print("=== Gate 4 · F5 · 5.2 · cancelación en vuelo"
          + (" · PRUEBA DE CAÍDA (registro neutralizado)" if CAER else "") + " ===\n")
    orig = _neutralizar_registro() if CAER else None
    try:
        if not CAER:
            bloque_A()
            bloque_B()
        bloque_C()
        bloque_DE()
        bloque_F()
        if not CAER:
            bloque_G()
    finally:
        if orig is not None:
            TO.fue_detenido, TO.atar_socket = orig
    print(f"\n=== {_passed} passed, {_failed} failed ===")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
