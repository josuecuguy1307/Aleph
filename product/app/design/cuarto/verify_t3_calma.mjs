/* verify_t3_calma.mjs — T3 "Calma" de la tanda CUARTO HONESTO (reports/step5/CUARTO-HONESTO.md §4).
 * Cubre las 4 piezas del slice, en wide/medium/narrow + WebKit + Chromium:
 *   1. Barra en 3 FAMILIAS (nav · acciones · meta) con separación + tooltips + meta colapsable en menú.
 *   2. Inspector PROGRESIVO: nivel 1 (qué es + slot de estado §1 + 1 acción) · "más" expande · el drawer gigante muere.
 *   3. Chat de pieza con CHIPS de límites concretos (cada chip = un cambio real, vía applyChatEdit).
 *   4. Fix del overflow de Biblioteca a 520px (WebKit).
 *
 * Estado (§1) lo pinta T2 — acá sólo el LAYOUT y su slot (#iestado). Run: node verify_t3_calma.mjs
 */
import { chromium, webkit } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = Number(process.env.T3_PORT || 8196);
if (PORT === 25374) { console.error("✗ :25374 es la .app instalada — jamás."); process.exit(2); }
const CUARTO = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const BIBLIO = `http://localhost:${PORT}/Biblioteca.dc.html`;
const VIEWPORTS = [["wide", 1440, 900], ["medium", 1024, 768], ["narrow", 900, 700]];

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(800);

