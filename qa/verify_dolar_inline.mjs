/* verify_dolar_inline.mjs — EL `$` INLINE, MEDIDO CONTRA LOS 216 PARES REALES.
 *
 * [Educación · los artefactos · 2026-08-27]
 *
 * EL PROBLEMA. Un tutor de matemática escribe `$h$`, `$x^2$`, `$6+h$`. Un informe
 * financiero escribe `US$ 63.762,69 / ETH: US$`. Con el `$` prendido a secas KaTeX se
 * come lo segundo entero; apagado, se pierde lo primero. Y la casa tenía LAS DOS
 * respuestas: `render.js` lo traía prendido, `sala-render.js` apagado — el mismo párrafo
 * se leía distinto según dónde cayera.
 *
 * LA VARA NO INVENTA CASOS: LOS SACA DE `aleph.db`. Barridos los mensajes de agente de
 * la máquina, los pares `$…$` reales son **218**, y están perfectamente repartidos:
 *
 *     Educación  213 pares — todos MATH    → TIENEN que convertirse
 *     Finanzas     3 pares — todos MONEDA  → TIENEN que quedar como texto
 *                                            «US$ 63.762,69 / ETH: US$»
 *     Oficina      2 pares — todos MONEDA  → idem
 *                                            «Transporte con $504.50 (38.2%)… vuelos $420.00»
 *
 * Y los dos hilos de moneda caen por reglas DISTINTAS, que es lo que hace fuerte al par:
 * Finanzas por la regla 1 (el `$` viene pegado a `US`), Oficina por la regla 2 (el
 * candidato a cierre viene pegado a un espacio). Una guardia que sólo mirara monedas
 * conocidas pasaría el caso de Oficina.
 *
 * Eso es un par falsable de verdad: una guardia que deja pasar todo falla del lado de
 * Finanzas, y una que no deja pasar nada falla del lado de Educación. No hay forma de
 * pasar esta vara sin discriminar.
 *
 * QUÉ CORRE. `sala-render.js` se ejecuta de verdad en un `vm` y se le pide su
 * `mathInlineDeDolar` — la función de producción, sobre las cadenas de producción. No se
 * mide KaTeX (eso ya estaba y ya andaba): se mide LA DECISIÓN, que es lo nuevo.
 *
 * Probala cayendo:
 *   ALEPH_VARA_ROMPER=todopasa   la guardia se reemplaza por una que abre siempre
 *                                → rojo por Finanzas (3 pares de moneda comidos)
 *   ALEPH_VARA_ROMPER=nadapasa   por una que nunca abre → rojo por Educación (213)
 *   ALEPH_VARA_ROMPER=digito     por la regla LITERAL del enunciado («un `$` pegado a
 *                                dígito no abre») → rojo, y dice cuántos math rompe
 *
 *   node qa/verify_dolar_inline.mjs
 *     0 → discrimina · 1 → no discrimina · 2 → no medible (NO cuenta como verde)
 */
import { readFileSync, existsSync } from "node:fs"
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"
import { homedir } from "node:os"
import vm from "node:vm"

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..")
const DESIGN = join(RAIZ, "product", "app", "design")
const ROMPER = (process.env.ALEPH_VARA_ROMPER || "").trim().toLowerCase()

const malas = []
const ok = (n, d) => console.log(`  ✔ ${n}${d ? "  · " + d : ""}`)
const mal = (n, d) => { malas.push(n); console.log(`  ✘ ${n}${d ? "  · " + d : ""}`) }
const noMedible = (m) => { console.log(`[no medible] ${m}`); process.exit(2) }

