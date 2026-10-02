/* catalog_equip.js — CONSUMIDOR del carril LIBRE equipar-desde-registro (POST /v1/catalog/equip).
 *
 * La línea del negocio: usar/conectar lo que YA existe = FREE (este camino) · construir lo que
 * NO existe = premium (Motor B, /v1/inspect/dispatch). Este módulo streamea el SSE de CURACIÓN
 * EN VIVO (buscar → curar → equipar) y devuelve un resultado TIPADO. Es Pixi-free y DOM-free:
 * cada superficie materializa a su manera (el Cuarto con equipResolvedMcp; Conectar refresca el
 * grid). Reusa la sesión (AlephSession/puppet_user), MISMO contrato que cuarto.inspect.js.
 *
 * Contrato de eventos (lo que emite el backend · el mismo vocabulario que el dispatcher + curación):
 *   dispatch.iniciado → resolver.buscando → { resolver.registry_down | resolver.miss |
 *     resolver.encontrado → curacion.probando → { curacion.rechazo | curacion.necesita_credencial |
 *     mcp.equipado } } → cerrado{path, ok, cause?, server?}
 *
 * Causas tipadas del cerrado (fallo VISIBLE, jamás mudo):
 *   registry_unreachable · no_confiable · curacion_rechazo · sin_red  (+ needs_credential = ruta a Conectar)
 */

import { causaDe } from "../conectores/causas-catalogo.js";

function _sessAuth(h) {
  h = h || {};
  try {
    const u = (window.AlephSession && window.AlephSession.get)
      ? window.AlephSession.get()
      : JSON.parse(sessionStorage.getItem("puppet_user") || localStorage.getItem("puppet_user") || "null");
    if (u && u.session_token) h["Authorization"] = "Bearer " + u.session_token;
  } catch (e) { /* sin sesión → el backend responde 401 honesto */ }
  return h;
}

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function _parseFrame(frame) {
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

/** Narración por defecto de la CURACIÓN EN VIVO (ES). Cada superficie puede ignorar `onState`
 *  y pintar los `onEvent` a su gusto; esto da un HUD honesto out-of-the-box. */
function _defaultState(ev, service) {
  const svc = _esc(service || "");
  switch (ev.type) {
    case "dispatch.iniciado": return `equipando <b>${_esc(ev.server_name || svc)}</b> desde el catálogo…`;
    case "resolver.buscando": return `buscando un MCP verificado para <b>${svc}</b> en el registro…`;
    case "resolver.encontrado":
      return ev.from_cache
        ? `✓ traje <b>${_esc(ev.server_name)}</b> de lo guardado <span class="muted">(el catálogo no responde ahora; revalido en vivo)</span>`
        : `✓ <b>${_esc(ev.server_name)}</b> verificado en el registro <span class="muted">(${_esc(ev.vendor_kind || "confiable")})</span>`;
    case "curacion.probando":
      return `curando <b>${_esc(ev.server || svc)}</b>… <span class="muted">arranco el MCP y verifico que viva y sirva sus tools</span>`;
    case "curacion.rechazo": {
      // ⚠️ ESTO PINTABA `ev.detail`, que el backend mandaba fijo: «La opción no pasó la
      // comprobación». Era una copy paralela —en Python— para un hecho que ya tenía la suya,
      // y decía menos: las cuatro causas finas se veían todas igual. Ahora sale del MISMO
      // vocabulario que la sección, así el fracaso se cuenta una sola vez y con las mismas
      // palabras en las dos superficies. `detail` queda de respaldo para un backend viejo.
      const c = causaDe(ev.cause);
      const porque = (c && c.texto) || (ev.detail || "").slice(0, 90);
      return `<span class="bad">✗ ${_esc(ev.server || svc)}: ${_esc(porque)}</span> <span class="muted">— no equipo nada crudo</span>`;
    }
    case "curacion.necesita_credencial":
      return `<b>${_esc(ev.server || svc)}</b> necesita tu llave — <span class="muted">conéctalo primero para equiparlo</span>`;
    case "resolver.registry_down":
      return `<span class="bad">el catálogo público no responde ahora — no pude confirmar si existe un MCP para <b>${svc}</b>. Reintenta ↻</span> <span class="muted">(no forjo nada a ciegas)</span>`;
    case "resolver.miss":
      return ev.rejected_impostor
        ? `<span class="bad">impostor rechazado: ${_esc((ev.reason || "").slice(0, 90))}</span>`
        : `sin MCP verificado en el registro para <b>${svc}</b> <span class="muted">— construir uno es premium (Motor B)</span>`;
    case "mcp.equipado":
      return `✓ equipé <b>${_esc(ev.server || svc)}</b> · ${(ev.tools || []).length} tool${(ev.tools || []).length === 1 ? "" : "s"} reales`;
    default: return null;
  }
}

/* [T6 §8.1] el stream con PLAZO: sin actividad por INACTIVITY_MS o pasado TOTAL_MS se corta
 * con un error tipado `timeout` — jamás un "curando…" congelado para siempre. */
const _CONSUME_INACTIVITY_MS = 75_000;
const _CONSUME_TOTAL_MS = 240_000;
// seam de verificación: el harness acorta los plazos para probar el corte sin esperar minutos
const _inactMs = () => Number(globalThis.__catalogEquipInactivityMs) || _CONSUME_INACTIVITY_MS;
const _totalMs = () => Number(globalThis.__catalogEquipTotalMs) || _CONSUME_TOTAL_MS;
async function _consume(resp, onEvent) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  const list = [];
  const t0 = Date.now();
  const readT = () => new Promise((resolve, reject) => {
    const t = setTimeout(() => {
      const e = new Error("timeout"); e.timeout = true;
      try { reader.cancel().catch(() => {}); } catch (_) {}
      reject(e);
    }, Math.max(60, Math.min(_inactMs(), _totalMs() - (Date.now() - t0))));
    reader.read().then((r) => { clearTimeout(t); resolve(r); }, (e) => { clearTimeout(t); reject(e); });
  });
  while (true) {
    if (Date.now() - t0 > _totalMs()) { const e = new Error("timeout"); e.timeout = true; try { reader.cancel().catch(() => {}); } catch (_) {} throw e; }
    const { value, done } = await readT();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
      const ev = _parseFrame(frame);
      if (ev) { list.push(ev); onEvent(ev); }
    }
  }
  if (buf.trim()) { const ev = _parseFrame(buf); if (ev) { list.push(ev); onEvent(ev); } }
  return list;
}

