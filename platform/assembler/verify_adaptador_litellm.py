#!/usr/bin/env python3
"""verify_adaptador_litellm.py — LA VARA DE F3 (Gate 2 · la frontera con LiteLLM).

Lo que esta vara exige que quede verde:

    el IMPORT no toca la red (audit hook) ni lee el `.env` del CWD, ni siquiera simulando
    el bundle congelado · contra un stub local: 401→key_invalida · 429 con retry-after→
    rate_limit CON los segundos · DNS muerto→sin_red (NO proveedor_caido: es la fila P1.d)
    · 500 de verdad→proveedor_caido · streaming: los chunks llegan, cortar cierra de veras
    (el stub lo confirma con un BrokenPipe) y cancelar la Task deja todo limpio · usage:
    el provider que reporta sale medido y el que no, `tokens_medidos=False` — jamás ceros
    presentados como medición · `model_final` es el del PROVEEDOR, no el del request ·
    y las varas de F1/F2a/F2b/F2c siguen verdes.

Cero red externa: todo corre contra un stub HTTP en 127.0.0.1 y contra un host inexistente.

    product/backend/.venv/bin/python platform/assembler/verify_adaptador_litellm.py
"""
from __future__ import annotations

import asyncio
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (str(_AQUI), str(_RAIZ / "platform"), str(_RAIZ / "qa" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import veredicto as _V                                   # noqa: E402

_fallos = 0
_salteados = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))


#: [H4a] los salteos que se comen el OBJETO de la vara. Acá el objeto ES litellm: sin él
#: esta vara no midió nada, y decir «TODO VERDE» era mentir. Ver `qa/lib/veredicto.py`.
_criticos = 0


def saltear(nombre, motivo, *, critico=False):
    global _salteados, _criticos
    _salteados += 1
    if critico:
        _criticos += 1
    print(f"  ⊘ {nombre}  →  SALTEADO{' (SU OBJETO)' if critico else ''}: {motivo}")


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


print("=" * 80)
print("VARA F3 · EL ADAPTADOR DE LiteLLM")
print("=" * 80)

# ══ 0 · EL SELLADO, ANTES DE QUE NADIE IMPORTE litellm ═════════════════════════════
# Esta sección corre en SUBPROCESOS a propósito: el sellado ocurre en el import, así que
# probarlo en este proceso —donde el import ya pasó— no probaría nada.
seccion("0 · el import no toca la red · no lee el .env")

_SONDA_RED = r"""
import json, os, sys, tempfile
EV = []
def hook(ev, args):
    if ev in ("socket.getaddrinfo", "socket.connect"):
        EV.append((ev, repr(args)[:90]))
sys.addaudithook(hook)
sys.path.insert(0, %(asm)r)
import adaptador_litellm as A
antes = len(EV)
A.init_litellm()
import litellm
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map_source_info
print(json.dumps({
    "eventos_red": EV,
    "fuente_cost_map": get_model_cost_map_source_info(),
    "request_timeout": litellm.request_timeout,
    "suppress_debug_info": litellm.suppress_debug_info,
    "disable_hf": litellm.disable_hf_tokenizer_download,
    "fallbacks": litellm.fallbacks,
    "num_retries": litellm.num_retries,
    "telemetry": litellm.telemetry,
}))
""" % {"asm": str(_AQUI)}

_SONDA_ENV = r"""
import json, os, sys
sys.frozen = True            # lo que PyInstaller pone en el bundle
sys._MEIPASS = os.getcwd()
sys.path.insert(0, %(asm)r)
import adaptador_litellm as A
A.init_litellm()
print(json.dumps({"marcador": os.environ.get("MARCADOR_F3"),
                  "key": os.environ.get("OPENAI_API_KEY"),
                  "modo": os.environ.get("LITELLM_MODE")}))
""" % {"asm": str(_AQUI)}


def _sub(codigo, *, cwd=None, env_extra=None):
    env = dict(os.environ)
    for k in ("LITELLM_LOCAL_MODEL_COST_MAP", "LITELLM_MODE"):
        env.pop(k, None)            # el sellado tiene que ponerlas ÉL, no heredarlas
    env.update(env_extra or {})
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True,
                       timeout=180, cwd=cwd, env=env)
    try:
        return json.loads((r.stdout or "").strip().splitlines()[-1]), r
    except Exception:                                   # noqa: BLE001
        return None, r


