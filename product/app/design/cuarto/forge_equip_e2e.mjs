/* forge_equip_e2e.mjs — DONE-BAR de 1b-equipar · el seam emit→EQUIPAR end-to-end, en el browser.
 *
 * Prueba, contra un backend REAL (puerto propio, NO :8091; cerebro Groq), que el MCP que forja
 * el Motor B (POST /v1/inspect/forge → mcp.forjado) se vuelve una PIEZA REAL del Cuarto, equipable
 * y usable en RUN. Los 4 asserts del contrato de la tarea:
 *
 *   (a) tras mcp.forjado real, la pieza tiene server≠null + belt_ref + puppet_id (NO hueca);
 *   (b) sus tools = las validadas (tool.validada) que sobrevivieron;
 *   (c) se equipa y un RUN real la invoca con éxito (handoff belt_ref → runtime);
 *   (d) el modelo de relaciones del Cuarto NO se mutó (mismo contrato: ida+eco al Núcleo).
 *
 * (c) corre por el camino SÍNCRONO /v1/puppets/run (mismo assemble_and_run que el botón RUN)
 * a propósito: la cola de /v1/runs/enqueue es POSTGRES COMPARTIDA y un worker ajeno (:8080)
 * robaría el job → no-determinista. El sync corre INLINE en ESTE backend → determinista y con
 * el belt forjado en ESTE worktree. Es el mismo handoff (belt_resolver → runtime), sin teatro.
 *
 * Uso (lo orquesta run_forge_equip_verify.sh, que levanta backend+serve.py en puertos libres):
 *   FORGE_E2E_BASE=http://localhost:PORT FORGE_E2E_TMDB_KEY=… node forge_equip_e2e.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.FORGE_E2E_BASE || "http://localhost:8232";
const TMDB_KEY = process.env.FORGE_E2E_TMDB_KEY || "";
const PUPPET_ID = process.env.FORGE_E2E_PUPPET || "pup-verify-1b-equipar-001";
const PAGE_URL = `${BASE}/cuarto/cuarto.pixi.html?puppet=${encodeURIComponent(PUPPET_ID)}`;

const RELATION_KINDS = new Set(["ida", "eco", "permanent", "enables", "gate"]);
const fail = (m) => { console.error("FATAL:", m); process.exit(2); };
if (!TMDB_KEY) fail("falta FORGE_E2E_TMDB_KEY (token del target TMDB).");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1320, height: 880 } });
const consoleErrors = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
page.on("pageerror", (e) => consoleErrors.push("PAGEERROR: " + String(e)));

await page.goto(PAGE_URL, { waitUntil: "load" });
await page.waitForFunction(() => window.__cuarto, null, { timeout: 12000 });

// ── snapshot del modelo ANTES de forjar (para probar que el alta entra por la vía normal) ──
const modelBefore = await page.evaluate(() => window.__cuarto.relationModel());

// ── 1) disparar la forja por la UI: ＋ Sumar tu MCP → modo "API cruda (URL + key)" ──
await page.click("#byoBtn");
await page.click('#byoTransport button[data-v="forge"]');
await page.waitForSelector('.byoFields[data-mode="forge"]:not([hidden])', { timeout: 4000 });
await page.fill("#byoFgUrl", "https://api.themoviedb.org/3");
await page.fill("#byoFgKey", TMDB_KEY);
await page.selectOption("#byoFgWhere", "query");
await page.fill("#byoFgParam", "api_key");
await page.fill("#byoFgValidate", "/configuration");
await page.fill("#byoLabel", "TMDB");
console.log("· forjando TMDB en vivo (Motor B + Groq)… puede tardar ~30-90s");
await page.click("#byoSubmit");

// el forge SSE corre el motor entero; esperamos a que el seam deje su resultado.
await page.waitForFunction(() => window.__lastForge !== undefined, null, { timeout: 240000 });
const forge = await page.evaluate(() => window.__lastForge);
if (!forge || !forge.ok) fail(`la forja no produjo pieza usable: ${forge && forge.reason}`);

// ── la PIEZA REAL tal cual quedó colocada en el Cuarto (de placedTiles, no del retorno) ──
const piece = await page.evaluate(() => {
  const t = window.__cuarto.placedTiles().find((x) => x.forged);
  return t || null;
});
if (!piece) fail("no encontré la pieza forjada en placedTiles()");

// ── ASSERT (a) — pieza NO hueca ───────────────────────────────────────────────────────
const a = !!piece.server && !!piece.belt_ref && !!piece.puppet_id && Array.isArray(piece.tools) && piece.tools.length > 0;

// ── ASSERT (b) — tools de la pieza = las validadas ──────────────────────────────────────
const validatedNames = new Set((forge.stats && forge.stats.validatedNames) || []);
const forjadoTools = (forge.forjado && forge.forjado.tools) || [];
const allInValidated = piece.tools.every((t) => validatedNames.has(t));
const matchesForjado = JSON.stringify([...piece.tools].sort()) === JSON.stringify([...forjadoTools].sort());
const b = piece.tools.length > 0 && allInValidated && matchesForjado;

// ── ASSERT (d) — modelo NO mutado: contrato intacto + la pieza entró por la vía normal ──
const modelAfter = await page.evaluate(() => window.__cuarto.relationModel());
const kindsOk = modelAfter.relationships.every((r) => RELATION_KINDS.has(r.kind));
const pieceInModel = modelAfter.pieces.find((p) => p.id === piece.id);
const idas = modelAfter.relationships.filter((r) => r.kind === "ida" && r.to === piece.id);
const ecos = modelAfter.relationships.filter((r) => r.kind === "eco" && r.from === piece.id);
const noToolToTool = !modelAfter.relationships.some(
  (r) => (r.kind === "ida" && r.from !== "nucleo") || (r.kind === "eco" && r.to !== "nucleo"));
// las piezas que YA existían no cambiaron de forma (mismo contrato {id,type,role})
const shapeOk = modelAfter.pieces.every((p) => "id" in p && "type" in p && "role" in p);
const d = kindsOk && !!pieceInModel && pieceInModel.type === "tool"
  && idas.length === 1 && ecos.length === 1 && noToolToTool && shapeOk;

// ── ASSERT (c) — RUN real invoca la pieza (handoff belt_ref → runtime) ──────────────────
// receta REAL del Cuarto (la misma que arma el botón RUN), con cerebro Groq para tool-use.
const runOut = await page.evaluate(async ({ tools }) => {
  const c = window.__cuarto;
  c.nucleoData().model = "oss";              // Groq gpt-oss-120b — hace tool-use (el shim Opus rehúsa)
  window.__sync();                            // recompila la receta viva con el modelo nuevo
  const recipe = window.__lastRecipe;         // la MISMA receta que arma el botón RUN (tilesToRecipe)
  // elegí una tool del set REAL forjado y dale un argumento concreto y verdadero, para que la
  // llamada EJECUTE contra TMDB y devuelva data real (no se quede pidiendo aclaraciones).
  const pick = (re) => tools.find((t) => re.test(t));
  let aTool, hint;
  const noArg = pick(/popular|genre_list|trending|now_playing|top_rated|upcoming|discover/i);
  if (pick(/get_movie_details/)) { aTool = "get_movie_details"; hint = "con movie_id=550 (Fight Club)"; }
  else if (pick(/movie_release_dates/)) { aTool = pick(/movie_release_dates/); hint = "con movie_id=550"; }
  else if (pick(/person_details/)) { aTool = pick(/person_details/); hint = "con person_id=287 (Brad Pitt)"; }
  else if (pick(/tv_details|tv_aggregate/)) { aTool = pick(/tv_details|tv_aggregate/); hint = "con tv_id=1399 (Game of Thrones)"; }
  else if (noArg) { aTool = noArg; hint = "(no necesita argumentos)"; }
  else { aTool = tools[0]; hint = "con movie_id=550 si pide un id"; }
  const prompt = `Tenés equipada la herramienta TMDB \`${aTool}\`. Llamala AHORA MISMO ${hint}. ` +
    `No pidas aclaraciones ni inventes datos: ejecutá la herramienta con ese valor real y, con lo que ` +
    `devuelva, decime en una sola frase un dato concreto del resultado.`;
  const r = await fetch("/v1/puppets/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recipe, prompt, space_id: "verify-1b-" + Date.now(), deadline_s: 150 }),
  });
  const body = await r.json().catch(() => null);
  return { status: r.status, ok: r.ok, body, recipe };
}, { tools: piece.tools });

const rec = (runOut.body && runOut.body.record) || {};
const toolsCabled = rec.tools_cabled || [];
const toolCalls = rec.tool_calls || [];
const forgedSet = new Set(piece.tools);
const cabledForged = toolsCabled.filter((t) => forgedSet.has(t.tool || t.name || t));
const calledForged = toolCalls.filter((tc) => forgedSet.has(tc.tool || tc.name));
const runOk = !!(runOut.body && runOut.body.ok);
// handoff = el belt forjado se resolvió y sus tools quedaron CABLEADAS en el runtime;
// invocación = el cerebro LLAMÓ al menos una tool forjada.
const c = runOk && cabledForged.length > 0 && calledForged.length > 0;

await browser.close();

// ── REPORTE ─────────────────────────────────────────────────────────────────────────
const line = "─".repeat(78);
console.log("\n" + "═".repeat(78));
console.log("  DONE-BAR · 1b-equipar · emit→EQUIPAR end-to-end");
console.log("═".repeat(78));
console.log(`\n  forja: ${forge.stats.proposed} propuestas · ${forge.stats.validated} validadas · ${forge.stats.dropped} descartadas`);

console.log("\n  ── EL OBJETO-PIEZA REAL (de cuarto.placedTiles()) ──");
console.log(JSON.stringify(piece, null, 2).split("\n").map((l) => "    " + l).join("\n"));

console.log("\n" + line);
console.log(`  (a) pieza NO hueca         : ${a ? "✓" : "✗"}  server=${piece.server} belt_ref=${piece.belt_ref ? "✓" : "∅"} puppet_id=${piece.puppet_id} tools=${piece.tools.length}`);
console.log(`  (b) tools = validadas      : ${b ? "✓" : "✗"}  ${piece.tools.length} tools, todas en tool.validada=${allInValidated}, ==forjado=${matchesForjado}`);
console.log(`  (c) RUN real la invoca     : ${c ? "✓" : "✗"}  ok=${runOk} · cableadas-forjadas=${cabledForged.length} · llamadas-forjadas=${calledForged.length} · model_final=${rec.model_final} · steps=${runOut.body && runOut.body.trajectory_steps}`);
console.log(`  (d) modelo NO mutado       : ${d ? "✓" : "✗"}  kinds⊆contrato=${kindsOk} · pieza∈modelo(tool)=${!!pieceInModel} · ida=${idas.length} eco=${ecos.length} · cero tool↔tool=${noToolToTool}`);

if (calledForged.length) {
  console.log("\n  ── tool_call REAL a la tool forjada (evidencia de invocación) ──");
  console.log("    " + JSON.stringify(calledForged[0]).slice(0, 400));
}
console.log("\n  ── tool_calls REALES del run record (diagnóstico) ──");
console.log("    " + JSON.stringify(toolCalls).slice(0, 500));
console.log("\n  ── belt resuelto + tools cableadas por el runtime (handoff) ──");
console.log("    resolved_belt: " + JSON.stringify(rec.belt).slice(0, 200));
console.log("    tools_cabled : " + JSON.stringify(toolsCabled).slice(0, 300));
if (!c) console.log("    run answer  : " + JSON.stringify((runOut.body || {}).answer || "").slice(0, 300) +
  "\n    run error   : " + JSON.stringify((runOut.body || {}).error || rec.error || null));

console.log("\n" + line);
console.log(`  console errors: ${consoleErrors.length ? "✗ " + consoleErrors.length : "✓ 0"}`);
if (consoleErrors.length) consoleErrors.forEach((e) => console.log("    ! " + e));

const allGreen = a && b && c && d && consoleErrors.length === 0;
console.log("\n" + "━".repeat(78));
console.log(`  RESULTADO: ${allGreen ? "✓ VERDE — forja → pieza real → equipada → usada en RUN, sin pieza hueca" : "✗ ROJO"}`);
console.log("━".repeat(78));
process.exit(allGreen ? 0 : 1);
