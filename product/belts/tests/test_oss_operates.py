#!/usr/bin/env python3
"""
REAL PROOF (FASE1, microtask e) — an OSS model OPERATES the belt.
=================================================================

Drives `openai/gpt-oss-120b` (OSS, NON-frontier) through the Tool-belt MCP
client over a niche task per scenario. Success = the model actually CALLS the
tool and uses its real output to answer (not "responds 200").

Model routing: prefers the LiteLLM gateway alias `constructor-code`
(groq/openai/gpt-oss-120b). If :4000 is down (do NOT restart shared services),
falls back to Groq direct with the same OSS model id. Either way the operator
is OSS, not frontier.

Run: python3 product/belts/tests/test_oss_operates.py
Needs GROQ_API_KEY in env (for the direct path).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
BELTS = HERE.parent
sys.path.insert(0, str(BELTS / "client"))
import mcp_client as mc  # noqa: E402

# env the belts expand. PUPPET_BELTS = product/belts (belts-root único T7): los belts
# referencian su server relativo a este root (${PUPPET_BELTS}/gaps/… · ${PUPPET_BELTS}/cowork/…).
# BELTS = HERE.parent = product/belts.
os.environ.setdefault("PUPPET_BELTS", str(BELTS))
WORKDIR = Path("/tmp/puppet_belt_workdir")
WORKDIR.mkdir(exist_ok=True)
os.environ.setdefault("PUPPET_WORKDIR", str(WORKDIR))


def resolve_model():
    """Return (base_url, model, api_key). Prefer gateway; never restart it."""
    gw = "http://127.0.0.1:4000/v1"
    try:
        req = urllib.request.Request(gw + "/models", headers={"Authorization": "Bearer sk-1234"})
        with urllib.request.urlopen(req, timeout=3) as r:
            r.read()
        return gw, "constructor-code", os.environ.get("LITELLM_KEY", "sk-1234"), "gateway:constructor-code"
    except Exception:
        key = os.environ.get("GROQ_API_KEY", "")
        return "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", key, "groq-direct:openai/gpt-oss-120b"


def banner(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def run_scenario(name, belt, tool_filters, system, prompt, expect_tool, base_url, model, key):
    banner(f"SCENARIO: {name}")
    servers, reg = mc.build(belt, tool_filters)
    try:
        out = mc.run_loop(prompt, system, reg, base_url, model, key, max_turns=6)
    finally:
        for s in servers:
            s.stop()
    time.sleep(8)  # pace under Groq free-tier TPM (8000 tok/min) between scenarios
    called = [t["tool"] for t in out["trace"]]
    operated = expect_tool in called
    print(f"\n[ANSWER] {out['answer']}")
    print(f"[TOOLS CALLED] {called}")
    print(f"[OPERATED '{expect_tool}'?] {'YES' if operated else 'NO'}")
    return {"scenario": name, "operated": operated, "tools_called": called,
            "answer": out["answer"], "trace": out["trace"]}


def main():
    base_url, model, key, route = resolve_model()
    banner(f"MODEL ROUTE: {route}  (OSS, non-frontier)")
    if not key:
        print("[FATAL] no API key (set GROQ_API_KEY)"); sys.exit(2)

    results = []

    # --- Scenario 1: ATOMICS — filesystem (write+read) on a cowork task ---
    (WORKDIR / "nota.txt").unlink(missing_ok=True)
    results.append(run_scenario(
        "atomicas/filesystem (cowork)",
        str(BELTS / "atomicas.mcp.json"),
        {"filesystem": ["write_file", "read_text_file", "read_file", "list_directory"]},
        "Sos un asistente de oficina. Usa SIEMPRE las tools de archivos; no inventes el contenido.",
        f"Crea un archivo en {WORKDIR}/nota.txt con el texto exacto 'reunion 9am lunes' y luego leelo de vuelta y dime que dice.",
        "write_file", base_url, model, key,
    ))

    # --- Scenario 2: GAP Caso-2 script-runner on a finanzas calc ---
    results.append(run_scenario(
        "gaps/scriptrunner (finanzas)",
        str(BELTS / "gaps.mcp.json"),
        {"scriptrunner": ["run_python"]},
        "Sos un analista financiero. Para CUALQUIER calculo numerico, escribi y EJECUTA codigo Python con run_python; no calcules mentalmente.",
        "Un bono paga cupon anual de 50 sobre nominal 1000 a una tasa de descuento de 6% por 3 anios, mas el nominal al final. "
        "Calcula el precio (valor presente) ejecutando Python. Da el numero redondeado a 2 decimales.",
        "run_python", base_url, model, key,
    ))

    # --- Scenario 3: GAP Caso-1 api-wrapper on a finanzas/research task ---
    results.append(run_scenario(
        "gaps/apiwrapper (finanzas)",
        str(BELTS / "gaps.mcp.json"),
        {"apiwrapper": ["ticker_to_cik"]},
        "Sos un analista. Para resolver tickers a identificadores SEC usa la tool; no adivines el CIK.",
        "Cual es el CIK de SEC EDGAR para el ticker MSFT? Usa la tool y dame el CIK exacto.",
        "ticker_to_cik", base_url, model, key,
    ))

    banner("SUMMARY")
    ok = 0
    for r in results:
        flag = "OPERATED" if r["operated"] else "FAILED"
        print(f"  [{flag}] {r['scenario']} -> tools={r['tools_called']}")
        ok += int(r["operated"])
    print(f"\n{ok}/{len(results)} scenarios: OSS model truly operated the tool.")
    # machine-readable dump for evidence
    print("\n[JSON]\n" + json.dumps(results, ensure_ascii=False))
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
