# -*- mode: python ; coding: utf-8 -*-
# CASA 2 · Fase 4 · 4.0 — freeze CRUDO del backend local.
#
# DELIBERADAMENTE `datas=[]`: el objetivo NO es que ande, es VER el discovery vacío
# (hipótesis B5∪B6 — belts/catalog no viajan + parents[N] mal en _MEIPASS). Si esto
# arranca y el discovery da 0, la hipótesis se confirma. Sin Tauri, sin allowlist.
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

REPO = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

# El backend usa módulos PLANOS sobre sys.path (platform/ no es paquete): hay que
# darle a Analysis dónde encontrarlos, igual que main.py hace en runtime.
_PATHS = ["product/backend", "platform", "platform/db", "platform/flywheel",
          "platform/gates", "platform/assembler", "platform/connectors", "platform/sanitizer"]
pathex = [os.path.join(REPO, p) for p in _PATHS]
for _p in pathex:
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("ALEPH_ROLE", "client")

# [4.1] Los targets planos que hoy se cargan por ruta (aleph_paths.load_module_by_path)
# tienen que VIAJAR como datos (sus .py) y ser VISIBLES a Analysis (hiddenimports = cerrar
# su dep-closure).
_TARGET_DIRS = ["platform/gates", "platform/connectors", "platform/assembler",
                "platform/db", "platform/flywheel", "platform/sanitizer"]
# [4.1·datas] Y los DATOS de la vitrina/catálogo: belts + catalog viajan al bundle (sus
# .mcp.json/_meta/.md). Con los roots ya frozen-aware (catalog.CATALOG_ROOT y
# atoms_router._REPO → resource_root()), el discovery los encuentra en _MEIPASS.
_DATA_DIRS = ["catalog", "product/belts", "product/app/design"]  # [4.4.0] frontend Capa 0 (serving=C)
datas = [(os.path.join(REPO, d), d) for d in _TARGET_DIRS + _DATA_DIRS]

# LA REGLA: todo módulo cargado con `aleph_paths.load_module_by_path` va acá (Analysis no
# ve las cargas por ruta; sin la entrada el bundle se arma bien y falla en runtime).
# Escrita entera en `aleph_sidecar.spec` y en `aleph_paths.load_module_by_path` (regla 2).
# Esta es la SONDA: la lista puede quedar corta respecto del sidecar sin que sea un bug.
_TARGET_MODULES = [
    "connect_engine", "oauth_flow", "oauth_loopback", "connections", "approval_gate", "recipe_enforcer",
    "recipe_assembler", "assembler", "session", "vault", "db", "events_replay",
    "sanitizer", "tier_gate", "scrubber", "runtime_integration",
    "build_id",   # [4.3] identidad de build (el muro premium-local lo lee, lazy)
]

try:
    hidden = collect_submodules("app") + ["role", "aleph_paths"] + _TARGET_MODULES
except Exception as e:  # noqa: BLE001
    print("spec: collect_submodules('app') falló:", e)
    hidden = ["role", "aleph_paths"] + _TARGET_MODULES

a = Analysis(
    [os.path.join(REPO, "deploy", "fase4", "fase4_freeze_probe.py")],
    pathex=pathex,
    binaries=[],
    datas=datas,                    # [4.1] los .py target viajan; belts/catalog NO (frente siguiente)
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="aleph_freeze_probe",
    debug=False, strip=False, upx=False, console=True,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="aleph_freeze_probe",
)
