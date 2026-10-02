/* vara.mjs — LA VARA DE LA FASE 1.
 *
 * Un turno REAL en la pantalla REAL contra el backend REAL. Nada de mocks: el cerebro es el
 * `claude` del humano vía el shim BYO-CLI, la tool es `calc` de verdad, y el navegador es
 * el que corre la Sala nueva.
 *
 * Matriz:
 *   1. Turno real  — se escribe, se envía, el hilo pinta la respuesta del modelo.
 *   2. ≤5 s        — el primer signo de vida en pantalla llega antes de 5 s.
 *   3. Estados     — la línea de estado pasa por los estados que corresponden, y **en el
 *                    orden en que ocurrieron**, sin mezclarse con el texto del modelo.
 *   4. Tool real   — la herramienta aparece en el hilo con su veredicto real.
 *   5. Anti-grift  — `model_final` real · `tool_calls > 0` · `degraded == null`.
 *                    Los tres salen de eventos del backend, no de lo que la pantalla dice.
 *   6. Restaurar   — recargar la pantalla devuelve el hilo (el historial no se pierde).
 *
 * NO cubre el punto «sobre la .app instalada»: eso necesita el build del sidecar congelado
 * y del Tauri, y se declara aparte en el reporte. Esta vara corre contra el MISMO código,
 * servido por el MISMO backend, en el mismo navegador — lo que no prueba es el empaquetado.
 *
 * Uso:  BASE=http://127.0.0.1:8261 node vara.mjs
 */
import { webkit } from "playwright";

const BASE = process.env.BASE || "http://127.0.0.1:8261";
const BRAIN = process.env.BRAIN || "http://127.0.0.1:8927/v1";
const PAGE = `${BASE}/sala-v2/sala-v2.html?v2=1`;
const PROMPT = "Sumá 2 más 3 usando la herramienta calc y decime el resultado.";

const fails = [];
const ok = (n, d) => console.log(`  ✅ ${n}${d ? " — " + d : ""}`);
const bad = (n, d) => {
  fails.push(`${n}${d ? " — " + d : ""}`);
  console.log(`  ❌ ${n}${d ? " — " + d : ""}`);
};

// ── una cuenta REAL, porque el hilo pertenece a la cuenta ────────────────────────────
// `chats.user_id` es NOT NULL (migración 0007): sin sesión el backend corre el turno pero
// NO lo registra, y entonces medir «¿sobrevive a la recarga?» no mide nada. La cuenta es
// desechable y vive en el datadir aislado del arnés.
const CUENTA = { email: `vara-f1-${Date.now()}@example.com`, password: "vara-fase1-2026" };
async function sesion() {
  for (const ruta of ["/v1/auth/register", "/v1/auth/login"]) {
    const r = await fetch(BASE + ruta, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(CUENTA),
    });
    if (!r.ok) continue;
    const j = await r.json().catch(() => null);
    if (j?.id && j?.session_token) return j;
  }
  return null;
}
const USUARIO = await sesion();
console.log(USUARIO ? `\n· sesión real: ${USUARIO.id}` : "\n· ⚠ sin sesión — el hilo no se va a registrar");

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errores = [];
page.on("pageerror", (e) => errores.push({ msg: String(e && e.message), stack: String(e && e.stack || "").split("\n").slice(0,4).join(" | "), fase: FASE.v }));
const FASE = { v: "carga" };

// La sesión se siembra ANTES de que corra un script de la página: `auth.js` la lee de
// `localStorage` al arrancar, igual que en producción.
if (USUARIO) {
  await page.addInitScript((u) => {
    localStorage.setItem("puppet_user", JSON.stringify(u));
  }, USUARIO);
}

await page.goto(PAGE, { waitUntil: "load" });
await page.waitForSelector(".sv-composer textarea", { timeout: 20000 });

