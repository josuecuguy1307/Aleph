/* verify_p9_linea.mjs — LA VARA DE LA LÍNEA DE RAZONAMIENTO + LOG (FIX-P9).
 *
 * WebKit real (el motor de WKWebView, el mismo de la .app) contra el SIDECAR FROZEN DE ESTE
 * ÁRBOL, en puerto propio :8280, con datadir aislado. El backend, la DB SQLite, el Cuarto y
 * La Sala son los que sirve el binario — no el árbol.
 *
 *   node product/app/design/chat/verify_p9_linea.mjs
 *
 * ── QUÉ SE SCRIPTEA, Y POR QUÉ ──────────────────────────────────────────────────────
 * DOS cosas, las dos declaradas:
 *   · `/v1/cuarto/guide` (el cerebro del Guía). Un modelo no es determinista y una vara con
 *     un modelo adentro no mide el producto: mide la suerte del día. Lo que se mide es lo
 *     que el producto hace con cada forma de turno.
 *   · `/v1/puppets/run` en §6. El CONTRATO DE BACKEND de `client_tools` (que la tool se le
 *     declara al modelo, que la call vuelve sin ejecutarse, que un impostor no tapa al belt)
 *     lo mide `platform/assembler/test_client_tools.py` contra el assembler REAL con el MCP
 *     calc REAL — 20/20. Acá se mide la otra mitad: que La Sala consume `client_calls` y las
 *     pinta con el mismo validador. Partido a propósito: cada mitad donde se puede medir sin
 *     inventar.
 *
 * ── LAS DOS CALIBRACIONES EN ROJO — entradas adversas, no flags ──────────────────────
 *   §4 · CEREBRO SIN RAZONAMIENTO. Ningún turno de esta vara emite razonamiento, y el bloque
 *        NO tiene que existir. Una afirmación que sólo puede dar 0 no prueba nada (la lección
 *        del punto ciego del slot, T7): por eso §4b enciende el bloque por la puerta REAL y
 *        exige que aparezca. La vara prueba que sabe distinguir «no hubo» de «no puedo verlo».
 *   §5 · TEATRO INYECTADO. Se mete a mano en el log UNA entrada que ningún evento produjo —
 *        que es exactamente cómo se vería el teatro en el DOM— y se corre EL MISMO comparador
 *        de §2. Tiene que dar ROJO. Si no, §2 es una tautología y no vale nada.
 *
 * PUERTO PROPIO :8280 — comprobado antes de arrancar. JAMÁS :25374 (la .app de persona usuaria).
 *
 * ⚠ GOTCHA: el sidecar frozen NO sirve tu árbol — sirve la COPIA de `product/app/design` que
 * quedó adentro del binario (datas → _MEIPASS). Después de cada cambio en design/ hay que
 * recompilar o se mide el front viejo:
 *   ALEPH_SIDECAR_ONEFILE=1 ALEPH_BUILD=public <venv>/bin/pyinstaller --clean --noconfirm \
 *       --distpath D --workpath W deploy/fase4/aleph_sidecar.spec   (~7 min)
 */
import { webkit } from "playwright";
import net from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnFrozen, matarFrozen } from "../../../../qa/lib/frozen_guard.mjs";

const ROOT = fileURLToPath(new URL("../../../../", import.meta.url));
const PORT = Number(process.env.P9_PORT || 8280);
if (PORT === 25374) { console.error("✗ 25374 es la .app instalada — hay que usar otro puerto"); process.exit(2); }
const BASE = `http://127.0.0.1:${PORT}`;
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  path.join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
const SHOTS = process.env.P9_SHOTS || path.join(os.tmpdir(), "p9-shots");

