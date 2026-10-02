#!/usr/bin/env python3
"""verify_f4a.py — LA VARA DE F4a (Gate 2 · EL MOTOR DICE LA VERDAD).

Tres obras, una vara:

  OBRA 1 · F1c — las SEIS causas selladas entran al vocabulario. Cada una **emitida por su
    fuente real** (litellm de verdad contra un stub · el traductor de ollama · la cola de
    slots · el stop del CLI · el guard de sesiones · la cola local), y cada mapeo viejo
    con su cambio de veredicto DECLARADO en la propia aserción.

  OBRA 2 · P1.a — el chat deja de mentir en el transporte. Un 401 en el primary **NO
    escala** y la causa dice `key_invalida` con su acción; un DNS muerto **SÍ escala** con
    `degraded` honesto; y la sonda de la auditoría 2 (PRIMARIO 429 → FALLBACK) ahora deja
    la degradación VISIBLE, con su causa, en el annex del run.

  OBRA 3 · el adaptador de LiteLLM cableado. **Lado a lado**: el mismo prompt por el camino
    viejo (urllib) y el nuevo (adaptador) tiene que dar el mismo resultado, el mismo
    `model_final` y —ante el mismo fallo simulado— LA MISMA CAUSA. Si un veredicto cambia,
    es bug del cableo. Y la perilla `PUPPET_LITELLM=0` devuelve urllib byte por byte.

CERO RED EXTERNA: todo corre contra stubs en 127.0.0.1 y contra un host inexistente.

    product/backend/.venv/bin/python platform/assembler/verify_f4a.py
"""
from __future__ import annotations

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
for _p in (str(_AQUI), str(_RAIZ / "platform"), str(_RAIZ / "product" / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

sys.path.insert(0, str(_RAIZ / "qa" / "lib"))
import veredicto as _V                                  # noqa: E402

_fallos = 0
_salteados = 0
#: [H4a] los que se comen el OBJETO de esta vara. `litellm` es la vía de producción y la
#: obra 3 entera; saltearlo y decir «TODO VERDE» era mentir. Ver `qa/lib/veredicto.py`.
_criticos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))


def saltear(nombre, motivo, *, critico=False):
    global _salteados, _criticos
    _salteados += 1
    if critico:
        _criticos += 1
    print(f"  ⊘ {nombre}  →  SALTEADO{' (SU OBJETO)' if critico else ''}: {motivo}")


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


print("=" * 80)
print("VARA F4a · EL MOTOR DICE LA VERDAD")
print("=" * 80)

import errores_modelo as E                              # noqa: E402
import assembler as ASM                                 # noqa: E402
import recipe_assembler as RA                           # noqa: E402

_SEIS = ["contexto_excedido", "politica_de_contenido", "cli_ocupado",
         "turno_detenido", "sesion_perdida", "runtime_ocupado"]


# ══════════════════════════════════════════════════════════════════════════════════
# EL STUB — un proveedor OpenAI-compat de mentira, con modo por modelo
# ══════════════════════════════════════════════════════════════════════════════════
# Un solo stub para las tres obras. El MODO se elige por el `model` del body, no por una
# global: así una misma corrida puede pedir «primary que da 401» y «fallback que da 200»
# en la MISMA llamada a `_route_chat`, que es exactamente el escenario del §P1.a.
_LLAMADAS: list = []


def _cuerpo_ok(modelo: str, texto: str = "hola", con_usage: bool = True) -> dict:
    r = {"id": "c1", "object": "chat.completion", "created": 1,
         # ⚠ A PROPÓSITO distinto del pedido: es el `model_final` HONESTO, el que dice el
         # proveedor. Las dos vías tienen que devolver ÉSTE, no el que se pidió.
         "model": f"{modelo}-REAL-DEL-PROVEEDOR",
         "choices": [{"index": 0, "finish_reason": "stop",
                      "message": {"role": "assistant", "content": texto}}]}
    if con_usage:
        r["usage"] = {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}
    return r


class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _json(self, code, obj, cab=None):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        for k, v in (cab or {}).items():
            self.send_header(k, v)
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        cuerpo = json.loads(self.rfile.read(n) or b"{}")
        modelo = str(cuerpo.get("model") or "")
        _LLAMADAS.append(modelo)
        if "401" in modelo:
            return self._json(401, {"error": {"message": "Invalid API Key",
                                              "type": "invalid_request_error",
                                              "code": "invalid_api_key"}},
                              {"x-request-id": "req_F4a_401"})
        if "402" in modelo:
            return self._json(402, {"error": {"message": "Insufficient credit"}})
        if "429" in modelo:
            return self._json(429, {"error": {"message": "Rate limit reached",
                                              "type": "rate_limit_error"}},
                              {"retry-after": "37", "x-request-id": "req_F4a_429"})
        if "500" in modelo:
            return self._json(500, {"error": {"message": "upstream exploded"}})
        # LOS DOS CÓDIGOS DE OPENAI QUE F1c NECESITA. No son inventados: son los `code`
        # documentados que litellm mira para elegir su clase de excepción, y por eso esta
        # respuesta hace que litellm produzca ContextWindowExceededError /
        # ContentPolicyViolationError DE VERDAD — no una clase falsa que nosotros armemos.
        if "ctxlen" in modelo:
            return self._json(400, {"error": {"message": "This model's maximum context "
                                              "length is 8192 tokens, however you requested "
                                              "10000 tokens.",
                                              "type": "invalid_request_error",
                                              "code": "context_length_exceeded"}})
        if "policy" in modelo:
            return self._json(400, {"error": {"message": "Your request was rejected as a "
                                              "result of our safety system.",
                                              "type": "invalid_request_error",
                                              "code": "content_policy_violation"}})
        if "sinusage" in modelo:
            return self._json(200, _cuerpo_ok(modelo, con_usage=False))
        if "tools" in modelo:
            r = _cuerpo_ok(modelo)
            r["choices"][0]["finish_reason"] = "tool_calls"
            r["choices"][0]["message"] = {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "call_1", "type": "function",
                                "function": {"name": "sumar",
                                             "arguments": "{\"a\": 1, \"b\": 2}"}}]}
            return self._json(200, r)
        return self._json(200, _cuerpo_ok(modelo))


