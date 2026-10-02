/* verify_step4_4a.mjs — STEP 4 · 4A#2/#3/#4 render layer in the REAL sala.html DOM.
 *
 * Página REAL (product/app/design/sala/sala.html) + renderers reales + el consumidor de
 * espinazo VIVO del keystone. Sólo el backend está stubeado: los JSON via page.route, y el
 * ESPINAZO (/v1/spaces/:id/stream) via un server SSE con DELAYS reales (para poder observar el
 * gate en su estado FREEZE antes de que llegue el `closed` que lo hace operable). Driveamos el
 * flujo REAL de submit → run → stream — nada de llamar funciones internas (el script es IIFE).
 *
 * Cubre, verbatim en el DOM que ve el usuario:
 *  #2 CINTURÓN — el stack panel muestra el belt REAL de la receta (fan-out /v1/belts/cards) y la
 *     pieza que DISPARA en el stream se ilumina AHORA (.active) y queda .used.
 *  #3 EVIDENCIA — memory_injected (A3) + rag_injected.provenance [doc#chunk] (C1) del record REAL
 *     aparecen con procedencia; la BYOK (byok_providers/llave) NO aparece en ningún lado del DOM.
 *  #4 GATE VIVO — gate_waiting → FREEZE operable-pendiente (botones disabled); el `closed` VIVO
 *     (run_id+approval_id) lo hace OPERABLE **antes** de que el POST /run resuelva; OK → POST
 *     /v1/runs/:id/approve REAL con {approval_id, ok:true}. El candado es del runtime.
 *  + COLAPSO — run de pura compute (held==0) → NO hay tarjeta gate (Frontera "no tocó el mundo ✓").
 *  + ANTI-GRIFT (estático) — sala.html no compara el model_final contra un literal (familia, no ===).
 *
 *   node product/app/design/sala/verify_step4_4a.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = new URL("..", import.meta.url).pathname;            // product/app/design/
const SALA = new URL(".", import.meta.url).pathname;               // product/app/design/sala/
const SHOTS = new URL("./screenshots/", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };
const FAMILY_RE = /^claude-(code-)?opus-4[.\-]8$/;                 // familia, NUNCA literal

const PID = "step4-puppet-1";
const BREF = "platform/assembler/fixtures/belt-inline-rich.mcp.json";
// belt REAL (forma exacta de /v1/belts/cards) — el cinturón que debe verse == el de la receta.
const CARDS = [
  { id: "pysandbox", label: "Python (cómputo)", tools: ["run_python"], state: "ready", backed_by: "pysandbox", connector: "pysandbox" },
  { id: "datatools", label: "Archivos (Excel / CSV)", tools: ["write_xlsx", "write_csv"], state: "ready", backed_by: "datatools", connector: "datatools" },
  { id: "calc", label: "Calculadora", tools: ["add", "sub", "mul", "div", "pow", "mod"], state: "ready", backed_by: "calc", connector: "calc" },
];
const ARGS = { a: 1234, b: 5678 };
const GATE_UX = {
  que_va_a_hacer: "mover algo fuera de tu espacio de solo-lectura",
  donde_afecta: "un destino fuera de tu espacio", vista_previa: "Acción: mul con 2 parámetros.",
  requiere_ok: true, boton_ok: "OK, hacelo", boton_cancelar: "No, cancelá",
  nivel: "confirma-siempre", accion_clase: "write-world", autonomia: "balanceado",
};
const RUN_ID = "run-gate-R1", APPROVAL_ID = "appr-A1";
const SECRET = "AIzaSyD3aBcDefGhIjKlMnOpQrStUvWxYz12345";   // formato REAL de key Gemini (BYOK de C1) — la que el scrub viejo NO cazaba; debe quedar ‹oculto›
// memoria (A3) real: bloque pineado. Metemos un secreto ADENTRO para probar el scrub anti-fuga.
const MEM = "· El cierre de mayo cerró en 4.2M.\n· Cliente clave: Acme. token=" + SECRET;
const PROV = ["ventas-q2.pdf#1", "ventas-q2.pdf#4", "informe-anual.pdf#12"];

function frame(id, type, payload) {
  return `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(Object.assign({ type }, payload))}\n\n`;
}
// guiones de espinazo por escenario (con delays reales para observar el FREEZE)
const SPINE = {
  gate: (res) => {
    res.write(frame(1, "cost", { model: "claude-code-opus-4.8", tier: "premium", degraded: false }));
    res.write(frame(2, "gate_waiting", { kind: "tool_call", tool: "calc", tool_raw: "mul", args: ARGS, gate_action: "needs_ok", turn: 1, gate_ux: GATE_UX }));
    setTimeout(() => {   // 1200ms después: el closed VIVO trae run_id + approval_id → operable (< /run 2000ms)
      // FIEL al backend real (_emit_run_terminal): el closed OMITE `args` en held_actions (sólo el
      // gate_waiting y el out terminal los traen). Si la firma del gate dependiera de args, el freeze
      // NO subiría a operable y se duplicaría la tarjeta → esta fidelidad es la que caza ese bug.
      res.write(frame(3, "closed", { ok: true, run_id: RUN_ID, model_final: "claude-code-opus-4.8", degraded: null, held_actions: [{ approval_id: APPROVAL_ID, server: "calc", tool: "mul", level: "confirma-siempre", action_class: "write-world", ux: GATE_UX }] }));
      res.end();
    }, 1200);
  },
  compute: (res) => {
    res.write(frame(1, "cost", { model: "claude-code-opus-4.8", tier: "premium", degraded: false }));
    res.write(frame(2, "tool_call_finished", { kind: "tool_call", tool: "calc", tool_raw: "mul", args: ARGS, result: "7006652.0", status: "ok", gate_action: "execute", turn: 1 }));
    setTimeout(() => {
      res.write(frame(3, "final", { ok: true, run_id: "run-compute-R2", model_final: "claude-code-opus-4.8", degraded: null, answer: "1234 × 5678 = 7006652" }));
      res.write(frame(4, "closed", { ok: true, run_id: "run-compute-R2", model_final: "claude-code-opus-4.8", degraded: null, held_actions: [] }));
      res.end();
    }, 300);
  },
};

/* ── server: archivos de diseño + el ESPINAZO SSE (timed) ─────────────────── */
function serve() {
  const state = { scenario: "gate" };
  const srv = http.createServer((req, r) => {
    const u = new URL(req.url, "http://x");
    if (/\/v1\/spaces\/[^/]+\/stream$/.test(u.pathname)) {
      r.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no" });
      (SPINE[state.scenario] || SPINE.gate)(r);
      return;
    }
    const p = path.join(DESIGN, decodeURIComponent(u.pathname));
    if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
    fs.createReadStream(p).pipe(r);
  });
  return new Promise((res) => srv.listen(0, "127.0.0.1", () => res({ srv, state })));
}

