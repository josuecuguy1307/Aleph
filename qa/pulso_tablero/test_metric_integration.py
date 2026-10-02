"""OLA PULSO §1 · INTEGRACIÓN — el CALL SITE del assembler emite 'metric' de verdad.
El unit (test_metric_event.py) prueba el normalizador aislado. Esto prueba el CABLEADO:
un assemble_and_run REAL (belt calc real por stdio, LLM stubbeado) donde el workdir tiene
un convergence.json → tras EXECUTE, on_event recibe un evento 'metric' por iteración.
Prueba que el call site (recipe_assembler tras tool_call_finished) se alcanza, lee
child_env['PUPPET_WORKDIR'] y emite. Reusa el patrón de test_gate_in_path.
Correr:  python3 qa/pulso_tablero/test_metric_integration.py
"""
import json, os, sys, tempfile, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "platform" / "assembler"))
import recipe_assembler as ra                         # noqa: E402
from test_gate_in_path import _recipe, _stub_chat_calling, REPO_ROOT  # noqa: E402

_fails = []
def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond: _fails.append(msg)

# workdir con un convergence.json ya escrito (como lo deja un hero belt tras iterar)
wd = tempfile.mkdtemp(prefix="pulso-int-")
json.dump({
    "type": "convergence", "title": "Quant", "task_id": "q1",
    "metric": {"name": "Sharpe", "unit": "", "goal": "max", "limit": 1.2},
    "limit": 1.2,
    "iterations": [
        {"n": 1, "value": 0.7, "passed": False, "curve": [1, 2]},
        {"n": 2, "value": 1.35, "passed": True},
    ],
}, open(os.path.join(wd, "convergence.json"), "w"))

events = []
orig = ra._asm._chat
ra._asm._chat = _stub_chat_calling("add", {"a": 2, "b": 3})   # el cerebro llama 'add' una vez
try:
    out = ra.assemble_and_run(_recipe({"calc": ["add", "mul"]}), "sumá 2 y 3",
                              repo_root=REPO_ROOT, approve=lambda s, t, p: True,   # EXECUTE real
                              workdir=wd, on_event=events.append)
finally:
    ra._asm._chat = orig

# la tool corrió de verdad (5 = 2+3) → el call site del metric se alcanzó tras EXECUTE
tc = next((t for t in out.get("tool_calls", []) if t["tool"] == "add"), {})
check("5" in str(tc.get("result", "")), "la tool 'add' EJECUTÓ (5) → el path post-EXECUTE se recorrió")

metrics = [e for e in events if e.get("type") == "metric"]
check(len(metrics) == 2, f"2 iteraciones en convergence.json → 2 eventos 'metric' emitidos (got {len(metrics)})")
if len(metrics) == 2:
    m0, m1 = metrics[0], metrics[1]
    check(m0["iteration"] == 1 and m0["value"] == 0.7, "metric#1 = iter 1, value 0.7 (real del archivo)")
    check(m1["iteration"] == 2 and m1["value"] == 1.35, "metric#2 = iter 2, value 1.35")
    check(m0["target"] == 1.2 and m0["goal"] == "max", "target=1.2 + goal=max (del núcleo común)")
    check(m1["passed"] is True, "passed real del archivo se propaga")
    check(m0["kind"] == "loop", "kind='loop' (marca del evento de Pulso)")

# el evento 'metric' viaja por el MISMO on_event que el resto del espinazo (mismo canal SSE)
check(any(e.get("type") == "tool_call_finished" for e in events), "el stream también trae tool_call_finished (canal compartido intacto)")

print()
if _fails: print(f"RESULT: {len(_fails)} FAIL"); sys.exit(1)
print("RESULT: ALL GREEN")
