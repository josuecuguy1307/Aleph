/* verify_metodo_sala.mjs — MÉTODO en la Sala (ORDEN §3-§5), probado no razonado.
 * Carga sala.html REAL en Chromium (server estático, sin backend) y maneja los seams
 * de producción (window.__metodoSala / __narrate / __ST). Cubre:
 *   P · propuesta contextual: card 3 opciones + libre · tal cual/ajustando/suelto ·
 *       typing nuevo descarta (nunca secuestra) · fail-open en timeout/err del match.
 *   G · guardar-desde-run al cierre exitoso (from_run) + ¿ajuste permanente?
 *   F · card de fallo §5 (diagnóstico + 5 salidas + libre) → seam remedy.
 *   EN · chrome bilingüe de las cards.
 * Correr: node product/app/design/sala/verify_metodo_sala.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { join, extname, resolve } from "node:path";

const ROOT = resolve(new URL("../", import.meta.url).pathname);
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };
const server = http.createServer((req, res) => {
  try {
    const p = decodeURIComponent(req.url.split("?")[0]);
    const f = join(ROOT, p);
    if (existsSync(f) && statSync(f).isFile()) { res.writeHead(200, { "Content-Type": MIME[extname(f)] || "text/plain" }); res.end(readFileSync(f)); }
    else { res.writeHead(404); res.end("nf"); }
  } catch (e) { res.writeHead(500); res.end(String(e)); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const PORT = server.address().port;

const fails = [];
const ok = (c, m, extra) => { console.log(`${c ? "✓" : "✗"} ${m}${(!c && extra) ? "  · " + extra : ""}`); if (!c) fails.push(m); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function boot(browser, lang) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript((l) => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u-1", session_token: "tok-1", email: "x@y.z" }));
    if (l) localStorage.setItem("aleph-lang", l);
  }, lang || "");
  const calls = [];
  await page.route("**/v1/**", (r) => {
    calls.push(r.request().method() + " " + new URL(r.request().url()).pathname + " " + (r.request().postData() || ""));
    r.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await page.route("**/v1/puppets/p1/methods", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ methods: [{ id: "m-earnings", name: "Cierre de earnings" }] }) }));
  await page.route("**/v1/methods/match", (r) => {
    calls.push("POST /v1/methods/match " + (r.request().postData() || ""));
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ match: { method_id: "m-earnings", name: "Cierre de earnings", last_run_days: 5 } }) });
  });
  await page.route("**/v1/methods/from_run", (r) => {
    calls.push("POST /v1/methods/from_run " + (r.request().postData() || ""));
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ method: { id: "m-nuevo", name: "Proceso del run" } }) });
  });
  await page.route("**/v1/methods/m-earnings/adjust_permanent", (r) => {
    calls.push("POST adjust_permanent " + (r.request().postData() || ""));
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });
  await page.route("**/v1/runs/**", (r) => {
    calls.push(r.request().method() + " " + new URL(r.request().url()).pathname + " " + (r.request().postData() || ""));
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });
  await page.goto(`http://127.0.0.1:${PORT}/sala/sala.html`, { waitUntil: "load" });
  await page.waitForFunction(() => window.__metodoSala && window.__narrate && window.__ST, null, { timeout: 12000 });
  errors.length = 0;   // el init sin backend mete ruido; cuentan los errores DESDE acá
  return { page, errors, calls };
}

