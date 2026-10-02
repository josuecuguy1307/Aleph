/* capture_metodo.mjs — capturas REALES de la pieza Método (Chromium, stubs /v1).
 * Mismo andamiaje que los verifies: server estático + sesión inyectada + seams.
 * Salida: metodo/screenshots/*.png (dark, ES).   Run: node capture_metodo.mjs */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = fileURLToPath(new URL("..", import.meta.url));
const OUT = HERE + "screenshots/";
mkdirSync(OUT, { recursive: true });
const PORT = 8179;
const PAGE = `http://localhost:${PORT}/metodo/metodo.html`;
const SALA = `http://localhost:${PORT}/sala/sala.html`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const M1 = { id: "m-earnings", name: "Cierre de earnings", steps: [
  { id: "s1", text: "Bajar el 10-Q de la SEC", phase: "Recolectar", checkpoint: false, executor: "sec_edgar", evidence_hint: null, timeout: null, retries: 3 },
  { id: "s1b", text: "Traer los precios del trimestre", phase: "Recolectar", checkpoint: false, executor: "yfinance", evidence_hint: null, timeout: null, retries: 3 },
  { id: "s2", text: "Comparar márgenes YoY contra el guidance", phase: "Analizar", checkpoint: false, executor: null, evidence_hint: null, timeout: null, retries: 3 },
  { id: "s2b", text: "Armar la planilla con el cierre", phase: "Analizar", checkpoint: false, executor: "excel", evidence_hint: "xlsx con las 4 métricas", timeout: 120, retries: 3 },
  { id: "s3", text: "Redactar el resumen ejecutivo", phase: "Entregar", checkpoint: false, executor: null, evidence_hint: null, timeout: null, retries: 3 },
  { id: "s4", text: "Enviar el resumen al equipo", phase: "Entregar", checkpoint: true, executor: "gmail", evidence_hint: null, timeout: null, retries: 3 },
] };
const M2 = { id: "m-semanal", name: "Chequeo semanal de cartera", steps: [
  { id: "t1", text: "Revisar los movimientos de la semana", phase: "Revisar", checkpoint: false, executor: "yfinance", evidence_hint: null, timeout: null, retries: 3 },
  { id: "t2", text: "Anotar lo que se salió del plan", phase: "Revisar", checkpoint: false, executor: null, evidence_hint: null, timeout: null, retries: 3 },
] };

