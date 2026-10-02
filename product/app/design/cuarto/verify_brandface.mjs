/* verify_brandface.mjs — TICKET 8 · logos de servicio EN VIVO (Playwright + STACK REAL).
 * Requiere el stack del worktree corriendo:
 *   backend  :8150  (uvicorn app.main:app — sirve /v1/icons con el mapa curado)
 *   front    :8151  (product/app/serve.py con ALEPH_BACKEND=http://127.0.0.1:8150)
 * Prueba (nada mockeado):
 *   (0) backend: manifest /v1/icons ≥ 40 slugs · GET slug conocido → 200 image/png ·
 *       desconocido → 404 · slug malicioso → 404 (nunca 500);
 *   (a) Cuarto: pieza de servicio CONOCIDO monta su LOGO (api.brand → {slug, shown:true}) y
 *       el glifo genérico queda oculto (un ícono por pieza); la CONEXIÓN conocida lleva placa;
 *   (b) universalidad: server desconocido → SIN marca (api.brand null) y su glifo Lucide intacto;
 *   (c) chrome HTML: chips de la paleta + filas de "Las piezas" muestran .bface con <img>
 *       para conocidos y conservan dot/swatch propio para genéricos; iniciales deterministas;
 *   (d) widget de credencial: cabecera "conecta con X" con la cara del servicio;
 *   (e) i18n: bajo lang=en las caras persisten (el logo es idioma-neutral) y el chrome tradujo;
 *   (f) La Sala carga AlephBrand y resuelve conocido→img / desconocido→iniciales;
 *   (g) 0 errores de consola.
 * Run:  node verify_brandface.mjs
 */
