/* verify_opciones_turno.mjs — LA VARA DE OPCIONES POR TURNO (FIX-P7).
 *
 * WebKit real (el motor de WKWebView / la .app Tauri) contra un sidecar STUB determinista en
 * :8277. Sin red externa (todo request no-local se ABORTA y se cuenta). Mide las DOS
 * superficies, UN caso por familia, y sobre todo mide lo que la mitad de los productos no
 * mide: que el botón esté CABLEADO, no sólo pintado.
 *
 *   node product/app/design/chat/verify_opciones_turno.mjs
 *
 * CALIBRACIÓN EN ROJO (una vara que no se puede poner roja no prueba nada):
 *   OPC_ROJO=descableado  → se desconecta a propósito el handler de [Enviar]. La vara DEBE
 *                           fallar: el botón no se pinta y el desenlace nunca llega.
 *   OPC_ROJO=pretap       → el turno del modelo afirma la acción ANTES del tap
 *                           ("Listo, ya lo envié"). La vara DEBE fallar.
 *
 * PUERTO PROPIO :8277 — y se COMPRUEBA antes de arrancar. La lección de 581aa1c: un
 * veredicto firmado sobre el árbol de otra sesión es peor que no tener veredicto.
 */
import { webkit } from "playwright";
import http from "node:http";
import net from "node:net";
import { readFile } from "node:fs/promises";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";

const DESIGN = fileURLToPath(new URL("../", import.meta.url));
const PORT = Number(process.env.VERIFY_PORT || 8277);
const ROJO = String(process.env.OPC_ROJO || "");
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp",
  ".woff2": "font/woff2", ".md": "text/markdown", ".ico": "image/x-icon" };

const fails = [];
const ok = (c, l, x) => { console.log(`${c ? "✓" : "✗"} ${l}${x ? "  — " + x : ""}`); if (!c) fails.push(l); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ── EL PUERTO ES MÍO O NO HAY VEREDICTO ──────────────────────────────────────────── */
await new Promise((resolve, reject) => {
  const probe = net.createConnection({ port: PORT, host: "127.0.0.1" });
  probe.on("connect", () => { probe.destroy();
    reject(new Error(`:${PORT} YA ESTÁ OCUPADO. Esta vara mide su propio árbol o no mide nada.\n` +
      `  Liberalo:  lsof -nP -iTCP:${PORT} -sTCP:LISTEN   →   kill <pid>\n` +
      `  O corré con otro:  VERIFY_PORT=8278 node ${process.argv[1]}`)); });
  probe.on("error", () => resolve());
});

/* ── EL SIDECAR STUB ──────────────────────────────────────────────────────────────── */
const PNG_1x1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const json = (res, code, obj) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(obj)); };

let guideScript = [];            // turnos scripteados del cerebro-guía
const guideCalls = [];           // cada POST /v1/cuarto/guide con su body (para contar turnos)
let runScript = [];              // respuestas scripteadas de /v1/puppets/run
const runCalls = [];             // cada POST /v1/puppets/run con su body
const approvals = [];            // cada POST /v1/runs/*/approve
const downloads = [];            // cada GET de descarga real

const RECETA = { schema_version: "v1", meta: { name: "correo", nicho: "general", output_type: "informe" },
  model: { primary: "opus", max_turns: 4 }, belt: { belt_ref: "belts/inline.yaml" },
  framing: { inline: "Sos un asistente de prueba." }, rag: { enabled: false }, keys: {}, gates: {} };

