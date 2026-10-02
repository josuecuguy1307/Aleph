/* verify_labels.mjs — la etiqueta del diorama es el NOMBRE DEL SERVICIO (como el reel), no la
 * descripción en español del card. server/backed_by titleizado: freecad→"Freecad",
 * openfoam→"Openfoam", dicom→"Dicom", forged-zapier→"Forged Zapier". Piezas sin server (Memoria)
 * caen a su label. Cero descripciones en español en canvas / lista / inspector.
 * Puerto :8160. Coloca piezas sintéticas con label ESPAÑOL + server real → prueba que gana el server.
 * Run: node verify_labels.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = 8160;
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`); if (!c) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SPANISH = /Modelado|Simulacion|Simulación|Consulta|Análisis|Analisis|Borradores|correo|parametrico|paramétrico|Cotizaciones|Backtest de|Datos de mercado/;

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);
const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1 });
  await context.addInitScript(() => { try { localStorage.setItem("aleph-lang", "en"); localStorage.setItem("aleph-theme", "dark"); } catch (e) {} });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__renderPieces && window.__cuarto.svcName, null, { timeout: 12000 });

  // piezas estilo-catálogo: label ESPAÑOL (como hoy) + server real → debe ganar el server.
  const PIECES = [
    { id: "p-freecad", label: "Modelado CAD parametrico (FreeCAD)", server: "freecad", category: "process", atom: "tool", tools: ["build_cad_model"], expect: "Freecad" },
    { id: "p-openfoam", label: "Simulacion CFD (OpenFOAM)", server: "openfoam", category: "process", atom: "tool", tools: ["run_pipe_flow"], expect: "Openfoam" },
    { id: "p-dicom", label: "Consulta PACS (DICOM)", server: "dicom", category: "read", atom: "tool", tools: ["query_studies"], expect: "Dicom" },
    { id: "p-gmail", label: "Borradores de correo (Gmail)", server: "gmail", category: "write", atom: "conexion", connector: "gmail", auth: "oauth", tools: ["create_draft"], expect: "Gmail" },
    { id: "p-forged", label: "Forged Zapier", server: "forged-zapier", puppet_id: "pp-1", category: "process", atom: "tool", tools: ["run"], expect: "Forged Zapier" },
    { id: "p-mem", label: "Memory", server: null, atom: "memoria", expect: "Memory" },
  ];
  await page.evaluate((ps) => { const c = window.__cuarto; ps.forEach((p) => c.placeTile(p)); window.__renderPieces(); }, PIECES);
  await sleep(300);

  // ── (1) etiqueta del DIORAMA (PIXI) = nombre de servicio, no descripción ──
  const dio = await page.evaluate((ids) => ids.map((i) => window.__cuarto.pieceLabelText(i)), PIECES.map((p) => p.id));
  PIECES.forEach((p, i) => ok(dio[i] === p.expect, `(1.${i + 1}) diorama '${p.server || "—"}' → "${p.expect}"`, `render='${dio[i]}'`));
  ok(!dio.some((t) => SPANISH.test(t || "")), "(1z) NINGUNA etiqueta del diorama tiene descripción en español", JSON.stringify(dio));

  /* ── (2) [FIX-P3 · §7] LA LISTA MURIÓ. La segunda superficie que nombra una pieza es el
   * PIE DE SU ARCO, en el diorama. Se re-apunta ahí, y la medición se ENDURECE: antes se
   * juntaban todas las filas en UNA string y se buscaba cada nombre adentro (una fila con el
   * nombre equivocado pasaba si el nombre correcto estaba en otra); ahora se abre el arco de
   * CADA pieza y se exige que su pie diga EXACTAMENTE lo que dice su etiqueta del piso. */
  const pies = await page.evaluate(async (ids) => {
    const out = {};
    for (const i of ids) {
      try { window.__closeAbanico(); } catch (e) {}
      window.__openAbanico(window.__cuarto.pieceData(i));
      await new Promise((r) => setTimeout(r, 60));
      out[i] = (document.getElementById("abName") || {}).textContent || "";
    }
    try { window.__closeAbanico(); } catch (e) {}
    return out;
  }, PIECES.map((p) => p.id));
  PIECES.forEach((p, i) => ok(pies[p.id] === p.expect,
    `(2.${i + 1}) el pie del arco de '${p.server || "—"}' dice "${p.expect}"`, `pie='${pies[p.id]}'`));
  ok(!Object.values(pies).some((t) => SPANISH.test(t || "")),
     "(2z) NINGÚN pie de arco tiene descripción en español", JSON.stringify(pies));

  // ── (3) inspector #iname = nombre de servicio ──
  const inameFreecad = await page.evaluate(() => { window.__openInspector(window.__cuarto.pieceData("p-freecad")); return document.getElementById("iname").textContent; });
  ok(inameFreecad === "Freecad", "(3) el inspector nombra la pieza por el servicio ('Freecad')", inameFreecad);

  // ── (4) idioma-neutral: bajo ES el nombre de servicio es idéntico (no se traduce, es nombre propio) ──
  await page.evaluate(() => { try { localStorage.setItem("aleph-lang", "es"); } catch (e) {} });
  await page.evaluate(() => window.__renderPieces());
  const dioEs = await page.evaluate(() => window.__cuarto.pieceLabelText("p-freecad"));
  ok(dioEs === "Freecad", "(4) ES y EN muestran el mismo nombre de servicio (idioma-neutral)", dioEs);
  await page.evaluate(() => { try { localStorage.setItem("aleph-lang", "en"); } catch (e) {} });

  ok(errors.length === 0, "(5) 0 errores JS/render", errors.slice(0, 2).join(" ; "));

  await page.screenshot({ path: join(HERE, "screenshots", "labels-servicio.png") });
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push(`harness: ${e && e.message ? e.message : String(e)}`);
} finally {
  await browser.close(); server.kill();
}
console.log("");
if (fails.length === 0) { console.log("RESULTADO: VERDE — labels por nombre de servicio (diorama+lista+inspector · como el reel · cero descripciones ES · idioma-neutral)"); process.exit(0); }
console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); process.exit(1);
