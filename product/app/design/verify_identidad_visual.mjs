/* verify_identidad_visual.mjs — IDENTIDAD VISUAL · una sola piel para toda la plataforma.
 *
 * Tres sondas en un solo script, sin suite E2E pesada:
 *
 *   1. CONTRASTE REAL (§b) — abre cada superficie en los DOS temas, camina el DOM VIVO y, por
 *      cada elemento con texto propio, compone el color efectivo de fondo (subiendo por los
 *      ancestros, componiendo alfas, y abriendo los gradientes en sus paradas para quedarse con
 *      el PEOR caso) y mide el ratio WCAG contra el color de texto efectivo (opacidad incluida).
 *      Falla cualquier par por debajo de 4.5:1 (texto normal) o 3:1 (texto grande: ≥24px, o
 *      ≥18.66px en negrita). Esto NO se puede hacer leyendo el CSS: el color heredado y la
 *      composición sobre gradientes sólo existen en el DOM montado.
 *
 *   2. TIPOGRAFÍA (§c) — lista las font-family DISTINTAS realmente computadas en texto visible.
 *      El estándar (Home · Conexiones · Métodos) usa dos: 'Hanken Grotesk' (UI) y 'Spectral'
 *      (títulos), más monoespaciada donde hay código. Cualquier otra familia es un mundo aparte.
 *
 *   4. EL MODO QUE MURIÓ (§d) — censo estático de los interruptores que partían la interfaz en dos
 *      ("Guiado | Técnico", "⚙ Modo técnico") + medición EN VIVO de lo que protegían: la revisión
 *      de tools antes de equipar, que ahora sale sola, con todo marcado y sin bloquear. Las dos
 *      mitades juntas o no prueba nada: sacar el interruptor y perder la información sería peor.
 *
 *   3. LITERALES DE COLOR (§a) — censo estático de colores hardcodeados en propiedades de color,
 *      separando las DEFINICIONES de token (legítimas: ahí nacen las variables) de los USOS
 *      sueltos (el bug: no giran con el tema). Es el número que se reporta como "sitios".
 *
 * Correr:  node product/app/design/verify_identidad_visual.mjs          (necesita node_modules)
 *          SOLO=Cuarto node ...           una superficie
 *          CENSO=1 node ...               sólo el censo estático (sin browser)
 *
 * sala/sala.html queda FUERA a propósito: un archivo, un dueño (terminal E). El censo lo lista
 * aparte para que el pase posterior tenga el mapa.
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join, relative, extname } from "node:path";
import fs from "node:fs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.FRONT_PORT || 8188);
const BASE = `http://localhost:${PORT}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* pinta la revisión antes de equipar con un forjado de mentira y le abre el "?" — es lo único que
 * hace falta para poder MEDIRLA (contraste, idioma, tooltips) sin una forja real. */
const PINTA_REVISION = () => {
  if (!window.__manual || !window.__manual._showForVerify) return false;
  window.__manual._showForVerify({
    server: "api.ejemplo.com", tools: ["listar_items", "buscar_item", "leer_item"] });
  // [T6 §10] el "?" ya no despliega un pliegue local: es el [?] estándar y abre #ayudapop con la
  // sección de docs/guia. Se lo abre igual, para medir SU contraste y SU idioma.
  const why = document.getElementById("msealWhy");
  if (why) why.click();
  return true;
};

/* ─────────────────────────── superficies ───────────────────────────
 * SESIÓN: se siembra `puppet_user` ANTES de cargar. Sin eso, Home y Métodos rebotan a
 * `/Auth.dc.html` y la sonda medía la pantalla de Auth creyendo que medía el Home — con la
 * consecuencia de que las secciones del Home ("Tus Aleph", "Lo que puedes armar", el carrusel
 * de ejemplos) NUNCA entraron al barrido y su contraste daba 0 por ausencia, no por estar bien.
 * El guard `mide lo que dice medir` (abajo) es lo que impide que el hueco vuelva en silencio.
 *
 * `abrir`: clicks previos a la medición — lo que vive detrás de un menú también es superficie
 * (el chip del cerebro dentro del ⋯ era justamente el caso índice del reporte humano).
 * `evaluar`: JS previo, para lo que ningún click alcanza. Lo pide la revisión antes de equipar
 * (#msealbar): sólo existe DESPUÉS de una forja real de dos minutos, y ahora la ve TODO el mundo
 * —ya no cuelga de un "Modo técnico"— así que su contraste y su idioma son medibles, no opinables. */
