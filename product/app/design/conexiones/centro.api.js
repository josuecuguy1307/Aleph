/* centro.api.js — el cliente del CENTRO DE CONEXIONES (Terminal B · nivel 1 + nivel 2).
 *
 * Habla con /v1/conexiones/* (el motor de REQUISITOS, que a su vez usa el Motor de Verdad).
 * No decide verdad ni inventa estados: lee, corre el checklist y devuelve lo que el
 * backend midió. El vocabulario de estados/causas es el CERRADO del motor — se importa de
 * cuarto.semaforo.js para que el Centro y el Cuarto pinten con el MISMO diccionario.
 *
 * Regla de la casa: toda espera tiene plazo y desenlace. Cada llamada acá lleva
 * AbortController; el stream lleva además un vigía de silencio (si el cable enmudece más
 * de SILENCIO_MAX, se corta con causa `timeout` en vez de dejar el latido girando).
 */

// ── sesión → Bearer (MISMO patrón que cuarto.semaforo.js / catalog_equip.js) ─────────
import { destinoDeSlug } from "../cuarto/cuarto.semaforo.js";

export function sesion() {
  try {
    if (window.AlephSession && window.AlephSession.get) return window.AlephSession.get();
    return JSON.parse(sessionStorage.getItem("puppet_user") || localStorage.getItem("puppet_user") || "null");
  } catch (e) { return null; }
}

// Mintar la sesión local NO puede ser una barrera para ver la pantalla: si el backend
// tarda (o no ofrece auth local), la lista se pinta igual y las filas dicen la verdad
// ("sin configurar"). Por eso lleva PLAZO y nunca se lo espera para renderizar.
const T_SESION = 8000;
export async function asegurarSesion(ms) {
  const u = sesion();
  if (u && u.id && u.session_token) return u;
  try {
    const A = window.AlephSession;
    if (!A || !A.ensureLocal) return null;
    return await Promise.race([
      A.ensureLocal().then((nu) => (nu && nu.id ? nu : null)),
      new Promise((res) => setTimeout(() => res(null), ms || T_SESION)),
    ]);
  } catch (e) { /* sin auth local → el backend contesta sin_sesion, honesto */ }
  return null;
}

function auth(h) {
  h = h || {};
  const u = sesion();
  if (u && u.session_token) h["Authorization"] = "Bearer " + u.session_token;
  return h;
}

const T_HTTP = 25000;
const SILENCIO_MAX = 45000;   // el cable puede tardar, pero no puede enmudecer para siempre

async function pedir(url, opts, ms) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), ms || T_HTTP);
  try {
    const r = await fetch(url, Object.assign({}, opts || {}, { signal: c.signal, headers: auth((opts || {}).headers) }));
    return r;
  } finally { clearTimeout(t); }
}

