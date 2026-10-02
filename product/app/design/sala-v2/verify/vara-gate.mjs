/* vara-gate.mjs — LA TARJETA DE CONSENTIMIENTO, CON UN GATE DE VERDAD.
 *
 * `vara.mjs` corre un turno con `calc`, que es lectura pura y NO dispara el gate. Ésta corre
 * uno con `datatools.write_csv` y la perilla de autonomía en `manual`, que es una acción de
 * clase `write-world`: el gate la RETIENE server-side y el turno queda esperando a la
 * persona. Es el único camino honesto para probar el consentimiento — un gate simulado
 * probaría la simulación.
 *
 * Matriz:
 *   1. La tarjeta aparece EN EL HILO (no en un modal aparte).
 *   2. Dice lo que el backend dice — el copy sale de `gate_ux`, no de la pantalla.
 *   3. UNA sola tarjeta: el `gate_waiting` vivo y el `held_action` del cierre son el MISMO
 *      gate y tienen que colapsar en la misma firma.
 *   4. Fail-closed: sin `approval_id` los botones NO son operables, y dicen por qué.
 *   5. Al llegar el `approval_id`, se vuelve operable.
 *   6. Autorizar hace un POST REAL a /v1/runs/{id}/approve y el backend lo acepta.
 *
 * Uso:  BASE=http://127.0.0.1:8261 node vara-gate.mjs
 */
import { webkit } from "playwright";

const BASE = process.env.BASE || "http://127.0.0.1:8261";
const BRAIN = process.env.BRAIN || "http://127.0.0.1:8927/v1";
const PAGE = `${BASE}/sala-v2/sala-v2.html?v2=1`;
const PROMPT =
  "Escribí un archivo CSV llamado datos.csv con dos filas: a,1 y b,2. Usá la herramienta de datatools.";

const fails = [];
const ok = (n, d) => console.log(`  ✅ ${n}${d ? " — " + d : ""}`);
const bad = (n, d) => {
  fails.push(`${n}${d ? " — " + d : ""}`);
  console.log(`  ❌ ${n}${d ? " — " + d : ""}`);
};

const CUENTA = { email: `vara-gate-${Date.now()}@example.com`, password: "vara-gate-2026" };
let USUARIO = null;
for (const ruta of ["/v1/auth/register", "/v1/auth/login"]) {
  const r = await fetch(BASE + ruta, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(CUENTA),
  });
  if (!r.ok) continue;
  const j = await r.json().catch(() => null);
  if (j?.session_token) {
    USUARIO = j;
    break;
  }
}
console.log(USUARIO ? `\n· sesión real: ${USUARIO.id}` : "\n· ⚠ sin sesión");

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errores = [];
page.on("pageerror", (e) => errores.push(String(e && e.message)));
// El POST de aprobación se observa a nivel red: que la pantalla diga «listo» no prueba que
// el backend lo haya recibido.
const approves = [];
page.on("response", (r) => {
  if (/\/v1\/runs\/[^/]+\/approve$/.test(r.url())) approves.push({ status: r.status(), url: r.url() });
});

if (USUARIO) {
  await page.addInitScript((u) => localStorage.setItem("puppet_user", JSON.stringify(u)), USUARIO);
}
await page.goto(PAGE, { waitUntil: "load" });
await page.waitForSelector(".sv-composer textarea", { timeout: 20000 });

await page.evaluate(
  ({ brain }) => {
    window.__salaV2.recetaDePrueba = {
      schema_version: "v1",
      meta: { name: "vara-gate", nicho: "test" },
      model: {
        primary: "claude-code-cli",
        base_url: brain,
        brain_provider: "claude_cli",
        cli_model: "sonnet",
        effort: "low",
        max_tokens: 400,
        temperature: 0,
        max_turns: 4,
      },
      belt: {
        belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
        tool_filters: { datatools: ["write_csv"], calc: ["add"] },
      },
      rag: { enabled: false },
      keys: {},
      // La perilla que fuerza el gate. Es un candado de RUNTIME dentro del gate: la receta
      // no puede bajarlo, sólo subirlo.
      autonomy: "manual",
    };
    window.__varaGates = [];
    window.__varaCrudos = [];
    // OBSERVADOR, NO FOTO.
    // El freeze (tarjeta visible, botones NO operables) dura desde el `gate_waiting` vivo
    // hasta que llega el `approval_id`. Con un run rápido esa ventana se cierra antes de
    // que un `page.evaluate` alcance a mirar, y la vara daba rojo por medir tarde — no
    // porque el producto fallara. Un observador registra TODAS las transiciones y después
    // se afirma sobre la secuencia, que es un hecho y no un instante.
    window.__varaBoton = [];
    const anotar = () => {
      const b = document.querySelector(".sv-gate .sv-btn.primario");
      if (!b) return;
      const s = { disabled: !!b.disabled, title: b.getAttribute("title") || "", texto: b.innerText };
      const ult = window.__varaBoton.at(-1);
      if (!ult || ult.disabled !== s.disabled || ult.title !== s.title) window.__varaBoton.push(s);
    };
    new MutationObserver(anotar).observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
    });
    window.__salaV2.onAlephEspia = (a) => {
      if (a.nombre === "aleph.gate_waiting") window.__varaGates.push({ ...a.valor, t: performance.now() });
    };
    window.__salaV2.onEventoEspia = (e) => window.__varaCrudos.push(e.type);
  },
  { brain: BRAIN },
);

