#!/usr/bin/env python3
"""Corredor de `verify_espacios_sin_carrera.mjs` — `correr_varas.py:140` sólo recolecta
`verify_*.py`, y una vara que el pool no ve es una vara que se abandona."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
raise SystemExit(subprocess.run(["node", str(Path(__file__).with_suffix(".mjs")), *sys.argv[1:]], text=True).returncode)
