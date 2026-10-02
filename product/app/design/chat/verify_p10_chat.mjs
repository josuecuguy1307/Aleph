/* verify_p10_chat.mjs — LA VARA DEL CHAT ESTABLE (FIX-P10).
 *
 * WebKit real (el motor de WKWebView, el mismo de la .app) contra el SIDECAR FROZEN DE ESTE
 * ÁRBOL, en puerto propio :8291, con datadir aislado. Todo es de verdad —el backend, la DB
 * SQLite, el reaper del boot, el Cuarto y la Sala servidos por el frozen— salvo UNA cosa,
 * declarada: `/v1/cuarto/guide` (el cerebro del Guía) se SCRIPTEA en la webview. Un modelo
 * no es determinista y una vara con un modelo adentro no mide el producto: mide la suerte
 * del día. Lo que se mide del modelo es su CONTRATO (qué tools ve, qué doctrina lee) y lo
 * que el producto hace con cada forma de turno.
 *
 *   node product/app/design/chat/verify_p10_chat.mjs
 *
 * §7 MIDE LA **UI FIJA**, NO LA RESPUESTA DEL MODELO — y es contrato, no omisión: el modelo
 * espeja el registro de quien le escribe, así que exigirle neutralidad a su salida sería medir
 * al humano. Lo que se mide es lo que escribimos nosotros: el prompt que se despacha, la UI
 * renderizada sin un solo turno, y el diccionario ES de estas superficies.
 *
 * LAS DOS CALIBRACIONES EN ROJO — no son flags, son ENTRADAS ADVERSAS reales:
 *   · §1 planta a mano un run 'running' viejo en la DB (el estado exacto que brickeaba el
 *     chat) y exige que el chat abra ESCRIBIBLE igual.
 *   · §2 deja el backend MUDO a propósito (la búsqueda del catálogo no contesta nunca) y
 *     exige que la card cierre con causa en vez de girar para siempre.
 *   Además §1.0 fotografía la DB ANTES del boot (run en 'running' = el rojo) y DESPUÉS
 *   (reapeado a 'huerfano' = el verde): la vara ve las dos caras, no sólo la que le gusta.
 *
 * PUERTO PROPIO :8291 — comprobado antes de arrancar. La lección de 581aa1c: un veredicto
 * firmado sobre el árbol de otra sesión es peor que no tener veredicto. JAMÁS :25374 (la
 * .app instalada de persona usuaria).
 *
 * ⚠ GOTCHA QUE CUESTA UNA VUELTA ENTERA: el sidecar frozen NO sirve tu árbol — sirve la
 * COPIA de `product/app/design` que quedó adentro del binario (datas → _MEIPASS). Tocar el
 * front y volver a correr la vara sin recompilar mide el front VIEJO y da verdes o rojos que
 * no existen. Después de cada cambio en design/:
 *   ALEPH_SIDECAR_ONEFILE=1 ALEPH_BUILD=public <venv>/bin/pyinstaller --clean --noconfirm \
 *       --distpath D --workpath W deploy/fase4/aleph_sidecar.spec   (~7 min)
 * (Es el precio de medir contra lo que se instala de verdad, y por eso el mandato pide
 * "frozen propio": un front que anda en dev y no viaja al binario es un bug que no se ve.)
 */
import { webkit } from "playwright";
import net from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { spawnFrozen, matarFrozen } from "../../../../qa/lib/frozen_guard.mjs";
import { hallazgos, grepDelMandato } from "../../../../qa/lib/neutro.mjs";

const ROOT = fileURLToPath(new URL("../../../../", import.meta.url));
const PORT = Number(process.env.P10_PORT || 8291);
if (PORT === 25374) { console.error("✗ 25374 es la .app instalada — hay que usar otro puerto"); process.exit(2); }
const BASE = `http://127.0.0.1:${PORT}`;
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  path.join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
const SHOTS = process.env.P10_SHOTS || path.join(os.tmpdir(), "p10-shots");

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
    `  lsof -nP -iTCP:${PORT} -sTCP:LISTEN  →  kill <pid>   ·   o P10_PORT=8292`)); });
  p.on("error", () => res());
});
if (!fs.existsSync(SIDECAR)) {
  console.error(`✗ no existe el sidecar frozen de ESTE árbol: ${SIDECAR}\n` +
                `  construílo (sólo el sidecar, sin tocar /Applications):\n` +
                `  ALEPH_SIDECAR_ONEFILE=1 ALEPH_BUILD=public <venv>/bin/pyinstaller --clean --noconfirm \\\n` +
                `      --distpath D --workpath W deploy/fase4/aleph_sidecar.spec`);
  process.exit(2);
}