async function newPage(browser, extra) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  await page.addInitScript(() => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u-1", session_token: "tok-1", email: "demo@example.invalid" }));
  });
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.route("**/v1/methods", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ methods: [M1, M2] }) }));
  await page.route("**/v1/methods/m-earnings", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(M1) }));
  if (extra) await extra(page);
  return page;
}

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);
const browser = await chromium.launch();
try {
  /* 01 · biblioteca + hero */
  {
    const p = await newPage(browser);
    await p.goto(PAGE, { waitUntil: "load" });
    await p.waitForFunction(() => window.__metodo && window.__metodo.state.methods.length === 2, null, { timeout: 9000 });
    await sleep(400);
    await p.screenshot({ path: OUT + "01-biblioteca.png" });

    /* 02 · editor Simple */
    await p.evaluate(() => [...document.querySelectorAll(".met-card")].find((c) => /Cierre/.test(c.textContent)).click());
    await p.waitForFunction(() => window.__metodoEditor, null, { timeout: 5000 });
    await sleep(350);
    await p.screenshot({ path: OUT + "02-editor-simple.png" });

    /* 03 · editor Pro (chips por paso) */
    await p.evaluate(() => document.querySelector('[data-ed-sw] button[data-sw="pro"]').click());
    await sleep(350);
    await p.screenshot({ path: OUT + "03-editor-pro.png" });

    /* 04 · editar conversando (diff propuesto) */
    await p.route("**/v1/methods/m-earnings/propose_edit", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      summary: "Valida el RUC del cliente antes de enviar y afina el análisis contra guidance.",
      proposal: { steps: M1.steps.filter((s) => s.id !== "s3").map((s) => s.id === "s2" ? Object.assign({}, s, { text: "Comparar márgenes YoY contra guidance y consenso" }) : s)
        .concat([{ id: "s9", text: "Validar el RUC del cliente", phase: "Entregar", checkpoint: false, executor: null, evidence_hint: null, timeout: null, retries: 3 }]) } }) }));
    await p.evaluate(() => document.querySelector('[data-ed-sw] button[data-sw="simple"]').click());
    await sleep(200);
    await p.fill("[data-conv-in]", "agrega un paso que valide el RUC antes de enviar");
    await p.evaluate(() => document.querySelector("[data-conv-go]").click());
    await p.waitForSelector(".ed-diff", { timeout: 5000 });
    await p.evaluate(() => document.querySelector(".ed-diff").scrollIntoView({ block: "center" }));
    await sleep(300);
    await p.screenshot({ path: OUT + "04-editar-conversando.png" });

    /* 05 · captura "Traer mi proceso" */
    await p.evaluate(() => document.querySelector("[data-diff-no]").click());
    await sleep(150);
    await p.evaluate(() => window.__metodo.traerProceso());
    await p.waitForSelector(".met-scrim [data-cap-ta]", { timeout: 5000 });
    await p.fill(".met-scrim [data-cap-ta]", "primero llamo al cliente y le pregunto qué necesita,\ndespués armo la cotización con los precios de la lista,\nse la mando por correo y agendo el seguimiento a los 3 días");
    await sleep(200);
    await p.screenshot({ path: OUT + "05-traer-mi-proceso.png" });
    await p.close();
  }

  /* 06 · grafo estático (el método respira) */
  {
    const p = await newPage(browser);
    await p.goto(PAGE + "?view=grafo&method=m-earnings", { waitUntil: "load" });
    await p.waitForFunction(() => window.__metodoGraph, null, { timeout: 9000 });
    await sleep(2200);   // la física se asienta, la red respira
    await p.screenshot({ path: OUT + "06-grafo-estatico.png" });
    await p.close();
  }

  /* 07 · grafo VIVO (chispa + brasa + checkpoint + fallo) + 08 · card de remedios */
  {
    const p = await newPage(browser, async (pg) => {
      await pg.route("**/v1/spaces/**", (r) => r.fulfill({ status: 200, contentType: "text/event-stream", body: "" }));
      await pg.route("**/v1/runs/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) }));
    });
    await p.goto(PAGE + "?view=grafo&method=m-earnings&space=sp-1&run=r-1", { waitUntil: "load" });
    await p.waitForFunction(() => window.__metodoGraph, null, { timeout: 9000 });
    await sleep(1800);
    // historia real: recolectó (brasa), está analizando (chispa), y el envío se trabó (ámbar)
    await p.evaluate(() => {
      const g = window.__metodoGraph;
      g.feed({ type: "method_step_started", step_id: "s1", executor: "sec_edgar" });
      g.feed({ type: "tool_call_finished", tool: "sec_edgar", status: "ok", result: {} });
      g.feed({ type: "method_step_done", executor: "sec_edgar" });
      g.feed({ type: "method_step_started", step_id: "s1b", executor: "yfinance" });
      g.feed({ type: "tool_call_finished", tool: "yfinance", status: "ok", result: {} });
      g.feed({ type: "method_step_done", executor: "yfinance" });
      g._tick(14);   // las primeras piezas decaen a brasa
      g.feed({ type: "method_step_started", step_id: "s2b", executor: "excel" });   // chispa AHORA
      g.feed({ type: "method_step_failed", step_id: "s4", executor: "gmail", run_id: "r-1",
        diagnosis: "credencial de gmail vencida — el conector pide re-conexión",
        remedies: { suggested_label: "reconectar gmail" } });
    });
    await sleep(900);   // partículas en vuelo + pulso ámbar visibles
    await p.screenshot({ path: OUT + "07-grafo-vivo.png" });
    await p.evaluate(() => window.__metodoGraph._clickNode("gmail"));
    await p.waitForSelector("#grDrawer .grfail", { timeout: 5000 });
    await sleep(400);
    await p.screenshot({ path: OUT + "08-grafo-card-remedios.png" });
    await p.close();
  }

  /* 09 · Sala: card de propuesta contextual · 10 · fallo + guardar-desde-run */
  {
    const p = await newPage(browser, async (pg) => {
      await pg.route("**/v1/puppets/p1/methods", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ methods: [{ id: "m-earnings", name: "Cierre de earnings" }] }) }));
      await pg.route("**/v1/methods/match", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ match: { method_id: "m-earnings", name: "Cierre de earnings", last_run_days: 5 } }) }));
    });
    await p.goto(SALA, { waitUntil: "load" });
    await p.waitForFunction(() => window.__metodoSala && window.__narrate, null, { timeout: 12000 });
    await p.evaluate(() => {
      window.__ST().puppetId = "p1";
      window.__metodoSala.st().equipped = [{ id: "m-earnings", name: "Cierre de earnings" }];
      const t = "arma el cierre de earnings del trimestre";
      document.getElementById("composer").value = t;
      // burbuja del usuario + card, como en el flujo real
      window.__ST().lastInput = t;
    });
    await p.evaluate(() => window.__metodoSala.maybePropose("arma el cierre de earnings del trimestre"));
    await p.waitForSelector("[data-metcard]", { timeout: 5000 });
    await sleep(400);
    await p.screenshot({ path: OUT + "09-sala-propuesta.png" });

    await p.evaluate(() => {
      window.__narrate({ type: "method_started", method_id: "m-earnings", name: "Cierre de earnings", run_id: "r-20" });
      window.__narrate({ type: "method_step_failed", run_id: "r-20", step_id: "s4", step_text: "Enviar el resumen al equipo",
        executor: "gmail", diagnosis: "credencial de gmail vencida — el conector pide re-conexión",
        remedies: { suggested_label: "reconectar gmail" } });
      window.__metodoSala.afterClose("cerrar el mes", { ok: true, run_id: "r-21", record: { tool_calls: [{ tool: "a" }, { tool: "b" }, { tool: "c" }] } });
    });
    await sleep(500);
    await p.screenshot({ path: OUT + "10-sala-fallo-y-guardar.png" });
    await p.close();
  }
} finally {
  await browser.close();
  server.kill();
}
console.log("capturas en " + OUT);
