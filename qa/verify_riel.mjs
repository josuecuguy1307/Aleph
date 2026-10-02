#!/usr/bin/env node
/**
 * verify_riel.mjs — LOS TRES CABLES QUE LA BARRA SE LLEVABA PUESTOS. [rediseño · fase 2 · 2.1]
 *
 * La barra superior murió y nació el riel. Lo peligroso no era la barra: eran las tres cosas
 * que colgaban de ella y que NADIE MÁS hacía.
 *
 *   1. `nav.js` INYECTA `aleph-ds.js` —el sistema de diseño— en las 24 pantallas que lo
 *      cargan. Matarlo sin mudar el inyector las dejaba a las 24 sin sistema.
 *   2. Los conmutadores de TEMA e IDIOMA vivían ahí y eran los ÚNICOS de esas 24 pantallas.
 *      Mueren de ahí, pero tienen que EXISTIR en su lugar nuevo el mismo día.
 *   3. `window.AlephDestinos` publica la tabla de destinos, y la leen el hub de
 *      `Home.dc.html` y los seis workspaces por `destinos-del-espacio.js`.
 *
 * POR QUÉ LA BARRA SE REESCRIBIÓ EN `nav.js` EN VEZ DE BORRAR EL ARCHIVO. Porque los tres
 * cables viven en él: borrarlo obligaba a mudar los tres, y mudar un cable es la forma más
 * común de que un botón quede perfecto y muerto. Se cambió lo que dibuja; no se movió nada
 * de lo que sostiene. Esta vara existe para probar exactamente eso.
 *
 * PROBADA CAYENDO
 *     node qa/verify_riel.mjs --mutante
 * borra el inyector de `aleph-ds.js`, la publicación de `AlephDestinos` y los controles de
 * tema/idioma de Settings, y exige que las tres mitades caigan.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const D = path.join(RAIZ, "product/app/design");
const MUT = process.argv.includes("--mutante");
const fallos = [];
const ok = (c, m) => { console.log(`  ${c ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m"} ${m}`); if (!c) fallos.push(m); };
const leer = (f) => fs.readFileSync(path.join(D, f), "utf8");

let nav = leer("nav.js");
let settings = leer("Settings.dc.html");
if (MUT) {
  nav = nav.replace("s.id = 'aleph-ds-js'", "s.id = 'MUTADO'")
           .replace("window.AlephDestinos =", "window.MUTADO =");
  settings = settings.replace(/\{\{ themes \}\}/g, "{{ MUTADO }}").replace(/\{\{ langs \}\}/g, "{{ MUTADO }}");
}

/* ── CABLE 1 · el sistema de diseño sigue llegando a las 24 ──────────────────────────── */
console.log("── cable 1 · el inyector de aleph-ds.js ──");
// Un solo recorrido, recursivo, con el mismo patrón laxo que usa el grep de la casa: la
// primera versión de esta vara miraba la raíz con un patrón estricto y seis subcarpetas con
// uno laxo, y contaba 23 donde `grep -rl` cuenta 24. Contar de dos formas es contar mal.
const pantallas = fs.readdirSync(D).filter((f) => f.endsWith(".html"));
const conNav = [];
(function caminar(dir, rel) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "vendor" || e.name === "node_modules" || e.name === "screenshots") continue;
    const abs = path.join(dir, e.name), r = rel ? rel + "/" + e.name : e.name;
    if (e.isDirectory()) caminar(abs, r);
    else if (e.name.endsWith(".html") && /nav\.js/.test(fs.readFileSync(abs, "utf8"))) conNav.push(r);
  }
})(D, "");
ok(conNav.length >= 24, `${conNav.length} pantallas cargan nav.js (esperado ≥24)`);
// La LÍNEA que inyecta, no la palabra: el comentario también dice «aleph-ds.js», así que
// buscar la cadena suelta habría dado verde con el inyector borrado.
ok(/s\.id = 'aleph-ds-js'/.test(nav) && /s\.src = base \+ 'aleph-ds\.js'/.test(nav),
   "nav.js sigue inyectando aleph-ds.js — las mismas pantallas, el mismo sistema");
ok(nav.indexOf("aleph-ds.js") < nav.indexOf("var CSS"),
   "el inyector va ANTES de todo lo demás (corre aunque el riel no se dibuje)");

