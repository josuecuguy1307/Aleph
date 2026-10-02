#!/usr/bin/env python3
"""higiene_store.py — LAS VARAS NO DEJAN BASURA EN EL STORE DEL CLI.

EL AGUJERO, MEDIDO (2026-08-08, `~/.claude/projects/`): **37 directorios huérfanos**
—22 `aleph-cli-brain-*`, 8 `vara-f2e-*`, 7 `aleph-f6-datos-*`— todos vacíos salvo un
`memory/` sin archivos. Los 22 primeros nacieron **anoche** (23:59-00:59), o sea que el
agujero seguía abierto. En la sesión del 2026-08-06 se barrieron 387 a mano.

DE DÓNDE SALEN. `cli_brain/base.py:1046`:

    workdir = getattr(sesion, "workdir", None) or tempfile.mkdtemp(prefix="aleph-cli-brain-")

Sin sesión persistente, cada `invoke` abre un `mkdtemp` y lo borra al terminar. Pero el
CLI, al correr con ese cwd, crea **su propia entrada espejo** en `~/.claude/projects/`.
El `finally` de la vara borra el workdir; el espejo queda. No es una vara sola: es toda
vara que spawnee un turno del cli_brain.

  ══ POR QUÉ EL SLUG SE DERIVA Y NO SE ADIVINA ═══════════════════════════════════════
  El nombre del espejo lo calcula el CLI: **todo lo no alfanumérico → `-`, UNO por
  carácter, sin colapsar**. Ésa es la regla que costó F4d (antes se traducía sólo `/`, y
  el bug sobrevivió a su propia vara justamente porque un `mkdtemp` es el único path
  «limpio» donde las dos reglas coinciden). Acá se importa `sesiones.slug_de` —la
  función REAL— en vez de reimplementarla: una copia se desincroniza y vuelve el bug.

  ══ LOS DOS CANDADOS ════════════════════════════════════════════════════════════════
  Este módulo BORRA directorios del store del usuario, donde también viven sus
  conversaciones reales. Dos condiciones, ambas obligatorias:

    1. **nacido en un temporal** — el nombre empieza con el slug de un directorio
       temporal del sistema (`tempfile.gettempdir()`). Una conversación del usuario vive
       bajo `-Users-…`; jamás bajo `-private-var-folders-…-T-`.
    2. **cero transcripts** — ni un `.jsonl` en todo el subárbol. Un `.jsonl` ES la
       conversación. Si hay uno, no se toca, aunque cumpla (1).

  `/private/tmp` y `/tmp` quedan FUERA a propósito: ahí viven los scratchpads de sesiones
  de Claude Code que pueden estar corriendo ahora mismo. El agujero medido es el de
  `mkdtemp`, y `mkdtemp` escribe en `gettempdir()`.

USO EN UNA VARA — una línea, al principio:

    import higiene_store                      # qa/lib en sys.path
    higiene_store.vigilar()                   # registra el barrido para la salida

USO A MANO — barrer lo acumulado:

    product/backend/.venv/bin/python qa/lib/higiene_store.py --barrer
    product/backend/.venv/bin/python qa/lib/higiene_store.py            # sólo censo
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (str(_RAIZ / "platform" / "assembler" / "cli_brain"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sesiones as _S  # noqa: E402  — la REGLA REAL del slug, no una copia

__all__ = ["raiz_del_store", "prefijos_temporales", "es_huerfano",
           "censar_huerfanos", "barrer", "vigilar"]


def raiz_del_store() -> Path:
    return Path(_S.raiz_del_store())


def prefijos_temporales() -> tuple[str, ...]:
    """Los slugs de los directorios donde `mkdtemp` escribe. Derivados con la regla real."""
    return (_S.slug_de(tempfile.gettempdir()),)


def _sin_transcripts(d: Path) -> bool:
    """Ni un `.jsonl` en todo el subárbol. El candado que protege las conversaciones."""
    try:
        return not any(d.rglob("*.jsonl"))
    except OSError:
        return False  # si no se puede mirar adentro, no se toca


def es_huerfano(nombre: str, raiz: Path | None = None) -> bool:
    """Los DOS candados. `nombre` es una entrada de `~/.claude/projects/`."""
    raiz = raiz or raiz_del_store()
    d = raiz / nombre
    if not d.is_dir():
        return False
    if not any(nombre.startswith(p) for p in prefijos_temporales()):
        return False
    return _sin_transcripts(d)


def censar_huerfanos(raiz: Path | None = None) -> list[str]:
    raiz = raiz or raiz_del_store()
    try:
        return sorted(n for n in os.listdir(raiz) if es_huerfano(n, raiz))
    except OSError:
        return []


def barrer(raiz: Path | None = None, *, ruidoso: bool = True) -> int:
    """Borra los huérfanos. Devuelve cuántos. Nunca toca nada con un `.jsonl`."""
    raiz = raiz or raiz_del_store()
    huerfanos = censar_huerfanos(raiz)
    for n in huerfanos:
        shutil.rmtree(raiz / n, ignore_errors=True)
    if ruidoso and huerfanos:
        # stderr por el mismo motivo que `vigilar()`: instrumentación, no veredicto.
        print(f"[higiene] {len(huerfanos)} espejo(s) huérfano(s) borrado(s) del store "
              f"del CLI", file=sys.stderr)
    return len(huerfanos)


_vigilando = False


def vigilar() -> None:
    """Barre al salir SÓLO lo que apareció durante esta corrida.

    El snapshot es lo que hace esto seguro de verdad: aunque los dos candados fallaran,
    una entrada que ya existía antes de arrancar la vara no se toca nunca.
    """
    global _vigilando
    if _vigilando:
        return
    _vigilando = True
    raiz = raiz_del_store()
    try:
        antes = set(os.listdir(raiz))
    except OSError:
        antes = set()

    def _al_salir() -> None:
        nuevos = [n for n in censar_huerfanos(raiz) if n not in antes]
        for n in nuevos:
            shutil.rmtree(raiz / n, ignore_errors=True)
        if nuevos:
            # ══ A STDERR, Y NO ES UN DETALLE ═══════════════════════════════════════════
            # Un `atexit` corre DESPUÉS del `print` del veredicto. Con esto en stdout, la
            # última línea de la vara pasaba a ser «[higiene] 2 espejo(s)…» — o sea que
            # tapar el agujero de H1 rompía la regla de H3, medido en la propia corrida de
            # regresión de esta fase. Es instrumentación, no veredicto: va por stderr, y
            # así un `tail -1` sobre stdout sigue leyendo lo que decide un merge.
            print(f"[higiene] {len(nuevos)} espejo(s) que dejó esta vara borrado(s) "
                  f"del store", file=sys.stderr)

    atexit.register(_al_salir)


if __name__ == "__main__":
    _raiz = raiz_del_store()
    _h = censar_huerfanos(_raiz)
    print(f"store: {_raiz}")
    print(f"prefijos temporales: {', '.join(prefijos_temporales())}")
    print(f"huérfanos (temporal + cero transcripts): {len(_h)}")
    for _n in _h:
        print(f"  · {_n}")
    if "--barrer" in sys.argv:
        print(f"\nBARRIDOS: {barrer(_raiz, ruidoso=False)}")
    else:
        print("\n(censo solamente — pasá --barrer para borrarlos)")
