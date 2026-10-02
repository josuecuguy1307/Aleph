/* sonda_busqueda_front.mjs — ¿A QUÉ URL LE PIDE UNA PANTALLA CUANDO EL USUARIO BUSCA?
 *
 * Corre el código de la pantalla con `fetch` interceptado y devuelve la primera URL que
 * pide al escribir. Es ejecución real: un grep sobre la fuente diría qué literal está
 * escrito, no a quién se le pide — y las dos cosas se separaron una vez, cuando el índice
 * existía y nadie lo llamaba.
 *
 *   node qa/lib/sonda_busqueda_front.mjs <archivo> <sala|historial>
 *   → stdout: JSON { url }
 */
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join, isAbsolute } from "node:path"
import vm from "node:vm"

const [, , ruta, gancho] = process.argv
const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..", "..")
/** El llamador puede pasar la ruta absoluta o relativa a la raíz; las dos valen. */
const abs = (p) => (isAbsolute(p) ? p : join(RAIZ, p))
const CONSULTA = "quetzal"

let pedida = ""
const fetchEspia = async (url) => {
  if (!pedida) pedida = String(url)
  return { ok: true, json: async () => ({ hilos: [], mensajes: [], artefactos: [], hits: [] }) }
}

function esperar(ms) { return new Promise((r) => setTimeout(r, ms)) }

try {
  if (gancho === "sala") {
    /* La Sala es un módulo con imports (React vendorizado): no entra en un `vm` pelado. Se
     * mide su HANDLER, que es lo que corre al teclear: se extrae el cuerpo de `onBuscar` del
     * archivo y se ejecuta con sus dependencias stubbeadas. Es el mismo cuerpo que despacha
     * el teclado — no una reimplementación. */
    const src = readFileSync(abs(ruta), "utf8")
    const m = src.match(/onBuscar: \(q\) => \{([\s\S]*?)\n      \},\n/)
    if (!m) throw new Error("no encontré el cuerpo de `onBuscar`")
    const ctx = vm.createContext({
      fetch: fetchEspia, console, setTimeout, clearTimeout, encodeURIComponent,
      setBuscando: () => {}, setResultados: () => {}, setHilos: () => {},
      cargarHilos: () => {}, authHeaders: () => ({}), PUPPET_ID: null,
      _tBuscar: { current: 0 },
    })
    vm.runInContext(`(function(q){${m[1]}})(${JSON.stringify(CONSULTA)})`, ctx, { filename: ruta })
    await esperar(400)
  } else {
    const html = readFileSync(abs(ruta), "utf8")
    const b = html.match(/<script[^>]*data-dc-script[^>]*>([\s\S]*?)<\/script>/)
    if (!b) throw new Error("no encontré el bloque `data-dc-script`")
    const win = { AlephSession: { get: () => ({ id: "u-vara", session_token: "t" }) } }
    const ctx = vm.createContext({
      DCLogic: class { setState() {} }, React: { createElement: () => ({}) },
      console, Date, Math, JSON, Number, Promise, window: win,
      document: { documentElement: { style: { setProperty() {} } }, querySelector: () => null },
      fetch: fetchEspia, localStorage: { getItem: () => null },
      setTimeout, clearTimeout, encodeURIComponent, URLSearchParams,
    })
    vm.runInContext(b[1] + "\n;globalThis.__C = Component;", ctx, { filename: ruta })
    const c = new ctx.__C()
    c.props = {}
    c.buscarEnElIndice(CONSULTA)
    await esperar(400)
  }
  process.stdout.write(JSON.stringify({ url: pedida }))
} catch (e) {
  process.stderr.write(String(e?.message || e))
  process.exit(1)
}
