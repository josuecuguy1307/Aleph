"""
url_guard.py — el ANTI-SSRF del recon (T9).

El recon navega/replica URLs que vienen del afuera (el target que el usuario apunta,
o la request observada que la tool sintetizada reconstruye). Sin guard, un target
`http://169.254.169.254/latest/meta-data/` o `http://localhost:6379/` convierte al
motor en un proxy hacia la red interna / la metadata del cloud / servicios sin auth.

Defensa (fail-closed, en capas):
  1. Esquema: solo http/https. file:// gopher:// data:// ftp:// → bloqueado.
  2. Sin credenciales embebidas (user:pass@) — vector de confusión.
  3. Rango de IP: se RESUELVE el host (getaddrinfo) y se chequea CADA dirección
     resultante. Si UNA sola no es `is_global` (privada/loopback/link-local/reserved/
     CGNAT/multicast/unspecified) → bloqueado. Esto cierra el DNS-rebinding (un nombre
     que resuelve a 127.0.0.1 cae igual que la IP literal).
  4. Metadata de cloud explícita (169.254.169.254 y parientes) — belt-and-suspenders.
  5. Allowlist de host opcional ("solo software con derecho a inspeccionar").

`allow_local_fixture=True` afloja SOLO loopback (127/8, ::1) — para el target benigno
local de la demo. NUNCA afloja link-local/metadata/LAN privada, ni siquiera ahí.
"""
from __future__ import annotations

import errno
import http.client
import ipaddress
import socket
import sys
import urllib.parse
import urllib.request
from typing import Optional

from . import config


class UrlBlocked(Exception):
    """El target/URL no tiene derecho a ser inspeccionado/contactado por el motor."""

    def __init__(self, url: str, reason: str):
        self.url = url
        self.reason = reason
        super().__init__(f"URL bloqueada por safety: {reason} — {url!r}")


