"""
tools_router.py — GET /v1/tools/{ref}/handler : el CÓDIGO del handler MCP de una pieza.

Profundidad 3 de la "pieza abierta" del Cuarto (decisión 4: READ-ONLY en v1). Dado un
`ref` = "server" o "server.tool" (+ belt_ref opcional), resuelve qué `.mcp.json` declara
ese server, y:
  · server LOCAL (python3 <script.py>) → devuelve el SOURCE del .py (read-only) + la línea
    de `def <tool>` si existe (para que la UI la resalte).
  · server EXTERNO (npx/uvx/docker)    → no hay handler local; devuelve external=true + cómo corre.

Anti-traversal: el .py DEBE caer dentro del repo. Nunca escribe (solo lectura).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

# [OBRA 6d] frozen-aware (bundle → _MEIPASS). MISMO patrón que `atoms_router` y
# `catalog_search_router`; en dev `resource_root() == parents[4]` → byte-idéntico.
#
# ⚠️ TODO lo que este módulo resuelve con `_REPO` VIAJA en el bundle: `catalog/templates` y
# `product/belts` son `_DATA_DIRS`, `platform/assembler/fixtures` es `_TARGET_DIR`. Pero el
# módulo vive en el PYZ, así que `parents[4]` caía en el PADRE de `_MEIPASS` —el TMPDIR del
# sistema— y ninguna de esas rutas existía. El fallo era MUDO: `_find_server` devolvía None
# y `_script_path` también, como si el belt simplemente no declarara el server.
try:
    import aleph_paths as _ap
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap
_REPO = _ap.resource_root()
_BELT_DIRS = [_REPO / "catalog" / "templates", _REPO / "platform" / "assembler" / "fixtures"]


def _expand(s: str) -> str:
    # ${PUPPET_BELTS} = <root>/product/belts — BELTS-ROOT ÚNICO (decisión T7), la MISMA
    # base que usan executor.py:71 y _puppet_run_env del assembler. Acá decía `_REPO`
    # (la raíz), o sea el mismo símbolo se expandía a dos lugares distintos dentro del
    # mismo artefacto y este lado resolvía a rutas que no existen.
    # Un export explícito del operador gana, igual que en el assembler.
    return ((s or "")
            .replace("${PUPPET_BELTS}",
                     os.environ.get("PUPPET_BELTS") or str(_REPO / "product" / "belts"))
            .replace("${PUPPET_REPO}", os.environ.get("PUPPET_REPO") or str(_REPO)))


def _find_server(server: str, belt_ref: Optional[str]) -> Optional[dict]:
    """Devuelve {cfg, belt_ref} del primer belt que declara `server`. Si belt_ref viene, ese."""
    paths = []
    if belt_ref:
        p = (_REPO / belt_ref).resolve()
        if str(p).startswith(str(_REPO)) and p.exists():
            paths = [p]
    if not paths:
        for d in _BELT_DIRS:
            if d.is_dir():
                paths.extend(sorted(d.rglob("*.mcp.json")))
    for p in paths:
        try:
            belt = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        srv = (belt.get("mcpServers") or {}).get(server)
        if srv:
            return {"cfg": srv, "belt_ref": str(p.relative_to(_REPO))}
    return None


def _script_path(cfg: dict) -> Optional[Path]:
    """El .py local del server (si lo hay), resuelto y validado dentro del repo."""
    if (cfg.get("command") or "") not in ("python3", "python"):
        return None
    for a in (cfg.get("args") or []):
        a = _expand(str(a))
        if a.endswith(".py"):
            p = Path(a)
            if not p.is_absolute():
                p = (_REPO / p)
            p = p.resolve()
            if str(p).startswith(str(_REPO)) and p.suffix == ".py" and p.exists():
                return p
    return None


def build_tools_router() -> APIRouter:
    router = APIRouter(prefix="/v1/tools", tags=["tools"])

    @router.get("/{ref}/handler")
    def tool_handler(ref: str, belt_ref: Optional[str] = Query(default=None)):
        server, _, tool = ref.partition(".")   # "server" o "server.tool"
        found = _find_server(server, belt_ref)
        if not found:
            raise HTTPException(status_code=404,
                detail={"error": "server_not_found", "detail": f"no encuentro el server '{server}'"})
        cfg = found["cfg"]
        script = _script_path(cfg)
        if script is None:
            # server externo (npx/uvx/docker): corre afuera, sin handler local que mostrar
            return {"ref": ref, "server": server, "tool": tool or None,
                    "belt_ref": found["belt_ref"], "external": True, "code": None,
                    "language": None, "command": cfg.get("command"),
                    "note": f"Esta pieza corre vía '{cfg.get('command')}' (servidor externo); no hay código local para mostrar."}
        code = script.read_text(encoding="utf-8")
        # mejor-esfuerzo: ubicar la línea de def <tool> para que la UI la resalte
        tool_line = None
        if tool:
            m = re.search(rf"^\s*def\s+{re.escape(tool)}\s*\(", code, re.MULTILINE)
            if m:
                tool_line = code[:m.start()].count("\n") + 1
        return {"ref": ref, "server": server, "tool": tool or None,
                "belt_ref": found["belt_ref"], "external": False, "language": "python",
                "path": str(script.relative_to(_REPO)), "lines": code.count("\n") + 1,
                "tool_line": tool_line, "code": code}

    return router


__all__ = ["build_tools_router"]
