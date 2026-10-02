/* verify_vacio_del_usuario_nuevo.mjs — ¿QUÉ VE UN USUARIO NUEVO EN HISTORIAL Y BIBLIOTECA?
 *
 * [convergencia · superficie 1]
 *
 * LO QUE MEDÍA ANTES DE LA OBRA: nueve sesiones inventadas («Cierre semanal · S24»,
 * «Migración del endpoint de auth») y cuatro Aleph que no existen (Reportero ·
 * Investigador · Programador · Tutora) con su obra fabricada por un PRNG sembrado.
 *
 * Y el detalle que lo hacía urgente: las dos maquetas se pintaban en la rama de CERO datos
 * —`if(!runs.length) return` en Historial, el `else` del `if(real && real.length)` en
 * Biblioteca—, así que las veía exactamente una persona: la que abre el producto por
 * primera vez. El dueño con obra real no las vio nunca, y por eso nadie las reportó.
 *
 * CÓMO MIDE. No es un grep contra el archivo: se EJECUTA el bloque de script de la página
 * con `DCLogic` stubbeado y se le pide su `renderVals()` con el estado de un usuario recién
 * llegado. Lo que se mira es el modelo de vista que la pantalla va a pintar. Un grep diría
 * que el literal no está; esto dice que la pantalla no lo muestra, que es la afirmación.
 *
 * LAS TRES ASERCIONES, por pantalla:
 *   1. con cero datos, la lista sale VACÍA;
 *   2. el vacío tiene copy —no es un hueco mudo—;
 *   3. y son DOS causas con DOS copys: «no hay nada» ≠ «nada coincide». Con la lista vacía,
 *      mandar a aflojar un filtro que el usuario no puso es mandarlo al lugar equivocado.
 *      (La regla ya estaba escrita en `sala-v2/ui/sidebar.js:162`; acá se custodia.)
 *
 * Probala cayendo:
 *   ALEPH_VARA_ROMPER=seed     devuelve el seed de las nueve sesiones → rojo en Historial
 *   ALEPH_VARA_ROMPER=unacausa colapsa los dos copys en uno → rojo en las dos
 *
 *   node qa/verify_vacio_del_usuario_nuevo.mjs
 *     0 → un usuario nuevo ve un vacío con causa
 *     1 → ve datos inventados, o un vacío mudo, o una sola causa
 *     2 → no se pudo medir (NO cuenta como verde)
 */
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"
import vm from "node:vm"

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..")
const ROMPER = (process.env.ALEPH_VARA_ROMPER || "").trim().toLowerCase()

const SEED_HISTORIAL = [
  { id: 1, agent: "rep", title: "Cierre semanal · S24", status: "paused", group: "today",
    when: "hace 2 h", steps: "7 pasos", produced: "hoja de cálculo", peek: "chart" },
]

function noMedible(motivo) {
  console.log(`[no medible] ${motivo}`)
  process.exit(2)
}

/** Corre el bloque `<script>` de una página y devuelve su clase `Component`. */
function componenteDe(rutaRel) {
  const html = readFileSync(join(RAIZ, rutaRel), "utf8")
  const m = html.match(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/)
  if (!m) throw new Error(`${rutaRel}: no encontré su bloque de script`)
  const ctx = vm.createContext({
    // `DCLogic` sólo aporta `setState`/`props` — la lógica de la pantalla es toda propia.
    DCLogic: class { setState() {} },
    React: { createElement: (t, p, ...k) => ({ t, p, k }) },
    console, Date, Math, JSON,
    document: { documentElement: { style: { setProperty() {} } }, querySelector: () => null },
    window: {}, fetch: async () => ({ ok: false }), localStorage: { getItem: () => null },
    setTimeout: () => 0, clearTimeout: () => {},
  })
  vm.runInContext(m[1] + "\n;globalThis.__C = Component;", ctx, { filename: rutaRel })
  return ctx.__C
}

const casos = [
  {
    pantalla: "Historial",
    ruta: "product/app/design/Historial.dc.html",
    /** El usuario nuevo: la pantalla montada y `loadHist()` que no trajo nada. */
    vista(C) {
      const c = new C()
      c.props = {}
      // El desenchufe tiene que reproducir el estado PREVIO ENTERO, no medio: la primera
      // versión devolvía sólo `sessions` y `renderVals` reventaba en
      // `this.agents[x.agent].name` — o sea salía 2 («no medible») donde tenía que salir 1
      // («rojo»). Un modo de rotura que no puede dar rojo no prueba la vara.
      if (ROMPER === "seed") {
        c.agents = { rep: { name: "Reportero", mono: "Rp", color: "#8A8A90" } }
        c.sessions = SEED_HISTORIAL
      }
      const v = c.renderVals()
      return { vacio: v.empty === true, titulo: v.emptyTitle, pista: v.emptyHint,
               filas: c.sessions.length }
    },
    /** La MISMA pantalla con datos, para poder comparar las dos causas. */
    conDatos(C) {
      const c = new C()
      c.props = {}
      c.agents = { rep: { name: "Reportero", mono: "Rp", color: "#8A8A90" } }
      c.sessions = SEED_HISTORIAL
      c.state = { ...c.state, query: "zzz-que-no-existe" }
      const v = c.renderVals()
      return { titulo: v.emptyTitle, pista: v.emptyHint }
    },
  },
  {
    pantalla: "Biblioteca",
    ruta: "product/app/design/Biblioteca.dc.html",
    vista(C) {
      const c = new C()
      c.props = {}
      const v = c.renderVals()
      return { vacio: v.rosterEmpty?.show === true, titulo: v.rosterEmpty?.title,
               pista: v.rosterEmpty?.hint, filas: (v.roster || []).length }
    },
    conDatos(C) {
      const c = new C()
      c.props = {}
      c._realOutputs = [{ id: "o1", kind: "report", puppet_id: "p1", puppet_name: "Real",
                          intent: "algo", created_at: new Date().toISOString() }]
      c.state = { ...c.state, query: "zzz-que-no-existe" }
      const v = c.renderVals()
      return { titulo: v.rosterEmpty?.title, pista: v.rosterEmpty?.hint }
    },
  },
]

let malas = []
console.log("¿QUÉ VE UN USUARIO NUEVO?\n")
for (const caso of casos) {
  let v, d
  try {
    const C = componenteDe(caso.ruta)
    v = caso.vista(C)
    d = caso.conDatos(C)
  } catch (e) {
    noMedible(`${caso.pantalla}: ${e?.message || e}`)
  }
  const problemas = []
  if (!v.vacio || v.filas > 0) problemas.push(`pinta ${v.filas} fila(s) inventada(s)`)
  if (!(v.titulo || "").trim() || !(v.pista || "").trim()) problemas.push("el vacío es mudo")
  const unaSola = ROMPER === "unacausa"
  const tituloConDatos = unaSola ? v.titulo : d.titulo
  if (tituloConDatos === v.titulo) {
    problemas.push(`una sola causa: «${v.titulo}» también con datos y filtro sin match`)
  }
  if (problemas.length) {
    malas.push(caso.pantalla)
    console.log(`  ❌  ${caso.pantalla.padEnd(11)}  ${problemas.join(" · ")}`)
  } else {
    console.log(`  ✅  ${caso.pantalla.padEnd(11)}  sin datos: «${v.titulo}» · ` +
                `con filtro sin match: «${d.titulo}»`)
  }
}
console.log()
if (malas.length) {
  console.log(`ROJO — ${malas.join(", ")}`)
  process.exit(1)
}
console.log("VERDE — el usuario nuevo ve un vacío con causa, y las dos causas están separadas.")
