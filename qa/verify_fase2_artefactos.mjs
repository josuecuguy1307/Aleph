/* verify_fase2_artefactos.mjs — LA VARA DE LA FASE 2 (contrato de artefactos).
 *
 * Enunciado (contrato §9): un artefacto real, producido por un turno real con tool real,
 * lleva su identidad ADENTRO, se versiona, sobrevive cerrar/reabrir, y check_provenance
 * valida su espacio. Anti-grift: model_final real · tool_calls > 0 · degraded = null.
 *
 * Sujeto: el binario que se le pase —dev o CONGELADO— sirviendo su propio frontend.
 * La Sala que se maneja es la v1 (`/sala/sala.html`): la v2 no tiene canvas de
 * artefactos todavía (deuda D3 del contrato). El turno entra por deep-chat
 * `submitUserMessage` — la MISMA API que dispara el tipeo a mano (paridad-mano).
 *
 * DATADIR AISLADO SIEMPRE: el sujeto es el binario, no los datos de persona usuaria.
 *
 * Modos:
 *   SIDECAR=<binario> node qa/verify_fase2_artefactos.mjs   ← levanta el congelado él mismo
 *   BASE=<url> DATA=<dir> node qa/verify_fase2_artefactos.mjs  ← backend ya corriendo (dev)
 * Extras: BRAIN (default http://127.0.0.1:8931/v1) · KEEP=1 (no barrer el datadir) ·
 *         SHOTS=<dir> (default /tmp/f2-shots)
 *
 * Declarado, no escondido: la EDICIÓN por UI necesita la cognición Groq (clasificador
 * edit/new) que el datadir aislado no tiene — el versionado se ejercita en el BORDE del
 * binario (PUT/revert), que ES el contrato. La invocación de check_provenance acá es
 * manual: cablearlo al runner es la obra 2.5, de otra sesión.
 */
import { webkit } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync, readFileSync, writeFileSync, mkdirSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const SIDECAR = process.env.SIDECAR || "";
const PORT = Number(process.env.ALEPH_PORT || 8341);
const BRAIN = process.env.BRAIN || "http://127.0.0.1:8931/v1";
const BRAIN_PORT = new URL(BRAIN).port || "8931";
const SHOTS = process.env.SHOTS || "/tmp/f2-shots";
mkdirSync(SHOTS, { recursive: true });

const fails = [];
const ok = (n, d) => console.log(`  ✅ ${n}${d ? " — " + d : ""}`);
const bad = (n, d) => { fails.push(`${n}${d ? " — " + d : ""}`); console.log(`  ❌ ${n}${d ? " — " + d : ""}`); };
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
const sha256 = (s) => createHash("sha256").update(s, "utf8").digest("hex");
const CANONICAL = ["informe","documento","planilla","dashboard","web","codigo","imagen","galeria",
                   "3d","cad","schematic","dicom","fieldplot","convergence","volume3d","linechart"];

// ── 0 · el sujeto ─────────────────────────────────────────────────────────────────────
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
  MEI = mkdtempSync(join(tmpdir(), "f2-mei-"));
  DATA = process.env.DATA || mkdtempSync(join(tmpdir(), "f2-data-"));
  BASE = `http://127.0.0.1:${PORT}`;
  const sha = spawnSync("shasum", ["-a", "256", SIDECAR], { encoding: "utf8" }).stdout.trim().slice(0, 16);
  console.log(`\n· sujeto FROZEN: ${SIDECAR}\n· sha256: ${sha}… · datadir: ${DATA}`);
} else {
  BASE = process.env.BASE || "http://127.0.0.1:8261";
  DATA = process.env.DATA;
  if (!DATA) { console.error("✗ en modo BASE hay que pasar DATA=<datadir del backend>"); process.exit(1); }
  console.log(`\n· sujeto DEV: ${BASE} · datadir: ${DATA}`);
}

// ── el cerebro: shim BYO-CLI sobre el `claude` local (arnés, no sujeto) ───────────────
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

// ── 1 · SEMBRAR el legacy v1 ANTES de que el binario escriba nada ─────────────────────
const LEGACY_SID = "legacy-f2";
{
  const dir = join(DATA, "artifacts");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, `${LEGACY_SID}.json`), JSON.stringify({
    session_id: LEGACY_SID,
    artifacts: [{ id: "aaaa11112222", session_id: LEGACY_SID, title: "Obra vieja",
                  type: "diagrama", content: "legacy", versions: [],
                  created_at: "2026-01-01T00:00:00+00:00", updated_at: "2026-01-01T00:00:00+00:00" }],
  }));
}

