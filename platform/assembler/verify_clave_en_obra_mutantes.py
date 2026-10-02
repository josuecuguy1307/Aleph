#!/usr/bin/env python3
"""Mutantes de verify_clave_en_obra — cada uno tiene que MATAR a la vara."""
import shutil, subprocess, sys, os
from pathlib import Path
_AQUI = Path(__file__).resolve().parent
RAIZ = _AQUI.parents[1]
VARA = _AQUI / "verify_clave_en_obra.py"
ST = _AQUI / "sobre_turno.py"
VOC = _AQUI / "cli_brain" / "broker" / "vocabulario.py"

MUTANTES = [
    ("M1 · `campos_del_cuerpo` deja de mandar la clave (vuelve el bug exacto)",
     ST, 'return {"sesion": sesion} if sesion else {}', 'return {}'),
    ("M2 · la manda SIEMPRE, también a bordes que no son de CLIs",
     ST, """    if not es_borde_cli:
        return {}
    _turno, _deadline, sesion = actual()""",
         """    if False:
        return {}
    _turno, _deadline, sesion = actual()"""),
    ("M3 · `dueno_de_clave` toma el campo equivocado (cruza dueños)",
     VOC, '        return partes[1].strip()', '        return partes[0].strip()'),
    ("M4 · el `sacar` no limpia: el sobre se pega al turno siguiente",
     ST, "def sacar(", "def sacar_DESACTIVADO("),
]

def main():
    print("=" * 74); print("MUTANTES · la clave en el camino de obra"); print("=" * 74)
    muertos, vivos = 0, []
    for nombre, arch, viejo, nuevo in MUTANTES:
        print(f"\n{nombre}")
        src = arch.read_text()
        if src.count(viejo) != 1:
            print(f"  ⚠️  INVÁLIDO: el ancla aparece {src.count(viejo)} veces")
            vivos.append(nombre + " (ancla inválida)"); continue
        bak = arch.with_suffix(arch.suffix + ".bak")
        shutil.copy2(arch, bak)
        try:
            arch.write_text(src.replace(viejo, nuevo, 1))
            r = subprocess.run([sys.executable, str(VARA)], capture_output=True,
                               text=True, timeout=120, cwd=str(RAIZ),
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        finally:
            shutil.move(str(bak), str(arch))
        rojas = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("❌")]
        if r.returncode != 0:
            muertos += 1
            print(f"  ✅ MUERTO · exit={r.returncode} · rojas={len(rojas)}")
            for l in rojas[:2]: print(f"      {l}")
        else:
            vivos.append(nombre); print("  ❌ VIVO — la vara pasó con el código roto")
    print("\n" + "-" * 74); print(f"{muertos}/{len(MUTANTES)} mutantes muertos")
    for v in vivos: print(f"   VIVO: {v}")
    return 1 if vivos else 0

if __name__ == "__main__":
    sys.exit(main())
