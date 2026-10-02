/* verify_modelos_p8_legacy.mjs — VARA HISTÓRICA de FIX-P8.
 *
 * INCOMPATIBLE CON MODELOS V2: preserva la caminata original de 125 aserciones contra
 * la UI anterior de grupos/cards. No es el entrypoint canónico ni debe usarse para
 * certificar BUSCAR vs CONFIGURAR; `verify_modelos.mjs` ejecuta la vara V2 viva en :8306.
 *
 * El bug que mide: el diseño del punto 35 nunca se construyó, y la caminata sumó dos más
 * —un MCP metido en la pantalla de modelos (banner Globalfishingwatch) y el nombre
 * «Cerebro», que hace sonar a esto como una cosa sola y mágica.
 *
 * Config: WebKit + el sidecar FROZEN (el binario instalado, en MI puerto) para todo lo
 * que ya existía (sesión, motor, iconos) + el sidecar de FUENTE de ESTE worktree para
 * /v1/modelos, que el frozen NO puede servir (se congeló antes de que existiera). Los dos
 * comparten ALEPH_DATA_DIR y el harness lo COMPRUEBA antes de medir.
 *
 * Y un TERCER backend: una FUENTE gemela con la API de Hugging Face apuntada a un host
 * muerto. Es la única forma honesta de medir «sin red»: cortarle la red de verdad al
 * proceso que la usa, no mockear el fetch del browser.
 *
 * MATRIZ
 *   1. LA SEPARACIÓN — sección propia + CERO MCPs en la pantalla (grep del banner y de
 *      todo el vocabulario de conectores). Es el caso índice del bug.
 *   2. EL RENAME — «Cerebro» = 0 en la UI viva, ES y EN, y las claves en lockstep.
 *   3. LOS 3 MODOS + «Incluido» — cada grupo con su título y su lede.
 *   4. LAS 5 CATEGORÍAS — las cinco, con su lede, y cargando de HF VIVO.
 *   5. HF EN VIVO — nombres que NO están horneados en el código + peso real.
 *   6. MAC → MLX PRIMERO — y sin dead-ends: si el runtime nativo no está, se dice
 *      arriba y NO se baja nada que no vaya a poder correr.
 *   7. SIN RED (calibración #1) — fallo VISIBLE + lo YA descargado igual listado.
 *   8. VEREDICTO CONTRA TU MÁQUINA — barra de disco + RAM pedida + las 3 respuestas.
 *   9. NO ENTRA (calibración #2) — el faltante EXACTO, con el peso inflado.
 *  10. DESCARGA REAL de un modelo CHICO: veredicto → progreso → CANCELAR LIMPIA →
 *      descargar → PRUEBA AUTOMÁTICA → 🟢. La salida de éxito RIGE.
 *  11. GATING (calibración #3) — pieza alta + modelo chico → aviso, JAMÁS corre.
 *  12. GUÍA FRONTIER-ONLY — un no-frontier sale bloqueado con su porqué.
 *  13. LOS 5 ESTADOS — cada uno con su glifo, su palabra y su camino.
 *  14. LOGOS — marca comercial por brandface; avatar de HF sólo desde cache.
 *  15. EL CHAT OFRECE EL CAMINO — `sin_vision` aterriza en la categoría correcta.
 *  16. EL DEFAULT DE ARRANQUE (hallazgo de P10) — el default elegido es UTILIZABLE, y si
 *      no hay ninguno, se dice con su camino. Calibración en rojo: nada utilizable.
 *
 * Run:  node product/app/design/modelos/verify_modelos.mjs
 * (levanta y mata SUS procesos — JAMÁS toca el :25374 del humano)
 */
import { webkit } from "playwright";
import http from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { spawnFrozen } from "../../../../qa/lib/frozen_guard.mjs";
import { mkdtempSync, existsSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { createRequire } from "node:module";

const require$ = createRequire(import.meta.url);
const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN = join(HERE, "..");
const REPO = join(DESIGN, "..", "..", "..");
const SHOTS = join(HERE, "screenshots");

// PUERTOS PROPIOS de FIX-P8. El :25374 es del humano y no aparece acá ni por accidente.
const PORT = Number(process.env.P8_PORT || 8279);        // el front (el puerto asignado)
const FUENTE = process.env.P8_FUENTE || "http://127.0.0.1:8280";
const FROZEN = process.env.P8_FROZEN || "http://127.0.0.1:8281";
const SINRED = process.env.P8_SINRED || "http://127.0.0.1:8283";  // gemela con HF muerto
const PAGE = `http://127.0.0.1:${PORT}/Modelos.dc.html`;
const APP_SIDECAR = process.env.ALEPH_SIDECAR_BIN || "/Applications/Aleph.app/Contents/MacOS/aleph_sidecar";
const PY = process.env.P8_PY || "/opt/miniconda3/bin/python";

// El modelo CHICO de la descarga real. Se DESCUBRE del catálogo vivo (no se hornea):
// el harness pide la categoría embeddings y toma el más liviano que entre cómodo.
let CHICO = null;
const API_SLUG = (id) => String(id || "").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase().slice(0, 80);

const fails = [];
let total = 0;
const ok = (cond, label, extra) => {
  total++;
  console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  — " + String(extra).slice(0, 150) : ""}`);
  if (!cond) fails.push(label);
};
const seccion = (t) => console.log(`\n── ${t} ${"─".repeat(Math.max(2, 74 - t.length))}`);

// ── el catálogo VIVO de HF se sirve por la FUENTE normal; el «sin red» por la gemela ──
// `hf` conmuta el catálogo vivo/sin-red · `brains` conmuta el estado de los proveedores
// de cognición: es la calibración en rojo del bug de instalación (nada utilizable).
const RUTA = { hf: "normal", brains: "real" };

const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
  ".webp": "image/webp", ".woff2": "font/woff2", ".md": "text/markdown", ".ico": "image/x-icon" };