if (SIDECAR) {
  const vivo = await bootSidecar();
  if (!vivo) { console.error("✗ el sidecar no levantó en 90 s\n" + log.slice(-2000)); process.exit(1); }
  console.log(`· vivo en :${PORT} · frontend: ${(log.match(/\[serving\] frontend montado desde (\S+)/) || [])[1] || "?"}`);
}
console.log(`· cerebro shim: ${(await bootBrain()) ? BRAIN : "NO LEVANTÓ (los turnos van a fallar)"}`);

// ── 2 · cuenta real + puppet real (calc vía shim BYO-CLI) ─────────────────────────────
const CUENTA = { email: `vara-f2-${Date.now()}@example.com`, password: "vara-fase2-2026" };
let U = null;
for (const ruta of ["/v1/auth/register", "/v1/auth/login"]) {
  const r = await fetch(BASE + ruta, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(CUENTA) });
  if (r.ok) { const j = await r.json().catch(() => null); if (j?.id && j?.session_token) { U = j; break; } }
}
U ? ok(`sesión real: ${U.id.slice(0, 8)}…`) : bad("no hubo sesión — la vara no puede seguir");
if (!U) { teardown(); process.exit(1); }
const AUTH = { "Content-Type": "application/json", Authorization: "Bearer " + U.session_token };

const RECIPE = {
  schema_version: "v1",
  meta: { name: "vara-fase2", nicho: "test" },
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
    body: JSON.stringify({ name: "vara-fase2", owner_id: U.id, nicho: "test", config: RECIPE }) });
  const j = await r.json().catch(() => null);
  PID = j?.id || j?.puppet?.id || null;
  PID ? ok(`puppet real: ${String(PID).slice(0, 8)}…`) : bad(`no se creó el puppet (${r.status})`, JSON.stringify(j).slice(0, 200));
}
if (!PID) { teardown(); process.exit(1); }

// ── 3 · navegador PERSISTENTE (el perfil sobrevive el cierre, como la webview del .app) ─
const PROFILE = mkdtempSync(join(tmpdir(), "f2-profile-"));
limpiar.push(() => rmSync(PROFILE, { recursive: true, force: true }));
const PAGE_URL = `${BASE}/sala/sala.html?puppet=${encodeURIComponent(PID)}`;
const errores = [];

async function abrirSala(ctx) {
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errores.push(String(e && e.message)));
  await page.addInitScript((u) => localStorage.setItem("puppet_user", JSON.stringify(u)), U);
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForSelector("deep-chat", { timeout: 25000 });
  return page;
}

let ctx = await webkit.launchPersistentContext(PROFILE, { viewport: { width: 1360, height: 900 } });
let page;
try { page = await abrirSala(ctx); ok("la Sala v1 montó con el puppet"); }
catch (e) { bad("la Sala v1 no montó", String(e).slice(0, 200)); teardown(); process.exit(1); }

// ── 4 · TURNO REAL → artefacto persistido ─────────────────────────────────────────────
console.log("\n4 · turno real con tool real (calc.add vía cerebro CLI)");
const PROMPT = "Arma un informe corto: usa la herramienta calc para sumar 2 mas 3, y anota el resultado.";
await dormir(2500);   // controles/receta del puppet cargando (controlsReady gatea el Send)
await page.evaluate((t) => {
  const dc = document.querySelector("deep-chat");
  dc.submitUserMessage({ text: t });   // la MISMA API que dispara el tipeo a mano
}, PROMPT);

const sidKey = "puppet_sala_sid_" + PID;
const SID = await page.evaluate((k) => localStorage.getItem(k), sidKey);
SID ? ok(`sid de dominio en localStorage: ${SID.slice(0, 18)}…`) : bad("el sid NO está en localStorage (¿clave de pestaña otra vez?)");

let arts = [];
const t0 = Date.now();
while (SID && Date.now() - t0 < 180000) {
  await dormir(2500);
  try {
    const r = await fetch(`${BASE}/v1/sessions/${encodeURIComponent(SID)}/artifacts`, { headers: AUTH });
    if (r.ok) { const j = await r.json(); arts = j?.artifacts || []; if (arts.length) break; }
  } catch (_) {}
}
arts.length ? ok(`el turno produjo ${arts.length} artefacto(s) persistido(s)`, `${Math.round((Date.now() - t0) / 1000)} s`)
            : bad("ningún artefacto persistido en 180 s");
await page.screenshot({ path: join(SHOTS, "1-obra.png"), fullPage: false }).catch(() => {});

