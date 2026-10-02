/* verify_conexion_inline.mjs — LA VARA DE LA CONEXIÓN DENTRO DEL TURNO.
 *
 * QUÉ MIDE. Cuando el Guía o La Sala necesitan algo NO conectado, el trámite aparece EN el
 * turno: logo · nombre · input con su formato · link a la página exacta · candado · [Conectar].
 * La llave se valida con los validadores de P11, queda en el VAULT GLOBAL (no en la charla),
 * y la conversación SIGUE sin recargar nada.
 *
 * POR QUÉ CONTRA EL FROZEN, Y NO CONTRA UN SERVER DE NODE.
 * El sidecar congelado sirve SU PROPIA COPIA de `product/app/design` (viaja como `datas` en
 * aleph_sidecar.spec). Un verde sobre el árbol de dev no dice NADA sobre la .app: es la
 * lección de FIX-P10. Acá el HTML, el JS y el CSS los sirve el binario que Tauri lanza.
 *
 * QUÉ ES REAL Y QUÉ ESTÁ SCRIPTEADO — la línea importa, porque una vara que stubbea lo que
 * dice medir no mide nada:
 *   REAL (del frozen)  · el `design/` servido · GET /v1/connectors/{slug} (la ficha canónica)
 *                      · POST /v1/connectors/{slug}/connect (connect_engine, el validador de
 *                        P11) · el VAULT cifrado · GET /v1/users/{id}/keys · /v1/auth/local.
 *   REAL (local)       · EL PROVEEDOR: un servidor propio en :8309 que habla como la API de
 *                        Canvas. Así el validador de P11 hace una request de verdad, con
 *                        veredicto determinista y CERO red externa. La llave buena da 200; la
 *                        mala da 401 — que es exactamente lo que P11 lee como "key_invalida".
 *   SCRIPTEADO         · SÓLO el cerebro: POST /v1/cuarto/guide y POST /v1/puppets/run. El
 *                        modelo decide CUÁNDO emitir la tool; eso no es lo que esta vara mide.
 *
 * CALIBRACIÓN EN ROJO (una vara que no se puede poner roja no prueba nada):
 *   CI_ROJO=sin_bus        → se le saca a la página el aviso cross-superficie (BroadcastChannel
 *                            y el pulso de storage). §5 DEBE fallar: la Sala no se entera.
 *   CI_ROJO=descriptor_404 → la ficha canónica del conector devuelve 404. §2..§4 DEBEN fallar:
 *                            sin ficha no hay formulario, y por lo tanto no hay verde posible.
 *
 * PUERTOS PROPIOS :8308 (frozen) y :8309 (proveedor). Se COMPRUEBAN libres antes de arrancar:
 * un veredicto firmado sobre el sidecar de otra sesión es peor que no tener veredicto (581aa1c).
 *
 *   node product/app/design/chat/verify_conexion_inline.mjs
 *   CI_ROJO=sin_bus node product/app/design/chat/verify_conexion_inline.mjs
 */