// ── NIVEL 1 · la lista escaneable + el conteo de arriba ─────────────────────────────
export async function listar(opts) {
  opts = opts || {};
  let url = "/v1/conexiones";
  const extra = (opts.mcp || []).map((r) => "mcp=" + encodeURIComponent(r)).join("&");
  if (extra) url += "?" + extra;
  const r = await pedir(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return await r.json();
}

// ── definición de requisitos (para pintar ○ pendientes ANTES de correr nada) ─────────
const _defsCache = {};
export async function requisitosDe(familia) {
  if (_defsCache[familia]) return _defsCache[familia];
  const r = await pedir("/v1/conexiones/requisitos/" + encodeURIComponent(familia),
    { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const d = await r.json();
  _defsCache[familia] = d.requisitos || [];
  return _defsCache[familia];
}

// ── NIVEL 2 · el checklist EN VIVO (SSE por POST: EventSource no manda el Bearer) ────
// onEvento(ev) recibe, tal cual llega: inicio · fila.inicio · requisito.probando ·
// requisito.resultado · fila.cerrada · latido · cerrado. Uno o N slugs por el MISMO
// cable → el batch en paralelo (§F) no es otro camino, es el mismo con más filas.
export async function correrChecklist(slugs, onEvento, opts) {
  opts = opts || {};
  const lista = Array.isArray(slugs) ? slugs : [slugs];
  const ctrl = new AbortController();
  let vivo = true;
  let ultimo = Date.now();
  const vigia = setInterval(() => {
    if (vivo && Date.now() - ultimo > SILENCIO_MAX) { try { ctrl.abort(); } catch (e) {} }
  }, 2000);
  const cerrar = (ev) => { if (!vivo) return; vivo = false; clearInterval(vigia); onEvento(ev); };

  let resp;
  try {
    resp = await fetch("/v1/conexiones/checklist", {
      method: "POST", signal: ctrl.signal,
      headers: auth({ "Content-Type": "application/json", Accept: "text/event-stream" }),
      body: JSON.stringify({ slugs: lista, profundo: !!opts.profundo, modelos: opts.modelos || {} }),
    });
  } catch (e) {
    cerrar({ type: "cerrado", ok: false, motivo: "sin_red", causa: "sin_red", detalle: String(e && e.message || e) });
    return { ok: false };
  }
  if (!resp.ok || !resp.body) {
    cerrar({ type: "cerrado", ok: false, motivo: "http", http: resp.status,
             causa: resp.status === 401 ? "sin_sesion" : "error_upstream" });
    return { ok: false, http: resp.status };
  }

  const reader = resp.body.getReader(), dec = new TextDecoder();
  let buf = "", ok = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      ultimo = Date.now();
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const bloque = buf.slice(0, i); buf = buf.slice(i + 2);
        for (const linea of bloque.split("\n")) {
          if (!linea.startsWith("data: ")) continue;
          let ev; try { ev = JSON.parse(linea.slice(6)); } catch (e) { continue; }
          if (ev.type === "cerrado") { ok = !!ev.ok; cerrar(ev); }
          else if (vivo) onEvento(ev);
        }
      }
    }
  } catch (e) {
    cerrar({ type: "cerrado", ok: false, motivo: "corte", causa: "timeout",
             detalle: "el checklist dejó de responder y lo corté" });
    return { ok: false };
  }
  // el servidor cerró sin decir `cerrado` → DESENLACE igual (jamás un latido eterno)
  cerrar({ type: "cerrado", ok: ok, motivo: ok ? "" : "sin_cierre", causa: ok ? null : "error_upstream" });
  return { ok };
}

// ── §E · agregar key: pegás → valida en vivo → guarda cifrada → queda conectada ──────
export async function agregarKey({ provider, secret, base_url, guardar_igual }) {
  await asegurarSesion();                       // sin sesión no hay dónde guardarla
  const r = await pedir("/v1/conexiones/key", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ provider, secret, base_url: base_url || null, guardar_igual: !!guardar_igual }),
  }, 40000);
  if (!r.ok) return { ok: false, estado: "roto", causa: r.status === 401 ? "sin_sesion" : "error_upstream",
                      mensaje: "el backend respondió " + r.status };
  return await r.json();
}

export async function quitarKey(provider) {
  const r = await pedir("/v1/conexiones/key/" + encodeURIComponent(provider), { method: "DELETE" });
  if (!r.ok) return { deleted: false, http: r.status };
  return await r.json();
}

// ── deep-link: Conexiones.dc.html?svc=<slug> — tolerante (api.groq · groq · claude_cli) ──
export function slugDeLaUrl(loc) {
  try {
    const qs = new URLSearchParams((loc || location).search);
    return (qs.get("svc") || qs.get("c") || qs.get("slug") || "").trim();
  } catch (e) { return ""; }
}

export function coincide(fila, slug) {
  if (!fila || !slug) return false;
  const s = String(slug).toLowerCase();
  if (String(fila.slug).toLowerCase() === s) return true;
  if (String(fila.ref).toLowerCase() === s) return true;
  if (String(fila.label || "").toLowerCase() === s) return true;
  // «mcp.belts/x.mcp.json#srv» ← el Cuarto puede mandar sólo el nombre del servidor
  const srv = String(fila.ref).split("#")[1];
  return !!srv && srv.toLowerCase() === s;
}

// ── A DÓNDE MANDA UN SLUG ────────────────────────────────────────────────────────────
// El Centro murió. El destino sale de la ÚNICA tabla (cuarto.semaforo.js · destinoDeSlug):
// cognición → Modelos, conectores → Conectores. El redirect de Conexiones.dc.html queda
// como red de seguridad para links viejos, no como el camino que usa la app.
export function urlDelCentro(slug, opts) {
  opts = opts || {};
  const d = destinoDeSlug(slug);
  const q = new URLSearchParams(d.q);
  if (opts.volver) q.set("return", opts.volver);
  const qs = q.toString();
  return (opts.base || "") + d.pantalla + (qs ? "?" + qs : "");
}

export default { sesion, asegurarSesion, listar, requisitosDe, correrChecklist,
                 agregarKey, quitarKey, slugDeLaUrl, coincide, urlDelCentro };
