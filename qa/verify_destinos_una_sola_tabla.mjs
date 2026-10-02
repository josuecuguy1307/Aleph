/* verify_destinos_una_sola_tabla.mjs — ¿LOS DESTINOS DE LA CASA SON UNA SOLA LISTA?
 *
 * [convergencia · superficie 8]
 *
 * LO QUE MEDÍA ANTES DE LA OBRA: había DOS listas de «los destinos del producto» y la
 * segunda había derivado, con consecuencia visible.
 *
 *   nav.js (la barra, 17 pantallas)  11 destinos
 *   Home.dc.html (el hub)             8 destinos — decía de sí mismo «mismo set que el
 *                                     launcher nav.js», y no lo era:
 *     · enlazaba `Estados.dc.html`, el catálogo de ESPECIFICACIÓN de diseño que la barra
 *       había sacado A PROPÓSITO («cualquier usuario llegaba a documentación interna con un
 *       clic»). El arreglo se hizo en una copia y la otra siguió llevando ahí.
 *     · le faltaban Modelos, Conectores, Métodos e Inspección.
 *   los 6 workspaces                  0 destinos — su barra tenía una sola salida
 *
 * LAS TRES ASERCIONES:
 *   1. los TRES consumidores pintan el MISMO conjunto (el hub sin «Inicio», que es donde ya
 *      estás — la única exclusión, y es del hub, no de la tabla);
 *   2. `Estados.dc.html` no está en ninguno;
 *   3. las rutas del panel del workspace RESUELVEN — se comprueba contra el disco, no por
 *      forma. Ésta nació de un defecto propio: la primera versión anteponía un `../` que la
 *      tabla ya ponía, y los once destinos quedaban rotos en los seis workspaces.
 *
 * CÓMO MIDE. Corre los tres archivos de producción: `nav.js` en un contexto de `vm` con
 * `location` apuntando a un workspace, el bloque de script de `Home.dc.html`, y
 * `destinos-del-espacio.js` montado contra una `.ws-bar` de mentira. Lo que se mira es lo
 * que cada uno PINTA, no lo que su fuente dice.
 *
 * Probala cayendo:
 *   ALEPH_VARA_ROMPER=estados   devuelve `Estados.dc.html` a la tabla → rojo por (1) y (2)
 *   ALEPH_VARA_ROMPER=hub       el hub vuelve a su lista propia de 8 → rojo por (1)
 *   ALEPH_VARA_ROMPER=ruta      el panel vuelve a anteponer `../` → rojo por (3)
 *
 *   node qa/verify_destinos_una_sola_tabla.mjs
 *     0 → una sola lista · 1 → volvieron a ser dos · 2 → no se pudo medir
 */
import { readFileSync, existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join, resolve } from "node:path"
import vm from "node:vm"

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..")
const DESIGN = join(RAIZ, "product", "app", "design")
const ROMPER = (process.env.ALEPH_VARA_ROMPER || "").trim().toLowerCase()
const ESTADOS = "Estados.dc.html"

function noMedible(motivo) { console.log(`[no medible] ${motivo}`); process.exit(2) }

function nodoFalso(tag) {
  const n = { tagName: tag, children: [], style: {}, attrs: {}, _html: "",
    hidden: false, className: "", textContent: "", type: "" }
  n.setAttribute = (k, v) => { n.attrs[k] = String(v) }
  n.getAttribute = (k) => (k in n.attrs ? n.attrs[k] : null)
  n.removeAttribute = (k) => { delete n.attrs[k] }
  n.appendChild = (c) => { n.children.push(c); return c }
  n.insertBefore = (c) => { n.children.push(c); return c }
  n.addEventListener = () => {}
  n.contains = () => false
  n.focus = () => {}
  n.querySelector = () => null
  Object.defineProperty(n, "innerHTML", { get: () => n._html, set: (v) => { n._html = String(v) } })
  return n
}

