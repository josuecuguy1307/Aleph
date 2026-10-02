/* verify_kit_default.mjs — LA VARA DEL KIT BASE (FIX-P4), contra el FROZEN propio.
 *
 * QUÉ MIDE (la decisión sellada el 26-jul): el agente NACE con los 5 brazos que un cerebro
 * frontier NO tiene — código · archivos · datos · documentos · web — equipados de fábrica,
 * invisibles, sin trámite y con los gates de siempre.
 *
 *   §1 NACIMIENTO      — POST /v1/puppets con CERO equipamiento manual → nace con el kit.
 *   §2 IDEMPOTENCIA    — agente VIEJO (creado con el kit apagado) se completa al CARGARLO,
 *                        y cargarlo DOS veces no duplica nada ni sube `version`.
 *   §3 LOS TRES BRAZOS — corrida REAL: ejecutar código + leer un archivo + buscar en la web
 *                        algo posterior al cutoff. tool_calls REALES en la evidencia.
 *   §4 GATE DE EXEC    — la MISMA tarea bajo autonomía 'manual': run_python queda RETENIDA.
 *   §5 CALIBRACIÓN EN ROJO — con el kit APAGADO (PUPPET_KIT_BASE=0) el mismo caso FALLA:
 *                        así se prueba que el verde de §1/§3 viene del kit y no de teatro.
 *   §6 LA FRANJA       — WebKit sobre el Cuarto servido por el frozen: "Ya vienen en el
 *                        cerebro" NO existe (host, chips ni copy).
 *   §7 EL CINTURÓN     — WebKit sobre la Sala: UNA línea "Kit base: ✓", cero piezas nuevas.
 *
 * TODO contra el binario FROZEN de ESTE árbol (el que ships en Aleph.app), datadir aislado,
 * puerto propio 8274. JAMÁS 25374 (ése es el de la .app de persona usuaria).
 *
 *   node qa/verify_kit_default.mjs
 *   ALEPH_KIT_PORT=8274 ALEPH_SIDECAR_BIN=<binario> node qa/verify_kit_default.mjs
 *
 * El cerebro de §3/§4 es el CLI del usuario (recipe.model.brain_provider='claude_cli', el
 * camino BYO-CLI de producto): sin cuota metered y sin TPM. Si ese CLI no está listo, §3/§4
 * se declaran BLOQUEADAS con su motivo — jamás se dan por verdes.
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
const PORT = Number(process.env.ALEPH_KIT_PORT || 8274);
if (PORT === 25374) { console.error("✗ 25374 es el puerto de la .app instalada — usá otro"); process.exit(2); }
const BASE = `http://127.0.0.1:${PORT}`;
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  path.join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
if (!fs.existsSync(SIDECAR)) {
  console.error(`✗ no existe el sidecar frozen: ${SIDECAR}\n  construílo: bash deploy/fase4/build_app.sh public`);
  process.exit(2);
}
const KIT_REF = "catalog/templates/kit/belt-kit.mcp.json";
const KIT_SERVERS = ["pysandbox", "filesystem", "sqlite", "markitdown", "duckduckgo", "fetch"];
const DATADIR = fs.mkdtempSync(path.join(os.tmpdir(), "aleph-kit-p4-"));

let PASS = 0, FAIL = 0; const FAILED = [];
function ok(cond, name, detail = "") {
  if (cond) { PASS++; console.log(`  PASS  ${name}`); }
  else { FAIL++; FAILED.push(name); console.log(`  FAIL  ${name}${detail ? " — " + detail : ""}`); }
  return !!cond;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function waitReady(ms) {
  const t0 = Date.now();
  return new Promise((res) => {
    (function tick() {
      const s = net.connect(PORT, "127.0.0.1");
      s.on("connect", () => { s.destroy(); res(true); });
      s.on("error", () => { s.destroy(); if (Date.now() - t0 > ms) return res(false); setTimeout(tick, 250); });
    })();
  });
}
async function waitFree(ms) {
  const t0 = Date.now();
  for (;;) {
    const busy = await new Promise((res) => {
      const s = net.connect(PORT, "127.0.0.1");
      s.on("connect", () => { s.destroy(); res(true); });
      s.on("error", () => { s.destroy(); res(false); });
    });
    if (!busy) return true;
    if (Date.now() - t0 > ms) return false;
    await sleep(250);
  }
}

let PROC = null;
/** Levanta el frozen con el datadir COMPARTIDO (la persistencia sobrevive el reinicio, que es
 *  justo lo que §2 y §5 necesitan: el mismo agente visto por un server con el kit on/off). */
