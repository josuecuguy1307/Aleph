#!/usr/bin/env node
/* Focused regression for the shared brain setup workflow. */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" };
const failures = [];
const check = (condition, label, detail = "") => {
  console.log(`${condition ? "OK" : "FAIL"} ${label}${detail ? " -- " + detail : ""}`);
  if (!condition) failures.push(label + (detail ? " -- " + detail : ""));
};

async function startServer() {
  const server = createServer(async (req, res) => {
    try {
      const pathname = decodeURIComponent(new URL(req.url || "/", "http://local").pathname);
      const file = resolve(ROOT, "." + (pathname === "/" ? "/brain-setup.html" : pathname));
      if (!file.startsWith(ROOT)) throw new Error("outside root");
      const body = await readFile(file);
      res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
      res.end(body);
    } catch {
      res.writeHead(404);
      res.end("not found");
    }
  });
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  return server;
}

function installRoutes(page, state) {
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  return Promise.all([
    page.route("**/v1/**", (route) => json(route, {})),
    page.route("**/v1/users/**", (route) => json(route, { puppets: [], docs: [] })),
    page.route("**/v1/brains/status**", (route) => json(route, {
      service: { state: "ready", mode: "managed", managed: true },
      providers: {
        included: { state: "ready", detail: "ruta incluida saludable" },
        claude_cli: { state: "ready", detail: "sesión activa" },
        codex_cli: { state: "ready", detail: "sesión activa" },
      },
    })),
    page.route("**/v1/users/**/keys", (route) => json(route, { keys: state.keys })),
    page.route("**/v1/keys", async (route) => {
      const body = JSON.parse(route.request().postData() || "{}");
      state.keyPost = { body, authorization: route.request().headers().authorization || "" };
      state.keys = [{ provider: body.provider, last4: "test", verified: true }];
      await json(route, { stored: true });
    }),
    page.route("**/v1/sessions/**", (route) => json(route, { artifacts: [] })),
    page.route("**/v1/belts/**", (route) => json(route, { cards: [] })),
    page.route("**/v1/chats/**", (route) => json(route, { chats: [], messages: [] })),
    page.route("**/v1/recipes/validate", (route) => json(route, { valid: true, errors: [] })),
  ]);
}

async function newPage(browser, state) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, reducedMotion: "reduce" });
  await context.addInitScript(() => {
    const user = { id: "brain-user", email: "brain@example.test", session_token: "brain-token" };
    sessionStorage.setItem("puppet_user", JSON.stringify(user));
    localStorage.setItem("puppet_user", JSON.stringify(user));
    localStorage.setItem("aleph-lang", "es");
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error" && !/Failed to load resource|favicon/i.test(message.text())) errors.push(message.text());
  });
  await installRoutes(page, state);
  return { context, page, errors };
}

const server = await startServer();
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();

try {
  const apiState = { keys: [] };
  const api = await newPage(browser, apiState);
  await api.page.goto(base + "/brain-setup.html?return=%2Fsala%2Fsala.html%3Fpuppet%3Dwrong", { waitUntil: "domcontentloaded" });
  await api.page.selectOption("#apiProvider", "groq");
  await api.page.selectOption("#apiModel", "openai/gpt-oss-120b");
  await api.page.fill("#apiSecret", "groq-test-secret");
  await api.page.click("#save");
  await api.page.waitForURL(/\/sala\/sala\.html$/, { timeout: 15_000 });
  await api.page.waitForFunction(() => window.__salaSliceD?.state?.().ready && window.__salaSliceD.state().power === "tuapi", null, { timeout: 15_000 });
  const apiResult = await api.page.evaluate(() => ({
    config: window.AlephBrain.getConfiguration(),
    recipe: window.__salaSliceD.recipe(),
    state: window.__salaSliceD.state(),
  }));
  check(apiState.keyPost?.body?.provider === "groq" && apiState.keyPost?.body?.secret === "groq-test-secret", "API key is stored for the chosen provider", JSON.stringify(apiState.keyPost?.body));
  check(apiState.keyPost?.authorization === "Bearer brain-token", "API key save carries the session token", apiState.keyPost?.authorization || "");
  check(apiResult.config?.mode === "api" && apiResult.config?.provider === "groq" && apiResult.config?.model === "openai/gpt-oss-120b" && !Object.hasOwn(apiResult.config || {}, "secret"), "API brain configuration persists without the secret", JSON.stringify(apiResult.config));
  check(apiResult.state.power === "tuapi" && apiResult.recipe?.model?.primary === "openai/gpt-oss-120b" && apiResult.recipe?.model?.base_url === "https://api.groq.com/openai/v1" && apiResult.recipe?.model?.byok_ref === "keys:groq", "Sala restores the API brain into the executable recipe", JSON.stringify(apiResult.recipe?.model));
  check(!api.page.url().includes("puppet"), "setup return drops legacy puppet redirects", api.page.url());
  check(api.errors.length === 0, "API setup path has no JavaScript errors", api.errors.slice(0, 2).join(" | "));
  await api.context.close();

  const cliState = { keys: [] };
  const cli = await newPage(browser, cliState);
  await cli.page.goto(base + "/brain-setup.html?mode=cli&brain=codex_cli&return=%2Fcuarto%2Fcuarto.pixi.html", { waitUntil: "domcontentloaded" });
  await cli.page.selectOption("#cliModel", "gpt-5.1-codex");
  await cli.page.click("#save");
  await cli.page.waitForURL(/\/cuarto\/cuarto\.pixi\.html$/, { timeout: 15_000 });
  await cli.page.waitForFunction(() => window.__cuarto && window.__models && window.__recipeMod, null, { timeout: 15_000 });
  const cliResult = await cli.page.evaluate(() => {
    const d = window.__cuarto.nucleoData();
    const recipe = window.__recipeMod.tilesToRecipe(window.__cuarto.placedTiles(), d);
    return { config: window.AlephBrain.getConfiguration(), model: d.model, cliModel: d._cliModel, recipe: recipe.model };
  });
  check(cliResult.config?.mode === "cli" && cliResult.config?.id === "codex_cli" && cliResult.config?.cliModel === "gpt-5.1-codex", "CLI brain configuration persists", JSON.stringify(cliResult.config));
  check(cliResult.model === "codex_cli" && cliResult.cliModel === "gpt-5.1-codex" && cliResult.recipe?.brain_provider === "codex_cli" && cliResult.recipe?.cli_model === "gpt-5.1-codex", "Cuarto restores the CLI brain into the executable recipe", JSON.stringify(cliResult));
  check(cli.errors.length === 0, "CLI setup path has no JavaScript errors", cli.errors.slice(0, 2).join(" | "));
  await cli.context.close();
} catch (error) {
  failures.push(error?.stack || String(error));
} finally {
  await browser.close();
  await new Promise((done) => server.close(done));
}

console.log(failures.length ? `RESULT: RED (${failures.length})\n - ${failures.join("\n - ")}` : "RESULT: GREEN -- shared brain setup persists and restores");
process.exit(failures.length ? 1 : 0);
