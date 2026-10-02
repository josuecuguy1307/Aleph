/* ORDEN 6 · verificación VIVA del panel de memoria (probado, no razonado) — Núcleo inspector.
 *
 * Sin backend: /v1/** stubbeado + sesión inyectada. Cubre las 3 piezas nuevas del orden 6:
 *   A · SELECTOR DE HERENCIA → escribe recipe.memory.inherit ('skill_only' ⇄ ausente) + PUT /config
 *       durable cuando el agente ya está guardado (?puppet=<uuid>).
 *   B · PANEL "SOBRE VOS" (memoria de cuenta) → pendientes (Guardar/descartar) + activos (badge de
 *       proveniencia + prov) + podar; cada acción pega al endpoint correcto (confirm/reject/prune).
 *   C · BADGES kind/prov en las filas de memoria del AGENTE (A3): pericia/episódica + hecho/inferido.
 *   D · 0 errores JS.
 *
 * Puerto :8172.   Run: node verify_panel_orden6.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = fileURLToPath(new URL("..", import.meta.url));   // product/app/design
const PID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";   // uuid del agente "guardado"
const PIXI_ENTRY = fileURLToPath(new URL("../cuarto/cuarto.pixi.html", import.meta.url));
const serverCode = "import http.server,sys; from functools import partial; s=http.server.ThreadingHTTPServer(('127.0.0.1',0),partial(http.server.SimpleHTTPRequestHandler,directory=sys.argv[1])); print(s.server_address[1],flush=True); s.serve_forever()";
const server = spawn("python3", ["-u", "-c", serverCode, DESIGN_DIR], { stdio: ["ignore", "pipe", "inherit"] });
const PORT = await new Promise((resolve, reject) => {
  let output = "";
  server.stdout.setEncoding("utf8");
  server.stdout.on("data", (chunk) => {
    output += chunk;
    const line = output.split(/\r?\n/, 1)[0].trim();
    if (/^\d+$/.test(line)) resolve(Number(line));
  });
  server.once("error", reject);
  server.once("exit", (code) => reject(new Error(`Pixi test server exited before bind (code ${code}): ${output}`)));
});
const PAGE = `http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html?puppet=${PID}`;

const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${(!c && extra) ? "  · " + extra : ""}`); if (!c) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function openSection(page, heading) {
  const header = page.locator("#d-opts .osec-h").filter({ hasText: heading }).first();
  await header.waitFor({ state: "visible", timeout: 5000 });
  if (await header.getAttribute("aria-expanded") !== "true") await header.click();
}

const A3_MEMS = { puppet_id: PID, total: 2, usage: { entries: 2, bytes: 40 }, caps: { max_entries: 50 },
  memories: [
    { id: "m-skill", source: "agent", content: "usa unidades SI siempre", meta: { kind: "skill", provenance: "hecho" } },
    { id: "m-epi", source: "agent", content: "el usuario preguntó por vigas ayer", meta: { kind: "episodica", provenance: "inferencia" } },
  ] };
const ACCT_PROPS = { total: 1, proposals: [{ id: "p-1", content: "vive en Quito", pinned: false, meta: { provenance: "hecho" } }] };
const ACCT_MEMS = { total: 2, usage: { entries: 2, bytes: 30 },
  memories: [
    { id: "a-user", source: "user", content: "prefiere reportes cortos", meta: { provenance: "hecho" } },
    { id: "a-agent", source: "agent", content: "trabaja en logística", meta: { provenance: "inferencia" } },
  ] };

let browser;
try {
  browser = await chromium.launch(process.env.ALEPH_CHROMIUM_PATH
    ? { executablePath: process.env.ALEPH_CHROMIUM_PATH } : {});
} catch (error) {
  server.kill();
  throw error;
}
const calls = [];   // captura method+path de las mutaciones
const modelSelectorRequests = [];
try {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("dialog", (d) => d.accept());   // el podar pide confirm() → aceptar

  // sesión ANTES del init (loadPuppet corre al arrancar y necesita el token)
  await page.addInitScript(() => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u-1", session_token: "tok-1", email: "x@y.z" }));
  });

  // catch-all primero; overrides específicos DESPUÉS (playwright usa el último que matchea)
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.route("**/v1/atoms/catalog**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ atoms: [], total: 0 }) }));
  await page.route("**/v1/brains/status**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ providers: {} }) }));
  // El editor compila la receta con el modelo principal por defecto. Este mock entrega
  // un modelo localmente conectado al compilador; no invoca ningún proveedor ni API de pago.
  await page.route("**/v1/modelos/selector*", (r) => {
    modelSelectorRequests.push(r.request().url());
    console.log("MODEL FIXTURE served:", r.request().url(), "→ fixture-opus");
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    version: 2, default: "incluido.cognicion", default_id: "fixture-opus", seleccion_id: "fixture-opus",
    modelos: [{ slug: "incluido.cognicion", picker_id: "fixture-opus", id: "fixture-opus", familia: "incluido",
      label: "Opus (test fixture)", model: "fixture/no-provider-call", base_url: "http://127.0.0.1/fixture",
      estado: "probado", conectado: true, default: true }],
  }) });
  });
  await page.route("**/v1/users/**/puppets**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ puppets: [] }) }));
  await page.route("**/v1/puppets/*/memories**", (r) => {
    const m = r.request().method();
    // [op 3 · reclasificar] el PATCH del ⇄ se registra con su body ({kind}) para asertarlo
    if (m !== "GET") {
      let body = {}; try { body = JSON.parse(r.request().postData() || "{}"); } catch (e) {}
      calls.push(`${m} ${new URL(r.request().url()).pathname} ${JSON.stringify(body)}`);
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    }
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(A3_MEMS) });
  });
  await page.route("**/v1/account/proposals**", (r) => {
    const m = r.request().method();
    if (m !== "GET") { calls.push(`${m} ${new URL(r.request().url()).pathname}`); return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) }); }
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ACCT_PROPS) });
  });
  await page.route("**/v1/account/memories**", (r) => {
    const m = r.request().method();
    if (m === "DELETE") { calls.push(`DELETE ${new URL(r.request().url()).pathname}`); return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) }); }
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ACCT_MEMS) });
  });
  await page.route("**/v1/puppets/*/config**", (r) => {
    calls.push(`PUT-CONFIG ${new URL(r.request().url()).pathname}`);
    // devolvemos el config que mandaron para inspección
    let body = {}; try { body = JSON.parse(r.request().postData() || "{}"); } catch (e) {}
    calls.push("INHERIT=" + JSON.stringify(((body.config || {}).memory || {}).inherit));
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, id: PID }) });
  });

  await page.goto(PAGE, { waitUntil: "load" });
  // __loadPuppet se asigna al FINAL del módulo (tras el `await loadAtoms()` y tras `let curPiece`):
  // esperar por él garantiza que el módulo terminó de evaluar (evita el TDZ de curPiece).
  await page.waitForFunction(() => window.__cuarto && window.__openInspector && window.__loadPuppet, null, { timeout: 12000 });
  await page.waitForFunction(() => window.__models && window.__models.list, null, { timeout: 12000 });
  // compileModel() in cuarto.models.js reads its module-local `_cache.byId`, populated by
  // loadModels() from the selector (or the shared AlephModelSelector cache). That cache is
  // created during Pixi module startup; inject the route before navigation and verify the
  // exposed same cache before the first tilesToRecipe()/compileModel() call.
  const connectedFixture = await page.evaluate(() => {
    const db = window.__models || {};
    return (db.list || []).filter((m) => m.connected === true || m.conectado === true)
      .map((m) => ({ id: m.id, label: m.label, model: m.model }));
  });
  console.log("Connected fake models before recipe compilation:", JSON.stringify(connectedFixture),
    "selectorRequests=", JSON.stringify(modelSelectorRequests));
  if (!modelSelectorRequests.length || connectedFixture.length < 1) {
    throw new Error(`No connected fake model; stopped before compileModel(). selectorRequests=${JSON.stringify(modelSelectorRequests)} models=${JSON.stringify(connectedFixture)}`);
  }
  console.log("Fake model ID used:", connectedFixture[0].id);
  const compileProof = await page.evaluate(async (id) => {
    const { compileModel } = await import("./cuarto.models.js");
    const model = compileModel(id);
    return { id, primary: model.primary, base_url: model.base_url };
  }, connectedFixture[0].id);
  if (compileProof.primary !== "fixture/no-provider-call") {
    throw new Error(`compileModel() did not resolve the injected fixture: ${JSON.stringify(compileProof)}`);
  }
  console.log("compileModel fixture proof:", JSON.stringify(compileProof));

  // abrir el inspector del Núcleo
  await page.evaluate(() => window.__openInspector(window.__cuarto.nucleoData()));
  await sleep(400);   // deja que wireAccountMem/wireMemory resuelvan sus fetch

  // ── A · SELECTOR DE HERENCIA ──
  await openSection(page, "Herencia");
  const herDom = await page.evaluate(() => {
    const box = document.querySelector("#d-opts [data-herpanel]");
    const btns = box ? [...box.querySelectorAll(".switch.her button")].map((b) => ({ v: b.dataset.v, on: b.classList.contains("on"), t: b.textContent })) : [];
    return { present: !!box, btns };
  });
  ok(herDom.present && herDom.btns.length === 2, "A·herencia · el selector renderiza (2 modos)", JSON.stringify(herDom.btns));
  ok(herDom.btns.find((b) => b.v === "all")?.on && !herDom.btns.find((b) => b.v === "skill")?.on, "A·herencia · default = 'Todo lo que sabe'");

  // click "Solo la pericia" → recipe.memory.inherit = 'skill_only' + PUT /config
  await page.locator('#d-opts [data-herpanel] .switch.her button[data-v="skill"]').click();
  await sleep(250);
  const afterSkill = await page.evaluate(async () => {
    const { tilesToRecipe } = await import("./cuarto.recipe.js");
    const r = tilesToRecipe(window.__cuarto.placedTiles(), window.__cuarto.nucleoData());
    return { inherit: (r.memory || {}).inherit, nd: window.__cuarto.nucleoData()._inherit };
  });
  ok(afterSkill.inherit === "skill_only" && afterSkill.nd === "skill_only", "A·herencia · 'solo pericia' → recipe.memory.inherit='skill_only'", JSON.stringify(afterSkill));
  // review orden 6 (LOW): el toggle NO auto-PUTea la receta entera a /config (eso colaba ediciones sin
  // guardar + saltaba el gate de Guardar). Persiste al Guardar, como el resto de perillas del Núcleo.
  ok(!calls.some((c) => c.startsWith("PUT-CONFIG")), "A·herencia · NO auto-PUTea al togglear (persiste al Guardar)", calls.join(" | "));

  // click "Todo" → inherit se va (receta byte-idéntica a hoy: sin memory.inherit)
  await page.locator('#d-opts [data-herpanel] .switch.her button[data-v="all"]').click();
  await sleep(200);
  const afterAll = await page.evaluate(async () => {
    const { tilesToRecipe } = await import("./cuarto.recipe.js");
    const r = tilesToRecipe(window.__cuarto.placedTiles(), window.__cuarto.nucleoData());
    return { inherit: (r.memory || {}).inherit === undefined, nd: window.__cuarto.nucleoData()._inherit };
  });
  ok(afterAll.inherit && afterAll.nd === undefined, "A·herencia · volver a 'Todo' quita inherit (default = continuación)", JSON.stringify(afterAll));

  // review orden 6 (LOW #5): una política dict ({projects|entries}, sólo vía API hoy) se PRESERVA en la
  // receta — antes loadPuppet la colapsaba a undefined y el próximo Guardar la dropeaba en silencio.
  const dictPreserved = await page.evaluate(async () => {
    const { tilesToRecipe } = await import("./cuarto.recipe.js");
    const nd = window.__cuarto.nucleoData();
    nd._inherit = { projects: ["run-1"] };
    const r = tilesToRecipe(window.__cuarto.placedTiles(), nd);
    nd._inherit = undefined;
    return JSON.stringify((r.memory || {}).inherit);
  });
  ok(dictPreserved === '{"projects":["run-1"]}', "A·herencia · una política dict se PRESERVA en la receta (no se dropea al guardar)", dictPreserved);

  // ── B · PANEL "SOBRE VOS" (memoria de cuenta) ──
  await openSection(page, "Sobre ti");
  const acct = await page.evaluate(() => {
    const body = document.querySelector("#d-opts [data-acctbody]");
    if (!body) return { present: false };
    const prop = body.querySelector("[data-pid]");
    const mem = [...body.querySelectorAll("[data-mid]")];
    const userRow = mem.find((r) => r.querySelector(".memsrc.acctuser"));
    const agentRow = mem.find((r) => r.querySelector(".memsrc.acctagent"));
    return {
      present: true,
      propText: prop ? prop.querySelector(".memtxt")?.textContent : null,
      hasConfirm: !!(prop && prop.querySelector('[data-act="confirm"]')),
      hasReject: !!(prop && prop.querySelector('[data-act="reject"]')),
      pendBadge: !!(prop && prop.querySelector(".acctpend")),
      memCount: mem.length,
      userProv: userRow ? !!userRow.querySelector(".memprov.hecho") : false,
      agentProv: agentRow ? !!agentRow.querySelector(".memprov.inferencia") : false,
      hasPrune: mem.every((r) => !!r.querySelector('[data-act="prune"]')),
    };
  });
  ok(acct.present, "B·cuenta · el panel 'sobre vos' renderiza");
  ok(acct.propText === "vive en Quito" && acct.pendBadge && acct.hasConfirm && acct.hasReject, "B·cuenta · pendiente con badge 'propuesta' + Guardar + descartar", JSON.stringify(acct));
  ok(acct.memCount === 2 && acct.userProv && acct.agentProv, "B·cuenta · activos con badge de proveniencia (tuya/confirmada) + prov (hecho/inferido)", JSON.stringify(acct));
  ok(acct.hasPrune, "B·cuenta · cada activo tiene podar");

  // click Guardar (confirm) en la propuesta → POST /proposals/{id}/confirm
  await page.locator('#d-opts [data-acctbody] [data-pid] [data-act="confirm"]').click();
  await sleep(200);
  ok(calls.some((c) => c === "POST /v1/account/proposals/p-1/confirm"), "B·cuenta · Guardar → POST confirm al endpoint correcto", calls.join(" | "));

  // click podar (✕) en un activo → confirm() auto-aceptado → DELETE /memories/{id}
  const fixtureMemoryRow = page.locator('#d-opts [data-acctbody] [data-mid="a-user"]');
  await fixtureMemoryRow.locator('[data-act="prune"]').click();
  await sleep(200);
  ok(calls.some((c) => /^DELETE \/v1\/account\/memories\/a-(user|agent)$/.test(c)), "B·cuenta · podar → DELETE memories al endpoint correcto", calls.join(" | "));

  // ── C · BADGES kind/prov en las filas de memoria del AGENTE (A3) ──
  await openSection(page, "Memoria · contexto");
  const a3 = await page.evaluate(() => {
    const body = document.querySelector("#d-opts [data-membody]");
    if (!body) return { present: false };
    const rows = [...body.querySelectorAll(".memrow")];
    const skill = rows.find((r) => r.querySelector(".memkind.skill"));
    const epi = rows.find((r) => r.querySelector(".memkind.episodica"));
    return {
      present: true, count: rows.length,
      skillKind: !!skill, skillProvHecho: skill ? !!skill.querySelector(".memprov.hecho") : false,
      epiKind: !!epi, epiProvInf: epi ? !!epi.querySelector(".memprov.inferencia") : false,
    };
  });
  ok(a3.present && a3.count === 2, "C·A3 · las filas de memoria del agente renderizan");
  ok(a3.skillKind && a3.skillProvHecho, "C·A3 · fila 'pericia' con prov 'hecho'", JSON.stringify(a3));
  ok(a3.epiKind && a3.epiProvInf, "C·A3 · fila 'episódica' con prov 'inferido'", JSON.stringify(a3));

  // ── C2 · RECLASIFICAR (op 3): el ⇄ de la fila manda PATCH {kind: el opuesto} ──
  const rekind = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#d-opts [data-membody] .memrow')];
    const skillRow = rows.find((r) => r.querySelector(".memkind.skill"));
    const epiRow = rows.find((r) => r.querySelector(".memkind.episodica"));
    const sBtn = skillRow && skillRow.querySelector('[data-act="rekind"]');
    const eBtn = epiRow && epiRow.querySelector('[data-act="rekind"]');
    if (eBtn) eBtn.click();                    // episódica → pedirá skill
    return { sHas: !!sBtn, sTo: sBtn ? sBtn.dataset.kind : null, eHas: !!eBtn, eTo: eBtn ? eBtn.dataset.kind : null };
  });
  await sleep(250);
  ok(rekind.sHas && rekind.sTo === "episodica" && rekind.eHas && rekind.eTo === "skill",
    "C2·op3 · ambas filas etiquetadas llevan ⇄ con el destino OPUESTO", JSON.stringify(rekind));
  ok(calls.some((c) => /^PATCH \/v1\/puppets\/.+\/memories\/m-epi \{"kind":"skill"\}$/.test(c)),
    "C2·op3 · click ⇄ en episódica → PATCH {kind:'skill'} al endpoint correcto", calls.filter((c) => c.startsWith("PATCH")).join(" | "));

  const esLabels = await page.evaluate(() => {
    const text = (selector) => document.querySelector(selector)?.textContent.trim() || "";
    const sectionLabel = (selector) => {
      const header = document.querySelector(selector);
      return header ? [...header.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent).join("").trim() : "";
    };
    return {
      locale: window.AlephI18n.lang(),
      inheritance: sectionLabel('#d-opts [data-osec="mem|Herencia"] .osec-h'),
      owner: sectionLabel('#d-opts [data-osec="mem|Sobre ti"] .osec-h'),
      all: text('#d-opts [data-herpanel] .switch.her button[data-v="all"]'),
      proposed: text('#d-opts [data-acctbody] .acctpend'),
      expertise: text('#d-opts [data-membody] .memkind.skill'),
    };
  });
  ok(esLabels.locale === "es" && esLabels.inheritance === "Herencia" && esLabels.owner === "Sobre ti"
    && esLabels.all === "Todo lo que sabe" && esLabels.proposed === "propuesta" && esLabels.expertise === "pericia",
    "ES · vocabulario canónico de herencia, cuenta y memoria", JSON.stringify(esLabels));

  // ── D · 0 errores JS ──
  ok(errors.length === 0, "D · 0 errores JS en toda la interacción", errors.slice(0, 3).join(" | "));

  await page.close();

  // ══ ESCENARIO EN · bilingüe como el resto (capa TM ES→EN) ══
  const pen = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errsEn = [];
  pen.on("pageerror", (e) => errsEn.push(String(e)));
  const enModelRequests = [];
  await pen.addInitScript(() => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u-1", session_token: "tok-1", email: "x@y.z" }));
    localStorage.setItem("aleph-lang", "en");   // la capa TM aplica EN al montar
  });
  await pen.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await pen.route("**/v1/atoms/catalog**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ atoms: [], total: 0 }) }));
  await pen.route("**/v1/modelos/selector*", (r) => {
    enModelRequests.push(r.request().url());
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      version: 2, default: "incluido.cognicion", default_id: "fixture-opus", seleccion_id: "fixture-opus",
      modelos: [{ slug: "incluido.cognicion", picker_id: "fixture-opus", id: "fixture-opus", familia: "incluido",
        label: "Opus (test fixture)", model: "fixture/no-provider-call", base_url: "http://127.0.0.1/fixture",
        estado: "probado", conectado: true, default: true }],
    }) });
  });
  await pen.route("**/v1/users/**/puppets**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ puppets: [] }) }));
  await pen.route("**/v1/puppets/*/memories**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(A3_MEMS) }));
  await pen.route("**/v1/account/proposals**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ACCT_PROPS) }));
  await pen.route("**/v1/account/memories**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ACCT_MEMS) }));
  await pen.goto(PAGE, { waitUntil: "load" });
  await pen.waitForFunction(() => window.__cuarto && window.__openInspector && window.__loadPuppet, null, { timeout: 12000 });
  await pen.waitForFunction(() => window.__models && window.__models.list, null, { timeout: 12000 });
  const enConnected = await pen.evaluate(() => (window.__models.list || []).filter((m) => m.connected === true || m.conectado === true).map((m) => m.id));
  if (!enModelRequests.length || !enConnected.length) throw new Error(`EN fixture missing before panel assertions: requests=${JSON.stringify(enModelRequests)} connected=${JSON.stringify(enConnected)}`);
  await pen.evaluate(() => window.__openInspector(window.__cuarto.nucleoData()));
  await openSection(pen, "Inheritance");
  await openSection(pen, "About you");
  await openSection(pen, "Memory · context");
  await openSection(pen, "Model");
  await sleep(300);   // deja actuar al MutationObserver de estados que aún usan copy de runtime
  const en = await pen.evaluate(() => {
    const txt = (document.getElementById("d-opts") || document.body).innerText;
    const text = (selector) => document.querySelector(selector)?.textContent.trim() || "";
    const sectionLabel = (selector) => {
      const header = document.querySelector(selector);
      return header ? [...header.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent).join("").trim() : "";
    };
    return {
      locale: window.AlephI18n.lang(),
      inheritanceSection: sectionLabel('#d-opts [data-osec="mem|Inheritance"] .osec-h'),
      accountSection: sectionLabel('#d-opts [data-osec="mem|About you"] .osec-h'),
      inheritanceTitle: text('#d-opts [data-herpanel] .k'),
      accountTitle: text('#d-opts [data-acctpanel] .k'),
      inheritance: text('#d-opts [data-herpanel] .switch.her button[data-v="all"]'),
      proposed: text('#d-opts [data-acctbody] .acctpend'),
      expertise: text('#d-opts [data-membody] .memkind.skill'),
      workshopTerms: /THE MIND · EXECUTION/.test(txt) && /Active execution plan/.test(txt)
        && /No active auxiliary agents/.test(txt) && /Auxiliary agent model/.test(txt),
      noRawEs: !/Sobre el dueño|Sobre ti|Herencia|Todo lo que sabe|propuesta|pericia|Agentes auxiliares|Plan de ejecución activo/.test(txt),
    };
  });
  ok(en.locale === "en" && en.inheritanceSection === "Inheritance" && en.accountSection === "About you"
    && en.inheritanceTitle === "Which memory carries over" && en.accountTitle === "Account memory",
    "EN · encabezados de herencia y memoria de cuenta", JSON.stringify(en));
  ok(en.inheritance === "Everything it knows", "EN · botón de herencia", JSON.stringify(en));
  ok(en.proposed === "proposed" && en.expertise === "expertise", "EN · badges de propuesta y pericia", JSON.stringify(en));
  ok(en.workshopTerms, "EN · Mente/plan/agentes auxiliares conservan la terminología canónica", JSON.stringify(en));
  ok(en.noRawEs, "EN · sin español crudo en el inspector abierto", JSON.stringify(en));
  ok(errsEn.length === 0, "EN · 0 errores JS", errsEn.slice(0, 2).join(" | "));
  await pen.close();
} finally {
  await browser.close();
  server.kill();
}
console.log(`\n${fails.length ? "FAILS: " + fails.join("; ") : "ALL GREEN"}  (${fails.length} fallos)`);
process.exit(fails.length ? 1 : 0);