import { webkit } from "playwright";
import http from "node:http";
import net from "node:net";
import { mkdtempSync, existsSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
// GUARD _MEI: TMPDIR privado por sidecar + barrido en TODA salida. El bootloader onefile
// deja ~170 MB si el proceso no cierra limpio (91 huérfanos llenaron el disco el 26-jul).
import { spawnFrozen, matarFrozen } from "../../../../qa/lib/frozen_guard.mjs";

const ROOT = fileURLToPath(new URL("../../../../", import.meta.url));
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
const PORT = Number(process.env.CI_PORT || 8308);
const PROV = Number(process.env.CI_PROV_PORT || 8309);
const BASE = `http://127.0.0.1:${PORT}`;
const PROV_URL = `http://127.0.0.1:${PROV}`;
const ROJO = String(process.env.CI_ROJO || "");
const SHOTS = join(ROOT, "reports/step5");

/* El conector de la vara. `canvas` es la elección correcta y no es arbitraria: needs_base_url
 * (self-hosted) significa que el api_base lo pone la persona — así el validador REAL de P11
 * pega contra MI proveedor y no contra internet. Un conector global obligaría a elegir entre
 * salir a la red (flaky, y prohibido acá) o stubbear el validador (y entonces no se mide P11). */
const CONECTOR = "canvas";
const LLAVE_BUENA = "canvas-vara-llave-buena-2026";
const LLAVE_MALA = "canvas-vara-llave-mala";

const fails = [];
const ok = (c, l, x) => { console.log(`${c ? "✓" : "✗"} ${l}${x != null && x !== "" ? "  — " + x : ""}`); if (!c) fails.push(l); };

/* UN CRASH ES UN VEREDICTO, NO UNA SALIDA POR LA VENTANA. Sin esto, una excepción a mitad
 * de camino se lleva puesto el epílogo: no se imprime el resultado, la calibración en rojo
 * no puede decir si vio algo, y —peor— el sidecar frozen queda vivo con su `_MEI` de 170 MB
 * tomando el puerto. Se reporta, se reapea y se sale con el código que corresponde. */
let _cerrar = () => {};
const cierreDuro = (e) => {
  ok(false, "la vara se CAYÓ antes de terminar", String((e && e.stack) || e).split("\n").slice(0, 2).join(" | "));
  try { _cerrar(); } catch (x) {}
  console.log(`\n✗ ${fails.length} FALLAS (corrida incompleta)`);
  if (ROJO) console.log(`── CALIBRACIÓN EN ROJO «${ROJO}»: falló, que es lo que se le pedía. La vara ve.`);
  process.exit(ROJO ? 0 : 1);
};
process.on("uncaughtException", cierreDuro);
process.on("unhandledRejection", cierreDuro);
const seccion = (t) => console.log(`\n══ ${t} ${"═".repeat(Math.max(0, 72 - t.length))}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try { mkdirSync(SHOTS, { recursive: true }); } catch (e) {}

/* ── LOS PUERTOS SON MÍOS O NO HAY VEREDICTO ─────────────────────────────────────── */
for (const p of [PORT, PROV]) {
  await new Promise((resolve, reject) => {
    const probe = net.createConnection({ port: p, host: "127.0.0.1" });
    probe.on("connect", () => { probe.destroy();
      reject(new Error(`:${p} YA ESTÁ OCUPADO. Esta vara mide su propio árbol o no mide nada.\n` +
        `  Liberalo:  lsof -nP -iTCP:${p} -sTCP:LISTEN   →   kill <pid>`)); });
    probe.on("error", () => resolve());
  });
}
if (!existsSync(SIDECAR)) {
  console.log(`✗ no existe el sidecar frozen: ${SIDECAR}\n` +
    `   construílo:  ALEPH_SIDECAR_ONEFILE=1 ALEPH_BUILD=dev product/backend/.venv/bin/pyinstaller \\\n` +
    `                  --clean --noconfirm deploy/fase4/aleph_sidecar.spec`);
  process.exit(1);
}

/* ── EL PROVEEDOR (habla como la API de Canvas) ───────────────────────────────────── */
const provHits = [];
const proveedor = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  const authz = String(req.headers.authorization || "");
  provHits.push(`${req.method} ${u.pathname}`);
  if (u.pathname === "/api/v1/users/self") {
    // 401 sobre llave mala es el veredicto que connect_engine lee como `invalid` → key_invalida.
    if (!authz.includes(LLAVE_BUENA)) {
      res.writeHead(401, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ status: "unauthenticated" }));
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ id: 77, name: "persona usuaria (vara)" }));
  }
  res.writeHead(404, { "Content-Type": "application/json" });
  res.end("{}");
});
await new Promise((r) => proveedor.listen(PROV, "127.0.0.1", r));

/* ── EL SIDECAR FROZEN ────────────────────────────────────────────────────────────── */
const DATADIR = mkdtempSync(join(tmpdir(), "ci-vara-"));
console.log(`── frozen ${SIDECAR}\n── datadir aislado ${DATADIR}\n── proveedor ${PROV_URL}`);
const proc = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
  env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATADIR },
  stdio: ["ignore", "pipe", "pipe"],
});
let salida = "";
proc.stdout.on("data", (d) => (salida += d));
proc.stderr.on("data", (d) => (salida += d));
let vivo = false;
for (let i = 0; i < 160; i++) {
  try { const r = await fetch(BASE + "/health"); if (r.ok) { vivo = true; break; } } catch {}
  await sleep(500);
}
ok(vivo, "el sidecar FROZEN arranca y contesta /health", vivo ? "" : salida.slice(-600));
if (!vivo) { matarFrozen(proc); proveedor.close(); process.exit(1); }

/* EL FROZEN QUE CONTESTA TIENE QUE LLEVAR MI ÁRBOL. Un binario viejo (o el de otra sesión)
 * daría verdes que no son míos — el pecado exacto de 581aa1c. Se prueba pidiéndole el módulo
 * nuevo: si no está DENTRO del bundle, no hay nada que medir. */
{
  const t = await fetch(`${BASE}/chat/conexion-inline.js`).then((r) => r.ok ? r.text() : "").catch(() => "");
  const trae = /conexión dentro del turno \(P7 \+ P11\)/.test(t) && /conectar_inline/.test(t);
  ok(trae, "…y el bundle congelado SÍ trae esta pieza (no es un frozen ajeno)", `${t.length} bytes`);
  if (!trae) { matarFrozen(proc); proveedor.close(); process.exit(2); }
}

/* ══════════════════════════════════════════════════════════════════════════════════
 * §0 · EL CONTRATO DEL MÓDULO — sin browser, que es donde sale más barato
 * ══════════════════════════════════════════════════════════════════════════════════ */
seccion("§0 · el contrato de la tool");
const M = await import("./conexion-inline.js");
const Sem = await import("../cuarto/cuarto.semaforo.js");
{
  const es = M.CONEXION_INLINE_TOOLS("es"), en = M.CONEXION_INLINE_TOOLS("en");
  ok(es.length === 1 && en.length === 1 && es[0].function.name === en[0].function.name &&
     es[0].function.name === "conectar_inline", "una sola tool, con el MISMO nombre en los dos idiomas");
  const props = Object.keys(es[0].function.parameters.properties);
  ok(!props.some((p) => /secret|credential|credencial|api_?key|token|password/i.test(p)),
     "el SCHEMA no tiene dónde meter una credencial ★", props.join(" · "));
  ok(/CUÁNDO|NO usar/.test(es[0].function.description) && /DO NOT use|Use only/.test(en[0].function.description),
     "la contracara de P7 viaja en la doctrina, en los dos idiomas");
  ok(/LOCAL/.test(es[0].function.description) && /OAUTH|OAuth/.test(es[0].function.description),
     "…y la división por tipo está sellada en la descripción (llave · oauth · local)");
  // El validador es la SEGUNDA puerta: aunque un modelo invente un campo, no pasa.
  ok(M.validar({ mensaje: "m", connector: "canvas", tipo: "llave", secret: "sk-robada" }).ok === false,
     "una credencial escondida en los args se RECHAZA ★",
     M.validar({ mensaje: "m", connector: "canvas", tipo: "llave", secret: "x" }).error);
  ok(M.validar({ mensaje: "m", connector: "ca nvas", tipo: "llave" }).ok === false, "un slug inválido se rechaza");
  ok(M.validar({ mensaje: "m", connector: "canvas", tipo: "instalar" }).ok === false, "un tipo fuera de la división se rechaza");
  ok(M.validar({ mensaje: "m", connector: "canvas", tipo: "local" }).ok === false,
     "LOCAL sin comando se rechaza (mostrar el trámite ES el trámite)");
  ok(M.validar({ mensaje: "m", connector: "canvas", tipo: "llave" }).ok === true, "…y el caso legítimo pasa");
  ok(M.OAUTH_RETURN_CONTRACT.type === "aleph:oauth:return" && M.OAUTH_RETURN_CONTRACT.version === 1,
     "el contrato de la vuelta de OAuth está declarado y congelado",
     M.OAUTH_RETURN_CONTRACT.statuses.join("|"));
}
{
  // La familia de P7 creció de 5 a 6 en UN solo lugar: si alguien agrega la tool a una
  // superficie y se olvida de la otra, esto lo caza sin abrir un browser.
  const O = await import("./opciones.js");
  ok(O.CLIENT_TOOL_NAMES.length === 6 && O.CLIENT_TOOL_NAMES.includes("conectar_inline"),
     "la familia del cliente es UNA lista de 6, compartida por las dos superficies",
     O.CLIENT_TOOL_NAMES.join(" · "));
  const B = await import("../cuarto/cuarto.guide.belt.js");
  ok(B.guideTools("es").filter((t) => t.function.name === "conectar_inline").length === 1,
     "…y el belt del Guía la declara exactamente una vez");
}

/* ══════════════════════════════════════════════════════════════════════════════════
 * EL BROWSER — WebKit real (el motor de WKWebView, o sea el de la .app)
 * ══════════════════════════════════════════════════════════════════════════════════ */
const browser = await webkit.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
_cerrar = () => { browser.close().catch(() => {}); matarFrozen(proc); proveedor.close(); };
const externas = [], errs = [];

let guideScript = [];
const guideCalls = [];
let runScript = [];
const runCalls = [];

const RECETA = { schema_version: "v1", meta: { name: "vara", nicho: "general", output_type: "informe" },
  model: { primary: "opus", max_turns: 4 }, belt: { belt_ref: "belts/inline.yaml" },
  framing: { inline: "Sos un asistente de prueba." }, rag: { enabled: false }, keys: {}, gates: {} };

await ctx.addInitScript(([lang, rojo]) => {
  try { localStorage.setItem("aleph-lang", lang);
        localStorage.setItem("aleph.cuarto.guideBrain", "opus");
        localStorage.setItem("aleph-active-brain", "claude_cli");
        localStorage.setItem("aleph-brain-configuration",
          JSON.stringify({ version: 1, mode: "cli", id: "claude_cli", cliModel: "" })); } catch (e) {}
  if (rojo === "sin_bus") {
    /* CALIBRACIÓN EN ROJO: se le cortan a la página LOS DOS avisos cross-superficie.
     * ⚠ GOTCHA de WebKit, medido acá: `localStorage.setItem = fn` NO reemplaza el método —
     * Storage es un legacy platform object con named-property setter, así que eso GUARDA UN
     * ÍTEM llamado "setItem" y el método sigue intacto. Hay que pisar el PROTOTIPO. La
     * primera versión de este knob no cortaba nada y la calibración salía "verde": una
     * calibración rota miente en la dirección más cara, diciendo que la vara ve cuando no ve. */
    try { delete window.BroadcastChannel; } catch (e) {}
    try { Object.defineProperty(window, "BroadcastChannel", { value: undefined, configurable: true }); } catch (e) {}
    const set = Storage.prototype.setItem;
    Storage.prototype.setItem = function (k, v) {
      if (String(k).indexOf("aleph.connection.pulse") === 0) return;
      return set.call(this, k, v);
    };
  }
}, ["es", ROJO]);

/* EL RUTEO. Todo lo que no es 127.0.0.1 se ABORTA y se cuenta (cero red externa). Del resto,
 * sólo el CEREBRO se scriptea; connectors, keys y auth van al frozen sin tocar. */
await ctx.route("**/*", async (route) => {
  const req = route.request();
  const url = req.url();
  if (!url.startsWith(`http://127.0.0.1:${PORT}`) && !url.startsWith("data:") && !url.startsWith("blob:")) {
    externas.push(url); return route.abort();
  }
  const p = new URL(url).pathname;
  const json = (obj) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(obj) });

  if (p === "/v1/cuarto/guide") {
    guideCalls.push(JSON.parse(req.postData() || "{}"));
    const t = guideScript.shift() || { content: "listo", tool_calls: [] };
    return json({ ...t, model_final: "opus-4.8" });
  }
  if (p === "/v1/puppets/run") {
    runCalls.push(JSON.parse(req.postData() || "{}"));
    const r = runScript.shift() || { answer: "listo", record: {} };
    return json(r);
  }
  // Fixture de UI, no de la cosa medida: La Sala necesita UN agente para abrir.
  if (/^\/v1\/users\/[^/]+\/puppets$/.test(p)) return json({ puppets: [{ id: "p1", name: "Agente de la vara", config: RECETA }] });
  if (p === "/v1/classify-turn") return json({ turn: "chat" });
  if (ROJO === "descriptor_404" && p === `/v1/connectors/${CONECTOR}`)
    return route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  return route.continue();     // ← connectors/connect/keys/auth/design: el FROZEN, intacto
});

