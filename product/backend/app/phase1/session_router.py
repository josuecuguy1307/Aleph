"""
session_router.py — LA CUARTA FORMA · captura de sesión por NAVEGADOR (OAuth + 2FA).
Rama 3-browser-oauth-entrada · reemplaza el 501 que 2f-formas dejó marcado.

§2 Forma 3 (humano + sesión): cuando el target exige OAuth/2FA — un login que el motor
NO puede ni debe automatizar — se abre un navegador INSTRUMENTADO donde el HUMANO se loguea
ÉL MISMO (incluido el segundo factor y el captcha). El sistema SOLO observa y, al terminar,
CAPTURA la sesión que quedó (cookies + localStorage = storage_state de Playwright). Esa sesión
es la MISMA `Session` uniforme que devuelven las otras 3 formas → el pipeline de arriba
(observar → sintetizar → validar → emitir) no sabe de qué forma vino.

    POST /v1/inspect/session/browser  {url, login_url?, ready_url?|ready_selector?, …}
      → browser.session.iniciado
      → browser.fase{abriendo}        (el navegador instrumentado se abre)
      → browser.fase{navegando}       (va al login; NO completa nada)
      → browser.fase{esperando_humano}(el HUMANO hace login + 2FA; el motor observa)
      → browser.fase{capturando}
      → sesion.capturada{session_key, cookie_count, origins_count, host, reused, red_line}
        / error{stage:"sesion", detail}   (cancelado / timeout / sin cookies → fallo HONESTO)

El `session_key` devuelto es la CAPABILITY que el caller le pasa luego a /v1/inspect/dispatch
(forma="browser-oauth", session_key=…): el Motor B REUSA esa sesión cifrada (no reabre el
navegador) y forja el MCP. El storage_state se persiste CIFRADO (Fernet del org, crypto.py);
el password del humano JAMÁS toca esto.

LÍNEA ROJA (§2, NO NEGOCIABLE): el segundo factor lo hace el HUMANO. Este router NO automatiza
2FA/captcha, NO acepta ni almacena credenciales del 2FA — sólo instrumenta el navegador y
captura la sesión resultante. La garantía es ESTRUCTURAL: `HumanBrowserSession` no tiene dónde
meter un secreto (ver platform/inspection/loop/session_browser.py).

CERO-TEATRO: `sesion.capturada` se emite SÓLO si el navegador dejó cookies/localStorage reales.
Si el humano cancela, el login expira, o no quedó nada → `error` honesto, sin sesión fantasma.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# El Motor B (Forma 3) vive en platform/inspection/ — asegurar que el backend lo importe.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLATFORM = _REPO_ROOT / "platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection.sse_util import _sse, _slug  # noqa: E402  [4.2.a] neutro (SHARED)


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except (ValueError, TypeError):
        return ""


def _new_session_key(host: str) -> str:
    """Capability NO adivinable: namespace + host + nonce. El que la tiene puede REUSAR la
    sesión cifrada en el forge — por eso lleva un uuid (no se deriva sólo del host)."""
    return f"browseroauth::{_slug(host) or 'target'}::{uuid.uuid4().hex}"


class BrowserSessionRequest(BaseModel):
    """El request de la captura. Núcleo: {url}. El humano se loguea en `login_url` y el motor
    reconoce el fin por `ready_url` (substring de la URL post-login) o `ready_selector` (CSS).
    NINGÚN campo acepta password/OTP/2FA — la línea roja vive en la forma del tipo."""
    url: str                                   # base REST del software (la que luego se forja)
    login_url: Optional[str] = None            # dónde se loguea el humano (default = url)
    ready_url: Optional[str] = None            # substring de la URL que marca "ya estoy adentro"
    ready_selector: Optional[str] = None       # o un selector CSS visible sólo logueado
    channel: Optional[str] = None              # p.ej. "chrome" (Chrome del sistema)
    login_timeout_ms: int = 180_000            # cuánto esperamos al humano (3 min default)
    session_key: Optional[str] = None          # reuso explícito; si falta se genera y se devuelve
    puppet_id: Optional[str] = None


# ── seam de verificación (env-gated, MISMO patrón que seed_probes/seed_candidates) ──────────
# El 2FA real lo hace un HUMANO en un navegador VISIBLE → no se puede automatizar (by design).
# Para el harness, PUPPET_BROWSER_SESSION_FIXTURE=<path|json> inyecta el storage_state que un
# login humano DEJARÍA (cookies + localStorage), saltándose la ventana — es el "punto de pausa
# donde interviene el humano", marcado explícito. En producto la env NO existe → SIEMPRE se abre
# el navegador real y el humano se loguea de verdad.
def _fixture_factory(host: str):
    """Si la env de fixture está, devuelve (browser_factory, source); si no, (None, "")."""
    raw = os.environ.get("PUPPET_BROWSER_SESSION_FIXTURE", "").strip()
    if not raw:
        return None, ""
    try:
        state = json.loads(raw) if raw.startswith("{") else json.loads(Path(raw).read_text())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail={
            "error": "fixture_invalida", "detail": f"PUPPET_BROWSER_SESSION_FIXTURE: {exc}"})

    class _FakePage:
        def __init__(self):
            self._url = "about:blank"
        async def goto(self, url, wait_until=None):
            self._url = url
        async def wait_for_url(self, pred, timeout=None):
            # simula que el HUMANO completó el login (incl. 2FA) y aterrizó adentro.
            self._url = f"https://{host}/dashboard"
            if not pred(self._url):
                self._url = f"https://{host}/?ok=1"
        async def wait_for_selector(self, selector, timeout=None):
            return object()

    class _FakeContext:
        async def storage_state(self):
            return state

    async def factory(*, storage_state, headless, channel):
        async def cleanup():
            pass
        return _FakePage(), _FakeContext(), cleanup

    return factory, ("inline" if raw.startswith("{") else raw)


def build_session_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["session"])

    @router.post("/inspect/session/browser")
    def capture_browser_session(
        body: BrowserSessionRequest, authorization: Optional[str] = Header(default=None)
    ):
        url = (body.url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail={"error": "url_requerida"})
        host = _host_of(url)

        # [borde · defense-in-depth] rate-limit + guard anti-SSRF. El provider REVALIDA en su
        # Capa 0 (fail-closed), pero el borde corta antes. (No puentea el guard del motor.)
        subject = (body.puppet_id or "anon")
        try:
            from safety import rate_limit, url_guard
            allowed, info = rate_limit.check_and_consume(subject, bucket="recon")
            if not allowed:
                raise HTTPException(status_code=429, detail={"error": "rate-limit de captura", **info})
            ok, reason = url_guard.is_safe(url)
            if not ok:
                raise HTTPException(status_code=400, detail={
                    "error": "target sin derecho a inspección", "reason": reason})
            login_u = (body.login_url or "").strip()
            if login_u:
                ok2, reason2 = url_guard.is_safe(login_u)
                if not ok2:
                    raise HTTPException(status_code=400, detail={
                        "error": "login_url sin derecho", "reason": reason2})
        except ImportError:
            pass  # capa de safety ausente: el guard del provider (Capa 0) sigue mandando.

        # señal de fin de login: ready_url o ready_selector. Sin ninguna, no hay forma de saber
        # cuándo el humano terminó → corte honesto (no abrimos un navegador que nunca cierra).
        if not (body.ready_url or body.ready_selector):
            raise HTTPException(status_code=400, detail={
                "error": "ready_signal_requerida",
                "detail": ("di cómo reconocer que el login terminó: `ready_url` (un trozo de la "
                           "URL a la que llegas ya autenticado) o `ready_selector` (un elemento que solo "
                           "se ve adentro). El HUMANO decide cuándo terminó; el motor solo observa.")})

        from inspection import contracts as C
        from inspection.loop.session_browser import HumanBrowserSession

        session_key = (body.session_key or "").strip() or _new_session_key(host)
        principal = C.Principal(anon_id=f"browseroauth-{body.puppet_id or 'anon'}-{uuid.uuid4().hex[:12]}")
        slug = f"browseroauth-{_slug(host)}"
        ready_when = {"url": body.ready_url} if body.ready_url else {"selector": body.ready_selector}

        try:
            factory, fixture_src = _fixture_factory(host)
        except HTTPException:
            raise

        provider = HumanBrowserSession(
            url, principal, slug,
            login_url=body.login_url or url,
            ready_when=ready_when,
            headless=False,                       # un login humano NECESITA ventana visible
            channel=body.channel,
            login_timeout_ms=body.login_timeout_ms,
            storage_key=session_key,              # capability estable → el forge la reusa
            browser_factory=factory,              # None = Playwright real (el humano se loguea)
        )

        async def stream():
            loop = asyncio.get_running_loop()
            q: asyncio.Queue = asyncio.Queue()

            def on_phase(phase: str, info: dict) -> None:
                # corre dentro de acquire_async (mismo loop) → push directo, sin secretos.
                q.put_nowait(("phase", {"type": "browser.fase", "fase": phase, **(info or {})}))

            async def runner():
                try:
                    sess = await provider.acquire_async(on_phase=on_phase)
                    q.put_nowait(("ok", sess))
                except Exception as exc:  # noqa: BLE001
                    q.put_nowait(("err", exc))

            yield _sse({"type": "browser.session.iniciado", "url": url, "host": host,
                        "forma": "browser-oauth", "session_key": session_key,
                        "fixture": bool(fixture_src),
                        "red_line": "engine_never_solves_2fa_or_captcha; human_authenticates"})
            task = asyncio.ensure_future(runner())
            try:
                while True:
                    kind, payload = await q.get()
                    if kind == "phase":
                        yield _sse(payload)
                    elif kind == "ok":
                        sess = payload
                        meta = dict(sess.meta or {})
                        yield _sse({
                            "type": "sesion.capturada", "ok": True,
                            "session_key": session_key, "host": host,
                            "form": getattr(sess.form, "value", str(sess.form)),
                            "auth_form": meta.get("auth_form"),
                            "cookie_count": meta.get("cookie_count"),
                            "origins_count": meta.get("origins_count"),
                            "reused": bool(meta.get("reused_session")),
                            "state_ref": meta.get("state_ref"),
                            "red_line": meta.get("red_line"),
                        })
                        break
                    elif kind == "err":
                        exc = payload
                        yield _sse({"type": "error", "stage": "sesion", "ok": False,
                                    "detail": f"{type(exc).__name__}: {exc}"})
                        break
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router
