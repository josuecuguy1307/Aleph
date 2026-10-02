#!/usr/bin/env python3
"""prompt_bridge.py — mensajes OpenAI ⇄ prompt plano del CLI (compartido por AMBOS providers).

Heredado VERBATIM del shim probado (eval/shim_claude_code.py, verificado en toda la
matriz Step 3/4): el CLI recibe UNA conversación renderizada + el catálogo de tools
como texto, y responde o texto final o el marcador <function=NOMBRE>{json}</function>
que acá se RE-EMITE como tool_calls OpenAI estructurado. Cero-teatro: solo se emite
tool_calls si el modelo REALMENTE puso un marcador; si nada parsea → texto.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Optional

_FUNC_RE = re.compile(r"<function=\s*([A-Za-z0-9_.\-]+)\s*>(.*?)</function>", re.DOTALL)
_FUNC_OPEN_RE = re.compile(r"<function=\s*([A-Za-z0-9_.\-]+)\s*>", re.DOTALL)

# ══ LA HOMONIMIA: LAS TOOLS DEL HARNESS SE LLAMAN IGUAL QUE LAS DEL CLI ═══════════════
#
# EL BUG QUE ESTO CIERRA, medido en Oficina el 2026-08-26. El harness de OpenWork declara
# 18 tools y entre ellas están `bash`, `write`, `edit`, `read`, `grep`, `glob`, `task` y
# `todowrite`: **exactamente los mismos nombres que el CLI que hace de cerebro ya tiene
# adentro**. El modelo lee la lista, reconoce sus propias herramientas, y en vez de emitir
# el marcador `<function=bash>` **usa las suyas**. El guard de pureza de `base.py` lo pilla
# (`exec_events > 0`) y descarta la generación ENTERA.
#
# LOS NÚMEROS, del registro de espacios (`workspace_step.tool_calls_requested`):
#     Diseño   115 pasos con tools → 106 con llamada   (92 %)   tools de dominio
#     Oficina   33 pasos con tools →   4 con llamada   (12 %)   tools homónimas
# No es el tamaño del catálogo: Finanzas cruza 94 tools y llama en el 42 %.
#
# Y ES CARO EN LAS DOS PUNTAS. En un turno medido, 46,3 s de generación (8 acciones)
# fueron a la basura; después, el reintento —el MISMO prompt, sin una palabra de lo que
# acababa de pasar— salió con una excusa INVENTADA: «habilitá acceso de escritura en el
# workspace y `@oai/artifact-tool`». Ninguna de las dos cosas existe: `grep` de
# `@oai/artifact-tool` y de `load_workspace_dependencies` sobre el árbol entero da CERO, y
# el agente `openwork` tiene `write` y `edit` en `allow`. O sea que el usuario recibió, con
# `ok: true`, un motivo que nadie le negó nunca.
#
# POR QUÉ EL TEXTO QUE YA HABÍA NO ALCANZA. El bloque decía «(las ejecuta EL SISTEMA, no
# vos)» arriba y «no ejecutes nada vos mismo» abajo — las dos veces **en abstracto y sin
# consecuencia**. Contra el prompt de sistema del propio CLI («sos un agente, usá tus
# herramientas»), una regla sin nombres y sin costo pierde. Acá se dicen las dos cosas que
# faltaban: **QUÉ nombres chocan, uno por uno**, y **QUÉ pasa si actúa** (se tira todo, no
# se tira «un poquito»).
#
# LO QUE ESTO **NO** ES: una lista blanca ni un filtro. No se le saca una sola tool al
# stack —este puente es un proxy, recortarle el catálogo sería mentirle— y si no hay
# homonimia el bloque no aparece. Es una advertencia, y se paga en tokens sólo cuando el
# choque es real.
#
#: Los nombres NATIVOS de los CLIs que hacen de cerebro. **Es una lista de hechos, no una
#: familia semántica**: cada entrada es un nombre que uno de estos binarios expone de
#: fábrica. Se dejaron AFUERA a propósito los sinónimos plausibles (`search`, `find`,
#: `list`, `create`, `run`, `delegate`…): un nombre que el CLI no tiene no es una
#: homonimia, y avisar de un choque que no existe le saca crédito al aviso que sí importa
#: —además de cobrarle tokens a un stack que no tiene el problema—. Si mañana un CLI gana
#: una tool, se agrega ACÁ y con su nombre; no se adivina por parecido.
#:
#:   claude  Bash · Read · Write · Edit · MultiEdit · Glob · Grep · Task · TodoWrite ·
#:           WebFetch · WebSearch · NotebookEdit
#:   codex   shell · apply_patch · update_plan · view_image · web_search
#:
#: Se compara en minúsculas y sin separadores, así que `todo_write`, `todoWrite` y
#: `TodoWrite` son el mismo nombre.
_NATIVAS_DEL_CLI = frozenset({
    # claude
    "bash", "read", "write", "edit", "multiedit", "glob", "grep", "task",
    "todowrite", "webfetch", "websearch", "notebookedit",
    # codex
    "shell", "applypatch", "updateplan", "viewimage", "websearch",
})


# ══ EL MARCADOR ES PROTOCOLO, NUNCA PROSA ═══════════════════════════════════════════
#
# Este puente le PIDE al modelo que escriba `<function=NOMBRE>{json}</function>` y lo
# re-emite como `tool_calls`. Lo que no puede pasar es que ADEMÁS se lo mande al usuario
# como texto: la llamada ya viaja estructurada, y la persona lee el andamio.
#
# Es distinto del filtro de `workspace_brain.py`, y por eso no se comparte: aquél limpia lo
# que un proveedor CUALQUIERA duplica en `content` sin que nadie se lo haya pedido. Éste es
# la casa no repitiendo su propio protocolo. Mismo síntoma, dos causas.
_MARCA = "<function="


def texto_visible(text):
    """El texto hasta el primer marcador. La prosa que lo precede se conserva entera."""
    if not isinstance(text, str):
        return text
    i = text.find(_MARCA)
    return text[:i].rstrip() if i >= 0 else text


class FiltroVivo:
    """`texto_visible` sobre un texto que llega partido, para el SSE.

    Llamar al filtro de una pieza en cada pedazo NO alcanza: `<func` + `tion=bash>` son dos
    trozos que, de a uno, son prosa inocente. Se retiene la cola que todavía podría ser el
    principio del marcador y se suelta el resto; confirmado el marcador, no sale nada más.
    """

    def __init__(self):
        self._pend = ""
        self._corto = False

    def empujar(self, texto):
        if self._corto or not isinstance(texto, str) or not texto:
            return ""
        self._pend += texto
        i = self._pend.find(_MARCA)
        if i >= 0:
            self._corto = True
            salida, self._pend = self._pend[:i], ""
            return salida
        n = 0
        tope = min(len(self._pend), len(_MARCA) - 1)
        for k in range(tope, 0, -1):
            if _MARCA.startswith(self._pend[-k:]):
                n = k
                break
        corte = len(self._pend) - n
        salida, self._pend = self._pend[:corte], self._pend[corte:]
        return salida

    def resto(self):
        """Lo retenido que al final no era marcador. Sin esto se come el último `<`."""
        if self._corto:
            return ""
        salida, self._pend = self._pend, ""
        return salida


def _clave_de_tool(nombre: str) -> str:
    """`Todo_Write` → `todowrite`. La comparación no puede depender del estilo del stack."""
    return "".join(ch for ch in str(nombre or "").lower() if ch.isalnum())


def homonimas(tools: list) -> list:
    """Los nombres declarados por el harness que un CLI también tiene NATIVOS.

    Devuelve los nombres **tal como los declaró el stack** (no la clave normalizada): lo
    que se le va a mostrar al modelo tiene que ser el string que va a tener que escribir
    adentro de `<function=...>`, letra por letra."""
    out = []
    for t in (tools or []):
        fn = t.get("function", t) if isinstance(t, dict) else {}
        nombre = str(fn.get("name") or "").strip()
        if nombre and _clave_de_tool(nombre) in _NATIVAS_DEL_CLI:
            out.append(nombre)
    return out


def obliga_a_tool(tool_choice) -> bool:
    """¿Este `tool_choice` OBLIGA a llamar una herramienta? Gemelo del de `workspace_brain`.

    Está duplicado a propósito y no importado: `platform/` no depende de `product/`, y una
    de las dos capas tendría que romper esa dirección para compartir tres líneas.
    """
    if isinstance(tool_choice, str):
        return tool_choice.strip().casefold() == "required"
    return isinstance(tool_choice, dict) and bool(tool_choice)


def nombre_exigido(tool_choice) -> str:
    """La función que el llamante exige por nombre, o `""` si sólo exige «alguna»."""
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function")
        if isinstance(fn, dict):
            return str(fn.get("name") or "").strip()
    return ""


def _firma_params(esquema) -> str:
    """La firma de los parámetros: `q: string, n?: number, tipo="web_search"`.

    POR QUÉ EXISTE. Hasta acá esta línea era `", ".join(params.keys())` — sólo los
    NOMBRES—, heredada verbatim del shim de evaluación (`eval/shim_claude_code.py:62`).
    No fue una decisión con un costo evaluado: no hay comentario ni mensaje de commit que
    la justifique, y el `desc[:200]` de al lado prueba que sí hubo conciencia de tamaño
    donde se la tuvo. El JSON Schema completo —tipos, `const`, `required`, `enum`— se
    perdía en el camino, y el modelo tenía que adivinarlo.

    MEDIDO, con 49 tools reales de tres conectores grabados
    (`platform/inspection/grabaciones/*/02-list_tools.json`):

      · `search(queries)` donde `queries` es `array<string>` → el modelo devolvía
        `{"arg": "..."}`, copiando el ejemplo genérico de más abajo. No podía saber que
        era una lista: nadie se lo dijo.
      · `get_weather(city, unit)`, ambas `string` → acertaba, porque con escalares el
        nombre alcanza para inferir.

    POR QUÉ UNA FIRMA Y NO EL JSON SCHEMA CRUDO. Medido también: volcar el schema entero
    es **1,88×** este bloque, y sobre las 94 tools que declara Finanzas son **+4.000
    tokens en cada turno** — encima de un preámbulo de CLI que ya pesa. La firma dice lo
    que el modelo necesita para acertar (tipo, lista, obligatoriedad, valor fijo) y cuesta
    prácticamente lo mismo que la lista de nombres que reemplaza.
    """
    props = (esquema or {}).get("properties") or {}
    if not isinstance(props, dict) or not props:
        return ""
    requeridos = set((esquema or {}).get("required") or [])
    partes = []
    for clave, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        # `const` PRIMERO, y es el que más importa: un discriminante equivocado hace que
        # el validador del stack descarte la llamada entera aunque el resto esté perfecto.
        if "const" in spec:
            tipo = f'="{spec["const"]}"'
        elif isinstance(spec.get("enum"), list) and spec["enum"]:
            tipo = ": " + "|".join(str(x) for x in spec["enum"][:6])
        else:
            t = spec.get("type") or "any"
            if t == "array":
                t = f"{((spec.get('items') or {}).get('type') or 'any')}[]"
            tipo = f": {t}"
        # ── LA UNIDAD NO SE ADIVINA ────────────────────────────────────────────────────
        # MEDIDO el 2026-08-29 en un turno real de Ciencia que se caía a la mitad. El
        # `notebook` del stack declara `timeout` en MILISEGUNDOS y lo dice en la
        # descripción del parámetro —«Execution timeout in ms (default: 120s, max: 600s)»—
        # que esta firma tiraba. El modelo veía `timeout: number`, mandó `600` pensando en
        # segundos, y el kernel lo subió a su piso: **5.000 ms**. De ahí salían las cinco
        # respuestas seguidas diciendo «the kernel enforces a hard 5 s per-cell cap» y
        # «matplotlib's import consistently exceeds it». El turno moría peleando contra un
        # tope que nosotros le habíamos fabricado escondiéndole una palabra.
        #
        # SÓLO A LOS NUMÉRICOS, y el motivo es el costo. El docstring de arriba ya midió
        # que volcar el schema entero son +4.000 tokens por turno en Finanzas. Medido
        # sobre las grabaciones reales: los numéricos son el **6,1 %** de los parámetros
        # (3 de 49) y su descripción recortada a 60 chars cuesta **~25 tokens en total**.
        # Un `string` llamado `city` se explica solo; un `number` llamado `timeout` no
        # dice si son segundos, milisegundos o celdas.
        if spec.get("type") in ("number", "integer"):
            _d = (spec.get("description") or "").strip().replace("\n", " ")
            if _d:
                tipo += f" ({_d[:60]})"
        partes.append(f"{clave}{'' if clave in requeridos else '?'}{tipo}")
    return ", ".join(partes)


def _tools_block(tools: list, tool_choice=None) -> str:
    # [medición · tanda de tokens] LA CRUZ DEL CATÁLOGO. Éste es el punto ÚNICO donde el
    # catálogo se rinde al modelo en el camino CLI — la Sala y los seis workspaces pasan
    # por acá. Contar acá da las cruces REALES, que no son los pasos: medido, Finanzas
    # hace 9 pasos pero cruza 8 veces (el último va sin tools, `loop.py:811`), y Ciencia
    # hace 8 pasos y cruza 5. Apagado sin `ALEPH_GRABAR_TOOLS`.
    try:
        from grabador_tools import grabar as _g
        _g("_cruce_prompt_bridge", tools, paso="tools_block")
    except Exception:
        pass
    if not tools:
        return ""
    lines = ["", "HERRAMIENTAS DISPONIBLES (las ejecuta EL SISTEMA, no tú):"]
    for t in tools:
        fn = t.get("function", t)
        name = fn.get("name", "?")
        desc = (fn.get("description") or "").strip().replace("\n", " ")[:200]
        lines.append(f"  - {name}({_firma_params(fn.get('parameters'))}): {desc}")
    lines += [
        "",
        "Para LLAMAR una herramienta responde SOLO con una línea, sin nada más:",
        # EL EJEMPLO ERA LA TRAMPA. Decía `{"arg":"valor"}`, y el modelo lo copiaba
        # LITERALMENTE cuando la firma no le alcanzaba para inferir las claves: llegaba
        # `{"arg": "..."}` a un stack que esperaba `{"queries": [...]}`. Ahora el ejemplo
        # usa nombres evidentemente-de-relleno y la regla dice de dónde salen los reales.
        '  <function=NOMBRE>{"parametro": "valor"}</function>',
        "Las claves del JSON son EXACTAMENTE las de la firma de arriba, con su tipo: "
        "`nombre[]` es una lista, `nombre=\"x\"` va con ese valor fijo, y `nombre?` "
        "se puede omitir.",
        "El sistema la ejecuta de verdad y te devuelve el resultado en el próximo mensaje.",
    ]
    # ── [B0-2 · CLI] EL `tool_choice` QUE ESTE TRANSPORTE SÍ PUEDE EXPRESAR ────────────
    # El CLI no tiene `tool_choice` nativo: no hay bandera de proveedor porque no hay
    # canal estructurado — Claude Code y Codex reciben un prompt plano por `-p` y las
    # tools viajan como el texto de acá arriba. Así que la obligación se dice donde el
    # modelo la puede leer, y —esto es lo que la vuelve real y no teatro— el server
    # COMPRUEBA la salida: si exigimos una llamada y no vino el marcador, no se devuelve
    # el texto como si nada (ver `server.py`, junto a `extract_tool_calls`).
    _exigido = nombre_exigido(tool_choice)
    if obliga_a_tool(tool_choice):
        lines.append(
            f"OBLIGATORIO EN ESTE PASO: tienes que llamar exactamente `{_exigido}`. "
            "No respondas texto final." if _exigido else
            "OBLIGATORIO EN ESTE PASO: tienes que llamar una de las herramientas de "
            "arriba. No respondas texto final.")
    else:
        lines.append("Para la RESPUESTA FINAL escribe texto normal (sin <function=...>).")
    lines.append(
        "Reglas: no ejecutes nada tú mismo, no inventes resultados de herramientas, "
        "fundamenta los datos SOLO en lo que la herramienta devuelva.")
    # ── LA HOMONIMIA, DICHA CON NOMBRE Y CON COSTO ────────────────────────────────────
    # Va al FINAL a propósito: es lo último que el modelo lee antes de la conversación, y
    # es lo que tiene que ganarle a su propio prompt de sistema. Ver el bloque de
    # `_NATIVAS_DEL_CLI` arriba para el defecto que cierra y los números que lo miden.
    _hom = homonimas(tools)
    if _hom:
        _lista = ", ".join(f"`{n}`" for n in _hom)
        lines += [
            "",
            f"⚠️ ATENCIÓN — {len(_hom)} de estas herramientas se llaman IGUAL que las tuyas: "
            f"{_lista}.",
            "NO son las tuyas. Son del sistema que te está preguntando, corren en SU "
            "máquina y sobre SUS archivos. Las tuyas, aquí, no sirven para nada: este paso "
            "no es tu turno de trabajar, es tu turno de DECIR qué hay que hacer.",
            # La consecuencia es la mitad que faltaba. «No lo hagas» sin costo pierde
            # contra un prompt de sistema que dice «sos un agente, actuá».
            "Si en vez del marcador usas tus propias herramientas, el sistema DESCARTA "
            "la respuesta ENTERA —no una parte: todo, incluido lo que hayas razonado "
            "bien— y el trabajo se pierde. Ya pasó: 46 s de generación tirados en un "
            "solo turno.",
            "Y si te falta algo para dar el paso, PEDILO POR SU NOMBRE REAL, el de la "
            "lista de arriba. No inventes herramientas ni permisos que no viste: decir "
            "que te falta algo que nadie te negó manda a la persona a arreglar lo que no "
            "está roto.",
        ]
    return "\n".join(lines)


def _cola_del_paso(tools: list, tool_choice=None) -> str:
    """La orden final del prompt. Con obligación NO puede seguir ofreciendo «o la
    respuesta final»: sería contradecir, dos líneas más abajo, lo que el bloque de
    herramientas acaba de exigir."""
    if tools and obliga_a_tool(tool_choice):
        _n = nombre_exigido(tool_choice)
        return (f"llama `{_n}` (formato <function=...>). Es obligatorio: no hay respuesta "
                f"final en este paso." if _n else
                "una sola llamada a herramienta (formato <function=...>). Es obligatorio: "
                "no hay respuesta final en este paso.")
    return "una sola llamada a herramienta (formato <function=...>) o la respuesta final."


# ══ LAS IMÁGENES VIAJAN COMO IMÁGENES, NO COMO TEXTO ═════════════════════════════════
#
# EL BUG QUE ESTO CIERRA. Hasta acá, un mensaje multimodal —el que manda cualquier paso
# de verificación visual: `[{"type":"text",...},{"type":"image_url",...}]`— caía en el
# f-string de `[Usuario]: {content}` y se rendía con `str(list)`: el data-URL entero,
# ~170 mil caracteres de base64 pegados COMO TEXTO LITERAL en el prompt. El modelo no
# veía nada (base64 no es una imagen), pagaba el contexto igual, y el gate de
# `model-use/v1` tenía razón en rechazar la llamada: el puente NO transportaba imágenes.
#
# CÓMO VIAJAN AHORA. La parte de imagen sale del texto y deja una MARCA numerada
# (`⟦imagen 1⟧`); las imágenes se devuelven aparte, en el mismo orden, y el provider que
# sepa mandarlas las manda por su propio carril (claude: `--input-format stream-json`,
# un bloque `image` por stdin — MEDIDO vivo sobre el binario 2.1.229).
#
# LO QUE NO VIAJA, Y SE DICE: una imagen por URL remota (`https://…`) no se descarga acá.
# Bajar bytes de la red adentro del renderizador del prompt es una llamada de red que
# nadie pidió y que no pasa por ningún gate. Esa parte se rinde como su URL en el texto
# —que es lo que el modelo puede al menos nombrar— y NO cuenta como imagen adjunta.

#: La marca que queda en el texto donde estaba la imagen. Numerada para que el modelo
#: pueda referirse a una de varias («en la ⟦imagen 2⟧ el botón se sale»).
_MARCA_IMG = "⟦imagen {n}⟧"

_DATA_URL_RE = re.compile(r"^data:(?P<mt>[^;,]+);base64,(?P<b64>.*)$", re.DOTALL)


def _img_de_data_url(url: str):
    """`data:image/png;base64,AAA` → {media_type, data}. `None` si no es un data-URL."""
    m = _DATA_URL_RE.match((url or "").strip())
    if not m:
        return None
    mt = (m.group("mt") or "").strip().lower() or "image/png"
    dato = (m.group("b64") or "").strip()
    if not dato or not mt.startswith("image/"):
        return None
    return {"media_type": mt, "data": dato}


#: Igual que la de imagen: la marca dice QUÉ documento es y en qué orden viaja.
_MARCA_DOC = "⟦documento {n}: {nombre}⟧"

#: Lo único que un cerebro Claude sabe leer como documento. El resto son bytes opacos.
_DOC_LEGIBLE = "application/pdf"


def _doc_de_parte(parte: dict):
    """Una parte multimodal → el DOCUMENTO adjunto que trae, o `None`.

    [Aleph] EL AGUJERO QUE TAPA, medido el 2026-08-29 con un adjunto real en Legal que
    dejaba el turno colgado en «working» para siempre.

    Este render ya tenía el caso de las imágenes resuelto —y su comentario cuenta que
    antes se pegaban «~170 mil caracteres de base64 COMO TEXTO LITERAL en el prompt»—,
    pero los DOCUMENTOS nunca entraron en esa cuenta: un PDF llega como
    `{"type":"file","mediaType":"application/pdf","url":"data:…;base64,<megabytes>"}` y
    caía en el `else` final, que hace `json.dumps(parte)`. O sea: los megabytes enteros,
    en base64, adentro del prompt. El CLI no se cae — se queda masticando, y la persona
    ve «working» hasta que se aburre.

    Se aceptan las formas que llegan de verdad al :8926, igual que con las imágenes, sin
    elegirle el dialecto al que llama:
      · AI SDK / OpenWork   `{"type":"file","mediaType":…,"url":"data:…","filename":…}`
      · OpenAI responses    `{"type":"input_file","file_data":"data:…","filename":…}`
      · Anthropic nativo    `{"type":"document","source":{"type":"base64",…}}`

    Returns:
        `{"media_type", "data", "nombre"}`, o `None` si la parte no es un documento.
    """
    if not isinstance(parte, dict):
        return None
    tipo = str(parte.get("type") or "").strip()
    nombre = str(parte.get("filename") or parte.get("name") or "").strip()

    def _de_url(url, mt_declarado=""):
        m = _DATA_URL_RE.match(str(url or "").strip())
        if not m:
            return None
        mt = (m.group("mt") or mt_declarado or "").strip().lower()
        dato = (m.group("b64") or "").strip()
        # Las imágenes ya tienen su camino: acá sólo lo que NO es imagen.
        if not dato or mt.startswith("image/"):
            return None
        return {"media_type": mt or "application/octet-stream", "data": dato,
                "nombre": nombre or "adjunto"}

    if tipo == "file":
        return _de_url(parte.get("url") or parte.get("data"),
                       str(parte.get("mediaType") or parte.get("mime_type") or ""))
    if tipo == "input_file":
        return _de_url(parte.get("file_data"), str(parte.get("mime_type") or ""))
    if tipo == "document":
        src = parte.get("source")
        if isinstance(src, dict) and str(src.get("type") or "") == "base64" and src.get("data"):
            mt = str(src.get("media_type") or _DOC_LEGIBLE).strip().lower()
            return {"media_type": mt, "data": str(src["data"]),
                    "nombre": nombre or "adjunto"}
        if isinstance(src, dict) and str(src.get("type") or "") == "url":
            return _de_url(src.get("url"))
    return None


def _img_de_parte(parte: dict):
    """Una parte multimodal → la imagen INLINE que trae, o `None`.

    Las TRES formas que llegan de verdad al :8926, y las tres se aceptan porque el
    puente es el borde de Aleph y no elige el dialecto del que llama:
      · OpenAI chat        `{"type":"image_url","image_url":{"url":"data:…"}}`
      · OpenAI responses   `{"type":"input_image","image_url":"data:…"}`
      · Anthropic nativo   `{"type":"image","source":{"type":"base64","media_type":…,"data":…}}`
    """
    if not isinstance(parte, dict):
        return None
    tipo = str(parte.get("type") or "").strip()
    if tipo in ("image_url", "input_image"):
        iu = parte.get("image_url")
        url = iu.get("url") if isinstance(iu, dict) else iu
        return _img_de_data_url(str(url or ""))
    if tipo == "image":
        src = parte.get("source")
        if isinstance(src, dict):
            if str(src.get("type") or "") == "base64" and src.get("data"):
                mt = str(src.get("media_type") or "image/png").strip().lower()
                return {"media_type": mt, "data": str(src["data"])}
            if str(src.get("type") or "") == "url":
                return _img_de_data_url(str(src.get("url") or ""))
    return None


def _url_de_parte(parte: dict) -> str:
    """La URL REMOTA de una parte de imagen que no es inline (para rendirla como texto)."""
    if not isinstance(parte, dict):
        return ""
    if str(parte.get("type") or "") in ("image_url", "input_image"):
        iu = parte.get("image_url")
        url = iu.get("url") if isinstance(iu, dict) else iu
        url = str(url or "").strip()
        return url if url and not url.startswith("data:") else ""
    src = parte.get("source") if str(parte.get("type") or "") == "image" else None
    if isinstance(src, dict) and str(src.get("type") or "") == "url":
        url = str(src.get("url") or "").strip()
        return url if url and not url.startswith("data:") else ""
    return ""


#: Por debajo de esto un data-URL es un ícono o una miniatura: cuesta nada y a veces el
#: modelo lo necesita literal. Por encima es un archivo, y un archivo no es texto.
_TOPE_BASE64 = 8 * 1024

_BASE64_INCRUSTADO = re.compile(r"data:([\w.+-]+/[\w.+-]+);base64,([A-Za-z0-9+/=]{%d,})" % _TOPE_BASE64)


def _sin_base64_gigante(texto: str) -> str:
    """Ningún archivo entra al prompt disfrazado de texto — venga por donde venga.

    [Aleph] LA PUERTA QUE FALTABA. El caso de las imágenes ya estaba tapado, y el de los
    documentos adjuntos se tapó el 2026-08-29 (`_doc_de_parte`). Pero al prompt se entra
    por más de una puerta: un RESULTADO DE TOOL llega como string y se pega tal cual, y
    este render no le pone tope a nada. Una tool que devuelva un `data:…;base64,…` de un
    archivo deja el turno colgado en «working» exactamente igual, sin que ninguna de las
    dos correcciones anteriores se entere.

    Así que la guarda va en la salida, que es la única que ve TODO lo que se va a mandar.
    No se trunca en silencio: se dice qué había y cuánto pesaba.

    Args:
        texto: El texto ya armado de un mensaje.

    Returns:
        El mismo texto con los blobs grandes reemplazados por su ficha.
    """
    def _ficha(m):
        kb = (len(m.group(2)) * 3) // 4096
        return f"[dato en base64 omitido: {m.group(1)}, ~{kb} KB]"
    return _BASE64_INCRUSTADO.sub(_ficha, texto)


def _texto_de(content, imgs: list) -> str:
    """El contenido de UN mensaje → texto para el prompt, apilando sus imágenes en `imgs`.

    `imgs` es el acumulador del render ENTERO: la numeración de las marcas es la posición
    en esa lista, así que la marca `⟦imagen 3⟧` y la tercera imagen que se manda son la
    misma, sin que nadie tenga que volver a recorrer los mensajes para saberlo.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return _sin_base64_gigante(content)
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    trozos = []
    for parte in content:
        if isinstance(parte, str):
            trozos.append(parte)
            continue
        if not isinstance(parte, dict):
            trozos.append(str(parte))
            continue
        img = _img_de_parte(parte)
        if img is not None:
            imgs.append(img)
            trozos.append(_MARCA_IMG.format(n=len(imgs)))
            continue
        url = _url_de_parte(parte)
        if url:
            trozos.append(f"[imagen por URL, no adjunta: {url}]")
            continue
        doc = _doc_de_parte(parte)
        if doc is not None:
            if doc["media_type"] == _DOC_LEGIBLE:
                # MISMO ACUMULADOR QUE LAS IMÁGENES, a propósito: la invariante de este
                # render es «el número de la marca ES la posición en la lista», y dos
                # listas paralelas la romperían. `clase` le dice a `build_stdin` qué
                # bloque emitir.
                imgs.append({**doc, "clase": "document"})
                trozos.append(_MARCA_DOC.format(n=len(imgs), nombre=doc["nombre"]))
            else:
                # ── SE LE SACA EL TEXTO, QUE ES LO QUE EL MODELO NECESITA ──────────────
                # Antes acá se decía «no legible» y se terminaba. Era honesto y era poco:
                # el modelo NO puede recibir un .docx, pero SÍ puede leer su contenido. Los
                # tres formatos de oficina son un ZIP con XML adentro y eso lo abre la
                # biblioteca estándar, sin sumarle una dependencia al pack.
                # MEDIDO contra un documento real del dueño: 44.780 bytes de .docx → 12.860
                # caracteres de texto, empezando por su primera línea de verdad.
                import base64
                from cli_brain import documentos
                try:
                    crudo = base64.b64decode(doc["data"], validate=False)
                except Exception:  # noqa: BLE001 — un base64 roto es «no se pudo», no un crash
                    crudo = b""
                texto_doc, causa = documentos.texto_de(crudo, doc["media_type"], doc["nombre"])
                if texto_doc:
                    trozos.append(f"[documento adjunto: {doc['nombre']}]\n{texto_doc}\n"
                                  f"[fin de {doc['nombre']}]")
                else:
                    # Y si no se pudo, se dice POR QUÉ. Nunca el base64.
                    trozos.append(f"[adjunto no legible: {causa}]")
            continue
        tipo = str(parte.get("type") or "").strip()
        if tipo in ("text", "input_text", "output_text") or "text" in parte:
            trozos.append(str(parte.get("text") or ""))
        else:
            trozos.append(json.dumps(parte, ensure_ascii=False))
    return _sin_base64_gigante("".join(trozos))


