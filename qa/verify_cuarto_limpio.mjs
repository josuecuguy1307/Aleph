/* verify_cuarto_limpio.mjs — ola C · CUARTO LIMPIO (feat/cuarto-limpio)
 *
 * La vara de la consolidación final del Cuarto, contra el worktree REAL, en los DOS motores
 * (chromium + webkit) y los DOS anchos (wide 1440 · narrow 1120). Estructura y comportamiento
 * de la capa de experiencia — no necesita backend: el /v1 va stubbeado con page.route, igual
 * que verify_rag_panel.mjs. Lo que se mide es lo que el usuario ve y toca.
 *
 *   A · BARRA DE 3 (item 2) — en #topright sólo quedan VISIBLES [← Salir] · [▶ Run] · [⋯];
 *       todo lo relegado sigue EXISTIENDO dentro de #metaMenu (cero pérdida de función) y
 *       agrupado en FAMILIAS con encabezado (no una lista plana).
 *   B · POPUP DEL NÚCLEO (item 1) — el closet del Núcleo se ancla a SU sprite igual que el de
 *       una pieza, y SIGUE anclado en 3 posiciones de cámara (zoom · rotar · encuadrar).
 *       Vara: el borde del popup queda a ≤ N px del punto del sprite (artScreenOf).
 *
 * Run:  node qa/verify_cuarto_limpio.mjs        (headless, SIN backend)
 * Puerto propio :8223 — jamás :25374 (la .app de persona usuaria).
 */
import { chromium, webkit } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..", "product", "app", "design");
// El :8223 que pedía la orden está OCUPADO por el sidecar de la ola B (conexiones_sidecar, worktree
// aleph-conexiones). No se mata una sesión paralela (CLAUDE.md §4g) → puerto propio :8323. Si algún
// día 8323 también está tomado, el preflight de abajo lo grita en vez de verificar la app ajena.
const PORT = Number(process.env.FRONT_PORT || 8323);
const PAGE_URL = `http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html`;

const ANCHOR_MAX_PX = 40;          // N · vara del anclaje (placeInspector usa un gap de 30px)
const BAR_EXPECTED = ["homeBtn", "salaBtn", "metaBtn"];
// [identidad visual 6/6] "manualBtn" salió de la lista: no está relegado al ⋯, directamente NO
// EXISTE (murió el Modo técnico). Listarlo acá daba verde por ausencia — el verde más barato y
// más mentiroso que hay.
const RELEGADOS = ["mineBtn", "saveBtn", "equipBtn", "byoBtn", "codeBtn", "cuartoThemeBtn", "copBtn"];

const fails = [];
const ok = (c, label, extra) => {
  console.log(`  ${c ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`);
  if (!c) fails.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], {
  cwd: DESIGN_DIR, stdio: "ignore",
});
const shutdown = () => { try { server.kill("SIGKILL"); } catch (e) {} };
process.on("exit", shutdown); process.on("SIGINT", () => { shutdown(); process.exit(130); });
await sleep(900);

// PREFLIGHT · fallo visible, jamás mudo: si el puerto lo ocupa OTRO servicio, mis requests se irían
// contra una app ajena y las varas darían verde/rojo sobre el archivo equivocado. Se aborta acá.
{
  let body = "", status = 0;
  try { const r = await fetch(PAGE_URL); status = r.status; body = await r.text(); }
  catch (e) { console.error(`✗ PREFLIGHT :${PORT} — no responde: ${e.message}`); shutdown(); process.exit(2); }
  if (status !== 200 || !/id="topright"/.test(body)) {
    console.error(`✗ PREFLIGHT :${PORT} — ese puerto NO está sirviendo mi Cuarto (status=${status}).`);
    console.error(`  Lo ocupa otro proceso. Elegí otro con FRONT_PORT=… (no mates sesiones ajenas).`);
    shutdown(); process.exit(2);
  }
  console.log(`preflight :${PORT} · sirviendo mi worktree ✓`);
}

async function settle(page, frames = 3) {
  await page.evaluate((n) => new Promise((res) => {
    let i = 0; const step = () => (++i >= n ? res() : requestAnimationFrame(step));
    requestAnimationFrame(step);
  }), frames);
}

