#!/usr/bin/env node
/**
 * verify_piel_flag.mjs — EL INTERRUPTOR DE LA PIEL, MEDIDO EN SUS DOS BRAZOS.
 * [rediseño · fase 1 · cable de seguridad (b)]
 *
 * QUÉ MIDE
 * ────────
 * El cable (b) parte en dos algo que estaba pegado: la hoja de piel **viaja** siempre
 * adentro del `dist` de cada stack, pero sólo se **aplica** cuando la casa manda
 * `aleph_piel=v2` en la URL del `<iframe>`. Sin eso, volver atrás del rediseño costaría un
 * build por stack.
 *
 * Un interruptor se mide por sus DOS brazos, no por uno. Una vara que sólo probara «con el
 * flag, aplica» dejaría pasar el peor defecto posible: que aplique SIEMPRE. Acá se exige:
 *
 *     con `aleph_piel=v2`  →  se marca `data-aleph-piel` y se agrega la hoja
 *     sin el flag          →  NO se marca y NO se agrega  (la cara queda como hoy)
 *     fuera de un iframe   →  NO hace absolutamente nada   (LEY 0)
 *
 * Y del lado de la casa, lo mismo con `piel.js`: `?piel=v2` prende y recuerda, `?piel=off`
 * apaga y SE ACUERDA, sin espacio el default es apagado, y un valor inventado no prende.
 * (El `off` recordado no es un capricho: con default POR ESPACIO, olvidar lo volvería a
 * prender en la recarga siguiente.)
 *
 * POR QUÉ UN DOBLE DE DOM Y NO UN NAVEGADOR. Lo que hay que medir es una decisión de tres
 * ramas, no layout ni CSS: `dom_minimo.mjs` no alcanza (no tiene `documentElement` ni
 * `createElement` con `rel`/`href`) y levantar Chrome para esto sería pagar 3 s por
 * pantalla para probar un `if`. El doble de acá es mínimo, propio y declarado: los nodos
 * que estos dos archivos tocan y nada más. Si mañana hace falta cascada real, se mide con
 * `qa/vara_visual.mjs`, que sí levanta un navegador.
 *
 * CÓMO SE PRUEBA QUE PUEDE DAR ROJO
 * ─────────────────────────────────
 *     node qa/verify_piel_flag.mjs --mutante
 *
 * corre los DOS archivos mutados —al de los stacks se le saca el `if (VERSION !== "v2")`,
 * al de la casa el `?piel=off`— y exige que la vara caiga por los dos.
 */

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const RAIZ = path.resolve(AQUI, "..");
const MUTANTE = process.argv.includes("--mutante");

/** Los seis lugares donde vive la mitad del stack. El archivo tiene que ser el MISMO. */
const STACKS = {
  ciencia:   "third_party/openscience/frontend/workspace/public",
  oficina:   "third_party/openwork/apps/app/public",
  finanzas:  "third_party/vibetrading/frontend/public",
  educacion: "third_party/deeptutor/web/public",
  legal:     "third_party/dochaus/apps/web/public",
  diseno:    "third_party/codesign/apps/desktop/src/renderer/public",
};
/** Dónde se carga en cada stack (la única cirugía sobre upstream: UNA línea). */
const ENGANCHES = {
  ciencia:   "third_party/openscience/frontend/workspace/index.html",
  oficina:   "third_party/openwork/apps/app/index.html",
  finanzas:  "third_party/vibetrading/frontend/index.html",
  educacion: "third_party/deeptutor/web/app/layout.tsx",
  legal:     "third_party/dochaus/apps/web/index.html",
  diseno:    "third_party/codesign/apps/desktop/src/renderer/index.html",
};
const WORKSPACES = ["ciencia", "diseno", "educacion", "finanzas", "legal", "oficina"];

const fallos = [];
function ok(cond, msg) {
  console.log(`  ${cond ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m"} ${msg}`);
  if (!cond) fallos.push(msg);
}

/* ── EL DOBLE DE DOM ───────────────────────────────────────────────────────────────────
 * Los nodos que estos dos archivos tocan, y nada más. */
