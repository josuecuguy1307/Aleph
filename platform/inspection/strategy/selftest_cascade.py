#!/usr/bin/env python3
"""
selftest_cascade.py — GATE VIVO del loop externo §4 (los 3 DONE-BARS).

  #1 openapi  — httpbin (sirve /spec.json, GETs keyless): la cascada SALE EN A
                (no corre C/D) y forja verificado. SIN cerebro.
  #2 nodoc    — PokéAPI (sin auto-descripción, sin familia): cae al par C/D y
                forja igual. D usa el CEREBRO (shim :8923).
  #3 stale    — httpbin con doc STALE (cap a 4 reales + 2 paths bogus que 404ean
                vivo): A rinde PARCIAL → switch nivel-2 → C/D recupera los faltantes.
                D usa el CEREBRO.

Todo verify-from-environment: el candado §3 (LiveValidator) es el árbitro en cada
peldaño. Corré con el venv (cryptography para Fernet) y el shim para #2/#3:

  PUPPET_BRAIN_SHIM=1 product/backend/.venv/bin/python \\
    platform/inspection/strategy/selftest_cascade.py [openapi|nodoc|stale|smoke|all]
"""
from __future__ import annotations

# ── shadow-fix ──────────────────────────────────────────────────────────────
# El módulo del contrato se llama `types.py` (lo fija la directiva). Al correr ESTE
# archivo como script, Python pone `strategy/` en sys.path[0] → un `import types`
# de la stdlib resolvería a nuestro `strategy/types.py` (circular import en enum/re).
# Sacamos el dir de este script de sys.path ANTES de importar nada de la stdlib.
# (En producción el backend corre desde la raíz de platform → strategy/ nunca es
# sys.path[0] y este problema no existe; esto solo blinda el modo script.)
import os as _os
import sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if _os.path.abspath(p or ".") != _HERE]

import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.budget import Budget  # noqa: E402
from inspection.loop.synth import tool_signature  # noqa: E402
from inspection.strategy.cascade import run_cascade  # noqa: E402
from inspection.strategy.types import Outcome, Rung  # noqa: E402


def _principal() -> C.Principal:
    return C.Principal(anon_id=f"cascade-{uuid.uuid4().hex[:12]}")


def _evprint(ev: dict) -> None:
    t = ev.get("type")
    if t == "rung.start":
        print(f"\n  ▸ PELDAÑO {ev['rung']} …")
    elif t == "rung.done":
        print(f"    {ev['rung']} → {ev['outcome']} · verified={ev['verified']} dropped={ev['dropped']} "
              f"brain={ev['used_brain']}  «{ev['notes']}»")
    elif t == "switch":
        print(f"    ⇄ SWITCH nivel-2: {ev.get('from')}→{ev.get('to')} · {ev.get('reason')}")
    elif t == "economy.skip_d":
        print(f"    ✂ {ev['reason']}")
    elif t == "forged":
        print(f"    ⚒ forjado {ev['server_name']} · {len(ev['tools'])} tools → {ev['belt_ref']}")
    elif t == "cascade.closed":
        print(f"  ▣ cerrado · winner={ev.get('winner')} tools={ev.get('tools')} "
              f"contrib={ev.get('contrib', {})}")
    elif t == "cascade.session_error":
        print(f"  ✗ puerta: {ev['detail']}")


def _summary(res) -> None:
    print("\n" + "─" * 70)
    print(f"  ok={res.ok} · winner={getattr(res.winner,'value',None)} · "
          f"early_exit={getattr(res.early_exit_at,'value',None)} · brain={res.used_brain}")
    print(f"  convergencia: {res.convergence}")
    print(f"  budget: {res.budget}")
    if res.forged:
        print(f"  MCP forjado: {res.forged.belt_ref} · {len(res.forged.tools)} tools")
        print(f"    {list(res.forged.tools)[:12]}{' …' if len(res.forged.tools)>12 else ''}")
    if res.family:
        print(f"  familia (handoff): {res.family.get('server_name')} ({res.family.get('source')})")
    for sr in res.rungs:
        print(f"    · {sr.rung.value} {sr.outcome.value} v={len(sr.verified)} d={len(sr.dropped)}")


# ── DONE-BAR #1 · openapi → salida temprana en A ───────────────────────────────
def donebar_openapi() -> bool:
    print("═" * 70 + "\n  #1 OPENAPI · httpbin → la cascada SALE EN A (sin cerebro)\n" + "═" * 70)
    res = run_cascade(
        "https://httpbin.org", "", _principal(), slug="cascade-httpbin",
        budget=Budget(max_rounds=3, max_live_calls=80, max_seconds=120),
        validate_path="/get", run_fingerprint=False, on_event=_evprint)
    _summary(res)
    ok = (res.ok and res.winner is Rung.A_SELF_DESCRIBING
          and res.early_exit_at is Rung.A_SELF_DESCRIBING
          and res.forged is not None and len(res.verified) > 0
          and not res.used_brain
          and not any(sr.rung is Rung.D_ACTIVE for sr in res.rungs))
    print(f"\n  DONE-BAR #1: {'✅ VERDE' if ok else '❌ ROJO'} "
          f"(salió en A={res.early_exit_at is Rung.A_SELF_DESCRIBING}, "
          f"sin C/D={not any(sr.rung in (Rung.C_CONVENTION, Rung.D_ACTIVE) for sr in res.rungs)}, "
          f"forjó {len(res.verified)} tools, cerebro={res.used_brain})")
    return ok


