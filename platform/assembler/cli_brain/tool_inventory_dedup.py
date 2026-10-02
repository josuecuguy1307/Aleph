"""Colapso fail-closed del inventario textual duplicado de herramientas.

El borde OpenAI recibe dos representaciones de las mismas tools: los schemas en
``tools`` y, en algunos stacks, un catálogo humano dentro del mensaje ``system``.
Sólo quitamos el segundo cuando se puede reconstruir *byte por byte* desde los
schemas.  Una diferencia de nombre, descripción, parámetro, orden o required
deja el prompt intacto: una optimización dudosa no cruza el borde.
"""
from __future__ import annotations

from typing import Any


_TOOLS_OPEN = "## Tools\n\n"
_TOOLS_CLOSE = "\n\n## Skills (use load_skill to read full docs)"


def _function(tool: dict[str, Any]) -> dict[str, Any]:
    candidate = tool.get("function", tool)
    return candidate if isinstance(candidate, dict) else {}


def _render_vibetrading_inventory(tools: list[dict[str, Any]]) -> str:
    """Reconstruye exactamente ``ContextBuilder._format_tool_descriptions``.

    No importa código del workspace financiero: el borde sigue siendo autónomo
    y Finanzas conserva su comportamiento standalone.
    """
    blocks: list[str] = []
    for tool in tools:
        fn = _function(tool)
        name = fn.get("name")
        description = fn.get("description")
        parameters = fn.get("parameters")
        if not isinstance(name, str) or not isinstance(description, str):
            return ""
        parameters = parameters if isinstance(parameters, dict) else {}
        properties = parameters.get("properties", {})
        required = parameters.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            return ""

        param_lines: list[str] = []
        for param_name, schema in properties.items():
            if not isinstance(param_name, str) or not isinstance(schema, dict):
                return ""
            suffix = " (required)" if param_name in required else ""
            detail = schema.get("description", schema.get("type", ""))
            param_lines.append(f"    - {param_name}: {detail}{suffix}")
        param_text = "\n".join(param_lines) if param_lines else "    (no params)"
        blocks.append(f"### {name}\n{description}\n  Params:\n{param_text}")
    return "\n\n".join(blocks)


def colapsar_inventario_textual(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool, int]:
    """Devuelve mensajes nuevos, si colapsó y cuántos caracteres retiró.

    La forma es deliberadamente estricta. Sólo acepta el bloque emitido por el
    ``ContextBuilder`` de Finanzas y sólo si coincide exactamente con *todas* las
    definiciones estructuradas del turno.
    """
    if not tools:
        return messages, False, 0
    expected = _render_vibetrading_inventory(tools)
    if not expected:
        return messages, False, 0

    changed = False
    removed = 0
    result: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "system":
            result.append(message)
            continue
        content = message.get("content")
        if not isinstance(content, str):
            result.append(message)
            continue
        # Ambigüedad = no tocar. También evita colapsar dos inventarios pegados.
        if content.count(_TOOLS_OPEN) != 1 or content.count(_TOOLS_CLOSE) != 1:
            result.append(message)
            continue
        before, tail = content.split(_TOOLS_OPEN, 1)
        inventory, after = tail.split(_TOOLS_CLOSE, 1)
        if inventory != expected:
            result.append(message)
            continue

        new_content = before + "## Skills (use load_skill to read full docs)" + after
        new_message = dict(message)
        new_message["content"] = new_content
        result.append(new_message)
        changed = True
        removed += len(content) - len(new_content)
    return result, changed, removed
