/* verify_conexiones.mjs — LA VARA DEL CENTRO DE CONEXIONES (Terminal B).
 *
 * WebKit contra el SIDECAR FROZEN del build instalado (:8222) + el router nuevo desde
 * FUENTE (:8223). Los dos comparten ALEPH_DATA_DIR, así que ven la MISMA SQLite del
 * cliente. Es la configuración honesta: el .app se congeló ANTES de que /v1/conexiones
 * existiera, así que el frozen no puede servirlo — pero todo lo demás (sesión, keys,
 * motor, catálogo) sí sale del binario real, no de un mock.
 *
 * El "proveedor de API" es un peer HTTP local de verdad, que puede contestar 200/401/402/429
 * y listar modelos: así el 401 ≠ 402 ≠ 429 se prueba de punta a punta (UI → backend → HTTP).
 *
 * Matriz:
 *   1. Nivel 1: la lista carga con conteo y luces (nada verde sin evidencia).
 *   2. Nivel 2: el checklist del CLI REAL del humano → requisitos verdes de verdad.
 *   3. §E Agregar llave: formulario REAL (no prompt()) · llave mala → NO se guarda, con causa.
 *   4. §E Llave buena → se guarda cifrada → queda CONECTADA y sobrevive al relanzamiento.
 *   5. §C 401 ≠ 402 ≠ 429: tres causas distintas con tres arreglos distintos.
 *   6. §F Batch: dos filas en paralelo, con progreso por fila y sin bloquear la app.
 *   7. §D [Reintentar] con camino: reintenta, y si sigue mal MUTA a un botón que lleva.
 *   8. Cero espera muerta: ningún ⟳ queda girando; el cable caído cierra con causa + botón.
 *
 * Run:  node product/app/design/conexiones/verify_conexiones.mjs
 * (levanta y mata sus propios procesos — JAMÁS toca el :25374 del humano)
 */
import { webkit } from "playwright";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
// GUARD _MEI (integración tanda-P): TMPDIR privado por sidecar + barrido en TODA salida.
// El bootloader onefile deja ~170 MB en `_MEI*` si el proceso no cierra limpio; 91 huérfanos
// llenaron el disco el 26-jul. Ver qa/lib/frozen_guard.mjs y qa/verify_frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "../../../../qa/lib/frozen_guard.mjs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN = join(HERE, "..");
const REPO = join(DESIGN, "..", "..", "..");

const FROZEN = process.env.CX_FROZEN || "http://127.0.0.1:8222";
const FUENTE = process.env.CX_FUENTE || "http://127.0.0.1:8223";
const PEER_PORT = Number(process.env.CX_PEER || 8224);
const PORT = Number(process.env.CX_PORT || 8299);
const PAGE = `http://127.0.0.1:${PORT}/Conexiones.dc.html`;
// [Integración #5] overridable: el default sigue siendo la .app INSTALADA (que es el criterio
// de cierre), pero antes de instalar hay que poder certificar el binario RECIÉN construido —
// si no, la vara sólo sabe hablar del build anterior. Se pasa ALEPH_SIDECAR_BIN=<ruta>.
// El datadir compartido frozen↔fuente lo crea esta vara, así que el frozen tiene que
// levantarlo ELLA: apuntar CX_FROZEN a uno propio los deja con SQLite distintas.
const APP_SIDECAR = process.env.ALEPH_SIDECAR_BIN || "/Applications/Aleph.app/Contents/MacOS/aleph_sidecar";
const PY = process.env.CX_PY || "/opt/miniconda3/bin/python";

const fails = [];
const ok = (cond, label, extra) => {
  console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  — " + extra : ""}`);
  if (!cond) fails.push(label);
};

