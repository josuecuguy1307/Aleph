"""
fixtures/demos/attendance.py — la demostración scripted de 'registrar asistencia'.

Una demo es `async def demo(page)`: ejecuta UNA vez la acción objetivo sobre la
página ya cargada. El recorder ya tiene la captura prendida; esta función sólo
reproduce lo que un humano haría (tipear + click). Mismo contrato que la versión
humana (apretá ENTER), pero reproducible para CI y para el deliverable.
"""
from __future__ import annotations


async def demo(page) -> None:
    await page.fill("#alumno", "persona usuaria Arcos")
    await page.fill("#codigo", "A-7731")
    await page.click("#enviar")
    await page.wait_for_timeout(800)   # deja salir el POST y su respuesta
