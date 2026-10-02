/* verify_espacios_modulo_corre.mjs — ¿EL MÓDULO DEL FILTRO POR ESPACIO **CORRE**?
 *
 * [convergencia · superficie 1]
 *
 * LA PREGUNTA, EN UNA LÍNEA: `product/app/design/espacios.js` —la fuente de datos del filtro
 * por espacio del Historial y de la Biblioteca— ¿devuelve los hilos, o se cae?
 *
 * POR QUÉ EXISTE. `memoriaDeLosSeis` usaba `ORDEN_ETIQUETA` en su PRIMERA línea y el import
 * del módulo no lo traía: `import { GENERAL, etiqueta, espacios }`. Resultado, medido en el
 * navegador contra el backend real:
 *
 *     ReferenceError: ORDEN_ETIQUETA is not defined   (espacios.js:59)
 *
 * Y con ella se caían las TRES funciones públicas, porque `hilosDeEspacio` y `obraDeEspacio`
 * la llaman. O sea que el filtro por espacio no filtraba mal: **no corría**. El Historial
 * mostraba «Todavía no hay sesiones» con seis hilos en la base.
 *
 * POR QUÉ NINGUNA VARA LO VEÍA, y por qué ésta es `.mjs` y no `.py`. Las varas de la casa son
 * de Python y miden el backend; ninguna EJECUTA el módulo de la pantalla, y un import que
 * falta no se ve leyendo el archivo —`ORDEN_ETIQUETA` está escrito ahí, sólo que sin
 * declarar—. Sólo se ve corriéndolo. Es la regla sellada de «el censo estático no alcanza»
 * y la de «el verde no prueba la cara», del mismo lado: acá se ejecuta el módulo REAL, con
 * `fetch` stubeado, sin navegador y sin backend.
 *
 * CÓMO SE PRUEBA CAYENDO:
 *     ALEPH_VARA_ROMPER=import   se le esconde `ORDEN_ETIQUETA` al módulo de la tabla → rojo
 *
 *     node qa/verify_espacios_modulo_corre.mjs
 *       0 → el módulo corre y devuelve los hilos con su espacio
 *       1 → se cae o devuelve de menos
 *       2 → no se pudo medir (NO cuenta como verde)
 */
import { pathToFileURL } from "node:url";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const DISENO = path.join(ROOT, "product", "app", "design");
const ROMPER = (process.env.ALEPH_VARA_ROMPER || "").trim().toLowerCase();

const fallas = [];
const ok = (cond, linea, detalle = "") => {
  console.log((cond ? "  ✅ " : "  ❌ ") + linea + (!cond && detalle ? `   → ${detalle}` : ""));
  if (!cond) fallas.push(linea);
};
const noMedible = (m) => { console.log(`[no medible] ${m}`); process.exit(2); };

const USER = "due-1";
const LOS_SEIS = ["ciencia", "oficina", "legal", "educacion", "diseno", "finanzas"];

// EL STUB ES DE RED, NO DEL MÓDULO. Se reemplaza `fetch` —la frontera del navegador— y no
// una función de `espacios.js`: lo que se mide es el módulo de producción entero.
const memoria = Object.fromEntries(LOS_SEIS.map((ws, i) => [ws, { chat_id: `c-${i}`, sid: "s-1" }]));
globalThis.fetch = async (url) => {
  const u = String(url);
  const m = u.match(/\/v1\/workspaces\/([^/]+)\/memoria/);
  if (m) {
    const mem = memoria[decodeURIComponent(m[1])];
    return { ok: true, json: async () => ({ memoria: mem || {} }) };
  }
  if (u.startsWith("/v1/chats")) {
    return { ok: true, json: async () => ({
      chats: LOS_SEIS.map((ws, i) => ({ id: `c-${i}`, title: ws, updated_at: "2026-08-27", n_messages: 3 })),
    }) };
  }
  if (u.includes("/artifacts")) return { ok: true, json: async () => ({ artifacts: [] }) };
  return { ok: false, json: async () => ({}) };
};
// EL `window` MÁS CHICO QUE ALCANZA, y a propósito no es `qa/dom_minimo.mjs`: ese archivo
// existe para probar CLICKS y su propia nota pide no agrandarlo «hasta que sea un navegador
// malo». Acá no se aprieta nada — sólo hay que dejar que el módulo se importe. `espacios.js`
// trae `cabeceras` de `conectores/fuentes.js`, que arrastra `widget.js` y
// `cuarto.semaforo.js`, y ésos sí registran oyentes al cargar. (De paso: el comentario de
// `espacios.js` dice importar de `espacios-tabla.js` «para no arrastrar el subsistema de
// conectores entero» — y por `fuentes.js` lo arrastra igual. Queda anotado, no es de esta obra.)
globalThis.window = globalThis;                       // el módulo publica su puente en `window`
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
globalThis.document = {
  addEventListener: () => {}, removeEventListener: () => {},
  querySelector: () => null, querySelectorAll: () => [],
  createElement: () => ({ style: {}, setAttribute: () => {}, appendChild: () => {},
                          addEventListener: () => {}, classList: { add: () => {}, remove: () => {} } }),
  documentElement: { style: { setProperty: () => {} } },
  body: { appendChild: () => {} },
};

