#!/usr/bin/env python3
"""verify_regla_loopback.py — LA VARA DE LA REGLA DE LOOPBACK (§6.a).
Regla: platform/browser/REGLA-LOOPBACK.md · código: platform/browser/loopback.py

QUÉ MIDE Y POR QUÉ PUEDE DAR ROJO
---------------------------------
Ocho de los nueve casos afirman una DENEGACIÓN. Aflojar el guard los pone en rojo, no en
verde silencioso. El noveno (caso 2) es el único que afirma un «sí», y está para que la
regla no pueda volverse inútil negando todo.

EL FIXTURE NO SIEMBRA EL REGISTRO. Es la trampa de esta semana —«tres casos salieron verdes
porque el fixture traía una pista»—: acá el registro arranca VACÍO y cada caso que necesita
un puerto lo anota explícitamente. Un caso que se olvide de anotar da deny, que es lo
correcto, y no un verde prestado.

Y AL FINAL LA VARA SE PRUEBA CAYENDO: re-corre los casos 1, 3 y 7 contra un guard
deliberadamente aflojado. Si ahí no dan rojo, la vara no mide nada y lo dice.

Correr:  python3 qa/verify_regla_loopback.py
"""
import sys, os, socket
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "platform"))
from browser import loopback as LB                                          # noqa: E402

_fallos = []
def caso(n, desc, cond, detalle=""):
    print(("  ✓ " if cond else "  ✗ ") + f"[{n}] {desc}" + (f"   {detalle}" if detalle and not cond else ""))
    if not cond: _fallos.append(f"[{n}] {desc}")

def deny(url, run="run-A"):
    v = LB.permitir(url, run_id=run); return (not v.ok), v
def allow(url, run="run-A"):
    v = LB.permitir(url, run_id=run); return v.ok, v

# ── el escenario: Aleph vive en 61000; el run levantó 61234 y NADA MÁS ────────────────
SIDECAR, MIO, AJENO = 61000, 61234, 61999
LB.fijar_sidecar(SIDECAR)
LB.anotar("run-A", MIO, pid=None)

# ¿resuelve localtest.me a loopback en esta máquina? Si no, el caso 3 NO se puede medir.
def _resuelve_a_loopback(h):
    try:
        return any(__import__("ipaddress").ip_address(i[4][0]).is_loopback
                   for i in socket.getaddrinfo(h, None))
    except Exception:
        return False

print("REGLA DE LOOPBACK — casos\n")
ok, v = deny(f"http://127.0.0.1:{AJENO}/");           caso(1, "puerto NO registrado → deny", ok, v.causa)
ok, v = allow(f"http://127.0.0.1:{MIO}/");            caso(2, "puerto registrado → allow", ok, v.causa + " " + v.detalle)

_HOST_DNS = "localtest.me"
if _resuelve_a_loopback(_HOST_DNS):
    ok, v = deny(f"http://{_HOST_DNS}:{AJENO}/");     caso(3, f"{_HOST_DNS} (DNS→loopback) puerto ajeno → deny", ok, v.causa)
else:
    print(f"  ~ [3] [no medible] {_HOST_DNS} no resuelve a loopback desde acá (sin red o DNS filtrado);")
    print( "        el caso que destapa «se dejó de resolver DNS» NO se pudo correr.")

LB.anotar("run-A", 80)                     # se registra a mano para probar que NO alcanza
ok, v = deny("http://169.254.169.254/");              caso(4, "metadata de nube, aun registrada → deny", ok, v.causa)
LB.desanotar("run-A", 80)

LB.anotar("run-A", 8080)
ok, v = deny("http://192.168.1.1:8080/");             caso(5, "LAN privada, aun registrada → deny", ok, v.causa)
LB.desanotar("run-A", 8080)

LB.anotar("run-A", SIDECAR)                # el peor caso: alguien registra el sidecar
ok, v = deny(f"http://127.0.0.1:{SIDECAR}/v1/");      caso(6, "el sidecar de Aleph, aun registrado → deny", ok, v.causa)
LB.desanotar("run-A", SIDECAR)

v = LB.permitir(f"http://127.0.0.1:{MIO}/", run_id=None)
caso(7, "sin run_id → deny (fail-closed)", not v.ok, v.causa)

ok, v = deny("file:///etc/passwd");                   caso(8, "esquema no http(s) → deny", ok, v.causa)

# ── R6 · el guard de inspección NO se aflojó ──────────────────────────────────────────
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from inspection.loop.guard import PublicHTTPGuard                       # noqa: E402
    gv = PublicHTTPGuard().check("http://127.0.0.1/")
    negado = not getattr(gv, "allowed", getattr(gv, "ok", True))
    caso(9, "R6 · el guard de inspección sigue negando loopback", negado, repr(gv))
except Exception as e:
    print(f"  ~ [9] [no medible] no pude cargar PublicHTTPGuard: {type(e).__name__}: {e}")

# ── LA PRUEBA DE QUE LA VARA PUEDE DAR ROJO ───────────────────────────────────────────
print("\nPRUEBA DE CAÍDA — los mismos casos contra un guard aflojado")
_orig = LB.permitir
def _aflojado(url, *, run_id):                 # el error típico: «abro loopback y listo»
    from urllib.parse import urlsplit
    h = urlsplit(url).hostname or ""
    if h in ("127.0.0.1", "localhost", "::1") or h.endswith(".localtest.me") or h == "localtest.me":
        return LB.Veredicto(True, "ok", "", "aflojado")
    return _orig(url, run_id=run_id)
LB.permitir = _aflojado
rojos = 0
for n, u, r in ((1, f"http://127.0.0.1:{AJENO}/", "run-A"),
                (3, f"http://{_HOST_DNS}:{AJENO}/", "run-A"),
                (7, f"http://127.0.0.1:{MIO}/", None)):
    if n == 3 and not _resuelve_a_loopback(_HOST_DNS):
        print(f"  ~ caso {n}: [no medible] (mismo motivo que arriba)"); continue
    v = LB.permitir(u, run_id=r)
    rojo = v.ok                                # con el guard aflojado, DEBE pasar ⇒ rojo
    print(("  ✓ " if rojo else "  ✗ ") + f"caso {n} da ROJO con el guard aflojado")
    rojos += 1 if rojo else 0
LB.permitir = _orig
esperados = 2 if not _resuelve_a_loopback(_HOST_DNS) else 3
if rojos < esperados:
    _fallos.append(f"LA VARA NO MIDE: sólo {rojos}/{esperados} casos dieron rojo con el guard aflojado")
    print(f"\n  ⚠️  LA VARA NO MIDE NADA: {rojos}/{esperados} rojos con el guard aflojado")
else:
    print(f"\n  → {rojos}/{esperados} rojos con el guard aflojado: la vara PUEDE fallar.")

print("\n" + ("PASS" if not _fallos else "FAIL: " + " · ".join(_fallos)))
sys.exit(1 if _fallos else 0)
