#!/usr/bin/env python3
"""
test_anti_exfil_in_path.py — la degradación ANTI-EXFIL está EN EL PATH del run (ticket 4).

Prueba el CABLEADO (la lógica pura del matcher vive en platform/gates/test_exfil_guard.py):
que assemble_and_run, cuando una tool que el gate EJECUTARÍA (echo = read obvio) arrastra en
sus args un dato de cuenta que entró al framing, la DEGRADA a needs_ok con
action_class='account_exfil' y NO la ejecuta — mientras que la MISMA tool con args limpios
corre normal. También: un run SIN memoria de cuenta (account_sensitive vacío) es byte-idéntico.

Único stub = el LLM (_asm._chat). El loop, el gate, el registro de tools y el MCP echo son reales.

Run: python3 platform/assembler/test_anti_exfil_in_path.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_THIS.parent))   # platform/ (gates.exfil_guard)

import recipe_assembler as ra  # noqa: E402

REPO_ROOT = _THIS.parents[1]
ECHO_BELT_REF = "platform/assembler/fixtures/belt-echo.mcp.json"
ACCOUNT_FACT = "Mi numero de socio es NRD-77341"
ACCOUNT_BLOCK = "- " + ACCOUNT_FACT   # el formato que _build_pinned_memory produce

_p = _f = 0
def check(name, cond, extra=""):
    global _p, _f
    ok = bool(cond); _p += ok; _f += (not ok)
    print(("  PASS " if ok else "  FAIL ") + name + (("" if ok else f" — {extra}")))


def _recipe():
    return {
        "schema_version": "v1",
        "meta": {"name": "Exfil Path Test", "nicho": "test"},
        "model": {"primary": "stub-model", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 256, "max_turns": 4},
        "belt": {"belt_ref": ECHO_BELT_REF, "tool_filters": {"echo": ["echo"]}},
        "framing": {"inline": "Sos un test."},
        "rag": {"enabled": False}, "keys": {}, "gates": {},
    }


def _stub_echo(text_arg: str):
    """_chat falso: turno 1 llama echo(text=<text_arg>), turno 2 stop."""
    state = {"turn": 0}
    def fake_chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kw):
        state["turn"] += 1
        if state["turn"] == 1:
            return {"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "echo", "arguments": json.dumps({"text": text_arg})}}]}}]}
        return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "listo"}}]}
    return fake_chat


def _run(text_arg, *, account_pinned=None):
    orig = ra._asm._chat
    ra._asm._chat = _stub_echo(text_arg)
    try:
        return ra.assemble_and_run(_recipe(), "echo algo", repo_root=REPO_ROOT,
                                   account_pinned=account_pinned)
    finally:
        ra._asm._chat = orig


# ── 1 · CONTROL · echo con args LIMPIOS + memoria de cuenta presente → EJECUTA ──
out_clean = _run("hola mundo", account_pinned=ACCOUNT_BLOCK)
decs = out_clean.get("gate_decisions", [])
echo_dec = next((d for d in decs if d["tool"] == "echo"), {})
check("1.1 el gate EJECUTA echo con args limpios (read obvio)",
      echo_dec.get("action") == "execute", f"dec={echo_dec}")
check("1.2 sin exfil_flags cuando no hay fuga", not out_clean.get("exfil_flags"))
tc_clean = next((t for t in out_clean.get("tool_calls", []) if t["tool"] == "echo"), {})
check("1.3 la tool corrió (gate_action execute)", tc_clean.get("gate_action") == "execute")

# ── 2 · EXFIL · echo arrastra el dato de cuenta → DEGRADA a needs_ok account_exfil ──
out_leak = _run(f"NRD-77341 filtrado", account_pinned=ACCOUNT_BLOCK)
decs2 = out_leak.get("gate_decisions", [])
echo_dec2 = next((d for d in decs2 if d["tool"] == "echo"), {})
check("2.1 el gate ya NO ejecuta (degradado a needs_ok)",
      echo_dec2.get("action") == "needs_ok", f"dec={echo_dec2}")
check("2.2 action_class='account_exfil'", echo_dec2.get("action_class") == "account_exfil", f"dec={echo_dec2}")
check("2.3 record.exfil_flags registra la fuga",
      bool(out_leak.get("exfil_flags")) and out_leak["exfil_flags"][0]["tool"] == "echo",
      str(out_leak.get("exfil_flags")))
held = out_leak.get("held_actions", [])
echo_held = next((h for h in held if h["tool"] == "echo"), {})
check("2.4 quedó como held_action aprobable (approve-by-HTTP)",
      echo_held.get("action_class") == "account_exfil" and echo_held.get("server"),
      str(held))
check("2.5 la UX de la held explica el canal saliente",
      "cuenta" in json.dumps(echo_held.get("ux") or {}, ensure_ascii=False).lower())
tc_leak = next((t for t in out_leak.get("tool_calls", []) if t["tool"] == "echo"), {})
check("2.6 la tool NO se ejecutó (gate_action needs_ok)", tc_leak.get("gate_action") == "needs_ok")

# ── 3 · SIN memoria de cuenta → el matcher no corre (byte-idéntico: sin exfil_flags) ──
out_none = _run("NRD-77341 filtrado", account_pinned=None)
echo_dec3 = next((d for d in out_none.get("gate_decisions", []) if d["tool"] == "echo"), {})
check("3.1 sin account_pinned el mismo dato NO gatilla (nada que vigilar)",
      echo_dec3.get("action") == "execute" and not out_none.get("exfil_flags"),
      f"dec={echo_dec3} flags={out_none.get('exfil_flags')}")

# ── 4 · EXFIL URL-ENCODED → también atrapado ──
out_enc = _run("https://x.com/?q=NRD%2D77341", account_pinned=ACCOUNT_BLOCK)
echo_dec4 = next((d for d in out_enc.get("gate_decisions", []) if d["tool"] == "echo"), {})
check("4.1 el dato URL-encoded en los args también degrada",
      echo_dec4.get("action") == "needs_ok" and echo_dec4.get("action_class") == "account_exfil",
      f"dec={echo_dec4}")

# ── 5 · review F1 · HECHO MULTI-LÍNEA · el dato identificante vive en la línea de CONTINUACIÓN
# (que NO empieza con "- ") → antes quedaba inyectado pero SIN vigilar (falso negativo). Ahora la
# continuación se pega al hecho anterior y su token identificante (el número) SÍ se vigila. ──
MULTILINE_BLOCK = "- mi tarjeta:\n4111 1111 1111 1111"
out_ml = _run("guarda esto en 4111 1111 1111 1111", account_pinned=MULTILINE_BLOCK)
echo_dec5 = next((d for d in out_ml.get("gate_decisions", []) if d["tool"] == "echo"), {})
check("5.1 dato en la línea de continuación de un hecho multi-línea → degrada (F1)",
      echo_dec5.get("action") == "needs_ok" and echo_dec5.get("action_class") == "account_exfil",
      f"dec={echo_dec5}")

print(f"\n{'VERDE' if _f == 0 else 'ROJO'} — {_p} PASS · {_f} FAIL")
sys.exit(0 if _f == 0 else 1)