async function runCuarto(engine, nm) {
  const b = await engine.launch();
  const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e).slice(0, 140)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errs.push(m.text().slice(0, 120)); });
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.goto(CUARTO, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__guideHost && window.__openInspector && window.__metaMenu, null, { timeout: 15000 });

  // ── 1) BARRA en 3 familias, por viewport ──
  for (const [vn, w, h] of VIEWPORTS) {
    await page.setViewportSize({ width: w, height: h });
    await sleep(150);
    const g = await page.evaluate(() => {
      const tr = document.getElementById("topright");
      const groups = [...document.querySelectorAll("#topright > .tbgroup")].map((e) => e.dataset.fam);
      const seps = document.querySelectorAll("#topright > .tbsep").length;
      const menu = document.getElementById("metaMenu");
      const menuIds = [...menu.querySelectorAll(".pill")].map((p) => p.id);
      const r = tr.getBoundingClientRect();
      // [INTEGRACIÓN P11] el botón Sala deshabilitado usa `title` como explicación causal
      // («equipá al menos una pieza»). Esa prosa no es un tooltip decorativo de la barra:
      // es la salida accesible de un control que no puede actuar todavía (§6 de P11).
      const titles = [...document.querySelectorAll("#topright [title]")]
        .filter((el) => !(el.id === "salaBtn" && el.disabled))
        .map((el) => (el.getAttribute("title") || ""));
      // [ola C · item 2] las FAMILIAS se mudaron ADENTRO del ⋯ (con encabezado cada una)
      const fams = [...menu.querySelectorAll(".mfam")].map((f) => (f.querySelector(".mfam-h")?.textContent || "").trim());
      return { groups, seps, fams, menuHidden: menu.hidden, menuIds, h: Math.round(r.height),
        inside: r.left >= -0.5 && r.right <= innerWidth + 0.5, scroll: document.documentElement.scrollWidth, iw: innerWidth,
        longTitles: titles.filter((t) => t.length > 24).length };
    });
    // ── SUPERSEDED por la ola C · CUARTO LIMPIO (item 2) ──────────────────────────────────────
    // T3 §4 pedía la barra "reagrupada en 3 familias con separación visual: navegación · acciones ·
    // meta". La ola C va un paso más allá con la MISMA intención (§8.2 mínimo visible): en la barra
    // quedan SÓLO 3 controles — ← Salir · ▶ Run · ⋯ — y las FAMILIAS (con su separación y sus
    // encabezados) viven DENTRO del ⋯. La agrupación no se perdió: se anidó. Se verifica ahí.
    ok(g.groups.join(",") === "nav,meta", `${nm} ${vn} · barra reducida a nav + ⋯ (ola C)`, g.groups.join(","));
    ok(g.seps === 1, `${nm} ${vn} · separador visual entre nav y ⋯`, `seps=${g.seps}`);
    ok(g.fams.length >= 4 && g.fams.every(Boolean),
      `${nm} ${vn} · las familias viven DENTRO del ⋯, con encabezado`, g.fams.join(" · "));
    ok(g.h <= 48, `${nm} ${vn} · barra en una sola fila`, `h=${g.h}`);
    ok(g.inside && g.scroll <= g.iw, `${nm} ${vn} · barra dentro del viewport, sin overflow`);
    ok(g.menuHidden, `${nm} ${vn} · menú meta oculto por default`);
    // [identidad visual 6/6] "⚙ Modo técnico" salió del menú: el modo murió (la revisión de tools
    // ahora aparece sola). Quedan las tres que sí son meta de vista/ayuda.
    ok(["cuartoThemeBtn", "copBtn", "evToggle"].every((id) => g.menuIds.includes(id)),
      `${nm} ${vn} · meta (☀ ? EV) dentro del menú`, g.menuIds.join(","));
    ok(!g.menuIds.includes("manualBtn"),
      `${nm} ${vn} · sin toggle de modo en el menú`, g.menuIds.join(","));
    ok(g.longTitles === 0, `${nm} ${vn} · tooltips de la barra ≤24 chars`);
  }
  // interacción del menú (wide)
  await page.setViewportSize({ width: 1440, height: 900 }); await sleep(120);
  await page.click("#metaBtn"); await sleep(100);
  const opened = await page.evaluate(() => { const m = document.getElementById("metaMenu"); const r = m.getBoundingClientRect();
    return { hidden: m.hidden, exp: document.getElementById("metaBtn").getAttribute("aria-expanded"), inside: r.right <= innerWidth + 0.5, ev: !!m.querySelector("#evToggle") }; });
  ok(!opened.hidden && opened.exp === "true" && opened.inside, `${nm} · ⋯ abre el menú meta dentro del viewport`);
  ok(opened.ev, `${nm} · EV (evidencia) reubicado dentro del menú meta`);
  await page.keyboard.press("Escape"); await sleep(80);
  ok(await page.evaluate(() => document.getElementById("metaMenu").hidden), `${nm} · Escape cierra el menú meta`);

  // ── 2) INSPECTOR progresivo ──
  await page.evaluate(() => window.__openInspector({ atom: "tool", role: "entrega", server: "gmail", label: "Gmail", tools: ["gmail_send", "gmail_search"], gated: true }));
  await sleep(140);
  const col = await page.evaluate(() => {
    const insp = document.getElementById("inspector");
    return { expanded: insp.classList.contains("expanded"), nivel2: getComputedStyle(document.getElementById("inspExpand")).display !== "none",
      purpose: (document.getElementById("ipurpose").textContent || "").length, primary: !!document.getElementById("iprimary").textContent,
      more: !!document.getElementById("iexpand"), estado: !!document.getElementById("iestado"), h: Math.round(insp.getBoundingClientRect().height) };
  });
  ok(!col.expanded && !col.nivel2, `${nm} · inspector abre COLAPSADO (nivel 2 oculto — jamás vuelca todo plano)`);
  ok(col.purpose > 0 && col.primary && col.more, `${nm} · nivel 1 = qué es + 1 acción + "más"`);
  ok(col.estado, `${nm} · slot de estado §1 (#iestado) presente para T2`);
  await page.click("#iexpand"); await sleep(140);
  const exp = await page.evaluate(() => ({ expanded: document.getElementById("inspector").classList.contains("expanded"),
    tabs: getComputedStyle(document.querySelector("#inspector .tabs")).display !== "none", h: Math.round(document.getElementById("inspector").getBoundingClientRect().height) }));
  ok(exp.expanded && exp.tabs && exp.h > col.h, `${nm} · "más" expande el detalle (tabs)`, `${col.h}→${exp.h}`);
  await page.click("#iexpand"); await sleep(100);
  ok(!(await page.evaluate(() => document.getElementById("inspector").classList.contains("expanded"))), `${nm} · "más" otra vez colapsa`);

  // ── 3) CHAT chips honestos ──
  await page.evaluate(() => { window.__setInspectorExpanded(false); window.__openInspector(window.__cuarto.nucleoData()); window.__setInspectorExpanded(true); });
  await sleep(140);
  const nucChips = await page.evaluate(() => [...document.querySelectorAll("#d-chat .chatchip")].map((c) => c.textContent));
  ok(nucChips.length >= 5, `${nm} · núcleo: chips de conducta`, nucChips.join(" · "));
  const nucApply = await page.evaluate(() => { const c = [...document.querySelectorAll("#d-chat .chatchip")].find((x) => x.textContent === "Frena siempre"); c && c.click();
    const s = document.querySelector("#chatlog .chatline .sys"); return s ? { txt: s.textContent, warn: s.className.includes("warn") } : null; });
  ok(nucApply && !nucApply.warn && /receta actualizada/.test(nucApply.txt), `${nm} · chip aplica un cambio REAL (honesto)`, nucApply && nucApply.txt);
  await page.evaluate(() => { window.__setInspectorExpanded(false); window.__openInspector({ atom: "tool", role: "entrega", server: "gmail", label: "Gmail", tools: ["gmail_send", "gmail_search"] }); window.__setInspectorExpanded(true); });
  await sleep(120);
  const toolChips = await page.evaluate(() => [...document.querySelectorAll("#d-chat .chatchip")].map((c) => c.dataset.phrase));
  ok(toolChips.some((p) => p.includes("send")) && toolChips.includes("frena siempre"), `${nm} · tool: chips concretos con sus tools reales`, toolChips.join(" · "));
  await page.evaluate(() => { window.__setInspectorExpanded(false); window.__openInspector({ atom: "contexto", label: "Memoria" }); window.__setInspectorExpanded(true); });
  await sleep(100);
  const ctx = await page.evaluate(() => ({ chips: document.querySelectorAll("#d-chat .chatchip").length, note: !!document.querySelector("#d-chat .chatnote"), input: !!document.getElementById("chatin") }));
  ok(ctx.chips === 0 && ctx.note && !ctx.input, `${nm} · contexto: nota honesta (a Opciones), sin campo abierto que promete todo`);

  ok(errs.length === 0, `${nm} · 0 errores JS/render en el Cuarto`, errs.slice(0, 2).join(" | "));
  await b.close();
}

