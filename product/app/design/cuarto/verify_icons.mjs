/* verify_icons.mjs — TEST EN FRÍO de cuarto.icons.js (headless: sin render, sin backend,
 * sin browser). Corre con:  node verify_icons.mjs   (desde product/app/design/cuarto).
 *
 * Cubre:
 *   (A) EXISTENCIA LUCIDE — cada glifo que el módulo puede emitir existe en
 *       lucide-static@1.21.0. Se chequea contra un set VERIFICADO embebido (frozen) y,
 *       si hay una lista autoritativa a mano ($LUCIDE_NAMES o /tmp/lucide_names.txt),
 *       se re-valida en vivo contra ella.
 *   (B) MATRIZ DE RESOLUCIÓN — un toolData de ejemplo por categoría madre + casos de
 *       forjado/resuelto/BYO + armario + default. Imprime entrada → ícono y asserta.
 */
import { readFileSync, existsSync } from "node:fs";
import {
  resolveIcon, categoryOf, GALLERY,
  MOTHER_ICON, LEVEL2, ALL_ICONS, ICON_PATHS,
} from "./cuarto.icons.js";

let fail = 0;
const ok = (c, msg) => { if (!c) { fail++; console.log("  ✗ " + msg); } };

// ── (A) EXISTENCIA LUCIDE ─────────────────────────────────────────────────────────────
// Set verificado en frío contra el árbol de archivos de lucide-static@1.21.0 (1986 glifos).
// Superconjunto de lo que el módulo emite; incluye alias deprecados aún presentes.
const VERIFIED_1_21_0 = new Set([
  "activity","at-sign","atom","axis-3d","banknote","bar-chart","bar-chart-3","battery",
  "beaker","binoculars","blocks","bolt","bone","book-marked","book-open","bot","box","boxes",
  "braces","brain","brain-circuit","briefcase","calculator","calendar","calendar-check",
  "calendar-clock","calendar-days","camera","candlestick-chart","chart-bar","chart-candlestick",
  "chart-column","chart-line","check-square","circuit-board","clapperboard","clock","code",
  "cog","coins","compass","component","cpu","credit-card","cross","database","dollar-sign",
  "feather","file","file-spreadsheet","file-text","files","film","flask-conical","flask-round",
  "folder","folder-open","folder-tree","function-square","gauge","git-branch",
  "git-commit-horizontal","git-fork","git-pull-request","globe","graduation-cap","grid-3x3",
  "hand-coins","hash","heart-pulse","id-card","image","inbox","kanban","key-round","landmark",
  "layers","layers-2","library","line-chart","list-checks","mail","mail-open","map","map-pin",
  "megaphone","message-circle","message-square","microchip","microscope","music","navigation",
  "network","notebook","notebook-pen","notebook-text","package","package-2","pen-line",
  "pencil","pencil-ruler","phone","pill","plug","podcast","puzzle","radio","radio-tower",
  "receipt","repeat","rotate-3d","rss","ruler","scan","scan-line","scan-search","search",
  "send","server","settings","shapes","sheet","shield-check","sigma","sparkles","square-check",
  "square-function","square-terminal","stethoscope","table","telescope","terminal","test-tube",
  "trending-up","type","users","video","wallet","waves","wind","workflow","wrench","zap",
]);

console.log("(A) EXISTENCIA LUCIDE — " + ALL_ICONS.length + " glifos emitibles vs lucide-static@1.21.0");
for (const g of ALL_ICONS) ok(VERIFIED_1_21_0.has(g), `glifo emitido NO verificado: "${g}"`);

// re-chequeo autoritativo en vivo si hay lista a mano (no requerido para pasar)
const authPath = process.env.LUCIDE_NAMES || "/tmp/lucide_names.txt";
if (existsSync(authPath)) {
  const live = new Set(readFileSync(authPath, "utf8").split(/\r?\n/).map(s => s.trim()).filter(Boolean));
  const missing = ALL_ICONS.filter(g => !live.has(g));
  console.log(`    [live] re-validado contra ${authPath} (${live.size} nombres) → ` +
    (missing.length ? "FALTAN: " + missing.join(", ") : "todos existen ✓"));
  for (const g of missing) ok(false, `glifo NO existe en lista autoritativa: "${g}"`);
} else {
  console.log("    [live] (sin lista autoritativa a mano — solo set embebido)");
}
console.log("    " + (fail ? `${fail} fallos` : "todos los glifos existen ✓") + "\n");

