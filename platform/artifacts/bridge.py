"""bridge.py — EL PUENTE: lo que un stack heredado produce, hecho ciudadano de la casa.
[Gate 4 · Fase 3 · obra 3.5 · ley 0 costura (2) · ley de producto 7]

QUÉ ES
------
Cada stack agéntico emite artefactos con SU vocabulario: uno habla de `snapshot_card`,
otro de `equity_curve`, otro de lo que su oficio nombre así. Aleph habla de 16 tipos
canónicos (`vocabulary.py`). Este archivo es la traducción, y es lo que permite que
**los stacks se hablen entre ellos**: cada uno es una isla; el tipo canónico es el
puerto.

ESTADO HOY: **el registro tiene su primer inquilino — Ciencia, con sus 10 clases.** La
Fase 3 lo estrenó con un stack heredado y midió sus 9 casos uno por uno; la cosecha sacó
ese stack y quedó el MECANISMO —causas con copy, adaptadores de forma, el rechazo con
causa visible— esperando al primero de verdad. Las 10 filas de Ciencia se escribieron
midiendo: se levantó el stack sobre un proyecto con artefactos REALES y su clasificador
corrió sobre ellos. `cross()` sobre un workspace o un kind que nadie registró sigue
levantando `workspace_kind_unknown` con su copy, que es lo que debe pasar.

LA REGLA QUE GOBIERNA CADA ENTRADA — y es la razón de que esta tabla exista en vez de
un `if` en cada consumidor:

    SE ADAPTA LA FORMA. JAMÁS EL DATO.

  · **Forma (permitida):** renombrar un campo (`results` → `rows`), envolver un objeto
    en el markdown que el renderer espera, derivar `labels`/`series` de una lista de
    puntos que YA trae fecha y valor, formatear una fecha. Nada de eso agrega ni quita
    información: es el mismo dato en otro envase.
  · **Dato (prohibida):** rellenar lo que falta. Un `pe` que el proveedor no devolvió
    NO se convierte en 0; una serie con huecos NO se interpola; un benchmark que el
    backtest no calculó NO se inventa. `null` ≠ 0 es la regla del repo (`latency_ms`),
    y acá vale igual: lo faltante viaja faltante y la forma lo dice.
  · Cuando lo que falta es ESTRUCTURAL —el dato que define el tipo no está— el puente
    **rechaza con causa visible** (`BridgeError`) en vez de entregar una forma vacía
    que el renderer pintaría como si tal cosa. Un panel en blanco es una mentira más
    cara que un error.

Esa contabilidad —qué fue forma, qué habría sido dato— es la materia prima del
traductor universal que se extrae en Fase 6 (regla del plan: el contrato universal se
EXTRAE después del adaptador 2, jamás se diseña antes). Por eso cada entrada declara su
`shape_changes` y su `never_filled`: cuando llegue el segundo stack, la extracción se
hace comparando dos tablas reales, no dos intuiciones. **La primera tabla real ya se
midió** (9 casos ejecutados contra un stack vivo) y quedó escrita como doctrina en
`~/Desktop/FASE3-COSECHA.md`; su implementación vive en el árbol hasta `552b9679`.

LO QUE NO HACE
--------------
No re-cablea al stack a nuestras fuentes (ley 0: sus datos son suyos), no toca la
autenticidad del contenido, y no decide dónde se muestra — eso es del workspace, que
declara qué tipos ACEPTA (`accepts`). Lo no reclamado cae a la base (ley 4 y 7).
"""
from __future__ import annotations

import io
import json
from typing import Any, Callable, Optional

from . import vocabulary


class BridgeError(ValueError):
    """El puente no puede entregar este artefacto sin inventar dato.

    `code` es del vocabulario cerrado de abajo para que la superficie tenga copy
    (regla sellada: ninguna causa llega a una pantalla sin copy)."""

    def __init__(self, code: str, detail: str, kind: str = "") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.kind = kind


#: Causas del puente. Cerradas: una causa nueva se agrega acá, con su copy, o no existe.
CAUSES = {
    "workspace_kind_unknown": "Este workspace produjo algo que la casa todavía no sabe recibir.",
    "artifact_data_missing": "El resultado llegó vacío: no hay nada que guardar.",
    "artifact_shape_unusable": "El resultado no tiene la forma que su propio tipo promete.",
    "workspace_tool_failed": "La herramienta del workspace no pudo correr, y lo dice ella misma.",
}

#: Palabras con las que las tools del stack CONFIESAN que no pudieron correr, dentro de su
#: propio campo `note`. Medido en la Fase 3 contra un stack vivo (el que la cosecha sacó):
#: una tool de screener devolvió `count:0, results:[]` con `note: "Screener could not run:
#: Invalid screener expression…"` — un fallo disfrazado de lista vacía. Sin esto, el puente
#: diría «llegó sin filas» y taparía la causa real.
_FAILURE_HINTS = ("could not run", "failed", "unavailable: ", "error:")


# ── helpers de FORMA (ninguno agrega dato) ────────────────────────────────────────

def _rows_from(data: Any, *keys: str) -> list:
    """La lista de filas, buscándola por los nombres que el stack usa. Si no hay
    ninguna, se devuelve vacía y el llamante decide — acá no se fabrica una fila."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def _fmt(value: Any) -> str:
    """Un valor, en texto, SIN rellenar. `None` sale como raya: no-medido tiene que
    verse distinto de cero (regla `latency_ms` del repo)."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:,}".replace(",", " ") if isinstance(value, int) else f"{value:.4g}"
    if isinstance(value, (dict, list)):
        return "`" + json.dumps(value, ensure_ascii=False, default=str)[:180] + "`"
    return str(value)


def _card_to_markdown(data: dict, *, title: str, skip: tuple = ()) -> str:
    """Un objeto plano → una tabla markdown. Envoltorio puro: cada clave del origen
    aparece una vez, con su valor tal cual, y las que faltan no se inventan."""
    filas = [f"| {k.replace('_', ' ')} | {_fmt(v)} |"
             for k, v in data.items() if k not in skip and not isinstance(v, (list, dict))]
    anidados = [(k, v) for k, v in data.items()
                if k not in skip and isinstance(v, (list, dict)) and v]
    partes = [f"## {title}", "", "| campo | valor |", "|---|---|", *filas]
    for k, v in anidados:
        partes += ["", f"### {k.replace('_', ' ')}", "",
                   "```json", json.dumps(v, ensure_ascii=False, indent=2, default=str)[:4000], "```"]
    return "\n".join(partes)


def _series_from_curve(curve: list, *, x_keys: tuple, y_keys: tuple) -> dict:
    """Una curva `[{fecha, valor…}]` → `{labels, series}`, que es la forma que el
    renderer `linechart` de Aleph valida.

    NO se rellenan huecos y NO se interpola: un punto sin valor entra como `None` y el
    renderer lo salta. Una serie que no existe en el origen no se crea vacía — si el
    backtest no calculó benchmark, no hay serie de benchmark."""
    labels: list = []
    cols: dict = {}
    for punto in curve:
        if not isinstance(punto, dict):
            continue
        x = next((punto[k] for k in x_keys if punto.get(k) is not None), None)
        labels.append(str(x) if x is not None else "")
        for k in y_keys:
            if k in punto:
                cols.setdefault(k, []).append(punto.get(k))
    series = [{"name": k, "values": v} for k, v in cols.items() if any(x is not None for x in v)]
    return {"labels": labels, "series": series}


# ── LA TABLA · una fila por caso REAL ejecutado ───────────────────────────────────
#
# `shape_changes` y `never_filled` no son decoración: son la contabilidad que el
# traductor universal de Fase 6 va a leer. Se escriben al medir el caso, no después.
# `degrades_to` declara a qué tipo cae el adaptador cuando el dato REAL no sostiene
# el tipo normal — una tool que corrió y no encontró nada da un informe honesto, no
# una planilla vacía y no un error (ver `_table`).

def _snapshot(a: dict) -> dict:
    d = a.get("data")
    if not isinstance(d, dict) or not d:
        raise BridgeError("artifact_data_missing", "el snapshot llegó sin datos", a.get("kind", ""))
    tit = str(d.get("company_name") or d.get("ticker") or "Ficha")
    return {"type": "informe", "title": tit,
            "content": _card_to_markdown(d, title=tit)}


def _card(a: dict) -> dict:
    d = a.get("data")
    if not isinstance(d, dict) or not d:
        raise BridgeError("artifact_data_missing", "la ficha llegó sin datos", a.get("kind", ""))
    tit = str(d.get("ticker") or d.get("query") or a.get("name") or "Resultado")
    return {"type": "informe", "title": tit, "content": _card_to_markdown(d, title=tit)}


