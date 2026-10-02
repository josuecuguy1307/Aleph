"""loopback.py — LA EXCEPCIÓN DE LOOPBACK DEL CINTURÓN, acotada por puerto.
[Gate 4 · Fase 6 · §6.a · la regla está en REGLA-LOOPBACK.md, escrita ANTES que esto]

QUÉ RESUELVE, EN UNA LÍNEA
--------------------------
«El agente levanta un servidor propio y lo navega» — sin que eso signifique que puede
navegar el backend de Aleph.

POR QUÉ NO ES UNA EXCEPCIÓN DE RANGO
------------------------------------
En esta máquina, con Aleph corriendo, escuchan en loopback: el sidecar entero (Home, Capa 0
y TODA `/v1` — `aleph-shell/src-tauri/src/lib.rs:4,10,55`), los packs de los seis workspaces
(`workspaces/pack.py:119`) y los motores de búsqueda y research. Abrir «loopback» le daría
al agente la API de Aleph con la sesión del usuario ya puesta en el navegador. Por eso la
excepción es **allowlist por (run_id, puerto)** y el resto de `127.0.0.0/8` sigue negado.

POR QUÉ NO SE DELEGA EN browser-use — MEDIDO, no supuesto
----------------------------------------------------------
Su `SecurityWatchdog._is_ip_address` (`security_watchdog.py:138-174`) canonicaliza IPv4 raras
(decimal/hex/octal/percent/Unicode) pero **sólo mira literales**: un hostname devuelve False.
Y `_is_url_allowed:216-221` **permite todo** cuando no hay `allowed_domains` ni
`prohibited_domains` — fail-OPEN. Este módulo corre ANTES y decide; el `allowed_domains` del
stack queda como segunda cerca, más gruesa.

LO QUE ESTE MÓDULO NO HACE: no abre sockets, no hace HTTP, no conoce el navegador. Recibe
una URL y un `run_id`, y dictamina. Así la regla se prueba con una tabla y la vara no
necesita levantar medio producto. Sólo stdlib.

⚠️ NO TOCA `platform/inspection/loop/guard.py`. Ése sigue fail-closed negando loopback: la
excepción es del cinturón, no de él (regla R6). La vara lo verifica.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import threading
import time
from typing import Iterable, NamedTuple, Optional
from urllib.parse import urlsplit

#: Causas tipadas. Ninguna causa llega a una superficie sin copy (regla sellada de la casa).
CAUSAS = {
    "ok": "",
    "sin_run": "No sé de qué trabajo viene este pedido, así que no lo abro.",
    "esquema": "Solo puedo abrir direcciones http o https.",
    "url_rota": "Esa dirección no se entiende.",
    "sin_host": "Esa dirección no dice a qué servidor ir.",
    "dns": "No pude averiguar a qué máquina apunta esa dirección.",
    "metadata": "Esa dirección es de la infraestructura de la nube y nunca se abre.",
    "privada": "Esa dirección es de tu red local, y por ahora no salgo ahí.",
    "reservada": "Esa dirección está reservada y no se abre.",
    "sidecar": "Esa es la dirección de Aleph mismo. No me navego a mí.",
    # ⚠️ DOS CAUSAS DISTINTAS, y la prueba de humo mostró por qué importa: con el puerto del
    # sidecar sin declarar, TODO loopback caía en «esa es la dirección de Aleph mismo» — que
    # es falso para un puerto cualquiera. El fail-closed es correcto (no se puede descartar
    # que sea él); lo que estaba mal era el TEXTO. La conducta no cambia: cambia lo que se dice.
    "sidecar_sin_declarar": "Todavía no sé en qué puerto vive Aleph, así que por las dudas no abro ninguna dirección local.",
    "puerto_ajeno": "Ese puerto local no lo levantó este trabajo, así que no lo abro.",
}

#: El puerto del propio sidecar. Lo fija el arranque con `fijar_sidecar()`; hasta entonces es
#: None y —fail-closed— **todo loopback se niega**, porque no podemos descartar que sea él.
_sidecar_port: Optional[int] = None

#: `run_id -> {puerto: pid}`. En memoria del proceso, muere con el proceso. No es un archivo:
#: el agente no tiene dónde escribir. El lock protege el registro de dos turnos concurrentes.
_registro: dict[str, dict[int, tuple[Optional[int], float]]] = {}
_lock = threading.Lock()


class Veredicto(NamedTuple):
    ok: bool
    causa: str
    copy: str
    detalle: str = ""


def _no(causa: str, detalle: str = "") -> Veredicto:
    return Veredicto(False, causa, CAUSAS.get(causa, CAUSAS["url_rota"]), detalle)


# ── el registro ────────────────────────────────────────────────────────────────────────
def fijar_sidecar(port: int) -> None:
    """El arranque declara en qué puerto vive Aleph. Antes de esto, todo loopback se niega."""
    global _sidecar_port
    _sidecar_port = int(port)


def anotar(run_id: str, puerto: int, pid: Optional[int] = None, *, ttl_s: int = 300) -> None:
    """La TOOL de la casa anota el puerto que acaba de levantar. El agente jamás llama acá."""
    if (not run_id or not isinstance(puerto, int) or not (1 <= puerto <= 65535)
            or ttl_s < 1 or ttl_s > 1800):
        return
    with _lock:
        _registro.setdefault(str(run_id), {})[puerto] = (pid, time.time() + ttl_s)


def desanotar(run_id: str, puerto: Optional[int] = None) -> None:
    """Al apagar el proceso (o al cerrar el run). Ciclo simétrico: nada queda huérfano."""
    with _lock:
        if puerto is None:
            _registro.pop(str(run_id), None)
        else:
            _registro.get(str(run_id), {}).pop(puerto, None)


def puertos_de(run_id: str) -> set:
    with _lock:
        return {port for port, (pid, deadline) in _registro.get(str(run_id), {}).items()
                if deadline > time.time() and _alive(pid)}


def _alive(pid: Optional[int]) -> bool:
    if pid is None:
        return True  # in-process fixture/tool registration; never exported cross-process
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def exportar_excepciones(run_id: str) -> list[dict]:
    """Only trusted parent code exports live, PID-bound grants to its child pack."""
    with _lock:
        return [{"port": port, "pid": pid, "expires_at": deadline}
                for port, (pid, deadline) in _registro.get(str(run_id), {}).items()
                if pid is not None and deadline > time.time() and _alive(pid)]


def importar_excepciones(run_id: str, grants: object) -> None:
    """Called solely after local_pack_auth verifies the launch capability."""
    if not isinstance(grants, list) or len(grants) > 8:
        raise ValueError("invalid browser loopback grants")
    for grant in grants:
        if not isinstance(grant, dict):
            raise ValueError("invalid browser loopback grant")
        port, pid, expires = grant.get("port"), grant.get("pid"), grant.get("expires_at")
        if (not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535
                or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0
                or not isinstance(expires, (int, float)) or not time.time() < expires <= time.time() + 300
                or not _alive(pid)):
            raise ValueError("invalid or expired browser loopback grant")
        # Preserve the originating expiry exactly; rounding a sub-second
        # remainder up would silently extend a cross-process exception.
        with _lock:
            _registro.setdefault(str(run_id), {})[port] = (pid, expires)


# ── la decisión ────────────────────────────────────────────────────────────────────────
def _ips_de(host: str) -> Optional[list]:
    """Cada IP a la que resuelve el host. `None` si no resuelve (⇒ deny, R5).

    Se resuelve SIEMPRE, aunque el host parezca un dominio: un hostname que apunta a
    loopback ES loopback (R4). Ésta es la línea que browser-use no tiene."""
    try:
        return [ipaddress.ip_address(h.strip("[]"))
                for h in {i[4][0] for i in socket.getaddrinfo(host, None)}]
    except Exception:
        try:
            return [ipaddress.ip_address(host.strip("[]"))]   # literal sin DNS
        except Exception:
            return None


def _clase(ip) -> Optional[str]:
    """La causa dura de una IP, o None si no es dura. El orden es el de la regla R3."""
    if str(ip) in ("169.254.169.254", "fd00:ec2::254"):
        return "metadata"
    if ip.version == 6 and ip.is_loopback:
        return "puerto_ajeno"  # grants are IPv4-loopback only, never ::1
    if ip.is_loopback:
        return None                                   # lo decide el registro (R1)
    if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return "reservada"
    if ip.is_private:
        return "privada"
    return None


def permitir(url: str, *, run_id: Optional[str]) -> Veredicto:
    """¿Puede el navegador del agente ir a esta URL? Fail-closed en todo camino (R5)."""
    try:
        host = urlsplit(url).hostname
    except Exception:
        return _no("url_rota", url[:120])
    return permitir_resueltos(url, run_id=run_id, ips=_ips_de(host) if host else None)


def permitir_resueltos(url: str, *, run_id: Optional[str], ips: Optional[list]) -> Veredicto:
    """Validate the *same* addresses that a caller will dial numerically.

    The browser proxy must not check DNS and then let Chromium resolve a second
    time. Its socket destination is drawn only from this validated snapshot.
    """
    if not run_id:
        return _no("sin_run")
    try:
        p = urlsplit(url)
    except Exception:
        return _no("url_rota", url[:120])
    if p.scheme.lower() not in ("http", "https"):
        return _no("esquema", p.scheme or "(vacío)")
    host = p.hostname
    if not host:
        return _no("sin_host", url[:120])

    if not ips:
        return _no("dns", host)

    permitidos = puertos_de(run_id)
    for ip in ips:                                    # TODAS las IPs, no la primera (R4)
        dura = _clase(ip)
        if dura:
            return _no(dura, f"{host} → {ip}")
        if ip.is_loopback:
            # R5: sin saber cuál es el sidecar, no podemos descartar que sea él.
            if _sidecar_port is None:
                return _no("sidecar_sin_declarar", "nadie llamó a fijar_sidecar()")
            puerto = p.port or (443 if p.scheme == "https" else 80)
            if puerto == _sidecar_port:               # R3: gana sobre el registro
                return _no("sidecar", f"{host}:{puerto}")
            if puerto not in permitidos:              # R1
                return _no("puerto_ajeno", f"{host}:{puerto}")
    return Veredicto(True, "ok", "", "")


__all__ = ["permitir", "permitir_resueltos", "anotar", "desanotar", "puertos_de", "fijar_sidecar",
           "exportar_excepciones", "importar_excepciones",
           "Veredicto", "CAUSAS"]
