/* cuarto.evidence.js — EL TERCER CARRIL · la EVIDENCIA TÉCNICA cruda por evento (modo dev).
 *
 * Los otros dos carriles del contrato ya viven en el Cuarto:
 *   1-A coreografía (cuarto.inspect.js)  — la danza para el NO-técnico (fantasmas → sólidas).
 *   1-B materialización (cuarto.forge.js) — la PIEZA real que queda equipada.
 * Falta el carril del DEV: la prueba dura de que "esta tool no me la inventaron — la PROBARON
 * contra el endpoint y devolvió ESTO". Eso hace VISIBLE el verify-from-environment.
 *
 * Este módulo es un OVERLAY DE LECTURA. Escucha el MISMO stream (por el `onEvent` que ya expone
 * el consumidor) y, bajo demanda, destapa por cada evento su payload de evidencia REAL — el que
 * Ola 0 ya emite (ver forge_router._translate):
 *   observando      → url observada · ronda · modo · probed · nuevas confirmadas
 *   tool.propuesta  → de qué observación salió · params inferidos · método/endpoint · modelo
 *   tool.validando  → el REQUEST exacto disparado contra el software vivo
 *   tool.validada   → la RESPUESTA real (status · payload) — la prueba dura
 *   tool.descartada → el error EXACTO (el 404/422 real, no "falló")
 *   mcp.forjado     → el MCP crudo (server · tool definitions · belt_ref · puppet_id)
 *
 * INVARIANTES (esto es auditable):
 *   • DEFAULT OCULTO. El no-técnico ve la coreografía limpia; la evidencia se expone al tocar dev.
 *   • CERO-TEATRO EXTREMO. Cada fila es un campo REAL del evento. Si un campo no vino → "(ausente)"
 *     / "(vacío)"; JAMÁS se fabrica un request/response de ejemplo. Cada tarjeta lleva además el
 *     PAYLOAD CRUDO (JSON.stringify del evento literal) — la verdad sin retoque.
 *   • NO toca el modelo, NO toca la coreografía base, NO altera el flujo. Sólo lee y pinta DOM aparte.
 *
 * Exporta: mountEvidence({doc, host}) → { onEvent, reset, setOpen, isOpen, toggle, count, events, el }.
 */

// Los campos de evidencia que destapamos por tipo de evento, EN ORDEN. Es un mapa de RÓTULOS:
// los valores se leen SIEMPRE del evento real (nunca se inventan). Un tipo sin entrada acá cae al
// fallback (todas las claves del evento menos `type`), así nunca se esconde evidencia real.
const EVIDENCE_FIELDS = {
  "forge.iniciado":     ["cerebro", "url", "forma", "slug", "puppet_id"],
  "dispatch.iniciado":  ["service"],
  "resolver.buscando":  [],
  "resolver.encontrado":["server_name", "vendor_kind"],
  "resolver.miss":      ["rejected_impostor", "reason"],
  "dispatch.forjando":  ["url"],
  "sesion.ok":          ["auth_form", "validated_by", "validate_status", "key_fingerprint", "cred_ref"],
  "observando":         ["url", "round", "mode", "passive", "probed", "new_confirmed"],
  "sintetizando":       ["round", "cerebro"],
  "forge.latido":       ["elapsed_s", "stage", "round"],
  "tool.propuesta":     ["nombre", "method", "endpoint", "kind", "params", "description", "round", "model"],
  "tool.validando":     ["nombre", "round", "request"],
  "tool.validada":      ["nombre", "status", "verified_by", "payload"],
  "tool.descartada":    ["nombre", "motivo", "symptom", "clase", "move"],
  "mcp.forjado":        ["server", "belt_ref", "puppet_id", "tools"],
  "mcp.equipado":       ["server", "belt_ref", "puppet_id", "tools", "tools_detail"],
  "cerrado":            ["convergence", "verified", "dropped", "degraded", "budget"],
  "error":              ["stage", "status", "detail", "degraded", "model"],
};