/* ── stub JSON del backend (page.route) — la obra + el record REAL viajan en out ── */
function terminalOut(scenario) {
  if (scenario === "compute") {
    return { ok: true, run_id: "run-compute-R2", answer: "1234 × 5678 = **7006652**",
      record: { model_final: "claude-code-opus-4.8", degraded: null, tool_calls: [{ tool: "calc" }], byok_providers: [] },
      outputs_captured: [], held_actions: [], obra: null };
  }
  // gate: held + record CON memoria (A3) + rag (C1) + byok — la evidencia debe surgir, la llave NO.
  return { ok: true, run_id: RUN_ID, answer: "La multiplicación quedó frenada por un gate; pedí tu OK.",
    record: { model_final: "claude-code-opus-4.8", degraded: null, tool_calls: [{ tool: "calc" }],
      memory_injected: MEM, rag_injected: { n_chunks: PROV.length, provenance: PROV },
      byok_providers: ["gemini"] },
    outputs_captured: [],
    held_actions: [{ approval_id: APPROVAL_ID, server: "calc", tool: "mul", args: ARGS, level: "confirma-siempre", action_class: "write-world", ux: GATE_UX }],
    obra: null };
}

async function wireRoutes(page, scenario, captured) {
  const j = (r, json) => r.fulfill({ json });
  await page.route("**/v1/classify-turn", (r) => j(r, { turn: "build" }));
  await page.route("**/v1/artifacts/classify-action", (r) => j(r, { action: "new" }));
  await page.route("**/v1/runs/*/approve", (r) => {
    try { captured.approve.push(r.request().postDataJSON()); } catch { captured.approve.push(null); }
    return j(r, { ok: true, executed: true });
  });
  await page.route("**/v1/puppets/run", async (r) => {
    await new Promise((res) => setTimeout(res, 2000));   // el /run resuelve DESPUÉS del closed vivo (1200ms)
    return j(r, terminalOut(scenario));
  });
  await page.route("**/v1/belts/cards*", (r) => j(r, { ref: BREF, slug: "inline-rich", cards: CARDS, total: CARDS.length, servers_real: CARDS.map((c) => c.id), dropped: [] }));
  await page.route("**/v1/users/*/puppets", (r) => j(r, { puppets: [{ id: PID, name: "Agente demo", config: { meta: { output_type: "informe" }, belt: { belt_ref: BREF } } }] }));
  await page.route("**/v1/sessions/**", (r) => r.request().method() === "GET" ? j(r, { artifacts: [] }) : j(r, { artifact: { id: "a-fx" } }));
  await page.route("**/v1/users/**", (r) => j(r, { puppets: [], keys: [], docs: [] }));   // rag/docs benignos
  await page.route("**/v1/obra-caption", (r) => j(r, {}));
  // UX·A1: el hilo persistente nace lazy en cada dispatch — stub benigno (registro fixture)
  await page.route("**/v1/chats*", (r) => r.request().method() === "POST" ? j(r, { id: "chat-fx", puppet_id: null, title: "" }) : j(r, { total: 0, chats: [] }));
  await page.route("**/v1/chats/**", (r) => j(r, { id: "chat-fx", messages: [] }));
}

