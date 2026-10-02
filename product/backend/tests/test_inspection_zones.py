"""Guard del carve LÓGICO de Motor B. [Casa 2 · Fase 4]

El carve físico daba seguridad por estructura (un archivo nuevo cae en resolve/ o forge/ por
donde lo guardás). El carve lógico (manifiesto `platform/inspection/zones.py`) la da con ESTE
test: si alguien agrega un módulo a `platform/inspection/` sin clasificarlo, se pone ROJO. Así
la allowlist de 4.2 —que deriva de zones.ships()— no puede desincronizarse en silencio.
"""
from pathlib import Path

from inspection import zones

_INSPECTION = Path(zones.__file__).resolve().parent

# Harness / máquinas que NO se clasifican (no son el motor; no derivan a la allowlist).
_SKIP_NAMES = {"zones", "__main__"}
_SKIP_PREFIXES = ("test_", "selftest", "verify_", "sonda_", "probe_", "demo_")


def _shippable_modules() -> set[str]:
    mods: set[str] = set()
    for p in _INSPECTION.rglob("*.py"):
        rel = p.relative_to(_INSPECTION)
        parts = rel.with_suffix("").parts
        if "__pycache__" in parts or "fixtures" in parts:
            continue
        if rel.stem.startswith(_SKIP_PREFIXES) or rel.stem in _SKIP_NAMES:
            continue
        mods.add("/".join(parts))
    return mods


def test_every_inspection_module_is_zoned():
    """Todo módulo de inspection/ está en EXACTAMENTE una zona (o el test cae en rojo)."""
    zoned = zones.RESOLVE | zones.SHARED | zones.FORGE
    on_disk = _shippable_modules()
    unclassified = on_disk - zoned
    assert not unclassified, (
        "módulos de inspection/ SIN clasificar en zones.py: "
        f"{sorted(unclassified)} — agregalos a RESOLVE|SHARED|FORGE "
        "(la allowlist del cliente de 4.2 deriva de zones.ships())"
    )


def test_no_zone_overlap():
    """Un módulo no puede estar en dos zonas (viaja/queda tiene que ser inequívoco)."""
    assert not (zones.RESOLVE & zones.SHARED), zones.RESOLVE & zones.SHARED
    assert not (zones.RESOLVE & zones.FORGE), zones.RESOLVE & zones.FORGE
    assert not (zones.SHARED & zones.FORGE), zones.SHARED & zones.FORGE


def test_zones_reference_only_real_files():
    """Drift al revés: zones.py no clasifica módulos que ya no existen en disco."""
    on_disk = _shippable_modules()
    ghosts = (zones.RESOLVE | zones.SHARED | zones.FORGE) - on_disk
    assert not ghosts, f"zones.py clasifica módulos inexistentes: {sorted(ghosts)}"
