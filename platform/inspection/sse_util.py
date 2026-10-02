"""sse_util.py — primitivas SHARED del stream de Motor B. [Casa 2 · Fase 4 · 4.2.a]

`_sse` (frame SSE del contrato) y `_slug` (slug estable) las usan tanto la FORJA
(`forge_router`, `session_router` — control) como el CURADO (`dispatch_router` — cliente).
Se extraen acá —zona NEUTRA, viaja— para poder **EXCLUIR** `forge_router` del `.exe` del
cliente (D-A: retención por AUSENCIA, no por flag) sin romper el import del dispatcher.
Mismo patrón que `loop/guard` en el carve. Stdlib only → no acopla nada.
"""
from __future__ import annotations

import json
import re


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s or "").strip("-").lower()
    return s or "x"


def _sse(ev: dict) -> str:
    """Un evento del contrato como frame SSE (event:<type> + data:<json>)."""
    return f"event: {ev.get('type')}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"


__all__ = ["_sse", "_slug"]
