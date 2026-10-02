/* verify_metodo_resume.mjs — ticket 10 (frontend): retoma desde la Sala de un método que quedó
 * A MITAD (out.method.status==='paused_incomplete').
 *
 * Página REAL sala.html + routing REAL; backend stubeado. Doble llave, cero self-report:
 *   Llave A: tras un run que pausó incompleto → aparece la card de reanudar y ST.metodo.resumable
 *     queda armado (runId/methodId), leído por el seam window.__metodoSala.st().
 *   Llave B (wire real): "Reanudar" (y el next-turn con cue) POSTea a /method/resume con un `space`
 *     FRESCO en el body (el contrato del backend space_override) — capturado del request real.
 *   Control (anti-secuestro): armado + un turno NO-cue ("armá un informe…") NO dispara resume.
 *
 *   node product/app/design/sala/verify_metodo_resume.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = new URL("..", import.meta.url).pathname;
const SHOTS = new URL("./screenshots/", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };

function serveDesign() {
  return new Promise((res) => {
    const srv = http.createServer((req, r) => {
      const p = path.join(DESIGN, decodeURIComponent(new URL(req.url, "http://x").pathname));
      if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
      r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
      fs.createReadStream(p).pipe(r);
    });
    srv.listen(0, "127.0.0.1", () => res(srv));
  });
}

// out de un método que PAUSÓ incompleto: trae answer (para que routeObra cierre la obra y dispare
// metodoAfterClose) + out.method con status paused_incomplete y el paso pausado.
function routesFor(state) {
  const out = {
    ok: true, run_id: "run-mp",
    answer: "Empecé la inspección. Necesito que traigas el flightcase al taller; avisame cuando esté y sigo.",
    record: { tool_calls: [{ tool: "a" }, { tool: "b" }], model_final: "fx", degraded: null },
    outputs_captured: [], held_actions: [], obra: null,
    method: { method_id: "m-insp", name: "Inspeccion", status: "paused_incomplete", completed: false,
              steps: [{ id: "s1", text: "traé el flightcase al taller", status: "active" }] },
  };
  return [
    { url: "**/v1/**", handler: (r) => r.fulfill({ json: {} }) },
    { url: "**/v1/classify-turn", handler: (r) => r.fulfill({ json: { turn: "obra" } }) },
    { url: "**/v1/artifacts/classify-action", handler: (r) => r.fulfill({ json: { action: "new" } }) },
    { url: "**/v1/puppets/*/methods", handler: (r) => r.fulfill({ json: { methods: [] } }) },
    { url: "**/v1/spaces/**", handler: (r) => r.fulfill({ status: 200, contentType: "text/event-stream", body: "" }) },
    { url: "**/v1/puppets/run", handler: (r) => r.fulfill({ json: out }) },
    // captura del POST de resume (Llave B: contrato space_override)
    { url: "**/v1/runs/*/method/resume", handler: (r) => {
        let body = {}; try { body = JSON.parse(r.request().postData() || "{}"); } catch {}
        state.resumePosts.push({ url: r.request().url(), space: body.space });
        return r.fulfill({ json: { ok: true, resumed: "continuation" } });
      } },
    { url: "**/v1/sessions/**", handler: (r) => r.request().method() === "GET"
        ? r.fulfill({ json: { artifacts: [] } }) : r.fulfill({ json: { id: "aid-x" } }) },
    { url: "**/v1/users/**", handler: (r) => r.fulfill({ json: { puppets: [], keys: [], docs: [] } }) },
  ];
}

async function waitIdle(page) {
  await page.waitForFunction(() => {
    const send = document.getElementById("send"), badge = document.getElementById("bbadge");
    return send && !send.disabled && (!badge || badge.style.display === "none");
  }, { timeout: 20_000 });
  await page.waitForTimeout(350);
}
const stMetodo = (page) => page.evaluate(() => window.__metodoSala.st());

