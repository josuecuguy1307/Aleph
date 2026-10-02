#!/usr/bin/env python3
"""
test_executor.py — RUN-EXECUTOR: el glue que corre un puppet E2E por el path de PROD.

Cubre lo que el executor AGREGA sobre Fundación (el assembler y la persistencia ya
tienen sus propios suites): que el run record del assembler se convierte en la
trayectoria del moat (los 5 campos), y que run_puppet_e2e orquesta el orden mandado
(crear run → assemble_and_run → persistir instrumentation_logs → finish_run) ligando
todo por run_id, SIN tocar Postgres ni el LLM en este suite (conexión y assembler
stubbeados — el cableado es lo que se prueba; el E2E real vivo se demostró aparte).

Run: python3 -m pytest app/phase1/test_executor.py  (o ejecutar directo)
"""

from __future__ import annotations

import sys
from pathlib import Path

# permitir 'app.phase1...' tanto bajo pytest como ejecución directa
_BACKEND = Path(__file__).resolve().parents[2]  # product/backend (donde vive el paquete app)
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.phase1 import executor

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    mark = "PASS" if cond else "FAIL"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


# ── 1. el run record del assembler → trayectoria del moat (campo 3) ─────────────
def test_trajectory_from_record():
    record = {
        "model_route": [
            {"model": "qwen3:8b", "tier": "primary", "ok": True},
            {"model": "qwen3:8b", "tier": "primary", "ok": True},
        ],
        "tool_calls": [
            {"tool": "units_check", "gate_action": "execute",
             "result": "[tool error] DimensionalityError"},
            {"tool": "create_workbook", "gate_action": "needs_ok",
             "result": "[gate: requiere tu OK...]"},
        ],
    }
    traj = executor.build_trajectory_from_record(record)
    kinds = [s["kind"] for s in traj]
    check("1.1 trayectoria tiene 2 model_calls + 2 tool_calls (orden del loop)",
          kinds == ["model_call", "model_call", "tool_call", "tool_call"],
          f"kinds={kinds}")
    check("1.2 los seq son consecutivos 1..4",
          [s["seq"] for s in traj] == [1, 2, 3, 4])
    uc = next(s for s in traj if s["name"] == "units_check")
    check("1.3 tool ejecutada con error de tool → error reflejado en la trayectoria",
          uc["error"] is not None and "DimensionalityError" in uc["error"]
          and uc["gate_decision"] == "execute", f"step={uc}")
    cw = next(s for s in traj if s["name"] == "create_workbook")
    # [GATE 3 · obra 5] CAMBIO DE VEREDICTO, DECLARADO. Antes: `error == "gate:needs_ok"`.
    # El acta de persona usuaria (2026-08-06) sella que EL GATE ES PROTECCIÓN, NO FALLO: el moat contaba
    # el freno del gate como una falla del run. Se registra igual —la acción no se pierde— pero
    # firmada en `retenida`, con el MISMO criterio que instrumentation.build_trayectoria.
    check("1.4 tool retenida por el gate (needs_ok) → PROTECCIÓN: retenida=True y error=None",
          cw["error"] is None and cw["retenida"] is True
          and cw["gate_decision"] == "needs_ok", f"step={cw}")
    check("1.4b la que SÍ falló sigue siendo error (retenida=False)",
          uc["retenida"] is False and uc["error"] is not None, f"step={uc}")


# ── 2. model_call fallido (routing) se refleja como error en la trayectoria ─────
def test_trajectory_marks_routing_failure():
    record = {
        "model_route": [
            {"model": "oss-primary", "tier": "primary", "ok": False, "error": "timeout"},
            {"model": "frontier-fb", "tier": "fallback", "ok": True, "reason": "primary failed"},
        ],
        "tool_calls": [],
    }
    traj = executor.build_trajectory_from_record(record)
    p = traj[0]
    fb = traj[1]
    check("2.1 model_call primary fallido → error='timeout'",
          p["error"] == "timeout" and p["tier"] == "primary", f"step={p}")
    check("2.2 fallback ok → sin error, tier=fallback",
          fb["error"] is None and fb["tier"] == "fallback", f"step={fb}")


