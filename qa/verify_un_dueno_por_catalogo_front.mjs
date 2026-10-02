/* verify_un_dueno_por_catalogo_front.mjs — EL CUARTO, POR SESIÓN.
 *
 * La corre `qa/verify_un_dueno_por_catalogo.py`; imprime una línea JSON con los testigos.
 * No se invoca suelta: la vara es una sola, como manda la casa.
 *
 * Abre EL MISMO Cuarto dos veces, con dos sesiones distintas, contra el MISMO backend y el
 * MISMO dir de datos. La cuenta A tiene que ver su pieza; la cuenta B no puede verla —y
 * tiene que seguir viendo la suya, porque esconderle la pieza a todo el mundo también
 * haría desaparecer la fuga, y sería un producto roto.
 */
import { chromium } from "playwright";

const BASE = process.env.ALEPH_VARA_URL;
const TOKEN_A = process.env.ALEPH_VARA_TOKEN_A;
const TOKEN_B = process.env.ALEPH_VARA_TOKEN_B;
const R = {};
const anotar = (n, ok, det = {}) => { R[n] = { ok: !!ok, ...det }; };

if (!BASE || !TOKEN_A || !TOKEN_B) {
  console.log(JSON.stringify({ "4_el_cuarto_por_sesion": { ok: false, motivo: "faltan las sesiones" } }));
  process.exit(1);
}

/** El catálogo que ve UNA sesión. La sesión se siembra ANTES de que corra un script de la
 *  página (`addInitScript`), que es como llega de verdad: el Cuarto la lee al arrancar. */
async function catalogoDe(browser, token) {
  const ctx = await browser.newContext();
  await ctx.addInitScript((t) => {
    const u = { id: "x", session_token: t };
    try { sessionStorage.setItem("puppet_user", JSON.stringify(u)); } catch (_) { /* ignorado */ }
    try { localStorage.setItem("puppet_user", JSON.stringify(u)); } catch (_) { /* ignorado */ }
  }, token);
  const page = await ctx.newPage();
  const errores = [];
  page.on("pageerror", (e) => errores.push(String(e).slice(0, 140)));
  await page.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForFunction("!!window.__catalog", { timeout: 90000 });
  const out = await page.evaluate(() => ({
    entityCount: window.__catalog.entityCount,
    claves: (window.__catalog.entries || []).map((e) => e.key),
  }));
  await ctx.close();
  return { ...out, errores };
}

let browser;
try {
  browser = await chromium.launch();
  const a = await catalogoDe(browser, TOKEN_A);
  const b = await catalogoDe(browser, TOKEN_B);

  const tiene = (cat, pieza) => cat.claves.some((k) => k.includes(pieza));

  anotar("4_el_cuarto_del_dueno_tiene_su_pieza", tiene(a, "pieza-de-a"),
    { A: a.claves.filter((k) => k.includes("pieza-")) });

  // ⚠️ EL TESTIGO QUE DECIDE LA OBRA. Dos pantallas idénticas, mismo backend, mismo disco:
  // lo único distinto es quién mira.
  anotar("4_el_cuarto_de_la_otra_cuenta_NO_la_tiene", !tiene(b, "pieza-de-a"),
    { B: b.claves.filter((k) => k.includes("pieza-")) });

  // El medio renglón que impide el arreglo perezoso: esconderla para todos también
  // «arreglaría» la fuga. B tiene que seguir viendo LA SUYA.
  anotar("4_pero_B_sigue_viendo_la_suya", tiene(b, "pieza-de-b"),
    { B: b.claves.filter((k) => k.includes("pieza-")) });

  // GUARD · el catálogo de la caja es el MISMO para las dos. Si el filtro se hubiera
  // llevado puesto lo público, una cuenta vería menos piezas que la otra y este testigo
  // rojearía — que es lo que lo hace un guard y no un adorno.
  const caja = (cat) => cat.claves.filter((k) => !k.includes("pieza-de-")).sort();
  const [ca, cb] = [caja(a), caja(b)];
  anotar("5_guard_la_caja_es_la_misma_para_las_dos",
    ca.length > 0 && JSON.stringify(ca) === JSON.stringify(cb),
    { piezas_de_la_caja: ca.length,
      solo_A: ca.filter((k) => !cb.includes(k)), solo_B: cb.filter((k) => !ca.includes(k)) });

  anotar("5_ninguna_superficie_tira_errores",
    a.errores.length === 0 && b.errores.length === 0,
    { A: a.errores.slice(0, 2), B: b.errores.slice(0, 2) });
} catch (e) {
  anotar("4_el_cuarto_por_sesion", false, { excepcion: String(e).slice(0, 300) });
} finally {
  if (browser) await browser.close().catch(() => {});
}

console.log(JSON.stringify(R));