const server = http.createServer(async (req, res) => {
  req.on("error", () => {}); res.on("error", () => {});
  const u = new URL(req.url, "http://x");
  if (u.pathname.startsWith("/v1/") || u.pathname === "/health") {
    const aModelos = u.pathname.startsWith("/v1/modelos") || u.pathname.startsWith("/v1/icons");
    const arriba = aModelos ? (RUTA.hf === "muerta" ? SINRED : FUENTE) : FROZEN;
    const chunks = []; for await (const c of req) chunks.push(c);
    const body = Buffer.concat(chunks);
    const fwd = {};
    for (const k of ["authorization", "content-type", "accept"]) if (req.headers[k]) fwd[k] = req.headers[k];
    let up;
    try {
      up = await fetch(arriba + req.url, {
        method: req.method, headers: fwd,
        body: ["GET", "HEAD"].includes(req.method) ? undefined : (body.length ? body : undefined),
        redirect: "manual",
      });
    } catch (e) { up = null; }
    if (!up) { res.writeHead(502); res.end("sidecar caído: " + arriba); return; }
    // CALIBRACIÓN del bug de instalación: se falsea el estado de los proveedores para
    // reproducir la máquina de un usuario nuevo (incluida sin llave, sin CLIs). Es la
    // única forma honesta: no le puedo desinstalar Claude Code al humano para medir.
    if (RUTA.brains === "nada" && u.pathname === "/v1/brains/status") {
      const cuerpo = JSON.stringify({ service: { state: "unavailable", detail: "forzado por la vara" },
        providers: { included: { state: "not_configured", detail: "sin llave en este runtime" },
                     claude_cli: { state: "not_installed", detail: "forzado por la vara" },
                     codex_cli: { state: "not_installed", detail: "forzado por la vara" } } });
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(cuerpo);
      return;
    }
    const h = {};
    up.headers.forEach((v, k) => { if (!/^(content-encoding|transfer-encoding|connection|content-length)$/i.test(k)) h[k] = v; });
    res.writeHead(up.status, h);
    if (up.body) {
      const reader = up.body.getReader();
      for (;;) { const { done, value } = await reader.read(); if (done) break; res.write(Buffer.from(value)); }
    }
    res.end();
    return;
  }
  try {
    const body = await readFile(join(DESIGN, decodeURIComponent(u.pathname).replace(/^\//, "")));
    res.writeHead(200, { "Content-Type": MIME[extname(u.pathname)] || "application/octet-stream" });
    res.end(body);
  } catch { res.writeHead(404); res.end("nf"); }
});
server.on("clientError", (e, s) => { try { s.destroy(); } catch {} });
server.on("error", () => {});

// LA VARA SE LIMPIA EN TODA SALIDA — incluida la que NO planeó.
// La primera corrida murió por un timeout de Playwright y dejó tres sidecars vivos en mis
// puertos: la corrida siguiente se paró (bien) diciendo «ocupado», y perdí la vuelta. Es
// la misma lección del guard de `_MEI`: un `finally` al final del archivo NO cubre el modo
// de fallo que importa. Se barre en excepción, en rechazo, en exit y en señal.
let _limpiando = false;
function barrer() {
  if (_limpiando) return;
  _limpiando = true;
  try { matar(); } catch {}
  try { server.close(); } catch {}
}
process.on("uncaughtException", (e) => {
  if (/aborted|ECONNRESET|EPIPE/i.test(String(e && (e.code || e.message)))) return;
  console.error("\n✗ la vara murió:", e && e.message);
  barrer();
  process.exit(1);
});
process.on("unhandledRejection", (e) => {
  console.error("\n✗ la vara murió (promesa sin catch):", e && e.message);
  barrer();
  process.exit(1);
});
process.on("exit", barrer);
for (const s of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(s, () => { barrer(); process.exit(130); });

// ── los backends ─────────────────────────────────────────────────────────────────────
const DATA = process.env.P8_DATA || mkdtempSync(join(tmpdir(), "p8-data-"));
let procFrozen = null, procFuente = null, procSinRed = null;

// HIGIENE DE PUERTO SIN MATAR A NADIE (lección de 581aa1c): el puerto ocupado NO se
// libera — se REPORTA y se para. Los puertos son baratos; el trabajo de otra sesión no.
function puertoLibre(puerto) {
  const { execSync } = require$("node:child_process");
  if (puerto === 25374) throw new Error("ese puerto es del humano — nunca");
  let pids = [];
  try {
    pids = execSync(`lsof -nP -tiTCP:${puerto} -sTCP:LISTEN 2>/dev/null || true`)
      .toString().trim().split("\n").filter(Boolean);
  } catch (e) { return true; }
  if (!pids.length) return true;
  for (const pid of pids) {
    let cmd = "";
    try { cmd = execSync(`ps -o command= -p ${pid} 2>/dev/null || true`).toString().trim(); } catch (e) {}
    console.log(`✗ :${puerto} está ocupado por pid ${pid} — ${cmd.slice(0, 90)}`);
  }
  console.log("  no lo mato (puede ser de otra sesión). Corré con P8_PORT/P8_FUENTE/P8_FROZEN/P8_SINRED en puertos libres.");
  return false;
}

async function sano(base, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try { const r = await fetch(base + "/health", { signal: AbortSignal.timeout(2000) }); if (r.ok) return true; } catch {}
    await new Promise((r) => setTimeout(r, 700));
  }
  return false;
}

async function bootFrozen() {
  procFrozen = spawnFrozen(APP_SIDECAR, ["--port", String(new URL(FROZEN).port)],
    { env: { ...process.env, ALEPH_DATA_DIR: DATA }, stdio: "ignore", detached: true });
  procFrozen.unref();
  return await sano(FROZEN);
}

function bootFuente(base, extraEnv) {
  const p = spawn(PY, ["-m", "uvicorn", "modelos_sidecar:app", "--app-dir",
    join(REPO, "product", "backend"), "--port", String(new URL(base).port), "--log-level", "warning"],
    { env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATA,
             PYTHONPATH: [join(REPO, "product", "backend"), join(REPO, "platform"),
                          join(REPO, "platform", "assembler")].join(":"),
             ...(extraEnv || {}) },
      stdio: "ignore", detached: true, cwd: REPO });
  p.unref();
  return p;
}

function matar() {
  for (const p of [procFuente, procSinRed, procFrozen]) {
    try { if (p) process.kill(-p.pid, "SIGKILL"); } catch {}
  }
  procFuente = procSinRed = procFrozen = null;
}

// ══════════════════════════════════════════════════════════════════════════════════════
await mkdir(SHOTS, { recursive: true });
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));
for (const p of [Number(new URL(FROZEN).port), Number(new URL(FUENTE).port), Number(new URL(SINRED).port)]) {
  if (!puertoLibre(p)) { server.close(); process.exit(1); }
}
console.log(`· datadir aislado: ${DATA}`);
if (!(await bootFrozen())) { console.log("✗ no pude levantar el sidecar FROZEN en " + FROZEN); matar(); process.exit(1); }
procFuente = bootFuente(FUENTE);
procSinRed = bootFuente(SINRED, { PUPPET_HF_API: "http://127.0.0.1:1" });
if (!(await sano(FUENTE))) { console.log("✗ no pude levantar la FUENTE en " + FUENTE); matar(); process.exit(1); }
if (!(await sano(SINRED))) { console.log("✗ no pude levantar la gemela SIN RED en " + SINRED); matar(); process.exit(1); }

