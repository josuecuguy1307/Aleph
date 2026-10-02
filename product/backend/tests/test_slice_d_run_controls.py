"""Focused Slice D regressions for streaming model controls and managed CLI SSE."""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.phase1 import stream_chat
from app.phase1.router import build_phase1_router


ROOT = Path(__file__).resolve().parents[3]
ASM = ROOT / "platform" / "assembler"
if str(ASM) not in sys.path:
    sys.path.insert(0, str(ASM))

from cli_brain.base import BrainResult  # noqa: E402
from cli_brain import server as cli_server  # noqa: E402


def _cli_recipe(effort: str = "auto") -> dict:
    return {
        "model": {
            "primary": "claude-code-cli",
            "base_url": "http://127.0.0.1:8926/v1",
            "max_tokens": 700,
            "temperature": 0,
            "max_turns": 16,
            "brain_provider": "claude_cli",
            "cli_model": "sonnet",
            "effort": effort,
        },
        "framing": {"inline": "Mantén las citas."},
    }


def _valid_saved_recipe() -> dict:
    recipe = _cli_recipe("max")
    recipe.update({
        "schema_version": "v1",
        "meta": {"name": "Slice D", "nicho": "test"},
        "belt": {"belt_ref": "fixture", "tool_filters": {"calc": ["add"]}},
        "rag": {"enabled": False},
        "keys": {},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    })
    recipe["model"]["max_turns"] = 2
    recipe["framing"]["inline"] = "Responde breve y directo. Mantén citas."
    return recipe


