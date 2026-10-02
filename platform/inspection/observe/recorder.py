"""
observe/recorder.py — record-and-generalize: corre UNA demostración con captura.

Engancha network + eventos ANTES de navegar, lleva la página al target, deja que
la acción ocurra (demostración scripted O humana), y devuelve el bundle crudo
(requests + eventos + DOM antes/después). Depende SÓLO de AuthedContext: el mismo
recorder corre sobre cloud o local-attach sin cambios.
"""
from __future__ import annotations

import asyncio
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from inspection.capture.dom import snapshot_dom
from inspection.capture.events import EventRecorder
from inspection.capture.network import NetworkRecorder
from inspection.models import CapturedRequest, DomSnapshot, ObservedEvent
from inspection.session.base import AuthedContext

# una demostración recibe la Page y ejecuta la acción objetivo
Demo = Callable[[object], Awaitable[None]]


@dataclass
class RecordingBundle:
    intent: str
    target_url: str
    started_at: float
    action_at: float
    requests: list[CapturedRequest] = field(default_factory=list)
    events: list[ObservedEvent] = field(default_factory=list)
    dom_pre: Optional[DomSnapshot] = None
    dom_post: Optional[DomSnapshot] = None


async def _settle(page, ms: int) -> None:
    """Espera a que la red se calme, pero ACOTADO (un poll que nunca para igual termina)."""
    try:
        await page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass
    try:
        await page.wait_for_timeout(min(ms, 600))
    except Exception:
        pass


async def _wait_for_enter(prompt: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, prompt)


async def _fire(on_event, phase: str, info: dict) -> None:
    """Llama on_event(phase, info), soportando callback sync o async."""
    if on_event is None:
        return
    try:
        res = on_event(phase, info)
        if asyncio.iscoroutine(res):
            await res
    except Exception:
        pass  # un observer no rompe la grabación


async def record_demonstration(
    ctx: AuthedContext,
    *,
    intent: str,
    target_url: str,
    demo: Optional[Demo] = None,
    settle_ms: int = 2000,
    with_a11y: bool = True,
    on_event: Optional[Callable[[str, dict], object]] = None,
) -> RecordingBundle:
    page = ctx.page

    net = NetworkRecorder()
    ev = EventRecorder()
    await ev.attach(ctx)        # binding + init-script ANTES de navegar
    net.attach(ctx)             # listeners de red

    t0 = time.time()
    await page.goto(target_url, wait_until="domcontentloaded")
    await _settle(page, settle_ms)         # deja que dispare el RUIDO de carga
    dom_pre = await snapshot_dom(page, with_a11y=with_a11y)

    # software.detectado — la pantalla cargó: sabemos host/título del software
    host = urllib.parse.urlsplit(dom_pre.url or target_url).netloc
    await _fire(on_event, "detectado", {
        "label": dom_pre.title or host, "host": host, "url": dom_pre.url, "title": dom_pre.title,
    })
    # inspeccion.analizando — arranca la observación (ya hay ruido de carga capturado)
    await _fire(on_event, "analizando", {"requests": len(net.dump())})

    action_at = time.time()
    if demo is not None:
        await demo(page)                   # demostración reproducible (scripted)
    else:
        await _wait_for_enter(
            f"→ Demuestra la acción '{intent}' en el navegador y presiona ENTER al terminar… "
        )

    await _settle(page, settle_ms)         # deja que termine la request de la ACCIÓN
    dom_post = await snapshot_dom(page, with_a11y=with_a11y)

    net.detach()
    return RecordingBundle(
        intent=intent,
        target_url=target_url,
        started_at=t0,
        action_at=action_at,
        requests=net.dump(),
        events=ev.events,
        dom_pre=dom_pre,
        dom_post=dom_post,
    )
