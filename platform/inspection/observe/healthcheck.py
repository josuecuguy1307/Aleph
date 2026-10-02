"""
observe/healthcheck.py — DRIFT: la tool se forja observando el software UNA vez.

La tool sintetizada congela la request observada (método, path, campos, body_kind).
Cuando el software cambia —renombra un campo, mueve el endpoint, cambia el verbo— la
tool se rompe SILENCIOSA: sigue mandando la request vieja y el mundo responde mal (o
peor: responde 200 ignorando el campo que ahora se llama distinto). Acá le damos:

  · FIRMA observable + VERSIÓN al spec (`_synth`): la forma que, si cambia, rompe la tool.
  · RE-INSPECCIÓN: vuelve a observar el software y compara la firma fresca contra la
    congelada. Distingue dos fallas:
       – SHAPE-DRIFT  (método/path/campos/body_kind): rompe el CONTRATO de la tool → re-forjar.
       – ENDPOINT-MOVE (host:port de la url): rompe la URL → re-forjar (url nueva).
  · al detectar drift: marca el belt `_meta.stale=true` y devuelve el spec re-sintetizado
    con la versión bumpeada (la re-forja la decide el caller/endpoint).

Stdlib pura. La firma EXCLUYE el puerto efímero del host para el dígito de shape (un
fixture liga a un puerto random cada vez); el cambio de endpoint se reporta aparte.
"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
from typing import Any, Optional

from inspection.models import ObservedAction


# ── firma ───────────────────────────────────────────────────────────────────────

def _host_no_port(host: Optional[str]) -> Optional[str]:
    if not host:
        return host
    return host.split(":", 1)[0]


def _body_kind(action: ObservedAction) -> Optional[str]:
    p = action.primary_request
    if p is None or not isinstance(p.post_data_json, dict):
        return None
    ct = (p.request_headers.get("content-type") or "").lower()
    return "form" if "form-urlencoded" in ct else "json"


def action_signature(action: ObservedAction) -> dict[str, Any]:
    """La forma observable que, si cambia, rompe la tool. host SIN puerto (shape)."""
    p = action.primary_request
    return {
        "method": (p.method.upper() if p else None),
        "host": _host_no_port(p.host if p else None),
        "path": (p.path if p else None),
        "var_fields": sorted(f.name for f in action.field_schema if f.variable),
        "all_fields": sorted(f.name for f in action.field_schema),
        "body_kind": _body_kind(action),
        "endpoint": (p.url if p else None),     # informativo: url completa (con puerto)
    }


def signature_digest(sig: dict[str, Any]) -> str:
    """Dígito de SHAPE (excluye `endpoint`: el host:port no es parte del contrato)."""
    shape = {k: sig.get(k) for k in ("method", "host", "path", "var_fields", "body_kind")}
    raw = json.dumps(shape, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def stamp_spec(spec: dict[str, Any], action: ObservedAction, *,
               version: int = 1, observed_at: Optional[float] = None) -> dict[str, Any]:
    """Sella el spec con su firma + versión (additivo: no toca mcp_tool/request)."""
    sig = action_signature(action)
    spec["_synth"] = {
        "version": int(version),
        "observed_at": observed_at,
        "signature": sig,
        "digest": signature_digest(sig),
    }
    return spec


def spec_frozen_signature(spec: dict[str, Any]) -> dict[str, Any]:
    """La firma congelada del spec. Back-compat: si no fue sellado, la reconstruye."""
    meta = spec.get("_synth")
    if isinstance(meta, dict) and isinstance(meta.get("signature"), dict):
        return meta["signature"]
    # reconstrucción best-effort desde request + inputSchema (specs FASE-4 sin sello)
    req = spec.get("request", {}) or {}
    url = req.get("url") or ""
    parts = urllib.parse.urlsplit(url)
    props = (spec.get("mcp_tool", {}).get("inputSchema", {}) or {}).get("properties", {}) or {}
    required = (spec.get("mcp_tool", {}).get("inputSchema", {}) or {}).get("required", []) or []
    return {
        "method": (req.get("method") or "GET").upper(),
        "host": _host_no_port(parts.hostname),
        "path": parts.path or None,
        "var_fields": sorted(required),
        "all_fields": sorted(props.keys()),
        "body_kind": req.get("body_kind"),
        "endpoint": url or None,
    }


# ── comparación ─────────────────────────────────────────────────────────────────

def compare_signatures(frozen: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """Diff frozen→fresh. Separa shape-drift (rompe contrato) de endpoint-move (url)."""
    changes = []
    for k in ("method", "host", "path", "body_kind"):
        if frozen.get(k) != fresh.get(k):
            changes.append({"field": k, "was": frozen.get(k), "now": fresh.get(k)})
    fz = set(frozen.get("var_fields") or [])
    fr = set(fresh.get("var_fields") or [])
    fields_added = sorted(fr - fz)
    fields_removed = sorted(fz - fr)

    shape_drift = bool(changes or fields_added or fields_removed)
    endpoint_changed = (frozen.get("endpoint") != fresh.get("endpoint"))

    return {
        "drift": shape_drift,                       # rompe el CONTRATO de la tool
        "endpoint_changed": endpoint_changed,       # la url se movió (host:port/path)
        "changes": changes,
        "fields_added": fields_added,
        "fields_removed": fields_removed,
        "frozen_digest": signature_digest(frozen),
        "fresh_digest": signature_digest(fresh),
    }


def healthcheck_spec(spec: dict[str, Any], fresh_action: ObservedAction) -> dict[str, Any]:
    """
    Compara el spec congelado contra una observación fresca del software.

    `healthy` se decide por SHAPE-DRIFT (método/host-sin-puerto/path/campos/body_kind):
    eso es lo que rompe el CONTRATO de la tool. `endpoint_changed` (url completa, con
    puerto) queda INFORMATIVO — un puerto efímero cambia entre corridas sin que el
    contrato cambie; un host/path real que se mueve YA aparece en el shape-drift.
    """
    frozen = spec_frozen_signature(spec)
    fresh = action_signature(fresh_action)
    diff = compare_signatures(frozen, fresh)
    diff["version"] = int((spec.get("_synth") or {}).get("version") or 1)
    diff["healthy"] = not diff["drift"]
    return diff


__all__ = [
    "action_signature", "signature_digest", "stamp_spec", "spec_frozen_signature",
    "compare_signatures", "healthcheck_spec",
]
