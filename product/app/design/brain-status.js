/* brain-status.js — contrato compartido del MODELO efectivo (desktop).
 *
 * [FIX-P8 · rename transversal] Lo que el usuario ve dice MODELOS. El nombre del archivo
 * y los identificadores internos (`AlephBrain`, `brain_provider`, `/v1/brains/status`)
 * NO se tocan: son contrato con el backend, con la receta persistida y con seis
 * superficies. Renombrar el contrato para renombrar una etiqueta habría sido cambiar la
 * cañería para cambiar el cartel.
 *
 * Una sola fuente para Home/Cuarto/Sala/Conectar/Settings:
 *   resolve(ctx) → {active,state,available,blockExecution,label,model,submodel,detail,action}
 *   mount(el, ctx) → indicador reusable con acción de reparación/gestión.
 *
 * Honestidad:
 * - una receta guardada NO implica "conectado";
 * - CLI se verifica por /v1/brains/status;
 * - BYOK se verifica por /v1/users/{id}/keys;
 * - lane incluida se verifica si /v1/brains/status expone providers.included; si no, queda
 *   "unverifiable", nunca "connected" por defecto.
 */
(function () {
  if (window.AlephBrain) return;

  var SCRIPT = document.currentScript && document.currentScript.src;
  var ROOT = SCRIPT ? new URL("./", SCRIPT) : new URL("./", location.href);
  var STATUS_TTL_MS = 12000;
  var _providers = null, _providersAt = 0, _cliService = null;

  var ACTIVE_KEY = "aleph-active-brain";
  var BYOK_KEY = "aleph-active-byok-provider";
  var CONFIG_KEY = "aleph-brain-configuration";

  var LLM_PROVIDERS = { anthropic: 1, openai: 1, groq: 1, openrouter: 1, gemini: 1 };
  var POWER = {
    included: { active: "included", id: "included", label: "Incluido", model: "openai/gpt-oss-120b", lane: "included" },
    estandar: { active: "included", id: "estandar", label: "Incluido · estándar", model: "openai/gpt-oss-120b", lane: "included" },
    veloz: { active: "included", id: "veloz", label: "Incluido · veloz", model: "openai/gpt-oss-20b", lane: "included" },
    oss: { active: "included", id: "oss", label: "GPT-OSS 120B", model: "openai/gpt-oss-120b", lane: "included" },
    llama70: { active: "included", id: "llama70", label: "Llama 3.3 70B", model: "llama-3.3-70b-versatile", lane: "included" },
    gemini: { active: "byok", id: "gemini", label: "Gemini · BYOK", provider: "gemini", model: "gemini-2.5-flash" },
    deepseek: { active: "byok", id: "deepseek", label: "DeepSeek · BYOK", provider: "openrouter", model: "deepseek/deepseek-chat-v3-0324" },
    tuapi: { active: "byok", id: "tuapi", label: "API/BYOK", provider: null, model: null },
    byok: { active: "byok", id: "byok", label: "API/BYOK", provider: null, model: null },
    claude_cli: { active: "claude_cli", id: "claude_cli", label: "Claude Code", provider: "claude_cli", model: "claude-code-cli" }, /* E1-FALLBACK */
    codex_cli: { active: "codex_cli", id: "codex_cli", label: "Codex", provider: "codex_cli", model: "codex-cli" }, /* E1-FALLBACK */
    none: { active: "none", id: "none", label: "Sin modelo", model: null },
  };
  // ORDEN_CLI y POWER[cli] se rellenan desde /v1/brains/status.catalog (registry).
  // El fallback de dos ids es sidecar viejo: justificado, no una tercera lista de producto.
  var ORDEN_CLI = ["claude_cli", "codex_cli"]; /* E1-FALLBACK */
  var CLI_CATALOG = [];
  function applyCliCatalog(catalog) {
    if (!catalog || !catalog.length) return;
    CLI_CATALOG = catalog;
    ORDEN_CLI = catalog.map(function (c) { return c.provider_id; }).filter(Boolean);
    catalog.forEach(function (c) {
      if (!c.provider_id) return;
      POWER[c.provider_id] = {
        active: c.provider_id, id: c.provider_id,
        label: c.display_name || c.picker_label || c.provider_id,
        provider: c.provider_id, model: c.response_model_id,
        glyph: c.glyph || ""
      };
    });
  }
  function isCliId(id) {
    id = String(id || "");
    if (ORDEN_CLI.indexOf(id) >= 0) return true;
    if (CLI_CATALOG.length) return false;
    return id === "claude_cli" || id === "codex_cli"; /* E1-FALLBACK sidecar viejo */
  }

  function t(key, fb) {
    try { var v = window.t ? window.t(key) : null; return (v && v !== key) ? v : fb; }
    catch (e) { return fb; }
  }
  function session() {
    try {
      if (window.AlephSession && window.AlephSession.get) return window.AlephSession.get();
      return JSON.parse(sessionStorage.getItem("puppet_user") || "null");
    }
    catch (e) { return null; }
  }
  function authHeaders(h) {
    h = h || {};
    var u = session();
    if (u && u.session_token) h.Authorization = "Bearer " + u.session_token;
    return h;
  }
  function href(path) { return new URL(path, ROOT).href; }
  function setupReturnPath() {
    var path = location.pathname || "/";
    // [Convergencia · superficie 7 · paso 3] LA V2 NO ESTABA CONTEMPLADA, y era un defecto
    // vivo: `/(^|\/)sala\//` NO matchea `/sala-v2/` —son carpetas distintas— así que quien
    // configuraba su cerebro DESDE la Sala moderna caía al `return` final y aterrizaba en
    // el Cuarto. Medido: `/sala-v2/sala-v2.html` → `/cuarto/cuarto.pixi.html`. Cada
    // pantalla vuelve a SÍ MISMA; la v2 va primero porque es la más específica.
    if (/(^|\/)sala-v2\//.test(path)) return "/sala-v2/sala-v2.html";
    if (/(^|\/)sala\//.test(path)) return "/sala/sala.html";
    if (/(^|\/)cuarto\//.test(path) || /\/Cuarto\.dc\.html$/i.test(path)) return "/cuarto/cuarto.pixi.html";
    return "/cuarto/cuarto.pixi.html";
  }
  // [FIX-P8] EL EMBUDO. Todas las superficies preguntan "¿dónde se configura el modelo?"
  // por acá — el chip del nav, la Sala, el Cuarto. Apuntarlo al Centro de Modelos hace
  // que TODAS aterricen en la pantalla nueva sin tocar ninguna de ellas.
  //
  // `mode` (api|cli) sigue viajando como `modo` y `cat` es lo NUEVO: la categoría exacta
  // (vision · razonamiento · codigo · rapido · embeddings). Es lo que convierte "te mandé
  // a la pantalla" en "te dejé parado en el lugar por el que viniste".
  var MODO_DE_MODE = { api: "api", cli: "cli", local: "local", included: "incluido" };
  function setupHref(options) {
    options = options || {};
    var target = new URL("Modelos.dc.html", ROOT);
    target.searchParams.set("return", options.returnTo || setupReturnPath());
    if (options.mode) target.searchParams.set("modo", MODO_DE_MODE[options.mode] || options.mode);
    if (options.cat) target.searchParams.set("cat", options.cat);
    if (options.brain) target.searchParams.set("m", options.brain);
    return target.href;
  }

  /** EL VAULT · donde se AÑADE un modelo (a diferencia de `setupHref`, donde se ELIGE).
   *  Mismo `ROOT` que `setupHref` para que funcione igual desde `sala-v2/` y desde la raíz. */
  function conectoresHref(options) {
    options = options || {};
    var target = new URL("Conectores.dc.html", ROOT);
    target.searchParams.set("return", options.returnTo || setupReturnPath());
    return target.href;
  }

  //: Causa del chat/semáforo → la CATEGORÍA en la que hay que aterrizar. Es la mitad que
  //: le faltaba a "no puedo ver imágenes": el camino existía, pero dejaba a la persona en
  //: una pantalla genérica a buscar sola qué apretar.
  var CAT_DE_CAUSA = { sin_vision: "vision", sin_memoria: "embeddings",
                       sin_codigo: "codigo", sin_razonamiento: "razonamiento" };
  function setupHrefPorCausa(causa, options) {
    options = options || {};
    var cat = CAT_DE_CAUSA[String(causa || "")];
    return setupHref(cat ? Object.assign({}, options, { cat: cat }) : options);
  }
  function readConfig() {
    try {
      var raw = localStorage.getItem(CONFIG_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }
  function cleanConfig(raw) {
    if (!raw || typeof raw !== "object") return null;
    var mode = raw.mode === "api" || raw.mode === "cli" || raw.mode === "included" ? raw.mode : null;
    var id = String(raw.id || "");
    if (!mode || !id) return null;
    if (mode === "api") {
      var provider = String(raw.provider || "").toLowerCase();
      var model = String(raw.model || "");
      var baseUrl = String(raw.baseUrl || raw.base_url || "");
      if (!provider || !model || !baseUrl) return null;
      return { version: 1, mode: "api", id: "tuapi", provider: provider, model: model,
        modelId: String(raw.modelId || "byok"), baseUrl: baseUrl };
    }
    if (mode === "cli") {
      if (!isCliId(id)) return null;
      return { version: 1, mode: "cli", id: id, cliModel: String(raw.cliModel || raw.cli_model || "") };
    }
    return { version: 1, mode: "included", id: id };
  }
  function getConfiguration() {
    var stored = cleanConfig(readConfig());
    if (stored) return stored;
    try {
      var id = localStorage.getItem(ACTIVE_KEY);
      if (!id) return null;
      if (id === "tuapi" || id === "byok") {
        return null;
      }
      if (isCliId(id)) return { version: 1, mode: "cli", id: id, cliModel: "" };
      return { version: 1, mode: "included", id: id };
    } catch (e) { return null; }
  }
  function configurationToSelected(config) {
    config = cleanConfig(config);
    if (!config) return null;
    if (config.mode === "api") return {
      active: "byok", id: "byok", label: config.provider.toUpperCase() + " · API",
      provider: config.provider, model: config.model, source: "configuration"
    };
    if (config.mode === "cli") return Object.assign({}, POWER[config.id], {
      submodel: config.cliModel || "", source: "configuration"
    });
    return Object.assign({}, POWER[config.id] || POWER.included, { source: "configuration" });
  }
  function setConfiguration(raw) {
    var config = cleanConfig(raw);
    if (!config) return null;
    try {
      localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
      localStorage.setItem(ACTIVE_KEY, config.id);
      if (config.mode === "api") localStorage.setItem(BYOK_KEY, config.provider);
      else localStorage.removeItem(BYOK_KEY);
    } catch (e) {}
    try { window.dispatchEvent(new CustomEvent("aleph:brain-active-changed", { detail: { id: config.id, config: config } })); } catch (e) {}
    return config;
  }
  function getProviderFromRef(ref) {
    ref = String(ref || "");
    if (!ref) return null;
    if (ref.indexOf("keys:") === 0) ref = ref.slice(5);
    if (ref.indexOf("user:") === 0 && ref.indexOf("/") >= 0) ref = ref.split("/").pop();
    if (ref.indexOf("keys.") === 0 && /\.byok_ref$/.test(ref)) ref = ref.slice(5, -9);
    return ref || null;
  }
  function modelToSelected(model, recipe) {
    model = model || {};
    var canvas = recipe && recipe.canvas && recipe.canvas.nucleos && recipe.canvas.nucleos[0] && recipe.canvas.nucleos[0].model;
    if (canvas && POWER[canvas]) return Object.assign({}, POWER[canvas], { source: "recipe", submodel: model.cli_model || "" });
    if (POWER[model.brain_provider]) return Object.assign({}, POWER[model.brain_provider], { source: "recipe", submodel: model.cli_model || "", effort: model.effort || "" });
    if (model.byok_ref) {
      var provider = getProviderFromRef(model.byok_ref);
      return { active: "byok", id: "byok", label: (provider ? provider.toUpperCase() + " · BYOK" : "API/BYOK"), provider: provider, model: model.primary || null, source: "recipe" };
    }
    if (model.alias && POWER[model.alias]) return Object.assign({}, POWER[model.alias], { source: "recipe", model: model.primary || POWER[model.alias].model });
    var pri = String(model.primary || ""), base = String(model.base_url || "");
    if (base.indexOf(":8926") >= 0) {
      for (var ci = 0; ci < CLI_CATALOG.length; ci++) {
        var row = CLI_CATALOG[ci];
        if (pri === row.response_model_id || (row.provider_id && pri.indexOf(row.provider_id.replace("_cli", "")) >= 0)) {
          return Object.assign({}, POWER[row.provider_id], { source: "recipe", submodel: model.cli_model || "", effort: model.effort || "" });
        }
      }
      if (pri === "claude-code-cli" || /claude/i.test(pri)) return Object.assign({}, POWER.claude_cli, { source: "recipe", submodel: model.cli_model || "", effort: model.effort || "" });
      if (pri === "codex-cli" || /codex/i.test(pri)) return Object.assign({}, POWER.codex_cli, { source: "recipe", submodel: model.cli_model || "", effort: model.effort || "" });
    }
    if (pri === "openai/gpt-oss-20b") return Object.assign({}, POWER.veloz, { source: "recipe" });
    if (pri === "openai/gpt-oss-120b") return Object.assign({}, POWER.estandar, { source: "recipe" });
    if (pri === "gemini-2.5-flash") return Object.assign({}, POWER.gemini, { source: "recipe" });
    if (pri === "deepseek/deepseek-chat-v3-0324") return Object.assign({}, POWER.deepseek, { source: "recipe" });
    if (pri || base) return { active: "custom", id: "custom", label: "Modelo personalizado", model: pri || null, source: "recipe" };
    return null;
  }
  function normalizeSelected(raw, ctx) {
    ctx = ctx || {};
    if (raw && typeof raw === "object" && raw.active) return Object.assign({}, raw);
    if (raw && typeof raw === "object" && raw.id) return Object.assign({}, POWER[raw.id] || { active: "custom", id: raw.id, label: raw.label || raw.id, model: raw.model || null }, raw);
    if (typeof raw === "string" && POWER[raw]) return Object.assign({}, POWER[raw]);
    if (ctx.recipe && ctx.recipe.model) return modelToSelected(ctx.recipe.model, ctx.recipe) || Object.assign({}, POWER.none);
    if (ctx.noneIfNoSelection) return Object.assign({}, POWER.none);
    var stored = null;
    try { stored = localStorage.getItem(ACTIVE_KEY); } catch (e) {}
    if (stored && POWER[stored]) {
      var s = Object.assign({}, POWER[stored]);
      if (s.active === "byok") {
        try { s.provider = localStorage.getItem(BYOK_KEY) || s.provider || null; } catch (e) {}
      }
      return s;
    }
    // OJO: acá NO se elige el default de arranque. Devolver `included` a ciegas es
    // exactamente el bug de instalación (ver `elegirDefault`): esta rama sólo se usa
    // cuando todavía no se consultó el estado real de los proveedores.
    return Object.assign({}, POWER.included, { _tentativo: true });
  }

  /* ══ EL DEFAULT DE ARRANQUE · el bug de instalación ═══════════════════════════════
   * MEDIDO en la máquina de un humano: instalás la .app, abrís la Sala y el composer
   * está apagado. Causa: sin configuración guardada, el default caía SIEMPRE en
   * «Incluido», y en el artefacto instalado la lane incluida no trae llave → estado
   * `not_configured` → `blockExecution: true`. Un usuario nuevo choca contra eso en su
   * primer minuto, sobrevive a cerrar y reabrir (es estado de entorno), y nada le dice
   * por qué. El peor bug posible: el que parece que el producto no funciona.
   *
   * LA REGLA: el default de arranque es el primero REALMENTE UTILIZABLE, verificado
   * contra `/v1/brains/status` — no el primero de una lista escrita a mano.
   *   1. «Incluido», SÓLO si de verdad está listo (sin llave que traer);
   *   2. tu Claude Code / tu Codex, si el CLI está `ready` Y su servicio local vive;
   *   3. si NINGUNO sirve: `none`, que es la verdad — con su aviso y su camino
   *      ([Conectar un modelo] → el Centro de Modelos). Jamás un bloqueo mudo.
   *
   * NO se persiste: es una elección DERIVADA del entorno, no una decisión del humano.
   * Todas las superficies la derivan igual, así que no hay dos verdades; y el día que la
   * lane incluida se configure, el default se mueve solo sin dejar basura en el storage. */
  function usable(st) { return !!(st && st.state === "ready"); }

  function elegirDefault(p, svc) {
    p = p || {};
    if (usable(p.included)) return Object.assign({}, POWER.included, { source: "auto", auto: true });
    var svcOk = !svc || svc.state === "ready";
    if (svcOk) {
      for (var i = 0; i < ORDEN_CLI.length; i++) {
        if (usable(p[ORDEN_CLI[i]])) {
          return Object.assign({}, POWER[ORDEN_CLI[i]], { source: "auto", auto: true });
        }
      }
    }
    return Object.assign({}, POWER.none, { source: "auto", auto: true, noUsable: true });
  }
  async function fetchJson(path) {
    var r = await fetch(path, { headers: authHeaders() });
    if (!r.ok) throw new Error("http " + r.status);
    return await r.json().catch(function () { return {}; });
  }
  async function providers(refresh) {
    if (!refresh && _providers && Date.now() - _providersAt < STATUS_TTL_MS) return _providers;
    try {
      var d = await fetchJson("/v1/brains/status");
      _providers = (d && d.providers) || {};
      _cliService = (d && d.service) || null;
      if (d && d.catalog) applyCliCatalog(d.catalog);
      _providersAt = Date.now();
    } catch (e) {
      _providers = {};
      _cliService = null;
      _providersAt = Date.now();
    }
    return _providers;
  }
  async function keysFor(userId) {
    if (!userId) return [];
    try {
      var d = await fetchJson("/v1/users/" + encodeURIComponent(userId) + "/keys");
      return Array.isArray(d.keys) ? d.keys : (Array.isArray(d) ? d : []);
    } catch (e) { return []; }
  }
  function action(kind, selected) {
    return { label: t("brain.action.connect", "Conectar modelo"), href: setupHref() };
  }
  // [identidad visual §f] La tabla POWER declara sus etiquetas en español y NUNCA pasaban
  // por t(): el chip terminaba mitad y mitad ("Incluido · unverified") en la UI en inglés,
  // y La Sala —que compone su subtítulo con este mismo label— arrastraba la mezcla. Se
  // traduce en baseStatus, que es el embudo por donde pasa TODO status antes de salir.
  var LABEL_KEY = {
    "Incluido": "brain.label.included",
    "Incluido · estándar": "brain.label.included_std",
    "Incluido · veloz": "brain.label.included_fast",
    "Sin modelo": "brain.label.none",
    "Modelo personalizado": "brain.label.custom",
  };
  function trLabel(l) { return LABEL_KEY[l] ? t(LABEL_KEY[l], l) : l; }

  function baseStatus(selected, state, detail) {
    var available = state === "healthy" || state === "unverifiable";
    return {
      active: selected.active,
      id: selected.id,
      label: trLabel(selected.label),
      provider: selected.provider || null,
      model: selected.model || null,
      submodel: selected.submodel || null,
      effort: selected.effort || null,
      source: selected.source || "global",
      state: state,
      available: available,
      blockExecution: state === "unavailable" || state === "not_configured",
      detail: detail || "",
      action: action(selected.active, selected),
    };
  }
  function cliStatus(selected, st, service) {
    // Slice C: una sesión CLI autenticada no alcanza si el listener local que ejecuta
    // completions no está vivo. El status compartido bloquea esa ruta en TODAS las
    // superficies; nunca convierte `ready` del auth en un falso "conectado".
    if (service && service.state !== "ready") {
      var waiting = service.state === "checking" || service.state === "starting";
      var out = baseStatus(selected, waiting ? "checking" : "unavailable",
        service.detail || t("brain.cli.service_down", "El servicio local de Claude Code/Codex no está disponible."));
      out.blockExecution = true;
      out.service = service;
      return out;
    }
    if (!st) return baseStatus(selected, "unverifiable", t("brain.cli.unverified", "No pude verificar este CLI; se confirma al ejecutar."));
    var status;
    if (st.state === "ready" && st.access_state === "allowed")
      status = baseStatus(selected, "healthy", st.detail || t("brain.cli.ready", "sesión CLI activa."));
    else if (st.state === "ready")
      status = baseStatus(selected, "unverifiable", t("brain.cli.access_unknown", "Sesión activa; acceso y ejecución aún sin verificar."));
    else if (st.state === "access_denied") status = baseStatus(selected, "unavailable", st.detail || "Sesión activa; el proveedor denegó el acceso.");
    else if (st.state === "auth_expired") status = baseStatus(selected, "unavailable", st.detail || "La sesión de Claude Code venció. Ejecuta `claude auth login` y vuelve a comprobar.");
    else if (st.state === "no_auth") status = baseStatus(selected, "unavailable", st.detail || t("brain.cli.no_auth", "CLI instalado, pero sin sesión."));
    else if (st.state === "not_installed") status = baseStatus(selected, "unavailable", st.detail || t("brain.cli.missing", "No encontré el CLI en esta máquina."));
    else if (st.state === "auth_unknown") status = baseStatus(selected, "unavailable", st.detail || "No pude verificar tu sesión CLI. Vuelve a comprobar.");
    else status = baseStatus(selected, "unverifiable", st.detail || t("brain.cli.unknown", "Estado CLI no verificable."));
    if (service) status.service = service;
    return status;
  }
  function includedStatus(selected, st) {
    if (!st) return baseStatus(selected, "unverifiable", t("brain.included.unverified", "La lane incluida no expone una señal de salud en este runtime; se confirma al ejecutar."));
    if (st.state === "ready") return baseStatus(selected, "healthy", st.detail || t("brain.included.ready", "lane incluida configurada."));
    if (st.state === "not_configured") return baseStatus(selected, "not_configured", st.detail || t("brain.included.no_key", "La lane incluida no está configurada en este runtime."));
    if (st.state === "unavailable") return baseStatus(selected, "unavailable", st.detail || t("brain.included.bad", "La lane incluida no está disponible."));
    return baseStatus(selected, "unverifiable", st.detail || t("brain.included.unknown", "No pude verificar la lane incluida."));
  }
  async function byokStatus(selected, ctx) {
    var u = (ctx && ctx.user) || session();
    var provider = selected.provider || null;
    var keys = await keysFor(u && u.id);
    if (!provider) {
      var first = keys.find(function (k) { return k && LLM_PROVIDERS[String(k.provider || "").toLowerCase()]; });
      provider = first && first.provider;
      if (provider) selected.provider = provider;
    }
    if (!provider) return baseStatus(selected, "not_configured", t("brain.byok.pick", "No hay una API key/modelo BYOK seleccionado."));
    var hit = keys.find(function (k) { return String(k.provider || "").toLowerCase() === String(provider).toLowerCase(); });
    selected.label = (provider ? provider.toUpperCase() : "API") + " · BYOK";
    if (!u || !u.id) return baseStatus(selected, "not_configured", t("brain.byok.no_user", "Inicia sesión para verificar tus API keys."));
    if (!hit) return baseStatus(selected, "not_configured", t("brain.byok.missing", "No encontré esa API key guardada para esta cuenta."));
    if (hit.verified === false) return baseStatus(selected, "unverifiable", t("brain.byok.unverified", "La key existe, pero este runtime no pudo validarla de forma dura."));
    return baseStatus(selected, "healthy", t("brain.byok.ready", "API key guardada y disponible para este usuario."));
  }
  async function resolve(ctx) {
    ctx = ctx || {};
    if (window.AlephBrainPageContext && !ctx._fromPage) {
      try { ctx = Object.assign({}, ctx, window.AlephBrainPageContext() || {}, { _fromPage: true }); } catch (e) {}
    }
    var configured = getConfiguration();
    if (configured && !ctx.ignoreSavedConfiguration) ctx.selected = configurationToSelected(configured);
    var selected = normalizeSelected(ctx.selected, ctx);
    var p = await providers(!!ctx.refresh);

    // ARRANQUE LIMPIO: nadie eligió todavía → el default se ELIGE contra el estado real,
    // no se hereda de una constante. Sólo cuando la elección es NUESTRA (`_tentativo`):
    // una receta guardada, una elección del humano o un ctx explícito mandan siempre.
    if (selected._tentativo) selected = elegirDefault(p, _cliService);

    var status;
    if (selected.active === "none") {
      // La verdad, con su camino. `blockExecution` sigue en true —no se puede ejecutar de
      // verdad— pero deja de ser MUDO: el chip lo dice y el botón lleva al Centro de
      // Modelos, que es donde se arregla.
      status = baseStatus(selected, "not_configured", selected.noUsable
        ? t("brain.none.usable", "No hay ningún modelo utilizable en esta máquina todavía: la cognición incluida no está configurada y no encontré tu Claude Code ni tu Codex.")
        : t("brain.none", "No hay un modelo seleccionado."));
      status.noUsable = !!selected.noUsable;
      status.auto = !!selected.auto;
    }
    else if (isCliId(selected.active)) status = cliStatus(selected, p[selected.active], _cliService);
    else if (selected.active === "byok") status = await byokStatus(selected, ctx);
    else if (selected.active === "included") status = includedStatus(selected, p.included);
    else status = baseStatus(selected, "unverifiable", t("brain.custom", "Modelo personalizado: se verifica al ejecutar."));
    if (selected.auto) status.auto = true;
    try { window.dispatchEvent(new CustomEvent("aleph:brain-status", { detail: status })); } catch (e) {}
    return status;
  }
  function stateLabel(s) {
    return s.state === "healthy" ? t("brain.state.healthy", "conectado")
      : s.state === "unavailable" ? t("brain.state.unavailable", "no disponible")
      : s.state === "not_configured" ? t("brain.state.not_configured", "no configurado")
      : s.state === "checking" ? t("brain.state.checking", "verificando")
      : t("brain.state.unverifiable", "sin verificación");
  }
  function stateClass(s) {
    return s.state === "healthy" ? "ok" : (s.state === "unavailable" || s.state === "not_configured") ? "bad" : "warn";
  }
  function installCss() {
    if (document.getElementById("aleph-brain-style")) return;
    var st = document.createElement("style");
    st.id = "aleph-brain-style";
    st.textContent = [
      /* [sistema 2026-07-31] Este widget se había quedado afuera del rediseño, y se nota
       * porque aparece en DOS lugares muy visibles: la barra superior y el pie del
       * compositor de la Sala. Traía borde, radio 12, pesos 600-800 y —lo peor— fallbacks
       * de la paleta ANTERIOR (#202138 violeta, #3C3D5C, #EDEBFA): en cuanto una pantalla
       * no cargara los tokens, el chip se pintaba con el sistema viejo.
       * Ahora: color del POZO (--paper2, que es lo que el modelo usa para este chip),
       * cero bordes, radios y pesos del sistema, y fallbacks alineados al tema oscuro nuevo. */
      ".aleph-brain{display:flex;align-items:center;gap:8px;border:0;background:var(--paper2,#1C1C1F);color:var(--ink,#F5F5F6);border-radius:var(--r-sm,13px);padding:8px 12px;min-width:0;font:400 12px/1.25 var(--font-ui)}",
      ".aleph-brain.compact{position:relative;width:38px;min-width:38px;height:38px;box-sizing:border-box;padding:0;display:block;overflow:visible}",
      ".aleph-brain.rich{align-items:flex-start;padding:11px 14px;border-radius:var(--r-md,18px);background:var(--paper2,#1C1C1F)}",
      /* el punto de estado pierde el anillo: un halo de 1px es un borde disfrazado */
      ".aleph-brain-dot{width:7px;height:7px;border-radius:50%;background:var(--quiet,rgba(160,160,166,.30));flex:none}",
      ".aleph-brain.ok .aleph-brain-dot{background:var(--green,#4E9E77)}",
      ".aleph-brain.warn .aleph-brain-dot{background:var(--amber,#C89329)}",
      ".aleph-brain.bad .aleph-brain-dot{background:var(--red,#C2412D)}",
      ".aleph-brain-main{min-width:0;flex:1}",
      ".aleph-brain-title{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--ink,#F5F5F6)}",
      ".aleph-brain-meta{display:block;margin-top:2px;font-size:11px;font-weight:300;color:var(--muted,#A0A0A6);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".aleph-brain.rich .aleph-brain-meta{white-space:normal;line-height:1.35}",
      ".aleph-brain-action{border:0;background:transparent;color:var(--accent-deep,#B7B5F5);font:400 11.5px/1 var(--font-ui);cursor:pointer;padding:3px 0 3px 6px;white-space:nowrap}",
      ".aleph-brain-action:hover{text-decoration:underline}",
      ".aleph-brain-trigger{position:relative;width:36px;height:36px;padding:0;border:0;border-radius:var(--r-sm,13px);background:transparent;color:var(--ink,#F5F5F6);cursor:pointer;display:grid;place-items:center}",
      ".aleph-brain-logo{font:400 16px/1 var(--font-ui);color:var(--accent-deep,#B7B5F5)}",
      ".aleph-brain-trigger .aleph-brain-dot{position:absolute;right:5px;bottom:5px;width:6px;height:6px}",
      /* el popover es un plano flotante: sombra, no línea */
      ".aleph-brain-pop{position:absolute;right:0;top:calc(100% + 7px);z-index:10000;width:238px;box-sizing:border-box;padding:14px;border:0;border-radius:var(--r-lg,22px);background:var(--paper,#141416);box-shadow:var(--sh-2,0 12px 38px rgba(0,0,0,.5))}",
      ".aleph-brain-pop[hidden]{display:none!important}",
      ".aleph-brain-pop .aleph-brain-title{font-size:13px;font-weight:400}",
      ".aleph-brain-pop .aleph-brain-meta{white-space:normal;margin:4px 0 10px;line-height:1.35}",
      ".aleph-brain-pop .aleph-brain-action{padding:5px 0;text-align:left;white-space:normal}",
      ".aleph-brain-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}",
      ".aleph-brain-actions button{border:0;background:var(--paper2,#1C1C1F);color:var(--ink,#F5F5F6);border-radius:var(--r-sm,13px);padding:6px 11px;font:400 11.5px/1 var(--font-ui);cursor:pointer}",
      ".aleph-brain-actions button:hover{color:var(--accent-deep,#B7B5F5)}",
      "@media(max-width:1120px){.aleph-brain.compact{width:38px;min-width:38px}}",
    ].join("");
    document.head.appendChild(st);
  }
  function render(el, status, opts) {
    opts = opts || {};
    installCss();
    // Localize known UI labels before writing attributes, where the text-node
    // observer cannot help. Provider/model identifiers remain unchanged by text().
    var label = window.AlephI18n && window.AlephI18n.text ? window.AlephI18n.text(status.label) : status.label;
    el.className = "aleph-brain " + (opts.rich ? "rich " : "compact ") + stateClass(status);
    var model = status.model ? " · " + status.model : "";
    var sub = status.submodel ? " · " + status.submodel : "";
    var detail = stateLabel(status) + model + sub;
    if (!opts.rich) {
      var logos = { included: "✦", byok: "＠", tuapi: "＠", opus: "✦", oss: "✦", none: "·",
        claude_cli: "◈", codex_cli: "⌘" }; /* E1-FALLBACK glyphs CLI; catalog manda */
      var fromPower = (POWER[status.id] && POWER[status.id].glyph)
        || (POWER[status.active] && POWER[status.active].glyph);
      var logo = fromPower || logos[status.id] || logos[status.active] || "◆";
      el.dataset.modelLogo = String(status.id || status.active || "");
      el.setAttribute("aria-label", label ? (t("brain.model_prefix", "Modelo: ") + label) : t("brain.unread", "Modelo sin leer"));
      el.innerHTML = '<button type="button" class="aleph-brain-trigger" aria-expanded="false">' +
        '<span class="aleph-brain-logo"></span><span class="aleph-brain-dot" aria-hidden="true"></span></button>' +
        '<div class="aleph-brain-pop" hidden><span class="aleph-brain-title"></span>' +
        '<span class="aleph-brain-meta"></span><button type="button" class="aleph-brain-action"></button></div>';
      el.querySelector(".aleph-brain-logo").textContent = logo;
      el.querySelector(".aleph-brain-title").textContent = label || t("brain.unread", "Modelo sin leer");
      el.querySelector(".aleph-brain-meta").textContent = status.label ? detail : t("brain.default_unread", "No pude leer el Default");
      var trigger = el.querySelector(".aleph-brain-trigger"), pop = el.querySelector(".aleph-brain-pop");
      trigger.onclick = function (e) {
        e.preventDefault(); e.stopPropagation(); pop.hidden = !pop.hidden;
        trigger.setAttribute("aria-expanded", pop.hidden ? "false" : "true");
      };
      var action = el.querySelector(".aleph-brain-action");
      action.textContent = status.action.label;
      action.onclick = function (e) {
        e.preventDefault();
        if (opts.onAction) return opts.onAction(status);
        location.href = status.action.href;
      };
      return;
    }
    el.innerHTML = '<span class="aleph-brain-dot" aria-hidden="true"></span>'
      + '<span class="aleph-brain-main"><span class="aleph-brain-title"></span><span class="aleph-brain-meta"></span></span>'
      + '<button type="button" class="aleph-brain-action"></button>';
    el.querySelector(".aleph-brain-title").textContent = label;
    el.querySelector(".aleph-brain-meta").textContent = opts.rich ? (detail + " — " + status.detail) : detail;
    var b = el.querySelector(".aleph-brain-action");
    b.textContent = status.action.label;
    b.onclick = function (e) {
      e.preventDefault();
      if (opts.onAction) return opts.onAction(status);
      location.href = status.action.href;
    };
    if (opts.actions) {
      var actions = document.createElement("div");
      actions.className = "aleph-brain-actions";
      opts.actions(status).forEach(function (a) {
        var ab = document.createElement("button");
        ab.type = "button"; ab.textContent = a.label; if (a.active) ab.setAttribute("data-active", "1");
        ab.onclick = function (e) { e.preventDefault(); a.run(status); };
        actions.appendChild(ab);
      });
      el.querySelector(".aleph-brain-main").appendChild(actions);
    }
  }
  function mount(target, opts) {
    var el = typeof target === "string" ? document.querySelector(target) : target;
    if (!el) return null;
    opts = opts || {};
    async function update(extra) {
      var ctx = typeof opts.getContext === "function" ? (opts.getContext() || {}) : (opts.context || {});
      if (extra) ctx = Object.assign({}, ctx, extra);
      var status;
      if (!opts.rich) {
        // El pill compacto no adivina desde localStorage: consume el MISMO
        // Default+Conectados de Modelos v2 que el selector del Núcleo y Sala.
        var contexto = opts.contexto || "sala";
        try {
          var data = await selectorLoad(contexto, !!ctx.refresh);
          var lista = selectorOpciones({ contexto: contexto, data: data });
          var id = selectorElegido({ contexto: contexto, data: data }, lista);
          var m = lista.find(function (x) { return x.id === id; });
          if (!m) throw new Error("selector sin Default");
          var connected = m.conectado === true || m.connected === true;
          status = {
            active: m.id, id: m.id, label: m.label || m.id, model: m.slug || "",
            state: connected ? "healthy" : "unavailable",
            action: { label: t("brain.action.cuarto", "Elegir o reparar el modelo"), href: setupHref({ returnTo: location.pathname + location.search }) },
          };
        } catch (e) {
          status = { active: "none", id: "none", label: "", model: "", state: "unverifiable",
            action: { label: t("brain.action.cuarto", "Elegir o reparar el modelo"), href: setupHref({ returnTo: location.pathname + location.search }) } };
        }
      } else status = await resolve(ctx);
      el.__alephBrainStatus = status;
      render(el, status, opts);
      return status;
    }
    el.__alephBrainUpdate = update;
    window.addEventListener("aleph:brain-active-changed", function () { update({ refresh: true }); });
    window.addEventListener("aleph:brain-context-changed", function () { update({ refresh: true }); });
    window.addEventListener("aleph:model-selection", function (e) {
      if (!e.detail || e.detail.contexto === (opts.contexto || "sala")) update();
    });
    update();
    return { update: update };
  }
  function setActive(id, extra) {
    extra = extra || {};
    if (id === "tuapi" || id === "byok") {
      var previous = getConfiguration();
      return setConfiguration({ mode: "api", id: "tuapi", provider: extra.provider || (previous && previous.provider),
        model: extra.model || (previous && previous.model), modelId: extra.modelId || (previous && previous.modelId),
        baseUrl: extra.baseUrl || (previous && previous.baseUrl) });
    }
    if (isCliId(id)) return setConfiguration({ mode: "cli", id: id, cliModel: extra.cliModel || "" });
    return setConfiguration({ mode: "included", id: id || "included" });
  }
  // [SALA VIVA] lectura del cache YA traído por resolve() (no dispara red). La Sala lo usa
  // para ofrecer SÓLO caminos que de verdad funcionan: si el modelo elegido está caído pero
  // Claude Code está `ready`, el botón "úsalo" no es una promesa, es un hecho verificado.
  function providersCache() { return _providers || {}; }
  function serviceCache() { return _cliService || null; }

  /* ══ MODELOS V2 · SELECTOR ÚNICO ════════════════════════════════════════════════
   * La pantalla define UN Default. Las superficies sólo persisten su elección POR
   * CONTEXTO y jamás cambian ese Default. La lista viene del sidecar: conectados+default;
   * en Guía, además ∩ frontier. */
  var _selectorCache = {};
  // El sidecar sigue siendo el único dueño persistente. Este canal sólo propaga el
  // PUT ya confirmado entre pestañas/superficies abiertas para que Cuarto, chrome y
  // Sala no necesiten recargarse ni mantengan una segunda preferencia local.
  var _selectorChannel = null;
  try {
    if (typeof BroadcastChannel === "function") {
      _selectorChannel = new BroadcastChannel("aleph-modelos-v2");
      _selectorChannel.onmessage = function (ev) {
        var d = ev && ev.data;
        if (!d) return;
        // [F8 · obra 3] ELEGIR MODELO DE UN PROVEEDOR es un hecho distinto de elegir la vía
        // para un contexto, y por eso viaja con su propio tipo. El catálogo cacheado de la
        // otra pestaña quedó viejo: se TIRA en vez de parchearse a medias — la próxima
        // apertura del panel lo vuelve a pedir, que es barato y no puede mentir.
        if (d.type === "choice" && d.slug) {
          delete _catalogoCache[String(d.slug)];
          Object.keys(_selectorCache).forEach(function (k) {
            var cache = _selectorCache[k];
            if (!cache || !Array.isArray(cache.modelos)) return;
            cache.modelos.forEach(function (row) {
              if (!row || row.slug !== d.slug) return;
              if (d.modelo) row.model = d.modelo;
              row.modelo_elegido = d.modelo || null;
              row.modelo_elegido_por = d.elegido_por || null;
            });
          });
          window.dispatchEvent(new CustomEvent("aleph:model-choice", {
            detail: { slug: String(d.slug), modelo: d.modelo || null,
                      elegido_por: d.elegido_por || null, remote: true },
          }));
          return;
        }
        if (d.type !== "selection" || !d.contexto || !d.id) return;
        var cache = _selectorCache[String(d.contexto)];
        if (cache) { cache.seleccion = d.slug; cache.seleccion_id = d.id; }
        window.dispatchEvent(new CustomEvent("aleph:model-selection", {
          detail: { contexto: String(d.contexto), id: d.id, slug: d.slug, remote: true },
        }));
      };
    }
  } catch (e) { _selectorChannel = null; }
  /* ══ EL POOL Y EL CATÁLOGO SON DOS PAYLOADS, Y NO COMPARTEN CACHE ═════════════════
   *
   * `/v1/modelos/selector` sin `todos` devuelve el POOL (conectados + Default): lo que se
   * puede USAR ahora, y es lo que pide la Sala. Con `todos=1` devuelve también lo NO
   * configurado con su trámite: lo que necesita un picker de CONFIGURACIÓN — si no, no hay
   * dónde poner la llave y la pantalla termina inventando su propia lista (que es
   * exactamente el bug que F7·B encontró en el builder viejo).
   *
   * ⚠️ Guardarlos bajo la MISMA clave sería el peor de los dos mundos: la Sala se pondría
   * a ofrecer modelos sin llave sólo porque el taller pasó por ahí antes. La clave lleva el
   * flag, y `selectorData(contexto)` a secas SIGUE devolviendo el pool — ningún llamador
   * anterior cambia de comportamiento.
   */
  function _claveSel(contexto, todos) {
    return String(contexto || "default") + (todos ? "::todos" : "");
  }
  function selectorSeed(data, contexto, todos) {
    if (data && typeof data === "object")
      _selectorCache[_claveSel(contexto || data.contexto, todos)] = data;
    return data;
  }
  async function selectorLoad(contexto, refresh, todos) {
    var key = _claveSel(contexto, todos);
    if (!refresh && _selectorCache[key]) return _selectorCache[key];
    var q = [];
    // ⚠️ `contexto` YA NO VIAJA AL SIDECAR. [TANDA 1 · obra 1] El cerebro es uno solo, así
    // que `?contexto=<x>` sólo podía hacer daño: `centro_modelos._selector_de` resuelve
    // `seleccion_slug = contextos[contexto] || default`, y con `contextos` viejo en disco
    // (medido: `{cuarto: cli.codex_cli, sala: cli.codex_cli}` de agosto) el widget habría
    // PINTADO Codex mientras el `default` —lo que realmente corre— era Grok. Un picker que
    // muestra un cerebro y ejecuta otro es peor que uno que no anda.
    // El filtro `guia` (sólo frontier) sigue existiendo del lado del cliente, en
    // `selectorOpciones`, así que no se pierde. `contexto` se conserva en la CLAVE del
    // cache porque los hosts siguen pidiendo con su nombre.
    if (todos) q.push("todos=1");
    var r = await fetch("/v1/modelos/selector" + (q.length ? "?" + q.join("&") : ""),
                        { headers: authHeaders({ Accept: "application/json" }) });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return selectorSeed(await r.json(), contexto, todos);
  }
  function selectorData(contexto, todos) {
    return _selectorCache[_claveSel(contexto, todos)] || null;
  }

  /** EL CEREBRO DE LA CASA · `preferencias-v2.default`. UNO SOLO, para las siete.
   *
   * [TANDA 1 · obra 1] Esto se llamaba `seleccionDeContexto(contexto)` y leía
   * `contextos[<contexto>]`. Dos motivos para que ya no exista esa forma:
   *
   *   1. **La distinción murió por decisión del dueño**: el cerebro elegido es uno para
   *      toda la casa. Cambiarlo en Diseño lo cambia en Finanzas y en la Sala.
   *   2. **Nunca tuvo un llamador.** Medido: cero en todo `product/app/design` fuera de la
   *      línea que la exportaba. Es la octava vez en este proyecto que la maquinaria está
   *      y falta quien la llame — así que en vez de borrarla se la apunta a la fuente que
   *      SÍ gobierna y se la enchufa (la Sala la usa desde `sala-v2.js`).
   *
   * NO DERIVA ESTADO: eso es de `semaforoDe()`, y no se toca. Acá sólo se responde *qué
   * cerebro eligió el dueño*; si sirve o no lo dice `resolve()` después.
   *
   * NO DERIVA ESTADO: eso es de `semaforoDe()`, y no se toca. Acá sólo se responde *qué
   * eligió el dueño para esta pantalla*; si sirve o no lo dice `resolve()` después.
   *
   * ⚠️ LA TRADUCCIÓN LA HACE EL PUENTE, NO ESTA FUNCIÓN. La primera versión parseaba el
   * `picker_id` acá (`id.slice(4)` para sacar el provider de `api:openrouter`) y eso era
   * exactamente la familia de bug que la obra D de Gate 3 acababa de cerrar: el árbol tiene
   * DOS vocabularios para nombrar un modelo —`picker_id` del sidecar y el id curado de la
   * receta, que se solapan en 3 de 11— y tenerlos traducidos en dos lugares produjo tres
   * síntomas que parecían no tener relación. `curadoDesdeFila` es ese puente, de una sola
   * pieza, y su propio comentario dice que armar la traducción en el llamador es lo que
   * viene a evitar. Además el `provider` sale de `byok_ref`, que es el campo autoritativo,
   * y no de cortar un string. (Objeción de review de la sesión de Gate 2 — tenía razón.)
   *
   * Devuelve `null` cuando no hay preferencia, o cuando la que hay ya no está en el pool
   * (el modelo se cayó). `null` es la respuesta correcta: deja que `elegirDefault()` elija
   * el primero REALMENTE utilizable, que es la regla que esta casa ya selló.
   */
  async function cerebroElegido() {
    var data = selectorData(null, true);
    if (!data) {
      try { data = await selectorLoad(null, false, true); } catch (e) { return null; }
    }
    if (!data) return null;
    var pref = String(data["default"] || "");
    if (!pref) return null;
    var fila = (data.modelos || []).find(function (m) {
      return m && String(m.slug || "") === pref;
    });
    if (!fila) return null;                       // la preferencia murió: que elija el default
    var curado = null;
    try {
      var M = await import(new URL("cuarto/cuarto.models.js", ROOT).href);
      curado = M.curadoDesdeFila(fila, data.modelos);
    } catch (e) { return null; }   // sin el puente no se adivina: que elija el default
    if (!curado || !curado.id) return null;
    if (curado.byok) {
      var prov = curado.byok.provider || null;
      return { active: "byok", id: "byok", provider: prov, source: "cerebro",
               model: curado.byok.model || null,
               label: (prov ? String(prov).toUpperCase() + " · API" : "API/BYOK") };
    }
    if (POWER[curado.id]) return Object.assign({}, POWER[curado.id], { source: "cerebro" });
    return null;
  }

  /** ELEGIR EL CEREBRO DE LA CASA desde un `picker_id` (`selection_ref`).
   *
   * El chip de la Sala habla en `selection_ref` (`grok_cli`) y el PUT de preferencias
   * habla en `slug` (`cli.grok_cli`) — dos vocabularios que esta casa ya pagó por tener
   * traducidos en dos lugares (ver el aviso de arriba). La traducción vive ACÁ, una sola
   * vez, contra el catálogo COMPLETO (`todos`): en modo pool la fila de un modelo sin
   * llave no aparece y elegirlo devolvería `null` en vez de decir por qué.
   *
   * Devuelve la respuesta del PUT, o lanza con el motivo. NO se traga el fallo: elegir un
   * cerebro y que no pase nada es la clase de silencio que este repo no permite. */
  async function elegirCerebro(pickerId) {
    var id = String(pickerId || "");
    if (!id) throw new Error("elegirCerebro necesita un selection_ref");
    var data = selectorData(null, true) || await selectorLoad(null, true, true);
    var fila = ((data || {}).modelos || []).find(function (m) {
      return m && String(m.picker_id || m.id || "") === id;
    });
    if (!fila || !fila.slug) throw new Error("«" + id + "» no está en el catálogo de modelos");
    return selectorPersist(null, { slug: fila.slug, id: fila.picker_id || fila.id });
  }
  function selectorOpciones(opts) {
    opts = opts || {};
    var contexto = String(opts.contexto || "default");
    var todos = opts.todos === true;
    var data = opts.data || selectorData(contexto, todos) || {};
    var remotas = Array.isArray(data.modelos) ? data.modelos : [];
    var locales = Array.isArray(opts.modelos) ? opts.modelos : [];
    var porId = {};
    locales.forEach(function (m) { if (m && m.id) porId[m.id] = m; });
    var lista = remotas.map(function (r) {
      var id = r.picker_id || r.id || r.slug;
      return Object.assign({}, porId[id] || {}, r, { id: id });
    });
    // Sin respuesta del sidecar no hay forma honesta de distinguir «conectado» de una
    // entrada meramente curada. Fail-closed: queda sólo [+ Modelos], nunca se promueve
    // `opus` (ni ningún otro) a Default/conectado desde el cliente.
    //
    // `todos` NO afloja ese fail-closed: sigue mandando lo que dijo el sidecar. Lo único
    // que cambia es que las filas que el sidecar declaró NO configuradas también se
    // muestran — con su estado y su trámite, no como si estuvieran listas.
    var seen = {};
    lista = lista.filter(function (m) {
      if (!m || !m.id || seen[m.id]) return false;
      seen[m.id] = true;
      var conectado = m.conectado === true || m.connected === true;
      var def = m.default === true || m.slug === data.default;
      if (!conectado && !def && !todos) return false;
      if (contexto === "guia" && !m.frontier) return false;
      return true;
    });
    return lista;
  }

  /* ══ EL ESTADO DE UNA FILA, CON EL COPY DEL DICCIONARIO ÚNICO ══════════════════════
   *
   * Regla sellada: ninguna causa llega a una superficie sin copy, y jamás el nombre
   * técnico. El diccionario es `cuarto.semaforo.js`, que se publica en
   * `window.CuartoSemaforo` justamente para las superficies no-module como ésta.
   *
   * Si el diccionario no está cargado NO se inventa un texto: se cae al par
   * conectado/no-disponible de siempre, que es lo que esta función decía antes.
   */
  function selectorEstado(m) {
    var conectado = m.conectado === true || m.connected === true;
    // ⚠️ [F9] EL ÚNICO ESTADO SIN COLOR ERA EL SANO. Toda fila rota llevaba emoji de color
    // (🔴 ⚪ 🟡 🔒) y la que ANDA llevaba un `●` dentro de `.ams-meta`, que es
    // `var(--faint)` — gris. Así, en la misma lista, «no disponible» se veía y «conectado»
    // se apagaba: el estado que uno busca era el que menos se distinguía.
    //
    // El verde sale del MISMO diccionario que los otros (`ESTADOS.probado.emoji`), no de un
    // carácter escrito acá: un color propio de esta superficie es cómo se llega a que el
    // Cuarto y la Sala pinten distinto lo mismo.
    if (conectado) {
      var S0 = window.CuartoSemaforo;
      var verde = (S0 && S0.ESTADOS && S0.ESTADOS.probado && S0.ESTADOS.probado.emoji) || "●";
      return { texto: verde + " " + t("brain.state.healthy", "conectado"), tramite: null };
    }
    var S = window.CuartoSemaforo;
    if (!S) return { texto: "○ " + t("brain.state.unavailable", "no disponible"), tramite: null };
    var estado = String(m.estado || "");
    var meta = (S.ESTADOS || {})[estado] || null;
    // LA CAUSA MANDA sobre el estado cuando la hay: «Tu llave no sirve» dice más que
    // «Roto». Pero una llave guardada y SIN veredicto (`detectado`) no es un fallo — es
    // «todavía no la probé»— y ahí manda el estado, para no mandar a arreglar lo que anda.
    var cara = (m.causa && estado !== "detectado")
      ? S.caraDeCausa({ causa: m.causa, detalle: m.detalle || "" }) : null;
    var texto = cara ? (S.ESTADOS.roto.emoji + " " + cara.titulo)
      : (meta ? meta.emoji + " " + meta.es
              : "○ " + t("brain.state.unavailable", "no disponible"));
    // El TRÁMITE: sólo las filas que el sidecar declara BYOK de API tienen llave que poner.
    // Sale de `byok_ref` (`keys:<provider>`), que es dato del backend — no se deriva del
    // nombre ni de una tabla del cliente.
    var ref = String(m.byok_ref || "");
    var prov = ref.indexOf("keys:") === 0 ? ref.slice(5) : "";
    if (!prov) return { texto: texto, tramite: null };
    // ⚠️ [F9] LA ACCIÓN TIENE QUE CORRESPONDER A LA CAUSA. Acá decía «Cambiar la llave»
    // para CUALQUIER fila con llave — incluida la que sólo está SIN PROBAR. Medido en la
    // app: Groq (Default) mostraba «Sin probar» y al lado «Cambiar la llave».
    //
    // La llave está puesta; lo que falta es probarla. Ofrecer cambiarla es mandar a rehacer
    // el trámite que ya se hizo —el mismo error que `modelo_no_elegido` mató en la fila— y
    // encima invita a borrar una credencial que puede estar perfecta.
    //
    //   con llave + SIN PROBAR   → [Comprobar]        (probar, no tocar la credencial)
    //   con llave + rota         → [Cambiar la llave] (ahí sí: la credencial es el problema)
    //   sin llave                → [Poner la llave]
    if (m.hay_llave === true && estado === "detectado")
      return { texto: texto,
               tramite: { provider: prov, accion: "probar",
                          label: t("brain.action.check", "Comprobar") } };
    return { texto: texto,
             tramite: { provider: prov, accion: "llave",
                        label: m.hay_llave === true
                          ? t("brain.action.rekey", "Cambiar la llave")
                          : t("brain.action.setkey", "Poner la llave") } };
  }
  function selectorElegido(opts, lista) {
    opts = opts || {}; lista = lista || selectorOpciones(opts);
    // ⚠️ `opts.todos` TAMBIÉN ACÁ. [TANDA 1 · obra 1] Esto leía `selectorData(opts.contexto)`
    // a secas —la clave del POOL— mientras `selectorOpciones` arma las filas con
    // `selectorData(contexto, todos)` —la clave del CATÁLOGO COMPLETO—. Con un host que
    // sólo cargó `todos` (el taller, y la Sala cuando pide el catálogo entero), las filas
    // salían de un payload y la marca «En uso» de otro que estaba vacío: se caía al
    // `lista[0]`, o sea **una fila cualquiera presentada como el cerebro en uso**. Lo
    // destapó `verify_selector_unico.mjs` al pedirle a dos superficies que reflejaran la
    // misma elección.
    var data = opts.data || selectorData(opts.contexto, opts.todos === true)
               || selectorData(opts.contexto) || {};
    /* [GATE 3 · obra D] `seleccionadoResuelto` — EL HOST YA SABE CUÁL CORRE, Y PUEDE SER
     * NINGUNA. Sin esta rama el widget no tenía forma de expresar «ninguna fila está en
     * uso»: `seleccionado: null` es falsy, caía al `seleccion_id` del sidecar, y si ése
     * tampoco estaba en la lista terminaba marcando `lista[0]` — una fila cualquiera
     * presentada como «En uso». Con un agente equipado con un modelo que el sidecar no
     * ofrece hoy, eso es un indicador que miente.
     *
     * El opt-in es del host: quien resolvió la elección contra la fuente que EJECUTA (la
     * receta) manda su veredicto tal cual, `null` incluido. Los hosts que no pasan la
     * bandera se comportan byte-idéntico a antes. */
    if (opts.seleccionadoResuelto === true) {
      var res = opts.seleccionado || null;
      return (res && lista.some(function (m) { return m.id === res; })) ? res : null;
    }
    // La elección viva de la superficie manda mientras el panel está abierto. Sin una,
    // el sidecar da primero la elección de ese contexto y finalmente el Default único.
    var id = opts.seleccionado || data.seleccion_id || data.default_id;
    return lista.some(function (m) { return m.id === id; })
      ? id : (lista[0] && lista[0].id) || null;
  }
  function installSelectorCss() {
    if (document.getElementById("aleph-model-selector-style")) return;
    var st = document.createElement("style");
    st.id = "aleph-model-selector-style";
    st.textContent = [
      ".ams{display:flex;flex-direction:column;gap:6px}",
      ".ams-option{width:100%;min-width:0;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;text-align:left;border:0;background:var(--paper2,#1C1C1F);color:var(--ink,#F5F5F6);border-radius:9px;padding:8px 10px;cursor:pointer;overflow:hidden}",
      ".ams-option:hover{color:var(--accent-deep,#B7B5F5)}",
      ".ams-option.on{background:var(--accent-soft,rgba(141,139,238,.15));color:var(--accent-deep,#B7B5F5)}",
      ".ams-main{min-width:0;display:flex;align-items:center;gap:7px}",
      ".ams-name{font-size:12px;font-weight:400;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".ams-side{min-width:0;display:flex;flex-direction:column;align-items:flex-end;gap:2px}",
      ".ams-meta{max-width:100%;font-size:9.5px;color:var(--faint,#A0A0A6);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".ams-use{font-size:10px;font-weight:400;color:var(--accent-deep,#B7B5F5);white-space:nowrap}",
      ".ams-option.on .ams-use{color:var(--ink,#F5F5F6)}",
      ".ams-badge{font-size:9px;font-weight:400;text-transform:uppercase;border:0;background:var(--accent-soft,rgba(141,139,238,.15));border-radius:999px;padding:1px 5px;color:var(--accent-deep,#B7B5F5)}",
      ".ams-add{border-style:dashed;color:var(--accent-deep,#B7B5F5);grid-template-columns:1fr;text-align:center}",
      ".ams-option.ams-off{opacity:.72}",
      ".ams-option.ams-off:hover{opacity:1}",
      ".ams-keybox{display:flex;flex-wrap:wrap;gap:6px;padding:2px 10px 8px}",
      ".ams-keybox[hidden]{display:none!important}",
      ".ams-keyin{flex:1 1 160px;min-width:0;border:1px solid var(--line2,#2A2A30);background:var(--paper,#141416);color:var(--ink,#F5F5F6);border-radius:8px;padding:7px 9px;font:400 12px var(--font-ui)}",
      ".ams-keysave{border:0;background:var(--accent-soft,rgba(141,139,238,.15));color:var(--accent-deep,#B7B5F5);border-radius:8px;padding:7px 11px;font:400 11.5px var(--font-ui);cursor:pointer}",
      ".ams-keysave[disabled]{opacity:.5;cursor:default}",
      ".ams-keymsg{flex:1 1 100%;margin:2px 0 0;font:400 11px/1.45 var(--font-ui);color:var(--muted,#AAA7C4)}",
      ".ams-keymsg[hidden]{display:none!important}",
      ".ams-keymsg.mal{color:var(--red,#C2412D)}",
      ".ams-keymsg.tibia{color:var(--amber,#C08A2E)}",
      ".ams-keymsg.ok{color:var(--green,#3E9C6A)}",
      // ── [F8 · obra 3] EL CATÁLOGO DEL PROVEEDOR ─────────────────────────────────
      ".amc{display:flex;flex-direction:column;gap:7px;min-width:0}",
      ".amc-search{width:100%;box-sizing:border-box;border:1px solid var(--line2,#2A2A30);background:var(--paper,#141416);color:var(--ink,#F5F5F6);border-radius:8px;padding:7px 9px;font:400 12px var(--font-ui)}",
      // Alto acotado + scroll propio: un proveedor puede traer 400 modelos (openrouter,
      // medido), y una lista sin techo empuja el resto del panel fuera de la pantalla.
      ".amc-list{display:flex;flex-direction:column;gap:3px;max-height:290px;overflow-y:auto;min-width:0}",
      ".amc-item{width:100%;min-width:0;display:flex;flex-direction:column;align-items:flex-start;gap:1px;text-align:left;border:0;background:var(--paper2,#1C1C1F);color:var(--ink,#F5F5F6);border-radius:8px;padding:7px 9px;cursor:pointer}",
      ".amc-item:hover{color:var(--accent-deep,#B7B5F5)}",
      ".amc-item.on{background:var(--accent-soft,rgba(141,139,238,.15));color:var(--accent-deep,#B7B5F5);cursor:default}",
      ".amc-id{font-size:12px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".amc-meta{font-size:9.5px;color:var(--faint,#A0A0A6)}",
      // El tag del vendor: chico, al lado del nombre, sin competirle.
      ".amc-marca{display:inline-flex;align-items:center;gap:3px;margin-left:6px;padding:1px 5px;" +
        "border:1px solid var(--line2,#2A2A30);border-radius:999px;font-size:9px;" +
        "color:var(--faint,#A0A0A6);vertical-align:middle;white-space:nowrap}",
      ".amc-marca-i{width:9px;height:9px;border-radius:2px;object-fit:contain}",
      ".amc-via{margin:0 0 8px;font:400 10.5px/1.45 var(--font-ui);color:var(--faint,#A0A0A6)}",
      // Ámbar, no rojo: la tabla vieja NO rompe nada —la lista que se ve es la del
      // proveedor— pero alguien tiene que arreglarla. Rojo diría «esto falló».
      ".amc-vieja{margin:0 0 8px;padding:7px 9px;border-radius:8px;" +
        "border:1px solid rgba(214,158,46,.35);background:rgba(214,158,46,.08);" +
        "font:400 10.5px/1.45 var(--font-ui);color:var(--warn,#D69E2E)}",
      ".amc-warn{color:var(--amber,#C08A2E)}",
      // [F9] el que no sirve de cerebro se ve apagado y no se puede apretar — pero se ve.
      ".amc-item.amc-nope{opacity:.55;cursor:not-allowed}",
      ".amc-item.amc-nope:hover{color:var(--ink,#F5F5F6)}",
      ".amc-on{color:var(--accent-deep,#B7B5F5)}",
      ".amc-fecha,.amc-empty{margin:0;font:400 10.5px/1.45 var(--font-ui);color:var(--faint,#A0A0A6)}",
      // La marca de la semilla va ARRIBA de la lista, no al pie: es la condición bajo la
      // que hay que leer todo lo de abajo, y una condición que se lee después ya no
      // condiciona nada.
      ".amc-semilla{margin:0 0 8px;padding:8px 10px;border:1px solid var(--line2,#2A2A30);" +
        "border-radius:8px;background:var(--paper2,#1A1A1E)}",
      ".amc-semilla-t{margin:0;font:500 11.5px/1.4 var(--font-ui);color:var(--ink,#F5F5F6)}",
      ".amc-semilla-d{margin:3px 0 0;font:400 10.5px/1.5 var(--font-ui);color:var(--faint,#A0A0A6)}",
      ".amc-semilla-d b{color:var(--ink,#F5F5F6);font-weight:500}",
      ".amc-auto{align-self:flex-start;border:1px solid var(--line2,#2A2A30);background:transparent;color:var(--muted,#AAA7C4);border-radius:8px;padding:6px 10px;font:400 11px var(--font-ui);cursor:pointer}",
      ".amc-msg{margin:0;font:400 11px/1.45 var(--font-ui);color:var(--muted,#AAA7C4)}",
      ".amc-msg[hidden]{display:none!important}",
      ".amc-msg.mal{color:var(--red,#C2412D)}",
      ".amc-usando{display:flex;align-items:center;gap:5px;flex-wrap:wrap;min-width:0;font:400 11px/1.4 var(--font-ui);color:var(--faint,#A0A0A6)}",
      ".amc-usando-m{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink,#F5F5F6);font-weight:400}",
      ".amc-cambiar{border:0;background:transparent;color:var(--accent-deep,#B7B5F5);padding:0 0 0 3px;font:400 11px var(--font-ui);cursor:pointer;text-decoration:underline}",
      "#ams-fallen{position:fixed;inset:0;z-index:9999;display:grid;place-items:center;padding:18px;background:rgba(7,8,18,.72)}",
      "#ams-fallen[hidden]{display:none!important}",
      ".ams-fallen-card{width:min(430px,94vw);border:1px solid var(--red,#C2412D);background:var(--paper,#141416);border-radius:14px;padding:18px;box-shadow:0 18px 60px rgba(0,0,0,.45)}",
      ".ams-fallen-card h2{font:500 17px/1.2 var(--font-display);margin:0 0 7px}",
      ".ams-fallen-card p{font:500 12.5px/1.5 var(--font-ui);color:var(--muted,#AAA7C4)}",
      ".ams-fallen-actions{display:flex;gap:8px;flex-wrap:wrap}",
      ".ams-fallen-actions button{border:1px solid var(--line2,transparent);background:var(--paper2,#1C1C1F);color:var(--ink,#F5F5F6);border-radius:8px;padding:8px 11px;font:500 11.5px var(--font-ui);cursor:pointer}",
    ].join("");
    document.head.appendChild(st);
  }
  function selectorHtml(opts) {
    opts = opts || {}; installSelectorCss();
    var lista = selectorOpciones(opts), elegido = selectorElegido(opts, lista);
    var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
    var rows = lista.map(function (m) {
      var conectado = m.conectado === true || m.connected === true;
      var def = !!m.default || m.slug === ((opts.data || selectorData(opts.contexto, opts.todos === true) || {}).default);
      var st = selectorEstado(m);
      // Un modelo que no está conectado no se puede USAR: ofrecerle «Usar este modelo»
      // es el verde falso otra vez, ahora en el botón. Lo que se ofrece es su trámite.
      var accion = conectado
        ? '<span class="ams-use">' + (m.id === elegido ? "En uso" : "Usar este modelo") + "</span>"
        : (st.tramite
            ? '<span class="ams-use ams-key">' + esc(st.tramite.label) + "</span>"
            : "");
      return '<button type="button" class="ams-option' + (m.id === elegido ? " on" : "") +
        (conectado ? "" : " ams-off") +
        '" data-model="' + esc(m.id) + '" data-slug="' + esc(m.slug) +
        '" data-connected="' + (conectado ? "1" : "0") + '"' +
        (st.tramite ? ' data-tramite="' + esc(st.tramite.accion || "llave") + '"' : "") +
        (st.tramite && (st.tramite.accion || "llave") === "llave"
          ? ' data-key-provider="' + esc(st.tramite.provider) + '"' : "") + ">" +
        '<span class="ams-main"><span class="ams-name"></span>' +
        (def ? '<span class="ams-badge">Default</span>' : "") +
        // [F8 · obra 3] QUÉ MODELO USA ESTA VÍA, en la fila. `sinBoton` NO: el [Cambiar] es
        // el único gesto que lleva al catálogo desde acá — pero NO lo abre en la fila, MANDA
        // AL PANEL (ver `selectorWire`). La ley de persona usuaria se cumple también en este host.
        (conectado ? enUsoHtml(m) : "") + "</span>" +
        '<span class="ams-side"><span class="ams-meta">' + esc(st.texto) + "</span>" +
        accion + "</span></button>" +
        (st.tramite ? '<div class="ams-keybox" data-keybox="' + esc(m.id) + '" hidden>' +
          '<input class="ams-keyin" type="password" autocomplete="off" spellcheck="false" ' +
          'placeholder="' + esc(t("brain.key.placeholder", "Pega o escribe tu llave de ") + (m.label || st.tramite.provider)) + '">' +
          '<button type="button" class="ams-keysave">' + esc(t("brain.key.save", "Guardar y probar")) + "</button>" +
          '<p class="ams-keymsg" hidden></p></div>' : "");
    }).join("");
    return '<div class="ams" data-contexto="' + String(opts.contexto || "default").replace(/"/g, "&quot;") + '">' +
      rows + '<button type="button" class="ams-option ams-add" data-add="1">＋ ' +
      t("brain.action.add_model", "Añadir otro modelo") + '</button></div>';
  }
  function selectorWire(host, opts) {
    opts = opts || {};
    var lista = selectorOpciones(opts);
    function reflectSelected(id) {
      host.querySelectorAll(".ams-option[data-model]").forEach(function (x) {
        var on = x.dataset.model === id;
        x.classList.toggle("on", on);
        var use = x.querySelector(".ams-use");
        if (use) use.textContent = on ? "En uso" : "Usar este modelo";
      });
    }
    // El [Cambiar] es un `span[role=button]` (no puede ser `<button>`: está dentro de uno).
    // El teclado no lo activa solo, así que Enter/Espacio se atan a mano — un control que
    // sólo responde al mouse es inalcanzable, que es el bug que Gate 1 persigue.
    host.querySelectorAll("[data-cambiar]").forEach(function (c) {
      c.onkeydown = function (ev) {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        ev.preventDefault(); ev.stopPropagation();
        location.href = window.AlephModelSelector.cambiarHref(c.dataset.cambiar);
      };
    });
    host.querySelectorAll(".ams-option[data-model]").forEach(function (b) {
      var m = lista.find(function (x) { return x.id === b.dataset.model; });
      var name = b.querySelector(".ams-name"); if (name && m) name.textContent = m.label || m.id;
      b.onclick = function (ev) {
        if (!m) return;
        // [F8 · obra 3] EL [Cambiar] NO ES «usar este modelo». Vive dentro de la fila, así
        // que su click llega acá: se intercepta y se MANDA AL PANEL. El catálogo no se abre
        // en la fila — ley sellada por persona usuaria, la misma que sacó el campo de llave de acá.
        var cambiar = ev && ev.target && ev.target.closest && ev.target.closest("[data-cambiar]");
        if (cambiar) {
          ev.preventDefault(); ev.stopPropagation();
          location.href = window.AlephModelSelector.cambiarHref(cambiar.dataset.cambiar);
          return;
        }
        var conectado = m.conectado === true || m.connected === true;
        // SIN LLAVE NO SE PUEDE ELEGIR: se abre el campo. Marcarlo como elegido y que el
        // fallo aparezca a mitad del turno es el verde falso que F7 vino a matar.
        // [F9] `data-tramite="probar"` NO abre el campo: la llave ya está, lo que falta es
        // medirla. Abrir el campo sería ofrecer borrar una credencial que puede estar bien.
        if (!conectado && b.dataset.tramite === "probar") {
          if (opts.onProbar) opts.onProbar(m);
          return;
        }
        if (!conectado && b.dataset.keyProvider) { abrirCampo(b, m); return; }
        if (!conectado) return;
        reflectSelected(m.id);
        var guardado = selectorPersist(opts.contexto, m);
        if (opts.onSelect) opts.onSelect(m, guardado);
        guardado.catch(function () {});
      };
    });

    /* ══ LA LLAVE SALE DE LA PÁGINA ═══════════════════════════════════════════════════
     *
     * Por la MISMA puerta que Modelos y Conectores (`POST /v1/conexiones/key`): valida
     * contra el proveedor con el validador discriminante, guarda cifrada, siembra el
     * motor. El `provider` sale de `byok_ref` —dato del backend—, no del nombre de la fila.
     *
     * Y EL RESULTADO SE PINTA CON LAS PALABRAS DEL BACKEND. Un `estado:"detectado"`
     * («la guardé, no la pude probar») sale 🟡 y el modelo NO queda elegido: sólo un
     * veredicto `probado` habilita usarlo.
     */
    function cajaDe(b) { return b.parentNode.querySelector('[data-keybox="' + CSS.escape(b.dataset.model) + '"]'); }
    function abrirCampo(b, m) {
      var caja = cajaDe(b); if (!caja) return;
      var abierta = !caja.hidden;
      host.querySelectorAll(".ams-keybox").forEach(function (c) { c.hidden = true; });
      caja.hidden = abierta;
      if (!caja.hidden) { var i = caja.querySelector(".ams-keyin"); if (i) i.focus(); }
    }
    function decir(caja, cls, texto) {
      var p = caja.querySelector(".ams-keymsg"); if (!p) return;
      p.className = "ams-keymsg" + (cls ? " " + cls : "");
      p.textContent = texto; p.hidden = !texto;
    }
    host.querySelectorAll(".ams-keybox").forEach(function (caja) {
      var b = host.querySelector('.ams-option[data-model="' + CSS.escape(caja.dataset.keybox) + '"]');
      var input = caja.querySelector(".ams-keyin");
      var boton = caja.querySelector(".ams-keysave");
      if (!b || !input || !boton) return;
      var m = lista.find(function (x) { return x.id === caja.dataset.keybox; });
      var enVuelo = false;
      async function guardar() {
        // GUARD DE VUELO: pegar + Enter + click son tres gestos encadenables, y la prueba
        // dura del validador es un POST de generación — se pagaría dos veces.
        if (enVuelo) return;
        var secret = (input.value || "").trim();
        if (secret.length < 8) {
          decir(caja, "mal", t("brain.key.short", "Esa llave es demasiado corta para ser una llave."));
          return;
        }
        enVuelo = true; boton.disabled = true;
        decir(caja, "", t("brain.key.checking", "Validando contra el proveedor…"));
        try {
          var r = await fetch("/v1/conexiones/key", {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ provider: b.dataset.keyProvider, secret: secret }),
          });
          var d = await r.json().catch(function () { return {}; });
          if (!r.ok || d.ok === false || d.estado === "roto") {
            var det = (d.detail && (d.detail.detail || d.detail.mensaje)) || d.mensaje || d.detalle;
            throw new Error(det || t("brain.key.rejected", "La llave no validó."));
          }
          input.value = "";
          var probada = d.estado === "probado";
          decir(caja, probada ? "ok" : "tibia",
                d.mensaje || (probada ? t("brain.key.ok", "Validada y guardada.")
                                      : t("brain.key.saved", "Guardada, sin probar.")));
          // La lista se relee del sidecar: la fila tiene que decir lo que el MOTOR midió,
          // no lo que este handler supuso.
          if (opts.onKey) opts.onKey(m, d, probada);
        } catch (e) {
          decir(caja, "mal", String((e && e.message) || e));
        } finally { enVuelo = false; boton.disabled = false; }
      }
      boton.onclick = guardar;
      input.onkeydown = function (ev) { if (ev.key === "Enter") { ev.preventDefault(); guardar(); } };
    });
    var add = host.querySelector("[data-add]");
    // «＋ Añadir otro modelo» lleva a CONECTORES, que es el vault: el destino único donde
    // una llave entra. Iba a `Modelos.dc.html` —la pantalla de elegir—, y desde un picker
    // que YA es la pantalla de elegir eso es un camino que vuelve al mismo lugar. No se
    // inventa pantalla: `conectoresHref` reusa el `ROOT` del propio script, igual que
    // `setupHref`.
    if (add) add.onclick = function () {
      if (opts.onAdd) return opts.onAdd();
      location.href = conectoresHref();
    };
  }
  function selectorRender(host, opts) {
    if (typeof host === "string") host = document.querySelector(host);
    if (!host) return null;
    host.innerHTML = selectorHtml(opts);
    selectorWire(host, opts);
    return host;
  }
  /** EL CEREBRO DE LA CASA ES UNO SOLO · escribe `preferencias-v2.default`.
   *
   * [TANDA 1 · obra 1 · decisión del dueño] Antes esto escribía
   * `contextos[<contexto>]`, o sea una elección POR SUPERFICIE. Medido el 2026-08-22
   * contra la `.app` instalada `d80109bb…`: esa elección no la leía **nadie** en el
   * camino que ejecuta —
   *
   *   · los seis workspaces resuelven por `router._model_use_catalog`, que pide el
   *     catálogo con `contexto=None` → `model_use_resolver.py:117` cae a
   *     `catalog["default_id"]`, que ES `preferencias-v2.default`;
   *   · la Sala resuelve igual (`POST /v1/puppets/run` sin `model`).
   *
   * O sea: `contextos` era un almacén que se escribía y no gobernaba nada. Con Grok
   * elegido en el picker respondía `claude-opus-5` con `degraded: null` — no un fallo,
   * un pedido que nunca salió. Poniendo `default = cli.grok_cli` los SIETE contestaron
   * `grok-4.6-build` sin tocar una línea. Así que el arreglo no es cablear un cuarto
   * camino: es que el picker escriba **la fuente que ya gobierna**.
   *
   * `contexto` se sigue recibiendo por firma —los hosts no cambian— y viaja en el evento
   * para que las superficies montadas se despierten igual; lo que ya no hace es partir la
   * elección en dos. */
  async function selectorPersist(contexto, modelo) {
    if (!modelo || !modelo.slug) return null;
    var r = await fetch("/v1/modelos/preferencias", {
      method: "PUT", headers: authHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
      body: JSON.stringify({ "default": modelo.slug }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    var d = await r.json();
    // TODOS LOS PAYLOADS EN CACHE, no los dos de este contexto. Antes se refrescaban
    // `selectorData(contexto)` y su gemelo `todos` porque la elección era de ESE contexto.
    // Ahora el cerebro es uno solo para la casa, así que una elección hecha en la Sala
    // tiene que dejar al Cuarto —cuyo payload está cacheado bajo OTRA clave— diciendo lo
    // mismo. Refrescar sólo dos dejaba al otro pintando la elección vieja hasta un F5: el
    // bug de «cambié en Diseño y Finanzas no se enteró», ahora del lado del navegador.
    Object.keys(_selectorCache).forEach(function (k) {
      var cache = _selectorCache[k];
      if (!cache) return;
      cache.seleccion = modelo.slug; cache.seleccion_id = modelo.id;
      cache["default"] = modelo.slug; cache.default_id = modelo.id;
      cache.contextos = d.contextos || {};
      // ⚠️ Y EL FLAG POR FILA, que es el que pinta el sello «Default».
      // `selectorHtml` decide el sello con `!!m.default || m.slug === data.default`: parchar
      // sólo la cabecera dejaba el `default:true` VIEJO en su fila, así que después de
      // elegir se veían DOS filas selladas Default a la vez. Visto en pantalla al montar el
      // picker en la barra de un workspace, pero el defecto es del componente COMPARTIDO —
      // o sea que Modelos y el Cuarto lo tenían igual. Una información, un dueño: si la
      // cabecera se parcha, la fila también.
      if (Array.isArray(cache.modelos)) {
        cache.modelos.forEach(function (row) {
          if (row) row["default"] = row.slug === modelo.slug;
        });
      }
    });
    // Una información, un dueño: el PUT de Modelos v2 sigue siendo la escritura
    // canónica. Este evento sólo despierta las superficies ya montadas para que Sala y
    // Cuarto reflejen ese mismo estado sin recargar ni crear un segundo almacén.
    window.dispatchEvent(new CustomEvent("aleph:model-selection", {
      detail: { contexto: String(contexto), id: modelo.id, slug: modelo.slug },
    }));
    try {
      if (_selectorChannel) _selectorChannel.postMessage({
        type: "selection", contexto: String(contexto), id: modelo.id, slug: modelo.slug,
      });
    } catch (e) {}
    return d;
  }

  /* ══ [GATE 2 · F8 · obra 3] EL CATÁLOGO DEL PROVEEDOR ══════════════════════════════
   *
   * ⚠️ VIVE ACÁ, EN EL COMPONENTE QUE YA EXISTE, Y NO EN UN MÓDULO NUEVO. La auditoría de
   * plataforma contó **cuatro catálogos de modelos** conviviendo; un quinto picker —aunque
   * fuera «el bueno»— sería el quinto lugar donde la misma pregunta se responde distinto.
   * Modelos y el Cuarto llaman a ESTAS funciones: si mañana el catálogo se ordena de otra
   * forma, se ordena de otra forma en los dos a la vez o en ninguno.
   *
   * REGLA SELLADA POR PERSONA USUARIA (2026-08-07): **el catálogo abre EN EL PANEL, nunca en la fila.**
   * Es la misma ley que sacó el `<input>` de llave de las filas en la obra 0 — una lista es
   * para comparar y elegir; el momento de configurar tiene su lugar, y es uno solo. Por eso
   * `catalogoRender` recibe un host y no lo inventa: la superficie que tiene panel lo pinta
   * adentro, y la que no tiene (el selector de la Sala) MANDA al panel en vez de abrirlo ahí.
   */
  /* ⚠️ DOS FRESCURAS DISTINTAS, Y CONFUNDIRLAS COSTÓ UNA VARA ROJA.
   *
   *   · `recargar` — no uses el caché DEL CLIENTE. Es lo que necesita el panel al abrirse:
   *     **qué modelo está en uso** puede haber cambiado desde otra superficie, y servirlo
   *     de un caché viejo es la card afirmando algo que ya no es cierto.
   *   · `fresco`   — que el BACKEND salga a la red del proveedor. Eso es caro y no hace
   *     falta para saber qué se está usando: el catálogo del proveedor cambia en días y
   *     tiene su propio caché fechado con la caducidad de F4c.
   *
   * La primera versión tenía una sola perilla para las dos: el panel reabierto mostraba el
   * `usando` cacheado y la vara lo cazó pidiendo el caso «hay llave y no hay modelo». */
  var _catalogoCache = {};
  async function catalogoLoad(slug, opts) {
    if (!slug) return null;
    opts = opts === true ? { recargar: true, fresco: true } : (opts || {});
    if (!opts.recargar && _catalogoCache[slug]) return _catalogoCache[slug];
    var r = await fetch("/v1/modelos/proveedor/" + encodeURIComponent(slug) + "/catalogo" +
                        (opts.fresco ? "?fresco=1" : ""),
                        { headers: authHeaders({ Accept: "application/json" }) });
    if (!r.ok) throw new Error("HTTP " + r.status);
    _catalogoCache[slug] = await r.json();
    return _catalogoCache[slug];
  }
  function catalogoData(slug) { return _catalogoCache[slug] || null; }

  /** Elegir un modelo para ESE proveedor. `modeloId` vacío = devolverle la decisión a Aleph.
   *
   * ⚠️ DESPUÉS DEL PUT SE RE-PREGUNTA EL CATÁLOGO, y no es una request de más. El backend
   * resuelve el modelo en uso con `_modelo_de_api` —preferencia del usuario, catálogo vivo,
   * semilla declarada, en ese orden— y al BORRAR la elección el cliente **no sabe** qué va a
   * re-elegir Aleph. Inventarlo acá sería fabricar el dato que toda esta obra existe para
   * no fabricar, y sería la quinta opinión sobre «qué modelo se usa». */
  async function usarModelo(slug, modeloId) {
    if (!slug) return null;
    var r = await fetch("/v1/modelos/preferencias", {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
      body: JSON.stringify({ slug: String(slug), modelo: modeloId || "" }),
    });
    if (!r.ok) {
      // El motivo del rechazo es del BACKEND y se muestra tal cual: «ese modelo ya no está
      // en el catálogo de groq» le dice a la persona qué pasó. Un «HTTP 409» no.
      var detalle = "";
      try { detalle = (await r.json()).detail || ""; } catch (e) {}
      throw new Error(detalle || ("HTTP " + r.status));
    }
    var pref = await r.json();
    var cat = await catalogoLoad(slug, { recargar: true }).catch(function () { return null; });
    var enUso = cat ? cat.usando : (modeloId || null);
    var porQuien = cat ? cat.elegido_por : (modeloId ? "usuario" : null);
    // El pool y el catálogo completo llevan `model`/`modelo_elegido` en la fila: quedaron
    // viejos. Se PARCHEAN con lo que dijo el backend (no con lo que el click pidió), igual
    // que `selectorPersist` hace con la selección de contexto.
    Object.keys(_selectorCache).forEach(function (k) {
      var cache = _selectorCache[k];
      if (!cache || !Array.isArray(cache.modelos)) return;
      cache.modelos.forEach(function (row) {
        if (!row || row.slug !== slug) return;
        if (enUso) row.model = enUso;
        row.modelo_elegido = enUso || null;
        row.modelo_elegido_por = porQuien || null;
      });
    });
    var detalle = { slug: String(slug), modelo: enUso || null, elegido_por: porQuien || null };
    window.dispatchEvent(new CustomEvent("aleph:model-choice", { detail: detalle }));
    try {
      if (_selectorChannel)
        _selectorChannel.postMessage(Object.assign({ type: "choice" }, detalle));
    } catch (e) {}
    return { preferencias: pref, catalogo: cat, usando: enUso, elegido_por: porQuien };
  }

  /** La línea que la card muestra: «usando X» + [Cambiar]. UNA sola redacción para las dos
   *  superficies — que Modelos diga «usando» y el Cuarto «modelo:» es cómo se llega a que
   *  parezcan dos productos. `elegido_por` decide el matiz, y por eso viaja desde el backend. */
  function enUsoTexto(fila) {
    var m = fila && (fila.modelo_elegido || fila.model);
    if (!m) return null;
    var por = fila.modelo_elegido_por;
    return {
      modelo: String(m),
      // «Elegido por vos» y «lo elegimos nosotros» NO son la misma frase, y el dato para
      // distinguirlas existe. Sin esto la card afirmaría una decisión que la persona no tomó.
      nota: por === "usuario" ? t("brain.model.byyou", "elegido por ti")
          : por === "catalogo" ? t("brain.model.bycatalog", "elegido del catálogo del proveedor")
          : por === "declarado" ? t("brain.model.byaleph", "elegido por Aleph")
          // La semilla NO es «elegido por Aleph» a secas: es «de nuestra tabla, y todavía
          // no lo confirmó el proveedor». Meterla en el mismo cajón que `declarado` le
          // sacaría a la persona el único dato que le dice por qué conviene poner la llave.
          : por === "semilla" ? t("brain.model.byseed", "de nuestra tabla · sin confirmar")
          : null,
      porQuien: por || null,
    };
  }
  function enUsoHtml(fila, opts) {
    opts = opts || {}; installSelectorCss();
    var u = enUsoTexto(fila);
    if (!u) return "";
    var slug = String((fila && fila.slug) || "");
    return '<div class="amc-usando" data-usando="' + _esc(slug) + '">' +
      '<span class="amc-usando-t">' + _esc(t("brain.model.using", "usando")) + " </span>" +
      '<b class="amc-usando-m">' + _esc(u.modelo) + "</b>" +
      (u.nota ? '<span class="amc-usando-n"> · ' + _esc(u.nota) + "</span>" : "") +
      // ⚠️ ES UN <span role="button">, NO UN <button>, Y NO ES UN CAPRICHO: esta línea se
      // pinta TAMBIÉN dentro de la fila del selector, que ya es un `<button>`. Un botón
      // anidado es HTML inválido —el navegador parte el botón externo— y la fila entera
      // dejaría de responder. Con `tabindex` y el manejo de Enter/Espacio en el wiring, el
      // gesto sigue siendo alcanzable por teclado, que es lo que el botón daba gratis.
      (opts.sinBoton ? "" :
        '<span class="amc-cambiar" role="button" tabindex="0" data-cambiar="' + _esc(slug) + '">' +
        _esc(t("brain.model.change", "Cambiar")) + "</span>") + "</div>";
  }

  function _esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /** El catálogo, buscable y con el elegido marcado. Orden: el que está EN USO primero, y
   *  después por contexto —el único tamaño que los proveedores declaran de forma comparable
   *  (la misma vara que usa `elegir()` en el backend)—. */
  /* ── EL UMBRAL DE LA BÚSQUEDA (traído de Diseño · `ModelSwitcher.tsx`) ──────────────
   * Debajo de esto el buscador es cromo: con ~12 modelos la persona los ve de un vistazo
   * y scrollea. Arriba, scrollear es una tarea — y acá no es hipotético: MEDIDO contra el
   * catálogo real, openrouter devuelve **410 modelos**. El umbral no está para el caso
   * grande, que obviamente lo necesita: está para que un proveedor con cuatro modelos no
   * arrastre un campo de texto que no sirve para nada. */
  var UMBRAL_BUSQUEDA = 12;

  /* ── EL NORMALIZADOR (traído de Diseño · `formatModelLabel`) ───────────────────────
   * Se usa SÓLO de respaldo, y por eso importa saber cuándo cae: MEDIDO contra el
   * catálogo real de openrouter, 410 de 410 filas traen `label` legible del proveedor
   * («AI21: Jamba Large 1.7»). Cuando el proveedor NO manda label, hoy se cae al
   * `model_id` crudo —`ai21/jamba-large-1.7`— y eso es lo que esto arregla.
   *
   * No se le pisa el label al proveedor: el catálogo declara, nosotros no inventamos. */
  function _titleCase(s) {
    return String(s).split(/[\s_-]+/).filter(Boolean).map(function (w) {
      return /^[A-Z0-9]+$/.test(w) ? w : w.slice(0, 1).toUpperCase() + w.slice(1);
    }).join(" ");
  }
  function formatModelLabel(modelId) {
    var id = String(modelId || "");
    var hoja = id.indexOf("/") >= 0 ? (id.split("/").pop() || id) : id;
    var gpt = hoja.match(/^gpt[-_]?(.+)$/i);
    if (gpt && gpt[1]) return "GPT-" + gpt[1];
    var claude = hoja.match(/^claude[-_](sonnet|opus|haiku)[-_](.+)$/i);
    if (claude && claude[1] && claude[2]) {
      return "Claude " + _titleCase(claude[1]) + " " + claude[2].replace(/-/g, ".");
    }
    var gemini = hoja.match(/^gemini[-_](.+)$/i);
    if (gemini && gemini[1]) return "Gemini " + gemini[1].replace(/-/g, " ");
    return hoja;
  }

  /* ── DE QUIÉN ES EL MODELO (traído de Ciencia · `displayProviderForModel`) ──────────
   * Una tabla de nombres lindos por prefijo de vendor. Es la MISMA figura que la de
   * Ciencia (`OPENROUTER_VENDOR_DISPLAY`, 15 entradas en su árbol), extendida con lo que
   * miden nuestros catálogos reales.
   *
   * ⚠️ ESTO SALIÓ DE UNA DECISIÓN ESCRITA QUE YO HABÍA DESOBEDECIDO. El censo de
   * convergencia declaró la fila de Ciencia como «la mejor cara de las 6» justamente
   * porque muestra los CUATRO datos que hacen falta para elegir —capacidad, ventana,
   * **proveedor** y costo— y recomendó traerla. La primera pasada trajo capacidad y
   * ventana y descartó el proveedor con el argumento de que era «la misma palabra 410
   * veces». El argumento era cierto para la MARCA DE LA TARJETA y falso para el vendor
   * del MODELO: medido sobre los catálogos vivos, las 420 filas con prefijo se reparten
   * entre **59 vendors distintos**.
   *
   * La tabla es corta a propósito: 15 vendors cubren el 77% de las filas, y lo que no
   * está NO se queda sin tag — cae al prefijo crudo, title-cased. Un nombre feo dice la
   * verdad; ninguna fila queda muda. */
  var VENDOR_DISPLAY = {
    anthropic: "Anthropic", openai: "OpenAI", google: "Google", gemini: "Google",
    "x-ai": "xAI", xai: "xAI", meta: "Meta", "meta-llama": "Meta Llama",
    deepseek: "DeepSeek", moonshotai: "Moonshot AI", "z-ai": "Z.AI", zai: "Z.AI",
    zhipuai: "Zhipu AI", mistralai: "Mistral", qwen: "Qwen", nvidia: "NVIDIA",
    minimax: "MiniMax", "bytedance-seed": "ByteDance", amazon: "Amazon",
    openrouter: "OpenRouter",
  };

  /* El vendor de una fila, SÓLO cuando aporta algo.
   *
   * Devuelve null si el id no trae prefijo, o si el vendor ES la marca de la tarjeta —
   * ahí sí sería la misma palabra repetida: adentro de la tarjeta de Anthropic, poner
   * «Anthropic» en las cinco filas no distingue nada. El tag existe para cuando el
   * modelo es de OTRO: `anthropic/claude-…` dentro de OpenRouter, o `openai/gpt-oss-120b`
   * dentro de Groq — que es exactamente el caso que no se veía. */
  function _plano(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9]/g, ""); }

  function vendorDeFila(modelId, marcaTarjeta, labelFila) {
    var id = String(modelId || "");
    var i = id.indexOf("/");
    if (i < 0) return null;
    var pref = id.slice(0, i).toLowerCase();
    if (!pref || pref === String(marcaTarjeta || "").toLowerCase()) return null;
    var nombre = VENDOR_DISPLAY[pref] || _titleCase(pref);
    /* ⚠️ SI EL NOMBRE YA LO DICE, EL TAG SE CALLA. Medido sobre los catálogos vivos:
     * de los 404 tags que salían en OpenRouter, **323 eran redundantes** — su propio
     * label ya nombra al vendor («AI21: Jamba Large 1.7», «Amazon: Nova 2 Lite»). Un tag
     * que repite la palabra de al lado no informa: ocupa. Los 81 que quedan sí aportan.
     * Y en Groq pasa lo contrario —7 de 8 aportan—, porque ahí el label es «GPT OSS 120B»
     * y sin el tag nadie sabe que es de OpenAI. La misma regla sirve para los dos. */
    var lbl = _plano(labelFila);
    if (lbl && (lbl.indexOf(_plano(pref)) >= 0 || lbl.indexOf(_plano(nombre)) >= 0)) return null;
    return { id: pref, label: nombre };
  }

  function catalogoHtml(opts) {
    opts = opts || {}; installSelectorCss();
    var slug = String(opts.slug || "");
    var data = opts.data || _catalogoCache[slug] || {};
    var modelos = Array.isArray(data.modelos) ? data.modelos : [];
    var usando = data.usando || null;
    var q = String(opts.q == null ? "" : opts.q).trim().toLowerCase();
    // SIN CATÁLOGO NO SE PINTA UNA LISTA VACÍA. Una lista de cero se lee como «este
    // proveedor no tiene modelos», que es una afirmación que nadie midió: lo que pasó es
    // que no se pudo traer. Se dice eso, con la causa que mandó el backend.
    if (!modelos.length) {
      var S = window.CuartoSemaforo;
      var cara = data.causa && S ? S.caraDeCausa({ causa: data.causa, detalle: "" }) : null;
      return '<div class="amc" data-slug="' + _esc(slug) + '" data-vacio="sin_catalogo">' +
        '<p class="amc-empty">' +
        _esc(cara ? cara.titulo : t("brain.catalog.none", "No se pudo traer el catálogo del proveedor.")) +
        '</p></div>';
    }
    var filtrados = q ? modelos.filter(function (m) {
      return String(m.model_id || "").toLowerCase().indexOf(q) >= 0 ||
             String(m.label || "").toLowerCase().indexOf(q) >= 0;
    }) : modelos.slice();
    filtrados.sort(function (a, b) {
      if ((a.model_id === usando) !== (b.model_id === usando)) return a.model_id === usando ? -1 : 1;
      return (b.context || 0) - (a.context || 0) ||
             String(a.model_id).localeCompare(String(b.model_id));
    });
    var items = filtrados.map(function (m) {
      var on = m.model_id === usando;
      var caps = m.capacidades || [];
      var vendor = vendorDeFila(m.model_id, data.marca || slug.split(".").pop(),
                                m.label || formatModelLabel(m.model_id));
      var meta = [];
      /* ── LA CAPACIDAD, PRIMERO (traído de Ciencia · `dialog-select-model.tsx`) ──────
       * Su fila abre con `reasoning | standard` antes de la ventana, y tiene razón en el
       * orden: qué SABE HACER el modelo pesa más que cuánto le entra. Acá el dato ya
       * viajaba en cada fila y no se pintaba: MEDIDO contra el catálogo real de
       * openrouter, de 410 filas 279 declaran `razonamiento` y 241 `vision`, y ninguna de
       * las dos cosas se veía. Sólo se decía lo que FALTABA («sin tool-calling»), así que
       * la lista sólo sabía hablar de carencias.
       *
       * Se dice lo que el catálogo DECLARA, ni una palabra más: `texto` y `tools` no se
       * listan porque son el piso —lo que no los tiene ya sale marcado abajo— y de las
       * demás se nombra lo que está. Nada se deriva ni se supone. */
      if (caps.indexOf("razonamiento") >= 0) meta.push(t("brain.catalog.reason", "razona"));
      if (caps.indexOf("vision") >= 0) meta.push(t("brain.catalog.vision", "ve imágenes"));
      if (m.context) meta.push(Math.round(m.context / 1000) + "k " + t("brain.catalog.ctx", "de contexto"));
      if (m.free === true) meta.push(t("brain.catalog.free", "gratis"));
      // ⚠️ «UN CEREBRO SIN TOOL-CALLING NO ES UN CEREBRO» (regla sellada en la obra 1). El
      // backend ya lo usa para desempatar; acá se DICE, porque si no la persona puede elegir
      // a mano justo el modelo con el que su agente no va a poder usar ninguna pieza — y se
      // enteraría a mitad del primer turno.
      var sinTools = caps.indexOf("tools") < 0;
      /* ⚠️ [F9] NO SIRVE DE CEREBRO ≠ NO TIENE TOOLS. Son dos avisos distintos y el segundo
       * es más grave: un modelo sin tool-calling PIENSA pero no puede usar piezas; uno que
       * no sirve **no genera texto** —`whisper` transcribe, `orpheus` habla— y el turno no
       * arranca. MEDIDO el 2026-08-07: 4 de los 15 del catálogo de groq son de ésos.
       *
       * `servible` lo declara el BACKEND con la MISMA función que decide el rechazo del PUT
       * (`_disc.servible`). Acá no se re-deriva de `capacidades`: dos criterios se separan,
       * y separarse significa ofrecer lo que la request siguiente va a rechazar.
       *
       * Se MARCA y se DESHABILITA; no se esconde. Esconder filas haría que la lista no
       * coincida con el catálogo del proveedor, y entonces «no está» y «no sirve» se leen
       * igual. Ausente ≠ inservible, otra vez. */
      var sirve = m.servible !== false;
      return '<button type="button" class="amc-item' + (on ? " on" : "") +
        (sirve ? "" : " amc-nope") + '"' + (sirve ? "" : " disabled") +
        ' data-modelo="' + _esc(m.model_id) + '"' +
        ' data-servible="' + (sirve ? "1" : "0") + '"' +
        (on ? ' aria-current="true"' : "") + ">" +
        '<span class="amc-id">' + _esc(m.label || formatModelLabel(m.model_id)) + "</span>" +
        /* El tag del vendor, con su logo si lo tenemos EN EL ÁRBOL. El `onerror` no es
         * pereza: de los 59 vendors sólo unos pocos tienen snapshot empaquetado, y
         * `/v1/icons/` devuelve 404 honesto para el resto. La fila degrada a texto sola,
         * sin pedirle nada a la red y sin dibujar un placeholder que finja una marca. */
        '<span class="amc-meta">' +
        /* El tag abre la meta en vez de tener línea propia: MIRADO en pantalla, con
         * `.amc-id` en `nowrap` el tag caía abajo del nombre y le robaba un renglón a
         * cada fila. Acá va en el renglón que ya existe. El `onerror` borra el logo que
         * no tenemos —de 59 vendors sólo unos pocos traen snapshot— y la fila degrada a
         * texto sola, sin pedirle nada a la red. */
        (vendor
          ? '<span class="amc-marca">' +
            '<img class="amc-marca-i" src="/v1/icons/' + encodeURIComponent(vendor.id) +
            '" alt="" onerror="this.remove()">' + _esc(vendor.label) + "</span> " +
            (meta.length ? "· " : "")
          : "") +
        _esc(meta.join(" · ")) +
        (!sirve ? '<span class="amc-warn"> · ' + _esc(m.motivo ||
            t("brain.catalog.nobrain", "no sirve de cerebro")) + "</span>"
         : sinTools ? '<span class="amc-warn"> · ' +
          _esc(t("brain.catalog.notools", "sin tool-calling")) + "</span>" : "") +
        (on ? '<span class="amc-on"> · ' + _esc(t("brain.catalog.inuse", "en uso")) + "</span>" : "") +
        "</span></button>";
    }).join("");
    var fecha = data.descubierto_en
      ? '<p class="amc-fecha">' + _esc(t("brain.catalog.asof", "catálogo del proveedor ·") + " " +
          String(data.descubierto_en).slice(0, 10) +
          (data.rancio ? " · " + t("brain.catalog.stale", "puede estar viejo") : "")) + "</p>"
      : "";

    /* ── LA MARCA DE LA SEMILLA ────────────────────────────────────────────────────────
     * Cuando el proveedor todavía no habló, la lista sale de la tabla del árbol. Eso hay
     * que DECIRLO, y decirlo bien: la marca **no es «puede estar mal»**, que sólo siembra
     * desconfianza y no le da a nadie nada que hacer. Es de QUIÉN es el dato — y de ahí
     * sale sola la acción: conectá tu llave y te lo dice el dueño del modelo.
     *
     * También dice que son LOS PRINCIPALES, no todos: la tabla está acotada a propósito
     * (~31 filas contra 113 vigentes) porque una tabla larga envejece más rápido. Callarlo
     * sería mentir por omisión — el usuario creería que ése es el catálogo entero. */
    /* ── «VÍA <la tarjeta>» — UNA VEZ, NO EN CADA FILA ────────────────────────────────
     * Sin esto, `Anthropic: Claude 3 Haiku` adentro de la tarjeta de OpenRouter se lee
     * como si el turno saliera a Anthropic. No sale: MEDIDO con `compileModel`, elegir
     * esa fila compila `base_url: openrouter.ai` y `byok_ref: keys:openrouter`. El modelo
     * es de su marca; la CONEXIÓN es del intermediario, y las dos cosas tienen que estar
     * dichas.
     *
     * Va en la tarjeta y no en la fila porque es constante para las 410: repetirlo abajo
     * de cada una sería el ruido que el tag de vendor vino justamente a evitar. */
    var viaN = filtrados.filter(function (m) {
      return vendorDeFila(m.model_id, data.marca || slug.split(".").pop(),
                          m.label || formatModelLabel(m.model_id));
    }).length;
    var via = viaN
      ? '<p class="amc-via">' + _esc(
          t("brain.catalog.via", "El modelo es de su marca; la conexión es de") + " " +
          String(data.label || slug) + ".") + "</p>"
      : "";

    /* ── LA TABLA ENVEJECIÓ, Y SE DICE ────────────────────────────────────────────────
     * Sólo aparece cuando el proveedor YA habló y contradijo a nuestra tabla. Es el
     * único momento en que se puede afirmar: antes de la llave no hay veredicto.
     *
     * Se separan los dos hallazgos porque no se resuelven igual. Un id MUERTO es grave —
     * la tabla estaba ofreciendo un modelo que no existe— y una ficha distinta es un
     * detalle equivocado sobre algo que sí está. Meterlos en el mismo número dejaría a
     * quien lo lea sin saber si tiene que arreglar la tabla hoy o cuando pueda. */
    var vejez = "";
    var _cv = data.semilla_contraste;
    if (_cv && (_cv.muertos || []).length + (_cv.distintos || []).length) {
      var _pz = [];
      var _nm = (_cv.muertos || []).length, _nd = (_cv.distintos || []).length;
      // Concordancia: «1 que ofrecíamos y ya no existen» es un cartel que se lee mal y
      // por lo tanto se cree menos. Lo cazó mirarlo en pantalla, no la medición.
      if (_nm) {
        _pz.push(_nm + " " + (_nm === 1
          ? t("brain.catalog.stale.dead1", "modelo que ofrecíamos y ya no existe")
          : t("brain.catalog.stale.dead", "modelos que ofrecíamos y ya no existen")));
      }
      if (_nd) {
        _pz.push(_nd + " " + (_nd === 1
          ? t("brain.catalog.stale.diff1", "con la ficha cambiada")
          : t("brain.catalog.stale.diff", "con la ficha cambiada")));
      }
      vejez = '<p class="amc-vieja">' + _esc(
        t("brain.catalog.stale.t", "Nuestra tabla quedó vieja:") + " " + _pz.join(" · ") +
        ". " + t("brain.catalog.stale.d", "Manda la lista de arriba, que es la del proveedor.")
      ) + "</p>";
    }

    var marca = "";
    if (data.fuente === "semilla") {
      var quien = _esc(String(data.label || slug));
      /* ⚠️ EL PORQUÉ SALE DE LAS FILAS, NO SE SUPONE. La primera versión decía «esto lo
       * dice OpenRouter» en TODAS las tarjetas sembradas — y en la de Together era falso:
       * sus filas son un HUECO (`sin_dato`), no una lectura de OpenRouter. Una marca de
       * honestidad que miente sobre su propia procedencia es peor que no ponerla. Se
       * decide por lo que cada fila declara en `fuente_dato`. */
      var hayOtro = filtrados.some(function (m) { return m.fuente_dato === "otro_proveedor"; });
      var porque = hayOtro
        ? t("brain.catalog.seed.why",
            "Esto lo dice OpenRouter sobre modelos de <b>__QUIEN__</b>. " +
            "Conecta tu llave y te lo dice <b>__QUIEN__</b>.")
        : t("brain.catalog.seed.blank",
            "Sabemos que existe, no qué hace: nadie nos publicó su ficha. " +
            "Conecta tu llave y te la da <b>__QUIEN__</b>.");
      marca = '<div class="amc-semilla">' +
        '<p class="amc-semilla-t">' +
        _esc(t("brain.catalog.seed.scope", "Los principales de") + " " + String(data.label || slug) +
             t("brain.catalog.seed.scope2", ", no todos.")) + "</p>" +
        '<p class="amc-semilla-d">' + porque.replace(/__QUIEN__/g, quien) + "</p></div>";
    }
    // El buscador aparece SÓLO si hay lista que buscar. El umbral mira `modelos`, no
    // `filtrados`: si mirara lo filtrado, tipear hasta dejar menos de 12 resultados haría
    // desaparecer el campo con el foco adentro.
    var conBuscador = modelos.length > UMBRAL_BUSQUEDA;
    return '<div class="amc" data-slug="' + _esc(slug) + '" data-n="' + filtrados.length + '">' +
      (conBuscador
        ? '<input class="amc-search" type="search" autocomplete="off" spellcheck="false" ' +
          'placeholder="' + _esc(t("brain.catalog.search", "Buscar modelo…")) + '" value="' + _esc(q) + '">'
        : "") +
      marca + vejez + via +
      '<div class="amc-list">' + (items ||
        '<p class="amc-empty">' + _esc(t("brain.catalog.nomatch", "Ningún modelo coincide.")) + "</p>") +
      "</div>" + fecha +
      // Devolverle la decisión a Aleph tiene que ser un gesto visible: sin él, quien probó
      // un modelo una vez queda casado con él para siempre.
      (usando && data.eleccion_del_usuario
        ? '<button type="button" class="amc-auto">' +
          _esc(t("brain.catalog.auto", "Que elija Aleph")) + "</button>"
        : "") +
      '<p class="amc-msg" hidden></p></div>';
  }

  function catalogoWire(host, opts) {
    opts = opts || {};
    if (typeof host === "string") host = document.querySelector(host);
    if (!host) return null;
    var slug = String(opts.slug || (host.querySelector(".amc") || {}).dataset &&
                      host.querySelector(".amc").dataset.slug || "");
    var msg = host.querySelector(".amc-msg");
    var buscador = host.querySelector(".amc-search");
    function decir(texto, mal) {
      if (!msg) return;
      msg.hidden = !texto; msg.textContent = texto || "";
      msg.className = "amc-msg" + (mal ? " mal" : "");
    }
    if (buscador) {
      // Re-pinta SÓLO la lista: re-renderizar todo se llevaría puesto el foco y lo tipeado.
      buscador.oninput = function () {
        var lista = host.querySelector(".amc-list");
        if (!lista) return;
        var tmp = document.createElement("div");
        tmp.innerHTML = catalogoHtml({ slug: slug, data: opts.data, q: buscador.value });
        var nueva = tmp.querySelector(".amc-list");
        if (nueva) { lista.innerHTML = nueva.innerHTML; atarItems(); }
      };
    }
    function elegir(modeloId, boton) {
      if (boton) boton.disabled = true;
      decir(t("brain.catalog.saving", "Guardando…"), false);
      usarModelo(slug, modeloId).then(function (res) {
        decir("", false);
        /* ⚠️ EL CATÁLOGO SE RE-PINTA, Y LA VARA LO CAZÓ. Sin esto quedaba mostrando el
         * estado ANTERIOR después de elegir: la marca «en uso» seguía sobre el modelo
         * viejo y el [Que elija Aleph] —que sólo existe cuando hay elección propia— no
         * aparecía nunca. O sea, el picker afirmaba lo contrario de lo que acababa de
         * pasar, que es el fallo mudo con otra cara.
         *
         * Se re-pinta con `catalogoData(slug)` —lo que devolvió el backend en `usarModelo`,
         * no lo que el click pidió— y se CONSERVA lo tipeado: perder la búsqueda después de
         * elegir obligaría a re-escribirla para comparar dos modelos. */
        var q = buscador ? buscador.value : "";
        host.innerHTML = catalogoHtml({ slug: slug, data: catalogoData(slug), q: q });
        catalogoWire(host, Object.assign({}, opts, { data: catalogoData(slug) }));
        if (opts.onPick) opts.onPick(res);
      }).catch(function (e) {
        decir(String((e && e.message) || e), true);
      }).then(function () { if (boton) boton.disabled = false; });
    }
    function atarItems() {
      host.querySelectorAll(".amc-item").forEach(function (b) {
        b.onclick = function () {
          if (b.classList.contains("on")) return;      // ya está en uso: no se re-guarda
          // [F9] El `disabled` del botón ya lo frena; esto es el cinturón: si alguien
          // repinta sin el atributo, no se manda igual un PUT que sabemos que sale 409.
          if (b.dataset.servible === "0") return;
          elegir(b.dataset.modelo, b);
        };
      });
    }
    atarItems();
    var auto = host.querySelector(".amc-auto");
    if (auto) auto.onclick = function () { elegir("", auto); };
    return host;
  }
  function catalogoRender(host, opts) {
    if (typeof host === "string") host = document.querySelector(host);
    if (!host) return null;
    host.innerHTML = catalogoHtml(opts);
    catalogoWire(host, opts);
    return host;
  }

  function selectorFallen(contexto, modelo, opts) {
    installSelectorCss(); opts = opts || {};
    var dlg = document.getElementById("ams-fallen");
    if (!dlg) {
      dlg = document.createElement("div"); dlg.id = "ams-fallen";
      dlg.innerHTML = '<section class="ams-fallen-card" role="alertdialog" aria-modal="true">' +
        '<h2>El Default no está disponible</h2><p></p><div class="ams-fallen-actions">' +
        '<button type="button" data-reconnect>Reconectar</button><button type="button" data-other>Usar otro conectado</button></div></section>';
      document.body.appendChild(dlg);
    }
    dlg.hidden = false;
    dlg.querySelector("p").textContent = (modelo.label || "El modelo") +
      " sigue siendo tu Default, pero ahora está caído.";
    dlg.querySelector("[data-reconnect]").onclick = function () {
      dlg.hidden = true; location.href = setupHref({ brain: modelo.slug, returnTo: location.pathname + location.search });
    };
    dlg.querySelector("[data-other]").onclick = function () {
      var otro = selectorOpciones({ contexto: contexto, modelos: opts.modelos, data: opts.data })
        .find(function (m) { return (m.conectado === true || m.connected === true) && m.id !== modelo.id; });
      dlg.hidden = true;
      if (otro) {
        var guardado = selectorPersist(contexto, otro);
        if (opts.onAlternate) opts.onAlternate(otro, guardado);
        guardado.catch(function () {});
      } else location.href = setupHref({ returnTo: location.pathname + location.search });
    };
  }
  function selectorGuard(contexto, id, opts) {
    opts = opts || {};
    var lista = selectorOpciones({ contexto: contexto, modelos: opts.modelos, data: opts.data, seleccionado: id });
    var data = opts.data || selectorData(contexto) || {};
    var m = lista.find(function (x) { return x.id === id; });
    if (!m) return false;
    if (m.conectado === true || m.connected === true) return true;
    var esDefault = m.default === true || m.slug === data.default;
    if (!esDefault) return false;
    selectorFallen(contexto, m, opts);
    return false;
  }
  window.AlephModelSelector = {
    load: selectorLoad, seed: selectorSeed, data: selectorData,
    options: selectorOpciones, selectedId: selectorElegido,
    html: selectorHtml, wire: selectorWire, render: selectorRender,
    persist: selectorPersist, guardUse: selectorGuard,
    // [F8 · obra 3] EL CATÁLOGO DEL PROVEEDOR — el MISMO para Modelos y para el Cuarto.
    catalogo: catalogoLoad, catalogoData: catalogoData, catalogoHtml: catalogoHtml,
    catalogoWire: catalogoWire, catalogoRender: catalogoRender,
    usarModelo: usarModelo, enUso: enUsoTexto, enUsoHtml: enUsoHtml,
    // El href al panel: la superficie SIN panel (el selector de la Sala) manda acá en vez
    // de abrir el catálogo en la fila. Una sola función arma el destino.
    cambiarHref: function (slug) {
      return setupHref({ brain: slug, returnTo: location.pathname + location.search }) +
             "&catalogo=1";
    },
  };
  window.AlephBrain = {
    resolve: resolve,
    providersCache: providersCache,
    serviceCache: serviceCache,
    mount: mount,
    render: render,
    setActive: setActive,
    stateLabel: stateLabel,
    modelToSelected: modelToSelected,
    normalizeSelected: normalizeSelected,
    getConfiguration: getConfiguration,
    setConfiguration: setConfiguration,
    configurationToSelected: configurationToSelected,
    cerebroElegido: cerebroElegido,
    elegirCerebro: elegirCerebro,
    conectoresHref: conectoresHref,
    setupHref: setupHref,
    setupHrefPorCausa: setupHrefPorCausa,
    CAT_DE_CAUSA: CAT_DE_CAUSA,
    POWER: POWER,
    isCliId: isCliId,
    applyCliCatalog: applyCliCatalog,
    cliCatalog: function () { return CLI_CATALOG.slice(); },
    cliOrder: function () { return ORDEN_CLI.slice(); },
    modelSelector: window.AlephModelSelector,
  };
})();
