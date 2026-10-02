/* modelos.api.js — el cliente del CENTRO DE MODELOS (FIX-P8).
 *
 * Habla con /v1/modelos/* (el sidecar). No decide verdad ni inventa estados: lee, corre
 * y devuelve lo que el backend midió. Los endpoints nuevos viven TODOS en el sidecar —
 * consultar Hugging Face, medir disco/RAM y bajar archivos son cosas del proceso que
 * tiene sistema de archivos, no del browser.
 *
 * Regla de la casa: toda espera tiene plazo y desenlace. Cada llamada lleva
 * AbortController; el stream de descarga lleva además un vigía de silencio.
 */

export function sesion() {
  try {
    if (window.AlephSession && window.AlephSession.get) return window.AlephSession.get();
    return JSON.parse(sessionStorage.getItem("puppet_user") || localStorage.getItem("puppet_user") || "null");
  } catch (e) { return null; }
}

function auth(h) {
  h = h || {};
  const u = sesion();
  if (u && u.session_token) h["Authorization"] = "Bearer " + u.session_token;
  return h;
}

const T_HTTP = 30000;
const T_HF = 40000;             // la API pública de HF puede tardar; no para siempre
const T_LOTE = 90000;            // cinco categorías concurrentes + detalle/peso en sidecar
const SILENCIO_MAX = 90000;     // una descarga puede tardar, pero no puede enmudecer

async function pedir(url, opts, ms) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), ms || T_HTTP);
  try {
    return await fetch(url, Object.assign({}, opts || {}, { signal: c.signal, headers: auth((opts || {}).headers) }));
  } finally { clearTimeout(t); }
}

async function json(url, opts, ms) {
  const r = await pedir(url, opts, ms);
  if (!r.ok) {
    let det = "";
    try {
      const body = await r.json();
      const pick = (value, depth = 0) => {
        if (depth > 3 || value == null) return "";
        if (typeof value === "string") return value.trim().slice(0, 240);
        if (Array.isArray(value)) return value.map((item) => pick(item, depth + 1)).filter(Boolean).join("; ").slice(0, 240);
        if (typeof value === "object") {
          for (const key of ["detail", "message", "error", "reason", "provider_error"]) {
            const text = pick(value[key], depth + 1);
            if (text) return text;
          }
        }
        return "";
      };
      det = pick(body);
    } catch (e) { /* cuerpo no-JSON */ }
    const err = new Error("HTTP " + r.status + (det ? " · " + det : ""));
    err.http = r.status;
    throw err;
  }
  return await r.json();
}

/** La pantalla entera: filas + grupos + las 5 categorías + piezas + tu máquina. */
export const listar = () => json("/v1/modelos", { headers: { Accept: "application/json" } });

/** MODELOS V2: el ÚNICO request inicial. Cada fila HF ya trae peso/RAM/veredicto. */
export function listarV2(opts) {
  opts = opts || {};
  const q = new URLSearchParams();
  if (opts.limiteHf) q.set("limite_hf", String(opts.limiteHf));
  if (opts.formato) q.set("formato", opts.formato);
  return json("/v1/modelos/v2" + (q.toString() ? "?" + q : ""),
    { headers: { Accept: "application/json" } }, T_LOTE);
}

/** Pool compartido y liviano: Conectados + Default; el Guía agrega ∩ frontier. */
export function selector(contexto) {
  const q = contexto ? "?contexto=" + encodeURIComponent(contexto) : "";
  return json("/v1/modelos/selector" + q, { headers: { Accept: "application/json" } });
}

/** Default y elección por contexto viven en el sidecar, no en una tabla del cliente. */
export const preferencias = () =>
  json("/v1/modelos/preferencias", { headers: { Accept: "application/json" } });
export const guardarPreferencias = (cambio) =>
  json("/v1/modelos/preferencias", {
    method: "PUT", headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(cambio || {}),
  });

/** Sesión CLI persistida sin tokens/paths: diagnóstico público del sidecar. */
export const sesionesCli = () =>
  json("/v1/modelos/cli/sesiones", { headers: { Accept: "application/json" } });
export const revalidarClaude = () =>
  json("/v1/brains/status?refresh_claude=1", { headers: { Accept: "application/json" } });

function cliHeaders(extra = {}) {
  const cap = window.__ALEPH_LAUNCH_CAP__;
  return { ...extra, ...(typeof cap === "string" && cap ? { "X-Aleph-Launch": cap } : {}) };
}
export const ejecutablesCli = () =>
  json("/v1/brains/executables", { headers: cliHeaders() });
export const guardarEjecutableCli = (provider_id, mode, path = "") =>
  json("/v1/brains/executables", { method: "PUT", headers: cliHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ provider_id, mode, path }) });
