#!/usr/bin/env node
/**
 * vara_visual.mjs — LA PRIMERA VARA QUE MIRA LA CARA. [rediseño · fase 1 · cable (c)]
 *
 * QUÉ MIDE, Y POR QUÉ NINGUNA DE LAS 356 QUE YA ESTÁN PUEDE MEDIRLO
 * ─────────────────────────────────────────────────────────────────
 * Medido antes de escribir una línea, sobre `main @ c459d2d2`:
 *
 *     grep pixelmatch      → 0
 *     grep toMatchSnapshot → 0
 *     archivos que llaman screenshot(  → 81
 *
 * O sea: la casa saca 81 capturas y **no compara ninguna**. Son evidencia, no red. Un
 * rediseño entero —tokens, tres familias tipográficas, un barrido de pesos— corre hoy sin
 * una sola vara capaz de decir «la cara cambió y nadie lo quiso». Ésta es esa vara.
 *
 * POR QUÉ SIN PLAYWRIGHT, Y ESTO NO ES PEREZA
 * ───────────────────────────────────────────
 * La política ya estaba escrita y medida (`qa/dom_minimo.mjs`): «playwright no está
 * instalado, no hay `node_modules/playwright` ni `~/.cache/ms-playwright`». **Re-medido
 * hoy y sigue siendo cierto**: `~/Library/Caches/ms-playwright` está vacío, no hay
 * playwright global y no hay `package.json` en la raíz. Una vara que necesita un `npm
 * install` que nadie corre no es verde: es silencio.
 *
 * Pero `dom_minimo` no alcanza acá y su propio docstring lo dice: «no implementa layout, ni
 * CSS… si una vara futura necesita algo de eso, la respuesta es levantar un navegador de
 * verdad». Esto es exactamente ese caso, así que se levanta uno **de los que ya están en la
 * máquina**:
 *
 *     Google Chrome  → --headless=new --screenshot   (capturar)
 *     sips           → -Z 640 -s format bmp          (normalizar; viene con macOS)
 *     node           → comparar BMP crudo            (24 bpp, sin compresión, offset 54)
 *
 * Cero dependencias de npm. Mecanismo existente antes que mecanismo nuevo.
 *
 * ⚠️ EL INSTRUMENTO, DECLARADO
 * ────────────────────────────
 *   · **Chrome estrangula timers en pestañas de fondo** — ya anuló un hallazgo en este
 *     proyecto. Acá no aplica por construcción: `--headless=new --screenshot` es una
 *     corrida de una sola página sin pestañas, y además se usa `--virtual-time-budget`,
 *     que avanza el reloj virtual hasta que la página se queda quieta en vez de esperar
 *     tiempo de pared. Si algún día esto pasa a un navegador persistente, hay que volver
 *     a mirarlo.
 *   · **EL RELOJ SE CORRE, NO SE CONGELA — y esto también se midió cayendo.** La primera
 *     versión clavaba `Date.now()` en una constante. Chrome **se colgó**: cualquier lazo
 *     que espere «que pasen N ms» ve 0 transcurrido para siempre, la página nunca se queda
 *     quieta y `--virtual-time-budget` nunca drena. La captura no volvía a los 90 s. Acá el
 *     reloj ARRANCA en un instante fijo —la hora del día es lo que elige el saludo de
 *     `Home.dc.html`— y AVANZA con el real: determinista para lo que se VE, monótono para
 *     lo que CORRE.
 *   · **DOS BANDERAS QUE CUELGAN A CHROME EN ESTA MÁQUINA, medidas y aisladas** (Chrome
 *     152.0.7977.82, macOS 24.6):
 *       `--run-all-compositor-stages-before-draw` → colgado indefinido (6 min y seguía);
 *       `--user-data-dir=<dir virgen>`            → colgado indefinido, y NO lo arregla
 *                                                   apagar updater, sync, component-update
 *                                                   ni background-networking (probado).
 *     Sin las dos, la captura tarda **2,5 s**. Consecuencia declarada: esta vara corre
 *     Chrome **con el perfil por defecto del dueño**, en modo `--screenshot` de un solo
 *     disparo (no abre ventana, no toca su sesión). Si algún día hace falta aislar el
 *     perfil, hay que resolver antes ese cuelgue — no volver a poner la bandera.
 *   · `spawnSync` mata con **SIGKILL**: Chrome se come el SIGTERM del `timeout` por
 *     defecto, y un instrumento que no se puede matar es otro proceso huérfano.
 *   · **La página se sirve por un server de esta vara**, no por `python3 -m http.server`,
 *     porque hace falta INYECTAR determinismo antes del primer script de la página:
 *     `Date` congelado, `Math.random` con semilla, animaciones y transiciones apagadas,
 *     caret invisible, y el tema forzado por `localStorage['aleph-theme']` (la clave real,
 *     `theme.js:11`) antes de que `theme.js` la lea.
 *   · **`/v1/*` se rechaza AL INSTANTE, y esto no es cosmético.** Primera corrida de
 *     determinismo: 15 de 16 pantallas dieron 0,000 % y **`Historial.dark` dio 2,860 %**.
 *     El diff mostró el vacío («Todavía no hay sesiones») dibujado a distinta altura entre
 *     corridas: el `fetch` a `/v1/*` moría por timeout de red en un momento distinto cada
 *     vez, así que el layout se asentaba distinto. Rechazarlo en el acto hace que «no hay
 *     backend» sea un hecho, no una carrera. **No se sube el umbral para tapar un flake:
 *     se le saca la fuente al flake.**
 *   · **Sin backend.** Las pantallas se capturan tal como quedan cuando `/v1/*` no
 *     contesta: portada de sesión, vacíos, estados de carga resueltos. Eso NO es un
 *     defecto de la vara — es su alcance, y está declarado: mide la CARA (frame, letra,
 *     color, peso), no el contenido que trae el dominio.
 *   · **Se compara a 640 px de ancho**, no a 1280: el antialiasing de texto a tamaño
 *     completo mete ruido que no es un cambio de diseño. Bajar de escala lo promedia.
 *
 * PANTALLAS INESTABLES — LO QUE LA VARA ENCONTRÓ ANTES DE MEDIR NADA
 * ──────────────────────────────────────────────────────────────────
 * Antes de comparar contra la baseline, cada pantalla se captura **dos veces seguidas sin
 * tocar nada**. Si esas dos ya difieren, la pantalla es **[no medible] hoy** y se dice por
 * nombre: compararla contra la baseline daría un rojo que no es del rediseño.
 *
 * Medido sobre `main @ c459d2d2`, sin una línea de rediseño puesta:
 *
 *     Historial  → hasta 2,86 % entre dos capturas propias
 *     Biblioteca → hasta 0,85 %
 *
 * El diff (`qa/visual/salida/*.diff.png`) señala **la fila de chips de espacio**: a veces
 * está y a veces no, y cuando está empuja el vacío hacia abajo. Las dos pantallas son
 * justamente las dos que alimenta `product/app/design/espacios.js`, que resuelve sus chips
 * con un `import()` dinámico encadenado a un `fetch`. **Es una carrera del producto, no de
 * la vara** — y ninguna de las 356 varas la veía, porque ninguna mira la pantalla.
 * Queda declarada como hallazgo para la fase 2; acá NO se arregla (una obra por vez) y
 * tampoco se tapa subiendo el umbral.
 *
 * CÓMO SE PRUEBA QUE ESTA VARA PUEDE DAR ROJO
 * ───────────────────────────────────────────
 *     node qa/vara_visual.mjs --mutante
 *
 * inyecta una mutación de color en el CSS servido —`--accent` y `--ink` a rojo puro— y
 * EXIGE que la comparación se ponga roja **en TODAS las pantallas**, no en algunas.
 * `--ink` es la tinta del texto: no hay pantalla de este producto sin texto, así que una
 * mutación que no las tumbe a las doce está diciendo que la vara no ve la letra — que es
 * justo lo que la fase 1 va a cambiar. (Con sólo `--accent` caían 4 de 12: el acento vive
 * en pocos píxeles. Se dejó anotado porque la primera versión del mutante daba «verde»
 * sobre 8 pantallas y eso era una vara que se cree probada y no lo está.) Si con la mutación puesta la vara sigue
 * verde, la vara está rota y lo dice con esas palabras. Una vara que no puede dar rojo no
 * mide nada.
 *
 * USO
 * ───
 *     node qa/vara_visual.mjs                  comparar contra la baseline
 *     node qa/vara_visual.mjs --actualizar     (re)escribir la baseline
 *     node qa/vara_visual.mjs --mutante        probar que puede dar rojo
 *     node qa/vara_visual.mjs --pantalla=Home  una sola pantalla
 *     node qa/vara_visual.mjs --umbral=0.5     % de píxeles distintos tolerado
 *
 * SALIDA: en rojo escribe `qa/visual/salida/<pantalla>.<tema>.{actual,diff}.png` para poder
 * MIRAR qué cambió. La baseline se guarda en PNG (≈40 KB) y no en BMP (≈800 KB): el BMP es
 * el formato de comparación, no el de archivo.
 */

