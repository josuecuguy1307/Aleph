/* verify_byo_cli_narr.mjs — D4 FRONT · la Sala NARRA el cerebro por suscripción (BYO-CLI).
 * Committable verify (Playwright, self-contained) — mismo patrón que verify_step4_4b.mjs:
 * server http local (DESIGN + espinazo SSE) + page.route stubs; se maneja la UI real
 * (composer) y se aserta sobre el #narrative del DOM.
 *
 * Escenarios:
 *   1 · byo-green  — brain_provider=claude_cli declarado + model_final REAL claude-sonnet-5
 *       (∉ FAMILY_RE vieja) → badge ✓ verde SOLO por el término BYO-CLI DECLARADO + coherencia.
 *   2 · byo-window — la ventana de la suscripción se agota mid-run: brain_window_exhausted
 *       (provider_name + reset) + notice degraded + cascade a qwen (degraded truthy) →
 *       fila narrada 'Tu ventana de Claude Code…' + aviso del switch + badge NO verde;
 *       mid-run el badge ya muestra 'ventana de Claude Code agotada' (no 'en curso…').
 *   3 · byo-spoof  — brain_provider=codex_cli pero model_final qwen3:8b (incoherente) →
 *       badge NO verde 'modelo no verificado' (la declaración NO alcanza sin coherencia).
 * Run: node product/app/design/sala/verify_byo_cli_narr.mjs */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = new URL("..", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };
const PID = "byo-cli-puppet", BREF = "platform/assembler/fixtures/belt-inline-rich.mcp.json";
const CARDS = [{ id: "calc", label: "Calculadora", tools: ["add", "mul"], state: "ready", backed_by: "calc", connector: "calc" }];
const ARGS = { a: 2, b: 3 };
const PROMPT = "multiplica 1234 por 5678 con la calculadora";
const WINDOW_MSG = "Tu ventana de Claude Code se agotó a mitad de la corrida — resetea ~18:00. Si hay un cerebro de respaldo configurado, el run sigue por ahí (degradado y visible); si no, corta honesto.";
const DEGR_MSG = "Cerebro degradado a fallback: se pidió 'claude-code-cli' pero respondió 'qwen3:8b' (oss-direct). No es el cerebro — fallback visible, no silencioso.";