# ── 3. orquestación E2E con conexión y assembler stubbeados (cableado puro) ─────
def test_run_e2e_orchestration_order():
    calls = {"create_run": 0, "assemble": 0, "persist": 0, "finish": [],
             "closed": 0, "commits": 0, "order": []}

    class FakeConn:
        def commit(self):
            calls["commits"] += 1
            calls["order"].append("commit")

        def close(self):
            calls["closed"] += 1

    fake_record = {
        "ok": True, "answer": "listo", "gate_enforced": True, "error": None,
        "belt": {"slug": "test"}, "tools_cabled": ["t1"], "tools_dropped": [],
        "gate_decisions": [{"tool": "t1", "server": "s", "action": "execute"}],
        "model_final": "oss", "tool_calls": [{"tool": "t1", "gate_action": "execute", "result": "ok"}],
        "model_route": [{"model": "oss", "tier": "primary", "ok": True}],
    }

    # stub repo
    orig_create = executor.phase1_repo.create_run
    orig_finish = executor.phase1_repo.finish_run
    orig_persist = executor.instr.persist_run
    orig_asm = executor._asm

    def fake_create_run(conn, **kw):
        calls["create_run"] += 1
        return {"id": "RUN-123"}

    def fake_finish_run(conn, run_id, status="done"):
        calls["finish"].append((run_id, status))
        return {"id": run_id, "status": status}

    def fake_persist(conn, *, run_id, intent, belt, trayectoria, senal=None, costo=None):
        calls["persist"] += 1
        # el moat liga por run_id; verificamos que llega el run_id creado y los 5 campos
        calls["persist_run_id"] = run_id
        calls["persist_belt_has_recipe"] = "recipe" in belt and "resolved_belt" in belt
        calls["persist_traj_len"] = len(trayectoria)
        return 999

    class FakeAsm:
        def assemble_and_run(self, recipe, prompt, **kw):
            calls["assemble"] += 1
            calls["order"].append("model_io")
            calls["assemble_repo_root"] = kw.get("repo_root")
            return fake_record

    executor.phase1_repo.create_run = fake_create_run
    executor.phase1_repo.finish_run = fake_finish_run
    executor.instr.persist_run = fake_persist
    executor._asm = lambda: FakeAsm()
    try:
        out = executor.run_puppet_e2e(
            {"schema_version": "v1"}, "hacé algo", conn=FakeConn(),
        )
    finally:
        executor.phase1_repo.create_run = orig_create
        executor.phase1_repo.finish_run = orig_finish
        executor.instr.persist_run = orig_persist
        executor._asm = orig_asm

    check("3.1 creó el run ANTES de correr (run_id es el ligador)",
          calls["create_run"] == 1 and out["run_id"] == "RUN-123")
    check("3.2 corrió assemble_and_run (enforcer en el path) con repo_root",
          calls["assemble"] == 1 and calls.get("assemble_repo_root") is not None
          and calls["commits"] >= 1
          and calls["order"].index("commit") < calls["order"].index("model_io"),
          f"order={calls['order']}")
    check("3.3 persistió instrumentation_logs ligado por el MISMO run_id, con belt+trayectoria",
          calls["persist"] == 1 and calls.get("persist_run_id") == "RUN-123"
          and calls.get("persist_belt_has_recipe") is True
          and calls.get("persist_traj_len") == 2,
          f"persist_run_id={calls.get('persist_run_id')} traj_len={calls.get('persist_traj_len')}")
    check("3.4 cerró el run como done (ok=True)",
          calls["finish"] == [("RUN-123", "done")])
    check("3.5 devolvió evidencia (record + ids), no un ✓ pelado",
          out["ok"] is True and out["instrumentation_log_id"] == 999
          and out["record"] is fake_record and out["gate_enforced"] is True)


# ── 4. si assemble falla, el run NO queda colgado en 'running' ──────────────────
def test_run_e2e_error_finishes_run():
    calls = {"finish": [], "commits": 0}

    class FakeConn:
        def commit(self):
            calls["commits"] += 1

        def close(self):
            pass

    orig_create = executor.phase1_repo.create_run
    orig_finish = executor.phase1_repo.finish_run
    orig_asm = executor._asm

    executor.phase1_repo.create_run = lambda conn, **kw: {"id": "RUN-ERR"}
    executor.phase1_repo.finish_run = lambda conn, rid, status="done": calls["finish"].append((rid, status))

    class BoomAsm:
        def assemble_and_run(self, *a, **k):
            raise RuntimeError("boom interno")

    executor._asm = lambda: BoomAsm()
    try:
        out = executor.run_puppet_e2e({"schema_version": "v1"}, "x", conn=FakeConn())
    finally:
        executor.phase1_repo.create_run = orig_create
        executor.phase1_repo.finish_run = orig_finish
        executor._asm = orig_asm

    check("4.1 ante excepción interna devuelve ok=False con error tipado",
          out["ok"] is False and "executor:" in str(out["error"]), f"out.error={out['error']}")
    check("4.2 el run NO queda colgado: se cierra como 'error'",
          ("RUN-ERR", "error") in calls["finish"], f"finish={calls['finish']}")


def main():
    print("=== executor (RUN-EXECUTOR) — glue del path de PROD (cableado) ===\n")
    test_trajectory_from_record()
    test_trajectory_marks_routing_failure()
    test_run_e2e_orchestration_order()
    test_run_e2e_error_finishes_run()
    print(f"\n=== {_passed} passed, {_failed} failed ===")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
