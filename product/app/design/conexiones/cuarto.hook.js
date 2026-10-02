/* cuarto.hook.js — EL PUENTE Cuarto → CENTRO DE CONEXIONES (Terminal B).
 *
 * Módulo ADITIVO y autocontenido: no toca `cuarto.pixi.html` (es de otra terminal). Se
 * engancha por fuera, a superficies que ese archivo ya expone como globals
 * (`window.__openInspector`, `window.__cuarto`, `window.__semHooks`) y a nodos estables
 * del DOM (`#palette`, `#equipBtn`, `#iprimary`). Si algo de eso no está, NO rompe nada:
 * cada enganche se salta solo.
 *
 * CONTRATO PARA LA TERMINAL C — una sola línea en cuarto.pixi.html:
 *     <script type="module" src="../conexiones/cuarto.hook.js"></script>
 * (o el import equivalente). Nada más. Todo lo de abajo se cablea solo.
 *
 * Qué arregla, de la caminata del humano:
 *   §G — el closet de MCPs (la paleta de Equipar) NO tenía salida visible: sólo cerraba
 *        re-apretando su propio botón. Ahora tiene ✕, se cierra con Escape y tocando
 *        afuera. El cierre reusa el toggle original (#equipBtn) para que la cámara del
 *        diorama vuelva a su lugar igual que siempre.
 *   §A — [Ver conexión] / [Configurar] dejan de abrir un flujo apilado dentro del closet
 *        chico: NAVEGAN al Centro, a la fila de ESA pieza (deep-link por slug), con
 *        ?volver= para regresar al Cuarto de un toque.
 *   §I — atajo para el Guía: window.AlephConexiones.abrir("context7") abre el Centro en
 *        esa fila. (El Guía es de otra terminal; acá vive sólo el gancho.)
 */
import Sem from "../cuarto/cuarto.semaforo.js";

const $ = (id) => document.getElementById(id);
const _lang = () => {
  try { return (window.AlephI18n && window.AlephI18n.lang && window.AlephI18n.lang()) || "es"; }
  catch (e) { return "es"; }
};
const L = (es, en) => (_lang() === "en" ? en : es);
const tr = (key) => window.AlephI18n.t(key);
const esConexion = () => $("ikind")?.getAttribute("data-i18n") === "workshop.item.connection";

function actualizarAccionInspector(prim) {
  if (esConexion()) {
    prim.setAttribute("data-i18n", "workshop.action.view_connection_external");
    prim.setAttribute("data-i18n-title", "workshop.action.connection_destination");
    prim.textContent = tr("workshop.action.view_connection_external");
    prim.title = tr("workshop.action.connection_destination");
  } else if (prim.getAttribute("data-i18n-title") === "workshop.action.connection_destination") {
    // openInspector restores the current action key/text; do not retain the old destination.
    prim.removeAttribute("data-i18n-title");
    prim.removeAttribute("title");
  }
}