def _table(a: dict) -> dict:
    rows = _rows_from(a.get("data"), "rows", "results", "top_candidates", "setups", "items")
    d = a.get("data") if isinstance(a.get("data"), dict) else {}
    if not rows:
        # ── LA DISTINCIÓN QUE LA MEDICIÓN OBLIGÓ A HACER ──────────────────────────
        # Una lista vacía puede ser tres cosas distintas, y tratarlas igual es cómo se
        # pierde información real. Los tres casos salieron de casos REALES (3.5):
        #
        #  (a) LA TOOL FALLÓ y lo confiesa en su propia nota — medido en un screener:
        #      `count:0, results:[]` + `note:"Screener could not run: Invalid screener
        #      expression…"`. Se rechaza CON LA CAUSA DEL ORIGEN: decir «llegó sin filas»
        #      taparía que el screener ni siquiera corrió.
        #  (b) LA TOOL CORRIÓ Y NO ENCONTRÓ NADA — medido en un scanner: `scanned:0,
        #      matches:0` + `note:"No matching setups were found…"`. **Eso es un
        #      resultado, no un error**: el cero MEDIDO no es el no-medido (la regla
        #      `null ≠ 0` del repo, aplicada al revés). Rechazarlo convertiría un
        #      hallazgo negativo legítimo en un fallo. Pero tampoco es una `planilla`:
        #      ese tipo PROMETE filas y su renderer pintaría una grilla en blanco. La
        #      forma correcta es un informe que DICE que no hubo resultados, con el
        #      contexto que la tool sí calculó.
        #  (c) NO VINO LA LISTA y nada dice por qué → la forma no sirve, se rechaza.
        nota = str(d.get("note") or "").strip()
        bajo = nota.lower()
        if nota and any(h in bajo for h in _FAILURE_HINTS):
            raise BridgeError("workspace_tool_failed", nota[:300], a.get("kind", ""))
        medido = any(isinstance(d.get(k), int) for k in ("count", "matches", "scanned", "returned"))
        if medido:
            tit = str(d.get("query") or a.get("name") or "Sin resultados")
            return {"type": "informe", "title": tit,
                    "content": _card_to_markdown(d, title=tit)}
        raise BridgeError("artifact_shape_unusable",
                          "la tabla llegó sin filas y sin decir cuántas midió",
                          a.get("kind", ""))
    tit = str(d.get("query") or a.get("name") or "Tabla")
    obra: dict = {"type": "planilla", "title": tit, "rows": rows}
    cols = d.get("columns") or d.get("cols")
    if isinstance(cols, list) and cols:
        obra["cols"] = cols
    # Contexto que el stack calculó y que NO se pierde: viaja como nota, no como fila.
    nota = d.get("analysis") or d.get("note")
    if isinstance(nota, str) and nota.strip():
        obra["note"] = nota.strip()[:2000]
    return obra


def _equity(a: dict) -> dict:
    d = a.get("data")
    if not isinstance(d, dict):
        raise BridgeError("artifact_data_missing", "el backtest llegó sin datos", a.get("kind", ""))
    curva = d.get("equity_curve")
    if not isinstance(curva, list) or not curva:
        raise BridgeError("artifact_shape_unusable",
                          "el backtest no trajo curva de capital", a.get("kind", ""))
    obra = _series_from_curve(curva, x_keys=("date", "t", "index"),
                              y_keys=("equity", "strategy", "benchmark", "value"))
    if not obra["series"]:
        raise BridgeError("artifact_shape_unusable",
                          "la curva no trae ninguna serie con valores", a.get("kind", ""))
    obra["type"] = "linechart"
    obra["title"] = str(d.get("ticker") or d.get("strategy") or a.get("name") or "Backtest")
    return obra


#: [Gate 4 · F3-ciencia] LA FICHA DE UN ARCHIVO PRODUCIDO, y por qué hace falta.
#:
#: MEDIDO contra el stack de Ciencia corriendo, con archivos reales de sus 10 clases:
#: lo que su listado de artefactos entrega es una **REFERENCIA**, no el dato.
#:
#:     {"name":"composicion.csv","path":"composicion.csv","kind":"dataset",
#:      "format":"csv","size":93,"modified":1786318323904.6357}
#:
#: Con eso NO se puede armar una `planilla`: no hay filas. Ni una `imagen`: no hay bytes.
#: Y la doctrina de este archivo es explícita — cuando falta el dato ESTRUCTURAL, no se
#: entrega una forma vacía que el renderer pintaría como si tal cosa. Pero rechazar
#: tampoco corresponde: el artefacto EXISTE, el stack lo produjo y sabemos qué es, cómo
#: se llama, cuánto pesa y dónde vive. Un panel en blanco es una mentira; una ficha que
#: dice exactamente lo que se sabe, no.
#:
#: Por eso los adaptadores de abajo son de DOS TIEMPOS: si el stack mandó el contenido,
#: se produce el tipo rico; si mandó sólo la referencia, se DEGRADA a esta ficha —
#: declarado en `degrades_to`, que es lo que la tabla exige para que el código no diverja
#: de lo que ella promete.
#: Los campos de la ficha, en orden de lectura. Los cuatro últimos son PROCEDENCIA y sólo
#: aparecen cuando el stack promovió el archivo a artefacto durable — medido hoy sobre
#: `art_a5269922…` y `art_ee1bd8c3…`: su registro durable trae `sha256`, `version` y
#: `captureQuality`, y la primera versión de esta ficha los tiraba. Llevarlos es FORMA (el
#: mismo dato en otro envase); tirarlos era perder la única prueba de que el artefacto es
#: el que dice ser.
#: `bytes` es el MISMO dato que `size` con otro nombre, y estaba entrando por la puerta que
#: la ficha no miraba: el plugin de Ciencia lo manda así (`n.size ?? n.bytes`,
#: `openscience.js:157`). Sin esta llave, la ficha de una figura de Ciencia decía la ruta y
#: el formato y se callaba el tamaño — el único número que tenía.
_CAMPOS_FICHA = ("path", "format", "size", "bytes", "kind", "sha256", "version", "captureQuality")


def _ficha(a: dict, *, que_es: str) -> dict:
    d = a.get("data") if isinstance(a.get("data"), dict) else {}
    nombre = str(d.get("name") or a.get("name") or "archivo")
    filas = {k: d.get(k) for k in _CAMPOS_FICHA if d.get(k) is not None}
    cuerpo = _card_to_markdown({"qué es": que_es, **filas}, title=nombre)
    return {"type": "informe", "title": nombre, "content": cuerpo}


def _texto_o_ficha(a: dict, *, que_es: str) -> dict:
    """Contenido de texto → informe. Sin contenido → la ficha. Nada se rellena."""
    d = a.get("data") if isinstance(a.get("data"), dict) else {}
    if not d:
        raise BridgeError("artifact_data_missing", "el artefacto llegó sin datos", a.get("kind", ""))
    txt = d.get("content")
    if isinstance(txt, str) and txt.strip():
        return {"type": "informe", "title": str(d.get("name") or a.get("name") or que_es), "content": txt}
    return _ficha(a, que_es=que_es)


def _imagen_o_ficha(a: dict) -> dict:
    """Una figura con sus bytes → imagen. Sólo la referencia → la ficha.

    LOS BYTES HACEN LA IMAGEN, Y LLEGAN EN DOS SOBRES. Esta función conocía uno solo
    —`data_uri`, ya armado— y **el productor vivo manda el otro**: el plugin de Ciencia
    lee el archivo del disco y cruza `content` en base64 con `encoding:"base64"`
    [código `platform/workspaces/plugins/openscience.js:161-168`]. Con un solo sobre
    reconocido, el `if` de abajo fallaba SIEMPRE y **todas** las figuras de Ciencia
    caían a ficha: el usuario pedía una gráfica y recibía la tarjeta de un archivo.

    El desarmador del segundo sobre ya existía —`_imagen_base64_o_ficha`, escrito en
    Convergencia 7 para Oficina— y no se disparaba acá porque Ciencia entra por esta
    puerta y no por aquélla. Es exactamente el precedente de la Sala: el arreglo estaba
    hecho, el camino era otro. Ahora esta puerta prueba el sobre armado y, si no vino,
    delega en el desarmador en vez de rendirse.

    Sin bytes de ninguna forma sigue saliendo la ficha: un marco vacío es peor que
    decir «hay una figura, se llama así»."""
    d = a.get("data") if isinstance(a.get("data"), dict) else {}
    if not d:
        raise BridgeError("artifact_data_missing", "la figura llegó sin datos", a.get("kind", ""))
    uri = d.get("data_uri")
    if isinstance(uri, str) and uri.startswith("data:"):
        return {"type": "imagen", "title": str(d.get("name") or a.get("name") or "Figura"),
                "content": uri}
    return _imagen_base64_o_ficha(a, que_es="figura")


def _planilla_o_ficha(a: dict) -> dict:
    """Filas → planilla. Sólo la referencia → la ficha. Jamás una grilla en blanco.

    EL MISMO CAMINO PERDIDO QUE LA FIGURA. Esta función sabía leer `rows`/`records`/`data`
    —filas ya estructuradas— y el plugin de Ciencia manda el CSV **crudo**, tal como
    salió del disco, en `content` utf8 [código `openscience.js:161-167`]. Sin filas en la
    raíz, todo dataset de Ciencia caía a ficha aunque sus 93 bytes de datos hubieran
    viajado enteros.

    Partirlo ya lo sabía hacer `_csv_o_ficha`, escrito en Convergencia 7 para Oficina; no
    se disparaba acá porque Ciencia entra por esta puerta. Y partir un CSV es FORMA, no
    dato: el separador ya está adentro, no se decide nada (el mismo argumento que ese
    archivo dejó escrito para no abrir un `.xlsx`)."""
    d = a.get("data") if isinstance(a.get("data"), dict) else {}
    if not d:
        raise BridgeError("artifact_data_missing", "el dataset llegó sin datos", a.get("kind", ""))
    filas = _rows_from(d, "rows", "records", "data")
    if not filas:
        return _csv_o_ficha(a, que_es="conjunto de datos")
    obra: dict = {"type": "planilla", "title": str(d.get("name") or a.get("name") or "Datos"), "rows": filas}
    cols = d.get("columns") or d.get("cols")
    if isinstance(cols, list) and cols:
        obra["cols"] = cols
    return obra


