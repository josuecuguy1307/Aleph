/* verify_metodo_obra_guard.mjs — ticket 22 (edge): una edición cosmética suelta de la Sala
 * NO pisa la obra CANÓNICA de un método; deriva una copia y deja la del método intacta.
 *
 * Página REAL sala.html + routing REAL; sólo el backend está stubeado (determinista, sin stack).
 * Doble llave, cero self-report:
 *   Llave A (comportamiento): tras el edit cosmético sobre una obra-de-método → se creó una COPIA
 *     ("(copia editada)") con el texto reformateado y el canvas la muestra.
 *   Llave B (ground truth de estado): ST.artifacts[0].artifact.content quedó BYTE-IDÉNTICO al que
 *     produjo el método (la obra canónica NO se pisó), leído por el seam window.__ST().
 * Control (regresión): una obra NORMAL (sin método) + edit cosmético → overwrite EN SITIO (el
 *   comportamiento histórico se preserva: length no crece, la obra se actualiza).
 *
 *   node product/app/design/sala/verify_metodo_obra_guard.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = new URL("..", import.meta.url).pathname;   // product/app/design/
const SHOTS = new URL("./screenshots/", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };

const ORIGINAL = "# Acta de inspeccion de mosquetones\n\nFecha: 2026-07-18\nInspector: equipo rigging\n\n- Mosqueton GY-24-001: OK\n- Mosqueton GY-24-004: en cuarentena por oxido, no usar\n\nProxima inspeccion: 2026-08-18";
const REFORMATTED = "## ACTA DE INSPECCION - MOSQUETONES\n\nFecha 2026-07-18 - Inspector equipo rigging\n\n1. Mosqueton GY-24-001 - OK\n2. Mosqueton GY-24-004 - EN CUARENTENA (oxido)\n\nProxima inspeccion 2026-08-18";

/* ── server estático efímero, root product/app/design/ ────────────────────── */
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

// stub del backend. `state.phase` alterna la respuesta de /puppets/run: 1ra corrida = obra
// (con o sin method según el escenario) · 2da = edit reformateado SIN method.
function routesFor(state) {
  return [
    // catch-all de BAJA precedencia (registrado primero → lo pisan los específicos de abajo):
    // cualquier endpoint no stubeado (artEdit/artCreate/ledger…) responde vacío → cero 404 ruidoso.
    { url: "**/v1/**", handler: (r) => r.fulfill({ json: {} }) },
    { url: "**/v1/classify-turn", handler: (r) => r.fulfill({ json: { turn: "obra" } }) },
    { url: "**/v1/artifacts/classify-action", handler: (r) => r.fulfill({ json: { action: "new" } }) },
    { url: "**/v1/puppets/*/methods", handler: (r) => r.fulfill({ json: { methods: [] } }) },
    // SSE del espinazo: stream vacío 200 → el consumer lee done y cierra (sin 404/retry ruidoso)
    { url: "**/v1/spaces/**", handler: (r) => r.fulfill({ status: 200, contentType: "text/event-stream", body: "" }) },
    { url: "**/v1/puppets/run", handler: (r) => {
        state.phase++;
        const first = state.phase === 1;
        const out = {
          ok: true, run_id: "run-" + state.phase,
          answer: first ? ORIGINAL : REFORMATTED,
          record: { tool_calls: [{ tool: "x" }, { tool: "y" }], model_final: "fx", degraded: null },
          outputs_captured: [], held_actions: [], obra: null,
        };
        // el executor sólo puebla out.method cuando corrió el arnés: en el escenario "metodo"
        // la 1ra corrida lo trae (obra dirigida); el edit cosmético jamás lo trae.
        if (first && state.withMethod) out.method = { method_id: "m-insp", name: "Inspeccion", status: "completed", completed: true, steps: [] };
        return r.fulfill({ json: out });
      } },
    { url: "**/v1/sessions/**", handler: (r) => r.request().method() === "GET"
        ? r.fulfill({ json: { artifacts: [] } }) : r.fulfill({ json: { id: "aid-" + (state.phase) } }) },
    { url: "**/v1/users/**", handler: (r) => r.fulfill({ json: { puppets: [], keys: [], docs: [] } }) },
    { url: "**/v1/obra-caption", handler: (r) => r.fulfill({ json: {} }) },
    { url: "**/v1/belts/**", handler: (r) => r.fulfill({ json: { cards: [] } }) },
    { url: "**/v1/account/**", handler: (r) => r.fulfill({ json: {} }) },
  ];
}

