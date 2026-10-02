#!/usr/bin/env node
/**
 * verify_picker_unico.mjs — UN SOLO PICKER EN LAS SIETE. [convergencia · 2026-08-22]
 *
 * QUÉ MIDE, Y POR QUÉ NO LO MIDE NINGUNA DE LAS DOS QUE YA ESTÁN
 * ─────────────────────────────────────────────────────────────
 *   · `qa/verify_cerebro_unico_e2e.py` mide la CADENA: puesta la fuente única, ¿los siete
 *     contestan ese cerebro? Da verde desde la tanda 1 y **no puede dar rojo por esta
 *     obra**: la obra es de CARA, y esa vara no mira ninguna pantalla.
 *   · `product/app/design/verify_selector_unico.mjs` mide el ESLABÓN del picker de la Sala:
 *     que el click escriba `preferencias-v2.default`. Tampoco puede dar rojo acá: no sabe
 *     que existe una barra de workspace.
 *
 * Ésta mide lo que falta: que el picker de la casa esté MONTADO en las seis anfitrionas,
 * que el del stack esté CERRADO por sus dos caminos (puntero y teclado), y —lo que más
 * importa— que **fuera de Aleph el stack quede intacto** (LEY 0).
 *
 * POR QUÉ SIN NAVEGADOR, y por qué no usa `qa/dom_minimo.mjs`
 * ──────────────────────────────────────────────────────────
 * La política de la casa ya está escrita y medida (`dom_minimo.mjs`): playwright no
 * resuelve en esta máquina, y una vara que no corre no es verde — es silencio. Pero
 * `dom_minimo` NO alcanza para este script: no tiene fase de captura, su
 * `window.addEventListener` es un no-op y no tiene `MutationObserver`. Su propio docstring
 * prohíbe agrandarlo «hasta que sea un navegador malo», así que acá va un doble PROPIO,
 * mínimo y declarado: los tres eventos en captura, `closest`, y un `postMessage` que se
 * anota. Nada más. Si mañana hace falta layout o foco, se levanta un navegador de verdad.
 *
 * CÓMO SE PRUEBA QUE ESTA VARA PUEDE DAR ROJO
 * ───────────────────────────────────────────
 * `node qa/verify_picker_unico.mjs --mutantes` aplica seis mutaciones al código real (no a
 * una copia teórica) y exige que **cada una** ponga la vara en rojo. Una corrida previa en
 * verde no prueba nada; un mutante que sobrevive sí prueba que el testigo está ciego.
 *
 * CORRE:  node qa/verify_picker_unico.mjs
 *         node qa/verify_picker_unico.mjs --mutantes
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CASA = path.join(RAIZ, "product/app/design/workspaces");
const WS = ["ciencia", "diseno", "educacion", "finanzas", "legal", "oficina"];

/* Los stacks que YA renunciaron a su picker. Crece de a uno, y crece acá: si alguien
 * agrega el script a un stack y se olvida de esta lista, la vara no lo mide — así que la
 * lista es parte del entregable, no un detalle. */
const STACKS_TOCADOS = [
  /* ⚠️ DOS RUTAS POR STACK, Y NO ES REDUNDANCIA. La FUENTE (`public/`, `index.html`,
   * `layout.tsx`) es lo que sobrevive a un rebuild del stack; el ARTEFACTO (`dist/`,
   * `standalone/`) es lo que viaja HOY en la `.app` — y está gitignoreado, así que un
   * `npm run build` se lleva puesto cualquier archivo que sólo viva ahí. Se miden las dos y
   * se exige que sean el mismo byte. */
  {
    ws: "oficina",
    fuente: "third_party/openwork/apps/app",
    dist: "third_party/openwork/apps/app/dist",
    enDist: "",
    declara: "third_party/openwork/apps/app/index.html",
  },
  {
    ws: "educacion",
    // Next no tiene `index.html`: el `<head>` lo emite `app/layout.tsx`, al lado del
    // `ThemeScript` de Aleph que ya vivía ahí. Su `public/` lo copia el build al standalone.
    fuente: "third_party/deeptutor/web",
    dist: "third_party/deeptutor/web/.next/standalone",
    enDist: "public/",
    declara: "third_party/deeptutor/web/app/layout.tsx",
  },
  {
    ws: "legal",
    // Su `ModelSelector` elige AGENTE, no modelo: no hay nada que reemplazar y el chip va
    // AL LADO, en su fila de herramientas. No se le toca un solo control.
    fuente: "third_party/dochaus/apps/web",
    dist: "third_party/dochaus/apps/web/dist",
    enDist: "",
    declara: "third_party/dochaus/apps/web/index.html",
  },
  {
    ws: "ciencia",
    // Su cara va EMBEBIDA en un binario compilado de 122 MB: no hay artefacto que abrir.
    // Se mide la FUENTE y que el binario contenga el nombre del script — es lo único
    // que prueba, sin recompilar, que la cara horneada es la que lleva el chip.
    fuente: "third_party/openscience/frontend/workspace",
    binario: "third_party/openscience/backend/cli/dist/@synsci/openscience-darwin-arm64/bin/openscience",
    declara: "third_party/openscience/frontend/workspace/index.html",
  },
  {
    ws: "diseno",
    // Su lienzo es un Electron y su artefacto es un ZIP de 101 MB, no un dir: comparar
    // byte a byte adentro costaría descomprimirlo en cada corrida. Se mide la FUENTE —que
    // es lo que el build hornea— y que el zip exista y esté ENTERO. `zipEntero` no es
    // decorado: un `ditto -c -k` copiado a mitad de escritura produce un zip truncado que
    // el pack no puede expandir, y Diseño queda caído con «El taller no está corriendo».
    // Pasó, y costó una ronda entera de diagnóstico contra un stack que no existía.
    fuente: "third_party/codesign/apps/desktop/src/renderer",
    zip: "third_party/codesign/apps/desktop/release/aleph-diseno-mac-arm64.zip",
    declara: "third_party/codesign/apps/desktop/src/renderer/index.html",
  },
  {
    ws: "finanzas",
    // Muestra el modelo y no deja elegirlo (un `<span>` sin click). Se esconde y el chip
    // ocupa su lugar. ⚠️ Y sirve con `script-src 'self'`: por eso el núcleo viaja adentro.
    fuente: "third_party/vibetrading/frontend",
    dist: "third_party/vibetrading/frontend/dist",
    enDist: "",
    declara: "third_party/vibetrading/frontend/index.html",
  },
];

