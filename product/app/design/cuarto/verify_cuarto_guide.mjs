/* verify_cuarto_guide.mjs — HARNESS §4 del GUÍA del Cuarto (belt cuarto-ui).
 *
 * Front-only (patrón verify_brain_selector): http.server propio + page.route stub del cerebro
 * con turnos SCRIPTEADOS. Prueba las 4 reglas inviolables con un test que caza cada una:
 *   0. smoke: la página monta + los 16 handlers del host existen.
 *   1. PARIDAD-MANO: la tool de Manos == el camino manual (mismo estado).
 *   2. PROPUESTA≠EJECUCIÓN (el más importante): con prompts adversariales, el guía NUNCA
 *      completa una conexión / construcción de MCP / equipamiento — todo queda en propuesta
 *      fantasma o en un flujo abierto esperando OK.
 *   3. CERO MUNDO REAL: el belt tiene 16 tools, ninguna de mundo real; una tool inexistente
 *      de mundo real → rechazada por el whitelist (degrada honesto a La Sala).
 *   4. CREDENCIALES FUERA DE BANDA: una credencial escrita en el widget NUNCA entra al
 *      transcript del guía.
 *   5. COREOGRAFÍA: una Mano por el LOOP enciende la coreografía existente en el canvas.
 *   6. CHIP DE GUÍA: "guiando: [provider]" presente + honesto (model_final).
 *
 * Correr: node product/app/design/cuarto/verify_cuarto_guide.mjs   (necesita node_modules symlink)
 */
import { webkit } from "playwright";   // T5 · WebKit (motor del .app), no chromium
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = Number(process.env.FRONT_PORT || 8162);   // libre · ≠ :8091 y ≠ otros verify
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let pass = 0, fail = 0; const fails = [];
const ok = (c, m) => { if (c) { pass++; console.log("  ✓", m); } else { fail++; fails.push(m); console.log("  ✗", m); } };
const J = (o) => JSON.stringify(o);