// PRUEBA DURA de datadir compartido: sin esto, todo lo de sesión mide el banco de pruebas.
let TOKEN = null;
{
  const r = await fetch(FROZEN + "/v1/auth/local", { method: "POST" }).catch(() => null);
  const j = r && r.ok ? await r.json().catch(() => null) : null;
  if (!j || !j.session_token) { console.log("✗ el frozen no minta sesión local"); matar(); process.exit(1); }
  TOKEN = j.session_token;
  const m = await fetch(FUENTE + "/v1/modelos", { headers: { Authorization: "Bearer " + TOKEN } })
    .then((x) => x.json()).catch(() => null);
  if (!m || !m.maquina || m.maquina.carpeta.indexOf(DATA) < 0) {
    console.log("✗ frozen y fuente NO comparten ALEPH_DATA_DIR — mediría otro árbol.",
                m && m.maquina && m.maquina.carpeta);
    matar(); process.exit(1);
  }
  console.log(`· carpeta de modelos compartida: ${m.maquina.carpeta}`);
}

const browser = await webkit.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
const page = await ctx.newPage();
const consolaMala = [];
const fallos404 = [];
page.on("console", (m) => { if (m.type() === "error") consolaMala.push(m.text()); });
page.on("pageerror", (e) => consolaMala.push("pageerror: " + e.message));
// El 404 se caza por RESPUESTA (con su URL), no por el texto de la consola: WebKit no
// pone la URL en el mensaje, así que un filtro por texto habría tapado un 404 real.
page.on("response", (r) => { if (r.status() >= 400) fallos404.push(r.status() + " " + r.url()); });

async function abrir(url) {
  await page.goto(url || PAGE, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#mdFilas .md-fila", { timeout: 25000 });
  await page.waitForTimeout(400);
}
await abrir();

// ══════════════════════════════════════════════════════════════════════════════════════
seccion("1 · LA SEPARACIÓN — modelos = lo que piensa · conectores = lo que hace");
{
  const txt = (await page.textContent("body")) || "";
  const html = await page.content();
  // El caso ÍNDICE: el banner de un conector MCP dentro de la pantalla de modelos.
  ok(!/globalfishing/i.test(txt) && !/globalfishing/i.test(html),
     "cero rastro de Globalfishingwatch (el MCP que se había colado)");
  // Y el vocabulario entero de conectores: si vuelve, vuelve con estas palabras.
  const mcpLeaks = ["mcpServers", "belt_ref", "backed_by", "servidor MCP equipado",
                    "opensanctions", "gleif", "tool_filters"];
  const colados = mcpLeaks.filter((k) => html.indexOf(k) >= 0);
  ok(colados.length === 0, "cero vocabulario de conectores/MCP en la pantalla", colados.join(", "));
  // La sección propia existe y está en el nav.
  ok(/Modelos/.test(await page.textContent("h1")), "la pantalla tiene su H1 propio: Modelos");
  const navTxt = (await page.textContent("#aleph-topbar").catch(() => "")) || "";
  ok(/Modelos/.test(navTxt), "la entrada «Modelos» está en el menú");
  // el lede DICE la separación (no la deja implícita)
  const lede = (await page.textContent(".md-lede")) || "";
  ok(/piensa/i.test(lede) && /(conectores|actúa)/i.test(lede),
     "el lede dice la separación en una línea", lede.slice(0, 80));
  // y el backend NO puede traer un MCP aunque quisiera: no conoce belts.
  const mod = await readFile(join(REPO, "product", "backend", "app", "phase1", "centro_modelos.py"), "utf8");
  ok(!/belt|mcpServers|mcp_resolver/i.test(mod.replace(/^.*(no conoce belts|MCP NO vive|conectores).*$/gmi, "")),
     "el módulo del backend no importa nada de belts/MCP (por construcción)");
}

seccion("2 · EL RENAME — «Cerebro» muere de la UI, ES y EN en lockstep");
{
  for (const [lang, url] of [["es", PAGE], ["en", PAGE]]) {
    if (lang === "en") {
      await page.evaluate(() => localStorage.setItem("aleph-lang", "en"));
      await abrir();
    }
    const txt = (await page.textContent("body")) || "";
    const n = (txt.match(/cerebro/gi) || []).length;
    ok(n === 0, `[${lang}] «Cerebro» = 0 en el texto vivo de la pantalla`, n ? `${n} apariciones` : "");
  }
  await page.evaluate(() => localStorage.setItem("aleph-lang", "es"));
  await abrir();

  // El chip compartido (nav) es la superficie que aparece en TODAS las pantallas.
  const chip = (await page.textContent("#aleph-nav-brain").catch(() => "")) || "";
  ok(!/cerebro/i.test(chip), "el chip del nav no dice «cerebro»", chip.trim().slice(0, 60));

  // LOCKSTEP: cada clave renombrada existe de los dos lados y ninguna quedó en español.
  const i18n = await readFile(join(DESIGN, "i18n.js"), "utf8");
  const claves = ["brain.label.none", "brain.label.custom", "brain.action.choose",
                  "brain.action.cuarto", "brain.none", "sala.power.brain", "sala.sb.brain",
                  "sala.sb.panel_cerebro", "nav.modelos"];
  let lock = 0;
  for (const k of claves) {
    const apar = (i18n.match(new RegExp(`["']${k.replace(/\./g, "\\.")}["']\\s*:`, "g")) || []).length;
    if (apar === 2) lock++;
    else ok(false, `clave ${k} declarada de los DOS lados`, `apariciones: ${apar}`);
  }
  ok(lock === claves.length, `las ${claves.length} claves del rename, ES y EN en lockstep`);
  ok(/["']nav\.modelos["']:\s*['"]Modelos['"]/.test(i18n) && /["']nav\.modelos["']:\s*['"]Models['"]/.test(i18n),
     "nav.modelos = Modelos / Models");
}

seccion("3 · LOS 3 MODOS (+ Incluido, que existe en el producto)");
{
  const grupos = await page.$$eval("#mdFilas .md-grupo", (gs) => gs.map((g) => ({
    familia: g.dataset.familia,
    titulo: (g.querySelector(".md-grupo-t") || {}).textContent || "",
    lede: (g.querySelector(".md-grupo-l") || {}).textContent || "",
    filas: g.querySelectorAll(".md-fila").length,
  })));
  const fams = grupos.map((g) => g.familia);
  for (const f of ["incluido", "cli", "api", "local"]) {
    const g = grupos.find((x) => x.familia === f);
    ok(!!g && g.lede.trim().length > 10, `grupo «${f}» con su lede propio`, g && g.lede.trim().slice(0, 46));
  }
  ok(fams.indexOf("local") === fams.length - 1, "el modo LOCAL (el nuevo) va último", fams.join(" → "));
  ok(grupos.reduce((a, g) => a + g.filas, 0) >= 12, "la pantalla lista modelos de verdad");
}

seccion("4 · LAS 5 CATEGORÍAS");
{
  const tabs = await page.$$eval("#mdCat .md-tab", (bs) => bs.map((b) => b.dataset.cat));
  for (const c of ["vision", "razonamiento", "codigo", "rapido", "embeddings"]) {
    ok(tabs.indexOf(c) >= 0, `categoría «${c}» presente`);
  }
  ok(tabs.length === 5, "exactamente 5 categorías, ni una de más", tabs.join(", "));
  await page.click('#mdCat .md-tab[data-cat="embeddings"]');
  await page.waitForTimeout(300);
  const lede = (await page.textContent("#mdCatLede")) || "";
  ok(lede.trim().length > 15, "la categoría abierta explica para qué sirve", lede.slice(0, 60));
}

seccion("5 · HUGGING FACE EN VIVO (nada horneado)");
{
  await page.waitForSelector("#mdCatBody .md-cand", { timeout: 45000 });
  const cands = await page.$$eval("#mdCatBody .md-cand", (ls) => ls.map((l) => ({
    id: l.dataset.id,
    meta: (l.querySelector(".md-cand-meta") || {}).textContent || "",
    ver: (l.querySelector(".md-ver-t") || {}).textContent || "",
  })));
  ok(cands.length > 0, `HF respondió con ${cands.length} candidatos reales`);
  ok(cands.every((c) => /\//.test(c.id)), "cada candidato es un repo real org/modelo", cands[0] && cands[0].id);
  ok(cands.every((c) => /GB/.test(c.meta)), "cada candidato trae su PESO real");
  // NADA horneado: ninguno de los ids vive en el código fuente.
  const src = (await readFile(join(REPO, "product", "backend", "app", "phase1", "centro_modelos.py"), "utf8"))
    + (await readFile(join(HERE, "modelos.ui.js"), "utf8"));
  const horneados = cands.filter((c) => src.indexOf(c.id) >= 0);
  ok(horneados.length === 0, "ningún nombre de modelo está horneado en el código", horneados.join(", "));
  // El más liviano que ENTRA es el que vamos a bajar de verdad (§10).
  const via = await page.evaluate(() => {
    const l = [...document.querySelectorAll("#mdCatBody .md-cand")]
      .filter((x) => x.dataset.veredicto === "comodo");
    return l.map((x) => ({ id: x.dataset.id,
      peso: parseFloat(((x.querySelector(".md-cand-meta") || {}).textContent || "").split(" GB")[0]) }));
  });
  CHICO = via.filter((x) => x.peso > 0).sort((a, b) => a.peso - b.peso)[0] || null;
  ok(!!CHICO, "hay al menos un candidato que entra cómodo (el de la descarga real)",
     CHICO && `${CHICO.id} · ${CHICO.peso} GB`);
}

seccion("6 · MAC → MLX PRIMERO (y sin dead-ends)");
{
  const maq = await (await fetch(FUENTE + "/v1/modelos/maquina")).json();
  const esMac = maq.plataforma === "darwin" && maq.arquitectura === "arm64";
  if (esMac) {
    ok(maq.formatos[0] === "mlx", "en Apple Silicon el formato nativo, y el PRIMERO ofrecido, es MLX", maq.formatos.join(" \u2192 "));
    ok(maq.formatos.indexOf("gguf") > 0, "y GGUF queda como el segundo");
    const btns = await page.$$eval("#mdCat .md-fbtn", (bs) => bs.map((b) => b.dataset.fmt));
    ok(btns[0] === "mlx", "la pantalla ofrece MLX primero en el selector de formato", btns.join(", "));
    const rt = maq.runtimes.mlx;
    if (!rt.vivo) {
      // «MLX primero» NO puede significar arrancar en un callejón sin salida. La pantalla
      // lo sigue ofreciendo primero, pero arranca en el formato que SÍ puede correr y
      // dice, arriba, qué falta instalar y con qué comando.
      ok(maq.formato_default !== "mlx", "sin runtime MLX, la pantalla ARRANCA en un formato que sí corre", maq.formato_default);
      await page.click('#mdCat .md-fbtn[data-fmt="mlx"]');
      await page.waitForSelector("#mdRtAviso:not([hidden])", { timeout: 25000 });
      const av = (await page.textContent("#mdRtAviso")) || "";
      ok(/MLX/.test(av), "al elegir MLX se AVISA que no puede correr acá", av.replace(/\s+/g, " ").slice(0, 70));
      ok(/pip install mlx-lm/.test(av), "con EL COMANDO exacto");
      // y el backend se niega ANTES de bajar un byte (el bug que cazó la primera corrida)
      const r = await fetch(FUENTE + "/v1/modelos/descargar", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hf_id: "mlx-community/x", archivo: "model.safetensors",
                               formato: "mlx", categoria: "rapido", peso_gb: 0.02 }),
      });
      const evs = (await r.text()).split("\n\n").filter((l) => l.startsWith("data: ")).map((l) => JSON.parse(l.slice(6)));
      const fin = evs.find((e) => e.tipo === "fin");
      ok(fin && fin.causa === "sin_runtime", "y el backend NO baja nada: corta con `sin_runtime`", fin && fin.causa);
      ok(evs.some((e) => e.tipo === "sin_runtime" && e.mano && e.mano.comando),
         "con la mano humana en el propio evento");
      ok(!evs.some((e) => e.tipo === "progreso"), "CERO bytes bajados a un disco donde no van a correr");
      await page.click(`#mdCat .md-fbtn[data-fmt="${maq.formato_default}"]`);
      await page.waitForTimeout(1500);
    } else {
      ok(maq.formato_default === "mlx", "con el runtime MLX vivo, la pantalla arranca EN MLX");
    }
  } else {
    ok(maq.formatos[0] === "gguf", "fuera de Apple Silicon, GGUF es el formato ofrecido");
  }
}