// Qué PRUEBA cada evento, en una línea. Honesto: describe la evidencia, no la adorna.
const EVENT_GLOSS = {
  "forge.iniciado":     "el Motor B arrancó · con qué modelo y contra qué URL",
  "dispatch.iniciado":  "el despachador arrancó (busca-antes-de-forjar)",
  "resolver.buscando":  "consultando el registry por un MCP ya verificado",
  "resolver.encontrado":"el MCP ya existía en el registry — se trae sin forjar",
  "resolver.miss":      "no había MCP verificado — se forja desde cero",
  "dispatch.forjando":  "se dispara el Motor B sobre la URL cruda",
  "sesion.ok":          "la sesión con el target se validó VIVA (no se asume)",
  "observando":         "qué endpoint detectó y qué respondió el software",
  "sintetizando":       "el modelo está sintetizando candidatas (la espera es real)",
  "forge.latido":       "keepalive del stream · cuánto lleva y en qué etapa va",
  "tool.propuesta":     "de qué observación salió · params inferidos y de dónde",
  "tool.validando":     "el REQUEST exacto disparado contra el software vivo",
  "tool.validada":      "la RESPUESTA real (status · payload) — la prueba dura",
  "tool.descartada":    "el error EXACTO (el 404/422 real, no «falló»)",
  "mcp.forjado":        "el MCP crudo · server · tool definitions · belt_ref",
  "mcp.equipado":       "el MCP traído del registry · server · belt_ref",
  "cerrado":            "el cierre de la ejecución · convergencia · verificadas vs descartadas",
  "error":              "el corte honesto (sesión caída / modelo degradado)",
};

const _esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

/** Render de UN valor de evidencia, CERO-TEATRO. Distingue ausente / vacío / null / escalar / json.
 *  Devuelve HTML; nunca fabrica un placeholder de ejemplo. */
function _renderValue(ev, field) {
  if (!Object.prototype.hasOwnProperty.call(ev, field))
    return `<span class="ev-absent" title="el evento no trajo este campo">(ausente)</span>`;
  const v = ev[field];
  if (v === null) return `<span class="ev-null">null</span>`;
  if (v === "") return `<span class="ev-absent">(vacío)</span>`;
  if (Array.isArray(v)) {
    if (!v.length) return `<span class="ev-absent">(vacío)</span>`;
    return `<pre class="ev-json">${_esc(JSON.stringify(v, null, 2))}</pre>`;
  }
  if (typeof v === "object") {
    if (!Object.keys(v).length) return `<span class="ev-absent">(vacío)</span>`;
    return `<pre class="ev-json">${_esc(JSON.stringify(v, null, 2))}</pre>`;
  }
  if (typeof v === "boolean") return `<span class="ev-bool">${v}</span>`;
  return `<span class="ev-scalar">${_esc(v)}</span>`;
}

/** Una tarjeta de evidencia para un evento. Lleva: rótulos por campo REAL + payload crudo literal. */
function _buildCard(ev, idx, doc) {
  const type = ev && ev.type ? String(ev.type) : "(sin tipo)";
  const fields = EVIDENCE_FIELDS[type] || Object.keys(ev || {}).filter((k) => k !== "type");
  const gloss = EVENT_GLOSS[type] || "";
  const ident = (ev && (ev.nombre || ev.server || ev.server_name)) || "";

  let rows = "";
  for (const f of fields) {
    rows += `<div class="ev-row"><span class="ev-k">${_esc(f)}</span>` +
            `<span class="ev-v">${_renderValue(ev, f)}</span></div>`;
  }
  if (!fields.length) rows = `<div class="ev-row ev-noflds">sin campos de detalle — sólo marca de fase</div>`;

  const raw = _esc(JSON.stringify(ev, null, 2));   // ← la verdad literal, sin retoque (auditable)
  const safeType = type.replace(/[^a-z0-9]+/gi, "-");

  const card = doc.createElement("div");
  card.className = "ev-card";
  card.dataset.type = type;
  card.dataset.idx = String(idx);
  card.innerHTML =
    `<div class="ev-hd">` +
      `<span class="ev-seq">#${idx + 1}</span>` +
      `<span class="ev-type type-${safeType}">${_esc(type)}</span>` +
      (ident ? `<span class="ev-id">${_esc(ident)}</span>` : "") +
    `</div>` +
    (gloss ? `<div class="ev-gloss">${_esc(gloss)}</div>` : "") +
    `<div class="ev-fields">${rows}</div>` +
    `<details class="ev-rawwrap"><summary>payload crudo · auditable</summary>` +
      `<pre class="ev-raw">${raw}</pre></details>`;
  return card;
}

