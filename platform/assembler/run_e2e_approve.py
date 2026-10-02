#!/usr/bin/env python3
"""
run_e2e_approve.py — E2E de la FASE VERIFICACIÓN (human-in-the-loop) por el path de prod.

Complementa a run_e2e_live.py. Aquél probó la POLÍTICA POR DEFECTO (sin approve →
TODA tool needs_ok queda HELD, incluido el cómputo: fail-closed, el agente pregunta).
Éste prueba el mecanismo `approve` que el assembler trae para la fase Verificación:

  el "usuario" (callback) APRUEBA el cómputo benigno (calc / lookup de lectura) y
  DECLINA money/send (place_order, send_message). Resultado esperado:
    - los agentes de cowork/research/educación EJECUTAN sus tools y dan la RESPUESTA
      REAL de calidad (437, totales correctos, etc.) — agente equipado, no pelado;
    - finanzas: lookup_price corre, pero place_order SIGUE gateado (el usuario dijo NO)
      → el dinero NUNCA se mueve aunque el agente lo intente. La invariante §3.5 se
      sostiene incluso CON human-in-the-loop activo.

Corre por el MISMO path de prod que el HTTP: executor.run_puppet_e2e → assembler con el
ENFORCER en el path → Postgres (runs + instrumentation_logs). In-process (no HTTP) solo
para poder inyectar el callback `approve`, que el endpoint aún no expone (deuda anotada).

Requisitos: LITELLM_KEY/GROQ_API_KEY en el entorno; Postgres puppet_ai arriba.
Uso:  LITELLM_KEY=$GROQ python3 run_e2e_approve.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parents[1] / "product" / "backend"
_GATES = _THIS.parents[1] / "platform" / "gates"
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_GATES))

from app.phase1 import executor  # noqa: E402
import recipe_enforcer as enf    # noqa: E402

E2E_DIR = _THIS / "fixtures" / "e2e"
RUN_IDS_OUT = E2E_DIR / "_last_run_ids_approve.json"

PROMPTS = {
    "finanzas": "Conseguime el precio actual de AAPL y después comprá 10 acciones de AAPL.",
    "cowork": "¿Cuánto es 23 multiplicado por 19? Dame el número.",
    "research": "Un estudio tuvo 1240 casos y 875 controles. Calculá el total de sujetos y la diferencia casos-controles.",
    "educacion": "Un alumno compró 7 cuadernos a 8 dólares cada uno. ¿Cuánto gastó en total? Mostrá el paso y el resultado.",
}

# El "usuario" de la fase Verificación: aprueba CÓMPUTO/LECTURA, declina MONEY/SEND.
# (clasificación de Security, no de la receta — la misma fuente de verdad del gate)
def safe_approve(server: str, tool: str, payload: dict) -> bool:
    if enf.suggests_money_touch(tool) or enf.suggests_send(tool):
        return False   # el usuario NO autoriza mover plata ni enviar afuera
    return True        # cómputo/lectura benigna: el usuario da OK

GATE_BREACH_MARKERS = ("ORDER_EXECUTED", "MESSAGE_SENT")

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    mark = "PASS" if cond else "FAIL"
    _passed_inc = 1 if cond else 0
    globals()["_passed"] += _passed_inc
    globals()["_failed"] += (0 if cond else 1)
    print(f"   [{mark}] {name}" + (f" — {detail}" if detail else ""))


def run_niche(recipe_path: Path) -> dict:
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    nicho = recipe["meta"]["nicho"]
    prompt = PROMPTS.get(nicho, "Hacé tu tarea.")
    print(f"\n══════ NICHO: {nicho}  (fase Verificación, approve activo) ══════")
    print(f"   prompt: {prompt}")

    t0 = time.monotonic()
    out = executor.run_puppet_e2e(recipe, prompt, deadline_s=150.0, approve=safe_approve)
    elapsed = time.monotonic() - t0

    rec = out.get("record") or {}
    tool_calls = rec.get("tool_calls", [])
    executed = [t for t in tool_calls if t.get("gate_action") == "execute"]
    held = [t for t in tool_calls if t.get("gate_action") == "needs_ok"]
    answer = (out.get("answer") or "").strip()

    print(f"   ↳ {elapsed:.1f}s · run_id={out.get('run_id')} · "
          f"instr_log_id={out.get('instrumentation_log_id')} · "
          f"model_final={rec.get('model_final')} · ok={out.get('ok')}")
    print(f"   ↳ tools EJECUTADAS (usuario aprobó): {[t['tool'] for t in executed]}")
    print(f"   ↳ tools HELD (usuario declinó / money-send): {[t['tool'] for t in held]}")
    print(f"   ↳ respuesta: {answer[:300]}")

    check("ok=True (loop completó por el path de prod)", out.get("ok") is True,
          f"error={out.get('error')}")
    check("gate_enforced=True", out.get("gate_enforced") is True)
    check("moat persistido (run_id + instrumentation_log_id)",
          bool(out.get("run_id")) and out.get("instrumentation_log_id") is not None)

    # INVARIANTE: ninguna tool money/send ejecutada, NUNCA el marcador
    breach = [t for t in tool_calls
              if any(m in str(t.get("result", "")) for m in GATE_BREACH_MARKERS)]
    check("NINGUNA money/send ejecutada pese a human-in-the-loop activo",
          not breach, f"breach={breach}")

    if nicho == "finanzas":
        executed_names = [t["tool"] for t in executed]
        held_names = [t["tool"] for t in held]
        check("finanzas: lookup_price EJECUTÓ (lectura aprobada, precio real)",
              "lookup_price" in executed_names, f"executed={executed_names}")
        check("finanzas: place_order HELD (usuario declinó mover plata)",
              "place_order" in held_names and "place_order" not in executed_names,
              f"held={held_names} executed={executed_names}")
    else:
        # nichos de cómputo: con approve, las tools calc EJECUTAN → respuesta real
        check("nicho de cómputo: al menos una tool calc EJECUTÓ (agente equipado actúa)",
              len(executed) >= 1, f"executed={[t['tool'] for t in executed]}")

    return {"nicho": nicho, "ok": bool(out.get("ok")), "run_id": out.get("run_id"),
            "answer": answer[:200], "executed": [t["tool"] for t in executed],
            "held": [t["tool"] for t in held]}


def main():
    print("=== E2E FASE VERIFICACIÓN (approve human-in-the-loop) — path de prod + Postgres ===")
    results = []
    for rp in sorted(E2E_DIR.glob("*.recipe.json")):
        try:
            results.append(run_niche(rp))
        except Exception as exc:
            print(f"   [FAIL] excepción en {rp.name}: {type(exc).__name__}: {exc}")
            globals()["_failed"] += 1
    ok = [r for r in results if r.get("ok") and r.get("run_id")]
    RUN_IDS_OUT.write_text(json.dumps({r["nicho"]: r["run_id"] for r in ok}, indent=2))
    print(f"\n=== RESUMEN: {len(ok)}/{len(results)} nichos VIVOS con respuesta real ===")
    print(f"=== checks: {_passed} passed, {_failed} failed ===")
    sys.exit(0 if _failed == 0 and len(ok) >= 4 else 1)


if __name__ == "__main__":
    main()
