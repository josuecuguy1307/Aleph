#!/usr/bin/env python3
"""verify_guardas_por_idioma.py — ninguna guarda decide por un idioma que la casa no habla.

QUÉ CLASE DE DEFECTO CAZA. Los stacks importados traen guardas que se arman leyendo PROSA:
un `re.compile` con vocabulario adentro —«buy», «price», 买入, 现价— que decide si una
muralla se levanta o no. Aleph corre en castellano. Si el vocabulario no lo incluye, la
guarda **no se arma**, y eso no falla ruidoso: falla en silencio y del lado peligroso.

MEDIDO, y por eso existe esta vara:
  · `_PRICE_CONTEXT_RE` (vibetrading/grounding.py) dejaba pasar «AAPL cerró a $412,77» —un
    precio que ninguna tool devolvió— y bloqueaba la MISMA frase en inglés. Se arregló.
  · Un mes después, `_ACTIONABLE_MARKET_RE`, en el MISMO archivo, seguía sin castellano:
    la guarda de identidad no se armaba para ningún pedido escrito en español.
  · Y con él, otras diez del mismo archivo.

O sea: se arregló una de doce, a mano, y nadie se enteró de las once. Esta vara existe para
que esa cuenta esté a la vista ANTES de buildear, en vez de aparecer en la cara del usuario.

NO ES UN LINTER DE ESTILO: sólo mira patrones que YA anclan por idioma. Un regex sin
vocabulario —fechas, números, símbolos— no le interesa y no lo nombra.

Correr:  python3 qa/verify_guardas_por_idioma.py
Salida:  0 si no hay guardas sordas al castellano · 1 si las hay.
"""
from __future__ import annotations

import io
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Dónde miramos. Los stacks importados y nuestra propia casa: la clase no distingue dueño.
ARBOLES = ("third_party", "platform", "product")

#: Lo que NO se recorre: dependencias y artefactos, que no son código nuestro ni del stack.
SALTAR = ("/node_modules/", "/.git/", "/dist/", "/build/", "/.next/", "/target/",
          "/site-packages/", "/__pycache__/", "/.venv/", "/vendor/",
          # Árboles de dependencias PRODUCIDOS por el build (`producir_research.sh`,
          # `producir_busqueda.sh`): son librerías de terceros, no guardas de nadie. Sin
          # esto la vara acusaba al tokenizador japonés de `transformers`.
          "/sala/research/lib/", "/sala/research/runtime/", "/sala/busqueda/searxng/")

_COMPILE = re.compile(r"(?:(_[A-Z0-9_]+)\s*=\s*)?re\.compile\(\s*((?:\s*r?[\"'].*?[\"'])+)", re.S)
_CJK = re.compile(r"[一-鿿]")

#: LA HUELLA DEL INGLÉS COMO VOCABULARIO, no como sintaxis. Una alternancia de palabras
#: enteras (`\bbuy\b|\bsell\b|…`) es alguien decidiendo por prosa. Tres o más para no
#: confundirla con un regex técnico que casualmente nombra una palabra.
_ALTERNANCIA_EN = re.compile(r"(?:\\b[a-z][a-z ]{2,}\\b\s*\|\s*){2,}\\b[a-z][a-z ]{2,}\\b")

#: ANCLAS DEL CASTELLANO. Raíces, no palabras completas: la prosa de un modelo no garantiza
#: ni tildes ni conjugación. Si el patrón trae una sola de éstas, la guarda ya oye español.
_ES = re.compile(
    r"compr|vend|precio|cotiza|cierre|cerr|apertur|objetiv|entrada|soporte|resistenc|"
    r"valuaci|cu[aá]nt|acci[oó]n|m[aá]xim|m[ií]nim|monto|cantidad|nivel|tasa|порcent|"
    r"porcent|fecha|a[ñn]o|mes\b|d[ií]a\b|privad|bolsa|cotiz",
    re.I,
)

#: EXENCIONES, con motivo escrito. Una guarda puede anclar en un idioma A PROPÓSITO cuando
#: su dominio es de ese idioma —un raspador de sanciones de la bolsa china no tiene por qué
#: entender español—. Se declara acá, no se silencia en el archivo del stack.
EXENTAS = {
    "third_party/vibetrading/agent/src/skills/ashare-pre-st-filter/scripts/fetch_sina_penalties.py":
        "raspa un sitio en chino: su vocabulario ES el dominio",
    "third_party/vibetrading/agent/src/tools/etf_holdings_tool.py":
        "parsea nombres de ETF del mercado chino, no prosa del usuario",
}


def archivos():
    for arbol in ARBOLES:
        base = os.path.join(RAIZ, arbol)
        if not os.path.isdir(base):
            continue
        for dp, _dns, fns in os.walk(base):
            if any(s in dp + "/" for s in SALTAR):
                continue
            for f in fns:
                if f.endswith((".py", ".ts", ".tsx")):
                    yield os.path.join(dp, f)


def guardas_sordas():
    """`(archivo, línea, constante, por_qué_ancla)` de cada guarda sin castellano."""
    fuera = []
    for ruta in archivos():
        rel = os.path.relpath(ruta, RAIZ)
        motivo_exenta = next((v for k, v in EXENTAS.items() if rel.startswith(k)), None)
        try:
            texto = io.open(ruta, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "re.compile" not in texto:
            continue
        for m in _COMPILE.finditer(texto):
            nombre, patron = m.group(1) or "(anónimo)", m.group(2)
            ancla = "chino" if _CJK.search(patron) else (
                "inglés" if _ALTERNANCIA_EN.search(patron) else None)
            # UN PATRÓN QUE COMPONE DESDE `idiomas` YA OYE CASTELLANO. Esto lo aprendí de
            # la propia vara: al mover el vocabulario a un módulo compartido —que era el
            # objetivo— el castellano dejó de estar en el texto del patrón y la vara siguió
            # acusando a guardas ya arregladas. Que el detector no vea el arreglo es el
            # detector fallando, no la guarda.
            compone = "idiomas." in texto[m.start():m.start() + len(patron) + 220]
            if not ancla or compone or _ES.search(patron):
                continue
            if motivo_exenta:
                continue
            fuera.append((rel, texto[:m.start()].count("\n") + 1, nombre, ancla))
    return fuera


def main() -> int:
    sordas = guardas_sordas()
    print("\n── guardas que deciden por idioma y NO oyen castellano ──\n")
    if not sordas:
        print("  (ninguna)\n\nPASS todas las guardas por idioma incluyen el castellano")
        return 0

    por_archivo: dict[str, list] = {}
    for rel, linea, nombre, ancla in sordas:
        por_archivo.setdefault(rel, []).append((linea, nombre, ancla))
    for rel in sorted(por_archivo):
        print(f"  {rel}")
        for linea, nombre, ancla in sorted(por_archivo[rel]):
            print(f"      :{linea:<5} {nombre:28} ancla en {ancla}")
        print()
    print(f"FAIL {len(sordas)} guarda(s) en {len(por_archivo)} archivo(s).")
    print("     Cada una decide con prosa que esta casa no escribe. Agregarle las anclas")
    print("     del castellano, o declararla en EXENTAS con el motivo.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