/* ══════════════════════════════════════════════════════════════════════════════════
 * §1 · EL GUÍA PIDE ALGO NO CONECTADO → EL TRÁMITE APARECE EN EL TURNO
 * ══════════════════════════════════════════════════════════════════════════════════ */
seccion("§1 · el Guía · el trámite aparece EN el turno");
const g = await ctx.newPage();
g.on("pageerror", (e) => errs.push("[guia] " + String(e).slice(0, 200)));
await g.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded", timeout: 45000 });
await g.waitForFunction(() => !!window.__guide, null, { timeout: 40000 }).catch(() => {});
await sleep(1500);
await g.evaluate(() => document.getElementById("copBtn").click());
await sleep(2500);

/* UNA CALIBRACIÓN QUE NO CALIBRA MIENTE PEOR QUE NO TENERLA: se comprueba que el knob
 * REALMENTE cortó lo que dice cortar, antes de creerle a su veredicto. */
if (ROJO === "sin_bus") {
  const cortado = await g.evaluate(() => {
    let pulso = false;
    try { localStorage.setItem("aleph.connection.pulse.v1", "x");
          pulso = localStorage.getItem("aleph.connection.pulse.v1") !== null; } catch (e) {}
    return { bc: typeof BroadcastChannel === "undefined", pulso: !pulso };
  });
  console.log(`── [calibración sin_bus] BroadcastChannel cortado: ${cortado.bc} · pulso de storage cortado: ${cortado.pulso}`);
  if (!cortado.bc || !cortado.pulso) {
    console.log("✗ el knob NO cortó los dos caminos — su veredicto no vale. Abortando.");
    await browser.close(); matarFrozen(proc); proveedor.close(); process.exit(4);
  }
}

const gQ = (sel) => g.evaluate((s) => { const n = window.__guiaQA(s); return n.length; }, sel);
const decir = (t) => g.evaluate((x) => window.__ensureGuiaChat().send(x), t);

const TC = (name, args) => ({ id: "tc" + Math.random().toString(36).slice(2, 8), type: "function",
  function: { name, arguments: JSON.stringify(args) } });

ok(await gQ(".aci") === 0, "antes del turno no hay ningún formulario colgado");

guideScript = [
  { content: "Para leer tu curso necesito tu Canvas.", tool_calls: [TC("conectar_inline", {
      mensaje: "Necesito tu Canvas para leer el material del curso.",
      connector: CONECTOR, tipo: "llave", nombre: "Canvas" })] },
  { content: "Listo, ya entro a tu Canvas. Sigo con el material del curso.", tool_calls: [] },
];
await decir("resumime el material de mi curso");
await sleep(3500);

