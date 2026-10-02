/* verify_pieza_en_el_cuarto_front.mjs — EL GUARD DE ALCANZABILIDAD de la vara.
 *
 * La corre `qa/verify_pieza_en_el_cuarto.py`; imprime una línea JSON con los testigos. No
 * se invoca suelta: la vara es una sola, como manda la casa.
 *
 * QUE LA PROYECCIÓN DEVUELVA LA ENTIDAD NO ES QUE EL USUARIO PUEDA USARLA. Acá no se
 * mockea nada: arranca el backend REAL contra el fixture (ALEPH_DATA_DIR), abre El Cuarto
 * de verdad, abre la paleta con un click, busca la pieza traída y la EQUIPA con un click.
 * El testigo es `placedTiles()`, o sea el piso, no el DOM de la lista.
 *
 * Los negativos calibran que cada testigo puede rojear: una pieza que no existe no produce
 * chip, y el catálogo de la caja tiene que seguir equipándose igual.
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { createServer as netCreateServer } from "node:net";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const PY = join(RAIZ, "product/backend/.venv/bin/python");
/** UN PUERTO LIBRE, PEDIDO AL SISTEMA. No un número fijo.
 *
 * ⚠️ ESTO NO ES HIGIENE, ES CORRECCIÓN. Con `8473` fijo, un sidecar que quedó vivo de una
 * corrida anterior —p. ej. una que cortó por timeout— sigue atendiendo ese puerto: el
 * `/health` responde **verde**, la vara cree que arrancó el suyo, y mide un proceso cuyo
 * fixture ya se borró. Medido: 48 entidades (sólo la caja) y la sesión sin resolver, sobre
 * una app instalada que estaba perfecta. Un puerto que el sistema nos da no puede ser de
 * nadie más.
 */
function puertoLibre() {
  const srv = netCreateServer();
  return new Promise((resolve, reject) => {
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const p = srv.address().port;
      srv.close(() => resolve(p));
    });
  });
}
const PUERTO = Number(process.env.ALEPH_VARA_PORT || await puertoLibre());
if (PUERTO === 25374) throw new Error(":25374 es la .app instalada — jamás");
const BASE = `http://127.0.0.1:${PUERTO}`;
const R = {};
const anotar = (nombre, ok, detalle = {}) => { R[nombre] = { ok: !!ok, ...detalle }; };


/** EQUIPAR CON UN CLICK, ESPERANDO LA CONDICIÓN — no un reloj.
 *
 * ⚠️ ESTE TESTIGO PARPADEÓ DOS VECES, y las dos por la vara, no por la superficie. El
 * handler de la paleta engancha su `pointerup` DENTRO del `pointerdown`: si los dos eventos
 * salen pegados, el listener todavía no existe y el click se pierde. La primera vuelta se
 * tapó con `waitForTimeout(150)` — y volvió a rojear bajo carga, corriendo junto a otras
 * varas. Un número fijo es una apuesta sobre la máquina del que corre.
 *
 * Acá se espera LO QUE TIENE QUE PASAR: que el piso crezca. Y si no crece, se reintenta el
 * click una vez más antes de declararlo. Una vara que rojea por su propia velocidad es
 * exactamente el rojo que mañana se ignora.
 */
