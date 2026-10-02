"""
observe/emit_belt.py — la tool sintetizada → un BELT equipable (FASE 4).

Escribe el artefacto que el assembler ya sabe consumir: un belt `.mcp.json` con la
misma forma del catálogo (`_meta.cards` de cara al usuario + `mcpServers` con el
launcher real). El server es synth_mcp_server.py, parametrizado por el .spec.json
de la tool. Así el agente equipa la tool sintetizada como CUALQUIER capability —
vía belt_ref / belt_refs (la composición dinámica que ya soporta el assembler).

NO ejecuta nada: sólo emite archivos. La ejecución (y su gate) vive en el server.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ruta al server genérico (platform/inspection/synth_mcp_server.py)
_SERVER = Path(__file__).resolve().parents[1] / "synth_mcp_server.py"


def _belt_slug(tool_name: str) -> str:
    return (tool_name or "tool").replace("_", "-")


def synthesize_belt(spec: dict[str, Any], *, out_dir: str | Path,
                    niche: str = "synthesized") -> dict[str, Any]:
    """
    Emite (belt.mcp.json + tool.spec.json) en out_dir y devuelve sus rutas + el belt.
    El belt referencia synth_mcp_server.py con SYNTH_TOOL_SPEC=<spec.json>.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    tool_name = spec["mcp_tool"]["name"]
    slug = _belt_slug(tool_name)
    server_name = tool_name           # clave en mcpServers + backed_by de la card
    desc = spec["mcp_tool"]["description"]

    spec_path = out / f"{slug}.spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    belt = {
        "_meta": {
            "belt": slug,
            "slug": slug,
            "que_es": desc,
            "synthesized": True,
            "source": {"host": spec.get("request", {}).get("host"),
                       "intent": spec.get("label")},
            "cards": [{
                "id": tool_name,
                "label": spec.get("label", tool_name),
                "sub": f"sintetizada de una demostración · {spec.get('category', 'read')}",
                "auth": "keyless",
                "armario": "apps",
                "backed_by": server_name,
                "tools": [tool_name],
            }],
        },
        "mcpServers": {
            server_name: {
                "command": "python3",
                "args": [str(_SERVER)],
                "env": {"SYNTH_TOOL_SPEC": str(spec_path)},
                "caso": 1,
                "bucket": "B1",
                "nichos": [niche],
                "credenciales": "ninguna",
                "atomica": False,
                "description": desc,
            }
        },
    }
    belt_path = out / f"belt-{slug}.mcp.json"
    belt_path.write_text(json.dumps(belt, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "belt_path": belt_path,
        "spec_path": spec_path,
        "server_name": server_name,
        "tool_name": tool_name,
        "belt": belt,
    }
