"""
loop/session_browser.py — Capa 1 · Forma 3 (humano + sesión) · la PUERTA.

§2 Forma 3: el target exige un login que el motor NO puede (ni debe) automatizar —
hay 2FA, captcha, SSO, lo que sea. La puerta abre una ventana de navegador VISIBLE,
el HUMANO se loguea ÉL MISMO (incluido el segundo factor y el captcha), y el motor
solo CAPTURA la sesión que quedó: el storage_state de Playwright (cookies +
localStorage). El resultado es la MISMA `Session` uniforme que las otras 3 formas
(§2) → el loop de arriba no sabe de qué forma vino.

LÍNEA ROJA (§2 Trampa 1) — PERMANENTE, NO NEGOCIABLE:
El motor NUNCA resuelve 2FA ni captcha. Acá eso se hace ESTRUCTURAL, no por promesa:

  • el constructor NO acepta password, OTP, código, ni credencial de ninguna clase
    — no hay DÓNDE meter un secreto, así que el motor no puede "tipearlo";
  • la puerta solo NAVEGA al login y OBSERVA hasta que el humano llega al estado
    logueado (wait_for_url / wait_for_selector / un ENTER del humano). No completa
    formularios, no escribe códigos, no toca el captcha.

Si en algún punto el diseño asumiera "el motor pasa el 2FA", se viola este contrato.

Persistencia: el storage_state capturado se guarda CIFRADO (SessionStateStore ·
Fernet del org, vía crypto.py) — nunca en claro. En corridas siguientes se REUSA
sin volver a pedir login. El password del humano JAMÁS se ve ni se guarda: solo
queda la cookie/sesión resultante, cifrada.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional
from urllib.parse import urlparse

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.crypto import SessionStateStore  # noqa: E402
from inspection.loop.guard import PublicHTTPGuard  # noqa: E402

# almacén de storage_states cifrado, por defecto bajo el árbol durable de los belts.
_DEFAULT_STATE = C.SYNTH_BELTS_DIR / ".sessions" / "human_sessions.enc"

#: tipo del seam de navegador inyectable: dada una storage_state previa (o None),
#: devuelve (page, context, cleanup). Default = Playwright real; el test inyecta uno falso.
BrowserFactory = Callable[..., Awaitable[tuple[Any, Any, Callable[[], Awaitable[None]]]]]


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except (ValueError, TypeError):
        return ""


def _cookies_for_host(storage_state: Mapping[str, Any], host: str) -> dict[str, str]:
    """name->value de las cookies del storage_state cuyo dominio matchea el host del
    target (suffix-match). Filtra para no arrastrar cookies de terceros."""
    out: dict[str, str] = {}
    for ck in (storage_state.get("cookies") or []):
        name = ck.get("name")
        if not name:
            continue
        dom = (ck.get("domain") or "").lstrip(".").lower()
        if not host or not dom or host == dom or host.endswith("." + dom) or dom.endswith(host):
            out[name] = ck.get("value", "")
    return out


def _origins_count(storage_state: Mapping[str, Any]) -> int:
    return len(storage_state.get("origins") or [])


class HumanBrowserSession(C.SessionProvider):
    """Provider Forma 3 (humano + sesión). Abre una ventana, el HUMANO se loguea,
    el motor captura el storage_state resultante (cifrado, reusable).

    CONSTRUCTOR SIN SECRETOS — a propósito: la línea roja vive en la forma del tipo.
    No hay parámetro de password/OTP/captcha; el motor no tiene cómo tipear un
    segundo factor aunque quisiera. Lo único que recibe es CÓMO reconocer que el
    humano ya terminó (`ready_when` / `wait_human`).
    """

    form = C.AuthForm.HUMAN_SESSION

    def __init__(
        self,
        base_url: str,
        principal: C.Principal,
        slug: str,
        *,
        login_url: Optional[str] = None,
        ready_when: Optional[Mapping[str, str]] = None,   # {"url": substr} | {"selector": css}
        wait_human: bool = False,                          # el humano apreta ENTER al terminar
        headless: bool = False,                            # un login humano NECESITA ventana visible
        channel: Optional[str] = None,                     # p.ej. "chrome" (Chrome del sistema)
        login_timeout_ms: int = 180_000,
        storage_key: Optional[str] = None,                 # clave del storage_state cifrado
        state_path: str | Path = _DEFAULT_STATE,
        master_secret: Optional[str] = None,
        guard: Optional[C.SSRFGuard] = None,
        browser_factory: Optional[BrowserFactory] = None,  # seam: default Playwright; test=fake
    ):
        self.base_url = base_url.rstrip("/")
        self.login_url = login_url or self.base_url
        self.principal = principal
        self.slug = slug
        self.ready_when = dict(ready_when or {})
        self.wait_human = wait_human
        self.headless = headless
        self.channel = channel
        self.login_timeout_ms = login_timeout_ms
        # clave de reuso: por defecto, el host del target dentro del namespace del principal.
        self.storage_key = storage_key or f"{C.credential_namespace(principal)}::{slug}::{_host_of(self.base_url)}"
        self.state_path = Path(state_path)
        self._guard = guard or PublicHTTPGuard()
        self._store = SessionStateStore(self.state_path, master_secret=master_secret)
        self._factory: BrowserFactory = browser_factory or self._default_factory

    # ── storage_state cifrado (reuso entre corridas) ────────────────────────────
    def _load_state(self) -> Optional[dict]:
        return self._store.load(self.storage_key)

    def _save_state(self, state: dict) -> None:
        self._store.save(self.storage_key, state)

    @property
    def _requires_login(self) -> bool:
        """Solo hay algo que capturar si sabemos RECONOCER el fin del login humano."""
        return bool(self.ready_when) or self.wait_human

    # ── la puerta (sync) — conforma al ABC; envuelve el flujo async ─────────────
    def acquire(self) -> C.Session:
        try:
            return asyncio.run(self.acquire_async())
        except RuntimeError as e:
            if "event loop" in str(e).lower():
                raise C.SessionError(
                    "acquire() sync no se puede usar dentro de un event loop activo; "
                    "llama `await acquire_async()` desde código async."
                ) from e
            raise

    async def acquire_async(self, on_phase: Optional[Callable[[str, dict], None]] = None) -> C.Session:
        """Captura (o reusa) la sesión humana. `on_phase(phase, info)` es un hook OPCIONAL de
        PROGRESO (default None = no-op): el caller SSE lo usa para emitir cada fase REAL del
        flujo (guard → reuse | navegando → esperando-humano → capturando). CERO-TEATRO: cada
        llamada mapea 1:1 a un paso que de verdad ocurrió. No recibe ni emite secretos."""
        _phase = on_phase or (lambda *_a, **_k: None)

        # 1 · Capa 0 — el guard manda sobre base_url Y la URL de login. Fail-closed.
        for url in {self.base_url, self.login_url}:
            verdict = self._guard.check(url)
            if not verdict:
                raise C.SessionError(f"guard SSRF bloqueó {url}: {verdict.reason}")

        # 2 · ¿hay una sesión guardada (cifrada)? → reusá, NO molestes al humano.
        saved = self._load_state()
        if saved is not None:
            _phase("reusando", {"storage_key": self.storage_key})
            return self._session_from_state(saved, reused=True)

        # 3 · login humano requerido — necesitamos saber cómo reconocer el fin.
        if not self._requires_login:
            raise C.SessionError(
                "Forma 3 sin sesión guardada necesita una SEÑAL de fin de login "
                "(ready_when={'url':…}/{'selector':…} o wait_human=True): el humano "
                "decide cuándo terminó, el motor solo observa."
            )
        # un login humano necesita ventana VISIBLE — headless no deja que el humano actúe.
        if self.headless:
            raise C.SessionError(
                "un login humano necesita ventana visible (headless=False): el HUMANO se "
                "loguea él (incl. 2FA/captcha). Con headless=True nadie puede completar el login."
            )

        # 4 · abrir el navegador, dejar que el HUMANO se loguee, CAPTURAR lo que quedó.
        _phase("abriendo", {"login_url": self.login_url, "channel": self.channel})
        page, context, cleanup = await self._factory(
            storage_state=None, headless=self.headless, channel=self.channel
        )
        try:
            _phase("navegando", {"login_url": self.login_url})
            await page.goto(self.login_url, wait_until="domcontentloaded")  # navega; NO completa nada
            # el HUMANO se loguea (incl. 2FA/captcha); el motor SOLO observa hasta el fin.
            _phase("esperando_humano", {"timeout_ms": self.login_timeout_ms,
                                        "ready_when": dict(self.ready_when) or None})
            await self._await_human_login(page)                              # OBSERVA hasta el fin
            _phase("capturando", {})
            state = await context.storage_state()                            # captura la sesión humana
        finally:
            await cleanup()

        if not (state.get("cookies") or state.get("origins")):
            raise C.SessionError(
                "el navegador no dejó ninguna cookie/localStorage tras el login — no hay "
                "sesión que capturar (¿el login no se completó?)"
            )
        self._save_state(state)  # CIFRADO
        return self._session_from_state(state, reused=False)

    # ── construir la Session uniforme desde el storage_state capturado ──────────
    def _session_from_state(self, state: Mapping[str, Any], *, reused: bool) -> C.Session:
        host = _host_of(self.base_url)
        cookies = _cookies_for_host(state, host)
        if not cookies and not _origins_count(state):
            raise C.SessionError("storage_state vacío — sin cookies ni localStorage para el host")
        return C.Session(
            form=self.form,
            base_url=self.base_url,
            headers={},                       # Forma 3: la auth vive en cookies/storage, no en header
            cookies=cookies,
            storage_state=dict(state),        # el state crudo, para replay completo del loop
            meta={
                "auth_form": "human_session",
                "login_url": self.login_url,
                "reused_session": reused,
                "cookie_count": len(cookies),
                "origins_count": _origins_count(state),
                "storage_key": self.storage_key,
                "state_ref": f"{self.state_path.name}#{self.storage_key}",
                # marca AUDITABLE de la línea roja: lo logueó el humano, no el motor.
                "red_line": "engine_never_solves_2fa_or_captcha; human_authenticated",
            },
        )

    # ── detectar el FIN del login humano — SOLO observa, nunca actúa ────────────
    async def _await_human_login(self, page: Any) -> None:
        """Espera a que el HUMANO termine de loguearse. Tres señales, todas
        pasivas: el motor mira la URL/el DOM o espera un ENTER. NUNCA escribe en un
        campo, NUNCA tipea un código, NUNCA resuelve un captcha (línea roja)."""
        if "selector" in self.ready_when:
            await page.wait_for_selector(self.ready_when["selector"], timeout=self.login_timeout_ms)
            return
        if "url" in self.ready_when:
            sub = self.ready_when["url"]
            await page.wait_for_url(lambda u: sub in u, timeout=self.login_timeout_ms)
            return
        if self.wait_human:
            await self._wait_for_enter(
                "→ Inicia sesión tú en la ventana del navegador (incluido 2FA/captcha) y "
                "presiona ENTER aquí cuando ya estés adentro… "
            )
            return
        raise C.SessionError("sin señal de fin de login (ready_when/wait_human)")

    @staticmethod
    async def _wait_for_enter(prompt: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input, prompt)

    # ── seam por defecto: Playwright real (headed) — el ÚNICO que toca Chromium ──
    async def _default_factory(self, *, storage_state: Optional[dict], headless: bool,
                               channel: Optional[str]):
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=headless, channel=channel)
        context = await browser.new_context(storage_state=storage_state or None)
        page = await context.new_page()

        async def _cleanup() -> None:
            for step in (context.close, browser.close, pw.stop):
                try:
                    await step()
                except Exception:
                    pass

        return page, context, _cleanup


# ══════════════════════════════════════════════════════════════════════════════
# self-test · captura→Session→persist cifrado→reuse + línea roja ESTRUCTURAL
# ══════════════════════════════════════════════════════════════════════════════
def _selftest() -> int:
    """Ejercita la lógica REAL de la puerta sin un browser real (browser_factory
    falso que devuelve un storage_state canónico — como el que Playwright deja tras
    un login humano). Asierta: captura de cookies, persistencia CIFRADA, REUSO sin
    re-login, el guard SSRF, y la LÍNEA ROJA estructural (no hay campo de password/
    2FA en la puerta). El camino con browser real se prueba con `--live <login_url>`."""
    import inspect
    import tempfile
    import uuid

    fails: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        mark = "✓" if cond else "✗"
        print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
        if not cond:
            fails.append(name)

    SECRET = "humansession_" + uuid.uuid4().hex
    HOST = "example.com"
    BASE = f"https://{HOST}"
    # storage_state como el que Playwright deja tras un login humano (cookie + localStorage)
    CANNED_STATE = {
        "cookies": [
            {"name": "sid", "value": SECRET, "domain": HOST, "path": "/", "httpOnly": True},
            {"name": "tracker", "value": "x", "domain": "ads.thirdparty.com", "path": "/"},
        ],
        "origins": [
            {"origin": BASE, "localStorage": [{"name": "csrf", "value": "abc123"}]},
        ],
    }

    captures = {"factory_calls": 0}

    class _FakePage:
        def __init__(self, target_url: str):
            self._url = "about:blank"
            self._target = target_url
        async def goto(self, url, wait_until=None):
            self._url = url  # navegó al login — el motor NO completa nada acá
        async def wait_for_url(self, pred, timeout=None):
            # simula que el HUMANO se logueó y el navegador aterrizó en el dashboard
            self._url = self._target
            assert pred(self._url), "pred de ready_when no matcheó la URL post-login"
        async def wait_for_selector(self, selector, timeout=None):
            return object()

    class _FakeContext:
        def __init__(self, state):
            self._state = state
        async def storage_state(self):
            return self._state

    def make_factory(state, *, raise_if_called=False, target="https://example.com/dashboard"):
        async def factory(*, storage_state, headless, channel):
            captures["factory_calls"] += 1
            if raise_if_called:
                raise AssertionError("¡el factory NO debería abrir un browser en modo reuso!")
            async def cleanup():
                pass
            return _FakePage(target), _FakeContext(state), cleanup
        return factory

    state_path = Path(tempfile.mkdtemp(prefix="forma3-gate-")) / "sessions.enc"
    test_guard = PublicHTTPGuard(resolve=False)  # guard REAL en modo test (sin DNS); example.com pasa

    print("═" * 72)
    print("  GATE · FORMA 3 (humano + sesión) · captura/persist/reuse + línea roja")
    print("═" * 72)

    # ── 1 · captura: el humano se logueó → el motor captura el storage_state ────
    print("\n[1] captura de la sesión humana (factory falso ↔ login real)")
    p1 = C.Principal(anon_id=f"f3-cap-{uuid.uuid4().hex[:8]}")
    prov = HumanBrowserSession(
        BASE, p1, "f3", login_url=f"{BASE}/login",
        ready_when={"url": "/dashboard"}, headless=False,
        storage_key="gate-key", state_path=state_path, guard=test_guard,
        browser_factory=make_factory(CANNED_STATE),
    )
    sess = prov.acquire()
    check("Session.form == HUMAN_SESSION", sess.form is C.AuthForm.HUMAN_SESSION)
    check("capturó la cookie de sesión del host (sid)", sess.cookies.get("sid") == SECRET)
    check("filtró la cookie de tercero (ads.thirdparty.com NO entra)", "tracker" not in sess.cookies)
    check("storage_state crudo viaja en la Session (replay completo)",
          isinstance(sess.storage_state, dict) and bool(sess.storage_state.get("origins")))
    check("meta marca la línea roja (auditable)",
          "human_authenticated" in sess.meta.get("red_line", ""))
    check("meta dice reused_session=False (primera captura)", sess.meta.get("reused_session") is False)
    check("se llamó al browser factory una vez (hubo 'login')", captures["factory_calls"] == 1)

    # ── 2 · persistencia CIFRADA — el SECRET no aparece en claro en disco ───────
    print("\n[2] el storage_state se persiste CIFRADO (Fernet) — nada en claro")
    check("el archivo de sesiones existe", state_path.exists(), str(state_path))
    blob = state_path.read_bytes()
    check("la cookie de sesión NO aparece en claro en disco", SECRET.encode() not in blob,
          "cifrado" if SECRET.encode() not in blob else "FILTRADA EN CLARO")
    check("el localStorage tampoco aparece en claro", b"abc123" not in blob)

    # ── 3 · REUSO — segunda corrida NO abre browser, reusa la sesión cifrada ────
    print("\n[3] reuso: segunda corrida reusa la sesión cifrada (sin re-login)")
    p2 = C.Principal(anon_id=f"f3-reuse-{uuid.uuid4().hex[:8]}")
    prov2 = HumanBrowserSession(
        BASE, p2, "f3", login_url=f"{BASE}/login",
        ready_when={"url": "/dashboard"}, headless=False,
        storage_key="gate-key", state_path=state_path, guard=test_guard,
        browser_factory=make_factory(CANNED_STATE, raise_if_called=True),  # explota si abre browser
    )
    sess2 = prov2.acquire()
    check("reusó la cookie sin abrir browser", sess2.cookies.get("sid") == SECRET)
    check("meta dice reused_session=True", sess2.meta.get("reused_session") is True)

    # ── 4 · LÍNEA ROJA ESTRUCTURAL — no hay DÓNDE meter un 2do factor ───────────
    print("\n[4] LÍNEA ROJA estructural: la puerta no acepta password/OTP/captcha")
    params = set(inspect.signature(HumanBrowserSession.__init__).parameters)
    forbidden_params = {"password", "passwd", "pass", "secret", "otp", "totp", "mfa",
                        "twofa", "two_factor", "code", "otp_code", "credential", "credentials",
                        "captcha", "pin", "token", "api_key"}
    bad_params = params & forbidden_params
    check("el constructor NO tiene parámetro de secreto/2do-factor", not bad_params,
          "limpio" if not bad_params else f"PROHIBIDOS: {bad_params}")
    # ningún método sugiere TIPEAR un secreto / resolver un captcha
    methods = {m for m in dir(HumanBrowserSession) if not m.startswith("__")}
    bad_methods = {m for m in methods
                   if any(w in m.lower() for w in ("password", "captcha", "otp", "2fa", "mfa",
                                                   "solve", "fill_login", "enter_code"))}
    check("ningún método tipea credenciales ni resuelve captcha", not bad_methods,
          "limpio" if not bad_methods else f"SOSPECHOSOS: {bad_methods}")
    # _await_human_login solo usa APIs de OBSERVACIÓN de Playwright (no .fill/.type/.click)
    src = inspect.getsource(HumanBrowserSession._await_human_login)
    acts = [a for a in (".fill(", ".type(", ".press(", ".click(", ".set_input_files(") if a in src]
    check("_await_human_login no ACTÚA sobre la página (solo wait_for_*)", not acts,
          "solo observa" if not acts else f"ACCIONES halladas: {acts}")

    # ── 5 · guard SSRF manda — loopback se bloquea con el guard real ────────────
    print("\n[5] el guard SSRF corre primero (fail-closed)")
    p5 = C.Principal(anon_id=f"f3-ssrf-{uuid.uuid4().hex[:8]}")
    blocked = HumanBrowserSession(
        "https://127.0.0.1", p5, "f3-ssrf", login_url="https://127.0.0.1/login",
        ready_when={"url": "/x"}, state_path=state_path,
        guard=PublicHTTPGuard(),  # guard REAL, resuelve
        browser_factory=make_factory(CANNED_STATE, raise_if_called=True),
    )
    try:
        blocked.acquire()
        check("el guard real bloquea loopback", False, "no bloqueó")
    except C.SessionError as e:
        check("el guard real bloquea loopback (SSRF)", "guard" in str(e).lower())

    # ── 6 · sin señal de fin + sin sesión guardada → SessionError honesto ───────
    print("\n[6] sin señal de fin de login (y sin sesión guardada) → SessionError")
    p6 = C.Principal(anon_id=f"f3-nosig-{uuid.uuid4().hex[:8]}")
    nosig = HumanBrowserSession(
        "https://fresh-example.org", p6, "f3-nosig",
        state_path=Path(tempfile.mkdtemp(prefix="f3-nosig-")) / "s.enc",
        guard=test_guard, browser_factory=make_factory(CANNED_STATE, raise_if_called=True),
    )
    try:
        nosig.acquire()
        check("sin señal de fin levanta SessionError", False, "no levantó")
    except C.SessionError as e:
        check("sin señal de fin levanta SessionError", "señal" in str(e).lower() or "ready_when" in str(e))

    print("\n" + "═" * 72)
    if fails:
        print(f"  ROJO — {len(fails)} check(s) fallaron: {fails}")
        return 1
    print("  VERDE — Forma 3 (humano + sesión) verificada: captura, cifrado, reuso y LÍNEA ROJA")
    return 0


def _live(login_url: str, base_url: str, ready_url: str) -> int:
    """Camino REAL con Chromium headed: abrí esto, logueate vos (incl. 2FA/captcha),
    y mirá cómo el motor captura la sesión. NUNCA tipea tu password ni el código."""
    import uuid
    p = C.Principal(anon_id=f"f3-live-{uuid.uuid4().hex[:8]}")
    prov = HumanBrowserSession(
        base_url, p, "f3-live", login_url=login_url,
        ready_when={"url": ready_url} if ready_url else None,
        wait_human=not bool(ready_url), headless=False,
    )
    print(f"  Abriendo {login_url} — inicia sesión tú en la ventana…")
    sess = prov.acquire()
    print(f"  ✓ sesión capturada: {sess.meta.get('cookie_count')} cookies, "
          f"{sess.meta.get('origins_count')} origins · red_line={sess.meta.get('red_line')}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        # uso: session_browser.py --live <login_url> <base_url> [ready_url_substr]
        a = sys.argv[2:]
        raise SystemExit(_live(a[0], a[1] if len(a) > 1 else a[0], a[2] if len(a) > 2 else ""))
    raise SystemExit(_selftest())