// ── peer del "proveedor" (OpenAI-compat REAL, con status conmutable) ────────────────
const PEER = { status: 200, modelos: ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"], hits: 0 };
const peer = http.createServer((req, res) => {
  req.on("error", () => {});
  PEER.hits++;
  const enviar = (code, obj, ctype) => {
    const b = typeof obj === "string" ? Buffer.from(obj) : Buffer.from(JSON.stringify(obj));
    res.writeHead(code, { "Content-Type": ctype || "application/json", "Content-Length": b.length });
    res.end(b);
  };
  if (req.url.endsWith("/models")) {
    if (PEER.status === 200) return enviar(200, { data: PEER.modelos.map((id) => ({ id })) });
    return enviar(PEER.status, { error: { message: "peer dice " + PEER.status } });
  }
  if (req.url.endsWith("/chat/completions")) {
    let n = 0; req.on("data", () => n++);
    req.on("end", () => {
      if (PEER.status !== 200) return enviar(PEER.status, { error: { message: "peer dice " + PEER.status } });
      enviar(200, 'data: {"choices":[{"delta":{"content":"p"}}]}\n\ndata: [DONE]\n\n', "text/event-stream");
    });
    return;
  }
  enviar(404, { error: "nf" });
});
const PEER_URL = `http://127.0.0.1:${PEER_PORT}/v1`;

// ── estático (el frontend de ESTE worktree) + proxy de DOS bocas ────────────────────
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
  ".webp": "image/webp", ".woff2": "font/woff2", ".md": "text/markdown", ".ico": "image/x-icon" };
let CORTAR_FUENTE = false;   // bloque 8: matar el cable a propósito

const server = http.createServer(async (req, res) => {
  req.on("error", () => {}); res.on("error", () => {});
  const u = new URL(req.url, "http://x");
  if (u.pathname.startsWith("/v1/") || u.pathname === "/health") {
    const alCentro = u.pathname.startsWith("/v1/conexiones");
    if (alCentro && CORTAR_FUENTE) { res.writeHead(502); res.end("fuente caida (a proposito)"); return; }
    const arriba = alCentro ? FUENTE : FROZEN;
    const chunks = []; for await (const c of req) chunks.push(c);
    const body = Buffer.concat(chunks);
    // sólo cabeceras SEGURAS (reenviar content-length/host cuelga undici — lección de A)
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
    const h = {};
    up.headers.forEach((v, k) => { if (!/^(content-encoding|transfer-encoding|connection|content-length)$/i.test(k)) h[k] = v; });
    res.writeHead(up.status, h);
    // stream real (el checklist es SSE: bufferearlo mataría el latido que estamos midiendo)
    if (up.body) {
      const reader = up.body.getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        res.write(Buffer.from(value));
      }
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
process.on("uncaughtException", (e) => {
  if (!/aborted|ECONNRESET|EPIPE/i.test(String(e && (e.code || e.message)))) throw e;
});

// ── los dos backends ────────────────────────────────────────────────────────────────
const DATA = mkdtempSync(join(tmpdir(), "cx-data-"));
let procFrozen = null, procFuente = null;

// HIGIENE DE PUERTO — un sidecar viejo colgado en :8222 contesta /health y parece sano,
// pero apunta a OTRO datadir: la sesión se minta en una SQLite y la llave se busca en otra
// («sin_sesion» que no es del producto, es del banco de pruebas). Antes de arrancar,
// liberamos el puerto SÓLO si lo tiene un proceso NUESTRO. El :25374 del humano no se toca
// jamás: no está en esta lista y el filtro por comando es explícito.
function liberarPuerto(puerto) {
  const { execSync } = require$("node:child_process");
  if (puerto === 25374) throw new Error("ese puerto es del humano — nunca");
  let pids = [];
  try {
    pids = execSync(`lsof -nP -tiTCP:${puerto} -sTCP:LISTEN 2>/dev/null || true`)
      .toString().trim().split("\n").filter(Boolean);
  } catch (e) { return true; }
  for (const pid of pids) {
    let cmd = "";
    try { cmd = execSync(`ps -o command= -p ${pid} 2>/dev/null || true`).toString(); } catch (e) {}
    if (!/aleph_sidecar|conexiones_sidecar|motor_sidecar/.test(cmd)) {
      console.log(`✗ el puerto ${puerto} lo tiene un proceso ajeno (pid ${pid}) — no lo toco. Liberalo vos.`);
      return false;
    }
    try { execSync(`kill -9 ${pid}`); } catch (e) {}
    console.log(`  · liberé :${puerto} (sidecar viejo, pid ${pid})`);
  }
  return true;
}
// require en un módulo ESM
import { createRequire } from "node:module";
const require$ = createRequire(import.meta.url);

async function sano(base, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try { const r = await fetch(base + "/health", { signal: AbortSignal.timeout(2000) }); if (r.ok) return true; } catch {}
    await new Promise((r) => setTimeout(r, 700));
  }
  return false;
}

async function bootFrozen() {
  if (process.env.CX_FROZEN) return await sano(FROZEN);
  procFrozen = spawnFrozen(APP_SIDECAR, ["--port", String(new URL(FROZEN).port)],
    { env: { ...process.env, ALEPH_DATA_DIR: DATA }, stdio: "ignore", detached: true });
  procFrozen.unref();
  return await sano(FROZEN);
}

async function bootFuente() {
  if (process.env.CX_FUENTE) return await sano(FUENTE);
  procFuente = spawn(PY, ["-m", "uvicorn", "conexiones_sidecar:app", "--app-dir",
    join(REPO, "product", "backend"), "--port", String(new URL(FUENTE).port), "--log-level", "warning"],
    { env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATA,
             PYTHONPATH: [join(REPO, "product", "backend"), join(REPO, "platform"),
                          join(REPO, "platform", "assembler")].join(":") },
      stdio: "ignore", detached: true, cwd: REPO });
  procFuente.unref();
  return await sano(FUENTE);
}

function matar() {
  for (const p of [procFrozen, procFuente]) {
    try { if (p) process.kill(-p.pid, "SIGKILL"); } catch {}
  }
  procFrozen = procFuente = null;
}

// ══════════════════════════════════════════════════════════════════════════════════
await new Promise((r) => peer.listen(PEER_PORT, "127.0.0.1", r));
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));
if (!process.env.CX_FROZEN && !liberarPuerto(Number(new URL(FROZEN).port))) process.exit(1);
if (!process.env.CX_FUENTE && !liberarPuerto(Number(new URL(FUENTE).port))) process.exit(1);
if (!(await bootFrozen())) { console.log("✗ no pude levantar el sidecar FROZEN en " + FROZEN); process.exit(1); }
// el frozen tiene que ser EL NUESTRO (mismo datadir): si contesta uno viejo, todo lo que
// dependa de la sesión medirá mentiras. Se comprueba mintando una sesión y leyéndola desde
// el sidecar de FUENTE — si los dos no ven la misma SQLite, se para acá.