const SUPERFICIES = [
  { id: "Home",        url: "/Home.dc.html" },
  // [cierre de Conexiones] el Centro murió y su ruta redirige: medir ahí disparaba el guard
  // §g («mide la URL que pidió») con razón. Se mide la pantalla que quedó viva.
  { id: "Modelos",     url: "/Modelos.dc.html",    abrir: [".md-abrir", "#mdAgregar"] },
  { id: "Metodos",     url: "/metodo/metodo.html" },
  { id: "Conectar",    url: "/Conectar.dc.html",   abrir: ["#kindFilter button:nth-child(2)", ".card .btn"] },
  // Settings NO se toca antes de medir: sus secciones (Preferencias, Zona de peligro)
  // conviven en un scroll y cualquier click de tab las saca del viewport medible.
  { id: "Settings",    url: "/Settings.dc.html" },
  { id: "Biblioteca",  url: "/Biblioteca.dc.html", abrir: [".libRosterRow"] },
  { id: "Historial",   url: "/Historial.dc.html",  abrir: [".scp1"] },
  { id: "Inspeccion",  url: "/inspeccion/inspeccion.html" },
  { id: "Ayuda",       url: "/Ayuda.dc.html",      abrir: [".scp2"] },
  { id: "Auth",        url: "/Auth.dc.html" },
  { id: "Onboarding",  url: "/Onboarding.dc.html" },
  // el Cuarto esconde casi todo detrás de disparadores: el ⋯ (con el chip del cerebro
  // adentro — el caso índice), la paleta de EQUIPAR, el chat del Guía y el overlay BYO.
  { id: "Cuarto",      url: "/cuarto/cuarto.pixi.html", espera: 2600,
    abrir: ["#metaBtn", "#equipBtn", "#camToggle", "#lpToggle"] },
  { id: "CuartoBYO",   url: "/cuarto/cuarto.pixi.html", espera: 2600,
    abrir: ["#metaBtn", "#byoBtn"] },
  // [§d] LA REVISIÓN ANTES DE EQUIPAR, con su detalle crudo desplegado. Se pinta con un forjado de
  // mentira (`_showForVerify`, seam declarado en cuarto.manual.js) porque el forjado REAL tarda
  // minutos y necesita llaves; lo que se mide acá es la PIEL del panel, que es idéntica.
  { id: "CuartoRevision", url: "/cuarto/cuarto.pixi.html", espera: 2600,
    evaluar: PINTA_REVISION },
];

/* ─────────────────────── 1 · contraste (en el DOM vivo) ─────────────────────── */
const SONDA_CONTRASTE = () => {
  const out = [];
  const seen = new Set();

  const num = (s) => parseFloat(s) || 0;
  function parse(c) {
    if (!c || c === "transparent" || c === "none") return null;
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (m) {
      const p = m[1].split(/[,\s/]+/).filter(Boolean).map(num);
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    }
    const h = c.match(/^#([0-9a-f]{3,8})$/i);
    if (h) {
      let x = h[1];
      if (x.length === 3 || x.length === 4) x = x.split("").map((d) => d + d).join("");
      const n = parseInt(x.slice(0, 6), 16);
      return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255, a: x.length === 8 ? parseInt(x.slice(6, 8), 16) / 255 : 1 };
    }
    return null;
  }
  const over = (fg, bg) => ({                       // fg sobre bg (bg se asume opaco)
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1,
  });
  function lum(c) {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }
  const ratio = (a, b) => { const L1 = lum(a), L2 = lum(b); const hi = Math.max(L1, L2), lo = Math.min(L1, L2); return (hi + 0.05) / (lo + 0.05); };
  const hex = (c) => "#" + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

  // paradas de color de un background-image (gradientes): el peor caso manda
  function paradas(img) {
    if (!img || img === "none") return [];
    const cs = img.match(/rgba?\([^)]+\)|#[0-9a-fA-F]{3,8}/g) || [];
    return cs.map(parse).filter((c) => c && c.a > 0);
  }

  // fondos CANDIDATOS de un elemento: sube por ancestros componiendo capas semitransparentes.
  function fondos(el) {
    let capas = [];              // capas de arriba hacia abajo, ya en orden de composición
    let n = el;
    while (n && n !== document.documentElement.parentNode) {
      const st = getComputedStyle(n);
      const grad = paradas(st.backgroundImage);
      const bc = parse(st.backgroundColor);
      if (grad.length) { capas.push({ tipo: "grad", cs: grad }); if (grad.every((g) => g.a >= 1)) break; }
      if (bc && bc.a > 0) { capas.push({ tipo: "solid", c: bc }); if (bc.a >= 1) break; }
      n = n.parentElement;
    }
    const base = { r: 255, g: 255, b: 255, a: 1 };       // suelo del browser
    // expandir los gradientes en variantes (peor caso = todas las combinaciones de sus paradas)
    let variantes = [base];
    for (let i = capas.length - 1; i >= 0; i--) {
      const cap = capas[i];
      const next = [];
      for (const v of variantes) {
        if (cap.tipo === "solid") next.push(over(cap.c, v));
        else for (const g of cap.cs) next.push(over(g, v));
      }
      variantes = next;
      if (variantes.length > 24) variantes = variantes.slice(0, 24);
    }
    return variantes;
  }

  function opacidadAcumulada(el) {
    let o = 1, n = el;
    while (n && n.nodeType === 1) { o *= parseFloat(getComputedStyle(n).opacity || "1"); n = n.parentElement; }
    return o;
  }

  function visible(el) {
    const st = getComputedStyle(el);
    if (st.visibility === "hidden" || st.display === "none") return false;
    if (el.closest("[hidden]")) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    return true;
  }

  function ruta(el) {
    const p = [];
    let n = el;
    for (let i = 0; n && n.nodeType === 1 && i < 4; i++) {
      let s = n.tagName.toLowerCase();
      if (n.id) { p.unshift(s + "#" + n.id); break; }
      if (n.className && typeof n.className === "string") s += "." + n.className.trim().split(/\s+/).slice(0, 2).join(".");
      p.unshift(s); n = n.parentElement;
    }
    return p.join(">");
  }

  const todos = document.querySelectorAll("body *");
  for (const el of todos) {
    if (/^(SCRIPT|STYLE|SVG|PATH|CANVAS|NOSCRIPT|TEMPLATE|BR|HR|IMG)$/.test(el.tagName)) continue;
    // sólo texto PROPIO (los nodos de texto directos), para no medir el mismo string N veces
    let txt = "";
    for (const n of el.childNodes) if (n.nodeType === 3) txt += n.nodeValue;
    txt = txt.replace(/\s+/g, " ").trim();
    if (!txt) continue;
    if (!visible(el)) continue;
    /* [WCAG 1.4.3 · excepción "Incidental"] El texto que forma parte de un control de
       interfaz INACTIVO está explícitamente exento del requisito de contraste. Un botón
       deshabilitado DEBE verse apagado: exigirle 4.5:1 sería exigir que no se note que
       está apagado. Sin esta exclusión, el control ^ˇ de la pista (que se deshabilita en
       los extremos de la lista, con opacity .3) contaba como fallo en cada pantalla. */
    if (el.closest("[disabled],[aria-disabled='true']")) continue;

    const st = getComputedStyle(el);
    const fgRaw = parse(st.color);
    if (!fgRaw) continue;
    const op = opacidadAcumulada(el);
    if (op < 0.06) continue;                                   // invisible a propósito (animaciones)

    const size = parseFloat(st.fontSize) || 16;
    const peso = parseInt(st.fontWeight, 10) || 400;
    const grande = size >= 24 || (size >= 18.66 && peso >= 700);
    const min = grande ? 3 : 4.5;

    const bgs = fondos(el);
    let peor = null;
    for (const bg of bgs) {
      const fg = over({ ...fgRaw, a: fgRaw.a * op }, bg);
      const r = ratio(fg, bg);
      if (!peor || r < peor.r) peor = { r, fg, bg };
    }
    if (!peor || peor.r >= min) continue;

    const key = ruta(el) + "|" + hex(peor.fg) + "|" + hex(peor.bg);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      ruta: ruta(el), texto: txt.slice(0, 46), ratio: Math.round(peor.r * 100) / 100, min,
      fg: hex(peor.fg), bg: hex(peor.bg), size: Math.round(size * 10) / 10, peso,
    });
  }

  // ── el texto que NO es un nodo de texto: los placeholders ──────────────────────
  // Un campo vacío es lo primero que se lee de un formulario y su color se declara
  // aparte (::placeholder); el barrido del DOM no lo ve y por eso se cuela gris sobre gris.
  for (const el of document.querySelectorAll("input[placeholder], textarea[placeholder]")) {
    if (!visible(el) || !el.getAttribute("placeholder")) continue;
    const ph = getComputedStyle(el, "::placeholder");
    const fgRaw = parse(ph.color);
    if (!fgRaw) continue;
    const st = getComputedStyle(el);
    const size = parseFloat(st.fontSize) || 16;
    const min = size >= 24 ? 3 : 4.5;
    const bgs = fondos(el);
    let peor = null;
    for (const bg of bgs) {
      const fg = over({ ...fgRaw, a: fgRaw.a * opacidadAcumulada(el) }, bg);
      const r = ratio(fg, bg);
      if (!peor || r < peor.r) peor = { r, fg, bg };
    }
    if (!peor || peor.r >= min) continue;
    const key = "ph|" + ruta(el) + "|" + hex(peor.fg);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ ruta: ruta(el) + "::placeholder", texto: el.getAttribute("placeholder").slice(0, 46),
      ratio: Math.round(peor.r * 100) / 100, min, fg: hex(peor.fg), bg: hex(peor.bg), size, peso: 400 });
  }

  out.sort((a, b) => a.ratio - b.ratio);
  return out;
};

