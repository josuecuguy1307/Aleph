"""
h.py — reusable Step 4.5 Caso 2/3 harness helper.
Reads the RIGHT fields (per the calibration-known-bads map): the previous harness
scored tool-error false-green (b) and pure-narration (c) as GREEN because it read
top-level ok/degraded and tc.get('ok')=None. This one reads tool_calls[].result
error markers, tools_cabled vs a per-probe needs_tool flag, and the cost-event tokens.
"""
from pathlib import Path
import json, urllib.request, urllib.error, time

BASE = "http://127.0.0.1:8130"
WT = str(Path(__file__).resolve().parent)

def login(email, password):
    body = {"email": email, "password": password}
    d = _post("/v1/auth/login", body, tok=None)
    return d["id"], d["session_token"]

def register(email, password, display_name):
    body = {"email": email, "password": password, "display_name": display_name}
    return _post("/v1/auth/register", body, tok=None)

def _post(path, body, tok, timeout=200):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=h, method="POST")
    r = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(r.read())

def fire(recipe, prompt, tok, user_id, autonomy="autonomo", space_id=None, deadline_s=180.0, timeout=None):
    """Fire a real sync run; return (elapsed_s, response_dict_or_httperror)."""
    body = {"recipe": recipe, "prompt": prompt, "user_id": user_id,
            "autonomy": autonomy, "deadline_s": deadline_s, "lang": "es"}
    if space_id:
        body["space_id"] = space_id
    t = time.time()
    try:
        d = _post("/v1/puppets/run", body, tok, timeout=timeout or (deadline_s + 60))
        return time.time() - t, d
    except urllib.error.HTTPError as e:
        return time.time() - t, {"__http_error__": e.code, "body": e.read().decode()[:800]}

_ERR_PREFIXES = ("[tool error", "[error", "error:", "[mcp error", "[err")

def _tool_errored(tc):
    """True if this tool_call's result signals an error (calibration-b: the
    per-tool 'ok' field does NOT exist — must inspect the result string/json)."""
    res = tc.get("result")
    if isinstance(res, str):
        if res.strip().lower().startswith(_ERR_PREFIXES):
            return True
        try:
            j = json.loads(res)
        except Exception:
            j = None
    elif isinstance(res, dict):
        j = res
    else:
        j = None
    if isinstance(j, dict):
        if j.get("ok") is False or j.get("isError") is True or j.get("error"):
            return True
    return False

def extract(d, needs_tool=False):
    """Structured, right-field read + calibration RED flags."""
    if d.get("__http_error__"):
        return {"http_error": d["__http_error__"], "body": d.get("body")}
    rec = d.get("record", d)
    tcs = rec.get("tool_calls") or []
    tool_errors = [tc.get("tool") for tc in tcs if _tool_errored(tc)]
    cabled = rec.get("tools_cabled") or []
    err = d.get("error") or rec.get("error")
    ok = d.get("ok") if d.get("ok") is not None else rec.get("ok")
    degraded = d.get("degraded") if d.get("degraded") is not None else rec.get("degraded")
    cost = rec.get("cost_events") or d.get("cost_events") or []
    model_costs = [{
        "model": c.get("model"), "tier": c.get("tier"), "degraded": c.get("degraded"),
        "pin": (c.get("tokens") or {}).get("prompt"),
        "cout": (c.get("tokens") or {}).get("completion"),
        "measured": c.get("tokens_measured"),
    } for c in cost if c.get("kind") == "model"]
    usage = rec.get("usage") or d.get("usage")
    return {
        "ok": ok, "degraded": degraded, "error": err,
        "model_final": rec.get("model_final"),
        "n_tool_calls": len(tcs),
        "tools": [tc.get("tool") for tc in tcs],
        "tool_errors": tool_errors,
        "tools_cabled": cabled,
        "held_actions": rec.get("held_actions") or d.get("held_actions") or [],
        "answer": (d.get("answer") or rec.get("answer") or "")[:500],
        "model_costs": model_costs,
        "usage": usage,
        # calibration RED flags (the instrument must fire these)
        "RED_narration": bool(needs_tool and len(tcs) == 0 and cabled),
        "RED_tool_error_falsegreen": bool(tool_errors and ok and not degraded and not err),
    }

def tool_results(d, keys=("ok", "symbol", "price", "sharpe", "weights", "ann_return_pct", "error", "verdict", "handle")):
    """Compact view of each tool call's args->result for eyeballing correctness."""
    rec = d.get("record", d)
    out = []
    for tc in (rec.get("tool_calls") or []):
        res = tc.get("result")
        try:
            j = json.loads(res) if isinstance(res, str) else res
        except Exception:
            j = None
        keep = {k: j.get(k) for k in keys if isinstance(j, dict) and k in j} or (str(res)[:120] if res is not None else None)
        out.append({"tool": tc.get("tool"), "err": _tool_errored(tc), "res": keep})
    return out

def pj(x):
    print(json.dumps(x, ensure_ascii=False, indent=2, default=str))
