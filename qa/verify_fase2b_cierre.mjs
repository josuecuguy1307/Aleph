/* verify_fase2b_cierre.mjs — LA VARA DE CIERRE DE LA SESIÓN 2.3-2.5.
 *
 * Enunciado: sobre la `.app` INSTALADA, con datadir aislado — un turno real produce
 * un artefacto de tipo CANÓNICO con su procedencia; el vocabulario único gobierna en
 * las dos superficies DENTRO del binario congelado; montar y desmontar obras en el
 * canvas real no deja timers vivos; y el anti-grift, corrido sobre ese espacio real y
 * ese artefacto real, dice AUTÉNTICO — y dice SOSPECHOSO en cuanto se le falsifica
 * un campo.
 *
 * Sujeto: el binario que se le pase (congelado). La Sala es la v1 (`/sala/sala.html`):
 * la v2 no tiene canvas de artefactos (deuda D3 del contrato). El turno entra por
 * `submitUserMessage` — la misma API que dispara el tipeo a mano (paridad-mano), y
 * los cambios de obra se hacen CLICKEANDO la Biblioteca (lección de la obra E de
 * Gate 3: un `.click()` a secas no destapa lo que destapa un puntero real).
 *
 *   SIDECAR=<binario> node qa/verify_fase2b_cierre.mjs
 *   BASE=<url> DATA=<dir> node qa/verify_fase2b_cierre.mjs     ← backend ya corriendo
 *
 * OJO CON EL MODO DEV: un run con tools contra el árbol muere en
 * `models.resolve_recipe_model` (tres `models.py` en el path; bug pre-existente
 * medido en Fase 1). C2 y C5 sólo son medibles contra el CONGELADO — que es el
 * sujeto de esta vara de todas formas.
 * Extras: BRAIN (default http://127.0.0.1:8931/v1) · KEEP=1 · SHOTS=<dir>
 */
import { webkit } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const SIDECAR = process.env.SIDECAR || "";
const PORT = Number(process.env.ALEPH_PORT || 8352);
const BRAIN = process.env.BRAIN || "http://127.0.0.1:8931/v1";
const BRAIN_PORT = new URL(BRAIN).port || "8931";
const SHOTS = process.env.SHOTS || "/tmp/f2b-shots";
mkdirSync(SHOTS, { recursive: true });

const fails = [];
const ok = (n, d) => console.log(`  ✅ ${n}${d ? " — " + d : ""}`);
const bad = (n, d) => { fails.push(`${n}${d ? " — " + d : ""}`); console.log(`  ❌ ${n}${d ? " — " + d : ""}`); };
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

//: Los 16 del contrato §2.2 — escritos acá A PROPÓSITO: una vara que le pregunta al
//: sujeto cuáles son sus tipos no mide nada (mediría que el sujeto es consistente
//: consigo mismo). Este es el testigo independiente.
const CANONICAL = ["informe","documento","planilla","dashboard","web","codigo","imagen","galeria",
                   "3d","cad","schematic","dicom","fieldplot","convergence","volume3d","linechart"];

// ── 0 · el sujeto ─────────────────────────────────────────────────────────────
let BASE, DATA, hijo = null, MEI = null, log = "";
const limpiar = [];
function matarSidecar() {
  if (!hijo) return;
  try { process.kill(-hijo.pid, "SIGTERM"); } catch (_) {}   // onefile = grupo, no el padre
  hijo = null;
}
async function bootSidecar() {
  hijo = spawn(SIDECAR, ["--port", String(PORT)], {
    env: { ...process.env, TMPDIR: MEI, ALEPH_DATA_DIR: DATA, ALEPH_ENV: "dev",
           PUPPET_ALLOW_PASSWORD_AUTH: "1", PUPPET_ALLOW_ANON_V1: "1" },
    detached: true, stdio: ["ignore", "pipe", "pipe"],
  });
  hijo.stdout.on("data", (b) => (log += b));
  hijo.stderr.on("data", (b) => (log += b));
  for (let i = 0; i < 90; i++) {
    await dormir(1000);
    try { const r = await fetch(BASE + "/health", { signal: AbortSignal.timeout(3000) }); if (r.ok) return true; }
    catch (_) {}
  }
  return false;
}

