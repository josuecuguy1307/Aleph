"""Slice C · contrato de lifecycle del cerebro CLI dentro del desktop."""
from __future__ import annotations

import os
import json
import socket
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ASM = ROOT / "platform" / "assembler"
if str(ASM) not in sys.path:
    sys.path.insert(0, str(ASM))

from cli_brain.base import _run_managed, sanitized_env, terminate_active_processes  # noqa: E402
from cli_brain.claude_cli import ClaudeCliProvider  # noqa: E402
from cli_brain.codex_cli import CodexCliProvider  # noqa: E402
from cli_brain.grok_cli import GrokCliProvider  # noqa: E402
from cli_brain.lifecycle import CliBrainLifecycle, probe_service  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_finder_path_discovers_nvm_codex_and_supplies_sibling_node(
        tmp_path: Path, monkeypatch) -> None:
    nvm_bin = tmp_path / ".nvm" / "versions" / "node" / "v22.20.0" / "bin"
    nvm_bin.mkdir(parents=True)
    codex = nvm_bin / "codex"
    node = nvm_bin / "node"
    codex.write_text("#!/usr/bin/env node\n")
    node.write_text("#!/bin/sh\nexit 0\n")
    codex.chmod(0o755)
    node.chmod(0o755)

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # forma típica de Finder, sin NVM
    monkeypatch.delenv("PUPPET_CODEX_BIN", raising=False)

    found = CodexCliProvider().binary()
    assert found == str(codex)
    child_path = sanitized_env(found)["PATH"].split(os.pathsep)
    assert child_path[0] == str(nvm_bin)
    assert "OPENAI_API_KEY" not in sanitized_env(found)


def test_codex_default_uses_validated_local_config_model(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model = "gpt-5.6-sol"\nmodel_reasoning_effort = "max"\n'
        '[mcp_servers.private]\ncommand = "contains-values-we-never-return"\n')
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.delenv("PUPPET_CODEX_CLI_MODEL", raising=False)
    assert CodexCliProvider().default_model() == "gpt-5.6-sol"


def test_claude_limit_error_is_classified_without_session_identifier() -> None:
    raw = json.dumps({
        "type": "result", "is_error": True, "api_error_status": 429,
        "result": "You've hit your weekly limit · resets 6pm (America/Guayaquil)",
        "session_id": "5bb11d58-bd76-4d18-8047-6c1f13e499d8",
    })
    result = ClaudeCliProvider().parse_result(1, raw, "", "/tmp", "haiku")
    assert result.error_kind == "rate_limit"
    assert "6pm" in result.reset_hint
    assert "session" not in result.error_detail.lower()
    assert "5bb11d58" not in result.error_detail


def test_cli_model_and_effort_reach_real_provider_argv(tmp_path: Path) -> None:
    claude = ClaudeCliProvider().build_argv(
        "claude", "prompt", "sonnet", "/tmp", effort="max")
    assert claude[claude.index("--model") + 1] == "sonnet"
    assert claude[claude.index("--effort") + 1] == "max"

    codex = CodexCliProvider().build_argv(
        "codex", "prompt", "gpt-5.1-codex-max", "/tmp", effort="max")
    assert codex[codex.index("-m") + 1] == "gpt-5.1-codex-max"
    assert 'model_reasoning_effort="high"' in codex

    grok = GrokCliProvider().build_argv(
        "grok", "prompt", "grok-4.6", str(tmp_path), effort="low")
    assert grok[grok.index("--model") + 1] == "grok-4.6"
    assert grok[grok.index("--effort") + 1] == "low"
    assert grok[grok.index("--agent") + 1] == "aleph-zero"
    assert "--no-subagents" in grok
    assert grok[grok.index("--permission-mode") + 1] == "default"
    assert (tmp_path / ".grok" / "agents" / "aleph-zero.md").is_file()


def test_grok_detect_parses_logged_in_and_unauthenticated() -> None:
    p = GrokCliProvider()
    st, detail, extra = p.parse_detect(0, "You are logged in with grok.com.\nDefault model: grok-4.6\n", "")
    assert st == "ready" and extra.get("auth_billing") == "subscription"
    st, detail, extra = p.parse_detect(0, "You are not authenticated.\nDefault model: grok-4.6\n", "")
    assert st == "no_auth"


def test_grok_parse_result_fail_closed_on_advertised_tools() -> None:
    p = GrokCliProvider()
    end = json.dumps({
        "type": "end", "stopReason": "end_turn", "text": "hola",
        "advertised_tools": ["run_terminal_command"], "tool_calls": 0,
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "modelUsage": {"grok-4.6-build": {"inputTokens": 1, "outputTokens": 1}},
    })
    r = p.parse_result(0, end, "", "/tmp", "grok-4.6")
    assert r.ok is False and r.exec_events >= 1
    assert "tools" in (r.error_detail or "").lower() or "puro" in (r.error_detail or "").lower()


def test_grok_parse_result_accepts_empty_tools() -> None:
    p = GrokCliProvider()
    end = json.dumps({
        "type": "end", "stopReason": "end_turn", "text": "ok",
        "sessionId": "abc",
        "advertised_tools": [], "tool_calls": 0,
        "usage": {"input_tokens": 10, "output_tokens": 3,
                  "cache_read_input_tokens": 5, "cache_creation_input_tokens": 0,
                  "reasoning_tokens": 2},
        "modelUsage": {"grok-4.6-build": {"inputTokens": 10, "outputTokens": 3}},
    })
    r = p.parse_result(0, end, "", "/tmp", "grok-4.6")
    assert r.ok is True and r.text == "ok"
    assert r.model_final == "grok-4.6-build"
    assert r.usage.get("prompt_tokens") == 10
    assert r.usage.get("cache_read_tokens") == 5
    assert r.usage.get("reasoning_tokens") == 2
    assert r.exec_events == 0


def test_lifecycle_owns_reuses_stops_and_restarts_without_duplicate_listener() -> None:
    port = _free_port()
    owner = CliBrainLifecycle(port)
    shared = CliBrainLifecycle(port)

    assert owner.start()["mode"] == "managed"
    assert probe_service(port)
    second = shared.start()
    assert second["state"] == "ready" and second["mode"] == "shared"

    # La instancia que no posee el listener no puede apagarlo.
    shared.stop()
    assert probe_service(port)
    owner.stop()
    assert not probe_service(port)

    restarted = CliBrainLifecycle(port)
    assert restarted.start()["mode"] == "managed"
    assert probe_service(port)
    restarted.stop()
    assert not probe_service(port)


def test_lifecycle_does_not_touch_a_foreign_listener() -> None:
    port = _free_port()
    foreign = socket.socket()
    foreign.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    foreign.bind(("127.0.0.1", port))
    foreign.listen(1)
    try:
        state = CliBrainLifecycle(port).start()
        assert state["state"] == "unavailable"
        assert state["mode"] == "failed"
        assert "ocupado" in state["detail"]
        assert foreign.fileno() >= 0
    finally:
        foreign.close()


def test_shutdown_terminates_an_active_cli_process() -> None:
    result = {}

    def run_long_cli() -> None:
        result["proc"] = _run_managed(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=40,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )

    thread = threading.Thread(target=run_long_cli, daemon=True)
    thread.start()
    deadline = time.monotonic() + 3
    killed = 0
    while time.monotonic() < deadline and not killed:
        killed = terminate_active_processes()
        if not killed:
            time.sleep(0.02)
    thread.join(timeout=3)
    assert killed == 1
    assert not thread.is_alive()
    assert result["proc"].returncode != 0