seccion("7 · SIN RED — fallo VISIBLE + lo YA descargado igual listado (calibración #1)");
{
  RUTA.hf = "muerta";
  await abrir();
  await page.click('#mdCat .md-tab[data-cat="razonamiento"]');
  await page.waitForSelector("#mdSinRed", { timeout: 25000 });
  const aviso = (await page.textContent("#mdSinRed")) || "";
  ok(/no pude|couldn/i.test(aviso), "el fallo se DICE (no hay lista vacía fingida)", aviso.slice(0, 70));
  ok(!!(await page.$("#mdReintentarCat")), "y ofrece [Reintentar] — un fallo con salida");
  const locales = await page.$$eval('#mdFilas .md-grupo[data-familia="local"] .md-fila', (l) => l.length);
  ok(locales > 0, `lo YA descargado sigue listado sin red: ${locales} modelo(s) local(es)`);
  ok(/\d+ modelo/i.test(aviso) || /\d+ model/i.test(aviso),
     "el aviso le RECUERDA que lo local sigue usable", aviso.slice(-80));
  await page.screenshot({ path: join(SHOTS, "p8-sin-red.png") });
  // CALIBRACIÓN: con la red viva, ese aviso NO aparece. Una vara que no sabe distinguir
  // los dos mundos no está midiendo la red — está midiendo el DOM.
  RUTA.hf = "normal";
  await abrir();
  await page.click('#mdCat .md-tab[data-cat="razonamiento"]');
  await page.waitForTimeout(2500);
  ok(!(await page.$("#mdSinRed")), "CALIBRACIÓN #1 ✓ con red, el aviso de fallo NO aparece");
}