const pieza = await g.evaluate(() => {
  const n = window.__guiaQA(".aci")[0];
  if (!n) return null;
  return {
    connector: n.dataset.connector, kind: n.dataset.kind, state: n.dataset.state,
    titulo: (n.querySelector(".aci-title b") || {}).textContent || "",
    porque: (n.querySelector(".aci-title small") || {}).textContent || "",
    logo: !!n.querySelector(".aci-logo, .aci-fallback, .bface, img, svg"),
    candado: (n.querySelector(".aci-lock") || {}).textContent || "",
    link: (() => { const a = n.querySelector(".aci-link"); return a && !a.hidden ? a.href : ""; })(),
    hintLink: (n.querySelector("[data-aci-deep-hint]") || {}).textContent || "",
    campos: [...n.querySelectorAll("input")].map((i) => ({ tipo: i.type, ph: i.placeholder })),
    formatos: [...n.querySelectorAll(".aci-field small")].map((s) => s.textContent),
    boton: (n.querySelector("[data-connect]") || {}).textContent || "",
  };
});
ok(!!pieza, "el formulario aparece DENTRO del turno del Guía (no en otra pantalla)");
ok(pieza && pieza.connector === CONECTOR && pieza.state === "ready", "…con su conector y listo para escribir",
   pieza && `${pieza.connector} · ${pieza.state}`);
ok(pieza && pieza.logo, "· LOGO");
/* Y EL LOGO DENTRO DE SU CAJA. Presencia no es layout: la primera captura de esta vara mostró
 * el logo de Canvas a tamaño natural, desbordando su caja de 28px, con el nombre encima. La
 * causa fue de clase, no de detalle: el CSS canónico de brandface se inyecta en el DOCUMENTO
 * y este chat vive en un SHADOW ROOT. Se mide la geometría, que es lo que la persona ve. */
{
  const caja = await g.evaluate(() => {
    const n = window.__guiaQA(".aci")[0];
    const f = n.querySelector(".aci-logo, .aci-fallback"); const t = n.querySelector(".aci-title");
    if (!f || !t) return null;
    const a = f.getBoundingClientRect(), b = t.getBoundingClientRect();
    const im = f.querySelector("img"); const r = im ? im.getBoundingClientRect() : a;
    return { w: Math.round(a.width), h: Math.round(a.height),
             imgW: Math.round(r.width), imgH: Math.round(r.height), solapa: r.right > b.left + 1 };
  });
  ok(caja && caja.w <= 30 && caja.h <= 30, "· …del tamaño que dice tener", caja && `${caja.w}×${caja.h}`);
  ok(caja && caja.imgW <= caja.w && caja.imgH <= caja.h,
     "· …con la imagen DENTRO de su caja (no a tamaño natural) ★", caja && `img ${caja.imgW}×${caja.imgH}`);
  ok(caja && !caja.solapa, "· …y sin encimarse con el nombre ★");
}
ok(pieza && /Canvas/i.test(pieza.titulo), "· NOMBRE", pieza && pieza.titulo);
ok(pieza && /material del curso/.test(pieza.porque), "· POR QUÉ, en la voz del turno", pieza && pieza.porque);
ok(pieza && pieza.campos.some((c) => c.tipo === "password"), "· INPUT de la llave (enmascarado)",
   pieza && JSON.stringify(pieza.campos));
ok(pieza && pieza.campos.some((c) => c.tipo === "url"), "· …y el campo de dominio que este conector self-hosted exige");
ok(pieza && pieza.formatos.some((f) => String(f).trim().length > 3), "· EL FORMATO esperado, de la ficha canónica",
   pieza && JSON.stringify(pieza.formatos));
/* EL LINK, en el caso difícil a propósito. `canvas` es self-hosted: su página exacta vive en
 * el dominio de la institución, así que la ficha declara `{base_url}/profile/settings#…`.
 * Antes de que la persona escriba su dominio NO se ofrece un destino (un link roto es peor
 * que ninguno); apenas lo escribe, el link tiene que volverse REAL. Se mide en ese orden. */
ok(pieza && !pieza.link && /dominio/i.test(pieza.hintLink),
   "· LINK: sin dominio todavía no se ofrece destino, y se dice por qué", pieza && pieza.hintLink.trim());
ok(pieza && /🔒/.test(pieza.candado) && /cifra|vault/i.test(pieza.candado), "· CANDADO de cifrado", pieza && pieza.candado.trim());
ok(pieza && /Conectar/i.test(pieza.boton), "· [Conectar]", pieza && pieza.boton.trim());
// REGLA DE TURNO: el turno se PARA en el trámite. Nada de "listo" antes de que la llave exista.
ok(guideCalls.length === 1, "el turno se DETIENE en el trámite (una sola vuelta al cerebro)", `${guideCalls.length}`);
/* La sesión la crea el propio widget al hidratarse (`asegurarSesion`), así que recién acá
 * existe. Es sesión REAL del frozen: sin ella el vault no tiene dueño y §4 no mediría nada. */
const usuario = await g.evaluate(() => { try { return JSON.parse(sessionStorage.getItem("puppet_user") ||
  localStorage.getItem("puppet_user") || "null"); } catch (e) { return null; } });
ok(!!(usuario && usuario.id && usuario.session_token), "hay sesión REAL del frozen (el vault particiona por dueño)",
   usuario && usuario.id);
ok(!/ya entro a tu Canvas/.test(await g.evaluate(() => (window.__guiaQ("#messages") || {}).textContent || "")),
   "…y el Guía NO afirma tener la conexión antes de tenerla ★");
await g.screenshot({ path: join(SHOTS, "conexion-inline-1-widget.png") }).catch(() => {});

/* ══════════════════════════════════════════════════════════════════════════════════
 * §2 · CALIBRACIÓN EN ROJO · la llave mala trae SU causa, con su botón
 * ══════════════════════════════════════════════════════════════════════════════════ */
seccion("§2 · la llave mala · la causa de P1B, jamás un rojo pelado");
const escribir = async (llave) => {
  await g.evaluate(([base, k]) => {
    const n = window.__guiaQA(".aci")[0];
    const set = (el, v) => { const s = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, "value").set; s.call(el, v);
      el.dispatchEvent(new Event("input", { bubbles: true })); };
    const url = n.querySelector('input[type="url"]'); if (url) set(url, base);
    set(n.querySelector('input[type="password"]'), k);
  }, [PROV_URL, llave]);
};
/* MOUSE REAL: `element.click()` saltea el hit-testing, así que un botón tapado, de 0×0 o
 * deshabilitado "funcionaría" igual. Esta pieza vive dentro de un shadow root, así que se
 * resuelve la caja y se le pega al centro con el mouse del browser. */
