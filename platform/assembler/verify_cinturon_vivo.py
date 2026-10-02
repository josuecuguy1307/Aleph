#!/usr/bin/env python3
"""verify_cinturon_vivo.py — ¿el turno DICE algo mientras arranca el cinturón?

EL AGUJERO QUE CIERRA, medido en la Sala en frío (censo por parentesco, 2026-08-25):

    +0 s      el usuario manda el turno · la pantalla dice «Pensando…»
    +4,4 s    nace el primer lanzador del cinturón   ← nadie lo sabe
    +33,2 s   nace el último                          ← nadie lo sabe
    +39,6 s   vuelve la primera llamada al modelo → PRIMER EVENTO del backend (`cost`)

O sea: **34-58 s de una sola frase quieta**. Y peor, silencioso: `GET /v1/spaces/{id}/stream`
devuelve 404 hasta que el run crea su `events.jsonl` (`aleph-agent.js:434`), y su reintento
tiene un plazo de 20 s — con el cinturón frío el espinazo se agotaba ANTES de existir y el
turno entero corría a ciegas, sin vivo, sin tools, sin nada.

`session.py:421` ya emitía `belt_ready` y el traductor del frente ya lo sabía pintar
(`aleph-agent.js:503`). La Sala **no pasa por `session.py`**: pasa por `recipe_assembler`,
que no lo emitía. El frente estaba listo hace meses esperando un evento que nadie mandaba.

CERO TEATRO — y esta vara existe para probar justamente eso:
  · el estado enciende con `belt_starting` y apaga con `belt_ready`, dos sucesos REALES
  · sin esos eventos la línea NO se mueve sola (caso C2: es lo que separa esto de un timer)
  · el número de piezas sale del evento; sin dato, la frase va sin número (nunca «(0)»)

  A · `belt_starting` es el PRIMER evento del run y llega en milisegundos, no en decenas
      de segundos — con un cinturón que tarda de verdad (fixture que duerme)
  B · `belt_ready` llega DESPUÉS del cinturón, con los nombres y las tools REALES
  C · la máquina del frente hace el recorrido, y NO lo hace sin los eventos
  D · el `ms` que viaja es el arranque medido, no una cuenta del frente

    python3 platform/assembler/verify_cinturon_vivo.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
REPO_ROOT = _AQUI.parents[1]

import recipe_assembler as ra                                       # noqa: E402

_FALLOS, _OK = [], 0
#: cuánto duerme el fixture en su saludo. Tiene que ser GRANDE respecto de lo que tarda
#: `belt_starting` (milisegundos) para que la separación no se pueda leer como ruido.
DORMIR_S = 1.2
SALA = Path(__file__).resolve().parents[1] / "app" / "design" / "sala-v2"
SALA = REPO_ROOT / "product" / "app" / "design" / "sala-v2"


def ok(c, t, d=""):
    global _OK
    if c:
        _OK += 1
        print(f"  ✅ {t}")
    else:
        _FALLOS.append(t)
        print(f"  ❌ {t}" + (f" — {d}" if d else ""))


def _belt_lento(tmp: Path, n: int) -> str:
    """Un belt de `n` piezas que duermen `DORMIR_S` en el saludo."""
    fixture = REPO_ROOT / "platform" / "inspection" / "fixtures_cinturon" / "mcp_lento.py"
    servers = {}
    for i in range(n):
        servers[f"lenta{i}"] = {
            "command": sys.executable,
            "args": [str(fixture)],
            "env": {"ALEPH_MCP_LENTO_S": str(DORMIR_S)},
            "description": f"fixture lenta {i}",
        }
    # `belt_ref` se resuelve contra el repo, así que el archivo tiene que vivir adentro.
    # Se borra al salir (el `tmp` que recibe es sólo el nombre único de la corrida).
    ruta = REPO_ROOT / "platform" / "assembler" / "fixtures" / f"belt-lento-{tmp.name}-{n}.mcp.json"
    ruta.write_text(json.dumps({"mcpServers": servers, "_meta": {"slug": "lento"}}))
    return str(ruta.relative_to(REPO_ROOT))


def _receta(belt_ref: str, filtros: dict) -> dict:
    return {
        "schema_version": "v1",
        "meta": {"name": "Cinturon Vivo", "nicho": "test"},
        "model": {"primary": "stub-model", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 64, "max_turns": 2},
        "belt": {"belt_ref": belt_ref, "tool_filters": filtros},
        "framing": {"inline": "Sos un test."},
        "rag": {"enabled": False}, "keys": {}, "gates": {},
    }


def _chat_que_tarda(demora_s: float):
    """El modelo TAMBIÉN tarda: si contestara instantáneo, `belt_ready` y el primer evento
    del modelo caerían en el mismo milisegundo y el caso A no podría separarlos."""
    def fake_chat(*a, **k):
        time.sleep(demora_s)
        return {"choices": [{"finish_reason": "stop",
                             "message": {"role": "assistant", "content": "listo"}}]}
    return fake_chat


# ══════════════════════════════════════════════════════════════════════════════════
# A y B · EL BACKEND — el camino que corre la Sala, con un cinturón que tarda de verdad
# ══════════════════════════════════════════════════════════════════════════════════
def caso_AB():
    print("\n[A/B] el backend emite los dos bordes, y el primero llega en milisegundos")
    import tempfile
    N = 4
    _sucios: list[Path] = []
    with tempfile.TemporaryDirectory() as td:
        belt = _belt_lento(Path(td), N)
        _sucios.append(REPO_ROOT / belt)
        eventos: list[tuple[float, dict]] = []
        t0 = time.time()

        def on_event(ev):
            eventos.append((time.time() - t0, ev if isinstance(ev, dict) else {"type": str(ev)}))

        orig = ra._asm._chat
        ra._asm._chat = _chat_que_tarda(0.8)
        try:
            out = ra.assemble_and_run(
                _receta(belt, {f"lenta{i}": ["nada"] for i in range(N)}),
                "hola", repo_root=REPO_ROOT, on_event=on_event)
        finally:
            ra._asm._chat = orig
            for _s in _sucios:
                _s.unlink(missing_ok=True)

    tipos = [e.get("type") for _, e in eventos]
    if out.get("error"):
        ok(False, "A0 el run corrió (sin él no hay nada que medir)", f"error={out['error']}")
        return None
    ok(True, f"A0 el run corrió · {len(eventos)} eventos: {tipos[:6]}")

    # A1 · `belt_starting` es EL PRIMERO. No «está»: es el primero.
    ok(bool(tipos) and tipos[0] == "belt_starting",
       "A1 `belt_starting` es el PRIMER evento del run", f"primero={tipos[0] if tipos else None}")

    t_start = next((t for t, e in eventos if e.get("type") == "belt_starting"), None)
    t_ready = next((t for t, e in eventos if e.get("type") == "belt_ready"), None)
    ok(t_start is not None and t_start < 0.5,
       f"A2 llega en milisegundos, no en decenas de segundos ({(t_start or -1)*1000:.0f} ms)",
       f"t={t_start}")

    # A3 · Y llega ANTES de que el cinturón termine: si saliera después, no serviría de nada.
    ok(t_ready is not None and t_start is not None and t_ready > t_start + DORMIR_S * 0.5,
       f"A3 el cinturón tarda de verdad y `belt_starting` lo precede "
       f"(start={(t_start or 0)*1000:.0f} ms · ready={(t_ready or 0)*1000:.0f} ms)",
       f"start={t_start} ready={t_ready}")

    ready = next((e for _, e in eventos if e.get("type") == "belt_ready"), None)
    ok(ready is not None, "B1 `belt_ready` sale")
    if ready:
        ok(sorted(ready.get("servers") or []) == sorted(f"lenta{i}" for i in range(N)),
           f"B2 lleva los servers REALES ({ready.get('servers')})")
        ok(len(ready.get("tools") or []) == N,
           f"B3 lleva las tools cableadas ({len(ready.get('tools') or [])} de {N})",
           f"tools={ready.get('tools')}")
        # D · el `ms` es medición, no adorno: tiene que parecerse al retardo del fixture.
        ms = ready.get("ms")
        ok(isinstance(ms, int) and ms >= DORMIR_S * 1000 * 0.8,
           f"D1 el `ms` es el arranque MEDIDO ({ms} ms · el fixture duerme {int(DORMIR_S*1000)})",
           f"ms={ms}")

    # A4 · y todo esto pasa ANTES del primer evento que depende del modelo.
    _del_modelo = [t for t, e in eventos
                   if e.get("type") in ("cost", "turn_started", "final", "closed")]
    if _del_modelo and t_start is not None:
        ok(min(_del_modelo) > t_start,
           f"A4 el primer evento del modelo llega {(min(_del_modelo)-t_start)*1000:.0f} ms "
           f"después — esa era LA VENTANA MUDA")
    else:
        ok(False, "A4 [no medible] no hubo evento derivado del modelo en esta corrida",
           f"tipos={tipos}")
    return eventos


# ══════════════════════════════════════════════════════════════════════════════════
# C · EL FRENTE — el traductor y la máquina, incluido el caso «sin evento, sin dibujo»
# ══════════════════════════════════════════════════════════════════════════════════
_JS = r"""
import { MaquinaDeEstados, ESTADO, copyDe } from "%(sala)s/agui/estados.js";