hay_litellm = True
d, r = _sub(_SONDA_RED)
if d is None:
    if "litellm no está instalado" in (r.stderr or "") or "No module named 'litellm'" in (r.stderr or ""):
        hay_litellm = False
        saltear("todo lo que necesita litellm instalado",
                "litellm no está en este intérprete — `pip install -r product/backend/requirements.txt`",
                critico=True)
    else:
        ok(False, "la sonda del import corrió", (r.stderr or "")[-300:])
else:
    ok(d["eventos_red"] == [],
       "un `import litellm` sellado NO abre NINGUNA conexión (audit hook)", str(d["eventos_red"]))
    ok(d["fuente_cost_map"]["source"] == "local" and d["fuente_cost_map"]["is_env_forced"] is True,
       "el cost map sale del backup LOCAL, forzado por env — no de raw.githubusercontent.com",
       str(d["fuente_cost_map"]))
    ok(d["request_timeout"] == 60.0,
       "request_timeout = 60 s, el mismo techo que `assembler._chat` (litellm trae 6000)",
       str(d["request_timeout"]))
    ok(d["suppress_debug_info"] is True, "suppress_debug_info=True: sin prints ANSI por error")
    ok(d["disable_hf"] is True, "disable_hf_tokenizer_download=True: sin descargas de HuggingFace")
    ok(d["fallbacks"] is None and d["num_retries"] is None,
       "fallbacks y num_retries APAGADOS (el cascade es de `_route_chat`, río arriba)",
       f"{d['fallbacks']} / {d['num_retries']}")
    ok(d["telemetry"] is False, "telemetry=False")

if hay_litellm:
    import tempfile
    _d = tempfile.mkdtemp(prefix="vara-f3-env-")
    with open(os.path.join(_d, ".env"), "w") as f:
        f.write("MARCADOR_F3=filtrado_desde_dotenv\nOPENAI_API_KEY=sk-desde-dotenv\n")
    d2, r2 = _sub(_SONDA_ENV, cwd=_d)
    if d2 is None:
        ok(False, "la sonda del .env corrió", (r2.stderr or "")[-300:])
    else:
        ok(d2["modo"] == "PRODUCTION", "LITELLM_MODE quedó en PRODUCTION", str(d2["modo"]))
        ok(d2["marcador"] is None and d2["key"] is None,
           "con sys.frozen=True (bundle) el `.env` del CWD NO se lee — el §P4.b queda cerrado",
           f"marcador={d2['marcador']} key={d2['key']}")

