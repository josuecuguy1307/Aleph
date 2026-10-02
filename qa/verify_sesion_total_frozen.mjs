/* verify_sesion_total_frozen.mjs — el MARTILLO de sesión, medido a la vara de la .app.
 *
 * Contra el SIDECAR FROZEN (el binario que ships en Aleph.app), WebKit real (el motor de
 * la webview de Tauri en macOS), datadir aislado. Dos perfiles:
 *
 *   VENENO  — reproduce la caminata del 24-jul: sessionStorage.puppet_user pisado con un
 *             JWT de cuenta que el sidecar cliente NO puede mapear (users.auth_uid vive en
 *             el control plane). Sin el martillo, TODA la app moría 401 "Esta acción
 *             necesita tu sesión". Con el martillo: el primer 401 repara la sesión local
 *             y reintenta — la acción SALE.
 *   LIMPIO  — perfil sin sesión alguna: validar key · guardar · persistir tras
 *             kill+relaunch del sidecar · equipar del registro · guía. Cero "necesita tu
 *             sesión" visible.
 *
 * Los checks corren DESDE la página real (cuarto.pixi.html servido por el frozen), así el
 * fetch pasa por el wrapper de auth.js del bundle — el mecanismo que estaba roto.
 *
 *   node qa/verify_sesion_total_frozen.mjs
 *   ALEPH_SIDECAR_BIN=<binario> node qa/verify_sesion_total_frozen.mjs
 */
import { webkit } from "playwright";
import { spawn } from "node:child_process";
// GUARD _MEI (integración tanda-P): TMPDIR privado por sidecar + barrido en TODA salida.
// El bootloader onefile deja ~170 MB en `_MEI*` si el proceso no cierra limpio; 91 huérfanos
// llenaron el disco el 26-jul. Ver qa/lib/frozen_guard.mjs y qa/verify_frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "./lib/frozen_guard.mjs";
import net from "node:net";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";

const ROOT = new URL("..", import.meta.url).pathname;
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  path.join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
if (!fs.existsSync(SIDECAR)) {
  console.error(`✗ no existe el sidecar frozen: ${SIDECAR}\n  construílo: bash deploy/fase4/build_app.sh public`);
  process.exit(2);
}

const DATADIR = fs.mkdtempSync(path.join(os.tmpdir(), "aleph-sesion-total-"));

function freePort() {
  return new Promise((res, rej) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); });
    s.on("error", rej);
  });
}
function waitReady(port, ms) {
  const t0 = Date.now();
  return new Promise((res) => {
    (function tick() {
      const sock = net.connect(port, "127.0.0.1");
      sock.on("connect", () => { sock.destroy(); res(true); });
      sock.on("error", () => {
        sock.destroy();
        if (Date.now() - t0 > ms) return res(false);
        setTimeout(tick, 200);
      });
    })();
  });
}
function lanzar(port) {
  return spawnFrozen(SIDECAR, ["--port", String(port)], {
    stdio: "ignore",
    env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATADIR },
  });
}

// La receta mínima que el validador acepta (calibrada contra el frozen: valid:true).
const RECETA = {
  schema_version: "v1",
  meta: { name: "VerifySesion", nicho: "general" },
  model: { primary: "specialist", base_url: "http://127.0.0.1:4000/v1",
           temperature: 0.2, max_tokens: 1024, max_turns: 6 },
  belt: { belt_ref: "research", mcp_servers: {}, tool_filters: { arxiv: ["search_papers"] } },
  rag: { enabled: false },
  framing: { system_prompt: "verify" },
};

// El JWT con el que supabase-auth pisaba el slot (mismo formato que el real de la caminata:
// firmado por Supabase, sub sin fila local → el sidecar cliente responde no_session SIEMPRE).
const VENENO = {
  id: "38e68cfd-7cf3-4ac8-ad28-c6cc4f7b2a1b",
  email: "humano@example.com",
  session_token: "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9." +
    Buffer.from(JSON.stringify({ sub: "38e68cfd-7cf3-4ac8-ad28-c6cc4f7b2a1b",
      iss: "https://x.supabase.co/auth/v1", exp: Math.floor(Date.now() / 1000) + 3600 }))
      .toString("base64url") + ".firmafalsa",
};

