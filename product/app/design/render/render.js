/* ============================================================================
 * render.js — ALEPH · MÓDULO RENDER (owner: T3) · INTERFAZ CONGELADA
 *
 *   render(artifactType, payload) → DOMNode
 *
 * Una sola función pública. Toma el TIPO de artefacto + su payload y devuelve, de
 * forma SÍNCRONA, un nodo DOM listo para colgar en el canvas. Los renderers que
 * necesitan CDN (markdown/math, three.js) devuelven el nodo YA y lo hidratan
 * cuando las libs cargan — el contrato `→ DOMNode` se respeta siempre.
 *
 * artifactType — el nombre CANÓNICO del vocabulario único (platform/artifacts) o
 * cualquiera de sus alias; fuera de la unión → prosa. Lo que este módulo dibuja:
 *   informe    — prosa md/html + math + tablas GFM + citas clickeables + ```chart
 *   planilla   — grilla tabular (rows/cols o tabla markdown), barra de fórmula
 *   web        — preview real en iframe AISLADO (sandbox srcdoc, sin same-origin)
 *   documento  — memo/carta/documento (serif, márgenes), markdown ·  alias: doc
 *   cad        — malla 3D three.js desde STL/OBJ/glTF (FreeCAD), órbita+zoom
 *   schematic  — esquemático SVG (KiCad), sanitizado, con pan/zoom
 *   fieldplot  — campo escalar (OpenFOAM): heatmap real en canvas + colorbar
 *   dicom      — visor de imagen médica (read-only), window/level + metadatos
 *
 * PRINCIPIOS
 *   · Tier 0–1, motor invisible: nada de VM/stack pesado. Las libs 3D/SVG corren
 *     DENTRO de un iframe sandbox (origen opaco) o se dibujan con canvas/DOM API.
 *   · Render, no ejecución: el html/markdown del modelo se SANITIZA (DOMPurify);
 *     el código vivo (web/cad) sólo corre aislado, jamás toca la sesión/BYOK.
 *   · Self-contained: este archivo inyecta su propio CSS. T1/T2 sólo lo IMPORTAN.
 *   · Honesto: payload vacío/ilegible → estado vacío explícito, nunca un fake.
 *
 * USO
 *   ESM:     import { render } from "../render/render.js";
 *            canvas.appendChild(render("informe", artifact));
 *   global:  <script type="module" src=".../render.js"></script>
 *            window.AlephRender.render("cad", { content: stlText, format: "stl" });
 *   await:   AlephRender.ready(node).then(() => screenshot())   // hidratación lista
 *   ciclo:   AlephRender.unmount(canvas)   // apaga timers e iframes y vacía el host
 * ========================================================================== */

// ── EL VOCABULARIO ÚNICO · registro 1/2 [Gate 4 · Fase 2 · obra 2.3] ─────────
// Acá vivían 11 tipos y 17 alias escritos a mano — la lista nº1 del censo §C.3, que
// además tenía `doc` como canónico y `documento` como alias: exactamente al revés
// que el almacén, que persiste `documento`. Los dos murieron:
//   · la IDENTIDAD (qué tipos existen y qué alias resuelve a cuál) sale del
//     vocabulario, la misma fuente que gobierna el borde de escritura;
//   · lo que queda de ESTE módulo es lo que sí es suyo: qué sabe DIBUJAR, y a qué
//     dibujo DELEGA un tipo canónico para el que no tiene renderer propio.
import * as VOCAB from "./vocabulary.js";

// TYPES ya no se declara: son los renderers que este módulo implementa (abajo).
// Se calcula después de RENDERERS, al final del archivo.

// DELEGACIONES DE DIBUJO — decisión de este módulo, NO identidad. Un `dashboard`
// sigue siendo un dashboard para el almacén; acá se dibuja con el renderer de
// `informe` porque los ```chart son ciudadanos de primera ahí. Por eso viven
// separadas de los alias del vocabulario (que sí son identidad) — mezclarlas fue
// justo lo que hizo que `3d` y `cad` parecieran el mismo tipo.
const DELEGATES = {
  // [Gate 4 · Fase 6 · §6.a] EL VISOR PROPIO SALIÓ, Y LA DELEGACIÓN SE DECLARA.
  // Decisión del dueño: «no queremos un dibujo hecho por nosotros, queremos la cosa real
  // corriendo» — el camino es el webview local (ley 8), no una malla que nosotros pintamos.
  // Así que `cad`, `volume3d` y `schematic` dejan de tener renderer.
  //
  // Pero NO desaparecen del vocabulario, y ésa es la diferencia entre sacar un dibujo y
  // romper una identidad: el almacén sigue persistiendo esos tipos, `bridge.py` sigue
  // mapeando lo que Ciencia produce, y `cad_server.py` sigue escribiendo `model.cad.json`.
  // Lo que cambia es QUIÉN LO DIBUJA. Sin esta declaración caerían al fallback en silencio
  // — y la vara del vocabulario lo dijo en rojo apenas se sacaron los tres, que es
  // exactamente para lo que sirve.
  cad: "informe",
  volume3d: "informe",
  schematic: "informe",
  "3d": "informe",        // antes delegaba a `cad`, que ya no existe
  dashboard: "informe",   // los ```chart son ciudadanos de primera en `informe`
  codigo: "informe",      // markdown + highlight: el render declarado (sala.html:2146)
  // [Convergencia · superficie 7] Una presentación NO se dibuja en línea: el .pptx es un
  // binario que llega de un stack, y lo que la casa tiene de él es su texto o su ficha.
  // Se dibuja con `informe` —que es lo que ese contenido ES— y se BAJA como .pptx real
  // (artifact_export._gen_pptx). Delegar el dibujo no toca la identidad: para el almacén
  // y para la descarga sigue siendo `presentacion`. Va acá y no en NOT_COVERED porque
  // NOT_COVERED significa «lo dibuja la Sala con renderer propio», y la Sala tampoco
  // tiene uno: una ausencia declarada en el lugar equivocado sigue siendo una mentira.
  presentacion: "informe",
};

// Tipos canónicos que este módulo NO cubre, DECLARADOS: los dibuja la Sala
// (render/sala-render.js) con renderers propios. Declararlos es la diferencia entre una
// ausencia conocida y un tipo que cae mudo a prosa.
const NOT_COVERED = ["imagen", "galeria"];

// ── CDN (idéntico a sala/render.js para no divergir en el look del markdown) ──
// [Casa 2 · F1.c] VENDORIZADO — ver la nota larga en render/sala-render.js.
// Este módulo se carga con type="module", así que la base sale de import.meta.url.
const VBASE = new URL("../vendor/", import.meta.url).href;
const CDN = {
  marked: VBASE + "marked.min.js",
  dompurify: VBASE + "purify.min.js",
  katex: VBASE + "katex/katex.min.js",
  katexAuto: VBASE + "katex/auto-render.min.js",
  katexCss: VBASE + "katex/katex.min.css",
  // [§6.a] `threeIframe` SALIÓ con el visor. La constante quedaba apuntando a un vendor
  // que este módulo ya no carga: una promesa que nadie cumple. El ARCHIVO se queda —
  // `render/sala-render.js` y las dos varas de Capa 0 (`verify_capa0_{frozen,offline}.mjs`)
  // lo siguen necesitando para probar que el vendor viaja sin red.
};

function loadScript(src) {
  return new Promise(function (res, rej) {
    var s = document.createElement("script");
    s.src = src; s.async = true; s.onload = res; s.onerror = rej;
    document.head.appendChild(s);
  });
}
function loadCss(href) {
  if (document.querySelector('link[href="' + href + '"]')) return;
  var l = document.createElement("link");
  l.rel = "stylesheet"; l.href = href; document.head.appendChild(l);
}

var _deps = null;
function ensureDeps() {
  if (_deps) return _deps;
  loadCss(CDN.katexCss);
  _deps = Promise.all([
    window.marked ? Promise.resolve() : loadScript(CDN.marked),
    window.DOMPurify ? Promise.resolve() : loadScript(CDN.dompurify),
    window.katex ? Promise.resolve() : loadScript(CDN.katex),
  ]).then(function () {
    return window.renderMathInElement ? Promise.resolve() : loadScript(CDN.katexAuto);
  });
  return _deps;
}

/* ── helpers de texto ─────────────────────────────────────────────────────── */
function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function P(payload) {
  // payload puede venir como artefacto {type,content,...} o como string suelto.
  if (payload && typeof payload === "object") return payload;
  return { content: String(payload == null ? "" : payload) };
}
function body(a) { return String(a.content != null ? a.content : (a.markdown != null ? a.markdown : "")); }

// saca el cerco markdown (```html / ```svg / ```three …) si el contenido vino enfencado.
function stripFences(s, langs) {
  s = String(s == null ? "" : s).trim();
  var re = new RegExp("```(?:" + (langs || "html|js|javascript|three|threejs|svg|xml") + ")?\\s*([\\s\\S]*?)```", "i");
  var m = s.match(re);
  return m ? m[1].trim() : s;
}

