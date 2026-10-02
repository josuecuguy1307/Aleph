/* cuarto.catalog.tools.js — transporte + routing PURO para las tools de catálogo del Guía.
 *
 * Son dos fuentes distintas y nunca se degradan una en la otra:
 *   · catálogo local = lo que la persona YA TIENE disponible en Aleph.
 *   · registro público = lo que PODRÍA TRAER; buscar es sólo lectura. La ingesta ocurre
 *     después, al traer/confirmar por el carril de equipamiento existente.
 *
 * Este módulo no pinta UI ni conoce Pixi. La búsqueda devuelve el envelope de lectura intacto.
 */

export const CLEAN_CATALOG_KEYS = Object.freeze([
  "id", "nombre", "tipo", "descripcion_1linea", "official",
  "confianza", "checklist", "fuente", "manifest_crudo", "fecha_ingesta",
  "requisitos", "senales_matcher", "consecuencias",
]);

export const INGEST_STAGES = Object.freeze([
  "leyendo", "limpiando", "clasificando", "veredicto",
]);

const _fold = (value) => String(value == null ? "" : value)
  .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
  .toLowerCase().replace(/\s+/g, " ").trim();

const _LOCAL = [
  /\bmi catalogo\b/, /\bcatalogo local\b/,
  /\b(?:pone\w*|mostra\w*|lista\w*)\b.*\b(?:las?|los?|lo)\s+que (?:ya )?(?:tengo|tenemos|tenes)\b/,
  /\b(?:pone\w*|mostra\w*|lista\w*)\b.*\b(?:las mias|los mios)\b/,
  /\b(?:show|list|put)\b.*\b(?:the ones?|what) (?:i|we) already have\b/,
  /\b(?:my catalog|local catalog)\b/,
];
const _REGISTRY = [
  /\b(?:el )?registro(?: publico)?\b/, /\bpublic registry\b/,
  /\b(?:podria|podrias|podriamos|puedo|podemos) traer\b/,
  /\b(?:podes|puede|pueden) traer\b/, /\bbuscar (?:afuera|fuera)\b/,
  /\b(?:bring in|could bring|can bring|from the registry)\b/,
];
const _CATALOG_REQUEST = [
  /\b(?:busca\w*|mostra\w*|pone\w*|trae\w*|consegui\w*|lista\w*|que hay|cuales)\b.*\b(?:catalogo|registro|mcp|mcps|conector|conectores|pieza|piezas)\b/,
  /\b(?:catalogo|registro|mcp|mcps|conector|conectores|pieza|piezas)\b.*\b(?:busca\w*|mostra\w*|pone\w*|trae\w*|consegui\w*|lista\w*|que hay|cuales)\b/,
  /\b(?:search|show|find|list|bring)\b.*\b(?:catalog|registry|connector|connectors|pieces?)\b/,
  /\b(?:catalog|registry|connector|connectors|pieces?)\b.*\b(?:search|show|find|list|bring)\b/,
];

function _some(patterns, text) {
  return patterns.some((re) => re.test(text));
}

/**
 * Decide únicamente la FUENTE. `null` significa que el turno no es un pedido de catálogo.
 * Si aparecen señales de ambos carriles, no se adivina.
 */
export function routeCatalogIntent(text) {
  const q = _fold(text);
  if (!q) return null;
  // Una pregunta factual sobre qué ES la fuente sigue siendo una explicación del Guía,
  // no una orden de buscar.
  if (/\b(?:que es|como funciona|what is|how does)\b/.test(q)
      && !/\b(?:busca\w*|mostra\w*|search|show|find)\b/.test(q)) return null;
  const local = _some(_LOCAL, q);
  const registry = _some(_REGISTRY, q);
  if (local && registry) return "ambiguous";
  if (local) return "local";
  if (registry) return "registry";
  if (_some(_CATALOG_REQUEST, q)) return "ambiguous";
  // Un sustantivo catalogal aislado sigue siendo una duda de fuente. En cambio,
  // frases generales como «lo que tenemos que hacer» no entran a este router.
  return /^(?:el |mi |the )?(?:catalogo|registro|conectores?|mcps?|registry|catalog|connectors?)$/.test(q)
    ? "ambiguous" : null;
}

/**
 * Extrae sólo el tema si el pedido lo trae ("de finanzas", "para research").
 * Un pedido genérico al catálogo local usa q vacío: significa listar todo lo disponible.
 */
export function catalogQueryFromRequest(text, route) {
  const raw = String(text == null ? "" : text).trim();
  const match = raw.match(/\b(?:de|para|sobre|for|about)\s+(.+?)(?:[?.!]|$)/i);
  if (match && match[1]) return match[1].trim();
  if (route === "registry") {
    const cleaned = _fold(raw)
      .replace(/\b(?:busca|buscar|buscame|mostra|muestra|mostrar|mostrame|poneme|trae|conseguime|bring|search|show)\b/g, " ")
      .replace(/\b(?:en|del?|the|el|la|los|las|registro|publico|public|registry|catalogo|catalog)\b/g, " ")
      .replace(/\b(?:que|podria|podrias|podriamos|puedo|podemos|podes|puede|traer|could|can)\b/g, " ")
      .replace(/^[\s:·—-]+/, "").replace(/\s+/g, " ").trim();
    return cleaned || "mcp";
  }
  return "";
}

