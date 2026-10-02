#!/usr/bin/env python3
"""verify_carril_auxiliar_mutantes.py — ¿la vara del carril puede dar ROJO?

Copia `platform/` a un temporal, rompe UNA cosa por vez, corre la vara contra la copia.
`PYTHONDONTWRITEBYTECODE=1` en los hijos: sin eso un `.pyc` del árbol sano sobrevive a la
copia y el mutante corre sin mutar.
"""
from __future__ import annotations

import os, shutil, subprocess, sys, tempfile
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[2]
C = "assembler/cli_brain"

MUTANTES = [
    ("M1 · el carril no existe: el auxiliar vuelve a compartir el techo del oficio",
     f"{C}/slots.py",
     '''                if aux:''',
     '''                if False:''',
     "A"),

    ("M2 · 🔴 el clasificador AL REVÉS: el OFICIO se iría por el carril auxiliar",
     f"{C}/server.py",
     '''        _es_auxiliar = not _tools''',
     '''        _es_auxiliar = bool(_tools)''',
     "G"),

    ("M3 · el auxiliar suma al techo del oficio (rompe el tope de la cuenta)",
     f"{C}/slots.py",
     '''                    hay_provider = self._aux_en_vuelo.get(pid, 0) < techo_pid
                    if hay_provider:
                        self._aux_en_vuelo[pid] = self._aux_en_vuelo.get(pid, 0) + 1
                        return''',
     '''                    hay_provider = self._aux_en_vuelo.get(pid, 0) < techo_pid
                    if hay_provider:
                        self._aux_en_vuelo[pid] = self._aux_en_vuelo.get(pid, 0) + 1
                        self._activos += 1
                        return''',
     "B/D"),

    ("M4 · el carril deja de decirse en `estado()`",
     f"{C}/slots.py",
     '''                "aux_en_vuelo": sorted(self._aux_en_vuelo),''',
     '''                "aux_en_vuelo": [],''',
     "D"),

    ("M5 · `soltar` no libera el carril: se tapa solo",
     f"{C}/slots.py",
     '''                n = self._aux_en_vuelo.get(pid, 0)
                if n > 0:
                    if n == 1:
                        self._aux_en_vuelo.pop(pid, None)''',
     '''                n = self._aux_en_vuelo.get(pid, 0)
                if n > 0:
                    if n == 999:
                        self._aux_en_vuelo.pop(pid, None)''',
     "C/E"),

    ("M6 · el carril no tiene techo: los títulos se apilan",
     f"{C}/slots.py",
     '''_MAX_AUX_POR_PROVIDER = _techo_aux()''',
     '''_MAX_AUX_POR_PROVIDER = 99''',
     "C"),

    ("M7 · la perilla se lee con `or` (vacío vuelve al default y no apaga)",
     f"{C}/slots.py",
     '''    crudo = os.environ.get("PUPPET_CLI_SLOTS_AUX", "1").strip()
    if crudo == "":
        return 0                                   # explícitamente vacío = apagado''',
     '''    crudo = (os.environ.get("PUPPET_CLI_SLOTS_AUX") or "1").strip()''',
     "F"),

    ("M7b · el `int()` pelado: la variable vacía revienta el import",
     f"{C}/slots.py",
     '''    crudo = os.environ.get("PUPPET_CLI_SLOTS_AUX", "1").strip()
    if crudo == "":
        return 0                                   # explícitamente vacío = apagado
    try:
        return max(0, int(crudo))
    except ValueError:
        print(f"[slots] PUPPET_CLI_SLOTS_AUX={crudo!r} no es un número; uso 1",
              file=sys.stderr, flush=True)
        return 1''',
     '''    return int(os.environ.get("PUPPET_CLI_SLOTS_AUX", "1"))''',
     "F"),

    ("M8 · el llamador se olvida UN `soltar` (el carril se filtra en un camino)",
     f"{C}/server.py",
     '''            _slots.SLOTS.soltar(provider.provider_id, auxiliar=_es_auxiliar)''',
     '''            _slots.SLOTS.soltar(provider.provider_id)''',
     "G"),
]


def main() -> int:
    print("=" * 74)
    print("MUTANTES DEL CARRIL AUXILIAR")
    print("=" * 74)
    vivos = []
    for i, (titulo, rel, viejo, nuevo, caso) in enumerate(MUTANTES, 1):
        tmp = tempfile.mkdtemp(prefix=f"mut-carril-{i}-")
        dest = os.path.join(tmp, "platform")
        shutil.copytree(_PLATFORM, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        obj = os.path.join(dest, rel)
        src = open(obj).read()
        n = src.count(viejo)
        if n < 1:
            print(f"\n{titulo}\n  ⚠️  NO SE PUDO APLICAR (0 coincidencias) — inválido")
            vivos.append(titulo + " [no aplicable]")
            shutil.rmtree(tmp, ignore_errors=True); continue
        # M8 muta SÓLO la primera aparición a propósito: el punto es que se olvide UNA
        src = src.replace(viejo, nuevo, 1) if i == 8 else src.replace(viejo, nuevo)
        open(obj, "w").write(src)
        r = subprocess.run([sys.executable, "-m", "assembler.cli_brain.verify_carril_auxiliar"],
                           cwd=dest, capture_output=True, text=True, timeout=600,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        rojas = [l.strip() for l in (r.stdout + r.stderr).splitlines() if l.strip().startswith("❌")]
        print(f"\n{titulo}")
        print(f"  rompe [{caso}] · exit={r.returncode} · rojas={len(rojas)}")
        for l in rojas[:3]:
            print(f"      {l[:150]}")
        if r.returncode != 0:
            print("  ✅ MUTANTE MUERTO")
        else:
            print("  ❌ MUTANTE VIVO")
            vivos.append(titulo)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "-" * 74)
    print(f"{len(MUTANTES) - len(vivos)}/{len(MUTANTES)} mutantes muertos")
    for v in vivos:
        print(f"   VIVO: {v}")
    return 1 if vivos else 0


if __name__ == "__main__":
    sys.exit(main())