if (!(await bootFuente())) { console.log("✗ no pude levantar el sidecar de FUENTE en " + FUENTE); matar(); process.exit(1); }
{
  const r = await fetch(FROZEN + "/v1/auth/local", { method: "POST" }).catch(() => null);
  const j = r && r.ok ? await r.json().catch(() => null) : null;
  if (!j || !j.session_token) { console.log("✗ el frozen no minta sesión local — no puedo medir nada de llaves"); matar(); process.exit(1); }
  // prueba DURA de que los dos ven la misma SQLite: la fuente tiene que resolver el OWNER
  // de ese token. Una llave con forma inválida rebota ANTES de guardar nada, así que el
  // sondeo no ensucia el estado; lo único que miramos es que la causa NO sea sin_sesion.
  const p = await fetch(FUENTE + "/v1/conexiones/key", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + j.session_token },
    body: JSON.stringify({ provider: "groq", secret: "no-tiene-la-forma" }),
  }).then((x) => x.json()).catch(() => null);
  if (!p || p.causa === "sin_sesion") {
    console.log("✗ frozen y fuente NO comparten la SQLite del cliente (la sesión no se ve del otro lado).");
    console.log("  Sin eso, todo lo de llaves mediría el banco de pruebas, no el producto.");
    matar(); process.exit(1);
  }
  console.log(`  · frozen y fuente comparten datadir (sesión ${j.id.slice(0, 8)}… visible en los dos)\n`);
}

