/* verify_math_en_el_chat.mjs — EL MATH DEL MODELO, EN LA BURBUJA DEL CHAT.
 *
 * [Educación · los artefactos]
 *
 * EL DEFECTO, MEDIDO SOBRE `aleph.db` ANTES DE ESCRIBIR UNA LÍNEA. El hilo de Educación
 * tiene 24 respuestas del tutor y traen **38 bloques `$$…$$`** (más 213 `$…$` inline, que
 * quedan fuera por la decisión sellada de delimitadores). Ninguno se pintaba: un tutor de
 * matemática entregando `\lim_{h \to 0}\frac{f(x+h)-f(x)}{h}` a la vista, mientras la
 * MISMA pantalla, del otro lado, pinta las obras con KaTeX.
 *
 * Y NO FALTABA EL MECANISMO: `sala-render.js` tiene `runKatex` desde siempre y los
 * renderers de obra lo llaman (`informe`, `dashboard`, `documento`). Lo que faltaba era la
 * puerta — no estaba en `window.SalaRender` — y los dos llamadores del chat
 * (`sala-v2/ui/hilo.js`, `chat/aleph-chat.js`), que ya llamaban a sus dos hermanos
 * (`renderInlineFigures`, `highlightIn`) y no a éste.
 *
 * ── QUÉ MIDE, Y QUÉ NO ───────────────────────────────────────────────────────────────
 *
 * A · MEDIDO, CORRIENDO EL MÓDULO DE PRODUCCIÓN. `sala-render.js` se ejecuta de verdad en
 *     un `vm` con un `window` mínimo; después se le pide `SalaRender.runKatex(nodo)` con
 *     un espía en `window.renderMathInElement`. O sea: se mide que la llamada LLEGUE a
 *     KaTeX, con ESE nodo, y con la lista de delimitadores de la casa — no que exista una
 *     función con ese nombre.
 *
 * B · MEDIDO, SOBRE EL CORPUS REAL. Si `aleph.db` está en esta máquina, se cuenta cuántos
 *     `$$…$$` hay de verdad en los hilos de workspace. Es la guarda contra medir un
 *     disparador que no existe: sin corpus esta mitad sale **[no medible]**, no verde.
 *
 * C · LEÍDO, Y SE DICE. Que los dos llamadores del chat nombren `runKatex` sale de LEER
 *     sus fuentes, no de correrlas: `hilo.js` importa el bundle de assistant-ui y
 *     `enhanceLast` vive dentro de un closure, así que en Node no hay forma de dispararlos
 *     sin fabricar un DOM — y un DOM fabricado mediría el DOM fabricado. Es falsable
 *     (borrar la llamada la pone roja) pero NO prueba el píxel. El píxel se mira en
 *     pantalla contra la .app instalada, y esta vara no autoriza a decir que se miró.
 *
 * Probala cayendo:
 *   ALEPH_VARA_ROMPER=sinexport    `SalaRender.runKatex` no se expone      → rojo en A
 *   ALEPH_VARA_ROMPER=sinllamador  se ignora la llamada de los dos chats   → rojo en C
 *
 *   node qa/verify_math_en_el_chat.mjs
 *     0 → el math del modelo llega pintado · 1 → no llega · 2 → no se pudo medir
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
const ok = (n, d) => console.log(`  ✅  ${n}${d ? " — " + d : ""}`)
const mal = (n, d) => { malas.push(n); console.log(`  ❌  ${n}${d ? " — " + d : ""}`) }
const noMedible = (motivo) => { console.log(`[no medible] ${motivo}`); process.exit(2) }

/* ══ A · EL MÓDULO DE PRODUCCIÓN, CORRIDO ═══════════════════════════════════════════ */
console.log("\nA · la puerta existe y la llamada LLEGA a KaTeX (módulo de producción, corrido)")

let SalaRender = null
const llamadas = []
try {
  const fuente = readFileSync(join(DESIGN, "render", "sala-render.js"), "utf8")
  // El `window` mínimo que el archivo necesita para evaluarse. `document.currentScript`
  // ausente es un caso que el propio archivo contempla (cae al `../vendor/` relativo).
  const ventana = {
    // EL ESPÍA. Es lo que vuelve MEDIBLE a `runKatex`: si la función existe pero no llama
    // a KaTeX, o llama con otro nodo, esto queda vacío y la vara se pone roja.
    renderMathInElement: (el, opciones) => { llamadas.push({ el, opciones }) },
  }
  const documento = {
    currentScript: null,
    querySelector: () => null,
    createElement: () => ({ setAttribute() {}, appendChild() {} }),
    head: { appendChild() {} },
  }
  const contexto = vm.createContext({ window: ventana, document: documento, console })
  contexto.globalThis = contexto
  vm.runInContext(fuente, contexto, { filename: "sala-render.js" })
  SalaRender = ventana.SalaRender || null
} catch (e) {
  noMedible(`sala-render.js no se pudo evaluar: ${e?.message || e}`)
}

if (!SalaRender) noMedible("sala-render.js corrió y no dejó `window.SalaRender`")