def extraer_imagenes(messages: list) -> list:
    """SÓLO las imágenes inline de una conversación, en orden de aparición.

    Es el mismo recorrido que hace el render —de hecho lo hace: pedirle las imágenes a
    otra función sería abrir la puerta a que la marca `⟦imagen 2⟧` y la segunda imagen
    dejen de ser la misma."""
    return render_con_imagenes(messages, [], None)[1]


def render_prompt(messages: list, tools: list, tool_choice=None) -> str:
    """Mensajes OpenAI → prompt plano de pura cognición para el CLI (SÓLO el texto).

    Firma intacta a propósito: la usan las siete herramientas de medición del prompt
    (`analizar_prompt`, `analizar_resto`, `grabador_prompt`, las varas). Quien además
    necesite las imágenes llama a `render_con_imagenes`, que es esta misma función."""
    return render_con_imagenes(messages, tools, tool_choice)[0]


def render_con_imagenes(messages: list, tools: list, tool_choice=None) -> tuple:
    """(prompt, imágenes). UN solo recorrido: la marca y la imagen no se pueden separar."""
    sys_parts, convo, imgs = [], [], []
    id2name = {}
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            id2name[tc.get("id")] = (tc.get("function") or {}).get("name", "tool")
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            if content:
                sys_parts.append(_texto_de(content, imgs))
        elif role == "user":
            convo.append(f"[Usuario]: {_texto_de(content, imgs)}")
        elif role == "assistant":
            tcs = m.get("tool_calls") or []
            if tcs:
                for tc in tcs:
                    fn = tc.get("function") or {}
                    convo.append(f"[Tú llamaste]: <function={fn.get('name')}>{fn.get('arguments')}</function>")
            if content:
                convo.append(f"[Tú]: {_texto_de(content, imgs)}")
        elif role == "tool":
            # ⚠️ EL RESULTADO DE UNA TOOL TAMBIÉN TRAE IMÁGENES, y es el caso de la
            # verificación visual: el paso que saca la captura la devuelve acá, no en un
            # `[Usuario]`. Si esto no las mirara, el arreglo entero no serviría de nada.
            nm = id2name.get(m.get("tool_call_id"), m.get("name", "herramienta"))
            convo.append(f"[Resultado de {nm}]: {_texto_de(content, imgs)}")
    head = "\n".join(sys_parts) if sys_parts else "Eres un agente útil y honesto."
    body = "\n".join(convo)
    return ((f"{head}\n{_tools_block(tools, tool_choice)}\n\n=== CONVERSACIÓN ===\n{body}\n\n"
             f"Dá el PRÓXIMO PASO: {_cola_del_paso(tools, tool_choice)} "
             f"No repitas pasos ya hechos."), imgs)


