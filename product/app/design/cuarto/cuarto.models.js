/* cuarto.models.js — el PICKER de modelo del agente (el modelo del núcleo).
 *
 * El picker es del frontend; la DISPONIBILIDAD la manda el backend. Hoy no existe
 * GET /v1/models en :8080, así que: `loadModels()` lo INTENTA y, si no está, cae a la
 * lista CURADA (los aliases reales de platform/assembler/models.py). Cuando Stream C
 * agregue /v1/models con {id,label,available,...}, este front lo consume sin tocar nada
 * (mismo patrón que `requirements`). Ver MODELS-CONTRACT.md.
 *
 * Honestidad de disponibilidad (no mentir): la ruta incluida/hosted se verifica por el
 * backend; los de Groq/Gemini REQUIEREN key; el local (ollama) necesita ollama corriendo.
 */

// lista CURADA = los aliases reales de models.py (alias → modelo/endpoint/requisito)
const CURATED = [
  { id: "byok", alias: "byok", label: "Tu API", tier: "API propia",
    model: "", base_url: "", fallbackModel: null, need: "byok", hidden: true,
    hint: "configura proveedor y modelo antes de usarlo" },
  { id: "opus", alias: "brain", label: "Opus 4.8", tier: "Modelo premium",
    model: "anthropic/claude-opus-4.8", base_url: "https://openrouter.ai/api/v1", fallbackModel: "openai/gpt-oss-120b",
    need: "included", hint: "El más capaz · ruta incluida/hosted de Aleph · disponibilidad verificada en este runtime" },
  { id: "oss", alias: "oss", label: "GPT-OSS 120B", tier: "Rápido y barato",
    model: "openai/gpt-oss-120b", base_url: "https://api.groq.com/openai/v1", fallbackModel: "llama-3.3-70b-versatile",
    need: "key:GROQ", hint: "Groq · músculo barato que completa e2e · requiere GROQ key" },
  { id: "llama70", alias: "premium", label: "Llama 3.3 70B", tier: "Equilibrado",
    model: "llama-3.3-70b-versatile", base_url: "https://api.groq.com/openai/v1", fallbackModel: "openai/gpt-oss-20b",
    need: "key:GROQ", hint: "Groq · requiere GROQ key" },
  { id: "qwen32", alias: "explorer-reason", label: "Qwen3 32B", tier: "Razonador",
    model: "qwen/qwen3-32b", base_url: "https://api.groq.com/openai/v1", fallbackModel: "llama-3.3-70b-versatile",
    need: "key:GROQ", hint: "Groq · razona <think> para tareas abiertas · requiere GROQ key" },
  { id: "qwen-local", alias: "oss-direct", label: "Qwen3 8B", tier: "Local · $0",
    model: "qwen3:8b", base_url: "http://127.0.0.1:11434/v1", fallbackModel: null,
    need: "local", hint: "ollama local · $0 marginal · requiere ollama corriendo" },
  { id: "gemini", alias: "vision", label: "Gemini Flash", tier: "Visión",
    model: "gemini-2.5-flash", base_url: "https://generativelanguage.googleapis.com/v1beta/openai", fallbackModel: null,
    need: "key:GEMINI", hint: "Gemini · multimodal (imágenes) · requiere GEMINI key" },
  // BYO-CLI (D3) — el CLI local del usuario como modelo por SUSCRIPCIÓN (no API key).
  // Vivo/apagado lo decide GET /v1/brains/status (detección real, jamás fingida);
  // brainProvider viaja a recipe.model.brain_provider y el backend rutea al server :8926.
];
const FALLBACK_CLI = [ /* E1-FALLBACK sidecar viejo */
  { id: "claude_cli", alias: "claude_cli", label: "Mi Claude Code", tier: "Tu suscripción",
    model: "claude-code-cli", base_url: "http://127.0.0.1:8926/v1", fallbackModel: null,
    need: "cli", brainProvider: "claude_cli",
    hint: "tu Claude Code local piensa por tu suscripción · $0 API" },
  { id: "codex_cli", alias: "codex_cli", label: "Mi Codex", tier: "Tu suscripción",
    model: "codex-cli", base_url: "http://127.0.0.1:8926/v1", fallbackModel: null,
    need: "cli", brainProvider: "codex_cli",
    hint: "tu Codex local piensa por tu suscripción · $0 API" },
];
function cliRowsFromCatalog(catalog) {
  if (!catalog || !catalog.length) return FALLBACK_CLI.map((r) => ({ ...r }));
  return catalog.map((c) => ({
    id: c.provider_id, alias: c.provider_id, label: c.picker_label || c.display_name,
    tier: c.tier || "Tu suscripción",
    model: c.response_model_id,
    base_url: "http://127.0.0.1:8926/v1", fallbackModel: null,
    need: "cli", brainProvider: c.provider_id,
    hint: c.picker_hint || "",
    loginNoAuth: c.login_no_auth, loginNotInstalled: c.login_not_installed,
  }));
}
function applyCliRows(catalog) {
  const cli = cliRowsFromCatalog(catalog);
  let i = CURATED.length;
  while (i--) {
    if (CURATED[i].need === "cli") CURATED.splice(i, 1);
  }
  CURATED.push(...cli);
  if (catalog && catalog.length) {
    const next = {};
    catalog.forEach((c) => {
      if (c.submodels) next[c.provider_id] = c.submodels;
    });
    Object.keys(CLI_SUBMODELS).forEach((k) => { delete CLI_SUBMODELS[k]; });
    Object.assign(CLI_SUBMODELS, next);
  }
}