import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const RAIZ = path.resolve(AQUI, "..");
const FRONT = path.join(RAIZ, "product/app/design");
const BASE = path.join(AQUI, "visual/baseline");
const SALIDA = path.join(AQUI, "visual/salida");
const TMP = fs.mkdtempSync(path.join(process.env.TMPDIR || "/tmp", "vara-visual-"));

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PUERTO = 8791 + (process.pid % 200);      // no chocar con otra corrida
const ANCHO = 1280, ALTO = 840;                 // el tamaño de la ventana real (tauri.conf)
const COMPARA_ANCHO = 640;

/** Tolerancia por canal: por debajo de esto, dos píxeles son "el mismo" (antialiasing). */
const TOL_CANAL = 12;
/** % de píxeles distintos que se tolera antes de declarar la pantalla cambiada.
 *  0,10 % NO es un número elegido a ojo: dos corridas limpias consecutivas contra la misma
 *  baseline dieron **máximo 0,025 %** en las 12 pantallas, así que 0,10 es 4× el ruido
 *  medido. Y se eligió por lo que deja pasar, no por lo que deja entrar: con 0,35 % la
 *  mutación de `--accent` sólo tumbaba 4 de 12; con 0,10 % tumba las 12. Un umbral que
 *  deja pasar un cambio de color no es un umbral, es un permiso. */