// canal usuario: matar leaks de internals (rutas, plan crudo, citas de tool) antes de render.
function stripLeaks(md) {
  var s = String(md == null ? "" : md);
  s = s.replace(/<<<\s*TURN\s*:\s*(?:chat|obra)\s*>>>/gi, "");
  s = s.replace(/【[^】]*】/g, "");
  s = s.replace(/[†‡]\w+[:=]\w+/g, "");
  s = s.replace(/\/Users\/[^\s)"'`\]]+/g, "[ruta]");
  s = s.replace(/^[ \t]*(?:›|▶▶?|»|⟶|\$ |# trace|TRACE:).*$/gim, "");
  s = s.replace(/^\s*(?:Plan de acci[oó]n|Pensando|Razonamiento)\s*:.*$/gim, "");
  s = s.replace(/\n{3,}/g, "\n\n");
  return s.trim();
}

function mdToSafeHtml(md) {
  var raw = window.marked.parse(String(md == null ? "" : md), {
    gfm: true, breaks: false, headerIds: false, mangle: false,
  });
  return window.DOMPurify.sanitize(raw, {
    ADD_ATTR: ["target", "rel"],
    FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form"],
  });
}

function linkCitations(html, citations) {
  if (!citations || !citations.length) return html;
  var byId = {};
  citations.forEach(function (c) { byId[String(c.id)] = c; });
  var withRefs = html.replace(/\[(\d+)\]/g, function (m, n) {
    if (!byId[n]) return m;
    return '<a href="#ar-cite-' + n + '" class="ar-cite" title="' +
      escapeHtml(byId[n].label || byId[n].url || "") + '">[' + n + "]</a>";
  });
  var list = citations.map(function (c) {
    var label = escapeHtml(c.label || c.url || ("Fuente " + c.id));
    var link = c.url
      ? '<a href="' + escapeHtml(c.url) + '" target="_blank" rel="noopener noreferrer">' + label + "</a>"
      : label;
    return '<li id="ar-cite-' + escapeHtml(String(c.id)) + '">' + link + "</li>";
  }).join("");
  return withRefs +
    '<hr class="ar-cite-sep"><div class="ar-sources"><div class="ar-sources-h">Fuentes</div>' +
    '<ol class="ar-sources-list">' + list + "</ol></div>";
}

/* ══ EL `$` INLINE, CON GUARDIA — MIRROR: sala-render.js ⇄ render.js ═══════════════════
 *
 * [Educación · los artefactos · 2026-08-27 · decisión del dueño]
 *
 * EL PROBLEMA REAL, y por qué había DOS respuestas distintas para el mismo texto. Un
 * tutor de matemática escribe `$h$`, `$x^2$`, `$6+h$`; un informe financiero escribe
 * `US$ 63.762,69 / ETH: US$`. Con el `$` prendido a secas, KaTeX se come lo segundo
 * (todo lo que hay entre los dos `US$` se vuelve una fórmula en itálica); apagado, se
 * pierde lo primero. `render.js` lo tenía PRENDIDO y `sala-render.js` APAGADO: el mismo
 * párrafo se leía distinto según dónde cayera.
 *
 * LA GUARDIA, Y DE DÓNDE SALE. No es una intuición: son las dos reglas que separan los
 * **216 pares `$…$` reales** de `aleph.db` (barridos los 212 mensajes de agente):
 *
 *     Educación  213 pares — TODOS math   `\dfrac{f(x+h)-f(x)}{h}` · `x^2` · `6+h` · `0.01`
 *     Finanzas     3 pares — TODOS moneda `US$ 63.762,69 / ETH: US$`
 *
 *   1 · un `$` precedido por letra o dígito NO abre. Mata `US$`, `AR$`, `50$` sin
 *       necesitar una lista de monedas que habría que mantener.
 *   2 · un `$` seguido de espacio NO abre, y un `$` precedido de espacio NO cierra. Es
 *       la regla clásica de markdown-math, y es la que mata `$80.2B, net income $29.6B`
 *       y `costs $5 and $10`: el candidato a cierre viene pegado a un espacio.
 *
 * ⚠️ SE MIDIÓ ANTES DE ESCRIBIRLA, Y CORRIGIÓ EL ENUNCIADO. La regla pedida decía «un `$`
 * pegado a dígito no abre math». Contra el corpus real eso rompe **17 pares de Educación
 * que son math**: `$2x$`, `$6+h$`, `$6$`, `$0.01$`, `$4x - 5 = 0 \Rightarrow x = 1.25$`,
 * `$3^2 + 1^2 = 10$`… El objetivo declarado (que los 213 rendericen y los 3 no) manda
 * sobre la letra de la regla, y las dos de arriba lo cumplen exactamente.
 *
 * QUÉ HACE, Y QUÉ NO. NO agrega el `$` a los delimitadores de KaTeX: convierte el par que
 * PASA la guardia en `\(…\)`, que es el delimitador inline que KaTeX ya tenía prendido.
 * O sea que la decisión vive acá, en un solo lugar, y el motor sigue siendo el de siempre.
 * Lo que no pasa la guardia queda como texto, intacto.
 *
 * `$$…$$` no se toca: es de KaTeX y se copia verbatim.
 */
var _MATH_INLINE_TOPE = 400;   // un «par» más largo que esto no es una fórmula inline

function mathInlineDeDolar(texto) {
  var s = String(texto == null ? "" : texto);
  if (s.indexOf("$") < 0) return s;
  var alfa = function (c) { return !!c && /[A-Za-z0-9]/.test(c); };
  var blanco = function (c) { return !!c && /\s/.test(c); };
  var out = "", i = 0, n = s.length;
  while (i < n) {
    var c = s.charAt(i);
    if (c !== "$") { out += c; i++; continue; }
    if (s.charAt(i + 1) === "$") {              // display: es de KaTeX, verbatim
      var fin = s.indexOf("$$", i + 2);
      if (fin < 0) { out += s.slice(i); break; }
      out += s.slice(i, fin + 2); i = fin + 2; continue;
    }
    var sig = s.charAt(i + 1);
    if (alfa(s.charAt(i - 1)) || sig === "" || blanco(sig)) { out += c; i++; continue; }
    var j = -1;
    for (var k = i + 1; k < n && k - i - 1 <= _MATH_INLINE_TOPE; k++) {
      var d = s.charAt(k);
      if (d === "\n") break;                    // una fórmula inline no cruza renglón
      if (d !== "$") continue;
      if (s.charAt(k + 1) === "$") { k++; continue; }
      if (blanco(s.charAt(k - 1))) continue;    // «$5 and $6»: eso no cierra nada
      j = k; break;
    }
    if (j < 0) { out += c; i++; continue; }
    var dentro = s.slice(i + 1, j);
    // Un cuerpo que YA trae el delimitador de destino no se re-envuelve: sería anidar
    // `\(` dentro de `\(` y KaTeX cortaría en el lugar equivocado. Queda como texto.
    if (dentro.indexOf("\\(") >= 0 || dentro.indexOf("\\)") >= 0) { out += c; i++; continue; }
    out += "\\(" + dentro + "\\)";
    i = j + 1;
  }
  return out;
}

//: Los mismos tags que KaTeX ignora (`auto-render` los trae de fábrica). Tienen que ser
//: LOS MISMOS: si acá se escribiera `\(` adentro de un `<code>`, KaTeX no lo renderizaría
//: y el usuario vería el delimitador crudo — peor que el `$` que vino a arreglar.
var _MATH_TAGS_IGNORADOS = {
  SCRIPT: 1, NOSCRIPT: 1, STYLE: 1, TEXTAREA: 1, PRE: 1, CODE: 1, OPTION: 1,
};

function aplicarMathInline(el) {
  if (!el || !el.ownerDocument || !el.ownerDocument.createTreeWalker) return;
  var w = el.ownerDocument.createTreeWalker(el, 4 /* NodeFilter.SHOW_TEXT */, null, false);
  var pendientes = [], nodo;
  while ((nodo = w.nextNode())) {
    if (!nodo.nodeValue || nodo.nodeValue.indexOf("$") < 0) continue;
    var p = nodo.parentNode, saltar = false;
    while (p && p !== el.parentNode) {
      if (p.nodeName && _MATH_TAGS_IGNORADOS[p.nodeName]) { saltar = true; break; }
      if (p.classList && p.classList.contains("katex")) { saltar = true; break; }
      p = p.parentNode;
    }
    if (!saltar) pendientes.push(nodo);
  }
  // Se escribe DESPUÉS de recorrer: mutar mientras el walker camina es pedir problemas.
  for (var i = 0; i < pendientes.length; i++) {
    var antes = pendientes[i].nodeValue;
    var despues = mathInlineDeDolar(antes);
    if (despues !== antes) pendientes[i].nodeValue = despues;
  }
}
// ══ FIN DEL MIRROR DEL `$` INLINE ══

function runKatex(el) {
  if (!window.renderMathInElement) return;
  // LA GUARDIA PRIMERO — ver el bloque MIRROR de arriba.
  try { aplicarMathInline(el); } catch (e) { /* la guardia jamás rompe el render */ }
  try {
    window.renderMathInElement(el, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        // el `$` pelado SALIÓ de acá: se lo comía «US$ 63.762,69 / ETH: US$» entero.
        // Ahora lo decide `mathInlineDeDolar`, que convierte a `\(…\)` lo que pasa.
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
      ],
      throwOnError: false,
    });
  } catch (e) { /* math malformado no rompe el render */ }
}

/* ── gráfico real desde ```chart {spec} (SVG por DOM API, sin inyección) ───── */
var CHART_PAL = ["#6c8cff", "#43c59e", "#e0a13a", "#e06a6a", "#9b6cff", "#3aa7e0"];
function fmtNum(n) {
  n = Number(n); var a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (a >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (a >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(Math.round(n * 100) / 100);
}
/* MIRROR: mantener en sync con buildChartSVG() de render/sala-render.js (misma lógica; solo
 * difiere la clase raíz ar-chart vs sala-chart). Tipos: bar (default) · line · area
 * (línea + relleno) · scatter ({series:[{name,points:[[x,y]]}]}, eje X por VALOR) ·
 * candlestick ({labels, ohlc:[[o,h,l,c]]}, velas up/down). Spec que no cierra → null
 * (el fence queda visible como código — fallback honesto, jamás un gráfico inventado). */
var CANDLE_UP = "#43c59e", CANDLE_DOWN = "#e06a6a";
var CHART_TYPES = { bar: 1, line: 1, area: 1, scatter: 1, candlestick: 1, linechart: 1 };
function normalizeChartSpec(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  var type = String(raw.type || "").toLowerCase();
  if (type === "linechart") type = "line";
  if (type && !CHART_TYPES[type]) return null;
  if (type === "scatter" || type === "candlestick") {
    return Object.assign({}, raw, { type: type });
  }
  var cuerpo = (raw.data && typeof raw.data === "object" && !Array.isArray(raw.data))
    ? raw.data : raw;
  var labels = cuerpo.labels || cuerpo.x;
  if (!Array.isArray(labels) || !labels.length) return null;
  var crudas = null;
  if (Array.isArray(cuerpo.series) && cuerpo.series.length) crudas = cuerpo.series;
  else if (Array.isArray(cuerpo.datasets) && cuerpo.datasets.length) crudas = cuerpo.datasets;
  else if (Array.isArray(cuerpo.data) && cuerpo.data.length) crudas = cuerpo.data;
  if (!crudas) return null;
  var series;
  if (typeof crudas[0] !== "object" || crudas[0] === null) {
    for (var i = 0; i < crudas.length; i++) {
      if (crudas[i] != null && typeof crudas[i] !== "number") return null;
    }
    series = [{ name: String(raw.title || type || "serie"), data: crudas.slice() }];
  } else {
    series = [];
    for (var j = 0; j < crudas.length; j++) {
      var s = crudas[j];
      if (!s || typeof s !== "object") return null;
      var datos = Array.isArray(s.data) ? s.data : s.values;
      if (!Array.isArray(datos)) return null;
      series.push({ name: String(s.name || s.label || "serie"), data: datos });
    }
  }
  return { type: type || "bar", title: raw.title, labels: labels, series: series };
}
function buildChartSVG(spec) {
  var norm = normalizeChartSpec(spec);
  if (norm) spec = norm;
  var W = 620, H = 300, padL = 48, padR = 16, padT = spec && spec.title ? 34 : 14, padB = 44;
  var plotW = W - padL - padR, plotH = H - padT - padB;
  var type = (spec && spec.type) || "bar";
  var NS = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "ar-chart"); svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.setAttribute("width", "100%"); svg.setAttribute("role", "img");
  function add(tag, attrs, txt) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (txt != null) e.textContent = txt;
    svg.appendChild(e); return e;
  }
  function frameY(min, max) {
    for (var g = 0; g <= 2; g++) {
      var gy = padT + plotH * g / 2, val = max - (max - min) * g / 2;
      add("line", { x1: padL, y1: gy, x2: W - padR, y2: gy, stroke: "#2a2f3e", "stroke-width": 1 });
      add("text", { x: padL - 6, y: gy + 3, fill: "#8b95ac", "font-size": 10.5, "text-anchor": "end" }, fmtNum(val));
    }
  }
  function title(n) {
    svg.setAttribute("aria-label", ((spec && spec.title) || "gráfico") + " — " + n + " puntos");
    if (spec.title) add("text", { x: padL, y: 20, fill: "#e8ecf7", "font-size": 13, "font-weight": 600 }, spec.title);
  }

  /* ── velas: labels + ohlc[[open,high,low,close]] alineados 1:1 ── */
  if (type === "candlestick") {
    var clabels = ((spec && spec.labels) || []).map(String);
    var ohlc = ((spec && spec.ohlc) || []).map(function (r) { return (r || []).map(Number); });
    if (!clabels.length || clabels.length !== ohlc.length) return null;
    for (var ci = 0; ci < ohlc.length; ci++) {
      if (ohlc[ci].length < 4 || ohlc[ci].slice(0, 4).some(function (v) { return isNaN(v); })) return null;
    }
    var cmin = Infinity, cmax = -Infinity;
    ohlc.forEach(function (r) { if (r[2] < cmin) cmin = r[2]; if (r[1] > cmax) cmax = r[1]; });
    if (!(cmax > cmin)) cmax = cmin + 1;
    title(clabels.length); frameY(cmin, cmax);
    var slot = plotW / clabels.length, bw = Math.max(3, Math.min(14, slot * 0.55));
    var cx = function (i) { return padL + slot * (i + 0.5); };
    var cy = function (v) { return padT + plotH * (1 - (v - cmin) / (cmax - cmin)); };
    ohlc.forEach(function (r, i) {
      var o = r[0], h = r[1], l = r[2], c = r[3], up = c >= o;
      var col = up ? CANDLE_UP : CANDLE_DOWN;
      add("line", { x1: cx(i), y1: cy(h), x2: cx(i), y2: cy(l), stroke: col, "stroke-width": 1.2 });
      add("rect", { x: cx(i) - bw / 2, y: cy(Math.max(o, c)), width: bw,
        height: Math.max(1, Math.abs(cy(o) - cy(c))), rx: 1, fill: col, "data-candle": up ? "up" : "down" });
    });
    var step = Math.max(1, Math.ceil(clabels.length / 8));   // etiquetas raleadas
    clabels.forEach(function (lb, i) {
      if (i % step) return;
      add("text", { x: cx(i), y: H - padB + 18, fill: "#8b95ac", "font-size": 10.5, "text-anchor": "middle" },
        lb.length > 9 ? lb.slice(0, 8) + "…" : lb);
    });
    return svg;
  }

  /* ── dispersión: series[{name, points:[[x,y]]}], eje X por valor ── */
  if (type === "scatter") {
    var ssers = ((spec && spec.series) || []).filter(function (s) { return s && s.points && s.points.length; });
    if (!ssers.length) return null;
    var xs = [], ys = [];
    ssers.forEach(function (s) { s.points.forEach(function (p) {
      var x = Number(p && p[0]), y = Number(p && p[1]);
      if (!isNaN(x) && !isNaN(y)) { xs.push(x); ys.push(y); }
    }); });
    if (!xs.length) return null;
    var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs);
    var ymin = Math.min.apply(null, ys), ymax = Math.max.apply(null, ys);
    if (!(xmax > xmin)) xmax = xmin + 1;
    if (!(ymax > ymin)) ymax = ymin + 1;
    title(xs.length); frameY(ymin, ymax);
    var sx = function (v) { return padL + plotW * (v - xmin) / (xmax - xmin); };
    var sy = function (v) { return padT + plotH * (1 - (v - ymin) / (ymax - ymin)); };
    [xmin, (xmin + xmax) / 2, xmax].forEach(function (v) {
      add("text", { x: sx(v), y: H - padB + 18, fill: "#8b95ac", "font-size": 10.5, "text-anchor": "middle" }, fmtNum(v));
    });
    ssers.forEach(function (s, si) {
      var col = CHART_PAL[si % CHART_PAL.length];
      s.points.forEach(function (p) {
        var x = Number(p && p[0]), y = Number(p && p[1]);
        if (isNaN(x) || isNaN(y)) return;
        add("circle", { cx: sx(x), cy: sy(y), r: 3.5, fill: col, "fill-opacity": .85 });
      });
    });
    if (ssers.length > 1 || ssers[0].name) {
      ssers.forEach(function (s, si) {
        var lx = padL + si * 116, ly = H - 9;
        add("rect", { x: lx, y: ly - 8, width: 9, height: 9, rx: 2, fill: CHART_PAL[si % CHART_PAL.length] });
        add("text", { x: lx + 13, y: ly, fill: "#8b95ac", "font-size": 11 }, s.name || ("Serie " + (si + 1)));
      });
    }
    return svg;
  }

  /* ── línea / área / barras (histórico; area = línea + relleno) ── */
  var labels = ((spec && spec.labels) || []).map(String);
  var series = ((spec && spec.series) || []).filter(function (s) { return s && s.data && s.data.length; });
  if (!labels.length || !series.length) return null;
  var all = [];
  series.forEach(function (s) { s.data.forEach(function (v) { var n = Number(v); if (!isNaN(n)) all.push(n); }); });
  if (!all.length) return null;
  var max = Math.max.apply(null, all), min = Math.min.apply(null, all.concat([0]));
  if (max === min) max = min + 1;
  function xc(i) { return padL + plotW * (i + 0.5) / labels.length; }
  function yc(v) { return padT + plotH * (1 - (v - min) / (max - min)); }
  title(labels.length); frameY(min, max);
  if (type === "line" || type === "area") {
    series.forEach(function (s, si) {
      var col = CHART_PAL[si % CHART_PAL.length];
      var d = s.data.map(function (v, i) { return (i ? "L" : "M") + xc(i) + " " + yc(Number(v)); }).join(" ");
      if (type === "area") {
        var base = yc(Math.max(min, 0));
        add("path", { d: d + " L" + xc(s.data.length - 1) + " " + base + " L" + xc(0) + " " + base + " Z",
          fill: col, "fill-opacity": .15, stroke: "none" });
      }
      add("path", { d: d, fill: "none", stroke: col, "stroke-width": 2.5, "stroke-linejoin": "round" });
      s.data.forEach(function (v, i) { add("circle", { cx: xc(i), cy: yc(Number(v)), r: 3, fill: col }); });
    });
  } else {
    var ns = series.length, slot2 = plotW / labels.length, bw2 = Math.max(4, slot2 * 0.7 / ns);
    labels.forEach(function (lb, i) {
      series.forEach(function (s, si) {
        var v = Number(s.data[i]); if (isNaN(v)) return;
        var bx = padL + slot2 * i + slot2 * 0.15 + si * bw2;
        var by = yc(Math.max(v, 0)), bh = Math.abs(yc(v) - yc(0));
        add("rect", { x: bx, y: by, width: bw2, height: Math.max(1, bh), rx: 2, fill: CHART_PAL[si % CHART_PAL.length] });
      });
    });
  }
  labels.forEach(function (lb, i) {
    add("text", { x: xc(i), y: H - padB + 18, fill: "#8b95ac", "font-size": 10.5, "text-anchor": "middle" },
      lb.length > 9 ? lb.slice(0, 8) + "…" : lb);
  });
  if (series.length > 1 || series[0].name) {
    series.forEach(function (s, si) {
      var lx = padL + si * 116, ly = H - 9;
      add("rect", { x: lx, y: ly - 8, width: 9, height: 9, rx: 2, fill: CHART_PAL[si % CHART_PAL.length] });
      add("text", { x: lx + 13, y: ly, fill: "#8b95ac", "font-size": 11 }, s.name || ("Serie " + (si + 1)));
    });
  }
  return svg;
}
function renderCharts(el) {
  if (!el || !el.querySelectorAll) return;
  var blocks = el.querySelectorAll("pre > code");
  Array.prototype.forEach.call(blocks, function (code) {
    var raw = String(code.textContent || "").trim();
    if (!raw || raw.charAt(0) !== "{") return;
    var parsed; try { parsed = JSON.parse(raw); } catch (e) { return; }
    var spec = normalizeChartSpec(parsed);
    if (!spec) return;
    var svg = null; try { svg = buildChartSVG(spec); } catch (e) { svg = null; }
    if (!svg) return;
    var pre = code.closest("pre") || code;
    var fig = document.createElement("figure"); fig.className = "ar-chart-fig";
    fig.appendChild(svg);
    if (pre.parentNode) pre.parentNode.replaceChild(fig, pre);
  });
}

