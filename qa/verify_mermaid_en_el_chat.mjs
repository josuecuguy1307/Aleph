/* verify_mermaid_en_el_chat.mjs — LOS DIAGRAMAS DEL MODELO, PINTADOS EN LA BURBUJA.
 *
 * [tanda de artefactos · la integración]
 *
 * EL DEFECTO. `visualize` emite cuatro fences —```svg ```mermaid ```chartjs ```html— y
 * este repo sólo componía el primero (`renderSvgFences`). Un ```mermaid quedaba como
 * bloque de código: el modelo entrega el diagrama y la pantalla entrega su fuente.
 *
 * LO QUE ESTA OBRA PRENDE, Y LO QUE DEJA AFUERA A PROPÓSITO. Sólo `mermaid`. `chartjs`
 * no, porque los charts ya los resuelve `buildChartSVG` de esta misma casa y un segundo
 * motor sería la duplicación que este repo mata; `html` no, porque es EJECUCIÓN, que es
 * justo lo que este renderer no hace. Las dos exclusiones se MIDEN acá abajo (F): si
 * alguien las prende sin decidirlo, esta vara se pone roja.
 *
 * ── QUÉ MIDE, Y QUÉ NO ───────────────────────────────────────────────────────────────
 *
 * MEDIDO, CORRIENDO EL MÓDULO DE PRODUCCIÓN. `sala-render.js` se evalúa de verdad en un
 * `vm` y se le pide `SalaRender.renderInlineFigures(nodo)` con un espía en
 * `window.mermaid`. O sea: se mide que la llamada LLEGUE a mermaid, con ESE texto, y que
 * el `<pre>` se reemplace por una `<figure>` — no que exista una función con ese nombre.
 *
 * ⚠️ LO QUE **NO** PRUEBA: EL PÍXEL. mermaid de verdad son 3,5 MB que miden texto contra
 * un layout real; acá está doblado. Que un `flowchart TD` concreto quede legible en la
 * burbuja se mira EN PANTALLA contra la .app instalada, y esta vara no autoriza a decir
 * que se miró. Lo que sí prueba es la costura: quién llama, con qué, y qué pasa cuando el
 * diagrama está roto.
 *
 * Probala cayendo:
 *   ALEPH_VARA_ROMPER=sinllamador   se borra la llamada a renderMermaidFences   → rojo B
 *   ALEPH_VARA_ROMPER=singuardia    el reject de mermaid deja de atajarse       → rojo C
 *   ALEPH_VARA_ROMPER=htmllabels    vuelve el `htmlLabels:true`                 → rojo D
 *   ALEPH_VARA_ROMPER=cdn           el vendor se cambia por un CDN              → rojo A
 *
 *   node qa/verify_mermaid_en_el_chat.mjs
 *     0 → el diagrama del modelo llega pintado · 1 → no llega · 2 → no se pudo medir
 */