let UMBRAL_PCT = 0.10;

/* ── LAS PANTALLAS ────────────────────────────────────────────────────────────────────
 * Sólo pantallas NUESTRAS (`product/app/design`), que es lo que la fase 1 toca. Los seis
 * workspaces NO están: su cara la sirve un proceso ajeno adentro de un `<iframe>` y sin
 * ese proceso levantado la captura sería un rectángulo vacío — o sea una baseline que no
 * puede detectar nada. Entran en la fase 3, con su pack vivo. */
const PANTALLAS = [
  "Home.dc.html",
  "Agentes.dc.html",
  "Settings.dc.html",
  "Historial.dc.html",
  "Biblioteca.dc.html",
  "Modelos.dc.html",
  "Conectores.dc.html",
  "Estados.dc.html",
  "Ayuda.dc.html",
  /* [fase 2 · 2.4] UN WORKSPACE, a propósito, y con su pack APAGADO. La vara rechaza `/v1/*`
   * al instante, así que lo que se captura es el marco de la casa —el sidebar de 260 px— más
   * la pantalla honesta de «no está corriendo». Es exactamente la mitad que esta fase toca:
   * el lienzo de adentro es del stack y entra en la fase 3. Con los seis pasaría lo mismo
   * seis veces; uno alcanza para ver el marco. */
  "workspaces/finanzas.html",
];
const TEMAS = ["light", "dark"];

/* ── LAS DOS QUE VOLVIERON ────────────────────────────────────────────────────────────
 * `Historial` y `Biblioteca` estuvieron fuera de la medición mientras eran BIESTABLES: dos
 * caras distintas de la misma pantalla sin tocar nada, 2,4–2,9 % entre dos capturas propias.
 * La causa estaba en NUESTRO código y esta vara fue lo único que la vio: `espacios.js` es
 * `type="module"` y las dos pantallas leían `window.AlephEspacios` una sola vez
 * (`if(!E) return;`), así que si el módulo llegaba después del montaje la fila de chips no
 * se dibujaba nunca — sin reintento y sin error.
 * Arreglado en la fase 2: el módulo AVISA (`aleph:espacios`) y las pantallas ESPERAN.
 * Vuelven a la lista. Si alguna vuelve a ponerse biestable, el chequeo de estabilidad de
 * abajo la va a nombrar sola — no hace falta una lista para eso. */
