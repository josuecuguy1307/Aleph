"""vocabulary.py — THE one artifact-type vocabulary. [Gate 4 · Fase 2 · §2 del contrato]

Before this module the repo had FOUR diverging type lists (censo §C.3, measured):
`render/render.js:37` (11) · `sala/render.js:431` (16) · `stream_chat._ARTIFACT_TYPES`
(7 — the only one the model ever saw) · `executor._capture_rich_obra` (10 file
suffixes) — plus a free-string sink in `artifact_store.create_artifact`. A type
added to one list and not the others degraded silently to `informe` by two
different fallbacks. All four die into THIS table; consumers get wired in 2.4.

WHY A PYTHON LITERAL AND NOT A JSON DATA FILE: a data file read by path is the #1
frozen-bundle killer (deploy/fase4/bundle_datos.py:48-62 — «un import exitoso no
dice nada de si el archivo está»; four layers, one build each). A module travels
by import cascade and cannot be lost by the .spec. The future `/v1/artifacts/types`
endpoint serves `as_json()` to the JS consumers — still ONE source.

VALUES STAY IN SPANISH (contract §2.3, sealed by persona usuaria 2026-08-08): they are
persisted on disk and travel in `recipe.meta.output_type` of real recipes;
renaming them is a migration of everything persisted for zero user value.
Field names and code are English (ley 11).

GOVERNS vs ADVISORY (ley técnica 7 — a governing field with no consumer wired in
the same commit does not enter as governing). 2.3 wired the last three, so as of
this commit NOTHING here is advisory: every field has a consumer that obeys it.
  - the type union + ALIASES ......... GOVERN the store's write border (2.2)
  - `formats` ........................ GOVERNS artifact_export (2.2) — exact
                                       mirror of artifact_export.py:34-42 + its
                                       ["md"] default: zero behavior change,
                                       one source instead of a fifth list
  - `producible_by_llm` .............. GOVERNS (2.3) the set the classifier may
                                       offer the model: stream_chat._ARTIFACT_TYPES
                                       and the type menu of its system prompt are
                                       DERIVED from it — the literal list of 7 died
  - `rich_capture` ................... GOVERNS (2.3) which types the executor
                                       scans for in the workdir
                                       (`_capture_rich_obra`) and which ones the
                                       Sala's RICH_SHAPES must validate
  - `label_es` ....................... GOVERNS (2.3) the fallback name of a type
                                       in the classifier's menu — a type added
                                       here reaches the model even with no prose
                                       written for it (nothing drops in silence)

WHY producible_by_llm STAYS FALSE FOR THE RICH TYPES (the census asked): a `cad`
or a `dicom` is the capture of a file a REAL tool wrote (executor), never prose a
model can type. Offering them in the classifier's menu would ask the model to
fabricate a mesh — fake-live, the exact thing the anti-grift exists to catch. The
win of 2.3 is that the answer now lives in ONE flag in ONE file instead of four
lists; flipping one is a product decision with a wired consumer, not an edit in
four places that silently disagree.
"""
from __future__ import annotations

SCHEMA_VERSION = "1"

#: Fields that do not govern anything yet. EMPTY since 2.3: `producible_by_llm`,
#: `rich_capture` and `label_es` got their consumers wired in the same commit that
#: took them out of here (ley técnica 7 read in both directions — a field that
#: governs must be wired, and a wired field must stop calling itself advisory).
ADVISORY_FIELDS: tuple[str, ...] = ()

