"""Robinhood remote MCP generic-operation mapping."""

from __future__ import annotations

from typing import Any

_REMOTE_TOOL_NAMES = {
    "account": "get_portfolio",
    "positions": "get_equity_positions",
    "orders": "get_equity_orders",
    "quote": "get_equity_quotes",
}

_RUNNER_TOOL_NAMES = {
    "account": "get_portfolio",
    "positions": "get_equity_positions",
    "orders": "get_equity_orders",
    "quote": "get_equity_quotes",
    "submit_order": "place_equity_order",
    "cancel_order": "cancel_equity_order",
}


def remote_tool_name(operation: str) -> str | None:
    """Return the Robinhood remote tool name for a generic operation."""
    return _REMOTE_TOOL_NAMES.get(operation)


def runner_tool_name(operation: str) -> str | None:
    """Return the Robinhood remote tool name used by live runner plumbing."""
    return _RUNNER_TOOL_NAMES.get(operation)


def remote_arguments(operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Normalize generic arguments for a Robinhood remote MCP operation."""
    if operation == "quote":
        symbol = arguments.get("symbol")
        symbols = arguments.get("symbols")
        return {"symbols": symbols or ([symbol] if symbol else [])}
    if operation in ("account", "positions", "orders"):
        # Robinhood's get_portfolio / get_equity_positions / get_equity_orders
        # MCP tools require account_number. The generic trading service passes
        # the CLI/agent-supplied account code in under the "account" key; map
        # it to the field name Robinhood's schema actually expects.
        account_number = arguments.get("account_number") or arguments.get("account")
        if account_number:
            return {"account_number": account_number}
        return {}
    return {}