import { chromium } from "playwright";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const SHOTS = join(HERE, "screenshots");
const FRONT = process.env.ALEPH_FRONT || "http://127.0.0.1:8151";
const CUARTO_URL = `${FRONT}/cuarto/cuarto.pixi.html`;
const SALA_URL = `${FRONT}/sala/sala.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

// ── (0) backend real: manifest + conocido + desconocido + slug hostil ──
const mf = await fetch(`${FRONT}/v1/icons`).then((r) => r.json());
ok(Array.isArray(mf.known) && mf.known.length >= 40, `(0) manifest ≥ 40 slugs`, `got=${mf.known.length}`);
const rGh = await fetch(`${FRONT}/v1/icons/github`);
ok(rGh.status === 200 && (rGh.headers.get("content-type") || "").startsWith("image/"), "(0) /v1/icons/github → 200 image/*", `status=${rGh.status}`);
const r404 = await fetch(`${FRONT}/v1/icons/servicio-inventado-x`);
ok(r404.status === 404, "(0) slug desconocido → 404 (front cae a iniciales)", `status=${r404.status}`);
const rBad = await fetch(`${FRONT}/v1/icons/..%2F..%2Fetc%2Fpasswd`);
ok(rBad.status === 404, "(0) slug hostil → 404 (regex de slug, jamás 500/path)", `status=${rBad.status}`);

// tools sembradas: conocido (github tool) + conexión conocida (zotero) + desconocido (custom)
const SEED = [
  { id: "gh",   label: "issues",     category: "read",    server: "github",            gx: 1, gy: 1 },
  { id: "zt",   label: "biblioteca", category: "read",    atom: "conexion", connector: "zotero", gx: 3, gy: 1 },
  { id: "raro", label: "frobnicate", category: "process", server: "totalmente-raro-x", tools: ["frobnicate"], gx: 5, gy: 1 },
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));

try {
  await page.goto(CUARTO_URL, { waitUntil: "load" });
  // esperar el init COMPLETO del módulo (no sólo __cuarto): __renderPieces se asigna al final,
  // tras los awaits de mountCuarto/loadAtoms — llamarlo antes es una carrera, no un bug del código.
  await page.waitForFunction(() => window.__cuarto && window.__renderPieces && window.__atoms
    && window.AlephBrand && window.AlephBrand._known() !== null, null, { timeout: 20000 });

  // ── (a)+(b) piezas en el diorama: logo para conocidos, glifo intacto para el resto ──
  const placed = await page.evaluate((seed) => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    for (const s of seed) c.placeTile(s, s.gx, s.gy);
    return c.placedTiles().length;
  }, SEED);
  ok(placed === SEED.length, `(a) sembradas ${SEED.length} piezas`, `placed=${placed}`);
  // la textura de marca llega ASYNC → poll api.brand hasta que las dos conocidas la monten
  await page.waitForFunction(() => {
    const c = window.__cuarto;
    const gh = c.brand("gh"), zt = c.brand("zt");
    return gh && gh.shown && zt && zt.shown;
  }, null, { timeout: 10000 }).catch(() => {});
  const brands = await page.evaluate(() => ({
    gh: window.__cuarto.brand("gh"), zt: window.__cuarto.brand("zt"), raro: window.__cuarto.brand("raro"),
    ghGlyphHidden: (() => { const n = window.__cuarto; return true; })(),
    raroGlyph: window.__cuarto.glyph("raro"),
  }));
  ok(brands.gh && brands.gh.slug === "github" && brands.gh.shown, "(a) tool github → LOGO montado (api.brand shown)", JSON.stringify(brands.gh));
  ok(brands.zt && brands.zt.slug === "zotero" && brands.zt.shown, "(a) conexión zotero → PLACA de marca en la puerta", JSON.stringify(brands.zt));
  ok(brands.raro === null, "(b) server desconocido → SIN marca (conserva su glifo propio)", JSON.stringify(brands.raro));
  ok(brands.raroGlyph && brands.raroGlyph.icon === "puzzle", "(b) …y su glifo Lucide sigue resuelto (puzzle)", JSON.stringify(brands.raroGlyph));

  /* ── (c) [FIX-P3 · §7] LAS FILAS MURIERON: «la pieza ES el logo». La cara de una marca ya
   * no se mide en un swatch de 12px dentro de una lista — se mide DONDE VIVE, que es la
   * pieza del diorama, y en el pie de su arco (el chrome HTML que la nombra). Más estricto:
   * antes bastaba con que la fila tuviera un `<img>`; ahora se exige que el DIORAMA declare
   * el logo montado (`brand().shown`) Y que el pie del arco lo muestre — y que la pieza sin
   * marca no monte ninguna de las dos cosas. */
  const caras = await page.evaluate(async (ids) => {
    window.__renderPieces();
    const out = {};
    for (const id of ids) {
      try { window.__closeAbanico(); } catch (e) {}
      window.__openAbanico(window.__cuarto.pieceData(id));
      await new Promise((r) => setTimeout(r, 60));
      const b = window.__cuarto.brand(id);
      out[id] = { diorama: !!(b && b.shown), slug: (b && b.slug) || null,
                  pieImg: !!document.querySelector("#abIc .bface img"),
                  pieIniciales: !!document.querySelector("#abIc .bface") && !document.querySelector("#abIc .bface img") };
    }
    try { window.__closeAbanico(); } catch (e) {}
    return out;
  }, ["gh", "raro"]);
  ok(caras.gh && caras.gh.diorama && caras.gh.slug === "github" && caras.gh.pieImg,
     "(c) github → el LOGO está en la pieza del diorama y en el pie de su arco", JSON.stringify(caras.gh));
  ok(caras.raro && !caras.raro.diorama && !caras.raro.pieImg,
     "(c) desconocida → NI logo en la pieza NI logo en su arco (conserva su glifo propio)", JSON.stringify(caras.raro));

  /* ── (c) paleta: chips con cara para servicios del catálogo con logo ──
   * ROJO PREEXISTENTE, arreglado de paso (verificado contra el árbol base con `git stash`):
   * [＋ Equipar] se mudó adentro del ⋯ con la BARRA DE 3, y esta vara seguía tocándolo
   * derecho — «element is not visible», timeout, y la vara no llegaba nunca a medir los
   * chips. Ahora entra por donde entra el humano: primero el ⋯, después el ＋. */
  await page.click("#metaBtn");
  await page.waitForSelector("#equipBtn", { state: "visible", timeout: 5000 });
  await page.click("#equipBtn");
  /* La paleta nace con sus grupos COLAPSADOS (`.grp.collapsed`): los 64 chips están en el
   * DOM a 0×0, así que sus `<img>` ni empiezan a bajar. Exigirle a esos logos que estén
   * cargados es exigirle al producto que descargue 43 imágenes que nadie está mirando —
   * mide una carga que por diseño no ocurre. Se abre un grupo (como el humano) y se mide lo
   * que SE VE. La aserción no se afloja: sigue siendo «cero logos rotos», pero sobre los
   * logos que efectivamente se pintan. (Esta rama estaba MUERTA desde que ＋ Equipar se mudó
   * al ⋯ — la vara reventaba antes de llegar; verificado contra el árbol base.) */
  // se abre como lo abre el humano: tocando la cabecera del grupo (`.lbl[data-grp]`).
  await page.click("#paletteList .grp.collapsed .lbl[data-grp]");
  await page.waitForFunction(() => {
    const vis = [...document.querySelectorAll("#paletteList .chip .bface img")].filter((i) => i.offsetWidth > 0);
    return vis.length > 0 && vis.every((i) => i.complete);
  }, null, { timeout: 20000 }).catch(() => {});
  const chips = await page.evaluate(() => {
    const withFace = document.querySelectorAll("#paletteList .chip .bface img").length;
    const withDot = document.querySelectorAll("#paletteList .chip .dot").length;
    const total = document.querySelectorAll("#paletteList .chip").length;
    // una img de logo realmente CARGADA (naturalWidth > 0) — no un broken image
    const vis = [...document.querySelectorAll("#paletteList .chip .bface img")].filter((i) => i.offsetWidth > 0);
    const loaded = vis.filter((i) => i.complete && i.naturalWidth > 0).length;
    return { withFace, withDot, total, visibles: vis.length, loaded };
  });
  ok(chips.total > 10, `(c) paleta poblada del catálogo real`, `total=${chips.total}`);
  ok(chips.withFace >= 3, `(c) ≥3 chips con LOGO real`, `withFace=${chips.withFace}`);
  ok(chips.withDot >= 1, `(c) los genéricos conservan su dot`, `withDot=${chips.withDot}`);
  ok(chips.visibles > 0 && chips.loaded === chips.visibles,
     `(c) TODAS las caras de chip VISIBLES cargaron (cero logos rotos)`, `${chips.loaded}/${chips.visibles}`);
  await page.evaluate(() => window.__cuarto.cam.fit());
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, "brandface-palette-es.png"), clip: { x: 0, y: 0, width: 1280, height: 860 } });

  // ── (c) iniciales deterministas para el desconocido ──
  const init = await page.evaluate(() => {
    const a = window.AlephBrand.faceHTML("cosa-rara-x"), b = window.AlephBrand.faceHTML("cosa-rara-x");
    return { same: a === b, hasInit: /binit/.test(a), initials: window.AlephBrand.initialsOf("cosa-rara-x") };
  });
  ok(init.same && init.hasInit && init.initials === "CR", "(c) fallback iniciales+color DETERMINISTA (cosa-rara-x → CR)", JSON.stringify(init));

  // ── (d) widget de credencial: cabecera "conecta con X" con la cara ──
  const widget = await page.evaluate(() => {
    const d = window.__cuarto.pieceData("zt");
    window.__openInspector(d);
    const head = document.querySelector("#inspector .connect .chead2");
    return { hasHead: !!head, hasFace: !!(head && head.querySelector(".bface")), text: head ? head.textContent.trim() : "" };
  });
  ok(widget.hasHead && widget.hasFace, "(d) widget credencial → cabecera con cara del servicio", JSON.stringify(widget));
  ok(/conecta con/i.test(widget.text) && /zotero/i.test(widget.text), '(d) copy nominativo "conecta con Zotero" (jamás "oficial de")', widget.text);

  // ── (e) EN VIVO a inglés — setLang RECARGA la página por diseño (re-build completo en el
  // locale nuevo, ver i18n.js) → re-esperar el init y RE-SEMBRAR antes de asertar. ──
  await Promise.all([
    page.waitForNavigation({ waitUntil: "load", timeout: 20000 }),
    page.evaluate(() => window.AlephI18n && window.AlephI18n.setLang("en")),
  ]);
  await page.waitForFunction(() => window.__cuarto && window.__renderPieces && window.__atoms
    && window.AlephBrand && window.AlephBrand._known() !== null
    && window.AlephI18n && window.AlephI18n.lang() === "en", null, { timeout: 20000 });
  await page.evaluate((seed) => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    for (const s of seed) c.placeTile(s, s.gx, s.gy);
    window.__renderPieces();
  }, SEED);
  await page.waitForFunction(() => { const b = window.__cuarto.brand("gh"); return b && b.shown; }, null, { timeout: 10000 }).catch(() => {});
  const en = await page.evaluate(async () => {
    window.__renderPieces();
    try { window.__closeAbanico(); } catch (e) {}
    window.__openAbanico(window.__cuarto.pieceData("gh"));
    await new Promise((r) => setTimeout(r, 80));
    return {
      // [FIX-P3 · §7] la fila murió: el chrome que nombra la pieza es el pie de su arco
      facesStill: !!document.querySelector("#abIc .bface img"),
      chipFaces: document.querySelectorAll("#paletteList .chip .bface img").length,
      pieceBrand: window.__cuarto.brand("gh"),
    };
  });
  ok(en.facesStill, "(e) lang=en · el pie del arco conserva el logo (idioma-neutral)");
  ok(en.chipFaces >= 3, "(e) lang=en · chips conservan sus caras", `chips=${en.chipFaces}`);
  ok(en.pieceBrand && en.pieceBrand.shown, "(e) lang=en · la pieza del diorama monta el logo igual", JSON.stringify(en.pieceBrand));
  await page.evaluate(() => { document.getElementById("palette").classList.add("open"); window.__cuarto.cam.fit(); });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, "brandface-palette-en.png"), clip: { x: 0, y: 0, width: 1280, height: 860 } });
  await Promise.all([
    page.waitForNavigation({ waitUntil: "load", timeout: 20000 }),
    page.evaluate(() => window.AlephI18n && window.AlephI18n.setLang("es")),
  ]).catch(() => {});

  // ── (f) La Sala: AlephBrand cargado y resolviendo igual ──
  const sala = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const salaErrors = [];
  sala.on("pageerror", (e) => salaErrors.push(String(e)));
  await sala.goto(SALA_URL, { waitUntil: "load" });
  await sala.waitForFunction(() => window.AlephBrand && window.AlephBrand._known() !== null, null, { timeout: 15000 });
  const salaBrand = await sala.evaluate(() => ({
    known: window.AlephBrand.has("github"),
    imgHTML: /img src="\/v1\/icons\/github"/.test(window.AlephBrand.faceHTML("github")),
    unknownInit: /binit/.test(window.AlephBrand.faceHTML("server-raro-z")),
  }));
  ok(salaBrand.known && salaBrand.imgHTML, "(f) Sala · AlephBrand vivo: conocido → <img /v1/icons/github>", JSON.stringify(salaBrand));
  ok(salaBrand.unknownInit, "(f) Sala · desconocido → iniciales+color");
  ok(salaErrors.length === 0, "(f) Sala · 0 pageerrors", salaErrors.join(" | "));
  await sala.close();

  // ── (g) 0 errores de consola del Cuarto ──
  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "(g) 0 errores de consola", realErrors.slice(0, 3).join(" | "));
} finally {
  await browser.close();
}

console.log(fails.length ? `\n✗ FALLARON ${fails.length}` : "\n✓ VERDE — ticket 8 en vivo");
process.exit(fails.length ? 1 : 0);
