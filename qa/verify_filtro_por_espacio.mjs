/* verify_filtro_por_espacio.mjs — ¿EL FILTRO POR ESPACIO SEPARA DE VERDAD?
 *
 * [convergencia · superficie 1]
 *
 * EL PAR FALSABLE, y es uno solo: **un hilo de Ciencia tiene que aparecer con el filtro en
 * Ciencia y NO aparecer con el filtro en Legal.** Un filtro que deja pasar todo es
 * decorativo, y hasta esta obra el filtro no podía ser otra cosa: medido, `runs.space_id`
 * de workspace era 0 de 2.341 y la tabla `outputs` no tiene ninguna columna que pueda
 * llevar un workspace. Filtrar daba vacío siempre, para los seis.
 *
 * CÓMO MIDE. Se corre el bloque de script de cada pantalla con `DCLogic` stubbeado y se le
 * pide su `renderVals()` una vez por filtro. Lo que se mira es qué filas pinta.
 *
 * Y el módulo del filtro **es el de producción, importado de verdad**: de
 * `product/app/design/espacios.js` se usan `pasa`, `espacios`, `etiqueta` y `GENERAL` tal
 * cual salen del archivo. Lo único stubbeado son los dos lectores que salen a la red
 * (`hilosDeEspacio` y `obraDeEspacio`) — o sea que si alguien afloja `pasa()`, esta vara se
 * entera. Stubbear el filtro entero habría medido el stub.
 *
 * Probala cayendo:
 *   ALEPH_VARA_ROMPER=sinfiltro  `pasa()` deja pasar todo → rojo en las dos (Ciencia se
 *                                cuela bajo Legal), que es el defecto que esta vara existe
 *                                para agarrar
 *   ALEPH_VARA_ROMPER=sinhilos   Historial no recibe los hilos → rojo en Historial
 *   ALEPH_VARA_ROMPER=sinobra    Biblioteca no recibe los artefactos → rojo en Biblioteca
 *
 *   node qa/verify_filtro_por_espacio.mjs
 *     0 → el filtro separa · 1 → no separa · 2 → no se pudo medir (NO cuenta como verde)
 */
import { readFileSync } from "node:fs"
import { fileURLToPath, pathToFileURL } from "node:url"
import { dirname, join } from "node:path"
import vm from "node:vm"

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..")
const DESIGN = join(RAIZ, "product", "app", "design")
const ROMPER = (process.env.ALEPH_VARA_ROMPER || "").trim().toLowerCase()
const AHORA = new Date().toISOString()

function noMedible(motivo) {
  console.log(`[no medible] ${motivo}`)
  process.exit(2)
}

/* EL MÓDULO DE PRODUCCIÓN. Sólo se reemplazan los dos lectores de red. */
let E
try {
  const real = await import(pathToFileURL(join(DESIGN, "espacios.js")).href)
  E = {
    GENERAL: real.GENERAL,
    espacios: real.espacios,
    etiqueta: real.etiqueta,
    pasa: ROMPER === "sinfiltro" ? () => true : real.pasa,
    async hilosDeEspacio() {
      if (ROMPER === "sinhilos") return []
      return [
        { ws: "ciencia", chat_id: "chat-ciencia", title: "Ciencia", updated_at: AHORA, n: 4 },
        { ws: "legal", chat_id: "chat-legal", title: "Legal", updated_at: AHORA, n: 2 },
      ]
    },
    async obraDeEspacio() {
      if (ROMPER === "sinobra") return []
      return [
        { id: "a1", title: "Informe de Ciencia", type: "informe", created_at: AHORA, workspace: "ciencia" },
        { id: "a2", title: "Revisión legal", type: "informe", created_at: AHORA, workspace: "legal" },
      ]
    },
  }
} catch (e) {
  noMedible(`no pude importar espacios.js: ${e?.message || e}`)
}

