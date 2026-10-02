/* verify_cerebro.mjs — done-bar FRONT de la sub-rama 2c (cerebro-propio):
 *   (a) tap REAL en el mini-Aleph → inspector del SUB-AGENTE (picker con "Heredar del Núcleo")
 *   (b) elegir cerebro propio → recipe.belt.agent_policy.child_models[slug] con el cfg compilado REAL
 *   (c) round-trip: canvasToRecipe → recipeToCanvas conserva child_model (alias humano)
 *   (d) pieza MEMORIA → recipe.memory{shared,ref} + rels permanent+comparte + rehidrata
 *   (e) PARIDAD: escena sin child_model ni memoria → receta SIN agent_policy y SIN memory (byte-honesta)
 *   (f) 0 errores JS
 * Puerto :8153. Sin backend (stub /v1/**).   Run: node verify_cerebro.mjs */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = 8153;
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`); if (!c) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1400, height: 860 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__cuarto.atomState && window.__openInspector, null, { timeout: 12000 });

  // ── (e-base) PARIDAD: tool suelta + agente SIN cerebro propio → ni agent_policy ni memory ──
  const parity = await page.evaluate(async () => {
    const c = window.__cuarto;
    c.placeTile({ id: "ce-t1", label: "t", category: "read", atom: "tool", server: "exa" });
    c.placeRecinto({ id: "ce-agente", label: "Quant", hasNucleo: true, w: 2, h: 2, agent_ref: "catalog/agents/research-sub.config.json" },
      [{ id: "ce-r1", label: "a", category: "read", atom: "tool", server: "arxiv" }]);
    const { tilesToRecipe } = await import("./cuarto.recipe.js");
    const r = tilesToRecipe(c.placedTiles());
    return { hasPolicy: !!(r.belt && r.belt.agent_policy), hasMemory: "memory" in r, agentRefs: (r.belt && r.belt.agent_refs) || [] };
  });
  ok(parity.hasPolicy === false && parity.hasMemory === false && parity.agentRefs.length === 1,
     "(e) paridad: sin elección → receta SIN agent_policy y SIN memory", JSON.stringify(parity));

  // ── (a) TAP REAL en el mini-Aleph → inspector SUB-AGENTE ──
  await sleep(200);   // un frame: el art se ancla al centro del footprint en el ticker
  const pt = await page.evaluate(() => {
    const p = window.__cuarto.artScreenOf("ce-agente");   // posición GLOBAL real del mini (post-cámara)
    const cv = document.querySelector("#cuarto canvas") || document.querySelector("canvas");
    const rb = cv.getBoundingClientRect();
    return { x: rb.x + p.x, y: rb.y + p.y };
  });
  await page.mouse.click(pt.x, pt.y);
  await sleep(250);
  const insp = await page.evaluate(() => ({
    open: document.getElementById("inspector").classList.contains("open"),
    kind: document.getElementById("ikind").textContent,
    inherit: !!document.querySelector('#d-opts .modelcard[data-model="__inherit"]'),
  }));
  ok(insp.open && insp.kind === "SUB-AGENTE" && insp.inherit,
     "(a) tap en el mini-Aleph → inspector SUB-AGENTE con 'Heredar del Núcleo'", JSON.stringify(insp));

  // ── (b) elegir cerebro propio → agent_policy.child_models[slug] compilado REAL ──
  const pol = await page.evaluate(async () => {
    const d = window.__cuarto.pieceData("ce-agente");
    d.child_model = "oss-120b";                      // (la UI escribe esto vía el picker; data es VIVA)
    const { tilesToRecipe } = await import("./cuarto.recipe.js");
    const { compileModel } = await import("./cuarto.models.js");
    const r = tilesToRecipe(window.__cuarto.placedTiles());
    const cm = r.belt.agent_policy && r.belt.agent_policy.child_models;
    const expected = compileModel("oss-120b", { max_turns: 8 });
    return { policy: r.belt.agent_policy && r.belt.agent_policy.child_model,
             slugs: cm ? Object.keys(cm) : [],
             primaryOk: cm && cm["research-sub"] && cm["research-sub"].primary === expected.primary,
             alias: cm && cm["research-sub"] && cm["research-sub"].alias };
  });
  ok(pol.policy === "own" && pol.slugs.length === 1 && pol.slugs[0] === "research-sub" && pol.primaryOk && pol.alias === "oss-120b",
     "(b) child_models[research-sub] = cfg compilado REAL + alias humano", JSON.stringify(pol));

  // ── (c) round-trip del alias por recipeToCanvas (camino fallback sin canvas) ──
  const rt = await page.evaluate(async () => {
    const { tilesToRecipe } = await import("./cuarto.recipe.js");
    const r = tilesToRecipe(window.__cuarto.placedTiles());
    delete r.canvas;                                    // fuerza el camino de inferencia (belt.agent_refs)
    const back = window.Projection.recipeToCanvas(r, []);
    const ag = back.blocks.find((b) => b.atom === "agente");
    return ag && ag.child_model;
  });
  ok(rt === "oss-120b", "(c) el alias del cerebro propio sobrevive el round-trip", `child_model=${rt}`);

  // ── (d) pieza MEMORIA: rels + recipe.memory + rehidratación ──
  const mem = await page.evaluate(async () => {
    const c = window.__cuarto;
    c.placeTile({ id: "ce-mem", label: "Memoria", atom: "memoria" });
    const rels = c.relations();
    const { tilesToRecipe } = await import("./cuarto.recipe.js");
    const r = tilesToRecipe(c.placedTiles());
    const back = window.Projection.recipeToCanvas({ ...r, canvas: undefined }, []);
    return {
      perm: rels.some((x) => x.kind === "permanent" && x.from === "ce-mem"),
      comparte: rels.filter((x) => x.kind === "comparte").map((x) => `${x.from}>${x.to}`),
      memory: r.memory || null,
      rehidrata: back.blocks.some((b) => b.atom === "memoria"),
    };
  });
  ok(mem.perm && mem.comparte.length === 1 && mem.comparte[0] === "ce-mem>ce-agente",
     "(d1) rels: permanent al Núcleo + comparte al sub-agente", JSON.stringify(mem.comparte));
  ok(!!mem.memory && mem.memory.shared === true && /memoria-compartida\.mcp\.json$/.test(mem.memory.ref || ""),
     "(d2) recipe.memory first-class {shared, ref}", JSON.stringify(mem.memory));
  ok(mem.rehidrata === true, "(d3) la pieza memoria REHIDRATA desde la receta", "");

  await page.evaluate(() => window.__cuarto.cam.fit(1.3)); await sleep(350);
  await page.screenshot({ path: join(HERE, "screenshots", "cerebro-memoria-dark.png") });
  ok(errors.length === 0, "(f) 0 errores JS/render", errors.slice(0, 2).join(" ; "));
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push(`harness: ${e && e.message ? e.message : String(e)}`);
} finally {
  await browser.close(); server.kill();
}
console.log("");
if (fails.length === 0) { console.log("RESULTADO: VERDE — cerebro propio (tap→picker→policy compilada→round-trip) + memoria first-class (rels+recipe+rehidrata)"); process.exit(0); }
console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); process.exit(1);