function casa({ search = "", enIframe = true, guardado = null } = {}) {
  const head = { hijos: [], appendChild(n) { const i = this.hijos.indexOf(n); if (i >= 0) this.hijos.splice(i, 1); this.hijos.push(n); n.parentNode = head; return n; } };
  const raiz = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; } };
  const almacen = new Map(guardado ? Object.entries(guardado) : []);
  const oyentes = {};
  const win = {
    location: { search, href: "http://127.0.0.1:1/?" + search.replace(/^\?/, "") },
    URLSearchParams, encodeURIComponent,
    document: {
      documentElement: raiz, head,
      createElement: (tag) => ({ tag, parentNode: null }),
      addEventListener: (ev, fn) => { (oyentes[ev] ||= []).push(fn); },
    },
    localStorage: {
      getItem: (k) => (almacen.has(k) ? almacen.get(k) : null),
      setItem: (k, v) => almacen.set(k, String(v)),
      removeItem: (k) => almacen.delete(k),
    },
    console,
  };
  win.window = win;
  win.parent = enIframe ? { distinto: true } : win;   // LEY 0 se decide acá
  win.globalThis = win;
  return { win, head, raiz, almacen, disparar: (ev) => (oyentes[ev] || []).forEach((f) => f()) };
}

function correr(codigo, ctx) {
  vm.createContext(ctx.win);
  vm.runInContext(codigo, ctx.win, { timeout: 5000 });
  return ctx;
}

/* ── 1 · EL CONTRATO ───────────────────────────────────────────────────────────────────── */
console.log("── contrato: el mismo archivo en los seis, y cargado en los seis ──");
const shas = new Map();
const shasCss = new Map();
for (const [ws, dir] of Object.entries(STACKS)) {
  const js = path.join(RAIZ, dir, "aleph-piel.js");
  const css = path.join(RAIZ, dir, "aleph-piel.css");
  ok(fs.existsSync(js), `${ws}: existe ${dir}/aleph-piel.js`);
  ok(fs.existsSync(css), `${ws}: existe ${dir}/aleph-piel.css`);
  const crypto = await import("node:crypto");
  const sha = (f) => crypto.createHash("sha256").update(fs.readFileSync(f)).digest("hex");
  if (fs.existsSync(js)) shas.set(ws, sha(js));
  // [fase 3] LA HOJA TAMBIÉN. Ahora que `aleph-piel.css` lleva la paleta y el mapeo de los
  // seis, seis copias que derivan serían seis paletas distintas — que es exactamente el
  // problema que este archivo existe para no tener. El mapeo de LOS SEIS vive adentro de UNA
  // hoja a propósito: un stack ignora los nombres de token que no usa.
  if (fs.existsSync(css)) shasCss.set(ws, sha(css));
  // Y la letra: las tres familias, subset latin + latin-ext.
  const fdir = path.join(RAIZ, dir, "fonts");
  const woff = fs.existsSync(fdir) ? fs.readdirSync(fdir) : [];
  for (const fam of ["poppins", "instrumentserif", "jetbrainsmono"]) {
    ok(woff.some((f) => f.startsWith(fam)), `${ws}: tiene los woff2 de ${fam}`);
  }
  ok(fs.existsSync(path.join(RAIZ, dir, "aleph-mascot-v2.png")), `${ws}: tiene la mascota`);
}
ok(new Set(shas.values()).size === 1,
   `los ${shas.size} aleph-piel.js son byte-idénticos (${new Set(shas.values()).size} sha distinto/s)`);
ok(new Set(shasCss.values()).size === 1,
   `las ${shasCss.size} aleph-piel.css son byte-idénticas (${new Set(shasCss.values()).size} sha distinto/s)`);