const NO_SESSION_TXT = ["necesita tu sesión", "needs your session"];
const resultados = [];
function check(nombre, ok, detalle) {
  resultados.push({ nombre, ok, detalle });
  console.log(`  ${ok ? "✓" : "✗"} ${nombre}${detalle ? " — " + detalle : ""}`);
}

// fetch DESDE la página (pasa por el wrapper de auth.js del bundle). Devuelve {status, body}.
async function pageFetch(page, url, opts) {
  return page.evaluate(async ({ url, opts }) => {
    const r = await fetch(url, opts);
    let body = null;
    try { body = await r.clone().json(); } catch (e) { try { body = await r.text(); } catch (e2) {} }
    return { status: r.status, body };
  }, { url, opts });
}
// Igual pero SSE/stream: lee el primer trozo y corta (equip abre un stream largo).
async function pageFetchStreamHead(page, url, opts, ms) {
  return page.evaluate(async ({ url, opts, ms }) => {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), ms);
    try {
      const r = await fetch(url, Object.assign({}, opts, { signal: ctl.signal }));
      if (!r.ok || !r.body) { clearTimeout(timer); let t = ""; try { t = await r.text(); } catch (e) {}
        return { status: r.status, head: t.slice(0, 400) }; }
      const reader = r.body.getReader();
      const { value } = await reader.read();
      clearTimeout(timer); ctl.abort();
      return { status: r.status, head: new TextDecoder().decode(value || new Uint8Array()).slice(0, 400) };
    } catch (e) { clearTimeout(timer); return { status: -1, head: String(e && e.message || e) }; }
  }, { url, opts, ms });
}
async function sinMensajeSesion(page) {
  const txt = await page.evaluate(() => document.body ? document.body.innerText : "");
  return !NO_SESSION_TXT.some((s) => txt.toLowerCase().includes(s.toLowerCase()));
}

const port = await freePort();
let child = lanzar(port);
if (!(await waitReady(port, 60000))) { console.error("✗ el sidecar frozen no levantó"); process.exit(2); }
const BASE = `http://127.0.0.1:${port}`;
const CUARTO = `${BASE}/cuarto/cuarto.pixi.html`;

const browser = await webkit.launch();
// __TAURI__ stub: la página debe creerse .app (fidelidad con la webview real — activa el
// gate desktop de supabase-auth y el flujo _esDesktop en general).
const TAURI_STUB = "window.__TAURI__ = window.__TAURI__ || { __verify_stub: true };";