seccion("8 · VEREDICTO CONTRA TU MÁQUINA");
{
  const maq = (await page.textContent("#mdMaquina")) || "";
  ok(/Disco libre|Free disk/i.test(maq) && /GB/.test(maq), "la pantalla muestra tu disco libre REAL", maq.trim().slice(0, 60));
  ok(/RAM/i.test(maq), "y tu RAM libre");
  await page.click('#mdCat .md-tab[data-cat="embeddings"]');
  await page.waitForSelector("#mdCatBody .md-cand .md-veredicto", { timeout: 45000 });
  const v = await page.$$eval("#mdCatBody .md-cand", (ls) => ls.map((l) => ({
    ver: (l.querySelector(".md-ver-t") || {}).textContent || "",
    barra: !!l.querySelector(".md-barra-in"),
    ram: (l.querySelector(".md-ver-ram") || {}).textContent || "",
  })));
  ok(v.every((x) => x.ver.trim().length > 0), "cada candidato trae su veredicto en palabras");
  ok(v.some((x) => x.barra), "y la BARRA de cuánto de tu disco se lleva");
  ok(v.some((x) => /RAM/i.test(x.ram)), "y la RAM que pide", (v.find((x) => /RAM/i.test(x.ram)) || {}).ram);
  const frases = v.map((x) => x.ver);
  ok(frases.some((f) => /Entra cómodo|Fits comfortably/i.test(f)), "la respuesta «Entra cómodo» existe");
  // las otras dos se prueban contra el backend, que es donde vive la decisión
  const j = (x) => fetch(FUENTE + "/v1/modelos/maquina").then((r) => r.json());
  const maqJ = await j();
  const ram = maqJ.ram_libre_gb || maqJ.ram_total_gb;
  const justo = await (await fetch(FUENTE + "/v1/modelos/catalogo?categoria=rapido&formato=gguf&limite=6")).json();
  ok(justo.red === true, "el catálogo por HTTP responde con red viva");
}

seccion("9 · NO ENTRA — el faltante EXACTO (calibración #2: peso inflado)");
{
  // Se INFLA el peso a propósito: es la única forma de medir la rama «no entra» sin
  // llenar el disco de verdad. El backend decide ANTES de bajar un solo byte.
  const r = await fetch(FUENTE + "/v1/modelos/descargar", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hf_id: "ggml-org/inexistente-gigante", archivo: "x.gguf",
                           formato: "gguf", categoria: "rapido", peso_gb: 9999, tier: "grande" }),
  });
  const txt = await r.text();
  const evs = txt.split("\n\n").filter((l) => l.startsWith("data: ")).map((l) => JSON.parse(l.slice(6)));
  const ver = evs.find((e) => e.tipo === "veredicto");
  const fin = evs.find((e) => e.tipo === "fin");
  ok(ver && ver.veredicto.veredicto === "no_entra", "un modelo que no entra se ATAJA antes de bajar nada");
  ok(ver && /te faltan [\d.]+ GB/i.test(ver.veredicto.es), "y dice el faltante EXACTO en GB", ver && ver.veredicto.es);
  ok(fin && fin.causa === "sin_espacio", "con causa tipada `sin_espacio`", fin && fin.causa);
  ok(evs.some((e) => e.tipo === "cerrado"), "y el cable CIERRA siempre (jamás espera muda)");
  // CALIBRACIÓN #2 en verde: el mismo endpoint con un peso real NO dice no_entra.
  const r2 = await fetch(FUENTE + "/v1/modelos/catalogo?categoria=embeddings&formato=gguf&limite=3");
  const d2 = await r2.json();
  ok(d2.modelos.some((m) => m.veredicto.veredicto !== "no_entra"),
     "CALIBRACIÓN #2 ✓ con el peso REAL, el mismo veredicto dice que sí entra");
  // Y la UI lo muestra deshabilitado, no escondido.
  const desh = await page.$$eval("#mdCatBody .md-cand", (ls) => ls
    .filter((l) => l.dataset.veredicto === "no_entra")
    .map((l) => !!l.querySelector("button[disabled]")));
  ok(desh.length === 0 || desh.every(Boolean), "un candidato que no entra sale DESHABILITADO, no escondido");
}