if (SIDECAR) {
  if (!existsSync(SIDECAR)) { console.error(`✗ no existe ${SIDECAR}`); process.exit(1); }
  MEI = mkdtempSync(join(tmpdir(), "f2b-mei-"));
  DATA = process.env.DATA || mkdtempSync(join(tmpdir(), "f2b-data-"));
  BASE = `http://127.0.0.1:${PORT}`;
  const sha = spawnSync("shasum", ["-a", "256", SIDECAR], { encoding: "utf8" }).stdout.trim().slice(0, 16);
  console.log(`\n· sujeto FROZEN: ${SIDECAR}\n· sha256: ${sha}… · datadir: ${DATA}`);
} else {
  BASE = process.env.BASE || "http://127.0.0.1:8261";
  DATA = process.env.DATA;
  if (!DATA) { console.error("✗ en modo BASE hay que pasar DATA=<datadir del backend>"); process.exit(1); }
  console.log(`\n· sujeto DEV: ${BASE} · datadir: ${DATA}`);
}

let brainProc = null;
async function bootBrain() {
  try { const r = await fetch(BRAIN + "/models", { signal: AbortSignal.timeout(1500) }); if (r.status < 599) return true; } catch (_) {}
  brainProc = spawn("python3", [join(REPO, "platform/assembler/cli_brain/server.py")], {
    env: { ...process.env, PUPPET_CLI_BRAIN_PORT: BRAIN_PORT }, detached: true, stdio: "ignore",
  });
  for (let i = 0; i < 30; i++) {
    await dormir(1000);
    try { const r = await fetch(BRAIN + "/models", { signal: AbortSignal.timeout(1500) }); if (r.status < 599) return true; } catch (_) {}
  }
  return false;
}
function teardown() {
  matarSidecar();
  if (brainProc) { try { process.kill(-brainProc.pid, "SIGTERM"); } catch (_) {} brainProc = null; }
  if (!process.env.KEEP) { for (const d of [MEI, SIDECAR ? DATA : null]) { if (d) { try { rmSync(d, { recursive: true, force: true }); } catch (_) {} } } }
  for (const f of limpiar) { try { f(); } catch (_) {} }
}
process.on("exit", teardown);

if (SIDECAR) {
  const vivo = await bootSidecar();
  if (!vivo) { console.error("✗ el sidecar no levantó en 90 s\n" + log.slice(-2000)); process.exit(1); }
  console.log(`· vivo en :${PORT}`);
}
console.log(`· cerebro shim: ${(await bootBrain()) ? BRAIN : "NO LEVANTÓ (los turnos van a fallar)"}`);

// ── cuenta + puppet reales ────────────────────────────────────────────────────
const CUENTA = { email: `vara-f2b-${Date.now()}@example.com`, password: "vara-fase2b-2026" };
let U = null;
for (const ruta of ["/v1/auth/register", "/v1/auth/login"]) {
  const r = await fetch(BASE + ruta, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(CUENTA) });
  if (r.ok) { const j = await r.json().catch(() => null); if (j?.id && j?.session_token) { U = j; break; } }
}
if (!U) { bad("no hubo sesión real — la vara no puede seguir"); teardown(); process.exit(1); }
ok(`sesión real: ${U.id.slice(0, 8)}…`);
const AUTH = { "Content-Type": "application/json", Authorization: "Bearer " + U.session_token };

const RECIPE = {
  schema_version: "v1",
  meta: { name: "vara-fase2b", nicho: "test" },
  model: { primary: "claude-code-cli", base_url: BRAIN, brain_provider: "claude_cli",
           cli_model: "sonnet", effort: "low", max_tokens: 400, temperature: 0, max_turns: 4 },
  belt: { belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
          tool_filters: { calc: ["add"] } },
  rag: { enabled: false },
  keys: {},
};
let PID = null;
{
  const r = await fetch(BASE + "/v1/puppets", { method: "POST", headers: AUTH,
    body: JSON.stringify({ name: "vara-fase2b", owner_id: U.id, nicho: "test", config: RECIPE }) });
  const j = await r.json().catch(() => null);
  PID = j?.id || j?.puppet?.id || null;
}
if (!PID) { bad("no se creó el puppet"); teardown(); process.exit(1); }
ok(`puppet real: ${String(PID).slice(0, 8)}…`);