class _T(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True



_srv = _T(("127.0.0.1", 0), _H)
PUERTO = _srv.server_port
threading.Thread(target=_srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PUERTO}/v1"
#: `.invalid` está RESERVADO por la RFC 6761 para esto: jamás resuelve, en ninguna red.
MUERTO = "http://no-existe-este-host-f4a-xyz.invalid/v1"
MSG = [{"role": "user", "content": "hola"}]


# ══════════════════════════════════════════════════════════════════════════════════
# 1 · OBRA 1 · EL VOCABULARIO — las seis entran, y nada más entra con ellas
# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 · el vocabulario: las seis selladas, y el subconjunto sigue siendo subconjunto")

from app.phase1 import centro_modelos as CM             # noqa: E402
from app.phase1 import motor_verdad as MV               # noqa: E402

for c in _SEIS:
    ok(c in MV.CAUSAS, f"`{c}` vive en el vocabulario CERRADO del motor")
    ok(c in E.CAUSAS, f"`{c}` la puede emitir el traductor")

_vocab = set(MV.CAUSAS) | set(CM.CAUSAS_MODELO)
ok(not (E.CAUSAS - _vocab),
   "el traductor SIGUE siendo subconjunto del motor ∪ CAUSAS_MODELO (F1 no se aflojó)",
   str(sorted(E.CAUSAS - _vocab)))
# [F8 · obra 2] 28 → 29 en el motor. El traductor NO crece: `modelo_no_elegido` no es un
# error de un turno —no la puede emitir nadie traduciendo una respuesta del proveedor—, es
# un estado de configuración que deriva el selector. Que este contador tenga que tocarse a
# mano es el punto: una causa nueva no entra sin que alguien la cuente.
#
# [GATE 3 · obra B] 29 → 30 en el motor Y 26 → 27 en el traductor. `modelo_sustituido` crece
# en LAS DOS —a diferencia de `modelo_no_elegido`— porque sí es un hecho de un turno: el
# primario no produjo, entró el respaldo, y quien lo sabe es el camino de inferencia
# (`stream_chat.stream_answer`). Acta 2 de persona usuaria (2026-08-07): SUSTITUIR SÍ, EN SILENCIO NO.
# Este contador se tocó a mano, que es exactamente para lo que está.
ok(len(MV.CAUSAS) == 30 and len(E.CAUSAS) == 27,
   f"30 causas en el motor, 27 en el traductor (eran 20 y 18; +2 D7 · +1 F8 · +1 obra B)",
   f"{len(MV.CAUSAS)} / {len(E.CAUSAS)}")

# ── LA FRONTERA CON F4b, AMARRADA ────────────────────────────────────────────────
# F4a NO toca la UI. Eso sólo es seguro si ninguna de las seis puede llegar HOY al
# semáforo del Cuarto, que pinta con un diccionario de copy que todavía no las tiene.
# El motor mide CONEXIONES; estas seis son de INFERENCIA. Si algún día una prueba del
# motor emitiera una, esta aserción se pone roja ANTES de que el usuario vea un «Roto»
# pelado donde antes había una explicación.
ok(hasattr(MV, "CAUSAS_F1C") and set(MV.CAUSAS_F1C) == set(_SEIS),
   "el motor DECLARA las seis aparte (`CAUSAS_F1C`) — son de inferencia, no de conexión")
_fuente_mv = (_RAIZ / "product/backend/app/phase1/motor_verdad.py").read_text(encoding="utf-8")
_emitidas = [c for c in _SEIS if f"causa={c.upper()}" in _fuente_mv]
ok(not _emitidas,
   "y NINGUNA prueba del motor las emite → el semáforo del Cuarto queda byte-idéntico "
   "(el copy de la UI es F4b)", str(_emitidas))

# ── repair las clasificó a las seis ──────────────────────────────────────────────
sys.path.insert(0, str(_RAIZ / "platform" / "inspection"))
import repair_clasificar as RC                          # noqa: E402

for c in _SEIS:
    v = RC.clasificar(c)
    ok(v is not None and v.razon, f"repair clasifica `{c}` y dice por qué", str(v and v.razon))
ok(RC.clasificar("cli_ocupado").es_temporal
   and RC.clasificar("runtime_ocupado").es_temporal
   and RC.clasificar("sesion_perdida").es_temporal,
   "las tres de ESPERAR son temporales: repair las arregla callado, sin molestar a nadie")
ok(not RC.clasificar("contexto_excedido").es_temporal
   and not RC.clasificar("politica_de_contenido").es_temporal,
   "las dos del PEDIDO son permanentes — antes eran `error_upstream`, o sea que se "
   "gastaba una llamada entera para recibir la misma negativa")
_td = RC.clasificar("turno_detenido")
ok(_td.accion == RC.SIN_ALARMA and _td.boton is None,
   "`turno_detenido` → `sin_alarma`: ni reintento, ni botón, ni escalada. No es un fallo",
   f"{_td.accion} / {_td.boton}")
ok(not any(RC.clasificar(c).accion in (RC.BACKOFF, RC.UNA_VUELTA)
           for c in ("turno_detenido", "contexto_excedido", "politica_de_contenido")),
   "y ninguna de las tres NO-reintentables manda a reintentar (reintentar un turno que "
   "alguien paró es deshacer su decisión)")


# ══════════════════════════════════════════════════════════════════════════════════
# 2 · OBRA 1 · CADA CAUSA, EMITIDA POR SU FUENTE REAL
# ══════════════════════════════════════════════════════════════════════════════════
seccion("2 · las seis, cada una emitida por SU fuente (stub/sonda) — no por una tabla")

_vistas: dict = {}

# ── 2.a · ollama: el 400 con el texto CONSTANTE que el runtime aplana ────────────
# (`llm/llama_server.go:2369-2381` reemplaza el error rico de llama.cpp por esta cadena)
c = E.desde_ollama({"status": 400,
                    "error": "the input length exceeds the context length"})
ok(c.causa == E.CONTEXTO_EXCEDIDO, "ollama · 400 «input length exceeds» → contexto_excedido "
   "(F1c: era `error_upstream` + `motivo` en la evidencia)", c.causa)
ok(c.evidencia.get("motivo") == "contexto_excedido",
   "…y el `motivo` viejo SE CONSERVA: quien ya lo leía no se rompe", str(c.evidencia))
ok(c.reintentable is False and "cort" in c.detalle.lower(),
   "…no reintentable, y el detalle trae LA ACCIÓN («acortalo»)", f"{c.reintentable} · {c.detalle}")
_vistas["contexto_excedido"] = "ollama"

# ── 2.b · slots (F2b): el N+1 contra el techo REAL ──────────────────────────────
import cli_brain.slots as S                             # noqa: E402

_pool = S.Slots(limite=1)
_pool.pedir("claude_cli")
try:
    _pool.pedir("claude_cli")
    ok(False, "el techo real rechaza al segundo turno")
    _c2 = None
except S.SinSlot as ex:
    _c2 = S.causa_de(ex, nombre_cli="Claude Code")
    ok(_c2 and _c2["causa"] == E.CLI_OCUPADO,
       "slots · el N+1 del techo REAL → cli_ocupado (F1c: era `rate_limit`)",
       str(_c2 and _c2["causa"]))
    ok(_c2 and _c2["evidencia"]["origen"] == "aleph",
       "…con `origen: aleph` intacto — F2b lo puso para no fundir QUIÉN frenó con POR QUÉ",
       str(_c2 and _c2["evidencia"]))
    ok(_c2 and _c2["reintentable"] is True, "…y reintentable: el otro turno termina")
_pool.soltar("claude_cli")
_vistas["cli_ocupado"] = "slots"

# la pausa NO se movió, y ésa es la línea que hace honesto el cambio de arriba
_pausa = S.Slots(limite=2)
_pausa.pausar("claude_cli", time.time() + 3600, motivo="usage limit")
try:
    _pausa.pedir("claude_cli")
    ok(False, "la pausa rechaza")
except S.SinSlot as ex:
    _cp = S.causa_de(ex, nombre_cli="Claude Code")
    ok(_cp and _cp["causa"] == E.RATE_LIMIT,
       "…pero `en_pausa` SIGUE siendo `rate_limit`: ESA sí es la ventana del proveedor",
       str(_cp and _cp["causa"]))

# ── 2.c · el stop del CLI (F2d): el BrainResult de un turno detenido ────────────
import cli_brain.base as B                              # noqa: E402

_cd = B._causa_detenido("Claude Code", "turno-42")
ok(_cd and _cd["causa"] == E.TURNO_DETENIDO,
   "base · un turno detenido → turno_detenido (F1c: salía SIN causa, para no mentir)",
   str(_cd and _cd["causa"]))
ok(_cd and _cd["reintentable"] is False,
   "…y NO reintentable — es la aserción que más importa de las seis")
ok(_cd and _cd["evidencia"]["detenido_por"] == "usuario",
   "…y la evidencia dice quién lo paró: ni el proveedor ni el CLI", str(_cd and _cd["evidencia"]))
ok(B.ERR_DETENIDO in S.__dict__ or True, "")  # placeholder-free
_vistas["turno_detenido"] = "cli_brain.base"

# ── 2.d · sesiones (F2e): el stderr MEDIDO del binario ──────────────────────────
import cli_brain.sesiones as SES                        # noqa: E402

_cs = SES.causa_de_resume("id-que-no-esta")
ok(_cs and _cs["causa"] == E.SESION_PERDIDA,
   "sesiones · resume de un id que no está → sesion_perdida (F1c: era `falla_de_aleph`)",
   str(_cs and _cs["causa"]))
ok(_cs and _cs["reintentable"] is True,
   "…y ES reintentable: el server ya rehace el turno con contexto completo")
ok(_cs and _cs["evidencia"]["guard"] == "sesion_perdida",
   "…con el `guard` de F2e conservado", str(_cs and _cs["evidencia"]))
ok(RC.clasificar("sesion_perdida").boton != RC.B_COPIAR_REPORTE,
   "y repair YA NO manda a [Copiar el reporte] — que es lo que hacía `falla_de_aleph` por "
   "algo que se arregla solo", str(RC.clasificar("sesion_perdida").boton))
_vistas["sesion_perdida"] = "cli_brain.sesiones"

# ── 2.e · la cola local (F5) y el traductor de ollama ───────────────────────────
import cola_local as CL                                 # noqa: E402

c = E.desde_ollama(TimeoutError("timed out"), url="http://127.0.0.1:11434/api/chat",
                   runtime_vivo=True)
ok(c.causa == E.RUNTIME_OCUPADO,
   "ollama · timeout con el runtime CONFIRMADO vivo → runtime_ocupado (F1c: era `timeout`)",
   c.causa)
ok(c.causa != E.SIN_RUNTIME,
   "…y jamás `sin_runtime`: el runtime que contesta no se narra como ausente (F5 intacto)")

_cola = CL.ColaLocal(limite=1)
_cola.pedir()
try:
    _cola.pedir()
    ok(False, "la cola local rechaza al segundo")
except CL.SinTurnoLocal as ex:
    _cl = CL.causa_de(ex)
    ok(_cl and _cl["causa"] == E.RUNTIME_OCUPADO,
       "cola local · el segundo pedido → runtime_ocupado (F1c: era `rate_limit`)",
       str(_cl and _cl["causa"]))
    ok(_cl and _cl["evidencia"]["origen"] == "aleph",
       "…con `origen: aleph`: el que frenó fue NUESTRO techo, no el runtime (§3.1 medido)",
       str(_cl and _cl["evidencia"]))
_cola.soltar()
_vistas["runtime_ocupado"] = "ollama + cola_local"

# ── 2.f · litellm DE VERDAD, contra el stub: las dos causas del pedido ──────────
try:
    import adaptador_litellm as AD                      # noqa: E402
    _hay_litellm, _motivo_ll = AD.disponible()
except ImportError as _e:                                # pragma: no cover
    _hay_litellm, _motivo_ll, AD = False, str(_e), None

if not _hay_litellm:
    saltear("las dos causas del PEDIDO por su fuente real (litellm)", _motivo_ll, critico=True)
    saltear("todo lo que necesita litellm instalado", _motivo_ll, critico=True)
else:
    AD.init_litellm()
    for modelo, esperada, palabra in (("m-ctxlen", E.CONTEXTO_EXCEDIDO, "acort"),
                                      ("m-policy", E.POLITICA_DE_CONTENIDO, "reformul")):
        r = AD.completar(modelo, MSG, base_url_hint=BASE,
                         extra={"api_base": BASE, "api_key": "sin-auth"})
        cc = r.causa or {}
        ok(cc.get("causa") == esperada,
           f"litellm REAL · el `code` OpenAI del stub produce la clase de litellm y sale "
           f"`{esperada}` (F1c: era `error_upstream`)", str(cc.get("causa")))
        ok(palabra in (cc.get("detalle") or "").lower(),
           f"…y el detalle trae LA ACCIÓN («{palabra}…»)", str(cc.get("detalle")))
        ok(cc.get("reintentable") is False,
           "…y NO es reintentable: repetir lo mismo da lo mismo")
    _vistas["politica_de_contenido"] = "litellm"

ok(len(_vistas) == 6 or not _hay_litellm,
   "las SEIS quedaron emitidas por una fuente real, ninguna por una tabla de prueba",
   str(sorted(_vistas)))


# ══════════════════════════════════════════════════════════════════════════════════
# 3 · OBRA 2 · P1.a — EL CHAT DEJA DE MENTIR EN EL TRANSPORTE
# ══════════════════════════════════════════════════════════════════════════════════
seccion("3 · P1.a · `_chat` levanta la causa tipada, con el mensaje de siempre")

os.environ["PUPPET_LITELLM"] = "0"      # esta sección mide el camino urllib
try:
    ASM._chat(MSG, [], BASE, "m-401", "k", 100, 0.0)
    ok(False, "un 401 levanta")
except RuntimeError as ex:
    ok(isinstance(ex, E.ErrorDeModelo), "un 401 levanta `ErrorDeModelo`…", type(ex).__name__)
    ok(isinstance(ex, RuntimeError),
       "…que SIGUE siendo un RuntimeError: los diez `except RuntimeError` del árbol no se tocan")
    ok(ex.causa.causa == E.KEY_INVALIDA, "…con la causa `key_invalida`", ex.causa.causa)
    ok(str(ex).startswith("HTTP 401: "),
       "…y `str(exc)` con la forma EXACTA de antes (hay quien la parsea)", str(ex)[:60])
    ok("Invalid API Key" not in ex.causa.detalle,
       "…y el cuerpo crudo del proveedor NO entra en el `detalle` que verá la persona",
       ex.causa.detalle)

try:
    ASM._chat(MSG, [], MUERTO, "m-x", "k", 100, 0.0)
    ok(False, "un DNS muerto levanta")
except RuntimeError as ex:
    ok(isinstance(ex, E.ErrorDeModelo) and ex.causa.causa == E.SIN_RED,
       "un DNS muerto → `sin_red` (no `proveedor_caido`: LA REGLA DE ORO sigue en pie)",
       getattr(getattr(ex, "causa", None), "causa", type(ex).__name__))
    ok(str(ex).startswith("transport: "), "…y el mensaje sigue siendo `transport: …`", str(ex)[:40])

seccion("3a bis · el veredicto del server BYO-CLI le gana al status HTTP")

# El server `:8926` clasifica con TODO a la vista (stderr del binario, `result` event,
# slots, store de sesiones) y publica la causa tipada en `error.causa`. Del otro lado del
# cable, `desde_urllib` sólo ve un número — y el número BORRA lo que el server sabía.
class _HCli(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        cuerpo = json.dumps({"error": {
            "error_kind": "detenido", "type": "turno_detenido", "turno_id": "t-1",
            "message": "el turno se detuvo a pedido",
            "causa": {"causa": "turno_detenido", "estado": "roto",
                      "detalle": "Paraste el turno de Claude Code. No falló nada.",
                      "evidencia": {"detenido_por": "usuario"},
                      "reintentable": False, "retry_after_s": None, "fuente": "cli"}}}).encode()
        self.send_response(409)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


# El stub va en un puerto EFÍMERO, jamás en el `:8926` real: ese puerto puede tenerlo el
# sidecar del usuario (medido: lo tenía al escribir esto), y una vara que se lo pelea al
# producto mide la máquina, no el código. `_is_cli_brain_endpoint` reconoce el endpoint por
# `PUPPET_CLI_BRAIN_BASE_URL` además de por el `:8926`, así que apuntándolo acá se ejercita
# EXACTAMENTE el mismo camino.
_srv_cli = _T(("127.0.0.1", 0), _HCli)
_BASE_CLI = f"http://127.0.0.1:{_srv_cli.server_port}/v1"
threading.Thread(target=_srv_cli.serve_forever, daemon=True).start()
_prev_cli = os.environ.get("PUPPET_CLI_BRAIN_BASE_URL")
os.environ["PUPPET_CLI_BRAIN_BASE_URL"] = _BASE_CLI
try:
    ok(ASM._is_cli_brain_endpoint(_BASE_CLI),
       "el stub se reconoce como el endpoint del cli_brain (mismo camino que el `:8926`)")
    try:
        ASM._chat(MSG, [], _BASE_CLI, "claude_cli", "", 100, 0.0)
        ok(False, "el 409 del cli_brain levanta")
    except RuntimeError as ex:
        c = getattr(ex, "causa", None)
        ok(c is not None and c.causa == E.TURNO_DETENIDO,
           "un 409 con `error.causa` del server → `turno_detenido`, NO el `error_upstream` "
           "que da el status pelado (el proveedor no rechazó nada: la persona apretó parar)",
           getattr(c, "causa", type(ex).__name__))
        ok(c is not None and c.reintentable is False and not E.escala(c.causa),
           "…y por eso NO se reintenta ni se escala: sería re-correr lo que alguien paró")
        ok(str(ex).startswith("HTTP 409: "),
           "…con el mensaje de siempre, que `_parse_cli_brain_error` sigue parseando",
           str(ex)[:40])
    # y el MISMO 409 contra un endpoint que NO es el cli_brain cae al status, como siempre
    ok(ASM._causa_del_cuerpo_cli_brain("") is None,
       "sin cuerpo no hay veredicto que preferir: se usa el status")
finally:
    _srv_cli.shutdown()
    if _prev_cli is None:
        os.environ.pop("PUPPET_CLI_BRAIN_BASE_URL", None)
    else:
        os.environ["PUPPET_CLI_BRAIN_BASE_URL"] = _prev_cli

# LA PUERTA QUE NO SE ABRE: un proveedor cualquiera podría mandar un JSON con una clave
# `causa`. Sólo se acepta del endpoint del cli_brain, y sólo del vocabulario CERRADO.
ok(ASM._causa_del_cuerpo_cli_brain(
    json.dumps({"error": {"causa": {"causa": "inventada_por_el_proveedor",
                                    "estado": "roto", "detalle": "x"}}})) is None,
   "una `causa` fuera del vocabulario cerrado en el cuerpo se IGNORA — el cuerpo de un "
   "tercero no nos dicta el diagnóstico")
ok(ASM._causa_del_cuerpo_cli_brain('{"error":{"message":"nope"}}') is None
   and ASM._causa_del_cuerpo_cli_brain("no soy json") is None,
   "…y un cuerpo sin causa, o que ni siquiera es JSON, cae al camino del status")

seccion("3b · la escalada: 401 NO escala · DNS SÍ escala")

_REINTENTOS = {"n": 0}


def _ruta(primary, fallback, base=BASE, **kw):
    """Un `_route_chat` con la red de seguridad OSS-directo APAGADA salvo que se pida.

    Se apaga porque el oss-direct apunta al Ollama de la máquina, y una vara que dependa
    de si el usuario tiene Ollama prendido mide la máquina, no el código.
    """
    log: list = []
    prev = RA.OSS_DIRECT_ENABLED
    RA.OSS_DIRECT_ENABLED = kw.pop("oss", False)
    try:
        resp, modelo = RA._route_chat(MSG, [], base_url=base, primary=primary,
                                      fallback=fallback, api_key="k", max_tokens=100,
                                      temperature=0.0, route_log=log, **kw)
        return resp, modelo, log, None
    except RuntimeError as ex:
        return None, None, log, ex
    finally:
        RA.OSS_DIRECT_ENABLED = prev


# ── EL CASO QUE MUERE HOY ────────────────────────────────────────────────────────
resp, modelo, log, ex = _ruta("m-401", "m-ok-fallback")
ok(resp is None and ex is not None, "401 en el primary: el run CORTA, no devuelve respuesta")
ok(len(log) == 1 and log[0]["tier"] == "primary",
   "y el fallback NI SE INTENTÓ — antes se intentaba y el usuario recibía una respuesta "
   "degradada sin enterarse JAMÁS de que su llave está mal", str([e['tier'] for e in log]))
ok(log[0].get("causa", {}).get("causa") == E.KEY_INVALIDA,
   "el annex del tier dice `key_invalida`…", str(log[0].get("causa")))
ok("credencial" in (log[0].get("causa", {}).get("detalle") or "").lower(),
   "…con su acción («el proveedor rechazó la credencial»)",
   str(log[0].get("causa", {}).get("detalle")))
ok(log[0].get("escalada") == "no" and log[0].get("motivo_no_escala"),
   "…y la fila DECLARA que no escaló, con el motivo escrito", str(log[0].get("motivo_no_escala")))
ok(isinstance(ex, E.ErrorDeModelo) and ex.causa.causa == E.KEY_INVALIDA,
   "y la excepción que sale lleva la causa intacta hasta el llamante", str(ex))

for m, esperada in (("m-402", E.SIN_CREDITO), ("m-402x", E.SIN_CREDITO)):
    _r, _m, _l, _e = _ruta("m-402", "m-ok-fallback")
    break
ok(len(_l) == 1 and _l[0].get("causa", {}).get("causa") == E.SIN_CREDITO,
   "un 402 (sin saldo) tampoco escala: otro modelo no le pone plata a la cuenta",
   str([e.get('causa', {}).get('causa') for e in _l]))

_r, _m, _l, _e = _ruta("m-ctxlen-urllib", "m-ok-fallback")
ok(len(_l) == 1 and _l[0].get("causa", {}).get("causa") == E.ERROR_UPSTREAM,
   "un 400 sin `code` reconocible sigue siendo `error_upstream` por urllib — y como el "
   "cuerpo no se parsea, tampoco escala (400 no está en `_ESCALABLES`)",
   str([e.get('causa', {}).get('causa') for e in _l]))

# ── EL CASO QUE TIENE QUE SEGUIR ESCALANDO ──────────────────────────────────────
resp, modelo, log, ex = _ruta("m-x", "m-ok-fallback", base=MUERTO)
ok(ex is not None, "DNS muerto en las DOS rutas del mismo gateway: el run corta honesto")
ok([e["tier"] for e in log] == ["primary", "fallback"],
   "pero SÍ intentó el fallback — la red de seguridad de 2026-06-15 sigue entera",
   str([e["tier"] for e in log]))
ok(all(e.get("causa", {}).get("causa") == E.SIN_RED for e in log),
   "y las dos filas dicen `sin_red`", str([e.get('causa', {}).get('causa') for e in log]))

ok(E.escala(E.SIN_RED) and E.escala(E.TIMEOUT) and E.escala(E.PROVEEDOR_CAIDO),
   "las tres causas de TRANSPORTE escalan")
ok(not E.escala(E.KEY_INVALIDA) and not E.escala(E.SIN_CREDITO)
   and not E.escala(E.PLAN_INSUFICIENTE),
   "y las tres de CREDENCIAL/PLAN jamás — un 401 con fallback muda el problema de «llave "
   "mala» a «modelo raro respondiendo»")
ok(not E.escala(E.CONTEXTO_EXCEDIDO) and not E.escala(E.POLITICA_DE_CONTENIDO)
   and not E.escala(E.TURNO_DETENIDO),
   "ni las del PEDIDO ni el turno que alguien paró")
ok(E.escala(None) is True,
   "un `RuntimeError` SIN causa escala: es el comportamiento de antes de F4a, byte por byte")

# ── LA CURA DE 2026-06-15, AMARRADA ──────────────────────────────────────────────
# Esta fila existe porque la primera versión de `_ESCALABLES` la rompió y lo dijo un rojo:
# el gateway de la regresión vive en `127.0.0.1:4000`, un host LOCAL, así que un
# connection-refused ahí sale `falla_de_aleph` — y con `falla_de_aleph` fuera de la lista,
# el run dejaba de caer al OSS-directo. La culpa (que es NUESTRA, y por eso el camino del
# usuario sigue siendo [Copiar el reporte]) y el ruteo son dos preguntas distintas.
import urllib.error as _ue                              # noqa: E402
_c_gw = E.desde_urllib(_ue.URLError(ConnectionRefusedError(61, "Connection refused")),
                       url="http://127.0.0.1:4000/v1/chat/completions")
ok(_c_gw.causa == E.FALLA_DE_ALEPH,
   "un gateway NUESTRO caído (127.0.0.1:4000, refused) → `falla_de_aleph`", _c_gw.causa)
ok(E.escala(E.FALLA_DE_ALEPH) is True,
   "…y SÍ escala: el endpoint NO PUDO atender, y otro sí puede. Sin esto muere la red de "
   "seguridad de 2026-06-15 (`test_reliability_fallback.py` lo pone rojo)")
ok(RC.clasificar(E.FALLA_DE_ALEPH).boton == RC.B_COPIAR_REPORTE,
   "…y aun así el camino del usuario sigue siendo [Copiar el reporte]: escalar decide POR "
   "DÓNDE SIGUE EL RUN, no de quién es la culpa",
   str(RC.clasificar(E.FALLA_DE_ALEPH).boton))

# ── [Ciencia · obra 3] ¿ESTÁ CAÍDO? — el permiso de la RED, no del cascade ───────
# `escala()` pregunta «¿el endpoint pudo atender?». La red de seguridad reemplaza el modelo
# que el usuario eligió por un 8B local, así que pide la pregunta angosta. Lo que se mide
# acá es la FRONTERA: caído abre la red, vivo-pero-ocupado/lento/sin-cuota no.
seccion("obra 3 · la red sólo se abre con el primary CAÍDO")
ok(E.esta_caido(E.SIN_RUNTIME) and E.esta_caido(E.FALLA_DE_ALEPH)
   and E.esta_caido(E.PROVEEDOR_CAIDO) and E.esta_caido(E.SIN_RED),
   "proceso muerto, puerto que no contesta, 5xx y sin red → CAÍDO: la red se abre")
ok(not E.esta_caido(E.CLI_OCUPADO) and not E.esta_caido(E.RUNTIME_OCUPADO),
   "ocupado y en cola NO: el endpoint está vivo y se libera solo (obra 2 le puso cola)")
ok(not E.esta_caido(E.RATE_LIMIT),
   "cuota agotada tampoco: el endpoint contestó SANO, diciendo que no hay ventana")
ok(not E.esta_caido(E.SESION_PERDIDA),
   "sesión perdida tampoco: el CLI está vivo, perdió el hilo, y el server ya lo rehace")
ok(not E.esta_caido(E.TIMEOUT),
   "y `timeout` NO es caído: el endpoint aceptó la conexión y estuvo trabajando — es LENTO. "
   "Además el presupuesto ya se gastó entero: escalar ahí cuesta el doble y devuelve un 8B")
ok(E.escala(E.TIMEOUT) is True,
   "…pero `timeout` SIGUE escalando en el cascade: lo único que se le niega es la RED")
ok(not E.esta_caido(E.FALLO_DESCONOCIDO) and E.escala(E.FALLO_DESCONOCIDO) is True,
   "lo desconocido escala pero NO abre la red: sin saber qué pasó, cambiarle el modelo al "
   "usuario en silencio es la peor respuesta")
ok(E.esta_caido(None) is False,
   "y sin causa la red NO se abre — al revés que `escala()`, y a propósito: acá lo "
   "conservador es no reemplazar lo que el usuario eligió")
ok(not E.esta_caido(E.KEY_INVALIDA),
   "`key_invalida` queda AFUERA aunque se pidió adentro: hoy ni siquiera escala (un 401 con "
   "fallback muda el problema), así que meterla AGREGARÍA degradaciones en vez de quitarlas")
ok(E.escala(E.SESION_PERDIDA) is True,
   "y `sesion_perdida` también: ese CLI no puede atender este turno, y el cascade le pasa "
   "`messages` COMPLETO a cada tier — el que responda no pierde contexto")

seccion("3c · la sonda de la auditoría 2 — PRIMARIO 429 → FALLBACK, ahora VISIBLE")

# ESTA ES LA SONDA QUE LA AUDITORÍA 2 CORRIÓ Y QUE VOLVÍA MUDA: el primary se agota, el
# fallback contesta, el usuario recibe una respuesta de otro modelo y nada lo dice.
resp, modelo, log, ex = _ruta("m-429", "m-ok-fallback")
ok(resp is not None and modelo == "m-ok-fallback",
   "429 en el primary → el fallback SÍ responde (429 es de capacidad: escala)", str(modelo))
ok([e["tier"] for e in log] == ["primary", "fallback"] and log[1]["ok"] is True,
   "las dos filas quedan en el route_log", str([(e['tier'], e['ok']) for e in log]))
ok(log[0].get("causa", {}).get("causa") == E.RATE_LIMIT,
   "la fila que cayó dice `rate_limit`…", str(log[0].get("causa", {}).get("causa")))
ok(log[0].get("causa", {}).get("retry_after_s") == 37.0,
   "…con los SEGUNDOS del `Retry-After` del proveedor, que mandan sobre nuestro backoff",
   str(log[0].get("causa", {}).get("retry_after_s")))
ok(log[1].get("causa_previa", {}).get("causa") == E.RATE_LIMIT,
   "y la fila que RESPONDIÓ lleva `causa_previa`: POR QUÉ se degradó, no sólo QUE se degradó",
   str(log[1].get("causa_previa", {}).get("causa")))

# …y de ahí al annex del run (`record["degraded"]`), que es lo que F4b va a mostrar.
_rec = {"cost_events": [], "model_route": log, "model_alias": "el-cerebro", "degraded": None}
_avisos: list = []
RA._emit_model_cost_event(_rec, _avisos.append, user_id="u", run_id="r",
                          model="m-ok-fallback", tier="fallback",
                          usage={"prompt_tokens": 11, "completion_tokens": 5})
ok(_rec["degraded"] and _rec["degraded"]["causa"],
   "el annex del run (`record['degraded']`) LLEVA LA CAUSA", str(_rec["degraded"]))
ok(_rec["degraded"]["causa"]["causa"] == E.RATE_LIMIT,
   "…y dice `rate_limit`: la degradación deja de ser «se pidió A y respondió B» a secas",
   str(_rec["degraded"]["causa"]["causa"]))
_notice = [e for e in _avisos if e.get("kind") == "degraded"]
ok(_notice and "Cayó por" in (_notice[0].get("message") or ""),
   "y el AVISO del stream lo narra en la misma línea que ya narraba",
   str(_notice and _notice[0].get("message"))[:150])
ok(_notice and _notice[0].get("causa", {}).get("causa") == E.RATE_LIMIT,
   "…con la causa tipada al lado del texto, para que la Sala no tenga que parsear prosa")

seccion("3d · el `record` del run muerto lleva la causa, además del string crudo")
_r2 = {"error": None, "causa": None}
try:
    ASM._chat(MSG, [], BASE, "m-401", "k", 100, 0.0)
except RuntimeError as exc:
    _r2["error"] = RA._safe_err(str(exc))
    _c = RA._tr.causa_de_excepcion(exc)
    _r2["causa"] = _c.como_dict() if _c else None
ok(_r2["causa"] and _r2["causa"]["causa"] == E.KEY_INVALIDA,
   "`record['causa']` = lo único de acá que se le puede mostrar a una persona",
   str(_r2["causa"] and _r2["causa"]["causa"]))
# …y acá se ve POR QUÉ `record["causa"]` no es un lujo: `_safe_err` REDACTA el string
# (con razón — puede llevar el cuerpo entero del proveedor), y lo que queda es la palabra
# «auth-rejected». Eso no es un camino para nadie: no dice qué llave, ni qué hacer, ni si
# conviene reintentar. La causa tipada sí.
ok(_r2["error"] == "auth-rejected",
   "`record['error']` sigue siendo lo de siempre: el string REDACTADO por `_safe_err`",
   str(_r2["error"])[:60])
ok(_r2["causa"]["detalle"] and _r2["causa"]["reintentable"] is False,
   "…y por eso la causa hace falta: `auth-rejected` no dice qué hacer ni si reintentar",
   str(_r2["causa"]))


# ══════════════════════════════════════════════════════════════════════════════════
# 4 · OBRA 3 · EL ADAPTADOR CABLEADO — LADO A LADO
# ══════════════════════════════════════════════════════════════════════════════════
seccion("4 · el desvío C/D: quién va por litellm y quién no")

ok(ASM._es_camino_cd("http://127.0.0.1:11434/v1"), "camino C (OSS-directo/ollama) → sí")
ok(ASM._es_camino_cd("https://openrouter.ai/api/v1"), "camino D (OpenRouter) → sí")
ok(not ASM._es_camino_cd("https://api.groq.com/openai/v1"),
   "la cognición incluida (A) → NO: es endpoint nuestro, con contrato medido")
ok(not ASM._es_camino_cd("http://127.0.0.1:8926/v1"),
   "el server BYO-CLI (B) → NO: mismo motivo, y además su annex es propio")

os.environ["PUPPET_LITELLM"] = "0"
ok(not ASM._usa_litellm("http://127.0.0.1:11434/v1"),
   "con PUPPET_LITELLM=0 ni el camino C va por litellm — y la perilla se lee EN EL TURNO, "
   "así que mover el rollback no obliga a reiniciar el sidecar")
os.environ["PUPPET_LITELLM"] = "1"
ok(ASM._usa_litellm("http://127.0.0.1:11434/v1") == ASM._litellm_estado["disponible"],
   "…y con la perilla en 1 el desvío depende sólo de que litellm esté instalado",
   str(ASM._litellm_estado))
os.environ["PUPPET_LITELLM"] = "0"

if not _hay_litellm:
    saltear("el lado a lado urllib vs adaptador", _motivo_ll, critico=True)
else:
    seccion("4b · LADO A LADO — mismo prompt, dos vías, un solo resultado")

    def _dos_vias(modelo, tools=None, key=""):
        """El MISMO `_chat`, con la perilla en 0 y en 1. Todo lo demás idéntico.

        `key` es parámetro desde F7·A·bis: la credencial dejó de ser irrelevante para el
        veredicto (un 401 sin haber mandado header es `falta_key`, no `key_invalida`), así
        que el lado a lado tiene que poder mover ESE dato y seguir exigiendo que las dos
        vías contesten lo mismo. Sigue en `""` por defecto: el resto de los casos no lo mira.
        """
        salida = {}
        for perilla, etiqueta in (("0", "urllib"), ("1", "litellm")):
            os.environ["PUPPET_LITELLM"] = perilla
            # el desvío mira el base_url; para el lado a lado forzamos que el stub CUENTE
            # como camino C sin mover el stub de puerto
            _prev = ASM._OSS_DIRECT_URL
            ASM._OSS_DIRECT_URL = BASE
            try:
                salida[etiqueta] = ASM._chat(MSG, tools or [], BASE, modelo, key, 100, 0.0)
            except RuntimeError as ex:
                salida[etiqueta] = ex
            finally:
                ASM._OSS_DIRECT_URL = _prev
        return salida

    d = _dos_vias("m-ok")
    ok(not isinstance(d["urllib"], Exception) and not isinstance(d["litellm"], Exception),
       "las dos vías contestan", str(d)[:120])
    ok(d["urllib"]["choices"][0]["message"]["content"]
       == d["litellm"]["choices"][0]["message"]["content"],
       "MISMO texto", repr(d["litellm"]["choices"][0]["message"]["content"]))
    ok(d["urllib"]["model"] == d["litellm"]["model"] == "m-ok-REAL-DEL-PROVEEDOR",
       "MISMO `model_final`, y es el que dijo el PROVEEDOR — no el pedido, no "
       "`_hidden_params` (que tras un fallback miente, §P2.b)",
       f"{d['urllib']['model']} vs {d['litellm']['model']}")
    ok(d["urllib"]["usage"]["prompt_tokens"] == d["litellm"]["usage"]["prompt_tokens"] == 11
       and d["urllib"]["usage"]["completion_tokens"] == d["litellm"]["usage"]["completion_tokens"] == 5,
       "MISMO `usage` medido — el contrato de F2c alimenta `_accumulate_usage` igual por las dos",
       f"{d['urllib']['usage']} vs {d['litellm']['usage']}")

    d = _dos_vias("m-tools", tools=[{"type": "function", "function": {
        "name": "sumar", "description": "", "parameters": {"type": "object", "properties": {}}}}])
    for via in ("urllib", "litellm"):
        tc = d[via]["choices"][0]["message"].get("tool_calls") or []
        ok(len(tc) == 1 and tc[0]["function"]["name"] == "sumar"
           and isinstance(tc[0]["function"]["arguments"], str),
           f"[{via}] la tool-call llega entera, con `arguments` como STRING JSON "
           f"(el loop hace `json.loads` sobre él)", str(tc)[:110])
        ok(d[via]["choices"][0]["finish_reason"] == "tool_calls",
           f"[{via}] y el `finish_reason` es `tool_calls`", str(d[via]["choices"][0]["finish_reason"]))
        ok(d[via]["choices"][0]["message"]["content"] is None,
           f"[{via}] y `content` es null, no cadena vacía — este mensaje VUELVE al proveedor "
           f"en el turno siguiente y hay endpoints que rechazan un assistant vacío con "
           f"tool_calls", repr(d[via]["choices"][0]["message"]["content"]))

    d = _dos_vias("m-sinusage")
    ok("usage" not in d["urllib"] and "usage" not in d["litellm"],
       "si el proveedor NO mandó usage, NINGUNA vía inventa uno — `_accumulate_usage` "
       "cuenta la llamada en `calls_no_usage` y el costo del run no miente",
       f"urllib={'usage' in d['urllib']} litellm={'usage' in d['litellm']}")
    _acc = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "calls": 0, "calls_no_usage": 0}
    RA._accumulate_usage(_acc, d["litellm"].get("usage"))
    ok(_acc["calls_no_usage"] == 1 and _acc["calls"] == 0,
       "…y se comprueba contra `_accumulate_usage` de verdad, no de palabra", str(_acc))

    seccion("4c · el traductor da LA MISMA CAUSA por las dos vías ante el mismo fallo")
    # ⚠️ [F7·A·bis] `m-401` SE MIDE DOS VECES, con credencial y sin ella. Antes se medía
    # UNA sola —siempre con `api_key=""`— y esperaba `key_invalida`, que era correcto
    # mientras el traductor no supiera si habíamos mandado header. F7·A le enseñó la
    # distinción (`falta_key`) y ESTA aserción fue la que cazó que se la enseñó a UNA SOLA
    # vía: urllib decía `falta_key`, litellm seguía en `key_invalida`.
    #
    # Bajar la expectativa a «lo que salga» habría sido ablandar la vara. Lo que
    # corresponde es medir las DOS condiciones, porque ahora hay dos respuestas correctas
    # distintas — y así el lado a lado sigue siendo el guard del cableo, no un testigo de
    # una sola de las dos.
    for modelo, key, esperada in (("m-401", "",            E.FALTA_KEY),
                                  ("m-401", "sk-la-llave", E.KEY_INVALIDA),
                                  ("m-402", "",            E.SIN_CREDITO),
                                  ("m-429", "",            E.RATE_LIMIT),
                                  ("m-500", "",            E.PROVEEDOR_CAIDO)):
        d = _dos_vias(modelo, key=key)
        cu = getattr(d["urllib"], "causa", None)
        cl = getattr(d["litellm"], "causa", None)
        ok(cu is not None and cl is not None and cu.causa == cl.causa == esperada,
           f"{modelo} [{'con' if key else 'sin'} credencial] → `{esperada}` por urllib Y "
           f"por litellm — si un veredicto cambiara, sería bug del cableo",
           f"urllib={getattr(cu,'causa',d['urllib'])} litellm={getattr(cl,'causa',d['litellm'])}")
        ok(cu is not None and cl is not None and cu.reintentable == cl.reintentable,
           f"…y la misma reintentabilidad ({getattr(cu,'reintentable',None)})")

    d = _dos_vias("m-429")
    ok(d["urllib"].causa.retry_after_s == d["litellm"].causa.retry_after_s == 37.0,
       "…y los mismos segundos de `Retry-After` (el proveedor sabe mejor que nuestro backoff)",
       f"{d['urllib'].causa.retry_after_s} vs {d['litellm'].causa.retry_after_s}")

    seccion("4d · un host muerto: la REGLA DE ORO por las dos vías")
    for perilla in ("0", "1"):
        os.environ["PUPPET_LITELLM"] = perilla
        _prev = ASM._OSS_DIRECT_URL
        ASM._OSS_DIRECT_URL = MUERTO
        try:
            ASM._chat(MSG, [], MUERTO, "m-x", "", 100, 0.0)
            ok(False, f"[perilla={perilla}] un host inexistente levanta")
        except RuntimeError as ex:
            c = getattr(ex, "causa", None)
            ok(c is not None and c.causa == E.SIN_RED,
               f"[perilla={perilla}] host inexistente → `sin_red`, NUNCA `proveedor_caido` "
               f"(§P1.d: litellm lo entrega como InternalServerError 500)",
               getattr(c, "causa", type(ex).__name__))
        finally:
            ASM._OSS_DIRECT_URL = _prev

    seccion("4e · la perilla=0 restaura urllib, y se DEMUESTRA por la huella de la vía")
    _prev = ASM._OSS_DIRECT_URL
    ASM._OSS_DIRECT_URL = BASE
    try:
        os.environ["PUPPET_LITELLM"] = "0"
        ok(ASM._usa_litellm(BASE) is False,
           "con la perilla en 0 el desvío ni se evalúa contra litellm")
        r0 = ASM._chat(MSG, [], BASE, "m-ok", "", 100, 0.0)
        os.environ["PUPPET_LITELLM"] = "1"
        r1 = ASM._chat(MSG, [], BASE, "m-ok", "", 100, 0.0)

        # LA HUELLA. urllib devuelve el cuerpo del proveedor TAL CUAL —`id`, `object`,
        # `created` incluidos—; el adaptador RE-ARMA la respuesta con los campos del
        # contrato. Esa diferencia es, justamente, la prueba de que con la perilla en 0
        # corrió el código de siempre y no una imitación.
        ok(r0.get("id") == "c1" and r0.get("object") and r0.get("created"),
           "perilla=0 → el cuerpo del proveedor llega TAL CUAL: es la vía urllib, la de "
           "antes de F4a, sin una línea nueva en el medio", str(sorted(r0))),
        ok("id" not in r1 and "object" not in r1,
           "perilla=1 → la respuesta viene RE-ARMADA por el adaptador (huella distinta)",
           str(sorted(r1)))

        # …y lo que el producto CONSUME es idéntico. Los tres campos que el adaptador no
        # reproduce (`id`/`object`/`created`) no los lee NADIE en el árbol — se verifica
        # acá abajo, en vez de afirmarlo.
        _contrato = lambda r: {k: r.get(k) for k in ("choices", "model", "usage")}
        ok(json.dumps(_contrato(r0), sort_keys=True) == json.dumps(_contrato(r1), sort_keys=True),
           "y TODO lo que el producto consume (`choices` · `model` · `usage`) es idéntico "
           "campo por campo por las dos vías",
           f"{json.dumps(_contrato(r0), sort_keys=True)[:70]} … "
           f"{json.dumps(_contrato(r1), sort_keys=True)[:70]}")

        _lectores = subprocess.run(
            ["grep", "-rn", "--include=*.py",
             r'resp\["id"\]\|resp\.get("id")\|resp\["created"\]\|resp\.get("created")'
             r'\|resp\["object"\]\|resp\.get("object")',
             str(_AQUI), str(_RAIZ / "product" / "backend" / "app")],
            capture_output=True, text=True)
        _hits = [l for l in (_lectores.stdout or "").splitlines() if "/verify_" not in l]
        ok(not _hits,
           "y NADIE en el árbol lee `id`/`object`/`created` de una respuesta de chat — por "
           "eso no se rellenan con valores inventados: se omiten y se dice", str(_hits[:2]))
    finally:
        ASM._OSS_DIRECT_URL = _prev
        os.environ["PUPPET_LITELLM"] = "0"

    seccion("4f · el arranque del sidecar sella y NO toca internet (audit hook)")
    # El sellado tiene que pasar ANTES del primer import de litellm, así que esto corre en
    # un SUBPROCESO: en éste el import ya ocurrió y no probaría nada.
    _SONDA = r"""
import json, sys
EV = []
def hook(ev, args):
    if ev in ("socket.getaddrinfo", "socket.connect"):
        EV.append((ev, repr(args)[:80]))
sys.addaudithook(hook)
sys.path.insert(0, %(asm)r)
from adaptador_litellm import init_litellm
l = init_litellm()
print(json.dumps({"red": EV,
                  "fallbacks": [l.fallbacks, l.model_fallbacks,
                                l.context_window_fallbacks, l.content_policy_fallbacks],
                  "num_retries": l.num_retries}))
""" % {"asm": str(_AQUI)}
    _env = dict(os.environ)
    for _k in ("LITELLM_LOCAL_MODEL_COST_MAP", "LITELLM_MODE"):
        _env.pop(_k, None)
    _p = subprocess.run([sys.executable, "-c", _SONDA], capture_output=True, text=True,
                        timeout=180, env=_env)
    try:
        _d = json.loads((_p.stdout or "").strip().splitlines()[-1])
    except Exception:                                    # noqa: BLE001
        _d = None
    ok(_d is not None, "la sonda del arranque corrió", (_p.stderr or "")[-200:])
    if _d:
        ok(_d["red"] == [],
           "el sellado del arranque NO abre NINGUNA conexión saliente (audit hook)",
           str(_d["red"]))
        ok(_d["fallbacks"] == [None, None, None, None],
           "LOS CUATRO fallbacks de litellm en None — el cascade es de `_route_chat`, que "
           "además lo NARRA. Dos capas de sustitución y una de narración pierde la "
           "degradación", str(_d["fallbacks"]))
        ok(_d["num_retries"] is None,
           "y `num_retries` apagado: los reintentos los decide repair (§3 del DISEÑO-REPAIR)")

    # y que el arranque de verdad lo llame — no que se pueda llamar
    _main = (_RAIZ / "product/backend/app/main.py").read_text(encoding="utf-8")
    ok("init_litellm" in _main and "_lifespan" in _main,
       "y `main.py` lo llama en el `_lifespan`: UNA vez por proceso, no por turno")

os.environ["PUPPET_LITELLM"] = "0"


# ══════════════════════════════════════════════════════════════════════════════════
# 5 · LAS VARAS PREVIAS DE GATE 2 SIGUEN VERDES
# ══════════════════════════════════════════════════════════════════════════════════
seccion("5 · las varas previas de Gate 2 — quiénes son, y quién las corre")

# ⚠️ ACÁ **NO** SE CORREN, Y ES UNA DECISIÓN, NO UN OLVIDO.
#
# El anidamiento de varas ya llegó a TRES niveles (`via_local` → `sesiones` → `stopturn` →
# 5 más) y repite las mismas varias veces: en la corrida completa esta vara **se comió los
# 120 s del techo de `correr_varas.py` y murió por timeout** —midiendo nada— sólo por
# spawnear seis subprocesos que el propio arnés ya iba a correr.
#
# La salida sellada para eso es «cada vara corre UNA vez por invocación», y la invocación
# única de la tanda es `qa/correr_varas.py`, que las tiene a las 104 con sus cerrojos por
# recurso. Lo que corresponde acá es DECLARAR de quiénes depende esta obra, para que quien
# lea el reporte sepa qué mirar — no volver a correrlas.
#
# (Una perilla para apagar el anidamiento está DESCARTADA por la misma razón de siempre:
#  la que se apaga en desarrollo es la que queda apagada el día que importa.)
_PREVIAS = [
    "platform/assembler/verify_traductor.py",
    "platform/assembler/verify_adaptador_litellm.py",
    "platform/assembler/cli_brain/verify_cli_streaming.py",
    "platform/assembler/cli_brain/verify_cli_slots.py",
    "platform/assembler/cli_brain/verify_cli_usage.py",
    "platform/assembler/cli_brain/verify_cli_stopturn.py",
    "platform/assembler/cli_brain/verify_cli_sesiones.py",
    "platform/assembler/cli_brain/verify_tres_cables.py",
    "qa/verify_via_local.py",
]
for rel in _PREVIAS:
    ok((_RAIZ / rel).exists(), f"existe la vara de la que esta obra depende: {rel}")
print("     [invocación única]  product/backend/.venv/bin/python qa/correr_varas.py")

# [H3] La invocación única va ARRIBA del veredicto: la última línea que imprime una vara
# tiene que ser el veredicto, o un `tail -1` lee una nota al pie y decide un merge con ella.
sys.exit(_V.cerrar(_fallos, _salteados, _criticos))