// etiqueta de disponibilidad HONESTA (no asevera lo que no puedo verificar desde el browser)
function availOf(need) {
  if (need === "included") return { kind: "unknown", text: "verificando ruta incluida…" };
  if (need === "local") return { kind: "local", text: "local · $0 (ollama)" };
  if (need === "cli") return { kind: "unknown", text: "verificando…" }; // lo pisa el status real
  if (need && need.startsWith("key:")) return { kind: "key", text: "requiere " + need.slice(4) + " key" };
  return { kind: "unknown", text: "se confirma al correr" };
}

// ── BYO-CLI (D2→D3) · detección honesta de los CLIs del usuario ──────────────────
// GET /v1/brains/status → {providers:{claude_cli:{state,detail,...}, codex_cli:{...}}}.
// Cada provider trae SU estado real e independiente (los estados no se contagian).
// Si el fetch falla, devolvemos null y el picker dice "no pude verificar". Si el backend
// sí confirma que el runtime :8926 está caído, la opción se apaga: no hay ruta ejecutable.
let _brainStatus = null, _brainStatusAt = 0, _brainRuntime = null;
const BRAIN_STATUS_URL = "/v1/brains/status", BRAIN_STATUS_TTL_MS = 15000;
export async function loadBrainStatus() {
  if (_brainStatus && Date.now() - _brainStatusAt < BRAIN_STATUS_TTL_MS) return _brainStatus;
  try {
    const r = await fetch(BRAIN_STATUS_URL);
    if (r.ok) {
      const d = await r.json();
      if (d && d.providers && Object.keys(d.providers).length) {
        _brainRuntime = d.service || null;
        _brainStatus = d.providers; _brainStatusAt = Date.now();
        if (d.catalog) {
          applyCliRows(d.catalog);
          if (window.AlephBrain && window.AlephBrain.applyCliCatalog) {
            window.AlephBrain.applyCliCatalog(d.catalog);
          }
        }
        return _brainStatus;
      }
    }
  } catch (e) { /* backend sin endpoint / caído → null honesto */ }
  _brainRuntime = null;
  return null;
}