function _cleanEntry(raw) {
  if (!raw || typeof raw !== "object") return null;
  const out = {};
  for (const key of CLEAN_CATALOG_KEYS) out[key] = raw[key];
  const bilingualText = out.descripcion_1linea && typeof out.descripcion_1linea === "object"
    && !Array.isArray(out.descripcion_1linea)
    && Object.keys(out.descripcion_1linea).sort().join(",") === "en,es"
    && ["es", "en"].every((lang) => typeof out.descripcion_1linea[lang] === "string"
      && out.descripcion_1linea[lang].trim() && !/[\r\n]/.test(out.descripcion_1linea[lang]));
  const checklistOk = out.checklist && typeof out.checklist === "object"
    && !Array.isArray(out.checklist)
    && Object.keys(out.checklist).sort().join(",") === "en,es"
    && ["es", "en"].every((lang) => Array.isArray(out.checklist[lang])
      && out.checklist[lang].every((step) => typeof step === "string" && step.trim()));
  if (typeof out.id !== "string" || !out.id.trim()
      || typeof out.nombre !== "string" || !out.nombre.trim()
      || !["remoto", "paquete", "hibrido"].includes(out.tipo)
      || typeof out.fuente !== "string" || !out.fuente.trim()
      || typeof out.official !== "boolean"
      || typeof out.confianza !== "number" || !Number.isFinite(out.confianza)
      || out.confianza < 0 || out.confianza > 1
      || !bilingualText || !checklistOk) return null;
  return out;
}

function _entries(payload) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const key of ["items", "entradas", "entries", "aceptadas", "catalogo"]) {
    if (Array.isArray(payload[key])) return payload[key];
  }
  return [];
}

function _cleanEntries(payload) {
  return _entries(payload).map(_cleanEntry).filter(Boolean);
}

export async function buscarCatalogoLocal(query = "", opts = {}) {
  const fetchImpl = opts.fetchImpl || globalThis.fetch;
  const q = String(query == null ? "" : query).trim();
  const response = await fetchImpl(`/v1/catalog/local?q=${encodeURIComponent(q)}`, {
    method: "GET", headers: { "Accept": "application/json" },
  });
  let payload = null;
  try { payload = await response.json(); } catch { payload = null; }
  if (!response.ok) {
    return { ok: false, fuente: "catalogo_local", status: response.status,
      causa: (payload && (payload.causa || payload.error || payload.detail)) || `HTTP ${response.status}`,
      items: [] };
  }
  const items = _cleanEntries(payload);
  return {
    ok: true, fuente: "catalogo_local", query: q, items,
    total: Number(payload && payload.total) || items.length,
  };
}

function _parseSseFrame(frame) {
  let event = "", data = "";
  for (const line of String(frame || "").split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += (data ? "\n" : "") + line.slice(5).trim();
  }
  if (!data) return null;
  let parsed;
  try { parsed = JSON.parse(data); } catch { parsed = { detalle: data }; }
  if (!parsed || typeof parsed !== "object") parsed = { valor: parsed };
  if (!parsed.type && event) parsed.type = event;
  return parsed;
}

function _stageOf(event) {
  const raw = _fold(event && (event.etapa || event.stage || event.type));
  return INGEST_STAGES.find((stage) => raw === stage || raw.endsWith("." + stage)) || null;
}

async function _consumeSse(response, onEvent, onStage) {
  const events = [];
  const stages = [];
  const drive = (event) => {
    if (!event) return;
    events.push(event);
    onEvent(event);
    const stage = _stageOf(event);
    if (stage) {
      stages.push(stage);
      onStage(stage, event);
    }
  };
  if (!response.body || typeof response.body.getReader !== "function") return { events, stages };
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let match;
    while ((match = buffer.match(/\r?\n\r?\n/))) {
      const index = match.index;
      drive(_parseSseFrame(buffer.slice(0, index)));
      buffer = buffer.slice(index + match[0].length);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) drive(_parseSseFrame(buffer));
  return { events, stages };
}

export async function buscarRegistro(query, opts = {}) {
  const fetchImpl = opts.fetchImpl || globalThis.fetch;
  const q = String(query == null ? "" : query).trim();
  if (!q) return { ok: false, fuente: "registro", causa: "falta qué buscar", items: [], events: [], etapas: [] };

  let response;
  try {
    response = await fetchImpl(`/v1/catalog/search?q=${encodeURIComponent(q)}&source=registry`, {
      method: "GET", headers: { "Accept": "application/json" },
    });
  } catch (error) {
    return { ok: false, fuente: "registro", causa: String((error && error.message) || error),
      items: [], events: [], etapas: [] };
  }
  if (!response.ok) {
    let payload = null;
    try { payload = await response.json(); } catch {}
    return { ok: false, fuente: "registro", status: response.status,
      causa: (payload && (payload.causa || payload.error || payload.detail)) || `HTTP ${response.status}`,
      items: [], events: [], etapas: [] };
  }

  let payload = null;
  try { payload = await response.json(); } catch {}
  const items = payload && Array.isArray(payload.items) ? payload.items : [];
  return {
    ok: true, fuente: "registro", query: q, items, solo_lectura: true,
    agregadas_al_local: 0, events: [], etapas: [],
    registry_status: payload && payload.registry_status,
    notice: payload && payload.notice,
    nota: "Buscar sólo consulta; traer o confirmar una pieza inicia la ingesta.",
  };
}
