/* cuarto.inspect.js — CONSUMIDOR DEL MOTOR B dentro del Cuarto (Ola 1 · 1a coreografía + 1c dispatch).
 *
 * UN SOLO consumidor SSE para el botón "Inspeccionar". Va por el DESPACHADOR §0.5 (1c):
 *   POST /v1/inspect/dispatch  {service, url, credential, forma:"token", puppet_id, …}
 * que BUSCA-ANTES-DE-FORJAR: si el resolver encuentra un MCP verificado lo trae del registry
 * (sin forjar); si no, dispara el MOTOR B (la MISMA forja de /v1/inspect/forge) embebida en el
 * stream. Este módulo lee ESE ÚNICO stream y reparte responsabilidades:
 *
 *   1-A (coreografía, `applyChoreography`) — dueña del stream desde sesion.ok hasta "listas para
 *        sellar": dibuja api.forge (draw-pass aparte) 1:1 con eventos REALES (cero-teatro):
 *          forge.iniciado → sesion.ok(conecta) → observando → tool.propuesta×N (fantasmas)
 *            → tool.validando (pulso) → tool.validada (sólida) / tool.descartada (desvanece)
 *            → mcp.forjado (listas para sellar)
 *   1-B (materialización, cuarto.forge.js) — dueña desde mcp.forjado: con los eventos del MISMO
 *        stream, `equipForgedMcp` vuelve el MCP forjado una PIEZA REAL (server≠null + belt_ref +
 *        puppet_id), usable en RUN. El camino FOUND del resolver usa `equipResolvedMcp`.
 *
 * UN clic → UN fetch → UN run → la coreografía y el equip corren sobre ESE mismo stream. No hay
 * dos fetch ni dos forjas. El endpoint es POST→text/event-stream (EventSource sólo hace GET): se
 * lee con fetch+ReadableStream y se parsean los frames SSE a mano.
 */

import { equipForgedMcp, equipResolvedMcp } from "./cuarto.forge.js";

// parsea un frame SSE ("event: <t>\ndata: <json>") → objeto del evento (o null).
// La sesión (Bearer) — contrato ÚNICO AlephSession (auth.js), MISMO que cuarto.pixi.html/
// sala.html: el muro premium server-side resuelve el tier POR LA SESIÓN; sin este header la
// construcción corre como anónima → free → 402 aunque el usuario pague. (Caso 3 · blocker:
// la cara final no autenticaba forge/dispatch.) El fallback dual sessionStorage→localStorage
// cubre contextos sin auth.js cargado; localStorage es lo que sobrevive relaunches del shell
// Tauri (GAP §Tauri-c — leer solo sessionStorage = deslogueado en cada arranque de la .app).
function _sessAuth(h) {
  h = h || {};
  try {
    const u = (window.AlephSession && window.AlephSession.get)
      ? window.AlephSession.get()
      : JSON.parse(sessionStorage.getItem("puppet_user") || localStorage.getItem("puppet_user") || "null");
    if (u && u.session_token) h["Authorization"] = "Bearer " + u.session_token;
  } catch (e) { /* sin sesión → run anónimo intacto */ }
  return h;
}

function parseFrame(frame) {
  let type = null, data = null;
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) data = line.slice(5).trim();
  }
  if (data == null) return null;
  let ev;
  try { ev = JSON.parse(data); } catch { ev = { type, _raw: data }; }
  if (!ev.type && type) ev.type = type;
  return ev;
}

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

/** Mensaje humano desde el `detail` de un rechazo HTTP del borde. Un 422 de Pydantic trae
 *  ARRAY de {loc,msg} — sin esto el HUD mostraba el JSON crudo. */
function _httpErrMsg(det, status) {
  if (Array.isArray(det)) return det.map((d) => `${((d && d.loc) || []).join(".")}: ${(d && d.msg) || ""}`).join(" · ");
  if (det && typeof det === "object") return det.reason || det.detail || det.error || JSON.stringify(det);
  if (typeof det === "string" && det) return _humanizeGuard(det);
  return `HTTP ${status}`;
}

/* [ssrf-consent] traduce el motivo TÉCNICO del guard SSRF a lenguaje de persona (estándar "dos
 * personas"): la razón cruda ("esquema no permitido: http…") no le dice nada a alguien no técnico. */
