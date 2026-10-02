/* territorio.js — STEP 4 · 4B · los 4 TERRITORIOS de La Sala (clases de capacidad).
 *
 * Un TERRITORIO es la LENTE con la que La Sala narra un run. Se DERIVA del cinturón:
 * cada pieza (belt card) → una categoría de dominio → uno de 4 territorios. La unión sobre
 * las piezas = los territorios que el cinturón HABILITA; los demás quedan 🔒 (con guía al
 * catálogo). El territorio NO cambia los datos del run — sólo re-tiñe la narrativa (presentación).
 *
 * POR QUÉ una tabla propia y no `categoryOf()` de cuarto.icons.js: reader C (recon 4B) probó que
 * `categoryOf()` MISCLASIFICA los servers de finanzas/datos por el round-trip de glyph (coingecko→
 * pagos, chart→financiero, datatools→documentos). La fuente de verdad curada son los COMENTARIOS-
 * SECCIÓN de SERVER_ICON — acá los materializamos como tabla server→territorio explícita. Para
 * servers FORJADOS/desconocidos caemos a categoría-por-keyword. Self-contained (classic script →
 * window.Territorio) para que el script clásico de sala.html lo lea sin fricción ESM.
 *
 * Cero PII, cero red, puro. Idempotente.
 */