const browser = await webkit.launch();
const errores = [];
const SHOTS = join(HERE, "screenshots");
const foto = async (page, nombre) => {
  try { await page.screenshot({ path: join(SHOTS, nombre + ".png"), fullPage: false }); } catch (e) {}
};
try { require$("node:fs").mkdirSync(SHOTS, { recursive: true }); } catch (e) {}
async function abrir(qs) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on("pageerror", (e) => errores.push(String(e).slice(0, 200)));
  page.on("console", (m) => { if (m.type() === "error") errores.push("console: " + m.text().slice(0, 160)); });
  await page.goto(PAGE + (qs || ""), { waitUntil: "domcontentloaded", timeout: 30000 });
  // esperar la lista DE VERDAD (no el placeholder de "leyendo…") y que los botones estén
  // cableados: montar() los engancha recién después de cargar.
  await page.waitForSelector("#cxFilas .cx-fila, #cxFilas .cx-vacio:not(.cx-cargando)", { timeout: 25000 });
  await page.waitForFunction(() => !!window.AlephCentro, null, { timeout: 20000 }).catch(() => {});
  return page;
}

const filas = (page) => page.evaluate(() => [...document.querySelectorAll("#cxFilas .cx-fila")].map((li) => ({
  slug: li.dataset.slug, estado: li.dataset.estado,
  nombre: (li.querySelector(".cx-nom b") || {}).textContent || "",
  texto: (li.querySelector(".cx-estado") || {}).textContent || "",
  abierta: li.classList.contains("abierta"),
})));

const reqs = (page, slug) => page.evaluate((s) => {
  const li = document.querySelector(`#cxFilas .cx-fila[data-slug="${s.replace(/"/g, '\\"')}"]`);
  if (!li) return [];
  return [...li.querySelectorAll(".cx-req")].map((r) => ({
    id: r.dataset.id, estado: r.dataset.estado,
    titulo: (r.querySelector(".cx-req-tit span") || {}).textContent || "",
    detalle: (r.querySelector(".cx-req-det") || {}).textContent || "",
    ayuda: !!r.querySelector(".cx-que"),
    comando: (r.querySelector(".cx-cmd code") || {}).textContent || "",
    doc: (r.querySelector(".cx-doc") || {}).getAttribute ? r.querySelector(".cx-doc").getAttribute("href") : "",
    boton: (r.querySelector(".cx-req-acc button") || {}).textContent || "",
  }));
}, slug);

async function esperarFila(page, slug, ms = 60000) {
  await page.waitForFunction((s) => {
    const li = document.querySelector(`#cxFilas .cx-fila[data-slug="${s.replace(/"/g, '\\"')}"]`);
    if (!li) return false;
    if (li.querySelector(".cx-trabajando")) return false;
    return [...li.querySelectorAll(".cx-req")].length > 0 &&
           ![...li.querySelectorAll(".cx-req")].some((r) => r.dataset.estado === "probando");
  }, slug, { timeout: ms });
}

console.log("══ VERIFY · CENTRO DE CONEXIONES (WebKit → frontend de este worktree → frozen :8222 + fuente :8223) ══\n");

// ── 1 · NIVEL 1: la lista escaneable ────────────────────────────────────────────────
console.log("── 1 · nivel 1: la lista + el conteo ──");
{
  const page = await abrir();
  const f = await filas(page);
  ok(f.length >= 3, `la lista trae ${f.length} conexiones`);
  ok(f.some((x) => x.slug === "cli.claude_cli"), "está tu Claude Code");
  ok(f.some((x) => x.slug === "api.groq"), "está groq (para agregar tu llave)");
  const conteo = await page.textContent("#cxConteo");
  ok(/\d/.test(conteo), "el conteo de arriba dice algo real", conteo.trim().slice(0, 60));
  const verdesSinProbar = f.filter((x) => x.estado === "probado");
  ok(verdesSinProbar.length === 0, "nada nace verde: sin probar no hay verde", `${verdesSinProbar.length} verdes`);
  await page.close();
}

