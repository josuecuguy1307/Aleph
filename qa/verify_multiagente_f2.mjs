/* MULTIAGENTE F2 · VARA VISUAL, contra el frozen propio en :8314.
 *
 * Cubre: baldosa Aleph vs caja MCP, contador/anillo, zoom semántico anclado,
 * profundidad y migas, controles zoom-invariantes con calibración roja, contrato de
 * cables + /plan, duplicado visible, corrida real de tres saltos con latencias medidas,
 * nucleo:false, muralla anti-fractal, opt-in visual, popup sin listas crudas y el
 * estado único de Modelos v2 leído por chrome + Núcleo + Sala.
 *
 * Corrida canónica (la vara toma lockf sola):
 *   ALEPH_SIDECAR_BIN=/tmp/aleph-f2-frozen/aleph_sidecar \
 *     node qa/verify_multiagente_f2.mjs
 */
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import net from "node:net";
import { fileURLToPath } from "node:url";
import { spawnFrozen, matarFrozen } from "./lib/frozen_guard.mjs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const ROOT = join(HERE, "..");
const SCRIPT = fileURLToPath(import.meta.url);
const PORT = Number(process.env.ALEPH_F2_PORT || 8314);
const BASE = `http://127.0.0.1:${PORT}`;
const LOCK = "/tmp/aleph-frozen.lock";
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
const DATADIR = mkdtempSync(join(tmpdir(), "aleph-ma-f2-"));
// [H2] Misma clase que `verify_modelos_v2`: `qa/screenshots/multiagente-f2-frozen.png`
// está COMMITEADO y esta vara lo reescribía en cada corrida. La captura es evidencia de
// la corrida → temporal; pisar la del árbol es un acto explícito.
const SHOT = process.argv.includes("--capturas-al-arbol")
  ? join(ROOT, "qa/screenshots/multiagente-f2-frozen.png")
  : join(tmpdir(), `aleph-ma-f2-shot-${process.pid}.png`);

if (![8314, 8320].includes(PORT) || PORT === 25374) {
  console.error("✗ F2 corre en :8314 (rama) o :8320 (integración); :25374 está prohibido");
  process.exit(2);
}
if (process.env.ALEPH_F2_LOCK_HELD !== "1" && existsSync("/usr/bin/lockf")) {
  const child = spawnSync("/usr/bin/lockf", [
    "-k", LOCK, "/usr/bin/env", "ALEPH_F2_LOCK_HELD=1",
    process.execPath, SCRIPT, ...process.argv.slice(2),
  ], { stdio: "inherit", env: process.env });
  process.exit(child.status == null ? 2 : child.status);
}

const A = "catalog/agents/ma-f1-extractor.config.json";
const B = "catalog/agents/ma-f1-calculo.config.json";
const C = "catalog/agents/ma-f1-informe.config.json";
const PROMPT = "Compramos 3 sensores, 10 resistencias y 7 capacitores. ¿Cuántas piezas en total?";
let PASS = 0;
const failures = [];
function ok(cond, label, detail = "") {
  if (cond) { PASS++; console.log(`  PASS  ${label}`); }
  else {
    failures.push(label);
    console.log(`  FAIL  ${label}${detail ? " — " + String(detail).slice(0, 420) : ""}`);
  }
  return !!cond;
}
function section(label) { console.log(`\n§ ${label}`); }
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const close = (a, b, eps = 0.12) => Math.abs(Number(a) - Number(b)) <= eps;
const spread = (xs) => xs.length ? Math.max(...xs) - Math.min(...xs) : Infinity;

