#!/usr/bin/env python3
"""verify_cinturon_vivo_mutantes.py — cada mutante tiene que MATAR a la vara.

La vara no se juzga por pasar en verde: se juzga por no poder pasar con el código roto.
Cada mutante rompe UNA cosa distinta y se espera que la vara caiga por el motivo correcto.

    python3 platform/assembler/verify_cinturon_vivo_mutantes.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
RAIZ = _AQUI.parents[1]
VARA = _AQUI / "verify_cinturon_vivo.py"

ASM = _AQUI / "recipe_assembler.py"
EST = RAIZ / "product" / "app" / "design" / "sala-v2" / "agui" / "estados.js"

MUTANTES = [
    ("M1 · el backend no emite `belt_starting` (vuelve el silencio de 39 s)",
     ASM, 'on_event({"type": "belt_starting", "kind": "belt",',
          'on_event({"type": "NO_SALE", "kind": "belt",'),

    ("M2 · `belt_starting` sale DESPUÉS del cinturón (tarde: ya no tapa nada)",
     ASM, """    _t_cinturon = time.time()
    if on_event:""",
          """    _t_cinturon = time.time()
    if False:"""),

    ("M3 · `belt_ready` viaja sin las tools reales (el frente cuenta 0)",
     ASM, '"tools": registry.tool_names(),', '"tools": [],'),

    ("M4 · el `ms` no se mide: se declara en 0",
     ASM, '"ms": int((time.time() - _t_cinturon) * 1000)}', '"ms": 0}'),

    ("M9 · `belt_starting` sale de la taxonomía (el EventLog lo tira MUDO) ← EL BUG REAL",
     RAIZ / "platform" / "flywheel" / "events_replay.py",
     '    "belt_starting",\n    "belt_ready",', '    "belt_ready",'),

    ("M5 · la máquina no consume `aleph.cinturon` (el evento llega y no se pinta)",
     EST, '      case "aleph.cinturon":', '      case "aleph.cinturon_NO":'),

    ("M6 · el número se inventa cuando no viene (aparece un «(0)» falso)",
     EST, 'texto = texto.replace("{piezas}", n ? ` (${n})` : "");',
          'texto = texto.replace("{piezas}", ` (${n ?? 0})`);'),

    ("M7 · `listo:true` no devuelve a «Pensando…» (la línea se queda clavada)",
     EST, '          if (this.estado === ESTADO.CINTURON) this._ir(ESTADO.PENSANDO);',
          '          if (false) this._ir(ESTADO.PENSANDO);'),

    ("M8 · el copy pierde el dato del salto (vuelve a entrar sólo `servicio`)",
     EST, 'texto: copyDe(estado, { ...(datos || {}), servicio: this.servicio }),',
          'texto: copyDe(estado, { servicio: this.servicio }),'),
]


def main() -> int:
    print("=" * 74)
    print("MUTANTES DEL CINTURÓN VIVO — cada uno tiene que MATAR a la vara")
    print("=" * 74)
    muertos, vivos = 0, []
    for nombre, archivo, viejo, nuevo in MUTANTES:
        print(f"\n{nombre}")
        src = archivo.read_text()
        if src.count(viejo) != 1:
            print(f"  ⚠️  MUTANTE INVÁLIDO: el ancla aparece {src.count(viejo)} veces")
            vivos.append(nombre + " (ancla inválida)")
            continue
        respaldo = archivo.with_suffix(archivo.suffix + ".bak")
        shutil.copy2(archivo, respaldo)
        try:
            archivo.write_text(src.replace(viejo, nuevo, 1))
            r = subprocess.run([sys.executable, str(VARA)], capture_output=True,
                               text=True, timeout=300, cwd=str(RAIZ),
                               env={**__import__("os").environ,
                                    "PYTHONDONTWRITEBYTECODE": "1"})
        finally:
            shutil.move(str(respaldo), str(archivo))
        rojas = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("❌")]
        if r.returncode != 0:
            muertos += 1
            print(f"  ✅ MUTANTE MUERTO · exit={r.returncode} · rojas={len(rojas)}")
            for l in rojas[:3]:
                print(f"      {l}")
        else:
            vivos.append(nombre)
            print(f"  ❌ MUTANTE VIVO — la vara pasó en verde con el código roto")
    print("\n" + "-" * 74)
    print(f"{muertos}/{len(MUTANTES)} mutantes muertos")
    for v in vivos:
        print(f"   VIVO: {v}")
    return 1 if vivos else 0


if __name__ == "__main__":
    sys.exit(main())