const tapear = async (sel) => {
  const box = await g.evaluate((s) => {
    const n = window.__guiaQA(".aci")[0]; const b = n && n.querySelector(s);
    if (!b) return null; const r = b.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    b.scrollIntoView({ block: "center" });
    const r2 = b.getBoundingClientRect();
    return { x: r2.left + r2.width / 2, y: r2.top + r2.height / 2 };
  }, sel);
  if (!box) return false;
  await g.mouse.click(box.x, box.y);
  return true;
};
const estado = () => g.evaluate(() => {
  const n = window.__guiaQA(".aci")[0]; if (!n) return null;
  const s = n.querySelector("[data-aci-status]");
  return { state: n.dataset.state, clase: s ? s.className : "",
    titulo: s ? ((s.querySelector("b") || {}).textContent || "") : "",
    detalle: s ? ((s.querySelector(".aci-detail") || {}).textContent || "") : "",
    boton: s ? ((s.querySelector(".aci-cause") || {}).textContent || "") : "",
    texto: s ? (s.textContent || "") : "" };
});

await escribir(LLAVE_MALA);
{
  const vivo = await g.evaluate(() => {
    const n = window.__guiaQA(".aci")[0]; const a = n.querySelector(".aci-link");
    const h = n.querySelector("[data-aci-deep-hint]");
    return { href: a && !a.hidden ? a.href : "", txt: a ? (a.textContent || "") : "", hint: !!(h && !h.hidden) };
  });
  ok(/^http:\/\/127\.0\.0\.1:\d+\/profile\/settings#access_tokens$/.test(vivo.href),
     "…y apenas hay dominio, el link a la página EXACTA se vuelve real ★", vivo.href);
  ok(!vivo.hint && /llave/i.test(vivo.txt), "…y la explicación de por qué faltaba se retira sola", vivo.txt.trim());
}
const provAntes = provHits.length;
ok(await tapear("[data-connect]"), "el [Conectar] recibe un CLICK REAL de mouse (no un .click() que saltea el hit-testing)");
await sleep(6000);
const rojo = await estado();
// Se DERIVA del diccionario a propósito: el copy se sella en un solo lugar y esta vara lo
// sigue sin editarse. (2026-08-07: pasó de «Tu llave no sirve» a «Credencial inválida» y
// esta línea no se tocó — lo único que hizo falta fue reconstruir el sidecar frozen.)
const CAUSA_ESPERADA = Sem.CAUSAS.key_invalida.es;
const CAMINO_ESPERADO = Sem.caminoDe({ estado: "roto", causa: "key_invalida" }).es;  // "Cambiar la llave"
ok(provHits.length > provAntes, "el validador de P11 hizo una request REAL al proveedor ★",
   provHits.slice(provAntes).join(" · "));
ok(rojo && /bad/.test(rojo.clase), "el widget se pone en rojo", rojo && rojo.clase);
ok(rojo && rojo.titulo.trim() === CAUSA_ESPERADA,
   `la causa es LA DE LA TABLA de P1B, palabra por palabra ★ («${CAUSA_ESPERADA}»)`, rojo && rojo.titulo);
ok(rojo && rojo.boton.trim() === CAMINO_ESPERADO,
   `…con SU botón de la misma tabla ★ («${CAMINO_ESPERADO}»)`, rojo && rojo.boton);
ok(rojo && !/No pudo conectar|No se pudo verificar|Algo salió mal/i.test(rojo.texto),
   "…y JAMÁS el rojo pelado que esta pieza prohíbe ★", rojo && rojo.texto.trim().slice(0, 90));
ok(rojo && rojo.detalle.trim().length > 0, "…y el mensaje crudo del proveedor sigue a la vista",
   rojo && rojo.detalle.trim().slice(0, 70));
// La llave rechazada no se queda en el DOM esperando a que alguien mire.
ok(await g.evaluate(() => { const n = window.__guiaQA(".aci")[0];
     return [...n.querySelectorAll('input[type="password"]')].every((i) => !i.value); }),
   "la llave rechazada se borra del DOM apenas hay veredicto");
await g.screenshot({ path: join(SHOTS, "conexion-inline-2-rojo.png") }).catch(() => {});

ok(await tapear(".aci-cause"), "el botón de la causa es TOCABLE de verdad");
await sleep(600);
ok(await g.evaluate(() => { const n = window.__guiaQA(".aci")[0];
     const i = n.querySelector('input[type="password"]');
     return !!i && (n.getRootNode().activeElement === i || document.activeElement !== document.body); }),
   "…y deja el cursor donde hay que corregir (el camino ACTÚA, no decora)");
// El vault sigue vacío: un rechazo NO guarda nada.
{
  const r = await fetch(`${BASE}/v1/users/${usuario.id}/keys`,
    { headers: { Authorization: "Bearer " + usuario.session_token } }).then((x) => x.json()).catch(() => ({}));
  ok(!((r.keys || []).some((k) => k.provider === CONECTOR)),
     "el vault global sigue SIN esa llave (un rechazo no guarda) ★", JSON.stringify((r.keys || []).map((k) => k.provider)));
}

/* ══════════════════════════════════════════════════════════════════════════════════
 * §3 · LA SALA — la MISMA pieza, por el canal de client_tools de P9
 * (se abre ANTES del verde: §5 exige que se entere SIN recargar)
 * ══════════════════════════════════════════════════════════════════════════════════ */
seccion("§3 · La Sala · el mismo componente, el mismo canal");
const s = await ctx.newPage();
s.on("pageerror", (e) => errs.push("[sala] " + String(e).slice(0, 200)));
await s.goto(`${BASE}/sala/sala.html?puppet=p1`, { waitUntil: "domcontentloaded", timeout: 45000 });
await s.waitForFunction(() => window.__salaChat && window.__salaShadow && window.__salaShadow(), null, { timeout: 40000 }).catch(() => {});
await sleep(3000);

