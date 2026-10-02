#!/usr/bin/env node
/**
 * verify_cerebro_un_solo_escritor.mjs — ELEGIR CEREBRO ES UN SOLO CAMINO.
 *
 * EL DEFECTO, MEDIDO EN LA .app INSTALADA (34a7ff04), no leído. Ledger
 * `cli_eventos.jsonl`, tres turnos con tres `turno_id` distintos:
 *
 *     …9a8a  chip decía Grok         → spawned grok_cli   rc=1
 *     …9666  chip decía Claude Code  → spawned grok_cli   rc=1
 *     …b74f  chip decía Codex        → spawned grok_cli   rc=0
 *
 * El `default` del dueño era `cli.grok_cli` y nunca se reescribió
 * (`actualizado_en` quedó en 09:14, tres cambios de chip después). Causa, con línea:
 * `sala-v2.js:1200` — el botón «Usar otro conectado» hacía `setModeloSeleccionado(ref)`
 * y NADA MÁS. Estado de React, cero persistencia. El chip pasaba a mentir sobre qué
 * cerebro iba a correr, que es el defecto que el comentario de `sala-v2.js:290` dice
 * haber cerrado — entrando por la otra puerta.
 *
 * ⚠️ LO QUE MIDE ES LA INVARIANTE, Y SE DICE POR QUÉ. `sala-v2.js` importa diez módulos
 * con `?v=sala-te` en la ruta: Node no los resuelve desde disco, así que correr el
 * componente pediría un navegador, y la política de la casa sobre eso ya está escrita y
 * medida (`qa/dom_minimo.mjs`: playwright no resuelve acá, y una vara que no corre no es
 * verde, es silencio). Entonces acá se mide una invariante ESTRUCTURAL —que no exista un
 * segundo escritor— y el HECHO lo da la pantalla contra la .app instalada, con el ledger
 * al lado. Esta vara NO autoriza a decir que se vio un turno.
 *
 * Es falsable, que es lo que la hace algo más que una lectura:
 *   node qa/verify_cerebro_un_solo_escritor.mjs --mutantes
 * aplica cinco mutaciones al código REAL y exige que cada una la ponga en rojo.
 *
 *   node qa/verify_cerebro_un_solo_escritor.mjs
 *     0 → un solo escritor · 1 → hay un segundo camino · 2 → no se pudo medir
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const RAIZ = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const F = path.join(RAIZ, "product", "app", "design", "sala-v2", "sala-v2.js");
const malas = [];
const ok = (c, n, d = "") => { console.log(`${c ? "  ✅" : "  ❌"} ${n}${!c && d ? " — " + d : ""}`); if (!c) malas.push(n); };
const noMedible = (m) => { console.log(`[no medible] ${m}`); process.exit(2); };

let src;
try { src = fs.readFileSync(F, "utf8"); } catch (e) { noMedible(`no se pudo leer sala-v2.js: ${e.message}`); }

/** El cuerpo de una función que arranca en `ancla`, por conteo de llaves. */
function cuerpo(s, ancla) {
  const i = s.indexOf(ancla);
  if (i < 0) return null;
  let j = s.indexOf("{", i), n = 0;
  if (j < 0) return null;
  for (let k = j; k < s.length; k++) {
    if (s[k] === "{") n++;
    else if (s[k] === "}") { n--; if (!n) return s.slice(i, k + 1); }
  }
  return null;
}

