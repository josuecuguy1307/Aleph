#!/usr/bin/env node
/**
 * Workshop locale regression: both production entry points, keyed chrome, user-facing samples,
 * nested panels, the Mind's live/empty states, language reload, navigation return, and a fresh
 * browser context restored from persisted localStorage (the desktop-restart analogue).
 * Run: node product/app/design/cuarto/verify_workshop_i18n.mjs
 */
import { spawn } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN = join(HERE, "..");
const REPO = fileURLToPath(new URL("../../../..", import.meta.url));
const EVIDENCE = join(REPO, "reports", "step5", "evidence");
const BASE_PATH = "http://127.0.0.1";
const failures = [];
const keyTranslations = { es: {}, en: {} };
let passes = 0;
const check = (condition, label, detail = "") => {
  if (condition) { passes++; console.log(`  PASS  ${label}`); }
  else { failures.push(label); console.log(`  FAIL  ${label}${detail ? ` — ${detail}` : ""}`); }
};
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function sourcePreflight() {
  const [dictionary, dc, pixi, bridge, evidence, semaforo, connectionHook, brain] = await Promise.all([
    readFile(join(DESIGN, "i18n.js"), "utf8"),
    readFile(join(DESIGN, "Cuarto.dc.html"), "utf8"),
    readFile(join(DESIGN, "cuarto", "cuarto.pixi.html"), "utf8"),
    readFile(join(DESIGN, "bridge.js"), "utf8"),
    readFile(join(HERE, "cuarto.evidence.js"), "utf8"),
    readFile(join(HERE, "cuarto.semaforo.js"), "utf8"),
    readFile(join(DESIGN, "conexiones", "cuarto.hook.js"), "utf8"),
    readFile(join(DESIGN, "brain-status.js"), "utf8"),
  ]);
  const enStart = dictionary.indexOf("    en: {");
  const esEnd = dictionary.indexOf("    },\n    en: {");
  const enEnd = dictionary.indexOf("    },\n  };", enStart);
  if (enStart < 0 || esEnd < 0 || enEnd < 0) throw new Error("No pude delimitar los diccionarios ES/EN.");
  const esBlock = dictionary.slice(dictionary.indexOf("    es: {"), esEnd);
  const enBlock = dictionary.slice(enStart, enEnd);
  const extract = (block) => {
    const keys = [];
    const re = /["'](workshop\.[^"']+)["']\s*:/g;
    let m;
    while ((m = re.exec(block))) keys.push(m[1]);
    return keys;
  };
  const esKeys = extract(esBlock), enKeys = extract(enBlock);
  const duplicates = (keys) => keys.filter((key, i) => keys.indexOf(key) !== i);
  const esSet = new Set(esKeys), enSet = new Set(enKeys);
  const parity = [...new Set([...esKeys, ...enKeys])].filter((key) => esSet.has(key) !== enSet.has(key));
  check(!duplicates(esKeys).length && !duplicates(enKeys).length,
    "preflight · sin claves workshop duplicadas", [...duplicates(esKeys), ...duplicates(enKeys)].join(", "));
  check(!parity.length, "preflight · diccionarios ES/EN con paridad de claves", parity.join(", "));
  const allKeys = new Set([...esKeys, ...enKeys]);
  const source = [dc, pixi, bridge, evidence, semaforo, connectionHook].join("\n");
  const refs = new Set();
  const refRe = /["'](workshop\.[^"']+)["']/g;
  let m;
  while ((m = refRe.exec(source))) refs.add(m[1]);
  const missing = [...refs].filter((key) => !key.endsWith(".") && !allKeys.has(key));
  check(!missing.length, "preflight · toda clave workshop referenciada existe en ES y EN", missing.join(", "));
  let activeLang = "es", pendingLang = null;
  const runtime = { window: {}, document: { readyState: "loading", documentElement: { setAttribute() {} }, addEventListener() {} },
    localStorage: { getItem: () => activeLang, setItem: (_key, value) => { activeLang = value; } },
    sessionStorage: { getItem: () => pendingLang, setItem: (_key, value) => { pendingLang = value; }, removeItem: () => { pendingLang = null; } } };
  runInNewContext(dictionary, runtime);
  const dictRuntime = runtime.window.AlephI18n;
  for (const locale of ["es", "en"]) {
    activeLang = locale;
    for (const key of [...esKeys, "brain.model_prefix", "brain.unread"])
      keyTranslations[locale][key] = dictRuntime.t(key);
  }
  activeLang = "es";
  const esRuntimeMissing = esKeys.filter((key) => dictRuntime.t(key) === key);
  activeLang = "en";
  const enRuntimeMissing = enKeys.filter((key) => dictRuntime.t(key) === key);
  activeLang = "es"; pendingLang = "en";
  const explicitSelectionWins = dictRuntime.lang() === "en" && activeLang === "en";
  pendingLang = null;
  const representative = activeLang === "en" &&
    dictRuntime.t("workshop.title") === "The Workshop" &&
    dictRuntime.t("workshop.action.return") === "Back to The Workshop" &&
    dictRuntime.t("workshop.mind") === "THE MIND · EXECUTION" &&
    dictRuntime.t("workshop.agents.empty") === "No active auxiliary agents" &&
    dictRuntime.t("workshop.multi.plan_ready", { steps: 2, links: 3 }) === "2 steps · 3 connections · contract confirmed";
  check(!esRuntimeMissing.length && !enRuntimeMissing.length,
    "preflight · el traductor resuelve en runtime todas las claves ES/EN",
    [...esRuntimeMissing, ...enRuntimeMissing].slice(0, 8).join(", "));
  check(representative, "preflight · traducción canónica e interpolación runtime");
  check(explicitSelectionWins, "preflight · selección explícita pendiente gana y repara localStorage frente a hidratación antigua");
  activeLang = "es";
  check(dictRuntime.t("workshop.action.return") === "Volver al Cuarto" &&
    bridge.includes('t("workshop.action.return")'),
    "preflight · el puente de retorno usa el nombre canónico ES/EN");
  check(dictionary.includes("localStorage.setItem('aleph-lang', l)") &&
    dictionary.includes("AlephTheme.guardar('idioma', l)") &&
    dictionary.includes("sessionStorage.setItem('aleph-lang-pending', l)") &&
    dictionary.includes("location.reload()"),
    "preflight · elección explícita sobrevive hidratación de cuenta y reconstruye");
  check(dictionary.includes("document.documentElement.setAttribute('lang', l)") &&
    dictionary.includes("if (mu.target.parentElement) apply(mu.target.parentElement)") &&
    dictionary.includes("if (el.textContent !== value) el.textContent = value"),
    "preflight · rerender DC reaplica claves canónicas sin bucle del observador");
  check(dc.includes('src="./i18n.js"') && pixi.includes('src="../i18n.js"'),
    "preflight · ambas entradas cargan el diccionario compartido");
  // Execute the production mode renderer against a minimal DOM. This exercises
  // both locale dictionaries and all mode states without needing Chromium.
  const modeRenderer = pixi.match(/function sincronizarModo\(\) \{([\s\S]*?)\n      \}\n      window\.__modo/);
  if (!modeRenderer) throw new Error("No pude localizar el renderer real del modo Pixi.");
  const modeFailures = [];
  for (const locale of ["es", "en"]) {
    activeLang = locale;
    for (const [mode, focus, stateKey, titleKey] of [
      ["mcps", false, "workshop.view.mcp_mode", "workshop.view.mode_mcp_title"],
      ["trabajo", false, "workshop.view.work_mode", "workshop.view.mode_work_title"],
      ["trabajo", true, "workshop.view.work_mode_one", "workshop.view.mode_work_title"],
    ]) {
      const node = () => ({ attrs: {}, classList: { toggle() {} },
        setAttribute(key, value) { this.attrs[key] = value; } });
      const nodes = { modoBtn: node(), modoState: node() };
      runInNewContext(`function sincronizarModo() {${modeRenderer[1]}\n}; sincronizarModo();`, {
        cuarto: { modo: () => ({ modo: mode, focus }) }, $: (id) => nodes[id],
        _wt: (key) => dictRuntime.t(key),
      });
      if (nodes.modoBtn.attrs["data-i18n-title"] !== titleKey || nodes.modoBtn.title !== dictRuntime.t(titleKey)
        || nodes.modoState.attrs["data-i18n"] !== stateKey || nodes.modoState.textContent !== dictRuntime.t(stateKey)) {
        modeFailures.push({ locale, mode, focus, nodes });
      }
    }
  }
  check(!modeFailures.length, "preflight · renderer real Pixi conserva claves/textos/títulos en seis estados ES/EN",
    JSON.stringify(modeFailures));
  const taskRenderer = pixi.match(/function ttPaint\(\) \{([\s\S]*?)\n      \}\n      function escTT/);
  const gateRenderer = pixi.match(/const show = \(\) => \{([\s\S]*?)\n          \};\n          const cleanup/);
  const degradedRenderer = pixi.match(/function refreshAntiGrift\(\) \{([\s\S]*?)\n      \}\n      window\.__antiGriftBanner/);
  if (!taskRenderer || !gateRenderer || !degradedRenderer) throw new Error("Falta un renderer Pixi en la auditoría estática.");
  const taskFailures = [], gateFailures = [], degradedFailures = [];
  for (const locale of ["es", "en"]) {
    activeLang = locale;
    for (const [status, key] of [["run", "workshop.task.running"], ["done", "workshop.task.done"],
      ["err", "workshop.task.error"], ["held", "workshop.task.held"]]) {
      const nodes = { teamtasks: {}, ttBody: {}, ttCount: {} };
      runInNewContext(`function ttPaint() {${taskRenderer[1]}\n}; ttPaint();`, {
        document: { getElementById: (id) => nodes[id] },
        teamTasks: { agents: new Map([["fixture", { label: "fixture-agent", rows: [{ st: status, task: "fixture-task" }] }]]) },
        escTT: String, scrubSec: String, _wt: (k) => dictRuntime.t(k),
      });
      if (nodes.teamtasks.hidden || !nodes.ttBody.innerHTML.includes(`· ${dictRuntime.t(key)}</em>`)
        || nodes.ttCount.textContent !== "(1)") taskFailures.push({ locale, status, nodes });
    }
    for (const [action, customLabel, key] of [["needs_ok", null, "workshop.gate.approve"],
      ["blocked", null, "workshop.gate.blocked"], ["needs_ok", "fixture-runtime-action", null]]) {
      const node = () => ({ attrs: { "data-i18n": "workshop.gate.approve" },
        setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; } });
      const okBtn = node(), nodes = {};
      runInNewContext(`const show = () => {${gateRenderer[1]}\n}; show();`, {
        queue: [{ action, ux: { boton_ok: customLabel, donde_afecta: "fixture-place" }, tool: "fixture-tool" }], idx: 0,
        okBtn, noBtn: node(), bar: {}, $: (id) => nodes[id] ||= {},
        _wt: (k, vars) => dictRuntime.t(k, vars), window: { AlephI18n: dictRuntime }, AlephI18n: dictRuntime,
      });
      if (okBtn.attrs["data-i18n"] !== (key || undefined) || okBtn.textContent !== (key ? dictRuntime.t(key) : customLabel)
        || okBtn.disabled !== (action === "blocked")
        || nodes.gateWhat.textContent !== "🔒 " + (action === "blocked" ? dictRuntime.t("workshop.gate.action_unallowed")
          : dictRuntime.t("workshop.gate.affects_world", { tool: "fixture-tool" }))
        || nodes.gateWhere.textContent !== dictRuntime.t("workshop.gate.where_context", { where: "fixture-place" })) {
        gateFailures.push({ locale, action, customLabel, okBtn, nodes });
      }
    }
    const banner = { style: {} };
    runInNewContext(`function refreshAntiGrift() {${degradedRenderer[1]}\n}; refreshAntiGrift();`, {
      window: { __cuarto: { antiGrift: () => ({ isDegraded: true,
        degraded: { intended_model: "fixture-requested", actual_model: "fixture-actual" } }) } },
      agBanner: banner, escapeHtml: String, ayuda: () => "[?]", logPush() {},
      _wt: (k, vars) => dictRuntime.t(k, vars), _L: (es, en) => locale === "en" ? en : es,
    });
    if (banner.style.display !== "block" || banner.innerHTML !== dictRuntime.t("workshop.status.degraded", {
      intended: "<b>fixture-requested</b>", actual: "<b>fixture-actual</b>",
    }) + "[?]") degradedFailures.push({ locale, banner });
  }
  check(!taskFailures.length, "preflight · estados reales del HUD de tareas localizados en ocho casos ES/EN", JSON.stringify(taskFailures));
  check(!gateFailures.length, "preflight · permiso real mantiene clave/label y respeta el texto runtime en seis casos ES/EN", JSON.stringify(gateFailures));
  check(!degradedFailures.length, "preflight · aviso real de modelo degradado conserva identificadores y traduce ES/EN", JSON.stringify(degradedFailures));

  // Component-owned root descriptions are not fixed Workshop labels. A stale
  // data-i18n-* on their host lets apply() overwrite newer model/state evidence.
  const ownedHostFailures = [];
  for (const id of ["cuartoBrainDock", "guideSemMount"]) {
    const tag = pixi.match(new RegExp(`<[^>]+id="${id}"[^>]*>`))?.[0];
    if (!tag || /data-i18n(?:-title|-aria)?=/.test(tag)) ownedHostFailures.push({ id, tag });
  }
  check(!ownedHostFailures.length, "preflight · hosts Brain y semáforo no retienen claves estáticas ajenas al renderer",
    JSON.stringify(ownedHostFailures));

  const badgeRenderer = semaforo.match(/export function pintarBadge\(el, res, opts\) \{([\s\S]*?)\n\}\n\n\/\/ §D/);
  const statesSource = semaforo.match(/export const ESTADOS = (\{[\s\S]*?\n\});/);
  const causesSource = semaforo.match(/export const CAUSAS = (\{[\s\S]*?\n\});/);
  const brainRenderer = brain.match(/  function render\(el, status, opts\) \{([\s\S]*?)\n  \}\n  function mount/);
  const hookRenderer = connectionHook.match(/function actualizarAccionInspector\(prim\) \{([\s\S]*?)\n\}/);
  if (!badgeRenderer || !statesSource || !causesSource || !brainRenderer || !hookRenderer)
    throw new Error("No pude extraer los renderers compartidos reales para probar su propiedad i18n.");
  const states = runInNewContext(`(${statesSource[1]})`), causes = runInNewContext(`(${causesSource[1]})`);
  const node = () => {
    const el = { attrs: {}, dataset: {}, className: "sem-mount", children: {},
      setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; },
      getAttribute(k) { return this.attrs[k] ?? null; },
      querySelector(s) { return s.startsWith(".sem-") ? null : this.children[s] ||= node(); } };
    Object.defineProperty(el, "title", { get() { return this.attrs.title || ""; },
      set(value) { this.attrs.title = value; } });
    return el;
  };
  const badgeFailures = [], brainFailures = [], hookFailures = [];
  for (const locale of ["es", "en"]) {
    activeLang = locale;
    for (const compact of [false, true]) {
      const el = node();
      for (const state of Object.keys(states)) {
        runInNewContext(`function pintarBadge(el,res,opts) {${badgeRenderer[1]}\n}; pintarBadge(el,res,opts);`, {
          el, res: { estado: state, causa: state === "roto" ? "sin_red" : null, ts: 999940 }, opts: { compacto: compact },
          window: { AlephI18n: dictRuntime }, ESTADOS: states, CAUSAS: causes, botonDe: () => null,
          _esc: String, _anotarParaCuandoVuelva() {}, horaDe: () => "fixture-time", haceRato: () => "hace 1 min",
          Date: { now: () => 1000000000 },
        });
        const sub = ({ probado: dictRuntime.t("workshop.badge.tested_ago", {
          when: dictRuntime.t("workshop.badge.ago", { amount: 1, unit: "min" }) }),
          detectado: dictRuntime.t("workshop.badge.untried"), parcial: dictRuntime.t("workshop.badge.partial"),
          roto: causes.sin_red[locale], no_configurado: dictRuntime.t("workshop.badge.configuration_missing"),
          premium: dictRuntime.t("workshop.badge.premium") })[state];
        const expected = states[state][locale] + " — " + sub;
        if (el.attrs["aria-label"] !== expected || (compact && el.title !== expected)
          || (!compact && !el.innerHTML.includes(states[state][locale]))) badgeFailures.push({ locale, compact, state, expected, el });
      }
    }
    for (const label of ["", "fixture-model", "Cognición incluida"]) {
      const el = node();
      runInNewContext(`function render(el,status,opts) {${brainRenderer[1]}\n}; render(el,status,{compact:true});`, {
        el, status: { label, id: "opus", action: { label: "fixture-action", href: "#" } },
        window: { AlephI18n: dictRuntime }, installCss() {}, stateClass: () => "", stateLabel: () => "", POWER: {}, t: (key) => dictRuntime.t(key),
      });
      const expected = label ? dictRuntime.t("brain.model_prefix") + dictRuntime.text(label) : dictRuntime.t("brain.unread");
      if (el.attrs["aria-label"] !== expected) brainFailures.push({ locale, label, expected, el });
    }
    const prim = node();
    prim.setAttribute("data-i18n", "workshop.action.view_connection");
    runInNewContext(`function actualizarAccionInspector(prim) {${hookRenderer[1]}\n}; actualizarAccionInspector(prim);`, {
      prim, esConexion: () => true, tr: (key) => dictRuntime.t(key),
    });
    if (prim.attrs["data-i18n"] !== "workshop.action.view_connection_external"
      || prim.textContent !== dictRuntime.t("workshop.action.view_connection_external")
      || prim.title !== dictRuntime.t("workshop.action.connection_destination")) hookFailures.push({ locale, prim });
    prim.setAttribute("data-i18n", "workshop.action.choose_model");
    prim.textContent = dictRuntime.t("workshop.action.choose_model");
    runInNewContext(`function actualizarAccionInspector(prim) {${hookRenderer[1]}\n}; actualizarAccionInspector(prim);`, {
      prim, esConexion: () => false, tr: (key) => dictRuntime.t(key),
    });
    if (prim.title || prim.attrs["data-i18n-title"]
      || prim.textContent !== dictRuntime.t("workshop.action.choose_model")) hookFailures.push({ locale, prim });
  }
  check(!badgeFailures.length, "preflight · semáforo real: 24 estados compactos/extendidos ES/EN sin título o ARIA obsoleto", JSON.stringify(badgeFailures));
  check(!brainFailures.length, "preflight · Brain real: ARIA preserva modelo actual o estado no leído en ES/EN", JSON.stringify(brainFailures));
  check(!hookFailures.length && connectionHook.includes('if (!esConexion()) return;'),
    "preflight · puente de conexión mantiene clave/acción/destino y limpia título al volver al Core en ES/EN", JSON.stringify(hookFailures));
}

