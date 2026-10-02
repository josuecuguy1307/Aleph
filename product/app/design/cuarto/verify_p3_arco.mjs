/* verify_p3_arco.mjs — FIX-P3 · EL ARCO, EL CANDADO Y EL PANEL.
 *
 * Mide, contra el SIDECAR FROZEN de esta rama (que sirve SU copia de design/ desde
 * _MEIPASS — el árbol de git es otro producto), las ocho cosas del mandato:
 *
 *   §1  EL ARCO      · las acciones ALREDEDOR de la pieza, no un card apilado.
 *                      Física de ola 4 cableada; la bandera la apaga y el menú SIGUE
 *                      funcionando; salvavidas 1 (2º click completa) y 2 (no-verde primero).
 *   §2  LA FUSIÓN    · una sola entrada de prueba; en rojo se llama [Probar de nuevo].
 *                      Cero botón «Reintentar» separado (grep + DOM).
 *   §3  EL ARCO ENTERO · 5 lugares + la línea de ESTADO al pie con su [?]; ▶ Play con
 *                      tokens de la casa, no verde sapo.
 *   §4  EL CANDADO   · UNO por pieza, PEGADO al cable, sólo si toca afuera. Pieza de pura
 *                      lectura: sin candado NI ofrecido. Popup con las cuatro cosas + el
 *                      piso honesto de [Quitar].
 *   §5  BUG #34      · cada salida del popup aparece UNA vez.
 *   §6  UN DUEÑO     · el registro no copia el error; [Ver error →] lleva a la pieza;
 *                      con pieza rota el texto del error está UNA vez en todo el DOM.
 *   §7  LAS FILAS    · la lista de piezas no existe; el panel es sólo registro.
 *   §8  LA CARRERA   · bajo carga, el repintado no pisa el latido ni el desenlace.
 *
 * Trae CALIBRACIONES EN ROJO: con el trabajo deshecho a mano, las aserciones caen.
 *
 * Run:  node qa/p3_frozen.mjs &            (levanta el frozen en :8273)
 *       node product/app/design/cuarto/verify_p3_arco.mjs
 */
import { webkit } from "playwright";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const SHOTS = join(HERE, "screenshots");
const BASE = process.env.SIDECAR || "http://127.0.0.1:8273";
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const fails = [];
const ok = (c, label, extra) => {
  console.log(`${c ? "✓" : "✗"} ${label}${extra != null && extra !== "" ? "  — " + extra : ""}`);
  if (!c) fails.push(label);
};

try {
  const r = await fetch(BASE + "/health");
  if (!r.ok) throw new Error("health " + r.status);
  console.log(`── frozen ${BASE} vivo\n`);
} catch (e) {
  console.log(`✗ el sidecar ${BASE} no responde (${e.message}) — corré primero: node qa/p3_frozen.mjs &`);
  process.exit(1);
}

