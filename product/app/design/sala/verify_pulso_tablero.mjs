/* verify_pulso_tablero.mjs — HARNESS DE HONESTIDAD de la ola Pulso+Tablero (§3).
 * Carga la sala.html REAL en Chromium headless (server estático propio, sin backend)
 * e inyecta un stream de eventos CONOCIDOS por los mismos seams de producción
 * (window.__narrate / __pulso / __teamStart / __setView). Assert: el dibujo == los
 * eventos, ni uno más. Cubre: fidelidad métrica · vacío honesto · no-converge + criterio
 * real · toggle inocuo (byte-idéntico) · gate navega-no-aprueba.
 * Correr:  node product/app/design/sala/verify_pulso_tablero.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { join, extname, resolve } from "node:path";

const ROOT = resolve(new URL("../", import.meta.url).pathname);   // product/app/design
const MIME = { ".html":"text/html", ".js":"text/javascript", ".css":"text/css", ".json":"application/json", ".svg":"image/svg+xml" };

const server = http.createServer((req, res) => {
  try {
    let p = decodeURIComponent(req.url.split("?")[0]);
    let f = join(ROOT, p);
    if (existsSync(f) && statSync(f).isFile()) {
      res.writeHead(200, { "Content-Type": MIME[extname(f)] || "text/plain" });
      res.end(readFileSync(f));
    } else { res.writeHead(404); res.end("nf"); }
  } catch (e) { res.writeHead(500); res.end(String(e)); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));   // puerto libre asignado por el OS (nunca choca :8091 ni otro server)
const PORT = server.address().port;

const fails = [];
const ok = (c, m) => { console.log((c ? "  ok  " : " FAIL ") + m); if (!c) fails.push(m); };

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const consoleErrs = [];
page.on("pageerror", (e) => consoleErrs.push(String(e)));
// sin backend: cortá los /v1 para que el init no cuelgue (la lógica de render NO los necesita)
await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));

try {
  await page.goto(`http://127.0.0.1:${PORT}/sala/sala.html`, { waitUntil: "load" });
  await page.waitForFunction(() => window.__narrateStart && window.__narrate && window.__pulso && window.AlephIcons, null, { timeout: 12000 });
  consoleErrs.length = 0;   // descartá el ruido de init (sin backend); sólo cuentan errores durante la inyección

  // ── S1 · FIDELIDAD MÉTRICA: N eventos → N puntos, target real, último passed ────
  const s1 = await page.evaluate(() => {
    const ST = window.__ST(); ST.puppetId = "t1"; ST._view = "narrative";
    window.__narrateStart("probar el loop de Sharpe");
    const evs = [
      { type:"metric", name:"Sharpe", unit:"", goal:"max", target:1.2, iteration:1, value:0.6, passed:false },
      { type:"metric", name:"Sharpe", unit:"", goal:"max", target:1.2, iteration:2, value:0.9, passed:false },
      { type:"metric", name:"Sharpe", unit:"", goal:"max", target:1.2, iteration:3, value:1.1, passed:false },
      { type:"metric", name:"Sharpe", unit:"", goal:"max", target:1.2, iteration:4, value:1.35, passed:true },
    ];
    evs.forEach((e) => window.__narrate(e));
    window.__narrate({ type:"metric", name:"Sharpe", goal:"max", target:1.2, iteration:4, value:1.35, passed:true }); // DUP → no debe sumar
    const el = document.getElementById("narrative");
    return {
      hasPulso: !!el.querySelector(".pt-pulso"),
      pts: el.querySelectorAll(".pt-pulso .pt-pt").length,
      hasTarget: !!el.querySelector(".pt-target"),
      targetLbl: (el.querySelector(".pt-target-lbl") || {}).textContent || "",
      lastOk: !!el.querySelector(".pt-pt.now.ok"),
      polyPts: ((el.querySelector(".pt-line") || {}).getAttribute ? el.querySelector(".pt-line").getAttribute("points").trim().split(" ").length : 0),
    };
  });
  ok(s1.hasPulso, "S1 · el bloque Pulso aparece con métrica");
  ok(s1.pts === 4, `S1 · 4 métricas → 4 puntos exactos (dup ignorada) (got ${s1.pts})`);
  ok(s1.hasTarget, "S1 · línea de target presente");
  ok(/meta\s*1\.2/.test(s1.targetLbl), `S1 · label de meta = 1.2 (got "${s1.targetLbl}")`);
  ok(s1.lastOk, "S1 · último punto resaltado (now) + verde (passed real)");
  ok(s1.polyPts === 4, `S1 · polilínea con 4 vértices (got ${s1.polyPts})`);

  // ── S2 · VACÍO HONESTO: sin métrica → NO hay Pulso ─────────────────────────────
  const s2 = await page.evaluate(() => {
    const ST = window.__ST(); ST.pulso = null; ST.team = null; ST.live = null; ST.narr = null;
    window.__narrateStart("una tarea sin loop");
    window.__narrate({ type:"tool_call_finished", tool:"x", tool_raw:"x", status:"ok", result:"hi" });
    const el = document.getElementById("narrative");
    return { hasPulso: !!el.querySelector(".pt-pulso"), hasActs: el.querySelectorAll("[data-act]").length };
  });
  ok(!s2.hasPulso, "S2 · sin métrica → NINGÚN bloque Pulso (nada inventado)");
  ok(s2.hasActs > 0, "S2 · la narrativa de actos sigue intacta");

  // ── S3 · NO CONVERGE + CRITERIO REAL: valores planos, closed → 'unmet'; budget → 'budget' ──
  const s3 = await page.evaluate(() => {
    const ST = window.__ST(); ST.pulso = null; ST.team = null; ST.live = null; ST.narr = null;
    window.__narrateStart("loop que no converge");
    [1,2,3].forEach((n) => window.__narrate({ type:"metric", name:"stress", unit:"MPa", goal:"min", target:250, iteration:n, value:300, passed:false }));
    const before = document.getElementById("narrative").querySelectorAll(".pt-pt").length;
    window.__narrate({ type:"closed", held_actions:[] });   // cierra sin alcanzar meta
    const el = document.getElementById("narrative");
    const stopU = el.querySelector(".pt-stop");
    const unmet = stopU && stopU.classList.contains("unmet") && /sin alcanzar/i.test(stopU.textContent);
    // ahora un run con budget_exhausted
    ST.pulso = null; ST.live = null; ST.narr = null;
    window.__narrateStart("loop cortado por presupuesto");
    [1,2].forEach((n) => window.__narrate({ type:"metric", name:"stress", goal:"min", target:250, iteration:n, value:300, passed:false }));
    window.__narrate({ type:"budget_exhausted", limit:12 });
    window.__narrate({ type:"closed", held_actions:[] });
    const stopB = document.getElementById("narrative").querySelector(".pt-stop");
    const budget = stopB && stopB.classList.contains("budget") && /presupuesto/i.test(stopB.textContent);
    return { before, unmet, budget, flatPts: 3 };
  });
  ok(s3.before === 3, `S3 · 3 puntos planos dibujados tal cual (got ${s3.before})`);
  ok(s3.unmet, "S3 · closed sin meta → criterio 'terminó sin alcanzar la meta' (honesto)");
  ok(s3.budget, "S3 · budget_exhausted → criterio 'presupuesto agotado' (evento real)");

  // ── S4 · TABLERO: sub_agent_* → carriles exactos, estados reales ───────────────
  const s4 = await page.evaluate(() => {
    const ST = window.__ST(); ST.pulso = null; ST.team = null; ST.live = null; ST.narr = null; ST._view = "narrative";
    window.__narrateStart("delegar en dos sub-agentes");
    // por el camino de PRODUCCIÓN (narrateEvent) — los sub_agent_* repintan la narrativa
    window.__narrate({ type:"sub_agent_started", slug:"buscador", meta_name:"Buscador", depth:1, parent_run_id:"root", task:"buscar fuentes" });
    window.__narrate({ type:"sub_agent_started", slug:"redactor", meta_name:"Redactor", depth:1, parent_run_id:"root", task:"redactar informe" });
    window.__narrate({ type:"sub_agent_finished", slug:"buscador", status:"ok", child_ok:true, held:0 });
    window.__narrate({ type:"sub_agent_finished", slug:"redactor", status:"gate", held:1 });
    const toggle = !!document.querySelector(".pt-viewtoggle");
    window.__setView("tablero");
    const el = document.getElementById("narrative");
    const lanes = el.querySelectorAll(".pt-board .pt-lane");
    const chips = [...el.querySelectorAll(".pt-lane .pt-lst")].map((c) => c.className.replace("pt-lst ", ""));
    const labels = [...el.querySelectorAll(".pt-lane-title")].map((t) => t.textContent.trim().split(" ")[0]);
    return { toggle, lanes: lanes.length, chips, labels };
  });
  ok(s4.toggle, "S4 · con delegación aparece el toggle de vista");
  ok(s4.lanes === 2, `S4 · 2 sub-agentes → 2 carriles exactos (got ${s4.lanes})`);
  ok(s4.chips.includes("done") && s4.chips.includes("held"), `S4 · estados reales: done + held (got ${JSON.stringify(s4.chips)})`);
  ok(s4.labels.includes("Buscador") && s4.labels.includes("Redactor"), `S4 · labels reales (got ${JSON.stringify(s4.labels)})`);

  // ── S5 · TOGGLE INOCUO: narrativa byte-idéntica ida y vuelta ───────────────────
  const s5 = await page.evaluate(() => {
    const ST = window.__ST();   // seguimos en el run multiagente de S4
    window.__setView("narrative");
    const a = document.getElementById("narrative").innerHTML;
    const acts = document.getElementById("narrative").querySelectorAll("[data-act]").length;
    window.__setView("tablero");
    window.__setView("narrative");
    const b = document.getElementById("narrative").innerHTML;
    return { identical: a === b, acts };
  });
  ok(s5.identical, "S5 · toggle tablero→narrativa→ídem: #narrative byte-idéntico (sin pérdida)");
  ok(s5.acts >= 4, `S5 · la narrativa de 5 actos sigue completa bajo el toggle (got ${s5.acts})`);

  // ── S6 · GATE: el Tablero NAVEGA, jamás aprueba ────────────────────────────────
  const s6 = await page.evaluate(() => {
    const ST = window.__ST(); ST._view = "narrative";
    // gate vivo por gate_waiting → ensureGate crea la card en #chat
    window.__narrate({ type:"gate_waiting", tool:"stripe", tool_raw:"create_charge", gate_ux:{ que_va_a_hacer:"cobrar 50 USD" }, args:{ amount:50 } });
    window.__setView("tablero");
    const board = document.querySelector(".pt-board");
    const badge = board && board.querySelector(".pt-gate-badge");
    const approveInBoard = board ? board.querySelectorAll("button.ok, button.no").length : -1;
    const badgeText = badge ? badge.textContent : "";
    const cardInChat = !!document.querySelector("#chat .gate");
    return { hasBadge: !!badge, approveInBoard, badgeText, cardInChat };
  });
  ok(s6.hasBadge, "S6 · gate pendiente aparece como badge en el Tablero");
  ok(s6.approveInBoard === 0, `S6 · CERO botones de aprobar en el Tablero (navega, no aprueba) (got ${s6.approveInBoard})`);
  ok(s6.cardInChat, "S6 · la card operable (con OK/Cancel) vive en su lugar, el #chat");

  // ── S7 · XSS: task del sub-agente (texto del MODELO) no puede romper el atributo ──
  // review-fix (HIGH): esc() ahora escapa " y '; una task maliciosa cae como texto inerte.
  const s7 = await page.evaluate(() => {
    const ST = window.__ST(); ST.pulso = null; ST.team = null; ST.live = null; ST.narr = null; ST._view = "narrative";
    window.__narrateStart("delegar con task hostil");
    const PAYLOAD = 'a" onmouseover="window.__xss=1" x="';
    window.__narrate({ type:"sub_agent_started", slug:"h", meta_name:"Hostil", depth:1, parent_run_id:"root", task: PAYLOAD });
    window.__setView("tablero");
    const t = document.querySelector(".pt-board .pt-lane-task");
    return {
      leaked: window.__xss === 1,                       // el handler jamás debió crearse
      hasHandlerAttr: !!(t && t.getAttributeNames && t.getAttributeNames().some((a) => /^on/i.test(a))),
      textShown: (t && t.textContent) || "",            // el payload debe verse como texto crudo
      titleShown: (t && t.getAttribute("title")) || "",
    };
  });
  ok(!s7.leaked, "S7 · el payload NO ejecutó (window.__xss quedó sin setear)");
  ok(!s7.hasHandlerAttr, "S7 · el nodo pt-lane-task no tiene ningún atributo on*");
  ok(/onmouseover/.test(s7.textShown) && /onmouseover/.test(s7.titleShown), "S7 · el payload se muestra como TEXTO inerte (title+cuerpo)");

  // ── S8 · OLA 4 · MURALLA §1 — un WORKER efímero (ephemeral:true) NO crea carril en el Tablero de
  //         La Sala. Los workers viven SÓLO en La Mente del Núcleo (Cuarto); un sub-agente REAL en el
  //         mismo run SÍ crea su carril (sólo el worker efímero se filtra). ──
  const s8 = await page.evaluate(() => {
    const ST = window.__ST(); ST.pulso = null; ST.team = null; ST.live = null; ST.narr = null; ST._view = "narrative";
    window.__narrateStart("el Núcleo reparte lectura en workers efímeros");
    // eventos ephemeral REALES del riel sub_agent_* (worker efímero) — invisibles en La Sala
    window.__narrate({ type:"sub_agent_started", ephemeral:true, worker_id:"w1-2-0", worker_kind:"lectores", slug:"w1-2-0", routed:"economico", task:"leer la fuente A", depth:1 });
    window.__narrate({ type:"sub_agent_finished", ephemeral:true, worker_id:"w1-2-0", worker_kind:"lectores", slug:"w1-2-0", status:"ok", child_ok:true, held:0, model_final:"econ-oss" });
    const afterWorker = (ST.team && ST.team.order) ? ST.team.order.slice() : [];
    // un sub-agente REAL en el MISMO run SÍ crea carril (retro-compat: sólo el worker se filtra)
    window.__narrate({ type:"sub_agent_started", slug:"analista", meta_name:"Analista", depth:1, parent_run_id:"root", task:"tarea real" });
    window.__narrate({ type:"sub_agent_finished", slug:"analista", status:"ok", child_ok:true, held:0 });
    window.__setView("tablero");
    const el = document.getElementById("narrative");
    const labels = [...el.querySelectorAll(".pt-lane-title")].map((t) => t.textContent.trim().split(" ")[0]);
    return { afterWorker, order: (ST.team && ST.team.order) ? ST.team.order.slice() : [],
             lanes: el.querySelectorAll(".pt-board .pt-lane").length, labels };
  });
  ok(s8.afterWorker.length === 0, `S8 · MURALLA §1: el worker efímero NO crea carril en el Tablero (order tras worker=${JSON.stringify(s8.afterWorker)})`);
  ok(s8.lanes === 1 && s8.order.length === 1 && s8.order[0] === "analista" && !s8.labels.includes("w1-2-0"),
     `S8 · el sub-agente REAL sí aparece (retro-compat); el worker efímero jamás (lanes=${s8.lanes}, labels=${JSON.stringify(s8.labels)})`);

  // errores de página durante la inyección (init ya descartado): deben ser CERO
  ok(consoleErrs.length === 0, `sin errores de página durante la inyección (got ${consoleErrs.length}: ${consoleErrs.slice(0,2).join(" | ")})`);

} catch (e) {
  ok(false, "EXCEPCIÓN: " + String(e && e.stack || e));
} finally {
  await browser.close();
  server.close();
}

console.log("");
if (fails.length) { console.log(`RESULT: ${fails.length} FAIL`); process.exit(1); }
console.log("RESULT: ALL GREEN"); process.exit(0);
