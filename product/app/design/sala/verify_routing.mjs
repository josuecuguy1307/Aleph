/* verify_routing.mjs — ruteo de OBRA RICA en sala.html: fixture → renderer correcto.
 *
 * Página REAL + renderers REALES; solo el backend está stubeado (determinismo, corre sin
 * stack). Un caso por fixture de sala/fixtures/: el JSON entra como out.obra del run y se
 * asserta el DOM del canvas por tipo (introspección dentro de iframes para volume3d).
 *
 * DOBLE ROL:
 *  - GOLDEN: convergence (fem/quant) y fieldplot son los tipos que el filtro HISTÓRICO
 *    acepta — sus asserts codifican el comportamiento observable de hoy y deben seguir
 *    verdes tras cualquier cambio de ruteo.
 *  - BUG-BAR: planilla / volume3d / imagen llegan como out.obra del backend y HOY se
 *    dropean (sala.html:1526) → estos casos arrancan ROJOS y el fix RICH_SHAPES los
 *    tiene que poner verdes SIN mover los goldens.
 *
 *   node product/app/design/sala/verify_routing.mjs            # todos
 *   node product/app/design/sala/verify_routing.mjs golden     # solo goldens
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = new URL("..", import.meta.url).pathname;            // product/app/design/
const FIX = new URL("./fixtures/", import.meta.url).pathname;
const SHOTS = new URL("./screenshots/", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };

const CASES = [
  { key: "fem-convergence", golden: true, fixture: "fem.convergence.json",
    assert: async (page, chk) => {
      // el hook _convShow se cuelga del nodo cuando el widget TERMINA de montar —
      // esperarlo (sin esto, ~1 de cada 5 corridas leía el veredicto antes de tiempo).
      await page.waitForFunction(() => {
        const n = document.querySelector("#canvas .aleph-render");
        return n && typeof n._convShow === "function" &&
               document.querySelectorAll("#canvas .ar-conv-dot").length === 3;
      }, { timeout: 10_000 }).catch(() => {});
      const st = await page.evaluate(() => ({
        cls: document.getElementById("canvas").className,
        conv: !!document.querySelector("#canvas .ar-conv"),
        dots: document.querySelectorAll("#canvas .ar-conv-dot").length,
        count: (document.querySelector("#canvas .aleph-render") || {})._convCount ?? null,
      }));
      chk.check("canvas → sala-rich-convergence", /sala-rich-convergence/.test(st.cls), st.cls);
      chk.check("stepper .ar-conv montado", st.conv);
      chk.check("3 iteraciones (dots)", st.dots === 3, "dots=" + st.dots);
      // veredicto final PASA (última iteración bajo el límite) vía hook determinístico
      await page.evaluate(() => { const n = document.querySelector("#canvas .aleph-render"); n && n._convShow && n._convShow(2); });
      const verdict = await page.evaluate(() => (document.querySelector("#canvas .ar-conv-verdict") || {}).className || "");
      chk.check("veredicto PASA en la última iteración", /pass/.test(verdict), verdict);
    } },
  { key: "quant-convergence", golden: true, fixture: "quant.convergence.json",
    assert: async (page, chk) => {
      const st = await page.evaluate(() => ({
        cls: document.getElementById("canvas").className,
        dots: document.querySelectorAll("#canvas .ar-conv-dot").length,
        stageCanvas: !!document.querySelector("#canvas .ar-conv-stage canvas"),
      }));
      chk.check("canvas → sala-rich-convergence", /sala-rich-convergence/.test(st.cls), st.cls);
      chk.check("3 iteraciones (dots)", st.dots === 3, "dots=" + st.dots);
      chk.check("stage dibuja la curva de equity (canvas)", st.stageCanvas);
    } },
  { key: "fem-fieldplot", golden: true, fixture: "fem.fieldplot.json",
    assert: async (page, chk) => {
      const st = await page.evaluate(() => ({
        cls: document.getElementById("canvas").className,
        canvas: !!document.querySelector("#canvas .ar-field-canvas"),
      }));
      chk.check("canvas → sala-rich-fieldplot", /sala-rich-fieldplot/.test(st.cls), st.cls);
      chk.check("heatmap real en canvas", st.canvas);
    } },
  { key: "electronica-planilla", golden: false, fixture: "electronica.planilla.json",
    assert: async (page, chk) => {
      const st = await page.evaluate(() => ({
        cls: document.getElementById("canvas").className,
        rows: document.querySelectorAll("#canvas table tbody tr").length,
        head: (document.querySelector("#canvas table thead") || {}).textContent || "",
      }));
      chk.check("canvas → sala-planilla (BOM del backend ya no se dropea)", /sala-planilla/.test(st.cls), st.cls);
      chk.check("grilla con las filas del fixture", st.rows === 4, "rows=" + st.rows);
      chk.check("cabecera real (Precio USD)", /Precio USD/.test(st.head), st.head);
    } },
  { key: "medicina-volume3d", golden: false, fixture: "medicina.volume3d.json",
    assert: async (page, chk) => {
      const cls = await page.evaluate(() => document.getElementById("canvas").className);
      chk.check("canvas → sala-rich-volume3d (el hero médico llega al canvas)", /sala-rich-volume3d/.test(cls), cls);
      // adentro del iframe sandbox: three.js montó un canvas WebGL y no hay #err
      let inner = { canvas: false, err: true };
      for (let i = 0; i < 40 && !inner.canvas; i++) {
        for (const f of page.frames()) {
          if (f === page.mainFrame()) continue;
          try { inner = await f.evaluate(() => ({ canvas: !!document.querySelector("canvas"), err: !!document.querySelector("#err") })); } catch {}
          if (inner.canvas) break;
        }
        if (!inner.canvas) await page.waitForTimeout(250);
      }
      chk.check("iframe: mesh three.js montado (canvas)", inner.canvas, JSON.stringify(inner));
      chk.check("iframe: sin #err", !inner.err);
    } },
  { key: "informe-charts", golden: false, fixture: "informe.charts.json",
    assert: async (page, chk) => {
      // el informe llega por out.answer (no out.obra) — ejercita la copia SalaRender
      // de buildChartSVG: 4 fences → 4 SVGs reales, velas con up+down.
      const st = await page.evaluate(() => {
        const c = document.getElementById("canvas");
        return {
          cls: c.className,
          figs: c.querySelectorAll(".sala-chart-fig").length,
          up: c.querySelectorAll('rect[data-candle="up"]').length,
          down: c.querySelectorAll('rect[data-candle="down"]').length,
        };
      });
      chk.check("canvas → sala-informe", /sala-informe/.test(st.cls), st.cls);
      chk.check("4 charts SVG reales (bar/area/scatter/candlestick)", st.figs === 4, "figs=" + st.figs);
      chk.check("velas up+down presentes", st.up > 0 && st.down > 0, JSON.stringify(st));
    } },
  { key: "medicina-imagen", golden: false, fixture: "medicina.imagen.json",
    assert: async (page, chk) => {
      const st = await page.evaluate(() => {
        const img = document.querySelector("#canvas img.sala-img");
        return { cls: document.getElementById("canvas").className, img: !!img, data: img ? img.src.startsWith("data:image/png") : false };
      });
      chk.check("canvas → sala-imagen (CT del backend ya no se dropea)", /sala-imagen/.test(st.cls), st.cls);
      chk.check("img montada desde data-uri PNG real", st.img && st.data, JSON.stringify(st));
    } },
  { key: "finanzas-linechart", golden: false, fixture: "finanzas.linechart.json",
    assert: async (page, chk) => {
      const st = await page.evaluate(() => {
        const fig = document.querySelector("#canvas .ar-chart-fig.ar-linechart");
        return {
          cls: document.getElementById("canvas").className,
          fig: !!fig,
          paths: fig ? fig.querySelectorAll("svg path").length : 0,
          points: fig ? fig.querySelectorAll("svg circle").length : 0,
          src: fig && fig.querySelector("figcaption") ? fig.querySelector("figcaption").textContent : "",
        };
      });
      chk.check("canvas → sala-rich-linechart (serie del worldbank llega al canvas)", /sala-rich-linechart/.test(st.cls), st.cls);
      chk.check("línea real (svg path) montada", st.fig && st.paths >= 1, JSON.stringify(st));
      chk.check("7 puntos de la serie", st.points === 7, "points=" + st.points);
      chk.check("procedencia visible (World Bank)", /World Bank/.test(st.src), st.src);
    } },
];

/* ── server estático efímero, root product/app/design/ ────────────────────── */
function serveDesign() {
  return new Promise((res) => {
    const srv = http.createServer((req, r) => {
      const p = path.join(DESIGN, decodeURIComponent(new URL(req.url, "http://x").pathname));
      if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
      r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
      fs.createReadStream(p).pipe(r);
    });
    srv.listen(0, "127.0.0.1", () => res(srv));
  });
}

