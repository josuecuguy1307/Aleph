#!/usr/bin/env node
/**
 * verify_p11_gate.mjs — FIX-P11 · §9 · EL GATE OFRECE SU DECISIÓN.
 *
 * EL BUG (caminata 2026-07-27): «la escritura quedó frenada esperando tu OK» — y nada más.
 * Te dice que espera y no te muestra dónde. Faltaba el TERCER botón —[Ver qué va a hacer]—
 * y, sobre todo, faltaba que ese botón sirviera DURANTE la espera: mientras el run todavía
 * no registró la acción, [Aprobar] y [No] están (bien) deshabilitados, y la tarjeta no
 * ofrecía absolutamente nada que tocar. Ver lo que va a pasar no necesita `approval_id`.
 *
 * Se mide sobre un gate REAL: espinazo SSE guionado (mismo patrón que verify_ux_b4_front),
 * la card del runtime, y el POST /v1/runs/{id}/approve de verdad interceptado para leer
 * qué mandó. WebKit + MOUSE REAL (los taps pasan por hit-testing: un botón deshabilitado
 * o tapado no se puede tocar, que es justamente lo que hay que distinguir).
 *
 * Corre: node product/app/design/sala/verify_p11_gate.mjs  (autocontenido, sin sidecar)
 */
import http from "http";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { webkit, chromium } from "playwright";

const DESIGN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SHOTS = process.env.SHOTS || path.join(DESIGN, "cuarto", "screenshots");
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
               ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };

const fails = [];
const ok = (c, label, extra) => {
  console.log(`${c ? "✓" : "✗"} ${label}${extra != null && extra !== "" ? "  — " + extra : ""}`);
  if (!c) fails.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const frame = (id, type, payload) =>
  `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(Object.assign({ type }, payload))}\n\n`;

const GATE_UX = {
  que_va_a_hacer: "mandar el informe por correo",
  donde_afecta: "la bandeja de contador@x.com",
  vista_previa: "Para: contador@x.com\nAsunto: Cierre trimestral\n\nAdjunto el informe.",
  requiere_ok: true, boton_ok: "Aprobar", boton_cancelar: "No",
  nivel: "confirma-siempre", accion_clase: "write-world", autonomia: "balanceado",
};
const TURN_TEXT = "Voy a mandarle el informe al contador con los totales del trimestre.";

// El espinazo deja UNA VENTANA de 2,5 s entre el freeze y el `closed` que trae el
// approval_id: es EXACTAMENTE el rato en que la persona lee «quedó frenada esperando tu OK»
// y no tiene nada que tocar. Ahí es donde se mide el tercer botón.
function spine(res) {
  res.write(frame(1, "gate_waiting", {
    kind: "tool_call", tool: "gmail", tool_raw: "send_email",
    args: { to: "contador@x.com", subject: "Cierre trimestral" },
    gate_action: "needs_ok", turn: 1, gate_ux: GATE_UX, turn_text: TURN_TEXT,
  }));
  setTimeout(() => {
    res.write(frame(2, "closed", {
      ok: true, run_id: "r-p11", model_final: "claude-code-opus-4.8", degraded: null,
      held_actions: [{ approval_id: "ap-p11", server: "gmail", tool: "send_email",
                       level: "confirma-siempre", action_class: "write-world", ux: GATE_UX }],
    }));
    res.end();
  }, 2500);
}

function serve() {
  const srv = http.createServer((req, r) => {
    const u = new URL(req.url, "http://x");
    /* GOTCHA (medido hoy): la Sala VIGENTE manda el turno por `POST /v1/puppets/run/stream`
     * (SSE), no por `/v1/spaces/{id}/stream` ni por el `POST /v1/puppets/run` de antes. Por
     * eso `verify_ux_b4_front.mjs` está ROJO EN LA BASE: su arnés apunta a puertas que el
     * chat ya no usa. Esta vara sirve el espinazo en la puerta que el producto abre HOY. */
    if (/\/v1\/(puppets\/run\/stream|spaces\/[^/]+\/stream)$/.test(u.pathname)) {
      r.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                         "Connection": "keep-alive", "X-Accel-Buffering": "no" });
      spine(r); return;
    }
    const p = path.join(DESIGN, decodeURIComponent(u.pathname));
    if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
    fs.createReadStream(p).pipe(r);
  });
  return new Promise((res) => srv.listen(0, "127.0.0.1", () => res(srv)));
}