await sourcePreflight();
if (failures.length) {
  console.log("\nROJO — preflight estático: " + failures.length + " FAIL");
  process.exit(1);
}
if (process.env.WORKSHOP_I18N_PREFLIGHT_ONLY === "1") {
  console.log("\nVERDE — preflight estático completo; QA del navegador omitida por solicitud.");
  process.exit(0);
}

const serverCode = "import http.server,sys; from functools import partial; s=http.server.ThreadingHTTPServer(('127.0.0.1',0),partial(http.server.SimpleHTTPRequestHandler,directory=sys.argv[1])); print(s.server_address[1],flush=True); s.serve_forever()";
const server = spawn("python3", ["-u", "-c", serverCode, DESIGN], { stdio: ["ignore", "pipe", "inherit"] });
const port = await new Promise((resolve, reject) => {
  let output = "";
  server.stdout.setEncoding("utf8");
  server.stdout.on("data", (chunk) => {
    output += chunk;
    const line = output.split(/\r?\n/, 1)[0].trim();
    if (/^\d+$/.test(line)) resolve(Number(line));
  });
  server.once("error", reject);
  server.once("exit", (code) => reject(new Error(`Workshop test server exited before bind (code ${code}): ${output}`)));
});
const base = `${BASE_PATH}:${port}`;

