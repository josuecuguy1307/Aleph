/* cuarto.browser.js — SUBSISTEMA DE UI · la CUARTA forma: captura de sesión por NAVEGADOR (OAuth+2FA).
 * Rama 3-browser-oauth-entrada · Ola 3.
 *
 * Esta es la ÚNICA pieza nueva del pipeline: la CAPTURA de la sesión humana. Todo lo demás
 * (coreografía 1-A, equip 1-B, resolver 1-C, manual 2-D, evidencia 2-E) ya existe y se reusa tal cual.
 *
 * Flujo: cuando el target exige OAuth+2FA, `captureBrowserSession` llama a
 *   POST /v1/inspect/session/browser
 * que abre un navegador INSTRUMENTADO donde el HUMANO hace login + el segundo factor a mano
 * (LÍNEA ROJA §2: el sistema NUNCA automatiza el 2FA — sólo observa y captura la sesión que queda).
 * El stream SSE narra cada fase REAL (abriendo → navegando → esperando_humano → capturando) y, al
 * terminar, devuelve `session_key` (la capability que el forge reusa) o un fallo HONESTO.
 *
 * CERO-TEATRO: `ok:true` SÓLO si el backend emitió `sesion.capturada` con cookies reales. Si el
 * humano cancela / expira / no queda sesión → `ok:false` con el motivo real (sin sesión fantasma).
 *
 * Una vez devuelto el session_key, el caller sigue con el pipeline NORMAL:
 *   inspectAndEquip({ forma:"browser-oauth", sessionKey, url, synthAlias:"brain", … })
 * (la forja post-sesión usa el modelo Opus vía el shim :8923 — no Groq).
 */

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

// parsea un frame SSE ("event: <t>\ndata: <json>") → objeto del evento (o null).
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

// frase humana por fase (lo que está pasando AHORA en el navegador instrumentado).
function _phaseText(ev, host) {
  switch (ev.fase) {
    case "abriendo":          return `abriendo un <b>navegador instrumentado</b> para que entres a <b>${_esc(host)}</b>…`;
    case "navegando":         return `te llevé al login <span style="color:var(--muted)">${_esc(ev.login_url || "")}</span> — <b>inicia sesión tú</b> (incluido el 2FA)`;
    case "esperando_humano":  return `⏳ esperando a que <b>completes el login + 2FA</b> en la ventana… <span style="color:var(--muted)">(el segundo factor lo haces tú; el sistema sólo observa)</span>`;
    case "capturando":        return `login detectado · <b>capturando tu sesión</b>…`;
    case "reusando":          return `ya tenías una sesión guardada · <b>la reuso</b> (sin reabrir el navegador)`;
    default:                  return `navegador · ${_esc(ev.fase || "")}`;
  }
}

/**
 * Abre el navegador instrumentado y captura la sesión humana (login + 2FA).
 * @returns {Promise<{ok:boolean, session_key?:string, host?:string, cookie_count?:number,
 *                     origins_count?:number, reused?:boolean, red_line?:string, events:Array, error?:string}>}
 */
export async function captureBrowserSession({
  url, loginUrl = null, readyUrl = null, readySelector = null, channel = null,
  sessionKey = null, puppetId = null, loginTimeoutMs = 180000,
  onState = () => {}, onEvent = null,
} = {}) {
  const host = String(url || "").replace(/^https?:\/\//, "").split("/")[0] || "target";
  if (!url) { onState(`<span style="color:var(--gate)">falta la URL del software</span>`); return { ok: false, events: [], error: "url_requerida" }; }
  if (!readyUrl && !readySelector) {
    onState(`<span style="color:var(--gate)">dime cómo reconocer que terminaste el login (una parte de la URL a la que caes ya adentro, o un elemento visible sólo logueado)</span>`);
    return { ok: false, events: [], error: "ready_signal_requerida" };
  }

  const body = { url, login_url: loginUrl || undefined, ready_url: readyUrl || undefined,
                 ready_selector: readySelector || undefined, channel: channel || undefined,
                 session_key: sessionKey || undefined, puppet_id: puppetId || undefined,
                 login_timeout_ms: loginTimeoutMs };

  onState(`preparando la <b>captura de sesión</b> de <b>${_esc(host)}</b> (login + 2FA lo haces tú)…`);

  let resp;
  try {
    resp = await fetch("/v1/inspect/session/browser", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    onState(`<span style="color:var(--gate)">no pude abrir la captura: ${_esc(e.message)}</span>`);
    return { ok: false, events: [], error: e.message };
  }
  // rechazo HONESTO del borde (400 url/ready · 429 rate-limit · SSRF guard) ANTES de abrir el stream.
  if (!resp.ok) {
    let det = null;
    try { det = (await resp.json()).detail; } catch {}
    const msg = (det && typeof det === "object") ? (det.reason || det.detail || det.error || JSON.stringify(det))
      : (typeof det === "string" ? det : `HTTP ${resp.status}`);
    onState(`<span style="color:var(--gate)">no pude capturar la sesión: ${_esc(msg)}</span>`);
    return { ok: false, events: [], error: String(msg) };
  }

  const events = [];
  let captured = null, errored = null;
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  const onFrame = (ev) => {
    if (!ev) return;
    events.push(ev);
    if (onEvent) { try { onEvent(ev); } catch {} }
    switch (ev.type) {
      case "browser.session.iniciado":
        onState(`captura iniciada · <span style="color:var(--muted)">el 2FA lo haces tú, nunca el sistema (línea roja)</span>`);
        break;
      case "browser.fase":
        onState(_phaseText(ev, host));
        break;
      case "sesion.capturada":
        captured = ev;
        onState(`✓ <b>sesión capturada</b> · ${ev.cookie_count ?? 0} cookie${(ev.cookie_count === 1) ? "" : "s"}${ev.reused ? " (reusada)" : ""} <span style="color:var(--muted)">— ahora forjo el MCP reusando tu sesión</span>`);
        break;
      case "error":
        errored = ev;
        onState(`<span style="color:var(--gate)">no se capturó la sesión: ${_esc(ev.detail || "el login no se completó")}</span>`);
        break;
    }
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
        onFrame(parseFrame(frame));
      }
    }
    if (buf.trim()) onFrame(parseFrame(buf));
  } catch (e) {
    onState(`<span style="color:var(--gate)">se cortó la captura: ${_esc(e.message)}</span>`);
    return { ok: false, events, error: e.message };
  }

  if (captured) {
    return {
      ok: true, session_key: captured.session_key, host: captured.host,
      cookie_count: captured.cookie_count, origins_count: captured.origins_count,
      reused: !!captured.reused, red_line: captured.red_line, events,
    };
  }
  // cero-teatro: sin sesion.capturada no hay sesión, punto.
  return { ok: false, events, error: (errored && errored.detail) || "no se capturó ninguna sesión" };
}