function skeleton(label) {
  return '<div class="ar-skel"><div class="ar-skel-dot"></div><div class="ar-skel-dot"></div>' +
    '<div class="ar-skel-dot"></div><span class="ar-skel-t">' + escapeHtml(label || tr("render.renderizando")) + "</span></div>";
}
function empty(msg) { return '<div class="ar-empty">' + escapeHtml(msg) + "</div>"; }
// [i18n-bi] resuelve claves de captura via window.t (i18n.js, cargado antes); fallback = la clave.
function tr(k, v) { return (typeof window !== "undefined" && window.t) ? window.t(k, v) : k; }

/* ── colormap viridis (anclas interpoladas) para fieldplot ────────────────── */
var VIRIDIS = [
  [68, 1, 84], [72, 40, 120], [62, 73, 137], [49, 104, 142], [38, 130, 142],
  [31, 158, 137], [53, 183, 121], [110, 206, 88], [181, 222, 43], [253, 231, 37],
];
function viridis(t) {
  t = Math.max(0, Math.min(1, t));
  var x = t * (VIRIDIS.length - 1), i = Math.floor(x), f = x - i;
  var a = VIRIDIS[i], b = VIRIDIS[Math.min(i + 1, VIRIDIS.length - 1)];
  return [Math.round(a[0] + (b[0] - a[0]) * f),
          Math.round(a[1] + (b[1] - a[1]) * f),
          Math.round(a[2] + (b[2] - a[2]) * f)];
}