#: The 17 canonical types — the real union of what circulates today, collapsed
#: by alias (contract §2.2). `codigo` is canonical because it is produced by the
#: Sala's isCodeDominant heuristic and persisted (sala.html:2146-2160). `3d` and
#: `cad` are TWO types (different content shapes: model-written three.js scene
#: vs FreeCAD mesh JSON). `diagrama` is NOT a type — both surfaces delegate it
#: to `schematic`, so it lives in ALIASES.
#:
#: [Convergencia · superficie 7] `presentacion` ENTRA porque el censo midió un hueco
#: con productor y con máquina, no una intuición: Oficina clasifica todo `.pptx` como
#: `presentation` (`platform/workspaces/plugins/openwork.js:131`) y Diseño tiene un
#: exportador de pptx con test al lado
#: (`third_party/codesign/packages/exporters/src/pptx.ts`). Antes de esta línea los 16
#: tipos conocían SIETE formatos entre todos —csv docx html md pdf png xlsx— y `pptx`
#: no era ninguno: un deck no tenía sustantivo en la casa, y todo lo que Oficina
#: produce rebotaba con `workspace_kind_unknown`.
#:
#: `zip` NO entra, y la diferencia importa: es un ENVASE de salida, no el formato de un
#: tipo. El único productor de zips es el `archive` de Ciencia, que el puente ya
#: resuelve a ficha honesta a propósito, y el `zip.ts` de Diseño empaqueta HTML+assets,
#: que es otro eje. Declararlo obligaría a inventar qué significa «bajar este informe
#: como zip» — exactamente lo que este archivo existe para que no pase. Vive en la
#: convergencia de exportadores.
TYPES: dict[str, dict] = {
    # ⚠️ EL PRIMER FORMATO ES EL DEFAULT DE LA DESCARGA, y para estos dos era `md`.
    # MEDIDO contra la .app instalada: el usuario veía en pantalla un informe con tabla y
    # gráfico, apretaba Download, y bajaba el MARKDOWN FUENTE — con el bloque ```chart como
    # texto plano. Abría el archivo y no encontraba nada de lo que había visto.
    # El `.md` sigue disponible (es la fuente, y sirve), pero deja de ser lo que baja por
    # defecto: lo que se ofrece primero es el formato que una persona espera abrir.
    # EL ORDEN ES LA DECISIÓN, y `html` va primero POR EL GRÁFICO. Es el único de los tres
    # que conserva el chart DIBUJADO (SVG inline, sin CDN — se abre sin internet); el pdf y
    # el docx sólo pueden conservar sus NÚMEROS, como tabla. El pdf queda segundo para quien
    # quiera imprimir, y el md sigue disponible como fuente.
    "informe":     {"formats": ["html", "pdf", "md", "docx"], "producible_by_llm": True,  "rich_capture": False, "label_es": "informe"},
    "documento":   {"formats": ["html", "pdf", "md", "docx"], "producible_by_llm": True,  "rich_capture": False, "label_es": "documento"},
    # `producible_by_llm` TRUE, y la primera versión de esta línea lo tuvo en False por un
    # razonamiento equivocado que conviene dejar escrito: «un modelo no tipea un .pptx».
    # Cierto, y ES IRRELEVANTE — el `content` de este tipo NO es un .pptx, es MARKDOWN, y
    # `artifact_export._gen_pptx` lo vuelve slides al bajarlo (un encabezado = un slide).
    # Escribir `# Propuesta` + viñetas es exactamente lo que un modelo hace bien. Es el
    # mismo caso que `dashboard`, cuyo contenido son ```chart en markdown y es producible.
    # Y es lo que un profesional no técnico pide con todas las letras: «armame una
    # presentación de esto».
    #
    # El binario es OTRA COSA y por eso no colisionan: un `.pptx` que llega de un stack
    # cruza el puente como FICHA, jamás como este tipo (`bridge.py`, fila oficina/
    # presentation). Un tipo cuyo contenido es markdown y un archivo de bytes ya hechos no
    # son el mismo artefacto aunque se bajen con la misma extensión.
    #
    # `rich_capture` FALSE porque el executor escanea `*.<tipo>.json` en el workdir, y un
    # markdown de slides no es eso: lo escribe el modelo en el hilo, no una tool en disco.
    "presentacion": {"formats": ["pptx", "md"],       "producible_by_llm": True,  "rich_capture": False, "label_es": "presentación"},
    "planilla":    {"formats": ["xlsx", "csv"],       "producible_by_llm": True,  "rich_capture": True,  "label_es": "planilla"},
    "dashboard":   {"formats": ["html", "csv"],       "producible_by_llm": True,  "rich_capture": False, "label_es": "tablero"},
    "web":         {"formats": ["html"],              "producible_by_llm": True,  "rich_capture": False, "label_es": "página web"},
    "codigo":      {"formats": ["md"],                "producible_by_llm": False, "rich_capture": False, "label_es": "código"},
    "imagen":      {"formats": ["png"],               "producible_by_llm": True,  "rich_capture": True,  "label_es": "imagen"},
    "galeria":     {"formats": ["md"],                "producible_by_llm": False, "rich_capture": True,  "label_es": "galería"},
    "3d":          {"formats": ["html"],              "producible_by_llm": True,  "rich_capture": False, "label_es": "escena 3D"},
    "cad":         {"formats": ["md"],                "producible_by_llm": False, "rich_capture": True,  "label_es": "pieza CAD"},
    "schematic":   {"formats": ["md"],                "producible_by_llm": False, "rich_capture": True,  "label_es": "esquemático"},
    "dicom":       {"formats": ["md"],                "producible_by_llm": False, "rich_capture": True,  "label_es": "estudio médico"},
    "fieldplot":   {"formats": ["md"],                "producible_by_llm": False, "rich_capture": True,  "label_es": "mapa de campo"},
    "convergence": {"formats": ["md"],                "producible_by_llm": False, "rich_capture": True,  "label_es": "convergencia"},
    "volume3d":    {"formats": ["md"],                "producible_by_llm": False, "rich_capture": True,  "label_es": "volumen 3D"},
    "linechart":   {"formats": ["md"],                "producible_by_llm": False, "rich_capture": True,  "label_es": "serie temporal"},
}