runScript = [{ answer: "Necesito tu Canvas para eso.", record: { client_calls: [
  { tool: "conectar_inline", call_id: "cc_sala_1", turn: 1, args: {
      mensaje: "Necesito tu Canvas para leer las notas.", connector: CONECTOR, tipo: "llave", nombre: "Canvas" } }] } }];
await s.evaluate(() => window.__salaChat.send("traeme mis notas del curso"));
await sleep(4000);

const enSala = await s.evaluate(() => {
  const n = window.__salaQA(".aci")[0]; if (!n) return null;
  return { connector: n.dataset.connector, state: n.dataset.state,
    titulo: (n.querySelector(".aci-title b") || {}).textContent || "",
    campos: [...n.querySelectorAll("input")].length,
    boton: (n.querySelector("[data-connect]") || {}).textContent || "" };
});
ok(!!enSala, "La Sala rinde la MISMA pieza en su turno (un componente, dos superficies)");
ok(enSala && enSala.connector === CONECTOR && enSala.campos >= 2 && /Conectar/i.test(enSala.boton),
   "…completa y operable, sin código propio de La Sala", enSala && JSON.stringify(enSala));
{
  const ct = ((runCalls[runCalls.length - 1] || {}).client_tools || []).map((t) => (t.function || {}).name);
  ok(ct.length === 6 && ct.includes("conectar_inline"),
     "…y viaja al modelo como client_tool REAL en el body (el canal de P9, no un invento) ★", ct.join(" · "));
}
ok(enSala && enSala.state !== "connected", "la Sala AÚN la ve desconectada (todavía no hay llave)", enSala && enSala.state);

/* ══════════════════════════════════════════════════════════════════════════════════
 * §4 · LA LLAVE BUENA · valida con P11 y queda en el VAULT GLOBAL
 * ══════════════════════════════════════════════════════════════════════════════════ */
seccion("§4 · la llave buena · validada y guardada GLOBAL");
await escribir(LLAVE_BUENA);
await tapear("[data-connect]");
await sleep(7000);

const verde = await estado();
ok(verde && verde.state === "connected", "el widget del Guía queda CONECTADO", verde && verde.state);
ok(verde && /good/.test(verde.clase) && /Conectado|guardado/i.test(verde.texto),
   "…y lo dice con el candado cumplido", verde && verde.texto.trim().slice(0, 70));
/* Y EL TRÁMITE SE RETIRA. Un formulario que sigue ahí después del verde invita a pegar otra
 * vez una llave que ya está guardada. Se mide la geometría, no el atributo: `[hidden]` no
 * alcanza contra un `display:flex` de autor — así se veía en la primera captura de La Sala. */
{
  const restos = await g.evaluate(() => {
    const n = window.__guiaQA(".aci")[0];
    const vis = (el) => !!el && !!(el.getBoundingClientRect().width || el.getBoundingClientRect().height);
    return { form: vis(n.querySelector(".aci-form")),
             inputs: [...n.querySelectorAll("input")].filter(vis).length,
             conectar: vis(n.querySelector("[data-connect]")) };
  });
  ok(restos && !restos.form && restos.inputs === 0 && !restos.conectar,
     "…y el formulario SE RETIRA de verdad (cero inputs, cero [Conectar] a la vista) ★",
     restos && JSON.stringify(restos));
}
{
  // LA VERDAD TERMINAL: no lo que pinta la UI, sino lo que el vault del frozen contesta.
  const r = await fetch(`${BASE}/v1/users/${usuario.id}/keys`,
    { headers: { Authorization: "Bearer " + usuario.session_token } }).then((x) => x.json()).catch(() => ({}));
  const fila = (r.keys || []).find((k) => k.provider === CONECTOR);
  ok(!!fila, "la credencial vive en el VAULT GLOBAL del frozen, no en la charla ★",
     JSON.stringify((r.keys || []).map((k) => k.provider)));
  ok(fila && !JSON.stringify(fila).includes(LLAVE_BUENA),
     "…y el vault no la devuelve en claro ni siquiera a su dueño ★", JSON.stringify(fila || {}).slice(0, 120));
}

/* ══════════════════════════════════════════════════════════════════════════════════
 * §5 · LA OTRA SUPERFICIE SE ENTERA · sin recargar nada  ← calibración CI_ROJO=sin_bus
 * ══════════════════════════════════════════════════════════════════════════════════ */
seccion("§5 · la otra superficie · GLOBAL de verdad");
const urlSalaAntes = s.url();
let salaVerde = null;
for (let i = 0; i < 40; i++) {
  salaVerde = await s.evaluate(() => {
    const n = window.__salaQA(".aci")[0]; if (!n) return null;
    const vis = (el) => !!el && !!(el.getBoundingClientRect().width || el.getBoundingClientRect().height);
    return { state: n.dataset.state, texto: (n.querySelector("[data-aci-status]") || {}).textContent || "",
             form: vis(n.querySelector(".aci-form")), conectar: vis(n.querySelector("[data-connect]")) };
  });
  if (salaVerde && salaVerde.state === "connected") break;
  await sleep(300);
}
ok(salaVerde && salaVerde.state === "connected",
   "La Sala pasa a CONECTADA sola, sin que nadie la toque ★", salaVerde && salaVerde.state);
ok(s.url() === urlSalaAntes, "…y sin recargar: es la misma página, el mismo hilo", urlSalaAntes.split("/").pop());
ok(/Conectado|guardado/i.test((salaVerde || {}).texto || ""), "…y lo dice con el mismo texto canónico",
   ((salaVerde || {}).texto || "").trim().slice(0, 60));
ok(salaVerde && !salaVerde.form && !salaVerde.conectar,
   "…y su formulario también se retira (no pide una llave que ya está guardada) ★",
   salaVerde && JSON.stringify({ form: salaVerde.form, conectar: salaVerde.conectar }));
await s.screenshot({ path: join(SHOTS, "conexion-inline-3-sala-global.png") }).catch(() => {});

/* ══════════════════════════════════════════════════════════════════════════════════
 * §6 · LA CONVERSACIÓN SIGUE — y la llave NO viaja con ella
 * ══════════════════════════════════════════════════════════════════════════════════ */
seccion("§6 · la conversación sigue · y la llave no la acompaña");
ok(guideCalls.length === 2, "el loop del Guía RETOMA solo tras el trámite (segunda vuelta al cerebro) ★",
   `${guideCalls.length} vuelta(s)`);