// ══════════════════════════════════════════════════════════════════════════════
// C1 · EL VOCABULARIO VIAJA ADENTRO DEL CONGELADO Y GOBIERNA EL BORDE
// (la lección de la obra 6d: preguntarle AL BINARIO, no al TOC del bundle)
// ══════════════════════════════════════════════════════════════════════════════
console.log("\nC1 · el vocabulario, adentro del binario");
{
  const r = await fetch(BASE + "/render/vocabulary.js");
  const txt = r.ok ? await r.text() : "";
  r.ok ? ok("el espejo JS del vocabulario se sirve desde el bundle (/render/vocabulary.js)")
       : bad(`el espejo JS NO viajó en el congelado (HTTP ${r.status}) — los dos registros quedan sin identidad`);
  const faltan = CANONICAL.filter((t) => !new RegExp(`"${t}":`).test(txt));
  faltan.length === 0 ? ok(`…con los 16 tipos canónicos adentro`)
                      : bad("al espejo servido le faltan tipos", faltan.join(", "));
  /"diagrama": "schematic"/.test(txt) ? ok("…y su tabla de alias (diagrama→schematic)")
                                      : bad("el espejo servido no trae los alias");
}
const SID_MANUAL = "f2b-borde-" + Date.now();
async function crear(tipo, contenido, titulo) {
  const r = await fetch(`${BASE}/v1/sessions/${SID_MANUAL}/artifacts`, { method: "POST", headers: AUTH,
    body: JSON.stringify({ title: titulo || ("obra " + tipo), type: tipo, content: contenido || "x",
                           user_id: U.id, produced_by: "manual" }) });
  return { status: r.status, body: await r.json().catch(() => null) };
}
{
  const a = await crear("doc", "# carta\n\ncuerpo");
  a.body?.artifact?.type === "documento"
    ? ok("el borde normaliza el alias `doc` → `documento` (mismo vocabulario que el frente)")
    : bad("el alias no se normalizó en el borde", JSON.stringify(a).slice(0, 160));
  const b = await crear("diagrama", "<svg xmlns='http://www.w3.org/2000/svg'></svg>");
  b.body?.artifact?.type === "schematic"
    ? ok("…y `diagrama` → `schematic`")
    : bad("`diagrama` no se normalizó", JSON.stringify(b).slice(0, 160));
  const c = await crear("banana", "x");
  c.status === 422 && c.body?.detail?.error === "artifact_type_invalid"
    ? ok("un tipo fuera de la unión → 422 tipado y visible")
    : bad(`tipo inválido mal rechazado (HTTP ${c.status})`, JSON.stringify(c.body).slice(0, 160));
}

// ══════════════════════════════════════════════════════════════════════════════
// C2 · TURNO REAL → artefacto de tipo canónico con procedencia resuelta
// ══════════════════════════════════════════════════════════════════════════════
console.log("\nC2 · turno real con tool real");
const PROFILE = mkdtempSync(join(tmpdir(), "f2b-profile-"));
limpiar.push(() => rmSync(PROFILE, { recursive: true, force: true }));
const PAGE_URL = `${BASE}/sala/sala.html?puppet=${encodeURIComponent(PID)}`;
const errores = [];

/** Instrumentación de timers ANTES de que cargue la Sala: es la única forma de
 *  contar timers VIVOS en la página real (la del binario, sin tocar su código).
 *  Se guarda el STACK de creación porque la Sala tiene intervalos propios y
 *  legítimos (pollers de estado): contar todos mediría el ruido de la página, no
 *  la fuga del render. Se cuentan los que nacieron DENTRO de render.js. */
const INSTRUMENTO = () => {
  window.__timers = new Map();
  const si = window.setInterval, ci = window.clearInterval;
  window.setInterval = function () {
    const id = si.apply(window, arguments);
    let st = ""; try { st = new Error().stack || ""; } catch (e) {}
    window.__timers.set(id, st);
    return id;
  };
  window.clearInterval = function (id) { window.__timers.delete(id); return ci.call(window, id); };
  window.__timersRender = function () {
    let n = 0;
    window.__timers.forEach(function (st) { if (/render\.js/.test(st)) n++; });
    return n;
  };
};

