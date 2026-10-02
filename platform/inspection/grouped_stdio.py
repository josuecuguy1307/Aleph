"""BYO-only MCP SDK spawn policy for supervised inspection process groups.

The SDK's normal detached session is right for long-lived MCP connections but
escapes the inspection watchdog. This override is installed only in the short-
lived BYO runner, before it creates a transport, and refuses SDK drift.
"""
from __future__ import annotations

import importlib.metadata
import inspect
import os
import sys


def install() -> None:
    if os.name != "posix" or os.getpid() != os.getpgrp():
        raise RuntimeError("BYO stdio requires a dedicated POSIX process group")
    if importlib.metadata.version("mcp") != "2.0.0":
        raise RuntimeError("unverified MCP SDK version for supervised BYO stdio")

    import anyio
    from mcp.client import stdio as sdk_stdio

    original = sdk_stdio._create_platform_compatible_process
    if tuple(inspect.signature(original).parameters) != ("command", "args", "env", "errlog", "cwd"):
        raise RuntimeError("MCP SDK stdio spawn contract changed")

    async def grouped_process(command, args, env=None, errlog=sys.stderr, cwd=None):
        # The remaining SDK stdio_client/ClientSession protocol path is unchanged.
        # The child inherits the BYO runner's group, which its independent
        # watchdog kills before the durable lease can expire.
        return await anyio.open_process([command, *args], env=env, stderr=errlog,
                                        cwd=cwd, start_new_session=False)

    sdk_stdio._create_platform_compatible_process = grouped_process