/* ── base64 helper para empotrar geometría/datos en el srcdoc del iframe ───── */
function b64(str) {
  try { return btoa(unescape(encodeURIComponent(String(str)))); }
  catch (e) { return btoa(String(str)); }
}

/* ============================================================================
 * RENDERERS — cada uno recibe (node, a). Puede devolver una Promise si hidrata
 * de forma asíncrona; render() la cuelga en node.__arReady.
 * ========================================================================== */
// escala VERDE→ROJO anclada a un UMBRAL (límite del material). val<limit → verde,
// val≈limit → amarillo, val>limit → rojo. Así el MISMO campo lee verde cuando pasa y
// rojo cuando falla. Reusada por fieldplot (a.limit) y por la capa de convergencia.
function limitColor(val, limit) {
  if (!(limit > 0)) return viridis(0.5);
  var r = val / limit;
  function mix(a, b, t) { t = t < 0 ? 0 : t > 1 ? 1 : t; return [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t), Math.round(a[2] + (b[2] - a[2]) * t)]; }
  var GREEN = [34, 160, 84], LIME = [150, 190, 55], YEL = [235, 200, 45], RED = [214, 48, 49], DEEP = [120, 18, 22];
  if (r <= 0.7) return mix(GREEN, LIME, r / 0.7);
  if (r <= 1.0) return mix(LIME, YEL, (r - 0.7) / 0.3);
  if (r <= 1.25) return mix(YEL, RED, (r - 1.0) / 0.25);
  return mix(RED, DEEP, Math.min(1, (r - 1.25) / 0.5));
}

var RENDERERS = {

  /* prosa + math + tablas + citas + ```chart real */
  informe: function (node, a) {
    node.classList.add("ar-prose");
    node.innerHTML = skeleton();
    return ensureDeps().then(function () {
      node.innerHTML = linkCitations(mdToSafeHtml(stripLeaks(body(a))), a.citations);
      renderCharts(node);
      runKatex(node);
      if (!node.textContent.trim() && !node.querySelector(".ar-chart-fig, img, table")) {
        node.innerHTML = empty(tr("render.informe.empty"));
      }
    });
  },

  /* grilla tabular + barra de fórmula. rows/cols → grilla editable; o tabla markdown. */
  planilla: function (node, a) {
    var bar = '<div class="ar-fxbar"><span class="ar-fx">fx</span>' +
      '<input class="ar-formula" placeholder="—" aria-label="barra de fórmula" readonly></div>';
    if (a.rows && a.rows.length) {
      var head = (a.cols || []).map(function (c) { return "<th>" + escapeHtml(c) + "</th>"; }).join("");
      var rows = a.rows.map(function (r) {
        return "<tr>" + r.map(function (cell) {
          var n = typeof cell === "number" || (cell !== "" && !isNaN(Number(cell)));
          return '<td class="' + (n ? "ar-num" : "") + '">' + escapeHtml(cell) + "</td>";
        }).join("") + "</tr>";
      }).join("");
      node.innerHTML = bar + '<div class="ar-grid-wrap"><table class="ar-grid">' +
        (head ? "<thead><tr>" + head + "</tr></thead>" : "") + "<tbody>" + rows + "</tbody></table></div>";
      attachGridSort(node.querySelector("table"), a);
      return;
    }
    // sólo content (tabla markdown) → necesita marked
    node.innerHTML = skeleton();
    return ensureDeps().then(function () {
      var html = mdToSafeHtml(body(a));
      node.innerHTML = bar + '<div class="ar-grid-wrap">' + (html || empty(tr("render.planilla.empty"))) + "</div>";
      var t = node.querySelector("table"); if (t) { t.classList.add("ar-grid"); attachGridSort(t, a); }
    });
  },

  /* preview real en iframe AISLADO (corre el html pero no toca tu sesión). */
  web: function (node, a) {
    var html = stripFences(body(a), "html|xml");
    if (!html.trim()) { node.innerHTML = empty(tr("render.web.empty")); return; }
    var f = document.createElement("iframe");
    f.className = "ar-frame";
    f.setAttribute("sandbox", "allow-scripts allow-forms allow-popups");
    f.setAttribute("title", tr("render.preview_web"));
    f.srcdoc = html;
    node.appendChild(f);
  },

  /* memo / carta / documento (serif, márgenes). markdown sanitizado.
   * [2.3] La clave es `documento` —el nombre CANÓNICO del vocabulario, el que el
   * almacén persiste—; `doc` sigue entrando por el alias, como siempre. */
  documento: function (node, a) {
    node.innerHTML = '<div class="ar-doc-page">' + skeleton() + "</div>";
    return ensureDeps().then(function () {
      var page = node.querySelector(".ar-doc-page");
      page.innerHTML = mdToSafeHtml(stripLeaks(body(a))) || empty(tr("render.doc.empty"));
      renderCharts(page);
      runKatex(page);
    });
  },




  /* campo escalar (OpenFOAM): heatmap real en canvas + colorbar. Sin CDN. */
  /* serie temporal DEDICADA (linechart): {labels, series[{name,data}], title?, source?} del
     productor real (worldbank → *.linechart.json). Reusa buildChartSVG (el line-path de los
     ```chart) como ciudadano de primera: obra propia, no un bloque dentro de un informe. */
  linechart: function (node, a) {
    var o = (a && a.labels && a.series) ? a : null;
    if (!o) { try { var p = JSON.parse(body(a)); if (p && p.labels && p.series) o = p; } catch (e) {} }
    var labels = (o && o.labels) || [], series = (o && o.series) || [];
    if (!labels.length || !series.length) { node.innerHTML = empty(tr("render.linechart.empty")); return; }
    var svg = null;
    try { svg = buildChartSVG({ type: "line", title: o.title || a.title || "", labels: labels, series: series }); } catch (e) { svg = null; }
    if (!svg) { node.innerHTML = empty(tr("render.linechart.empty")); return; }
    node.innerHTML = "";
    var fig = document.createElement("figure"); fig.className = "ar-chart-fig ar-linechart";
    fig.appendChild(svg);
    if (o.source) { var cap = document.createElement("figcaption"); cap.className = "ar-linechart-src"; cap.textContent = String(o.source); fig.appendChild(cap); }
    node.appendChild(fig);
  },

  fieldplot: function (node, a) {
    // imagen ya rasterizada (p.ej. paraFoam screenshot) → mostrarla.
    var img = a.image || a.url || (/^(https?:|data:)/i.test(body(a)) ? body(a) : "");
    if (img && !a.grid) {
      node.innerHTML = '<figure class="ar-field"><img class="ar-field-img" alt="' +
        escapeHtml(a.title || "campo") + '" src="' + escapeHtml(img) + '">' +
        (a.title ? '<figcaption>' + escapeHtml(a.title) + "</figcaption>" : "") + "</figure>";
      return;
    }
    var grid = a.grid || a.field;
    if (!grid || !grid.values || !grid.values.length) { node.innerHTML = empty(tr("render.fieldplot.empty")); return; }
    drawFieldplot(node, grid, a);
  },

  /* visor de imagen médica (read-only). image+meta, o pixeles con window/level. */
  dicom: function (node, a) {
    var pix = a.pixels || a.pixel || null;
    if (pix && pix.data && pix.width && pix.height) { drawDicomPixels(node, pix, a); return; }
    var img = a.image || a.url || (/^(https?:|data:)/i.test(body(a)) ? body(a) : "");
    if (!img) { node.innerHTML = empty(tr("render.dicom.empty")); return; }
    var m = a.meta || a.metadata || {};
    node.innerHTML =
      '<div class="ar-dicom">' +
      '  <div class="ar-dicom-vp"><img class="ar-dicom-img" alt="' + escapeHtml(m.SeriesDescription || "DICOM") + '" src="' + escapeHtml(img) + '">' +
      '    <div class="ar-dicom-ovl ar-tl">' + dicomLine(m.PatientName || m.patient) + dicomLine(m.PatientID || m.patientId) + "</div>" +
      '    <div class="ar-dicom-ovl ar-tr">' + dicomLine(m.Modality || m.modality) + dicomLine(m.StudyDate || m.studyDate) + "</div>" +
      '    <div class="ar-dicom-ovl ar-bl">' + dicomLine(m.SeriesDescription || m.series) + dicomLine(m.SliceThickness ? ("Slice " + m.SliceThickness + "mm") : "") + "</div>" +
      '    <div class="ar-dicom-ovl ar-br">' + dicomLine(m.InstitutionName || m.institution) + '<span class="ar-dicom-ro">READ-ONLY</span></div>' +
      "  </div></div>";
  },

  /* convergencia: hace VISIBLE el loop. Una PROGRESIÓN de iteraciones (no entradas sueltas):
   * contador it.N + métrica clave cambiando con su delta + veredicto FALLA(rojo)→PASA(verde) +
   * stepping/auto-play. REUSA fieldplot para el campo (coloreado por `limit`). GENÉRICO: cualquier
   * nicho cuyo loop emita {value, grid} por iteración (FEM von Mises, CFD, electrónica…) lo usa. */
  convergence: function (node, a) {
    var iters = (a.iterations || a.steps || []).filter(function (x) { return x && (x.grid || x.value != null); });
    if (!iters.length) { node.innerHTML = empty(tr("render.convergence.sin_iteraciones")); return; }
    var metric = a.metric || {};
    var limit = (a.limit != null) ? Number(a.limit) : (metric.limit != null ? Number(metric.limit) : null);
    var unit = metric.unit || (iters[0].grid && iters[0].grid.unit) || a.unit || "";
    var mname = metric.name || a.metric_name || "métrica";
    var goalMin = (metric.goal !== "max");   // por defecto: menor es mejor (la convergencia baja)

    var wrap = document.createElement("div"); wrap.className = "ar-conv";
    wrap.innerHTML =
      '<div class="ar-conv-head">' +
      '  <div class="ar-conv-it"><span class="ar-conv-itn">it. 1</span><span class="ar-conv-ittot"> / ' + iters.length + '</span></div>' +
      '  <div class="ar-conv-metric"><span class="ar-conv-mlabel"></span><span class="ar-conv-val">–</span><span class="ar-conv-delta"></span></div>' +
      '  <div class="ar-conv-verdict"></div>' +
      '</div>' +
      '<div class="ar-conv-stage"></div>' +
      (limit != null ? '<div class="ar-conv-limit"></div>' : '') +
      '<div class="ar-conv-ctrl">' +
      '  <button class="ar-conv-btn ar-conv-prev" title="anterior">‹</button>' +
      '  <button class="ar-conv-btn ar-conv-play" title="reproducir/pausar">⏸</button>' +
      '  <button class="ar-conv-btn ar-conv-next" title="siguiente">›</button>' +
      '  <div class="ar-conv-track"></div>' +
      '</div>';
    node.appendChild(wrap);
    wrap.querySelector(".ar-conv-mlabel").textContent = tr(mname);
    if (limit != null) wrap.querySelector(".ar-conv-limit").textContent = tr("render.convergence.limit") + fmtNum(limit) + (unit ? (" " + unit) : "");
    var itnEl = wrap.querySelector(".ar-conv-itn"), valEl = wrap.querySelector(".ar-conv-val"),
        deltaEl = wrap.querySelector(".ar-conv-delta"), verdictEl = wrap.querySelector(".ar-conv-verdict"),
        stage = wrap.querySelector(".ar-conv-stage"), track = wrap.querySelector(".ar-conv-track"),
        prevB = wrap.querySelector(".ar-conv-prev"), nextB = wrap.querySelector(".ar-conv-next"),
        playB = wrap.querySelector(".ar-conv-play");
    iters.forEach(function () { track.appendChild(document.createElement("span")).className = "ar-conv-dot"; });
    var dots = track.querySelectorAll(".ar-conv-dot");

    var i = -1, timer = null;
    // PASA/FALLA según la DIRECCIÓN del objetivo: min (FEM/Bode: v ≤ límite) o max (quant
    // Sharpe: v ≥ límite). Aditivo — goalMin por defecto, así los loops min-goal no cambian.
    function passes(v) { return (limit == null) ? null : (goalMin ? (v <= limit) : (v >= limit)); }
    function show(k) {
      k = Math.max(0, Math.min(iters.length - 1, k)); if (k === i) return; i = k;
      var it = iters[i];
      itnEl.textContent = "it. " + (it.n != null ? it.n : (i + 1));
      valEl.textContent = (it.value != null ? fmtNum(it.value) : "–") + (unit ? (" " + unit) : "");
      if (i > 0 && iters[i - 1].value != null && it.value != null) {
        var d = it.value - iters[i - 1].value, good = goalMin ? (d < 0) : (d > 0);
        deltaEl.textContent = (d > 0 ? "▲ +" : (d < 0 ? "▼ " : "")) + fmtNum(d) + (unit ? (" " + unit) : "");
        deltaEl.className = "ar-conv-delta " + (d === 0 ? "" : (good ? "good" : "bad"));
      } else { deltaEl.textContent = ""; deltaEl.className = "ar-conv-delta"; }
      var p = passes(it.value);
      verdictEl.textContent = (p == null) ? "" : (p ? tr("render.convergence.verdict_pass") : tr("render.convergence.verdict_fail"));
      verdictEl.className = "ar-conv-verdict " + (p == null ? "" : (p ? "pass" : "fail"));
      wrap.setAttribute("data-verdict", p == null ? "none" : (p ? "pass" : "fail"));
      stage.innerHTML = "";
      // ESTAGE por iteración: una curva (quant: equity, redibujándose) o un heatmap (FEM/CFD).
      // Aditivo — si la iteración trae `curve` dibujamos la línea; si no, el fieldplot de siempre.
      if (it.curve && it.curve.length) { drawConvCurve(stage, it.curve, { passed: p }); }
      else { stage.appendChild(render("fieldplot", { grid: it.grid, limit: limit, title: "", unit: unit })); }
      for (var k2 = 0; k2 < dots.length; k2++) dots[k2].className = "ar-conv-dot" + (k2 === i ? " on" : (k2 < i ? " past" : ""));
      prevB.disabled = (i === 0); nextB.disabled = (i === iters.length - 1);
    }
    function stop() { if (timer) { clearInterval(timer); timer = null; } playB.textContent = "▶"; wrap.removeAttribute("data-playing"); }
    function tick() { if (!document.body.contains(node)) { stop(); return; } if (i < iters.length - 1) show(i + 1); else stop(); }
    function play() { if (timer || iters.length < 2) return; playB.textContent = "⏸"; wrap.setAttribute("data-playing", "1"); timer = setInterval(tick, 1400); }
    prevB.addEventListener("click", function () { stop(); show(i - 1); });
    nextB.addEventListener("click", function () { stop(); show(i + 1); });
    playB.addEventListener("click", function () { if (timer) stop(); else { if (i === iters.length - 1) show(0); play(); } });
    show(0);
    node._convShow = show; node._convCount = iters.length;   // hook determinístico para tests
    // [2.4] EL timer que se iba de fiesta: `tick` se auto-frenaba sólo si el nodo
    // había llegado a estar en `document.body`. Desmontar lo apaga siempre.
    onTeardown(node, stop);
    if (a.autoplay !== false && iters.length > 1) play();
  },
};

