#!/usr/bin/env python3
"""verify_piel_viajo.py — QUE LA PIEL ESTÉ ADENTRO DEL ARTEFACTO, NO SÓLO DEL ÁRBOL.
[rediseño · fase 3]

POR QUÉ ESTA ES LA VARA QUE MÁS IMPORTA
───────────────────────────────────────
Todo lo demás de esta fase se puede verificar leyendo o sirviendo el árbol. Pero la cara de
cada stack **viaja horneada**: lo que el usuario ve sale de su `dist/` (o de su binario), no
de sus fuentes. Entre las dos cosas hay un build, y un build que no corre deja la piel nueva
adentro del repo y la cara vieja adentro del producto — sin un solo error.

Ya pasó, y esta vara lo cazó apenas se escribió: los cuatro `dist/` del árbol y la `.app`
instalada tenían el `aleph-picker-unico.js` de agosto y **cero** rastro del `aleph-piel.js`
de la fase 1. O sea que el interruptor llevaba una fase entera sin viajar.

DOS PREGUNTAS DISTINTAS, Y SE RESPONDEN DISTINTO
───────────────────────────────────────────────
1. **¿Está en el `dist` horneado?** Si el `dist` es más NUEVO que las fuentes, tiene que
   estarlo: rojo si no. Si es más VIEJO, no puede estarlo y eso no es un defecto del
   mecanismo — es un build pendiente, y se dice así.
2. **¿Está en la `.app` instalada?** Misma regla contra la fecha del build.

Sin esa distinción la vara sería roja para siempre en cualquier máquina sin disco para
buildear, y una vara que siempre es roja se ignora igual que una que siempre es verde.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = Path("/Applications/Aleph.app/Contents/Frameworks")

#: (nombre, fuente del enganche, public/, dir de assets horneado, archivo donde vive el enganche)
#: ⚠️ El «horneado» NO tiene la misma forma en los cinco, y modelarlos igual fue mi primer
#: error: Next con `output: standalone` no deja un `index.html` al lado de sus assets — el
#: HTML renderizado vive en `.next/server/app/` y los assets en `standalone/public/`, y son
#: dos rutas distintas. Un modelo que asume `dist/index.html` para todos declara «no hay cara
#: horneada» sobre una cara que existe.
STACKS = [
    ("Oficina",   "third_party/openwork/apps/app/index.html",
                  "third_party/openwork/apps/app/public",
                  "third_party/openwork/apps/app/dist",
                  "third_party/openwork/apps/app/dist/index.html"),
    ("Finanzas",  "third_party/vibetrading/frontend/index.html",
                  "third_party/vibetrading/frontend/public",
                  "third_party/vibetrading/frontend/dist",
                  "third_party/vibetrading/frontend/dist/index.html"),
    ("Legal",     "third_party/dochaus/apps/web/index.html",
                  "third_party/dochaus/apps/web/public",
                  "third_party/dochaus/apps/web/dist",
                  "third_party/dochaus/apps/web/dist/index.html"),
    ("Ciencia",   "third_party/openscience/frontend/workspace/index.html",
                  "third_party/openscience/frontend/workspace/public",
                  "third_party/openscience/frontend/workspace/dist",
                  "third_party/openscience/frontend/workspace/dist/index.html"),
    ("Educación", "third_party/deeptutor/web/app/layout.tsx",
                  "third_party/deeptutor/web/public",
                  "third_party/deeptutor/web/.next/standalone/public",
                  "third_party/deeptutor/web/.next/standalone/.next/server/app/index.html"),
]

fallos: list[str] = []
pendientes: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        fallos.append(msg)


def nota(msg: str) -> None:
    print(f"  ~ {msg}")
    pendientes.append(msg)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def mirar(nombre: str, raiz: Path, dist_rel: str, pub: Path, fuente: Path, donde: str,
          idx_rel: str) -> None:
    dist = raiz / dist_rel
    idx = raiz / idx_rel
    if not idx.is_file():
        nota(f"{nombre} · {donde}: no hay cara horneada ({idx_rel}) — [no medible] sin build")
        return
    # ¿el horneado es posterior a la fuente? Si no, la piel NO PUEDE estar y no es un defecto.
    if idx.stat().st_mtime < fuente.stat().st_mtime:
        nota(f"{nombre} · {donde}: la cara horneada es MÁS VIEJA que su fuente "
             f"⇒ la piel todavía no viajó. [no verificado] hasta el próximo build")
        return
    txt = idx.read_text(errors="ignore")
    ok("aleph-piel.js" in txt, f"{nombre} · {donde}: el index horneado carga /aleph-piel.js")
    hoja = dist / "aleph-piel.css"
    ok(hoja.is_file(), f"{nombre} · {donde}: la hoja está adentro del horneado")
    if hoja.is_file() and (pub / "aleph-piel.css").is_file():
        ok(sha(hoja) == sha(pub / "aleph-piel.css"),
           f"{nombre} · {donde}: …y es byte-idéntica a la del árbol (no una copia vieja)")
    fdir = dist / "fonts"
    tiene = {f.name.split("-")[0] for f in fdir.glob("*.woff2")} if fdir.is_dir() else set()
    ok({"poppins", "instrumentserif", "jetbrainsmono"} <= tiene,
       f"{nombre} · {donde}: las tres familias viajaron ({len(tiene)} familias)")


#: [merge+build · 2026-09-07] LAS DOS FORMAS QUE ESTA VARA NO SABÍA LEER.
#: Ciencia y Diseño NO viajan como una carpeta `dist/` al lado del sidecar: Ciencia va
#: adentro del binario de su pack (PyInstaller) y Diseño adentro del `app.asar` de su runtime
#: de Electron, que a su vez viaja comprimido en un ZIP. Modelarlos como a los otros hacía
#: que la vara dijera «no hay cara horneada» sobre caras que SÍ están, y eso es peor que un
#: rojo: es un [no medible] falso, que se lee como «todavía no toca».
#:
#: ⚠️ Y NO ALCANZA CON BUSCAR `aleph-piel`: ese nombre aparece igual en el índice de un
#: paquete aunque el contenido sea de agosto. Se buscan CADENAS FECHADAS —cadenas que sólo
#: existen desde una obra concreta— así la vara distingue «viajó» de «viajó lo de HOY».
EMPAQUETADOS = [
    ("Ciencia", "third_party/openscience/bin/openscience", None),
    ("Diseño",  "third_party/codesign/apps/desktop/release/aleph-diseno-mac-arm64.zip",
                "Aleph Diseno.app/Contents/Resources/app.asar"),
]
#: (cadena, de qué obra nació). Si mañana se agrega otra, se agrega acá.
FECHADAS = [("--al-lienzo-h", "fase 5.2 · el triplete HSL de Finanzas"),
            ("data-aleph-ws", "fase 5.2 · el mapeo acotado por workspace"),
            ("MENU_FINANZAS", "fase 5.0 · el puente del menú de Finanzas")]


def mirar_empaquetado(nombre: str, raiz: Path, rel: str, dentro: str | None) -> None:
    art = raiz / rel
    if not art.is_file():
        nota(f"{nombre} · .app: no está su artefacto ({rel}) — [no medible]")
        return
    if dentro:
        import subprocess
        r = subprocess.run(["unzip", "-p", str(art), dentro], capture_output=True)
        if r.returncode != 0 or not r.stdout:
            nota(f"{nombre} · .app: no pude abrir {dentro} adentro del zip — [no medible]")
            return
        crudo = r.stdout
    else:
        crudo = art.read_bytes()
    ok(crudo.count(b"aleph-piel") > 0, f"{nombre} · .app: la piel está adentro del empaquetado")
    for cadena, obra in FECHADAS:
        ok(crudo.count(cadena.encode()) > 0,
           f"{nombre} · .app: y es la de HOY — lleva «{cadena}» ({obra})")


def main() -> int:
    print("── en el ÁRBOL horneado ──")
    for nombre, fuente_rel, pub_rel, dist_rel, idx_rel in STACKS:
        mirar(nombre, RAIZ, dist_rel, RAIZ / pub_rel, RAIZ / fuente_rel, "árbol", idx_rel)

    print("\n── en la .app INSTALADA ──")
    if not APP.is_dir():
        nota("no hay .app instalada — [no medible]")
    else:
        for nombre, fuente_rel, pub_rel, dist_rel, idx_rel in STACKS:
            if nombre == "Ciencia":
                continue  # viaja empaquetado, se mide abajo
            mirar(nombre, APP, dist_rel, RAIZ / pub_rel, RAIZ / fuente_rel, ".app", idx_rel)
        for nombre, rel, dentro in EMPAQUETADOS:
            mirar_empaquetado(nombre, APP, rel, dentro)

    print("")
    if pendientes:
        print(f"~ {len(pendientes)} [no verificado] · piden un build para poder afirmar nada:")
        for p in pendientes:
            print(f"    · {p}")
    if fallos:
        print(f"✗ {len(fallos)} rojas — hay cara horneada NUEVA que NO lleva la piel")
        return 1
    print("✓ donde hay cara horneada nueva, la piel está adentro")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