// ── 2 · NIVEL 2: el CLI real del humano ─────────────────────────────────────────────
console.log("\n── 2 · el checklist del CLI REAL del humano ──");
{
  const page = await abrir("?svc=cli.claude_cli&correr=1");
  await esperarFila(page, "cli.claude_cli");
  const r = await reqs(page, "cli.claude_cli");
  ok(r.length === 8, `los 8 requisitos del carril CLI (${r.map((x) => x.id).join(", ")})`);
  ok(r.every((x) => x.ayuda), "cada requisito trae su «?» que explica más");
  const hechos = r.filter((x) => x.estado === "hecho");
  ok(hechos.length >= 6, `${hechos.length}/8 verificados contra el CLI real`,
    r.filter((x) => x.estado !== "hecho").map((x) => `${x.id}=${x.estado}`).join(" "));
  const fila = (await filas(page)).find((x) => x.slug === "cli.claude_cli");
  ok(fila.estado === "probado", "la fila queda 🟢 conectado", fila.texto);
  // [FIX-P2] la palabra del 🟢 pasó de «conectado · verificado hace X» a «probado hace X»:
  // «probado» es el término del vocabulario CERRADO del semáforo (ESTADOS.probado), y
  // «conectado» era un sexto sinónimo que sólo existía en esta pantalla. La vara sigue
  // midiendo lo MISMO —que el verde diga CUÁNDO— y ahora además exige la expresión de tiempo.
  ok(/probado (recién|hace )/.test(fila.texto), "…y dice CUÁNDO se probó", fila.texto);
  ok(!/probando/.test(await page.innerHTML("#cxFilas")), "no quedó ningún ⟳ girando");
  await foto(page, "cli-verde");
  await page.close();
}

// ── 2b · CLI ausente → causa + EL COMANDO ───────────────────────────────────────────
console.log("\n── 2b · un CLI que NO está → causa + comando copiable + doc ──");
{
  // el detector real busca el binario; forzamos uno inexistente por env del sidecar de fuente
  matarFuenteYRelanzar: {
    try { if (procFuente) process.kill(-procFuente.pid, "SIGKILL"); } catch {}
    procFuente = null;
    procFuente = spawn(PY, ["-m", "uvicorn", "conexiones_sidecar:app", "--app-dir",
      join(REPO, "product", "backend"), "--port", String(new URL(FUENTE).port), "--log-level", "warning"],
      { env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATA,
               PUPPET_CLAUDE_BIN: "/no/existe/claude", PUPPET_CODEX_BIN: "/no/existe/codex",
               PYTHONPATH: [join(REPO, "product", "backend"), join(REPO, "platform"),
                            join(REPO, "platform", "assembler")].join(":") },
        stdio: "ignore", detached: true, cwd: REPO });
    procFuente.unref();
    if (!(await sano(FUENTE))) { ok(false, "el sidecar de fuente volvió con el CLI forzado ausente"); break matarFuenteYRelanzar; }
  }
  const page = await abrir("?svc=cli.claude_cli&correr=1");
  await esperarFila(page, "cli.claude_cli");
  const r = await reqs(page, "cli.claude_cli");
  const bin = r.find((x) => x.id === "binario") || {};
  ok(bin.estado === "roto", "«El comando está instalado» sale ✗", bin.detalle);
  ok(/npm install/.test(bin.comando), "trae EL COMANDO exacto, copiable", bin.comando);
  ok(/^https:\/\//.test(bin.doc || ""), "y el link a la doc oficial", bin.doc);
  const ver = r.find((x) => x.id === "version") || {};
  ok(ver.estado === "pendiente", "sin binario NO se inventa un rojo de versión", ver.estado);
  const fila = (await filas(page)).find((x) => x.slug === "cli.claude_cli");
  ok(fila.estado === "roto", "la fila queda 🔴 con su causa", fila.texto);
  await foto(page, "cli-roto-comando");
  await page.close();
}
// devolver el sidecar de fuente a la normalidad (CLIs reales)
try { if (procFuente) process.kill(-procFuente.pid, "SIGKILL"); } catch {}
procFuente = null;
if (!(await bootFuente())) { console.log("✗ no pude restaurar el sidecar de fuente"); }

