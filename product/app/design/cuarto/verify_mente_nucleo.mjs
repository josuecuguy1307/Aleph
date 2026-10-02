#!/usr/bin/env node
/**
 * verify_mente_nucleo.mjs — OLA 4 · §3 · LA MENTE DEL NÚCLEO (workers efímeros + plan vivo).
 *
 * Driva el MISMO mapeo compartido que consume el SSE real de producción
 * (window.__cuartoApplyFrontierEvent / __cuartoReplayEvent) con eventos `ephemeral:true` fixture
 * y verifica la muralla anti-fractal (§1) + el inspector-Mente (§3):
 *   M.1 worker ephemeral → NO enciende recinto (aunque el id resuelva) NI #teamtasks; SÍ entra a La Mente.
 *   M.2 finished ephemeral → estado done + model_final REAL; sigue sin tocar diorama/teamtasks.
 *   M.3 sub_agent NO-ephemeral (sub-agente real) → SÍ alimenta #teamtasks (retro-compat: sólo el worker se desvía).
 *   M.4 plan_declared con `decompose` → Plan vivo del run.
 *   M.5 delegation_serialized ephemeral → nota de serialización en La Mente.
 *   M.6 abrir el inspector del Núcleo → La Mente RENDERIZA los carriles reales (workers + plan + slot workers).
 *   M.7 worker guión + escalado → chips «guión» / «escaló al principal» desde eventos reales.
 *   M.8 reset por run → La Mente vuelve a vacío (cero teatro, cero worker fantasma).
 * Run: node product/app/design/cuarto/verify_mente_nucleo.mjs (autocontenido)
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PIXI_ENTRY = join(DESIGN_DIR, "cuarto", "cuarto.pixi.html");
// Python elige y mantiene el puerto dentro del mismo bind. Así no hay carrera entre
// “reservar” un puerto y soltarlo antes de que arranque el servidor real.
const serverCode = "import http.server,sys; from functools import partial; s=http.server.ThreadingHTTPServer(('127.0.0.1',0),partial(http.server.SimpleHTTPRequestHandler,directory=sys.argv[1])); print(s.server_address[1],flush=True); s.serve_forever()";
const server = spawn("python3", ["-u", "-c", serverCode, DESIGN_DIR], { stdio: ["ignore", "pipe", "inherit"] });
const PORT = await new Promise((resolve, reject) => {
  let output = "";
  server.stdout.setEncoding("utf8");
  server.stdout.on("data", (chunk) => {
    output += chunk;
    const line = output.split(/\r?\n/, 1)[0].trim();
    if (/^\d+$/.test(line)) resolve(Number(line));
  });
  server.once("error", reject);
  server.once("exit", (code) => reject(new Error(`Pixi test server exited before bind (code ${code}): ${output}`)));
});
const PAGE_URL = `http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html`;

let PASS = 0, FAIL = 0; const FAILED = [];
function check(name, ok, detail = "") {
  if (ok) { PASS++; console.log(`  PASS  ${name}`); }
  else { FAIL++; FAILED.push(name); console.log(`  FAIL  ${name}${detail ? " — " + detail : ""}`); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let browser;
try {
  browser = await chromium.launch(process.env.ALEPH_CHROMIUM_PATH
    ? { executablePath: process.env.ALEPH_CHROMIUM_PATH } : {});
} catch (error) {
  server.kill();
  throw error;
}
const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
const errors = [];
const consoleErrors = [];
const fixture404s = [];
page.on("pageerror", (e) => errors.push(e && e.stack ? e.stack : String(e)));
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
page.on("response", (r) => {
  if (r.status() === 404) fixture404s.push({ url: r.url(), status: r.status() });
});

// El arranque del Guía resuelve su modelo por el mismo catálogo/cache que compileModel().
// Se inyecta antes de navegar: un modelo conectado falso evita una llamada real y evita que
// el fixture falle por arrancar con selector vacío. Este harness nunca ejecuta al proveedor.
const modelSelectorRequests = [];
await page.route("**/v1/brains/status*", (route) => route.fulfill({
  status: 200, contentType: "application/json", body: JSON.stringify({ providers: {} }),
}));
await page.route("**/v1/modelos/selector*", (route) => {
  modelSelectorRequests.push(route.request().url());
  console.log("Mente fake model fixture:", route.request().url(), "→ fixture-opus");
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    version: 2, default: "fixture-opus", default_id: "fixture-opus", seleccion_id: "fixture-opus",
    modelos: [{ slug: "fixture-opus", picker_id: "fixture-opus", id: "fixture-opus",
      label: "Opus (test fixture)", model: "fixture/no-provider-call",
      base_url: "http://127.0.0.1/fixture", estado: "probado", conectado: true,
      default: true, frontier: true }],
  }) });
});