const browser = await chromium.launch();
try {
  /* ══ P · PROPUESTA CONTEXTUAL ════════════════════════════════════════ */
  {
    const { page, errors, calls } = await boot(browser);
    // puppet con métodos equipados (cache sembrada = ya cargó)
    await page.evaluate(() => { window.__ST().puppetId = "p1"; window.__metodoSala.st().equipped = [{ id: "m-earnings", name: "Cierre de earnings" }]; });

    // eco → card con 3 opciones + respuesta libre
    const deferred = await page.evaluate(() => window.__metodoSala.maybePropose("arma el cierre de earnings del trimestre"));
    ok(deferred === true, "P · con eco posible, el turno se difiere (la card decide)");
    await page.waitForSelector("[data-metcard]", { timeout: 5000 });
    const card = await page.evaluate(() => {
      const d = document.querySelector("[data-metcard]");
      return { t: d.querySelector("b").textContent, p: d.querySelector("p").textContent,
        acts: [...d.querySelectorAll(".acts button")].map((b) => b.getAttribute("data-m")), free: d.querySelector(".mfree").textContent };
    });
    ok(/Cierre de earnings/.test(card.t), "P · la card nombra el método", card.t);
    ok(/hace 5 días/.test(card.p), "P · '…corrido hace 5 días' (dato real del match)", card.p);
    ok(card.acts.join(",") === "usar,ajustar,suelto", "P · tres opciones §4", JSON.stringify(card.acts));
    ok(/nunca te secuestra/.test(card.free), "P · la respuesta libre SIEMPRE está a la vista");

    // Usarlo tal cual → el RUN REAL viaja con method_id (capturado del POST) + consumo único
    await page.evaluate(() => document.querySelector('[data-metcard] [data-m="usar"]').click());
    await page.waitForFunction(() => window.__lastCalls && window.__lastCalls.length, null, { timeout: 100 }).catch(() => {});
    let runPost = null;
    for (let i = 0; i < 30 && !runPost; i++) { await sleep(150); runPost = calls.find((c) => c.startsWith("POST /v1/puppets/run") && /"method_id":\s*"m-earnings"/.test(c)); }
    ok(!!runPost && !/method_adjust/.test(runPost), "P · 'tal cual' → el run REAL viaja con method_id (sin ajuste)", calls.filter((c) => /puppets\/run/.test(c)).slice(-1).join(""));
    const b2 = await page.evaluate(() => window.__metodoSala.buildBody("x", "sp-1"));
    ok(b2.method_id === undefined, "P · el attach se consume UNA sola vez (no contamina el run siguiente)");
    const col1 = await page.evaluate(() => ({ txt: document.querySelector("[data-metcard]").textContent, link: !!document.querySelector('[data-metcard] [data-m="grafo"]') }));
    ok(/dirigiendo este run/.test(col1.txt) && col1.link, "P · card colapsa a 'dirigiendo este run' + ver modo workflow", col1.txt.slice(0, 60));
    const cont1 = await page.evaluate(() => window.__metodoSala.st()._continued);
    ok(cont1 === 1, "P · el turno original SIGUE su camino tras decidir (no se pierde)");

    // Ajustando algo → input libre → method_adjust viaja
    await page.evaluate(() => { document.querySelector("[data-metcard]").removeAttribute("data-metcard"); window.__metodoSala.st().lastRun = null; });
    await page.evaluate(() => window.__metodoSala.maybePropose("arma el cierre de earnings otra vez"));
    await page.waitForSelector("[data-metcard]", { timeout: 5000 });
    await page.evaluate(() => document.querySelector('[data-metcard] [data-m="ajustar"]').click());
    await page.fill("[data-metcard] [data-adj]", "sáltate la parte de guidance");
    await page.evaluate(() => document.querySelector('[data-metcard] [data-m="correr"]').click());
    let runAdj = null;
    for (let i = 0; i < 30 && !runAdj; i++) { await sleep(150); runAdj = calls.find((c) => c.startsWith("POST /v1/puppets/run") && /"method_adjust":\s*"sáltate la parte de guidance"/.test(c)); }
    ok(!!runAdj && /"method_id":\s*"m-earnings"/.test(runAdj), "P · 'ajustando' → el run REAL viaja con method_id + method_adjust", calls.filter((c) => /puppets\/run/.test(c)).slice(-1).join("").slice(0, 160));
    ok(await page.evaluate(() => /solo para este run/.test(document.querySelector("[data-metcard]").textContent)), "P · el ajuste queda declarado como de-un-run");

    // Suelto, sin método
    await page.evaluate(() => { document.querySelector("[data-metcard]").removeAttribute("data-metcard"); window.__metodoSala.st().lastRun = null; });
    await page.evaluate(() => window.__metodoSala.maybePropose("arma el cierre de earnings de nuevo"));
    await page.waitForSelector("[data-metcard]", { timeout: 5000 });
    await page.evaluate(() => document.querySelector('[data-metcard] [data-m="suelto"]').click());
    await sleep(150);
    const b4 = await page.evaluate(() => window.__metodoSala.buildBody("x", "sp-3"));
    ok(b4.method_id === undefined, "P · 'suelto' → el run sale SIN método");

    // NUNCA secuestra: typing nuevo con card pendiente → card neutralizada, turno nuevo sigue
    await page.evaluate(() => { document.querySelector("[data-metcard]").removeAttribute("data-metcard"); });
    await page.evaluate(() => window.__metodoSala.maybePropose("arma el cierre de earnings versión 4"));
    await page.waitForSelector("[data-metcard]", { timeout: 5000 });
    const free = await page.evaluate(() => window.__metodoSala.maybePropose("mejor dime un chiste"));
    ok(free === false, "P · mensaje nuevo con card pendiente → el turno NUEVO pasa directo (cero secuestro)");
    const neut = await page.evaluate(() => {
      const d = document.querySelector("[data-metcard]");
      return { acts: d.querySelectorAll(".acts").length, note: d.querySelector(".mfree").textContent };
    });
    ok(neut.acts === 0 && /quedó sin correr/.test(neut.note), "P · la card vieja se neutraliza con nota honesta", neut.note);

    // fail-open: match caído → el run sigue solo (sin card)
    await page.unroute("**/v1/methods/match");
    await page.route("**/v1/methods/match", (r) => r.fulfill({ status: 500, contentType: "application/json", body: "{}" }));
    const before = await page.evaluate(() => window.__metodoSala.st()._continued);
    await page.evaluate(() => { window.__metodoSala.st().pending = null; window.__metodoSala.maybePropose("otro cierre distinto"); });
    await page.waitForFunction((n) => window.__metodoSala.st()._continued > n, before, { timeout: 4000 });
    ok(true, "P · match caído → fail-open: el turno corre igual, sin card");

    /* ── P+ · fixes del review adversarial ─────────────────────────────── */
    // PRE-CARD race: typing nuevo con match EN VUELO → nota honesta suelta + el viejo no corre fantasma
    await page.unroute("**/v1/methods/match");
    await page.route("**/v1/methods/match", async (r) => { await sleep(3000); r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ match: null }) }); });
    const contBefore = await page.evaluate(() => window.__metodoSala.st()._continued);
    await page.evaluate(() => { window.__metodoSala.st().pending = null; window.__metodoSala.st().card = null; window.__metodoSala.maybePropose("pedido uno que quedará sin correr"); });
    const second = await page.evaluate(() => window.__metodoSala.maybePropose("pedido dos inmediato"));
    ok(second === false, "P+ · segundo mensaje pre-card pasa directo (cero secuestro)");
    const note = await page.evaluate(() => [...document.querySelectorAll(".metnote")].map((n) => n.textContent).join("|"));
    ok(/quedó sin correr/.test(note), "P+ · race pre-card: nota honesta SUELTA en el chat (sin turno tragado en silencio)", note);
    await sleep(1600);
    const contAfter = await page.evaluate(() => window.__metodoSala.st()._continued);
    ok(contAfter === contBefore, "P+ · el pedido viejo NO se re-despacha fantasma tras el timeout", contBefore + "→" + contAfter);

    // decisión cacheada: ↻ Reintentar con el MISMO pedido → sin card, decisión re-aplicada
    await page.evaluate(() => { window.__metodoSala.st().lastDecision = { t: "reintento x", attach: { method_id: "m-earnings", name: "Cierre de earnings" } }; });
    const again = await page.evaluate(() => window.__metodoSala.maybePropose("reintento x"));
    const reAttach = await page.evaluate(() => (window.__metodoSala.st().attach || {}).method_id || null);
    ok(again === false && reAttach === "m-earnings", "P+ · mismo pedido ya decidido → sin re-preguntar, decisión re-aplicada", JSON.stringify({ again, reAttach }));

    // un turno de CHARLA no arrastra el attach al run siguiente
    await page.route("**/v1/classify-turn", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ turn: "chat" }) }));
    await page.evaluate(() => { window.__metodoSala.st().bypass = true; });
    await page.fill("#composer", "charla suelta cualquiera");
    await page.evaluate(() => document.getElementById("send").click());
    await page.waitForFunction(() => window.__metodoSala.st().attach === null, null, { timeout: 5000 });
    ok(true, "P+ · turno de charla limpia el attach (no contamina el run siguiente)");

    ok(errors.length === 0, "P · 0 errores JS", errors.slice(0, 3).join(" | "));
    await page.close();
  }

  /* ══ G · GUARDAR-DESDE-RUN + AJUSTE PERMANENTE ═══════════════════════ */
  {
    const { page, errors, calls } = await boot(browser);
    // run exitoso con trabajo real (≥2 tools) y SIN método → card de guardar
    await page.evaluate(() => window.__metodoSala.afterClose("cerrar el mes", { ok: true, run_id: "r-9", record: { tool_calls: [{ tool: "a" }, { tool: "b" }, { tool: "c" }] } }));
    await page.waitForSelector("[data-metsave]", { timeout: 5000 });
    ok(true, "G · run exitoso con proceso real → ofrece 'Guardar como Método'");
    // idempotente por run
    await page.evaluate(() => window.__metodoSala.afterClose("cerrar el mes", { ok: true, run_id: "r-9", record: { tool_calls: [{ tool: "a" }, { tool: "b" }] } }));
    const nSave = await page.evaluate(() => document.querySelectorAll("[data-metsave]").length);
    ok(nSave === 1, "G · la oferta es UNA por run (no spamea)");
    // chat sin proceso → cero teatro
    await page.evaluate(() => window.__metodoSala.afterClose("hola", { ok: true, run_id: "r-10", record: { tool_calls: [] } }));
    await sleep(200);
    const nSave2 = await page.evaluate(() => document.querySelectorAll("[data-metsave]").length);
    ok(nSave2 === 1, "G · un turno sin trabajo real NO ofrece guardar (cero teatro)");
    // guardar → from_run + link para abrirlo
    await page.evaluate(() => document.querySelector('[data-metsave] [data-m="si"]').click());
    await page.waitForFunction(() => /Método guardado/.test((document.querySelector("[data-metsave]") || {}).textContent || ""), null, { timeout: 4000 });
    const link = await page.evaluate(() => (document.querySelector("[data-metsave] a") || {}).getAttribute("href"));
    ok(calls.some((c) => c.startsWith("POST /v1/methods/from_run") && /"run_id":\s*"r-9"/.test(c)), "G · Guardar → POST from_run con el run real");
    ok(/metodo\.html\?method=m-nuevo/.test(link || ""), "G · 'abrirlo →' apunta al método recién creado", link);

    // run CON ajuste → al cierre pregunta ¿permanente?
    await page.evaluate(() => { window.__metodoSala.st().lastRun = { method_id: "m-earnings", adjust: "sáltate guidance" }; });
    await page.evaluate(() => window.__metodoSala.afterClose("cierre ajustado", { ok: true, run_id: "r-11", record: { tool_calls: [{ tool: "a" }, { tool: "b" }] } }));
    await page.waitForSelector("[data-metadj]", { timeout: 5000 });
    await page.evaluate(() => document.querySelector('[data-metadj] [data-m="si"]').click());
    await page.waitForFunction(() => /Ajuste guardado/.test((document.querySelector("[data-metadj]") || {}).textContent || ""), null, { timeout: 4000 });
    ok(calls.some((c) => c.startsWith("POST adjust_permanent") && /sáltate guidance/.test(c) && /"run_id":\s*"r-11"/.test(c)), "G · '¿permanente?' → seam adjust_permanent con el ajuste real");

    // run fallido → NO ofrece nada
    await page.evaluate(() => window.__metodoSala.afterClose("fallo", { ok: false, run_id: "r-12", record: { tool_calls: [{ tool: "a" }, { tool: "b" }] } }));
    await sleep(200);
    const nAll = await page.evaluate(() => document.querySelectorAll("[data-metsave],[data-metadj]").length);
    ok(nAll === 2, "G · run NO exitoso → sin ofertas (honesto)");

    ok(errors.length === 0, "G · 0 errores JS", errors.slice(0, 3).join(" | "));
    await page.close();
  }

  /* ══ F · CARD DE FALLO §5 (por el espinazo real) ═════════════════════ */
  {
    const { page, errors, calls } = await boot(browser);
    await page.evaluate(() => {
      window.__ST().puppetId = "p1";
      window.__narrate({ type: "method_started", method_id: "m-earnings", name: "Cierre de earnings", run_id: "r-20" });
    });
    const chip = await page.evaluate(() => [...document.querySelectorAll(".gate.met")].map((d) => d.textContent).join(" | "));
    ok(/dirigiendo este run/.test(chip) && /workflow/.test(chip), "F · method_started → chip 'dirigiendo' + link al modo workflow", chip.slice(0, 80));

    await page.evaluate(() => window.__narrate({ type: "method_step_failed", run_id: "r-20", step_id: "s3", step_text: "Enviar el resumen", executor: "gmail", diagnosis: "credencial faltante", remedies: { suggested_label: "reconectar gmail" } }));
    await page.waitForSelector(".gate.metfail", { timeout: 5000 });
    const fc = await page.evaluate(() => {
      const d = document.querySelector(".gate.metfail");
      return { p: d.querySelector("p").textContent, diag: d.querySelector(".diag").textContent,
        acts: [...d.querySelectorAll("[data-rem]")].map((b) => b.getAttribute("data-rem")), free: !!d.querySelector("[data-rem-free]") };
    });
    ok(/Enviar el resumen/.test(fc.p), "F · la card nombra el paso trabado (dato real del evento)");
    ok(/credencial faltante/.test(fc.diag), "F · diagnóstico del Motor B visible", fc.diag);
    ok(fc.acts.join(",") === "apply,retry,retry_in,skip,edit" && fc.free, "F · remedios §5 completos + respuesta libre", JSON.stringify(fc.acts));
    await page.evaluate(() => document.querySelector('.gate.metfail [data-rem="skip"]').click());
    await page.waitForFunction(() => /al mando/.test((document.querySelector(".gate.metfail") || {}).textContent || ""), null, { timeout: 4000 });
    ok(calls.some((c) => c.startsWith("POST /v1/runs/r-20/method/remedy") && /"action":\s*"skip"/.test(c)), "F · Saltar → seam remedy action=skip (queda en auditoría del runtime)");

    /* ── F+ · fixes del review adversarial ─────────────────────────────── */
    // method_started duplicado del MISMO run → UN solo chip (ranWith por-run)
    await page.evaluate(() => window.__narrate({ type: "method_started", method_id: "m-earnings", name: "Cierre de earnings", run_id: "r-20" }));
    const chips = await page.evaluate(() => [...document.querySelectorAll(".gate.met")].filter((d) => /dirigiendo/.test(d.textContent)).length);
    ok(chips === 1, "F+ · method_started duplicado → UN solo chip 'dirigiendo'", String(chips));

    // [H6] scrub en la card de fallo: diagnóstico/sugerencia con secreto → ‹oculto›
    await page.evaluate(() => window.__narrate({ type: "method_step_failed", run_id: "r-20", step_id: "s9", diagnosis: "la key sk_live-abc123def456 venció", remedies: { suggested_label: "rotar token ghp_zzzzzz123456" } }));
    await sleep(150);
    const scr = await page.evaluate(() => [...document.querySelectorAll(".gate.metfail")].pop().textContent);
    ok(/‹oculto›/.test(scr) && !/sk_live-abc123def456|ghp_zzzzzz123456/.test(scr), "F+ · diagnóstico y sugerencia scrubbeados (‹oculto›)", scr.slice(0, 120));

    ok(errors.length === 0, "F · 0 errores JS", errors.slice(0, 3).join(" | "));
    await page.close();
  }

  /* ══ EN · chrome bilingüe de las cards ═══════════════════════════════ */
  {
    const { page, errors } = await boot(browser, "en");
    await page.evaluate(() => { window.__ST().puppetId = "p1"; window.__metodoSala.st().equipped = [{ id: "m-earnings", name: "Cierre de earnings" }]; });
    await page.evaluate(() => window.__metodoSala.maybePropose("build the earnings close"));
    await page.waitForSelector("[data-metcard]", { timeout: 5000 });
    await page.evaluate(() => window.__narrate({ type: "method_step_failed", run_id: "r-30", step_id: "s1", diagnosis: "missing credential" }));
    await page.waitForSelector(".gate.metfail", { timeout: 5000 });
    const en = await page.evaluate(() => {
      const c = document.querySelector("[data-metcard]").textContent;
      const f = document.querySelector(".gate.metfail").textContent;
      return {
        match: /This matches your Method/.test(c), asis: /Use it as is/.test(c), hijack: /never hijacks/.test(c),
        days: /last run 5 days ago/.test(c),
        failH: /you are in charge/.test(f), retry: /Retry now/.test(f), skip: /stays in the audit/.test(f),
        noEs: !/Usarlo tal cual|nunca te secuestra|Reintentar ahora/.test(c + f),
      };
    });
    ok(en.match && en.asis && en.hijack && en.days, "EN · card de propuesta traducida", JSON.stringify(en));
    ok(en.failH && en.retry && en.skip, "EN · card de fallo traducida");
    ok(en.noEs, "EN · sin español crudo en las cards");
    ok(errors.length === 0, "EN · 0 errores JS", errors.slice(0, 2).join(" | "));
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
}
console.log(`\n${fails.length ? "FAILS: " + fails.join("; ") : "ALL GREEN"}  (${fails.length} fallos)`);
process.exit(fails.length ? 1 : 0);