// La receta del turno se inyecta por el seam público de la pantalla: sala-v2 la toma de
// `/v1/puppets/{id}` cuando hay agente guardado, y acá no queremos crear uno sólo para
// medir. El adaptador es el mismo; lo único que cambia es de dónde sale la receta.
await page.evaluate(
  ({ brain }) => {
    window.__salaV2.recetaDePrueba = {
      schema_version: "v1",
      meta: { name: "vara-fase1", nicho: "test" },
      model: {
        primary: "claude-code-cli",
        base_url: brain,
        brain_provider: "claude_cli",
        cli_model: "sonnet",
        effort: "low",
        max_tokens: 300,
        temperature: 0,
        max_turns: 4,
      },
      belt: {
        belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
        tool_filters: { calc: ["add"] },
      },
      rag: { enabled: false },
      keys: {},
    };
    // Registro de TODO lo que el adaptador manda por el canal lateral: la vara mide sobre
    // eventos reales, no sobre pixeles que podrían venir de cualquier lado.
    window.__varaEventos = [];
    window.__varaEstados = [];
    window.__varaCrudos = [];
    const orig = window.__salaV2.onAlephEspia;
    window.__salaV2.onAlephEspia = (a) => {
      window.__varaEventos.push({ ...a, t: performance.now() });
      orig?.(a);
    };
    window.__salaV2.onEventoEspia = (e) => window.__varaCrudos.push(e.type);
    window.__salaV2.onEstadoEspia = (e) =>
      window.__varaEstados.push({ estado: e.estado, texto: e.texto, t: performance.now() });
    window.__varaT0 = performance.now();
  },
  { brain: BRAIN },
);

FASE.v = "turno";
console.log("\n1 · turno real");
const caja = await page.$(".sv-composer textarea");
await caja.click();
await page.keyboard.type(PROMPT);
await page.evaluate(() => (window.__varaT0 = performance.now()));
await page.keyboard.press("Enter");

// Espera al CIERRE REAL del turno: `RUN_FINISHED`/`RUN_ERROR` de AG-UI.
//
// Antes esperaba al primer `aleph.veredicto` y medía demasiado pronto: el `veredicto` sale
// con el `final` del espinazo, y el TEXTO del modelo se emite DESPUÉS. La vara daba roja
// «el hilo no muestra la respuesta» sobre un hilo que sí la mostraba medio segundo más
// tarde. Medir el final por un evento intermedio es medir otra cosa.
const cerrado = await page
  .waitForFunction(
    () => (window.__varaCrudos || []).some((t) => t === "RUN_FINISHED" || t === "RUN_ERROR"),
    { timeout: 120000, polling: 200 },
  )
  .then(() => true)
  .catch(() => false);
// Un tick para que React pinte lo último antes de leer el DOM.
await page.waitForTimeout(400);

const datos = await page.evaluate(() => ({
  eventos: window.__varaEventos || [],
  estados: window.__varaEstados || [],
  t0: window.__varaT0,
  textoHilo: document.querySelector(".sv-thread")?.innerText || "",
  tools: [...document.querySelectorAll(".sv-tool")].map((n) => n.innerText),
}));

cerrado ? ok("el turno cerró") : bad("el turno no cerró en 120 s");
const respuesta = /\b5\b/.test(datos.textoHilo);
respuesta
  ? ok("el hilo pintó la respuesta del modelo")
  : bad("el hilo no muestra la respuesta", datos.textoHilo.slice(0, 160));

console.log("\n2 · ≤5 s al primer signo de vida");
const primero = datos.eventos.find((e) =>
  ["aleph.costo", "aleph.tool_inicio", "aleph.paso"].includes(e.nombre),
);
const primerEstado = datos.estados.find((e) => e.estado !== "quieto");
const tSigno = primero ? Math.round(primero.t - datos.t0) : null;
const tEstado = primerEstado ? Math.round(primerEstado.t - datos.t0) : null;
if (tSigno == null) bad("no hubo un solo evento en vivo");
else if (tSigno <= 5000) ok(`primer evento en vivo a ${tSigno} ms`);
else bad(`primer evento en vivo a ${tSigno} ms`, "supera los 5 s");
if (tEstado != null && tEstado <= 5000) ok(`la línea de estado se encendió a ${tEstado} ms`);
else bad("la línea de estado no se encendió a tiempo", String(tEstado));

