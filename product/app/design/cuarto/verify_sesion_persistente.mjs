/* verify_sesion_persistente.mjs — GATE del fix "puerto estable + sesión en localStorage"
 * (GAP-DEV-DESKTOP §Tauri-c): DOS LAUNCHES CONSECUTIVOS → MISMA SESIÓN VIVA, SIN RE-LOGIN.
 *
 * El bug medido: el shell Tauri estrenaba puerto efímero por launch → WebKit particiona el
 * storage por ORIGEN (host:puerto) → el login del launch N era invisible en el N+1 (38
 * particiones huérfanas); y el Cuarto encima leía la sesión SOLO de sessionStorage (que
 * muere con la webview). El fix: puerto ESTABLE (25374, rango determinístico en lib.rs del
 * shell — este PORT va en sync) + contrato único AlephSession (localStorage persiste).
 *
 * Simulación FIEL de dos launches de la .app, sin GUI/TCC:
 *   launch = sidecar REAL (suelto, mismo entrypoint sidecar_serve.py, ALEPH_ROLE=client)
 *            en el puerto estable + WebKit REAL (motor de la WKWebView) con perfil
 *            PERSISTENTE (el ~/Library/WebKit del shell). Entre launches muere TODO:
 *            proceso del navegador y sidecar. Lo único que sobrevive es el disco.
 *
 *   L1: Cuarto → AlephSession.set(sesión)  [el write path REAL del login]
 *       → ⌂ Mis agentes dispara GET /v1/users/{id}/puppets CON Bearer (cliente autenticado)
 *   L2: (nada se siembra) Cuarto → la sesión REAPARECE por localStorage
 *       → ⌂ Mis agentes SIN muro "Inicia sesión" y CON el MISMO Bearer  ← LA prueba
 *   CTRL: contexto WebKit efímero (sin perfil) → el muro "Inicia sesión" SÍ aparece
 *         (la señal de L2 depende del storage persistido; no hay auto-login que la regale).
 *
 * El HTTP status del GET no se asserta: con DB-sin-schema (carril aparte del GAP) el
 * backend responde 401/500 — acá se mide el CLIENTE: sesión viva + Bearer + sin re-login.
 * DB y datadir van AISLADOS a un tmp (PUPPET_SQLITE_PATH ignora ALEPH_DATA_DIR — gotcha
 * medido: sin ese env el sidecar abriría la base REAL de ~/Library).
 *
 *   node product/app/design/cuarto/verify_sesion_persistente.mjs
 */
import { webkit } from "playwright";
import { spawn } from "node:child_process";
import net from "node:net";
import os from "node:os";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const ROOT = path.resolve(HERE, "..", "..", "..", "..");   // cuarto → design → app → product → repo

// EN SYNC con PORT_RANGE[0] de deploy/fase4/aleph-shell/src-tauri/src/lib.rs ("ALEPH" en keypad).
const PORT = 25374;
const BASE = `http://127.0.0.1:${PORT}`;
const CUARTO = `${BASE}/cuarto/cuarto.pixi.html`;
const SESION = { id: "u-sesion-estable", session_token: "tok-persistente-1", email: "estable@aleph.app" };

const PY = path.join(ROOT, "product/backend/.venv/bin/python");
const SIDECAR = path.join(ROOT, "deploy/fase4/sidecar_serve.py");
// mismos roots que pathex del .spec (aleph_sidecar.spec) — el sidecar suelto importa igual que frozen
const PYPATH = ["product/backend", "platform", "platform/db", "platform/flywheel",
  "platform/gates", "platform/assembler", "platform/connectors", "platform/sanitizer"]
  .map((p) => path.join(ROOT, p)).join(":");

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "aleph-sesion-"));
const profileDir = path.join(scratch, "webkit-profile");   // ~/Library/WebKit del "shell": SOBREVIVE entre launches
fs.mkdirSync(profileDir, { recursive: true });
fs.mkdirSync(path.join(scratch, "datadir"), { recursive: true });

function waitReady(port, ms) {
  const t0 = Date.now();
  return new Promise((res) => {
    (function tick() {
      const sock = net.connect(port, "127.0.0.1");
      sock.on("connect", () => { sock.destroy(); res(true); });
      sock.on("error", () => {
        sock.destroy();
        if (Date.now() - t0 > ms) return res(false);
        setTimeout(tick, 150);
      });
    })();
  });
}

function bootSidecar() {
  const child = spawn(PY, [SIDECAR, "--port", String(PORT)], {
    stdio: "ignore",
    env: { ...process.env, ALEPH_ROLE: "client", PYTHONPATH: PYPATH,
      PUPPET_SQLITE_PATH: path.join(scratch, "aleph.db"),
      ALEPH_DATA_DIR: path.join(scratch, "datadir") },
  });
  return child;
}
function stopSidecar(child) {
  return new Promise((res) => {
    if (!child || child.exitCode !== null) return res();
    child.on("exit", () => res());
    child.kill("SIGTERM");
    setTimeout(() => { try { child.kill("SIGKILL"); } catch (e) {} res(); }, 4000);
  });
}

const checks = [];
const check = (name, ok, detail) => {
  checks.push({ name, ok });
  console.log(`  ${ok ? "✓" : "✗"} ${name}${detail ? ` — ${detail}` : ""}`);
};