/** El CÓDIGO, sin los comentarios.
 *
 * ⚠️ NO ES COSMÉTICA. La primera versión de esta vara grepeaba el archivo entero y dio DOS
 * rojas falsas: `ev.origin` y «Cerebro de Aleph» aparecen en los COMENTARIOS —justamente
 * porque el comentario explica por qué NO se usan— y la vara los leyó como si fueran
 * código. Un testigo que confunde la prosa con la instrucción no mide el archivo: mide su
 * documentación, y se pone rojo cuando alguien documenta mejor. Se miden los HECHOS. */
const soloCodigo = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const fails = [];
const ok = (c, label, extra = "") => {
  console.log(`${c ? "  ✓" : "  ✗"} ${label}${!c && extra ? " — " + extra : ""}`);
  if (!c) fails.push(label);
};

/* ══ EL DOBLE: el DOM más chico que alcanza para correr ESTE script ═══════════════════ */
function fabricarMundo({ conPadre, referrer = "http://127.0.0.1:8330/workspaces/oficina.html" }) {
  const oyentes = { captura: {}, burbuja: {} };
  const posteos = [];
  const nodos = [];

  function nodo(attrs = {}, padre = null) {
    const n = {
      attrs, padre, tagName: "BUTTON", dataset: {}, style: {}, children: [],
      getAttribute: (k) => (k in attrs ? attrs[k] : null),
      setAttribute: (k, v) => { attrs[k] = String(v); },
      querySelector: () => null,
      closest(sel) {
        /* ⚠️ LISTA, NO UNO. El script pasó a enganchar por VARIOS `aria-label` (uno por
         * stack) unidos con coma, y este doble sólo parseaba un selector: devolvía null y la
         * vara daba rojo por su propia carencia, no por el código. Un doble que se queda
         * atrás del código que mide produce rojas que no hablan de nada. */
        const partes = String(sel).split(",").map((x) => x.trim()).filter(Boolean);
        for (const parte of partes) {
          const m = /^\[([^=]+)="([^"]*)"\]$/.exec(parte);
          if (!m) continue;
          let p = this;
          while (p) { if (p.getAttribute(m[1]) === m[2]) return p; p = p.padre; }
        }
        return null;
      },
    };
    nodos.push(n);
    return n;
  }

  const doc = {
    readyState: "complete",
    /* ⚠️ EL `referrer` NO ES DECORADO. El script resuelve el origen de la casa desde acá y
     * se va si no lo consigue. La primera versión de esta vara no lo ponía: el script salía
     * en esa línea, no enganchaba nada, y el testigo de LEY 0 daba VERDE **por el motivo
     * equivocado** mientras los dos del bloqueo daban rojo. Un doble incompleto no produce
     * un rojo honesto: produce una conclusión falsa en las dos direcciones. */
    referrer,
    /* El script carga el núcleo con un `<script src>` y la hoja con un `<link>`. El doble no
     * baja nada: fabrica el nodo, deja que se lo «agreguen» y dispara su `onload` en el
     * próximo tick con el núcleo ya puesto en `window`. Así se prueba el CAMINO real de
     * arranque —que es donde vive `arrancar()`— sin pedirle red a una vara. */
    createElement(tag) {
      const n = { tagName: String(tag).toUpperCase(), style: {}, setAttribute() {}, remove() {},
                  appendChild() {}, addEventListener() {}, get isConnected() { return true; } };
      Object.defineProperty(n, "src", {
        set(v) { this._src = v; setTimeout(() => { if (this.onload) this.onload(); }, 0); },
        get() { return this._src; },
      });
      return n;
    },
    head: { appendChild() {} },
    body: { appendChild(n) { n.__enBody = true; } },
    documentElement: nodo(),
    addEventListener(tipo, fn, captura) {
      const donde = captura ? oyentes.captura : oyentes.burbuja;
      (donde[tipo] = donde[tipo] || []).push(fn);
    },
    querySelector(sel) {
      for (const parte of String(sel).split(",").map((x) => x.trim()).filter(Boolean)) {
        const m = /^\[([^=]+)="([^"]*)"\]$/.exec(parte);
        if (!m) continue;
        const hit = nodos.find((n) => n.getAttribute(m[1]) === m[2]);
        if (hit) return hit;
      }
      return null;
    },
  };

  const padre = { postMessage: (d) => posteos.push(d) };
  const win = {
    document: doc,
    addEventListener() {},
    // `conPadre:false` ⇒ `window.parent === window`, que es EXACTAMENTE el estado de un
    // stack corrido suelto. Es el testigo de LEY 0 y no se simula con un flag: se arma la
    // topología real.
    get parent() { return conPadre ? padre : win; },
  };

  return {
    win, doc, posteos, nodo,
    /** Dispara un evento como lo haría el navegador: primero la CAPTURA del documento. */
    disparar(tipo, ev) {
      const corridos = [];
      let cortado = false;
      ev.preventDefault = () => { ev.__prevenido = true; };
      ev.stopPropagation = () => { cortado = true; };
      ev.stopImmediatePropagation = () => { cortado = true; ev.__inmediato = true; };
      for (const fn of oyentes.captura[tipo] || []) { fn(ev); corridos.push(fn); if (cortado) break; }
      return { cortado, prevenido: !!ev.__prevenido, corridos: corridos.length };
    },
    hayOyentes: () => Object.keys(oyentes.captura).length + Object.keys(oyentes.burbuja).length,
  };
}