const linea = [];
const M = new MaquinaDeEstados((v) => linea.push([v.estado, v.texto]));

// EL RECORRIDO CON LOS EVENTOS
M.consumir({ type: "RUN_STARTED" });
M.consumir({ type: "CUSTOM", name: "aleph.cinturon", value: { listo: false, piezas: 8 } });
M.consumir({ type: "CUSTOM", name: "aleph.cinturon", value: { listo: true, tools: 25 } });
M.consumir({ type: "TOOL_CALL_START", toolCallName: "read_text_file" });

// SIN LOS EVENTOS: la línea NO puede llegar sola al cinturón. Esto es lo que separa
// un estado de un timer, y es el caso que mata al mutante «lo pinto con setTimeout».
const solo = [];
const M2 = new MaquinaDeEstados((v) => solo.push(v.estado));
M2.consumir({ type: "RUN_STARTED" });
M2.consumir({ type: "CUSTOM", name: "aleph.costo", value: {} });
M2.consumir({ type: "TEXT_MESSAGE_CONTENT", delta: "x" });

// EL NÚMERO SALE DEL EVENTO. Sin dato no se inventa uno.
const conN  = copyDe(ESTADO.CINTURON, { piezas: 8 });
const sinN  = copyDe(ESTADO.CINTURON, {});

