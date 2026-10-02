/* verify_inmersion_ciencia.mjs — LA INMERSIÓN DEL WORKSPACE DE CIENCIA.
 * [Gate 4 · F3-ciencia · inmersión 3.8 · ley 3 · ley 6]
 *
 * ENUNCIADO. Entrar a Ciencia desde frío tiene que dar el banco de trabajo, DIRECTO: cero
 * pantallas intermedias, cero auth visible, cero palabra que no sea de Aleph. Y cuando el
 * stack NO está, la pantalla tiene que decirlo — jamás afirmar «en vivo» sobre un lienzo
 * roto.
 *
 * POR QUÉ ESTA VARA EXISTE, Y ES UNA HISTORIA CORTA. La obra tenía el registro en verde,
 * la vara del borde en 23/0 y ninguna roja en ningún lado. Una CAPTURA mostró la barra de
 * Aleph diciendo «● en vivo» dos centímetros arriba de un lienzo que decía «Local
 * workspace unavailable». La pantalla se contradecía a sí misma y ninguna medición lo
 * había visto, porque todas medían el JSON y ninguna miraba la cara.
 *
 * LA CAUSA, MEDIDA: `running` pedía `/` y daba por vivo cualquier 200. Contra este stack
 * esa sonda está INVERTIDA en las dos direcciones:
 *
 *     corriendo de verdad  →  GET /  404   ·  GET /global/health  200
 *     sólo su dist servido →  GET /  200   ·  GET /global/health  404
 *
 * El PASO 2 de acá abajo es exactamente ese caso, convertido en regresión: se sirve el
 * `dist` sin su backend —un servidor estático, que contesta 200 en `/`— y se exige que el
 * registro diga `running:false` y que la pantalla diga la verdad. Con la sonda vieja este
 * paso queda ROJO; es la prueba de que la vara cae.
 *
 * SE MIRAN LOS PÍXELES, NO LAS PROPIEDADES. `el.hidden` fue `true` mientras el cartel se
 * veía pintado encima del terminal (la lección que el propio `workspace.css` documenta):
 * `[hidden]` no gana contra un `display` de autor. Acá se usa `isVisible()` de Playwright
 * y además se sacan capturas, que hay que MIRAR.
 *
 * Uso:  node qa/verify_inmersion_ciencia.mjs
 *       PYBIN=<python del venv>   SIDECAR=<binario>   SHOTS=<dir>
 */
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { mkdtempSync, mkdirSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright";

const PUERTO = Number(process.env.PUERTO || 8401);
const BASE = `http://127.0.0.1:${PUERTO}`;
const WS_PUERTO = Number(process.env.WS_PUERTO || 4096);
const WS_URL = `http://127.0.0.1:${WS_PUERTO}`;
const SIDECAR = process.env.SIDECAR || "";
const PYBIN = process.env.PYBIN || fileURLToPath(new URL("../product/backend/.venv/bin/python", import.meta.url));
const BUN = process.env.BUN || "bun";
const CHROME = process.env.CAP_CHROME || "";
const SHOTS = process.env.SHOTS || "/tmp/inmersion-ciencia";
const DIST = "third_party/openscience/frontend/workspace/dist";
//: ABSOLUTA: el stack se lanza con `cwd` en su propio datadir aislado, así que una
//: ruta relativa al repo no resuelve desde ahí (se midió: el proceso no levantaba).
const STACK_ENTRY = resolve("third_party/openscience/backend/cli/src/index.ts");

//: Las palabras del proyecto de origen que NO pueden aparecer en la cara. Viajan
//: codificadas por la misma razón que en la vara de la cosecha: un guard que lleva en
//: claro el término que prohíbe es su propio hit.
const _d = (s) => Buffer.from(s, "base64").toString("utf8");
const MARCAS = ["T3BlblNjaWVuY2U=", "U3ludGhldGljIFNjaWVuY2Vz", "c3ludGhldGljc2NpZW5jZXM=", "QXRsYXM="].map(_d);

const fails = [];
const oks = [];
const ok = (n, d) => { oks.push(n); console.log(`  ✅ ${n}${d ? " — " + d : ""}`); };
const bad = (n, d) => { fails.push(`${n}${d ? " — " + d : ""}`); console.log(`  ❌ ${n}${d ? " — " + d : ""}`); };
const sec = (t) => console.log(`\n── ${t} ${"─".repeat(Math.max(0, 74 - t.length))}`);

const DATA = mkdtempSync(join(tmpdir(), "inm-"));
const WSDATA = mkdtempSync(join(tmpdir(), "inm-ws-"));
mkdirSync(SHOTS, { recursive: true });
let backend = null, stack = null, navegador = null;

function matar(p) {
  if (!p) return;
  try { process.kill(-p.pid, "SIGKILL"); } catch (_) { try { p.kill("SIGKILL"); } catch (__) {} }
}
async function esperar(url, ms = 60000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try { const r = await fetch(url, { signal: AbortSignal.timeout(2500) }); if (r.ok) return true; } catch (_) {}
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

let cerrado = false;
function cerrar(motivo) {
  if (cerrado) return;
  cerrado = true;
  matar(stack); matar(backend);
  try { navegador?.close(); } catch (_) {}
  spawnSync("pkill", ["-f", `ALEPH_DATA_DIR=${DATA}`]);
  rmSync(DATA, { recursive: true, force: true });
  rmSync(WSDATA, { recursive: true, force: true });
  console.log(`\n${"═".repeat(78)}`);
  if (motivo) console.log(`  ⛔ LA VARA NO LLEGÓ AL FINAL — ${motivo}`);
  console.log(`  ${oks.length} verdes · ${fails.length} rojas${motivo ? "  (PARCIAL)" : ""}`);
  if (fails.length) { console.log("\n  ROJAS:"); fails.forEach((f) => console.log("   ✗ " + f)); }
  console.log(`  capturas en ${SHOTS} — MIRARLAS (el verde no prueba la cara)`);
  console.log(`${"═".repeat(78)}\n`);
  process.exit(motivo || fails.length ? 1 : 0);
}
process.on("uncaughtException", (e) => cerrar(`EXCEPCIÓN: ${e?.message || e}`));
process.on("unhandledRejection", (e) => cerrar(`RECHAZO: ${e?.message || e}`));

function arrancarBackend() {
  const env = { ...process.env, ALEPH_DATA_DIR: DATA, ALEPH_ENV: "dev",
                PUPPET_ALLOW_PASSWORD_AUTH: "1", PUPPET_ALLOW_ANON_V1: "1",
                ALEPH_WORKSPACE_CIENCIA_URL: WS_URL };
  if (SIDECAR) {
    const p = spawn(SIDECAR, ["--port", String(PUERTO)], { env, detached: true, stdio: "ignore" });
    p.unref(); return p;
  }
  const p = spawn(PYBIN, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(PUERTO)],
                  { env, cwd: "product/backend", detached: true, stdio: "ignore" });
  p.unref(); return p;
}

/** El `dist` servido SIN su backend: un servidor estático. Contesta 200 en `/` y no tiene
 *  API. Es el caso que la captura destapó, y el que la sonda vieja llamaba «en vivo». */
function arrancarSoloDist() {
  const p = spawn("python3", ["-m", "http.server", String(WS_PUERTO), "--bind", "127.0.0.1"],
                  { cwd: DIST, detached: true, stdio: "ignore" });
  p.unref(); return p;
}

/** El stack de verdad: su server, con su API. */
function arrancarStackVivo() {
  const p = spawn(BUN, ["--conditions=browser", STACK_ENTRY, "serve", "--port", String(WS_PUERTO)], {
    env: { ...process.env,
           XDG_CONFIG_HOME: join(WSDATA, "config"), XDG_DATA_HOME: join(WSDATA, "data"),
           XDG_CACHE_HOME: join(WSDATA, "cache"), XDG_STATE_HOME: join(WSDATA, "state"),
           OPENSCIENCE_CONFIG_DIR: join(WSDATA, "config", "openscience"),
           OPENSCIENCE_DATA_DIR: join(WSDATA, "data", "openscience") },
    cwd: WSDATA, detached: true, stdio: "ignore",
  });
  p.unref(); return p;
}

const J = (r) => r.json();
async function registro() {
  const r = await fetch(`${BASE}/v1/workspaces`);
  const j = await J(r).catch(() => ({}));
  return (j.workspaces || []).find((w) => w.id === "ciencia") || null;
}

/** Abre la pantalla del workspace, saca la captura y devuelve lo que se VE. */
async function mirarPantalla(nombre) {
  const p = await navegador.newPage({ viewport: { width: 1440, height: 900 } });
  const errs = [];
  p.on("pageerror", (e) => errs.push(String(e).slice(0, 160)));
  await p.goto(`${BASE}/workspaces/ciencia.html`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await p.waitForTimeout(6000);
  const shot = join(SHOTS, nombre + ".png");
  await p.screenshot({ path: shot });
  // EL CONTENIDO DEL LIENZO, no sólo su caja. Un `<iframe>` con un 404 adentro está
  // perfectamente «visible»: la primera versión de esta vara dio 16/0 con el lienzo
  // mostrando `404 Not Found`, y lo destapó la CAPTURA. `isVisible()` mide la caja;
  // esto mide lo que el usuario lee.
  let lienzo = "";
  try {
    const f = p.frameLocator("#ws-frame");
    lienzo = (await f.locator("body").innerText({ timeout: 4000 })).trim();
  } catch (_) { lienzo = ""; }

  const out = {
    lienzo,
    titulo: await p.title(),
    // PÍXELES, no propiedades: `[hidden]` no gana contra un `display` de autor.
    frameVisible: await p.locator("#ws-frame").isVisible().catch(() => null),
    caidoVisible: await p.locator("#ws-caido").isVisible().catch(() => null),
    estado: (await p.locator("#ws-estado").innerText().catch(() => "")).trim(),
    texto: await p.locator("body").innerText().catch(() => ""),
    errores: errs, shot,
  };
  await p.close();
  return out;
}

// ═══════════════════════════════════════════════════════════════════════════════════════
console.log(`\n· sujeto      ${SIDECAR || `${PYBIN} -m uvicorn (fuente)`}`);
console.log(`· workspace   ${WS_URL}`);
console.log(`· capturas    ${SHOTS}\n`);

if (!existsSync(join(DIST, "index.html")))
  cerrar(`no existe ${DIST}/index.html — corré \`bun run build\` en frontend/workspace primero`);

backend = arrancarBackend();
if (!(await esperar(`${BASE}/health`))) cerrar("el backend de Aleph no levantó");
navegador = await chromium.launch(CHROME ? { executablePath: CHROME } : {});

// ── PASO 1 · INSTALADO ES UN HECHO, NO UNA DECLARACIÓN ────────────────────────────────
sec("PASO 1 · el registro: `installed` sale de que el dist EXISTA");
{
  const w = await registro();
  if (w) ok("Ciencia está en el registro", `label=${w.label} · icon=${w.icon}`);
  else bad("Ciencia está en el registro", "GET /v1/workspaces no la trae");
  if (w?.stack?.installed) ok("`installed` es verdadero porque el dist está", DIST);
  else bad("`installed` es verdadero", JSON.stringify(w?.stack));
  if ((w?.sources || []).length === 42) ok("y el censo 2.ter viaja con la fila", "42 fuentes");
  else bad("el censo 2.ter viaja con la fila", `${(w?.sources || []).length} fuentes`);
}

// ── PASO 2 · LA REGRESIÓN: 200 EN `/` NO ES ESTAR VIVO ────────────────────────────────
sec("PASO 2 · el dist SIN su backend: la sonda vieja decía «en vivo» acá");
{
  stack = arrancarSoloDist();
  await esperar(`${WS_URL}/`, 20000);

  const raiz = await fetch(`${WS_URL}/`).then((r) => r.status).catch(() => 0);
  const salud = await fetch(`${WS_URL}/global/health`).then((r) => r.status).catch(() => 0);
  if (raiz === 200 && salud !== 200)
    ok("el servidor estático contesta 200 en `/` y NO tiene señal de salud", `/ → ${raiz} · /global/health → ${salud}`);
  else bad("el caso de la regresión está bien montado", `/ → ${raiz} · /global/health → ${salud}`);

  const w = await registro();
  // ── EL ASSERT QUE CAE CON LA SONDA VIEJA ──────────────────────────────────────────
  if (w?.stack?.running === false)
    ok("`running` es FALSO: un 200 en `/` no es estar vivo", "la sonda mira la señal de salud, no la puerta");
  else bad("`running` es falso cuando sólo hay archivos estáticos",
           `running=${w?.stack?.running} — con la sonda vieja (GET /) esto da true y la barra miente`);

  const cara = await mirarPantalla("2-sin-backend");
  if (cara.caidoVisible === true && cara.frameVisible === false)
    ok("la pantalla dice que no corre, y NO pinta el lienzo", cara.shot);
  else bad("la pantalla dice que no corre", `caido=${cara.caidoVisible} · frame=${cara.frameVisible}`);
  if (!/en vivo|live/i.test(cara.estado))
    ok("y la barra NO afirma «en vivo» sobre un lienzo roto", `estado="${cara.estado}"`);
  else bad("la barra no afirma «en vivo» sobre un lienzo roto",
           `estado="${cara.estado}" — ÉSTE es el defecto que la captura destapó`);

  matar(stack); stack = null;
  await new Promise((r) => setTimeout(r, 1500));
}

// ── PASO 3 · EL STACK VIVO: LA INMERSIÓN ──────────────────────────────────────────────
sec("PASO 3 · el stack corriendo de verdad: entrar es estar adentro");
{
  stack = arrancarStackVivo();
  const vivo = await esperar(`${WS_URL}/global/health`, 60000);
  if (vivo) ok("el stack contesta su señal de salud", `${WS_URL}/global/health`);
  else bad("el stack contesta su señal de salud", "no levantó");

  const raiz = await fetch(`${WS_URL}/`).then((r) => r.status).catch(() => 0);
  const w = await registro();
  if (w?.stack?.running === true)
    ok("`running` es VERDADERO aunque `/` conteste " + raiz, "la sonda vieja lo habría dado por muerto");
  else bad("`running` es verdadero con el stack vivo", `running=${w?.stack?.running} · / → ${raiz}`);

  const cara = await mirarPantalla("3-vivo");
  if (cara.frameVisible === true && cara.caidoVisible === false)
    ok("la caja del lienzo está puesta y el cartel de fallo no", cara.shot);
  else bad("la caja del lienzo está puesta", `frame=${cara.frameVisible} · caido=${cara.caidoVisible}`);

  // ── EL ASSERT QUE LA PRIMERA VERSIÓN NO TENÍA ─────────────────────────────────────
  // Un iframe con un 404 adentro es un iframe visible. Acá se lee lo que el usuario lee.
  const vacio = !cara.lienzo || /^404|not found/i.test(cara.lienzo);
  if (!vacio && cara.lienzo.length > 40)
    ok("y ADENTRO está el banco de trabajo — cero pantallas intermedias",
       JSON.stringify(cara.lienzo.slice(0, 70)));
  else
    bad("adentro del lienzo está el banco de trabajo",
        `el lienzo dice ${JSON.stringify((cara.lienzo || "(vacío)").slice(0, 60))} — desde FUENTE el stack no sirve su UI ` +
        `(sus assets se embeben en su propio build). La inmersión completa se mide contra la .app construida.`);
  if (/en vivo|live/i.test(cara.estado)) ok("y la barra dice «en vivo» sobre algo que SÍ lo está", cara.estado);
  else bad("la barra dice «en vivo»", `estado="${cara.estado}"`);
}

// ── PASO 4 · CERO PALABRA QUE NO SEA DE ALEPH ─────────────────────────────────────────
sec("PASO 4 · la piel: ni una palabra del proyecto de origen en la cara");
{
  const cara = await mirarPantalla("4-piel");
  const sucias = MARCAS.filter((m) => new RegExp(m, "i").test(cara.texto));
  if (!sucias.length) ok(`las ${MARCAS.length} marcas del proyecto de origen, ausentes del texto`, "medido sobre el innerText");
  else bad("cero palabra del proyecto de origen", `aparecen: ${sucias.join(", ")}`);

  if (/Ciencia/.test(cara.titulo) && /Aleph/.test(cara.titulo)) ok("el título es de la casa", cara.titulo);
  else bad("el título es de la casa", cara.titulo);

  if (/La Sala/.test(cara.texto)) ok("y el camino de vuelta a La Sala está a la vista", "◂ La Sala");
  else bad("el camino de vuelta a La Sala está a la vista", "no aparece");

  // Cero auth visible: entrar no puede pedir cuenta ni mostrar un login.
  if (!/iniciar sesión|sign in|log in|api key/i.test(cara.texto))
    ok("cero auth visible: entrar no pide cuenta", "la sesión es la de Aleph y ya estaba resuelta");
  else bad("cero auth visible", "aparece algo de login/llave en la cara");

  if (!cara.errores.length) ok("y la pantalla no tira un solo error de consola", "0 pageerror");
  else bad("la pantalla no tira errores de consola", cara.errores.slice(0, 2).join(" | "));
}

cerrar(null);
