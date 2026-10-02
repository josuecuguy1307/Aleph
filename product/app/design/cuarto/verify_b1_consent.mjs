/* verify_b1_consent.mjs — CAZA EL BUG DEL ZIP (review adversarial B1, finding HIGH money-consent).
 *
 * El bug: con la delegación agente→agente, closed.held_actions se volvió un SUPERCONJUNTO
 * (held del PADRE + held HOISTEADAS de un sub-agente, que NO emiten gate_waiting — RIEL#5). El
 * front zipeaba `gates` (sólo del padre) ↔ held_actions POR ÍNDICE, así que una held de DINERO
 * del hijo (held[0]) le robaba el approval_id a la tarjeta BENIGNA del padre → al dar OK sobre el
 * aviso benigno, el POST /approve ejecutaba la TRANSFERENCIA del hijo (confused-deputy; el humano
 * jamás vio la tarjeta del dinero). Ningún harness backend lo veía: llaman /approve con el
 * approval_id correcto directo, nunca ejercitan el zip del FRONT. Este test SÍ.
 *
 * Corre las funciones REALES del worktree (window.__bindGateApprovals + el flujo #run→gatebar→OK):
 *   A · UNIT determinístico — bindGateApprovals ata la tarjeta del padre a SU held (por identidad de
 *       tool), NUNCA a la del hijo; y la held delegada rinde su PROPIA tarjeta (no queda huérfana).
 *   B · E2E DOM — un run con gate benigna del padre + money HOISTEADA del hijo: se aprueba la
 *       tarjeta benigna → el POST /approve va con el approval_id BENIGNO (NO el del dinero); y el
 *       dinero del hijo SÍ se presenta como su propia tarjeta aprobable (antes: huérfana).
 *
 * Run:  node verify_b1_consent.mjs        (headless, SIN backend — SSE stubbeado)
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");                       // cuarto → design
const PORT = Number(process.env.FRONT_PORT || 8114);       // ≠ otros verify
const PAGE_URL = `http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

// ── el escenario del bug: money del HIJO es held[0] (orden real del hoist-then-append), aviso
// benigno del PADRE es held[1]. El front sólo vio la gate_waiting del padre (aviso). ──────────
const SEND_UX  = { que_va_a_hacer: "enviar un aviso por Slack", donde_afecta: "tu canal #general", vista_previa: "“corrida lista”" };
const MONEY_UX = { que_va_a_hacer: "transferir $500 a un tercero", donde_afecta: "tu cuenta bancaria conectada", vista_previa: "$500 → payee externo" };
const HELD_ACTIONS = [
  { approval_id: "MONEY_CHILD", tool: "transfer_money", server: "bank",   via_delegation: true,  agent_path: ["cajero-sub"], depth: 1, ux: MONEY_UX },
  { approval_id: "SEND_PARENT", tool: "send_x",         server: "notify", via_delegation: false,                             ux: SEND_UX },
];

function sseBody(frames) {
  let id = 0, out = "";
  for (const f of frames) { id++; out += `id: ${id}\nevent: ${f.type}\ndata: ${JSON.stringify(f)}\n\n`; }
  return out;
}
const RUN_FRAMES = [
  // el PADRE gatea SU propio aviso (benigno) → gate_waiting con su ux
  { type: "gate_waiting", kind: "tool_call", tool: "notify", tool_raw: "send_x", gate_action: "needs_ok", gate_ux: SEND_UX, turn: 1 },
  // el HIJO trabaja y deja una acción retenida (money) — RIEL#5: NO emite gate_waiting, sólo el evento estructural
  { type: "sub_agent_started",  kind: "delegation", slug: "cajero-sub", tool: "cajero-sub", turn: 1 },
  { type: "sub_agent_finished", kind: "delegation", slug: "cajero-sub", tool: "cajero-sub", held: 1, wall_s: 1.2, turn: 1 },
  // el TERMINAL trae held_actions como OBJETOS (padre + hijo hoisteada), money PRIMERO
  { type: "closed", ok: true, run_id: "r_consent", model_final: "claude-code-opus-4.8", held_actions: HELD_ACTIONS },
];

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 800));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1320, height: 880 }, deviceScaleFactor: 1 });
const cerr = [];
page.on("console", (m) => { if (m.type() === "error") cerr.push(m.text()); });
page.on("pageerror", (e) => cerr.push(String(e)));

// captura de TODOS los POST /approve (el corazón de la prueba: qué approval_id se ejecuta de verdad)
const approvePosts = [];
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
await page.route("**/v1/runs/enqueue", (route) => route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ job_id: "j_consent", run_id: "r_consent" }) }));
await page.route("**/v1/spaces/*/stream*", (route) => route.fulfill({ status: 200, contentType: "text/event-stream", headers: { "cache-control": "no-cache" }, body: sseBody(RUN_FRAMES) }));
await page.route("**/v1/runs/*/approve", (route) => {
  let body = null; try { body = JSON.parse(route.request().postData() || "null"); } catch {}
  approvePosts.push(body);
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ executed: true }) });
});

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__bindGateApprovals && window.Projection, null, { timeout: 15000 });

  // ── A) UNIT determinístico: la función REAL del worktree, sin DOM ──────────────────────────
  const unit = await page.evaluate((held) => {
    const gates = [{ tileId: "t_send", ux: { que_va_a_hacer: "enviar un aviso por Slack" }, action: "needs_ok", tool: "send_x" }];
    const cards = window.__bindGateApprovals(gates, held);
    const parent = cards.find((c) => c.tool === "send_x" && !c.delegated);
    const child  = cards.find((c) => c.delegated);
    return {
      parentApproval: parent ? parent.approvalId : null,
      childApproval: child ? child.approvalId : null,
      childDelegated: !!(child && child.delegated),
      childHasUx: !!(child && child.ux && child.ux.que_va_a_hacer),
      nCards: cards.length,
    };
  }, HELD_ACTIONS);
  ok(unit.parentApproval === "SEND_PARENT",
     "A · la tarjeta BENIGNA del padre se ata a SU held (SEND_PARENT), no a la del hijo por índice",
     `parent.approvalId=${unit.parentApproval} (bug: sería MONEY_CHILD)`);
  ok(unit.parentApproval !== "MONEY_CHILD",
     "A · la tarjeta del padre NUNCA recibe el approval_id de DINERO del hijo (confused-deputy cerrado)");
  ok(unit.childApproval === "MONEY_CHILD" && unit.childDelegated,
     "A · la held DELEGADA del hijo rinde su PROPIA tarjeta (aprobable, no huérfana)", `child.approvalId=${unit.childApproval}`);
  ok(unit.childHasUx, "A · la tarjeta del hijo lleva SU ux (el humano ve qué aprueba: el dinero)", JSON.stringify(unit.childHasUx));
  ok(unit.nCards === 2, "A · exactamente 2 tarjetas (aviso del padre + dinero del hijo)", `nCards=${unit.nCards}`);

  // ── B) E2E DOM: correr el flujo real y aprobar la tarjeta BENIGNA ───────────────────────────
  await page.evaluate(() => window.__cuarto.placeTile({ id: "t_send", key: "t_send", label: "Aviso (notify)", category: "act", atom: "tool", server: "notify", tools: ["send_x"] }));
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(150);
  // [Cuarto entrega, no corre] la tarea viaja por argumento (ya no hay input en el Cuarto).
  await page.evaluate(() => { window.__lastRun = undefined; });
  // [Cuarto entrega, no corre] el Cuarto ya no tiene botón de Ejecutar: correr es de La Sala.
  // El PIPELINE quedó intacto y sigue siendo lo que esta vara prueba — se dispara por código.
  await page.evaluate((p) => window.__ejecutarTurno(p), 'delegá el pago al cajero y avisame por Slack');

  // esperar a que el run cierre Y la gatebar aparezca (resolveGates ya montó la 1ª tarjeta)
  await page.waitForFunction(() => window.__lastRun !== undefined, null, { timeout: 20000 }).catch(() => {});
  await page.waitForFunction(() => { const b = document.getElementById("gatebar"); return b && !b.hidden; }, null, { timeout: 8000 }).catch(() => {});

  // la 1ª tarjeta DEBE describir el aviso benigno (no el dinero) — es lo que el humano ve al dar OK
  const card1 = await page.evaluate(() => ({
    what: (document.getElementById("gateWhat") || {}).textContent || "",
    count: (document.getElementById("gateCount") || {}).textContent || "",
    barHidden: (document.getElementById("gatebar") || {}).hidden,
  }));
  ok(!card1.barHidden, "B · la gatebar apareció (hay decisión humana que tomar)");
  ok(/aviso|slack/i.test(card1.what) && !/\$500|transferir/i.test(card1.what),
     "B · la 1ª tarjeta describe el AVISO benigno del padre (no el dinero del hijo)", `what="${card1.what}"`);
  ok(/1\/2/.test(card1.count), "B · la cola muestra 2 tarjetas (aviso + dinero), la 1ª en curso", `count="${card1.count}"`);

  // APROBAR la tarjeta benigna → el POST /approve DEBE ejecutar el approval_id BENIGNO, no el dinero
  await page.click("#gateOk");
  // esperar a que onOk resuelva (fetch + ecoReturn + sleep(750)) y next() monte la 2ª tarjeta (el dinero)
  await page.waitForFunction(() => /\$500|transferir/i.test((document.getElementById("gateWhat") || {}).textContent || ""),
    null, { timeout: 8000 }).catch(() => {});

  const firstPost = approvePosts[0] || {};
  ok(firstPost.approval_id === "SEND_PARENT",
     "B · aprobar el AVISO ejecuta el approval_id BENIGNO (SEND_PARENT) — el bug ejecutaría MONEY_CHILD",
     `POST.approval_id=${firstPost.approval_id} ok=${firstPost.ok}`);
  ok(!approvePosts.some((p) => p && p.approval_id === "MONEY_CHILD" && p.ok === true),
     "B · el DINERO del hijo NO se ejecutó por aprobar la tarjeta benigna (consentimiento informado intacto)",
     JSON.stringify(approvePosts));

  // la 2ª tarjeta (el dinero) SÍ se presenta como aprobable — antes quedaba huérfana (tile atascado)
  const card2 = await page.evaluate(() => ({
    what: (document.getElementById("gateWhat") || {}).textContent || "",
    barHidden: (document.getElementById("gatebar") || {}).hidden,
  }));
  ok(!card2.barHidden && /\$500|transferir/i.test(card2.what),
     "B · el DINERO del hijo se presenta como SU PROPIA tarjeta aprobable (no huérfana)", `what="${card2.what}"`);

  ok(cerr.length === 0, "0 errores de consola", cerr.slice(0, 2).join(" | "));
} catch (e) {
  ok(false, "excepción en el probe", String(e));
} finally {
  await browser.close();
  try { server.kill("SIGKILL"); } catch {}
}

console.log("");
if (fails.length) { console.error(`✗ B1 CONSENT ROJO — ${fails.length} fallas`); process.exit(1); }
console.log("✓ B1 CONSENT VERDE — el zip por índice cerrado: el OK del aviso NO ejecuta el dinero del hijo; el dinero es su propia tarjeta aprobable");
