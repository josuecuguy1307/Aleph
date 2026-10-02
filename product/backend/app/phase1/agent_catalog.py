"""agent_catalog.py — el EXPORTER (D3 · el PUENTE de identidad UUID→agent_ref).

Idempotente, keyed por UUID. Dado un puppet row (UUID + config) escribe
``<repo_root>/catalog/agents/agent-<uuid>.config.json`` ATÓMICAMENTE (tmp + os.replace).
El contenido = ``{**config, "schema_version": "v1"}`` MENOS ``canvas`` (presentación pura;
el motor la ignora — recipe_validator.py:48-50 — y engorda las recetas hijas). El slug
sale del UUID, JAMÁS del nombre: dos "My agent" con UUID distinto → dos archivos distintos
(nombre-derivado = asesino silencioso, el 2º pisaría al 1º → el padre correría la receta
EQUIVOCADA sin error).

Por qué EXPORT y no branch-DB (recon D3): belt_resolver.py es stdlib puro (sin red/DB,
docstring :23); ``resolve_agent_refs(refs, repo_root)`` sólo recibe un path — no tiene cómo
recibir una conexión. El candidato #3 existente (belt_resolver.py:313,
``catalog/agents/<slug>.config.json``) resuelve el archivo exportado byte-idéntico a los 2
fixtures. CERO cambios a belt_resolver.py / delegation.py / el validador.

La capa DB (repo.py) queda PURA: el router llama a export_agent() tras create_puppet /
update_config (el file I/O vive acá, no en el DB layer).
"""

from __future__ import annotations

import json
import os
import copy
import re
import tempfile
from pathlib import Path
from typing import Any, Union

SCHEMA_VERSION = "v1"
FALLBACK_AGENT_NAME = "Agente sin nombre"

_UUID = re.compile(r"^(?:(?:agent|agt|puppet)[-_])?[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$", re.I)
_OPAQUE_SEQUENCE = re.compile(r"^\d+(?:[-_./]\d+)*$")
_GENERATED_AGENT = re.compile(r"^(?:agent|puppet)[-_]?\d+$", re.I)
_OPAQUE_HEX = re.compile(r"^[0-9a-f]{20,}$", re.I)
_AGENT_REF = re.compile(r"(?:^|/)(?:agent[-_])?[^/]+\.(?:config\.)?json$", re.I)
_GENERATED_LABEL = re.compile(r"^(?:aleph|agent|puppet)\s+[\w-]*\s+[0-9a-f]{6,}$", re.I)


def clean_human_name(value: Any) -> str | None:
    """Return a displayable user name, never an opaque implementation key."""
    if not isinstance(value, str):
        return None
    name = " ".join(value.split())
    if not name or (_UUID.fullmatch(name) or _OPAQUE_SEQUENCE.fullmatch(name)
                    or _GENERATED_AGENT.fullmatch(name) or _OPAQUE_HEX.fullmatch(name)
                    or _AGENT_REF.search(name) or _GENERATED_LABEL.fullmatch(name)):
        return None
    return name


def display_name(name: Any = None, config: Any = None) -> str:
    """Prefer stored/legacy human names; IDs are never presentation fallback."""
    direct = clean_human_name(name)
    if direct:
        return direct
    if isinstance(config, dict):
        meta = config.get("meta")
        legacy = clean_human_name(meta.get("name") if isinstance(meta, dict) else None)
        if legacy:
            return legacy
    return FALLBACK_AGENT_NAME


def config_with_display_name(config: Any, name: Any) -> dict[str, Any]:
    """Synchronize recipe metadata with the human label without changing its ID."""
    cfg = copy.deepcopy(config) if isinstance(config, dict) else {}
    meta = cfg.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        cfg["meta"] = meta
    meta["name"] = display_name(name, cfg)
    return cfg


def slug_from_uuid(puppet_id: str) -> str:
    """'<uuid>' → 'agent-<uuid>'. MISMO slug que belt_resolver._slug_from_agent_ref deriva de
    'catalog/agents/agent-<uuid>.config.json' (basename sin .config.json) → biyección
    slug↔UUID↔path. El UUID es único/inmutable/filename-safe."""
    return f"agent-{puppet_id}"


def agent_ref_for(puppet_id: str) -> str:
    """El agent_ref REPO-RELATIVO que un padre coloca como pieza. Va a AMBOS destinos:
    belt.agent_refs[] (al proyectar) y el bloque canvas atom='agente'. Nunca absoluto."""
    return f"catalog/agents/{slug_from_uuid(puppet_id)}.config.json"


def child_recipe_from_config(config: Union[dict, str, None]) -> dict:
    """Transform de export (NO copia cruda):
      (a) FUERZA ``schema_version='v1'`` — la columna default es 'v0' (schema.sql:39) pero el
          resolver hard-checkea ``recipe.schema_version=='v1'`` (belt_resolver.py:276); v0/faltante
          → hijo silenciosamente NO-resoluble.
      (b) DROPA ``canvas`` — presentación pura (el motor la ignora); es exactamente lo que el
          cycle-walk lee del editor vivo, no del archivo hijo → recetas hijas lean.
      Resto (meta/model/belt/framing/rag/gates/autonomy/memory/keys) copia VERBATIM.
    """
    if isinstance(config, str):
        config = json.loads(config)
    config = config or {}
    recipe = {k: v for k, v in config.items() if k != "canvas"}
    recipe["schema_version"] = SCHEMA_VERSION
    return recipe


def export_agent(row: dict, repo_root: Union[str, Path]) -> Path:
    """Escribe la receta hija exportada para un puppet row (necesita ``id`` + ``config``).

    Idempotente: re-exportar con el mismo config produce el MISMO archivo byte-idéntico
    (JSON determinístico, sort_keys). Escritura ATÓMICA (tmp en el mismo dir → os.replace)
    para que un lector concurrente vea el archivo entero o nada, nunca un truncado. Devuelve
    el Path del archivo escrito.
    """
    puppet_id = str(row["id"])
    recipe = child_recipe_from_config(row.get("config"))

    dest_dir = Path(repo_root) / "catalog" / "agents"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{slug_from_uuid(puppet_id)}.config.json"

    payload = json.dumps(recipe, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    # escritura ATÓMICA: tmp en el MISMO dir (mismo filesystem → os.replace es atómico) + rename
    fd, tmp = tempfile.mkstemp(dir=str(dest_dir), prefix=".agent-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return dest


def delete_agent_export(puppet_id: str, repo_root: Union[str, Path]) -> bool:
    """Remove the derived delegation export for a persisted agent.

    The database row remains the source of truth; this file is only the bridge used by
    agent_ref resolution. Keep the path UUID-derived and scoped to catalog/agents so a
    user-provided label can never choose a filesystem target.
    """
    dest = Path(repo_root) / "catalog" / "agents" / f"{slug_from_uuid(str(puppet_id))}.config.json"
    dest.unlink(missing_ok=True)
    return not dest.exists()