seccion("10 · DESCARGA REAL — veredicto → progreso → cancelar limpia → 🟢 probado");
{
  if (!CHICO) { ok(false, "sin candidato chico no puedo medir la descarga real"); }
  else {
    // 10a · CANCELAR LIMPIA — se corta a mitad y el disco queda como estaba.
    const antes = existsSync(join(DATA, "modelos")) ? readdirSync(join(DATA, "modelos")).length : 0;
    await page.click('#mdCat .md-tab[data-cat="embeddings"]');
    await page.waitForSelector("#mdCatBody .md-cand", { timeout: 45000 });
    // El de la descarga real se re-elige AHORA, en el formato que la pantalla trae por
    // defecto (el que tiene runtime): bajar en un formato que no corre mide otra cosa.
    const via2 = await page.evaluate(() => [...document.querySelectorAll("#mdCatBody .md-cand")]
      .filter((x) => x.dataset.veredicto === "comodo")
      .map((x) => ({ id: x.dataset.id,
        peso: parseFloat(((x.querySelector(".md-cand-meta") || {}).textContent || "").split(" GB")[0]) })));
    CHICO = via2.filter((x) => x.peso > 0).sort((a, b) => a.peso - b.peso)[0] || CHICO;
    console.log(`  \u00b7 el chico de la descarga real: ${CHICO.id} (${CHICO.peso} GB)`);
    const sel = `#mdCatBody .md-cand[data-id="${CHICO.id.replace(/"/g, '\\"')}"]`;
    await page.click(`${sel} .md-bajar`);
    await page.waitForSelector(`${sel} .md-prog-in`, { timeout: 20000 });
    await page.waitForFunction((s) => {
      const t = (document.querySelector(s + " .md-prog-txt") || {}).textContent || "";
      return /bajando|downloading/i.test(t);
    }, sel, { timeout: 30000 });
    const enVuelo = (await page.textContent(`${sel} .md-prog-txt`)) || "";
    const det = (await page.textContent(`${sel} .md-prog-det`)) || "";
    ok(/\d/.test(enVuelo) && /MB/.test(enVuelo), "durante la descarga se ven los MB", enVuelo.trim());
    ok(/MB\/s/.test(det), "la velocidad", det.trim());
    ok(/faltan|left/i.test(det), "y lo que falta");
    await page.click(`${sel} .md-cancelar`);
    await page.waitForSelector(`${sel} .md-desenlace[data-estado="cancelado"]`, { timeout: 20000 });
    await page.waitForTimeout(900);
    const carpeta = join(DATA, "modelos", CHICO.id.replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase());
    const restos = existsSync(carpeta) ? readdirSync(carpeta).filter((f) => /\.part$/.test(f)) : [];
    ok(restos.length === 0, "CANCELAR LIMPIA: no queda ningún `.part` a medio bajar", restos.join(", "));
    await page.screenshot({ path: join(SHOTS, "p8-cancelada.png") });

    // 10b · LA DESCARGA COMPLETA, y su desenlace VERDE con evidencia.
    await abrir();
    await page.click('#mdCat .md-tab[data-cat="embeddings"]');
    await page.waitForSelector(sel, { timeout: 45000 });
    await page.click(`${sel} .md-bajar`);
    // ESPERA CON DIAGNÓSTICO. Una vara que se queda 7 minutos mirando un selector que no
    // va a aparecer no está midiendo: está perdiendo la vuelta y no dice por qué. Si no
    // llega el desenlace, se DUMPEA lo que sí está en pantalla y lo que dice el backend.
    let desen = null;
    try {
      await page.waitForSelector(`${sel} .md-desenlace`, { timeout: 300000 });
      desen = await page.$eval(`${sel} .md-desenlace`, (e) => ({
        estado: e.dataset.estado || "", txt: e.textContent || "", clase: e.className,
      }));
    } catch (e) {
      const vivo = await page.$eval(`${sel} .md-progreso`, (n) => n.textContent.replace(/\s+/g, " ").trim())
        .catch(() => "(sin bloque de progreso)");
      const job = await fetch(FUENTE + "/v1/modelos/descarga/" + API_SLUG(CHICO.id))
        .then((r) => r.json()).catch((x) => ({ error: String(x) }));
      ok(false, "la descarga TERMINA en un desenlace visible",
         `sin desenlace tras 300 s · pantalla: «${vivo}» · backend: ${JSON.stringify(job).slice(0, 200)}`);
      await page.screenshot({ path: join(SHOTS, "p8-descarga-colgada.png"), fullPage: true });
      desen = { estado: "(ninguno)", txt: "", clase: "" };
    }
    ok(desen.estado === "probado", "la descarga TERMINA en 🟢 probado (la salida de éxito rige)", desen.estado);
    ok(/verde/.test(desen.clase), "pintado en verde");
    ok(/\d/.test(desen.txt), "con EVIDENCIA de lo que el modelo contestó de verdad", desen.txt.trim().slice(0, 80));
    ok(/probado a las|tested at/i.test(desen.txt), "y su TIMESTAMP", desen.txt.trim().slice(-40));
    ok(!/paso|siguiente|ahora .*prob/i.test(desen.txt.replace(/probado/gi, "")),
       "el workflow termina ahí: no pide un paso extra");
    await page.screenshot({ path: join(SHOTS, "p8-descarga-verde.png"), fullPage: true });

    // 10c · y la fila LOCAL quedó 🟢 sola, sin recargar a mano.
    await page.waitForTimeout(1200);
    const filaVerde = await page.$$eval('#mdFilas .md-grupo[data-familia="local"] .md-fila', (ls) =>
      ls.map((l) => ({ slug: l.dataset.slug, estado: l.dataset.estado })));
    ok(filaVerde.some((f) => f.estado === "probado"), "la fila local quedó 🟢 sin un paso extra",
       JSON.stringify(filaVerde.map((f) => f.estado)));
  }
}

seccion("11 · CAPABILITY GATING — pieza alta + modelo chico → aviso, JAMÁS corre");
{
  const g = await (await fetch(FUENTE + "/v1/modelos/gate?pieza=codigo&slug=local.x&tier=chico&categoria=codigo&familia=local")).json();
  ok(g.alcanza === false, "una pieza que pide `medio` con un modelo `chico` NO alcanza");
  ok(/necesita un modelo medio/i.test(g.es), "y lo dice en palabras, con el tier exacto", g.es);
  ok(!!g.porque_es && g.porque_es.length > 20, "con el PORQUÉ, no sólo el veredicto", g.porque_es.slice(0, 60));
  ok(!!g.recomendacion && g.recomendacion.descargar === true && g.recomendacion.api === true,
     "y con las DOS salidas: [Descargar este] y [Conectar API]");
  // CALIBRACIÓN #3: la misma pieza con un modelo que SÍ alcanza tiene que pasar. Un gate
  // que dice que no a todo no es un gate, es una pared.
  const g2 = await (await fetch(FUENTE + "/v1/modelos/gate?pieza=codigo&slug=api.groq&familia=api")).json();
  ok(g2.alcanza === true, "CALIBRACIÓN #3 ✓ la misma pieza con un modelo capaz SÍ alcanza");
  // capacidad ≠ tier: un modelo grande de sólo-texto no hace visión, y se dice distinto.
  const g3 = await (await fetch(FUENTE + "/v1/modelos/gate?pieza=vision&slug=api.groq&familia=api")).json();
  ok(g3.alcanza === false && g3.falta_capacidad === true && g3.falta_tier === false,
     "falta de CAPACIDAD y falta de TIER son cosas distintas y se distinguen", g3.es);
  // Y en la UI: el candado con su porqué y sus salidas.
  const localFila = await page.$('#mdFilas .md-grupo[data-familia="local"] .md-fila');
  if (localFila) {
    await localFila.$eval(".md-abrir", (b) => b.click());
    await page.waitForTimeout(500);
    const roles = await localFila.$$eval(".md-rol", (rs) => rs.map((r) => ({
      txt: r.textContent.trim(), no: r.classList.contains("no"),
      titulo: r.getAttribute("title") || "",
    })));
    ok(roles.length >= 4, `la fila declara para qué sirve y para qué no (${roles.length} piezas)`);
    ok(roles.some((r) => r.no), "y al menos una sale con 🔒");
    ok(roles.filter((r) => r.no).every((r) => r.titulo.length > 10), "cada 🔒 con su porqué");
    const por = (await localFila.$eval(".md-rol-por", (e) => e.textContent).catch(() => "")) || "";
    ok(/descargar|download|conectar|connect/i.test(por), "y el bloque de bloqueo ofrece la SALIDA", por.slice(0, 90));
  } else ok(false, "no hay fila local sobre la que medir el gating en la UI");
}