function _humanizeGuard(msg) {
  const m = String(msg || "");
  if (/esquema no permitido: http\b/i.test(m) || /guard SSRF/i.test(m) && /http\b/i.test(m)) {
    return "Tu servidor usa http:// y no es local. Por seguridad sólo forjamos targets públicos por " +
           "https:// o servidores tuyos en tu red local. Si es tu servidor self-hosted, márcalo como local.";
  }
  if (/IP no pública|no pública|SSRF|loopback|host local prohibido/i.test(m)) {
    return "Ese destino está en una red privada. Si es tu propio servidor self-hosted, márcalo como local " +
           "para conectarlo; si no, no podemos alcanzarlo por seguridad.";
  }
  return m;
}

/* [ssrf-consent] ¿la URL apunta a un servidor local/self-hosted del usuario? Detección de
 * conveniencia — el backend es la ÚNICA autoridad (guard: abre SÓLO el host:port EXACTO y sólo si
 * es una IP literal loopback/privada o el nombre 'localhost'). Espejamos ESA política acá para no
 * anunciar "local" y que el server luego bloquee: sólo IP literal loopback/RFC1918 o 'localhost'.
 * Los nombres .local/.internal NO se auto-marcan (el server los rechaza → posible DNS-rebinding);
 * link-local/metadata (169.254) tampoco. Un usuario con un nombre así puede usar la IP directa. */
function _looksLocal(u) {
  if (!u) return false;
  let h;
  try { h = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(u) ? u : "http://" + u).hostname.toLowerCase(); }
  catch { return false; }
  if (!h) return false;
  h = h.replace(/^\[|\]$/g, "");                                        // IPv6 entre corchetes
  if (h === "169.254.169.254" || /^169\.254\./.test(h)) return false;  // metadata/link-local: nunca
  if (h === "localhost" || h === "::1" || /^127\./.test(h)) return true;
  if (/^10\./.test(h) || /^192\.168\./.test(h) || /^172\.(1[6-9]|2\d|3[01])\./.test(h)) return true;
  return false;
}

/**
 * 1-A · COREOGRAFÍA — un evento del contrato → su transición REAL en api.forge (draw-pass aparte).
 * CERO-TEATRO: cada llamada a api.forge.* mapea 1:1 a un evento REAL; no inventa transiciones.
 * Reusada por `startForgeInspection` (stream /forge) Y por `inspectAndEquip` (stream /dispatch).
 */
export function applyChoreography(api, ev, { host = "target", onState = () => {} } = {}) {
  switch (ev.type) {
    case "forge.iniciado":
      onState(`<b>Motor B</b> arrancó · modelo <span style="color:var(--muted)">${_esc(ev.modelo || "?")}</span>`);
      break;
    case "sesion.ok":
      api.forge.session({ host });
      onState(`conectado a <b>${_esc(host)}</b> ✓ <span style="color:var(--muted)">(${_esc(ev.validate_status || "ok")})</span>`);
      break;
    case "observando":
      api.forge.observe();
      onState(`observando <b>${_esc(host)}</b>… <span style="color:var(--muted)">ronda ${ev.round ?? 1}</span>`);
      break;
    // narración pura (HUD): jamás api.forge.* — el latido no es una transición del motor
    case "sintetizando":
      onState(`el modelo <span style="color:var(--muted)">${_esc(ev.modelo || "?")}</span> sintetiza tools… <span style="color:var(--muted)">ronda ${ev.round ?? 1}</span>`);
      break;
    case "forge.latido":
      onState(`forjando… <span style="color:var(--muted)">${ev.elapsed_s ?? "?"}s · ${_esc(ev.stage || "")}</span>`);
      break;
    case "tool.propuesta":
      api.forge.propose({ name: ev.nombre, endpoint: ev.endpoint, method: ev.method, kind: ev.kind });
      onState(`propuesta <b>${_esc(ev.nombre)}</b> <span style="color:var(--muted)">${_esc(ev.method || "")} ${_esc(ev.endpoint || "")}</span>`);
      break;
    case "tool.validando":
      api.forge.validating(ev.nombre);
      onState(`validando <b>${_esc(ev.nombre)}</b>…`);
      break;
    case "tool.validada":
      api.forge.validated(ev.nombre);
      onState(`✓ <b>${_esc(ev.nombre)}</b> validada <span style="color:var(--muted)">(${_esc(ev.status ?? ev.verified_by ?? "ok")})</span>`);
      break;
    case "tool.descartada":
      api.forge.discarded(ev.nombre, ev.motivo);
      onState(`✗ <b>${_esc(ev.nombre)}</b> descartada <span style="color:var(--muted)">${_esc((ev.motivo || "").toString().slice(0, 60))}</span>`);
      break;
    case "mcp.forjado":
      api.forge.forged();
      onState(`forjado <b>${_esc(ev.server || "MCP")}</b> · ${(ev.tools || []).length} tool${(ev.tools || []).length === 1 ? "" : "s"} listas para sellar`);
      break;
    case "cerrado":
      api.forge.end();
      break;
    case "error":
      api.forge.end();
      onState(`<span style="color:var(--gate)">error en ${_esc(ev.stage || "el motor")}: ${_esc(ev.detail || (ev.degraded ? "el modelo no respondió (degradado)" : ""))}</span>`);
      break;
  }
}

