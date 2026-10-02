/* cuarto.forge.js — el seam emit→EQUIPAR · MATERIALIZA la PIEZA REAL desde el stream del Motor B.
 *
 * `POST /v1/inspect/forge` (LA COSTURA, Ola 0) y `POST /v1/inspect/dispatch` (§0.5, Ola 1c)
 * corren el Motor B real y emiten, por SSE, el contrato capa-por-capa:
 *   forge.iniciado → sesion.ok → observando → tool.propuesta(×N) → tool.validando
 *     → tool.validada / tool.descartada → mcp.forjado{server,tools[],belt_ref,puppet_id} → cerrado
 *
 * Este módulo es DUEÑO desde `mcp.forjado` en adelante (la frontera de la integración Ola 1):
 * NO lee el stream ni toca la coreografía de validación (eso es 1-A, vive en cuarto.inspect.js
 * y en el motor). Recibe los EVENTOS YA ACUMULADOS y, en `mcp.forjado`, vuelve el MCP forjado una
 * PIEZA REAL del Cuarto por la VÍA NORMAL (api.placeTile, un átomo Tool que arrastra su belt) —
 * núcleo-céntrica como cualquier otra, sin mutar el modelo de relaciones.
 *
 * CERO-TEATRO (la regla del 401 honesto de F5): la pieza nace SOLO si el emit trae un belt_ref
 * USABLE — server≠null + belt_ref + ≥1 tool forjada. Si el run cierra sin forjar (verified==0),
 * degrada (el modelo no respondió) o el target rechaza la sesión, NO se finge una pieza ni se
 * fabrica un belt falso: se reporta honesto y el cuarto queda igual.
 *
 * Exporta:
 *   • equipForgedMcp({api, events, label, body})   — la frontera 1-B (camino MISS→forja del dispatch)
 *   • equipResolvedMcp({api, equipado, label})     — la pieza traída del registry (camino FOUND, 1c)
 *   • forgeAndEquip({api, body, label})            — consumidor standalone de 1-B (lee /forge solo);
 *                                                    backward-compat (forge_equip_e2e.mjs). Reusa la
 *                                                    MISMA materialización (equipForgedMcp), sin 2do camino.
 */

const ZONE_OF_KIND = { read: "fuentes", write: "entrega" };

let _seq = 0;
const _uid = (s) => `forge-${s}-${Date.now().toString(36)}-${++_seq}`;

/** server_name del motor = "forged-<slug>"; lo volvemos legible si el usuario no dio nombre. */
function _prettyLabel(server, fallback) {
  if (fallback && fallback.trim()) return fallback.trim();
  const s = String(server || "").replace(/^forged-/, "").replace(/^forge-/, "");
  const words = s.replace(/[-_]+/g, " ").trim();
  return words ? words.replace(/\b\w/g, (c) => c.toUpperCase()) : (server || "MCP forjado");
}

/** Parser SSE incremental sobre el ReadableStream del POST. Llama onFrame({type,data}) por frame. */
async function _readSSE(resp, onFrame, signal) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder("utf-8");
  let buf = "";
  let evType = null;
  const flushLine = (line) => {
    if (line.startsWith("event:")) { evType = line.slice(6).trim(); return; }
    if (line.startsWith("data:")) {
      const blob = line.slice(5).trim();
      let data; try { data = JSON.parse(blob); } catch { data = { _raw: blob }; }
      onFrame({ type: evType || data.type, data });
      return;
    }
    if (line === "") { evType = null; }   // fin de frame
  };
  for (;;) {
    if (signal && signal.aborted) { try { await reader.cancel(); } catch {} break; }
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).replace(/\r$/, "");
      buf = buf.slice(nl + 1);
      flushLine(line);
    }
  }
  // cola sin newline final
  if (buf) buf.split("\n").forEach((l) => flushLine(l.replace(/\r$/, "")));
}

