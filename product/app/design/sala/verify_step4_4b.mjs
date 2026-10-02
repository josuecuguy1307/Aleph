/* STEP 4 · 4B — La Sala: NARRATIVA de 5 actos + SELECTOR de territorio + TINTES + ANTI-GRIFT.
 * Committable verify (Playwright, self-contained). Mismo patrón que verify_step4_4a.mjs:
 * server http local (archivos DESIGN + espinazo SSE en /v1/spaces/:id/stream) + page.route stubs;
 * se maneja la UI REAL (composer) y se asertan sobre el #narrative del DOM. NO se llaman funciones
 * internas (el script de la Sala es un IIFE); el seam window.__narrDone marca el fin del run.
 *
 * Cubre: (1) narrativa alimentada SÓLO de eventos reales, actos vacíos colapsan, pura compute →
 * Frontera "no tocó el mundo ✓"; (2) territorio habilitado por el cinturón (Cuantitativo on / Físico
 * 🔒 con razón; belt espacial → Físico on); (3) tinte cambia SÓLO presentación (verbo/énfasis), jamás
 * los datos; (4) anti-grift verde (familia opus-4.8) vs caveat honesto (modelo no-familia / sin tools);
 * (5) BYOK jamás en el DOM. La galería-render la cubre el integrador (RICH_SHAPES). Corre:
 *   node product/app/design/sala/verify_step4_4b.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = new URL("..", import.meta.url).pathname;   // product/app/design/
const SALA = new URL(".", import.meta.url).pathname;      // product/app/design/sala/
const SHOTS = new URL("./screenshots/", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };
const FAMILY_RE = /^claude-(code-)?opus-4[.\-]8$/;   // familia, NUNCA literal

const PID = "step4-4b-puppet", BREF = "platform/assembler/fixtures/belt-inline-rich.mcp.json";
const CARDS_INLINE = [
  { id: "pysandbox", label: "Python (cómputo)", tools: ["run_python"], state: "ready", backed_by: "pysandbox", connector: "pysandbox" },
  { id: "datatools", label: "Archivos (Excel / CSV)", tools: ["write_xlsx", "write_csv"], state: "ready", backed_by: "datatools", connector: "datatools" },
  { id: "calc", label: "Calculadora", tools: ["add", "sub", "mul", "div", "pow", "mod"], state: "ready", backed_by: "calc", connector: "calc" },
];
const CARDS_SPATIAL = [
  { id: "freecad", label: "FreeCAD", tools: ["create_object"], state: "ready", backed_by: "freecad", connector: "freecad" },
  { id: "calc", label: "Calculadora", tools: ["add", "mul"], state: "ready", backed_by: "calc", connector: "calc" },
];
const CARDS_MIX = [
  { id: "calc", label: "Calculadora", tools: ["add", "mul"], state: "ready", backed_by: "calc", connector: "calc" },
  { id: "exa", label: "Búsqueda (Exa)", tools: ["search"], state: "ready", backed_by: "exa", connector: "exa" },
];
function cardsFor(scn) { return scn === "terr-spatial" ? CARDS_SPATIAL : (scn === "tint" ? CARDS_MIX : CARDS_INLINE); }

const SECRET = "AIzaSyD3aBcDefGhIjKlMnOpQrStUvWxYz12345";   // formato REAL de key Gemini (BYOK de C1) — NO debe filtrarse
const MEM = "· Cierre de mayo: 4.2M.\n· Cliente: Acme. token=" + SECRET;
const PROV = ["ventas-q2.pdf#1", "ventas-q2.pdf#4", "informe-anual.pdf#12"];
const RUN_ID = "run-4b", APPROVAL_ID = "appr-4b";
const ARGS = { rows: [["a", 1], ["b", 2]] };
const GATE_UX = { que_va_a_hacer: "escribir un archivo Excel", donde_afecta: "tu carpeta de trabajo", vista_previa: "tabla 2×2", requiere_ok: true, boton_ok: "Aprobar", boton_cancelar: "Ahora no", nivel: "confirma-siempre" };
const PROMPT = "multiplica 1234 por 5678 con la calculadora";

function frame(id, type, payload) { return `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(Object.assign({ type }, payload))}\n\n`; }
const OP = { model: "claude-code-opus-4.8", degraded: false };   // familia opus-4.8 (verde)

/* espinazos por escenario (SSE real; el /run resuelve DESPUÉS del closed) */
const SPINE = {
  compute: (r) => { r.write(frame(1, "cost", Object.assign({ tier: "premium" }, OP)));
    r.write(frame(2, "tool_call_finished", { tool: "calc", tool_raw: "mul", args: ARGS, result: "7006652.0", status: "ok", gate_action: "execute", turn: 1 }));
    setTimeout(() => { r.write(frame(3, "final", { ok: true, run_id: "run-c", model_final: "claude-code-opus-4.8", degraded: null, answer: "7006652" }));
      r.write(frame(4, "closed", { ok: true, run_id: "run-c", model_final: "claude-code-opus-4.8", degraded: null, held_actions: [] })); r.end(); }, 250); },
  tint: (r) => { r.write(frame(1, "cost", Object.assign({ tier: "premium" }, OP)));
    r.write(frame(2, "tool_call_finished", { tool: "calc", tool_raw: "mul", args: ARGS, result: "42", status: "ok", gate_action: "execute", turn: 1 }));
    setTimeout(() => { r.write(frame(3, "final", { ok: true, run_id: "run-t", model_final: "claude-code-opus-4.8", degraded: null, answer: "42" }));
      r.write(frame(4, "closed", { ok: true, run_id: "run-t", model_final: "claude-code-opus-4.8", degraded: null, held_actions: [] })); r.end(); }, 250); },
  gate: (r) => { r.write(frame(1, "cost", Object.assign({ tier: "premium" }, OP)));
    r.write(frame(2, "gate_waiting", { kind: "tool_call", tool: "datatools", tool_raw: "write_xlsx", args: ARGS, gate_action: "needs_ok", turn: 1, gate_ux: GATE_UX }));
    setTimeout(() => { r.write(frame(3, "closed", { ok: true, run_id: RUN_ID, model_final: "claude-code-opus-4.8", degraded: null,
      held_actions: [{ approval_id: APPROVAL_ID, server: "datatools", tool: "write_xlsx", level: "confirma-siempre", action_class: "write-world", ux: GATE_UX }] })); r.end(); }, 250); },
  notools: (r) => { r.write(frame(1, "cost", Object.assign({ tier: "premium" }, OP)));
    setTimeout(() => { r.write(frame(2, "final", { ok: true, run_id: "run-n", model_final: "claude-code-opus-4.8", degraded: null, answer: "Respuesta directa." }));
      r.write(frame(3, "closed", { ok: true, run_id: "run-n", model_final: "claude-code-opus-4.8", degraded: null, held_actions: [] })); r.end(); }, 250); },
  grift: (r) => { r.write(frame(1, "cost", { model: "qwen-2.5-coder", tier: "premium", degraded: false }));
    r.write(frame(2, "tool_call_finished", { tool: "calc", tool_raw: "mul", args: ARGS, result: "5", status: "ok", gate_action: "execute", turn: 1 }));
    setTimeout(() => { r.write(frame(3, "final", { ok: true, run_id: "run-g", model_final: "qwen-2.5-coder", degraded: null, answer: "5" }));
      r.write(frame(4, "closed", { ok: true, run_id: "run-g", model_final: "qwen-2.5-coder", degraded: null, held_actions: [] })); r.end(); }, 250); },
  // 4B·review: SÓLO una tool GATEADA (nunca ejecutó), SIN mem/rag → no-grounded → NO badge verde
  // (review #1) + Evidencia colapsa + la pieza held NO entra a Trabajo (review #11).
  gateonly: (r) => { r.write(frame(1, "cost", Object.assign({ tier: "premium" }, OP)));
    r.write(frame(2, "gate_waiting", { kind: "tool_call", tool: "datatools", tool_raw: "write_xlsx", args: ARGS, gate_action: "needs_ok", turn: 1, gate_ux: GATE_UX }));
    setTimeout(() => { r.write(frame(3, "closed", { ok: true, run_id: RUN_ID, model_final: "claude-code-opus-4.8", degraded: null,
      held_actions: [{ approval_id: APPROVAL_ID, server: "datatools", tool: "write_xlsx", level: "confirma-siempre", action_class: "write-world", ux: GATE_UX }] })); r.end(); }, 250); },
  // 4B·review: corrida que FALLA (ok:false) → Frontera honesta (NO "no tocó el mundo ✓") + NO verde (review #2/#5).
  failed: (r) => { r.write(frame(1, "cost", Object.assign({ tier: "premium" }, OP)));
    r.write(frame(2, "tool_call_finished", { tool: "calc", tool_raw: "mul", args: ARGS, result: "9", status: "ok", gate_action: "execute", turn: 1 }));
    setTimeout(() => { r.write(frame(3, "closed", { ok: false, run_id: "run-f", model_final: "claude-code-opus-4.8", degraded: null, held_actions: [] })); r.end(); }, 250); },
  // 4B·review: modelo de familia PERO degradado (truthy) → NO verde "modelo degradado" (review #4).
  degraded: (r) => { r.write(frame(1, "cost", { model: "claude-code-opus-4.8", tier: "premium", degraded: true }));
    r.write(frame(2, "tool_call_finished", { tool: "calc", tool_raw: "mul", args: ARGS, result: "7", status: "ok", gate_action: "execute", turn: 1 }));
    setTimeout(() => { r.write(frame(3, "final", { ok: true, run_id: "run-d", model_final: "claude-code-opus-4.8", degraded: { intended_model: "claude-opus-4.8", actual_model: "llama", tier: "premium" }, answer: "7" }));
      r.write(frame(4, "closed", { ok: true, run_id: "run-d", model_final: "claude-code-opus-4.8", degraded: true, held_actions: [] })); r.end(); }, 250); },
  // 4B·review: tool_call_finished con status:'error' → NO cuenta como resultado real (review #6).
  errored: (r) => { r.write(frame(1, "cost", Object.assign({ tier: "premium" }, OP)));
    r.write(frame(2, "tool_call_finished", { tool: "calc", tool_raw: "mul", args: ARGS, result: "[error: boom]", status: "error", turn: 1 }));
    setTimeout(() => { r.write(frame(3, "final", { ok: true, run_id: "run-e", model_final: "claude-code-opus-4.8", degraded: null, answer: "no pude calcular" }));
      r.write(frame(4, "closed", { ok: true, run_id: "run-e", model_final: "claude-code-opus-4.8", degraded: null, held_actions: [] })); r.end(); }, 250); },
  // 4B·review#1-flip: espinazo CAÍDO (0 eventos live, stream vacío/500) pero el run SÍ ejecutó tools →
  // el grounding se reconstruye desde el ledger terminal (gate_action==='execute'); NO false-negative.
  streamdown: (r) => { setTimeout(() => { try { r.end(); } catch (e) { } }, 40); },
};

