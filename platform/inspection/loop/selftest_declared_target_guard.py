"""
selftest_declared_target_guard.py — el opt-in de target self-hosted es TIGHT (Capa 0).

Prueba que DeclaredLocalTargetGuard deja pasar SÓLO el host:port EXACTO que el usuario declaró
(aunque sea loopback/privado, http) y delega TODO lo demás al guard estricto público-solo — de
modo que el agente NO puede pivotar del target local a la IP de metadata ni a otro servicio interno.

Sin red (stdlib): usa IPs literales (127.0.0.1, 10.x, 169.254.x) y `localhost` (resuelve por hosts).

Run:  python selftest_declared_target_guard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection.loop.guard import (  # noqa: E402
    PublicHTTPGuard, DeclaredLocalTargetGuard, declared_target_guard,
)

fails = []


def check(label: str, cond: bool, extra: str = "") -> None:
    print(f"{'✓' if cond else '✗'} {label}{'  ' + extra if extra else ''}")
    if not cond:
        fails.append(label)


def main() -> int:
    print("═" * 72)
    print("  GATE · el opt-in de target self-hosted es TIGHT (sólo el host declarado)")
    print("═" * 72)

    # ── 1 · SIN opt-in, el guard estricto BLOQUEA el self-hosted http (el muro que vio B1) ──
    strict = PublicHTTPGuard(resolve=False)
    v = strict.check("http://127.0.0.1:8210")
    check("[1] sin opt-in: el estricto BLOQUEA http://127.0.0.1:8210 (esquema+loopback)",
          not v, v.reason)

    # ── 2 · CON opt-in, el host:port EXACTO declarado PASA (http + loopback) ──
    g = declared_target_guard("http://127.0.0.1:8210", resolve=False)
    v = g.check("http://127.0.0.1:8210")
    check("[2] con opt-in: el target declarado http://127.0.0.1:8210 PASA", bool(v), v.reason)
    v = g.check("http://127.0.0.1:8210/v1/feeds?limit=5")
    check("[2b] con opt-in: una request bajo el MISMO host:port (path/query) PASA", bool(v), v.reason)

    # ── 3 · el opt-in NO abre NADA MÁS: otro puerto, otro host, otra IP privada, metadata ──
    v = g.check("http://127.0.0.1:8211")
    check("[3a] otro PUERTO del mismo host → estricto → BLOQUEA (no es el declarado)", not v, v.reason)
    v = g.check("http://10.0.0.5:8210")
    check("[3b] otra IP privada (10.0.0.5) → estricto → BLOQUEA", not v, v.reason)
    v = g.check("http://169.254.169.254/latest/meta-data/")
    check("[3c] IP de metadata de la nube → estricto → BLOQUEA (no hay pivote SSRF)", not v, v.reason)
    v = g.check("http://192.168.1.1:8210")
    check("[3d] router/otro host de la LAN → estricto → BLOQUEA", not v, v.reason)

    # ── 4 · declarar la IP de metadata NO la abre (nunca es un self-hosted legítimo) ──
    gm = declared_target_guard("http://169.254.169.254:80", resolve=False)
    v = gm.check("http://169.254.169.254:80")
    check("[4] declarar la IP de metadata NO la abre (_is_safe_local la excluye)", not v, v.reason)

    # ── 5 · declarar una IP PÚBLICA por http NO la abre por el opt-in (la maneja el estricto) ──
    gp = declared_target_guard("http://8.8.8.8:80", resolve=False)
    v = gp.check("http://8.8.8.8:80")
    check("[5] declarar una IP pública por http → estricto la evalúa (no es 'local'), BLOQUEA", not v, v.reason)

    # ── 6 · el opt-in delega el TRÁFICO público normal al estricto (https público pasa) ──
    v = g.check("https://api.themoviedb.org/3/configuration")
    check("[6] con opt-in de loopback, un https PÚBLICO sigue pasando (delegado al estricto)",
          bool(v), v.reason)
    v = g.check("file:///etc/passwd")
    check("[6b] con opt-in, file:// sigue BLOQUEADO (delegado al estricto)", not v, v.reason)

    # ── 7 · 'localhost' declarado resuelve a loopback → PASA (ejercita la ruta de resolución) ──
    gl = declared_target_guard("http://localhost:8210", resolve=True)
    v = gl.check("http://localhost:8210")
    check("[7] 'localhost' declarado (resuelve a 127.0.0.1) PASA", bool(v), v.reason)
    v = gl.check("http://127.0.0.1:8210")  # IP distinta del literal declarado 'localhost'
    check("[7b] el mismo opt-in NO abre la IP literal si se declaró el nombre (host≠) → estricto",
          not v, v.reason)

    # ── 8 · BYPASS por ENCODING (hallado en security-review): la IP de metadata como IPv4-mapped
    #        IPv6 NO se abre. is_private/is_link_local eran True y su string no estaba en el denylist;
    #        ahora se normaliza a la IPv4 y todo el rango link-local queda excluido. ──
    for form in ("http://[::ffff:169.254.169.254]:80", "http://[::ffff:a9fe:a9fe]:80"):
        gmap = declared_target_guard(form, resolve=False)
        v = gmap.check(form)
        check(f"[8] declarar metadata como IPv4-mapped IPv6 NO la abre · {form}", not v, v.reason)
    # y como IP a alcanzar desde un opt-in de loopback (pivote) tampoco:
    v = g.check("http://[::ffff:169.254.169.254]:80/latest/meta-data/")
    check("[8b] con opt-in de loopback, NO se alcanza metadata IPv4-mapped IPv6", not v, v.reason)

    # ── 9 · el opt-in NO resuelve hostnames arbitrarios (cierra el DNS-rebinding, probe 2): sólo
    #        IP literal loopback/privada o el nombre 'localhost'. .local/.internal/dominios → estricto. ──
    for name in ("http://myserver.local:8096", "http://intra.internal:8080", "http://evil.example.com:80"):
        gn = declared_target_guard(name, resolve=False)
        v = gn.check(name)
        check(f"[9] hostname no-localhost → estricto (sin auto-local, sin rebind) · {name}", not v, v.reason)

    print("\n" + ("═" * 72))
    print("RESULTADO:", "ROJO (" + str(len(fails)) + ")" if fails else "VERDE — opt-in TIGHT: sólo el host:port declarado, nada de pivote SSRF")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
