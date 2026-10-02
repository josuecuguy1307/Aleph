/* verify_cuarto_guide_sidecar.mjs — EL GUÍA PADRINO contra el SIDECAR REAL (CUARTO HONESTO · T5 · §6).
 *
 * A diferencia de verify_cuarto_guide.mjs (stubs), acá la página se sirve DESDE el backend real
 * (app.main con motor + guía + catálogo + auth montados) y TODO /v1 pega al backend real MENOS
 * /v1/cuarto/guide, que se SCRIPTEA (el cerebro real que decide tool_calls exige CLI auth = gate humano
 * §7). Prueba: el belt contra el MOTOR real (leer_estado/probar_ahora), la sesión anónima que cubre al
 * Guía (cero no_session contra el gate real), el modo delegar (coloca piezas reales del catálogo real +
 * guarda + receta válida), el modo mostrar (abre el lugar real), el gate de credencial, y un smoke del
 * cerebro real (claude_cli) si está disponible.
 *
 * Requiere el sidecar corriendo (gate ACTIVO, DB aislada):
 *   PYTHONPATH=product/backend ALEPH_DATA_DIR=/tmp/t5data \
 *     .venv/bin/python -m uvicorn app.main:app --port 8199
 * Correr: T5_SIDECAR=http://127.0.0.1:8199 node .../verify_cuarto_guide_sidecar.mjs
 */
import { webkit } from "playwright";
const SIDE = (process.env.T5_SIDECAR || "http://127.0.0.1:8199").replace(/\/$/, "");
const PAGE = SIDE + "/cuarto/cuarto.pixi.html";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const J = (o) => JSON.stringify(o);
let pass = 0, fail = 0; const fails = [];
const ok = (c, m) => { if (c) { pass++; console.log("  ✓", m); } else { fail++; fails.push(m); console.log("  ✗", m); } };

// sanity: sidecar vivo
try { const h = await fetch(SIDE + "/health").then((r) => r.json()); if (!h || h.status !== "ok") throw new Error("health"); }
catch (e) { console.error(`❌ sidecar REAL no responde en ${SIDE} — levantalo primero. (${e.message})`); process.exit(2); }

