"""Account-specific Codex model catalog via the CLI's app-server model/list RPC."""
from __future__ import annotations

import json
import os
import select
import subprocess
import time
from functools import lru_cache

from .base import sanitized_env


def _response(proc: subprocess.Popen, request_id: int, deadline: float) -> dict:
    pending = b""
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        if not select.select([proc.stdout], [], [], min(remaining, 0.5))[0]:
            continue
        chunk = os.read(proc.stdout.fileno(), 65536)
        if not chunk:
            break
        pending += chunk
        if len(pending) > 2_000_000:
            return {}
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("id") == request_id:
                return obj
    return {}


def _send(proc: subprocess.Popen, obj: dict) -> None:
    proc.stdin.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())
    proc.stdin.flush()


@lru_cache(maxsize=8)
def _catalog_cached(binary: str, time_bucket: int) -> tuple[tuple[str, ...], str]:
    """Return visible ids and account default, never a global hard-coded model list."""
    try:
        proc = subprocess.Popen([binary, "app-server"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                bufsize=0, env=sanitized_env(binary),
                                start_new_session=True)
    except OSError:
        return (), ""
    deadline = time.monotonic() + 8.0
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"clientInfo": {"name": "aleph", "title": "Aleph", "version": "0.1.2"}}})
        if "result" not in _response(proc, 1, deadline):
            return (), ""
        _send(proc, {"jsonrpc": "2.0", "method": "initialized"})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "model/list",
                     "params": {"limit": 100, "includeHidden": False}})
        response = _response(proc, 2, deadline)
        data = (response.get("result") or {}).get("data") or []
        if not isinstance(data, list):
            return (), ""
        ids = tuple(str(item.get("id")) for item in data
                    if isinstance(item, dict) and item.get("id"))
        default = next((str(item["id"]) for item in data
                        if isinstance(item, dict) and item.get("id") and item.get("isDefault")), "")
        return ids, default
    except (OSError, ValueError, BrokenPipeError):
        return (), ""
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)


def catalog(binary: str) -> tuple[tuple[str, ...], str]:
    return _catalog_cached(binary, int(time.time() // 60))
