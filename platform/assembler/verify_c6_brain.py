#!/usr/bin/env python3
"""
verify_c6_brain.py — DONE-BAR de C6, verificado contra el entorno VIVO (no self-report).

C6: "correr un agente en la Sala → model_final = opus verificado vivo; y si Opus no está,
la UI/telemetría MUESTRA el fallback (no silencioso)." Corremos el MISMO path que la Sala
(recipe_assembler.assemble_and_run) — sin tocar :8080 — con el alias `brain`, en dos escenarios.

El escenario lo fija el ENTORNO (los aliases de models.py se computan al importar), así que se
corre en DOS procesos:

  # A — brain → shim Opus real en :8923  ⇒  model_final = opus, sin degradación
  PUPPET_BRAIN_SHIM=1 \
    .venv/bin/python verify_c6_brain.py expect-opus

  # B — brain → shim caído (puerto muerto)  ⇒  fallback VISIBLE (record["degraded"] + aviso)
  PUPPET_BRAIN_SHIM=1 PUPPET_BRAIN_SHIM_BASE_URL=http://127.0.0.1:8999/v1 \
    .venv/bin/python verify_c6_brain.py expect-degraded

Requisitos: el shim :8923 vivo (escenario A) y la red OSS de Groq/ollama (escenario B).
"""
from __future__ import annotations

import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

import models as _models       # noqa: E402
import recipe_assembler as ra  # noqa: E402

REPO_ROOT = _THIS.parents[1]
CALC_BELT_REF = "platform/assembler/fixtures/belt-calc.mcp.json"

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


def _recipe_brain() -> dict:
    """Receta que usa el alias `brain` (sin hornear primary/base_url) — el cerebro del producto."""
    return {
        "schema_version": "v1",
        "meta": {"name": "C6 brain verify", "nicho": "test"},
        "model": {"alias": "brain", "temperature": 0, "max_tokens": 64, "max_turns": 3},
        "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": ["add", "mul"]}},
        "framing": {"inline": "Sos un agente de cálculo. Respondé sólo el número final."},
        "rag": {"enabled": False},
        "keys": {},
        "gates": {},
    }


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "expect-opus"

    # Cómo resolvió el alias brain ESTE proceso (según el entorno) — evidencia del seam.
    eff = _models.resolve_recipe_model({"alias": "brain"})
    print(f"[seam] brain → primary={eff['primary']!r} base_url={eff['base_url']!r} "
          f"shim_on={_models._BRAIN_SHIM_ON}")

    events: list = []
    out = ra.assemble_and_run(
        _recipe_brain(), "cuánto es 21 + 21",
        repo_root=REPO_ROOT, deadline_s=180.0,
        on_event=lambda e: events.append(e),
        user_id="c6-verify", run_id="c6-run",
    )

    model_final = (out.get("model_final") or "")
    degraded = out.get("degraded")
    notices = [e for e in events if e.get("type") == "notice" and e.get("kind") == "degraded"]
    route = out.get("model_route", [])
    answer = (out.get("answer") or "").strip()
    print(f"[run] ok={out.get('ok')} model_final={model_final!r} degraded={degraded} "
          f"answer={answer[:60]!r}")
    print(f"[run] route={[ (r.get('tier'), r.get('model'), r.get('ok')) for r in route ]}")

    if mode == "expect-opus":
        # DONE-BAR mitad 1: el brain ruteó a Opus REAL y respondió vivo.
        check("A.1 model_final = opus (cerebro real vía shim)", "opus" in model_final.lower(), model_final)
        check("A.2 el run completó OK", out.get("ok") is True, str(out.get("error")))
        check("A.3 NO hubo degradación (record['degraded'] None)", degraded is None, str(degraded))
        check("A.4 NO se emitió aviso de fallback", not notices, str(notices))
        check("A.5 produjo respuesta real", bool(answer), answer)
        check("A.6 el primary (brain) respondió ok en el route_log",
              any(r.get("tier") == "primary" and r.get("ok") for r in route), str(route))
    elif mode == "expect-degraded":
        # DONE-BAR mitad 2: Opus NO está → la telemetría MUESTRA el fallback (no silencioso).
        check("B.1 model_final NO es opus (cayó del cerebro)", "opus" not in model_final.lower(), model_final)
        check("B.2 el run completó igual (red de seguridad)", out.get("ok") is True, str(out.get("error")))
        check("B.3 record['degraded'] LLENO (telemetría durable)", isinstance(degraded, dict), str(degraded))
        check("B.4 degraded.intended apunta al cerebro pedido",
              isinstance(degraded, dict) and "opus" in str(degraded.get("intended_model", "")).lower(),
              str(degraded))
        check("B.5 degraded.actual = el modelo que respondió de verdad",
              isinstance(degraded, dict) and degraded.get("actual_model") == model_final, str(degraded))
        check("B.6 salió UN aviso de degradación en el stream", len(notices) == 1, str(notices))
        check("B.7 el primary (brain/shim) falló en el route_log",
              any(r.get("tier") == "primary" and r.get("ok") is False for r in route), str(route))
    else:
        print(f"[ERROR] modo desconocido: {mode}")
        sys.exit(2)

    print(f"\n=== {_passed} passed, {_failed} failed ===")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
