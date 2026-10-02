"""test_session_cache.py — el criterio NO NEGOCIABLE de v2, atacado por todos lados.

    "JWT vencido + sin red JAMÁS mata al cliente."

Cada test de acá es un intento distinto de que el cliente eche a un usuario legítimo.
Si alguno pasa a rojo, v2 no se cierra.

    python3 platform/payments/test_session_cache.py     (o pytest)
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ALEPH_SESSION_CACHE_DIR"] = tempfile.mkdtemp(prefix="sess-cache-test-")

from payments import session_cache as sc  # noqa: E402

AHORA = _dt.datetime(2026, 7, 20, 12, 0, tzinfo=_dt.timezone.utc)
CUENTA = "8adc014d-6bd7-4cf6-b2e2-fd838b427247"

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def _sin_red():
    raise ConnectionError("sin red")


def main():
    # ── REGLA 1 · nunca supimos nada ───────────────────────────────────────────
    sc.olvidar()
    i = sc.resolver_identidad(_sin_red, ahora=AHORA)
    check("sin sesión guardada y sin red → anónimo", not i.hay_sesion)
    check("  → y lo dice, no finge", i.degraded and bool(i.mensaje))

    # ── Camino feliz ──────────────────────────────────────────────────────────
    i = sc.resolver_identidad(lambda: CUENTA, ahora=AHORA)
    check("el servidor confirma → hay sesión", i.account_id == CUENTA)
    check("  → sin degradar", i.degraded is False and i.fuente == "remoto")

    # ── REGLA 2 · EL CRITERIO NO NEGOCIABLE ───────────────────────────────────
    despues = AHORA + _dt.timedelta(hours=3)      # el JWT ya venció hace rato
    i = sc.resolver_identidad(_sin_red, ahora=despues, forzar=True)
    check("TOKEN VENCIDO + SIN RED → SIGUE SIENDO ÉL", i.account_id == CUENTA,
          f"dio {i.account_id!r} — el cliente echó a un usuario legítimo")
    check("  → marcado degraded (honesto)", i.degraded is True)
    check("  → fuente cache_offline", i.fuente == "cache_offline")
    check("  → con mensaje que la UI puede mostrar", bool(i.mensaje))

    # sin caducidad dura: ni a los 10 años la red caída lo deslogea
    i = sc.resolver_identidad(_sin_red, ahora=AHORA + _dt.timedelta(days=3650), forzar=True)
    check("SIN RED a los 10 años → sigue siendo él", i.account_id == CUENTA)

    # y da igual CÓMO falle la red
    for modo, fn in (("excepción", _sin_red),
                     ("None", lambda: None),
                     ("string vacío", lambda: ""),
                     ("timeout", lambda: (_ for _ in ()).throw(TimeoutError())),
                     ("basura", lambda: {"account_id": CUENTA}),
                     ("0", lambda: 0)):
        i = sc.resolver_identidad(fn, ahora=despues, forzar=True)
        check(f"red rota por {modo} → NO deslogea", i.account_id == CUENTA,
              f"dio {i.account_id!r}")

    # ── REGLA 3 · un NO con red de por medio SÍ cierra ────────────────────────
    i = sc.resolver_identidad(lambda: False, ahora=despues, forzar=True)
    check("el servidor NIEGA la sesión (401 con red) → cierra EN EL ACTO",
          not i.hay_sesion, f"dio {i.account_id!r} — ignoró una respuesta autoritativa")
    check("  → y borró la sesión guardada", sc.leer() is None)
    # y desde ahí, la red caída ya no lo resucita
    i = sc.resolver_identidad(_sin_red, ahora=despues, forzar=True)
    check("  → tras cerrar, el offline NO lo resucita", not i.hay_sesion)

    # ── La distinción que sostiene todo ───────────────────────────────────────
    sc.guardar(CUENTA, ahora=AHORA)
    i_silencio = sc.resolver_identidad(lambda: None, ahora=despues, forzar=True)
    sc.guardar(CUENTA, ahora=AHORA)
    i_negado = sc.resolver_identidad(lambda: False, ahora=despues, forzar=True)
    check("'no pude preguntar' ≠ 'me dijeron que no'",
          i_silencio.hay_sesion and not i_negado.hay_sesion,
          f"silencio={i_silencio.account_id!r} negado={i_negado.account_id!r}")

    # ── Frescura: no molesta a la red si no hace falta ────────────────────────
    sc.guardar(CUENTA, ahora=AHORA)
    llamadas = []
    i = sc.resolver_identidad(lambda: (llamadas.append(1), CUENTA)[1],
                              ahora=AHORA + _dt.timedelta(minutes=2))
    check("sesión fresca → no revalida", len(llamadas) == 0 and i.fuente == "cache")
    sc.resolver_identidad(lambda: (llamadas.append(1), CUENTA)[1],
                          ahora=AHORA + _dt.timedelta(hours=2))
    check("sesión vieja → sí revalida", len(llamadas) == 1)

    # ── Logout y máquina compartida ───────────────────────────────────────────
    sc.guardar(CUENTA, ahora=AHORA)
    sc.olvidar()
    i = sc.resolver_identidad(_sin_red, ahora=AHORA)
    check("tras logout → anónimo (no revive al usuario anterior)", not i.hay_sesion)

    # ── Robustez del archivo ──────────────────────────────────────────────────
    sc.guardar(CUENTA, ahora=AHORA)
    sc._archivo().write_text("{ roto")
    i = sc.resolver_identidad(_sin_red, ahora=AHORA)
    check("cache corrupto + sin red → anónimo (no explota)", not i.hay_sesion)

    sc.guardar(CUENTA, ahora=AHORA)
    p = sc._archivo()
    modo = oct(p.stat().st_mode)[-3:]
    check("el archivo de sesión NO es legible por otros usuarios (0600)",
          modo == "600", f"permisos={modo}")

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


def test_session_cache():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