const SEED = [
  // toca afuera (github: create_issue) · pura lectura (arxiv) · una que rompe de verdad
  { id: "p-gh", label: "GitHub", server: "github", connector: "github", atom: "tool", role: "mesa",
    tools: ["create_issue", "list_repos"], gx: 1, gy: 1 },
  /* PURA LECTURA de verdad, según el MOTOR y no según la intuición: el advisor clasifica
   * `search_*` como **exfil** (consecuente) porque la consulta SALE de tu máquina, aunque
   * no escriba nada. Así que una pieza «de sólo leer» con un buscador adentro SÍ toca
   * afuera — y lleva candado, con razón. La fixture usa tools que el motor declara
   * `lectura` pura (get/find de un visor médico), que es el caso del mandato. */
  { id: "p-lee", label: "Dicom", server: "orthanc", atom: "tool", role: "fuentes",
    auth: "keyless", tools: ["find_study", "get_paper"], gx: -2, gy: 0 },
];

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errs = [];
page.on("pageerror", (e) => errs.push(String(e)));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|401/.test(m.text())) errs.push(m.text()); });
await page.goto(PAGE, { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => window.__cuarto && window.__openAbanico && window.__abanicoArco, null, { timeout: 60000 });
await sleep(1500);
await page.evaluate((seed) => {
  const c = window.__cuarto;
  c.placedTiles().forEach((t) => c.removeTile(t.id));
  for (const s of seed) c.placeTile(s, s.gx, s.gy);
  window.__sync && window.__sync();
}, SEED);
await page.waitForFunction(() => window.__advisorReady === true, null, { timeout: 20000 }).catch(() => {});
await sleep(1200);

// ═══ §1 · EL ARCO ════════════════════════════════════════════════════════════════════
console.log("§1 · EL ARCO — las acciones alrededor de la pieza");
await page.evaluate(() => window.__openAbanico(window.__cuarto.pieceData("p-gh")));
await sleep(700);
const arco = await page.evaluate(() => window.__abanicoArco());
const radios = arco.items.map((i) => i.radio);
const spread = Math.max(...radios) - Math.min(...radios);
ok(arco.items.length >= 4, "el arco abre con sus lugares", `n=${arco.items.length}`);
ok(spread <= 6, "TODOS los ítems a la MISMA distancia de la pieza: es un arco, no una pila",
   `radios=${radios.join("/")} · spread=${spread}px`);
const angs = arco.items.map((i) => i.ang).sort((a, b) => a - b);
const pasos = angs.slice(1).map((a, i) => a - angs[i]);
ok(pasos.length > 0 && pasos.every((p) => p > 8),
   "…y repartidos por ÁNGULO alrededor de ella (cero solape)", `ángulos=${angs.join("/")}`);
const xs = new Set(arco.items.map((i) => i.dx));
ok(xs.size > 1, "…con x que VARÍA: un card apilado tendría todos los x iguales", `dx únicos=${xs.size}`);
ok(!arco.items.some((i) => i.dx === 0 && i.dy === 0), "ningún ítem cae ENCIMA de la pieza");

// la caja: el contenedor NO es un card (sin fondo propio)
const caja = await page.evaluate(() => {
  const b = document.getElementById("abanico"), cs = getComputedStyle(b);
  return { bg: cs.backgroundColor, sombra: cs.boxShadow, w: b.offsetWidth, h: b.offsetHeight };
});
ok(/rgba\(0, 0, 0, 0\)|transparent/.test(caja.bg) && caja.sombra === "none",
   "§1 · el contenedor del arco NO tiene caja: es un punto sobre la pieza", JSON.stringify(caja));

// ── FÍSICA: llegan escalonadas, salen DESDE la pieza, y se recogen al cerrar ──
/* DICTAMEN P3-CIERRE · PROXY MUERTO.
 * Esta vara medía `DOMMatrix.m41/m42` como si fueran el radio del arco. Eso dejó de ser
 * cierto cuando el arco se ancló por el CENTRO visible de cada píldora: el `transform`
 * incluye `translate(... -50%, ... -50%)`, o sea que m41/m42 mezclan recorrido físico con
 * el tamaño real del botón. La ley sigue siendo la misma —parten en la pieza y terminan en
 * el arco— pero el instrumento correcto es screen-space: centro visible de `.ab-act` menos
 * centro del ancla `#abanico`, igual que `verify_p3_cierre.mjs`.
 */
const fisica = await page.evaluate(async () => {
  window.__closeAbanico(); await new Promise((r) => setTimeout(r, 200));
  window.__openAbanico(window.__cuarto.pieceData("p-gh"));
  const lee = () => [...document.querySelectorAll("#abActs .ab-act")].map((b) => {
    const anchor = document.getElementById("abanico").getBoundingClientRect();
    const box = b.getBoundingClientRect();
    const cs = getComputedStyle(b);
    const cx = box.left + box.width / 2, cy = box.top + box.height / 2;
    return { op: Math.round(parseFloat(cs.opacity) * 100),
             r: Math.round(Math.hypot(cx - anchor.left, cy - anchor.top)) };
  });
  const t0 = lee();                                    // punto de partida: sobre la pieza
  await new Promise((r) => setTimeout(r, 60));
  const mid = lee();
  await new Promise((r) => setTimeout(r, 500));
  const fin = lee();
  return { t0, mid, fin };
});
ok(fisica.t0.every((x) => x.r < 30), "FÍSICA · parten PEGADAS a la pieza (radio ~0)", JSON.stringify(fisica.t0.map((x) => x.r)));
ok(new Set(fisica.mid.map((x) => x.op)).size > 1, "…llegan ESCALONADAS (a mitad no están todas iguales)", fisica.mid.map((x) => x.op).join("/"));
ok(fisica.fin.every((x) => x.op >= 99 && x.r > 60), "…y terminan puestas, sobre el arco", JSON.stringify(fisica.fin.map((x) => x.r)));
const recoge = await page.evaluate(async () => {
  window.__closeAbanico();
  await new Promise((r) => setTimeout(r, 30));
  const b = document.querySelector("#abActs .ab-act");
  return { anim: document.getElementById("abanico").dataset.anim, op: b ? getComputedStyle(b).opacity : null };
});
ok(recoge.anim === "out", "…y al cerrar SE RECOGEN por el mismo camino", JSON.stringify(recoge));

// ── SALVAVIDAS 1 · el segundo click completa YA ──
const salva1 = await page.evaluate(async () => {
  window.__closeAbanico(); await new Promise((r) => setTimeout(r, 250));
  const d = window.__cuarto.pieceData("p-gh");
  window.__openAbanico(d);                       // arranca la llegada…
  await new Promise((r) => setTimeout(r, 20));
  window.__openAbanico(d);                       // …segundo click MIENTRAS llega
  await new Promise((r) => setTimeout(r, 10));
  const b = document.querySelector("#abActs .ab-act");
  return { anim: document.getElementById("abanico").dataset.anim,
           delay: b ? getComputedStyle(b).transitionDelay : null };
});
ok(salva1.anim === "in", "SALVAVIDAS 1 · el segundo click COMPLETA la llegada, no la reinicia", JSON.stringify(salva1));

// ── SALVAVIDAS 2 · el no-verde llega PRIMERO ──
const salva2 = await page.evaluate(async () => {
  window.__registrarDesenlace("p-gh", { res: { tipo: "mcp", ref: "github", estado: "roto", causa: "falta_key",
                                               evidencia: { detail: "sin llave (fixture)" }, ts: Math.floor(Date.now() / 1000) } });
  window.__closeAbanico(); window.__openAbanico(window.__cuarto.pieceData("p-gh"));
  await new Promise((r) => setTimeout(r, 400));
  return [...document.querySelectorAll("#abActs .ab-act")]
    .map((b, i) => ({ act: b.dataset.act, turno: Number(b.dataset.turno), pos: i }));
});
const cam = salva2.find((x) => x.act === "camino");
ok(cam && cam.turno === 0, "SALVAVIDAS 2 · el no-verde LLEGA PRIMERO (turno 0)", JSON.stringify(salva2));
ok(cam && cam.pos > 0, "…pero conserva su LUGAR en el arco (la posición es memoria muscular)", `pos=${cam && cam.pos}`);

// ── LA BANDERA APAGA LA FÍSICA Y EL MENÚ SIGUE FUNCIONANDO ──
const p2 = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await p2.goto(PAGE + "?motion=0", { waitUntil: "domcontentloaded" });
await p2.waitForFunction(() => window.__cuarto && window.__openAbanico, null, { timeout: 60000 });
await sleep(1400);
await p2.evaluate((seed) => {
  const c = window.__cuarto;
  c.placedTiles().forEach((t) => c.removeTile(t.id));
  for (const s of seed) c.placeTile(s, s.gx, s.gy);
}, SEED);
await sleep(600);
const flag = await p2.evaluate(async () => {
  window.__openAbanico(window.__cuarto.pieceData("p-gh"));
  await new Promise((r) => setTimeout(r, 10));       // SIN esperar la animación
  const b = document.querySelector("#abActs .ab-act");
  const cs = b ? getComputedStyle(b) : null;
  const m = cs ? new DOMMatrixReadOnly(cs.transform) : null;
  return { motion: document.getElementById("abanico").dataset.motion,
           dur: cs && cs.transitionDuration, op: cs && Math.round(parseFloat(cs.opacity) * 100),
           r: m ? Math.round(Math.hypot(m.m41, m.m42)) : null,
           acts: window.__abanicoActs().length };
});
ok(flag.motion === "0" && /^0s/.test(flag.dur || ""), "BANDERA · ?motion=0 apaga la física entera", JSON.stringify(flag));
ok(flag.op === 100 && flag.r > 60 && flag.acts >= 4,
   "…y el menú queda 100% FUNCIONAL: el arco entero, puesto de entrada", JSON.stringify(flag));
// …y las acciones ACTÚAN con la física apagada
const flagActua = await p2.evaluate(async () => {
  const b = document.querySelector('#abActs .ab-act[data-act="tools"]');
  b.click(); await new Promise((r) => setTimeout(r, 200));
  return window.__toolWidget();
});
ok(flagActua.abierto, "…y sus acciones ACTÚAN igual (con la bandera puesta)", JSON.stringify(flagActua));
await p2.close();

// ═══ §2 · LA FUSIÓN ══════════════════════════════════════════════════════════════════
console.log("\n§2 · LA FUSIÓN — un disparo, un rótulo");
const fus = await page.evaluate(async () => {
  const C = window.__cuarto;
  window.__olvidarDesenlace("p-gh"); window.CuartoSemaforo.reiniciarIntentos();
  window.__closeAbanico(); window.__openAbanico(C.pieceData("p-lee"));   // 🟡 sin probar
  await new Promise((r) => setTimeout(r, 300));
  const amarillo = window.__abanicoActs();
  window.__registrarDesenlace("p-lee", { res: { tipo: "mcp", ref: "arxiv", estado: "roto", causa: "error_upstream",
                                                evidencia: { detail: "caído (fixture)" }, ts: Math.floor(Date.now() / 1000) } });
  window.__closeAbanico(); window.__openAbanico(C.pieceData("p-lee"));
  await new Promise((r) => setTimeout(r, 300));
  return { amarillo, rojo: window.__abanicoActs() };
});
const et = (a) => (a.find((x) => x.act === "probar") || {}).label || "";
ok(/Probar\b/.test(et(fus.amarillo)) && !/de nuevo/.test(et(fus.amarillo)),
   "🟡 sin probar → [Probar]", et(fus.amarillo));
ok(/Probar de nuevo/.test(et(fus.rojo)), "🔴 roto → EL MISMO botón pasa a [Probar de nuevo]", et(fus.rojo));
ok(fus.amarillo.filter((a) => a.act === "probar").length === 1 &&
   fus.rojo.filter((a) => a.act === "probar").length === 1,
   "…una SOLA entrada de prueba en los dos estados");
const sueltos = await page.evaluate(() =>
  [...document.querySelectorAll("button,a")].filter((b) => /reintentar|retry/i.test((b.textContent || "").trim()))
    .map((b) => b.textContent.trim()));
ok(sueltos.length === 0, "§2 · CERO botón «Reintentar» separado en el DOM del Cuarto", sueltos.join("|") || "ninguno");
// …y en el CÓDIGO: ninguna superficie del Cuarto escribe ese rótulo
const src = ["cuarto.pixi.html", "cuarto.semaforo.js"].map((f) => readFileSync(join(HERE, f), "utf8")).join("\n");
const grep = (src.match(/"Reintentar"|>Reintentar<|'Reintentar'/g) || []);
ok(grep.length === 0, "§2 · GREP · cero rótulo «Reintentar» en el código del Cuarto", grep.join(" ") || "0 ocurrencias");

// ═══ §3 · EL ARCO COMPLETO + EL PIE + EL ▶ PLAY ══════════════════════════════════════
console.log("\n§3 · el arco completo, la línea de estado y el ▶ Play");
const completo = await page.evaluate(async () => {
  window.__closeAbanico(); window.__openAbanico(window.__cuarto.pieceData("p-gh"));
  await new Promise((r) => setTimeout(r, 350));
  return { acts: window.__abanicoActs().map((a) => a.act), pie: window.__abanicoEstado() };
});
ok(["tools", "probar", "asegurar", "quitar"].every((a) => completo.acts.includes(a)),
   "§3 · [Ver tools] · [Probar] · [Asegurar] · [Quitar]", completo.acts.join("·"));
ok(completo.acts.includes("camino"), "§3 · …+ [El camino], porque la pieza no está verde", completo.acts.join("·"));
ok(completo.pie && completo.pie.estado === "roto" && /Roto/.test(completo.pie.txt),
   "§3 · el ESTADO va como línea AL PIE («Roto · causa»)", completo.pie && completo.pie.txt);
ok(completo.pie && /Falta tu llave/.test(completo.pie.txt), "…nombrando la CAUSA", completo.pie && completo.pie.txt);
ok(completo.pie && completo.pie.ayuda, "…con su [?] (§10: la UI opera, docs/guia explica)");
const guia = await page.evaluate(async () => {
  const b = document.querySelector("#abEstado [data-guia]");
  if (!b) return { falta: true };
  const ancla = b.dataset.guia;
  b.click(); await new Promise((r) => setTimeout(r, 900));
  const pop = document.getElementById("ayudapop");
  return { ancla, abrio: !!pop, txt: pop ? pop.textContent.slice(0, 90) : null };
});
ok(guia.ancla === "piezas#estado", "…apuntando a la sección real de docs/guia", guia.ancla);
ok(guia.abrio && !/no pude|falló/i.test(guia.txt || ""), "…y el [?] ABRE esa sección desde el frozen", (guia.txt || "").slice(0, 60));
// el ▶ Play con tokens de la casa
const play = await page.evaluate(() => {
  const b = document.getElementById("salaBtn"); const cs = getComputedStyle(b);
  const acc = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  return { bg: cs.backgroundColor, img: cs.backgroundImage, accent: acc };
});
ok(!/gradient/.test(play.img) && !/79, 224, 168|47, 201, 140/.test(play.bg + play.img),
   "§3 · el ▶ Play dejó el verde sapo hardcodeado", JSON.stringify(play));
ok(!!play.accent, "…y usa el acento de la casa (--accent)", `${play.accent} → ${play.bg}`);

await page.evaluate(() => { window.__closeAbanico(); });
await sleep(200);
await page.evaluate(() => window.__openAbanico(window.__cuarto.pieceData("p-gh")));
await sleep(700);
await page.screenshot({ path: join(SHOTS, "p3-arco.png") });
console.log("  → screenshots/p3-arco.png");

// ═══ §4 · EL CANDADO ═════════════════════════════════════════════════════════════════
console.log("\n§4 · el candado: UNO por pieza, pegado al cable, sólo si toca afuera");
const cd = await page.evaluate(() => {
  const C = window.__cuarto;
  return { ids: C.candados(), gh: C.candado("p-gh"), lee: C.candado("p-lee"),
           tocaGh: window.__tocaAfuera("p-gh"), tocaLee: window.__tocaAfuera("p-lee") };
});
ok(cd.tocaGh === true && cd.tocaLee === false,
   "§4 · el predicado distingue la que toca afuera de la que sólo lee", JSON.stringify({ gh: cd.tocaGh, lee: cd.tocaLee }));
ok(cd.lee === null, "§4 · ASSERT · pieza de PURA LECTURA → SIN candado");
const arcoLee = await page.evaluate(async () => {
  window.__closeAbanico(); window.__openAbanico(window.__cuarto.pieceData("p-lee"));
  await new Promise((r) => setTimeout(r, 300));
  const a = window.__abanicoActs().map((x) => x.act);
  window.__openCandado(window.__cuarto.pieceData("p-lee"));
  await new Promise((r) => setTimeout(r, 200));
  return { acts: a, popup: window.__candado().abierto };
});
ok(!arcoLee.acts.includes("asegurar"), "§4 · ASSERT · …NI OFRECIDO: su arco no tiene [Asegurar]", arcoLee.acts.join("·"));
ok(arcoLee.popup === false, "§4 · …y ni siquiera se puede abrir su candado a la fuerza");
ok(cd.ids.length === new Set(cd.ids).size, "§4 · UNO por pieza: cero candados repetidos", JSON.stringify(cd.ids));
ok(cd.gh && cd.gh.dCable <= 1.5,
   "§4 · ASSERT DE ANCLAJE · el candado está PEGADO al cable (cero flotando)", `dCable=${cd.gh && cd.gh.dCable.toFixed(2)}px`);
ok(cd.gh && cd.gh.dPieza > 12 && cd.gh.dNucleo > 12,
   "§4 · …SOBRE el cable, no encima de la pieza ni del Núcleo",
   `pieza=${Math.round(cd.gh.dPieza)}px núcleo=${Math.round(cd.gh.dNucleo)}px`);
// el popup con las CUATRO cosas + el piso honesto
const pop = await page.evaluate(async () => {
  const C = window.__cuarto, d = C.pieceData("p-gh");
  window.__openCandado(d); await new Promise((r) => setTimeout(r, 250));
  const reglas = [...document.querySelectorAll("#cdReglas .cd-r")].map((b) => b.dataset.regla);
  const st0 = window.__candado();
  document.querySelector('#cdReglas .cd-r[data-regla="stop"]').click();
  await new Promise((r) => setTimeout(r, 200));
  const siempre = window.__candado();
  document.querySelector('#cdReglas .cd-r[data-regla="auto"]').click();
  await new Promise((r) => setTimeout(r, 200));
  return { reglas, que: st0.que, veces: st0.veces, siempre: siempre.regla,
           quitado: window.__candado(), gated: !!C.pieceData("p-gh").gated,
           decisiones: (document.getElementById("cdDecisiones") || {}).getAttribute("href"),
           ayuda: !!document.querySelector("#candado [data-guia]") };
});
ok(/frena|Frena/.test(pop.que), "§4 · popup · dice QUÉ frena", pop.que.slice(0, 70));
ok(JSON.stringify(pop.reglas) === JSON.stringify(["stop", "ok", "auto"]),
   "§4 · popup · la regla: siempre · una vez · quitar", pop.reglas.join("/"));
ok(/vez|veces|Todavía/.test(pop.veces), "§4 · popup · dice CUÁNTAS veces frenó", pop.veces);
ok(/Historial/.test(pop.decisiones || ""), "§4 · popup · el botón a las decisiones", pop.decisiones);
ok(pop.siempre === "stop" && pop.quitado.regla === "auto" && pop.gated === false,
   "§4 · popup · elegir la regla la APLICA de verdad", `${pop.siempre} → ${pop.quitado.regla}`);
ok(/plata y envíos/.test(pop.quitado.piso || ""),
   "§4 · popup · el PISO HONESTO de [Quitar]: el motor retiene plata y envíos", pop.quitado.piso);
ok(pop.ayuda, "§4 · popup · con su [?] a docs/guia");
await page.evaluate(() => { document.getElementById("cdClose").click(); });

// ═══ §7 · LAS FILAS MUEREN ═══════════════════════════════════════════════════════════
console.log("\n§7 · las filas mueren: el panel es sólo registro");
const filas = await page.evaluate(() => ({
  pieceList: !!document.getElementById("pieceList"),
  prow: document.querySelectorAll(".prow").length,
  prowOut: document.querySelectorAll(".prow-out").length,
  legend: !!document.getElementById("legend"),
  logList: !!document.getElementById("logList"),
}));
ok(!filas.pieceList && filas.prow === 0 && filas.prowOut === 0,
   "§7 · la lista de piezas NO EXISTE (ni el contenedor, ni una fila)", JSON.stringify(filas));
ok(filas.legend && filas.logList, "§7 · …y el panel sigue vivo como REGISTRO", JSON.stringify(filas));

// ═══ §5 §6 · EL POPUP DE MUTACIÓN Y EL DUEÑO DEL ERROR ═══════════════════════════════
console.log("\n§5 §6 · el popup de mutación (#34) y el dueño del error");
const dueño = await page.evaluate(async () => {
  const C = window.__cuarto;
  window.__limpiarLogs(); window.__legendOpen(true);
  window.CuartoSemaforo.reiniciarIntentos(); window.__olvidarDesenlace("p-gh");
  window.__closeAbanico();
  window.__semLatidoInstante = true;
  await window.__probarPieza("p-gh", { motivo: "manual" });   // 1ª → rojo real del motor
  await window.__probarPieza("p-gh", { motivo: "reintento" }); // 2ª → gasta el reintento
  await new Promise((r) => setTimeout(r, 700));
  const d = (window.__desenlaces() || []).find((x) => x.id === "p-gh");
  const frag = d ? String(d.crudo || "").split("\n")[0].trim() : "";
  const copias = (raiz) => frag.length < 8 ? -1
    : [...raiz.querySelectorAll("*")].filter((el) => !el.children.length && (el.textContent || "").includes(frag)).length;
  const fila = document.querySelector("#logList .logrow.bad");
  return { frag, cerrado: copias(document), hayVer: !!(fila && fila.querySelector("[data-ver]")),
           pieza: fila ? (fila.querySelector(".logp") || {}).textContent : null,
           hora: fila ? (fila.querySelector(".logt") || {}).textContent : null,
           lineas: document.querySelectorAll("#logList .logrow").length };
});
ok(dueño.lineas >= 1 && dueño.pieza && /^\d\d:\d\d$/.test(dueño.hora || ""),
   "§6 · el registro guarda UNA LÍNEA por evento: pieza · qué pasó · hora",
   `${dueño.pieza} · ${dueño.hora} · ${dueño.lineas} línea(s)`);
ok(dueño.hayVer, "§6 · …con [Ver error →], que es el único camino al error desde el registro");
ok(dueño.cerrado === 0, "§6 · ASSERT · el panel NO copia el error: con el popup cerrado, 0 en el DOM",
   `«${dueño.frag.slice(0, 44)}» ×${dueño.cerrado}`);
const abierto = await page.evaluate(async (frag) => {
  document.querySelector("#logList .logrow.bad [data-ver]").click();
  await new Promise((r) => setTimeout(r, 700));
  const pop = document.getElementById("abanico");
  const cru = document.querySelector("#abMsg .sem-out-crudo");
  const cuenta = (raiz, f) => [...raiz.querySelectorAll("*")].filter((el) => !el.children.length && (el.textContent || "").trim() === f).length;
  return {
    arco: window.__abanicoAbierto(), crudoAbierto: cru ? cru.open : null,
    copias: [...document.querySelectorAll("*")].filter((el) => !el.children.length && (el.textContent || "").includes(frag)).length,
    // [INTEGRACIÓN P11] P3 es dueño de la UNICIDAD del pliegue; P11 es dueño de su rótulo:
    // «Ver el detalle» para probado/detectado y «Ver el error completo» para un rojo real.
    // Contar ambos y exigir suma=1 conserva el assert duro sin congelar la ley vieja.
    verDetalle: cuenta(pop, "Ver el detalle"), verError: cuenta(pop, "Ver el error completo"),
    aMano: cuenta(pop, "Probar el server a mano"),
    quitar: cuenta(pop, "Quitar"), arreglar: cuenta(pop, "Arreglarlo") + cuenta(pop, "Configurar"),
  };
}, dueño.frag);
ok(abierto.arco && abierto.crudoAbierto === true,
   "§6 · [Ver error →] ENFOCA la pieza y abre SU popup con el crudo destapado", JSON.stringify({ arco: abierto.arco, abierto: abierto.crudoAbierto }));
ok(abierto.copias === 1, "§6 · VARA DE UNICIDAD · el texto del error aparece UNA vez en TODO el DOM", `copias=${abierto.copias}`);
ok(abierto.verDetalle + abierto.verError === 1 &&
   abierto.aMano === 1 && abierto.quitar === 1 && abierto.arreglar === 1,
   "§5 · BUG #34 CERRADO · cada salida del popup, UNA vez", JSON.stringify(abierto));
await page.screenshot({ path: join(SHOTS, "p3-popup-mutacion.png") });
console.log("  → screenshots/p3-popup-mutacion.png");

// ═══ §2 · [Probar de nuevo] → latido → desenlace REAL ════════════════════════════════
console.log("\n§2 · [Probar de nuevo] → latido → desenlace real");
let posts = 0;
page.on("request", (r) => { if (/\/v1\/motor\/probar/.test(r.url())) posts++; });
await page.evaluate(() => { window.__semLatidoInstante = false; });
const SEL = '#abActs .ab-act[data-act="probar"]';
const caja2 = await page.evaluate((s) => {
  const el = document.querySelector(s); if (!el) return null;
  const r = el.getBoundingClientRect();
  const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: Math.round(r.width),
           tapado: !(top === el || el.contains(top)), txt: el.textContent.trim() };
}, SEL);
ok(caja2 && caja2.w > 0 && !caja2.tapado, "el [Probar de nuevo] del arco es alcanzable por un MOUSE REAL", JSON.stringify(caja2));
posts = 0;
await page.mouse.click(caja2.x, caja2.y);
const lat = await page.evaluate((s) => {
  const el = document.querySelector(s); if (!el) return { falta: true };
  const t = el.querySelector(".ab-t") || el;
  return { probando: el.dataset.probando === "1", txt: (t.textContent || "").trim() };
}, SEL);
ok(lat.probando && /Probando/i.test(lat.txt), "LATIDO sobre el botón que se apretó", JSON.stringify(lat));
await sleep(3000);
ok(posts >= 1, "…prueba REAL contra el motor (POST /v1/motor/probar)", `posts=${posts}`);
const des = await page.evaluate(() => {
  const h = document.getElementById("abMsg");
  return { hay: !!h.querySelector(".sem-out-linea"),
           tit: (h.querySelector(".sem-out-tit") || {}).textContent,
           sub: (h.querySelector(".sem-out-sub") || {}).textContent,
           crudo: (h.querySelector(".sem-out-crudo pre") || {}).textContent };
});
ok(des.hay && /\d\d:\d\d:\d\d/.test(des.sub || ""), "DESENLACE con hora, no un repintado mudo", `${des.tit} · ${des.sub}`);
ok(!!des.crudo && des.crudo.length > 10, "…con el error REAL plegado debajo", (des.crudo || "").slice(0, 60));

