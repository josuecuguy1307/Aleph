"""
loop/guard.py — Capa 0 · SSRFGuard real (Trampa 3) · corre ANTES de tocar el target.

El motor apunta a URLs que el usuario trae crudas → agujero SSRF de manual. Este
guard es OBLIGATORIO y FAIL-CLOSED: ante cualquier duda, deny. Bloquea:

  • esquemas que no sean http/https (file://, gopher://, ftp://…),
  • loopback / privadas / link-local / reservadas / multicast / la IP de metadata
    de la nube (169.254.169.254) — RESOLVIENDO el host por DNS y mirando CADA IP
    (no solo el literal; un hostname puede resolver a 127.0.0.1).

Cumple el contrato C.SSRFGuard (check(url) → GuardVerdict). No hace la request:
solo dictamina si tocarla es seguro. Reusa la idea del guard anti-SSRF de T9
(platform/safety) pero acá vive autocontenido para el loop (stdlib only).
"""
from __future__ import annotations

import ipaddress
import socket
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402

_METADATA_IPS = {"169.254.169.254", "fd00:ec2::254"}


def _ip_is_dangerous(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # no parsea ⇒ peligro (fail-closed)
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
        or ip in _METADATA_IPS
    )


class PublicHTTPGuard(C.SSRFGuard):
    """Solo deja pasar http/https a hosts PÚBLICOS. Todo lo demás → deny + razón.

    `resolve=True` (default) resuelve el host por DNS y valida cada IP; `False`
    valida solo el literal (útil en tests sin red, sigue siendo fail-closed)."""

    def __init__(self, *, resolve: bool = True, allow_http: bool = False):
        self._resolve = resolve
        self._allow_http = allow_http

    def check(self, url: str) -> C.GuardVerdict:
        try:
            u = urlparse(url)
        except (ValueError, TypeError):
            return C.GuardVerdict(False, "url no parseable")

        scheme = (u.scheme or "").lower()
        allowed_schemes = {"https"} | ({"http"} if self._allow_http else set())
        if scheme not in allowed_schemes:
            return C.GuardVerdict(False, f"esquema no permitido: {scheme or '∅'} (solo {sorted(allowed_schemes)})")

        host = u.hostname or ""
        if not host:
            return C.GuardVerdict(False, "sin host")

        low = host.lower()
        if low in ("localhost",) or low.endswith(".local") or low.endswith(".internal"):
            return C.GuardVerdict(False, f"host local prohibido: {host}")

        # ¿el host YA es una IP literal?
        try:
            ipaddress.ip_address(host)
            if _ip_is_dangerous(host):
                return C.GuardVerdict(False, f"IP no pública: {host}")
            return C.GuardVerdict(True, f"IP pública: {host}")
        except ValueError:
            pass  # es un hostname → resolver

        if not self._resolve:
            return C.GuardVerdict(True, f"host {host} (sin resolución DNS; modo test)")

        try:
            infos = socket.getaddrinfo(host, u.port or (443 if scheme == "https" else 80),
                                       proto=socket.IPPROTO_TCP)
        except socket.gaierror as e:
            return C.GuardVerdict(False, f"DNS no resuelve {host}: {e}")

        ips = {info[4][0] for info in infos}
        if not ips:
            return C.GuardVerdict(False, f"{host} no resolvió a ninguna IP")
        for ip in ips:
            if _ip_is_dangerous(ip):
                return C.GuardVerdict(False, f"{host} resuelve a IP no pública {ip} (SSRF)")
        return C.GuardVerdict(True, f"{host} → {sorted(ips)} (público)")


def _norm_ip(addr: "ipaddress._BaseAddress") -> "ipaddress._BaseAddress":
    """Normaliza IPv4-mapped IPv6 (::ffff:a.b.c.d) a la IPv4 real. Sin esto, la IP de metadata
    169.254.169.254 escrita como ::ffff:169.254.169.254 evade el denylist por-string (bypass real
    hallado en security-review): tiene is_private/is_link_local True y su string NO está en
    _METADATA_IPS. Normalizando, cae en la misma IPv4 que sí se bloquea."""
    m = getattr(addr, "ipv4_mapped", None)
    return m if m is not None else addr