seccion("12 · EL GUÍA ES FRONTIER-ONLY");
{
  const gGuia = await (await fetch(FUENTE + "/v1/modelos/gate?pieza=guia&slug=local.chico&tier=chico&familia=local")).json();
  ok(gGuia.alcanza === false, "un modelo no-frontier NO puede ser el Guía");
  ok(gGuia.min_tier === "frontier", "porque la pieza declara `frontier` como mínimo");
  ok(/frontier/i.test(gGuia.es), "y el aviso nombra el tier que falta", gGuia.es);
  const gOk = await (await fetch(FUENTE + "/v1/modelos/gate?pieza=guia&slug=cli.claude_cli&familia=cli")).json();
  ok(gOk.alcanza === true, "y un frontier SÍ puede (el gate no es una pared)");
  // misma vara que el Cuarto y que el backend del Guía: fail-closed sobre la lista.
  const py = await readFile(join(REPO, "product", "backend", "app", "phase1", "centro_modelos.py"), "utf8");
  const cu = await readFile(join(REPO, "product", "backend", "app", "phase1", "cuarto_guide.py"), "utf8");
  ok(/FRONTIER_SLUGS/.test(py) && /_es_frontier_guia/.test(cu),
     "la regla frontier vive en las dos puntas y se nombra igual");
  // en la UI: el rol Guía sale 🔒 sobre un modelo local
  const li = await page.$('#mdFilas .md-grupo[data-familia="local"] .md-fila');
  if (li) {
    const guia = await li.$$eval('.md-rol[data-pieza="guia"]', (rs) => rs.map((r) => ({
      no: r.classList.contains("no"), t: r.getAttribute("title") })));
    ok(guia.length === 1 && guia[0].no === true, "en la pantalla, «El Guía» sale bloqueado sobre un modelo local");
    ok(guia[0] && /frontier|modelo/i.test(guia[0].t || ""), "con su porqué", guia[0] && guia[0].t);
  }
}

seccion("13 · LOS 5 ESTADOS DEL SEMÁFORO");
{
  const vivos = await page.$$eval("#mdFilas .md-fila", (ls) => {
    const m = {};
    ls.forEach((l) => {
      m[l.dataset.estado] = m[l.dataset.estado] || {
        glifo: (l.querySelector(".md-luz") || {}).textContent || "",
        palabra: (l.querySelector(".md-estado") || {}).textContent || "",
        camino: (l.querySelector(".md-camino, .md-probar") || {}).textContent || "",
      };
    });
    return m;
  });
  const GLIFO = { probado: "🟢", detectado: "🟡", roto: "🔴", no_configurado: "⚪", premium: "🔒" };
  for (const est of Object.keys(GLIFO)) {
    if (vivos[est]) {
      ok(vivos[est].glifo.trim() === GLIFO[est], `[real] ${est} → ${GLIFO[est]}`, vivos[est].glifo);
      ok(vivos[est].palabra.trim().length > 0, `[real] ${est} dice su palabra`, vivos[est].palabra.trim().slice(0, 40));
    }
  }
  ok(Object.keys(vivos).length >= 3, `${Object.keys(vivos).length} estados vinieron de datos REALES`,
     Object.keys(vivos).join(", "));

  // ROTO de verdad: se le pregunta al backend por un modelo local cuyo runtime no está.
  const rotoR = await fetch(FUENTE + "/v1/modelos/probar", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug: "no-existe-en-el-manifiesto" }),
  });
  const roto = await rotoR.json();
  ok(roto.estado === "roto" && roto.causa === "sin_runtime",
     "[real] un modelo sin runtime da 🔴 con causa `sin_runtime`", roto.causa);
  ok((roto.detalle || "").length > 10, "y con detalle legible, no un código", roto.detalle);

  // Los 5, con su glifo, su palabra Y SU CAMINO, por el diccionario compartido.
  const mapa = await page.evaluate(async () => {
    const M = await import("./modelos/modelos.semaforo.js");
    const out = {};
    for (const e of ["probado", "detectado", "roto", "no_configurado", "premium"]) {
      const cam = M.caminoModelo({ estado: e, causa: e === "roto" ? "sin_runtime" : null });
      out[e] = { g: M.ESTADO[e].g, es: M.ESTADO[e].es, camino: cam ? cam.es : null };
    }
    out.__ext = ["sin_runtime", "sin_espacio", "descarga_cancelada"].map((c) => {
      const cam = M.caminoModelo({ estado: "roto", causa: c });
      return { c, boton: cam ? cam.es : null };
    });
    return out;
  });
  for (const e of Object.keys(GLIFO)) {
    ok(mapa[e].g === GLIFO[e] && mapa[e].es.length > 0, `los 5 renderizan: ${e} ${mapa[e].g} «${mapa[e].es}»`);
  }
  ok(mapa.probado.camino === null, "🟢 no fuerza camino (verde no es una tarea)");
  ok(["detectado", "roto", "no_configurado", "premium"].every((e) => !!mapa[e].camino),
     "y los 4 no-verdes SIEMPRE ofrecen un camino",
     ["detectado", "roto", "no_configurado", "premium"].map((e) => `${e}→${mapa[e].camino}`).join(" · "));
  ok(mapa.__ext.every((x) => !!x.boton), "las 3 causas propias de modelo tienen su botón",
     mapa.__ext.map((x) => `${x.c}→${x.boton}`).join(" · "));
}

seccion("14 · LAS CARAS — marca comercial empaquetada · avatar de HF sólo desde cache");
{
  const caras = await page.$$eval("#mdFilas .md-fila .md-face-h", (hs) => hs.map((h) => {
    const img = h.querySelector("img");
    return { tipo: img ? "img" : (h.querySelector(".binit") ? "iniciales" : "otro"),
             cargada: img ? img.naturalWidth > 0 : null,
             src: img ? img.getAttribute("src") : null };
  }));
  ok(caras.length > 0, `${caras.length} filas con cara`);
  const rotas = caras.filter((c) => c.tipo === "img" && c.cargada === false);
  ok(rotas.length === 0, "ninguna cara es un <img> roto (un 404 degrada en silencio)", rotas.length);
  // El avatar de HF NO se pide en caliente: sale del endpoint de CACHE del sidecar.
  const hfImgs = caras.filter((c) => c.src && c.src.indexOf("/v1/modelos/avatar/") >= 0);
  ok(hfImgs.every((c) => !/huggingface\.co/.test(c.src)),
     "los avatares de HF salen del cache del sidecar, nunca de la red en caliente");
  const pedidosExternos = [];
  page.on("request", (r) => { if (/^https?:\/\/(?!127\.0\.0\.1)/.test(r.url())) pedidosExternos.push(r.url()); });
  await abrir();
  await page.waitForTimeout(1500);
  ok(pedidosExternos.length === 0, "la pantalla no hace UN SOLO pedido a un tercero desde el browser",
     pedidosExternos.slice(0, 2).join(" · "));
}

