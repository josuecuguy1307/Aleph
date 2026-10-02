/* verify_h9_money_gate.mjs — LLAVE A de H9 (money-gate) en El Cuarto.
 * Camino REAL (consumeLive ← SSE controlado, contrato Motor B). Dos tools del server maritime:
 *   - gfw_vessel_search (lectura) → tool_call_started/finished → aura "done" (corrió OK).
 *   - pay_for_premium_report (dinero) → gate_waiting → gateHold + aura "held" (FRENADA, NO ejecutada).
 * INVARIANTE H9: la acción de dinero se pinta HELD (candado rojo), JAMÁS "done"/pagado. La UI nunca
 * muestra la compra como hecha sobre un gate retenido.
 *   node cuarto/verify_h9_money_gate.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8112;
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

const TOOLS = [
  { id: "t_gfw", key: "t_gfw", label: "Buscar buque (GFW)", category: "read",  atom: "tool", server: "maritime", tools: ["gfw_vessel_search"] },
  { id: "t_pay", key: "t_pay", label: "Informe premium (pago)", category: "write", atom: "tool", server: "maritime", tools: ["pay_for_premium_report"] },
];
const RUN_ID = "r_h9_money";
const frames = [
  { type: "tool_call_started",  call_id: "c1", tool: "gfw_vessel_search" },
  { type: "tool_call_finished", call_id: "c1", tool: "gfw_vessel_search", status: "ok", wall_s: 0.4 },
  { type: "gate_waiting", call_id: "c2", tool: "pay_for_premium_report", action: "money_touch",
    ux: { title: "Comprar informe premium AIS", amount_usd: 499, provider: "marinetraffic" } },
  { type: "closed", ok: true, run_id: RUN_ID, model_final: "claude-code-opus-4.8",
    held_actions: [{ approval_id: "d30156fb", tool: "pay_for_premium_report", server: "maritime",
                     args: { provider: "marinetraffic", amount_usd: 499 } }] },
];
function sseBody(fr) { let id = 0, out = ""; for (const f of fr) { id++; out += `id: ${id}\nevent: ${f.type}\ndata: ${JSON.stringify(f)}\n\n`; } return out; }

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
const shot = async (name) => { const el = await page.$("#cuarto"); if (el) await el.screenshot({ path: join(SHOTS, name) }); };

await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });
  const placed = await page.evaluate((TOOLS) => {
    const c = window.__cuarto; TOOLS.forEach((t) => c.placeTile(t));
    return c.placedTiles().map((t) => ({ id: t.id, tools: t.tools }));
  }, TOOLS);
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(250);
  ok(placed.length === 2, "2 tools sembradas (lectura GFW + pago premium)", `placed=${placed.length}`);

  await page.route("**/v1/runs/enqueue", (route) => route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ job_id: "j_h9", run_id: RUN_ID }) }));
  await page.route("**/v1/spaces/*/stream*", (route) => route.fulfill({ status: 200, contentType: "text/event-stream", headers: { "cache-control": "no-cache" }, body: sseBody(frames) }));
  await page.evaluate(() => { const r = document.getElementById("runprompt"); if (r) r.value = "comprá el informe premium del buque"; });
  // [Cuarto entrega, no corre] el Cuarto ya no tiene botón de Ejecutar: correr es de La Sala.
  // El PIPELINE quedó intacto y sigue siendo lo que esta vara prueba — se dispara por código.
  await page.evaluate(() => window.__ejecutarTurno());
  await page.waitForTimeout(2200);   // deja consumir el stream + asentar auras

  const st = await page.evaluate(() => {
    const c = window.__cuarto; const tiles = c.placedTiles();
    const pay = tiles.find((t) => (t.tools || []).includes("pay_for_premium_report"));
    const read = tiles.find((t) => (t.tools || []).includes("gfw_vessel_search"));
    return {
      payHeld: c.isGateHeld(pay.id),
      payAura: (c.tileLiveState(pay.id) || {}).state || null,
      readAura: (c.tileLiveState(read.id) || {}).state || null,
      gatesHeld: c.gatesHeld(),
    };
  });
  console.log("  estado:", JSON.stringify(st));

  ok(st.payHeld === true, "H9·A · la acción de DINERO quedó FRENADA en el gate (isGateHeld=true)", `payHeld=${st.payHeld}`);
  ok(st.payAura === "held", "H9·A · aura de la pieza de dinero = 'held' (espera tu OK)", `payAura=${st.payAura}`);
  ok(st.payAura !== "done", "H9·A · INVARIANTE: el dinero NUNCA se pinta 'done'/pagado sobre el gate retenido", `payAura=${st.payAura}`);
  ok(st.readAura === "done", "H9·A · contraste: la LECTURA sí completa ('done') — el gate es selectivo al dinero", `readAura=${st.readAura}`);
  ok(st.gatesHeld.length === 1, "H9·A · exactamente 1 gate retenido (el de dinero)", `gatesHeld=${JSON.stringify(st.gatesHeld)}`);

  await shot("caso2-2b-h9-money-gate-held.png");
  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) { console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message); }
finally { await browser.close(); server.kill("SIGKILL"); }

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — H9 Llave A: dinero FRENADO (held, candado rojo), nunca 'done'; lectura completa OK"));
process.exit(fails.length ? 1 : 0);
