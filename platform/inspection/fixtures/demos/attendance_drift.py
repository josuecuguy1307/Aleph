"""
fixtures/demos/attendance_drift.py — la MISMA intención sobre el software CAMBIADO.

El usuario hace lo de siempre (registrar asistencia), pero el software derivó: el campo
`codigo` ahora es `matricula`. Re-inspeccionar con esta demo contra BenignTestApp(drift=True)
produce una firma distinta a la congelada → el health-check detecta drift.
"""
from __future__ import annotations


async def demo(page) -> None:
    await page.fill("#alumno", "persona usuaria Arcos")
    await page.fill("#matricula", "2026-1307")
    await page.click("#enviar")
    await page.wait_for_timeout(800)