let PASS = 0; const FALLOS = [];
const ok = (c, name, det = "") => {
  if (c) { PASS++; console.log(`  ✓ ${name}${det ? "  — " + det : ""}`); }
  else { FALLOS.push(name); console.log(`  ✗ ${name}${det ? "  — " + det : ""}`); }
  return !!c;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sec = (t) => console.log(`\n── ${t} ${"─".repeat(Math.max(0, 68 - t.length))}`);

/* ── el puerto es mío o no hay veredicto ─────────────────────────────────────────── */
await new Promise((res, rej) => {
  const p = net.createConnection({ port: PORT, host: "127.0.0.1" });
  p.on("connect", () => { p.destroy(); rej(new Error(
    `:${PORT} YA ESTÁ OCUPADO. Esta vara mide su propio árbol o no mide nada.\n` +
    `  lsof -nP -iTCP:${PORT} -sTCP:LISTEN  →  kill <pid>   ·   o P9_PORT=8281`)); });
  p.on("error", () => res());
});
if (!fs.existsSync(SIDECAR)) {
  console.error(`✗ no existe el sidecar frozen de ESTE árbol: ${SIDECAR}`);
  process.exit(2);
}

const DATADIR = fs.mkdtempSync(path.join(os.tmpdir(), "aleph-p9-"));
let PROC = null;
async function esperarPuerto(ms, libre = false) {
  const t0 = Date.now();
  for (;;) {
    const ocupado = await new Promise((r) => {
      const s = net.connect(PORT, "127.0.0.1");
      s.on("connect", () => { s.destroy(); r(true); });
      s.on("error", () => { s.destroy(); r(false); });
    });
    if (ocupado !== libre) return true;
    if (Date.now() - t0 > ms) return false;
    await sleep(250);
  }
}
async function bootear() {
  PROC = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATADIR },
  });
  PROC.stdout.on("data", () => {});
  PROC.stderr.on("data", () => {});
  if (!(await esperarPuerto(90000))) throw new Error("el sidecar frozen no levantó");
  await sleep(600);
}
async function matar() {
  if (!PROC) return;
  try { matarFrozen(PROC); } catch (e) {}
  PROC = null;
  await esperarPuerto(20000, true);
}
const api = async (m, ruta, { token, body } = {}) => {
  const h = { "Content-Type": "application/json" };
  if (token) h.Authorization = "Bearer " + token;
  const r = await fetch(BASE + ruta, { method: m, headers: h, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text();
  let j = null; try { j = t ? JSON.parse(t) : null; } catch (e) {}
  return { status: r.status, json: j, text: t };
};

console.log(`▸ sidecar : ${SIDECAR}`);
console.log(`▸ datadir : ${DATADIR}`);
console.log(`▸ base    : ${BASE}`);

/* ── EL LECTOR DE LA LÍNEA — una sola lectura del DOM, la misma para todas las §. ──
 * Devuelve, del shadow root del chat: la línea, su estado, sus entradas, y APARTE la
 * telemetría que el Guía registró (window.__guide.calls / el record). §2 los compara. */
const LEER_LINEA = (sel) => {
  const host = document.querySelector(sel);
  const sr = host && host.shadowRoot;
  if (!sr) return { montado: false };
  const L = sr.querySelector(".ac-linea");
  const entradas = Array.from(sr.querySelectorAll(".ac-li-log .ac-act")).map((a) => ({
    tool: a.dataset.tool || "",
    clases: a.className,
    estado: (a.querySelector(".ac-act-st") || {}).textContent || "",
    sub: (a.querySelector(".ac-act-sub") || {}).textContent || "",
    cara: !!a.querySelector(".ac-face"),
    detalle: !!a.querySelector(".ac-li-more"),
    camino: !!a.querySelector(".ac-li-cam"),
  }));
  return {
    montado: true,
    hayLinea: !!L,
    viva: L ? L.getAttribute("data-viva") : null,
    abierta: L ? L.getAttribute("data-open") : null,
    resumen: L ? ((L.querySelector(".ac-li-res") || {}).textContent || "") : "",
    razonamiento: sr.querySelectorAll(".ac-li-piensa").length,
    entradas,
    nLineas: sr.querySelectorAll(".ac-linea").length,
    // el latido: el MISMO nodo de P10, hospedado por la cabecera mientras el turno corre
    vitalesVivos: !!sr.querySelector('.ac-vitals[data-live="1"]'),
    vitalesEnLaLinea: !!sr.querySelector('.ac-li-head .ac-vitals[data-live="1"]'),
    texto: sr.textContent || "",
    // cuerpo VISIBLE del hilo: colapsada por default ⇒ altura 0
    cuerpoVisible: L ? ((L.querySelector(".ac-li-body") || { getBoundingClientRect: () => ({ height: 0 }) })
      .getBoundingClientRect().height > 0) : false,
  };
};

let SESION = null;
try {
  await bootear();
  const s0 = await api("POST", "/v1/auth/local");
  SESION = s0.json || {};
  ok(s0.status === 200 && SESION.session_token, "sesión de equipo del frozen", `http ${s0.status}`);

  const browser = await webkit.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript((u) => { try { localStorage.setItem("puppet_user", JSON.stringify(u)); } catch (e) {} }, SESION);
  fs.mkdirSync(SHOTS, { recursive: true });

  /* el cerebro del Guía, scripteado turno a turno */
  const guia = async (pg, turnos) => {
    let i = 0;
    await pg.route("**/v1/cuarto/guide", async (route) => {
      const t = turnos[Math.min(i++, turnos.length - 1)];
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ ...t, model_final: "opus-4.8" }) });
    });
  };
  const abrirCuarto = async (pg) => {
    await pg.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" });
    await pg.waitForTimeout(4500);
    await pg.evaluate(() => { const b = document.getElementById("copBtn"); if (b) b.click(); });
    await pg.waitForTimeout(1800);
  };
  const decir = async (pg, texto) => pg.evaluate((t) => { window.__guide.send(t); }, texto);
  const TC = (name, args, id) => ({ id: id || ("tc-" + name), type: "function",
    function: { name, arguments: JSON.stringify(args || {}) } });
  const GUIA = "#copBody deep-chat";
  const leer = (pg, sel = GUIA) => pg.evaluate(LEER_LINEA, sel);

  /* ══ §1 · EL CASO REAL: 2+ TOOL CALLS ══════════════════════════════════════════ */
  sec("§1 · LA LÍNEA VIVA — latido, resumen con conteo REAL, y se despliega");
  {
    const pg = await ctx.newPage();
    const errores = []; pg.on("pageerror", (e) => errores.push(String(e).slice(0, 160)));
    await guia(pg, [
      { content: "Miro el Cuarto y busco lo que falta.",
        tool_calls: [TC("ver_cuarto", {}, "t1"), TC("buscar_catalogo", { query: "zotero", fuente: "todo" }, "t2")] },
      { content: "Encontré dos piezas que sirven.", tool_calls: [] },
    ]);
    await abrirCuarto(pg);
    ok((await leer(pg)).montado, "el chat del Guía monta");

    await decir(pg, "buscame algo para citas");
    await pg.waitForTimeout(500);
    const vuelo = await leer(pg);
    ok(vuelo.hayLinea, "§1 · nace LA LÍNEA del turno");
    ok(vuelo.viva === "1", "§1 · …viva mientras el turno corre", `data-viva=${vuelo.viva}`);
    ok(vuelo.abierta === "0", "§1 · …y COLAPSADA por default ★", `data-open=${vuelo.abierta}`);
    ok(!vuelo.cuerpoVisible, "§1 · …el hilo no se ve hasta que lo piden");
    ok(vuelo.vitalesEnLaLinea, "§1 · EL LATIDO vive EN la cabecera de la línea (un solo pulso) ★",
       `vitales=${vuelo.vitalesVivos} enLaLinea=${vuelo.vitalesEnLaLinea}`);
    await pg.screenshot({ path: path.join(SHOTS, "p9-linea-viva.png") });

    await pg.waitForTimeout(4500);
    const fin = await leer(pg);
    ok(fin.viva === "0", "§1 · el turno terminó ⇒ la línea se pliega", `data-viva=${fin.viva}`);
    ok(!fin.vitalesVivos, "§1 · …sin spinner huérfano");
    ok(fin.entradas.length === 2, "§1 · DOS entradas, una por tool call REAL",
       fin.entradas.map((e) => e.tool).join(" · "));
    ok(/2 acciones|2 actions/.test(fin.resumen), "§1 · el resumen cuenta lo que PASÓ ★", `«${fin.resumen}»`);
    ok(fin.entradas.every((e) => /done|fail/.test(e.clases)),
       "§1 · toda entrada tiene desenlace (✓ o ✗) — P10 sigue en pie",
       fin.entradas.map((e) => e.estado).join(" · "));
    ok(fin.entradas.every((e) => e.cara), "§1 · cada entrada trae el logo real del servicio");
    ok(fin.abierta === "0", "§1 · …y sigue colapsada al cerrar (resumen discreto)");

    // desplegar: las entradas aparecen
    await pg.evaluate(() => {
      const sr = document.querySelector("#copBody deep-chat").shadowRoot;
      sr.querySelector(".ac-li-head").click();
    });
    await pg.waitForTimeout(300);
    const abierta = await leer(pg);
    ok(abierta.abierta === "1" && abierta.cuerpoVisible, "§1 · DESPLEGADA muestra el hilo ★",
       `open=${abierta.abierta} visible=${abierta.cuerpoVisible}`);
    await pg.screenshot({ path: path.join(SHOTS, "p9-linea-desplegada.png") });

    /* ══ §2 · ASSERT DURO — el log ES la telemetría, uno a uno ═══════════════════ */
    sec("§2 · ASSERT DURO — entradas del log == tool_calls de la telemetría");
    /* LA TELEMETRÍA no se lee del DOM: se lee del TRANSCRIPT que el loop del Guía le mandó
     * al modelo (`snapshotMessages`). Es la otra punta del cable — lo que el modelo pidió y
     * lo que de verdad se ejecutó, sin pasar por la pantalla.
     *
     * DOS DESCUENTOS, y los dos van DECLARADOS y CONTADOS (un descuento callado es la
     * grieta por donde se cuela el teatro):
     *   · las 5 familias de OPCIONES no abren card POR DISEÑO (P7): las opciones SON el
     *     mensaje, y anunciar «estoy preguntando» encima de la pregunta es ruido;
     *   · una tool que el modelo alucina fuera de la whitelist no existe para el Guía: no
     *     se ejecuta y no abre card.
     * Si alguno de los dos fuera > 0 en este caso, la comparación de abajo no probaría lo
     * que dice — por eso la vara los imprime y exige que sean CERO acá. */
    const cmp = await pg.evaluate(() => {
      const sr = document.querySelector("#copBody deep-chat").shadowRoot;
      const log = Array.from(sr.querySelectorAll(".ac-li-log .ac-act")).map((a) => a.dataset.tool || "");
      const OPC = ["preguntar_opciones", "accion_de_producto", "camino_de_falta", "aprobar", "redirigir"];
      const conocidas = (window.__guide.tools || []).map((t) => t.function.name);
      const pedidas = [];
      (window.__guide.snapshotMessages() || []).forEach((m) => {
        if (m.role !== "assistant" || !m.tool_calls) return;
        m.tool_calls.forEach((tc) => pedidas.push((tc.function || {}).name || ""));
      });
      const opciones = pedidas.filter((n) => OPC.indexOf(n) >= 0).length;
      const fuera = pedidas.filter((n) => conocidas.indexOf(n) < 0 && OPC.indexOf(n) < 0).length;
      const tel = pedidas.filter((n) => OPC.indexOf(n) < 0 && conocidas.indexOf(n) >= 0);
      return { log, tel, opciones, fuera,
               iguales: log.length === tel.length && log.every((t, i) => t === tel[i]) };
    });
    ok(cmp.tel.length >= 2, "§2 · la telemetría del turno tiene 2+ tool calls (el caso pedido)",
       cmp.tel.join(" · "));
    ok(cmp.opciones === 0 && cmp.fuera === 0,
       "§2 · cero descuentos en este caso (opciones y alucinadas), así la comparación es limpia",
       `opciones=${cmp.opciones} fuera-de-whitelist=${cmp.fuera}`);
    ok(cmp.iguales, "§2 · LAS ENTRADAS DEL LOG == LOS TOOL_CALLS, UNO A UNO ★★",
       `log=[${cmp.log.join(",")}] telemetría=[${cmp.tel.join(",")}]`);

    /* ══ §5 · CALIBRACIÓN #2 EN ROJO — teatro inyectado ═════════════════════════ */
    sec("§5 · CALIBRACIÓN EN ROJO — una entrada que ningún evento produjo");
    const teatro = await pg.evaluate(() => {
      const sr = document.querySelector("#copBody deep-chat").shadowRoot;
      const log = sr.querySelector(".ac-li-log");
      // así se vería el teatro en el DOM: una entrada perfecta que nadie ejecutó.
      const d = document.createElement("div");
      d.className = "ac-act done"; d.dataset.tool = "inventada";
      d.innerHTML = '<span class="ac-act-tt">Consulté algo</span><span class="ac-act-st">listo</span>';
      log.appendChild(d);
      const dom = Array.from(sr.querySelectorAll(".ac-li-log .ac-act")).map((a) => a.dataset.tool || "");
      const OPC = ["preguntar_opciones", "accion_de_producto", "camino_de_falta", "aprobar", "redirigir"];
      const conocidas = (window.__guide.tools || []).map((t) => t.function.name);
      const pedidas = [];
      (window.__guide.snapshotMessages() || []).forEach((m) => {
        if (m.role !== "assistant" || !m.tool_calls) return;
        m.tool_calls.forEach((tc) => pedidas.push((tc.function || {}).name || ""));
      });
      const tel = pedidas.filter((n) => OPC.indexOf(n) < 0 && conocidas.indexOf(n) >= 0);
      const iguales = dom.length === tel.length && dom.every((t, i) => t === tel[i]);
      d.remove();                                      // se limpia: la vara no deja basura
      return { dom, tel, iguales };
    });
    ok(teatro.iguales === false,
       "§5 · con teatro inyectado, EL MISMO comparador da ROJO ★★ (§2 no es una tautología)",
       `log=[${teatro.dom.join(",")}] telemetría=[${teatro.tel.join(",")}]`);
    ok((await pg.evaluate(() => document.querySelector("#copBody deep-chat").shadowRoot
        .querySelectorAll(".ac-li-log .ac-act").length)) === cmp.tel.length,
       "§5 · …y la vara deja el DOM como lo encontró");

    /* ══ §4 · CALIBRACIÓN #1 — razonamiento: cero si no hubo, y visible si hubo ══ */
    sec("§4 · RAZONAMIENTO — cero bloque si el cerebro no razonó");
    ok(abierta.razonamiento === 0,
       "§4a · el cerebro no emitió razonamiento ⇒ CERO bloque ★ (pensamiento inventado = mentira)",
       `bloques=${abierta.razonamiento}`);
    // …y la afirmación NO es vacía: por la puerta REAL, el bloque SÍ aparece.
    await pg.evaluate(() => window.__guiaChat.pensar("Busco los nombres reales, no de memoria."));
    await pg.waitForTimeout(250);
    const conRazon = await leer(pg);
    ok(conRazon.razonamiento === 1,
       "§4b · …y con razonamiento REAL el bloque SÍ aparece ★ (la vara puede dar >0)",
       `bloques=${conRazon.razonamiento}`);
    ok(/no de memoria/.test(conRazon.texto), "§4b · …con el texto que emitió el cerebro");
    await pg.evaluate(() => window.__guiaChat.cerrarLinea());

    ok(!/<function|&lt;function/.test(fin.texto), "§1 · cero <function=…> crudo en el chat");
    ok(!errores.length, "§1 · sin excepciones en la página", errores[0] || "");
    await pg.close();
  }

  /* ══ §3 · LA ACCIÓN FALLIDA: roja, con causa y con camino ══════════════════════ */
  sec("§3 · FALLO — entrada roja con causa, y el camino ahí mismo");
  {
    const pg = await ctx.newPage();
    // el catálogo NO CONTESTA NUNCA: la promesa del host queda colgada para siempre.
    await pg.route("**/v1/catalog/search**", () => { /* silencio deliberado */ });
    await pg.addInitScript(() => { window.__guideToolTimeoutMs = 2500; });
    await guia(pg, [
      { content: "Busco en el catálogo.", tool_calls: [TC("buscar_catalogo", { query: "zotero", fuente: "todo" }, "t9")] },
      { content: "No pude traerlo.", tool_calls: [] },
    ]);
    await abrirCuarto(pg);
    await decir(pg, "buscame zotero");
    await pg.waitForTimeout(7000);
    const d = await leer(pg);
    const e = d.entradas.find((x) => x.tool === "buscar_catalogo");
    ok(!!e, "§3 · la entrada de la búsqueda existe");
    ok(!!e && /fail/.test(e.clases), "§3 · …y cierra en ROJO, no en verde falso ★", e && e.clases);
    ok(!!e && /tard|espera|too long/i.test(e.sub), "§3 · …con la CAUSA escrita en la entrada", e && e.sub);
    ok(!!e && /reintent|camino|retry|path/i.test(e.sub), "§3 · …y con el CAMINO pegado a la causa",
       e && e.sub.slice(-70));
    ok(d.entradas.every((x) => !/doing/.test(x.clases)),
       "§3 · CERO entradas «en curso» al terminar (P10 §2b sigue verde)");
    /* §3b · EL CAMINO COMO BOTÓN. Cuando el llamador tiene un destino cableado (La Sala lo
     * saca de `caminoDe`, la única tabla), la entrada roja lleva su botón — y el botón HACE
     * algo. Pintado ≠ cableado: media UI es el botón, la otra media es que lleve a algún lado. */
    const cam = await pg.evaluate(async () => {
      const C = window.__guiaChat;
      const asa = C.action("Probé algo", { tool: "probar", service: "probar" });
      asa.fail("no anduvo", { camino: { label: "Ver el catálogo", onClick: () => { window.__camDisparo = true; } } });
      await new Promise((r) => setTimeout(r, 250));
      const sr = document.querySelector("#copBody deep-chat").shadowRoot;
      const b = sr.querySelector(".ac-li-cam");
      if (!b) return { boton: false };
      b.click();
      await new Promise((r) => setTimeout(r, 150));
      return { boton: true, label: b.textContent.trim(), disparo: !!window.__camDisparo };
    });
    ok(cam.boton, "§3b · la entrada roja lleva su botón de camino ★", cam.label || "");
    ok(cam.disparo, "§3b · …y el botón DISPARA (pintado ≠ cableado) ★");
    // el camino: se despliega y se ve
    await pg.evaluate(() => document.querySelector("#copBody deep-chat").shadowRoot.querySelector(".ac-li-head").click());
    await pg.waitForTimeout(250);
    await pg.screenshot({ path: path.join(SHOTS, "p9-entrada-roja.png") });
    await pg.close();
  }

  /* ══ §6 · LA SALA — client_tools, opciones REALES, y la línea del record ══════ */
  sec("§6 · LA SALA — las opciones llegan como tool call REAL (client_tools)");
  let PUPPET = null;
  {
    const p = await api("POST", "/v1/puppets", { token: SESION.session_token, body: {
      owner_id: SESION.id, name: "Agente P9", nicho: "general",
      config: { schema_version: "v1", meta: { name: "Agente P9", nicho: "general", output_type: "informe" },
        model: { primary: "openai/gpt-oss-120b", base_url: "https://api.groq.com/openai/v1",
                 temperature: 0.2, max_tokens: 800, max_turns: 3 },
        belt: { belt_ref: "catalog/templates/kit/belt-kit.mcp.json", tool_filters: {} },
        framing: { inline: "" }, rag: { enabled: false }, keys: {},
        gates: { money_touch: "needs_ok", send: "needs_ok" } } } });
    PUPPET = (p.json || {}).id || (p.json || {}).puppet_id;
    ok(!!PUPPET, "§6 · agente guardado creado (el camino con loop de tools)", `http ${p.status}`);

    const pg = await ctx.newPage();
    const errores = []; pg.on("pageerror", (e) => errores.push(String(e).slice(0, 160)));
    /* El frozen PÚBLICO no trae llave de cognición — a propósito: es el binario que se
     * instala, no el del dev. Sin cerebro utilizable el gate del composer no deja disparar
     * un run, y §6 no mide el gate: mide el transporte de las opciones. Se le da una lane
     * incluida sana y nada más. (Declarado, como el scripteo del modelo.) */
    await pg.route("**/v1/brains/status", (route) => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ providers: { included: { state: "ready", detail: "lane de prueba" } }, service: null }) }));
    let cuerpoDelRun = null;
    await pg.route("**/v1/puppets/run", async (route) => {
      try { cuerpoDelRun = JSON.parse(route.request().postData() || "{}"); } catch (e) { cuerpoDelRun = {}; }
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
        run_id: "run-p9", ok: true, answer: "Hay dos caminos para esto.",
        held_actions: [],
        record: {
          tool_calls: [
            { tool: "search_works", server: "crossref", args: '{"q":"vision"}', result: "[1,2,3]", gate_action: "execute" },
            { tool: "run_python", server: "pysandbox", args: '{"code":"1+1"}', result: "2", gate_action: "execute" },
          ],
          client_calls: [{ tool: "preguntar_opciones", call_id: "cc_9", turn: 1, args: {
            mensaje: "¿Con cuál sigo?",
            preguntas: [{ pregunta: "¿Con cuál sigo?", opciones: [{ label: "Con el informe" }, { label: "Con la tabla" }] }],
          } }],
        },
      }) });
    });
    /* UN AGENTE GUARDADO, no el inline. No es un detalle de setup: el turno del agente
     * inline corre por `/v1/puppets/run/stream`, que es chat de TEXTO puro SIN loop de
     * tools — ahí no hay canal de tools que usar y el bloque cercado sigue siendo el único
     * transporte (declarado en el informe). El camino que estrena `client_tools` es el del
     * agente con receta guardada, que es el que sí tiene loop. */
    await pg.goto(`${BASE}/sala/sala.html?puppet=${PUPPET}`, { waitUntil: "domcontentloaded" });
    await pg.waitForTimeout(7000);
    await pg.evaluate(() => { window.__salaChat.send("armá un informe"); });
    await pg.waitForTimeout(5000);

    ok(!!cuerpoDelRun, "§6 · el turno salió por /v1/puppets/run (el camino CON loop de tools)");
    const ct = (cuerpoDelRun && cuerpoDelRun.client_tools) || [];
    ok(ct.length === 6, "§6 · La Sala DECLARA las 6 tools de cliente como client_tools ★",
       ct.map((t) => (t.function || {}).name).join(" · "));
    ok(ct.some((t) => (t.function || {}).name === "preguntar_opciones"),
       "§6 · …incluida preguntar_opciones");
    ok(ct.some((t) => (t.function || {}).name === "conectar_inline"),
       "§6 · …incluida conectar_inline");
    const sys = String((((cuerpoDelRun || {}).recipe || {}).framing || {}).inline || "");
    ok(/OPCIONES POR TURNO|OPTIONS PER TURN/.test(sys),
       "§6 · la doctrina sigue viajando al system", `${sys.length} chars`);
    // esta afirmación NO puede pasar por vacía: exige que HAYA system, y que en ese system
    // no esté el protocolo del fence. Sin la primera mitad, un system vacío la ganaría gratis.
    ok(sys.length > 200 && !/```aleph:opciones/.test(sys),
       "§6 · …y MUERE el protocolo del bloque cercado en este camino ★", `${sys.length} chars de system`);

    const sala = await pg.evaluate(LEER_LINEA, "deep-chat");
    ok(sala.entradas.length === 2, "§6 · la línea del turno tiene las 2 tools del record ★",
       sala.entradas.map((e) => e.tool).join(" · "));
    ok(/2 acciones|2 actions/.test(sala.resumen), "§6 · …con el conteo REAL del record", `«${sala.resumen}»`);
    const opts = await pg.evaluate(() => {
      const sr = document.querySelector("deep-chat").shadowRoot;
      return { cajas: sr.querySelectorAll(".ac-opts").length,
               botones: Array.from(sr.querySelectorAll(".ac-opt")).map((b) => b.textContent.trim()) };
    });
    ok(opts.cajas === 1, "§6 · las opciones se pintaron desde client_calls ★", `cajas=${opts.cajas}`);
    ok(opts.botones.length === 2 && /informe/i.test(opts.botones.join(" ")),
       "§6 · …con las dos opciones tocables del modelo", opts.botones.join(" | "));
    ok((await pg.evaluate(() => window.__salaClientCalls().length)) === 1,
       "§6 · una sola vez: el dedup por call_id no la pinta dos veces");
    ok(!errores.length, "§6 · sin excepciones en la página", errores[0] || "");
    await pg.screenshot({ path: path.join(SHOTS, "p9-sala-opciones-tool.png") });

    /* ══ §7 · EL PANEL «Modelo» DEL SIDEBAR — legible, horizontal ══════════════ */
    sec("§7 · PANEL DEL SIDEBAR — el texto deja de caer en columna");
    await pg.evaluate(() => document.querySelector('#sbRows .sb-row[data-panel="cerebro"]').click());
    await pg.waitForTimeout(700);
    const panel = await pg.evaluate(() => {
      const bs = document.querySelector("#brainState"); if (!bs) return null;
      const r = bs.getBoundingClientRect();
      const main = bs.querySelector(".aleph-brain-main");
      const t = bs.querySelector(".aleph-brain-title");
      const mr = main ? main.getBoundingClientRect() : { width: 0, height: 0 };
      const tr = t ? t.getBoundingClientRect() : { width: 0, height: 0 };
      return { w: Math.round(r.width), h: Math.round(r.height),
               mainW: Math.round(mr.width), mainH: Math.round(mr.height),
               tituloW: Math.round(tr.width), tituloH: Math.round(tr.height),
               provs: bs.querySelectorAll(".aleph-brain-actions button").length,
               accion: (bs.querySelector(".aleph-brain-action") || {}).textContent || "" };
    });
    ok(!!panel, "§7 · el panel abre");
    ok(!!panel && panel.mainW > 200, "§7 · el contenido usa el ancho del panel (era 20 px) ★",
       `main=${panel && panel.mainW}px`);
    ok(!!panel && panel.tituloH < 30, "§7 · el título entra en UNA línea (no una letra por línea) ★",
       `título ${panel && panel.tituloW}×${panel && panel.tituloH}px`);
    ok(!!panel && panel.h < 200, "§7 · …y la tarjeta entera deja de ser una columna de 559 px",
       `alto=${panel && panel.h}px`);
    ok(!!panel && panel.provs === 0, "§7 · el panel dice lo MÍNIMO: cero botones de proveedor",
       `botones=${panel && panel.provs}`);
    ok(!!panel && /configuraci|configuration|Modelos|Models/i.test(panel.accion),
       "§7 · …y queda [Ver configuración] → el Centro de Modelos", `«${panel && panel.accion}»`);
    await pg.screenshot({ path: path.join(SHOTS, "p9-panel-modelos.png") });

    /* ══ §8 · UN SOLO [Reintentar] ═══════════════════════════════════════════════ */
    sec("§8 · LA CARD DE FALLO — un solo [Reintentar]");
    const card = await pg.evaluate(async () => {
      /* La causa `timeout` REAL del producto. Se dispara DOS veces a propósito: el primer
       * timeout NO pinta card — reintenta solo una vez (el contrato del fallo con loop de
       * P10). La card sale recién cuando el reintento también falla, que es justamente el
       * momento en que se apilaban los dos [Reintentar]. */
      window.__salaFailRun({ _timeout: true }, null, "x");
      await new Promise((r) => setTimeout(r, 1200));
      window.__salaFailRun({ _timeout: true }, null, "x");
      await new Promise((r) => setTimeout(r, 400));
      const sr = document.querySelector("deep-chat").shadowRoot;
      const c = Array.from(sr.querySelectorAll(".errcard")).pop();
      if (!c) return null;
      const btns = Array.from(c.querySelectorAll(".acts button")).map((b) => b.textContent.trim());
      return { titulo: (c.querySelector("b") || {}).textContent || "", botones: btns,
               reintentos: btns.filter((b) => /reintentar|retry/i.test(b)).length,
               marcados: c.querySelectorAll('[data-reintento="1"]').length,
               aviso: !!c.querySelector(".ac-auto") };
    });
    ok(!!card, "§8 · la card de fallo aparece");
    ok(!!card && /cort|espera|wait/i.test(card.titulo), "§8 · …es la «Corté la espera», que se conserva",
       card && card.titulo);
    ok(!!card && card.reintentos === 1, "§8 · UN SOLO [Reintentar] ★",
       card && `${card.reintentos} de ${card.botones.length}: ${card.botones.join(" | ")}`);
    ok(!!card && card.botones.length >= 2, "§8 · …y los botones de camino siguen ahí",
       card && card.botones.join(" | "));
    ok(!!card && card.aviso,
       "§8 · …y el aviso del reintento automático NO se perdió con la dedup", `aviso=${card && card.aviso}`);
    await pg.screenshot({ path: path.join(SHOTS, "p9-card-un-reintentar.png") });

    /* ══ §9 · PERSISTENCIA — una línea vieja se despliega igual ══════════════════ */
    sec("§9 · PERSISTENCIA — la línea del turno viejo sigue viva en el transcript");
    const vieja = await pg.evaluate(async () => {
      const sr = document.querySelector("deep-chat").shadowRoot;
      // se apilan más turnos encima (la línea del §6 queda «vieja»)
      for (let i = 0; i < 3; i++) window.__salaChat.say("otro mensaje " + i);
      await new Promise((r) => setTimeout(r, 400));
      const L = sr.querySelector(".ac-linea");
      if (!L) return { abre: false, detalle: false, texto: "(no quedó ninguna línea en el transcript)" };
      L.querySelector(".ac-li-head").click();
      await new Promise((r) => setTimeout(r, 200));
      const body = L.querySelector(".ac-li-body");
      const antes = body.getBoundingClientRect().height > 0;
      const more = L.querySelector(".ac-li-more");
      if (more) more.click();
      await new Promise((r) => setTimeout(r, 150));
      const det = L.querySelector(".ac-li-det");
      return { abre: antes, detalle: det ? !det.hidden : false, texto: (det || {}).textContent || "" };
    });
    ok(vieja.abre, "§9 · la línea de un turno anterior SE DESPLIEGA ★ (el toggle es DOM, no callback)");
    ok(vieja.detalle, "§9 · …y el detalle de una entrada también se abre");
    ok(/vision|1\+1|Con qué|With what/i.test(vieja.texto), "§9 · …con los args/result reales de la tool",
       vieja.texto.slice(0, 60));
    await pg.close();
  }

  /* ══ §10 · i18n EN — la línea habla los dos idiomas ══════════════════════════════ */
  sec("§10 · i18n — ES/EN en lockstep");
  {
    const pg = await ctx.newPage();
    await pg.addInitScript(() => { try { localStorage.setItem("aleph-lang", "en"); } catch (e) {} });
    await guia(pg, [
      { content: "Looking around.", tool_calls: [TC("ver_cuarto", {}, "e1")] },
      { content: "Done.", tool_calls: [] },
    ]);
    await abrirCuarto(pg);
    await decir(pg, "look around");
    await pg.waitForTimeout(5000);
    const en = await leer(pg);
    ok(/action|Thought/.test(en.resumen), "§10 · el resumen sale en inglés ★", `«${en.resumen}»`);
    ok(!/acción|acciones|Pensó/.test(en.resumen), "§10 · …y no queda una palabra en español", `«${en.resumen}»`);
    await pg.close();
  }

  await browser.close();
} catch (e) {
  console.error("\n✗✗ la vara se cayó:", (e && e.stack) || e);
  FALLOS.push("EXCEPCIÓN: " + ((e && e.message) || e));
} finally {
  await matar();
  try { fs.rmSync(DATADIR, { recursive: true, force: true }); } catch (e) {}
}

console.log(`\n${"═".repeat(72)}`);
// [H3] Las capturas van ARRIBA: la última línea de una vara es su veredicto.
console.log(`  capturas: ${SHOTS}`);
console.log(`  ${PASS} verdes · ${FALLOS.length} rojos`);
if (FALLOS.length) { FALLOS.forEach((f) => console.log(`  ✗ ${f}`)); process.exit(1); }
