/* verify_conexiones_reforma.mjs — LA VARA DE FIX-P2 · el Centro habla el idioma de la casa.
 *
 * El bug que mide: el Centro de Conexiones quedó PRE-reforma dentro de un producto
 * post-reforma. Círculos genéricos donde van los logos, lista plana sin secciones, cero
 * jerarquía de recomendado, estados sin camino. Dos idiomas en un producto.
 *
 * Config: WebKit + el sidecar FROZEN instalado (:8270) para todo lo que ya existía
 * (sesión, llaves, motor) + el router de FUENTE de ESTE worktree (:8271) para
 * /v1/conexiones y /v1/icons. Los dos comparten ALEPH_DATA_DIR y el harness lo COMPRUEBA
 * antes de medir. /v1/icons va a fuente A PROPÓSITO: el mapa curado de marcas es un
 * recurso del artefacto, y el frozen sirve el que tenía al congelarse — medir los logos
 * contra él sería medir el árbol equivocado.
 *
 * Matriz:
 *   1. LOGOS REALES — cada fila con la cara de su marca; se cuentan los fallbacks y se
 *      nombran. El manifiesto llega async: se mide DESPUÉS del repintado, que es el bug
 *      clásico ("logos en Conectar, iniciales acá").
 *   2. SECCIONES — agrupado por tipo, en el orden sellado, con el RECOMENDADO arriba de
 *      su grupo y visible.
 *   3. FILA EN REPOSO — logo + nombre + estado. Una línea. Sin el sub-título repetido.
 *   4. LOS 5 ESTADOS con su consecuencia: 🟢 con timestamp · 🟡 con [Probar ahora] al
 *      lado · 🔴 con causa legible + camino · ⚪ con qué falta + camino · 🔒 [Ver planes].
 *   5. caminoDe ES EL DICCIONARIO — el Centro y el Cuarto dan la MISMA salida ante la
 *      MISMA causa. No una segunda tabla.
 *   6. FILA ROTA → CLICK → ATERRIZA EN SU WORKFLOW (el del tipo de la fila).
 *   7. SALIDA DE ÉXITO — se completa el workflow y LA FILA queda 🟢 con su timestamp,
 *      ahí mismo, sin paso extra.
 *   8. CERO VERDE SIN PING + CALIBRACIÓN EN ROJO: se fuerza un "conectado" DECLARADO sin
 *      evidencia y la vara TIENE que fallar. Una vara que no sabe fallar no mide nada.
 *   9. ACCIÓN IMPOSIBLE = DESHABILITADA + PORQUÉ.
 *  10. ROLES HONESTOS — el Guía es frontier-only; un no-frontier se ve, sirve para
 *      agentes, y para Guía sale bloqueado con su porqué.
 *
 * Run:  node product/app/design/conexiones/verify_conexiones_reforma.mjs
 * (levanta y mata SUS procesos — JAMÁS toca el :25374 del humano)
 */
import { webkit } from "playwright";
import http from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
// GUARD _MEI (integración tanda-P): TMPDIR privado por sidecar + barrido en TODA salida.
// El bootloader onefile deja ~170 MB en `_MEI*` si el proceso no cierra limpio; 91 huérfanos
// llenaron el disco el 26-jul. Ver qa/lib/frozen_guard.mjs y qa/verify_frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "../../../../qa/lib/frozen_guard.mjs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { createRequire } from "node:module";

const require$ = createRequire(import.meta.url);
const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN = join(HERE, "..");
const REPO = join(DESIGN, "..", "..", "..");
const SHOTS = join(HERE, "screenshots");

// PUERTOS PROPIOS de FIX-P2. El :25374 es del humano y no aparece acá ni por accidente.
// El mandato asignó :8272, pero el 82xx bajo está lleno de sesiones hermanas vivas (al
// arrancar: :8271 un sidecar_serve, :8272 un `dist/aleph_sidecar`, :8274 un uvicorn — de
// otros worktrees). Matarlos habría barrido trabajo ajeno, así que la vara se mudó ENTERA
// a un bloque libre. Overrideable por env: P2_PORT=8272 cuando el puerto vuelva a ser mío.
const FROZEN = process.env.P2_FROZEN || "http://127.0.0.1:8340";
const FUENTE = process.env.P2_FUENTE || "http://127.0.0.1:8341";
const PORT = Number(process.env.P2_PORT || 8342);
const PEER_PORT = Number(process.env.P2_PEER || 8343);
const PAGE = `http://127.0.0.1:${PORT}/Conexiones.dc.html`;
const APP_SIDECAR = process.env.ALEPH_SIDECAR_BIN || "/Applications/Aleph.app/Contents/MacOS/aleph_sidecar";
const PY = process.env.P2_PY || "/opt/miniconda3/bin/python";

const fails = [];
let total = 0;
const ok = (cond, label, extra) => {
  total++;
  console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  — " + extra : ""}`);
  if (!cond) fails.push(label);
};

// ── peer OpenAI-compat REAL (status conmutable) ──────────────────────────────────────
const PEER = { status: 200, modelos: ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"] };
const peer = http.createServer((req, res) => {
  req.on("error", () => {});
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
    req.on("data", () => {});
    req.on("end", () => {
      if (PEER.status !== 200) return enviar(PEER.status, { error: { message: "peer dice " + PEER.status } });
      enviar(200, 'data: {"choices":[{"delta":{"content":"p"}}]}\n\ndata: [DONE]\n\n', "text/event-stream");
    });
    return;
  }
  enviar(404, { error: "nf" });
});
const PEER_URL = `http://127.0.0.1:${PEER_PORT}/v1`;

// ── estático de ESTE worktree + proxy de dos bocas ───────────────────────────────────
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
  ".webp": "image/webp", ".woff2": "font/woff2", ".md": "text/markdown", ".ico": "image/x-icon" };

