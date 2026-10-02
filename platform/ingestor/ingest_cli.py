#!/usr/bin/env python3
"""
ingest_cli.py — Run the deterministic ingestor refresh from the command line.

Usage:
    python3 ingest_cli.py --recipe recipes/<r>.json --raw fixtures/<f> [--fetched-at ISO]
                          [--json out.json] [--sample N]

This is the $0-cognition refresh path: load recipe, extract, clean, attach
provenance, print/serialize. No model, no network. Re-running on the same file
produces the same structured output — that is the determinism the mandate
requires.
"""

from __future__ import annotations

import argparse
import json
import sys

from runner import run_ingest_from_recipe_file


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic ingestor refresh ($0 cognition).")
    ap.add_argument("--recipe", required=True, help="path to the parse recipe JSON")
    ap.add_argument("--raw", required=True, help="path to the raw file (pdf/csv)")
    ap.add_argument("--fetched-at", default=None, help="ISO timestamp of the one-off fetch")
    ap.add_argument("--json", default=None, help="write full structured result to this path")
    ap.add_argument("--sample", type=int, default=8, help="how many datums to print as a sample")
    args = ap.parse_args(argv)

    result = run_ingest_from_recipe_file(args.raw, args.recipe, fetched_at=args.fetched_at)

    print(f"recipe   : {result.recipe_id}")
    print(f"source   : {result.source.file}  sha256={result.source.sha256[:16]}…  kind={result.source.kind}")
    print(f"url      : {result.source.url}")
    print(f"datums   : {len(result.data)}  ok={result.n_ok}  errors={result.n_error}")
    print(f"refreshed: {result.refreshed_at}")
    print("\n--- sample (datum -> source/locator) ---")
    shown = 0
    for d in result.data:
        if d.value is None and d.ok:
            continue  # skip legitimate blanks in the sample for readability
        dd = d.to_dict()
        print(f"  {dd['field']!r} = {dd['value']!r}   <-  raw {dd['provenance']['raw']!r}")
        print(f"      provenance: {dd['citation']}")
        shown += 1
        if shown >= args.sample:
            break

    errs = [d for d in result.data if not d.ok]
    if errs:
        print(f"\n--- {len(errs)} cell(s) failed cleaning (reported, NOT faked) ---")
        for d in errs[:10]:
            print(f"  raw={d.provenance.raw!r} cleaner={d.cleaner} error={d.error} @ {d.provenance.locator.human()}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"\nfull result -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