const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "  ✓" : "  ✗"} ${label}${(!c && extra) ? "  → " + extra : ""}`); if (!c) fails.push(label); };
function frame(id, type, payload) { return `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(Object.assign({ type }, payload))}\n\n`; }

const SPINE = {
  "byo-green": (r) => {
    r.write(frame(1, "cost", { model: "claude-sonnet-5", tier: "primary", degraded: false }));
    r.write(frame(2, "tool_call_finished", { tool: "calc", tool_raw: "mul", args: ARGS, result: "7006652.0", status: "ok", gate_action: "execute", turn: 1 }));
    setTimeout(() => {
      r.write(frame(3, "final", { ok: true, run_id: "run-bg", model_final: "claude-sonnet-5", degraded: null, brain_provider: "claude_cli", answer: "7006652" }));
      r.write(frame(4, "closed", { ok: true, run_id: "run-bg", model_final: "claude-sonnet-5", degraded: null, brain_provider: "claude_cli", held_actions: [] }));
      r.end();
    }, 250);
  },
  "byo-window": (r) => {
    r.write(frame(1, "brain_window_exhausted", { kind: "control", brain_provider: "claude_cli", provider_name: "Claude Code", reset_hint: "18:00", message: WINDOW_MSG }));
    r.write(frame(2, "notice", { kind: "degraded", intended_model: "claude-code-cli", actual_model: "qwen3:8b", tier: "oss-direct", message: DEGR_MSG }));
    r.write(frame(3, "cost", { model: "qwen3:8b", tier: "oss-direct", degraded: true }));
    r.write(frame(4, "tool_call_finished", { tool: "calc", tool_raw: "mul", args: ARGS, result: "7006652.0", status: "ok", gate_action: "execute", turn: 1 }));
    setTimeout(() => {
      r.write(frame(5, "final", { ok: true, run_id: "run-bw", model_final: "qwen3:8b", degraded: { intended_model: "claude-code-cli", actual_model: "qwen3:8b", tier: "oss-direct" }, brain_provider: "claude_cli", answer: "7006652" }));
      r.write(frame(6, "closed", { ok: true, run_id: "run-bw", model_final: "qwen3:8b", degraded: true, brain_provider: "claude_cli",
        brain_window_exhausted: { brain_provider: "claude_cli", provider_name: "Claude Code", reset_hint: "18:00" }, held_actions: [] }));
      r.end();
    }, 900);
  },
  "byo-spoof": (r) => {
    r.write(frame(1, "cost", { model: "qwen3:8b", tier: "primary", degraded: false }));
    r.write(frame(2, "tool_call_finished", { tool: "calc", tool_raw: "mul", args: ARGS, result: "5", status: "ok", gate_action: "execute", turn: 1 }));
    setTimeout(() => {
      r.write(frame(3, "final", { ok: true, run_id: "run-bs", model_final: "qwen3:8b", degraded: null, brain_provider: "codex_cli", answer: "5" }));
      r.write(frame(4, "closed", { ok: true, run_id: "run-bs", model_final: "qwen3:8b", degraded: null, brain_provider: "codex_cli", held_actions: [] }));
      r.end();
    }, 250);
  },
};

function terminalOut(scn) {
  if (scn === "byo-window") return { ok: true, run_id: "run-bw", answer: "7006652",
    record: { model_final: "qwen3:8b", degraded: { intended_model: "claude-code-cli", actual_model: "qwen3:8b", tier: "oss-direct" },
      brain_provider: "claude_cli", brain_window_exhausted: { brain_provider: "claude_cli", provider_name: "Claude Code", reset_hint: "18:00" },
      tool_calls: [{ tool: "calc", gate_action: "execute", result: "7006652.0" }] },
    outputs_captured: [], held_actions: [], obra: null };
  if (scn === "byo-spoof") return { ok: true, run_id: "run-bs", answer: "5",
    record: { model_final: "qwen3:8b", degraded: null, brain_provider: "codex_cli", tool_calls: [{ tool: "calc", gate_action: "execute" }] },
    outputs_captured: [], held_actions: [], obra: null };
  return { ok: true, run_id: "run-bg", answer: "7006652",
    record: { model_final: "claude-sonnet-5", degraded: null, brain_provider: "claude_cli", tool_calls: [{ tool: "calc", gate_action: "execute" }] },
    outputs_captured: [], held_actions: [], obra: null };
}

function serve() {
  const state = { scenario: "byo-green" };
  const srv = http.createServer((req, r) => {
    const u = new URL(req.url, "http://x");
    if (/favicon|apple-touch-icon/i.test(u.pathname)) { r.writeHead(204); r.end(); return; }
    if (/\/v1\/spaces\/[^/]+\/stream$/.test(u.pathname)) {
      r.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive" });
      (SPINE[state.scenario])(r); return;
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
  await page.route("**/v1/classify-turn", (r) => j(r, { turn: "obra" }));
  await page.route("**/v1/artifacts/classify-action", (r) => j(r, { action: "new" }));
  await page.route("**/v1/puppets/run", async (r) => { await new Promise((res) => setTimeout(res, scenario === "byo-window" ? 1400 : 700)); return j(r, terminalOut(scenario)); });
  await page.route("**/v1/belts/cards*", (r) => j(r, { ref: BREF, slug: "inline-rich", cards: CARDS, total: CARDS.length, servers_real: ["calc"], dropped: [] }));
  await page.route("**/v1/icons**", (r) => j(r, { known: [] }));
  await page.route("**/v1/puppets/*/methods**", (r) => j(r, { methods: [] }));
  await page.route("**/v1/sessions/**", (r) => r.request().method() === "GET" ? j(r, { artifacts: [] }) : j(r, { artifact: { id: "a-fx" } }));
  await page.route("**/v1/users/**", (r) => j(r, { puppets: [], keys: [], docs: [] }));
  await page.route("**/v1/users/*/puppets", (r) => j(r, { puppets: [{ id: PID, name: "Agente BYO", config: { meta: { output_type: "informe" }, belt: { belt_ref: BREF }, model: { brain_provider: "claude_cli" } } }] }));
  await page.route("**/v1/obra-caption", (r) => j(r, {}));
  // UX·A1: el hilo persistente nace lazy en cada dispatch — stub benigno (registro fixture)
  await page.route("**/v1/chats*", (r) => r.request().method() === "POST" ? j(r, { id: "chat-fx", puppet_id: null, title: "" }) : j(r, { total: 0, chats: [] }));
  await page.route("**/v1/chats/**", (r) => j(r, { id: "chat-fx", messages: [] }));
  await page.route("**/v1/brains/status**", (r) => j(r, { providers: {} }));
}

const READ_NARR = () => {
  const el = document.getElementById("narrative");
  if (!el) return null;
  const b = el.querySelector(".ngrift");
  return { on: el.classList.contains("on"), text: el.textContent,
           badge: b ? { cls: b.className, text: b.textContent.trim() } : null };
};

const { srv, state } = await serve();
const base = "http://127.0.0.1:" + srv.address().port;
const browser = await chromium.launch();
let anyFail = false;

async function scenario(name, run) {
  console.log("══ " + name + " ══");
  const before = fails.length;
  state.scenario = name;
  const ctx = await browser.newContext({ viewport: { width: 1320, height: 900 }, reducedMotion: "reduce" });
  await ctx.addInitScript(() => { try { if (window.top !== window) return;
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", session_token: "t1" }));
    localStorage.setItem("aleph-lang", "es"); } catch { } });
  const page = await ctx.newPage();
  const cerr = [];
  const nf = [];
  page.on("console", (m) => { if (m.type() === "error") cerr.push(m.text()); });
  page.on("pageerror", (e) => cerr.push(String(e)));
  page.on("response", (r) => { if (r.status() === 404) nf.push(r.url()); });
  await wireRoutes(page, name);
  await page.goto(base + "/sala/sala.html?puppet=" + PID, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#composer", { timeout: 15000 });
  await page.waitForSelector("#narrative.on .tchip", { timeout: 15000 });
  await page.fill("#composer", PROMPT);
  await page.press("#composer", "Enter");
  await run(page);
  const errs = cerr.filter((t) => !/favicon|net::ERR/i.test(t));
  ok(errs.length === 0, "consola limpia", (nf.slice(0, 2).join(" | ") || errs.slice(0, 2).join(" | ")));
  await ctx.close();
  if (fails.length > before) anyFail = true;
}

try {
  // 1 · VERDE por DECLARACIÓN BYO-CLI + coherencia (sonnet ∉ FAMILY_RE vieja)
  await scenario("byo-green", async (page) => {
    await page.waitForFunction(() => window.__narrDone === true, { timeout: 12000 });
    const n = await page.evaluate(READ_NARR);
    ok(n && n.on, "#narrative visible");
    ok(n.badge && /ngrift ok/.test(n.badge.cls) && /verificado/.test(n.badge.text),
       "badge ✓ VERDE por brain_provider declarado + model_final coherente (claude-sonnet-5)",
       JSON.stringify(n.badge));
  });

  // 2 · VENTANA AGOTADA mid-run → narrada + badge no-verde
  await scenario("byo-window", async (page) => {
    await page.waitForFunction(() => {
      const el = document.getElementById("narrative");
      return el && /ventana de Claude Code/i.test(el.textContent);
    }, { timeout: 6000 });
    const mid = await page.evaluate(READ_NARR);
    ok(mid.badge && /ngrift no/.test(mid.badge.cls) && /ventana de Claude Code agotada/i.test(mid.badge.text),
       "MID-RUN: el badge ya muestra la ventana agotada (no 'en curso…')", JSON.stringify(mid.badge));
    await page.waitForFunction(() => window.__narrDone === true, { timeout: 12000 });
    const n = await page.evaluate(READ_NARR);
    ok(/Tu ventana de Claude Code se agotó/.test(n.text), "fila narrada con el NOMBRE del provider real");
    ok(/resetea ~18:00/.test(n.text), "el reset del CLI se narra");
    ok(/Cerebro degradado a fallback/.test(n.text), "el switch al respaldo se narra (notice degraded ya no se pierde)");
    ok(n.badge && /ngrift no/.test(n.badge.cls) && !/verificado/.test(n.badge.text),
       "badge JAMÁS verde en este turno", JSON.stringify(n.badge));
  });

  // 3 · ANTI-SPOOF: declaración sin coherencia NO alcanza
  await scenario("byo-spoof", async (page) => {
    await page.waitForFunction(() => window.__narrDone === true, { timeout: 12000 });
    const n = await page.evaluate(READ_NARR);
    ok(n.badge && /ngrift no/.test(n.badge.cls),
       "badge NO verde: codex_cli declarado pero model_final qwen3:8b (incoherente)", JSON.stringify(n.badge));
  });
} finally {
  await browser.close();
  srv.close();
}
console.log(anyFail || fails.length ? `\n✗ ${fails.length} falla(s): ${fails.join(" · ")}` : "\n✓ verify_byo_cli_narr: TODO VERDE");
process.exit(fails.length ? 1 : 0);
