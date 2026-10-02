/* p3_carrera.mjs — §8 · LA CARRERA DEL REPINTADO, medida BAJO CARGA.
 *
 * La deuda de P1A: «el repintado pisa el latido/desenlace, reproducible bajo carga». Esta
 * sonda no confía en el azar: FABRICA la contención. Interpone el GET barato
 * (/v1/motor/estado) con un retardo grande y deja el POST (/v1/motor/probar) rápido, que es
 * exactamente la forma que tiene la carrera en la vida real (la lectura tarda más que la
 * prueba). Después dispara N barridos EN MEDIO de la prueba y mira dos cosas:
 *
 *   A · el LATIDO sobrevive: el botón que se apretó sigue diciendo "Probando…" mientras
 *       corre, y sigue siendo EL MISMO nodo del DOM (no lo reemplazó un repintado).
 *   B · el DESENLACE manda: cuando todo aterriza, el estado de la pieza es el de la PRUEBA,
 *       no el de una lectura vieja que llegó tarde.
 *
 * Y trae su CALIBRACIÓN EN ROJO: con el guard de época desarmado (window.__p3SinEpoca = 1)
 * las mismas aserciones tienen que FALLAR. Si pasan igual, la sonda es ciega.
 *
 * Run: SIDECAR=http://127.0.0.1:8273 node qa/p3_carrera.mjs
 */
import { webkit } from "playwright";
const BASE = process.env.SIDECAR || "http://127.0.0.1:8273";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [];
const ok = (c, l, x) => { console.log(`${c ? "✓" : "✗"} ${l}${x != null && x !== "" ? "  — " + x : ""}`); if (!c) fails.push(l); };

const b = await webkit.launch();
const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("  [pageerror]", String(e).slice(0, 300)));

/* LA CONTENCIÓN, fabricada: el GET tarda 900ms; el POST vuelve enseguida y en ROJO.
 * Es la asimetría real bajo carga — y la que hace que una lectura ARRANCADA ANTES del click
 * termine DESPUÉS de la prueba. */
await page.route("**/v1/motor/estado*", async (route) => {
  await new Promise((r) => setTimeout(r, 900));
  await route.fulfill({ status: 200, contentType: "application/json",
    body: JSON.stringify({ tipo: "mcp", ref: "cfd", estado: "detectado", causa: null,
                           evidencia: { detail: "LECTURA VIEJA" }, ts: Math.floor(Date.now() / 1000) }) });
});
await page.route("**/v1/motor/probar*", async (route) => {
  await route.fulfill({ status: 200, contentType: "application/json",
    body: JSON.stringify({ tipo: "mcp", ref: "cfd", estado: "roto", causa: "error_upstream",
                           evidencia: { detail: "LA PRUEBA REAL" }, ts: Math.floor(Date.now() / 1000) }) });
});

await page.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => window.__cuarto && window.__probarPieza && window.__openAbanico, null, { timeout: 30000 });
await sleep(1200);

async function corrida(conGuard) {
  await page.evaluate((g) => {
    window.__p3SinEpoca = g ? 0 : 1;
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeTile({ id: "t-carrera", label: "CFD", server: "cfd", belt_ref: "cfd", atom: "tool",
                  role: "mesa", auth: "keyless", tools: ["solve"] }, 1, 1);
    window.__limpiarLogs();
  }, conGuard);
  await sleep(300);
  return page.evaluate(async () => {
    const $ = (i) => document.getElementById(i);
    window.__openAbanico(window.__cuarto.pieceData("t-carrera"));
    await new Promise((r) => setTimeout(r, 250));
    const btn = document.querySelector('#abActs .ab-act[data-act="probar"]');
    if (!btn) return { sinBoton: true };
    // 1) un barrido ARRANCA ANTES del click: su GET tarda 900ms y va a llegar tarde
    window.__renderPieces();
    await new Promise((r) => setTimeout(r, 60));
    // 2) el click. El latido cae sobre ESTE nodo.
    const marca = "p3-" + Math.random().toString(36).slice(2);
    btn.dataset.marca = marca;
    const p = btn.click();
    // 3) …y MÁS barridos encima, mientras la prueba corre (la carga de verdad)
    for (let i = 0; i < 6; i++) { window.__renderPieces(); await new Promise((r) => setTimeout(r, 40)); }
    const vivo = document.querySelector('#abActs .ab-act[data-act="probar"]');
    const latido = { mismoNodo: !!(vivo && vivo.dataset.marca === marca),
                     probando: !!(vivo && vivo.dataset.probando === "1"),
                     txt: vivo ? vivo.textContent.trim() : null };
    await p;
    // 4) todo aterriza: incluida la lectura vieja de 900ms
    await new Promise((r) => setTimeout(r, 1600));
    const d = (window.__desenlaces() || [])[0] || null;
    return { latido, carrera: window.__carrera(),
             estadoFinal: (window.__abanicoEstado ? window.__abanicoEstado() : null),
             pie: ($("abEstado") || {}).textContent || "",
             desenlace: d ? { estado: d.estado, causa: d.causa } : null };
  });
}

console.log("\n── CON el guard de época (el arreglo) ────────────────────────────────");
const c1 = await corrida(true);
console.log("  ", JSON.stringify(c1));
ok(c1.latido && c1.latido.mismoNodo, "A · el botón que se apretó SIGUE siendo el mismo nodo bajo carga", JSON.stringify(c1.latido));
ok(c1.latido && c1.latido.probando && /Probando/i.test(c1.latido.txt || ""), "A · …y su LATIDO sigue vivo (no lo borró un repintado)", c1.latido && c1.latido.txt);
ok(/Roto/i.test(c1.pie), "B · el pie del arco quedó con el resultado de LA PRUEBA, no con la lectura vieja", c1.pie.trim());
ok(c1.carrera && c1.carrera.descartados > 0, "B · …y las lecturas que llegaron tarde se DESCARTARON", `descartados=${c1.carrera && c1.carrera.descartados}`);

console.log("\n── CALIBRACIÓN EN ROJO · sin el guard, esto TIENE que fallar ─────────");
const c2 = await corrida(false);
console.log("  ", JSON.stringify(c2));
const rojo = !/Roto/i.test(c2.pie);
ok(rojo, "sin el guard, la lectura vieja PISA el resultado de la prueba (la sonda ve la carrera)", c2.pie.trim());

console.log(`\n${fails.length ? "✗ " + fails.length + " fallos" : "✓ TODO VERDE"}`);
await b.close();
process.exit(fails.length ? 1 : 0);