#: Read-side + write-border normalization. NEVER a second list: an alias maps to
#: exactly one canonical type. NOTE `dashboard→informe` and `3d→cad` from
#: render/render.js:40-58 are RENDER delegations, not identity aliases — both
#: sides are canonical here and deliberately absent from this map.
#: `grafico`/`lista` (artifact_store.py's old docstring) have no unambiguous
#: destination — inventing one would be guessing; unknown legacy strings are
#: preserved as-is at read (contract §5.3).
ALIASES: dict[str, str] = {
    "doc": "documento", "document": "documento",
    "markdown": "informe", "md": "informe",
    "table": "planilla", "spreadsheet": "planilla", "tabla": "planilla",
    "serie": "linechart", "timeseries": "linechart",
    "html": "web",
    "mesh": "cad",
    "svg": "schematic", "diagrama": "schematic", "diagram": "schematic",
    "heatmap": "fieldplot", "field": "fieldplot",
    # [Convergencia · superficie 7] `presentation` es EXACTAMENTE la palabra que emite
    # `claseDe()` de Oficina; `pptx` y `deck` son las otras dos con las que un stack
    # nombra lo mismo. Van acá y no en LLM_ALIASES porque son identidad de dato
    # persistible, no una palabra que un modelo escribió en un JSON.
    "presentation": "presentacion", "pptx": "presentacion", "deck": "presentacion",
}

#: Conveniencia para quien necesita el conjunto (el rechazo tipado del almacén lo
#: sirve como `allowed`). Es una FOTO de `TYPES` al importar: la verdad es `TYPES`,
#: y por eso `normalize()` consulta el dict y no esta foto — una copia que decide
#: es una copia que puede quedar vieja (2.3 lo midió: la vara agregó un tipo y el
#: clasificador no lo veía porque la foto no se había sacado de nuevo).
CANONICAL: frozenset = frozenset(TYPES)

#: [2.3] The colloquial words the MODEL writes when it names a type — classifier
#: INPUT normalization, deliberately NOT artifact identity, and deliberately not
#: merged into ALIASES:
#:   · ALIASES governs the STORE's write border — an artifact may be persisted
#:     under an alias, so every entry there is a promise about stored data.
#:   · these only clean up a word inside a JSON field an LLM just wrote. Nothing
#:     is ever persisted under them: the classifier resolves to a canonical type
#:     before anything is created.
#: `grafico → dashboard` lives HERE and not in ALIASES on purpose: contract §2.2
#: declined it as an identity alias («inventarle destino sería adivinar»), and
#: that stands for stored data. As classifier input it is not invented — it is
#: what stream_chat._coerce_type has answered in production since ticket 37, and
#: 2.3 moved it here rather than leaving a fifth list in the consumer.
LLM_ALIASES: dict[str, str] = {
    "three": "3d", "threejs": "3d", "three.js": "3d", "escena": "3d", "modelo3d": "3d",
    "grafico": "dashboard", "gráfico": "dashboard", "graficos": "dashboard",
    "charts": "dashboard", "chart": "dashboard", "viz": "dashboard",
    "visualizacion": "dashboard", "visualización": "dashboard",
    "hoja": "planilla", "excel": "planilla", "presupuesto": "planilla",
    "pagina": "web", "página": "web", "sitio": "web", "site": "web",
    "landing": "web", "webpage": "web",
    "carta": "documento", "memo": "documento", "correo": "documento",
    "email": "documento", "contrato": "documento",
    "image": "imagen", "ilustracion": "imagen", "ilustración": "imagen", "foto": "imagen",
    # [Convergencia · superficie 7] Las palabras con las que un modelo nombra un deck
    # cuando el usuario le pidió «armame una presentación». `presentacion` NO va acá —es
    # el nombre canónico y el assert de abajo prohíbe taparlo—; van las coloquiales.
    "slides": "presentacion", "diapositivas": "presentacion", "presentación": "presentacion",
    "powerpoint": "presentacion", "keynote": "presentacion",
}

