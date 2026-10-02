"""Materialización server-side de una selección canónica para los runtimes heredados.

``model-use/v1`` sólo transporta ``selection_ref``. Los ejecutores actuales todavía
consumen el bloque plano ``recipe.model``; esta costura lo reconstruye dentro del
backend y conserva únicamente las perillas legítimas del agente. El navegador nunca
participa en esta traducción.

Los modelos auxiliares (workers/reporter/subagentes) se preservan byte a byte durante
esta primera migración. Son clases de llamada distintas y se moverán con flags propios;
mezclarlas con el Núcleo alteraría agentes y tools, justo lo que la convergencia prohíbe.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from app.phase1.model_use_contract import RouteSnapshot
from app.phase1.model_use_resolver import ResolutionFailure, resolve_model_use
from app.phase1.model_use_adapters import adapt_recipe_v1


_ROUTE_FIELDS = frozenset({
    "primary", "base_url", "alias", "byok_ref", "brain_provider", "fallback",
    "key", "api_key", "secret", "token", "key_env",
})


def selection_ref_for_recipe(recipe: dict[str, Any], catalog: dict[str, Any]) -> Optional[str]:
    """Mapea una Recipe v1 existente al ``picker_id`` canónico sin adivinar.

    Se acepta primero una referencia ya migrada. Para recetas anteriores se usa el
    mismo orden factual del puente del Cuarto: byok_ref, brain_provider, par
    model/base_url y, sólo si es inequívoco, model.
    """
    declared = recipe.get("model_use") if isinstance(recipe, dict) else None
    explicit = declared.get("selection_ref") if isinstance(declared, dict) else None
    rows = list(catalog.get("modelos") or [])
    if explicit and any(str(row.get("picker_id") or "") == str(explicit) for row in rows):
        return str(explicit)

    model = recipe.get("model") if isinstance(recipe, dict) else None
    if not isinstance(model, dict):
        return None

    def ref(row: dict[str, Any]) -> Optional[str]:
        value = str(row.get("picker_id") or "").strip()
        return value or None

    byok_ref = str(model.get("byok_ref") or "").strip()
    if byok_ref:
        hit = next((row for row in rows if str(row.get("byok_ref") or "") == byok_ref), None)
        if hit:
            return ref(hit)

    brain_provider = str(model.get("brain_provider") or "").strip()
    if brain_provider:
        hit = next(
            (row for row in rows if str(row.get("brain_provider") or "") == brain_provider),
            None,
        )
        if hit:
            return ref(hit)

    primary = str(model.get("primary") or model.get("model") or "").strip()
    base_url = str(model.get("base_url") or "").strip()
    if primary and base_url:
        hit = next((
            row for row in rows
            if str(row.get("model") or "") == primary
            and str(row.get("base_url") or "") == base_url
        ), None)
        if hit:
            return ref(hit)

    if primary:
        matches = [row for row in rows if str(row.get("model") or "") == primary]
        refs = {ref(row) for row in matches if ref(row)}
        if len(refs) == 1:
            return next(iter(refs))
    return None


def materialize_model_config(
    snapshot: RouteSnapshot,
    catalog: dict[str, Any],
    *,
    current: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Produce el ``model_cfg`` ejecutable dentro del backend.

    ``snapshot`` ya fue owner-gated y admitido. La fila se vuelve a localizar sólo para
    obtener la infraestructura privada. Controles como temperatura, límites, workers y
    reporter sobreviven; cualquier routing recibido del cliente se descarta.
    """
    row = next((
        item for item in (catalog.get("modelos") or [])
        if str(item.get("picker_id") or "") == snapshot.selection_ref
    ), None)
    if row is None:
        raise ResolutionFailure(
            "selection_not_found",
            "La selección admitida ya no existe en el catálogo canónico.",
            409,
            {"selection_ref": snapshot.selection_ref},
        )

    cfg = {
        key: value for key, value in dict(current or {}).items()
        if key not in _ROUTE_FIELDS
    }
    cfg.update({
        "primary": snapshot.resolved_model,
        "base_url": str(row.get("base_url") or ""),
    })
    for key in ("alias", "byok_ref", "brain_provider", "fallback"):
        if row.get(key) is not None:
            cfg[key] = row[key]
    return cfg


def materialize_recipe(
    recipe: dict[str, Any], snapshot: RouteSnapshot, catalog: dict[str, Any]
) -> dict[str, Any]:
    """Devuelve una copia de la receta con routing central y referencia auditable."""
    out = dict(recipe)
    out["model"] = materialize_model_config(
        snapshot, catalog, current=recipe.get("model") if isinstance(recipe, dict) else None
    )
    out["model_use"] = {
        "schema_version": "model-use/v1",
        "selection_ref": snapshot.selection_ref,
        "selection_scope": snapshot.selection_scope,
    }
    return out


def canonicalize_recipe_selection(
    recipe: dict[str, Any],
    *,
    selection_ref: str,
    owner_id: str,
    agent_id: str,
    read_catalog: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Convierte el payload secretless del Cuarto en la Recipe v1 interna.

    Esta operación no depende del flag de ejecución: si el cliente optó por mandar sólo
    un id, el backend debe persistir una receta legacy válida para que rollback siga
    funcionando. El runtime v2 volverá a resolver la referencia al ejecutar.
    """
    belt = recipe.get("belt") if isinstance(recipe, dict) else None
    needs_tools = bool(isinstance(belt, dict) and (
        belt.get("belt_ref") or belt.get("belt_refs") or belt.get("agent_refs")
        or belt.get("tool_filters")
    ))
    request = adapt_recipe_v1(
        recipe=recipe,
        agent_id=agent_id,
        selection_ref=selection_ref,
        call_id=f"save:{agent_id}",
        idempotency_key=f"save:{agent_id}:{selection_ref}",
        workspace_id="cuarto",
        call_class="agent.recipe.save",
        required_capabilities=["text", *(["tool_calling"] if needs_tools else [])],
        stream=True,
    )
    catalog = read_catalog(owner_id)
    snapshot = resolve_model_use(
        request, owner_id=owner_id, read_catalog=lambda _owner: catalog
    )
    return materialize_recipe(recipe, snapshot, catalog)


__all__ = [
    "canonicalize_recipe_selection", "materialize_model_config", "materialize_recipe",
    "selection_ref_for_recipe",
]
