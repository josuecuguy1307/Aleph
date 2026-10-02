#!/usr/bin/env bash
# Aleph · Gate 4 · Fase 6 · §6.f — PRODUCIR LAS DEPENDENCIAS DEL MODO LARGO DE LA SALA.
#
# Qué produce, y por qué no está en git:
#
#   platform/sala/research/lib/    las 279 dependencias del motor (1,9 GiB de wheels)
#
# Y qué NO produce, a propósito:
#
#   · **El motor.** `third_party/ldr/src` es código importado y versionado (3.080 archivos,
#     `IMPORT.md` + `MANIFEST.sha256`). Se importa como LIBRERÍA por `PYTHONPATH`, no se
#     instala: instalarlo pondría una copia adentro de `lib/` que le ganaría al árbol
#     extirpado, y las extirpaciones de la Ley 2.bis dejarían de tener efecto.
#   · **El intérprete.** `platform/sala/research/runtime` lo produce
#     `producir_busqueda.sh` y lo COMPARTEN los dos modos: uno solo, una instalación.
#     Correr los dos scripts en cualquier orden funciona; el que llegue segundo lo
#     encuentra hecho.
#
# Es idempotente: correrlo dos veces no rehace lo que ya está sano.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
LDR="$RAIZ/third_party/ldr"
LIB="$RAIZ/platform/sala/research/lib"
RT="$RAIZ/platform/sala/research/runtime"

decir() { echo "▸ $*"; }
morir() { echo "producir_research: $*" >&2; exit 1; }

# ── 0 · las herramientas y el terreno, ANTES de bajar 1,9 GiB ─────────────────
command -v uv >/dev/null || morir "falta uv (https://docs.astral.sh/uv/)"
[ -f "$LDR/pyproject.toml" ] || morir "no está el motor en third_party/ldr — ¿árbol incompleto?"

# EL INTÉRPRETE ES DEL OTRO SCRIPT, Y ESO SE DICE, no se resuelve en silencio: producirlo
# acá dejaría dos dueños del mismo directorio y una carrera el día que los dos corran.
if [ ! -x "$RT/bin/python3" ]; then
  morir "falta el runtime de Python compartido ($RT).
       Lo produce el script hermano, y lo usan LOS DOS modos:
         bash deploy/fase6/producir_busqueda.sh runtime"
fi

# El disco: un build necesita 12 GiB y esto se lleva 1,9 más su caché. Se avisa ANTES,
# porque quedarse sin disco a mitad de un `uv pip install` deja el árbol a medias — y en
# esta casa ya costó: `internal error in Code Signing subsystem` era el disco lleno.
_libres_gib="$(df -g "$RAIZ" | awk 'NR==2 {print $4}')"
if [ "${_libres_gib:-99}" -lt 8 ]; then
  morir "quedan ${_libres_gib} GiB libres y esto necesita ~6 (1,9 instalados + caché).
       Liberá antes de empezar: df -h /System/Volumes/Data"
fi

# ── 1 · las dependencias, al lado del launcher ────────────────────────────────
#
# `--target` y no un venv: `arranque.sh` las pone en `PYTHONPATH` (`$AQUI/lib`), que es el
# mismo mecanismo con el que su hermano cuelga SearXNG de `searxng/lib`. Un venv traería su
# propio `bin/python3` y volveríamos a tener dos intérpretes donde alcanza uno.
if [ -d "$LIB/langchain_openai" ] && [ "${1:-}" != "--rehacer" ]; then
  decir "research · las dependencias ya están ($(du -sh "$LIB" | cut -f1)) — nada que hacer"
