#!/usr/bin/env python3
"""Mutantes de verify_arranque_acotado — el primero devuelve EL DEFECTO REAL medido."""
import os, shutil, subprocess, sys
from pathlib import Path
_AQUI = Path(__file__).resolve().parent
RAIZ = _AQUI.parents[3]
VARA = _AQUI / "verify_arranque_acotado.py"
VOC = _AQUI / "vocabulario.py"
CDX = _AQUI / "codex_appserver.py"
GRK = _AQUI / "grok_acp.py"

MUTANTES = [
    ("M1 · vuelve el plazo de 120 s de codex ← EL DEFECTO QUE SE MIDIÓ (120,1 s de espera)",
     CDX, "def abrir_sesion(self, ses: Session, plazo: float = ARRANQUE_S) -> None:",
          "def abrir_sesion(self, ses: Session, plazo: float = 120.0) -> None:"),
    ("M2 · sólo UNO de los tres queda acotado (los otros esperan 90 s)",
     GRK, "def abrir_sesion(self, ses: Session, plazo: float = ARRANQUE_S) -> None:",
          "def abrir_sesion(self, ses: Session, plazo: float = 90.0) -> None:"),
    ("M3 · el presupuesto se agranda hasta el viejo",
     VOC, "        return 8.0\n    try:", "        return 60.0\n    try:"),
    ("M4 · el plazo del TURNO se acorta también (rompería la generación)",
     CDX, "              plazo: float = 180.0) -> ResultadoTurno:",
          "              plazo: float = 8.0) -> ResultadoTurno:"),
    # ⚠️ M5 nació INVÁLIDO en su primera forma: sacar el `if not crudo` NO rompía nada
    # porque el `try/except ValueError` de abajo ya atrapa `float("")`. Dos capas, y quitar
    # una no cambia la conducta — o sea el mutante no probaba nada. Se muta la capa que SÍ
    # protege. (Un mutante que no cambia la conducta se ve igual que una vara floja.)
    ("M5 · sin el `except`, la variable vacía o basura explota el import del broker",
     VOC, "    except ValueError:", "    except ZeroDivisionError:"),
]


def main():
    print("=" * 76); print("MUTANTES · el arranque acotado del broker"); print("=" * 76)
    muertos, vivos = 0, []
    for nombre, arch, viejo, nuevo in MUTANTES:
        print(f"\n{nombre}")
        src = arch.read_text()
        if src.count(viejo) != 1:
            print(f"  ⚠️  INVÁLIDO: ancla {src.count(viejo)}×"); vivos.append(nombre); continue
        bak = arch.with_suffix(arch.suffix + ".bak"); shutil.copy2(arch, bak)
        try:
            arch.write_text(src.replace(viejo, nuevo, 1))
            r = subprocess.run([sys.executable, str(VARA)], capture_output=True, text=True,
                               timeout=120, cwd=str(RAIZ),
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        finally:
            shutil.move(str(bak), str(arch))
        rojas = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("❌")]
        if r.returncode != 0:
            muertos += 1; print(f"  ✅ MUERTO · exit={r.returncode} · rojas={len(rojas)}")
            for l in rojas[:2]: print(f"      {l}")
        else:
            vivos.append(nombre); print("  ❌ VIVO — la vara pasó con el código roto")
    print("\n" + "-" * 76); print(f"{muertos}/{len(MUTANTES)} mutantes muertos")
    for v in vivos: print(f"   VIVO: {v}")
    return 1 if vivos else 0


if __name__ == "__main__":
    sys.exit(main())