// EL MUTANTE REPRODUCE EL DEFECTO EXACTO: le saca `ORDEN_ETIQUETA` al import de
// `espacios.js` — que es, byte por byte, cómo estaba el archivo. Se copia UN solo archivo a
// un temporal y sus imports se reescriben a rutas ABSOLUTAS del árbol real, para que
// `espacios-tabla.js` y todo el subárbol de `conectores/` resuelvan al de producción.
//
// El primer intento copiaba el subárbol al temporal y daba rojo — pero por «Cannot find
// module widget.js», o sea por la copia incompleta y no por el símbolo. Un rojo por el
// motivo equivocado no prueba nada: la vara habría pasado por buena sin medir el defecto.
let DIR = DISENO;
if (ROMPER === "import") {
  const { readFileSync, writeFileSync, mkdtempSync } = await import("node:fs");
  const os = await import("node:os");
  const tmp = mkdtempSync(path.join(os.tmpdir(), "vara-espacios-"));
  const src = readFileSync(path.join(DISENO, "espacios.js"), "utf8")
    .replace("import { GENERAL, ORDEN_ETIQUETA, etiqueta, espacios }",
             "import { GENERAL, etiqueta, espacios }")          // ← el defecto, tal cual estaba
    .replace(/from "\.\/([^"]+)"/g, (_, r) => `from "${pathToFileURL(path.join(DISENO, r)).href}"`)
    .replace(/from "\.\.\/([^"]+)"/g, (_, r) => `from "${pathToFileURL(path.join(DISENO, "..", r)).href}"`);
  if (src.includes("ORDEN_ETIQUETA, etiqueta")) noMedible("el mutante no encontró el import que muta");
  writeFileSync(path.join(tmp, "espacios.js"), src);
  DIR = tmp;
}


console.log(`\n── el módulo del filtro por espacio corre ${"─".repeat(44)}`);
let E;
try {
  E = await import(pathToFileURL(path.join(DIR, "espacios.js")).href);
} catch (exc) {
  ok(false, "el módulo se importa sin caerse", exc.message);
}

if (E) {
  // 1 · LA FUNCIÓN QUE SE CAÍA. `ORDEN_ETIQUETA` se usa en su primera línea.
  let mem = null, err = null;
  try { mem = await E.memoriaDeLosSeis(USER); } catch (exc) { err = exc; }
  ok(!err, "`memoriaDeLosSeis` corre sin ReferenceError", err ? err.message : "");
  ok(mem && Object.keys(mem).length === 6,
     "y devuelve los seis espacios", `devolvió ${mem ? Object.keys(mem).length : "nada"}`);

  // 2 · LAS DOS PÚBLICAS QUE DEPENDEN DE ELLA — son las que consumen las pantallas.
  let hilos = null; err = null;
  try { hilos = await E.hilosDeEspacio(USER); } catch (exc) { err = exc; }
  ok(!err, "`hilosDeEspacio` corre (la usa Historial.dc.html)", err ? err.message : "");
  ok(hilos && hilos.length === 6, "y devuelve un hilo por espacio",
     `devolvió ${hilos ? hilos.length : "nada"}`);
  const sinWs = (hilos || []).filter((h) => !h.ws).length;
  ok(!sinWs, "cada hilo dice de qué espacio es", `${sinWs} sin \`ws\``);

  err = null;
  try { await E.obraDeEspacio(USER, "s-1"); } catch (exc) { err = exc; }
  ok(!err, "`obraDeEspacio` corre (la usa Biblioteca.dc.html)", err ? err.message : "");

  // 3 · EL PUENTE A LAS `.dc.html`, que no pueden `import` y leen `window.AlephEspacios`.
  const P = globalThis.window.AlephEspacios;
  const faltan = ["GENERAL", "espacios", "etiqueta", "hilosDeEspacio", "obraDeEspacio",
                  "memoriaDeLosSeis", "pasa"].filter((k) => !(P && k in P));
  ok(!faltan.length, "`window.AlephEspacios` publica su superficie entera", `faltan: ${faltan}`);
}

console.log("\n" + "=".repeat(78));
if (fallas.length) {
  console.log(`ROJO — ${fallas.length} fallaron:`);
  fallas.forEach((f) => console.log(`  · ${f}`));
  process.exit(1);
}
console.log("VERDE — el módulo del filtro por espacio corre y devuelve los seis.");
