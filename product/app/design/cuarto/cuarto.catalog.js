/* cuarto.catalog.js — EL CATÁLOGO REAL de átomos del Cuarto.
 *
 * C1 (Fase 1): la paleta tira de GET /v1/atoms/catalog EN VIVO — cero demo, cero
 * hardcode. Cada átomo del backend (tool | conexion) aparece como pieza equipable.
 * El validador acepta receta MULTI-BELT (belt_refs[] verificado verde), así que la
 * paleta puede mezclar belts: cada pieza arrastra su propio belt_ref y la proyección
 * los une.  (El demo single-belt de research quedó RETIRADO con esta versión.)
 *
 * Invariante "cero teatro": si el endpoint no responde, NO se inventan cards — se
 * propaga el error y la paleta queda vacía con aviso (fail loud).
 *
 * zona (del backend, regla C3): read→fuentes · process→mesa · write/send→entrega.
 */

// zona del backend → category del render (color del átomo + ghost de drag)
const ZONE_CATEGORY = { fuentes: "read", mesa: "process", entrega: "write" };

const _titleize = (s) => (s || "").replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const _humanTool = (t) => (t || "").replace(/^[a-z]+_/, "").replace(/[_-]+/g, " ");

/* ══ NATIVAS — capacidad del modelo, no pieza equipable ═════════════════════════════
 * calc/time/sympy/units no son integraciones: son cosas que el modelo YA hace. Salen del
 * catálogo equipable (sin toggles, sin gate): un `uvx` faltante pintaba de rojo una
 * capacidad que igual funciona.
 *
 * [FIX-P4] Y NO SE ANUNCIAN. La franja "Ya vienen en el modelo" (NATIVE_CAPABILITIES +
 * #palNativas) se BORRÓ: decirle a un modelo frontier que sabe sumar es ruido. Lo que el
 * agente NO tiene lo trae el KIT BASE, equipado de fábrica (kit_base.py). Este Set queda
 * porque sigue haciendo el trabajo REAL: sacar esas 4 del piso equipable. */
export const NATIVE_SERVERS = new Set(["calc", "time", "sympy", "units"]);

export function esNativa(a) {
  if (!a) return false;
  return NATIVE_SERVERS.has(a.server || a.backed_by || a.id || "");
}

export const CATALOG_KIND_META = {
  public_mcp: {
    label: "MCP público",
    short: "MCP",
    description: "Tool del catálogo público/verificado de MCPs de Aleph",
  },
  built_in_piece: {
    label: "Pieza incluida",
    short: "Incluida",
    description: "Pieza nativa del Cuarto, sin instalación externa",
  },
  account_connector: {
    label: "Conector de cuenta",
    short: "Cuenta",
    description: "Conecta tu cuenta o API key antes de usar todo su alcance",
  },
};

export const BUILTIN_CATALOG_ENTRIES = [
  {
    key: "builtin:memoria",
    id: "memoria",
    catalogKind: "built_in_piece",
    label: "Memoria compartida",
    sub: "base común que el agente y sus sub-agentes pueden consultar entre corridas",
    atom: "memoria",
    zone: "mesa",
    category: "process",
    auth: "keyless",
    tools: [],
    server: null,
    ref: null,
    connector: null,
    armario: "saberes",
    state: "ready",
    badge: "Incluida · sin llave",
  },
  {
    key: "builtin:contexto",
    id: "contexto",
    catalogKind: "built_in_piece",
    label: "Contexto",
    sub: "documentos, instrucciones y conocimiento que el agente mantiene a mano",
    atom: "contexto",
    zone: "mesa",
    category: "process",
    auth: "keyless",
    tools: [],
    server: null,
    ref: null,
    connector: null,
    armario: "saberes",
    state: "ready",
    badge: "Incluida · sin llave",
  },
];

function _kindForAtom(a) {
  return (a && a.auth && a.auth !== "keyless") || (a && a.atom === "conexion")
    ? "account_connector"
    : "public_mcp";
}