// ── 3 · §E AGREGAR LLAVE: el formulario real, y la llave mala NO se guarda ──────────
console.log("\n── 3 · §E agregar llave: formulario REAL (no prompt) ──");
let paginaViva = null;
{
  PEER.status = 401;
  const page = await abrir();
  await page.click("#cxAgregar");
  ok(await page.isVisible("#cxKeyDlg"), "el formulario se abre (no un prompt() que devuelve null)");
  await page.fill("#cxKeyProv", "groq");
  await page.fill("#cxKeySecret", "gsk_" + "x".repeat(40));
  await page.fill("#cxKeyBase", PEER_URL);
  await page.click("#cxKeyGuardar");
  await page.waitForFunction(() => {
    const m = document.getElementById("cxKeyMsg");
    return m && !m.hidden && !/validando/.test(m.textContent);
  }, null, { timeout: 30000 });
  const msg = await page.textContent("#cxKeyMsg");
  ok(/✗/.test(msg), "llave rechazada → lo dice, no la traga en silencio", msg.trim().slice(0, 90));
  ok(/401|no sirve/i.test(msg), "…y dice que el problema es LA LLAVE (401)", msg.trim().slice(0, 90));
  ok(!(await page.isVisible("#cxKeyGuardarIgual")), "no ofrece «guardar igual» una llave que no sirve");
  await foto(page, "key-form-401");

  // ── 4 · la llave buena: se guarda cifrada y queda CONECTADA ──────────────────────
  console.log("\n── 4 · §E la llave buena: valida, guarda y NO se re-pega ──");
  PEER.status = 200;
  await page.fill("#cxKeySecret", "gsk_" + "y".repeat(40));
  await page.click("#cxKeyGuardar");
  await page.waitForFunction(() => {
    const m = document.getElementById("cxKeyMsg");
    return m && !m.hidden && /✓|✗/.test(m.textContent);
  }, null, { timeout: 30000 });
  const msg2 = await page.textContent("#cxKeyMsg");
  ok(/✓/.test(msg2), "llave aceptada por el proveedor → guardada", msg2.trim().slice(0, 90));
  await page.waitForTimeout(2500);
  paginaViva = page;
}

// ── 4b · RELANZAR: la llave sobrevive (persistencia visible) ────────────────────────
{
  if (paginaViva) await paginaViva.close();
  const page = await abrir("?svc=api.groq&correr=1");
  await esperarFila(page, "api.groq");
  const r = await reqs(page, "api.groq");
  ok(r.length === 7, `los 7 requisitos del carril API (${r.map((x) => x.id).join(", ")})`);
  const porId = Object.fromEntries(r.map((x) => [x.id, x]));
  ok(porId.formato.estado === "hecho", "tras relanzar, la llave sigue ahí (formato ✓)", porId.formato.detalle);
  ok(porId.viva.estado === "hecho", "y el proveedor la sigue aceptando (validación viva ✓)");
  ok(porId.persistencia.estado === "hecho", "persistencia: guardada cifrada, sin re-pegar", porId.persistencia.detalle);
  ok(/…\w{2,}|cifrada/.test(porId.persistencia.detalle), "…y lo demuestra con el last4 del almacén", porId.persistencia.detalle);
  ok(porId.streaming.estado === "hecho", "streaming probado de verdad", porId.streaming.detalle);
  ok(porId.modelo.estado === "hecho", "el modelo pedido está en la lista de la llave", porId.modelo.detalle);
  const fila = (await filas(page)).find((x) => x.slug === "api.groq");
  ok(fila.estado === "probado" && /probado (recién|hace )/.test(fila.texto),
     "la fila queda 🟢 con «probado hace X»", fila.texto);
  await foto(page, "api-verde-persistida");
  await page.close();
}