/* ── runner ────────────────────────────────────────────────────────────────── */
const { srv, state } = await serve();
const base = "http://127.0.0.1:" + srv.address().port;
const browser = await chromium.launch();
fs.mkdirSync(SHOTS, { recursive: true });
const results = [];

async function scenario(name, run) {
  console.log("══ " + name + " ══");
  const fails = [];
  const chk = { check(n, ok, d) { if (!ok) fails.push(n); console.log((ok ? "  ✓ " : "  ✗ ") + n + (ok || !d ? "" : "  → " + d)); } };
  state.scenario = name;
  const captured = { approve: [] };
  const ctx = await browser.newContext({ viewport: { width: 1320, height: 900 }, reducedMotion: "reduce" });
  await ctx.addInitScript(() => {
    try { if (window.top !== window) return;
      sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", session_token: "t1" }));
      localStorage.setItem("aleph-lang", "es"); } catch {}
  });
  const page = await ctx.newPage();
  const cerr = [];
  page.on("console", (m) => { if (m.type() === "error") cerr.push(m.text()); });
  page.on("pageerror", (e) => cerr.push(String(e)));
  await wireRoutes(page, name, captured);
  await page.goto(base + "/sala/sala.html?puppet=" + PID, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#composer", { timeout: 15_000 });
  await run(page, chk, captured);
  const errs = cerr.filter((t) => !/favicon/i.test(t));
  chk.check("consola limpia", errs.length === 0, errs.slice(0, 2).join(" | "));
  await page.screenshot({ path: SHOTS + "step4-4a-" + name + ".png", fullPage: false });
  results.push({ name, pass: fails.length === 0, fails });
  await ctx.close();
}

// ── #2/#3/#4 en un run REAL con gate ──
await scenario("gate", async (page, chk, captured) => {
  // #2 · el CINTURÓN se arma del belt REAL de la receta (en la carga, ANTES de correr)
  await page.waitForFunction(() => {
    const s = document.getElementById("stackPanel");
    return s && s.classList.contains("on") && document.querySelectorAll("#stackRow .piece").length === 3;
  }, { timeout: 15_000 });
  const belt = await page.evaluate(() => Array.from(document.querySelectorAll("#stackRow .piece .pn")).map((n) => n.textContent));
  chk.check("#2 cinturón = 3 piezas del belt real", belt.length === 3, belt.join(", "));
  const hdr = await page.evaluate(() => (document.getElementById("stackH") || {}).textContent || "");
  chk.check("#2 encabezado legible (no eco de clave i18n)", hdr === "Cinturón", hdr);
  chk.check("#2 piezas = calc/pysandbox/datatools (la receta, cero pérdida)",
    ["Calculadora", "Python (cómputo)", "Archivos (Excel / CSV)"].every((l) => belt.includes(l)), belt.join(", "));

  await page.fill("#composer", "¿cuánto es 1234 por 5678? usá la calculadora");
  await page.press("#composer", "Enter");

  // #4a · gate_waiting → FREEZE: tarjeta con botones DISABLED + banda de pausa
  await page.waitForFunction(() => {
    const g = document.querySelector("#chat .gate"); if (!g) return false;
    const ok = g.querySelector(".ok"); return ok && ok.disabled && g.querySelector(".frz");
  }, { timeout: 15_000 });
  const frozen = await page.evaluate(() => {
    const g = document.querySelector("#chat .gate");
    return { ok: !!g.querySelector(".ok"), disabled: g.querySelector(".ok").disabled, frz: !!g.querySelector(".frz"),
      qva: g.querySelector("p") ? g.querySelector("p").textContent : "" };
  });
  chk.check("#4 gate VIVO en FREEZE (botones disabled, banda pausa)", frozen.ok && frozen.disabled && frozen.frz, JSON.stringify(frozen));
  chk.check("#4 el freeze dice qué va a hacer (gate_ux)", /solo-lectura|mover algo/i.test(frozen.qva), frozen.qva);
  // #2 · la pieza calc dispara AHORA → .active (ventana [90ms paint, 1200ms closed]; paintStack throttlea 90ms)
  const litUp = await page.waitForFunction(() => {
    const a = document.querySelector("#stackRow .piece.active .pn"); return a && a.textContent === "Calculadora";
  }, { timeout: 1000 }).then(() => true).catch(() => false);
  chk.check("#2 pieza ACTIVA = Calculadora (el stream la iluminó)", litUp, "no .active en la ventana");

  // #4b · el closed VIVO (~1200ms) hace el gate OPERABLE — y el /run terminal (2000ms) AÚN no resolvió
  //       (no hay tarjeta .ev todavía) → prueba que fue el STREAM, no el out terminal, quien lo operó.
  await page.waitForFunction(() => {
    const ok = document.querySelector("#chat .gate .ok"); return ok && !ok.disabled;
  }, { timeout: 5_000 });
  const preTerminal = await page.evaluate(() => document.querySelectorAll("#chat .ev").length === 0);
  chk.check("#4 gate OPERABLE por el stream (closed) ANTES del /run terminal (sin .ev aún)", preTerminal);
  // el closed (sin args) debe SUBIR el freeze existente, NO crear una 2da tarjeta (firma server|fn estable)
  const nGate = await page.evaluate(() => document.querySelectorAll("#chat .gate").length);
  chk.check("#4 UNA sola tarjeta gate (freeze subió a operable, no se duplicó)", nGate === 1, "gates=" + nGate);

  // #4c · click OK → POST /approve REAL con {approval_id, ok:true}
  await page.click("#chat .gate .ok");
  await page.waitForFunction(() => /Hecho|✓/.test((document.querySelector("#chat .gate") || {}).textContent || ""), { timeout: 8_000 }).catch(() => {});
  chk.check("#4 aprobar → POST /approve con approval_id+ok:true (altera el run REAL)",
    captured.approve.length === 1 && captured.approve[0] && captured.approve[0].approval_id === APPROVAL_ID && captured.approve[0].ok === true,
    JSON.stringify(captured.approve));

  // #3 · evidencia con procedencia (tras resolver /run) — memoria + [doc#chunk], NUNCA la llave
  await page.waitForFunction(() => !!document.querySelector("#chat .ev"), { timeout: 8_000 });
  const ev = await page.evaluate(() => {
    const e = document.querySelector("#chat .ev");
    return { tags: Array.from(e.querySelectorAll(".prov .ptag")).map((t) => t.textContent),
      hasMem: /memoria/i.test(e.textContent), text: e.textContent };
  });
  chk.check("#3 evidencia: cita la memoria (A3)", ev.hasMem, ev.text.slice(0, 60));
  chk.check("#3 evidencia: procedencia [doc#chunk] (C1)",
    ev.tags.includes("ventas-q2.pdf#1") && ev.tags.includes("ventas-q2.pdf#4"), ev.tags.join(", "));
  // BYOK JAMÁS al front: ni el secreto embebido en la memoria, ni el nombre del provider, en el chat.
  // (el label "token=" puede quedar; lo que NO puede quedar es el VALOR → debe verse el centinela ‹oculto›)
  const leak = await page.evaluate((secret) => {
    const t = document.getElementById("chat").textContent || "";
    return { secret: t.includes(secret), aiza: /AIzaSy/.test(t), gemini: /gemini/i.test(t), scrubbed: t.includes("‹oculto›") };
  }, SECRET);
  chk.check("#3 BYOK: la key Gemini (AIzaSy…) NO aparece (valor scrubeado a ‹oculto›)", !leak.secret && !leak.aiza && leak.scrubbed, JSON.stringify(leak));
  chk.check("#3 BYOK: el provider (gemini) NO se muestra", !leak.gemini, JSON.stringify(leak));
});

// ── COLAPSO: pura compute, held==0 → sin gate, sin evidencia ──
await scenario("compute", async (page, chk) => {
  await page.waitForFunction(() => document.querySelectorAll("#stackRow .piece").length === 3, { timeout: 15_000 });
  await page.fill("#composer", "¿cuánto es 1234 por 5678? usá la calculadora");
  await page.press("#composer", "Enter");
  // la pieza calc se USA (tool_call_finished) y no hay gate
  await page.waitForFunction(() => document.querySelector("#stackRow .piece.used"), { timeout: 15_000 });
  const used = await page.evaluate(() => { const u = document.querySelector("#stackRow .piece.used .pn"); return u ? u.textContent : null; });
  chk.check("#2 pieza USADA = Calculadora (tool_call_finished)", used === "Calculadora", String(used));
  // esperar a que el /run resuelva
  await page.waitForFunction(() => {
    const s = document.getElementById("send"); return s && !s.disabled;
  }, { timeout: 20_000 });
  await page.waitForTimeout(300);
  const st = await page.evaluate(() => ({ gate: document.querySelectorAll("#chat .gate").length, ev: document.querySelectorAll("#chat .ev").length,
    active: document.querySelectorAll("#stackRow .piece.active").length }));
  chk.check("COLAPSO: Frontera sin gate (held==0 · no tocó el mundo ✓)", st.gate === 0, "gates=" + st.gate);
  chk.check("COLAPSO: sin evidencia (run sin memoria/corpus)", st.ev === 0, "ev=" + st.ev);
  chk.check("#2 sin pieza activa tras el cierre (activeId limpio)", st.active === 0, "active=" + st.active);
});

// ── ANTI-GRIFT (estático): sala.html no compara model_final contra un literal ──
{
  const txt = fs.readFileSync(SALA + "sala.html", "utf8");
  const literalEq = /(===|==)\s*["']claude-(code-)?opus/.test(txt) || /["']claude-(code-)?opus[^"']*["']\s*(===|==)/.test(txt);
  const fam = FAMILY_RE.test("claude-code-opus-4.8") && FAMILY_RE.test("claude-opus-4.8") && FAMILY_RE.test("claude-opus-4-8");
  console.log("══ anti-grift (estático) ══");
  console.log((!literalEq ? "  ✓ " : "  ✗ ") + "sala.html sin igualdad-literal de model_final (familia, no ===)");
  console.log((fam ? "  ✓ " : "  ✗ ") + "la familia opus-4.8 (3 grafías) matchea el regex");
  results.push({ name: "anti-grift", pass: !literalEq && fam, fails: (!literalEq && fam) ? [] : ["literal-eq or family regex"] });
}

await browser.close();
srv.close();
const allok = results.every((r) => r.pass);
fs.writeFileSync(SALA + "EVIDENCE-step4-4a.json", JSON.stringify({ ok: allok, results }, null, 2));
console.log("\nevidence → " + SALA + "EVIDENCE-step4-4a.json");
console.log(allok ? "\x1b[32m\x1b[1mALL GREEN ✓\x1b[0m" : "\x1b[31m\x1b[1mRED ✗\x1b[0m  " + results.filter((r) => !r.pass).map((r) => r.name).join(", "));
process.exit(allok ? 0 : 1);