// Anota las entradas CLI de la lista con el estado real: viva (ready) o APAGADA con
// razón honesta + guía (patrón 🔒 del territorio de la Sala — jamás fabrica capacidad).
function _annotateBrains(list, providers, runtime) {
  for (const m of list) {
    if (m.need === "included") {
      const inc = providers && providers.included;
      if (!inc) {
        m.locked = false;
        m.avail = { kind: "unknown", text: "no pude verificar la ruta incluida" };
      } else if (inc.state === "ready") {
        m.locked = false;
        m.avail = { kind: "ok", text: "lista · ruta incluida saludable" };
      } else if (inc.state === "not_configured" || inc.state === "unavailable") {
        m.locked = true;
        m.lockReason = inc.detail || "La ruta incluida no está configurada en este runtime.";
        m.avail = { kind: "lock", text: "no disponible 🔒" };
      } else {
        m.locked = false;
        m.avail = { kind: "unknown", text: "ruta incluida sin verificación" };
      }
      continue;
    }
    if (!m.brainProvider) continue;
    if (runtime && runtime.state !== "ready") {
      m.locked = true;
      m.lockReason = runtime.detail || "El servicio local de Claude Code/Codex no está disponible.";
      m.avail = { kind: "lock", text: "servicio local no disponible 🔒" };
      continue;
    }
    const st = providers && providers[m.brainProvider];
    if (!st) {
      m.locked = false;
      m.avail = { kind: "unknown", text: "no pude verificar · se confirma al correr" };
      continue;
    }
    if (st.state === "ready") {
      m.locked = false;
      const sub = (st.extra || {}).subscriptionType;
      m.avail = st.access_state === "allowed"
        ? { kind: "ok", text: "listo · " + (sub ? "plan " + sub : "acceso verificado") }
        : { kind: "unknown", text: "sesión activa · acceso sin probar" };
    } else if (st.state === "access_denied") {
      m.locked = true;
      m.lockReason = st.detail || "La cuenta está autenticada, pero el proveedor denegó el acceso.";
      m.avail = { kind: "lock", text: "acceso del proveedor denegado 🔒" };
    } else if (st.state === "no_auth") {
      m.locked = true;
      m.lockReason = "Está instalado pero sin sesión. " +
        (m.loginNoAuth || (m.brainProvider === "claude_cli"
          ? "Abre una terminal y corre `claude` para loguearte."
          : "Abre una terminal y corre `codex login`."));
      m.avail = { kind: "lock", text: "sin sesión 🔒" };
    } else if (st.state === "auth_expired") {
      m.locked = true;
      m.lockReason = st.detail || "La sesión de Claude Code venció. Ejecuta `claude auth login` y luego pulsa Revisar sesión en Modelos.";
      m.avail = { kind: "lock", text: "sesión vencida 🔒" };
    } else if (st.state === "not_installed") {
      m.locked = true;
      m.lockReason = "No encontré el CLI en esta máquina. " +
        (m.loginNotInstalled || (m.brainProvider === "claude_cli"
          ? "Instala Claude Code (claude.com/code) e inicia sesión."
          : "Instala Codex (npm i -g @openai/codex) y corre `codex login`."));
      m.avail = { kind: "lock", text: "no instalado 🔒" };
    } else {
      m.locked = true;
      m.lockReason = st.detail || "No pude verificar la autenticación del CLI.";
      m.avail = { kind: "unknown", text: st.state === "config_invalid"
        ? "configuración inválida" : "autenticación sin verificar" };
    }
  }
}

let _cache = null;
let _baseList = null;   // la lista base (curada/backend) — se construye UNA vez
let _baseSource = "curated";
let _selectorData = Object.create(null), _selectorContext = "default", _selectorTodos = false;

// Normaliza la respuesta del backend (forma del MODELS-CONTRACT) a la del picker.
function _fromBackend(raw) {
  return raw.map((m) => ({ ...m, id: m.id || m.alias, label: m.label || m.model || m.id,
    avail: m.available != null
      ? { kind: m.available ? "ok" : "key", text: m.availability || (m.available ? "disponible" : "no disponible") }
      : availOf(m.need) }));
}

// `todos` pide el CATÁLOGO (lo configurado + lo que falta configurar, con su trámite) en
// vez del POOL (lo usable ahora). Son dos payloads distintos y el componente compartido los
// cachea por separado a propósito — ver `_claveSel` en brain-status.js. Acá el cache local
// hace lo mismo: si el taller pide `todos` y la Sala lee después, la Sala tiene que seguir
// viendo su pool.
function _claveCtx(contexto, todos) { return String(contexto) + (todos ? "::todos" : ""); }