// ── 5 · EL CONTRATO, leído del DISCO del datadir ──────────────────────────────────────
console.log("\n5 · identidad ADENTRO, leída del disco (no de la pantalla)");
const safeSid = String(SID || "").replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
const sessPath = join(DATA, "artifacts", `${safeSid}.json`);
let doc = null, art = null;
try { doc = JSON.parse(readFileSync(sessPath, "utf8")); art = (doc.artifacts || [])[0] || null; } catch (e) { bad("no se pudo leer el JSON de la sesión", String(e).slice(0, 120)); }
if (doc) {
  doc.schema_version === 2 ? ok("schema_version = 2 en el archivo") : bad("schema_version ≠ 2", String(doc.schema_version));
  doc.owner === U.id ? ok("owner = la cuenta real (claim-on-first-create)") : bad("owner no ligado", String(doc.owner));
}
if (art) {
  const p = art.provenance || {};
  CANONICAL.includes(art.type) ? ok(`type canónico: ${art.type}`) : bad(`type fuera del vocabulario: ${art.type}`);
  art.content_sha256 === sha256(art.content || "") ? ok("content_sha256 verifica") : bad("content_sha256 NO verifica");
  p.produced_by === "run" ? ok("produced_by = run") : bad("produced_by ≠ run", String(p.produced_by));
  p.capture_quality === "exact" ? ok("capture_quality = exact (resuelto del espacio)") : bad("capture_quality ≠ exact", String(p.capture_quality));
  p.space_id && p.run_id ? ok(`referencia re-verificable: space=${String(p.space_id).slice(0, 14)}… run=${String(p.run_id).slice(0, 8)}…`) : bad("faltan space_id/run_id");
  p.model_final ? ok(`model_final REAL: ${p.model_final}`) : bad("model_final vacío (¿lo declaró el cliente en vez de resolverlo el server?)");
  Number(p.tool_calls) >= 1 ? ok(`tool_calls = ${p.tool_calls} (> 0)`) : bad(`tool_calls = ${p.tool_calls}`);
  (p.tools || []).includes("calc") ? ok(`tools incluye calc: [${(p.tools || []).join(", ")}]`) : bad("tools no incluye calc", JSON.stringify(p.tools));
  p.degraded === null ? ok("degraded = null") : bad("degraded ≠ null", String(p.degraded));
  p.ok === true ? ok("ok = true") : bad("ok ≠ true", String(p.ok));
  p.user_id === U.id ? ok("user_id = quién (la cuenta)") : bad("user_id no coincide", String(p.user_id));
  p.agent_id === PID ? ok("agent_id = el puppet") : bad("agent_id no coincide", String(p.agent_id));
  p.intent ? ok(`intent: «${String(p.intent).slice(0, 40)}…»`) : bad("intent vacío");
}

// ── 6 · VERSIONADO en el borde del binario (el edit por UI necesita cognición Groq) ───
console.log("\n6 · versionado con identidad por versión (borde del binario)");
if (art) {
  const r = await fetch(`${BASE}/v1/sessions/${encodeURIComponent(SID)}/artifacts/${art.id}`, {
    method: "PUT", headers: AUTH,
    body: JSON.stringify({ content: (art.content || "") + "\n\n— editado por la vara", user_id: U.id,
                           produced_by: "manual", intent: "edicion de la vara" }) });
  const e1 = (await r.json().catch(() => null))?.artifact;
  if (e1) {
    (e1.versions || []).length >= 1 ? ok(`versions = ${e1.versions.length}`) : bad("no se snapshoteó versión");
    const v0 = (e1.versions || [])[0] || {};
    v0.provenance?.produced_by === "run" ? ok("la versión previa CONSERVA su identidad (run)") : bad("la versión previa perdió identidad", JSON.stringify(v0.provenance || {}).slice(0, 120));
    e1.provenance?.produced_by === "manual" ? ok("el contenido nuevo lleva SU identidad (manual)") : bad("la identidad nueva no es del turno editor");
    const rv = await fetch(`${BASE}/v1/sessions/${encodeURIComponent(SID)}/artifacts/${art.id}/revert`, { method: "POST", headers: AUTH, body: "{}" });
    const e2 = (await rv.json().catch(() => null))?.artifact;
    e2 && e2.content === art.content && e2.provenance?.produced_by === "run"
      ? ok("revert restaura contenido Y procedencia JUNTOS")
      : bad("revert no restauró contenido+procedencia", JSON.stringify({ c: e2?.content === art.content, p: e2?.provenance?.produced_by }));
  } else bad("el edit del borde falló", `HTTP ${r.status}`);

  const rb = await fetch(`${BASE}/v1/sessions/${encodeURIComponent(SID)}/artifacts`, {
    method: "POST", headers: AUTH,
    body: JSON.stringify({ title: "Mala", type: "banana", content: "x", user_id: U.id, produced_by: "manual" }) });
  rb.status === 422 && (await rb.json().catch(() => ({})))?.detail?.error === "artifact_type_invalid"
    ? ok("tipo fuera del vocabulario → 422 artifact_type_invalid (tipado, visible)")
    : bad(`tipo inválido no rechazó bien (HTTP ${rb.status})`);
}

