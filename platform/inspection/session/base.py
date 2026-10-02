"""
session/base.py — la ABC del substrate. PLAYWRIGHT-FREE a propósito.

EL CONTRATO: todo lo que está arriba de session/ (capture/, observe/, cli) habla
SÓLO con `AuthedContext` y `SessionProvider`. Nadie importa `session.cloud`
directo. El local-attach (Path B) será otro SessionProvider que devuelve el mismo
`AuthedContext` (una Page Playwright ya logueada, heredada del navegador vivo) y
el motor de captura/observación funciona idéntico encima.

`AuthedContext` expone lo único que las capas de arriba necesitan:
  - `.page` / `.context`  → la superficie Playwright para navegar y snapshot
  - `.on(event, cb)`      → el HOOK DE RED (page.on) para los listeners de captura
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


@dataclass
class AuthedContext:
    """Handle neutral al substrate. NO sabe si vino de cloud o de local-attach."""
    page: Any                                   # playwright.async_api.Page
    context: Any                                # playwright.async_api.BrowserContext
    provider: str                               # nombre del SessionProvider de origen
    reused_session: bool = False                # True si se reusó storage_state cifrado
    meta: dict = field(default_factory=dict)
    _cleanup: Optional[Callable[[], Awaitable[None]]] = None

    # ── HOOK DE RED — la superficie que la capa capture/ usa ──
    def on(self, event: str, cb: Callable) -> None:
        """page.on(...) passthrough: el único punto de enganche de red/eventos."""
        self.page.on(event, cb)

    def off(self, event: str, cb: Callable) -> None:
        try:
            self.page.remove_listener(event, cb)
        except Exception:
            pass

    async def aclose(self) -> None:
        if self._cleanup is not None:
            await self._cleanup()
            self._cleanup = None


class SessionProvider(ABC):
    """
    Provee un AuthedContext listo para inspeccionar. Una implementación por
    substrate: CloudSession (esta fase) y, después, LocalAttachSession (Path B).
    """
    name: str = "base"

    @abstractmethod
    async def provide_context(self) -> AuthedContext:
        """Devuelve un AuthedContext con una Page lista (logueada si aplica)."""
        raise NotImplementedError

    # azúcar de context-manager async
    async def __aenter__(self) -> AuthedContext:
        self._ctx = await self.provide_context()
        return self._ctx

    async def __aexit__(self, *exc) -> None:
        ctx = getattr(self, "_ctx", None)
        if ctx is not None:
            await ctx.aclose()
