#!/usr/bin/env python3
"""
selftest_reinject.py — DONE-BAR VIVO de FASE 3 (el moat §8 PROBADO, no afirmado).

Mide la CONVERGENCIA RELATIVA: la 1ra vez contra un software (almacén vacío) corre
la cascada §4 entera; la 2da vez contra la MISMA familia matchea la huella, reinyecta
la ganadora y converge en 1 batch — MEDIBLE menos calls/vueltas/tokens, SIN cerebro.

  product/backend/.venv/bin/python platform/inspection/library/selftest_reinject.py [httpbin|pokeapi|all]
  # pokeapi (cerebro): PUPPET_BRAIN_SHIM=1 … selftest_reinject.py pokeapi

Casos:
  httpbin — DETERMINISTA, sin cerebro. 1ra vez gana en A (sniff+parse+valida); 2da vez
            host-key pega GRATIS → revalida priors en 1 batch. B.calls < A.calls.
  pokeapi — el HEADLINE (necesita shim). 1ra vez cae a D (cerebro: vueltas+tokens);
            2da vez reinyecta → 0 cerebro, 0 tokens, calls ≪ A.

La generalización CROSS-HOST de la huella (familia, no instancia) se prueba OFFLINE en
selftest_store.py (hosts distintos → mismo family_id + shape_hash). Acá se prueba que
la reinyección es REAL (revalida vivo, verify-before-trust) y converge MÁS BARATO.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _HERE]

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C                 # noqa: E402
from inspection.loop.budget import Budget             # noqa: E402
from inspection.library import store                  # noqa: E402
from inspection.library.reinject import inspect_target  # noqa: E402


def _principal() -> C.Principal:
    return C.Principal(anon_id=f"lib-{uuid.uuid4().hex[:12]}")


def _ev(tag):
    def f(ev):
        t = ev.get("type", "")
        if t in ("reinject.hit", "reinject.sniff", "reinject.forged", "reinject.diverged",
                 "capture", "cascade.closed", "economy.skip_d"):
            print(f"      [{tag}] {t}: { {k: v for k, v in ev.items() if k != 'type'} }")
    return f


def _b(res) -> dict:
    return {"calls": res.budget.get("live_calls", 0), "tokens": res.budget.get("synth_tokens", 0),
            "rounds": res.budget.get("rounds", 0), "brain": res.used_brain}


def _table(a, b) -> None:
    print(f"\n      {'':14} {'calls':>7} {'tokens':>8} {'rounds':>7} {'brain':>6}")
    print(f"      {'1ra vez (A)':14} {a['calls']:>7} {a['tokens']:>8} {a['rounds']:>7} {str(a['brain']):>6}")
    print(f"      {'reinyect (B)':14} {b['calls']:>7} {b['tokens']:>8} {b['rounds']:>7} {str(b['brain']):>6}")


# ── httpbin · determinista, sin cerebro ─────────────────────────────────────────
def donebar_httpbin() -> bool:
    print("═" * 72 + "\n  HTTPBIN · 1ra vez gana en A · 2da vez host-key GRATIS → reinyecta\n" + "═" * 72)
    root = Path(tempfile.mkdtemp(prefix="cap-httpbin-"))
    knobs = dict(validate_path="/get", run_fingerprint=False, max_doc_candidates=8)

    print("\n  ▸ 1ra vez (almacén vacío) → cascada completa + captura")
    a = inspect_target("https://httpbin.org", "", _principal(), slug="lib-httpbin-a",
                       budget=Budget(max_rounds=3, max_live_calls=80, max_seconds=120),
                       root=root, on_event=_ev("A"), **knobs)
    print(f"    source={a.source} ok={a.ok} captured={a.captured} family={a.family_id} "
          f"forjó={len(a.verified)} brain={a.used_brain}")

    print("\n  ▸ 2da vez (misma familia) → lookup por huella → reinyección")
    b = inspect_target("https://httpbin.org", "", _principal(), slug="lib-httpbin-b",
                       budget=Budget(max_rounds=3, max_live_calls=80, max_seconds=120),
                       root=root, on_event=_ev("B"), **knobs)
    print(f"    source={b.source} ok={b.ok} reinjected={b.reinjected} family={b.family_id} "
          f"revalidó={len(b.verified)} brain={b.used_brain}")

    ba, bb = _b(a), _b(b)
    _table(ba, bb)
    ok = (a.ok and a.captured and not a.used_brain
          and b.ok and b.reinjected and not b.used_brain
          and b.family_id == a.family_id
          and len(b.verified) > 0
          and bb["calls"] < ba["calls"])      # reinyección se ahorró el descubrimiento
    store.clear(root=root)
    print(f"\n  DONE-BAR httpbin: {'✅ VERDE' if ok else '❌ ROJO'} "
          f"(captura→reinyecta misma familia · B.calls {bb['calls']} < A.calls {ba['calls']} · 0 cerebro)")
    return ok


# ── pokeapi · el headline (cerebro → reinyección sin cerebro) ───────────────────
def donebar_pokeapi() -> bool:
    print("═" * 72 + "\n  POKEAPI · 1ra vez D=cerebro · 2da vez reinyecta SIN cerebro (B ≪ A)\n" + "═" * 72)
    if not os.environ.get("PUPPET_BRAIN_SHIM"):
        print("  ⚠ SKIP: necesita PUPPET_BRAIN_SHIM=1 (la 1ra vez usa el cerebro). "
              "Corre:\n    PUPPET_BRAIN_SHIM=1 <venv>/python selftest_reinject.py pokeapi")
        return True   # no-rojo: skip explícito, no falla el gate
    root = Path(tempfile.mkdtemp(prefix="cap-pokeapi-"))
    knobs = dict(validate_path="/pokemon/ditto", run_fingerprint=False)
    big = lambda: Budget(max_rounds=3, max_live_calls=60, max_synth_tokens=300_000, max_seconds=300)

    print("\n  ▸ 1ra vez → A vacío → C/D (cerebro mina endpoints) + captura")
    a = inspect_target("https://pokeapi.co/api/v2", "", _principal(), slug="lib-poke-a",
                       budget=big(), root=root, on_event=_ev("A"), **knobs)
    print(f"    source={a.source} ok={a.ok} captured={a.captured} family={a.family_id} "
          f"forjó={len(a.verified)} brain={a.used_brain}")

    print("\n  ▸ 2da vez → host-key GRATIS → reinyecta priors → 1 batch, 0 cerebro")
    b = inspect_target("https://pokeapi.co/api/v2", "", _principal(), slug="lib-poke-b",
                       budget=big(), root=root, on_event=_ev("B"), **knobs)
    print(f"    source={b.source} ok={b.ok} reinjected={b.reinjected} family={b.family_id} "
          f"revalidó={len(b.verified)} brain={b.used_brain}")

    ba, bb = _b(a), _b(b)
    _table(ba, bb)
    ok = (a.ok and a.captured and a.used_brain          # 1ra vez SÍ usó cerebro
          and b.ok and b.reinjected and not b.used_brain  # 2da vez NO
          and b.family_id == a.family_id
          and len(b.verified) > 0
          and bb["tokens"] == 0 and bb["tokens"] < ba["tokens"]   # 0 tokens vs >0
          and bb["calls"] < ba["calls"])                          # menos calls
    store.clear(root=root)
    print(f"\n  DONE-BAR pokeapi: {'✅ VERDE' if ok else '❌ ROJO'} "
          f"(A cerebro={ba['brain']} tokens={ba['tokens']} calls={ba['calls']} → "
          f"B cerebro={bb['brain']} tokens={bb['tokens']} calls={bb['calls']})")
    return ok


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    runners = {"httpbin": donebar_httpbin, "pokeapi": donebar_pokeapi}
    if which == "all":
        results = {k: f() for k, f in runners.items()}
        print("\n" + "═" * 72)
        for k, v in results.items():
            print(f"  {k:8s}: {'✅ VERDE' if v else '❌ ROJO'}")
        return 0 if all(results.values()) else 1
    if which in runners:
        return 0 if runners[which]() else 1
    print(f"uso: selftest_reinject.py [{'|'.join(runners)}|all]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
