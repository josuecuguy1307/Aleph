"""
strategy/rungs.py — los 4 PELDAÑOS de la cascada §4. Cada uno produce priors y los
pasa por el candado §3 compartido (ctx.validator); ninguno forja (eso lo hace el
orquestador, UNA vez, desde la unión). "Rinde" = candidatas sobreviven el candado.

  A · AUTODESCRIPTIVO — sniff /openapi.json + parseo → CandidateTool · SIN cerebro.
  B · HUELLA          — ¿familia conocida? → reusa el RESOLVER (mcp_resolver) · SIN cerebro.
  C · CONVENCIÓN      — /api/v1 + raíz + validate_path como reads · SIN cerebro.
  D · ACTIVO          — run_internal_loop (cerebro Opus + minería de frontera) · CON cerebro.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.budget import Budget  # noqa: E402
from inspection.loop.engine import run_internal_loop  # noqa: E402
from inspection.strategy import openapi as _openapi  # noqa: E402
from inspection.strategy.types import (  # noqa: E402
    DiscoverySignal, Outcome, Rung, Strategy, StrategyContext, StrategyResult,
)


# un doc se considera STALE (worth bajar a C/D a recuperar) solo si una FRACCIÓN
# real de sus endpoints 404ea vivo. Un 404 incidental (1 endpoint muerto en un doc
# por lo demás correcto) NO arrastra a toda la cascada al fallback: se dropea esa tool
# y A gana igual. La distinción §5 es "tool equivocada" (drop suelto) vs "estrategia
# equivocada" (el doc no describe el software vivo) — y eso es proporción, no un 404.
_STALE_RATIO = 0.25


def _classify_batch(verified: Sequence, dropped: Sequence, *, had_doc_signal: bool):
    """Calcula el outcome + la clase §5 AGREGADA del lote (el switch nivel-2 vive acá,
    no en el validador per-tool). Un 404 suelto = drop interno; una fracción ≥25% en
    404 = doc STALE (PARTIAL); TODO 404 con señal de doc = ESTRATEGIA equivocada
    (ALL_404_OPENAPI)."""
    stale = sum(1 for f in dropped if f.failure is C.FailureClass.NOT_FOUND)
    nver = len(verified)
    if nver and stale == 0:
        return Outcome.YIELDED, None
    if nver and stale > 0:
        if stale / (stale + nver) >= _STALE_RATIO:
            return Outcome.PARTIAL, None        # doc STALE: forjá lo vivo, recuperá el resto abajo
        return Outcome.YIELDED, None            # doc mayormente bueno: dropeo los pocos 404 y gano en A
    if not verified and stale > 0 and stale == len(dropped):
        # TODO cayó 404. Con señal de doc al lado → "estrategia equivocada" (nivel externo §5).
        return Outcome.REJECTED, (C.FailureClass.ALL_404_OPENAPI if had_doc_signal else C.FailureClass.NOT_FOUND)
    if dropped:
        return Outcome.REJECTED, None
    return Outcome.EMPTY, None


# ══════════════════════════════════════════════════════════════════════════════
# A · AUTODESCRIPTIVO
# ══════════════════════════════════════════════════════════════════════════════
class RungA(Strategy):
    rung = Rung.A_SELF_DESCRIBING

    def __init__(self, *, inject_stale_paths: tuple[str, ...] = (), max_doc_candidates: int = 0):
        # inyección de paths bogus AL DOC parseado (demo del done-bar STALE): el doc
        # los "lista" pero el software vivo los 404ea → fuerza el patrón stale honesto.
        self._stale = inject_stale_paths
        # cap de candidatas del doc: 0 = todas. >0 modela un doc INCOMPLETO (stale por
        # omisión: endpoints reales que el doc todavía no lista) → D los recupera.
        self._cap = max_doc_candidates

    def propose(self, ctx: StrategyContext) -> StrategyResult:
        signals, cands, meta = _openapi.discover(ctx)
        cands = list(cands)
        if self._cap > 0:
            cands = cands[:self._cap]
        for path in self._stale:
            cands.append(_bogus_candidate(path))
        had_doc = any(s.kind in ("openapi", "swagger", "spec") and s.status == 200 for s in signals)
        if not cands:
            return StrategyResult(
                rung=self.rung,
                outcome=(Outcome.SWITCH if signals else Outcome.EMPTY),
                signals=tuple(signals), budget=ctx.ledger.snapshot(),
                notes=("señal de doc pero 0 candidatas GET forjables (¿GraphQL?)" if signals
                       else "sin auto-descripción (ningún /openapi.json·/swagger·/graphql)"))
        validation = ctx.validator.validate(ctx.session, cands)
        outcome, aggregate = _classify_batch(validation.verified, validation.failed, had_doc_signal=had_doc)
        return StrategyResult(
            rung=self.rung, outcome=outcome,
            candidates=tuple(cands), verified=validation.verified, dropped=validation.failed,
            signals=tuple(signals), aggregate_failure=aggregate,
            budget=ctx.ledger.snapshot(),
            notes=f"{meta.get('title','')} · {meta.get('version','')} · {len(cands)} GET candidatas")


def _bogus_candidate(path: str) -> C.CandidateTool:
    slug = "".join(ch if ch.isalnum() else "_" for ch in path).strip("_") or "x"
    return C.CandidateTool(
        name=("get_" + slug)[:60], kind=C.ToolKind.READ, endpoint=path, method="GET",
        input_schema={"type": "object", "properties": {},
                      "x-sample-call": {"path_params": {}, "query": {}}},
        description="(stale-doc demo) endpoint listado por el doc pero ausente del software vivo",
        derived_from=("openapi:stale-injected",))


# ══════════════════════════════════════════════════════════════════════════════
# B · HUELLA (familia conocida → RESOLVER)
# ══════════════════════════════════════════════════════════════════════════════
class RungB(Strategy):
    rung = Rung.B_FINGERPRINT

    def __init__(self, *, live_equip: bool = True):
        # live_equip: si la familia resuelve a un MCP HOSTED y hay credencial, intenta
        # validarlo vivo (el "candado" de B). stdio (npx/docker) NO se arranca en el
        # torneo (caro) → queda como handoff al resolver, que ya tiene su GREEN propio.
        self._live_equip = live_equip

    def propose(self, ctx: StrategyContext) -> StrategyResult:
        from inspection import mcp_resolver  # import perezoso (toca red al registro)
        service = _service_from_host(ctx.base_url)
        try:
            resolution = mcp_resolver.resolve_service(service, timeout=10.0)
        except mcp_resolver.NotFound as e:
            return StrategyResult(rung=self.rung, outcome=Outcome.EMPTY,
                                  budget=ctx.ledger.snapshot(),
                                  notes=f"sin familia confiable para '{service}': {e}")
        except Exception as e:  # noqa: BLE001 — registro caído / sin red
            return StrategyResult(rung=self.rung, outcome=Outcome.SKIPPED,
                                  budget=ctx.ledger.snapshot(),
                                  notes=f"resolver no disponible ('{service}'): {e}")
        if not resolution.get("found"):
            return StrategyResult(rung=self.rung, outcome=Outcome.EMPTY,
                                  budget=ctx.ledger.snapshot(), notes="resolver: no encontrado")

        server_name = resolution.get("server_name")
        sig = DiscoverySignal(kind="fingerprint", url=ctx.base_url, status=200,
                              detail=f"familia conocida: {server_name} ({resolution.get('source')})")
        spec = resolution.get("spec") or {}
        validated = False
        note = f"familia {server_name} resuelta (handoff al resolver para equipar)"
        if self._live_equip and spec.get("transport") == "http" and ctx.api_key:
            try:
                mcp_resolver.validate_live(spec, ctx.api_key, label=server_name)
                validated = True
                note = f"familia {server_name} resuelta Y validada viva (candado del resolver)"
            except Exception as e:  # noqa: BLE001
                note = f"familia {server_name} resuelta; validación viva falló: {e}"
        return StrategyResult(
            rung=self.rung,
            outcome=(Outcome.YIELDED if validated else Outcome.EMPTY),
            family=resolution, signals=(sig,), budget=ctx.ledger.snapshot(), notes=note)


def _service_from_host(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    parts = [p for p in host.split(".") if p]
    # tirá subdominios de API y el TLD: api.themoviedb.org → themoviedb ; www.alphavantage.co → alphavantage
    while parts and parts[0] in ("api", "www", "app", "rest", "data", "cloud", "v1", "v2", "v3"):
        parts = parts[1:]
    if len(parts) >= 2:
        return parts[-2]            # SLD
    return parts[0] if parts else host


# ══════════════════════════════════════════════════════════════════════════════
# C · CONVENCIÓN (/api/v1 + raíz + validate_path) — observación pasiva barata
# ══════════════════════════════════════════════════════════════════════════════
# rutas de convención genéricas: índice de la API, versionados, salud/estado. No es
# adivinar el dominio — es probar las CONVENCIONES REST que casi todas las APIs comparten.
_CONVENTION_PATHS = ("", "/", "/api", "/api/v1", "/v1", "/v2", "/status", "/health",
                     "/version", "/info")


class RungC(Strategy):
    rung = Rung.C_CONVENTION

    def propose(self, ctx: StrategyContext) -> StrategyResult:
        paths: list[str] = []
        seen = set()
        for p in (ctx.validate_path,) + tuple(ctx.passive_probes) + _CONVENTION_PATHS:
            if p is None:
                continue
            if p not in seen:
                seen.add(p)
                paths.append(p)
        cands = [C.CandidateTool(
            name=_conv_name(p), kind=C.ToolKind.READ, endpoint=(p or "/"), method="GET",
            input_schema={"type": "object", "properties": {},
                          "x-sample-call": {"path_params": {},
                                            "query": dict(ctx.validate_query or {}) if p == ctx.validate_path else {}}},
            description=f"(convención) lectura de {p or '/'}",
            derived_from=("convention",)) for p in paths]
        validation = ctx.validator.validate(ctx.session, cands)
        outcome, aggregate = _classify_batch(validation.verified, validation.failed, had_doc_signal=False)
        return StrategyResult(
            rung=self.rung, outcome=outcome,
            candidates=tuple(cands), verified=validation.verified, dropped=validation.failed,
            aggregate_failure=aggregate, budget=ctx.ledger.snapshot(),
            notes=f"{len(cands)} rutas de convención probadas")


def _conv_name(path: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in (path or "root")).strip("_") or "root"
    return ("get_" + slug)[:60]


# ══════════════════════════════════════════════════════════════════════════════
# D · ACTIVO (loop interno §3 — cerebro + minería de frontera)
# ══════════════════════════════════════════════════════════════════════════════
class RungD(Strategy):
    rung = Rung.D_ACTIVE

    def propose(self, ctx: StrategyContext) -> StrategyResult:
        cap = ctx.ledger.exhausted()
        if cap:
            return StrategyResult(rung=self.rung, outcome=Outcome.SKIPPED,
                                  budget=ctx.ledger.snapshot(), notes=f"budget agotado antes de D: {cap}")
        remaining = _remaining_budget(ctx)
        res = run_internal_loop(
            ctx.base_url, ctx.api_key, ctx.principal, slug=ctx.slug,
            budget=remaining, master_secret=ctx.master_secret, cred_root=ctx.cred_root,
            auth_param=ctx.auth_param, validate_path=ctx.validate_path, validate_query=ctx.validate_query,
            passive_probes=ctx.passive_probes or None, api_shape_hint=ctx.api_shape_hint,
            soft_error_keys=ctx.soft_error_keys, soft_notice_keys=ctx.soft_notice_keys,
            dispatch_param=ctx.dispatch_param, min_interval=ctx.min_interval,
            on_event=ctx.on_event, forge=False, synth_alias=ctx.synth_alias)
        # plegá lo que D gastó al ledger compartido (cap §6 único de la cascada)
        ctx.ledger.add_calls(int(res.budget.get("live_calls", 0)))
        ctx.ledger.add_tokens(int(res.budget.get("synth_tokens", 0)))
        if res.error:
            return StrategyResult(rung=self.rung, outcome=Outcome.SKIPPED, used_brain=True,
                                  budget=res.budget, notes=f"loop interno cortó: {res.error}")
        outcome = Outcome.YIELDED if res.verified else (Outcome.REJECTED if res.dropped else Outcome.EMPTY)
        return StrategyResult(
            rung=self.rung, outcome=outcome,
            verified=res.verified, dropped=res.dropped, used_brain=True, budget=res.budget,
            notes=f"convergencia={res.convergence} · degraded={res.degraded}")


def _remaining_budget(ctx: StrategyContext) -> Budget:
    """El budget que le queda a la cascada al llegar a D — UN solo techo §6, no N."""
    b, l = ctx.budget, ctx.ledger
    return Budget(
        max_rounds=b.max_rounds,
        max_live_calls=max(1, b.max_live_calls - l.live_calls),
        max_synth_tokens=max(1, b.max_synth_tokens - l.synth_tokens),
        max_seconds=max(5.0, b.max_seconds - l.elapsed()),
        dr_window=b.dr_window, dr_min_new=b.dr_min_new)


__all__ = ["RungA", "RungB", "RungC", "RungD"]