console.log("\n3 · estados en vivo, en orden");
const orden = datos.estados.map((e) => e.estado);
const secuencia = orden.filter((e, i) => e !== orden[i - 1]);
console.log(`     secuencia: ${secuencia.join(" → ") || "(ninguna)"}`);
const esperados = ["pensando", "preparando", "ejecutando", "recibiendo"];
const presentes = esperados.filter((e) => secuencia.includes(e));
presentes.length >= 3
  ? ok(`${presentes.length}/4 estados de tool presentes`, presentes.join(", "))
  : bad(`sólo ${presentes.length}/4 estados`, presentes.join(", ") || "ninguno");
// El orden importa: preparando NUNCA puede venir después de recibiendo.
const iPrep = secuencia.indexOf("preparando");
const iRec = secuencia.indexOf("recibiendo");
if (iPrep === -1 || iRec === -1 || iPrep < iRec) ok("el orden es coherente");
else bad("los estados salieron desordenados", secuencia.join(" → "));

console.log("\n4 · herramienta real en el hilo");
const evTool = datos.eventos.filter((e) => e.nombre === "aleph.tool_meta");
evTool.length ? ok(`${evTool.length} tool(s) con veredicto`, evTool.map((e) => `${e.valor.nombre}=${e.valor.status}`).join(" · ")) : bad("ninguna tool llegó al hilo");
datos.tools.length ? ok(`${datos.tools.length} tool(s) pintadas`, datos.tools.join(" | ").slice(0, 120)) : bad("la tool no se pintó en el hilo");

console.log("\n5 · anti-grift (sobre eventos del backend, no sobre la pantalla)");
const ver = datos.eventos.filter((e) => e.nombre === "aleph.veredicto").map((e) => e.valor);
const v = ver.find((x) => x.model_final) || ver.at(-1) || {};
v.model_final ? ok(`model_final real: ${v.model_final}`) : bad("model_final vacío", JSON.stringify(v));
evTool.length > 0 ? ok(`tool_calls = ${evTool.length} (> 0)`) : bad("tool_calls = 0");
v.degraded == null ? ok("degraded = null") : bad("degraded no es null", String(v.degraded));
v.ok === true ? ok("ok = true") : bad("ok no es true", String(v.ok));

FASE.v = "recarga";
console.log("\n6 · el hilo se restaura al recargar");
const chatId = await page.evaluate(() => window.__salaV2?.chatIdActual || null);
await page.reload({ waitUntil: "load" });
await page.waitForSelector(".sv-composer textarea", { timeout: 20000 });
const hilosTrasRecarga = await page.evaluate(
  () => [...document.querySelectorAll(".sv-hilo")].map((n) => n.innerText).filter((t) => !t.startsWith("＋")),
);
hilosTrasRecarga.length
  ? ok(`${hilosTrasRecarga.length} hilo(s) en el menú tras recargar`, hilosTrasRecarga.slice(0, 2).join(" | "))
  : bad("no quedó ningún hilo tras recargar", `chat_id=${chatId}`);

if (!errores.length) ok("cero pageerror en todo el turno");
else bad(`${errores.length} pageerror`, errores.map((e) => `[${e.fase}] ${e.msg} @ ${e.stack}`).join(" ||| "));

await browser.close();

console.log("\n" + "─".repeat(64));
if (fails.length) {
  console.log(`VARA FASE 1: ${fails.length} ROJAS`);
  for (const f of fails) console.log("  · " + f);
  process.exit(1);
}
console.log("VARA FASE 1: todo verde");
