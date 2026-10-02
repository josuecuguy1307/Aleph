/* verify_shared_membership.mjs — STEP 2·B2 · la línea teal REAL + el panel del cilindro con AUTOR.
 *
 * Hoy la línea teal era 100% decorativa (un blanket a TODO sub-agente) y recipe.memory era
 * todo-o-nada. Este test prueba que la MEMBRESÍA es real y que el panel de la memoria compartida
 * rinde el AUTOR de cada nota, corriendo las funciones REALES del worktree (SIN backend, todo
 * stubbeado con page.route):
 *
 *   A · MEMBRESÍA — projection.canvasToRecipe emite recipe.memory.members = exactamente las
 *       identidades CONECTADAS ('nucleo' + slug de cada agente conectado). Desconectar un agente
 *       (sharesMemory:false) lo SACA de members Y borra su edge "comparte" del modelo (la línea
 *       teal desaparece SÓLO para él). Un Cuarto SIN pieza-memoria queda byte-idéntico (sin memory).
 *   B · AUTOR — wireSharedMemory pinta cada fila con un badge de AUTOR (author_label) dado un GET
 *       stubbeado {memories:[{content, author_label:'Agente A', source:'agent'}, …]}.
 *   C · GATING HONESTO — un Cuarto SIN guardar (sin savedPuppetId) muestra la nota honesta
 *       "Guardá el Cuarto…" y NO dispara un fetch roto contra /v1/compositions.
 *
 * Run:  node verify_shared_membership.mjs        (headless, SIN backend)
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");                       // cuarto → design
const PORT = Number(process.env.FRONT_PORT || 8123);       // ≠ otros verify
const PAGE_URL = `http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html`;
const UUID = "c4b5de4d-0000-4000-8000-000000000b2b";       // composition_id sintético (uuid válido)

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`); if (!cond) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// payload del cilindro: dos notas, DISTINTO autor (un agente + Vos) — el corazón del badge de AUTOR
const SHARED_GET = {
  composition_id: UUID, total: 2,
  usage: { entries: 2, bytes: 42 }, caps: { max_entries: 50, max_bytes: 8000 },
  memories: [
    { id: "m1", composition_id: UUID, content: "el cliente prefiere gráficos de línea", author_label: "Agente A", author_agent_id: "alpha", source: "agent", pinned: true },
    { id: "m2", composition_id: UUID, content: "cerrar el reporte los lunes 9am", author_label: "Vos", author_agent_id: UUID, source: "user", pinned: true },
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

// catch-all primero; la ruta ESPECÍFICA del cilindro se registra DESPUÉS (gana en Playwright).
const compGets = [];
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
await page.route("**/v1/compositions/*/memories", (route) => {
  if (route.request().method() === "GET") { compGets.push(route.request().url()); return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(SHARED_GET) }); }
  return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
});

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection && window.__wireSharedMemory && window.__openInspector && window.__recipeMod, null, { timeout: 15000 });

  // ── A) MEMBRESÍA — projection + modelo ──────────────────────────────────────────────────────
  // A.1 projection: 1 memoria + 2 agentes; agtB DESCONECTADO (sharesMemory:false)
  const proj = await page.evaluate(() => {
    const blocks = [
      { id: "mem", atom: "memoria" },
      { id: "agtA", atom: "agente", nucleo: true, agent_ref: "product/agents/alpha.config.json" },   // slug alpha · conectado
      { id: "agtB", atom: "agente", nucleo: true, agent_ref: "product/agents/beta.json", sharesMemory: false }, // slug beta · DESCONECTADO
    ];
    const r = window.Projection.canvasToRecipe({ nucleo: { name: "Cuarto X" }, blocks, links: [] });
    return r.memory || null;
  });
  ok(proj && proj.shared === true, "A.1 · con pieza-memoria, recipe.memory.shared = true");
  ok(proj && Array.isArray(proj.members) && proj.members.includes("nucleo"), "A.1 · members incluye 'nucleo' (el Núcleo comparte por default)", JSON.stringify(proj && proj.members));
  ok(proj && proj.members.includes("alpha"), "A.1 · members incluye el slug del agente CONECTADO (alpha)", JSON.stringify(proj && proj.members));
  ok(proj && !proj.members.includes("beta"), "A.1 · members NO incluye el slug del agente DESCONECTADO (beta) — la membresía es real, no blanket", JSON.stringify(proj && proj.members));

  // A.2 byte-identidad: un Cuarto SIN pieza-memoria NO emite recipe.memory
  const noMem = await page.evaluate(() => {
    const blocks = [{ id: "agtA", atom: "agente", nucleo: true, agent_ref: "product/agents/alpha.config.json" }];
    const r = window.Projection.canvasToRecipe({ nucleo: { name: "Cuarto sin cilindro" }, blocks, links: [] });
    return { hasMemory: "memory" in r, memory: r.memory };
  });
  ok(!noMem.hasMemory, "A.2 · un Cuarto SIN pieza-memoria queda byte-idéntico (recipe.memory ausente)", JSON.stringify(noMem.memory));

  // A.3 MODELO: coloca memoria + 2 recintos-agente; ambos conectados → 2 edges "comparte"
  const edgesBefore = await page.evaluate(() => {
    window.__cuarto.placeTile({ id: "mem", atom: "memoria", label: "Memoria" });
    window.__cuarto.placeRecinto({ id: "agtA", nucleo: true, agent_ref: "product/agents/alpha.config.json", label: "Alpha" });
    window.__cuarto.placeRecinto({ id: "agtB", nucleo: true, agent_ref: "product/agents/beta.json", label: "Beta" });
    return window.__cuarto.relations().filter((r) => r.kind === "comparte").map((r) => r.to).sort();
  });
  ok(edgesBefore.length === 2 && edgesBefore.includes("agtA") && edgesBefore.includes("agtB"),
     "A.3 · default: la línea teal (comparte) va a AMBOS agentes (compat con el look de hoy)", JSON.stringify(edgesBefore));

  // A.4 DESCONECTAR agtB → su edge "comparte" desaparece del modelo (sólo el suyo)
  const edgesAfter = await page.evaluate(() => {
    window.__cuarto.setSharesMemory("agtB", false);
    return {
      comparte: window.__cuarto.relations().filter((r) => r.kind === "comparte").map((r) => r.to).sort(),
      sharesA: window.__cuarto.sharesMemory("agtA"), sharesB: window.__cuarto.sharesMemory("agtB"),
    };
  });
  ok(edgesAfter.comparte.length === 1 && edgesAfter.comparte[0] === "agtA",
     "A.4 · desconectar agtB → SÓLO su edge teal desaparece; el de agtA sigue", JSON.stringify(edgesAfter.comparte));
  ok(edgesAfter.sharesA === true && edgesAfter.sharesB === false, "A.4 · api.sharesMemory refleja la membresía viva (A conectado · B no)");

  // A.5 el render→projection se cierra: tilesToRecipe de la escena viva refleja la desconexión
  const wired = await page.evaluate(() => {
    const r = window.__recipeMod.tilesToRecipe(window.__cuarto.placedTiles(), window.__cuarto.nucleoData());
    return r.memory ? r.memory.members : null;
  });
  ok(wired && wired.includes("nucleo") && wired.includes("alpha") && !wired.includes("beta"),
     "A.5 · tilesToRecipe(escena viva) → members sin 'beta' (la desconexión llega a la receta REAL del RUN)", JSON.stringify(wired));

  // limpiar la escena antes de los tests de DOM
  await page.evaluate(() => window.__cuarto.placedTiles().forEach((t) => window.__cuarto.removeTile(t.id)));

  // ── C) GATING HONESTO — Cuarto SIN guardar (hago C antes de B: setear el guardado es lo último) ─
  const gateBefore = compGets.length;
  const gating = await page.evaluate(() => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ session_token: "tok-test" }));   // logueado…
    try { delete window.__savedPuppet; } catch (e) { window.__savedPuppet = null; }          // …pero SIN guardar
    return window.__savedPuppetId ? window.__savedPuppetId() : "hook-missing";
  });
  ok(gating === null, "C · sin ?puppet ni __savedPuppet, savedPuppetId() = null (Cuarto sin guardar)", `savedPuppetId=${gating}`);
  await page.evaluate(() => window.__openInspector({ atom: "memoria", id: "mem", label: "Memoria" }));
  await page.waitForFunction(() => { const b = document.querySelector("#d-opts [data-sharedbody]"); return b && !/cargando/.test(b.textContent); }, null, { timeout: 6000 }).catch(() => {});
  const gateNote = await page.evaluate(() => (document.querySelector("#d-opts [data-sharedbody]") || {}).textContent || "");
  ok(/Guardá el Cuarto/i.test(gateNote), "C · el panel muestra la NOTA honesta 'Guardá el Cuarto…' (no un panel roto)", `nota="${gateNote.trim().slice(0, 80)}"`);
  ok(compGets.length === gateBefore, "C · sin guardar NO se dispara ningún GET a /v1/compositions (cero fetch roto)", `gets=${compGets.length - gateBefore}`);

  // ── B) AUTOR — panel del cilindro con badge de author_label ──────────────────────────────────
  await page.evaluate((uuid) => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ session_token: "tok-test" }));
    window.__savedPuppet = { id: uuid };   // Cuarto GUARDADO → savedPuppetId() = uuid
  }, UUID);
  await page.evaluate(() => window.__openInspector({ atom: "memoria", id: "mem", label: "Memoria" }));
  await page.waitForFunction(() => document.querySelectorAll("#d-opts [data-sharedbody] .memrow").length >= 2, null, { timeout: 8000 }).catch(() => {});
  const rows = await page.evaluate(() => Array.from(document.querySelectorAll("#d-opts [data-sharedbody] .memrow")).map((rw) => ({
    author: (rw.querySelector(".memauthor") || {}).textContent || "",
    src: (rw.querySelector(".memsrc") || {}).className || "",
    srcText: (rw.querySelector(".memsrc") || {}).textContent || "",
    txt: (rw.querySelector(".memtxt") || {}).textContent || "",
  })));
  ok(rows.length === 2, "B · el panel rinde una fila por nota compartida (2)", `rows=${rows.length}`);
  ok(rows.some((r) => r.author === "Agente A"), "B · una fila lleva el badge de AUTOR 'Agente A' (quién escribió la nota del agente)", JSON.stringify(rows.map((r) => r.author)));
  ok(rows.some((r) => r.author === "Vos"), "B · la nota del usuario lleva el badge de AUTOR 'Vos'", JSON.stringify(rows.map((r) => r.author)));
  ok(rows.some((r) => /agent/.test(r.src)) && rows.some((r) => /user/.test(r.src)),
     "B · el badge de SOURCE distingue agente vs Vos (memsrc.agent / memsrc.user)", JSON.stringify(rows.map((r) => r.src)));
  ok(compGets.length > gateBefore, "B · con Cuarto GUARDADO el panel SÍ hace GET /v1/compositions/{cid}/memories", `gets=${compGets.length}`);

  ok(cerr.length === 0, "0 errores de consola", cerr.slice(0, 2).join(" | "));
} catch (e) {
  ok(false, "excepción en el probe", String(e));
} finally {
  await browser.close();
  try { server.kill("SIGKILL"); } catch {}
}

console.log("");
if (fails.length) { console.error(`✗ B2 SHARED-MEMBERSHIP ROJO — ${fails.length} fallas`); process.exit(1); }
console.log("✓ B2 SHARED-MEMBERSHIP VERDE — la línea teal = membresía real (desconectar un agente lo saca de members Y del modelo); el panel del cilindro rinde el AUTOR de cada nota; sin guardar, nota honesta sin fetch roto");
