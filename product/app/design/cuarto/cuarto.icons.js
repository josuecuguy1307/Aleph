/* cuarto.icons.js — el ÍCONO DE DOMINIO de cada TOOL del Cuarto (Aleph).
 *
 * CONTRATO, no render. Este módulo NO dibuja nada: traduce el dato de una pieza
 * (el átomo / `n.data` del diorama) a UN NOMBRE de glifo Lucide. El dibujo real (montar
 * el path SVG de Lucide como 3er hijo de makeToolPiece) es el paso de integración que
 * vive en cuarto.render.js — ver PLAN-ICONOS.md. Por eso este archivo es PURO,
 * sin estado, sin PIXI, testeable solo en Node (verify_icons.mjs).
 *
 * TESIS · UNIVERSALIDAD: cualquier MCP que entre —conocido o no— recibe un ícono
 * COHERENTE. Nunca un cubo/llave anónima sin sentido. El conocido cae determinístico;
 * el desconocido cae a un default ("puzzle") y el flujo de forja ofrece la galería de
 * 2 niveles (GALLERY()). El sistema cubre el UNIVERSO de software, no solo los ~19
 * servers curados de hoy.
 *
 * CADENA DE RESOLUCIÓN (de más fuerte a default) — resolveIcon(toolData):
 *   (1) server conocido            → SERVER_ICON
 *   (2) connector conocido         → CONNECTOR_ICON
 *   (3) slug forjado/resuelto      → strip(forged-/resolved-) → CATEGORY_KEYWORDS → MOTHER_ICON
 *       (también matchea cualquier server/connector con nombre pero fuera de tabla:
 *        amplía la universalidad sin romper el contrato)
 *   (4) keywords de tools[]        → KEYWORD_ICON (send_→mail, quote→trending-up, …)
 *   (5) armario (5 cubos)          → ARMARIO_ICON (fallback grueso por bucket)
 *   (6) DEFAULT                    → "puzzle"  (+ GALLERY ofrecible en la forja)
 *
 * shape de toolData (lo que produce atoms_router.collect_atoms → n.data del Cuarto):
 *   { id, label, sub, atom, zone, server, tools:[], belt_ref, auth, connector, armario }
 *
 * VERIFICACIÓN LUCIDE: todos los nombres de abajo existen en lucide-static@1.21.0
 * (1986 glifos; verificado en frío contra el árbol de archivos de jsdelivr — ver
 * PLAN-ICONOS.md §verificación). Único candidato inicial inexistente: "scan-3d" →
 * reemplazado por "axis-3d". Se prefieren los nombres canónicos NUEVOS de Lucide
 * (chart-line, chart-column, chart-candlestick) sobre los alias deprecados
 * (line-chart, bar-chart, candlestick-chart) que aún existen como archivo.
 */

// ── 21 CATEGORÍAS MADRE — la base del universo. clave → glifo Lucide ────────────────
const MOTHER_ICON = {
  financiero:   "trending-up",
  documentos:   "file-text",
  academico:    "graduation-cap",
  busqueda:     "search",
  datos:        "database",
  media:        "film",
  medico:       "heart-pulse",
  mapas:        "map",
  cad:          "box",
  simulacion:   "wind",
  electronica:  "cpu",
  codigo:       "code",
  ml_ia:        "brain",
  email:        "mail",
  mensajeria:   "message-circle",
  calendario:   "calendar",
  escritura:    "pen-line",
  pagos:        "credit-card",
  automatizacion: "workflow",
  comunicacion: "radio",
  custom:       "puzzle",
};

// etiqueta humana de cada madre (para la galería / debug)
const MOTHER_LABEL = {
  financiero: "Financiero", documentos: "Documentos", academico: "Académico",
  busqueda: "Búsqueda", datos: "Datos / DB", media: "Media", medico: "Médico",
  mapas: "Mapas / geo", cad: "CAD / 3D", simulacion: "Simulación", electronica: "Electrónica",
  codigo: "Código", ml_ia: "ML / IA", email: "Email", mensajeria: "Mensajería / social",
  calendario: "Calendario", escritura: "Escritura", pagos: "Pagos",
  automatizacion: "Automatización", comunicacion: "Comunicación", custom: "Custom",
};

// ── VARIANTES NIVEL 2 — 3-5 glifos por madre, para la galería que ofrece el default ──
// El primer elemento es siempre el glifo madre (default de la categoría).
const LEVEL2 = {
  financiero:   ["trending-up", "chart-line", "chart-candlestick", "landmark", "dollar-sign"],
  documentos:   ["file-text", "file", "files", "book-open", "table"],
  academico:    ["graduation-cap", "book-marked", "library", "microscope", "flask-conical"],
  busqueda:     ["search", "globe", "telescope", "binoculars", "scan-search"],
  datos:        ["database", "table", "chart-column", "server", "sheet"],
  media:        ["film", "image", "music", "video", "camera"],
  medico:       ["heart-pulse", "stethoscope", "scan", "bone", "pill"],
  mapas:        ["map", "map-pin", "globe", "navigation", "compass"],
  cad:          ["box", "boxes", "axis-3d", "rotate-3d", "pencil-ruler"],
  simulacion:   ["wind", "waves", "gauge", "activity", "calculator"],
  electronica:  ["cpu", "circuit-board", "microchip", "zap", "plug"],
  codigo:       ["code", "terminal", "braces", "git-branch", "git-fork"],
  ml_ia:        ["brain", "brain-circuit", "bot", "sparkles", "network"],
  email:        ["mail", "mail-open", "send", "inbox", "at-sign"],
  mensajeria:   ["message-circle", "message-square", "hash", "users", "send"],
  calendario:   ["calendar", "calendar-days", "calendar-clock", "calendar-check", "clock"],
  escritura:    ["pen-line", "pencil", "feather", "type", "notebook-pen"],
  pagos:        ["credit-card", "wallet", "banknote", "coins", "receipt"],
  automatizacion: ["workflow", "zap", "bot", "repeat", "git-branch"],
  comunicacion: ["radio", "rss", "megaphone", "podcast", "phone"],
  custom:       ["puzzle", "blocks", "package", "shapes", "component"],
};

