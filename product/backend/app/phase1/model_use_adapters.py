"""Adaptadores puros desde los dos caminos existentes hacia ``model-use/v1``."""
from __future__ import annotations

from typing import Any, Optional

from app.phase1.model_use_contract import ModelUse


def adapt_workspace_raw(
    *,
    call_id: str,
    idempotency_key: str,
    workspace_id: str,
    call_class: str,
    selection_ref: Optional[str],
    selection_scope: str,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    messages: Optional[list[dict[str, Any]]] = None,
    attachments: Optional[list[dict[str, Any]]] = None,
    tools: Optional[list[dict[str, Any]]] = None,
    required_capabilities: Optional[list[str]] = None,
    stream: bool = True,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
) -> ModelUse:
    """LEY 15: crea una llamada válida con agente/política nulos."""
    return ModelUse.model_validate({
        "schema_version": "model-use/v1",
        "call_id": call_id,
        "idempotency_key": idempotency_key,
        "workspace_id": workspace_id,
        "call_class": call_class,
        "context": {
            "session_id": session_id,
            "task_id": task_id,
            "agent_id": None,
            "partner_id": None,
            "entity_id": entity_id,
        },
        "selection_ref": selection_ref,
        "selection_scope": selection_scope,
        "policy_ref": None,
        "capabilities": {"required": required_capabilities or []},
        "input": {"messages": messages or [], "attachments": attachments or []},
        "tools": {"definitions": tools or [], "required": bool(tools)},
        "generation": {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        },
        "stream": stream,
    })


def adapt_recipe_v1(
    *,
    recipe: dict[str, Any],
    agent_id: str,
    selection_ref: str,
    call_id: str,
    idempotency_key: str,
    workspace_id: str,
    call_class: str,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    messages: Optional[list[dict[str, Any]]] = None,
    attachments: Optional[list[dict[str, Any]]] = None,
    tools: Optional[list[dict[str, Any]]] = None,
    required_capabilities: Optional[list[str]] = None,
    stream: bool = True,
) -> ModelUse:
    """Adapta Recipe v1 sin copiar ``recipe.model`` al contrato público.

    ``selection_ref`` debe provenir del mapa server-side de migración. La receta queda
    referenciada como política y sigue gobernando al agente fuera de este payload.
    """
    if recipe.get("schema_version") != "v1":
        raise ValueError("adapt_recipe_v1 exige Recipe v1")
    if not str(agent_id or "").strip():
        raise ValueError("el adaptador de Recipe v1 exige agent_id")
    generation = recipe.get("model") or {}
    return ModelUse.model_validate({
        "schema_version": "model-use/v1",
        "call_id": call_id,
        "idempotency_key": idempotency_key,
        "workspace_id": workspace_id,
        "call_class": call_class,
        "context": {
            "session_id": session_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "partner_id": None,
            "entity_id": entity_id,
        },
        "selection_ref": selection_ref,
        "selection_scope": "agent",
        "policy_ref": f"recipe:v1:{agent_id}",
        "capabilities": {"required": required_capabilities or []},
        "input": {"messages": messages or [], "attachments": attachments or []},
        "tools": {"definitions": tools or [], "required": bool(tools)},
        "generation": {
            "temperature": generation.get("temperature"),
            "max_output_tokens": generation.get("max_tokens"),
        },
        "stream": stream,
    })


__all__ = ["adapt_recipe_v1", "adapt_workspace_raw"]
