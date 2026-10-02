"""
strategy/types.py — los TIPOS del loop externo §4. CONGELADO para FASE 3.

Viven ACÁ (no en contracts.py) por la frontera de archivos: contracts.py es
compartido con otra lane en paralelo. Reusamos los tipos de contracts.py por
import (C.CandidateTool, C.VerifiedTool, C.FailedTool, C.FailureClass, …) y SOLO
agregamos lo que el torneo necesita.

Invariante central (el contrato del candado, §3): un peldaño "RINDE" ⇔ al menos
una candidata SOBREVIVIÓ al candado vivo — NUNCA "devolvió un doc". Lo fuerza la
property `yielded` (verified no-vacío), no la buena fe del peldaño.
"""
from __future__ import annotations

import abc
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# Los 4 PELDAÑOS de la cascada (§4) — el orden ES la prioridad: barato → caro.
# ══════════════════════════════════════════════════════════════════════════════
class Rung(str, Enum):
    A_SELF_DESCRIBING = "A"   # autodescriptivo — sniff /openapi.json /swagger · POST /graphql introspect
    B_FINGERPRINT     = "B"   # huella — ¿familia conocida? → reusa el RESOLVER (mcp_resolver)
    C_CONVENTION      = "C"   # convención — /api/v1 + observación pasiva de la raíz
    D_ACTIVE          = "D"   # activo — lo que el loop interno §3 ya hace (cerebro + minería)


class Outcome(str, Enum):
    """El veredicto de UN peldaño tras pasar (o no) por el candado."""
    YIELDED  = "yielded"   # candidatas SOBREVIVIERON el candado → rinde (gatilla salida temprana A/B)
    PARTIAL  = "partial"   # unas sobreviven, otras 404 (doc STALE) → forjá lo que hay y SEGUÍ abajo
    REJECTED = "rejected"  # propuso candidatas pero TODAS cayeron el candado
    EMPTY    = "empty"     # no produjo candidatas (no hay doc / no hay familia)
    SWITCH   = "switch"    # señal nivel-2: estrategia equivocada → cambiá de peldaño
    SKIPPED  = "skipped"   # el peldaño no aplica (ej: B sin red al registro público)


@dataclass(frozen=True)
class DiscoverySignal:
    """Una señal de descubrimiento que un peldaño levantó. ALIMENTA el switch
    nivel-2: un /openapi.json que dio 200 al lado es la "señal de peldaño
    superior" que distingue "tool equivocada" de "ESTRATEGIA equivocada"."""
    kind: str               # openapi | swagger | spec | graphql | rest_pattern | root_index | har
    url: str                # URL REDACTADA donde apareció (apta para log)
    status: int             # 200 = señal viva
    detail: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# StrategyResult — lo que UN peldaño produce. *** CONGELADO para FASE 3 ***
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class StrategyResult:
    """Lo que devuelve `Strategy.propose(ctx)`.

    El candado §3 es el árbitro: `verified`/`dropped` SALEN del LiveValidator (o,
    en el peldaño B, de la validación viva del resolver). `aggregate_failure` es la
    clase §5 AGREGADA del lote (la calcula el orquestador, no el validador
    per-tool) — ej. `ALL_404_OPENAPI` cuando TODO cayó 404 habiendo señal de doc.
    """
    rung: Rung
    outcome: Outcome
    candidates: tuple[C.CandidateTool, ...] = ()          # priors que el peldaño generó
    verified:   tuple[C.VerifiedTool, ...]  = ()          # SOBREVIVIERON el candado (lo único forjable)
    dropped:    tuple[C.FailedTool, ...]    = ()          # cayeron, con su FailureClass §5
    signals:    tuple[DiscoverySignal, ...] = ()          # señales para el switch nivel-2
    aggregate_failure: Optional[C.FailureClass] = None    # clase §5 del LOTE (ej. ALL_404_OPENAPI)
    family:     Optional[dict] = None                     # peldaño B: resolve_service(...) crudo
    used_brain: bool = False                              # economía §6: A/B/C=False, D=True
    budget:     dict = field(default_factory=dict)        # snapshot del ledger al cerrar el peldaño
    notes:      str  = ""

    # ── lecturas para el orquestador ──────────────────────────────────────────
    @property
    def yielded(self) -> bool:
        """RINDE de verdad: candidatas sobrevivieron el candado. NO 'devolvió algo'."""
        return self.outcome in (Outcome.YIELDED, Outcome.PARTIAL) and bool(self.verified)

    @property
    def won(self) -> bool:
        """¿Este peldaño es candidato a SALIDA TEMPRANA? Forjó tools vivas (A/C/D) o
        resolvió+validó una familia conocida vía el resolver (B). El orquestador
        decide si la salida temprana aplica (A/B) o si se siguen acumulando (C/D)."""
        return self.yielded or (self.outcome is Outcome.YIELDED and self.family is not None)

    @property
    def stale_count(self) -> int:
        """Cuántas candidatas cayeron 404 (NOT_FOUND) — la firma de un doc STALE."""
        return sum(1 for f in self.dropped if f.failure is C.FailureClass.NOT_FOUND)