const _STYLE_ID = "ev-evidence-style";
function _injectStyle(doc) {
  if (doc.getElementById(_STYLE_ID)) return;
  const st = doc.createElement("style");
  st.id = _STYLE_ID;
  st.textContent = `
    #evToggle .ev-glyph { font-family: var(--font-mono); opacity:.8; margin-right:1px; }
    #evToggle .ev-count { margin-left:6px; padding:1px 6px; border-radius:var(--r-sm); font-size:10.5px; font-weight:500;
      background:rgba(122,162,255,.22); color:#cfe0ff; }
    #evToggle.on .ev-count { background:rgba(7,18,43,.25); color:#07122b; }
    #evDrawer { right:18px; top:64px; bottom:78px; width:430px; max-width:calc(100vw - 36px);
      display:none; flex-direction:column; padding:0; z-index:40; pointer-events:auto; overflow:hidden; }
    #evDrawer .ev-top { display:flex; align-items:center; gap:8px; padding:12px 14px; border-bottom:1px solid var(--line); }
    #evDrawer .ev-ttl { font-weight:400; letter-spacing:.2px; font-size:13px; }
    #evDrawer .ev-ttl .ev-sub { font-weight:300; color:var(--muted); font-size:11px; margin-left:6px; }
    #evDrawer .ev-x { margin-left:auto; width:28px; height:28px; border:0; border-radius:var(--r-sm); cursor:pointer;
      color:var(--ink); background:rgba(255,255,255,.06); font-size:14px; }
    #evDrawer .ev-x:hover { background:rgba(255,255,255,.12); }
    #evDrawer .ev-lede { padding:10px 14px; color:var(--muted); font-size:11.5px; line-height:1.5; border-bottom:1px solid var(--line); }
    #evDrawer .ev-lede b { color:var(--ink); }
    #evDrawer .ev-body { flex:1; overflow:auto; padding:10px 12px; display:flex; flex-direction:column; gap:9px; }
    #evDrawer .ev-empty { color:var(--muted); font-size:12px; padding:18px 6px; text-align:center; }
    .ev-card { border:0; border-radius:var(--r-md); background:var(--paper2); padding:9px 11px; }
    .ev-hd { display:flex; align-items:center; gap:8px; }
    .ev-hd .ev-seq { font-family:var(--font-mono); font-size:10px; color:var(--muted); }
    .ev-hd .ev-type { font-family:var(--font-mono); font-size:11.5px; font-weight:400; color:var(--ink);
      padding:1px 7px; border-radius:var(--r-xs); background:rgba(255,255,255,.05); }
    .ev-hd .ev-type.type-tool-validada { color:#0d1b10; background:var(--fuentes); }
    .ev-hd .ev-type.type-tool-descartada { color:#1d0f10; background:#ff8d8d; }
    .ev-hd .ev-type.type-tool-validando { color:#07122b; background:#7aa2ff; }
    .ev-hd .ev-type.type-tool-propuesta { color:#160c20; background:var(--mesa); }
    .ev-hd .ev-type.type-mcp-forjado, .ev-hd .ev-type.type-mcp-equipado { color:#0d1b10; background:var(--eco); }
    .ev-hd .ev-type.type-observando { color:#1c1405; background:var(--gate); }
    .ev-hd .ev-type.type-error { color:#1d0f10; background:#ff8d8d; }
    .ev-hd .ev-id { font-family:var(--font-mono); font-size:11px; color:var(--muted);
      margin-left:auto; max-width:55%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .ev-gloss { color:var(--muted); font-size:11px; margin:5px 0 7px; line-height:1.4; }
    .ev-fields { display:flex; flex-direction:column; gap:5px; }
    .ev-row { display:grid; grid-template-columns:118px 1fr; gap:8px; align-items:start; font-size:11.5px; }
    .ev-row .ev-k { font-family:var(--font-mono); color:var(--muted); }
    .ev-row .ev-v { min-width:0; word-break:break-word; color:var(--ink); }
    .ev-row.ev-noflds { display:block; color:var(--muted); font-style:italic; }
    .ev-v .ev-absent { color:var(--muted); font-style:italic; opacity:.75; }
    .ev-v .ev-null { color:#c98aff; font-family:var(--font-mono); }
    .ev-v .ev-bool { color:var(--conexion); font-family:var(--font-mono); }
    .ev-v .ev-scalar { font-family:var(--font-mono); }
    .ev-json, .ev-raw { font-family:var(--font-mono); font-size:10.5px; line-height:1.45; margin:2px 0 0;
      padding:7px 9px; border-radius:var(--r-sm); background:var(--panel2); color:#cdd6e8; white-space:pre-wrap;
      word-break:break-word; max-height:230px; overflow:auto; box-shadow:var(--sh-line); }
    .ev-rawwrap { margin-top:8px; }
    .ev-rawwrap summary { cursor:pointer; font-size:10.5px; color:var(--muted); font-family:var(--font-mono);
      list-style:none; user-select:none; }
    .ev-rawwrap summary:hover { color:var(--ink); }
    .ev-rawwrap[open] summary { color:var(--ink); }
  `;
  (doc.head || doc.documentElement).appendChild(st);
}

