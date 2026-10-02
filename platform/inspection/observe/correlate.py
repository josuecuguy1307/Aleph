"""
observe/correlate.py — aísla la SEÑAL del RUIDO y arma el schema de campos.

Una carga de página dispara ~decenas de requests (analytics, assets, polls). La
acción demostrada produce 1 (o pocas) requests reales. Correlate las separa con
una señal fuerte y verificable: la request cuyo payload CONTIENE los valores que
el humano tipeó, disparada DESPUÉS del submit, que cambia estado y es XHR/fetch.

Después extrae el schema: de la request primaria, qué campos son VARIABLES (los
que el humano tipeó → parámetros del futuro tool) vs constantes (csrf, ids fijos).
"""
from __future__ import annotations

import urllib.parse
from typing import Optional

from inspection.models import (
    CapturedRequest,
    FieldSpec,
    ObservedAction,
    REDACTED,
    infer_type,
    looks_secret_name,
    looks_secret_value,
)
from inspection.observe.recorder import RecordingBundle

import re

# patrones de ruido conocido (analytics / telemetría / beacons)
_NOISE_URL = re.compile(
    r"(google-analytics|googletagmanager|doubleclick|/gtag|/ga\b|segment\.|mixpanel|"
    r"amplitude|hotjar|sentry|/beacon|/collect|/track|/telemetry|/metrics|/ping|"
    r"facebook\.|fbevents|/rum|/heartbeat)", re.I,
)
_ASSET_TYPES = {"image", "stylesheet", "font", "media", "script", "manifest",
                "texttrack", "other", "ping", "eventsource", "websocket"}

_PRIMARY_THRESHOLD = 20      # score mínimo para considerar algo "la acción"


def _collect_demo_values(bundle: RecordingBundle) -> list[tuple[str, str]]:
    """[(valor, selector)] de lo que el humano tipeó (no secreto, len>=2)."""
    out: list[tuple[str, str]] = []
    seen = set()
    for e in bundle.events:
        if e.type in ("input", "change") and e.value:
            v = e.value.strip()
            if len(v) >= 2 and v.lower() not in seen:
                seen.add(v.lower())
                out.append((v, e.selector))
    return out


def _action_trigger_ts(bundle: RecordingBundle) -> float:
    """Timestamp del disparo de la acción (último submit/click), o action_at."""
    triggers = [e.ts for e in bundle.events if e.type in ("submit", "click")]
    return max(triggers) if triggers else bundle.action_at


def _haystacks(req: CapturedRequest) -> list[str]:
    """Texto donde buscar valores demostrados: body crudo + body decodeado + query."""
    hs = []
    if req.post_data:
        hs.append(req.post_data)
        try:
            hs.append(urllib.parse.unquote_plus(req.post_data))
        except Exception:
            pass
    if req.query:
        hs.append(" ".join(f"{k}={v}" for k, v in req.query.items()))
    return [h.lower() for h in hs if h]


def _score(req: CapturedRequest, demo_values, trigger_ts, target_host):
    score = 0
    reasons: list[str] = []
    matched: list[str] = []

    hs = _haystacks(req)
    for value, selector in demo_values:
        if any(value.lower() in h for h in hs):
            matched.append(value if not looks_secret_value(value) else REDACTED)
    if matched:
        score += 50
        reasons.append(f"payload contiene {len(matched)} valor(es) demostrado(s)")

    if req.is_state_changing:
        score += 15
        reasons.append(f"método {req.method} (cambia estado)")
    if req.is_xhr:
        score += 10
        reasons.append("xhr/fetch")
    if target_host and req.host == target_host:
        score += 5
        reasons.append("mismo host")

    if req.resource_type in _ASSET_TYPES:
        score -= 40
        reasons.append(f"asset/{req.resource_type}")
    if _NOISE_URL.search(req.url):
        score -= 50
        reasons.append("url de telemetría/ruido")

    # temporal: después del disparo = a favor; mucho antes = en contra
    if req.started_at >= trigger_ts - 0.25:
        score += 10
        reasons.append("posterior al disparo")
    elif req.started_at < trigger_ts - 1.0:
        score -= 5
        reasons.append("anterior a la acción")

    return score, reasons, matched


def _build_field_schema(primary: CapturedRequest, demo_values) -> list[FieldSpec]:
    if primary is None:
        return []
    demo_lookup = {v.lower(): sel for v, sel in demo_values}
    specs: list[FieldSpec] = []

    def add(name, location, value):
        is_var = str(value).strip().lower() in demo_lookup
        secret = looks_secret_name(name) or looks_secret_value(value)
        specs.append(FieldSpec(
            name=name,
            location=location,
            inferred_type=infer_type(value),
            variable=is_var,
            example=REDACTED if secret else value,
            demonstrated_from=demo_lookup.get(str(value).strip().lower()),
        ))

    body = primary.post_data_json
    if isinstance(body, dict):
        ct = (primary.request_headers.get("content-type") or "").lower()
        body_loc = "form" if "form-urlencoded" in ct else "json"
        for k, v in body.items():
            add(k, body_loc, v)
    # query params (sólo si aportan; típico en GET-acciones)
    for k, v in (primary.query or {}).items():
        add(k, "query", v)
    return specs


def correlate(bundle: RecordingBundle, *, top_n: int = 6) -> ObservedAction:
    target_host = urllib.parse.urlsplit(bundle.target_url).netloc
    demo_values = _collect_demo_values(bundle)
    trigger_ts = _action_trigger_ts(bundle)

    scored = []
    for req in bundle.requests:
        s, reasons, matched = _score(req, demo_values, trigger_ts, target_host)
        scored.append({"request": req, "score": s, "reasons": reasons, "matched": matched})
    scored.sort(key=lambda c: c["score"], reverse=True)

    primary = None
    if scored and scored[0]["score"] >= _PRIMARY_THRESHOLD:
        primary = scored[0]["request"]

    candidates = [c for c in scored if c["score"] > 0][:top_n]
    field_schema = _build_field_schema(primary, demo_values)

    notes: list[str] = []
    if not demo_values:
        notes.append("No se capturaron valores tipeados — correlación sólo por método/tipo/ruido.")
    if primary is None:
        notes.append("Ninguna request superó el umbral; revisa candidatos por score.")
    n_var = sum(1 for f in field_schema if f.variable)
    if primary is not None:
        notes.append(f"{n_var}/{len(field_schema)} campos detectados como variables (params del tool).")

    return ObservedAction(
        intent=bundle.intent,
        target_url=bundle.target_url,
        demonstrated_at=bundle.started_at,
        primary_request=primary,
        field_schema=field_schema,
        candidates=candidates,
        ui_events=bundle.events,
        total_requests=len(bundle.requests),
        noise_filtered=len(bundle.requests) - len(candidates),
        notes=notes,
    )
