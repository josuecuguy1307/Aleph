#!/usr/bin/env python3
"""
demo_live.py — corre un recon EN VIVO emitido a un space, SIN viewer headless.

A diferencia de selftest_live (que abre su propio Chromium y screenshotea), este
emite los eventos al space y NADA más: VOS abrís el Cuarto en tu browser
(/cuarto/cuarto.pixi.html?recon=<space>) y lo ves animarse en vivo. Da un head-start
(pre_sleep) para que alcances a abrir el link antes del primer beat.

Uso:  python platform/inspection/demo_live.py [space_id] [pre_sleep_s]
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[1]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection.bridge import SpaceEmitter, run_recon_to_space
from inspection.fixtures.demos.attendance import demo as attendance_demo
from inspection.fixtures.test_app import BenignTestApp


async def _run(space_id: str, pre_sleep: int) -> int:
    SpaceEmitter(space_id, public=True, claim=True)
    url = f"http://127.0.0.1:8091/cuarto/cuarto.pixi.html?recon={space_id}"
    print(f"[demo] space = {space_id}", flush=True)
    print(f"[demo] ABRÍ EN EL BROWSER:  {url}", flush=True)
    if pre_sleep > 0:
        print(f"[demo] arranco el recon en {pre_sleep}s — abrí el link ya…", flush=True)
        await asyncio.sleep(pre_sleep)
    with BenignTestApp() as app:
        print(f"[demo] inspeccionando target benigno {app.base_url} …", flush=True)
        await run_recon_to_space(
            space_id=space_id, target_url=app.base_url,
            intent="registrar asistencia", demo=attendance_demo,
            settle_ms=2200, pace_ms=2600,
            allow_local_fixture=True,   # [T9-safety] target benigno local (loopback) confiable
        )
    print("[demo] listo — el capability-block quedó en la escena (persistido para replay).", flush=True)
    return 0


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else f"recon-live-{int(time.time())}"
    pre = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    raise SystemExit(asyncio.run(_run(sid, pre)))