const ctx = await webkit.launchPersistentContext(PROFILE, { viewport: { width: 1360, height: 900 } });
async function abrirSala() {
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errores.push(String(e && e.message)));
  await page.addInitScript(INSTRUMENTO);
  await page.addInitScript((u) => localStorage.setItem("puppet_user", JSON.stringify(u)), U);
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForSelector("deep-chat", { timeout: 25000 });
  return page;
}
let page;
try { page = await abrirSala(); ok("la Sala v1 montó con el puppet"); }
catch (e) { bad("la Sala v1 no montó", String(e).slice(0, 200)); teardown(); process.exit(1); }

await dormir(2500);
await page.evaluate((t) => document.querySelector("deep-chat").submitUserMessage({ text: t }),
  "Arma un informe corto: usa la herramienta calc para sumar 2 mas 3, y anota el resultado.");

const SID = await page.evaluate((k) => localStorage.getItem(k), "puppet_sala_sid_" + PID);
let arts = [];
const t0 = Date.now();
while (SID && Date.now() - t0 < 180000) {
  await dormir(2500);
  try {
    const r = await fetch(`${BASE}/v1/sessions/${encodeURIComponent(SID)}/artifacts`, { headers: AUTH });
    if (r.ok) { const j = await r.json(); arts = j?.artifacts || []; if (arts.length) break; }
  } catch (_) {}
}
arts.length ? ok(`el turno produjo ${arts.length} artefacto(s)`, `${Math.round((Date.now() - t0) / 1000)} s`)
            : bad("ningún artefacto persistido en 180 s");
await page.screenshot({ path: join(SHOTS, "1-turno-real.png") }).catch(() => {});

const safeSid = String(SID || "").replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
const sessPath = join(DATA, "artifacts", `${safeSid}.json`);
let art = null;
try { art = (JSON.parse(readFileSync(sessPath, "utf8")).artifacts || [])[0] || null; } catch (_) {}
if (art) {
  CANONICAL.includes(art.type)
    ? ok(`el clasificador entregó un tipo del vocabulario: ${art.type}`)
    : bad(`tipo fuera del vocabulario: ${art.type}`);
  const p = art.provenance || {};
  p.model_final && Number(p.tool_calls) >= 1 && p.degraded === null && p.capture_quality === "exact"
    ? ok(`procedencia resuelta del espacio: modelo=${p.model_final} · tool_calls=${p.tool_calls} · degraded=null · exact`)
    : bad("la procedencia no quedó completa", JSON.stringify(p).slice(0, 220));
} else bad("no se pudo leer el artefacto del datadir", sessPath);