function _normalizeKind(entry) {
  const kind = entry.catalogKind || "public_mcp";
  const meta = CATALOG_KIND_META[kind] || CATALOG_KIND_META.public_mcp;
  entry.kindLabel = meta.label;
  entry.kindShort = meta.short;
  entry.kindDescription = meta.description;
  entry.searchText = [
    entry.label, entry.sub, entry.server, entry.connector, entry.auth,
    entry.armario, entry.zone, entry.kindLabel, ...(entry.tools || []),
    ...((entry.toolsDetail || []).map((t) => t.frase)),
  ].filter(Boolean).join(" ").toLowerCase();
  return entry;
}

/* deriveRequirements — C2: qué declara un átomo que NECESITA, para ARMAR su panel de
 * Opciones (no fijo). Es el FALLBACK del frontend hasta que el backend agregue
 * `atom.requirements` a /v1/atoms/catalog (ver REQUIREMENTS-CONTRACT.md). Si el backend
 * ya lo trae, `normalizeAtom` usa ése y NO llama a esto.
 *
 * Reglas (de los campos que el catálogo YA expone: atom/zone/auth/connector/state):
 *  · conexión / no-keyless con connector → bloque `connect` (activar + llave/OAuth)
 *  · tool keyless en Fuentes              → `readonly` (no toca el mundo, sin llave, sin perillas)
 *  · zona entrega o conexión              → `gate.applicable` (perilla Autonomía)
 *  · params HUMANO = sus tools[] como toggles ("Qué hace esta pieza") → tool_filters
 */
function deriveRequirements(a) {
  const atom = a.atom || "tool";
  const zone = a.zone || "mesa";
  const auth = a.auth || "keyless";
  const connector = a.connector || null;
  const tools = a.tools || [];
  // necesita conexión si hay CUALQUIER connector real (incluye gateados connectable:false → el widget
  // los muestra bloqueados, no los oculta; y keyless-con-onboarding como worldbank → modo SWITCH).
  const needsConn = !!connector;
  // readonly puro (panel mínimo, sin widget) = keyless SIN connector (yfinance/arxiv): nada que conectar.
  const readonly = atom === "tool" && zone === "fuentes" && auth === "keyless" && !connector;
  const gateApplicable = zone === "entrega" || atom === "conexion";

  // tuning (detalle/pasos) es AGENT-LEVEL → vive en el núcleo, no en cada pieza (gap 4)
  const req = { readonly, tuning: [] };

  if (needsConn) {
    req.connect = {
      kind: auth,                                  // auth REAL: keyless | token | personal_token | oauth
      connector: connector,                        // (el widget rinde el modo por auth_method que trae /v1/connectors/{name})
      connectable: a.connectable !== false,        // false = gateado (p.ej. OAuth sin app)
      label: "Conectar " + _titleize(connector),
    };
  }
  if (gateApplicable) req.gate = { applicable: true, default: "needs_ok" };

  if (!readonly && tools.length) {
    req.params = [{
      key: "tools", label: "Qué hace esta pieza", type: "multitoggle",
      options: tools.map((t) => ({ value: t, label: _humanTool(t), on: true })),
    }];
  } else {
    req.params = [];
  }
  // info read-only de capacidades (para el panel mínimo de una Fuente de solo-lectura)
  req.capabilities = tools.map((t) => _humanTool(t));
  return req;
}

/* Reconciliación con Stream B (C3): el backend ya ENVÍA `requirements` con forma
 *   { connection:{needed,auth,connector,connectable,state}, params:[], gate:{gated,level} }
 * (ver FASE1-C3-BYO-NOTES.md). Mapeamos ESA forma a nuestro modelo interno de panel
 * ({connect, gate.applicable, params, readonly, tuning, capabilities}) para que cuando
 * F1-byomcp mergee, el panel consuma lo del backend sin romperse. Si no viene, derivamos. */