async function _loadSelector(contexto, refresh, todos = false) {
  const clave = _claveCtx(contexto, todos);
  try {
    const api = window.AlephModelSelector;
    // [TANDA 1 · obra 1] SIN `contexto` — mismo motivo que `brain-status.js::selectorLoad`:
    // el cerebro es uno solo y `?contexto=` haría que el respaldo (cuando el componente
    // compartido no está montado) resolviera un `contextos[...]` viejo en vez del `default`.
    const q = todos ? "?todos=1" : "";
    const data = api && api.load
      ? await api.load(contexto, refresh, todos)
      : await fetch("/v1/modelos/selector" + q)
          .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
    if (data && Array.isArray(data.modelos)) {
      _selectorData[clave] = data;
      _selectorContext = contexto;
      _selectorTodos = todos;
      if (api && api.seed) api.seed(data, contexto, todos);
      return data;
    }
  } catch (e) { /* sidecar anterior/caído: el componente compartido hará fail-closed */ }
  return null;
}

// El sidecar manda la configuración ejecutable: el cliente no mantiene una segunda tabla
// de providers. Sólo enriquecemos las filas con copy/controles ya conocidos por el Cuarto.
/** Por qué esta fila no se puede usar, con el copy del diccionario ÚNICO.
 *
 *  Regla sellada: ninguna causa llega a una superficie sin copy, y jamás el nombre técnico.
 *  `r.causa` viene del backend como slug (`falta_key`, `key_invalida`…); pintarlo crudo es
 *  exactamente lo que la regla prohíbe — y es lo que esta función hacía.
 */
function _porQueNo(r, data) {
  const S = window.CuartoSemaforo;
  if (S && r.causa) {
    const cara = S.caraDeCausa({ causa: r.causa, detalle: r.detalle || "" });
    if (cara) return cara.texto || cara.titulo;
  }
  if (S && r.estado === "no_configurado") return "Todavía no lo configuraste.";
  if (S && r.estado === "detectado") return "Tiene llave, pero nadie la probó todavía.";
  if (r.slug === data.default) return "El Default está caído; reconéctalo antes de usarlo.";
  return "No está conectado.";
}

function _candadoDe(r) {
  const S = window.CuartoSemaforo;
  const meta = S && (S.ESTADOS || {})[String(r.estado || "")];
  return meta ? meta.emoji + " " + meta.es : "no disponible 🔒";
}

function _mergeSelector(base, data, todos = false) {
  // El catálogo curado no prueba conexión. Sin contrato V2 el selector queda vacío y
  // ofrece [+ Modelos]; jamás transforma todas las entradas históricas en «Conectados».
  //
  // `todos` NO afloja eso: las filas extra que deja pasar son las que el SIDECAR declaró
  // no configuradas, y siguen llegando con `conectado:false` y su candado. Lo que cambia es
  // que ahora se ven — un picker de CONFIGURACIÓN necesita mostrar lo que falta configurar,
  // porque si no, no hay dónde poner la llave.
  if (!data || !Array.isArray(data.modelos)) return [];
  const byId = Object.fromEntries(base.map((m) => [m.id, m]));
  return data.modelos
    .filter((r) => r && (todos || r.conectado === true || r.default === true || r.slug === data.default))
    .map((r) => {
      const id = r.picker_id || r.id || r.slug;
      const known = byId[id] || {};
      const connected = r.conectado === true;
      return {
        ...known, ...r, id,
        label: r.label || known.label || id,
        tier: r.tier || known.tier || "",
        hint: r.sub || known.hint || "",
        brainProvider: r.brain_provider || known.brainProvider,
        byok_ref: r.byok_ref || known.byok_ref,
        connected, conectado: connected,
        default: r.default === true || r.slug === data.default,
        locked: !connected,
        // ⚠️ Este copy se escribió cuando la ÚNICA fila no conectada posible era el Default
        // caído. Con `todos` ya no: la mayoría son modelos que nunca se configuraron, y
        // decirles «el Default está caído» es mandar a arreglar algo que no está roto.
        // El copy sale del diccionario único (`window.CuartoSemaforo`), y sólo se cae al
        // texto viejo cuando la fila ES el Default y no trae ni causa ni estado.
        lockReason: connected ? "" : _porQueNo(r, data),
        avail: connected
          ? { kind: "ok", text: "conectado" }
          : { kind: "lock", text: _candadoDe(r) },
      };
    });
}

/** Devuelve { list, byId, source }.
 *  Hoy NO existe GET /v1/models en :8080 → uso la lista CURADA (aliases reales de models.py),
 *  sin fetch especulativo (no ensucio la consola con un 404). Cuando Stream C exponga el
 *  endpoint (MODELS-CONTRACT.md), basta apuntar BACKEND_MODELS_URL para adoptarlo en vivo. */