/** Acumula el estado del stream desde los EVENTOS del contrato (la pieza se TIPA de lo observado). */
function _accumulate(events) {
  const proposed = new Map();    // nombre → { kind, endpoint, method }
  const validated = new Map();   // nombre → { status, verified_by }
  let dropped = 0, degraded = false, sessionErr = null, closed = null, forjado = null;
  for (const ev of events || []) {
    switch (ev && ev.type) {
      case "tool.propuesta":
        if (ev.nombre) proposed.set(ev.nombre, { kind: ev.kind || "read", endpoint: ev.endpoint, method: ev.method });
        break;
      case "tool.validada":
        if (ev.nombre) validated.set(ev.nombre, { status: ev.status, verified_by: ev.verified_by });
        break;
      case "tool.descartada":
        dropped++;
        break;
      case "error":
        if (ev.degraded) degraded = true;
        if (ev.stage === "sesion") sessionErr = ev.detail || "la sesión con el target falló";
        else if (!degraded) sessionErr = sessionErr || ev.detail || null;
        break;
      case "mcp.forjado":
        forjado = ev;            // ← el EMIT que materializa la pieza
        break;
      case "cerrado":
        closed = ev;
        break;
      default:
        break;
    }
  }
  return { proposed, validated, dropped, degraded, sessionErr, closed, forjado };
}

/**
 * FRONTERA 1-B · materializa la pieza REAL desde los eventos ya acumulados del Motor B.
 * NO lee el stream (eso es 1-A); recibe `events` (los frames del contrato ya parseados).
 *
 * @param {object}   opts
 * @param {object}   opts.api      - el api de mountCuarto (placeTile/freeCell/pulse/…)
 * @param {Array}    opts.events   - eventos del contrato (el MISMO stream que dibujó la coreografía)
 * @param {string}   [opts.label]  - nombre amigable para la pieza
 * @param {object}   [opts.body]   - el request {url,auth_in,puppet_id} (para tipar el sub/auth)
 * @param {function} [opts.onState]- callback(texto, kind) para el HUD
 * @returns {{ok, piece?, server?, belt_ref?, puppet_id?, tools?, gated?, reason?, stats, forjado?}}
 */
export function equipForgedMcp({ api, events, label = null, body = {}, onState = () => {} }) {
  const { proposed, validated, dropped, degraded, sessionErr, closed, forjado } = _accumulate(events);
  const stats = { proposed: proposed.size, validated: validated.size,
                  validatedNames: [...validated.keys()], dropped };

  // ── CERO-TEATRO: la pieza nace SOLO con un emit USABLE ──────────────────────────────
  if (!forjado) {
    let reason;
    if (sessionErr) reason = sessionErr;
    else if (degraded) reason = "el modelo (Groq) no respondió — corte honesto, sin forjar";
    else if (closed && Number(closed.verified || 0) === 0) reason = "no se verificó ninguna tool contra el target — nada que forjar";
    else reason = "el motor cerró sin forjar un MCP";
    return { ok: false, reason, stats };
  }
  const server = forjado.server;
  const belt_ref = forjado.belt_ref;
  const tools = Array.isArray(forjado.tools) ? forjado.tools.slice() : [];
  if (!server || !belt_ref || !tools.length) {
    // el emit llegó pero hueco (no debería: el contrato lo prohíbe). No fingimos usable.
    return { ok: false, reason: "el motor emitió un MCP incompleto (server/belt_ref/tools) — no lo equipo hueco",
             stats, forjado };
  }

  // tools = las VALIDADAS que sobrevivieron (el motor forja sólo desde verified). Si el motor
  // expuso validadas, las usamos de autoridad cruzada; si no (sin perillas de seed), usamos las
  // del emit tal cual (que YA son las verified de la Capa 5).
  const toolList = tools.filter((t) => !validated.size || validated.has(t));
  const finalTools = toolList.length ? toolList : tools;
  const hasWrite = finalTools.some((t) => (proposed.get(t) || {}).kind === "write");
  const zone = hasWrite ? ZONE_OF_KIND.write : ZONE_OF_KIND.read;

  // [FIX-P11 · §4] DEDUPE en el camino del Motor B. Antes de pedir celda: si este servidor
  // ya está en el piso, no se forja una gemela. Se chequea con la IDENTIDAD (server+belt),
  // no con el id — que acá es `_uid(server)`, distinto en cada pasada, y por eso la guarda
  // de P5 en placeTile nunca se activaba desde este camino.
  // La sonda tiene que tener la MISMA FORMA que la pieza que se va a colocar — server,
  // belt Y CAPACIDAD (`key`/`tools`). Con un objeto pelado, la capacidad se lee de un
  // label vacío y NUNCA colisiona con la pieza real (que sí lleva key): el dedupe queda
  // mudo, la gemela llega al backstop de placeTile y el mensaje sale equivocado — «no
  // pude colocar la pieza», que suena a fallo nuestro, en vez de «ya la tenés».
  const yaEsta = api.yaColocadaPor && api.yaColocadaPor(
    { server, belt_ref, atom: "tool", key: `forged:${server}`, tools: finalTools });
  if (yaEsta) {
    const nombre = _prettyLabel(server, label);
    try { api.pulse && api.pulse(yaEsta); } catch (e) {}
    onState(`<b>${nombre}</b> ya está en El Cuarto`, "info");
    return { ok: false, duplicada: true, pieceId: yaEsta, server, belt_ref, nombre,
             reason: `${nombre} ya está en El Cuarto`, stats, forjado };
  }

  const cell = api.freeCell(zone);
  if (!cell) return { ok: false, reason: `la zona ${zone} está llena — haz lugar y reinténtalo`, stats, forjado };

  // La PIEZA: un átomo Tool que arrastra su belt (server real + belt_ref real + tools verificadas),
  // atado al puppet_id del request. MISMA forma que un átomo del catálogo o una card BYO → entra
  // por la vía normal (api.placeTile → rebuildModel le da ida+eco al Núcleo). NO muta el modelo.
  const piece = {
    id: _uid(server),
    key: `forged:${server}`,
    label: _prettyLabel(server, label),
    category: hasWrite ? "write" : "read",
    atom: "tool",
    server,                       // ← SERVER REAL (≠null) — el MCP forjado
    ref: server,
    tools: finalTools,            // ← las tool.validada que sobrevivieron
    belt_ref,                     // ← BELT_REF REAL (synth_belts) — el runtime lo resuelve igual que el catálogo
    puppet_id: forjado.puppet_id || body.puppet_id || null,  // ← atada al puppet_id
    connector: null,
    auth: (body.auth_in === "header" ? "session-header" : "token-query") + " (vault)",
    sub: `forjado en vivo · ${finalTools.length} tool${finalTools.length === 1 ? "" : "s"} · ${body.url || ""}`,
    state: "ready",
    armario: "apps",
    role: zone,
    gated: hasWrite,              // write toca el mundo → nace GATEADA (candado sobre la línea, F5)
    forged: true,                 // provenance: la pieza vino del Motor B (no del catálogo/BYO)
  };

  const placed = api.placeTile(piece, cell.gx, cell.gy);
  if (!placed) return { ok: false, reason: "no pude colocar la pieza en el cuarto", stats, forjado };
  api.pulse(piece.id);

  onState(`equipé <b>${piece.label}</b> · ${finalTools.length} tools reales`, "ok");
  return { ok: true, piece, server, belt_ref, puppet_id: piece.puppet_id, tools: finalTools, gated: hasWrite, stats, forjado };
}

