#!/usr/bin/env python3
"""Vara única Gate 3 · Obra D: EL PUENTE ENTRE LOS DOS ESPACIOS DE ID.

    python3 platform/assembler/verify_costura_obraD.py

EL BUG QUE CIERRA, reportado por persona usuaria sobre la .app de la obra C y REPRODUCIDO antes de
tocar nada: el árbol tiene DOS vocabularios para nombrar un modelo y nadie los traducía.

  · el WIDGET (Modelos v2 / sidecar) → `picker_id`  `opus` · `claude_cli` · `api:anthropic`
  · la RECETA (`cuarto.models.js`)   → id CURADO    `opus` · `claude_cli` · `byok` · `oss` …

Se solapan en TRES. Las ocho filas `api:*` no existen del lado curado, así que:

  F1 · elegir un modelo de API no hacía NADA — `modelEntry('api:anthropic')` daba `null` y el
       click moría en un `return` mudo.
  F2/F3 · «En uso» salía del sidecar y caía a `lista[0]` cuando el id no matcheaba, así que
       marcaba una fila cualquiera mientras el turno corría otra cosa.

── ⚠️ POR QUÉ LAS VARAS DE LAS OBRAS B Y C NO LO CAZARON ───────────────────────────────
Porque **su arnés sembraba LOS MISMOS IDS EN LOS DOS LADOS**. `VB1`/`VB3`/`VB4` usaban ids
curados (`qwen-local`, `oss`) tanto para el catálogo como para las filas del widget: un mundo
donde la traducción no hace falta, o sea donde el bug es inalcanzable. Y `VB2` medía NOMBRES
DE CLASE del DOM (`ams`, `ams-option`), que prueba que es el mismo componente y nunca que un
click resuelva.

Esta vara siembra **los dos espacios por separado**, como producción, y mide COMPORTAMIENTO:
si un click no resuelve, cae. Es la tercera vez en esta tanda que un verde no medía lo que
decía (las otras: `verify_f4a` salteando LiteLLM, `verify_slice_d_controls` crasheando antes
de llegar) — el patrón ya tiene nombre.

── DE DÓNDE SALE CADA MEDICIÓN ─────────────────────────────────────────────────────────
VD1-VD5 los mide `arnes_costura_obraD.mjs` en WebKit REAL contra la Sala de este árbol. El
`PUT /v1/puppets/{id}/config` se INTERCEPTA: se mide QUÉ se iba a escribir, sin tocar DB.

NO SPAWNEA OTRAS VARAS (regla sellada). Las regresiones —obras 1·2·3·5·A·B·C,
`verify_slice_d_controls`, `modelos_v2`, `cuarto_modelos`, `f4a` con el venv, y los tests—
se corren APARTE y se reportan aparte. `verify_costura_obra4` NO entra: ~9 min y esta obra no
toca su territorio (`cli_brain`).

Cero red, cero backend, cero puertos fijos. JAMÁS :8377 ni :25374.
"""

from __future__ import annotations

import json
import subprocess
import pytest
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARNES = ROOT / "product" / "app" / "design" / "sala" / "arnes_costura_obraD.mjs"
MODELS = ROOT / "product" / "app" / "design" / "cuarto" / "cuarto.models.js"
SALA = ROOT / "product" / "app" / "design" / "sala" / "sala.html"

# [Convergencia · superficie 7 · paso 6] LA SALA VIEJA SE BORRÓ.
# Esta vara medía, entre otras cosas, texto de `sala/sala.html`. Esa pantalla ya no existe:
# su trabajo se rescató en la v2 y el resto murió con ella. La mitad que medía la Sala se
# SALTEA diciéndolo —no se borra la vara, porque el RESTO de lo que mide sigue vivo— y no
# se finge verde: un checkeo sin objeto es un salteo, jamás un ✓.
SALA_VIVA = SALA.exists()


PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: Any = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"PASS {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"FAIL {name} — {detail}")