const texto = await g.evaluate(() => (window.__guiaQ("#messages") || {}).textContent || "");
ok(/Sigo con el material del curso/.test(texto), "…y el turno continúa donde estaba, sin recargar ★");
ok(g.url().endsWith("cuarto.pixi.html"), "…en la misma página (nadie fue expulsado a un wizard)");

const vuelta = guideCalls[1] || {};
const tools = (vuelta.messages || []).filter((m) => m.role === "tool");
const crudo = JSON.stringify(vuelta);
ok(tools.length >= 1, "el resultado vuelve al modelo como role:tool (no como prosa inventada)", `${tools.length}`);
ok(!crudo.includes(LLAVE_BUENA) && !crudo.includes(LLAVE_MALA),
   "NI UNA de las dos llaves viaja al cerebro ★");
ok(/"credencial_en_chat":false/.test(crudo) || /credencial_en_chat/.test(crudo),
   "…el resultado afirma explícitamente que no lleva credencial", "credencial_en_chat");

/* CERO RASTRO. No alcanza con que el modelo no la vea: la llave no puede quedar en el estado
 * del chat, ni en el snapshot público de la pieza, ni en el almacenamiento del browser. */
const rastro = await g.evaluate(([buena, mala]) => {
  const hay = (s) => typeof s === "string" && (s.includes(buena) || s.includes(mala));
  const out = { storage: [], snapshot: null, dom: false, chat: [] };
  for (const st of [localStorage, sessionStorage]) {
    for (let i = 0; i < st.length; i++) { const k = st.key(i); if (hay(st.getItem(k))) out.storage.push(k); }
  }
  try { out.snapshot = JSON.stringify(window.__guiaConexionInline.snapshot()); } catch (e) { out.snapshot = "sin snapshot"; }
  const sr = window.__guiaQ("#messages");
  out.dom = hay(sr ? sr.innerHTML : "");
  try { out.chat = (window.__guide.snapshotMessages() || [])
    .filter((m) => hay(JSON.stringify(m))).map((m) => m.role); } catch (e) { out.chat = ["sin snapshotMessages"]; }
  return out;
}, [LLAVE_BUENA, LLAVE_MALA]);
ok(rastro.storage.length === 0, "cero rastro de la llave en localStorage/sessionStorage ★", rastro.storage.join(" · ") || "ninguno");
ok(!rastro.dom, "cero rastro en el DOM del hilo ★");
ok(rastro.chat.length === 0, "cero rastro en el estado de la conversación ★", rastro.chat.join(" · ") || "ninguno");
ok(!hayLlave(rastro.snapshot), "…y el snapshot público de la pieza es incapaz de contenerla ★", rastro.snapshot);
function hayLlave(s) { return typeof s === "string" && (s.includes(LLAVE_BUENA) || s.includes(LLAVE_MALA)); }

/* ══════════════════════════════════════════════════════════════════════════════════
 * §7 · LA DIVISIÓN POR TIPO, SELLADA
 * ══════════════════════════════════════════════════════════════════════════════════ */
seccion("§7 · la división por tipo · llave · oauth · local");
/* UN solo turno scripteado: OAUTH queda esperando al humano y NO se completa a propósito —
 * justamente el caso que antes colgaba el loop. Si algo acá pidiera una vuelta extra, el
 * script vacío devuelve el default y las secciones siguientes no se desfasan. */
guideScript = [
  { content: "Para tu correo hace falta autorizar.", tool_calls: [TC("conectar_inline", {
      mensaje: "Autorizá tu Gmail y sigo.", connector: "gmail", tipo: "oauth", nombre: "Gmail" })] },
];
await decir("mandá un correo");
await sleep(5000);
const oauth = await g.evaluate(() => {
  const n = window.__guiaQA(".aci").pop(); if (!n) return null;
  return { kind: n.dataset.kind, boton: (n.querySelector("[data-connect]") || {}).textContent || "",
    campos: [...n.querySelectorAll("input")].length, nonce: !!n.dataset.oauthNonce,
    candado: !!n.querySelector(".aci-lock") };
});
ok(oauth && oauth.kind === "oauth", "OAUTH se rinde como OAUTH (lo decide la ficha, no el modelo) ★", oauth && oauth.kind);
ok(oauth && oauth.campos === 0, "· sin ningún input de llave (un consent no se pega a mano)", oauth && String(oauth.campos));
ok(oauth && /Abrir autorización|Open authorization/i.test(oauth.boton), "· con el botón que ABRE el consent", oauth && oauth.boton.trim());
ok(oauth && oauth.nonce, "· y un nonce propio: el mensaje de vuelta de otra ventana no se acepta a ciegas ★");

/* LA VUELTA DEL CONSENT — MOCK DOCUMENTADO. El consent real de Google no es montable acá
 * (necesita la app OAuth registrada + un humano en el navegador del proveedor), así que se
 * ejercita EL CONTRATO EXACTO del retorno, que es lo que esta pieza sí posee:
 *
 *   window.postMessage({ type:"aleph:oauth:return", version:1,
 *                        connector:"<slug>", status:"ok"|"partial"|"cancelled"|"error",
 *                        nonce:"<el del widget>" }, location.origin)
 *
 * Regla dura, y por eso se mide en los dos sentidos: el mensaje NUNCA alcanza para pintar
 * verde. Sólo DESPIERTA una relectura del vault; el verde lo firma `GET /users/{id}/keys`.
 * (El retorno vigente en producción sigue siendo el callback del backend →
 *  Conectar.dc.html?c=<slug>&oauth=ok. Este canal es el adaptador para shells embebibles.) */
const antesFalso = await g.evaluate(() => (window.__guiaQA(".aci").pop() || {}).dataset.state);
await g.evaluate(() => {
  const n = window.__guiaQA(".aci").pop();
  window.postMessage({ type: "aleph:oauth:return", version: 1, connector: n.dataset.connector,
    status: "ok", nonce: "nonce-de-otro" }, location.origin);
});
await sleep(1200);
ok(await g.evaluate(() => (window.__guiaQA(".aci").pop() || {}).dataset.state) === antesFalso,
   "un retorno con nonce AJENO no mueve nada ★", antesFalso);
await g.evaluate(() => {
  const n = window.__guiaQA(".aci").pop();
  window.postMessage({ type: "aleph:oauth:return", version: 1, connector: n.dataset.connector,
    status: "ok", nonce: n.dataset.oauthNonce }, location.origin);
});
await sleep(1500);
ok(await g.evaluate(() => (window.__guiaQA(".aci").pop() || {}).dataset.state) !== "connected",
   "…y un `ok` con el nonce BUENO tampoco pinta verde: manda el vault, no el mensaje ★");