function _mergeBackendRequirements(derived, br) {
  if (!br || typeof br !== "object") return derived;
  if (br.connection) {
    if (br.connection.needed) {
      const auth = br.connection.auth === "byok" ? "token" : (br.connection.auth || "token");
      const connector = br.connection.connector || (derived.connect && derived.connect.connector) || "";
      derived.connect = {
        kind: auth === "keyless" ? "token" : auth,
        connector,
        connectable: br.connection.connectable !== false,
        label: "Conectar " + _titleize(connector),
        state: br.connection.state,
      };
      derived.readonly = false;
    } else {
      delete derived.connect; // el backend afirma que no necesita conexión (sin campo de llave)
    }
  }
  if (br.gate) derived.gate = { applicable: !!br.gate.gated, default: "needs_ok", level: br.gate.level || null };
  if (Array.isArray(br.params) && br.params.length) derived.params = (derived.params || []).concat(br.params);
  return derived;
}

/** Normaliza un átomo crudo de /v1/atoms/catalog a la forma que usan render+receta.
 *  `idx` da una key ÚNICA por chip (el backend trae ids duplicados: exa, calc). */
function normalizeAtom(a, idx) {
  const safeIdx = idx == null ? 0 : idx;
  const category = ZONE_CATEGORY[a.zone] || "process";
  const base = {
    key: `${a.id}#${safeIdx}`,        // identidad única de la pieza en la paleta/drag
    id: a.id,
    catalogKind: _kindForAtom(a),
    atom: a.atom || "tool",           // "tool" | "conexion"
    label: a.label || a.id,
    sub: a.sub || a.server || "",
    server: a.server || null,
    ref: a.server || null,            // server MCP = ref para /v1/tools/{ref}/handler
    tools: a.tools || [],
    belt_ref: a.belt_ref || null,
    zone: a.zone || "mesa",
    category,
    auth: a.auth || "keyless",        // keyless | token | personal_token | oauth
    connector: a.connector || null,   // nombre del conector (gmail, exa, …) o null
    armario: a.armario || null,       // apps | mundo | datos | archivos | saberes
    state: a.state || "ready",        // ready | connectable | connected | partial | local
    badge: a.badge || "",
    // DÓNDE CORRE, medido por el backend contra SU entorno (eje ortogonal a `auth`):
    // "server" = este backend puede lanzar el MCP · "local" = corre en la máquina del usuario.
    // `requires` dice QUÉ falta (Node.js, FreeCAD, un handler…) — es lo que la capa de guía
    // de onboarding usa para asistir a instalarlo. La pieza NUNCA se oculta por esto.
    runtime: a.runtime || "server",
    requires: a.requires || [],
    requiere_app: a.requiere_app || null,
    connectable: a.connectable,       // true/false (sólo conexiones)
    criticality: a.criticality || "low",  // low | high — high pide confirmación al SACARla en sesión activa
  };
  // C2: lo que el átomo DECLARA que necesita → arma su panel de Opciones.
  // Siempre derivamos el modelo interno; si el backend trae `requirements` (forma Stream B),
  // lo mapeamos ENCIMA (autoridad del backend para connection/gate/params).
  const derived = deriveRequirements(base);
  base.requirements = a.requirements ? _mergeBackendRequirements(derived, a.requirements) : derived;
  return _normalizeKind(base);
}

let _atomsCache = null;
let _capabilityCache = null;
let _dioramaServices = Object.create(null);
let _dioramaValid = new Set(["generico"]);
let _dioramaDefault = "generico";

/** Clasificación curada por identidad de servicio. Nunca inspecciona marcas ni nombres. */
export function dioramaSymbolFor(service, declared) {
  const curated = _dioramaServices[String(service || "").trim().toLowerCase()];
  if (_dioramaValid.has(curated)) return curated;
  const value = String(declared || "").trim().toLowerCase();
  return _dioramaValid.has(value) ? value : _dioramaDefault;
}