seccion("15 · EL CHAT OFRECE EL CAMINO Y ATERRIZA EN LA CATEGORÍA");
{
  const src = await readFile(join(DESIGN, "chat", "opciones.js"), "utf8");
  ok(/CAT_DE_FALTA/.test(src) && /sin_vision:\s*"vision"/.test(src),
     "el contrato del chat mapea `sin_vision` → categoría `vision`");
  ok(/Modelos\.dc\.html\?cat=/.test(src) || /setupHrefPorCausa/.test(src),
     "y el destino es el Centro de Modelos con la categoría");
  const bs = await readFile(join(DESIGN, "brain-status.js"), "utf8");
  ok(/Modelos\.dc\.html/.test(bs), "el EMBUDO compartido (setupHref) apunta al Centro de Modelos");
  ok(/setupHrefPorCausa/.test(bs), "y expone el atajo por causa para las demás superficies");
  // el aterrizaje REAL: ?cat=vision deja la categoría abierta y enfocada
  await page.goto(PAGE + "?cat=vision", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#mdCat .md-tab.on", { timeout: 25000 });
  const abierta = await page.$eval("#mdCat .md-tab.on", (b) => b.dataset.cat);
  ok(abierta === "vision", "llegar con ?cat=vision deja ABIERTA la categoría visión", abierta);
  const sel = await page.$eval("#mdCat .md-tab.on", (b) => b.getAttribute("aria-selected"));
  ok(sel === "true", "y marcada como seleccionada para lectores de pantalla");
  await page.goto(PAGE + "?modo=local", { waitUntil: "domcontentloaded" });
  await page.waitForSelector('#mdFilas .md-grupo[data-familia="local"]', { timeout: 25000 });
  ok(true, "y ?modo=local aterriza en el grupo de los locales");
  await page.screenshot({ path: join(SHOTS, "p8-foco-vision.png"), fullPage: true });
}

seccion("16 · EL DEFAULT DE ARRANQUE — el bug de instalación (hallazgo de P10)");
{
  // EL BUG, medido en la máquina de un humano: instalás, abrís la Sala y el composer está
  // apagado. Sin configuración guardada el default caía SIEMPRE en «Incluido», que en el
  // artefacto instalado no trae llave → not_configured → blockExecution. Sobrevive a
  // cerrar y reabrir porque es estado de ENTORNO, no de sesión.
  const limpio = async () => {
    await page.evaluate(() => {
      localStorage.removeItem("aleph-brain-configuration");
      localStorage.removeItem("aleph-active-brain");
      localStorage.removeItem("aleph-active-byok-provider");
    });
    await abrir();
    return await page.evaluate(async () => {
      const s = await window.AlephBrain.resolve({ refresh: true });
      return { id: s.id, active: s.active, state: s.state, block: s.blockExecution,
               auto: !!s.auto, noUsable: !!s.noUsable, label: s.label,
               detail: s.detail, accion: s.action && s.action.label, href: s.action && s.action.href };
    });
  };

  // ── ARRANQUE LIMPIO, máquina real ────────────────────────────────────────────
  RUTA.brains = "real";
  const real = await limpio();
  const brains = await (await fetch(FROZEN + "/v1/brains/status")).json().catch(() => ({}));
  const hayAlguno = Object.values(brains.providers || {}).some((x) => x && x.state === "ready");
  console.log(`  · proveedores ready en esta máquina: ${Object.entries(brains.providers || {})
    .filter(([, v]) => v && v.state === "ready").map(([k]) => k).join(", ") || "ninguno"}`);
  ok(real.auto === true, "sin configuración guardada, el default se ELIGE (no se hereda de una constante)");
  if (hayAlguno) {
    ok(real.block === false, "arranque limpio → el default elegido es UTILIZABLE (el chat no queda bloqueado)",
       `${real.id} · ${real.state}`);
    ok(real.state === "healthy", "y su estado es sano de verdad, verificado contra /v1/brains/status", real.state);
    ok(real.id !== "included" || (brains.providers.included || {}).state === "ready",
       "«Incluido» sólo es el default si de verdad funciona sin llave", real.id);
  } else {
    ok(real.noUsable === true, "sin nada utilizable, el arranque lo DICE (no elige uno roto en silencio)");
  }

  // ── CALIBRACIÓN EN ROJO: la máquina de un usuario nuevo, sin nada utilizable ──
  RUTA.brains = "nada";
  const nada = await limpio();
  ok(nada.active === "none" && nada.noUsable === true,
     "CALIBRACIÓN ✗→ con TODO sin configurar, el default no finge: dice que no hay ninguno",
     `${nada.active} · noUsable=${nada.noUsable}`);
  ok(nada.block === true, "el bloqueo sigue siendo real (no se puede ejecutar sin modelo)");
  ok(/no hay ning[úu]n modelo utilizable|no usable model/i.test(nada.detail || ""),
     "PERO NO ES MUDO: explica exactamente qué pasa", (nada.detail || "").slice(0, 90));
  ok(/conectar un modelo|connect a model/i.test(nada.accion || ""),
     "y ofrece EL CAMINO: [Conectar un modelo]", nada.accion);
  ok(/Modelos\.dc\.html/.test(nada.href || ""), "que lleva al Centro de Modelos", nada.href);
  // y el chip lo MUESTRA (es la superficie que aparece en todas las pantallas)
  const chip = await page.evaluate(async () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    await window.AlephBrain.mount(host, {}).update({ refresh: true });
    return { txt: host.textContent || "", cls: host.className,
             boton: (host.querySelector(".aleph-brain-action") || {}).textContent || "" };
  });
  ok(/bad/.test(chip.cls), "el chip se pinta en ROJO (no en gris de «cargando»)", chip.cls);
  ok(/conectar un modelo|connect a model/i.test(chip.boton), "y su botón es el camino", chip.boton.trim());
  ok(!/^\s*$/.test(chip.txt), "el chip nunca queda vacío", chip.txt.trim().slice(0, 60));
  await page.screenshot({ path: join(SHOTS, "p8-sin-modelo-utilizable.png") });

  RUTA.brains = "real";
  await limpio();
}

seccion("17 · HIGIENE");
{
  // Los 404 se miden por URL, no por el texto del mensaje: WebKit no la incluye en la
  // consola, así que filtrar por texto habría tapado un 404 de verdad. La primera corrida
  // dio rojo acá y era REAL — la pantalla pedía un avatar que sabía que no existía.
  const graves = consolaMala.filter((m) => !/favicon/i.test(m));
  ok(graves.length === 0, "cero errores de consola", graves.slice(0, 3).join(" | "));
  const rotos = fallos404.filter((u) => !/favicon/i.test(u));
  ok(rotos.length === 0, "cero pedidos que devuelven 4xx/5xx", rotos.slice(0, 4).join(" · "));
}

// ══════════════════════════════════════════════════════════════════════════════════════
console.log(`\n${"═".repeat(78)}`);
// [H3] Las capturas van ARRIBA: la última línea de una vara es su veredicto.
console.log(`capturas: ${SHOTS}`);
if (fails.length) { console.log("\nFALLAS:"); fails.forEach((f) => console.log("  ✗ " + f)); }
console.log(`FIX-P8 · Centro de Modelos:  ${total - fails.length} ✓  /  ${fails.length} ✗`);

await browser.close();
server.close();
matar();
process.exit(fails.length ? 1 : 0);