const BACKEND_MODELS_URL = ""; // ej. "/v1/models" cuando exista — vacío = curado, sin probe
// `refreshBrains:true` (o forzado por el TTL) re-consulta /v1/brains/status y RE-ANOTA la lista
// CLI en el lugar — así el candado 🔒 se actualiza cuando el usuario se loguea sin recargar la
// página (review LOW #22: antes el _cache congelaba la anotación y el TTL era código muerto).
export async function loadModels({ refreshBrains = false, contexto = "default",
                                  todos = false } = {}) {
  if (refreshBrains) { _brainStatus = null; _brainStatusAt = 0; _brainRuntime = null; }
  if (!_baseList) {
    let list = null;
    if (BACKEND_MODELS_URL) {
      try {
        const r = await fetch(BACKEND_MODELS_URL);
        if (r.ok) { const d = await r.json(); const raw = d.models || d.data || d.list;
          if (Array.isArray(raw) && raw.length) { list = _fromBackend(raw); _baseSource = "backend"; } }
      } catch (e) { /* cae a curado */ }
    }
    if (!list) list = CURATED.map((m) => ({ ...m, avail: availOf(m.need) }));
    _baseList = list;
  }
  // Status y pool se leen en paralelo. El pool es la ley del selector: conectados+Default.
  const [providers, selector] = await Promise.all([
    loadBrainStatus(), _loadSelector(contexto, refreshBrains, todos),
  ]);
  _annotateBrains(_baseList, providers, _brainRuntime);
  const guardado = _selectorData[_claveCtx(contexto, todos)];
  const live = _mergeSelector(_baseList, selector || guardado, todos);
  _cache = {
    list: live,
    byId: Object.fromEntries(live.map((m) => [m.id, m])),
    source: selector
      ? (todos ? "sidecar · catálogo completo" : "sidecar · conectados+Default")
      : _baseSource,
    selector: selector || guardado || null,
    contexto,
    todos,
  };
  return _cache;
}

/** Re-consulta la detección BYO-CLI y re-anota la lista viva. Devuelve true si algún estado
 *  CLI cambió (para que el caller re-renderice el picker). Barato (fetch + anotación en sitio). */
export async function refreshBrains() {
  if (!_baseList) { await loadModels(); return true; }
  const before = _baseList.filter((m) => m.brainProvider).map((m) => m.brainProvider + ":" + (m.locked ? 1 : 0) + ":" + (m.avail || {}).text).join("|");
  _brainStatus = null; _brainStatusAt = 0; _brainRuntime = null;
  const [providers, selector] = await Promise.all([
    loadBrainStatus(), _loadSelector(_selectorContext, true, _selectorTodos),
  ]);
  _annotateBrains(_baseList, providers, _brainRuntime);
  const guardado = _selectorData[_claveCtx(_selectorContext, _selectorTodos)];
  const live = _mergeSelector(_baseList, selector || guardado, _selectorTodos);
  _cache = {
    list: live,
    byId: Object.fromEntries(live.map((m) => [m.id, m])),
    source: selector
      ? (_selectorTodos ? "sidecar · catálogo completo" : "sidecar · conectados+Default")
      : _baseSource,
    selector: selector || guardado || null,
    contexto: _selectorContext,
    todos: _selectorTodos,
  };
  const after = _baseList.filter((m) => m.brainProvider).map((m) => m.brainProvider + ":" + (m.locked ? 1 : 0) + ":" + (m.avail || {}).text).join("|");
  return before !== after;
}