export const verificarEjecutableCli = (provider_id, path) =>
  json("/v1/brains/executables/verify", { method: "POST", headers: cliHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ provider_id, mode: "manual", path }) });

/** Disco, RAM y qué runtimes existen DE VERDAD. */
export const maquina = () => json("/v1/modelos/maquina", { headers: { Accept: "application/json" } });

/** Lo que YA está en tu máquina. NO toca la red externa: existe aunque el mundo se caiga. */
export const instalados = () => json("/v1/modelos/instalados", { headers: { Accept: "application/json" } });

/** El catálogo VIVO de Hugging Face por categoría.
 *  Sin red el backend devuelve `{red:false, causa, detalle}` — NO una lista vacía. El
 *  caller tiene que pintar el fallo; una lista vacía fingida sería la mentira exacta. */
export function catalogo(categoria, formato, limite) {
  const q = new URLSearchParams({ categoria });
  if (formato) q.set("formato", formato);
  if (limite) q.set("limite", String(limite));
  return json("/v1/modelos/catalogo?" + q.toString(), { headers: { Accept: "application/json" } }, T_HF);
}

/** ¿Este modelo alcanza para esta pieza? Con porqué, recomendación y camino. */
export function gate(pieza, opts) {
  opts = opts || {};
  const q = new URLSearchParams({ pieza });
  ["slug", "tier", "categoria", "familia"].forEach((k) => { if (opts[k]) q.set(k, opts[k]); });
  return json("/v1/modelos/gate?" + q.toString(), { headers: { Accept: "application/json" } });
}

/* ── EL CHECKLIST VIVO · los verbos completándose, uno por uno ─────────────────────
 *
 * [F7 · obra 3] `POST /v1/modelos/checklist` lo construyó F4c (obra 4) y hasta hoy tenía
 * **cero llamadores**: el endpoint emitía la secuencia entera por SSE y nadie la miraba,
 * así que el spinner mudo que esa obra vino a matar seguía mudo.
 *
 * Mismos nombres de evento que `POST /v1/conexiones/checklist` (Gate 1) — a propósito: un
 * segundo dialecto sería una segunda cosa que mantener. `fila.inicio` trae los verbos
 * ANTES de correr ninguno (el usuario ve el plan, no sólo el registro), `verbo.*` los va
 * cerrando, `fila.cerrada` trae el veredicto tipado.
 *
 * Devuelve el evento `fila.cerrada` (o `null` si el cable murió sin cerrar). Toda espera
 * tiene plazo y desenlace: `T_CHECKLIST` corta.
 */
const T_CHECKLIST = 120000;

export async function checklistEnVivo(refs, onEvento) {
  const lista = Array.isArray(refs) ? refs : [refs];
  const c = new AbortController();
  const t = setTimeout(() => { try { c.abort(); } catch (e) { /* ya cortado */ } }, T_CHECKLIST);
  let cierre = null;
  try {
    const r = await fetch("/v1/modelos/checklist", {
      method: "POST", signal: c.signal,
      headers: auth({ "Content-Type": "application/json", Accept: "text/event-stream" }),
      body: JSON.stringify({ refs: lista }),
    });
    if (!r.ok || !r.body) throw new Error("HTTP " + r.status);
    const lector = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const trozo = await lector.read();
      if (trozo.done) break;
      buf += dec.decode(trozo.value, { stream: true });
      const partes = buf.split("\n\n");
      buf = partes.pop();
      for (const p of partes) {
        const linea = p.split("\n").find((x) => x.startsWith("data: "));
        if (!linea) continue;
        let ev;
        try { ev = JSON.parse(linea.slice(6)); } catch (e) { continue; }
        if (ev.tipo === "fila.cerrada" || ev.type === "fila.cerrada") cierre = ev;
        try { onEvento(ev); } catch (e) { /* el pintor no puede matar el cable */ }
      }
    }
  } finally { clearTimeout(t); }
  return cierre;
}

/** La prueba automática, a pedido. Corre el modelo; jamás declara. */
export const probar = (slug, extra) =>
  json("/v1/modelos/probar", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ slug }, extra || {})),
  }, 240000);

/** Liberar espacio de verdad: el archivo, la carpeta y el registro del runtime. */
export const borrar = (slug) =>
  json("/v1/modelos/local/" + encodeURIComponent(slug), { method: "DELETE" }, 120000);

export const cancelar = (slug) =>
  json("/v1/modelos/cancelar", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug }),
  });

/** Cachea el avatar de una org de HF. Se llama AL DESCARGAR, jamás al listar: una lista
 *  de 8 modelos no puede disparar 8 fetch a un tercero mientras alguien mira la pantalla. */