/* ── LOS TIPOS QUE ESTE MÓDULO DIBUJA (derivados, no declarados) ──────────────
 * Antes era una lista a mano que podía decir un tipo que no existía como renderer
 * (o callarse uno que sí). Ahora son las llaves de RENDERERS: imposible mentir. */
const TYPES = Object.keys(RENDERERS);

/* Cobertura contra EL vocabulario — la lee la vara de 2.3 (y cualquiera que quiera
 * saber qué pasa con un tipo). `uncovered` DEBE quedar vacío: todo canónico o tiene
 * renderer acá, o delega declarado, o está declarado como cubierto por la Sala. */
function coverage() {
  var canon = VOCAB.CANONICAL;
  var renderers = TYPES.slice();
  var uncovered = canon.filter(function (t) {
    return !RENDERERS[t] && !DELEGATES[t] && NOT_COVERED.indexOf(t) === -1;
  });
  var outside = renderers.filter(function (t) { return canon.indexOf(t) === -1; });
  return {
    canonical: canon.slice(), renderers: renderers,
    delegates: Object.assign({}, DELEGATES), notCovered: NOT_COVERED.slice(),
    uncovered: uncovered,        // canónicos sin dibujo ni delegación declarada
    outside: outside,            // renderers que no son de la unión (drift al revés)
  };
}

function dicomLine(v) { return v ? '<span>' + escapeHtml(v) + "</span>" : ""; }