console.log(JSON.stringify({ linea, solo, conN, sinN }));
"""

# El traductor NO se puede importar en node crudo: `aleph-agent.js` arrastra el bundle de
# assistant-ui, que es código de navegador y explota al evaluarse fuera de uno (medido:
# `node rc=1` en la primera corrida de esta vara). Así que se lo mide DONDE VIVE — en un
# navegador de verdad, con un server estático mínimo. Sin backend: al traductor se le dan
# los eventos a mano y se miran los CUSTOM que salen.
_JS_TRAD = r"""
import { AlephAgent } from "/agui/aleph-agent.js";
const salidos = [];
const emisor = { paso: () => {}, pasoFin: () => {}, aleph: (n, v) => salidos.push([n, v]) };
const a = Object.create(AlephAgent.prototype);
a._traducirEspinazo(emisor, { type: "belt_starting", piezas: 8 });
a._traducirEspinazo(emisor, { type: "belt_ready", servers: ["a", "b"],
                              tools: ["t1", "t2", "t3"], servers_skipped: [], ms: 1234 });
window.__RESULTADO__ = JSON.stringify(salidos);
"""


def _en_navegador(src: str):
    """Corre un módulo ES contra los archivos REALES de la Sala, en webkit."""
    import http.server, socketserver, threading, functools
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SALA))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as srv:
        srv.allow_reuse_address = True
        puerto = srv.server_address[1]
        hilo = threading.Thread(target=srv.serve_forever, daemon=True)
        hilo.start()
        js = _AQUI / "_cinturon_vivo_tmp.mjs"
        pagina = SALA / "_cinturon_vivo_tmp.html"
        pagina.write_text(f"<!doctype html><meta charset=utf-8>"
                          f"<script type=module>{src}</script>")
        try:
            r = subprocess.run(
                [os.environ.get("NODE", "node"), "--input-type=module", "-e", f"""
