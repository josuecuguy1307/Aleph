# -*- mode: python ; coding: utf-8 -*-
"""Freeze the Vibe-Trading server used by the Finanzas workspace.

The outer Aleph sidecar carries this onefile as opaque data. Keeping the Python
runtime here avoids making the installed workspace depend on whatever Python (or
which packages) happen to exist on the user's Mac.
"""
import os
import sys

from PyInstaller.building.api import COLLECT
from PyInstaller.building.build_main import Analysis, EXE, PYZ
from importlib.metadata import distributions as _distributions
from PyInstaller.utils.hooks import collect_submodules, copy_metadata


REPO = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
AGENT = os.path.join(REPO, "third_party", "vibetrading", "agent")
sys.path.insert(0, AGENT)


_DATA = []
for _source, _destination in (
    (os.path.join(AGENT, ".env.example"), "."),
    (os.path.join(AGENT, "src", "providers", "llm_providers.json"), "src/providers"),
    (os.path.join(AGENT, "src", "skills"), "src/skills"),
    (os.path.join(AGENT, "src", "scheduled_research", "playbooks"),
     "src/scheduled_research/playbooks"),
    (os.path.join(AGENT, "src", "shadow_account", "templates"),
     "src/shadow_account/templates"),
    (os.path.join(AGENT, "src", "swarm", "presets"), "src/swarm/presets"),
    (os.path.join(AGENT, "src", "factors", "zoo"), "src/factors/zoo"),
):
    if not os.path.exists(_source):
        raise SystemExit(f"Vibe-Trading spec: falta dato requerido: {_source}")
    _DATA.append((_source, _destination))


# ── [F2 · F] LA METADATA DE `fastmcp`, QUE EL PAQUETE PIDE DE SÍ MISMO ─────────────────────
# El síntoma, en el log del build: `Skipped src.tools.mcp: No package metadata was found for
# fastmcp`. No falta el MÓDULO —viene por `collect_submodules("src")`— falta su
# `fastmcp-*.dist-info`: PyInstaller copia el código pero no el directorio de metadata, y
# `importlib.metadata.version("fastmcp")` revienta en runtime. `copy_metadata` existe
# exactamente para eso.
#
# ⚠️ VA EN ESTE SPEC Y NO EN EL DEL SIDECAR, y eso hay que decirlo porque la propuesta original
# no lo distinguía: `src.tools.mcp` es de Finanzas
# (`third_party/vibetrading/agent/src/tools/mcp`), y este stack se congela con SU PROPIO venv,
# sincronizado desde `third_party/vibetrading/requirements-lock.txt` (`build_app.sh:318`).
# Ponerlo en `aleph_sidecar.spec` habría fallado al evaluar el spec: ese otro venv sale del lock
# de EDUCACIÓN y no tiene `fastmcp`.
#
# EL LOCK PINEA DOS Y NO SE ADIVINA CUÁL HACE FALTA: `fastmcp==3.4.6` (línea 950) y
# `fastmcp-slim[client,server]==3.4.6` (línea 954), y los `# via fastmcp-slim` del propio lock
# dicen que varios módulos los provee el slim. Acá se copia la metadata del nombre que el
# ERROR pide —`fastmcp`— y nada más: **si además hiciera falta la del slim, lo dice el TOC
# nuevo**, no una suposición. Adivinar el segundo enlace es cómo se agregan dependencias que
# nadie necesita.
# ── [Aleph] Y AHORA LA CLASE ENTERA, NO EL PAQUETE QUE MORDIÓ ─────────────────────────
#
# Todo lo de arriba se resolvió una vez, para `fastmcp`, cuando reventó. El 2026-08-29
# reventó OTRO de la misma familia y en la cara del dueño:
#
#     No package metadata was found for caio
#
# `caio` viaja como módulo —está en `_internal/caio`— pero SIN su `dist-info`, así que
# `importlib.metadata` no lo encuentra. Es exactamente el mismo defecto con otro nombre, y
# el próximo va a ser otro: cualquier paquete que le pregunte su versión a
# `importlib.metadata` rompe, y no hay forma estática de saber cuáles lo hacen.
#
# ASÍ QUE VIAJAN TODAS. Un `dist-info` son unos KB de texto —no el paquete, sólo su ficha—,
# de modo que copiarlas todas cuesta poco y cierra la familia de una vez en lugar de
# esperar a que cada una muerda. El nombre sale de las distribuciones REALMENTE instaladas
# en el venv con el que se congela, no de una lista escrita a mano que se desactualiza.
#
# Una que falle no puede tumbar el build: se saltea y se dice cuántas quedaron.
_METADATA = []
_vistas = set()
_sin_metadata = []
for _dist in _distributions():
    _nombre = (_dist.metadata or {}).get("Name")
    if not _nombre or _nombre in _vistas:
        continue
    _vistas.add(_nombre)
    try:
        _METADATA += copy_metadata(_nombre)
    except Exception as _e:            # noqa: BLE001 — una ficha ausente no rompe el pack
        _sin_metadata.append(_nombre)
print(f"spec: metadata de {len(_vistas) - len(_sin_metadata)}/{len(_vistas)} distribuciones"
      + (f" · sin ficha: {', '.join(sorted(_sin_metadata)[:6])}" if _sin_metadata else ""))
if "fastmcp" not in _vistas:
    # El caso que originó todo esto tiene que seguir cubierto aunque el barrido cambie.
    raise SystemExit("spec: el venv de Finanzas no tiene `fastmcp` — ver el bloque de arriba")

_HIDDEN = ["api_server", "mcp_server"]
for _package in ("cli", "src", "backtest"):
    _HIDDEN.extend(collect_submodules(_package))


a = Analysis(
    [os.path.join(REPO, "deploy", "fase4", "vibetrading_pack_serve.py")],
    pathex=[AGENT],
    binaries=[],
    datas=_DATA + _METADATA,
    hiddenimports=sorted(set(_HIDDEN)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vibe_trading_backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="vibe_trading_backend",
)
