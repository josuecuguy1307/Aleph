/* cuarto.ayuda.js — EL [?] · el afordance ÚNICO de la LEY MINIMALISTA (§10).
 *
 * §10 dice: la UI del Cuarto dice SOLO lo operativo — nombre + estado + acción + máx UNA
 * línea. TODA explicación más larga vive en `docs/guia` (los MD que el Guía sirve) y en su
 * lugar, en la pantalla, queda un [?] que abre la ayuda. SIEMPRE el mismo patrón.
 *
 * Este módulo es ESE patrón, una sola vez:
 *   · `ayuda("cuarto", "nucleo")` → el HTML del botón, para incrustar donde estaba el párrafo.
 *   · `ayudaContenido("registro:id")` → el MISMO botón para evidencia estructurada.
 *   · `montarAyuda({...})`        → instala UN listener delegado + UN popover para toda la app.
 *
 * De dónde sale el texto: del MISMO MD que lee el Guía (`docs/guia/<tema>.<locale>.md`),
 * recortado por la sección cuyo slug `{#ancla}` coincide. No hay una segunda copia del texto
 * en el cliente: si el MD cambia, el [?] cambia. Fuente única, de verdad.
 *
 * Por qué NO es solo "abrir el chat del Guía": el Guía necesita un cerebro frontier y una
 * llamada de red. Una AYUDA que se cae cuando el cerebro no está listo no es ayuda: es el
 * texto perdido. Entonces el [?] RESUELVE solo (lee el MD, determinista, offline-capaz) y
 * ADEMÁS ofrece el Guía para lo que un MD no contesta — que es el mecanismo existente
 * (`abrirGuia` de cuarto.pixi.html, que abre el copiloto y le carga la pregunta).
 *
 * §4h · FALLO VISIBLE: si el MD no se puede leer, el popover lo DICE (con el path que falló)
 * y deja el camino al Guía abierto. Jamás un popover vacío ni un [?] que no hace nada.
 */

const DOCS_BASE_DEFAULT = "/docs/guia";

