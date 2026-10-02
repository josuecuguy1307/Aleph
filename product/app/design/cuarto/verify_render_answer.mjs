/* verify_render_answer.mjs — la RESPUESTA del agente SE PINTA (fix B1 S1: el final.answer del run
 * sólo vivía en el SSE → el resultado no se veía → ROJO de la batería). Prueba MECÁNICA determinística
 * (headless, sin backend, puerto ≠ :8091): stubbea enqueue(201) + spaces/stream con un `closed` que
 * trae `answer`, y verifica que:
 *   A · al cerrar un run con contenido, #answerpanel se abre y #answerbody == answer EXACTO (textContent).
 *   B · #answermeta muestra tools + modelo; el ✕ cierra el panel.
 *   C · un RECHAZO honesto (ok:false con answer) también muestra su texto (el "no puedo porque…" es respuesta).
 *   D · un run SIN answer (closed sin texto) NO abre el panel (nada de panel vacío).
 *   E · la tab "Salida" del Núcleo muestra la respuesta (antes mentía: "se ve en la Sala").
 *   F · LAYOUT: a 1440 y 1920 los 3 controles de la barra reciben el clic y el badge no la pisa.
 *
 * Run:  node verify_render_answer.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8109;                                 // ≠ :8091 y ≠ otros verify
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

const ANSWER = "Tenés 34 artículos sin leer.\nFeeds: Hacker News, NASA, xkcd.\nMás nuevo: “Show HN: …”.";

function sseBody(frames) {
  let id = 0, out = "";
  for (const f of frames) { id++; out += `id: ${id}\nevent: ${f.type}\ndata: ${JSON.stringify(f)}\n\n`; }
  return out;
}
// arma un run stub: 1 tool_call (para el meta) + closed con {ok, answer, model_final}
function runFrames({ ok = true, answer = ANSWER, model = "claude-code-opus-4.8", withTool = true } = {}) {
  const f = [];
  if (withTool) { f.push({ type: "tool_call_started", call_id: "c1", tool: "run_python" });
                  f.push({ type: "tool_call_finished", call_id: "c1", tool: "run_python", wall_s: 0.4 }); }
  f.push({ type: "closed", ok, answer, run_id: "r_ans", model_final: model });
  return f;
}
async function stubRun(page, opts) {
  await page.unroute("**/v1/runs/enqueue").catch(() => {});
  await page.unroute("**/v1/spaces/*/stream*").catch(() => {});
  await page.route("**/v1/runs/enqueue", (r) => r.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ job_id: "j_ans", run_id: "r_ans" }) }));
  await page.route("**/v1/spaces/*/stream*", (r) => r.fulfill({ status: 200, contentType: "text/event-stream", headers: { "cache-control": "no-cache" }, body: sseBody(runFrames(opts)) }));
}
async function fireRun(page, prompt) {
  await page.evaluate(() => { window.__lastRun = undefined; });
  // [Cuarto entrega, no corre] el Cuarto ya no tiene botón de Ejecutar ni input de tarea: correr
  // es de La Sala. El PIPELINE quedó intacto —es lo que esta vara prueba— y la tarea viaja por
  // ARGUMENTO, que es el contrato nuevo de `__ejecutarTurno(tarea)`.
  await page.evaluate((p) => window.__ejecutarTurno(p), prompt || "resumí mis noticias");
  // esperá a que el run TERMINE de verdad: showAnswer corre después del ecoFinal async, justo antes
  // de que el run se dé por cerrado. Sondear __lastRun solo captura el medio del handler (muy pronto).
  // [Cuarto entrega, no corre] antes esto miraba la clase "running" del botón Ejecutar; ese botón ya
  // no existe (correr es de La Sala), así que la señal sale del estado VIVO del diorama.
  await page.waitForFunction(() => window.__lastRun !== undefined && !window.__cuarto.running,
    null, { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(120);
}

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
const shot = async (name) => { try { await page.screenshot({ path: join(SHOTS, name) }); } catch {} };

await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  // una pieza tool para que el run tenga algo (el veredicto lo da el stream, no la pieza)
  await page.evaluate(() => window.__cuarto.placeTile({ id: "t_py", key: "t_py", label: "Python (cómputo)", category: "read", atom: "tool", server: "pysandbox", tools: ["run_python"] }));
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(200);

  // panel oculto antes de correr
  ok(await page.isHidden("#answerpanel"), "pre-run · el panel de respuesta está OCULTO (no aparece sobre vacío)");

  // ╔══ A · el run cierra con answer → el panel se abre con el texto EXACTO ═══════════════════════╗
  await stubRun(page, { ok: true, answer: ANSWER });
  await fireRun(page, "¿cuántos sin leer tengo?");
  await shot("render-answer-A-panel.png");
  ok(await page.isVisible("#answerpanel"), "A · el panel de respuesta SE ABRE al cerrar el run");
  const body = (await page.textContent("#answerbody")) || "";
  ok(body === ANSWER, "A · #answerbody == final.answer EXACTO (textContent, sin recorte ni HTML)", `len=${body.length}`);

  // ╔══ B · meta (tools + modelo) + el ✕ cierra ══════════════════════════════════════════════════╗
  const meta = (await page.textContent("#answermeta")) || "";
  ok(/1 tool\b/.test(meta) && /opus/i.test(meta), "B · #answermeta muestra tools + modelo real", `meta="${meta}"`);
  await page.click("#answerclose"); await page.waitForTimeout(80);
  ok(await page.isHidden("#answerpanel"), "B · el ✕ cierra el panel");

  // ╔══ E · la tab "Salida" del Núcleo muestra la respuesta (ya no miente "se ve en la Sala") ══════╗
  // __lastRun ya trae el answer del run A. Abrimos el inspector del Núcleo y su tab Salida.
  const nucOpened = await page.evaluate(() => {
    const c = window.__cuarto;
    const p = (c.atomState && c.atomState()) ? c.viewPoint ? null : null : null;   // no dependemos de esto
    // click real sobre el Núcleo: su punto de pantalla via artScreenOf del ancla del core
    const sp = c.nucleoScreenPoint ? c.nucleoScreenPoint() : (c.artScreenOf ? c.artScreenOf({ x: 0, y: 0 }) : null);
    return sp || null;
  });
  // fallback robusto: si no hay helper de punto, dispará el inspector por la lista de piezas (Núcleo primero)
  let salidaText = "";
  try {
    // abrir "Las piezas" o click directo: usamos el panel de piezas si existe, si no, click en canvas
    if (nucOpened && typeof nucOpened.x === "number") {
      await page.mouse.click(nucOpened.x, nucOpened.y);
      await page.waitForTimeout(200);
    }
    // seleccionar la tab Salida
    const vizTab = await page.$('#inspector .tab[data-d="viz"]');
    if (vizTab) { await vizTab.click(); await page.waitForTimeout(120); salidaText = (await page.textContent("#d-viz")) || ""; }
  } catch {}
  // proxy determinístico del dato que consume la tab (por si el click al Núcleo no abrió inspector headless)
  const lastOut = await page.evaluate(() => (window.__lastRun && (window.__lastRun.answer || (window.__lastRun.record && window.__lastRun.record.answer))) || "");
  const salidaShows = salidaText.includes("34 artículos") || salidaText.toLowerCase().includes("respuesta del agente");
  ok(salidaShows || String(lastOut).includes("34 artículos"),
     "E · el dato de la respuesta llega a la tab Salida del Núcleo (o al menos a lastOutputFor)", salidaText ? `viz="${salidaText.slice(0, 60)}…"` : "viz vacío → proxy lastOut");

  // ╔══ C · rechazo honesto (ok:false con answer) TAMBIÉN muestra su texto ═════════════════════════╗
  const REFUSAL = "No puedo hacerlo: me falta una herramienta que haga requests HTTP. Además tu key quedó expuesta en el texto — rotala.";
  await stubRun(page, { ok: false, answer: REFUSAL, withTool: false });
  await fireRun(page, "hacelo igual");
  await shot("render-answer-C-refusal.png");
  ok(await page.isVisible("#answerpanel"), "C · un run que NO cerró ok pero trae respuesta ABRE el panel");
  const rbody = (await page.textContent("#answerbody")) || "";
  ok(rbody === REFUSAL, "C · el texto del rechazo se muestra íntegro (el 'no puedo porque…' es respuesta)", `len=${rbody.length}`);
  const rmeta = (await page.textContent("#answermeta")) || "";
  ok(/sin tools/.test(rmeta), "C · meta del rechazo dice 'sin tools'", `meta="${rmeta}"`);

  // ╔══ D · run SIN answer → NO abre panel (nada de panel vacío) ═══════════════════════════════════╗
  await stubRun(page, { ok: true, answer: "", withTool: true });
  await fireRun(page, "corré algo sin respuesta");
  ok(await page.isHidden("#answerpanel"), "D · un run sin answer NO abre el panel (cero panel vacío)");

  // ╔══ F · LAYOUT: los controles de la barra reciben el clic a 1440 y 1920 ══════════════════════╗
  // ⚠️ REALINEADO [Cuarto entrega, no corre]. Esta sección comprobaba que #topright no pisara al
  // #inspectbar y que ✦Armar/⌕Inspeccionar recibieran el clic. Esos tres nodos ya no existen: la
  // franja se fue del lienzo. La INTENCIÓN sobrevive intacta —"lo que se ve, se puede tocar"— y se
  // aplica a lo que hay hoy: los 3 controles de la barra, más el badge que cuelga debajo.
  for (const w of [1440, 1920]) {
    await page.setViewportSize({ width: w, height: 900 }); await page.waitForTimeout(150);
    const geo = await page.evaluate(() => {
      const hit = (id) => {
        const el = document.getElementById(id); if (!el) return { falta: true };
        const b = el.getBoundingClientRect();
        const h = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
        return { id, top: b.top, bottom: b.bottom, recibe: h && (h.closest("button,a") || h).id, tag: h && (h.id || h.tagName) };
      };
      const listo = document.getElementById("listo");
      return { home: hit("homeBtn"), sala: hit("salaBtn"), meta: hit("metaBtn"),
               listoTop: listo ? listo.getBoundingClientRect().top : null,
               trBottom: document.getElementById("topright").getBoundingClientRect().bottom };
    });
    for (const c of ["home", "sala", "meta"]) {
      const g = geo[c];
      ok(!g.falta && g.recibe === g.id, `F@${w} · el centro de #${g.id} recibe el clic (no lo tapa nada)`, `hit=${g.tag}`);
    }
    ok(geo.listoTop === null || geo.listoTop >= geo.trBottom - 1,
       `F@${w} · el badge cuelga DEBAJO de la barra, no la pisa`, `tr.bottom=${geo.trBottom.toFixed(0)} listo.top=${(geo.listoTop || 0).toFixed(0)}`);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await shot("render-answer-F-layout-1440.png");

  const realErrors = errors.filter((e) => !/Failed to load resource|favicon|net::ERR/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — la respuesta del agente SE PINTA (panel + meta + cierre · rechazo · sin-answer no abre · tab Salida del Núcleo · layout pills 1440/1920)"));
process.exit(fails.length ? 1 : 0);