try {
  await page.goto(PAGE_URL);
  const pageProof = await page.evaluate(() => ({
    url: location.href,
    title: document.title,
    teamtasks: !!document.getElementById("teamtasks"),
    taskBody: !!document.getElementById("ttBody"),
    taskCount: !!document.getElementById("ttCount"),
    tipcard: !!document.getElementById("tipcard"),
  }));
  console.log("Pixi entry proof:", JSON.stringify({ requested: PAGE_URL, path: PIXI_ENTRY, ...pageProof }));
  const pathOk = new URL(pageProof.url).pathname === "/cuarto/cuarto.pixi.html";
  const fixtureOk = pathOk && pageProof.teamtasks && pageProof.taskBody && pageProof.taskCount && pageProof.tipcard;
  check("fixture Pixi · URL y DOM exactos de producción", fixtureOk, JSON.stringify(pageProof));
  if (!fixtureOk) throw new Error(`Entrada Pixi incorrecta: requested=${PAGE_URL}; served=${pageProof.url}; file=${PIXI_ENTRY}`);
  await page.evaluate(() => { window.__menteInitialDocument = document; });
  await page.waitForFunction(() => typeof window.__cuartoApplyFrontierEvent === "function"
    && typeof window.__cuartoMenteState === "function", null, { timeout: 20000 });
  await sleep(500);
  const fixtureModels = await page.evaluate(() => (window.__models?.list || [])
    .filter((m) => m.connected === true || m.conectado === true)
    .map((m) => ({ id: m.id, model: m.model })));
  const guideFixtureId = await page.evaluate(() => window.__guideBrainId?.() || null);
  console.log("Mente connected fake model before tests:", JSON.stringify(fixtureModels),
    "guideModelId=", guideFixtureId, "selectorRequests=", JSON.stringify(modelSelectorRequests));
  if (!modelSelectorRequests.length || fixtureModels.length < 1
      || fixtureModels[0].model !== "fixture/no-provider-call"
      || guideFixtureId !== fixtureModels[0].id) {
    throw new Error(`Missing connected fake model before M.1–M.10; no provider call will be made. selectorRequests=${JSON.stringify(modelSelectorRequests)} models=${JSON.stringify(fixtureModels)}`);
  }
  const compileProof = await page.evaluate(async (id) => {
    const { compileModel } = await import("./cuarto.models.js");
    const model = compileModel(id);
    return { id, primary: model.primary, base_url: model.base_url };
  }, fixtureModels[0].id);
  console.log("Mente fake compileModel proof:", JSON.stringify(compileProof));
  if (compileProof.primary !== "fixture/no-provider-call")
    throw new Error(`compileModel did not resolve the fake model before M.1–M.10: ${JSON.stringify(compileProof)}`);

  // Espía recintoRun: la muralla §1 exige que un evento ephemeral JAMÁS lo llame (sería una pieza en el diorama).
  await page.evaluate(() => {
    window.__recintoCalls = [];
    const o = window.__cuarto.recintoRun;
    window.__cuarto.recintoRun = function (...a) { window.__recintoCalls.push(a); return o && o.apply(this, a); };
    window.__cuartoMenteReset(); window.__cuartoTeamTasksReset();
  });

  const menteState = () => page.evaluate(() => window.__cuartoMenteState());
  const teamHidden = () => page.evaluate(() => { const el = document.getElementById("teamtasks"); return !el || el.hidden; });
  const recintoCalls = () => page.evaluate(() => window.__recintoCalls.length);

  // ── M.1 · worker ephemeral: resolveId DEVUELVE un id truthy a propósito → si el filtro fallara,
  //         recintoRun se llamaría. Debe cortar ANTES: sin recinto, sin teamtasks, sí en La Mente.
  await page.evaluate(() => {
    window.__cuartoApplyFrontierEvent("sub_agent_started", {
      ephemeral: true, worker_id: "w1-2-0", worker_kind: "lectores", routed: "economico",
      route_reason: "'leer' → lectura", step_n: 2, declared: true,
      task: "leé la fuente A y extraé los tickers", turn: 1,
    }, () => "RECINTO_FAKE_ID");
  });
  let ms = await menteState();
  check("M.1 worker ephemeral → NO enciende recinto (aunque el id resuelva)", (await recintoCalls()) === 0);
  check("M.1 worker ephemeral → NO entra a #teamtasks", (await teamHidden()) === true);
  check("M.1 worker ephemeral → SÍ entra a La Mente (st run, routed económico, step_n)",
    ms.workers.length === 1 && ms.workers[0].worker_id === "w1-2-0"
    && ms.workers[0].st === "run" && ms.workers[0].routed === "economico" && ms.workers[0].step_n === 2,
    JSON.stringify(ms.workers));

  // ── M.2 · finished ephemeral → done + model_final REAL; sigue sin tocar diorama/teamtasks
  await page.evaluate(() => {
    window.__cuartoApplyFrontierEvent("sub_agent_finished", {
      ephemeral: true, worker_id: "w1-2-0", worker_kind: "lectores", routed: "economico",
      status: "ok", child_ok: true, model_final: "econ-oss", spent: { input_tokens_est: 42 }, turn: 1,
    }, () => "RECINTO_FAKE_ID");
  });
  ms = await menteState();
  check("M.2 finished ephemeral → estado done + model_final REAL (econ-oss)",
    ms.workers[0].st === "done" && ms.workers[0].model_final === "econ-oss"
    && ms.workers[0].spent && ms.workers[0].spent.input_tokens_est === 42, JSON.stringify(ms.workers[0]));
  check("M.2 tras dos eventos ephemeral: recintoRun sigue en CERO + #teamtasks ausente",
    (await recintoCalls()) === 0 && (await teamHidden()) === true);

  // ── M.3 · sub-agente REAL (sin ephemeral) → SÍ alimenta #teamtasks (sólo el worker se desvía)
  const m3Payload = { type: "sub_agent_started", ephemeral: false, slug: "analista", meta_name: "Analista",
    task: "tarea de un sub-agente real", depth: 1, turn: 5 };
  await page.evaluate((payload) => window.__cuartoReplayEvent(payload), m3Payload);
  const teamAfterReal = await page.evaluate(() => {
    const el = document.getElementById("teamtasks");
    return { exists: !!el, hidden: !el || el.hidden, rows: [...document.querySelectorAll("#teamtasks .tt-row")].map((r) => r.textContent) };
  });
  ms = await menteState();
  check("M.3 sub-agente NO-ephemeral → SÍ aparece en #teamtasks (retro-compat intacta)",
    teamAfterReal.hidden === false && teamAfterReal.rows.some((t) => /sub-agente real/.test(t)),
    JSON.stringify(teamAfterReal));
  check("M.3 el sub-agente real NO se cuela en La Mente (sólo workers ephemeral viven ahí)",
    ms.workers.length === 1 && ms.workers[0].worker_id === "w1-2-0", JSON.stringify(ms.workers.map((w) => w.worker_id)));

  // ── M.4 · plan_declared con decompose → Plan vivo
  await page.evaluate(() => {
    window.__cuartoApplyFrontierEvent("plan_declared", { steps: [
      { n: 1, paso: "preparar el terreno", tool: null },
      { n: 2, paso: "repartir la lectura de fuentes", tool: "repartir_en_workers",
        decompose: { kind: "lectores", n: 3, perfil: "economico" } },
      { n: 3, paso: "sintetizar", tool: null },
    ], turn: 1 }, () => null);
  });
  ms = await menteState();
  const step2 = (ms.plan && ms.plan.steps || []).find((s) => s.n === 2);
  check("M.4 plan_declared → Plan vivo con `decompose` preservado (paso 2 → 3 workers económicos)",
    ms.plan && ms.plan.steps.length === 3 && step2 && step2.decompose
    && step2.decompose.n === 3 && step2.decompose.perfil === "economico", JSON.stringify(ms.plan));

  // ── M.5 · delegation_serialized ephemeral → nota de serialización
  await page.evaluate(() => {
    window.__cuartoApplyFrontierEvent("delegation_serialized", { ephemeral: true, cause: "provider_saturated",
      requested: 3, max_parallel: 1, leyenda: "El cerebro económico corre local; los workers van en fila." }, () => null);
  });
  ms = await menteState();
  check("M.5 delegation_serialized ephemeral → nota de serialización (provider_saturated)",
    ms.serialized && ms.serialized.cause === "provider_saturated" && ms.serialized.max_parallel === 1,
    JSON.stringify(ms.serialized));

  // ── M.7 (antes del render) · sumá un worker guión + uno escalado, para que el DOM muestre sus chips
  await page.evaluate(() => {
    window.__cuartoApplyFrontierEvent("sub_agent_started", { ephemeral: true, worker_id: "w1-3-0",
      worker_kind: "guion", routed: "economico", step_n: 3, task: "sumá el lote y devolvé el total", turn: 1 }, () => "X");
    window.__cuartoApplyFrontierEvent("sub_agent_finished", { ephemeral: true, worker_id: "w1-3-0",
      worker_kind: "guion", routed: "economico", status: "ok", child_ok: true, model_final: "econ-oss", turn: 1 }, () => "X");
    window.__cuartoApplyFrontierEvent("sub_agent_started", { ephemeral: true, worker_id: "w1-4-0",
      worker_kind: "lectores", routed: "economico", step_n: 4, task: "leé la fuente que falla", turn: 1 }, () => "X");
    window.__cuartoApplyFrontierEvent("sub_agent_finished", { ephemeral: true, worker_id: "w1-4-0",
      worker_kind: "lectores", routed: "principal", status: "ok", child_ok: true, model_final: "principal-brain",
      escalated: { retried: true, from: "econ-oss", to: "principal-brain", reason: "vacío" }, turn: 1 }, () => "X");
  });

  // ── M.6 · abrir el inspector del Núcleo → La Mente renderiza los carriles REALES
  const tipProof = await page.evaluate(() => ({ url: location.href,
    sameDocument: document === window.__menteInitialDocument,
    tipcardExists: !!document.getElementById("tipcard"),
    tipcardConnected: !!(document.getElementById("tipcard") && document.getElementById("tipcard").isConnected),
    startupError: document.querySelector("#stage > pre.err")?.textContent || null }));
  console.log("Before openInspector/closeTip DOM proof:", JSON.stringify({ ...tipProof, fixture404s }));
  // La entrada Pixi de producción puede pedir recursos/API que el servidor estático del
  // fixture no implementa. Esos 404 ya se observan arriba, pero no hacen que closeTip
  // pierda #tipcard: sólo el documento/DOM distinto lo invalidaría. Las excepciones JS
  // inesperadas siguen acumulándose en `errors` y M.9 las mantiene fatales.
  if (!tipProof.sameDocument || !tipProof.tipcardExists || !tipProof.tipcardConnected)
    throw new Error(`Pixi document/DOM invalid before openInspector: ${JSON.stringify({ ...tipProof, fixture404s, consoleErrors })}`);
  await page.evaluate(() => { window.__openInspector(window.__cuarto.nucleoData()); });
  await sleep(300);
  const closeTipResult = await page.evaluate(() => ({
    inspectorOpen: document.getElementById("inspector")?.classList.contains("open") === true,
    tipcardExists: !!document.getElementById("tipcard"),
    tipcardHidden: document.getElementById("tipcard")?.hidden === true,
  }));
  check("M.6 openInspector → closeTip cierra la tarjeta existente y abre el inspector",
    closeTipResult.inspectorOpen && closeTipResult.tipcardExists && closeTipResult.tipcardHidden,
    JSON.stringify(closeTipResult));
  const dom = await page.evaluate(() => ({
    rows: [...document.querySelectorAll("#mente-workers-body .mw-row")].map((r) => ({ cls: r.className, txt: r.textContent })),
    plan: [...document.querySelectorAll("#mente-plan-body .mp-row")].map((r) => r.textContent),
    dec: !!document.querySelector("#mente-plan-body .mp-dec"),
    guionChip: [...document.querySelectorAll("#mente-workers-body .mw-chip.guion")].map((c) => c.textContent),
    escChip: [...document.querySelectorAll("#mente-workers-body .mw-chip.esc")].map((c) => c.textContent),
    hasWorkersBrain: !!document.getElementById("workersBrainSel"),
    modelTexts: [...document.querySelectorAll("#mente-workers-body .mw-model")].map((c) => c.textContent),
  }));
  check("M.6 inspector del Núcleo → La Mente RENDERIZA los workers reales (3: lector done, guión, escalado)",
    dom.rows.length === 3 && dom.rows.some((r) => /done/.test(r.cls)), JSON.stringify(dom.rows.map((r) => r.cls)));
  check("M.6 La Mente renderiza el Plan vivo con la anotación de descomposición (mp-dec)",
    dom.plan.length === 3 && dom.dec === true, JSON.stringify(dom.plan));
  check("M.6 el slot 'Cerebro de los workers' está presente (UI net-new)", dom.hasWorkersBrain === true);
  check("M.6 model_final REAL por worker visible en el DOM (econ-oss / principal-brain)",
    dom.modelTexts.some((t) => /econ-oss/.test(t)) && dom.modelTexts.some((t) => /principal-brain/.test(t)),
    JSON.stringify(dom.modelTexts));

  // ── M.7 · chips desde eventos reales
  check("M.7 worker guión → chip «guión»; worker escalado → chip «escaló al principal»",
    dom.guionChip.some((t) => /guión/.test(t)) && dom.escChip.some((t) => /escaló/.test(t)),
    JSON.stringify({ guion: dom.guionChip, esc: dom.escChip }));

  // ── M.8 · reset por run → La Mente vacía + DOM vuelve a "sin workers"
  const afterReset = await page.evaluate(() => {
    window.__cuartoMenteReset();
    return { st: window.__cuartoMenteState(),
      emptyDom: !!document.querySelector("#mente-workers-body .mente-empty"),
      recinto: window.__recintoCalls.length };
  });
  check("M.8 reset por run → La Mente vacía (0 workers, sin plan, sin nota)",
    afterReset.st.workers.length === 0 && !afterReset.st.plan && !afterReset.st.serialized
    && afterReset.emptyDom === true, JSON.stringify(afterReset.st));
  check("M.8 INVARIANTE §1 · en TODA la corrida recintoRun NUNCA fue llamado por un worker",
    afterReset.recinto === 0, "recintoCalls=" + afterReset.recinto);

  // ── M.10 · i18n (review §5) — bajo lang=en La Mente renderiza en INGLÉS (cero español). Repinta
  //          un worker guión + un lector escalado y abre el inspector con lang=en. ──
  await page.evaluate(() => {
    localStorage.setItem("aleph-lang", "en");
    window.dispatchEvent(new CustomEvent("aleph:langchange", { detail: { lang: "en" } }));
    window.__cuartoMenteReset();
    window.__cuartoApplyFrontierEvent("plan_declared", { steps: [{ n: 2, paso: "read", decompose: { kind: "lectores", n: 3, perfil: "economico" } }], turn: 1 }, () => null);
    window.__cuartoApplyFrontierEvent("sub_agent_started", { ephemeral: true, worker_id: "w1-2-0", worker_kind: "guion", routed: "economico", step_n: 2, task: "sum the batch", turn: 1 }, () => "X");
    window.__cuartoApplyFrontierEvent("sub_agent_finished", { ephemeral: true, worker_id: "w1-2-0", worker_kind: "guion", routed: "principal", status: "ok", child_ok: true, model_final: "econ-oss", escalated: { retried: true }, turn: 1 }, () => "X");
    window.__openInspector(window.__cuarto.nucleoData());
  });
  await sleep(120);   // el rename §4 traduce por el MutationObserver del TM (async, microtask tras el innerHTML)
  const i18n = await page.evaluate(() => {
    const opts = document.getElementById("d-opts"), txt = opts ? opts.textContent : "";
    const toneLabel = opts?.querySelector("#nuc-instr")?.closest(".field")?.querySelector(".k")?.textContent?.trim() || null;
    return {
      en: /Auxiliary agent model/.test(txt) && /THE MIND · EXECUTION/.test(txt) && /Active execution plan/.test(txt) && /Active auxiliary agents/.test(txt) && /Inherit the main model/.test(txt),
      chipsEN: /script/.test(txt) && /escalated to main/.test(txt) && /step 2/.test(txt),
      toneLabel,
      renameEN: toneLabel === window.AlephI18n.t("workshop.inspector.memory.context")
        && toneLabel === "Tone and context",
      spanishLeak: /Cerebro de los workers|La Mente ·|Plan vivo|Workers en vivo|Hereda el cerebro principal|escaló al principal|Agentes auxiliares/.test(txt),
    };
  });
  check("M.10 · i18n: bajo lang=en los widgets §3 (La Mente + slot workers) renderizan en inglés",
    i18n.en === true && i18n.chipsEN === true, JSON.stringify(i18n));
  check("M.10 · i18n: el label semántico §4 usa su clave EN y no filtra español en La Mente",
    i18n.renameEN === true && i18n.spanishLeak === false, JSON.stringify(i18n));

  check("M.9 sin errores JS de página", errors.length === 0, errors.slice(0, 2).join(" | "));
  console.log("Static-fixture 404s (diagnostic only):", JSON.stringify(fixture404s));
} finally {
  await browser.close(); server.kill();
}

console.log(`\n${FAIL === 0 ? "VERDE" : "ROJO"} — ${PASS} PASS · ${FAIL} FAIL`);
if (FAILED.length) FAILED.forEach((f) => console.log(`  ✗ ${f}`));
process.exit(FAIL === 0 ? 0 : 1);