# An alias that shadows a canonical name would make normalize() ambiguous.
assert not (set(ALIASES) & CANONICAL), "alias shadows a canonical type"
assert set(ALIASES.values()) <= CANONICAL, "alias points outside the union"
# The classifier map may not shadow a canonical name either, and it may only
# point at types the model is actually allowed to produce — a colloquial word
# resolving to something the classifier cannot offer would be a dead end.
assert not (set(LLM_ALIASES) & CANONICAL), "classifier alias shadows a canonical type"
assert all(TYPES[v]["producible_by_llm"] for v in LLM_ALIASES.values()), \
    "classifier alias points at a type the model may not produce"

_DEFAULT_FORMATS = ["md"]


def normalize(type_: str | None) -> str | None:
    """Canonical name for `type_` (alias-resolved, case/space-insensitive), or
    None if it is outside the union. None is a VERDICT, not a fallback — the
    write border rejects it visibly; readers keep the original string as-is."""
    t = (type_ or "").strip().lower()
    if not t:
        return None
    if t in TYPES:                       # el dict ES la verdad (ver CANONICAL)
        return t
    return ALIASES.get(t)


def is_valid(type_: str | None) -> bool:
    return normalize(type_) is not None


def formats_for(type_: str | None) -> list[str]:
    """Export formats for a type — first one is the default. Unknown/legacy
    types fall to ["md"], byte-identical to artifact_export's old behavior."""
    t = normalize(type_)
    if t is None:
        return list(_DEFAULT_FORMATS)
    return list(TYPES[t]["formats"])


def default_format(type_: str | None) -> str:
    return formats_for(type_)[0]


def producible_by_llm() -> tuple[str, ...]:
    """GOVERNS (2.3): the subset the classifier may offer the model.
    stream_chat._ARTIFACT_TYPES and its prompt menu derive from this.

    DECLARATION order, not alphabetical: the menu is read by a model and the
    first entries carry weight (the prompt's own tie-break is «ante la duda,
    informe» — which is where TYPES starts). Sorting it would put `3d` first for
    no reason but the alphabet."""
    return tuple(t for t, d in TYPES.items() if d["producible_by_llm"])


def rich_capture_types() -> tuple[str, ...]:
    """GOVERNS (2.3): the types the executor scans for in the run's workdir
    (`*.<type>.json`) and the ones the Sala's RICH_SHAPES must be able to
    validate. Declaration order; the executor declares its own scan PRIORITY
    (convergence first) and appends anything this set adds — a type added here
    can never fall out of the scan in silence."""
    return tuple(t for t, d in TYPES.items() if d["rich_capture"])


def normalize_from_llm(type_: str | None) -> str | None:
    """[2.3] Canonical type for what the MODEL answered, restricted to the
    producible subset. Two layers in order: LLM_ALIASES (colloquial) then THE
    alias table. Outside the producible subset → None, a VERDICT the caller
    turns into its documented default («ante la duda, informe») — never a silent
    coercion into a type nobody asked for."""
    t = (type_ or "").strip().lower()
    if not t:
        return None
    c = normalize(LLM_ALIASES.get(t, t))
    if c is None:
        return None
    return c if TYPES[c]["producible_by_llm"] else None


def as_json() -> dict:
    """The whole vocabulary as one JSON-able dict. Two consumers, one payload:
    the `/v1/artifacts/types` endpoint (router) and the generator that writes the
    JS mirror the two render registries read (`gen_vocabulary_js.py`). A vara
    asserts the served payload and the generated file agree — a mirror nobody
    checks is a fifth list with extra steps."""
    return {
        "schema_version": SCHEMA_VERSION,
        "advisory_fields": list(ADVISORY_FIELDS),
        "types": {t: dict(d) for t, d in TYPES.items()},
        "aliases": dict(ALIASES),
        "llm_aliases": dict(LLM_ALIASES),
    }


__all__ = [
    "SCHEMA_VERSION", "ADVISORY_FIELDS", "TYPES", "ALIASES", "LLM_ALIASES",
    "CANONICAL", "normalize", "normalize_from_llm", "is_valid", "formats_for",
    "default_format", "producible_by_llm", "rich_capture_types", "as_json",
]