function loadPlaywright() {
  for (const root of [
    process.env.PLAYWRIGHT_PROJECT,
    ROOT,
  ].filter(Boolean)) {
    if (!existsSync(join(root, "node_modules/playwright/package.json"))) continue;
    return createRequire(join(root, "package.json"))("playwright");
  }
  throw new Error("Playwright no está disponible; definí PLAYWRIGHT_PROJECT");
}
function keyFromEnvFile() {
  if (process.env.LITELLM_KEY) return process.env.LITELLM_KEY;
  if (process.env.GROQ_API_KEY) return process.env.GROQ_API_KEY;
  for (const file of [
    join(ROOT, "infra/.env"),
  ]) {
    if (!existsSync(file)) continue;
    for (const line of readFileSync(file, "utf8").split("\n")) {
      const hit = /^\s*(LITELLM_KEY|GROQ_API_KEY)\s*=\s*(.+?)\s*$/.exec(line);
      if (hit) return hit[2].replace(/^["']|["']$/g, "");
    }
  }
  return "";
}
function globo(refs, links = null) {
  const belt = { agent_refs: refs, tool_filters: {} };
  if (links) belt.agent_links = links;
  return {
    schema_version: "v1", modo: "cadena",
    meta: { name: "F2 · cadena visual", nicho: "general" },
    model: { primary: "openai/gpt-oss-120b", base_url: "https://api.groq.com/openai/v1",
      temperature: 0, max_tokens: 256, max_turns: 3 },
    belt, rag: { enabled: false },
  };
}
async function api(method, path, body, token) {
  const response = await fetch(BASE + path, {
    method,
    headers: {
      accept: "application/json",
      ...(body === undefined ? {} : { "content-type": "application/json" }),
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let json = null;
  try { json = await response.json(); } catch {}
  return { status: response.status, json };
}
function causeOf(result) {
  const d = result && result.json && result.json.detail;
  if (!d) return "";
  if (d.causa) return d.causa;
  const first = (d.errors || [])[0];
  if (typeof first === "string") return (/^\[([a-z_]+)/.exec(first) || [])[1] || first;
  return first && (first.causa || first.error) || "";
}
function portOpen() {
  return new Promise((resolve) => {
    const socket = net.connect(PORT, "127.0.0.1");
    socket.on("connect", () => { socket.destroy(); resolve(true); });
    socket.on("error", () => { socket.destroy(); resolve(false); });
  });
}
async function waitReady(timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await portOpen()) return true;
    await sleep(250);
  }
  return false;
}
async function waitUntil(fn, timeoutMs = 8000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await fn()) return true;
    await sleep(50);
  }
  return false;
}

// Contratos estáticos que una captura no ve.
section("0 · contratos estáticos");
const SRC_RENDER = readFileSync(join(ROOT, "product/app/design/cuarto/cuarto.render.js"), "utf8");
const SRC_HTML = readFileSync(join(ROOT, "product/app/design/cuarto/cuarto.pixi.html"), "utf8");
const SRC_BRAIN = readFileSync(join(ROOT, "product/app/design/brain-status.js"), "utf8");
const SRC_SALA = readFileSync(join(ROOT, "product/app/design/sala/sala.html"), "utf8");
const SRC_RECIPE = readFileSync(join(ROOT, "product/app/design/cuarto/cuarto.recipe.js"), "utf8");
ok(/structure:\s*"baldosa"/.test(SRC_RENDER) && /__structure\s*=\s*"caja"/.test(SRC_RENDER) &&
   /makeAlephCreature/.test(SRC_RENDER) && !/makeAgentDoll/.test(SRC_RENDER),
  "Aleph=baldosa+criatura canónica y MCP=caja, por ramas de render distintas");
ok(/virtualized:\s*true/.test(SRC_RENDER) && /visibleFloorBounds/.test(SRC_RENDER),
  "suelo finito virtualizado: pool por viewport, no malla completa");
ok(!/\(\$\{gx\},\$\{gy\}\)/.test(SRC_HTML) && /data-rp-purpose/.test(SRC_HTML) &&
   /data-rp-state/.test(SRC_HTML) && /AGENTE ALEPH/.test(SRC_HTML),
  "cero coordenadas dev; popup Aleph lleva propósito y estado localizado");
ok(/fixedControls\s*\?\s*1\s*\/\s*cam\.scale/.test(SRC_RENDER),
  "contador, puerto y latencia comparten la compensación zoom-invariante");
ok(/Tus Aleph/.test(SRC_HTML) && /aleph-chip/.test(SRC_HTML),
  "la paleta suma sólo la entrada Tus Aleph");
ok(/recipe\.modo/.test(SRC_RECIPE) && /agent_links/.test(SRC_RECIPE),
  "modo y cables tipados sobreviven el round-trip de receta");
ok(/`\$\{d\.tools\.length\} tools`/.test(SRC_HTML) &&
   !/frenadas\.slice\([^)]*\)\.join\(\s*["']\,/.test(SRC_HTML),
  "popup resume N tools y no vuelca listas crudas coma-separadas");
ok(/BroadcastChannel\("aleph-modelos-v2"\)/.test(SRC_BRAIN) &&
   /aleph:model-selection/.test(SRC_SALA) && /id="cuartoBrainDock"/.test(SRC_HTML),
  "Modelos v2 alimenta las tres lecturas: chrome, Núcleo y Sala");
ok(/En uso/.test(SRC_BRAIN) && /Usar este modelo/.test(SRC_BRAIN) &&
   /Probar ahora|onProbar/.test(SRC_HTML + SRC_SALA),
  "selección declarada por texto y prueba separada del semáforo");

if (!existsSync(SIDECAR)) {
  console.error(`\n✗ falta frozen: ${SIDECAR}`);
  rmSync(DATADIR, { recursive: true, force: true });
  process.exit(2);
}
if (await portOpen()) {
  console.error(`\n✗ :${PORT} ya está ocupado; la vara sólo mide su propio frozen`);
  rmSync(DATADIR, { recursive: true, force: true });
  process.exit(2);
}

console.log(`\n══ MULTIAGENTE F2 · frozen :${PORT} ══\n  bin: ${SIDECAR}\n  data: ${DATADIR}`);
const proc = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
  stdio: ["ignore", "pipe", "pipe"],
  env: {
    ...process.env, ALEPH_DATA_DIR: DATADIR, ALEPH_ROLE: "client",
    ALEPH_BUILD: "public", LITELLM_KEY: keyFromEnvFile(),
  },
});
let frozenLog = "";
proc.stdout?.on("data", (chunk) => { frozenLog += chunk; });
proc.stderr?.on("data", (chunk) => { frozenLog += chunk; });

let browser = null;
try {
  section("1 · frozen y motor sellado");
  if (!ok(await waitReady(180000), `el frozen propio levanta en :${PORT}`, frozenLog.slice(-800)))
    throw new Error("frozen no levantó");
  const health = await api("GET", "/health");
  const boot = await api("GET", "/v1/motor/arranque");
  ok(health.status === 200 && boot.status === 200 &&
    boot.json && boot.json.entorno && boot.json.entorno.frozen === true,
    "la sonda de arranque prueba frozen=true", JSON.stringify(boot.json).slice(0, 300));
  const session = await api("POST", "/v1/auth/local", {});
  const token = session.json && session.json.session_token;
  const userId = session.json && session.json.id;
  ok(!!token && !!userId, "sesión local aislada para el run");

  const planned = await api("POST", "/v1/multiagente/plan", { recipe: globo([A, B, C]) }, token);
  const plan = planned.json && planned.json.plan;
  const piezas = planned.json && planned.json.piezas_aleph;
  ok(planned.status === 200 && plan && plan.eslabones.length === 3,
    "/plan devuelve tres eslabones", JSON.stringify(planned.json).slice(0, 300));
  ok(JSON.stringify(plan.eslabones.map((e) => e.nucleo)) === JSON.stringify([true, false, true]),
    "/plan es el dueño de nucleo:true/false/true");
  ok(plan.cables.length === 2 && plan.cables.every((c) => c.tipo === "entregar"),
    "/plan devuelve tipo y dirección de los cables");

  const invalidLoop = await api("POST", "/v1/multiagente/plan", {
    recipe: globo([A, B], [{ from: "ma-f1-extractor", to: "ma-f1-extractor", tipo: "entregar" }]),
  }, token);
  ok(invalidLoop.status >= 400 && /ciclo|bucle/.test(causeOf(invalidLoop) + JSON.stringify(invalidLoop.json)),
    "/plan confirma el rechazo del bucle", JSON.stringify(invalidLoop.json).slice(0, 260));

  const { chromium } = loadPlaywright();
  browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const selector = {
    id: "claude_cli", slug: "cli.claude", writes: [], cutWrite: false, cutRead: false,
  };
  const modelRows = [
    { id: "claude_cli", slug: "cli.claude", label: "Claude Code", conectado: true,
      connected: true, default: true, frontier: true },
    { id: "codex_cli", slug: "cli.codex", label: "Codex", conectado: true,
      connected: true, default: false, frontier: true },
  ];
  const selectorBody = (contexto = "sala") => ({
    contexto, default: "cli.claude", default_id: "claude_cli",
    seleccion: selector.slug, seleccion_id: selector.id,
    regla: "conectados+default", modelos: modelRows,
  });
  await context.route("**/v1/modelos/selector*", async (route) => {
    if (selector.cutRead) return route.fulfill({ status: 503, contentType: "application/json",
      body: JSON.stringify({ detail: "lectura cortada por calibración" }) });
    const url = new URL(route.request().url());
    return route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify(selectorBody(url.searchParams.get("contexto") || "sala")) });
  });
  await context.route("**/v1/modelos/preferencias", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    let body = {};
    try { body = route.request().postDataJSON(); } catch {}
    selector.writes.push(body);
    if (selector.cutWrite) return route.fulfill({ status: 500, contentType: "application/json",
      body: JSON.stringify({ detail: "escritura cortada por calibración" }) });
    const row = modelRows.find((m) => m.slug === body.seleccion);
    if (row) { selector.id = row.id; selector.slug = row.slug; }
    return route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ version: 2, contextos: { sala: selector.slug } }) });
  });

  const runtimeErrors = [];
  const attachErrors = (page) => {
    page.on("pageerror", (e) => runtimeErrors.push(String(e)));
    page.on("console", (m) => {
      if (m.type() === "error" && !/Failed to load resource|401|404|favicon/i.test(m.text()))
        runtimeErrors.push(m.text());
    });
  };
  const cuartoPage = await context.newPage();
  const salaPage = await context.newPage();
  attachErrors(cuartoPage); attachErrors(salaPage);
  await Promise.all([
    cuartoPage.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" }),
    salaPage.goto(`${BASE}/sala/sala.html`, { waitUntil: "domcontentloaded" }),
  ]);
  await cuartoPage.waitForFunction(() => window.__cuarto && window.Projection &&
    window.AlephModelSelector && window.__buildAlephPalette, null, { timeout: 90000 });
  await salaPage.waitForFunction(() => document.getElementById("powNow") &&
    document.getElementById("powNow").textContent.trim(), null, { timeout: 90000 });
  await sleep(1600);

  section("2 · opt-in y estructura de pieza");
  await cuartoPage.evaluate(() => {
    const C = window.__cuarto;
    C.placedTiles().forEach((t) => C.removeTile(t.id));
    C.multiagente.setMode(null);
    C.app.ticker.stop();
    C.app.renderer.render(C.app.stage);
  });
  const baseline = await cuartoPage.locator("#cuarto").screenshot();
  await cuartoPage.evaluate(() => {
    window.__cuarto.multiagente.setMode(null);
    window.__cuarto.multiagente.setRestriction(true);
    window.__cuarto.app.renderer.render(window.__cuarto.app.stage);
  });
  const optin = await cuartoPage.locator("#cuarto").screenshot();
  ok(Buffer.compare(baseline, optin) === 0,
    "Cuarto sin sub-Alephs: diff de canvas contra baseline = 0 bytes");
  await cuartoPage.evaluate(() => window.__cuarto.app.ticker.start());

  const sideBySide = await cuartoPage.evaluate(async (A) => {
    const C = window.__cuarto;
    C.placeTile({ id: "mcp-yf", label: "Yfinance", server: "yfinance", category: "read",
      tools: ["history", "quote", "news"] }, 2, 2);
    C.placeTile({ id: "agt-a", label: "Analista", atom: "agente", nucleo: true,
      agent_ref: A, interiorCount: 3 }, 5, 3);
    await new Promise((r) => setTimeout(r, 180));
    return {
      mcp: C.pieceStructure("mcp-yf"), aleph: C.pieceStructure("agt-a"),
      draw: C.recintoDraw().find((x) => x.id === "agt-a"),
      atom: C.atomState().recintos["agt-a"],
      placed: C.placedTiles().map((x) => x.id),
    };
  }, A);
  ok(sideBySide.mcp === "caja" && sideBySide.aleph === "baldosa",
    "MCP y Aleph lado a lado son caja vs baldosa", JSON.stringify(sideBySide));
  ok(sideBySide.draw && sideBySide.draw.alephCreature && !sideBySide.draw.atomMark &&
    sideBySide.draw.ring &&
    sideBySide.draw.counter === 3 && sideBySide.draw.interiorVisible === false,
    "Aleph exterior: criatura + nombre/contador, sin átomo; interior jamás visible",
    JSON.stringify(sideBySide.draw));
  ok(sideBySide.placed.length === 2,
    "las piezas interiores no se materializan fuera del Aleph", JSON.stringify(sideBySide.placed));

  const agentPoint = await cuartoPage.evaluate(() => window.__cuarto.artScreenOf("agt-a"));
  const canvasBox = await cuartoPage.locator("#cuarto").boundingBox();
  await cuartoPage.mouse.click(canvasBox.x + agentPoint.x, canvasBox.y + agentPoint.y);
  await cuartoPage.waitForFunction(() => window.__recintoPanel && window.__recintoPanel().open);
  const agentPopup = await cuartoPage.evaluate(() => ({
    state: window.__recintoPanel(),
    text: document.getElementById("recintoPanel").textContent.replace(/\s+/g, " ").trim(),
  }));
  ok(agentPopup.state.name === "Analista" && agentPopup.state.purpose &&
    agentPopup.state.pieceCount === 3 && agentPopup.state.status === "detectado" &&
    /AGENTE ALEPH/.test(agentPopup.text) && /estado/.test(agentPopup.text) && /Entrar/.test(agentPopup.text),
    "popup ES lleva nombre, qué hace, contador, anillo/estado y acción", JSON.stringify(agentPopup));
  await cuartoPage.evaluate(() => window.__recintoPanelClose());

  const duplicate = await cuartoPage.evaluate((A) => {
    const C = window.__cuarto;
    const before = C.placedTiles().length;
    const placed = C.placeTile({ id: "agt-a-copy", label: "Analista 2", atom: "agente",
      nucleo: true, agent_ref: A, interiorCount: 1 }, 6, 5);
    return { placed, before, after: C.placedTiles().length,
      visible: document.getElementById("multiModeStatus").textContent };
  }, A);
  ok(!duplicate.placed && duplicate.before === duplicate.after &&
    duplicate.visible.includes("este Aleph ya está en la cadena"),
    "mismo Aleph dos veces: rechazo visible antes de /plan", JSON.stringify(duplicate));

  const parentRed = await cuartoPage.evaluate(async () => {
    const C = window.__cuarto;
    C.multiagente.setInterior("agt-a", { estado: "error" });
    await new Promise((r) => setTimeout(r, 100));
    const red = C.recintoDraw().find((x) => x.id === "agt-a");
    C.multiagente.setInterior("agt-a", { estado: "idle" });
    return red;
  });
  ok(parentRed && parentRed.ringState === "error",
    "CALIBRACIÓN ROJA · romper el interior sube rojo al anillo del padre", JSON.stringify(parentRed));

  await cuartoPage.evaluate(() => {
    window.__buildAlephPalette([{
      id: "fixture-saved", name: "Extractor guardado", nicho: "datos",
      config: { canvas: { blocks: [{ id: "x" }, { id: "y" }] }, belt: { agent_refs: [] } },
    }]);
  });
  const palette = await cuartoPage.evaluate(() => ({
    title: document.querySelector('#paletteList [data-grp="alephs:tus"]')?.textContent || "",
    chip: document.querySelector('#paletteList .aleph-chip')?.textContent || "",
  }));
  ok(/Tus Aleph/.test(palette.title) && /2 piezas/.test(palette.chip),
    "Tus Aleph usa el catálogo guardado y el mismo chip equipable", JSON.stringify(palette));

  section("3 · cámara, continuum y controles fijos");
  const controls = await cuartoPage.evaluate(async () => {
    const C = window.__cuarto;
    const rows = [];
    for (const target of [0.5, 1, 2]) {
      C.cam.zoomAt(target / C.cam.state.scale, 8, 8);
      await new Promise((r) => setTimeout(r, 100));
      rows.push({ zoom: target, box: C.agentControlBounds("agt-a") });
    }
    return rows;
  });
  const counterWidths = controls.map((x) => x.box && x.box.counter && x.box.counter.width);
  const portWidths = controls.map((x) => x.box && x.box.port && x.box.port.width);
  ok(counterWidths.every(Number.isFinite) && spread(counterWidths) <= 0.12 &&
    portWidths.every(Number.isFinite) && spread(portWidths) <= 0.12,
  "controles screen-space invariantes a 0.5×/1×/2× (≤0.12px)",
  JSON.stringify({ counterWidths, portWidths }));
  const scalableRed = await cuartoPage.evaluate(async () => {
    const C = window.__cuarto;
    C.multiagente.setFixedControls(false);
    const widths = [];
    for (const target of [0.5, 2]) {
      C.cam.zoomAt(target / C.cam.state.scale, 8, 8);
      await new Promise((r) => setTimeout(r, 80));
      widths.push(C.agentControlBounds("agt-a").counter.width);
    }
    C.multiagente.setFixedControls(true);
    return widths;
  });
  ok(spread(scalableRed) > 4,
    "CALIBRACIÓN ROJA · hacer escalable el control rompe la vara", JSON.stringify(scalableRed));

  const childRecipe = await cuartoPage.evaluate(() => window.Projection.canvasToRecipe({
    nucleo: { name: "Extractor", gridX: 3, gridY: 1 },
    blocks: [{ id: "deep", atom: "agente", nucleo: true, agent_ref: "catalog/agents/deep.config.json",
      label: "Extractor", gridX: 4, gridY: 3, interiorCount: 1 }],
    links: [],
  }));
  await cuartoPage.evaluate((recipe) => {
    window.__cuartoFetchChildRecipe = async () => recipe;
    const C = window.__cuarto;
    C.cam.zoomAt(1.64 / C.cam.state.scale, 8, 8);
  }, childRecipe);
  const anchorCss = await cuartoPage.evaluate(() => window.__cuarto.agentAnchorScreen("agt-a"));
  await cuartoPage.evaluate((p) => {
    const canvas = document.getElementById("cuarto"), r = canvas.getBoundingClientRect();
    canvas.dispatchEvent(new WheelEvent("wheel", {
      bubbles: true, cancelable: true, deltaY: -100,
      clientX: r.left + p.x, clientY: r.top + p.y,
    }));
  }, anchorCss);
  await cuartoPage.waitForFunction(() => window.__cuarto.fractal().depth === 1, null, { timeout: 8000 });
  await sleep(500);
  const zoomed = await cuartoPage.evaluate(() => ({
    fr: window.__cuarto.fractal(),
    anchor: window.__cuarto.cam.semanticAnchor(),
    crumb: document.getElementById("fractalBar").textContent.replace(/\s+/g, " ").trim(),
    rootVisible: window.__cuarto.worldVisible(),
    visual: window.__cuarto.fractalVisual(),
  }));
  const anchorError = zoomed.anchor && zoomed.anchor.after
    ? Math.hypot(zoomed.anchor.after.x - zoomed.anchor.cursor.x,
      zoomed.anchor.after.y - zoomed.anchor.cursor.y) : Infinity;
  ok(zoomed.fr.depth === 1 && zoomed.rootVisible === true &&
    /Mi Aleph/.test(zoomed.crumb) && /Analista/.test(zoomed.crumb),
    "zoom in convierte la baldosa en su Cuarto y pinta la miga", JSON.stringify(zoomed));
  ok(zoomed.visual && zoomed.visual.floor && zoomed.visual.nucleus &&
    zoomed.visual.cableCount === zoomed.visual.childCount &&
    zoomed.visual.namedCount === zoomed.visual.childCount &&
    zoomed.visual.labelOverlaps === 0 &&
    zoomed.visual.parentAlpha > 0 && zoomed.visual.parentAlpha < 1,
    "Cuarto hijo completo: suelo+nucleo+arco+cables+nombres; padre atenuado",
    JSON.stringify(zoomed.visual));
  ok(anchorError <= 0.12 &&
    Math.hypot(zoomed.anchor.before.x - zoomed.anchor.cursor.x,
      zoomed.anchor.before.y - zoomed.anchor.cursor.y) <= 0.75,
    "ancla de cámara fija bajo el cursor pre/post", JSON.stringify(zoomed.anchor));
  await cuartoPage.evaluate(() => window.__cuarto.cam.zoomAt(0.8, 8, 8));
  await cuartoPage.waitForFunction(() => window.__cuarto.fractal().depth === 0, null, { timeout: 8000 });
  ok(await cuartoPage.evaluate(() => window.__cuarto.fractal().atRoot &&
    document.getElementById("fractalBar").style.display === "none"),
    "zoom out vuelve al padre; la miga se recoge en raíz");

  const depthCap = await cuartoPage.evaluate(async (recipe) => {
    const C = window.__cuarto;
    const r1 = await C.enter("agt-a", { recipe });
    const r2 = await C.enter("deep", { recipe });
    const r3 = await C.enter("deep", { recipe });
    const r4 = await C.enter("deep", { recipe });
    const depth = C.fractal().depth;
    const crumb = document.getElementById("fractalBar").textContent.replace(/\s+/g, " ").trim();
    const visible = document.body.textContent;
    C.exitTo(0);
    return { r1, r2, r3, r4, depth, crumb, visible };
  }, childRecipe);
  ok(depthCap.depth === 3 && depthCap.r4 && depthCap.r4.reason === "depth_cap" &&
    /máx 3 niveles/.test(depthCap.visible),
    "tope visual=3 falla con causa visible, nunca muere mudo", JSON.stringify(depthCap.r4));
  await sleep(550);
  const restoredWorld = await cuartoPage.evaluate(() => ({
    layers: window.__cuarto.worldLayers(),
    ids: window.__cuarto.placedTiles().map((tile) => tile.id),
  }));
  ok(restoredWorld.layers.total === 1 && restoredWorld.layers.visible === 1 &&
    !restoredWorld.ids.includes("deep"),
    "saltar la miga al raíz destruye los Cuartos intermedios; cero mundo hijo huérfano",
    JSON.stringify(restoredWorld));

  const floorAndNames = await cuartoPage.evaluate(async () => {
    const C = window.__cuarto;
    C.placedTiles().forEach((t) => C.removeTile(t.id));
    const before = C.gridSize().N;
    C.placeTile({ id: "edge-piece", label: "Borde", category: "read" }, before - 2, before - 2);
    await new Promise((r) => setTimeout(r, 320));
    const after = C.gridSize().N;
    C.growToN(999);
    await new Promise((r) => setTimeout(r, 320));
    const mesh = C.meshStats();
    C.cam.panBy(5000, -4000);
    const far = C.cam.state;
    const framed = C.cam.reset();
    const dims = { width: C.app.screen.width, height: C.app.screen.height };
    const points = C.placedTiles().map((p) => C.screenPointOf(p.id));

    C.removeTile("edge-piece");
    C.placeTile({ id: "name-a", label: "Mi agente", atom: "agente", nucleo: true,
      agent_ref: "catalog/agents/name-a.config.json", interiorCount: 2 }, 3, 4);
    C.placeTile({ id: "name-b", label: "Mi agente", atom: "agente", nucleo: true,
      agent_ref: "catalog/agents/name-b.config.json", interiorCount: 3 }, 4, 4);
    await new Promise((r) => setTimeout(r, 240));
    const named = C.agentNames.state();

    C.agentNames.setGuardEnabled(false);
    C.placeTile({ id: "red-name-a", label: "Duplicado", atom: "agente", nucleo: true,
      agent_ref: "catalog/agents/red-name-a.config.json" }, 2, 5);
    C.placeTile({ id: "red-name-b", label: "Duplicado", atom: "agente", nucleo: true,
      agent_ref: "catalog/agents/red-name-b.config.json" }, 3, 5);
    await new Promise((r) => setTimeout(r, 120));
    const redNames = C.agentNames.state().labels.filter((x) => x.text.startsWith("Duplicado"));
    C.agentNames.setGuardEnabled(true);

    const beforeCut = C.gridSize().N;
    C.floorGrowth.setEnabled(false);
    C.floorGrowth.near(beforeCut - 1, beforeCut - 1);
    const afterCut = C.gridSize().N;
    C.floorGrowth.setEnabled(true);
    return { before, after, mesh, far, framed, dims, points, named, redNames, beforeCut, afterCut };
  });
  ok(floorAndNames.after === floorAndNames.before + 1 &&
    floorAndNames.mesh.virtualized && floorAndNames.mesh.floorPool < floorAndNames.mesh.floor,
    "soltar en el borde crece una fila; pool de piso depende del viewport",
    JSON.stringify({ before: floorAndNames.before, after: floorAndNames.after, mesh: floorAndNames.mesh }));
  ok(Math.abs(floorAndNames.far.x - floorAndNames.framed.x) > 1000 &&
    floorAndNames.points.every((p) => p && p.x >= 0 && p.x <= floorAndNames.dims.width &&
      p.y >= 0 && p.y <= floorAndNames.dims.height),
    "⊙ recupera una cámara lejana y encuadra todo lo colocado", JSON.stringify(floorAndNames));
  ok(new Set(floorAndNames.named.labels.map((x) => x.text.split("\n")[0])).size === floorAndNames.named.labels.length &&
    floorAndNames.named.overlaps === 0,
    "nombres obligatorios/únicos y legibles aun con sub-Alephs adyacentes",
    JSON.stringify(floorAndNames.named));
  ok(floorAndNames.redNames.length === 2 &&
    floorAndNames.redNames[0].text.split("\n")[0] === floorAndNames.redNames[1].text.split("\n")[0],
    "CALIBRACIÓN ROJA · cortar la guarda deja que la vara detecte el duplicado",
    JSON.stringify(floorAndNames.redNames));
  ok(floorAndNames.afterCut === floorAndNames.beforeCut,
    "CALIBRACIÓN ROJA · cortar crecimiento impide que cambie la dimensión",
    JSON.stringify({ before: floorAndNames.beforeCut, after: floorAndNames.afterCut }));

  section("4 · modo declarado, cables y /plan vivo");
  await cuartoPage.evaluate((refs) => {
    const C = window.__cuarto;
    C.placedTiles().forEach((t) => C.removeTile(t.id));
    refs.forEach((ref, i) => C.placeTile({
      id: `chain-${i}`, label: ["Extractor", "Cálculo", "Informe"][i],
      atom: "agente", nucleo: true, agent_ref: ref, interiorCount: i + 1,
    }, 1 + i * 2, 1 + i));
    C.multiagente.setMode("cadena");
  }, [A, B, C]);
  await sleep(250);
  await cuartoPage.evaluate(({ plan, piezas }) => window.__cuarto.multiagente.applyPlan(plan, piezas),
    { plan, piezas });
  await sleep(250);
  const contractUi = await cuartoPage.evaluate(() => ({
    visible: !document.getElementById("multiModeWrap").hidden,
    text: document.getElementById("multiModeMenu").textContent.replace(/\s+/g, " "),
  }));
  ok(contractUi.visible && /Cadena/.test(contractUi.text) && /Orquesta/.test(contractUi.text) &&
    /Oficina/.test(contractUi.text) && /Abanico/.test(contractUi.text) &&
    /todavía no corre/.test(contractUi.text),
    "modo declarado: cadena/orquesta al frente; oficina/abanico adentro y no-corren visible");

  let planRequests = 0;
  const countPlans = (req) => { if (req.url().includes("/v1/multiagente/plan")) planRequests++; };
  cuartoPage.on("request", countPlans);
  const beforeLocal = planRequests;
  const localRejects = await cuartoPage.evaluate(async () => {
    const M = window.__cuarto.multiagente;
    const loop = await M.connect("chain-0", "chain-0", "entregar");
    const reverse = await M.connect("chain-1", "chain-0", "entregar");
    return { loop, reverse };
  });
  await sleep(250);
  ok(localRejects.loop.beforePlan && localRejects.reverse.beforePlan &&
    planRequests === beforeLocal,
    "bucle y A↔B se rechazan con causa ANTES de /plan", JSON.stringify(localRejects));
  const restrictionCut = await cuartoPage.evaluate(() => {
    const M = window.__cuarto.multiagente;
    M.setRestriction(false);
    const result = M.checkCable("chain-0", "chain-0", "entregar");
    M.setRestriction(true);
    return result;
  });
  ok(restrictionCut.ok === true,
    "CALIBRACIÓN ROJA · neutralizar restricción hace que el lienzo acepte el bucle local");

  const chainDraw = await cuartoPage.evaluate(() => ({
    state: window.__cuarto.multiagente.state(),
    draw: window.__cuarto.recintoDraw(),
  }));
  const middle = chainDraw.draw.find((x) => x.id === "chain-1");
  ok(middle && middle.hasNucleo === false,
    "eslabón del medio se dibuja sin Núcleo leyendo nucleo:false", JSON.stringify(middle));
  ok(chainDraw.state.visualCables.length === 2 &&
    chainDraw.state.visualCables.every((x) => x.tipo === "entregar" && x.arrows === 1 && !x.echo),
    "entregar-y-suelta se dibuja con una sola punta", JSON.stringify(chainDraw.state.visualCables));
  const delegarVisual = await cuartoPage.evaluate((refs) => {
    const C = window.__cuarto;
    C.multiagente.applyPlan({
      modo: "orquesta",
      eslabones: [
        { agent_ref: refs[0], slug: "ma-f1-extractor", nucleo: true },
        { agent_ref: refs[1], slug: "ma-f1-calculo", nucleo: true },
      ],
      cables: [{ from: "ma-f1-extractor", to: "ma-f1-calculo", tipo: "delegar" }],
    }, []);
    return new Promise((resolve) => setTimeout(() => resolve(C.multiagente.state().visualCables), 120));
  }, [A, B]);
  ok(delegarVisual[0] && delegarVisual[0].arrows === 2 && delegarVisual[0].echo === true,
    "delegar-y-vuelve se dibuja como ida+eco, sin etiqueta", JSON.stringify(delegarVisual));
  await cuartoPage.evaluate(({ plan, piezas }) => window.__cuarto.multiagente.applyPlan(plan, piezas),
    { plan, piezas });

  section("5 · cadena real: luz y latencia medida");
  await cuartoPage.evaluate((p) => window.__cuarto.multiagente.runStart(p), plan);
  const waitingRun = await cuartoPage.evaluate(() => ({
    state: window.__cuarto.multiagente.state(), draw: window.__cuarto.recintoDraw(),
  }));
  ok(waitingRun.state.running && waitingRun.state.activeHop === 0 &&
    waitingRun.state.displayedLatencies.length === 0,
    "mientras /run espera se enciende el primero sin inventar latencia");

  console.log("  … /run real en curso; las cifras vendrán del transcript del frozen");
  const runResult = await api("POST", "/v1/multiagente/run", {
    recipe: globo([A, B, C]), prompt: PROMPT, user_id: userId, deadline_s: 300,
  }, token);
  const run = runResult.json || {};
  ok(runResult.status === 201 && run.ok === true && Array.isArray(run.saltos) &&
    run.saltos.length === 3, "la cadena real completa tres saltos", JSON.stringify(run).slice(0, 500));
  ok(run.saltos.every((s) => Number.isInteger(s.latencia_ms) && s.latencia_ms > 0),
    "cada salto trae latencia_ms medida", JSON.stringify(run.saltos.map((s) => s.latencia_ms)));
  console.log(`  latencias medidas: ${run.saltos.map((s) => `${s.latencia_ms} ms`).join(" → ")}`);
  const replay = [];
  for (let i = 0; i < (run.saltos || []).length; i++) {
    replay.push(await cuartoPage.evaluate(({ i, ms }) => {
      const C = window.__cuarto;
      C.multiagente.hop(i, ms);
      return new Promise((resolve) => setTimeout(() => resolve({
        state: C.multiagente.state(), draw: C.recintoDraw(),
      }), 100));
    }, { i, ms: run.saltos[i].latencia_ms }));
  }
  ok(replay.map((x) => x.state.activeHop).join(",") === "0,1,2" &&
    replay.every((x, i) => x.state.displayedLatencies.some((v) => v.ms === run.saltos[i].latencia_ms)),
    "la luz recorre izquierda→derecha y aparece la cifra medida por salto");
  await cuartoPage.screenshot({ path: SHOT, fullPage: true });
  console.log(`  captura viva: ${SHOT}`);
  await cuartoPage.evaluate(() => window.__cuarto.multiagente.runStop());
  await sleep(120);
  const idle = await cuartoPage.evaluate(() => ({
    state: window.__cuarto.multiagente.state(), draw: window.__cuarto.recintoDraw(),
  }));
  ok(idle.state.displayedLatencies.length === 0 &&
    idle.draw.every((x) => x.latencyVisible === false),
    "reposo: cero números de latencia", JSON.stringify(idle));

  section("6 · muralla anti-fractal");
  const gestures = await cuartoPage.evaluate(() => window.__cuarto.multiagente.gestures());
  ok(gestures.zoomCoreOpensMind === false && gestures.pressAlephZooms === false &&
    gestures.zoomAlephEntersRoom === true && gestures.pressCoreOpensMind === true &&
    await cuartoPage.evaluate(() => window.__cuarto.multiagente.workersRendered() === 0),
    "workers jamás se dibujan; los cuatro gestos no se confunden");

  await cuartoPage.evaluate(() => {
    const C = window.__cuarto;
    C.cam.zoomAt(1.64 / C.cam.state.scale, 8, 8);
  });
  const coreCss = await cuartoPage.evaluate(() => window.__cuarto.artScreenOf("nucleo"));
  await cuartoPage.evaluate((p) => {
    const canvas = document.getElementById("cuarto"), r = canvas.getBoundingClientRect();
    canvas.dispatchEvent(new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: -100,
      clientX: r.left + p.x, clientY: r.top + p.y }));
  }, coreCss);
  await sleep(250);
  ok(await cuartoPage.evaluate(() => window.__cuarto.fractal().depth === 0),
    "zoom sobre el Núcleo NO abre la Mente ni cambia de Cuarto");
  await cuartoPage.evaluate(() => window.__openInspector(window.__cuarto.nucleoData()));
  const mindOpen = await cuartoPage.evaluate(() => {
    const sec = [...document.querySelectorAll("#d-opts .osec")]
      .find((x) => /La Mente/.test(x.textContent));
    return document.getElementById("inspector").classList.contains("open") &&
      sec && !sec.classList.contains("closed");
  });
  ok(mindOpen, "presionar el Núcleo abre su Mente existente");
  const pressAleph = await cuartoPage.evaluate(() => {
    const before = window.__cuarto.fractal().depth;
    window.__openInspector(window.__cuarto.pieceData("chain-0"));
    return { before, after: window.__cuarto.fractal().depth,
      inspector: document.getElementById("inspector").classList.contains("open") };
  });
  ok(pressAleph.before === pressAleph.after && pressAleph.inspector,
    "presionar un Aleph abre detalle pero NO hace zoom", JSON.stringify(pressAleph));

  section("7 · popup contenido");
  const popupCases = [
    { id: "popup-yf", label: "Yfinance", server: "yfinance", n: 40 },
    { id: "popup-ccxt", label: "CCXT", server: "ccxt", n: 52 },
  ];
  for (const fixture of popupCases) {
    const measured = await cuartoPage.evaluate(async (f) => {
      const C = window.__cuarto;
      C.placedTiles().forEach((t) => C.removeTile(t.id));
      const tools = Array.from({ length: f.n }, (_, i) => `extremely_long_tool_name_${f.server}_${i}`);
      C.placeTile({ id: f.id, label: f.label, server: f.server, category: "process", tools }, 3, 3);
      window.__openInspector(C.pieceData(f.id));
      const detail = [...document.querySelectorAll("#d-opts .osec")]
        .find((x) => /Detalle técnico/.test(x.textContent));
      const head = detail && detail.querySelector(".osec-h");
      if (head && detail.classList.contains("closed")) head.click();
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const card = document.getElementById("inspector").getBoundingClientRect();
      const val = [...document.querySelectorAll("#inspector .val")]
        .find((x) => /tools/.test(x.textContent));
      const box = val && val.getBoundingClientRect();
      return {
        card: { left: card.left, right: card.right, top: card.top, bottom: card.bottom },
        box: box && { left: box.left, right: box.right, top: box.top, bottom: box.bottom },
        text: document.getElementById("inspector").textContent,
        firstTool: tools[0], lastTool: tools[tools.length - 1],
      };
    }, fixture);
    ok(measured.box && measured.box.left >= measured.card.left - 0.5 &&
      measured.box.right <= measured.card.right + 0.5 &&
      measured.box.top >= measured.card.top - 0.5 &&
      measured.box.bottom <= measured.card.bottom + 0.5,
      `${fixture.label}: bbox del texto cabe dentro de la card`, JSON.stringify(measured));
    ok(new RegExp(`${fixture.n}\\s+tools`).test(measured.text) &&
      !measured.text.includes(measured.firstTool) && !measured.text.includes(measured.lastTool),
      `${fixture.label}: sólo N tools; cero lista cruda incluso con ${fixture.n}`, measured.text.slice(0, 220));
  }

  section("8 · un estado de modelo, tres lecturas");
  await cuartoPage.evaluate(() => {
    const C = window.__cuarto;
    C.placedTiles().forEach((t) => C.removeTile(t.id));
    window.__openInspector(C.nucleoData());
    document.getElementById("iprimary").click();
  });
  await cuartoPage.waitForSelector('#d-opts .ams-option[data-model="codex_cli"]');
  ok(/Claude Code/.test(await salaPage.locator("#powNow").textContent()),
    "precondición: Sala empieza leyendo Claude del mismo Default");
  const writesBefore = selector.writes.length;
  await cuartoPage.locator('#d-opts .ams-option[data-model="codex_cli"]').click();
  await waitUntil(() => selector.writes.length > writesBefore);
  await salaPage.waitForFunction(() => /Codex/.test(document.getElementById("powNow").textContent),
    null, { timeout: 10000 });
  await cuartoPage.waitForFunction(() =>
    document.getElementById("cuartoBrainDock")?.dataset.modelLogo === "codex_cli",
    null, { timeout: 10000 });
  const triad = await cuartoPage.evaluate(() => {
    const active = document.querySelector('#d-opts .ams-option[data-model="codex_cli"]');
    const inactive = document.querySelector('#d-opts .ams-option[data-model="claude_cli"]');
    const pill = document.getElementById("cuartoBrainDock");
    return {
      active: active && active.classList.contains("on"),
      activeText: active?.querySelector(".ams-use")?.textContent,
      inactiveText: inactive?.querySelector(".ams-use")?.textContent,
      pillLogo: pill?.dataset.modelLogo,
      pillGlyph: pill?.querySelector(".aleph-brain-logo")?.textContent,
      pillWidth: pill?.getBoundingClientRect().width,
    };
  });
  ok(triad.active && triad.activeText === "En uso" &&
    triad.inactiveText === "Usar este modelo",
    "widget declara En uso / Usar este modelo, no sólo borde", JSON.stringify(triad));
  ok(triad.pillLogo === "codex_cli" && triad.pillGlyph === "⌘" && triad.pillWidth <= 40,
    "chrome cambia al logo Codex y ocupa ancho de ícono", JSON.stringify(triad));
  await cuartoPage.locator("#cuartoBrainDock .aleph-brain-trigger").click();
  const popover = await cuartoPage.evaluate(() => {
    const pop = document.querySelector("#cuartoBrainDock .aleph-brain-pop");
    return { hidden: pop.hidden, text: pop.textContent.replace(/\s+/g, " ").trim() };
  });
  ok(!popover.hidden && /Codex/.test(popover.text) &&
    /Elegir o arreglar el modelo/.test(popover.text),
    "click del pill despliega nombre, estado y acción", JSON.stringify(popover));
  ok(/Codex/.test(await salaPage.locator("#powNow").textContent()),
    "Sala refleja Codex sin recargar");

  await cuartoPage.reload({ waitUntil: "domcontentloaded" });
  await cuartoPage.waitForFunction(() => window.__cuarto && window.AlephModelSelector &&
    window.__guideHost && document.querySelector("#cuartoBrainDock .aleph-brain-trigger"),
    null, { timeout: 90000 });
  await cuartoPage.evaluate(() => {
    window.__openInspector(window.__cuarto.nucleoData());
    document.getElementById("iprimary").click();
  });
  await cuartoPage.waitForSelector('#d-opts .ams-option[data-model="codex_cli"].on');
  ok(true, "recargar conserva Codex desde la preferencia persistida");

  selector.cutWrite = true;
  const beforeCut = selector.writes.length;
  await cuartoPage.locator('#d-opts .ams-option[data-model="claude_cli"]').click();
  await waitUntil(() => selector.writes.length > beforeCut);
  await sleep(250);
  const writeDetector = await cuartoPage.evaluate(() => ({
    node: document.querySelector('#d-opts .ams-option[data-model="claude_cli"]')?.classList.contains("on"),
    pill: document.getElementById("cuartoBrainDock")?.dataset.modelLogo,
  }));
  ok(writeDetector.node === true && writeDetector.pill === "codex_cli" &&
    /Codex/.test(await salaPage.locator("#powNow").textContent()),
    "CALIBRACIÓN ROJA · cortar escritura vuelve incoherente la tríada y la vara lo detecta",
    JSON.stringify(writeDetector));
  selector.cutWrite = false;
  await cuartoPage.reload({ waitUntil: "domcontentloaded" });
  await cuartoPage.waitForFunction(() => window.__cuarto &&
    window.__guideHost &&
    document.getElementById("cuartoBrainDock")?.dataset.modelLogo === "codex_cli",
    null, { timeout: 90000 });
  ok(true, "tras la escritura cortada, reload sigue en el último estado confirmado");

  selector.cutRead = true;
  const mutedPage = await context.newPage();
  attachErrors(mutedPage);
  await mutedPage.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" });
  await mutedPage.waitForFunction(() => document.querySelector("#cuartoBrainDock .aleph-brain-trigger"),
    null, { timeout: 90000 });
  const muted = await mutedPage.evaluate(() => ({
    id: document.getElementById("cuartoBrainDock")?.dataset.modelLogo,
    aria: document.getElementById("cuartoBrainDock")?.getAttribute("aria-label"),
  }));
  ok(muted.id === "none" && /sin leer/i.test(muted.aria || ""),
    "CALIBRACIÓN ROJA · cortar lectura deja el pill mudo y la vara lo detecta", JSON.stringify(muted));
  await mutedPage.close();
  selector.cutRead = false;

  ok(runtimeErrors.length === 0, "cero errores JS no esperados",
    runtimeErrors.slice(0, 5).join(" | "));
  await context.close();
} catch (error) {
  failures.push("harness");
  console.error("\nHARNESS ERROR:", error && error.stack || error);
} finally {
  if (browser) await browser.close().catch(() => {});
  matarFrozen(proc);
  rmSync(DATADIR, { recursive: true, force: true });
}

ok(!(await portOpen()), `cierre: :${PORT} quedó libre`);
console.log(`\n${failures.length
  ? `MULTIAGENTE F2 ROJO · ${failures.length} falla(s) · ${PASS} PASS`
  : `MULTIAGENTE F2 VERDE · ${PASS} PASS`}`);
if (failures.length) {
  failures.forEach((f) => console.log(`  - ${f}`));
  process.exit(1);
}