(function () {
  "use strict";

  // ── los 4 territorios · orden = prioridad de desempate del default ────────────
  var ORDER = ["cuantitativo", "fisico", "conocimiento", "operativo"];
  var META = {
    cuantitativo: { key: "cuantitativo", label: "Cuantitativo", glyph: "📈",
      sub: "números, finanzas, datos, cálculo" },
    fisico:       { key: "fisico",       label: "Físico",       glyph: "🧊",
      sub: "CAD, simulación, medicina, electrónica, mapas" },
    conocimiento: { key: "conocimiento", label: "Conocimiento", glyph: "📚",
      sub: "investigación, documentos, escritura, ML" },
    operativo:    { key: "operativo",    label: "Operativo",    glyph: "⚙️",
      sub: "correo, mensajería, calendario, pagos, automatización" }
  };

  // ── tabla CURADA server→territorio (de los comentarios-sección de SERVER_ICON) ─
  var SERVER = {
    // Financiero → cuantitativo
    alphavantage: "cuantitativo", yfinance: "cuantitativo", backtest: "cuantitativo",
    broker: "cuantitativo", ccxt: "cuantitativo", coingecko: "cuantitativo",
    fred: "cuantitativo", massive: "cuantitativo", secedgar: "cuantitativo", precio: "cuantitativo",
    // Datos / DB + cómputo → cuantitativo
    datatools: "cuantitativo", excel: "cuantitativo", sheets: "cuantitativo",
    stata: "cuantitativo", chart: "cuantitativo", calc: "cuantitativo",
    sympy: "cuantitativo", units: "cuantitativo", pysandbox: "cuantitativo",
    jupyter: "cuantitativo", script_runner: "cuantitativo", worldbank: "cuantitativo",
    // Físico / Espacial (CAD, simulación, electrónica, medicina, mapas, materiales)
    freecad: "fisico", materialsproject: "fisico", onshape: "fisico", openbom: "fisico",
    fem: "fisico", openfoam: "fisico", kicad: "fisico", spice: "fisico",
    dicom: "fisico", segmentacion: "fisico", biomcp: "fisico", openfda: "fisico",
    // Conocimiento (académico, búsqueda, documentos, escritura, ML)
    arxiv: "conocimiento", crossref: "conocimiento", openalex: "conocimiento",
    orcid: "conocimiento", pubmed: "conocimiento", zotero: "conocimiento",
    zenodo: "conocimiento", osf: "conocimiento",
    exa: "conocimiento", fetch: "conocimiento", wikipedia: "conocimiento",
    pandoc: "conocimiento", google_drive: "conocimiento", filesystem: "conocimiento",
    context7: "conocimiento", huggingface: "conocimiento", notion: "conocimiento",
    canvas: "conocimiento", classroom: "conocimiento", moodle: "conocimiento",
    // Operativo (correo, mensajería, calendario, pagos, automatización, escritura-al-mundo)
    gmail: "operativo", slack: "operativo", google_calendar: "operativo",
    github: "operativo", asana: "operativo", linear: "operativo", hubspot: "operativo",
    credprobe: "operativo"
    // echo, custom, forjados desconocidos → null (neutral, no fuerzan territorio)
  };

  // ── 21 categorías madre → territorio (fallback + huérfanas decididas) ──────────
  var CATEGORY = {
    financiero: "cuantitativo", datos: "cuantitativo",
    cad: "fisico", simulacion: "fisico", electronica: "fisico", medico: "fisico", mapas: "fisico",
    academico: "conocimiento", busqueda: "conocimiento", documentos: "conocimiento",
    escritura: "conocimiento",
    email: "operativo", mensajeria: "operativo", calendario: "operativo",
    pagos: "operativo", automatizacion: "operativo",
    // huérfanas §4 (reader C): decididas
    media: "conocimiento", codigo: "conocimiento", ml_ia: "conocimiento",
    comunicacion: "operativo"
    // custom → null (neutral)
  };

  // ── fallback por keyword para servers FORJADOS/desconocidos (substring, 1er hit) ─
  // Fragmentos ESPECÍFICOS (substring, 1er hit). NO incluir 3-char genéricos (map/data/coin) que
  // sobre-matchean slugs forjados ajenos (roadmap→fisico, datadog→cuantitativo): mejor caer a
  // neutral que FALSE-ENABLE un territorio. Los servers reales viven en la tabla curada SERVER.
  var KEYWORDS = [
    ["cuantitativo", ["stock", "price", "precio", "finance", "financ", "trade", "trading",
      "crypto", "market", "fred", "excel", "sheet", "csv", "sql", "quant", "backtest",
      "ledger", "invoice", "accounting", "contab", "calc", "statistic", "estadist", "datos", "dataset", "database"]],
    ["fisico", ["cad", "mesh", "fem", "simul", "openfoam", "cfd", "kicad", "spice", "circuit",
      "electron", "dicom", "medic", "segment", "material", "geometr", "mapa", "onshape"]],
    ["conocimiento", ["arxiv", "paper", "research", "wiki", "search", "busqueda", "doc", "pdf",
      "escrib", "write", "note", "zotero", "cite", "cita", "knowledge", "saber", "rag", "model",
      "hugging", "academ", "escuela", "curso", "lms"]],
    ["operativo", ["email", "mail", "gmail", "slack", "message", "mensaje", "calendar", "calendario",
      "event", "pay", "pago", "notif", "send", "envi", "deploy", "github", "gitlab", "issue",
      "crm", "hubspot", "automat", "workflow", "zapier"]]
  ];

  var FORGE_PREFIX = /^(forged|resolved)[-:_]/i;
  function _norm(s) { return String(s == null ? "" : s).trim().toLowerCase(); }

  function _keyword(slug) {
    var s = _norm(slug).replace(FORGE_PREFIX, "");
    if (!s) return null;
    for (var i = 0; i < KEYWORDS.length; i++) {
      var terr = KEYWORDS[i][0], frags = KEYWORDS[i][1];
      for (var j = 0; j < frags.length; j++) { if (s.indexOf(frags[j]) >= 0) return terr; }
    }
    return null;
  }

  /* ofCard(card) → territorio key | null (neutral). card = belt card
   * {backed_by, id, connector, category?, tools?}. Prioridad: server curado → connector curado →
   * categoría declarada → keyword del slug. null = pieza territory-agnóstica (no fuerza lente). */
  function ofCard(card) {
    if (!card) return null;
    var server = _norm(card.backed_by || card.id || card.server);
    var connector = _norm(card.connector);
    if (server && SERVER[server]) return SERVER[server];
    if (connector && SERVER[connector]) return SERVER[connector];
    // categoría explícita si la card la trae (ej. inspección la adjunta)
    var cat = _norm(card.category);
    if (cat && CATEGORY[cat]) return CATEGORY[cat];
    return _keyword(server) || _keyword(connector) || null;
  }

  /* forBelt(cards) → { enabled:[terr…], counts:{terr:n}, suggested:terr|"general", neutral:n }.
   * enabled = territorios con ≥1 pieza; suggested = el DOMINANTE (desempate por ORDER); si el
   * cinturón no habilita ninguno (todo neutral/vacío) → suggested "general" (esqueleto neutro). */
  function forBelt(cards) {
    cards = Array.isArray(cards) ? cards : [];
    var counts = {}, neutral = 0;
    cards.forEach(function (c) {
      var t = ofCard(c);
      if (t) counts[t] = (counts[t] || 0) + 1; else neutral++;
    });
    var enabled = ORDER.filter(function (t) { return counts[t] > 0; });
    var suggested = "general", best = 0;
    ORDER.forEach(function (t) { if ((counts[t] || 0) > best) { best = counts[t]; suggested = t; } });
    return { enabled: enabled, counts: counts, suggested: suggested, neutral: neutral };
  }

  function meta(key) { return META[key] || null; }
  function isTerritorio(key) { return ORDER.indexOf(key) >= 0; }

  window.Territorio = {
    ORDER: ORDER.slice(), META: META,
    meta: meta, isTerritorio: isTerritorio,
    ofCard: ofCard, forBelt: forBelt,
    _tables: { SERVER: SERVER, CATEGORY: CATEGORY, KEYWORDS: KEYWORDS }  // seam de test
  };
})();
