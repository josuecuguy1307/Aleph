#!/usr/bin/env node
/**
 * verify_sidebar_workspace.mjs — EL MARCO DE 260 px, Y LOS CUATRO CABLES QUE COLGABAN DE LA
 * BARRA VIEJA. [rediseño · fase 2 · 2.4]
 *
 * `.ws-bar` era una franja de 48 px encima del lienzo ajeno. Parecía decoración y no lo era:
 * medido con grep antes de tocarla, TRES módulos se montan solos adentro buscándola por
 * nombre, y un cuarto elemento vive ahí y no tiene otro lugar.
 *
 *     ajustes.js:239                 el ⚙            → querySelector(".ws-bar")
 *     destinos-del-espacio.js:43     «Ir a…»          → querySelector(".ws-bar")
 *     conectores-del-espacio.js:30   Conectores + el host del picker de modelo
 *     #ws-estado                     el «● en vivo / ● no responde» del pack, con aria-live
 *
 * Los tres primeros anclan además en `barra.querySelector("#ws-estado")`. Renombrar el
 * contenedor los dejaba a los tres buscando un elemento inexistente: **tres botones que
 * desaparecen sin un error**. Por eso el PIE del sidebar conserva la clase `ws-bar`.
 *
 * Y el cuarto es el que más importa: `#ws-estado` es el ÚNICO aviso de que un workspace
 * instalado no está respondiendo, y lo lee un lector de pantalla por su `aria-live`. Si algo
 * deja de decirse, no es una mejora.
 *
 * ⚠️ [rediseño · fase DISEÑO] LA VARA MEDÍA UN CONTRATO QUE YA NO ES EL DE TODOS.
 * Desde la fase 6 el frame se ESCRIBE en el componente del stack, y el espacio que llega a
 * ese punto BORRA su `aside.ws-riel` para no quedarse con dos barras. Finanzas lo hizo y esta
 * vara quedó en 8 rojas sobre main —medido, testigo `7cdd61b4`— porque seguía exigiéndole el
 * riel a un archivo que ya no lo tiene. Una vara roja que nadie mira deja de ser una vara.
 *
 * Así que ahora hay DOS contratos y la vara sabe cuál le toca a cada uno:
 *
 *   · `RIEL_DE_LA_CASA`  — todavía dibujan el sidebar de 260 px acá afuera. Se les exige lo
 *                          de siempre: el marco, `‹ Inicio`, y los cuatro cables del pie.
 *   · `FRAME_EN_EL_STACK` — el riel se borró y la barra la escribe el componente adentro del
 *                          iframe. Se les exige lo CONTRARIO —que el nodo no esté— y, sobre
 *                          todo, que los cables que colgaban de él tengan su puente de vuelta:
 *                          un módulo sin puente es un botón movido sin su cable, que es el
 *                          defecto que esta casa cuenta como nº12.
 *
 * PROBADA CAYENDO
 *     node qa/verify_sidebar_workspace.mjs --mutante
 * le saca la clase `ws-bar` al pie de los que aún tienen riel, el `aria-live` al estado, y a
 * los del frame en el stack les borra los tres puentes (`aleph-go-home`, `aleph-open-settings`
 * y `aleph-open-destinos`) y el apagado del pack al volver. Exige que todo eso caiga.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const W = path.join(RAIZ, "product/app/design/workspaces");
const D = path.join(RAIZ, "product/app/design");
const MUT = process.argv.includes("--mutante");
const fallos = [];
const ok = (c, m) => { console.log(`  ${c ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m"} ${m}`); if (!c) fallos.push(m); };

/* Los que todavía dibujan el riel acá afuera, y los que ya lo mudaron adentro del stack.
   Mover un espacio de una lista a la otra es el trámite que cierra su fase. */
const RIEL_DE_LA_CASA = ["ciencia", "educacion", "legal", "oficina", "local"];
const FRAME_EN_EL_STACK = ["finanzas", "diseno"];

