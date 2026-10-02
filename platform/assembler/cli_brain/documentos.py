"""Sacarle el TEXTO a un documento que el modelo no puede leer en crudo.

POR QUÉ EXISTE. Un `.docx` adjunto muere antes de llegar a ningún modelo: el conversor al
formato de cable (`@ai-sdk/openai-compatible`) sólo sabe poner imágenes y PDF, y para
cualquier otra cosa tira `file part media type … functionality not supported`. Visto en
pantalla el 2026-08-29 en Oficina, dos veces seguidas, con el mismo archivo.

El modelo SÍ puede leer el contenido — lo que no puede es recibirlo así. Así que se le manda
lo único que siempre entiende: texto.

SIN DEPENDENCIAS NUEVAS, y eso es deliberado. Los tres formatos de oficina son un ZIP con
XML adentro, y eso lo abre la biblioteca estándar. Agregar `python-docx`/`openpyxl` al pack
sería sumar peso y superficie para leer lo que ya se puede leer.

LO QUE NO HACE: no interpreta, no resume y no adivina. Saca el texto que hay, en orden, y si
no puede dice por qué. Un extractor que devuelve algo parecido es peor que uno que falla.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile

#: Lo que sabemos abrir, por media type. El valor es la función que saca el texto.
#: Cada uno es un ZIP con XML adentro; cambia dónde vive el texto y cómo se separa.
_OOXML = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}

#: Los que ya son texto y sólo hay que decodificar.
_TEXTO_PLANO = re.compile(
    r"^(?:text/|application/(?:json|xml|yaml|x-yaml|toml|x-toml|csv|markdown)|"
    r"application/.*\+(?:json|xml)$)", re.IGNORECASE)

#: Tope de lo que se manda. Un documento largo entero puede comerse la ventana; se corta y
#: se DICE, que es distinto de truncar en silencio.
TOPE_CHARS = 200_000


def _texto_de_xml(datos: bytes, etiqueta: str, separador: str) -> list[str]:
    """Todos los nodos `etiqueta` de un XML, en orden, como texto."""
    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError:
        return []
    # OOXML usa namespaces y el prefijo cambia entre archivos: se casa por el nombre local.
    trozos = [(n.text or "") for n in raiz.iter()
              if n.tag.rsplit("}", 1)[-1] == etiqueta]
    return [t for t in (s.strip() for s in trozos) if t] if separador else trozos


def _docx(z: zipfile.ZipFile) -> str:
    """El cuerpo del documento: cada `<w:t>` es un pedazo de texto de un párrafo."""
    partes = []
    for nombre in ("word/document.xml",) + tuple(
            n for n in z.namelist() if n.startswith("word/header") or n.startswith("word/footer")):
        try:
            datos = z.read(nombre)
        except KeyError:
            continue
        try:
            raiz = ET.fromstring(datos)
        except ET.ParseError:
            continue
        # El párrafo es la unidad de línea; adentro, cada `t` es un run.
        for p in raiz.iter():
            if p.tag.rsplit("}", 1)[-1] != "p":
                continue
            linea = "".join((n.text or "") for n in p.iter()
                            if n.tag.rsplit("}", 1)[-1] == "t")
            if linea.strip():
                partes.append(linea)
    return "\n".join(partes)


def _xlsx(z: zipfile.ZipFile) -> str:
    """Las celdas, hoja por hoja. Las cadenas viven en una tabla compartida."""
    compartidas: list[str] = []
    try:
        raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in raiz.iter():
            if si.tag.rsplit("}", 1)[-1] == "si":
                compartidas.append("".join((n.text or "") for n in si.iter()
                                           if n.tag.rsplit("}", 1)[-1] == "t"))
    except (KeyError, ET.ParseError):
        pass
    salida = []
    for nombre in sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet")):
        try:
            raiz = ET.fromstring(z.read(nombre))
        except (KeyError, ET.ParseError):
            continue
        salida.append(f"--- {nombre.rsplit('/', 1)[-1]} ---")
        for fila in raiz.iter():
            if fila.tag.rsplit("}", 1)[-1] != "row":
                continue
            celdas = []
            for c in fila:
                if c.tag.rsplit("}", 1)[-1] != "c":
                    continue
                # ⚠️ UNA CELDA GUARDA SU TEXTO DE TRES FORMAS Y HAY QUE CONOCER LAS TRES.
                # Esto lo escribió una medición, no la especificación: con una planilla real
                # del dueño la extracción devolvía 102 filas de NÚMEROS y ni una etiqueta.
                # El archivo no tenía `sharedStrings` —usa `t="inlineStr"` con el texto
                # adentro de un `<is>`— y mi versión sólo miraba `<v>`. Una tabla sin sus
                # encabezados es peor que no mandar nada: el modelo la lee y no sabe qué es.
                tipo = c.get("t")
                if tipo == "inlineStr":
                    celdas.append("".join((n.text or "") for n in c.iter()
                                          if n.tag.rsplit("}", 1)[-1] == "t"))
                    continue
                v = next((n.text for n in c.iter()
                          if n.tag.rsplit("}", 1)[-1] == "v"), None)
                if v is None:
                    celdas.append("")
                elif tipo == "s":
                    # `t="s"` significa que el valor es un ÍNDICE a la tabla compartida.
                    try:
                        celdas.append(compartidas[int(v)])
                    except (ValueError, IndexError):
                        celdas.append("")
                elif tipo == "b":
                    celdas.append("TRUE" if v == "1" else "FALSE")
                else:
                    # Número, fecha o resultado de fórmula (`t="str"`): tal cual.
                    celdas.append(v)
            if any(x.strip() for x in celdas):
                salida.append("\t".join(celdas))
    return "\n".join(salida)


def _pptx(z: zipfile.ZipFile) -> str:
    """El texto de cada diapositiva, en orden de número."""
    def orden(n: str) -> int:
        m = re.search(r"slide(\d+)\.xml$", n)
        return int(m.group(1)) if m else 0

    salida = []
    for nombre in sorted((n for n in z.namelist()
                          if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=orden):
        lineas = _texto_de_xml(z.read(nombre), "t", "\n")
        if lineas:
            salida.append(f"--- {nombre.rsplit('/', 1)[-1]} ---")
            salida.extend(lineas)
    return "\n".join(salida)


_EXTRACTORES = {"docx": _docx, "xlsx": _xlsx, "pptx": _pptx}


def texto_de(datos: bytes, media_type: str, nombre: str = "") -> tuple[str, str]:
    """El texto de un documento, o la causa de por qué no se pudo.

    Args:
        datos: El archivo entero.
        media_type: Su tipo declarado.
        nombre: Su nombre, para poder nombrarlo en el resultado.

    Returns:
        `(texto, causa)`. Con texto, `causa` es "". Sin texto, `causa` dice qué pasó — y
        NUNCA se devuelven las dos cosas vacías: un extractor mudo es lo que hay que evitar.
    """
    mt = (media_type or "").split(";", 1)[0].strip().lower()
    etiqueta = nombre or "adjunto"

    if _TEXTO_PLANO.match(mt):
        for codec in ("utf-8", "latin-1"):
            try:
                return datos.decode(codec), ""
            except UnicodeDecodeError:
                continue
        return "", f"{etiqueta}: es texto declarado pero no pude decodificarlo"

    clase = _OOXML.get(mt)
    if not clase:
        return "", f"{etiqueta}: no sé leer {mt or 'un tipo sin declarar'}"

    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
    except zipfile.BadZipFile:
        return "", f"{etiqueta}: dice ser {clase} pero no es un ZIP válido"

    with z:
        try:
            texto = _EXTRACTORES[clase](z)
        except Exception as e:  # noqa: BLE001 — un archivo roto se dice, no se traga
            return "", f"{etiqueta}: no pude leer el {clase} ({type(e).__name__})"

    if not texto.strip():
        return "", f"{etiqueta}: el {clase} no tiene texto extraíble (¿imágenes o escaneo?)"
    if len(texto) > TOPE_CHARS:
        texto = texto[:TOPE_CHARS] + (
            f"\n\n[…{len(texto) - TOPE_CHARS} caracteres más de {etiqueta} sin incluir: "
            f"pasa el tope de {TOPE_CHARS}]")
    return texto, ""