def render_prompt_incremental(nuevos: list, tools: list, tool_choice=None) -> str:
    """La cola, SÓLO el texto. Ver `render_incremental_con_imagenes`."""
    return render_incremental_con_imagenes(nuevos, tools, tool_choice)[0]


def render_incremental_con_imagenes(nuevos: list, tools: list, tool_choice=None) -> tuple:
    """SÓLO lo que el CLI todavía no vio (Gate 2 · F2e). Éste es el ahorro entero.

    Con `--resume`, el CLI YA TIENE la conversación: mandarle otra vez los mensajes viejos
    es pagar dos veces por lo mismo, que es exactamente la brecha del §Q5. Acá va la cola
    —los mensajes posteriores al último turno— con el mismo formato que `render_prompt`
    para que el modelo no vea un cambio de estilo a mitad de la charla.

    El catálogo de TOOLS sí se re-manda: no es historia, es la instrucción vigente, y
    omitirlo dejaría al modelo sin saber qué puede llamar en este turno. Es chico al lado
    de lo que se ahorra.
    """
    convo, imgs = [], []
    id2name = {}
    for m in nuevos:
        for tc in (m.get("tool_calls") or []):
            id2name[tc.get("id")] = (tc.get("function") or {}).get("name", "tool")
    for m in nuevos:
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            # Un `system` nuevo a mitad de una conversación es una instrucción que cambió;
            # se manda como tal y no se descarta.
            if content:
                convo.append(f"[Instrucción]: {_texto_de(content, imgs)}")
        elif role == "user":
            convo.append(f"[Usuario]: {_texto_de(content, imgs)}")
        elif role == "assistant":
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                convo.append(f"[Tú llamaste]: <function={fn.get('name')}>{fn.get('arguments')}</function>")
            if content:
                convo.append(f"[Tú]: {_texto_de(content, imgs)}")
        elif role == "tool":
            nm = id2name.get(m.get("tool_call_id"), m.get("name", "herramienta"))
            convo.append(f"[Resultado de {nm}]: {_texto_de(content, imgs)}")
    body = "\n".join(convo)
    # ⚠️ LA NUMERACIÓN ES DE ESTE TURNO, y tiene que serlo: por `--resume` el CLI ya tiene
    # las imágenes viejas en su conversación, así que re-mandarlas sería pagarlas de nuevo.
    # La marca `⟦imagen 1⟧` de una cola nombra la primera imagen DE LA COLA, que es la
    # única que se adjunta en este spawn.
    return ((f"{_tools_block(tools, tool_choice)}\n\n=== SIGUE LA CONVERSACIÓN ===\n{body}\n\n"
             f"Dá el PRÓXIMO PASO: {_cola_del_paso(tools, tool_choice)} "
             f"No repitas pasos ya hechos."), imgs)


