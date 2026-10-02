"""
dispatch/ — LA COSTURA resolver → despachador → motor (§0.5).

Módulo NUEVO y autocontenido (sibling de loop/ strategy/ library/). MONTA sobre piezas
que YA existen — no reescribe ninguna:

  • classifier.py — PURO/read-only: mcp_registry.search + mcp_matcher.rank → un Verdict
    {CONFIABLE, DUDOSO, NADA} derivado de las señales del matcher, + el `draft` (run-spec del
    candidato). NO toca el mundo, NO dispara gate.
  • dispatcher.py — rutea el verdict a su path. Dueño del GATE VISIBLE §0.5 (preguntar por
    defecto + toggle opt-in "siempre auto"). Determinístico: routing + confirm, sin cerebro.
  • liveness.py — el CANDADO verify-from-environment de los paths que tocan el mundo: §9 SSRF
    guard ANTES de conectar, byo_mcp.probe_mcp (tools/list = árbitro), y un tools/call de
    liveness opcional. CERO validación nueva: monta sobre probe_mcp.

Frontera (LÍNEA DURA): este módulo SOLO vive bajo dispatch/. LEE y LLAMA (read-only) al
resolver/matcher/registry, byo_mcp.probe_mcp, run_cascade, equip_resolved y contracts —
NUNCA los edita. El insight del dudoso ("un MCP dudoso es un borrador con prior") se realiza
en SUSTRATO MCP: el draft te dice CUÁL MCP arrancar (ahorra discovery), probe_mcp arbitra
(tools/list contra el server vivo → los reales se forjan, los phantom se dropean). El moat
REST (library/) NO participa del dudoso — queda para targets REST crudos (el path NADA).
"""
from __future__ import annotations

from inspection.dispatch.models import (
    Draft,
    DispatchResult,
    GateRequest,
    Verdict,
)
from inspection.dispatch.classifier import classify
from inspection.dispatch.dispatcher import dispatch

__all__ = [
    "Verdict",
    "Draft",
    "GateRequest",
    "DispatchResult",
    "classify",
    "dispatch",
]