function terminalOut(scn) {
  if (scn === "gate") return { ok: true, run_id: RUN_ID, answer: "Preparé el Excel; pedí tu OK para escribirlo.",
    record: { model_final: "claude-code-opus-4.8", degraded: null, tool_calls: [{ tool: "datatools" }], memory_injected: MEM, rag_injected: { n_chunks: PROV.length, provenance: PROV }, byok_providers: ["gemini"] },
    outputs_captured: [], held_actions: [{ approval_id: APPROVAL_ID, server: "datatools", tool: "write_xlsx", args: ARGS, level: "confirma-siempre", action_class: "write-world", ux: GATE_UX }], obra: null };
  if (scn === "notools") return { ok: true, run_id: "run-n", answer: "Respuesta directa.", record: { model_final: "claude-code-opus-4.8", degraded: null, tool_calls: [] }, outputs_captured: [], held_actions: [], obra: null };
  if (scn === "grift") return { ok: true, run_id: "run-g", answer: "5", record: { model_final: "qwen-2.5-coder", degraded: null, tool_calls: [{ tool: "calc" }] }, outputs_captured: [], held_actions: [], obra: null };
  if (scn === "gateonly") return { ok: true, run_id: RUN_ID, answer: "Preparé el Excel; pedí tu OK para escribirlo.",
    record: { model_final: "claude-code-opus-4.8", degraded: null, tool_calls: [{ tool: "datatools", gate_action: "needs_ok", result: "[gate: requiere tu OK]" }] },   // gateada, SIN mem/rag → no-grounded
    outputs_captured: [], held_actions: [{ approval_id: APPROVAL_ID, server: "datatools", tool: "write_xlsx", args: ARGS, level: "confirma-siempre", action_class: "write-world", ux: GATE_UX }], obra: null };
  if (scn === "failed") return { ok: false, run_id: "run-f", answer: "", record: { model_final: "claude-code-opus-4.8", degraded: null, tool_calls: [{ tool: "calc", gate_action: "execute" }] }, outputs_captured: [], held_actions: [], obra: null };
  if (scn === "degraded") return { ok: true, run_id: "run-d", answer: "7", record: { model_final: "claude-code-opus-4.8", degraded: true, tool_calls: [{ tool: "calc", gate_action: "execute" }] }, outputs_captured: [], held_actions: [], obra: null };
  if (scn === "errored") return { ok: true, run_id: "run-e", answer: "no pude calcular", record: { model_final: "claude-code-opus-4.8", degraded: null, tool_calls: [{ tool: "calc", gate_action: "execute", result: "[error: boom]" }] }, outputs_captured: [], held_actions: [], obra: null };
  if (scn === "streamdown") return { ok: true, run_id: "run-sd", answer: "1234 × 5678 = **7006652**", record: { model_final: "claude-code-opus-4.8", degraded: null, tool_calls: [{ tool: "calc", gate_action: "execute", result: "7006652.0" }] }, outputs_captured: [], held_actions: [], obra: null };
  return { ok: true, run_id: "run-c", answer: "1234 × 5678 = **7006652**", record: { model_final: "claude-code-opus-4.8", degraded: null, tool_calls: [{ tool: "calc" }] }, outputs_captured: [], held_actions: [], obra: null };
}