// ── SERVER_ICON — los servers curados REALES del repo (mcpServers de catalog/templates
// + fixtures). Cada uno mapeado a su glifo; el comentario marca su categoría madre. ──
// NO se inventan servers: esta es la unión exacta de los `mcpServers` que existen hoy.
const SERVER_ICON = {
  // Financiero
  alphavantage:   "chart-candlestick",
  yfinance:       "chart-candlestick",
  backtest:       "chart-line",
  broker:         "landmark",
  ccxt:           "chart-candlestick", // mercados cripto (CCXT, batch a2)
  coingecko:      "coins",             // precios cripto (batch a2)
  fred:           "trending-up",
  massive:        "chart-candlestick", // Massive ex-Polygon (batch a2)
  secedgar:       "landmark",
  precio:         "receipt",          // quote_bom / quote_component (precio de pieza)
  // Académico
  arxiv:          "graduation-cap",
  crossref:       "book-marked",
  openalex:       "graduation-cap",
  orcid:          "id-card",          // identidad del investigador
  pubmed:         "microscope",
  zotero:         "book-marked",
  // Búsqueda
  exa:            "search",
  fetch:          "globe",            // trae una URL cruda
  wikipedia:      "book-open",
  // Datos / DB
  datatools:      "table",            // write_csv / write_xlsx
  excel:          "file-spreadsheet",
  sheets:         "sheet",
  stata:          "chart-column",     // estadística / regresión
  chart:          "chart-line",       // graficación
  // Médico
  dicom:          "scan",
  segmentacion:   "bone",             // segmentación anatómica / volumen 3D
  biomcp:         "microscope",       // literatura biomédica / genómica (batch a4)
  openfda:        "pill",             // datos abiertos FDA: fármacos / recalls (batch a4)
  // CAD / 3D
  freecad:        "box",
  materialsproject: "atom",           // ciencia de materiales
  // Simulación / cómputo científico
  fem:            "gauge",            // análisis de esfuerzos
  openfoam:       "wind",             // CFD
  calc:           "calculator",       // aritmética
  sympy:          "sigma",            // álgebra simbólica
  units:          "ruler",            // conversión de unidades
  // Electrónica
  kicad:          "circuit-board",
  spice:          "zap",              // simulación de circuito
  // Código
  github:         "git-branch",
  context7:       "book-open",        // docs de librerías
  filesystem:     "folder",
  script_runner:  "terminal",
  pysandbox:      "terminal",         // run_python
  jupyter:        "notebook-text",
  echo:           "square-terminal",  // demo / test
  // ML / IA
  huggingface:    "brain",
  // Email
  gmail:          "mail",
  // Mensajería / social
  slack:          "message-square",
  // Calendario
  google_calendar: "calendar",
  // Documentos / escritura
  pandoc:         "file-text",        // conversión de documentos
  // Archivos
  google_drive:   "folder-open",
  // Automatización (interno)
  credprobe:      "key-round",        // probador de credenciales (no on-camera)
};

// ── CONNECTOR_ICON — los connectors REALES (catalog/connectors/onboarding/*.json).
// Muchos coinciden con un server (y ahí gana SERVER_ICON, paso 1); esta tabla cubre
// los átomos de tipo "conexión" cuyo `connector` manda. ──
const CONNECTOR_ICON = {
  alphavantage:   "chart-candlestick", // Financiero
  asana:          "kanban",            // Automatización / PM
  canvas:         "graduation-cap",    // LMS
  classroom:      "graduation-cap",    // Google Classroom
  coingecko:      "coins",             // precios cripto (batch a2)
  context7:       "book-open",         // Código / docs
  exa:            "search",            // Búsqueda
  fred:           "trending-up",       // Financiero / macro
  github:         "git-branch",        // Código
  gmail:          "mail",              // Email
  google_calendar: "calendar",         // Calendario
  google_drive:   "folder-open",       // Documentos / archivos
  hubspot:        "users",             // CRM
  huggingface:    "brain",             // ML / IA
  linear:         "kanban",            // issue tracker
  massive:        "chart-candlestick", // Massive ex-Polygon (batch a2)
  moodle:         "graduation-cap",    // LMS
  notion:         "notebook-text",     // Escritura / docs
  onshape:        "box",               // CAD
  openbom:        "boxes",             // CAD / BOM
  orcid:          "id-card",           // Académico
  osf:            "graduation-cap",    // Open Science Framework
  slack:          "message-square",    // Mensajería
  worldbank:      "landmark",          // Financiero / macro
  zenodo:         "book-marked",       // Académico / repositorio
  zotero:         "book-marked",       // Académico
};

// ── ARMARIO_ICON — los 5 "cubos" (card.armario) como fallback grueso por bucket ──────
const ARMARIO_ICON = {
  mundo:    "globe",      // toca el mundo externo
  archivos: "folder",     // archivos locales
  saberes:  "book-open",  // conocimiento / referencia
  apps:     "blocks",     // apps / integraciones
  datos:    "database",   // datos
};

// ── KEYWORD_ICON — fragmentos de nombres de tools[] → glifo. Orden = prioridad (el
// primero que matchea gana). De más específico a más genérico: get_/list_/search_
// quedan al final para que un keyword con significado real gane primero. ──
const KEYWORD_ICON = [
  // toca afuera / comunicación
  [["send_", "draft", "email", "smtp", "imap"], "mail"],
  [["pay", "charge", "checkout", "invoice", "refund", "billing"], "credit-card"],
  // dominios fuertes
  [["dicom", "windowing", "patient", "study_", "series", "instance", "radiolog", "anatom", "segment"], "heart-pulse"],
  [["schematic", "circuit", "erc", "spice", "pcb", "gerber", "footprint"], "cpu"],
  [["mesh", "stl", "render_volume", "volume_3d", "cad", "step_", "extrude"], "box"],
  [["simulate", "solve", "fem", "foam", "fluid", "thermal", "flow", "elastic", "stress"], "wind"],
  [["quote", "price", "ticker", "stock", "ohlc", "candlestick", "filing", "financ", "xbrl"], "trending-up"],
  [["paper", "arxiv", "scholar", "citation", "doi", "pubmed", "crossref", "orcid"], "graduation-cap"],
  [["commit", "repo", "pull_request", "branch", "git_", "gist"], "git-branch"],
  [["calendar", "event", "freebusy", "ical"], "calendar"],
  // cómputo / datos
  [["sql", "select_", "database", "table", "csv", "xlsx", "spreadsheet", "sheet"], "database"],
  [["chart", "plot", "graph_", "histogram"], "chart-line"],
  [["run_python", "exec", "script", "sandbox", "repl"], "terminal"],
  [["convert", "pandoc", "render_pdf", "to_pdf"], "file-text"],
  [["message", "channel", "post_message", "chat", "slack", "discord", "telegram"], "message-circle"],
  [["map", "geocode", "route", "navigation", "place", "weather"], "map"],
  [["model", "inference", "embedding", "dataset", "predict", "hf_"], "brain"],
  // web / lectura genérica (último: get_/list_/search_/fetch caen acá si nada mejor)
  [["web_", "http", "url", "crawl", "scrape"], "globe"],
  [["search_", "find_", "lookup_", "query_"], "search"],
  [["get_", "list_", "read_", "fetch"], "search"],
];

