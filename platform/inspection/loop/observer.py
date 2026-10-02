"""
loop/observer.py — Capa 2 · el Observador (§1).

Dos modos, según el contrato:

  • 1ra vuelta PASIVA (frontier vacía): mira lo que el target EXPONE sin adivinar
    tools — pega la raíz y el "describite" canónico (`/configuration` en TMDB) y se
    queda con lo que vuelva crudo. De ahí salen las primeras Capability CONFIRMED.
  • vueltas siguientes ACTIVAS (frontier con pistas): toma una pista sin explorar
    (un endpoint que un read minado destapó), la PEGA viva y mira la respuesta
    cruda. "Puede ver parcial" → por eso el loop vuelve a observar la frontera que
    se abre.

No sintetiza ni valida: solo produce el mapa de capacidades + CONFIRMED. La
respuesta cruda viaja al sintetizador para que proponga sobre EVIDENCIA, no sobre
memoria sola.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.live_http import HttpResult, LiveHTTP  # noqa: E402

# rutas de descubrimiento pasivo: NO son un catálogo de tools — son las superficies
# canónicas de "¿qué sos?" que una API REST suele exponer. El raíz revela el sobre
# de error; /configuration (si existe) revela la forma del servicio. Si no existen,
# el observador simplemente registra el status que vuelva (sigue siendo evidencia).
_PASSIVE_PROBES = ("", "/configuration")

# cuánto cuerpo crudo viaja al synth por observación (evidencia, no la respuesta entera).
_SNIPPET = 1400


def _snippet(res: HttpResult) -> str:
    return (res.text or "")[:_SNIPPET]


class LiveObserver:
    """Capa 2 contra software vivo. Satisface el Protocol C.Observer."""

    def __init__(self, http: LiveHTTP, *, passive_probes: Sequence[str] = _PASSIVE_PROBES):
        self._http = http
        self._passive_probes = tuple(passive_probes)

    def observe(self, session: C.Session, frontier: Sequence[C.FrontierLead]) -> C.Observation:
        base = session.base_url.rstrip("/")
        if not frontier:
            return self._observe_passive(base)
        return self._observe_active(base, frontier)

    # ── 1ra vuelta · PASIVA ───────────────────────────────────────────────────
    def _observe_passive(self, base: str) -> C.Observation:
        cap_map: dict[str, Any] = {"mode": "passive", "probes": {}}
        confirmed: list[C.Capability] = []
        for path in self._passive_probes:
            res = self._http.get(base + path)
            label = path or "/"
            cap_map["probes"][label] = {
                "status": res.status,
                "elapsed_ms": res.elapsed_ms,
                "shape": _kind_of(res.json),
                "snippet": _snippet(res),
            }
            if res.ok and res.has_shape:
                confirmed.append(C.Capability(
                    endpoint=path or "/", method="GET",
                    evidence=f"{res.status} · {_kind_of(res.json)} · {_top_keys(res.json)}",
                    fields=_top_keys(res.json),
                ))
        return C.Observation(capability_map=cap_map, confirmed=tuple(confirmed), passive=True)

    # ── vueltas siguientes · ACTIVA ───────────────────────────────────────────
    def _observe_active(self, base: str, frontier: Sequence[C.FrontierLead]) -> C.Observation:
        # elegí la primera pista que sea un endpoint pegable (path absoluto).
        lead = next((f for f in frontier if (f.hint or "").startswith("/")), None)
        if lead is None:
            return C.Observation(capability_map={"mode": "active", "note": "sin pista pegable"},
                                 confirmed=(), passive=False)
        res = self._http.get(base + lead.hint)
        cap_map: dict[str, Any] = {
            "mode": "active",
            "probed": lead.hint,
            "lead_kind": lead.kind,
            "source_tool": lead.source_tool,
            "status": res.status,
            "shape": _kind_of(res.json),
            "snippet": _snippet(res),
        }
        confirmed: tuple[C.Capability, ...] = ()
        if res.ok and res.has_shape:
            confirmed = (C.Capability(
                endpoint=lead.hint, method="GET",
                evidence=f"{res.status} · {_kind_of(res.json)} · {_top_keys(res.json)}",
                fields=_top_keys(res.json),
            ),)
        return C.Observation(capability_map=cap_map, confirmed=confirmed, passive=False)


def _kind_of(body: Any) -> str:
    if isinstance(body, dict):
        return "object"
    if isinstance(body, list):
        return "array"
    if body is None:
        return "none"
    return type(body).__name__


def _top_keys(body: Any) -> tuple[str, ...]:
    if isinstance(body, dict):
        return tuple(list(body.keys())[:24])
    if isinstance(body, list) and body and isinstance(body[0], dict):
        return tuple(list(body[0].keys())[:24])
    return ()