// ── el botón ──────────────────────────────────────────────────────────────────────────────
// Un solo look, un solo tamaño, un solo comportamiento. `tema` = archivo de docs/guia,
// `ancla` = el slug `{#...}` de la sección. `titulo` es el tooltip (opcional, corto).
export function ayuda(tema, ancla, titulo) {
  const t = String(tema || "").replace(/[^a-z0-9_-]/gi, "");
  const a = String(ancla || "").replace(/[^a-z0-9_-]/gi, "");
  const lbl = titulo ? String(titulo).replace(/"/g, "&quot;") : "";
  return `<button class="qmark" type="button" data-guia="${t}#${a}"${lbl ? ` title="${lbl}" aria-label="${lbl}"` : ' aria-label="Ayuda"'}>?</button>`;
}

// El mismo botón, como elemento (para código que arma DOM en vez de strings).
export function ayudaEl(tema, ancla, titulo) {
  const d = document.createElement("div");
  d.innerHTML = ayuda(tema, ancla, titulo);
  return d.firstElementChild;
}

// Evidencia estructurada que no vive en docs/guia (por ejemplo, el manifest crudo de una
// entrada del Registro). Conserva exactamente el mismo botón, popover y listener; lo único
// que cambia es el proveedor del cuerpo. `resolverContenido` de montarAyuda devuelve un nodo
// DOM, así el crudo nunca se interpreta como HTML.
export function ayudaContenido(ref, titulo) {
  const r = String(ref || "").replace(/[^a-z0-9_:/@.-]/gi, "");
  const lbl = titulo ? String(titulo).replace(/"/g, "&quot;") : "";
  return `<button class="qmark" type="button" data-ayuda-contenido="${r}"${lbl ? ` title="${lbl}" aria-label="${lbl}"` : ' aria-label="Ayuda"'}>?</button>`;
}

export function ayudaContenidoEl(ref, titulo) {
  const d = document.createElement("div");
  d.innerHTML = ayudaContenido(ref, titulo);
  return d.firstElementChild;
}

// ── el MD ─────────────────────────────────────────────────────────────────────────────────
const _cache = new Map();   // "tema.locale" → texto crudo del MD (o Error)

async function leerMD(base, tema, locale) {
  const key = `${tema}.${locale}`;
  if (_cache.has(key)) {
    const v = _cache.get(key);
    if (v instanceof Error) throw v;
    return v;
  }
  const url = `${base}/${tema}.${locale}.md`;
  let txt;
  try {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    txt = await r.text();
  } catch (e) {
    const err = new Error(`${url} — ${(e && e.message) || e}`);
    _cache.set(key, err);
    throw err;
  }
  _cache.set(key, txt);
  return txt;
}

/** Recorta la sección `## Título {#ancla}` hasta el próximo heading del mismo nivel o mayor.
 *  Sin `ancla` (o si no matchea) devuelve el preámbulo: el `# Título` y su primer bloque. */
export function seccion(md, ancla) {
  const lines = String(md || "").split("\n");
  const head = /^(#{1,6})\s+(.*?)\s*(?:\{#([a-z0-9_-]+)\})?\s*$/i;
  let start = -1, level = 0, titulo = "";
  if (ancla) {
    for (let i = 0; i < lines.length; i++) {
      const m = head.exec(lines[i]);
      if (m && m[3] && m[3].toLowerCase() === String(ancla).toLowerCase()) {
        start = i + 1; level = m[1].length; titulo = m[2]; break;
      }
    }
  }
  // ¿matcheó el ancla que pidió el [?]? Si NO, igual mostramos algo (el preámbulo del tema),
  // pero `encontrada:false` viaja hasta el popover para que lo DIGA (§4h: un [?] que apunta a
  // una sección que no existe es un bug de contenido y tiene que verse, no taparse con el intro).
  // (un [?] SIN ancla pide el tema entero a propósito: eso no es un fallo, es el preámbulo.)
  const encontrada = start >= 0 || !ancla;
  if (start < 0) {                       // sin ancla útil → el preámbulo del documento
    for (let i = 0; i < lines.length; i++) {
      const m = head.exec(lines[i]);
      if (m && m[1].length === 1) { start = i + 1; level = 1; titulo = m[2]; break; }
    }
    if (start < 0) return { titulo: "", cuerpo: String(md || "").trim(), encontrada: false };
  }
  const out = [];
  for (let i = start; i < lines.length; i++) {
    const m = head.exec(lines[i]);
    if (m && m[1].length <= level) break;
    out.push(lines[i]);
  }
  return { titulo, cuerpo: out.join("\n").trim(), encontrada };
}

// ── markdown mínimo → HTML (escapado primero; nada de este texto es confiable como markup) ─
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1");   // el link se aplana: la ayuda no navega afuera
}

export function mdHtml(src) {
  const lines = String(src || "").split("\n");
  const out = [];
  let li = false, para = [];
  const cierraP = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
  const cierraLi = () => { if (li) { out.push("</ul>"); li = false; } };
  for (const raw of lines) {
    const l = raw.trim();
    if (!l) { cierraP(); cierraLi(); continue; }
    const h = /^(#{1,6})\s+(.*?)\s*(?:\{#[a-z0-9_-]+\})?\s*$/i.exec(l);
    if (h) { cierraP(); cierraLi(); out.push(`<h5>${inline(h[2])}</h5>`); continue; }
    const b = /^[-*]\s+(.*)$/.exec(l);
    if (b) { cierraP(); if (!li) { out.push("<ul>"); li = true; } out.push(`<li>${inline(b[1])}</li>`); continue; }
    if (/^\|/.test(l) || /^```/.test(l)) { continue; }   // tablas/bloques: no entran al popover
    // los MD de docs/guia envuelven a ~80 columnas: la 2ª línea de un bullet viene INDENTADA y
    // es continuación, no un párrafo nuevo. Sin esto la ayuda se ve partida en dos bloques.
    if (li && /^\s{2,}\S/.test(raw)) { out[out.length - 1] = out[out.length - 1].replace(/<\/li>$/, " " + inline(l) + "</li>"); continue; }
    cierraLi(); para.push(l);
  }
  cierraP(); cierraLi();
  return out.join("");
}

// ── el CSS, adentro del componente ────────────────────────────────────────────────────────
// §10 pide UN patrón para toda la app; si la piel vive en el <style> de una pantalla, la
// segunda superficie que monte el [?] lo hereda roto. Va acá: importar el módulo alcanza.
const CSS = `
.qmark { width:18px; height:18px; min-width:18px; padding:0; margin:0 0 0 5px; flex:0 0 auto;
  border:0; border-radius:50%; background:transparent; color:var(--muted);
  font:inherit; font-size:11px; font-weight:400; line-height:16px; text-align:center;
  cursor:pointer; vertical-align:middle; position:relative; transition:color .12s, border-color .12s, background .12s; }
.qmark::after { content:""; position:absolute; inset:-4px; }
.qmark:hover, .qmark:focus-visible { color:var(--accent); background:var(--accent-soft); outline:none; }
.qmark[aria-expanded="true"] { color:var(--accent); background:var(--accent-soft); }

#ayudapop { position:fixed; width:290px; max-width:calc(100vw - 24px); padding:11px 13px; z-index:2147483000;
  border-radius:var(--r-lg, 12px); background:var(--paper, rgba(12,16,24,.94)); color:var(--ink, #e8ecf4);
  border:0; box-shadow:var(--sh-3); backdrop-filter:blur(8px); }
#ayudapop[hidden] { display:none; }
#ayudapop .ayHead { display:flex; align-items:center; gap:7px; }
#ayudapop .ayKind { width:16px; height:16px; min-width:16px; border-radius:50%; border:0; background:var(--accent-soft);
  color:var(--accent); font-size:10px; font-weight:400; line-height:16px; text-align:center; }
#ayudapop .ayTitle { font-size:12.5px; font-weight:400; color:var(--ink); flex:1 1 auto; }
#ayudapop .ayX { border:0; background:transparent; color:var(--muted); cursor:pointer; font-size:12px; line-height:1; padding:0 2px; }
#ayudapop .ayX:hover { color:var(--ink); }
/* CONTRASTE: el cuerpo es texto de LECTURA, no un subtítulo apagado — token de prosa, no un hex suelto. */
#ayudapop .ayBody { margin-top:6px; max-height:min(46vh, 340px); overflow:auto; font-size:11.5px; line-height:1.5; color:var(--ink); }
#ayudapop .ayBody p { margin:0 0 6px; }
#ayudapop .ayBody p:last-child { margin-bottom:0; }
#ayudapop .ayBody h5 { margin:8px 0 3px; font-size:11px; font-weight:400; letter-spacing:.04em; color:var(--muted); text-transform:none; }
#ayudapop .ayBody ul { margin:0 0 6px; padding-left:15px; }
#ayudapop .ayBody li { margin:0 0 3px; }
#ayudapop .ayBody code { font-size:10.5px; padding:0 3px; border-radius:var(--r-2xs, 3px); background:color-mix(in srgb, var(--ink) 9%, transparent); }
#ayudapop .ayBody b { color:var(--ink); font-weight:400; }
#ayudapop .ayBody .ayWait { color:var(--muted); }
#ayudapop .ayBody .ayFail { color:var(--amber); }
/* AA en CLARO: el ámbar del tema oscuro da 4.18:1 sobre blanco. El aviso de §4h tiene que
   LEERSE en los dos temas, o el fallo visible es visible sólo en uno. */
html[data-theme="light"] #ayudapop .ayBody .ayFail { color:var(--amber); }
#ayudapop[data-contenido] { width:min(520px, calc(100vw - 24px)); }
#ayudapop .ayData { display:grid; gap:7px; }
#ayudapop .ayDataMeta { display:grid; grid-template-columns:max-content minmax(0,1fr); gap:3px 9px;
  margin:0; font-size:11px; }
#ayudapop .ayDataMeta dt { color:var(--muted); }
#ayudapop .ayDataMeta dd { min-width:0; margin:0; color:var(--ink); overflow-wrap:anywhere; }
#ayudapop .ayData details { border:0; border-radius:var(--r-sm);
  background:color-mix(in srgb, var(--ink) 3%, transparent); }
#ayudapop .ayData details > summary { padding:6px 8px; color:var(--ink); cursor:pointer;
  font-size:11px; font-weight:400; list-style-position:inside; }
#ayudapop .ayData details details { margin:8px; }
#ayudapop .ayData pre { max-height:180px; overflow:auto; margin:0; padding:8px;
  white-space:pre-wrap; overflow-wrap:anywhere; font:10px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace;
  color:var(--ink); }
#ayudapop .ayData .ayTools { display:grid; gap:3px; margin:0; padding:8px; list-style:none; }
#ayudapop .ayData .ayTools code { display:block; overflow-wrap:anywhere; }
#ayudapop .ayData .ayGap { color:var(--muted); font-size:10.5px; }
#ayudapop .ayDataAction { display:flex; align-items:center; justify-content:space-between; gap:8px;
  padding-top:2px; }
