/* ============================================================================
 * verify_unmount_sin_fugas.mjs — LA VARA DE LA OBRA 2.4.
 * [Gate 4 · Fase 2 · obra 2.4 — plan OSS 2.5: «agregar unmount (hoy no existe —
 *  con React pesado es fuga)»]
 *
 * Mide LOS DOS CAMINOS en la misma corrida, en pestañas separadas:
 *   · «viejo»    — lo que el módulo hacía antes: `host.innerHTML=""` + appendChild.
 *   · «unmount»  — el ciclo simétrico de 2.4: montar desmonta lo anterior, y el
 *                  desmontaje apaga timers e iframes ANTES de soltar el nodo.
 *
 * DOS EXPERIMENTOS, porque miden dos cosas distintas:
 *
 * E1 · LOS RENDERERS DE VERDAD (convergence · cad · volume3d · web · fieldplot ·
 *      informe). Se mide EN EL INSTANTE en que termina el ciclo, no después: el
 *      autoplay de `convergence` ya tenía un auto-freno (`tick` se apaga si el
 *      nodo no está en `document.body`), así que a los ~1,4 s los timers viejos
 *      se apagan solos. La primera pasada de esta vara midió a los 1500 ms, vio
 *      cero y me corrigió: lo que 2.4 cambia acá NO es «se apaga vs no se apaga»,
 *      es CUÁNDO. Sin desmontaje quedan N timers vivos redibujando heatmaps en
 *      nodos que ya nadie mira hasta que el auto-freno los pilla; con desmontaje
 *      se apagan en el acto. La vara mide las dos fotos y las reporta.
 *
 * E2 · EL CASO REACT (lo que el plan nombra). Una pantalla pesada no fuga por el
 *      nodo: fuga por el REGISTRO GLOBAL que la apunta. El arnés monta N veces un
 *      nodo con ~1,5 MB de estado metido en un `Map` y declara su liberación con
 *      `AR.onTeardown` — la pieza que 2.4 agrega y que antes no existía. Sin
 *      desmontaje nadie la llama: el registro crece y el heap con él. Acá el
 *      número es grande y determinístico, no ruido. (El estado tiene que ser
 *      objetos/strings: la primera pasada usó `Uint8Array` y el heap no se movió,
 *      porque su backing store es memoria EXTERNA y `getHeapUsage` no la cuenta.)
 *
 * E3 · LA PUERTA REAL — el mismo ciclo pero por `SalaRender.renderArtifact`, que
 *      es lo que el canvas de la Sala llama de verdad, para que el cableado del
 *      segundo registro quede medido y no supuesto.
 *
 *     node qa/verify_unmount_sin_fugas.mjs [--ciclos 12] [--pesados 24]
 * ========================================================================== */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const DIR = dirname(fileURLToPath(import.meta.url));      // …/qa
const ROOT = resolve(DIR, "..");                          // raíz del repo
const arg = (n, d) => {
  const i = process.argv.indexOf(n);
  return i > 0 && process.argv[i + 1] ? Number(process.argv[i + 1]) : d;
};
const CICLOS = arg("--ciclos", 12);
const PESADOS = arg("--pesados", 24);
const SALA_CICLOS = arg("--sala", 8);

//: Tipos PESADOS elegidos por el recurso que prenden (no por variedad):
//: convergence = timer + heatmaps · cad/volume3d = iframe con three.js (WebGL) ·
//: web = iframe con documento propio · fieldplot = canvas · informe = KaTeX/marked.
const TIPOS = ["convergence", "cad", "volume3d", "web", "fieldplot", "informe"];

const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
               ".css": "text/css", ".json": "application/json", ".png": "image/png",
               ".woff2": "font/woff2", ".woff": "font/woff" };