/* ══ LA FUNCIÓN DE PRODUCCIÓN ══════════════════════════════════════════════════════ */
let guardia = null
try {
  const fuente = readFileSync(join(DESIGN, "render", "sala-render.js"), "utf8")
  const ventana = { renderMathInElement: () => {} }
  const documento = {
    currentScript: null, querySelector: () => null,
    createElement: () => ({ setAttribute() {}, appendChild() {} }),
    head: { appendChild() {} },
  }
  const ctx = vm.createContext({ window: ventana, document: documento, console })
  ctx.globalThis = ctx
  vm.runInContext(fuente, ctx, { filename: "sala-render.js" })
  guardia = ventana.SalaRender && ventana.SalaRender.mathInlineDeDolar
} catch (e) {
  noMedible(`sala-render.js no se pudo evaluar: ${e?.message || e}`)
}
if (typeof guardia !== "function") {
  noMedible("`SalaRender.mathInlineDeDolar` no está expuesta: no hay guardia que medir")
}

// Los mutantes reemplazan LA DECISIÓN, no el arnés: así el rojo dice algo.
const MUTANTES = {
  todopasa: (s) => String(s).replace(/(?<!\$)\$(?!\$)([^$\n]{1,400})\$(?!\$)/g, "\\($1\\)"),
  nadapasa: (s) => String(s),
  // La regla LITERAL del enunciado: además de la guardia, un `$` pegado a dígito no abre.
  digito: (s) => guardia(String(s)).replace(/\\\(([0-9][^)]*?)\\\)/g, "$$$1$$"),
}
const decidir = MUTANTES[ROMPER] || guardia

/* ══ EL CORPUS REAL ════════════════════════════════════════════════════════════════ */
const DB = join(homedir(), "Library", "Application Support", "Aleph", "aleph.db")
if (!existsSync(DB)) noMedible(`no hay aleph.db en esta máquina (${DB})`)

const SEP = "\u001f"
let filas = []
try {
  // Se pide el contenido en base64 para que los saltos de línea del `content` no partan
  // la salida: contar filas por `\n` sobre texto de chat es exactamente el error que ya
  // dejó una vara mintiendo en esta misma tanda.
  const sql =
    "select replace(c.title, char(10), ' '), hex(cast(m.content as blob)) " +
    "from chat_messages m " +
    "join chats c on c.id = m.chat_id where m.role = 'agent' and m.content like '%$%'"
  const salida = execFileSync("sqlite3", ["-readonly", "-separator", SEP, DB, sql],
                              { encoding: "utf8", maxBuffer: 128 * 1024 * 1024 })
  for (const linea of salida.split("\n")) {
    const i = linea.indexOf(SEP)
    if (i < 0) continue
    filas.push({
      chat: linea.slice(0, i),
      texto: Buffer.from(linea.slice(i + 1), "hex").toString("utf8"),
    })
  }
} catch (e) {
  noMedible(`no se pudo leer aleph.db: ${e?.message || e}`)
}
if (!filas.length) noMedible("ningún mensaje de agente con `$` en esta máquina")

/* Los pares `$…$` que HAY en el corpus (fuera de `$$…$$`), por hilo. Es el universo
 * contra el que se juzga: sin él, «0 convertidos» y «no había nada» son indistinguibles. */
