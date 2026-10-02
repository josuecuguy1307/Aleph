# Avisos de fuentes
Textos OFL obtenidos 2026-09-13 de Google Fonts:
- instrumentserif: https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentserif/OFL.txt
- jetbrainsmono: https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/OFL.txt
- poppins: https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/OFL.txt
- outfit: https://raw.githubusercontent.com/google/fonts/main/ofl/outfit/OFL.txt
- newsreader: https://raw.githubusercontent.com/google/fonts/main/ofl/newsreader/OFL.txt
- hankengrotesk: https://raw.githubusercontent.com/google/fonts/main/ofl/hankengrotesk/OFL.txt
- spectral: https://raw.githubusercontent.com/google/fonts/main/ofl/spectral/OFL.txt

Los textos se conservan íntegros con sus avisos upstream en archivos *.OFL.txt.
Correspondencia de familias: fonts-estandar.css (Instrument Serif, JetBrains Mono, Poppins),
fonts-sistema.css (Outfit, Newsreader). EXACT-FILES.json identifica además Hanken Grotesk
y Spectral mediante metadatos y registra SHA256 de los 49 binarios. Ver ATTRIBUTIONS.md
para importación local.
Estos avisos no prueban por sí solos identidad binaria. Esa comprobación está ahora registrada
por archivo en UPSTREAM-PROVENANCE.json: A=49, B=0, C=0, mediante SHA256 calculado sobre
los artefactos oficiales de fonts.gstatic.com y comparado con los bytes locales intactos.
No son licencia de Aleph.

## Evidencia exacta y reproducción

UPSTREAM-PROVENANCE.json conserva consultas oficiales, User-Agent, CSS recibido y su digest,
URL/version de distribución `/vN/`, digest y tamaño de cada artefacto, familia/peso/estilo
declarados, subsets unicode-range, versión interna y aviso copyright/OFL correspondiente.
Los nombres locales basados en prefijos hash no se utilizan como prueba de identidad.
EXACT-FILES.json mantiene el inventario previo; la matriz docs/THIRD-PARTY-MATRIX.json
enlaza esta evidencia para cada uno de los 49 recursos.

Newsreader conserva ejes variables opsz=6..72 y wght=200..800. Las declaraciones locales
400/500/600 seleccionan pesos de ese mismo binario. La solicitud sin eje óptico entrega
otro artefacto; la consulta oficial con ambos ejes demuestra identidad de los tres subsets.
No se transformaron ni sustituyeron fuentes, ni se editaron declaraciones funcionales CSS.
Renombrar un archivo o reescribir una URL local no transforma sus bytes: clasificación A,
no B. No se propone ninguna sustitución.

Los siete avisos OFL se compararon contra google/fonts commit
809e4d8b8d7e9364a914909bb777679606c178b8, con URLs fijadas y hashes registrados.
Newsreader y Spectral sólo añaden un LF final al texto oficial; el resto coincide byte a byte.
Este commit fija los avisos, NO se atribuye como commit de compilación de los WOFF2.
La identidad probada es con artefactos alojados por el servicio oficial, no una reconstrucción
de su pipeline ni la identidad de quien realizó la descarga histórica.

Desde el root:

    PYTHONDONTWRITEBYTECODE=1 python3 qa/verify_font_upstream.py --offline
    PYTHONDONTWRITEBYTECODE=1 python3 qa/verify_font_upstream.py

La segunda orden usa red y devuelve nueva evidencia por stdout sin escribir archivos;
la primera verifica inventario, hashes locales, avisos y CSS registrado sin red.
Si el servicio cambia versiones, no aprobar automáticamente nuevas discrepancias.

## Alcance explícito

Este cierre cubre los 49 WOFF2 de product/app/design/vendor/fonts, no todos los archivos
de extensión WOFF2 del árbol. Git contiene 215 en total: 69 bajo product/app/design
y 146 bajo terceros (codesign, deeptutor, dochaus, openscience, openwork y vibetrading).
Los otros 166 no se sustituyeron ni clasificaron en esta sesión. Su presencia en Git
no demuestra que entren en el paquete final; esta evidencia no certifica su procedencia.
No declarar cerrado todo el conjunto de fuentes del producto usando únicamente este resultado.