/* ─────────────────────── 4 · tooltips que tapan (§e) ───────────────────────
 * El tooltip nativo (`title`) lo posiciona el sistema operativo BAJO EL CURSOR: no se
 * puede reubicar, no se puede correr, y en un menú tapa la fila de al lado. Es
 * aceptable cuando AGREGA algo; es puro estorbo cuando repite lo que el elemento ya
 * dice —ahí el globo tapa justamente el texto que estaba describiendo. Ese era el caso
 * del reporte: el chip del cerebro, con toda su información escrita adentro, llevaba
 * title="Cerebro" encima.
 * Esta sonda marca dos cosas: (1) el `title` redundante —su texto ya está visible en el
 * propio elemento— y (2) el `title` sobre un contenedor que no es un control. */
const SONDA_TOOLTIPS = () => {
  const out = [];
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
  for (const el of document.querySelectorAll("[title]")) {
    const t = norm(el.getAttribute("title"));
    if (!t) continue;
    const st = getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden") continue;
    const propio = norm(el.textContent);
    if (!propio) continue;                       // sin texto visible no puede taparlo
    const redundante = propio === t || propio.includes(t) || (t.length > 3 && t.includes(propio));
    if (!redundante) continue;
    out.push({
      sel: (el.id ? "#" + el.id : el.tagName.toLowerCase() + "." + String(el.className || "").split(/\s+/)[0]),
      title: el.getAttribute("title").slice(0, 40), texto: el.textContent.replace(/\s+/g, " ").trim().slice(0, 40),
      enMenu: !!el.closest("[role='menu'], .metamenu, #aleph-nav-panel"),
    });
  }
  return out;
};

/* ─────────────────────── 5 · idioma mezclado en la misma vista (§f) ───────────────────
 * El diccionario ES/EN está en lockstep (633/633 claves, verificado aparte). El idioma
 * mezclado NO viene de ahí: viene de los strings que NUNCA pasan por t() — literales
 * escritos en el HTML o armados en JS. A esos los traduce en vivo el mapa TM de i18n.js
 * por MutationObserver, y lo que no está en el mapa se queda en español aunque la UI
 * esté en inglés. Eso es "popups en inglés con botones en español".
 *
 * La sonda carga cada superficie en EN y marca el texto VISIBLE que sigue en español.
 * Criterio conservador (el mismo de scanlib): sólo marca por PERTENENCIA a un léxico
 * cerrado de palabras-función y marcas ortográficas del español. Un token desconocido
 * —nombre propio, ticker, comando, unidad— nunca se marca. */
