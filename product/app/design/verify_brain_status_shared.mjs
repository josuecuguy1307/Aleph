#!/usr/bin/env node
/**
 * verify_brain_status_shared.mjs — Slice B · contrato compartido de cerebro desktop.
 *
 * Prueba:
 * - none / included / BYOK / Claude / Codex / saved recipe unavailable;
 * - Home, Cuarto, Sala, Conectar y Settings montan el mismo indicador;
 * - la acción de gestión navega al setup común.
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = path.resolve(new URL(".", import.meta.url).pathname);
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };
const fails = [];
const ok = (c, label, extra = "") => { console.log(`${c ? "  ✓" : "  ✗"} ${label}${!c && extra ? " — " + extra : ""}`); if (!c) fails.push(label); };

function serve() {
  const srv = http.createServer((req, res) => {
    const u = new URL(req.url, "http://x");
    if (u.pathname === "/__brain_fixture.html") {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(`<!doctype html><meta charset="utf-8"><script src="/brain-status.js"></script><div id="t"></div>`);
      return;
    }
    const p = path.join(DESIGN, decodeURIComponent(u.pathname));
    if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end("nf"); return; }
    res.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
    fs.createReadStream(p).pipe(res);
  });
  return new Promise((resolve) => srv.listen(0, "127.0.0.1", () => resolve(srv)));
}

const state = {
  service: { state: "ready", mode: "managed", managed: true, detail: "servicio CLI administrado por Aleph" },
  providers: {
    included: { provider: "included", state: "ready", detail: "lane incluida configurada" },
    claude_cli: { provider: "claude_cli", state: "ready", detail: "sesión activa", extra: { subscriptionType: "max" } },
    codex_cli: { provider: "codex_cli", state: "not_installed", detail: "no encontré codex" },
  },
  keys: [],
};

async function wire(page) {
  const j = (r, json) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(json) });
  await page.route("**/v1/**", (r) => j(r, {}));
  await page.route("**/v1/brains/status**", (r) => j(r, { providers: state.providers, service: state.service }));
  await page.route("**/v1/users/*/keys", (r) => j(r, { keys: state.keys }));
  await page.route("**/v1/users/*/puppets", (r) => j(r, { puppets: [{ id: "p-cli", name: "CLI roto", config: { meta: {}, belt: { belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json" }, model: { brain_provider: "claude_cli" } } }] }));
  await page.route("**/v1/connectors", (r) => j(r, { connectors: [{ connector: "github", auth_method: "personal_token", capability_line: "repos" }], total: 1 }));
  await page.route("**/v1/connectors/**", (r) => j(r, { connector: "github", auth_method: "personal_token", credential_fields: [], steps: [] }));
  await page.route("**/v1/belts/cards*", (r) => j(r, { cards: [{ id: "calc", label: "Calculadora", tools: ["add"], state: "ready" }], total: 1, dropped: [] }));
  await page.route("**/v1/sessions/**", (r) => j(r, { artifacts: [] }));
  await page.route("**/v1/chats*", (r) => j(r, { total: 0, chats: [] }));
  await page.route("**/v1/chats/**", (r) => j(r, { id: "chat-fx", messages: [] }));
  await page.route("**/v1/payments/status", (r) => j(r, { ok: true }));
  await page.route("**/v1/auth/login", (r) => j(r, { id: "u1", email: "u@x", session_token: "tok" }));
}

const srv = await serve();
const base = `http://127.0.0.1:${srv.address().port}`;
const browser = await chromium.launch();

async function newPage() {
  const ctx = await browser.newContext({ viewport: { width: 1380, height: 900 }, reducedMotion: "reduce" });
  await ctx.addInitScript(() => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", email: "u@x", session_token: "tok" }));
    localStorage.setItem("aleph-lang", "es");
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/favicon|Failed to load resource/i.test(m.text())) errors.push(m.text()); });
  await wire(page);
  page.__errors = errors;
  page.__ctx = ctx;
  return page;
}

try {
  console.log("══ contrato resolve() ══");
  let page = await newPage();
  await page.goto(base + "/__brain_fixture.html");
  await page.waitForFunction(() => !!window.AlephBrain);

  let s = await page.evaluate(() => AlephBrain.resolve({ selected: "none" }));
  ok(s.active === "none" && s.state === "not_configured" && s.blockExecution, "no brain configured → bloquea");

  state.providers.included = { provider: "included", state: "ready", detail: "ok" };
  s = await page.evaluate(() => AlephBrain.resolve({ selected: "included", refresh: true }));
  ok(s.active === "included" && s.state === "healthy" && !s.blockExecution, "included healthy → conectado");

  state.keys = [{ provider: "anthropic", last4: "1234", verified: true }];
  s = await page.evaluate(() => AlephBrain.resolve({ selected: { active: "byok", id: "byok", provider: "anthropic", label: "Anthropic · BYOK" }, refresh: true }));
  ok(s.active === "byok" && s.state === "healthy" && !s.blockExecution, "BYOK configurado → healthy");
  s = await page.evaluate(() => AlephBrain.resolve({ selected: { active: "byok", id: "byok", provider: "openai", label: "OpenAI · BYOK" }, refresh: true }));
  ok(s.active === "byok" && s.state === "not_configured" && s.blockExecution, "BYOK faltante → bloquea");

  state.providers.claude_cli = { provider: "claude_cli", state: "ready", detail: "sesión activa" };
  s = await page.evaluate(() => AlephBrain.resolve({ selected: "claude_cli", refresh: true }));
  ok(s.active === "claude_cli" && s.state === "healthy", "Claude Code conectado");
  state.service = { state: "unavailable", mode: "failed", managed: false, detail: "puerto ocupado" };
  s = await page.evaluate(() => AlephBrain.resolve({ selected: "claude_cli", refresh: true }));
  ok(s.active === "claude_cli" && s.state === "unavailable" && s.blockExecution && /ocupado/.test(s.detail),
    "CLI autenticado + servicio caído → NO finge conectado y bloquea");
  state.service = { state: "ready", mode: "managed", managed: true, detail: "servicio CLI administrado por Aleph" };
  state.providers.claude_cli = { provider: "claude_cli", state: "no_auth", detail: "sin sesión" };
  s = await page.evaluate(() => AlephBrain.resolve({ selected: "claude_cli", refresh: true }));
  ok(s.active === "claude_cli" && s.state === "unavailable" && s.blockExecution, "Claude Code no disponible → bloquea");

  state.providers.codex_cli = { provider: "codex_cli", state: "ready", detail: "sesión activa" };
  s = await page.evaluate(() => AlephBrain.resolve({ selected: "codex_cli", refresh: true }));
  ok(s.active === "codex_cli" && s.state === "healthy", "Codex conectado");
  state.providers.codex_cli = { provider: "codex_cli", state: "not_installed", detail: "no instalado" };
  s = await page.evaluate(() => AlephBrain.resolve({ selected: "codex_cli", refresh: true }));
  ok(s.active === "codex_cli" && s.state === "unavailable" && s.blockExecution, "Codex no disponible → bloquea");

  s = await page.evaluate(() => AlephBrain.resolve({ recipe: { model: { brain_provider: "claude_cli" } }, refresh: true }));
  ok(s.active === "claude_cli" && s.state === "unavailable" && s.blockExecution, "receta guardada con Claude no disponible → no finge conectado");

  await page.evaluate(() => AlephBrain.mount("#t", { context: { selected: "claude_cli", refresh: true } }));
  await page.waitForSelector("#t .aleph-brain-action");
  await page.click("#t .aleph-brain-action");
  ok(/brain-setup\.html/.test(page.url()) && /mode=cli/.test(page.url()) && /brain=claude_cli/.test(page.url())
    && /return=%2Fcuarto%2Fcuarto\.pixi\.html/.test(page.url()), "acción CLI navega al setup común canónico");
  ok(page.__errors.length === 0, "contrato sin errores JS", page.__errors.slice(0, 2).join(" | "));
  await page.__ctx.close();

  console.log("══ superficies compartidas ══");
  state.providers = {
    included: { provider: "included", state: "ready", detail: "lane incluida configurada" },
    claude_cli: { provider: "claude_cli", state: "no_auth", detail: "sin sesión" },
    codex_cli: { provider: "codex_cli", state: "not_installed", detail: "no instalado" },
  };
  state.keys = [];
  for (const [name, url, expect] of [
    ["Home", "/Home.dc.html", /Incluido|conectado/],
    ["Cuarto", "/Cuarto.dc.html", /Incluido|conectado/],
    ["Conectar", "/Conectar.dc.html", /Incluido|conectado/],
    ["Settings", "/Settings.dc.html", /Incluido|conectado/],
    ["La Sala saved unavailable", "/sala/sala.html?puppet=p-cli", /Claude Code|no disponible|sin sesión/],
  ]) {
    page = await newPage();
    await page.goto(base + url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".aleph-brain", { timeout: 15000 });
    const txt = await page.locator(".aleph-brain").first().textContent();
    ok(expect.test(txt || ""), `${name} muestra indicador compartido`, txt || "");
    ok(page.__errors.length === 0, `${name} sin errores JS`, page.__errors.slice(0, 2).join(" | "));
    await page.__ctx.close();
  }
} finally {
  await browser.close();
  srv.close();
}

console.log(fails.length ? `\n✗ ${fails.length} falla(s): ${fails.join(" · ")}` : "\n✓ verify_brain_status_shared: TODO VERDE");
process.exit(fails.length ? 1 : 0);