/** Abre el Cuarto, clickea ⌂ Mis agentes y devuelve { authHeader, muro } (qué hizo el CLIENTE). */
async function abrirMisAgentes(page) {
  await page.goto(CUARTO, { waitUntil: "domcontentloaded", timeout: 30000 });
  // el módulo del Cuarto es async: el HANDLER de #mineBtn se cuelga bastante después de que
  // el botón exista en el DOM — clickear antes es un no-op (carrera medida en este verify)
  await page.waitForFunction(() => {
    const b = document.getElementById("mineBtn");
    return !!(b && typeof b.onclick === "function");
  }, { timeout: 30000 });
  const reqPromise = page
    .waitForRequest((r) => r.url().includes("/v1/users/") && r.url().includes("/puppets"), { timeout: 8000 })
    .catch(() => null);
  await page.click("#mineBtn");
  const req = await reqPromise;
  // el handler pinta SIEMPRE algo en #mineList (muro / Cargando… / resultado del fetch)
  await page.waitForFunction(() => ((document.getElementById("mineList") || {}).textContent || "").trim().length > 0,
    { timeout: 8000 }).catch(() => {});
  const muro = await page.$eval("#mineList", (el) => /inicia sesi/i.test(el.textContent || "")).catch(() => false);
  return { authHeader: req ? (await req.allHeaders()).authorization || null : null, muro };
}

let sidecar = null;
let fallo = false;
try {
  // ── LAUNCH 1 ─────────────────────────────────────────────────────────────────────
  console.log(`\n· LAUNCH 1 — sidecar :${PORT} + WebKit con perfil persistente`);
  sidecar = bootSidecar();
  if (!(await waitReady(PORT, 60000))) throw new Error(`el sidecar no respondió en :${PORT}`);

  let ctx = await webkit.launchPersistentContext(profileDir, { viewport: { width: 1280, height: 840 } });
  let page = ctx.pages()[0] || (await ctx.newPage());
  await page.goto(CUARTO, { waitUntil: "domcontentloaded", timeout: 30000 });
  const tieneHelper = await page.evaluate(() => !!(window.AlephSession && window.AlephSession.get && window.AlephSession.set));
  check("L1 · auth.js (AlephSession) cargado en el Cuarto", tieneHelper);
  if (!tieneHelper) throw new Error("sin AlephSession no hay contrato que probar");
  await page.evaluate((s) => window.AlephSession.set(s), SESION);   // el write path REAL del login
  const l1 = await abrirMisAgentes(page);
  check("L1 · ⌂ Mis agentes sale autenticado (Bearer, sin muro)",
    l1.authHeader === `Bearer ${SESION.session_token}` && !l1.muro,
    `auth=${l1.authHeader} muro=${l1.muro}`);
  await ctx.close();                       // muere la webview (y su sessionStorage)
  await stopSidecar(sidecar); sidecar = null;   // muere el "shell" entero

  // ── LAUNCH 2 — mismo puerto, mismo perfil, CERO seeding ─────────────────────────
  console.log(`· LAUNCH 2 — relaunch completo en el MISMO puerto estable`);
  sidecar = bootSidecar();
  if (!(await waitReady(PORT, 60000))) throw new Error(`el sidecar no respondió en :${PORT} (launch 2)`);

  ctx = await webkit.launchPersistentContext(profileDir, { viewport: { width: 1280, height: 840 } });
  page = ctx.pages()[0] || (await ctx.newPage());
  await page.goto(CUARTO, { waitUntil: "domcontentloaded", timeout: 30000 });
  const viva = await page.evaluate(() => (window.AlephSession && window.AlephSession.get()) || null);
  check("L2 · la sesión del launch 1 sigue VIVA (localStorage, mismo origen)",
    !!(viva && viva.id === SESION.id && viva.session_token === SESION.session_token),
    viva ? `id=${viva.id}` : "sin sesión");
  const l2 = await abrirMisAgentes(page);
  check("L2 · SIN re-login: ⌂ Mis agentes reusa el Bearer del launch 1",
    l2.authHeader === `Bearer ${SESION.session_token}` && !l2.muro,
    `auth=${l2.authHeader} muro=${l2.muro}`);
  await ctx.close();

  // ── CONTROL — contexto efímero: sin storage persistido el muro SÍ aparece ───────
  console.log("· CONTROL — WebKit efímero (sin perfil): debe pedir login");
  const browser = await webkit.launch();
  const ephem = await browser.newContext({ viewport: { width: 1280, height: 840 } });
  const cpage = await ephem.newPage();
  const ctrl = await abrirMisAgentes(cpage);
  check("CTRL · sin storage → muro \"Inicia sesión\" (la señal no es un auto-login)",
    ctrl.muro && !ctrl.authHeader, `auth=${ctrl.authHeader} muro=${ctrl.muro}`);
  await browser.close();
} catch (e) {
  console.error(`\n  ✗ ${e.message}`);
  fallo = true;
} finally {
  await stopSidecar(sidecar);
  try { fs.rmSync(scratch, { recursive: true, force: true }); } catch (e) {}
}

const rojos = checks.filter((c) => !c.ok).length + (fallo ? 1 : 0);
console.log(`\n${rojos === 0 ? "VERDE" : "ROJO"} — ${checks.filter((c) => c.ok).length}/${checks.length} checks`);
process.exit(rojos === 0 ? 0 : 1);
