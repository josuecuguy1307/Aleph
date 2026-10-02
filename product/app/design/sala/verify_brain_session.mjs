/* verify_brain_session.mjs -- Guide brain selection -> session -> LLM request.
 *
 * Serves the real design surface, opens sala.html, and stubs only /v1 so the
 * emitted Guide requests can be inspected deterministically.
 *
 * Run:
 *   node product/app/design/sala/verify_brain_session.mjs
 */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DIR = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(DIR, "..");
const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

const failures = [];
function check(label, condition, detail = "") {
  console.log(`${condition ? "OK" : "FAIL"} ${label}${detail ? " -- " + detail : ""}`);
  if (!condition) failures.push(label + (detail ? " -- " + detail : ""));
}

async function startServer() {
  const server = createServer(async (req, res) => {
    try {
      const pathname = decodeURIComponent((req.url || "/").split("?")[0]);
      const file = resolve(join(ROOT, pathname === "/" ? "/Home.dc.html" : pathname));
      if (!file.startsWith(ROOT)) throw new Error("outside root");
      const buf = await readFile(file);
      res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
      res.end(buf);
    } catch {
      res.writeHead(404);
      res.end("not found");
    }
  });
  await new Promise((resolveListen) => server.listen(0, "127.0.0.1", resolveListen));
  return server;
}

function defaultRoutes(page, seen, runHandler) {
  page.route("**/v1/classify-turn", async (route) => {
    seen.classifyAuth = route.request().headers().authorization || "";
    seen.classifyBody = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ turn: "chat" }) });
  });
  page.route("**/v1/puppets/run/stream", async (route) => {
    seen.runAuth = route.request().headers().authorization || "";
    seen.runBody = JSON.parse(route.request().postData() || "{}");
    seen.runCount = (seen.runCount || 0) + 1;
    await runHandler(route, seen);
  });
  page.route("**/v1/sessions/**", async (route) => {
    const body = route.request().method() === "GET" ? { artifacts: [] } : { id: "artifact-fixture" };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  page.route("**/v1/users/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ puppets: [], keys: [], docs: [] }) });
  });
  page.route("**/v1/obra-caption", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });
  page.route("**/v1/belts/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ cards: [] }) });
  });
}

async function openGuide(browser, base, storedUser, runHandler) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, reducedMotion: "reduce" });
  await context.addInitScript((user) => {
    localStorage.setItem("puppet_user", JSON.stringify(user));
    localStorage.setItem("aleph-lang", "es");
  }, storedUser);
  const page = await context.newPage();
  const seen = {};
  defaultRoutes(page, seen, runHandler);
  await page.goto(base + "/sala/sala.html", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#composer", { timeout: 15_000 });
  await page.waitForFunction(() => window.__salaSliceD?.state?.().ready, { timeout: 15_000 });
  await page.evaluate(() => {
    window.__salaSliceD.set({ power: "oss" });
    window.AlephBrain?.setActive?.("oss");
  });
  return { context, page, seen };
}

const server = await startServer();
const base = "http://127.0.0.1:" + server.address().port;
const browser = await chromium.launch();

try {
  const valid = await openGuide(
    browser,
    base,
    { id: "guide-user", email: "guide@example.test", session_token: "guide-token" },
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'data: {"type":"done","answer":"ola desde GPT-OSS 120B"}\n\n',
      });
    }
  );
  await valid.page.fill("#composer", "ola");
  await valid.page.press("#composer", "Enter");
  await valid.page.waitForFunction(() => document.body.innerText.includes("ola desde GPT-OSS 120B"), { timeout: 10_000 });

  const hydrated = await valid.page.evaluate(() => {
    try { return JSON.parse(sessionStorage.getItem("puppet_user") || "{}"); } catch { return {}; }
  });
  check("saved session hydrates sessionStorage", hydrated.session_token === "guide-token", JSON.stringify(hydrated));
  check("classify-turn carries Bearer token", valid.seen.classifyAuth === "Bearer guide-token", valid.seen.classifyAuth);
  check("LLM run carries Bearer token", valid.seen.runAuth === "Bearer guide-token", valid.seen.runAuth);
  check("LLM run uses saved user id", valid.seen.runBody && valid.seen.runBody.user_id === "guide-user", JSON.stringify(valid.seen.runBody));
  check("Guide selected brain reaches run recipe", valid.seen.runBody?.recipe?.model?.primary === "openai/gpt-oss-120b", JSON.stringify(valid.seen.runBody?.recipe?.model || {}));
  check("Guide selected brain base_url reaches run recipe", valid.seen.runBody?.recipe?.model?.base_url === "https://api.groq.com/openai/v1", JSON.stringify(valid.seen.runBody?.recipe?.model || {}));
  check("model response is rendered", (await valid.page.locator("body").innerText()).includes("ola desde GPT-OSS 120B"));
  check("valid run does not show no_session", !(await valid.page.locator("body").innerText()).includes("no_session"));
  await valid.context.close();

  const rejected = await openGuide(
    browser,
    base,
    { id: "guide-user", email: "guide@example.test", session_token: "bad-token" },
    async (route) => {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: { error: "no_session", detail: "Esta accion necesita tu sesion. Inicia sesion." } }),
      });
    }
  );
  await rejected.page.fill("#composer", "ola");
  await rejected.page.press("#composer", "Enter");
  await rejected.page.waitForFunction(() => document.body.innerText.includes("Esta accion necesita tu sesion"), { timeout: 10_000 });
  const rejectedText = await rejected.page.locator("body").innerText();
  check("backend no_session remains visible", rejectedText.includes("Esta accion necesita tu sesion"));
  check("no_session is not replaced by fallback chat", !rejectedText.includes("Adelante"));
  check("rejected run still sent claimed Bearer token for backend resolution", rejected.seen.runAuth === "Bearer bad-token", rejected.seen.runAuth);
  await rejected.context.close();
} catch (e) {
  failures.push(e && e.stack ? e.stack : String(e));
} finally {
  await browser.close();
  await new Promise((resolveClose) => server.close(resolveClose));
}

console.log("");
if (!failures.length) {
  console.log("RESULT: GREEN -- Guide brain/session path is wired to LLM requests");
  process.exit(0);
}

console.log(`RESULT: RED (${failures.length})`);
for (const failure of failures) console.log(" - " + failure);
process.exit(1);
