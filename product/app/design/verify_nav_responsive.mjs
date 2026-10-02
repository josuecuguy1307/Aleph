/* verify_nav_responsive.mjs -- focused regression for Aleph navigation chrome.
 * Serves product/app/design and verifies that ordinary pages keep the shared
 * topbar responsive while workspace surfaces expose Home/theme controls in top
 * UI instead of a detached bottom launcher.
 *
 * Run:
 *   node product/app/design/verify_nav_responsive.mjs
 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { accessSync, constants } from "node:fs";
import { join, extname, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

const fails = [];
const ok = (cond, label, extra = "") => {
  console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`);
  if (!cond) fails.push(label + (extra ? " " + extra : ""));
};

function localChromePath() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  const candidates = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  ];
  for (const p of candidates) {
    try { accessSync(p, constants.X_OK); return p; } catch {}
  }
  return null;
}

async function startServer() {
  const server = createServer(async (req, res) => {
    try {
      const pathname = decodeURIComponent((req.url || "/").split("?")[0]);
      const rel = pathname === "/" ? "/Home.dc.html" : pathname;
      const file = resolve(join(ROOT, rel));
      if (!file.startsWith(ROOT)) throw new Error("outside root");
      const buf = await readFile(file);
      res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
      res.end(buf);
    } catch {
      res.writeHead(404);
      res.end("not found");
    }
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  return server;
}

async function navState(page) {
  return await page.evaluate(() => {
    const rect = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
    };
    const visible = [...document.querySelectorAll("#aleph-topbar, #aleph-topbar > *, #aleph-topbar a, #aleph-topbar button")]
      .map((el) => ({ label: el.id || el.className || el.textContent.trim(), rect: rect(el) }))
      .filter((x) => x.rect && x.rect.width > 0 && x.rect.height > 0);
    const clipped = visible.filter((x) => x.rect.left < -0.5 || x.rect.right > innerWidth + 0.5);
    const library = [...document.querySelectorAll(".aleph-tb-link")]
      .find((a) => a.textContent.includes("Biblioteca") || a.textContent.includes("Library"));
    return {
      viewport: { width: innerWidth, height: innerHeight },
      topbar: rect(document.querySelector("#aleph-topbar")),
      linksDisplay: getComputedStyle(document.querySelector(".aleph-tb-links")).display,
      burgerDisplay: getComputedStyle(document.querySelector("#aleph-tb-burger")).display,
      ctaDisplay: getComputedStyle(document.querySelector(".aleph-tb-cta")).display,
      brandTextDisplay: getComputedStyle(document.querySelector(".aleph-tb-brand span")).display,
      visible,
      clipped,
      library: rect(library),
    };
  });
}

async function workspaceState(page) {
  return await page.evaluate(() => {
    const rect = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
    };
    const visible = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
    };
    const home = document.querySelector("#homeBtn, #salaHome");
    const theme = document.querySelector("#cuartoThemeBtn, #salaThemeBtn");
    return {
      viewport: { width: innerWidth, height: innerHeight },
      bottomLauncher: rect(document.querySelector("#aleph-nav-btn")),
      bottomTheme: rect(document.querySelector("#aleph-tg")),
      home: rect(home),
      theme: rect(theme),
      lens: rect(document.querySelector("#lenswrap")),
      activeId: document.activeElement && document.activeElement.id,
      homeVisible: visible(home),
      themeVisible: visible(theme),
      homeTitle: home && home.getAttribute("title"),
      homeAria: home && home.getAttribute("aria-label"),
      themeTitle: theme && theme.getAttribute("title"),
      themeAria: theme && theme.getAttribute("aria-label"),
    };
  });
}

const server = await startServer();
const port = server.address().port;
const chromePath = localChromePath();
const launchOpts = chromePath ? { executablePath: chromePath } : {};
let browser;

try {
  browser = await chromium.launch({ headless: true, ...launchOpts });

  for (const vp of [
    { width: 1280, height: 860, name: "wide" },
    { width: 1100, height: 760, name: "boundary" },
    { width: 390, height: 700, name: "narrow" },
    { width: 320, height: 700, name: "extra-narrow" },
  ]) {
    const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 1, reducedMotion: "reduce" });
    const page = await ctx.newPage();
    await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
    await page.goto(`http://127.0.0.1:${port}/Biblioteca.dc.html`, { waitUntil: "load" });
    await page.waitForSelector("#aleph-topbar");

    const st = await navState(page);
    ok(st.topbar.left === 0 && Math.abs(st.topbar.right - vp.width) < 0.5, `${vp.name}: topbar spans viewport`, JSON.stringify(st.topbar));
    ok(st.clipped.length === 0, `${vp.name}: visible topbar controls stay in viewport`, JSON.stringify(st.clipped));

    if (vp.name === "wide") {
      ok(st.linksDisplay === "flex", "wide: desktop links are visible", `display=${st.linksDisplay}`);
      ok(st.library.left >= 0 && st.library.right <= vp.width, "wide: Biblioteca link starts inside viewport", JSON.stringify(st.library));
    } else {
      ok(st.linksDisplay === "none" && st.burgerDisplay === "flex", `${vp.name}: links collapse to burger`, `links=${st.linksDisplay} burger=${st.burgerDisplay}`);
    }
    if (vp.width <= 520) ok(st.ctaDisplay === "none", `${vp.name}: CTA is folded into drawer`, `display=${st.ctaDisplay}`);
    if (vp.width <= 360) ok(st.brandTextDisplay === "none", `${vp.name}: brand text yields to controls`, `display=${st.brandTextDisplay}`);

    if (vp.name === "narrow") {
      await page.click("#aleph-tb-burger");
      await page.waitForSelector("#aleph-nav-panel.on");
      const drawer = await page.evaluate(() => {
        const rect = (el) => {
          const r = el.getBoundingClientRect();
          return { left: r.left, right: r.right, width: r.width };
        };
        const link = [...document.querySelectorAll(".aleph-nav-link")]
          .find((a) => a.textContent.includes("Biblioteca"));
        return { panel: rect(document.querySelector("#aleph-nav-panel")), library: rect(link) };
      });
      ok(drawer.panel.left === 0, "narrow drawer: panel opens from viewport left", JSON.stringify(drawer.panel));
      ok(drawer.library.left >= 0 && drawer.library.right <= vp.width, "narrow drawer: Biblioteca starts inside viewport", JSON.stringify(drawer.library));
    }

    await ctx.close();
  }

  for (const pageCase of [
    { path: "/cuarto/cuarto.pixi.html", name: "Cuarto", home: "#homeBtn", theme: "#cuartoThemeBtn", hasLens: true },
    { path: "/sala/sala.html", name: "Sala", home: "#salaHome", theme: "#salaThemeBtn", hasLens: false },
  ]) {
    for (const vp of [
      { width: 1280, height: 820, name: "wide" },
      { width: 390, height: 700, name: "narrow" },
    ]) {
      const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 1, reducedMotion: "reduce" });
      const page = await ctx.newPage();
      await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
      await page.goto(`http://127.0.0.1:${port}${pageCase.path}`, { waitUntil: "load" });
      await page.waitForSelector(pageCase.home);
      await page.focus(pageCase.home);

      const st = await workspaceState(page);
      ok(!st.bottomLauncher, `${pageCase.name} ${vp.name}: no bottom navigation launcher`, JSON.stringify(st.bottomLauncher));
      ok(!st.bottomTheme, `${pageCase.name} ${vp.name}: theme is not a bottom-right square`, JSON.stringify(st.bottomTheme));
      ok(st.homeVisible, `${pageCase.name} ${vp.name}: Home control is visible`);
      ok(st.themeVisible, `${pageCase.name} ${vp.name}: theme control is still available`);
      ok(st.home.top >= 0 && st.home.bottom <= Math.min(vp.height, 180) && st.home.left >= 0 && st.home.right <= vp.width,
        `${pageCase.name} ${vp.name}: Home control stays in top UI`, JSON.stringify(st.home));
      ok(st.homeTitle === "Home" && st.homeAria === "Home", `${pageCase.name} ${vp.name}: Home control has tooltip and accessible label`, `title=${st.homeTitle} aria=${st.homeAria}`);
      ok(st.themeTitle === "Tema" && st.themeAria === "Tema", `${pageCase.name} ${vp.name}: theme control has tooltip and accessible label`, `title=${st.themeTitle} aria=${st.themeAria}`);
      ok(st.activeId === pageCase.home.slice(1), `${pageCase.name} ${vp.name}: Home accepts keyboard focus`, `active=${st.activeId}`);
      if (pageCase.hasLens) ok(!!st.lens, `${pageCase.name} ${vp.name}: Flow control remains present`, JSON.stringify(st.lens));

      await ctx.close();
    }
  }
} catch (e) {
  console.error("HARNESS ERROR:", e);
  fails.push(e && e.message ? e.message : String(e));
} finally {
  if (browser) await browser.close();
  await new Promise((r) => server.close(r));
}

console.log("");
if (!fails.length) {
  console.log("RESULTADO: VERDE -- nav responsive sin clipping horizontal");
  process.exit(0);
}
console.log(`RESULTADO: ROJO (${fails.length})`);
for (const f of fails) console.log(" - " + f);
process.exit(1);
