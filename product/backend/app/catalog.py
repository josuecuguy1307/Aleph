"""
catalog.py — Catalog loader for puppet-ai-core
Parametrizable: nicho is a path parameter — zero hardcoded domain names.
"""

import re
from pathlib import Path
from typing import Optional

# Root of the catalog. [Casa 2 · Fase 4 · 4.1] frozen-aware: bajo PyInstaller los recursos
# viven en _MEIPASS, no en parents[3] (que apunta FUERA del bundle). Se cablea
# aleph_paths.resource_root(); catalog.py se importa ANTES de que main.py meta platform/ en
# sys.path, así que el import va guardado (mismo patrón que aleph_paths.is_client). En dev,
# resource_root() == parents[3] (la raíz del repo) → byte-idéntico.
try:
    import aleph_paths as _ap
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "platform"))
    import aleph_paths as _ap
_REPO_ROOT = _ap.resource_root()
CATALOG_ROOT = _REPO_ROOT / "catalog" / "templates"


def _parse_template_md(md_text: str) -> dict:
    """Extract structured fields from a template.md file."""
    result = {}

    # Title line: "# T01 — Nombre humano"
    title_match = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    if title_match:
        result["nombre"] = title_match.group(1).strip()

    # ID interno
    id_match = re.search(r"\*\*ID interno:\*\*\s*(.+)", md_text)
    if id_match:
        result["id"] = id_match.group(1).strip()

    # Tier
    tier_match = re.search(r"\*\*Tier:\*\*\s*(.+)", md_text)
    if tier_match:
        result["tier"] = tier_match.group(1).strip()

    # Fricción
    friccion_match = re.search(r"\*\*Fricción de onboarding:\*\*\s*(.+)", md_text)
    if friccion_match:
        raw = friccion_match.group(1).strip()
        if raw.upper().startswith("CERO"):
            result["friccion"] = "cero-friccion"
            result["friccion_detalle"] = raw
        else:
            # GATEADO — requiere ...
            gate_match = re.search(r"GATEADO\s*[—-]\s*(.+)", raw, re.IGNORECASE)
            result["friccion"] = "gateado"
            result["friccion_detalle"] = gate_match.group(1).strip() if gate_match else raw

    # Gallery description: "## Qué hace el agente (galería del workshop)"
    gallery_match = re.search(
        r"## Qué hace el agente.*?\n\n(.+?)(?:\n\n---|\Z)",
        md_text,
        re.DOTALL,
    )
    if gallery_match:
        result["descripcion"] = gallery_match.group(1).strip()

    return result


def _parse_surgery_params(config: dict) -> dict:
    """Extract surgery_params from config.json."""
    return config.get("surgery_params", {})


def load_catalog(nicho: str) -> list[dict]:
    """
    Load all templates for a given nicho from catalog/templates/{nicho}/.
    Returns a list of template dicts with gallery metadata and surgery params.
    nicho is fully parametric — no domain name is hardcoded here.
    """
    import json

    nicho_dir = CATALOG_ROOT / nicho
    if not nicho_dir.exists() or not nicho_dir.is_dir():
        return []

    templates = []
    for template_dir in sorted(nicho_dir.iterdir()):
        if not template_dir.is_dir():
            continue

        md_file = template_dir / "template.md"
        config_file = template_dir / "config.json"

        if not md_file.exists():
            continue

        md_text = md_file.read_text(encoding="utf-8")
        parsed = _parse_template_md(md_text)

        surgery_params: dict = {}
        belt_path: str = ""
        tool_filters: dict = {}
        if config_file.exists():
            try:
                cfg = json.loads(config_file.read_text(encoding="utf-8"))
                surgery_params = _parse_surgery_params(cfg)
                # The catalog DECLARES its belt path — the UI must not guess it.
                # Read it from the template's real config.json (it already has it).
                belt_path = cfg.get("belt_path", "") or ""
                # The catalog also DECLARES which servers/tools this template uses.
                # The UI passes this verbatim so the test run boots exactly the
                # right (and only the right) MCP servers — never guessing.
                tool_filters = cfg.get("tool_filters", {}) or {}
            except (json.JSONDecodeError, OSError):
                pass

        # Fallback id to directory name if not found in md
        if "id" not in parsed:
            parsed["id"] = template_dir.name

        templates.append({
            "id": parsed.get("id", template_dir.name),
            "nombre": parsed.get("nombre", template_dir.name),
            "descripcion": parsed.get("descripcion", ""),
            "tier": parsed.get("tier", ""),
            "friccion": parsed.get("friccion", ""),
            "friccion_detalle": parsed.get("friccion_detalle", ""),
            "belt_path": belt_path,
            "tool_filters": tool_filters,
            "surgery_params": surgery_params,
        })

    return templates


def nicho_exists(nicho: str) -> bool:
    """Check if a nicho directory exists in the catalog."""
    return (CATALOG_ROOT / nicho).is_dir()
