#!/usr/bin/env python3
"""
run_tmdb.py — corredor VIVO del loop interno contra TMDB (la demo end-to-end).

Toma `base_url + api_key` CRUDOS (la key por env TMDB_API_KEY o --key) y deja correr
el loop §3 contra TMDB v3, imprimiendo el working set vuelta a vuelta, las tools
verificadas, las candidatas dropeadas por la tabla §5, y el MCP forjado.

Uso:
    TMDB_API_KEY=xxxxxxxx PUPPET_BRAIN_SHIM=1 \\
      product/backend/.venv/bin/python platform/inspection/loop/run_tmdb.py

    # forzar degradado (cerebro caído → degraded:true honesto):
    TMDB_API_KEY=xxxx PUPPET_BRAIN_SHIM_BASE_URL=http://127.0.0.1:1/v1 \\
      python platform/inspection/loop/run_tmdb.py --degraded
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
from inspection.loop.engine import TMDB_BASE, run_internal_loop  # noqa: E402


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
        if ev["frontier_opened"]:
            print(f"          ↟ frontera +{ev['frontier_opened']}")
    elif t == "forged":
        print(f"\n  ⚒  MCP forjado: {ev['server_name']} · {len(ev['tools'])} tools → {ev['belt_ref']}")
    elif t == "closed":
        print(f"\n  ▣ cerrado: {ev['convergence']} · verified={ev['verified']} "
              f"dropped={ev['dropped']} degraded={ev['degraded']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("TMDB_API_KEY", ""))
    ap.add_argument("--base", default=os.environ.get("TMDB_BASE", TMDB_BASE))
    ap.add_argument("--degraded", action="store_true", help="documenta que se espera caída del cerebro")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--max-calls", type=int, default=60)
    # techo alto a propósito: el shim (proxy Claude Code) inyecta ~12k tok de contexto
    # por llamada, así que medimos por rounds/calls/tiempo, no por el overhead del proxy.
    ap.add_argument("--max-tokens", type=int, default=300_000)
    args = ap.parse_args()

    if not args.key:
        print("ERROR: falta la api_key de TMDB (env TMDB_API_KEY o --key).", file=sys.stderr)
        print("Consíguela gratis en https://www.themoviedb.org/settings/api (API Key v3).",
              file=sys.stderr)
        return 2

    principal = C.Principal(anon_id=f"run-tmdb-{uuid.uuid4().hex[:12]}")
    budget = Budget(max_rounds=args.rounds, max_live_calls=args.max_calls,
                    max_synth_tokens=args.max_tokens)

    print("═" * 72)
    print(f"  LOOP INTERNO §3 · vivo contra {args.base}")
    print("═" * 72)
    res = run_internal_loop(args.base, args.key, principal, slug="tmdb-live",
                            budget=budget, on_event=_print_event)

    print("\n" + "─" * 72)
    print("  RESUMEN")
    print("─" * 72)
    if res.error:
        print(f"  ✗ {res.error}")
        return 1
    print(f"  convergencia: {res.convergence}")
    print(f"  budget: {res.budget}")
    print(f"\n  TOOLS VERIFICADAS (llamadas vivas, respondieron) — {len(res.verified)}:")
    for v in res.verified:
        print(f"    ✓ {v.candidate.name:32s} {v.candidate.method} {v.candidate.endpoint}  [{v.verified_by}]")
    print(f"\n  CANDIDATAS DROPEADAS por la tabla §5 — {len(res.dropped)}:")
    for d in res.dropped_by_failure_table:
        print(f"    ✗ {d['endpoint']:40s} {d['class']}({d['symptom']}) {d['level']} move={d['move']}")
    if res.forged:
        print(f"\n  MCP FORJADO (desde cero): {res.forged.belt_ref}")
        print(f"    server={res.forged.server_name} · tools={list(res.forged.tools)}")
    print(f"\n  degraded={res.degraded}")
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