const DECLARADAS_INESTABLES = {};


const args = process.argv.slice(2);
const tiene = (f) => args.includes(f);
const valor = (f, d) => { const a = args.find((x) => x.startsWith(f + "=")); return a ? a.slice(f.length + 1) : d; };
const MODO_ACTUALIZAR = tiene("--actualizar");
const MODO_MUTANTE = tiene("--mutante");
const SOLO = valor("--pantalla", null);
UMBRAL_PCT = parseFloat(valor("--umbral", String(UMBRAL_PCT)));

/* ── EL SERVER QUE INYECTA DETERMINISMO ───────────────────────────────────────────────
 * Un static server de 40 líneas que, en toda respuesta HTML, mete el bloque de abajo justo
 * después de `<head>`. Va PRIMERO porque tiene que ganarle a `theme.js` (que lee
 * `localStorage` antes del primer paint, `theme.js:89-91`) y a cualquier `Date.now()` de
 * arranque — `Home.dc.html` elige su saludo por la hora del día. */
const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
  ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".ico": "image/x-icon" };

function inyeccion(tema) {
  const mut = MODO_MUTANTE
    ? `document.addEventListener('DOMContentLoaded',function(){var s=document.createElement('style');`
      + `s.textContent=':root,html[data-theme="light"]{--accent:#ff0000!important;--accent-deep:#ff0000!important;--ink:#ff0000!important}';`
      + `document.head.appendChild(s);});`
    : "";
  return `<script>(function(){
  try{localStorage.setItem('aleph-theme','${tema}');}catch(e){}
  /* EL RELOJ SE CORRE, NO SE CONGELA: ver la nota del encabezado. */
  var FIJO=1756500000000;               /* 2026-08-29T22:00:00Z */
  var D=Date, T0=D.now();
  function F(){ if(arguments.length===0) return new D(FIJO+(D.now()-T0)); return new (Function.prototype.bind.apply(D,[null].concat([].slice.call(arguments)))); }
  F.now=function(){return FIJO+(D.now()-T0);}; F.parse=D.parse; F.UTC=D.UTC; F.prototype=D.prototype;
  try{window.Date=F;}catch(e){}
  var sem=42; try{Math.random=function(){sem=(sem*1103515245+12345)&0x7fffffff;return sem/0x7fffffff;};}catch(e){}
  /* SIN BACKEND, PERO SIEMPRE AL MISMO TIEMPO: ver la nota del encabezado. */
  try{var of=window.fetch;window.fetch=function(u){var s=String((u&&u.url)||u||'');
    if(s.indexOf('/v1/')>=0) return Promise.reject(new TypeError('vara_visual: sin backend'));
    return of.apply(this,arguments);};}catch(e){}
  ${mut}
})();</script>
<style id="vara-visual-quieta">*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}
html{scrollbar-width:none}::-webkit-scrollbar{display:none}</style>`;
}

function levantarServer(tema) {
  return new Promise((res) => {
    const srv = createServer((req, rq) => {
      let p = decodeURIComponent(req.url.split("?")[0]);
      if (p === "/") p = "/Home.dc.html";
      const abs = path.join(FRONT, p);
      if (!abs.startsWith(FRONT) || !fs.existsSync(abs) || fs.statSync(abs).isDirectory()) {
        rq.writeHead(404, { "content-type": "text/plain" }); return rq.end("no");
      }
      const ext = path.extname(abs);
      if (ext === ".html") {
        let html = fs.readFileSync(abs, "utf8");
        const i = html.search(/<head[^>]*>/i);
        html = i >= 0
          ? html.slice(0, html.indexOf(">", i) + 1) + inyeccion(tema) + html.slice(html.indexOf(">", i) + 1)
          : inyeccion(tema) + html;
        rq.writeHead(200, { "content-type": MIME[ext], "cache-control": "no-store" });
        return rq.end(html);
      }
      rq.writeHead(200, { "content-type": MIME[ext] || "application/octet-stream", "cache-control": "no-store" });
      fs.createReadStream(abs).pipe(rq);
    });
    srv.listen(PUERTO, "127.0.0.1", () => res(srv));
  });
}

