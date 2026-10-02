#!/usr/bin/env python3
"""verify_cola_mutantes.py — ¿la vara de la cola puede dar ROJO?

Copia `platform/` a un temporal, le rompe el mecanismo de UNA forma por vez, y corre
`verify_cola.py` contra la copia rota. **Cada mutante TIENE que morir**: si la vara pasa
en verde con el código roto, la vara no mide eso y hay que decirlo.

Los mutantes no son «corridas previas»: son ediciones al código de producción que
invierten exactamente la decisión que cada caso afirma.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_AQUI = Path(__file__).resolve()
_PLATFORM = _AQUI.parents[2]

CLI = "assembler/cli_brain"


BLOQUE_CORTE_ORIGINAL = """            if on_linea is not None:
                try:
                    on_linea(canal, linea)
                except Exception:                           # noqa: BLE001 — un consumidor
                    pass                                    # que explota no mata la lectura
            # ── EL CORTE ──────────────────────────────────────────────────────────
            # Se pregunta DESPUÉS de entregar, nunca antes: la línea que dispara el corte
            # es la que trae el usage, y tiene que haber pasado por `on_linea` (y por el
            # ledger) antes de que dejemos de leer.
            if corta_ya is not None:
                try:
                    cortar = bool(corta_ya())
                except Exception:                           # noqa: BLE001 — fail-closed:
                    cortar = False                          # si el juez explota, se espera el EOF
                if cortar:
                    cerrado_temprano = True
                    t_corte = time.monotonic()
                    break
"""

BLOQUE_CORTE_MOVIDO = """            if corta_ya is not None:
                try:
                    cortar = bool(corta_ya())
                except Exception:                           # noqa: BLE001
                    cortar = False
                if cortar:
                    cerrado_temprano = True
                    t_corte = time.monotonic()
                    break
            if on_linea is not None:
                try:
                    on_linea(canal, linea)
                except Exception:                           # noqa: BLE001
                    pass
"""

MUTANTES = [
    ("M1 · claude.fin_limpio acepta también el evento terminal de ERROR",
     f"{CLI}/claude_cli.py",
     'if obj.get("is_error") is not False:\n            return False',
     'if "is_error" not in obj:\n            return False',
     "B"),
    ("M2 · el corte se MUEVE a antes de entregar la línea (la de la última línea se pierde)",
     f"{CLI}/base.py",
     BLOQUE_CORTE_ORIGINAL,
     BLOQUE_CORTE_MOVIDO,
     "A"),
    ("M3 · el workdir se borra igual aunque el cosechador sea el dueño",
     f"{CLI}/base.py",
     '            if not _cosecha_manda:\n                _borrar_workdir()',
     '            if True:\n                _borrar_workdir()',
     "D"),
    ("M4 · el cosechador no desregistra el proceso",
     f"{CLI}/base.py",
     '            for h in hilos:\n                h.join(timeout=1.0)\n            _unregister_process(proc)\n            rc = proc.returncode',
     '            for h in hilos:\n                h.join(timeout=1.0)\n            rc = proc.returncode',
     "E"),
    ("M5 · cerrar_turno borra la fila aunque el pid siga vivo",
     f"{CLI}/base.py",
     '        if not en_cosecha:\n            _registro_borrar(t.id)',
     '        if True:\n            _registro_borrar(t.id)',
     "F"),
    ("M6 · el default de fin_limpio deja de ser fail-closed",
     f"{CLI}/base.py",
     'evento terminal dice error, esto devuelve False y el turno se cierra por EOF con el\n        `returncode` REAL, que es lo que los tres `parse_result` consultan en su camino de\n        error. Un `True` de más ahí haría que un fallo dejara de decirse.\n        """\n        return False',
     'evento terminal dice error, esto devuelve False y el turno se cierra por EOF con el\n        `returncode` REAL, que es lo que los tres `parse_result` consultan en su camino de\n        error. Un `True` de más ahí haría que un fallo dejara de decirse.\n        """\n        return True',
     "G"),
    ("M7 · al cortar temprano se devuelve el returncode crudo (None) en vez del 0 del evento",
     f"{CLI}/base.py",
     '    rc = 0 if cerrado_temprano else proc.returncode',
     '    rc = proc.returncode',
     "A"),
    ("M8 · el cosechador NO espera: mata el proceso al cortar",
     f"{CLI}/base.py",
     '            stats.cierre = "evento_terminal"\n            _cosechar(',
     '            stats.cierre = "evento_terminal"\n            _terminate_process(proc)\n            _cosechar(',
     "D"),
]


def main() -> int:
    print("=" * 74)
    print("MUTANTES DE LA COLA — cada uno tiene que MATAR a la vara")
    print("=" * 74)
    vivos = []
    for i, (titulo, rel, viejo, nuevo, caso) in enumerate(MUTANTES, 1):
        tmp = tempfile.mkdtemp(prefix=f"mut-cola-{i}-")
        dest = os.path.join(tmp, "platform")
        shutil.copytree(_PLATFORM, dest,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        objetivo = os.path.join(dest, rel)
        src = open(objetivo).read()
        if src.count(viejo) != 1:
            print(f"\n{titulo}\n  ⚠️  EL MUTANTE NO SE PUDO APLICAR "
                  f"({src.count(viejo)} coincidencias) — mutante inválido, no cuenta")
            vivos.append(titulo + "  [no aplicable]")
            shutil.rmtree(tmp, ignore_errors=True)
            continue
        open(objetivo, "w").write(src.replace(viejo, nuevo))
        r = subprocess.run([sys.executable, os.path.join(dest, rel.replace("base.py", ""),
                                                         "verify_cola.py")
                            if False else os.path.join(dest, CLI, "verify_cola.py")],
                           capture_output=True, text=True, timeout=300)
        salida = r.stdout + r.stderr
        rojas = [l.strip() for l in salida.splitlines() if l.strip().startswith("❌")]
        murio = r.returncode != 0
        print(f"\n{titulo}")
        print(f"  espera romper el caso [{caso}] · exit={r.returncode} · rojas={len(rojas)}")
        for l in rojas[:4]:
            print(f"      {l}")
        if murio:
            print("  ✅ MUTANTE MUERTO (la vara lo cazó)")
        else:
            print("  ❌ MUTANTE VIVO — la vara pasó en verde con el código roto")
            vivos.append(titulo)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "-" * 74)
    print(f"{len(MUTANTES) - len(vivos)}/{len(MUTANTES)} mutantes muertos")
    for v in vivos:
        print(f"   VIVO: {v}")
    return 1 if vivos else 0


if __name__ == "__main__":
    sys.exit(main())