await mkdir(EVIDENCE, { recursive: true });
let browser;
try {
  const { chromium } = await import("playwright");
  browser = await chromium.launch(process.env.ALEPH_CHROMIUM_PATH
    ? { executablePath: process.env.ALEPH_CHROMIUM_PATH } : {});
} catch (error) {
  server.kill();
  console.error("BLOCKED — el preflight estático sí corrió, pero Chromium no pudo iniciar la QA visual:", error && error.message ? error.message : error);
  process.exit(2);
}
const pageErrors = [];
const accountPreferencesSeen = [];

async function newContext(lang = "es", storageState, accountLang = null, accountSaveStatus = 200) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, storageState });
  await context.addInitScript((initialLang) => {
    if (initialLang) localStorage.setItem("aleph-lang", initialLang);
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "locale-fixture", session_token: "fixture-token" }));
  }, lang);
  await context.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await context.route("**/v1/preferencias", (route) => {
    const method = route.request().method();
    const status = method === "PUT" ? accountSaveStatus : 200;
    accountPreferencesSeen.push({ method, url: route.request().url(), idioma: accountLang || null, status });
    return route.fulfill({ status, contentType: "application/json",
      body: JSON.stringify({ ajustes: accountLang ? { idioma: accountLang } : {} }) });
  });
  await context.route("**/v1/modelos/selector**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ modelos: [
    { picker_id: "opus", slug: "incluido.cognicion", label: "Cognición incluida", sub: "Incluido con Aleph", model: "anthropic/claude-opus", familia: "hosted", conectado: true, hay_llave: true, default: true },
    { picker_id: "openai-test", slug: "openai/gpt-test", label: "OpenAI GPT-4.1", sub: "API key required", model: "openai/gpt-test", familia: "api", conectado: false, hay_llave: false, default: false },
  ] }) }));
  return context;
}

async function waitForWorkshop(page, entry) {
  if (entry === "dc") {
    await page.waitForSelector('[data-i18n="workshop.goal.title"]', { timeout: 30000 });
    await page.waitForFunction(() => document.querySelector("#dc-root .sc-host"), null, { timeout: 30000 });
  } else {
    await page.waitForFunction(() => typeof window.__openInspector === "function" && window.__cuarto,
      null, { timeout: 30000 });
  }
}

async function waitForPixiInspector(page) {
  // openInspector() builds Options synchronously; this waits for the actual visible
  // panel instead of guessing how long a browser frame or model refresh will take.
  await page.locator('#inspector.open.expanded #d-opts.on .osec[data-osec^="mente|"] .osec-h')
    .waitFor({ state: "visible", timeout: 30000 });
}

async function logPixiSurfaceAudit(page, stage) {
  const audit = await page.evaluate(() => {
    const targets = [
      ["#ikind", "openInspector", "workshop.item.core"],
      ["#iname", "openInspector / service identity", null],
      ["#isub", "openInspector / agent identity", null],
      ["#iprimary", "openInspector", "workshop.action.choose_model"],
      ['#d-opts .osec[data-osec^="mente|"] .osec-h', "optsHTML / osec", "workshop.mind"],
      ["#mente-plan-body", "paintMentePlan", "workshop.plan.empty"],
      ["#mente-workers-body", "paintMenteWorkers", "workshop.agents.empty"],
      ['#d-opts .field:has([data-sw="nau"]) .k', "nauHTML / swField", "workshop.inspector.setting.agent_autonomy"],
      ['#d-opts [data-sw="pa"] [data-v="full"]', "paHTML / swField", "workshop.inspector.setting.steps.exhaustive"],
      ["#mfamConstruir .mfam-h", "static menu / wireMetaMenu", "workshop.nav.build"],
      ["#evToggle", "mountEvidence / AlephI18n.apply", null],
      ["#modoState", "sincronizarModo", null],
      ["#modoBtn", "sincronizarModo", null],
      ["#multiModeState", "refreshMultiMode", null],
      ["#cuartoBrainDock", "AlephBrain.render: brain.model_prefix + model / brain.unread", null],
      ["#guideSemMount", "Sem.pintarBadge: ESTADOS + workshop.badge.*", null],
      ["#status", "say / trWith", null],
      ["#listoTxt", "pintarListo", null],
    ];
    return { locale: AlephI18n.lang(), documentLang: document.documentElement.lang, title: document.title,
      nodes: targets.map(([selector, mutator, generatedKey]) => {
        const el = document.querySelector(selector), r = el?.getBoundingClientRect();
        const style = el && getComputedStyle(el);
        const attributes = el && Object.fromEntries([...el.attributes].filter((a) => a.name.startsWith("data-i18n"))
          .map((a) => [a.name, a.value]));
        return { selector, mutator, generatedKey, expectedFromGeneratedKey: generatedKey ? AlephI18n.t(generatedKey) : null,
          actualText: el?.textContent?.trim() ?? null, actualInnerText: el?.innerText ?? null,
          title: el?.getAttribute("title") ?? null, ariaLabel: el?.getAttribute("aria-label") ?? null, attributes,
          textTransform: style?.textTransform ?? null,
          visible: !!r?.width && !!r?.height && style.display !== "none" && style.visibility !== "hidden" };
      }) };
  });
  console.log(`PIXI SURFACE AUDIT ${stage}:`, JSON.stringify(audit));
}