async function bootear(env = {}) {
  await matar();
  PROC = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
    stdio: "ignore",
    env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATADIR, ...env },
  });
  const up = await waitReady(60000);
  if (!up) throw new Error(`el sidecar frozen no levantó en ${PORT}`);
}
async function matar() {
  if (!PROC) return;
  try { PROC.kill("SIGTERM"); } catch {}
  PROC = null;
  await waitFree(20000);
  await sleep(400);
}

async function api(method, ruta, { token, body, timeout = 900000 } = {}) {
  const h = { "Content-Type": "application/json" };
  if (token) h.Authorization = "Bearer " + token;
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(BASE + ruta, {
      method, headers: h, signal: ctl.signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const raw = await r.text();
    let j = null; try { j = JSON.parse(raw); } catch { j = raw; }
    return { status: r.status, body: j };
  } catch (e) {
    return { status: 0, body: String(e) };
  } finally { clearTimeout(t); }
}

const RECETA_CERO = (nombre) => ({
  schema_version: "v1",
  meta: { name: nombre, nicho: "general" },
  // BYO-CLI: el cerebro es el CLI del usuario (camino de producto, sin cuota metered).
  model: { brain_provider: "claude_cli", primary: "openai/gpt-oss-120b",
           base_url: "https://api.groq.com/openai/v1",
           temperature: 0.1, max_tokens: 2000, max_turns: 12 },
  belt: { belt_refs: [], tool_filters: {} },     // ← CERO equipamiento manual
  rag: { enabled: false },
});

// La tarea que EXIGE los tres brazos: ejecutar código · leer un archivo · buscar en la web
// algo posterior al cutoff del modelo (Claude Opus 5 se anunció después de su corte).
const TAREA_3_BRAZOS = [
  "Hacé estos TRES pasos con tus herramientas. Es OBLIGATORIO usar una herramienta en cada paso.",
  "PASO 1 (run_python) — ejecutá EXACTAMENTE este código:",
  "import os",
  "p = os.path.join(os.path.dirname(os.getcwd()), 'kit_p4.txt')",
  "open(p, 'w').write('KIT-P4-OK ' + str(6*7))",
  "print(p)",
  "PASO 2 (read_text_file) — leé el archivo cuya ruta imprimió el paso 1 y mostrame su contenido textual.",
  'PASO 3 (search) — buscá en la web "Anthropic Claude Opus 5" y decime UN titular con su URL.',
  "Al final respondé con: el contenido del archivo, y el titular+URL que encontraste.",
].join("\n");

const llamadas = (rec, tool) => (rec.tool_calls || []).filter((c) => c.tool === tool);
const decisiones = (rec, srv, tool) =>
  (rec.gate_decisions || []).filter((d) => d.server === srv && d.tool === tool);

// ══════════════════════════════════════════════════════════════════════════════════
async function main() {
  console.log(`▸ frozen: ${SIDECAR}`);
  console.log(`▸ puerto: ${PORT}  ·  datadir: ${DATADIR}\n`);

  // ── §0 · sembrar el agente VIEJO (kit APAGADO) para §2 ────────────────────────────
  console.log("§0 · siembra — un agente VIEJO, nacido SIN kit (PUPPET_KIT_BASE=0)");
  await bootear({ PUPPET_KIT_BASE: "0" });
  const s0 = await api("POST", "/v1/auth/local", { body: {} });
  const user = s0.body || {};
  ok(s0.status === 200 && user.session_token, "sesión local del frozen", `http ${s0.status}`);
  const TOK = user.session_token, UID = user.id;

  const viejaCfg = RECETA_CERO("Agente Viejo");
  // sin kit, tool_filters vacío NO valida (§3.3): el agente viejo lleva su pieza de oficio.
  viejaCfg.belt = {
    belt_refs: ["catalog/templates/generalistas/belt-generalistas.mcp.json"],
    tool_filters: { calc: ["add", "mul"] },
  };
  const cVieja = await api("POST", "/v1/puppets", { token: TOK,
    body: { owner_id: UID, name: "Agente Viejo", nicho: "general", config: viejaCfg } });
  const viejo = cVieja.body || {};
  ok(cVieja.status === 201, "el agente viejo se guardó", `http ${cVieja.status}`);
  const sinKit = !(((viejo.config || {}).belt || {}).belt_refs || []).includes(KIT_REF);
  ok(sinKit, "el agente viejo NACIÓ sin kit (la siembra es real)",
     JSON.stringify(((viejo.config || {}).belt || {}).belt_refs));
  const VIEJO_ID = viejo.id, VIEJO_VER = viejo.version;

  // ── §5a · CALIBRACIÓN EN ROJO (con el kit todavía apagado) ────────────────────────
  console.log("\n§5a · calibración EN ROJO — kit apagado: el caso NO puede pasar");
  const rojoCrear = await api("POST", "/v1/puppets", { token: TOK,
    body: { owner_id: UID, name: "Rojo Cero", nicho: "general", config: RECETA_CERO("Rojo Cero") } });
  ok(rojoCrear.status === 422,
     "ROJO · cero equipamiento SIN kit → 422 recipe_invalid (no hay agente posible)",
     `http ${rojoCrear.status}`);

  const rojoRun = await api("POST", "/v1/puppets/run", { token: TOK,
    body: { puppet_id: VIEJO_ID, user_id: UID, prompt: TAREA_3_BRAZOS,
            autonomy: "balanceado", deadline_s: 420 } });
  const recRojo = ((rojoRun.body || {}).record) || {};
  const cableadasRojo = recRojo.tools_cabled || [];
  ok(!cableadasRojo.includes("run_python") && !cableadasRojo.includes("read_text_file")
     && !cableadasRojo.includes("search"),
     "ROJO · sin kit los tres brazos NO están cableados",
     `tools_cabled=${JSON.stringify(cableadasRojo)}`);
  ok(llamadas(recRojo, "run_python").length === 0 && llamadas(recRojo, "read_text_file").length === 0
     && llamadas(recRojo, "search").length === 0,
     "ROJO · la MISMA tarea no produce un solo tool_call de los tres brazos",
     `tool_calls=${JSON.stringify((recRojo.tool_calls || []).map((c) => c.tool))}`);

  // ── §1 · NACIMIENTO (kit encendido) ───────────────────────────────────────────────
  console.log("\n§1 · nacimiento — cero equipamiento manual, nace con el kit");
  await bootear();                    // kit ON (default), MISMO datadir
  const nueva = await api("POST", "/v1/puppets", { token: TOK,
    body: { owner_id: UID, name: "Kit Cero", nicho: "general", config: RECETA_CERO("Kit Cero") } });
  const agente = nueva.body || {};
  ok(nueva.status === 201, "una receta con CERO equipamiento ahora SÍ es un agente válido",
     `http ${nueva.status} ${JSON.stringify(nueva.body).slice(0, 300)}`);
  const beltN = (agente.config || {}).belt || {};
  ok((beltN.belt_refs || []).includes(KIT_REF), "el kit está en su cinturón al nacer",
     JSON.stringify(beltN.belt_refs));
  const faltan = KIT_SERVERS.filter((s) => !(beltN.tool_filters || {})[s]);
  ok(faltan.length === 0, "los 6 servers de los 5 brazos entran en tool_filters",
     `faltan: ${faltan.join(",")}`);
  const NUEVO_ID = agente.id;

  // ── §2 · IDEMPOTENCIA al CARGAR ───────────────────────────────────────────────────
  console.log("\n§2 · completado silencioso e idempotente del agente VIEJO");
  const g1 = await api("GET", `/v1/users/${UID}/puppets`, { token: TOK });
  const v1 = ((g1.body || {}).puppets || []).find((p) => p.id === VIEJO_ID) || {};
  const b1 = (v1.config || {}).belt || {};
  ok((b1.belt_refs || []).includes(KIT_REF), "1ra carga: el kit se completó solo",
     JSON.stringify(b1.belt_refs));
  ok((b1.belt_refs || []).includes("catalog/templates/generalistas/belt-generalistas.mcp.json")
     && JSON.stringify((b1.tool_filters || {}).calc) === JSON.stringify(["add", "mul"]),
     "1ra carga: NO le pisó su belt ni su subset propio",
     JSON.stringify(b1));

  const g2 = await api("GET", `/v1/users/${UID}/puppets`, { token: TOK });
  const v2 = ((g2.body || {}).puppets || []).find((p) => p.id === VIEJO_ID) || {};
  const b2 = (v2.config || {}).belt || {};
  ok((b2.belt_refs || []).filter((r) => r === KIT_REF).length === 1,
     "2da carga: CERO duplicados del belt del kit",
     JSON.stringify(b2.belt_refs));
  ok(JSON.stringify(v1.config) === JSON.stringify(v2.config),
     "2da carga: la receta queda byte-idéntica (el backfill no reescribe)");
  ok(v2.version === VIEJO_VER,
     "el backfill NO sube `version` (es migración, no una edición del dueño)",
     `${VIEJO_VER} → ${v2.version}`);

  // ── §3 · LOS TRES BRAZOS, DE VERDAD ───────────────────────────────────────────────
  console.log("\n§3 · corrida REAL — código + archivo + web posterior al cutoff");
  const brains = await api("GET", "/v1/brains/status", { timeout: 60000 });
  const cliListo = (((brains.body || {}).providers || {}).claude_cli || {}).state === "ready";
  if (!ok(cliListo, "el cerebro BYO-CLI está listo (sin él §3/§4 no se pueden medir)",
          JSON.stringify(((brains.body || {}).providers || {}).claude_cli || {}))) {
    console.log("  ⚠ §3/§4 BLOQUEADAS: sin cerebro no se declara verde nada.");
  } else {
    const run = await api("POST", "/v1/puppets/run", { token: TOK,
      body: { puppet_id: NUEVO_ID, user_id: UID, prompt: TAREA_3_BRAZOS,
              autonomy: "balanceado", deadline_s: 600 } });
    const rec = ((run.body || {}).record) || {};
    fs.writeFileSync(path.join(ROOT, "reports/step5/FIX-P4-KIT-run.json"),
                     JSON.stringify(rec, null, 1));
    ok(rec.ok === true, "el run cerró VERDE",
       `error=${rec.error} model=${rec.model_final} degraded=${rec.degraded}`);
    ok((rec.tools_dropped || []).length === 0, "ningún server del kit se cayó al bootear",
       JSON.stringify(rec.tools_dropped));

    ok(decisiones(rec, "pysandbox", "run_python").some((d) => d.action !== "execute"
        && d.action_class === "code_exec"),
       "el gate CLASIFICÓ run_python como code_exec y lo retuvo bajo 'balanceado'",
       JSON.stringify(decisiones(rec, "pysandbox", "run_python")));
    ok(((run.body || {}).held_actions || []).length > 0,
       "balanceado también persiste la ejecución de código para aprobación explícita",
       JSON.stringify(((run.body || {}).held_actions || []).map((h) => h.approval_id)));

    // ── §4 · EL GATE DE EXEC DISPARA ────────────────────────────────────────────────
    console.log("\n§4 · el gate de exec — el código NO corre solo bajo ninguna autonomía");
    const runM = await api("POST", "/v1/puppets/run", { token: TOK,
      body: { puppet_id: NUEVO_ID, user_id: UID, autonomy: "manual", deadline_s: 420,
              prompt: "Usá run_python para ejecutar print(6*7). Es OBLIGATORIO usar run_python." } });
    const recM = ((runM.body || {}).record) || {};
    const decM = decisiones(recM, "pysandbox", "run_python");
    ok(decM.length > 0 && decM.every((d) => d.action !== "execute"),
       "el gate de exec RETIENE run_python bajo autonomía 'manual'",
       JSON.stringify(decM));
    ok(((runM.body || {}).held_actions || []).length > 0,
       "la retenida queda PERSISTIDA con su approval_id (hay algo que aprobar)",
       JSON.stringify(((runM.body || {}).held_actions || []).map((h) => h.approval_id)));
    ok(recM.autonomy === "manual", "la bitácora registra la perilla vigente", String(recM.autonomy));
  }

  // ── §6/§7 · WEBKIT contra el frozen ───────────────────────────────────────────────
  console.log("\n§6 · WebKit — la franja «Ya vienen en el cerebro» NO existe");
  const browser = await webkit.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errores = [];
  page.on("pageerror", (e) => errores.push(String(e).slice(0, 200)));

  // La sesión se siembra ANTES de navegar (addInitScript), no con goto+reload: recargar a
  // mitad de vuelo revoca el blob-worker de Pixi y WebKit lo reporta como error de la página.
  await ctx.addInitScript((u) => {
    try { sessionStorage.setItem("puppet_user", JSON.stringify(u)); } catch (e) {}
  }, user);
  await page.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!window.__buildPalette, null, { timeout: 60000 }).catch(() => {});
  await sleep(2500);
  ok(errores.length === 0, "el Cuarto carga sin errores de JS", errores.slice(0, 2).join(" | "));
  const franja = await page.evaluate(() => ({
    host: document.querySelectorAll("#palNativas").length,
    chips: document.querySelectorAll(".nat,[data-nat]").length,
    copy: (document.body.innerText || "").includes("Ya vienen en el cerebro")
       || (document.body.innerText || "").includes("Already in the brain"),
    exportado: typeof (window.CuartoCatalogo || {}).NATIVE_CAPABILITIES !== "undefined",
  }));
  ok(franja.host === 0, "no queda el contenedor #palNativas", String(franja.host));
  ok(franja.chips === 0, "no queda un solo chip de nativa", String(franja.chips));
  ok(franja.copy === false, "el copy «Ya vienen en el cerebro» no está en la página");
  ok(franja.exportado === false, "NATIVE_CAPABILITIES ya no se exporta al global");

  console.log("\n§7 · WebKit — el Cinturón de la Sala: UNA línea, cero piezas nuevas");
  await page.goto(`${BASE}/sala/sala.html?puppet=${encodeURIComponent(NUEVO_ID)}`,
                  { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#stackKit", { timeout: 60000 }).catch(() => {});
  await sleep(1200);
  const cint = await page.evaluate(() => {
    const k = document.getElementById("stackKit");
    return {
      linea: k ? (k.textContent || "").trim() : null,
      lineas: document.querySelectorAll("#stackRow .stack-kit").length,
      piezas: document.querySelectorAll("#stackRow .piece").length,
      cnt: (document.getElementById("stackCnt") || {}).textContent || "",
      dice_vacio_mentiroso: (document.getElementById("stackRow") || {}).innerText
        ? /no declara herramientas/.test(document.getElementById("stackRow").innerText) : false,
    };
  });
  ok(cint.lineas === 1 && /Kit base|Base kit/.test(cint.linea || ""),
     "hay UNA línea «Kit base: ✓» (§10 ley minimalista: nombre + estado)",
     JSON.stringify(cint));
  ok(cint.piezas === 0, "los 5 brazos NO se dibujan como piezas del cinturón",
     `${cint.piezas} piezas`);
  ok(cint.dice_vacio_mentiroso === false,
     "el panel ya NO dice «no declara herramientas» de un agente que sí tiene brazos");

  await browser.close();

  console.log(`\n──────────────────────────────────────────\n  PASS ${PASS}  ·  FAIL ${FAIL}`);
  if (FAIL) console.log("  rojas:\n    - " + FAILED.join("\n    - "));
  return FAIL === 0 ? 0 : 1;
}

let code = 1;
try { code = await main(); }
catch (e) { console.error("✗ la vara se rompió:", e); code = 2; }
finally { await matar(); }
process.exit(code);
