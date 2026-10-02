#!/usr/bin/env python3
"""
test_reliability_fallback.py — REGRESIÓN del cuelgue 2026-06-15 (Fase 2).

Bug original: el run se colgó porque el gateway :4000 estaba caído y el agente quedó
esperando SIN timeout ni fallback. Peor: primary y fallback de las recetas vivían en el
MISMO :4000, así que una caída del gateway mataba ambos sin escape a OSS local.

La cura (ver recipe_assembler._route_chat + assembler._chat):
  - transporte caído/medio-abierto → RuntimeError ACOTADO (PUPPET_HTTP_TIMEOUT), nunca cuelgue;
  - RED DE SEGURIDAD: si gateway (primary y fallback) falla, cae a OSS-DIRECTO (ollama),
    un base_url DISTINTO. El run JAMÁS se cuelga ni muere esperando un gateway muerto.

Esta es una prueba VIVA (usa el ollama nativo en :11434 con qwen3:8b) + el MCP calc real;
lo ÚNICO muerto es el "gateway" (:4000, puerto cerrado). Sin mocks de nuestras piezas.

Run:  python3 test_reliability_fallback.py
Requisitos: ollama corriendo en :11434 con qwen3:8b (la red de seguridad OSS-directo).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

import recipe_assembler as ra  # noqa: E402

REPO_ROOT = _THIS.parents[1]
CALC_BELT_REF = "platform/assembler/fixtures/belt-calc.mcp.json"
DEAD_GATEWAY = "http://127.0.0.1:4000/v1"  # puerto cerrado en esta corrida (gateway caído)

# cota dura de "no se cuelga": connect-refused es instantáneo; aun si fuera medio-abierto,
# PUPPET_HTTP_TIMEOUT lo acota. Damos margen para la generación local del OSS-directo.
NO_HANG_BUDGET_S = 150.0

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    mark = "PASS" if cond else "FAIL"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _recipe_dead_gateway() -> dict:
    """Receta cuyo gateway (primary + fallback) está MUERTO. La red de seguridad debe
    rescatar el run cayendo a OSS-directo. Belt calc real (credential-free)."""
    return {
        "schema_version": "v1",
        "meta": {"name": "Reliability Regression", "nicho": "test"},
        "model": {
            "primary": "gpt-oss-120b",       # vive (vivía) en el gateway muerto
            "fallback": "llama-3.3-70b",     # MISMO gateway muerto → también falla
            "base_url": DEAD_GATEWAY,
            "temperature": 0,
            "max_tokens": 512,
            "max_turns": 4,
        },
        "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": ["add", "mul"]}},
        "framing": {"inline": "Sos un agente de cálculo. Para sumar usá la herramienta add. "
                              "Respondé sólo el número final."},
        "rag": {"enabled": False},
        "keys": {},
        "gates": {},
    }


def test_dead_gateway_falls_to_oss_direct_without_hanging():
    t0 = time.monotonic()
    out = ra.assemble_and_run(_recipe_dead_gateway(), "cuánto es 21 + 21",
                              repo_root=REPO_ROOT, deadline_s=120.0)
    elapsed = time.monotonic() - t0

    check("R.1 el run NO se colgó: completó dentro del presupuesto",
          elapsed < NO_HANG_BUDGET_S, f"elapsed={elapsed:.1f}s (budget {NO_HANG_BUDGET_S}s)")
    check("R.2 el run completó OK pese al gateway muerto",
          out.get("ok") is True, f"out.error={out.get('error')}")

    route = out.get("model_route", [])
    primary_failed = any(r["tier"] == "primary" and r.get("ok") is False for r in route)
    fallback_failed = any(r["tier"] == "fallback" and r.get("ok") is False for r in route)
    oss_rescued = any(r["tier"] == "oss-direct" and r.get("ok") is True for r in route)
    check("R.3 primary falló (gateway caído)", primary_failed, f"route={route}")
    check("R.4 fallback (mismo gateway) también falló", fallback_failed, f"route={route}")
    check("R.5 OSS-DIRECTO rescató el run (red de seguridad)", oss_rescued, f"route={route}")
    check("R.6 el modelo final fue el OSS-directo, no el gateway muerto",
          out.get("model_final") == ra.OSS_DIRECT_MODEL,
          f"model_final={out.get('model_final')}")

    # evidencia de que CORRIÓ de verdad por OSS-directo: o respondió, o usó la tool calc.
    answered = bool((out.get("answer") or "").strip())
    used_tool = any(t.get("tool") in ("add", "mul") for t in out.get("tool_calls", []))
    check("R.7 produjo trabajo real vía OSS-directo (respuesta o tool calc usada)",
          answered or used_tool,
          f"answer={out.get('answer')!r} tool_calls={out.get('tool_calls')}")


def test_safety_net_can_be_disabled():
    """Con PUPPET_OSS_DIRECT=0 la red se apaga: el run NO se cuelga (clave), pero
    devuelve error tipado en vez de rescatar. Prueba que el apagado es honesto."""
    import os
    prev = os.environ.get("PUPPET_OSS_DIRECT")
    # recargar el módulo con la env nueva para releer la constante
    os.environ["PUPPET_OSS_DIRECT"] = "0"
    import importlib
    importlib.reload(ra)
    try:
        t0 = time.monotonic()
        out = ra.assemble_and_run(_recipe_dead_gateway(), "cuánto es 1 + 1",
                                  repo_root=REPO_ROOT, deadline_s=30.0)
        elapsed = time.monotonic() - t0
        check("R.8 sin red de seguridad TAMPOCO se cuelga (error tipado, no hang)",
              elapsed < NO_HANG_BUDGET_S and out.get("ok") is False
              and out.get("error") is not None,
              f"elapsed={elapsed:.1f}s ok={out.get('ok')} error={out.get('error')}")
    finally:
        if prev is None:
            os.environ.pop("PUPPET_OSS_DIRECT", None)
        else:
            os.environ["PUPPET_OSS_DIRECT"] = prev
        importlib.reload(ra)  # restaurar la red de seguridad para el resto del proceso


def main():
    print("=== reliability fallback (regresión del cuelgue 2026-06-15; ollama vivo) ===\n")
    test_dead_gateway_falls_to_oss_direct_without_hanging()
    test_safety_net_can_be_disabled()
    print(f"\n=== {_passed} passed, {_failed} failed ===")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