# ── [Convergencia · superficie 7] LOS ADAPTADORES DE OFICINA ───────────────────────────
#
# LA REGLA QUE GOBIERNA LAS SEIS FILAS, y sale de MEDIR el payload, no de suponerlo:
# **sólo el contenido `utf8` es texto.** `openwork.js:196-197` decide la codificación con
# `esBinario(rel)`, así que un `.docx`, un `.xlsx`, un `.pptx` y un `.pdf` llegan en
# BASE64. Meter ese base64 en el `content` de un artefacto sería mostrarle al usuario una
# pared de caracteres y llamarla informe: no es adaptar la forma, es entregar otra cosa.
#
# Decodificar un `.docx` a texto tampoco es forma —es parsear OOXML, o sea DERIVAR dato
# que no vino— así que lo binario que Aleph no puede re-derivar cruza como **ficha
# honesta**, exactamente como el `model` y el `archive` de Ciencia.
#
# La ÚNICA excepción es la imagen, y es excepción porque ahí sí es puro envase: los bytes
# ya vinieron, y `base64 + extensión → data:` es el mismo dato en otro sobre. Sin eso,
# `_imagen_o_ficha` —que exige `data_uri`— mandaba a ficha TODAS las imágenes de Oficina.

#: `esBinario()` de openwork.js:138-141 al revés: qué extensión es una imagen que el
#: navegador sabe pintar, y con qué mime. `svg` viaja en utf8 (no está en su lista de
#: binarios) y también se envuelve: el data URI acepta texto igual.
_MIME_IMAGEN = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "svg": "image/svg+xml",
}


def _ext_de(d: dict) -> str:
    """La extensión, del primer campo que la tenga — y `format` como última fuente.

    Oficina nombra sus archivos por su ruta relativa (`rel`), así que su extensión
    siempre estuvo en `name`. Ciencia manda `name` = la ETIQUETA del artefacto, que es
    una frase («el top-10 de aminoácidos») y puede no tener punto; la extensión vive en
    `path` y el stack además declara `format` [código `openscience.js:154-157`]. Un solo
    campo alcanzaba mientras el puente tuviera un solo inquilino; hoy tiene dos y se
    miran los cuatro, en orden de confianza: el nombre, la ruta, y recién al final lo
    que el stack DICE que es.

    `format` va último a propósito, y no es paranoia de más: es una DECLARACIÓN, y la
    sonda de Convergencia 7 ya mostró que un stack puede declarar mal (mandó un `.png`
    diciendo utf8). Para la imagen ni siquiera decide — ahí manda el olfateo de los
    bytes reales (`_mime_sniffado`); acá sólo desempata cuando no hay ruta."""
    for campo in ("name", "rel", "path"):
        nombre = str(d.get(campo) or "")
        if "." in nombre:
            return nombre.rsplit(".", 1)[-1].lower()
    return str(d.get("format") or "").lower().lstrip(".")


def _texto_utf8(d: dict) -> Optional[str]:
    """El contenido SÓLO si es texto de verdad. Un base64 no es texto (ver la nota de
    arriba): devuelve None y el llamador cae a la ficha."""
    if str(d.get("encoding") or "utf8").lower() != "utf8":
        return None
    txt = d.get("content")
    return txt if isinstance(txt, str) and txt.strip() else None


def _tipado_o_ficha(a: dict, *, que_es: str, tipo: str) -> dict:
    """Texto utf8 → el tipo RICO que la fila declara. Lo demás → ficha (`informe`).

    Es el `_texto_o_ficha` de Ciencia con una diferencia que importa: aquél siempre
    devuelve `informe`, y acá el destino rico es el que la fila dice. Un `.html` de
    Oficina tiene que llegar como `web` —que es lo que ES— y no como un informe que
    después no se puede volver a bajar en su formato de origen."""
    d = a.get("data") if isinstance(a.get("data"), dict) else {}
    if not d:
        raise BridgeError("artifact_data_missing", "el archivo llegó sin datos", a.get("kind", ""))
    txt = _texto_utf8(d)
    if txt is None:
        return _ficha(a, que_es=que_es)
    return {"type": tipo, "title": str(d.get("name") or a.get("name") or que_es), "content": txt}


def _redline_a_informe(a: dict) -> dict:
    """El antes y el después REALES de una cláusula → un informe legible.

    FORMA, no dato, y acá la distinción es delicada porque el resultado PARECE contenido
    nuevo: los dos textos ya vinieron enteros desde la herramienta —son los mismos que
    quedaron grabados en la cola de revisión de doc.haus (`lib/redlines.ts`)— y lo único
    que se hace es ponerlos uno debajo del otro con su rótulo. No se diffea palabra por
    palabra, no se resume y no se opina sobre el cambio.

    ES ESTRUCTURAL, Y POR ESO RECHAZA. Un redline sin NINGUNO de los dos lados no es un
    redline: es la noticia de que hubo un cambio sin decir cuál. Eso el renderer lo
    pintaría como una tarjeta con un título y nada adentro, que es exactamente la mentira
    barata que este puente existe para no entregar. Con UNO de los dos lados sí cruza —una
    cláusula que se AGREGA no tiene `antes` y una que se BORRA no tiene `despues`, y las
    dos son cambios legítimos—; lo que falta se dice, no se rellena.
    """
    d = a.get("data") if isinstance(a.get("data"), dict) else {}
    if not d:
        raise BridgeError("artifact_data_missing", "el redline llegó sin datos", a.get("kind", ""))
    antes = d.get("antes") if isinstance(d.get("antes"), str) else None
    despues = d.get("despues") if isinstance(d.get("despues"), str) else None
    if not (antes and antes.strip()) and not (despues and despues.strip()):
        raise BridgeError("artifact_shape_unusable",
                          "el redline llegó sin el texto anterior ni el propuesto: no hay cambio que mostrar",
                          a.get("kind", ""))
    titulo = str(d.get("name") or a.get("name") or "Redline")
    cabecera = {k: d.get(k) for k in ("document", "autor", "redline_id", "alcance") if d.get(k) is not None}
    partes = [_card_to_markdown(cabecera, title=titulo) if cabecera else f"## {titulo}"]
    # El lado ausente se NOMBRA. Callarlo dejaría la tarjeta indistinguible de un redline
    # completo al que se le perdió una mitad por el camino.
    partes += ["", "### texto anterior", "", antes.strip() if antes and antes.strip()
               else "_la herramienta no devolvió el texto anterior_"]
    partes += ["", "### texto propuesto", "", despues.strip() if despues and despues.strip()
               else "_la herramienta no devolvió el texto propuesto_"]
    resumen = d.get("resumen")
    if isinstance(resumen, str) and resumen.strip():
        partes += ["", "### lo que dijo la herramienta", "", resumen.strip()]
    return {"type": "informe", "title": titulo, "content": "\n".join(partes)}



#: Los primeros bytes de cada formato que el navegador sabe pintar. Es la ÚNICA fuente
#: que no depende de que nadie declare nada: el archivo dice lo que es.
_MAGIA_IMAGEN = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _cabeza_b64(b64: str) -> Optional[bytes]:
    """Los primeros bytes de un base64, o `None` si no se dejó desarmar.

    Se piden 64 caracteres (48 bytes) porque WEBP necesita llegar al byte 12. El
    `+ "=="` es relleno: cortar un base64 a mano deja un bloque incompleto, y este
    padding de más lo tolera el decodificador no estricto."""
    import base64 as _b64
    try:
        cabeza = _b64.b64decode(b64.strip()[:64] + "==", validate=False)
    except Exception:
        return None
    return cabeza or None


def _mime_sniffado(b64: str) -> Optional[str]:
    """El mime que dicen LOS BYTES, no el que declara el stack. `None` = no sé.

    Desarmar 48 bytes de base64 es barato y cierra de raíz la trampa que ya está escrita
    en este archivo («creerle a una sola fuente»): con la extensión sola, un stack que
    llame `.png` a un PDF arma un `data:image/png` perfectamente formado que ningún
    navegador puede pintar — el marco vacío otra vez, ahora con la bendición del puente.

    Esto NO es derivar dato: no convierte, no reescala, no decide nada del contenido.
    Sólo LEE lo que el archivo ya dice de sí mismo en su primer renglón de bytes."""
    cabeza = _cabeza_b64(b64)
    if not cabeza:
        return None
    for firma, mime in _MAGIA_IMAGEN:
        if cabeza.startswith(firma):
            return mime
    # WEBP viaja adentro de un contenedor RIFF: `RIFF····WEBP`.
    if cabeza[:4] == b"RIFF" and cabeza[8:12] == b"WEBP":
        return "image/webp"
    return None