/**
 * curateAndEquipRegistry — corre el carril libre y devuelve el desenlace TIPADO.
 * @returns {Promise<{ok, cause, server?, belt_ref?, tools?, equipado?, events, rejectedImpostor,
 *                     premiumAvailable, needsCredential, retry, reason}>}
 *   cause ∈ null(ok) | registry_unreachable | no_confiable | curacion_rechazo |
 *           needs_credential | estado_local_no_escribible | error_backend | sin_red
 */
export async function curateAndEquipRegistry({
  service, serverName = null, credential = null, puppetId = null,
  seedCandidates = null, seedSpec = null, onEvent = () => {}, onState = () => {},
} = {}) {
  const svc = String(service || "").trim();
  const body = { service: svc, server_name: serverName, credential, puppet_id: puppetId };
  if (seedCandidates != null) body.seed_candidates = seedCandidates;
  if (seedSpec != null) body.seed_spec = seedSpec;

  let resp;
  try {
    // [T6 §8.1] el connect también con plazo (25 s): un backend que no contesta no cuelga el botón.
    const ac = new AbortController(); const act = setTimeout(() => ac.abort(), 25_000);
    try {
      resp = await fetch("/v1/catalog/equip", {
        method: "POST",
        headers: _sessAuth({ "Content-Type": "application/json", "Accept": "text/event-stream" }),
        body: JSON.stringify(body),
        signal: ac.signal,
      });
    } finally { clearTimeout(act); }
  } catch (e) {
    const timedOut = e && (e.name === "AbortError" || e.timeout);
    const reason = timedOut ? "el catálogo no respondió a tiempo" : e.message;
    const ev = { type: "error", stage: timedOut ? "timeout" : "conexion", detail: reason };
    onEvent(ev); onState(`<span class="bad">${timedOut ? _esc(reason) : "no pude conectar al catálogo: " + _esc(reason)}</span>`, ev);
    return { ok: false, cause: timedOut ? "timeout" : "sin_red", retry: true, events: [ev], reason };
  }
  if (!resp.ok) {
    // 401 = sin sesión (mutación = identidad). El resto = borde honesto.
    let det = null;
    try { det = (await resp.json()).detail; } catch {}
    const reason = (det && (det.detail || det.error)) || `HTTP ${resp.status}`;
    const ev = { type: "error", stage: "borde", status: resp.status, detail: det ?? reason };
    onEvent(ev);
    onState(`<span class="bad">${resp.status === 401 ? "inicia sesión para equipar" : _esc(reason)}</span>`, ev);
    const cause = resp.status === 401 ? "no_session"
      : resp.status === 503 ? "estado_local_no_escribible"
        : resp.status >= 500 ? "error_backend" : "solicitud_rechazada";
    return { ok: false, cause,
             status: resp.status, events: [ev], reason };
  }

  let equipado = null;
  const drive = (ev) => {
    onEvent(ev);
    const html = _defaultState(ev, svc);
    if (html) onState(html, ev);
    if (ev.type === "mcp.equipado") equipado = ev;
  };
  let events;
  try {
    events = await _consume(resp, drive);
  } catch (e) {
    // [T6 §8.1] timeout tipado ≠ corte de red: cada uno con su verdad y su camino (reintentar).
    const timedOut = !!(e && e.timeout);
    const reason = timedOut ? "la curación tardó demasiado" : e.message;
    const ev = { type: "error", stage: timedOut ? "timeout" : "stream", detail: reason };
    onEvent(ev); onState(`<span class="bad">${timedOut ? _esc(reason) : "se cortó el stream: " + _esc(reason)}</span>`, ev);
    return { ok: false, cause: timedOut ? "timeout" : "sin_red", retry: true, events: [ev], reason };
  }

  const closed = events.find((e) => e.type === "cerrado") || {};
  if (equipado && closed.ok) {
    return {
      ok: true, cause: null, server: equipado.server, belt_ref: equipado.belt_ref,
      tools: equipado.tools || [], registered: equipado.registered, equipado, events,
      rejectedImpostor: false, premiumAvailable: false, needsCredential: false, retry: false,
    };
  }
  return {
    ok: false, cause: closed.cause || "sin_red", server: closed.server || serverName || null,
    trusted: closed.trusted || null, events, equipado: null,
    rejectedImpostor: !!closed.rejected_impostor,
    premiumAvailable: !!closed.premium_available,
    needsCredential: closed.cause === "needs_credential",
    retry: !!closed.retry,
    reason: (events.find((e) => /miss|rechazo|registry_down|necesita|error/.test(e.type || "")) || {}).reason
            || (closed.cause || "no pude equipar"),
  };
}
