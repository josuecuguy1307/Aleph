#!/usr/bin/env python3
"""
selftest_live.py — DELIVERABLE de FASE 2: el recon, VISIBLE en el Cuarto.

Corre el motor contra el target benigno y emite su ciclo de vida a un space; en
paralelo abre el Cuarto (Pixi) en vivo (vía el :8091/:8080 ya corriendo) apuntado
a ese space con ?recon=, y SCREENSHOTEA cómo el software aparece → late mientras
analiza → se solidifica en un capability-block. End-to-end visible, verificado
contra el entorno real (no self-report): chequea events.jsonl + captura imágenes.

Requisitos: backend :8080 y frontend :8091 corriendo (no los reinicia).
Uso:  python platform/inspection/selftest_live.py
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
import time
from pathlib import Path

_PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DIR))

from inspection.bridge import SpaceEmitter, run_recon_to_space
from inspection.fixtures.demos.attendance import demo as attendance_demo
from inspection.fixtures.test_app import BenignTestApp

_SHOTS = _PLATFORM_DIR / "inspection" / ".state" / "recon-shots"
_FRONT = "http://127.0.0.1:8091"
_REQUIRED_EVENTS = {"software.detectado", "inspeccion.analizando", "accion.observada", "tool.sintetizada"}


def _port_up(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.5)
        return s.connect_ex((host, port)) == 0


async def _run() -> int:
    if not (_port_up("127.0.0.1", 8080) and _port_up("127.0.0.1", 8091)):
        print("[live] :8080/:8091 no están arriba — no puedo mostrar el Cuarto en vivo.")
        return 3
    _SHOTS.mkdir(parents=True, exist_ok=True)
    from playwright.async_api import async_playwright

    space_id = f"recon-demo-{int(time.time())}"
    SpaceEmitter(space_id, public=True, claim=True)
    url = f"{_FRONT}/cuarto/cuarto.pixi.html?recon={space_id}"
    print(f"[live] space={space_id}\n[live] Cuarto: {url}")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page(viewport={"width": 1180, "height": 760})
    shots: list[Path] = []

    async def shot(name: str, settle_ms: int = 800):
        await page.wait_for_timeout(settle_ms)
        p = _SHOTS / f"{name}.png"
        await page.screenshot(path=str(p))
        shots.append(p)
        print(f"[live]   shot → {p.name}")

    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1600)   # mount Pixi + conectar EventSource

        with BenignTestApp() as app:
            print(f"[live] target benigno {app.base_url}")
            # cada beat del recon → screenshot del Cuarto en ese estado
            async def on_beat(name: str):
                await shot(name)
            action, cap = await run_recon_to_space(
                space_id=space_id, target_url=app.base_url,
                intent="registrar asistencia", demo=attendance_demo,
                on_beat=on_beat, settle_ms=2200, pace_ms=1500,
            )
        await shot("final", settle_ms=2200)   # el capability-block ya solidificado
    finally:
        try: await browser.close()
        except Exception: pass
        try: await pw.stop()
        except Exception: pass

    # ── verify-before-trust contra el entorno real ──
    print("\n========== VERIFY (entorno real, no self-report) ==========")
    events_path = SpaceEmitter(space_id, public=True, claim=True).events_path
    types = []
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                types.append(json.loads(line).get("type"))
            except json.JSONDecodeError:
                pass
    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    present = set(types)
    for t in ["software.detectado", "inspeccion.analizando", "accion.observada", "tool.sintetizada"]:
        check(f"evento '{t}' en events.jsonl del space", t in present)
    check("orden correcto (detectado→analizando→observada→sintetizada)",
          [t for t in types if t in _REQUIRED_EVENTS] ==
          ["software.detectado", "inspeccion.analizando", "accion.observada", "tool.sintetizada"])
    check(f"capturé screenshots del Cuarto ({len(shots)})", len(shots) >= 4)
    check("la tool sintetizada salió como write→entrega", cap.get("category") == "write")

    print(f"\n[live] events.jsonl: {events_path}")
    print(f"[live] screenshots:  {_SHOTS}")
    print(f"[live] tipos emitidos: {types}")
    print(f"\n[live] {'OK ✅' if ok else 'FALLÓ ❌'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