/** `nav.js` corrido de verdad, desde la ruta de un workspace. */
function tablaDeNav() {
  const src = readFileSync(join(DESIGN, "nav.js"), "utf8")
  const ctx = vm.createContext({
    ALEPH_NAV_BRAIN_OFF: 1, URLSearchParams, console,
    document: { documentElement: { classList: { add() {} } }, body: null,
      getElementById: () => null, createElement: nodoFalso, addEventListener() {},
      head: { appendChild() {} } },
    location: { pathname: "/design/workspaces/legal.html", search: "" },
    localStorage: { getItem: () => null },
  })
  ctx.window = ctx
  vm.runInContext(src, ctx, { filename: "nav.js" })
  const D = ctx.AlephDestinos
  if (!D || !D.items) throw new Error("nav.js no publicó `window.AlephDestinos`")
  if (ROMPER === "estados") {
    D.items.push({ id: ESTADOS, icon: "◫", key: "nav.estados", fb: "Estados",
                   get label() { return "Estados" } })
  }
  return D
}

/** El hub de Home, corrido de verdad, con la tabla ya publicada. */
function hubDeHome(D) {
  const html = readFileSync(join(DESIGN, "Home.dc.html"), "utf8")
  // EL BLOQUE ES EL DE `data-dc-script`, no «el primero sin src»: Home tiene varios y el
  // primero no es el del componente. Tomar el primero daba `Component is not defined`, o sea
  // salida 2 — el arnés diciendo «no pude medir» sobre un archivo perfectamente medible.
  const m = html.match(/<script[^>]*data-dc-script[^>]*>([\s\S]*?)<\/script>/)
  if (!m) throw new Error("Home.dc.html: no encontré su bloque `data-dc-script`")
  const roto = ROMPER === "hub"
  const win = {
    AlephDestinos: roto
      ? { items: D.items.filter((it) => /Cuarto|sala-v2|Historial|Biblioteca|Settings|Ayuda/.test(it.id))
                  .concat([{ id: ESTADOS, icon: "◫", get label() { return "Estados" } }]),
          etiqueta: D.etiqueta, href: D.href }
      : D,
    t: null,
  }
  const ctx = vm.createContext({
    DCLogic: class { setState() {} },
    React: { createElement: (t, p, ...k) => ({ t, p, k }) },
    console, Date, Math, JSON, Number, window: win,
    document: { documentElement: { style: { setProperty() {} } }, querySelector: () => null },
    fetch: async () => ({ ok: false }), localStorage: { getItem: () => null },
    setTimeout: () => 0, clearTimeout: () => {},
  })
  vm.runInContext(m[1] + "\n;globalThis.__C = Component;", ctx, { filename: "Home.dc.html" })
  const c = new ctx.__C()
  c.props = {}
  return (c.renderVals().hubItems || [])
}

/** El panel del workspace, montado de verdad contra una `.ws-bar` de mentira. */
function panelDelWorkspace(D) {
  const src = readFileSync(join(DESIGN, "workspaces", "destinos-del-espacio.js"), "utf8")
  const barra = nodoFalso("header")
  const body = nodoFalso("body")
  const win = { AlephDestinos: D }
  const ctx = vm.createContext({
    console, window: win,
    document: { querySelector: (q) => (q === ".ws-bar" ? barra : null),
      createElement: nodoFalso, body, addEventListener() {} },
  })
  vm.runInContext(src, ctx, { filename: "destinos-del-espacio.js" })
  win.AlephDestinosDelEspacio.montar("legal")
  const boton = barra.children[0]
  if (!boton) throw new Error("el panel no puso su botón en la barra")
  // se abre como lo abre el usuario: por el mismo camino que el click
  const panel = body.children[0]
  if (!panel) throw new Error("el panel no se montó")
  // `pintar()` corre al abrir; se fuerza llamando al handler registrado no es posible acá,
  // así que se re-monta pidiendo el HTML tras un click simulado: el módulo pinta en `click`.
  return { boton, panel }
}

let D, hub, ws
try {
  D = tablaDeNav()
  hub = hubDeHome(D)
} catch (e) { noMedible(`nav/Home: ${e?.message || e}`) }