/* ── stub del backend: la obra rica del fixture entra como out.obra ────────── */
function routesFor(fixtureJson) {
  // informe viaja como out.answer (así llega en producción); los ricos como out.obra
  const isInforme = fixtureJson.type === "informe";
  const out = {
    ok: true, run_id: "fx-run",
    answer: isInforme ? fixtureJson.content : "obra del fixture lista",
    record: { tool_calls: [], model_final: "fixture", degraded: null },
    outputs_captured: [], held_actions: [],
    obra: isInforme ? null : fixtureJson,
  };
  return [
    { url: "**/v1/classify-turn", handler: (r) => r.fulfill({ json: { turn: "obra" } }) },
    { url: "**/v1/artifacts/classify-action", handler: (r) => r.fulfill({ json: { action: "new" } }) },
    { url: "**/v1/puppets/run", handler: async (r) => r.fulfill({ json: out }) },
    { url: "**/v1/sessions/**", handler: (r) => r.request().method() === "GET"
        ? r.fulfill({ json: { artifacts: [] } }) : r.fulfill({ json: { id: "a-fx" } }) },
    { url: "**/v1/users/**", handler: (r) => r.fulfill({ json: { puppets: [], keys: [], docs: [] } }) },
    { url: "**/v1/obra-caption", handler: (r) => r.fulfill({ json: {} }) },
    { url: "**/v1/belts/**", handler: (r) => r.fulfill({ json: { cards: [] } }) },
  ];
}