def _imagen_base64_o_ficha(a: dict, *, que_es: str = "imagen") -> dict:
    """Los bytes que YA vinieron, envueltos en el sobre que el renderer espera.

    FORMA, no dato: `base64 → data:<mime>;base64,<bytes>`. No se comprime, no se
    reescala, no se convierte de formato — nada de eso podría hacerse sin decidir algo
    que nadie declaró. Unos bytes que no sabemos pintar caen a ficha en vez de que les
    inventemos un mime.

    EL CAMPO ES `content`, Y ESO ES UN ARREGLO, NO UN GUSTO. Hasta acá el puente emitía
    `data_uri`, un sustantivo que **no habla nadie más en el árbol**: el único productor
    vivo de `imagen` lo manda en `content`
    [código `product/belts/medicina/segmentacion_server.py:536`], el renderer lee
    `a.content || a.url` [código `product/app/design/render/sala-render.js:577`] y su
    validador de forma exige `typeof o.content === "string"` [ídem `:745`]. Grep sobre
    el árbol: cero consumidores de `data_uri`. O sea que **toda** imagen que este puente
    produjo alguna vez —Oficina incluida— pintaba «Sin imagen.».

    Y había un segundo filo: con un campo de más, `router.py:6064` marcaba la obra como
    RICA y le metía el JSON entero adentro de `content`; `canvas.js:130` lo desarmaba y
    se quedaba con un objeto sin `content`. El mismo marco vacío, por otro camino."""
    d = a.get("data") if isinstance(a.get("data"), dict) else {}
    if not d:
        raise BridgeError("artifact_data_missing", "la imagen llegó sin datos", a.get("kind", ""))
    ext = _ext_de(d)
    contenido = d.get("content")
    codif = str(d.get("encoding") or "").lower()
    titulo = str(d.get("name") or a.get("name") or que_es.capitalize())
    if isinstance(contenido, str) and contenido.strip():
        if codif == "base64":
            # EL ORDEN IMPORTA, y es el de la confianza:
            #   1. lo que dicen los bytes → se usa, venga de donde venga la extensión;
            #   2. los bytes se desarmaron y NO son una imagen conocida → ficha. Sabemos
            #      que no se puede pintar; taparlo con la extensión sería volver a armar
            #      el marco vacío;
            #   3. los bytes no se dejaron desarmar → recién ahí queda la extensión, que
            #      es lo único que hay.
            mime = _mime_sniffado(contenido)
            if mime is None and _cabeza_b64(contenido) is None:
                mime = _MIME_IMAGEN.get(ext)
            if mime:
                return {"type": "imagen", "title": titulo,
                        "content": f"data:{mime};base64,{contenido.strip()}"}
        # LA RAMA utf8 ES SÓLO PARA `.svg`, y el `ext == "svg"` no es defensa de más: lo
        # destapó la sonda de esta obra mandando un `.png` declarado utf8. Sin esa
        # condición se armaba `data:image/png;utf8,…` con texto adentro — un URI bien
        # formado que ningún navegador puede pintar, o sea el marco vacío que el puente
        # existe para no entregar. Confiar en la codificación que declara el stack, sin
        # cruzarla con la extensión, es creerle a una sola fuente.
        if ext == "svg" and codif != "base64":
            from urllib.parse import quote
            return {"type": "imagen", "title": titulo,
                    "content": f"data:image/svg+xml;utf8,{quote(contenido)}"}
    return _ficha(a, que_es=que_es)


#: Los separadores que un `.csv`/`.tsv` puede traer, en el orden en que se prueban. NO se
#: adivina: se elige el que parte TODAS las líneas en la misma cantidad de columnas, que es
#: lo que ya está en el archivo. Si ninguno lo logra, no hay tabla y sale la ficha.
_SEPARADORES = (",", ";", "\t", "|")


def _csv_o_ficha(a: dict, *, que_es: str = "planilla") -> dict:
    """Un `.csv` utf8 → filas de planilla. Un `.xlsx` (base64) → ficha.

    Partir un CSV en filas es FORMA: el separador ya está en el dato, no se decide nada.
    Abrir un xlsx sería otra cosa —descomprimir y parsear XML— y además exigiría una lib
    en el puente, que es justo lo que este archivo no hace."""
    d = a.get("data") if isinstance(a.get("data"), dict) else {}
    if not d:
        raise BridgeError("artifact_data_missing", "la planilla llegó sin datos", a.get("kind", ""))
    txt = _texto_utf8(d)
    # `.tsv` entra por la misma puerta: es el mismo archivo con otro separador, y el
    # clasificador de Ciencia lo tipa `dataset` igual que al `.csv`.
    if txt is None or _ext_de(d) not in ("csv", "tsv"):
        return _ficha(a, que_es=que_es)
    import csv as _csv
    mejor: list = []
    for sep in _SEPARADORES:
        filas = [f for f in _csv.reader(io.StringIO(txt), delimiter=sep)
                 if any(c.strip() for c in f)]
        # Una sola columna significa que ese separador NO estaba en el archivo: leer un
        # `.tsv` con comas devuelve una columna con toda la línea adentro, que es una
        # tabla mentirosa. Se exige que el separador parta de verdad.
        if len(filas) >= 2 and len(filas[0]) > 1 and len(filas[0]) > len(mejor[0] if mejor else []):
            mejor = filas
    if not mejor:
        # Ningún separador partió en más de una columna. NO se degrada a ficha por eso:
        # una columna sola es una planilla legítima (una lista de valores), y ése era el
        # comportamiento de antes de esta obra. Se cae a la lectura por comas, tal cual.
        mejor = [f for f in _csv.reader(io.StringIO(txt)) if any(c.strip() for c in f)]
    if not mejor:
        return _ficha(a, que_es=que_es)
    return {"type": "planilla", "title": str(d.get("name") or a.get("name") or "Planilla"),
            "cols": mejor[0], "rows": mejor[1:]}


# ── [artefactos de Ciencia] EL CUADERNO, QUE ERA UN MURO DE JSON ───────────────────────
#
# QUÉ PASABA. `notebook` salía por `_texto_o_ficha`, que hace lo correcto para un `.md`:
# el texto va tal cual al `content` del informe. Pero el texto de un `.ipynb` **es su
# JSON** — `{"cells":[{"cell_type":"code","source":[...],"outputs":[...]}],...}`. El
# usuario pedía un cuaderno y en pantalla aparecía la serialización del cuaderno: cada
# línea de código partida en un string de un array, cada figura como un renglón de base64
# de 40.000 caracteres. Técnicamente «el contenido llegó»; en la pantalla, ilegible.
#
# POR QUÉ ESTO ES FORMA Y NO DATO, que es la única pregunta que decide si entra. El
# `.ipynb` **ya viene estructurado**: sabe cuáles celdas son markdown, cuáles son código,
# en qué lenguaje, y qué dejó cada una al ejecutarse. Acá no se ejecuta nada, no se
# re-renderiza nada y no se completa nada — se lee la estructura que el archivo declara y
# se la escribe en el envase que el renderer de `informe` sabe pintar (markdown + fences
# + imágenes). Una celda sin salidas sale sin salidas; un cuaderno nunca corrido sale con
# sus celdas y ninguna salida, que es exactamente lo que ES.
#
# Y no hay tipo canónico `notebook` en el vocabulario, ni se inventa uno acá: la ley 7 del
# repo prohíbe un sustantivo gobernante sin consumidor cableado en el mismo commit. El
# destino sigue siendo `informe`. Lo que cambia es que el informe ahora se lee.

#: Tope de bytes de imagen que un cuaderno puede llevar embebidos. Es el mismo techo que
#: la casa ya declaró para una obra (`executor._MAX_OBRA_BYTES`, 4.000.000 b por default):
#: no se inventa un número nuevo. Pasado el tope, la salida NO se recorta en silencio —
#: se dice cuánto pesaba y por qué no está, que es la regla de `omitido` del plugin.
_TOPE_IMAGENES_CUADERNO = 4_000_000

#: Qué salida de una celda se prefiere cuando el kernel mandó varias representaciones del
#: mismo resultado (un plot de matplotlib llega como png Y como `text/plain` que dice
#: `<Figure size 640x480>`). La imagen gana: es la que el usuario fue a buscar.
_MIMES_CUADERNO = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml")


def _fuente(celda: dict) -> str:
    """`source` viene como lista de líneas CON su `\n`, o como un string. Las dos formas
    están en la especificación del formato y las dos aparecen en cuadernos reales."""
    src = celda.get("source")
    if isinstance(src, list):
        return "".join(str(x) for x in src)
    return str(src or "")


def _salida_a_markdown(sal: dict, presupuesto: list) -> str:
    """Una salida de celda → el markdown que la MUESTRA. `presupuesto` es una caja de un
    elemento con los bytes de imagen que quedan (se muta a propósito: el tope es del
    cuaderno entero, no de cada figura)."""
    tipo = sal.get("output_type")
    if tipo == "stream":
        txt = sal.get("text")
        txt = "".join(txt) if isinstance(txt, list) else str(txt or "")
        return f"```\n{txt.rstrip()}\n```" if txt.strip() else ""
    if tipo == "error":
        traza = sal.get("traceback")
        cuerpo = ("\n".join(str(x) for x in traza) if isinstance(traza, list)
                  else f"{sal.get('ename', '')}: {sal.get('evalue', '')}")
        # La traza trae códigos ANSI de color del kernel; sin sacarlos, la pantalla
        # muestra `[0;31m` en vez del error. Sacarlos es forma: el texto es el mismo.
        import re as _re
        cuerpo = _re.sub(r"\x1b\[[0-9;]*m", "", cuerpo)
        return f"```\n{cuerpo.rstrip()}\n```" if cuerpo.strip() else ""
    if tipo in ("execute_result", "display_data"):
        data = sal.get("data") if isinstance(sal.get("data"), dict) else {}
        for mime in _MIMES_CUADERNO:
            crudo = data.get(mime)
            if not crudo:
                continue
            crudo = "".join(crudo) if isinstance(crudo, list) else str(crudo)
            if mime == "image/svg+xml":
                from urllib.parse import quote
                return f"![]({'data:image/svg+xml;utf8,' + quote(crudo)})"
            limpio = "".join(crudo.split())
            if len(limpio) > presupuesto[0]:
                return (f"*(salida omitida: la imagen pesa {len(limpio)} b y el cuaderno "
                        f"ya llegó al tope de {_TOPE_IMAGENES_CUADERNO} b)*")
            presupuesto[0] -= len(limpio)
            return f"![](data:{mime};base64,{limpio})"
        txt = data.get("text/plain")
        txt = "".join(txt) if isinstance(txt, list) else str(txt or "")
        # `text/html` NO se re-renderiza: meterlo acá sería pasarle al sanitizador HTML
        # que escribió un kernel ajeno, y además duplicaría lo que ya dice `text/plain`.
        return f"```\n{txt.rstrip()}\n```" if txt.strip() else ""
    return ""