import {{ webkit }} from "playwright";
const b = await webkit.launch();
const p = await b.newPage();
const errs = [];
p.on("pageerror", (e) => errs.push(String(e)));
await p.goto("http://127.0.0.1:{puerto}/_cinturon_vivo_tmp.html");
await p.waitForFunction(() => window.__RESULTADO__ !== undefined, {{ timeout: 15000 }})
   .catch(() => {{}});
const r = await p.evaluate(() => window.__RESULTADO__ ?? null);
await b.close();
console.log(JSON.stringify({{ r, errs }}));
"""], capture_output=True, text=True, timeout=90, cwd=str(SALA))
        finally:
            pagina.unlink(missing_ok=True)
            js.unlink(missing_ok=True)
            srv.shutdown()
    if r.returncode != 0:
        falta = "ERR_MODULE_NOT_FOUND" in r.stderr and "playwright" in r.stderr
        return "SIN_PLAYWRIGHT" if falta else None
    try:
        salida = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(f"     (salida ilegible) {r.stdout[-300:]}")
        return None
    if salida.get("errs"):
        print(f"     (pageerror) {salida['errs'][:2]}")
    return json.loads(salida["r"]) if salida.get("r") else None


def _node(src: str) -> dict | list | None:
    try:
        r = subprocess.run([os.environ.get("NODE", "node"), "--input-type=module",
                            "-e", src % {"sala": SALA.as_posix()}],
                           capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return None
    if r.returncode != 0:
        print(f"     (node rc={r.returncode}) {r.stderr.strip()[:400]}")
        return None
    return json.loads(r.stdout.strip().splitlines()[-1])


def caso_C():
    print("\n[C] el frente: el traductor, la máquina, y «sin evento no hay dibujo»")
    tr = _en_navegador(_JS_TRAD)
    if tr == "SIN_PLAYWRIGHT":
        # [NO MEDIBLE] CON MOTIVO, no una verde regalada. `aleph-agent.js` importa el bundle
        # de assistant-ui, que es código de navegador: fuera de uno el módulo ni evalúa. El
        # único juez posible es un navegador de verdad, y esta máquina no tiene playwright.
        # MEDIDO A MANO el 2026-08-26 sirviendo `product/app/design` y abriendo la página en
        # un navegador real: salen los DOS `aleph.cinturon`, el de apertura con
        # `{listo:false, piezas:8}` y el de cierre con `{listo:true, tools:3, ms:1234}`.
        # Instalando playwright esta rama corre sola y el caso deja de ser declarativo.
        print("  ⚠️  C0 [NO MEDIBLE ACÁ] playwright no está instalado — el traductor sólo se "
              "puede juzgar en un navegador (medido a mano: los dos CUSTOM salen bien)")
    elif tr is None:
        ok(False, "C0 [no medible] el navegador no corrió el traductor")
    else:
        nombres = [n for n, _ in tr]
        ok(nombres.count("aleph.cinturon") == 2,
           f"C1 los dos bordes salen como `aleph.cinturon` ({nombres})")
        if nombres.count("aleph.cinturon") == 2:
            v0 = tr[0][1]
            v1 = tr[-1][1]
            ok(v0.get("listo") is False and v0.get("piezas") == 8,
               f"C2 el de apertura lleva las piezas ({v0})")
            ok(v1.get("listo") is True and v1.get("tools") == 3 and v1.get("ms") == 1234,
               f"C3 el de cierre lleva el conteo y el `ms` del backend ({v1})")

    m = _node(_JS)
    if m is None:
        ok(False, "C4 [no medible] node no corrió la máquina")
        return
    estados = [e for e, _ in m["linea"]]
    ok(estados == ["pensando", "cinturon", "pensando", "preparando"],
       f"C4 el recorrido es el esperado ({estados})")
    ok(any(t == "Preparando las herramientas (8)…" for _, t in m["linea"]),
       f"C5 y lo dice con el número REAL del evento ({[t for _,t in m['linea']]})")
    # EL CASO QUE MATA AL TIMER
    ok("cinturon" not in m["solo"],
       f"C6 SIN los eventos la línea nunca llega al cinturón — no hay timer ({m['solo']})")
    ok(m["conN"] == "Preparando las herramientas (8)…"
       and m["sinN"] == "Preparando las herramientas…",
       f"C7 sin dato la frase va SIN número, no con «(0)» ({m['sinN']!r})")


# ══════════════════════════════════════════════════════════════════════════════════
# E · EL EVENTO TIENE QUE SOBREVIVIR AL CAMINO REAL, no sólo al callback
# ══════════════════════════════════════════════════════════════════════════════════
# ESTE CASO EXISTE PORQUE LA VARA PASÓ EN VERDE CON EL BUG PUESTO.
#
# Los casos A/B le dan a `assemble_and_run` un `on_event` de mentira que sólo appendea
# a una lista, así que medían que el evento SE EMITE — no que LLEGA. En el producto el
# `on_event` real es `_make_space_emitter` (`run_handler.py:24`), que escribe por
# `EventLog.append`, y ése VALIDA `type` contra la taxonomía `EVENT_TYPES`.
#
# MEDIDO EN VIVO el 2026-08-26 contra la .app instalada: `belt_ready` llegaba (estaba en
# la taxonomía desde `session.py`) y `belt_starting` NO — lo rechazaba el validador, y
# `_make_space_emitter` se comía la excepción con un `except Exception: pass`. El evento
# desaparecía MUDO y la Sala volvía a callar los 25 s enteros.
#
# Es la regla sellada: correr una PIEZA no concluye sobre el SISTEMA.
def caso_E():
    print("\n[E] los tipos que emite el assembler entran en la taxonomía REAL del EventLog")
    import importlib.util
    ruta = REPO_ROOT / "platform" / "flywheel" / "events_replay.py"
    spec = importlib.util.spec_from_file_location("events_replay_vara", ruta)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:                                          # noqa: BLE001
        ok(False, "E0 [no medible] no pude cargar events_replay", str(e)[:120])
        return

    # NO se leen de `EVENT_TYPES` —eso sería preguntarle al acusado—: son los tipos que
    # `recipe_assembler` emite para el cinturón, escritos acá a mano.
    EMITE = ["belt_starting", "belt_ready"]
    faltan = [t for t in EMITE if t not in mod.EVENT_TYPES]
    ok(not faltan, f"E1 los {len(EMITE)} tipos del cinturón están en la taxonomía",
       f"FALTAN: {faltan}")

    # Y la prueba dura: escribir de verdad por el mismo camino del producto.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        log = mod.EventLog(Path(td) / "events.jsonl")
        for tipo in EMITE:
            try:
                log.append({"type": tipo, "space_id": "space-vara", "kind": "belt"})
                ok(True, f"E2 `{tipo}` sobrevive a EventLog.append")
            except Exception as e:                                  # noqa: BLE001
                ok(False, f"E2 `{tipo}` sobrevive a EventLog.append", str(e)[:140])


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    print("=" * 82)
    print("verify_cinturon_vivo — ¿el turno dice algo mientras arranca el cinturón?")
    print("=" * 82)
    caso_AB()
    caso_C()
    caso_E()
    print("\n" + "-" * 82)
    print(f"{_OK} verdes · {len(_FALLOS)} rojas")
    for f in _FALLOS:
        print(f"   ❌ {f}")
    sys.exit(1 if _FALLOS else 0)