/**
 * PIEZA DEL REGISTRY (1c · camino FOUND) — el resolver TRAJO un MCP verificado (sin forjar) y el
 * dispatcher YA lo equipó server-side (equip_resolved → recipe.belt_refs). Acá lo materializamos
 * como pieza del Cuarto para que se VEA. server/belt_ref/tools son los del evento `mcp.equipado`.
 *
 * @param {object} opts.api       - api de mountCuarto
 * @param {object} opts.equipado  - el evento mcp.equipado {server,tools[],belt_ref,puppet_id,tools_detail}
 * @param {string} [opts.label]
 * @returns {{ok, piece?, server?, belt_ref?, tools?, reason?}}
 */
export function equipResolvedMcp({ api, equipado, label = null, onState = () => {} }) {
  if (!equipado) return { ok: false, reason: "el resolver no devolvió un MCP equipado" };
  const server = equipado.server;
  const belt_ref = equipado.belt_ref;
  const tools = Array.isArray(equipado.tools) ? equipado.tools.slice() : [];
  if (!server || !belt_ref || !tools.length) {
    return { ok: false, reason: "el resolver trajo un MCP incompleto (server/belt_ref/tools)" };
  }
  // los MCP del registry suelen ser read+write; sin kind por-tool, los colocamos en fuentes (read)
  // sin gate (el resolver YA verificó identidad por DNS/owner — anti-impostor). La belt es real.
  const zone = ZONE_OF_KIND.read;
  // [FIX-P11 · §4] ESTE es el camino por el que KiCad entró tres veces: el catálogo del
  // registro equipa server-side y después materializa acá con un id nuevo cada vez. El
  // dedupe va antes de tocar el piso, y DICE lo que pasa en vez de colocar una gemela.
  // La sonda tiene que tener la MISMA FORMA que la pieza que se va a colocar — server,
  // belt Y CAPACIDAD (`key`/`tools`). Con un objeto pelado, la capacidad se lee de un
  // label vacío y NUNCA colisiona con la pieza real (que sí lleva key): el dedupe queda
  // mudo, la gemela llega al backstop de placeTile y el mensaje sale equivocado — «no
  // pude colocar la pieza», que suena a fallo nuestro, en vez de «ya la tenés».
  const yaEsta = api.yaColocadaPor && api.yaColocadaPor(
    { server, belt_ref, atom: "tool", key: `resolved:${server}`, tools });
  if (yaEsta) {
    const nombre = _prettyLabel(server, label);
    try { api.pulse && api.pulse(yaEsta); } catch (e) {}
    onState(`<b>${nombre}</b> ya está en El Cuarto`, "info");
    return { ok: false, duplicada: true, pieceId: yaEsta, server, belt_ref, nombre,
             reason: `${nombre} ya está en El Cuarto` };
  }
  const cell = api.freeCell(zone);
  if (!cell) return { ok: false, reason: `la zona ${zone} está llena — haz lugar y reinténtalo` };
  const piece = {
    id: _uid(server),
    key: `resolved:${server}`,
    label: _prettyLabel(server, label),
    category: "read",
    atom: "tool",
    server,
    ref: server,
    tools,
    belt_ref,
    puppet_id: equipado.puppet_id || null,
    connector: null,
    auth: "registry (vault)",
    sub: `traído del registry · ${tools.length} tool${tools.length === 1 ? "" : "s"} verificada${tools.length === 1 ? "" : "s"}`,
    state: "ready",
    armario: "apps",
    role: zone,
    gated: false,
    resolved: true,               // provenance: vino del registry (no forjado)
  };
  const placed = api.placeTile(piece, cell.gx, cell.gy);
  if (!placed) return { ok: false, reason: "no pude colocar la pieza en el cuarto" };
  api.pulse(piece.id);
  onState(`equipé <b>${piece.label}</b> · ${tools.length} tools del registry`, "ok");
  return { ok: true, piece, server, belt_ref, tools };
}

