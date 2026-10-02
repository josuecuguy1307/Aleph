#!/usr/bin/env python3
"""verify_public_vigilado.py — QUE UN CAMBIO EN `public/` DISPARE EL REHORNEADO.
[rediseño · fase 1 · cable de seguridad (a)]

QUÉ AGUJERO CIERRA, MEDIDO ANTES DE ESCRIBIR UNA LÍNEA
──────────────────────────────────────────────────────
`deploy/fase4/build_app.sh` decide si vuelve a hornear la cara de cada stack con
`esta_fresco(artefacto, …directorios…)`: busca un archivo más nuevo que el artefacto y, si
no lo hay, se saltea el build. Los directorios que vigilaba eran:

    :200  Ciencia   → src, index.html                       ← SIN public/
    :318  Oficina   → apps, packages                        ← public/ cae bajo apps/  ✓
    :341  Diseño    → apps, packages                        ← ✓
    :410  Educación → app, src, components                  ← SIN public/
    :457  Finanzas  → src                                   ← SIN public/
    :236  Legal     → sin guarda: se rehornea SIEMPRE       ← ✓

Y `public/` es **exactamente donde vive toda la piel de Aleph** en los seis stacks
(`aleph-picker-unico.js`, `aleph-model-chip.core.{js,css}`, `aleph-theme-preload.js`).
Verificado dentro de la `.app` instalada: esos archivos SÍ terminan copiados adentro de
`dist/` y de `.next/standalone/public/`, o sea que el copiado lo hace el build — y **si el
build decide no correr, el `dist` conserva la copia vieja y nadie se entera**.

Es «el build no lleva lo recién horneado» otra vez, en un lugar nuevo. Tres palabras lo
cierran; esta vara existe para que no se vuelvan a caer.

QUÉ MIDE, EN DOS NIVELES
────────────────────────
1. **EL CONTRATO** — que los tres sitios nombren `public` en las DOS llamadas: la de
   `esta_fresco` y la de `por_que_rehornea`. Van juntas a propósito: si sólo una lleva
   `public`, el build rehornea pero el mensaje no puede nombrar al culpable (o al revés),
   y un caché que no explica por qué corre es indistinguible de uno roto.

2. **EL MECANISMO** — se extraen las dos funciones REALES de `build_app.sh` (no una copia:
   se leen del archivo con `sed`) y se corren contra un árbol de fixture donde **lo único
   nuevo está en `public/`**. Se exige:
       · con la lista VIEJA (sin public) → dice «fresco»  ⇒ el bug se reproduce
       · con la lista NUEVA (con public) → dice «no fresco» Y `por_que_rehornea` NOMBRA
         el archivo culpable

CÓMO SE PRUEBA QUE ESTA VARA PUEDE DAR ROJO
───────────────────────────────────────────
El nivel 2 **contiene su propia caída**: el brazo «lista vieja» es la vara probándose a sí
misma. Si ese brazo diera «no fresco», el agujero nunca habría existido y la vara lo diría.
Y para el nivel 1:

    python3 qa/verify_public_vigilado.py --mutante

quita `"$SCI_WS/public"` de una copia del script en un temporal y exige que el contrato se
ponga rojo. No toca el archivo real.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "deploy/fase4/build_app.sh"

#: (nombre del stack, variable del árbol, los tres sitios que TIENEN que llevar `public`)
SITIOS = [
    ("Ciencia",   "SCI_WS",   'esta_fresco "$SCI_WS/dist/index.html"'),
    ("Educación", "EDU_WEB",  'esta_fresco "$EDU_WEB/.next/standalone/server.js"'),
    ("Finanzas",  "VIBE_WEB", 'esta_fresco "$VIBE_WEB/dist/index.html"'),
]

fallos: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        fallos.append(msg)


def lineas_de(texto: str, patron: str) -> list[str]:
    return [l.strip() for l in texto.splitlines() if re.search(patron, l)]


# ── NIVEL 1 · EL CONTRATO ────────────────────────────────────────────────────────────────
def contrato(script_txt: str) -> None:
    print("── contrato: los tres sitios nombran public en SUS DOS llamadas ──")
    for nombre, var, _ in SITIOS:
        fresco = lineas_de(script_txt, rf'esta_fresco "\${var}/')
        porque = lineas_de(script_txt, rf'por_que_rehornea "\${var}/')
        ok(len(fresco) == 1, f"{nombre}: exactamente una llamada a esta_fresco (hay {len(fresco)})")
        ok(len(porque) == 1, f"{nombre}: exactamente una llamada a por_que_rehornea (hay {len(porque)})")
        for etiqueta, ls in (("esta_fresco", fresco), ("por_que_rehornea", porque)):
            if not ls:
                continue
            ok(f'"${var}/public"' in ls[0], f"{nombre}: {etiqueta} vigila $" + var + "/public")


# ── NIVEL 2 · EL MECANISMO, CON LAS FUNCIONES REALES ─────────────────────────────────────
def extraer(script_txt: str, nombre: str) -> str:
    """La función tal cual está en `build_app.sh`. No una copia escrita acá: si alguien la
    cambia, esta vara mide la nueva — que es todo el punto."""
    m = re.search(rf"^{nombre}\(\) \{{.*?^\}}", script_txt, re.M | re.S)
    if not m:
        raise SystemExit(f"✗ no encontré la función {nombre}() en {SCRIPT}")
    return m.group(0)


def mecanismo(script_txt: str) -> None:
    print("── mecanismo: las funciones REALES contra un árbol donde sólo public/ es nuevo ──")
    fns = extraer(script_txt, "esta_fresco") + "\n" + extraer(script_txt, "por_que_rehornea") + "\n"

    with tempfile.TemporaryDirectory(prefix="vara-public-") as tmp:
        raiz = Path(tmp)
        (raiz / "src").mkdir()
        (raiz / "public").mkdir()
        (raiz / "dist").mkdir()
        (raiz / "src/app.tsx").write_text("viejo\n")
        (raiz / "dist/index.html").write_text("horneado\n")
        # El artefacto y las fuentes quedan VIEJOS; sólo `public/` es nuevo. Es exactamente
        # el caso «cambié la piel y no toqué el código».
        viejo = time.time() - 600
        for f in ("src/app.tsx", "dist/index.html"):
            os.utime(raiz / f, (viejo, viejo))
        (raiz / "public/aleph-piel.css").write_text(":root{}\n")   # lo único fresco

        def correr(args: list[str]) -> tuple[bool, str]:
            guion = fns + '\nif esta_fresco "$@"; then echo FRESCO; else echo NO_FRESCO; por_que_rehornea "$@"; fi\n'
            r = subprocess.run(["bash", "-c", guion, "bash", *args],
                               capture_output=True, text=True, timeout=30)
            return r.stdout.startswith("FRESCO"), r.stdout + r.stderr

        art = str(raiz / "dist/index.html")
        vieja = [art, str(raiz / "src")]
        nueva = [art, str(raiz / "src"), str(raiz / "public")]

        fresco_viejo, _ = correr(vieja)
        ok(fresco_viejo,
           "con la lista VIEJA (sin public) dice «fresco» — el agujero se reproduce, "
           "o sea que esta vara puede dar rojo")

        fresco_nuevo, salida = correr(nueva)
        ok(not fresco_nuevo, "con la lista NUEVA (con public) dice «no fresco» ⇒ el build corre")
        ok("aleph-piel.css" in salida,
           f"por_que_rehornea NOMBRA al culpable (aleph-piel.css) · dijo: {salida.strip().splitlines()[-1][:90]!r}")


def main() -> int:
    if not SCRIPT.is_file():
        print(f"✗ no está {SCRIPT}")
        return 2
    txt = SCRIPT.read_text()

    if "--mutante" in sys.argv:
        # La mutación NO toca el archivo real: se le saca `public` a Ciencia en una copia.
        print("── MUTANTE: se le quita $SCI_WS/public a Ciencia (en copia) y se exige rojo ──")
        mutado = txt.replace('"$SCI_WS/src" "$SCI_WS/public"', '"$SCI_WS/src"')
        if mutado == txt:
            print("✗ la mutación no aplicó: el texto que buscaba no está. La vara no está probada.")
            return 1
        contrato(mutado)
        if not fallos:
            print("\n✗ LA VARA ESTÁ ROTA: con Ciencia mutada el contrato siguió verde.")
            return 1
        print(f"\n✓ la vara puede dar rojo: {len(fallos)} afirmaciones cayeron con la mutación.")
        return 0

    contrato(txt)
    mecanismo(txt)
    print("")
    if fallos:
        print(f"✗ {len(fallos)} rojas")
        return 1
    print("✓ public/ vigilado en los tres stacks que no lo tenían, y el mecanismo lo prueba")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