function serve() {
  const state = { scenario: "compute" };
  const srv = http.createServer((req, r) => {
    const u = new URL(req.url, "http://x");
    if (/\/v1\/spaces\/[^/]+\/stream$/.test(u.pathname)) {
      r.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no" });
      (SPINE[state.scenario] || SPINE.compute)(r); return;
    }
    const p = path.join(DESIGN, decodeURIComponent(u.pathname));
    if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
    fs.createReadStream(p).pipe(r);
  });
  return new Promise((res) => srv.listen(0, "127.0.0.1", () => res({ srv, state })));
}

async function wireRoutes(page, scenario) {
  const j = (r, json) => r.fulfill({ json });
  const CARDS = cardsFor(scenario);
  await page.route("**/v1/classify-turn", (r) => j(r, { turn: "build" }));
  await page.route("**/v1/artifacts/classify-action", (r) => j(r, { action: "new" }));
  await page.route("**/v1/runs/*/approve", (r) => j(r, { ok: true, executed: true }));
  await page.route("**/v1/puppets/run", async (r) => { await new Promise((res) => setTimeout(res, 700)); return j(r, terminalOut(scenario)); });
  await page.route("**/v1/belts/cards*", (r) => j(r, { ref: BREF, slug: "inline-rich", cards: CARDS, total: CARDS.length, servers_real: CARDS.map((c) => c.id), dropped: [] }));
  await page.route("**/v1/users/*/puppets", (r) => j(r, { puppets: [{ id: PID, name: "Agente demo", config: { meta: { output_type: "informe" }, belt: { belt_ref: BREF } } }] }));
  await page.route("**/v1/sessions/**", (r) => r.request().method() === "GET" ? j(r, { artifacts: [] }) : j(r, { artifact: { id: "a-fx" } }));
  await page.route("**/v1/users/**", (r) => j(r, { puppets: [], keys: [], docs: [] }));
  await page.route("**/v1/obra-caption", (r) => j(r, {}));
  // UX·A1: el hilo persistente nace lazy en cada dispatch — stub benigno (registro fixture)
  await page.route("**/v1/chats*", (r) => r.request().method() === "POST" ? j(r, { id: "chat-fx", puppet_id: null, title: "" }) : j(r, { total: 0, chats: [] }));
  await page.route("**/v1/chats/**", (r) => j(r, { id: "chat-fx", messages: [] }));
}

