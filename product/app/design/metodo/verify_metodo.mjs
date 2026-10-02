/* MÉTODO · verificación VIVA de la pantalla (probado, no razonado) — patrón verify_panel_orden6.
 *
 * Sin backend: /v1/** stubbeado + sesión inyectada. Secciones por pieza (cada una
 * se activa cuando su módulo existe en el árbol — el verify crece con la build):
 *   A · SHELL + BIBLIOTECA: lista con conteos, hero, nav con "Métodos", EN, 0 errores JS.
 *   B · EDITOR Simple/Pro (metodo.editor.js): pasos, reorder, checkpoint, fases, Pro, JSON.
 *   C · CAPTURA "Traer mi proceso" + EDITAR CONVERSANDO (diff aceptar/rechazar).
 *   D · GRAFO Obsidian vivo (metodo.graph.js): topología núcleo-céntrica + estados por telemetría.
 *
 * Puerto :8177.   Run: node verify_metodo.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = fileURLToPath(new URL("..", import.meta.url));
const PORT = 8177;
const PAGE = `http://localhost:${PORT}/metodo/metodo.html`;

const HAS_EDITOR = existsSync(HERE + "metodo.editor.js");
const HAS_GRAPH = existsSync(HERE + "metodo.graph.js");

const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${(!c && extra) ? "  · " + extra : ""}`); if (!c) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* métodos stub — contra el schema publicado (ORDEN_METODO §2) */
const M1 = { id: "m-earnings", name: "Cierre de earnings", steps: [
  { id: "s1", text: "Bajar el 10-Q", phase: "Recolectar", checkpoint: false, executor: "sec_edgar", evidence_hint: null, timeout: null, retries: 3 },
  { id: "s2", text: "Comparar márgenes YoY", phase: "Analizar", checkpoint: false, executor: null, evidence_hint: null, timeout: null, retries: 3 },
  { id: "s3", text: "Enviar el resumen", phase: "Entregar", checkpoint: true, executor: "gmail", evidence_hint: null, timeout: null, retries: 3 },
] };
const M2 = { id: "m-simple", name: "Chequeo semanal", steps: [
  { id: "t1", text: "Revisar los números", phase: "", checkpoint: false, executor: null, evidence_hint: null, timeout: null, retries: 3 },
] };

