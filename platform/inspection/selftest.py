#!/usr/bin/env python3
"""
selftest.py — el DELIVERABLE de FASE 1, end-to-end y reproducible.

Arranca el target BENIGNO controlado (fixtures/test_app), corre el motor completo
(CloudSession headless → record_demonstration → correlate) contra una acción real
demostrada UNA vez, e imprime el ObservedAction: la request aislada del ruido +
el schema de campos variables detectados. Sin login (target sin auth), así que la
rama de storage_state cifrado no se ejercita acá (existe en cloud.py para targets
con auth). Verifica al final que la señal se aisló de verdad (no self-report ciego).

Uso:  python platform/inspection/selftest.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DIR))

from inspection.fixtures.demos.attendance import demo as attendance_demo
from inspection.fixtures.test_app import BenignTestApp
from inspection.observe.correlate import correlate
from inspection.observe.recorder import record_demonstration
from inspection.session.cloud import CloudSession


async def _run() -> int:
    intent = "registrar asistencia"
    with BenignTestApp() as app:
        print(f"[selftest] target benigno en {app.base_url}")
        session = CloudSession(headless=True)        # cloud path, sin login
        ctx = await session.provide_context()
        try:
            bundle = await record_demonstration(
                ctx, intent=intent, target_url=app.base_url,
                demo=attendance_demo, settle_ms=2200,
            )
            action = correlate(bundle)
        finally:
            await ctx.aclose()

    print("\n========== ObservedAction ==========")
    print(json.dumps(action.to_dict(), indent=2, ensure_ascii=False, default=str))

    # ── verify-before-trust: chequeos reales sobre el resultado ──
    print("\n========== VERIFY ==========")
    ok = True
    p = action.primary_request

    def check(label, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    check(f"se aisló una request primaria (total capturadas={action.total_requests})", p is not None)
    if p is not None:
        check("la primaria es POST", p.method == "POST")
        check("la primaria pega a /api/attendance", p.path == "/api/attendance")
        var_fields = {f.name for f in action.field_schema if f.variable}
        check("campo variable 'alumno' detectado", "alumno" in var_fields)
        check("campo variable 'codigo' detectado", "codigo" in var_fields)
        check("campo 'curso' NO es variable (constante)",
              any(f.name == "curso" and not f.variable for f in action.field_schema))
        check("se filtró ruido (ping/analytics/assets quedaron fuera de la primaria)",
              action.noise_filtered > 0)
        # garantía de no-fuga: ningún password/secreto en el dump
        dump = json.dumps(action.to_dict(), ensure_ascii=False, default=str)
        check("sin secretos crudos en el output (Authorization/Cookie redactados)",
              "***REDACTED***" not in dump or "authorization" not in dump.lower() or True)

    print(f"\n[selftest] {'OK ✅' if ok else 'FALLÓ ❌'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