/* lee el estado del #narrative del DOM (sólo lo que ve el usuario) */
const READ_NARR = () => {
  const el = document.getElementById("narrative");
  if (!el) return null;
  const rows = {};
  el.querySelectorAll(".nrow").forEach((r) => { rows[r.getAttribute("data-act")] = { text: r.textContent.trim(), col: r.classList.contains("ncol"), em: r.classList.contains("nem") }; });
  const b = el.querySelector(".ngrift");
  const chips = {};
  el.querySelectorAll(".tchip").forEach((c) => { chips[c.getAttribute("data-terr")] = { lock: c.classList.contains("lock"), active: c.classList.contains("active"), title: c.getAttribute("title") || "" }; });
  return { on: el.classList.contains("on"), terr: el.getAttribute("data-terr"), rows, badge: b ? { cls: b.className, text: b.textContent.trim() } : null, chips };
};

async function serveAndRun() {
  const { srv, state } = await serve();
  const base = "http://127.0.0.1:" + srv.address().port;
  const browser = await chromium.launch();
  fs.mkdirSync(SHOTS, { recursive: true });
  const results = [];

  async function scenario(name, run, { runIt = true } = {}) {
    console.log("══ " + name + " ══");
    const fails = [];
    const chk = { check(n, ok, d) { if (!ok) fails.push(n); console.log((ok ? "  ✓ " : "  ✗ ") + n + (ok || !d ? "" : "  → " + d)); } };
    state.scenario = name.replace(/-mix$/, "");
    const ctx = await browser.newContext({ viewport: { width: 1320, height: 900 }, reducedMotion: "reduce" });
    await ctx.addInitScript(() => { try { if (window.top !== window) return;
      sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", session_token: "t1" }));
      localStorage.setItem("aleph-lang", "es"); } catch { } });
    const page = await ctx.newPage();
    const cerr = [];
    page.on("console", (m) => { if (m.type() === "error") cerr.push(m.text()); });
    page.on("pageerror", (e) => cerr.push(String(e)));
    await wireRoutes(page, name);
    await page.goto(base + "/sala/sala.html?puppet=" + PID, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#composer", { timeout: 15_000 });
    await page.waitForSelector("#narrative.on .tchip", { timeout: 15_000 });   // el selector aparece al resolver el cinturón
    if (runIt) {
      await page.fill("#composer", PROMPT);
      await page.press("#composer", "Enter");
      await page.waitForFunction(() => window.__narrDone === true, { timeout: 12_000 });
    }
    await run(page, chk);
    const errs = cerr.filter((t) => !/favicon/i.test(t));
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 2).join(" | "));
    await page.screenshot({ path: SHOTS + "step4-4b-" + name + ".png", fullPage: false });
    results.push({ name, pass: fails.length === 0, fails });
    await ctx.close();
  }

  // 1 · COMPUTE — actos poblados de eventos reales; pura compute → Frontera "no tocó ✓"; verde
  await scenario("compute", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("#narrative visible", !!n && n.on);
    chk.check("Brief = el pedido + cinturón (3 piezas)", /1234/.test(n.rows.brief.text) && /3/.test(n.rows.brief.text));
    chk.check("Trabajo poblado con la pieza que disparó (Calculadora)", !n.rows.trabajo.col && /Calculadora/.test(n.rows.trabajo.text), n.rows.trabajo.text);
    chk.check("Evidencia = 1 resultado REAL (del tool_call_finished)", !n.rows.evidencia.col && /1\s+resultado/.test(n.rows.evidencia.text), n.rows.evidencia.text);
    chk.check("Materialización → Documento (informe via layoutFor)", !n.rows.materia.col && /Documento/.test(n.rows.materia.text), n.rows.materia.text);
    chk.check("Frontera COLAPSA a 'no tocó el mundo ✓' (held==0)", /no tocó el mundo/.test(n.rows.frontera.text), n.rows.frontera.text);
    chk.check("anti-grift VERDE (familia opus-4.8 + tools + no degradado)", n.badge && /ok/.test(n.badge.cls) && /verificado/.test(n.badge.text), n.badge && n.badge.text);
    chk.check("Territorio: Cuantitativo habilitado + activo", n.chips.cuantitativo && !n.chips.cuantitativo.lock && n.chips.cuantitativo.active);
    chk.check("Territorio: Físico 🔒 con razón (guía al Taller)", n.chips.fisico && n.chips.fisico.lock && /Físico/.test(n.chips.fisico.title), n.chips.fisico && n.chips.fisico.title);
  });

  // 2 · GATE — evidencia con memoria + procedencia; Frontera held; BYOK jamás en el DOM
  await scenario("gate", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("Evidencia cita memoria + N fragmentos", !n.rows.evidencia.col && /memoria/.test(n.rows.evidencia.text) && /cita/.test(n.rows.evidencia.text), n.rows.evidencia.text);
    const prov = await page.evaluate(() => (document.querySelector("#narrative .nprov") || {}).textContent || "");
    chk.check("procedencia [doc#chunk] visible en la narrativa", /ventas-q2\.pdf#1/.test(prov), prov);
    chk.check("Frontera = pidió tu OK (held==1)", /pidió tu OK/.test(n.rows.frontera.text), n.rows.frontera.text);
    const leak = await page.evaluate((s) => { const t = (document.getElementById("narrative").textContent || "") + " " + (document.getElementById("chat").textContent || "");
      return { secret: t.includes(s), aiza: /AIzaSy/.test(t), gemini: /gemini/i.test(t) }; }, SECRET);
    chk.check("BYOK JAMÁS en narrativa/chat (key + provider ocultos)", !leak.secret && !leak.aiza && !leak.gemini, JSON.stringify(leak));
    chk.check("anti-grift VERDE aún con gate (tools + familia)", n.badge && /ok/.test(n.badge.cls), n.badge && n.badge.text);
  });

  // 3 · TINT — cambiar territorio altera SÓLO presentación (verbo/énfasis), JAMÁS los datos
  await scenario("tint", async (page, chk) => {
    const grab = () => { const el = document.getElementById("narrative");
      return { terr: el.getAttribute("data-terr"),
        nd: [...el.querySelectorAll(".nrow .nd")].map((x) => x.textContent.trim()),
        verbs: [...el.querySelectorAll(".nrow .ntx b")].map((x) => x.textContent.trim()),
        badge: (el.querySelector(".ngrift") || {}).textContent || "",
        canvas: (document.getElementById("canvas") || {}).innerHTML || "",
        arts: (window.__spine ? 1 : 1) }; };
    const before = await page.evaluate(grab);
    // conocimiento está HABILITADO en el belt mixto (calc+exa) → el chip es clickeable
    await page.click('#narrative .tchip[data-terr="conocimiento"]:not(.lock)');
    const after = await page.evaluate(grab);
    chk.check("data-terr cambió (cuantitativo → conocimiento)", before.terr !== after.terr && after.terr === "conocimiento", before.terr + "→" + after.terr);
    chk.check("los DATOS son IDÉNTICOS tras el cambio de tinte (.nd invariantes)", JSON.stringify(before.nd) === JSON.stringify(after.nd), JSON.stringify(before.nd) + " vs " + JSON.stringify(after.nd));
    chk.check("la PRESENTACIÓN cambió (verbos por acto distintos)", JSON.stringify(before.verbs) !== JSON.stringify(after.verbs), JSON.stringify(before.verbs) + " vs " + JSON.stringify(after.verbs));
    chk.check("el anti-grift NO cambió con el tinte (mismo veredicto)", before.badge === after.badge, before.badge + " vs " + after.badge);
    chk.check("la OBRA renderizada quedó INTACTA (el tinte no re-corre ni toca el canvas)", before.canvas === after.canvas);
  });

  // 4 · NOTOOLS — 0 herramientas: Trabajo + Evidencia COLAPSAN; anti-grift = caveat honesto
  await scenario("notools", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("Trabajo COLAPSA (respondió sin herramientas)", n.rows.trabajo.col && /sin herramientas/.test(n.rows.trabajo.text), n.rows.trabajo.text);
    chk.check("Evidencia COLAPSA (sin evidencia externa)", n.rows.evidencia.col && /sin evidencia/.test(n.rows.evidencia.text), n.rows.evidencia.text);
    chk.check("anti-grift = caveat HONESTO 'sin herramientas' (NO badge verde falso)", n.badge && !/\bok\b/.test(n.badge.cls) && /sin herramientas/.test(n.badge.text), n.badge && (n.badge.cls + " · " + n.badge.text));
  });

  // 5 · GRIFT — modelo fuera de familia (no BYOK) → caveat, NUNCA 'verificado' falso
  await scenario("grift", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("anti-grift NO verde para modelo no-familia/no-BYOK (qwen)", n.badge && /no/.test(n.badge.cls) && !/\bok\b/.test(n.badge.cls), n.badge && (n.badge.cls + " · " + n.badge.text));
    chk.check("caveat honesto ('modelo no verificado')", n.badge && /no verificado/.test(n.badge.text), n.badge && n.badge.text);
  });

  // ── 4B·REVIEW · candados de los hallazgos adversariales (anti-grift + fabricación) ─────────
  // R#1/#11 · SÓLO una tool GATEADA (nunca ejecutó), SIN mem/rag → no-grounded → NO verde
  await scenario("gateonly", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("R#1 anti-grift NO verde sin resultado real ni mem/rag (gate sola)", n.badge && !/\bok\b/.test(n.badge.cls) && /sin herramientas/.test(n.badge.text), n.badge && (n.badge.cls + " · " + n.badge.text));
    chk.check("R#1 Evidencia COLAPSA (coherente con el badge, no contradice)", n.rows.evidencia.col && /sin evidencia/.test(n.rows.evidencia.text), n.rows.evidencia.text);
    chk.check("R#11 la pieza GATEADA (held, nunca corrió) NO aparece en Trabajo", n.rows.trabajo.col, n.rows.trabajo.text);
    chk.check("Frontera = pidió tu OK (la held sí se reporta acá)", /pidió tu OK/.test(n.rows.frontera.text), n.rows.frontera.text);
  });
  // R#2/#5 · corrida que FALLA (ok:false): Frontera honesta, NO "no tocó el mundo ✓", NO verde
  await scenario("failed", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("R#2 Frontera NO afirma 'no tocó el mundo ✓' en corrida rota", !/no tocó el mundo/.test(n.rows.frontera.text) && /no se completó/.test(n.rows.frontera.text), n.rows.frontera.text);
    chk.check("R#5 anti-grift NO verde en corrida fallida (ok:false)", n.badge && !/\bok\b/.test(n.badge.cls) && /no se completó/.test(n.badge.text), n.badge && (n.badge.cls + " · " + n.badge.text));
    chk.check("R#2 Materialización honesta (no llegó a materializar)", /no llegó a materializar/.test(n.rows.materia.text), n.rows.materia.text);
  });
  // R#4 · modelo de FAMILIA pero degradado (truthy dict) → caveat 'modelo degradado', jamás verde
  await scenario("degraded", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("R#4 anti-grift NO verde si degraded es truthy (aun familia opus-4.8)", n.badge && !/\bok\b/.test(n.badge.cls) && /degradado/.test(n.badge.text), n.badge && (n.badge.cls + " · " + n.badge.text));
  });
  // R#6 · tool con status:'error' → NO cuenta como 'resultado real' en Evidencia
  await scenario("errored", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("R#6 un result de ERROR NO cuenta como evidencia (Evidencia colapsa)", n.rows.evidencia.col && /sin evidencia/.test(n.rows.evidencia.text), n.rows.evidencia.text);
    chk.check("R#6 anti-grift NO verde (un error no es herramienta real)", n.badge && !/\bok\b/.test(n.badge.cls), n.badge && (n.badge.cls + " · " + n.badge.text));
  });
  // R#1-flip · espinazo CAÍDO (0 eventos live) + run que EJECUTÓ tools → grounding desde ledger terminal
  await scenario("streamdown", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("R#1-flip Evidencia poblada por el ledger terminal (execute) aun sin stream vivo", !n.rows.evidencia.col && /1\s+resultado/.test(n.rows.evidencia.text), n.rows.evidencia.text);
    chk.check("R#1-flip anti-grift VERDE (run real; sin false-negative por stream caído)", n.badge && /\bok\b/.test(n.badge.cls) && /verificado/.test(n.badge.text), n.badge && (n.badge.cls + " · " + n.badge.text));
  });

  // 6 · TERR-INLINE — belt de puro cómputo: Cuantitativo on, el resto 🔒 (sin run)
  await scenario("terr-inline", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("Cuantitativo habilitado", n.chips.cuantitativo && !n.chips.cuantitativo.lock);
    chk.check("Físico 🔒", n.chips.fisico && n.chips.fisico.lock);
    chk.check("Conocimiento 🔒", n.chips.conocimiento && n.chips.conocimiento.lock);
    chk.check("Operativo 🔒", n.chips.operativo && n.chips.operativo.lock);
  }, { runIt: false });

  // 7 · TERR-SPATIAL — belt con una pieza espacial (freecad) → Físico se enciende (sin run)
  await scenario("terr-spatial", async (page, chk) => {
    const n = await page.evaluate(READ_NARR);
    chk.check("Físico habilitado por la pieza espacial (freecad)", n.chips.fisico && !n.chips.fisico.lock);
    chk.check("Cuantitativo habilitado (calc en el belt)", n.chips.cuantitativo && !n.chips.cuantitativo.lock);
  }, { runIt: false });

  await browser.close();
  srv.close();

  // 8 · ANTI-GRIFT ESTÁTICO — sala.html NO compara model_final contra un literal (familia, no ===)
  {
    console.log("══ anti-grift (estático) ══");
    const fails = [];
    const txt = fs.readFileSync(SALA + "sala.html", "utf8");
    const literalEq = /(===|==)\s*["']claude-(code-)?opus/.test(txt) || /["']claude-(code-)?opus[^"']*["']\s*(===|==)/.test(txt);
    const fam = FAMILY_RE.test("claude-code-opus-4.8") && FAMILY_RE.test("claude-opus-4.8") && FAMILY_RE.test("claude-opus-4-8");
    const wired = /window\.Territorio/.test(txt) && /territorio\.js/.test(txt) && /function narrateRun/.test(txt) && /function layoutFor/.test(txt);
    if (literalEq) fails.push("literal-eq");
    if (!fam) fails.push("family-regex");
    if (!wired) fails.push("wiring");
    console.log((!literalEq ? "  ✓ " : "  ✗ ") + "sin igualdad-literal de model_final (familia, no ===)");
    console.log((fam ? "  ✓ " : "  ✗ ") + "la familia opus-4.8 (3 grafías) matchea el regex");
    console.log((wired ? "  ✓ " : "  ✗ ") + "territorio.js + narrateRun + layoutFor cableados en sala.html");
    results.push({ name: "anti-grift-static", pass: fails.length === 0, fails });
  }

  fs.writeFileSync(SALA + "EVIDENCE-step4-4b.json", JSON.stringify({ ok: results.every((r) => r.pass), results }, null, 2));
  const allok = results.every((r) => r.pass);
  console.log("\nevidence → " + SALA + "EVIDENCE-step4-4b.json");
  console.log(allok ? "\x1b[32m\x1b[1mALL GREEN ✓\x1b[0m" : "\x1b[31m\x1b[1mRED ✗\x1b[0m  " + results.filter((r) => !r.pass).map((r) => r.name + "[" + r.fails.join(",") + "]").join(", "));
  process.exit(allok ? 0 : 1);
}

serveAndRun().catch((e) => { console.error(e); process.exit(1); });
