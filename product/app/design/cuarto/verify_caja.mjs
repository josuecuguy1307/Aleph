/* verify_caja.mjs — TICKET 7 · CAJA + CANDADO-SEMÁFORO en vivo (Playwright + STACK REAL).
 * Requiere el stack del worktree: backend :8150 + front :8151.
 * [FIX-P3 · §4] LA DOCTRINA CAMBIÓ, A PROPÓSITO. Esto medía DOS candados por pieza: el de
 * la TAPA (que reportaba) y el del CABLE (que permitía), «ambos visibles a la vez». Era
 * cierto y se veía mal — dos candados sueltos por pieza, uno custodiando una esquina. La
 * versión sellada el 26-jul es UNO por pieza, pegado a su cable al Núcleo, con un solo
 * vocabulario de estados que absorbe los dos. `lidLock(id)` conserva su nombre porque el
 * DATO es el mismo —qué está frenando esta pieza— pero ya no hay tapa: hay EL candado.
 *   (a) EL CANDADO: pieza con tools consecuentes sin gate → "alerta" (arco abierto,
 *       respirando); pura lectura → SIN candado (ni ofrecido); plata → "firme" (piso);
 *   (b) CICLO: aceptar la sugerencia pone el gate REAL → el candado pasa a "firme", en el
 *       MISMO punto del cable (no salta de superficie) y sigue habiendo UNO solo;
 *   (c) CAJA ABIERTA: las tools adentro con TINTE POR NATURALEZA (verde=LEE · ámbar=ACTÚA)
 *       + el porqué (title) desde la MISMA clasificación del advisor;
 *   (d) lang=en: tinte igual (dato visual) + why en inglés;
 *   (e) 0 errores de consola.
 * Run:  node verify_caja.mjs
 */