const server = createServer(async (req, res) => {
  try {
    const p = decodeURIComponent(req.url.split("?")[0]);
    const file = resolve(join(ROOT, p));
    if (!file.startsWith(ROOT)) throw new Error("fuera de raíz");
    const buf = await readFile(file);
    res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
    res.end(buf);
  } catch { res.writeHead(404); res.end("nope"); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const PORT = server.address().port;
const URL_ARNES = `http://127.0.0.1:${PORT}/qa/harness_unmount.html`;

const browser = await chromium.launch();
const fails = [];
const ok = (cond, nombre, detalle) => {
  if (!cond) fails.push(nombre + (detalle ? ` → ${detalle}` : ""));
  console.log(`  ${cond ? "✓" : "✗"} ${nombre}${detalle ? "  ·  " + detalle : ""}`);
  return cond;
};

async function abrir() {
  const page = await browser.newPage({ viewport: { width: 1100, height: 700 } });
  const gl = { avisos: 0 };
  page.on("console", (m) => { if (/too many active webgl/i.test(m.text())) gl.avisos++; });
  await page.goto(URL_ARNES, { waitUntil: "load" });
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 30000 });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("HeapProfiler.enable");
  const heap = async () => {
    await cdp.send("HeapProfiler.collectGarbage");
    const { usedSize } = await cdp.send("Runtime.getHeapUsage");
    return usedSize;
  };
  return { page, cdp, heap, gl };
}

/** E1 — los renderers de verdad. */
async function e1(modo) {
  const { page, cdp, heap, gl } = await abrir();
  await page.evaluate(([t, m]) => window.__cycle(t, 1, m), [TIPOS, modo]);   // calentamiento
  await page.waitForTimeout(1200);
  const antes = await heap();
  const montajes = await page.evaluate(([t, c, m]) => window.__cycle(t, c, m), [TIPOS, CICLOS, modo]);
  const enElActo = await page.evaluate(() => window.__medir());     // ← la foto que importa
  await page.waitForTimeout(1600);                                  // el auto-freno de `tick`
  const enReposo = await page.evaluate(() => window.__medir());
  const despues = await heap();
  await cdp.detach(); await page.close();
  return { modo, montajes, enElActo, enReposo, glAvisos: gl.avisos,
           heapKB: { antes: Math.round(antes / 1024), despues: Math.round(despues / 1024),
                     delta: Math.round((despues - antes) / 1024) } };
}

/** E2 — la pantalla pesada con estado en un registro global (el caso React). */
async function e2(modo) {
  const { page, cdp, heap } = await abrir();
  await page.evaluate((m) => window.__cicloPesado(2, m), modo);     // calentamiento
  await page.waitForTimeout(400);
  const antes = await heap();
  const retenidos = await page.evaluate(([c, m]) => window.__cicloPesado(c, m), [PESADOS, modo]);
  await page.waitForTimeout(400);
  const despues = await heap();
  const med = await page.evaluate(() => window.__medir());
  await cdp.detach(); await page.close();
  return { modo, retenidos, registroPesado: med.registroPesado,
           heapKB: { antes: Math.round(antes / 1024), despues: Math.round(despues / 1024),
                     delta: Math.round((despues - antes) / 1024) } };
}

/** E3 — el mismo ciclo por la puerta que usa el canvas de la Sala. */
async function e3(modo) {
  const { page, cdp } = await abrir();
  await page.evaluate((m) => window.__cicloSala(1, m), modo);        // calentamiento
  const montajes = await page.evaluate(([c, m]) => window.__cicloSala(c, m), [SALA_CICLOS, modo]);
  const enElActo = await page.evaluate(() => window.__medir());
  await cdp.detach(); await page.close();
  return { modo, montajes, enElActo };
}

console.log("=".repeat(80));
console.log(`VARA · MONTAR/DESMONTAR SIN FUGAS (Gate 4 · 2.4)`);
console.log(`E1: ${CICLOS} ciclos × ${TIPOS.length} tipos   ·   E2: ${PESADOS} pantallas de ~1,5 MB`);
console.log("=".repeat(80));

const v1 = await e1("viejo");
const n1 = await e1("unmount");
const v2 = await e2("viejo");
const n2 = await e2("unmount");

console.log("\n── E1 · los renderers de verdad ─────────────────────────────────────");
for (const r of [v1, n1]) {
  console.log(`  [${r.modo.padEnd(7)}] montajes=${r.montajes}` +
    `  timers EN EL ACTO=${r.enElActo.timersVivos} → en reposo=${r.enReposo.timersVivos}` +
    `  nodos=${r.enReposo.nodosRender} iframes=${r.enReposo.iframes}` +
    `  heap Δ${r.heapKB.delta}KB  avisosWebGL=${r.glAvisos}`);
}
console.log("\n── E2 · la pantalla pesada (registro global + ~1,5 MB por montaje) ───");
for (const r of [v2, n2]) {
  console.log(`  [${r.modo.padEnd(7)}] retenidos en el registro=${r.registroPesado}` +
    `  heap ${r.heapKB.antes}KB → ${r.heapKB.despues}KB (Δ ${r.heapKB.delta}KB)`);
}

const v3 = await e3("viejo");
const n3 = await e3("unmount");
console.log("\n── E3 · por la puerta real (SalaRender.renderArtifact) ───────────────");
for (const r of [v3, n3]) {
  console.log(`  [${r.modo.padEnd(7)}] montajes=${r.montajes}  timers EN EL ACTO=${r.enElActo.timersVivos}` +
    `  nodos=${r.enElActo.nodosRender}`);
}

console.log("\n── veredicto ────────────────────────────────────────────────────────");
ok(v1.enElActo.timersVivos > 0,
   "E1 · el camino VIEJO deja timers vivos EN EL ACTO — la fuga existe y esta vara la ve",
   `timers=${v1.enElActo.timersVivos}`);
ok(n1.enElActo.timersVivos === 0,
   "E1 · con unmount no queda un solo timer vivo en el instante del desmontaje",
   `timers=${n1.enElActo.timersVivos}`);
ok(n1.enReposo.nodosRender === 0 && n1.enReposo.iframes === 0,
   "E1 · ni un nodo de render ni un iframe quedan en el documento",
   `nodos=${n1.enReposo.nodosRender} iframes=${n1.enReposo.iframes}`);
ok(n1.montajes === CICLOS * TIPOS.length,
   `E1 · se montaron los ${CICLOS * TIPOS.length} esperados (no se midió un ciclo vacío)`,
   String(n1.montajes));

ok(v2.registroPesado >= PESADOS,
   "E2 · sin desmontaje el registro global retiene TODAS las pantallas montadas",
   `retenidas=${v2.registroPesado}`);
ok(n2.registroPesado === 0,
   "E2 · con unmount el registro queda en cero: el teardown declarado corrió",
   `retenidas=${n2.registroPesado}`);
ok(n2.heapKB.delta < v2.heapKB.delta / 2,
   "E2 · el heap con unmount crece MENOS DE LA MITAD que sin él",
   `unmount Δ${n2.heapKB.delta}KB vs viejo Δ${v2.heapKB.delta}KB`);
ok(v3.enElActo.timersVivos > 0,
   "E3 · por la puerta de la Sala, el camino viejo también deja timers vivos",
   `timers=${v3.enElActo.timersVivos}`);
ok(n3.enElActo.timersVivos === 0 && n3.enElActo.nodosRender === 0,
   "E3 · `SalaRender.renderArtifact` + `unmount` no dejan timer ni nodo vivo",
   `timers=${n3.enElActo.timersVivos} nodos=${n3.enElActo.nodosRender}`);
ok(n2.heapKB.delta < 4096,
   `E2 · …y queda bajo 4 MB tras ${PESADOS} montajes de ~1,5 MB`,
   `Δ${n2.heapKB.delta}KB`);

const out = { pass: fails.length === 0, ciclos: CICLOS, pesados: PESADOS, tipos: TIPOS,
              e1: { viejo: v1, unmount: n1 }, e2: { viejo: v2, unmount: n2 },
              e3: { viejo: v3, unmount: n3 }, fails };
console.log("\n" + JSON.stringify(out));

await browser.close();
server.close();
process.exit(fails.length ? 1 : 0);
