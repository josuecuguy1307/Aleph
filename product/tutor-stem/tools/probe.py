#!/usr/bin/env python3
"""Sonda MCP stdio: handshake + tools/list + tools/call opcional. Uso:
   python3 mcp_probe.py '<comando>' [tool_name] [json_args]
"""
import json, subprocess, sys, threading, shlex

cmd = shlex.split(sys.argv[1])
tool = sys.argv[2] if len(sys.argv) > 2 else None
args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}

p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True)

def send(obj):
    p.stdin.write(json.dumps(obj) + "\n"); p.stdin.flush()

resp = {}
def reader():
    for line in p.stdout:
        line = line.strip()
        if not line: continue
        try:
            m = json.loads(line)
            if "id" in m: resp[m["id"]] = m
        except json.JSONDecodeError:
            pass

t = threading.Thread(target=reader, daemon=True); t.start()

send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    "protocolVersion":"2024-11-05","capabilities":{},
    "clientInfo":{"name":"puppet-probe","version":"0.1"}}})
import time
for _ in range(120):
    if 1 in resp: break
    time.sleep(0.5)
else:
    print("TIMEOUT en initialize"); p.kill(); sys.exit(1)
print("INIT OK:", json.dumps(resp[1].get("result",{}).get("serverInfo",{}), ensure_ascii=False))
send({"jsonrpc":"2.0","method":"notifications/initialized"})
send({"jsonrpc":"2.0","id":2,"method":"tools/list"})
for _ in range(60):
    if 2 in resp: break
    time.sleep(0.5)
tools = [t_["name"] for t_ in resp.get(2,{}).get("result",{}).get("tools",[])]
print(f"TOOLS ({len(tools)}):", ", ".join(tools[:15]))
if tool:
    send({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":tool,"arguments":args}})
    for _ in range(120):
        if 3 in resp: break
        time.sleep(0.5)
    r = resp.get(3, {"error":"TIMEOUT"})
    out = json.dumps(r.get("result", r.get("error")), ensure_ascii=False)
    print("CALL RESULT:", out[:600])
p.kill()
