"""
artifact_export.py — DESCARGA POR TIPO.

Convierte el CONTENIDO de una obra (lo que se ve) en el ARCHIVO REAL de su formato —
NO el HTML del render, NO un markdown disfrazado — y lo PERSISTE (cache por contenido):
descargar dos veces NO regenera; editar la obra (contenido nuevo) regenera una vez.

Por tipo (primer formato = default):
  planilla  → .xlsx (openpyxl, celdas reales) · .csv      ← parsea la tabla markdown
  informe   → .md · .pdf (reportlab) · .docx (python-docx)
  documento → .md · .pdf · .docx
  presentacion → .pptx (python-pptx, un slide por encabezado) · .md
  web       → .html
  dashboard → .html · .csv                                ← datos de los bloques ```chart
  imagen    → .png/.jpg/.svg  (decodifica el data-URL)
  3d        → .html            (la escena three.js es html/js)

Libs puras (openpyxl/python-docx/reportlab) + stdlib.

[Gate 4 · Fase 2] Cache under aleph_paths.data_root()/artifact_downloads — the old
`parents[4]` fell inside `_MEIPASS` under PyInstaller (censo §J.1). The cache is
NOT migrated, on purpose: it is regenerable by content (see `export` docstring —
downloading twice does not regenerate; migrating a cache is carrying dead weight).
The per-type FORMATS table moved into artifacts.vocabulary (the ONE vocabulary —
keeping a local dict would have bred the fifth parallel list); values are the
exact mirror of the old table, zero behavior change.
"""
from __future__ import annotations

import base64
import csv as _csv
import hashlib
import io
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aleph.artifacts")

# Old arithmetic — kept ONLY as the dev fallback when platform/ is unreachable.
_REPO = Path(__file__).resolve().parents[4]
_LEGACY_DL_ROOT = _REPO / "product" / "backend" / "data" / "artifact_downloads"

_DEFAULT_FORMATS = ["md"]
_ADVERTISED = set()


def dl_root() -> Path:
    """Where the export cache lives (client → user data dir; control → tree)."""
    try:
        import aleph_paths
        return aleph_paths.data_root() / "artifact_downloads"
    except ImportError:
        plat = str(_REPO / "platform")
        if plat not in sys.path and (_REPO / "platform").is_dir():
            sys.path.insert(0, plat)
        try:
            import aleph_paths
            return aleph_paths.data_root() / "artifact_downloads"
        except Exception:
            pass
    except Exception:
        pass
    return _LEGACY_DL_ROOT


def _vocab():
    try:
        from artifacts import vocabulary
        return vocabulary
    except ImportError:
        plat = str(_REPO / "platform")
        if plat not in sys.path and (_REPO / "platform").is_dir():
            sys.path.insert(0, plat)
        try:
            from artifacts import vocabulary
            return vocabulary
        except ImportError:
            return None

_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "html": "text/html; charset=utf-8",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "svg": "image/svg+xml", "gif": "image/gif", "webp": "image/webp",
    "txt": "text/plain; charset=utf-8",
}


def formats_for(type_: str) -> list:
    """Per-type export formats from THE vocabulary (first = default). If the
    vocabulary is unreachable: degrade to ["md"] with a visible log — honest
    degradation, never a local copy of the table."""
    v = _vocab()
    if v is None:
        if "vocab" not in _ADVERTISED:
            log.warning("artifact_export: vocabulary unavailable — all types fall to %s",
                        _DEFAULT_FORMATS)
            _ADVERTISED.add("vocab")
        return list(_DEFAULT_FORMATS)
    return v.formats_for(type_)


def default_format(type_: str) -> str:
    return formats_for(type_)[0]


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(s or "").strip())[:80] or "obra"


# ── parseo de tabla markdown → filas de celdas ──────────────────────────────────
def _parse_md_table(content: str):
    """Devuelve [ [celda,...], ... ] (1ra fila = header) de una tabla markdown GitHub.
    None si no hay tabla."""
    rows = []
    for raw in (content or "").splitlines():
        l = raw.strip()
        if not (l.startswith("|") and l.count("|") >= 2):
            continue
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        # fila separadora |---|:--:|  → se descarta
        if cells and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != ""):
            continue
        rows.append(cells)
    return rows or None


def _fallback_rows(content: str):
    """Sin tabla markdown: cada línea no vacía = fila; separa por tab/coma si hay."""
    out = []
    for raw in (content or "").splitlines():
        l = raw.rstrip()
        if not l.strip():
            continue
        if "\t" in l:
            out.append(l.split("\t"))
        elif "," in l and l.count(",") <= 12:
            out.append([c.strip() for c in l.split(",")])
        else:
            out.append([l.strip()])
    return out or [["(vacío)"]]


def _coerce(x: str):
    """Texto → número cuando corresponde (para que la celda sea numérica de verdad)."""
    s = (x or "").strip()
    if re.fullmatch(r"-?\d{1,15}", s):
        try:
            return int(s)
        except ValueError:
            return s
    if re.fullmatch(r"-?\d*\.\d+", s):
        try:
            return float(s)
        except ValueError:
            return s
    return s


def _rows_for_grid(content: str):
    return _parse_md_table(content) or _fallback_rows(content)