/* ── CAPTURA Y NORMALIZACIÓN ──────────────────────────────────────────────────────────── */
/**
 * ⚠️ ASÍNCRONA, Y ÉSTA ES LA TRAMPA QUE MÁS CARO SALIÓ (tres corridas colgadas de 90 s).
 *
 * La primera versión llamaba a Chrome con `spawnSync`. `spawnSync` **bloquea el event loop
 * de Node** — y el server que le sirve la página a Chrome vive EN ESTE MISMO PROCESO. O
 * sea: Chrome pedía el HTML, el server no podía contestarle porque el hilo estaba
 * bloqueado esperando a Chrome, y Chrome esperaba el HTML. Un abrazo mortal perfecto, que
 * desde afuera se ve idéntico a «Chrome se colgó» — y por eso se persiguió primero a las
 * banderas. La misma orden en una shell tarda 2,4 s; adentro de la vara no volvía nunca.
 *
 * Se deja escrito porque el síntoma miente: **el instrumento colgado era el nuestro.**
 */
/** Chrome falla al azar en esta máquina (SIGKILL a los 90 s, ~1 de cada 30 arranques).
 *  Se reintenta dos veces; si igual no sale, la pantalla se declara NO CAPTURABLE y se
 *  nombra. Lo que NO se hace es tumbar la corrida entera por un arranque perdido. */
async function capturarConReintento(pantalla, destino, intentos = 3) {
  let ultimo = null;
  for (let i = 0; i < intentos; i++) {
    try { await capturarUna(pantalla, destino); return; }
    catch (e) { ultimo = e; try { fs.rmSync(destino, { force: true }); } catch (_) {} }
  }
  throw ultimo;
}

function capturarUna(pantalla, destino) {
  const errF = path.join(TMP, "chrome.err");
  const err = fs.openSync(errF, "a");
  return new Promise((res, rej) => {
    const p = spawn(CHROME, [
      "--headless=new", "--disable-gpu", "--hide-scrollbars",
      "--force-device-scale-factor=1", `--window-size=${ANCHO},${ALTO}`,
      "--virtual-time-budget=9000",
      // HERMÉTICA: todo host que no sea el server de esta vara muere en el resolver, al
      // instante. Sin esto, `Conectores.dc.html` sale a buscar logos afuera, el pedido se
      // queda colgado y `--virtual-time-budget` espera la red: medido, Chrome llegó a los
      // 90 s del SIGKILL con un `handshake failed` en el log. Una vara que depende de que
      // haya internet no mide la pantalla: mide la conexión.
      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
      `--screenshot=${destino}`, `http://127.0.0.1:${PUERTO}/${pantalla}`,
    ], { stdio: ["ignore", "ignore", err] });
    const reloj = setTimeout(() => { try { p.kill("SIGKILL"); } catch (_) {} }, 90000);
    p.on("close", (code) => {
      clearTimeout(reloj); try { fs.closeSync(err); } catch (_) {}
      if (!fs.existsSync(destino)) {
        const cola = fs.existsSync(errF) ? fs.readFileSync(errF, "utf8").slice(-500) : "(sin stderr)";
        return rej(new Error(`Chrome no escribió ${destino} (code ${code}): ${cola}`));
      }
      res();
    });
    p.on("error", rej);
  });
}

function aBmp(png, bmp) {
  const r = spawnSync("sips", ["-Z", String(COMPARA_ANCHO), "-s", "format", "bmp", png, "--out", bmp],
    { encoding: "utf8" });
  if (!fs.existsSync(bmp)) throw new Error(`sips falló sobre ${png}: ${r.stderr}`);
}

function leerBmp(f) {
  const b = fs.readFileSync(f);
  if (b.toString("ascii", 0, 2) !== "BM") throw new Error(`${f} no es BMP`);
  const off = b.readUInt32LE(10), w = b.readInt32LE(18), hCrudo = b.readInt32LE(22);
  const bpp = b.readUInt16LE(28), comp = b.readUInt32LE(30);
  if (bpp !== 24 || comp !== 0) throw new Error(`${f}: BMP inesperado (bpp ${bpp}, comp ${comp})`);
  return { datos: b, off, w, h: Math.abs(hCrudo), fila: Math.ceil((w * 3) / 4) * 4 };
}