export const cachearAvatar = (org) =>
  json("/v1/modelos/avatar/" + encodeURIComponent(org), { method: "POST" }, 20000)
    .catch(() => ({ cacheado: false }));

/* ── LA DESCARGA · SSE, con desenlace SIEMPRE ────────────────────────────────────────
 * El backend emite: veredicto → arranque → progreso* → instalando → instalado →
 * probando → prueba → fin → cerrado. `onEvento` los recibe todos, tal cual.
 *
 * Devuelve {promesa, abortar}. `abortar()` corta el cable del lado del browser; el
 * CANCEL REAL (el que borra el `.part`) es POST /cancelar — los dos se llaman juntos.
 */
export function descargar(modelo, onEvento) {
  const c = new AbortController();
  let mudoDesde = Date.now();
  const vigia = setInterval(() => {
    if (Date.now() - mudoDesde > SILENCIO_MAX) {
      clearInterval(vigia);
      try { c.abort(); } catch (e) { /* ya estaba abortado */ }
      onEvento({ tipo: "fin", estado: "roto", causa: "timeout",
                 detalle: "el cable enmudeció: corté la espera en vez de dejar el latido girando" });
    }
  }, 2000);

  const promesa = (async () => {
    let r;
    try {
      r = await fetch("/v1/modelos/descargar", {
        method: "POST", signal: c.signal,
        headers: auth({ "Content-Type": "application/json", Accept: "text/event-stream" }),
        body: JSON.stringify({
          hf_id: modelo.id, archivo: modelo.archivo, archivos: modelo.archivos,
          formato: modelo.formato, categoria: modelo.categoria,
          peso_gb: modelo.peso_gb, tier: modelo.tier,
        }),
      });
    } catch (e) {
      clearInterval(vigia);
      onEvento({ tipo: "fin", estado: "roto", causa: "sin_red", detalle: String(e && e.message || e) });
      return;
    }
    if (!r.ok || !r.body) {
      clearInterval(vigia);
      onEvento({ tipo: "fin", estado: "roto", causa: "error_upstream",
                 detalle: "el sidecar respondió HTTP " + r.status });
      return;
    }
    const lector = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      let trozo;
      try { trozo = await lector.read(); }
      catch (e) { break; }                       // abortado o cable cortado
      if (trozo.done) break;
      mudoDesde = Date.now();
      buf += dec.decode(trozo.value, { stream: true });
      const partes = buf.split("\n\n");
      buf = partes.pop();
      for (const p of partes) {
        const linea = p.split("\n").find((x) => x.startsWith("data: "));
        if (!linea) continue;
        try { onEvento(JSON.parse(linea.slice(6))); } catch (e) { /* trozo partido */ }
      }
    }
    clearInterval(vigia);
  })();

  return { promesa, abortar: () => { try { c.abort(); } catch (e) { /* ya cortado */ } } };
}

/** El slug con el que el backend nombra a un modelo de HF (espejo de `slug_de`). */
export function slugDe(hfId) {
  return String(hfId || "").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase().slice(0, 80);
}

/** Deep-link: Modelos.dc.html?cat=vision&modo=local · tolerante con las formas viejas. */
export function focoDeLaUrl(loc) {
  try {
    const qs = new URLSearchParams((loc || location).search);
    return {
      categoria: (qs.get("cat") || qs.get("categoria") || "").trim() || null,
      modo: (qs.get("modo") || qs.get("mode") || "").trim() || null,
      slug: (qs.get("m") || qs.get("modelo") || "").trim() || null,
      volver: qs.get("return") || qs.get("volver") || null,
    };
  } catch (e) { return { categoria: null, modo: null, slug: null, volver: null }; }
}

/** La URL del Centro de Modelos para que CUALQUIER superficie mande al lugar exacto. */
export function urlDelCentro(opts) {
  opts = opts || {};
  const q = [];
  if (opts.categoria) q.push("cat=" + encodeURIComponent(opts.categoria));
  if (opts.modo) q.push("modo=" + encodeURIComponent(opts.modo));
  if (opts.slug) q.push("m=" + encodeURIComponent(opts.slug));
  if (opts.volver) q.push("return=" + encodeURIComponent(opts.volver));
  return (opts.base || "") + "Modelos.dc.html" + (q.length ? "?" + q.join("&") : "");
}

export default {
  sesion, listar, listarV2, selector, preferencias, guardarPreferencias, sesionesCli,
  maquina, instalados, catalogo, gate, probar, borrar, cancelar, checklistEnVivo,
  cachearAvatar, descargar, slugDe, focoDeLaUrl, urlDelCentro,
};
