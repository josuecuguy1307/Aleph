/* sonda_cuarto_orden.mjs — SONDA ESTÁTICA del bundle [orden del Cuarto].
 *
 * Sin Playwright y sin navegador: el gate visual es el humano en la .app. Acá sólo se
 * comprueba, sobre el `cuarto.pixi.html` REALMENTE EMPAQUETADO (el que sale del binario
 * frozen, no el del árbol), que lo que se borró no viajó y que lo que se movió llegó.
 *
 *   A · la BARRA INFERIOR no está (ni el input de tarea suelto, ni #runbar)
 *   B · la FRANJA SUPERIOR no está (ni campo, ni forma, ni token, ni ✦ Armar)
 *   C · arriba-derecha: los 3 controles, y ▶ Run es el EJECUTOR
 *   D · ⌕ Inspeccionar existe DENTRO del ⋯ (y "Probar en la Sala" también bajó ahí)
 *   E · abajo-izquierda: el chip y el ⊙, los dos anclados a esa esquina
 *   F · la tarea sigue existiendo, mudada (#runask con #runprompt y #preflight)
 *
 *   node qa/sonda_cuarto_orden.mjs                    # contra el sidecar frozen construido
 *   ALEPH_SIDECAR_BIN=<ruta> node qa/sonda_cuarto_orden.mjs
 */
import { spawn } from "node:child_process";
// GUARD _MEI (integración tanda-P): TMPDIR privado por sidecar + barrido en TODA salida.
// El bootloader onefile deja ~170 MB en `_MEI*` si el proceso no cierra limpio; 91 huérfanos
// llenaron el disco el 26-jul. Ver qa/lib/frozen_guard.mjs y qa/verify_frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "./lib/frozen_guard.mjs";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
const PORT = Number(process.env.SONDA_PORT || 8275);
const BASE = `http://127.0.0.1:${PORT}`;
const DATADIR = mkdtempSync(join(tmpdir(), "orden-"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  — " + extra : ""}`); if (!c) fails.push(label); };

if (!existsSync(SIDECAR)) { console.log(`✗ no existe el sidecar frozen: ${SIDECAR}`); process.exit(1); }
console.log(`── sidecar FROZEN ${SIDECAR}\n`);

const proc = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
  env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATADIR },
  stdio: ["ignore", "pipe", "pipe"],
});
let vivo = false;
for (let i = 0; i < 120; i++) {
  try { const r = await fetch(BASE + "/health"); if (r.ok) { vivo = true; break; } } catch {}
  await sleep(500);
}
ok(vivo, "el sidecar frozen arranca");
if (!vivo) { proc.kill(); process.exit(1); }

