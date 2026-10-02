"""Pinned macOS guest executor; never falls back to host Python or a shell.

The VM has no network/storage/share devices and exchanges one bounded JSON line
over a dedicated Virtio serial channel. Inputs are model-controlled, not paths.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _ROOT / "deploy" / "guest" / "runtime"
_MANIFEST = "guest-manifest.json"


class GuestUnavailable(RuntimeError):
    pass


def _load_asset_manifest() -> dict[str, str]:
    """Load hashes generated from the exact signed guest staged for this build."""
    manifest = _RUNTIME / _MANIFEST
    if not manifest.is_file() or manifest.is_symlink():
        raise GuestUnavailable("guest asset manifest missing or unsafe")
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
        assets = document["assets"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise GuestUnavailable("guest asset manifest invalid") from exc
    if not isinstance(assets, dict):
        raise GuestUnavailable("guest asset manifest invalid")
    expected: dict[str, str] = {}
    for name in ("aleph-guest-runner", "Image.arm64", "rootfs.arm64.cpio.gz"):
        value = assets.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise GuestUnavailable(f"guest asset manifest invalid: {name}")
        expected[name] = value
    return expected


def _verified_assets() -> tuple[Path, Path, Path]:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise GuestUnavailable("isolated guest is only verified on macOS arm64")
    for name, expected in _load_asset_manifest().items():
        path = _RUNTIME / name
        if not path.is_file() or path.is_symlink():
            raise GuestUnavailable(f"guest asset missing or unsafe: {name}")
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        if h.hexdigest() != expected:
            raise GuestUnavailable(f"guest asset hash mismatch: {name}")
    helper = _RUNTIME / "aleph-guest-runner"
    if not os.access(helper, os.X_OK):
        # PyInstaller onefile extracts `datas` without preserving its executable
        # bit. The hash has already been verified on the exact extracted bytes.
        try:
            helper.chmod(helper.stat().st_mode | 0o100)
        except OSError as exc:
            raise GuestUnavailable("guest helper is not executable") from exc
    if not os.access(helper, os.X_OK):
        raise GuestUnavailable("guest helper is not executable")
    signed = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(helper)],
                            capture_output=True, timeout=5, check=False)
    if signed.returncode != 0:
        raise GuestUnavailable("guest helper signature invalid")
    return helper, _RUNTIME / "Image.arm64", _RUNTIME / "rootfs.arm64.cpio.gz"


def _execute_payload(request: dict, timeout_s: int,
                     on_tool: Callable[[str, dict], dict] | None = None) -> dict:
    helper, kernel, rootfs = _verified_assets()
    payload = json.dumps(request).encode() + b"\n"
    if len(payload) > 1024 * 1024:
        raise GuestUnavailable("guest request exceeds input limit")
    try:
        proc = subprocess.Popen([str(helper), str(kernel), str(rootfs)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0,
                                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                                start_new_session=True)
    except OSError as exc:
        raise GuestUnavailable(f"isolated guest unavailable: {type(exc).__name__}") from exc
    try:
        assert proc.stdin and proc.stdout
        proc.stdin.write(payload)
        deadline = time.monotonic() + timeout_s + 40
        buf = bytearray()
        calls = 0
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                if b"\n" not in buf:
                    events = selector.select(max(0, deadline - time.monotonic()))
                    if not events:
                        raise GuestUnavailable("isolated guest response timed out")
                    chunk = os.read(proc.stdout.fileno(), 4096)
                    if not chunk:
                        raise GuestUnavailable("isolated guest closed IPC")
                    buf.extend(chunk)
                    if len(buf) > 65536:
                        raise GuestUnavailable("isolated guest frame too large")
                    continue
                line, _, tail = buf.partition(b"\n")
                buf = bytearray(tail)
                frame = json.loads(line)
                if frame.get("kind") == "tool":
                    calls += 1
                    if (on_tool is None or calls > 64 or not isinstance(frame.get("name"), str)
                            or not isinstance(frame.get("args"), dict)):
                        raise GuestUnavailable("guest tool request not authorized")
                    reply = on_tool(frame["name"], frame["args"])
                    encoded = json.dumps(reply, ensure_ascii=True, default=str).encode() + b"\n"
                    if len(encoded) > 65536 or not isinstance(reply.get("ok"), bool):
                        raise GuestUnavailable("guest tool response too large or invalid")
                    proc.stdin.write(encoded)
                    continue
                result = frame
                break
        proc.stdin.close()
        proc.wait(timeout=5)
        if proc.returncode != 0:
            raise GuestUnavailable(f"isolated guest exited without result: {proc.returncode}")
        if not isinstance(result, dict) or not all(
            field in result for field in ("ok", "returncode", "stdout", "stderr", "timed_out")
        ):
            raise ValueError("invalid guest result")
        return {**result, "cwd": "/tmp/aleph-run"}
    except (ValueError, UnicodeDecodeError, OSError, subprocess.TimeoutExpired) as exc:
        raise GuestUnavailable("isolated guest returned invalid result") from exc
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()


def execute_python(code: str, timeout_s: int = 15, *,
                   on_tool: Callable[[str, dict], dict] | None = None) -> dict:
    if not isinstance(code, str) or len(code.encode("utf-8")) > 1024 * 1024:
        raise GuestUnavailable("guest code exceeds input limit")
    timeout_s = max(1, min(int(timeout_s), 30))
    return _execute_payload({"mode": "python", "code": code, "timeout_s": timeout_s,
                             "bridge": on_tool is not None}, timeout_s, on_tool)


def execute_shell(argv: list[str], timeout_s: int = 20) -> dict:
    allowed = {"git", "pandoc", "octave", "octave-cli", "python3", "pytest",
               "ls", "cat", "echo"}
    if (not isinstance(argv, list) or not argv or len(argv) > 64
            or argv[0] not in allowed
            or any(not isinstance(part, str) or len(part) > 4096 for part in argv)):
        raise GuestUnavailable("shell command not allowed in guest")
    timeout_s = max(1, min(int(timeout_s), 60))
    return _execute_payload({"mode": "shell", "argv": argv, "timeout_s": timeout_s}, timeout_s)