function _sessionHeaders() {
  const headers = { "Accept": "application/json" };
  try {
    const user = (window.AlephSession && window.AlephSession.get)
      ? window.AlephSession.get()
      : JSON.parse(sessionStorage.getItem("puppet_user") || localStorage.getItem("puppet_user") || "null");
    if (user && user.session_token)
      headers.Authorization = "Bearer " + user.session_token;
  } catch (_) { /* catálogo público; sin sesión no hay metadatos del llavero */ }
  return headers;
}

/** Carga (una vez) el catálogo real. Devuelve { list, byKey, total, by_zone }. */
export async function loadAtoms(opts = {}) {
  const userId = opts.userId || opts.user_id || null;
  const force = !!opts.force;
  if (_atomsCache && !force && _atomsCache.userId === userId) return _atomsCache;
  const qs = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  const r = await fetch("/v1/atoms/catalog" + qs);
  if (!r.ok) throw new Error(`/v1/atoms/catalog → ${r.status}`);
  const d = await r.json();
  const list = (d.atoms || []).map(normalizeAtom);
  const byKey = Object.fromEntries(list.map((a) => [a.key, a]));
  _atomsCache = { list, byKey, total: d.total != null ? d.total : list.length, by_zone: d.by_zone || {}, userId };
  return _atomsCache;
}

async function _loadConnectors() {
  const r = await fetch("/v1/connectors");
  if (!r.ok) throw new Error(`/v1/connectors → ${r.status}`);
  const d = await r.json();
  return d.connectors || [];
}

async function _loadConnectorEntities() {
  const [r, symbolsResponse] = await Promise.all([
    fetch("/v1/connector-entities", { headers: _sessionHeaders() }),
    fetch("/cuarto/diorama-symbols.json"),
  ]);
  if (!r.ok) throw new Error(`/v1/connector-entities → ${r.status}`);
  const data = await r.json();
  const manifest = symbolsResponse.ok
    ? await symbolsResponse.json().catch(() => ({})) : {};
  const valid = new Set(manifest.symbols || []);
  const fallback = valid.has(manifest.default) ? manifest.default : "generico";
  const services = manifest.services || {};
  _dioramaValid = valid.size ? valid : new Set(["generico"]);
  _dioramaDefault = fallback;
  _dioramaServices = Object.assign(Object.create(null), services);
  data.entities = (data.entities || []).map((entity) => {
    return Object.assign({}, entity, {
      diorama_symbol: dioramaSymbolFor(entity.id, entity.diorama_symbol),
    });
  });
  return data;
}

/** Entidad backend → pieza visible. Una pieza puede cargar N servers y N belt_refs;
 * `projection.js` conserva esa topología interna al equiparla. */