/* ── datadir aislado + la DB semilla ─────────────────────────────────────────────── */
const DATADIR = fs.mkdtempSync(path.join(os.tmpdir(), "aleph-p10-"));
const DB = path.join(DATADIR, "aleph.db");
const sq = (sql) => execFileSync("sqlite3", [DB, sql], { encoding: "utf8" }).trim();

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
  LOG = "";
  PROC.stdout.on("data", (b) => { LOG += b.toString(); });
  PROC.stderr.on("data", (b) => { LOG += b.toString(); });
  if (!(await esperarPuerto(90000))) throw new Error("el sidecar frozen no levantó");
  await sleep(600);
}
let LOG = "";
async function matar() {
  if (!PROC) return;
  try { matarFrozen(PROC); } catch (e) {}
  PROC = null;
  await esperarPuerto(20000, true);
  await sleep(300);
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

let SESION = null;
try {
  /* ══ §1 · EL TURNO SIEMPRE CIERRA (La Sala) ══════════════════════════════════════ */
  sec("§1 · EL TURNO SIEMPRE CIERRA — el registro deja de mentir");

  // primer boot: crea el schema del cliente y da sesión de equipo.
  await bootear();
  const s0 = await api("POST", "/v1/auth/local");
  SESION = s0.json || {};
  ok(s0.status === 200 && SESION.session_token, "sesión de equipo del frozen", `http ${s0.status}`);
  const UID = SESION.id;

  // un chat REAL con dos mensajes (el equivalente del chat de derivadas del humano).
  const c = await api("POST", "/v1/chats", { token: SESION.session_token, body: {} });
  const CHAT = (c.json || {}).id;
  ok((c.status === 200 || c.status === 201) && CHAT, "chat persistente creado", `http ${c.status}`);
  sq(`INSERT INTO chat_messages (chat_id,role,kind,content) VALUES ` +
     `('${CHAT}','user','chat','ayudame con la power rule'),` +
     `('${CHAT}','agent','chat','La derivada de x^n es n·x^(n-1).');`);

  // ── CALIBRACIÓN EN ROJO (a) · EL RUN PEGADO A MANO ──
  // Éste es, byte a byte, el estado que dejaba el chat brickeado: 'running', sin nadie
  // corriéndolo, sobreviviendo al cierre de la app.
  const RUN_PEGADO = "11111111-1111-4111-8111-111111111111";
  await matar();
  sq(`INSERT INTO runs (id,user_id,space_id,intent,status,started_at,finished_at) VALUES ` +
     `('${RUN_PEGADO}','${UID}','sp-p10','turno cortado a mano','running','2026-07-27T02:09:05.000',NULL);`);
  ok(sq(`SELECT status FROM runs WHERE id='${RUN_PEGADO}';`) === "running",
     "ROJO plantado: el run queda 'running' con la app cerrada");

  await bootear();
  const estadoTrasBoot = sq(`SELECT status FROM runs WHERE id='${RUN_PEGADO}';`);
  ok(estadoTrasBoot === "huerfano",
     "§1a · el reaper del boot lo marca huérfano", `status='${estadoTrasBoot}'`);
  ok(/reaper: \d+ run/.test(LOG), "§1a · el reaper NO es mudo: lo dice en el log",
     (LOG.match(/\[runs\][^\n]*/) || ["(sin línea)"])[0]);
  ok(sq(`SELECT finished_at IS NOT NULL FROM runs WHERE id='${RUN_PEGADO}';`) === "1",
     "§1a · el huérfano queda SELLADO (finished_at)");

  const est = await api("GET", "/v1/runs/estado", { token: SESION.session_token });
  ok(est.status === 200 && est.json && est.json.vivo === null && !(est.json.huerfanos || []).length,
     "§1a · /v1/runs/estado: cero vivos, cero mentiras", JSON.stringify(est.json && est.json.vivo));
  ok(!!(est.json && est.json.cortado && est.json.cortado.run_id === RUN_PEGADO),
     "§1a · …y SÍ reporta el corte, para poder decirlo");

  /* ── WebKit ─────────────────────────────────────────────────────────────────────── */
  const browser = await webkit.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript((u) => { try { localStorage.setItem("puppet_user", JSON.stringify(u)); } catch (e) {} }, SESION);
  fs.mkdirSync(SHOTS, { recursive: true });

  // ── §1b · LA PRUEBA REINA: el chat con el run pegado abre ESCRIBIBLE ──
  {
    const pg = await ctx.newPage();
    const errores = [];
    pg.on("pageerror", (e) => errores.push(String(e).slice(0, 160)));
    await pg.goto(`${BASE}/sala/sala.html?chat=${CHAT}`, { waitUntil: "domcontentloaded" });
    await pg.waitForTimeout(6500);

    const m = await pg.evaluate(() => {
      const dc = document.querySelector("deep-chat");
      const sr = dc && dc.shadowRoot;
      const inp = sr && sr.querySelector("#text-input");
      const txt = sr ? sr.textContent || "" : "";
      return {
        url: location.href,
        hayInput: !!inp,
        editable: inp ? inp.getAttribute("contenteditable") !== "false" && !inp.hasAttribute("disabled") : false,
        hilo: /power rule/i.test(txt),
        aviso: !!(sr && sr.querySelector("[data-corte]")),
        turno: window.__salaTurno || null,
      };
    });
    ok(m.url.includes(`chat=${CHAT}`), "§1b · el ?chat= sobrevive al arranque (no se tira el hilo)", m.url.split("/").pop());
    ok(m.hilo, "§1b · el hilo guardado se re-proyecta (las burbujas vuelven)");
    ok(m.hayInput && m.editable, "§1b · EL CHAT ABRE ESCRIBIBLE con el run pegado en la DB ★");
    ok(!!m.aviso, "§1b · …y lo dice: «el turno anterior quedó cortado»");
    ok(m.turno && m.turno.estado && !(m.turno.estado.huerfanos || []).length,
       "§1b · el front leyó el estado real del turno (evidencia, no permiso)");
    ok(!errores.length, "§1b · sin excepciones en la página", errores[0] || "");

    // …y ESCRIBIR de verdad entra: el composer no es un adorno habilitado.
    await pg.evaluate(() => {
      const sr = document.querySelector("deep-chat").shadowRoot;
      const i = sr.querySelector("#text-input"); i.focus();
    });
    await pg.keyboard.type("sigo acá");
    const tecleado = await pg.evaluate(() => {
      const sr = document.querySelector("deep-chat").shadowRoot;
      return (sr.querySelector("#text-input").textContent || "").trim();
    });
    ok(tecleado === "sigo acá", "§1b · el composer acepta tecleo real", `«${tecleado}»`);
    await pg.screenshot({ path: path.join(SHOTS, "p10-sala-chat-escribible.png") });
    await pg.close();
  }

  /* ══ §2·§3·§5·§6·§7 · EL GUÍA ════════════════════════════════════════════════════ */
  // El cerebro del Guía se scriptea: cada POST /v1/cuarto/guide devuelve el turno que toca.
  const guia = async (pg, turnos) => {
    let i = 0;
    await pg.route("**/v1/cuarto/guide", async (route) => {
      const t = turnos[Math.min(i++, turnos.length - 1)];
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ ...t, model_final: "opus-4.8" }) });
    });
  };
  const abrirCuarto = async (pg) => {
    // el plazo por tool se baja ANTES de que el Cuarto construya el Guía (createGuide lo lee
    // una vez): con addInitScript ya está puesto cuando corre el módulo.
    await pg.addInitScript(() => { window.__guideToolTimeoutMs = 2500; });
    await pg.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" });
    await pg.waitForTimeout(4500);
    await pg.evaluate(() => { const b = document.getElementById("copBtn"); if (b) b.click(); });
    await pg.waitForTimeout(1800);
  };
  // NO se espera el turno: hay que poder MIRAR el chat mientras está en vuelo (§5 mide
  // justamente eso). `send` se dispara y se sigue; quien quiera el final, espera por el DOM.
  const decir = async (pg, texto) => pg.evaluate((t) => { window.__guide.send(t); }, texto);
  const chatDOM = (pg) => pg.evaluate(() => {
    const host = document.querySelector("#copBody deep-chat");
    const sr = host && host.shadowRoot;
    if (!sr) return { montado: false };
    const acts = Array.from(sr.querySelectorAll(".ac-act"));
    return {
      montado: true,
      texto: sr.textContent || "",
      acts: acts.map((a) => ({ tool: a.dataset.tool, clases: a.className, estado: (a.querySelector(".ac-act-st") || {}).textContent || "", sub: (a.querySelector(".ac-act-sub") || {}).textContent || "" })),
      enCurso: acts.filter((a) => a.classList.contains("doing")).length,
      vitales: !!sr.querySelector(".ac-vitals"),
      opciones: Array.from(sr.querySelectorAll(".ac-opc, .opc-btn, [data-opc]")).length,
      botones: Array.from(sr.querySelectorAll("button")).map((b) => (b.textContent || "").trim()).filter(Boolean),
    };
  });

  const TC = (name, args, id) => ({ id: id || ("tc-" + name), type: "function",
    function: { name, arguments: JSON.stringify(args || {}) } });

  sec("§2 · TODA CARD CIERRA — ✓ resultado o ✗ causa");
  {
    const pg = await ctx.newPage();
    await guia(pg, [
      { content: "Miro el Cuarto y busco.", tool_calls: [TC("ver_cuarto", {}, "t1")] },
      { content: "Listo — eso es lo que hay.", tool_calls: [] },
    ]);
    await abrirCuarto(pg);
    const montado = await chatDOM(pg);
    ok(montado.montado, "el chat del Guía monta");

    await decir(pg, "mostrame el cuarto");
    await pg.waitForTimeout(400);
    const enVuelo = await chatDOM(pg);
    ok(enVuelo.acts.length >= 1, "la tool se ve como card de ACCIÓN", JSON.stringify(enVuelo.acts[0] || {}));

    await pg.waitForTimeout(3000);
    const cerrado = await chatDOM(pg);
    ok(cerrado.enCurso === 0, "§2 · CERO cards «en curso» al terminar el turno ★",
       `acts=${cerrado.acts.length} enCurso=${cerrado.enCurso}`);
    ok(cerrado.acts.every((a) => /done|fail/.test(a.clases)), "§2 · toda card tiene desenlace (done|fail)",
       cerrado.acts.map((a) => a.estado).join(" · "));
    ok(!cerrado.vitales, "§2 · sin spinner huérfano al cerrar el turno");
    await pg.close();
  }

  sec("§2b · CALIBRACIÓN EN ROJO — backend mudo a propósito");
  {
    const pg = await ctx.newPage();
    // el catálogo NO CONTESTA NUNCA: la promesa del host queda colgada para siempre.
    await pg.route("**/v1/catalog/search**", () => { /* silencio deliberado */ });
    await guia(pg, [
      { content: "Busco en el catálogo.", tool_calls: [TC("buscar_catalogo", { query: "zotero", fuente: "todo" }, "t9")] },
      { content: "No pude traerlo.", tool_calls: [] },
    ]);
    await abrirCuarto(pg);
    await decir(pg, "buscame zotero");
    await pg.waitForTimeout(7000);
    const d = await chatDOM(pg);
    const card = d.acts.find((a) => a.tool === "buscar_catalogo");
    ok(!!card, "la card de la búsqueda existe");
    ok(d.enCurso === 0, "§2b · con el backend MUDO la card igual CIERRA ★", `enCurso=${d.enCurso}`);
    ok(!!card && /fail/.test(card.clases), "§2b · …y cierra en ROJO, no en verde falso", card && card.clases);
    ok(!!card && /tard|espera|too long/i.test(card.sub), "§2b · …con la CAUSA escrita en la card", card && card.sub);
    await pg.screenshot({ path: path.join(SHOTS, "p10-guia-card-cierra-con-causa.png") });
    await pg.close();
  }

  sec("§3 · DOS CATÁLOGOS, DOS BÚSQUEDAS");
  {
    // (i) el CONTRATO que el modelo lee distingue los dos, y lo dice
    const pg = await ctx.newPage();
    await guia(pg, [{ content: "ok", tool_calls: [] }]);
    await abrirCuarto(pg);
    const contrato = await pg.evaluate(() => {
      const t = (window.__guide.tools || []).find((x) => x.function.name === "buscar_catalogo");
      return { enum: (((t || {}).function || {}).parameters || {}).properties?.fuente?.enum || [],
               desc: ((t || {}).function || {}).description || "" };
    });
    ok(contrato.enum.includes("mi_cuarto"), "§3 · la tool ofrece «mi_cuarto» (lo que YA está equipado)", contrato.enum.join("|"));
    ok(/YA TIENE|ya tengo|las mías/i.test(contrato.desc), "§3 · la descripción nombra el caso «las que ya tengo»");
    ok(/no se adivina/i.test(contrato.desc) && /preguntar_opciones/.test(contrato.desc),
       "§3 · …y ordena PREGUNTAR con opciones ante la duda (sin adivinar)");

    // (ii) el COMPORTAMIENTO: buscar lo propio NO sale a la red
    const red = [];
    pg.on("request", (r) => { if (r.url().includes("/v1/catalog/search")) red.push(r.url()); });
    const local = await pg.evaluate(async () => await window.__guideHost.buscarCatalogo("todo", "mi_cuarto", ""));
    await pg.waitForTimeout(600);
    ok(local && local.ok && local.fuente === "mi_cuarto", "§3 · «mi_cuarto» contesta desde el Cuarto", JSON.stringify(local).slice(0, 90));
    ok(red.length === 0, "§3 · …y NO sale al registro público ★", `requests=${red.length}`);
    ok(typeof local.total_en_cuarto === "number", "§3 · reporta cuántas piezas hay de verdad", `total=${local.total_en_cuarto}`);
    await pg.close();
  }

  sec("§4 · OPCIONES DONDE CORRESPONDE (y sólo ahí)");
  {
    const pg = await ctx.newPage();
    await guia(pg, [
      { content: "Encontré varios. ¿Cuáles abro?", tool_calls: [TC("preguntar_opciones", {
        mensaje: "Encontré estos MCPs. ¿Cuáles equipamos?",
        preguntas: [{ pregunta: "Elegí los que quieras", multi: true,
          opciones: [{ label: "Zotero" }, { label: "Crossref" }, { label: "arXiv" }] }],
      }, "t7")] },
    ]);
    await abrirCuarto(pg);
    await decir(pg, "buscame algo de research");
    await pg.waitForTimeout(2500);
    const d = await chatDOM(pg);
    const tocables = d.botones.filter((b) => /Zotero|Crossref|arXiv/.test(b));
    ok(tocables.length === 3, "§4 · la pregunta enumerable llega como OPCIONES TOCABLES ★", tocables.join(" · "));
    ok(/Encontré estos MCPs/.test(d.texto), "§4 · con su línea conversacional (jamás opciones mudas)");
    await pg.screenshot({ path: path.join(SHOTS, "p10-guia-opciones-multi.png") });
    await pg.close();

    // la contracara: pregunta ABIERTA → CERO opciones
    const pg2 = await ctx.newPage();
    await guia(pg2, [{ content: "¿Para qué va a servir? Con eso lo armo.", tool_calls: [] }]);
    await abrirCuarto(pg2);
    await decir(pg2, "quiero armar un agente");
    await pg2.waitForTimeout(1800);
    const d2 = await chatDOM(pg2);
    const opc = d2.botones.filter((b) => b.length > 1 && !/^(Reintentar|Probar|Cerrar|✕|＠|🎙)/.test(b));
    ok(/Para qué va a servir/.test(d2.texto), "§4 · la pregunta abierta llega como prosa");
    ok(opc.length === 0, "§4 · …y NO fabrica opciones para una respuesta no enumerable ★", opc.join(" · "));
    await pg2.close();
  }

  sec("§5 · SIGNOS VITALES — jamás silencio");
  {
    const pg = await ctx.newPage();
    let libera; const bloqueo = new Promise((r) => { libera = r; });
    // la segunda vuelta del cerebro se hace esperar: es EXACTAMENTE el hueco donde el chat
    // quedaba mudo (el modelo escribió una línea y sigue trabajando).
    let n = 0;
    await pg.route("**/v1/cuarto/guide", async (route) => {
      n++;
      const t = n === 1
        ? { content: "Voy a mirar tu Cuarto.", tool_calls: [TC("ver_cuarto", {}, "tv")] }
        : { content: "Listo.", tool_calls: [] };
      if (n === 2) await bloqueo;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...t, model_final: "opus" }) });
    });
    await abrirCuarto(pg);
    await decir(pg, "mostrame el cuarto");
    await pg.waitForTimeout(1500);
    const medio = await chatDOM(pg);
    ok(medio.vitales, "§5 · con el turno EN VUELO hay señal viva («pensando…») ★",
       `enCurso=${medio.enCurso}`);
    ok(/Voy a mirar tu Cuarto/.test(medio.texto), "§5 · …y la prosa ya escrita también está");
    libera();
    await pg.waitForTimeout(2500);
    const fin = await chatDOM(pg);
    ok(!fin.vitales && fin.enCurso === 0, "§5 · al cerrar el turno: sin señal viva y sin cards abiertas");
    await pg.close();
  }

  sec("§6 · EL PANEL CONTIENE SU CONVERSACIÓN");
  {
    const pg = await ctx.newPage();
    await guia(pg, [{ content: "El Cuarto es el taller: acá vive el agente en construcción, con sus piezas alrededor del Núcleo. " + "Cada pieza es una herramienta real y su color dice si está probada, detectada o rota. ".repeat(2), tool_calls: [] }]);
    await abrirCuarto(pg);
    // una conversación LARGA de verdad, por el camino REAL: 24 turnos que entran por el
    // composer y salen por onAssistant (nada de inyectar HTML a mano — eso mediría otra cosa).
    for (let i = 0; i < 24; i++) {
      await pg.evaluate((n) => window.__guide.send("una vuelta más del cuarto, " + n), i);
      await pg.waitForTimeout(120);
    }
    await pg.waitForTimeout(2500);
    const geo = await pg.evaluate(() => {
      const p = document.getElementById("copilot");
      const r = p.getBoundingClientRect();
      const host = document.querySelector("#copBody deep-chat");
      const sr = host && host.shadowRoot;
      const msgs = sr && sr.querySelector("#messages");
      const flot = Array.from(document.querySelectorAll(".float, .hintline, [role='tooltip']"))
        .filter((e) => e.offsetParent !== null)
        .map((e) => { const b = e.getBoundingClientRect(); return { id: e.id || e.className, ...{ x: b.x, y: b.y, w: b.width, h: b.height } }; });
      const solapa = flot.filter((f) => !(f.x + f.w < r.left || f.x > r.right || f.y + f.h < r.top || f.y > r.bottom));
      return {
        panel: { top: r.top, bottom: r.bottom, left: r.left, right: r.right, h: r.height },
        vp: { w: innerWidth, h: innerHeight },
        scrollInterno: msgs ? { sh: msgs.scrollHeight, ch: msgs.clientHeight, ov: getComputedStyle(msgs).overflowY } : null,
        solapa,
      };
    });
    ok(geo.panel.top >= -1 && geo.panel.bottom <= geo.vp.h + 1,
       "§6 · el panel entero cabe en la pantalla (cero desborde) ★",
       `top=${geo.panel.top.toFixed(0)} bottom=${geo.panel.bottom.toFixed(0)} vh=${geo.vp.h}`);
    ok(geo.panel.left >= -1 && geo.panel.right <= geo.vp.w + 1, "§6 · …también a lo ancho");
    ok(!!geo.scrollInterno && geo.scrollInterno.sh > geo.scrollInterno.ch,
       "§6 · la conversación larga scrollea ADENTRO", geo.scrollInterno && `${geo.scrollInterno.sh}>${geo.scrollInterno.ch}`);
    ok(geo.solapa.length === 0, "§6 · cero solape con flotantes/tooltips del diorama",
       geo.solapa.map((s) => s.id).join(" · ") || "ninguno");
    await pg.screenshot({ path: path.join(SHOTS, "p10-panel-contiene.png") });
    await pg.close();
  }

  sec("§7 · LA UI FIJA — cero segunda persona (y el system sin regla de registro)");
  {
    /* ── QUÉ SE MIDE ACÁ, Y QUÉ NO ─────────────────────────────────────────────────
     * SE MIDE **EL TEXTO FIJO QUE ESCRIBIMOS NOSOTROS**, en sus tres formas:
     *   (a) el prompt que se despacha — system (3 modos) + los 27 schemas;
     *   (b) la UI renderizada SIN NINGÚN TURNO — chrome, saludos, placeholders, labels;
     *   (c) el diccionario ES que usan estas superficies (copy que hoy no está en pantalla
     *       pero se pinta en cuanto pasa algo: bloqueos, ofertas, errores).
     *
     * NO SE MIDE LA RESPUESTA VIVA DEL MODELO, y no es una omisión: **es el contrato**. El
     * modelo espeja el registro de quien le escribe. Si el humano tutea, va a tutear — y eso
     * está BIEN: es conversación, no interfaz. Una vara que exigiera neutralidad en la salida
     * estaría midiendo al humano, no al producto, y para pasarla habría que meterle al modelo
     * la regla de estilo que §2 sacó a propósito. Por eso §7 abre las páginas y NO manda ni
     * un turno; el guard de abajo lo comprueba en vez de confiar en que me acordé.
     *
     * DOS MEDIDAS, no una:
     *   · GREP DEL MANDATO — los DOCE literales pedidos (los diez + `tu`/`tus`), en crudo.
     *   · DETECTOR — la lista larga: pronombres y posesivos, 2ª conjugada y sus imperativos,
     *     en las dos variantes del castellano. Encuentra lo que el grep de doce no ve.
     *
     * Y no se mide el CÓDIGO FUENTE: un comentario que documenta un regex sobre el idioma
     * DEL USUARIO («hazlo corto» = seguimiento) no es copy nuestra, y contarlo sería ruido. */
    const cero = (txt, nombre, estrella) => {
      const g = grepDelMandato(txt), h = hallazgos(txt);
      ok(g.length === 0, `§7 · ${nombre} — grep del mandato${estrella ? " ★" : ""}`,
         g.length ? g.map((x) => `«${x.palabra}» ${x.contexto.trim().slice(0, 46)}`).join(" | ") : "0 de 12");
      ok(h.length === 0, `§7 · ${nombre} — detector de 2ª persona`,
         h.length ? h.map((x) => `${x.clase}:${x.palabra}→${x.contexto.trim().slice(0, 40)}`).join(" | ") : "0");
    };

    const pg = await ctx.newPage();
    let turnosAlModelo = 0;
    await pg.route("**/v1/cuarto/guide", async (route) => {   // no debería dispararse NUNCA acá
      turnosAlModelo++;
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ content: "", tool_calls: [] }) });
    });
    await abrirCuarto(pg);

    // (a) EL PROMPT QUE SE DESPACHA
    const t = await pg.evaluate(async () => {
      const b = await import("./cuarto.guide.belt.js");
      const sys = ["delegar", "guiar", "explicar"].map((m) => b.buildGuideSystem("es", { mode: m })).join("\n");
      const sysEn = ["delegar", "guiar", "explicar"].map((m) => b.buildGuideSystem("en", { mode: m })).join("\n");
      const tools = b.guideTools("es").map((x) => x.function.name + " " + x.function.description +
        " " + JSON.stringify(x.function.parameters)).join("\n");
      return { sys, sysEn, tools, n: b.guideTools("es").length };
    });
    ok(t.n === 27, "§7 · son 27 schemas los que lee el modelo", String(t.n));
    cero(t.sys, "el SYSTEM del Guía (3 modos)", true);
    cero(t.tools, "los 27 schemas", true);

    /* [FIX-P10 §2] EL SYSTEM NO DICTA REGISTRO. Ni «neutro», ni una variante del castellano,
     * ni una lista de tokens: instruir el registro vuelve rígido a un modelo que ya espeja al
     * humano solo. Lo que queda permitido es UNA línea de categoría y en positivo. Esta
     * aserción existe para que nadie la re-agregue "por las dudas" dentro de seis meses. */
    const dicta = /\bneutr[oa]\b|\bvoseo\b|\btuteo\b|segunda persona|rioplatense|castellano rioplat/i;
    ok(!dicta.test(t.sys) && !dicta.test(t.sysEn),
       "§7 · el system NO dicta registro (sin regla de estilo ni lista de tokens) ★",
       (t.sys.match(dicta) || t.sysEn.match(dicta) || ["ninguna"])[0]);

    // (b) LA UI RENDERIZADA, sin un solo turno de por medio
    const domCuarto = await pg.evaluate(() => document.body.innerText);
    cero(domCuarto, "el Cuarto renderizado (sin turnos)");

    // (c) EL DICCIONARIO ES de estas superficies — copy fija que hoy no está en pantalla
    const dic = await pg.evaluate(async () => {
      const r = await fetch("../i18n.js"); const src = await r.text();
      const d = src.slice(src.indexOf("var DICT = {"), src.indexOf("var TM = {"));
      const es = d.slice(0, d.indexOf("en: {"));
      const pares = [...es.matchAll(/^\s*'?"?([\w.\-]+)'?"?\s*:\s*(['"])((?:(?!\2)[^\\]|\\.)*)\2/gm)]
        .map((m) => ({ k: m[1], v: m[3] }));
      const tm = src.slice(src.indexOf("var TM = {"));
      const claves = [...tm.matchAll(/^\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")\s*:/gm)]
        .map((m) => m[1] ?? m[2]).filter(Boolean);
      const fuentes = await Promise.all(["../sala/sala.html", "./cuarto.pixi.html",
        "../chat/aleph-chat.js", "../chat/opciones.js"].map((p) => fetch(p).then((x) => x.text()).catch(() => "")));
      const todo = fuentes.join("\n");
      const usados = pares.filter((p) => todo.includes(`'${p.k}'`) || todo.includes(`"${p.k}"`)).map((p) => p.v);
      const tmUsados = claves.filter((k) => todo.includes(k));
      return { texto: usados.concat(tmUsados).join("\n"), nEntradas: usados.length + tmUsados.length };
    });
    ok(dic.nEntradas > 100, "§7 · el diccionario de estas superficies se leyó entero", `${dic.nEntradas} entradas`);
    cero(dic.texto, "el diccionario ES de Guía y Sala", true);
    await pg.close();

    const pg2 = await ctx.newPage();
    await pg2.goto(`${BASE}/sala/sala.html`, { waitUntil: "domcontentloaded" });
    await pg2.waitForTimeout(4500);
    const domSala = await pg2.evaluate(() => {
      const dc = document.querySelector("deep-chat");
      return document.body.innerText + "\n" + ((dc && dc.shadowRoot && dc.shadowRoot.textContent) || "");
    });
    cero(domSala, "La Sala renderizada (sin turnos)");
    await pg2.close();

    ok(turnosAlModelo === 0, "§7 · …y NADA de esto pasó por el modelo (se midió UI fija) ★",
       `turnos al cerebro: ${turnosAlModelo}`);
  }

  await browser.close();
} catch (e) {
  console.error("\n✗ la vara MURIÓ:", (e && e.stack) || e);
  FALLOS.push("excepción: " + ((e && e.message) || e));
} finally {
  await matar();
  try { fs.rmSync(DATADIR, { recursive: true, force: true }); } catch (e) {}
}

console.log(`\n${"═".repeat(72)}`);
// [H3] Las capturas van ARRIBA: la última línea de una vara es su veredicto, no la ruta
// de un png — un `tail -1` que lee eso no sabe si el merge puede pasar.
console.log(`capturas: ${SHOTS}`);
console.log(`FIX-P10 · ${PASS} verdes · ${FALLOS.length} rojos`);
if (FALLOS.length) { FALLOS.forEach((f) => console.log("   ✗ " + f)); process.exit(1); }
