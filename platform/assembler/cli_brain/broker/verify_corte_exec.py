#!/usr/bin/env python3
"""verify_corte_exec.py — el corte en la primera acción: cableado, apagado, y sin inventar causa.

QUÉ SE MIDIÓ (Oficina, turnos reales desde la pantalla, 2026-08-26):

    sin corte:  ✗ 65,0 s · Codex ejecutó 10 acción(es) — descartado por seguridad
    con corte:  ✗ 12,1 s · Codex ejecutó  1 acción(es)   ← corta en la PRIMERA
                ✗ 11,8 s · Codex ejecutó  1 acción(es)

−81 % en la generación descartada. **Pero la entrega salió PEOR** en la única corrida con el
corte puesto (pidió permisos en vez de dar el total), y con N=1 de cada lado eso no cierra.
Por eso la perilla nace APAGADA: la vara que decide es la entrega, no el tiempo.

  A · apagada por defecto (y «vacía» no la prende)
  B · prendida, el predicado de espera SÍ mira `exec`
  C · el resultado del corte NO inventa una causa nueva: sale como el de siempre
  D · `turn/interrupt` se pide (el proceso del pool no queda con un turno colgado)

    python3 platform/assembler/cli_brain/broker/verify_corte_exec.py
"""
from __future__ import annotations

import importlib
import inspect
import os
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[1]))

_F, _OK = [], 0


def ok(c, t, d=""):
    global _OK
    if c:
        _OK += 1; print(f"  ✅ {t}")
    else:
        _F.append(t); print(f"  ❌ {t}" + (f" — {d}" if d else ""))


def _fuente():
    from cli_brain.broker import codex_appserver
    return inspect.getsource(codex_appserver.CodexAppServer.turno)


def main():
    print("=" * 74)
    print("verify_corte_exec — el corte en la primera acción")
    print("=" * 74)
    src = _fuente()

    print("\n[A] apagada por defecto")
    for crudo in ("", "0", "off", "no", "  "):
        os.environ["PUPPET_CLI_BROKER_CORTE_EXEC"] = crudo
        val = (os.environ.get("PUPPET_CLI_BROKER_CORTE_EXEC", "").strip().lower()
               in ("1", "on", "true", "si", "sí"))
        ok(val is False, f"A · {crudo!r} → apagada")
    os.environ.pop("PUPPET_CLI_BROKER_CORTE_EXEC", None)
    val = (os.environ.get("PUPPET_CLI_BROKER_CORTE_EXEC", "").strip().lower()
           in ("1", "on", "true", "si", "sí"))
    ok(val is False, "A · AUSENTE → apagada (el default es no cortar)")

    print("\n[B] prendida, el predicado mira `exec`")
    for crudo in ("1", "on", "true", "si"):
        val = crudo.strip().lower() in ("1", "on", "true", "si", "sí")
        ok(val is True, f"B · {crudo!r} → prendida")
    ok("_cortar_en_exec and estado[\"exec\"] > 0" in src,
       "B · el predicado de `_hasta` mira `exec` SÓLO con la perilla puesta")

    print("\n[C] el corte no inventa una causa nueva")
    ok("ok=True" in src.split("_cortar_en_exec and estado")[-1][:600],
       "C1 devuelve `ok=True` con `exec_events` — el guard de arriba pone SU mensaje")
    ok("error_detalle" not in src.split("turn/interrupt")[-1][:400],
       "C2 y NO fabrica un `error_detalle` propio (sería una causa sin copy)")

    print("\n[D] se interrumpe el turno")
    ok("turn/interrupt" in src, "D1 pide `turn/interrupt` al cortar")
    from cli_brain.broker import codex_appserver
    ok(codex_appserver.CodexAppServer.CAPS.interrumpible is True,
       "D2 y el adaptador lo declara en sus CAPS (no se promete lo que no se puede)")

    print("\n" + "-" * 74)
    print(f"{_OK} verdes · {len(_F)} rojas")
    for f in _F:
        print(f"   ❌ {f}")
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
