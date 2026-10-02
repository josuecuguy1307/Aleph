#!/usr/bin/env python3
"""
inference-compare/compare.py  —  Puppet AI cost+latency comparator (stdlib only).

WHAT IT DOES
  1. Reads prices.json ($/1M tokens in/out, fetched by hand — never hits the web).
  2. Measures LIVE latency where an endpoint is reachable:
       - LiteLLM proxy :4000 with its lane aliases (premium / constructor-code /
         explorer-reason / specialist), authed with LITELLM_MASTER_KEY.
       - Ollama :11434 local directly (qwen3:8b).
     Each ping asks for ~20 tokens, short timeout. Unreachable => declared SKIP.
  3. Combines price + latency + notes and emits a RECOMMENDATION per org lane:
       constructor-code / explorer-reason / premium / specialist.

No third-party deps. Run:  python3 compare.py
Reads infra/.env for keys/bases if present (LITELLM_MASTER_KEY, OLLAMA_API_BASE).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICES_PATH = HERE / "prices.json"

# Endpoints (local-first). Overridable via env.
LITELLM_BASE = os.environ.get("LITELLM_BASE", "http://localhost:4000")
OLLAMA_BASE_LOCAL = os.environ.get("OLLAMA_LOCAL_BASE", "http://localhost:11434")
PING_TIMEOUT = float(os.environ.get("PING_TIMEOUT", "12"))
PING_MAX_TOKENS = 20

# Lane -> LiteLLM alias (the names agents actually request from the gateway).
LANE_ALIASES = {
    "premium": "premium",
    "constructor-code": "constructor-code",
    "explorer-reason": "explorer-reason",
    "specialist": "specialist",
}


# ----------------------------- env / prices ------------------------------- #

def load_env_file():
    """Minimal .env loader (no python-dotenv). Looks at ../../infra/.env."""
    env_path = HERE.parent.parent / "infra" / ".env"
    found = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            found[k.strip()] = v.strip()
    # Real environment wins over file.
    for k, v in found.items():
        os.environ.setdefault(k, v)
    return found


def load_prices():
    with open(PRICES_PATH, "r") as f:
        return json.load(f)


# ----------------------------- live latency ------------------------------- #

def _http_post_json(url, payload, headers, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
    ms = (time.perf_counter() - t0) * 1000.0
    return ms, body


def ping_litellm_alias(alias):
    """One ~20-token chat completion through the LiteLLM proxy. Returns dict."""
    key = os.environ.get("LITELLM_MASTER_KEY", "")
    url = f"{LITELLM_BASE}/v1/chat/completions"
    payload = {
        "model": alias,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": PING_MAX_TOKENS,
        "temperature": 0,
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        ms, body = _http_post_json(url, payload, headers, PING_TIMEOUT)
        try:
            j = json.loads(body)
        except Exception:
            return {"status": "ERROR", "detail": f"non-JSON: {body[:120]}"}
        if "error" in j:
            return {"status": "ERROR", "detail": str(j["error"])[:160]}
        backend = j.get("model", "?")
        return {"status": "OK", "latency_ms": round(ms, 1), "backend": backend}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:160] if e.fp else str(e)
        return {"status": "SKIP", "detail": f"HTTP {e.code}: {detail}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"status": "SKIP", "detail": f"unreachable: {e}"}


def ping_ollama_direct(model="qwen3:8b"):
    """Direct ping to local Ollama (bypasses proxy). Returns dict."""
    url = f"{OLLAMA_BASE_LOCAL}/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "stream": False,
        "options": {"num_predict": PING_MAX_TOKENS, "temperature": 0},
    }
    headers = {"Content-Type": "application/json"}
    try:
        ms, body = _http_post_json(url, payload, headers, max(PING_TIMEOUT, 60))
        try:
            j = json.loads(body)
        except Exception:
            return {"status": "ERROR", "detail": f"non-JSON: {body[:120]}"}
        if "error" in j:
            return {"status": "ERROR", "detail": str(j["error"])[:160]}
        return {"status": "OK", "latency_ms": round(ms, 1), "backend": model}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return {"status": "SKIP", "detail": f"unreachable: {e}"}


# ----------------------------- price helpers ------------------------------ #

def blended_per_1m(model_entry, in_w=0.75, out_w=0.25):
    """Blended $/1M tokens assuming a 3:1 input:output mix (typical agent turn)."""
    return round(model_entry["input"] * in_w + model_entry["output"] * out_w, 4)


def lane_price_row(prices):
    """Map each lane to its primary provider price + cheapest paid alternative."""
    g = prices["providers"]["groq"]["models"]
    orouter = prices["providers"]["openrouter"]["models"]
    deepseek = prices["providers"]["deepseek"]["models"]
    ollama = prices["providers"]["ollama_local"]["models"]

    rows = {}
    rows["constructor-code"] = {
        "primary": ("groq", "openai/gpt-oss-120b", g["openai/gpt-oss-120b"]),
        "alt": ("openrouter", "openai/gpt-oss-120b", orouter["openai/gpt-oss-120b"]),
    }
    rows["explorer-reason"] = {
        "primary": ("groq", "qwen/qwen3-32b", g["qwen/qwen3-32b"]),
        "alt": ("openrouter", "qwen/qwen3-32b", orouter["qwen/qwen3-32b"]),
        "alt2": ("deepseek", "deepseek-v4-flash", deepseek["deepseek-v4-flash"]),
    }
    rows["premium"] = {
        "primary": ("groq", "llama-3.3-70b-versatile", g["llama-3.3-70b-versatile"]),
        "alt": ("openrouter", "llama-3.3-70b:free",
                orouter["meta-llama/llama-3.3-70b-instruct:free"]),
    }
    rows["specialist"] = {
        "primary": ("ollama_local", "qwen3:8b", ollama["qwen3:8b"]),
    }
    return rows


# ----------------------------- rendering ---------------------------------- #

def fmt_price(m):
    return f"in ${m['input']:.4f} / out ${m['output']:.4f} per 1M"


def main():
    load_env_file()
    prices = load_prices()
    fetched = prices["_meta"]["fetched_on"]
    today = time.strftime("%Y-%m-%d")

    out = []
    p = out.append

    p("=" * 78)
    p("PUPPET AI — INFERENCE COST + LATENCY COMPARATOR")
    p(f"run_date={today}   prices_fetched_on={fetched}   (prices.json, not live web)")
    p("=" * 78)

    # ---- live latency ----
    p("\n[1] LIVE LATENCY  (one ~20-token ping each, timeout %.0fs)" % PING_TIMEOUT)
    p("-" * 78)
    live = {}

    p(f"  LiteLLM proxy @ {LITELLM_BASE} (lane aliases):")
    for lane, alias in LANE_ALIASES.items():
        r = ping_litellm_alias(alias)
        live[("litellm", lane)] = r
        if r["status"] == "OK":
            p(f"    {lane:<17} alias={alias:<17} OK  {r['latency_ms']:>8.1f} ms  -> {r['backend']}")
        else:
            p(f"    {lane:<17} alias={alias:<17} {r['status']}  {r.get('detail','')}")

    p(f"\n  Ollama direct @ {OLLAMA_BASE_LOCAL} (bypass proxy):")
    r = ping_ollama_direct("qwen3:8b")
    live[("ollama", "specialist")] = r
    if r["status"] == "OK":
        p(f"    qwen3:8b                              OK  {r['latency_ms']:>8.1f} ms")
    else:
        p(f"    qwen3:8b                              {r['status']}  {r.get('detail','')}")

    # ---- price table ----
    p("\n[2] PRICE TABLE  ($/1M tokens, from prices.json fetched %s)" % fetched)
    p("-" * 78)
    rows = lane_price_row(prices)
    for lane in ("constructor-code", "explorer-reason", "premium", "specialist"):
        p(f"  {lane}:")
        for slot in ("primary", "alt", "alt2"):
            if slot not in rows[lane]:
                continue
            prov, name, m = rows[lane][slot]
            blended = blended_per_1m(m)
            tag = {"primary": "PRIMARY", "alt": "alt", "alt2": "alt"}[slot]
            p(f"    [{tag:<7}] {prov:<12} {name:<34} {fmt_price(m)}  | blended3:1 ${blended}/1M")

    # ---- recommendation ----
    p("\n[3] RECOMMENDATION PER LANE  (price + live latency + notes)")
    p("-" * 78)

    def lat(lane, src="litellm"):
        r = live.get((src, lane), {})
        return r if r.get("status") == "OK" else None

    recs = []

    # constructor-code
    cc_lat = lat("constructor-code")
    cc = rows["constructor-code"]
    line = ("CONSTRUCTOR-CODE -> Groq gpt-oss-120b (free tier).\n"
            "    Cheapest code-direct OSS on the ladder: $0.15 in / $0.60 out, blended "
            f"${blended_per_1m(cc['primary'][2])}/1M. Free tier covers it (200k TPD).\n"
            "    Fallback when Groq rate-limits: OpenRouter gpt-oss-120b paid "
            f"(${cc['alt'][2]['input']}/${cc['alt'][2]['output']}) — ~4x cheaper input than Groq paid,\n"
            "    use it as the paid overflow, not Groq paid. ")
    line += (f"LIVE: {cc_lat['latency_ms']} ms via proxy ({cc_lat['backend']})."
             if cc_lat else "LIVE: ping SKIP/err — verify proxy alias before trusting.")
    recs.append(line)

    # explorer-reason
    er_lat = lat("explorer-reason")
    er = rows["explorer-reason"]
    line = ("EXPLORER-REASON -> Groq qwen3-32b (free tier) for open/reasoning tasks.\n"
            f"    $0.29 in / $0.59 out, blended ${blended_per_1m(er['primary'][2])}/1M; emits <think> so give generous max_tokens.\n"
            "    Cheaper external alt for heavy reasoning volume: DeepSeek v4-flash "
            f"(${er['alt2'][2]['input']} in / ${er['alt2'][2]['output']} out, cache-hit in ${er['alt2'][2]['input_cache_hit']}),\n"
            "    which undercuts Groq paid AND OpenRouter qwen3-32b — route here if free tier TPM (6k) chokes. ")
    line += (f"LIVE: {er_lat['latency_ms']} ms via proxy ({er_lat['backend']})."
             if er_lat else "LIVE: ping SKIP/err — verify proxy alias.")
    recs.append(line)

    # premium
    pr_lat = lat("premium")
    pr = rows["premium"]
    line = ("PREMIUM -> Groq llama-3.3-70b-versatile (free tier) for Leads/Reviewers/Supervisor.\n"
            f"    $0.59 in / $0.79 out, blended ${blended_per_1m(pr['primary'][2])}/1M — priciest lane, keep it for judgment only.\n"
            "    Fallback OpenRouter llama-3.3-70b:free ($0/$0) when Groq 429s; it is truly free but\n"
            "    rate-capped (~20 rpm, 50-1000/day) and upstream-availability-dependent, so it's a spillover, not the primary. ")
    line += (f"LIVE: {pr_lat['latency_ms']} ms via proxy ({pr_lat['backend']})."
             if pr_lat else "LIVE: ping SKIP/err — verify proxy alias.")
    recs.append(line)

    # specialist
    sp_lat = lat("specialist", "litellm") or lat("specialist", "ollama")
    sp_ol = live.get(("ollama", "specialist"), {})
    line = ("SPECIALIST -> local Ollama qwen3:8b ($0 dollar-cost) for high-volume executor work.\n"
            "    $0/token; the real cost is latency+quality, not money. Best when throughput matters and the\n"
            "    task is bounded enough for an 8B model. If a turn needs more muscle, escalate to constructor-code.\n"
            "    No rate limits, fully private/local. ")
    if sp_ol.get("status") == "OK":
        line += f"LIVE: {sp_ol['latency_ms']} ms direct to Ollama (this is the latency you pay instead of dollars)."
    elif sp_lat:
        line += f"LIVE: {sp_lat['latency_ms']} ms via proxy."
    else:
        line += "LIVE: ping SKIP/err — Ollama not responding; specialist lane unavailable right now."
    recs.append(line)

    for i, r in enumerate(recs, 1):
        p(f"\n  {i}. {r}")

    p("\n" + "=" * 78)
    p("BOTTOM LINE: free Groq tier serves all 4 paid lanes today; route by tokens-per-day,")
    p("not requests. Paid overflow order: OpenRouter (gpt-oss-120b / qwen3-32b) and DeepSeek")
    p("v4-flash beat Groq paid on $/token — escalate to them before paying Groq. Specialist")
    p("stays local at $0 with latency as its only cost.")
    p("=" * 78)

    text = "\n".join(out)
    print(text)
    return text


if __name__ == "__main__":
    main()