def _ip_local_ok(ip_str: str) -> bool:
    """True SÓLO si la IP es loopback o privada (RFC1918) legítima de un self-hosted — NUNCA la IP
    de metadata ni link-local. La IP de metadata (169.254.169.254) ES link-local: excluir TODO el
    rango link-local borra el denylist frágil por-string y cierra el bypass por encoding."""
    try:
        a = _norm_ip(ipaddress.ip_address(ip_str))
    except ValueError:
        return False
    if (str(a) in _METADATA_IPS or a.is_link_local or a.is_multicast
            or a.is_reserved or a.is_unspecified):
        return False   # metadata/link-local/multicast/reservada/0.0.0.0 nunca son "tu servidor"
    return bool(a.is_loopback or a.is_private)


def _is_safe_local(host: str, port: Optional[int] = None) -> bool:
    """El opt-in de target-local confía SÓLO en:
       (a) una IP LITERAL loopback/privada (normalizada: sin link-local, sin metadata), o
       (b) el nombre literal 'localhost' (estable vía /etc/hosts, no rebindeable por DNS remoto).
    CUALQUIER otro hostname (.local, .internal, un dominio) se RECHAZA → cae al guard estricto.
    Motivo (security-review, probe 2): el fetch re-resuelve el host de forma independiente; un
    hostname arbitrario que resuelve privado al chequear podría rebindear a metadata/público al
    usar (TOCTOU). No resolviendo nombres acá, el opt-in NO agrega ese vector de DNS-rebinding."""
    if not host:
        return False
    try:
        ipaddress.ip_address(host)      # ¿IP literal (v4/v6, incluida ::ffff:… mapeada)?
        return _ip_local_ok(host)
    except ValueError:
        return host.lower() == "localhost"


class DeclaredLocalTargetGuard(C.SSRFGuard):
    """OPT-IN explícito del usuario: 'este es MI servidor self-hosted (loopback/red privada)'.

    El SSRF protege contra que el AGENTE sea engañado para tocar servicios internos; NO contra
    que el USUARIO apunte a SU PROPIO servidor con SU credencial. Este guard deja pasar http/https
    SÓLO al host:port EXACTO que el usuario declaró (aunque sea loopback/privado) y SÓLO si ese
    host es realmente local (`_is_safe_local`: nunca metadata, nunca público disfrazado). TODO lo
    demás — cualquier otro host, otra IP privada, la IP de metadata, otro esquema — se delega al
    guard ESTRICTO (`PublicHTTPGuard`). Así el agente no puede pivotar del target local declarado
    a 169.254.169.254 ni a ningún otro servicio interno: sólo alcanza lo que el usuario declaró."""

    def __init__(self, allowed_host: str, allowed_port: Optional[int], *,
                 resolve: bool = True, strict: Optional[C.SSRFGuard] = None):
        self._host = (allowed_host or "").lower()
        self._port = allowed_port
        self._resolve = resolve
        self._strict = strict or PublicHTTPGuard(resolve=resolve)

    def check(self, url: str) -> C.GuardVerdict:
        try:
            u = urlparse(url)
        except (ValueError, TypeError):
            return C.GuardVerdict(False, "url no parseable")
        scheme = (u.scheme or "").lower()
        host = (u.hostname or "").lower()
        if (scheme in ("http", "https") and host and host == self._host and u.port == self._port
                and _is_safe_local(host, u.port)):
            return C.GuardVerdict(True, f"target self-hosted declarado por el usuario: {host}:{self._port}")
        # cualquier otra cosa → guard estricto público-solo (fail-closed por delegación)
        return self._strict.check(url)


def declared_target_guard(base_url: str, *, resolve: bool = True,
                          strict: Optional[C.SSRFGuard] = None) -> DeclaredLocalTargetGuard:
    """Construye el guard de target-local desde la URL declarada (deriva host:port)."""
    u = urlparse(base_url)
    return DeclaredLocalTargetGuard(u.hostname or "", u.port, resolve=resolve, strict=strict)
