#!/usr/bin/env python3
"""
selftest_loop.py — DELIVERABLE de FASE 5: el loop usuario→agente, COMPLETO.

Prueba, SIN depender de Postgres ni de un server HTTP (corre el runner en-proceso con
puppet_id=None → no registra en DB pero ejerce TODO el resto), que:

  1. INSPECCIÓN GATEADA con OK: recon → tool sintetizada → belt persistido (durable) →
     ejecución gateada → la tool se INVOCA de verdad y el ECO queda FRENADO POR SAFETY
     (decisión de dueños 2026-06-21 · opción B): el fixture corre en loopback y `guard_replay`
     (T9) mantiene política pública estricta de ESCRITURA — replay-write a interno/loopback se
     rechaza (anti-SSRF), eco honesto-refused. Contra software REAL externo el eco sí ejecuta.
     Y que el events.jsonl trae la secuencia completa de tipos del contrato (§4.4).
  2. INSPECCIÓN SIN OK: la tool write NO toca el mundo → gate.held, sin eco.
  3. HEALTH-CHECK de DRIFT: re-observar el MISMO software → healthy; re-observar el
     software CAMBIADO (campo renombrado + endpoint movido) → drift detectado y la tool
     RE-FORJADA (versión+1).

La registración en el puppet (recipe.belt_refs) + el authz + el SSE en vivo se prueban
aparte contra el server (ver el e2e HTTP); acá blindamos la lógica del motor en CI.

Uso:  python platform/inspection/selftest_loop.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[1]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

import shutil

from inspection.bridge import _DEFAULT_ESPACIOS
from inspection.fixtures.demos.attendance_drift import demo as drift_demo
from inspection.inspect_run import run_inspection, re_inspect
from inspection.registry import belt_dir_for

_SPACES = ("selftest-loop-ok", "selftest-loop-held", "selftest-drift-ok", "selftest-drift-yes")


def _clean() -> None:
    """Estado limpio: cada corrida es determinística (la re-forja de drift versiona)."""
    for sid in _SPACES:
        shutil.rmtree(Path(_DEFAULT_ESPACIOS) / sid, ignore_errors=True)
    shutil.rmtree(belt_dir_for(None, "registrar-asistencia"), ignore_errors=True)


def _events(space_id: str) -> list[dict]:
    path = Path(_DEFAULT_ESPACIOS) / space_id / "events.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _types(space_id: str) -> list[str]:
    return [e["type"] for e in _events(space_id)]


async def _run() -> bool:
    _clean()
    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    # ── 1) inspección gateada CON OK ────────────────────────────────────────────
    sid1 = "selftest-loop-ok"
    r1 = await run_inspection(space_id=sid1, puppet_id=None, user_id=None, auto_approve=True,
                              pace_ms=0)
    types1 = _types(sid1)
    need = ["software.detectado", "inspeccion.analizando", "accion.observada",
            "tool.sintetizada", "tool.equipada", "tool_call", "gate.approved", "eco",
            "cost", "closed"]
    print("\n[1] inspección CON OK →", types1)
    check("secuencia completa de eventos del contrato", all(t in types1 for t in need))
    check("el belt sintetizado quedó persistido (durable)", Path(r1["spec_path"]).exists())
    # [seam T4↔T9 · opción B 2026-06-21] el fixture es loopback → guard_replay (política pública
    # estricta de escritura) FRENA el eco-write. Es el comportamiento CORRECTO: contra software
    # real externo el eco ejecutaría. Verificamos que la tool se INVOCÓ y que el freno es de safety.
    check("la tool se INVOCÓ de verdad (gate aprobó, tool_call no-dry)",
          r1.get("gated") == "approved"
          and any(e.get("type") == "tool_call" and e.get("dry_run") is False for e in _events(sid1)))
    check("ECO frenado por SAFETY en loopback (replay-write estricto T9, no replay ciego al interno)",
          r1.get("eco_refused") is True and r1.get("eco_by") == "safety")
    check("emitió COST-EVENT por call (§4.6)", types1.count("cost") >= 2)

    # ── 2) inspección SIN OK: la tool write se retiene ──────────────────────────
    sid2 = "selftest-loop-held"
    r2 = await run_inspection(space_id=sid2, puppet_id=None, user_id=None, auto_approve=False,
                              pace_ms=0)
    types2 = _types(sid2)
    print("\n[2] inspección SIN OK →", [t for t in types2 if t in ("gate.held", "eco", "tool_call")])
    check("gate.held: la tool write NO tocó el mundo sin OK", "gate.held" in types2)
    check("sin OK no hay eco (no se ejecutó)", "eco" not in types2 and r2.get("gated") == "held")

    # ── 3) health-check de drift ────────────────────────────────────────────────
    belt_ref = r1["belt_ref"]
    print("\n[3] health-check sobre", Path(belt_ref).name)
    hc_ok = await re_inspect(space_id="selftest-drift-ok", belt_ref=belt_ref,
                             fixture_drift=False, auto_resynth=True)
    check("MISMO software → healthy (sin drift)", hc_ok.get("healthy") is True and hc_ok.get("action") == "healthy")
    hc_drift = await re_inspect(space_id="selftest-drift-yes", belt_ref=belt_ref,
                                demo=drift_demo, fixture_drift=True, auto_resynth=True)
    check("software CAMBIADO → drift detectado", hc_drift.get("drift") is True)
    check("la tool fue RE-FORJADA (versión+1)",
          hc_drift.get("action") == "resynthesized" and hc_drift.get("version") == 2)
    fa = set(hc_drift.get("fields_added") or [])
    fr = set(hc_drift.get("fields_removed") or [])
    check("el diff captura el campo renombrado (codigo→matricula)",
          "matricula" in fa and "codigo" in fr)

    print(f"\n[loop] {'OK ✅' if ok else 'FALLÓ ❌'}")
    return ok


def main() -> int:
    return 0 if asyncio.run(_run()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