async function keyedDrift(page) {
  return page.evaluate((translations) => {
    const I = window.AlephI18n;
    const mismatches = [];
    for (const el of document.querySelectorAll("[data-i18n]")) {
      const key = el.getAttribute("data-i18n"), expected = I.t(key);
      if (el.textContent.trim() !== expected) mismatches.push({ selector: el.id ? `#${el.id}` : `[data-i18n="${key}"]`,
        key, got: el.textContent.trim(), expected });
    }
    for (const [attr, dataAttr] of [["placeholder", "data-i18n-ph"], ["title", "data-i18n-title"], ["aria-label", "data-i18n-aria"]]) {
      for (const el of document.querySelectorAll(`[${dataAttr}]`)) {
        const key = el.getAttribute(dataAttr), expected = I.t(key);
        if (el.getAttribute(attr) !== expected) mismatches.push({ selector: el.id ? `#${el.id}` : `[${dataAttr}="${key}"]`,
          key, attr, got: el.getAttribute(attr), expected });
      }
    }
    return mismatches.map((m) => {
      const el = document.querySelector(m.selector);
      return { ...m, expectedKey: m.key, translations: { es: translations.es[m.key], en: translations.en[m.key] },
        actualDataI18n: el?.getAttribute("data-i18n"), actualDataI18nTitle: el?.getAttribute("data-i18n-title"),
        actualDataI18nAria: el?.getAttribute("data-i18n-aria"), actualTitle: el?.getAttribute("title"),
        locale: I.lang(), documentLang: document.documentElement.lang };
    });
  }, keyTranslations);
}

async function logLocaleState(page, label, accountPreference) {
  const state = await page.evaluate(() => {
    const visible = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect(), s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.display !== "none" && s.visibility !== "hidden";
    };
    const title = document.querySelector('[data-i18n="workshop.title"]');
    const goal = document.querySelector('[data-i18n="workshop.goal.title"]');
    const input = [...document.querySelectorAll('input[data-i18n-ph="workshop.model.key_placeholder"]')].find(visible);
    const keyPanel = input?.parentElement?.parentElement?.parentElement;
    const validation = [...document.querySelectorAll(".sc-host *")].find((el) => visible(el)
      && /(?:too short|demasiado corta|validating|validando|could not be validated|no se pudo validar)/i.test(el.textContent || ""));
    return {
      localStorageLanguage: localStorage.getItem("aleph-lang"),
      pendingLanguage: sessionStorage.getItem("aleph-lang-pending"),
      effectiveAlephI18nLocale: window.AlephI18n?.lang?.() || null,
      documentLang: document.documentElement.lang || null,
      documentTitle: document.title,
      renderedWorkshopTitle: title?.textContent?.trim() || null,
      renderedGoalChrome: goal?.textContent?.trim() || null,
      byokLabel: keyPanel?.innerText?.trim() || null,
      byokPlaceholder: input?.getAttribute("placeholder") || null,
      validationText: validation?.textContent?.trim() || null,
    };
  });
  console.log(`LOCALE ${label}:`, JSON.stringify({ ...state, accountPreference,
    latestAccountPreferenceResponse: accountPreferencesSeen.at(-1) || null }));
}

async function visibleByokPanel(page) {
  const input = page.locator('input[type="password"][data-i18n-ph="workshop.model.key_placeholder"]:visible');
  await input.waitFor({ state: "visible" });
  // input → row flex → credential panel → model-list item; every action/assertion below
  // stays attached to the exact visible BYOK model, never another hidden template row.
  return input.locator("xpath=../../..");
}

async function clickMyAgentsFromMenu(page, locale) {
  const before = await page.locator("#mineBtn").evaluate((el) => {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    const hiddenOrCollapsedAncestors = [];
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      const ps = getComputedStyle(parent);
      if (parent.hidden || parent.getAttribute("aria-hidden") === "true" || ps.display === "none"
        || ps.visibility === "hidden" || parent.classList.contains("closed")
        || parent.getAttribute("aria-expanded") === "false") {
        hiddenOrCollapsedAncestors.push({ tag: parent.tagName.toLowerCase(), id: parent.id || "",
          hidden: parent.hidden, ariaHidden: parent.getAttribute("aria-hidden"),
          display: ps.display, visibility: ps.visibility, opacity: ps.opacity,
          pointerEvents: ps.pointerEvents });
      }
    }
    const menu = el.closest('[role="menu"]');
    const opener = menu?.id ? document.querySelector(`[aria-controls="${menu.id}"]`) : null;
    const openerRect = opener?.getBoundingClientRect(), openerStyle = opener && getComputedStyle(opener);
    const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
    return {
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height,
        top: rect.top, right: rect.right, bottom: rect.bottom, left: rect.left },
      display: style.display, visibility: style.visibility, opacity: style.opacity,
      pointerEvents: style.pointerEvents, hiddenAttribute: el.hasAttribute("hidden"),
      ariaHidden: el.getAttribute("aria-hidden"),
      nearestHiddenOrCollapsedAncestor: hiddenOrCollapsedAncestors[0] || null,
      hiddenOrCollapsedAncestors,
      containingMenu: menu && { id: menu.id, hidden: menu.hidden,
        ariaHidden: menu.getAttribute("aria-hidden"), display: getComputedStyle(menu).display,
        isOpen: !menu.hidden && getComputedStyle(menu).display !== "none" },
      opener: opener && { id: opener.id, ariaExpanded: opener.getAttribute("aria-expanded"),
        display: openerStyle.display, visibility: openerStyle.visibility,
        visible: !!openerRect?.width && !!openerRect?.height && openerStyle.display !== "none"
          && openerStyle.visibility !== "hidden" },
      viewport: { width: innerWidth, height: innerHeight, centerX: x, centerY: y,
        centerInside: rect.width > 0 && rect.height > 0 && x >= 0 && y >= 0 && x < innerWidth && y < innerHeight },
      controlToOpenFirst: menu?.hidden ? opener?.id || null : null,
    };
  });
  console.log(`#mineBtn ${locale} before interaction:`, JSON.stringify(before));
  if (before.containingMenu?.hidden) {
    if (before.opener?.id !== "metaBtn" || !before.opener.visible)
      throw new Error(`El menú de Mis agentes está cerrado sin un control visible para abrirlo: ${JSON.stringify(before)}`);
    await page.locator("#metaBtn").click();
    await page.locator("#mineBtn").waitFor({ state: "visible" });
  }
  await page.locator("#mineBtn").click();
}

async function checkMyAgentsEmpty(page, locale) {
  const selector = "#mineOverlay.open .mineEmpty";
  const expected = locale === "ES" ? "Todavía no guardaste ningún agente." : "You have not saved any agents yet.";
  const snapshot = () => page.evaluate((target) => {
    const el = document.querySelector(target);
    return { selector: target, actualDomValue: el?.textContent?.trim() ?? null,
      outerHTML: el?.outerHTML ?? null, effectiveLocale: window.AlephI18n?.lang?.() ?? null,
      documentLang: document.documentElement.lang, dataI18n: el?.getAttribute("data-i18n") ?? null,
      canonicalEmpty: window.AlephI18n?.t?.("workshop.mine.empty") ?? null,
      canonicalLoading: window.AlephI18n?.t?.("workshop.mine.loading") ?? null };
  }, selector);
  await page.locator(selector).waitFor({ state: "visible" });
  const initial = await snapshot();
  console.log(`ASSERT Pixi My agents ${locale} initial:`, JSON.stringify({
    assertion: "empty-state text equals canonical locale copy", expected, ...initial,
    keyUsedByRenderer: initial.actualDomValue === initial.canonicalLoading ? "workshop.mine.loading" : "workshop.mine.empty",
    nodeOrigin: "created dynamically by mineBtn.onclick", rerenderedAfterLocaleChange: locale === "EN" }));
  // El mismo selector representa «Cargando…» durante el GET y el desenlace después.
  // Esperar a que salga de ese estado prueba el texto final sin una pausa arbitraria.
  await page.waitForFunction((target) => {
    const el = document.querySelector(target);
    return !!el && el.textContent.trim() !== window.AlephI18n.t("workshop.mine.loading");
  }, selector, { timeout: 30000 });
  const settled = await snapshot();
  console.log(`ASSERT Pixi My agents ${locale} settled:`, JSON.stringify({
    assertion: "empty-state text equals canonical locale copy", expected, ...settled,
    keyUsedByRenderer: "workshop.mine.empty", nodeOrigin: "created dynamically by mineBtn.onclick",
    rerenderedAfterLocaleChange: locale === "EN", classifiedAs: settled.actualDomValue === expected ? "harness timing" : "product or fixture text" }));
  check(settled.actualDomValue === expected,
    locale === "ES" ? "Pixi · estado vacío de Mis agentes en español" : "Pixi · estado vacío de My agents en inglés",
    JSON.stringify({ selector, expected, actual: settled.actualDomValue, locale: settled.effectiveLocale,
      documentLang: settled.documentLang, dataI18n: settled.dataI18n, key: "workshop.mine.empty" }));
}