const PAR = /(?<!\$)\$(?!\$)([^$\n]{1,400})\$(?!\$)/g
const hay = new Map()
const convertidos = new Map()
const rotos = new Map()
for (const { chat, texto } of filas) {
  const sinDisplay = texto.replace(/\$\$[\s\S]*?\$\$/g, "")
  const pares = [...sinDisplay.matchAll(PAR)]
  if (!pares.length) continue
  hay.set(chat, (hay.get(chat) || 0) + pares.length)
  const salida = decidir(texto)
  const nuevos = (salida.match(/\\\(/g) || []).length
  convertidos.set(chat, (convertidos.get(chat) || 0) + nuevos)
  // ⚠️ LOS EJEMPLOS SE GUARDAN POR HILO. La primera versión los juntaba todos y el rojo
  // de Educación mostraba cadenas de Finanzas como si fueran suyas: un diagnóstico que
  // apunta al hilo equivocado es peor que no dar ejemplos.
  if (nuevos < pares.length) {
    const lista = rotos.get(chat) || []
    for (const p of pares) {
      if (lista.length >= 3) break
      if (!salida.includes("\\(" + p[1] + "\\)")) lista.push(p[1].slice(0, 36))
    }
    rotos.set(chat, lista)
  }
}

console.log("\nEL CORPUS (pares `$…$` reales por hilo, de aleph.db)")
for (const [chat, n] of [...hay.entries()].sort((a, b) => b[1] - a[1])) {
  console.log(`     ${chat.slice(0, 34).padEnd(36)} ${String(n).padStart(4)} pares` +
              `  →  ${String(convertidos.get(chat) || 0).padStart(4)} convertidos`)
}

const EDU = [...hay.keys()].filter((c) => c.startsWith("Educación"))
const FIN = [...hay.keys()].filter((c) => !c.startsWith("Educación"))
const suma = (claves, mapa) => claves.reduce((a, c) => a + (mapa.get(c) || 0), 0)
const eduHay = suma(EDU, hay), eduConv = suma(EDU, convertidos)
const finHay = suma(FIN, hay), finConv = suma(FIN, convertidos)

console.log("\nEL PAR FALSABLE")
if (!eduHay) noMedible("el hilo de Educación no tiene pares `$…$`: no hay disparador")
if (!finHay) noMedible("ningún hilo no-educativo tiene pares `$…$`: falta el contraste")

ok.length  // (no-op: mantiene el linter callado sobre el helper)
if (eduConv === eduHay) {
  ok(`los ${eduHay} pares de Educación se convierten a \\(…\\)`, "math, todos")
} else {
  const ej = EDU.flatMap((c) => rotos.get(c) || [])
  mal(`Educación: ${eduConv} de ${eduHay} convertidos`,
      ej.length ? "se quedaron sin math: " + ej.slice(0, 3).join(" · ") : "")
}
if (finConv === 0) {
  ok(`los ${finHay} pares de moneda quedan como TEXTO`, "«US$ 63.762,69 / ETH: US$» intacto")
} else {
  mal(`moneda comida: ${finConv} de ${finHay} pares se volvieron math`,
      "KaTeX los pintaría en itálica como si fueran una fórmula")
}

/* ══ LOS DOS RENDERERS DICEN LO MISMO ══════════════════════════════════════════════ */
console.log("\nEL MIRROR (la misma decisión en las dos pantallas)")
const INI = "/* ══ EL `$` INLINE, CON GUARDIA"
const FIN_M = "// ══ FIN DEL MIRROR DEL `$` INLINE ══"
const trozo = (archivo) => {
  const s = readFileSync(join(DESIGN, "render", archivo), "utf8")
  const a = s.indexOf(INI), b = s.indexOf(FIN_M)
  if (a < 0 || b < 0) return null
  // Se compara sin indentación: `sala-render.js` vive adentro de un IIFE y `render.js` no.
  return s.slice(a, b).split("\n").map((l) => l.trim()).join("\n").trim()
}
const A = trozo("sala-render.js"), B = trozo("render.js")
if (!A || !B) {
  mal("falta el bloque MIRROR en alguno de los dos renderers",
      `sala-render=${!!A} render=${!!B}`)
} else if (A !== B) {
  mal("los dos renderers ya no dicen lo mismo",
      "el mismo texto se leería distinto según dónde caiga — es el defecto que esto cerró")
} else {
  ok("el bloque es idéntico en sala-render.js y render.js", `${A.length} caracteres`)
}
const crudoPelado = readFileSync(join(DESIGN, "render", "render.js"), "utf8")
  .includes('{ left: "$", right: "$", display: false }')
if (crudoPelado) {
  mal("`render.js` volvió a pasarle el `$` pelado a KaTeX",
      "eso se come la moneda entera, que es de donde salió esta obra")
} else {
  ok("ningún renderer le pasa el `$` pelado a KaTeX", "la decisión es de la guardia")
}

console.log()
if (malas.length) {
  console.log("ROJO — " + malas.join(" · "))
  process.exit(1)
}
console.log("VERDE — discrimina: 213 fórmulas sí, 5 monedas no, y las dos pantallas igual.")
console.log("        Lo que NO dice: cómo se ve. El píxel pide la .app.")
