"""
strategy/cascade.py — EL ORQUESTADOR del loop externo §4.

Corre el torneo A→B→C→D con SALIDA TEMPRANA real y el SWITCH NIVEL-2 de la tabla §5,
sobre UN substrate compartido (una sesión, un ledger §6, un candado §3). No relaja la
validación: cada peldaño pasa por el MISMO LiveValidator; la cascada solo decide QUÉ
candidatos se generan y CUÁNDO parar.

Reglas (encarnan el DONE-BAR):
  • A rinde COMPLETO (verificadas, 0 stale) → SALIDA TEMPRANA en A, no corre B/C/D.
  • A rinde PARCIAL (mitad 404 = doc STALE) → forjá lo vivo + bajá a C/D por los faltantes.
  • A vacío / todo-404 → B (huella). B resuelve+valida una familia → handoff, salida temprana.
  • Sin doc ni huella → el par C/D (C convención barata + D cerebro) forja igual y se unen.

La forja es ÚNICA, al final, desde la UNIÓN deduplicada de verificadas — así un doc
stale más el rescate de C/D producen UN MCP coherente, no tres parciales.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.budget import Budget, Ledger  # noqa: E402
from inspection.loop.emit import MCPEmitter  # noqa: E402
from inspection.loop.guard import PublicHTTPGuard  # noqa: E402
from inspection.loop.live_http import LiveHTTP  # noqa: E402
from inspection.loop.session import TMDBTokenSession  # noqa: E402
from inspection.loop.synth import tool_signature  # noqa: E402
from inspection.loop.validator import LiveValidator  # noqa: E402
from inspection.strategy.rungs import RungA, RungB, RungC, RungD  # noqa: E402
from inspection.strategy.types import (  # noqa: E402
    CascadeResult, Outcome, Rung, StrategyContext, StrategyResult,
)

#: si C ya forjó al menos esto y NO estamos rescatando un doc stale, NO quemamos el
#: cerebro de D (economía §6: A/B/C baratos; D solo cuando hace falta).
_C_ENOUGH = 5


def build_context(
    base_url: str, api_key: str, principal: C.Principal, *,
    slug: str = "cascade-live", budget: Optional[Budget] = None,
    auth_param: str = "api_key", validate_path: str = "/configuration",
    validate_query: Optional[dict] = None, soft_error_keys: tuple = (),
    soft_notice_keys: tuple = (), dispatch_param: Optional[str] = None,
    min_interval: float = 0.0, api_shape_hint: str = "", passive_probes: tuple = (),
    master_secret: Optional[str] = None, cred_root: Path = C.SYNTH_BELTS_DIR,
    synth_alias: str = "brain", on_event=None,
) -> StrategyContext:
    """Construye el substrate COMPARTIDO: guard (Capa 0), sesión validada+cifrada
    (Capa 1), http keyed/discovery, candado (Capa 4), ledger §6. Levanta
    C.SessionError si la puerta no abre (la key no vale / target inalcanzable)."""
    budget = budget or Budget()
    guard = PublicHTTPGuard()
    ledger = Ledger(budget)

    provider = TMDBTokenSession(
        base_url, api_key, principal, slug,
        auth_param=auth_param, validate_path=validate_path, validate_query=validate_query,
        soft_error_keys=soft_error_keys, soft_notice_keys=soft_notice_keys,
        min_interval=min_interval, guard=guard, master_secret=master_secret, cred_root=cred_root)
    session = provider.acquire()         # guard + valida key viva + cifra cred (Capa 1)
    ledger.add_calls(1)                  # la call de validación cuenta contra el techo §6

    keyed_http = LiveHTTP(secret=provider.secret, auth_param=auth_param,
                          ledger=ledger, min_interval=min_interval)
    discovery_http = LiveHTTP(secret="", auth_param=auth_param,
                              ledger=ledger, min_interval=min_interval)  # docs públicas: sin key
    validator = LiveValidator(keyed_http, soft_error_keys=soft_error_keys,
                              soft_notice_keys=soft_notice_keys, ledger=ledger)

    return StrategyContext(
        base_url=base_url, api_key=api_key, principal=principal, slug=slug,
        guard=guard, session=session, keyed_http=keyed_http, discovery_http=discovery_http,
        validator=validator, ledger=ledger, budget=budget,
        auth_param=auth_param, validate_path=validate_path, validate_query=validate_query,
        soft_error_keys=soft_error_keys, soft_notice_keys=soft_notice_keys,
        dispatch_param=dispatch_param, min_interval=min_interval, api_shape_hint=api_shape_hint,
        passive_probes=passive_probes, master_secret=master_secret, cred_root=cred_root,
        synth_alias=synth_alias, on_event=on_event)


def run_cascade(
    base_url: str, api_key: str, principal: C.Principal, *,
    slug: str = "cascade-live", budget: Optional[Budget] = None,
    inject_stale_paths: tuple[str, ...] = (), max_doc_candidates: int = 0,
    run_fingerprint: bool = True, on_event=None, **knobs,
) -> CascadeResult:
    """El torneo completo. `knobs` son las perillas del target (auth_param,
    validate_path, soft_*_keys, dispatch_param, min_interval, api_shape_hint,
    passive_probes, …) que se reenvían a build_context y a rung D."""
    def emit(ev: dict) -> None:
        if on_event:
            on_event(ev)

    try:
        ctx = build_context(base_url, api_key, principal, slug=slug, budget=budget,
                            on_event=on_event, **knobs)
    except C.SessionError as e:
        emit({"type": "cascade.session_error", "detail": str(e)})
        return CascadeResult(ok=False, base_url=base_url, error=str(e))

    dispatch = ctx.dispatch_param or ""
    union: dict[str, C.VerifiedTool] = {}     # firma → VerifiedTool (dedup entre peldaños)
    contrib: dict[Rung, int] = {}
    trace: list[StrategyResult] = []
    switches: list[dict] = []

    def absorb(sr: StrategyResult) -> int:
        added = 0
        for vt in sr.verified:
            sig = tool_signature(vt.candidate, dispatch)
            if sig not in union:
                union[sig] = vt
                added += 1
        if added:
            contrib[sr.rung] = contrib.get(sr.rung, 0) + added
        return added

    def record(sr: StrategyResult) -> None:
        trace.append(sr)
        emit({"type": "rung.done", "rung": sr.rung.value, "outcome": sr.outcome.value,
              "verified": len(sr.verified), "dropped": len(sr.dropped),
              "used_brain": sr.used_brain, "notes": sr.notes})

    # ── PELDAÑO A · autodescriptivo ─────────────────────────────────────────────
    emit({"type": "rung.start", "rung": "A"})
    a = RungA(inject_stale_paths=inject_stale_paths, max_doc_candidates=max_doc_candidates).propose(ctx)
    record(a)
    absorb(a)
    if a.outcome is Outcome.YIELDED and a.verified:
        forged = _forge(ctx, union)
        emit({"type": "cascade.closed", "winner": "A", "early_exit": "A", "tools": len(union)})
        return CascadeResult(
            ok=True, base_url=base_url, winner=Rung.A_SELF_DESCRIBING,
            early_exit_at=Rung.A_SELF_DESCRIBING, forged=forged,
            verified=tuple(union.values()), rungs=tuple(trace), switches=(),
            budget=ctx.ledger.snapshot(),
            convergence="A · autodescriptivo: doc completo verificado (salida temprana, no corrió B/C/D)")
    if a.outcome is Outcome.PARTIAL:
        switches.append({"from": "A", "to": "C/D", "level": C.FailureLevel.SWITCH_STRATEGY.value,
                         "reason": f"OpenAPI STALE: {a.stale_count} endpoint(s) 404 vivo → forjo lo vivo "
                                   f"y bajo a C/D por los faltantes", "verified_kept": len(a.verified)})
        emit({"type": "switch", **switches[-1]})
    elif a.outcome is Outcome.REJECTED and a.aggregate_failure is C.FailureClass.ALL_404_OPENAPI:
        switches.append({"from": "A", "to": "B/C/D", "level": C.FailureLevel.SWITCH_STRATEGY.value,
                         "aggregate": a.aggregate_failure.name, "move": a.aggregate_failure.move,
                         "reason": "doc presente pero TODO 404 vivo (doc 100% stale / base equivocada) "
                                   "→ estrategia equivocada, cambio de peldaño"})
        emit({"type": "switch", **switches[-1]})

    # ── PELDAÑO B · huella → resolver (salida temprana si valida una familia) ─────
    # Solo si todavía no forjamos nada (si A fue PARCIAL ya tenemos surface → directo a C/D).
    if run_fingerprint and not union:
        emit({"type": "rung.start", "rung": "B"})
        b = RungB().propose(ctx)
        record(b)
        if b.won:
            emit({"type": "cascade.closed", "winner": "B", "early_exit": "B",
                  "family": (b.family or {}).get("server_name")})
            return CascadeResult(
                ok=True, base_url=base_url, winner=Rung.B_FINGERPRINT,
                early_exit_at=Rung.B_FINGERPRINT, forged=None, family=b.family,
                verified=(), rungs=tuple(trace), switches=tuple(switches),
                budget=ctx.ledger.snapshot(),
                convergence=f"B · huella: familia conocida resuelta+validada → handoff al resolver "
                            f"({(b.family or {}).get('server_name')})")

    # ── PAR C/D · fallback (C convención barata + D cerebro; corren juntos, se unen) ─
    emit({"type": "rung.start", "rung": "C"})
    c = RungC().propose(ctx)
    record(c)
    absorb(c)

    stale_recovery = a.outcome in (Outcome.PARTIAL, Outcome.REJECTED)
    need_d = stale_recovery or len(union) < _C_ENOUGH
    if need_d and ctx.ledger.exhausted() is None:
        emit({"type": "rung.start", "rung": "D"})
        d = RungD().propose(ctx)
        record(d)
        absorb(d)
    elif not need_d:
        emit({"type": "economy.skip_d", "reason": f"C ya forjó {len(union)} tools (≥{_C_ENOUGH}) sin stale → no quemo el cerebro"})

    # ── FORJA ÚNICA desde la unión ───────────────────────────────────────────────
    if not union:
        emit({"type": "cascade.closed", "winner": None, "tools": 0})
        return CascadeResult(
            ok=False, base_url=base_url, rungs=tuple(trace), switches=tuple(switches),
            budget=ctx.ledger.snapshot(),
            convergence="ningún peldaño sobrevivió el candado §3 (sin tools verificadas)",
            error="0 tools verificadas")

    forged = _forge(ctx, union)
    winner = max(contrib, key=lambda r: (contrib[r], _depth(r))) if contrib else None
    emit({"type": "cascade.closed", "winner": getattr(winner, "value", None),
          "tools": len(union), "contrib": {r.value: n for r, n in contrib.items()}})
    return CascadeResult(
        ok=True, base_url=base_url, winner=winner, early_exit_at=None, forged=forged,
        verified=tuple(union.values()), family=next((t.family for t in trace if t.family), None),
        rungs=tuple(trace), switches=tuple(switches), budget=ctx.ledger.snapshot(),
        convergence=_convergence_note(contrib, switches))


def _forge(ctx: StrategyContext, union: dict) -> C.ForgedMCP:
    emitter = MCPEmitter(ctx.principal, ctx.slug, ctx.base_url, auth_param=ctx.auth_param,
                         cred_root=ctx.cred_root, min_interval=ctx.min_interval)
    forged = emitter.emit(tuple(union.values()))
    ctx.emit({"type": "forged", "server_name": forged.server_name,
              "belt_ref": forged.belt_ref, "tools": list(forged.tools)})
    return forged


def _depth(r: Rung) -> int:
    return {Rung.A_SELF_DESCRIBING: 0, Rung.B_FINGERPRINT: 1,
            Rung.C_CONVENTION: 2, Rung.D_ACTIVE: 3}[r]


def _convergence_note(contrib: dict, switches: list) -> str:
    src = " + ".join(f"{r.value}({n})" for r, n in sorted(contrib.items(), key=lambda kv: _depth(kv[0])))
    sw = f" · {len(switches)} switch(es) nivel-2" if switches else ""
    return f"forjado de la unión {src}{sw}"


__all__ = ["build_context", "run_cascade"]
