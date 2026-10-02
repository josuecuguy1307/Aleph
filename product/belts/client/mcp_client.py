#!/usr/bin/env python3
"""
Puppet AI — Tool-belt MCP client (standalone)
=============================================

A minimal, dependency-free MCP stdio client used by the Tool-belt squad to
PROVE a belt: spawn the servers declared in a `.mcp.json`, do the JSON-RPC 2.0
handshake, build a tool registry (honoring per-server tool_filters), and run an
OpenAI-compatible tool-use loop so a real model can OPERATE the tools.

This is the squad's own test harness. It deliberately does NOT import or modify
`platform/assembler/*` (that is another squad's lane). The wire format is the
same MCP/JSON-RPC so a verified belt drops straight into the assembler.

stdlib only (urllib/subprocess/select/threading).
"""

import json
import os
import select
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import re
from pathlib import Path
from typing import Optional


class MCPServer:
    """One MCP server subprocess over JSON-RPC 2.0 stdio."""

    def __init__(self, name, command, args, env=None):
        self.name = name
        self._cmd = [command] + list(args or [])
        self._env = {**os.environ, **(env or {})}
        self._proc = None
        self._lock = threading.Lock()
        self._id = 0

    def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=self._env,
            )
        except Exception as e:
            print(f"[MCP] {self.name}: spawn error {e}", file=sys.stderr)
            return False
        resp = self._rpc("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "puppet-belt-client", "version": "0.1"},
        })
        if resp and "result" in resp:
            info = resp["result"].get("serverInfo", {})
            print(f"[MCP] {self.name}: INIT OK -> {info.get('name')} {info.get('version')}", file=sys.stderr)
            self._notify("notifications/initialized", {})
            return True
        print(f"[MCP] {self.name}: INIT FAIL {resp}", file=sys.stderr)
        return False

    def list_tools(self):
        r = self._rpc("tools/list", {})
        return (r or {}).get("result", {}).get("tools", []) if r else []

    def call_tool(self, name, arguments):
        r = self._rpc("tools/call", {"name": name, "arguments": arguments}, timeout=60)
        if not r:
            return f"[no response from {self.name}]"
        if "error" in r:
            return f"[error {r['error']}]"
        res = r.get("result", {})
        parts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
        return "\n".join(parts) if parts else json.dumps(res)

    def stop(self):
        if self._proc:
            try:
                self._proc.terminate(); self._proc.wait(timeout=3)
            except Exception:
                pass

    def _nid(self):
        self._id += 1
        return self._id

    def _rpc(self, method, params, timeout=30.0):
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                return None
            rid = self._nid()
            msg = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            try:
                self._proc.stdin.write((msg + "\n").encode()); self._proc.stdin.flush()
            except BrokenPipeError:
                return None
            deadline = time.time() + timeout
            while time.time() < deadline:
                line = self._readline(max(0.1, deadline - time.time()))
                if line is None:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("id") == rid:
                    return obj
            return None

    def _notify(self, method, params):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write((json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n").encode())
                self._proc.stdin.flush()
            except Exception:
                pass

    def _readline(self, timeout=10.0):
        if not self._proc or self._proc.poll() is not None:
            return None
        try:
            ready, _, _ = select.select([self._proc.stdout.fileno()], [], [], timeout)
        except Exception:
            return None
        if not ready:
            return None
        line = self._proc.stdout.readline()
        return line.decode(errors="replace").strip() if line else None


class ToolRegistry:
    def __init__(self, servers, tool_filters=None):
        tool_filters = tool_filters or {}
        self._by_tool = {}
        self._schema = []
        for srv in servers:
            allowed = tool_filters.get(srv.name)
            for t in srv.list_tools():
                if allowed is not None and t["name"] not in allowed:
                    continue
                self._by_tool[t["name"]] = srv
                self._schema.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                    },
                })
        print(f"[Registry] {len(self._schema)} tools: {[s['function']['name'] for s in self._schema]}", file=sys.stderr)

    def schema(self):
        return self._schema

    def call(self, name, args):
        srv = self._by_tool.get(name)
        if not srv:
            return f"[unknown tool {name}]"
        print(f"[Tool->] {name}({json.dumps(args)})", file=sys.stderr)
        out = srv.call_tool(name, args)
        print(f"[Tool<-] {name}: {out[:400]}", file=sys.stderr)
        return out


def chat(messages, tools, base_url, model, api_key, max_tokens=1024, temperature=0):
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # some edges (Cloudflare on Groq) 403 the default Python UA
            "User-Agent": "puppet-belt-client/0.1",
        },
        method="POST",
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code == 429 and attempt < 4:
                # honor free-tier TPM; parse "try again in Ns" if present, else backoff
                wait = 8.0
                m = re.search(r"try again in ([0-9.]+)s", body)
                if m:
                    wait = float(m.group(1)) + 1.0
                print(f"[chat] 429 rate-limit, sleeping {wait:.1f}s (attempt {attempt+1})", file=sys.stderr)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {body}")
    raise RuntimeError("HTTP 429: exhausted retries")


def run_loop(prompt, system, registry, base_url, model, api_key, max_turns=8):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    tools = registry.schema()
    trace = []
    for turn in range(1, max_turns + 1):
        print(f"\n[Turn {turn}/{max_turns}]", file=sys.stderr)
        resp = chat(messages, tools, base_url, model, api_key)
        choice = resp["choices"][0]
        msg = choice["message"]
        finish = choice.get("finish_reason", "")
        messages.append(msg)
        tcs = msg.get("tool_calls") or []
        if tcs and finish != "stop":
            for tc in tcs:
                fn = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = registry.call(fn, args)
                trace.append({"turn": turn, "tool": fn, "args": args, "result": result[:1000]})
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        else:
            return {"answer": msg.get("content", ""), "trace": trace, "turns": turn}
    return {"answer": "[max turns reached]", "trace": trace, "turns": max_turns}


def load_belt(belt_path, expand_env=True):
    raw = Path(belt_path).read_text()
    if expand_env:
        raw = os.path.expandvars(raw)
    return json.loads(raw).get("mcpServers", {})


def build(belt_path, tool_filters=None):
    servers = []
    for name, scfg in load_belt(belt_path).items():
        srv = MCPServer(name, scfg["command"], scfg.get("args", []), scfg.get("env"))
        if srv.start():
            servers.append(srv)
        else:
            print(f"[WARN] {name} failed to start; skipping", file=sys.stderr)
    return servers, ToolRegistry(servers, tool_filters)


if __name__ == "__main__":
    # smoke: python mcp_client.py <belt.mcp.json>
    belt = sys.argv[1] if len(sys.argv) > 1 else None
    if not belt:
        print("usage: mcp_client.py <belt.mcp.json>", file=sys.stderr)
        sys.exit(1)
    servers, reg = build(belt)
    print(json.dumps([s["function"]["name"] for s in reg.schema()]))
    for s in servers:
        s.stop()
