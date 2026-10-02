#!/usr/bin/env node
/**
 * Regression browser test for agent deletion on Agentes.dc.html.
 * The fixture API stores its rows outside the page, so reload verifies persistence rather
 * than merely checking that the component optimistically removed a card.
 */
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const serverCode = "import http.server,sys; from functools import partial; s=http.server.ThreadingHTTPServer(('127.0.0.1',0),partial(http.server.SimpleHTTPRequestHandler,directory=sys.argv[1])); print(s.server_address[1],flush=True); s.serve_forever()";
const server = spawn("python3", ["-u", "-c", serverCode, HERE], { stdio: ["ignore", "pipe", "inherit"] });
const port = await new Promise((resolve, reject) => {
  let output = "";
  server.stdout.setEncoding("utf8");
  server.stdout.on("data", (chunk) => {
    output += chunk;
    const line = output.split(/\r?\n/, 1)[0].trim();
    if (/^\d+$/.test(line)) resolve(Number(line));
  });
  server.once("error", reject);
  server.once("exit", (code) => reject(new Error(`Agentes test server exited before bind (${code}): ${output}`)));
});

let records = [
  { id: "11111111-1111-4111-8111-111111111111", name: "Local Agent", status: "active", usado_at: null,
    config: { belt: { tool_filters: { calc: ["add"] } } } },
  { id: "22222222-2222-4222-8222-222222222222", name: "Synced Agent", status: "draft", usado_at: null,
    config: { belt: { tool_filters: { research: ["search"] } } },
  },
];
let failNextDelete = false;
let holdNextDeleteResponse = false;
let releaseHeldDelete = null;
let signalDeleteRequest = null;
const calls = [];
const errors = [];
let browser;

try {
  browser = await chromium.launch(process.env.ALEPH_CHROMIUM_PATH
    ? { executablePath: process.env.ALEPH_CHROMIUM_PATH } : {});
  const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  await context.addInitScript(() => {
    localStorage.setItem("aleph-lang", "es");
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "agent-delete-fixture", session_token: "fixture-token" }));
  });
  await context.route("**/v1/**", async (route) => {
    const req = route.request(), url = new URL(req.url()), method = req.method();
    calls.push(`${method} ${url.pathname}`);
    if (method === "GET" && url.pathname === "/v1/users/agent-delete-fixture/puppets") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ puppets: records }) });
    }
    const del = url.pathname.match(/^\/v1\/puppets\/([^/]+)$/);
    if (method === "DELETE" && del) {
      if (signalDeleteRequest) { const signal = signalDeleteRequest; signalDeleteRequest = null; signal(); }
      if (failNextDelete) {
        failNextDelete = false;
        return route.fulfill({ status: 503, contentType: "application/json",
          body: JSON.stringify({ detail: { error: "agent_delete_failed", detail: "No se pudo eliminar." } }) });
      }
      records = records.filter((agent) => agent.id !== decodeURIComponent(del[1]));
      if (holdNextDeleteResponse) {
        await new Promise((resolve) => { releaseHeldDelete = resolve; });
        holdNextDeleteResponse = false;
      }
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ deleted: true, id: decodeURIComponent(del[1]) }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });

  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  const base = `http://127.0.0.1:${port}`;
  const url = `${base}/Agentes.dc.html`;
  const check = (ok, name, detail = "") => {
    console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
    if (!ok) errors.push(name);
  };
  const deleteButton = (row) => row.locator("button.ag-delete");
  const rows = () => page.locator(".ag-fila");
  const totalCount = () => page.locator(".ag-filtro .n").first().innerText();

  await page.goto(url, { waitUntil: "load" });
  await page.locator(".ag-fila").first().waitFor({ state: "visible", timeout: 30000 });
  check(await rows().count() === 2, "carga ambos agentes persistidos (fixture local y sincronizado)");

  const search = page.locator(".ag-buscar input");
  await search.fill("Local");
  const localRow = page.locator(".ag-fila").filter({ hasText: "Local Agent" });
  let dialogText = "";
  page.once("dialog", async (dialog) => { dialogText = dialog.message(); await dialog.dismiss(); });
  await deleteButton(localRow).click();
  check(/Eliminar este agente/.test(dialogText), "cancel · se pide confirmación antes de borrar", dialogText);
  check(records.length === 2 && await rows().count() === 1 && await search.inputValue() === "Local"
    && await totalCount() === "2" && !calls.some((c) => c.startsWith("DELETE ")),
    "cancel · no muta API, contador ni búsqueda/filtro");

  holdNextDeleteResponse = true;
  const deleteRequest = new Promise((resolve) => { signalDeleteRequest = resolve; });
  page.once("dialog", async (dialog) => { dialogText = dialog.message(); await dialog.accept(); });
  await deleteButton(localRow).click();
  await deleteRequest;
  await page.waitForFunction(() => !document.body.innerText.includes("Local Agent"));
  const allFilterSelected = await page.locator(".ag-filtro").first().evaluate((el) => el.classList.contains("on"));
  check(records.length === 1 && await totalCount() === "1" && await search.inputValue() === "Local"
    && allFilterSelected,
    "success · contador y lista se actualizan antes de la respuesta, conserva búsqueda/filtro");
  if (releaseHeldDelete) { releaseHeldDelete(); releaseHeldDelete = null; }
  await page.waitForFunction(() => !document.querySelector(".ag-delete[disabled]"));
  check(calls.includes("DELETE /v1/puppets/11111111-1111-4111-8111-111111111111"),
    "success · usa DELETE del agente persistido, no solo estado de pantalla");

  await page.reload({ waitUntil: "load" });
  await page.locator(".ag-fila").first().waitFor({ state: "visible", timeout: 30000 });
  check(await rows().count() === 1 && await page.locator(".ag-fila").innerText().then((s) => s.includes("Synced Agent"))
    && records.every((a) => a.name !== "Local Agent"), "persistence · tras reload el agente borrado sigue ausente");

  await search.fill("Synced");
  failNextDelete = true;
  const syncedRow = page.locator(".ag-fila").filter({ hasText: "Synced Agent" });
  page.once("dialog", async (dialog) => { await dialog.accept(); });
  await deleteButton(syncedRow).click();
  await page.locator(".ag-delete-error[role=alert]").waitFor({ state: "visible" });
  const filterPreservedAfterError = await page.locator(".ag-filtro").first().evaluate((el) => el.classList.contains("on"));
  check(records.length === 1 && await rows().count() === 1 && await search.inputValue() === "Synced"
    && filterPreservedAfterError && /No se pudo eliminar el agente/.test(await page.locator(".ag-delete-error").innerText()),
    "failure · restaura tarjeta, conserva búsqueda y muestra error legible");

  page.once("dialog", async (dialog) => { await dialog.accept(); });
  await deleteButton(syncedRow).click();
  await page.waitForFunction(() => !document.body.innerText.includes("Synced Agent"));
  await page.reload({ waitUntil: "load" });
  await page.locator(".ds-well").waitFor({ state: "visible", timeout: 30000 });
  await page.locator(".ag-delete-error").waitFor({ state: "hidden" }).catch(() => {});
  check(records.length === 0 && await rows().count() === 0,
    "synced account · retry succeeds and remains deleted after reload");
  check(errors.length === 0, "sin excepciones JavaScript", errors.slice(0, 2).join(" | "));
  await context.close();
} finally {
  if (browser) await browser.close();
  server.kill();
}

const failed = errors.length > 0;
console.log(`\n${failed ? "ROJO" : "VERDE"} — ${failed ? "regression test failed" : "agent deletion scenarios pass"}`);
process.exit(failed ? 1 : 0);