try {
  const r = await fetch(BASE + "/cuarto/cuarto.pixi.html");
  const h = await r.text();
  ok(r.status === 200 && h.length > 1000, "cuarto.pixi.html se sirve del binario", `HTTP ${r.status} · ${h.length}B`);

  // helpers: posición de un id en el documento empaquetado
  const at = (id) => h.indexOf(`id="${id}"`);
  const hay = (id) => at(id) >= 0;
  // el bloque #topright, para preguntar "¿está DENTRO de la barra?" sin DOM
  const iTop = h.indexOf('id="topright"');
  const iMenu = h.indexOf('id="metaMenu"');
  const iMenuFin = h.indexOf("</div>\n    </div>", iMenu);
  const enBarraVisible = (id) => at(id) > iTop && at(id) < iMenu;      // antes de que abra el ⋯
  const enMenu = (id) => at(id) > iMenu && (iMenuFin < 0 || at(id) < iMenuFin);

  // ── A · la barra inferior no viajó ──────────────────────────────────────────────────
  ok(!hay("runbar"), "A · #runbar (la barra de abajo) NO está en el empaquetado");
  ok(!/¿Qué quieres que haga el agente ahora\?[\s\S]{0,400}id="run"[^G]/.test(h) || !hay("runbar"),
     "A · el input de tarea ya no cuelga de una barra propia");

  // ── B · la franja superior no viajó ─────────────────────────────────────────────────
  for (const id of ["inspectbar", "intent", "inspectforma", "inspecttoken", "forge"]) {
    ok(!hay(id), `B · #${id} NO está en el empaquetado`);
  }
  ok(!h.includes("Describe tu agente para armarlo"), "B · el placeholder de la franja no viajó");
  ok(!h.includes('placeholder="token / API key"'), "B · el campo de token/API key no viajó");
  // OJO: "✦ Armar" sigue apareciendo en COMENTARIOS que documentan adónde se mudó. Lo que no
  // puede quedar es un CONTROL vivo, así que se busca el <button>, no el texto suelto.
  ok(!/<button[^>]*>[^<]*✦\s*Armar/i.test(h), "B · no queda ningún botón ✦ Armar vivo");

  // ── C · los 3 controles de esquina; el de la barra es el HANDOFF a La Sala ──────────
  ok(enBarraVisible("homeBtn"), "C · [← Salir] visible en la barra");
  ok(enBarraVisible("salaBtn"), "C · [▶ Probar en la Sala] visible en la barra");
  ok(enBarraVisible("metaBtn"), "C · [⋯] visible en la barra");
  // nada más suelto ahí: el único otro id visible del bloque es el separador (sin id)
  // (se descuenta "topright", que es el CONTENEDOR, no un control)
  const visibles = [...h.slice(iTop, iMenu).matchAll(/id="([\w-]+)"/g)].map((m) => m[1])
    .filter((v) => v !== "topright");
  ok(visibles.length === 3 && visibles.every((v) => ["homeBtn", "salaBtn", "metaBtn"].includes(v)),
     "C · arriba-derecha hay EXACTAMENTE esos 3 controles", `[${visibles.join(", ")}]`);

  // ── C2 · el Cuarto NO corre: ni botón de Ejecutar ni input de tarea ─────────────────
  for (const id of ["run", "runask", "runprompt", "runGo"]) {
    ok(!hay(id), `C2 · #${id} NO está (ejecutar es de La Sala)`);
  }
  ok(!h.includes("¿Qué quieres que haga el agente ahora?"), "C2 · el input de tarea no viajó");

  // ── D · el ⋯, sin el duplicado de la Sala ───────────────────────────────────────────
  ok(enMenu("inspectBtn"), "D · ⌕ Inspeccionar vive DENTRO del ⋯");
  ok(!enMenu("salaBtn"), "D · «Probar en la Sala» NO está duplicado en el ⋯ (vive en la barra)");
  ok(/id="inspectBtn"[\s\S]{0,80}⌕ Inspeccionar/.test(h), "D · …y dice ⌕ Inspeccionar");

  // ── G · el preflight NO se borró: es el badge, con línea + botón ────────────────────
  ok(hay("listo") && hay("listoTxt") && hay("listoBtn"), "G · el badge de listo-para-la-Sala existe");
  ok(hay("preflight") && at("preflight") > at("listo"), "G · el detalle del preflight vive DENTRO del badge");
  for (const frase of ["Equipá una pieza para empezar", "Probá tus piezas antes de la Sala", "Listo para la Sala"]) {
    ok(h.includes(frase), `G · copy accionable presente: "${frase}"`);
  }
  ok(/pintarListo\("vacio"[\s\S]{0,240}Equipar/.test(h), "G · vacío → botón [＋ Equipar]");
  ok(/pintarListo\("sinprobar"[\s\S]{0,240}Probar todo/.test(h), "G · sin probar → botón [Probar todo]");
  ok(/pintarListo\("listo"[\s\S]{0,240}Probar en la Sala/.test(h), "G · listo → botón [▶ Probar en la Sala]");
  ok(/pintarListo\("roto"[\s\S]{0,320}faltaDe\(/.test(h), "G · roto → nombra la pieza y su falta, con el botón del arreglo");

  // ── E · la esquina de abajo-izquierda ───────────────────────────────────────────────
  ok(hay("legend") && hay("cam"), "E · el chip LAS PIEZAS y el ⊙ están los dos");
  ok(/#cam \{[^}]*left:18px[^}]*bottom:16px/.test(h), "E · el ⊙ está anclado abajo-izquierda");
  ok(/#legend \{[^}]*left:18px[^}]*bottom:76px/.test(h), "E · el chip queda encima del ⊙, misma esquina");
  ok(/#topright \{ right:18px; top:18px/.test(h), "E · la barra recuperó el borde de arriba");

  // (la vieja sección F afirmaba que la pedida de tarea existía. Se fue con ella: ejecutar es de
  //  La Sala. Lo que quedó de ese contrato lo cubren C2 —no hay input ni botón de Ejecutar— y G
  //  —el preflight NO se borró, es el badge—.)
} catch (e) {
  ok(false, "la sonda corrió sin excepción", String(e && e.message || e));
} finally {
  proc.kill();
}

console.log(`\n${fails.length === 0 ? "VERDE" : "ROJO"} · ${fails.length} fallo(s)`);
if (fails.length) { fails.forEach((f) => console.log("  ✗ " + f)); process.exit(1); }