# ══ EL STUB ════════════════════════════════════════════════════════════════════════
MODO = {"v": "200"}
EVENTOS = []


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _json(self, code, obj, cabeceras=None):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        for k, v in (cabeceras or {}).items():
            self.send_header(k, v)
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        m = MODO["v"]
        if m == "401":
            return self._json(401, {"error": {"message": "Invalid API Key",
                                              "type": "invalid_request_error"}},
                              {"x-request-id": "req_F3_401"})
        if m == "429":
            return self._json(429, {"error": {"message": "Rate limit reached",
                                              "type": "rate_limit_error"}},
                              {"retry-after": "37", "x-request-id": "req_F3_429"})
        if m == "500":
            return self._json(500, {"error": {"message": "upstream exploded",
                                              "type": "server_error"}})
        if m == "200":
            return self._json(200, {
                "id": "c1", "object": "chat.completion", "created": 1,
                "model": "modelo-REAL-DEL-PROVEEDOR",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "hola"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}})
        if m == "200_sin_usage":
            return self._json(200, {
                "id": "c1", "object": "chat.completion", "created": 1,
                "model": "modelo-REAL-DEL-PROVEEDOR",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "hola mundo"}}]})
        if m in ("stream", "stream_sin_usage", "stream_largo"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            n = 300 if m == "stream_largo" else 4
            enviados = 0
            try:
                for i in range(n):
                    ch = {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                          "model": "modelo-REAL-DEL-PROVEEDOR",
                          "choices": [{"index": 0, "delta": {"content": f"t{i} "},
                                       "finish_reason": None}]}
                    self.wfile.write(f"data: {json.dumps(ch)}\n\n".encode())
                    self.wfile.flush()
                    enviados += 1
                    if m == "stream_largo":
                        time.sleep(0.02)
                if m == "stream":
                    fin = {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                           "model": "modelo-REAL-DEL-PROVEEDOR", "choices": [],
                           "usage": {"prompt_tokens": 5, "completion_tokens": 4,
                                     "total_tokens": 9}}
                    self.wfile.write(f"data: {json.dumps(fin)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                if m == "stream_largo":
                    EVENTOS.append(f"servidor sirvió los {n} chunks (el cliente NUNCA cerró)")
            except (BrokenPipeError, ConnectionResetError, OSError):
                EVENTOS.append(f"servidor detectó el cierre del cliente tras {enviados} chunks")


class T(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


if hay_litellm:
    srv = T(("127.0.0.1", 0), H)
    PUERTO = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    BASE = f"http://127.0.0.1:{PUERTO}/v1"
    MUERTO = "http://no-existe-este-host-f3-abc.invalid/v1"

    import adaptador_litellm as A                        # noqa: E402
    import errores_modelo as E                           # noqa: E402
    A.init_litellm()
    MSG = [{"role": "user", "content": "hola"}]

    def corr(coro):
        return asyncio.run(coro)

    # ══ 1 · LA TAXONOMÍA ═══════════════════════════════════════════════════════════
    seccion("1 · errores — el traductor F1 en su primer uso real")
    # ⚠ EL 401 LLEGA CON EL NOMBRE DE CLASE EQUIVOCADO, Y NO ES UN BUG DEL ADAPTADOR.
    # Medido sobre litellm 1.93.0: un 401 de un endpoint OpenAI-compat sale como
    # `BadRequestError` **con `status_code=401`** — la clase y el status se CONTRADICEN.
    #
    # HISTORIA DE ESTA FILA (por qué el comentario es largo y se queda). Cuando F3 midió
    # esto, `desde_litellm` clasificaba por nombre de clase ANTES que por status, así que
    # ganaba «BadRequest» → `error_upstream`: al usuario se le decía «revisá tu pedido»
    # cuando lo que pasaba era que su key no servía. La vara de F3 FIJÓ esa realidad con
    # su nombre —`401 → HOY da error_upstream`— justamente para que el día que se
    # arreglara, este test fallara y obligara a actualizarlo. **Ese día llegó en F2d**
    # (obra 0): `_STATUS_MANDA` en `errores_modelo.py` le da precedencia al status en los
    # cinco códigos accionables (401/402/403/404/429). La fila ahora exige lo correcto, y
    # el mecanismo funcionó exactamente como estaba previsto.
    casos = [
        ("401", "401 → key_invalida: litellm levanta BadRequestError con status_code=401 "
                "y el STATUS manda (precedencia de F2d)", E.KEY_INVALIDA, False),
        ("429", "429 con retry-after → rate_limit", E.RATE_LIMIT, True),
        ("500", "500 REAL (con servidor del otro lado) → proveedor_caido", E.PROVEEDOR_CAIDO, True),
    ]
    for modo, nombre, esperada, reint in casos:
        MODO["v"] = modo
        r = corr(A.acompletar("oss-direct", MSG, base_url_hint=BASE, extra={"api_base": BASE}))
        c = r.causa or {}
        ok(r.ok is False, f"{nombre}: no se devuelve como turno bueno")
        ok(c.get("causa") == esperada, nombre, f"dio {c.get('causa')}")
        ok(c.get("reintentable") is reint, f"{nombre} → reintentable={reint}",
           str(c.get("reintentable")))

    MODO["v"] = "429"
    r = corr(A.acompletar("oss-direct", MSG, base_url_hint=BASE, extra={"api_base": BASE}))
    ok((r.causa or {}).get("retry_after_s") == 37.0,
       "el retry-after del proveedor llega como 37.0 s (repair lo usa sobre su curva, §2.3)",
       str((r.causa or {}).get("retry_after_s")))

    MODO["v"] = "401"
    r401 = corr(A.acompletar("oss-direct", MSG, base_url_hint=BASE, extra={"api_base": BASE}))
    ok((r401.causa or {}).get("evidencia", {}).get("http_status") == 401,
       "el status 401 viaja en la evidencia — es lo que hizo posible el arreglo",
       str((r401.causa or {}).get("evidencia")))
    ok((r401.causa or {}).get("evidencia", {}).get("clase") == "BadRequestError",
       "y la evidencia deja registrada la clase que litellm inventó",
       str((r401.causa or {}).get("evidencia", {}).get("clase")))
    # La contradicción queda ANOTADA, no borrada: el día que litellm arregle sus clases,
    # esta marca deja de aparecer y se sabrá que la precedencia ya no se está usando acá.
    ok((r401.causa or {}).get("evidencia", {}).get("precedencia") == "status",
       "y la evidencia declara que ganó el STATUS sobre la clase",
       str((r401.causa or {}).get("evidencia")))
    ok((r401.causa or {}).get("evidencia", {}).get("clase_decia") == E.ERROR_UPSTREAM,
       "dejando por escrito qué habría salido con la clase mandando (error_upstream)",
       str((r401.causa or {}).get("evidencia", {}).get("clase_decia")))

    # LA FILA P1.d
    seccion("1b · LA FILA P1.d — la red no es el servidor")
    r = corr(A.acompletar("oss-direct", MSG, base_url_hint=MUERTO, extra={"api_base": MUERTO}))
    c = r.causa or {}
    ok(c.get("causa") == E.SIN_RED,
       "un host inexistente → `sin_red`", str(c.get("causa")))
    ok(c.get("causa") != E.PROVEEDOR_CAIDO,
       "y NO `proveedor_caido` — que es lo que LiteLLM entrega crudo (500 con DNS abajo)")
    ok(c.get("reintentable") is True, "sin_red es reintentable (repair hace backoff, §3)")
    MODO["v"] = "500"
    r5 = corr(A.acompletar("oss-direct", MSG, base_url_hint=BASE, extra={"api_base": BASE}))
    ok((r5.causa or {}).get("causa") == E.PROVEEDOR_CAIDO,
       "y un 5xx CON servidor vivo SÍ es proveedor_caido — la otra mitad de la regla")

    # ══ 2 · MODEL_FINAL ════════════════════════════════════════════════════════════
    seccion("2 · model_final — del PROVEEDOR, jamás del request")
    MODO["v"] = "200"
    r = corr(A.acompletar("oss-direct", MSG, base_url_hint=BASE, extra={"api_base": BASE}))
    ok(r.ok, "el turno sale bien", str(r.causa))
    ok(r.model_final == "modelo-REAL-DEL-PROVEEDOR",
       "model_final es el que respondió el proveedor, no el pedido", str(r.model_final))
    pedido = A._models.resolve("oss-direct").model
    ok(r.model_final != pedido,
       f"y es DISTINTO del pedido ({pedido}) — si fueran iguales el test no probaría nada")
    fuente = A._AQUI and open(_AQUI / "adaptador_litellm.py").read()
    ok("_hidden_params['litellm_model_name']" in fuente or "litellm_model_name" in fuente,
       "el campo que MIENTE está nombrado en el módulo…")
    ok("hp.get(\"litellm_model_name\")" not in fuente and "['litellm_model_name']" not in fuente.replace(
        "`_hidden_params['litellm_model_name']`", ""),
       "…pero SÓLO para decir que no se usa (nunca se lee)")

    # ══ 3 · USAGE ══════════════════════════════════════════════════════════════════
    seccion("3 · usage — medido vs no reportado")
    MODO["v"] = "200"
    r = corr(A.acompletar("oss-direct", MSG, base_url_hint=BASE, extra={"api_base": BASE}))
    ok(r.tokens == {"prompt_tokens": 7, "completion_tokens": 3} and r.tokens_medidos is True,
       "provider que SÍ reporta → los números y tokens_medidos=True", f"{r.tokens} {r.tokens_medidos}")

    MODO["v"] = "200_sin_usage"
    r = corr(A.acompletar("oss-direct", MSG, base_url_hint=BASE, extra={"api_base": BASE}))
    ok(r.tokens == {"prompt_tokens": None, "completion_tokens": None},
       "provider que NO reporta → None, no los ceros que devuelve litellm", str(r.tokens))
    ok(r.tokens_medidos is False, "y tokens_medidos=False", str(r.tokens_medidos))
    ok(r.usd is None, "sin tokens medidos no hay usd (jamás un 0.0 inventado)", str(r.usd))
    # la prueba de que litellm SÍ devolvía ceros con cara de medición
    _l = A.init_litellm()
    _raw = corr(_l.acompletion(model="qwen3:8b", custom_llm_provider="openai",
                               messages=MSG, api_base=BASE, api_key="sin-auth",
                               timeout=30, num_retries=0))
    ok(_raw.usage.prompt_tokens == 0 and _raw.usage.completion_tokens == 0,
       "EL CONTRASTE: litellm crudo devuelve Usage(0,0,0) — ceros con cara de medición",
       str(_raw.usage))
    _rc = _raw._hidden_params.get("response_cost")
    ok(_rc in (0.0, None),
       f"y response_cost={_rc!r}: un no-dato disfrazado (0.0 sería indistinguible de «gratis»; "
       f"None es honesto pero igual de inservible para cobrar)", str(_rc))

    # ══ 4 · STREAMING ══════════════════════════════════════════════════════════════
    seccion("4 · streaming — llega, corta de verdad, y el usage no se estima")

    async def _leer_todo():
        textos, final = [], None
        async for clase, carga in A.acompletar_stream("oss-direct", MSG, base_url_hint=BASE,
                                                      extra={"api_base": BASE}):
            if clase == "texto":
                textos.append(carga)
            else:
                final = carga
        return textos, final

    MODO["v"] = "stream"
    textos, final = corr(_leer_todo())
    ok(len(textos) >= 4, f"llegaron {len(textos)} deltas", str(textos[:5]))
    ok(final and final.texto == "".join(textos), "el texto final es la suma de los deltas")
    ok(final and final.model_final is None,
       "MEDIDO: en streaming litellm ECOA el id pedido en los chunks, así que NO hay "
       "model_final honesto — y no se inventa uno", str(final and final.model_final))
    ok(final and final.meta.get("model_final_ecoado") is True,
       "y la meta declara por qué está en None", str(final and final.meta))
    ok(final and final.tokens_medidos is True and final.tokens["completion_tokens"] == 4,
       "el provider mandó usage en un chunk → MEDIDO", f"{final.tokens} {final.tokens_medidos}")

    MODO["v"] = "stream_sin_usage"
    textos2, final2 = corr(_leer_todo())
    ok(len(textos2) >= 4, "el stream sin usage también entrega sus deltas")
    ok(final2 and final2.tokens_medidos is False,
       "litellm INYECTÓ un usage estimado → se detecta contra token_counter y sale medidos=False",
       f"{final2.tokens} {final2.tokens_medidos}")
    ok(final2 and final2.tokens == {"prompt_tokens": None, "completion_tokens": None},
       "y los tokens son None, no el número que tiktoken adivinó", str(final2.tokens))
    ok(final2 and final2.meta.get("usage_estimado_por_litellm") is True,
       "la meta lo declara: usage_estimado_por_litellm=True", str(final2.meta))
    # y la prueba de que lo que litellm iba a entregar ERA una estimación
    _est = _l.token_counter(model="qwen3:8b", text="".join(textos2))
    ok(isinstance(_est, int) and _est > 0,
       f"EL CONTRASTE: token_counter local da {_est} — ése es el número que litellm habría "
       f"presentado como medido")

    seccion("4b · cortar el stream a mitad CIERRA de verdad")
    MODO["v"] = "stream_largo"
    EVENTOS.clear()

    async def _cortar():
        n = 0
        agen = A.acompletar_stream("oss-direct", MSG, base_url_hint=BASE,
                                   extra={"api_base": BASE})
        async for clase, _ in agen:
            if clase == "texto":
                n += 1
                if n >= 3:
                    break
        await agen.aclose()          # el `finally` del adaptador corre acá
        return n

    n = corr(_cortar())
    time.sleep(1.5)
    ok(n == 3, "se consumieron 3 deltas y se cortó", str(n))
    ok(any("detectó el cierre" in e for e in EVENTOS),
       "el STUB confirma que el cliente cerró: el proveedor dejó de servir",
       str(EVENTOS))
    ok(not any("NUNCA cerró" in e for e in EVENTOS),
       "y NO se sirvieron los 300 chunks — que es lo que pasa sin `aclose()` (§P6.a)")

    seccion("4c · cancelar la Task deja todo limpio")
    EVENTOS.clear()

    async def _cancelar():
        consumidos = {"n": 0}

        async def consumir():
            async for clase, _ in A.acompletar_stream("oss-direct", MSG, base_url_hint=BASE,
                                                      extra={"api_base": BASE}):
                if clase == "texto":
                    consumidos["n"] += 1

        t = asyncio.create_task(consumir())
        await asyncio.sleep(0.5)
        t.cancel()
        cancelada = False
        try:
            await t
        except asyncio.CancelledError:
            cancelada = True
        await asyncio.sleep(1.2)
        return cancelada, consumidos["n"]

    cancelada, consumidos = corr(_cancelar())
    ok(cancelada, "la CancelledError se propaga (el usuario aprieta «parar»)")
    ok(consumidos > 0, f"y alcanzó a consumir {consumidos} deltas antes")
    ok(any("detectó el cierre" in e for e in EVENTOS),
       "el stub confirma el cierre también por cancelación", str(EVENTOS))

    # ══ 5 · EL PUENTE SYNC ═════════════════════════════════════════════════════════
    seccion("5 · puente sync — el patrón de `transporte_sdk`, no un loop a mano")
    MODO["v"] = "200"
    rs = A.completar("oss-direct", MSG, base_url_hint=BASE, extra={"api_base": BASE})
    ok(rs.ok and rs.model_final == "modelo-REAL-DEL-PROVEEDOR",
       "`completar()` sync devuelve lo mismo que el async", str(rs.como_dict())[:110])
    MODO["v"] = "stream"
    piezas = [c for k, c in A.completar_stream("oss-direct", MSG, base_url_hint=BASE,
                                               extra={"api_base": BASE}) if k == "texto"]
    ok(len(piezas) >= 4, f"`completar_stream()` sync entrega {len(piezas)} deltas", str(piezas[:4]))
    fuente = open(_AQUI / "adaptador_litellm.py").read()
    ok("start_blocking_portal" in fuente and "new_event_loop" not in fuente,
       "usa el portal de anyio (patrón `transporte_sdk.py:317`), no un loop propio")

    srv.shutdown()

# ══ 6 · LAS VARAS ANTERIORES ═══════════════════════════════════════════════════════
seccion("6 · verify_traductor · cli_streaming · cli_slots · cli_usage")
for nombre, ruta in (("verify_traductor", _AQUI / "verify_traductor.py"),
                     ("verify_cli_streaming", _AQUI / "cli_brain" / "verify_cli_streaming.py"),
                     ("verify_cli_slots", _AQUI / "cli_brain" / "verify_cli_slots.py"),
                     ("verify_cli_usage", _AQUI / "cli_brain" / "verify_cli_usage.py")):
    r = subprocess.run([sys.executable, str(ruta)], capture_output=True, text=True,
                       timeout=900, env=dict(os.environ))
    ok(r.returncode == 0, f"{nombre}.py sale con exit 0",
       (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "")
    # [H4a] `"TODO VERDE" in stdout` daba True también con `TODO VERDE (con 3 salteo(s)…)`:
    # el verde barato de la hija se propagaba al padre sin que nadie lo viera. `es_verde_limpio`
    # pide la línea ENTERA — verde sin salteos, o no es verde.
    ok(_V.es_verde_limpio(r.stdout),
       f"y dice TODO VERDE, SIN salteos ({r.stdout.count('✓')} aserciones)",
       (r.stdout.strip().splitlines() or [""])[-1])

# [H4a] El cierre pasa por `qa/lib/veredicto.py`: con salteos declarados la última
# línea ya NO es el string pelado `TODO VERDE`. La regla vive en un solo lugar.
sys.exit(_V.cerrar(_fallos, _salteados, _criticos))
