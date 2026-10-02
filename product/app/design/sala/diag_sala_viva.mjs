/* diag_sala_viva.mjs — DIAGNÓSTICO del bloqueador "en La Sala no se puede escribir".
 * NO repara nada: instrumenta la página REAL servida por el SIDECAR FROZEN del build
 * instalado (puerto propio 8201, datadir aislado) y reporta el estado CRUDO:
 *   H1 · canSend() real, ST.controlsReady, ST.brainState, disabled/readonly del textarea,
 *        ¿hay listener de submit?, ¿el submit llega al backend? (assert del request real)
 *   H2 · qué pide la página al backend y qué le contesta (con tiempos)
 * Run: node diag_sala_viva.mjs
 */
import { webkit } from "playwright";

const BASE = process.env.SALA_BASE || "http://127.0.0.1:8201";
const PAGE = `${BASE}/sala/sala.html`;
const out = (k, v) => console.log(`${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`);

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });

const errs = [], reqs = [], slow = [];
page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
page.on("console", (m) => { if (m.type() === "error") errs.push("console: " + m.text().slice(0, 200)); });
page.on("request", (r) => { if (r.url().includes("/v1/")) reqs.push({ m: r.method(), u: r.url().replace(BASE, ""), t0: Date.now() }); });
page.on("requestfinished", (r) => {
  const e = reqs.find((x) => x.u === r.url().replace(BASE, "") && !x.ms);
  if (e) e.ms = Date.now() - e.t0;
});

console.log("══ DIAGNÓSTICO · LA SALA MUDA ══");
console.log("página:", PAGE);
const tNav = Date.now();
await page.goto(PAGE, { waitUntil: "domcontentloaded", timeout: 30000 });
out("nav_ms", Date.now() - tNav);

// dar tiempo al boot (loadSalaModels + AlephBrain.resolve)
await page.waitForTimeout(6000);

// ── H1 · el estado CRUDO del gate y del composer ──
console.log("\n── H1 · GATE + COMPOSER ──");
const st = await page.evaluate(() => {
  const c = document.getElementById("composer"), s = document.getElementById("send");
  const cs = c ? getComputedStyle(c) : null;
  const r = c ? c.getBoundingClientRect() : null;
  // ¿quién está encima del composer en su propio centro? (overlay invisible = no se puede escribir)
  let topEl = null;
  if (r && r.width) {
    const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    topEl = el ? (el.tagName + (el.id ? "#" + el.id : "") + (el.className ? "." + String(el.className).slice(0, 40) : "")) : null;
  }
  const api = window.SalaPower && window.SalaPower.state ? window.SalaPower.state() : null;
  return {
    composer_exists: !!c,
    composer_disabled: c ? c.disabled : null,
    composer_readonly: c ? c.readOnly : null,
    composer_pointerEvents: cs ? cs.pointerEvents : null,
    composer_visibility: cs ? cs.visibility : null,
    composer_rect: r ? { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top) } : null,
    elementFromPoint_over_composer: topEl,
    send_exists: !!s,
    send_disabled: s ? s.disabled : null,
    send_title: s ? s.title : null,
    powerState: api,
  };
});
Object.entries(st).forEach(([k, v]) => out("  " + k, v));

// canSend()/ST no son globales: se leen por el efecto observable (send.disabled + title) y
// por el probe público SalaPower.state() (ready === ST.controlsReady).
out("  ST.controlsReady (via SalaPower.state().ready)", st.powerState ? st.powerState.ready : "SIN PROBE");

// ── ¿se puede ESCRIBIR? (teclado real, no .value=) ──
console.log("\n── H1b · ¿ACEPTA TECLADO? ──");
await page.click("#composer").catch(() => {});
await page.keyboard.type("hola prueba", { delay: 12 });
const typed = await page.inputValue("#composer").catch(() => "<no se pudo leer>");
out("  valor tras teclear", JSON.stringify(typed));
out("  ¿ACEPTA ESCRITURA?", typed === "hola prueba" ? "SÍ" : "NO");
out("  focus real", await page.evaluate(() => document.activeElement ? document.activeElement.id || document.activeElement.tagName : null));

// ── ¿ENVÍA? assert del request REAL al backend ──
console.log("\n── H1c · ¿EL ENVÍO LLEGA AL BACKEND? ──");
const before = reqs.length;
const runSeen = [];
page.on("request", (r) => { if (/\/v1\/(puppets\/run|chats|motor)/.test(r.url())) runSeen.push(r.method() + " " + r.url().replace(BASE, "")); });
await page.click("#send").catch((e) => out("  click send falló", String(e).slice(0, 120)));
await page.waitForTimeout(6000);
out("  requests /v1 nuevos tras enviar", reqs.length - before);
out("  requests de RUN vistos", runSeen.length ? runSeen : "NINGUNO");
const chat = await page.evaluate(() => {
  const box = document.querySelector(".chat-scroll");
  if (!box) return "<sin .chat-scroll>";
  return Array.from(box.children).map((n) => (n.textContent || "").trim().slice(0, 150));
});
out("  burbujas en el chat", chat);
out("  composer tras enviar", JSON.stringify(await page.inputValue("#composer").catch(() => "")));

// ── tráfico y errores ──
console.log("\n── TRÁFICO /v1 (con tiempos) ──");
reqs.forEach((r) => console.log(`  ${r.m} ${r.u} — ${r.ms == null ? "SIN TERMINAR (¿colgado?)" : r.ms + "ms"}`));
console.log("\n── ERRORES DE PÁGINA ──");
console.log(errs.length ? errs.map((e) => "  " + e).join("\n") : "  (ninguno)");

await browser.close();
