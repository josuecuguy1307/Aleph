/* verify_reforma_ola4.mjs — REFORMA DEL CUARTO · OLA 4 (MOVIMIENTO).
 *
 * El abanico abre con FÍSICA, no con piel. Contra el sidecar frozen real (WebKit, :8261):
 *   · llega moviéndose: ease-out cúbico con un pelo de overshoot
 *   · escalonado 20ms/ítem, ~180ms de punta a punta
 *   · se RECOGE al cerrar (no desaparece de golpe)
 *   · la pieza se despega (sube + sombra) mientras su abanico está abierto
 *   · hover = PROFUNDIDAD, no color (el fondo no cambia; sí la sombra y el transform)
 *   · la sala ATENÚA — no desenfoca
 *   · SALVAVIDAS: el segundo click completa ya · el no-verde llega PRIMERO
 *   · cero neón / cero holograma
 *   · LA BANDERA apaga la animación entera
 *
 * Run:  SIDECAR=http://127.0.0.1:8261 node product/app/design/cuarto/verify_reforma_ola4.mjs
 */
import { webkit } from "playwright";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const BASE = process.env.SIDECAR || "http://127.0.0.1:8261";
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (c, label, extra) => {
  console.log(`${c ? "✓" : "✗"} ${label}${extra != null && extra !== "" ? "  — " + extra : ""}`);
  if (!c) fails.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

try {
  const r = await fetch(BASE + "/health");
  if (!r.ok) throw new Error("health " + r.status);
  console.log(`── sidecar ${BASE} vivo\n`);
} catch (e) {
  console.log(`✗ el sidecar ${BASE} no responde (${e.message})`);
  process.exit(1);
}

const html = await readFile(join(HERE, "cuarto.pixi.html"), "utf8");

async function abrirPagina(browser, qs) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  await page.goto(PAGE + (qs || ""), { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!window.__catalog && !!window.__preflight, null, { timeout: 45000 }).catch(() => {});
  await sleep(800);
  await page.evaluate(async () => {
    const cat = window.__catalog, C = window.__cuarto;
    const e = (cat.entries || []).find((x) => x.mcp === "pysandbox");
    if (e) C.placeTile(Object.assign({}, e, { id: "t-mov" }));
    window.__sync && window.__sync(); window.__renderPieces && window.__renderPieces();
    await new Promise((r) => setTimeout(r, 1500));
  });
  return { page, errs };
}

const browser = await webkit.launch();
const { page, errs } = await abrirPagina(browser, "");
ok(errs.length === 0, "la página carga sin errores de JS", errs.slice(0, 2).join(" | "));

// ══ LA FÍSICA ═══════════════════════════════════════════════════════════════════════
console.log("§q · llega moviéndose");
const fisica = await page.evaluate(() => {
  const d = window.__cuarto.pieceData("t-mov");
  window.__openAbanico(d);
  const b = document.querySelector("#abActs .ab-act");
  const cs = getComputedStyle(b);
  return {
    anim: document.getElementById("abanico").dataset.anim,
    easing: cs.transitionTimingFunction,
    dur: cs.transitionDuration,
    props: cs.transitionProperty,
    motion: window.__abMotion(),
  };
});
ok(/cubic-bezier\(0\.22,\s*1\.2,\s*0\.36,\s*1\)/.test(fisica.easing),
   "ease-out cúbico con un pelo de overshoot (>1 en el 2º control)", fisica.easing);
ok(/transform/.test(fisica.props) && /opacity/.test(fisica.props),
   "lo que se anima es POSICIÓN y presencia, no un brillo", fisica.props);
ok(fisica.motion.step >= 20 && fisica.motion.step <= 30, "escalonado 20-30ms por ítem", fisica.motion.step + "ms");
ok(fisica.motion.total >= 150 && fisica.motion.total <= 210, "~180ms de punta a punta", fisica.motion.total + "ms");

// llegan escalonadas de verdad (medido en el DOM, no en el CSS)
await sleep(40);
const mitad = await page.evaluate(() => [...document.querySelectorAll("#abActs .ab-act")]
  .map((b) => Math.round(parseFloat(getComputedStyle(b).opacity) * 100)));
await sleep(400);
const final = await page.evaluate(() => [...document.querySelectorAll("#abActs .ab-act")]
  .map((b) => Math.round(parseFloat(getComputedStyle(b).opacity) * 100)));
ok(new Set(mitad).size > 1, "a mitad de camino NO están todas iguales: llegan escalonadas", mitad.join("/"));
ok(final.every((o) => o >= 99), "y todas terminan puestas", final.join("/"));

// ══ EL NO-VERDE LLEGA PRIMERO ═══════════════════════════════════════════════════════
console.log("\n§q · salvavidas · el no-verde llega PRIMERO");
/* [FIX-P3 · §2] la fixture cambia, la ley no. El salvavidas «el no-verde llega PRIMERO» se
 * mide sobre el slot del CAMINO, y tras la fusión ese slot ya no existe cuando la causa es
 * REINTENTABLE (ahí el camino ES [Probar de nuevo], que tiene su lugar fijo). Para medir el
 * camino hace falta una causa cuyo arreglo NO sea reintentar: `falta_key` → [Poner la
 * llave]. Ninguna aserción se afloja: cambia la pieza que se rompe. */
const turnos = await page.evaluate(async () => {
  window.__registrarDesenlace("t-mov", { res: { tipo: "mcp", ref: "x", estado: "roto", causa: "falta_key",
                                                evidencia: { detail: "falta la llave (fixture de la vara)" },
                                                ts: Math.floor(Date.now() / 1000) } });
  window.__closeAbanico(); window.__openAbanico(window.__cuarto.pieceData("t-mov"));
  await new Promise((r) => setTimeout(r, 400));
  return [...document.querySelectorAll("#abActs .ab-act")]
    .map((b) => ({ act: b.dataset.act, turno: Number(b.dataset.turno) }));
});
const camino = turnos.find((t) => t.act === "camino");
ok(camino && camino.turno === 0, "el camino del no-verde tiene el turno 0", JSON.stringify(turnos));
ok(turnos.findIndex((t) => t.act === "camino") > 0,
   "…pero CONSERVA su lugar en la lista (la posición es memoria muscular)",
   "posición " + turnos.findIndex((t) => t.act === "camino"));

// ══ LA PIEZA SE DESPEGA · LA SALA ATENÚA ════════════════════════════════════════════
console.log("\n§q · la pieza se despega · la sala atenúa");
const despegue = await page.evaluate(async () => {
  await new Promise((r) => setTimeout(r, 320));
  const l = window.__cuarto.pieceLiftState("t-mov");
  const st = document.getElementById("stage").dataset.abanico;
  const sc = getComputedStyle(document.getElementById("abScrim"));
  return { lift: l, stage: st, opacidad: sc.opacity, filtro: sc.filter, backdrop: sc.backdropFilter || "" };
});
ok(despegue.lift && despegue.lift.target === 1 && despegue.lift.lift > 0.5,
   "la pieza sube mientras su abanico está abierto", JSON.stringify(despegue.lift));
ok(despegue.stage === "1" && parseFloat(despegue.opacidad) > 0.05,
   "la sala se atenúa", `opacidad=${despegue.opacidad}`);
ok(!/blur/i.test(despegue.filtro) && !/blur/i.test(despegue.backdrop),
   "…ATENÚA, no desenfoca (cero blur)", `${despegue.filtro} | ${despegue.backdrop}`);

// ══ HOVER = PROFUNDIDAD, NO COLOR ═══════════════════════════════════════════════════
console.log("\n§q · hover acerca la opción (profundidad, no color)");
const hov = await page.evaluate(async () => {
  const b = document.querySelector('#abActs .ab-act[data-act="probar"]');
  const antes = getComputedStyle(b);
  const bg0 = antes.backgroundColor, sh0 = antes.boxShadow, tr0 = antes.transform;
  b.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
  // el :hover real de CSS no se dispara con eventos sintéticos: se lee la REGLA
  return { bg0, sh0, tr0 };
});
/* [FIX-P3 · §1] el selector se especificó (`#abanico .ab-act:hover`) al pasar el menú a
 * ARCO, y la profundidad ya no se pinta con un translateY fijo: la píldora ESCALA sobre su
 * propio punto del arco (`--ab-s`), que es lo que hace que se acerque sin salirse de la
 * curva. Sigue siendo profundidad, no color — y eso es lo que se mide. */
const reglaHover = (html.match(/#abanico \.ab-act:hover \{[^}]*\}/) || [""])[0];
ok(!!reglaHover, "existe la regla de hover del arco", reglaHover.slice(0, 60));
ok(/background:var\(--paper2\)/.test(reglaHover), "el hover NO cambia el color de fondo", reglaHover.slice(0, 70));
ok(/--ab-s:1\.0\d/.test(reglaHover) && /box-shadow/.test(reglaHover),
   "…acerca la opción: escala un pelo y proyecta sombra", "--ab-s + box-shadow");

// ══ SE RECOGE AL CERRAR ═════════════════════════════════════════════════════════════
console.log("\n§q · se recoge al cerrar");
const recoge = await page.evaluate(async () => {
  window.__closeAbanico();
  const inmediato = { anim: document.getElementById("abanico").dataset.anim,
                      oculto: document.getElementById("abanico").hidden };
  await new Promise((r) => setTimeout(r, 250));
  return { inmediato, despues: document.getElementById("abanico").hidden,
           lift: window.__cuarto.pieceLiftState("t-mov"), stage: document.getElementById("stage").dataset.abanico };
});
ok(recoge.inmediato.anim === "out" && !recoge.inmediato.oculto,
   "al cerrar se RECOGE primero (no desaparece de golpe)", JSON.stringify(recoge.inmediato));
ok(recoge.despues, "…y recién después se va");
ok(recoge.lift.target === 0, "la pieza vuelve a apoyarse");
ok(recoge.stage === "0", "y la sala recupera su luz");

// ══ SALVAVIDAS · SEGUNDO CLICK COMPLETA YA ══════════════════════════════════════════
console.log("\n§q · salvavidas · el segundo click completa ya");
const segundo = await page.evaluate(async () => {
  const d = window.__cuarto.pieceData("t-mov");
  window.__openAbanico(d);
  await new Promise((r) => setTimeout(r, 30));      // a mitad de la llegada
  const enVuelo = [...document.querySelectorAll("#abActs .ab-act")]
    .map((b) => Math.round(parseFloat(getComputedStyle(b).opacity) * 100));
  window.__openAbanico(d);                          // SEGUNDO click
  await new Promise((r) => setTimeout(r, 30));
  const trasSegundo = document.getElementById("abanico").dataset.anim;
  return { enVuelo, trasSegundo };
});
ok(segundo.trasSegundo === "in", "el segundo click deja todo puesto sin esperar", segundo.trasSegundo);

// ══ CERO NEÓN / CERO HOLOGRAMA ══════════════════════════════════════════════════════
console.log("\n§q · cero neón, cero holograma");
const bloque = (html.match(/#abanico \{ --ab-dur[\s\S]*?\.ab-act:active[^}]*\}/) || [""])[0];
ok(bloque.length > 100 && !/text-shadow|drop-shadow|glow|neon|saturate\(|hue-rotate/i.test(bloque),
   "el bloque del abanico no tiene brillos ni filtros de neón", `${bloque.length} chars`);

// ══ LA BANDERA ══════════════════════════════════════════════════════════════════════
console.log("\n§q · la bandera apaga la animación");
const { page: p2 } = await abrirPagina(browser, "?motion=0");
const flag = await p2.evaluate(async () => {
  const d = window.__cuarto.pieceData("t-mov");
  window.__openAbanico(d);
  const b = document.querySelector("#abActs .ab-act");
  const cs = getComputedStyle(b);
  const inmediato = { op: cs.opacity, dur: cs.transitionDuration, tr: cs.transform,
                      motion: document.getElementById("abanico").dataset.motion,
                      anim: document.getElementById("abanico").dataset.anim };
  window.__closeAbanico();
  return { inmediato, cerradoYa: document.getElementById("abanico").hidden, m: window.__abMotion().motion };
});
ok(flag.m === false && flag.inmediato.motion === "0", "?motion=0 apaga la física", JSON.stringify(flag.inmediato.motion));
ok(parseFloat(flag.inmediato.op) === 1 && /^(0s|none)$/.test(flag.inmediato.dur.split(",")[0].trim()),
   "las opciones están puestas de entrada, sin transición", `op=${flag.inmediato.op} dur=${flag.inmediato.dur}`);
ok(flag.cerradoYa, "…y cerrar es instantáneo");

await browser.close();
console.log(`\n${fails.length ? "✗ FALLOS: " + fails.length : "✓ TODO VERDE"}`);
fails.forEach((f) => console.log("   · " + f));
process.exit(fails.length ? 1 : 0);