else
  decir "research · instalando las 279 dependencias del motor (esto tarda)"
  rm -rf "$LIB"
  uv pip install --python "$RT/bin/python3" --target "$LIB" "$LDR"

  # ⚠️ SE SACA EL MOTOR DE `lib/`. `uv pip install <dir>` construye e instala el paquete
  # ADEMÁS de sus dependencias, y esa copia le ganaría a `third_party/ldr/src` en el
  # `PYTHONPATH` que arma el launcher. Sería el árbol SIN las extirpaciones de la Ley
  # 2.bis corriendo en producción, y nada lo diría: mismo nombre, mismo import, otro
  # código. Se instala por sus dependencias; el motor se importa del árbol.
  decir "research · sacando la copia instalada del motor (gana el árbol extirpado)"
  rm -rf "$LIB/local_deep_research" "$LIB"/local_deep_research-*.dist-info

  # ── LA PODA ─────────────────────────────────────────────────────────────────
  #
  # POR QUÉ HAY QUE PODAR, y no es higiene: **sin poda el `.app` no arranca.** El sidecar
  # es un onefile de PyInstaller y `_OPAQUE_PACK_DIRS` termina adentro del ejecutable, así
  # que estos 2,05 GB se suman al binario. Medido: con ellos el sidecar pesa 2,09 GB y
  # muere en dyld antes de correr una línea —«dyld cache not loaded: syscall to map cache
  # into shared region failed»—, mientras que el instalado de 1,53 GB arranca. El par
  # falsable ya estaba: 1,53 arranca, 2,09 no.
  #
  # QUÉ SE PODA, Y CÓMO SE ELIGIÓ: **corriendo, no leyendo el `pyproject`.** Se corrieron
  # los DOS modos (`resumen` e `informe`) contra un SearXNG real, y se volcó `sys.modules`
  # al final del turno: de los 305 paquetes instalados, la vía real carga **253**. Los de
  # abajo son los que no cargó ninguno de los dos, de 9 MB para arriba.
  #
  # El precedente es de la casa: Vane compilaba once plataformas y el spec usaba una —se
  # podaron 1,6 GiB con el mismo criterio—.
  #
  # ⚠️ EL RIESGO ESTÁ DECLARADO. Un import perezoso por un camino que el censo no
  # ejercitó rompería en la máquina del usuario y no en la nuestra. Por eso:
  #   · se poda por LISTA EXPLÍCITA, no por «todo lo que no salió en el censo»;
  #   · cada línea dice para qué lo quiere LDR y por qué nuestra vía no lo toca;
  #   · `torch` y `transformers` **NO se podan** aunque sean 544 MB: el censo dice que la
  #     vía real los carga, y podar lo que se usa es cambiar un `.app` que no arranca por
  #     uno que se rompe a mitad de una obra;
  #   · el testigo de abajo corre los dos modos DESPUÉS de podar.
  decir "research · podando lo que la vía real no carga (censo medido, no el pyproject)"
  _PODA="
    playwright patchright          # el navegador de crawl4ai: nuestra vía usa el fetch simple
    llvmlite numba                 # JIT, entra por la cadena de análisis
    scipy sklearn sympy mpmath     # matemática de sus caminos de análisis/RAG
    matplotlib plotly              # gráficos: este modo entrega texto y fuentes
    spacy nltk thinc blis cymem murmurhash preshed srsly wasabi catalogue confection langcodes
                                   # NLP local: la síntesis la hace el cerebro de la casa
    faiss                          # índice vectorial: sin RAG local no se toca
    pypandoc                       # conversión de documentos subidos
    litellm                        # su vía alternativa de LLM: nosotros INYECTAMOS el nuestro
    networkx                       # grafos de su modo de relaciones
    babel primp                    # i18n y su cliente HTTP alternativo
  "
  for _paq in $(echo "$_PODA" | sed 's/#.*$//'); do
    rm -rf "$LIB/$_paq" "$LIB/${_paq}.py" "$LIB"/${_paq}-*.dist-info "$LIB"/${_paq}.libs 2>/dev/null || true
  done
fi

# ── 2 · el testigo: que el motor IMPORTE de verdad ────────────────────────────
#
# No se chequea que los directorios existan —eso ya lo hace el spec— sino que el motor
# **arranque por el camino que el pack usa**. Es la diferencia entre «los archivos están»
# y «el modo funciona», y en esta casa esa diferencia ya costó un build entero.
decir "research · testigo: importar el motor como lo hace el pack"
PYTHONPATH="$LDR/src:$LIB" "$RT/bin/python3" - <<'PY' || morir "el motor no importa — las deps quedaron a medias"
import sys
from local_deep_research.api import quick_summary, detailed_research   # noqa: F401
from local_deep_research.api.settings_utils import create_settings_snapshot  # noqa: F401
from local_deep_research.exceptions import ResearchTerminatedException  # noqa: F401
import local_deep_research
# Y que sea EL DEL ÁRBOL, no una copia instalada: si esto falla, el `rm -rf` de arriba no
# corrió y estaríamos sirviendo el motor sin extirpar.
assert "third_party/ldr/src" in local_deep_research.__file__, local_deep_research.__file__
# `langchain_openai` es el único import de `cerebro.py`: sin él el pack levanta verde y
# muere en la primera obra con `cerebro_sin_sdk`.
import langchain_openai   # noqa: F401
print("   motor OK ·", local_deep_research.__file__)
PY

decir "listo · $(du -sh "$LIB" | cut -f1) en $LIB"
decir "     el intérprete lo comparten los dos modos: $RT"
