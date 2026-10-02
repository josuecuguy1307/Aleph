#!/usr/bin/env python3
"""verify_cli_streaming.py — LA VARA DE F2a (Gate 2 · streaming real en cli_brain).

Lo que esta vara exige que quede verde:

    el CLI REAL, un prompt trivial, LADO A LADO viejo-vs-nuevo: mismo texto final, mismo
    model_final — y ≥2 eventos parciales ANTES del `result`, que es la prueba de que el
    stream es real y no fabricado · el watchdog corta un stub que enmudece, y lo distingue
    del techo total · una línea de 2 MB sube el contador de overflow y NO se acumula ·
    stderr pasa por el mismo parser con fallback a texto · `sanitized_env` y
    `FORBIDDEN_FLAGS` intactos · los errores traen la CausaModelo del traductor F1 ·
    `verify_traductor` sigue 158/158.

Los stubs de stream son procesos Python de verdad (no mocks del transporte): uno enmudece,
otro escupe una línea gigante, otro mezcla JSON en stdout con ruido en stderr.

DOS llamadas al CLI real, con `--model haiku` y un prompt de una palabra: es lo mínimo
para probar «mismo resultado» sin gastar la ventana. Se saltean con `SIN_CLI=1`.

    product/backend/.venv/bin/python platform/assembler/cli_brain/verify_cli_streaming.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_ASM = _AQUI.parent
_RAIZ = _ASM.parents[1]
for _p in (str(_ASM), str(_RAIZ / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

sys.path.insert(0, str(_RAIZ / "qa" / "lib"))

from cli_brain import base as B                       # noqa: E402
from cli_brain.claude_cli import ClaudeCliProvider    # noqa: E402
from cli_brain.codex_cli import CodexCliProvider      # noqa: E402
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


def stub(cuerpo: str) -> list[str]:
    """Un proceso Python de verdad que se comporta como un CLI."""
    return [sys.executable, "-c", textwrap.dedent(cuerpo)]


print("=" * 80)
print("VARA F2a · STREAMING REAL EN cli_brain")
print("=" * 80)

# ══ 1 · EL BUFFER DE LÍNEA ═════════════════════════════════════════════════════════
seccion("1 · buffer de línea parcial + flush en end + techo")
b = B._BufferDeLineas(max_bytes=1024)
ok(b.alimentar(b'{"a":1}\n{"b"') == ['{"a":1}'],
   "una línea cortada a la mitad NO se entrega: queda en el buffer")
ok(b.alimentar(b':2}\n') == ['{"b":2}'],
   "y se completa con el chunk siguiente (patrón CLITrigger)")
b2 = B._BufferDeLineas()
b2.alimentar(b"sin salto final")
ok(b2.flush() == ["sin salto final"], "flush en end: lo que quedó sin '\\n' se entrega igual")
ok(b2.flush() == [], "y el flush es idempotente")
b3 = B._BufferDeLineas()
ok(b3.alimentar("hola ñandú 🙂\n".encode()) == ["hola ñandú 🙂"],
   "multibyte cortado entre chunks no rompe el decode (buffer de BYTES)")
b4 = B._BufferDeLineas()
mitad = "ñ".encode()          # 2 bytes
ok(b4.alimentar(mitad[:1]) == [] and b4.alimentar(mitad[1:] + b"\n") == ["ñ"],
   "un carácter partido EXACTAMENTE por la mitad entre dos chunks se reensambla")

# ══ 2 · OVERFLOW: UNA LÍNEA DE 2 MB ════════════════════════════════════════════════
seccion("2 · techo de línea — 2 MB no se comen la memoria")
bo = B._BufferDeLineas(max_bytes=1024 * 1024)          # techo de 1 MB
gigante = b"X" * (2 * 1024 * 1024)                     # línea de 2 MB, sin '\n'
salida = bo.alimentar(gigante)
ok(salida == [], "la línea de 2 MB NO se entrega")
ok(bo.overflow == 1, "el contador de overflow subió a 1", str(bo.overflow))
ok(len(bo._buf) == 0, "y el buffer quedó VACÍO (no se acumula)", f"{len(bo._buf)} bytes")
resto = bo.alimentar(b"basura del final\n" + b'{"ok":1}\n')
ok(resto == ['{"ok":1}'],
   "el resto de la línea descartada se tira y se retoma en la SIGUIENTE", str(resto))
ok(bo.bytes_descartados >= 2 * 1024 * 1024,
   "los bytes descartados quedan contados, no perdidos en silencio", str(bo.bytes_descartados))

# y de punta a punta, con un proceso real que emite la línea gigante
r, st = B._run_streaming(
    stub("""
        import sys
        sys.stdout.write("X" * (2*1024*1024))     # 2 MB sin salto
        sys.stdout.write("\\n")
        sys.stdout.write('{"type":"result","is_error":false,"num_turns":1,"usage":{}}\\n')
        sys.stdout.flush()
    """),
    timeout=30, chunk_timeout=10, max_line_bytes=1024 * 1024)
ok(st.overflow >= 1, "de punta a punta: el overflow se cuenta en las stats", str(st.como_dict()))
ok('"type":"result"' in (r.stdout or ""),
   "y la línea BUENA que viene después sí llega", (r.stdout or "")[:60])
ok(len(r.stdout or "") < 3 * 1024 * 1024,
   "el stdout reensamblado no arrastra los 2 MB descartados", str(len(r.stdout or "")))

# ══ 3 · SILENCIO COMO SEÑAL + DEADLINE ════════════════════════════════════════════
seccion("3 · silencio registrado — sólo el deadline mata")
t0 = time.monotonic()
try:
    _, st_mudo = B._run_streaming(
        stub("""
            import sys, time
            print('{"type":"system","subtype":"init"}', flush=True)
            time.sleep(3)                       # piensa sin emitir
            print('{"type":"result","is_error":false,"num_turns":1,"usage":{}}', flush=True)
        """),
        timeout=10, chunk_timeout=1.0)
    dt = time.monotonic() - t0
    ok(dt >= 3, "un proceso vivo sobrevive más de un intervalo de silencio", f"{dt:.1f}s")
    ok(st_mudo.silencios >= 2, "cada intervalo mudo queda contado", str(st_mudo.como_dict()))
except Exception as e:                                  # noqa: BLE001
    ok(False, "un proceso vivo y silencioso continúa hasta producir salida",
       f"{type(e).__name__}: {e}")

t0 = time.monotonic()
try:
    B._run_streaming(
        stub("""
            import sys, time
            for i in range(20):
                print('{"type":"stream_event","i":%d}' % i, flush=True)
                time.sleep(0.3)                 # LENTO pero vivo
            print('{"type":"result","is_error":false,"num_turns":1,"usage":{}}', flush=True)
        """),
        timeout=60, chunk_timeout=2.0)
    ok(True, "un stream LENTO pero vivo NO se corta (cada chunk resetea el reloj)")
except Exception as e:                                  # noqa: BLE001
    ok(False, "un stream LENTO pero vivo NO se corta", f"{type(e).__name__}: {e}")

t0 = time.monotonic()
try:
    B._run_streaming(
        stub("""
            import sys, time
            while True:
                print('{"t":1}', flush=True)
                time.sleep(0.2)                 # vivo para siempre
        """),
        timeout=3.0, chunk_timeout=30.0)
    ok(False, "el techo TOTAL sigue existiendo aunque el stream esté vivo")
except subprocess.TimeoutExpired:
    ok(time.monotonic() - t0 < 10, "el techo TOTAL sigue existiendo aunque el stream esté vivo")
except Exception as e:                                  # noqa: BLE001
    ok(False, "el techo TOTAL corta con TimeoutExpired", f"{type(e).__name__}: {e}")

# el proceso no queda vivo tras el corte
ok(len(B._ACTIVE_PROCESSES) == 0,
   "ningún proceso queda registrado (ni vivo) después de los cortes",
   str(list(B._ACTIVE_PROCESSES)))

# ══ 4 · stderr POR EL MISMO PARSER ═════════════════════════════════════════════════
seccion("4 · stderr por el mismo parser, con fallback a texto")
vistos = []
r, st = B._run_streaming(
    stub("""
        import sys
        sys.stderr.write("ruido de terminal que no es JSON\\n"); sys.stderr.flush()
        sys.stdout.write('{"type":"stream_event","event":{"type":"content_block_delta",'
                         '"delta":{"type":"text_delta","text":"hola"}}}\\n'); sys.stdout.flush()
        sys.stderr.write('{"type":"system","subtype":"warn"}\\n'); sys.stderr.flush()
        sys.stdout.write('{"type":"result","is_error":false,"num_turns":1,"usage":{}}\\n')
        sys.stdout.flush()
    """),
    timeout=20, chunk_timeout=10, on_linea=lambda c, l: vistos.append((c, l[:40])))
canales = {c for c, _ in vistos}
ok(canales == {"stdout", "stderr"}, "las líneas de LOS DOS canales llegan al parser", str(canales))
ok(any(c == "stderr" and "ruido" in l for c, l in vistos),
   "el ruido de stderr NO se descarta: llega como línea")
ok(any(c == "stderr" and l.startswith("{") for c, l in vistos),
   "y un JSON en stderr también llega (mismo parser, no dos)")
ok("ruido de terminal" in (r.stderr or ""),
   "el stderr crudo se reensambla igual que con communicate", (r.stderr or "")[:50])

# ══ 5 · EL ARGV: contrato medido, y lo prohibido sigue prohibido ═══════════════════
seccion("5 · argv — contrato medido del binario + FORBIDDEN_FLAGS")
p = ClaudeCliProvider()
viejo = p.build_argv("/bin/claude", "hola", "opus", "/tmp")
nuevo = p.build_argv("/bin/claude", "hola", "opus", "/tmp", stream=True)
ok(viejo[viejo.index("--output-format") + 1] == "json",
   "sin `stream` el argv queda BYTE-IDÉNTICO al de antes (--output-format json)")
ok(nuevo[nuevo.index("--output-format") + 1] == "stream-json",
   "con `stream` pide stream-json")
ok("--verbose" in nuevo,
   "y lleva --verbose, que el binario EXIGE con stream-json (medido, reporte 3 §0.3)")
ok("--include-partial-messages" in nuevo,
   "y --include-partial-messages, que es lo que lo vuelve token-a-token")
ok([a for a in viejo if a not in ("--output-format", "json")] ==
   [a for a in nuevo if a not in ("--output-format", "stream-json", "--verbose",
                                  "--include-partial-messages")],
   "fuera del bloque de formato, los dos argv son el MISMO")
for arg in B.FORBIDDEN_FLAGS:
    ok(arg not in nuevo, f"el argv de streaming NO lleva `{arg}`")
try:
    B.assert_argv_safe(nuevo + ["--dangerously-skip-permissions"])
    ok(False, "assert_argv_safe sigue reventando ante un flag de bypass")
except RuntimeError:
    ok(True, "assert_argv_safe sigue reventando ante un flag de bypass")
ok("--tools" in nuevo and nuevo[nuevo.index("--tools") + 1] == "",
   "las tools siguen apagadas en el camino de streaming")
ok("--strict-mcp-config" in nuevo and "--setting-sources" in nuevo,
   "y siguen fuera los MCP y los hooks del usuario")

seccion("5b · sanitized_env intacto")
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-NO-DEBE-VIAJAR"
os.environ["GROQ_API_KEY"] = "gsk-NO-DEBE-VIAJAR"
os.environ["PUPPET_CLAUDE_CLI_MODEL"] = "haiku"
env = B.sanitized_env("/opt/homebrew/bin/claude")
ok("ANTHROPIC_API_KEY" not in env, "ANTHROPIC_API_KEY NO viaja al CLI (atribución a la suscripción)")
ok("GROQ_API_KEY" not in env, "ningún secreto de infra viaja al CLI")
ok("PATH" in env and "HOME" in env, "lo mínimo para que el CLI encuentre su auth sí viaja")
ok(env.get("PUPPET_CLAUDE_CLI_MODEL") == "haiku", "los overrides propios del BYO-CLI siguen pasando")
ok(env["PATH"].split(os.pathsep)[0] == "/opt/homebrew/bin",
   "y el dir del binario se antepone al PATH (launcher con shebang)")
del os.environ["ANTHROPIC_API_KEY"], os.environ["GROQ_API_KEY"]

# ══ 6 · CODEX SIN TOCAR ════════════════════════════════════════════════════════════
seccion("6 · codex queda byte-idéntico (no se adivinó su formato)")
c = CodexCliProvider()
ok(c.usa_stream_json() is False, "codex NO declara stream-json en esta fase")
ok(c.build_argv("/bin/codex", "hola", "gpt-5", "/tmp") ==
   c.build_argv("/bin/codex", "hola", "gpt-5", "/tmp", stream=True),
   "su argv es EL MISMO con y sin `stream` (el flag se acepta y se ignora)")
ok(c.parse_stream_line({"msg": {"type": "agent_message_delta"}}) == (None, None),
   "y su parse_stream_line no inventa: devuelve (None, None)")

# ══ 7 · LA CAUSA TIPADA (traductor F1) VIAJA EN EL ERROR ═══════════════════════════
seccion("7 · el traductor F1 entra: CausaModelo en los fallos")
ok(B._traductor is not None, "el traductor está disponible desde cli_brain")
import errores_modelo as E                              # noqa: E402

cz = B._causa_tipada("getaddrinfo ENOTFOUND api.anthropic.com", 1)
ok(cz and cz["causa"] == E.SIN_RED,
   "un DNS caído del CLI da `sin_red` (antes: model_error)", str(cz and cz["causa"]))
cz = B._causa_tipada("", 1, {"is_error": True, "api_error_status": 429,
                             "terminal_reason": "api_error"})
ok(cz and cz["causa"] == E.RATE_LIMIT and cz["reintentable"] is True,
   "el result_event con 429 da `rate_limit` reintentable", str(cz))
cz = B._causa_tipada("", 1, {"is_error": True, "terminal_reason": "timeout"})
ok(cz and cz["causa"] == E.TIMEOUT, "terminal_reason=timeout da `timeout`", str(cz))
cz = B._causa_tipada("algo rarísimo", 9)
ok(cz and cz["causa"] == E.FALLO_DESCONOCIDO,
   "lo no clasificable da `fallo_desconocido`, jamás una causa que mienta", str(cz))
cz = B._causa_tipada("authentication_error: sk-ant-api03-SECRETO12345678901234567890", 1)
ok(cz and "sk-ant-api03-SECRETO12345678901234567890" not in json.dumps(cz),
   "y ninguna key sobrevive en la causa (redacción del traductor)", json.dumps(cz)[:100])
cw = B._causa_del_wrapper("el CLI ejecutó acciones por su cuenta")
ok(cw and cw["causa"] == E.FALLA_DE_ALEPH and cw["reintentable"] is False,
   "el guard del wrapper puro se reporta como `falla_de_aleph`, no como culpa del usuario",
   str(cw))

# no instalado → causa tipada, sin spawnear nada
class _SinBinario(ClaudeCliProvider):
    def binary(self):
        return None


r_sb = _SinBinario().invoke("hola")
ok(r_sb.ok is False and r_sb.error_kind == B.ERR_NOT_INSTALLED,
   "un CLI ausente sigue dando ERR_NOT_INSTALLED (contrato viejo intacto)")
ok(r_sb.causa and r_sb.causa["causa"] == E.CLI_NO_INSTALADO,
   "y ahora ADEMÁS trae la causa tipada `cli_no_instalado`", str(r_sb.causa))

# ══ 8 · EL CLI REAL, LADO A LADO ═══════════════════════════════════════════════════
seccion("8 · CLI REAL — viejo vs nuevo, mismo resultado, stream verificable")
PROMPT = "Responde exactamente con la palabra: OK"
MODELO = os.environ.get("VARA_CLI_MODELO", "haiku")

if os.environ.get("SIN_CLI"):
    saltear("las dos llamadas al CLI real", "SIN_CLI=1")
else:
    prov = ClaudeCliProvider()
    binario = prov.binary()
    if not binario:
        saltear("las dos llamadas al CLI real", "`claude` no está instalado")
    else:
        estado = prov.detect()
        if estado.state != B.STATE_READY:
            saltear("las dos llamadas al CLI real", f"detect() = {estado.state} ({estado.detail})")
        else:
            # ── ARM VIEJO: exactamente la secuencia de antes de F2a ──────────────
            wd = tempfile.mkdtemp(prefix="vara-viejo-")
            t0 = time.monotonic()
            try:
                argv_v = B.assert_argv_safe(prov.build_argv(binario, PROMPT, MODELO, wd))
                rv = B._run_managed(argv_v, cwd=wd, env=B.sanitized_env(binario), timeout=120)
                res_viejo = prov.parse_result(rv.returncode, rv.stdout or "", rv.stderr or "", wd, MODELO)
            finally:
                shutil.rmtree(wd, ignore_errors=True)
            dt_viejo = time.monotonic() - t0
            ok(res_viejo.ok, "ARM VIEJO (communicate + --output-format json) responde",
               f"{res_viejo.error_kind}: {res_viejo.error_detail[:90]}")

            # ── ARM NUEVO: invoke() con lectura incremental ──────────────────────
            orden = []          # la SECUENCIA de clases, que es la prueba del stream
            t_primero = {"v": None}
            t1 = time.monotonic()

            def _ev(clase, carga):
                if clase in ("texto", "pensando") and t_primero["v"] is None:
                    t_primero["v"] = time.monotonic() - t1
                orden.append(clase)

            res_nuevo = prov.invoke(PROMPT, model=MODELO, on_evento=_ev)
            dt_nuevo = time.monotonic() - t1
            ok(res_nuevo.ok, "ARM NUEVO (stream-json incremental) responde",
               f"{res_nuevo.error_kind}: {res_nuevo.error_detail[:90]}")

            if res_viejo.ok and res_nuevo.ok:
                v_txt = (res_viejo.text or "").strip()
                n_txt = (res_nuevo.text or "").strip()
                ok(v_txt == n_txt, "MISMO texto final en los dos caminos",
                   f"viejo={v_txt[:40]!r} nuevo={n_txt[:40]!r}")
                ok(res_viejo.model_final == res_nuevo.model_final,
                   f"MISMO model_final: {res_nuevo.model_final}",
                   f"viejo={res_viejo.model_final} nuevo={res_nuevo.model_final}")
                ok(res_nuevo.model_final_source == res_viejo.model_final_source == "cli-reported",
                   "y en los dos sale de modelUsage (cli-reported), no del wrapper",
                   f"{res_viejo.model_final_source} / {res_nuevo.model_final_source}")
                ok(res_viejo.exec_events == res_nuevo.exec_events == 0,
                   "ninguno ejecutó nada por su cuenta (wrapper puro)")

            # LA PRUEBA DE QUE EL STREAM ES REAL
            parciales = [c for c in orden if c in ("texto", "pensando")]
            idx_result = orden.index("resultado") if "resultado" in orden else -1
            antes = [c for c in orden[:idx_result] if c in ("texto", "pensando")] if idx_result >= 0 else []
            ok(len(parciales) >= 2,
               f"llegaron {len(parciales)} eventos parciales (≥2)", str(orden[:12]))
            ok(idx_result >= 0, "el evento `result` llegó y se reconoció")
            ok(len(antes) >= 2,
               f"y {len(antes)} de ellos llegaron ANTES del result — el stream NO es fabricado",
               f"orden={orden[:14]}")
            ok(t_primero["v"] is not None and t_primero["v"] < dt_nuevo,
               f"el primer delta llegó a los {t_primero['v'] and round(t_primero['v'], 1)}s "
               f"de un turno de {dt_nuevo:.1f}s (antes: todo al final)",
               f"primero={t_primero['v']} total={dt_nuevo}")
            st = (res_nuevo.meta or {}).get("stream") or {}
            ok(st.get("stream_json") is True and st.get("lineas", 0) > 5,
               f"las stats del stream viajan en meta: {st}", str(st))
            ok(st.get("overflow", 0) == 0, "y no hubo overflow en un turno normal", str(st))
            print(f"      · viejo {dt_viejo:.1f}s   ·   nuevo {dt_nuevo:.1f}s   "
                  f"·   primer delta {t_primero['v'] and round(t_primero['v'], 1)}s")

# ══ 8b · EL SERVER REENVÍA, NO FABRICA ═════════════════════════════════════════════
seccion("8b · server :SSE — los eventos salen SEGÚN LLEGAN, no al final")
import http.client                                       # noqa: E402
import threading                                         # noqa: E402

from cli_brain import detect as _detect                  # noqa: E402
from cli_brain.server import create_server               # noqa: E402


class _ProviderLento(ClaudeCliProvider):
    """Un provider de laboratorio: emite 5 deltas espaciados y después el resultado.
    No spawnea nada — lo que se prueba acá es el REENVÍO del server, no el CLI."""
    provider_id = "lab_lento"
    display_name = "Lab Lento"
    response_model_id = "lab-lento"

    def __init__(self, falla=None):
        self._falla = falla

    def binary(self):
        return "/bin/true"

    def invoke(self, prompt, model=None, timeout=None, effort=None,
               on_evento=None, chunk_timeout=None):
        if self._falla == "antes":
            return B.BrainResult(ok=False, error_kind=B.ERR_RATE_LIMIT,
                                 error_detail="ventana agotada", reset_hint="02:59",
                                 causa=B._causa_tipada("usage limit reached", 1))
        for i in range(5):
            if on_evento:
                on_evento("sistema", {"type": "system", "model": "lab-modelo-real"}) if i == 0 else None
                on_evento("texto", f"t{i} ")
            time.sleep(0.25)
        if self._falla == "mitad":
            return B.BrainResult(ok=False, error_kind=B.ERR_MODEL,
                                 error_detail="se cayó a mitad",
                                 causa=B._causa_tipada("", 1,
                                                       {"is_error": True, "api_error_status": 500}))
        return B.BrainResult(ok=True, text="t0 t1 t2 t3 t4 ", model_final="lab-modelo-real",
                             model_final_source="cli-reported",
                             usage={"prompt_tokens": 1, "completion_tokens": 5},
                             meta={"stream": {"lineas": 12, "eventos_parciales": 5}})


def _pedir_sse(puerto, modelo, cuerpo_extra=None):
    """Devuelve (status, headers, [(t_relativo, linea)]) leyendo el SSE a medida que llega."""
    conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=30)
    payload = {"model": modelo, "messages": [{"role": "user", "content": "hola"}], "stream": True}
    payload.update(cuerpo_extra or {})
    conn.request("POST", "/v1/chat/completions", json.dumps(payload),
                 {"Content-Type": "application/json", "Host": f"127.0.0.1:{puerto}"})
    r = conn.getresponse()
    t0 = time.monotonic()
    marcas = []
    if r.status == 200:
        while True:
            linea = r.fp.readline()
            if not linea:
                break
            s = linea.decode("utf-8", "replace").strip()
            if s.startswith("data:"):
                marcas.append((time.monotonic() - t0, s[5:].strip()))
                if s.strip().endswith("[DONE]"):
                    break
        cuerpo = None
    else:
        cuerpo = json.loads(r.read().decode())
    conn.close()
    return r.status, dict(r.getheaders()), marcas, cuerpo


srv = create_server(0)
puerto = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
_guardado = dict(_detect._BY_MODEL_ID)
try:
    _detect._BY_MODEL_ID["lab-lento"] = _ProviderLento()
    _detect._BY_MODEL_ID["lab-falla-antes"] = _ProviderLento(falla="antes")
    _detect._BY_MODEL_ID["lab-falla-mitad"] = _ProviderLento(falla="mitad")

    st, hdrs, marcas, _ = _pedir_sse(puerto, "lab-lento")
    ok(st == 200, "el stream responde 200", str(st))
    ok("Content-Length" not in hdrs,
       "SIN Content-Length: es un stream de verdad, no un cuerpo precalculado",
       str(hdrs.get("Content-Length")))
    ok(hdrs.get("X-Accel-Buffering") == "no", "y pide que ningún proxy lo vuelva a bufferear")
    datos = [m for m in marcas if m[1] != "[DONE]"]
    ok(len(datos) >= 6, f"llegaron {len(datos)} frames (rol + 5 deltas + cierre)", str(len(datos)))
    ok(marcas[-1][1] == "[DONE]", "y cierra con [DONE]")
    ok(marcas[-1][0] - marcas[0][0] > 0.6,
       f"los frames se ESPACIARON en el tiempo ({marcas[-1][0]-marcas[0][0]:.2f}s entre "
       f"el primero y el último) — no salieron todos juntos al final",
       f"{[round(t,2) for t,_ in marcas]}")
    contenidos = []
    finales = []
    for _, d in datos:
        o = json.loads(d)
        dl = (o.get("choices") or [{}])[0].get("delta") or {}
        if dl.get("content"):
            contenidos.append(dl["content"])
        if (o.get("choices") or [{}])[0].get("finish_reason"):
            finales.append(o)
    ok("".join(contenidos) == "t0 t1 t2 t3 t4 ",
       "el texto reensamblado desde los deltas es el mismo que el final", "".join(contenidos))
    ok(len(finales) == 1 and finales[0]["choices"][0]["finish_reason"] == "stop",
       "hay exactamente UN chunk de cierre con finish_reason")
    ok(finales and finales[0].get("model") == "lab-modelo-real",
       "y el chunk final lleva el model_final AUTORITATIVO", str(finales and finales[0].get("model")))
    annex = finales[0].get("aleph_cli_brain") if finales else {}
    ok(annex.get("model_final_source") == "cli-reported",
       "el annex de siempre sigue viajando en el cierre", str(annex)[:90])
    ok(all(json.loads(d).get("object") == "chat.completion.chunk" for _, d in datos),
       "TODOS los frames son `chat.completion.chunk` — el formato no cambió")

    # ── COMPATIBILIDAD: un provider con la firma VIEJA no puede romper el server ──
    # Esto lo cazó `product/backend/tests/test_slice_d_run_controls.py` durante F2a: su
    # FakeProvider implementa `invoke(prompt, model, effort)` SIN `on_evento`, y pasarle
    # el kwarg nuevo mataba el handler antes de escribir una sola línea de respuesta.
    class _ProviderFirmaVieja:
        provider_id, display_name, response_model_id = "lab_viejo", "Lab Viejo", "lab-viejo"

        def invoke(self, prompt, model=None, effort=None):        # SIN on_evento, a propósito
            return B.BrainResult(ok=True, text="soy del contrato viejo",
                                 model_final="lab-viejo-real", model_final_source="cli-reported",
                                 usage={"prompt_tokens": 1, "completion_tokens": 1})

    _detect._BY_MODEL_ID["lab-viejo"] = _ProviderFirmaVieja()
    st, hdrs, marcas, _ = _pedir_sse(puerto, "lab-viejo")
    ok(st == 200, "un provider con la firma VIEJA de invoke sigue respondiendo 200", str(st))
    cuerpos = [json.loads(d) for _, d in marcas if d != "[DONE]"]
    ok(len(cuerpos) == 1 and (cuerpos[0]["choices"][0]["delta"].get("content")
                              == "soy del contrato viejo"),
       "emite su turno entero en un chunk, como hasta ayer (sin adelantar nada)",
       str(cuerpos)[:110])
    ok(marcas[-1][1] == "[DONE]", "y cierra con [DONE] igual")
    from cli_brain.server import _acepta_on_evento                # noqa: E402
    ok(_acepta_on_evento(_ProviderFirmaVieja().invoke) is False,
       "la detección por FIRMA dice que no lo acepta (no se descubre por TypeError)")
    ok(_acepta_on_evento(ClaudeCliProvider().invoke) is True,
       "y dice que el provider nuevo sí")

    st, hdrs, marcas, cuerpo = _pedir_sse(puerto, "lab-falla-antes")
    ok(st == 429, "un fallo ANTES del primer delta sigue siendo un HTTP con status (429)", str(st))
    ok(cuerpo["error"]["error_kind"] == B.ERR_RATE_LIMIT and cuerpo["error"]["reset_hint"] == "02:59",
       "con las MISMAS claves de error de siempre", str(cuerpo["error"])[:110])
    ok(cuerpo["error"].get("causa", {}).get("causa") == E.RATE_LIMIT,
       "y ADEMÁS la CausaModelo tipada del traductor F1",
       str(cuerpo["error"].get("causa"))[:110])

    st, hdrs, marcas, _ = _pedir_sse(puerto, "lab-falla-mitad")
    ok(st == 200, "un fallo A MITAD (imposible antes de F2a) ya no puede cambiar el status")
    cierre = [json.loads(d) for _, d in marcas if d != "[DONE]"]
    err = [c for c in cierre if (c.get("choices") or [{}])[0].get("finish_reason") == "error"]
    ok(len(err) == 1, "se reporta por el canal con finish_reason='error'", str(len(err)))
    ok(err and err[0]["aleph_cli_brain"]["causa"]["causa"] == E.PROVEEDOR_CAIDO,
       "llevando la causa tipada (500 → proveedor_caido)",
       str(err and err[0]["aleph_cli_brain"].get("causa"))[:110])
    ok(marcas[-1][1] == "[DONE]", "y cierra limpio igual")
finally:
    _detect._BY_MODEL_ID.clear()
    _detect._BY_MODEL_ID.update(_guardado)
    srv.shutdown()
    srv.server_close()

# ══ 9 · verify_traductor SIGUE VERDE ═══════════════════════════════════════════════
# El número es EXACTO a propósito: así una fase que borre aserciones del traductor para
# «pasar» se cae acá. Historia: 120 → 128 en F2d (obra 0), las 8 filas de la precedencia
# clase-vs-status en `TABLA_LITELLM`; 128 → 149 en F1b, las filas finas de ollama (la
# tabla medida en la auditoría 4 §3.2) más sus aserciones de evidencia; 149 → 158 en F5,
# la distinción apagado-vs-ocupado (`runtime_vivo`); 158 → 159 en F1c, la fila que
# amarra que `RejectedRequestError` NO se movió a `politica_de_contenido` (las otras
# cinco filas de F1c cambiaron de veredicto, no de cantidad); 159 → 161 en F7·A, las dos
# filas de `TABLA_URLLIB` que separan `falta_key` de `key_invalida` en un 401; 161 → 163
# en F7·A·bis, las MISMAS dos filas del lado litellm — que faltaban, y por faltar las dos
# vías daban veredictos distintos ante el mismo 401 (lo cazó `verify_f4a` §4c, no ésta);
# 163 → 166 en F9, las TRES filas de la ley del 403 (`error code: 1010` → falla_de_aleph ·
# `1015` → rate_limit · el 403 que no es de infra sigue en plan_insuficiente).
# Subirlo es parte del trabajo de la fase que agrega filas; bajarlo, jamás.
#
# ⚠️ Y ESTE GUARD SE OLVIDA FÁCIL: F7·A agregó sus dos filas, corrió `verify_traductor`
# —verde— y no corrió ESTA, que es la que cuenta. El barrido de regresión fue lo que lo
# encontró. Si agregás filas al traductor, este número es parte de tu obra.
# ⚠️ [F9] ESTO ERA UNA IGUALDAD (`verdes == N`) Y MORDIÓ DOS VECES EN DOS TANDAS, en esta
# misma línea: F7·A agregó dos filas al traductor y no actualizó el número; F9 agregó tres
# (la ley del 403) y tampoco. Las dos veces el barrido de regresión lo encontró, y las dos
# veces la «regresión» era una MEJORA — más filas verdes.
#
# **Un guard que hay que acordarse de actualizar a mano no es un guard: es una trampa con
# documentación.** El invariante real nunca fue «son exactamente N»: era «NINGUNA FILA
# DESAPARECIÓ». Eso se expresa con PISOS, y un piso no se rompe al agregar.
#
#   · `verdes >= _PISO_VERDES`         — agregar filas nunca lo rompe; borrarlas sí.
#   · las causas NOMBRADAS son un piso — si una causa deja de tener fila que la ejercite,
#     se nota por NOMBRE, que es el dato accionable («perdió su fila `rate_limit`»), no un
#     número que hay que ir a comparar contra el commit anterior.
#
# Los dos pisos se MIDIERON (2026-08-07), no se escribieron de memoria. Subirlos cuando una
# fase agrega cobertura es opcional; bajarlos, jamás.
_PISO_VERDES = 166
_PISO_CAUSAS = frozenset(['cli_no_instalado', 'cli_sin_permisos', 'contexto_excedido', 'error_upstream', 'falla_de_aleph', 'fallo_desconocido', 'falta_key', 'key_invalida', 'modelo_no_disponible', 'plan_insuficiente', 'politica_de_contenido', 'proveedor_caido', 'rate_limit', 'runtime_ocupado', 'sin_credito', 'sin_red', 'sin_runtime', 'sin_sesion', 'timeout'])

seccion("9 · el traductor de F1 no perdió filas (pisos, no igualdad)")
rt = subprocess.run([sys.executable, str(_ASM / "verify_traductor.py")],
                    capture_output=True, text=True, timeout=180)
verdes = rt.stdout.count("✓")
ok(rt.returncode == 0, "verify_traductor.py sale con exit 0", f"exit={rt.returncode}")
ok(verdes >= _PISO_VERDES,
   f"y no perdió aserciones: {verdes} >= {_PISO_VERDES} (agregar no rompe; borrar sí)",
   rt.stdout.strip().splitlines()[-1] if rt.stdout else "")
_sin_fila = sorted(c for c in _PISO_CAUSAS if c not in rt.stdout)
ok(not _sin_fila,
   f"★ y ninguna causa perdió su fila que la ejercite ({len(_PISO_CAUSAS)} cubiertas)",
   f"se quedaron sin fila: {_sin_fila}")

# [H4a] El cierre pasa por `qa/lib/veredicto.py`: con salteos declarados la última
# línea ya NO es el string pelado `TODO VERDE`. La regla vive en un solo lugar.
sys.path.insert(0, str(_RAIZ / "qa" / "lib"))
import veredicto as _V  # noqa: E402

print(f"\n{_V.texto(_fallos, _salteados)}")
sys.exit(0 if _fallos == 0 else 1)
