#!/usr/bin/env python3
"""verify_composer_ciencia.py — LAS CUATRO OPCIONES DE CIENCIA YA ESTÁN, Y GOBIERNAN.
[rediseño · fase 4 · 4.3]

EL RESULTADO DE ESTA OBRA ES QUE NO HAY OBRA, y eso hay que probarlo, no afirmarlo.

El encargo daba 4.3 como «mover el botón»: llevar Delegation, Auto-review, Reviewer model y
Specialist a los «dos palitos» del diseño. Medido sobre el stack, **el menú ya es ése**:

    prompt-input.tsx:2303   <Icon name="sliders" />        ← los dos palitos del mockup 35a
    prompt-input.tsx:2307   capabilityView() === "main"    ← la vista principal
    prompt-input.tsx:2308   workspace-composer__capability-list
    prompt-input.tsx:373    title="Reviewer model"         ← su submenú
    prompt-input.tsx:2307+  views "specialists" y "reviewer"

O sea que el mockup no pedía trabajo nuevo: dibujó lo que Ciencia ya tiene. Lo que le
faltaba era la PIEL, y eso lo puso la fase 3. Mover esos controles a un menú nuestro habría
sido cirugía sobre un componente ajeno **para llegar al mismo lugar**.

Y LA PERSISTENCIA TAMBIÉN ESTÁ, que es la mitad que de verdad importa:

    prompt-input.tsx:288    saveDelegation → PATCH de las preferencias
    routes/settings/preferences.ts:15   `Global.Path.config/settings.json`
    …:33-45                 `read()` lee el archivo EN CADA request, sin caché
    …:24-27                 `delegation_enabled` y `delegation_specialist` en el esquema

Así que el toggle no se queda en la pantalla: baja a un archivo que su servidor relee. Es
exactamente el criterio de esta fase —leer el destino final— y ya se cumplía.

⚠️ POR ESO ESTA VARA ES DE CENSO Y NO DE EJECUCIÓN. Afirma que las piezas están donde el
análisis dice. Correr el composer de verdad pide el pack vivo con un modelo; eso queda
[no medible] acá y está dicho. Lo que esta vara impide es que alguien «mueva» mañana esos
controles creyendo que faltaban.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CO = RAIZ / "third_party/openscience/frontend/workspace/src/components/prompt-input.tsx"
PR = RAIZ / "third_party/openscience/backend/cli/src/server/routes/settings/preferences.ts"
MUT = "--mutante" in sys.argv
fallos: list[str] = []


def ok(c: bool, m: str) -> None:
    print(f"  {'✓' if c else '✗'} {m}")
    if not c:
        fallos.append(m)


def main() -> int:
    for p in (CO, PR):
        if not p.is_file():
            print(f"✗ falta {p.relative_to(RAIZ)} — sin el árbol del stack no se puede afirmar nada")
            return 1
    co = CO.read_text()
    pr = PR.read_text()
    if MUT:
        # La mutación borra el disparador del menú y la clave del store: si la vara siguiera
        # verde, no estaría midiendo que las piezas existen.
        co = co.replace('<Icon name="sliders" />', "<!-- MUTADO -->")
        pr = pr.replace("delegation_enabled", "MUTADO")

    print("── el menú de los dos palitos ya está en el composer ──")
    ok('<Icon name="sliders" />' in co, "el disparador es un ícono `sliders` — los dos palitos del mockup")
    ok("workspace-composer__capability-list" in co, "…y abre una lista de capacidades")
    for vista in ("main", "specialists", "reviewer"):
        ok(f'capabilityView() === "{vista}"' in co, f"…con la vista «{vista}»")
    ok('title="Reviewer model"' in co, "«Reviewer model» está, con su submenú")
    ok("const setDelegation" in co and "const setSpecialist" in co,
       "Delegation y Specialist tienen su setter")

    print("\n── y bajan hasta un archivo que su servidor relee ──")
    ok("saveDelegation" in co, "el composer persiste con `saveDelegation`")
    ok("delegation_enabled" in pr and "delegation_specialist" in pr,
       "las dos claves están en el esquema del store del stack")
    ok('path.join(Global.Path.config, "settings.json")' in pr,
       "el store es un JSON en el config del stack")
    ok(re.search(r"async function read\(\)[\s\S]{0,200}Bun\.file\(filepath\)", pr) is not None,
       "…y se LEE en cada request, sin caché — el destino final, no un intermedio")
    ok(".patch(" in pr, "expone un PATCH: la casa podría escribirle si algún día hiciera falta")

    print("")
    if MUT:
        if not fallos:
            print("✗ LA VARA ESTÁ ROTA: se borró el disparador y la clave, y no cayó nada.")
            return 1
        print(f"✓ la vara puede dar rojo: {len(fallos)} afirmaciones cayeron.")
        return 0
    if fallos:
        print(f"✗ {len(fallos)} rojas")
        return 1
    print("✓ 4.3 no pedía obra: el menú y su persistencia ya estaban. La piel se la puso la fase 3")
    print("  ~ [no medible acá] apretar el toggle en el composer vivo: pide el pack con un modelo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