console.log("\n1 · la tarjeta aparece en el hilo");
const caja = await page.$(".sv-composer textarea");
await caja.click();
await page.keyboard.type(PROMPT);
await page.keyboard.press("Enter");

const aparecio = await page
  .waitForSelector(".sv-thread .sv-gate", { timeout: 120000 })
  .then(() => true)
  .catch(() => false);
aparecio ? ok("la tarjeta está DENTRO del hilo") : bad("la tarjeta nunca apareció en el hilo");


console.log("\n2 · dice lo que dice el backend");
const texto = await page.evaluate(() => document.querySelector(".sv-gate")?.innerText || "");
const delBackend = await page.evaluate(() => {
  const g = (window.__varaGates || []).find((x) => x.ux);
  return g?.ux || null;
});
if (!delBackend) bad("no llegó el payload gate_ux del backend");
else {
  const frases = [delBackend.que_va_a_hacer, delBackend.vista_previa, delBackend.leyenda].filter(Boolean);
  const pintadas = frases.filter((f) => texto.includes(f));
  pintadas.length === frases.length
    ? ok(`las ${frases.length} frases del backend están en la tarjeta`)
    : bad(`sólo ${pintadas.length}/${frases.length} frases del backend`, texto.slice(0, 140));
  const botOk = await page.evaluate(() => document.querySelector(".sv-gate .sv-btn.primario")?.innerText || "");
  botOk.trim() === (delBackend.boton_ok || "").trim()
    ? ok(`el botón usa el copy del backend: “${botOk.trim()}”`)
    : bad("el botón NO usa el copy del backend", `pantalla=“${botOk.trim()}” backend=“${delBackend.boton_ok}”`);
}

console.log("\n3 · fail-closed mientras no hay approval_id");
{
  // Se afirma sobre la SECUENCIA registrada por el observador y sobre los eventos, no
  // sobre una foto: el freeze es un tramo, no un instante.
  const trans = await page.evaluate(() => window.__varaBoton || []);
  const primerGate = await page.evaluate(() => (window.__varaGates || [])[0] || null);
  console.log(`     transiciones del botón: ${JSON.stringify(trans)}`);
  primerGate && !primerGate.approval_id
    ? ok("el primer gate llegó SIN approval_id (freeze real)")
    : bad("el primer gate ya traía approval_id", JSON.stringify(primerGate));
  const congelado = trans.find((t) => t.disabled);
  congelado
    ? ok("hubo un tramo con los botones NO operables")
    : bad("los botones nunca estuvieron bloqueados");
  congelado?.title
    ? ok("y decían por qué", congelado.title)
    : bad("botón apagado y MUDO — la ley 4 lo prohíbe");
}

// Esperar al cierre del run, que es cuando llega el approval_id.
await page
  .waitForFunction(() => (window.__varaCrudos || []).some((t) => t === "RUN_FINISHED" || t === "RUN_ERROR"), {
    timeout: 120000,
    polling: 200,
  })
  .catch(() => {});
await page.waitForTimeout(500);

console.log("\n4 · una sola tarjeta, no dos");
const cuantas = await page.$$eval(".sv-gate", (ns) => ns.length);
const firmas = await page.evaluate(() => [...new Set((window.__varaGates || []).map((g) => g.sig))]);
cuantas === 1
  ? ok("hay exactamente 1 tarjeta")
  : bad(`hay ${cuantas} tarjetas`, "el freeze y la retenida no colapsaron en la misma firma");
firmas.length === 1
  ? ok(`una sola firma: ${firmas[0]}`)
  : bad(`${firmas.length} firmas distintas`, firmas.join(" · "));

console.log("\n5 · se vuelve operable cuando llega el approval_id");
const operable = await page.evaluate(() => {
  const b = document.querySelector(".sv-gate .sv-btn.primario");
  return { disabled: !!b?.disabled, conId: (window.__varaGates || []).some((g) => g.approval_id) };
});
operable.conId ? ok("llegó el approval_id") : bad("nunca llegó el approval_id");
!operable.disabled ? ok("los botones quedaron operables") : bad("la tarjeta nunca llegó a operable");

console.log("\n6 · autorizar llega al backend de verdad");
if (operable.disabled) bad("no se pudo probar: la tarjeta no era operable");
else {
  await page.click(".sv-gate .sv-btn.primario");
  await page
    .waitForFunction(() => !!document.querySelector(".sv-gate-hecho"), { timeout: 30000, polling: 150 })
    .catch(() => {});
  approves.length
    ? ok(`POST /v1/runs/{id}/approve → ${approves.map((a) => a.status).join(", ")}`)
    : bad("la pantalla no hizo NINGÚN POST de aprobación");
  const acepto = approves.some((a) => a.status >= 200 && a.status < 300);
  acepto ? ok("el backend lo aceptó") : bad("el backend NO lo aceptó", JSON.stringify(approves));
  const cerro = await page.evaluate(() => document.querySelector(".sv-gate-hecho")?.innerText || "");
  cerro ? ok(`la tarjeta se cerró: “${cerro}”`) : bad("la tarjeta no cambió tras autorizar");
}

if (!errores.length) ok("cero pageerror");
else bad(`${errores.length} pageerror`, errores.slice(0, 2).join(" | "));

await browser.close();

console.log("\n" + "─".repeat(64));
if (fails.length) {
  console.log(`VARA GATE: ${fails.length} ROJAS`);
  for (const f of fails) console.log("  · " + f);
  process.exit(1);
}
console.log("VARA GATE: todo verde");