// ── CATEGORY_KEYWORDS — para el paso (3): matchea un slug (forjado/resuelto o un
// server/connector con nombre fuera de tabla) contra las 21 madre. Substring, primer
// match gana. Cubre el universo de software, no solo los servers de hoy. ──
const CATEGORY_KEYWORDS = [
  ["financiero",   ["financ", "stock", "price", "ticker", "market", "trade", "broker", "edgar", "alpha", "vantage", "yfinance", "quote", "macro", "invest", "bank", "fund"]],
  ["pagos",        ["stripe", "paypal", "payment", "billing", "checkout", "plaid", "wallet", "payout", "merchant"]],
  ["medico",       ["dicom", "medic", "health", "patient", "clinic", "fhir", "hl7", "radiolog", "anatom", "pacs", "orthanc"]],
  ["electronica",  ["kicad", "spice", "circuit", "schematic", "pcb", "electron", "gerber", "eda", "eagle"]],
  ["cad",          ["cad", "freecad", "onshape", "solidwork", "openbom", "stl", "step_", "mesh", "material", "3d", "fusion"]],
  ["simulacion",   ["simul", "fem", "cfd", "foam", "openfoam", "solver", "physics", "fluid", "thermal", "sympy", "units"]],
  ["academico",    ["arxiv", "scholar", "pubmed", "crossref", "openalex", "orcid", "zenodo", "zotero", "academ", "citation", "journal", "doi"]],
  ["media",        ["media", "movie", "film", "tmdb", "imdb", "video", "image", "photo", "music", "audio", "youtube", "spotify"]],
  ["mapas",        ["map", "geo", "location", "route", "navigation", "weather", "osm", "mapbox", "places"]],
  ["calendario",   ["calendar", "schedule", "ical", "booking", "appointment"]],
  ["email",        ["gmail", "email", "mail", "smtp", "imap", "outlook", "sendgrid", "mailgun"]],
  ["mensajeria",   ["slack", "discord", "telegram", "whatsapp", "twilio", "mattermost", "intercom", "chat"]],
  ["pagos",        ["square_"]],
  ["ml_ia",        ["huggingface", "openai", "anthropic", "replicate", "inference", "llm", "embedding", "tensor", "neural", "vision"]],
  ["codigo",       ["github", "gitlab", "bitbucket", "git", "code", "repo", "jira", "linear", "context7", "docker", "npm", "ci_", "deploy"]],
  ["automatizacion", ["zapier", "automat", "workflow", "asana", "trello", "hubspot", "crm", "n8n", "pipeline", "make_"]],
  ["comunicacion", ["feed", "rss", "podcast", "broadcast", "voice", "phone", "zoom", "meet", "webrtc"]],
  ["busqueda",     ["search", "exa", "fetch", "web", "wiki", "crawl", "serp", "brave"]],
  ["datos",        ["data", "sql", "postgres", "mysql", "mongo", "airtable", "sheet", "excel", "csv", "stata", "analytics", "warehouse"]],
  ["documentos",   ["doc", "pdf", "drive", "pandoc", "onedrive", "dropbox", "gdrive", "confluence"]],
  ["escritura",    ["notion", "obsidian", "blog", "cms", "wordpress", "ghost", "write"]],
];

const FORGE_PREFIX = /^(forged|resolved)[-:_]/i;

// ── helpers puros ───────────────────────────────────────────────────────────────────
function _norm(s) { return (s == null ? "" : String(s)).trim().toLowerCase(); }

function _data(toolData) {
  // acepta el objeto-dato directo o un nodo con .data anidado (defensivo)
  if (toolData && typeof toolData === "object") {
    if (toolData.server == null && toolData.connector == null && toolData.tools == null
        && toolData.data && typeof toolData.data === "object") return toolData.data;
  }
  return toolData || {};
}

// matchea un slug contra las 21 madre → clave de categoría, o null
function _categoryForSlug(slug) {
  const s = _norm(slug);
  if (!s) return null;
  for (const [cat, words] of CATEGORY_KEYWORDS) {
    for (const w of words) { if (s.includes(w)) return cat; }
  }
  return null;
}

// matchea la lista de tools contra KEYWORD_ICON → glifo, o null
function _iconForTools(tools) {
  const names = (Array.isArray(tools) ? tools : []).map(_norm).filter(Boolean);
  if (!names.length) return null;
  for (const [frags, icon] of KEYWORD_ICON) {
    for (const f of frags) {
      if (names.some((n) => n.includes(f))) return icon;
    }
  }
  return null;
}

/**
 * resolveIcon(toolData) → "<lucide-name>"  (PURA, nunca lanza, siempre devuelve string).
 * Ver la cadena de resolución en el encabezado del archivo.
 */
function resolveIcon(toolData) {
  const d = _data(toolData);
  const server = _norm(d.server);
  const connector = _norm(d.connector);

  // (1) server conocido
  if (server && Object.prototype.hasOwnProperty.call(SERVER_ICON, server)) return SERVER_ICON[server];
  // (2) connector conocido
  if (connector && Object.prototype.hasOwnProperty.call(CONNECTOR_ICON, connector)) return CONNECTOR_ICON[connector];

  // (3) slug forjado/resuelto (o cualquier server/connector con nombre fuera de tabla)
  //     → strip de prefijo forge → match contra las 21 madre
  const slugSource = server || connector;
  if (slugSource) {
    const slug = slugSource.replace(FORGE_PREFIX, "");
    const cat = _categoryForSlug(slug);
    if (cat) return MOTHER_ICON[cat];
  }

  // (4) keywords de tools[]
  const byTool = _iconForTools(d.tools);
  if (byTool) return byTool;

  // (5) armario (5 cubos)
  const armario = _norm(d.armario);
  if (armario && Object.prototype.hasOwnProperty.call(ARMARIO_ICON, armario)) return ARMARIO_ICON[armario];

  // (6) DEFAULT — el flujo de forja ofrece GALLERY() de 2 niveles
  return MOTHER_ICON.custom; // "puzzle"
}

