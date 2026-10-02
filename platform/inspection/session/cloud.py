"""
session/cloud.py — CloudSession: el ÚNICO módulo que sabe de Chromium + login.

Path A (cloud): lanza un Chromium propio. Si hay sesión guardada (storage_state
cifrado) la reusa y NO pide login. Si no, y el target requiere auth, abre el
navegador (headed) y deja que el HUMANO se loguee ÉL MISMO — Aleph nunca captura
ni guarda el password crudo; sólo persiste el storage_state resultante, cifrado
vía SessionStateStore (Fernet del org).

CONTRATO: este archivo importa Playwright y crypto; las capas de arriba NO lo
importan a él — sólo a session.base. Cambiar de substrate = cambiar este archivo.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

# bootstrap de path: permite `from inspection...` corriendo el archivo directo o como módulo
_PKG_PARENT = Path(__file__).resolve().parents[2]   # .../platform
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

from inspection.crypto import SessionStateStore
from inspection.session.base import AuthedContext, SessionProvider

_DEFAULT_STATE = Path(__file__).resolve().parents[1] / ".state" / "sessions.enc"


class CloudSession(SessionProvider):
    name = "cloud"

    def __init__(
        self,
        *,
        login_url: Optional[str] = None,
        ready_when: Optional[dict] = None,   # {"url": substr} | {"selector": css}
        wait_human: bool = False,            # login interactivo (apretá Enter)
        headless: bool = True,
        storage_key: Optional[str] = None,   # clave del storage_state cifrado (p.ej. host)
        state_path: str | Path = _DEFAULT_STATE,
        channel: Optional[str] = None,       # p.ej. "chrome" para Chrome del sistema
        login_timeout_ms: int = 180_000,
    ):
        self.login_url = login_url
        self.ready_when = ready_when or {}
        self.wait_human = wait_human
        self.headless = headless
        self.storage_key = storage_key
        self.state_path = Path(state_path)
        self.channel = channel
        self.login_timeout_ms = login_timeout_ms
        self._store = SessionStateStore(self.state_path) if storage_key else None

    # ── storage_state cifrado ──
    def _load_state(self) -> Optional[dict]:
        if self._store and self.storage_key:
            return self._store.load(self.storage_key)
        return None

    def _save_state(self, state: dict) -> None:
        if self._store and self.storage_key:
            self._store.save(self.storage_key, state)

    @property
    def _requires_login(self) -> bool:
        return bool(self.login_url) and (bool(self.ready_when) or self.wait_human)

    async def provide_context(self) -> AuthedContext:
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=self.headless, channel=self.channel)

        saved = self._load_state()
        context = await browser.new_context(storage_state=saved if saved else None)
        page = await context.new_page()
        reused = saved is not None

        async def _cleanup() -> None:
            for step in (context.close, browser.close, pw.stop):
                try:
                    await step()
                except Exception:
                    pass

        # Login SÓLO si el target lo requiere y no había sesión reusable.
        if not reused and self._requires_login:
            try:
                await page.goto(self.login_url, wait_until="domcontentloaded")
                await self._await_login_ready(page)
                state = await context.storage_state()
                self._save_state(state)   # cifrado
            except Exception:
                await _cleanup()
                raise

        return AuthedContext(
            page=page,
            context=context,
            provider=self.name,
            reused_session=reused,
            meta={"headless": self.headless, "storage_key": self.storage_key},
            _cleanup=_cleanup,
        )

    async def _await_login_ready(self, page) -> None:
        """Detecta que el HUMANO terminó de loguearse, sin tocar su password."""
        if "selector" in self.ready_when:
            await page.wait_for_selector(self.ready_when["selector"], timeout=self.login_timeout_ms)
            return
        if "url" in self.ready_when:
            await page.wait_for_url(
                lambda u: self.ready_when["url"] in u, timeout=self.login_timeout_ms
            )
            return
        if self.wait_human:
            await self._wait_for_enter(
                "→ Inicia sesión tú en la ventana del navegador y presiona ENTER aquí cuando estés listo… "
            )

    @staticmethod
    async def _wait_for_enter(prompt: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input, prompt)