/* EL TRÁMITE ABANDONADO NO PUEDE DEJAR MUDO AL GUÍA.
 * La primera versión de esta pieza ESPERABA el resultado del widget dentro del loop. Con el
 * OAuth de arriba sin completar, esa espera no terminaba nunca: el Guía quedaba mudo y todo
 * lo que viniera después moría en silencio (esta misma vara lo pasó, y sus asserts de §8
 * "pasaban" contando cero sobre una página congelada). Se mide explícitamente. */
{
  const antes = guideCalls.length;
  guideScript = [{ content: "Sigo disponible aunque no hayas autorizado todavía.", tool_calls: [] }];
  await decir("dejá eso, contame otra cosa");
  await sleep(2500);
  ok(guideCalls.length === antes + 1,
     "con un trámite ABIERTO sin completar, el Guía SIGUE contestando (cero cuelgue) ★",
     `${guideCalls.length - antes} vuelta(s)`);
  ok(/Sigo disponible/.test(await g.evaluate(() => (window.__guiaQ("#messages") || {}).textContent || "")),
     "…y su respuesta se pinta de verdad");
}

guideScript = [
  { content: "Eso corre en tu máquina.", tool_calls: [TC("conectar_inline", {
      mensaje: "FreeCAD tiene que estar instalado en tu compu.", connector: "freecad", tipo: "local",
      nombre: "FreeCAD", comando: "brew install --cask freecad" })] },
  { content: "Cuando lo tengas, seguimos.", tool_calls: [] },
];
await decir("abrime el modelo 3d");
await sleep(4000);
const local = await g.evaluate(() => {
  const n = window.__guiaQA(".aci").pop(); if (!n) return null;
  return { kind: n.dataset.kind, state: n.dataset.state,
    comando: (n.querySelector(".aci-command code") || {}).textContent || "",
    link: (n.querySelector(".aci-link") || {}).href || "",
    inputs: [...n.querySelectorAll("input")].length,
    conectar: !!n.querySelector("[data-connect]") };
});
ok(local && local.kind === "local" && local.state === "external", "LOCAL se rinde como LOCAL", local && `${local.kind}/${local.state}`);
ok(local && local.comando === "brew install --cask freecad", "· muestra el comando EXACTO", local && local.comando);
ok(local && /Conectar\.dc\.html|freecad/i.test(local.link), "· y el link a SU pantalla", local && local.link);
ok(local && local.inputs === 0 && !local.conectar,
   "· y NADA más: ni input, ni [Conectar] — instalar no es inline y no se finge que sí ★");
await g.screenshot({ path: join(SHOTS, "conexion-inline-4-tipos.png") }).catch(() => {});

/* ══════════════════════════════════════════════════════════════════════════════════
 * §8 · LA CONTRACARA DE P7 · la pregunta abierta NO recibe un formulario
 * ══════════════════════════════════════════════════════════════════════════════════ */
seccion("§8 · la contracara · cero widget donde no corresponde");
const antesContracara = await gQ(".aci");
for (const [prompt, respuesta] of [
  ["uf, llevo tres horas peleándome con esto", "Tres horas con lo mismo cansa a cualquiera. Contame qué pasó."],
  ["¿conviene postgres o sqlite?", "Yo iría por SQLite: es un archivo, cero servidor, y a tu escala alcanza."],
  ["qué opinás de cómo quedó el agente", "Quedó sólido: el belt es chico y hace lo que promete."],
]) {
  guideScript = [{ content: respuesta, tool_calls: [] }];
  await decir(prompt);
  await sleep(2200);
}
ok(await gQ(".aci") === antesContracara,
   "desahogo, «¿A o B?» y opinión abierta reciben PROSA, cero formulario ★", `${await gQ(".aci")} vs ${antesContracara}`);
ok(/SQLite/.test(await g.evaluate(() => (window.__guiaQ("#messages") || {}).textContent || "")),
   "…y la respuesta conversacional sí está (no se quedó mudo)");
// La otra mitad de la contracara: un contrato inválido no pinta un formulario a medias.
{
  const antes = await gQ(".aci");
  guideScript = [{ content: "", tool_calls: [TC("conectar_inline", { mensaje: "x", connector: CONECTOR, tipo: "instalar" })] },
                 { content: "Perdón, te lo digo en prosa.", tool_calls: [] }];
  await decir("probá con un tipo inventado");
  await sleep(2500);
  ok(await gQ(".aci") === antes, "un `tipo` fuera de la división NO pinta nada ★", `${await gQ(".aci")} vs ${antes}`);
  const ult = guideCalls[guideCalls.length - 1] || {};
  const tmsg = ((ult.messages || []).filter((m) => m.role === "tool").pop() || {});
  ok(/tipo|llave, oauth o local/i.test(String(tmsg.content || "")),
     "…y el error vuelve AL MODELO para que corrija (no se traga en silencio)", String(tmsg.content || "").slice(0, 80));
}

/* ══════════════════════════════════════════════════════════════════════════════════
 * §9 · HIGIENE
 * ══════════════════════════════════════════════════════════════════════════════════ */
seccion("§9 · higiene");
ok(externas.length === 0, "CERO requests a la red externa en toda la corrida ★", externas.slice(0, 3).join(" · ") || "ninguna");
ok(errs.length === 0, "cero errores de página en las dos superficies", errs.slice(0, 3).join(" · ") || "ninguno");
ok(provHits.every((h) => h.startsWith("GET /api/v1/users/self")),
   "el validador de P11 pegó SÓLO donde la ficha dice (no a la raíz — el bug de FIX-P11 §1) ★",
   [...new Set(provHits)].join(" · "));

/* ── cierre ───────────────────────────────────────────────────────────────────────── */
await browser.close();
matarFrozen(proc);
proveedor.close();

console.log(`\n${fails.length === 0 ? "✓ TODO VERDE" : "✗ " + fails.length + " FALLAS"} — ${fails.length ? fails.join("\n   · ") : ""}`);
if (ROJO) {
  console.log(`\n── CALIBRACIÓN EN ROJO «${ROJO}»: esta corrida DEBE tener fallas. ${
    fails.length ? "Las tiene: la vara ve." : "NO LAS TIENE → la vara está ciega."}`);
  process.exit(fails.length ? 0 : 3);
}
process.exit(fails.length ? 1 : 0);
