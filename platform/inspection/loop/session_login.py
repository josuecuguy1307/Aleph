"""
loop/session_login.py — Capa 1 · Forma 2 (login DEFINIDO POR LA API) · la PUERTA.

§2 Forma 2: la API define cómo se loguea. El motor POSTea las credenciales al
endpoint de login que la API expone, la API devuelve una sesión (un token en el
cuerpo, un header, o una cookie), y el motor la EXTRAE y la inyecta en las
requests siguientes. El resultado es la MISMA `Session` uniforme que devuelven las
otras 3 formas (§2) → el loop de arriba no sabe de qué forma vino.

Cuatro cosas pasan en `acquire()`, en orden, y ninguna es teatro:

  1. Capa 0 PRIMERO: el guard SSRF aprueba el base_url Y la URL de login, o no se
     toca nada. Fail-closed.
  2. CIFRA las credenciales: cada valor de login (incluido el password) se persiste
     vía Fernet (FernetCredentialStore, contracts.py) en la carpeta aislada
     por-principal. El plaintext NUNCA toca disco (cierra CASO D).
  3. LOGIN VIVO: un POST real al endpoint de login. 2xx ⇒ se extrae la sesión;
     401/403 ⇒ SessionError (la puerta no miente). El token obtenido se CIFRA también
     (es la credencial de llamada que el emisor reusa, igual que la api_key de Forma 1).
  4. VALIDA la sesión VIVA: una request real con la auth ya inyectada al
     `validate_path` — 2xx ⇒ la sesión vale.

LÍNEA ROJA (§2 Trampa 1): el motor NUNCA resuelve 2FA ni captcha. Si el login
responde un DESAFÍO MFA (202 / `mfa_required` / `two_factor` / pide un código), esta
puerta NO lo resuelve — levanta SessionError apuntando a la Forma 3 (el humano se
loguea él en una ventana). Una Forma 2 que "pase el segundo factor" violaría el
contrato del SessionProvider.

El secreto (el token de sesión) NO viaja en claro en los logs: la `Session` lo lleva
inyectado en `headers`/`cookies` (loggeables redactados) y en disco solo vive Fernet.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.guard import PublicHTTPGuard  # noqa: E402

#: nombre del token de sesión (la credencial de LLAMADA) dentro del vault por-principal
SESSION_CRED_NAME = "SESSION_TOKEN"
#: prefijo de cada credencial de login (la durable, para re-loguear) en el vault
LOGIN_CRED_PREFIX = "LOGIN_"
_REDACT = "***"

# síntomas de un DESAFÍO MFA — la API pide un segundo factor. La Forma 2 NO lo resuelve.
_MFA_BODY_KEYS = {
    "mfa", "mfa_required", "mfa_token", "two_factor", "two_factor_required",
    "2fa", "2fa_required", "otp", "otp_required", "challenge", "totp_required",
    "requires_2fa", "needs_mfa", "verification_required",
}
_MFA_TEXT_HINTS = (
    "two-factor", "two factor", "2fa", "verification code", "authenticator app",
    "one-time code", "one time passcode", "código de verificación",
)


# ══════════════════════════════════════════════════════════════════════════════
# Especificación declarativa: de DÓNDE sale la sesión y CÓMO se inyecta después
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class TokenSource:
    """De DÓNDE sale el token que el login devolvió.

      • where="json"   → `key` es un path con puntos en el cuerpo JSON
                          (p.ej. "access_token", "data.token").
      • where="header" → `key` es el nombre del header de respuesta
                          (p.ej. "Authorization", "X-Auth-Token").
      • where="cookie" → `key` es el nombre de la cookie que el login dejó
                          (Set-Cookie; p.ej. "session", "sid").
    """
    where: str = "json"
    key: str = "access_token"


@dataclass(frozen=True)
class AuthInjection:
    """CÓMO se inyecta la sesión obtenida en cada request siguiente.

      • where="header" → `name`=header, `template` arma el valor ("Bearer {token}").
      • where="cookie" → `name`=cookie; el valor es el token tal cual.
      • where="query"  → `name`=param; cae al carril de Forma 1 (token en query),
                          se expone vía .secret/.auth_param (la Session no lleva query).
    """
    where: str = "header"
    name: str = "Authorization"
    template: str = "Bearer {token}"

    def render(self, token: str) -> str:
        return self.template.format(token=token) if "{token}" in self.template else token


# ══════════════════════════════════════════════════════════════════════════════
# Transporte HTTP (POST + GET) — autocontenido (stdlib), inyectable para test
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class HttpResp:
    """Respuesta cruda de una request viva. `status=0` ⇒ transporte caído/timeout."""
    status: int
    headers: Mapping[str, str]          # nombres en minúscula
    cookies: Mapping[str, str]          # parseadas de Set-Cookie
    json: Optional[Any]
    text: str
    reason: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@runtime_checkable
class Transport(Protocol):
    """La superficie de red mínima de la Forma 2. La implementación real usa
    urllib; el test inyecta una falsa contra un server local."""

    def post(self, url: str, *, body: Mapping[str, Any], headers: Mapping[str, str],
             body_format: str) -> HttpResp: ...

    def get(self, url: str, *, headers: Mapping[str, str]) -> HttpResp: ...


def _parse_cookies(set_cookie_values: list[str]) -> dict[str, str]:
    """name->value de una lista de headers Set-Cookie (ignora atributos)."""
    out: dict[str, str] = {}
    for raw in set_cookie_values:
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            continue
        for name, morsel in jar.items():
            out[name] = morsel.value
    return out


class UrllibTransport:
    """POST/GET vivos con stdlib. Honesto: transporte caído ⇒ status=0 + reason
    (no una excepción que el caller tenga que adivinar)."""

    def __init__(self, *, timeout: float = 15.0, max_text: int = 20_000,
                 user_agent: str = "puppet-inspection-loop/1.0"):
        self._timeout = timeout
        self._max_text = max_text
        self._ua = user_agent

    def _do(self, req: urllib.request.Request, t0: float) -> HttpResp:
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                status = resp.getcode() or 0
                hdrs = resp.headers
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
            status = e.code
            hdrs = e.headers
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return HttpResp(status=0, headers={}, cookies={}, json=None, text="",
                            reason=str(getattr(e, "reason", e)))
        headers = {k.lower(): v for k, v in (hdrs.items() if hdrs else [])}
        set_cookie = hdrs.get_all("Set-Cookie") if hdrs else None
        cookies = _parse_cookies(set_cookie or [])
        text = raw[: self._max_text]
        try:
            parsed = json.loads(raw) if raw else None
        except (json.JSONDecodeError, ValueError):
            parsed = None
        return HttpResp(status=status, headers=headers, cookies=cookies, json=parsed, text=text)

    def post(self, url: str, *, body: Mapping[str, Any], headers: Mapping[str, str],
             body_format: str) -> HttpResp:
        if body_format == "form":
            data = urllib.parse.urlencode(body).encode("utf-8")
            ctype = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode("utf-8")
            ctype = "application/json"
        h = {"User-Agent": self._ua, "Accept": "application/json",
             "Content-Type": ctype, **dict(headers)}
        req = urllib.request.Request(url, data=data, headers=h, method="POST")
        return self._do(req, time.monotonic())

    def get(self, url: str, *, headers: Mapping[str, str]) -> HttpResp:
        h = {"User-Agent": self._ua, "Accept": "application/json", **dict(headers)}
        req = urllib.request.Request(url, headers=h, method="GET")
        return self._do(req, time.monotonic())


# ══════════════════════════════════════════════════════════════════════════════
# helpers de extracción / redacción
# ══════════════════════════════════════════════════════════════════════════════
def _dig(obj: Any, dotted: str) -> Optional[Any]:
    """Camina un path con puntos en un dict anidado. None si falta algún tramo."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _fingerprint(secret: str) -> str:
    """Huella NO reversible del token, para loggear sin filtrarlo."""
    import hashlib
    if not secret:
        return "∅"
    last4 = secret[-4:] if len(secret) >= 4 else "****"
    h = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]
    return f"sha256:{h}…{last4}"