console.log("── el marco: sidebar de 260 px en los que todavía lo dibujan acá ──");
for (const w of RIEL_DE_LA_CASA) {
  let s = fs.readFileSync(path.join(W, w + ".html"), "utf8");
  if (MUT) s = s.replace('class="ws-pie ws-bar"', 'class="ws-pie"').replace(' aria-live="polite"', "");
  ok(/<aside class="ws-riel">/.test(s), `${w}: tiene el sidebar`);
  ok(!/<header class="ws-bar">/.test(s), `${w}: ya no tiene la barra de 48 px`);
  ok(/aleph-mascot-v2\.png/.test(s) && /ws-wordmark/.test(s), `${w}: mascota + «Aleph» en la cabecera`);
  ok(/class="ws-volver"[^>]*>‹ Inicio|‹ Inicio<\/a>/.test(s), `${w}: «‹ Inicio» como primer ítem`);
  // ── EL CABLE ──
  ok(/class="ws-pie ws-bar"/.test(s),
     `${w}: el PIE conserva la clase ws-bar (los tres módulos la buscan por nombre)`);
  ok(/id="ws-estado"[^>]*aria-live="polite"/.test(s) || /aria-live="polite"[^>]*id="ws-estado"/.test(s),
     `${w}: el estado del pack sigue con aria-live`);
  ok(/role="status"/.test(s), `${w}: …y con role=status`);
  const pie = s.slice(s.indexOf('class="ws-pie'), s.indexOf("</aside>"));
  ok(/id="ws-estado"/.test(pie), `${w}: el estado vive DENTRO del pie, que es donde anclan los tres`);
}

/* ── LOS QUE YA MUDARON EL FRAME ADENTRO ───────────────────────────────────────────────
   Acá lo que se mide NO es el marco —el marco es del stack y vive en su `.tsx`— sino que al
   borrar el riel no haya quedado un módulo sin disparador. Los tres puentes son el contrato:
   `aleph-go-home` (el `‹ Inicio` del stack), `aleph-open-settings` (su `⚙`) y
   `aleph-open-destinos` (el «Ir a…», que era el único sin puente propio). */
console.log("\n── los que mudaron el frame adentro del stack: sin riel, y con los puentes ──");
for (const w of FRAME_EN_EL_STACK) {
  let s = fs.readFileSync(path.join(W, w + ".html"), "utf8");
  if (MUT) s = s.replace(/aleph-go-home/g, "MUTADO")
               .replace(/aleph-open-settings/g, "MUTADO")
               .replace(/aleph-open-destinos/g, "MUTADO")
               .replace(/salir\(\)\.then/g, "MUTADO.then");
  /* Se sacan LOS DOS tipos de comentario, el de HTML y el de bloque de JS. Estos archivos
     documentan sus propios puentes con el nombre del mensaje adentro del comentario, así que
     buscarlo sobre el texto crudo daba verde por la documentación y no por el cable — la
     misma trampa que ya está anotada más abajo, en su versión inversa. */
  const sinComentarios = s.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  ok(!/<aside class="ws-riel">/.test(sinComentarios),
     `${w}: el riel de la casa se BORRÓ (una sola barra, y es la del stack)`);
  ok(/data\.type !== "aleph-open-settings"|type !== "aleph-open-settings"/.test(sinComentarios),
     `${w}: el ⚙ del stack tiene su puente de vuelta`);
  ok(/type !== "aleph-go-home"/.test(sinComentarios),
     `${w}: «‹ Inicio» del stack tiene su puente de vuelta`);
  /* ⚠️ [integración] ESTA ASERCIÓN SE DIO VUELTA, Y EL CONTRATO QUE MEDÍA ESTÁ DEROGADO.
     Pedía que `finanzas.html` y `diseno.html` trajeran un listener de `aleph-open-destinos`
     para que «Ir a…» tuviera puente. Medido sobre todo el árbol: ese mensaje NUNCA tuvo
     emisor —cero, en los seis stacks y en la casa—, así que la vara estaba protegiendo un
     cable que no llegaba a ningún lado y salía verde por eso.

     El dueño cerró el empate mirando la pantalla: el pie del sidebar son DOS filas, `⚙
     Settings` y la cuenta, y nada más. Lo dicen `Aleph Estandar.dc.html` («RECENT SESSIONS
     y, en el pie, Settings + la cuenta») y el artboard 38a de Legal. `Ir a…` y `Conectores`
     se alcanzan por `‹ Inicio`, que es el primer ítem del raíz y está en los seis.

     Así que ahora se mide LO CONTRARIO y por AUSENCIA: ninguna página puede cargar un
     listener sin emisor. Es la misma regla que esta sesión aplicó del otro lado cuando sacó
     el censo del pie —emisor y contestador juntos—, y sirve de trinquete para que el defecto
     no vuelva por la puerta de atrás. */
  ok(!/data\.type !== "aleph-open-destinos"/.test(sinComentarios),
     `${w}: NO carga un listener de «aleph-open-destinos» (nadie lo dispara; el pie son dos filas)`);
  /* EL HANDLER QUE VIAJÓ CON EL BOTÓN. El viejo `.ws-volver` apagaba el pack ANTES de
     navegar; el `pagehide` es el respaldo, no el camino. Si al mudar el botón adentro del
     iframe nadie llama a `salir()` en el puente, la salida más común del workspace deja de
     avisar y el pack tarda de más en apagarse. */
  const puente = sinComentarios.slice(sinComentarios.indexOf('"aleph-go-home"'));
  ok(/salir\(\)\.then/.test(puente.slice(0, 400)),
     `${w}: al volver al Inicio se apaga el pack ANTES de navegar (el handler del viejo ws-volver)`);
}