import { readFileSync, existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"
import vm from "node:vm"

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..")
const DESIGN = join(RAIZ, "product", "app", "design")
const ROMPER = (process.env.ALEPH_VARA_ROMPER || "").trim().toLowerCase()

const malas = []
const ok = (n, d) => console.log(`  ✅  ${n}${d ? " — " + d : ""}`)
const mal = (n, d) => { malas.push(n); console.log(`  ❌  ${n}${d ? " — " + d : ""}`) }
const noMedible = (m) => { console.log(`[no medible] ${m}`); process.exit(2) }

// Sin el `.catch` del renderer, el reject de mermaid queda HUÉRFANO y node mata el
// proceso: la vara caería por crash, que es una caída ilegible. Se atrapa acá para que el
// modo de falla se REPORTE —«se escapó el error»— en vez de reventar la corrida.
const escapados = []
process.on("unhandledRejection", (e) => { escapados.push(e) })

/* ══ EL DOM MÁS CHICO QUE ALCANZA ═══════════════════════════════════════════════════
 * No es `dom_minimo.mjs`: aquél modela CLICKS y delegación de eventos, y lo que hace
 * falta acá es otra cosa —`closest`, `replaceChild` y un `querySelectorAll` por clase de
 * lenguaje—. Agrandar aquél para esto lo volvería un navegador malo (su propio aviso).  */
let _seq = 0
class N {
  constructor(tag) { this.tag = tag; this.hijos = []; this.padre = null; this.attrs = {}; this.texto = ""; this.style = {}; this._html = "" }
  get nodeType() { return 1 }
  get parentNode() { return this.padre }
  get className() { return this.attrs.class || "" }
  set className(v) { this.attrs.class = v }
  setAttribute(k, v) { this.attrs[k] = String(v) }
  removeAttribute(k) { delete this.attrs[k] }
  appendChild(h) { h.padre = this; this.hijos.push(h); return h }
  get textContent() { return this.texto }
  set textContent(v) { this.texto = v }
  get innerHTML() { return this._html }
  set innerHTML(v) {
    this._html = v
    // Sólo lo que el código real le pide a una figura recién armada: encontrar su <svg>.
    this.hijos = /<svg[\s>]/i.test(v) ? [Object.assign(new N("svg"), { padre: this })] : []
  }
  closest(sel) { let n = this; while (n) { if (n.tag === sel) return n; n = n.padre } return null }
  querySelector(sel) { return this.hijos.find((h) => h.tag === sel) || null }
  replaceChild(nuevo, viejo) {
    const i = this.hijos.indexOf(viejo)
    if (i < 0) throw new Error("replaceChild: no es hijo")
    this.hijos[i] = nuevo; nuevo.padre = this; viejo.padre = null
  }
  remove() { if (this.padre) this.padre.hijos = this.padre.hijos.filter((h) => h !== this) }
  *_todos() { yield this; for (const h of this.hijos) yield* h._todos() }
  querySelectorAll(sel) {
    // Alcanza con las dos formas que el código real usa: `pre > code.language-X` y
    // `code.language-X`. Cualquier otra cosa devuelve vacío, y se ve.
    const clases = sel.split(",").map((s) => (s.match(/code\.(language-[\w-]+)/) || [])[1]).filter(Boolean)
    return [...this._todos()].filter((n) => n.tag === "code" && clases.includes(n.className))
  }
}
const fence = (lang, txt) => {
  const pre = new N("pre"), code = new N("code")
  code.className = "language-" + lang; code.textContent = txt
  pre.appendChild(code); return pre
}

/* ══ A · VENDORIZADO, JAMÁS UN CDN ══════════════════════════════════════════════════ */
console.log("\nA · el bundle es de la casa (local-first), no una promesa de red")

let fuente
try { fuente = readFileSync(join(DESIGN, "render", "sala-render.js"), "utf8") }
catch (e) { noMedible(`sala-render.js no se pudo leer: ${e?.message || e}`) }

if (ROMPER === "cdn") fuente = fuente.replace('mermaid: VBASE + "mermaid.min.js"', 'mermaid: "https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"')
if (ROMPER === "sinllamador") fuente = fuente.replace("    renderMermaidFences(el);\n", "")
if (ROMPER === "htmllabels") fuente = fuente.replace(/htmlLabels: false/g, "htmlLabels: true")
if (ROMPER === "singuardia") fuente = fuente.replace('.catch(function () { /* diagrama inválido: se queda el code-block */ })', ".then(function () {})")

const decl = (fuente.match(/mermaid:\s*(.+),/) || [])[1] || ""
if (/https?:\/\//.test(decl)) mal("mermaid se declara por RED", `${decl.trim()} — Aleph es local-first y el .app viaja sin internet`)
else if (!/VBASE/.test(decl)) mal("mermaid no sale del vendor", decl.trim())
else ok("mermaid sale de `vendor/`", decl.trim())

const BUNDLE = join(DESIGN, "vendor", "mermaid.min.js")
if (!existsSync(BUNDLE)) mal("el bundle NO está en el árbol", "la declaración apunta a un archivo que no existe")
else {
  const b = readFileSync(BUNDLE, "utf8")
  const kb = Math.round(b.length / 1024)
  if (!/globalThis\["mermaid"\]\s*=/.test(b)) mal("el bundle no deja `window.mermaid`", "loadScript cargaría y nadie lo encontraría")
  else ok("el bundle está y expone `mermaid`", `${kb} KB en vendor/`)
}

/* ══ EL MÓDULO DE PRODUCCIÓN, CORRIDO ═══════════════════════════════════════════════ */
const pedidos = []          // lo que se le pidió a mermaid.render
const inits = []            // con qué se inicializó
const sanitizados = []      // lo que pasó por DOMPurify
let cargados = []           // qué scripts se pidieron por red/vendor
let siguiente = null        // qué contesta el mermaid doble

const documento = {
  currentScript: null,
  body: new N("body"),
  querySelector: () => null,
  getElementById: () => null,
  createElement: (t) => new N(t),
  createElementNS: (_ns, t) => new N(t),
  head: { appendChild: (s) => { cargados.push(s.src); if (s.onload) s.onload() } },
}
const ventana = {
  mermaid: {
    initialize: (o) => inits.push(o),
    render: (id, txt) => { pedidos.push({ id, txt }); return siguiente(txt) },
  },
  DOMPurify: {
    sanitize: (html, cfg) => { sanitizados.push({ html, cfg }); return html },
  },
  getComputedStyle: () => ({ backgroundColor: "rgb(255, 255, 255)" }),
}
let SalaRender = null
try {
  const ctx = vm.createContext({ window: ventana, document: documento, console, getComputedStyle: ventana.getComputedStyle, Math, Promise, Array, String, Object, Error })
  ctx.globalThis = ctx
  vm.runInContext(fuente, ctx, { filename: "sala-render.js" })
  SalaRender = ventana.SalaRender || null
} catch (e) { noMedible(`sala-render.js no se pudo evaluar: ${e?.message || e}`) }
if (!SalaRender || typeof SalaRender.renderInlineFigures !== "function")
  noMedible("sala-render.js corrió y no dejó `SalaRender.renderInlineFigures`")

const respirar = () => new Promise((r) => setTimeout(r, 0))
async function pintar(nodo) { SalaRender.renderInlineFigures(nodo); await respirar(); await respirar(); return nodo }

/* ══ B · EL FENCE VÁLIDO SE CONVIERTE EN FIGURA ═════════════════════════════════════ */
console.log("\nB · un mermaid válido llega a mermaid y sale como figura")
const DIAGRAMA = "flowchart TD\n  A[Turno] --> B[Puente]\n  B --> C[Obra]"
siguiente = () => Promise.resolve({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><g/></svg>' })
{
  const raiz = new N("div"); raiz.appendChild(fence("mermaid", DIAGRAMA))
  await pintar(raiz)
  if (!pedidos.length) mal("la llamada no llegó a mermaid", "el fence se quedaría como bloque de código")
  else if (pedidos[0].txt !== DIAGRAMA) mal("mermaid recibió otro texto", pedidos[0].txt.slice(0, 40))
  else ok("el texto del fence llega tal cual a mermaid", `${DIAGRAMA.split("\n")[0]}…`)
  const hijo = raiz.hijos[0]
  if (hijo && hijo.tag === "figure") ok("el <pre> se reemplazó por una <figure>", hijo.className)
  else mal("el <pre> sigue ahí", `quedó <${hijo && hijo.tag}> — el diagrama no se compuso`)
}

/* ══ C · EL INVÁLIDO CAE LEGIBLE, NO ROMPE LA PANTALLA ══════════════════════════════ */
console.log("\nC · un mermaid roto se queda como código: la burbuja NO se rompe")
for (const [comoFalla, doble] of [
  ["la promesa rechaza", () => Promise.reject(new Error("Parse error on line 2"))],
  ["tira sincrónico", () => { throw new Error("Parse error") }],
]) {
  siguiente = doble
  const raiz = new N("div"); raiz.appendChild(fence("mermaid", "flowchart TD\n  A -->"))
  let reventó = null
  escapados.length = 0
  try { await pintar(raiz) } catch (e) { reventó = e }
  if (!reventó && escapados.length) reventó = escapados[0]   // el reject huérfano también cuenta
  if (reventó) mal(`${comoFalla}: se escapó el error`, String(reventó.message || reventó))
  else if (raiz.hijos[0] && raiz.hijos[0].tag === "pre") ok(`${comoFalla}: queda el <pre><code>`, "fallback honesto")
  else mal(`${comoFalla}: la burbuja quedó rota`, `hay un <${raiz.hijos[0] && raiz.hijos[0].tag}> en vez del código`)
}

/* ══ D · LA FORMA QUE EL SANITIZADOR ACEPTA ════════════════════════════════════════ */
console.log("\nD · sin `foreignObject`: las etiquetas tienen que sobrevivir al sanitizador")
{
  const cfgs = sanitizados.map((s) => s.cfg || {})
  const prohibe = cfgs.some((c) => (c.FORBID_TAGS || []).includes("foreignObject"))
  if (!prohibe) mal("el sanitizador ya no prohíbe `foreignObject`", "es render, no ejecución")
  else ok("`foreignObject` sigue prohibido", "el perfil no se aflojó para que entre mermaid")
  const conf = inits[0] || {}
  const flat = conf.htmlLabels === false && (conf.flowchart || {}).htmlLabels === false
  if (!flat) mal("mermaid pinta las etiquetas con HTML", "el sanitizador se las come: nodos VACÍOS")
  else ok("`htmlLabels:false`", "las etiquetas salen como <text>, que sí sobrevive")
  if (conf.securityLevel !== "strict") mal("mermaid no corre en `strict`", String(conf.securityLevel))
  else ok("mermaid corre en `strict`", "sin handlers ni click bindings")
}

/* ══ E · LO QUE YA ANDABA SIGUE ANDANDO ════════════════════════════════════════════ */
console.log("\nE · el ```svg de siempre no se tocó")
{
  const raiz = new N("div"); raiz.appendChild(fence("svg", '<svg viewBox="0 0 10 10"><rect/></svg>'))
  await pintar(raiz)
  const h = raiz.hijos[0]
  if (h && h.tag === "figure") ok("un ```svg sigue componiéndose", h.className)
  else mal("se rompió el ```svg", `quedó <${h && h.tag}>`)
}

/* ══ F · LAS EXCLUSIONES SON UNA DECISIÓN, Y SE MIDEN ══════════════════════════════ */
console.log("\nF · ```chartjs y ```html quedan afuera A PROPÓSITO")
for (const lang of ["chartjs", "html"]) {
  const raiz = new N("div"); raiz.appendChild(fence(lang, "algo"))
  await pintar(raiz)
  const h = raiz.hijos[0]
  if (h && h.tag === "pre") ok(`\`\`\`${lang} sigue siendo código`, lang === "html" ? "es ejecución: no entra" : "los charts los hace buildChartSVG")
  else mal(`\`\`\`${lang} se prendió sin decisión`, `quedó <${h && h.tag}>`)
}

/* ══ G · SIN FENCE, NO SE BAJAN 3,5 MB ═════════════════════════════════════════════ */
console.log("\nG · el bundle no se carga en un turno de texto")
{
  cargados = []
  const raiz = new N("div"); raiz.appendChild(fence("python", "print(1)"))
  await pintar(raiz)
  const pidió = cargados.some((s) => /mermaid/.test(String(s)))
  if (pidió) mal("se bajó mermaid sin ningún diagrama", "3,5 MB por un turno de texto")
  else ok("no se pidió el bundle", "carga on-demand, como hljs")
}

/* ══ VEREDICTO ═════════════════════════════════════════════════════════════════════ */
console.log("\n" + "=".repeat(80))
if (malas.length) { console.log(`ROJO — ${malas.length}: ${malas.join(" · ")}`); process.exit(1) }
console.log("TODO VERDE — el diagrama del modelo llega pintado, y el roto cae legible")
console.log("⚠️  el PÍXEL no lo prueba esta vara: se mira en pantalla contra la .app instalada")
console.log("=".repeat(80))