const SCENARIOS = [
  { key: "boton-reanudar", run: async (page, chk, state) => {
      // Llave A · card + armado
      const armed = await stMetodo(page);
      chk.check("A · ST.metodo.resumable armado (runId+methodId)",
        !!(armed.resumable && armed.resumable.runId === "run-mp" && armed.resumable.methodId === "m-insp"),
        JSON.stringify(armed.resumable));
      const cardTxt = await page.evaluate(() => { const d = document.querySelector('[data-metresume]'); return d ? d.textContent : null; });
      chk.check("A · card de reanudar presente con 'Reanudar el método'", !!cardTxt && /Reanudar el método/.test(cardTxt), cardTxt);
      // clic Reanudar → POST resume con space
      await page.click('[data-metresume] [data-m="resume"]');
      await page.waitForTimeout(500);
      chk.check("B · clic Reanudar → POST /method/resume del run pausado",
        state.resumePosts.length === 1 && /\/runs\/run-mp\/method\/resume/.test(state.resumePosts[0].url),
        JSON.stringify(state.resumePosts));
      chk.check("B · el POST lleva un `space` FRESCO (contrato space_override)",
        !!(state.resumePosts[0] && typeof state.resumePosts[0].space === "string" && state.resumePosts[0].space.length > 0),
        state.resumePosts[0] && state.resumePosts[0].space);
    } },
  { key: "next-turn-cue", run: async (page, chk, state) => {
      // el SIGUIENTE turno con cue de continuar re-engancha el arnés
      await page.fill("#composer", "listo, ya está — seguí");
      await page.press("#composer", "Enter");
      await page.waitForTimeout(600);
      chk.check("B · turno-cue ('listo…') → POST /method/resume (re-engancha en el siguiente turno)",
        state.resumePosts.length === 1 && /\/runs\/run-mp\/method\/resume/.test(state.resumePosts[0].url),
        JSON.stringify(state.resumePosts));
      chk.check("B · el turno-cue también manda `space` fresco",
        !!(state.resumePosts[0] && state.resumePosts[0].space), state.resumePosts[0] && state.resumePosts[0].space);
    } },
  { key: "control-no-hijack", run: async (page, chk, state) => {
      // armado + un pedido NO-cue no debe secuestrarse en resume
      await page.fill("#composer", "armá un informe de ventas del trimestre");
      await page.press("#composer", "Enter");
      await page.waitForTimeout(600);
      chk.check("control · turno NO-cue NO dispara resume (cero secuestro)",
        state.resumePosts.length === 0, "posts=" + state.resumePosts.length);
      const armed = await stMetodo(page);
      chk.check("control · la card sigue armada (resumable intacto para reanudar luego)",
        !!(armed.resumable && armed.resumable.runId === "run-mp"), JSON.stringify(armed.resumable));
    } },
];

const srv = await serveDesign();
const base = "http://127.0.0.1:" + srv.address().port;
const browser = await chromium.launch();
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
for (const sc of SCENARIOS) {
  console.log("══ " + sc.key + " ══");
  const fails = [];
  const chk = { check(name, ok, detail) { fails.push(...(ok ? [] : [name])); console.log((ok ? "  ✓ " : "  ✗ ") + name + (ok || !detail ? "" : "  → " + detail)); } };
  const state = { resumePosts: [] };
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, reducedMotion: "reduce" });
  await ctx.addInitScript(() => { try { if (window.top !== window) return; sessionStorage.setItem("puppet_user", JSON.stringify({ id: "fx-user", session_token: "fx-token" })); localStorage.setItem("aleph-lang", "es"); } catch {} });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  for (const r of routesFor(state)) await page.route(r.url, r.handler);

  await page.goto(base + "/sala/sala.html", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#composer", { timeout: 15_000 });
  // fase común: correr el método → pausa incompleta → card + armado
  await page.fill("#composer", "corré el método de inspección de los mosquetones");
  await page.press("#composer", "Enter");
  await waitIdle(page);

  await sc.run(page, chk, state);
  const errs = consoleErrors.filter((t) => !/favicon/i.test(t));
  chk.check("consola limpia", errs.length === 0, errs.slice(0, 2).join(" | "));
  await page.screenshot({ path: SHOTS + "metodo-resume-" + sc.key + ".png" });
  results.push({ key: sc.key, pass: fails.length === 0, fails });
  await ctx.close();
}
await browser.close();
srv.close();

console.log("\n════ TICKET 10 · RETOMA DESDE LA SALA (frontend) ════");
for (const r of results) console.log((r.pass ? "  ✓ " : "  ✗ ") + r.key + (r.pass ? "" : "  → " + r.fails.join(", ")));
const allPass = results.every((r) => r.pass);
console.log(allPass ? "✓ VERDE" : "✗ hay rojos");
process.exit(allPass ? 0 : 1);