function _entityEntry(entity) {
  const credential = entity.credential || null;
  const servers = (entity.servers || []).map((server) => ({
    id: server.id,
    name: server.name,
    server: server.name,
    belt_ref: server.belt_ref,
    tools: (server.tools || []).slice(),
    tools_final: (server.tools_final || []).slice(),
    tool_aliases: Object.assign({}, server.tool_aliases || {}),
    connector: server.connector || null,
    credential_provider: server.credential_provider || null,
    credential_binding: server.credential_binding
      ? Object.assign({}, server.credential_binding) : null,
    origin: server.origin ? Object.assign({}, server.origin) : {},
    transport: server.transport || "stdio",
    state: server.state,
    runtime: server.runtime,
    requires: (server.requires || []).slice(),
    runtime_detail: server.runtime_detail || null,
    official: !!server.official,
  }));
  const zone = entity.zone || "mesa";
  const toolsDetail = (entity.tools || []).map((tool) => ({
    name: tool.name,
    rawName: tool.raw_name || tool.name,
    server: tool.server,
    frase: _humanTool(tool.name),
    connector: credential && credential.connector || null,
    auth: credential && credential.auth_method || "keyless",
    zone,
  }));
  const base = {
    key: `service:${entity.id}`,
    id: entity.id,
    service: entity.id,
    logo: entity.logo || entity.id,
    diorama_symbol: dioramaSymbolFor(entity.id, entity.diorama_symbol),
    catalogKind: credential ? "account_connector" : "public_mcp",
    label: entity.name || _titleize(entity.id),
    sub: entity.description || "",
    atom: credential ? "conexion" : "tool",
    zone,
    category: ZONE_CATEGORY[zone] || "process",
    auth: credential && credential.auth_method || "keyless",
    tools: toolsDetail.map((tool) => tool.name),
    toolsDetail,
    toolCount: Number(entity.tool_count != null ? entity.tool_count : toolsDetail.length),
    serverCount: servers.length,
    server: null,
    ref: null,
    servers,
    belt_refs: (entity.belt_refs || []).slice(),
    credential: credential ? Object.assign({}, credential) : null,
    connector: credential && (credential.connector || credential.provider) || null,
    connectors: credential
      ? Array.from(new Set([credential.provider, ...(credential.aliases || [])].filter(Boolean)))
      : [],
    armario: entity.armario || null,
    state: credential ? (credential.connected ? "connected" : "connectable") : "ready",
    badge: credential
      ? (credential.connected ? "Conectado" : "Conectar")
      : `${servers.length} servidor${servers.length === 1 ? "" : "es"}`,
    official: !!entity.official,
    criticality: entity.criticality || "low",
    migrationSources: (entity.source_entries || []).map((row) => Object.assign({}, row)),
  };
  base.requirements = deriveRequirements(base);
  return _normalizeKind(base);
}

/* Un conector sin ninguna card no trae NINGUNA tool: conectar la cuenta no le da al agente
 * ni una capacidad. Aparecía como pieza equipable igual que las demás — una promesa muda.
 * Se marca `sinTools` y la fila lo DICE; sigue alcanzable (conectar la cuenta sirve para el
 * resto de la app), pero deja de ofrecerse como si fuera capacidad. */
function _connectorEntry(c) {
  const name = c.connector || c.id || "";
  return _normalizeKind({
    sinTools: true,
    key: `connector:${name}`,
    id: name,
    catalogKind: "account_connector",
    label: _titleize(name),
    sub: c.capability_line || "",
    atom: "conexion",
    zone: "mesa",
    category: "process",
    auth: c.auth_method || "personal_token",
    tools: [],
    server: null,
    ref: null,
    connector: name,
    armario: "apps",
    state: "connectable",
    badge: c.auth_method === "oauth" ? "OAuth" : c.auth_method === "keyless" ? "Sin llave" : "API key",
    connectorOnly: true,
    needs_base_url: !!c.needs_base_url,
    tier: c.tier,
  });
}

/* ══ EL CATÁLOGO SON MCPs, NO TOOLS ══════════════════════════════════════════════════
 * Un belt declara CARDS; una card es un recorte de tools de UN server MCP. El catálogo
 * mostraba cards, así que el mismo MCP aparecía dos y cuatro veces ("Modelado CAD" y
 * "Automatizar FreeCAD" son el MISMO FreeCAD; los 4 de maritime, el mismo server). La
 * unidad visible pasa a ser el SERVER: una fila por MCP, y sus tools ANIDADAS adentro.
 *
 * Lo que la fusión NO hace: inventar. Cada tool conserva de qué card viene, con su auth,
 * su connector y su gate — que es exactamente lo que el widget del MCP tiene que mostrar.
 * El estado del MCP es el PEOR de sus cards (una llave que falta no se disimula con las
 * tools que sí corren).
 */
const _AUTH_RANK = { keyless: 0, token: 2, personal_token: 2, byok: 2, oauth: 3 };
const _STATE_RANK = { ready: 0, connected: 0, local: 1, partial: 2, connectable: 3 };

function _peor(list, rank, def) {
  let best = def, bestR = -1;
  list.forEach((v) => { const r = rank[v] != null ? rank[v] : 1; if (r > bestR) { bestR = r; best = v; } });
  return best;
}

