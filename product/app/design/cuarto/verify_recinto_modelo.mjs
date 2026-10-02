/* verify_recinto_modelo.mjs — sub-rama 1 (recinto-modelo) · headless, SIN backend (puerto ≠ :8091).
 *
 * Sirve product/app/design ESTÁTICO en un puerto libre, stubea /v1/** (sin DB), y maneja el Cuarto
 * por window.__cuarto. Prueba: (A) placeRecinto con hijos → relationModel() recinto+parentId;
 * (B) _isAgentPiece coincide datos(projection)↔render; (C) footprintFree sella (rechazo + rebote real);
 * (D) REGRESIÓN: una escena SIN recintos modela byte-idéntica. Falla si hay error JS de página.
 * Run:  node verify_recinto_modelo.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");            // product/app/design (para que ../theme.js resuelva)
const PORT = 8097;                               // ≠ :8091
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// ── static server (stdlib python) ────────────────────────────────────────────
const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
// stub el backend ausente (catálogo/modelos/validate) → cero ruido 404; window.__cuarto sólo necesita assets locales
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

const clientOf = (gx, gy) => page.evaluate(({ gx, gy }) => {
  const c = window.__cuarto, p = c.viewPoint(gx, gy), r = c.app.canvas.getBoundingClientRect();
  return { x: r.left + p.x * (r.width / c.app.screen.width), y: r.top + p.y * (r.height / c.app.screen.height) };
}, { gx, gy });

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  // ╔══ D · REGRESIÓN primero (escena SIN recintos = byte-idéntica) ═══════════════════════════════╗
  const reg = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));               // limpiar (queda sólo el Núcleo)
    c.placeTile({ id: "t1", key: "t1", label: "T1", category: "process" }, 4, 3);
    c.placeTile({ id: "ctx1", key: "ctx1", label: "Ctx", atom: "contexto" }, 5, 3);
    const m = c.relationModel();
    return {
      pieces: m.pieces,
      rels: m.relationships,
      keysT1: Object.keys(m.pieces.find((p) => p.id === "t1")).sort(),
      anyParentId: m.pieces.some((p) => "parentId" in p),
    };
  });
  ok(eq(reg.pieces, [
    { id: "nucleo", type: "nucleo", role: null },
    { id: "t1", type: "tool", role: "mesa" },
    { id: "ctx1", type: "contexto", role: null },
  ]), "D · pieces de escena sin recinto IDÉNTICAS (nucleo+tool+contexto, shape {id,type,role})");
  ok(eq(reg.rels, [
    { kind: "ida", from: "nucleo", to: "t1" },
    { kind: "eco", from: "t1", to: "nucleo" },
    { kind: "permanent", from: "ctx1", to: "nucleo" },
  ]), "D · relationships IDÉNTICAS (ida+eco de la tool, permanent del contexto)");
  ok(eq(reg.keysT1, ["id", "role", "type"]) && !reg.anyParentId, "D · pieza normal SIN parentId (modelo plano intacto)");

  // ╔══ A · placeRecinto con hijos → recinto type + hijos con parentId ════════════════════════════╗
  const A = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    const res = c.placeRecinto(
      { id: "agt-research", label: "Sub-agente research", nucleo: true, agent_ref: "agents/research", w: 2, h: 2 },
      [{ id: "t-cross", key: "crossref", label: "Crossref", category: "read" },
       { id: "t-py", key: "python", label: "Python", category: "process" }],
    );
    const m = c.relationModel();
    return {
      res,
      recinto: m.pieces.find((p) => p.id === "agt-research"),
      children: m.pieces.filter((p) => p.parentId === "agt-research").map((p) => ({ id: p.id, type: p.type, parentId: p.parentId })),
      crossRels: m.relationships.filter((r) => r.to === "t-cross" || r.from === "t-cross").map((r) => r.kind).sort(),
    };
  });
  ok(A.res && A.res.hasNucleo === true && A.res.w === 2 && A.res.h === 2 && eq(A.res.children, ["t-cross", "t-py"]),
    "A · placeRecinto devuelve {hasNucleo, w×h, children}", JSON.stringify(A.res));
  ok(A.recinto && A.recinto.type === "recinto" && A.recinto.hasNucleo === true && eq(A.recinto.children, ["t-cross", "t-py"]),
    "A · relationModel() muestra el recinto con type:'recinto' + hasNucleo + children", JSON.stringify(A.recinto));
  ok(A.children.length === 2 && A.children.every((ch) => ch.parentId === "agt-research"),
    "A · los hijos aparecen con parentId apuntando al recinto", JSON.stringify(A.children));
  ok(eq(A.crossRels, ["eco", "ida"]), "A · un hijo conserva su ida+eco al Núcleo (intactos)", JSON.stringify(A.crossRels));

  // ╔══ B · _isAgentPiece coincide datos(projection.canvasToRecipe)↔render(kind:'recinto') ════════╗
  const B = await page.evaluate(() => {
    const c = window.__cuarto;
    const samples = [
      { label: "atom=agente + nucleo", atom: "agente", nucleo: true, agent_ref: "a/1", expect: true },
      { label: "sólo flag nucleo",     atom: "tool",   nucleo: true, agent_ref: "a/2", expect: true },
      { label: "tool pura",            atom: "tool",   nucleo: false, expect: false },
      { label: "sólo atom=agente",     atom: "agente", nucleo: false, agent_ref: "a/3", expect: true },
    ];
    return samples.map((s, i) => {
      // PROJECTION (datos): ¿canvasToRecipe lo manda a belt.agent_refs[]?
      const block = { id: "s" + i, atom: s.atom, nucleo: s.nucleo, agent_ref: s.agent_ref, ref: s.agent_ref || ("r" + i), tools: [], zone: "mesa" };
      const recipe = window.Projection.canvasToRecipe({ nucleo: { name: "x" }, blocks: [block], links: [] });
      const projAgent = !!(recipe.belt.agent_refs && recipe.belt.agent_refs.length);
      // RENDER: ¿placeTile lo materializa como kind:'recinto' (type:'recinto' en el modelo)?
      c.placedTiles().forEach((t) => c.removeTile(t.id));
      const id = "b" + i;
      c.placeTile({ id, key: id, label: id, category: "process", atom: s.atom, nucleo: s.nucleo, agent_ref: s.agent_ref });
      const piece = c.relationModel().pieces.find((p) => p.id === id);
      const renderAgent = !!(piece && piece.type === "recinto");
      return { label: s.label, expect: s.expect, projAgent, renderAgent };
    });
  });
  for (const r of B) ok(r.projAgent === r.expect && r.renderAgent === r.expect,
    `B · "${r.label}" → datos=${r.projAgent} render=${r.renderAgent} (esperado ${r.expect})`);

  // ╔══ C · footprintFree SELLA: rechazo determinístico + rebote real al arrastrar ════════════════╗
  await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeTile({ id: "drifter", key: "drifter", label: "Drifter", category: "process" }, 1, 1);
    c.placeRecinto({ id: "box", nucleo: true, agent_ref: "a/box", gridX: 4, gridY: 4, w: 2, h: 2 }, []);
  });
  const sealReject = await page.evaluate(() => {
    const c = window.__cuarto, before = c.placedTiles().length;
    const r = c.placeTile({ id: "intruder", key: "intruder", label: "I", category: "process" }, 5, 5); // celda sellada
    return { rejected: r === null, countUnchanged: c.placedTiles().length === before };
  });
  ok(sealReject.rejected && sealReject.countUnchanged, "C · placeTile sobre celda sellada del footprint → RECHAZADO (no se encima)");
  // arrastre REAL al centro del recinto EXPANDIDO. NOTA: la sub-rama 3 EVOLUCIONÓ esto — soltar DENTRO
  // de un recinto expandido ya no rebota: ADOPTA la pieza como hijo (occ LOCAL, sin solaparse en el global).
  // El sello (no-solape) lo sigue probando sealReject arriba; acá verificamos la adopción.
  const from = await clientOf(1, 1), to = await clientOf(4, 4);
  await page.mouse.move(from.x, from.y); await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps: 16 }); await page.waitForTimeout(140);
  await page.mouse.up(); await page.waitForTimeout(260);
  const adopted = await page.evaluate(() => window.__cuarto.parentOf("drifter"));
  ok(adopted === "box", "C · arrastrar al footprint de un recinto expandido → ADOPTADO como hijo (sub-rama 3; sello no-solape intacto)");

  // ── 0 errores JS/render ──
  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e);
  fails.push("harness: " + e.message);
} finally {
  await browser.close();
  server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — sub-rama 1 (recinto-modelo) verificada"));
process.exit(fails.length ? 1 : 0);
