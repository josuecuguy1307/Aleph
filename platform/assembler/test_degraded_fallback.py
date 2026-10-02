#!/usr/bin/env python3
"""
test_degraded_fallback.py — FALLBACK VISIBLE (C6). Determinista, SIN RED, cero mocks de red.

El done-bar de C6 dice: "si Opus no está, la UI/telemetría MUESTRA el fallback (no silencioso)".
Acá probamos la capa de telemetría de esa caída en aislamiento, llamando directo a
recipe_assembler._emit_model_cost_event con un `record` armado a mano + un on_event que captura
el stream. Verifica:
  - primary → NO hay degradación (ni flag, ni notice, ni record["degraded"]);
  - fallback/oss-direct → el cost-event lleva degraded=True, sale UN aviso
    {type:"notice", kind:"degraded"} con intended vs actual, y record["degraded"] queda lleno;
  - una 2da caída en el mismo run NO re-emite el aviso (un banner por run), pero actualiza el resumen;
  - el tier "reporter" (etapa aparte) NO cuenta como degradación.

Run:  python3 test_degraded_fallback.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recipe_assembler as ra  # noqa: E402

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"[FAIL] {name} — {detail}")


def _fresh_record() -> dict:
    """Un record mínimo con la forma que el assembler inicializa (lo que toca la telemetría)."""
    return {
        "model_route": [],
        "cost_events": [],
        "model_alias": "brain",
        "degraded": None,
    }


def _events_sink():
    out: list = []
    return out, (lambda e: out.append(e))


USAGE = {"prompt_tokens": 100, "completion_tokens": 20}


# ── 1. PRIMARY: sin degradación ───────────────────────────────────────────────
rec = _fresh_record()
rec["model_route"].append({"model": "anthropic/claude-opus-4.8", "tier": "primary", "ok": True})
events, on_event = _events_sink()
ra._emit_model_cost_event(rec, on_event, user_id="u1", run_id="r1",
                          model="anthropic/claude-opus-4.8", tier="primary", usage=USAGE)
cost = [e for e in events if e.get("type") == "cost"]
notices = [e for e in events if e.get("type") == "notice"]
check("1.1 primary → cost-event con degraded=False", cost and cost[0].get("degraded") is False, str(cost))
check("1.2 primary → NINGÚN aviso de degradación", not notices, str(notices))
check("1.3 primary → record['degraded'] sigue None", rec["degraded"] is None, str(rec["degraded"]))


# ── 2. FALLBACK: degradación surfaceada ───────────────────────────────────────
rec = _fresh_record()
# el route_log del run: primary falló, fallback respondió (lo que arma _route_chat).
rec["model_route"].append({"model": "anthropic/claude-opus-4.8", "tier": "primary", "ok": False, "error": "HTTP 402"})
rec["model_route"].append({"model": "openai/gpt-oss-120b", "tier": "fallback", "ok": True})
events, on_event = _events_sink()
ra._emit_model_cost_event(rec, on_event, user_id="u1", run_id="r1",
                          model="openai/gpt-oss-120b", tier="fallback", usage=USAGE)
cost = [e for e in events if e.get("type") == "cost"]
notices = [e for e in events if e.get("type") == "notice"]
check("2.1 fallback → cost-event con degraded=True", cost and cost[0].get("degraded") is True, str(cost))
check("2.2 fallback → sale UN aviso", len(notices) == 1, f"n={len(notices)}")
n = notices[0] if notices else {}
check("2.3 aviso tipado notice/degraded", n.get("type") == "notice" and n.get("kind") == "degraded", str(n))
check("2.4 aviso: intended = el cerebro pedido (route_log[0])",
      n.get("intended_model") == "anthropic/claude-opus-4.8", str(n.get("intended_model")))
check("2.5 aviso: actual = el modelo que respondió", n.get("actual_model") == "openai/gpt-oss-120b", str(n.get("actual_model")))
check("2.6 aviso: tier = fallback", n.get("tier") == "fallback", str(n.get("tier")))
check("2.7 aviso: mensaje legible no vacío", isinstance(n.get("message"), str) and len(n["message"]) > 10, str(n.get("message")))
check("2.8 record['degraded'] DURABLE lleno", isinstance(rec["degraded"], dict)
      and rec["degraded"].get("actual_model") == "openai/gpt-oss-120b"
      and rec["degraded"].get("intended_model") == "anthropic/claude-opus-4.8"
      and rec["degraded"].get("tier") == "fallback", str(rec["degraded"]))


# ── 3. SEGUNDA caída en el mismo run: no re-spamea el aviso, actualiza el resumen ──
rec["model_route"].append({"model": "qwen3:8b", "tier": "oss-direct", "ok": True})
events2, on_event2 = _events_sink()
ra._emit_model_cost_event(rec, on_event2, user_id="u1", run_id="r1",
                          model="qwen3:8b", tier="oss-direct", usage=None)
notices2 = [e for e in events2 if e.get("type") == "notice"]
cost2 = [e for e in events2 if e.get("type") == "cost"]
check("3.1 2da degradación → cost-event degraded=True", cost2 and cost2[0].get("degraded") is True, str(cost2))
check("3.2 2da degradación → NO re-emite aviso (un banner por run)", not notices2, str(notices2))
check("3.3 record['degraded'] refleja la última caída (oss-direct)",
      rec["degraded"].get("tier") == "oss-direct" and rec["degraded"].get("actual_model") == "qwen3:8b",
      str(rec["degraded"]))


# ── 4. REPORTER: etapa aparte, NO es degradación ──────────────────────────────
rec = _fresh_record()
rec["model_route"].append({"model": "anthropic/claude-opus-4.8", "tier": "primary", "ok": True})
events, on_event = _events_sink()
ra._emit_model_cost_event(rec, on_event, user_id="u1", run_id="r1",
                          model="some-reporter-model", tier="reporter", usage=USAGE)
cost = [e for e in events if e.get("type") == "cost"]
notices = [e for e in events if e.get("type") == "notice"]
check("4.1 reporter → cost-event degraded=False", cost and cost[0].get("degraded") is False, str(cost))
check("4.2 reporter → NINGÚN aviso de degradación", not notices, str(notices))
check("4.3 reporter → record['degraded'] sigue None", rec["degraded"] is None, str(rec["degraded"]))


# ── 5. on_event ausente: la degradación igual queda en el record (telemetría durable) ──
rec = _fresh_record()
rec["model_route"].append({"model": "anthropic/claude-opus-4.8", "tier": "primary", "ok": False})
rec["model_route"].append({"model": "openai/gpt-oss-120b", "tier": "fallback", "ok": True})
ra._emit_model_cost_event(rec, None, user_id=None, run_id=None,
                          model="openai/gpt-oss-120b", tier="fallback", usage=USAGE)
check("5.1 sin on_event → record['degraded'] igual se llena", isinstance(rec["degraded"], dict)
      and rec["degraded"].get("tier") == "fallback", str(rec["degraded"]))
check("5.2 sin on_event → el cost-event degradado queda en el record",
      any(e.get("degraded") for e in rec["cost_events"]), str(rec["cost_events"]))


print(f"\n=== {_passed} passed, {_failed} failed ===")
sys.exit(1 if _failed else 0)