async function waitIdle(page) {
  await page.waitForFunction(() => {
    const send = document.getElementById("send"), badge = document.getElementById("bbadge");
    return send && !send.disabled && (!badge || badge.style.display === "none");
  }, { timeout: 20_000 });
  await page.waitForTimeout(350);
}
const arts = (page) => page.evaluate(() => (window.__ST().artifacts || []).map((a) => ({
  content: a.artifact && a.artifact.content, title: a.title, from_method: !!a.from_method,
})));

const SCENARIOS = [
  { key: "metodo-guard", withMethod: true, assert: (chk, before, after) => {
      chk.check("fase1: obra marcada from_method (estampa de procedencia)", before.length === 1 && before[0].from_method === true, JSON.stringify(before[0] && { fm: before[0].from_method }));
      // Llave A · comportamiento: se DERIVÓ una copia con el texto reformateado
      chk.check("fase2: se creó UNA copia (2 artifacts)", after.length === 2, "len=" + after.length);
      chk.check("fase2: la copia lleva '(copia editada)'", !!(after[1] && /\(copia editada\)/.test(after[1].title)), after[1] && after[1].title);
      chk.check("fase2: la copia tiene el texto REFORMATEADO", !!(after[1] && after[1].content && after[1].content.indexOf("EN CUARENTENA") >= 0), after[1] && (after[1].content || "").slice(0, 40));
      // Llave B · ground truth: la obra del método quedó BYTE-IDÉNTICA (no se pisó)
      chk.check("LLAVE B: la obra canónica del método NO se pisó (byte-idéntica)", after[0].content === before[0].content, "changed=" + (after[0].content !== before[0].content));
      chk.check("LLAVE B: el texto reformateado NO entró en la canónica", after[0].content.indexOf("EN CUARENTENA") < 0, "leak=" + (after[0].content.indexOf("EN CUARENTENA") >= 0));
    } },
  { key: "control-no-metodo", withMethod: false, assert: (chk, before, after) => {
      chk.check("control fase1: obra normal SIN from_method", before.length === 1 && before[0].from_method === false, JSON.stringify(before[0] && { fm: before[0].from_method }));
      // sin procedencia de método → el edit cosmético PISA EN SITIO (comportamiento histórico)
      chk.check("control: NO se apila copia (sigue 1 artifact)", after.length === 1, "len=" + after.length);
      chk.check("control: la obra se actualizó al texto reformateado", after[0].content.indexOf("EN CUARENTENA") >= 0, after[0].content.slice(0, 40));
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
  const state = { phase: 0, withMethod: sc.withMethod };
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, reducedMotion: "reduce" });
  await ctx.addInitScript(() => { try { if (window.top !== window) return; sessionStorage.setItem("puppet_user", JSON.stringify({ id: "fx-user", session_token: "fx-token" })); localStorage.setItem("aleph-lang", "es"); } catch {} });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  for (const r of routesFor(state)) await page.route(r.url, r.handler);

  await page.goto(base + "/sala/sala.html", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#composer", { timeout: 15_000 });

  // fase 1 · producir la obra (dirigida por método en el escenario metodo-guard)
  await page.fill("#composer", "arma el acta de inspeccion de los mosquetones");
  await page.press("#composer", "Enter");
  await waitIdle(page);
  const before = await arts(page);

  // fase 2 · edición COSMÉTICA (verbo de cambio 'format' → _looksLikeFollowup → edit)
  await page.fill("#composer", "formatea el acta y ponela mas prolija");
  await page.press("#composer", "Enter");
  await waitIdle(page);
  const after = await arts(page);

  sc.assert(chk, before, after);
  const errs = consoleErrors.filter((t) => !/favicon/i.test(t));
  chk.check("consola limpia", errs.length === 0, errs.slice(0, 2).join(" | "));
  await page.screenshot({ path: SHOTS + "metodo-guard-" + sc.key + ".png" });
  results.push({ key: sc.key, pass: fails.length === 0, fails });
  await ctx.close();
}
await browser.close();
srv.close();

console.log("\n════ TICKET 22 · GUARD OBRA-DE-METODO ════");
for (const r of results) console.log((r.pass ? "  ✓ " : "  ✗ ") + r.key + (r.pass ? "" : "  → " + r.fails.join(", ")));
const allPass = results.every((r) => r.pass);
console.log(allPass ? "✓ VERDE" : "✗ hay rojos");
process.exit(allPass ? 0 : 1);
