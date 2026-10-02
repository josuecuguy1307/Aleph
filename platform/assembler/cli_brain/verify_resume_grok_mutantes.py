#!/usr/bin/env python3
"""verify_resume_grok_mutantes.py — ¿la vara del resume de grok puede dar ROJO?

Copia `platform/` a un temporal, rompe UNA cosa por vez y corre la vara contra la copia.
Cada mutante tiene que morir. `PYTHONDONTWRITEBYTECODE=1` en los hijos: sin eso un `.pyc`
del árbol sano sobrevive a la copia y el mutante corre sin mutar.

Los mutantes de R1/R2 corren en modo `--rapido` (sin turnos reales): son puros y no gastan
cuota. Los de R3/R4 necesitan a grok vivo y se declaran aparte.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[2]
C = "assembler/cli_brain"

MUTANTES = [
    ("M1 · el regex vuelve a NO reconocer «already in use» (la charla queda muerta)",
     f"{C}/grok_cli.py",
     '''                        r"|session id .{0,80}? is already in use)"''',
     '''                        r")"''',
     "R1", True),

    ("M2 · el regex matchea DE MÁS: cualquier error es «sesión perdida»",
     f"{C}/grok_cli.py",
     '''_SESION_RE = re.compile(r"(session .{0,80}not found|no session|unknown session"
                        r"|session id .{0,80}? is already in use)", re.I)''',
     '''_SESION_RE = re.compile(r"(error|session)", re.I)''',
     "R1", True),

    ("M3 · el workdir de sesión deja de separar por dueño y por charla",
     f"{C}/sesiones.py",
     '        h = hashlib.sha256(f"{provider}\\x00{clave}".encode("utf-8")).hexdigest()[:20]',
     '        h = hashlib.sha256(f"{provider}".encode("utf-8")).hexdigest()[:20]',
     "R2", True),
    ("M4 · grok sale de RESUME_PROBADO (no hay resume que medir)",
     f"{C}/sesiones.py",
     '''RESUME_PROBADO = frozenset({"claude_cli", "grok_cli"})''',
     '''RESUME_PROBADO = frozenset({"claude_cli"})''',
     "R3", False),
]


def main() -> int:
    print("=" * 74)
    print("MUTANTES DEL RESUME DE GROK")
    print("=" * 74)
    vivos, saltados = [], []
    for i, (titulo, rel, viejo, nuevo, caso, rapido) in enumerate(MUTANTES, 1):
        if not rapido and os.environ.get("MUTANTES_CON_GROK", "") != "1":
            print(f"\n{titulo}\n  ⏭  necesita turnos reales de grok — "
                  f"correr con MUTANTES_CON_GROK=1")
            saltados.append(titulo)
            continue
        tmp = tempfile.mkdtemp(prefix=f"mut-resume-{i}-")
        dest = os.path.join(tmp, "platform")
        shutil.copytree(_PLATFORM, dest,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        obj = os.path.join(dest, rel)
        src = open(obj).read()
        if src.count(viejo) != 1:
            print(f"\n{titulo}\n  ⚠️  NO SE PUDO APLICAR ({src.count(viejo)}) — inválido")
            vivos.append(titulo + " [no aplicable]")
            shutil.rmtree(tmp, ignore_errors=True)
            continue
        open(obj, "w").write(src.replace(viejo, nuevo))
        cmd = [sys.executable, "-m", "assembler.cli_brain.verify_resume_grok"]
        if rapido:
            cmd.append("--rapido")
        else:
            cmd += ["--charlas", "1", "--plazo", "120"]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                   PUPPET_CLI_EVENTOS=os.path.join(tmp, "e.jsonl"))
        r = subprocess.run(cmd, cwd=dest, capture_output=True, text=True, timeout=1800,
                           env=env)
        rojas = [l.strip() for l in (r.stdout + r.stderr).splitlines()
                 if l.strip().startswith("❌")]
        print(f"\n{titulo}")
        print(f"  rompe [{caso}] · exit={r.returncode} · rojas={len(rojas)}")
        for l in rojas[:3]:
            print(f"      {l[:140]}")
        if r.returncode != 0:
            print("  ✅ MUTANTE MUERTO")
        else:
            print("  ❌ MUTANTE VIVO")
            vivos.append(titulo)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "-" * 74)
    corridos = len(MUTANTES) - len(saltados)
    print(f"{corridos - len(vivos)}/{corridos} mutantes muertos"
          + (f" · {len(saltados)} salteados (necesitan grok)" if saltados else ""))
    for v in vivos:
        print(f"   VIVO: {v}")
    return 1 if vivos else 0


if __name__ == "__main__":
    sys.exit(main())
