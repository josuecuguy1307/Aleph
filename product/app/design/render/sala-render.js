/* ============================================================================
 * render/sala-render.js — PIPELINE DE RENDER + CANVAS POLIMÓRFICO (Sala de uso · slice 1)
 *
 * REUSABLE. Convierte la salida del agente en obra renderada: NUNCA texto crudo.
 *  - markdown (negritas/listas/tablas GFM/links)  vía marked
 *  - math LaTeX ($...$ inline · $$...$$ display)   vía KaTeX
 *  - citas clickeables ([n] → ancla a la fuente)
 *  - sanitización (DOMPurify): la obra se renderiza, no se ejecuta HTML arbitrario.
 *
 * Canvas polimórfico: SalaRender.renderArtifact(el, artifact) despacha por
 * artifact.type, resuelto antes contra EL vocabulario único (alias → canónico →
 * delegación declarada; ver `resolveType`). Fuera de la unión → fallback markdown.
 * Agregar un tipo = agregarlo al vocabulario (platform/artifacts/vocabulary.py) y
 * darle renderer o delegación acá — la vara de 2.3 falla si queda sin cubrir.
 *
 * Contrato del artefacto:
 *   { type:'informe'|'planilla'|'web'|'documento'|'imagen'|<otro>,
 *     content:string,           // markdown / html / texto / data-uri-o-url
 *     citations?:[{id,label,url}],
 *     rows?:[[...]], cols?:[...] // para 'planilla'
 *   }
 * Invariante: ningún JSON/path/tool-call llega acá; el caller manda SOLO la obra.
 * ========================================================================== */