/* ── fieldplot: heatmap en canvas con colorbar (viridis) ──────────────────── */
function drawFieldplot(node, grid, a) {
  var nx = grid.nx | 0, ny = grid.ny | 0, vals = grid.values;
  if (!nx || !ny) { nx = Math.round(Math.sqrt(vals.length)); ny = Math.ceil(vals.length / nx); }
  var min = grid.min, max = grid.max;
  if (min == null || max == null) {
    min = Infinity; max = -Infinity;
    for (var i = 0; i < vals.length; i++) { var v = Number(vals[i]); if (v < min) min = v; if (v > max) max = v; }
  }
  if (!(max > min)) max = min + 1;
  // UMBRAL opcional (límite del material): si viene, el campo se colorea relativo a él
  // (verde bajo el límite, rojo encima) en vez de viridis. Aditivo: sin limit → viridis.
  var limit = (a && a.limit != null) ? Number(a.limit) : (grid.limit != null ? Number(grid.limit) : null);
  if (limit != null && !(limit > 0)) limit = null;
  var SCALE = Math.max(1, Math.min(12, Math.floor(420 / Math.max(nx, ny))));
  var pad = 28, cbW = 16, cbGap = 46;
  var plotW = nx * SCALE, plotH = ny * SCALE;
  var W = plotW + pad * 2 + cbGap, H = plotH + pad * 2;
  var c = document.createElement("canvas");
  c.className = "ar-field-canvas"; c.width = W; c.height = H;
  c.style.maxWidth = "100%"; c.style.height = "auto";
  var g = c.getContext("2d");
  g.fillStyle = "#0b0e16"; g.fillRect(0, 0, W, H);
  // celdas
  var off = document.createElement("canvas"); off.width = nx; off.height = ny;
  var octx = off.getContext("2d"), img = octx.createImageData(nx, ny);
  for (var y = 0; y < ny; y++) for (var x = 0; x < nx; x++) {
    var idx = y * nx + x, val = Number(vals[idx]);
    var col = isNaN(val) ? [20, 24, 34] : (limit != null ? limitColor(val, limit) : viridis((val - min) / (max - min)));
    var p = idx * 4; img.data[p] = col[0]; img.data[p + 1] = col[1]; img.data[p + 2] = col[2]; img.data[p + 3] = 255;
  }
  octx.putImageData(img, 0, 0);
  g.imageSmoothingEnabled = (grid.interpolate !== false);
  g.drawImage(off, 0, 0, nx, ny, pad, pad, plotW, plotH);
  g.strokeStyle = "#2a3142"; g.lineWidth = 1; g.strokeRect(pad + 0.5, pad + 0.5, plotW, plotH);
  // colorbar
  var cbX = pad + plotW + 18, cbTop = pad, cbH = plotH;
  for (var yy = 0; yy < cbH; yy++) {
    var frac = 1 - yy / cbH, col2 = (limit != null) ? limitColor(min + frac * (max - min), limit) : viridis(frac);
    g.fillStyle = "rgb(" + col2[0] + "," + col2[1] + "," + col2[2] + ")";
    g.fillRect(cbX, cbTop + yy, cbW, 1);
  }
  g.strokeStyle = "#2a3142"; g.strokeRect(cbX + 0.5, cbTop + 0.5, cbW, cbH);
  // marcador del UMBRAL sobre la colorbar (la línea donde verde→rojo)
  if (limit != null && limit > min && limit < max) {
    var ly = cbTop + (1 - (limit - min) / (max - min)) * cbH;
    g.strokeStyle = "#ffffff"; g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(cbX - 3, ly); g.lineTo(cbX + cbW + 3, ly); g.stroke();
    g.fillStyle = "#ffffff"; g.font = "9px ui-monospace, SFMono-Regular, Menlo, monospace"; g.textBaseline = "middle";
    g.fillText("lím", cbX + cbW + 5, ly);
  }
  g.fillStyle = "#9aa6bf"; g.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace"; g.textBaseline = "middle";
  g.fillText(fmtNum(max), cbX + cbW + 5, cbTop + 5);
  g.fillText(fmtNum((max + min) / 2), cbX + cbW + 5, cbTop + cbH / 2);
  g.fillText(fmtNum(min), cbX + cbW + 5, cbTop + cbH - 5);
  node.innerHTML = "";
  var fig = document.createElement("figure"); fig.className = "ar-field";
  fig.appendChild(c);
  var cap = (a.title || "") + (grid.unit ? "  [" + grid.unit + "]" : "");
  if (cap.trim()) { var fc = document.createElement("figcaption"); fc.textContent = cap; fig.appendChild(fc); }
  node.appendChild(fig);
}

/* ── curva de equity (quant): línea en canvas para el stage de convergencia. ──
 * Dibuja una serie 1D (valor de la cartera en el tiempo, base 1.0). Verde si la
 * iteración PASA, ámbar si no. Sin CDN. Reusada solo por el renderer `convergence`
 * cuando una iteración trae `curve` (las de heatmap siguen usando fieldplot). */
function drawConvCurve(node, curve, opts) {
  opts = opts || {};
  var vals = (curve || []).map(Number).filter(function (v) { return !isNaN(v); });
  if (vals.length < 2) { node.innerHTML = empty(tr("render.sin_curva")); return; }
  var W = 460, H = 230, padL = 46, padR = 14, padT = 16, padB = 26;
  var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
  if (!(max > min)) max = min + 1;
  var plotW = W - padL - padR, plotH = H - padT - padB;
  function X(i) { return padL + (i / (vals.length - 1)) * plotW; }
  function Y(v) { return padT + (1 - (v - min) / (max - min)) * plotH; }
  var c = document.createElement("canvas"); c.className = "ar-field-canvas";
  c.width = W; c.height = H; c.style.maxWidth = "100%"; c.style.height = "auto";
  var g = c.getContext("2d");
  g.fillStyle = "#0b0e16"; g.fillRect(0, 0, W, H);
  // gridlines + marco
  g.strokeStyle = "#1c2536"; g.lineWidth = 1;
  for (var k = 0; k <= 4; k++) { var yy = padT + (k / 4) * plotH; g.beginPath(); g.moveTo(padL, yy); g.lineTo(W - padR, yy); g.stroke(); }
  g.strokeStyle = "#2a3142"; g.strokeRect(padL + 0.5, padT + 0.5, plotW, plotH);
  // línea base 1.0 (capital inicial) si está en rango
  if (1.0 > min && 1.0 < max) { var y1 = Y(1.0); g.setLineDash([3, 3]); g.strokeStyle = "#39435a"; g.beginPath(); g.moveTo(padL, y1); g.lineTo(W - padR, y1); g.stroke(); g.setLineDash([]); }
  // área + curva
  var pass = opts.passed === true;
  var line = pass ? "#22a054" : "#e0a23c", fill = pass ? "rgba(34,160,84,0.16)" : "rgba(224,162,60,0.14)";
  g.beginPath(); g.moveTo(X(0), Y(vals[0]));
  for (var i = 1; i < vals.length; i++) g.lineTo(X(i), Y(vals[i]));
  g.lineTo(X(vals.length - 1), padT + plotH); g.lineTo(X(0), padT + plotH); g.closePath();
  g.fillStyle = fill; g.fill();
  g.beginPath(); g.moveTo(X(0), Y(vals[0]));
  for (var j = 1; j < vals.length; j++) g.lineTo(X(j), Y(vals[j]));
  g.strokeStyle = line; g.lineWidth = 2; g.lineJoin = "round"; g.stroke();
  // ejes (valor final + min/max)
  g.fillStyle = "#9aa6bf"; g.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace"; g.textBaseline = "middle";
  g.textAlign = "right";
  g.fillText("×" + fmtNum(max), padL - 6, Y(max));
  g.fillText("×" + fmtNum(min), padL - 6, Y(min));
  g.textAlign = "left";
  node.innerHTML = "";
  var fig = document.createElement("figure"); fig.className = "ar-field";
  fig.appendChild(c);
  var fc = document.createElement("figcaption");
  fc.textContent = tr("render.equity", { x: fmtNum(vals[vals.length - 1]) });
  fig.appendChild(fc);
  node.appendChild(fig);
}

/* ── dicom: pixeles grises con window/level interactivo (read-only viewer) ── */
function drawDicomPixels(node, pix, a) {
  var w = pix.width | 0, h = pix.height | 0;
  var data = pix.data;
  if (typeof data === "string") { // base64 de Uint16/8 → no soportado inline; degradar honesto
    node.innerHTML = empty("Pixeles DICOM en base64 no soportados en este visor; pasa { image } rasterizado.");
    return;
  }
  var c = document.createElement("canvas"); c.width = w; c.height = h;
  c.className = "ar-dicom-canvas"; c.style.maxWidth = "100%"; c.style.height = "auto";
  var g = c.getContext("2d");
  var wc = pix.wc != null ? pix.wc : (pix.windowCenter != null ? pix.windowCenter : 128);
  var ww = pix.ww != null ? pix.ww : (pix.windowWidth != null ? pix.windowWidth : 256);
  var m = a.meta || a.metadata || {};
  function paint() {
    var img = g.createImageData(w, h), lo = wc - ww / 2;
    for (var i = 0; i < w * h; i++) {
      var val = Number(data[i]);
      var gv = Math.max(0, Math.min(255, Math.round((val - lo) / ww * 255)));
      var p = i * 4; img.data[p] = img.data[p + 1] = img.data[p + 2] = gv; img.data[p + 3] = 255;
    }
    g.putImageData(img, 0, 0);
    wlLabel.textContent = "W " + Math.round(ww) + " · L " + Math.round(wc);
  }
  var vp = document.createElement("div"); vp.className = "ar-dicom-vp";
  vp.appendChild(c);
  vp.insertAdjacentHTML("beforeend",
    '<div class="ar-dicom-ovl ar-tl"><span>' + escapeHtml(m.PatientName || m.patient || "—") + "</span></div>" +
    '<div class="ar-dicom-ovl ar-tr"><span>' + escapeHtml(m.Modality || m.modality || "") + "</span></div>");
  var wlLabel = document.createElement("div"); wlLabel.className = "ar-dicom-ovl ar-br ar-dicom-wl";
  vp.appendChild(wlLabel);
  // drag = window/level (mirar, no editar el dato)
  var drag = null;
  vp.addEventListener("pointerdown", function (e) { drag = { x: e.clientX, y: e.clientY, wc: wc, ww: ww }; vp.setPointerCapture(e.pointerId); });
  vp.addEventListener("pointermove", function (e) {
    if (!drag) return;
    ww = Math.max(1, drag.ww + (e.clientX - drag.x));
    wc = drag.wc + (e.clientY - drag.y);
    paint();
  });
  vp.addEventListener("pointerup", function () { drag = null; });
  var wrap = document.createElement("div"); wrap.className = "ar-dicom"; wrap.appendChild(vp);
  node.innerHTML = ""; node.appendChild(wrap);
  paint();
}

/* ── pan/zoom genérico (schematic): wheel = zoom, drag = pan ──────────────── */
function attachPanZoom(wrap) {
  if (!wrap) return;
  var sx = 1, tx = 0, ty = 0, drag = null;
  var target = wrap.firstElementChild;
  function apply() { if (target) target.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + sx + ")"; }
  if (target) { target.style.transformOrigin = "0 0"; target.style.transition = "transform .03s linear"; }
  wrap.addEventListener("wheel", function (e) {
    e.preventDefault();
    var k = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    var r = wrap.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    tx = mx - (mx - tx) * k; ty = my - (my - ty) * k; sx = Math.max(0.2, Math.min(20, sx * k)); apply();
  }, { passive: false });
  wrap.addEventListener("pointerdown", function (e) { drag = { x: e.clientX - tx, y: e.clientY - ty }; wrap.setPointerCapture(e.pointerId); wrap.classList.add("ar-pz-drag"); });
  wrap.addEventListener("pointermove", function (e) { if (!drag) return; tx = e.clientX - drag.x; ty = e.clientY - drag.y; apply(); });
  wrap.addEventListener("pointerup", function () { drag = null; wrap.classList.remove("ar-pz-drag"); });
  wrap.addEventListener("dblclick", function () { sx = 1; tx = 0; ty = 0; apply(); });
}