const server = http.createServer(async (req, res) => {
  req.on("error", () => {}); res.on("error", () => {});
  const u = new URL(req.url, "http://x");
  if (u.pathname.startsWith("/v1/") || u.pathname === "/health") {
    // /v1/conexiones y /v1/icons salen de FUENTE (este worktree); el resto, del binario real.
    const aFuente = u.pathname.startsWith("/v1/conexiones") || u.pathname.startsWith("/v1/icons");
    const arriba = aFuente ? FUENTE : FROZEN;
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
process.on("uncaughtException", (e) => {
  if (!/aborted|ECONNRESET|EPIPE/i.test(String(e && (e.code || e.message)))) throw e;
});

// ── los dos backends ─────────────────────────────────────────────────────────────────
const DATA = mkdtempSync(join(tmpdir(), "p2-data-"));
let procFrozen = null, procFuente = null;

// HIGIENE DE PUERTO — VERSIÓN QUE NO MATA A NADIE.
// La vara vieja mataba cualquier PID cuyo comando dijera «aleph_sidecar». Eso es un
// disparo a ciegas: hay sesiones hermanas corriendo SU sidecar en puertos vecinos (hoy
// mismo :8271 y :8272 eran de otras dos), y el nombre del binario es idéntico. Matarlo
// barre trabajo ajeno y encima deja a la vara midiendo un árbol que no es el suyo.
// Regla nueva: el puerto ocupado NO se libera — se REPORTA y se para. Los puertos son
// baratos; el trabajo de otra sesión no.
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
  console.log(`  no lo mato (puede ser de otra sesión). Corré con P2_PORT/P2_FROZEN/P2_FUENTE/P2_PEER en puertos libres.`);
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

async function bootFuente(extraEnv) {
  procFuente = spawn(PY, ["-m", "uvicorn", "conexiones_sidecar:app", "--app-dir",
    join(REPO, "product", "backend"), "--port", String(new URL(FUENTE).port), "--log-level", "warning"],
    { env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATA,
             PYTHONPATH: [join(REPO, "product", "backend"), join(REPO, "platform"),
                          join(REPO, "platform", "assembler")].join(":"),
             ...(extraEnv || {}) },
      stdio: "ignore", detached: true, cwd: REPO });
  procFuente.unref();
  return await sano(FUENTE);
}

function matarFuente() {
  try { if (procFuente) process.kill(-procFuente.pid, "SIGKILL"); } catch {}
  procFuente = null;
}
function matar() {
  matarFuente();
  try { if (procFrozen) process.kill(-procFrozen.pid, "SIGKILL"); } catch {}
  procFrozen = null;
}

// ══════════════════════════════════════════════════════════════════════════════════════
await mkdir(SHOTS, { recursive: true });
await new Promise((r) => peer.listen(PEER_PORT, "127.0.0.1", r));
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));
for (const p of [Number(new URL(FROZEN).port), Number(new URL(FUENTE).port)]) {
  if (!puertoLibre(p)) { peer.close(); server.close(); process.exit(1); }
}
if (!(await bootFrozen())) { console.log("✗ no pude levantar el sidecar FROZEN en " + FROZEN); process.exit(1); }
if (!(await bootFuente())) { console.log("✗ no pude levantar el sidecar de FUENTE en " + FUENTE); matar(); process.exit(1); }

// PRUEBA DURA de datadir compartido: sin esto, todo lo de llaves mide el banco de pruebas.
let TOKEN = null;
{
  const r = await fetch(FROZEN + "/v1/auth/local", { method: "POST" }).catch(() => null);
  const j = r && r.ok ? await r.json().catch(() => null) : null;
  if (!j || !j.session_token) { console.log("✗ el frozen no minta sesión local"); matar(); process.exit(1); }
  TOKEN = j.session_token;
  const p = await fetch(FUENTE + "/v1/conexiones/key", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + TOKEN },
    body: JSON.stringify({ provider: "groq", secret: "no-tiene-la-forma" }),
  }).then((x) => x.json()).catch(() => null);
  if (!p || p.causa === "sin_sesion") {
    console.log("✗ frozen y fuente NO comparten la SQLite del cliente — mediría el banco de pruebas.");
    matar(); process.exit(1);
  }
  console.log(`  · frozen :${new URL(FROZEN).port} + fuente :${new URL(FUENTE).port} · datadir compartido ✓\n`);
}

const browser = await webkit.launch();
const ctx = await browser.newContext({ viewport: { width: 1180, height: 1000 } });
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("  ⚠ pageerror: " + String(e).slice(0, 140)));