console.log("\n── los tres módulos siguen encontrando su casa ──");
for (const [f, quien] of [["../ajustes.js", "el ⚙"],
                          ["destinos-del-espacio.js", "«Ir a…»"],
                          ["conectores-del-espacio.js", "Conectores y el picker"]]) {
  const p = f.startsWith("..") ? path.join(D, f.slice(3)) : path.join(W, f);
  const s = fs.readFileSync(p, "utf8");
  ok(/querySelector\("\.ws-bar"\)/.test(s), `${quien}: sigue buscando .ws-bar — y la encuentra en el pie`);
  ok(/#ws-estado/.test(s), `${quien}: sigue anclando en #ws-estado`);
}

console.log("\n── y el ⚙ deja de flotar ──");
const aj = fs.readFileSync(path.join(D, "ajustes.js"), "utf8");
ok(/\.ws-pie #aleph-cog\{position:static/.test(aj),
   "adentro del pie el ⚙ vuelve al flujo (la regla lo clavaba fixed SIEMPRE, también en la barra vieja)");
ok(/aleph-riel/.test(aj), "y no se dibuja donde el riel ya pone AJUSTES");

console.log("\n── lo que este sidebar NO finge tener ──");
// Sin los comentarios: el mío EXPLICA que esas cuatro cosas no están, y buscar la palabra
// suelta hacía que la vara se cayera por su propia documentación. Tercera vez que me pasa en
// esta fase; queda escrito para no repetirlo una cuarta.
/* Se mide sobre uno que TODAVÍA tiene riel: `finanzas.html` ya no lo tiene, así que la
   afirmación del hueco se caía por medir el archivo equivocado — la otra mitad de las 8
   rojas que había sobre main. */
const conRiel = fs.readFileSync(path.join(W, RIEL_DE_LA_CASA[0] + ".html"), "utf8").replace(/<!--[\s\S]*?-->/g, "");
ok(!/New chat|RECENT SESSIONS/i.test(conRiel),
   "no dibuja New chat / Search / Library / RECENT SESSIONS: son del stack y entran en la fase 3");
ok(/ws-seccion/.test(conRiel), "el hueco de la sección propia está declarado, no rellenado");

console.log("");
if (MUT) {
  if (!fallos.length) { console.log("\x1b[31m✗ LA VARA ESTÁ ROTA\x1b[0m: con el pie renombrado y sin aria-live no cayó nada."); process.exit(1); }
  console.log(`\x1b[32m✓ la vara puede dar rojo\x1b[0m: ${fallos.length} afirmaciones cayeron.`); process.exit(0);
}
if (fallos.length) { console.log(`\x1b[31m✗ ${fallos.length} rojas\x1b[0m`); process.exit(1); }
console.log("\x1b[32m✓ el marco es de 260 px y los cuatro cables siguen enteros\x1b[0m");
process.exit(0);