try {
  // ── PERFIL VENENO ─────────────────────────────────────────────────────────────
  console.log("\n── VENENO · slot pisado con JWT inmapeable (la caminata del humano) ──");
  {
    const ctx = await browser.newContext();
    await ctx.addInitScript(TAURI_STUB);
    const page = await ctx.newPage();
    await page.goto(CUARTO, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.evaluate((v) => sessionStorage.setItem("puppet_user", JSON.stringify(v)), VENENO);

    const r = await pageFetch(page, "/v1/recipes/validate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipe: {} }) });
    check("acción con slot envenenado NO muere en 401", r.status === 200,
      `status=${r.status} body=${JSON.stringify(r.body).slice(0, 90)}`);
    check("la respuesta es el veredicto honesto del validador", !!(r.body && r.body.valid === false));

    const u = await page.evaluate(() => window.AlephSession && window.AlephSession.get());
    check("el slot quedó SANADO a sesión local (device::)",
      !!(u && typeof u.email === "string" && u.email.startsWith("device::")),
      u ? u.email : "sin sesión");
    check("sin 'necesita tu sesión' visible", await sinMensajeSesion(page));
    await ctx.close();
  }

  // ── PERFIL LIMPIO ─────────────────────────────────────────────────────────────
  console.log("\n── LIMPIO · perfil sin sesión: la vara de la caminata ──");
  const ctx = await browser.newContext();
  await ctx.addInitScript(TAURI_STUB);
  const page = await ctx.newPage();
  await page.goto(CUARTO, { waitUntil: "domcontentloaded", timeout: 60000 });

  { // 1 · validar credencial (el caso índice de la captura del humano)
    const r = await pageFetch(page, "/v1/connectors/alphavantage/connect", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ creds: { api_key: "FAKE-VERIFY" } }) });
    const esVeredictoDeKey = r.status === 200 && r.body && r.body.state && r.body.state !== "no_session";
    check("validar key sin sesión → veredicto de la KEY, no pide sesión", esVeredictoDeKey,
      `status=${r.status} state=${r.body && r.body.state}`);
  }

  let ownerId = null, puppetId = null;
  { // 2 · guardar agente
    const u = await page.evaluate(() => window.AlephSession && window.AlephSession.get());
    // el flujo real (saveBtn) manda owner_id de la sesión; sin sesión el wrapper la minta al 401
    const r = await pageFetch(page, "/v1/puppets", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ owner_id: (u && u.id) || "00000000-0000-0000-0000-000000000000",
        name: "VerifySesion", nicho: "general", config: RECETA }) });
    puppetId = r.body && r.body.id;
    ownerId = r.body && r.body.owner_id;
    check("guardar agente sin pedir sesión", (r.status === 200 || r.status === 201) && !!puppetId,
      `status=${r.status} id=${puppetId}`);
  }

  // 3 · persistencia REAL: kill del sidecar + relaunch (mismo puerto+datadir), storage superviviente
  const estado = await ctx.storageState();
  await ctx.close();
  child.kill("SIGTERM");
  await new Promise((res) => child.on("exit", res));
  child = lanzar(port);
  check("relaunch del sidecar frozen (mismo datadir)", await waitReady(port, 60000));

  const ctx2 = await browser.newContext({ storageState: estado });
  await ctx2.addInitScript(TAURI_STUB);
  const page2 = await ctx2.newPage();
  await page2.goto(CUARTO, { waitUntil: "domcontentloaded", timeout: 60000 });
  {
    const u = await page2.evaluate(() => window.AlephSession && window.AlephSession.get());
    const r = u && u.id
      ? await pageFetch(page2, `/v1/users/${u.id}/puppets`, { method: "GET" })
      : { status: 0, body: null };
    const nombres = (r.body && r.body.puppets || []).map((p) => p.id);
    check("el agente guardado PERSISTE tras kill+relaunch", nombres.includes(puppetId),
      `sesión=${u && u.email} agentes=${nombres.length}`);
  }

  { // 4 · equipar del registro (stream del despachador: arranca sin pedir sesión)
    const r = await pageFetchStreamHead(page2, "/v1/catalog/equip", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ service: "open-meteo" }) }, 20000);
    check("equipar del registro arranca sin pedir sesión",
      r.status === 200 && r.head.includes("dispatch.iniciado"),
      `status=${r.status} head=${r.head.slice(0, 60).replace(/\n/g, " ")}`);
  }

  { // 5 · guía: SIN cerebro configurado en el datadir aislado la respuesta honesta es
    //     bad_guide_model (config), JAMÁS no_session. La respuesta plena exige el cerebro
    //     del humano (BYO-CLI) — fuera del alcance de un datadir de verificación.
    const r = await pageFetch(page2, "/v1/cuarto/guide", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [{ role: "user", content: "hola" }] }) });
    const noEsSesion = r.status !== 401 &&
      !(JSON.stringify(r.body || "").toLowerCase().includes("no_session"));
    check("guía NUNCA pide sesión (honesta si falta cerebro)", noEsSesion,
      `status=${r.status} body=${JSON.stringify(r.body).slice(0, 80)}`);
  }

  check("sin 'necesita tu sesión' visible al final del run", await sinMensajeSesion(page2));
  await ctx2.close();
} finally {
  await browser.close();
  try { child.kill("SIGTERM"); } catch (e) {}
  try { fs.rmSync(DATADIR, { recursive: true, force: true }); } catch (e) {}
}

const rojos = resultados.filter((r) => !r.ok);
console.log(`\n${rojos.length === 0 ? "VERDE" : "ROJO"}: ${resultados.length - rojos.length}/${resultados.length} checks`);
process.exit(rojos.length === 0 ? 0 : 1);
