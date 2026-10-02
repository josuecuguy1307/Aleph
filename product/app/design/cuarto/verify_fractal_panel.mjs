/* verify_fractal_panel.mjs — D5 (panel del recinto · identidad + acciones) · headless, SIN backend real.
 *
 * Sirve product/app/design ESTÁTICO en :8106 y stubea /v1 con una IDENTIDAD real: GET /v1/users/{id}/puppets
 * devuelve la config completa del hijo (canvas.blocks → piezas count), GET /v1/puppets/{uuid}/memories
 * devuelve una memoria (→ ownMemory). Inyecta una sesión dueña (sessionStorage) para que los fetch corran.
 * Maneja el Cuarto por window.__cuarto + el panel por window.__recintoPanel(). Prueba D5:
 *   · CLIC en recinto-AGENTE (mouse real sobre el mini-Aleph) → panel ABRE con nombre/modelo correctos,
 *     pieceCount desde la config stubeada, ownMemory desde el endpoint stubeado, bus = membresía teal.
 *   · CAJÓN → clicarlo NO abre el panel de agente (un cajón no tiene identidad de sub-agente).
 *   · ENTRAR → botón real → cuarto.enter(id) → fractal().depth===1 (reusa D2, fetch por agent_ref).
 *   · DESACOPLAR → botón real → removeTile → la pieza sale de la escena y de belt.agent_refs[]; cajón intacto.
 *   · VER → botón real → navega a ?puppet={uuid} (seam __navTo, sin navegar de verdad).
 *   · 0 errores JS de página.
 * Run:  node verify_fractal_panel.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");             // product/app/design (para que ../theme.js resuelva)
const PORT = 8106;                                // ≠ :8091/:8103/:8104/:8105 (D5 sin backend)
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

// ── identidad del hijo (agente guardado): su config real + su memoria propia ──────────────────────
const CHILD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const CHILD_REF = "catalog/agents/agent-" + CHILD + ".config.json";
const CHILD_CONFIG = {
  schema_version: "v1", meta: { name: "Analista" },
  canvas: {
    nucleos: [{ model: "equilibrado", gridX: 3, gridY: 1 }],
    blocks: [   // 2 tools + 1 sub-agente anidado → pieceCount = filter(atom!=='agente') = 2
      { id: "cp1", atom: "tool", card_id: "python", ref: "python", label: "Py", zone: "mesa", gridX: 4, gridY: 3, tools: [] },
      { id: "cp2", atom: "tool", card_id: "reader", ref: "reader", label: "Rd", zone: "fuentes", gridX: 5, gridY: 3, tools: [] },
      { id: "cAg", atom: "agente", agent_ref: "catalog/agents/agent-zzzz.config.json", nucleo: true, zone: "mesa", gridX: 6, gridY: 3 },
    ],
  },
  belt: {},
};
const PUPPETS = { puppets: [{ id: CHILD, name: "Analista", config: CHILD_CONFIG }] };
const MEMORIES = { memories: [{ id: "m1", source: "user", content: "recordá el ticker AAPL" }], usage: { entries: 1, bytes: 21 }, caps: { max_entries: 50 } };
const USERS_PUPPETS_RE = /\/v1\/users\/[^/]+\/puppets/;
const MEMORIES_RE = /\/v1\/puppets\/[^/]+\/memories/;

// ── static server (stdlib python) ────────────────────────────────────────────
const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
// sesión DUEÑA → sessUser()/authHeaders() válidos, así los fetch de identidad/memoria del panel corren
await page.addInitScript(() => { try { sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", session_token: "tok" })); } catch (e) {} });
// stub: identidad (users/*/puppets) + memoria propia (puppets/*/memories); el resto → []
await page.route("**/v1/**", (route) => {
  const url = route.request().url();
  if (MEMORIES_RE.test(url)) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MEMORIES) });
  if (USERS_PUPPETS_RE.test(url)) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(PUPPETS) });
  return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
});

const clientOf = (gx, gy) => page.evaluate(({ gx, gy }) => {
  const c = window.__cuarto, p = c.viewPoint(gx, gy), r = c.app.canvas.getBoundingClientRect();
  return { x: r.left + p.x * (r.width / c.app.screen.width), y: r.top + p.y * (r.height / c.app.screen.height) };
}, { gx, gy });

// clic REAL sobre el mini-Aleph de un recinto-agente (posición GLOBAL post-cámara, como verify_cerebro)
async function clickMiniAleph(id) {
  const pt = await page.evaluate((id) => {
    const p = window.__cuarto.artScreenOf(id); if (!p) return null;
    const cv = document.querySelector("#cuarto canvas") || document.querySelector("canvas");
    const rb = cv.getBoundingClientRect();
    return { x: rb.x + p.x, y: rb.y + p.y };
  }, id);
  if (!pt) throw new Error("no artScreenOf for " + id);
  await page.mouse.click(pt.x, pt.y);
}
const panel = () => page.evaluate(() => window.__recintoPanel());
// espera a que el enriquecimiento async (config → pieceCount) aterrice
const waitEnriched = () => page.waitForFunction(() => { const p = window.__recintoPanel(); return p.open && p.pieceCount !== null && p.ownMemory !== null; }, null, { polling: 60, timeout: 6000 });

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection && window.__recintoPanel && window.__cuarto.setRecintoPanelListener, null, { timeout: 10000 });

  // ╔══ SEED · un recinto-AGENTE (agent_ref del hijo, child_model, label) + un CAJÓN ════════════════╗
  await page.evaluate(({ CHILD_REF }) => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeRecinto({ id: "agtA", label: "Analista", nucleo: true, agent_ref: CHILD_REF, gridX: 2, gridY: 2, w: 2, h: 2 },
      [{ id: "a1", key: "a1", label: "A1", category: "read" }]);
    c.pieceData("agtA").child_model = "oss-120b";   // el cerebro elegido viaja con la pieza (node-derived)
    c.placeRecinto({ id: "cajB", gridX: 6, gridY: 5, w: 2, h: 2 },
      [{ id: "k1", key: "k1", label: "K1", category: "process" }]);
  }, { CHILD_REF });
  await page.waitForTimeout(220);   // un frame → el mini-Aleph se ancla al centro del footprint

  // ╔══ CAJÓN · clicarlo NO abre el panel de agente (no tiene identidad de sub-agente) ══════════════╗
  const caj = await clientOf(6, 5);
  await page.mouse.click(caj.x, caj.y);
  await page.waitForTimeout(120);
  const afterCajon = await panel();
  ok(afterCajon.open === false, "CAJÓN · clicar un cajón NO abre el panel del recinto (sin identidad de sub-agente)", JSON.stringify({ open: afterCajon.open }));

  // ╔══ CLIC agente → panel ABRE con identidad real (name/model node · pieceCount+ownMemory fetched) ═╗
  await clickMiniAleph("agtA");
  const opened = await page.evaluate(() => window.__recintoPanel().open);
  ok(opened === true, "CLIC · clicar el mini-Aleph del recinto-AGENTE ABRE el panel");
  await waitEnriched();
  const P = await panel();
  ok(P.id === "agtA" && P.name === "Analista", "PANEL · nombre = data.label ('Analista')", JSON.stringify({ id: P.id, name: P.name }));
  ok(P.model === "oss-120b", "PANEL · modelo = data.child_model del nodo ('oss-120b')", JSON.stringify({ model: P.model }));
  ok(P.pieceCount === 2, "PANEL · pieceCount = config.canvas.blocks.filter(atom!=='agente').length (=2, excluye el sub-agente)", JSON.stringify({ pieceCount: P.pieceCount }));
  ok(P.ownMemory === true, "PANEL · memoria propia = true (GET /v1/puppets/{uuid}/memories stubeado con 1 recuerdo)", JSON.stringify({ ownMemory: P.ownMemory }));
  ok(P.sharesMemory === true, "PANEL · bus compartido = data.sharesMemory (membresía teal B2, default true)", JSON.stringify({ sharesMemory: P.sharesMemory }));
  ok(P.uuid === CHILD, "PANEL · uuid derivado del agent_ref (mirror _slug_from_agent_ref)", JSON.stringify({ uuid: P.uuid }));
  ok(JSON.stringify(P.actions) === JSON.stringify(["entrar", "desacoplar", "ver"]), "PANEL · 3 acciones (entrar/desacoplar/ver)", JSON.stringify(P.actions));
  // el DOM refleja la identidad (no sólo el api)
  const domName = await page.evaluate(() => document.querySelector("#recintoPanel [data-rp-name]").textContent);
  ok(domName === "Analista", "PANEL · el DOM del card muestra el nombre ('Analista')", JSON.stringify({ domName }));

  // membresía del bus DRIVE-ada por el flag: desconectar → re-abrir → bus=false (reusa la teal-membership)
  await page.evaluate(() => window.__cuarto.setSharesMemory("agtA", false));
  await clickMiniAleph("agtA");
  await page.waitForFunction(() => { const p = window.__recintoPanel(); return p.open && p.sharesMemory === false; }, null, { polling: 60, timeout: 4000 }).catch(() => {});
  const busOff = await panel();
  ok(busOff.sharesMemory === false, "PANEL · desconectar del bus (setSharesMemory false) → bus compartido = false (flag real, no fabricado)", JSON.stringify({ sharesMemory: busOff.sharesMemory }));
  await page.evaluate(() => window.__cuarto.setSharesMemory("agtA", true));   // restaurar

  // ╔══ VER · botón real → navega a ?puppet={uuid} (seam __navTo, sin navegar de verdad) ════════════╗
  await page.evaluate(() => { window.__navTarget = null; window.__navTo = (u) => { window.__navTarget = u; }; });
  const urlBefore = page.url();
  await page.evaluate(() => document.querySelector("#recintoPanel [data-rp-ver]").click());
  await page.waitForTimeout(80);
  const ver = await page.evaluate(() => ({ target: window.__navTarget }));
  ok(ver.target && ver.target.indexOf("puppet=" + CHILD) !== -1, "VER · el botón navega a ?puppet={uuid} (path 'abrir' de Mis agentes)", JSON.stringify(ver));
  ok(page.url() === urlBefore, "VER · con el seam __navTo NO navega de verdad (el harness sobrevive)");

  // ╔══ ENTRAR · botón real → cuarto.enter(id) → fractal().depth===1 (reusa D2, fetch por agent_ref) ═╗
  await page.evaluate(() => document.querySelector("#recintoPanel [data-rp-enter]").click());
  await page.waitForFunction(() => window.__cuarto.fractal().depth === 1, null, { polling: 60, timeout: 6000 });
  const ent = await page.evaluate(() => ({ depth: window.__cuarto.fractal().depth, worldVisible: window.__cuarto.worldVisible(), panelOpen: window.__recintoPanel().open }));
  ok(ent.depth === 1, "ENTRAR · el botón invoca cuarto.enter(id) → fractal().depth===1 (push-in de D2)", JSON.stringify(ent));
  ok(ent.worldVisible === false, "ENTRAR · el world del padre queda oculto (bajamos al hijo)");
  ok(ent.panelOpen === false, "ENTRAR · el panel se cierra al bajar al hijo");
  await page.evaluate(() => window.__cuarto.exitTo(0));   // volver a la raíz (padre byte-idéntico, invariante D2)
  await page.waitForFunction(() => window.__cuarto.fractal().atRoot === true, null, { polling: 60, timeout: 6000 });
  await page.waitForTimeout(220);

  // ╔══ DESACOPLAR · botón real → removeTile → sale de la escena y de belt.agent_refs[]; cajón intacto ═╗
  const beforeDes = await page.evaluate(() => {
    const c = window.__cuarto;
    const recipe = window.__recipeMod.tilesToRecipe(c.placedTiles(), c.nucleoData());
    return { has: c.placedTiles().some((t) => t.id === "agtA"), agent_refs: (recipe.belt && recipe.belt.agent_refs) || [], cajon: c.placedTiles().some((t) => t.id === "cajB") };
  });
  ok(beforeDes.has && beforeDes.agent_refs.indexOf(CHILD_REF) !== -1, "DESACOPLAR · PRE: el agente está en la escena y su ref en belt.agent_refs[]", JSON.stringify(beforeDes.agent_refs));
  await clickMiniAleph("agtA");                        // re-abrir el panel
  await page.waitForFunction(() => window.__recintoPanel().open && window.__recintoPanel().id === "agtA", null, { polling: 60, timeout: 4000 });
  await page.evaluate(() => document.querySelector("#recintoPanel [data-rp-desac]").click());
  await page.waitForTimeout(120);
  const afterDes = await page.evaluate(() => {
    const c = window.__cuarto;
    const recipe = window.__recipeMod.tilesToRecipe(c.placedTiles(), c.nucleoData());
    return { has: c.placedTiles().some((t) => t.id === "agtA"), agent_refs: (recipe.belt && recipe.belt.agent_refs) || [],
             cajon: c.placedTiles().some((t) => t.id === "cajB"), panelOpen: window.__recintoPanel().open };
  });
  ok(afterDes.has === false, "DESACOPLAR · la pieza-agente sale de ESTE Cuarto (removeTile)", JSON.stringify({ has: afterDes.has }));
  ok(afterDes.agent_refs.indexOf(CHILD_REF) === -1, "DESACOPLAR · su ref YA NO se proyecta a belt.agent_refs[]", JSON.stringify(afterDes.agent_refs));
  ok(afterDes.cajon === true, "DESACOPLAR · la escena por lo demás intacta (el cajón sigue)", JSON.stringify({ cajon: afterDes.cajon }));
  ok(afterDes.panelOpen === false, "DESACOPLAR · el panel se cierra tras desacoplar (la pieza ya no existe)");

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

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — D5 (panel del recinto · identidad + acciones) verificada"));
process.exit(fails.length ? 1 : 0);