/** Frase humana de una tool. Si su card declara UNA sola tool, la card ya la describe
 *  mejor que cualquier regex — se usa su `sub`. Si no, se desarma el nombre real. */
function _fraseTool(name, card) {
  if (card && (card.tools || []).length === 1 && card.sub) return card.sub;
  return _humanTool(name) || name;
}

export function foldAtomsToMcp(atoms) {
  const byServer = new Map();
  const sueltos = [];
  (atoms || []).forEach((a) => {
    const srv = a.server;
    if (!srv) { sueltos.push(a); return; }          // sin server no hay MCP que agrupar
    if (!byServer.has(srv)) byServer.set(srv, []);
    byServer.get(srv).push(a);
  });
  const out = [];
  byServer.forEach((cards, srv) => {
    const first = cards[0];
    const tools = [];
    const toolsDetail = [];
    const connectors = [];
    cards.forEach((c) => {
      (c.tools || []).forEach((t) => {
        if (tools.indexOf(t) !== -1) return;
        tools.push(t);
        toolsDetail.push({
          name: t, frase: _fraseTool(t, c),
          cardId: c.id, cardLabel: c.label,
          auth: c.auth || "keyless", connector: c.connector || null,
          gated: !!(c.requirements && c.requirements.gate && (c.requirements.gate.applicable || c.requirements.gate.gated)),
          zone: c.zone || "mesa",
        });
      });
      if (c.connector && connectors.indexOf(c.connector) === -1) connectors.push(c.connector);
    });
    const auth = _peor(cards.map((c) => c.auth || "keyless"), _AUTH_RANK, "keyless");
    const state = _peor(cards.map((c) => c.state || "ready"), _STATE_RANK, "ready");
    const conexionish = cards.some((c) => c.atom === "conexion");
    // la card que MANDA para auth/connector/requirements: la primera que pide credencial
    const rectora = cards.find((c) => (c.auth || "keyless") !== "keyless") || first;
    const entry = Object.assign({}, rectora, {
      key: "mcp:" + srv,
      id: rectora.id || srv,
      mcp: srv,
      // 1 card → su etiqueta (describe mejor). >1 → el MCP, que es lo que las une.
      label: cards.length === 1 ? (first.label || _titleize(srv)) : _titleize(srv),
      sub: cards.length === 1 ? (first.sub || srv) : cards.map((c) => c.label).filter(Boolean).join(" · "),
      server: srv, ref: srv,
      atom: conexionish ? "conexion" : "tool",
      auth, state,
      connector: rectora.connector || connectors[0] || null,
      connectors,
      tools, toolsDetail,
      cards: cards.map((c) => ({ id: c.id, label: c.label, sub: c.sub, tools: (c.tools || []).slice(), auth: c.auth, connector: c.connector })),
      cardCount: cards.length,
      criticality: cards.some((c) => c.criticality === "high") ? "high" : "low",
    });
    out.push(_normalizeKind(entry));
  });
  return out.concat(sueltos);
}

/** Une las fuentes ya existentes bajo un contrato visual único.
 *  - atoms: /v1/atoms/catalog (MCPs públicos + piezas que requieren cuenta)
 *  - built-ins: piezas nativas del Cuarto
 *  - connectors: /v1/connectors, sólo cuando no existe ya una pieza del catálogo para ese conector
 */
