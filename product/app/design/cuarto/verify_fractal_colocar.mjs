/* verify_fractal_colocar.mjs — D3 (agente-como-pieza · colocar/exportar + ciclos) · headless, SIN backend.
 *
 * Sirve product/app/design ESTÁTICO en :8104, y stubea /v1: GET /v1/users/{id}/puppets devuelve un
 * GRAFO REAL de agentes guardados (belt.agent_refs[] ∪ canvas.blocks agente) que incluye un ciclo
 * A→B→A y una cadena A→Bchain→Bcyc→A, para que la guardia de ciclo (mirror del runtime) tenga data.
 * Maneja el Cuarto por window.__cuarto + window.Projection. Prueba D3:
 *   · ROUND-TRIP  : colocar agente-pieza (cuartoPlaceAgent real) → tilesToRecipe → ref en belt.agent_refs[]
 *                   y JAMÁS en belt_refs[] → recipeToTiles → estructura idéntica (agent_ref intacto, agente).
 *   · CAJÓN DIRECTO: placeRecinto SIN núcleo + tools → tilesToRecipe → agent_refs vacío + tools en belt_refs.
 *   · CICLOS      : A→A (self) rechazado; A→Bcyc→A (canvas union) rechazado; A→Bchain→Bcyc→A (belt union,
 *                   multi-hop) rechazado; A→Bleaf (sin back-ref) PERMITIDO y colocado.
 *   · enter()-fetch HONESTO: sin sesión → __cuartoFetchChildRecipe devuelve null (path full = backend real, D4).
 * Falla si hay error JS de página. Run:  node verify_fractal_colocar.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");             // product/app/design (para que ../theme.js resuelva)
const PORT = 8104;                                // ≠ :8091 (D2/D3/D5 sin backend); ≠ :8103 (D2)
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

// ── GRAFO de agentes guardados (owner-materializado, como el list de puppets del owner) ───────────
const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";      // el PADRE que se edita
const BCYC = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";   // back-ref a A vía canvas.blocks agente  → A→BCYC→A
const BCHAIN = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"; // ref a BCYC vía belt.agent_refs         → A→BCHAIN→BCYC→A
const BLEAF = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";  // sin agent_refs                          → A→BLEAF válido
const RT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";     // round-trip (fuera del grafo de ciclos)
const ref = (u) => "catalog/agents/agent-" + u + ".config.json";
const GRAPH = [
  { id: A, name: "Agente A", config: { schema_version: "v1", meta: { name: "Agente A" }, belt: { belt_refs: ["b/x.mcp.json"] } } },
  { id: BCYC, name: "Agente Bcyc", config: { schema_version: "v1", meta: { name: "Agente Bcyc" },
      belt: {}, canvas: { blocks: [{ id: "back", atom: "agente", agent_ref: ref(A) }] } } },   // ← union por canvas.blocks
  { id: BCHAIN, name: "Agente Bchain", config: { schema_version: "v1", meta: { name: "Agente Bchain" },
      belt: { agent_refs: [ref(BCYC)] } } },                                                      // ← union por belt.agent_refs
  { id: BLEAF, name: "Agente Bleaf", config: { schema_version: "v1", meta: { name: "Agente Bleaf" }, belt: { belt_refs: ["b/leaf.mcp.json"] } } },
  { id: RT, name: "Round Trip", config: { schema_version: "v1", meta: { name: "Round Trip" }, canvas: { nucleos: [{ model: "equilibrado" }] } } },
];
const USERS_PUPPETS_RE = /\/v1\/users\/[^/]+\/puppets/;

// ── static server (stdlib python) ────────────────────────────────────────────
const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
// stub el backend: users/*/puppets → GRAFO real (la guardia de ciclo camina ESTA data); el resto → []
await page.route("**/v1/**", (route) => {
  const url = route.request().url();
  if (USERS_PUPPETS_RE.test(url))
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ puppets: GRAPH }) });
  return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
});

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection && window.__cuartoCycleGuard && window.__cuartoPlaceAgent, null, { timeout: 10000 });

  // ╔══ ROUND-TRIP · colocar (gesto REAL) → save (tilesToRecipe) → load (recipeToTiles) idéntico ═════╗
  const rt = await page.evaluate(async ({ RT, refRT, GRAPH }) => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));                     // escena limpia (queda el Núcleo)
    const res = await window.__cuartoPlaceAgent(RT, 4, 3, { puppets: GRAPH, parentUuid: null });   // colocar como pieza (aditivo)
    const placed = c.placedTiles();
    const isAgent = placed.some((p) => p.id === "agt-" + RT && (p.atom === "agente" || p.nucleo));
    const recipe = window.__recipeMod.tilesToRecipe(placed, c.nucleoData());  // SAVE (misma receta que RUN)
    const agent_refs = (recipe.belt && recipe.belt.agent_refs) || [];
    const belt_refs = (recipe.belt && recipe.belt.belt_refs) || [];
    const tiles = window.__recipeMod.recipeToTiles(recipe, (window.__atoms && window.__atoms.list) || []);  // LOAD
    const agentTiles = tiles.filter((t) => t.atom === "agente");
    return { placed: res && res.placed, isAgent, agent_refs, belt_refs, refRT,
             rehydratedRefs: agentTiles.map((t) => t.agent_ref), rehydratedIsAgent: agentTiles.length === 1 && agentTiles[0].nucleo === true };
  }, { RT, refRT: ref(RT), GRAPH });
  ok(rt.placed === true && rt.isAgent, "ROUND-TRIP · cuartoPlaceAgent coloca una pieza-AGENTE (aditivo, sin destruir la escena)", JSON.stringify({ placed: rt.placed, isAgent: rt.isAgent }));
  ok(rt.agent_refs.length === 1 && rt.agent_refs[0] === rt.refRT, "ROUND-TRIP · el ref cae en belt.agent_refs[] (proyección)", JSON.stringify(rt.agent_refs));
  ok(rt.belt_refs.indexOf(rt.refRT) === -1, "ROUND-TRIP · el ref JAMÁS cae en belt_refs[] (fuga = muerte silenciosa)", JSON.stringify(rt.belt_refs));
  ok(rt.rehydratedRefs.length === 1 && rt.rehydratedRefs[0] === rt.refRT && rt.rehydratedIsAgent,
    "ROUND-TRIP · recipeToTiles rehidrata la MISMA pieza-agente (agent_ref intacto, sigue siendo agente)", JSON.stringify(rt.rehydratedRefs));

  // ╔══ CAJÓN NUNCA agent_ref (DIRECTO) · recinto SIN núcleo + tools → agent_refs vacío + tools en belt_refs ═╗
  const cajon = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeRecinto({ id: "cajon", gridX: 3, gridY: 3, w: 2, h: 2 },   // SIN nucleo/agent_ref → CAJÓN (scoping visual)
      [{ id: "k1", key: "calc", label: "Calc", category: "process", atom: "tool", ref: "calc", belt_ref: "belts/calc.mcp.json", tools: ["add"] },
       { id: "k2", key: "py", label: "Py", category: "process", atom: "tool", ref: "py", belt_ref: "belts/py.mcp.json", tools: ["run"] }]);
    const placed = c.placedTiles();
    const recipe = window.__recipeMod.tilesToRecipe(placed, c.nucleoData());
    return { agent_refs: (recipe.belt && recipe.belt.agent_refs) || [], belt_refs: (recipe.belt && recipe.belt.belt_refs) || [],
             cajonIsAgent: placed.some((p) => p.id === "cajon" && (p.atom === "agente" || p.nucleo)) };
  });
  ok(cajon.agent_refs.length === 0, "CAJÓN · un cajón (recinto sin núcleo) NO genera agent_ref (belt.agent_refs vacío/ausente)", JSON.stringify(cajon.agent_refs));
  ok(cajon.belt_refs.indexOf("belts/calc.mcp.json") !== -1 && cajon.belt_refs.indexOf("belts/py.mcp.json") !== -1,
    "CAJÓN · las tools del cajón SUBEN por unión a belt_refs[]", JSON.stringify(cajon.belt_refs));
  ok(cajon.cajonIsAgent === false, "CAJÓN · el cajón NO es pieza-agente (isAgentPiece false)");

  // ╔══ CICLOS · la guardia (mirror del runtime) camina el GRAFO STUBEADO ════════════════════════════╗
  const cyc = await page.evaluate(async ({ A, BCYC, BCHAIN, BLEAF }) => {
    // fetch REAL desde el stub → la guardia camina ESTA data (no un objeto inventado en el test)
    const d = await fetch("/v1/users/u1/puppets").then((r) => r.json()).catch(() => null);
    const puppets = (d && d.puppets) || [];
    const G = window.__cuartoCycleGuard;
    const self = G(A, puppets, A);                       // A→A
    const cycCanvas = G(BCYC, puppets, A);               // A→Bcyc→A (back-ref por canvas.blocks)
    const cycChain = G(BCHAIN, puppets, A);              // A→Bchain→Bcyc→A (belt.agent_refs, multi-hop)
    const valid = G(BLEAF, puppets, A);                  // A→Bleaf (sin back-ref)
    // y el GESTO real de colocación respeta la guardia (rechazo = NO se coloca)
    const c = window.__cuarto; c.placedTiles().forEach((t) => c.removeTile(t.id));
    const beforeSelf = c.placedTiles().length;
    const placeSelf = await window.__cuartoPlaceAgent(A, 5, 4, { puppets, parentUuid: A });
    const afterSelf = c.placedTiles().length;
    const placeCyc = await window.__cuartoPlaceAgent(BCYC, 5, 4, { puppets, parentUuid: A });
    const afterCyc = c.placedTiles().length;
    const placeValid = await window.__cuartoPlaceAgent(BLEAF, 5, 4, { puppets, parentUuid: A });
    const afterValid = c.placedTiles().length;
    const validIsAgent = c.placedTiles().some((p) => p.id === "agt-" + BLEAF && (p.atom === "agente" || p.nucleo));
    return { self, cycCanvas, cycChain, valid, beforeSelf, afterSelf, placeSelf, placeCyc, afterCyc, placeValid, afterValid, validIsAgent, fetched: puppets.length };
  }, { A, BCYC, BCHAIN, BLEAF });
  ok(cyc.fetched === GRAPH.length, "CICLO · el stub /v1/users/*/puppets alimentó el grafo REAL a la guardia", JSON.stringify({ fetched: cyc.fetched }));
  ok(cyc.self && cyc.self.ok === false && cyc.self.reason === "self", "CICLO · A→A (self) → rechazo honesto {ok:false, reason:'self'}", JSON.stringify(cyc.self));
  ok(cyc.cycCanvas && cyc.cycCanvas.ok === false && cyc.cycCanvas.reason === "cycle", "CICLO · A→Bcyc→A (union por canvas.blocks) → rechazo honesto {ok:false, reason:'cycle'}", JSON.stringify(cyc.cycCanvas));
  ok(cyc.cycChain && cyc.cycChain.ok === false && cyc.cycChain.reason === "cycle", "CICLO · A→Bchain→Bcyc→A (union por belt.agent_refs, multi-hop) → rechazo honesto", JSON.stringify(cyc.cycChain));
  ok(cyc.valid && cyc.valid.ok === true, "CICLO · A→Bleaf (sin back-ref) → PERMITIDO {ok:true}", JSON.stringify(cyc.valid));
  ok(cyc.placeSelf && cyc.placeSelf.placed === false && cyc.afterSelf === cyc.beforeSelf, "CICLO · colocar A en A → NO se coloca (placed:false, escena intacta)", JSON.stringify({ placed: cyc.placeSelf && cyc.placeSelf.placed }));
  ok(cyc.placeCyc && cyc.placeCyc.placed === false && cyc.afterCyc === cyc.beforeSelf, "CICLO · colocar Bcyc bajo A → NO se coloca (placed:false, escena intacta)", JSON.stringify({ placed: cyc.placeCyc && cyc.placeCyc.placed }));
  ok(cyc.placeValid && cyc.placeValid.placed === true && cyc.afterValid === cyc.beforeSelf + 1 && cyc.validIsAgent,
    "CICLO · colocar Bleaf bajo A → SÍ se coloca (placed:true, +1 pieza-agente)", JSON.stringify({ placed: cyc.placeValid && cyc.placeValid.placed }));

  // ╔══ enter()-fetch HONESTO · sin sesión → null (el path full = backend real + sesión, D4) ═════════╗
  const fetchHonesty = await page.evaluate(async ({ refRT }) => {
    const childRecipe = await window.__cuartoFetchChildRecipe(refRT);   // sin sesión (sessUser()===null) → null
    const uuid = window.__cuartoRefToUuid(refRT);
    return { childRecipe, uuid };
  }, { refRT: ref(RT) });
  ok(fetchHonesty.childRecipe === null, "ENTER-FETCH · sin sesión __cuartoFetchChildRecipe devuelve null (HONESTO; path full = D4 backend real)");
  ok(fetchHonesty.uuid === RT, "ENTER-FETCH · refToUuid parsea el UUID del agent_ref (mirror de _slug_from_agent_ref)", JSON.stringify({ uuid: fetchHonesty.uuid }));

  // ── 0 errores JS/render de página ──
  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e);
  fails.push("harness: " + e.message);
} finally {
  await browser.close();
  server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — D3 (agente-como-pieza · colocar/exportar + ciclos) verificada"));
process.exit(fails.length ? 1 : 0);