/* ── sort por columna para la grilla (planilla) ───────────────────────────────
 * MIRROR: mantener en sync con attachGridSort() de render/sala-render.js (misma lógica,
 * clases ar-sort-* compartidas). Mueve los <tr> existentes (sort estable) — jamás
 * reconstruye desde a.rows, así las ediciones del usuario en celdas sobreviven.
 * Opt-out: payload con sortable:false. Numérico-consciente: sólo si AMBAS celdas
 * son número-con-adornos ($ % , espacios); si no, localeCompare (part-numbers ok). */
function attachGridSort(table, a) {
  if (!table || (a && a.sortable === false)) return;
  var tbody = table.tBodies[0], head = table.tHead;
  if (!tbody || !head || !head.rows.length) return;
  function numOf(s) {
    s = String(s).trim().replace(/^[$€£]\s*/, "");
    if (!/^[-+]?[\d.,\s]+%?$/.test(s)) return NaN;
    return parseFloat(s.replace(/[^\d.eE+-]/g, ""));
  }
  function cmp(x, y) {
    var nx = numOf(x), ny = numOf(y);
    if (!isNaN(nx) && !isNaN(ny)) return nx - ny;
    return String(x).localeCompare(String(y));
  }
  Array.prototype.forEach.call(head.rows[0].cells, function (th, i) {
    th.classList.add("ar-sortable");
    th.title = tr("render.planilla.sort");
    th.addEventListener("click", function () {
      var dir = th.getAttribute("aria-sort") === "ascending" ? -1 : 1;
      Array.prototype.forEach.call(head.rows[0].cells, function (h) {
        h.removeAttribute("aria-sort"); h.classList.remove("ar-sort-asc", "ar-sort-desc");
      });
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      th.classList.add(dir === 1 ? "ar-sort-asc" : "ar-sort-desc");
      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function (ra, rb) {
        var ca = ra.cells[i] ? ra.cells[i].textContent.trim() : "";
        var cb = rb.cells[i] ? rb.cells[i].textContent.trim() : "";
        return dir * cmp(ca, cb);
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });
}



/* ── error visible (nunca un crudo con tags) ──────────────────────────────── */
function renderError(node, e, a) {
  node.className = "aleph-render ar-error";
  node.innerHTML = '<div class="ar-empty ar-err">' +
    '<strong>' + escapeHtml(tr("render.no_render")) + '</strong><br>' +
    '<span class="ar-err-msg">' + escapeHtml((e && e.message) || String(e)) + "</span>" +
    (a && body(a) ? '<details><summary>' + escapeHtml(tr("render.contenido_crudo")) + '</summary><pre class="ar-fallback">' +
      escapeHtml(body(a)).slice(0, 4000) + "</pre></details>" : "") + "</div>";
}

/* ============================================================================
 * render(artifactType, payload) → DOMNode   ·   LA INTERFAZ CONGELADA
 * ========================================================================== */
function render(artifactType, payload) {
  injectCss();
  // [2.3] Resolución en TRES pasos, cada uno con su dueño:
  //   1. identidad — alias → canónico, con la MISMA función que el borde de escritura
  //   2. dibujo    — delegación declarada de este módulo (dashboard→informe, 3d→cad)
  //   3. fallback  — tipo fuera de la unión (legacy, basura) → prosa, como siempre
  var raw = String(artifactType || "").toLowerCase().trim();
  var t = VOCAB.normalize(raw) || raw;
  t = DELEGATES[t] || t;
  if (!RENDERERS[t]) t = "informe";
  var a = P(payload);

  var node = document.createElement("div");
  node.className = "aleph-render ar-" + t;
  node.setAttribute("data-artifact-type", t);
  node.setAttribute("data-artifact-title", a.title || "");

  node.__arTeardown = [];                       // [2.4] lo que este render prendió
  var p;
  try { p = Promise.resolve(RENDERERS[t](node, a)); }
  catch (e) { p = Promise.reject(e); }
  node.__arReady = p.then(function () { return node; })
    // [2.4] un nodo ya desmontado no se "arregla": pintarle el error encima lo
    // resucita en un árbol que nadie mira (y el error suele SER el desmontaje).
    .catch(function (e) { if (!node.__arDead) renderError(node, e, a); return node; });
  return node;
}

/* hidratación lista (para tests/screenshots): ready(node) → Promise<node> */
function ready(node) { return (node && node.__arReady) || Promise.resolve(node); }

/* ============================================================================
 * unmount(target) → nº de nodos desmontados     ·  [Gate 4 · Fase 2 · obra 2.4]
 *
 * POR QUÉ EXISTE. Sacar un nodo del DOM NO apaga lo que ese nodo prendió:
 *   · `convergence` con autoplay es un `setInterval` que cada 1,4 s vuelve a
 *     DIBUJAR un heatmap entero dentro de un nodo que ya nadie mira. Se
 *     auto-frenaba sólo si el nodo había llegado a estar en `document.body`
 *     (`tick()`); un nodo que nunca se colgó, o un canvas que se reemplaza por
 *     otro, dejaba el timer corriendo para siempre.
 *   · cada iframe (`web`, `cad`, `volume3d`) sostiene un documento entero y un
 *     contexto WebGL. Removerlo del árbol no lo apaga en el acto: primero se le
 *     apaga el contenido (`about:blank`) y recién después se lo saca.
 * Con React pesado colgando de acá (el spike de la Sala moderna) esto deja de
 * ser una molestia y pasa a ser fuga: montar/desmontar N veces tiene que dejar
 * la memoria donde estaba. La vara `qa/verify_unmount_sin_fugas.mjs` lo MIDE, y
 * mide también el camino sin unmount para que el número tenga con qué compararse.
 *
 * `target` puede ser un nodo de render (se desmonta él y sus anidados y se lo
 * saca de su padre) o un HOST (se desmonta lo que tenga adentro y queda vacío,
 * listo para el próximo mount).
 * ========================================================================== */
/* onTeardown(node, fn) — EL CONTRATO para quien monta algo pesado encima.
 * Es la pieza que no existía: sin un lugar donde declarar "cuando este nodo
 * muera, soltá esto", una pantalla React (o cualquier cosa con suscripciones o
 * estado en un registro global) no tiene forma de soltar nada, y el nodo queda
 * retenido por el registro que lo apuntaba. Lo usan los renderers de acá y lo
 * exporta el módulo para que lo usen los de afuera. */
function onTeardown(node, fn) {
  if (!node) return;
  (node.__arTeardown || (node.__arTeardown = [])).push(fn);
}

function isRenderNode(n) {
  return !!(n && (n.__arTeardown ||
    (n.classList && n.classList.contains && n.classList.contains("aleph-render"))));
}

function killFrames(root) {
  if (!root || !root.querySelectorAll) return 0;
  var fr = root.querySelectorAll("iframe"), n = 0;
  for (var i = 0; i < fr.length; i++) {
    try { fr[i].removeAttribute("srcdoc"); fr[i].setAttribute("src", "about:blank"); } catch (e) {}
    try { if (fr[i].parentNode) fr[i].parentNode.removeChild(fr[i]); } catch (e) {}
    n++;
  }
  return n;
}

function teardownNode(node) {
  if (!node || node.__arDead) return 0;
  node.__arDead = true;                       // la hidratación tardía lo mira y se corta
  var fns = node.__arTeardown || [];
  for (var i = 0; i < fns.length; i++) { try { fns[i](); } catch (e) {} }
  node.__arTeardown = [];
  killFrames(node);
  return 1;
}

function unmount(target) {
  if (!target) return 0;
  var n = 0, nodes = [], i;
  if (target.querySelectorAll) {
    var kids = target.querySelectorAll(".aleph-render");   // anidados primero
    for (i = 0; i < kids.length; i++) nodes.push(kids[i]);
  }
  var self = isRenderNode(target);
  if (self) nodes.push(target);
  for (i = 0; i < nodes.length; i++) n += teardownNode(nodes[i]);
  killFrames(target);                          // iframes que no cuelgan de un nodo ar-*
  if (self) { if (target.parentNode) target.parentNode.removeChild(target); }
  else { try { target.innerHTML = ""; } catch (e) {} }
  return n;
}

/* ¿este nodo ya se desmontó? Lo consulta la hidratación tardía (y las varas). */
function isDead(node) { return !!(node && node.__arDead); }

/* conveniencias (NO son el contrato; el contrato es render/ready):
 *  · mount(el, type, payload) → DOMNode  (limpia el host y cuelga el nodo)
 *  · renderArtifact(payload) → DOMNode    (lee payload.type) */
function mount(el, artifactType, payload) {
  var node = render(artifactType, payload);
  // [2.4] montar DESMONTA lo anterior: `innerHTML=""` sacaba el nodo viejo del árbol
  // y le dejaba el timer y el iframe corriendo. El ciclo tiene que ser simétrico.
  if (el) { unmount(el); el.appendChild(node); }
  return node;
}
function renderArtifact(payload) {
  var a = P(payload);
  return render(a.type || a.artifactType || "informe", a);
}

/* ── CSS self-contained (inyectado una sola vez) ──────────────────────────── */
var _cssDone = false;
function injectCss() {
  if (_cssDone || typeof document === "undefined") return;
  _cssDone = true;
  if (document.getElementById("aleph-render-css")) return;
  var st = document.createElement("style");
  st.id = "aleph-render-css";
  st.textContent = AR_CSS;
  document.head.appendChild(st);
}

var AR_CSS = `
.aleph-render{--ar-bg:#0e1118;--ar-fg:#e6eaf4;--ar-mut:#8b95ac;--ar-line:#222838;--ar-acc:#6c8cff;
  position:relative;width:100%;height:100%;min-height:80px;box-sizing:border-box;
  color:var(--ar-fg);font:14px/1.6 var(--font-ui, "Hanken Grotesk", system-ui, sans-serif);overflow:auto}
.aleph-render *{box-sizing:border-box}
.ar-skel{display:flex;align-items:center;gap:8px;padding:22px;color:var(--ar-mut)}
.ar-skel-dot{width:7px;height:7px;border-radius:50%;background:var(--ar-acc);opacity:.4;animation:ar-bl 1s infinite}
.ar-skel-dot:nth-child(2){animation-delay:.15s}.ar-skel-dot:nth-child(3){animation-delay:.3s}
.ar-skel-t{font-size:12px;margin-left:4px}
@keyframes ar-bl{0%,100%{opacity:.25}50%{opacity:1}}
.ar-empty{padding:26px;color:var(--ar-mut);font-style:italic;text-align:center}
.ar-err{font-style:normal;text-align:left;color:#e9b8b8}.ar-err-msg{color:#f0a0a0;font:12px var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)}
.ar-fallback{background:#11151f;border:1px solid var(--ar-line);border-radius:8px;padding:10px;overflow:auto;color:#c8d0e0;white-space:pre-wrap}
.ar-error details{margin-top:8px}.ar-error summary{cursor:pointer;color:var(--ar-mut)}

/* informe / doc */
.ar-prose{padding:26px 30px}
.ar-prose h1,.ar-prose h2,.ar-prose h3{line-height:1.25;margin:1.1em 0 .5em}
.ar-prose h1{font-size:1.6em}.ar-prose h2{font-size:1.3em}.ar-prose h3{font-size:1.12em}
.ar-prose p{margin:.6em 0}.ar-prose ul,.ar-prose ol{margin:.5em 0 .5em 1.4em}
.ar-prose code{background:#11151f;border:1px solid var(--ar-line);border-radius:5px;padding:.08em .35em;font:.88em var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)}
.ar-prose pre{background:#0b0e16;border:1px solid var(--ar-line);border-radius:10px;padding:13px 15px;overflow:auto}
.ar-prose pre code{background:none;border:none;padding:0}
.ar-prose a{color:var(--ar-acc);text-decoration:none}.ar-prose a:hover{text-decoration:underline}
.ar-prose table{border-collapse:collapse;margin:1em 0;width:100%}
.ar-prose th,.ar-prose td{border:1px solid var(--ar-line);padding:7px 11px;text-align:left}
.ar-prose th{background:#161b27;font-weight:500}
.ar-prose blockquote{border-left:3px solid var(--ar-acc);margin:.8em 0;padding:.2em 1em;color:var(--ar-mut)}
.ar-cite{color:var(--ar-acc);font-size:.82em;vertical-align:super;text-decoration:none;padding:0 1px}
.ar-cite-sep{border:none;border-top:1px solid var(--ar-line);margin:1.4em 0 .8em}
.ar-sources-h{font-size:.78em;text-transform:uppercase;letter-spacing:.08em;color:var(--ar-mut);margin-bottom:.4em}
.ar-sources-list{margin:0 0 0 1.2em;font-size:.9em;color:var(--ar-mut)}
.ar-chart-fig{margin:1.1em 0;background:#0b0e16;border:1px solid var(--ar-line);border-radius:12px;padding:14px}
.ar-doc-page{max-width:760px;margin:0 auto;padding:46px 56px;background:#12151d;border:1px solid var(--ar-line);
  border-radius:6px;font-family:Georgia,"Times New Roman",serif;line-height:1.7}
.ar-documento .ar-doc-page,.ar-doc .ar-doc-page,.aleph-render.ar-documento,.aleph-render.ar-doc{background:transparent}
.ar-documento,.ar-doc{padding:24px;background:#0a0c12}

/* planilla */
.ar-fxbar{display:flex;align-items:center;gap:8px;padding:6px 10px;background:#11151f;border-bottom:1px solid var(--ar-line)}
.ar-fx{font:500 11px var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);color:var(--ar-mut);background:#0b0e16;border:1px solid var(--ar-line);border-radius:5px;padding:2px 7px}
.ar-formula{flex:1;background:transparent;border:none;color:var(--ar-fg);font:13px var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);outline:none}
.ar-grid-wrap{overflow:auto}
.ar-grid{border-collapse:collapse;width:100%;font:13px var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)}
.ar-grid th,.ar-grid td{border:1px solid var(--ar-line);padding:6px 12px;text-align:left;white-space:nowrap}
.ar-grid th{background:#161b27;color:var(--ar-mut);font-weight:500;position:sticky;top:0}
.ar-grid td.ar-num{text-align:right;font-variant-numeric:tabular-nums}
.ar-grid tr:nth-child(even) td{background:rgba(255,255,255,.014)}
.ar-grid th.ar-sortable{cursor:pointer;user-select:none;white-space:nowrap}
.ar-grid th.ar-sortable::after{content:"↕";opacity:.28;font-size:9px;margin-left:6px}
.ar-grid th.ar-sort-asc::after{content:"↑";opacity:.9}
.ar-grid th.ar-sort-desc::after{content:"↓";opacity:.9}

/* web / cad iframe */
.ar-frame{width:100%;height:100%;min-height:340px;border:none;background:#fff;border-radius:8px;display:block}
.ar-cad-frame{background:#0c0f18;min-height:420px}

/* schematic pan/zoom */
.ar-pz{position:relative;width:100%;height:100%;min-height:360px;overflow:hidden;background:#0b0e16;
  border:1px solid var(--ar-line);border-radius:10px;cursor:grab}
.ar-pz.ar-pz-drag{cursor:grabbing}
.ar-pz-inner,.ar-pz-img{will-change:transform}
.ar-pz-inner svg{display:block}.ar-pz-img{max-width:none}
.ar-pz-inner{padding:14px;background:#f7f8fb;border-radius:6px}

/* fieldplot */
.ar-field{margin:0;padding:18px;display:flex;flex-direction:column;align-items:center;gap:10px}
.ar-field-canvas,.ar-field-img{border-radius:8px;background:#0b0e16}
.ar-field-img{max-width:100%}
.ar-field figcaption{color:var(--ar-mut);font:12px var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)}

/* dicom */
.ar-dicom{padding:14px;display:flex;justify-content:center;background:#05070b;border-radius:10px}
.ar-dicom-vp{position:relative;background:#000;border-radius:6px;overflow:hidden;touch-action:none;cursor:crosshair;max-width:100%}
.ar-dicom-img,.ar-dicom-canvas{display:block;max-width:100%;max-height:560px;object-fit:contain}
.ar-dicom-ovl{position:absolute;display:flex;flex-direction:column;gap:1px;font:11px var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);color:#7ee0c0;text-shadow:0 1px 2px #000;pointer-events:none}
.ar-dicom-ovl.ar-tl{top:8px;left:9px}.ar-dicom-ovl.ar-tr{top:8px;right:9px;text-align:right;align-items:flex-end}
.ar-dicom-ovl.ar-bl{bottom:8px;left:9px}.ar-dicom-ovl.ar-br{bottom:8px;right:9px;text-align:right;align-items:flex-end}
.ar-dicom-ro{color:#d08a8a;letter-spacing:.1em;font-size:9px}
.ar-dicom-wl{color:#e0c87e}

/* convergencia (capa que hace visible el loop · genérica) */
.ar-conv{padding:16px 18px;display:flex;flex-direction:column;gap:13px}
.ar-conv-head{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.ar-conv-it{font:500 13px var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);color:var(--ar-mut)}
.ar-conv-itn{color:var(--ar-fg);font-size:15px}
.ar-conv-metric{display:flex;align-items:baseline;gap:10px;flex:1;min-width:170px}
.ar-conv-mlabel{font-size:11px;color:var(--ar-mut);text-transform:uppercase;letter-spacing:.06em}
.ar-conv-val{font:500 26px/1 var(--font-ui, "Hanken Grotesk", system-ui, sans-serif);font-variant-numeric:tabular-nums;color:var(--ar-fg)}
.ar-conv-delta{font:500 13px var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);color:var(--ar-mut)}
.ar-conv-delta.good{color:#37c871}.ar-conv-delta.bad{color:#e85d5d}
.ar-conv-verdict{font:500 12.5px var(--font-ui, "Hanken Grotesk", system-ui, sans-serif);letter-spacing:.09em;padding:5px 15px;border-radius:999px;border:1px solid var(--ar-line);color:var(--ar-mut)}
.ar-conv-verdict.fail{color:#fff;background:#cf2e30;border-color:#e85d5d}
.ar-conv-verdict.pass{color:#06281a;background:#37c871;border-color:#37c871}
.ar-conv-stage{display:flex;justify-content:center;align-items:center;min-height:120px;background:#0b0e16;border:1px solid var(--ar-line);border-radius:10px;overflow:auto;transition:border-color .25s}
.ar-conv-stage .aleph-render{height:auto;min-height:0;overflow:visible}
.ar-conv-stage .ar-field{padding:12px}
.ar-conv[data-verdict="fail"] .ar-conv-stage{border-color:#cf2e3066}
.ar-conv[data-verdict="pass"] .ar-conv-stage{border-color:#37c87166}
.ar-conv-limit{font:11px var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);color:var(--ar-mut);text-align:center}
.ar-conv-ctrl{display:flex;align-items:center;gap:8px}
.ar-conv-btn{background:#161b27;color:var(--ar-fg);border:1px solid var(--ar-line);border-radius:7px;min-width:30px;height:28px;cursor:pointer;font-size:14px;line-height:1}
.ar-conv-btn:disabled{opacity:.35;cursor:default}
.ar-conv-track{flex:1;display:flex;gap:5px;align-items:center;padding-left:4px}
.ar-conv-dot{width:8px;height:8px;border-radius:50%;background:#2a3142;transition:background .2s,box-shadow .2s}
.ar-conv-dot.past{background:#5a647d}
.ar-conv-dot.on{background:var(--ar-acc);box-shadow:0 0 0 3px #6c8cff33}
`;

/* ── superficie pública ───────────────────────────────────────────────────── */
if (typeof window !== "undefined") {
  window.AlephRender = {
    render: render, ready: ready, mount: mount, renderArtifact: renderArtifact,
    unmount: unmount, isDead: isDead, onTeardown: onTeardown,   // [2.4] el ciclo, simétrico
    TYPES: TYPES.slice(),
    // ALIAS conserva el NOMBRE (superficie pública) y cambia de dueño: ya no es
    // una tabla local, es la del vocabulario. DELEGATES es lo que sí decide acá.
    ALIAS: VOCAB.ALIASES, DELEGATES: DELEGATES, coverage: coverage,
    vocabulary: VOCAB, ensureDeps: ensureDeps,
  };
}

export { render, ready, mount, unmount, isDead, onTeardown, renderArtifact, TYPES, coverage, ensureDeps };
export default render;