def _cuaderno_a_markdown(nb: dict) -> str:
    """El `.ipynb` desarmado en el markdown que la pantalla sabe pintar."""
    meta = nb.get("metadata") if isinstance(nb.get("metadata"), dict) else {}
    lengua = str(
        (meta.get("language_info") or {}).get("name")
        or (meta.get("kernelspec") or {}).get("language")
        or "python"
    ).lower()
    presupuesto = [_TOPE_IMAGENES_CUADERNO]
    partes: list = []
    for celda in nb.get("cells") or []:
        if not isinstance(celda, dict):
            continue
        clase = celda.get("cell_type")
        fuente = _fuente(celda)
        if clase == "markdown":
            if fuente.strip():
                partes.append(fuente.rstrip())
            continue
        if clase == "code":
            if fuente.strip():
                partes.append(f"```{lengua}\n{fuente.rstrip()}\n```")
            for sal in celda.get("outputs") or []:
                if isinstance(sal, dict):
                    pinta = _salida_a_markdown(sal, presupuesto)
                    if pinta:
                        partes.append(pinta)
            continue
        # `raw` y cualquier clase que el formato agregue después: su texto, sin adornarlo.
        if fuente.strip():
            partes.append(fuente.rstrip())
    return "\n\n".join(partes)


def _cuaderno_o_ficha(a: dict) -> dict:
    """Un `.ipynb` legible → informe con sus celdas y sus salidas. Sin texto → la ficha."""
    d = a.get("data") if isinstance(a.get("data"), dict) else {}
    if not d:
        raise BridgeError("artifact_data_missing", "el cuaderno llegó sin datos", a.get("kind", ""))
    txt = _texto_utf8(d)
    if txt is None:
        return _ficha(a, que_es="cuaderno")
    titulo = str(d.get("name") or a.get("name") or "Cuaderno")
    try:
        nb = json.loads(txt)
    except Exception:
        nb = None
    if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list):
        # No es un cuaderno que sepamos leer. Su texto va tal cual —el comportamiento de
        # antes— en vez de rechazarlo: el archivo existe y su contenido viajó.
        return {"type": "informe", "title": titulo, "content": txt}
    cuerpo = _cuaderno_a_markdown(nb)
    if not cuerpo.strip():
        # Un cuaderno SIN celdas con contenido no es un informe vacío: es una ficha que
        # dice que el cuaderno está vacío. Un panel en blanco es una mentira (la regla de
        # este archivo, y acá aplica igual que en la figura).
        return _ficha(a, que_es="cuaderno")
    return {"type": "informe", "title": titulo, "content": cuerpo}


#: Los adaptadores de FORMA que la Fase 3 midió, por la forma que reciben (no por el
#: stack del que salieron). Son las cuatro que aparecieron en 9 casos reales: una ficha
#: plana, una ficha con anidados, una tabla de filas y una curva temporal. Un stack nuevo
#: instancia su fila del registro apuntando a una de éstas, o trae la suya.
ADAPTERS: dict[str, Callable[[dict], dict]] = {
    "snapshot": _snapshot,   # objeto plano → informe (tabla markdown de dos columnas)
    "card": _card,           # objeto con anidados → informe (tabla + bloques JSON)
    "table": _table,         # lista de filas → planilla, con las tres lecturas del vacío
    "curve": _equity,        # curva temporal → linechart, sin interpolar ni inventar series
    # [F3-ciencia] los tres de dos tiempos: tipo rico si vino el dato, ficha si vino la
    # referencia. Ninguno rellena, y los tres declaran su degradación en la tabla.
    "figura": _imagen_o_ficha,
    "datos": _planilla_o_ficha,
}

#: workspace → { kind del stack → (tipo canónico, adaptador, shape_changes, never_filled) }
#:
#: [Gate 4 · F3-ciencia] **LAS 10 FILAS DE CIENCIA, CADA UNA CON SU CASO EJECUTADO.**
#: Ninguna se escribió de intuición: se levantó el stack sobre un proyecto con artefactos
#: REALES —la corrida de TP53 dejó su FASTA, su figura y su informe— y se crearon archivos
#: genuinos de las clases que faltaban (un .ipynb válido, un PDB con átomos, un VCF con la
#: variante R175H, un pickle, un zip). El clasificador del stack corrió sobre los 13 y
#: devolvió las 10 clases; sus payloads quedaron guardados y la vara los usa TAL CUAL.
#:
#: LA CONTABILIDAD, EN UNA LÍNEA: el stack entrega una REFERENCIA
#: (`{name, path, kind, format, size, modified}`), no el dato. Por eso los seis tipos que
#: Aleph no tiene —structure, sequence, genomics, spectrum, model, archive— y los tres que
#: sí —figure, dataset, notebook— comparten el mismo destino honesto: **ficha de informe**,
#: salvo que el stack mande el contenido, en cuyo caso sale el tipo rico. Lo que jamás
#: pasa es que salga una planilla sin filas o una imagen sin bytes.
# ── [Gate 4 · F6-finanzas] LOS DOS ADAPTADORES DE FORMA DE ESTE OFICIO ──────────────────
def _ohlcv_a_planilla(a: dict) -> dict:
    """`{símbolo: [barra, …]}` → una planilla con el símbolo como columna.

    El stack devuelve las barras AGRUPADAS POR SÍMBOLO, que es la forma natural de una
    consulta multi-símbolo y la que `_table` no sabe leer (busca `rows|results|items` en la
    raíz). Se adapta la FORMA —se aplana y se agrega la columna `symbol`—, jamás el dato:
    los OHLCV van tal cual, y un símbolo que volvió sin barras **no se rellena con ceros**,
    desaparece de las filas (la regla `null ≠ 0` del repo).
    """
    data = a.get("data")
    if not isinstance(data, dict) or not data:
        return _ficha(a, que_es="planilla")
    filas = []
    for simbolo, barras in data.items():
        if not isinstance(barras, list):
            continue
        for b in barras:
            if isinstance(b, dict):
                filas.append({"symbol": simbolo, **b})
    if not filas:
        return _ficha(a, que_es="planilla")
    return _table({**a, "data": {"rows": filas}})


def _resultado_anidado_a_planilla(a: dict) -> dict:
    """`{status, result: {items: [...]}}` → planilla, sin perder el envoltorio del stack.

    Varias tools de este stack envuelven su resultado en `{"status": "ok", "result": {…}}`.
    Desenvolver es adaptación de FORMA. Si el envoltorio dice `status != ok`, no se
    convierte nada: se deja que `_table` levante la causa DEL ORIGEN en vez de fabricar
    una planilla vacía.
    """
    data = a.get("data")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        if str(data.get("status", "ok")).lower() not in ("ok", "success", ""):
            return _table(a)
        return _table({**a, "data": data["result"]})
    return _table(a)