def main() -> int:
    if not SALA_VIVA:
        # El arnés abre `sala/sala.html` en un navegador REAL. Sin pantalla no hay nada
        # que abrir: se saltea diciéndolo, jamás se finge verde.
        pytest.skip("el arnés medía la Sala vieja, que se borró (paso 6)")
    corrida = subprocess.run(["node", str(ARNES)], cwd=ROOT, text=True, capture_output=True)
    if corrida.returncode != 0:
        check("arnés del frente corre", False, (corrida.stderr or corrida.stdout)[-500:])
        print(f"=== {PASSED} passed, {FAILED} failed ===")
        return 1
    front = json.loads(corrida.stdout)
    check("arnés del frente sin errores de página", not front["errores_de_pagina"],
          front["errores_de_pagina"])

    v1, v2, v3, p = front["vd1"], front["vd2"], front["vd3"], front["vd5"]
    cr = front["click_real"]

    # ══ [obra E] EL CLICK CON PUNTERO REAL ═════════════════════════════════════════
    # LA ASERCIÓN QUE FALTABA, y sin ella esta vara pasó con el bug VIVO: un `mousedown`
    # global cerraba el panel antes de que el `click` aterrizara (`sala.html:2991`, la regla
    # «click afuera cierra» de los popups del composer, que la obra C dejó apuntando al panel
    # lateral). Ni el seam ni un `.click()` programático disparan `mousedown`: SÓLO un puntero
    # de verdad lo destapa. persona usuaria lo vio en la .app; la vara no.
    check("VE1 el panel SOBREVIVE al mousedown de su propio click",
          cr["filas_encontradas"] == 1 and cr["panel_sobrevive"] is True, cr)
    check("VE2 y un click de PUNTERO REAL sobre la fila abre la confirmación",
          cr["confirma"] == ["Cambiar el agente", "Dejarlo como está"], cr["confirma"])

    # ══ VD1 · el panel monta el widget compartido, con las filas del sidecar ══════════
    check("VD1 el panel monta el componente compartido (render/html reales, no una copia)",
          v1["es_el_componente"] is True)
    check("VD1b …y pinta EXACTAMENTE las filas del sidecar, en su propio espacio de id",
          v1["ids_del_widget"] == v1["ids_esperados"], v1["ids_del_widget"])
    check("VD1c incluidas las filas `api:*`, que son las que el catálogo curado NO tiene",
          v1["tiene_api"] is True, v1["ids_del_widget"])

    # ══ VD3 · «En uso» sale de lo que EJECUTA, no del sidecar ════════════════════════
    check("VD3 el agente corre `opus` → la fila marcada «En uso» es `opus`",
          v3["marcadas"] == ["opus"] and v3["en_uso"] == ["opus"]
          and v3["corre"] == "anthropic/claude-opus-4.8", v3)
    check("VD3b …con el sidecar diciendo OTRA cosa (si volviera a leer de ahí, esto cae)",
          v3["sidecar_decia"] == "claude_cli" and "claude_cli" not in v3["marcadas"], v3)
    # EL CASO QUE ANTES MARCABA UNA FILA CUALQUIERA: el agente corre algo que el sidecar no
    # ofrece. La respuesta honesta es NINGUNA marcada — no la primera de la lista.
    check("VD3c agente con un modelo que el sidecar no lista → NINGUNA fila «En uso»",
          v1["marcadas"] == [] and v1["corre"] == "qwen3:8b", v1)

    # ══ VD2 · el click de una fila `api:*` resuelve, confirma y ESCRIBE ══════════════
    sc = v2["sinConfirmar"]
    check("VD2 elegir una fila `api:*` RESUELVE y pide confirmación (antes: return mudo)",
          sc["pide"] is True and len(sc["botones"]) == 2, sc)
    check("VD2b sin confirmar no se escribe nada", sc["puts"] == 0, sc)
    check("VD2c confirmar escribe UNA vez en la fuente única", v2["puts"] == 1, v2)
    check("VD2d y lo persistido es el BYOK de esa fila, compilado con el payload completo",
          v2["persistido"] == {"primary": "claude-opus-4-8",
                               "base_url": "https://api.anthropic.com/v1",
                               "byok_ref": "keys:anthropic"}, v2["persistido"])
    check("VD2e el turno corre ESE modelo (no una receta con `primary` vacío)",
          v2["corre_despues"] == "claude-opus-4-8", v2["corre_despues"])

    # ══ VD5 · el viaje de vuelta: el Cuarto lo lee, y el panel se re-marca ═══════════
    check("VD5 el Cuarto lee lo persistido con SU función y ve el modelo nuevo",
          v2["id_que_leeria_el_cuarto"] == "byok", v2)
    check("VD5b y el panel marca «En uso» la fila que acaba de quedar corriendo",
          v2["marcadas_despues"] == ["api:anthropic"], v2["marcadas_despues"])

    # ══ EL PUENTE, contra el módulo REAL, en las dos direcciones ════════════════════
    check("VD-P1 ida · fila `api:*` → `byok` con su payload {provider, model, baseUrl}",
          p["api"]["id"] == "byok" and p["api"]["via"] == "byok_ref"
          and p["api"]["byok"] == {"provider": "anthropic", "model": "claude-opus-4-8",
                                   "baseUrl": "https://api.anthropic.com/v1"}, p["api"])
    check("VD-P2 ida · fila `cli` → su provider curado, por `brain_provider`",
          p["cli"]["id"] == "claude_cli" and p["cli"]["via"] == "brain_provider", p["cli"])
    check("VD-P3 ida · fila `incluido` → `opus`, por identidad de `picker_id`",
          p["incluido"]["id"] == "opus" and p["incluido"]["via"] == "picker_id", p["incluido"])
    # LO QUE NO SE PUEDE TRADUCIR DEVUELVE `null` — y quien llama lo DICE. Cambiar un return
    # mudo por otro return mudo no habría arreglado nada.
    check("VD-P4 ida · una fila que no se puede traducir devuelve `null`, no una adivinanza",
          p["desconocida"] is None, p["desconocida"])
    check("VD-P5 vuelta · por `byok_ref` · por `brain_provider` · por modelo+base_url",
          p["vuelta_byok"] == "api:anthropic" and p["vuelta_cli"] == "claude_cli"
          and p["vuelta_modelo"] == "opus", p)
    check("VD-P6 vuelta · un modelo que el sidecar no lista devuelve `null` (ninguna fila)",
          p["vuelta_ninguna"] is None, p["vuelta_ninguna"])

    # ══ LA TRADUCCIÓN VIVE EN UN SOLO LUGAR ═════════════════════════════════════════
    # La regla que persona usuaria puso: nada de convertir ad hoc en cada punto de uso. Se congela.
    if not SALA_VIVA:
        print("  ~ SALTEADO: la Sala vieja se borró (paso 6) — esta mitad no tiene objeto")
        return
    fuente_sala = SALA.read_text()
    check("VD-U1 el puente vive en `cuarto.models.js`, con nombre propio y las dos direcciones",
          "export function curadoDesdeFila" in MODELS.read_text()
          and "export function filaDesdeReceta" in MODELS.read_text())
    # La regla se congela midiendo DOS cosas concretas, no un heurístico de texto: que la
    # Sala LLAME al puente, y que NO manipule sus internals. `picker_id` y el `keys:` de un
    # `byok_ref` son vocabulario DEL PUENTE — si aparecen acá, alguien está traduciendo a
    # mano, que es exactamente lo que la regla prohíbe.
    check("VD-U2 la Sala LLAMA al puente en las dos direcciones",
          "_modelsApi.curadoDesdeFila" in fuente_sala
          and "_modelsApi.filaDesdeReceta" in fuente_sala)
    codigo_sala = "\n".join(l for l in fuente_sala.splitlines()
                            if not l.strip().startswith(("*", "//", "/*")))
    check("VD-U2b …y NO manipula los internals del puente (cero traducción ad hoc)",
          "picker_id" not in codigo_sala and "keys:/" not in codigo_sala,
          [l.strip()[:70] for l in codigo_sala.splitlines() if "picker_id" in l])
    check("VD-U3 y le pide al widget el veredicto RESUELTO (que puede ser «ninguna»)",
          "seleccionadoResuelto:true" in fuente_sala)

    print(f"=== {PASSED} passed, {FAILED} failed ===")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
