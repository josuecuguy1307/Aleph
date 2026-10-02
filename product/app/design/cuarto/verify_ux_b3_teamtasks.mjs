#!/usr/bin/env node
/**
 * verify_ux_b3_teamtasks.mjs — B3 · mini task-list por agente en el Cuarto (run multiagente).
 *
 * Driva window.__cuartoReplayEvent (el MISMO mapeo compartido que consume el SSE real de
 * producción — FIX D) con eventos sub_agent_* fixture y verifica el panel #teamtasks:
 *   · sin eventos → panel AUSENTE (run sin delegación no muestra nada)
 *   · sub_agent_started.task → fila «en curso» bajo el agente correcto
 *   · sub_agent_finished ok → «hecho» · con held>0 → «espera tu OK» · error → «falló»
 *   · una tarea sin finished QUEDA en curso (cero autocompletado fake)
 *   · reset por run → panel vuelve a ausente · colapsable
 * Run: node product/app/design/cuarto/verify_ux_b3_teamtasks.mjs (autocontenido)
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = 8109;
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

let PASS = 0, FAIL = 0; const FAILED = [];
function check(name, ok, detail = "") {
  if (ok) { PASS++; console.log(`  PASS  ${name}`); }
  else { FAIL++; FAILED.push(name); console.log(`  FAIL  ${name}${detail ? " — " + detail : ""}`); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"],
  { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));

try {
  await page.goto(PAGE_URL);
  await page.waitForFunction(() => typeof window.__cuartoReplayEvent === "function", { timeout: 20000 });
  await sleep(500);

  const state = () => page.evaluate(() => {
    const el = document.getElementById("teamtasks");
    return {
      hidden: !el || el.hidden,
      agents: [...document.querySelectorAll("#teamtasks .tt-agent")].map((a) => a.textContent),
      rows: [...document.querySelectorAll("#teamtasks .tt-row")].map((r) => ({
        st: r.className.replace("tt-row", "").trim(), txt: r.textContent })),
      count: (document.getElementById("ttCount") || {}).textContent || "",
    };
  });

  let st = await state();
  check("B3.1 sin eventos → panel AUSENTE", st.hidden === true);

  await page.evaluate(() => {
    window.__cuartoReplayEvent({ type: "sub_agent_started", slug: "analista", meta_name: "Analista",
      task: "buscar los tickers del sector", depth: 1, turn: 1 });
  });
  st = await state();
  check("B3.2 started → panel con la tarea REAL «en curso»",
    !st.hidden && st.agents.length === 1 && st.rows.length === 1 && st.rows[0].st === "run"
    && /buscar los tickers/.test(st.rows[0].txt), JSON.stringify(st.rows));

  await page.evaluate(() => {
    window.__cuartoReplayEvent({ type: "sub_agent_started", slug: "redactor", meta_name: "Redactor",
      task: "armar el informe final", depth: 1, turn: 2 });
    window.__cuartoReplayEvent({ type: "sub_agent_started", slug: "analista", meta_name: "Analista",
      task: "chequear los precios de cierre", depth: 1, turn: 3 });
  });
  st = await state();
  check("B3.3 varios agentes → cada recinto con SU lista (2 agentes, 3 tareas)",
    st.agents.length === 2 && st.rows.length === 3 && st.count === "(3)", JSON.stringify(st.agents));

  await page.evaluate(() => {
    window.__cuartoReplayEvent({ type: "sub_agent_finished", slug: "analista", status: "ok",
      child_ok: true, held: 0, depth: 1, turn: 1 });
  });
  st = await state();
  const analistaRows = st.rows.filter((r) => /tickers|precios/.test(r.txt));
  check("B3.4 finished ok marca UNA tarea «hecho» (la otra sigue en curso)",
    analistaRows.some((r) => r.st === "done") && analistaRows.some((r) => r.st === "run"),
    JSON.stringify(analistaRows));

  await page.evaluate(() => {
    window.__cuartoReplayEvent({ type: "sub_agent_finished", slug: "redactor", status: "gate",
      child_ok: true, held: 2, depth: 1, turn: 2 });
  });
  st = await state();
  check("B3.5 finished con held>0 → «espera tu OK» (jamás hecho)",
    st.rows.some((r) => r.st === "held" && /espera tu OK/.test(r.txt)),
    JSON.stringify(st.rows.map((r) => r.st)));

  check("B3.6 la tarea sin finished QUEDA en curso (cero autocompletado)",
    st.rows.some((r) => r.st === "run" && /precios/.test(r.txt)));

  // error path + colapso + reset
  await page.evaluate(() => {
    window.__cuartoReplayEvent({ type: "sub_agent_started", slug: "qa", meta_name: "QA", task: "validar", turn: 4 });
    window.__cuartoReplayEvent({ type: "sub_agent_finished", slug: "qa", status: "error", child_ok: false, held: 0, turn: 4 });
  });
  st = await state();
  check("B3.7 finished error → «falló»", st.rows.some((r) => r.st === "err" && /validar/.test(r.txt)));

  const collapsed = await page.evaluate(() => {
    document.getElementById("ttHead").click();
    const closed = document.getElementById("teamtasks").classList.contains("closed");
    document.getElementById("ttHead").click();
    return closed;
  });
  check("B3.8 el panel es colapsable", collapsed === true);

  const afterReset = await page.evaluate(() => {
    window.__cuartoTeamTasksReset();
    return document.getElementById("teamtasks").hidden;
  });
  check("B3.9 run nuevo (reset) → panel vuelve a ausente", afterReset === true);

  check("B3.10 sin errores JS de página", errors.length === 0, errors.slice(0, 2).join(" | "));
} finally {
  await browser.close(); server.kill();
}

console.log(`\n${FAIL === 0 ? "VERDE" : "ROJO"} — ${PASS} PASS · ${FAIL} FAIL`);
if (FAILED.length) FAILED.forEach((f) => console.log(`  ✗ ${f}`));
process.exit(FAIL === 0 ? 0 : 1);
