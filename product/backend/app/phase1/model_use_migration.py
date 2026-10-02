"""Control de convivencia entre la ruta heredada y Modelos v2."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.phase1.model_route_flags import RouteMode
from app.phase1.model_use_contract import ModelUse, RouteSnapshot
from app.phase1.model_use_resolver import CatalogReader, ResolutionFailure, resolve_model_use


@dataclass(frozen=True)
class MigrationDecision:
    mode: RouteMode
    use_aleph_v2: bool
    snapshot: Optional[RouteSnapshot] = None
    shadow_error: Optional[dict] = None


def admit_for_mode(request: ModelUse, *, mode: RouteMode, owner_id: Optional[str],
                   read_catalog: CatalogReader) -> MigrationDecision:
    """Decide sin ejecutar.

    - legacy: no paga preflight y conserva exactamente la ruta anterior;
    - shadow: mide admisión, pero un fallo nunca altera el turno heredado;
    - aleph_v2: falla fuerte y entrega el snapshot que consume el gateway.
    """
    if mode is RouteMode.LEGACY:
        return MigrationDecision(mode=mode, use_aleph_v2=False)
    try:
        snapshot = resolve_model_use(
            request, owner_id=owner_id, read_catalog=read_catalog
        )
    except ResolutionFailure as exc:
        if mode is RouteMode.SHADOW:
            return MigrationDecision(
                mode=mode, use_aleph_v2=False, shadow_error=exc.as_detail()
            )
        raise
    return MigrationDecision(
        mode=mode,
        use_aleph_v2=(mode is RouteMode.ALEPH_V2),
        snapshot=snapshot,
    )


__all__ = ["MigrationDecision", "admit_for_mode"]