/**
 * STANDALONE (1-A) · arranca una inspección del Motor B por /v1/inspect/forge y la pinta como
 * coreografía. NO materializa la pieza (eso lo hace `inspectAndEquip` con 1-B). Backward-compat de
 * verify_1a_coreografia.mjs.
 * @returns {Promise<{ok:boolean, events?:Array, error?:string}>}
 */
export async function startForgeInspection({ api, url, cred, puppetId, onState = () => {}, onEvent = null, seedProbes = null,
  forma = "token", apiShapeHint = "", validatePath = null, localTarget = null, loginPath = "/login", loginCredentials = null,
  loginTokenWhere = "json", loginTokenKey = "access_token", loginInjectWhere = "header",
  loginInjectName = "Authorization", loginInjectTemplate = "Bearer {token}", loginBodyFormat = "json" }) {
  const host = String(url || "").replace(/^https?:\/\//, "").split("/")[0] || "target";
  api.forge.begin({ url, host });
  onState(`conectando al <b>Motor B</b> · ${_esc(host)}…`);

  const body = { url, cred, forma, puppet_id: puppetId };
  if ((localTarget != null ? !!localTarget : _looksLocal(url))) body.local_target = true;  // [ssrf-consent]
  if (validatePath) body.validate_path = validatePath;
  if (apiShapeHint) body.api_shape_hint = apiShapeHint;
  if (forma === "login") {
    body.login_path = loginPath; body.login_credentials = loginCredentials || {};
    body.login_token_where = loginTokenWhere; body.login_token_key = loginTokenKey;
    body.login_inject_where = loginInjectWhere; body.login_inject_name = loginInjectName;
    body.login_inject_template = loginInjectTemplate; body.login_body_format = loginBodyFormat;
  }
  if (seedProbes && seedProbes.length) body.seed_probes = seedProbes;

  let resp;
  try {
    resp = await fetch("/v1/inspect/forge", {
      method: "POST",
      headers: _sessAuth({ "Content-Type": "application/json", "Accept": "text/event-stream" }),
      body: JSON.stringify(body),
    });
  } catch (e) {
    onState(`<span style="color:var(--gate)">no pude conectar al Motor B: ${e.message}</span>`);
    api.forge.end();
    return { ok: false, error: e.message };
  }

  // rechazo HONESTO del borde (400 url/cred/forma · 429 rate-limit · SSRF guard): el contrato falla
  // ANTES de abrir el stream → leemos el JSON de error y lo decimos tal cual (no fingimos coreografía).
  if (!resp.ok) {
    let det = null;
    try { det = (await resp.json()).detail; } catch {}
    const msg = _httpErrMsg(det, resp.status);
    const errEv = { type: "error", stage: "borde", status: resp.status, detail: det ?? msg };
    if (onEvent) { try { onEvent(errEv); } catch {} }   // evidencia del rechazo pre-stream
    onState(`<span style="color:var(--gate)">no pude inspeccionar (HTTP ${resp.status}): ${_esc(msg)}</span>`);
    api.forge.end();
    return { ok: false, error: String(msg), events: [errEv] };
  }

  const events = await _consumeStream(resp, (ev) => {
    if (onEvent) { try { onEvent(ev); } catch {} }
    applyChoreography(api, ev, { host, onState });
  }, () => api.forge.end());
  if (events.error) return { ok: false, error: events.error, events: events.list };

  api.forge.end();
  return { ok: true, events: events.list };
}

/**
 * UNIFICADO (1-A coreografía + 1-B equip + 1-C dispatch) · el camino de PRODUCTO del botón
 * "Inspeccionar": UN fetch al despachador → coreografía sobre el stream → al cerrar, materializa la
 * pieza (forjada del Motor B, o traída del registry). Sin segundo fetch ni segunda forja.
 *
 * @param {object}   opts.api
 * @param {string}   opts.service     - nombre del servicio o URL (lo que el resolver busca)
 * @param {string}   [opts.url]       - URL base REST para forjar si el resolver da miss
 * @param {string}   [opts.cred]      - credencial / token (forma="token")
 * @param {string}   [opts.puppetId]
 * @param {string}   [opts.label]
 * @param {function} [opts.onState]   - HUD
 * @param {function} [opts.onEvent]   - callback(ev) crudo (verificación)
 * @param {string}   [opts.authIn]    - "query" | "header" (defaults Forma 1 / TMDB)
 * @param {Array}    [opts.seedProbes]      - VERIFICACIÓN (env PUPPET_FORGE_ALLOW_SEED_PROBES)
 * @param {Array}    [opts.seedCandidates]  - VERIFICACIÓN (env PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES)
 * @param {object}   [opts.seedSpec]        - VERIFICACIÓN: run-spec del equip (MCP local real)
 * @param {object}   [opts.manual]          - 2d · GANCHO MANUAL OPCIONAL (controllerForRun de cuarto.manual.js).
 *                                            null = flujo AUTOMÁTICO (byte-idéntico; es lo que usan los
 *                                            consumidores headless). Si viene, modula QUÉ entra al belt
 *                                            sin tocar 1-A/1-B ni el modelo de relaciones:
 *                                              · reviewBeforeSeal(emit) — Promise<{keep:Set,drop:Set}|null>
 *                                              · cleanup()              — cierra el panel
 * @returns {Promise<{ok, path, origin, piece?, server?, belt_ref?, tools?, events, reason?, rejected_impostor?}>}
 */
export async function inspectAndEquip({
  api, service, url = null, cred = null, puppetId = null, label = null,
  onState = () => {}, onEvent = null,
  authIn = "query", authParam = "api_key", authHeader = "Authorization",
  authTemplate = "Bearer {token}", validatePath = "/configuration",
  synthAlias = "brain", maxRounds = 3,   // el forge de PRODUCTO sintetiza con el modelo real (shim/OpenRouter); sin fallback silencioso a oss
  seedProbes = null, seedCandidates = null, seedSpec = null,
  manual = null,   // 2d · gancho de revisión opcional (modula qué entra al belt)
  // [2f-formas] la FORMA de sesión rutea al SessionProvider del Motor B (abierto · token · login).
  // [3-browser-oauth] forma="browser-oauth": la sesión la capturó ANTES el HUMANO (browser+2FA);
  //   acá sólo viaja su `sessionKey` para que el Motor B REUSE esa sesión y forje (línea roja §2:
  //   el motor NUNCA resuelve el 2FA). La captura la hace cuarto.browser.js (subsistema aparte).
  forma = "token", apiShapeHint = "", sessionKey = null, loginUrl = null,
  localTarget = null,   // [ssrf-consent] null = auto-detectar (loopback/red privada); true/false = forzar
  loginPath = "/login", loginCredentials = null,
  loginTokenWhere = "json", loginTokenKey = "access_token",
  loginInjectWhere = "header", loginInjectName = "Authorization",
  loginInjectTemplate = "Bearer {token}", loginBodyFormat = "json",
} = {}) {
  const svc = String(service || url || "").trim();
  const host = String(url || svc || "").replace(/^https?:\/\//, "").split("/")[0] || "target";
  const isLocal = localTarget != null ? !!localTarget : _looksLocal(url || svc);

  const body = {
    service: svc, url, credential: cred, puppet_id: puppetId,
    forma, auth_in: authIn, auth_param: authParam,
    auth_header: authHeader, auth_template: authTemplate,
    validate_path: validatePath, synth_alias: synthAlias, max_rounds: maxRounds,
  };
  if (isLocal) { body.local_target = true; onState(`servidor local detectado — sólo tú lo alcanzas`, "local"); }
  if (apiShapeHint) body.api_shape_hint = apiShapeHint;
  if (forma === "login") {
    // ruteo directo al LoginAPISession del Motor B (los nombres de campo son del login real).
    body.login_path = loginPath;
    body.login_credentials = loginCredentials || {};
    body.login_token_where = loginTokenWhere;
    body.login_token_key = loginTokenKey;
    body.login_inject_where = loginInjectWhere;
    body.login_inject_name = loginInjectName;
    body.login_inject_template = loginInjectTemplate;
    body.login_body_format = loginBodyFormat;
  }
  if (forma === "browser-oauth" || forma === "browser") {
    // [3-browser-oauth] la sesión humana (login+2FA) ya está capturada y cifrada bajo sessionKey;
    // el Motor B la REUSA. Sin sessionKey el backend corta honesto (no hay sesión que reusar).
    body.session_key = sessionKey;
    if (loginUrl) body.login_url = loginUrl;
  }
  if (seedProbes && seedProbes.length) body.seed_probes = seedProbes;
  if (seedCandidates != null) body.seed_candidates = seedCandidates;
  if (seedSpec != null) body.seed_spec = seedSpec;

  onState(`busca-antes-de-forjar · consultando el registry para <b>${_esc(svc)}</b>…`);

  let resp;
  try {
    resp = await fetch("/v1/inspect/dispatch", {
      method: "POST",
      headers: _sessAuth({ "Content-Type": "application/json", "Accept": "text/event-stream" }),
      body: JSON.stringify(body),
    });
  } catch (e) {
    if (manual && manual.cleanup) manual.cleanup();   // 2d
    const errEv = { type: "error", stage: "conexion", detail: e.message };
    if (onEvent) { try { onEvent(errEv); } catch {} }   // evidencia: el fallo de red entra al carril 2e
    onState(`<span style="color:var(--gate)">no pude conectar al despachador: ${e.message}</span>`);
    return { ok: false, path: null, origin: null, events: [errEv], error: e.message };
  }
  if (!resp.ok) {
    if (manual && manual.cleanup) manual.cleanup();   // 2d
    let det = null;
    try { det = (await resp.json()).detail; } catch {}
    const msg = _httpErrMsg(det, resp.status);
    // el rechazo del borde (422/400/429) es EVIDENCIA: entra al carril de eventos con el
    // payload real del server — antes moría en el HUD y el drawer 2e nunca lo veía.
    const errEv = { type: "error", stage: "despacho", status: resp.status, detail: det ?? msg };
    if (onEvent) { try { onEvent(errEv); } catch {} }
    onState(`<span style="color:var(--gate)">no pude despachar (HTTP ${resp.status}): ${_esc(msg)}</span>`);
    return { ok: false, path: null, origin: null, events: [errEv], error: String(msg) };
  }

  let begun = false, equipado = null, miss = false, rejectedImpostor = false, closed = null, registryDown = false;
  let choreo = null;   // snapshot de la coreografía en mcp.forjado (para verificación sin race)
  const ensureBegin = () => {
    if (begun) return;
    begun = true;
    api.forge.begin({ url: url || svc, host });   // arranca el draw-pass de la coreografía
  };

  const handle = (ev) => {
    if (onEvent) { try { onEvent(ev); } catch {} }
    switch (ev.type) {
      // ── frames de ORDEN del despachador (1c) ──
      case "dispatch.iniciado":
        onState(`despachando <b>${_esc(ev.service || svc)}</b>…`);
        break;
      case "resolver.buscando":
        onState(`buscando un MCP verificado en el registry…`);
        break;
      case "resolver.encontrado":
        // [T-3] from_cache = el registro estaba CAÍDO y traje una resolución previa validada.
        // Honesto: le decimos que es lo guardado y que el catálogo no responde ahora (no lo
        // vendemos como un hallazgo fresco del registry).
        onState(ev.from_cache
          ? `✓ traje <b>${_esc(ev.server_name || "MCP")}</b> de lo que ya tenías guardado <span style="color:var(--muted)">(${_esc(ev.vendor_kind || "verificado")}) — el catálogo público no responde ahora; revalidé la pieza en vivo</span>`
          : `✓ <b>${_esc(ev.server_name || "MCP")}</b> ya existe en el registry <span style="color:var(--muted)">(${_esc(ev.vendor_kind || "verificado")})</span> — lo traigo sin forjar`);
        break;
      case "resolver.miss":
        miss = true;
        rejectedImpostor = !!ev.rejected_impostor;
        onState(ev.rejected_impostor
          ? `<span style="color:var(--gate)">impostor rechazado por el resolver: ${_esc((ev.reason || "").slice(0, 80))}</span>`
          : `sin MCP verificado en el registry — forjo desde cero con el <b>Motor B</b>`);
        break;
      case "resolver.registry_down":
        // [T-3] el registro NO respondió: esto NO es "no existe". No forjamos a ciegas ni
        // mostramos lista vacía. Mensaje honesto + reintentar (jamás el false-empty que le
        // mentiría al usuario diciéndole que su conector no existe).
        registryDown = true;
        onState(`<span style="color:var(--gate)">el catálogo público no responde ahora mismo — no pude confirmar si existe un MCP para <b>${_esc(svc)}</b>. Reintenta ↻</span> <span style="color:var(--muted)">(no forjo nada a ciegas)</span>`);
        break;
      case "dispatch.forjando":
        ensureBegin();
        onState(`forjando <b>${_esc(ev.url || url || svc)}</b> con el <b>Motor B</b>…`);
        break;
      case "mcp.equipado":
        equipado = ev;
        break;
      // ── coreografía del Motor B (1a) — el MISMO stream ──
      case "forge.iniciado":
      case "sesion.ok":
      case "observando":
      case "tool.descartada":
        ensureBegin();
        applyChoreography(api, ev, { host, onState });
        break;
      case "sintetizando":
        ensureBegin();
        applyChoreography(api, ev, { host, onState });   // HUD-only (no toca api.forge.*)
        break;
      case "forge.latido":
        // transporte: narra sin arrancar el draw-pass (un latido no es una transición del motor)
        applyChoreography(api, ev, { host, onState });
        break;
      case "tool.propuesta":
        ensureBegin();
        applyChoreography(api, ev, { host, onState });   // 1-A intacta: el ghost nace igual
        break;
      case "tool.validando":
      case "tool.validada":
        ensureBegin();
        // [identidad visual 6/6] acá se suprimía la validación de una propuesta descartada a mano
        // (el viejo "punto 1", detrás del Modo técnico). Se fue con el modo: pedía decidir sobre
        // fantasmas que todavía no se sabía si iban a validar. La misma decisión —qué queda
        // adentro— se toma después, sobre las tools reales, en `reviewBeforeSeal`.
        applyChoreography(api, ev, { host, onState });
        break;
      case "mcp.forjado":
        ensureBegin();
        applyChoreography(api, ev, { host, onState });
        try { choreo = api.forge.stats(); } catch {}   // captura ANTES de cualquier limpieza
        break;
      case "cerrado":
        closed = ev;
        if (begun) api.forge.end();
        break;
      case "error":
        if (begun) applyChoreography(api, ev, { host, onState });
        break;
    }
  };

  const out = await _consumeStream(resp, handle, () => { if (begun) api.forge.end(); });
  if (out.error) {
    if (manual && manual.cleanup) manual.cleanup();   // 2d · stream cortado → cierra el panel de revisión
    onState(`<span style="color:var(--gate)">se cortó el stream del despachador: ${_esc(out.error)}</span>`);
    return { ok: false, path: null, origin: null, events: out.list, error: out.error };
  }
  const events = out.list;

  // ── [T-3] REGISTRO CAÍDO: honesto y sin forjar. NUNCA "no existe" ni lista vacía fingida.
  // Cortamos ACÁ (antes de cualquier lógica de miss/forja) con retry:true — el catálogo no
  // respondió, así que no afirmamos nada sobre la existencia del conector. ─────────────────
  if (registryDown || (closed && closed.path === "registry_down")) {
    if (manual && manual.cleanup) manual.cleanup();
    return { ok: false, path: "registry_down", origin: null, events, retry: true,
             reason: "el catálogo público no respondió — reintenta; no forjé nada a ciegas" };
  }

  // ── DESENLACE: FOUND (registry) · forjado (Motor B) · honesto ──────────────────────
  if (equipado) {
    if (manual && manual.cleanup) manual.cleanup();   // 2d · el camino registry no forja nada que revisar
    const r = equipResolvedMcp({ api, equipado, label, onState });
    // [FIX-P11 · §4] `duplicada` viaja hacia arriba: la superficie tiene que poder decir
    // «ya está en El Cuarto» en vez de leer un ok:false como si algo hubiera fallado.
    return { ok: r.ok, path: "registry", origin: r.ok ? "registry" : null, events,
             piece: r.piece, server: r.server, belt_ref: r.belt_ref, tools: r.tools,
             duplicada: !!r.duplicada, pieceId: r.pieceId || null,
             reason: r.reason, choreo };
  }
  if (events.some((e) => e.type === "mcp.forjado")) {
    const fb = { url, cred, auth_in: authIn, puppet_id: puppetId, forma };   // 2f · forma → equip auth-aware
    // 2d · REVISAR ANTES DE EQUIPAR. Sin `manual` (consumidores headless: harness, deep-link) esto
    // NO corre → equip automático byte-idéntico. Con `manual`, el panel muestra las tools REALES del
    // emit con TODAS marcadas: continuar sin tocar nada equipa exactamente lo forjado. Lo destildado
    // cura el evento mcp.forjado (su `tools[]`) → 1-B (equipForgedMcp, INTACTA) materializa la pieza
    // con sólo lo que quedó marcado.
    let equipEvents = events;
    if (manual && manual.reviewBeforeSeal) {
      const forjadoEv = events.find((e) => e.type === "mcp.forjado");
      const decision = await manual.reviewBeforeSeal(forjadoEv);
      if (manual.cleanup) manual.cleanup();
      if (!decision) {   // cancelaste antes de equipar → honesto, no se equipa nada
        return { ok: false, path: "forged", origin: null, events, reason: "cancelaste antes de equipar", choreo };
      }
      const keep = decision.keep;
      const curated = { ...forjadoEv, tools: (forjadoEv.tools || []).filter((t) => keep.has(t)) };
      equipEvents = events.map((e) => (e === forjadoEv ? curated : e));
    }
    const r = equipForgedMcp({ api, events: equipEvents, label, body: fb, onState });
    return { ok: r.ok, path: "forged", origin: r.ok ? "forged" : null, events,
             piece: r.piece, server: r.server, belt_ref: r.belt_ref, puppet_id: r.puppet_id,
             duplicada: !!r.duplicada, pieceId: r.pieceId || null,   // [FIX-P11 §4]
             tools: r.tools, gated: r.gated, reason: r.reason, stats: r.stats, choreo };
  }
  if (manual && manual.cleanup) manual.cleanup();   // 2d · forja que no emitió MCP → cierra el panel
  // ni encontrado ni forjado → honesto (impostor rechazado / miss sin url / degradado)
  const degradedEv = events.find((e) => e.type === "error" && e.degraded);
  return {
    ok: false, path: miss ? "miss" : (closed && closed.path) || null,
    origin: null, rejected_impostor: rejectedImpostor, events, choreo,
    reason: rejectedImpostor ? "impostor rechazado por el resolver"
      : degradedEv ? `el modelo (${degradedEv.model || "alias:brain"}) no respondió — forja degradada, no se equipó nada`
      : (closed && closed.detail) || "el despachador no equipó ni forjó nada",
  };
}

/** Lee el ReadableStream SSE del POST frame-a-frame; llama onEvent(ev) por cada uno. Devuelve
 *  {list, error?}. `onAbort` corre si el stream se corta a mitad. UN solo lector — sin duplicar. */
async function _consumeStream(resp, onEvent, onAbort = () => {}) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  const list = [];
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
        const ev = parseFrame(frame);
        if (ev) { list.push(ev); onEvent(ev); }
      }
    }
    if (buf.trim()) { const ev = parseFrame(buf); if (ev) { list.push(ev); onEvent(ev); } }
  } catch (e) {
    onAbort();
    return { list, error: e.message };
  }
  return { list };
}