/**
 * categoryOf(toolData) → clave de categoría madre (o "custom") — para el brillo del lente,
 * agrupar por dominio, o etiquetar. NO se usa en el render base; expuesto para integración.
 */
function categoryOf(toolData) {
  const d = _data(toolData);
  const server = _norm(d.server), connector = _norm(d.connector);
  // si el server/connector es conocido, derivamos la madre por su glifo
  const known = (server && SERVER_ICON[server]) || (connector && CONNECTOR_ICON[connector]) || null;
  if (known) {
    for (const [cat, list] of Object.entries(LEVEL2)) { if (list.includes(known)) return cat; }
  }
  const slugSource = server || connector;
  if (slugSource) {
    const cat = _categoryForSlug(slugSource.replace(FORGE_PREFIX, ""));
    if (cat) return cat;
  }
  return "custom";
}

/**
 * GALLERY(motherKeyOrIcon) → array de glifos nivel-2 para la galería de 2 niveles.
 * Acepta una clave de madre ("medico") o un glifo madre ("heart-pulse").
 */
function GALLERY(key) {
  const k = _norm(key);
  if (LEVEL2[k]) return LEVEL2[k].slice();
  for (const [cat, list] of Object.entries(LEVEL2)) { if (list[0] === k) return list.slice(); }
  return LEVEL2.custom.slice();
}

// el universo plano de glifos que este módulo puede emitir (para el verify)
const ALL_ICONS = Array.from(new Set([
  ...Object.values(MOTHER_ICON),
  ...Object.values(LEVEL2).flat(),
  ...Object.values(SERVER_ICON),
  ...Object.values(CONNECTOR_ICON),
  ...Object.values(ARMARIO_ICON),
  ...KEYWORD_ICON.map(([, icon]) => icon),
])).sort();