TABLE: dict[str, dict[str, dict]] = {
    # [Fase 6 · Educación] El tutor entrega una síntesis/documento de la sesión.
    # Es texto producido por el stack, por eso cruza como informe sin inventar
    # estructura ni convertirlo en una segunda autoridad de memoria.
    #
    # ── [Educación · cortes 3 y 4] LAS FILAS, Y QUIÉN LAS EMITE ──────────────────────
    # Durante dos commits esta fila fue código inalcanzable, y por DOS motivos distintos:
    # Educación no declara `plugin` (el `POST /v1/workspaces/artifacts` tiene tres
    # llamadores y los tres lo son), y la cosecha del borde —`artefactos_del_borde.py`—
    # no le sirve porque exige `json.loads` del `content` y **ninguna** de las 19 tools
    # de `deeptutor/tools/builtin/__init__.py` pone JSON ahí: todas ponen prosa
    # (`core/agentic/tool_dispatch.py:637-645`).
    #
    # EL EMISOR AHORA ES `app/phase1/obras_del_pack.py`, que lee el almacén que el stack
    # YA escribe: `chat_history.db`, con `attachments_json` (los archivos generados) y
    # `events_json` (el evento `result` de cada turno). No es un canal nuevo — el canal
    # estaba lleno y le faltaba el lector.
    #
    # LAS CINCO FILAS, Y DE DÓNDE SALE LA FORMA DE CADA UNA:
    #   `report`     ya estaba. Es el destino de TODA capacidad: las cinco
    #                (`chat` · `deep_research` · `deep_question` · `visualize` ·
    #                `math_animator`) comparten el campo `response`, leído de sus cinco
    #                emisores uno por uno, y el de `chat` además MEDIDO en el store real.
    #   las otras 4  son ARCHIVOS que el turno dejó en disco, clasificados por extensión
    #                con el mismo criterio de `openwork.js:127-136`. Los adaptadores son
    #                los que Oficina ya midió contra un stack vivo: acá cambia de dónde
    #                sale el archivo, no cómo se lo nombra ni cómo se lo envuelve.
    #
    # ⚠️ EL CASO EJECUTADO DE `figura` ES REAL Y ES DE ESTA TANDA: `qa/verify_sandbox_
    # educacion.py` corre matplotlib POR EL SANDBOX DEL STACK y deja un
    # `grafica.png` de 16.423 b que `collect_public_artifacts` publica como
    # `/api/outputs/workspace/chat/_detached_code_execution/…`. Los otros tres cruzan la
    # misma cañería con otra extensión.
    "educacion": {
        "report": {
            "type": "informe", "adapt": lambda a: _texto_o_ficha(a, que_es="informe educativo"),
            "shape_changes": ["el texto de la síntesis pasa tal cual a `content`"],
            "never_filled": ["el contenido pedagógico que el tutor no entregó"],
            "degrades_to": ("informe",),
            "caso": "sintesis.md · markdown · informe de la sesión de estudio",
        },
        # El texto de CUALQUIERA de las cinco capacidades entra por `report`: su `response`
        # pasa tal cual a `content`. No hay una fila por capacidad porque no hay cinco
        # formas — hay una, y multiplicarla sería inventar diferencias que el stack no hace.
        "figura": {
            "type": "imagen", "adapt": _imagen_base64_o_ficha,
            "shape_changes": ["base64 + extensión → `data:<mime>;base64,…`",
                              "un `.svg` viaja utf8 y se percent-encodea",
                              "sin bytes (o por encima del tope): ficha, jamás un marco vacío"],
            "never_filled": ["los píxeles: una figura que no se escribió no se dibuja aquí",
                             "sus dimensiones, que el registro de adjuntos no trae"],
            "degrades_to": ("informe",),
            "caso": "grafica.png · 16.423 b · image/png — x² con su tangente en x=3, "
                    "dibujada por matplotlib adentro del sandbox del stack y publicada en "
                    "`/api/outputs/workspace/chat/_detached_code_execution/…` "
                    "(corrida real de `qa/verify_sandbox_educacion.py`, 2026-08-27)",
        },
        "planilla": {
            "type": "planilla", "adapt": _csv_o_ficha,
            "shape_changes": ["un `.csv` utf8 se parte en `cols` + `rows`",
                              "un `.xlsx` (base64): ficha, jamás una grilla en blanco"],
            "never_filled": ["las celdas de un binario: abrirlo pediría una lib adentro "
                             "del puente, que es lo que este archivo no hace"],
            "degrades_to": ("informe",),
            "caso": "notas.csv del sandbox → cols + filas; notas.xlsx → ficha",
        },
        "documento": {
            "type": "documento", "adapt": lambda a: _tipado_o_ficha(
                a, que_es="documento del tutor", tipo="documento"),
            "shape_changes": ["el texto utf8 (.md/.txt/.json/.py/.html) pasa a `content`",
                              "binario o ilegible como utf8: ficha con nombre, ruta y tamaño"],
            "never_filled": ["el texto de un binario: parsearlo sería derivar dato"],
            "degrades_to": ("informe",),
            "caso": "resumen.md que el turno escribió en su workspace → documento entero",
        },
        "archivo": {
            "type": "informe", "adapt": lambda a: _ficha(a, que_es="archivo generado"),
            "shape_changes": ["ficha del archivo: nombre, formato, tamaño y ruta"],
            "never_filled": ["su contenido: un `.zip`, un `.pdf` o un binario cualquiera "
                             "no se abre ni se describe adivinando"],
            "caso": "entrega.zip del sandbox → ficha con su tamaño real",
        },
    },
    "ciencia": {
        # ── los tres que Aleph SÍ sabe recibir rico ──────────────────────────────────
        "report": {
            "type": "informe", "adapt": lambda a: _texto_o_ficha(a, que_es="informe"),
            "shape_changes": ["el markdown del informe pasa tal cual a `content`",
                              "sin `content`: ficha con nombre, formato, tamaño y ruta"],
            "never_filled": ["el texto del informe: si no vino, no se resume ni se inventa"],
            "degrades_to": ("informe",),
            "caso": "hallazgos.md · md · 648 b — el informe que escribió la corrida de TP53",
        },
        "figure": {
            "type": "imagen", "adapt": _imagen_o_ficha,
            "shape_changes": ["los bytes del archivo → `imagen`: `base64 + mime olfateado` se "
                              "envuelve en `content` como `data:<mime>;base64,…`, que es el "
                              "sobre que el renderer lee. Un `data_uri` ya armado también entra",
                              "sin bytes: ficha (jamás un marco vacío)"],
            "never_filled": ["los bytes de la figura", "sus dimensiones, que la referencia no trae",
                             "el pLDDT y las cisteínas que el título del artefacto NARRA: son del "
                             "cálculo del stack, no se re-derivan de la imagen"],
            "degrades_to": ("informe",),
            "caso": "figura_sintetica.png · v1 · sha256 y captureQuality declarados; "
                    "un segundo registro sintético del mismo kind conserva la misma forma.",
        },
        "dataset": {
            "type": "planilla", "adapt": _planilla_o_ficha,
            "shape_changes": ["`rows`/`records`/`data` → filas de planilla",
                              "un `.csv`/`.tsv` crudo en `content` se PARTE en filas: el "
                              "separador ya está en el archivo, no se decide nada",
                              "sin filas ni CSV: ficha (jamás una grilla en blanco)"],
            "never_filled": ["las filas: un CSV que no viajó no se re-lee del disco de nadie"],
            "degrades_to": ("informe",),
            "caso": "composicion.csv · csv · 93 b — la composición de aminoácidos, 5 filas",
        },
        # ── los siete sin tipo propio en Aleph: ficha honesta, no forma prestada ─────
        # No se mapean a `3d`, `cad` ni `volume3d`: esos tipos PROMETEN un render que
        # nadie produce, y una promesa incumplida es peor que un informe que dice la
        # verdad. Que Aleph no tenga tipo para una estructura molecular es un hecho del
        # vocabulario, y el traductor de Fase 6 lo va a leer acá.
        "notebook": {
            "type": "informe", "adapt": _cuaderno_o_ficha,
            "shape_changes": ["el `.ipynb` se desarma en el markdown que la pantalla pinta: "
                              "celdas markdown tal cual, celdas de código en fences del "
                              "lenguaje que el cuaderno declara, y las salidas que el kernel "
                              "YA dejó adentro (imágenes embebidas, stdout y errores)",
                              "sin `content`: ficha con nombre, formato, tamaño y ruta",
                              "un `.ipynb` ilegible: su texto tal cual, sin desarmar"],
            "never_filled": ["las celdas y sus salidas: el .ipynb no se ejecuta ni se re-renderiza. "
                             "Una celda que nunca corrió sale SIN salida, no con una inventada",
                             "el `text/html` de una salida: no se re-renderiza HTML ajeno"],
            "caso": "analisis.ipynb · ipynb · 479 b — un cuaderno válido con una celda ejecutada",
        },
        "structure": {
            "type": "informe", "adapt": lambda a: _texto_o_ficha(a, que_es="estructura molecular"),
            "shape_changes": ["ficha de la estructura; con `content`, su texto"],
            "never_filled": ["la geometría: no se parsea el PDB ni se deriva un render 3D"],
            "caso": "modelo.pdb · pdb · 308 b — cabecera y tres átomos de un Cα",
        },
        "sequence": {
            "type": "informe", "adapt": lambda a: _texto_o_ficha(a, que_es="secuencia"),
            "shape_changes": ["ficha de la secuencia; con `content`, el FASTA tal cual"],
            "never_filled": ["el largo y la composición: se calculan ejecutando, no mirando"],
            "caso": "tp53_P04637.fasta · fasta · 490 b — la secuencia canónica de TP53",
        },
        "genomics": {
            "type": "informe", "adapt": lambda a: _texto_o_ficha(a, que_es="datos genómicos"),
            "shape_changes": ["ficha; con `content`, el texto del VCF/BED"],
            "never_filled": ["las variantes: no se parsea el VCF para contar ni anotar"],
            "caso": "variantes.vcf · vcf · 131 b — VCFv4.2 con rs28934578 (TP53 R175H)",
        },
        "spectrum": {
            "type": "informe", "adapt": lambda a: _texto_o_ficha(a, que_es="espectro"),
            "shape_changes": ["ficha; con `content`, el texto del mzML"],
            "never_filled": ["los picos: no se deriva un espectro de una referencia"],
            "caso": "espectro.mzml · mzml · 66 b — mzML 1.1.0 bien formado",
        },
        "model": {
            "type": "informe", "adapt": lambda a: _ficha(a, que_es="modelo entrenado"),
            "shape_changes": ["ficha del modelo: nombre, formato, tamaño, ruta"],
            "never_filled": ["sus pesos y su arquitectura: un binario no se describe adivinando",
                             "y NO se deserializa: abrir un pickle ajeno es ejecutar código ajeno"],
            "caso": "modelo.pkl · pkl · 58 b — un pickle real de la corrida",
        },
        "archive": {
            "type": "informe", "adapt": lambda a: _ficha(a, que_es="archivo comprimido"),
            "shape_changes": ["ficha del comprimido"],
            "never_filled": ["su contenido: no se descomprime para listar lo que hay adentro"],
            "caso": "entrega.zip · zip · 622 b — un zip real con el FASTA adentro",
        },
    },
    # [Convergencia · superficie 7] LAS SEIS CLASES DE OFICINA — la fila que faltaba.
    #
    # EL AGUJERO QUE TAPA, MEDIDO: `openwork.js:210` posteaba a `/v1/workspaces/artifacts`
    # desde que existe el plugin, y esta tabla no tenía la clave `oficina`. Corrido contra
    # el borde HTTP real con el payload literal del plugin, las SEIS clases devolvían
    # `422 workspace_kind_unknown`, y el propio plugin se las tragaba a su bitácora
    # (`openwork.js:220-223`: «un tipo que el puente RECHAZA con causa no es un error del
    # turno»). O sea: el 100 % de lo que produce Oficina se perdía, y se perdía
    # elegantemente —con causa, con copy, sin romper el turno— y sin que nadie se enterara.
    #
    # LOS DESTINOS SALEN DE `claseDe()` (openwork.js:127-136), no de una intuición sobre
    # qué produce una oficina. Y el corte entre «tipo rico» y «ficha» sale de `esBinario()`
    # (openwork.js:138-141): lo que viaja utf8 es texto y llega entero; lo binario que
    # Aleph no puede re-derivar llega como ficha, salvo la imagen, cuyos bytes sólo
    # necesitan otro sobre.
    "oficina": {
        "document": {
            "type": "documento", "adapt": lambda a: _tipado_o_ficha(a, que_es="documento", tipo="documento"),
            "shape_changes": ["el texto utf8 (.md/.txt) pasa tal cual a `content`",
                              "binario (.docx/.pdf): ficha con nombre, ruta y tamaño"],
            "never_filled": ["el texto de un .docx: parsear OOXML sería DERIVAR dato, no adaptarlo"],
            "degrades_to": ("informe",),
            "caso": "un .md del proyecto cruza entero; un .docx cruza como ficha",
        },
        "spreadsheet": {
            "type": "planilla", "adapt": _csv_o_ficha,
            "shape_changes": ["un .csv utf8 se parte en `cols` + `rows` (el separador ya está en el dato)",
                              "un .xlsx (base64): ficha, jamás una grilla en blanco"],
            "never_filled": ["las celdas de un .xlsx: abrirlo exigiría una lib adentro del puente"],
            "degrades_to": ("informe",),
            "caso": "presupuesto.csv → cols + filas; presupuesto.xlsx → ficha",
        },
        # OJO — y esto se midió, no se supuso: un `.pptx` de Oficina llega SIEMPRE en
        # base64 (`esBinario` lo lista), así que NO puede cruzar al tipo `presentacion`.
        # Ese tipo tiene por contrato un `content` markdown que `_gen_pptx` convierte en
        # slides; meterle un base64 haría que la descarga generara un deck de basura.
        # Un binario que Aleph no puede re-derivar es una ficha honesta — la misma
        # decisión que el `model` y el `archive` de Ciencia.
        "presentation": {
            "type": "informe", "adapt": lambda a: _ficha(a, que_es="presentación"),
            "shape_changes": ["ficha de la presentación: nombre, ruta, tamaño"],
            "never_filled": ["sus slides: un .pptx no se abre para contarlos ni describirlos",
                             "y NO se cruza como `presentacion`: ese tipo promete un markdown "
                             "que se vuelve deck, y esto son bytes de un deck ya hecho"],
            "caso": "pitch.pptx → ficha; el tipo `presentacion` es para el markdown que SE VUELVE deck",
        },
        "page": {
            "type": "web", "adapt": lambda a: _tipado_o_ficha(a, que_es="página", tipo="web"),
            "shape_changes": ["el HTML utf8 pasa tal cual a `content`"],
            "never_filled": ["los recursos que el HTML referencia y no viajaron con él"],
            "degrades_to": ("informe",),
            "caso": "nota.html → `web`, y se puede volver a bajar como .html",
        },
        "image": {
            "type": "imagen", "adapt": _imagen_base64_o_ficha,
            "shape_changes": ["`base64 + extensión` → `data:<mime>;base64,…` (el mismo dato, otro sobre)",
                              "un .svg viaja utf8 y se envuelve igual",
                              "extensión que no sabemos pintar: ficha, jamás un mime inventado"],
            "never_filled": ["los píxeles: no se reescala, no se convierte de formato",
                             "sus dimensiones, que la referencia no trae"],
            "degrades_to": ("informe",),
            "caso": "logo.png (base64) → imagen con su data URI; diagrama.svg (utf8) → idem",
        },
        # El catch-all de `claseDe()`. No necesita tipo nuevo: es exactamente el caso que
        # Ciencia ya resolvió con una ficha, y por eso reusa el mismo adaptador.
        "file": {
            "type": "informe", "adapt": lambda a: _ficha(a, que_es="archivo"),
            "shape_changes": ["ficha del archivo: nombre, ruta, tamaño"],
            "never_filled": ["su contenido: una extensión que nadie clasificó no se adivina"],
            "caso": "adjunto.bin → ficha honesta, y cae a la base (ley 4)",
        },
    },
    "legal": {
        # Una revisión sólo cruza si el plugin del workspace vio una cita ya
        # verificada por Legal. El puente no resume ni completa conclusiones.
        "legal_review": {
            "type": "informe", "adapt": lambda a: _texto_o_ficha(a, que_es="revisión legal"),
            "shape_changes": ["respuesta citada del workspace → informe"],
            "never_filled": ["citas o conclusiones que Legal no verificó"],
            "caso": "revisión de contrato con cita verificada; el plugin la cruza sólo tras session.idle",
        },
        # [Legal · artefactos] LAS DOS FILAS QUE FALTABAN — y con ellas Legal deja de ser
        # el único vertical que sólo entrega texto.
        #
        # EL AGUJERO QUE TAPAN. `legal_review` era la ÚNICA clave de este workspace, así
        # que el oficio entero de doc.haus —redlines, documentos redactados, ediciones con
        # control de cambios— no tenía dónde aterrizar: aunque el plugin lo hubiera
        # posteado, habría vuelto `422 workspace_kind_unknown`. Es el mismo agujero que
        # `oficina` tuvo hasta la superficie 7, con el atenuante de que allá el plugin sí
        # posteaba; acá ni siquiera se cosechaba.
        "legal_redline": {
            "type": "informe", "adapt": _redline_a_informe,
            "shape_changes": ["`antes`/`despues` —los dos textos que la tool YA grabó en la "
                              "cola de revisión— se envuelven en el markdown que el renderer espera",
                              "el documento, el autor y el número de redline pasan tal cual a la cabecera"],
            "never_filled": ["el lado del cambio que la tool no devolvió: si falta el `antes`, "
                             "NO se lee el documento para reconstruirlo",
                             "el veredicto: un redline es una PROPUESTA, y el puente no dice "
                             "si conviene aceptarla"],
            "caso": "redline de cláusula: `oldText` → `replacement`, con su `#id` en la cola de doc.haus",
        },
        # Mismo criterio que `oficina/document`, y por la misma razón: el `.docx` que
        # `draft-document` deja en el matter es binario y Aleph no lo puede re-derivar, así
        # que viaja como ficha honesta. Parsear OOXML acá sería DERIVAR dato, no adaptarlo.
        "legal_document": {
            "type": "documento", "adapt": lambda a: _tipado_o_ficha(a, que_es="documento legal", tipo="documento"),
            "shape_changes": ["texto utf8 (.md/.txt) → `content` sin transformación",
                              "binario (.docx/.pdf): ficha con nombre, ruta y tamaño"],
            "never_filled": ["el texto de un .docx: parsear OOXML sería DERIVAR dato",
                             "las cláusulas que quedaron sin llenar: eso lo dice la propia tool en su salida"],
            "degrades_to": ("informe",),
            "caso": "un .docx redactado en el matter cruza como ficha y se puede volver a bajar",
        },
    },
    # [Gate 4 · F6-diseño] Caso ejecutable de la salida de Diseño: el exporter entrega
    # HTML como texto. El puente no lo reinterpreta ni rellena: se conserva como informe
    # con el contenido exacto, que es lo único honesto que puede reclamar la Biblioteca.
    "diseno": {
        # [Convergencia · superficie 7] ERA `informe`, Y ESO PERDÍA EL FORMATO DE ORIGEN.
        # Medido: entraba un `<!doctype html>…` y salía `informe`, cuyos formatos son
        # `md · pdf · docx` — o sea que la obra ya no se podía volver a bajar como `.html`.
        # El contenido no se falseaba (el `content` era el HTML exacto), pero el envase
        # mentía sobre qué era, y el usuario perdía el archivo que Diseño acababa de
        # exportar. El vocabulario tiene `web` con `formats: ["html"]` justo para esto.
        #
        # Mismo patrón que `oficina/page`: texto → el tipo rico; sin texto → ficha. Nada
        # de esto es dato nuevo — es el mismo HTML, llamado por su nombre.
        "design_export": {
            "type": "web", "adapt": lambda a: _tipado_o_ficha(a, que_es="exportación de diseño", tipo="web"),
            "shape_changes": ["`data.content` (HTML exportado) pasa sin transformación a `content`",
                              "sin contenido: ficha con nombre, ruta y tamaño"],
            "never_filled": ["markup, estilos, recursos o metadatos ausentes"],
            "degrades_to": ("informe",),
            "caso": "export HTML de Diseño, cruzado por `verify_fase6_diseno.py`",
        },
    },
    # [Gate 4 · F6-finanzas] LAS FILAS DE FINANZAS. Misma disciplina que Ciencia: ninguna
    # se escribió de intuición — cada una tiene su caso EJECUTADO contra el stack corriendo
    # sin llave y sin cuenta, y su payload quedó guardado.
    "finanzas": {
        "market_ohlcv": {
            "type": "planilla", "adapt": _ohlcv_a_planilla,
            "shape_changes": ["`{símbolo: [barras]}` se aplana a filas y gana la columna `symbol`",
                              "sin barras para ningún símbolo: ficha, jamás una grilla en blanco"],
            "never_filled": ["las barras que el origen no devolvió: no se interpolan ni se ponen en 0",
                             "la moneda y el ajuste: si el origen no los dijo, no se deducen"],
            "degrades_to": ("planilla",),
            "caso": "BTC-USDT diario · OKX · 2026-08-01→08 · 1.647 b — 6 barras reales, sin llave",
        },
        "alpha_zoo": {
            "type": "planilla", "adapt": _resultado_anidado_a_planilla,
            "shape_changes": ["se desenvuelve `{status, result:{items}}` y las `items` son las filas",
                              "`status != ok`: no se convierte — la causa del origen manda"],
            "never_filled": ["la fórmula de un alpha: si el zoo no la trae, la celda queda vacía"],
            "degrades_to": ("planilla",),
            "caso": "alpha101 · list_alphas · limit=4 · 1.783 b — 4 de los 101 de Kakushadze",
        },
    },
    # [Gate 4 · Fase 6 · §6.f] El modo largo de LA SALA. No es un workspace: es una
    # capacidad. Pero lo que produce sí es un artefacto de primera clase, y §6.f lo nombra
    # con su tipo: «informe final como artefacto `informe` con las fuentes en el pasaporte».
    "sala_research": {
        "deep_research_report": {
            "type": "informe", "adapt": lambda a: _texto_o_ficha(a, que_es="informe de investigación"),
            "shape_changes": ["informe citado del motor → informe"],
            # Las fuentes son del motor, no del puente. El motor las devuelve en `sources`
            # (`third_party/ldr/src/local_deep_research/api/research_functions.py:326-334`,
            # que es su `all_links_of_system`) y el servidor del pack las normaliza a
            # `{url, titulo}` sin inventar ninguna. Si el motor no encontró fuentes, el
            # informe cruza SIN fuentes y se ve que no las tiene: un informe de deep
            # research sin bibliografía es una señal, no un hueco que se rellena.
            "never_filled": ["fuentes que el motor no devolvió", "conclusiones que el informe no saca"],
            "caso": "una obra larga: el motor devuelve summary + sources, y el informe cruza con su sha256",
        },
    },
    # [Gate 4 · Fase 6 · §6.a.bis] La búsqueda base de LA SALA. Tampoco es un workspace.
    # §6.a.bis: «fuentes citadas en el hilo, resultado como artefacto con las fuentes en el
    # pasaporte, al canvas».
    "sala_busqueda": {
        "web_search_answer": {
            "type": "informe", "adapt": lambda a: _texto_o_ficha(a, que_es="respuesta con fuentes"),
            "shape_changes": ["respuesta citada del motor → informe"],
            # Las citas son del motor. Vane emite el bloque `source` con los `Chunk` que de
            # verdad usó (`third_party/vane/src/lib/agents/search/researcher/index.ts:210-214`),
            # y el adaptador las normaliza a `{url, titulo}` deduplicando por URL. Una cita
            # que el motor no emitió NO se deduce del texto: si la respuesta menciona algo
            # sin fuente, cruza sin fuente y se ve.
            "never_filled": ["citas que el motor no emitió", "fuentes deducidas del texto de la respuesta"],
            "caso": "una consulta con 8 resultados: cruza la respuesta con sus URLs citadas",
        },
    },
}