#ayudapop .ayDataAction button { border:0; border-radius:var(--r-xs);
  background:var(--paper2); color:var(--ink); padding:5px 8px; cursor:pointer; font:inherit; font-size:10.5px; }
#ayudapop .ayDataAction button:hover:not(:disabled) { background:var(--accent-soft); color:var(--accent); }
#ayudapop .ayDataAction button:disabled { cursor:default; color:var(--muted); }
#ayudapop .ayFoot { margin-top:8px; }
#ayudapop .ayFoot[hidden] { display:none; }
#ayudapop .ayLink { border:0; background:transparent; color:var(--accent); cursor:pointer; font:inherit; font-size:11px; padding:1px 0; }
#ayudapop .ayLink:hover { text-decoration:underline; }
`;

export function inyectarCSS(doc = document) {
  if (doc.getElementById("ayuda-css")) return;
  const s = doc.createElement("style"); s.id = "ayuda-css"; s.textContent = CSS;
  (doc.head || doc.documentElement).appendChild(s);
}

// ── el popover ────────────────────────────────────────────────────────────────────────────
/**
 * montarAyuda({ getLang, onGuia, anchorTo, docsBase, root, resolverContenido })
 *   getLang()  → "es" | "en"        (qué MD leer)
 *   onGuia(q)  → abre el copiloto con la pregunta `q` — el MECANISMO EXISTENTE del Guía.
 *   resolverContenido(ref, { lang }) → { titulo, nodo } para evidencia estructurada.
 *   anchorTo(el, btn) → opcional: coloca el popover. Default: pegado al botón, en viewport.
 *   docsBase   → "/docs/guia" por default.
 *   root       → dónde escuchar los clicks (default: document).
 * Devuelve { abrir(tema, ancla, btn), cerrar(), abierto() } — hooks de verificación incluidos.
 */
export function montarAyuda({
  getLang = () => "es",
  onGuia = null,
  anchorTo = null,
  docsBase = DOCS_BASE_DEFAULT,
  root = document,
  resolverContenido = null,
} = {}) {
  inyectarCSS(document);
  let pop = document.getElementById("ayudapop");
  if (!pop) {
    pop = document.createElement("div");
    pop.id = "ayudapop";
    pop.className = "float glass";
    pop.hidden = true;
    pop.setAttribute("role", "dialog");
    pop.innerHTML = `
      <div class="ayHead"><span class="ayKind" id="ayKind">?</span><span class="ayTitle" id="ayTitle"></span>
        <button class="ayX" id="ayClose" type="button" title="Cerrar" aria-label="Cerrar">✕</button></div>
      <div class="ayBody" id="ayBody"></div>
      <div class="ayFoot" id="ayFoot"><button class="ayLink" id="ayAsk" type="button"></button></div>`;
    document.body.appendChild(pop);
  }
  // sin copiloto en esta superficie (p.ej. Cuarto.dc.html) no se ofrece un camino que no existe.
  const foot = document.getElementById("ayFoot");
  if (foot) foot.hidden = !onGuia;
  const $ = (id) => document.getElementById(id);
  let curBtn = null, curRef = "";
  let resolverDeContenido = resolverContenido;

  const L = (es, en) => (getLang() === "en" ? en : es);

  function cerrar() {
    pop.hidden = true;
    pop.removeAttribute("data-contenido");
    pop.removeAttribute("data-guia");
    curBtn = null;
    curRef = "";
  }

  function colocar(btn) {
    if (anchorTo) { try { anchorTo(pop, btn); return; } catch (e) {} }
    const r = btn.getBoundingClientRect();
    const w = pop.offsetWidth || 300, h = pop.offsetHeight || 200;
    const x = Math.max(10, Math.min(window.innerWidth - w - 10, r.left + r.width / 2 - w / 2));
    // abajo si entra; si no, arriba. Nunca fuera de la ventana.
    const y = (r.bottom + 8 + h <= window.innerHeight - 10) ? r.bottom + 8 : Math.max(10, r.top - h - 8);
    pop.style.position = "fixed";
    pop.style.left = Math.round(x) + "px";
    pop.style.top = Math.round(y) + "px";
    pop.style.right = "auto";
  }

  async function abrir(tema, ancla, btn) {
    curBtn = btn || null; curRef = `${tema}#${ancla}`;
    pop.removeAttribute("data-contenido");
    pop.dataset.guia = curRef;
    if (foot) foot.hidden = !onGuia;
    $("ayKind").textContent = "?";
    $("ayTitle").textContent = L("Ayuda", "Help");
    $("ayBody").innerHTML = `<p class="ayWait">${L("leyendo la guía…", "reading the guide…")}</p>`;
    $("ayAsk").textContent = L("Pregúntale al Guía →", "Ask the Guide →");
    pop.hidden = false;
    if (btn) colocar(btn);
    const locale = getLang() === "en" ? "en" : "es";
    let titulo = "", cuerpo = "", falla = null;
    try {
      const md = await leerMD(docsBase, tema, locale);
      const s = seccion(md, ancla);
      titulo = s.titulo; cuerpo = s.cuerpo;
      if (!s.encontrada) falla = L(`la guía no tiene la sección «${ancla}»`, `the guide has no «${ancla}» section`);
    } catch (e) {
      // §4h · el fallo se VE, con el path que falló. Y el Guía sigue a un clic.
      falla = L("no pude leer la guía", "couldn't read the guide") + `: ${(e && e.message) || e}`;
    }
    if (pop.hidden || pop.dataset.guia !== curRef) return;   // el usuario ya cerró/cambió
    $("ayTitle").textContent = titulo || L("Ayuda", "Help");
    $("ayBody").innerHTML = (cuerpo ? mdHtml(cuerpo) : "") +
      (falla ? `<p class="ayFail">⚠️ ${esc(falla)}</p>` : "");
    if (btn) colocar(btn);
  }

  async function abrirContenido(ref, btn) {
    curBtn = btn || null;
    curRef = `contenido:${String(ref || "")}`;
    pop.removeAttribute("data-guia");
    pop.dataset.contenido = String(ref || "");
    $("ayKind").textContent = "?";
    $("ayTitle").textContent = L("Detalle", "Details");
    $("ayBody").innerHTML = `<p class="ayWait">${L("leyendo el detalle…", "reading details…")}</p>`;
    if (foot) foot.hidden = true;
    pop.hidden = false;
    if (btn) colocar(btn);
    let titulo = "", nodo = null, falla = null;
    try {
      if (typeof resolverDeContenido !== "function") throw new Error(L(
        "esta superficie no registró el contenido",
        "this surface didn't register the content"
      ));
      const contenido = await resolverDeContenido(String(ref || ""), {
        lang: getLang() === "en" ? "en" : "es",
      });
      titulo = contenido && contenido.titulo || "";
      nodo = contenido && contenido.nodo;
      if (!(nodo instanceof Node)) throw new Error(L(
        "el detalle no devolvió un nodo",
        "the details didn't return a node"
      ));
    } catch (e) {
      falla = (e && e.message) || String(e);
    }
    if (pop.hidden || pop.dataset.contenido !== String(ref || "")) return;
    $("ayTitle").textContent = titulo || L("Detalle", "Details");
    if (nodo) $("ayBody").replaceChildren(nodo);
    else $("ayBody").innerHTML = `<p class="ayFail">⚠️ ${esc(falla || L("sin detalle", "no details"))}</p>`;
    if (btn) colocar(btn);
  }

  // UN listener delegado para TODOS los [?] de la app — presentes y futuros (la UI se re-pinta).
  root.addEventListener("click", (e) => {
    const b = e.target && e.target.closest && e.target.closest("[data-guia],[data-ayuda-contenido]");
    if (b) {
      e.preventDefault(); e.stopPropagation();
      if (curBtn === b && !pop.hidden) { cerrar(); return; }   // segundo toque = cerrar
      if (b.dataset.ayudaContenido) {
        abrirContenido(b.dataset.ayudaContenido, b);
      } else {
        if (foot) foot.hidden = !onGuia;
        const [tema, ancla] = String(b.dataset.guia || "").split("#");
        abrir(tema, ancla || "", b);
      }
      return;
    }
    if (!pop.hidden && !pop.contains(e.target)) cerrar();
  }, true);

  $("ayClose").onclick = cerrar;
  $("ayAsk").onclick = () => {
    const t = ($("ayTitle").textContent || "").trim();
    cerrar();
    if (onGuia) onGuia(L(`¿me explicas ${t}?`, `can you explain ${t}?`));
  };
  root.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) cerrar(); });

  const api = {
    abrir,
    abrirContenido,
    cerrar,
    abierto: () => !pop.hidden,
    ref: () => curRef,
    el: pop,
    registrarContenido: (resolver) => {
      if (typeof resolver === "function") resolverDeContenido = resolver;
      return api;
    },
  };
  try { window.__ayuda = api; } catch (e) {}
  return api;
}

export default {
  ayuda,
  ayudaEl,
  ayudaContenido,
  ayudaContenidoEl,
  montarAyuda,
  seccion,
  mdHtml,
};
