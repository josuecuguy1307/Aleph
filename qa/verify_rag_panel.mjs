/* verify_rag_panel.mjs — STEP 2·C1 · el PANEL de CONOCIMIENTO (RAG) de la pieza-contexto.
 *
 * Corre las funciones REALES del worktree (wireKnowledge en cuarto.pixi.html) SIN backend — todo
 * stubbeado con page.route — y prueba que el panel de la pieza Conocimiento rinde honestamente:
 *
 *   A · LISTA con BADGE de ESTADO — dado un GET {docs:[{doc_name, bytes, status}, …]}, el panel
 *       pinta UNA fila por documento con nombre + tamaño (KB) + un BADGE de índice honesto
 *       (indexado · procesando… · falta tu llave · error), leyendo data-status de cada .kstat.
 *   B · BORRAR — el botón ✕ de una fila dispara DELETE /v1/compositions/{cid}/knowledge/{doc_id}
 *       (el usuario controla su corpus; no es sólo lectura).
 *   C · GATING HONESTO — un Cuarto SIN guardar (sin savedPuppetId) muestra la nota
 *       "Guardá el Cuarto primero…" y NO dispara ningún GET roto contra /v1/compositions.
 *
 * Es el clon C1 de verify_shared_membership.mjs (B2). Requiere playwright + chromium.
 * Run:  node verify_rag_panel.mjs        (headless, SIN backend)
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..", "product", "app", "design");   // qa → design
const PORT = Number(process.env.FRONT_PORT || 8127);               // ≠ otros verify
const PAGE_URL = `http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html`;
const UUID = "c4b5de4d-0000-4000-8000-000000000c1c";              // composition_id sintético (uuid válido)

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`); if (!cond) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// payload del corpus: TRES docs con DISTINTO status → el corazón del badge de ESTADO honesto.
const KNOW_GET = {
  composition_id: UUID, total: 3,
  usage: { doc_count: 3, total_bytes: 8192 }, caps: null,   // self_hosted → caps null (sin tope)
  docs: [
    { id: "d1", doc_name: "runbook-acme.pdf", mime: "application/pdf", bytes: 4096, status: "indexed", error: null, n_chunks: 7 },
    { id: "d2", doc_name: "notas-sprint.txt", mime: "text/plain", bytes: 2048, status: "pending", error: null, n_chunks: 0 },
    { id: "d3", doc_name: "informe.docx", mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", bytes: 2048, status: "error_no_key", error: "Para indexar conecta tu propia llave de embeddings.", n_chunks: 0 },
  ],
};

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(800);

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1320, height: 900 }, deviceScaleFactor: 1 });
await context.addInitScript(() => { try { localStorage.setItem("aleph-lang", "es"); localStorage.setItem("aleph-theme", "dark"); } catch (e) {} });
const page = await context.newPage();
const cerr = [];
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) cerr.push(m.text()); });
page.on("pageerror", (e) => cerr.push(String(e)));

// catch-all primero; las rutas ESPECÍFICAS del conocimiento se registran DESPUÉS (ganan en Playwright).
const knowGets = [];
const knowDeletes = [];
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
// DELETE de un doc concreto (más específica primero)
await page.route("**/v1/compositions/*/knowledge/*", (route) => {
  if (route.request().method() === "DELETE") { knowDeletes.push(route.request().url()); return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ deleted: true }) }); }
  return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
});
// GET/POST de la colección
await page.route("**/v1/compositions/*/knowledge", (route) => {
  if (route.request().method() === "GET") { knowGets.push(route.request().url()); return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(KNOW_GET) }); }
  return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ doc_id: "dN", status: "indexed", docs: KNOW_GET.docs }) });
});

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  // __renderPieces se asigna DESPUÉS de `let curPiece` (línea ~1053) en el mismo módulo async con
  // awaits (loadAtoms/loadModels) → esperarlo garantiza que curPiece ya se inicializó (evita el TDZ
  // 'Cannot access curPiece before initialization' si openInspector se llama demasiado temprano).
  await page.waitForFunction(() => window.__cuarto && window.__wireKnowledge && window.__openInspector && window.__renderPieces, null, { timeout: 15000 });

  // ── C) GATING HONESTO — Cuarto SIN guardar (lo hago antes de A/B: setear el guardado es lo último) ─
  const gateBefore = knowGets.length;
  await page.evaluate(() => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ session_token: "tok-test" }));   // logueado…
    try { delete window.__savedPuppet; } catch (e) { window.__savedPuppet = null; }          // …pero SIN guardar
  });
  await page.evaluate(() => window.__openInspector({ atom: "contexto", id: "know", label: "Conocimiento" }));
  await page.waitForFunction(() => { const b = document.querySelector("#d-opts [data-knowbody]"); return b && !/cargando/.test(b.textContent); }, null, { timeout: 6000 }).catch(() => {});
  const gateNote = await page.evaluate(() => (document.querySelector("#d-opts [data-knowbody]") || {}).textContent || "");
  ok(/Guardá el Cuarto/i.test(gateNote), "C · sin guardar, el panel muestra la NOTA honesta 'Guardá el Cuarto…' (no un panel roto)", `nota="${gateNote.trim().slice(0, 80)}"`);
  ok(knowGets.length === gateBefore, "C · sin guardar NO se dispara ningún GET a /v1/compositions/{cid}/knowledge (cero fetch roto)", `gets=${knowGets.length - gateBefore}`);

  // ── A) LISTA + BADGE de ESTADO — Cuarto GUARDADO → savedPuppetId() = uuid ─────────────────────
  await page.evaluate((uuid) => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ session_token: "tok-test" }));
    window.__savedPuppet = { id: uuid };   // Cuarto GUARDADO → savedPuppetId() = uuid
  }, UUID);
  await page.evaluate(() => window.__openInspector({ atom: "contexto", id: "know", label: "Conocimiento" }));
  await page.waitForFunction(() => document.querySelectorAll("#d-opts [data-knowbody] .knowrow").length >= 3, null, { timeout: 8000 }).catch(() => {});
  const rows = await page.evaluate(() => Array.from(document.querySelectorAll("#d-opts [data-knowbody] .knowrow")).map((rw) => ({
    id: rw.dataset.id,
    name: (rw.querySelector(".memtxt") || {}).textContent || "",
    size: (rw.querySelector(".knowsize") || {}).textContent || "",
    status: (rw.querySelector(".kstat") || {}).dataset ? (rw.querySelector(".kstat")).dataset.status : "",
    statusText: (rw.querySelector(".kstat") || {}).textContent || "",
  })));
  ok(rows.length === 3, "A · el panel rinde una fila por documento del corpus (3)", `rows=${rows.length}`);
  ok(rows.some((r) => r.name === "runbook-acme.pdf") && rows.some((r) => r.name === "informe.docx"), "A · cada fila lleva el NOMBRE del documento", JSON.stringify(rows.map((r) => r.name)));
  ok(rows.some((r) => r.status === "indexed" && /indexado/i.test(r.statusText)), "A · BADGE de estado 'indexado' para el doc indexado", JSON.stringify(rows.map((r) => r.status)));
  ok(rows.some((r) => r.status === "pending" && /procesando/i.test(r.statusText)), "A · BADGE 'procesando…' para el doc pending");
  ok(rows.some((r) => r.status === "error_no_key" && /falta tu llave/i.test(r.statusText)), "A · BADGE honesto 'falta tu llave' para error_no_key (nunca 'error genérico')");
  ok(rows.some((r) => /KB/.test(r.size)), "A · cada fila muestra el tamaño en KB", JSON.stringify(rows.map((r) => r.size)));
  ok(knowGets.length > gateBefore, "A · con Cuarto GUARDADO el panel SÍ hace GET /v1/compositions/{cid}/knowledge", `gets=${knowGets.length}`);

  // ── B) BORRAR — el ✕ de una fila dispara DELETE del doc ───────────────────────────────────────
  const delBefore = knowDeletes.length;
  await page.evaluate(() => {
    const row = document.querySelector('#d-opts [data-knowbody] .knowrow[data-id="d1"]');
    const btn = row && row.querySelector('[data-act="del"]');
    if (btn) btn.click();
  });
  await page.waitForFunction((n) => true, null, { timeout: 1000 }).catch(() => {});
  await sleep(400);
  ok(knowDeletes.length > delBefore && /\/knowledge\/d1$/.test(knowDeletes[knowDeletes.length - 1] || ""),
     "B · el botón ✕ dispara DELETE /v1/compositions/{cid}/knowledge/d1 (el usuario controla su corpus)", `deletes=${knowDeletes.length - delBefore}`);

  ok(cerr.length === 0, "0 errores de consola", cerr.slice(0, 2).join(" | "));
} catch (e) {
  ok(false, "excepción en el probe", String(e));
} finally {
  await browser.close();
  try { server.kill("SIGKILL"); } catch {}
}

console.log("");
if (fails.length) { console.error(`✗ C1 RAG-PANEL ROJO — ${fails.length} fallas`); process.exit(1); }
console.log("✓ C1 RAG-PANEL VERDE — el panel de Conocimiento lista los documentos con badge de estado honesto (indexado/procesando/falta tu llave), permite borrar, y sin guardar muestra la nota honesta sin fetch roto");
