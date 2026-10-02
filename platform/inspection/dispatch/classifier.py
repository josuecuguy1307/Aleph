"""
dispatch/classifier.py — PURO y read-only: `service` → (Verdict, Draft). NO toca el mundo
(ni red de probe, ni creds, ni disco) y NO dispara gate. Solo consulta el registro + el
matcher y DERIVA el veredicto de 3 valores.

POR QUÉ derivar (y no leer un verdict nativo): el resolver es BINARIO — resolve_service
devuelve found o tira NotFound, y en NotFound DESCARTA los candidatos ranked. El borrador
más valioso (un top-candidate below-threshold) NO sale por ahí. Por eso el classifier llama
mcp_registry.search + mcp_matcher.rank DIRECTO (read-only, permitido) y clasifica con las
señales crudas del matcher (verified_vendor, score, ranked) + el curado.

Mapa señales → verdict (reusa los umbrales del matcher, no inventa):
  • CONFIABLE = curado manual/pin (lock duro) · o best_match found con verified_vendor=True
                (namespace DNS/github_org verificado).
  • DUDOSO    = best_match found con verified_vendor=False (community sobre UNVERIFIED_MIN_SCORE)
                · o top-candidate below-threshold con score ≥ MIN_SCORE (borrador usable que
                el matcher rechazó por SEGURIDAD — pero probe_mcp será el árbitro, no el match).
  • NADA      = sin candidato · o el mejor score < MIN_SCORE (borrador demasiado débil).

El `spec` (run-spec) se deriva acá de remotes/packages del candidato — una porción chica de
lógica que el resolver tiene PRIVADA (_exec_spec) y que además no es alcanzable en el caso
below-threshold (resolve_service tira NotFound antes). Es derivación de forma, NO validación;
el candado sigue siendo probe_mcp (liveness.py).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_PLATFORM = Path(__file__).resolve().parents[2]   # dispatch → inspection → platform
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import mcp_matcher, mcp_registry   # noqa: E402  (read-only)
from inspection.dispatch.models import Draft, Verdict  # noqa: E402

# transportes hosted que el cliente Streamable-HTTP entiende (preferimos streamable-http)
_HTTP_TYPES = ("streamable-http", "http", "sse")
#: piso del borrador: un candidato con score < MIN_SCORE no es ni borrador (demasiado débil).
_DRAFT_FLOOR = mcp_matcher.MIN_SCORE


# ── derivación del run-spec (forma, NO validación; el candado es probe_mcp) ──────
def _remote_spec(remote: dict) -> dict:
    header_name, header_template, declared = "Authorization", "Bearer {key}", False
    for h in (remote.get("headers") or []):
        if h.get("isSecret") or h.get("isRequired") or "{" in (h.get("value") or ""):
            header_name = h.get("name") or header_name
            header_template = h.get("value") or header_template
            declared = True
            break
    return {"transport": "http", "url": remote.get("url"), "remote_type": remote.get("type"),
            "header_name": header_name, "header_template": header_template,
            "needs_credential": True, "credential_declared": declared}


def _package_spec(pkg: dict) -> dict:
    rtype = (pkg.get("registryType") or "").lower()
    ident = pkg.get("identifier") or ""
    version = pkg.get("version") or ""
    if rtype == "npm":
        command, args = "npx", ["-y", ident + (f"@{version}" if version else "")]
    elif rtype == "pypi":
        command, args = "uvx", [ident + (f"=={version}" if version else "")]
    elif rtype == "oci":
        command, args = "docker", ["run", "-i", "--rm", ident]
    else:
        command, args = ident, []
    env_var, declared = None, False
    for ev in (pkg.get("environmentVariables") or []):
        if ev.get("isSecret") or ev.get("isRequired"):
            env_var, declared = ev.get("name"), True
            break
    return {"transport": "stdio", "command": command, "args": args, "registry_type": rtype,
            "package_env_var": env_var, "needs_credential": bool(env_var),
            "credential_declared": declared}


def _spec_from_candidate(candidate: dict, curated: Optional[dict]) -> Optional[dict]:
    """run-spec del candidato (hosted preferido por simplicidad de probe). None si el server
    no declara ni remote ni package (no hay forma de correrlo → no es borrador forjable)."""
    preferred = None
    for t in _HTTP_TYPES:
        for r in (candidate.get("remotes") or []):
            if (r.get("type") or "").lower() == t and r.get("url"):
                preferred = r
                break
        if preferred:
            break
    if preferred:
        spec = _remote_spec(preferred)
    elif candidate.get("packages"):
        spec = _package_spec(candidate["packages"][0])
    else:
        return None
    spec["signature"] = [str(s).lower() for s in ((curated or {}).get("signature") or [])]
    return spec


def _manual_spec(manual: dict, curated: Optional[dict]) -> dict:
    """Spec desde un override curado 'manual' (gap del registro, ej. github)."""
    if (manual.get("transport") or "http") == "http":
        spec = {"transport": "http", "url": manual.get("url"), "remote_type": "streamable-http",
                "header_name": manual.get("header_name") or "Authorization",
                "header_template": manual.get("header_template") or "Bearer {key}",
                "needs_credential": True, "credential_declared": True}
    else:
        spec = {"transport": "stdio", "command": manual.get("command"),
                "args": list(manual.get("args") or []), "package_env_var": manual.get("env_var"),
                "needs_credential": bool(manual.get("env_var")),
                "credential_declared": bool(manual.get("env_var"))}
    spec["signature"] = [str(s).lower() for s in ((curated or {}).get("signature") or [])]
    return spec


def _draft(service: str, candidate: dict, spec: dict, *, source: str, score: float,
           verified: bool, reason: str, ranked: list[dict]) -> Draft:
    return Draft(
        service=service,
        server_name=candidate.get("name") or candidate.get("display_name") or f"curated:{service}",
        spec=spec, vendor_kind=candidate.get("vendor_kind", source),
        source=source, score=round(float(score), 4), verified_vendor=bool(verified),
        signature=tuple(spec.get("signature") or ()), reason=reason,
        ranked=tuple({"name": r.get("name"), "score": r.get("score"),
                      "verified": r.get("verified_vendor")} for r in ranked[:5]))


# ── classify — el único entry público ────────────────────────────────────────────
def classify(service: str, *, timeout: float = 12.0,
             candidates: Optional[list[dict]] = None) -> tuple[Verdict, Optional[Draft]]:
    """`service` → (Verdict, Draft|None). Read-only puro. `candidates` se puede inyectar
    (fixtures determinísticos) para no pegarle al registro vivo."""
    service = (service or "").strip()
    if not service:
        return Verdict.NADA, None
    curated = mcp_registry.curated_entry(service)

    # (a) curado manual = gap del registro (server oficial sin publicar). CONFIABLE duro.
    if curated and curated.get("manual"):
        spec = _manual_spec(curated["manual"], curated)
        cand = {"name": curated["manual"].get("display_name") or f"curated:{service}",
                "vendor_kind": "curated_manual"}
        return Verdict.CONFIABLE, _draft(service, cand, spec, source="curated_manual",
                                         score=1.0, verified=True,
                                         reason="override curado (gap del registro)", ranked=[])

    # (b) registro + matcher (search inyectable para fixtures)
    if candidates is None:
        try:
            candidates = mcp_registry.search(service, timeout=timeout)
        except mcp_registry.RegistryError:
            candidates = []
    if not candidates:
        return Verdict.NADA, None

    ranked = mcp_matcher.rank(service, candidates)
    decision = mcp_matcher.best_match(service, candidates)
    pin = (curated or {}).get("pin")

    # pin curado presente entre candidatos → lock duro CONFIABLE (anti-impostor)
    if pin:
        pinned = next((c for c in candidates if c.get("name") == pin), None)
        if pinned is not None:
            spec = _spec_from_candidate(pinned, curated)
            if spec is not None:
                return Verdict.CONFIABLE, _draft(
                    service, pinned, spec, source="curated_pin",
                    score=next((r["score"] for r in ranked if r["name"] == pin), 1.0),
                    verified=True, reason="pin curado verificado", ranked=ranked)

    if decision["found"]:
        winner = decision["winner"]
        spec = _spec_from_candidate(winner["candidate"], curated)
        if spec is None:
            return Verdict.NADA, None
        verdict = Verdict.CONFIABLE if winner["verified_vendor"] else Verdict.DUDOSO
        return verdict, _draft(service, winner["candidate"], spec,
                               source=winner["candidate"].get("source", "registry"),
                               score=winner["score"], verified=winner["verified_vendor"],
                               reason=decision["reason"], ranked=ranked)

    # best_match NO encontró (umbral/ambigüedad) — PERO el top puede ser un BORRADOR usable:
    # el matcher rechaza por seguridad (no auto-equipa); el dudoso NO auto-confía: probe arbitra.
    top = ranked[0]
    if top["score"] >= _DRAFT_FLOOR:
        spec = _spec_from_candidate(top["candidate"], curated)
        if spec is not None:
            return Verdict.DUDOSO, _draft(
                service, top["candidate"], spec, source=top["candidate"].get("source", "registry"),
                score=top["score"], verified=False,
                reason=f"borrador below-threshold ({top['score']:.2f} ≥ piso {_DRAFT_FLOOR:.2f}; "
                       f"el matcher no auto-equipa, probe_mcp arbitra)", ranked=ranked)

    return Verdict.NADA, None


__all__ = ["classify"]
