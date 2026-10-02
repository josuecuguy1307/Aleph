"""
dispatch/dispatcher.py — LA COSTURA §0.5: classifier → gate → {confiable | dudoso | nada}.

Determinístico (routing + confirm, sin cerebro). El classifier es read-only y NO dispara
gate; el GATE VISIBLE va ANTES de cualquier path que toque el mundo (probear/forjar conecta a
un MCP externo, usa creds, abre superficie SSRF = alta consecuencia). Preguntar por defecto;
toggle opt-in `auto=True` para el power user.

Los 3 paths montan sobre lo que YA existe:
  • CONFIABLE → liveness.probe (confirma que el MCP vive y sirve los tools) → equip_resolved
                (forja SEGURA: credencial como placeholder ${VAR}, secreto al vault Fernet).
  • DUDOSO   → liveness.probe(allowed=borrador) + tools/call → probe_mcp ARBITRA: real forjado,
                phantom (no listado) y caído (no responde) dropeados. CERO cerebro. Si nada
                sobrevive / el MCP no conecta → fall-through a la cascada (auto-sana, como el moat).
  • NADA     → run_cascade(base_url, …) (el motor REST desde cero; YA existe, se invoca).

Frontera: SOLO llama funciones públicas read-only (classify, liveness, equip_resolved,
run_cascade). NO edita resolver/byo_mcp/library/loop/strategy/contracts.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import byo_mcp, contracts as C, mcp_resolver  # noqa: E402  (read-only)
# [Casa 2 · Fase 4 · carve] run_cascade (strategy.cascade = FORGE) NO se importa top-level:
# el path found→equip (curado) no lo toca; sólo el path NADA/forja. Import LAZY en _nada,
# con honest-fail si forge no viaja (cliente sin puente). Ver inspection/zones.py.
from inspection.dispatch import liveness                      # noqa: E402
from inspection.dispatch.classifier import classify           # noqa: E402
from inspection.dispatch.models import (                      # noqa: E402
    DispatchResult, Draft, GateRequest, Verdict,
)


# ── el GATE VISIBLE §0.5 (determinístico) ────────────────────────────────────────
def _gate(req: GateRequest, *, auto: bool,
          confirm: Optional[Callable[[GateRequest], bool]]) -> tuple[bool, bool]:
    """Devuelve (shown, allowed). `auto` salta el gate (toggle power-user). Sin auth y sin
    confirm → no se puede pedir permiso → NO se toca el mundo (fail-closed)."""
    if auto:
        return False, True
    if confirm is None:
        return False, False
    return True, bool(confirm(req))


def _redacted_target(spec: dict) -> str:
    if (spec.get("transport") or "").lower() == "http":
        return spec.get("url") or ""
    cmd = spec.get("command") or ""
    args = " ".join(str(a) for a in (spec.get("args") or []))
    return (cmd + (" " + args if args else "")).strip()


def _resolution(draft: Draft) -> dict:
    """La forma que equip_resolved consume (spec + identidad del server)."""
    return {"spec": draft.spec, "server_name": draft.server_name,
            "source": draft.source, "vendor_kind": draft.vendor_kind}


def _blocked(verdict: Verdict, draft: Optional[Draft], *, shown: bool, reason: str) -> DispatchResult:
    return DispatchResult(verdict=verdict, path="blocked", ok=False, gate_shown=shown,
                          server_name=(draft.server_name if draft else ""),
                          source=(draft.source if draft else ""), reason=reason)


# ── el entry público (CONTRATO CONGELADO) ────────────────────────────────────────
def dispatch(
    service: str,
    secret: Optional[str] = None,
    principal: Optional[C.Principal] = None,
    *,
    puppet_id: Optional[str] = None,
    auto: bool = False,
    confirm: Optional[Callable[[GateRequest], bool]] = None,
    base_url: Optional[str] = None,
    guard: Optional[C.SSRFGuard] = None,
    verify_calls: bool = True,
    cascade_fn: Optional[Callable[..., Any]] = None,
    classify_fn: Optional[Callable[..., Any]] = None,
    candidates: Optional[list[dict]] = None,
    conn: Any = None,
    **knobs: Any,
) -> DispatchResult:
    """service (+ credencial del vault) → pieza equipada, ruteando por veredicto.

    `secret` ya viene del VAULT (el caller lo resolvió; nunca texto plano del request).
    `confirm(GateRequest)->bool` es el gate visible; `auto=True` lo saltea. `base_url` es el
    target REST para el path NADA (forja desde cero). `cascade_fn`/`classify_fn`/`candidates`
    son inyectables para fixtures determinísticos.
    """
    _classify = classify_fn or classify
    verdict, draft = _classify(service, candidates=candidates)

    if verdict is Verdict.NADA or draft is None:
        return _nada(service, secret, principal, base_url=base_url, auto=auto, confirm=confirm,
                     cascade_fn=cascade_fn, knobs=knobs)
    if verdict is Verdict.CONFIABLE:
        return _confiable(draft, secret, principal, puppet_id=puppet_id, auto=auto,
                          confirm=confirm, guard=guard, base_url=base_url, conn=conn,
                          cascade_fn=cascade_fn, knobs=knobs)
    return _dudoso(draft, secret, principal, puppet_id=puppet_id, auto=auto, confirm=confirm,
                   guard=guard, verify_calls=verify_calls, base_url=base_url, conn=conn,
                   cascade_fn=cascade_fn, knobs=knobs)


# ── CONFIABLE · probe de liveness → equip ────────────────────────────────────────
def _confiable(draft, secret, principal, *, puppet_id, auto, confirm, guard, base_url, conn,
               cascade_fn, knobs) -> DispatchResult:
    req = GateRequest(service=draft.service, verdict=Verdict.CONFIABLE, action="probe+equip",
                      server_name=draft.server_name, transport=draft.spec.get("transport", ""),
                      target=_redacted_target(draft.spec),
                      needs_credential=bool(draft.spec.get("needs_credential")))
    shown, allowed = _gate(req, auto=auto, confirm=confirm)
    if not allowed:
        return _blocked(Verdict.CONFIABLE, draft, shown=shown, reason="usuario no confirmó el gate")
    try:
        probe = liveness.probe(draft.spec, secret, guard=guard)     # liveness: vive + sirve tools
    except (byo_mcp.BYOValidationError, liveness.GuardDenied) as e:
        return _fallthrough(Verdict.CONFIABLE, draft, secret, principal, base_url=base_url,
                            cascade_fn=cascade_fn, knobs=knobs, shown=shown, why=str(e))
    equipped = _equip(draft, probe, principal=principal, puppet_id=puppet_id, conn=conn)
    names = tuple(t["name"] for t in probe["tools"])
    return DispatchResult(
        verdict=Verdict.CONFIABLE, path="confiable", ok=True, forged=equipped, verified=names,
        used_brain=False, gate_shown=shown, source=draft.source, server_name=draft.server_name,
        reason=draft.reason, meta={"vendor_kind": draft.vendor_kind, "tools": len(names)})


# ── DUDOSO · probe arbitra (real forjado, phantom + caído dropeados) ──────────────
def _dudoso(draft, secret, principal, *, puppet_id, auto, confirm, guard, verify_calls,
            base_url, conn, cascade_fn, knobs) -> DispatchResult:
    req = GateRequest(service=draft.service, verdict=Verdict.DUDOSO, action="probe+equip",
                      server_name=draft.server_name, transport=draft.spec.get("transport", ""),
                      target=_redacted_target(draft.spec),
                      needs_credential=bool(draft.spec.get("needs_credential")),
                      claimed_tools=draft.claimed_tools)
    shown, allowed = _gate(req, auto=auto, confirm=confirm)
    if not allowed:
        return _blocked(Verdict.DUDOSO, draft, shown=shown, reason="usuario no confirmó el gate")

    claimed = list(draft.claimed_tools) or None
    try:
        probe = liveness.probe(draft.spec, secret, guard=guard, allowed_tools=claimed)
    except (byo_mcp.BYOValidationError, liveness.GuardDenied) as e:
        # el MCP no conecta / no lista nada usable → fall-through a la cascada (auto-sana)
        return _fallthrough(Verdict.DUDOSO, draft, secret, principal, base_url=base_url,
                            cascade_fn=cascade_fn, knobs=knobs, shown=shown, why=str(e))

    live = [t["name"] for t in probe["tools"]]
    dropped: set[str] = set(draft.claimed_tools) - set(live) if draft.claimed_tools else set()

    if verify_calls and live:
        alive, dead = liveness.call_liveness(draft.spec, secret, live)
        dropped |= dead
        live = [n for n in live if n in alive]
        probe = {**probe, "tools": [t for t in probe["tools"] if t["name"] in alive]}

    if not live:
        return _fallthrough(Verdict.DUDOSO, draft, secret, principal, base_url=base_url,
                            cascade_fn=cascade_fn, knobs=knobs, shown=shown,
                            why="ningún tool del borrador sobrevivió el candado (todo phantom/caído)")

    equipped = _equip(draft, probe, principal=principal, puppet_id=puppet_id, conn=conn)
    return DispatchResult(
        verdict=Verdict.DUDOSO, path="dudoso", ok=True, forged=equipped, verified=tuple(live),
        dropped=tuple(sorted(dropped)), used_brain=False, gate_shown=shown, source=draft.source,
        server_name=draft.server_name, reason=draft.reason,
        meta={"claimed": list(draft.claimed_tools), "forged": len(live), "dropped": len(dropped)})


# ── NADA · forja desde cero (run_cascade) ────────────────────────────────────────
def _nada(service, secret, principal, *, base_url, auto, confirm, cascade_fn, knobs) -> DispatchResult:
    if not base_url:
        return DispatchResult(
            verdict=Verdict.NADA, path="nada", ok=False,
            reason="sin MCP confiable y sin base_url REST → nada que forjar desde cero "
                   "(pasa base_url para la cascada)")
    req = GateRequest(service=service, verdict=Verdict.NADA, action="forge-from-scratch",
                      transport="http", target=base_url, needs_credential=bool(secret))
    shown, allowed = _gate(req, auto=auto, confirm=confirm)
    if not allowed:
        return DispatchResult(verdict=Verdict.NADA, path="blocked", ok=False, gate_shown=shown,
                              reason="usuario no confirmó el gate")
    run = cascade_fn
    if run is None:
        try:
            from inspection.strategy.cascade import run_cascade   # FORGE (lazy)
        except ImportError:
            # [carve] forge/ no viaja al cliente (D-A). Sin puente (4.2) y sin forja local →
            # honest fail-closed. Forjar es premium / control-plane, nunca crash ni stub.
            return DispatchResult(verdict=Verdict.NADA, path="nada", ok=False,
                                  reason="forjar = premium / control-plane")
        run = run_cascade
    cr = run(base_url, secret or "", principal, **knobs)
    ok = bool(getattr(cr, "ok", False))
    verified = tuple(getattr(vt, "candidate", vt).name if hasattr(getattr(vt, "candidate", vt), "name")
                     else str(vt) for vt in (getattr(cr, "verified", ()) or ()))
    return DispatchResult(
        verdict=Verdict.NADA, path="nada", ok=ok, forged=getattr(cr, "forged", None),
        verified=verified, used_brain=bool(getattr(cr, "used_brain", False)), gate_shown=shown,
        source="cascade", reason=getattr(cr, "convergence", "") or getattr(cr, "error", ""),
        meta={"routed_to": "run_cascade"})


# ── helpers compartidos ──────────────────────────────────────────────────────────
def _equip(draft: Draft, probe: dict, *, principal, puppet_id, conn) -> dict:
    """Forja SEGURA reusando resolver.equip_resolved (placeholder ${VAR} + vault Fernet +
    belt_refs/keys.byok_ref). user_id sale del principal autenticado (anon → forja anon)."""
    user_id = principal.user_id if (principal and getattr(principal, "user_id", None)) else None
    return mcp_resolver.equip_resolved(_resolution(draft), probe, user_id=user_id,
                                       puppet_id=puppet_id, service=draft.service, conn=conn)


def _fallthrough(verdict, draft, secret, principal, *, base_url, cascade_fn, knobs,
                 shown, why) -> DispatchResult:
    """El candado no dejó pasar nada (o el MCP cayó) → auto-sana a la cascada genérica si hay
    base_url. Si no, devuelve el fallo honesto (sin teatro)."""
    if base_url:
        res = _nada(draft.service, secret, principal, base_url=base_url, auto=True,
                    confirm=None, cascade_fn=cascade_fn, knobs=knobs)
        return DispatchResult(
            verdict=verdict, path="fallthrough", ok=res.ok, forged=res.forged,
            verified=res.verified, used_brain=res.used_brain, gate_shown=shown,
            source="cascade", server_name=draft.server_name,
            reason=f"{verdict.value} no sobrevivió ({why}) → cascada genérica", meta=res.meta)
    return DispatchResult(
        verdict=verdict, path=verdict.value, ok=False, gate_shown=shown,
        server_name=draft.server_name, source=draft.source,
        reason=f"{verdict.value} no sobrevivió el candado y no hay base_url para fall-through: {why}")


__all__ = ["dispatch"]