# ══════════════════════════════════════════════════════════════════════════════
# Strategy — la ABC que cada peldaño implementa
# ══════════════════════════════════════════════════════════════════════════════
class Strategy(abc.ABC):
    """Un peldaño de la cascada §4. `propose` genera priors y los pasa por el
    candado compartido (vía ctx). No forja: devuelve QUÉ sobrevivió; el
    orquestador forja UNA vez desde la unión."""

    rung: ClassVar[Rung]

    @abc.abstractmethod
    def propose(self, ctx: "StrategyContext") -> StrategyResult:
        raise NotImplementedError


# ══════════════════════════════════════════════════════════════════════════════
# StrategyContext — el substrate COMPARTIDO de la cascada (UN ledger, UN candado)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class StrategyContext:
    """Lo que toda la cascada comparte. Garantías que el contrato fija:

      • budget §6 = UN solo `ledger`/`budget` para la cascada ENTERA (no N por peldaño);
      • candado §3 = UN solo `validator` (LiveValidator) — el árbitro es el mismo en cada peldaño;
      • SSRF (Capa 0) = `guarded_get` corre el guard ANTES de CADA fetch de descubrimiento.

    Los servicios (guard/session/http/validator/ledger) los construye e inyecta el
    orquestador (cascade.build_context); los peldaños solo los CONSUMEN. Tipados
    laxos a propósito: types.py no importa loop/* (frontera de archivos)."""
    # crudos
    base_url: str
    api_key: str
    principal: C.Principal
    slug: str
    # servicios compartidos (inyectados por la cascada — UNA instancia c/u)
    guard: Any            # C.SSRFGuard  · .check(url) -> GuardVerdict
    session: Any          # C.Session    · ya adquirida (Capa 1)
    keyed_http: Any       # LiveHTTP CON la key (validación de endpoints)
    discovery_http: Any   # LiveHTTP SIN la key (sniff de docs públicas)
    validator: Any        # LiveValidator compartido · .validate(session, cands) -> C.Validation
    ledger: Any           # Ledger compartido · cap §6 ÚNICO
    budget: Any           # Budget original (para derivar el remanente de D)
    # perillas del target (genéricas; se reenvían a rung D / forja)
    auth_param: str = "api_key"
    validate_path: str = "/configuration"
    validate_query: Optional[dict] = None
    soft_error_keys: tuple = ()
    soft_notice_keys: tuple = ()
    dispatch_param: Optional[str] = None
    min_interval: float = 0.0
    api_shape_hint: str = ""
    passive_probes: tuple = ()
    master_secret: Optional[str] = None
    cred_root: Any = C.SYNTH_BELTS_DIR
    synth_alias: str = "brain"
    on_event: Optional[Callable[[dict], None]] = None

    def emit(self, ev: dict) -> None:
        if self.on_event:
            self.on_event(ev)

    def guarded_get(self, url: str, query: Optional[dict] = None, *, keyed: bool = False):
        """SSRF guard (Capa 0) ANTES de CADA fetch de descubrimiento. Devuelve el
        HttpResult, o None si el guard bloqueó (fail-closed) — el peldaño trata el
        None como "no pude mirar ahí" y sigue."""
        verdict = self.guard.check(url)
        if not verdict:
            self.emit({"type": "guard.deny", "url": url, "reason": getattr(verdict, "reason", "")})
            return None
        http = self.keyed_http if keyed else self.discovery_http
        return http.get(url, query)


# ══════════════════════════════════════════════════════════════════════════════
# CascadeResult — el veredicto del torneo entero (auditable para el gate)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class CascadeResult:
    ok: bool
    base_url: str
    winner: Optional[Rung] = None                 # qué peldaño forjó (o resolvió, B)
    early_exit_at: Optional[Rung] = None          # dónde cortó la cascada (None = corrió hasta D)
    forged: Optional[C.ForgedMCP] = None          # el MCP forjado desde la UNIÓN de verificadas
    verified: tuple[C.VerifiedTool, ...] = ()      # unión deduplicada (stale: A + C + D)
    family: Optional[dict] = None                  # si ganó B: la familia resuelta (handoff al resolver)
    rungs: tuple[StrategyResult, ...] = ()         # el rastro de TODOS los peldaños corridos
    switches: tuple[dict, ...] = ()                # cada switch nivel-2 con su razón (§5)
    budget: dict = field(default_factory=dict)
    convergence: str = ""
    error: str = ""

    @property
    def used_brain(self) -> bool:
        return any(r.used_brain for r in self.rungs)


__all__ = [
    "Rung", "Outcome", "DiscoverySignal", "StrategyResult", "Strategy",
    "StrategyContext", "CascadeResult",
]