/** Devuelve {pct, distintos, total, diff:Buffer|null}. `diff` pinta en rojo lo que cambió. */
function comparar(aF, bF, conDiff) {
  const A = leerBmp(aF), B = leerBmp(bF);
  if (A.w !== B.w || A.h !== B.h) return { pct: 100, distintos: -1, total: -1, diff: null,
    nota: `tamaños distintos: ${A.w}x${A.h} vs ${B.w}x${B.h}` };
  let distintos = 0;
  const total = A.w * A.h;
  const salida = conDiff ? Buffer.from(B.datos) : null;
  for (let y = 0; y < A.h; y++) {
    const ra = A.off + y * A.fila, rb = B.off + y * B.fila;
    for (let x = 0; x < A.w; x++) {
      const ia = ra + x * 3, ib = rb + x * 3;
      const d = Math.max(
        Math.abs(A.datos[ia] - B.datos[ib]),
        Math.abs(A.datos[ia + 1] - B.datos[ib + 1]),
        Math.abs(A.datos[ia + 2] - B.datos[ib + 2]));
      if (d > TOL_CANAL) {
        distintos++;
        if (salida) { salida[ib] = 0; salida[ib + 1] = 0; salida[ib + 2] = 255; }   // BGR → rojo
      }
    }
  }
  return { pct: (distintos / total) * 100, distintos, total, diff: salida };
}

