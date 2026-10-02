#!/usr/bin/env python3
"""Mide los umbrales del matcher contra el corpus vivo del registro MCP.

No cambia el matcher ni equipa servidores. Lee todas las versiones ``latest`` del
registro oficial y arma carriles separados con candidatos reales:

* ``official_product``: cada namespace de procedencia verificada puntuado contra
  la identidad de producto publicada en su leaf. Es la consulta productiva.
* ``official_owner``: control secundario contra el dueño del namespace.
* ``unverified_control``: el mismo corpus/consulta de producto, pero sin crédito
  de procedencia. Es un control conservador del carril comunitario.

El corte recomendado es el score mínimo de ``official_product`` y se aplica sólo
a procedencia verificada. Comunidad conserva 0.80 + margen: así pasan todos los
official medidos sin aplicarles esa relajación a entradas comunitarias.

Uso:
    python qa/calibrar_registro_scores.py \
      --output reports/step5/registro-calibracion.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "platform"))

from inspection import mcp_matcher, mcp_registry  # noqa: E402

_ENDPOINT = f"{mcp_registry.REGISTRY_BASE}/v0/servers"
_OFFICIAL_META = "io.modelcontextprotocol.registry/official"
_GENERIC_PRODUCT_TOKENS = {
    "api",
    "app",
    "apps",
    "connector",
    "integration",
    "mcp",
    "server",
    "servers",
    "service",
    "tools",
}


def _fetch_json(params: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = _ENDPOINT + "?" + urllib.parse.urlencode(params)
    if os.environ.get("ALEPH_REGISTRY_TRANSPORT") == "curl":
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                completed = subprocess.run(
                    [
                        "curl",
                        "--fail",
                        "--silent",
                        "--show-error",
                        "--http2",
                        "--max-time",
                        str(timeout),
                        "--header",
                        "Accept: application/json",
                        "--user-agent",
                        "aleph-registry-score-calibration/1.0",
                        url,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return json.loads(completed.stdout)
            except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(1)
        raise RuntimeError(f"no pude leer {url} con curl: {last_error}") from last_error

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "aleph-registry-score-calibration/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"no pude leer {url}: {exc}") from exc


def fetch_latest(*, page_size: int, timeout: float, max_entries: int | None) -> tuple[list[dict], int]:
    """Descarga el corpus latest completo mediante el cursor público."""
    entries: list[dict] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": page_size, "version": "latest"}
        if cursor:
            params["cursor"] = cursor
        payload = _fetch_json(params, timeout)
        page = payload.get("servers") or []
        if not isinstance(page, list):
            raise RuntimeError("el registro devolvió `servers` con una forma inesperada")
        entries.extend(page)
        pages += 1
        if max_entries is not None and len(entries) >= max_entries:
            return entries[:max_entries], pages
        next_cursor = (payload.get("metadata") or {}).get("nextCursor")
        if not next_cursor:
            return entries, pages
        if next_cursor == cursor:
            raise RuntimeError("el cursor del registro no avanzó")
        cursor = next_cursor


def _candidate(entry: dict) -> dict | None:
    """Usa la misma normalización productiva; evita duplicar reglas de namespace."""
    return mcp_registry._candidate(entry)  # type: ignore[attr-defined]


def _product_query(candidate: dict) -> str:
    """Identidad corta del producto publicada en el leaf, sin relleno MCP."""
    leaf = candidate.get("leaf") or ""
    tokens = [
        token
        for token in re.split(r"[^A-Za-z0-9]+", leaf)
        if token and token.lower() not in _GENERIC_PRODUCT_TOKENS and not token.isdigit()
    ]
    return " ".join(tokens)


def _quantile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    index = round((len(sorted_values) - 1) * fraction)
    return sorted_values[index]


def _summary(rows: list[dict]) -> dict[str, Any]:
    values = sorted(float(row["score"]) for row in rows)
    return {
        "n": len(rows),
        "min": values[0] if values else None,
        "p05": _quantile(values, 0.05),
        "p25": _quantile(values, 0.25),
        "median": _quantile(values, 0.50),
        "p75": _quantile(values, 0.75),
        "p95": _quantile(values, 0.95),
        "max": values[-1] if values else None,
    }


def _compact(row: dict) -> dict:
    return {
        "query": row["query"],
        "name": row["name"],
        "vendor_kind": row["vendor_kind"],
        "score": row["score"],
        "signals": row["signals"],
    }


def _extremes(rows: list[dict], *, reverse: bool, n: int = 12) -> list[dict]:
    ordered = sorted(rows, key=lambda row: (row["score"], row["name"]), reverse=reverse)
    return [_compact(row) for row in ordered[:n]]


def _count_passing(rows: Iterable[dict], threshold: float) -> int:
    return sum(float(row["score"]) >= threshold for row in rows)


def _by_vendor_kind(rows: list[dict], threshold: float) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind in sorted({str(row["vendor_kind"]) for row in rows}):
        subset = [row for row in rows if row["vendor_kind"] == kind]
        passing = _count_passing(subset, threshold)
        result[kind] = {
            **_summary(subset),
            "passing_at_0_80": passing,
            "rejected_at_0_80": len(subset) - passing,
        }
    return result


def calibrate(entries: list[dict], *, pages: int, page_size: int) -> dict[str, Any]:
    pairs = [
        (entry, candidate)
        for entry in entries
        if (candidate := _candidate(entry)) is not None
    ]
    candidates = [candidate for _, candidate in pairs]
    official_product_rows: list[dict] = []
    official_owner_rows: list[dict] = []
    unverified_control_rows: list[dict] = []
    status_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    skipped_non_active = 0

    for entry, candidate in pairs:
        meta = ((entry.get("_meta") or {}).get(_OFFICIAL_META)) or {}
        status = meta.get("status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        kind = candidate.get("vendor_kind") or "unknown"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if status != "active":
            skipped_non_active += 1
            continue

        provenance_verified = kind in {"dns", "github_org"}
        if not provenance_verified:
            continue

        owner_query = candidate.get("vendor") or ""
        owner_score = mcp_matcher.score_candidate(owner_query, candidate)
        official_owner_rows.append(
            {
                "query": owner_query,
                "name": candidate["name"],
                "vendor_kind": kind,
                "score": owner_score["score"],
                "signals": owner_score["signals"],
            }
        )

        product_query = _product_query(candidate)
        if product_query:
            product_score = mcp_matcher.score_candidate(product_query, candidate)
            official_product_rows.append(
                {
                    "query": product_query,
                    "name": candidate["name"],
                    "vendor_kind": kind,
                    "score": product_score["score"],
                    "signals": product_score["signals"],
                }
            )
            unverified = {
                **candidate,
                "vendor": "sin-procedencia",
                "vendor_kind": "unknown",
            }
            control_score = mcp_matcher.score_candidate(product_query, unverified)
            unverified_control_rows.append(
                {
                    "query": product_query,
                    "name": candidate["name"],
                    "vendor_kind": kind,
                    "score": control_score["score"],
                    "signals": control_score["signals"],
                }
            )

    official_product = _summary(official_product_rows)
    official_owner = _summary(official_owner_rows)
    unverified_control = _summary(unverified_control_rows)
    cutoff = official_product["min"]
    community_cut = mcp_matcher.UNVERIFIED_MIN_SCORE
    official_passing_at_080 = _count_passing(official_product_rows, community_cut)
    official_rejected_at_080 = len(official_product_rows) - official_passing_at_080

    return {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "endpoint": _ENDPOINT,
            "parameters": {"version": "latest", "limit": page_size},
            "pages": pages,
            "entries": len(entries),
            "candidates": len(candidates),
            "unique_names": len({candidate["name"] for candidate in candidates}),
            "status_counts": dict(sorted(status_counts.items())),
            "vendor_kind_counts": dict(sorted(kind_counts.items())),
            "calibration_skipped_non_active": skipped_non_active,
        },
        "method": {
            "official_product": (
                "score(product identity from leaf, candidate), conservado sólo "
                "cuando vendor_kind=dns|github_org"
            ),
            "official_owner": "score(candidate.vendor, candidate), control secundario",
            "unverified_control": (
                "misma consulta y manifest real, pero vendor_kind=unknown y sin "
                "crédito de procedencia"
            ),
            "community_threshold_unchanged": community_cut,
            "weights": {
                "name": mcp_matcher.W_NAME,
                "vendor": mcp_matcher.W_VENDOR,
                "trust": mcp_matcher.W_TRUST,
                "semantic": mcp_matcher.W_SEMANTIC,
            },
        },
        "distribution": {
            "official_product": official_product,
            "official_product_by_vendor_kind": _by_vendor_kind(
                official_product_rows, community_cut
            ),
            "official_owner": official_owner,
            "unverified_control": unverified_control,
        },
        "calibration": {
            "lanes_separated": True,
            "official_recommended_cutoff": cutoff,
            "official_passing_at_recommended": (
                _count_passing(official_product_rows, cutoff)
                if cutoff is not None else None
            ),
            "official_passing_at_0_80": official_passing_at_080,
            "official_rejected_at_0_80": official_rejected_at_080,
            "official_rejected_rate_at_0_80": (
                round(official_rejected_at_080 / len(official_product_rows), 6)
                if official_product_rows else None
            ),
            "unverified_passing_at_community_cut": _count_passing(
                unverified_control_rows, community_cut
            ),
            "unverified_passing_if_official_cut_were_misapplied": (
                _count_passing(unverified_control_rows, cutoff)
                if cutoff is not None else None
            ),
            "note": (
                "El corte official sólo corresponde a procedencia verificada. "
                "Comunidad conserva 0.80 + margen; no aplicar el corte official allí."
            ),
        },
        "evidence": {
            "lowest_official_product": _extremes(
                official_product_rows, reverse=False
            ),
            "highest_unverified_control": _extremes(
                unverified_control_rows, reverse=True
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-entries", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.page_size <= 100:
        parser.error("--page-size debe estar entre 1 y 100")
    if args.max_entries is not None and args.max_entries < 1:
        parser.error("--max-entries debe ser positivo")

    entries, pages = fetch_latest(
        page_size=args.page_size,
        timeout=args.timeout,
        max_entries=args.max_entries,
    )
    result = calibrate(entries, pages=pages, page_size=args.page_size)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
