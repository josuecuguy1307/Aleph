/* verify_fractal_zoom.mjs — D2 (zoom semántico + breadcrumb) · headless, SIN backend (puerto ≠ :8091).
 *
 * Sirve product/app/design ESTÁTICO en :8103, stubea /v1/** (sin DB), maneja el Cuarto por window.__cuarto.
 * Prueba D2: (REG) escena sin recintos = plano + atRoot; baldosa-agente ≠ cajón; ENTRAR 1 nivel (child-world
 * montado, padre oculto, cam movida, breadcrumb); SALIR → relationModel() padre BYTE-IDÉNTICO al snapshot;
 * N niveles (breadcrumb sigue la profundidad + salto de nivel deja el padre-de-ese-nivel intacto); TOPE de
 * profundidad → {ok:false} sin crash; el fitAll congelado dentro de un hijo. Falla si hay error JS de página.
 * Run:  node verify_fractal_zoom.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");             // product/app/design (para que ../theme.js resuelva)
const PORT = 8103;                                // ≠ :8091 (D2/D3/D5 sin backend)
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

// ── static server (stdlib python) ────────────────────────────────────────────
const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
// stub el backend ausente → cero ruido 404 (D2 no necesita backend; el fetch-por-agent_ref es de D4)
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

// espera a que el push-in/pull-back (camTween) se ASIENTE (dos lecturas de scale iguales) — NO waitForTimeout.
const settleCam = () => page.evaluate(() => { window.__cs = null; })
  .then(() => page.waitForFunction(() => {
    const s = Math.round(window.__cuarto.cam.state.scale * 1e4);
    if (window.__cs === s) return true; window.__cs = s; return false;
  }, null, { polling: 80, timeout: 6000 }));

const crumbCount = () => page.evaluate(() => window.__fractalBar.querySelectorAll("button.crumb").length);

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  // ╔══ REGRESIÓN (mandatory) — escena SIN recintos = modelo plano + atRoot ═══════════════════════╗
  const reg = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeTile({ id: "t1", key: "t1", label: "T1", category: "process" }, 4, 3);
    c.placeTile({ id: "ctx1", key: "ctx1", label: "Ctx", atom: "contexto" }, 5, 3);
    const m = c.relationModel(), fr = c.fractal();
    return { anyParentId: m.pieces.some((p) => "parentId" in p), atRoot: fr.atRoot, depth: fr.depth };
  });
  ok(!reg.anyParentId && reg.atRoot === true && reg.depth === 0,
    "REG · escena sin recintos → modelo plano (0 parentId) + fractal().atRoot & depth===0", JSON.stringify(reg));

  // ╔══ SEED · escena PADRE = un recinto-AGENTE (agent_ref) + un CAJÓN — snapshot byte-idéntico ════╗
  await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeRecinto({ id: "agtA", nucleo: true, agent_ref: "child-a", gridX: 2, gridY: 2, w: 2, h: 2 },
      [{ id: "a1", key: "a1", label: "A1", category: "read" }]);
    c.placeRecinto({ id: "cajB", gridX: 6, gridY: 5, w: 2, h: 2 },
      [{ id: "k1", key: "k1", label: "K1", category: "process" }, { id: "k2", key: "k2", label: "K2", category: "write" }]);
  });
  await page.waitForTimeout(160);                     // deja correr un tick → drawRecintos llena _draw REAL
  const PARENT_SNAP = await page.evaluate(() => JSON.stringify(window.__cuarto.relationModel()));

  // ╔══ F2 · ESTRUCTURA — agente=baldosa+muñeco; el cajón conserva su caja ════════════════════════╗
  const portal = await page.evaluate(() => {
    const d = window.__cuarto.recintoDraw();
    return { agt: d.find((x) => x.id === "agtA"), caj: d.find((x) => x.id === "cajB") };
  });
  ok(portal.agt && portal.agt.structure === "baldosa" && portal.agt.agentDoll === true,
    "F2 · el recinto-AGENTE es baldosa con muñeco", JSON.stringify(portal.agt));
  ok(portal.caj && portal.caj.structure !== "baldosa",
    "F2 · el CAJÓN conserva una estructura distinta", JSON.stringify(portal.caj));

  // ╔══ ENTER · 1 nivel con receta hija INYECTADA (child-world montado, padre oculto, cam movida) ══╗
  const camBefore = await page.evaluate(() => window.__cuarto.cam.state);
  const en1 = await page.evaluate(async () => {
    const CHILD = window.Projection.canvasToRecipe({
      nucleo: { name: "child-a", gridX: 3, gridY: 1 },
      blocks: [
        { id: "c-py", atom: "tool", card_id: "python", ref: "python", label: "Py", tools: [], zone: "mesa", gridX: 4, gridY: 3 },
        { id: "c-rd", atom: "tool", card_id: "reader", ref: "reader", label: "Rd", tools: [], zone: "fuentes", gridX: 5, gridY: 3 },
      ], links: [],
    });
    const res = await window.__cuarto.enter("agtA", { recipe: CHILD });
    const fr = window.__cuarto.fractal();
    return { res, depth: fr.depth, stackLen: fr.stack.length, childCount: window.__cuarto.placedTiles().length, worldVisible: window.__cuarto.worldVisible() };
  });
  await settleCam();
  const camAfter = await page.evaluate(() => window.__cuarto.cam.state);
  const crumbs1 = await crumbCount();
  ok(en1.res && en1.res.ok === true && en1.depth === 1 && en1.stackLen === 1, "ENTER · profundidad 1, stack.length 1 (fractal())", JSON.stringify({ res: en1.res, depth: en1.depth }));
  ok(en1.childCount === 2, "ENTER · las piezas del HIJO están montadas (placedTiles()===2, la receta inyectada)", JSON.stringify({ childCount: en1.childCount }));
  ok(en1.worldVisible === false, "ENTER · el world del PADRE queda oculto (worldVisible()===false), no destruido");
  ok(crumbs1 === 2, "ENTER · breadcrumb con 2 migas (Cuarto raíz › agente A)", JSON.stringify({ crumbs: crumbs1 }));
  const camChanged = Math.abs(camAfter.scale - camBefore.scale) > 0.05 || Math.hypot(camAfter.x - camBefore.x, camAfter.y - camBefore.y) > 5;
  ok(camChanged, "ENTER · la CÁMARA se movió (push-in: scale/pos ≠ cam guardada del padre)", JSON.stringify({ before: { s: +camBefore.scale.toFixed(3) }, after: { s: +camAfter.scale.toFixed(3) } }));

  // fitAll CONGELADO dentro del hijo (gotcha R2): cam.fit() NO debe snapear la cámara de vuelta
  const guard = await page.evaluate(() => {
    const a = window.__cuarto.cam.state; window.__cuarto.cam.fit(); const b = window.__cuarto.cam.state;
    return { moved: Math.abs(a.scale - b.scale) > 1e-6 || Math.abs(a.x - b.x) > 1e-6 || Math.abs(a.y - b.y) > 1e-6 };
  });
  ok(!guard.moved, "GUARD · dentro del hijo fitAll es NO-OP (cam.fit() no snapea la cámara — R2/riesgo d)");

  // ╔══ EXIT · relationModel() del padre BYTE-IDÉNTICO al snapshot (invariante anti-corrupción §7.2) ═╗
  const ex1 = await page.evaluate(() => {
    const res = window.__cuarto.exit();
    return { res, atRoot: window.__cuarto.fractal().atRoot, snap: JSON.stringify(window.__cuarto.relationModel()), worldVisible: window.__cuarto.worldVisible() };
  });
  ok(ex1.res && ex1.res.ok === true && ex1.atRoot === true, "EXIT · vuelve a la raíz (fractal().atRoot===true)");
  ok(ex1.worldVisible === true, "EXIT · el world del padre se re-muestra (worldVisible()===true)");
  ok(ex1.snap === PARENT_SNAP, "EXIT · relationModel() del padre == snapshot BYTE-IDÉNTICO (padre INTACTO)", ex1.snap === PARENT_SNAP ? "" : "\n  got:  " + ex1.snap + "\n  want: " + PARENT_SNAP);
  ok((await crumbCount()) === 0, "EXIT · breadcrumb oculto en la raíz (0 migas)");

  // ╔══ FIX A (§9·A) · FUGA ESPACIAL — editar DENTRO de un hijo NO debe crecer la grilla/zonas/piso del PADRE ═╗
  // El snapshot de enter/exit serializaba placedById/occupancy/model/cam PERO NO los singletons ESPACIALES
  // compartidos (N, grid.cols/rows, scene.zones, floorNodes). Un edit-adentro que crecía el mundo
  // (growToN/growZone/placeTile-sin-celda) mutaba esos singletons → al salir el padre quedaba con grid
  // crecido + floor huérfano + zones drifted, y relationModel() era CIEGO (no serializa gx/gy ni grid). El
  // fix bloquea el crecimiento mientras fractalStack>0. Este assert usa el snapshot ESPACIAL (no relationModel)
  // y FALLA en el código pre-fix (revert-test) / PASA con el fix → prueba que NO es tautológico.
  const SPATIAL_BEFORE = await page.evaluate(() => JSON.stringify(window.__cuarto.spatialSnapshot()));
  const spatialEdit = await page.evaluate(async () => {
    const c = window.__cuarto;
    const CHILD = window.Projection.canvasToRecipe({
      nucleo: { name: "child-a", gridX: 3, gridY: 1 },
      blocks: [{ id: "sc-py", atom: "tool", card_id: "python", ref: "python", label: "Py", tools: [], zone: "mesa", gridX: 4, gridY: 3 }],
      links: [],
    });
    const en = await c.enter("agtA", { recipe: CHILD });
    // edits que EN EL CÓDIGO PRE-FIX habrían crecido la grilla/zonas/piso COMPARTIDOS del padre:
    const gz = c.growZone("mesa", "down", 3);          // crecer una zona (scene.zones + N)
    const gn = c.growToN(999);                         // crecer N al conteo (grilla enorme + floorNodes)
    const auto = c.placeTile({ id: "sc-auto", key: "sc-auto", label: "Auto", category: "process" });   // placeTile SIN celda → auto-grow
    // edit NORMAL que NO crece (celda libre EXISTENTE dentro del hijo) — DEBE seguir funcionando
    const onFree = c.placeTile({ id: "sc-free", key: "sc-free", label: "Free", category: "read" }, 5, 3);
    const res = c.exit();
    return { en, gz, gn, auto: !!auto, onFree: !!onFree, atRoot: c.fractal().atRoot, exitOk: res && res.ok };
  });
  const SPATIAL_AFTER = await page.evaluate(() => JSON.stringify(window.__cuarto.spatialSnapshot()));
  ok(spatialEdit.en && spatialEdit.en.ok === true, "FIX A · setup: se entró al hijo para editar adentro");
  ok(spatialEdit.gz && spatialEdit.gz.frozen === true && spatialEdit.gz.blocked === true,
    "FIX A · growZone DENTRO del hijo es no-op (frozen) — no crece las zonas del padre", JSON.stringify(spatialEdit.gz));
  ok(spatialEdit.gn && spatialEdit.gn.grew === false && spatialEdit.gn.frozen === true,
    "FIX A · growToN DENTRO del hijo es no-op (frozen) — no crece la grilla del padre", JSON.stringify(spatialEdit.gn));
  ok(spatialEdit.onFree === true, "FIX A · un edit NORMAL que NO crece (celda libre existente) SIGUE funcionando dentro del hijo");
  ok(spatialEdit.atRoot === true && spatialEdit.exitOk === true, "FIX A · se salió del hijo tras editar (de vuelta en la raíz)");
  ok(SPATIAL_AFTER === SPATIAL_BEFORE,
    "FIX A · snapshot ESPACIAL del padre BYTE-IDÉNTICO tras editar-adentro-y-salir (N/grid/zones/floorNodes/gx-gy intactos)",
    SPATIAL_AFTER === SPATIAL_BEFORE ? "" : "\n  got:  " + SPATIAL_AFTER + "\n  want: " + SPATIAL_BEFORE);
  // y el relationModel del padre también sigue byte-idéntico (el edit-adentro no tocó al padre)
  const relAfterEdit = await page.evaluate(() => JSON.stringify(window.__cuarto.relationModel()));
  ok(relAfterEdit === PARENT_SNAP, "FIX A · relationModel() del padre también byte-idéntico tras el edit-adentro-y-salir");

  // ╔══ N NIVELES · breadcrumb sigue la profundidad + salto de nivel deja al padre-de-ese-nivel intacto ═╗
  const R = {                                        // receta auto-similar: 1 tool + 1 sub-agente 'deeper' (para bajar)
    nucleo: { name: "lvl", gridX: 3, gridY: 1 },
    blocks: [
      { id: "t1", atom: "tool", card_id: "python", ref: "python", label: "T1", tools: [], zone: "mesa", gridX: 4, gridY: 3 },
      { id: "deeper", atom: "agente", nucleo: true, agent_ref: "agents/deeper", card_id: "deeper", ref: "agents/deeper", label: "Más hondo", tools: [], zone: "mesa", gridX: 6, gridY: 4 },
    ], links: [],
  };
  const nlv = await page.evaluate(async (R) => {
    const c = window.__cuarto;
    const mk = () => window.Projection.canvasToRecipe(R);
    await c.enter("agtA", { recipe: mk() });          // depth 1
    const snap1 = JSON.stringify(c.relationModel());
    const cr1 = window.__fractalBar.querySelectorAll("button.crumb").length;
    await c.enter("deeper", { recipe: mk() });         // depth 2
    const cr2 = window.__fractalBar.querySelectorAll("button.crumb").length;
    await c.enter("deeper", { recipe: mk() });         // depth 3
    const d3 = c.fractal().depth, cr3 = window.__fractalBar.querySelectorAll("button.crumb").length;
    c.exitTo(1);                                       // salto de breadcrumb → nivel 1
    return { snap1, cr1, cr2, d3, cr3, depthAfterJump: c.fractal().depth, snapBack1: JSON.stringify(c.relationModel()), crAfter: window.__fractalBar.querySelectorAll("button.crumb").length };
  }, R);
  ok(nlv.cr1 === 2 && nlv.cr2 === 3 && nlv.d3 === 3 && nlv.cr3 === 4, "N · el breadcrumb sigue la profundidad (2→3→4 migas para depth 1→2→3)", JSON.stringify({ cr1: nlv.cr1, cr2: nlv.cr2, cr3: nlv.cr3, d3: nlv.d3 }));
  ok(nlv.depthAfterJump === 1 && nlv.crAfter === 2, "N · salto de breadcrumb (exitTo(1)) → profundidad 1 + 2 migas", JSON.stringify({ depth: nlv.depthAfterJump, crumbs: nlv.crAfter }));
  ok(nlv.snapBack1 === nlv.snap1, "N · tras el salto, el modelo del NIVEL 1 vuelve byte-idéntico (padre-de-ese-nivel intacto)");
  const backToRoot = await page.evaluate(() => { window.__cuarto.exitTo(0); return { atRoot: window.__cuarto.fractal().atRoot, snap: JSON.stringify(window.__cuarto.relationModel()) }; });
  ok(backToRoot.atRoot && backToRoot.snap === PARENT_SNAP, "N · salir del todo tras la inmersión → raíz + padre byte-idéntico");

  // ╔══ TOPE de profundidad (MAX_DEPTH_UI=3) → {ok:false} SIN crash; espejo del motor ════════════════╗
  const cap = await page.evaluate(async (R) => {
    const c = window.__cuarto, mk = () => window.Projection.canvasToRecipe(R);
    await c.enter("agtA", { recipe: mk() });            // 1
    for (let i = 0; i < 6; i++) await c.enter("deeper", { recipe: mk() }); // intenta bajar 6 (topa en 3)
    const before = c.fractal().depth;
    const res = await c.enter("deeper", { recipe: mk() });   // ya en el tope → rechazo honesto
    const after = c.fractal().depth;
    c.exitTo(0);
    return { before, res, after, backSnap: JSON.stringify(c.relationModel()) };
  }, R);
  ok(cap.before === 3, "TOPE · la profundidad se CLAVA en MAX_DEPTH_UI=3", JSON.stringify({ depth: cap.before }));
  ok(cap.res && cap.res.ok === false && cap.res.reason === "depth_cap", "TOPE · entrar pasado el tope devuelve {ok:false, reason:'depth_cap'} (sin throw/crash)", JSON.stringify(cap.res));
  ok(cap.after <= 3, "TOPE · fractal().depth JAMÁS supera el tope");
  ok(cap.backSnap === PARENT_SNAP, "TOPE · salir tras topar → padre byte-idéntico (el tope no corrompió nada)");

  // ╔══ FIX B (§9·B) · RE-ENTRANCY — un enter EN VUELO bloquea a los re-entrantes (no bypassean el cap ni empujan frames fantasma) ═╗
  // El cap se chequeaba ANTES del await del fetch y el frame se empujaba DESPUÉS, sin lock → N enters en un
  // solo RTT pasaban todos y corrompían el stack. Se simula la ventana con un fetch hook LENTO (sólo existe
  // en el path de fetch real; con recipe inyectada no hay await). El segundo enter debe rebotar {busy}.
  const busy = await page.evaluate(async (R) => {
    const c = window.__cuarto;
    window.__cuartoFetchChildRecipe = () => new Promise((res) => setTimeout(() => res(window.Projection.canvasToRecipe(R)), 120));
    const p1 = c.enter("agtA");          // arranca el fetch (queda EN VUELO en el await)
    const p2 = c.enter("agtA");          // MISMO RTT, uno en vuelo → debe rebotar por el lock síncrono
    const r1 = await p1, r2 = await p2;
    const depth = c.fractal().depth;
    c.exitTo(0);
    delete window.__cuartoFetchChildRecipe;
    return { r1, r2, depth, backSnap: JSON.stringify(c.relationModel()) };
  }, R);
  ok(busy.r2 && busy.r2.ok === false && busy.r2.reason === "busy",
    "FIX B · un 2º enter() con uno EN VUELO devuelve {ok:false,reason:'busy'} (lock síncrono, sin frame fantasma)",
    JSON.stringify({ r1: busy.r1 && busy.r1.ok, r2: busy.r2 }));
  ok(busy.r1 && busy.r1.ok === true && busy.depth === 1,
    "FIX B · el PRIMER enter completa normal (depth 1) — el lock aborta al re-entrante, no al legítimo",
    JSON.stringify({ r1ok: busy.r1 && busy.r1.ok, depth: busy.depth }));
  ok(busy.backSnap === PARENT_SNAP, "FIX B · tras el enter en vuelo + exit → padre byte-idéntico (el re-entrante no dejó basura)");

  // ── 0 errores JS/render de página ──
  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e);
  fails.push("harness: " + e.message);
} finally {
  await browser.close();
  server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — D2 (zoom semántico + breadcrumb) verificada"));
process.exit(fails.length ? 1 : 0);