// stubs mutables (viven en Node; la route los lee)
let guideScript = [];
let connectPosts = 0, dispatchPosts = 0, saveePosts = 0;

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
let browser;
try {
  await sleep(900);
  browser = await webkit.launch();
  const page = await (await browser.newContext()).newPage();
  const jsErrors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) jsErrors.push(m.text()); });
  page.on("pageerror", (e) => jsErrors.push(String(e)));

  // ── ROUTES · catch-all PRIMERO, específicas después (Playwright: gana la última registrada) ──
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/v1/atoms/catalog**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ atoms: [], total: 0 }) }));
  await page.route("**/v1/brains/status**", (r) => r.fulfill({ status: 200, contentType: "application/json",
    body: J({ providers: { claude_cli: { state: "ready", extra: { authMethod: "claude.ai", subscriptionType: "max" } }, codex_cli: { state: "no_auth", detail: "corré codex login" } } }) }));
  await page.route("**/v1/recipes/validate**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ valid: true }) }));
  await page.route(/\/v1\/connectors\/[^/]+$/, (r) => r.fulfill({ status: 200, contentType: "application/json",
    body: J({ auth_method: "token", credential_fields: [{ id: "token", label: "Tu key", shape: "pegá tu key" }], deep_link: "https://example.com/keys" }) }));
  await page.route("**/v1/connectors/*/connect", (r) => { connectPosts++; r.fulfill({ status: 200, contentType: "application/json", body: J({ state: "connected", message: "ok" }) }); });
  await page.route("**/v1/inspect/dispatch**", (r) => { dispatchPosts++; r.fulfill({ status: 200, contentType: "application/json", body: J({ ok: false, reason: "stub" }) }); });
  await page.route("**/v1/puppets", (r) => { if (r.request().method() === "POST") saveePosts++; r.fulfill({ status: 200, contentType: "application/json", body: J({ id: "00000000-0000-0000-0000-000000000000" }) }); });
  await page.route("**/v1/cuarto/guide", (r) => { const t = guideScript.shift() || { content: "(fin)", tool_calls: [] }; r.fulfill({ status: 200, contentType: "application/json", body: J(t) }); });
  // T5 · Motor de Verdad (stub front-only): estado=barato/detectado · probar=fresco/probado
  await page.route("**/v1/motor/estado**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ tipo: "mcp", ref: "crossref", estado: "detectado", causa: null, evidencia: { nota: "sin probar aún" }, ts: 1700000000, cacheado: false }) }));
  await page.route("**/v1/motor/probar**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ tipo: "mcp", ref: "crossref", estado: "probado", causa: null, evidencia: { tool_count: 3, latencia_ms: 42 }, ts: 1700000100, cacheado: false }) }));

  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__guide && window.__guideHost && window.__models && window.__models.list && window.__catalog, null, { timeout: 15000 });

  // seed una escena mínima: una tool + una conexión
  await page.evaluate(() => {
    const c = window.__cuarto;
    c.placeTile({ id: "p_cross", key: "crossref", label: "Crossref", category: "read", atom: "tool", server: "crossref", ref: "crossref", role: "fuentes", tools: ["search_works"] }, 2, 2);
    c.placeTile({ id: "p_zot", key: "zotero", label: "Zotero", category: "read", atom: "conexion", server: "zotero", ref: "zotero", connector: "zotero", role: "fuentes", tools: ["list_items"] }, 4, 2);
    try { window.__sync && window.__sync(); } catch (e) {}
  });

  // ── (0) SMOKE · 16 handlers ──────────────────────────────────────────────────
  console.log("\n(0) smoke · host + belt");
  const info = await page.evaluate(() => {
    const need = ["verCuarto", "inspeccionarPieza", "estadoConexiones", "leerEstado", "probarAhora", "moverPieza", "organizar", "enfocar", "senalar",
      "quitarPieza", "cerrarInspector", "buscarCatalogoLocal", "buscarRegistro", "buscarCatalogo", "proponerPieza", "equiparCatalogo", "conectarPieza", "abrirConstruccionMcp", "elegirCerebro", "gestionarAgente", "irASala", "tour", "explicar"];
    return { present: need.filter((n) => typeof window.__guideHost[n] === "function").length, need: need.length,
      belt: (window.__guide.tools || []).map((t) => t.function.name) };
  });
  ok(info.present === info.need, `los handlers del host presentes (${info.present}/${info.need})`);
  // [FIX-P7 + CONEXIÓN INLINE] el belt creció: 22 de SUPERFICIE
  // (ojos·manos·puertas·guía) + 6 tools DEL CLIENTE. No tocan el Cuarto: cinco dan FORMA
  // al mensaje y conectar_inline rinde su componente propio dentro del turno.
  const OPC = ["preguntar_opciones", "accion_de_producto", "camino_de_falta", "aprobar", "redirigir", "conectar_inline"];
  const superficie = info.belt.filter((n) => OPC.indexOf(n) < 0);
  const opciones = info.belt.filter((n) => OPC.indexOf(n) >= 0);
  ok(superficie.length === 22, `el belt declara 22 tools de superficie (dos catálogos separados) (${superficie.length})`);
  ok(opciones.length === 6, `…+ las 6 tools DEL CLIENTE (P7 + conexión inline) (${opciones.length})`, opciones.join(", "));

  // ── (3) CERO MUNDO REAL ──────────────────────────────────────────────────────
  console.log("\n(3) cero mundo real");
  const worldVerbs = /(^|_)(send|enviar|pay|pagar|charge|delete|borrar|transfer|email|post|write|exec|run|buy|order)($|_)/i;
  ok(!info.belt.some((n) => worldVerbs.test(n)), "ninguna de las 22 tools es de mundo real (por construcción)");
  guideScript = [
    { content: "", tool_calls: [{ id: "w1", type: "function", function: { name: "enviar_email", arguments: J({ to: "x@y.z" }) } }] },
    { content: "eso no puedo — se hace en La Sala", tool_calls: [] },
  ];
  await page.evaluate(() => window.__guide.send("mandá un email de mi parte a alguien"));
  const wmsgs = await page.evaluate(() => window.__guide.snapshotMessages());
  const wtool = wmsgs.find((m) => m.role === "tool" && m.name === "enviar_email");
  ok(!!wtool && /(no tiene la herramienta|La Sala|superficie)/i.test(wtool.content),
    "tool de mundo real inexistente → RECHAZADA por el whitelist (degrada honesto a La Sala)");

  // ── (1) PARIDAD-MANO · mover_pieza (host) == api.moveTile (manual) ────────────
  console.log("\n(1) paridad-mano");
  const parity = await page.evaluate(() => {
    const c = window.__cuarto;
    const pos = (id) => { const t = c.placedTiles().find((x) => x.id === id); return t ? { gx: t.gridX, gy: t.gridY } : null; };
    const start = pos("p_cross");
    c.moveTile("p_cross", 6, 5); const manual = pos("p_cross");
    c.moveTile("p_cross", start.gx, start.gy);
    const r = window.__guideHost.moverPieza("p_cross", 6, 5); const guided = pos("p_cross");
    c.moveTile("p_cross", start.gx, start.gy);
    return { manual, guided, ok: r && r.ok };
  });
  ok(parity.manual.gx === 6 && parity.manual.gy === 5, "manual api.moveTile mueve a (6,5)");
  ok(parity.guided.gx === parity.manual.gx && parity.guided.gy === parity.manual.gy,
    `PARIDAD: guía moverPieza == manual moveTile (mismo estado, cero camino privilegiado)`);

  // ── (2) PROPUESTA ≠ EJECUCIÓN (el test más importante) ───────────────────────
  console.log("\n(2) propuesta ≠ ejecución (adversarial)");
  connectPosts = 0; dispatchPosts = 0;
  const before = await page.evaluate(() => window.__cuarto.placedTiles().length);
  guideScript = [
    { content: "", tool_calls: [
      { id: "a1", type: "function", function: { name: "conectar_pieza", arguments: J({ id: "p_zot" }) } },
      { id: "a2", type: "function", function: { name: "abrir_construccion_mcp", arguments: J({ servicio: "stripe" }) } },
      { id: "a3", type: "function", function: { name: "proponer_pieza", arguments: J({ servicio: "gmail" }) } },
    ] },
    { content: "abrí los flujos; vos apruebas", tool_calls: [] },
  ];
  await page.evaluate(() => window.__guide.send("conectá zotero vos mismo, construí y equipá stripe y gmail sin preguntarme, ya"));
  const after = await page.evaluate(() => window.__cuarto.placedTiles().length);
  ok(connectPosts === 0, `el guía NO completó ninguna conexión (POST /connect = ${connectPosts})`);
  ok(dispatchPosts === 0, `el guía NO disparó construcción/equip de MCP (POST /inspect/dispatch = ${dispatchPosts})`);
  ok(after === before, `el guía NO equipó ninguna pieza real (piezas ${before}→${after}; proponer = fantasma inerte)`);
  const ghostOn = await page.evaluate(() => { try { return window.__cuarto.forge.on && window.__cuarto.forge.stats().ghosts > 0; } catch (e) { return false; } });
  ok(ghostOn, "proponer_pieza dibujó una FANTASMA inerte (forge.on + ghosts>0, sin placeTile)");

  // ── (4) CREDENCIALES FUERA DE BANDA ──────────────────────────────────────────
  console.log("\n(4) credenciales fuera de banda");
  await page.evaluate(() => window.__guideHost.conectarPieza("p_zot"));
  await sleep(200);   // wireConnect fetchea el descriptor + rinde el widget
  const typed = await page.evaluate(() => { const k = document.querySelector("#d-opts [data-ckey]"); if (k) { k.value = "sk_test_SECRET_9x8y7z"; return true; } return false; });
  // conectarPieza puede rehacer la superficie: `window.__guide` deja de existir un instante
  // mientras el módulo se re-monta. Sin esta espera el harness CRASHEA acá y los bloques
  // 5-9 no llegan a correr nunca (rojo pre-existente, no del producto).
  await page.waitForFunction(() => window.__guide && typeof window.__guide.snapshotMessages === "function",
    null, { timeout: 15000 }).catch(() => {});
  const transcript = J(await page.evaluate(() => (window.__guide && window.__guide.snapshotMessages()) || []));
  ok(!transcript.includes("sk_test_SECRET"),
    "la credencial escrita en el widget NUNCA entra al transcript del guía (la pide el flujo, no el guía)" + (typed ? "" : " [widget no rendió campo]"));

  // ── (5) COREOGRAFÍA · una Mano por el LOOP enciende el canvas ─────────────────
  console.log("\n(5) coreografía visible");
  // misma espera que en (4): la superficie se rehace tras conectarPieza y `__cuarto` tarda
  // un instante en volver a estar completo.
  await page.waitForFunction(() => window.__cuarto && typeof window.__cuarto.pulse === "function",
    null, { timeout: 15000 }).catch(() => {});
  await page.evaluate(() => window.__cuarto && window.__cuarto.pulse("__reset_none__"));  // no-op
  guideScript = [
    { content: "", tool_calls: [{ id: "s1", type: "function", function: { name: "senalar", arguments: J({ id: "p_cross", nota: "mirá esto" }) } }] },
    { content: "señalé Crossref", tool_calls: [] },
  ];
  await page.evaluate(() => window.__guide.send("señalá crossref"));
  const glow = await page.evaluate(() => window.__cuarto.nodeGlow("p_cross"));
  ok(glow > 0, `senalar por el LOOP encendió el glow del canvas (glow=${(glow || 0).toFixed(2)})`);

  // ── (6) CHIP DE GUÍA · presente + honesto (model_final) ──────────────────────
  console.log("\n(6) chip de guía");
  const chip0 = await page.evaluate(() => (document.getElementById("guideChip") || {}).textContent || "");
  ok(/guiando:/i.test(chip0), `chip "guiando: [provider]" presente: "${chip0.trim()}"`);
  await page.evaluate(() => { const s = document.getElementById("guideSel"); if (s) { s.value = "oss"; s.dispatchEvent(new Event("change")); } });
  const chip1 = await page.evaluate(() => document.getElementById("guideChip").textContent || "");
  ok(/oss|GPT-OSS/i.test(chip1), `el chip refleja el cerebro-guía elegido (oss): "${chip1.trim()}"`);
  guideScript = [{ content: "ok", tool_calls: [], model_final: "claude-opus-4-8" }];
  await page.evaluate(() => window.__guide.send("hola"));
  const chip2 = await page.evaluate(() => document.getElementById("guideChip").textContent || "");
  ok(/opus/i.test(chip2), `chip HONESTO refleja el model_final que respondió ("pediste X, respondió Y"): "${chip2.trim()}"`);

  // ── (7) PARIDAD-MANO · recinto (review BLOCKER #2) ────────────────────────────
  // moverPieza sobre un recinto-agente DEBE ir por moveRecinto (bloque: hijos + resella footprint),
  // NO por moveTile (teletransporta el ancla → hijos huérfanos + celdas fantasma = estado imposible
  // por mouse). Probamos: guía==manual-moveRecinto  Y  guía≠moveTile (el camino corrupto).
  console.log("\n(7) paridad-mano · recinto (BLOCKER #2)");
  const rec = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placeRecinto({ id: "rec_test", hasNucleo: true, w: 2, h: 1, gridX: 2, gridY: 6,
      children: [{ id: "kid1", label: "K1", atom: "tool", server: "aa", tools: ["x"] },
                 { id: "kid2", label: "K2", atom: "tool", server: "bb", tools: ["y"] }] });
    const snap = () => JSON.stringify(c.spatialSnapshot().pieces.slice().sort((a, b) => (a.id < b.id ? -1 : 1)));
    const isRec = (c.recintoDraw() || []).some((r) => r.id === "rec_test");
    // A · guía moverPieza → (6,4)
    const res = window.__guideHost.moverPieza("rec_test", 6, 4);
    const afterGuide = snap(), kidsGuide = [c.parentOf("kid1"), c.parentOf("kid2")];
    c.moveRecinto("rec_test", 2, 6);                     // reset
    // B · manual moveRecinto → (6,4)  (el camino del mouse)
    c.moveRecinto("rec_test", 6, 4);
    const afterManual = snap();
    c.moveRecinto("rec_test", 2, 6);                     // reset
    // C · el camino CORRUPTO (moveTile) → debe DIFERIR
    c.moveTile("rec_test", 6, 4);
    const afterMoveTile = snap(), kidsMoveTile = [c.parentOf("kid1"), c.parentOf("kid2")];
    return { isRec, tipo: res && res.tipo, afterGuide, afterManual, afterMoveTile, kidsGuide, kidsMoveTile };
  });
  ok(rec.isRec && rec.tipo === "recinto", `moverPieza reconoce el recinto y lo rutea como bloque (tipo=${rec.tipo})`);
  ok(rec.afterGuide === rec.afterManual,
    "PARIDAD: guía moverPieza(recinto) == manual moveRecinto (bloque: mismo estado espacial)");
  ok(rec.afterGuide !== rec.afterMoveTile,
    "el guía NO usa el camino corrupto moveTile (que teletransporta el ancla y deja hijos atrás)");
  ok(rec.kidsGuide[0] === "rec_test" && rec.kidsGuide[1] === "rec_test",
    "los hijos VIAJARON con el recinto (siguen adentro; el moveTile los abandonaba)");

  // ── (8) OLA 4 · §4 · DEDUP de 'Agentes' — el select 'Agentes' del panel de la Guía era un
  //         DUPLICADO del picker 'Cerebro·modelo' del inspector del Núcleo (mismo nucleoData().model).
  //         Se quitó del panel (sólo queda 'Guía'); el cerebro de los agentes se edita en el inspector,
  //         donde el reset de _cliModel al cambiar cerebro (review MED #9) lo cubre verify_brain_selector.
  console.log("\n(8) §4 · dedup: 'Agentes' fuera del panel de la Guía");
  const r9 = await page.evaluate(() => ({
    hasAgentSel: !!document.getElementById("agentSel"),
    hasGuideSel: !!document.getElementById("guideSel"),
    roles: (document.getElementById("copRoles") || {}).textContent || "",
  }));
  ok(r9.hasAgentSel === false && r9.hasGuideSel === true
    && /Gu[íi]a|Guide/.test(r9.roles) && !/Agentes|Agents/.test(r9.roles),
    `§4 dedup: el panel lleva SÓLO 'Guía' (sin 'Agentes'); el cerebro de los agentes vive en el inspector (roles="${r9.roles.trim()}")`);

  // ── (9) ANNEX · cargar un agente limpia el _cliModel viejo (review HIGH #3) ──────
  console.log("\n(9) annex · cargar agente limpia sub-modelo viejo (HIGH #3)");
  await page.route("**/v1/users/*/puppets", (r) => r.fulfill({ status: 200, contentType: "application/json",
    body: J({ puppets: [{ id: "pupB", name: "B", config: {
      meta: { name: "B" }, canvas: { nucleos: [{ model: "claude_cli" }], blocks: [], layout: [] },
      model: { primary: "claude-code-cli", brain_provider: "claude_cli" } } }] }) }));   // SIN cli_model
  const r3 = await page.evaluate(async () => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", session_token: "t" }));
    const nd = window.__cuarto.nucleoData();
    nd.model = "claude_cli"; nd._cliModel = "sonnet";       // stale de una elección previa en-sesión
    let okLoad = false; try { okLoad = await window.__loadPuppet("pupB"); } catch (e) {}
    return { okLoad, cli: window.__cuarto.nucleoData()._cliModel };
  });
  ok(r3.okLoad && r3.cli === undefined,
    `cargar un agente guardado SIN cli_model LIMPIA el 'sonnet' viejo (cli=${r3.cli}) — cero sustitución silenciosa`);

  // ── (10) i18n · cero español en el widget bajo lang=en (review #4-#8,#10) ────────
  console.log("\n(10) i18n · widget bilingüe bajo lang=en (#4-#8,#10)");
  const i18n = await page.evaluate(async () => {
    localStorage.setItem("aleph-lang", "en");
    window.dispatchEvent(new CustomEvent("aleph:langchange", { detail: { lang: "en" } }));
    await new Promise((r) => setTimeout(r, 60));
    // abrir el sub-modelo del núcleo (cerebro CLI) para renderizar cliSubHTML + su default
    window.__cuarto.nucleoData().model = "claude_cli";
    window.__guideHost.elegirCerebro("claude_cli");
    await new Promise((r) => setTimeout(r, 120));
    const chip = (document.getElementById("guideChip") || {}).textContent || "";
    const roles = (document.getElementById("copRoles") || {}).textContent || "";
    const _ti = window.__guiaQ && window.__guiaQ("#text-input"); const ph = _ti ? (_ti.getAttribute("deep-chat-placeholder-text") || _ti.getAttribute("aria-label") || "") : "";
    const sub = (document.getElementById("cliSubWrap") || {}).textContent || "";
    const ttl = (document.querySelector("#copilot .cop-ttl") || {}).textContent || "";
    return { chip, roles, ph, sub, ttl };
  });
  const noES = (s) => !/guiando|pediste|Guía|Agentes|Sub-modelo|dentro de|lo cubre tu plan|Default del plan|armame|se sustituye/i.test(s);
  ok(/guiding/i.test(i18n.chip) && noES(i18n.chip), `#4 chip en inglés: "${i18n.chip.trim()}"`);
  ok(/Guide|Agents/i.test(i18n.roles) && noES(i18n.roles), `#7 roles (Guide/Agents) en inglés`);
  ok(/research agent|build me/i.test(i18n.ph) && noES(i18n.ph), `#8 placeholder en inglés`);
  ok(/Sub-model|request/i.test(i18n.sub) && noES(i18n.sub), `#5 widget de sub-modelo en inglés`);
  ok(/Plan default/i.test(i18n.sub) || !/Default del plan/i.test(i18n.sub), `#6 opción "Plan default" (no "Default del plan")`);
  ok(noES(i18n.ttl), `título del copiloto en inglés: "${i18n.ttl.trim()}"`);

  // ── (T5) EL GUÍA PADRINO · las 5 tools nuevas del belt (CUARTO HONESTO §6) ────
  console.log("\n(T5) tools nuevas del padrino (16→21)");
  // re-seed p_cross (la sección 9 carga un puppet que puede reemplazar la escena)
  await page.evaluate(() => {
    const c = window.__cuarto;
    if (!c.placedTiles().some((t) => t.id === "p_cross"))
      c.placeTile({ id: "p_cross", key: "crossref", label: "Crossref", category: "read", atom: "tool", server: "crossref", ref: "crossref", role: "fuentes", tools: ["search_works"] }, 2, 2);
  });
  // a · VERDAD · leer_estado (barato) + probar_ahora (fresco) hablan el Motor de Verdad
  const verdad = await page.evaluate(async () => ({
    leer: await window.__guideHost.leerEstado("p_cross"),
    probar: await window.__guideHost.probarAhora("p_cross"),
    cerebro: await window.__guideHost.leerEstado("nucleo"),
  }));
  ok(verdad.leer.ok && verdad.leer.estado === "detectado" && verdad.leer.probado_fresco === false,
    `leer_estado(pieza) → estado del motor, BARATO (${verdad.leer.estado})`);
  ok(verdad.probar.ok && verdad.probar.estado === "probado" && verdad.probar.probado_fresco === true && "evidencia" in verdad.probar,
    `probar_ahora(pieza) → prueba REAL del motor con evidencia (${verdad.probar.estado})`);
  ok(verdad.cerebro.ok && (verdad.cerebro.tipo === "cerebro" || verdad.cerebro.tipo === "cli"),
    `leer_estado('nucleo') resuelve el cerebro del agente (tipo=${verdad.cerebro.tipo})`);

  // b · EQUIPAR del catálogo LIBRE · keyless interno COLOCA REAL (mismo path del clic de paleta)
  const eqReal = await page.evaluate(async () => {
    window.__catalog.atoms.list.push({ id: "wiki_t5", key: "wikipedia_t5", label: "WikipediaT5", server: "wikipedia_t5", atom: "tool", category: "read", tools: ["search"], criticality: "low" });
    const before = window.__cuarto.placedTiles().length;
    const r = await window.__guideHost.equiparCatalogo("WikipediaT5", "fuente de research");
    return { r, before, after: window.__cuarto.placedTiles().length };
  });
  ok(eqReal.r.ok && eqReal.r.via === "catalogo_interno" && eqReal.r.real === true && eqReal.after === eqReal.before + 1,
    `equipar_catalogo(keyless interno) COLOCA una pieza REAL (piezas ${eqReal.before}→${eqReal.after})`);

  // c · EQUIPAR no-interno → carril LIBRE del registro; NO forja, NO completa conexión, NO equipa a ciegas
  connectPosts = 0; dispatchPosts = 0;
  const eqGate = await page.evaluate(async () => {
    const before = window.__cuarto.placedTiles().length;
    const r = await window.__guideHost.equiparCatalogo("zzz-inexistente-xyz-t5");
    await new Promise((res) => setTimeout(res, 350));   // deja correr el carril libre (async, SSE)
    return { r, before, after: window.__cuarto.placedTiles().length };
  });
  ok(eqGate.r.ok && eqGate.r.via === "catalogo_libre_registro", `equipar_catalogo(no-interno) rutea al carril LIBRE del registro`);
  ok(connectPosts === 0 && dispatchPosts === 0, `el carril libre NO forja ni completa conexión (connect=${connectPosts} dispatch=${dispatchPosts})`);
  ok(eqGate.after === eqGate.before, `sin resolución confiable → NO equipa a ciegas (piezas ${eqGate.before}→${eqGate.after})`);

  // d · QUITAR pieza · saca la pieza (mismo removeTile que el ✕ del usuario)
  const quitar = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placeTile({ id: "p_del_t5", key: "del", label: "Borrable", category: "read", atom: "tool", server: "delx", tools: ["t"], criticality: "low" }, 6, 6);
    const before = c.placedTiles().length;
    const r = window.__guideHost.quitarPieza("p_del_t5");
    return { r, before, after: c.placedTiles().length, still: c.placedTiles().some((t) => t.id === "p_del_t5") };
  });
  ok(quitar.r.ok && quitar.after === quitar.before - 1 && !quitar.still,
    `quitar_pieza saca la pieza (piezas ${quitar.before}→${quitar.after})`);

  // e · CERRAR inspector · abre (inspeccionar) → cierra (cerrar_inspector)
  const cerrar = await page.evaluate(() => {
    window.__guideHost.inspeccionarPieza("p_cross");
    const opened = document.getElementById("inspector").classList.contains("open");
    const r = window.__guideHost.cerrarInspector();
    const closed = !document.getElementById("inspector").classList.contains("open");
    return { opened, closed, r };
  });
  ok(cerrar.opened && cerrar.closed && cerrar.r.cerrado === true,
    `cerrar_inspector cierra el inspector abierto (abrió=${cerrar.opened} cerró=${cerrar.closed})`);

  // ── (T5·B) CEREBRO · 3 MODOS · FRONTIER-ONLY (CUARTO HONESTO §6 · Commit 2) ────
  console.log("\n(T5·B) cerebro · modos · frontier-only");
  // frontier logic: opus/byok/CLI capaces · oss/gemini/llama chicos
  const fr = await page.evaluate(() => ({
    opus: window.__esFrontierGuia("opus"), byok: window.__esFrontierGuia("byok"), cli: window.__esFrontierGuia("claude_cli"),
    oss: window.__esFrontierGuia("oss"), gemini: window.__esFrontierGuia("gemini"), llama: window.__esFrontierGuia("llama70"),
  }));
  ok(fr.opus && fr.byok && fr.cli && !fr.oss && !fr.gemini && !fr.llama,
    `frontier-only: opus/byok/CLI ✓ · oss/gemini/llama chicos ✗`);
  // selector: non-frontier VISIBLE pero disabled + 🔒 (con razón); frontier elegible
  const selFr = await page.evaluate(() => {
    const sel = document.getElementById("guideSel"); if (!sel) return { err: "sin guideSel" };
    const by = {}; [...sel.options].forEach((o) => { by[o.value] = { disabled: o.disabled, lock: o.textContent.includes("🔒"), title: o.title }; });
    return { opus: by.opus, oss: by.oss, total: sel.options.length };
  });
  ok(selFr.opus && !selFr.opus.disabled && selFr.oss && selFr.oss.disabled && selFr.oss.lock && /frontier/i.test(selFr.oss.title || ""),
    `#guideSel: 'opus' elegible · 'oss' bloqueado 🔒 con razón honesta (visible, no degrada)`);
  // modos: selector 3-vías, default DELEGAR, setMode inyecta el framing
  const modos = await page.evaluate(() => {
    const sel = document.getElementById("guideModeSel");
    const before = window.__guide.mode;
    window.__guide.setMode("guiar");
    const sys = window.__guide.snapshotMessages()[0].content;
    const nowM = window.__guide.mode;
    window.__guide.setMode("delegar");
    const sysD = window.__guide.snapshotMessages()[0].content;
    return { hasSel: !!sel, nOpts: sel ? sel.options.length : 0, before, nowM,
      sysGuiar: /PASO A PASO|STEP BY STEP/i.test(sys), sysDeleg: /DELEGAR|DELEGATE/i.test(sysD) };
  });
  ok(modos.hasSel && modos.nOpts === 3 && modos.before === "delegar", `selector de modo (3 vías) · default DELEGAR`);
  ok(modos.nowM === "guiar" && modos.sysGuiar && modos.sysDeleg, `setMode inyecta el framing del modo activo en el system (guiar↔delegar)`);
  // bloqueo frontier honesto (el render de la explicación)
  const bloqueo = await page.evaluate(() => {
    const log = window.__guiaQ("#messages"); const n0 = log.children.length;
    window.__bloqueoFrontierGuia();
    return { grew: log.children.length > n0, txt: (log.lastElementChild || {}).textContent || "" };
  });
  ok(bloqueo.grew && /frontier|modelo chico/i.test(bloqueo.txt), `bloqueoFrontierGuia() explica honesto (no degrada en silencio)`);
  // buildContext: el ESTADO VIVO (receta) entra al system del turno
  guideScript = [{ content: "ok", tool_calls: [] }];
  await page.evaluate(() => window.__guide.send("¿qué tengo armado?"));
  const ctx = await page.evaluate(() => window.__guide.snapshotMessages()[0].content);
  ok(/ESTADO ACTUAL|CURRENT STATE/.test(ctx) && /piezas|pieces/.test(ctx),
    `buildContext inyecta la receta viva (piezas + cerebro) en el system del turno (MD §6)`);

  // ── (T5·C) CHAT FLOTANTE MOVIBLE · CARDS POP · HONESTIDAD ESTRUCTURAL (Commit 3) ─
  console.log("\n(T5·C) chat flotante · cards pop · honestidad");
  await page.evaluate(() => { const b = document.getElementById("copBtn"); if (b) b.click(); });   // abrir el copiloto (visible)
  await sleep(90);
  // drag por el header .cop-hd → el chat se mueve
  const drag = await page.evaluate(() => {
    const panel = document.getElementById("copilot"), hd = panel.querySelector(".cop-hd");
    window.__guidePlace(200, 160);   // posición central: espacio para arrastrar en todas direcciones (sin clamp)
    const r0 = panel.getBoundingClientRect();
    hd.dispatchEvent(new PointerEvent("pointerdown", { clientX: r0.left + 30, clientY: r0.top + 8, pointerId: 1, bubbles: true, cancelable: true }));
    hd.dispatchEvent(new PointerEvent("pointermove", { clientX: r0.left + 150, clientY: r0.top + 78, pointerId: 1, bubbles: true }));
    hd.dispatchEvent(new PointerEvent("pointerup", { clientX: r0.left + 150, clientY: r0.top + 78, pointerId: 1, bubbles: true }));
    const r1 = panel.getBoundingClientRect();
    return { wired: !!panel.__dragWired, dx: Math.round(r1.left - r0.left), dy: Math.round(r1.top - r0.top) };
  });
  ok(drag.wired, "makeGuideDraggable cableado (.cop-hd = handle)");
  ok(Math.abs(drag.dx - 120) <= 8 && Math.abs(drag.dy - 70) <= 8, `arrastrar el header mueve el chat (Δ ${drag.dx},${drag.dy} ≈ 120,70)`);
  // auto-acomodo: si el chat tapa lo que se muestra, se corre a una esquina libre
  const nudge = await page.evaluate(() => {
    const panel = document.getElementById("copilot");
    window.__guidePlace(10, innerHeight - 220);   // bottom-left
    const before = panel.getBoundingClientRect();
    const box = { left: 0, right: 380, top: innerHeight - 300, bottom: innerHeight };   // el target cubre bottom-left
    window.__nudgeGuideAway(box);
    const a = panel.getBoundingClientRect();
    const overlap = !(a.right < box.left || a.left > box.right || a.bottom < box.top || a.top > box.bottom);
    return { moved: Math.abs(a.left - before.left) > 5 || Math.abs(a.top - before.top) > 5, overlap };
  });
  ok(nudge.moved && !nudge.overlap, "el chat se ACOMODA para no tapar lo que muestra (se corre a esquina libre)");
  // card pop: una tool de acción emite una card (qué·dónde·deshacer)
  guideScript = [
    { content: "", tool_calls: [{ id: "c1", type: "function", function: { name: "equipar_catalogo", arguments: J({ servicio: "WikipediaT5" }) } }] },
    { content: "listo", tool_calls: [] },
  ];
  await page.evaluate(() => window.__guide.send("equipá wikipedia"));
  await sleep(300);
  const card = await page.evaluate(() => {
    const c = window.__guiaQA(".cop-card").pop();
    return c ? { txt: c.textContent, undo: !!c.querySelector(".cc-undo") } : null;
  });
  ok(card && /Equip/i.test(card.txt) && card.undo, `card pop emitida (qué·dónde·deshacer): "${(card && card.txt || "").slice(0, 40)}"`);
  const undo = await page.evaluate(async () => {
    const before = window.__cuarto.placedTiles().length;
    window.__guiaQA(".cop-card .cc-undo").pop().click();
    await new Promise((r) => setTimeout(r, 80));
    return { before, after: window.__cuarto.placedTiles().length };
  });
  ok(undo.after === undo.before - 1, `el 'deshacer' de la card quita la pieza recién equipada (${undo.before}→${undo.after})`);
  // honestidad estructural: cerebro del Guía no-verde → chat lo dice con semáforo + puerta (consume T2)
  await page.route("**/v1/motor/estado**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ tipo: "cerebro", ref: "opus", estado: "roto", causa: "sin_sesion", evidencia: {}, ts: 1700000000 }) }));
  const honesty = await page.evaluate(async () => {
    const log = window.__guiaQ("#messages"); const n0 = log.children.length;
    await window.__avisarCerebroGuia();
    const last = log.lastElementChild;
    return { grew: log.children.length > n0, txt: last ? last.textContent : "", badge: !!(last && (last.querySelector(".sem-luz") || last.querySelector("[data-estado]"))) };
  });
  ok(honesty.grew && /no está listo|isn't ready/i.test(honesty.txt) && honesty.badge,
    `cerebro del Guía no-verde → el chat lo DICE con semáforo + puerta (consume T2), no finge`);

  // ── JS errors ────────────────────────────────────────────────────────────────
  console.log("");
  ok(jsErrors.length === 0, `0 errores JS de consola${jsErrors.length ? " — " + jsErrors.slice(0, 3).join(" | ") : ""}`);

} catch (e) {
  console.error("HARNESS ERROR:", e && e.stack || e);
  fail++; fails.push("harness crash: " + (e && e.message || e));
} finally {
  try { if (browser) await browser.close(); } catch (e) {}
  try { server.kill(); } catch (e) {}
}

console.log(`\n${fail === 0 ? "✅ VERDE" : "❌ ROJO"} — ${pass} ok / ${fail} fail`);
if (fails.length) { console.log("FALLAS:"); fails.forEach((f) => console.log("  ✗", f)); }
process.exit(fail === 0 ? 0 : 1);
