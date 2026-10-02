/* ============================================================================
 * vocabulary.js — EL vocabulario de tipos de artefacto, del lado del navegador.
 *
 *   ARCHIVO GENERADO — NO SE EDITA A MANO.
 *   Fuente:      platform/artifacts/vocabulary.py
 *   Se regenera: python3 platform/artifacts/gen_vocabulary_js.py
 *   La vara `qa/verify_vocabulario_cableado.py` FALLA si este archivo drifteó de
 *   su fuente: un espejo que nadie chequea es una quinta lista con pasos extra.
 *
 * Lo consumen los DOS registros de render (render/render.js por import, y
 * render/sala-render.js por `window.AlephVocabulary`), que antes tenían cada uno su
 * propia lista de tipos y su propio mapa de alias — 11 y 16, con `doc` canónico
 * de un lado y `documento` del otro (censo §C.3).
 *
 * `normalize()` es la MISMA función que el borde de escritura del almacén: alias
 * → canónico, minúsculas, sin espacios; fuera de la unión → null (un VEREDICTO,
 * no un fallback: quien llama decide qué hacer con el null, a la vista).
 * ========================================================================== */

export const SCHEMA_VERSION = "1";

export const ADVISORY_FIELDS = [];

export const TYPES = {
  "informe": {
    "formats": [
      "html",
      "pdf",
      "md",
      "docx"
    ],
    "producible_by_llm": true,
    "rich_capture": false,
    "label_es": "informe"
  },
  "documento": {
    "formats": [
      "html",
      "pdf",
      "md",
      "docx"
    ],
    "producible_by_llm": true,
    "rich_capture": false,
    "label_es": "documento"
  },
  "presentacion": {
    "formats": [
      "pptx",
      "md"
    ],
    "producible_by_llm": true,
    "rich_capture": false,
    "label_es": "presentación"
  },
  "planilla": {
    "formats": [
      "xlsx",
      "csv"
    ],
    "producible_by_llm": true,
    "rich_capture": true,
    "label_es": "planilla"
  },
  "dashboard": {
    "formats": [
      "html",
      "csv"
    ],
    "producible_by_llm": true,
    "rich_capture": false,
    "label_es": "tablero"
  },
  "web": {
    "formats": [
      "html"
    ],
    "producible_by_llm": true,
    "rich_capture": false,
    "label_es": "página web"
  },
  "codigo": {
    "formats": [
      "md"
    ],
    "producible_by_llm": false,
    "rich_capture": false,
    "label_es": "código"
  },
  "imagen": {
    "formats": [
      "png"
    ],
    "producible_by_llm": true,
    "rich_capture": true,
    "label_es": "imagen"
  },
  "galeria": {
    "formats": [
      "md"
    ],
    "producible_by_llm": false,
    "rich_capture": true,
    "label_es": "galería"
  },
  "3d": {
    "formats": [
      "html"
    ],
    "producible_by_llm": true,
    "rich_capture": false,
    "label_es": "escena 3D"
  },
  "cad": {
    "formats": [
      "md"
    ],
    "producible_by_llm": false,
    "rich_capture": true,
    "label_es": "pieza CAD"
  },
  "schematic": {
    "formats": [
      "md"
    ],
    "producible_by_llm": false,
    "rich_capture": true,
    "label_es": "esquemático"
  },
  "dicom": {
    "formats": [
      "md"
    ],
    "producible_by_llm": false,
    "rich_capture": true,
    "label_es": "estudio médico"
  },
  "fieldplot": {
    "formats": [
      "md"
    ],
    "producible_by_llm": false,
    "rich_capture": true,
    "label_es": "mapa de campo"
  },
  "convergence": {
    "formats": [
      "md"
    ],
    "producible_by_llm": false,
    "rich_capture": true,
    "label_es": "convergencia"
  },
  "volume3d": {
    "formats": [
      "md"
    ],
    "producible_by_llm": false,
    "rich_capture": true,
    "label_es": "volumen 3D"
  },
  "linechart": {
    "formats": [
      "md"
    ],
    "producible_by_llm": false,
    "rich_capture": true,
    "label_es": "serie temporal"
  }
};

