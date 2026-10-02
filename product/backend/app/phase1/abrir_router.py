"""
abrir_router.py — POST /v1/dev/abrir : ABRIR EL CÓDIGO EN EL EDITOR DE VERDAD.

[reforma · l] Regla de plataforma: **código → VS Code · configuración → formulario**.

El Cuarto tenía un tab «Código» que mostraba —y en parte dejaba EDITAR— el JSON de la
receta y el source del handler MCP dentro de un `<pre>`. Nadie edita código en un popup de
280px sin resaltado, sin buscar, sin deshacer y sin git. Lo que hace falta ahí no es un
editor peor: es un botón que abra el archivo en el editor que la persona ya usa.

CONTRATO DE SEGURIDAD (esta ruta LANZA UN PROCESO — se diseña cerrada):
  1. El cliente NO manda rutas. Manda un `ref` (server MCP) y el path lo RESUELVE el
     backend con el mismo `_find_server`/`_script_path` que ya usa el handler read-only.
     Un path del cliente sería «abrí lo que yo te diga» sobre la máquina del usuario.
  2. Lo resuelto tiene que caer DENTRO del repo/bundle (mismo anti-traversal del handler).
  3. Sólo corre cuando el proceso ES el cliente de escritorio (`aleph_paths.is_client()`).
     En el control plane no hay escritorio que abrir: responde 409 y lo DICE.
  4. Sin VS Code instalado no se falla mudo: se revela la carpeta en el explorador y la
     respuesta declara `via: "finder"` para que la UI diga qué pasó.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException

from app.phase1.tools_router import _find_server, _script_path, _REPO

# los tres nombres con los que VS Code aparece en cada plataforma (CLI primero: es el barato)
_VSCODE_CLI = ("code", "code-insiders", "codium")
_VSCODE_APP_MAC = "/Applications/Visual Studio Code.app"


def _es_cliente() -> bool:
    try:
        import aleph_paths  # type: ignore
        return bool(aleph_paths.is_client())
    except Exception:
        # sin el módulo (dev suelto) se decide por el env, que es el mismo interruptor
        return (os.environ.get("ALEPH_ROLE") or "").lower() == "client"


def _abrir(path: Path) -> dict:
    """Abre `path` en VS Code; si no está, revela la carpeta. Devuelve QUÉ hizo."""
    cli = next((c for c in _VSCODE_CLI if shutil.which(c)), None)
    if cli:
        subprocess.Popen([cli, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "via": "vscode", "con": cli}
    if sys.platform == "darwin":
        if Path(_VSCODE_APP_MAC).exists():
            subprocess.Popen(["open", "-a", _VSCODE_APP_MAC, str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "via": "vscode", "con": "Visual Studio Code.app"}
        subprocess.Popen(["open", "-R", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "via": "finder"}
    if sys.platform.startswith("linux") and shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(path.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "via": "finder"}
    raise HTTPException(status_code=409, detail={
        "error": "sin_editor",
        "detail": "No encontré VS Code ni una forma de abrir carpetas en este sistema."})


def build_abrir_router() -> APIRouter:
    router = APIRouter(prefix="/v1/dev", tags=["dev"])

    @router.post("/abrir")
    def abrir(body: dict = Body(...)):
        if not _es_cliente():
            raise HTTPException(status_code=409, detail={
                "error": "no_local",
                "detail": "Esto abre un archivo en tu máquina; sólo funciona en la app de escritorio."})
        ref = str((body or {}).get("ref") or "").strip()
        belt_ref = (body or {}).get("belt_ref") or None
        if not ref:
            raise HTTPException(status_code=422, detail={"error": "falta_ref", "detail": "falta el ref del MCP"})
        server, _, _tool = ref.partition(".")
        found = _find_server(server, belt_ref)
        if not found:
            raise HTTPException(status_code=404, detail={
                "error": "server_not_found", "detail": f"no encuentro el server '{server}'"})
        script: Optional[Path] = _script_path(found["cfg"])
        # server externo (npx/uvx/docker): no hay fuente local — se abre SU BELT, que es el
        # archivo que efectivamente se edita para cambiar cómo corre.
        destino = script if script is not None else (_REPO / found["belt_ref"])
        destino = Path(destino).resolve()
        if not str(destino).startswith(str(Path(_REPO).resolve())):
            raise HTTPException(status_code=400, detail={
                "error": "fuera_del_repo", "detail": "esa ruta cae fuera del repositorio"})
        if not destino.exists():
            raise HTTPException(status_code=404, detail={
                "error": "no_existe", "detail": f"el archivo ya no está: {destino.name}"})
        out = _abrir(destino)
        out["path"] = str(destino.relative_to(Path(_REPO).resolve()))
        out["externo"] = script is None
        return out

    return router


__all__ = ["build_abrir_router"]
