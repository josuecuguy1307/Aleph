"""
dispatch/models.py — los tipos del seam (SOLO forma, cero comportamiento).

Nombrado `models` y NO `types` a propósito: un `types.py` dentro del paquete sombrea el
módulo `types` de la stdlib (ya nos mordió en strategy/). Acá viven el Verdict de 3 valores
que el classifier deriva, el Draft (el "borrador con prior" = run-spec del candidato), el
GateRequest que ve el humano en el gate §0.5, y el DispatchResult congelado del contrato.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Verdict(str, Enum):
    """El veredicto de 3 valores que el classifier DERIVA de las señales del matcher
    (el resolver es binario found/NotFound; el 3-way no es nativo — ver classifier.py)."""
    CONFIABLE = "confiable"   # vendor verificado (DNS/github_org) o curado (pin/manual)
    DUDOSO = "dudoso"         # community sobre el bar, o top-candidate below-threshold = borrador
    NADA = "nada"             # sin candidato usable → forjar desde cero (cascada REST)


@dataclass(frozen=True)
class Draft:
    """El BORRADOR del dudoso/confiable = el prior que ahorra discovery: QUÉ MCP arrancar
    y CÓMO. NO es la verdad — probe_mcp arbitra contra el server vivo. `spec` tiene la forma
    que consume resolver.validate_live/equip_resolved (transport + url|command + slot de
    credencial). `claimed_tools` (si el prior trae nombres) habilita el drop de phantoms:
    lo que el borrador reclama pero el server vivo NO lista, se cae."""
    service: str
    server_name: str
    spec: dict                                  # run-spec (transport/url|cmd + credencial)
    vendor_kind: str = ""
    source: str = ""                            # registry | curated | curated_manual | ...
    score: float = 0.0
    verified_vendor: bool = False
    claimed_tools: tuple[str, ...] = ()         # nombres que el prior reclama (opcional)
    signature: tuple[str, ...] = ()             # tokens de firma curada (cross-check suave)
    reason: str = ""
    ranked: tuple[dict, ...] = ()               # top-N del matcher (auditable)


@dataclass(frozen=True)
class GateRequest:
    """Lo que el gate §0.5 le muestra al humano ANTES de tocar el mundo. Probear/forjar
    conecta a un MCP externo, usa creds y abre superficie SSRF → alta consecuencia."""
    service: str
    verdict: Verdict
    action: str                                 # "probe+equip" | "forge-from-scratch"
    server_name: str = ""
    transport: str = ""
    target: str = ""                            # url o command (redactado de credencial)
    needs_credential: bool = False
    claimed_tools: tuple[str, ...] = ()

    def summary(self) -> str:
        tgt = f" → {self.target}" if self.target else ""
        return (f"[{self.verdict.value}] {self.action} '{self.service}'"
                f"{(' (' + self.server_name + ')') if self.server_name else ''}"
                f" · {self.transport}{tgt}"
                f"{' · requiere credencial' if self.needs_credential else ''}")


@dataclass(frozen=True)
class DispatchResult:
    """*** CONTRATO CONGELADO *** — el veredicto del seam.

    `forged` lleva el ForgedMCP/registro cuando un path forjó/equipó algo. `verified` y
    `dropped` son los nombres de tools que pasaron / se cayeron el candado (phantom/caído).
    `gate_shown` = si el gate visible se disparó. `used_brain` = si el path quemó cerebro
    (dudoso/confiable: nunca; nada: lo que reporte la cascada)."""
    verdict: Verdict
    path: str                                   # "confiable" | "dudoso" | "nada" | "blocked"
    ok: bool = False
    forged: Any = None                          # dict de equip/forge, o CascadeResult-ish
    verified: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    used_brain: bool = False
    gate_shown: bool = False
    source: str = ""
    server_name: str = ""
    reason: str = ""
    error: str = ""
    meta: dict = field(default_factory=dict)


__all__ = ["Verdict", "Draft", "GateRequest", "DispatchResult"]
