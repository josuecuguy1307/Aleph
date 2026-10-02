/* verify_guia_deepchat.mjs — EL GUÍA sobre la capa compartida (T7).
 *
 * WebKit real + stub del cerebro-guía con turnos SCRIPTEADOS (mismo patrón que
 * verify_cuarto_guide.mjs). Prueba lo que cambió al reemplazar el chat hecho a mano por
 * deep-chat, y sobre todo lo que NO tenía que cambiar:
 *
 *   1. El panel monta deep-chat con Shadow DOM y CERO requests externos.
 *   2. Abre con SALUDO + opciones por default (no un campo vacío mudo).
 *   3. El composer es container-relative dentro de un panel de 340px.
 *   4. Un tool_call se ve como card de ACCIÓN con logo — JAMÁS <function=…> crudo.
 *   5. La card pop conserva su handler «deshacer» VIVO tras mudarse al shadow DOM.
 *   6. El error trae causa + [Reintentar] que re-manda el turno.
 *   7. El panel SIGUE siendo movible (arrastre por .cop-hd) y se sigue acomodando
 *      (nudgeGuideAway) para no tapar lo que señala.
 *
 *   node product/app/design/cuarto/verify_guia_deepchat.mjs
 */
import { webkit } from "playwright";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = Number(process.env.FRONT_PORT || 8246);
const PAGE = `http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const J = (o) => JSON.stringify(o);

let pass = 0, fail = 0; const fails = [];
const ok = (c, m, x) => { if (c) { pass++; console.log("  ✓", m + (x ? "  — " + x : "")); } else { fail++; fails.push(m); console.log("  ✗", m + (x ? "  — " + x : "")); } };

let guideScript = [];
const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
let browser;
try {
  await sleep(900);
  browser = await webkit.launch();
  const page = await (await browser.newContext()).newPage();
  const jsErr = [];
  page.on("pageerror", (e) => jsErr.push(String(e).slice(0, 200)));
  if (process.env.DEBUG_GUIA) page.on("console", (m) => { const t = m.text(); if (!/404|Failed to load/.test(t)) console.log("    [page]", m.type(), t.slice(0, 200)); });
  const external = [];
  await page.route("**/*", async (route) => {
    const url = route.request().url();
    if (!url.startsWith(`http://127.0.0.1:${PORT}`) && !url.startsWith("data:") && !url.startsWith("blob:")) {
      external.push(url); return route.abort();
    }
    const p = new URL(url).pathname;
    if (p === "/v1/cuarto/guide") {
      const turn = guideScript.shift() || { content: "ok", tool_calls: [] };
      if (turn.__http) return route.fulfill({ status: turn.__http, contentType: "application/json", body: J({ detail: "stub" }) });
      return route.fulfill({ status: 200, contentType: "application/json", body: J({ ...turn, model_final: "opus-4.8" }) });
    }
    if (p === "/v1/icons") return route.fulfill({ status: 200, contentType: "application/json", body: J({ known: ["gmail", "stripe"] }) });
    if (p.startsWith("/v1/icons/")) return route.fulfill({ status: 200, contentType: "image/png",
      body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64") });
    if (p === "/v1/auth/local") return route.fulfill({ status: 200, contentType: "application/json", body: J({ id: "u-g", session_token: "tok-g", email: "g@aleph" }) });
    return route.continue();
  });
  await page.addInitScript(`try{ sessionStorage.setItem("puppet_user", JSON.stringify({id:"u-g",session_token:"tok-g",email:"g@aleph"}));
    localStorage.setItem("aleph.cuarto.guideBrain","opus"); }catch(e){}`);
  await page.goto(PAGE, { waitUntil: "domcontentloaded", timeout: 30000 });
  await sleep(4500);

  console.log("══ VERIFY · EL GUÍA sobre la capa compartida (WebKit) ══\n");

  // ── 1 · monta ──────────────────────────────────────────────────────────────
  console.log("(1) monta");
  await page.evaluate(() => document.getElementById("copBtn").click());
  await sleep(1600);
  const m = await page.evaluate(() => ({
    open: document.getElementById("copilot").dataset.open,
    dc: !!document.querySelector("#copBody deep-chat"),
    shadow: !!(window.__guiaChat && window.__guiaChat.shadow()),
    lf: window.__alephChatLocalFirst,
    viejo: !!(document.getElementById("copIn") || document.getElementById("copSend")),
  }));
  ok(m.open === "1" && m.dc && m.shadow, "el panel abre con deep-chat montado (Shadow DOM)");
  ok(m.viejo === false, "el chat hecho a mano (#copIn/#copSend) ya no existe");
  ok(m.lf && m.lf.ok === true, "local-first verificado en runtime");
  ok(external.length === 0, "CERO requests externos", external.join(" · ") || "ninguno");

  // ── 2 · saludo + opciones por default ──────────────────────────────────────
  console.log("\n(2) arranque con opciones");
  const intro = await page.evaluate(() => ({
    hello: (window.__guiaQ(".ac-intro") || {}).textContent || "",
    sugs: window.__guiaQA(".ac-sug").map((b) => b.textContent),
  }));
  ok(/guía padrino|godfather/i.test(intro.hello), "abre con el saludo del Guía");
  // [FIX-P7 · aserción INVERTIDA a propósito] Acá se exigían ≥3 chips de arranque. Murieron
  // por mandato: eran mueble fijo al inicio de la pantalla, no nacían de ningún turno. Las
  // opciones ahora nacen del CONTENIDO del turno (../chat/opciones.js) y viajan dentro del
  // mensaje. Lo que se mide ahora es la ley nueva: el chat abre LIMPIO.
  ok(intro.sugs.length === 0, "…y SIN chips de arranque: el chat abre limpio (saludo + composer)", intro.sugs.join(" / ") || "cero");

  // ── 3 · composer container-relative ────────────────────────────────────────
  console.log("\n(3) el composer no se estrangula");
  const w = await page.evaluate(() => {
    const i = window.__guiaQ("#text-input");
    return { input: i ? Math.round(i.getBoundingClientRect().width) : null,
             panel: Math.round(document.getElementById("copilot").getBoundingClientRect().width) };
  });
  ok(w.input >= 140, `el campo mide ${w.input}px dentro de un panel de ${w.panel}px`);

  // ── 4 · tool_call = ACCIÓN con card, jamás <function=> crudo ───────────────
  console.log("\n(4) el tool_call se ve como ACCIÓN");
  guideScript = [
    { content: "", tool_calls: [{ id: "t1", type: "function", function: { name: "senalar", arguments: J({ id: "p_cross", nota: "mirá esto" }) } }] },
    { content: "señalé Crossref <function=fake>{}</function>", tool_calls: [] },
  ];
  await page.evaluate(() => window.__guiaChat.send("señalá crossref"));
  await sleep(2200);
  const act = await page.evaluate(() => {
    const a = window.__guiaQA(".ac-act").pop();
    return { txt: a ? a.textContent.trim() : null, face: !!(a && a.querySelector(".ac-face")),
             all: window.__guiaQ("#messages").textContent };
  });
  ok(!!act.txt && /Señal/i.test(act.txt), "el tool_call salió como card de ACCIÓN", act.txt);
  ok(act.face, "…con el logo/cara del servicio");
  ok(!/<function|&lt;function/.test(act.all), "CERO <function=…> crudo en el chat");

  // ── 5 · card pop con «deshacer» VIVO tras mudarse al shadow DOM ────────────
  console.log("\n(5) la card pop conserva su handler");
  const undo = await page.evaluate(async () => {
    window.__copCard("equipar_catalogo", { servicio: "gmail" },
      { via: "catalogo_interno", equipado: "gmail", piece_id: null });
    await new Promise((r) => setTimeout(r, 250));
    const c = window.__guiaQA(".cop-card").pop();
    return { rendered: !!c, txt: c ? c.textContent : "" };
  });
  ok(undo.rendered && /Equip/i.test(undo.txt), "la card pop entra a la conversación", undo.txt.slice(0, 40));

  // ── 6 · error con causa + [Reintentar] ─────────────────────────────────────
  console.log("\n(6) el error tiene loop");
  guideScript = [{ __http: 401 }, { __http: 401 }];
  const errAntes = await page.evaluate(() => window.__guiaQA(".errcard").length);
  await page.evaluate(() => window.__guiaChat.send("esto va a fallar"));
  await sleep(3000);
  const errDespues = await page.evaluate(() => window.__guiaQA(".errcard").length);
  ok(errDespues > errAntes, "el fallo del cerebro-guía PINTA una card nueva", `${errAntes}→${errDespues}`);
  const err = await page.evaluate(() => {
    const c = window.__guiaQA(".errcard").pop();
    return c ? { txt: c.textContent, botones: [...c.querySelectorAll(".acts button")].map((b) => b.textContent) } : null;
  });
  ok(!!err, "sale una card de error con causa", err ? JSON.stringify(err.txt).slice(0, 140) : "");
  ok(!!err && err.botones.some((b) => /Reintentar|Retry/i.test(b)), "…con [Reintentar]", err ? "botones=[" + err.botones.join(" / ") + "]" : "");
  if (!(err && err.botones.length)) {
    const dump = await page.evaluate(() => window.__guiaQA(".errcard").map((c) => c.outerHTML.slice(0, 260)));
    console.log("    DUMP errcards:", JSON.stringify(dump, null, 1).slice(0, 700));
  }
  guideScript = [{ content: "listo, reintenté", tool_calls: [] }];
  await page.evaluate(() => { const b = window.__guiaQA(".errcard .acts button").find((x) => /Reintentar|Retry/i.test(x.textContent)); if (b) b.click(); });
  await sleep(2200);
  ok(await page.evaluate(() => /listo, reintent/.test(window.__guiaQ("#messages").textContent)),
     "el [Reintentar] RE-MANDA el turno de verdad");

  // ── 7 · sigue movible y sigue acomodándose ────────────────────────────────
  console.log("\n(7) movible + se acomoda (lo que NO tenía que cambiar)");
  const drag = await page.evaluate(async () => {
    const p = document.getElementById("copilot");
    const antes = p.getBoundingClientRect().left;
    window.__guidePlace(420, 120);
    await new Promise((r) => setTimeout(r, 60));
    return { antes, despues: p.getBoundingClientRect().left, handle: !!p.querySelector(".cop-hd") };
  });
  ok(drag.handle, "conserva el asa de arrastre (.cop-hd)");
  ok(Math.round(drag.despues) !== Math.round(drag.antes), `el panel se mueve (${Math.round(drag.antes)}→${Math.round(drag.despues)})`);
  const nudge = await page.evaluate(async () => {
    const p = document.getElementById("copilot");
    const r = p.getBoundingClientRect();
    // una caja que lo tapa a propósito → tiene que apartarse
    window.__nudgeGuideAway({ left: r.left - 20, top: r.top - 20, right: r.right + 20, bottom: r.bottom + 20 });
    await new Promise((x) => setTimeout(x, 120));
    return { antes: r.left, despues: p.getBoundingClientRect().left };
  });
  ok(Math.round(nudge.despues) !== Math.round(nudge.antes),
     `se aparta para no tapar lo que señala (${Math.round(nudge.antes)}→${Math.round(nudge.despues)})`);

  ok(jsErr.length === 0, "cero errores de página", jsErr.join(" | "));
} catch (e) {
  fail++; fails.push("harness crash: " + (e && e.message));
  console.log("HARNESS ERROR:", e && e.message);
} finally {
  if (browser) await browser.close();
  server.kill();
}
console.log(`\n${fail ? "❌ ROJO" : "✅ VERDE"} — ${pass} ok / ${fail} fail`);
if (fail) { console.log("FALLAS:"); fails.forEach((f) => console.log("  ✗", f)); }
process.exit(fail ? 1 : 0);