/** Compila la elección de modelo a la forma PLANA que el validador exige (+ alias portable). */
export function compileModel(id, opts = {}) {
  const byId = (_cache && _cache.byId) || Object.fromEntries(CURATED.map((m) => [m.id, m]));
  const byok = opts.byok || null;
  if (id === "byok" && byok && byok.provider && byok.model && (byok.baseUrl || byok.base_url)) {
    /* ⚠️ ACÁ IBA `alias: "byok"`, Y ESO ROMPÍA EL TURNO.
     *
     * `byok` es el id de la LANE CURADA (el vocabulario de este módulo), NO un alias del
     * registro: `platform/assembler/models.py` no lo tiene como entrada, y su propio
     * docstring lo dice — «byok/managed son DECLARATIVOS (el ruteo sigue por byok_ref)».
     *
     * Pero `resolve_recipe_model` aplica la precedencia SELLADA de 1-línea:
     *
     *     env PUPPET_BRAIN  >  model.alias  >  model.primary + model.base_url
     *
     * así que `alias:"byok"` le GANABA al `primary` correcto de acá arriba, y `byok` salía
     * al cable como nombre de modelo. MEDIDO sobre la instalada, eligiendo OpenRouter en el
     * panel de La Sala:
     *
     *     model_route: [{"model":"byok", ok:false, error:"HTTP 400",
     *                    causa:"El proveedor rechazó el pedido (BadRequestError)"}]
     *     tool_calls: 0 · model_final: null · usage 0/0/0 · answer ""
     *
     * Discriminante: la MISMA receta con `alias:null` corre y llama tools.
     *
     * SE ARREGLA ACÁ Y NO EN EL EJECUTOR a propósito: la precedencia es de Gate 2 y está
     * sellada; hacerla condicional («salvo que haya byok_ref») le agrega un caso especial a
     * una regla de una línea y crea dos comportamientos. El dato equivocado entra ACÁ.
     * Nadie lee `alias === "byok"` —ni el frente ni el backend, verificado—, así que quitarlo
     * no le saca nada a nadie: la identidad de la lane ya viaja en `byok_ref`, que es el
     * campo AUTORITATIVO (el mismo que usa `curadoDesdeFila`). */
    return {
      primary: String(byok.model),
      fallback: null,
      base_url: String(byok.baseUrl || byok.base_url),
      temperature: opts.temperature != null ? opts.temperature : 0,
      max_tokens: opts.max_tokens || 700,
      max_turns: opts.max_turns || 8,
      alias: null,
      byok_ref: "keys:" + String(byok.provider).toLowerCase(),
    };
  }
  const m = byId[id] || Object.values(byId)[0];
  if (!m) throw new Error("No hay un modelo conectado para compilar");
  return {
    primary: m.model,
    // BYO-CLI: sin fallback horneado (null) — si la ventana de la suscripción se agota,
    // actúa la red de seguridad del runtime (oss-direct) y la caída se NARRA. El resto
    // conserva el default histórico byte-idéntico.
    fallback: m.brainProvider ? (m.fallbackModel || null) : (m.fallbackModel || "openai/gpt-oss-20b"),
    base_url: m.base_url,
    temperature: opts.temperature != null ? opts.temperature : 0,
    max_tokens: opts.max_tokens || 700,
    max_turns: opts.max_turns || 8,
    alias: m.alias || null, // portable: el backend puede re-resolver por alias si prefiere
    // API/local dinámicos vienen del sidecar; la referencia de llave nunca se hornea acá.
    ...(m.byok_ref ? { byok_ref: m.byok_ref } : {}),
    // BYO-CLI (aditivo): el provider DECLARADO viaja en la receta → badge 4B + ruteo.
    ...(m.brainProvider ? { brain_provider: m.brainProvider } : {}),
    // ANNEX · SUB-MODELO POR PROVIDER: el sub-modelo pedido DENTRO del provider (ej. Mi Claude
    // Code → sonnet) sólo tiene sentido en un provider CLI; en el resto se OMITE → byte-idéntico.
    // Es un PEDIDO: el hecho (model_final) lo reporta el CLI en el run. Vacío = default del plan.
    ...(m.brainProvider && opts.cli_model ? { cli_model: String(opts.cli_model) } : {}),
    // TICKET 27·3 · DIAL DE ESFUERZO: el effort elegido (low/medium/high/max/auto) viaja a
    // recipe.model.effort; el assembler lo baja al CLI (--effort). Vacío = default del CLI.
    ...(m.brainProvider && opts.effort ? { effort: String(opts.effort) } : {}),
  };
}