export const ALIASES = {
  "doc": "documento",
  "document": "documento",
  "markdown": "informe",
  "md": "informe",
  "table": "planilla",
  "spreadsheet": "planilla",
  "tabla": "planilla",
  "serie": "linechart",
  "timeseries": "linechart",
  "html": "web",
  "mesh": "cad",
  "svg": "schematic",
  "diagrama": "schematic",
  "diagram": "schematic",
  "heatmap": "fieldplot",
  "field": "fieldplot",
  "presentation": "presentacion",
  "pptx": "presentacion",
  "deck": "presentacion"
};

export const LLM_ALIASES = {
  "three": "3d",
  "threejs": "3d",
  "three.js": "3d",
  "escena": "3d",
  "modelo3d": "3d",
  "grafico": "dashboard",
  "gráfico": "dashboard",
  "graficos": "dashboard",
  "charts": "dashboard",
  "chart": "dashboard",
  "viz": "dashboard",
  "visualizacion": "dashboard",
  "visualización": "dashboard",
  "hoja": "planilla",
  "excel": "planilla",
  "presupuesto": "planilla",
  "pagina": "web",
  "página": "web",
  "sitio": "web",
  "site": "web",
  "landing": "web",
  "webpage": "web",
  "carta": "documento",
  "memo": "documento",
  "correo": "documento",
  "email": "documento",
  "contrato": "documento",
  "image": "imagen",
  "ilustracion": "imagen",
  "ilustración": "imagen",
  "foto": "imagen",
  "slides": "presentacion",
  "diapositivas": "presentacion",
  "presentación": "presentacion",
  "powerpoint": "presentacion",
  "keynote": "presentacion"
};

export const CANONICAL = Object.keys(TYPES);

/** Nombre canónico de `t` (alias resuelto), o null si está fuera de la unión. */
export function normalize(t) {
  const s = String(t == null ? "" : t).trim().toLowerCase();
  if (!s) return null;
  if (Object.prototype.hasOwnProperty.call(TYPES, s)) return s;
  return Object.prototype.hasOwnProperty.call(ALIASES, s) ? ALIASES[s] : null;
}

export function isValid(t) { return normalize(t) !== null; }

/** Los tipos con una bandera prendida, en orden de declaración. */
function withFlag(flag) { return CANONICAL.filter((t) => TYPES[t][flag]); }

/** Los que el clasificador puede ofrecerle al modelo (gobierna stream_chat). */
export function producibleByLlm() { return withFlag("producible_by_llm"); }

/** Los que el executor captura del workdir y la Sala valida en RICH_SHAPES. */
export function richCapture() { return withFlag("rich_capture"); }

export function isRich(t) {
  const c = normalize(t);
  return c !== null && !!TYPES[c].rich_capture;
}

export function formatsFor(t) {
  const c = normalize(t);
  return c === null ? ["md"] : TYPES[c].formats.slice();
}

export function labelEs(t) {
  const c = normalize(t);
  return c === null ? String(t == null ? "" : t) : TYPES[c].label_es;
}

/* Global además de ESM: `render/sala-render.js` es un script clásico (IIFE) y no puede
 * importar. Se expone al cargarse este módulo — que es lo que hace render.js al
 * importarlo. Una superficie que cargue SalaRender sin AlephRender no tiene
 * vocabulario y degrada declarándolo (ver `render/sala-render.js`), jamás en silencio. */
const API = {
  SCHEMA_VERSION, TYPES, ALIASES, LLM_ALIASES, ADVISORY_FIELDS, CANONICAL,
  normalize, isValid, isRich, producibleByLlm, richCapture, formatsFor, labelEs,
};
if (typeof window !== "undefined") window.AlephVocabulary = API;

export default API;