export async function loadCapabilityCatalog(opts = {}) {
  const userId = opts.userId || opts.user_id || null;
  const force = !!opts.force;
  if (_capabilityCache && !force && _capabilityCache.userId === userId) return _capabilityCache;

  const atoms = await loadAtoms({ userId, force });
  let connectors = [];
  let entityData = null;
  try { connectors = await _loadConnectors(); } catch (e) { connectors = []; }
  try { entityData = await _loadConnectorEntities(); } catch (e) { entityData = null; }

  const builtins = BUILTIN_CATALOG_ENTRIES.map((e) => _normalizeKind({ ...e }));
  const nativas = atoms.list.filter(esNativa);
  let entities = [];
  let connectorOnly = [];
  let mcps = [];
  if (entityData && Array.isArray(entityData.entities)) {
    // Modelo nuevo: un SERVICIO por pieza. Las credenciales sin tools quedan como
    // perfiles internos/dormidos; jamás reaparecen como piezas APPS de 0 tools.
    entities = entityData.entities.map(_entityEntry);
  } else {
    // Fallback fail-visible para un backend anterior durante rolling upgrade. No es la
    // ruta del frozen certificado, pero conserva una vitrina utilizable.
    const usedConnectors = new Set(atoms.list.map((a) => a.connector).filter(Boolean));
    connectorOnly = connectors
      .filter((c) => c && c.connector && !usedConnectors.has(c.connector))
      .map(_connectorEntry);
    mcps = foldAtomsToMcp(atoms.list.filter((a) => !esNativa(a)));
  }
  const entries = entityData
    ? [...builtins, ...entities]
    : [...builtins, ...mcps, ...connectorOnly];
  const byKey = Object.fromEntries(entries.map((e) => [e.key, e]));
  const byKind = entries.reduce((acc, e) => {
    acc[e.catalogKind] = (acc[e.catalogKind] || 0) + 1;
    return acc;
  }, {});

  _capabilityCache = {
    entries, byKey, byKind,
    atoms,
    connectors,
    nativas,                       // capacidad del modelo — se declara, no se equipa
    mcpCount: entityData
      ? entities.reduce((n, entity) => n + (entity.servers || []).length, 0)
      : mcps.length,
    entityCount: entities.length,
    migration: entityData && entityData.migration || null,
    credentialProfiles: entityData && entityData.credential_profiles || null,
    cardCount: atoms.list.length,
    sinTools: connectorOnly.length,
    total: entries.length,
    userId,
  };
  return _capabilityCache;
}

/** MIGRACIÓN de recetas guardadas al modelo por-MCP. Una receta vieja podía tener DOS
 *  bloques del mismo server (una card por tool-group: cad-freecad + cad-script). Con el
 *  catálogo por MCP eso son dos piezas idénticas en el piso. Se pliegan a UNA con la unión
 *  de sus tools; las NATIVAS se retiran (el modelo ya las hace). Nada más se toca: ids,
 *  posiciones y el resto de los bloques quedan como estaban, así el save/load no se rompe.
 *  Devuelve {blocks, plegados, nativas} para poder DECIR cuántas se migraron. */
export function migrarBloquesAMcp(blocks) {
  const out = [];
  const porServer = new Map();
  let plegados = 0, nativas = 0;
  (blocks || []).forEach((b) => {
    // Entidad Conector: varios bloques legacy pueden rehidratar al MISMO servicio.
    // Queda una pieza, ya cargada con todos sus servidores por recipeToCanvas.
    if (b && b.service) {
      const key = "service:" + b.service;
      const prevEntity = porServer.get(key);
      if (!prevEntity) { porServer.set(key, b); out.push(b); return; }
      plegados++;
      return;
    }
    const esTool = !b.nucleo && !b.agent_ref && (b.atom === "tool" || b.atom === "conexion" || b.atom == null);
    const srv = b.ref || b.server;
    if (!esTool || !srv) { out.push(b); return; }
    if (NATIVE_SERVERS.has(srv)) { nativas++; return; }          // capacidad nativa → fuera del piso
    const prev = porServer.get(srv);
    if (!prev) { porServer.set(srv, b); out.push(b); return; }
    const u = (prev.tools || []).slice();
    (b.tools || []).forEach((t) => { if (u.indexOf(t) === -1) u.push(t); });
    prev.tools = u;
    plegados++;
  });
  return { blocks: out, plegados, nativas };
}

