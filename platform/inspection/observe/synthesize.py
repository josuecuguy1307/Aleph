"""
observe/synthesize.py — de la acción observada → un capability-block (tool spec).

Primera versión (FASE 2): toma el ObservedAction y arma una "card" mínima con la
forma del modelo de belt del org (label/category/tools/params), donde los params
son los campos VARIABLES detectados (lo que el humano tipeó). FASE 3 la convertirá
en un mcpServers entry real; acá alcanza para que el Cuarto la muestre naciendo.

Regla de zona (misma C3 del Cuarto): acción que cambia estado (POST/PUT/…) → write
(entrega); lectura (GET) → read (fuentes).
"""
from __future__ import annotations

from typing import Any

from inspection.models import ObservedAction


def _category_for(action: ObservedAction) -> str:
    p = action.primary_request
    if p is not None and p.is_state_changing:
        return "write"
    return "read"


def _label_for(intent: str) -> str:
    intent = (intent or "").strip()
    return intent[:1].upper() + intent[1:] if intent else "Tool"


def synthesize_capability(action: ObservedAction) -> dict[str, Any]:
    p = action.primary_request
    params = [
        {"name": f.name, "type": f.inferred_type, "location": f.location, "example": f.example}
        for f in action.field_schema if f.variable
    ]
    constants = [
        {"name": f.name, "type": f.inferred_type, "location": f.location, "value": f.example}
        for f in action.field_schema if not f.variable
    ]
    return {
        "label": _label_for(action.intent),
        "category": _category_for(action),
        "intent": action.intent,
        "method": p.method if p else None,
        "host": p.host if p else None,
        "path": p.path if p else None,
        "url": p.url if p else None,
        "params": params,            # los campos del tool (variables)
        "constants": constants,      # fijos del software (csrf/ids/flags)
        "tools": [_slug(action.intent)],
    }


def _slug(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "_" for c in (text or "tool"))
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_") or "tool"


# ── FASE 3: de la acción observada → una TOOL MCP real y parametrizable ─────────

_JSONSCHEMA_TYPE = {
    "integer": "integer", "number": "number", "boolean": "boolean",
    "email": "string", "url": "string", "string": "string",
    "array": "array", "object": "object",
}


def synthesize_tool(action: ObservedAction) -> dict[str, Any]:
    """
    Convierte el ObservedAction en una TOOL MCP completa:
      - `mcp_tool`: definición estilo MCP (name/description/inputSchema) — lo que el
        agente ve en tools/list.
      - `request`: el TEMPLATE de la request real (method/url/body/query/headers).
      - `param_slots`: dónde inyectar cada parámetro variable (location+key) al llamar.
    El replayer (observe/replay) toma esto + args del modelo y reconstruye la request.
    """
    cap = synthesize_capability(action)
    p = action.primary_request
    var_fields = [f for f in action.field_schema if f.variable]

    props: dict[str, Any] = {}
    required: list[str] = []
    param_slots: list[dict[str, Any]] = []
    for f in var_fields:
        props[f.name] = {
            "type": _JSONSCHEMA_TYPE.get(f.inferred_type, "string"),
            "description": f"campo '{f.name}' (observado en {f.location})",
            "example": f.example,
        }
        required.append(f.name)
        param_slots.append({"name": f.name, "location": f.location, "key": f.name})

    body_kind = None
    if p is not None and isinstance(p.post_data_json, dict):
        ct = (p.request_headers.get("content-type") or "").lower()
        body_kind = "form" if "form-urlencoded" in ct else "json"

    return {
        "mcp_tool": {
            "name": _slug(action.intent),
            "description": f"{cap['label']} — sintetizada de una demostración en {p.host if p else '?'}.",
            "inputSchema": {"type": "object", "properties": props, "required": required},
        },
        "label": cap["label"],
        "category": cap["category"],          # read|write|send → zona / gate
        "request": {
            "method": p.method if p else "GET",
            "url": p.url if p else None,
            "body": p.post_data_json if (p and isinstance(p.post_data_json, dict)) else None,
            "body_kind": body_kind,
            "query": dict(p.query) if p else {},
        },
        "param_slots": param_slots,
        "constants": cap["constants"],
    }