# ── generadores por formato ─────────────────────────────────────────────────────
def _gen_xlsx(content: str, title: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = (_safe(title) or "Datos")[:31]
    rows = _rows_for_grid(content)
    for r in rows:
        ws.append([_coerce(c) for c in r])
    if rows:
        for cell in ws[1]:
            cell.font = Font(bold=True)
        # ancho de columna aproximado
        ncols = max(len(r) for r in rows)
        for ci in range(1, ncols + 1):
            width = max((len(str(r[ci - 1])) for r in rows if ci - 1 < len(r)), default=8)
            ws.column_dimensions[ws.cell(row=1, column=ci).column_letter].width = min(48, max(10, width + 2))
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _gen_csv(content: str, title: str) -> bytes:
    rows = _rows_for_grid(content)
    sio = io.StringIO()
    w = _csv.writer(sio)
    for r in rows:
        w.writerow(r)
    return sio.getvalue().encode("utf-8-sig")  # BOM → Excel abre acentos bien


def _gen_md(content: str, title: str) -> bytes:
    body = content or ""
    if title and not body.lstrip().startswith("#"):
        body = "# " + title.strip() + "\n\n" + body
    return body.encode("utf-8")


def _md_inline(s: str) -> str:
    """**bold**/*italic*/`code` → tags reportlab; escapa &<>."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<i>\1</i>", s)
    s = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', s)
    return s


#: `---`, `***` o `___` solos en su línea son una REGLA HORIZONTAL de markdown, no texto.
#: VISTO EN EL PDF: se dibujaban como el literal «---» entre las láminas, tres guiones
#: sueltos arriba de cada título. No es un caso raro: el modelo separa secciones así.
#: ⚠️ NO confundir con la línea `|---|---|` de una tabla (esa ya la saltea el bloque de
#: tablas) ni con un setext heading (`Título` + `---` en la línea siguiente): esto exige la
#: línea SOLA, que es lo que la distingue.
_RE_REGLA = re.compile(r"^\s*([-*_])\1{2,}\s*$")

def _chart_normalizado(spec: dict):
    """El spec de un ```chart, en UNA sola forma: `(labels, [(nombre, data)])`. `None` si no.

    POR QUÉ EXISTE, y por qué es uno solo. Tres funciones de este mismo archivo leían el
    spec por su cuenta y las tres se equivocaban distinto:

        `_chart_a_filas`  (la tabla del pdf/docx)   `labels`/`series` en la RAÍZ o None
        `_chart_a_svg`    (el gráfico del html)     ídem
        `_gen_dashboard_csv`                        `series or data`, y con Chart.js
                                                    reventaba con `KeyError: 0`

    MEDIDO en la `.app` instalada (sidecar 30cde224): el modelo emitió la forma de Chart.js
    —`{"type":"bar","data":{"labels":[…],"datasets":[{"label":…,"data":[…]}]}}`— las dos
    primeras devolvieron `None` y **el JSON crudo salió como TEXTO adentro del .html que
    baja el usuario**. Es el mismo defecto que T2.7 y T2.12 cerraron para pdf/docx/pptx,
    entrando por otra puerta. Las dos formas son legítimas y la de Chart.js es la que más
    abunda: el modelo va a emitir cualquiera de las dos y ninguna es un error suyo.

    Un solo lector, entonces. Si mañana aparece una tercera forma se agrega ACÁ y las tres
    superficies la ganan juntas — que es justo lo que no pasó con las dos que ya había.

    SE ADAPTA LA FORMA, JAMÁS EL DATO (`platform/artifacts/bridge.py`): esto sólo renombra
    y desanida. Ningún valor se convierte, se rellena ni se descarta — un `null` sigue
    siendo un hueco cuando llega al llamador, y una forma que no se reconoce devuelve
    `None` en vez de forzar una lectura.
    """
    if not isinstance(spec, dict):
        return None

    # Chart.js anida todo bajo `data`; la forma de la raíz lo tiene al lado de `labels`.
    cuerpo = spec.get("data") if isinstance(spec.get("data"), dict) else spec

    labels = cuerpo.get("labels")
    if not isinstance(labels, list):
        labels = cuerpo.get("x")
    if not isinstance(labels, list) or not labels:
        return None

    crudas = None
    for clave in ("series", "datasets", "data"):
        cand = cuerpo.get(clave)
        if isinstance(cand, list) and cand:
            crudas = cand
            break
    if crudas is None:
        return None

    # Una lista de números sueltos es UNA serie sin nombre; el nombre sale del spec.
    if not isinstance(crudas[0], dict):
        if not all(isinstance(v, (int, float)) or v is None for v in crudas):
            return None
        return labels, [(str(spec.get("title") or spec.get("type") or "serie"), list(crudas))]

    fuera = []
    for s in crudas:
        if not isinstance(s, dict):
            return None
        datos = s.get("data")
        if not isinstance(datos, list):
            datos = s.get("values")
        if not isinstance(datos, list):
            return None                       # forma desconocida ⇒ no se fuerza
        fuera.append((str(s.get("name") or s.get("label") or "serie"), list(datos)))
    return labels, fuera


def _chart_a_filas(spec: dict) -> Optional[list]:
    """El bloque ```chart, como TABLA. `None` si no se puede sin inventar nada.

    SE ADAPTA LA FORMA, JAMÁS EL DATO (`platform/artifacts/bridge.py`). Un chart declara
    `labels` y `series[{name,data}]`: los MISMOS números en una tabla son el mismo dato en
    otro envase — no se agrega ni se quita información, y el que abre el .pdf ve los valores
    que la pantalla graficó en vez de un JSON.

    EL DEFECTO QUE TAPA, medido leyendo `_gen_pdf`: no había ninguna rama para bloques
    cercados, así que cada línea del JSON caía en el `else` final y se dibujaba COMO PROSA.
    El usuario veía en pantalla una tabla y un gráfico, bajaba el archivo, y encontraba
    `{"type":"line","labels":[...]}` desparramado entre los párrafos.

    Dibujar el gráfico DE VERDAD en el PDF sería otra obra (un motor de charts server-side)
    y sobre todo otra decisión: acá se conserva el dato, no se imita el píxel.
    """
    norm = _chart_normalizado(spec)
    if norm is None:
        return None
    labels, series = norm
    nombres = [n for n, _ in series]
    columnas = [d for _, d in series]
    filas = [[""] + nombres]
    for i, lab in enumerate(labels):
        fila = [str(lab)]
        for col in columnas:
            v = col[i] if i < len(col) else None
            # `null` en una serie es un hueco REAL (una media móvil no existe en el mes 1):
            # se muestra vacío, no cero — rellenarlo sería inventar el dato.
            fila.append("" if v is None else str(v))
        filas.append(fila)
    return filas


def _partir_cercados(content: str):
    """El markdown, partido en tramos: `("texto", str)` y `("cercado", lenguaje, cuerpo)`.

    Sin esto, un bloque de código se dibuja como prosa línea por línea — que es lo que
    pasaba con ```chart y también con ```python.
    """
    tramos = []
    buf = []
    dentro = False
    lang = ""
    cuerpo = []
    for raw in (content or "").splitlines():
        ls = raw.strip()
        if ls.startswith("```"):
            if dentro:
                tramos.append(("cercado", lang, "\n".join(cuerpo)))
                dentro, lang, cuerpo = False, "", []
            else:
                if buf:
                    tramos.append(("texto", "\n".join(buf)))
                    buf = []
                dentro, lang = True, ls[3:].strip().lower()
            continue
        (cuerpo if dentro else buf).append(raw)
    if dentro:                                 # cerca sin cerrar: se trata como código igual
        tramos.append(("cercado", lang, "\n".join(cuerpo)))
    if buf:
        tramos.append(("texto", "\n".join(buf)))
    return tramos


def _gen_pdf(content: str, title: str) -> bytes:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=LETTER, leftMargin=0.9 * inch,
                            rightMargin=0.9 * inch, topMargin=0.9 * inch, bottomMargin=0.9 * inch,
                            title=title or "obra")
    ss = getSampleStyleSheet()
    flow = []
    if title:
        flow += [Paragraph(_md_inline(title), ss["Title"]), Spacer(1, 10)]
    tbuf = []  # acumulador de filas de tabla markdown contiguas

    def flush_table():
        if not tbuf:
            return
        # UNA TABLA ANCHA NO SE APIÑA: con muchas columnas la letra baja para que los
        # encabezados no se partan. VISTO en el PDF de 12 columnas: «Volatilid ad»,
        # «Media/V ol», «AAP L». Se achica el texto, no se recortan datos.
        ncols = max(len(r) for r in tbuf)
        est = ss["BodyText"]
        if ncols >= 7:
            from reportlab.lib.styles import ParagraphStyle
            est = ParagraphStyle("chico", parent=ss["BodyText"],
                                 fontSize=6.2 if ncols >= 11 else 7.2,
                                 leading=7.6 if ncols >= 11 else 8.8)
        data = [[Paragraph(_md_inline(c), est) for c in r] for r in tbuf]
        t = Table(data, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        flow.append(t)
        flow.append(Spacer(1, 8))
        tbuf.clear()

    def pintar_cercado(lang: str, cuerpo: str) -> None:
        """Un bloque cercado. `chart` se vuelve TABLA (mismo dato, otro envase); el resto,
        monoespaciado. Lo que NO puede volver a pasar es que caiga en el `else` de abajo y
        se dibuje como prosa, que es como el JSON del chart terminaba en el informe."""
        if lang == "chart":
            try:
                filas = _chart_a_filas(json.loads(cuerpo))
            except (ValueError, TypeError):
                filas = None
            if filas:
                spec_titulo = ""
                try:
                    spec_titulo = str(json.loads(cuerpo).get("title") or "")
                except (ValueError, TypeError):
                    pass
                if spec_titulo:
                    flow.append(Paragraph(_md_inline(spec_titulo), ss["Heading3"]))
                tbuf.extend(filas)
                flush_table()
                return
        # Sin forma reconocible: se muestra como CÓDIGO, no como prosa. El dato no se
        # pierde y el lector ve que es un bloque, no un párrafo del informe.
        mono = ss["Code"] if "Code" in ss.byName else ss["BodyText"]
        for linea in (cuerpo or "").splitlines() or [""]:
            seguro = linea.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            flow.append(Paragraph(seguro or "&nbsp;", mono))
        flow.append(Spacer(1, 8))

    for tramo in _partir_cercados(content):
        if tramo[0] == "cercado":
            flush_table()
            pintar_cercado(tramo[1], tramo[2])
            continue
        for raw in tramo[1].splitlines():
            l = raw.rstrip()
            ls = l.strip()
            if ls.startswith("|") and ls.count("|") >= 2:
                cells = [c.strip() for c in ls.strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != ""):
                    tbuf.append(cells)
                continue
            flush_table()
            if not ls:
                flow.append(Spacer(1, 6))
            elif _RE_REGLA.match(ls):
                from reportlab.platypus import HRFlowable
                flow.append(Spacer(1, 6))
                flow.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
                flow.append(Spacer(1, 6))
            elif ls.startswith("### "):
                flow.append(Paragraph(_md_inline(ls[4:]), ss["Heading3"]))
            elif ls.startswith("## "):
                flow.append(Paragraph(_md_inline(ls[3:]), ss["Heading2"]))
            elif ls.startswith("# "):
                flow.append(Paragraph(_md_inline(ls[2:]), ss["Heading1"]))
            elif re.match(r"^([-*]|\d+\.)\s+", ls):
                txt = re.sub(r"^([-*]|\d+\.)\s+", "", ls)
                flow.append(Paragraph("• " + _md_inline(txt), ss["BodyText"], bulletText=""))
            else:
                flow.append(Paragraph(_md_inline(ls), ss["BodyText"]))
        flush_table()
    if not flow:
        flow = [Paragraph("(obra vacía)", ss["BodyText"])]
    doc.build(flow)
    return bio.getvalue()


def _gen_docx(content: str, title: str) -> bytes:
    from docx import Document
    doc = Document()
    if title:
        doc.add_heading(title.strip(), level=0)
    tbuf = []

    def flush_table():
        if not tbuf:
            return
        ncols = max(len(r) for r in tbuf)
        tbl = doc.add_table(rows=0, cols=ncols)
        tbl.style = "Light Grid Accent 1"
        for ri, r in enumerate(tbuf):
            cells = tbl.add_row().cells
            for ci in range(ncols):
                cells[ci].text = r[ci] if ci < len(r) else ""
                if ri == 0:
                    for p in cells[ci].paragraphs:
                        for run in p.runs:
                            run.bold = True
        tbuf.clear()

    def plain(s):  # quita marcadores markdown inline para docx
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        return s

    def pintar_cercado(lang: str, cuerpo: str) -> None:
        """Mismo criterio que el PDF: `chart` se vuelve TABLA (mismo dato, otro envase) y
        el resto va monoespaciado. Sin esto el JSON del gráfico se escribía como párrafos
        del informe."""
        if lang == "chart":
            try:
                spec = json.loads(cuerpo)
                filas = _chart_a_filas(spec)
            except (ValueError, TypeError):
                spec, filas = None, None
            if filas:
                t = str((spec or {}).get("title") or "")
                if t:
                    doc.add_heading(plain(t), level=3)
                tbuf.extend(filas)
                flush_table()
                return
        for linea in (cuerpo or "").splitlines() or [""]:
            par = doc.add_paragraph(linea)
            for run in par.runs:
                run.font.name = "Courier New"

    for tramo in _partir_cercados(content):
        if tramo[0] == "cercado":
            flush_table()
            pintar_cercado(tramo[1], tramo[2])
            continue
        for raw in tramo[1].splitlines():
            ls = raw.strip()
            if ls.startswith("|") and ls.count("|") >= 2:
                cells = [c.strip() for c in ls.strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != ""):
                    tbuf.append(cells)
                continue
            flush_table()
            if not ls or _RE_REGLA.match(ls):
                continue          # la regla horizontal no es texto; en .docx no se dibuja
            if ls.startswith("### "):
                doc.add_heading(plain(ls[4:]), level=3)
            elif ls.startswith("## "):
                doc.add_heading(plain(ls[3:]), level=2)
            elif ls.startswith("# "):
                doc.add_heading(plain(ls[2:]), level=1)
            elif re.match(r"^([-*]|\d+\.)\s+", ls):
                doc.add_paragraph(plain(re.sub(r"^([-*]|\d+\.)\s+", "", ls)), style="List Bullet")
            else:
                doc.add_paragraph(plain(ls))
        flush_table()
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()


#: LA PIEL DE ALEPH EN UN DECK. Los valores salen de `product/app/design/aleph-tokens.css`,
#: que es la ÚNICA hoja que define la paleta; se transcriben acá porque el backend no puede
#: leer CSS y NO se inventa ninguno — si el token cambia, esta tabla se corrige contra él.
#:
#: SE USA LA PALETA CLARA, Y ES UNA DECISIÓN. La app es oscura, pero un deck se PROYECTA y
#: se IMPRIME: un fondo #0B0B0C en un aula con luz no se lee, y en papel es un cartucho
#: entero. La identidad viaja en el acento y en la tipografía, no en el fondo negro — que
#: es la misma regla que la casa ya aplica al cruzar su tema a un stack (el criterio es la
#: LUMINANCIA, no el hex).
_PPTX_PIEL = {
    "fondo":  (0xF4, 0xF4, 0xF5),   # --page-bg   (claro)
    "tinta":  (0x0A, 0x0A, 0x0A),   # --ink
    "suave":  (0x65, 0x65, 0x6A),   # --muted     4.5:1 declarado en el token
    "acento": (0x5A, 0x4F, 0xD6),   # --accent    (claro)
}
#: La familia: Aleph usa Outfit, que viaja como woff2 y NO se puede embeber en un .pptx sin
#: convertirla y arrastrar su licencia adentro del archivo. Se declara una sans del sistema
#: y se deja que PowerPoint sustituya — un deck que abre con la fuente cambiada es mejor que
#: uno que no abre. Nada de serif por defecto, que era lo que se veía.
_PPTX_FUENTE = "Helvetica Neue"


def _pptx_pintar(slide, prs, es_portada: bool) -> None:
    """El fondo, la barra de acento y el pie. Sin imágenes ni adornos: sólo la piel."""
    from pptx.util import Emu, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    fondo = slide.background.fill
    fondo.solid()
    fondo.fore_color.rgb = RGBColor(*_PPTX_PIEL["fondo"])
    # UNA barra de acento, arriba. En la portada es ancha (es la firma); en las demás, fina
    # —marca la lámina sin robarle sitio al contenido, que es lo que el deck viene a decir.
    alto = Emu(int(prs.slide_height * (0.012 if es_portada else 0.005)))
    ancho = Emu(int(prs.slide_width * (0.34 if es_portada else 1.0)))
    barra = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, ancho, alto)
    barra.fill.solid()
    barra.fill.fore_color.rgb = RGBColor(*_PPTX_PIEL["acento"])
    barra.line.fill.background()
    barra.shadow.inherit = False


def _pptx_tipografia(slide, es_portada: bool) -> None:
    """Tipografía y color de la lámina. Tamaños por JERARQUÍA, no por gusto: el título
    manda, el cuerpo se lee de lejos, y una lámina con muchas viñetas baja de cuerpo en vez
    de desbordar — desbordar es perder contenido, achicar es sólo leer más cerca."""
    from pptx.util import Pt
    from pptx.dml.color import RGBColor
    tit = getattr(slide.shapes, "title", None)
    if tit is not None and tit.has_text_frame:
        for par in tit.text_frame.paragraphs:
            for run in par.runs:
                run.font.size = Pt(40 if es_portada else 30)
                run.font.bold = True
                run.font.name = _PPTX_FUENTE
                run.font.color.rgb = RGBColor(*_PPTX_PIEL["tinta"])
    for ph in slide.placeholders:
        if tit is not None and ph == tit:
            continue
        if not ph.has_text_frame:
            continue
        pars = [p for p in ph.text_frame.paragraphs if p.text.strip()]
        cuerpo_pt = 18 if len(pars) <= 5 else (15 if len(pars) <= 9 else 12)
        for par in ph.text_frame.paragraphs:
            for run in par.runs:
                run.font.size = Pt(cuerpo_pt)
                run.font.name = _PPTX_FUENTE
                run.font.color.rgb = RGBColor(*_PPTX_PIEL["tinta"])


def _gen_pptx(content: str, title: str) -> bytes:
    """`presentacion` → .pptx REAL (python-pptx, slides de verdad).
    [Convergencia · superficie 7]

    POR QUÉ EXISTE ESTA FUNCIÓN Y NO UN `formats: ["md"]`: `formats` GOBIERNA el
    export (`vocabulary.py:29`), así que declarar `pptx` sin generador NO da un error
    — da una MENTIRA MUDA. Medido antes de escribir esto, con el tipo ya declarado y
    esta función todavía ausente:

        pedido fmt='pptx'  ->  fmt SERVIDO='md'  mime='text/markdown'  filename='pitch.md'

    Sin 500, sin aviso: el botón dice «bajar .pptx» y entrega un markdown, porque el
    final de `_generate` es `# desconocido → markdown crudo`. Es exactamente la ley
    técnica 7 — un campo que gobierna sin consumidor cableado no entra como gobernante.

    EL CORTE DE SLIDES es por ENCABEZADO, y es la única decisión de este archivo: cada
    `#`/`##`/`###` abre un slide y lo que sigue son sus viñetas. Sin ningún encabezado
    sale UN slide con el título de la obra — jamás cero slides, que abriría un .pptx
    vacío (la misma regla que el puente: una ficha honesta antes que un marco en blanco).

    LO QUE NO HACE: no inventa diseño, ni imágenes, ni orador. Una tabla markdown viaja
    como sus filas en texto, porque convertirla en tabla de pptx exigiría decidir anchos
    y estilos que nadie declaró. El contenido es el que la obra tiene."""
    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation()
    layout = prs.slide_layouts[1]          # título + cuerpo, el de la plantilla base
    layout_titulo = prs.slide_layouts[5]   # sólo título: para una portada sin viñetas

    def plain(s: str) -> str:              # mismos marcadores que _gen_docx
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        return s

    slides: list[tuple[str, list[str]]] = []
    actual: Optional[tuple[str, list[str]]] = None

    # LOS BLOQUES CERCADOS, PRIMERO. Sin esto cada línea del JSON de un ```chart entraba
    # como VIÑETA — el mismo defecto que tenían el pdf y el docx, y en un slide se ve peor
    # todavía: media lámina de llaves y corchetes. Un chart se vuelve sus FILAS (mismo dato,
    # otro envase: la regla de `platform/artifacts/bridge.py`); el resto va como texto, que
    # es lo que ya hacía con el código.
    lineas: list[str] = []
    for tramo in _partir_cercados(content):
        if tramo[0] == "cercado":
            lang, cuerpo_c = tramo[1], tramo[2]
            filas = None
            spec = None
            if lang == "chart":
                try:
                    spec = json.loads(cuerpo_c)
                    filas = _chart_a_filas(spec)
                except (ValueError, TypeError):
                    filas = None
            if filas:
                t = str((spec or {}).get("title") or "")
                if t:
                    lineas.append("### " + t)     # el gráfico abre su propia lámina
                lineas.extend(" · ".join(c for c in fila if c) for fila in filas)
            else:
                lineas.extend((cuerpo_c or "").splitlines())
            continue
        lineas.extend(tramo[1].splitlines())

    for raw in lineas:
        ls = raw.strip()
        if not ls or _RE_REGLA.match(ls):
            continue          # separador de secciones: no es una viñeta de la lámina
        m = re.match(r"^(#{1,3})\s+(.*)$", ls)
        if m:
            actual = (plain(m.group(2)).strip() or (title or "obra"), [])
            slides.append(actual)
            continue
        if ls.startswith("|") and ls.count("|") >= 2:
            celdas = [c.strip() for c in ls.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in celdas if c != ""):
                continue               # la línea de guiones de la tabla no es contenido
            ls = " · ".join(c for c in celdas if c)
        ls = re.sub(r"^([-*]|\d+\.)\s+", "", ls)
        if actual is None:
            actual = ((title or "obra").strip(), [])
            slides.append(actual)
        actual[1].append(plain(ls))

    if not slides:
        slides = [((title or "obra").strip(), [])]

    for n_slide, (encabezado, vinetas) in enumerate(slides):
        # LA PORTADA VA SIN CUERPO SI NO LO NECESITA: la primera lámina anuncia, no
        # enumera. Con el layout de sólo-título el placeholder vacío no deja su hueco.
        es_portada = (n_slide == 0)
        usar = layout_titulo if (es_portada and not vinetas) else layout
        s = prs.slides.add_slide(usar)
        _pptx_pintar(s, prs, es_portada)
        s.shapes.title.text = encabezado[:120]
        if vinetas:
            # El cuerpo se busca por su placeholder, no por índice fijo: el layout de
            # sólo-título NO tiene `placeholders[1]` y acceder a él tira IndexError.
            marco = next((ph.text_frame for ph in s.placeholders
                          if ph.has_text_frame and ph != s.shapes.title), None)
            if marco is not None:
                marco.clear()
                for j, v in enumerate(vinetas):
                    par = marco.paragraphs[0] if j == 0 else marco.add_paragraph()
                    par.text = v[:500]
        # La piel se aplica DESPUÉS de escribir: los runs no existen hasta que hay texto.
        _pptx_tipografia(s, es_portada)

    bio = io.BytesIO()
    prs.save(bio)
    return bio.getvalue()


def _chart_a_svg(spec: dict) -> Optional[str]:
    """El bloque ```chart, dibujado DE VERDAD: SVG inline, sin librería y sin CDN.

    POR QUÉ SVG A MANO Y NO UNA LIB DE CHARTS. El archivo que baja el usuario tiene que
    abrirse SOLO — en su navegador, sin internet, dentro de un mail, o impreso. Un `<script
    src>` a un CDN rompe las cuatro cosas, y es exactamente lo que la doctrina de Capa 0
    prohíbe («cero conexiones al mundo exterior»). Un `<svg>` inline es el gráfico, no una
    receta para dibujarlo después.

    Soporta línea y barras — que es lo que el modelo emite. Un `type` desconocido cae a
    línea en vez de fallar: la forma del dato es la misma y perderlo sería peor.

    `None` cuando no se puede sin inventar: ahí el llamador cae a la tabla, que ya existe.
    """
    norm = _chart_normalizado(spec)
    if norm is None:
        return None
    labels, series = norm

    limpias = []
    for nombre, datos in series:
        vals = []
        for v in datos:
            try:
                vals.append(None if v is None else float(v))
            except (TypeError, ValueError):
                vals.append(None)            # un valor ilegible es un HUECO, no un cero
        limpias.append((nombre, vals))

    numeros = [v for _, vs in limpias for v in vs if v is not None]
    if not numeros:
        return None
    vmax, vmin = max(numeros), min(numeros)
    if vmax == vmin:
        vmax, vmin = vmax + 1, vmin - 1      # una serie plana no se divide por cero
    # El eje arranca en 0 cuando todo es positivo: una barra que no nace en cero exagera la
    # diferencia, y eso es mentir con la forma.
    if vmin > 0:
        vmin = 0

    W, H = 720, 300
    PL, PR, PT, PB = 56, 16, 28, 46
    iw, ih = W - PL - PR, H - PT - PB
    n = len(labels)
    px = lambda i: PL + (iw * i / max(n - 1, 1))
    py = lambda v: PT + ih - (ih * (v - vmin) / (vmax - vmin))
    COLORES = ["#8b5cf6", "#22c55e", "#e2a336", "#38bdf8", "#e5484d"]
    esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
           f'role="img" aria-label="{esc(spec.get("title") or "gráfico")}" '
           f'style="max-width:100%;height:auto">']
    # rejilla + eje Y con sus valores: un gráfico sin escala no se puede leer
    for k in range(5):
        v = vmin + (vmax - vmin) * k / 4
        y = py(v)
        out.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" '
                   f'stroke="#8884" stroke-width="0.5"/>')
        out.append(f'<text x="{PL-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" '
                   f'fill="#888">{v:,.0f}</text>')
    # eje X: se saltean etiquetas si no entran, en vez de encimarlas
    paso = max(1, n // 12)
    for i, lab in enumerate(labels):
        if i % paso:
            continue
        out.append(f'<text x="{px(i):.1f}" y="{H-PB+18}" text-anchor="middle" '
                   f'font-size="11" fill="#888">{esc(lab)}</text>')

    barras = str(spec.get("type") or "").lower() in ("bar", "barras", "column")
    for si, (nombre, vals) in enumerate(limpias):
        color = COLORES[si % len(COLORES)]
        if barras:
            ancho = max(2.0, (iw / max(n, 1)) / max(len(limpias), 1) * 0.7)
            for i, v in enumerate(vals[:n]):
                if v is None:
                    continue
                x = px(i) - (ancho * len(limpias) / 2) + ancho * si
                y = py(v)
                out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{ancho:.1f}" '
                           f'height="{(PT+ih-y):.1f}" fill="{color}" opacity="0.85"/>')
        else:
            # Los huecos CORTAN la línea (una media móvil no existe en el mes 1): unirlos
            # dibujaría un dato que nadie calculó.
            tramo = []
            for i, v in enumerate(vals[:n]):
                if v is None:
                    if len(tramo) > 1:
                        out.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" '
                                   f'points="{" ".join(tramo)}"/>')
                    tramo = []
                    continue
                tramo.append(f"{px(i):.1f},{py(v):.1f}")
            if len(tramo) > 1:
                out.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" '
                           f'points="{" ".join(tramo)}"/>')
        # leyenda
        lx = PL + si * 150
        out.append(f'<rect x="{lx}" y="6" width="10" height="10" fill="{color}"/>'
                   f'<text x="{lx+15}" y="15" font-size="11" fill="#888">{esc(nombre)}</text>')
    out.append("</svg>")
    return "".join(out)


_HTML_CSS = """
:root{color-scheme:light dark}
body{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
     max-width:820px;margin:40px auto;padding:0 20px;color:#1a1a1a;background:#fff}
@media (prefers-color-scheme:dark){body{color:#e8e3da;background:#131318}
  th{background:#ffffff10}td,th{border-color:#ffffff22}code,pre{background:#ffffff10}}
h1,h2,h3{line-height:1.25;margin:1.6em 0 .5em}h1{margin-top:0}
table{border-collapse:collapse;margin:1.2em 0;width:100%;font-size:14px}
td,th{border:1px solid #0002;padding:6px 10px;text-align:left}
th{background:#0000000a;font-weight:600}
pre{background:#00000008;padding:12px;border-radius:8px;overflow:auto;font-size:13px}
code{background:#00000010;padding:1px 5px;border-radius:4px;font-size:.9em}
figure{margin:1.4em 0}figcaption{font-size:13px;color:#888;margin-bottom:6px}
"""


def _md_a_html(content: str) -> str:
    """Markdown → HTML. Encabezados, tablas, listas, cercados e inline.

    EL DEFECTO QUE TAPA, medido leyendo `_gen_html`: NO parseaba markdown. Envolvía el
    texto crudo en un `<html>` y listo, así que un informe bajaba como markdown plano en
    una página en blanco — sin tabla, sin títulos y con el JSON del chart a la vista. Era
    peor que el PDF, que al menos armaba las tablas.
    """
    partes = []
    for tramo in _partir_cercados(content):
        if tramo[0] == "cercado":
            lang, cuerpo = tramo[1], tramo[2]
            if lang == "chart":
                try:
                    spec = json.loads(cuerpo)
                except (ValueError, TypeError):
                    spec = None
                svg = _chart_a_svg(spec) if spec else None
                if svg:
                    t = str((spec or {}).get("title") or "")
                    cap = f"<figcaption>{_md_inline_html(t)}</figcaption>" if t else ""
                    partes.append(f"<figure>{cap}{svg}</figure>")
                    continue
                filas = _chart_a_filas(spec) if spec else None
                if filas:                      # sin SVG posible, la tabla conserva el dato
                    partes.append(_tabla_html(filas))
                    continue
            seguro = (cuerpo or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            partes.append(f"<pre><code>{seguro}</code></pre>")
            continue

        tbuf = []
        for raw in tramo[1].splitlines():
            ls = raw.strip()
            if ls.startswith("|") and ls.count("|") >= 2:
                cells = [c.strip() for c in ls.strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != ""):
                    tbuf.append(cells)
                continue
            if tbuf:
                partes.append(_tabla_html(tbuf))
                tbuf = []
            if not ls:
                continue
            if _RE_REGLA.match(ls):
                partes.append("<hr>")
                continue
            if ls.startswith("### "):
                partes.append(f"<h3>{_md_inline_html(ls[4:])}</h3>")
            elif ls.startswith("## "):
                partes.append(f"<h2>{_md_inline_html(ls[3:])}</h2>")
            elif ls.startswith("# "):
                partes.append(f"<h1>{_md_inline_html(ls[2:])}</h1>")
            elif re.match(r"^([-*]|\d+\.)\s+", ls):
                txt = re.sub(r"^([-*]|\d+\.)\s+", "", ls)
                partes.append(f"<li>{_md_inline_html(txt)}</li>")
            else:
                partes.append(f"<p>{_md_inline_html(ls)}</p>")
        if tbuf:
            partes.append(_tabla_html(tbuf))
    # los <li> sueltos se agrupan en una <ul> para que el navegador los dibuje como lista
    html = "\n".join(partes)
    return re.sub(r"(?:<li>.*?</li>\n?)+", lambda m: "<ul>" + m.group(0) + "</ul>", html, flags=re.DOTALL)


def _tabla_html(filas: list) -> str:
    if not filas:
        return ""
    cab = "".join(f"<th>{_md_inline_html(c)}</th>" for c in filas[0])
    cuerpo = "".join(
        "<tr>" + "".join(f"<td>{_md_inline_html(c)}</td>" for c in fila) + "</tr>"
        for fila in filas[1:])
    return f"<table><thead><tr>{cab}</tr></thead><tbody>{cuerpo}</tbody></table>"


def _md_inline_html(s: str) -> str:
    """**bold**/*italic*/`code` → HTML. Escapa primero, como su hermano de reportlab."""
    s = str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def _gen_html(content: str, title: str) -> bytes:
    c = (content or "").strip()
    low = c.lower()
    # UNA OBRA QUE YA ES HTML SE SIRVE TAL CUAL. Es el caso de `web` y `3d`, cuyo contenido
    # ES la página: pasarla por el conversor de markdown la destruiría.
    if "<html" in low or "<!doctype" in low:
        return c.encode("utf-8")
    cuerpo = _md_a_html(c)
    t = (title or "obra").replace("&", "&amp;").replace("<", "&lt;")
    # SIN CDN, SIN SCRIPT, SIN FUENTE REMOTA: el archivo se abre solo, sin internet, en un
    # mail o impreso. El gráfico va como `<svg>` INLINE — es el dibujo, no una receta para
    # dibujarlo después. Es la doctrina de Capa 0 aplicada al archivo que baja.
    return ("<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{t}</title><style>{_HTML_CSS}</style></head><body>\n"
            f"{cuerpo}\n</body></html>").encode("utf-8")


def _gen_png(content: str, title: str):
    """imagen: el contenido es un data-URL (data:image/png;base64,...) o una URL/markdown.
    Devuelve (bytes, ext_real). Si no se puede decodificar, cae a un .txt con la URL."""
    m = re.search(r"data:image/([A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)", content or "")
    if m:
        ext = m.group(1).lower().replace("jpeg", "jpg").replace("svg+xml", "svg")
        try:
            return base64.b64decode(re.sub(r"\s+", "", m.group(2))), ext
        except Exception:
            pass
    # SVG inline
    if "<svg" in (content or "").lower():
        return (content or "").encode("utf-8"), "svg"
    # URL suelta → no es el archivo; devolvemos un .txt honesto con el puntero
    return ("La imagen vive en una URL externa:\n" + (content or "")).encode("utf-8"), "txt"


def _gen_dashboard_csv(content: str, title: str) -> bytes:
    """Extrae los datos de los bloques ```chart {json} del dashboard → CSV (serie, label, valor)."""
    out_rows = [["chart", "label", "value"]]
    for m in re.finditer(r"```chart\s*(\{.*?\})\s*```", content or "", re.DOTALL):
        try:
            spec = json.loads(m.group(1))
        except Exception:
            continue
        # MISMO lector que la tabla y el svg. Antes leía el spec por su cuenta y con la
        # forma de Chart.js `spec["data"]` era un dict: `series[0]` tiraba `KeyError: 0`
        # y se llevaba puesto el CSV entero del dashboard, no sólo ese chart.
        norm = _chart_normalizado(spec)
        if norm is None:
            continue
        labels, series = norm
        for nombre, datos in series:
            for i, v in enumerate(datos):
                out_rows.append([nombre, labels[i] if i < len(labels) else i, v])
    if len(out_rows) == 1:  # sin charts → caemos a la tabla si hay
        return _gen_csv(content, title)
    sio = io.StringIO()
    _csv.writer(sio).writerows(out_rows)
    return sio.getvalue().encode("utf-8-sig")


def _generate(type_: str, fmt: str, content: str, title: str):
    """Devuelve (bytes, ext_real)."""
    if fmt == "xlsx":
        return _gen_xlsx(content, title), "xlsx"
    if fmt == "csv":
        if (type_ or "").lower() == "dashboard":
            return _gen_dashboard_csv(content, title), "csv"
        return _gen_csv(content, title), "csv"
    if fmt == "md":
        return _gen_md(content, title), "md"
    if fmt == "pdf":
        return _gen_pdf(content, title), "pdf"
    if fmt == "docx":
        return _gen_docx(content, title), "docx"
    if fmt == "pptx":
        return _gen_pptx(content, title), "pptx"
    if fmt == "html":
        return _gen_html(content, title), "html"
    if fmt == "png":
        return _gen_png(content, title)  # ya devuelve (bytes, ext)
    # desconocido → markdown crudo
    return _gen_md(content, title), "md"


def export(artifact: dict, fmt: Optional[str], sid: str) -> dict:
    """Genera (o reusa cache) el archivo real de la obra. Devuelve {path, mime, filename}.

    Cache: dl_root()/{sid}/{aid}.{hash}.{ext} — keyed por (contenido, fmt) → descargar dos
    veces NO regenera; editar la obra (contenido nuevo) regenera una vez.
    """
    type_ = (artifact.get("type") or "").lower()
    content = artifact.get("content") or ""
    title = artifact.get("title") or "obra"
    aid = artifact.get("id") or "art"
    allowed = formats_for(type_)
    f = (fmt or allowed[0]).lower()
    if f not in allowed:
        f = allowed[0]
    # sha256 = the same hash the store stamps as content_sha256 (contract §4/§7);
    # stale sha1-keyed cache files simply never match again and are regenerated.
    h = hashlib.sha256((content + "|" + f).encode("utf-8")).hexdigest()[:10]
    cache_dir = dl_root() / _safe(sid)
    cache_dir.mkdir(parents=True, exist_ok=True)
    # ext puede no coincidir con fmt (imagen png→jpg/svg); resolvemos generando si no hay cache.
    existing = list(cache_dir.glob(f"{_safe(aid)}.{h}.*"))
    if existing:
        path = existing[0]
        ext = path.suffix.lstrip(".")
    else:
        data, ext = _generate(type_, f, content, title)
        path = cache_dir / f"{_safe(aid)}.{h}.{ext}"
        path.write_bytes(data)
    return {
        "path": str(path),
        "mime": _MIME.get(ext, "application/octet-stream"),
        "filename": _safe(title) + "." + ext,
        "fmt": ext,
    }
