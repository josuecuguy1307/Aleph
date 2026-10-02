#!/usr/bin/env python3
"""verify_arranque_acotado.py — ¿el broker se rinde RÁPIDO cuando no puede servir?

EL AGUJERO QUE CIERRA, medido en un turno real de Oficina el 2026-08-26:

    +  11,6 s   slot_granted   queue_s = 0,0007 s      ← «tenés el slot»
    + 131,7 s   spawned                                 ← 120,1 s DESPUÉS

Los 120,1 s eran `codex_appserver.abrir_sesion(plazo=120.0)` agotándose ENTERO antes de
rendirse. El turno terminó bien —cayó al camino de hoy— pero el usuario pagó **dos minutos
por un broker que no pudo servir**, y eso rompe la única condición que el broker tiene que
cumplir: si se cae, el usuario NO puede esperar más que sin broker.

  A · los TRES adaptadores acotan su arranque con el MISMO presupuesto
  B · el presupuesto es chico de verdad (no 60, no 90, no 120)
  C · y es holgado contra el tiempo SANO que los propios adaptadores documentan
  D · el plazo del TURNO no se tocó: generar tarda lo que tarda
  E · la perilla de entorno manda, y «vacía» no la rompe

    python3 platform/assembler/cli_brain/broker/verify_arranque_acotado.py
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[1]))

from cli_brain.broker import claude_streamjson, codex_appserver, grok_acp   # noqa: E402
from cli_brain.broker.vocabulario import ARRANQUE_S                          # noqa: E402

_F, _OK = [], 0
#: EL TECHO, ESCRITO A MANO. Leerlo de `ARRANQUE_S` sería preguntarle al acusado: con el
#: defecto viejo (120 s) la vara pasaría igual.
TECHO_S = 15.0
#: El peor tiempo SANO que los propios adaptadores documentan (`codex_appserver.py:5`).
SANO_S = 0.394

ADAPTADORES = [("grok_acp", grok_acp.GrokACP),
               ("claude_streamjson", claude_streamjson.ClaudeStreamJson),
               ("codex_appserver", codex_appserver.CodexAppServer)]


def ok(c, t, d=""):
    global _OK
    if c:
        _OK += 1; print(f"  ✅ {t}")
    else:
        _F.append(t); print(f"  ❌ {t}" + (f" — {d}" if d else ""))


def _defecto(cls, metodo):
    firma = inspect.signature(getattr(cls, metodo))
    return firma.parameters["plazo"].default


def main():
    print("=" * 76)
    print("verify_arranque_acotado — ¿el broker se rinde rápido si no puede servir?")
    print("=" * 76)

    print("\n[A] los tres adaptadores acotan su ARRANQUE con el mismo presupuesto")
    vistos = {}
    for nombre, cls in ADAPTADORES:
        for metodo in ("saludar", "abrir_sesion"):
            d = _defecto(cls, metodo)
            vistos[f"{nombre}.{metodo}"] = d
            ok(d <= TECHO_S,
               f"A · {nombre}.{metodo} se rinde en ≤{TECHO_S:.0f}s (es {d}s)",
               f"plazo={d}")
    ok(len(set(vistos.values())) == 1,
       f"A · y es EL MISMO en los seis ({sorted(set(vistos.values()))})")

    print("\n[B] el presupuesto es chico de verdad")
    ok(ARRANQUE_S <= TECHO_S, f"B1 ARRANQUE_S={ARRANQUE_S}s ≤ {TECHO_S:.0f}s")
    ok(ARRANQUE_S not in (60.0, 90.0, 120.0),
       f"B2 y NO es ninguno de los viejos (60/90/120) — es {ARRANQUE_S}")

    print("\n[C] holgado contra el tiempo sano documentado")
    ok(ARRANQUE_S >= SANO_S * 10,
       f"C1 {ARRANQUE_S}s es ≥10× el peor sano documentado ({SANO_S}s) — "
       f"no corta arranques buenos")

    print("\n[D] el plazo del TURNO no se tocó")
    for nombre, cls in ADAPTADORES:
        d = _defecto(cls, "turno")
        ok(d >= 120.0, f"D · {nombre}.turno sigue con plazo largo ({d}s) — generar tarda")

    print("\n[E] la perilla manda, y vacía no rompe")
    import importlib
    # `esperado` es el valor que DEBE quedar. Para la vacía es el default: vacío no
    # significa «cero», significa «no dije nada» — y sobre todo NO puede explotar el
    # import del broker entero, que es lo que hacía `float("")`.
    for crudo, esperado in (("3", 3.0), ("", 8.0), ("no-soy-un-numero", 8.0), ("-5", 8.0)):
        os.environ["PUPPET_CLI_BROKER_ARRANQUE_S"] = crudo
        try:
            voc = importlib.reload(importlib.import_module("cli_brain.broker.vocabulario"))
            ok(voc.ARRANQUE_S == esperado,
               f"E · PUPPET_CLI_BROKER_ARRANQUE_S={crudo!r} → {voc.ARRANQUE_S}s "
               f"(esperado {esperado}s)")
        except Exception as e:                                  # noqa: BLE001
            ok(False, f"E · {crudo!r} EXPLOTA el import ({type(e).__name__})", str(e)[:70])
    os.environ.pop("PUPPET_CLI_BROKER_ARRANQUE_S", None)

    print("\n" + "-" * 76)
    print(f"{_OK} verdes · {len(_F)} rojas")
    for f in _F:
        print(f"   ❌ {f}")
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