async function newPage(browser, lang) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("dialog", (d) => d.accept());
  await page.addInitScript((l) => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u-1", session_token: "tok-1", email: "x@y.z" }));
    if (l) localStorage.setItem("aleph-lang", l);
  }, lang || "");
  const calls = [];
  await page.route("**/v1/**", (r) => { calls.push(r.request().method() + " " + new URL(r.request().url()).pathname); r.fulfill({ status: 200, contentType: "application/json", body: "{}" }); });
  await page.route("**/v1/methods", (r) => {
    const m = r.request().method();
    calls.push(m + " /v1/methods" + (r.request().postData() ? " " + r.request().postData() : ""));
    if (m === "POST") { let b = {}; try { b = JSON.parse(r.request().postData() || "{}"); } catch (e) {}
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(Object.assign({ id: "m-nuevo" }, b)) }); }
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ methods: [M1, M2] }) });
  });
  await page.route("**/v1/methods/m-earnings", (r) => {
    const m = r.request().method();
    calls.push(m + " /v1/methods/m-earnings" + (m === "PUT" ? " " + (r.request().postData() || "") : ""));
    if (m === "PUT") { let b = {}; try { b = JSON.parse(r.request().postData() || "{}"); } catch (e) {}
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(b) }); }
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(M1) });
  });
  return { page, errors, calls };
}

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);
const browser = await chromium.launch();
try {
  /* ══ A · SHELL + BIBLIOTECA (ES) ══════════════════════════════════════ */
  {
    const { page, errors } = await newPage(browser);
    await page.goto(PAGE, { waitUntil: "load" });
    await page.waitForFunction(() => window.__metodo && window.__metodo.state.methods.length === 2, null, { timeout: 9000 });

    const shell = await page.evaluate(() => {
      const cards = [...document.querySelectorAll(".met-card")].map((c) => ({
        nm: c.querySelector(".nm").textContent, meta: c.querySelector(".meta").textContent,
        hasGrafo: !!c.querySelector('[data-act="grafo"]'), hasDel: !!c.querySelector('[data-act="del"]') }));
      return { cards, hero: !document.getElementById("metHero").hidden,
        title: document.querySelector(".met-side-h h1").textContent.trim(),
        nuevo: !!document.getElementById("metNuevo"), traer: !!document.getElementById("metTraer") };
    });
    ok(shell.cards.length === 2, "A · la biblioteca lista los métodos", JSON.stringify(shell.cards));
    ok(/Cierre de earnings/.test(shell.cards[0].nm) && /3 fases/.test(shell.cards[0].meta) && /3 pasos/.test(shell.cards[0].meta), "A · conteo de fases/pasos del schema real", shell.cards[0].meta);
    ok(/1 checkpoints/.test(shell.cards[0].meta), "A · badge de checkpoints cuando hay", shell.cards[0].meta);
    ok(shell.hero && /Método/.test(shell.title), "A · hero + título de la pantalla");
    ok(shell.cards[0].hasGrafo && shell.cards[0].hasDel, "A · acciones por card (grafo/borrar)");

    const nav = await page.evaluate(() => {
      const links = [...document.querySelectorAll("#aleph-topbar .aleph-tb-link")].map((a) => ({ t: a.textContent.trim(), cur: a.classList.contains("cur") }));
      return links.find((l) => /Métodos|Methods/.test(l.t)) || null;
    });
    ok(!!nav, "A · la barra de navegación tiene el destino Métodos", JSON.stringify(nav));
    ok(nav && nav.cur, "A · el destino Métodos marca current en esta pantalla");

    ok(errors.length === 0, "A · 0 errores JS (ES)", errors.slice(0, 3).join(" | "));
    await page.close();
  }

  /* ══ A-EN · bilingüe ══════════════════════════════════════════════════ */
  {
    const { page, errors } = await newPage(browser, "en");
    await page.goto(PAGE, { waitUntil: "load" });
    await page.waitForFunction(() => window.__metodo && window.__metodo.state.methods.length === 2, null, { timeout: 9000 });
    await sleep(500);   // capa TM + apply()
    const en = await page.evaluate(() => {
      const side = document.querySelector(".met-side").innerText;
      const hero = document.getElementById("metHero").innerText;
      const nav = [...document.querySelectorAll("#aleph-topbar .aleph-tb-link")].map((a) => a.textContent.trim()).join(" | ");
      return {
        method: /Method/.test(side), newm: /New method/.test(side), bring: /Bring my process/.test(side),
        phases: /phases/.test(side) && /steps/.test(side),
        heroEn: /A method is your process/.test(hero),
        navEn: /Methods/.test(nav),
        noRawEs: !/Nuevo método|Traer mi proceso|fases ·/.test(side) && !/Escribe los pasos/.test(hero),
      };
    });
    ok(en.method && en.newm && en.bring, "A-EN · chrome del sidebar traducido", JSON.stringify(en));
    ok(en.phases, "A-EN · conteos (phases/steps) traducidos");
    ok(en.heroEn, "A-EN · hero traducido");
    ok(en.navEn, "A-EN · nav 'Methods'");
    ok(en.noRawEs, "A-EN · sin español crudo residual");
    ok(errors.length === 0, "A-EN · 0 errores JS", errors.slice(0, 3).join(" | "));
    await page.close();
  }

  /* ══ B · EDITOR (cuando metodo.editor.js existe) ══════════════════════ */
  if (HAS_EDITOR) {
    const mod = await import("./verify_metodo_editor.part.mjs");
    await mod.run({ browser, newPage, PAGE, ok, sleep });
  } else {
    console.log("· B/C · editor aún no está en el árbol — sección omitida (pieza 2/3)");
  }

  /* ══ D · GRAFO (cuando metodo.graph.js existe) ════════════════════════ */
  if (HAS_GRAPH) {
    const mod = await import("./verify_metodo_grafo.part.mjs");
    await mod.run({ browser, newPage, PAGE, ok, sleep });
  } else {
    console.log("· D · grafo aún no está en el árbol — sección omitida (pieza 4)");
  }

  /* ══ E · CERTIFICACIÓN EN TOTAL del chrome (§8 — estándar de la casa) ═ */
  if (HAS_EDITOR && HAS_GRAPH) {
    // E1 · editor + chooser + captura + conversar en EN
    {
      const { page, errors } = await newPage(browser, "en");
      await page.goto(PAGE, { waitUntil: "load" });
      await page.waitForFunction(() => window.__metodo && window.__metodo.state.methods.length === 2, null, { timeout: 9000 });
      await page.evaluate(() => document.getElementById("metNuevo").click());
      await page.waitForSelector(".met-scrim .sk-opt", { timeout: 5000 });
      const sk = await page.evaluate(() => ({
        h: document.querySelector(".met-modal h3").textContent,
        opts: [...document.querySelectorAll(".sk-opt .lbl")].map((x) => x.textContent).join(" | "),
      }));
      ok(/How do we start\?/.test(sk.h), "E1 · chooser EN", sk.h);
      ok(/Research → Analyze → Produce → Deliver/.test(sk.opts) && /Blank/.test(sk.opts), "E1 · esqueletos de FORMA traducidos", sk.opts);
      await page.evaluate(() => document.querySelector('.sk-opt[data-sk="blank"]').click());
      await page.waitForFunction(() => window.__metodoEditor, null, { timeout: 5000 });
      const ed = await page.evaluate(() => ({
        save: document.querySelector("[data-ed-save]").textContent,
        namePh: document.querySelector(".ed-name").placeholder,
        addPh: document.querySelector("[data-add]").placeholder,
        fase1: document.querySelector(".ph").getAttribute("data-phase"),
        ckTitle: "", // sin pasos aún
      }));
      ok(ed.save === "Save" && /Method name/.test(ed.namePh), "E1 · header del editor EN", JSON.stringify(ed));
      ok(/type a step/.test(ed.addPh), "E1 · placeholder de paso EN");
      ok(ed.fase1 === "First phase", "E1 · fase inicial del esqueleto en EN", ed.fase1);
      // abrir M1 → Pro tabs + checkpoint tooltip + conversar EN
      await page.evaluate(() => [...document.querySelectorAll(".met-card")].find((c) => /Cierre de earnings/.test(c.textContent)).click());
      await page.waitForFunction(() => window.__metodoEditor && window.__metodoEditor.getMethod().id === "m-earnings", null, { timeout: 5000 });
      await page.evaluate(() => document.querySelector('[data-ed-sw] button[data-sw="pro"]').click());
      await page.waitForSelector(".step-pro", { state: "attached", timeout: 4000 });
      const pro = await page.evaluate(() => ({
        tabs: [...document.querySelectorAll('.ed-sw button[data-t]')].map((b) => b.textContent).join(","),
        ck: document.querySelector('.step [data-ck]').title,
        exe: document.querySelector('[data-pf="executor"]').placeholder,
        conv: document.querySelector("[data-conv-in]").placeholder,
        equip: [...document.querySelectorAll(".msec-h")].map((x) => x.textContent).join(" | "),
        raw: document.getElementById("metEditorHost").innerText,
      }));
      // [REESCRITO · reforma·l] los tabs Pasos/JSON murieron con la vista JSON editable: en Pro
      // ya no hay dos puertas, hay una. Lo que sí sigue siendo bilingüe son los CHIPS de Pro.
      ok(pro.tabs === "", "E1 · sin tabs Pro (la puerta JSON murió)", pro.tabs || "(ninguno)");
      ok(/the process waits for you/.test(pro.ck), "E1 · tooltip de checkpoint EN");
      ok(/the brain decides/.test(pro.exe), "E1 · chip executor EN");
      ok(/ask for a change/.test(pro.conv), "E1 · editar conversando EN");
      ok(/Equipped by \(reference, not copy\)/.test(pro.equip), "E1 · equipar por referencia EN", pro.equip);
      ok(!/Guardar|reintentos|pídele|nombre de la fase/.test(pro.raw), "E1 · sin español crudo en el editor");
      // captura EN
      await page.evaluate(() => window.__metodo.traerProceso());
      await page.evaluate(() => { const d = document.querySelector(".met-scrim"); if (!d) throw 0; });   // dirty-confirm auto-aceptado
      const cap = await page.evaluate(() => ({
        h: document.querySelector(".met-modal h3").textContent,
        ph: document.querySelector("[data-cap-ta]").placeholder,
        go: document.querySelector("[data-cap-go]").textContent,
      }));
      ok(/Bring my process/.test(cap.h) && /paste your process/.test(cap.ph) && /Structure it/.test(cap.go), "E1 · captura multimodal EN", JSON.stringify(cap));
      ok(errors.length === 0, "E1 · 0 errores JS", errors.slice(0, 3).join(" | "));
      await page.close();
    }
    // E2 · grafo EN: strip + card de fallo
    {
      const { page, errors } = await newPage(browser, "en");
      await page.route("**/v1/spaces/**", (r) => r.fulfill({ status: 200, contentType: "text/event-stream", body: "" }));
      await page.route("**/v1/runs/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) }));
      await page.goto(PAGE + "?view=grafo&method=m-earnings&space=sp-1&run=r-1", { waitUntil: "load" });
      await page.waitForFunction(() => window.__metodoGraph, null, { timeout: 9000 });
      const s0 = await page.evaluate(() => ({
        estado: document.getElementById("grEstado").innerText,
        volver: document.getElementById("grVolver").innerText,
      }));
      ok(/waiting for run activity/.test(s0.estado), "E2 · estado del strip EN", s0.estado);
      ok(/library/.test(s0.volver), "E2 · volver a la biblioteca EN");
      await page.evaluate(() => window.__metodoGraph.feed({ type: "gate_waiting", tool: "gmail" }));
      ok(await page.evaluate(() => /waits for you/.test(document.getElementById("grEstado").innerText)), "E2 · checkpoint EN");
      await page.evaluate(() => window.__metodoGraph.feed({ type: "method_step_failed", step_id: "s3", executor: "gmail", diagnosis: "missing credential" }));
      await page.evaluate(() => window.__metodoGraph._clickNode("gmail"));
      await page.waitForSelector("#grDrawer .grfail", { timeout: 5000 });
      const f = await page.evaluate(() => document.getElementById("grDrawer").innerText);
      ok(/you are in charge/i.test(f) && /Retry now/.test(f) && /stays in the audit/.test(f), "E2 · card de remedios EN (el título viaja uppercase por CSS)", f.slice(0, 90));
      ok(!/Reintentar|tú mandas|Diagnóstico:/.test(f), "E2 · sin español crudo en la card");
      const core = await page.evaluate(() => window.__metodoGraph.nodes().find((n) => n.core).label);
      ok(core === "Core", "E2 · el Núcleo se etiqueta 'Core' en EN", core);
      // §8: [data-no-tm] protege el CONTENIDO del usuario de la capa TM (con control positivo)
      const tm = await page.evaluate(() => {
        const mk = (noTm) => { const d = document.createElement("div"); if (noTm) d.setAttribute("data-no-tm", ""); d.textContent = "Guardar"; document.body.appendChild(d); window.AlephI18n.tr(d); const v = d.textContent; d.remove(); return v; };
        return { prot: mk(true), control: mk(false) };
      });
      ok(tm.prot === "Guardar" && tm.control !== "Guardar", "E2 · [data-no-tm]: un paso que coincide con chrome NO se traduce (control sí)", JSON.stringify(tm));
      const aria = await page.evaluate(() => document.getElementById("grCanvas").getAttribute("aria-label"));
      ok(aria === "method graph", "E2 · aria-label del canvas bilingüe (data-i18n-aria)", aria);
      ok(errors.length === 0, "E2 · 0 errores JS", errors.slice(0, 3).join(" | "));
      await page.close();
    }
  }
} finally {
  await browser.close();
  server.kill();
}
console.log(`\n${fails.length ? "FAILS: " + fails.join("; ") : "ALL GREEN"}  (${fails.length} fallos)`);
process.exit(fails.length ? 1 : 0);