const server = http.createServer(async (req, res) => {
  req.on("error", () => {}); res.on("error", () => {});
  const u = new URL(req.url, "http://x");
  const p = u.pathname;
  if (p.startsWith("/v1/") || p === "/health" || p.startsWith("/catalog/")) {
    const chunks = []; for await (const c of req) chunks.push(c);
    const raw = Buffer.concat(chunks).toString() || "";
    let body = null; try { body = raw ? JSON.parse(raw) : null; } catch {}

    if (p === "/v1/cuarto/guide") {
      guideCalls.push(body || {});
      const turn = guideScript.shift() || { content: "listo", tool_calls: [] };
      return json(res, 200, { ...turn, model_final: "opus-4.8" });
    }
    if (p === "/v1/icons") return json(res, 200, { known: ["gmail", "stripe"] });
    if (p.startsWith("/v1/icons/")) { res.writeHead(200, { "Content-Type": "image/png" }); return res.end(PNG_1x1); }
    if (p === "/v1/auth/local") return json(res, 200, { id: "u-p7", session_token: "tok-p7", email: "p7@aleph" });
    if (p === "/v1/brains/status") return json(res, 200, {
      providers: { claude_cli: { provider: "claude_cli", state: "ready", detail: "sesión activa", installed: true } },
      service: { state: "ready", mode: "shared" } });
    if (p === "/v1/motor/estado") return json(res, 200, { tipo: "cerebro", ref: "opus", estado: "probado", causa: null, evidencia: { detail: "corrió" }, ts: 1700000000 });
    if (p === "/v1/classify-turn") return json(res, 200, { turn: "chat" });
    if (p === "/v1/chats" && req.method === "POST") return json(res, 200, { id: "chat-p7" });
    if (p.startsWith("/v1/chats")) return json(res, 200, { id: "chat-p7", messages: [], chats: [] });
    if (/^\/v1\/users\/[^/]+\/puppets$/.test(p)) return json(res, 200, { puppets: [{ id: "p1", name: "Agente de prueba", config: RECETA }] });
    if (p === "/v1/puppets/run") {
      runCalls.push(body || {});
      const r = runScript.shift() || { answer: "ok", record: {} };
      return json(res, 200, r);
    }
    if (/^\/v1\/runs\/[^/]+\/approve$/.test(p)) {
      approvals.push({ path: p, body });
      return json(res, 200, body && body.ok
        ? { status: "executed", executed: true, receipts: [{ ok: true, what: "correo enviado", ref: "msg-77" }] }
        : { status: "rejected", executed: false });
    }
    if (/\/download$/.test(p)) {
      downloads.push(p);
      res.writeHead(200, { "Content-Type": "text/markdown" }); return res.end("# informe\n\nreal.");
    }
    if (/^\/v1\/sessions\/[^/]+\/artifacts\//.test(p)) return json(res, 200, { artifact: { versions: [{ content: "# informe\n\nreal." }] } });
    return json(res, 200, {});
  }
  try {
    const f = join(DESIGN, decodeURIComponent(p).replace(/^\//, ""));
    const b = await readFile(f);
    res.writeHead(200, { "Content-Type": MIME[extname(f)] || "application/octet-stream" });
    res.end(b);
  } catch { res.writeHead(404); res.end("nf"); }
});
server.on("clientError", (e, s) => { try { s.destroy(); } catch {} });
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));

/* el server que contesta TIENE que ser el mío (§581aa1c: veredicto sobre árbol propio) */
{
  const probe = await fetch(`http://127.0.0.1:${PORT}/chat/opciones.js`).then((r) => r.text()).catch(() => "");
  if (!/OPCIONES POR TURNO · el contrato transversal/.test(probe)) {
    console.error(`✗ el server de :${PORT} NO es el de este árbol — abortando antes de firmar nada ajeno`);
    process.exit(2);
  }
}

const SESSION = `try{
  sessionStorage.setItem("puppet_user", JSON.stringify({id:"u-p7",session_token:"tok-p7",email:"p7@aleph"}));
  localStorage.setItem("aleph.cuarto.guideBrain","opus");
  localStorage.setItem("aleph-active-brain","claude_cli");
  localStorage.setItem("aleph-brain-configuration", JSON.stringify({version:1,mode:"cli",id:"claude_cli",cliModel:""}));
  localStorage.setItem("aleph-lang","es");
}catch(e){}`;

const browser = await webkit.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.addInitScript(SESSION);
const external = [], errs = [];
await ctx.route("**/*", (route) => {
  const url = route.request().url();
  if (!url.startsWith(`http://127.0.0.1:${PORT}`) && !url.startsWith("data:") && !url.startsWith("blob:")) {
    external.push(url); return route.abort();
  }
  route.continue();
});

const TC = (name, args) => ({ id: "tc" + Math.random().toString(36).slice(2, 8), type: "function",
  function: { name, arguments: JSON.stringify(args) } });
const BLOQUE = (tool, args) => "```aleph:opciones\n" + JSON.stringify({ tool, args }) + "\n```";

/* SIEMPRE la ÚLTIMA caja de la familia. Los mensajes viejos siguen en el hilo (con sus
 * botones apagados): apuntarle a `[0]` mide el turno ANTERIOR y deja pasar defectos del
 * actual — pasó en la primera corrida de la calibración en rojo. */
const btnsUlt = (page, qa, familia) => page.evaluate(([q, f]) => {
  const caja = window[q](`.ac-opts[data-familia="${f}"]`).pop();
  return caja ? [...caja.querySelectorAll(".ac-opt")].map((b) => (b.textContent || "").trim()) : [];
}, [qa, familia]);
const tapUlt = (page, qa, familia, re) => page.evaluate(([q, f, r]) => {
  const caja = window[q](`.ac-opts[data-familia="${f}"]`).pop();
  if (!caja) return false;
  const b = [...caja.querySelectorAll(".ac-opt")].find((x) => new RegExp(r).test((x.textContent || "").trim()));
  if (!b) return false;
  b.click(); return true;
}, [qa, familia, re]);
const finUlt = (page, qa, familia) => page.evaluate(([q, f]) => {
  const caja = window[q](`.ac-opts[data-familia="${f}"]`).pop();
  return caja ? caja.querySelectorAll(".ac-fin").length : -1;
}, [qa, familia]);

console.log(`══ VERIFY · OPCIONES POR TURNO (WebKit → stub :${PORT})${ROJO ? "  ·  CALIBRACIÓN EN ROJO: " + ROJO : ""} ══`);

/* ══ 0 · i18n ES/EN EN LOCKSTEP · sin browser, sobre el módulo mismo ═══════════════════
 * Los labels de T2/T3/T4/T5 son NUESTROS (el modelo elige QUÉ acción, el producto elige
 * CÓMO se llama): si una clave existe en un idioma y no en el otro, la superficie en inglés
 * muestra español y nadie se entera. Se mide acá, que es barato, en vez de esperar a verlo. */
{
  const M = await import("./opciones.js");
  console.log("\n── 0 · i18n ES/EN en lockstep ──");
  const kEs = Object.keys(M.STRINGS.es).sort(), kEn = Object.keys(M.STRINGS.en).sort();
  ok(kEs.length === kEn.length && kEs.every((k, i) => k === kEn[i]),
     "STRINGS: las MISMAS claves en ES y EN", `${kEs.length} vs ${kEn.length}`);
  ok(kEs.every((k) => String(M.STRINGS.en[k] || "").trim()), "…y ninguna entrada EN quedó vacía",
     kEs.filter((k) => !String(M.STRINGS.en[k] || "").trim()).join(", ") || "ninguna");
  // Una entrada IDÉNTICA en los dos idiomas casi siempre es un olvido de traducción. Las que
  // de verdad se escriben igual van declaradas acá, una por una: así un olvido nuevo no se
  // puede esconder detrás de "y bueno, alguna se repite".
  const IGUALES_A_PROPOSITO = new Set(["apr.no"]);   // "No" es "No" en los dos idiomas
  const repes = kEs.filter((k) => M.STRINGS.en[k] === M.STRINGS.es[k] && !IGUALES_A_PROPOSITO.has(k));
  ok(repes.length === 0, "…y ninguna quedó copiada del español sin declararlo", repes.join(", ") || "ninguna");
  const tEs = M.OPCIONES_TOOLS("es"), tEn = M.OPCIONES_TOOLS("en");
  ok(tEs.length === 5 && tEn.length === 5, "las 5 tools existen en los dos idiomas");
  ok(tEs.every((t, i) => t.function.name === tEn[i].function.name), "…con los MISMOS nombres (el contrato no se traduce)");
  ok(tEn.every((t) => /WHEN NO|CONTRACT PROHIBITION|TURN RULE/.test(t.function.description)),
     "…y la doctrina EN está escrita, no es el español disfrazado");
  ok(tEs.every((t) => /CUÁNDO NO|REGLA DE TURNO|PROHIBICIÓN/.test(t.function.description)),
     "…y la doctrina ES también");
  ok(/OPTIONS PER TURN/.test(M.doctrinaSistema("en", { superficie: "sala", transporte: "bloque" })) &&
     /OPCIONES POR TURNO/.test(M.doctrinaSistema("es", { superficie: "sala", transporte: "bloque" })),
     "la doctrina del system sale en el idioma de la sesión");
  // el parser: el humano JAMÁS ve JSON crudo, y un bloque roto se REPORTA (no se traga)
  const ex = M.extraer('Hola.\n\n```aleph:opciones\n{"tool":"redirigir","args":{"mensaje":"m","destino":"cuarto"}}\n```\n');
  ok(ex.texto === "Hola." && ex.llamadas.length === 1, "extraer(): saca el bloque y deja la prosa limpia", JSON.stringify(ex.texto));
  const roto = M.extraer("Hola.\n\n```aleph:opciones\n{no es json\n```");
  ok(roto.llamadas.length === 0 && roto.rotos.length === 1, "…y un bloque roto se REPORTA, no se traga", JSON.stringify(roto.rotos));
}

/* ══════════════════════════════════════════════════════════════════════════════════
 * BLOQUE A · EL GUÍA — las 5 familias como TOOL CALLS de verdad
 * ══════════════════════════════════════════════════════════════════════════════════ */
const g = await ctx.newPage();
g.on("pageerror", (e) => errs.push("[guia] " + String(e).slice(0, 200)));
await g.goto(`http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded", timeout: 30000 });
await g.waitForFunction(() => !!window.__guide, null, { timeout: 25000 }).catch(() => {});
await sleep(1200);
await g.evaluate(() => document.getElementById("copBtn").click());
await sleep(2500);

const gQA = (sel) => g.evaluate((s) => window.__guiaQA(s).map((n) => (n.textContent || "").trim()), sel);
const gN = (sel) => g.evaluate((s) => window.__guiaQA(s).length, sel);
const gTexto = () => g.evaluate(() => { const sr = window.__guiaQ("#messages"); return sr ? sr.textContent : ""; });
const decir = async (t) => { await g.evaluate((x) => window.__ensureGuiaChat().send(x), t); };

console.log("\n── A1 · el chat del Guía abre LIMPIO (mueren las chips de arranque) ──");
ok(await gN(".ac-sug") === 0, "cero chips de arranque en el Guía", String(await gN(".ac-sug")));
ok(/guía padrino|godfather/i.test(await g.evaluate(() => (window.__guiaQ(".ac-intro") || {}).textContent || "")),
   "…pero el saludo sigue (el chat no queda mudo, sólo sin mueble)");
ok(await gN(".ac-opts") === 0, "y cero opciones antes de que haya un turno");
await g.screenshot({ path: fileURLToPath(new URL("../../../../reports/step5/p7-guia-limpio.png", import.meta.url)) }).catch(() => {});

console.log("\n── A2 · T1 preguntar_opciones · el ciclo completo ──");
guideScript = [
  { content: "Antes de armarlo necesito una cosa.", tool_calls: [TC("preguntar_opciones", {
      mensaje: "¿Para qué lo vas a usar?",
      preguntas: [{ pregunta: "¿Para qué lo vas a usar?", tipo: "single",
        opciones: [{ label: "Para mí" }, { label: "Para un cliente" }] }] })] },
  { content: "Perfecto, lo armo para un cliente.", tool_calls: [] },
];
const callsAntes = guideCalls.length;
await decir("armame un agente de research");
await sleep(2500);
const nCallsT1 = guideCalls.length - callsAntes;
const labels = await gQA(".ac-opt");
ok(await gN('.ac-opts[data-familia="preguntar_opciones"]') === 1, "el agente pregunta y las opciones aparecen EN el mensaje");
ok(labels.length === 2, "dos opciones tocables", labels.join(" / "));
ok(/¿Para qué lo vas a usar\?/.test(await gTexto()), "…con su línea conversacional antes (jamás opciones mudas)");
// REGLA DE TURNO: emitió opciones ⇒ el turno TERMINÓ. Una sola vuelta al cerebro.
ok(nCallsT1 === 1, "el turno del agente TERMINÓ al emitir (no se auto-contestó)", `${nCallsT1} vuelta(s) al cerebro`);
ok(!/Perfecto, lo armo/.test(await gTexto()), "…y no escribió nada debajo de su propia pregunta");

const antesTap = guideCalls.length;
await g.evaluate(() => window.__guiaQA(".ac-opt").filter((b) => /cliente/i.test(b.textContent))[0].click());
await sleep(2200);
const marcadas = await g.evaluate(() => window.__guiaQA(".ac-opt").map((b) => ({ t: (b.textContent || "").trim(), e: b.getAttribute("data-elegida"), a: b.getAttribute("data-apagada") })));
ok(marcadas.some((m) => /cliente/i.test(m.t) && m.e === "1"), "la elegida queda MARCADA", JSON.stringify(marcadas));
ok(marcadas.some((m) => /Para mí/i.test(m.t) && m.a === "1"), "…y el resto APAGADO");
// EL TRUCO DEL TRANSCRIPT: el label es el MENSAJE del humano, no un tool result.
const burbujasUsuario = await g.evaluate(() => window.__guiaQA(".deep-chat-outer-container-role-user").map((n) => (n.textContent || "").trim()));
ok(burbujasUsuario.some((t) => /Para un cliente/i.test(t)), "el label entró como MENSAJE DEL HUMANO", JSON.stringify(burbujasUsuario.slice(-2)));
const ultimo = guideCalls[guideCalls.length - 1] || {};
const msgs = (ultimo.messages || []);
const ultUser = [...msgs].reverse().find((m) => m.role === "user") || {};
ok(guideCalls.length === antesTap + 1, "el tap abrió UN turno nuevo", `${guideCalls.length - antesTap}`);
ok(/Para un cliente/i.test(String(ultUser.content || "")), "…y el cerebro lo ve como lo que el humano contestó", JSON.stringify(String(ultUser.content || "").slice(0, 40)));
ok(/Perfecto, lo armo para un cliente/.test(await gTexto()), "…y el agente continúa coherente");

console.log("\n── A3 · el contrato se ENFORCEA (topes duros, no buen gusto) ──");
const opsAntes = await gN(".ac-opts");
guideScript = [
  { content: "", tool_calls: [TC("preguntar_opciones", { mensaje: "elegí", preguntas: [{ pregunta: "¿?", opciones: [{ label: "Sí" }] }] })] },
  { content: "Perdón — te lo digo en prosa.", tool_calls: [] },
];
await decir("probá con una sola opción");
await sleep(2200);
ok(await gN(".ac-opts") === opsAntes, "una sola opción se RECHAZA (menos de 2 no es una elección)");
const rechazo = guideCalls[guideCalls.length - 1] || {};
const toolMsg = ((rechazo.messages || []).filter((m) => m.role === "tool").pop() || {});
ok(/mínimo es 2/.test(String(toolMsg.content || "")), "…y el error vuelve al modelo para que corrija", String(toolMsg.content || "").slice(0, 80));

const opsAntes2 = await gN(".ac-opts");
guideScript = [
  { content: "", tool_calls: [TC("preguntar_opciones", { mensaje: "elegí", preguntas: [{ pregunta: "¿?", opciones: [
      { label: "esta opción tiene demasiadas palabras" }, { label: "corta" }] }] })] },
  { content: "Ok.", tool_calls: [] },
];
await decir("probá con un label largo");
await sleep(2200);
ok(await gN(".ac-opts") === opsAntes2, "un label de más de 3 palabras se RECHAZA");

const opsAntes2b = await gN(".ac-opts");
guideScript = [
  { content: "", tool_calls: [TC("preguntar_opciones", { mensaje: "elegí", preguntas: [
      { pregunta: "a", opciones: [{ label: "sí" }, { label: "no" }] },
      { pregunta: "b", opciones: [{ label: "sí" }, { label: "no" }] },
      { pregunta: "c", opciones: [{ label: "sí" }, { label: "no" }] },
      { pregunta: "d", opciones: [{ label: "sí" }, { label: "no" }] }] })] },
  { content: "Ok.", tool_calls: [] },
];
await decir("probá con cuatro preguntas");
await sleep(2200);
ok(await gN(".ac-opts") === opsAntes2b, "4 preguntas se RECHAZA: 3 es techo duro, no meta");

const opsAntes3 = await gN(".ac-opts");
guideScript = [
  { content: "", tool_calls: [TC("accion_de_producto", { mensaje: "listo", producto: { tipo: "informe", titulo: "Cierre" }, acciones: ["enviar"] })] },
  { content: "Ok.", tool_calls: [] },
];
await decir("probá un botón que no corresponde");
await sleep(2200);
const toolMsg2 = ((guideCalls[guideCalls.length - 1] || {}).messages || []).filter((m) => m.role === "tool").pop() || {};
ok(/no lleva \[enviar\]/i.test(String(toolMsg2.content || "")), "un informe NO lleva [Enviar]: el botón nativo depende del tipo", String(toolMsg2.content || "").slice(0, 90));
ok(await gN('.ac-opts[data-familia="accion_de_producto"] .ac-opt') === 0, "…y no se pintó ningún botón");

console.log("\n── A4 · T3 camino_de_falta · el botón sale de caminoDe, no del modelo ──");
guideScript = [
  { content: "El proveedor devolvió error.", tool_calls: [TC("camino_de_falta", {
      mensaje: "El proveedor cortó — no es tuyo, es de ellos.", causa: "error_upstream" })] },
];
await decir("qué pasó recién");
await sleep(2200);
const camLabels = await btnsUlt(g, "__guiaQA", "camino_de_falta");
// [Integración C1 · P3 §2] El contrato de acción sigue siendo `reintentar`, pero el único
// rótulo visible canónico se fusionó con la prueba de la pieza: «Probar de nuevo».
ok(camLabels[0] === "Probar de nuevo", "el label es el CANÓNICO de caminoDe («Probar de nuevo»), no el que escriba el modelo", camLabels.join(" / "));
ok(camLabels.includes("Ver error"), "…con su acción extra del mismo diccionario", camLabels.join(" / "));
ok(await tapUlt(g, "__guiaQA", "camino_de_falta", "^Probar de nuevo$"), "el botón está ahí para tocarlo");
await sleep(1000);
ok(await finUlt(g, "__guiaQA", "camino_de_falta") === 1, "el tap deja DESENLACE (nunca un botón que se toca y no pasa nada)");
// cerrado es CERRADO: una opción ya decidida no se vuelve a disparar (ni con un click sintético)
const finAntesRetap = await finUlt(g, "__guiaQA", "camino_de_falta");
await tapUlt(g, "__guiaQA", "camino_de_falta", "^Probar de nuevo$");
await sleep(700);
ok(await finUlt(g, "__guiaQA", "camino_de_falta") === finAntesRetap, "…y re-tocarla NO la vuelve a disparar");
// una causa que el diccionario NO conoce no inventa botón (regla de caminoDe)
guideScript = [
  { content: "", tool_calls: [TC("camino_de_falta", { mensaje: "algo falta", causa: "causa_que_no_existe" })] },
  { content: "Te lo digo en prosa entonces.", tool_calls: [] },
];
await decir("y esto otro");
await sleep(2200);
const toolMsg3 = ((guideCalls[guideCalls.length - 1] || {}).messages || []).filter((m) => m.role === "tool").pop() || {};
ok(/desconocida/.test(String(toolMsg3.content || "")), "una causa inventada se RECHAZA antes de mandar a nadie a ningún lado", String(toolMsg3.content || "").slice(0, 80));

console.log("\n── A5 · T4 aprobar · el tap ES el consentimiento ──");
guideScript = [
  { content: "Voy a sacar la pieza del Cuarto, pero pido tu OK.", tool_calls: [TC("aprobar", {
      mensaje: "Esto toca tu armado y no se deshace solo.", resumen: "Quitar la pieza de Gmail",
      plan: ["Leer el estado actual", "Quitar la pieza", "Reordenar el Cuarto"], consecuencia: "datos",
      instruccion: "quitá la pieza de gmail" })] },
];
const callsAntesApr = guideCalls.length;
await decir("sacá gmail");
await sleep(2200);
const aprLabels = await btnsUlt(g, "__guiaQA", "aprobar");
ok(aprLabels.length === 3 && /Aprobar/.test(aprLabels[0]) && /Ver qué va a hacer/.test(aprLabels[1]) && /^No$/.test(aprLabels[2]),
   "trae [Aprobar] [Ver qué va a hacer] [No]", aprLabels.join(" / "));
ok(guideCalls.length === callsAntesApr + 1, "NADA corrió antes del tap (una sola vuelta, cero ejecución)");
await tapUlt(g, "__guiaQA", "aprobar", "Ver qué");
await sleep(500);
const plan = await g.evaluate(() => (window.__guiaQA(".ac-plan").pop() || {}).textContent || "");
ok(/Leer el estado actual/.test(plan) && /Reordenar el Cuarto/.test(plan), "[Ver qué va a hacer] despliega el PLAN REAL, paso por paso", JSON.stringify(plan.slice(0, 70)));
const callsAntesNo = guideCalls.length;
await tapUlt(g, "__guiaQA", "aprobar", "^No$");
await sleep(900);
ok(guideCalls.length === callsAntesNo, "[No] CANCELA de verdad: cero turnos nuevos, nada corrió");
// [integración tanda-B] la aserción medía la PUNTUACIÓN, no el desenlace: T6 §10 reescribió
// «No lo hice. Nada corrió.» a una sola oración («No lo hice — nada corrió.») porque dos
// oraciones son HARD en la ley minimalista. Ninguna rama sola lo vio (T6 no corre esta vara;
// P8 la actualizó sobre un árbol sin T6). Se mide el desenlace, en cualquiera de las dos formas.
ok(/No lo hice\s*[—.]\s*[Nn]ada corrió\./.test(await gTexto()), "…y lo dice");

guideScript = [
  { content: "Pido tu OK antes.", tool_calls: [TC("aprobar", { mensaje: "Toca tu armado.", resumen: "Ordenar el Cuarto",
      plan: ["Reubicar cada pieza suelta"], consecuencia: "datos", instruccion: "ordená el cuarto" })] },
  { content: "Listo — ordené el Cuarto.", tool_calls: [TC("organizar_cuarto", { criterio: "auto" })] },
  { content: "Quedó ordenado.", tool_calls: [] },
];
await decir("ordená esto");
await sleep(2200);
const callsAntesOk = guideCalls.length;
await tapUlt(g, "__guiaQA", "aprobar", "^Aprobar$");
await sleep(2600);
ok(guideCalls.length > callsAntesOk, "[Aprobar] SÍ ejecuta (el turno arranca recién con el tap)");
ok(await gN(".ac-act") > 0, "…y la ejecución deja evidencia visible (card de acción real)");

console.log("\n── A6 · T5 redirigir · llegar es quedar PARADO en el lugar correcto ──");
const piezas = await g.evaluate(() => (window.__cuarto.placedTiles() || []).map((t) => t.id));
guideScript = [
  { content: "Eso se ajusta en el Cuarto.", tool_calls: [TC("redirigir", {
      mensaje: "El cerebro se cambia acá mismo — te abro el selector.", destino: "cerebro" })] },
];
await decir("cómo cambio el cerebro");
await sleep(2200);
const redLabels = await btnsUlt(g, "__guiaQA", "redirigir");
ok(redLabels.length === 1 && /Elegir modelo/.test(redLabels[0]), "trae su botón de redirección", redLabels.join(" / "));
await tapUlt(g, "__guiaQA", "redirigir", "Elegir modelo");
await sleep(1200);
ok(await g.evaluate(() => { const i = document.getElementById("inspector"); return !!i && i.classList.contains("open"); }),
   "el tap ABRE de verdad el lugar (inspector del Núcleo), no una pantalla genérica");

console.log("\n── A7 · los casos NEGATIVOS (tan obligatorios como los positivos) ──");
const opsPrevias = await gN(".ac-opts");
guideScript = [{ content: "Uf, tres horas con lo mismo cansa a cualquiera. Contame qué pasó.", tool_calls: [] }];
await decir("uf, llevo tres horas peleándome con esto");
await sleep(2000);
ok(await gN(".ac-opts") === opsPrevias, "el desahogo NO recibe un menú: cero opciones");
guideScript = [{ content: "Yo iría por SQLite: es un archivo, cero servidor, y a tu escala alcanza.", tool_calls: [] }];
await decir("¿conviene postgres o sqlite?");
await sleep(2000);
ok(await gN(".ac-opts") === opsPrevias, "«¿A o B?» del humano recibe ANÁLISIS, no sus botones de vuelta");
ok(/SQLite/.test(await gTexto()), "…y el análisis está");
guideScript = [{ content: "Con esos datos ya avanzo: lo armo para tu cliente, en inglés, para el viernes.", tool_calls: [] }];
await decir("hacelo para mi cliente, en inglés, para el viernes");
await sleep(2000);
ok(await gN(".ac-opts") === opsPrevias, "con los constraints ya dados NO se re-pregunta");

console.log("\n── A8 · PROHIBICIÓN DE CONTRATO · la afirmación pre-tap se DETECTA ──");
const prosaPretap = ROJO === "pretap"
  ? "Listo, ya lo envié."                       // ← el defecto inyectado a propósito
  : "Te lo dejo listo para enviar.";
guideScript = [
  { content: prosaPretap, tool_calls: [TC("aprobar", { mensaje: "Pido tu OK.", resumen: "Enviar el correo",
      plan: ["Abrir el borrador", "Enviarlo"], consecuencia: "cuenta" })] },
];
await decir("mandá ese correo");
await sleep(2200);
const contrato = await g.evaluate(() => window.__alephOpcionesContrato);
ok(contrato && contrato.ok === true, "el turno NO afirma la acción antes del tap", JSON.stringify((contrato || {}).violaciones || []));

// VA ÚLTIMO A PROPÓSITO: este camino NAVEGA de verdad (falta_key aterriza en el Centro de
// Conexiones, por el puente que ya existía), así que se lleva puesta la página del Guía.
console.log("\n── A9 · T3 · el camino que NAVEGA aterriza donde corresponde ──");
guideScript = [
  { content: "Gmail no puede sin su llave.", tool_calls: [TC("camino_de_falta", {
      mensaje: "Gmail necesita tu llave — sin eso no toco tu correo.", causa: "falta_key" })] },
];
await decir("por qué no anda gmail");
await sleep(2200);
// la ÚLTIMA caja de esta familia: en el hilo ya hay una de A4 y sus botones siguen ahí
// (apagados) — apuntarle al [0] mediría el mensaje viejo.
const camKey = await btnsUlt(g, "__guiaQA", "camino_de_falta");
ok(camKey[0] === "Poner la llave", "el label canónico de falta_key («Poner la llave»)", camKey.join(" / "));
const urlAntes = g.url();
await tapUlt(g, "__guiaQA", "camino_de_falta", "^Poner la llave$");
await sleep(1800);
// [FIX-P1B · §1] Esto MEDÍA UNA NAVEGACIÓN: el tap se llevaba puesta la página del Guía y
// aterrizaba en Modelos. Aterrizar en algo real era la mitad correcta; irse de la
// conversación era la mitad equivocada — la persona perdía el hilo por poner una llave.
// Ahora la reparación abre EL WORKFLOW DE SU TIPO anclado, sin sacar a nadie de donde
// está. La aserción se endurece: además de que aparezca el workflow, se exige que la
// conversación SIGA ahí (antes esto no se podía ni preguntar).
const aterrizaje = await g.evaluate(() => {
  const w = document.querySelector(".wz");
  return { hayWorkflow: !!w, tipo: w ? w.dataset.tipo : null,
           titulo: w ? (w.querySelector(".wz-tit") || {}).textContent : null };
});
ok(aterrizaje.hayWorkflow, "el tap ATERRIZA en el workflow de su tipo, ahí mismo",
   `${aterrizaje.tipo} · ${aterrizaje.titulo}`);
ok(g.url() === urlAntes, "…y la conversación NO se pierde (no hay navegación)", g.url().split("/").pop());

ok(errs.filter((e) => e.startsWith("[guia]")).length === 0, "el Guía: cero errores de página", errs.filter((e) => e.startsWith("[guia]")).join(" · ") || "ninguno");

/* ══════════════════════════════════════════════════════════════════════════════════
 * BLOQUE B · LA SALA — el mismo contrato por el transporte de bloque
 * ══════════════════════════════════════════════════════════════════════════════════ */
const s = await ctx.newPage();
s.on("pageerror", (e) => errs.push("[sala] " + String(e).slice(0, 200)));
await s.goto(`http://127.0.0.1:${PORT}/sala/sala.html?puppet=p1`, { waitUntil: "domcontentloaded", timeout: 30000 });
await s.waitForFunction(() => window.__salaChat && window.__salaShadow && window.__salaShadow(), null, { timeout: 25000 }).catch(() => {});
await sleep(3000);

const sQA = (sel) => s.evaluate((x) => window.__salaQA(x).map((n) => (n.textContent || "").trim()), sel);
const sN = (sel) => s.evaluate((x) => window.__salaQA(x).length, sel);
const sTexto = () => s.evaluate(() => { const b = window.__salaQ("#messages"); return b ? b.textContent : ""; });
const pedir = async (t) => { await s.evaluate((x) => window.__salaChat.send(x), t); };

console.log("\n── B1 · La Sala abre LIMPIA ──");
ok(await sN(".ac-sug") === 0, "cero chips de arranque en La Sala", String(await sN(".ac-sug")));
ok(await sN(".ac-opts") === 0, "…y cero opciones antes del primer turno");
await s.screenshot({ path: fileURLToPath(new URL("../../../../reports/step5/p7-sala-limpia.png", import.meta.url)) }).catch(() => {});

console.log("\n── B2 · la DOCTRINA llega al system del agente (no al panel de controles) ──");
runScript = [{ answer: "Adelante.", record: {} }];
await pedir("hola");
await sleep(2600);
const primeraRun = runCalls[runCalls.length - 1] || {};
const inline = String((((primeraRun.recipe || {}).framing) || {}).inline || "");
ok(/## OPCIONES POR TURNO/.test(inline), "la doctrina viaja en recipe.framing.inline");
ok(/REGLA DE TURNO/.test(inline) && /CUÁNDO NO/.test(inline) && /REGLA DE ORO/.test(inline),
   "…con cuándo-NO, regla de oro y regla de turno");
/* ── ASERCIÓN INVERTIDA A PROPÓSITO (FIX-P9 §3) — no «arreglada para que pase» ──────
 * ANTES: `/aleph:opciones/ && /preguntar_opciones/` — el system tenía que llevar el
 * PROTOCOLO DEL BLOQUE CERCADO y los 5 schemas escritos en texto, porque La Sala no tenía
 * canal de tools (era la deuda #1 declarada en el informe de P7).
 * AHORA: `/v1/puppets/run` acepta `client_tools`, así que la familia viaja como TOOLS REALES en
 * el body y el system ya no necesita —ni debe— cargar medio protocolo en prosa. La aserción
 * vieja mide una ley muerta; ésta mide la nueva, y es MÁS dura: exige que el fence esté
 * AUSENTE del system Y que las 6 estén PRESENTES en el body (las 5 opciones + conexión inline).
 * (El fence sigue funcionando como transporte donde no hay loop de tools —el agente inline
 *  por /puppets/run/stream—; B3-B7 de esta misma vara lo siguen ejercitando.) */
ok(!/aleph:opciones/.test(inline), "…y el system YA NO carga el protocolo del bloque (client_tools)",
   `${inline.length} chars de system`);
{
  const ct = (primeraRun.client_tools || []).map((t) => (t.function || {}).name);
  ok(ct.length === 6 && ct.includes("preguntar_opciones") && ct.includes("conectar_inline"),
     "…porque las 6 viajan como client_tools REALES en el body ★", ct.join(" · ") || "ninguna");
}
ok(/Sos un asistente de prueba/.test(inline), "…SIN pisar el framing del autor del agente");
ok(!/OPCIONES POR TURNO/.test(String(await s.evaluate(() => (window.__salaSliceD.state().controls || {}).instructions || ""))),
   "…y la doctrina NO se filtró a las «instrucciones» del usuario en el panel de controles");

console.log("\n── B3 · T2 accion_de_producto · correo → [Enviar] → gate → envío REAL ──");
const prosaB3 = ROJO === "pretap" ? "Listo, ya lo envié." : "Te lo dejo redactado — vos decidís si sale.";
runScript = [{ answer: prosaB3 + "\n\n" + BLOQUE("accion_de_producto", {
    mensaje: "Te lo dejo redactado.", producto: { tipo: "correo", titulo: "Propuesta para Marta", instruccion: "enviá el correo a Marta" },
    acciones: ["enviar", "editar"] }), record: {} }];
await pedir("redactá y enviá un correo a Marta");
await sleep(2800);
if (ROJO === "descableado") {
  await s.evaluate(() => { delete window.__salaOpciones.destinos.enviar; });   // ← el defecto inyectado
  runScript = [{ answer: "Otra vez.\n\n" + BLOQUE("accion_de_producto", {
      mensaje: "Te lo dejo redactado.", producto: { tipo: "correo", titulo: "Propuesta para Marta", instruccion: "enviá el correo a Marta" },
      acciones: ["enviar", "editar"] }), record: {} }];
  await pedir("de nuevo");
  await sleep(2800);
}
const prodLabels = await btnsUlt(s, "__salaQA", "accion_de_producto");
ok(prodLabels.some((l) => /^Enviar$/.test(l)), "el correo trae SU botón nativo [Enviar]", prodLabels.join(" / ") || "ningún botón");
ok(prodLabels.some((l) => /^Editar$/.test(l)), "…y [Editar]");
ok(!/aleph:opciones|\{"tool"/.test(await sTexto()), "el humano NUNCA ve el JSON crudo (el bloque sale de la prosa)");
const contrato2 = await s.evaluate(() => window.__alephOpcionesContrato);
ok(contrato2 && contrato2.ok === true, "el turno NO dijo «enviado» antes del tap", JSON.stringify((contrato2 || {}).violaciones || []));

// EL TAP. Recién ahora la orden entra al pipeline REAL, y el motor la RETIENE en su gate.
runScript = [{ answer: "Lo dejé frenado esperando tu OK.", run_id: "run-77",
  held_actions: [{ server: "gmail", tool: "send_email", approval_id: "ap-1",
    ux: { que_va_a_hacer: "enviar un correo a Marta", donde_afecta: "tu cuenta de Gmail" } }], record: {} }];
const runsAntes = runCalls.length;
await tapUlt(s, "__salaQA", "accion_de_producto", "^Enviar$");
await sleep(3000);
ok(runCalls.length === runsAntes + 1, "el tap dispara el handler REAL (un run nuevo)", `${runCalls.length - runsAntes}`);
ok(/enviá el correo a Marta/i.test(String((runCalls[runCalls.length - 1] || {}).prompt || "")), "…con la instrucción exacta del producto",
   JSON.stringify(String((runCalls[runCalls.length - 1] || {}).prompt || "").slice(0, 40)));
ok(await finUlt(s, "__salaQA", "accion_de_producto") > 0, "…y el desenlace del botón se ve SIEMPRE");
ok(await sN(".gate") > 0, "…y la orden pasa por el GATE que ya existía (no un gate paralelo)", String(await sN(".gate")));
const apAntes = approvals.length;
await s.evaluate(() => { const b = window.__salaQA(".gate .acts button.ok")[0]; if (b) b.click(); });
await sleep(2200);
ok(approvals.length === apAntes + 1 && approvals[approvals.length - 1].body.ok === true, "el OK del gate ejecuta de verdad", JSON.stringify(approvals[approvals.length - 1] || {}));
ok(/Hecho|envié/i.test(await s.evaluate(() => (window.__salaQ(".gate") || {}).textContent || "")),
   "…y queda la EVIDENCIA del envío", JSON.stringify(await s.evaluate(() => ((window.__salaQ(".gate") || {}).textContent || "").slice(0, 60))));

console.log("\n── B4 · T2 informe → [Descargar] REAL ──");
runScript = [{ answer: "Ahí va.\n\n" + BLOQUE("accion_de_producto", {
    mensaje: "Te dejo el informe.", producto: { tipo: "informe", titulo: "Cierre de mayo" }, acciones: ["descargar"] }), record: {} }];
// pedido SIN verbo de producción: este turno es charla (el ruteo a obra es otro camino y no
// es lo que se está midiendo acá). La obra se materializa DESPUÉS, por el camino real, y el
// handler la resuelve recién en el TAP — que es justo el contrato que se quiere probar.
await pedir("necesito ver el cierre de mayo");
await sleep(2800);
await s.evaluate(() => window.__salaForceArt("Cierre de mayo"));
await sleep(600);
const dlAntes = downloads.length;
await s.evaluate(() => { const b = window.__salaQA(".ac-opt").filter((x) => /^Descargar$/.test(x.textContent.trim())).pop(); if (b) b.click(); });
await sleep(2000);
ok(downloads.length === dlAntes + 1, "[Descargar] baja el archivo DE VERDAD", downloads[downloads.length - 1] || "ninguna descarga");

console.log("\n── B5 · T3 sin visión → el camino que la Sala ya tenía ──");
runScript = [{ answer: "No la vi.\n\n" + BLOQUE("camino_de_falta", {
    mensaje: "Para MIRAR la imagen necesito un cerebro con visión — no adivino sobre algo que no vi.", causa: "sin_vision" }), record: {} }];
await pedir("qué dice esta imagen");
await sleep(2800);
const faltaLabels = await btnsUlt(s, "__salaQA", "camino_de_falta");
ok(faltaLabels.includes("Conectar un modelo de visión"), "trae [Conectar un modelo de visión]", faltaLabels.join(" / "));
await tapUlt(s, "__salaQA", "camino_de_falta", "Conectar un modelo");
await sleep(1500);
// [FIX-P8] el destino de `sin_vision` dejó de ser la pantalla genérica de configuración:
// ahora aterriza en el Centro de Modelos CON LA CATEGORÍA abierta. Que caiga «en algún
// lado» era media honestidad; la otra mitad es dejar a la persona parada donde se
// resuelve, no buscando sola qué apretar.
ok(/Modelos\.dc\.html/.test(s.url()), "…y aterriza en el Centro de Modelos", s.url().split("/").pop());
ok(/[?&]cat=vision/.test(s.url()), "…en la categoría VISIÓN, no en la pantalla genérica", s.url().split("?").pop());
await s.goto(`http://127.0.0.1:${PORT}/sala/sala.html?puppet=p1`, { waitUntil: "domcontentloaded", timeout: 30000 });
await s.waitForFunction(() => window.__salaChat && window.__salaShadow && window.__salaShadow(), null, { timeout: 20000 }).catch(() => {});
await sleep(2600);

console.log("\n── B6 · T5 redirigir → el Cuarto, con la pieza ENFOCADA ──");
runScript = [{ answer: "Eso se equipa allá.\n\n" + BLOQUE("redirigir", {
    mensaje: "Esa herramienta se equipa en el Cuarto — te llevo.", destino: "pieza", pieza_id: piezas[0] || "nucleo" }), record: {} }];
await pedir("dónde equipo gmail");
await sleep(3000);
const irLabels = await btnsUlt(s, "__salaQA", "redirigir");
ok(irLabels.length === 1 && /Abrir la pieza|Ir al Cuarto/.test(irLabels[0]), "trae su botón de redirección", irLabels.join(" / "));
await tapUlt(s, "__salaQA", "redirigir", "Abrir la pieza|Ir al Cuarto");
await sleep(1500);
ok(/Cuarto\.dc\.html/.test(s.url()) && /foco=/.test(s.url()), "navega DE VERDAD y lleva el foco en la URL", decodeURIComponent(s.url().split("/").pop() || ""));

console.log("\n── B7 · el caso NEGATIVO de La Sala ──");
await s.goto(`http://127.0.0.1:${PORT}/sala/sala.html?puppet=p1`, { waitUntil: "domcontentloaded", timeout: 30000 });
await s.waitForFunction(() => window.__salaChat && window.__salaShadow && window.__salaShadow(), null, { timeout: 20000 }).catch(() => {});
await sleep(2600);
runScript = [{ answer: "Contame un poco más y arrancamos.", record: {} }];
await pedir("no sé bien qué necesito");
await sleep(2600);
ok(await sN(".ac-opts") === 0, "una respuesta conversacional NO trae opciones");
ok(await sN(".ac-sug") === 0, "…y el chat sigue sin chips de arranque");

/* ══════════════════════════════════════════════════════════════════════════════════
 * BLOQUE C · el aterrizaje: ?foco= deja al humano PARADO en la pieza
 * ══════════════════════════════════════════════════════════════════════════════════ */
console.log("\n── C · el aterrizaje del foco ──");
const c = await ctx.newPage();
c.on("pageerror", (e) => errs.push("[foco] " + String(e).slice(0, 200)));
await c.goto(`http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html?foco=${encodeURIComponent(piezas[0] || "nucleo")}`,
  { waitUntil: "domcontentloaded", timeout: 30000 });
await c.waitForFunction(() => !!window.__cuarto, null, { timeout: 25000 }).catch(() => {});
await sleep(2500);
ok(await c.evaluate(() => window.__focoAterrizo || null) === (piezas[0] || "nucleo"), "?foco= resuelve la pieza al llegar",
   String(await c.evaluate(() => window.__focoAterrizo || null)));
ok(await c.evaluate(() => { const i = document.getElementById("inspector"); return !!i && i.classList.contains("open"); }),
   "…y el humano queda PARADO en ella (su inspector abierto), no en la pantalla genérica");
const cFoco = await ctx.newPage();
await cFoco.goto(`http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html?foco=no-existe-esta-pieza`, { waitUntil: "domcontentloaded", timeout: 30000 });
await cFoco.waitForFunction(() => !!window.__cuarto, null, { timeout: 25000 }).catch(() => {});
await sleep(5000);   // la espera acotada del foco (3s) + margen: recién ahí se declara honesto
ok(await cFoco.evaluate(() => !window.__focoAterrizo), "una pieza inexistente NO se inventa");
ok(/no encontré la pieza/i.test(await cFoco.evaluate(() => (document.getElementById("status") || {}).textContent || "")),
   "…se dice honesto", await cFoco.evaluate(() => ((document.getElementById("status") || {}).textContent || "").slice(0, 50)));

console.log("\n── cierre ──");
ok(external.length === 0, "CERO requests externos en toda la corrida", external.join(" · ") || "ninguno");
ok(errs.length === 0, "cero errores de página", errs.join(" · ") || "ninguno");

await browser.close();
server.close();
console.log(`\n${fails.length ? "❌ ROJO" : "✅ VERDE"} — ${fails.length ? `${fails.length} fallo(s)` : "todo verde"}`);
if (fails.length) { console.log("FALLAS:"); fails.forEach((f) => console.log("  ✗ " + f)); }
process.exit(fails.length ? 1 : 0);