async function equipar(page, selector, antes) {
  for (let intento = 0; intento < 3; intento++) {
    // EL CHIP SE RE-BUSCA Y SE RE-MIDE EN CADA INTENTO, esperando VISIBILIDAD. La paleta se
    // pinta de una sola pasada, así que entre medir y apretar el nodo puede haberse
    // reemplazado: `page.$` devolvía el de antes —sin caja— y `equipar` se rendía sin haber
    // apretado nada, o apretaba coordenadas viejas que caen en el vecino. Las dos veces el
    // testigo habría culpado a la superficie.
    const chip = await page.waitForSelector(selector, { state: "visible", timeout: 8000 })
      .catch(() => null);
    if (!chip) continue;
    // ⚠️ AL VIEWPORT ANTES DE MEDIR. «Visible» para Playwright es tener caja, no estar en
    // pantalla: la lista de la paleta scrollea, y con el catálogo lleno el chip caía DEBAJO
    // del pliegue. La caja daba coordenadas reales… fuera de la ventana, así que el
    // `mouse.down` aterrizaba en la nada. Medido con `elementFromPoint`: devolvía `null` en
    // el centro exacto del chip, mientras `placeTile` funcionaba perfecto. La vara culpaba
    // a la superficie por no haber mirado dónde estaba apretando.
    await chip.scrollIntoViewIfNeeded().catch(() => {});
    const caja = await chip.boundingBox();
    if (!caja) continue;
    await page.mouse.move(caja.x + caja.width / 2, caja.y + caja.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(60);
    await page.mouse.up();
    try {
      await page.waitForFunction(
        (n) => window.__cuarto.placedTiles().length > n, antes, { timeout: 4000 });
      return true;
    } catch { /* el click no prendió: se reintenta, y si no, el testigo lo dirá */ }
  }
  return false;
}


/** ABRIR LA PALETA · click, y ESPERAR a que de verdad se haya abierto.
 *
 * ⚠️ `page.click("#equipBtn")` NO ALCANZA. El `onclick` del botón se asigna TARDE en el
 * arranque del Cuarto —mucho después de `window.__catalog`/`__cuarto`, que es lo que la
 * vara espera para empezar—, así que el click puede caer sobre un botón todavía sin
 * cablear y no pasar nada. En la fuente el orden salía bien por casualidad; contra el
 * binario CONGELADO no, y la vara acusaba «el chip no está en el DOM» sobre una app
 * PERFECTA: los 51 chips estaban ahí, plegados, con la paleta cerrada.
 *
 * Se aprieta hasta que `#palette` tenga la clase `open`, y su resultado es un testigo
 * propio: si la paleta no abre, eso es lo que hay que leer — no «no encontré el chip».
 */
async function abrirPaleta(page) {
  for (let intento = 0; intento < 5; intento++) {
    const abierta = await page.evaluate(() =>
      document.getElementById("palette").classList.contains("open"));
    if (abierta) return true;
    await page.click("#equipBtn").catch(() => {});
    try {
      await page.waitForFunction(
        () => document.getElementById("palette").classList.contains("open"),
        { timeout: 3000 });
      return true;
    } catch { /* el botón todavía no estaba cableado: se reintenta */ }
  }
  return false;
}

/* ── el backend REAL contra el fixture ──────────────────────────────────────────────── */
if (!existsSync(PY)) {
  console.log(JSON.stringify({ "5_guard_alcanzable_por_clicks": { ok: false, motivo: "sin venv del backend" } }));
  process.exit(1);
}
// `sidecar_serve` congelado resuelve `app.main` por el pathex del .spec; suelto hay que
// darle el mismo suelo (product/backend + platform), o muere con `No module named 'app'`.
// ⚠️ LA MISMA VARA CERTIFICA LA FUENTE O EL BINARIO. Con `ALEPH_VARA_SIDECAR` apuntando a
// un sidecar congelado —el de la app INSTALADA, por ejemplo— la pieza traída se mide sobre
// el artefacto que el usuario abre, no sobre el árbol. Que el arreglo esté escrito y que
// haya VIAJADO son dos cosas distintas: las obras 6a y 6d de este gate nacieron de eso.
const CONGELADO = (process.env.ALEPH_VARA_SIDECAR || "").trim();
const ARRANQUE = CONGELADO
  ? [CONGELADO, ["--port", String(PUERTO)]]
  : [PY, [join(RAIZ, "deploy/fase4/sidecar_serve.py"), "--port", String(PUERTO)]];
console.error(`[vara] backend: ${CONGELADO ? "CONGELADO " + CONGELADO : "fuente"}`);
const server = spawn(ARRANQUE[0], ARRANQUE[1], {
  cwd: RAIZ,
  env: {
    ...process.env,
    ALEPH_DATA_DIR: process.env.ALEPH_DATA_DIR || "",
    PYTHONPATH: [join(RAIZ, "product/backend"), join(RAIZ, "platform"), process.env.PYTHONPATH || ""]
      .filter(Boolean).join(":"),
  },
  stdio: ["ignore", "pipe", "pipe"],
  // ⚠️ GRUPO PROPIO, Y NO ES UN DETALLE. Un binario PyInstaller *onefile* es un bootloader
  // que lanza un HIJO: matar el pid que devuelve `spawn` mata al padre y deja al hijo vivo,
  // atendiendo el puerto y sosteniendo el pipe. Consecuencias medidas, las dos feas: node no
  // termina nunca (la vara se cuelga hasta el timeout), y el huérfano sobrevive para
  // contestarle el `/health` a la corrida SIGUIENTE — que entonces mide un servidor cuyo
  // fixture ya se borró, y sale verde hablándole a un muerto.
  detached: true,
});
let logServer = "";
server.stdout.on("data", (d) => { logServer += d; });
server.stderr.on("data", (d) => { logServer += d; });

const arriba = await (async () => {
  for (let i = 0; i < 90; i++) {
    try {
      const r = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(2000) });
      if (r.ok) return true;
    } catch { /* todavía no */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
})();

//: Se mata el GRUPO (`-pid`), no el pid: ver la nota de `detached` arriba.
const cerrar = () => {
  try { process.kill(-server.pid, "SIGKILL"); } catch { /* ya murió */ }
  try { server.kill("SIGKILL"); } catch { /* ya murió */ }
};

if (!arriba) {
  cerrar();
  console.log(JSON.stringify({
    "5_guard_alcanzable_por_clicks": { ok: false, motivo: "el backend no levantó", log: logServer.slice(-400) },
  }));
  process.exit(1);
}

let browser;
try {
  /* ── 0 · el endpoint que El Cuarto MIRA responde ──────────────────────────────────── */
  const rEnt = await fetch(`${BASE}/v1/connector-entities`,
    { headers: { Authorization: `Bearer ${process.env.ALEPH_VARA_TOKEN || ""}` } });
  const ent = rEnt.ok ? await rEnt.json() : null;
  anotar("5a_el_endpoint_que_el_cuarto_mira_responde", rEnt.status === 200, {
    status: rEnt.status,
    entidades: ent ? ent.total : null,
    // ⚠️ ESTE ERA EL BUG: 500 acá manda a El Cuarto a la ruta de respaldo — la que su
    // propio comentario declara «no es la ruta del frozen certificado».
  });

  browser = await chromium.launch();
  // ⚠️ LA SESIÓN VIAJA (A1 · la fuga entre cuentas). El Cuarto sólo sirve las piezas de
  // quien mira; sin sesión esta vara vería el catálogo de la caja y creería que la pieza
  // traída no llegó. Se siembra ANTES de que corra un script de la página, que es como
  // llega de verdad: el Cuarto la lee al arrancar.
  const ctx = await browser.newContext();
  await ctx.addInitScript((t) => {
    const u = { id: "x", session_token: t };
    try { sessionStorage.setItem("puppet_user", JSON.stringify(u)); } catch (_) { /* ignorado */ }
    try { localStorage.setItem("puppet_user", JSON.stringify(u)); } catch (_) { /* ignorado */ }
  }, process.env.ALEPH_VARA_TOKEN || "");
  const page = await ctx.newPage();
  const errores = [];
  page.on("pageerror", (e) => errores.push(String(e).slice(0, 160)));
  await page.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForFunction("!!window.__catalog && !!window.__cuarto", { timeout: 90000 });

  /* ── 1 · la pieza traída está en el catálogo POR LA RUTA VIVA ─────────────────────── */
  const cat = await page.evaluate(() => ({
    total: window.__catalog.total,
    entityCount: window.__catalog.entityCount,
    entradas: (window.__catalog.entries || []).map((e) => ({ key: e.key, label: e.label })),
  }));
  // `service:` = la proyección de entidades (la ruta certificada). `mcp:` = el respaldo.
  const entrada = cat.entradas.find((e) => e.key === "service:pieza-traida");
  const clave = entrada && entrada.key;
  anotar("5b_la_pieza_traida_esta_por_la_ruta_viva", !!clave && cat.entityCount > 0, {
    clave: clave || null, entityCount: cat.entityCount, total: cat.total,
  });

  /* ── 2 · aparece como CHIP en la paleta, con un click ─────────────────────────────── */
  // Se busca POR LA ETIQUETA, que es lo que el usuario ve y tipea. Buscar por el id
  // (`pieza-traida`) daba 0 resultados y hacía rojear la vara por su propia consulta: el
  // buscador matchea el nombre visible ("Pieza Traida"), no la clave interna.
  anotar("5b_la_paleta_abre", await abrirPaleta(page));
  await page.fill("#palSearch", (entrada && entrada.label) || "pieza");
  const sel = `#paletteList .chip[data-key="${clave || "service:pieza-traida"}"]`;
  // ⚠️ SE ESPERA QUE EL CHIP SEA VISIBLE, no un número de milisegundos. Con sesión el Cuarto
  // hace más trabajo al arrancar (carga tus Aleph, el semáforo…) y un `waitForTimeout(600)`
  // llegaba antes que el layout: el chip estaba en el DOM y sin caja, o sea inalcanzable
  // para el usuario según la vara — y alcanzable de verdad medio segundo después.
  const chip = await page.waitForSelector(sel, { state: "visible", timeout: 15000 })
    .catch(() => null);
  const caja = chip ? await chip.boundingBox() : null;
  anotar("5c_la_pieza_traida_es_un_chip_visible", !!chip && !!caja, {
    // Existir en el DOM no es existir para el usuario: sin caja no se puede tocar.
    en_dom: !!chip, con_caja: !!caja,
  });

  /* ── 3 · SE EQUIPA POR CLICKS (el testigo es el piso, no la lista) ────────────────── */
  const antes = await page.evaluate(() => window.__cuarto.placedTiles().length);
  if (caja) {
    await equipar(page, sel, antes);
  }
  const colocadas = await page.evaluate(() => window.__cuarto.placedTiles().map((t) => t.key || t.id));
  anotar("5d_la_pieza_traida_se_equipa_por_clicks",
    colocadas.length === antes + 1 && colocadas.some((k) => String(k).includes("pieza-traida")),
    { antes, despues: colocadas.length, colocadas: colocadas.slice(-3) });

  /* ── NEGATIVO · una pieza que NO existe no produce chip. Calibra 5c: si el selector
   *    matcheara cualquier cosa, este testigo saldría verde igual y 5c no mediría nada. */
  await page.fill("#palSearch", "pieza-que-no-existe-jamas");
  await page.waitForTimeout(600);
  const fantasma = await page.$$("#paletteList .chip");
  anotar("5e_negativo_una_pieza_inexistente_no_da_chip", fantasma.length === 0, {
    chips: fantasma.length,
  });

  /* ── GUARD · una de las de la caja sigue igual: aparece y se equipa ───────────────── */
  const deLaCaja = cat.entradas.find((e) => /(^|:)(arxiv|calc|wikipedia|duckduckgo)$/.test(e.key))
    || cat.entradas.find((e) => e.key.startsWith("service:") && e.key !== clave);
  await page.fill("#palSearch", (deLaCaja && deLaCaja.label) || "");
  const chipCaja = deLaCaja
    ? await page.waitForSelector(`#paletteList .chip[data-key="${deLaCaja.key}"]`,
                                 { state: "visible", timeout: 15000 }).catch(() => null)
    : null;
  const cajaCaja = chipCaja ? await chipCaja.boundingBox() : null;
  const antes2 = await page.evaluate(() => window.__cuarto.placedTiles().length);
  if (cajaCaja) {
    await equipar(page, `#paletteList .chip[data-key="${deLaCaja.key}"]`, antes2);
  }
  const despues2 = await page.evaluate(() => window.__cuarto.placedTiles().length);
  anotar("5f_guard_una_de_la_caja_sigue_igual", !!chipCaja && !!cajaCaja && despues2 === antes2 + 1, {
    pieza: (deLaCaja && deLaCaja.key) || null, antes: antes2, despues: despues2,
  });

  anotar("5g_la_superficie_no_tira_errores", errores.length === 0, { errores: errores.slice(0, 3) });
} catch (e) {
  anotar("5_guard_alcanzable_por_clicks", false, { excepcion: String(e).slice(0, 300) });
} finally {
  if (browser) await browser.close().catch(() => {});
  cerrar();
}

console.log(JSON.stringify(R));
