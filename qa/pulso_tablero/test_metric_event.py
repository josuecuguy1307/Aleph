"""OLA PULSO §1 · unit del normalizador del evento de métrica.
Prueba las invariantes de HONESTIDAD del backend (sin motor, sin red):
  - un evento 'metric' por iteración NUEVA (delta; cero duplicados al re-leer)
  - deriva `passed` cuando el belt no lo escribe (electronica)
  - usa el `limit` top-level cuando falta metric.limit (fem)
  - sin convergence.json → CERO eventos (vacío honesto)
  - JSON truncado/corrupto → CERO eventos, sin crash (nunca tumba el run)
Correr:  python3 qa/pulso_tablero/test_metric_event.py
"""
import json, os, sys, tempfile, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "platform" / "assembler"))  # flat imports (convención del repo)
from recipe_assembler import (  # noqa: E402
    _emit_metric_events, _read_convergence, _derive_passed,
)

_fails = []
def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)

def _collect(workdir, hi):
    """Corre el emisor capturando los eventos en una lista."""
    got = []
    _emit_metric_events(got.append, workdir, hi, turn=1)
    return got

def _write(workdir, obj):
    with open(os.path.join(workdir, "convergence.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f)

# ── Caso 1 · finanzas (Sharpe ↑, goal max, tiene passed + task_id) ────────────
with tempfile.TemporaryDirectory() as wd:
    hi = {}
    _write(wd, {
        "type": "convergence", "title": "Quant", "task_id": "t1",
        "metric": {"name": "Sharpe", "unit": "", "goal": "max", "limit": 1.2},
        "limit": 1.2,
        "iterations": [
            {"n": 1, "value": 0.8, "passed": False, "curve": [1, 2]},
            {"n": 2, "value": 1.1, "passed": False},
        ],
    })
    ev = _collect(wd, hi)
    check(len(ev) == 2, f"finanzas: 2 iters → 2 eventos (got {len(ev)})")
    check(all(e["type"] == "metric" for e in ev), "finanzas: type=metric")
    check(ev[0]["value"] == 0.8 and ev[1]["value"] == 1.1, "finanzas: values reales en orden")
    check(ev[0]["target"] == 1.2 and ev[0]["goal"] == "max", "finanzas: target+goal reales")
    check(ev[1]["passed"] is False, "finanzas: passed real del archivo")

    # crece a 3 iters → SOLO 1 evento nuevo (delta, cero duplicado)
    _write(wd, {
        "type": "convergence", "title": "Quant", "task_id": "t1",
        "metric": {"name": "Sharpe", "unit": "", "goal": "max", "limit": 1.2},
        "limit": 1.2,
        "iterations": [
            {"n": 1, "value": 0.8, "passed": False},
            {"n": 2, "value": 1.1, "passed": False},
            {"n": 3, "value": 1.35, "passed": True},
        ],
    })
    ev2 = _collect(wd, hi)
    check(len(ev2) == 1 and ev2[0]["iteration"] == 3, f"delta: solo la iter 3 nueva (got {len(ev2)})")
    check(ev2[0]["passed"] is True, "delta: passed=True cuando cruza el target")

# ── Caso 2 · electronica (atten dB ↓, goal min, SIN passed) → derivar ─────────
with tempfile.TemporaryDirectory() as wd:
    _write(wd, {
        "type": "convergence", "title": "Filtro", "task_id": "e1",
        "metric": {"name": "Atenuación@fc", "unit": "dB", "goal": "min", "limit": 3.0},
        "limit": 3.0,
        "iterations": [
            {"n": 1, "value": 6.5, "measured_fc_hz": 1000, "note": "x"},  # 6.5 > 3.0 → NO pasa
            {"n": 2, "value": 2.1, "measured_fc_hz": 1000, "note": "y"},  # 2.1 <= 3.0 → pasa
        ],
    })
    ev = _collect(wd, {})
    check(len(ev) == 2, f"electronica: 2 eventos (got {len(ev)})")
    check(ev[0]["passed"] is False, "electronica: derive passed=False (6.5>3.0, goal min)")
    check(ev[1]["passed"] is True, "electronica: derive passed=True (2.1<=3.0, goal min)")

# ── Caso 3 · fem (von Mises ↓, SIN metric.limit interno; usa top-level limit) ──
with tempfile.TemporaryDirectory() as wd:
    _write(wd, {
        "type": "convergence", "title": "Viga",
        "metric": {"name": "obra.fem.metric_von_mises", "unit": "MPa", "goal": "min"},
        "limit": 250.0,
        "iterations": [{"n": 1, "value": 310.0, "passed": False}],
    })
    ev = _collect(wd, {})
    check(len(ev) == 1 and ev[0]["target"] == 250.0, "fem: target del limit top-level (metric.limit ausente)")
    check(ev[0]["unit"] == "MPa" and ev[0]["name"].startswith("obra.fem"), "fem: name(i18n-key)+unit pasan crudos")

# ── Caso 4 · sin convergence.json → CERO eventos (vacío honesto) ──────────────
with tempfile.TemporaryDirectory() as wd:
    ev = _collect(wd, {})
    check(ev == [], "sin archivo → 0 eventos (nada inventado)")
    check(_read_convergence(wd) is None, "sin archivo → _read_convergence None")
    check(_read_convergence(None) is None, "workdir None → None")

# ── Caso 5 · JSON truncado/corrupto → 0 eventos, sin crash ────────────────────
with tempfile.TemporaryDirectory() as wd:
    with open(os.path.join(wd, "convergence.json"), "w") as f:
        f.write('{"type":"convergence","iterations":[{"n":1,"value":1.0')  # truncado
    ev = _collect(wd, {})  # no debe lanzar
    check(ev == [], "JSON truncado → 0 eventos, sin crash")

# ── Caso 6 · type != convergence → ignorado (no es un archivo de loop) ─────────
with tempfile.TemporaryDirectory() as wd:
    _write(wd, {"type": "otra_cosa", "iterations": [{"n": 1, "value": 1}]})
    check(_collect(wd, {}) == [], "type!=convergence → ignorado")

# ── _derive_passed directo ────────────────────────────────────────────────────
check(_derive_passed(1.5, 1.2, "max") is True, "derive max: 1.5>=1.2 True")
check(_derive_passed(1.0, 1.2, "max") is False, "derive max: 1.0>=1.2 False")
check(_derive_passed(2.0, 3.0, "min") is True, "derive min: 2.0<=3.0 True")
check(_derive_passed(None, 3.0, "min") is None, "derive: value None → None")
check(_derive_passed(2.0, None, "min") is None, "derive: target None → None")
# review-fix (LOW #3): goal no canónico NO debe inventar un veredicto pass/fail
check(_derive_passed(5.0, 3.0, "maximize") is None, "derive: goal desconocido → None (no fabrica pass)")
check(_derive_passed(5.0, 3.0, "") is None, "derive: goal vacío → None")

print()
if _fails:
    print(f"RESULT: {len(_fails)} FAIL")
    sys.exit(1)
print("RESULT: ALL GREEN")
