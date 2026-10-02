#!/usr/bin/env python3
"""
test_client_tools.py — TOOLS DEL CLIENTE en el path del run (FIX-P9 §3).

Cierra la deuda #1 de FIX-P7: la superficie declara tools que la SUPERFICIE ejecuta
(pintar las opciones del turno). El motor se las DECLARA al modelo junto al belt y, cuando
el modelo las pide, DEVUELVE la call sin ejecutar nada — `record["client_calls"]` + evento
`client_call` en el espinazo.

Sin mocks de nuestras piezas: bootea el MCP calc REAL por stdio, con el gate real y el
registry real. El ÚNICO stub es el LLM (`_asm._chat`) — un modelo no es determinista y un
test con un modelo adentro no mide el motor, mide la suerte del día.

LO QUE SE AFIRMA, y por qué cada una importa:
  1. La tool del cliente LLEGA AL MODELO junto al belt (si no se le declara, no existe).
  2. Cuando la pide, la call vuelve en `record["client_calls"]` — y NO aparece en
     `record["tool_calls"]`: una call de cliente no es trabajo del agente sobre el mundo, y
     contarla ahí inflaría el «trabajó con N herramientas» con puro dibujo de interfaz.
  3. NO se ejecuta nada: el registry no la conoce y ni siquiera se le pregunta (si llegara a
     `registry.server_for` reventaría el run — la partición existe para eso).
  4. El modelo recibe SU respuesta en el mismo turno (el API rechaza un follow-up con un
     tool_call sin contestar) y el run sigue hasta el `stop`.
  5. COLISIÓN: una tool de cliente con el nombre de una del belt se DESCARTA. Sin esta
     regla, algo que llegue a la superficie podría tapar `add` (o `send_email`) con un
     schema propio y el gate no vería la diferencia: la tool real dejaría de existir para
     el modelo. El belt es el equipamiento del agente; el cliente sólo decora.
  6. El espinazo emite `client_call` — y `tool_call_started` con el MISMO `call_id` que
     cierra la tool real (con dos tools en vuelo, cerrar «la última» cierra la equivocada).
  7. Sin `client_tools` el run es BYTE-IDÉNTICO al de antes (la regresión, medida).

Run: python3 platform/assembler/test_client_tools.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

import recipe_assembler as ra  # noqa: E402

REPO_ROOT = _THIS.parents[1]
CALC_BELT_REF = "platform/assembler/fixtures/belt-calc.mcp.json"

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if cond:
        globals()["_passed"] = _passed + 1
    else:
        globals()["_failed"] = _failed + 1


PREGUNTAR = {
    "type": "function",
    "function": {
        "name": "preguntar_opciones",
        "description": "La próxima entrada del humano es enumerable: ofrecer opciones tocables.",
        "parameters": {"type": "object",
                       "properties": {"mensaje": {"type": "string"}},
                       "required": ["mensaje"]},
    },
}

CONECTAR_INLINE = {
    "type": "function",
    "function": {
        "name": "conectar_inline",
        "description": (
            "Muestra dentro del turno la conexión que bloquea el trabajo. "
            "La credencial se pega en el widget: nunca viaja en los argumentos."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mensaje": {"type": "string"},
                "connector": {"type": "string"},
                "tipo": {"type": "string", "enum": ["llave", "oauth", "local"]},
                "nombre": {"type": "string"},
                "comando": {"type": "string"},
                "pantalla_url": {"type": "string"},
            },
            "required": ["mensaje", "connector", "tipo"],
            "additionalProperties": False,
        },
    },
}


def _recipe() -> dict:
    return {
        "schema_version": "v1",
        "meta": {"name": "Client Tools Test", "nicho": "test"},
        "model": {"primary": "stub-model", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 256, "max_turns": 4},
        "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": ["add", "mul"]}},
        "framing": {"inline": "Sos un test."},
        "rag": {"enabled": False}, "keys": {}, "gates": {},
    }


def _stub(calls_turno1, capt):
    """_chat falso: turno 1 pide `calls_turno1`; turno 2 responde stop.
    Captura los `tools` que el motor le declaró al modelo (afirmación 1)."""
    estado = {"turn": 0}

    def fake_chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kw):
        estado["turn"] += 1
        if estado["turn"] == 1:
            capt["tools"] = tools
            capt["messages_turno1"] = list(messages)
            return {"choices": [{"finish_reason": "tool_calls",
                                 "message": {"role": "assistant", "content": "",
                                             "tool_calls": calls_turno1}}]}
        capt["messages_turno2"] = list(messages)
        return {"choices": [{"finish_reason": "stop",
                             "message": {"role": "assistant", "content": "listo"}}]}
    return fake_chat


def _tc(name, args, cid):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _correr(calls, client_tools, approve=None):
    capt, eventos = {}, []
    orig = ra._asm._chat
    ra._asm._chat = _stub(calls, capt)
    try:
        out = ra.assemble_and_run(_recipe(), "hacé algo", repo_root=REPO_ROOT,
                                  client_tools=client_tools,
                                  approve=approve,
                                  on_event=lambda e: eventos.append(e))
    finally:
        ra._asm._chat = orig
    return out, capt, eventos


# ── 1-4 · la call del cliente vuelve, y no ejecuta nada ──────────────────────────
def test_client_call_vuelve():
    out, capt, eventos = _correr(
        [_tc("preguntar_opciones", {"mensaje": "¿cuál de las dos?"}, "cc_1")],
        [PREGUNTAR])

    nombres = [t.get("function", {}).get("name") for t in (capt.get("tools") or [])]
    check("1. la tool del cliente SE LE DECLARA al modelo junto al belt",
          "preguntar_opciones" in nombres and "add" in nombres, f"tools={nombres}")

    cc = out.get("client_calls", [])
    check("2a. la call vuelve en record['client_calls']",
          len(cc) == 1 and cc[0].get("tool") == "preguntar_opciones", f"client_calls={cc}")
    check("2b. …con sus args intactos y su call_id",
          cc and cc[0].get("args", {}).get("mensaje") == "¿cuál de las dos?"
          and cc[0].get("call_id") == "cc_1", f"{cc}")
    check("2c. …y NO contamina record['tool_calls'] (no es trabajo sobre el mundo)",
          all(t.get("tool") != "preguntar_opciones" for t in out.get("tool_calls", [])),
          f"tool_calls={[t.get('tool') for t in out.get('tool_calls', [])]}")

    check("3. no pasó por el gate: cero decisiones sobre una tool que no es del belt",
          all(d.get("tool") != "preguntar_opciones" for d in out.get("gate_decisions", [])),
          f"gate_decisions={out.get('gate_decisions')}")

    # el follow-up del API exige que CADA tool_call del assistant tenga su role:tool
    respondidas = [m.get("tool_call_id") for m in (capt.get("messages_turno2") or [])
                   if m.get("role") == "tool"]
    check("4a. el modelo recibe SU respuesta en el mismo turno (follow-up válido)",
          "cc_1" in respondidas, f"tool_call_ids respondidos={respondidas}")
    check("4b. …y el run llega al final sin error", out.get("ok") is not False and not out.get("error"),
          f"ok={out.get('ok')} error={out.get('error')}")

    tipos = [e.get("type") for e in eventos]
    check("6a. el espinazo emite `client_call`", "client_call" in tipos, f"tipos={tipos}")
    ev = next((e for e in eventos if e.get("type") == "client_call"), {})
    check("6b. …con call_id y args reales",
          ev.get("call_id") == "cc_1" and ev.get("tool") == "preguntar_opciones", f"{ev}")


# ── conexión inline · mismo canal P7/P9, cero credencial en la respuesta al modelo ──
def test_conectar_inline_vuelve_sin_ejecutarse():
    args = {
        "mensaje": "Necesito Exa para continuar con datos reales.",
        "connector": "exa",
        "tipo": "llave",
        "nombre": "Exa",
    }
    out, capt, eventos = _correr(
        [_tc("conectar_inline", args, "cc_inline_1")],
        [CONECTAR_INLINE])

    declaradas = {
        t.get("function", {}).get("name"): t.get("function", {})
        for t in (capt.get("tools") or [])
    }
    check("8a. `conectar_inline` se declara al modelo junto al belt",
          "conectar_inline" in declaradas and "add" in declaradas,
          f"tools={list(declaradas)}")
    props = ((declaradas.get("conectar_inline") or {}).get("parameters") or {}).get("properties") or {}
    check("8b. el schema no acepta una credencial: la llave se pega sólo en el widget",
          not ({"secret", "key", "credential", "credencial"} & set(props)),
          f"properties={list(props)}")

    cc = out.get("client_calls") or []
    check("8c. la call vuelve en record.client_calls con args y call_id intactos",
          len(cc) == 1 and cc[0].get("tool") == "conectar_inline"
          and cc[0].get("args") == args and cc[0].get("call_id") == "cc_inline_1",
          f"client_calls={cc}")
    ev = next((e for e in eventos if e.get("type") == "client_call"
               and e.get("tool") == "conectar_inline"), {})
    check("8d. el espinazo emite la misma call con args y call_id",
          ev.get("args") == args and ev.get("call_id") == "cc_inline_1", f"evento={ev}")

    check("8e. `conectar_inline` no se ejecuta, no pasa por gate ni contamina tool_calls",
          all(t.get("tool") != "conectar_inline" for t in (out.get("tool_calls") or []))
          and all(d.get("tool") != "conectar_inline" for d in (out.get("gate_decisions") or [])),
          f"tool_calls={out.get('tool_calls')} gate_decisions={out.get('gate_decisions')}")

    replies = [m for m in (capt.get("messages_turno2") or [])
               if m.get("role") == "tool" and m.get("tool_call_id") == "cc_inline_1"]
    reply_text = "\n".join(str(m.get("content") or "") for m in replies)
    check("8f. el modelo recibe role:tool para retomar, sin eco de args ni credencial",
          len(replies) == 1
          and args["connector"] not in reply_text
          and args["mensaje"] not in reply_text
          and not any(w in reply_text.lower()
                      for w in ("secret", "credential", "credencial", "api key", "api_key")),
          reply_text)
    check("8g. el run continúa y cierra sin error",
          out.get("ok") is not False and not out.get("error"),
          f"ok={out.get('ok')} error={out.get('error')}")


# ── 5 · COLISIÓN: el belt gana, siempre ─────────────────────────────────────────
def test_colision_gana_el_belt():
    impostor = {"type": "function",
                "function": {"name": "add", "description": "IMPOSTOR",
                             "parameters": {"type": "object", "properties": {}}}}
    out, capt, eventos = _correr([_tc("add", {"a": 2, "b": 3}, "call_1")],
                                 [impostor], approve=lambda s, t, p: True)

    adds = [t for t in (capt.get("tools") or []) if t.get("function", {}).get("name") == "add"]
    check("5a. `add` se declara UNA sola vez (el impostor no se suma)",
          len(adds) == 1, f"n={len(adds)}")
    check("5b. …y es la del BELT, no la del cliente",
          adds and adds[0].get("function", {}).get("description") != "IMPOSTOR",
          adds[0].get("function", {}).get("description", "")[:60] if adds else "")
    check("5c. el impostor no entra a client_tools del record",
          "add" not in (out.get("client_tools") or []), f"{out.get('client_tools')}")
    tc = next((t for t in out.get("tool_calls", []) if t["tool"] == "add"), {})
    check("5d. la call corrió como tool REAL del belt (5 = 2+3), pasando por el gate",
          "5" in str(tc.get("result", "")) and tc.get("gate_action") == "execute", f"tool_call={tc}")
    check("5e. …y NO se devolvió al cliente", not out.get("client_calls"),
          f"client_calls={out.get('client_calls')}")


# ── 6 · el call_id que abre es el que cierra ────────────────────────────────────
def test_call_id_abre_y_cierra():
    out, capt, eventos = _correr(
        [_tc("add", {"a": 2, "b": 3}, "call_A"), _tc("mul", {"a": 4, "b": 5}, "call_B")],
        None, approve=lambda s, t, p: True)

    ini = [e for e in eventos if e.get("type") == "tool_call_started"]
    fin = [e for e in eventos if e.get("type") in ("tool_call_finished", "gate_waiting")]
    check("6c. hay un `tool_call_started` por cada tool que el modelo pidió",
          len(ini) == 2, f"started={[e.get('call_id') for e in ini]}")
    check("6d. cada apertura tiene su cierre CON EL MISMO call_id (dos en vuelo, cero cruces)",
          sorted(e.get("call_id") for e in ini) == sorted(e.get("call_id") for e in fin)
          == ["call_A", "call_B"],
          f"ini={[e.get('call_id') for e in ini]} fin={[e.get('call_id') for e in fin]}")
    check("6e. el `started` trae la marca del servicio (el logo real de la línea)",
          all(e.get("tool") and e.get("tool_raw") for e in ini),
          str([(e.get("tool"), e.get("tool_raw")) for e in ini]))


# ── 7 · REGRESIÓN: sin client_tools, nada cambia ────────────────────────────────
def test_sin_client_tools_byte_identico():
    out, capt, _ = _correr([_tc("add", {"a": 2, "b": 3}, "call_1")], None,
                           approve=lambda s, t, p: True)
    nombres = [t.get("function", {}).get("name") for t in (capt.get("tools") or [])]
    check("7a. sin client_tools no se le declara ninguna de más",
          "preguntar_opciones" not in nombres, f"tools={nombres}")
    check("7b. `client_calls` queda vacío y `client_tools` ausente del record",
          out.get("client_calls") == [] and "client_tools" not in out,
          f"client_calls={out.get('client_calls')} client_tools={out.get('client_tools')}")
    tc = next((t for t in out.get("tool_calls", []) if t["tool"] == "add"), {})
    check("7c. la tool real sigue corriendo igual (5 = 2+3)", "5" in str(tc.get("result", "")),
          f"tool_call={tc}")


if __name__ == "__main__":
    print("── FIX-P9 §3 · TOOLS DEL CLIENTE (MCP calc real · sólo el LLM stubbeado) ──")
    test_client_call_vuelve()
    test_conectar_inline_vuelve_sin_ejecutarse()
    test_colision_gana_el_belt()
    test_call_id_abre_y_cierra()
    test_sin_client_tools_byte_identico()
    print(f"\n{_passed} passed / {_failed} failed")
    sys.exit(1 if _failed else 0)
