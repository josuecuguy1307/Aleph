"""
verify_oficina_puente.py — VARA de la fila de Oficina en el puente.
[Convergencia · superficie 7 · punto 1]

EL AGUJERO QUE ESTA VARA CUIDA, MEDIDO ANTES DE TAPARLO
--------------------------------------------------------
`openwork.js:210` posteaba a `POST /v1/workspaces/artifacts` desde que existe el
plugin, y `bridge.TABLE` no tenía la clave `oficina`. Corrido contra el borde HTTP
real con el payload literal del plugin, las SEIS clases de `claseDe()` devolvían:

    document · spreadsheet · presentation · page · image · file
      →  HTTP 422  error='workspace_kind_unknown'

y el propio plugin se las tragaba a su bitácora (`openwork.js:220-223`). El 100 % de
lo que Oficina produce se perdía, y se perdía elegantemente: con causa, con copy, sin
romper el turno, y sin que nadie se enterara.

POR QUÉ EL PAYLOAD DE ESTA VARA ES BASE64 Y NO TEXTO
-----------------------------------------------------
Porque es el REAL. `openwork.js:196` decide la codificación con `esBinario(rel)`, así
que `.docx`, `.xlsx`, `.pptx`, `.pdf` y los rasters llegan en base64. Una vara que
mande todo en utf8 mide un stack que no existe — y de hecho la primera versión de
esta obra lo hizo y se comió un defecto: un `.png` declarado utf8 armaba
`data:image/png;utf8,…`, un URI bien formado que nadie puede pintar.

LO QUE SE MIDE
  1 · las seis clases cruzan (ninguna 422)
  2 · cada una aterriza en el tipo que la tabla declara, y las degradaciones son las
      DECLARADAS (el `assert` de `cross()` no se puede saltar en silencio)
  3 · lo binario que Aleph no puede re-derivar cae a FICHA, no a un `content` con una
      pared de base64 adentro
  4 · la imagen es la única excepción, y su data URI es de verdad
  5 · `ACCEPTS` está declarado (sin fila, la invariante de la ley 7 se rompe)

    product/backend/.venv/bin/python qa/verify_oficina_puente.py
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import tempfile
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parent
for _p in (str(_RAIZ / "product" / "backend"), str(_RAIZ / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("PUPPET_MOTOR_PERSISTE", "0")
os.environ["ALEPH_DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="vara-oficina-")) / "data")

from artifacts import bridge                          # noqa: E402
from artifacts import vocabulary as vocab             # noqa: E402

_fallos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))
    return bool(cond)


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


print("=" * 80)
print("VARA · LA FILA DE OFICINA EN EL PUENTE  [Convergencia · superficie 7]")
print("=" * 80)

# PNG mínimo REAL (1×1, transparente) — bytes de verdad, no un string que dice «png».
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def payload(rel: str, contenido: bytes | str, binario: bool) -> dict:
    """El `datos` EXACTO de openwork.js:190-201, con su regla de codificación."""
    d = {"name": rel.split("/")[-1], "path": f"/proyecto/{rel}",
         "bytes": len(contenido), "rel": rel}
    if binario:
        d["encoding"] = "base64"
        d["content"] = base64.b64encode(contenido).decode()
    else:
        d["encoding"] = "utf8"
        d["content"] = contenido
    return d


# (kind de claseDe, archivo, contenido, ¿esBinario?, tipo esperado, ¿ficha?)
CASOS = [
    ("document",     "notas.md",         "# Acta\n\ntexto",        False, "documento", False),
    ("document",     "informe.docx",     b"PK\x03\x04docx",        True,  "informe",   True),
    ("spreadsheet",  "gastos.csv",       "eje,valor\ncosto,10",    False, "planilla",  False),
    ("spreadsheet",  "gastos.xlsx",      b"PK\x03\x04xlsx",        True,  "informe",   True),
    ("presentation", "pitch.pptx",       b"PK\x03\x04pptx",        True,  "informe",   True),
    ("page",         "nota.html",        "<h1>hola</h1>",          False, "web",       False),
    ("image",        "logo.png",         _PNG,                     True,  "imagen",    False),
    ("image",        "plano.svg",        "<svg xmlns='x'/>",       False, "imagen",    False),
    ("file",         "adjunto.bin",      "cualquier cosa",         False, "informe",   True),
]

seccion("1 · las seis clases de `claseDe()` cruzan — ninguna 422")

_kinds_vistos = set()
_obras = {}
for kind, rel, cont, binario, esperado, es_ficha in CASOS:
    _kinds_vistos.add(kind)
    etiqueta = f"{kind}/{rel}"
    try:
        obra = bridge.cross("oficina", {"kind": kind, "name": rel, "data": payload(rel, cont, binario)})
        _obras[etiqueta] = obra
        ok(obra["type"] == esperado, f"{etiqueta:26s} → {esperado}", f"dio {obra.get('type')}")
    except bridge.BridgeError as e:
        ok(False, f"{etiqueta:26s} → {esperado}", f"BridgeError {e.code}")
        _obras[etiqueta] = None

# Las SEIS clases que el plugin puede emitir están cubiertas — no cinco.
_declaradas = set(bridge.kinds("oficina"))
ok(_declaradas == {"document", "spreadsheet", "presentation", "page", "image", "file"},
   "la tabla declara las SEIS clases de claseDe(), ni una menos", str(sorted(_declaradas)))

# Y las seis salen del código de Oficina, no de la cabeza del que escribió la vara.
_plugin = (_RAIZ / "platform" / "workspaces" / "plugins" / "openwork.js").read_text(encoding="utf-8")
_emitidas = set(re.findall(r'return "([a-z]+)"', _plugin.split("function claseDe")[1].split("}")[0] + "}"))
ok(_emitidas <= _declaradas,
   "cada `return` de claseDe() tiene fila en la tabla", f"sin fila: {sorted(_emitidas - _declaradas)}")

seccion("2 · lo binario que Aleph no puede re-derivar cae a FICHA, no a base64 crudo")
# CAÍDA: si `_texto_utf8` dejara pasar el base64, estos tres darían `content` con la
# pared de caracteres adentro y el usuario vería basura llamada documento.

for etiqueta in ("document/informe.docx", "spreadsheet/gastos.xlsx", "presentation/pitch.pptx"):
    o = _obras.get(etiqueta) or {}
    cuerpo = str(o.get("content") or "")
    ok(cuerpo.startswith("##"), f"{etiqueta:26s} es una ficha markdown", cuerpo[:40])
    ok("PK" not in cuerpo and "cGs" not in cuerpo,
       f"{etiqueta:26s} NO lleva los bytes crudos adentro", cuerpo[:60])

seccion("3 · el texto utf8 llega ENTERO y con su tipo rico")

ok((_obras.get("document/notas.md") or {}).get("content") == "# Acta\n\ntexto",
   "un .md cruza su texto tal cual")
ok((_obras.get("page/nota.html") or {}).get("content") == "<h1>hola</h1>",
   "un .html cruza como `web` — se puede volver a bajar en su formato de origen")
_csv = _obras.get("spreadsheet/gastos.csv") or {}
ok(_csv.get("cols") == ["eje", "valor"] and _csv.get("rows") == [["costo", "10"]],
   "un .csv se parte en cols+rows: el separador ya estaba en el dato (FORMA)",
   json.dumps({"cols": _csv.get("cols"), "rows": _csv.get("rows")}, ensure_ascii=False))

seccion("4 · la imagen: el único caso donde los bytes cambian de sobre")
# CAÍDA: sin `_imagen_base64_o_ficha`, `_imagen_o_ficha` exige `data_uri` y manda a
# ficha TODAS las imágenes de Oficina — que fue el defecto que la auditoría midió.
#
# ⚠️ EL CAMPO ERA `data_uri`, Y ESTA VARA ESTABA VERDE MIDIÉNDOLO. Es el caso de manual de
# «una vara puede ser verde y no medir nada»: afirmaba que el sobre se armaba bien, y era
# cierto — pero el sobre iba dirigido a un campo que NO CONSUME NADIE. El renderer lee
# `a.content || a.url` (`product/app/design/render/sala-render.js:577`) y su validador de
# forma exige `content` (`:745`); el único productor vivo de `imagen` en el árbol también
# manda `content` (`product/belts/medicina/segmentacion_server.py:536`). O sea que estas
# tres líneas certificaban en verde una imagen que en pantalla decía «Sin imagen.».
# Ahora la vara mide el campo que la pantalla lee.

_png = _obras.get("image/logo.png") or {}
ok(str(_png.get("content", "")).startswith("data:image/png;base64,"),
   "un .png base64 se envuelve en un data URI de imagen", str(_png.get("content"))[:48])
# Y los bytes son los MISMOS: el sobre cambió, el dato no.
_dentro = str(_png.get("content", "")).split(",", 1)[-1]
ok(base64.b64decode(_dentro) == _PNG, "…y los bytes de adentro son idénticos a los que entraron")
ok(str((_obras.get("image/plano.svg") or {}).get("content", "")).startswith("data:image/svg+xml;utf8,"),
   "un .svg (utf8) se envuelve igual")
# La obra NO puede llevar una llave de más: con cuatro, `router.py:6064` la marca RICA y
# guarda el JSON entero adentro de `content`, que es el otro camino al marco vacío.
ok(set(_png) == {"type", "title", "content"},
   "la imagen sale con las tres llaves justas — ni una de más", json.dumps(sorted(_png)))

# El defecto que destapó la sonda: un raster declarado utf8 NO se envuelve.
_raro = bridge.cross("oficina", {"kind": "image", "name": "logo.png",
                                 "data": payload("logo.png", "esto no son pixeles", False)})
ok(_raro["type"] == "informe" and not str(_raro.get("content", "")).startswith("data:"),
   "un .png declarado utf8 cae a ficha — jamás un data URI que nadie puede pintar",
   json.dumps(_raro, ensure_ascii=False)[:80])

seccion("5 · la invariante de la ley 7: quien tiene filas declara qué acepta")
# CAÍDA: sin la entrada en ACCEPTS, `accepts('oficina')` vuelve a `()` y el destino
# dice `nadie_lo_reclama` para todo lo que Oficina sí sabe recibir.

_acc = bridge.accepts("oficina")
ok(_acc != (), "`oficina` declara qué acepta de vuelta", str(_acc))
ok("oficina" not in bridge.SOLO_PRODUCEN, "…y no es un modo: es un lugar a donde mandar trabajo")
ok(set(_acc) <= set(vocab.CANONICAL), "todo lo que acepta es canónico", str(_acc))
# Simetría declarada: acepta las mismas formas que sabe producir, más la prosa común.
ok(set(_acc) == {"documento", "planilla", "presentacion", "informe"},
   "acepta las formas que su propio claseDe() produce, + informe", str(sorted(_acc)))
ok(bridge.claims("oficina", "documento") and not bridge.claims("oficina", "web"),
   "reclama `documento` y NO `web` — su cara es una suite, no un visor")

print()
print("=" * 80)
print("TODO VERDE" if _fallos == 0 else f"{_fallos} FALLO(S)")
print("=" * 80)
sys.exit(1 if _fallos else 0)