async function switchLanguage(page, lang) {
  const nav = page.waitForNavigation({ waitUntil: "load", timeout: 15000 });
  await page.evaluate((next) => window.AlephI18n.setLang(next), lang);
  await nav;
}
async function assertPickerControlUnblocked(page, name) {
  const control = page.getByText(name, { exact: true }).first();
  await control.waitFor({ state: "visible" });
  const hit = await control.evaluate((el) => {
    const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    const top = document.elementFromPoint(x, y);
    return { x, y, blockedByRail: !!(top && top.closest("#aleph-riel")), top: top && `${top.tagName.toLowerCase()}#${top.id || ""}` };
  });
  if (hit.blockedByRail) throw new Error(`El riel tapa el control interactivo «${name}»: ${JSON.stringify(hit)}`);
}
async function clickRealAccordion(page, key, contentSelector) {
  const header = page.locator(`button:has([data-i18n="${key}"])`);
  const count = await header.count();
  if (count !== 1) throw new Error(`Acordeón ${key}: esperaba un botón real, encontré ${count}.`);
  const snapshot = async () => header.evaluate((el, selector) => {
    const r = el.getBoundingClientRect(), style = getComputedStyle(el);
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const top = cx >= 0 && cy >= 0 && cx < innerWidth && cy < innerHeight ? document.elementFromPoint(cx, cy) : null;
    const ancestors = [];
    let parent = el.parentElement;
    while (parent) {
      const ps = getComputedStyle(parent), pr = parent.getBoundingClientRect();
      if (parent.hidden || ps.display === "none" || ps.visibility === "hidden" || pr.width === 0 || pr.height === 0
        || parent.classList?.contains("closed") || parent.getAttribute("aria-expanded") === "false") {
        ancestors.push({ tag: parent.tagName.toLowerCase(), id: parent.id || "", className: String(parent.className || ""),
          hidden: parent.hidden, display: ps.display, visibility: ps.visibility,
          collapsed: parent.classList?.contains("closed") || parent.getAttribute("aria-expanded") === "false",
          condition: parent.tagName.toLowerCase() === "sc-if" ? parent.getAttribute("value") : null });
      }
      parent = parent.parentElement;
    }
    const content = document.querySelector(selector), cr = content && content.getBoundingClientRect();
    const contentStyle = content && getComputedStyle(content);
    const contentOpen = !!(content && contentStyle.display !== "none" && contentStyle.visibility !== "hidden"
      && cr.width > 0 && cr.height > 0);
    return {
      button: `${el.tagName.toLowerCase()}#${el.id || ""}`,
      rect: { x: r.x, y: r.y, top: r.top, right: r.right, bottom: r.bottom, left: r.left, width: r.width, height: r.height },
      computed: { display: style.display, visibility: style.visibility, pointerEvents: style.pointerEvents },
      viewport: { width: innerWidth, height: innerHeight },
      point: { x: cx, y: cy, outsideViewport: cx < 0 || cy < 0 || cx >= innerWidth || cy >= innerHeight,
        hit: top && `${top.tagName.toLowerCase()}#${top.id || ""}.${String(top.className || "").replace(/\s+/g, ".")}`,
        hitInsideHeader: !!top && el.contains(top) },
      parentHiddenOrCollapsed: ancestors,
      contentOpen,
      caret: el.querySelector("span:last-child")?.textContent.trim() || "",
    };
  }, contentSelector);
  let before = await snapshot();
  if (key === "workshop.parameters.title") console.log("Parameters accordion geometry before scroll:", JSON.stringify(before));
  // The section is conditional on having at least one equipped tool. A hidden `sc-if`
  // placeholder is not a user-interactive header and must not be clicked by the test.
  const hasToolsGate = before.parentHiddenOrCollapsed.some((p) => p.tag === "sc-if" && /hasTools/.test(p.condition || ""));
  if (hasToolsGate && before.parentHiddenOrCollapsed.some((p) => p.display === "none" || p.hidden)) {
    if (key === "workshop.parameters.title") console.log("Parameters accordion unavailable by hasTools condition; no visible control to click.");
    return "unavailable-no-tools";
  }
  if (before.contentOpen) return "already-open";
  // Playwright's normal click scrolls, but our own hit-test must do so first too; otherwise
  // elementFromPoint(center) is null for an off-screen accordion and falsely calls it blocked.
  await header.scrollIntoViewIfNeeded();
  const afterScroll = await snapshot();
  if (key === "workshop.parameters.title") console.log("Parameters accordion geometry after scroll:", JSON.stringify(afterScroll));
  if (afterScroll.parentHiddenOrCollapsed.length || afterScroll.rect.width === 0 || afterScroll.rect.height === 0)
    throw new Error(`Acordeón ${key} no está visible tras scroll normal: ${JSON.stringify(afterScroll)}`);
  if (!afterScroll.point.hitInsideHeader)
    throw new Error(`Acordeón ${key}: hit-test del control visible fue interceptado: ${JSON.stringify(afterScroll)}`);
  await header.click();
  await page.locator(contentSelector).waitFor({ state: "visible" });
  return "opened";
}
async function closeModelPicker(page) {
  const backdropHandle = await page.evaluateHandle(() => [...document.querySelectorAll(".sc-host div")].find((el) => {
    const style = getComputedStyle(el), rect = el.getBoundingClientRect();
    return style.position === "fixed" && style.zIndex === "40"
      && rect.width >= innerWidth - 1 && rect.height >= innerHeight - 1;
  }) || null);
  const backdrop = backdropHandle.asElement();
  if (!backdrop) {
    await backdropHandle.dispose();
    throw new Error("No encontré el backdrop visible del selector de modelos.");
  }
  // La navegación fija ocupa x=0..78 y queda sobre el backdrop en esa franja. El
  // usuario cierra haciendo clic en el backdrop fuera del diálogo; usamos su esquina
  // inferior derecha, que no pertenece ni al rail ni al picker. Sin force: si otro
  // control la tapa, esta aserción debe seguir detectándolo.
  const point = await backdrop.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const x = Math.max(90, r.width - 8), y = Math.max(8, r.height - 8);
    const hit = document.elementFromPoint(r.left + x, r.top + y);
    return { x, y, hitBackdrop: hit === el || el.contains(hit), hit: hit && `${hit.tagName.toLowerCase()}#${hit.id || ""}.${String(hit.className || "").replace(/\s+/g, ".")}` };
  });
  if (!point.hitBackdrop) throw new Error(`El backdrop está bloqueado en su esquina libre: ${JSON.stringify(point)}`);
  await backdrop.click({ position: { x: point.x, y: point.y } });
  await page.locator('[data-i18n="workshop.model.choose"]').waitFor({ state: "hidden" });
  await backdropHandle.dispose();
}

