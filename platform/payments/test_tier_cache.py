"""test_tier_cache.py — el local-first, blindado. Step 5 · Casa 1 · P6.

Criterio de aceptación de persona usuaria: "sin red, el cliente sigue con la última sesión/tier
conocido y degrada honesto, jamás cierra la puerta por un token expirado."

Cada test de acá es una forma distinta de intentar que el cliente cierre la puerta.

    python3 platform/payments/test_tier_cache.py     (o pytest)
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="tier-cache-test-")
os.environ["ALEPH_TIER_CACHE_DIR"] = _TMP

from payments import tier_cache as tc  # noqa: E402

AHORA = _dt.datetime(2026, 7, 20, 12, 0, tzinfo=_dt.timezone.utc)
CUENTA = "cuenta-de-prueba-p6"

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def _limpiar():
    tc.olvidar(CUENTA)


def _revienta():
    raise ConnectionError("sin red")


def main():
    # ── REGLA 1 · nunca supimos nada → free (fail-closed donde no duele) ────────
    _limpiar()
    v = tc.resolver_tier(CUENTA, _revienta, ahora=AHORA)
    check("sin cache y sin red → free", v.tier == "free", f"dio {v.tier!r}")
    check("  → y lo dice honesto (degraded + mensaje)", v.degraded and v.mensaje)
    check("  → fuente 'sin_dato' (no finge haber consultado)", v.fuente == "sin_dato")

    # ── Camino feliz: el remoto responde y manda ───────────────────────────────
    _limpiar()
    v = tc.resolver_tier(CUENTA, lambda: "basico", ahora=AHORA)
    check("remoto responde 'basico' → premium", v.tier == "basico" and v.es_premium)
    check("  → sin degradar (es dato fresco)", v.degraded is False)
    check("  → quedó persistido", (tc.leer(CUENTA) or {}).get("tier") == "basico")

    # ── REGLA 2 · EL CRITERIO DE ACEPTACIÓN ────────────────────────────────────
    v = tc.resolver_tier(CUENTA, _revienta, ahora=AHORA + _dt.timedelta(days=2))
    check("CONOCIDO premium + SIN RED → SIGUE premium", v.tier == "basico",
          f"dio {v.tier!r} — le cortó el producto a alguien que pagó")
    check("  → marcado degraded (honesto, no finge certeza)", v.degraded is True)
    check("  → fuente 'cache_offline'", v.fuente == "cache_offline")
    check("  → con mensaje explicando por qué", bool(v.mensaje))

    # Sin caducidad dura: ni a los 10 años la red caída revoca.
    v = tc.resolver_tier(CUENTA, _revienta, ahora=AHORA + _dt.timedelta(days=3650))
    check("SIN RED a los 10 años → SIGUE premium (no hay caducidad dura)",
          v.tier == "basico", f"dio {v.tier!r}")

    # Y da igual CÓMO falle la red: excepción, None, string vacío, basura.
    for modo, fn in (("excepción", _revienta),
                     ("None", lambda: None),
                     ("string vacío", lambda: ""),
                     ("timeout", lambda: (_ for _ in ()).throw(TimeoutError())),
                     ("basura no-str", lambda: {"tier": "free"})):
        v = tc.resolver_tier(CUENTA, fn, ahora=AHORA + _dt.timedelta(days=2))
        check(f"red rota por {modo} → NO revoca", v.tier == "basico",
              f"dio {v.tier!r}")

    # ── REGLA 3 · una respuesta EXITOSA manda, incluso para degradar ───────────
    v = tc.resolver_tier(CUENTA, lambda: "free", ahora=AHORA + _dt.timedelta(days=2))
    check("el servidor dice 'free' → degrada EN EL ACTO", v.tier == "free",
          f"dio {v.tier!r} — ignoró una respuesta autoritativa")
    check("  → sin marcar degraded (es una certeza, no una suposición)",
          v.degraded is False)
    check("  → y el cache quedó actualizado a free",
          (tc.leer(CUENTA) or {}).get("tier") == "free")
    # y desde ahí, la red caída ya no lo devuelve a premium
    v = tc.resolver_tier(CUENTA, _revienta, ahora=AHORA + _dt.timedelta(days=3))
    check("  → tras degradar, el offline NO lo resucita a premium", v.tier == "free")

    # ── Frescura: no molesta a la red si no hace falta ─────────────────────────
    _limpiar()
    tc.resolver_tier(CUENTA, lambda: "basico", ahora=AHORA)
    llamadas = []

    def _contando():
        llamadas.append(1)
        return "basico"

    tc.resolver_tier(CUENTA, _contando, ahora=AHORA + _dt.timedelta(minutes=5))
    check("dato fresco → no consulta la red", len(llamadas) == 0)
    tc.resolver_tier(CUENTA, _contando, ahora=AHORA + _dt.timedelta(days=2))
    check("dato viejo → sí consulta", len(llamadas) == 1)
    tc.resolver_tier(CUENTA, _contando, ahora=AHORA, forzar_remoto=True)
    check("forzar_remoto ignora la frescura", len(llamadas) == 2)

    # ── Aislamiento entre cuentas (misma máquina, dos usuarios) ────────────────
    tc.olvidar("otra-cuenta")
    tc.resolver_tier(CUENTA, lambda: "basico", ahora=AHORA)
    v = tc.resolver_tier("otra-cuenta", _revienta, ahora=AHORA)
    check("otra cuenta NO hereda el premium de la primera", v.tier == "free",
          f"dio {v.tier!r} — filtró plan entre cuentas")

    # ── Logout no deja el plan del anterior ────────────────────────────────────
    tc.resolver_tier(CUENTA, lambda: "basico", ahora=AHORA)
    tc.olvidar(CUENTA)
    v = tc.resolver_tier(CUENTA, _revienta, ahora=AHORA)
    check("tras olvidar() (logout) → vuelve a free", v.tier == "free")

    # ── Robustez del archivo ───────────────────────────────────────────────────
    tc.resolver_tier(CUENTA, lambda: "basico", ahora=AHORA)
    p = tc._archivo(CUENTA)
    p.write_text("{ esto no es json")
    v = tc.resolver_tier(CUENTA, _revienta, ahora=AHORA)
    check("cache corrupto + sin red → free (no explota)", v.tier == "free")

    p.write_text('{"tier": "", "confirmado_at": "no-es-fecha"}')
    v = tc.resolver_tier(CUENTA, _revienta, ahora=AHORA)
    check("cache con campos basura → free (no explota)", v.tier == "free")

    # un tier inventado en el archivo no otorga premium por sí solo
    tc.guardar(CUENTA, "premium", ahora=AHORA)      # 'premium' NO es un tier válido
    v = tc.resolver_tier(CUENTA, _revienta, ahora=AHORA)
    check("un tier inválido guardado a mano NO cuenta como premium",
          v.es_premium is False, f"es_premium={v.es_premium} tier={v.tier!r}")

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


def test_tier_cache():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