// ── ICON_PATHS — markup interno (shapes) de cada glifo Lucide que el módulo puede emitir,
// vendored de lucide-static@1.21.0 (ISC, Lucide contributors). Data PURA (sin PIXI): el
// render (makeDomainGlyph en cuarto.render.js) lo envuelve en un <svg> stroke y lo dibuja
// con PIXI v8 Graphics.svg(). `puzzle` es OBLIGATORIO (fallback duro del draw). ────────────
const ICON_PATHS = {
  "activity"            : '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2" />',
  "at-sign"             : '<circle cx="12" cy="12" r="4" /> <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8" />',
  "atom"                : '<circle cx="12" cy="12" r="1" /> <path d="M20.2 20.2c2.04-2.03.02-7.36-4.5-11.9-4.54-4.52-9.87-6.54-11.9-4.5-2.04 2.03-.02 7.36 4.5 11.9 4.54 4.52 9.87 6.54 11.9 4.5Z" /> <path d="M15.7 15.7c4.52-4.54 6.54-9.87 4.5-11.9-2.03-2.04-7.36-.02-11.9 4.5-4.52 4.54-6.54 9.87-4.5 11.9 2.03 2.04 7.36.02 11.9-4.5Z" />',
  "axis-3d"             : '<path d="M13.5 10.5 15 9" /> <path d="M4 4v15a1 1 0 0 0 1 1h15" /> <path d="M4.293 19.707 6 18" /> <path d="m9 15 1.5-1.5" />',
  "banknote"            : '<rect width="20" height="12" x="2" y="6" rx="2" /> <circle cx="12" cy="12" r="2" /> <path d="M6 12h.01M18 12h.01" />',
  "binoculars"          : '<path d="M10 10h4" /> <path d="M19 7V4a1 1 0 0 0-1-1h-2a1 1 0 0 0-1 1v3" /> <path d="M20 21a2 2 0 0 0 2-2v-3.851c0-1.39-2-2.962-2-4.829V8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v11a2 2 0 0 0 2 2z" /> <path d="M 22 16 L 2 16" /> <path d="M4 21a2 2 0 0 1-2-2v-3.851c0-1.39 2-2.962 2-4.829V8a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v11a2 2 0 0 1-2 2z" /> <path d="M9 7V4a1 1 0 0 0-1-1H6a1 1 0 0 0-1 1v3" />',
  "blocks"              : '<path d="M10 22V7a1 1 0 0 0-1-1H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5a1 1 0 0 0-1-1H2" /> <rect x="14" y="2" width="8" height="8" rx="1" />',
  "bone"                : '<path d="M17 10c.7-.7 1.69 0 2.5 0a2.5 2.5 0 1 0 0-5 .5.5 0 0 1-.5-.5 2.5 2.5 0 1 0-5 0c0 .81.7 1.8 0 2.5l-7 7c-.7.7-1.69 0-2.5 0a2.5 2.5 0 0 0 0 5c.28 0 .5.22.5.5a2.5 2.5 0 1 0 5 0c0-.81-.7-1.8 0-2.5Z" />',
  "book-marked"         : '<path d="M10 2v8l3-3 3 3V2" /> <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20" />',
  "book-open"           : '<path d="M12 7v14" /> <path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z" />',
  "bot"                 : '<path d="M12 8V4H8" /> <rect width="16" height="12" x="4" y="8" rx="2" /> <path d="M2 14h2" /> <path d="M20 14h2" /> <path d="M15 13v2" /> <path d="M9 13v2" />',
  "box"                 : '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" /> <path d="m3.3 7 8.7 5 8.7-5" /> <path d="M12 22V12" />',
  "boxes"               : '<path d="M2.97 12.92A2 2 0 0 0 2 14.63v3.24a2 2 0 0 0 .97 1.71l3 1.8a2 2 0 0 0 2.06 0L12 19v-5.5l-5-3-4.03 2.42Z" /> <path d="m7 16.5-4.74-2.85" /> <path d="m7 16.5 5-3" /> <path d="M7 16.5v5.17" /> <path d="M12 13.5V19l3.97 2.38a2 2 0 0 0 2.06 0l3-1.8a2 2 0 0 0 .97-1.71v-3.24a2 2 0 0 0-.97-1.71L17 10.5l-5 3Z" /> <path d="m17 16.5-5-3" /> <path d="m17 16.5 4.74-2.85" /> <path d="M17 16.5v5.17" /> <path d="M7.97 4.42A2 2 0 0 0 7 6.13v4.37l5 3 5-3V6.13a2 2 0 0 0-.97-1.71l-3-1.8a2 2 0 0 0-2.06 0l-3 1.8Z" /> <path d="M12 8 7.26 5.15" /> <path d="m12 8 4.74-2.85" /> <path d="M12 13.5V8" />',
  "braces"              : '<path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5c0 1.1.9 2 2 2h1" /> <path d="M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1" />',
  "brain"               : '<path d="M12 18V5" /> <path d="M15 13a4.17 4.17 0 0 1-3-4 4.17 4.17 0 0 1-3 4" /> <path d="M17.598 6.5A3 3 0 1 0 12 5a3 3 0 1 0-5.598 1.5" /> <path d="M17.997 5.125a4 4 0 0 1 2.526 5.77" /> <path d="M18 18a4 4 0 0 0 2-7.464" /> <path d="M19.967 17.483A4 4 0 1 1 12 18a4 4 0 1 1-7.967-.517" /> <path d="M6 18a4 4 0 0 1-2-7.464" /> <path d="M6.003 5.125a4 4 0 0 0-2.526 5.77" />',
  "brain-circuit"       : '<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z" /> <path d="M9 13a4.5 4.5 0 0 0 3-4" /> <path d="M6.003 5.125A3 3 0 0 0 6.401 6.5" /> <path d="M3.477 10.896a4 4 0 0 1 .585-.396" /> <path d="M6 18a4 4 0 0 1-1.967-.516" /> <path d="M12 13h4" /> <path d="M12 18h6a2 2 0 0 1 2 2v1" /> <path d="M12 8h8" /> <path d="M16 8V5a2 2 0 0 1 2-2" /> <circle cx="16" cy="13" r=".5" /> <circle cx="18" cy="3" r=".5" /> <circle cx="20" cy="21" r=".5" /> <circle cx="20" cy="8" r=".5" />',
  "calculator"          : '<rect width="16" height="20" x="4" y="2" rx="2" /> <line x1="8" x2="16" y1="6" y2="6" /> <line x1="16" x2="16" y1="14" y2="18" /> <path d="M16 10h.01" /> <path d="M12 10h.01" /> <path d="M8 10h.01" /> <path d="M12 14h.01" /> <path d="M8 14h.01" /> <path d="M12 18h.01" /> <path d="M8 18h.01" />',
  "calendar"            : '<path d="M8 2v4" /> <path d="M16 2v4" /> <rect width="18" height="18" x="3" y="4" rx="2" /> <path d="M3 10h18" />',
  "calendar-check"      : '<path d="M8 2v4" /> <path d="M16 2v4" /> <rect width="18" height="18" x="3" y="4" rx="2" /> <path d="M3 10h18" /> <path d="m9 16 2 2 4-4" />',
  "calendar-clock"      : '<path d="M16 14v2.2l1.6 1" /> <path d="M16 2v4" /> <path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5" /> <path d="M3 10h5" /> <path d="M8 2v4" /> <circle cx="16" cy="16" r="6" />',
  "calendar-days"       : '<path d="M8 2v4" /> <path d="M16 2v4" /> <rect width="18" height="18" x="3" y="4" rx="2" /> <path d="M3 10h18" /> <path d="M8 14h.01" /> <path d="M12 14h.01" /> <path d="M16 14h.01" /> <path d="M8 18h.01" /> <path d="M12 18h.01" /> <path d="M16 18h.01" />',
  "camera"              : '<path d="M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z" /> <circle cx="12" cy="13" r="3" />',
  "chart-candlestick"   : '<path d="M9 5v4" /> <rect width="4" height="6" x="7" y="9" rx="1" /> <path d="M9 15v2" /> <path d="M17 3v2" /> <rect width="4" height="8" x="15" y="5" rx="1" /> <path d="M17 13v3" /> <path d="M3 3v16a2 2 0 0 0 2 2h16" />',
  "chart-column"        : '<path d="M3 3v16a2 2 0 0 0 2 2h16" /> <path d="M18 17V9" /> <path d="M13 17V5" /> <path d="M8 17v-3" />',
  "chart-line"          : '<path d="M3 3v16a2 2 0 0 0 2 2h16" /> <path d="m19 9-5 5-4-4-3 3" />',
  "circuit-board"       : '<rect width="18" height="18" x="3" y="3" rx="2" /> <path d="M11 9h4a2 2 0 0 0 2-2V3" /> <circle cx="9" cy="9" r="2" /> <path d="M7 21v-4a2 2 0 0 1 2-2h4" /> <circle cx="15" cy="15" r="2" />',
  "clock"               : '<circle cx="12" cy="12" r="10" /> <path d="M12 6v6l4 2" />',
  "code"                : '<path d="m16 18 6-6-6-6" /> <path d="m8 6-6 6 6 6" />',
  "coins"               : '<path d="M13.744 17.736a6 6 0 1 1-7.48-7.48" /> <path d="M15 6h1v4" /> <path d="m6.134 14.768.866-.5 2 3.464" /> <circle cx="16" cy="8" r="6" />',
  "compass"             : '<circle cx="12" cy="12" r="10" /> <path d="m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z" />',
  "component"           : '<path d="M15.536 11.293a1 1 0 0 0 0 1.414l2.376 2.377a1 1 0 0 0 1.414 0l2.377-2.377a1 1 0 0 0 0-1.414l-2.377-2.377a1 1 0 0 0-1.414 0z" /> <path d="M2.297 11.293a1 1 0 0 0 0 1.414l2.377 2.377a1 1 0 0 0 1.414 0l2.377-2.377a1 1 0 0 0 0-1.414L6.088 8.916a1 1 0 0 0-1.414 0z" /> <path d="M8.916 17.912a1 1 0 0 0 0 1.415l2.377 2.376a1 1 0 0 0 1.414 0l2.377-2.376a1 1 0 0 0 0-1.415l-2.377-2.376a1 1 0 0 0-1.414 0z" /> <path d="M8.916 4.674a1 1 0 0 0 0 1.414l2.377 2.376a1 1 0 0 0 1.414 0l2.377-2.376a1 1 0 0 0 0-1.414l-2.377-2.377a1 1 0 0 0-1.414 0z" />',
  "cpu"                 : '<path d="M12 20v2" /> <path d="M12 2v2" /> <path d="M17 20v2" /> <path d="M17 2v2" /> <path d="M2 12h2" /> <path d="M2 17h2" /> <path d="M2 7h2" /> <path d="M20 12h2" /> <path d="M20 17h2" /> <path d="M20 7h2" /> <path d="M7 20v2" /> <path d="M7 2v2" /> <rect x="4" y="4" width="16" height="16" rx="2" /> <rect x="8" y="8" width="8" height="8" rx="1" />',
  "credit-card"         : '<rect width="20" height="14" x="2" y="5" rx="2" /> <line x1="2" x2="22" y1="10" y2="10" />',
  "database"            : '<ellipse cx="12" cy="5" rx="9" ry="3" /> <path d="M3 5V19A9 3 0 0 0 21 19V5" /> <path d="M3 12A9 3 0 0 0 21 12" />',
  "dollar-sign"         : '<line x1="12" x2="12" y1="2" y2="22" /> <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />',
  "feather"             : '<path d="M12.67 19a2 2 0 0 0 1.416-.588l6.154-6.172a6 6 0 0 0-8.49-8.49L5.586 9.914A2 2 0 0 0 5 11.328V18a1 1 0 0 0 1 1z" /> <path d="M16 8 2 22" /> <path d="M17.5 15H9" />',
  "file"                : '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" /> <path d="M14 2v5a1 1 0 0 0 1 1h5" />',
  "file-spreadsheet"    : '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" /> <path d="M14 2v5a1 1 0 0 0 1 1h5" /> <path d="M8 13h2" /> <path d="M14 13h2" /> <path d="M8 17h2" /> <path d="M14 17h2" />',
  "file-text"           : '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" /> <path d="M14 2v5a1 1 0 0 0 1 1h5" /> <path d="M10 9H8" /> <path d="M16 13H8" /> <path d="M16 17H8" />',
  "files"               : '<path d="M15 2h-4a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V8" /> <path d="M16.706 2.706A2.4 2.4 0 0 0 15 2v5a1 1 0 0 0 1 1h5a2.4 2.4 0 0 0-.706-1.706z" /> <path d="M5 7a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h8a2 2 0 0 0 1.732-1" />',
  "film"                : '<rect width="18" height="18" x="3" y="3" rx="2" /> <path d="M7 3v18" /> <path d="M3 7.5h4" /> <path d="M3 12h18" /> <path d="M3 16.5h4" /> <path d="M17 3v18" /> <path d="M17 7.5h4" /> <path d="M17 16.5h4" />',
  "flask-conical"       : '<path d="M14 2v6a2 2 0 0 0 .245.96l5.51 10.08A2 2 0 0 1 18 22H6a2 2 0 0 1-1.755-2.96l5.51-10.08A2 2 0 0 0 10 8V2" /> <path d="M6.453 15h11.094" /> <path d="M8.5 2h7" />',
  "folder"              : '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />',
  "folder-open"         : '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" />',
  "gauge"               : '<path d="m12 14 4-4" /> <path d="M3.34 19a10 10 0 1 1 17.32 0" />',
  "git-branch"          : '<path d="M15 6a9 9 0 0 0-9 9V3" /> <circle cx="18" cy="6" r="3" /> <circle cx="6" cy="18" r="3" />',
  "git-fork"            : '<circle cx="12" cy="18" r="3" /> <circle cx="6" cy="6" r="3" /> <circle cx="18" cy="6" r="3" /> <path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9" /> <path d="M12 12v3" />',
  "globe"               : '<circle cx="12" cy="12" r="10" /> <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" /> <path d="M2 12h20" />',
  "graduation-cap"      : '<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z" /> <path d="M22 10v6" /> <path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5" />',
  "hash"                : '<line x1="4" x2="20" y1="9" y2="9" /> <line x1="4" x2="20" y1="15" y2="15" /> <line x1="10" x2="8" y1="3" y2="21" /> <line x1="16" x2="14" y1="3" y2="21" />',
  "heart-pulse"         : '<path d="M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5" /> <path d="M3.22 13H9.5l.5-1 2 4.5 2-7 1.5 3.5h5.27" />',
  "id-card"             : '<path d="M16 10h2" /> <path d="M16 14h2" /> <path d="M6.17 15a3 3 0 0 1 5.66 0" /> <circle cx="9" cy="11" r="2" /> <rect x="2" y="5" width="20" height="14" rx="2" />',
  "image"               : '<rect width="18" height="18" x="3" y="3" rx="2" ry="2" /> <circle cx="9" cy="9" r="2" /> <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />',
  "inbox"               : '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12" /> <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />',
  "kanban"              : '<path d="M5 3v14" /> <path d="M12 3v8" /> <path d="M19 3v18" />',
  "key-round"           : '<path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z" /> <circle cx="16.5" cy="7.5" r=".5" fill="currentColor" />',
  "landmark"            : '<path d="M10 18v-7" /> <path d="M11.119 2.205a2 2 0 0 1 1.762 0l7.84 3.846A.5.5 0 0 1 20.5 7h-17a.5.5 0 0 1-.22-.949z" /> <path d="M14 18v-7" /> <path d="M18 18v-7" /> <path d="M3 22h18" /> <path d="M6 18v-7" />',
  "library"             : '<path d="m16 6 4 14" /> <path d="M12 6v14" /> <path d="M8 8v12" /> <path d="M4 4v16" />',
  "mail"                : '<path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7" /> <rect x="2" y="4" width="20" height="16" rx="2" />',
  "mail-open"           : '<path d="M21.2 8.4c.5.38.8.97.8 1.6v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V10a2 2 0 0 1 .8-1.6l8-6a2 2 0 0 1 2.4 0l8 6Z" /> <path d="m22 10-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 10" />',
  "map"                 : '<path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z" /> <path d="M15 5.764v15" /> <path d="M9 3.236v15" />',
  "map-pin"             : '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0" /> <circle cx="12" cy="10" r="3" />',
  "megaphone"           : '<path d="M11 6a13 13 0 0 0 8.4-2.8A1 1 0 0 1 21 4v12a1 1 0 0 1-1.6.8A13 13 0 0 0 11 14H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z" /> <path d="M6 14a12 12 0 0 0 2.4 7.2 2 2 0 0 0 3.2-2.4A8 8 0 0 1 10 14" /> <path d="M8 6v8" />',
  "message-circle"      : '<path d="M2.992 16.342a2 2 0 0 1 .094 1.167l-1.065 3.29a1 1 0 0 0 1.236 1.168l3.413-.998a2 2 0 0 1 1.099.092 10 10 0 1 0-4.777-4.719" />',
  "message-square"      : '<path d="M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z" />',
  "microchip"           : '<path d="M10 12h4" /> <path d="M10 17h4" /> <path d="M10 7h4" /> <path d="M18 12h2" /> <path d="M18 18h2" /> <path d="M18 6h2" /> <path d="M4 12h2" /> <path d="M4 18h2" /> <path d="M4 6h2" /> <rect x="6" y="2" width="12" height="20" rx="2" />',
  "microscope"          : '<path d="M6 18h8" /> <path d="M3 22h18" /> <path d="M14 22a7 7 0 1 0 0-14h-1" /> <path d="M9 14h2" /> <path d="M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z" /> <path d="M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3" />',
  "music"               : '<path d="M9 18V5l12-2v13" /> <circle cx="6" cy="18" r="3" /> <circle cx="18" cy="16" r="3" />',
  "navigation"          : '<polygon points="3 11 22 2 13 21 11 13 3 11" />',
  "network"             : '<rect x="16" y="16" width="6" height="6" rx="1" /> <rect x="2" y="16" width="6" height="6" rx="1" /> <rect x="9" y="2" width="6" height="6" rx="1" /> <path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3" /> <path d="M12 12V8" />',
  "notebook-pen"        : '<path d="M13.4 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7.4" /> <path d="M2 6h4" /> <path d="M2 10h4" /> <path d="M2 14h4" /> <path d="M2 18h4" /> <path d="M21.378 5.626a1 1 0 1 0-3.004-3.004l-5.01 5.012a2 2 0 0 0-.506.854l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837a2 2 0 0 0 .854-.506z" />',
  "notebook-text"       : '<path d="M2 6h4" /> <path d="M2 10h4" /> <path d="M2 14h4" /> <path d="M2 18h4" /> <rect width="16" height="20" x="4" y="2" rx="2" /> <path d="M9.5 8h5" /> <path d="M9.5 12H16" /> <path d="M9.5 16H14" />',
  "package"             : '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z" /> <path d="M12 22V12" /> <polyline points="3.29 7 12 12 20.71 7" /> <path d="m7.5 4.27 9 5.15" />',
  "pen-line"            : '<path d="M13 21h8" /> <path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" />',
  "pencil"              : '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" /> <path d="m15 5 4 4" />',
  "pencil-ruler"        : '<path d="M13 7 8.7 2.7a2.41 2.41 0 0 0-3.4 0L2.7 5.3a2.41 2.41 0 0 0 0 3.4L7 13" /> <path d="m8 6 2-2" /> <path d="m18 16 2-2" /> <path d="m17 11 4.3 4.3c.94.94.94 2.46 0 3.4l-2.6 2.6c-.94.94-2.46.94-3.4 0L11 17" /> <path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" /> <path d="m15 5 4 4" />',
  "phone"               : '<path d="M13.832 16.568a1 1 0 0 0 1.213-.303l.355-.465A2 2 0 0 1 17 15h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2A18 18 0 0 1 2 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-.8 1.6l-.468.351a1 1 0 0 0-.292 1.233 14 14 0 0 0 6.392 6.384" />',
  "pill"                : '<path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z" /> <path d="m8.5 8.5 7 7" />',
  "plug"                : '<path d="M12 22v-5" /> <path d="M15 8V2" /> <path d="M17 8a1 1 0 0 1 1 1v4a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1z" /> <path d="M9 8V2" />',
  "podcast"             : '<path d="M13 17a1 1 0 1 0-2 0l.5 4.5a0.5 0.5 0 0 0 1 0z" fill="currentColor" /> <path d="M16.85 18.58a9 9 0 1 0-9.7 0" /> <path d="M8 14a5 5 0 1 1 8 0" /> <circle cx="12" cy="11" r="1" fill="currentColor" />',
  "puzzle"              : '<path d="M15.39 4.39a1 1 0 0 0 1.68-.474 2.5 2.5 0 1 1 3.014 3.015 1 1 0 0 0-.474 1.68l1.683 1.682a2.414 2.414 0 0 1 0 3.414L19.61 15.39a1 1 0 0 1-1.68-.474 2.5 2.5 0 1 0-3.014 3.015 1 1 0 0 1 .474 1.68l-1.683 1.682a2.414 2.414 0 0 1-3.414 0L8.61 19.61a1 1 0 0 0-1.68.474 2.5 2.5 0 1 1-3.014-3.015 1 1 0 0 0 .474-1.68l-1.683-1.682a2.414 2.414 0 0 1 0-3.414L4.39 8.61a1 1 0 0 1 1.68.474 2.5 2.5 0 1 0 3.014-3.015 1 1 0 0 1-.474-1.68l1.683-1.682a2.414 2.414 0 0 1 3.414 0z" />',
  "radio"               : '<path d="M16.247 7.761a6 6 0 0 1 0 8.478" /> <path d="M19.075 4.933a10 10 0 0 1 0 14.134" /> <path d="M4.925 19.067a10 10 0 0 1 0-14.134" /> <path d="M7.753 16.239a6 6 0 0 1 0-8.478" /> <circle cx="12" cy="12" r="2" />',
  "receipt"             : '<path d="M12 17V7" /> <path d="M16 8h-6a2 2 0 0 0 0 4h4a2 2 0 0 1 0 4H8" /> <path d="M4 3a1 1 0 0 1 1-1 1.3 1.3 0 0 1 .7.2l.933.6a1.3 1.3 0 0 0 1.4 0l.934-.6a1.3 1.3 0 0 1 1.4 0l.933.6a1.3 1.3 0 0 0 1.4 0l.933-.6a1.3 1.3 0 0 1 1.4 0l.934.6a1.3 1.3 0 0 0 1.4 0l.933-.6A1.3 1.3 0 0 1 19 2a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1 1.3 1.3 0 0 1-.7-.2l-.933-.6a1.3 1.3 0 0 0-1.4 0l-.934.6a1.3 1.3 0 0 1-1.4 0l-.933-.6a1.3 1.3 0 0 0-1.4 0l-.933.6a1.3 1.3 0 0 1-1.4 0l-.934-.6a1.3 1.3 0 0 0-1.4 0l-.933.6a1.3 1.3 0 0 1-.7.2 1 1 0 0 1-1-1z" />',
  "repeat"              : '<path d="m17 2 4 4-4 4" /> <path d="M3 11v-1a4 4 0 0 1 4-4h14" /> <path d="m7 22-4-4 4-4" /> <path d="M21 13v1a4 4 0 0 1-4 4H3" />',
  "rotate-3d"           : '<path d="m15.194 13.707 3.814 1.86-1.86 3.814" /> <path d="M16.47214 7.52786 A 5 10 0 1 0 13 21.79796" /> <path d="M21.79796 11 A 10 5 0 1 0 19 15.57071" />',
  "rss"                 : '<path d="M4 11a9 9 0 0 1 9 9" /> <path d="M4 4a16 16 0 0 1 16 16" /> <circle cx="5" cy="19" r="1" />',
  "ruler"               : '<path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0Z" /> <path d="m14.5 12.5 2-2" /> <path d="m11.5 9.5 2-2" /> <path d="m8.5 6.5 2-2" /> <path d="m17.5 15.5 2-2" />',
  "scan"                : '<path d="M3 7V5a2 2 0 0 1 2-2h2" /> <path d="M17 3h2a2 2 0 0 1 2 2v2" /> <path d="M21 17v2a2 2 0 0 1-2 2h-2" /> <path d="M7 21H5a2 2 0 0 1-2-2v-2" />',
  "scan-search"         : '<path d="M3 7V5a2 2 0 0 1 2-2h2" /> <path d="M17 3h2a2 2 0 0 1 2 2v2" /> <path d="M21 17v2a2 2 0 0 1-2 2h-2" /> <path d="M7 21H5a2 2 0 0 1-2-2v-2" /> <circle cx="12" cy="12" r="3" /> <path d="m16 16-1.9-1.9" />',
  "search"              : '<path d="m21 21-4.34-4.34" /> <circle cx="11" cy="11" r="8" />',
  "send"                : '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z" /> <path d="m21.854 2.147-10.94 10.939" />',
  "server"              : '<rect width="20" height="8" x="2" y="2" rx="2" ry="2" /> <rect width="20" height="8" x="2" y="14" rx="2" ry="2" /> <line x1="6" x2="6.01" y1="6" y2="6" /> <line x1="6" x2="6.01" y1="18" y2="18" />',
  "shapes"              : '<path d="M8.3 10a.7.7 0 0 1-.626-1.079L11.4 3a.7.7 0 0 1 1.198-.043L16.3 8.9a.7.7 0 0 1-.572 1.1Z" /> <rect x="3" y="14" width="7" height="7" rx="1" /> <circle cx="17.5" cy="17.5" r="3.5" />',
  "sheet"               : '<rect width="18" height="18" x="3" y="3" rx="2" ry="2" /> <line x1="3" x2="21" y1="9" y2="9" /> <line x1="3" x2="21" y1="15" y2="15" /> <line x1="9" x2="9" y1="9" y2="21" /> <line x1="15" x2="15" y1="9" y2="21" />',
  "sigma"               : '<path d="M18 7V5a1 1 0 0 0-1-1H6.5a.5.5 0 0 0-.4.8l4.5 6a2 2 0 0 1 0 2.4l-4.5 6a.5.5 0 0 0 .4.8H17a1 1 0 0 0 1-1v-2" />',
  "sparkles"            : '<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z" /> <path d="M20 2v4" /> <path d="M22 4h-4" /> <circle cx="4" cy="20" r="2" />',
  "square-terminal"     : '<path d="m7 11 2-2-2-2" /> <path d="M11 13h4" /> <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />',
  "stethoscope"         : '<path d="M11 2v2" /> <path d="M5 2v2" /> <path d="M5 3H4a2 2 0 0 0-2 2v4a6 6 0 0 0 12 0V5a2 2 0 0 0-2-2h-1" /> <path d="M8 15a6 6 0 0 0 12 0v-3" /> <circle cx="20" cy="10" r="2" />',
  "table"               : '<path d="M12 3v18" /> <rect width="18" height="18" x="3" y="3" rx="2" /> <path d="M3 9h18" /> <path d="M3 15h18" />',
  "telescope"           : '<path d="m10.065 12.493-6.18 1.318a.934.934 0 0 1-1.108-.702l-.537-2.15a1.07 1.07 0 0 1 .691-1.265l13.504-4.44" /> <path d="m13.56 11.747 4.332-.924" /> <path d="m16 21-3.105-6.21" /> <path d="M16.485 5.94a2 2 0 0 1 1.455-2.425l1.09-.272a1 1 0 0 1 1.212.727l1.515 6.06a1 1 0 0 1-.727 1.213l-1.09.272a2 2 0 0 1-2.425-1.455z" /> <path d="m6.158 8.633 1.114 4.456" /> <path d="m8 21 3.105-6.21" /> <circle cx="12" cy="13" r="2" />',
  "terminal"            : '<path d="M12 19h8" /> <path d="m4 17 6-6-6-6" />',
  "trending-up"         : '<path d="M16 7h6v6" /> <path d="m22 7-8.5 8.5-5-5L2 17" />',
  "type"                : '<path d="M12 4v16" /> <path d="M4 7V5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v2" /> <path d="M9 20h6" />',
  "users"               : '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /> <path d="M16 3.128a4 4 0 0 1 0 7.744" /> <path d="M22 21v-2a4 4 0 0 0-3-3.87" /> <circle cx="9" cy="7" r="4" />',
  "video"               : '<path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5" /> <rect x="2" y="6" width="14" height="12" rx="2" />',
  "wallet"              : '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1" /> <path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4" />',
  "waves"               : '<path d="M2 12q2.5 2 5 0t5 0 5 0 5 0" /> <path d="M2 19q2.5 2 5 0t5 0 5 0 5 0" /> <path d="M2 5q2.5 2 5 0t5 0 5 0 5 0" />',
  "wind"                : '<path d="M12.8 19.6A2 2 0 1 0 14 16H2" /> <path d="M17.5 8a2.5 2.5 0 1 1 2 4H2" /> <path d="M9.8 4.4A2 2 0 1 1 11 8H2" />',
  "workflow"            : '<rect width="8" height="8" x="3" y="3" rx="2" /> <path d="M7 11v4a2 2 0 0 0 2 2h4" /> <rect width="8" height="8" x="13" y="13" rx="2" />',
  "zap"                 : '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z" />',
};

export {
  resolveIcon, categoryOf, GALLERY,
  MOTHER_ICON, MOTHER_LABEL, LEVEL2,
  SERVER_ICON, CONNECTOR_ICON, KEYWORD_ICON, ARMARIO_ICON, CATEGORY_KEYWORDS,
  ALL_ICONS, ICON_PATHS,
};