/** El inspector ENTRA con una transición CSS (~300ms). Medir durante el deslizamiento da un gap
 *  falso: la posición anclada ya está escrita en style.left desde el frame 0, pero el rect pintado
 *  todavía viaja. Se espera a que el rect se quede quieto (3 frames iguales) antes de medir. */
async function waitAnchorStable(page, limit = 1600) {
  await page.evaluate((ms) => new Promise((res) => {
    const insp = document.getElementById("inspector");
    if (!insp) return res();
    let last = -1, same = 0; const t0 = performance.now();
    const tick = () => {
      const l = Math.round(insp.getBoundingClientRect().left);
      if (l === last) { if (++same >= 3) return res(); } else { same = 0; last = l; }
      if (performance.now() - t0 > ms) return res();
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }), limit);
}

/** mide el closet abierto contra el sprite de `id` (px de página) */
async function anchorGap(page, id) {
  return page.evaluate((pid) => {
    const insp = document.getElementById("inspector");
    const cvEl = document.getElementById("cuarto");
    if (!insp || !cvEl || !window.__cuarto) return { err: "sin montar" };
    const p = window.__cuarto.artScreenOf(pid);
    if (!p) return { err: "artScreenOf null" };
    const cv = cvEl.getBoundingClientRect(), r = insp.getBoundingClientRect();
    const sx = cv.left + p.x;
    return {
      anchored: insp.dataset.anchored,
      open: insp.classList.contains("open"),
      loop: !!(window.__anchorLoop && window.__anchorLoop()),
      gap: Math.round(Math.min(Math.abs(r.left - sx), Math.abs(r.right - sx))),
      w: Math.round(r.width),
    };
  }, id);
}

async function runOne(browserType, name, viewport, vpName) {
  const tag = `${name}/${vpName}`;
  console.log(`\n── ${tag} ${"─".repeat(Math.max(0, 46 - tag.length))}`);
  const browser = await browserType.launch();
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  await context.addInitScript(() => {
    try { localStorage.setItem("aleph-lang", "es"); localStorage.setItem("aleph-theme", "dark"); } catch (e) {}
  });
  // /v1 stubbeado: la capa de experiencia no depende del backend para estas varas.
  // EXCEPCIÓN: /v1/atoms/catalog devuelve un catálogo MÍNIMO real, porque rehidratar una receta pasa
  // por Projection.recipeToCanvas(recipe, ATOMS.list) — con el catálogo vacío no hay nada que
  // reconstruir. Es la misma dependencia que ya tiene loadPuppet: sin catálogo, un agente guardado
  // tampoco vuelve. Sin este stub la vara del autoguardado mediría el vacío, no la persistencia.
  await context.route("**/v1/atoms/catalog*", (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ total: 2, atoms: [
      { key: "auto_a", id: "auto_a", label: "Pieza A", atom: "tool", zone: "mesa", category: "process", server: "verifA", tools: [] },
      { key: "auto_b", id: "auto_b", label: "Pieza B", atom: "tool", zone: "fuentes", category: "read", server: "verifB", tools: [] },
    ] }),
  }));
  await context.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  const page = await context.newPage();
  const cerr = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) cerr.push(m.text()); });
  page.on("pageerror", (e) => cerr.push(String(e)));

  await page.goto(PAGE_URL, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!(window.__cuarto && window.__cuarto.nucleoData), null, { timeout: 20000 });
  await settle(page, 4);

  // ── A · BARRA DE 3 ────────────────────────────────────────────────────────
  const bar = await page.evaluate(() => {
    const tr = document.getElementById("topright");
    const isVis = (el) => {
      const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none" && cs.opacity !== "0";
    };
    const vis = [...tr.querySelectorAll(":scope > .tbgroup > .pill")].filter(isVis).map((e) => e.id);
    const menu = document.getElementById("metaMenu");
    const inMenu = [...menu.querySelectorAll("[id]")].map((e) => e.id);
    const fams = [...menu.querySelectorAll(".mfam")].map((f) => ({
      h: (f.querySelector(".mfam-h")?.textContent || "").trim(),
      n: f.querySelectorAll(".pill").length,
    }));
    return { vis, inMenu, fams, menuHidden: menu.hidden };
  });
  ok(bar.vis.length === 3, `${tag} · barra: exactamente 3 controles visibles`, `vis=[${bar.vis}]`);
  ok(BAR_EXPECTED.every((id) => bar.vis.includes(id)), `${tag} · barra: son ← Salir · ▶ Run · ⋯`, `esperado=[${BAR_EXPECTED}]`);
  const faltan = RELEGADOS.filter((id) => !bar.inMenu.includes(id));
  ok(faltan.length === 0, `${tag} · cero pérdida: los 8 relegados viven en el ⋯`, faltan.length ? `faltan=[${faltan}]` : `${RELEGADOS.length}/8`);
  ok(bar.fams.length >= 4 && bar.fams.every((f) => f.h), `${tag} · el ⋯ agrupa por FAMILIAS (no lista plana)`,
     bar.fams.map((f) => `${f.h}:${f.n}`).join(" · "));
  ok(bar.menuHidden === true, `${tag} · el ⋯ arranca COLAPSADO`);

  // ── B · POPUP DEL NÚCLEO, anclado en 3 posiciones de cámara ───────────────
  await page.evaluate(() => window.__openInspector(window.__cuarto.nucleoData()));
  await waitAnchorStable(page);
  // §8.3 · un closet ABIERTO tampoco puede cubrir interacción (a anchos angostos aterrizaba encima
  // de los controles del diorama y los volvía inclickeables).
  const tapa = await page.evaluate(() => {
    const insp = document.getElementById("inspector").getBoundingClientRect();
    return ["cam", "topright", "runbar", "legend"].map((id) => {
      const el = document.getElementById(id); if (!el || el.hidden) return null;
      const r = el.getBoundingClientRect(); if (!(r.width > 0 && r.height > 0)) return null;
      const ov = Math.max(0, Math.min(insp.right, r.right) - Math.max(insp.left, r.left)) *
                 Math.max(0, Math.min(insp.bottom, r.bottom) - Math.max(insp.top, r.top));
      return ov > 4 ? `${id}=${Math.round(ov)}px²` : null;
    }).filter(Boolean);
  });
  ok(tapa.length === 0, `${tag} · el closet abierto NO tapa controles`, tapa.join(" · ") || "limpio");

  // los controles de cámara viven ANIDADOS (item 4): el camino real del usuario es abrirlos primero.
  await page.click("#camToggle");
  await settle(page, 2);
  const posiciones = [
    ["reposo", null],
    ["zoom ＋", "zin"],
    ["rotar ⟲", "rotl"],
    ["encuadrar ⊙", "creset"],
  ];
  for (const [etiqueta, btn] of posiciones) {
    if (btn) { await page.click(`#${btn}`); await settle(page, 6); await waitAnchorStable(page, 600); }
    const m = await anchorGap(page, "nucleo");
    if (m.err) { ok(false, `${tag} · Núcleo anclado @ ${etiqueta}`, m.err); continue; }
    ok(m.anchored === "1" && m.gap <= ANCHOR_MAX_PX,
       `${tag} · Núcleo anclado @ ${etiqueta}`, `gap=${m.gap}px (≤${ANCHOR_MAX_PX}) anchored=${m.anchored} loop=${m.loop}`);
  }

  // paridad con una PIEZA real (el patrón que el Núcleo debía igualar)
  const piezaOk = await page.evaluate(() => {
    try {
      const t = { id: "verif_pieza", label: "Pieza de verificación", atom: "tool", role: "mesa", server: "verif" };
      window.__cuarto.placeTile(t); return true;
    } catch (e) { return String(e && e.message || e); }
  });
  if (piezaOk === true) {
    await settle(page, 4);
    await page.evaluate(() => window.__openInspector(window.__cuarto.pieceData("verif_pieza")));
    await waitAnchorStable(page);
    const m = await anchorGap(page, "verif_pieza");
    ok(!m.err && m.anchored === "1" && m.gap <= ANCHOR_MAX_PX,
       `${tag} · paridad: la PIEZA usa el mismo ancla`, m.err || `gap=${m.gap}px`);
  } else {
    ok(false, `${tag} · paridad: la PIEZA usa el mismo ancla`, `no pude colocar la pieza: ${piezaOk}`);
  }

  // ── C · WIDGETS COLAPSADOS POR DEFAULT (items 3·4·5) ──────────────────────
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!(window.__cuarto && window.__cuarto.nucleoData), null, { timeout: 20000 });
  await settle(page, 4);
  const w = await page.evaluate(() => {
    const vis = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
    };
    const leg = document.getElementById("legend"), cam = document.getElementById("cam");
    return {
      legOpen: leg.dataset.open, legBodyVis: vis(document.getElementById("legBody")),
      legChipVis: vis(document.getElementById("legToggle")),
      camOpen: cam.dataset.open, camBodyVis: vis(document.getElementById("camBody")),
      camToggleVis: vis(document.getElementById("camToggle")),
      lensSuelta: !!document.getElementById("lenswrap"),
      lensDentroDeCam: !!cam.querySelector("#lensBtn"),
      // controles del diorama que deben seguir EXISTIENDO (cero pérdida), aunque anidados
      controles: ["zin", "zout", "rotl", "rotr", "creset", "lensBtn"].filter((id) => cam.querySelector("#" + id)).length,
    };
  });
  if (process.env.SHOT) {
    const dir = process.env.SHOT_DIR || ".";
    await page.screenshot({ path: `${dir}/cuarto-limpio-${name}-${vpName}-reposo.png` });
    await page.evaluate(() => document.getElementById("metaBtn").click());
    await settle(page, 2);
    await page.screenshot({ path: `${dir}/cuarto-limpio-${name}-${vpName}-menu.png` });
    await page.evaluate(() => document.getElementById("metaBtn").click());
    await settle(page, 2);
  }
  ok(w.legOpen === "0" && !w.legBodyVis && w.legChipVis, `${tag} · "Las piezas" arranca COLAPSADO (chip visible)`);
  ok(w.camOpen === "0" && !w.camBodyVis && w.camToggleVis, `${tag} · controles del diorama colapsados a UN botón`);
  ok(!w.lensSuelta && w.lensDentroDeCam, `${tag} · FLOW anidado en los controles (no flota suelto)`);
  ok(w.controles === 6, `${tag} · cero pérdida: los 6 controles siguen ahí`, `${w.controles}/6`);

  // se abren, y se abren de verdad
  await page.click("#legToggle"); await page.click("#camToggle"); await settle(page, 3);
  const w2 = await page.evaluate(() => ({
    leg: document.getElementById("legend").dataset.open,
    legBody: !document.getElementById("legBody").hidden,
    cam: document.getElementById("cam").dataset.open,
    camBody: !document.getElementById("camBody").hidden,
  }));
  ok(w2.leg === "1" && w2.legBody && w2.cam === "1" && w2.camBody, `${tag} · ambos widgets ABREN al tocarlos`);

  // el ＋ Equipar despliega "Las piezas" (item 3: "se abre con el +")
  await page.click("#legToggle"); await settle(page, 2);          // volver a cerrar
  await page.evaluate(() => { document.getElementById("metaBtn").click(); document.getElementById("equipBtn").click(); });
  await settle(page, 3);
  const w3 = await page.evaluate(() => document.getElementById("legend").dataset.open);
  ok(w3 === "1", `${tag} · el ＋ Equipar despliega "Las piezas"`);

  // ── E · GLOSARIO ≠ CLOSET (item 6) ────────────────────────────────────────
  // la puerta MCP del decorado no opera nada: debe abrir la TIPCARD (liviana, sin acciones), no el
  // closet de una pieza real. Y la leyenda de formas salió del diorama al "?" del ⋯.
  const glos = await page.evaluate(() => {
    const doorData = { atom: "conexion", id: "mcp_door", label: "Conexión (MCP)", role: "fuentes",
                       connector: null, hint: "Puerta + llave: conecta una app y caen sus tools." };
    window.__openInspector(doorData);
    const tip = document.getElementById("tipcard"), insp = document.getElementById("inspector");
    const cs = tip ? getComputedStyle(tip) : null;
    return {
      tipAbierta: tip && !tip.hidden,
      closetCerrado: insp && !insp.classList.contains("open"),
      tipAnclada: tip && tip.dataset.anchored,
      // estilo VISUALMENTE distinto del closet: borde punteado y sin la sombra del panel
      bordeDistinto: cs && /dashed/.test(cs.borderStyle || cs.borderTopStyle || ""),
      sinSombraDePanel: cs && (cs.boxShadow === "none" || cs.boxShadow === ""),
      // CERO botones de acción: sólo cerrar + los dos links de ayuda
      botones: tip ? [...tip.querySelectorAll("button")].map((b) => b.id) : [],
      // el glosario NO cuelga del panel de piezas y vive detrás del "?" del ⋯
      legKeyMuerto: !document.getElementById("legKey"),
      glosarioExiste: !!document.getElementById("glosario"),
      glosarioOculto: document.getElementById("glosario").hidden,
      glosBtnEnMenu: !!document.getElementById("metaMenu").querySelector("#glosarioBtn"),
    };
  });
  ok(glos.tipAbierta && glos.closetCerrado, `${tag} · una forma del decorado abre TIPCARD, no el closet`);
  // [REESCRITO · reforma·f] la PUERTA MCP del decorado se fue con la silueta de puerta: era un
  // objeto clickeable que sólo enseñaba una metáfora ya muerta ("puerta + llave"). Sin sprite,
  // su tipcard cae al rincón — que es el comportamiento CORRECTO y declarado de anchorTo para
  // un sujeto sin posición. La ley del ancla se mide donde hay algo a lo que anclarse: una
  // pieza REAL, con la MISMA función (mismo anchorTo, mismo bucle por frame).
  ok(glos.tipAnclada === "0", `${tag} · sin sprite, la tipcard cae al rincón (y lo declara)`, glos.tipAnclada);
  const tipReal = await page.evaluate(async () => {
    if (!window.__cuarto.pieceData("verif_tip"))
      window.__cuarto.placeTile({ id: "verif_tip", label: "Forma de prueba", atom: "tool", role: "mesa", server: "verif" });
    await new Promise((r) => setTimeout(r, 260));
    window.__openTip({ id: "verif_tip", label: "Forma de prueba", hint: "forma de prueba" });
    await new Promise((r) => setTimeout(r, 260));
    const t = document.getElementById("tipcard");
    return { anclada: t.dataset.anchored, left: t.style.left, loop: window.__anchorLoop() };
  });
  ok(tipReal.anclada === "1" && !!tipReal.left && tipReal.loop,
     `${tag} · sobre una pieza REAL la tipcard usa el mismo ancla que el closet`, `left=${tipReal.left}`);
  ok(glos.bordeDistinto && glos.sinSombraDePanel, `${tag} · la tipcard se VE distinta del closet`,
     `dashed=${glos.bordeDistinto} sinSombra=${glos.sinSombraDePanel}`);
  ok(glos.botones.length === 3 && glos.botones.every((id) => ["tipClose", "tipAsk", "tipGloss"].includes(id)),
     `${tag} · tipcard sin botones de acción (sólo cerrar/ayuda)`, `[${glos.botones}]`);
  ok(glos.legKeyMuerto && glos.glosarioExiste && glos.glosarioOculto && glos.glosBtnEnMenu,
     `${tag} · el glosario salió del diorama al "?" del ⋯`);

  // el "?" lo abre de verdad, y el glosario explica sin operar
  await page.evaluate(() => { document.getElementById("metaBtn").click(); document.getElementById("glosarioBtn").click(); });
  await settle(page, 3);
  const g2 = await page.evaluate(() => {
    const g = document.getElementById("glosario");
    return { abierto: !g.hidden, formas: g.querySelectorAll(".row").length,
             acciones: [...g.querySelectorAll("button")].map((b) => b.id) };
  });
  ok(g2.abierto && g2.formas === 8, `${tag} · el "?" abre el glosario con las 8 formas`, `filas=${g2.formas}`);
  ok(g2.acciones.every((id) => ["glosClose", "glosAsk"].includes(id)), `${tag} · el glosario no opera nada`, `[${g2.acciones}]`);

  // ── D · CERO FLOTANTE SOBRE CONTROLES (§8.3 regla de capas) ───────────────
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!(window.__cuarto && window.__cuarto.nucleoData), null, { timeout: 20000 });
  await settle(page, 5);
  const medirSolapes = () => page.evaluate(() => {
    const CTRL = ["topright", "cam", "runbar", "legend"];
    const box = (id) => {
      const el = document.getElementById(id); if (!el || el.hidden) return null;
      const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      if (!(r.width > 0 && r.height > 0) || cs.visibility === "hidden" || cs.display === "none") return null;
      return { id, r };
    };
    const ctrls = CTRL.map(box).filter(Boolean);
    const flotantes = [...document.querySelectorAll(".float, #copilot, #byoOverlay, #mineOverlay, #palette")]
      .map((el) => el.id).filter((id) => id && !CTRL.includes(id)).map(box).filter(Boolean);
    const hits = [];
    for (const f of flotantes) for (const c of ctrls) {
      const ov = Math.max(0, Math.min(f.r.right, c.r.right) - Math.max(f.r.left, c.r.left)) *
                 Math.max(0, Math.min(f.r.bottom, c.r.bottom) - Math.max(f.r.top, c.r.top));
      if (ov > 4) hits.push(`${f.id}×${c.id}=${Math.round(ov)}px²`);
    }
    return hits;
  });
  const solapes = await medirSolapes();
  ok(solapes.length === 0, `${tag} · cero flotante sobre controles en reposo`, solapes.slice(0, 3).join(" · ") || "limpio");

  // …y con el ⋯ ABIERTO: con 4 familias el menú es alto y llegaba justo encima del ⊙ de la cámara.
  await page.click("#metaBtn"); await settle(page, 3);
  const solapesMenu = await page.evaluate(() => {
    const menu = document.getElementById("metaMenu").getBoundingClientRect();
    return ["cam", "runbar", "legend"].map((id) => {
      const el = document.getElementById(id); if (!el || el.hidden) return null;
      const r = el.getBoundingClientRect(); if (!(r.width > 0 && r.height > 0)) return null;
      const ov = Math.max(0, Math.min(menu.right, r.right) - Math.max(menu.left, r.left)) *
                 Math.max(0, Math.min(menu.bottom, r.bottom) - Math.max(menu.top, r.top));
      return ov > 4 ? `${id}=${Math.round(ov)}px²` : null;
    }).filter(Boolean);
  });
  ok(solapesMenu.length === 0, `${tag} · el menú ⋯ abierto no tapa controles`, solapesMenu.join(" · ") || "limpio");
  await page.click("#metaBtn"); await settle(page, 2);

  // ── H · AUTOGUARDADO (item 8) ─────────────────────────────────────────────
  // La vara literal de la orden: cambio → relanzar → persiste · [Descartar] vuelve al último guardado.
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!(window.__cuarto && window.__autoguardar), null, { timeout: 20000 });
  await settle(page, 4);
  // estado de partida limpio (este slot es "nuevo": sin ?puppet)
  await page.evaluate(() => { try { Object.keys(localStorage).filter((k) => k.startsWith("aleph:cuarto:")).forEach((k) => localStorage.removeItem(k)); } catch (e) {} });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!(window.__cuarto && window.__autoguardar), null, { timeout: 20000 });
  await settle(page, 4);

  // un CAMBIO real: dos piezas colocadas por el mismo camino que usa el producto
  await page.evaluate(() => {
    window.__cuarto.placeTile({ id: "auto_a", key: "auto_a", label: "Pieza A", atom: "tool", role: "mesa", server: "verifA" });
    window.__cuarto.placeTile({ id: "auto_b", key: "auto_b", label: "Pieza B", atom: "tool", role: "fuentes", server: "verifB" });
    window.__sync();
  });
  await page.waitForFunction(() => !!window.__draft, null, { timeout: 5000 }).catch(() => {});
  const guardado = await page.evaluate(() => ({
    draft: !!window.__draft,
    piezas: (window.__draft && window.__draft.recipe && window.__draft.recipe.canvas
             && window.__draft.recipe.canvas.layout || []).length,
    indicador: (document.getElementById("savestate").textContent || "").trim(),
    enDisco: !!localStorage.getItem("aleph:cuarto:draft:nuevo"),
  }));
  ok(guardado.draft && guardado.enDisco, `${tag} · autoguardado escribió el borrador local (silencioso)`);
  ok(/guardado|saved/i.test(guardado.indicador), `${tag} · indicador discreto "guardado hace X"`, `"${guardado.indicador}"`);

  // RELANZAR: la persistencia se prueba recargando de cero, no leyendo la variable en memoria
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!(window.__cuarto && window.__autoguardar), null, { timeout: 20000 });
  await page.waitForFunction(() => window.__cuarto.placedTiles().length > 0, null, { timeout: 8000 }).catch(() => {});
  await settle(page, 4);
  const tras = await page.evaluate(() => ({
    ids: window.__cuarto.placedTiles().map((t) => t.id).sort(),
    indicador: (document.getElementById("savestate").textContent || "").trim(),
  }));
  ok(tras.ids.join(",") === "auto_a,auto_b", `${tag} · cambio → relanzar → PERSISTE`, `[${tras.ids}]`);
  ok(/guardado|saved/i.test(tras.indicador), `${tag} · el indicador sobrevive el relanzamiento`, `"${tras.indicador}"`);

  // [Descartar cambios] vuelve al último estado guardado (acá: el vacío con el que arrancó el slot)
  await page.evaluate(() => { document.getElementById("metaBtn").click(); document.getElementById("discardBtn").click(); });
  await settle(page, 4);
  const desc = await page.evaluate(() => ({
    piezas: window.__cuarto.placedTiles().length,
    draftBorrado: !localStorage.getItem("aleph:cuarto:draft:nuevo"),
  }));
  ok(desc.piezas === 0 && desc.draftBorrado, `${tag} · [Descartar] vuelve al último guardado`, `piezas=${desc.piezas}`);

  // …y no vuelve a "resucitar" al recargar (descartar es de verdad)
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!(window.__cuarto && window.__autoguardar), null, { timeout: 20000 });
  await settle(page, 5);
  ok(await page.evaluate(() => window.__cuarto.placedTiles().length === 0),
     `${tag} · lo descartado no resucita al relanzar`);

  // el diálogo al salir es la EXCEPCIÓN, no la regla
  const salida = await page.evaluate(() => {
    const antes = window.__salidaPregunta();                        // cuarto vacío → no pregunta
    window.__cuarto.placeTile({ id: "auto_c", key: "auto_c", label: "Pieza C", atom: "tool", role: "mesa", server: "verifC" });
    window.__sync();
    const sinNombre = window.__salidaPregunta();                    // piezas + sin nombre → pregunta
    window.__cuarto.nucleoData().name = "Mi agente";
    const conNombre = window.__salidaPregunta();                    // con nombre → no pregunta
    return { antes, sinNombre, conNombre };
  });
  ok(salida.antes === false && salida.sinNombre === true && salida.conNombre === false,
     `${tag} · pregunta al salir SÓLO lo que el autoguardado no resuelve`, JSON.stringify(salida));

  // ── F · INSPECCIÓN EN SECCIÓN PROPIA (item 7) ─────────────────────────────
  const insp7 = await page.evaluate(() => ({
    modalMuerto: !document.getElementById("byoOverlay"),
    // el overlay de "Mis agentes" comparte el lenguaje visual .byo — NO debe haberse ido con el modal
    mineVive: !!document.getElementById("mineOverlay"),
    entradaExiste: !!document.getElementById("byoBtn"),
    // ningún resto del modal en el DOM
    camposHuerfanos: ["byoUrl", "byoSubmit", "byoTransport", "byoCatList", "byoFgForma"]
      .filter((id) => !!document.getElementById(id)),
  }));
  ok(insp7.modalMuerto && insp7.camposHuerfanos.length === 0,
     `${tag} · el modal de inspección ya NO vive sobre el diorama`, `restos=[${insp7.camposHuerfanos}]`);
  ok(insp7.mineVive, `${tag} · "Mis agentes" sigue vivo (comparte el CSS .byo)`);
  ok(insp7.entradaExiste, `${tag} · la entrada ＋ Tu MCP sigue existiendo (cero pérdida)`);

  // ＋ Tu MCP navega a la pantalla propia (la pantalla en sí se carga y verifica abajo)
  ok(await page.evaluate(() => typeof document.getElementById("byoBtn").onclick === "function"),
     `${tag} · ＋ Tu MCP tiene handler de navegación`);

  ok(cerr.length === 0, `${tag} · sin errores JS nuevos`, cerr.length ? cerr.slice(0, 2).join(" | ") : "limpio");

  // ── G · LA PANTALLA DE INSPECCIÓN ARRANCA Y ES REAL ───────────────────────
  const perr = [];
  const p2 = await context.newPage();
  p2.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) perr.push(m.text()); });
  p2.on("pageerror", (e) => perr.push(String(e)));
  await p2.goto(`http://127.0.0.1:${PORT}/inspeccion/inspeccion.html`, { waitUntil: "domcontentloaded" });
  await p2.waitForFunction(() => !!document.getElementById("go"), null, { timeout: 15000 }).catch(() => {});
  const pant = await p2.evaluate(() => {
    const seg = [...document.querySelectorAll("#transporte button")].map((b) => b.dataset.v);
    return {
      transportes: seg,
      arsenal: !!document.getElementById("arsList"),
      submit: !!document.getElementById("go"),
      // los campos del modal viajaron completos (los 3 caminos)
      http: !!document.getElementById("fUrl"), stdio: !!document.getElementById("fCmd"),
      forge: !!document.getElementById("fFgUrl") && !!document.getElementById("fForma"),
      login: !!document.getElementById("fCreds"),
      log: !!document.getElementById("log"),
      navTieneEntrada: /Inspecci/i.test(document.body.textContent || ""),
    };
  });
  ok(pant.transportes.join(",") === "http,stdio,forge", `${tag} · la pantalla tiene los 3 transportes`, `[${pant.transportes}]`);
  ok(pant.http && pant.stdio && pant.forge && pant.login, `${tag} · los campos del modal viajaron completos`);
  ok(pant.arsenal && pant.submit && pant.log, `${tag} · la pantalla tiene arsenal, submit y log del Motor B`);
  // el handoff por query (?forma=login) preselecciona, como hacía el modal
  await p2.goto(`http://127.0.0.1:${PORT}/inspeccion/inspeccion.html?forma=login&url=https://api.x.dev`, { waitUntil: "domcontentloaded" });
  await settle(p2, 3);
  const hand = await p2.evaluate(() => ({
    modo: [...document.querySelectorAll("#transporte button")].find((b) => b.classList.contains("on"))?.dataset.v,
    forma: document.getElementById("fForma").value,
    url: document.getElementById("fFgUrl").value,
    loginVisible: !document.getElementById("wrapLogin").hidden,
  }));
  ok(hand.modo === "forge" && hand.forma === "login" && hand.url === "https://api.x.dev" && hand.loginVisible,
     `${tag} · el handoff ?forma=&url= preselecciona`, JSON.stringify(hand));
  ok(perr.length === 0, `${tag} · la pantalla de Inspección sin errores JS`, perr.slice(0, 2).join(" | ") || "limpio");
  await p2.close();

  await browser.close();
}

for (const [type, name] of [[chromium, "chromium"], [webkit, "webkit"]]) {
  for (const [vp, vpName] of [[{ width: 1440, height: 900 }, "wide"], [{ width: 1120, height: 780 }, "narrow"]]) {
    try { await runOne(type, name, vp, vpName); }
    catch (e) { ok(false, `${name}/${vpName} · la corrida se cayó`, String(e && e.message || e).slice(0, 160)); }
  }
}

shutdown();
console.log(`\n${fails.length ? "✗" : "✓"} CUARTO LIMPIO · ${fails.length} fallo(s)`);
if (fails.length) { fails.forEach((f) => console.log(`   · ${f}`)); process.exit(1); }
process.exit(0);