const SONDA_IDIOMA = () => {
  const out = [];
  const seen = new Set();
  // Palabras EXCLUSIVAS del español — sin homógrafos ingleses (fuera: no, es, son, sin, la,
  // el, un, en, a, y, o, real, total, final, media, error…, que hacían saltar frases inglesas
  // perfectamente sanas como "No active session" o "one tap, no forms").
  const ES = /(^|[\s(¿¡"'—·«])(del|los|las|una|unos|unas|que|para|con|por|sus|tus|mis|más|muy|hay|está|están|fue|hacer|tiene|tienes|todo|todos|toda|todas|cada|cuando|donde|desde|hasta|entre|pero|porque|así|acá|aquí|este|esta|esto|esos|esas|otro|otra|algo|nada|alguien|nadie|qué|cómo|cuál|quién|ya|sí|puede|pueden|hace|haces|sirve|arma|armar|guardá|guardar|cerrar|agregar|sumar|volver|seguir|probar|piezas|pieza|cuenta|llave|llaves|herramienta|herramientas|conexión|conexiones|ajustes|ayuda|buscar|nuevo|nueva|listo|todavía|ahora|antes|después|arriba|abajo|toca|tocá|elegí|elige|mira|mirá|pídele|pedile|tuyo|tuya|propio|propia|último|última|día|días|semana|obra|estado|lectura)([\s.,;:!?)"'…—·»]|$)/i;
  const ORTO = /[ñ¿¡áéíóú]/i;
  // una sola palabra ambigua no alcanza: hace falta ortografía española o DOS señales
  const esEspanol = (t) => {
    if (ORTO.test(t)) return true;
    let n = 0, re = new RegExp(ES.source, "gi"), m;
    while ((m = re.exec(t)) && n < 2) { n++; re.lastIndex = m.index + 1; }
    return n >= 2;
  };
  // vocabulario compartido ES↔EN que NO es fuga (marcas, jerga técnica, unidades)
  const NEUTRO = /^(aleph|mcp|api|url|json|http|https|ok|id|ui|ia|ai|cli|gpu|cpu|sdk|oauth|token|web|run|tool|tools|log|logs|error|status|beta|demo|dev|test|opus|sonnet|haiku|claude|openai|groq|github|google|stripe|gmail|drive|notion|slack|python|node|npm|git|docker|sql|csv|pdf|png|svg|css|html|js|ts)$/i;

  function visible(el) {
    const st = getComputedStyle(el);
    if (st.visibility === "hidden" || st.display === "none") return false;
    if (el.closest("[hidden]")) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 2 && r.height >= 2;
  }

  // por NODO DE TEXTO, no por elemento: así el string reportado es EXACTAMENTE la clave
  // que necesita el mapa TM (que traduce nodo por nodo, con trim).
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  let n;
  while ((n = w.nextNode())) {
    const el = n.parentElement;
    if (!el || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|TEXTAREA)$/.test(el.tagName)) continue;
    const txt = n.nodeValue.replace(/\s+/g, " ").trim();
    if (txt.length < 4) continue;
    if (NEUTRO.test(txt)) continue;
    if (el.closest("[data-no-tm]")) continue;      // contenido del usuario: la capa TM no lo toca
    if (!visible(el)) continue;
    if (!esEspanol(txt)) continue;
    if (seen.has(txt)) continue;
    seen.add(txt);
    out.push({ texto: txt.slice(0, 240), sel: el.id ? "#" + el.id : el.tagName.toLowerCase() + "." + String(el.className || "").split(/\s+/)[0] });
  }
  // los atributos que también se leen: placeholder y aria-label
  for (const el of document.querySelectorAll("[placeholder], [aria-label]")) {
    if (!visible(el) || el.closest("[data-no-tm]")) continue;
    for (const a of ["placeholder", "aria-label"]) {
      const v = (el.getAttribute(a) || "").trim();
      if (v.length < 4 || NEUTRO.test(v) || !esEspanol(v) || seen.has(v)) continue;
      seen.add(v);
      out.push({ texto: v.slice(0, 240), sel: (el.id ? "#" + el.id : el.tagName.toLowerCase()) + "[" + a + "]" });
    }
  }
  return out;
};

/* ─────────────────────── 6 · no queda un modo que aprender (§d) ───────────────────
 * El producto tenía DOS interruptores que partían la interfaz en dos versiones: la píldora
 * "Guiado | Técnico" (Taller + Preferencias) y el "⚙ Modo técnico" del ⋯ del Cuarto. Los dos
 * fallaban del mismo modo: el que no sabía que existían no veía nunca la mitad de la información,
 * y el que sí, tenía que elegir un modo ANTES de que hubiera algo que mirar.
 *
 * Se van los interruptores, NO la información. Lo que estaba detrás del modo queda:
 *   · la revisión de tools antes de equipar → siempre visible, todo marcado, [Continuar]
 *   · el detalle crudo (de dónde salió, qué validó el motor) → detrás del [?] (docs/guia, T6 §10)
 *     y de la evidencia
 *   · el system prompt en crudo y la config MCP a mano → detrás de "más", donde se usan
 *   · "Tu propio modelo" → en la lista de modelos, como cualquier otro
 *
 * Esta sonda mide las dos mitades: que el interruptor NO exista (censo estático sobre el árbol
 * servido) y que lo que protegía SÍ esté y no bloquee (DOM vivo del panel). */
const MODO_MUERTO = [
  { que: 'toggle "Modo técnico"', re: /Modo t[ée]cnico|manualBtn|manualState/ },
  { que: "panel de descarte de propuestas", re: /\bmpropbar\b|\bmpropList\b/ },
  { que: 'píldora "Guiado | Técnico"', re: /setTecnico|pickTecnico|isTecnico|tecnicoBtnStyle|tecnicoStyle/ },
  { que: 'estado de modo (mode === "tecnico")', re: /mode\s*===?\s*['"]tecnico['"]/ },
];
/* el toggle Guiado↔Código de la Mesa NO entra: no esconde nada — son dos renders del MISMO estado,
 * lado a lado, sin capacidad detrás. Lo que muere es el modo que RACIONA información. */
const MODO_FUERA = [/^cuarto\/mesa\./, /^verify_identidad_visual\.mjs$/];

function censoModo() {
  const hits = [];
  for (const abs of archivos(HERE)) {
    const rel = relative(HERE, abs).split("\\").join("/");
    if (MODO_FUERA.some((r) => r.test(rel))) continue;
    if (!/\.(html|js|mjs|css)$/.test(rel)) continue;
    // Los comentarios que EXPLICAN la remoción no son el interruptor: el interruptor es código.
    // Hay que seguir el estado de bloque (/* … */ y <!-- … -->) o la SEGUNDA línea de un comentario
    // de varias —que no empieza con ningún marcador— pasa por código y da un falso rojo.
    let enBloque = null;   // "js" | "html" | null
    fs.readFileSync(abs, "utf8").split(/\r?\n/).forEach((text, i) => {
      const t = text.trim();
      const eraBloque = enBloque;
      if (enBloque === "js" && t.includes("*/")) enBloque = null;
      else if (enBloque === "html" && t.includes("-->")) enBloque = null;
      else if (!enBloque) {
        if (t.startsWith("/*") && !t.includes("*/")) enBloque = "js";
        else if (t.startsWith("<!--") && !t.includes("-->")) enBloque = "html";
      }
      if (eraBloque) return;                                                 // adentro de un bloque
      if (t.startsWith("//") || t.startsWith("*") || t.startsWith("/*") || t.startsWith("<!--")) return;
      for (const m of MODO_MUERTO) if (m.re.test(text)) hits.push({ rel, line: i + 1, que: m.que, text: t.slice(0, 110) });
    });
  }
  return hits;
}

/* la otra mitad: lo que el modo protegía sigue ahí, visible y sin bloquear. */
const SONDA_REVISION = () => {
  const $ = (i) => document.getElementById(i);
  const rows = [...document.querySelectorAll("#msealbar .srow")];
  const ok = $("msealConfirm");
  return {
    visible: !!($("msealbar") && !$("msealbar").hidden),
    filas: rows.length,
    marcadas: rows.filter((r) => r.querySelector(".schk").checked).length,
    boton: ok ? ok.textContent.trim() : "",
    bloquea: !!(ok && ok.disabled),
    salida: !!$("msealCancel"),
    // [T6 §10] el detalle crudo se mudó a docs/guia: lo accesible ahora es el [?] estándar
    // (.qmark + data-guia) y el popover que abre. Se mide eso, que es la verdad de hoy.
    detalle: !!($("msealWhy") && $("msealWhy").classList.contains("qmark") &&
                $("msealWhy").dataset.guia && $("ayudapop") && !$("ayudapop").hidden),
    sinToggle: !$("manualBtn") && !$("manualState") && !$("mpropbar"),
  };
};

/* ─────────────────────── 2 · tipografías realmente usadas ─────────────────────── */
const SONDA_FUENTES = () => {
  const fam = new Map();
  for (const el of document.querySelectorAll("body *")) {
    let txt = "";
    for (const n of el.childNodes) if (n.nodeType === 3) txt += n.nodeValue;
    if (!txt.trim()) continue;
    const st = getComputedStyle(el);
    if (st.visibility === "hidden" || st.display === "none") continue;
    const f = st.fontFamily.split(",")[0].replace(/["']/g, "").trim();
    if (!fam.has(f)) fam.set(f, { n: 0, ej: txt.trim().slice(0, 30) });
    fam.get(f).n++;
  }
  return [...fam.entries()].map(([f, v]) => ({ familia: f, usos: v.n, ejemplo: v.ej })).sort((a, b) => b.usos - a.usos);
};

/* ─────────────────────── 3 · censo estático de literales ─────────────────────── */
const SKIP_DIRS = new Set(["vendor", "fonts", "node_modules", "screenshots", "uploads", ".git", "katex", "three"]);
const FUERA = [/^sala\/sala\.html$/];                       // un archivo, un dueño (terminal E)
const NOMBRES = ["white", "black", "red", "green", "blue", "yellow", "orange", "purple", "gray", "grey", "silver", "crimson", "gold", "pink", "tomato", "coral", "indigo", "violet", "magenta", "cyan"];
const LIT = new RegExp("#[0-9a-fA-F]{3,8}\\b|\\brgba?\\([^)]*\\)|\\bhsla?\\([^)]*\\)|(?<=[:\\s,(])(?:" + NOMBRES.join("|") + ")(?=[;\\s,)}'\"]|$)", "g");
const PROP_COLOR = /(^|[;{"'\s])(color|background|background-color|background-image|border|border-top|border-right|border-bottom|border-left|border-color|border-top-color|border-bottom-color|border-left-color|border-right-color|outline|outline-color|box-shadow|text-shadow|fill|stroke|caret-color|accent-color|text-decoration-color|column-rule|scrollbar-color|-webkit-text-fill-color)\s*:/i;
const DEF_TOKEN = /--[a-zA-Z0-9_-]+\s*:/;

function archivos(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name.startsWith(".")) continue;
    const p = join(dir, e.name);
    if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) archivos(p, out); }
    else if ([".html", ".js", ".css"].includes(extname(e.name))) out.push(p);
  }
  return out;
}

function censo() {
  const res = { defs: 0, usos: 0, fuera: 0, porArchivo: new Map(), detalle: [] };
  for (const f of archivos(HERE).sort()) {
    const rel = relative(HERE, f);
    const esFuera = FUERA.some((r) => r.test(rel));
    const src = fs.readFileSync(f, "utf8");
    src.split("\n").forEach((ln, i) => {
      const t = ln.trim();
      if (t.startsWith("*") || t.startsWith("//") || t.startsWith("/*")) return;
      const ms = ln.match(LIT);
      if (!ms) return;
      for (const m of ms) {
        const idx = ln.indexOf(m);
        const decl = ln.slice(0, idx).split(/[;{]/).pop();
        const esDef = DEF_TOKEN.test(decl);
        const esColor = PROP_COLOR.test(decl + ":") || PROP_COLOR.test(ln.slice(Math.max(0, idx - 80), idx + 1));
        if (esFuera) { if (!esDef && esColor) res.fuera++; continue; }
        if (esDef) res.defs++;
        else if (esColor) {
          res.usos++;
          res.porArchivo.set(rel, (res.porArchivo.get(rel) || 0) + 1);
          res.detalle.push({ rel, line: i + 1, lit: m, text: t.slice(0, 120) });
        }
      }
    });
  }
  return res;
}

/* ─────────────────────────────── main ─────────────────────────────── */
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log("  ✓", m); } else { fail++; console.log("  ✗", m); } };

async function main() {
  console.log("\n═══ 3 · CENSO DE LITERALES DE COLOR (§a) ═══");
  const c = censo();
  const top = [...c.porArchivo.entries()].sort((a, b) => b[1] - a[1]);
  for (const [rel, n] of top.slice(0, 14)) console.log(`   ${String(n).padStart(4)}  ${rel}`);
  if (top.length > 14) console.log(`   ...  (+${top.length - 14} archivos)`);
  console.log(`\n   definiciones de token : ${c.defs}   (legítimas — ahí nacen las variables)`);
  console.log(`   USOS hardcodeados     : ${c.usos}   ← los sitios que no giran con el tema`);
  console.log(`   fuera de alcance      : ${c.fuera}  (sala/sala.html · terminal E)`);
  if (process.env.DUMP) for (const d of c.detalle) if (d.rel.includes(process.env.DUMP)) console.log(`   ${d.rel}:${d.line} [${d.lit}] ${d.text}`);
  if (process.env.CENSO) return;

  /* El puerto es FIJO y el spawn va con stdio:"ignore": si otro proceso ya tiene :8188 —otra
   * sesión, otro worktree, un server que quedó colgado de una corrida anterior— el bind falla
   * EN SILENCIO y la sonda navega igual, midiendo EL ÁRBOL AJENO y firmando el veredicto como
   * si fuera el propio. Pasó: tres corridas seguidas dieron 44 pares bajo AA que no existían
   * en este árbol. Es el mismo hueco que el guard §g cierra adentro de la página, un piso más
   * abajo: primero hay que estar seguro de QUÉ servidor se está midiendo. */
  const ajeno = await fetch(`${BASE}/`, { method: "HEAD" }).then(() => true).catch(() => false);
  if (ajeno) {
    console.error(`\n✗ :${PORT} YA ESTÁ OCUPADO por otro proceso.`);
    console.error(`  Esta sonda mediría ese árbol y no el de acá. Liberá el puerto`);
    console.error(`  (lsof -nP -iTCP:${PORT} -sTCP:LISTEN) o corré con FRONT_PORT=<otro>.`);
    process.exit(2);
  }
  const srv = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1", "--directory", HERE], { stdio: "ignore" });
  await sleep(900);
  const propio = await fetch(`${BASE}/`, { method: "HEAD" }).then(() => true).catch(() => false);
  if (!propio) {
    console.error(`\n✗ el server propio no levantó en :${PORT} — nada que medir.`);
    try { srv.kill(); } catch {}
    process.exit(2);
  }
  const browser = await chromium.launch();
  const fallos = { light: [], dark: [] };
  const desvios = [];
  const tips = [];
  const familias = new Map();
  let revision = null;

  try {
    for (const s of SUPERFICIES) {
      if (process.env.SOLO && s.id !== process.env.SOLO) continue;
      for (const tema of ["dark", "light"]) {
        const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
        page.on("pageerror", () => {});
        await page.addInitScript((t) => {
          try { localStorage.setItem("aleph-theme", t); } catch (e) {}
          // sesión de verificación: sin esto Home y Métodos rebotan a Auth (ver cabecera)
          try {
            sessionStorage.setItem("puppet_user", JSON.stringify(
              { id: "u-verif", session_token: "tok-verif", email: "verif@aleph" }));
          } catch (e) {}
        }, tema);
        try {
          await page.goto(BASE + s.url, { waitUntil: "domcontentloaded", timeout: 25000 });
          await sleep(s.espera || 1400);
          // GUARD · una superficie que rebotó mide OTRA pantalla y su verde no vale nada
          const real = await page.evaluate(() => location.pathname);
          if (real !== s.url) desvios.push({ sup: s.id, tema, pedido: s.url, real });
          await page.evaluate((t) => {
            document.documentElement.setAttribute("data-theme", t);
            // las .dc.html pintan su propio data-theme en un div interno
            document.querySelectorAll("[data-theme]").forEach((n) => n.setAttribute("data-theme", t));
          }, tema);
          await sleep(450);
          for (const sel of (s.abrir || [])) {
            try { await page.click(sel, { timeout: 2500 }); await sleep(500); } catch (e) {}
          }
          if (s.evaluar) { try { await page.evaluate(s.evaluar); await sleep(400); } catch (e) {} }
          if (s.id === "CuartoRevision" && tema === "dark") revision = await page.evaluate(SONDA_REVISION);
          const malos = await page.evaluate(SONDA_CONTRASTE);
          for (const m of malos) fallos[tema].push({ sup: s.id, ...m });
          if (tema === "dark") for (const t of await page.evaluate(SONDA_TOOLTIPS)) tips.push({ sup: s.id, ...t });
          for (const f of await page.evaluate(SONDA_FUENTES)) {
            const k = f.familia;
            if (!familias.has(k)) familias.set(k, { usos: 0, donde: new Set(), ej: f.ejemplo });
            familias.get(k).usos += f.usos; familias.get(k).donde.add(s.id);
          }
        } catch (e) {
          console.log(`   ! ${s.id} (${tema}): ${String(e).split("\n")[0].slice(0, 100)}`);
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
    srv.kill();
  }

  // ── pasada de idioma: cada superficie cargada en INGLÉS, una sola vez ──
  const mezcla = [];
  {
    /* MISMO guard que :PORT, un piso más abajo — a este le faltaba (integración tanda-P).
     * La pasada de idioma usa PORT+1, y ESE bind también falla en silencio: con
     * FRONT_PORT=8289 el +1 cayó sobre un sidecar de esta misma sesión en :8290, que sirve
     * la app CON el catálogo. Resultado: 30 "españoles sueltos" que no son de este árbol y
     * un rojo que no existe. Guardar sólo el puerto principal deja la mitad del agujero. */
    const PORT2 = PORT + 1, BASE2 = `http://127.0.0.1:${PORT2}`;
    const ajeno2 = await fetch(`${BASE2}/`, { method: "HEAD" }).then(() => true).catch(() => false);
    if (ajeno2) {
      console.error(`\n✗ :${PORT2} (la pasada de idioma usa FRONT_PORT+1) YA ESTÁ OCUPADO.`);
      console.error(`  Mediría ESE árbol y no el de acá. Liberalo o corré con FRONT_PORT=<otro>`);
      console.error(`  eligiendo un par libre (lsof -nP -iTCP:${PORT2} -sTCP:LISTEN).`);
      try { srv.kill(); } catch {}
      process.exit(2);
    }
    const srv2 = spawn("python3", ["-m", "http.server", String(PORT2), "--bind", "127.0.0.1", "--directory", HERE], { stdio: "ignore" });
    await sleep(900);
    const propio2 = await fetch(`${BASE2}/`, { method: "HEAD" }).then(() => true).catch(() => false);
    if (!propio2) {
      console.error(`\n✗ el server propio no levantó en :${PORT2} — nada que medir en la pasada de idioma.`);
      try { srv2.kill(); } catch {}
      process.exit(2);
    }
    const br2 = await chromium.launch();
    try {
      for (const s of SUPERFICIES) {
        if (process.env.SOLO && s.id !== process.env.SOLO) continue;
        const page = await br2.newPage({ viewport: { width: 1440, height: 900 } });
        page.on("pageerror", () => {});
        await page.addInitScript(() => {
          try { localStorage.setItem("aleph-lang", "en"); localStorage.setItem("aleph-theme", "dark"); } catch (e) {}
          // misma sesión que la pasada de contraste: si no, Home y Métodos miden Auth en inglés
          try {
            sessionStorage.setItem("puppet_user", JSON.stringify(
              { id: "u-verif", session_token: "tok-verif", email: "verif@aleph" }));
          } catch (e) {}
        });
        try {
          await page.goto("http://localhost:" + (PORT + 1) + s.url, { waitUntil: "domcontentloaded", timeout: 25000 });
          await sleep((s.espera || 1400) + 800);   // el TM traduce por MutationObserver: hay que dejarlo pasar
          for (const sel of (s.abrir || [])) { try { await page.click(sel, { timeout: 2500 }); await sleep(600); } catch (e) {} }
          if (s.evaluar) { try { await page.evaluate(s.evaluar); await sleep(700); } catch (e) {} }
          for (const m of await page.evaluate(SONDA_IDIOMA)) mezcla.push({ sup: s.id, ...m });
        } catch (e) {
          console.log("   ! idioma " + s.id + ": " + String(e).split("\n")[0].slice(0, 90));
        }
        await page.close();
      }
    } finally { await br2.close(); srv2.kill(); }
  }
  console.log("\n═══ 6 · NO QUEDA UN MODO QUE APRENDER (§d) ═══");
  const modo = censoModo();
  for (const h of modo) console.log(`   ${h.rel}:${h.line}  [${h.que}]  ${h.text}`);
  ok(modo.length === 0, `ningún interruptor de modo en el árbol servido (${modo.length} sitios)`);
  const rv = revision || {};
  console.log(`   revisión antes de equipar: visible=${rv.visible} filas=${rv.filas} ` +
    `marcadas=${rv.marcadas} botón="${rv.boton}" bloquea=${rv.bloquea} salida=${rv.salida} ` +
    `detalle_tras_el_?=${rv.detalle} sin_toggle=${rv.sinToggle}`);
  ok(rv.visible === true && rv.filas > 0 && rv.marcadas === rv.filas && rv.bloquea === false && rv.salida === true,
    `la revisión de tools aparece sola, con todo marcado y sin bloquear (${rv.marcadas}/${rv.filas})`);
  ok(rv.detalle === true && rv.sinToggle === true,
    "el detalle crudo sigue accesible — detrás del [?] estándar (docs/guia), no de un modo");

  console.log("\n═══ 5 · IDIOMA MEZCLADO — español visible con la UI en inglés (§f) ═══");
  for (const m of mezcla) console.log(`   ${m.sup.padEnd(11)} ${m.sel.padEnd(22)} "${m.texto}"`);
  ok(mezcla.length === 0, `sin español suelto con la UI en inglés (${mezcla.length})`);

  console.log("\n═══ 4 · TOOLTIPS QUE TAPAN LO QUE DESCRIBEN (§e) ═══");
  for (const t of tips) console.log(`   ${t.sup.padEnd(11)} ${t.sel.padEnd(24)} title="${t.title}"  ya dice: “${t.texto}”${t.enMenu ? "  [dentro de un menú]" : ""}`);
  ok(tips.length === 0, `ningún title redundante (${tips.length})`);

  console.log("\n═══ 2 · TIPOGRAFÍAS COMPUTADAS (§c) ═══");
  const fs2 = [...familias.entries()].sort((a, b) => b[1].usos - a[1].usos);
  for (const [f, v] of fs2) console.log(`   ${String(v.usos).padStart(5)}  ${f.padEnd(24)} ${[...v.donde].join(" ")}`);
  const PERMITIDAS = ["Hanken Grotesk", "Spectral", "ui-monospace", "SFMono-Regular", "monospace", "Menlo"];
  const sueltas = fs2.filter(([f]) => !PERMITIDAS.includes(f));
  ok(sueltas.length === 0, `una sola tipografía + su escala (familias sueltas: ${sueltas.map((s) => s[0]).join(", ") || "ninguna"})`);

  /* FUERA DE ALCANCE POR ORDEN — no son deuda tapada, son territorio ajeno:
   *   · las cinco filas de filtros del catálogo de EQUIPAR PIEZA (#fGroup #fZone #fType
   *     #fKind #fKey): se eliminan en la reforma R, pulirlas es trabajo tirado.
   *   · sala/sala.html: un archivo, un dueño (terminal E).
   * Se listan igual, para que el pase que las toque sepa qué encontrar. */
  const EXCLUIDO = /#(fGroup|fZone|fType|fKind|fKey)\b/;

  console.log("\n═══ 1 · CONTRASTE WCAG AA EN AMBOS TEMAS (§b) ═══");
  const gate = { dark: [], light: [] };
  for (const tema of ["dark", "light"]) {
    const excl = fallos[tema].filter((m) => EXCLUIDO.test(m.ruta));
    gate[tema] = fallos[tema].filter((m) => !EXCLUIDO.test(m.ruta));
    console.log(`\n  ── ${tema.toUpperCase()} · ${gate[tema].length} pares bajo el mínimo ──`);
    for (const m of gate[tema].slice(0, 40)) {
      console.log(`   ${String(m.ratio).padStart(5)}:1 (min ${m.min})  ${m.sup.padEnd(11)} ${m.fg} sobre ${m.bg}  ${m.ruta}`);
      console.log(`             “${m.texto}”`);
    }
    if (gate[tema].length > 40) console.log(`   ... y ${gate[tema].length - 40} más`);
    for (const m of excl) console.log(`   [fuera de alcance] ${m.ratio}:1  ${m.sup} ${m.ruta}  “${m.texto}”`);
  }
  ok(gate.dark.length === 0, `oscuro sin texto bajo AA (${gate.dark.length})`);
  ok(gate.light.length === 0, `claro sin texto bajo AA (${gate.light.length})`);

  /* ═══ 0 · CADA SUPERFICIE MIDE LA QUE DICE (§g) ═══
   * El verde de esta sonda vale exactamente lo que valga esta línea: una superficie que
   * rebota a otra URL se mide igual, sin avisar, y su "0 pares bajo el mínimo" significa
   * "no había nada que medir". Fue el caso de Home y Métodos, que rebotaban a /Auth.dc.html
   * y devolvían el contraste de Auth tres veces. */
  console.log("\n═══ 0 · CADA SUPERFICIE MIDE LA QUE DICE (§g) ═══");
  for (const d of desvios) console.log(`   ✗ ${d.sup} (${d.tema}): pidió ${d.pedido} y midió ${d.real}`);
  ok(desvios.length === 0, `ninguna superficie rebotó a otra pantalla (${desvios.length})`);
  if (process.env.REPORTE) fs.writeFileSync(process.env.REPORTE, JSON.stringify({ fallos, mezcla, tips, modo, revision, familias: fs2.map(([f, v]) => ({ familia: f, usos: v.usos, donde: [...v.donde] })), censo: { defs: c.defs, usos: c.usos, fuera: c.fuera, porArchivo: [...c.porArchivo.entries()] } }, null, 1));

  console.log(`\n${fail === 0 ? "VERDE" : "ROJO"} — ${pass} ok · ${fail} fallos`);
  process.exit(fail === 0 ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(1); });
