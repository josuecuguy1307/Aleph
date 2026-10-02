#!/usr/bin/env python3
"""Sonda directa del finanzas_data_server por stdio (verify-before-trust)."""
import json, os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE / "finanzas_data_server.py"
WORKDIR = "/tmp/finz-probe"
os.makedirs(WORKDIR, exist_ok=True)

reqs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "worldbank_series",
        "arguments": {"country": "EC", "indicator": "NY.GDP.MKTP.CD", "start_year": 2015, "end_year": 2023}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "bce_pdf_ingest", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
        "name": "build_workbook",
        "arguments": {"filename": "finanzas_ecuador.xlsx",
                      "handles": ["wb:NY.GDP.MKTP.CD:EC",
                                  "bce:bce-estmacro-comercializacion-derivados-p15-t0"]}}},
]

env = dict(os.environ, PUPPET_WORKDIR=WORKDIR)
p = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
inp = "\n".join(json.dumps(r) for r in reqs) + "\n"
out, err = p.communicate(inp, timeout=120)

for line in out.splitlines():
    line = line.strip()
    if not line:
        continue
    o = json.loads(line)
    rid = o.get("id")
    if rid == 1:
        print("init:", o["result"]["serverInfo"])
    elif rid == 2:
        print("tools:", [t["name"] for t in o["result"]["tools"]])
    else:
        res = o["result"]
        txt = res["content"][0]["text"]
        try:
            d = json.loads(txt)
        except Exception:
            d = txt
        print(f"--- id {rid} (isError={res['isError']}):")
        print(json.dumps(d, ensure_ascii=False, indent=2)[:1100])

if err.strip():
    print("=== STDERR ===")
    print(err[:800])
