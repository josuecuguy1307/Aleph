/* verify_resolver_pick.mjs — PR-3 · RESOLVER-AL-ELEGIR + CONSTRUÍ UN MCP (widget vivo · doble llave).
 * El catálogo (#reg) deja de conectar a ciegas: al ELEGIR un conector del registro, valida
 * anti-impostor vía GET /v1/catalog/validate y muestra un GATE de confianza. Y cuando el registro
 * NO conoce el servicio (miss legítimo, registry_status:"ok"), ofrece una card VISIBLE para construir
 * un MCP. Verifica:
 *   (a) < 2 chars → panel oculto.
 *   (b) "stripe" → 2 filas (oficial + impostor comunitario con nombre parecido).
 *   (c) elegir el OFICIAL → confiable + picked_is_trusted → conecta directo (#intent = server confiable,
 *       panel cierra, SIN gate).
 *   (d) elegir el IMPOSTOR → gate ⚠ "no el que elegiste" + [conectar el verificado] → #intent = el
 *       server OFICIAL (com.stripe/mcp), no el impostor.
 *   (e) "community" (dudoso) → gate ⚠ "conecta bajo tu criterio"; [cancelar] no conecta; [conectar igual] sí.
 *   (f) "nadaxyz" (registro OK, cero resultados) → card "construye un MCP" → click → construye (#intent = query).
 *   (g) "valdown" → validate registry_status:"unreachable" → gate ⚠ "no puedo validar, reintentá" + NO conecta.
 *   (h) 0 errores JS/render.
 * Puerto :8155. /v1/atoms/catalog · /v1/catalog/search · /v1/catalog/validate MOCKEADOS. inspect no-op.
 * Run:  node verify_resolver_pick.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = 8155;
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`); if (!c) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const CATALOG = { total: 3, by_zone: {}, atoms: [
  { id: "gmail", label: "Gmail", atom: "conexion", server: "gmail", zone: "entrega", auth: "oauth", connector: "gmail" },
  { id: "exa",   label: "Exa",   atom: "tool",     server: "exa",   zone: "fuentes", auth: "keyless" },
  { id: "yf",    label: "Yahoo Finance", atom: "tool", server: "yfinance", zone: "fuentes", auth: "keyless" },
] };

const badge = (kind, label, verified) => ({ kind, label, verified });
const regRow = (id, name, b) => ({ id, name, description: "d", source: "registry", server_name: id, badge: b });

function searchResponse(q) {
  const base = { query: q, source: "all", registry_status: "ok", notice: null };
  if (q === "nadaxyz") return { ...base, counts: { internal: 0, registry: 0, total: 0 }, items: [] };
  if (q === "stripe") return { ...base, counts: { internal: 0, registry: 2, total: 2 }, items: [
    regRow("com.stripe/mcp", "Stripe", badge("official_dns", "✓ oficial (com.stripe)", true)),
    regRow("io.github.evil/stripe-mcp", "Stripe (comunidad)", badge("community_unverified", "⚠ community · no verificado", false)),
  ] };
  if (q === "community") return { ...base, counts: { internal: 0, registry: 1, total: 1 }, items: [
    regRow("io.github.rando/notas", "Notas", badge("community_unverified", "⚠ community · no verificado", false)),
  ] };
  if (q === "valdown") return { ...base, counts: { internal: 0, registry: 1, total: 1 }, items: [
    regRow("io.unknown/x", "X server", badge("community_unverified", "⚠ community · no verificado", false)),
  ] };
  return { ...base, counts: { internal: 0, registry: 0, total: 0 }, items: [] };
}

function validateResponse(service, picked) {
  if (service === "stripe") {
    const trusted = "com.stripe/mcp";
    const isTrusted = picked === trusted;
    return { service, verdict: "confiable", registry_status: "ok", server_name: trusted,
      vendor_kind: "dns", verified: true, score: 0.97, reason: "vendor verificado", ranked: [],
      picked, picked_is_trusted: isTrusted,
      message: isTrusted ? "verificado como oficial — puedes conectar tranquilo."
        : `ojo: el conector oficial verificado es «${trusted}», distinto del que elegiste. Conecta el verificado.` };
  }
  if (service === "community") {
    return { service, verdict: "dudoso", registry_status: "ok", server_name: null,
      vendor_kind: null, verified: false, score: 0.5, reason: "sin ownership verificado", ranked: [{ name: "io.github.rando/notas" }],
      picked, picked_is_trusted: false,
      message: "no está verificado como oficial (sin prueba de dueño). Conecta sólo si confías en la fuente." };
  }
  if (service === "valdown") {
    return { service, verdict: null, registry_status: "unreachable", server_name: null,
      vendor_kind: null, verified: false, score: null, reason: "registro inalcanzable", ranked: [],
      picked, picked_is_trusted: false, retry: true,
      message: "no puedo validar ahora — el catálogo público no responde. Reintenta ↻" };
  }
  // nada
  return { service, verdict: "nada", registry_status: "ok", server_name: null, vendor_kind: null,
    verified: false, score: null, reason: "el registro no conoce ese servicio", ranked: [],
    picked, picked_is_trusted: null,
    message: "el registro no conoce este servicio. Puedes construir un MCP desde tu API o tus docs." };
}

const rowByName = (name) => `[...document.querySelectorAll(".regRow")].find(r => r.querySelector(".regLabel")?.textContent === ${JSON.stringify(name)})`;

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);
const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1400, height: 860 }, deviceScaleFactor: 1 });
  await context.addInitScript(() => { try { localStorage.setItem("aleph-lang", "es"); localStorage.setItem("aleph-theme", "dark"); } catch (e) {} });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/v1/**", (r) => {
    const url = r.request().url();
    if (url.includes("/v1/atoms/catalog"))
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CATALOG) });
    if (url.includes("/v1/catalog/search")) {
      const q = (new URL(url).searchParams.get("q") || "").toLowerCase();
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(searchResponse(q)) });
    }
    if (url.includes("/v1/catalog/validate")) {
      const u = new URL(url);
      const svc = (u.searchParams.get("service") || "").toLowerCase();
      const picked = u.searchParams.get("server_name") || "";
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(validateResponse(svc, picked)) });
    }
    return r.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__atoms && window.__atoms.list.length >= 3, null, { timeout: 12000 });
  // inspect no-op (aísla del Motor B): el pick fija #intent + dispara inspect; acá cortamos ese click
  // y CONTAMOS cuántas veces se disparó — así distinguimos "conectó" (inspect++) de "canceló" (igual).
  await page.evaluate(() => { window.__inspectClicks = 0; document.getElementById("inspect")
    .addEventListener("click", (e) => { e.stopImmediatePropagation(); e.preventDefault(); window.__inspectClicks++; }, true); });
  const inspectClicks = () => page.evaluate(() => window.__inspectClicks);

  const clickRow = async (name) => page.evaluate((sel) => { const el = eval(sel); el && el.dispatchEvent(new MouseEvent("click", { bubbles: true })); }, rowByName(name));
  const clickBtn = async (attr) => page.evaluate((a) => { const b = document.querySelector(`#registryList [${a}]`); b && b.dispatchEvent(new MouseEvent("click", { bubbles: true })); }, attr);
  const gateText = () => page.evaluate(() => document.querySelector("#registryList .regConfirm")?.textContent || "");
  const intentVal = () => page.evaluate(() => document.getElementById("intent").value);
  const panelHidden = () => page.evaluate(() => document.getElementById("registryPanel").hidden);
  const doSearch = async (q) => { await page.fill("#intent", q); await page.waitForFunction(() => !document.getElementById("registryPanel").hidden, null, { timeout: 5000 }); await sleep(120); };

  // ── (a) < 2 chars → panel oculto ──
  await page.fill("#intent", "s"); await sleep(400);
  ok(await panelHidden() === true, "(a) 1 char → panel OCULTO");

  // ── (b) "stripe" → 2 filas ──
  await doSearch("stripe");
  const nRows = await page.evaluate(() => document.querySelectorAll(".regRow").length);
  ok(nRows === 2, "(b) 'stripe' → 2 filas (oficial + impostor)", `n=${nRows}`);

  // ── (c) elegir el OFICIAL → conecta directo (sin gate) ──
  await clickRow("Stripe");
  await page.waitForFunction(() => document.getElementById("registryPanel").hidden, null, { timeout: 5000 });
  ok(await intentVal() === "com.stripe/mcp" && await panelHidden(),
     "(c) pick OFICIAL → confiable+propio → conecta directo (#intent=server confiable, sin gate)", `intent=${await intentVal()}`);

  // ── (d) elegir el IMPOSTOR → gate ⚠ → [conectar el verificado] fija el OFICIAL ──
  await doSearch("stripe");
  await clickRow("Stripe (comunidad)");
  await page.waitForFunction(() => document.querySelector("#registryList .regConfirm.warn"), null, { timeout: 5000 });
  const dGate = await gateText();
  ok(/no el que elegiste|distinto/i.test(dGate), "(d1) impostor → gate ⚠ 'no el que elegiste'", JSON.stringify(dGate.slice(0, 60)));
  const hasVerified = await page.evaluate(() => !!document.querySelector("#registryList [data-cconnect]"));
  ok(hasVerified, "(d2) el gate ofrece [conectar el verificado]");
  await clickBtn("data-cconnect");
  await page.waitForFunction(() => document.getElementById("registryPanel").hidden, null, { timeout: 5000 });
  ok(await intentVal() === "com.stripe/mcp", "(d3) [conectar el verificado] → #intent = el OFICIAL, no el impostor", `intent=${await intentVal()}`);

  // ── (e) "community" (dudoso): cancelar NO conecta; conectar igual SÍ. Se distingue por inspect++,
  //        no por #intent (que en ambos casos queda con la QUERY "community" que el usuario tipeó). ──
  await doSearch("community");
  await clickRow("Notas");
  await page.waitForFunction(() => document.querySelector("#registryList .regConfirm.warn"), null, { timeout: 5000 });
  ok(/criterio|no está verificado/i.test(await gateText()), "(e1) dudoso → gate ⚠ 'conecta bajo tu criterio'");
  const eBefore = await inspectClicks();
  await clickBtn("data-ccancel");
  await page.waitForFunction(() => document.getElementById("registryPanel").hidden, null, { timeout: 5000 });
  ok(await inspectClicks() === eBefore && await panelHidden(),
     "(e2) [cancelar] → NO conecta (inspect no disparó)", `clicks ${eBefore}→${await inspectClicks()}`);
  await doSearch("community");
  await clickRow("Notas");
  await page.waitForFunction(() => document.querySelector("#registryList [data-cconnect]"), null, { timeout: 5000 });
  const e3Before = await inspectClicks();
  await clickBtn("data-cconnect");
  await page.waitForFunction(() => document.getElementById("registryPanel").hidden, null, { timeout: 5000 });
  ok(await inspectClicks() === e3Before + 1, "(e3) [conectar igual] → conecta (inspect disparó)", `clicks ${e3Before}→${await inspectClicks()}`);

  // ── (f) "nadaxyz" (registro OK, 0 resultados) → card construir → construye ──
  await page.fill("#intent", "nadaxyz");
  await page.waitForFunction(() => document.querySelector("#registryList .regBuild"), null, { timeout: 5000 });
  ok(true, "(f1) miss legítimo → card 'construye un MCP' VISIBLE");
  await clickBtn("data-build");
  await page.waitForFunction(() => document.getElementById("registryPanel").hidden, null, { timeout: 5000 });
  ok(await intentVal() === "nadaxyz" && await panelHidden(),
     "(f2) click card → construye (#intent = query, panel cierra)", `intent=${await intentVal()}`);

  // ── (g) "valdown" → validate unreachable → gate ⚠ 'no puedo validar' + NO conecta ──
  await page.fill("#intent", "");
  await doSearch("valdown");
  await clickRow("X server");
  await page.waitForFunction(() => document.querySelector("#registryList .regConfirm.warn"), null, { timeout: 5000 });
  ok(/no puedo validar|no responde/i.test(await gateText()), "(g1) validate outage → gate ⚠ 'no puedo validar, reintentá'");
  const noConnectBtn = await page.evaluate(() => !document.querySelector("#registryList [data-cconnect]"));
  ok(noConnectBtn, "(g2) el gate de outage NO ofrece conectar (solo cerrar)");

  ok(errors.length === 0, "(h) 0 errores JS/render", errors.slice(0, 2).join(" ; "));
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push(`harness: ${e && e.message ? e.message : String(e)}`);
} finally {
  await browser.close(); server.kill();
}
console.log("");
if (fails.length === 0) { console.log("RESULTADO: VERDE — resolver-al-elegir (gate confiable/dudoso/impostor) + construí-un-MCP visible + outage honesto"); process.exit(0); }
console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); process.exit(1);
