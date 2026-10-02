"""
brands.py — Loader for catalog/brands.json.

The catalog DECLARES the brand (label, monogram, color, logo, human connection
name) for each belt server, plus the per-template gate copy. The UI consumes
this verbatim and never guesses. PARAMETRIZABLE: adding a nicho = adding its
servers here; zero hardcode in the UI.

GATE PER CONNECTOR (D1): the catalog declares each server's `tools_capability`
(the tool names it exposes). This module runs Security's enforcer
(platform/gates/recipe_enforcer.py) over those names and DERIVES a `gate` field
per connector ("money_touch" | "send" | null). The UI reads `gate` verbatim to
show the lock state — it never classifies money/send itself (single source of
truth = the enforcer). Zero nicho hardcode: the classification is by tool name.
"""

import importlib.util
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]  # product/backend/app -> repo root
BRANDS_PATH = _REPO_ROOT / "catalog" / "brands.json"
_ENFORCER_PATH = _REPO_ROOT / "platform" / "gates" / "recipe_enforcer.py"


@lru_cache(maxsize=1)
def _load() -> dict:
    if not BRANDS_PATH.exists():
        return {"tools": {}, "gates": {}, "_version": "0"}
    try:
        return json.loads(BRANDS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"tools": {}, "gates": {}, "_version": "0"}


@lru_cache(maxsize=1)
def _load_enforcer() -> Optional[Any]:
    """Carga el enforcer de Security por ruta (platform no es un paquete del backend).
    Misma técnica que main.py usa para vault/session. Si falla, devolvemos None y
    la derivación de gate degrada a null (fail-open en la UI, no rompe el catálogo)."""
    if not _ENFORCER_PATH.exists():
        return None
    try:
        import aleph_paths
        return aleph_paths.load_module_by_path("puppet_recipe_enforcer_brands", _ENFORCER_PATH)
    except Exception:
        return None


def _derive_gate(tools_capability: list[str]) -> Optional[str]:
    """Corre el enforcer sobre los nombres de tool del server y devuelve la
    clasificación de gate: 'money_touch' (gana), 'send', o None. Es la MISMA
    clasificación que el motor aplica EN EL PATH (suggests_money_touch / suggests_send),
    así el badge del taller no puede mentir vs lo que el agente realmente hará."""
    enf = _load_enforcer()
    if enf is None or not tools_capability:
        return None
    money = any(enf.suggests_money_touch(t) for t in tools_capability)
    if money:
        return "money_touch"
    send = any(enf.suggests_send(t) for t in tools_capability)
    if send:
        return "send"
    return None


def load_brands() -> dict:
    """Return the declared brand + gate catalog (tools, gates, version).

    Cada server en `tools` se enriquece con `gate` (money_touch|send|null),
    DERIVADO por el enforcer de Security sobre su `tools_capability`. La UI lo
    consume verbatim para el estado 'gateado' (candado)."""
    data = _load()
    tools = {}
    for server, brand in (data.get("tools", {}) or {}).items():
        enriched = dict(brand)
        enriched["gate"] = _derive_gate(brand.get("tools_capability", []) or [])
        tools[server] = enriched
    return {
        "version": data.get("_version", "0"),
        "tools": tools,
        "gates": data.get("gates", {}),
    }
