#!/usr/bin/env node
/* Vara WebKit específica: tools reales del Guía + proceso persistente por etapas. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { webkit } from "playwright";
import { join, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..");
const DESIGN = resolve(ROOT, "product/app/design");
const PORT = Number(process.env.FRONT_PORT || 8305);
const SIDECAR = String(process.env.SIDECAR_BIN || "").trim();
if (PORT === 25374) throw new Error(":25374 está prohibido");
const pageUrl = `http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html`;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const J = JSON.stringify;

let localCalls = 0;
let registryCalls = 0;
const clean = {
  id: "com.acme/mail", nombre: "Correo", tipo: "remoto",
  descripcion_1linea: { es: "Consultá correo.", en: "Read email." },
  official: true, confianza: 0.91,
  checklist: { es: ["Revisá permisos."], en: ["Review permissions."] },
  fuente: "https://registry.modelcontextprotocol.io/v0/servers?search=com.acme%2Fmail",
};
const sse = [
  { etapa: "leyendo" },
  { etapa: "limpiando", cantidad: 1 },
  { etapa: "clasificando", tipos: { remoto: 1 } },
  { etapa: "veredicto", ok: true, agregadas: 1, entradas: [clean] },
].map((event) => `data: ${J(event)}\n\n`).join("");

const sandbox = SIDECAR ? mkdtempSync(join(tmpdir(), "aleph-catalogos-guia-")) : "";
const server = SIDECAR
  ? spawn(SIDECAR, ["--port", String(PORT)], {
      detached: true,
      env: {
        ...process.env,
        ALEPH_ROLE: "client",
        ALEPH_DATA_DIR: join(sandbox, "data"),
        TMPDIR: sandbox,
        PUPPET_PORT: String(PORT),
        PORT: String(PORT),
      },
      stdio: "ignore",
    })
  : spawn(
      "python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"],
      { cwd: DESIGN, stdio: "ignore" },
    );
let browser;
try {
  if (SIDECAR) {
    let ready = false;
    for (let attempt = 0; attempt < 180; attempt++) {
      try {
        const response = await fetch(`http://127.0.0.1:${PORT}/health`);
        if (response.ok) { ready = true; break; }
      } catch {}
      await sleep(350);
    }
    assert.ok(ready, "el frozen no respondió /health");
  } else {
    await sleep(700);
  }
  browser = await webkit.launch();
  const page = await (await browser.newContext()).newPage();
  await page.route("**/v1/**", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: "[]",
  }));
  await page.route("**/v1/atoms/catalog**", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: J({ atoms: [], total: 0 }),
  }));
  await page.route("**/v1/brains/status**", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: J({ providers: { claude_cli: { state: "ready" } } }),
  }));
  await page.route("**/v1/catalog/local**", (route) => {
    localCalls++;
    route.fulfill({
      status: 200, contentType: "application/json",
      body: J({ items: [clean], total: 1 }),
    });
  });
  await page.route("**/v1/catalog/ingest", (route) => {
    registryCalls++;
    route.fulfill({ status: 200, contentType: "text/event-stream", body: sse });
  });
  await page.route("**/v1/cuarto/guide", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: J({ content: "Listo.", tool_calls: [] }),
  }));

  await page.goto(pageUrl, { waitUntil: "load" });
  await page.waitForFunction(() => window.__guide && window.__guideHost && window.__guiaQ);
  await page.evaluate(() => document.getElementById("copBtn")?.click());
  await page.waitForFunction(() => window.__guiaQ("#messages"));

  await page.evaluate(() => window.__guide.send("poneme las que ya tengo"));
  assert.equal(localCalls, 1);
  assert.equal(registryCalls, 0, "el pedido local no toca el registro");

  await page.evaluate(() => window.__guide.send("buscá en el registro correo"));
  assert.equal(registryCalls, 1, "la tool de registro dispara ingesta");
  const visible = await page.evaluate(
    () => window.__guiaQ("#messages").textContent.toLowerCase(),
  );
  const indexes = ["leyendo", "limpiando", "clasificando", "veredicto"]
    .map((stage) => visible.indexOf(stage));
  assert.ok(indexes.every((index) => index >= 0), visible);
  assert.ok(indexes.every((index, i) => i === 0 || index > indexes[i - 1]), indexes);
  assert.doesNotMatch(visible, /buscar_(?:catalogo_local|registro)/u);
  console.log(
    `VERDE · WebKit ${SIDECAR ? "frozen " : ""}:`
      + `${PORT} · local=${localCalls} registro=${registryCalls} · `
      + "leyendo → limpiando → clasificando → veredicto visibles",
  );
} finally {
  try { await browser?.close(); } catch {}
  try {
    if (SIDECAR) process.kill(-server.pid, "SIGKILL");
    else server.kill();
  } catch {}
  if (sandbox) rmSync(sandbox, { recursive: true, force: true });
}