def _looks_like_mfa(resp: HttpResp) -> bool:
    """¿El login está pidiendo un SEGUNDO FACTOR? La Forma 2 no lo resuelve."""
    if resp.status == 202:  # convención común: 'aceptado, falta el 2do factor'
        return True
    if isinstance(resp.json, Mapping):
        for k, v in resp.json.items():
            if k.lower() in _MFA_BODY_KEYS and v:
                return True
    low = (resp.text or "").lower()
    return any(h in low for h in _MFA_TEXT_HINTS)


# ══════════════════════════════════════════════════════════════════════════════
# CAPA 1 · Forma 2 · LoginAPISession
# ══════════════════════════════════════════════════════════════════════════════
class LoginAPISession(C.SessionProvider):
    """Provider Forma 2 (login definido por la API). POSTea credenciales al login
    endpoint, extrae la sesión que la API devuelve y la inyecta en una `Session`
    uniforme. No es específico de ningún SaaS: `login_path`, `credentials`,
    `token_source` e `inject_as` describen el contrato de login de CUALQUIER API.

    LÍNEA ROJA: ante un desafío MFA/2FA, levanta SessionError (→ Forma 3). NUNCA
    resuelve el segundo factor.
    """

    form = C.AuthForm.LOGIN_API

    def __init__(
        self,
        base_url: str,
        login_path: str,
        credentials: Mapping[str, str],
        principal: C.Principal,
        slug: str,
        *,
        secret_fields: tuple[str, ...] = ("password", "pass", "secret", "client_secret", "api_secret"),
        token_source: TokenSource = TokenSource(),
        inject_as: AuthInjection = AuthInjection(),
        body_format: str = "json",                  # "json" | "form"
        validate_path: Optional[str] = None,        # GET con auth inyectada → 2xx confirma
        guard: Optional[C.SSRFGuard] = None,
        transport: Optional[Transport] = None,
        master_secret: Optional[str] = None,
        cred_root: Path = C.SYNTH_BELTS_DIR,
        timeout: float = 15.0,
    ):
        if not credentials:
            raise ValueError("Forma 2 necesita credenciales para POSTear al login.")
        self.base_url = base_url.rstrip("/")
        self.login_path = login_path if login_path.startswith("/") else "/" + login_path
        self._credentials = dict(credentials)
        self.principal = principal
        self.slug = slug
        self._secret_fields = {f.lower() for f in secret_fields}
        self.token_source = token_source
        self.inject_as = inject_as
        self.body_format = body_format
        self.validate_path = validate_path
        self._guard = guard or PublicHTTPGuard()
        self._transport = transport or UrllibTransport(timeout=timeout)
        # vault por-principal (Fernet) — aislado, no colisiona entre anónimos.
        self._store = C.FernetCredentialStore(
            principal, slug, master_secret=master_secret, root=cred_root
        )
        self._token: str = ""

    # ── superficie pública (espeja Forma 1: .secret + .store) ──────────────────
    @property
    def secret(self) -> str:
        """El token de sesión en claro, SOLO en memoria, para el http del loop."""
        return self._token

    @property
    def store(self) -> C.CredentialStore:
        return self._store

    @property
    def login_url(self) -> str:
        return self.base_url + self.login_path

    # ── la puerta ──────────────────────────────────────────────────────────────
    def acquire(self) -> C.Session:
        # 1 · Capa 0 — el guard manda sobre base_url Y la URL de login. Fail-closed.
        for url in (self.base_url, self.login_url):
            verdict = self._guard.check(url)
            if not verdict:
                raise C.SessionError(f"guard SSRF bloqueó {url}: {verdict.reason}")

        # 2 · cifrar las credenciales de login (Fernet) — el plaintext no toca disco.
        for name, value in self._credentials.items():
            self._store.put(f"{LOGIN_CRED_PREFIX}{name.upper()}", str(value))

        # 3 · LOGIN VIVO — POST real al endpoint que la API define.
        resp = self._transport.post(
            self.login_url, body=self._credentials, headers={}, body_format=self.body_format
        )
        if resp.status == 0:
            raise C.SessionError(f"target inalcanzable en login: {resp.reason}")
        # LÍNEA ROJA: ¿desafío MFA? → Forma 3. El motor NO resuelve el 2do factor.
        if _looks_like_mfa(resp):
            raise C.SessionError(
                "el login pide un SEGUNDO FACTOR (2FA/MFA/OTP) — la Forma 2 (login API) NO "
                "resuelve el segundo factor (línea roja §2 Trampa 1). Usa la Forma 3: el HUMANO "
                "se loguea él en una ventana y el motor captura la sesión resultante."
            )
        if resp.status in (401, 403):
            raise C.SessionError(
                f"credenciales inválidas ({resp.status}) en {self.login_path} — la puerta no miente"
            )
        if not resp.ok:
            raise C.SessionError(
                f"login devolvió {resp.status} (no 2xx) en {self.login_path}: {resp.text[:160]}"
            )

        # 4 · extraer la sesión que la API devolvió (cuerpo/header/cookie).
        token = self._extract_token(resp)
        if not token:
            raise C.SessionError(
                f"el login respondió 2xx pero NO trajo la sesión esperada "
                f"({self.token_source.where}:{self.token_source.key}) — sin token no hay sesión "
                f"(la puerta no inventa una)"
            )
        self._token = token
        # el token es la credencial de LLAMADA (lo que el emisor reusa) → cifrarlo también.
        self._store.put(SESSION_CRED_NAME, token)

        # 5 · armar la auth inyectada y VALIDAR viva.
        headers, cookies, auth_param = self._inject(token)
        validate_status: Optional[int] = None
        if self.validate_path:
            vurl = self.base_url + (self.validate_path if self.validate_path.startswith("/")
                                    else "/" + self.validate_path)
            if auth_param:
                sep = "&" if "?" in vurl else "?"
                vurl = vurl + sep + urllib.parse.urlencode({auth_param: token})
            # la validación debe EJERCER la auth de verdad: si va por cookie, serializala
            # al header Cookie (la Session la lleva en .cookies, pero la request la manda acá).
            vheaders = dict(headers)
            if cookies:
                vheaders["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
            vres = self._transport.get(vurl, headers=vheaders)
            validate_status = vres.status
            if vres.status in (401, 403):
                raise C.SessionError(
                    f"la sesión obtenida no validó ({vres.status}) contra {self.validate_path} — "
                    f"el token no abre la puerta"
                )
            if vres.status == 0:
                raise C.SessionError(f"target inalcanzable al validar: {vres.reason}")

        return C.Session(
            form=self.form,
            base_url=self.base_url,
            headers=headers,
            cookies=cookies,
            meta={
                "auth_form": "login_api",
                "login_path": self.login_path,
                "token_source": f"{self.token_source.where}:{self.token_source.key}",
                "inject_as": f"{self.inject_as.where}:{self.inject_as.name}",
                "token_fingerprint": _fingerprint(token),          # redactado
                "login_status": resp.status,
                "validated_by": self.validate_path or "(login 2xx)",
                "validate_status": validate_status,
                "cred_ref": f"{C.credential_namespace(self.principal)}/{self.slug}#{SESSION_CRED_NAME}",
            },
        )

    # ── internos ───────────────────────────────────────────────────────────────
    def _extract_token(self, resp: HttpResp) -> str:
        ts = self.token_source
        if ts.where == "json":
            val = _dig(resp.json, ts.key) if resp.json is not None else None
            return str(val) if val not in (None, "") else ""
        if ts.where == "header":
            raw = resp.headers.get(ts.key.lower(), "")
            # un 'Authorization: Bearer xxx' devuelto → quedate con el token pelado
            if raw.lower().startswith("bearer "):
                raw = raw[7:]
            return raw.strip()
        if ts.where == "cookie":
            return resp.cookies.get(ts.key, "")
        return ""

    def _inject(self, token: str) -> tuple[dict[str, str], dict[str, str], str]:
        """Devuelve (headers, cookies, auth_param) según `inject_as`. Solo uno se
        llena; los otros quedan vacíos."""
        inj = self.inject_as
        if inj.where == "header":
            return {inj.name: inj.render(token)}, {}, ""
        if inj.where == "cookie":
            return {}, {inj.name: token}, ""
        if inj.where == "query":
            # carril Forma 1: el token va en query; la Session no lo lleva, .secret sí.
            return {}, {}, inj.name
        raise ValueError(f"inject_as.where desconocido: {inj.where!r}")


# ══════════════════════════════════════════════════════════════════════════════
# self-test · REAL, no teatro — login server LOCAL vivo (http.server) + urllib real
# ══════════════════════════════════════════════════════════════════════════════
def _selftest() -> int:
    """Levanta un login server REAL en loopback y corre la puerta completa contra él:
    POST de login real, token real extraído de 3 fuentes (json/header/cookie),
    validación viva con la auth inyectada, credenciales cifradas en disco, redacción,
    y el RECHAZO de un desafío MFA (línea roja). Cero mocks de la lógica de la puerta."""
    import http.server
    import socketserver
    import tempfile
    import threading
    import uuid

    fails: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        mark = "✓" if cond else "✗"
        print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
        if not cond:
            fails.append(name)

    TOKEN = "tok_" + uuid.uuid4().hex
    GOOD = {"username": "demo-user", "password": "s3cr3t-pass"}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencio
            pass

        def _send(self, code, body=None, headers=None):
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body or {}).encode())

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n).decode()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = dict(urllib.parse.parse_qsl(raw))
            if self.path == "/login":
                if payload.get("username") == GOOD["username"] and payload.get("password") == GOOD["password"]:
                    # devuelve la sesión por las 3 vías a la vez: json + header + cookie
                    self._send(200, {"access_token": TOKEN, "token_type": "bearer"},
                               headers={"X-Auth-Token": TOKEN,
                                        "Set-Cookie": f"sid={TOKEN}; Path=/; HttpOnly"})
                else:
                    self._send(401, {"error": "bad credentials"})
            elif self.path == "/login-mfa":
                self._send(200, {"mfa_required": True, "challenge": "totp"})
            else:
                self._send(404, {"error": "no such endpoint"})

        def do_GET(self):
            # protegido: exige el token por header Authorization, cookie sid, o ?token=
            auth = self.headers.get("Authorization", "")
            cookie = self.headers.get("Cookie", "")
            q = urllib.parse.urlparse(self.path)
            qs = dict(urllib.parse.parse_qsl(q.query))
            ok = (auth == f"Bearer {TOKEN}") or (f"sid={TOKEN}" in cookie) or (qs.get("token") == TOKEN)
            if q.path == "/me":
                self._send(200 if ok else 401,
                           {"user": "demo-user"} if ok else {"error": "unauthorized"})
            else:
                self._send(404, {})

    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    srv.allow_reuse_address = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    # guard de TEST: permite loopback http (opt-in explícito; la puerta sigue corriendo el guard).
    test_guard = PublicHTTPGuard(resolve=False, allow_http=True)

    class _LoopbackGuard(C.SSRFGuard):
        def check(self, url: str) -> C.GuardVerdict:
            return C.GuardVerdict(True, "loopback test")

    guard = _LoopbackGuard()
    root = Path(tempfile.mkdtemp(prefix="forma2-gate-"))

    print("═" * 72)
    print(f"  GATE · FORMA 2 (login API) · login server REAL en {base}")
    print("═" * 72)

    try:
        # ── 1 · token desde JSON + inyección en header Authorization ────────────
        print("\n[1] login real → token de JSON → header Bearer → /me 200")
        p1 = C.Principal(anon_id=f"f2-json-{uuid.uuid4().hex[:8]}")
        s1 = LoginAPISession(
            base, "/login", GOOD, p1, "f2-json",
            token_source=TokenSource("json", "access_token"),
            inject_as=AuthInjection("header", "Authorization", "Bearer {token}"),
            validate_path="/me", guard=guard, cred_root=root,
        )
        sess1 = s1.acquire()
        check("Session.form == LOGIN_API", sess1.form is C.AuthForm.LOGIN_API)
        check("auth inyectada en header Authorization", sess1.headers.get("Authorization") == f"Bearer {TOKEN}")
        check("validate_status == 200 (sesión viva)", sess1.meta.get("validate_status") == 200)
        check("token NO en claro en la meta (solo fingerprint)",
              TOKEN not in json.dumps(dict(sess1.meta)) and sess1.meta.get("token_fingerprint", "").startswith("sha256:"))
        check(".secret expone el token en memoria", s1.secret == TOKEN)

        # ── 2 · token desde header de respuesta ─────────────────────────────────
        print("\n[2] token desde header de respuesta (X-Auth-Token)")
        p2 = C.Principal(anon_id=f"f2-hdr-{uuid.uuid4().hex[:8]}")
        s2 = LoginAPISession(
            base, "/login", GOOD, p2, "f2-hdr",
            token_source=TokenSource("header", "X-Auth-Token"),
            inject_as=AuthInjection("header", "Authorization", "Bearer {token}"),
            validate_path="/me", guard=guard, cred_root=root,
        )
        sess2 = s2.acquire()
        check("token extraído del header de respuesta", s2.secret == TOKEN)
        check("validó vivo (200)", sess2.meta.get("validate_status") == 200)

        # ── 3 · token desde cookie + inyección como cookie ──────────────────────
        print("\n[3] token desde Set-Cookie → inyección como cookie 'sid'")
        p3 = C.Principal(anon_id=f"f2-ck-{uuid.uuid4().hex[:8]}")
        s3 = LoginAPISession(
            base, "/login", GOOD, p3, "f2-ck",
            token_source=TokenSource("cookie", "sid"),
            inject_as=AuthInjection("cookie", "sid"),
            validate_path="/me", guard=guard, cred_root=root,
        )
        sess3 = s3.acquire()
        check("token extraído de la cookie del login", s3.secret == TOKEN)
        check("auth inyectada como cookie sid", sess3.cookies.get("sid") == TOKEN)
        check("validó vivo con la cookie (200)", sess3.meta.get("validate_status") == 200)

        # ── 4 · credenciales CIFRADAS en disco (Fernet) — nada en claro ─────────
        print("\n[4] credenciales cifradas en disco (Fernet) — password jamás en claro")
        cred_file = C.credential_dir(p1, "f2-json", root=root) / "credentials.enc"
        check("credentials.enc existe", cred_file.exists(), str(cred_file))
        leaked = []
        for pth in root.rglob("*"):
            if pth.is_file() and pth.name != "credentials.enc":
                blob = pth.read_bytes()
                if GOOD["password"].encode() in blob or TOKEN.encode() in blob:
                    leaked.append(str(pth.relative_to(root)))
        # y el propio .enc no contiene el plaintext del password
        enc_has_plaintext = GOOD["password"].encode() in cred_file.read_bytes()
        check("password NUNCA en claro en disco", not leaked and not enc_has_plaintext,
              "limpio" if not leaked and not enc_has_plaintext else f"FILTRADO en {leaked or 'credentials.enc'}")
        check("el token de sesión se guardó cifrado (SESSION_TOKEN)", s1.store.has(SESSION_CRED_NAME))
        check("se descifra y coincide", s1.store.get(SESSION_CRED_NAME) == TOKEN)

        # ── 5 · credenciales malas → SessionError (la puerta no miente) ─────────
        print("\n[5] credenciales inválidas → SessionError 401")
        p5 = C.Principal(anon_id=f"f2-bad-{uuid.uuid4().hex[:8]}")
        bad = LoginAPISession(base, "/login", {"username": "x", "password": "nope"}, p5, "f2-bad",
                              guard=guard, cred_root=root)
        try:
            bad.acquire()
            check("login malo levanta SessionError", False, "no levantó")
        except C.SessionError as e:
            check("login malo levanta SessionError", "401" in str(e) or "inválid" in str(e).lower())

        # ── 6 · LÍNEA ROJA · desafío MFA → SessionError → Forma 3 ───────────────
        print("\n[6] LÍNEA ROJA · el login pide 2FA → la Forma 2 NO lo resuelve")
        p6 = C.Principal(anon_id=f"f2-mfa-{uuid.uuid4().hex[:8]}")
        mfa = LoginAPISession(base, "/login-mfa", GOOD, p6, "f2-mfa", guard=guard, cred_root=root)
        try:
            mfa.acquire()
            check("desafío MFA levanta SessionError", False, "no levantó — VIOLARÍA la línea roja")
        except C.SessionError as e:
            msg = str(e).lower()
            check("desafío MFA levanta SessionError (no intenta resolverlo)",
                  ("2fa" in msg or "mfa" in msg or "segundo factor" in msg))
            check("el error remite a la Forma 3 (el humano se loguea)", "forma 3" in msg or "humano" in msg)

        # ── 7 · guard SSRF manda — sin guard de test, loopback se bloquea ────────
        print("\n[7] el guard SSRF corre primero (fail-closed)")
        p7 = C.Principal(anon_id=f"f2-ssrf-{uuid.uuid4().hex[:8]}")
        blocked = LoginAPISession(base, "/login", GOOD, p7, "f2-ssrf",
                                  guard=PublicHTTPGuard(), cred_root=root)  # guard REAL
        try:
            blocked.acquire()
            check("el guard real bloquea loopback", False, "no bloqueó")
        except C.SessionError as e:
            check("el guard real bloquea loopback (SSRF)", "guard" in str(e).lower() or "ssrf" in str(e).lower())

    finally:
        srv.shutdown()

    print("\n" + "═" * 72)
    if fails:
        print(f"  ROJO — {len(fails)} check(s) fallaron: {fails}")
        return 1
    print("  VERDE — Forma 2 (login API) verificada contra un login server real")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