const puerta = ROMPER === "sinexport" ? undefined : SalaRender.runKatex
if (typeof puerta !== "function") {
  mal("`SalaRender.runKatex` no está expuesto",
      "el chat no tiene forma de pedir el math sin duplicar el motor")
} else {
  const nodo = { __soy: "la burbuja" }
  puerta(nodo)
  if (llamadas.length !== 1) {
    mal("la llamada no llegó a KaTeX", `${llamadas.length} llamada/s a renderMathInElement`)
  } else if (llamadas[0].el !== nodo) {
    mal("KaTeX recibió otro nodo", "el math se pintaría fuera de la burbuja")
  } else {
    const izq = (llamadas[0].opciones?.delimiters || []).map((d) => d.left)
    // La MISMA lista que usan las obras: una decisión, un lugar. Si el chat empezara a
    // traer su propia lista, el mismo texto se leería distinto según dónde caiga — que es
    // exactamente el defecto que esta obra viene a cerrar, con los papeles cambiados.
    const esperados = ["$$", "\\[", "\\("]
    const falta = esperados.filter((d) => !izq.includes(d))
    if (falta.length) mal("delimitadores incompletos", `faltan ${falta.join(" ")}`)
    else ok("runKatex llega a KaTeX con la burbuja", `delimitadores ${izq.join(" ")}`)
    // La decisión sellada: el `$` solo NO entra (moneda en los informes financieros).
    // Se afirma para que prenderlo sea una decisión y no un descuido de alguien.
    if (izq.includes("$")) {
      mal("el `$` solo entró sin decisión",
          "en el chat de Finanzas se come «US$ 63.762,69 / ETH: US$» — 3 casos medidos")
    } else {
      ok("el `$` solo sigue afuera", "decisión sellada, con sus dos puntas medidas")
    }
  }
}

/* ══ B · EL DISPARADOR EXISTE EN EL CORPUS REAL ═════════════════════════════════════ */
console.log("\nB · ¿hay math de verdad en los hilos? (corpus real, no una suposición)")

const DB = join(homedir(), "Library", "Application Support", "Aleph", "aleph.db")
if (!existsSync(DB)) {
  console.log(`  ⚠️  [no medible] no hay aleph.db en esta máquina (${DB})`)
  console.log("      La mitad A sigue valiendo; ésta NO cuenta como verde.")
} else {
  try {
    // ⚠️ EL CONTEO VA EN SQL, NO EN JS. Un `content` de chat tiene saltos de línea
    // adentro, así que partir la salida de sqlite3 por `\n` cuenta cualquier cosa: la
    // primera versión de esta vara hacía eso y dijo «no medible» sobre una DB que tenía
    // 38 bloques. Contando en SQL, una fila de salida es una fila de verdad.
    const CUENTA = "((length(m.content) - length(replace(m.content, '$$', ''))) / 2) / 2"
    const sql =
      `select replace(c.title, char(10), ' '), sum(${CUENTA}) ` +
      "from chat_messages m join chats c on c.id = m.chat_id " +
      `where m.role = 'agent' group by 1 having sum(${CUENTA}) > 0`
    // ⚠️ `sqlite3 -readonly` y un `select`: esta vara NO escribe en la DB REAL. Es la
    // lección de `qa/suite_instalada.mjs`, que sí escribía.
    const SEP = "\u001f"
    const salida = execFileSync("sqlite3", ["-readonly", "-separator", SEP, DB, sql],
                                { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 })
    const porHilo = new Map()
    for (const fila of salida.split("\n")) {
      const i = fila.indexOf(SEP)
      if (i < 0) continue
      const n = parseInt(fila.slice(i + 1), 10)
      if (n > 0) porHilo.set(fila.slice(0, i) || "(sin título)", n)
    }
    const total = [...porHilo.values()].reduce((a, b) => a + b, 0)
    if (!total) {
      console.log("  ⚠️  [no medible] ningún hilo de esta máquina trae `$$…$$`: " +
                  "el disparador no está presente, así que acá no hay verde ni rojo.")
    } else {
      const detalle = [...porHilo.entries()].sort((a, b) => b[1] - a[1])
        .map(([t, n]) => `${t} ${n}`).join(" · ")
      ok(`${total} bloques \`$$…$$\` esperando pintarse`, detalle)
    }
  } catch (e) {
    console.log(`  ⚠️  [no medible] no se pudo leer aleph.db: ${e?.message || e}`)
  }
}

/* ══ C · LOS DOS LLAMADORES (LEÍDO, y se dice) ══════════════════════════════════════ */
console.log("\nC · los dos chats piden el math [LEÍDO de la fuente, no corrido]")

const SUPERFICIES = [
  { que: "sala-v2/ui/hilo.js", ruta: join(DESIGN, "sala-v2", "ui", "hilo.js") },
  { que: "chat/aleph-chat.js", ruta: join(DESIGN, "chat", "aleph-chat.js") },
]
for (const s of SUPERFICIES) {
  let fuente = ""
  try { fuente = readFileSync(s.ruta, "utf8") } catch (e) {
    mal(s.que, `no se pudo leer: ${e?.message || e}`); continue
  }
  if (ROMPER === "sinllamador") fuente = fuente.split("runKatex").join("noLlamaANadie")
  // Los tres hermanos van juntos: el que pinta texto del modelo los quiere a los tres.
  const falta = ["renderInlineFigures", "highlightIn", "runKatex"]
    .filter((n) => !fuente.includes(`.${n}(`))
  if (falta.length) mal(s.que, `no pide ${falta.join(", ")}`)
  else ok(s.que, "pide figuras, highlight y math")
}

console.log()
if (malas.length) {
  console.log(`ROJO — ${malas.join(" · ")}`)
  process.exit(1)
}
console.log("VERDE — la puerta está abierta y los dos chats la tocan.")
console.log("        Lo que esta vara NO dice: cómo se ve en pantalla. Eso pide la .app.")