# ── DONE-BAR #2 · sin doc ni huella → C/D forja igual (cerebro) ─────────────────
def donebar_nodoc() -> bool:
    print("═" * 70 + "\n  #2 NODOC · PokéAPI → cae a C/D y forja igual (D=cerebro)\n" + "═" * 70)
    res = run_cascade(
        "https://pokeapi.co/api/v2", "", _principal(), slug="cascade-pokeapi",
        budget=Budget(max_rounds=3, max_live_calls=60, max_synth_tokens=300_000, max_seconds=300),
        validate_path="/pokemon/ditto", run_fingerprint=True, on_event=_evprint)
    _summary(res)
    d = next((sr for sr in res.rungs if sr.rung is Rung.D_ACTIVE), None)
    a = next((sr for sr in res.rungs if sr.rung is Rung.A_SELF_DESCRIBING), None)
    ok = (res.ok and res.forged is not None and len(res.verified) > 0
          and res.early_exit_at is None              # NO salió temprano (no había doc ni familia)
          and a is not None and a.outcome in (Outcome.EMPTY, Outcome.SWITCH)
          and d is not None and res.used_brain)       # D corrió con cerebro
    print(f"\n  DONE-BAR #2: {'✅ VERDE' if ok else '❌ ROJO'} "
          f"(A sin doc={a.outcome.value if a else '∅'}, D corrió={d is not None}, "
          f"cerebro={res.used_brain}, forjó {len(res.verified)} tools)")
    return ok


# ── DONE-BAR #3 · doc STALE (mitad 404) → switch → C/D recupera ─────────────────
def donebar_stale() -> bool:
    print("═" * 70 + "\n  #3 STALE · httpbin doc incompleto+bogus → A PARCIAL → switch → C/D\n" + "═" * 70)
    res = run_cascade(
        "https://httpbin.org", "", _principal(), slug="cascade-stale",
        budget=Budget(max_rounds=3, max_live_calls=60, max_synth_tokens=300_000, max_seconds=300),
        validate_path="/get",
        inject_stale_paths=("/__stale_removed_alpha", "/__stale_removed_beta"),
        max_doc_candidates=4,        # doc INCOMPLETO: solo 4 reales listadas → D recupera el resto
        run_fingerprint=False, on_event=_evprint)
    _summary(res)
    a = next((sr for sr in res.rungs if sr.rung is Rung.A_SELF_DESCRIBING), None)
    d = next((sr for sr in res.rungs if sr.rung is Rung.D_ACTIVE), None)
    a_verified = len(a.verified) if a else 0
    bogus_in_forge = any("stale_removed" in n for n in (res.forged.tools if res.forged else ()))
    ok = (res.ok and res.forged is not None
          and a is not None and a.outcome is Outcome.PARTIAL      # A rindió PARCIAL (stale)
          and a.stale_count >= 2                                   # los bogus 404earon vivo
          and len(res.switches) >= 1                               # switch nivel-2 registrado
          and d is not None and res.used_brain                     # bajó a C/D (cerebro)
          and len(res.verified) > a_verified                       # C/D RECUPERÓ faltantes
          and not bogus_in_forge)                                  # los bogus NO entraron al MCP
    print(f"\n  DONE-BAR #3: {'✅ VERDE' if ok else '❌ ROJO'} "
          f"(A parcial={a.outcome.value if a else '∅'}, stale={a.stale_count if a else 0}, "
          f"switch={len(res.switches)}, A_v={a_verified}→union={len(res.verified)}, "
          f"bogus_en_MCP={bogus_in_forge})")
    return ok


# ── smoke estructural (sin red): imports + parseo offline ───────────────────────
def smoke() -> bool:
    from inspection.strategy import openapi as O
    doc = {"openapi": "3.0.0", "servers": [{"url": "/v1"}], "info": {"title": "x"},
           "paths": {"/things": {"get": {"operationId": "listThings"}},
                     "/things/{id}": {"get": {"operationId": "getThing",
                                              "parameters": [{"name": "id", "in": "path", "required": True,
                                                              "schema": {"type": "integer"}}]}},
                     "/make": {"post": {"operationId": "mk"}}}}
    cands, meta = O._parse(doc, "https://ex.com/v1")
    names = {c.name for c in cands}
    ok = ("listThings" in names and "getThing" in names and "mk" not in names
          and all(c.method == "GET" for c in cands)
          and [c for c in cands if c.name == "getThing"][0].input_schema["x-sample-call"]["path_params"] == {})
    print(f"  smoke estructural: {'✅' if ok else '❌'}  ({len(cands)} GET candidatas, meta={meta.get('server')})")
    return ok


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    runners = {"openapi": donebar_openapi, "nodoc": donebar_nodoc,
               "stale": donebar_stale, "smoke": smoke}
    if which == "all":
        results = {k: f() for k, f in runners.items()}
        print("\n" + "═" * 70)
        for k, v in results.items():
            print(f"  {k:8s}: {'✅ VERDE' if v else '❌ ROJO'}")
        return 0 if all(results.values()) else 1
    if which in runners:
        return 0 if runners[which]() else 1
    print(f"uso: selftest_cascade.py [{'|'.join(runners)}|all]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
