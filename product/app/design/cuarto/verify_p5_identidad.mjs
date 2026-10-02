/* verify_p5_identidad.mjs — FIX-P5 · IDENTIDAD ÚNICA POR PIEZA.
 *
 * EL BUG (caminata): "Cad", "Cad", "Freecad" — piezas con el mismo logo y casi el mismo
 * nombre en el diorama; adivinanza pura sobre cuál equipar o cuál está rota.
 *
 * LO QUE SE MIDE, contra el CATÁLOGO REAL (los 54 átomos que el backend surfacea de los
 * belts, reconstruidos con la MISMA regla de de-dup de atoms_router.collect_atoms):
 *   (1) la receta de la caminata carga y las piezas CAD se distinguen a simple vista
 *   (2) ASSERT DURO: CERO pares de labels idénticos en el diorama
 *   (3) labels = NOMBRE DE SERVICIO (ley 7-jul), cero descripciones en español
 *   (4) el detalle completo vive un clic adentro (server + origen + qué la distingue)
 *   (5) el flujo de equipar YA NO permite duplicar (se intenta equipar dos veces)
 *   (6) ES/EN lockstep: el nombre propio no se traduce
 *   (7) la lista de piezas dice lo MISMO que el diorama
 *   (8) 0 errores JS
 *
 * Puerto :8275. Run: node verify_p5_identidad.mjs
 */
import { chromium, webkit } from "playwright";
import { spawn } from "node:child_process";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { readdirSync, readFileSync } from "node:fs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const REPO = join(HERE, "..", "..", "..", "..");
// El puerto es de la SESIÓN, no de la vara: cada integración corre en el suyo (:25374 es la
// .app de persona usuaria y jamás se toca). 8275 queda de default por compatibilidad con P5.
const PORT = Number(process.env.PORT || 8275);
if (PORT === 25374) { console.error("✗ :25374 es la .app de persona usuaria — jamás."); process.exit(2); }
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const fails = [];
let motor = "";
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`); if (!c) fails.push(`${motor} · ${label}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// descripciones en español que JAMÁS deben aparecer como etiqueta del diorama (ley 7-jul)
const SPANISH = /Modelado|Simulacion|Simulación|Consulta|Análisis|Analisis|Borradores|correo|parametrico|paramétrico|Cotizaciones|Backtest de|Datos de mercado|Esquematicos|Propiedades de/;

/** El catálogo REAL: misma regla que product/backend/app/phase1/atoms_router.collect_atoms
 *  (de-dup por backed_by + tools; sólo cards cuyo backed_by existe en mcpServers). */
