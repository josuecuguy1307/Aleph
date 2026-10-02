#!/usr/bin/env python3
"""gen_vocabulary_js.py — write the JS mirror of THE vocabulary.

[Gate 4 · Fase 2 · obra 2.3] The two render registries live in the browser and the
vocabulary lives in Python. Three ways to bridge that, and why this one:

  (a) hand-copy the table into JS ......... that IS the drift the obra kills. No.
  (b) fetch `/v1/artifacts/types` at runtime ... `render(type, payload) → DOMNode`
      is SYNCHRONOUS and frozen (render/README.md), and `render.demo.html` runs
      with no backend at all. A registry that needs the network to know its own
      types is a registry that breaks offline.
  (c) GENERATE the mirror from the source, commit it, and let a vara fail if it
      drifts. ← this. The file is derived, never authored; the drift is caught
      mechanically instead of being trusted.

The endpoint (a) declared in contract §2.4 still exists and serves `as_json()`;
the vara checks that what it serves and what this generates are the same payload.

    python3 platform/artifacts/gen_vocabulary_js.py            # write the mirror
    python3 platform/artifacts/gen_vocabulary_js.py --check    # exit 1 if drifted
    python3 platform/artifacts/gen_vocabulary_js.py --stdout   # print, write nothing
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
if str(_HERE.parents[1]) not in sys.path:                 # platform/
    sys.path.insert(0, str(_HERE.parents[1]))

from artifacts import vocabulary  # noqa: E402

#: The mirror lives next to the module that imports it (render/render.js), which
#: is the one both surfaces already load.
TARGET = _HERE.parents[2] / "product" / "app" / "design" / "render" / "vocabulary.js"

_HEADER = """/* ============================================================================
 * vocabulary.js — EL vocabulario de tipos de artefacto, del lado del navegador.
 *
 *   ARCHIVO GENERADO — NO SE EDITA A MANO.
 *   Fuente:      platform/artifacts/vocabulary.py
 *   Se regenera: python3 platform/artifacts/gen_vocabulary_js.py
 *   La vara `qa/verify_vocabulario_cableado.py` FALLA si este archivo drifteó de
 *   su fuente: un espejo que nadie chequea es una quinta lista con pasos extra.
 *
 * Lo consumen los DOS registros de render (render/render.js por import, y
 * render/sala-render.js por `window.AlephVocabulary`), que antes tenían cada uno su
 * propia lista de tipos y su propio mapa de alias — 11 y 16, con `doc` canónico
 * de un lado y `documento` del otro (censo §C.3).
 *
 * `normalize()` es la MISMA función que el borde de escritura del almacén: alias
 * → canónico, minúsculas, sin espacios; fuera de la unión → null (un VEREDICTO,
 * no un fallback: quien llama decide qué hacer con el null, a la vista).
 * ========================================================================== */
"""

_TAIL = """
export const CANONICAL = Object.keys(TYPES);

/** Nombre canónico de `t` (alias resuelto), o null si está fuera de la unión. */
export function normalize(t) {
  const s = String(t == null ? "" : t).trim().toLowerCase();
  if (!s) return null;
  if (Object.prototype.hasOwnProperty.call(TYPES, s)) return s;
  return Object.prototype.hasOwnProperty.call(ALIASES, s) ? ALIASES[s] : null;
}

export function isValid(t) { return normalize(t) !== null; }

/** Los tipos con una bandera prendida, en orden de declaración. */
function withFlag(flag) { return CANONICAL.filter((t) => TYPES[t][flag]); }

/** Los que el clasificador puede ofrecerle al modelo (gobierna stream_chat). */
export function producibleByLlm() { return withFlag("producible_by_llm"); }

/** Los que el executor captura del workdir y la Sala valida en RICH_SHAPES. */
export function richCapture() { return withFlag("rich_capture"); }

export function isRich(t) {
  const c = normalize(t);
  return c !== null && !!TYPES[c].rich_capture;
}

export function formatsFor(t) {
  const c = normalize(t);
  return c === null ? ["md"] : TYPES[c].formats.slice();
}

export function labelEs(t) {
  const c = normalize(t);
  return c === null ? String(t == null ? "" : t) : TYPES[c].label_es;
}

/* Global además de ESM: `render/sala-render.js` es un script clásico (IIFE) y no puede
 * importar. Se expone al cargarse este módulo — que es lo que hace render.js al
 * importarlo. Una superficie que cargue SalaRender sin AlephRender no tiene
 * vocabulario y degrada declarándolo (ver `render/sala-render.js`), jamás en silencio. */
const API = {
  SCHEMA_VERSION, TYPES, ALIASES, LLM_ALIASES, ADVISORY_FIELDS, CANONICAL,
  normalize, isValid, isRich, producibleByLlm, richCapture, formatsFor, labelEs,
};
if (typeof window !== "undefined") window.AlephVocabulary = API;

export default API;
"""


def _js_const(name: str, value) -> str:
    return "export const %s = %s;\n\n" % (
        name, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False))


def build() -> str:
    payload = vocabulary.as_json()
    body = [_HEADER, "\n"]
    body.append(_js_const("SCHEMA_VERSION", payload["schema_version"]))
    body.append(_js_const("ADVISORY_FIELDS", payload["advisory_fields"]))
    body.append(_js_const("TYPES", payload["types"]))
    body.append(_js_const("ALIASES", payload["aliases"]))
    body.append(_js_const("LLM_ALIASES", payload["llm_aliases"]))
    body.append(_TAIL.lstrip("\n"))
    return "".join(body)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Genera el espejo JS del vocabulario.")
    ap.add_argument("--check", action="store_true",
                    help="no escribe: sale 1 si el archivo committeado drifteó")
    ap.add_argument("--stdout", action="store_true", help="imprime y no escribe")
    args = ap.parse_args(argv)

    js = build()
    if args.stdout:
        sys.stdout.write(js)
        return 0
    if args.check:
        if not TARGET.exists():
            print("DRIFT: falta %s" % TARGET, file=sys.stderr)
            return 1
        live = TARGET.read_text(encoding="utf-8")
        if live != js:
            print("DRIFT: %s no coincide con vocabulary.py — regenerá con:\n"
                  "  python3 platform/artifacts/gen_vocabulary_js.py" % TARGET,
                  file=sys.stderr)
            return 1
        print("OK: el espejo JS coincide con el vocabulario (%d tipos, %d alias)"
              % (len(vocabulary.TYPES), len(vocabulary.ALIASES)))
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(js, encoding="utf-8")
    print("escrito: %s (%d tipos, %d alias)"
          % (TARGET, len(vocabulary.TYPES), len(vocabulary.ALIASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