/** Reverse-map a saved recipe to the human model id used by both Cuarto and Sala. */
export function modelIdForRecipe(recipe) {
  recipe = recipe || {};
  const model = recipe.model || {};
  const list = (_cache && _cache.list) || CURATED;
  const nucleus = recipe.canvas && recipe.canvas.nucleos && recipe.canvas.nucleos[0];
  const canvasId = nucleus && nucleus.model;
  if (model.byok_ref) {
    const exactByok = list.find((m) => m.byok_ref === model.byok_ref &&
      (!model.primary || m.model === model.primary));
    if (exactByok) return exactByok.id;
    return "byok";
  }
  if (model.brain_provider) {
    const byProvider = list.find((m) => m.brainProvider === model.brain_provider);
    if (byProvider) return byProvider.id;
  }
  if (model.alias) {
    const byAlias = list.find((m) => m.alias === model.alias || m.id === model.alias);
    if (byAlias) return byAlias.id;
  }
  const byExact = list.find((m) => m.model === model.primary && m.base_url === model.base_url);
  if (byExact) return byExact.id;
  const byPrimary = list.find((m) => m.model === model.primary);
  if (byPrimary) return byPrimary.id;
  return !model.primary && canvasId && list.some((m) => m.id === canvasId) ? canvasId : null;
}

// ANNEX · SUB-MODELO POR PROVIDER (BYO-CLI) · catálogo HONESTO por provider. El id viaja LITERAL
// al flag del CLI (`claude --model X` / `codex -m X`, ver cli_brain/*_cli.py build_argv); "" = sin
// flag = default del plan (claude→opus · codex→gpt-5.1-codex-max). Ofrecer un sub-modelo NO promete
// que el plan lo cubra: si no, el server :8926 devuelve error CLASIFICADO (jamás un falso verde).
const CLI_SUBMODELS = { /* E1-FALLBACK; catalog overwrite via applyCliRows */
  claude_cli: [
    { id: "", label: "Default del plan (Opus)" },
    { id: "sonnet", label: "Sonnet" },
    { id: "opus", label: "Opus" },
    { id: "haiku", label: "Haiku" },
  ],
  codex_cli: [
    { id: "", label: "Default del plan" },
    { id: "gpt-5.1-codex-max", label: "GPT-5.1 Codex Max" },
    { id: "gpt-5.1-codex", label: "GPT-5.1 Codex" },
    { id: "o4-mini", label: "o4-mini" },
  ],
};
applyCliRows(null);

/** Sub-modelos ofrecibles para una entrada del picker. Vacío ([]) si NO es un provider CLI
 *  (los modelos por API key NO exponen sub-modelo: el `model` ya es exacto). */
export function cliSubmodels(id) {
  const byId = (_cache && _cache.byId) || Object.fromEntries(CURATED.map((m) => [m.id, m]));
  const m = byId[id];
  return (m && m.brainProvider && CLI_SUBMODELS[m.brainProvider]) || [];
}

export { CURATED, availOf, CLI_SUBMODELS };

/* ══ [GATE 3 · obra D] EL PUENTE ENTRE LOS DOS ESPACIOS DE ID ═══════════════════════════
 *
 * EL BUG QUE CIERRA (medido en la .app de la obra C): el árbol tiene DOS vocabularios para
 * nombrar un modelo y nadie los traducía.
 *
 *   · el WIDGET (Modelos v2 / sidecar)  → `picker_id`   `opus` · `claude_cli` · `api:anthropic`
 *   · la RECETA (este módulo, CURATED)  → id curado     `opus` · `claude_cli` · `byok` · `oss` …
 *
 * Se solapan sólo en tres (`opus`, `claude_cli`, `codex_cli`). Las ocho filas `api:*` no
 * existen del lado curado, así que `modelEntry('api:anthropic')` devolvía `null` y el click
 * moría en un `return` silencioso: elegir un modelo de API NO HACÍA NADA. Y en el otro
 * sentido, pasarle un id curado al widget lo hacía caer a su fallback y marcar «En uso» en
 * la PRIMERA FILA — un indicador que no tenía nada que ver con lo que ejecutaba el turno.
 *
 * ⚠️ LA TRADUCCIÓN VIVE ACÁ Y EN NINGÚN OTRO LADO. Traducir ad hoc en cada punto de uso es
 * cómo se llega a tres traducciones que no coinciden — la misma lección que `compileModel` y
 * `modelIdForRecipe`, que ya viven acá por el mismo motivo. Este módulo es el dueño de la
 * IDENTIDAD de un modelo; el puente es parte de eso.
 *
 * ── POR QUÉ ESTAS REGLAS Y NO OTRAS ────────────────────────────────────────────────────
 * Salen del censo REAL de `_PICKER_HOSTEADO` (`centro_modelos.py:184`), 11 filas, no de un
 * parecido: `incluido` → `opus` · `cli` → su `brain_provider` · `api` → `byok_ref`. **Hoy no
 * hay una sola fila sin equivalente**, y el orden de las preguntas es el contrato:
 *
 *   1 · ¿trae `brain_provider`?  → el modelo curado de ese provider (Mi Claude Code / Codex)
 *   2 · ¿trae `byok_ref`?        → `byok`, con su payload {provider, model, baseUrl}
 *   3 · ¿su `picker_id` existe en el catálogo curado? → ése
 *   4 · ¿matchea por `model` + `base_url`? → ése (el último recurso que sigue siendo un HECHO)
 *   5 · nada de lo anterior     → **`null`, y quien llama TIENE QUE DECIRLO.** Que una fila
 *       nueva del backend muera en silencio es exactamente el bug que esta obra cierra: no se
 *       cambia el `return` mudo por otro `return` mudo. */