def test_saved_recipe_override_reaches_full_executor_and_stays_owner_gated(
        monkeypatch, tmp_path: Path) -> None:
    from app.phase1 import billing, executor, repo

    owner = "slice-d-owner"
    token = repo.mint_session(owner)
    captured = {}

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(repo, "get_puppet", lambda conn, puppet_id: {
        "id": puppet_id, "owner_id": owner, "config": _valid_saved_recipe(),
    })
    monkeypatch.setattr(billing, "preflight", lambda conn, user_id: {"allowed": True})
    monkeypatch.setattr(billing, "record_run_cost", lambda *args, **kwargs: {"ingested": 0})

    def fake_run(recipe, prompt, **kwargs):
        captured.update(recipe=recipe, prompt=prompt, kwargs=kwargs)
        return {"ok": True, "answer": "ok", "run_id": "run-slice-d", "cost_events": []}

    monkeypatch.setattr(executor, "run_puppet_e2e", fake_run)
    app = FastAPI()
    app.include_router(build_phase1_router(
        get_conn=FakeConn,
        events_dir=lambda: tmp_path,
    ))
    client = TestClient(app)
    recipe = _valid_saved_recipe()
    payload = {
        "puppet_id": "saved-slice-d",
        "user_id": owner,
        "recipe": recipe,
        "prompt": "audita",
    }
    response = client.post(
        "/v1/puppets/run", json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    assert captured["recipe"]["model"]["cli_model"] == "sonnet"
    assert captured["recipe"]["model"]["effort"] == "max"
    assert captured["recipe"]["model"]["max_turns"] == 2
    assert captured["recipe"]["framing"]["inline"].startswith("Responde breve")
    assert captured["kwargs"]["puppet_id"] == "saved-slice-d"

    anonymous = dict(payload)
    anonymous.pop("user_id")
    denied = client.post("/v1/puppets/run", json=anonymous)
    assert denied.status_code == 401


def test_stream_forwards_cli_submodel_and_resolves_auto_effort(monkeypatch) -> None:
    seen = []

    monkeypatch.setattr(stream_chat, "_system_content", lambda recipe: recipe["framing"]["inline"])
    monkeypatch.setattr(stream_chat, "_resolve_llm_key", lambda recipe, resolver: ("", False))

    def fake_stream(base_url, model, key, system, prompt, max_tokens, temperature,
                    cli_model=None, effort=None):
        seen.append({
            "base_url": base_url,
            "model": model,
            "system": system,
            "cli_model": cli_model,
            "effort": effort,
        })
        yield ("token", "ok")

    monkeypatch.setattr(stream_chat, "_stream_openai", fake_stream)

    assert list(stream_chat.stream_answer(_cli_recipe(), "hola", method_active=False)) == [("token", "ok")]
    assert seen[-1] == {
        "base_url": "http://127.0.0.1:8926/v1",
        "model": "claude-code-cli",
        "system": "Mantén las citas.",
        "cli_model": "sonnet",
        "effort": "low",
    }

    list(stream_chat.stream_answer(_cli_recipe(), "hola", method_active=True))
    assert seen[-1]["effort"] == "high"

    explicit = _cli_recipe("max")
    list(stream_chat.stream_answer(explicit, "hola"))
    assert seen[-1]["effort"] == "max"


def test_stream_does_not_leak_cli_controls_to_regular_provider(monkeypatch) -> None:
    seen = {}
    recipe = _cli_recipe("high")
    recipe["model"].update({
        "primary": "openai/gpt-oss-120b",
        "base_url": "https://api.groq.com/openai/v1",
    })
    monkeypatch.setattr(stream_chat, "_system_content", lambda recipe: "framing")
    monkeypatch.setattr(stream_chat, "_resolve_llm_key", lambda recipe, resolver: ("key", False))

    def fake_stream(*args, **kwargs):
        seen.update(kwargs)
        yield ("token", "ok")

    monkeypatch.setattr(stream_chat, "_stream_openai", fake_stream)
    assert list(stream_chat.stream_answer(recipe, "hola")) == [("token", "ok")]
    assert seen == {"cli_model": None, "effort": None}


def test_openai_stream_http_payload_contains_cli_controls(monkeypatch) -> None:
    captured = {}
    monkeypatch.setenv("PUPPET_CLI_BRAIN_TIMEOUT", "180")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            chunk = {"choices": [{"delta": {"content": "ok"}}]}
            return iter([f"data: {json.dumps(chunk)}\n".encode(), b"data: [DONE]\n"])

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(stream_chat.urllib.request, "urlopen", fake_urlopen)
    result = list(stream_chat._stream_openai(
        "http://127.0.0.1:8926/v1", "claude-code-cli", "", "sistema", "hola",
        700, 0, cli_model="sonnet", effort="high"))
    assert result == [("token", "ok")]
    assert captured["body"]["stream"] is True
    assert captured["body"]["cli_model"] == "sonnet"
    assert captured["body"]["effort"] == "high"
    assert captured["timeout"] >= 210


def test_managed_cli_server_emits_real_sse_and_forwards_controls(monkeypatch) -> None:
    captured = {}

    class FakeProvider:
        provider_id = "claude_cli"
        display_name = "Claude Code"
        response_model_id = "claude-code-cli"

        def invoke(self, prompt, model=None, effort=None):
            captured.update(prompt=prompt, model=model, effort=effort)
            return BrainResult(
                ok=True,
                text="respuesta real",
                model_final="claude-sonnet-real",
                model_final_source="cli-reported",
                usage={"prompt_tokens": 7, "completion_tokens": 2},
            )

    monkeypatch.setattr(cli_server, "get_provider", lambda model_id: FakeProvider())
    server = cli_server.create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = {
            "model": "claude-code-cli",
            "stream": True,
            "messages": [{"role": "user", "content": "hola"}],
            "cli_model": "sonnet",
            "effort": "high",
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            body = response.read().decode()
            assert response.headers.get_content_type() == "text/event-stream"
        assert captured["model"] == "sonnet"
        assert captured["effort"] == "high"
        assert "respuesta real" in body
        assert '"model": "claude-sonnet-real"' in body
        assert "data: [DONE]" in body
        assert '"reasoning"' not in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
