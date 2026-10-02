"""Entry points run the one-time legacy-state migration (issue #904)."""

from __future__ import annotations

import pytest

from src.config import migrate


@pytest.fixture()
def record_migration(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(
        migrate, "migrate_legacy_state", lambda *a, **k: calls.append(1) or []
    )
    return calls


def test_cli_main_runs_migration(
    monkeypatch: pytest.MonkeyPatch, record_migration: list[int]
) -> None:
    import importlib

    import cli._legacy as legacy

    cli_main = importlib.import_module("cli.main")

    monkeypatch.setattr(cli_main, "_is_interactive_invocation", lambda argv: False)
    monkeypatch.setattr(legacy, "main", lambda argv: 0)

    assert cli_main.main(["list"]) == 0
    assert record_migration


def test_mcp_server_main_runs_migration(
    monkeypatch: pytest.MonkeyPatch, record_migration: list[int]
) -> None:
    import mcp_server

    monkeypatch.setattr(
        "sys.argv", ["vibe-trading-mcp", "--transport", "stdio"]
    )
    monkeypatch.setattr(mcp_server.mcp, "run", lambda **kwargs: None)

    mcp_server.main()
    assert record_migration


def test_api_startup_runs_migration(
    monkeypatch: pytest.MonkeyPatch, record_migration: list[int]
) -> None:
    import asyncio

    import api_server

    monkeypatch.setattr("src.preflight.run_preflight", lambda console: None)
    monkeypatch.setattr(api_server, "_start_scheduled_research_executor", lambda: None)
    monkeypatch.setattr(
        "src.config.accessor.get_env_config",
        lambda: type(
            "Cfg",
            (),
            {
                "agent_tuning": type(
                    "Tuning", (), {"vibe_trading_channels_auto_start": False}
                )()
            },
        )(),
    )

    preflight = asyncio.run(api_server._run_startup_preflight())
    preflight.join(timeout=1)
    assert record_migration


def test_api_lifespan_preserves_startup_and_shutdown_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    import api_server

    events: list[str] = []

    monkeypatch.setattr(
        migrate,
        "migrate_legacy_state",
        lambda: events.append("migration"),
    )
    monkeypatch.setattr(
        "src.preflight.run_preflight",
        lambda console: events.append("preflight"),
    )
    monkeypatch.setattr(
        api_server,
        "_start_scheduled_research_executor",
        lambda: events.append("scheduler-start"),
    )

    async def stop_scheduler() -> None:
        events.append("scheduler-stop")

    monkeypatch.setattr(api_server, "_stop_scheduled_research_executor", stop_scheduler)

    async def scenario() -> None:
        async with api_server._lifespan(api_server.app):
            events.append("serving")

    asyncio.run(scenario())

    # [Aleph · F6] el runtime de canales de IM se extirpó: ya no hay
    # "channels-start" / "channels-stop" en el ciclo de vida.
    assert events[0:2] == ["migration", "scheduler-start"]
    assert events.index("scheduler-start") < events.index("serving")
    assert events.index("serving") < events.index("scheduler-stop")
