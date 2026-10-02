#!/usr/bin/env python3
"""Corredor de `verify_riel.mjs` — el pool sólo recolecta `verify_*.py`."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
raise SystemExit(subprocess.run(["node", str(Path(__file__).with_suffix(".mjs")), *sys.argv[1:]], text=True).returncode)