def _unwrap_v4_mapped(ip: ipaddress._BaseAddress):
    """::ffff:10.0.0.1 → 10.0.0.1, así un v4-mapped no esquiva el filtro de rangos."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        # 6to4 (2002::/16) y demás tunelados quedan como v6; is_global los cubre.
    return ip


def _ip_is_blocked(ip_str: str, *, allow_loopback: bool) -> Optional[str]:
    """Devuelve el motivo si la IP debe bloquearse, o None si es pública/permitida."""
    if ip_str in config.CLOUD_METADATA_IPS:
        return "cloud-metadata-ip"
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return "ip-invalida"
    ip = _unwrap_v4_mapped(ip)
    # re-chequear metadata tras el unwrap
    if str(ip) in config.CLOUD_METADATA_IPS:
        return "cloud-metadata-ip"
    if ip.is_loopback:
        return None if allow_loopback else "loopback"
    if ip.is_link_local:
        return "link-local"          # incluye 169.254.0.0/16 (metadata) y fe80::/10
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_reserved:
        return "reserved"
    if ip.is_private:
        return "rango-privado"        # 10/8, 172.16/12, 192.168/16, fc00::/7, CGNAT…
    if not ip.is_global:
        return "no-global"            # red de carrier / cualquier rango no-ruteable
    return None


def _host_allowed(host: str) -> bool:
    """allowlist de host (sufijos). Vacía = no se aplica allowlist."""
    allow = config.INSPECT_HOST_ALLOWLIST
    if not allow:
        return True
    h = host.lower().rstrip(".")
    return any(h == a or h.endswith("." + a) for a in allow)


def classify_url(url: str, *, allow_local_fixture: bool = False) -> Optional[str]:
    """
    Devuelve el MOTIVO de bloqueo (str) o None si la URL es inspeccionable.
    No resuelve excepciones — pensado para `is_safe`/diagnóstico.
    """
    if not url or not isinstance(url, str):
        return "url-vacia"
    parts = urllib.parse.urlsplit(url.strip())

    if parts.scheme.lower() not in config.ALLOWED_SCHEMES:
        return f"esquema-no-permitido:{parts.scheme or '∅'}"
    if "@" in parts.netloc:
        return "credenciales-embebidas"

    host = parts.hostname
    if not host:
        return "sin-host"
    if not _host_allowed(host):
        return "fuera-de-allowlist"

    allow_loopback = allow_local_fixture or config.ALLOW_PRIVATE_TARGETS

    try:
        port = parts.port
    except ValueError:
        return "puerto-invalido"

    # Si el host YA es una IP literal, no hace falta resolver.
    try:
        ipaddress.ip_address(host)
        is_literal = True
    except ValueError:
        is_literal = False

    if is_literal:
        reason = _ip_is_blocked(host, allow_loopback=allow_loopback)
        return reason  # None si pública

    # Nombre → resolver TODAS las direcciones y chequear cada una (anti-rebinding).
    if config.ALLOW_PRIVATE_TARGETS:
        # dev override total: no resolvemos contra rangos (pero esquema/allowlist ya pasaron)
        return None
    try:
        infos = socket.getaddrinfo(host, port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return "dns-no-resuelve"      # fail-closed: si no resuelve, no se contacta
    except Exception:
        return "dns-error"
    if not infos:
        return "dns-vacio"
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        reason = _ip_is_blocked(ip_str, allow_loopback=allow_loopback)
        if reason:
            return f"{reason}(resuelto:{ip_str})"
    return None


def is_safe(url: str, *, allow_local_fixture: bool = False) -> tuple[bool, Optional[str]]:
    reason = classify_url(url, allow_local_fixture=allow_local_fixture)
    return (reason is None, reason)


def assert_inspectable(url: str, *, allow_local_fixture: bool = False) -> str:
    """
    Garantiza que `url` puede ser inspeccionada/contactada por el motor, o levanta
    UrlBlocked. Devuelve la url (normalizada/strip) para encadenar.
    """
    reason = classify_url(url, allow_local_fixture=allow_local_fixture)
    if reason is not None:
        raise UrlBlocked(url, reason)
    return url.strip()


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Revalida cada salto antes de que urllib siga un redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_inspectable(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if (old.scheme.lower(), old.hostname, old.port) != (
                new.scheme.lower(), new.hostname, new.port):
            # urllib otherwise copies caller credentials onto a different public host.
            for name in list(redirected.headers):
                if name.lower() in ("authorization", "x-api-key"):
                    redirected.remove_header(name)
        return redirected


def _pinned_public_ip(host: str, port: int) -> str:
    """Resuelve, valida todas las respuestas y devuelve una IP numérica para conectar."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlBlocked(host, "dns-no-resuelve") from exc
    except Exception as exc:
        raise UrlBlocked(host, "dns-error") from exc
    if not infos:
        raise UrlBlocked(host, "dns-vacio")

    allow_loopback = config.ALLOW_PRIVATE_TARGETS
    for info in infos:
        ip_str = info[4][0]
        reason = _ip_is_blocked(ip_str, allow_loopback=allow_loopback)
        if reason:
            raise UrlBlocked(host, f"{reason}(resuelto:{ip_str})")
    return infos[0][4][0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Conecta a la IP validada sin una segunda resolución DNS en el socket."""

    def connect(self):
        sys.audit("http.client.connect", self, self.host, self.port)
        pinned_ip = _pinned_public_ip(self.host, self.port)
        self.sock = self._create_connection(
            (pinned_ip, self.port), self.timeout, self.source_address)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            if exc.errno != errno.ENOPROTOOPT:
                raise


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Pin DNS while retaining the original hostname for TLS certificate/SNI checks."""

    def connect(self):
        sys.audit("http.client.connect", self, self.host, self.port)
        pinned_ip = _pinned_public_ip(self.host, self.port)
        self.sock = self._create_connection(
            (pinned_ip, self.port), self.timeout, self.source_address)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            if exc.errno != errno.ENOPROTOOPT:
                raise
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context)


# ProxyHandler({}) is deliberate: a generic environment proxy would resolve the target
# out of process and undo address pinning. Connector validation therefore goes direct.
_PUBLIC_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _PinnedHTTPHandler(),
    _PinnedHTTPSHandler(),
    _SafeRedirectHandler(),
)


def open_public_url(target, *, timeout: float):
    """Abre sólo HTTP(S) público y vuelve a aplicar el guard en cada redirect.

    ``target`` acepta la misma URL o ``Request`` que ``urllib``. La clasificación se
    hace inmediatamente antes de abrir para que todos los llamadores compartan el mismo
    borde fail-closed; el redirect handler impide que una URL pública pivote luego a una
    dirección privada, loopback, link-local o de metadata.
    """
    url = target.full_url if isinstance(target, urllib.request.Request) else str(target)
    assert_inspectable(url)
    return _PUBLIC_OPENER.open(target, timeout=timeout)
