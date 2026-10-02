#!/usr/bin/env python3
"""verify_adjunto_no_se_pega_al_prompt.py — un documento adjunto no es texto del prompt.

EL DEFECTO, medido el 2026-08-29 con un adjunto real en Legal: el turno se quedaba en
«working» para siempre.

El render del puente ya tenía resuelto el caso de las IMÁGENES —su propio comentario
cuenta que antes se pegaban «~170 mil caracteres de base64 COMO TEXTO LITERAL en el
prompt»— pero los DOCUMENTOS nunca entraron en esa cuenta. Un PDF llega como
`{"type":"file","mediaType":"application/pdf","url":"data:…;base64,<megabytes>"}` y caía
en el `else` final, que hace `json.dumps(parte)`: los megabytes enteros adentro del
prompt. El CLI no se cae, se queda masticando, y la persona ve «working» hasta que se
aburre.

QUÉ CUIDA ESTA VARA. Que el adjunto viaje POR SU CANAL (bloque `document` por stdin, que
es lo que el modelo sabe leer) y que lo que no se puede leer se DIGA en vez de pegarse.

Correr:  python3 qa/verify_adjunto_no_se_pega_al_prompt.py
"""
from __future__ import annotations

import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "platform/assembler"))

from cli_brain.claude_cli import ClaudeCliProvider  # noqa: E402
from cli_brain.prompt_bridge import _texto_de  # noqa: E402

def _cli():
    """El proveedor sin construirlo: `build_stdin` no toca estado de instancia."""
    return ClaudeCliProvider.__new__(ClaudeCliProvider)


fallos: list[str] = []


def ok(cond, que):
    print(("  ✓ " if cond else "  ✗ ") + que)
    if not cond:
        fallos.append(que)


# Un PDF de ~750 KB: suficiente para que pegarlo al prompt se note.
PDF_B64 = "JVBERi0xLjQK" + ("QUJDRA" * 170_000)
DOCX_B64 = "UEsDBBQA" + ("WFla" * 40_000)


def parte_pdf(nombre="informe.pdf"):
    return {"type": "file", "mediaType": "application/pdf", "filename": nombre,
            "url": f"data:application/pdf;base64,{PDF_B64}"}


print("\n── el PDF no termina adentro del prompt ──")
imgs: list = []
texto = _texto_de([{"type": "text", "text": "Reformateá esto"}, parte_pdf()], imgs)
ok(PDF_B64[:80] not in texto,
   f"el base64 NO está en el prompt (el prompt quedó en {len(texto)} chars, no {len(PDF_B64)})")
ok(len(imgs) == 1 and imgs[0].get("clase") == "document",
   "el documento se acumuló por su canal, marcado como `document`")
ok("⟦documento 1: informe.pdf⟧" in texto,
   "y en el prompt queda una marca que dice cuál es y en qué orden viaja")

print("\n── la marca y el bloque son la misma cosa ──")
imgs2: list = []
t2 = _texto_de([{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                parte_pdf("segundo.pdf")], imgs2)
ok("⟦imagen 1⟧" in t2 and "⟦documento 2: segundo.pdf⟧" in t2,
   "imagen y documento comparten la numeración: 1 y 2, sin listas paralelas")

print("\n── llega al CLI como bloque `document`, no como imagen ──")
linea = _cli().build_stdin("hola", imgs)
bloques = json.loads(linea.decode("utf-8"))["message"]["content"]
tipos = [b.get("type") for b in bloques]
ok(tipos == ["text", "document"], f"los bloques son text + document (fueron {tipos})")
ok(bloques[1]["source"]["media_type"] == "application/pdf",
   "con su media_type real")

print("\n── lo que este cerebro NO puede leer se DICE, no se pega ──")
imgs3: list = []
t3 = _texto_de([{"type": "file", "filename": "acta.docx",
                 "mediaType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "url": f"data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{DOCX_B64}"}],
               imgs3)
ok(DOCX_B64[:80] not in t3, "el .docx tampoco se pega al prompt")
ok(imgs3 == [], "y NO se manda como documento: el modelo no lo sabría leer")
ok("acta.docx" in t3 and "no legible" in t3,
   "se dice qué llegó y que no se puede leer, con su nombre y su peso")

print("\n── las imágenes siguen andando igual ──")
imgs4: list = []
t4 = _texto_de([{"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}], imgs4)
ok(len(imgs4) == 1 and imgs4[0].get("clase") is None and "⟦imagen 1⟧" in t4,
   "una imagen sigue siendo una imagen, sin `clase`")
ok(json.loads(_cli().build_stdin("x", imgs4).decode())["message"]["content"][1]["type"] == "image",
   "y el CLI le sigue mandando un bloque `image`")

print("\n── y la puerta de las TOOLS, que es otra ──")
# Un resultado de tool llega como string y se pega tal cual: si trae un data-URL de un
# archivo, cuelga igual que el adjunto, sin que las correcciones anteriores se enteren.
resultado = 'Listo. La gráfica quedó en data:image/png;base64,' + ("QUJD" * 90_000)
t5 = _texto_de(resultado, [])
ok(len(t5) < 200, f"un data-URL gigante en un resultado de tool NO se pega (quedó en {len(t5)} chars)")
ok("base64 omitido" in t5 and "KB" in t5, "y se dice qué había y cuánto pesaba")
chico = "data:image/png;base64," + ("QUJD" * 50)
ok(chico in _texto_de(chico, []), "un data-URL chico (ícono, miniatura) pasa intacto")

print("\n" + ("PASS el adjunto viaja por su canal"
              if not fallos else f"FAIL {len(fallos)} punto(s)"))
sys.exit(1 if fallos else 0)
