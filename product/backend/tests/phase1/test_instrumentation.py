"""
test_instrumentation.py — el pipeline liga los 5 campos por run_id (campo 3 desde el
events.jsonl del loop). La parte que toca Postgres está en test_db_integration.py.
"""

import importlib.util
from pathlib import Path

from app.phase1 import instrumentation as instr

REPO_ROOT = Path(__file__).resolve().parents[4]
ER_PY = REPO_ROOT / "platform" / "flywheel" / "events_replay.py"


def test_build_trayectoria_from_events():
    # eventos con datos planos (forma de session.py) y anidados (forma events_replay).
    events = [
        {"id": 1, "type": "belt_ready", "payload": {"servers": ["echo"]}},
        {"id": 2, "type": "turn_started", "payload": {"turn": 1}},
        {"id": 3, "type": "tool_call_finished", "tool": "echo", "result": "hola",
         "wall_s": 0.12, "gate_decision": "OK"},
        {"id": 4, "type": "turn_started", "payload": {"turn": 2}},
        {"id": 5, "type": "final", "payload": {"answer": "ok"}},
    ]
    traj = instr.build_trayectoria(events)
    kinds = [s["kind"] for s in traj]
    # 2 model_call (los 2 turn_started) + 1 tool_call.
    assert kinds == ["model_call", "tool_call", "model_call"]
    tool_step = traj[1]
    assert tool_step["name"] == "echo"
    assert tool_step["latency_ms"] == 120  # wall_s 0.12 → 120ms
    assert tool_step["error"] is None
    assert tool_step["gate_decision"] == "OK"
    # secuencia contigua
    assert [s["seq"] for s in traj] == [1, 2, 3]


def test_gate_retenida_es_proteccion_no_error():
    """[GATE 3 · obra 5] CAMBIO DE VEREDICTO, DECLARADO.

    Este test fijaba `traj[0]["error"] == "gate:NO"` — o sea, fijaba EL BUG: `"NO"` no es un
    valor del gate. `GateDecision` declara `execute`/`needs_ok`/`blocked` y nada más
    (platform/gates/approval_gate.py:220-222), así que el fixture inventaba un vocabulario
    para que la rama que lo testeaba se pudiera alcanzar. Una vara verde que no medía nada.

    Lo que se fija ahora es el criterio del acta: una acción retenida por el gate es
    PROTECCIÓN, no un fallo. Se registra —antes ni siquiera aparecía— con `error=None` y
    `retenida=True`.
    """
    events = [
        {"id": 1, "type": "tool_call_finished", "payload": {"tool": "wire_money",
         "wall_s": 0.01, "gate_decision": "blocked", "result": "[gate: acción BLOQUEADA]"}},
    ]
    traj = instr.build_trayectoria(events)
    assert traj[0]["error"] is None
    assert traj[0]["retenida"] is True
    assert traj[0]["gate_decision"] == "blocked"


def test_gate_waiting_es_un_paso_de_la_trayectoria():
    """El emisor manda las decisiones NO-execute con `type:"gate_waiting"`
    (recipe_assembler.py:3304) y esta función sólo miraba `tool_call_finished`: una acción
    frenada por el gate NO EXISTÍA en la trayectoria (auditoría 4 §G-2)."""
    events = [
        {"id": 1, "type": "turn_started", "payload": {"turn": 1}},
        {"id": 2, "type": "gate_waiting", "tool": "send_email",
         "gate_decision": "needs_ok", "gate_action": "needs_ok", "executed": False,
         "causa": "gate_bloqueado", "origen": "aleph", "reintentable": False},
    ]
    traj = instr.build_trayectoria(events)
    assert [s["kind"] for s in traj] == ["model_call", "tool_call"]
    paso = traj[1]
    assert paso["name"] == "send_email"
    assert paso["retenida"] is True
    assert paso["error"] is None          # protección, no error
    assert paso["latency_ms"] is None     # no corrió: no hay latencia que inventar
    assert paso["causa"] == "gate_bloqueado"


def test_error_de_tool_real_sigue_siendo_error():
    """La contracara: lo que SÍ falló sigue registrándose como error, byte por byte."""
    events = [
        {"id": 1, "type": "tool_call_finished", "payload": {"tool": "units_check",
         "wall_s": 0.2, "gate_decision": "execute",
         "result": "[tool error] DimensionalityError"}},
    ]
    traj = instr.build_trayectoria(events)
    assert traj[0]["error"] == "[tool error] DimensionalityError"
    assert traj[0]["retenida"] is False


def test_trayectoria_from_real_events_file(tmp_path):
    # escribe un events.jsonl con la lib REAL del loop y lo reconstruye.
    spec = importlib.util.spec_from_file_location("er_t2", ER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    log = mod.EventLog(tmp_path / "events.jsonl")
    log.append({"type": "turn_started", "space_id": "sp", "payload": {"turn": 1}})
    log.append({"type": "tool_call_finished", "space_id": "sp",
                "payload": {"tool": "read_data_from_excel", "wall_s": 0.5,
                            "gate_decision": "OK", "result": "rows"}})
    traj = instr.trayectoria_from_file(tmp_path / "events.jsonl")
    assert len(traj) == 2
    assert traj[1]["name"] == "read_data_from_excel"
    assert traj[1]["latency_ms"] == 500


def test_build_signal_shape():
    sig = instr.build_signal(explicit="up", saved=True, edited=False, abandoned=False)
    assert sig["explicit"] == "up"
    assert sig["implicit"] == {"saved": True, "edited": False, "abandoned": False}


def test_build_cost_totals():
    cost = instr.build_cost(prompt_tokens=100, completion_tokens=50,
                            by_model={"gpt-oss-120b": 150})
    assert cost["total_tokens"] == 150
    assert cost["by_model"]["gpt-oss-120b"] == 150


def test_persist_run_requires_run_id():
    import pytest
    with pytest.raises(ValueError):
        instr.persist_run(None, run_id="", intent="x", belt={}, trayectoria=[])
