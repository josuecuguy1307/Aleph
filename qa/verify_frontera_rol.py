"""verify_frontera_rol.py — la frontera cliente / plano de control EXISTE. [Casa 2 · 2.0]

Antes de esto, `main.py` montaba sus 23 routers sin un solo condicional: el mismo binario
servía el webhook de pagos y la memoria del agente. Empaquetar el cliente con PyInstaller
significaba meter el webhook de Dodo en la máquina del usuario.

No se verifica leyendo el código: se IMPORTA la app con cada `ALEPH_ROLE` y se lee la
superficie que realmente publica (`app.openapi()`) — la misma que se sondea contra
producción.

    ./product/backend/.venv/bin/python qa/verify_frontera_rol.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Superficie que NO puede existir en la máquina de un usuario.
SOLO_CONTROL = [
    ("POST", "/v1/payments/webhook/{procesador}"),   # recibe POSTs de afuera
    ("POST", "/v1/payments/checkout"),               # abre la sesión de pago
    ("POST", "/v1/payments/reconcile"),              # corrige el tier contra el procesador
    ("POST", "/v1/billing/webhook/stripe"),
    ("POST", "/v1/billing/checkout"),
]
# Lo que el cliente SÍ necesita: preguntar su plan sin llamar a casa (D1).
AMBOS = [
    ("GET", "/v1/payments/me/tier"),
    ("GET", "/health"),
]

# Se enumera con app.openapi(), NO con app.routes: esta versión de FastAPI mete un
# `_IncludedRouter` perezoso por cada include_router y NO aplana las rutas hijas, así que
# app.routes sólo muestra 7 paths de los ~118 reales. Leerlo mal daba un falso verde
# perfecto: "el cliente no expone el webhook" pasaba porque no se veía NINGUNA ruta.
# openapi() es lo que el servidor realmente publica — la misma superficie que se sondea
# contra producción.
_SNIPPET = r"""
import json, sys, os
sys.path.insert(0, os.environ["ALEPH_ROOT"] + "/product/backend")
sys.path.insert(0, os.environ["ALEPH_ROOT"] + "/platform")
from app.main import app
spec = app.openapi()
rutas = [[m.upper(), p] for p, ops in spec.get("paths", {}).items() for m in ops]
print("___RUTAS___" + json.dumps(rutas))
"""

def rutas_con_rol(rol: str | None) -> set:
    env = {**os.environ, "ALEPH_ROOT": str(ROOT), "PUPPET_WORKERS": "0",
           "SUPABASE_DB_URL": "", "DATABASE_URL": ""}
    if rol is None:
        env.pop("ALEPH_ROLE", None)
    else:
        env["ALEPH_ROLE"] = rol
    out = subprocess.run([sys.executable, "-c", _SNIPPET], env=env, cwd=str(ROOT),
                         capture_output=True, text=True, timeout=180)
    marca = "___RUTAS___"
    linea = next((l for l in out.stdout.splitlines() if l.startswith(marca)), None)
    if linea is None:
        print("  ✗ la app no importó con ALEPH_ROLE=%r" % rol)
        print("   ", (out.stderr or "")[-500:])
        return set()
    return {(m, p) for m, p in json.loads(linea[len(marca):])}


ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1; print(f"  ✓ {label}")
    else:
        fail += 1; print(f"  ✗ {label}  {detail}")


def main() -> int:
    print("\n[1] ALEPH_ROLE=control — el plano de control SÍ sirve pagos")
    ctrl = rutas_con_rol("control")
    check("la app arranca", bool(ctrl), "no importó")
    # GUARDA ANTI-FALSO-VERDE: si la app trae 4 rutas, "no expone el webhook" pasa por
    # motivos equivocados. Prod publica ~118; se exige un piso holgado pero real.
    check(f"la superficie es completa ({len(ctrl)} rutas, no un cascarón)", len(ctrl) > 90,
          "montó demasiado poco → las aserciones de abajo no significarían nada")
    for m, p in SOLO_CONTROL:
        check(f"expone {m} {p}", (m, p) in ctrl)

    print("\n[2] ALEPH_ROLE=client — el Aleph del usuario NO los tiene")
    cli = rutas_con_rol("client")
    check("la app arranca", bool(cli), "no importó")
    for m, p in SOLO_CONTROL:
        check(f"NO expone {m} {p}", (m, p) not in cli,
              "SIGUE EXPUESTO en el binario del usuario")

    print("\n[3] lo que el cliente sí necesita sigue estando")
    for m, p in AMBOS:
        check(f"{m} {p} en client", (m, p) in cli)
        check(f"{m} {p} en control", (m, p) in ctrl)

    print("\n[4] default sin declarar → fail-closed a client")
    sin = rutas_con_rol(None)
    check("la app arranca sin ALEPH_ROLE", bool(sin))
    check("sin rol declarado NO expone el webhook de pagos",
          ("POST", "/v1/payments/webhook/{procesador}") not in sin,
          "el default NO es fail-closed")

    if ctrl and cli:
        print(f"\n  rutas totales — control: {len(ctrl)} · client: {len(cli)} "
              f"· diferencia: {len(ctrl) - len(cli)}")
        solo = sorted(ctrl - cli)
        print("  lo que el cliente NO embarca:")
        for m, p in solo:
            print(f"     {m:6} {p}")

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