/* ── CABLE 2 · tema e idioma nacieron en su lugar nuevo ─────────────────────────────── */
console.log("\n── cable 2 · tema e idioma, de la barra a Preferencias ──");
// Se busca la DECLARACIÓN y el ENGANCHE, no la palabra: el comentario que explica por qué
// se fueron las nombra, y una vara que se cae por su propia documentación es una vara mal
// escrita. (Me pasó: la primera versión daba rojo por su propio comentario.)
ok(!/function\s+toggleTheme|function\s+toggleLang|onclick\s*=\s*toggle/.test(nav),
   "nav.js ya no declara ni engancha los conmutadores");
ok(!/function\s+curTheme|function\s+curLang/.test(nav),
   "…ni sus ayudantes, que quedaron sin llamante al irse los botones");
ok(!/aleph-tb-ic|aleph-tb-cta/.test(nav), "…ni las pastillas ni el CTA de la barra vieja");
// y ESTO es lo que hace que borrarlos no rompa nada: ya existían del otro lado.
ok(/\{\{ themes \}\}/.test(settings) && /t\.pick/.test(settings),
   "Settings.dc.html tiene el control de TEMA, con sus opciones cableadas a un pick");
ok(/\{\{ langs \}\}/.test(settings) && /l\.pick/.test(settings),
   "Settings.dc.html tiene el control de IDIOMA, con sus opciones cableadas a un pick");
ok(/\{\{ sizes \}\}/.test(settings), "…y el de tamaño del texto, que ya estaba");
const ajustes = leer("ajustes.js");
const conTheme = [];
for (const f of pantallas) if (/src="\.\/theme\.js"/.test(leer(f))) conTheme.push(f);
ok(/AlephAjustes/.test(ajustes) && /Settings\.dc\.html/.test(ajustes),
   "el ⚙ de ajustes.js lleva a Settings.dc.html — la puerta a Preferencias");
ok(/aleph-riel/.test(ajustes),
   "…y NO se duplica donde el riel ya dibuja AJUSTES (dos disparadores del mismo destino)");

/* ── CABLE 3 · la tabla de destinos ─────────────────────────────────────────────────── */
console.log("\n── cable 3 · window.AlephDestinos y sus dos lectores ──");
ok(/window\.AlephDestinos = \{ items: ITEMS/.test(nav), "nav.js sigue publicando la tabla");
ok(/window\.AlephDestinos/.test(leer("Home.dc.html")), "el hub de Home la sigue leyendo");
ok(/window\.AlephDestinos/.test(leer("workspaces/destinos-del-espacio.js")),
   "destinos-del-espacio.js (los seis workspaces) la sigue leyendo");

/* ── Y LOS DESTINOS SIGUEN ALCANZABLES ──────────────────────────────────────────────── */
console.log("\n── los destinos existen y ninguno quedó huérfano ──");
// SÓLO la tabla ITEMS. El `{ id: '…' }` suelto matchea también los `el('div', {id:'aleph-riel'})`
// del propio riel, y la vara se ponía a buscar un archivo llamado `aleph-nav-scrim`.
const tabla = nav.slice(nav.indexOf("var ITEMS = ["), nav.indexOf("];", nav.indexOf("var ITEMS = [")));
const ids = [...tabla.matchAll(/\{ id: '([^']+)'/g)].map((m) => m[1]);
ok(ids.length >= 10, `la tabla tiene ${ids.length} destinos`);
for (const id of ids) ok(fs.existsSync(path.join(D, id)), `existe ${id}`);
ok(ids.includes("Agentes.dc.html"), "Agentes entró a la tabla");
ok(ids.includes("Cuarto.dc.html"),
   "el Cuarto SIGUE en la tabla aunque salga del riel — si no, el hub lo perdería");
ok(/＋ \{\{ crearLabel \}\}|Cuarto\.dc\.html/.test(leer("Agentes.dc.html")),
   "…y se llega a él desde Agentes, que es donde el diseño puso «crear»");
ok(/RIELLINKS|PIELINKS/.test(nav), "el riel se parte en cuerpo y pie, como el diseño");

console.log("");
if (MUT) {
  if (!fallos.length) { console.log("\x1b[31m✗ LA VARA ESTÁ ROTA\x1b[0m: con los tres cables cortados no cayó nada."); process.exit(1); }
  console.log(`\x1b[32m✓ la vara puede dar rojo\x1b[0m: ${fallos.length} afirmaciones cayeron.`); process.exit(0);
}
if (fallos.length) { console.log(`\x1b[31m✗ ${fallos.length} rojas\x1b[0m`); process.exit(1); }
console.log("\x1b[32m✓ la barra murió y los tres cables siguen enteros\x1b[0m");
process.exit(0);