/**
 * Consumidor STANDALONE de 1-B (lee /v1/inspect/forge directo, sin coreografía ni dispatch).
 * Backward-compat para forge_equip_e2e.mjs. La VÍA DE PRODUCTO del Cuarto NO usa esto: usa
 * `inspectAndEquip` (cuarto.inspect.js), que lee UN solo stream (dispatch) y delega la
 * materialización a `equipForgedMcp` — sin segundo fetch. Acá reusamos la MISMA materialización.
 *
 * @returns {Promise<{ok, piece?, server?, belt_ref?, puppet_id?, tools?, reason?, stats}>}
 */
export async function forgeAndEquip({ api, body, label = null, onState = () => {}, signal = null }) {
  const events = [];
  onState("forjando tu MCP en vivo…", "work");

  let resp;
  try {
    resp = await fetch("/v1/inspect/forge", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    return { ok: false, reason: `no pude llamar al motor: ${e.message}`, stats: { proposed: 0, validated: 0, dropped: 0 } };
  }
  if (!resp.ok || !resp.body) {
    // el borde rechazó (400 forma/url · 429 rate-limit · 400 SSRF): leelo honesto, sin stream.
    let detail = `HTTP ${resp.status}`;
    try { const j = await resp.json(); const d = j && j.detail;
      detail = (d && typeof d === "object") ? (d.reason || d.detail || d.error || JSON.stringify(d)) : (typeof d === "string" ? d : detail);
    } catch {}
    return { ok: false, reason: detail, stats: { proposed: 0, validated: 0, dropped: 0 } };
  }

  await _readSSE(resp, ({ type, data }) => {
    const ev = (data && typeof data === "object") ? { ...data, type: type || data.type } : { type, _raw: data };
    events.push(ev);
    switch (type) {
      case "tool.propuesta": onState(`propuso <b>${ev.nombre || "tool"}</b>…`, "work"); break;
      case "sesion.ok":      onState("sesión válida con el target", "ok"); break;
      case "observando":     onState("observando el software…", "work"); break;
      default: break;
    }
  }, signal);

  return equipForgedMcp({ api, events, label, body, onState });
}