import { chromium } from "playwright";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const SHOTS = join(HERE, "screenshots");
const FRONT = process.env.ALEPH_FRONT || "http://127.0.0.1:8151";
const CUARTO_URL = `${FRONT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

const SEED = [
  { id: "mix", label: "correo",   category: "write", server: "svc-mailer", tools: ["send_mail", "get_price"], gx: 1, gy: 1 },
  { id: "lec", label: "lector",   category: "read",  server: "svc-reader", tools: ["get_price", "list_files"], gx: 3, gy: 1 },
  { id: "pla", label: "banco",    category: "write", server: "svc-bank",   tools: ["transfer_funds"], gx: 5, gy: 1 },
];
const seedAndWait = async (page) => {
  await page.evaluate((seed) => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    for (const s of seed) c.placeTile(s, s.gx, s.gy);
    window.__sync();
  }, SEED);
  await page.waitForFunction(() => window.__cuarto.lidLock("mix") !== null, null, { timeout: 10000 });
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));

try {
  await page.goto(CUARTO_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__renderPieces && window.__atoms, null, { timeout: 20000 });
  await seedAndWait(page);

  // ── (a) semáforo de la tapa por estado real ──
  const lids = await page.evaluate(() => ({
    mix: window.__cuarto.lidLock("mix"), lec: window.__cuarto.lidLock("lec"), pla: window.__cuarto.lidLock("pla"),
  }));
  ok(lids.mix === "alerta", "(a) consecuente sin gate → candado ALERTA (arco abierto, respirando)", JSON.stringify(lids));
  ok(lids.lec === null, "(a) pura lectura → SIN candado (nada que frenar, y nada que ofrecer)");
  ok(lids.pla === "firme", "(a) plata → candado FIRME (piso del sistema: ya frenada, no opción)");
  // …y «ni ofrecido»: el arco de una pieza de pura lectura no tiene [Asegurar].
  const arcoLec = await page.evaluate(async () => {
    window.__openAbanico(window.__cuarto.pieceData("lec"));
    await new Promise((r) => setTimeout(r, 250));
    const a = window.__abanicoActs().map((x) => x.act);
    window.__closeAbanico(); return a;
  });
  ok(!arcoLec.includes("asegurar"), "(a) …y a la de pura lectura NI SE LE OFRECE [Asegurar]", arcoLec.join("·"));
  await page.evaluate(() => window.__cuarto.cam.fit());
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(SHOTS, "caja-semaforo.png"), clip: { x: 0, y: 0, width: 1280, height: 860 } });

  // ── (b) ciclo: propuesto en el cable → aceptar → el MISMO candado se cierra, ahí mismo ──
  const pre = await page.evaluate(() => ({ ghosts: window.__cuarto.advisorGhosts(),
                                           donde: window.__cuarto.candado("mix") }));
  ok(pre.ghosts.includes("mix"), "(b) …y el fantasma del PERMISO está en el CABLE de esa pieza", JSON.stringify(pre.ghosts));
  await page.evaluate(() => window.__cuarto.applyGhost("mix"));
  await page.waitForTimeout(150);
  const post = await page.evaluate(() => ({
    lid: window.__cuarto.lidLock("mix"),
    ghosts: window.__cuarto.advisorGhosts(),
    cableGate: window.__cuarto.relationModel().relationships.some((r) => r.kind === "gate" && r.on === "mix"),
    donde: window.__cuarto.candado("mix"),
    candados: window.__cuarto.candados(),
  }));
  ok(post.lid === "firme", "(b) aceptaste → el candado se CIERRA (firme)", post.lid);
  ok(post.cableGate, "(b) el PERMISO quedó en el cable (kind:'gate' en el modelo)");
  ok(!post.ghosts.includes("mix"), "(b) …y el propuesto se fue: no quedan dos");
  /* [FIX-P3 · §4] las tres invariantes de la versión sellada, MEDIDAS (no grepeadas):
   * UNO por pieza · pegado al cable · y el ciclo no lo teletransporta a otra superficie. */
  ok(post.donde && post.donde.dCable <= 1.5,
     "(b) el candado está PEGADO al cable, antes y después de aceptar",
     `antes=${(pre.donde || {}).dCable?.toFixed(2)}px después=${post.donde.dCable.toFixed(2)}px`);
  ok(pre.donde && Math.hypot(post.donde.x - pre.donde.x, post.donde.y - pre.donde.y) < 1.5,
     "(b) …y en el MISMO punto: aceptar cambia el estado, no el lugar");
  ok(post.candados.length === new Set(post.candados).size && post.candados.length <= 2,
     "(b) UNO por pieza: cero candados repetidos en la escena", JSON.stringify(post.candados));

  // ── (c) caja abierta: tinte por naturaleza + porqué ──
  const open = await page.evaluate(() => {
    window.__openInspector(window.__cuarto.pieceData("mix"));
    const tgs = [...document.querySelectorAll("#inspector .tg")];
    const by = {};
    for (const b of tgs) by[b.dataset.v] = { nat: (b.querySelector(".natdot") || {}).dataset ? b.querySelector(".natdot").dataset.nat : null, title: b.title || "" };
    return by;
  });
  ok(open.send_mail && open.send_mail.nat === "actua", "(c) send_mail adentro → tinte ÁMBAR (actúa)", JSON.stringify(open.send_mail));
  ok(open.get_price && open.get_price.nat === "lee", "(c) get_price adentro → tinte VERDE (lee)", JSON.stringify(open.get_price));
  ok(/afuera|OK/i.test((open.send_mail || {}).title || ""), "(c) el porqué viaja en el title (microcopy)", (open.send_mail || {}).title.slice(0, 60));

  // ── (d) lang=en (reload por diseño → re-seed) ──
  await Promise.all([
    page.waitForNavigation({ waitUntil: "load", timeout: 20000 }),
    page.evaluate(() => window.AlephI18n.setLang("en")),
  ]);
  await page.waitForFunction(() => window.__cuarto && window.__renderPieces && window.__atoms
    && window.AlephI18n && window.AlephI18n.lang() === "en", null, { timeout: 20000 });
  await seedAndWait(page);
  const en = await page.evaluate(() => {
    window.__openInspector(window.__cuarto.pieceData("mix"));
    const b = [...document.querySelectorAll("#inspector .tg")].find((x) => x.dataset.v === "send_mail");
    return { lid: window.__cuarto.lidLock("mix"), nat: b && b.querySelector(".natdot") ? b.querySelector(".natdot").dataset.nat : null, title: b ? b.title : "" };
  });
  ok(en.lid === "alerta" && en.nat === "actua", "(d) lang=en · tapa y tinte iguales (dato visual)", JSON.stringify({ lid: en.lid, nat: en.nat }));
  ok(/sends|gate/i.test(en.title), "(d) lang=en · el porqué en inglés", en.title.slice(0, 60));
  await Promise.all([
    page.waitForNavigation({ waitUntil: "load", timeout: 20000 }),
    page.evaluate(() => window.AlephI18n.setLang("es")),
  ]).catch(() => {});

  // ── (e) consola limpia ──
  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "(e) 0 errores de consola", realErrors.slice(0, 3).join(" | "));
} finally {
  await browser.close();
}

console.log(fails.length ? `\n✗ FALLARON ${fails.length}` : "\n✓ VERDE — ticket 7 (caja + candado-semáforo) en vivo");
process.exit(fails.length ? 1 : 0);