#: Tipos que cada workspace ACEPTA de vuelta (ley de producto 7: compatibilidad por
#: TIPO, jamás por MCP). Lo que un workspace no acepta NO se rechaza: cae a la base,
#: que es el suelo común y no un estado roto (ley 4).
#:
#: [F3-ciencia] Ciencia reclama las tres formas que su banco de trabajo sabe mostrar en
#: línea: un informe, una imagen y una planilla. Un `cad`, un `dicom` o un `volume3d` que
#: llegue de otro workspace **no se rechaza** — cae a la base y se ve ahí, que es
#: exactamente lo que la ley 4 pide.
#: [Gate 4 · Fase 6] **LOS QUE SÓLO PRODUCEN.**
#:
#: Hasta esta fase, toda clave de `TABLE` era un WORKSPACE, y la invariante del puente
#: —«un workspace con filas tiene que declarar qué acepta de vuelta» (ley 7)— alcanzaba.
#: La Sala trajo una categoría que no existía: **un MODO**. Deep Research y la búsqueda
#: base producen artefactos de primera clase, pero **no son un lugar a donde mandar
#: trabajo**: no hay pantalla que abrir, no hay banco donde dejarlo. Mandarles un
#: artefacto no tendría a quién.
#:
#: Se declara acá, como DATO y no como excepción en una vara, porque la diferencia entre
#: «no acepta nada» y «se olvidaron de declarar qué acepta» tiene que ser legible por el
#: código. Sin esta lista, la vara del puente no puede distinguirlas — y de hecho no podía:
#: la agregó en rojo hasta que esto se declaró.
#:
#: Es la otra mitad del `oculto` del registro (`product/backend/app/phase1/router.py`):
#: uno impide que aparezcan en el menú y como destino; éste impide que reclamen por tipo.
SOLO_PRODUCEN: frozenset = frozenset({"sala_research", "sala_busqueda", "sala_browser"})