/* ══ A · EL ESCRITOR ES UNO ════════════════════════════════════════════════════════ */
console.log("\nA · ningún gesto mueve el chip por fuera del escritor único");
const ESCRITOR = cuerpo(src, "const elegirCerebro = React.useCallback");
if (!ESCRITOR) noMedible("no existe `elegirCerebro` — la obra no está en este árbol");
ok(/AlephBrain\.elegirCerebro\(/.test(ESCRITOR),
   "el escritor único persiste por `AlephBrain.elegirCerebro`",
   "sin esto no escribe la fuente que el backend lee");

// Todo `setModeloSeleccionado(` del archivo tiene que estar en UNO de dos lugares:
// el escritor único, o el reflejo de la FUENTE en `recargarChoices`.
const REFLEJO = cuerpo(src, "const recargarChoices = React.useCallback");
const total = (src.match(/setModeloSeleccionado\(/g) || []).length;
const enEscritor = (ESCRITOR.match(/setModeloSeleccionado\(/g) || []).length;
const enReflejo = ((REFLEJO || "").match(/setModeloSeleccionado\(/g) || []).length;
const declarado = (src.match(/const \[modeloSeleccionado, setModeloSeleccionado\]/g) || []).length;
const sueltos = total - enEscritor - enReflejo;
ok(sueltos === 0, "no hay un segundo escritor del chip",
   `${sueltos} llamada(s) a setModeloSeleccionado fuera de elegirCerebro/recargarChoices (total ${total}, decl ${declarado})`);

/* ══ B · LOS DOS GESTOS ENTRAN POR AHÍ ════════════════════════════════════════════ */
console.log("\nB · los DOS gestos que cambian el cerebro pasan por el mismo camino");
const ALT = cuerpo(src, "onUsarAlternativa:");
ok(!!ALT && /elegirCerebroRef\.current\?\.\(|elegirCerebro\(/.test(ALT),
   "«Usar otro conectado» llama al escritor único",
   "era `setModeloSeleccionado` a secas: el turno siguiente salía con el cerebro viejo");
const SEL = (src.match(/onSelect:\s*[^\n]*\n?[^\n]*/) || [""])[0];
ok(/elegirCerebro\(/.test(SEL), "el chip del composer llama al escritor único", SEL.trim().slice(0, 70));

/* ══ C · EL FALLO SE DICE, Y EL ERROR NO SE LIMPIA SOLO ═══════════════════════════ */
console.log("\nC · si el cambio NO entra, se dice — y el fallo queda a la vista");
ok(/setModeloSeleccionado\(previo/.test(ESCRITOR), "si falla, el chip vuelve a lo que de verdad está elegido");
ok(/cerebro_no_cambio/.test(ESCRITOR), "…y lo dice con copy (regla sellada: ninguna causa sin copy)");
ok(!!ALT && /if \(ok\) setFallo\(null\)/.test(ALT),
   "el error se limpia SÓLO si el cambio entró",
   "limpiarlo siempre borraría el fallo dejando el cerebro viejo: la pantalla mentiría dos veces");

/* ══ VEREDICTO ═══════════════════════════════════════════════════════════════════ */
console.log("\n" + "=".repeat(78));
if (malas.length) { console.log(`ROJO — ${malas.length}: ${malas.join(" · ")}`); process.exit(1); }
console.log("TODO VERDE — elegir cerebro es un solo camino, y persiste");
console.log("⚠️  el TURNO no lo prueba esta vara: eso es pantalla + ledger contra la .app");
console.log("=".repeat(78));

/* ══ MUTANTES ════════════════════════════════════════════════════════════════════ */
if (process.argv.includes("--mutantes")) {
  const MUT = [
    ["el botón del error vuelve a mover sólo estado de React",
     /Promise\.resolve\(elegirCerebroRef\.current\?\.\(ref\)\)\.then\(\(ok\) => \{\s*if \(ok\) setFallo\(null\);\s*\}\);/,
     "setModeloSeleccionado(ref); setFallo(null);"],
    ["el escritor único deja de persistir", /await window\.AlephBrain\.elegirCerebro\(selectionRef\);/, "/* no persiste */;"],
    ["el chip se salta el escritor", /onSelect: \(selectionRef\) => \{ elegirCerebro\(selectionRef\); \},/,
     "onSelect: (selectionRef) => { setModeloSeleccionado(selectionRef); },"],
    ["el fallo deja de revertir", /setModeloSeleccionado\(previo \|\| null\);/, "/* se queda en el nuevo */;"],
    ["el error se limpia siempre", /if \(ok\) setFallo\(null\);/, "setFallo(null);"],
  ];
  console.log("\n── MUTANTES: cada uno tiene que poner la vara en ROJO ──");
  const orig = src;
  let sobrevivientes = 0;
  for (const [nombre, re, reemplazo] of MUT) {
    if (!re.test(orig)) { console.log(`  ⚠️  ${nombre}: el patrón ya no existe — MUTANTE INVÁLIDO`); sobrevivientes++; continue; }
    fs.writeFileSync(F, orig.replace(re, reemplazo), "utf8");
    let rojo = false;
    try { execFileSync(process.execPath, [fileURLToPath(import.meta.url)], { stdio: "pipe" }); }
    catch (e) { rojo = e.status === 1; }
    fs.writeFileSync(F, orig, "utf8");
    console.log(`  ${rojo ? "✅" : "❌"} ${nombre}${rojo ? "" : " — SOBREVIVIÓ: la vara está ciega acá"}`);
    if (!rojo) sobrevivientes++;
  }
  if (sobrevivientes) { console.log(`\nROJO — ${sobrevivientes} mutante(s) sobrevivieron`); process.exit(1); }
  console.log("\nlos 5 mutantes murieron: la vara ve lo que dice ver");
}
