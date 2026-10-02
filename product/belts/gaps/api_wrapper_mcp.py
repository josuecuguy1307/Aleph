#!/usr/bin/env python3
"""
Puppet AI — Tool-belt GAP: thin API wrapper (Caso 1, derivation `Caso 1 + B4`)
==============================================================================

The FASE0 table derivation rule: `Caso 1 + B4 = wrapper delgado de API`.
This is the reference Caso-1 GAP wrapper. Concrete instance = a public HTTP
JSON API exposed as MCP tools the model calls directly. Pure stdlib (urllib),
zero third-party deps, JSON-RPC 2.0 over stdio.

Instance chosen on purpose: SEC EDGAR's `company_tickers` + a generic
`http_get_json` — both CERO-FRICCIÓN (no key, no gate). This proves the
wrapper pattern WITHOUT touching the gated providers (Sheets GCP / Stata
license / paid keys), per founder guardrail #6.

Exposed tools:
  - ticker_to_cik   : resolve a US ticker -> SEC CIK (EDGAR public file)
  - http_get_json   : GET an allow-listed public JSON endpoint, return parsed body

A real wrapper for a keyed API (FRED, Alpha Vantage) is the SAME shape: swap
the base URL, read the key by reference (RECIPE-SCHEMA byok_ref), add the
query param. Kept keyless here so the test runs with no human gate.
"""

import json
import sys
import urllib.request
import urllib.error
from urllib.parse import urlparse

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "puppet-api-wrapper"
SERVER_VERSION = "0.1.0"

# Allow-list of hosts the wrapper may call (no SSRF to arbitrary/internal hosts).
HOST_ALLOW = {"www.sec.gov", "data.sec.gov", "api.stlouisfed.org", "www.alphavantage.co"}
USER_AGENT = "PuppetAI-toolbelt/0.1 (contact: ops@puppet.ai)"
TIMEOUT = 20


def _http_get(url: str) -> dict:
    host = urlparse(url).netloc
    if host not in HOST_ALLOW:
        return {"ok": False, "error": f"host '{host}' not in allow-list", "allow_list": sorted(HOST_ALLOW)}
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        try:
            return {"ok": True, "status": 200, "json": json.loads(body)}
        except json.JSONDecodeError:
            return {"ok": True, "status": 200, "text": body[:8000]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}", "body": e.read().decode(errors="replace")[:500]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_ticker_to_cik(args: dict) -> dict:
    ticker = (args.get("ticker") or "").upper().strip()
    if not ticker:
        return {"ok": False, "error": "empty ticker"}
    res = _http_get("https://www.sec.gov/files/company_tickers.json")
    if not res.get("ok"):
        return res
    data = res.get("json", {})
    for _, row in data.items():
        if str(row.get("ticker", "")).upper() == ticker:
            cik = str(row.get("cik_str", "")).zfill(10)
            return {"ok": True, "ticker": ticker, "cik": cik, "title": row.get("title")}
    return {"ok": False, "error": f"ticker '{ticker}' not found in SEC company_tickers"}


def tool_http_get_json(args: dict) -> dict:
    url = args.get("url", "")
    if not url:
        return {"ok": False, "error": "empty url"}
    return _http_get(url)


TOOLS = {
    "ticker_to_cik": {
        "description": "Resolve a US stock ticker to its SEC EDGAR CIK (10-digit, zero-padded). "
                       "Keyless, public SEC data. Use the CIK to pull fundamentals from EDGAR.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "e.g. AAPL, MSFT, TSLA"}},
            "required": ["ticker"],
        },
        "fn": tool_ticker_to_cik,
    },
    "http_get_json": {
        "description": "GET an allow-listed public JSON endpoint (SEC/FRED/AlphaVantage hosts) "
                       "and return the parsed body. Thin Caso-1 wrapper.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        "fn": tool_http_get_json,
    },
}


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
            continue
        elif method == "tools/list":
            _result(req_id, {"tools": [
                {"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
                for n, t in TOOLS.items()
            ]})
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            tool = TOOLS.get(name)
            if not tool:
                _error(req_id, -32601, f"unknown tool: {name}")
                continue
            try:
                out = tool["fn"](params.get("arguments", {}))
            except Exception as e:
                out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            _result(req_id, {
                "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                "isError": not out.get("ok", False),
            })
        elif req_id is not None:
            _error(req_id, -32601, f"method not found: {method}")


if __name__ == "__main__":
    main()