try {
  // ── DC entry: Home → El Cuarto; model picker/key input; nested accordions; locale reload. ──
  // Simula el intervalo real entre el PUT keepalive y su convergencia: durante el switch
  // ES→EN, el GET puede devolver todavía ES. El locale elegido en esta pestaña debe ganar.
  let context = await newContext("es", undefined, "es");
  let page = await context.newPage();
  page.on("pageerror", (e) => pageErrors.push(`DC: ${e}`));
  await page.goto(`${base}/Home.dc.html`, { waitUntil: "load" });
  const enter = page.locator('a[href="Cuarto.dc.html"]:visible').first();
  await enter.waitFor({ timeout: 30000 });
  await enter.click();
  await page.waitForURL(/Cuarto\.dc\.html/);
  await waitForWorkshop(page, "dc");
  await pause(250);
  check(await page.title() === "El Cuarto", "DC · navegación inicial desde Home usa el nombre canónico ES");
  check(await page.locator('[data-i18n="workshop.goal.title"]').innerText() === "¿Qué quieres que haga?",
    "DC · chrome inicial en español");
  check((await keyedDrift(page)).length === 0, "DC · todas las marcas i18n iniciales se resuelven", JSON.stringify(await keyedDrift(page)));

  await page.locator('[data-i18n="workshop.model"]').click();
  await page.locator('[data-i18n="workshop.model.choose"]').waitFor({ state: "visible" });
  await assertPickerControlUnblocked(page, "OpenAI GPT-4.1");
  await page.getByText("OpenAI GPT-4.1", { exact: true }).click();
  const esByok = await visibleByokPanel(page);
  check(await esByok.locator('input[type="password"]').getAttribute("placeholder") === "Pega tu API key…",
    "DC · modelo BYOK muestra el campo de llave en español");
  check(await esByok.locator('[data-i18n="workshop.model.save_test"]').innerText() === "Guardar y probar",
    "DC · acción de guardar/probar localizada");
  await esByok.locator('input[type="password"]').fill("short");
  await esByok.locator('[data-i18n="workshop.model.save_test"]').click();
  await esByok.getByText("Esa llave es demasiado corta.", { exact: true }).waitFor();
  check(true, "DC · error de validación local de llave se muestra en ES");
  await closeModelPicker(page);

  await page.locator('[data-i18n="workshop.sample.weekly_report"]').click();
  await pause(180);
  check(await page.locator('input[data-i18n-ph="workshop.name.placeholder"]').inputValue() === "Reportero",
    "DC · ejemplo integrado rellena el nombre español");
  check((await page.locator('textarea[data-i18n-ph="workshop.goal.placeholder"]').inputValue()).includes("números de la semana"),
    "DC · ejemplo integrado rellena su contenido español");
  const dcAccordions = [
    ["workshop.memory.title", '[data-i18n-ph="workshop.memory.fact_placeholder"]'],
    ["workshop.closets.title", '[data-i18n="workshop.closets.why"]'],
    ["workshop.parameters.title", '[data-i18n="workshop.parameters.autonomy"]'],
    ["workshop.team.title_card", '[data-i18n="workshop.team.add"]'],
    ["workshop.permissions.title", '[data-i18n="workshop.permissions.auto"]'],
  ];
  for (const [key, contentSelector] of dcAccordions) {
    const state = await clickRealAccordion(page, key, contentSelector);
    const label = {
      "workshop.memory.title": "memoria",
      "workshop.closets.title": "armarios",
      "workshop.parameters.title": "parámetros",
      "workshop.team.title_card": "equipo",
      "workshop.permissions.title": "permisos",
    }[key];
    const ok = key === "workshop.parameters.title"
      ? state === "opened" || state === "already-open" || state === "unavailable-no-tools"
      : state === "opened" || state === "already-open";
    check(ok, `DC ES · acordeón ${label} ${state === "unavailable-no-tools" ? "sin tools (condición real)" : "abierto"}`, state);
  }
  await pause(200);
  check((await keyedDrift(page)).length === 0, "DC · textos montados después del primer render siguen localizados en ES", JSON.stringify(await keyedDrift(page)));
  await page.screenshot({ path: join(EVIDENCE, "workshop-dc-es.png"), fullPage: true });

  await switchLanguage(page, "en");
  await waitForWorkshop(page, "dc");
  await pause(250);
  await logLocaleState(page, "DC ES→EN after reload, before opening BYOK", "ES (fixture keeps previous account preference)");
  check(await page.evaluate(() => sessionStorage.getItem("aleph-lang-pending") === "en" &&
    localStorage.getItem("aleph-lang") === "en" && AlephI18n.lang() === "en" &&
    document.documentElement.lang === "en") && await page.title() === "The Workshop",
    "DC · selección explícita EN gana al GET ES viejo en pending, caché, locale efectivo y documento");
  check(await page.title() === "The Workshop", "DC · cambio ES→EN recarga con el nombre canónico");
  check(await page.locator("html").getAttribute("lang") === "en", "DC · document lang pasa a EN junto con el contenido");
  check(await page.locator('[data-i18n="workshop.goal.title"]').innerText() === "What would you like it to do?",
    "DC · chrome inicial EN después del cambio");
  check((await keyedDrift(page)).length === 0, "DC · todas las marcas estáticas y async resueltas en EN", JSON.stringify(await keyedDrift(page)));
  await page.locator('[data-i18n="workshop.model"]').click();
  await page.locator('[data-i18n="workshop.model.choose"]').waitFor({ state: "visible" });
  await assertPickerControlUnblocked(page, "OpenAI GPT-4.1");
  await page.getByText("OpenAI GPT-4.1", { exact: true }).click();
  const enByok = await visibleByokPanel(page);
  await logLocaleState(page, "DC ES→EN BYOK opened", "ES (fixture keeps previous account preference)");
  check(await enByok.locator('input[type="password"]').getAttribute("placeholder") === "Paste your API key…",
    "DC · el campo de llave cambia a EN", JSON.stringify(await enByok.locator('input[type="password"]').evaluate((el) => ({ placeholder: el.placeholder, label: el.parentElement?.parentElement?.parentElement?.innerText }))));
  await enByok.locator('input[type="password"]').fill("short");
  await enByok.locator('[data-i18n="workshop.model.save_test"]').click();
  await pause(50);
  await logLocaleState(page, "DC ES→EN key validation", "ES (fixture keeps previous account preference)");
  await enByok.getByText("That key is too short.", { exact: true }).waitFor();
  check(true, "DC · error de validación local de llave se muestra en EN");
  await closeModelPicker(page);
  await page.locator('[data-i18n="workshop.sample.weekly_report"]').click();
  await pause(160);
  check(await page.locator('input[data-i18n-ph="workshop.name.placeholder"]').inputValue() === "Reporter",
    "DC · ejemplo integrado rellena el nombre EN");
  check((await page.locator('textarea[data-i18n-ph="workshop.goal.placeholder"]').inputValue()).startsWith("Gather the week’s numbers"),
    "DC · ejemplo integrado rellena su contenido EN");
  for (const [key, contentSelector] of dcAccordions) {
    const state = await clickRealAccordion(page, key, contentSelector);
    const label = {
      "workshop.memory.title": "memory",
      "workshop.closets.title": "cabinets",
      "workshop.parameters.title": "parameters",
      "workshop.team.title_card": "team",
      "workshop.permissions.title": "permissions",
    }[key];
    const ok = key === "workshop.parameters.title"
      ? state === "opened" || state === "already-open" || state === "unavailable-no-tools"
      : state === "opened" || state === "already-open";
    check(ok, `DC EN · ${label} accordion ${state === "unavailable-no-tools" ? "unavailable without tools" : "opened"}`, state);
  }
  await pause(180);
  check((await keyedDrift(page)).length === 0, "DC · acordeones e inputs siguen en EN tras interactuar", JSON.stringify(await keyedDrift(page)));
  await page.screenshot({ path: join(EVIDENCE, "workshop-dc-en.png"), fullPage: true });

  // Navigation to the use room and back must keep the same language; then a fresh context
  // restored from persisted browser storage simulates closing/reopening the desktop app.
  const salaLink = page.locator('[data-i18n="workshop.start_using"]');
  if (await salaLink.count()) {
    await salaLink.click();
    await page.waitForURL(/sala-v2\/sala-v2\.html/);
    await page.goBack({ waitUntil: "load" });
    await waitForWorkshop(page, "dc");
  } else {
    await page.goto(`${base}/sala-v2/sala-v2.html`, { waitUntil: "load" });
    await page.goto(`${base}/Cuarto.dc.html`, { waitUntil: "load" });
    await waitForWorkshop(page, "dc");
  }
  check(await page.evaluate(() => AlephI18n.lang()) === "en" && await page.title() === "The Workshop",
    "DC · navegación a La Sala y vuelta conserva EN");
  await page.reload({ waitUntil: "load" });
  await waitForWorkshop(page, "dc");
  check(await page.evaluate(() => AlephI18n.lang()) === "en", "DC · recarga dentro de El Cuarto conserva idioma");
  const saved = await context.storageState();
  await context.close();
  context = await newContext(null, saved, "en");
  page = await context.newPage();
  page.on("pageerror", (e) => pageErrors.push(`DC restart: ${e}`));
  await page.goto(`${base}/Cuarto.dc.html`, { waitUntil: "load" });
  await waitForWorkshop(page, "dc");
  check(await page.evaluate(() => AlephI18n.lang()) === "en" && await page.title() === "The Workshop",
    "DC · contexto nuevo restaura EN persistido (reinicio simulado)");
  await context.close();

  context = await newContext("es", undefined, "en");
  page = await context.newPage();
  // La hidratación de la cuenta cambia ES→EN en el primer documento y después lo
  // recarga. Esperar sólo lang/título puede resolver antes de ese reload.
  let dcNavigations = 0;
  const hydratedDcNavigation = page.waitForEvent("framenavigated", {
    predicate: (frame) => {
      if (frame !== page.mainFrame() || new URL(frame.url()).pathname !== "/Cuarto.dc.html") return false;
      return ++dcNavigations === 2;
    },
    timeout: 30000,
  });
  await page.goto(`${base}/Cuarto.dc.html`, { waitUntil: "load" });
  await hydratedDcNavigation;
  await page.waitForURL(`${base}/Cuarto.dc.html`, { waitUntil: "load" });
  await waitForWorkshop(page, "dc");
  await page.waitForFunction(() => window.AlephI18n && AlephI18n.lang() === "en" &&
    document.title === "The Workshop", null, { timeout: 30000 });
  await logLocaleState(page, "DC initial EN via account hydration", "EN");
  check(await page.locator("html").getAttribute("lang") === "en" &&
    await page.locator('[data-i18n="workshop.goal.title"]').innerText() === "What would you like it to do?",
    "DC · preferencia inicial EN hidrata también chrome y lang del documento");
  check(true, "DC · la preferencia de idioma de la cuenta hidrata y reemplaza la caché local");
  await context.close();

  // Un rechazo del write-through no puede revertir la selección local y tampoco debe
  // quedar oculto. El GET sigue devolviendo ES para reproducir cuenta desactualizada.
  context = await newContext("es", undefined, "es", 503);
  page = await context.newPage();
  let languageSaveWarning = null;
  page.on("dialog", async (dialog) => { languageSaveWarning = dialog.message(); await dialog.accept(); });
  await page.goto(`${base}/Cuarto.dc.html`, { waitUntil: "load" });
  await waitForWorkshop(page, "dc");
  await switchLanguage(page, "en");
  await waitForWorkshop(page, "dc");
  await logLocaleState(page, "DC account PUT fails after explicit EN", "ES (stale account preference; PUT 503)");
  check(languageSaveWarning === "The language was saved on this device, but not to your account. It will stay active here; choose it again when you are back online to sync it.",
    "DC · un fallo de guardado de cuenta se informa explícitamente", String(languageSaveWarning));
  check(await page.evaluate(() => localStorage.getItem("aleph-lang") === "en" &&
    AlephI18n.lang() === "en" && document.documentElement.lang === "en") && await page.title() === "The Workshop",
    "DC · un PUT fallido conserva el idioma explícito en esta pestaña pese al GET ES antiguo");
  await context.close();

  // ── Pixi entry: keyed toolbar + inspector's nested execution/memory sections. ──
  context = await newContext("es");
  page = await context.newPage({ viewport: { width: 1440, height: 900 } });
  page.on("pageerror", (e) => pageErrors.push(`Pixi ES: ${e}`));
  await page.goto(`${base}/cuarto/cuarto.pixi.html`, { waitUntil: "load" });
  await waitForWorkshop(page, "pixi");
  await page.evaluate(() => window.__openInspector(window.__cuarto.nucleoData()));
  await waitForPixiInspector(page);
  const esMind = page.locator('#d-opts .osec[data-osec^="mente|"]');
  if (await esMind.locator(".osec-h").getAttribute("aria-expanded") === "false") await esMind.locator(".osec-h").click();
  const esBehavior = page.locator('#d-opts .osec[data-osec^="beh|"]');
  if (await esBehavior.count() !== 1) throw new Error("El Núcleo ES debe mostrar una única sección Comportamiento.");
  if (await esBehavior.locator(".osec-h").getAttribute("aria-expanded") === "false") await esBehavior.locator(".osec-h").click();
  await esBehavior.locator(".osec-b").waitFor({ state: "visible" });
  await logPixiSurfaceAudit(page, "ES inspector empty");
  const esPixiText = await page.locator("#d-opts").innerText();
  check((await page.title()).startsWith("El Cuarto") && /LA MENTE · EJECUCIÓN/.test(esPixiText),
    "Pixi · título y panel de ejecución en español canónico");
  check(/No hay agentes auxiliares activos/.test(esPixiText) && /Plan de ejecución activo/.test(esPixiText),
    "Pixi · estado vacío y nombre del plan en español");
  check(/Autonomía del agente/.test(esPixiText) && /Exhaustivo/.test(esPixiText),
    "Pixi · ajustes de ejecución usan términos españoles canónicos");
  check(await page.locator("#ikind").innerText() === "NÚCLEO" &&
    await page.locator("#iprimary").innerText() === "Elegir modelo",
    "Pixi · inspector del Núcleo conserva su tipo y acción reales en ES");
  const modoBefore = await page.locator("#modoBtn").evaluate((el) => {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    const ancestors = [];
    let parent = el.parentElement;
    while (parent) {
      const ps = getComputedStyle(parent), pr = parent.getBoundingClientRect();
      if (parent.hidden || parent.getAttribute("aria-hidden") === "true" || ps.display === "none"
        || ps.visibility === "hidden" || parent.classList.contains("closed")
        || parent.getAttribute("aria-expanded") === "false") {
        ancestors.push({ tag: parent.tagName.toLowerCase(), id: parent.id || "",
          hidden: parent.hidden, ariaHidden: parent.getAttribute("aria-hidden"),
          display: ps.display, visibility: ps.visibility, opacity: ps.opacity,
          pointerEvents: ps.pointerEvents, rect: { x: pr.x, y: pr.y, width: pr.width, height: pr.height } });
      }
      parent = parent.parentElement;
    }
    const cam = document.querySelector("#cam"), body = document.querySelector("#camBody");
    const tab = el.closest('[role="tabpanel"]');
    const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
    const hit = rect.width && rect.height && x >= 0 && y >= 0 && x < innerWidth && y < innerHeight
      ? document.elementFromPoint(x, y) : null;
    return {
      rect: { x: rect.x, y: rect.y, top: rect.top, right: rect.right, bottom: rect.bottom,
        left: rect.left, width: rect.width, height: rect.height },
      display: style.display, visibility: style.visibility, opacity: style.opacity,
      pointerEvents: style.pointerEvents, hiddenAttribute: el.hasAttribute("hidden"),
      ariaHidden: el.getAttribute("aria-hidden"), nearestHiddenOrCollapsedAncestor: ancestors[0] || null,
      hiddenOrCollapsedAncestors: ancestors,
      containingPanel: { id: "camBody", hidden: body?.hidden ?? null,
        camDataOpen: cam?.dataset.open ?? null, isOpen: !!body && !body.hidden && cam?.dataset.open === "1" },
      containingTab: tab && { id: tab.id || "", hidden: tab.hidden,
        ariaHidden: tab.getAttribute("aria-hidden"), display: getComputedStyle(tab).display },
      viewport: { width: innerWidth, height: innerHeight },
      viewportPosition: { centerX: x, centerY: y,
        inside: rect.width > 0 && rect.height > 0 && x >= 0 && y >= 0 && x < innerWidth && y < innerHeight },
      hit: hit && `${hit.tagName.toLowerCase()}#${hit.id || ""}`,
      controlToOpenFirst: body?.hidden ? "#camToggle opens the intentionally collapsed #camBody" : null,
    };
  });
  console.log("#modoBtn before interaction:", JSON.stringify(modoBefore));
  if (modoBefore.containingPanel.hidden) {
    await page.locator("#camToggle").click();
    await page.locator("#modoBtn").waitFor({ state: "visible" });
  }
  await page.locator("#modoBtn").click();
  check(await page.locator("#modoState").innerText() === "Trabajo", "Pixi · el estado de vista se localiza al activar Trabajo");
  await page.locator("#modoBtn").click();
  await clickMyAgentsFromMenu(page, "ES");
  await checkMyAgentsEmpty(page, "ES");
  await page.locator("#mineClose").click();
  await page.locator("#metaBtn").click();
  await page.locator("#metaMenu").waitFor({ state: "visible" });
  await logPixiSurfaceAudit(page, "ES menu after view changes");
  const esMenuText = await page.locator("#metaMenu").innerText(), esMarkedDrift = await keyedDrift(page);
  const esMenuState = await page.evaluate(() => {
    const menu = document.querySelector("#metaMenu"), build = document.querySelector("#mfamConstruir .mfam-h");
    const marked = ["status", "listoTxt", "ikind", "iprimary", "modoState", "modoBtn", "saveBtn", "gateOk"].map((id) => {
      const el = document.getElementById(id), attribute = id === "modoBtn" ? "data-i18n-title" : "data-i18n";
      const key = el?.getAttribute(attribute);
      return { selector: `#${id}`, actualDomValue: id === "modoBtn" ? el?.title : el?.textContent?.trim() ?? null,
        attribute, key: key ?? null, expectedFromKey: key ? AlephI18n.t(key) : null,
        nodeOrigin: ({ status: "say / trWith", listoTxt: "pintarListo", ikind: "openInspector", iprimary: "openInspector",
          modoState: "sincronizarModo", modoBtn: "sincronizarModo", saveBtn: "guardarAgente", gateOk: "resolveGates.show" })[id] };
    });
    return { effectiveLocale: AlephI18n.lang(), documentLang: document.documentElement.lang,
      menuOpen: !menu.hidden, menuText: menu.innerText, buildSelector: "#mfamConstruir .mfam-h",
      buildActual: build?.textContent?.trim() ?? null, buildKey: build?.getAttribute("data-i18n") ?? null,
      buildExpectedFromKey: AlephI18n.t("workshop.nav.build"), marked };
  });
  console.log("ASSERT Pixi ES menu and inspector:", JSON.stringify({
    assertion: "menu includes Construir and all marked nodes match their i18n keys",
    expected: { buildText: "Construir", markedDrift: [] }, actual: esMenuState,
    selector: "#metaMenu + [data-i18n]", staticMenu: true,
    inspectorRerenderedAfterLocaleChange: false, mismatches: esMarkedDrift,
    classifiedAs: esMenuText.includes("Construir") && esMarkedDrift.length ? "product dynamic key mismatch" : "inspect menu text/state" }));
  check(esMenuState.buildActual === esMenuState.buildExpectedFromKey,
    "Pixi · menú superior usa la clave Construir en ES",
    JSON.stringify(esMenuState));
  check(esMarkedDrift.length === 0,
    "Pixi · etiquetas y títulos dinámicos corresponden a sus claves en ES",
    JSON.stringify({ expected: { buildText: "Construir", markedDrift: [] },
      actual: { buildText: esMenuState.buildActual, menuText: esMenuText, markedDrift: esMarkedDrift },
      locale: esMenuState.effectiveLocale, documentLang: esMenuState.documentLang }));
  await page.locator("#metaBtn").click();
  await page.evaluate(() => {
    window.__cuartoApplyFrontierEvent("plan_declared", { steps: [{ n: 2, paso: "leer fuentes", decompose: { n: 3, perfil: "economico" } }], turn: 4 }, () => null);
    window.__cuartoApplyFrontierEvent("sub_agent_started", { ephemeral: true, worker_id: "locale-es", worker_kind: "lectores", routed: "economico", step_n: 2, task: "comparar tres fuentes", turn: 4 }, () => null);
    window.__cuartoApplyFrontierEvent("sub_agent_finished", { ephemeral: true, worker_id: "locale-es", status: "ok", child_ok: true, model_final: "fixture-model", turn: 4 }, () => null);
  });
  const activeEs = await page.locator("#d-opts").innerText();
  check(/3 agentes auxiliares/.test(activeEs) && /lector/.test(activeEs) && /fixture-model/.test(activeEs),
    "Pixi · plan y agente auxiliar activo se renderizan desde eventos reales de UI");
  await page.screenshot({ path: join(EVIDENCE, "workshop-pixi-es.png"), fullPage: true });

  await switchLanguage(page, "en");
  await waitForWorkshop(page, "pixi");
  page.on("pageerror", (e) => pageErrors.push(`Pixi EN: ${e}`));
  await page.evaluate(() => window.__openInspector(window.__cuarto.nucleoData()));
  await waitForPixiInspector(page);
  const enMind = page.locator('#d-opts .osec[data-osec^="mente|"]');
  if (await enMind.locator(".osec-h").getAttribute("aria-expanded") === "false") await enMind.locator(".osec-h").click();
  const emptyEn = await page.locator("#d-opts").innerText();
  check((await page.title()).startsWith("The Workshop") && /THE MIND · EXECUTION/.test(emptyEn),
    "Pixi · cambio ES→EN traduce título y Mente");
  check(/No active auxiliary agents/.test(emptyEn) && /Active execution plan/.test(emptyEn),
    "Pixi · estados vacíos EN usan el vocabulario acordado");
  const enBehavior = page.locator('#d-opts .osec[data-osec^="beh|"]');
  if (await enBehavior.count() !== 1) throw new Error("El Núcleo EN debe mostrar una única sección Behavior.");
  if (await enBehavior.locator(".osec-h").getAttribute("aria-expanded") === "false") await enBehavior.locator(".osec-h").click();
  await enBehavior.locator(".osec-b").waitFor({ state: "visible" });
  await logPixiSurfaceAudit(page, "EN inspector empty");
  check(/Agent autonomy/.test(await page.locator("#d-opts").innerText()) && /Thorough/.test(await page.locator("#d-opts").innerText()),
    "Pixi · ajustes de ejecución usan términos ingleses");
  check(await page.locator("#ikind").innerText() === "CORE" &&
    await page.locator("#iprimary").innerText() === "Choose model",
    "Pixi · inspector del Core conserva su tipo y acción reales en EN");
  check((await keyedDrift(page)).length === 0, "Pixi · etiquetas/títulos/ARIA marcados se resuelven en EN", JSON.stringify(await keyedDrift(page)));
  await clickMyAgentsFromMenu(page, "EN");
  await checkMyAgentsEmpty(page, "EN");
  await page.locator("#mineClose").click();
  if (await page.locator("#camBody").isHidden()) await page.locator("#camToggle").click();
  await page.locator("#modoBtn").waitFor({ state: "visible" });
  await page.locator("#modoBtn").click();
  check(await page.locator("#modoState").innerText() === "Work", "Pixi · el estado de vista se localiza al activar Work");
  await page.locator("#modoBtn").click();
  await page.locator("#metaBtn").click();
  await page.locator("#metaMenu").waitFor({ state: "visible" });
  await logPixiSurfaceAudit(page, "EN menu after view changes");
  const buildEN = page.locator('#mfamConstruir [data-i18n="workshop.nav.build"]');
  await buildEN.waitFor({ state: "visible" });
  const buildStateEN = await buildEN.evaluate((el, translations) => ({
    selector: '#mfamConstruir [data-i18n="workshop.nav.build"]', actualText: el.textContent.trim(),
    actualInnerText: el.innerText, actualTitle: el.title, actualDataI18n: el.getAttribute("data-i18n"),
    actualDataI18nTitle: el.getAttribute("data-i18n-title"), expectedKey: "workshop.nav.build",
    expected: AlephI18n.t("workshop.nav.build"), translations,
    locale: AlephI18n.lang(), documentLang: document.documentElement.lang,
    textTransform: getComputedStyle(el).textTransform,
  }), { es: keyTranslations.es["workshop.nav.build"], en: keyTranslations.en["workshop.nav.build"] });
  console.log("PIXI BUILD KEY EN:", JSON.stringify(buildStateEN));
  // innerText includes CSS uppercase presentation (BUILD), not the key's semantic copy (Build).
  check(buildStateEN.actualText === buildStateEN.expected,
    "Pixi · menú superior usa la clave Build en EN después de interactuar", JSON.stringify(buildStateEN));
  const enAfterInteractionDrift = await keyedDrift(page);
  check(enAfterInteractionDrift.length === 0,
    "Pixi · claves dinámicas permanecen alineadas en EN después de cambiar vista y abrir menús",
    JSON.stringify(enAfterInteractionDrift));
  await page.locator("#metaBtn").click();
  await page.evaluate(() => {
    window.__cuartoApplyFrontierEvent("plan_declared", { steps: [{ n: 2, paso: "read sources", decompose: { n: 3, perfil: "economico" } }], turn: 5 }, () => null);
    window.__cuartoApplyFrontierEvent("sub_agent_started", { ephemeral: true, worker_id: "locale-en", worker_kind: "guion", routed: "economico", step_n: 2, task: "compare three sources", turn: 5 }, () => null);
    window.__cuartoApplyFrontierEvent("sub_agent_finished", { ephemeral: true, worker_id: "locale-en", status: "ok", child_ok: true, model_final: "fixture-model", turn: 5 }, () => null);
  });
  const activeEn = await page.locator("#d-opts").innerText();
  check(/3 auxiliary agents/.test(activeEn) && /script/.test(activeEn) && /fixture-model/.test(activeEn),
    "Pixi · agente y plan activos permanecen en inglés");
  check(!/Agentes auxiliares|agentes auxiliares|La Mente|Plan vivo|Cerebro de los workers/.test(activeEn),
    "Pixi · no filtra copy español en estado dinámico");
  await page.screenshot({ path: join(EVIDENCE, "workshop-pixi-en.png"), fullPage: true });
  await page.reload({ waitUntil: "load" });
  await waitForWorkshop(page, "pixi");
  check(await page.evaluate(() => AlephI18n.lang()) === "en", "Pixi · recarga dentro de El Cuarto conserva EN");
  await context.close();

  context = await newContext("es", undefined, "en");
  page = await context.newPage();
  page.on("pageerror", (e) => pageErrors.push(`Pixi account hydration: ${e}`));
  let pixiNavigations = 0;
  const hydratedPixiNavigation = page.waitForEvent("framenavigated", {
    predicate: (frame) => {
      if (frame !== page.mainFrame() || new URL(frame.url()).pathname !== "/cuarto/cuarto.pixi.html") return false;
      return ++pixiNavigations === 2;
    }, timeout: 30000,
  });
  await page.goto(`${base}/cuarto/cuarto.pixi.html`, { waitUntil: "load" });
  await hydratedPixiNavigation;
  await page.waitForURL(`${base}/cuarto/cuarto.pixi.html`, { waitUntil: "load" });
  await waitForWorkshop(page, "pixi");
  await page.waitForFunction(() => window.AlephI18n && AlephI18n.lang() === "en" &&
    document.title.startsWith("The Workshop"), null, { timeout: 30000 });
  check(true, "Pixi · la preferencia de idioma de la cuenta hidrata y reemplaza la caché local");
  check(pageErrors.length === 0, "ambas entradas · sin errores JavaScript", pageErrors.slice(0, 3).join(" | "));
  await context.close();
} catch (error) {
  failures.push("harness completó el recorrido");
  console.error("  FAIL  harness completó el recorrido —", error && (error.stack || error));
} finally {
  if (browser) await browser.close();
  server.kill();
}

console.log(`\n${failures.length ? "ROJO" : "VERDE"} — ${passes} PASS · ${failures.length} FAIL`);
if (failures.length) failures.forEach((name) => console.log(`  ✗ ${name}`));
process.exit(failures.length ? 1 : 0);