def _balanced_json(s: str) -> str:
    """Primer objeto/array JSON balanceado al inicio de `s` (tolera multilínea y strings
    con llaves). "" si no hay uno bien cerrado (fallback de un <function=> sin cierre)."""
    s = s.lstrip()
    if not s or s[0] not in "{[":
        return ""
    open_c, close_c = (("{", "}") if s[0] == "{" else ("[", "]"))
    depth = 0
    in_str = esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_c:
            depth += 1
        elif ch == close_c:
            depth -= 1
            if depth == 0:
                return s[:i + 1]
    return ""


def _mk_call(name: str, raw_args: str):
    name = (name or "").strip()
    raw_args = (raw_args or "").strip()
    if not name:
        return None
    if not raw_args:
        args_str = "{}"
    else:
        try:
            args_str = json.dumps(json.loads(raw_args), ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            return None
    return {"id": "call_" + uuid.uuid4().hex[:24], "type": "function",
            "function": {"name": name, "arguments": args_str}}


def extract_tool_calls(text: str) -> list:
    """<function=NOMBRE>{json}</function> del content → tool_calls OpenAI. Robusto:
    multilínea + varias llamadas; nada parsea → [] (texto). NUNCA tira."""
    try:
        text = text or ""
        calls = []
        for m in _FUNC_RE.finditer(text):
            c = _mk_call(m.group(1), m.group(2))
            if c:
                calls.append(c)
        if calls:
            return calls
        m = _FUNC_OPEN_RE.search(text)
        if m:
            raw = _balanced_json(text[m.end():])
            c = _mk_call(m.group(1), raw) if raw else None
            if c:
                return [c]
        return []
    except Exception:  # robustez dura: ante cualquier sorpresa, cae a texto
        return []


def marcador_ilegible(text: str, tools: list) -> Optional[str]:
    """El nombre de la tool que el modelo INTENTÓ llamar y no se pudo parsear. `None` si
    no hubo intento.

    POR QUÉ EXISTE, Y QUÉ SE VEÍA SIN ESTO. `extract_tool_calls` devuelve `[]` en dos
    casos que no son el mismo: el modelo escribió una respuesta final (bien), o el modelo
    escribió un marcador y el JSON de adentro no cerraba (mal). Río arriba los dos
    quedaban idénticos, y el segundo terminaba en `content: res.text` con
    `finish_reason: "stop"` — o sea que **el `<function=redline>{"docum…` crudo se le
    mostraba al usuario como si fuera la respuesta del abogado**. Ese es el «texto con
    código en crudo»: no es un problema de renderizado, es una llamada a herramienta
    fallida que se sirve como prosa.

    EL DISCRIMINANTE ES DE HECHOS, NO DE PARECIDO — y por eso pide las dos cosas:
      · que el marcador esté escrito con la sintaxis exacta que este puente documenta, y
      · que el NOMBRE sea una de las tools que este paso realmente declaró.

    Sin la segunda condición, un documento legal que citara la cadena `<function=…>`
    —cosa que un texto sobre este mismo sistema haría— se convertiría en un turno roto.
    Con ella, el falso positivo exige que el texto nombre una herramienta que existe en
    ESTE paso, con la sintaxis del marcador: es un residuo aceptable, y el costo del
    error inverso (código crudo en la cara del usuario) es mucho más caro.

    No mira `tool_choice`: la obligación es otra cosa y ya tiene su propio bloqueo. Acá
    da igual si la llamada era obligatoria — si el modelo la intentó, la intentó.
    """
    try:
        if not text or not tools:
            return None
        declaradas = set()
        for t in tools:
            if not isinstance(t, dict):
                continue
            fn = t.get("function") if isinstance(t.get("function"), dict) else t
            nombre = fn.get("name") if isinstance(fn, dict) else None
            if isinstance(nombre, str) and nombre:
                declaradas.add(nombre)
        if not declaradas:
            return None
        for m in _FUNC_OPEN_RE.finditer(text):
            if m.group(1) in declaradas:
                return m.group(1)
        return None
    except Exception:  # misma robustez dura que el extractor: ante la duda, no acusa
        return None
