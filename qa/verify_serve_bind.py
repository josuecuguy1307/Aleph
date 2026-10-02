"""verify_serve_bind.py — el servidor del cliente NO escucha en la red.

`product/app/serve.py` bindeaba a `("", PORT)` = 0.0.0.0. No es un detalle de dev: ese
proceso PROXEA `/v1` al backend del usuario — vault, credenciales BYOK, sesión — sin auth
y sin CORS, y con listado de directorio activo (no hay ningún index.html en design/).
Cualquiera en la misma wifi entraba.

Esto NO se verifica leyendo el código: se levanta el server de verdad y se intenta
conectar desde la IP de LAN real de esta máquina. Si el socket acepta, está expuesto.

    ./product/backend/.venv/bin/python qa/verify_serve_bind.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVE = ROOT / "product" / "app" / "serve.py"
PORT = 8709                      # puerto propio, para no pisar un stack vivo

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def ip_lan() -> str | None:
    """La IP real de esta máquina en su red — el punto de vista de un vecino de wifi."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # no manda nada; sólo elige la interfaz
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def alcanza(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def levantar(env_extra: dict | None = None):
    env = {**os.environ, "ALEPH_FRONT_PORT": str(PORT)}
    env.update(env_extra or {})
    p = subprocess.Popen([sys.executable, str(SERVE)], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):                      # esperar a que el socket esté arriba
        if alcanza("127.0.0.1", PORT, 0.3):
            return p
        time.sleep(0.15)
    return p


def main():
    lan = ip_lan()
    print(f"\nIP de LAN de esta máquina: {lan or '(sin red — el caso hostil no se puede probar)'}")

    print("\n[1] DEFAULT (sin ALEPH_BIND) — tiene que escuchar SÓLO en loopback")
    p = levantar()
    try:
        check("responde en 127.0.0.1 (el usuario sí entra)", alcanza("127.0.0.1", PORT))
        if lan:
            check("NO responde en la IP de LAN (el vecino de wifi NO entra)",
                  not alcanza(lan, PORT), f"{lan}:{PORT} aceptó la conexión → EXPUESTO")
        else:
            print("  ⏸ sin IP de LAN: el caso hostil queda SIN PROBAR (se dice, no se asume)")
    finally:
        p.terminate(); p.wait(timeout=10)

    print("\n[2] OPT-IN EXPLÍCITO (ALEPH_BIND=0.0.0.0) — exponer tiene que seguir siendo posible,")
    print("    pero sólo si alguien lo pide a propósito")
    p = levantar({"ALEPH_BIND": "0.0.0.0"})
    try:
        if lan:
            check("con el opt-in SÍ responde en la LAN (la salida de escape existe)",
                  alcanza(lan, PORT), "ni con ALEPH_BIND se puede exponer")
        else:
            print("  ⏸ sin IP de LAN: sin probar")
    finally:
        p.terminate(); p.wait(timeout=10)

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