async function runBiblioteca(engine, nm) {
  const b = await engine.launch();
  const page = await b.newPage({ viewport: { width: 900, height: 820 } });
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ outputs: [] }) }));
  await page.goto(BIBLIO, { waitUntil: "load" });
  await sleep(1300);
  for (const w of [520, 480, 560, 700, 900]) {
    await page.setViewportSize({ width: w, height: 820 }); await sleep(180);
    const m = await page.evaluate(() => ({ iw: innerWidth, sw: document.documentElement.scrollWidth, roster: !!document.querySelector(".libRosterRow") }));
    ok(m.sw <= m.iw, `${nm} · Biblioteca @${w}px sin overflow horizontal`, `scroll=${m.sw} inner=${m.iw}`);
    if (w === 520) ok(m.roster, `${nm} · Biblioteca @520 renderiza el roster`);
  }
  await b.close();
}

try {
  await runCuarto(chromium, "chromium");
  await runCuarto(webkit, "webkit");
  await runBiblioteca(webkit, "webkit");
  await runBiblioteca(chromium, "chromium");
} catch (e) {
  console.error("HARNESS ERROR:", e);
  fails.push(`harness: ${e && e.message ? e.message : String(e)}`);
} finally {
  server.kill();
}

console.log("");
if (fails.length === 0) {
  console.log("RESULTADO: VERDE — T3 Calma: barra nav+⋯ con las familias anidadas (ola C) · inspector progresivo · chat con chips honestos · Biblioteca 520px (wide/medium/narrow · WebKit+Chromium)");
  process.exit(0);
}
console.log(`RESULTADO: ROJO (${fails.length})`);
fails.forEach((f) => console.log(" - " + f));
process.exit(1);