// ── (A2) COBERTURA ICON_PATHS — cada glifo emitible tiene markup vendored (el draw nunca cae
// a vacío); `puzzle` (fallback duro del draw) existe. ──
console.log("(A2) COBERTURA ICON_PATHS — markup vendored (lucide-static@1.21.0)");
const noPath = ALL_ICONS.filter((g) => !ICON_PATHS[g]);
ok(noPath.length === 0, "sin markup: " + noPath.join(", "));
ok(!!ICON_PATHS.puzzle, "puzzle (fallback duro del draw) debe existir");
console.log(`    ${Object.keys(ICON_PATHS).length} paths · cubren ${ALL_ICONS.length} glifos emitibles · ` +
  (noPath.length ? "FALTAN " + noPath.join(",") : "cobertura completa ✓") + "\n");

// ── (B) MATRIZ DE RESOLUCIÓN ──────────────────────────────────────────────────────────
// cada caso: etiqueta, toolData, ícono esperado, vía de la cadena que debería disparar.
const CASES = [
  // (1) server conocido — una por categoría madre con server real
  ["financiero · alphavantage",  { server: "alphavantage", tools: ["yfinance_get_ticker_info"] }, "chart-candlestick", "1·server"],
  ["documentos · pandoc",        { server: "pandoc", tools: ["convert-contents"] },               "file-text",         "1·server"],
  ["academico · arxiv",          { server: "arxiv", tools: ["arxiv_search"] },                     "graduation-cap",    "1·server"],
  ["busqueda · exa",             { server: "exa", tools: ["exa_search"] },                         "search",            "1·server"],
  ["datos · datatools",          { server: "datatools", tools: ["write_xlsx"] },                   "table",             "1·server"],
  ["medico · dicom",             { server: "dicom", tools: ["query_patients"] },                   "scan",              "1·server"],
  ["cad · freecad",              { server: "freecad", tools: ["create_object"] },                  "box",               "1·server"],
  ["simulacion · openfoam",      { server: "openfoam", tools: ["analyze_external_flow"] },         "wind",              "1·server"],
  ["electronica · kicad",        { server: "kicad", tools: ["create_schematic"] },                 "circuit-board",     "1·server"],
  ["codigo · github",            { server: "github", tools: ["github_list_repos"] },               "git-branch",        "1·server"],
  ["ml_ia · huggingface",        { server: "huggingface", tools: ["paper_search"] },               "brain",             "1·server"],
  ["email · gmail",              { server: "gmail", tools: ["create_draft"] },                     "mail",              "1·server"],
  ["mensajeria · slack",         { server: "slack", tools: ["post_message"] },                     "message-square",    "1·server"],
  ["calendario · google_calendar",{ server: "google_calendar", tools: ["list_events"] },           "calendar",          "1·server"],
  ["simulacion · sympy",         { server: "sympy", tools: ["simplify"] },                         "sigma",             "1·server"],
  ["medico · segmentacion",      { server: "segmentacion", tools: ["segment_structure"] },         "bone",              "1·server"],
  ["automatizacion · credprobe", { server: "credprobe", tools: ["probe"] },                        "key-round",         "1·server"],

  // (2) connector conocido (sin server en tabla)
  ["escritura · notion",         { connector: "notion", auth: "oauth", tools: ["create_page"] },   "notebook-text",     "2·connector"],
  ["crm · hubspot",              { connector: "hubspot", auth: "oauth" },                          "users",             "2·connector"],
  ["pm · linear",                { connector: "linear", auth: "token" },                           "kanban",            "2·connector"],
  ["academico · orcid",          { connector: "orcid", auth: "oauth" },                            "id-card",           "2·connector"],

  // (3) slug forjado/resuelto → categoría madre  (cubre media, pagos, mapas, comunicacion)
  ["media · forged-tmdb",        { server: "forged-tmdb", tools: ["get_movie_details"] },          "film",              "3·forge→cat"],
  ["pagos · resolved-stripe",    { server: "resolved-stripe", tools: ["create_charge"] },          "credit-card",       "3·forge→cat"],
  ["mapas · resolved:mapbox",    { server: "resolved:mapbox", tools: ["geocode_address"] },        "map",               "3·forge→cat"],
  ["comunicacion · forged-rss",  { server: "forged-rss-feed", tools: ["list_items"] },             "radio",             "3·forge→cat"],
  ["universal · server sin tabla (spotify)", { server: "spotify", tools: ["xx"] },                 "film",              "3·named→cat"],

  // (4) keywords de tools[] (forjado sin slug-categoría → mira las tools)
  ["tools · send_/draft → mail", { server: "forged-x7", tools: ["send_message", "draft_email"] },  "mail",              "4·tools"],
  ["tools · quote → financiero", { tools: ["quote_bom", "quote_component"] },                       "trending-up",       "4·tools"],
  ["tools · schematic → elec",   { tools: ["create_schematic", "add_wire"] },                       "cpu",               "4·tools"],
  ["tools · run_python → code",  { tools: ["run_python"] },                                         "terminal",          "4·tools"],
  ["tools · windowing → medico", { server: "forged-z", tools: ["windowing", "query_studies"] },     "heart-pulse",       "4·tools"],

  // (5) armario (5 cubos) — fallback grueso cuando nada antes matchea
  ["armario · mundo",            { server: "forged-zzz", tools: ["frobnicate"], armario: "mundo" },  "globe",            "5·armario"],
  ["armario · datos",            { tools: ["frobnicate"], armario: "datos" },                        "database",        "5·armario"],
  ["armario · saberes",          { tools: ["frobnicate"], armario: "saberes" },                      "book-open",       "5·armario"],

  // (6) DEFAULT → puzzle (+ galería)
  ["default · desconocido total",{ server: "forged-qqq", tools: ["frobnicate"] },                   "puzzle",           "6·default"],
  ["default · vacío",            {},                                                                 "puzzle",           "6·default"],
];