(function () {
  "use strict";
  if (window.SalaRender) return;

  // [Casa 2 · F1.c] VENDORIZADO. Estas 6 libs son Capa 0 — el "wow base": markdown,
  // fórmulas, código resaltado. Bajarlas de un CDN significaba que sin internet el
  // agente producía la obra y La Sala no podía mostrarla. Cargan BAJO DEMANDA, así
  // que el costo de empaquetarlas sólo se paga cuando se usan.
  //
  // Las rutas se resuelven contra la URL de ESTE script, no del documento: sala/ y
  // metodo/ están un nivel abajo y `./vendor/…` apuntaría al lugar equivocado.
  var VBASE = (function () {
    try {
      var s = document.currentScript && document.currentScript.src;
      if (s) return new URL("../vendor/", s).href;
    } catch (e) {}
    return "../vendor/";
  })();
  var CDN = {
    marked: VBASE + "marked.min.js",
    dompurify: VBASE + "purify.min.js",
    katex: VBASE + "katex/katex.min.js",
    katexAuto: VBASE + "katex/auto-render.min.js",
    katexCss: VBASE + "katex/katex.min.css",
    hljs: VBASE + "highlight.min.js",
    mermaid: VBASE + "mermaid.min.js",
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

  var _ready = null;
  function ensureDeps() {
    if (_ready) return _ready;
    loadCss(CDN.katexCss);
    _ready = Promise.all([
      window.marked ? Promise.resolve() : loadScript(CDN.marked),
      window.DOMPurify ? Promise.resolve() : loadScript(CDN.dompurify),
      window.katex ? Promise.resolve() : loadScript(CDN.katex),
    ]).then(function () {
      return window.renderMathInElement ? Promise.resolve() : loadScript(CDN.katexAuto);
    });
    return _ready;
  }

  // ── [highlight] resaltado de sintaxis en los code blocks de una obra ─────────
  // (el belt de programación entregaba código plano). hljs se carga ON DEMAND — sólo
  // si el root realmente contiene <pre><code>; sin red / CDN caído → el código queda
  // plano (degradación segura, jamás rompe el render). Corre POST-sanitización: hljs
  // sólo envuelve texto ya escapado en <span class="hljs-*"> (cero HTML del contenido).
  // Los colores no vienen de un css externo: sala.html los tiñe con las vars del tema.
  var _hljsP = null;
  function ensureHljs() {
    if (window.hljs) return Promise.resolve();
    if (!_hljsP) _hljsP = loadScript(CDN.hljs).catch(function () { _hljsP = null; });
    return _hljsP;
  }
  function highlightIn(el) {
    try {
      if (!el || !el.querySelector("pre code")) return;
      ensureHljs().then(function () {
        if (!window.hljs) return;
        el.querySelectorAll("pre code").forEach(function (b) {
          if (b.dataset.hlDone) return;
          b.dataset.hlDone = "1";
          try { window.hljs.highlightElement(b); } catch (e) {}
        });
      });
    } catch (e) {}
  }

  function escapeHtml(s) {
    // Escapa TAMBIÉN comillas: imagen/galeria interpolan src/alt en atributos "..." →
    // sin escapar la comilla, un src/alt malicioso rompe el atributo (onerror = XSS almacenado).
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // [i18n-bi Ola B] base-types del SalaRender VIVO: resuelve claves de captura vía
  // window.t (i18n.js, cargado antes en sala.html); fallback = el literal ES original.
  // Hornea el idioma del run al render (cubre text-nodes Y atributos title/alt).
  function tr(k, fb) { var s = window.t ? window.t(k) : null; return (s && s !== k) ? s : fb; }

  // saca el cerco markdown (```html / ```js / ```three …) si el contenido vino enfencado;
  // el renderer 3D/web necesita el código crudo, no dentro de un bloque de código.
  function stripFences(s) {
    s = String(s == null ? "" : s).trim();
    var m = s.match(/```(?:html|js|javascript|three|threejs)?\s*([\s\S]*?)```/i);
    return m ? m[1].trim() : s;
  }

  // ── canal usuario: matar leaks de internals antes de renderizar ────────────
  // El trace interno (rutas, JSON de plan, marcadores de tool/terminal) NUNCA va al canvas.
  function stripLeaks(md) {
    var s = String(md == null ? "" : md);
    s = s.replace(/<<<\s*TURN\s*:\s*(?:chat|obra)\s*>>>/gi, "");        // marcador de turno (si lo hubiera)
    s = s.replace(/【[^】]*】/g, "");                                     // citas de tool 【search_works†…】
    s = s.replace(/[†‡]\w+[:=]\w+/g, "");                       // †result=0 sueltos
    s = s.replace(/\/Users\/[^\s)"'`\]]+/g, "[ruta]");                   // rutas absolutas /Users/...
    s = s.replace(/^[ \t]*(?:›|▶▶?|»|⟶|\$ |# trace|TRACE:).*$/gim, "");   // líneas de trace/terminal
    s = s.replace(/^\s*(?:Plan de acci[oó]n|Pensando|Razonamiento)\s*:.*$/gim, "");  // plan/razonamiento crudo
    s = s.replace(/\n{3,}/g, "\n\n");
    return s.trim();
  }

  // ── markdown → html sanitizado ────────────────────────────────────────────
  function mdToSafeHtml(md) {
    var raw = window.marked.parse(String(md == null ? "" : md), {
      gfm: true, breaks: false, headerIds: false, mangle: false,
    });
    // sanitiza: render, no ejecución. Permitimos los tags de una obra (incl. tablas,
    // anchors con target/rel) pero nada de scripts/iframes inyectados por el contenido.
    return window.DOMPurify.sanitize(raw, {
      ADD_ATTR: ["target", "rel"],
      FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form"],
    });
  }

  // ── citas clickeables: [n] en el texto → ancla a la lista de fuentes ───────
  function linkCitations(html, citations) {
    if (!citations || !citations.length) return html;
    var byId = {};
    citations.forEach(function (c) { byId[String(c.id)] = c; });
    var withRefs = html.replace(/\[(\d+)\]/g, function (m, n) {
      if (!byId[n]) return m;
      return '<a href="#cite-' + n + '" class="sala-cite" ' +
        'title="' + escapeHtml(byId[n].label || byId[n].url || "") + '">[' + n + "]</a>";
    });
    var list = citations.map(function (c) {
      var label = escapeHtml(c.label || c.url || ("Fuente " + c.id));
      var link = c.url
        ? '<a href="' + escapeHtml(c.url) + '" target="_blank" rel="noopener noreferrer">' + label + "</a>"
        : label;
      return '<li id="cite-' + escapeHtml(String(c.id)) + '">' + link + "</li>";
    }).join("");
    return withRefs +
      '<hr class="sala-cite-sep"><div class="sala-sources"><div class="sala-sources-h">' + escapeHtml(tr("render.fuentes", "Fuentes")) + '</div>' +
      '<ol class="sala-sources-list">' + list + "</ol></div>";
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
    // LA GUARDIA PRIMERO: convierte los `$…$` que pasan el filtro en `\(…\)`, que es
    // el delimitador que KaTeX ya tenía prendido. El motor no cambia; la decisión
    // vive en UN lugar y no en la lista de delimitadores de dos archivos.
    try { aplicarMathInline(el); } catch (e) { /* la guardia jamás rompe el render */ }
    try {
      window.renderMathInElement(el, {
        // NOTE: single-`$` inline math is intentionally DISABLED. In finance/data
        // artifacts `$` is overwhelmingly currency (e.g. "$80.2B, net income $29.6B"),
        // and the `$…$` delimiter would swallow it into italic KaTeX math. Inline math
        // still works via `\(…\)`; display math via `$$…$$`.
        //
        // [Educación] LA DECISIÓN SIGUE EN PIE, Y AHORA ESTÁ MEDIDA TAMBIÉN EN EL CHAT —
        // que es la otra superficie, y la que este archivo acaba de empezar a servir. Se
        // barrieron los 212 mensajes de agente de `aleph.db` buscando pares `$…$`:
        //
        //     Educación  213 pares · 207 son math (`\dfrac{f(x+h)-f(x)}{h}`, `x^2`, `h`)
        //     Finanzas     3 pares · los TRES son el falso positivo de moneda
        //                            («US$ 63.762,69 / ETH: US$»), que KaTeX se comería
        //     Oficina      2 pares
        //
        // O sea: prenderlo arreglaría 213 renglones de un tutor y rompería 3 de un
        // informe financiero. NO se prende acá y NO se inventa un discriminador de texto:
        // es una decisión de producto con las dos puntas medidas, y queda para el dueño.
        // Lo que sí queda cerrado hoy son los 38 `$$…$$` del hilo de Educación, que no
        // tenían ninguna ambigüedad y tampoco se pintaban.
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\[", right: "\\]", display: true },
          { left: "\\(", right: "\\)", display: false },
        ],
        throwOnError: false,
      });
    } catch (e) { /* math malformado no debe romper el render */ }
  }

  // ── GRÁFICO REAL desde un bloque ```chart {spec json} ─────────────────────
  // El agente emite, dentro de la obra:  ```chart {"type":"bar"|"line","title":..,
  //   "labels":[..],"series":[{"name":..,"data":[..]}]}```  y lo dibujamos como SVG REAL
  //   (no una imagen falsa). Los datos son los de la obra. Estilos inline → self-contained.
  var CHART_PAL = ["#6c8cff", "#43c59e", "#e0a13a", "#e06a6a", "#9b6cff", "#3aa7e0"];
  function fmtNum(n) {
    n = Number(n); var a = Math.abs(n);
    if (a >= 1e9) return (n / 1e9).toFixed(1) + "B";
    if (a >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (a >= 1e3) return (n / 1e3).toFixed(1) + "k";
    return String(Math.round(n * 100) / 100);
  }
  /* MIRROR: mantener en sync con buildChartSVG() de ../render/render.js (misma lógica; solo
   * difiere la clase raíz ar-chart vs sala-chart). Tipos: bar (default) · line · area
   * (línea + relleno) · scatter ({series:[{name,points:[[x,y]]}]}, eje X por VALOR) ·
   * candlestick ({labels, ohlc:[[o,h,l,c]]}, velas up/down). Spec que no cierra → null
   * (el fence queda visible como código — fallback honesto, jamás un gráfico inventado). */
  var CANDLE_UP = "#43c59e", CANDLE_DOWN = "#e06a6a";
  var CHART_TYPES = { bar: 1, line: 1, area: 1, scatter: 1, candlestick: 1, linechart: 1 };
  // UN lector de spec (misma idea que artifact_export._chart_normalizado): la raíz
  // {labels,series} y Chart.js {data:{labels,datasets}} son el MISMO dato. type ausente
  // con labels+series → bar. type desconocido (p.ej. JSON Schema "object") → null.
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
    svg.setAttribute("class", "sala-chart"); svg.setAttribute("viewBox", "0 0 " + W + " " + H);
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
  // reemplaza los bloques ```chart por el SVG (post-markdown, post-sanitización: el SVG lo
  // construimos NOSOTROS con DOM API + textContent, nunca con html del modelo → sin inyección).
  function renderCharts(el) {
    if (!el || !el.querySelectorAll) return;
    // Cualquier fence cuyo JSON CIERRA como chart (```chart, ```json, o sin lenguaje).
    // Si no cierra, el bloque se queda como código — fallback honesto.
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
      var fig = document.createElement("figure"); fig.className = "sala-chart-fig";
      fig.appendChild(svg);
      if (pre.parentNode) pre.parentNode.replaceChild(fig, pre);
    });
    renderSvgFences(el);
    renderMermaidFences(el);
  }

  // [UX·A5] DIAGRAMAS INLINE: los bloques ```svg del modelo se componen como figura,
  // SANITIZADOS con el MISMO perfil que el renderer schematic (render, no ejecución:
  // sin script/foreignObject/handlers). Un SVG inválido queda como code-block (honesto).
  function renderSvgFences(el) {
    var blocks = el.querySelectorAll("pre > code.language-svg, code.language-svg");
    Array.prototype.forEach.call(blocks, function (code) {
      var raw = String(code.textContent || "").trim();
      if (!/^<svg[\s>]/i.test(raw) || !window.DOMPurify) return;
      var safe = window.DOMPurify.sanitize(raw, {
        USE_PROFILES: { svg: true, svgFilters: true },
        ADD_TAGS: ["use"],
        FORBID_TAGS: ["script", "foreignObject"],
        FORBID_ATTR: ["onload", "onclick"],
      });
      if (!safe || safe.indexOf("<svg") < 0) return;
      var pre = code.closest("pre") || code;
      var fig = document.createElement("figure"); fig.className = "sala-chart-fig sala-svg-fig";
      fig.innerHTML = safe;
      var s = fig.querySelector("svg");
      if (s) { s.style.maxWidth = "100%"; s.style.height = "auto"; }
      if (pre.parentNode) pre.parentNode.replaceChild(fig, pre);
    });
  }

  // ── [mermaid] LOS DIAGRAMAS DEL MODELO, PINTADOS ────────────────────────────
  // `visualize` emite cuatro fences: ```svg ```mermaid ```chartjs ```html. Sólo el
  // primero se componía; los otros tres caían al code-block. Éste prende `mermaid`
  // y SÓLO mermaid: `chartjs` y `html` quedan afuera a propósito —el primero pide un
  // motor de charts que este repo ya resuelve con `buildChartSVG`, y el segundo es
  // ejecución, que es justo lo que este renderer no hace.
  //
  // VENDORIZADO, JAMÁS UN CDN. Aleph es local-first: el bundle vive en `vendor/` y
  // viaja adentro del .app. Se carga ON DEMAND —igual que hljs— y sólo si el nodo
  // realmente trae un fence mermaid: son 3,5 MB que no se bajan en un turno de texto.
  //
  // SIN `foreignObject`. mermaid pinta las etiquetas con HTML embebido si lo dejás, y
  // el perfil de sanitización de este archivo lo prohíbe (render, no ejecución) — así
  // que las etiquetas saldrían VACÍAS. `htmlLabels:false` las manda a `<text>`, que es
  // SVG de verdad y sobrevive al sanitizador. Es el precedente de siempre: no alcanza
  // con que los bytes lleguen, tienen que llegar en la forma que el otro lado acepta.
  var _mermaidP = null;
  function ensureMermaid() {
    if (window.mermaid) return Promise.resolve();
    if (!_mermaidP) _mermaidP = loadScript(CDN.mermaid).catch(function () {
      _mermaidP = null;                     // sin el vendor: el fence queda como código
      throw new Error("mermaid no cargó");
    });
    return _mermaidP;
  }

  //: El tema se decide por LUMINANCIA del fondo real, no por un hex ni por una clase:
  //: es el mismo criterio con el que la piel de Aleph cruza a los stacks.
  function _mermaidOscuro(el) {
    try {
      var bg = getComputedStyle(el && el.nodeType === 1 ? el : document.body).backgroundColor;
      var m = /rgba?\(([^)]+)\)/.exec(bg || "");
      if (!m) return false;
      var p = m[1].split(",").map(parseFloat);
      if (p.length >= 4 && p[3] === 0) return false;          // transparente: no sé, claro
      return (0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]) < 128;
    } catch (e) { return false; }
  }

  var _mermaidN = 0;
  function renderMermaidFences(el) {
    if (!el || !el.querySelectorAll) return;
    var blocks = el.querySelectorAll("pre > code.language-mermaid, code.language-mermaid");
    if (!blocks.length) return;                  // nada que pintar: no se baja el bundle
    ensureMermaid().then(function () {
      try {
        window.mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          htmlLabels: false,
          flowchart: { htmlLabels: false },
          theme: _mermaidOscuro(el) ? "dark" : "default",
        });
      } catch (e) { return; }
      Array.prototype.forEach.call(blocks, function (code) {
        var raw = String(code.textContent || "").trim();
        if (!raw) return;
        var id = "sala-mmd-" + (++_mermaidN) + "-" + Math.floor(Math.random() * 1e6);
        var p;
        // UN diagrama roto no puede llevarse la burbuja: el throw sincrónico de
        // `render()` y el reject de su promesa se atajan los DOS, y el fence se queda
        // como bloque de código — que es la verdad: no se pudo dibujar.
        try { p = window.mermaid.render(id, raw); } catch (e) { return; }
        if (!p || typeof p.then !== "function") return;
        p.then(function (out) {
          var svg = out && out.svg ? out.svg : "";
          if (!svg || !window.DOMPurify) return;
          var safe = window.DOMPurify.sanitize(svg, {
            USE_PROFILES: { svg: true, svgFilters: true },
            ADD_TAGS: ["use"],
            FORBID_TAGS: ["script", "foreignObject"],
            FORBID_ATTR: ["onload", "onclick"],
          });
          if (!safe || safe.indexOf("<svg") < 0) return;
          var pre = code.closest("pre") || code;
          if (!pre.parentNode) return;
          var fig = document.createElement("figure");
          fig.className = "sala-chart-fig sala-svg-fig sala-mermaid-fig";
          fig.innerHTML = safe;
          var sv = fig.querySelector("svg");
          if (sv) { sv.style.maxWidth = "100%"; sv.style.height = "auto"; sv.removeAttribute("height"); }
          pre.parentNode.replaceChild(fig, pre);
        }).catch(function () { /* diagrama inválido: se queda el code-block */ })
          .then(function () {
            // mermaid deja su nodo de trabajo colgado cuando el parseo falla.
            var huerfano = document.getElementById("d" + id) || document.getElementById(id);
            if (huerfano && huerfano.parentNode === document.body) huerfano.remove();
          });
      });
    }).catch(function () { /* sin vendor: los fences quedan como código */ });
  }

  // ── sort por columna para la grilla (planilla) ─────────────────────────────
  // MIRROR: mantener en sync con attachGridSort() de ../render/render.js (misma
  // lógica, clases ar-sort-* compartidas — el CSS vive en sala.html para .sala-grid).
  // Mueve los <tr> existentes (sort estable): las ediciones contenteditable sobreviven.
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
      th.title = tr("render.planilla.sort", "ordenar por esta columna");
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

  // ── RENDERERS por tipo ─────────────────────────────────────────────────────
  var RENDERERS = {
    // prosa + math + tablas + citas clickeables
    informe: function (el, a) {
      el.className = "sala-canvas sala-informe";
      el.innerHTML = linkCitations(mdToSafeHtml(stripLeaks(a.content || "")), a.citations);
      highlightIn(el);   // [highlight] code blocks de la obra
      renderCharts(el);   // ```chart → SVG real
      runKatex(el);
    },
    // grilla (tabular-nums) + barra de fórmula. v0: render de rows/cols o tabla markdown.
    planilla: function (el, a) {
      el.className = "sala-canvas sala-planilla";
      var cols = a.cols, rows = a.rows;
      if ((!rows || !rows.length) && a.content) {
        // si vino como tabla markdown, la renderizamos como grilla
        el.innerHTML =
          '<div class="sala-formula-bar"><span class="sala-fx">fx</span><input class="sala-formula" placeholder="—" aria-label="barra de fórmula"></div>' +
          '<div class="sala-grid-wrap">' + mdToSafeHtml(a.content) + "</div>";
        highlightIn(el);   // [highlight]
        attachGridSort(el.querySelector(".sala-grid-wrap table"), a);
        return;
      }
      var head = (cols || []).map(function (c) { return "<th>" + escapeHtml(c) + "</th>"; }).join("");
      var body = (rows || []).map(function (r) {
        return "<tr>" + r.map(function (cell) {
          return '<td contenteditable="true">' + escapeHtml(cell) + "</td>";
        }).join("") + "</tr>";
      }).join("");
      el.innerHTML =
        '<div class="sala-formula-bar"><span class="sala-fx">fx</span><input class="sala-formula" placeholder="—" aria-label="barra de fórmula"></div>' +
        '<div class="sala-grid-wrap"><table class="sala-grid">' +
        (head ? "<thead><tr>" + head + "</tr></thead>" : "") +
        "<tbody>" + body + "</tbody></table></div>";
      attachGridSort(el.querySelector("table.sala-grid"), a);
    },
    // preview real en iframe AISLADO (sandbox: corre el html pero no toca tu sesión).
    web: function (el, a) {
      el.className = "sala-canvas sala-web";
      var f = document.createElement("iframe");
      f.className = "sala-web-frame";
      f.setAttribute("sandbox", "allow-scripts allow-forms");
      f.setAttribute("title", tr("render.preview_web", "preview web"));
      f.srcdoc = String(a.content || "");
      el.innerHTML = "";
      el.appendChild(f);
    },
    // dashboard: gráficos como obra de PRIMERA clase (no incrustados en prosa). El contenido
    // trae uno o más bloques ```chart {spec}; los dibujamos grandes en una grilla. El texto
    // suelto (títulos/notas) acompaña. Mismo chart-renderer seguro (SVG por DOM API).
    dashboard: function (el, a) {
      el.className = "sala-canvas sala-dashboard";
      el.innerHTML = '<div class="sala-dash-grid">' + mdToSafeHtml(stripLeaks(a.content || "")) + "</div>";
      highlightIn(el);   // [highlight]
      renderCharts(el);
      runKatex(el);
      if (!el.querySelector(".sala-chart-fig")) {           // no había chart real → honesto, no vacío fingido
        el.innerHTML = '<div class="sala-empty">' + escapeHtml(tr("render.dashboard.empty", "Este dashboard todavía no tiene gráficos con datos.")) + '</div>';
      }
    },
    // 3D: escena three.js. Corre DENTRO del iframe aislado (sandbox allow-scripts SIN
    // allow-same-origin → origen opaco, render·D): el código del modelo nunca toca tu sesión.
    // three.js se carga desde CDN ADENTRO del iframe (su propio contexto), no en la página.
    "3d": function (el, a) {
      el.className = "sala-canvas sala-web sala-3d";
      var code = stripFences(String(a.content || ""));
      var full = /<html|<!doctype/i.test(code);
      var doc = full ? code : (
        '<!doctype html><html><head><meta charset="utf-8">' +
        '<style>html,body{margin:0;height:100%;overflow:hidden;background:#0b0b0f}canvas{display:block}</style>' +
        // URL ABSOLUTA a propósito: el iframe va con sandbox="allow-scripts" (sin
        // allow-same-origin), y una ruta relativa dentro de un srcdoc es terreno
        // resbaladizo. Además, concatenar '<scr'+'ipt' hace que ningún bundler
        // encuentre esta dependencia — por eso vivía sin que nadie la viera.
        '<scr' + 'ipt src="' + new URL("three/three.min.js", VBASE).href + '"></scr' + 'ipt></head>' +
        '<body><scr' + 'ipt>try{\n' + code +
        '\n}catch(e){document.body.innerHTML="<pre style=\\"color:#f88;padding:16px;font:13px monospace\\">"+(e&&e.stack||e)+"</pre>";}</scr' + 'ipt></body></html>'
      );
      var f = document.createElement("iframe");
      f.className = "sala-web-frame";
      f.setAttribute("sandbox", "allow-scripts");   // SIN allow-same-origin → BYOK/sesión protegidas
      f.setAttribute("title", tr("render.escena_3d", "escena 3D"));
      f.srcdoc = doc;
      el.innerHTML = "";
      el.appendChild(f);
    },
    // memo / carta / doc: markdown en contenedor "documento" (serif, márgenes).
    documento: function (el, a) {
      el.className = "sala-canvas sala-documento";
      el.innerHTML = '<div class="sala-doc-page">' + mdToSafeHtml(stripLeaks(a.content || "")) + "</div>";
      highlightIn(el);   // [highlight]
      renderCharts(el);   // ```chart → SVG real
      runKatex(el);
    },
    // imagen a tamaño completo (url o data-uri).
    imagen: function (el, a) {
      el.className = "sala-canvas sala-imagen";
      var src = String(a.content || a.url || "");
      el.innerHTML = src
        ? '<img class="sala-img" alt="' + escapeHtml(a.alt || tr("render.imagen.alt", "imagen generada")) + '" src="' + escapeHtml(src) + '">'
        : '<div class="sala-empty">' + escapeHtml(tr("render.imagen.empty", "Sin imagen.")) + '</div>';
    },
    // galería: grilla de N imágenes. Reusa la MISMA celda <img class="sala-img"> que 'imagen'
    // (mismo estilo/comportamiento), una por entrada de a.images; salta las vacías. CSS auto-
    // contenido (grid inline en el wrapper), sin depender de hoja externa. Contrato:
    //   a = { type:"galeria", images:[{content|url, alt?}, ...], title? }
    galeria: function (el, a) {
      el.className = "sala-canvas sala-galeria";
      var cells = (a.images || []).map(function (img) {
        var src = String((img && (img.content || img.url)) || "");
        if (!src) return "";
        return '<div class="sala-galeria-cell"><img class="sala-img" alt="' +
          escapeHtml((img && img.alt) || tr("render.imagen.alt", "imagen generada")) +
          '" src="' + escapeHtml(src) + '"></div>';
      }).filter(function (s) { return s; }).join("");
      if (!cells) {
        el.innerHTML = '<div class="sala-empty">' + escapeHtml(tr("render.imagen.empty", "Sin imagen.")) + '</div>';
        return;
      }
      var head = a.title
        ? '<div class="sala-galeria-title">' + escapeHtml(String(a.title)) + '</div>'
        : "";
      el.innerHTML = head +
        '<div class="sala-galeria-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px">' +
        cells + '</div>';
    },
    // ── tipos RICOS delegados a AlephRender (render/render.js) · ADITIVO ──
    // cad = malla 3D orbitable (STL/OBJ/glTF) · schematic = SVG pan/zoom (KiCad)
    // dicom = visor médico read-only (overlays) · fieldplot = heatmap de campo escalar
    // (FEM/CFD: von Mises, temperatura) con colorbar viridis. NO tocan los 7 de arriba; si
    // el módulo AlephRender no cargó, degradan a 'informe' (honesto, nunca crashea).
    cad: function (el, a) { richDelegate(el, a, "cad"); },
    schematic: function (el, a) { richDelegate(el, a, "schematic"); },
    // [UX·A5 · 2.3] 'diagrama' ya NO es una llave: es un ALIAS de `schematic` en EL
    // vocabulario, y `renderArtifact` lo resuelve antes de despachar. El dibujo es el
    // mismo de siempre (SVG sanitizado + pan/zoom); lo que murió es la llave que
    // hacía parecer que era un tipo aparte de este lado y un alias del otro.
    dicom: function (el, a) { richDelegate(el, a, "dicom"); },
    fieldplot: function (el, a) { richDelegate(el, a, "fieldplot"); },
    // convergence = la capa que hace VISIBLE el loop (it.N + métrica+delta + veredicto
    // FALLA→PASA + heatmap rojo→verde). Reusa fieldplot adentro; misma degradación honesta.
    convergence: function (el, a) { richDelegate(el, a, "convergence"); },
    // volume3d = volumen 3D rotable (medicina): mesh por marching cubes de una estructura
    // segmentada (pulmón/hueso). three.js en iframe sandbox, como cad. Misma degradación.
    volume3d: function (el, a) { richDelegate(el, a, "volume3d"); },
    // linechart = serie temporal dedicada (worldbank → *.linechart.json): labels+series.
    linechart: function (el, a) { richDelegate(el, a, "linechart"); },
  };

  // delega un tipo rico al módulo AlephRender (lo importa sala.html). El nodo trae
  // su propio CSS (ar-*) y su hidratación (three.js en iframe / SVG sanitizado).
  function richDelegate(el, a, type) {
    if (!(window.AlephRender && window.AlephRender.render)) { RENDERERS.informe(el, a); return; }
    el.className = "sala-canvas sala-rich sala-rich-" + type;
    el.innerHTML = "";
    el.appendChild(window.AlephRender.render(type, a));
  }

  // ── EL VOCABULARIO ÚNICO · registro 2/2 [Gate 4 · Fase 2 · obra 2.3] ───────
  // Este registro tenía 16 llaves y CERO alias: un artefacto `doc`, `table`, `md`
  // o `heatmap` —todos alias que el almacén acepta y persiste— caía al fallback
  // markdown aunque su renderer existiera acá. Ahora la identidad la resuelve EL
  // vocabulario (`render/vocabulary.js`, cargado por AlephRender) y lo que decide
  // este módulo es sólo su propio dibujo.
  function vocab() { return window.AlephVocabulary || null; }

  //: Delegaciones de DIBUJO de este registro (no identidad): un tipo canónico sin
  //: renderer propio y con destino declarado.
  var DELEGATES = {
    // `codigo` (heurística isCodeDominant de la Sala): markdown + highlight ES su
    // render declarado (sala.html:2146), no un accidente del fallback.
    codigo: "informe",
    // [Convergencia · superficie 7] Misma delegación que el registro de `render/`: un
    // .pptx no se dibuja en línea, y lo que la casa tiene de él es su texto o su ficha.
    // Se declara en LOS DOS registros a propósito — este archivo no ve el `DELEGATES`
    // del otro, y un canónico cubierto en uno y mudo en el otro es exactamente la
    // divergencia que EL vocabulario existe para matar. Medido: durante esta obra el
    // registro de `render/` quedó verde y éste rojo, y sólo la sonda lo dijo.
    presentacion: "informe",
  };

  var _vocabWarned = false;
  function resolveType(raw) {
    var v = vocab();
    var t = String(raw == null ? "" : raw).trim().toLowerCase();
    if (v) { t = v.normalize(t) || t; }
    else if (!_vocabWarned) {
      _vocabWarned = true;
      // Fallo VISIBLE: sin vocabulario los alias no resuelven (un `doc` dibuja como
      // prosa). Pasa sólo en una página que cargue SalaRender sin AlephRender.
      try { console.warn("[SalaRender] sin EL vocabulario (render/vocabulary.js): los alias de tipo no resuelven; se despacha por el nombre crudo."); } catch (e) {}
    }
    return DELEGATES[t] || t;
  }

  /* Cobertura contra EL vocabulario — la lee la vara de 2.3. `uncovered` DEBE
   * quedar vacío: todo canónico tiene renderer o delegación declarada acá. */
  function coverage() {
    var v = vocab();
    var canon = v ? v.CANONICAL.slice() : [];
    var renderers = Object.keys(RENDERERS);
    return {
      canonical: canon, renderers: renderers,
      delegates: Object.assign({}, DELEGATES),
      uncovered: canon.filter(function (t) { return !RENDERERS[t] && !DELEGATES[t]; }),
      outside: renderers.filter(function (t) { return canon.length && canon.indexOf(t) === -1; }),
    };
  }

  /* ── DESMONTAJE [Gate 4 · Fase 2 · obra 2.4] ───────────────────────────────
   * Los renderers de acá escriben con `el.innerHTML = …`: el nodo viejo sale del
   * árbol y sus recursos NO. Los de este módulo son los iframes (`web` y `3d`,
   * que cuelgan directo del host, sin nodo `ar-*`); los de los tipos ricos los
   * apaga AlephRender, que es quien los prendió. Devuelve cuántas piezas apagó. */
  function unmount(el) {
    if (!el) return 0;
    var n = 0;
    try {
      var fr = el.querySelectorAll ? el.querySelectorAll("iframe") : [];
      for (var i = 0; i < fr.length; i++) {
        // apagar ANTES de sacar: un iframe removido a secas se lleva puesto su
        // documento y su contexto WebGL sin soltarlos en el momento.
        try { fr[i].removeAttribute("srcdoc"); fr[i].setAttribute("src", "about:blank"); } catch (e) {}
        if (fr[i].parentNode) fr[i].parentNode.removeChild(fr[i]);
        n++;
      }
    } catch (e) {}
    try {
      if (window.AlephRender && window.AlephRender.unmount) n += window.AlephRender.unmount(el);
    } catch (e) {}
    try { el.innerHTML = ""; } catch (e) {}
    return n;
  }

  function renderArtifact(el, artifact) {
    if (!el) return Promise.resolve();
    artifact = artifact || {};
    unmount(el);                      // [2.4] montar desmonta lo anterior: ciclo simétrico
    return ensureDeps().then(function () {
      var fn = RENDERERS[resolveType(artifact.type)];
      if (fn) { fn(el, artifact); }
      else { RENDERERS.informe(el, artifact); }   // desconocido → markdown (fallback)
    }).catch(function () {
      // si el CDN falla, degradamos a texto escapado — JAMÁS crudo con tags.
      el.className = "sala-canvas sala-informe";
      el.innerHTML = "<pre class='sala-fallback'>" + escapeHtml(artifact.content || "") + "</pre>";
    });
  }

  // ── OBRA RICA: la validación de FORMA por tipo ─────────────────────────────────────
  //
  // [Convergencia · superficie 7 · paso 2] Vivía adentro de `sala/sala.html`, y por eso
  // pasaban dos cosas: la Sala v2 —que usa ESTE MISMO renderer— no tenía validación de
  // obra rica, y `qa/verify_vocabulario_cableado.py` tenía que auditarla parseando el HTML
  // de una página entera con un `split("var RICH_SHAPES = {")`. La forma es del que dibuja
  // la forma; acá está al lado de los renderers que la consumen.
  //
  // Espejo exacto del contrato del productor (`executor._capture_rich_obra`). Fail-closed:
  // tipo desconocido o forma inválida → null → el path histórico queda intacto.
  var RICH_SHAPES = {
    fieldplot:   function(o){ return !!(o.grid && o.grid.values && o.grid.values.length); },
    convergence: function(o){ return Array.isArray(o.iterations) && o.iterations.length>0; },
    planilla:    function(o){ return Array.isArray(o.rows) && o.rows.length>0; },
    cad:         function(o){ return typeof o.content==='string' && !!o.content.trim(); },
    volume3d:    function(o){ return typeof o.vertices_b64==='string' && typeof o.faces_b64==='string'; },
    imagen:      function(o){ return typeof o.content==='string' && !!o.content; },
    linechart:   function(o){ return Array.isArray(o.labels) && o.labels.length>0 && Array.isArray(o.series) && o.series.length>0; },
    // 4B · formas run-surfaceadas: galería (grilla de N) + dicom/schematic (gap #6 cerrado).
    galeria:     function(o){ return Array.isArray(o.images) && o.images.length>0 && o.images.every(function(im){ return im && (im.content||im.url); }); },
    dicom:       function(o){ return (typeof o.image==='string' && !!o.image.trim()) || (typeof o.url==='string' && !!o.url.trim()) || !!(o.pixels && o.pixels.data && o.pixels.width && o.pixels.height); },
    schematic:   function(o){ return (typeof o.content==='string' && !!o.content.trim()) || (typeof o.url==='string' && !!o.url.trim()); }
  };
  // [Gate 4 · Fase 2 · 2.3] QUÉ tipos son de captura rica lo dice EL vocabulario
  // (`rich_capture`, la misma bandera que gobierna executor._capture_rich_obra); acá vive
  // sólo la FORMA. Un tipo rico nuevo sin validador NO se cuela mudo: se rechaza
  // diciéndolo (una vez), que es lo contrario de lo que pasaba antes — esta tabla era un
  // espejo a mano y su desfase no lo veía nadie.
  var _richWarned = {};
  function validRichObra(o){
    if(!o || !o.type) return null;
    var V = window.AlephVocabulary;
    var t = V ? (V.normalize(o.type) || o.type) : o.type;
    if(V && !V.isRich(t)){ return null; }        // no es de captura rica: no es obra rica
    var f = RICH_SHAPES[t];
    if(!f){
      if(!_richWarned[t]){ _richWarned[t]=1;
        try{ console.warn('[SalaRender] el vocabulario declara "'+t+'" como captura rica y no hay validador de forma para ese tipo — no se acepta.'); }catch(e){}
      }
      return null;
    }
    return f(o) ? o : null;
  }
  // La vara de 2.3 la lee: las llaves de RICH_SHAPES contra `rich_capture` del vocabulario.
  window.__salaRichShapes = function(){
    var V = window.AlephVocabulary;
    var keys = Object.keys(RICH_SHAPES);
    var rich = V ? V.richCapture() : [];
    return { keys: keys, rich: rich,
             sinValidador: rich.filter(function(t){ return !RICH_SHAPES[t]; }),
             deMas: keys.filter(function(t){ return rich.length && rich.indexOf(t)<0; }) };
  };

  window.SalaRender = {
    renderArtifact: renderArtifact,
    // La forma de una obra rica, validada. La usan las DOS Salas.
    validRichObra: validRichObra,
    renderMarkdown: function (md) { return ensureDeps().then(function () { return mdToSafeHtml(md); }); },
    clean: stripLeaks,                         // canal usuario: limpiar leaks (reusado por el chat)
    types: Object.keys(RENDERERS),
    resolveType: resolveType,                  // [2.3] alias → canónico → delegación
    coverage: coverage,                        // [2.3] cobertura contra EL vocabulario
    unmount: unmount,                          // [2.4] apaga iframes/timers y vacía el host
    ensureDeps: ensureDeps,
    // [UX·A5] figuras inline post-markdown (```chart + ```svg sanitizado) — lo usa el
    // chat de la Sala para que un diagrama del modelo se componga en la burbuja.
    renderInlineFigures: renderCharts,
    // [highlight] resaltado de sintaxis on-demand — lo usa el chat para sus burbujas.
    highlightIn: highlightIn,
    // [Educación] EL MATH, PARA QUIEN PINTE TEXTO DEL MODELO FUERA DE UNA OBRA.
    //
    // `runKatex` existía desde siempre y las obras lo llamaban (`informe`, `dashboard`,
    // `documento`); lo que faltaba era la puerta para el CHAT, que pinta el MISMO texto
    // del mismo modelo y se quedaba con el markup crudo. Medido sobre `aleph.db`: las 24
    // respuestas del hilo de Educación traen **38 bloques `$$…$$`** y ninguno se pintaba
    // — un tutor de matemática entregando `\lim_{h \to 0}` a la vista.
    //
    // Va como export y no copiado adentro del chat A PROPÓSITO: los delimitadores son UNA
    // decisión y tiene que vivir en UN lugar (ver la nota de `runKatex`). Un segundo
    // `renderMathInElement` con su propia lista sería la duplicación que este repo mata.
    runKatex: runKatex,
    // [Educación] LA GUARDIA DEL `$` INLINE, expuesta como FUNCIÓN PURA. No es un
    // adorno: es lo que permite medirla contra los 216 pares reales de `aleph.db` sin
    // navegador ni DOM (`qa/verify_dolar_inline.mjs`). La decisión de qué es fórmula y
    // qué es moneda se toma acá adentro; KaTeX sólo dibuja lo que ya pasó el filtro.
    mathInlineDeDolar: mathInlineDeDolar,
  };
})();