function componenteDe(rutaRel) {
  const html = readFileSync(join(RAIZ, rutaRel), "utf8")
  const m = html.match(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/)
  if (!m) throw new Error(`${rutaRel}: no encontré su bloque de script`)
  const win = { AlephEspacios: E, AlephSession: { get: () => ({ id: "u-vara" }) } }
  const ctx = vm.createContext({
    DCLogic: class { setState() {} },
    React: { createElement: (t, p, ...k) => ({ t, p, k }) },
    console, Date, Math, JSON, Number, Promise, window: win,
    document: { documentElement: { style: { setProperty() {} } }, querySelector: () => null },
    fetch: async () => ({ ok: false }), localStorage: { getItem: () => null },
    setTimeout: (f) => { if (typeof f === "function") f(); return 0 }, clearTimeout: () => {},
  })
  vm.runInContext(m[1] + "\n;globalThis.__C = Component;", ctx, { filename: rutaRel })
  return ctx.__C
}

/** Los títulos que la pantalla pinta con este filtro. */
function titulosHistorial(c, espacio) {
  c.state = { ...c.state, espacio }
  const v = c.renderVals()
  const de = []
  ;(v.pinned || []).forEach((x) => de.push(x.title))
  ;(v.groups || []).forEach((g) => (g.items || []).forEach((x) => de.push(x.title)))
  return de
}

function titulosBiblioteca(c, espacio) {
  c.state = { ...c.state, espacio }
  const v = c.renderVals()
  return (v.roster || []).map((a) => a.name)
}

const casos = [
  {
    pantalla: "Historial",
    ruta: "product/app/design/Historial.dc.html",
    async cargar(C) {
      const c = new C()
      c.props = {}
      await c.loadEspacios()                 // el loader REAL de la pantalla
      return c
    },
    titulos: titulosHistorial,
    // el hilo de Ciencia, tal como la pantalla lo nombra
    deCiencia: "Ciencia",
    deLegal: "Legal",
  },
  {
    pantalla: "Biblioteca",
    ruta: "product/app/design/Biblioteca.dc.html",
    async cargar(C) {
      const c = new C()
      c.props = {}
      await c.loadObraDeEspacios()
      return c
    },
    titulos: titulosBiblioteca,
    deCiencia: "Ciencia",
    deLegal: "Legal",
  },
]

let malas = []
console.log("¿EL FILTRO POR ESPACIO SEPARA?\n")
for (const caso of casos) {
  let general, ciencia, legal
  try {
    const C = componenteDe(caso.ruta)
    const c = await caso.cargar(C)
    general = caso.titulos(c, E.GENERAL)
    ciencia = caso.titulos(c, "ciencia")
    legal = caso.titulos(c, "legal")
  } catch (e) {
    noMedible(`${caso.pantalla}: ${e?.message || e}`)
  }
  const hay = (lista, t) => lista.some((x) => String(x).includes(t))
  const problemas = []
  if (!hay(general, caso.deCiencia) || !hay(general, caso.deLegal)) {
    problemas.push(`GENERAL no trae los dos espacios (${general.length} fila/s)`)
  }
  if (!hay(ciencia, caso.deCiencia)) problemas.push("con filtro Ciencia, Ciencia NO aparece")
  if (hay(legal, caso.deCiencia)) problemas.push("con filtro Legal, Ciencia SE CUELA")
  if (!hay(legal, caso.deLegal)) problemas.push("con filtro Legal, Legal no aparece")
  if (problemas.length) {
    malas.push(caso.pantalla)
    console.log(`  ❌  ${caso.pantalla.padEnd(11)}  ${problemas.join(" · ")}`)
  } else {
    console.log(`  ✅  ${caso.pantalla.padEnd(11)}  GENERAL ${general.length} · ` +
                `Ciencia ${ciencia.length} · Legal ${legal.length} — y Ciencia no cruza a Legal`)
  }
}
console.log()
if (malas.length) {
  console.log(`ROJO — ${malas.join(", ")}`)
  process.exit(1)
}
console.log("VERDE — sin filtro va todo junto; con filtro, sólo ese espacio.")