/* ── LA CORRIDA ───────────────────────────────────────────────────────────────────────── */
function tick(ok) { return ok ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m"; }

const casos = [];
const saltadas = [];
for (const p of PANTALLAS) {
  if (SOLO && !p.toLowerCase().startsWith(SOLO.toLowerCase())) continue;
  // El id no puede llevar `/`: es parte de un NOMBRE DE ARCHIVO, y `workspaces/finanzas`
  // mandaba la captura a un subdirectorio que no existe. Chrome no escribía nada y la
  // pantalla salía «NO CAPTURABLE» — un rojo del instrumento, no del producto.
  const corto = p.replace(/\.dc\.html$/, "").replace(/\.html$/, "").replace(/\//g, "-");
  if (DECLARADAS_INESTABLES[corto] && !tiene("--incluir-inestables")) {
    saltadas.push(`${corto}: ${DECLARADAS_INESTABLES[corto]}`);
    continue;
  }
  for (const t of TEMAS) casos.push({ pantalla: p, tema: t, id: `${corto}.${t}` });
}
if (saltadas.length) {
  console.log("\x1b[33m~ DECLARADAS INESTABLES — NO SE MIDEN\x1b[0m (deuda abierta, fase 2):");
  for (const l of saltadas) console.log(`    · ${l}`);
  console.log("    (--incluir-inestables las mide igual, para trabajar sobre ellas)\n");
}
if (!casos.length) { console.error(`sin pantallas que casen con --pantalla=${SOLO}`); process.exit(2); }
if (!fs.existsSync(CHROME)) { console.error(`✗ no está Google Chrome en ${CHROME} — esta vara NO puede correr, y eso es rojo, no verde`); process.exit(2); }

fs.mkdirSync(BASE, { recursive: true });
fs.mkdirSync(SALIDA, { recursive: true });

const filas = [];
for (const tema of TEMAS) {
  const mios = casos.filter((c) => c.tema === tema);
  if (!mios.length) continue;
  const srv = await levantarServer(tema);
  try {
    for (const c of mios) {
     try {
      // ── ESTABILIDAD PRIMERO: dos capturas de la MISMA pantalla, sin tocar nada ───────
      // Si las dos no coinciden, esta pantalla no se puede medir HOY, y decirlo es la única
      // salida honesta: comparar contra la baseline daría un rojo que no es del rediseño.
      // Ver la nota «PANTALLAS INESTABLES» del encabezado.
      const uno = path.join(TMP, `${c.id}.1.png`);
      const actualPng = path.join(TMP, `${c.id}.png`);
      await capturarConReintento(c.pantalla, uno);
      await capturarConReintento(c.pantalla, actualPng);
      {
        const u = path.join(TMP, `${c.id}.u.bmp`), d = path.join(TMP, `${c.id}.d.bmp`);
        aBmp(uno, u); aBmp(actualPng, d);
        const est = comparar(u, d, false);
        if (est.pct > UMBRAL_PCT) {
          filas.push({ id: c.id, estado: "inestable", pct: est.pct });
          console.log(`  \x1b[33m~\x1b[0m ${c.id.padEnd(26)} INESTABLE (${est.pct.toFixed(3)}% entre dos capturas propias) — no medible`);
          continue;
        }
      }
      const basePng = path.join(BASE, `${c.id}.png`);
      if (MODO_ACTUALIZAR) {
        fs.copyFileSync(actualPng, basePng);
        filas.push({ id: c.id, estado: "baseline", pct: 0 });
        console.log(`  ${tick(true)} ${c.id.padEnd(26)} baseline escrita`);
        continue;
      }
      if (!fs.existsSync(basePng)) {
        filas.push({ id: c.id, estado: "sin-baseline", pct: 100 });
        console.log(`  ${tick(false)} ${c.id.padEnd(26)} SIN BASELINE — corré --actualizar`);
        continue;
      }
      const aB = path.join(TMP, `${c.id}.a.bmp`), bB = path.join(TMP, `${c.id}.b.bmp`);
      aBmp(basePng, aB); aBmp(actualPng, bB);
      const r = comparar(aB, bB, true);
      const ok = r.pct <= UMBRAL_PCT;
      filas.push({ id: c.id, estado: ok ? "igual" : "cambió", pct: r.pct, nota: r.nota });
      console.log(`  ${tick(ok)} ${c.id.padEnd(26)} ${r.pct.toFixed(3)}% distinto${r.nota ? " · " + r.nota : ""}`);
      if (!ok) {
        fs.copyFileSync(actualPng, path.join(SALIDA, `${c.id}.actual.png`));
        if (r.diff) {
          const dB = path.join(TMP, `${c.id}.diff.bmp`);
          fs.writeFileSync(dB, r.diff);
          spawnSync("sips", ["-s", "format", "png", dB, "--out", path.join(SALIDA, `${c.id}.diff.png`)]);
        }
      }
     } catch (e) {
      filas.push({ id: c.id, estado: "no-capturable", pct: 0, nota: String(e.message || e).slice(0, 120) });
      console.log(`  ${tick(false)} ${c.id.padEnd(26)} NO CAPTURABLE — ${String(e.message || e).slice(0, 90)}`);
     }
    }
  } finally { srv.close(); }
}

const rojas = filas.filter((f) => f.estado === "cambió" || f.estado === "sin-baseline" || f.estado === "no-capturable");
const inestables = filas.filter((f) => f.estado === "inestable");
console.log("");
if (inestables.length) {
  console.log(`\x1b[33m~ ${inestables.length}/${filas.length} pantallas NO MEDIBLES hoy\x1b[0m (dos capturas propias ya difieren): `
    + inestables.map((f) => f.id).join(", "));
  console.log("  No cuentan para el veredicto. La causa es del PRODUCTO, no de la vara — ver el encabezado.");
}
if (MODO_ACTUALIZAR) { console.log(`baseline: ${filas.length} capturas en qa/visual/baseline/`); process.exit(0); }

if (MODO_MUTANTE) {
  // LA VARA PROBADA CAYENDO. Con el `--accent` mutado a rojo puro, TODAS las pantallas que
  // usan el acento tienen que caer. Si no cae ninguna, la que está rota es la vara.
  const medibles = filas.filter((f) => f.estado !== "inestable");
  if (rojas.length < medibles.length) {
    console.log(`\x1b[31m✗ LA VARA NO ESTÁ PROBADA\x1b[0m: con --accent y --ink en rojo puro sólo cayeron `
      + `${rojas.length}/${medibles.length}. Las que quedaron verdes no ven un cambio de color de TEXTO.`);
    process.exit(1);
  }
  console.log(`\x1b[32m✓ la vara puede dar rojo\x1b[0m: ${rojas.length}/${medibles.length} cayeron con la mutación.`);
  process.exit(0);
}

if (rojas.length) {
  console.log(`\x1b[31m✗ ${rojas.length}/${filas.length} pantallas cambiaron\x1b[0m (umbral ${UMBRAL_PCT}%). Mirá qa/visual/salida/`);
  process.exit(1);
}
console.log(`\x1b[32m✓ ${filas.length}/${filas.length} pantallas iguales a la baseline\x1b[0m (umbral ${UMBRAL_PCT}%)`);
process.exit(0);