function correrScript(codigo, mundo) {
  const MutationObserver = function () { return { observe() {} }; };
  // `new Function` y no `import`: el script del stack es un `<script>` clásico que espera
  // `window`/`document` globales, no un módulo. Se le dan los suyos y ninguno más.
  new Function("window", "document", "MutationObserver", codigo)(mundo.win, mundo.doc, MutationObserver);
}

/* ══ 1 · LA CASA: el picker montado en las seis ═══════════════════════════════════════ */
function medirCasa() {
  console.log("\n── el picker de la casa, en las seis anfitrionas ──");
  const modulo = path.join(CASA, "modelo-del-espacio.js");
  ok(fs.existsSync(modulo), "existe `workspaces/modelo-del-espacio.js`");
  const src = soloCodigo(fs.readFileSync(modulo, "utf8"));

  for (const ws of WS) {
    const html = fs.readFileSync(path.join(CASA, `${ws}.html`), "utf8");
    ok(html.includes('src="./modelo-del-espacio.js"'), `${ws.padEnd(10)} declara el módulo`);
    ok(html.includes(`AlephModeloDelEspacio.montar("${ws}")`),
       `${ws.padEnd(10)} lo monta con SU propio ws`,
       "un ws cruzado haría que el panel hable del espacio equivocado");
  }

  // ── EL COMPONENTE ES UNO SOLO, Y VIVE EN `ui/model-chip.core.js` ──────────────────
  const core = soloCodigo(fs.readFileSync(path.join(RAIZ, "product/app/design/ui/model-chip.core.js"), "utf8"));
  ok(/window\.AlephModelChip\s*=/.test(core), "el núcleo del chip se publica en `window.AlephModelChip`");
  // ⚠️ EL TEMA LO DICE EL HOST, y el chip lo estampa en una marca PROPIA. Sin esto salió
  // oscuro sobre la página clara de Educación: cada stack usa su convención (`html.dark` de
  // Tailwind, `data-theme` de la casa) y ningún selector nuestro las cubre a todas.
  ok(/raiz\.dataset\.amcTheme\s*=\s*opts\.tema/.test(core),
     "el chip estampa el tema que el host le dice");
  ok(/temaPorLuminancia/.test(core),
     "y hay caída por LUMINANCIA del fondo, no por adivinar su convención de clases");
  ok(/sv-model-menu-abajo/.test(core),
     "el menú se voltea cuando no entra hacia arriba",
     "en Legal el composer está a media pantalla y el menú se salía por el techo");
  ok(!/\bexport\b/.test(core), "y NO es un módulo ESM",
     "un `import` cross-origin pide CORS y el sidecar no lo manda: el stack no podría cargarlo");
  const cascara = soloCodigo(fs.readFileSync(
    path.join(RAIZ, "product/app/design/sala-v2/ui/model-chip.js"), "utf8"));
  ok(/window\.AlephModelChip/.test(cascara) && /montarChip\(/.test(cascara),
     "la Sala consume ESE núcleo (no tiene su propio chip)",
     "si la Sala vuelve a pintar sus filas, hay dos versiones otra vez");
  ok(!/sv-model-row/.test(cascara), "la cáscara de React NO pinta filas");
  const csssala = fs.readFileSync(path.join(RAIZ, "product/app/design/sala-v2/sala-v2.css"), "utf8");
  ok(!/^\.sv-model-row\b/m.test(csssala), "y tampoco quedó una copia de sus estilos en la Sala");

  /* ── LA SALA TAMBIÉN REINTENTA SU CATÁLOGO ────────────────────────────────────────
   * Medido el 2026-08-22 en la primera apertura de la `.app` recién instalada: el chip
   * decía «Elegir modelo», sin una sola opción, y con un F5 aparecía «Grok». La Sala pedía
   * su catálogo UNA vez al montar; si el sidecar todavía no había detectado los CLIs,
   * recibía la lista vacía y no volvía a preguntar. Es la MISMA falla que ya se arregló del
   * otro lado del borde, y le faltaba al lado de acá. */
  const sala = soloCodigo(fs.readFileSync(
    path.join(RAIZ, "product/app/design/sala-v2/sala-v2.js"), "utf8"));
  ok(/ESPERAS\s*=\s*\[/.test(sala) && /recargarChoices\(\)\.then\(\(n\)/.test(sala),
     "la Sala reintenta su catálogo hasta que llega",
     "sin esto el chip queda vacío en el arranque en frío — la primera pantalla al abrir Aleph");
  ok(/intento >= ESPERAS\.length/.test(sala),
     "y el reintento tiene TOPE",
     "cero modelos es un estado legítimo: reintentar para siempre lo volvería un latido eterno");

  // ── LA HOJA NO PUEDE LEER TOKENS DEL DOCUMENTO QUE LA ALOJA ──────────────────────
  const csscore = fs.readFileSync(path.join(RAIZ, "product/app/design/ui/model-chip.core.css"), "utf8");
  const ajenos = (soloCodigo(csscore).match(/var\(--(?!amc-)[a-z0-9-]+/g) || []);
  ok(ajenos.length === 0,
     "el chip usa SU paleta `--amc-*`, ningún token del anfitrión",
     `leería del host: ${[...new Set(ajenos)].join(", ")} — shadcn define \`--muted\` como FONDO y dejó el rótulo invisible`);

  // ── EL PUENTE DE DATOS, Y SU CANDADO ─────────────────────────────────────────────
  ok(/aleph:\s*"modelo-catalogo"/.test(src), "la casa le baja el catálogo al stack");
  ok(/ofrecidas\.some\(/.test(src),
     "y valida lo que sube contra lo que ELLA ofreció",
     "sin esto un stack podría pedir un modelo que nunca le mostramos");
  ok(/ev\.source\s*!==\s*frame\.contentWindow/.test(src),
     "candado 1 · el emisor tiene que ser el contentWindow de NUESTRO frame");
  ok(!/ev\.origin/.test(src), "candado 1b · no se conforma con `ev.origin`");
  ok(!/d\.ws\b/.test(src), "candado 2 · el `ws` que mande el stack se ignora");
  ok(!/todos.*true/.test(src.slice(src.indexOf("function bajar"), src.indexOf("function bajar") + 900)),
     "al chip le van SÓLO las usables, no el catálogo de configuración",
     "ofrecer una API sin llave en el composer es el verde falso otra vez");
}

/* ══ 2 · EL STACK: el picker cerrado, y LEY 0 ═════════════════════════════════════════ */
function medirStack(entrada) {
  const { ws, fuente, dist } = entrada;
  console.log(`\n── ${ws}: el picker del stack renunció ──`);
  /* ⚠️ SE MIDE LA FUENTE Y SE COMPARA CON EL ARTEFACTO — en ese orden, y lo enseñó un
   * mutante. La primera versión leía y EJECUTABA la copia de `dist/`; como los mutantes
   * pinchan la fuente (`public/`), TRES de ellos sobrevivieron: la vara estaba mirando otro
   * archivo que el que se estaba rompiendo. Ahora corre la fuente —que es la que sobrevive a
   * un `pnpm run build`— y exige que el artefacto lleve exactamente esos bytes. */
  const js = path.join(RAIZ, fuente, "public/aleph-picker-unico.js");
  const html = path.join(RAIZ, entrada.declara);
  ok(fs.existsSync(js), "la FUENTE lleva el script (la que sobrevive a un rebuild del stack)");

  if (entrada.binario) {
    const bin = path.join(RAIZ, entrada.binario);
    ok(fs.existsSync(bin), "su binario compilado está");
    let dentro = false;
    if (fs.existsSync(bin)) {
      try {
        execFileSync("/bin/sh", ["-c",
          `strings ${JSON.stringify(bin)} | grep -q aleph-picker-unico`], { stdio: "ignore" });
        dentro = true;
      } catch (e) { dentro = false; }
    }
    ok(dentro, "y la cara horneada adentro DECLARA el script",
       "sin esto el binario es de antes del chip y el workspace no lo lleva");
    for (const nombre of ["aleph-model-chip.core.js", "aleph-model-chip.core.css"]) {
      const canonico = path.join(RAIZ, "product/app/design/ui",
                                 nombre.replace("aleph-model-chip.core", "model-chip.core"));
      const enFuente = path.join(RAIZ, fuente, "public", nombre);
      ok(fs.existsSync(enFuente) &&
         fs.readFileSync(enFuente, "utf8") === fs.readFileSync(canonico, "utf8"),
         `${nombre} viaja con el stack y es idéntico al de la casa`);
    }
    const canonBin = path.join(RAIZ, STACKS_TOCADOS[0].fuente, "public/aleph-picker-unico.js");
    ok(fs.readFileSync(js, "utf8") === fs.readFileSync(canonBin, "utf8"),
       "y el script es el mismo que el de los otros stacks");
    ok(fs.readFileSync(html, "utf8").includes("aleph-picker-unico.js"),
       `${path.basename(entrada.declara)} lo declara`);
    return;
  }

  if (entrada.zip) {
    const z = path.join(RAIZ, entrada.zip);
    ok(fs.existsSync(z), "su artefacto (el zip del Electron) está");
    let entero = false;
    try {
      execFileSync("/usr/bin/unzip", ["-t", z], { stdio: "ignore" });
      entero = true;
    } catch (e) { entero = false; }
    ok(entero, "y el zip está ENTERO",
       "un zip copiado a mitad de escritura deja el workspace caído, sin decir por qué");
    for (const nombre of ["aleph-model-chip.core.js", "aleph-model-chip.core.css"]) {
      const canonico = path.join(RAIZ, "product/app/design/ui",
                                 nombre.replace("aleph-model-chip.core", "model-chip.core"));
      const enFuente = path.join(RAIZ, fuente, "public", nombre);
      ok(fs.existsSync(enFuente) &&
         fs.readFileSync(enFuente, "utf8") === fs.readFileSync(canonico, "utf8"),
         `${nombre} viaja con el stack y es idéntico al de la casa`);
    }
    const canonZip = path.join(RAIZ, STACKS_TOCADOS[0].fuente, "public/aleph-picker-unico.js");
    ok(fs.readFileSync(js, "utf8") === fs.readFileSync(canonZip, "utf8"),
       "y el script es el mismo que el de los otros stacks");
    ok(fs.readFileSync(html, "utf8").includes("aleph-picker-unico.js"),
       `${path.basename(entrada.declara)} lo declara`);
    return;
  }

  const enDist = path.join(RAIZ, dist, entrada.enDist + "aleph-picker-unico.js");
  ok(fs.existsSync(enDist), `el artefacto que viaja (${dist}) también`);
  ok(fs.existsSync(js) && fs.existsSync(enDist) &&
     fs.readFileSync(js, "utf8") === fs.readFileSync(enDist, "utf8"),
     "y son EL MISMO archivo, byte a byte",
     "si divergen, lo que se prueba no es lo que corre");
  // ⚠️ Y EL MISMO QUE EL DE LOS OTROS STACKS. Un archivo por stack sería la partición que
  // esta obra cerró, multiplicada por seis: el enganche de uno se arreglaría y el de los
  // otros no. La lista `SELECTORES` es lo que los hace servir a todos.
  const canon = path.join(RAIZ, STACKS_TOCADOS[0].fuente, "public/aleph-picker-unico.js");
  ok(fs.readFileSync(js, "utf8") === fs.readFileSync(canon, "utf8"),
     "y el mismo que el de los otros stacks",
     "el script es UNO; lo que cambia entre stacks es sólo la tabla CASOS, que está adentro");

  /* ⚠️ EL NÚCLEO VIAJA ADENTRO DE CADA STACK, y la razón es de seguridad ajena: Finanzas
   * sirve `Content-Security-Policy: script-src 'self'` y bloqueó cargarlo desde la casa. Su
   * CSP es SUYO — aflojarlo para meterle nuestra cara sería bajarle una defensa real, o sea
   * lo contrario de la LEY 0. Copiarlo cuesta 12 KB; que las copias diverjan cuesta un bug
   * que sólo aparece en un stack. */
  const nucleoCanon = path.join(RAIZ, "product/app/design/ui/model-chip.core.js");
  const hojaCanon = path.join(RAIZ, "product/app/design/ui/model-chip.core.css");
  for (const [nombre, canonico] of [["aleph-model-chip.core.js", nucleoCanon],
                                    ["aleph-model-chip.core.css", hojaCanon]]) {
    const enFuente = path.join(RAIZ, fuente, "public", nombre);
    const enArtefacto = path.join(RAIZ, dist, entrada.enDist + nombre);
    ok(fs.existsSync(enFuente) && fs.existsSync(enArtefacto) &&
       fs.readFileSync(enFuente, "utf8") === fs.readFileSync(canonico, "utf8") &&
       fs.readFileSync(enArtefacto, "utf8") === fs.readFileSync(canonico, "utf8"),
       `${nombre} viaja con el stack y es idéntico al de la casa`,
       "el CSP del stack no deja cargarlo de afuera, y una copia que se desincroniza es un bug por stack");
  }
  if (!fs.existsSync(js)) return;
  const src = soloCodigo(fs.readFileSync(js, "utf8"));
  ok(fs.readFileSync(html, "utf8").includes("aleph-picker-unico.js"),
     `${path.basename(entrada.declara)} lo declara`,
     "sin esta línea el archivo viaja y no corre — verde mudo");

  // ENGANCHE POR ATRIBUTO SEMÁNTICO, NO POR COPY.
  ok(/aria-label="Change model"/.test(src) && /aria-label="Select model"/.test(src),
     "engancha por `aria-label` (los de los dos stacks), que es semántico");
  ok(!/Cerebro de Aleph/.test(src), "NO engancha por el copy del rótulo",
     "el copy lo escribimos nosotros (`cerebro_label`) y cambia con el idioma");

  // ── LEY 0, EJECUTADA: suelto, el script no engancha NADA ──────────────────────────
  const entero = fs.readFileSync(js, "utf8");   // se EJECUTA el archivo real, no el podado
  const suelto = fabricarMundo({ conPadre: false });
  correrScript(entero, suelto);
  ok(suelto.hayOyentes() === 0, "LEY 0 · corrido FUERA de Aleph no engancha un solo oyente",
     `enganchó ${suelto.hayOyentes()}`);
  ok(suelto.posteos.length === 0, "LEY 0 · y no le postea nada a nadie");

  /* Y con padre, pero sin que nadie conteste el saludo —que es lo que pasa si esto queda
   * embebido en una página que no es Aleph—: engancha y saluda, pero NO TOCA NADA. Es la
   * guarda `catalogoOk`, y es más fuerte que la anterior por `document.referrer`: no
   * depende de un dato del navegador que un stack puede no mandar (Electron no lo manda, y
   * eso dejó al script en un no-op mudo en Diseño). */
  const remoto = fabricarMundo({ conPadre: true, referrer: "https://ejemplo.com/lo-que-sea" });
  correrScript(entero, remoto);
  const ctrlRemoto = remoto.nodo({ "aria-label": "Change model" });
  remoto.disparar("pointerdown", { target: ctrlRemoto });
  ok(ctrlRemoto.style.visibility !== "hidden",
     "sin respuesta de la casa, el control del stack NO se esconde",
     "LEY 0 por construcción: si nadie contesta, el workspace queda como estaba");

  // ── ADENTRO DE ALEPH: el control del stack queda cerrado, por los DOS caminos ─────
  const dentro = fabricarMundo({ conPadre: true });
  correrScript(entero, dentro);

  const contenedor = dentro.nodo({ "aria-label": "Change model" });
  const etiqueta = dentro.nodo({}, contenedor);        // el <span> de adentro del botón
  const puntero = dentro.disparar("pointerdown", { target: etiqueta });
  ok(puntero.prevenido && puntero.cortado, "puntero · el click al picker del stack se corta");
  const teclado = dentro.disparar("keydown", { metaKey: true, altKey: true, key: "/" });
  ok(teclado.prevenido && teclado.cortado,
     "teclado · el atajo `Meta+Alt+/` del propio control también se corta",
     "un control bloqueado sólo para el mouse sigue abierto con su atajo");

  // ── LO QUE **NO** SE TOCA: el picker de agente ────────────────────────────────────
  const otro = dentro.nodo({ "aria-label": "Default agent" });
  const ajeno = dentro.disparar("pointerdown", { target: otro });
  ok(!ajeno.prevenido, "el picker de AGENTE del stack sigue siendo suyo, intacto",
     "Aleph se lleva el cerebro, no la elección de agente");

  // ── EL CHIP SE MONTA FUERA DEL ÁRBOL DE REACT ────────────────────────────────────
  ok(/document\.body\.appendChild\(contenedor\)/.test(src),
     "el chip cuelga del `<body>`, no del composer del stack",
     "adentro, React reemplaza el subárbol en cada re-render y lo dejó sin pintar nunca");
  ok(/visibility\s*=\s*"hidden"/.test(src) && !/display\s*=\s*"none".*SEL/.test(src),
     "el control del stack se apaga con `visibility`, que CONSERVA la caja",
     "con `display:none` no hay rect al que anclar el chip");
  ok(/setInterval\(latido/.test(src),
     "un LATIDO propio garantiza la reparación; el observer sólo la adelanta",
     "medido en Legal: colgado del observer, `_pintar` corrió 3 veces en 20 s y el chip nunca apareció");
  ok(/reintentarSiVacio/.test(src),
     "y el saludo se repite hasta que el catálogo llega",
     "medido en Finanzas: el chip montado, vivo y con CERO opciones, en silencio");
  ok(/NUCLEO_JS\s*=\s*"\/aleph-model-chip\.core\.js"/.test(src),
     "el núcleo se carga del PROPIO origen del stack (su CSP no se toca)");
  ok(/rendido\s*=\s*true/.test(src) && /reparaciones\.length > TOPE/.test(src),
     "el reparador tiene tope: si el stack le gana la pulseada, se rinde en vez de colgar",
     "sin esto React repone el style, el observer repara, y la pestaña muere");
  const tabla = src.slice(src.indexOf("var CASOS"), src.indexOf("var caso ="));
  for (const [quien, marca] of [["Oficina", 'aria-label="Change model"'],
                                ["Educación", 'aria-label="Select model"'],
                                ["Finanzas", "text-foreground[title]"],
                                ["Ciencia", "data-model-settings-trigger-style"],
                                ["Diseño", 'data-aleph-modelo="rotulo"'],
                                ["Legal", ".composer-tools"]]) {
    ok(tabla.includes(marca), `la tabla CASOS cubre a ${quien}`);
  }
  ok(/modo:\s*"allado"/.test(tabla),
     "y hay modo «al lado» para el stack que no tiene nada que reemplazar",
     "que no haya qué reemplazar lo hace más fácil, no innecesario: el chip va en las siete");
  ok(/c\.modo === "picker"/.test(src),
     "sólo se BLOQUEA lo que es un picker ajeno",
     "bloquear la fila de herramientas de Legal le rompería sus propios controles");
  ok(/if \(!b\) \{ contenedor\.style\.display = "none"/.test(src),
     "sin ancla el chip se esconde",
     "si no, queda flotando sobre los esqueletos de carga del stack");
  ok(/if \(!catalogoOk\) return;/.test(src),
     "no se toca NADA del stack hasta que la casa contestó con su catálogo",
     "la guarda por `document.referrer` fallaba en Diseño —Electron no lo manda— y dejaba el script en un no-op mudo");
}

/* ══ 3 · el sello «Default», que no puede quedar en dos filas ═════════════════════════ */
function medirSello() {
  console.log("\n── el sello Default vive en UNA fila ──");
  const src = fs.readFileSync(path.join(RAIZ, "product/app/design/brain-status.js"), "utf8");
  const bloque = soloCodigo(src.slice(src.indexOf("async function selectorPersist")));
  ok(/row\["default"\]\s*=\s*row\.slug === modelo\.slug/.test(bloque),
     "`selectorPersist` parcha el flag POR FILA, no sólo la cabecera",
     "sin esto quedan DOS filas selladas Default hasta un F5 — visto en pantalla");
}

/* ══ los mutantes ════════════════════════════════════════════════════════════════════ */
const MUTANTES = [
  { f: path.join(CASA, "ciencia.html"),
    de: 'AlephModeloDelEspacio.montar("ciencia")', a: 'AlephModeloDelEspacio.montar("legal")',
    por: "montar una anfitriona con el ws de otra" },
  { f: path.join(CASA, "modelo-del-espacio.js"),
    de: "ev.source !== frame.contentWindow", a: "!ev.origin",
    por: "aflojar el candado del emisor a un `ev.origin`" },
  { f: path.join(CASA, "modelo-del-espacio.js"),
    de: "if (!ofrecidas.some(function (m) { return m.selection_ref === ref; })) return;",
    a: "if (false) return;",
    por: "aceptar un modelo que la casa nunca le ofreció al stack" },
  { f: path.join(RAIZ, "product/app/design/sala-v2/ui/model-chip.js"),
    de: "montarChip(host.current", a: "noMontarChip(host.current",
    por: "que la Sala deje de consumir el núcleo compartido" },
  { f: path.join(RAIZ, "product/app/design/ui/model-chip.core.css"),
    de: "color: var(--amc-muted); font: inherit; font-size: 11.5px;",
    a: "color: var(--muted, #A0A0A6); font: inherit; font-size: 11.5px;",
    por: "volver a leer un token del anfitrión (el rótulo invisible de shadcn)" },
  { f: path.join(RAIZ, "third_party/openwork/apps/app/public/aleph-picker-unico.js"),
    de: "if (window.parent === window) return;", a: "if (false) return;",
    por: "sacar la guarda de LEY 0" },
  { f: path.join(RAIZ, "third_party/openwork/apps/app/public/aleph-picker-unico.js"),
    de: "    if (!catalogoOk) return;", a: "    void 0;",
    por: "tocar el stack antes de que la casa haya contestado" },
  { f: path.join(RAIZ, "third_party/openwork/apps/app/public/aleph-picker-unico.js"),
    de: '"pointerdown", "mousedown", "click", "keydown"', a: '"pointerdown", "mousedown", "click"',
    por: "dejar el atajo de teclado del picker sin bloquear" },
  { f: path.join(RAIZ, "third_party/openwork/apps/app/public/aleph-picker-unico.js"),
    de: "document.body.appendChild(contenedor);", a: "document.documentElement.appendChild(contenedor);",
    por: "montar el chip en otro lado que el body" },
  { f: path.join(RAIZ, "third_party/openwork/apps/app/public/aleph-picker-unico.js"),
    de: '{ sel: \'[aria-label="Change model"]\', modo: "picker" },', a: "",
    por: "sacar a Oficina de la tabla de casos" },
  { f: path.join(RAIZ, "product/app/design/sala-v2/sala-v2.js"),
    de: "const ESPERAS = [700, 1000, 1500, 2500, 4000, 6000, 8000, 10000];",
    a: "const ESPERAS_ = [];",
    por: "sacarle a la Sala el reintento del catálogo (chip vacío en el arranque en frío)" },
  { f: path.join(RAIZ, "product/app/design/sala-v2/sala-v2.js"),
    de: "if (!vivo || n > 0 || intento >= ESPERAS.length) return;",
    a: "if (!vivo || n > 0) return;",
    por: "dejar el reintento de la Sala SIN tope" },
  { f: path.join(RAIZ, "product/app/design/ui/model-chip.core.js"),
    de: 'if (opts.tema === "light" || opts.tema === "dark") raiz.dataset.amcTheme = opts.tema;',
    a: "void 0;",
    por: "que el chip deje de honrar el tema que el host le dice (salió oscuro sobre claro)" },
  { f: path.join(RAIZ, "third_party/openwork/apps/app/public/aleph-picker-unico.js"),
    de: 'var NUCLEO_JS  = "/aleph-model-chip.core.js";',
    a: 'var NUCLEO_JS  = "http://127.0.0.1:8330/ui/model-chip.core.js";',
    por: "volver a cargar el núcleo de afuera (lo bloquea el CSP de Finanzas)" },
  { f: path.join(RAIZ, "third_party/openwork/apps/app/public/aleph-picker-unico.js"),
    de: "    reintentarSiVacio();", a: "    void 0;",
    por: "dejar el saludo del catálogo sin reintento (el chip queda vivo y vacío)" },
  { f: path.join(RAIZ, "third_party/openwork/apps/app/public/aleph-picker-unico.js"),
    de: '{ sel: ".composer-tools", modo: "allado" },', a: "",
    por: "sacar a Legal de la tabla (el chip dejaría de estar en las siete)" },
  { f: path.join(RAIZ, "third_party/openwork/apps/app/public/aleph-picker-unico.js"),
    de: '{ sel: \'[data-aleph-modelo="rotulo"]\', modo: "rotulo" },', a: "",
    por: "sacar a Diseño de la tabla" },
  { f: path.join(RAIZ, "third_party/openwork/apps/app/public/aleph-picker-unico.js"),
    de: '{ sel: "[data-model-settings-trigger-style]", modo: "picker" },', a: "",
    por: "sacar a Ciencia de la tabla (era la queja original del dueño)" },
];

function medirTodo() {
  fails.length = 0;
  medirCasa();
  for (const s of STACKS_TOCADOS) medirStack(s);
  medirSello();
  return fails.length;
}

if (process.argv.includes("--mutantes")) {
  console.log("── MUTANTES: cada uno tiene que poner la vara en ROJO ──");
  const silencio = console.log;
  let sobrevivientes = 0;
  for (const m of MUTANTES) {
    const orig = fs.readFileSync(m.f, "utf8");
    if (!orig.includes(m.de)) {
      silencio(`  ✗ mutante no aplicable (el ancla no está): ${m.por}`);
      sobrevivientes++;
      continue;
    }
    fs.writeFileSync(m.f, orig.replace(m.de, m.a));
    console.log = () => {};
    let rojos = 0;
    try { rojos = medirTodo(); } finally {
      console.log = silencio;
      fs.writeFileSync(m.f, orig);
    }
    const murio = rojos > 0;
    silencio(`  ${murio ? "✓" : "✗"} ${m.por} → ${murio ? `${rojos} roja(s)` : "SOBREVIVIÓ"}`);
    if (!murio) sobrevivientes++;
  }
  silencio(sobrevivientes === 0
    ? "\n✓ los seis mutantes murieron: la vara puede dar rojo"
    : `\n✗ ${sobrevivientes} mutante(s) sobrevivieron: la vara está ciega ahí`);
  process.exit(sobrevivientes === 0 ? 0 : 1);
}

const rojas = medirTodo();
console.log(rojas === 0 ? "\n✓ un solo picker: todo verde" : `\n✗ ${rojas} roja(s)`);
process.exit(rojas === 0 ? 0 : 1);
