"""
loop/budget.py — §6 · el cap duro + la contabilidad del loop.

El loop interno NO puede girar al pedo: cada llamada viva, cada token del cerebro
y cada segundo cuentan contra un techo. `Budget` fija los topes; `Ledger` mide el
gasto real y dictamina CUÁNDO parar (`exhausted()` devuelve la razón, no un bool
pelado, para que el log diga POR QUÉ se cortó).

Convergencia (§6) la decide el motor (engine), pero las PALANCAS de rendimientos
decrecientes viven acá (`diminishing_returns`): <k tools nuevas en N vueltas.

Stdlib only, sin red. El reloj entra por inyección (default time.monotonic) para
poder testear el corte por tiempo sin dormir.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class Budget:
    """Los topes DUROS del loop. Pasar 0 / None desactiva ese eje puntual, pero
    siempre queda al menos `max_rounds` como backstop."""
    max_rounds: int = 6           # vueltas del loop interno
    max_live_calls: int = 60      # requests HTTP vivas (observer + validator)
    max_synth_tokens: int = 60_000  # tokens del cerebro acumulados
    max_seconds: float = 240.0    # pared de tiempo total
    # rendimientos decrecientes: si en las últimas `window` vueltas se verificaron
    # < `min_new` tools nuevas EN TOTAL, el loop convergió.
    dr_window: int = 2
    dr_min_new: int = 1


@dataclass
class Ledger:
    """La contabilidad VIVA contra un Budget. Mutable: el loop la va cargando."""
    budget: Budget
    clock: Callable[[], float] = time.monotonic
    rounds: int = 0
    live_calls: int = 0
    synth_tokens: int = 0
    started_at: float = field(default=0.0)
    # historial de verificadas-nuevas por vuelta (para rendimientos decrecientes)
    new_verified_per_round: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    # ── registradores (los llaman las capas / el engine) ──────────────────────
    def tick_round(self) -> None:
        self.rounds += 1

    def add_calls(self, n: int = 1) -> None:
        self.live_calls += max(0, n)

    def add_tokens(self, n: int) -> None:
        self.synth_tokens += max(0, n)

    def record_new_verified(self, n: int) -> None:
        self.new_verified_per_round.append(max(0, n))

    def elapsed(self) -> float:
        return self.clock() - self.started_at

    # ── consultas de techo (cap DURO; el engine las chequea antes de cada paso) ─
    def can_make_call(self) -> bool:
        return self.live_calls < self.budget.max_live_calls

    def tokens_left(self) -> int:
        return max(0, self.budget.max_synth_tokens - self.synth_tokens)

    def diminishing_returns(self) -> bool:
        """<dr_min_new tools nuevas en las últimas dr_window vueltas ⇒ convergió.
        Solo aplica cuando ya hubo al menos `dr_window` vueltas (si no, falso)."""
        w = self.budget.dr_window
        if len(self.new_verified_per_round) < w:
            return False
        return sum(self.new_verified_per_round[-w:]) < self.budget.dr_min_new

    def exhausted(self) -> Optional[str]:
        """Razón de corte por BUDGET (no por convergencia de frontera). None si
        todavía hay margen. El engine la usa como guardia dura."""
        b = self.budget
        if self.rounds >= b.max_rounds:
            return f"max_rounds ({b.max_rounds}) alcanzado"
        if self.live_calls >= b.max_live_calls:
            return f"max_live_calls ({b.max_live_calls}) alcanzado"
        if self.synth_tokens >= b.max_synth_tokens:
            return f"max_synth_tokens ({b.max_synth_tokens}) alcanzado"
        if self.elapsed() >= b.max_seconds:
            return f"max_seconds ({b.max_seconds:.0f}s) alcanzado"
        return None

    def snapshot(self) -> dict:
        return {
            "rounds": self.rounds,
            "live_calls": self.live_calls,
            "synth_tokens": self.synth_tokens,
            "elapsed_s": round(self.elapsed(), 2),
            "caps": {
                "max_rounds": self.budget.max_rounds,
                "max_live_calls": self.budget.max_live_calls,
                "max_synth_tokens": self.budget.max_synth_tokens,
                "max_seconds": self.budget.max_seconds,
            },
        }
