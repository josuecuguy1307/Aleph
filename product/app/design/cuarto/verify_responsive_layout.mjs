/* verify_responsive_layout.mjs — El Cuarto chrome no se pisa ni se recorta.
 * Cubre el bug de controles amontonados: toolbar superior, Flow/tema/HUD abajo-derecha
 * y tooltips largos sobre controles densos.
 *
 * Run: node verify_responsive_layout.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = Number(process.env.RESP_PORT || 8178);
if (PORT === 25374) { console.error("✗ :25374 es la .app instalada — jamás."); process.exit(2); }
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const VIEWPORTS = [
  ["wide", 1440, 900],
  ["medium", 1024, 768],
  ["narrow", 900, 700],
  ["compact", 720, 560],
];
// ⚠️ ACTUALIZADO a las superficies que existen HOY. Salieron: `inspectbar` y `runbar` (las dos
// barras se fueron del lienzo) y `lenswrap` (la lente vive dentro de #cam desde "Cuarto limpio").
// Entró `listo`, el badge de listo-para-la-Sala. Un id muerto acá no es inocuo: la vara mide cajas
// y un getBoundingClientRect sobre null la rompe entera.
const BOX_IDS = ["hud", "topright", "listo", "cam", "legend", "camhint", "aleph-tg"];
const NO_OVERLAP = [
  ["topright", "hud"],
  ["listo", "hud"],
  ["cam", "legend"],        // los dos widgets de la esquina de abajo comparten borde: no pueden pisarse
  ["camhint", "legend"],
  ["camhint", "aleph-tg"],
];
const TOOLTIP_SELECTOR = [
  "#topright [title]",
  "#listo [title]",
  "#cam [title]",
  "#aleph-tg[title]",
].join(",");

const fails = [];
const ok = (cond, label, extra) => {
  console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`);
  if (!cond) fails.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const visible = (b) => b && !b.hidden;
const overlaps = (a, b) => visible(a) && visible(b) && a.right > b.left && b.right > a.left && a.bottom > b.top && b.bottom > a.top;
const insideX = (b, w) => !visible(b) || (b.left >= -0.5 && b.right <= w + 0.5);

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);

let browser;
try {
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto, null, { timeout: 12000 });
  await page.evaluate(() => {
    if (document.getElementById("aleph-tg")) return;
    const btn = document.createElement("button");
    btn.id = "aleph-tg";
    btn.textContent = "☀";
    btn.setAttribute("aria-label", "Tema");
    btn.setAttribute("title", "Tema");
    btn.setAttribute("style", "position:fixed;bottom:18px;right:18px;z-index:99999;width:40px;height:40px;border-radius:12px;border:1px solid rgba(150,150,190,.4);background:rgba(150,150,190,.14);color:inherit;font-size:17px;cursor:pointer");
    document.body.appendChild(btn);
  });

  for (const [name, width, height] of VIEWPORTS) {
    await page.setViewportSize({ width, height });
    await sleep(140);
    const geo = await page.evaluate(({ ids, tooltipSelector }) => {
      const box = (id) => {
        const el = document.getElementById(id);
        if (!el) return null;
        const cs = getComputedStyle(el);
        const b = el.getBoundingClientRect();
        return { id, left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height,
          hidden: cs.display === "none" || cs.visibility === "hidden" };
      };
      return {
        innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        boxes: Object.fromEntries(ids.map((id) => [id, box(id)])),
        titles: [...document.querySelectorAll(tooltipSelector)].map((el) => ({ id: el.id || el.parentElement?.id || el.tagName, title: el.getAttribute("title") || "" })),
      };
    }, { ids: BOX_IDS, tooltipSelector: TOOLTIP_SELECTOR });

    ok(geo.scrollWidth <= geo.innerWidth, `${name} ${width}x${height} · sin overflow horizontal`, `scroll=${geo.scrollWidth}`);
    for (const id of BOX_IDS) ok(insideX(geo.boxes[id], geo.innerWidth), `${name} · #${id} no se recorta horizontalmente`);
    ok(geo.boxes.topright.height <= 48, `${name} · #topright queda en una sola fila`, `h=${Math.round(geo.boxes.topright.height)}`);
    for (const [a, b] of NO_OVERLAP) {
      ok(!overlaps(geo.boxes[a], geo.boxes[b]), `${name} · #${a} no pisa #${b}`);
    }
    const long = geo.titles.filter((t) => t.title.length > 24);
    ok(long.length === 0, `${name} · tooltips densos son cortos`, long.map((t) => `${t.id}=${t.title.length}`).join(", "));
  }

  ok(errors.length === 0, "0 errores JS/render de página", errors.slice(0, 3).join(" ; "));
} catch (e) {
  console.error("HARNESS ERROR:", e);
  fails.push(`harness: ${e && e.message ? e.message : String(e)}`);
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill();
}

console.log("");
if (fails.length === 0) {
  console.log("RESULTADO: VERDE — layout responsive del Cuarto sin clipping ni overlap (wide/medium/narrow/compact · tooltips cortos)");
  process.exit(0);
}
console.log(`RESULTADO: ROJO (${fails.length})`);
fails.forEach((f) => console.log(" - " + f));
process.exit(1);
