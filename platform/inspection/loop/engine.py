"""
loop/engine.py — §3+§6 · el LOOP INTERNO orquestado (Observador→Sintetizador→Validador).

Cablea las 5 capas contra software vivo y las hace girar hasta converger, con el
budget como cap duro. En CADA vuelta loguea el WORKING SET (qué entró a VERIFIED,
qué a FAILED y por qué, qué frontera se abrió) — el §3 hecho auditable.

Convergencia (§6), en orden de chequeo:
  • el cerebro cae (degraded) ⇒ corte honesto (sin fingir candidatas);
  • el sintetizador no propone nada nuevo ⇒ no hay más que explorar;
  • frontera vacía Y cero tools nuevas esta vuelta ⇒ se secó la veta;
  • rendimientos decrecientes (<k tools nuevas en N vueltas) ⇒ convergió;
  • budget agotado (rounds / calls / tokens / tiempo) ⇒ cap duro.

Al cerrar, la Capa 5 forja el MCP desde las VERIFIED — desde cero, no de un config.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.budget import Budget, Ledger  # noqa: E402
from inspection.loop.emit import AgentEmitter, MCPEmitter  # noqa: E402
from inspection.loop.live_http import LiveHTTP  # noqa: E402
from inspection.loop.observer import LiveObserver  # noqa: E402
from inspection.loop.session import TMDBTokenSession  # noqa: E402
from inspection.loop.synth import BrainSynthesizer, tool_signature  # noqa: E402
from inspection.loop.validator import LiveValidator  # noqa: E402

TMDB_BASE = "https://api.themoviedb.org/3"
ALPHAVANTAGE_BASE = "https://www.alphavantage.co"


@dataclass
class LoopResult:
    """El veredicto del loop + todo lo auditable para el gate."""
    ok: bool
    base_url: str
    verified: tuple[C.VerifiedTool, ...] = ()
    dropped: tuple[C.FailedTool, ...] = ()
    forged: Optional[C.ForgedMCP] = None
    forged_agents: tuple[C.ForgedAgent, ...] = ()   # camino agente (paralelo, aditivo)
    rounds_log: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    convergence: str = ""
    degraded: bool = False
    budget: dict = field(default_factory=dict)
    session_meta: dict = field(default_factory=dict)
    error: str = ""

    # ── lecturas convenientes para el gate ────────────────────────────────────
    @property
    def verified_names(self) -> list[str]:
        return [v.candidate.name for v in self.verified]

    @property
    def dropped_by_failure_table(self) -> list[dict]:
        return [{"name": f.candidate.name, "endpoint": f.candidate.endpoint,
                 "class": f.failure.name, "symptom": f.failure.symptom,
                 "level": f.failure.level.value, "move": f.failure.move,
                 "detail": f.detail} for f in self.dropped]


def run_internal_loop(
    base_url: str,
    api_key: str,
    principal: C.Principal,
    *,
    slug: str = "tmdb-live",
    budget: Optional[Budget] = None,
    master_secret: Optional[str] = None,
    cred_root: Path = C.SYNTH_BELTS_DIR,
    auth_param: str = "api_key",
    validate_path: str = "/configuration",
    validate_query: Optional[dict] = None,
    passive_probes: Optional[Sequence[str]] = None,
    api_shape_hint: str = "",
    soft_error_keys: Sequence[str] = (),
    soft_notice_keys: Sequence[str] = (),
    dispatch_param: Optional[str] = None,
    min_interval: float = 0.0,
    on_event: Optional[Callable[[dict], None]] = None,
    provider: Optional[C.SessionProvider] = None,
    guard: Optional[C.SSRFGuard] = None,   # [ssrf-consent] guard del default token-query; None = estricto
    forge: bool = True,
    synth_alias: str = "brain",
    seed_candidates: Sequence[C.CandidateTool] = (),
    equip_agents: Sequence[C.VerifiedAgent] = (),
    moat: bool = True,   # TICKET 30 · biblioteca de captura: reinyecta la familia capturada + captura al ganar
) -> LoopResult:
    budget = budget or Budget()
    ledger = Ledger(budget)
    events: list[dict] = []
    rounds_log: list[dict] = []

    def emit(ev: dict) -> None:
        events.append(ev)
        if on_event:
            on_event(ev)

    # ── Capa 1 (con Capa 0 adentro): la puerta ────────────────────────────────
    # El provider es INYECTABLE (§2): sin uno, el default es Forma 1 (token en query) —
    # comportamiento idéntico al de siempre. Cualquier SessionProvider (Forma 2 login-API,
    # Forma 3 humano+sesión) entra por acá sin que el loop sepa de qué forma vino: lo
    # único que el loop consume es la `Session` uniforme.
    if provider is None:
        provider = TMDBTokenSession(
            base_url, api_key, principal, slug,
            auth_param=auth_param, validate_path=validate_path, validate_query=validate_query,
            soft_error_keys=tuple(soft_error_keys), soft_notice_keys=tuple(soft_notice_keys),
            min_interval=min_interval, guard=guard,   # [ssrf-consent] None → Session usa PublicHTTPGuard (estricto)
            master_secret=master_secret, cred_root=cred_root,
        )
    try:
        session = provider.acquire()
    except C.SessionError as e:
        emit({"type": "session.error", "detail": str(e)})
        return LoopResult(ok=False, base_url=base_url, error=str(e), events=events)
    emit({"type": "session.acquired", "form": session.form.value, "meta": dict(session.meta)})

    # TICKET 30 · MOAT §8 · REINYECCIÓN: si no vino seed y HAY una familia capturada para esta huella
    # (la 1ra forja de esta familia la guardó), sembramos el loop con sus endpoints → la 2da NO
    # re-descubre = converge barato (la palanca del diferenciador). host-key = GRATIS (sin red).
    # Fail-safe TOTAL: cualquier fallo de la biblioteca → no-op → forja normal (jamás la rompe).
    if moat and forge and not seed_candidates:
        try:
            from inspection.library import store as _lib_store, fingerprint as _lib_fp
            _cs = _lib_store.lookup(_lib_fp.lookup_keys(base_url))
            if _cs is not None:
                _eps = (_cs.priors or {}).get("endpoints") or []
                if _eps:
                    seed_candidates = tuple(_lib_store.candidate_from_dict(e) for e in _eps)
                    _lib_store.record_hit(_cs)
                    emit({"type": "library.reinject", "family_id": _cs.family_id,
                          "hits": _cs.hits + 1, "seeded": len(seed_candidates)})
        except Exception:
            pass

    # El http del loop lee la auth de la Session UNIFORME (headers/cookies de Forma 2/3) y
    # SÓLO cuando la sesión no lleva auth en línea (Forma 1 / inject=query) inyecta el
    # secreto en query (carril histórico, byte-equivalente). Así el observador/validador
    # llaman igual y la auth viaja sola, sin que sepan de qué forma vino.
    inline_auth = bool(session.headers) or bool(session.cookies)
    query_secret = "" if inline_auth else getattr(provider, "secret", "")
    http = LiveHTTP(secret=query_secret, auth_param=auth_param,
                    headers=session.headers, cookies=session.cookies,
                    ledger=ledger, min_interval=min_interval)
    observer = (LiveObserver(http, passive_probes=tuple(passive_probes))
                if passive_probes else LiveObserver(http))
    synth = BrainSynthesizer(_host_of(base_url), ledger=ledger, alias=synth_alias,
                             shape_hint=api_shape_hint)
    synth.set_dispatch_param(dispatch_param or "")
    validator = LiveValidator(http, soft_error_keys=tuple(soft_error_keys),
                              soft_notice_keys=tuple(soft_notice_keys), ledger=ledger,
                              # H-P2-01 · el MISMO guard con consent [ssrf-consent] que usa la
                              # Session: sin esto la verificación de writes (OPTIONS/dry-run)
                              # caía al PublicHTTPGuard estricto (https-only) y TODO write
                              # contra un self-hosted http://localhost moría FORBIDDEN aunque
                              # el usuario ya había opt-ineado ese host. None → estricto igual.
                              guard=guard)

    def _sig(cand: C.CandidateTool) -> str:
        return tool_signature(cand, dispatch_param or "")

    confirmed: dict[str, C.Capability] = {}      # endpoint → Capability (dedup)
    verified: list[C.VerifiedTool] = []
    verified_eps: set[str] = set()
    failed: list[C.FailedTool] = []
    failed_eps: set[str] = set()
    frontier: list[C.FrontierLead] = []
    explored: set[str] = set()
    convergence = ""
    degraded = False

    while True:
        cap = ledger.exhausted()
        if cap:
            convergence = f"budget: {cap}"
            break
        ledger.tick_round()
        rnum = ledger.rounds

        # ── Capa 2 · observar (pasiva 1ra vuelta, activa luego) ────────────────
        unexplored = [f for f in frontier if f.hint not in explored]
        observation = observer.observe(session, unexplored)
        probed = observation.capability_map.get("probed")
        if probed:
            explored.add(probed)
        for c in observation.confirmed:
            confirmed.setdefault(c.endpoint, c)   # obs caps no tienen despacho → endpoint
        emit({"type": "observe", "round": rnum, "passive": observation.passive,
              "mode": observation.capability_map.get("mode"),
              "probed": probed, "new_confirmed": [c.endpoint for c in observation.confirmed]})

        # ── Capa 3 · sintetizar (Opus real) ────────────────────────────────────
        # la llamada al cerebro puede tardar ~90s; sin este emit el stream queda mudo
        emit({"type": "synth.start", "round": rnum, "alias": synth_alias})
        candidates = synth.synthesize(tuple(confirmed.values()), observation, tuple(failed))
        if synth.last.degraded:
            degraded = True
            emit({"type": "synth", "round": rnum, "degraded": True,
                  "reason": synth.last.reason, "model": synth.last.model})
            convergence = "degraded: el cerebro (shim) no respondió"
            break
        # [ola0-costura] EDGE PROBES sembradas por el caller: el §3 pide "sondear el borde";
        # sembrarlas lo hace determinístico. Pasan por el MISMO candado (Capa 4) contra el
        # target vivo — NO es atajo: si existen, verifican; si 404ean, son drops REALES. Solo
        # 1ra vuelta; sin semillas el bloque es no-op (callers existentes byte-idénticos).
        if seed_candidates and rnum == 1:
            candidates = tuple(seed_candidates) + tuple(candidates)
        # no repetir tools ya verificadas/falladas (firma: endpoint, o endpoint#dispatch)
        fresh = tuple(c for c in candidates
                      if _sig(c) not in verified_eps and _sig(c) not in failed_eps)
        emit({"type": "synth", "round": rnum, "degraded": False, "model": synth.last.model,
              "proposed": [_sig(c) for c in candidates],
              "fresh": [_sig(c) for c in fresh],
              # [ola0-costura] evidencia cruda de las candidatas FRESCAS (las que van al
              # candado) — aditivo: deja que un consumidor SSE emita tool.propuesta{params}
              # sin tocar el control flow. params == input_schema real que propuso el cerebro.
              "fresh_detail": [_cand_detail(c, _sig(c)) for c in fresh],
              "tokens": synth.last.prompt_tokens + synth.last.completion_tokens})
        if not fresh:
            convergence = "sin candidatas nuevas (el sintetizador no propuso nada explorable)"
            _log_round(rounds_log, rnum, observation, (), C.Validation(), confirmed, frontier, ledger)
            break

        # ── Capa 4 · EL CANDADO ────────────────────────────────────────────────
        validation = validator.validate(session, fresh)
        new_verified = [v for v in validation.verified if _sig(v.candidate) not in verified_eps]
        for v in new_verified:
            verified.append(v)
            verified_eps.add(_sig(v.candidate))
            # el read verificado se vuelve CONFIRMED con su respuesta real como evidencia →
            # el sintetizador ve datos reales la próxima vuelta. Keyed por firma (no
            # endpoint) para que en despacho-por-query no se pisen entre funciones.
            confirmed[_sig(v.candidate)] = C.Capability(
                endpoint=v.candidate.endpoint, method=v.candidate.method,
                evidence=f"VERIFIED · {v.verified_by} · {(v.sample_response or '')[:240]}",
                fields=tuple((v.candidate.input_schema.get("properties") or {}).keys()),
            )
        for f in validation.failed:
            failed.append(f)
            failed_eps.add(_sig(f.candidate))
        for ld in validation.frontier:
            if ld.hint not in explored and ld.hint not in {x.hint for x in frontier}:
                frontier.append(ld)

        emit({"type": "validate", "round": rnum,
              "verified": [v.candidate.name for v in new_verified],
              # [ola0-costura] evidencia cruda del candado (aditivo): status+payload REALES
              # de cada VERIFIED y el detalle REAL (HTTP status / sobre en-banda / url
              # redactada) de cada FAILED → habilita tool.validada/tool.descartada con
              # payload de evidencia, sin re-llamar al target ni cambiar el veredicto.
              "verified_detail": [_verified_detail(v) for v in new_verified],
              "failed": [{"name": f.candidate.name, "class": f.failure.name,
                          "symptom": f.failure.symptom, "move": f.failure.move,
                          "endpoint": f.candidate.endpoint, "method": f.candidate.method,
                          "params": dict(f.candidate.input_schema or {}),
                          "detail": f.detail}
                         for f in validation.failed],
              "frontier_opened": [ld.hint for ld in validation.frontier]})

        _log_round(rounds_log, rnum, observation, tuple(new_verified), validation,
                   confirmed, frontier, ledger)
        ledger.record_new_verified(len(new_verified))

        # ── §6 · convergencia ──────────────────────────────────────────────────
        remaining = [f for f in frontier if f.hint not in explored]
        if not remaining and not new_verified:
            convergence = "frontera vacía + sin tools nuevas (veta agotada)"
            break
        if ledger.diminishing_returns():
            convergence = (f"rendimientos decrecientes "
                           f"(<{budget.dr_min_new} tools nuevas en {budget.dr_window} vueltas)")
            break

    # ── Capa 5 · forjar el MCP desde las VERIFIED (desde cero) ─────────────────
    forged: Optional[C.ForgedMCP] = None
    if forge and verified:
        # el MCP forjado se autentica como la SESIÓN: Forma 1 → token en query;
        # Forma 2/3 → header (Bearer) o cookie. El cred_name sale del cred_ref de la
        # sesión (#API_KEY / #SESSION_TOKEN) → el server forjado resuelve la credencial
        # correcta del vault. Sin esto, una API header-auth se forjaría como query (teatro).
        # [T-4] si el validador conmutó a header (re-observe de un query-401), el forge spec
        # debe declarar HEADER — si no, el MCP forjado se autenticaría por query y las tools
        # verificadas-por-header fallarían en RUN (false-success).
        auth_spec = _forge_auth_spec(session, provider, auth_param,
                                     override_headers=validator.switched_headers())
        emitter = MCPEmitter(principal, slug, base_url, auth_param=auth_param,
                             cred_name=auth_spec["cred_name"], auth_spec=auth_spec,
                             cred_root=cred_root, min_interval=min_interval)
        forged = emitter.emit(tuple(verified))

    # ── Capa 5 (camino AGENTE) · equipar sub-agentes, EN PARALELO al de tools ───
    # [forja-agentes] Si el caller pasó `equip_agents` (recetas hijas ya verificadas),
    # se forjan como agent_refs[] (NUNCA belt_refs[]). Es una vía aparte: el loop NO
    # descubre agentes (eso es discovery, sistema aparte) — los recibe ya verificados.
    forged_agents: tuple[C.ForgedAgent, ...] = ()
    if forge and equip_agents:
        agent_emitter = AgentEmitter(principal, slug, cred_root=cred_root)
        forged_agents = agent_emitter.emit_agent(tuple(equip_agents))

    # DUAL-MODE: el evento 'forged' lleva tools:[] Y agents:[] a la vez. Un lector viejo
    # que sólo mira `tools` sigue funcionando (agents es aditivo). Se emite si se forjó
    # CUALQUIERA de los dos. Tool-only (equip_agents=()): byte-equivalente a hoy + agents:[].
    if forge and (forged or forged_agents):
        emit(_build_forged_event(forged, forged_agents))

    emit({"type": "closed", "convergence": convergence,
          "verified": len(verified), "dropped": len(failed),
          "degraded": degraded, "budget": ledger.snapshot()})

    _result = LoopResult(
        ok=bool(verified) and not degraded,
        base_url=base_url,
        verified=tuple(verified),
        dropped=tuple(failed),
        forged=forged,
        forged_agents=forged_agents,
        rounds_log=rounds_log,
        events=events,
        convergence=convergence,
        degraded=degraded,
        budget=ledger.snapshot(),
        session_meta=dict(session.meta),
    )
    # TICKET 30 · MOAT §8 · CAPTURA: al ganar (verificadas), guardamos la estrategia indexada por
    # huella → la PRÓXIMA forja de la MISMA familia la reinyecta (arriba) y converge barato. store.capture
    # es idempotente (preserva hits). Fail-safe: un fallo de la biblioteca NUNCA rompe el forge.
    if moat and _result.ok and verified:
        try:
            from inspection.library import store as _lib_store
            _cap = _lib_store.capture(
                _result, base_url=base_url, auth_param=auth_param,
                validate_path=validate_path, validate_query=validate_query)
            if _cap is not None:
                emit({"type": "library.captured", "family_id": _cap.family_id,
                      "verified": len(verified)})
        except Exception:
            pass
    return _result


# [ola0-costura] proyecciones serializables de los objetos del working set, para que un
# consumidor del stream (la costura /v1/forge) emita los eventos del contrato con su
# evidencia cruda. Pura forma: leen lo que la capa YA computó, no recalculan ni mutan nada.
def _cand_detail(cand: C.CandidateTool, sig: str) -> dict:
    return {"name": cand.name, "endpoint": cand.endpoint, "method": cand.method,
            "kind": cand.kind.value, "params": dict(cand.input_schema or {}),
            "description": cand.description, "sig": sig}


# [forja-agentes] el evento 'forged' DUAL-MODE: `tools` del MCP forjado (intacto, byte-equiv
# al de siempre cuando no hay agentes) + `agents` de los sub-agentes equipados (aditivo). Un
# lector que sólo lee `tools` no se entera de `agents`. Extraído como helper para testearlo
# headless sin un target vivo.
def _forged_agent_payload(fa: C.ForgedAgent) -> dict:
    return {"agent_name": fa.agent_name, "recipe_ref": fa.recipe_ref,
            "agent_ref": fa.agent_ref, "manifest_ref": fa.manifest_ref}


def _build_forged_event(forged: Optional[C.ForgedMCP],
                        forged_agents: Sequence[C.ForgedAgent]) -> dict:
    return {
        "type": "forged",
        "server_name": forged.server_name if forged else None,
        "belt_ref": forged.belt_ref if forged else None,
        "tools": list(forged.tools) if forged else [],
        "agents": [_forged_agent_payload(fa) for fa in forged_agents],
    }


def _verified_detail(v: C.VerifiedTool) -> dict:
    return {"name": v.candidate.name, "endpoint": v.candidate.endpoint,
            "method": v.candidate.method, "kind": v.candidate.kind.value,
            "params": dict(v.candidate.input_schema or {}),
            "verified_by": v.verified_by, "sample_response": v.sample_response}


def _log_round(rounds_log, rnum, observation, new_verified, validation, confirmed,
               frontier, ledger: Ledger) -> None:
    """El WORKING SET de esta vuelta, auditable (§3)."""
    rounds_log.append({
        "round": rnum,
        "observe": {"passive": observation.passive,
                    "mode": observation.capability_map.get("mode"),
                    "probed": observation.capability_map.get("probed")},
        "CONFIRMED_total": len(confirmed),
        "VERIFIED_nuevas": [v.candidate.name + " ⇐ " + v.candidate.endpoint for v in new_verified],
        "FAILED_nuevas": [f"{f.candidate.endpoint} → {f.failure.name}({f.failure.symptom}) "
                          f"move={f.failure.move}" for f in validation.failed],
        "FRONTIER_size": len([f for f in frontier]),
        "budget": ledger.snapshot(),
    })


def _forge_auth_spec(session: C.Session, provider: Any, auth_param: str,
                     override_headers: Optional[dict] = None) -> dict:
    """Describe CÓMO se autentica el MCP forjado, leído de la Session UNIFORME (no de
    la forma concreta). El cred_name sale del `cred_ref` de la sesión (#API_KEY,
    #SESSION_TOKEN, …) → el server forjado resuelve la credencial correcta del vault.

      • Forma 1 / inject=query → token en query (`auth_param`).
      • Forma 2/3 header       → header con su template ("Bearer {token}"), reconstruido
                                 reemplazando el token concreto por el placeholder {token}.
      • Forma 2/3 cookie       → cookie con su nombre; el valor es el token tal cual.
    """
    cred_ref = (session.meta or {}).get("cred_ref", "")
    cred_name = cred_ref.rsplit("#", 1)[-1] if "#" in cred_ref else "API_KEY"
    headers = override_headers or session.headers
    if headers:
        name, value = next(iter(headers.items()))
        tok = getattr(provider, "secret", "") or ""
        template = value.replace(tok, "{token}") if tok and tok in value else "{token}"
        return {"in": "header", "name": name, "template": template, "cred_name": cred_name}
    if session.cookies:
        name = next(iter(session.cookies.keys()))
        return {"in": "cookie", "name": name, "cred_name": cred_name}
    return {"in": "query", "param": auth_param, "cred_name": cred_name}


def _host_of(url: str) -> str:
    from urllib.parse import urlparse
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}{u.path}".rstrip("/")