export function curadoDesdeFila(fila, catalogo) {
  if (!fila) return null;
  // Acepta la FILA entera (lo normal: trae `byok_ref`/`brain_provider`, que es lo que
  // permite traducir) o un id suelto, para el host que sólo tiene eso. Vive acá y no en el
  // llamador porque `picker_id` es vocabulario DE ESTE MÓDULO: que la Sala arme una fila
  // sintética a mano ya sería la traducción ad hoc que esta pieza existe para evitar.
  if (typeof fila === "string") fila = { picker_id: fila, id: fila };
  const lista = catalogo || (_cache && _cache.list) || CURATED;
  const hay = (id) => lista.some((m) => m.id === id) || CURATED.some((m) => m.id === id);

  if (fila.brain_provider) {
    const m = lista.find((x) => x.brainProvider === fila.brain_provider)
           || CURATED.find((x) => x.brainProvider === fila.brain_provider);
    if (m) return { id: m.id, byok: null, via: "brain_provider" };
  }
  if (fila.byok_ref) {
    return { id: "byok", via: "byok_ref", byok: {
      provider: String(fila.byok_ref).replace(/^keys:/, ""),
      model: fila.model || fila.primary || "",
      baseUrl: fila.base_url || fila.baseUrl || "",
    } };
  }
  const pid = fila.picker_id || fila.id;
  if (pid && hay(pid)) return { id: pid, byok: null, via: "picker_id" };
  const porModelo = lista.find((x) => x.model === fila.model && x.base_url === fila.base_url)
                 || CURATED.find((x) => x.model === fila.model && x.base_url === fila.base_url);
  if (porModelo) return { id: porModelo.id, byok: null, via: "modelo" };
  return null;
}

/** El camino de vuelta: **QUÉ FILA DEL WIDGET ES LA QUE DE VERDAD CORRE.**
 *
 * Se resuelve contra `recipe.model` —lo que el backend ejecuta— y NO contra la selección del
 * sidecar. Ésa es la diferencia entre un indicador honesto y el que había: «En uso» tiene que
 * salir de la misma fuente que el turno, o vuelve a mentir en cuanto las dos se separan (que
 * es justo lo que pasó al hacer que la ejecución siguiera la receta).
 *
 * Devuelve el `picker_id` de la fila, o `null` si el modelo de la receta no está en la lista
 * —caso legítimo: un agente equipado con algo que el sidecar no ofrece hoy— y ahí el widget
 * NO debe marcar ninguna fila, en vez de marcar la primera. */
export function filaDesdeReceta(recipeModel, filas) {
  const m = recipeModel || {};
  const lista = Array.isArray(filas) ? filas : [];
  if (!lista.length) return null;
  const por = (fn) => { const f = lista.find(fn); return f ? (f.picker_id || f.id) : null; };
  if (m.byok_ref) {
    const hit = por((f) => f.byok_ref === m.byok_ref);
    if (hit) return hit;
  }
  if (m.brain_provider) {
    const hit = por((f) => f.brain_provider === m.brain_provider);
    if (hit) return hit;
  }
  return por((f) => f.model === m.primary && f.base_url === m.base_url)
      || por((f) => f.model === m.primary);
}