const only = process.argv[2];
const selected = only === "golden" ? CASES.filter((c) => c.golden) : CASES;

const srv = await serveDesign();
const base = "http://127.0.0.1:" + srv.address().port;
const browser = await chromium.launch();
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
for (const c of selected) {
  console.log("══ " + c.key + (c.golden ? " [GOLDEN]" : " [BUG-BAR]") + " ══");
  const fails = [];
  const chk = {
    check(name, ok, detail) {
      fails.push(...(ok ? [] : [name]));
      console.log((ok ? "  ✓ " : "  ✗ ") + name + (ok || !detail ? "" : "  → " + detail));
    },
  };
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, reducedMotion: "reduce" });
  await ctx.addInitScript(() => {
    try {
      if (window.top !== window) return;
      sessionStorage.setItem("puppet_user", JSON.stringify({ id: "fx-user", session_token: "fx-token" }));
      localStorage.setItem("aleph-lang", "es");
    } catch {}
  });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  const fixture = JSON.parse(fs.readFileSync(FIX + c.fixture, "utf8"));
  for (const r of routesFor(fixture)) await page.route(r.url, r.handler);

  await page.goto(base + "/sala/sala.html", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#composer", { timeout: 15_000 });
  await page.fill("#composer", "muéstrame la obra del caso " + c.key);
  await page.press("#composer", "Enter");
  await page.waitForFunction(() => {
    const send = document.getElementById("send"), badge = document.getElementById("bbadge");
    return send && !send.disabled && (!badge || badge.style.display === "none");
  }, { timeout: 20_000 });
  await page.waitForTimeout(400);   // debounce del render (90ms) + hidratación corta

  await c.assert(page, chk);
  const errs = consoleErrors.filter((t) => !/favicon/i.test(t));
  chk.check("consola limpia", errs.length === 0, errs.slice(0, 2).join(" | "));

  await page.screenshot({ path: SHOTS + "routing-" + c.key + ".png" });
  results.push({ key: c.key, golden: c.golden, pass: fails.length === 0, fails });
  await ctx.close();
}
await browser.close();
srv.close();

console.log("\n════ RUTEO ════");
for (const r of results) console.log((r.pass ? "  ✓ " : "  ✗ ") + r.key + (r.golden ? " [golden]" : ""));
const goldenBroken = results.filter((r) => r.golden && !r.pass);
const allPass = results.every((r) => r.pass);
if (goldenBroken.length) console.log("✗✗ GOLDEN ROTO — el ruteo histórico cambió: " + goldenBroken.map((r) => r.key).join(", "));
console.log(allPass ? "✓ RUTEO VERDE" : "✗ hay rojos");
process.exit(goldenBroken.length ? 2 : allPass ? 0 : 1);