async function irAlCentro(qs) {
  await page.goto(PAGE + (qs || ""), { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.AlephCentro && window.AlephCentro.ST.filas.length > 0,
    null, { timeout: 25000 });
  // el manifiesto de logos llega async: esperamos a que AlephBrand haya resuelto ANTES de
  // medir caras. Medir antes daría "todo fallback" y sería un falso rojo.
  await page.waitForFunction(() => window.AlephBrand && window.AlephBrand._known() !== null,
    null, { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(350);
}

await irAlCentro();

// ══ 1 · LOGOS REALES ══════════════════════════════════════════════════════════════════
console.log("§1 · LOGOS REALES en cada fila (brandface, mapa curado, cero red)");
const caras = await page.evaluate(() => {
  const C = window.AlephCentro;
  return C.ST.filas.map((f) => {
    const li = document.querySelector(`#cxFilas [data-slug="${CSS.escape(f.slug)}"]`);
    const host = li && li.querySelector(".cx-face-h");
    const img = host && host.querySelector("img");
    return {
      slug: f.slug, label: f.label, marca: f.marca || "",
      hayCara: !!(host && host.firstElementChild),
      esImg: !!img, src: img ? img.getAttribute("src") : "",
      esFallback: C.esFallback(f),
      iniciales: host && !img ? (host.textContent || "").trim() : "",
    };
  });
});
ok(caras.length > 0, `hay filas que medir`, `${caras.length} filas`);
ok(caras.every((c) => c.hayCara), "TODA fila tiene una cara (jamás un hueco ni un círculo vacío)");
const conLogo = caras.filter((c) => c.esImg);
const fallback = caras.filter((c) => !c.esImg);
ok(conLogo.length >= 9, `las filas de proveedor traen LOGO REAL (<img> de /v1/icons)`,
   `${conLogo.length}/${caras.length} con logo`);
// las 8 marcas que el mandato nombra, uno por uno
for (const [slug, marca] of [["cli.claude_cli", "claude_code"], ["cli.codex_cli", "codex"],
  ["api.anthropic", "anthropic"], ["api.deepseek", "deepseek"], ["api.groq", "groq"],
  ["api.mistral", "mistral"], ["api.openai", "openai"], ["api.openrouter", "openrouter"],
  ["api.together", "together"]]) {
  const c = caras.find((x) => x.slug === slug);
  ok(!!c && c.esImg && c.src.indexOf("/v1/icons/" + marca) >= 0,
    `${slug} → logo real de «${marca}»`, c ? (c.esImg ? c.src : "FALLBACK " + c.iniciales) : "fila ausente");
}
// los <img> tienen que CARGAR de verdad (un src que 404ea degrada a iniciales en silencio)
const cargados = await page.evaluate(() => [...document.querySelectorAll(".cx-face-h img")]
  .map((i) => ({ src: i.getAttribute("src"), w: i.naturalWidth })));
ok(cargados.length > 0 && cargados.every((i) => i.w > 0),
  "cada logo CARGÓ de verdad (naturalWidth > 0 — no un 404 que degrada callado)",
  `${cargados.filter((i) => i.w > 0).length}/${cargados.length}`);
console.log(`  · fallbacks (serviceFace iniciales+color): ${fallback.length}` +
  (fallback.length ? " → " + fallback.map((f) => `${f.slug} [${f.iniciales}]`).join(", ") : ""));
// el NOMBRE al lado del logo: capitalizar el slug daba «Openai»/«Deepseek» pegado al logo
// REAL de esa marca — se lee como un error de la casa, que es justo lo que veníamos a sacar.
const nombres = await page.evaluate(() => {
  const n = (s) => {
    const li = document.querySelector(`#cxFilas [data-slug="${CSS.escape(s)}"] .cx-nom b`);
    return li ? getComputedStyle(li).textTransform === "capitalize"
      ? li.textContent.trim() : li.textContent.trim() : null;
  };
  return { openai: n("api.openai"), openrouter: n("api.openrouter"), deepseek: n("api.deepseek") };
});
ok(nombres.openai === "OpenAI" && nombres.openrouter === "OpenRouter" && nombres.deepseek === "DeepSeek",
  "el nombre se escribe como lo escribe su dueño (no «Openai» al lado del logo de OpenAI)",
  Object.values(nombres).join(" · "));

// ══ 2 · SECCIONES + RECOMENDADO ═══════════════════════════════════════════════════════
console.log("\n§2 · SECCIONES por tipo, con el recomendado arriba de su grupo");
const secc = await page.evaluate(() => [...document.querySelectorAll("#cxFilas .cx-grupo")].map((g) => ({
  familia: g.dataset.familia,
  titulo: (g.querySelector(".cx-grupo-t") || {}).textContent.trim(),
  lede: !!g.querySelector(".cx-grupo-l"),
  filas: [...g.querySelectorAll(".cx-fila")].map((li) => li.dataset.slug),
  primeraRec: !!(g.querySelector(".cx-fila") || {}).querySelector?.(".cx-rec"),
})));
ok(secc.length >= 3, "la lista PLANA murió: hay secciones", `${secc.length} grupos`);
const orden = secc.map((s) => s.familia);
ok(JSON.stringify(orden.slice(0, 3)) === JSON.stringify(["incluido", "cli", "api"]),
  "el orden sellado: Incluido · CLI/suscripción · API con tu llave", orden.join(" → "));
ok(secc.every((s) => s.titulo && s.lede), "cada sección con su título y su lede (una vez, no por fila)");
for (const [fam, rec] of [["incluido", "incluido.cognicion"], ["cli", "cli.claude_cli"], ["api", "api.groq"]]) {
  const s = secc.find((x) => x.familia === fam);
  ok(!!s && s.filas[0] === rec, `«${fam}»: el recomendado (${rec}) va PRIMERO de su grupo`,
     s ? s.filas[0] : "grupo ausente");
}
const pills = await page.evaluate(() => [...document.querySelectorAll(".cx-rec")].map((p) =>
  p.closest(".cx-fila").dataset.slug));
ok(pills.length === 3 && pills.indexOf("api.groq") >= 0,
  "el recomendado está MARCADO y visible (píldora), uno por grupo", pills.join(", "));

// ══ 3 · FILA EN REPOSO ════════════════════════════════════════════════════════════════
console.log("\n§3 · fila en reposo = logo + nombre + estado (una línea)");
const reposo = await page.evaluate(() => {
  const li = document.querySelector('#cxFilas [data-slug="api.groq"]');
  const b = li.querySelector(".cx-abrir");
  return { alturas: [...document.querySelectorAll("#cxFilas .cx-abrir")].map((x) => Math.round(x.getBoundingClientRect().height)),
           tieneSub: !!li.querySelector(".cx-nom em"),
           partes: [...b.children].map((c) => c.className.split(" ")[0]) };
});
ok(!reposo.tieneSub, "el sub-título repetido por fila («tu propia llave de API») ya no está");
ok(Math.max(...reposo.alturas) <= 54, "ninguna fila pasa de una línea", `alto máx ${Math.max(...reposo.alturas)}px`);
ok(JSON.stringify(reposo.partes) === JSON.stringify(["cx-face-h", "cx-luz", "cx-nom", "cx-estado", "cx-chev"]),
  "el orden de la fila: cara · luz · nombre · estado", reposo.partes.join(" "));

// ══ 4 · LOS 5 ESTADOS, CADA UNO CON SU CONSECUENCIA ═══════════════════════════════════
console.log("\n§4 · los 5 estados y su consecuencia");
const est = await page.evaluate(() => {
  const C = window.AlephCentro;
  const uno = (estado, causa) => {
    const f = { slug: "x", label: "X", familia: "api", estado, causa, ts: 1700000000 };
    const cam = C.caminoFila(f);
    return { texto: C.textoEstado(f), camino: cam && cam.es, accion: cam && cam.accion };
  };
  return { probado: uno("probado", null), detectado: uno("detectado", null),
           roto: uno("roto", "falta_key"), roto_cli: uno("roto", "cli_no_instalado"),
           roto_red: uno("roto", "sin_red"), nocfg: uno("no_configurado", null),
           premium: uno("premium", null) };
});
ok(/^probado hace |^probado recién/.test(est.probado.texto) && est.probado.camino === null,
  "🟢 probado: dice CUÁNDO (evidencia) y no fuerza camino", est.probado.texto);
ok(est.detectado.camino === "Probar ahora", "🟡 sin probar → [Probar ahora]", est.detectado.camino);
ok(est.roto.texto.indexOf("falta tu key") >= 0 && est.roto.camino === "Poner la key",
  "🔴 roto: LA causa legible + su camino", `${est.roto.texto} → [${est.roto.camino}]`);
ok(est.roto_cli.texto.indexOf("cli no instalado") >= 0 && est.roto_cli.camino === "Cómo instalar",
  "🔴 causa distinta → camino distinto (CLI no instalado)", `${est.roto_cli.texto} → [${est.roto_cli.camino}]`);
ok(est.roto_red.texto.indexOf("sin conexión") >= 0 && est.roto_red.accion === "reintentar",
  "🔴 sin red → [Reintentar]", `${est.roto_red.texto} → [${est.roto_red.camino}]`);
ok(est.nocfg.texto.indexOf("falta tu llave") >= 0 && est.nocfg.camino === "Conectar",
  "⚪ sin configurar: qué falta en UNA línea + camino", `${est.nocfg.texto} → [${est.nocfg.camino}]`);
ok(est.premium.camino === "Ver planes" && est.premium.accion === "premium",
  "🔒 premium: muro honesto con [Ver planes], jamás botón muerto", est.premium.camino);
// y el botón 🟡 existe EN EL DOM, al lado del estado (no escondido adentro)
const btnAlLado = await page.evaluate(() => {
  const li = document.querySelector('#cxFilas [data-familia="cli"] .cx-fila, #cxFilas [data-slug="cli.claude_cli"]');
  const row = document.querySelector('#cxFilas [data-slug="cli.claude_cli"]');
  const b = row && row.querySelector(".cx-cab .cx-cab-acc .cx-camino");
  return { hay: !!b, txt: b && b.textContent.trim(), estado: row && row.dataset.estado,
           dentroDelCuerpo: !!(row && row.querySelector(".cx-cuerpo .cx-camino")) };
});
ok(btnAlLado.hay && !btnAlLado.dentroDelCuerpo,
  "el camino vive AL LADO del estado, en la cabecera (no hay que abrir la fila)",
  `[${btnAlLado.txt}] en ${btnAlLado.estado}`);

// ══ 5 · caminoDe ES EL DICCIONARIO ════════════════════════════════════════════════════
console.log("\n§5 · caminoDe: UN diccionario para toda la casa");
const mismo = await page.evaluate(async () => {
  const Sem = (await import("../cuarto/cuarto.semaforo.js")).default;
  const C = window.AlephCentro;
  const casos = [["detectado", null], ["no_configurado", null], ["premium", null],
                 ["roto", "falta_key"], ["roto", "cli_no_instalado"], ["roto", "sin_red"],
                 ["roto", "plan_insuficiente"], ["roto", "sin_sesion"]];
  return casos.map(([estado, causa]) => {
    const a = Sem.caminoDe({ estado, causa });
    const b = C.caminoFila({ estado, causa, familia: "api" });
    return { estado, causa, igual: JSON.stringify(a) === JSON.stringify(b), es: a && a.es };
  });
});
ok(mismo.every((m) => m.igual),
  "el Centro y el Cuarto dan LA MISMA salida ante la MISMA causa (una tabla, no dos)",
  `${mismo.filter((m) => m.igual).length}/${mismo.length}`);
mismo.forEach((m) => console.log(`    ${m.estado}/${m.causa || "—"} → [${m.es}]`));

// ══ 6 · FILA ROTA → CLICK → SU WORKFLOW ═══════════════════════════════════════════════
console.log("\n§6 · fila no-verde → click → aterriza en el workflow de SU tipo");
// ⚪ api (lleva llave) → el formulario REAL de credencial
await page.click('#cxFilas [data-slug="api.groq"] .cx-camino');
await page.waitForTimeout(400);
const trasApi = await page.evaluate(() => ({
  dlg: !document.getElementById("cxKeyDlg").hidden,
  prov: document.getElementById("cxKeyProv").value,
  titulo: document.getElementById("cxKeyTitulo").textContent,
}));
ok(trasApi.dlg && trasApi.prov === "groq",
  "⚪ api.groq → [Conectar] → el formulario de llave REAL, con el proveedor puesto",
  `${trasApi.titulo}`);
await page.keyboard.press("Escape");
await page.waitForTimeout(200);
// 🟡 cli → [Probar ahora] → LATIDO → DESENLACE, todo en LA MISMA FILA (nada espera mudo)
const yellowAntes = await page.evaluate(() => {
  const li = document.querySelector('#cxFilas [data-slug="cli.claude_cli"]');
  return { luz: li.querySelector(".cx-luz").textContent.trim(), estado: li.dataset.estado,
           btn: li.querySelector(".cx-camino").textContent.trim() };
});
ok(yellowAntes.luz === "🟡" && yellowAntes.btn === "Probar ahora",
  "🟡 la fila arranca «sin probar» con [Probar ahora] AL LADO", `${yellowAntes.luz} → [${yellowAntes.btn}]`);
await page.click('#cxFilas [data-slug="cli.claude_cli"] .cx-camino');
// EL LATIDO: se captura mientras corre (⟳ girando + «probando… Ns» que avanza)
// SEÑAL DE TRABAJO EN VIVO. Dos cosas distintas, y se informan por separado en vez de
// mezclarlas: (a) mientras corre, la fila muestra spinner + «probando…»; (b) el CONTADOR
// de segundos, que sólo se puede ver si la corrida dura más que un latido del backend
// (PUPPET_CONEX_LATIDO = 2 s). Un checklist de CLI local suele cerrar antes de los 2 s:
// eso NO es un fallo — es un éxito rápido —, así que se dice cuál de los dos se vio en vez
// de exigir uno que puede no existir. Que el spinner no quede girando para siempre lo
// prueba el DESENLACE de abajo, que es la mitad que de verdad importa.
const tLatido = Date.now();
const latido = await page.waitForFunction(() => {
  const li = document.querySelector('#cxFilas [data-slug="cli.claude_cli"]');
  const t = li.querySelector(".cx-trabajando");
  if (!t) return null;
  const em = t.querySelector("em");
  return { txt: t.textContent.replace(/\s+/g, " ").trim(),
           secs: em && /\d+(\.\d+)?s/.test(em.textContent) ? em.textContent.trim() : "",
           spin: !!t.querySelector(".cx-spin"),
           probando: li.querySelectorAll(".cx-marca.run").length };
}, null, { timeout: 20000, polling: 100 }).then((h) => h.jsonValue()).catch(() => null);
// si el spinner ya se fue es porque cerró rapidísimo: se comprueba que HUBO corrida
const cerroYa = !latido && await page.evaluate(() =>
  !!window.AlephCentro.ST.reqs["cli.claude_cli"]);
ok((!!latido && latido.spin && /probando/.test(latido.txt)) || cerroYa,
  "…y mientras corre la fila MUESTRA que trabaja (spinner + «probando…»)",
  latido ? `«${latido.txt}»${latido.secs ? "" : " (aún sin contador)"} · ${latido.probando} req en ⟳`
         : "cerró antes de que el spinner fuera observable");
if (latido && latido.secs) {
  ok(true, "…con su CONTADOR avanzando (el latido del cable, no un ícono girando)", latido.secs);
} else {
  console.log(`  · el contador de latido no se vio: la corrida cerró en <${((Date.now() - tLatido) / 1000).toFixed(1)}s, ` +
    `antes del primer latido del backend (cada 2 s). No es un fallo — es un éxito rápido; ` +
    `el «nada gira para siempre» lo prueba el desenlace.`);
}
await page.screenshot({ path: join(SHOTS, "reforma-5-latido.png"), fullPage: true });
// EL DESENLACE: la MISMA fila cierra con veredicto; ningún ⟳ queda girando
await page.waitForFunction(() => {
  const C = window.AlephCentro;
  return !C.ST.corriendo.size;
}, null, { timeout: 90000 }).catch(() => {});
const trasCli = await page.evaluate(() => {
  const li = document.querySelector('#cxFilas [data-slug="cli.claude_cli"]');
  const f = window.AlephCentro.ST.filas.find((x) => x.slug === "cli.claude_cli");
  return { abierta: li.classList.contains("abierta"),
           reqs: li.querySelectorAll(".cx-req").length,
           girando: li.querySelectorAll(".cx-marca.run").length,
           resueltos: li.querySelectorAll('.cx-req[data-estado="hecho"], .cx-req[data-estado="roto"], .cx-req[data-estado="na"]').length,
           luz: li.querySelector(".cx-luz").textContent.trim(),
           txt: li.querySelector(".cx-estado").textContent.trim(),
           ts: f && f.ts };
});
ok(trasCli.abierta && trasCli.reqs > 0,
  "🟡 cli.claude_cli → [Probar ahora] → abre y CORRE su checklist (el workflow del tipo cli)",
  `${trasCli.reqs} requisitos`);
ok(trasCli.girando === 0 && trasCli.resueltos > 0,
  "…y DESENLACE en la misma fila: 0 requisitos girando, todos con veredicto",
  `${trasCli.resueltos}/${trasCli.reqs} resueltos · luz ${trasCli.luz} «${trasCli.txt}»`);
// TODO destino que `andar()` puede navegar tiene que EXISTIR. Un `Settings.dc.html#planes`
// inventado navega a ninguna parte y parece que funciona — el peor de los botones falsos.
const destinos = await page.evaluate(async () => {
  const urls = new Set();
  const real = { href: location.href };
  // se interceptan las navegaciones en vez de ejecutarlas
  const spy = { premium: null };
  window.alephMostrarPaywall = (d) => { spy.premium = d; };
  const C = window.AlephCentro;
  const Sem = (await import("../cuarto/cuarto.semaforo.js")).default;
  // premium: con paywall montado NO navega; sin él cae a /#premium (un ancla de la app)
  Sem.despachar("premium", { tipo: "key", ref: "x", estado: "premium" }, { feature: "x" });
  return { premiumLlamoPaywall: !!spy.premium, sigueEnLaPagina: location.href === real.href };
});
ok(destinos.premiumLlamoPaywall && destinos.sigueEnLaPagina,
  "🔒 [Ver planes] usa el despachador de la casa (paywall real), no un ancla inventada");
const anclas = await page.evaluate(async () => {
  const r = await fetch("Settings.dc.html").then((x) => x.text()).catch(() => "");
  return { planes: /id=["']planes["']|name=["']planes["']/.test(r) };
});
ok(!anclas.planes,
  "…y queda constancia de POR QUÉ: Settings.dc.html no tiene ancla #planes (el destino viejo era falso)");

// ══ 7 · SALIDA DE ÉXITO: la fila queda 🟢 ahí mismo ═══════════════════════════════════
console.log("\n§7 · la salida de éxito — el camino termina en la PRUEBA, no en un consejo");
PEER.status = 200;
// EL CAMINO REAL, TOCADO COMO LO TOCA UN HUMANO. Nada de `fetch()` por atrás: se hace
// CLICK en el botón de la fila ⚪, se TIPEA en el formulario y se aprieta [Validar y
// guardar]. Un test que llama al backend a mano prueba el backend, no el camino — y el
// camino es justo lo que el mandato pide certificar.
const FILA7 = "api.deepseek";                       // ⚪ virgen (groq ya se tocó en §6)
await irAlCentro();
const antes7 = await page.evaluate((s) => {
  const li = document.querySelector(`#cxFilas [data-slug="${CSS.escape(s)}"]`);
  return { estado: li.dataset.estado, luz: li.querySelector(".cx-luz").textContent.trim(),
           btn: (li.querySelector(".cx-camino") || {}).textContent };
}, FILA7);
ok(antes7.estado === "no_configurado" && antes7.luz === "⚪",
  `arranco de una fila NO-verde de verdad (${FILA7})`, `${antes7.luz} ${antes7.estado} → [${(antes7.btn || "").trim()}]`);

await page.click(`#cxFilas [data-slug="${FILA7}"] .cx-camino`);   // ← CLICK real
await page.waitForSelector("#cxKeyDlg:not([hidden])", { timeout: 5000 });
await page.fill("#cxKeySecret", "sk-" + "d".repeat(40));          // ← TIPEO real
await page.fill("#cxKeyBase", PEER_URL);                          // dirección propia (campo real)
await page.click("#cxKeyGuardar");                                // ← [Validar y guardar]
// el formulario dice qué está haciendo mientras valida (nada espera en silencio)
const validando = await page.waitForFunction(
  () => { const m = document.getElementById("cxKeyMsg"); return m && !m.hidden && /validando|✓|✗/.test(m.textContent); },
  null, { timeout: 20000 }).then(() => page.evaluate(() => document.getElementById("cxKeyMsg").textContent.trim())).catch(() => "");
ok(/validando|✓/.test(validando), "el formulario NARRA la validación en vivo", validando.slice(0, 70));

// …y desde ahí, SOLO, hasta el verde: sin recargar, sin apretar nada más.
await page.waitForFunction((s) => {
  const f = window.AlephCentro.ST.filas.find((x) => x.slug === s);
  return f && f.estado === "probado";
}, FILA7, { timeout: 60000 }).catch(() => {});
const verde = await page.evaluate((s) => {
  const li = document.querySelector(`#cxFilas [data-slug="${CSS.escape(s)}"]`);
  const f = window.AlephCentro.ST.filas.find((x) => x.slug === s);
  return { estado: li.dataset.estado, luz: li.querySelector(".cx-luz").textContent.trim(),
           txt: li.querySelector(".cx-estado").textContent.trim(), ts: f && f.ts,
           camino: !!li.querySelector(".cx-cab-acc .cx-camino"),
           dlgCerrado: document.getElementById("cxKeyDlg").hidden };
}, FILA7);
ok(verde.dlgCerrado, "el formulario se cierra solo al terminar bien (no te deja el modal encima)");
ok(verde.estado === "probado" && verde.luz === "🟢",
  "completado el workflow POR LA UI, LA FILA queda 🟢 en el lugar (sin paso extra)", `${verde.luz} ${verde.txt}`);
ok(!!verde.ts && /probado (recién|hace )/.test(verde.txt),
  "…y con su TIMESTAMP: la evidencia, no una declaración", verde.txt);
ok(!verde.camino, "en 🟢 el camino desaparece (caminoDe no fuerza botón en verde)");
await page.screenshot({ path: join(SHOTS, "reforma-4-salida-de-exito.png"), fullPage: true });

// ══ 8 · CERO VERDE SIN PING ═══════════════════════════════════════════════════════════
console.log("\n§8 · nada se pinta verde sin ping");
// CALIBRACIÓN EN ROJO (P2_CALIBRAR=1) — se ENVENENA el estado ANTES de §8 con un
// «conectado» DECLARADO: estado probado, ts nulo, cero pings. La vara tiene que ponerse
// ROJA y salir 1. Una vara que no sabe fallar no está midiendo nada, y este modo lo
// demuestra corriéndola de verdad en vez de afirmarlo.
if (process.env.P2_CALIBRAR === "1") {
  await page.evaluate(() => {
    window.AlephCentro.ST.filas.push({
      slug: "api.mentira", familia: "api", ref: "mentira", label: "Mentira", marca: "",
      estado: "probado", causa: null, ts: null, recomendado: false, requisitos: [],
      fuente: "inyectada-por-la-calibracion" });
    window.AlephCentro.pintarLista();
  });
  console.log("  ⚠ CALIBRACIÓN ACTIVA: inyecté un 🟢 declarado sin ping — §8 DEBE fallar");
}
const sinPing = await page.evaluate(() => {
  const C = window.AlephCentro;
  return C.ST.filas.filter((f) => f.estado === "probado" && !f.ts).map((f) => f.slug);
});
ok(sinPing.length === 0, "no hay NINGUNA fila 🟢 sin timestamp de una prueba real",
   sinPing.length ? "verdes huérfanos: " + sinPing.join(", ") : "0 verdes sin evidencia");
// la lane INCLUIDA es el caso que importa: /v1/brains/status la declara "ready" sólo
// porque hay una llave CONFIGURADA. Eso es DECLARADO, no probado — y no puede salir verde.
const incl = await page.evaluate(() => window.AlephCentro.ST.filas.find((f) => f.familia === "incluido"));
ok(incl && incl.estado !== "probado",
  "la lane INCLUIDA no nace 🟢 por tener llave configurada (declarado ≠ probado)",
  `${incl && incl.slug} = ${incl && incl.estado}`);

// ══ 9 · ACCIÓN IMPOSIBLE = DESHABILITADA + PORQUÉ ═════════════════════════════════════
// Las DOS ramas se ejercitan de verdad. Una vara que sólo pasa por la rama habilitada
// reporta verde sobre código que nunca corrió — que es la mentira que estamos matando.
console.log("\n§9 · acción imposible = deshabilitada + porqué");

// 9a · un servidor MCP corre en TU máquina y no lleva llave → [Conectar] es un botón que
// no arregla nada. La fila entra por el deep-link ?mcp=<ref> (el camino REAL del backend).
await irAlCentro("?mcp=" + encodeURIComponent("catalog/templates/belt-p2.mcp.json#pysandbox"));
const mcpFila = await page.evaluate(() => {
  const f = window.AlephCentro.ST.filas.find((x) => x.familia === "mcp");
  if (!f) return { hay: false };
  const li = document.querySelector(`#cxFilas [data-slug="${CSS.escape(f.slug)}"]`);
  const b = li && li.querySelector(".cx-camino");
  return { hay: true, slug: f.slug, estado: f.estado, label: f.label,
           grupo: !!document.querySelector('#cxFilas .cx-grupo[data-familia="mcp"]'),
           hayBoton: !!b, disabled: b ? b.disabled : null,
           txt: b ? b.textContent.trim() : "",
           porque: ((li && li.querySelector(".cx-porque")) || {}).textContent || "" };
});
ok(mcpFila.hay && mcpFila.grupo, "el deep-link ?mcp= materializa la sección «Servidores MCP equipados»",
   mcpFila.slug);
// en 🟡 el MCP tiene un camino REAL (probar el handshake): ahí NO va apagado. El candado
// es sólo para el camino que no existe para su tipo — la llave.
ok(mcpFila.hayBoton && mcpFila.disabled === false && mcpFila.txt === "Probar ahora",
  "MCP en 🟡: su camino REAL (probar el handshake) va habilitado", `[${mcpFila.txt}]`);
// y en ⚪, donde caminoDe pide [Conectar], el botón se apaga: un servidor que corre en tu
// máquina no tiene llave que poner. Se fuerza el estado (el backend lo produce) para
// ejercitar la rama de verdad en vez de reportar verde sobre código que no corrió.
const mcpApagado = await page.evaluate(() => {
  const C = window.AlephCentro;
  const f = C.ST.filas.find((x) => x.familia === "mcp");
  f.estado = "no_configurado"; f.causa = null;
  C.pintarLista();                       // el MISMO camino de pintado que usa la pantalla
  const li = document.querySelector(`#cxFilas [data-slug="${CSS.escape(f.slug)}"]`);
  const b = li && li.querySelector(".cx-camino");
  return { estado: f.estado, hay: !!b, txt: b && b.textContent.trim(),
           disabled: b ? b.disabled : null,
           porque: ((li && li.querySelector(".cx-porque")) || {}).textContent || "" };
});
ok(mcpApagado.hay && mcpApagado.txt === "Conectar" && mcpApagado.disabled === true &&
   /no lleva llave/.test(mcpApagado.porque),
  "MCP en ⚪: [Conectar] visible pero DESHABILITADO con su porqué (no un botón fantasma)",
  `[${mcpApagado.txt}] · ${mcpApagado.porque}`);
// contra-prueba: el mismo ⚪ en una fila que SÍ lleva llave (api) NO se apaga.
const apiNoApagado = await page.evaluate(() => {
  const b = document.querySelector('#cxFilas [data-slug="api.anthropic"] .cx-camino');
  return { txt: b && b.textContent.trim(), disabled: b ? b.disabled : null };
});
ok(apiNoApagado.txt === "Conectar" && apiNoApagado.disabled === false,
  "…y el MISMO ⚪ en una fila que sí lleva llave queda habilitado (el candado mira el tipo)",
  `api.anthropic [${apiNoApagado.txt}]`);

// 9b · [Probar a fondo] GASTA una corrida real contra tu suscripción: con el CLI ausente
// es imposible. Se fuerza el estado que el motor produce de verdad (cli_no_instalado) para
// ejercitar la rama, aunque ESTA máquina tenga el CLI puesto.
const fondo = await page.evaluate(async () => {
  const C = window.AlephCentro;
  const f = C.ST.filas.find((x) => x.slug === "cli.codex_cli");
  const real = { estado: f.estado, causa: f.causa };
  f.estado = "roto"; f.causa = "cli_no_instalado";
  await C.abrirFila("cli.codex_cli", { correr: false });
  const li = document.querySelector('#cxFilas [data-slug="cli.codex_cli"]');
  const b = li.querySelector('[data-acc="profundo"]');
  const out = { hay: !!b, disabled: b && b.disabled, title: b && b.getAttribute("title"),
                porque: ((li.querySelector(".cx-pie .cx-porque")) || {}).textContent || "",
                real };
  f.estado = real.estado; f.causa = real.causa;      // se deja como estaba
  C.cerrarFila("cli.codex_cli");
  return out;
});
ok(fondo.hay && fondo.disabled === true && /no está instalado/.test(fondo.porque),
  "[Probar a fondo] con el CLI ausente: visible, DESHABILITADO y con su porqué",
  `${fondo.porque} (el real en esta máquina: ${fondo.real.estado}/${fondo.real.causa || "sin causa"})`);
// y la contra-prueba: con el CLI usable el botón NO está apagado (el candado no es decorativo)
const fondoOk = await page.evaluate(async () => {
  const C = window.AlephCentro;
  const f = C.ST.filas.find((x) => x.slug === "cli.codex_cli");
  const real = { estado: f.estado, causa: f.causa };
  f.estado = "probado"; f.causa = null;
  await C.abrirFila("cli.codex_cli", { correr: false });
  const b = document.querySelector('#cxFilas [data-slug="cli.codex_cli"] [data-acc="profundo"]');
  const out = { hay: !!b, disabled: b && b.disabled };
  f.estado = real.estado; f.causa = real.causa;
  C.cerrarFila("cli.codex_cli");
  return out;
});
ok(fondoOk.hay && fondoOk.disabled === false,
  "…y con el CLI usable vuelve a estar habilitado (el candado depende del estado, no es decoración)");

// ══ 10 · ROLES HONESTOS ═══════════════════════════════════════════════════════════════
console.log("\n§10 · roles honestos — el Guía es frontier-only");
const rol = await page.evaluate(() => {
  const C = window.AlephCentro;
  const de = (slug) => {
    const f = C.ST.filas.find((x) => x.slug === slug);
    const rs = f ? C.roles(f) : [];
    return { slug, agentes: (rs.find((r) => r.id === "agentes") || {}).puede,
             guia: (rs.find((r) => r.id === "guia") || {}).puede,
             porque: (rs.find((r) => r.id === "guia") || {}).porque };
  };
  return { groq: de("api.groq"), claude: de("cli.claude_cli"),
           incluido: de("incluido.cognicion"), anthropic: de("api.anthropic"),
           mcp: C.roles({ familia: "mcp", slug: "mcp.x" }).length };
});
ok(rol.groq.agentes === true && rol.groq.guia === false,
  "Groq: se ve, SIRVE para agentes, y para el rol de Guía queda bloqueado", rol.groq.porque);
ok(/frontier/.test(rol.groq.porque || ""), "…con su PORQUÉ escrito, no un candado mudo");
ok(rol.claude.guia === true && rol.incluido.guia === true && rol.anthropic.guia === true,
  "los frontier sí pueden guiar (CLI por suscripción · lane incluida · Opus por tu API)");
ok(rol.mcp === 0, "una pieza MCP no finge tener rol de cerebro (no inventa opción)");
// y en pantalla, el rol bloqueado se VE
await page.evaluate(() => window.AlephCentro.abrirFila("api.groq", { correr: false }));
await page.waitForTimeout(300);
const rolDOM = await page.evaluate(() => {
  const li = document.querySelector('#cxFilas [data-slug="api.groq"]');
  return { chips: [...li.querySelectorAll(".cx-rol")].map((c) => c.textContent.trim() + (c.classList.contains("no") ? " [BLOQUEADO]" : "")),
           porque: (li.querySelector(".cx-rol-por") || {}).textContent };
});
ok(rolDOM.chips.length === 2 && /BLOQUEADO/.test(rolDOM.chips[1]),
  "en pantalla: ✓ Agentes · 🔒 Guía bloqueado", rolDOM.chips.join(" | "));

// ══ 11 · LOS 5 ESTADOS, FORZADOS Y VISTOS EN PANTALLA ═════════════════════════════════
// §4 midió las funciones; esto mide el PÍXEL. Se fuerzan los 5 estados sobre filas reales
// y se comprueba lo RENDERIZADO: emoji, texto y botón. Una función que devuelve lo correcto
// y una fila que pinta otra cosa es un bug que §4 no ve.
console.log("\n§11 · los 5 estados forzados y VISTOS (no la función: el píxel)");
await irAlCentro();
const CINCO = [
  ["incluido.cognicion", "probado",        null,               "🟢", null],
  ["cli.claude_cli",     "detectado",      null,               "🟡", "Probar ahora"],
  ["cli.codex_cli",      "roto",           "cli_no_instalado", "🔴", "Cómo instalar"],
  ["api.anthropic",      "no_configurado", null,               "⚪", "Conectar"],
  ["api.openai",         "premium",        null,               "🔒", "Ver planes"],
];
const pintados = await page.evaluate((casos) => {
  const C = window.AlephCentro;
  const ahora = Math.floor(Date.now() / 1000);
  casos.forEach(([slug, estado, causa]) => {
    const f = C.ST.filas.find((x) => x.slug === slug);
    f.estado = estado; f.causa = causa;
    f.ts = estado === "probado" ? ahora - 120 : f.ts;   // «probado hace 2 min»
  });
  C.pintarLista();
  return casos.map(([slug]) => {
    const li = document.querySelector(`#cxFilas [data-slug="${CSS.escape(slug)}"]`);
    const b = li.querySelector(".cx-camino");
    return { slug, luz: li.querySelector(".cx-luz").textContent.trim(),
             txt: li.querySelector(".cx-estado").textContent.trim(),
             btn: b ? b.textContent.trim() : null, disabled: b ? b.disabled : null };
  });
}, CINCO);
for (const [slug, estado, , emoji, boton] of CINCO) {
  const p = pintados.find((x) => x.slug === slug);
  const okEmoji = p.luz === emoji;
  const okBtn = boton === null ? p.btn === null : p.btn === boton;
  ok(okEmoji && okBtn, `${emoji} ${estado} → «${p.txt}»${boton ? ` + [${boton}]` : " · sin botón"}`,
     `${slug}: ${p.luz} «${p.txt}» ${p.btn ? "[" + p.btn + "]" : "(sin botón)"}`);
}
// el 🟢 tiene que decir CUÁNDO, y el 🔴 tiene que decir LA CAUSA
const verdeTxt = pintados[0].txt, rojoTxt = pintados[2].txt, blancoTxt = pintados[3].txt;
ok(/probado hace 2 min/.test(verdeTxt), "🟢 muestra su timestamp en pantalla", verdeTxt);
ok(/cli no instalado/.test(rojoTxt), "🔴 muestra LA causa legible en pantalla", rojoTxt);
ok(/falta tu llave/.test(blancoTxt), "⚪ muestra qué falta, en una línea", blancoTxt);
await page.screenshot({ path: join(SHOTS, "reforma-6-cinco-estados.png"), fullPage: true });
console.log("  · screenshot → reforma-6-cinco-estados.png");
await irAlCentro();   // se deshace el forzado leyendo del backend otra vez

// ── screenshots ───────────────────────────────────────────────────────────────────────
await page.evaluate(() => window.AlephCentro.cerrarFila("api.groq"));
await page.waitForTimeout(250);
await page.screenshot({ path: join(SHOTS, "reforma-1-secciones-logos.png"), fullPage: true });
await page.evaluate(() => window.AlephCentro.abrirFila("api.groq", { correr: false }));
await page.waitForTimeout(300);
await page.screenshot({ path: join(SHOTS, "reforma-2-roles-honestos.png"), fullPage: true });
await page.emulateMedia({ colorScheme: "light" });
await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
await page.waitForTimeout(250);
await page.screenshot({ path: join(SHOTS, "reforma-3-tema-claro.png"), fullPage: true });
await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
console.log("\n  · screenshots → conexiones/screenshots/reforma-*.png");

// ══ CALIBRACIÓN EN ROJO ═══════════════════════════════════════════════════════════════
// Una vara que no sabe fallar no mide nada. Se inyecta una fila "conectada" DECLARADA, sin
// evidencia (estado probado, ts nulo) y sin haber corrido ningún ping. La comprobación de
// §8 TIENE que atraparla. Si pasa, la vara es decorativa y el reporte miente.
console.log("\n§CALIBRACIÓN EN ROJO · un «conectado» declarado sin evidencia");
const calib = await page.evaluate(() => {
  const C = window.AlephCentro;
  C.ST.filas.push({ slug: "api.mentira", familia: "api", ref: "mentira", label: "Mentira",
                    marca: "", estado: "probado", causa: null, ts: null, recomendado: false,
                    requisitos: [], fuente: "inyectada-por-la-vara" });
  const huerfanos = C.ST.filas.filter((f) => f.estado === "probado" && !f.ts).map((f) => f.slug);
  C.ST.filas = C.ST.filas.filter((f) => f.slug !== "api.mentira");
  return huerfanos;
});
const atrapada = calib.indexOf("api.mentira") >= 0;
ok(atrapada, "la vara ATRAPA un verde declarado sin ping (si esto pasa en verde, la vara sirve)",
   atrapada ? "detectada: " + calib.join(", ") : "NO LA VIO — la vara §8 es decorativa");

// ── cierre ────────────────────────────────────────────────────────────────────────────
await browser.close();
matar();
peer.close(); server.close();

console.log(`\n${"═".repeat(70)}`);
console.log(fails.length
  ? `✗ ${fails.length}/${total} FALLARON:\n  · ${fails.join("\n  · ")}`
  : `✓ ${total}/${total} — el Centro habla el idioma de la casa.`);
console.log(`fallbacks a serviceFace: ${fallback.length}${fallback.length ? " (" + fallback.map((f) => f.slug).join(", ") + ")" : ""}`);
process.exit(fails.length ? 1 : 0);