console.log("(B) MATRIZ DE RESOLUCIÓN — entrada → ícono");
const pad = (s, n) => (s + " ".repeat(n)).slice(0, n);
for (const [label, input, expect, via] of CASES) {
  const got = resolveIcon(input);
  const pass = got === expect;
  if (!pass) fail++;
  console.log(`  ${pass ? "✓" : "✗"} ${pad(label, 38)} → ${pad(got, 20)} [${via}]` +
    (pass ? "" : `  ESPERADO ${expect}`));
}

// ── (C) helpers auxiliares ────────────────────────────────────────────────────────────
console.log("\n(C) helpers");
ok(MOTHER_ICON.custom === "puzzle", "custom debe ser puzzle");
ok(Object.keys(MOTHER_ICON).length === 21, "deben ser 21 categorías madre");
ok(Object.keys(LEVEL2).length === 21, "deben ser 21 grupos de variantes");
for (const [k, list] of Object.entries(LEVEL2)) {
  ok(list.length >= 3 && list.length <= 5, `${k}: 3-5 variantes (tiene ${list.length})`);
  ok(list[0] === MOTHER_ICON[k], `${k}: 1ra variante == glifo madre`);
}
ok(GALLERY("medico")[0] === "heart-pulse", "GALLERY por clave");
ok(GALLERY("heart-pulse")[0] === "heart-pulse", "GALLERY por glifo madre");
ok(categoryOf({ server: "dicom" }) === "medico", "categoryOf server conocido");
ok(categoryOf({ server: "forged-tmdb" }) === "media", "categoryOf forjado");
ok(categoryOf({ server: "totalmente-raro-xyz" }) === "custom", "categoryOf default→custom");
console.log("  " + (fail ? "(ver fallos arriba)" : "helpers ok ✓"));

// ── veredicto ─────────────────────────────────────────────────────────────────────────
console.log("\n" + (fail === 0
  ? "DONE-BAR · VERDE — " + (ALL_ICONS.length) + " glifos verificados, " + CASES.length + " casos de resolución, helpers ok"
  : `DONE-BAR · ROJO — ${fail} fallo(s)`));
process.exit(fail === 0 ? 0 : 1);