// ═══ CALIBRACIONES EN ROJO ═══════════════════════════════════════════════════════════
console.log("\n══ CALIBRACIONES EN ROJO — con el trabajo deshecho, esto TIENE que caer ══");
const calArco = await page.evaluate(async () => {
  // se le saca al arco su geometría (lo que hacía el card apilado): todos al mismo punto,
  // en columna. …y se ESPERA a que la transición termine: medir el rect en el mismo tick
  // devolvería el arco viejo — la vara se mediría a sí misma, no al DOM.
  document.querySelectorAll("#abActs .ab-act").forEach((b, i) => {
    b.style.setProperty("--ab-x", "0"); b.style.setProperty("--ab-y", String(i * 0.5));
  });
  await new Promise((r) => setTimeout(r, 500));
  const a = window.__abanicoArco();
  const rr = a.items.map((i) => i.radio);
  return { spread: Math.max(...rr) - Math.min(...rr), xs: new Set(a.items.map((i) => i.dx)).size };
});
ok(calArco.xs === 1 && calArco.spread > 6,
   "CALIBRACIÓN §1 · apilados en una columna, la vara del ARCO los caza", JSON.stringify(calArco));
const calCandado = await page.evaluate(async () => {
  const C = window.__cuarto, d = C.pieceData("p-lee");
  d.gated = true; try { C.setGated("p-lee", true); } catch (e) {}
  // `candado()` lee lo que dibujó el ÚLTIMO frame: leerlo en el mismo tick devuelve el
  // estado de antes del cambio — la vara se mediría a sí misma.
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  return { lee: C.candado("p-lee") };            // ahora SÍ tiene candado: ya no es solo-lectura
});
ok(calCandado.lee !== null,
   "CALIBRACIÓN §4 · si una pieza de solo-lectura recibiera candado, la vara lo vería", JSON.stringify(calCandado.lee && calCandado.lee.estado));

ok(errs.length === 0, "0 errores de JS/consola en toda la corrida", errs.slice(0, 2).join(" | "));
await browser.close();

console.log("\n" + "─".repeat(72));
if (fails.length) { console.log(`✗ ${fails.length} FALLA(S):\n  - ` + fails.join("\n  - ")); process.exit(1); }
console.log("✓ TODO VERDE — el arco, la fusión, el candado sobre el cable, el #34, el dueño del error y las filas muertas.");