for (const [ws, f] of Object.entries(ENGANCHES)) {
  const p = path.join(RAIZ, f);
  ok(fs.existsSync(p) && /src="\/aleph-piel\.js"/.test(fs.readFileSync(p, "utf8")),
     `${ws}: ${f} carga /aleph-piel.js`);
}
for (const ws of WORKSPACES) {
  const p = path.join(RAIZ, "product/app/design/workspaces", `${ws}.html`);
  const s = fs.readFileSync(p, "utf8");
  /* ⚠️ LOS PARÉNTESIS VACÍOS ERAN PARTE DEL CONTRATO Y DEJARON DE SERLO. `query()` sin
     argumento no sabía a qué espacio le habla; desde que el default es POR ESPACIO se llama
     `query(WS)`. Pedir los paréntesis vacíos ponía esta vara en rojo justo cuando el código
     pasó a estar bien. Se mide lo que importa —que la query salga de `AlephPiel`, no a mano—
     y se deja el argumento libre. */
  ok(/AlephPiel\.query\([^)]*\)/.test(s),
     `${ws}.html suma AlephPiel.query(…) a la URL del iframe`);
  ok(/src="\.\.\/piel\.js"/.test(s), `${ws}.html carga ../piel.js`);
}

/* ── 1.bis · LA HOJA YA NO ESTÁ VACÍA ─────────────────────────────────────────────────── */
console.log("\n── la hoja trae la paleta, la letra y el mapeo de los seis ──");
{
  const hoja = fs.readFileSync(path.join(RAIZ, STACKS.ciencia, "aleph-piel.css"), "utf8");
  ok(/--al-lienzo:\s*#f4f3f1/.test(hoja), "declara el lienzo del estándar (#f4f3f1)");
  ok(/--al-lienzo:\s*#0f0e0d/.test(hoja), "…y el oscuro derivado (#0f0e0d)");
  ok(/data-aleph-scheme="dark"/.test(hoja), "el oscuro cuelga de NUESTRO atributo, no del de cada stack");
  /* ⚠️ [fase 5 · 5.2] ESTOS NOMBRES SE MIDIERON, NO SE ELIGIERON. La versión anterior de
   * esta lista exigía `--theme-background` para «Legal/Ciencia» — un nombre con CERO
   * definiciones en los dos árboles. O sea que la vara se ponía verde comprobando que la
   * hoja escribe una variable que nadie lee: la piel de esos dos stacks era inerte y esto
   * lo certificaba. Cada entrada de acá abajo tiene su contraparte medida en el `dist`. */
  for (const [n, re] of [["Oficina", /--dls-surface:\s*var\(--al-lienzo\)/],
                         ["Educación (shadcn nuevo, color)", /--background:\s*var\(--al-lienzo\)/],
                         ["Finanzas (shadcn viejo, triplete HSL)", /--background:\s*var\(--al-lienzo-h\)/],
                         ["Legal (su `--bg`)", /--bg:\s*var\(--al-lienzo\)/],
                         ["Ciencia (su capa base)", /--background-base:\s*var\(--al-lienzo\)/],
                         ["Diseño (su `--color-background`)", /--color-background:\s*var\(--al-lienzo\)/]])
    ok(re.test(hoja), `mapea los tokens de ${n}`);
  /* Y LOS TRES BLOQUES DE NOMBRE GENÉRICO VAN ACOTADOS. `--background`, `--bg` y
   * `--background-base` los usan varios stacks con formatos distintos: sueltos en un `:root`
   * compartido, uno le rompe la cara al otro en silencio. */
  for (const ws of ["finanzas", "legal", "ciencia", "diseno"])
    ok(new RegExp(`:root\\[data-aleph-ws="${ws}"\\]`).test(hoja), `el bloque de ${ws} está acotado por data-aleph-ws`);
  /* ⚠️ Y ACÁ VA LA REGLA GENERAL, PORQUE LA LISTA DE ARRIBA NO ALCANZÓ. Enumerar los
     bloques que SÍ están acotados deja verde una hoja que suma uno nuevo sin acotar — y eso
     es exactamente lo que pasó: el bloque de shadcn vivía en un `:root` suelto declarando
     `--muted`, `--accent` y `--border`, tres nombres que Legal usa con OTRA semántica (texto
     y línea, no fondo). En pantalla: el subtítulo de cada pantalla, el chip de ID de cada
     matter y EL ÍTEM ACTIVO DE LA BARRA, ilegibles. El propio archivo ya había declarado el
     peligro para `--bg`/`--panel`/`--text` y volvió a pasar con otros nombres.

     La regla, y se mide por AUSENCIA: en esta hoja, un bloque que declara tokens fuera del
     namespace `--al-*` tiene que estar acotado por `data-aleph-ws`. El namespace propio es
     la única excepción —contado sobre los seis árboles, cero stacks declaran un `--al-`— y
     además es la fuente que todos los bloques acotados leen. */
  {
    const bloques = [...hoja.matchAll(/(?:^|\n)([^{}\n][^{}]*?)\{([^{}]*)\}/g)];
    const sueltos = bloques
      .filter(([, sel, cuerpo]) => !sel.includes("data-aleph-ws")
        && /(--[a-zA-Z0-9-]+)\s*:/.test(cuerpo)
        && (cuerpo.match(/--[a-zA-Z0-9-]+\s*:/g) || []).some((t) => !t.startsWith("--al-")))
      .map(([, sel, cuerpo]) => sel.trim().replace(/\s+/g, " ").slice(0, 40) + " → "
        + (cuerpo.match(/--[a-zA-Z0-9-]+(?=\s*:)/g) || []).filter((t) => !t.startsWith("--al-")).slice(0, 4).join(" "));
    ok(sueltos.length === 0,
       "ningún bloque de tokens ajenos vive en un selector sin acotar",
       sueltos.join(" | "));
  }
  ok(/data-aleph-ws/.test(fs.readFileSync(path.join(RAIZ, STACKS.ciencia, "aleph-piel.js"), "utf8")),
    "…y el script escribe ese atributo (si no, los bloques acotados no aplican nunca)");
  ok(/@font-face/.test(hoja) && /Poppins/.test(hoja) && /Instrument Serif/.test(hoja) && /JetBrains Mono/.test(hoja),
     "trae las tres familias");
  /* DOS AGUJEROS DISTINTOS, TAPADOS LOS DOS.
     · SEIS DIGITOS. El regex cazaba `#rrggbb` y `color:#fff` —tres— pasaba en verde mientras
       pintaba flecha blanca sobre boton casi blanco en oscuro. Ahora toma 3 a 8 y ademas los
       NOMBRES de color, que son la otra forma de clavar uno.
     · FALSOS ROJOS. De los estados para abajo hay hex que NO son un color clavado: los que
       viven dentro de un COMENTARIO explicando de donde sale un valor, y el RESPALDO de un
       token (`var(--al-tinta, #1c1c1a)`). Medido contra main: 10 coincidencias, las 10 falsas.
       Se sacan los dos antes de mirar.
     El respaldo hoy no aparece —los 42 se sacaron— pero la limpieza se queda: el dia que
     alguien reponga uno legitimamente, este assert no tiene que volverse ruido. */
  {
    const cola = (hoja.split("LOS CUATRO ESTADOS")[1] || "")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/var\(\s*--[A-Za-z0-9_-]+\s*,[^)]*\)/g, "VAR");
    const crudos = (cola.match(/#[0-9a-f]{3,8}\b/ig) || [])
      .concat(cola.match(/:\s*(?:white|black|red|blue|green|gray|grey)\b/ig) || []);
    ok(crudos.length === 0,
       `de los estados para abajo no hay un color CRUDO: todo apunta a --al-* (${crudos.length ? crudos.join(" ") : "ninguno"})`);
  }
}

/* ── 2 · EL MECANISMO · la mitad del STACK ─────────────────────────────────────────────── */
console.log("\n── mecanismo · aleph-piel.js (la mitad del stack), sus tres ramas ──");
let stackJs = fs.readFileSync(path.join(RAIZ, STACKS.ciencia, "aleph-piel.js"), "utf8");
if (MUTANTE) stackJs = stackJs.replace('if (VERSION !== "v2") return;', "/* MUTADO */");

{
  const c = correr(stackJs, casa({ search: "?aleph_ws=ciencia&aleph_piel=v2" }));
  c.disparar("DOMContentLoaded");
  const link = c.head.hijos.find((n) => n.id === "aleph-piel");
  ok(c.raiz.getAttribute("data-aleph-piel") === "v2", "con aleph_piel=v2 · marca data-aleph-piel");
  ok(!!link && link.rel === "stylesheet" && String(link.href).startsWith("/aleph-piel.css"),
     "con aleph_piel=v2 · agrega la hoja /aleph-piel.css");
  ok(!!link && c.head.hijos[c.head.hijos.length - 1] === link,
     "con aleph_piel=v2 · la hoja queda ÚLTIMA en el head tras DOMContentLoaded (gana la cascada)");
}
{
  const c = correr(stackJs, casa({ search: "?aleph_ws=ciencia&aleph_scheme=dark" }));
  c.disparar("DOMContentLoaded");
  ok(c.raiz.getAttribute("data-aleph-piel") === null, "SIN el flag · no marca nada");
  ok(c.head.hijos.length === 0, "SIN el flag · no agrega hoja — la cara queda como hoy");
}
{
  const c = correr(stackJs, casa({ search: "?aleph_ws=ciencia&aleph_piel=v2", enIframe: false }));
  ok(c.raiz.getAttribute("data-aleph-piel") === null && c.head.hijos.length === 0,
     "LEY 0 · fuera de un iframe no hace nada, ni con el flag puesto");
}

/* ── 3 · EL MECANISMO · la mitad de la CASA ────────────────────────────────────────────── */
console.log("\n── mecanismo · piel.js (la mitad de la casa), sus cuatro caminos ──");
let casaJs = fs.readFileSync(path.join(RAIZ, "product/app/design/piel.js"), "utf8");
if (MUTANTE) casaJs = casaJs.replace('if (q === "off" || q === "0") {', "if (false) {");

function piel(opts) { const c = correr(casaJs, casa(opts)); return { P: c.win.AlephPiel, c }; }
{
  const { P, c } = piel({ search: "?piel=v2" });
  ok(P.version() === "v2" && P.query() === "&aleph_piel=v2", "?piel=v2 · prende");
  ok(c.almacen.get("aleph-piel") === "v2", "?piel=v2 · lo recuerda");
}
{
  const { P } = piel({ search: "", guardado: { "aleph-piel": "v2" } });
  ok(P.version() === "v2", "sin query pero recordado · sigue prendida");
}
{
  const { P, c } = piel({ search: "?piel=off", guardado: { "aleph-piel": "v2" } });
  ok(P.version() === "" && P.query() === "", "?piel=off · apaga");
  /* ⚠️ APAGAR ES GUARDAR «off», NO BORRAR LA CLAVE — y la vara pedía lo contrario.
     Cuando el default era uno solo (apagado), borrar alcanzaba. Con el default POR ESPACIO,
     no quedar nada guardado significa «prendido si a tu espacio le toca», así que el olvido
     hacía que el apagado durara UNA pantalla. La frase de esta misma vara —«si no, el
     apagado sería mentira»— hoy argumenta a favor de recordar, no de olvidar. */
  ok(c.almacen.get("aleph-piel") === "off", "?piel=off · SE ACUERDA de que apagó (si no, el apagado duraría una pantalla)");
  ok(P.version("finanzas") === "", "?piel=off · y sigue apagada para un espacio que trae default");
}
{
  const { P } = piel({ search: "" });
  ok(P.version() === "" && P.query() === "", "sin nada · el default es APAGADO");
}
{
  const { P } = piel({ search: "?piel=rojo" });
  ok(P.version() === "", "un valor inventado no prende");
}

/* ── VEREDICTO ─────────────────────────────────────────────────────────────────────────── */
console.log("");
if (MUTANTE) {
  if (fallos.length === 0) {
    console.log("\x1b[31m✗ LA VARA ESTÁ ROTA\x1b[0m: con los dos archivos mutados no cayó ninguna afirmación.");
    process.exit(1);
  }
  console.log(`\x1b[32m✓ la vara puede dar rojo\x1b[0m: ${fallos.length} afirmaciones cayeron con la mutación.`);
  process.exit(0);
}
if (fallos.length) { console.log(`\x1b[31m✗ ${fallos.length} rojas\x1b[0m`); process.exit(1); }
console.log("\x1b[32m✓ el interruptor de la piel funciona en sus dos brazos, en los seis stacks\x1b[0m");
process.exit(0);
