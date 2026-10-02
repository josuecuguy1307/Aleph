/* verify_guardar.mjs — GATE de "Guardar mis agentes" (round-trip REAL con posición).
 *
 * Prueba lo que el feature promete: armar piezas en posiciones distintas → Guardar (POST
 * /v1/puppets) → recargar el Cuarto con ?puppet={id} → deben reaparecer LAS MISMAS PIEZAS en
 * LAS MISMAS POSICIONES. No fabrica: usa el backend REAL (:8080 + Postgres) y la UI REAL.
 *
 *   (a) la receta guardada round-trip a la DB SIN pérdida (deep-equal de blocks+belt+gates+layout
 *       entre lo que el Cuarto INTENTÓ guardar y lo que el backend PERSISTIÓ y DEVUELVE);
 *   (b) al recargar con ?puppet={id} cada pieza cae EN SU CELDA (layout reaplicado == originales).
 *
 * Requiere el stack vivo (backend :8080 + Postgres). El shim Opus NO hace falta (Guardar no corre
 * el agente). Puerto del front ≠ 8091/8096. Run:  node verify_guardar.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const WORKTREE = join(HERE, "..", "..", "..", "..");   // cuarto → design → app → product → repo
const SHOTS = join(HERE, "screenshots");
const BACKEND = process.env.BACKEND || "http://127.0.0.1:8080";
const FRONT_PORT = Number(process.env.FRONT_PORT || 8101);   // ≠ 8091/8096/8094/8099/8232
const BASE = `http://127.0.0.1:${FRONT_PORT}`;
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;

const log = (...a) => console.log(...a);
const fails = [];
const ok = (cond, label, extra) => { log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

// deep-equal por VALOR (order-independent en objetos; tolera el round-trip JSONB de Postgres)
function deepEq(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (a === null || b === null) return a === b;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((v, i) => deepEq(v, b[i]));
  }
  if (typeof a === "object") {
    const ka = Object.keys(a), kb = Object.keys(b);
    if (ka.length !== kb.length) return false;
    return ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && deepEq(a[k], b[k]));
  }
  return false;
}

async function up(url) { try { const r = await fetch(url, { signal: AbortSignal.timeout(3000) }); return r.ok; } catch { return false; } }

// ── 0) pre-flight ──
if (!(await up(`${BACKEND}/health`))) { console.error(`FALTA: backend en ${BACKEND}/health no responde. Levantá el stack.`); process.exit(3); }
log(`· backend ${BACKEND} ✓`);

// mint sesión (login legacy get-or-create, sin password) — cuenta fresca por corrida para una lista limpia
const email = `guardar-gate-${Date.now()}@aleph.test`;
const sess = await (await fetch(`${BACKEND}/v1/auth/login`, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, display_name: "Guardar Gate" }),
})).json().catch(() => null);
if (!sess || !sess.id || !sess.session_token) { console.error("FALTA: no pude mint la sesión de prueba", sess); process.exit(3); }
log(`· sesión de prueba ✓  user=${sess.id.slice(0, 8)}…`);

// ── 1) front de ESTE worktree → proxy /v1 a :8080 ──
const front = spawn("python3", ["product/app/serve.py"], {
  cwd: WORKTREE, stdio: "ignore",
  env: { ...process.env, ALEPH_FRONT_PORT: String(FRONT_PORT), ALEPH_BACKEND: BACKEND },
});
const cleanup = () => { try { front.kill("SIGTERM"); } catch {} };
process.on("exit", cleanup);
await new Promise((r) => setTimeout(r, 1000));
// confirmá que sirve EL CÓDIGO DE GUARDAR de este worktree (no otro)
const servesGuardar = await (async () => { try { const t = await (await fetch(PAGE)).text(); return /id="saveBtn"/.test(t) && /attachLayout/.test(t); } catch { return false; } })();
ok(servesGuardar, "el front sirve el código de GUARDAR de este worktree (saveBtn + attachLayout)");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1320, height: 880 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
// la sesión vive ANTES de cargar la página (igual que el login real deja sessionStorage.puppet_user)
await page.addInitScript((s) => { try { sessionStorage.setItem("puppet_user", JSON.stringify(s)); } catch (e) {} }, { id: sess.id, session_token: sess.session_token, email });
const shot = async (name) => { try { const el = await page.$("#cuarto"); if (el) await el.screenshot({ path: join(SHOTS, name) }); } catch {} };

let savedId = null, originals = null, intended = null, persisted = null;
try {
  // ── 2) abrir vacío, equipar 3 átomos REALES y MOVERLOS a celdas distintas elegidas por el usuario ──
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection && window.__atoms && window.__atoms.list && window.__atoms.list.length, null, { timeout: 20000 });

  originals = await page.evaluate(() => {
    const api = window.__cuarto;
    const cat = window.__atoms.list;
    // 3 tools keyless con belt_ref real → la receta valida (belt_refs[] resuelve, tool_filters no-vacío)
    const pick = cat.filter((a) => (a.atom === "tool" || !a.atom) && a.belt_ref && (a.auth === "keyless" || !a.auth)).slice(0, 3);
    const placed = pick.map((a) => api.placeTile({ ...a, key: a.id })).filter(Boolean);
    // celdas libres deterministas (no el auto-layout): probá candidatos y movélos a 3 distintas
    const { N } = api.gridSize();
    const taken = new Set(api.placedTiles().map((t) => t.gridX + "," + t.gridY));
    taken.add("3,1");  // núcleo
    const free = [];
    for (let gy = 1; gy < N && free.length < 3; gy++)
      for (let gx = 1; gx < N && free.length < 3; gx++)
        if (!taken.has(gx + "," + gy)) { free.push([gx, gy]); taken.add(gx + "," + gy); }
    placed.forEach((p, i) => { if (free[i]) api.moveTile(p.id, free[i][0], free[i][1]); });
    // posiciones REALES tras mover = la verdad (source of truth del render)
    return api.placedTiles().map((t) => ({ id: t.id, server: t.server || null, gridX: t.gridX, gridY: t.gridY }));
  });
  const distinct = new Set(originals.map((o) => o.gridX + "," + o.gridY)).size === originals.length;
  ok(originals.length >= 2, "equipé piezas reales", `(${originals.length} piezas)`);
  ok(distinct, "las piezas quedaron en posiciones DISTINTAS", originals.map((o) => `${o.gridX},${o.gridY}`).join(" · "));
  await shot("guardar-before.png");

  // la receta que el Cuarto VA a guardar (misma expresión que el handler), capturada para el deep-equal
  intended = await page.evaluate(() => {
    const api = window.__cuarto;
    const { tilesToRecipe, attachLayout } = window.__recipeMod;
    const placed = api.placedTiles();
    return attachLayout(tilesToRecipe(placed, api.nucleoData()), placed);
  }).catch(() => null);

  // ── 3) GUARDAR (click real en el botón) ──
  await page.click("#saveBtn");
  await page.waitForFunction(() => window.__savedPuppet && window.__savedPuppet.id, null, { timeout: 15000 });
  const saved = await page.evaluate(() => window.__savedPuppet);
  savedId = saved.id;
  ok(!!savedId, "Guardar → POST /v1/puppets devolvió un id estable", savedId ? savedId.slice(0, 8) + "…" : "");
  persisted = saved.config;

  // (a) la receta intentada == la persistida (round-trip validate+DB sin pérdida): blocks+belt+gates+layout
  if (intended && persisted) {
    ok(deepEq(intended.belt, persisted.belt), "round-trip · belt deep-equal");
    ok(deepEq(intended.gates, persisted.gates), "round-trip · gates deep-equal");
    ok(deepEq(intended.autonomy, persisted.autonomy), "round-trip · autonomy (perilla A2) deep-equal", String(persisted.autonomy));
    ok(deepEq(intended.canvas && intended.canvas.blocks, persisted.canvas && persisted.canvas.blocks), "round-trip · piezas (canvas.blocks) deep-equal");
    ok(deepEq(intended.canvas && intended.canvas.layout, persisted.canvas && persisted.canvas.layout), "round-trip · POSICIÓN (canvas.layout) deep-equal");
  } else ok(false, "capturé la receta intentada + la persistida");

  // el layout persistido cubre exactamente las piezas, con sus coords
  const layout = (persisted && persisted.canvas && persisted.canvas.layout) || [];
  const layoutMatchesOriginals = originals.every((o) => {
    const l = layout.find((x) => x.id === o.id); return l && l.gridX === o.gridX && l.gridY === o.gridY;
  }) && layout.length === originals.length;
  ok(layoutMatchesOriginals, "canvas.layout guardado == posiciones originales", `(${layout.length} entradas)`);

  // (b) GET /v1/users/{id}/puppets (el camino de La Sala) trae la config completa.
  // owner-gated → mando el Bearer de la sesión (lo mismo que hace authHeaders() en la UI).
  const fetched = await page.evaluate(async ({ uid, tok }) => {
    const r = await fetch(`/v1/users/${encodeURIComponent(uid)}/puppets`, { headers: { Authorization: "Bearer " + tok } });
    const d = await r.json();
    return (d.puppets || [])[0] || null;
  }, { uid: sess.id, tok: sess.session_token });
  ok(fetched && fetched.id === savedId, "GET /v1/users/{id}/puppets lista el agente guardado (patrón Sala)");
  ok(fetched && deepEq(fetched.config.canvas.layout, layout), "config del GET == config persistida (layout)");

  // ── 4) RECARGAR con ?puppet={id} → rehidratar piezas+posición ──
  await page.goto(`${PAGE}?puppet=${encodeURIComponent(savedId)}`, { waitUntil: "load" });
  await page.waitForFunction(() => window.__loadedPuppet && window.__loadedPuppet.count >= 0, null, { timeout: 20000 });
  await page.waitForFunction((n) => window.__cuarto && window.__cuarto.placedTiles().length >= n, originals.length, { timeout: 10000 }).catch(() => {});
  const reloaded = await page.evaluate(() => window.__cuarto.placedTiles().map((t) => ({ id: t.id, server: t.server || null, gridX: t.gridX, gridY: t.gridY })));
  await shot("guardar-after.png");

  // MISMAS PIEZAS (mismo set de ids)
  const samePieces = originals.length === reloaded.length &&
    originals.every((o) => reloaded.find((r) => r.id === o.id));
  ok(samePieces, "tras recargar: MISMAS piezas", `(${reloaded.length} vs ${originals.length})`);

  // MISMAS POSICIONES (layout reaplicado == originales; tolerancia de redondeo en celdas enteras = 0)
  const TOL = 0;
  const samePos = originals.every((o) => {
    const r = reloaded.find((x) => x.id === o.id);
    return r && Math.abs(r.gridX - o.gridX) <= TOL && Math.abs(r.gridY - o.gridY) <= TOL;
  });
  ok(samePos, "tras recargar: MISMAS posiciones (layout reaplicado == originales)",
    reloaded.map((r) => `${r.gridX},${r.gridY}`).join(" · "));

  // ── 5) compat hacia atrás: una receta SIN layout NO rompe (cae al auto-layout) ──
  const legacyOk = await page.evaluate(async () => {
    const api = window.__cuarto;
    const { recipeToTiles, applyLayout } = window.__recipeMod;
    // simulá un agente viejo: receta con canvas.blocks pero SIN canvas.layout
    const { tilesToRecipe } = window.__recipeMod;
    const recipe = tilesToRecipe(api.placedTiles(), api.nucleoData());
    if (recipe.canvas) delete recipe.canvas.layout;
    const tiles = applyLayout(recipeToTiles(recipe, window.__atoms.list), recipe.canvas && recipe.canvas.layout);
    // applyLayout sin layout devuelve los tiles tal cual (con su gridX/gridY de canvas.blocks) — no rompe
    return Array.isArray(tiles) && tiles.length > 0 && tiles.every((t) => t.gridX != null && t.gridY != null);
  }).catch(() => false);
  ok(legacyOk, "compat · receta SIN layout rehidrata igual (no rompe)");

  // ── 6) consola limpia ──
  ok(errors.length === 0, "0 errores de consola en todo el round-trip", errors.slice(0, 3).join(" | "));
} catch (e) {
  ok(false, "el round-trip corrió sin excepción", String(e && e.message || e));
} finally {
  await browser.close();
  cleanup();
}

log("");
if (fails.length) { console.error(`✗ GATE ROJO — ${fails.length} fallo(s): ${fails.join(", ")}`); process.exit(1); }
log("✓ GATE VERDE — Guardar mis agentes: round-trip receta + posición REAL");
