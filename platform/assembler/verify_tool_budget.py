#!/usr/bin/env python3
"""Vara única Gate 4 · Fase 5 · obra 5.1: EL CINTURÓN ENTERO NO VA AL MODELO.

    python3 platform/assembler/verify_tool_budget.py
    python3 platform/assembler/verify_tool_budget.py --caer     # la prueba de caída

── QUÉ CIERRA ──────────────────────────────────────────────────────────────────────
El 413 medido el 2026-08-08 (ESTADO-CERT §12.2): 5 piezas equipadas = **49 tools**, y Groq
rechaza el pedido entero con `x-ratelimit-remaining-requests: 1000` — o sea que la cuota
estaba intacta y lo que no entraba era el pedido. El mismo cinturón por OpenRouter pasaba.
El censo lo dejó escrito y sin una línea de código.

Y arrastraba un segundo defecto, con nombre desde entonces:
`el-413-se-anuncia-como-rate-limited`. La causa sellada siempre estuvo bien; el rótulo de
primer nivel mentía, y a quien lee «rate-limited» le decís que ESPERE por un problema que
esperar no arregla.

── LO QUE ESTA VARA MIDE, Y CÓMO ───────────────────────────────────────────────────
A · el presupuesto PURO (cero red, cero proceso): orden, piso, techo ausente, repliegue.
B · la CAUSA: 413 → `contexto_excedido` + `motivo`, y el rótulo que dejó de mentir.
C · un 413 POR UN SOCKET DE VERDAD: un proveedor falso que rechaza por tamaño, atravesado
    por `assembler._chat` con urllib real. Sin esto la cadena estaría medida sólo en
    memoria, y el bug original vivía justamente en el borde de la red.
D · EL LOOP REAL: `assemble_and_run` con el belt `calc` REAL por stdio, el gate real y el
    registry real. El único stub es el LLM — un modelo no es determinista y un test con un
    modelo adentro mide la suerte del día, no el motor.
E · el PISO del método: la tool que un paso NOMBRA viaja aunque el techo la deje afuera.
F · el REPLIEGUE: el proveedor dice 413 y **la obra igual sale**.
G · la CARA: la misma causa, dos motivos, dos copys, y la culpa donde corresponde.
H · la REGRESIÓN: sin techo declarado, el array que llega al modelo es el de siempre.

── POR QUÉ UN PROVEEDOR FALSO Y NO GROQ ────────────────────────────────────────────
No hay ninguna llave de proveedor en esta máquina (`infra/.env` no existe, el entorno no
trae ninguna), así que la pata viva contra Groq no se puede correr desde acá y queda
declarada en el acta. Pero además el falso es MEJOR instrumento para esto: el
discriminante es «el filtro impide que el pedido pase el techo», y contra un techo que
elijo yo eso se mide exacto y se repite igual mañana, sin depender de la cuota de nadie ni
del humor del proveedor. Lo que el falso NO prueba —que el número declarado para Groq sea
el correcto— tampoco lo probaría una corrida viva: entre 2 y 49 tools nadie midió dónde
está la línea, y por eso el número está declarado como apuesta y existe el repliegue.

── LA PRUEBA DE CAÍDA ──────────────────────────────────────────────────────────────
`--caer` apaga el filtro por la perilla (`ALEPH_TOOL_BUDGET_BYTES=0`) y EXIGE que las
aserciones del recorte se pongan en rojo. Una vara que no puede caer no está midiendo:
está describiendo.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from email.message import Message
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

import errores_modelo as E        # noqa: E402
import models as M                # noqa: E402
import tool_budget as TB          # noqa: E402
import recipe_assembler as ra     # noqa: E402
import method_harness as MH       # noqa: E402

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
    """Aserción que la prueba de caída DA VUELTA. Con `--caer` se exige lo contrario:
    si el filtro apagado la deja verde, la aserción no estaba midiendo el filtro."""
    if CAER:
        check(f"[caída] NO se cumple sin filtro · {name}", not cond, detail)
    else:
        check(name, cond, detail)


# ══ A · EL PRESUPUESTO, PURO ═══════════════════════════════════════════════════════

def _T(n: str, desc: str = "d" * 40) -> dict:
    return {"type": "function",
            "function": {"name": n, "description": desc,
                         "parameters": {"type": "object",
                                        "properties": {"a": {"type": "string"}}}}}


def bloque_A() -> None:
    tools = [_T(f"t{i}") for i in range(12)]
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]

    r = TB.recortar(tools, msgs, TB.SIN_TECHO)
    check("A1 sin techo declarado NO se recorta nada (`None` es «no sé», jamás «infinito»)",
          len(r.enviadas) == 12 and not r.demoradas)

    p = TB.Presupuesto(900, "vara")
    r = TB.recortar(tools, msgs, p)
    check("A2 con techo, lo enviado ENTRA en el techo",
          r.bytes_enviados <= 900 and len(r.enviadas) < 12,
          f"{r.bytes_enviados}B ≤ 900B con {len(r.enviadas)}/12")
    check("A3 lo que queda afuera sale CON NOMBRE Y MOTIVO (no hay recorte mudo)",
          bool(r.demoradas) and all(d.get("name") and d.get("motivo") == TB.POR_PRESUPUESTO
                                    for d in r.demoradas))
    check("A4 nada se duplica ni se inventa: enviadas + demoradas = el total",
          len(r.enviadas) + len(r.demoradas) == 12)

    r = TB.recortar(tools, msgs, p, piso={"t11"})
    check("A5 EL PISO VIAJA aunque sea la última del orden de registro",
          "t11" in [TB.nombre_de(t) for t in r.enviadas])

    # El piso solo YA no entra (una tool enorme), pero los mensajes sí: acá el recorte
    # tiene sentido y aun así el piso viaja, porque romper el método es peor que un 413.
    gordo = _T("t_gordo", "d" * 1500)
    r = TB.recortar(tools + [gordo], msgs, TB.Presupuesto(600, "vara"), piso={"t_gordo"})
    check("A6 …y viaja INCLUSO si el piso solo ya excede el techo, avisando",
          [TB.nombre_de(t) for t in r.enviadas] == ["t_gordo"] and r.piso_excede,
          f"{[TB.nombre_de(t) for t in r.enviadas]} piso_excede={r.piso_excede}")

    r = TB.recortar(tools, msgs, p, usadas={"t10"}, del_cliente={"t0", "t1"})
    envs = [TB.nombre_de(t) for t in r.enviadas]
    check("A7 la tool que YA TRABAJÓ no se demora antes que una que nunca se usó",
          "t10" in envs)
    check("A8 las del CLIENTE se demoran primero (el belt equipa; el cliente decora)",
          "t0" not in envs and "t1" not in envs)

    check("A9 el orden de registro se restituye (payload estable entre turnos)",
          envs == sorted(envs, key=lambda n: int(n[1:])))

    r2 = TB.recortar(tools, msgs, p)
    check("A10 es PURO: mismo input → mismo recorte",
          [TB.nombre_de(t) for t in r2.enviadas] == [TB.nombre_de(t) for t in
                                                     TB.recortar(tools, msgs, p).enviadas])

    rp = TB.repliegue(tools, piso={"t11"})
    check("A11 el repliegue suelta la mitad y CONSERVA el piso",
          len(rp.enviadas) < 12 and "t11" in [TB.nombre_de(t) for t in rp.enviadas]
          and all(d["motivo"] == TB.POR_REPLIEGUE for d in rp.demoradas))

    # LO QUE DESTAPÓ LA VARA: con un techo por debajo del historial, recortar TODAS las
    # tools no evita el 413 (el pedido igual no entra) y deja al agente sin manos.
    gordos = [{"role": "user", "content": "x" * 5000}]
    r = TB.recortar(tools, gordos, TB.Presupuesto(900, "vara"))
    check("A13 si los MENSAJES solos ya no entran, las tools NO son el problema: no se recorta",
          len(r.enviadas) == 12 and not r.demoradas and r.mensajes_exceden)
    check("A14 …y el aviso lo dice con nombre, en vez de un recorte inútil y mudo",
          r.como_dict().get("aviso") == TB.MENSAJES_EXCEDEN)

    g = M.limite_de("https://api.groq.com/openai/v1")
    o = M.limite_de("https://openrouter.ai/api/v1")
    check("A12 el techo de Groq sale de una MEDICIÓN VIVA, no de una apuesta",
          g["max_payload_bytes"] == 40_960 and g["fuente"].startswith("medido:"),
          f"{g['max_payload_bytes']}B fuente={g['fuente']}")
    check("A12b …y un host sin medir NO tiene techo (`None` es «no sé»)",
          o["max_payload_bytes"] is None and o["max_tools"] is None)

    # ── EL SEGUNDO TECHO, medido en vivo el 2026-08-09 ────────────────────────────
    # Groq contesta `400 invalid_request_error` — *"'tools' : maximum number of items is
    # 128"* — con 400 tools. Es de OTRA naturaleza que el 413: no lo salva ningún repliegue
    # por bytes, porque 129 schemas minúsculos siguen siendo 129 ítems.
    check("A15 el techo de CANTIDAD de Groq está declarado (128, medido)",
          g["max_tools"] == 128)
    muchas = [_T(f"m{i}", "d") for i in range(140)]           # 140 diminutas: pesan poco
    p_items = TB.Presupuesto(max_payload_bytes=None, max_tools=128, fuente="vara")
    r = TB.recortar(muchas, msgs, p_items)
    check("A16 con techo SÓLO de cantidad, se recorta por ítems aunque quepan en bytes",
          len(r.enviadas) == 128 and len(r.demoradas) == 12,
          f"{len(r.enviadas)} enviadas / {len(r.demoradas)} demoradas")
    r = TB.recortar(muchas, msgs, p_items, piso={"m139"})
    check("A17 …y el piso del método sobrevive también a ESE techo",
          "m139" in [TB.nombre_de(x) for x in r.enviadas] and len(r.enviadas) == 128)
    r = TB.recortar(muchas, msgs, TB.Presupuesto(2_000, 128, "vara"))
    check("A18 los dos techos se aplican juntos: primero ítems, después bytes",
          len(r.enviadas) < 128 and r.bytes_enviados <= 2_000,
          f"{len(r.enviadas)} enviadas · {r.bytes_enviados}B")


# ══ B · LA CAUSA ═══════════════════════════════════════════════════════════════════

def _http413(cuerpo: str) -> urllib.error.HTTPError:
    h = Message()
    h["x-ratelimit-remaining-requests"] = "1000"
    return urllib.error.HTTPError("https://api.groq.com/openai/v1/chat/completions",
                                  413, "Payload Too Large", h, io.BytesIO(cuerpo.encode()))


#: El cuerpo REAL que devuelve Groq — trae `rate_limit_exceeded` adentro, que es lo que
#: hacía que el rótulo mintiera.
CUERPO_GROQ = ('{"error":{"message":"Request too large","type":"tokens",'
               '"code":"rate_limit_exceeded"}}')


def bloque_B() -> None:
    c = E.desde_urllib(_http413(CUERPO_GROQ), url="https://api.groq.com/v1", con_tools=True)
    check("B1 un 413 CON tools → `contexto_excedido` (era el 4xx genérico `error_upstream`)",
          c.causa == E.CONTEXTO_EXCEDIDO, c.causa)
    check("B2 …con `motivo: demasiadas_tools` — la culpa es de la casa, no del usuario",
          c.evidencia.get("motivo") == E.MOTIVO_DEMASIADAS_TOOLS)
    c2 = E.desde_urllib(_http413("{}"), url="https://api.groq.com/v1", con_tools=False)
    check("B3 un 413 SIN tools es OTRO motivo: ahí sí el texto es largo",
          c2.causa == E.CONTEXTO_EXCEDIDO
          and c2.evidencia.get("motivo") == E.MOTIVO_PEDIDO_GRANDE)
    check("B4 la causa está en el vocabulario CERRADO (cero causa nueva)",
          E.CONTEXTO_EXCEDIDO in E.CAUSAS)
    check("B5 no escala al fallback: otro modelo no arregla un pedido que no entra",
          E.escala(E.CONTEXTO_EXCEDIDO) is False)
    check("B6 no es reintentable tal cual (repetirlo idéntico vuelve a no entrar)",
          c.reintentable is False)

    check("B7 el rótulo DEJÓ DE MENTIR con el cuerpo real de Groq",
          ra._safe_err("HTTP 413: " + CUERPO_GROQ) == "payload-too-large",
          ra._safe_err("HTTP 413: " + CUERPO_GROQ))
    check("B8 …y el 429 de verdad sigue diciendo lo suyo (nada se rompió al reordenar)",
          ra._safe_err("HTTP 429: rate limit reached") == "rate-limited")
    check("B9 el 401 y el timeout siguen intactos",
          ra._safe_err("HTTP 401: nope") == "auth-rejected"
          and ra._safe_err("read timed out") == "timeout")

    check("B10 el discriminante del repliegue es la CAUSA TIPADA, no un substring",
          ra._es_413_por_tools(E.ErrorDeModelo(c, "x")) is True
          and ra._es_413_por_tools(E.ErrorDeModelo(c2, "x")) is False
          and ra._es_413_por_tools(RuntimeError("HTTP 413 too large")) is False)


# ══ C · UN 413 POR UN SOCKET DE VERDAD ═════════════════════════════════════════════

class _Proveedor(BaseHTTPRequestHandler):
    """Proveedor falso: rechaza por TAMAÑO con un 413 real, como Groq."""

    techo = 1_000

    def do_POST(self):                                        # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(n)
        if n > self.techo:
            data = CUERPO_GROQ.encode()
            self.send_response(413)
            self.send_header("Content-Type", "application/json")
            self.send_header("x-ratelimit-remaining-requests", "1000")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        pedido = json.loads(cuerpo or b"{}")
        data = json.dumps({
            "model": pedido.get("model") or "falso",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_a):                               # silencio
        return


def bloque_C() -> None:
    srv = HTTPServer(("127.0.0.1", 0), _Proveedor)            # puerto 0: jamás uno fijo
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    msgs = [{"role": "user", "content": "hola"}]
    muchas = [_T(f"t{i}", "d" * 200) for i in range(20)]
    try:
        # chico → pasa
        r = ra._asm._chat(msgs, [], base, "m", "k", 64, 0.0)
        check("C1 el proveedor falso contesta 200 a un pedido que entra",
              r["choices"][0]["message"]["content"] == "ok")

        # grande CON tools → 413 real por el socket, tipado con el motivo correcto
        try:
            ra._asm._chat(msgs, muchas, base, "m", "k", 64, 0.0)
            check("C2 un pedido que no entra levanta", False, "no levantó")
        except Exception as exc:                              # noqa: BLE001
            c = E.causa_de_excepcion(exc)
            check("C2 un 413 REAL por el socket sale `contexto_excedido`",
                  c is not None and c.causa == E.CONTEXTO_EXCEDIDO,
                  getattr(c, "causa", type(exc).__name__))
            check("C3 …y `assembler._chat` supo que llevaba tools (motivo correcto)",
                  c is not None and c.evidencia.get("motivo") == E.MOTIVO_DEMASIADAS_TOOLS)
            check("C4 …con el status en la evidencia, no adivinado del texto",
                  c is not None and c.evidencia.get("http_status") == 413)
            check("C5 …y `_safe_err` sobre ESE error ya no dice rate-limited",
                  ra._safe_err(str(exc)) == "payload-too-large", ra._safe_err(str(exc)))
    finally:
        srv.shutdown()


# ══ D-F-H · EL LOOP REAL, con el belt calc por stdio ═══════════════════════════════

def _recipe(max_turns: int = 3) -> dict:
    return {
        "schema_version": "v1",
        "meta": {"name": "F5 tool budget", "nicho": "test"},
        "model": {"primary": "stub", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 128, "max_turns": max_turns},
        # `None` = TODA la superficie del server (6 tools: add/sub/mul/div/pow/mod).
        "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": None}},
        "framing": {"inline": "Sos un test."},
        "rag": {"enabled": False}, "keys": {}, "gates": {},
    }


def _correr(capt: dict, *, presupuesto=None, method_harness=None, cae_413_con=None):
    """Corre el loop real con el LLM stubbeado. `cae_413_con`: si el stub recibe >= N
    tools, levanta el mismo error tipado que levantaría el proveedor."""
    estado = {"n": 0}

    def fake_chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kw):
        estado["n"] += 1
        capt.setdefault("tools_por_llamada", []).append(
            [TB.nombre_de(t) for t in (tools or [])])
        capt.setdefault("messages", list(messages))
        capt.setdefault("tools_crudas", list(tools or []))
        if cae_413_con is not None and len(tools or []) >= cae_413_con:
            raise E.ErrorDeModelo(
                E.desde_urllib(_http413(CUERPO_GROQ), url=base_url, con_tools=True),
                "HTTP 413: " + CUERPO_GROQ)
        return {"choices": [{"finish_reason": "stop",
                             "message": {"role": "assistant", "content": "listo"}}]}

    prev = os.environ.get("ALEPH_TOOL_BUDGET_BYTES")
    # LA PRUEBA DE CAÍDA apaga el filtro DE VERDAD: con la perilla en 0 el camino es el de
    # antes de esta obra, y las aserciones marcadas `caediza` tienen que ponerse en rojo.
    # (Primera versión: `_correr` forzaba igual el techo pedido y la caída medía el filtro
    # prendido — o sea, no medía nada. La cazó la propia corrida con `--caer`.)
    if CAER:
        presupuesto = 0
    if presupuesto is not None:
        os.environ["ALEPH_TOOL_BUDGET_BYTES"] = str(presupuesto)
    orig = ra._asm._chat
    ra._asm._chat = fake_chat
    try:
        return ra.assemble_and_run(_recipe(), "hacé algo", repo_root=REPO_ROOT,
                                   method_harness=method_harness)
    finally:
        ra._asm._chat = orig
        if prev is None:
            os.environ.pop("ALEPH_TOOL_BUDGET_BYTES", None)
        else:
            os.environ["ALEPH_TOOL_BUDGET_BYTES"] = prev


def bloque_D() -> None:
    # ── H · la REGRESIÓN primero: sin techo, todo igual que antes de la obra ──────
    capt = {}
    out = _correr(capt, presupuesto=0)          # 0 = perilla apagada explícita
    todas = capt["tools_por_llamada"][0]
    check("H1 SIN techo el modelo recibe el cinturón COMPLETO (regresión intacta)",
          len(todas) == 6, f"{len(todas)} tools: {todas}")
    check("H2 …y el record no inventa recortes",
          out["tool_budget"]["recortes"] == []
          and out["tools_dropped"] == [])
    check("H3 …y el run sale bien",
          out["ok"] is True and out.get("error") is None)

    # ── D · con techo, el array que CRUZA es más chico ───────────────────────────
    # El techo se calcula DEL PEDIDO REAL de la corrida de arriba (mensajes + ~2 tools),
    # no a ojo: un número inventado puede quedar por debajo del historial y entonces la
    # aserción mediría otra cosa (fue exactamente lo que pasó en la primera corrida).
    base = TB.medir(capt["messages"], [], reservado=M.RESERVA_DE_CUERPO_BYTES)
    una = TB.medir(capt["messages"], capt["tools_crudas"][:1],
                   reservado=M.RESERVA_DE_CUERPO_BYTES) - base
    capt2 = {}
    out2 = _correr(capt2, presupuesto=base + int(una * 2.5))
    enviadas = capt2["tools_por_llamada"][0]
    caediza("D1 con techo, al modelo le llegan MENOS tools — pero NUNCA cero "
            "(recortar hasta dejarlo sin manos no es recortar: es romperlo)",
            0 < len(enviadas) < 6, f"{len(enviadas)}/6 → {enviadas}")
    caediza("D2 el recorte queda en el record con turno, tamaños y nombres",
            bool(out2["tool_budget"]["recortes"])
            and out2["tool_budget"]["recortes"][0]["turno"] == 1)
    caediza("D3 lo demorado entra a `tools_dropped` con motivo (no hay recorte mudo)",
            any(d.get("motivo") == TB.POR_PRESUPUESTO
                for d in out2["tools_dropped"]))
    check("D4 el run igual SALE (recortar no rompe el turno)",
          out2["ok"] is True, str(out2.get("error")))
    check("D5 el presupuesto y su fuente quedan declarados en el record",
          out2["tool_budget"]["presupuesto"]["fuente"].startswith("perilla")
          and out2["tool_budget"]["tools_totales"] == 6)


def bloque_E() -> None:
    """EL PISO: la tool que el método NOMBRA viaja aunque el techo la deje afuera."""
    spec = {"steps": [{"id": "s1", "titulo": "elevar", "executor": "calc#pow"}]}
    h = MH.MethodHarness(spec, method_id="m-vara", lang="es")
    check("E1 el arnés sabe decir qué tools NOMBRAN sus pasos",
          h.herramientas_declaradas() == {"pow"}, str(h.herramientas_declaradas()))

    # El techo se mide sobre un run CON EL MÉTODO PUESTO: el arnés inyecta su bloque de
    # estado en `messages[0]`, así que un baseline sin método daría un techo por debajo del
    # historial real y el guard de A13 se comería el recorte (pasó, y la vara lo cazó).
    # Dos arneses idénticos porque uno ya corrido tiene estado.
    capt0 = {}
    _correr(capt0, presupuesto=0,
            method_harness=MH.MethodHarness(spec, method_id="m-base", lang="es"))
    base = TB.medir(capt0["messages"], [], reservado=M.RESERVA_DE_CUERPO_BYTES)
    una = TB.medir(capt0["messages"], capt0["tools_crudas"][:1],
                   reservado=M.RESERVA_DE_CUERPO_BYTES) - base
    capt = {}
    out = _correr(capt, presupuesto=base + una, method_harness=h)
    enviadas = capt["tools_por_llamada"][0]
    caediza("E2 con lugar para UNA sola tool, la que viaja es la que DECLARÓ el método",
            enviadas == ["pow"], f"{enviadas}")
    check("E3 el piso queda declarado en el record",
          out["tool_budget"]["piso_metodo"] == ["pow"])


def bloque_F() -> None:
    """EL REPLIEGUE: el proveedor dice 413 y la obra SALE igual."""
    capt = {}
    # Sin techo (el caso real de un proveedor no medido) y el proveedor rechaza con 6.
    out = _correr(capt, presupuesto=0, cae_413_con=6)
    llamadas = capt["tools_por_llamada"]
    check("F1 el primer intento va con el cinturón entero y el proveedor lo rechaza",
          len(llamadas) >= 2 and len(llamadas[0]) == 6, str([len(x) for x in llamadas]))
    check("F2 se reintenta UNA vez, con MENOS tools",
          len(llamadas) >= 2 and len(llamadas[1]) < len(llamadas[0]),
          str([len(x) for x in llamadas]))
    check("F3 **la obra SALE** — el 413 dejó de costar el turno",
          out["ok"] is True and out.get("error") is None, str(out.get("error")))
    check("F4 el repliegue queda registrado con de→a y los nombres soltados",
          bool(out["tool_budget"].get("repliegues"))
          and out["tool_budget"]["repliegues"][0]["de"] == 6)
    check("F5 …y lo soltado también entra a `tools_dropped`",
          any(d.get("motivo") == TB.POR_REPLIEGUE
              for d in out["tools_dropped"]))

    # Y el borde honesto: si ni replegando entra, el run cae con la causa correcta.
    capt2 = {}
    out2 = _correr(capt2, presupuesto=0, cae_413_con=1)
    check("F6 si ni con menos entra, el run cae con `contexto_excedido` (jamás mudo)",
          out2["ok"] is False
          and (out2.get("causa") or {}).get("causa") == E.CONTEXTO_EXCEDIDO,
          str((out2.get("causa") or {}).get("causa")))
    check("F7 …y el rótulo de primer nivel dice payload-too-large, no rate-limited",
          "rate-limited" not in json.dumps(out2["model_route"]),
          json.dumps(out2["model_route"])[:160])


# ══ G · LA CARA ════════════════════════════════════════════════════════════════════

_JS = r"""
import('%s').then(S => {
  const tools = S.caraDeCausa({causa:'contexto_excedido', detalle:'x',
                               evidencia:{motivo:'demasiadas_tools'}});
  const texto = S.caraDeCausa({causa:'contexto_excedido', detalle:'x',
                               evidencia:{motivo:'pedido_demasiado_grande'}});
  const pelada= S.caraDeCausa({causa:'contexto_excedido', detalle:'x'});
  const desc  = S.caraDeCausa({causa:'no_existe_esta_causa', detalle:'x'});
  console.log(JSON.stringify({
    tools_titulo: tools.titulo, tools_culpa: tools.culpa, tools_camino: tools.camino.es,
    texto_titulo: texto.titulo, texto_culpa: texto.culpa, texto_camino: texto.camino.es,
    pelada_titulo: pelada.titulo, pelada_culpa: pelada.culpa,
    desconocida: desc.desconocida, sin_boton: !!tools.sinBoton,
  }));
}).catch(e => { console.error(e.message); process.exit(1); });
"""


def bloque_G() -> None:
    sem = REPO_ROOT / "product" / "app" / "design" / "cuarto" / "cuarto.semaforo.js"
    try:
        salida = subprocess.run(
            ["node", "--input-type=module", "-e", _JS % sem.as_uri()],
            capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT))
    except Exception as exc:                                   # noqa: BLE001
        check("G0 node disponible para medir la cara", False, str(exc))
        return
    if salida.returncode != 0:
        check("G0 la superficie carga", False, (salida.stderr or "")[:200])
        return
    d = json.loads(salida.stdout.strip().splitlines()[-1])
    check("G1 el 413 por tools NO le echa la culpa al usuario",
          d["tools_culpa"] == "aleph" and d["texto_culpa"] == "tuya",
          f"tools={d['tools_culpa']} texto={d['texto_culpa']}")
    check("G2 …y no le dice «acorta el pedido» (no hay nada suyo que acortar)",
          "Acorta" not in d["tools_camino"] and "Acorta" in d["texto_camino"])
    check("G3 el camino por tools nombra las DOS salidas reales que sí tiene",
          "pieza" in d["tools_camino"] and "modelo" in d["tools_camino"],
          d["tools_camino"])
    check("G4 sin motivo, el copy es EXACTAMENTE el de siempre (regresión de la cara)",
          d["pelada_titulo"] == d["texto_titulo"] and d["pelada_culpa"] == "tuya")
    check("G5 una causa desconocida SIGUE marcándose como tal (no la tapó el merge)",
          d["desconocida"] is True)
    check("G6 ninguna de las dos ofrece un botón imposible",
          d["sin_boton"] is True)


# ══ M · EL BORDE DE DIALECTO ═══════════════════════════════════════════════════════

def bloque_M() -> None:
    """El repliegue del BORDE, que es por donde va a entrar el próximo 413.

    Lo escribí y no lo medía nadie: el hueco lo encontró una relectura del diff, no la
    vara. Y es el camino que más importa de los dos — un stack heredado manda SUS ~40
    schemas en cada paso, así que el 413 de producción va a salir por acá y no por el
    cinturón de la casa.

    Sin red: se stubbea `_route_chat` del árbol que el borde usa. Lo que se afirma es la
    POLÍTICA, que es lo que distingue a este camino del otro: acá **no hay recorte
    preventivo** (un proxy que recorta en silencio miente) y **sí hay repliegue**, porque
    la alternativa no es «el paso con todas las tools», es «no hay paso».
    """
    sys.path.insert(0, str(REPO_ROOT / "product" / "backend"))
    try:
        from app.phase1 import workspace_brain as wb
    except Exception as exc:                                   # noqa: BLE001
        check("M0 el borde carga", False, str(exc)[:120])
        return
    a = wb._asm()

    check("M1 el borde tiene un techo por TAMAÑO además del de ítems "
          "(96 schemas ricos pesan mucho más que 96 pobres)",
          isinstance(wb.MAX_TOOLS_BYTES, int) and wb.MAX_TOOLS_BYTES > 0)
    # El peso NO se mete por la descripción: `sanitize_tools` ya la trunca a 2.000 (lo
    # midió esta misma aserción cuando la escribí al revés). El campo sin techo es
    # `parameters`, que se acepta tal cual — y es justo el que un harness con un schema
    # generado puede inflar sin querer. Ahí es donde el techo por tamaño gana su sueldo.
    _params = {"type": "object", "properties": {
        f"campo_{j}": {"type": "string", "description": "x" * 200} for j in range(30)}}
    gordas = [{"type": "function", "function": {
        "name": f"t{i}", "description": "d", "parameters": _params}} for i in range(96)]
    try:
        wb.sanitize_tools(gordas)
        check("M2 …y RECHAZA tipado cuando se pasa (no recorta: es una barrera de borde)",
              False, "no rechazó")
    except wb.BrainError as e:
        check("M2 …y RECHAZA tipado cuando se pasa (no recorta: es una barrera de borde)",
              e.error == "tools_too_large", e.error)

    recipe = {"schema_version": "v1", "meta": {"name": "borde", "nicho": "test"},
              "model": {"primary": "stub", "base_url": "http://127.0.0.1:0/v1",
                        "temperature": 0, "max_tokens": 64},
              "belt": {}, "framing": {"inline": ""}, "rag": {"enabled": False},
              "keys": {}, "gates": {}}
    tools = [_T(f"h{i}", "d" * 120) for i in range(40)]
    msgs = [{"role": "user", "content": "hola"}]

    vistas: list = []
    orig = a._route_chat

    def ruta(messages, _tools, **kw):
        vistas.append(len(_tools or []))
        if len(vistas) == 1:                                   # el proveedor dice 413
            raise E.ErrorDeModelo(
                E.desde_urllib(_http413(CUERPO_GROQ), url=kw.get("base_url"),
                               con_tools=True), "HTTP 413")
        return ({"choices": [{"finish_reason": "stop",
                              "message": {"role": "assistant", "content": "ok"}}]}, "stub")

    a._route_chat = ruta
    try:
        out = wb.complete(recipe, msgs, tools)
    except Exception as exc:                                   # noqa: BLE001
        out = {"_error": f"{type(exc).__name__}: {exc}"[:160]}
    finally:
        a._route_chat = orig

    check("M3 el borde NO recorta preventivamente: el primer intento lleva TODO "
          "(LEY 0 — este borde es un proxy del stack, no su editor)",
          vistas and vistas[0] == 40, str(vistas))
    check("M4 ante el 413 SÍ repliega, y con menos tools",
          len(vistas) == 2 and vistas[1] < vistas[0], str(vistas))
    check("M5 **el paso del stack SALE** en vez de morir con el 413",
          out.get("content") == "ok", str(out.get("_error") or out.get("content"))[:120])
    check("M6 …y el repliegue se DICE (si no, el stack vería menos tools sin saber por qué)",
          isinstance(out.get("repliegue"), dict)
          and out["repliegue"]["de"] == 40 and out["repliegue"]["a"] == vistas[1],
          json.dumps(out.get("repliegue")))


# ══ L · LA PATA VIVA (opcional, contra el Groq real) ═══════════════════════════════

def bloque_L() -> None:
    """El discriminante de la obra, contra el proveedor de verdad.

    OPT-IN por `GROQ_API_KEY`: sin llave NO se corre y **se declara no-medible**, jamás se
    da por buena por omisión (un guard que no pudo mirar no dice que está bien). Así la
    vara sigue siendo del pool —determinista y offline— y la pata viva se suma cuando hay
    con qué.

    Cuesta UNA llamada de ~6.000 tokens. El 413, en cambio, es gratis: el proveedor lo
    rechaza sin consumir la ventana, y por eso se mide primero el que rebota.
    """
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key:
        print("[SKIP] L · pata viva contra Groq: sin `GROQ_API_KEY` — NO MEDIBLE, "
              "no se certifica por omisión")
        return
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def enviar(tools, msgs):
        body = {"model": "openai/gpt-oss-120b", "messages": msgs, "max_tokens": 1,
                "tools": tools, "tool_choice": "auto"}
        d = json.dumps(body).encode()
        req = urllib.request.Request(
            URL, data=d, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key,
                     "User-Agent": "puppet-ai/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                o = json.loads(r.read())
                return 200, len(d), (o.get("usage") or {}).get("prompt_tokens"), ""
        except urllib.error.HTTPError as e:
            c = e.read().decode("utf-8", "replace")
            try:
                m = (json.loads(c).get("error") or {}).get("message", "")[:300]
            except Exception:                                  # noqa: BLE001
                m = c[:300]
            return e.code, len(d), None, m

    # Los schemas TIENEN que pesar como los de un belt real: la primera versión usó los
    # sintéticos flacos de los bloques puros (100 = 36 KB) y **entraban**, así que la pata
    # viva medía otra cosa. Éstos son los de la sonda del 2026-08-09: 100 = ~55 KB, que es
    # el caso que produce el 413.
    def _gorda(i):
        return {"type": "function", "function": {
            "name": f"herramienta_{i}",
            "description": ("Hace algo útil con datos del oficio. " * 20)[:180],
            "parameters": {"type": "object", "properties": {
                "consulta": {"type": "string", "description": "qué buscar"},
                "limite": {"type": "integer", "description": "cuántos"},
                "formato": {"type": "string", "enum": ["json", "csv", "texto"]}},
                "required": ["consulta"]}}}

    msgs = [{"role": "user", "content": "hola"}]
    crudas = [_gorda(i) for i in range(100)]
    st, _b, _pt, msg = enviar(crudas, msgs)
    if st == 429:
        print("[SKIP] L · la ventana por minuto está agotada — NO MEDIBLE ahora "
              "(esperá un minuto y repetí; un 429 no dice nada del filtro)")
        return
    check("L1 el cinturón CRUDO (100 tools) lo rechaza Groq — el 413 sigue existiendo",
          st == 413, f"status={st}")
    # El `org_…` del proveedor se recorta del detalle: identifica la cuenta del dueño y no
    # tiene por qué quedar en la salida de una vara que se pega en un acta.
    _m = re.sub(r"`org_[^`]*`", "`org_…`", msg or "")
    check("L2 …y lo rechaza por la VENTANA POR MINUTO, no por el tamaño del cuerpo "
          "(es lo que hacía que el número declarado estuviera en la unidad equivocada)",
          "tokens per minute" in (msg or "").lower(), _m[:150])

    lim = M.limite_de("https://api.groq.com/openai/v1")
    pre = TB.Presupuesto(max_payload_bytes=lim["max_payload_bytes"],
                         max_tools=lim["max_tools"], fuente=lim["fuente"])
    r = TB.recortar(crudas, msgs, pre, reservado=M.RESERVA_DE_CUERPO_BYTES)
    st2, b2, pt2, msg2 = enviar(r.enviadas, msgs)
    if st2 == 429:
        print("[SKIP] L3/L4 · ventana agotada por la propia medición — NO MEDIBLE ahora")
        return
    check("L3 **CON EL FILTRO, EL MISMO CINTURÓN ENTRA**: el 413 muere por construcción",
          st2 == 200,
          f"{len(crudas)}→{len(r.enviadas)} tools · {r.bytes_pedidos}→{b2}B · "
          f"prompt_tokens={pt2} · status={st2} {msg2}")
    check("L4 …y entra con aire: el prompt queda POR DEBAJO de la ventana medida (8.000)",
          isinstance(pt2, int) and pt2 < 8000, f"prompt_tokens={pt2}")


def main() -> int:
    print("=== Gate 4 · F5 · 5.1 · tools por contexto"
          + (" · PRUEBA DE CAÍDA (filtro apagado)" if CAER else "") + " ===\n")
    if not CAER:
        bloque_A()
        bloque_B()
        bloque_C()
    bloque_D()
    bloque_E()
    if not CAER:
        bloque_F()
        bloque_G()
        bloque_M()
        bloque_L()
    print(f"\n=== {_passed} passed, {_failed} failed ===")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
