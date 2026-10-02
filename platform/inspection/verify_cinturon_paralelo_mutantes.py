#!/usr/bin/env python3
"""verify_cinturon_paralelo_mutantes.py — ¿la vara del cinturón puede dar ROJO?"""
from __future__ import annotations
import os, shutil, subprocess, sys, tempfile
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[1]

MUTANTES = [
    ("M1 · el cliente viejo vuelve a NO exponer su pid (el diff serializa el handshake)",
     "assembler/assembler.py",
     '''    @property
    def pid(self):''',
     '''    @property
    def _pid_oculto(self):''',
     "A"),

    ("M2 · el lock del diff vuelve a cubrir `start()` entero",
     "inspection/dueno.py",
     '''            if hasattr(srv, "al_spawnear"):
                srv.al_spawnear(_cerrar_diff)''',
     '''            pass''',
     "A (con cliente sin pid)"),

    ("M3 · el lock NO se suelta si el arranque falla",
     "inspection/dueno.py",
     '''            finally:
                # Si el aviso no llegó (servidor sin la costura, o un fallo antes del
                # spawn), el diff se cierra acá y el lock se suelta igual.
                _cerrar_diff()''',
     '''            finally:
                pass''',
     "D"),

    ("M4 · el fixture deja de dormir: la vara ya no puede distinguir fila de paralelo",
     "inspection/fixtures_cinturon/mcp_lento.py",
     '''            time.sleep(_DORMIR)                 # ← EL RETARDO, que es todo el fixture''',
     '''            pass''',
     "A (auto-control)"),

    ("M5 · el diff deja de atribuir pids (el barrido queda ciego)",
     "inspection/dueno.py",
     '''            con.pids = _diff["pids"] or []''',
     '''            con.pids = []''',
     "B"),
]


def main() -> int:
    print("=" * 74); print("MUTANTES DEL CINTURÓN PARALELO"); print("=" * 74)
    vivos = []
    for i, (titulo, rel, viejo, nuevo, caso) in enumerate(MUTANTES, 1):
        tmp = tempfile.mkdtemp(prefix=f"mut-cint-{i}-")
        dest = os.path.join(tmp, "platform")
        shutil.copytree(_PLATFORM, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        obj = os.path.join(dest, rel)
        src = open(obj).read()
        if src.count(viejo) != 1:
            print(f"\n{titulo}\n  ⚠️  NO SE PUDO APLICAR ({src.count(viejo)}) — inválido")
            vivos.append(titulo + " [no aplicable]"); shutil.rmtree(tmp, ignore_errors=True); continue
        open(obj, "w").write(src.replace(viejo, nuevo))
        r = subprocess.run([sys.executable, "-m", "inspection.verify_cinturon_paralelo"],
                           cwd=dest, capture_output=True, text=True, timeout=900,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        rojas = [l.strip() for l in (r.stdout + r.stderr).splitlines() if l.strip().startswith("❌")]
        print(f"\n{titulo}")
        print(f"  rompe [{caso}] · exit={r.returncode} · rojas={len(rojas)}")
        for l in rojas[:3]: print(f"      {l[:140]}")
        if r.returncode != 0:
            print("  ✅ MUTANTE MUERTO")
        else:
            print("  ❌ MUTANTE VIVO"); vivos.append(titulo)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "-" * 74)
    print(f"{len(MUTANTES)-len(vivos)}/{len(MUTANTES)} mutantes muertos")
    for v in vivos: print(f"   VIVO: {v}")
    return 1 if vivos else 0


if __name__ == "__main__":
    sys.exit(main())
