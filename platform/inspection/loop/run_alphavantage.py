#!/usr/bin/env python3
"""
run_alphavantage.py — el MISMO loop interno §3, apuntado a Alpha Vantage.

Mismo engine.py / mismas 5 capas / mismo budget+convergencia §6 que TMDB. Lo único
que cambia son las PERILLAS del target (no el motor):

  • base = https://www.alphavantage.co  · dispatch_path /query · auth `apikey` en query
  • DESPACHO-POR-QUERY: todas las tools van a /query y la operación la nombra `function`
    → `dispatch_param="function"` (la firma de tool incluye la función, no colisiona).
  • AV señala errores EN BANDA (HTTP 200 + {"Error Message"/"Information"/"Note": …}) →
    `soft_error_keys`/`soft_notice_keys`: un 200 que es SOLO error NO es una tool. AHÍ
    caza el candado las alucinaciones ORGÁNICAS del cerebro.

Key: env ALPHAVANTAGE_API_KEY (nunca en el prompt/CLI). Cerebro: Opus 4.8 vía shim.

Uso:
    export ALPHAVANTAGE_API_KEY=xxxx
    PUPPET_BRAIN_SHIM=1 product/backend/.venv/bin/python \\
      platform/inspection/loop/run_alphavantage.py
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.budget import Budget  # noqa: E402
from inspection.loop.engine import ALPHAVANTAGE_BASE, run_internal_loop  # noqa: E402

# las perillas del target AV (forma, no motor) — reusadas por el gate.
AV_KNOBS = dict(
    auth_param="apikey",
    validate_path="/query",
    validate_query={"function": "GLOBAL_QUOTE", "symbol": "IBM"},
    passive_probes=["/query"],
    dispatch_param="function",
    soft_error_keys=("Error Message", "Information"),
    soft_notice_keys=("Note",),
    # AV throttlea a 1 req/seg → pacing obligatorio o todo vuelve rate-limited.
    min_interval=1.3,
    api_shape_hint=(
        "Alpha Vantage es DESPACHO-POR-QUERY: TODAS las tools pegan al MISMO path '/query' "
        "y la operación la elige el query param `function` (p.ej. GLOBAL_QUOTE, "
        "TIME_SERIES_DAILY, OVERVIEW, CURRENCY_EXCHANGE_RATE). Por eso CADA tool candidata "
        "debe tener endpoint='/query' y traer `function` (+ params como symbol/interval/"
        "from_currency) DENTRO de sample_call.query. Señala errores EN BANDA con HTTP 200 + "
        "{'Error Message'|'Information'|'Note': ...}; el candado lo detecta y la dropea."
    ),
)


def _print_event(ev: dict) -> None:
    t = ev.get("type")
    if t == "session.acquired":
        print(f"  · sesión OK · {ev['meta'].get('auth_form')} · key {ev['meta'].get('key_fingerprint')}")
    elif t == "observe":
        kind = "PASIVA" if ev["passive"] else f"ACTIVA→{ev.get('probed')}"
        print(f"\n[vuelta {ev['round']}] observar ({kind}) · +confirmed {ev.get('new_confirmed')}")
    elif t == "synth":
        if ev.get("degraded"):
            print(f"  synth DEGRADADO ⚠️  {ev.get('reason')}")
        else:
            print(f"  synth ({ev.get('model')}) propuso {ev.get('proposed')}")
            print(f"           frescas → {ev.get('fresh')}  [{ev.get('tokens')} tok]")
    elif t == "validate":
        print(f"  candado ✓ VERIFIED {ev['verified']}")
        for f in ev["failed"]:
            print(f"          ✗ DROP {f['name']} → {f['class']}({f['symptom']}) move={f['move']}")
    elif t == "forged":
        print(f"\n  ⚒  MCP forjado: {ev['server_name']} · {len(ev['tools'])} tools → {ev['belt_ref']}")
    elif t == "closed":
        print(f"\n  ▣ cerrado: {ev['convergence']} · verified={ev['verified']} "
              f"dropped={ev['dropped']} degraded={ev['degraded']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("ALPHAVANTAGE_API_KEY", ""))
    ap.add_argument("--base", default=os.environ.get("ALPHAVANTAGE_BASE", ALPHAVANTAGE_BASE))
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--max-tokens", type=int, default=300_000)
    args = ap.parse_args()

    if not args.key:
        print("ERROR: falta la api_key de Alpha Vantage (env ALPHAVANTAGE_API_KEY o --key).",
              file=sys.stderr)
        print("Gratis: https://www.alphavantage.co/support/#api-key", file=sys.stderr)
        return 2

    principal = C.Principal(anon_id=f"run-av-{uuid.uuid4().hex[:12]}")
    budget = Budget(max_rounds=args.rounds, max_live_calls=args.max_calls,
                    max_synth_tokens=args.max_tokens)

    print("═" * 72)
    print(f"  LOOP INTERNO §3 · vivo contra {args.base}/query (Alpha Vantage)")
    print("═" * 72)
    res = run_internal_loop(args.base, args.key, principal, slug="alphavantage-live",
                            budget=budget, on_event=_print_event, **AV_KNOBS)

    print("\n" + "─" * 72)
    print("  RESUMEN")
    print("─" * 72)
    if res.error:
        print(f"  ✗ {res.error}")
        return 1
    print(f"  convergencia: {res.convergence}")
    print(f"  budget: {res.budget}")
    print(f"\n  TOOLS VERIFICADAS (llamadas vivas, 200 + datos reales) — {len(res.verified)}:")
    for v in res.verified:
        sample = (v.candidate.input_schema.get("x-sample-call") or {}).get("query", {})
        fn = sample.get("function", "?")
        print(f"    ✓ {v.candidate.name:34s} function={fn}")
    print(f"\n  CANDIDATAS DROPEADAS por la tabla §5 — {len(res.dropped)}:")
    for d in res.dropped_by_failure_table:
        print(f"    ✗ {d['name']:34s} {d['class']}({d['symptom']}) move={d['move']}")
        print(f"        {d['detail'][:150]}")
    if res.forged:
        print(f"\n  MCP FORJADO (desde cero): {res.forged.belt_ref}")
        print(f"    server={res.forged.server_name} · tools={list(res.forged.tools)}")
    print(f"\n  degraded={res.degraded}")
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