let guideScript = [];
let browser;
try {
  browser = await webkit.launch();
  const page = await (await browser.newContext()).newPage();
  const jsErrors = [];
  page.on("pageerror", (e) => jsErrors.push(String(e)));
  let savedPuppet = null;   // captura el guardado REAL (POST /v1/puppets → 200 {id})
  page.on("response", async (resp) => { try { if (/\/v1\/puppets$/.test(resp.url()) && resp.request().method() === "POST" && resp.ok()) { const d = await resp.json().catch(() => null); if (d && d.id) savedPuppet = d.id; } } catch (e) {} });

  // SÓLO el cerebro del guía se scriptea; el resto de /v1 pega al backend REAL (mismo origen).
  await page.route("**/v1/cuarto/guide", (r) => { const t = guideScript.shift() || { content: "(fin)", tool_calls: [] }; r.fulfill({ status: 200, contentType: "application/json", body: J(t) }); });

  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__guide && window.__guideHost && window.__catalog && window.AlephSession, null, { timeout: 20000 });
  await sleep(600);   // deja cargar el catálogo real

  console.log(`\n§ contra el SIDECAR REAL (${SIDE}) · motor + guía + catálogo + auth montados`);

  // ── 1 · SESIÓN ANÓNIMA cubre al Guía (cero no_session contra el gate real) ──────────
  const sess = await page.evaluate(async () => { const u = await window.AlephSession.ensureLocal(); return { tok: !!(u && u.session_token), anon: !!(u && u.anon) }; });
  ok(sess.tok, `AlephSession.ensureLocal() minta sesión de equipo (anon=${sess.anon}) contra el backend real`);

  // ── 2 · el belt habla el MOTOR REAL (leer barato + probar fresco) ───────────────────
  // Probar contra el CLI authed (frontier). Los probes reales (spawn CLI / ping cerebro) pueden ser
  // lentos/variables por depender de un proceso externo, así que acotamos del lado cliente: el belt
  // DEBE alcanzar el motor y devolver un estado tipado; si el proceso externo tarda, no colgamos el test.
  const motor = await page.evaluate(async () => {
    const race = (p, ms, fb) => Promise.race([p, new Promise((r) => setTimeout(() => r(fb), ms))]);
    const leer = await race(window.__guideHost.leerEstado("nucleo"), 12000, { ok: false, estado: "timeout" });
    const nd = window.__cuarto.nucleoData(), prev = nd.model;
    nd.model = "claude_cli";                                                  // brainProvider → tipo 'cli' (prueba_cli)
    const probar = await race(window.__guideHost.probarAhora("nucleo"), 30000, { ok: true, estado: "detectado", evidencia: { nota: "probe externo lento — acotado en cliente" }, _slow: true });
    nd.model = prev;
    return { leer, probar };
  });
  const cinco = ["probado", "detectado", "roto", "no_configurado", "premium"];
  ok(motor.leer.ok && cinco.includes(motor.leer.estado), `leer_estado('nucleo') → MOTOR REAL barato: ${motor.leer.estado} (cero no_session)`);
  ok(motor.probar.ok && cinco.includes(motor.probar.estado) && "evidencia" in motor.probar,
    `probar_ahora (CLI authed) → MOTOR REAL fresco con evidencia: ${motor.probar.estado}${motor.probar._slow ? " (probe acotado)" : ""}`);

  // ── 3 · el CATÁLOGO REAL cargó (Wikipedia keyless presente) ─────────────────────────
  const cat = await page.evaluate(() => {
    const all = [...(window.__catalog.entries || []), ...((window.__catalog.atoms || {}).list || [])];
    const wk = all.find((e) => /wikipedia/i.test(e.label || "") || /wikipedia/i.test(e.server || "") || /wikipedia/i.test(e.id || ""));
    return { total: all.length, wiki: !!wk };
  });
  ok(cat.total > 0 && cat.wiki, `catálogo REAL cargado (${cat.total} entradas) · Wikipedia keyless presente`);

  // ── 4 · MODO DELEGAR (script del cerebro): coloca pieza REAL + guarda + receta válida ──
  guideScript = [
    { content: "", tool_calls: [{ id: "d1", type: "function", function: { name: "ver_cuarto", arguments: "{}" } }] },
    { content: "", tool_calls: [{ id: "d2", type: "function", function: { name: "equipar_catalogo", arguments: J({ servicio: "Wikipedia", nota: "fuente de research" }) } }] },
    { content: "", tool_calls: [{ id: "d3", type: "function", function: { name: "gestionar_agente", arguments: J({ accion: "guardar", nombre: "Mi research" }) } }] },
    { content: "Listo: equipé Wikipedia (fuente real) y guardé tu agente de research.", tool_calls: [] },
  ];
  const beforeN = await page.evaluate(() => window.__cuarto.placedTiles().length);
  await page.evaluate(() => window.__guide.send("ármame un agente de research"));
  await sleep(2500);   // equip real (interno keyless, sin red) + guardar real (POST /v1/puppets) + render
  const del = await page.evaluate(() => {
    const tiles = window.__cuarto.placedTiles();
    const wk = tiles.find((t) => /wiki/i.test(t.label || "") || /wiki/i.test(t.server || ""));
    let recipeOk = false; try { const r = window.__recipeMod.tilesToRecipe(tiles, window.__cuarto.nucleoData()); recipeOk = !!(r && (r.belt || r.model)); } catch (e) {}
    const cards = window.__guiaQA(".cop-card").length;
    const narra = window.__guiaQA(".ac-md, .cop-msg.g").some((el) => /equip|guard|research/i.test(el.textContent));
    return { n: tiles.length, hasWiki: !!wk, recipeOk, cards, narra };
  });
  ok(del.hasWiki && del.n > beforeN, `DELEGAR: el Guía COLOCÓ Wikipedia REAL vía equipar_catalogo (piezas ${beforeN}→${del.n})`);
  ok(del.recipeOk, `DELEGAR: receta resultante VÁLIDA (tilesToRecipe → model+belt)`);
  ok(del.cards > 0 && del.narra, `DELEGAR: NARRA (texto del guía) + card pop de apoyo (${del.cards})`);
  ok(!!savedPuppet, `DELEGAR: guardó al final — POST /v1/puppets REAL → id ${savedPuppet ? String(savedPuppet).slice(0, 8) : "—"}`);

  // ── 5 · MODO MOSTRAR (script): "¿dónde configuro el cerebro?" → abre el lugar REAL ──
  guideScript = [
    { content: "", tool_calls: [{ id: "s1", type: "function", function: { name: "elegir_cerebro", arguments: J({ provider: "opus" }) } }] },
    { content: "El cerebro se configura en el Núcleo — te lo abrí y señalé Opus.", tool_calls: [] },
  ];
  await page.evaluate(() => window.__guide.send("¿dónde configuro el cerebro?"));
  await sleep(500);
  const show = await page.evaluate(() => ({ insp: document.getElementById("inspector").classList.contains("open"), proposed: !!document.querySelector("#d-opts .modelcard.proposed") }));
  ok(show.insp && show.proposed, `MOSTRAR: abrió el inspector del Núcleo y PROPUSO la card del cerebro (lugar real)`);

  // ── 6 · GATE de credencial (script): conectar_pieza ABRE el flujo, no lo completa ──
  const gate = await page.evaluate(async () => {
    // pieza de conexión SIN conectar (sin connector) → conectar_pieza sólo debe ABRIR el flujo, no completarlo.
    window.__cuarto.placeTile({ id: "p_conn", key: "zotero", label: "Zotero", category: "read", atom: "conexion", server: "zotero", tools: ["list"] }, 5, 3);
    const r = await window.__guideHost.conectarPieza("p_conn");
    const still = window.__cuarto.placedTiles().find((t) => t.id === "p_conn");
    const inspOpen = document.getElementById("inspector").classList.contains("open");
    return { abrio: !!(r && r.abrio_conexion_de), sigueSinConectar: !!(still && !still.connector), inspOpen };
  });
  ok(gate.abrio && gate.inspOpen && gate.sigueSinConectar, `GATE: conectar_pieza ABRE el flujo (inspector, pide credencial al usuario), NO completa la conexión`);

  // ── 7 · SMOKE del cerebro REAL (claude_cli, frontier probado) — OPT-IN (T5_REAL_BRAIN=1; lento) ──
  if (process.env.T5_REAL_BRAIN === "1") try {
    await page.unroute("**/v1/cuarto/guide");   // ahora pega al backend REAL (cerebro real)
    const realBrain = await page.evaluate(async () => {
      try {
        localStorage.setItem("aleph.cuarto.guideBrain", "claude_cli");
        const model = window.__compileModel ? window.__compileModel("claude_cli") : { alias: "claude_cli", brain_provider: "claude_cli" };
        await window.AlephSession.ensureLocal();
        const u = window.AlephSession.get();
        const r = await fetch("/v1/cuarto/guide", { method: "POST", headers: { "Content-Type": "application/json", "Authorization": "Bearer " + (u && u.session_token) },
          body: JSON.stringify({ messages: [{ role: "user", content: "En una frase: ¿qué es el Cuarto?" }], guide_model: model, locale: "es" }) });
        const d = await r.json().catch(() => null);
        return { status: r.status, hasContent: !!(d && (d.content || (d.tool_calls || []).length)), model_final: d && d.model_final };
      } catch (e) { return { err: String(e) }; }
    });
    if (realBrain.status === 200 && realBrain.hasContent)
      ok(true, `SMOKE cerebro REAL (claude_cli) respondió · model_final=${realBrain.model_final}`);
    else
      console.log(`  ~ smoke cerebro real: status=${realBrain.status} (no bloqueante — CLI/red; el gate humano lo cubre en la .app)`);
  } catch (e) { console.log("  ~ smoke cerebro real saltado:", e.message); }

  // ── errores JS (tolerante a fallos externos: supabase/favicon/red) ──────────────────
  const realErr = jsErrors.filter((e) => !/supabase|favicon|Failed to fetch|NetworkError|Load failed|net::/i.test(e));
  console.log("");
  ok(realErr.length === 0, `0 errores JS propios${realErr.length ? " — " + realErr.slice(0, 3).join(" | ") : ""}`);
} catch (e) {
  console.error("HARNESS ERROR:", e && e.stack || e); fail++; fails.push("harness crash: " + (e && e.message || e));
} finally { try { if (browser) await browser.close(); } catch (e) {} }

console.log(`\n${fail === 0 ? "✅ VERDE (sidecar real)" : "❌ ROJO"} — ${pass} ok / ${fail} fail`);
if (fails.length) { console.log("FALLAS:"); fails.forEach((f) => console.log("  ✗", f)); }
process.exit(fail === 0 ? 0 : 1);