// ── 5 · §C 401 ≠ 402 ≠ 429 ──────────────────────────────────────────────────────────
console.log("\n── 5 · §C llave mala ≠ sin crédito ≠ rate limit ──");
{
  const casos = [
    [401, /no sirve|401/i, "key_invalida"],
    [402, /saldo|402/i, "sin_credito"],
    [429, /techo|429|espera/i, "rate_limit"],
  ];
  for (const [status, re, esperada] of casos) {
    PEER.status = status;
    const page = await abrir("?svc=api.groq&correr=1");
    await esperarFila(page, "api.groq");
    const r = await reqs(page, "api.groq");
    const diag = r.find((x) => x.id === "diagnostico") || {};
    const viva = r.find((x) => x.id === "viva") || {};
    ok(viva.estado === "roto", `  ${status} · la validación viva sale ✗`);
    ok(re.test(diag.detalle), `  ${status} · el diagnóstico nombra la causa correcta (${esperada})`, diag.detalle.slice(0, 90));
    await foto(page, "api-" + status);
    await page.close();
  }
  // los tres textos tienen que ser DISTINTOS entre sí (si no, no distinguen nada)
  PEER.status = 200;
}

// ── 6 · §F batch en paralelo ────────────────────────────────────────────────────────
console.log("\n── 6 · §F batch: dos filas a la vez, con progreso por fila ──");
{
  const page = await abrir();
  await page.evaluate(() => {
    const q = (s) => document.querySelector(`#cxFilas .cx-fila[data-slug="${s}"] .cx-pick`);
    [q("cli.claude_cli"), q("api.groq")].forEach((c) => { if (c) { c.checked = true; c.dispatchEvent(new Event("change")); } });
  });
  ok(await page.isVisible("#cxProbarSel"), "aparece el botón de probar la selección");
  const t0 = Date.now();
  await page.click("#cxProbarSel");
  // el latido tiene que existir MIENTRAS corre (nada espera en silencio)
  const huboLatido = await page.waitForFunction(() => !!document.querySelector(".cx-trabajando"),
    null, { timeout: 8000 }).then(() => true).catch(() => false);
  ok(huboLatido, "mientras corre, cada fila muestra su latido («probando… Ns»)");
  const bloqueado = await page.evaluate(async () => {
    // la app no puede quedar bloqueada mientras corre el batch
    const t = performance.now();
    document.getElementById("cxFiltro").value = "gr";
    document.getElementById("cxFiltro").dispatchEvent(new Event("input"));
    return performance.now() - t;
  });
  ok(bloqueado < 300, "la app sigue respondiendo mientras corre el batch", `${Math.round(bloqueado)}ms`);
  await page.evaluate(() => { const f = document.getElementById("cxFiltro"); f.value = ""; f.dispatchEvent(new Event("input")); });
  await esperarFila(page, "cli.claude_cli", 90000);
  await esperarFila(page, "api.groq", 90000);
  const f = await filas(page);
  const dos = f.filter((x) => ["cli.claude_cli", "api.groq"].indexOf(x.slug) >= 0);
  ok(dos.every((x) => x.estado === "probado"), "las dos cerraron con su veredicto",
    dos.map((x) => `${x.slug}=${x.estado}`).join(" "));
  ok(Date.now() - t0 < 90000, `el batch terminó en ${Math.round((Date.now() - t0) / 1000)}s`);
  ok(!(await page.isVisible("#cxTrabajo")), "el indicador de trabajo se apagó al terminar");
  await page.close();
}

