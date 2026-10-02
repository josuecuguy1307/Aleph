# -*- mode: python ; coding: utf-8 -*-
"""Backend congelado del pack Educación; onedir dentro del sidecar de Aleph."""
import os

from PyInstaller.building.api import COLLECT
from PyInstaller.utils.hooks import collect_all

REPO = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
STACK = os.path.join(REPO, "third_party", "deeptutor")

datas, binaries, hidden = collect_all("deeptutor")
# `run_server.py` hands the ASGI target to uvicorn as a dotted string, so the
# application module is not visible to PyInstaller's static import graph. Keep
# the actual app in the frozen backend; otherwise the child exits immediately
# with `Could not import module "deeptutor.api.main"` while the Next process may
# still briefly report ready.
hidden += ["deeptutor.api.main"]
# Aleph Educación mounts these routers by dynamic module name so that one optional
# surface cannot prevent the tutor from starting. PyInstaller cannot infer string-based
# imports; keep the exact allow-list from ``deeptutor.api.main`` in the frozen backend.
hidden += [
    f"deeptutor.api.routers.{name}"
    for name in (
        "agent_config", "attachments", "book", "capabilities_settings", "co_writer",
        "dashboard", "imports", "knowledge", "mastery_path", "memory", "notebook",
        "personas", "plugins_api", "question", "question_notebook", "quiz_judge",
        "sessions", "settings", "mcp_settings", "skills", "space_mcp", "subagents",
        "system", "tools", "voice",
    )
]
# ``services.config`` lazy-loads this module through importlib from __getattr__.
hidden += [
    "deeptutor.services.config.test_runner",
]
# ``core.agentic`` is a deliberately lazy facade: several members are resolved through
# module-level __getattr__/importlib. This spec runs before Analysis adds STACK to its
# import path, so collect_submodules() silently sees only the package installed in the
# build venv and can omit source-tree modules. Keep the complete, audited source set.
hidden += [
    f"deeptutor.core.agentic.{name}"
    for name in (
        "client", "labeled_step", "labels", "loop", "messages",
        "tool_arg_guard", "tool_dispatch", "usage",
    )
]
# ``CapabilityRegistry.load_builtins()`` resolves every capability class through
# ``importlib.import_module`` over the string paths in
# ``deeptutor/runtime/bootstrap/builtin_capabilities.py``. Nothing imports them
# statically, so PyInstaller never sees them and the frozen tutor answers every turn
# with ``Unknown capability: chat. Available: []`` — the registry swallows the seven
# ``ModuleNotFoundError`` in ``capability_registry.py:56`` and starts up empty.
# This list MIRRORS ``BUILTIN_CAPABILITY_CLASSES``: adding a capability there without
# adding it here ships a tutor that cannot run it.
hidden += [
    "deeptutor.agents.chat.capability",             # chat
    "deeptutor.capabilities.solve.capability",      # deep_solve
    "deeptutor.agents.question.capability",         # deep_question
    "deeptutor.agents.research.capability",         # deep_research
    "deeptutor.agents.math_animator.capability",    # math_animator
    "deeptutor.agents.visualize.capability",        # visualize
    "deeptutor.capabilities.mastery.capability",    # mastery_path
]
# LOS DATOS DEL STACK. `collect_all("deeptutor")` de arriba devuelve cero en las TRES columnas,
# no sólo en `hidden`: el venv efímero del build hace `uv pip sync requirements-lock.txt` y nunca
# instala el stack, así que PyInstaller no tiene paquete instalado del que recolectar. La obra 1
# declaró los módulos a mano y dejó `datas` en cero — medido: 0 de 138 archivos no-.py viajaban,
# y `_internal/deeptutor` ni existía en el bundle. El costo de eso no es un error visible sino
# capacidades MUDAS: `deep_solve` devolvía `{}` en 8 ms porque
# `capabilities/solve/prompts/en/system.md` no estaba adentro, y con él se caían cinco de las
# siete. Son 764 KB en total; el criterio es el mismo que con las clases: declarar todo y que el
# build muera fuerte si el árbol dejó de tener lo que este spec promete.
_STACK_PKG = os.path.join(STACK, "deeptutor")
_stack_datas = []
for _dir, _subdirs, _files in os.walk(_STACK_PKG):
    _subdirs[:] = [d for d in _subdirs if d != "__pycache__"]
    _destino = os.path.normpath(os.path.join("deeptutor", os.path.relpath(_dir, _STACK_PKG)))
    for _f in _files:
        if _f.endswith((".py", ".pyc", ".pyo")) or _f == ".DS_Store":
            continue
        _stack_datas.append((os.path.join(_dir, _f), _destino))
if not _stack_datas:
    raise SystemExit(f"spec: el stack de Educación no tiene archivos de datos en {_STACK_PKG}")
_prompts = [o for o, _ in _stack_datas if f"{os.sep}prompts{os.sep}" in o]
if not _prompts:
    raise SystemExit("spec: no viaja ningún prompt de Educación — las capacidades quedarían mudas")
print(f"spec Educación: {len(_stack_datas)} archivos de datos del stack, {len(_prompts)} prompts")
datas += _stack_datas
# pypdfium2 necesita tanto su dylib como su árbol de avisos. El segundo además se
# copia como aviso de distribución por build_app.sh (Resources/PDFIUM-NOTICES).
for package in ("pypdfium2", "pypdfium2_raw", "pypdfium2_cfg", "pypdfium2_cli"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hidden += h

a = Analysis(
    [os.path.join(REPO, "deploy", "fase4", "deeptutor_pack_serve.py")],
    pathex=[STACK], binaries=binaries, datas=datas, hiddenimports=hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["test", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="deeptutor_backend",
    debug=False, strip=True, upx=False, console=True,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=True, upx=False, name="deeptutor_backend",
)
