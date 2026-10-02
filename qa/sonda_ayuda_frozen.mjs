/* sonda_ayuda_frozen.mjs — LA DEUDA #1 DE T6: el camino FROZEN del [?].
 *
 * T6 sólo pudo verificar el CONTRATO estático (docs/guia está en _DATA_DIRS del spec y el
 * mount de main.py sale de resource_root(), que es frozen-aware). Lo que NO pudo probar,
 * porque no construyó frozen, es el tramo `_MEIPASS`: que la .app SIRVA esos MD de verdad.
 * Si ese tramo falla, los 14 [?] del Cuarto abren el fallo visible y la explicación que §10
 * mudó a docs/guia deja de existir para el usuario que instala.
 *
 * Se mide contra el SIDECAR FROZEN de este árbol, en puerto propio, con datadir aislado:
 *   §1  el mount arranca desde _MEIPASS (no desde el repo) y lo DICE en el log.
 *   §2  GET /docs/guia/*.md devuelve el MD real, ES y EN, con sus anclas {#slug}.
 *   §3  el Cuarto SERVIDO POR EL FROZEN abre un [?] y pinta la sección — no el fallo visible.
 *
 * Run:  node qa/sonda_ayuda_frozen.mjs        (puerto propio :8293 · JAMÁS :25374)
 */
import { webkit } from "playwright";
import net from "node:net";
import path from "node:path";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { spawnFrozen, matarFrozen } from "./lib/frozen_guard.mjs";

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const PORT = Number(process.env.AYUDA_PORT || 8293);
if (PORT === 25374) { console.error("✗ 25374 es la .app de persona usuaria"); process.exit(2); }
const BASE = `http://127.0.0.1:${PORT}`;
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  path.join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");

let PASS = 0; const FALLOS = [];
const ok = (c, name, det = "") => {
  if (c) { PASS++; console.log(`  ✓ ${name}${det ? "  — " + det : ""}`); }
  else { FALLOS.push(name); console.log(`  ✗ ${name}${det ? "  — " + det : ""}`); }
  return !!c;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* el puerto es mío o no hay veredicto */
await new Promise((res, rej) => {
  const p = net.createConnection({ port: PORT, host: "127.0.0.1" });
  p.on("connect", () => { p.destroy(); rej(new Error(`:${PORT} ocupado — esta sonda mide su árbol o no mide nada`)); });
  p.on("error", () => res());
});

const DATA = mkdtempSync(path.join(tmpdir(), "ayuda-frozen-"));
let log = "";
const proc = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
  env: { ...process.env, ALEPH_DATA_DIR: DATA, ALEPH_ROLE: "client", ALEPH_BUILD: "public" },
});
proc.stdout?.on("data", (b) => { log += b.toString(); });
proc.stderr?.on("data", (b) => { log += b.toString(); });

let vivo = false;
for (let i = 0; i < 120 && !vivo; i++) {
  await sleep(500);
  try { const r = await fetch(`${BASE}/health`); vivo = r.ok; } catch {}
}

try {
  console.log("\n── §1 · el mount sale de _MEIPASS, no del repo ─────────────────────");
  ok(vivo, "el sidecar frozen levantó", `${BASE}`);
  const linea = (log.match(/\[serving\] docs\/guia[^\n]*/) || [""])[0];
  ok(/montado desde/.test(linea), "el arranque DICE de dónde monta docs/guia", linea.trim());
  ok(/_MEI/.test(linea), "…y ese origen es el _MEIPASS del onefile, no el árbol de git ★",
     linea.replace(/.*montado desde /, ""));
  ok(!/AUSENTE/.test(log), "no salió el aviso de docs/guia AUSENTE");

  console.log("\n── §2 · los MD se sirven de verdad, ES y EN, con sus anclas ────────");
  for (const [f, head] of [["cuarto.es.md", "# "], ["cuarto.en.md", "# "],
                           ["cerebros.es.md", "# "], ["memoria.es.md", "# "]]) {
    const r = await fetch(`${BASE}/docs/guia/${f}`);
    const t = r.ok ? await r.text() : "";
    ok(r.ok && t.startsWith(head) && t.length > 400, `GET /docs/guia/${f}`,
       `HTTP ${r.status} · ${t.length} bytes`);
  }
  const es = await (await fetch(`${BASE}/docs/guia/cuarto.es.md`)).text();
  const en = await (await fetch(`${BASE}/docs/guia/cuarto.en.md`)).text();
  const slugs = (s) => (s.match(/\{#([a-z0-9-]+)\}/g) || []).sort().join(",");
  ok(slugs(es).length > 0, "el MD frozen conserva las anclas {#slug} (contrato del [?])", slugs(es));
  ok(slugs(es) === slugs(en), "…y ES/EN tienen los MISMOS slugs ★", `${slugs(es)} == ${slugs(en)}`);

  console.log("\n── §3 · el [?] del Cuarto SERVIDO POR EL FROZEN abre su sección ────");
  const b = await webkit.launch();
  const pg = await b.newPage({ viewport: { width: 1440, height: 900 } });
  await pg.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(() => !!window.__ayuda, null, { timeout: 30000 }).catch(() => {});
  // Qué panel hospeda cada [?] ya lo cubren los 14/14 de T6 §B contra el árbol. Lo que ESTA
  // sonda mide, y sólo se puede medir acá, es el TRANSPORTE: que el fetch del MD resuelva
  // contra el binario. Por eso se abre por la API del componente, no por un click.
  const montado = await pg.evaluate(() => !!window.__ayuda && !!document.getElementById("ayudapop"));
  ok(montado, "el Cuarto que sirve el frozen monta el componente del [?]");
  const pop = await pg.evaluate(async () => {
    window.__ayuda.cerrar();
    await window.__ayuda.abrir("cuarto", "nucleo", null);
    const el = document.getElementById("ayudapop");
    if (!el) return null;
    return { visible: window.__ayuda.abierto(),
             titulo: (el.querySelector(".ayTitle") || {}).textContent || "",
             cuerpo: ((el.querySelector(".ayBody") || {}).textContent || "").slice(0, 120),
             fallo: !!el.querySelector(".ayFail") };
  });
  ok(!!pop && pop.visible, "el popover abre", pop ? `titulo="${pop.titulo}"` : "no existe");
  ok(!!pop && !pop.fallo, "NO cayó al fallo visible (o sea: leyó el MD desde el binario) ★",
     pop && pop.fallo ? "salió .ayFail" : "sin .ayFail");
  ok(!!pop && pop.cuerpo.trim().length > 60, "…con el texto real de la sección", pop ? pop.cuerpo.trim().slice(0, 80) : "");
  await b.close();
} finally {
  matarFrozen(proc);
}

console.log("\n" + "═".repeat(70));
console.log(`SONDA [?] FROZEN · ${PASS} verdes · ${FALLOS.length} rojos`);
if (FALLOS.length) { FALLOS.forEach((f) => console.log("   ✗ " + f)); process.exit(1); }
