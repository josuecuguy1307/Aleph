"""
loop/live_http.py — el cliente HTTP VIVO que usan el observador y el candado.

Una sola superficie de red para todo el loop. GET real (stdlib urllib), con dos
invariantes no negociables:

  • Forma 1 (token en query): el secreto (api_key) se inyecta en el query string
    en el ÚLTIMO momento, acá; ninguna capa de arriba lo manosea.
  • LOG REDACTADO: la URL que sale a cualquier log NUNCA lleva el secreto — se
    reemplaza por `api_key=***`. El valor en claro vive solo en memoria, en el
    momento de la request.

Honesto: timeout / transporte caído ⇒ `status=0` + `reason`, no una excepción que
el loop tenga que adivinar. El candado clasifica `status` por la tabla §5.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Optional

_REDACT = "***"


@dataclass(frozen=True)
class HttpResult:
    """El resultado crudo de una request viva. `ok` == 2xx con cuerpo parseable."""
    status: int                     # 0 == transporte caído / timeout
    json: Optional[Any]             # cuerpo parseado (dict/list) o None
    text: str                       # cuerpo crudo (recortado)
    elapsed_ms: int
    url_redacted: str               # URL SIN el secreto (apta para log)
    reason: str = ""                # detalle cuando status==0 (timeout/transport)
    allow: tuple[str, ...] = ()     # métodos del header `Allow` (solo en OPTIONS; () en GET)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def has_shape(self) -> bool:
        """Cuerpo con FORMA (dict no-vacío o lista) — el candado exige forma, no
        solo un 200 hueco."""
        if isinstance(self.json, dict):
            return len(self.json) > 0
        if isinstance(self.json, list):
            return True
        return False


def _redact(url: str, secret: str) -> str:
    if secret and secret in url:
        url = url.replace(secret, _REDACT)
    return url


def _parse_allow(value: str) -> tuple[str, ...]:
    """`Allow: GET, POST, OPTIONS` → ('GET','POST','OPTIONS'). Vacío → ()."""
    if not value:
        return ()
    return tuple(m.strip().upper() for m in value.split(",") if m.strip())


class LiveHTTP:
    """GET vivo con inyección de auth uniforme + redacción del secreto en logs.

    Dos carriles de auth, NO excluyentes pero en la práctica disjuntos por forma:
      • Forma 1 (token en query): `secret`/`auth_param` → cada GET agrega
        `?<auth_param>=<secret>`. El secreto se redacta en `url_redacted`.
      • Forma 2/3 (sesión ya adquirida): `headers`/`cookies` de la `Session` uniforme
        (p.ej. `Authorization: Bearer …` o una cookie de sesión) se inyectan en CADA
        request. ADITIVO: en Forma 1 ambos llegan vacíos y la request es byte-idéntica
        a la de siempre — el carril token-en-query no se toca.
    `ledger` (opcional) cuenta cada llamada contra el cap duro (§6).
    """

    def __init__(
        self,
        *,
        secret: str = "",
        auth_param: str = "api_key",
        timeout: float = 15.0,
        max_text: int = 20_000,
        ledger: Any = None,
        user_agent: str = "puppet-inspection-loop/1.0",
        min_interval: float = 0.0,
        headers: Optional[Mapping[str, str]] = None,
        cookies: Optional[Mapping[str, str]] = None,
    ):
        self._secret = secret or ""
        self._auth_param = auth_param
        self._timeout = timeout
        self._max_text = max_text
        self._ledger = ledger
        self._ua = user_agent
        # Forma 2/3: la auth que la Session ya lleva inyectada (header Bearer, cookie de
        # sesión). El loop la consume sin saber de qué forma vino. En Forma 1 quedan {}.
        self._session_headers = dict(headers or {})
        self._session_cookies = dict(cookies or {})
        # PACING: intervalo mínimo entre requests (s). Muchas APIs throttlean
        # (Alpha Vantage = 1 req/seg); sin pacing TODAS las calls vuelven con el
        # aviso de rate-limit y nada verifica. 0 = sin pausa (TMDB no throttlea).
        self._min_interval = max(0.0, min_interval)
        self._last_call = 0.0

    def get(self, url: str, query: Optional[Mapping[str, Any]] = None) -> HttpResult:
        """GET vivo. `url` es absoluta; `query` son params extra (los del tool).
        El secreto se agrega acá y se redacta en `url_redacted`."""
        if self._min_interval:
            import time as _t
            wait = self._min_interval - (_t.monotonic() - self._last_call)
            if wait > 0:
                _t.sleep(wait)
            self._last_call = _t.monotonic()
        if self._ledger is not None:
            self._ledger.add_calls(1)

        params: dict[str, Any] = {}
        for k, v in (query or {}).items():
            if v is None:
                continue
            params[str(k)] = v
        if self._secret:
            params[self._auth_param] = self._secret

        full = url
        if params:
            sep = "&" if ("?" in url) else "?"
            full = url + sep + urllib.parse.urlencode(params, doseq=True)
        redacted = _redact(full, self._secret)

        req_headers = {"User-Agent": self._ua, "Accept": "application/json"}
        # Forma 2/3: sumá la auth uniforme de la Session (header y/o cookie). En Forma 1
        # ambos están vacíos ⇒ req_headers queda byte-idéntico al de siempre (no rompe TMDB).
        if self._session_headers:
            req_headers.update(self._session_headers)
        if self._session_cookies:
            req_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._session_cookies.items())
        req = urllib.request.Request(full, headers=req_headers, method="GET")
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                status = resp.getcode() or 0
        except urllib.error.HTTPError as e:
            # 4xx/5xx llegan acá con cuerpo: lo conservamos (el candado lo clasifica).
            raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
            status = e.code
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ms = int((time.monotonic() - t0) * 1000)
            return HttpResult(status=0, json=None, text="", elapsed_ms=ms,
                              url_redacted=redacted, reason=str(getattr(e, "reason", e)))

        ms = int((time.monotonic() - t0) * 1000)
        text = raw[: self._max_text]
        parsed: Optional[Any] = None
        try:
            parsed = json.loads(raw) if raw else None
        except (json.JSONDecodeError, ValueError):
            parsed = None
        return HttpResult(status=status, json=parsed, text=text, elapsed_ms=ms,
                          url_redacted=redacted)

    def options(self, url: str) -> HttpResult:
        """OPTIONS vivo · preflight que NO muta (§7): confirma que el endpoint EXISTE y
        qué métodos acepta (header `Allow`) SIN tocar el mundo. Aditivo — `get()` no se
        toca; el carril read es byte-idéntico. Misma auth/pacing/redacción que `get()`
        (algunos servers exigen la sesión para responder OPTIONS). El cuerpo de un OPTIONS
        no interesa: lo que importa es `status` + `allow`."""
        if self._min_interval:
            import time as _t
            wait = self._min_interval - (_t.monotonic() - self._last_call)
            if wait > 0:
                _t.sleep(wait)
            self._last_call = _t.monotonic()
        if self._ledger is not None:
            self._ledger.add_calls(1)

        full = url
        if self._secret:
            sep = "&" if ("?" in url) else "?"
            full = url + sep + urllib.parse.urlencode({self._auth_param: self._secret})
        redacted = _redact(full, self._secret)

        req_headers = {"User-Agent": self._ua, "Accept": "application/json"}
        if self._session_headers:
            req_headers.update(self._session_headers)
        if self._session_cookies:
            req_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._session_cookies.items())
        req = urllib.request.Request(full, headers=req_headers, method="OPTIONS")
        t0 = time.monotonic()
        allow_raw = ""
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                resp.read()                         # drena el cuerpo (sin parsear)
                status = resp.getcode() or 0
                allow_raw = resp.headers.get("Allow", "") or resp.headers.get("allow", "")
        except urllib.error.HTTPError as e:
            # 4xx/5xx para OPTIONS: 405 suele traer `Allow` igual — lo conservamos.
            status = e.code
            try:
                allow_raw = e.headers.get("Allow", "") if e.headers else ""
            except AttributeError:
                allow_raw = ""
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ms = int((time.monotonic() - t0) * 1000)
            return HttpResult(status=0, json=None, text="", elapsed_ms=ms,
                              url_redacted=redacted, reason=str(getattr(e, "reason", e)))

        ms = int((time.monotonic() - t0) * 1000)
        return HttpResult(status=status, json=None, text="", elapsed_ms=ms,
                          url_redacted=redacted, allow=_parse_allow(allow_raw))