export function catalogEntryMatches(entry, opts = {}) {
  if (!entry) return false;
  const kind = opts.kind || "";
  const zone = opts.zone || "";
  const type = opts.type || "";
  const key = opts.key || "";
  const q = (opts.q || "").trim().toLowerCase();
  if (kind && entry.catalogKind !== kind) return false;
  if (zone && entry.zone !== zone) return false;
  if (type && entry.atom !== type) return false;
  const needsKey = entry.auth !== "keyless";
  if (key === "free" && needsKey) return false;
  if (key === "key" && !needsKey) return false;
  if (q && !(entry.searchText || "").includes(q)) return false;
  return true;
}

/** BÚSQUEDA POR TEXTO que encuentra por nombre de TOOL y revela el MCP padre.
 *  Devuelve, por entrada que matchea, qué tools la hicieron matchear — para que la fila se
 *  abra ya mostrando la tool encontrada en vez de dejar al usuario adivinar por qué salió. */
export function buscarEnCatalogo(entries, q) {
  const s = String(q || "").trim().toLowerCase();
  if (!s) return (entries || []).map((e) => ({ entry: e, tools: [], porTool: false }));
  const out = [];
  (entries || []).forEach((e) => {
    const tools = (e.toolsDetail || (e.tools || []).map((t) => ({ name: t, frase: t })))
      .filter((t) => String(t.name || "").toLowerCase().includes(s) ||
                     String(t.frase || "").toLowerCase().includes(s));
    const propio = [e.label, e.sub, e.server, e.connector, e.armario]
      .filter(Boolean).join(" ").toLowerCase().includes(s);
    if (!tools.length && !propio && !(e.searchText || "").includes(s)) return;
    out.push({ entry: e, tools, porTool: !propio && tools.length > 0 });
  });
  return out;
}

export function tileFromCatalogEntry(entry) {
  if (!entry || entry.connectorOnly) return null;
  return {
    id: entry.id,
    key: entry.key,
    label: entry.label,
    category: entry.category,
    atom: entry.atom,
    server: entry.server,
    ref: entry.ref || entry.server || null,
    tools: (entry.tools || []).slice(),
    belt_ref: entry.belt_ref || null,
    connector: entry.connector || null,
    auth: entry.auth || "keyless",
    sub: entry.sub || "",
    state: entry.state || "ready",
    connectable: entry.connectable,
    armario: entry.armario || null,
    requirements: entry.requirements,
    catalogKind: entry.catalogKind,
    criticality: entry.criticality || "low",
    // la pieza VIAJA con el detalle de sus tools y sus conectores: es lo que el widget del
    // MCP muestra y lo que la proyección necesita para no perder una segunda credencial.
    toolsDetail: (entry.toolsDetail || []).map((t) => Object.assign({}, t)),
    connectors: (entry.connectors || []).slice(),
    mcp: entry.mcp || entry.server || null,
    cards: (entry.cards || []).map((c) => Object.assign({}, c)),
    service: entry.service || null,
    logo: entry.logo || entry.service || null,
    diorama_symbol: dioramaSymbolFor(entry.service || entry.id, entry.diorama_symbol),
    servers: (entry.servers || []).map((server) => JSON.parse(JSON.stringify(server))),
    belt_refs: (entry.belt_refs || []).slice(),
    credential: entry.credential ? JSON.parse(JSON.stringify(entry.credential)) : null,
    toolCount: entry.toolCount != null ? entry.toolCount : (entry.tools || []).length,
    serverCount: entry.serverCount != null ? entry.serverCount : (entry.servers || []).length,
  };
}

export function resetCatalogCaches() {
  _atomsCache = null;
  _capabilityCache = null;
}

export { normalizeAtom, deriveRequirements, ZONE_CATEGORY };

// global para superficies no-module (varas, El Guía, el chat)
if (typeof window !== "undefined") {
  window.CuartoCatalogo = { foldAtomsToMcp, migrarBloquesAMcp, buscarEnCatalogo, esNativa,
                            NATIVE_SERVERS };
}