function atomsReales() {
  const ZONE = { apps: "mesa", mundo: "fuentes", datos: "fuentes", archivos: "mesa", saberes: "fuentes" };
  const dir = join(REPO, "catalog", "templates");
  const seen = new Set(); const out = [];
  for (const sub of readdirSync(dir, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name).sort()) {
    for (const f of readdirSync(join(dir, sub)).filter((f) => f.endsWith(".mcp.json")).sort()) {
      const p = join(dir, sub, f);
      let belt; try { belt = JSON.parse(readFileSync(p, "utf8")); } catch { continue; }
      const servers = belt.mcpServers || {};
      for (const c of ((belt._meta || {}).cards) || []) {
        const backed = c.backed_by;
        if (!backed || !(backed in servers)) continue;           // cero theater
        const tools = c.tools || [];
        const k = backed + "::" + tools.slice().sort().join(",");
        if (seen.has(k)) continue; seen.add(k);
        const auth = c.auth || "keyless";
        out.push({ id: c.id, label: c.label, sub: c.sub, atom: auth !== "keyless" ? "conexion" : "tool",
          zone: ZONE[c.armario] || "mesa", server: backed, tools, belt_ref: `catalog/templates/${sub}/${f}`,
          auth, connector: c.connector || null, armario: c.armario || null, state: "ready",
          criticality: c.criticality || "low" });
      }
    }
  }
  return out;
}
const ATOMS = atomsReales();

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(800);
// GUARDA DE PUERTO: :8275 no se libera al instante entre varas (la anterior deja el socket
// colgando) y el http.server nuevo falla al bindear EN SILENCIO → la página carga vacía y la
// vara da ROJO por un motivo que no es el producto. Se espera a que SIRVA de verdad, y si no
// sirve se dice, en vez de medir la nada.
{
  let vivo = false;
  for (let i = 0; i < 25 && !vivo; i++) {
    try { const r = await fetch(PAGE, { method: "GET" }); vivo = r.ok; } catch (e) {}
    if (!vivo) await sleep(400);
  }
  if (!vivo) { console.error(`FALTA: :${PORT} no sirve ${PAGE} — ¿otra vara todavía lo tiene?`); server.kill(); process.exit(2); }
}
// WEBKIT es el motor de la .app (WKWebView); chromium queda como control. Se corren los DOS:
// un verde sólo en chromium no dice nada sobre lo que persona usuaria ve en el escritorio.
const ENGINES = [["webkit", webkit], ["chromium", chromium]];
for (const [_motor, tipo] of ENGINES) {
motor = _motor;
console.log(`\n──────── motor: ${motor} ────────`);
const browser = await tipo.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1 });
  await ctx.addInitScript(() => { try { localStorage.setItem("aleph-lang", "es"); localStorage.setItem("aleph-theme", "dark"); } catch (e) {} });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  // ORDEN: la genérica PRIMERO — playwright da prioridad a la ÚLTIMA route registrada.
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/v1/atoms/catalog*", (r) => r.fulfill({ status: 200, contentType: "application/json",
    body: JSON.stringify({ atoms: ATOMS, total: ATOMS.length }) }));
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__cuarto.dioramaLabels, null, { timeout: 15000 });
  await sleep(1200);

  ok(ATOMS.length > 40, `(0) catálogo REAL cargado desde los belts`, `${ATOMS.length} átomos`);

  // ── LA RECETA DE LA CAMINATA: las piezas CAD, tal como salen del catálogo plegado ──
  const cad = await page.evaluate(() => {
    const C = window.__cuarto, cc = window.CuartoCatalogo;
    const folded = cc.foldAtomsToMcp((window.__atoms && window.__atoms.list) || []);
    const out = [];
    folded.filter((e) => /^(freecad|cad|fem|kicad)$/.test(e.server || "")).forEach((e) => {
      const t = { id: e.id, key: e.key, label: e.label, server: e.server, ref: e.server, category: e.category,
                  atom: e.atom, tools: e.tools, belt_ref: e.belt_ref, cards: e.cards, cardCount: e.cardCount };
      if (C.placeTile(t)) out.push({ server: e.server, id: t.id, label: C.pieceLabelText(t.id),
                                     detalle: C.pieceDetalle(t.id) });
    });
    window.__renderPieces && window.__renderPieces();
    return out;
  });
  console.log("\n  piezas CAD en el piso:");
  cad.forEach((c) => console.log(`    server=${String(c.server).padEnd(8)} → "${c.label}"`));
  ok(cad.length >= 3, "(1) la receta de la caminata carga las piezas CAD", `${cad.length} piezas`);
  const cadLabels = cad.map((c) => c.label);
  ok(new Set(cadLabels).size === cadLabels.length, "(1b) las piezas CAD se distinguen a simple vista",
     JSON.stringify(cadLabels));
  // EVIDENCIA VISUAL: las etiquetas del diorama sólo se revelan al hover (anti-superposición),
  // así que se las mantiene encendidas con `pulse` mientras se saca la foto — si no, la captura
  // mostraría piezas mudas y no probaría nada.
  const cadIds = cad.map((c) => c.id);
  await page.evaluate((ids) => {
    window.__p5hold = setInterval(() => ids.forEach((i) => window.__cuarto.pulse(i)), 16);
  }, cadIds);
  await sleep(400);
  await page.screenshot({ path: join(HERE, "screenshots", `p5-cad-distinguibles-${motor}.png`) });
  await page.evaluate(() => { clearInterval(window.__p5hold); });

  const elCad = cad.find((c) => c.server === "cad");
  ok(!!elCad && /·/.test(elCad.label || ""), "(1c) 'Cad' (confundible con 'Freecad') gana calificador honesto",
     elCad ? elCad.label : "no está");

  // ── (2) ASSERT DURO · CERO pares de labels idénticos, con TODO el catálogo en el piso ──
  const todo = await page.evaluate(() => {
    const C = window.__cuarto, cc = window.CuartoCatalogo;
    const folded = cc.foldAtomsToMcp((window.__atoms && window.__atoms.list) || []);
    folded.forEach((e) => C.placeTile({ id: e.id, key: e.key, label: e.label, server: e.server, ref: e.server,
      category: e.category, atom: e.atom, tools: e.tools, belt_ref: e.belt_ref, cards: e.cards, cardCount: e.cardCount }));
    window.__renderPieces && window.__renderPieces();
    return C.dioramaLabels();
  });
  const labels = todo.map((x) => x.label);
  const dupes = labels.filter((l, i) => labels.indexOf(l) !== i);
  ok(dupes.length === 0, "(2) CERO pares de labels idénticos en el diorama",
     `${labels.length} piezas · ${new Set(labels).size} labels únicos${dupes.length ? " · DUP: " + JSON.stringify([...new Set(dupes)]) : ""}`);

  // ── (3) labels = NOMBRE DE SERVICIO, cero descripciones en español (ley 7-jul intacta) ──
  const conEspanol = labels.filter((l) => SPANISH.test(l || ""));
  ok(conEspanol.length === 0, "(3) labels = nombre de servicio · cero descripciones en español",
     conEspanol.length ? JSON.stringify(conEspanol.slice(0, 4)) : `${labels.length} labels limpios`);

  // ── (3b) el label es CORTO: el detalle no se derrama al piso ──
  const largos = labels.filter((l) => (l || "").length > 34);
  ok(largos.length === 0, "(3b) el label es corto (≤34) — el detalle vive un clic adentro",
     largos.length ? JSON.stringify(largos.slice(0, 3)) : "todos cortos");

  // ── (4) el DETALLE completo vive un clic adentro ──
  const det = elCad && elCad.detalle;
  ok(!!(det && det.servidor && det.origen && det.distingue && det.porQue),
     "(4) el closet muestra server + origen + qué la distingue",
     det ? `servidor=${det.servidor} · origen=${det.origen} · distingue=${det.distingue}` : "sin detalle");
  const inameTxt = await page.evaluate((id) => {
    window.__openInspector(window.__cuarto.pieceData(id));
    return { name: document.getElementById("iname").textContent, sub: document.getElementById("isub").textContent };
  }, elCad ? elCad.id : "");
  ok(inameTxt.name === (elCad && elCad.label), "(4b) el inspector nombra la pieza con su identidad del diorama",
     JSON.stringify(inameTxt.name));
  ok(/·/.test(inameTxt.sub || ""), "(4c) el sub del inspector dice QUÉ la separa de su homónima", JSON.stringify(inameTxt.sub));

  // ── (5) el flujo de EQUIPAR ya no permite duplicar ──
  const dup = await page.evaluate(() => {
    const C = window.__cuarto;
    const t = { id: "p5-dup", label: "X", server: "freecad", ref: "freecad", category: "process", atom: "tool", tools: ["create_object"] };
    const r1 = C.placeTile(t);
    const r2 = C.placeTile(t);                       // MISMA pieza, segunda vez
    const n = C.dioramaLabels().filter((x) => x.id === "p5-dup").length;
    return { primera: !!r1, segunda: !!r2, enElPiso: n, yaColocada: C.yaColocada("p5-dup") };
  });
  ok(dup.primera && !dup.segunda && dup.enElPiso === 1,
     "(5) equipar la MISMA pieza dos veces ya NO duplica", JSON.stringify(dup));

  // ── (6) ES/EN lockstep — el nombre propio no se traduce ──
  const es = await page.evaluate(() => window.__cuarto.dioramaLabels().map((x) => x.label).join("|"));
  await page.evaluate(() => { try { localStorage.setItem("aleph-lang", "en"); } catch (e) {} });
  await page.evaluate(() => window.__renderPieces && window.__renderPieces());
  await sleep(200);
  const en = await page.evaluate(() => window.__cuarto.dioramaLabels().map((x) => x.label).join("|"));
  ok(es === en, "(6) ES/EN lockstep: el nombre de servicio es idioma-neutral",
     es === en ? "idénticos" : "DIFIEREN");

  /* ── (7) [FIX-P3 · §7] LA LISTA MURIÓ: la identidad se contrasta contra EL PIE DEL ARCO,
   * pieza por pieza. Se ENDURECE de dos maneras:
   *   · antes se comparaban dos CONJUNTOS («¿está este label en alguna fila?»): dos piezas
   *     con los labels cruzados pasaban, porque el conjunto era el mismo. Ahora se compara
   *     POR ID — el arco de la pieza X tiene que decir el label de la pieza X;
   *   · y se abre el arco de verdad, así que un pie que no se pintara sale rojo.
   * Se mide EN EL MISMO INSTANTE que el piso (el piso cambió desde el paso 1: la pieza
   * sintética del paso 5 comparte server con `freecad`, así que ambas ganan calificador — es
   * el sistema funcionando; comparar contra el snapshot viejo mediría una foto caduca). */
  const { pies, dioramaAhora } = await page.evaluate(async () => {
    window.__renderPieces && window.__renderPieces();
    const dio = window.__cuarto.dioramaLabels();
    const pies = {};
    for (const x of dio) {
      try { window.__closeAbanico(); } catch (e) {}
      window.__openAbanico(window.__cuarto.pieceData(x.id));
      await new Promise((r) => setTimeout(r, 50));
      pies[x.id] = ((document.getElementById("abName") || {}).textContent || "").trim();
    }
    try { window.__closeAbanico(); } catch (e) {}
    return { pies, dioramaAhora: dio };
  });
  const desalineadas = dioramaAhora.filter((x) => pies[x.id] !== x.label);
  ok(desalineadas.length === 0, "(7) el arco de CADA pieza dice lo MISMO que su etiqueta del piso",
     desalineadas.length ? JSON.stringify(desalineadas.slice(0, 3).map((x) => `${x.id}: piso='${x.label}' arco='${pies[x.id]}'`))
                         : `${dioramaAhora.length} piezas, ${dioramaAhora.length} arcos, cero desalineadas`);
  const nombres = Object.values(pies);
  const dupLista = nombres.filter((l, i) => nombres.indexOf(l) !== i);
  ok(dupLista.length === 0, "(7b) CERO arcos con el mismo nombre", dupLista.length ? JSON.stringify([...new Set(dupLista)]) : "todos únicos");

  ok(errors.length === 0, "(8) 0 errores JS/render", errors.slice(0, 2).join(" ; "));

  await page.evaluate(() => { const b = document.getElementById("inspector"); if (b) b.classList.remove("open"); });
  await sleep(150);
  await page.screenshot({ path: join(HERE, "screenshots", `p5-identidad-unica-${motor}.png`) });
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push(`${motor} · harness: ${e && e.message ? e.message : String(e)}`);
} finally { await browser.close(); }
}
server.kill();

console.log("");
if (fails.length === 0) { console.log("RESULTADO: VERDE — identidad única por pieza (cero labels gemelos · calificador honesto · dedupe al equipar · detalle un clic adentro)"); process.exit(0); }
console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); process.exit(1);
