#!/usr/bin/env python3
"""verify_adjunto_se_lee_como_texto.py — un documento que el modelo no puede recibir, se lee igual.

EL DEFECTO, visto en pantalla el 2026-08-29 en Oficina, dos veces con el mismo archivo:

    'file part media type application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    functionality not supported.

Lo tira `@ai-sdk/openai-compatible` al convertir el mensaje al formato de cable: ese formato
sólo sabe poner imágenes y PDF. El modelo NO puede RECIBIR un .docx — pero sí puede LEER su
contenido. Así que se le manda lo único que siempre entiende: texto.

SIN DEPENDENCIAS NUEVAS: los tres formatos de oficina son un ZIP con XML adentro y eso lo
abre la biblioteca estándar.

⚠️ LOS FIXTURES DE ACÁ REPRODUCEN FORMAS MEDIDAS EN ARCHIVOS REALES, no las cómodas. Es
deliberado: hoy mismo una vara de 5/5 verde probaba un caso que el producto nunca recorre
(el `.py` que existe en disco). En particular, una planilla real del dueño NO tenía
`sharedStrings` —usaba `t="inlineStr"`— y la primera versión devolvía 102 filas de números
sin una sola etiqueta.

Correr:  python3 qa/verify_adjunto_se_lee_como_texto.py
"""
from __future__ import annotations

import io
import os
import sys
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "platform/assembler"))

from cli_brain.documentos import texto_de  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"

fallos: list[str] = []


def ok(cond, que):
    print(("  ✓ " if cond else "  ✗ ") + que)
    if not cond:
        fallos.append(que)


def zip_con(archivos: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nombre, cuerpo in archivos.items():
            z.writestr(nombre, cuerpo)
    return buf.getvalue()


print("\n── el .docx: párrafos, en orden ──")
docx = zip_con({"word/document.xml": f"""<?xml version="1.0"?>
<w:document xmlns:w="{W}"><w:body>
  <w:p><w:r><w:t>Primera línea</w:t></w:r><w:r><w:t> y su continuación</w:t></w:r></w:p>
  <w:p><w:r><w:t>Segunda línea</w:t></w:r></w:p>
  <w:p></w:p>
</w:body></w:document>"""})
t, c = texto_de(docx, DOCX, "acta.docx")
ok(c == "" and "Primera línea y su continuación" in t,
   "los `runs` de un párrafo se unen en UNA línea, sin espacios de más")
ok(t.count("\n") == 1, "un párrafo vacío no agrega una línea en blanco de la nada")

print("\n── el .xlsx: LAS TRES formas en que una celda guarda su texto ──")
# `inlineStr` es la que rompió: una planilla real del dueño no tenía sharedStrings.
xlsx = zip_con({
    "xl/sharedStrings.xml": f'<?xml version="1.0"?><sst xmlns="{S}"><si><t>Compartida</t></si></sst>',
    "xl/worksheets/sheet1.xml": f"""<?xml version="1.0"?>
<worksheet xmlns="{S}"><sheetData>
  <row><c r="A1" t="inlineStr"><is><t>Encabezado</t></is></c><c r="B1" t="s"><v>0</v></c>
       <c r="C1"><v>42</v></c><c r="D1" t="b"><v>1</v></c><c r="E1"/></row>
</sheetData></worksheet>"""})
t, c = texto_de(xlsx, XLSX, "datos.xlsx")
ok("Encabezado" in t, "`inlineStr` — la que devolvía filas de números sin etiquetas")
ok("Compartida" in t, "`sharedStrings` por índice")
ok("42" in t, "el número tal cual")
ok("TRUE" in t, "el booleano como palabra, no como 1")

print("\n── el .pptx: una diapositiva por vez, en orden numérico ──")
def slide(txt):
    return f'<?xml version="1.0"?><p:sld xmlns:p="x" xmlns:a="{A}"><a:t>{txt}</a:t></p:sld>'
pptx = zip_con({"ppt/slides/slide10.xml": slide("Diez"),
                "ppt/slides/slide2.xml": slide("Dos")})
t, c = texto_de(pptx, PPTX, "charla.pptx")
ok(t.index("Dos") < t.index("Diez"),
   "slide2 va ANTES que slide10: se ordena por número, no alfabéticamente")

print("\n── lo que ya era texto pasa derecho ──")
t, c = texto_de("hola\nmundo".encode(), "text/markdown", "n.md")
ok(t == "hola\nmundo" and c == "", "un text/* se decodifica y listo")
t, c = texto_de(b'{"a":1}', "application/json", "d.json")
ok(t == '{"a":1}', "y un JSON también")

print("\n── y cuando NO se puede, se dice por qué ──")
t, c = texto_de(b"no soy un zip", DOCX, "roto.docx")
ok(t == "" and "no es un ZIP" in c, "un .docx que no es un ZIP: se nombra el archivo y la causa")
t, c = texto_de(zip_con({"word/document.xml": f'<w:document xmlns:w="{W}"><w:body/></w:document>'}),
                DOCX, "vacio.docx")
ok(t == "" and "no tiene texto extraíble" in c,
   "un .docx sin texto (escaneo) lo dice, en vez de mandar vacío")
t, c = texto_de(b"\x00\x01", "application/x-cosa-rara", "x.bin")
ok(t == "" and "no sé leer" in c, "un tipo desconocido se nombra, no se adivina")
ok(not (t == "" and c == ""), "NUNCA las dos vacías: un extractor mudo es lo que hay que evitar")

print("\n── el tope, dicho ──")
from cli_brain.documentos import TOPE_CHARS
grande = zip_con({"word/document.xml":
                  f'<w:document xmlns:w="{W}"><w:body>'
                  + "".join(f"<w:p><w:r><w:t>{'x'*100}</w:t></w:r></w:p>"
                            for _ in range(TOPE_CHARS // 100 + 50))
                  + "</w:body></w:document>"})
t, c = texto_de(grande, DOCX, "largo.docx")
ok(len(t) > TOPE_CHARS and "sin incluir" in t,
   "un documento largo se corta y DICE cuánto quedó afuera")

print("\n" + ("PASS el documento se lee como texto"
              if not fallos else f"FAIL {len(fallos)} punto(s)"))
sys.exit(1 if fallos else 0)
