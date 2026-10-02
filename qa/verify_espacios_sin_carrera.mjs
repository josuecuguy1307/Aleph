#!/usr/bin/env node
/**
 * verify_espacios_sin_carrera.mjs — LA FILA DE CHIPS SE DIBUJA AUNQUE EL MÓDULO LLEGUE TARDE.
 * [rediseño · fase 2 · 2.5]
 *
 * QUÉ DEFECTO CIERRA, Y QUIÉN LO ENCONTRÓ
 * ───────────────────────────────────────
 * `product/app/design/espacios.js` es `type="module"`: se ejecuta DESPUÉS de parsear el
 * documento. `Historial` y `Biblioteca` leían `window.AlephEspacios` UNA sola vez —
 * `if (!E) return;` en su `loadEspacios`, y un stub `{espacios:()=>[]}` en el render — así
 * que si el módulo llegaba después del montaje la fila de chips de espacio **no se dibujaba
 * nunca**, sin reintento y sin error. La misma pantalla tenía dos caras según quién ganara.
 *
 * Ninguna de las 356 varas del árbol lo veía, porque ninguna mira la pantalla. Lo destapó
 * `qa/vara_visual.mjs` en su primera corrida: 2,4–2,9 % de diferencia entre dos capturas
 * seguidas, sin una línea de rediseño de por medio.
 *
 * QUÉ MIDE ESTA VARA, Y POR QUÉ EN DOS MITADES
 * ────────────────────────────────────────────
 *   1. **El módulo AVISA** — se ejecuta el bloque real de `espacios.js` en un doble de
 *      `window` y se exige que publique `AlephEspacios`, marque `listo` y dispare
 *      `aleph:espacios`. Esto se corre de verdad, no se lee.
 *   2. **Las pantallas ESPERAN** — censo sobre `Historial.dc.html` y `Biblioteca.dc.html`:
 *      que exista `esperarEspacios`, que el `componentDidMount` lo llame, que registre el
 *      oyente del evento y que repinte. Es censo estático a propósito: el cuerpo de esas
 *      pantallas corre adentro del runtime DC, y levantarlo entero para probar un `if` sería
 *      pagar un navegador por una rama. **La prueba de que de verdad no hay carrera es
 *      empírica y vive al lado:** `qa/vara_visual.mjs` las mide en cada corrida y tiene un
 *      chequeo de estabilidad que las nombraría solas si volvieran a partirse.
 *
 * PROBADA CAYENDO
 * ───────────────
 *     node qa/verify_espacios_sin_carrera.mjs --mutante
 * le saca el `dispatchEvent` al módulo y el `addEventListener` a las pantallas, y exige que
 * las dos mitades caigan.
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const D = path.join(RAIZ, "product/app/design");
const MUT = process.argv.includes("--mutante");
const fallos = [];
const ok = (c, m) => { console.log(`  ${c ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m"} ${m}`); if (!c) fallos.push(m); };

/* ── 1 · EL MÓDULO AVISA (se corre de verdad) ─────────────────────────────────────────── */
console.log("── el módulo avisa cuando llega ──");
let mod = fs.readFileSync(path.join(D, "espacios.js"), "utf8");
if (MUT) mod = mod.replace('window.dispatchEvent(new Event("aleph:espacios"));', "/* MUTADO */");

// Sólo el bloque `if (typeof window !== "undefined") { … }` del final: lo de arriba tiene
// `import`s y necesitaría un cargador de módulos entero para probar un `dispatchEvent`.
const i = mod.lastIndexOf('if (typeof window !== "undefined") {');
const bloque = mod.slice(i);
const oidos = [];
const win = {
  GENERAL: "general", espacios: () => [], etiqueta: (x) => x,
  hilosDeEspacio: () => [], obraDeEspacio: () => [], memoriaDeLosSeis: () => ({}), pasa: () => true,
  Event: class { constructor(t) { this.type = t; } },
  dispatchEvent(e) { oidos.push(e.type); return true; },
  addEventListener() {}, console,
};
win.window = win; win.globalThis = win;
vm.createContext(win);
vm.runInContext(bloque, win, { timeout: 5000 });
ok(!!win.AlephEspacios, "publica window.AlephEspacios");
ok(win.AlephEspacios && win.AlephEspacios.listo === true, "marca `listo` (para quien llegue después)");
ok(oidos.includes("aleph:espacios"), `dispara el evento aleph:espacios (oídos: ${JSON.stringify(oidos)})`);

/* ── 2 · LAS PANTALLAS ESPERAN ────────────────────────────────────────────────────────── */
console.log("\n── las dos pantallas esperan en vez de muestrear ──");
for (const [f, carga] of [["Historial.dc.html", "loadEspacios"], ["Biblioteca.dc.html", "loadObraDeEspacios"]]) {
  let s = fs.readFileSync(path.join(D, f), "utf8");
  if (MUT) s = s.replace(/window\.addEventListener\('aleph:espacios'/, "/*MUTADO*/(function(){}('aleph:espacios'");
  const n = f.replace(".dc.html", "");
  ok(/esperarEspacios\(\)\{/.test(s), `${n}: tiene esperarEspacios()`);
  ok(/componentDidMount\(\)\{[^}]*this\.esperarEspacios\(\)/.test(s), `${n}: el componentDidMount lo llama`);
  ok(/window\.addEventListener\('aleph:espacios'/.test(s), `${n}: registra el oyente del evento`);
  ok(/\{\s*once\s*:\s*true\s*\}/.test(s), `${n}: el oyente es de una sola vez (no se acumula por re-render)`);
  ok(new RegExp(`this\\.${carga}\\(\\)`).test(s), `${n}: reintenta la carga (${carga})`);
  ok(/this\.setState\(\{\s*espacio:\s*this\.state\.espacio\s*\}\)/.test(s), `${n}: repinta después de reintentar`);
}

console.log("");
if (MUT) {
  if (!fallos.length) { console.log("\x1b[31m✗ LA VARA ESTÁ ROTA\x1b[0m: con las dos mitades mutadas no cayó nada."); process.exit(1); }
  console.log(`\x1b[32m✓ la vara puede dar rojo\x1b[0m: ${fallos.length} afirmaciones cayeron.`); process.exit(0);
}
if (fallos.length) { console.log(`\x1b[31m✗ ${fallos.length} rojas\x1b[0m`); process.exit(1); }
console.log("\x1b[32m✓ el módulo avisa y las dos pantallas esperan — la carrera está cerrada\x1b[0m");
process.exit(0);