#: ⚠️ `sala_browser` entra acá y **A PROPÓSITO NO tiene fila en `TABLE`**. La censo de §6.e
#: midió que las filas de `sala_research` (`deep_research_report`) y `sala_busqueda`
#: (`web_search_answer`) son CÓDIGO INALCANZABLE: quien produce escribe al almacén por el
#: borde de escritura —que arma el pasaporte solo— sin pasar por `bridge.cross()`, porque el
#: puente traduce de un STACK HEREDADO a Aleph y estas tres son capacidades de la casa.
#: Agregar una cuarta fila muerta sería declarar un contrato que nadie ejerce. Estar en
#: `SOLO_PRODUCEN` es lo que distingue «no acepta nada» de «se olvidaron de declararlo», que
#: es justo lo que esta lista existe para decir.

#: Tipos que cada workspace ACEPTA de vuelta. Lo que no está en `SOLO_PRODUCEN` y no tiene
#: fila acá es un olvido, no una decisión — y la vara lo dice.
ACCEPTS: dict[str, tuple] = {
    "educacion": ("informe",),
    # [Convergencia · superficie 7] EL CRITERIO ES SIMÉTRICO Y SE PUEDE DEFENDER: Oficina
    # acepta de vuelta **las mismas formas que sabe producir**, leídas de su propio
    # `claseDe()` — document · spreadsheet · presentation — más `informe`, que es la forma
    # de prosa que aceptan los cinco. Y `presentacion` está acá porque ahora Aleph puede
    # entregarle un .pptx REAL (`artifact_export._gen_pptx`), no la promesa de uno.
    #
    # `imagen` y `web` quedan AFUERA a propósito, aunque su proyecto guarde .png y .html:
    # su cara es una suite de oficina, no un visor. Y la ley 4 hace que equivocarse por
    # defecto sea barato — lo no reclamado cae a la base, que es un lugar sano, mientras
    # que reclamar de más manda trabajo a un workspace que no sabe qué hacer con él.
    "oficina": ("documento", "planilla", "presentacion", "informe"),
    "ciencia": ("informe", "imagen", "planilla"),
    # [Legal · artefactos] `documento` ENTRA por la misma razón exacta que `web` entró en
    # Diseño: desde esta obra Legal PRODUCE documentos —`draft-document` deja un `.docx` en
    # el matter— y un workspace que no reclama su propia salida es incoherente. Sin esta
    # palabra, `claims()` daba False sobre el documento que Legal acababa de redactar y la
    # obra caía a la base en vez de volver a su escritorio.
    "legal": ("informe", "documento"),
    # [Convergencia · superficie 7] `web` ENTRA porque ahora Diseño lo PRODUCE, y un
    # workspace que no reclama su propia salida es incoherente: `claims()` habría dado
    # False sobre el artefacto que él mismo acaba de exportar, y la obra habría caído a
    # la base en vez de volver a su taller. Además es lo que mejor sabe mostrar — su
    # producto entero es renderizar prototipos HTML.
    "diseno": ("informe", "imagen", "web"),
    # [F6-finanzas] Finanzas reclama las mismas tres formas que su cara sabe mostrar: una
    # planilla (su grilla), una imagen (sus gráficos) y un informe. Lo que no acepta NO se
    # rechaza: cae a la base, que es el suelo común (ley 4).
    "finanzas": ("planilla", "imagen", "informe"),
}


def accepts(workspace: str) -> tuple:
    return ACCEPTS.get((workspace or "").strip().lower(), ())


def claims(workspace: str, artifact_type: str) -> bool:
    """¿Este workspace reclama un artefacto de este tipo? Se normaliza contra EL
    vocabulario antes de comparar: `doc` y `documento` no pueden dar respuestas
    distintas."""
    t = vocabulary.normalize(artifact_type) or artifact_type
    return t in accepts(workspace)


def kinds(workspace: str) -> tuple:
    return tuple(TABLE.get((workspace or "").strip().lower(), {}).keys())


def cross(workspace: str, artifact: dict) -> dict:
    """Cruza el puente: `{kind, name, data}` del stack → obra con tipo canónico.

    Devuelve `{type, title, …}` listo para el borde de escritura del almacén (que lo
    valida otra vez contra el vocabulario: este puente propone, el borde dispone).
    Levanta `BridgeError` cuando entregar exigiría inventar dato."""
    ws = (workspace or "").strip().lower()
    kind = str((artifact or {}).get("kind") or "").strip()
    fila = TABLE.get(ws, {}).get(kind)
    if not fila:
        raise BridgeError("workspace_kind_unknown",
                          f"el workspace '{ws}' emitió un artefacto '{kind}' que el puente no mapea",
                          kind)
    obra = fila["adapt"](artifact)
    # El tipo que produce el adaptador tiene que ser el que la tabla declara, O una
    # DEGRADACIÓN declarada en la misma fila. Si divergen sin declararlo, la tabla dejó de
    # describir lo que el código hace — y una tabla que miente es peor que no tenerla.
    permitidos = {fila["type"], *(fila.get("degrades_to") or ())}
    assert obra.get("type") in permitidos, (kind, obra.get("type"), permitidos)
    canon = vocabulary.normalize(obra["type"])
    if not canon:
        raise BridgeError("workspace_kind_unknown",
                          f"el puente produjo un tipo fuera del vocabulario: {obra['type']}", kind)
    obra["type"] = canon
    return obra


def as_json() -> dict:
    """La tabla, legible: para el reporte, para una vara y para la extracción del
    traductor en Fase 6. Los adaptadores no viajan (son código)."""
    return {
        "workspaces": {
            ws: {
                "accepts": list(accepts(ws)),
                # [Fase 6] Que un consumidor pueda DISTINGUIR un modo de un workspace sin
                # tener que adivinar por `accepts: []`. El próximo lector de esta tabla es
                # la extracción del traductor universal, y «acepta nada» y «no es un
                # lugar» son dos cosas distintas que se ven iguales si no se dicen.
                "solo_produce": ws in SOLO_PRODUCEN,
                "kinds": {
                    k: {kk: vv for kk, vv in fila.items() if kk != "adapt"}
                    for k, fila in filas.items()
                },
            }
            for ws, filas in TABLE.items()
        },
        "causes": CAUSES,
    }


__all__ = ["TABLE", "ACCEPTS", "SOLO_PRODUCEN", "ADAPTERS", "CAUSES", "BridgeError",
           "accepts", "claims", "kinds", "cross", "as_json"]