const srv = await serve();
const BASE = `http://127.0.0.1:${srv.address().port}`;
console.log(`── verify_p11_gate · ${BASE}\n`);

const browser = await (process.env.NAV === "chromium" ? chromium : webkit).launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => {
  sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u-fx", email: "fx@x", session_token: "tok-fx" }));
});
const page = await ctx.newPage();
if (process.env.DEBUG) { page.on("request", (q) => { if (/\/v1\//.test(q.url())) console.log("   →", q.method(), q.url().replace(BASE, "")); }); page.on("pageerror", (e) => console.log("   ‼", String(e).slice(0,140))); }
const approves = [];
const j = (r, obj) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(obj) });
await page.route("**/v1/classify-turn", (r) => j(r, { turn: "build" }));
await page.route("**/v1/artifacts/classify-action", (r) => j(r, { action: "new" }));
await page.route("**/v1/runs/*/approve", (r) => {
  approves.push(JSON.parse(r.request().postData() || "{}"));
  const b = approves[approves.length - 1];
  return j(r, b.ok ? { found: true, executed: true, status: "executed" }
                   : { found: true, executed: false, status: "rejected" });
});
// `/v1/puppets/run/stream` NO se intercepta: lo sirve el servidor local con el espinazo
// SSE de arriba, que es lo que deja medir la VENTANA entre el freeze y el approval_id.
await page.route("**/v1/chats*", (r) => r.request().method() === "POST" ? j(r, { id: "chat-fx", title: "" }) : j(r, { total: 0, chats: [] }));
await page.route("**/v1/chats/**", (r) => j(r, { id: "chat-fx", messages: [] }));
await page.route("**/v1/belts/cards*", (r) => j(r, { cards: [], total: 0, servers_real: [], dropped: [] }));
await page.route("**/v1/users/**", (r) => j(r, { puppets: [], keys: [], docs: [] }));
await page.route("**/v1/sessions/**", (r) => j(r, { artifacts: [] }));
await page.route("**/v1/obra-caption", (r) => j(r, {}));

await page.goto(BASE + "/sala/sala.html");
await page.waitForFunction(() => typeof window.__salaGate === "object" && typeof window.__salaQ === "function", null, { timeout: 25000 });
await sleep(400);

/* ── EL FREEZE, tal como lo emite el runtime ────────────────────────────────────────
 * Primero llega `gate_waiting` (la acción se frenó) y SÓLO DESPUÉS el `closed` con el
 * `approval_id`. En el medio hay una ventana real —la que la persona vive como «quedó
 * frenada esperando tu OK»— donde no se puede decidir todavía. Se reproduce igual acá. */
await page.evaluate((ux) => {
  window.__salaGate.ensure({ sig: window.__salaGate.sig("gmail", "send_email"),
    ux, tool: "gmail", tool_raw: "send_email",
    turnText: "Voy a mandarle el informe al contador con los totales del trimestre.",
    args: { to: "contador@x.com", subject: "Cierre trimestral" } });
}, GATE_UX);
await page.waitForFunction(() => !!(window.__salaQ(".gate") || document.querySelector(".gate")), null, { timeout: 15000 });
await sleep(250);

// ── LA VENTANA DE LA ESPERA: el gate llegó, el approval_id todavía no ────────────────
const espera = await page.evaluate(() => {
  const g = (window.__salaQ(".gate") || document.querySelector(".gate"));
  const b = (s) => g.querySelector(s);
  return {
    ok: !!b(".acts .ok"), okDis: b(".acts .ok") ? b(".acts .ok").disabled : null,
    no: !!b(".acts .no"), noDis: b(".acts .no") ? b(".acts .no").disabled : null,
    ver: !!b(".acts .ver"), verDis: b(".acts .ver") ? b(".acts .ver").disabled : null,
    planOculto: b(".gplan") ? b(".gplan").hidden : null,
    frz: !!b(".frz"),
    texto: g.textContent.replace(/\s+/g, " ").slice(0, 130),
  };
});
console.log(`   card: "${espera.texto}"`);
ok(espera.ok && espera.no && espera.ver,
   "§9 · los TRES botones están: [Aprobar] [Ver qué va a hacer] [No]",
   `ok=${espera.ok} ver=${espera.ver} no=${espera.no}`);
ok(espera.frz && espera.okDis === true && espera.noDis === true,
   "§9 · durante la espera, decidir está (bien) deshabilitado…");
ok(espera.ver && espera.verDis !== true,
   "§9 · …pero MIRAR sigue vivo: no necesita approval_id (era el «no te muestra dónde»)");
ok(espera.planOculto === true, "§9 · el plan nace PLEGADO (§7·3)");

// [Ver qué va a hacer] EN PLENA ESPERA
await page.evaluate(() => (window.__salaQ(".gate .ver") || document.querySelector(".gate .ver")).click());
await sleep(200);
const abierto = await page.evaluate(() => {
  const p = (window.__salaQ(".gate .gplan") || document.querySelector(".gate .gplan"));
  return { oculto: p.hidden, texto: (p.textContent || "").replace(/\s+/g, " ").slice(0, 200) };
});
ok(abierto.oculto === false && abierto.texto.length > 5,
   "§9 · [Ver qué va a hacer] DESPLIEGA el plan durante la espera", abierto.texto.slice(0, 90));
ok(/send_email|gmail|contador/.test(abierto.texto),
   "§9 · …y lo que muestra es la acción REAL, no un texto genérico");
try { fs.mkdirSync(SHOTS, { recursive: true }); } catch (e) {}
await page.screenshot({ path: path.join(SHOTS, "p11-gate-tres-botones.png") });
console.log(`   📸 ${path.join(SHOTS, "p11-gate-tres-botones.png")}`);

// ── EL GATE SE VUELVE OPERABLE (llegó el `closed` con el approval_id) ──────────────
await page.evaluate(() => window.__salaGate.ensure({
  sig: window.__salaGate.sig("gmail", "send_email"), runId: "r-p11", approvalId: "ap-p11" }));
await page.waitForFunction(() => {
  const b = (window.__salaQ(".gate .acts .ok") || document.querySelector(".gate .acts .ok"));
  return b && !b.disabled;
}, null, { timeout: 15000 });
const operable = await page.evaluate(() => {
  const g = (window.__salaQ(".gate") || document.querySelector(".gate"));
  return { ok: !g.querySelector(".acts .ok").disabled, no: !g.querySelector(".acts .no").disabled,
           ver: !!g.querySelector(".acts .ver") };
});
ok(operable.ok && operable.no && operable.ver,
   "§9 · ya operable: los tres siguen ahí y los dos de decidir se habilitan");

// ── [No] CANCELA DE VERDAD ──────────────────────────────────────────────────────────
await page.evaluate(() => (window.__salaQ(".gate .acts .no") || document.querySelector(".gate .acts .no")).click());
await sleep(1400);
ok(approves.length === 1 && approves[0].ok === false,
   "§9 · [No] manda el rechazo REAL (POST approve ok:false), no un no-op",
   JSON.stringify(approves[0] || null));
const tras = await page.evaluate(() => ((window.__salaQ(".gate") || document.querySelector(".gate")) || {}).textContent || "");
ok(/no se hizo|no se ejecut|cancel/i.test(tras),
   "§9 · …y la tarjeta lo DICE: no se hizo", tras.replace(/\s+/g, " ").slice(0, 80));

await browser.close();
srv.close();
console.log("\n" + "─".repeat(78));
if (fails.length) {
  console.log(`✗ ${fails.length} FALLA(S):`);
  fails.forEach((f) => console.log("   · " + f));
  process.exit(1);
}
console.log("✓ §9 VERDE — el gate ofrece su decisión");