// ══════════════════════════════════════════════════════════════════════════════
// C3 · LAS DOS SUPERFICIES, DENTRO DE LA APP
// ══════════════════════════════════════════════════════════════════════════════
console.log("\nC3 · los dos registros de render, medidos en la página del binario");
{
  const m = await page.evaluate(() => {
    const V = window.AlephVocabulary, A = window.AlephRender, S = window.SalaRender;
    if (!V || !A || !S) return { falta: { V: !!V, A: !!A, S: !!S } };
    const nodo = A.render("doc", { content: "x" });
    const rich = typeof window.__salaRichShapes === "function" ? window.__salaRichShapes() : null;
    return {
      canonical: V.CANONICAL, advisory: V.ADVISORY_FIELDS,
      aleph: A.coverage(), sala: S.coverage(),
      despachoDoc: nodo.getAttribute("data-artifact-type"),
      salaDiagrama: S.resolveType("diagrama"), salaTable: S.resolveType("table"),
      rich,
    };
  });
  if (m.falta) {
    bad("faltan globales en la página del binario", JSON.stringify(m.falta));
  } else {
    JSON.stringify(m.canonical.slice().sort()) === JSON.stringify(CANONICAL.slice().sort())
      ? ok("la página del binario ve los 16 canónicos (mismo testigo que esta vara)")
      : bad("la unión de la página no es la del contrato", JSON.stringify(m.canonical));
    (m.advisory || []).length === 0 ? ok("ningún campo del vocabulario quedó ADVISORY")
                                    : bad("quedan campos advisory", JSON.stringify(m.advisory));
    m.aleph.uncovered.length === 0 && m.aleph.outside.length === 0
      ? ok("AlephRender: cobertura completa y ninguna llave fuera de la unión")
      : bad("AlephRender drifteó", JSON.stringify({ u: m.aleph.uncovered, o: m.aleph.outside }));
    m.sala.uncovered.length === 0 && m.sala.outside.length === 0
      ? ok("SalaRender: cobertura completa y ninguna llave fuera de la unión")
      : bad("SalaRender drifteó", JSON.stringify({ u: m.sala.uncovered, o: m.sala.outside }));
    m.despachoDoc === "documento" ? ok("`doc` despacha al renderer `documento` en la app")
                                  : bad("el alias no despacha", String(m.despachoDoc));
    m.salaDiagrama === "schematic" && m.salaTable === "planilla"
      ? ok("la Sala resuelve `diagrama`→schematic y `table`→planilla")
      : bad("la Sala no resuelve alias", JSON.stringify([m.salaDiagrama, m.salaTable]));
    m.rich && m.rich.sinValidador.length === 0 && m.rich.deMas.length === 0
      ? ok(`RICH_SHAPES cubre exactamente los ${m.rich.rich.length} tipos de captura rica`)
      : bad("RICH_SHAPES no coincide con el vocabulario", JSON.stringify(m.rich));
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// C4 · MONTAR/DESMONTAR EN EL CANVAS REAL, CLICKEANDO LA BIBLIOTECA
// ══════════════════════════════════════════════════════════════════════════════
console.log("\nC4 · N ciclos de obra en el canvas real (sin fugas)");
{
  const CONV = JSON.stringify({
    type: "convergence", title: "Loop de la vara",
    metric: { name: "von Mises", unit: "MPa", goal: "min" }, limit: 250,
    iterations: [
      { n: 1, value: 420, grid: { nx: 6, ny: 4, values: Array.from({ length: 24 }, (_, i) => 400 + i) } },
      { n: 2, value: 291, grid: { nx: 6, ny: 4, values: Array.from({ length: 24 }, (_, i) => 280 + i) } },
      { n: 3, value: 180, grid: { nx: 6, ny: 4, values: Array.from({ length: 24 }, (_, i) => 170 + i) } },
    ],
  });
  for (const [t, c, tt] of [["convergence", CONV, "Loop de la vara"],
                            ["informe", "# Informe de la vara\n\ncuerpo", "Informe de la vara"]]) {
    const r = await fetch(`${BASE}/v1/sessions/${encodeURIComponent(SID)}/artifacts`, {
      method: "POST", headers: AUTH,
      body: JSON.stringify({ title: tt, type: t, content: c, user_id: U.id, produced_by: "manual" }) });
    if (!r.ok) bad(`no se pudo sembrar la obra ${t}`, `HTTP ${r.status}`);
  }
  await page.close();
  page = await abrirSala();                      // recarga → hidrata las obras persistidas
  await dormir(3000);

  await page.locator("#libBtn").click().catch(() => {});
  await dormir(600);
  const items = page.locator("#libList .lib-item");
  const n = await items.count();
  n >= 3 ? ok(`la Biblioteca lista ${n} obras tras recargar`) : bad(`la Biblioteca lista ${n} obras (esperaba ≥3)`);

  const CICLOS = 8;
  const base = await page.evaluate(() => window.__timersRender());
  const baseTotal = await page.evaluate(() => window.__timers.size);
  let pico = 0, vistoConv = false;
  for (let i = 0; i < CICLOS && n >= 2; i++) {
    for (const idx of [n - 2, n - 1]) {           // convergence ↔ informe, con puntero real
      await page.locator("#libBtn").click().catch(() => {});
      await dormir(250);
      const it = items.nth(idx);
      await it.scrollIntoViewIfNeeded().catch(() => {});
      await it.click().catch(() => {});
      await dormir(450);
      const v = await page.evaluate(() => window.__timersRender());
      if (v > 0) vistoConv = true;                 // la obra con autoplay SÍ prendió su timer
      pico = Math.max(pico, v);
    }
  }
  const vivos = await page.evaluate(() => window.__timersRender());
  const nodos = await page.evaluate(() => document.querySelectorAll("#canvas .aleph-render").length);
  console.log(`     [medido] ${CICLOS * 2} cambios de obra · timers DE RENDER: base=${base} pico=${pico} final=${vivos}` +
              ` · (intervalos totales de la página al empezar: ${baseTotal}) · nodos de render en el canvas=${nodos}`);
  vistoConv ? ok("la obra con autoplay prendió su timer al montarse (la vara mide algo vivo)")
            : bad("nunca se vio un timer de render: la vara no midió la fuga");
  pico <= 1 ? ok(`${CICLOS * 2} cambios de obra y NUNCA hubo más de un timer de render vivo (pico=${pico})`)
            : bad(`se acumularon timers de render al cambiar de obra (pico=${pico})`);
  vivos === 0 ? ok("con la última obra sin timer, no queda ninguno vivo")
              : bad(`quedaron ${vivos} timers de render vivos al final`);
  nodos <= 1 ? ok(`el canvas sostiene ${nodos} nodo(s) de render, no una pila`)
             : bad(`el canvas acumuló ${nodos} nodos de render`);
  await page.screenshot({ path: join(SHOTS, "2-canvas-tras-ciclos.png") }).catch(() => {});
}
await ctx.close();

// ══════════════════════════════════════════════════════════════════════════════
// C5 · EL ANTI-GRIFT SOBRE LO REAL (y su discriminación, sobre lo mismo)
// ══════════════════════════════════════════════════════════════════════════════
console.log("\nC5 · check_provenance sobre el espacio y el artefacto REALES");
{
  const space = art?.provenance?.space_id;
  const ev = space ? join(DATA, "espacios", space, "events.jsonl") : null;
  const auditar = (evPath, artPath) => {
    const args = [join(REPO, "qa/anti-fake-suite/check_provenance.py"), evPath, "--json"];
    if (artPath) args.push("--artifact", artPath);
    const r = spawnSync("python3", args, { encoding: "utf8" });
    let rep = null; try { rep = JSON.parse(r.stdout); } catch (_) {}
    return { code: r.status, rep };
  };
  if (!ev || !existsSync(ev)) {
    bad("no hay events.jsonl del espacio real para auditar", String(ev));
  } else {
    const a = auditar(ev, sessPath);
    const s8 = (a.rep?.signals || []).find((s) => s.name.startsWith("S8")) || {};
    a.code === 0 && a.rep?.global === "AUTÉNTICO"
      ? ok("AUTÉNTICO sobre el espacio real producido por el binario")
      : bad("el auditor no dio AUTÉNTICO sobre lo real", JSON.stringify(a.rep?.global_reasons || []).slice(0, 300));
    const resumen = (s8.reasons || []).find((r) => /cruce\(s\)/.test(r)) || (s8.reasons || [])[0];
    s8.verdict === "AUTÉNTICO" && /cruce\(s\)/.test(String(resumen))
      ? ok("S8 cruzó el artefacto REAL contra su registro (modelo · tools · hash)", resumen)
      : bad("S8 no midió sobre lo real", JSON.stringify(s8).slice(0, 300));

    // la misma foto, con UN campo falsificado: tiene que caer, y decir cuál.
    const falso = join(DATA, "artifacts", "FALSIFICADO.json");
    const doc = JSON.parse(readFileSync(sessPath, "utf8"));
    doc.artifacts[0].provenance.model_final = "gpt-4o-inventado";
    writeFileSync(falso, JSON.stringify(doc));
    limpiar.push(() => { try { rmSync(falso, { force: true }); } catch (_) {} });
    const b = auditar(ev, falso);
    const s8b = (b.rep?.signals || []).find((s) => s.name.startsWith("S8")) || {};
    b.code === 1 && s8b.verdict === "SOSPECHOSO" && (s8b.reasons || []).some((r) => r.includes("model_final"))
      ? ok("con el modelo falsificado → SOSPECHOSO, exit 1, nombrando `model_final`")
      : bad("la falsificación no se detectó sobre lo real", JSON.stringify(s8b).slice(0, 300));
  }
}

errores.length ? bad(`${errores.length} pageerror`, errores.slice(0, 2).join(" | ")) : ok("cero pageerror en la sesión");

teardown();
console.log("\n" + "═".repeat(64));
if (fails.length) {
  console.log(`VARA FASE 2B (2.3-2.5): ${fails.length} ROJAS`);
  for (const f of fails) console.log("  · " + f);
  process.exit(1);
}
console.log("VARA FASE 2B (2.3-2.5): todo verde");