// ── a dónde manda cada cosa ───────────────────────────────────────────────────────────
const SUB = () => (/\/(cuarto|sala|metodo)\//.test(location.pathname) ? "../" : "");

// El Centro murió: el destino sale de la ÚNICA tabla (cuarto.semaforo.js · destinoDeSlug).
import { destinoDeSlug } from "../cuarto/cuarto.semaforo.js";

export function urlCentro(slug, opts) {
  opts = opts || {};
  const d = destinoDeSlug(slug);
  const q = new URLSearchParams(d.q);
  q.set("return", opts.volver || (location.pathname + location.search));
  return SUB() + d.pantalla + "?" + q.toString();
}

/** Pieza del Cuarto → slug del Centro, usando el MISMO mapeo pieza→{tipo,ref} del semáforo
 *  (window.__semHooks.semCoordDe) para no inventar una segunda verdad. */
export function slugDePieza(d) {
  if (!d) return "";
  try {
    const H = window.__semHooks;
    if (H && H.semCoordDe) {
      const coord = H.semCoordDe(d);
      if (coord) {
        const ctx = Object.assign({}, coord.ctx, { backed_by: (coord.opts || {}).backed_by });
        const s = Sem.slugDeCentro({ tipo: coord.tipo, ref: coord.ref }, ctx);
        if (s) return s;
      }
    }
  } catch (e) { /* seguimos con el fallback honesto */ }
  return String(d.connector || d.server || d.ref || d.id || "");
}

export function irAlCentro(slug, opts) { location.href = urlCentro(slug, opts); }

// ── §G · SALIDA del closet de MCPs (la paleta de Equipar) ─────────────────────────────
function cerrarPaleta() {
  const p = $("palette"), b = $("equipBtn");
  if (!p || !p.classList.contains("open")) return false;
  // reusar el toggle original: así la cámara vuelve (setInsets) exactamente como siempre.
  if (b) b.click();
  else p.classList.remove("open");
  if (b) try { b.focus(); } catch (e) {}
  return true;
}

function montarSalidaPaleta() {
  const p = $("palette");
  if (!p || p.dataset.salidaCx === "1") return false;
  p.dataset.salidaCx = "1";

  // ✕ visible, dentro del encabezado del closet
  const head = p.querySelector(".phead") || p.firstElementChild || p;
  const x = document.createElement("button");
  x.type = "button";
  x.id = "palClose";
  x.className = "cx-pal-x";
  x.setAttribute("aria-label", L("Cerrar el closet", "Close the drawer"));
  x.title = L("Cerrar (Esc)", "Close (Esc)");
  x.textContent = "✕";
  x.onclick = (e) => { e.stopPropagation(); cerrarPaleta(); };
  head.appendChild(x);
  if (getComputedStyle(head).position === "static") head.style.position = "relative";

  // Escape (capture: llega antes que cualquier handler de la pantalla)
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    // si hay un overlay propio del Cuarto abierto, ése manda; sólo cerramos la paleta
    const byo = $("byoOverlay");
    if (byo && byo.classList.contains("open")) return;
    if (cerrarPaleta()) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  // click AFUERA (en el escenario) cierra. Se ignoran los clicks del propio closet y del
  // botón que la abre (si no, abriría y cerraría en el mismo gesto).
  document.addEventListener("pointerdown", (e) => {
    const pal = $("palette");
    if (!pal || !pal.classList.contains("open")) return;
    if (pal.contains(e.target)) return;
    const b = $("equipBtn");
    if (b && (b === e.target || b.contains(e.target))) return;
    cerrarPaleta();
  }, true);

  const css = document.createElement("style");
  css.id = "cx-pal-css";
  css.textContent = `
  .cx-pal-x{position:absolute;top:8px;right:8px;width:24px;height:24px;border-radius:var(--r-xs);
    border:0;background:var(--paper2);color:var(--muted);
    font-size:12px;line-height:1;cursor:pointer;padding:0;z-index:5}
  .cx-pal-x:hover{border-color:#8e8bf5;color:#fff;background:rgba(142,139,245,.22)}
  html[data-theme="light"] .cx-pal-x{background:rgba(255,255,255,.8);color:#4B3CA8;border-color:#D7D3EC}
  #palette .phead h3{padding-right:30px}`;
  if (!$("cx-pal-css")) document.head.appendChild(css);
  return true;
}

// ── §A · [Ver conexión]/[Configurar] del closet → la fila del Centro ─────────────────
let _ultimaPieza = null;

function montarPuenteInspector() {
  if (typeof window.__openInspector !== "function" || window.__openInspector.__cx) return false;
  const orig = window.__openInspector;
  const envuelto = function (d) { _ultimaPieza = d; return orig.apply(this, arguments); };
  envuelto.__cx = true;
  window.__openInspector = envuelto;

  const prim = $("iprimary");
  if (prim && prim.dataset.cx !== "1") {
    prim.dataset.cx = "1";
    // capture: corre ANTES del onclick original (que sólo expandía el nivel 2 del closet)
    prim.addEventListener("click", (e) => {
      const d = _ultimaPieza;
      if (!d) return;
      // sólo las CONEXIONES se van al Centro; núcleo/contexto/memoria se ajustan acá mismo
      if (!esConexion()) return;
      const slug = slugDePieza(d);
      if (!slug) return;
      e.preventDefault(); e.stopImmediatePropagation();
      irAlCentro(slug);
    }, true);
    // el botón deja de mentir: dice a dónde te lleva
    try {
      const obs = new MutationObserver(() => {
        actualizarAccionInspector(prim);
      });
      const ik = $("ikind"); if (ik) obs.observe(ik, { childList: true, characterData: true, subtree: true });
    } catch (e) { /* sin observer el botón sigue funcionando, sólo no se re-etiqueta */ }
  }
  return true;
}

// ── §A/§D · las acciones del semáforo que piden trabajo profundo van al Centro ───────
function montarPuenteSemaforo() {
  if (window.__cxSemPuente) return;
  window.__cxSemPuente = true;
  // capture en window: el evento se despacha sobre el badge (bubbles) → llegamos primero
  // que el oyente del Cuarto, que abría el flujo APILADO dentro del closet chico.
  window.addEventListener("cuarto:semaforo-accion", (ev) => {
    const det = ev.detail || {};
    if (["credencial", "configurar", "instalar"].indexOf(det.accion) < 0) return;
    const res = det.res || {};
    const ctx = det.ctx || {};
    const slug = Sem.slugDeCentro(res, ctx) ||
      (ctx.pieceId && window.__cuarto && window.__cuarto.pieceData
        ? slugDePieza(window.__cuarto.pieceData(ctx.pieceId)) : "");
    ev.preventDefault();
    ev.stopImmediatePropagation();
    irAlCentro(slug);
  }, true);
}

// ── §I · el atajo del Guía ────────────────────────────────────────────────────────────
export const AlephConexiones = {
  abrir(slug, opts) { irAlCentro(slug || "", opts); return { navegado: true, slug: slug || "" }; },
  url: urlCentro,
  slugDePieza,
  cerrarCloset: cerrarPaleta,
  // hooks de verificación (el verify los usa; ningún flujo de producto depende de esto)
  _montar: montarTodo,
};

function montarTodo() {
  const out = {
    paleta: montarSalidaPaleta(),
    inspector: montarPuenteInspector(),
  };
  montarPuenteSemaforo();
  return out;
}

// El Cuarto arma su UI dentro de un module que corre después del DOM: reintentamos un
// puñado de veces hasta que los nodos/globals existan, y paramos. Sin timers eternos.
function arrancar() {
  let intentos = 0;
  const tic = () => {
    const r = montarTodo();
    intentos++;
    if ((r.paleta && r.inspector) || intentos > 40) return;
    setTimeout(tic, 250);
  };
  tic();
}

if (typeof window !== "undefined") {
  window.AlephConexiones = AlephConexiones;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arrancar);
  else arrancar();
}

export default AlephConexiones;
