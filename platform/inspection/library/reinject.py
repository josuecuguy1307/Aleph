"""
library/reinject.py — el WRAPPER caller-side (FASE 3b captura + 3c reinyección).
CERO ediciones fuera de library/: importa la cascada §4 y los componentes del loop
(read-only); no edita ni reconstruye nada.

`inspect_target(...)` es el riel del moat §8:

  1. ANTES de la cascada genérica, consultá el almacén por HUELLA:
       a. host-key (GRATIS, sin red) — pega para reinyección sobre el mismo host.
       b. si falla, 1 sniff barato del doc → doc-key (familias self-hosted cross-host).
  2. HIT → reinyectá: reconstruí los priors como CandidateTool y pasalos por el
     MISMO candado §3 (verify-before-trust) en UN batch → forjá. SIN A/B/C, SIN D,
     SIN cerebro, SIN tanteo de descubrimiento. Si los priors NO sobreviven (la
     instancia divergió) → fall-through a la cascada (auto-sana).
  3. MISS → run_cascade genérico; si gana → CAPTURÁ la ganadora indexada por huella.

El candado de la reinyección se arma con los MISMOS componentes que build_context
(provider→sesión validada+cifrada, LiveValidator, MCPEmitter) — el árbitro no se
relaja. La única diferencia: el guard es INYECTABLE (para fixtures controlados); por
defecto es PublicHTTPGuard (fail-closed), idéntico a la cascada.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C                       # noqa: E402
from inspection.loop.budget import Budget, Ledger           # noqa: E402
from inspection.loop.emit import MCPEmitter                 # noqa: E402
from inspection.loop.guard import PublicHTTPGuard           # noqa: E402
from inspection.loop.live_http import LiveHTTP              # noqa: E402
from inspection.loop.session import TMDBTokenSession        # noqa: E402
from inspection.loop.synth import tool_signature            # noqa: E402
from inspection.loop.validator import LiveValidator         # noqa: E402
from inspection.strategy import openapi as _openapi         # noqa: E402
from inspection.strategy.cascade import run_cascade         # noqa: E402
from inspection.strategy.types import CascadeResult         # noqa: E402
from inspection.library import fingerprint as fp            # noqa: E402
from inspection.library import store                        # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# LibraryResult — el veredicto del wrapper (envuelve, no reemplaza, CascadeResult)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class LibraryResult:
    ok: bool
    base_url: str
    source: str                                   # reinjected | cascade | reinject-fallback
    family_id: str = ""
    forged: Optional[C.ForgedMCP] = None
    verified: tuple[C.VerifiedTool, ...] = ()
    budget: dict = field(default_factory=dict)
    reinjected: bool = False
    captured: bool = False
    used_brain: bool = False
    convergence: str = ""
    cascade: Optional[CascadeResult] = None        # presente en el camino cascada/fallback
    error: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# sniff barato del doc (para la doc-key) — guard SSRF ANTES de cada fetch
# ══════════════════════════════════════════════════════════════════════════════
def _looks_openapi(doc: Any) -> bool:
    return isinstance(doc, dict) and ("openapi" in doc or "swagger" in doc) and bool(doc.get("paths") or doc.get("info"))


def _sniff_doc(base_url: str, guard: C.SSRFGuard, ledger: Ledger, *, timeout: float = 8.0) -> tuple[str, str]:
    """Devuelve (title, version) del primer doc auto-descriptivo alcanzable, o
    ('',''). Keyless (los docs son públicos). Cuenta las calls en `ledger`."""
    http = LiveHTTP(secret="", ledger=ledger, timeout=timeout)
    for url in _openapi._candidate_doc_urls(base_url):
        if not ledger.can_make_call():
            break
        if not guard.check(url):                  # fail-closed
            continue
        try:
            res = http.get(url)
        except Exception:                          # noqa: BLE001
            continue
        if res.ok and _looks_openapi(res.json):
            info = res.json.get("info") or {}
            version = res.json.get("openapi") or (
                ("swagger-" + str(res.json.get("swagger"))) if res.json.get("swagger") else "")
            return info.get("title", ""), str(version)
    return "", ""


# ══════════════════════════════════════════════════════════════════════════════
# el candado de la reinyección (mismos componentes que build_context, guard inyectable)
# ══════════════════════════════════════════════════════════════════════════════
def _acquire_lock(base_url, api_key, principal, *, slug, guard, ledger, knobs):
    provider = TMDBTokenSession(
        base_url, api_key, principal, slug,
        auth_param=knobs.get("auth_param", "api_key"),
        validate_path=knobs.get("validate_path", "/configuration"),
        validate_query=knobs.get("validate_query"),
        soft_error_keys=tuple(knobs.get("soft_error_keys", ())),
        soft_notice_keys=tuple(knobs.get("soft_notice_keys", ())),
        min_interval=knobs.get("min_interval", 0.0),
        guard=guard, master_secret=knobs.get("master_secret"),
        cred_root=knobs.get("cred_root", C.SYNTH_BELTS_DIR))
    session = provider.acquire()                   # guard + valida key viva + cifra cred (Capa 1)
    ledger.add_calls(1)
    keyed_http = LiveHTTP(secret=provider.secret, auth_param=knobs.get("auth_param", "api_key"),
                          ledger=ledger, min_interval=knobs.get("min_interval", 0.0))
    validator = LiveValidator(keyed_http, soft_error_keys=tuple(knobs.get("soft_error_keys", ())),
                              soft_notice_keys=tuple(knobs.get("soft_notice_keys", ())), ledger=ledger)
    return provider, session, validator


def _reinject(cs, base_url, api_key, principal, *, slug, guard, budget, knobs, root, emit) -> Optional[LibraryResult]:
    """Re-valida los priors capturados contra ESTA instancia, en 1 batch. Devuelve
    None si nada sobrevive (la instancia divergió → el caller hace fall-through)."""
    ledger = Ledger(budget or Budget())
    eps = cs.priors.get("endpoints", []) or []
    cands = [store.candidate_from_dict(e) for e in eps]
    if not cands:
        return None
    # los priors saben sus propias perillas (auth_param/validate_path) — ganan a los knobs
    merged = dict(knobs)
    for k in ("auth_param", "validate_path"):
        if cs.priors.get(k):
            merged[k] = cs.priors[k]
    if cs.priors.get("validate_query") is not None:
        merged["validate_query"] = cs.priors["validate_query"]

    try:
        _provider, session, validator = _acquire_lock(
            base_url, api_key, principal, slug=slug, guard=guard, ledger=ledger, knobs=merged)
    except C.SessionError as e:
        emit({"type": "reinject.session_error", "detail": str(e)})
        return None

    emit({"type": "reinject.validate", "family_id": cs.family_id, "priors": len(cands)})
    validation = validator.validate(session, cands)
    if not validation.verified:
        return None                                # divergió → fall-through

    dispatch = merged.get("dispatch_param") or ""
    union: dict[str, C.VerifiedTool] = {}
    for vt in validation.verified:
        union.setdefault(tool_signature(vt.candidate, dispatch), vt)

    emitter = MCPEmitter(principal, slug, base_url, auth_param=merged.get("auth_param", "api_key"),
                         cred_root=merged.get("cred_root", C.SYNTH_BELTS_DIR),
                         min_interval=merged.get("min_interval", 0.0))
    forged = emitter.emit(tuple(union.values()))
    store.record_hit(cs, root=root)
    snap = ledger.snapshot()
    emit({"type": "reinject.forged", "server_name": forged.server_name,
          "tools": len(forged.tools), "live_calls": snap.get("live_calls"), "used_brain": False})
    return LibraryResult(
        ok=True, base_url=base_url, source="reinjected", family_id=cs.family_id,
        forged=forged, verified=tuple(union.values()), budget=snap, reinjected=True,
        used_brain=False,
        convergence=(f"reinyectado de {cs.family_id}: {len(union)}/{len(cands)} priors "
                     f"revalidados vivos en 1 batch · 0 cerebro · 0 vueltas de descubrimiento"))


# ══════════════════════════════════════════════════════════════════════════════
# inspect_target — el riel del moat
# ══════════════════════════════════════════════════════════════════════════════
def inspect_target(
    base_url: str, api_key: str, principal: C.Principal, *,
    slug: str = "library-live", budget: Optional[Budget] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    reinject: bool = True, capture_on_win: bool = True,
    guard: Optional[C.SSRFGuard] = None, root: Path = store.CAPTURE_DIR,
    **knobs,
) -> LibraryResult:
    def emit(ev: dict) -> None:
        if on_event:
            on_event(ev)

    g = guard or PublicHTTPGuard()
    doc_title = doc_version = ""

    # ── 1 · LOOKUP por huella (ANTES de la cascada) ──────────────────────────────
    if reinject:
        cs = store.lookup(fp.lookup_keys(base_url), root=root)   # host-key: GRATIS
        if cs is None:
            sniff_led = Ledger(Budget())
            doc_title, doc_version = _sniff_doc(base_url, g, sniff_led)
            if doc_title:
                emit({"type": "reinject.sniff", "doc_title": doc_title, "calls": sniff_led.live_calls})
                cs = store.lookup(fp.lookup_keys(base_url, doc_title=doc_title, doc_version=doc_version), root=root)
        if cs is not None:
            emit({"type": "reinject.hit", "family_id": cs.family_id, "hits": cs.hits,
                  "ledger_class": cs.ledger_class})
            res = _reinject(cs, base_url, api_key, principal, slug=slug, guard=g,
                            budget=budget, knobs=knobs, root=root, emit=emit)
            if res is not None:
                return res
            emit({"type": "reinject.diverged", "family_id": cs.family_id,
                  "detail": "priors no sobrevivieron el candado → fall-through a la cascada"})

    # ── 2 · MISS / fallback · cascada genérica + CAPTURA al ganar ────────────────
    cr = run_cascade(base_url, api_key, principal, slug=slug, budget=budget,
                     on_event=on_event, **knobs)
    captured = None
    if capture_on_win and cr.ok:
        if not doc_title:                          # aún no snifeamos el doc → hacelo para la clave
            doc_title, doc_version = _sniff_doc(base_url, g, Ledger(Budget()))
        captured = store.capture(
            cr, base_url=base_url,
            auth_param=knobs.get("auth_param", "api_key"),
            validate_path=knobs.get("validate_path", "/configuration"),
            validate_query=knobs.get("validate_query"),
            doc_title=doc_title, doc_version=doc_version, root=root)
        if captured:
            emit({"type": "capture", "family_id": captured.family_id,
                  "ledger_class": captured.ledger_class, "winner": captured.winner_rung,
                  "tools": len(captured.priors.get("endpoints", []))})

    return LibraryResult(
        ok=cr.ok, base_url=base_url, source=("reinject-fallback" if reinject else "cascade"),
        family_id=(captured.family_id if captured else ""),
        forged=cr.forged, verified=cr.verified, budget=cr.budget,
        captured=bool(captured), used_brain=cr.used_brain,
        cascade=cr, convergence=cr.convergence, error=cr.error)


__all__ = ["LibraryResult", "inspect_target"]