/**
 * Monta el overlay de evidencia. Aditivo: agrega un toggle (en #topright si existe) y un cajón
 * (en #stage), AMBOS ocultos hasta que el dev toca el toggle. Devuelve la API de lectura.
 *
 * @param {object}   [opts]
 * @param {Document} [opts.doc=document]
 * @param {Element}  [opts.host]  - contenedor del cajón (default #stage o body)
 * @returns {{onEvent, reset, setOpen, isOpen, toggle, count, events, el}}
 */
export function mountEvidence({ doc = document, host = null } = {}) {
  _injectStyle(doc);
  const stage = host || doc.getElementById("stage") || doc.body;

  // ── el TOGGLE (modo dev) — default OFF ──
  const toggle = doc.createElement("button");
  toggle.id = "evToggle";
  toggle.type = "button";
  toggle.className = "pill";
  // [identidad visual §e] aria-label, NO title: en la barra el botón es sólo el glifo "EV"
  // (necesita nombre) pero vive DOCKEADO en el ⋯, donde ya dice "evidencia" y el globo del
  // sistema le caía encima a la fila de abajo. El nombre accesible se conserva en los dos.
  toggle.setAttribute("aria-label", "Evidencia");
  toggle.setAttribute("data-i18n-aria", "workshop.action.evidence");
  toggle.innerHTML = `<span class="ev-glyph">&lt;/&gt;</span> <span data-i18n="workshop.action.evidence">Evidencia</span>`;
  doc.defaultView?.AlephI18n?.apply(toggle);
  const topright = doc.getElementById("topright");
  if (topright) {
    topright.appendChild(toggle);
  } else {
    toggle.classList.add("float");
    toggle.style.cssText = "right:18px; bottom:84px; z-index:40;";
    stage.appendChild(toggle);
  }

  // ── el CAJÓN (drawer) — default OCULTO ──
  const drawer = doc.createElement("aside");
  drawer.id = "evDrawer";
  drawer.className = "float glass";
  drawer.innerHTML =
    `<div class="ev-top"><div class="ev-ttl">&lt;/&gt; Evidencia técnica` +
      `</div>` +
      `<button class="ev-x" type="button" title="cerrar">✕</button></div>` +
    `<div class="ev-body" id="evBody"></div>`;
  stage.appendChild(drawer);

  const body = drawer.querySelector("#evBody");
  const EMPTY = `<div class="ev-empty">Inspecciona un software (⌕ Inspeccionar) ` +
    `y la evidencia técnica de cada paso aparece aquí.</div>`;
  body.innerHTML = EMPTY;

  const events = [];       // los eventos REALES, en orden de stream (referencias literales)
  let open = false;

  const updateBadge = () => {
    let b = toggle.querySelector(".ev-count");
    if (!events.length) { if (b) b.remove(); return; }
    if (!b) { b = doc.createElement("span"); b.className = "ev-count"; toggle.appendChild(b); }
    b.textContent = String(events.length);
  };

  const renderAll = () => {
    body.innerHTML = "";
    if (!events.length) { body.innerHTML = EMPTY; return; }
    events.forEach((ev, i) => body.appendChild(_buildCard(ev, i, doc)));
    body.scrollTop = body.scrollHeight;
  };

  const setOpen = (v) => {
    open = !!v;
    drawer.style.display = open ? "flex" : "none";
    toggle.classList.toggle("on", open);
    toggle.setAttribute("aria-pressed", open ? "true" : "false");
    if (open) renderAll();   // refresca por si llegaron eventos con el cajón cerrado
  };

  // El ÚNICO punto de entrada de datos: el evento REAL del stream. Sólo guarda y (si está abierto)
  // pinta. NO transforma el evento, NO toca el modelo ni la coreografía.
  const onEvent = (ev) => {
    if (!ev || typeof ev !== "object") return;
    const idx = events.length;
    events.push(ev);
    updateBadge();
    if (open) {
      const e = body.querySelector(".ev-empty"); if (e) e.remove();
      body.appendChild(_buildCard(ev, idx, doc));
      body.scrollTop = body.scrollHeight;
    }
  };

  const reset = () => { events.length = 0; updateBadge(); if (open) renderAll(); };

  toggle.addEventListener("click", () => setOpen(!open));
  drawer.querySelector(".ev-x").addEventListener("click", () => setOpen(false));

  return {
    onEvent, reset, setOpen,
    isOpen: () => open,
    toggle: () => setOpen(!open),
    count: () => events.length,
    events,                      // expuesto para verificación (referencias a los eventos reales)
    el: { toggle, drawer, body },
  };
}