/* El panel pinta dentro del handler de click, que el `vm` no dispara solo. Se reproduce el
 * MISMO cuerpo por su superficie pública: se re-monta con un `addEventListener` que captura
 * el handler y se lo invoca. Es el handler de producción, no una copia. */
function abrirPanel() {
  const src = readFileSync(join(DESIGN, "workspaces", "destinos-del-espacio.js"), "utf8")
  const barra = nodoFalso("header")
  const body = nodoFalso("body")
  let handler = null
  const boton = nodoFalso("button")
  boton.addEventListener = (ev, fn) => { if (ev === "click" && !handler) handler = fn }
  const win = { AlephDestinos: D }
  let creados = 0
  const ctx = vm.createContext({
    console, window: win,
    document: {
      querySelector: (q) => (q === ".ws-bar" ? barra : null),
      createElement: (tag) => (creados++ === 0 ? boton : nodoFalso(tag)),
      body, addEventListener() {},
    },
  })
  vm.runInContext(src, ctx, { filename: "destinos-del-espacio.js" })
  win.AlephDestinosDelEspacio.montar("legal")
  if (!handler) throw new Error("el botón no registró su click")
  handler()
  const panel = body.children[0]
  const hrefs = [...String(panel._html).matchAll(/href="([^"]+)"/g)].map((m) => m[1])
  return { html: panel._html, hrefs }
}

try { ws = abrirPanel() } catch (e) { noMedible(`panel: ${e?.message || e}`) }

const idsTabla = D.items.map((i) => i.id)
const enHub = hub.map((h) => h.href)
const problemas = []

// 1 · el mismo conjunto
const esperadoHub = idsTabla.filter((id) => id !== "Home.dc.html")
const faltanHub = esperadoHub.filter((id) => !enHub.some((h) => h.endsWith(id)))
const sobranHub = enHub.filter((h) => !idsTabla.some((id) => h.endsWith(id)))
if (faltanHub.length) problemas.push(`al hub le faltan: ${faltanHub.join(", ")}`)
if (sobranHub.length) problemas.push(`el hub tiene de más: ${sobranHub.join(", ")}`)
const faltanWs = idsTabla.filter((id) => !ws.hrefs.some((h) => h.endsWith(id)))
if (faltanWs.length) problemas.push(`al panel del workspace le faltan: ${faltanWs.join(", ")}`)

// 2 · Estados no está en ninguno
const dondeEstados = []
if (idsTabla.includes(ESTADOS)) dondeEstados.push("la tabla")
if (enHub.some((h) => h.endsWith(ESTADOS))) dondeEstados.push("el hub de Home")
if (ws.hrefs.some((h) => h.endsWith(ESTADOS))) dondeEstados.push("el panel del workspace")
if (dondeEstados.length) {
  problemas.push(`documentación interna (${ESTADOS}) alcanzable desde: ${dondeEstados.join(" · ")}`)
}

// 3 · las rutas del panel resuelven contra el disco
const rotas = ws.hrefs.filter((h) => {
  const limpio = h.split("?")[0]
  const prefijo = ROMPER === "ruta" ? "../" : ""
  return !existsSync(resolve(join(DESIGN, "workspaces"), prefijo + limpio))
})
if (rotas.length) problemas.push(`rutas que no resuelven desde un workspace: ${rotas.join(", ")}`)

console.log("¿LOS DESTINOS SON UNA SOLA LISTA?\n")
console.log(`  tabla (nav.js)          ${idsTabla.length} destinos`)
console.log(`  hub (Home.dc.html)      ${enHub.length}`)
console.log(`  panel (los 6 workspaces) ${ws.hrefs.length}`)
console.log()
if (problemas.length) {
  problemas.forEach((p) => console.log(`  ❌  ${p}`))
  console.log("\nROJO — vuelven a ser listas distintas.")
  process.exit(1)
}
console.log("  ✅  los tres pintan el mismo conjunto")
console.log(`  ✅  ${ESTADOS} no es alcanzable desde ninguno`)
console.log("  ✅  las 11 rutas resuelven desde un workspace")
console.log("\nVERDE — una sola tabla, tres consumidores.")