// ── 7 · LEGACY v1 leído por el binario: repara al leer, sube a v2 al escribir ─────────
console.log("\n7 · legacy v1 sembrado antes del boot");
{
  const r = await fetch(`${BASE}/v1/sessions/${LEGACY_SID}/artifacts/aaaa11112222`, { headers: AUTH });
  const a = (await r.json().catch(() => null))?.artifact;
  a?.type === "schematic" ? ok("alias reparado al leer (diagrama→schematic), disco intacto") : bad("el legacy no se reparó al leer", JSON.stringify(a || {}).slice(0, 120));
  (a && "provenance" in a && a.provenance === null) ? ok("provenance null confesado (unknown)") : bad("el legacy inventó procedencia", JSON.stringify(a?.provenance));
  const rw = await fetch(`${BASE}/v1/sessions/${LEGACY_SID}/artifacts/aaaa11112222`, {
    method: "PUT", headers: AUTH, body: JSON.stringify({ content: "upgraded", produced_by: "manual" }) });
  if (rw.ok) {
    const disk = JSON.parse(readFileSync(join(DATA, "artifacts", `${LEGACY_SID}.json`), "utf8"));
    disk.schema_version === 2 ? ok("una escritura real subió el archivo a v2") : bad("no subió a v2 al escribir");
  } else bad(`el edit del legacy falló (HTTP ${rw.status})`);
}

// ── 8 · CERRAR TODO Y REABRIR (la mitad de la vara que la clave vieja hacía imposible) ─
console.log("\n8 · cerrar app y navegador · reabrir · la Biblioteca recuerda");
await ctx.close();
if (SIDECAR) {
  matarSidecar();
  await dormir(1500);
  const rev = await bootSidecar();
  rev ? ok("el sidecar re-levantó con el MISMO datadir") : bad("el sidecar no re-levantó");
}
ctx = await webkit.launchPersistentContext(PROFILE, { viewport: { width: 1360, height: 900 } });
try {
  page = await abrirSala(ctx);
  const SID2 = await page.evaluate((k) => localStorage.getItem(k), sidKey);
  SID && SID2 === SID ? ok("la clave de sesión SOBREVIVIÓ el cierre (localStorage, §6.2)") : bad("la clave no sobrevivió (o nunca existió)", `${SID} → ${SID2}`);
  let lista = [];
  for (let i = 0; i < 10 && !lista.length; i++) {
    await dormir(1500);
    const r = await fetch(`${BASE}/v1/sessions/${encodeURIComponent(SID2)}/artifacts`, { headers: AUTH });
    if (r.ok) lista = (await r.json())?.artifacts || [];
  }
  lista.length ? ok(`la sesión restaurada lista ${lista.length} artefacto(s) con ${lista[0].n_versions} versión(es)`) : bad("la sesión restaurada está vacía");
  const enDom = await page.evaluate((t) => document.body.innerText.includes(t), (arts[0] || {}).title || "@@@");
  enDom ? ok("la obra aparece en la superficie reabierta") : bad("la obra NO aparece en la superficie reabierta");
  await page.screenshot({ path: join(SHOTS, "2-reabierta.png"), fullPage: false }).catch(() => {});
} catch (e) { bad("no reabrió", String(e).slice(0, 160)); }
await ctx.close();

// ── 9 · check_provenance sobre el events.jsonl REAL del espacio ───────────────────────
console.log("\n9 · check_provenance (manual — cablearlo al runner es 2.5)");
{
  const space = art?.provenance?.space_id;
  const ev = space ? join(DATA, "espacios", space, "events.jsonl") : null;
  if (ev && existsSync(ev)) {
    const r = spawnSync("python3", [join(REPO, "qa/anti-fake-suite/check_provenance.py"), ev], { encoding: "utf8" });
    const salida = (r.stdout || "") + (r.stderr || "");
    /AUTÉNTICO/.test(salida) && r.status === 0 ? ok("VEREDICTO GLOBAL: AUTÉNTICO sobre el espacio real") : bad("check_provenance no dio AUTÉNTICO", salida.slice(-300));
    const mTc = salida.match(/tool_calls=(\d+)/);
    mTc && Number(mTc[1]) === Number(art?.provenance?.tool_calls)
      ? ok(`cruce: tool_calls del auditor (${mTc[1]}) == del artefacto (${art?.provenance?.tool_calls})`)
      : bad("el conteo del auditor no cruza con el artefacto", `${mTc && mTc[1]} vs ${art?.provenance?.tool_calls}`);
  } else bad("no hay events.jsonl del espacio para auditar", String(ev));
}

errores.length ? bad(`${errores.length} pageerror`, errores.slice(0, 2).join(" | ")) : ok("cero pageerror en las dos pasadas");

teardown();
console.log("\n" + "═".repeat(64));
if (fails.length) {
  console.log(`VARA FASE 2: ${fails.length} ROJAS`);
  for (const f of fails) console.log("  · " + f);
  process.exit(1);
}
console.log("VARA FASE 2: todo verde");
