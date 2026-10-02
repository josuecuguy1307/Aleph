#!/usr/bin/env python3
"""
Puppet AI — Tool-belt GAP: script-runner sandbox (Caso 2, Bucket B3 / moat)
===========================================================================

THE motor for every Caso-2 tool (CLI/scriptable) across Prog, Finanzas,
Educación and (R&D) Ingeniería. Pattern from FASE0 table §2:

    model GENERATES code  ->  runner EXECUTES in a sandbox  ->  runner PARSES output

It is a plain MCP server (JSON-RPC 2.0 over stdio) so the assembler/MCP client
wires it like any other belt server. One piece unblocks N niches; that is why
the FASE0 roll-up classifies it B3 (build-it-ourselves moat).

Exposed tools (the curated surface — belt.tool_filters picks the subset):
  - run_python   : execute a Python snippet, return stdout/stderr/exit/result
  - run_shell    : execute an allow-listed CLI command (git, pandoc, octave...)

SANDBOX GUARANTEES (defense-in-depth, host-safe — the moat is "runs without
reventar el host"):
  1. Work only inside an ephemeral temp dir (cwd forced there); never the host CWD.
  2. Wall-clock timeout (kills the whole process group on overrun).
  3. Output capped (no log-bomb / OOM on the parent).
  4. run_shell is ALLOW-LIST only (refuses anything not explicitly permitted).
  5. SECURITY GATE HOOK: a Caso-2 tool that touches money/sends is gated by
     Security per RECIPE-SCHEMA §3.5 (the engine forces it). This server marks
     such requests with needs_gate=true in its structured result instead of
     silently executing — Security/assembler is the enforcer; we DECLARE.

NO third-party deps. Pure stdlib so it runs anywhere uvx/python runs.
"""

import json
import re
import sys
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "puppet-script-runner"
SERVER_VERSION = "0.1.0"

# ── sandbox policy ────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 20           # seconds, wall-clock
MAX_TIMEOUT = 60
MAX_OUTPUT = 16_000            # chars returned per stream
# run_shell allow-list: only Caso-2 CLIs the belt actually wires.
SHELL_ALLOW = {"git", "pandoc", "octave", "octave-cli", "python3", "pytest", "ls", "cat", "echo"}
# crude money/send classifier (Security owns the real one; this is the DECLARE side)
GATE_PATTERNS = re.compile(
    r"\b(send|sendmail|smtp|transfer|withdraw|wire|pay(ment)?|charge|buy|sell_order|place_order)\b",
    re.IGNORECASE,
)


def _cap(s: str) -> str:
    if s is None:
        return ""
    if len(s) > MAX_OUTPUT:
        return s[:MAX_OUTPUT] + f"\n...[truncated {len(s) - MAX_OUTPUT} chars]"
    return s


def _needs_gate(payload: str) -> bool:
    return bool(GATE_PATTERNS.search(payload or ""))


# ── tool implementations ──────────────────────────────────────────────────────

def tool_run_python(args: dict) -> dict:
    code = args.get("code", "")
    timeout = min(int(args.get("timeout", DEFAULT_TIMEOUT)), MAX_TIMEOUT)
    if not code.strip():
        return {"ok": False, "error": "empty code"}
    if _needs_gate(code):
        return {
            "ok": False,
            "needs_gate": True,
            "gate": "money_touch|send",
            "note": "Script matches a money/send pattern. Security must approve (RECIPE-SCHEMA 3.5) before execution.",
        }
    try:
        _generalistas = str(Path(__file__).resolve().parents[1] / "generalistas")
        if _generalistas not in sys.path:
            sys.path.insert(0, _generalistas)
        from guest_execution import execute_python
        result = execute_python(code, timeout)
        return {"ok": result["ok"], "exit_code": result["returncode"],
                "stdout": _cap(result["stdout"]), "stderr": _cap(result["stderr"]),
                "workdir": result["cwd"], "timed_out": result["timed_out"]}
    except Exception as exc:
        return {"ok": False, "blocked": True,
                "error": f"isolated_guest_unavailable: {type(exc).__name__}"}


def tool_run_shell(args: dict) -> dict:
    cmd = args.get("command", [])
    if isinstance(cmd, str):
        cmd = cmd.split()
    if not isinstance(cmd, list) or not cmd:
        return {"ok": False, "error": "empty command"}
    name = Path(str(cmd[0])).name
    if name not in SHELL_ALLOW:
        return {"ok": False, "blocked": True, "error": "command not allowed in isolated guest",
                "allow_list": sorted(SHELL_ALLOW)}
    cmd = [name, *cmd[1:]]
    if _needs_gate(" ".join(str(part) for part in cmd)):
        return {"ok": False, "needs_gate": True, "gate": "money_touch|send",
                "note": "Command matches a money/send pattern. Security must approve before execution."}
    try:
        _generalistas = str(Path(__file__).resolve().parents[1] / "generalistas")
        if _generalistas not in sys.path:
            sys.path.insert(0, _generalistas)
        from guest_execution import execute_shell
        result = execute_shell(cmd, args.get("timeout", DEFAULT_TIMEOUT))
        return {"ok": result["ok"], "exit_code": result["returncode"],
                "stdout": _cap(result["stdout"]), "stderr": _cap(result["stderr"]),
                "timed_out": result["timed_out"]}
    except Exception as exc:
        return {"ok": False, "blocked": True,
                "error": f"isolated_guest_unavailable: {type(exc).__name__}"}


TOOLS = {
    "run_python": {
        "description": "Execute a self-contained Python3 snippet in an isolated sandbox "
                       "(ephemeral cwd, wall-clock timeout, capped output, isolated env). "
                       "Returns stdout/stderr/exit_code. Use print() to emit results. "
                       "This is the Caso-2 motor: generate code, run it, read the parsed output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python3 source to execute."},
                "timeout": {"type": "integer", "description": f"Seconds (max {MAX_TIMEOUT}).", "default": DEFAULT_TIMEOUT},
            },
            "required": ["code"],
        },
        "fn": tool_run_python,
    },
    "run_shell": {
        "description": "Execute an allow-listed CLI command (git/pandoc/octave/pytest...) "
                       "in an isolated sandbox. Refuses anything outside the allow-list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "array", "items": {"type": "string"},
                            "description": "Argv list, e.g. [\"git\",\"--version\"]."},
                "timeout": {"type": "integer", "default": DEFAULT_TIMEOUT},
            },
            "required": ["command"],
        },
        "fn": tool_run_shell,
    },
}


# ── JSON-RPC 2.0 stdio loop ───────────────────────────────────────────────────

def _send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _result(req_id, result):
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code, message):
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            _result(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        elif method == "notifications/initialized":
            continue  # notification, no response
        elif method == "tools/list":
            _result(req_id, {
                "tools": [
                    {"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
                    for n, t in TOOLS.items()
                ]
            })
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            tool = TOOLS.get(name)
            if not tool:
                _error(req_id, -32601, f"unknown tool: {name}")
                continue
            try:
                out = tool["fn"](arguments)
            except Exception as e:  # never crash the server on a tool error
                out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            is_err = not out.get("ok", False) and not out.get("needs_gate", False)
            _result(req_id, {
                "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                "isError": is_err,
            })
        elif req_id is not None:
            _error(req_id, -32601, f"method not found: {method}")


if __name__ == "__main__":
    main()
