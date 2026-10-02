"""
test_event_stream.py — SSE sobre los eventos que el loop YA emite (token-cost CERO).
Verifica formato SSE, replay exacto con Last-Event-ID, tailing y corte en 'closed'.
Usa events_replay.EventLog (la fuente real) para escribir el log, igual que el loop.
"""

import importlib.util
import threading
import time
from pathlib import Path

import pytest

from app.phase1 import event_stream as es

REPO_ROOT = Path(__file__).resolve().parents[4]
ER_PY = REPO_ROOT / "platform" / "flywheel" / "events_replay.py"


def _load_event_log(path):
    spec = importlib.util.spec_from_file_location("er_test", ER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.EventLog(path)


def _write_sample(path, space_id="sp_test"):
    log = _load_event_log(path)
    log.append({"type": "belt_ready", "space_id": space_id,
                "payload": {"servers": ["echo"], "tools": ["echo"]}})
    log.append({"type": "turn_started", "space_id": space_id, "payload": {"turn": 1}})
    log.append({"type": "tool_call_finished", "space_id": space_id,
                "payload": {"tool": "echo", "result": "hola", "wall_s": 0.12,
                            "gate_decision": "OK"}})
    log.append({"type": "final", "space_id": space_id,
                "payload": {"answer": "listo", "turns_truncated": False}})
    return log


def test_format_sse_has_id_event_data(tmp_path):
    ev = {"id": 3, "type": "tool_call_finished", "space_id": "sp", "payload": {"tool": "echo"}}
    frame = es.format_sse(ev)
    assert "id: 3" in frame
    assert "event: tool_call_finished" in frame
    assert "data: " in frame
    assert frame.endswith("\n\n")


def test_replay_exact_from_last_event_id(tmp_path):
    log_path = tmp_path / "events.jsonl"
    _write_sample(log_path)
    # Last-Event-ID = 2 → exactamente {3, 4}, ni uno de más, ni uno de menos.
    got = es.replay_events(log_path, last_event_id=2)
    ids = [e["id"] for e in got]
    assert ids == [3, 4]


def test_replay_from_zero_is_full(tmp_path):
    log_path = tmp_path / "events.jsonl"
    _write_sample(log_path)
    got = es.replay_events(log_path, last_event_id=0)
    assert [e["id"] for e in got] == [1, 2, 3, 4]


def test_iter_catchup_and_stops_on_closed(tmp_path):
    log_path = tmp_path / "events.jsonl"
    log = _write_sample(log_path)
    log.append({"type": "closed", "space_id": "sp_test", "payload": {}})
    frames = list(es.iter_sse_events(log_path, last_event_id=0,
                                     idle_timeout_s=1.0, heartbeat_s=99))
    # debe contener los 5 eventos y CORTAR en closed (sin colgarse en el tail).
    data_frames = [f for f in frames if f.startswith("id:") or "event:" in f]
    assert any("event: belt_ready" in f for f in data_frames)
    assert any("event: closed" in f for f in data_frames)


def test_iter_tails_new_events(tmp_path):
    log_path = tmp_path / "events.jsonl"
    log = _write_sample(log_path)  # ids 1..4
    collected = []

    def consume():
        gen = es.iter_sse_events(log_path, last_event_id=4, poll_interval=0.05,
                                 idle_timeout_s=2.0, heartbeat_s=99)
        for frame in gen:
            collected.append(frame)
            if "event: closed" in frame:
                break

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    time.sleep(0.2)
    # el loop appendea un evento NUEVO mientras el stream está vivo → el tail lo emite.
    log.append({"type": "artifact_created", "space_id": "sp_test",
                "payload": {"artifact_id": "a1", "kind": "report"}})
    time.sleep(0.2)
    log.append({"type": "closed", "space_id": "sp_test", "payload": {}})
    t.join(timeout=3.0)
    assert any("event: artifact_created" in f for f in collected)
    assert any("event: closed" in f for f in collected)