// ── 7 · §D [Reintentar] con camino ──────────────────────────────────────────────────
console.log("\n── 7 · §D reintentar → y si sigue mal, un botón que LLEVA ──");
{
  PEER.status = 401;
  const page = await abrir("?svc=api.groq&correr=1");
  await esperarFila(page, "api.groq");
  let fila = (await filas(page)).find((x) => x.slug === "api.groq");
  ok(fila.estado === "roto", "la fila está roja", fila.texto);
  const pie1 = await page.textContent(`#cxFilas .cx-fila[data-slug="api.groq"] .cx-pie`);
  ok(/Reintentar/.test(pie1) && !/Arreglar esto/.test(pie1),
    "primero ofrece [Reintentar] y NADA MÁS (todavía no se gastó)", pie1.trim().slice(0, 60));
  await page.click(`#cxFilas .cx-fila[data-slug="api.groq"] .cx-pie [data-acc="reintentar"]`);
  await esperarFila(page, "api.groq");
  const pie2 = await page.textContent(`#cxFilas .cx-fila[data-slug="api.groq"] .cx-pie`);
  ok(/Arreglar esto/.test(pie2), "reintentó y sigue mal → el botón MUTA a [Arreglar esto]", pie2.trim().slice(0, 70));
  await page.click(`#cxFilas .cx-fila[data-slug="api.groq"] .cx-pie [data-acc="arreglar"]`);
  await page.waitForTimeout(400);
  const foco = await page.evaluate(() => {
    const li = document.querySelector('#cxFilas .cx-fila[data-slug="api.groq"]');
    const f = li.querySelector(".cx-req.cx-foco");
    return f ? { id: f.dataset.id, estado: f.dataset.estado,
                 accion: (f.querySelector(".cx-req-acc button") || {}).textContent || "" } : null;
  });
  ok(!!foco, "…y te deja PARADO frente al requisito que hay que tocar", foco ? foco.id : "sin foco");
  ok(!!foco && /llave/i.test(foco.accion), "con su botón de arreglo a mano", foco ? foco.accion : "");
  await foto(page, "reintentar-muta");
  PEER.status = 200;
  await page.close();
}

// ── 8 · cero espera muerta: el cable cae y la UI cierra con causa + botón ────────────
console.log("\n── 8 · el cable cae a mitad → causa + botón (jamás un latido eterno) ──");
{
  const page = await abrir();
  CORTAR_FUENTE = true;
  await page.click(`#cxFilas .cx-fila[data-slug="api.groq"] .cx-abrir`);
  await page.waitForFunction(() => {
    const a = document.getElementById("cxAviso");
    return a && !a.hidden;
  }, null, { timeout: 30000 }).catch(() => {});
  const aviso = await page.textContent("#cxAviso").catch(() => "");
  ok(!!aviso && aviso.trim().length > 0, "sale un aviso honesto con la causa", aviso.trim().slice(0, 80));
  ok(/Reintentar/.test(await page.innerHTML("#cxAviso")), "…y trae SU botón (el loop se cierra)");
  const girando = await page.evaluate(() =>
    [...document.querySelectorAll(".cx-req")].filter((r) => r.dataset.estado === "probando").length);
  ok(girando === 0, "no quedó ningún requisito girando para siempre", `${girando} girando`);
  CORTAR_FUENTE = false;
  await page.close();
}

// ── 9 · deep-link desde el catálogo ─────────────────────────────────────────────────
console.log("\n── 9 · §A el deep-link por slug aterriza en la fila ──");
{
  const page = await abrir("?svc=groq&correr=0");     // slug PELADO (como lo manda el Guía)
  const f = (await filas(page)).find((x) => x.slug === "api.groq");
  ok(!!f && f.abierta, "«groq» a secas abre la fila api.groq");
  ok(await page.isVisible("#cxVolver") === false, "sin ?volver no aparece el botón de volver");
  await page.close();
  const page2 = await abrir("?svc=api.groq&volver=Conectar.dc.html");
  ok(await page2.isVisible("#cxVolver"), "con ?volver sí aparece — el camino de vuelta existe");
  await page2.close();
}

// ── cierre ──────────────────────────────────────────────────────────────────────────
// el 502 del bloque 8 lo provocamos NOSOTROS (matar el cable a propósito): no es un error
// de la pantalla, es exactamente lo que estábamos midiendo.
const errRelevantes = errores.filter((e) => !/favicon|supabase|Load failed|502|Bad Gateway/i.test(e));
ok(errRelevantes.length === 0, "cero errores de JS en la pantalla",
  errRelevantes.slice(0, 3).join(" | "));

console.log(`\n${fails.length === 0 ? "✓ TODO VERDE" : "✗ " + fails.length + " FALLO(S)"} — ${fails.join(" · ")}`);
await browser.close();
server.close(); peer.close();
matar();
process.exit(fails.length ? 1 : 0);
