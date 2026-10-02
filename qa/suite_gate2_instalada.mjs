#!/usr/bin/env node
/**
 * suite_gate2_instalada.mjs — LA CERTIFICACIÓN DE GATE 2, CONTRA LA APP INSTALADA.
 *
 *   node qa/suite_gate2_instalada.mjs
 *   ALEPH_APP=/Applications/Aleph.pre-gate2.app node qa/suite_gate2_instalada.mjs   # calibración
 *
 * ⚠️ POR QUÉ EXISTE, y por qué no alcanza con las varas del repo.
 *
 * Gate 2 se construyó en el árbol y se midió en el árbol. Entre el árbol y el usuario hay
 * un empaquetador que **pierde callado**: PyInstaller no se queja de lo que no ve, la vara
 * del repo sale verde, y el fallo aparece en la máquina de quien instaló. Esta suite hereda
 * el sujeto de `suite_instalada.mjs` (Gate 1): **el bundle, no localhost**.
 *
 * Lo que agrega sobre aquélla: aquélla preguntaba «¿viajaron los archivos?». Ésta pregunta
 * «¿la app instalada HACE lo que main promete?», y eso sólo se contesta CORRIENDO las vías
 * de inferencia de punta a punta contra el bundle, con las credenciales reales de la
 * máquina. Una vía que no se puede correr NO se aprueba: se declara NO MEDIBLE con qué
 * haría falta para medirla.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LAS TRES REGLAS DE ESTA SUITE
 *
 *   1. **EL SUJETO ES EL BUNDLE.** El sidecar que se levanta es
 *      `<APP>/Contents/MacOS/aleph_sidecar`, y el `:8926` que atiende la vía CLI es el que
 *      ESE binario administra (`mode: managed`). Cero código del repo en el camino medido.
 *
 *   2. **CREDENCIALES REALES, ESCRITURAS EN UNA COPIA.** El datadir real
 *      (`~/Library/Application Support/Aleph`) se COPIA y se apunta `ALEPH_DATA_DIR` a la
 *      copia. Las sesiones y llaves de verdad viajan —es lo que hace honesta la medición—
 *      pero un turno de prueba, un estado de modelo o un reinicio jamás tocan la DB del
 *      usuario. Medir no puede costarle datos a nadie.
 *
 *   3. **TRES VEREDICTOS, NO DOS.** `verde` · `rojo` · `no_medible`. El tercero lleva
 *      SIEMPRE escrito qué haría falta. Un `no_medible` contado como verde es exactamente
 *      la mentira que una certificación existe para impedir, y contarlo como rojo haría
 *      que la suite castigue a la app por una cuenta que el usuario no tiene.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LA CALIBRACIÓN ES PARTE DE LA SUITE, NO UN EXTRA.
 *
 * Una suite que sale verde en cualquier build no certifica nada: mide que el arnés corre.
 * Por eso se corre TAMBIÉN contra el build anterior (`ALEPH_APP=...pre-gate2.app`) y se
 * exige que ahí salga ROJA. Las pruebas marcadas `discrimina: true` son las que tienen que
 * distinguir: son obra de Gate 2 y el build viejo no las puede pasar.
 */
import { execFileSync, spawn } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const APP = process.env.ALEPH_APP || "/Applications/Aleph.app";
const SIDECAR = join(APP, "Contents/MacOS/aleph_sidecar");
const PUERTO = Number(process.env.ALEPH_F6_PORT || 8397);
const B = `http://127.0.0.1:${PUERTO}`;
const DATADIR_REAL = join(homedir(), "Library/Application Support/Aleph");
const OLLAMA = process.env.ALEPH_F6_OLLAMA || "http://127.0.0.1:11434";
const CLI_BRAIN = "http://127.0.0.1:8926/v1";

const t0 = Date.now();
const seg = () => ((Date.now() - t0) / 1000).toFixed(1);
const log = (s = "") => console.log(s);
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

if (!existsSync(SIDECAR)) {
  console.error(`✗ no existe el sidecar instalado: ${SIDECAR}`);
  process.exit(2);
}
const HASH = execFileSync("shasum", ["-a", "256", SIDECAR], { encoding: "utf8" }).split(" ")[0];

/* ── EL REGISTRO DE RESULTADOS ───────────────────────────────────────────────────────── */
const VERDE = "verde", ROJO = "rojo", NO_MEDIBLE = "no_medible";
const M = [];   // {via, prueba, veredicto, detalle, discrimina}
//: UN 429 DEL TIER GRATUITO ES DATO, NO FALLO. Lo que importa no es que no pase —pasa, y no
//: lo controlamos— sino que cuando pasa llegue TIPADO a la superficie. Se registran todos
//: los que aparezcan en cualquier turno de la corrida, con su `retry_after_s` si viene.
const RATE_LIMITS = [];
function mirarRateLimit(via, eventos) {
  for (const e of eventos || []) {
    const c = e?.causa;
    if (c?.causa === "rate_limit") {
      RATE_LIMITS.push({ via, retry_after_s: c.retry_after_s ?? null,
                         reintentable: c.reintentable ?? null, detalle: String(c.detalle || "").slice(0, 120) });
    }
  }
}
function anotar(via, prueba, veredicto, detalle, discrimina = false) {
  M.push({ via, prueba, veredicto, detalle, discrimina });
  const icono = veredicto === VERDE ? "✅" : veredicto === ROJO ? "❌" : "⚪";
  log(`    ${icono} ${via.padEnd(6)} ${prueba.padEnd(14)} ${detalle}`);
  return veredicto;
}

/* ── ARRANQUE Y PARADA DEL SIDECAR DEL BUNDLE ────────────────────────────────────────── */
let proc = null;
const DATADIR = mkdtempSync(join(tmpdir(), "aleph-f6-datos-"));

async function levantar(etiqueta) {
  proc = spawn(SIDECAR, ["--port", String(PUERTO)], {
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ALEPH_DATA_DIR: DATADIR },
  });
  let salida = "";
  proc.stdout.on("data", (b) => { salida += b; });
  proc.stderr.on("data", (b) => { salida += b; });
  for (let i = 0; i < 90; i++) {
    await dormir(1000);
    try {
      const r = await fetch(`${B}/health`);
      if (r.ok) return await r.json();
    } catch { /* todavía no */ }
  }
  console.error(`✗ el sidecar instalado no levantó (${etiqueta})\n${salida.slice(-2000)}`);
  process.exit(2);
}

async function bajar() {
  if (!proc) return;
  try { proc.kill("SIGTERM"); } catch { /* ya no está */ }
  // El sidecar administra el `:8926`; se le da tiempo a bajarlo con él.
  for (let i = 0; i < 15; i++) {
    await dormir(400);
    if (proc.exitCode !== null || proc.signalCode !== null) break;
  }
  try { proc.kill("SIGKILL"); } catch { /* ya no está */ }
  proc = null;
  await dormir(800);
}

/* ── HELPERS HTTP ────────────────────────────────────────────────────────────────────── */
let TOKEN = null;
const cab = () => ({ "Content-Type": "application/json",
                     ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}) });

async function jget(ruta, ms = 30000) {
  const c = AbortSignal.timeout(ms);
  try {
    const r = await fetch(B + ruta, { headers: cab(), signal: c });
    return { status: r.status, json: await r.json().catch(() => null) };
  } catch (e) { return { status: -1, json: null, error: String(e.message || e) }; }
}
async function jpost(ruta, body, ms = 30000) {
  const c = AbortSignal.timeout(ms);
  try {
    const r = await fetch(B + ruta, { method: "POST", headers: cab(),
                                      body: JSON.stringify(body ?? {}), signal: c });
    return { status: r.status, json: await r.json().catch(() => null) };
  } catch (e) { return { status: -1, json: null, error: String(e.message || e) }; }
}

/**
 * Consume el SSE de `/v1/puppets/run/stream` y devuelve los eventos CON SU RELOJ.
 * El sello de tiempo por evento es el que hace verificable el STREAMING: sin él, un
 * servidor que juntara todo y lo escupiera al final sería indistinguible de uno que
 * streamea, y la prueba diría «streaming ✓» sobre una respuesta fabricada.
 */
async function stream(recipe, prompt, { ms = 180000, alPrimerToken = null, userId = null } = {}) {
  const t = Date.now();
  const eventos = [];
  const ctl = new AbortController();
  const reloj = setTimeout(() => ctl.abort(), ms);
  let disparado = false;
  try {
    const r = await fetch(`${B}/v1/puppets/run/stream`, {
      method: "POST", headers: cab(), signal: ctl.signal,
      //: `user_id` SÓLO cuando hace falta: es lo que hace que el router construya el
      //: `byok_resolver` ligado al usuario (`credential_broker.make_user_resolver`). Sin él
      //: el `byok_ref` de la receta no resuelve y el turno cae a la cognición incluida —
      //: que mediría OTRA cosa y la llamaría «vía API».
      body: JSON.stringify({ prompt, recipe, deadline_s: Math.round(ms / 1000), lang: "es",
                             ...(userId ? { user_id: userId } : {}) }),
    });
    if (!r.ok || !r.body) {
      const j = await r.json().catch(() => null);
      return { ok: false, status: r.status, json: j, eventos, ms: Date.now() - t };
    }
    const dec = new TextDecoder();
    let buf = "";
    for await (const trozo of r.body) {
      buf += dec.decode(trozo, { stream: true });
      let corte;
      while ((corte = buf.indexOf("\n\n")) >= 0) {
        const linea = buf.slice(0, corte).trim(); buf = buf.slice(corte + 2);
        if (!linea.startsWith("data:")) continue;
        let ev = null;
        try { ev = JSON.parse(linea.slice(5).trim()); } catch { continue; }
        eventos.push({ ...ev, _t: Date.now() - t });
        if (!disparado && alPrimerToken && (ev.type === "token" || ev.type === "thinking")) {
          disparado = true;
          // No se espera: parar es concurrente con el stream a propósito.
          alPrimerToken(eventos).catch(() => {});
        }
      }
    }
    mirarRateLimit(recipe?.meta?.name || "?", eventos);
    return { ok: true, status: r.status, eventos, ms: Date.now() - t };
  } catch (e) {
    return { ok: false, status: -1, eventos, ms: Date.now() - t, error: String(e.message || e) };
  } finally { clearTimeout(reloj); }
}

/* ── LAS RECETAS POR VÍA ─────────────────────────────────────────────────────────────── */
//: `belt_ref` apunta al fixture que YA VIAJA en el bundle (lo usa la suite de la Sala
//: instalada). El contrato de receta v1 lo exige aunque el chat de texto no llame tools:
//: inventar un belt inexistente daría un 422 del validador y no de la vía, que es un rojo
//: que no habla de lo que estamos midiendo.
const BELT = { belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
               tool_filters: { calc: ["add", "mul"] } };

const receta = (nombre, model) => ({
  schema_version: "v1",
  meta: { name: `F6 · ${nombre}`, nicho: "general" },
  model: { temperature: 0, max_tokens: 64, max_turns: 1, ...model },
  belt: BELT,
  rag: { enabled: false },
});

//: `max_tokens` 512 y `/no_think`, MEDIDOS y no elegidos al azar: qwen3 es RAZONADOR y con
//: 64 tokens gastó el presupuesto entero pensando (61 frames `thinking`, 0 de contenido) y
//: cerró con `answer` vacío. Eso es un rojo del ARNÉS disfrazado de rojo de la app: el
//: modelo hizo exactamente lo que se le pidió con el presupuesto que se le dio. Dar
//: presupuesto suficiente no es ablandar la prueba —la aserción sigue siendo «contenido
//: real»—, es dejar de medir mi propio error.
const R_LOCAL = receta("local", { base_url: `${OLLAMA}/v1`, primary: "qwen3:8b", max_tokens: 512 });
//: SIN `cli_model`. Medido contra el `:8926` del bundle: mandar el slug del PROVEEDOR
//: (`claude_cli`) viaja como `--model claude_cli` y Claude Code contesta 404
//: (`modelo_no_disponible`, con su evidencia). `None` = el default del plan, que es lo que
//: manda la app real; con eso el turno corre y responde `claude-opus-5`.
const R_CLI = receta("cli", { base_url: CLI_BRAIN, primary: "claude-code-cli",
                              brain_provider: "claude_cli", max_tokens: 128 });
/* ── LA LLAVE DE LA VÍA API ──────────────────────────────────────────────────────────
 * JAMÁS en el código. Entra por env (`ALEPH_F6_OPENROUTER_KEY`) o por un archivo que se
 * nombra por env (`..._KEY_FILE`), y se carga en el broker de la app con su propio
 * endpoint: así lo que se certifica es el CAMINO REAL del producto —guardar cifrado,
 * resolver el `byok_ref`, correr con la key del usuario— y no un atajo de la suite.
 * Sin llave la vía queda `no_medible`, como antes. Nada de esto se commitea.
 */
const OR_KEY = (() => {
  const directa = (process.env.ALEPH_F6_OPENROUTER_KEY || "").trim();
  if (directa) return directa;
  const arch = (process.env.ALEPH_F6_OPENROUTER_KEY_FILE || "").trim();
  if (arch && existsSync(arch)) { try { return readFileSync(arch, "utf8").trim(); } catch { return ""; } }
  return "";
})();
//: EL MODELO SE VERIFICA CONTRA EL CATÁLOGO VIVO, no se asume: los `:free` de OpenRouter
//: rotan sin aviso. Medido el 2026-08-05 contra `/api/v1/models`: `qwen/qwen3.6-plus:free`
//: NO existe (sí `qwen/qwen3.6-plus`, de pago) y `openai/gpt-oss-120b:free` tampoco. La
//: cuenta da `total_credits: 0` y aun así `qwen/qwen3.6-plus` RESPONDE —OpenRouter lo
//: sirve vía Alibaba—, así que se usa ése. Si un día deja de responder, el fallback
//: declarado es `openai/gpt-oss-20b:free`, que sí está en el catálogo gratuito.
const OR_MODELO = process.env.ALEPH_F6_OPENROUTER_MODEL || "qwen/qwen3.6-plus";
//: `max_tokens` 600, por la MISMA razón medida que en la vía local y con el mismo error
//: cometido antes de aprenderlo: `qwen3.6-plus` es RAZONADOR. Con 64 la corrida dio 18
//: frames `thinking`, CERO de contenido y `answer` vacío — un rojo que hablaba de mi
//: presupuesto, no de la vía. Con 600: 45 `thinking` + 2 `token` y `answer:"LISTO"`.
//: (El mismo prompt por curl pelado sí contestaba con 16 tokens; lo que cambia es que por
//: Aleph viaja el system de la receta y el modelo razona más. Medir la vía es medirla CON
//: la receta, no sin ella.)
const R_API = receta("api", { base_url: "https://openrouter.ai/api/v1",
                              primary: OR_MODELO, byok_ref: "keys:openrouter",
                              max_tokens: 600 });

/* ══ ARRANQUE ════════════════════════════════════════════════════════════════════════ */
log("═".repeat(100));
log("CERTIFICACIÓN GATE 2 — CONTRA LA APP INSTALADA");
log("═".repeat(100));
log(`  app     : ${APP}`);
log(`  sidecar : ${HASH}`);
log(`  repo    : ${execFileSync("git", ["-C", RAIZ, "rev-parse", "--short", "HEAD"], { encoding: "utf8" }).trim()}`);

// El datadir REAL se copia: credenciales de verdad, escrituras en la copia.
if (existsSync(DATADIR_REAL)) {
  try { cpSync(DATADIR_REAL, DATADIR, { recursive: true }); } catch { /* lo dirá la prueba */ }
  log(`  datadir : copia de ${DATADIR_REAL}`);
} else {
  log(`  datadir : ⚠️ no existe ${DATADIR_REAL} — se corre sin credenciales reales`);
}
log("");

log("0 · levantando el sidecar DEL BUNDLE");
let salud = await levantar("arranque");
log(`    vivo · build=${salud?.proceso?.build} · ${seg()}s`);
const sesion = await jpost("/v1/auth/local", {});
TOKEN = sesion.json?.session_token || null;
const UID = sesion.json?.id || null;
log(`    sesión local: ${TOKEN ? "ok" : "✗ SIN SESIÓN"}`);

// La llave se guarda POR EL ENDPOINT DE LA APP, no escribiendo la DB por atrás: guardar es
// parte de lo que hay que certificar (cifrado fernet, aislamiento por usuario).
let orCargada = null;
if (OR_KEY && UID) {
  const r = await jpost("/v1/keys", { user_id: UID, provider: "openrouter", secret: OR_KEY }, 30000);
  orCargada = r.status === 200;
  //: se reporta el `last4` que devuelve la app, JAMÁS el secreto.
  log(`    llave openrouter → broker: ${orCargada ? `ok (…${r.json?.last4 ?? "?"})` : `✗ HTTP ${r.status}`}`);
} else {
  log(`    llave openrouter: no provista (ALEPH_F6_OPENROUTER_KEY[_FILE]) — la vía API queda sin certificar`);
}
log("");

/* ══ 1 · CONFIGURACIÓN — ¿la credencial/sesión se resuelve? ══════════════════════════ */
log("1 · CONFIGURACIÓN — la credencial/sesión se RESUELVE contra el bundle");
{
  // local: el runtime tiene que estar vivo Y el modelo instalado, dicho por la app.
  const inst = await jget("/v1/modelos/instalados", 60000);
  const filas = inst.json?.modelos || [];
  const qwen = filas.find((m) => String(m.ollama_tag || m.slug).includes("qwen3"));
  anotar("local", "CONFIGURACIÓN",
    qwen?.en_ollama ? VERDE : ROJO,
    qwen ? `la app ve ${qwen.slug} en_ollama=${qwen.en_ollama}` : "la app no ve ningún qwen3 instalado");

  // cli: sesiones REALES, reportadas por el bundle.
  const ses = await jget("/v1/modelos/cli/sesiones", 60000);
  const provs = ses.json?.providers || {};
  const listos = Object.entries(provs).filter(([, p]) => p.state === "ready").map(([k]) => k);
  anotar("cli", "CONFIGURACIÓN",
    listos.length ? VERDE : ROJO,
    listos.length ? `sesión activa: ${listos.join(", ")} (${provs[listos[0]]?.detail || ""})`
                  : "ningún proveedor CLI con sesión");

  // api: se pregunta por la llave; la ausencia NO es rojo de la app, es falta de cuenta.
  const v2 = await jget("/v1/modelos/v2", 60000);
  const api = (v2.json?.filas || []).filter((f) => f.familia === "api");
  const conLlave = api.filter((f) => f.hay_llave === true);
  // Con llave cargada la exigencia SUBE: no alcanza con exponer proveedores, la app tiene
  // que RESOLVER la credencial y decir que la tiene. Sin llave, exponerlos es lo único que
  // se le puede pedir.
  const or = api.find((f) => String(f.slug).includes("openrouter") || String(f.ref) === "openrouter");
  anotar("api", "CONFIGURACIÓN",
    orCargada ? (or?.hay_llave === true ? VERDE : ROJO) : (api.length ? VERDE : ROJO),
    orCargada
      ? (or?.hay_llave === true
         ? `la app RESUELVE la credencial de openrouter (hay_llave=true) · ${conLlave.length}/${api.length} proveedores con llave`
         : `se cargó la llave por el broker pero la app reporta hay_llave=${or?.hay_llave} para openrouter`)
      : (api.length ? `${api.length} proveedores de API expuestos · con llave cargada: ${conLlave.length}`
                    : "el bundle no expone ningún proveedor de API"));
}
log("");

/* ══ 2 y 3 · EJECUCIÓN + STREAMING ══════════════════════════════════════════════════ */
log("2·3 · EJECUCIÓN (contenido válido) + STREAMING (parciales ANTES del final)");
const corridas = {};
for (const [via, R] of [["local", R_LOCAL], ["cli", R_CLI]]) {
  //: `/no_think` es el interruptor de razonamiento de qwen3. Sin él el modelo puede gastar
  //: TODO el presupuesto pensando y cerrar sin contenido — y entonces la prueba mediría el
  //: presupuesto, no la vía.
  const pedido = via === "local" ? "Decí exactamente: LISTO /no_think" : "Decí exactamente: LISTO";
  const s = await stream(R, pedido, { ms: 240000 });
  corridas[via] = s;
  const done = s.eventos.find((e) => e.type === "done");
  const err = s.eventos.find((e) => e.type === "error");
  const texto = (done?.answer || "").trim();

  anotar(via, "EJECUCIÓN",
    texto.length > 0 ? VERDE : ROJO,
    texto.length > 0 ? `respuesta real de ${s.ms} ms: ${JSON.stringify(texto.slice(0, 60))}`
                     : `sin contenido${err ? ` · error: ${String(err.detail).slice(0, 90)}` : ""}`);

  // STREAMING: parciales con reloj ESTRICTAMENTE anterior al `done`. Dos o más parciales
  // separados en el tiempo es lo que distingue streamear de escupir todo junto al final.
  const parciales = s.eventos.filter((e) => e.type === "token" || e.type === "thinking");
  const tDone = done?._t ?? Infinity;
  const antes = parciales.filter((e) => e._t < tDone);
  const separados = antes.length >= 2 && (antes[antes.length - 1]._t - antes[0]._t) > 0;
  anotar(via, "STREAMING",
    antes.length >= 2 && separados ? VERDE : ROJO,
    antes.length >= 2
      ? `${antes.length} parciales entre ${antes[0]._t}ms y ${antes[antes.length - 1]._t}ms, done a ${tDone}ms`
      : `sólo ${antes.length} parciales antes del done — indistinguible de fabricado`);
}
{
  // api: con llave cargada se corre de verdad; sin llave se declara qué haría falta.
  if (!orCargada) {
    const falta = "una API key real cargada en el broker (ALEPH_F6_OPENROUTER_KEY[_FILE])";
    anotar("api", "EJECUCIÓN", NO_MEDIBLE, `no hay llave cargada — haría falta ${falta}`);
    anotar("api", "STREAMING", NO_MEDIBLE, `no hay llave cargada — haría falta ${falta}`);
  } else {
    const s = await stream(R_API, "Decí exactamente: LISTO", { ms: 150000, userId: UID });
    corridas.api = s;
    const done = s.eventos.find((e) => e.type === "done");
    const err = s.eventos.find((e) => e.type === "error");
    const texto = (done?.answer || "").trim();
    anotar("api", "EJECUCIÓN", texto ? VERDE : ROJO,
      texto ? `respuesta real de ${s.ms} ms vía ${OR_MODELO}: ${JSON.stringify(texto.slice(0, 50))}`
            : `sin contenido${err ? ` · ${String(err.causa?.causa || err.detail).slice(0, 90)}` : ""}`);
    const parc = s.eventos.filter((e) => (e.type === "token" || e.type === "thinking") &&
                                         e._t < (done?._t ?? Infinity));
    anotar("api", "STREAMING", parc.length >= 2 ? VERDE : ROJO,
      parc.length >= 2
        ? `${parc.length} parciales entre ${parc[0]._t}ms y ${parc[parc.length - 1]._t}ms, done a ${done?._t}ms`
        : `sólo ${parc.length} parciales antes del done — indistinguible de fabricado`);
  }
}
log("");

/* ══ 4 · CANCELACIÓN — que el stop MATE el proceso, medido con ps ═══════════════════ */
log("4 · CANCELACIÓN — el stop mata el proceso de verdad (medido con ps)");
{
  // ⚠️ CONTAR procesos `claude` NO SIRVE ACÁ, y el primer intento de esta suite se comió
  // ese error: la medición salía «1→1» y pasaba igual, porque el `claude` que contaba era
  // la sesión DE QUIEN CORRE LA SUITE, no el hijo del turno. Un contador global mide el
  // ambiente; lo que hay que medir es EL PROCESO DE ESTE TURNO.
  // Por eso: se fotografían los PIDs ANTES, se identifican los NACIDOS durante el turno, y
  // después del stop se exige que ESOS PIDs no estén. Es la única forma de que el ps diga
  // algo sobre la cancelación y no sobre la máquina.
  const pidsClaude = () => {
    try {
      const salida = execFileSync("bash", ["-lc",
        "ps -Ao pid=,command= | grep -E '[c]laude' || true"], { encoding: "utf8" });
      return new Set(salida.split("\n").filter(Boolean)
        .map((l) => l.trim().split(/\s+/)[0]).filter(Boolean));
    } catch { return new Set(); }
  };
  const vive = (pid) => {
    try { execFileSync("bash", ["-lc", `kill -0 ${pid} 2>/dev/null`]); return true; }
    catch { return false; }
  };
  const base = pidsClaude();
  let nacidos = [];
  let paro = null, turnoId = null;

  const s = await stream(R_CLI, "Contá del 1 al 300, uno por línea, sin parar.", {
    ms: 120000,
    alPrimerToken: async (evs) => {
      const t = evs.find((e) => e.type === "turno");
      turnoId = t?.turno_id || null;
      // Con el turno YA en vuelo: los `claude` que no estaban antes son los de este turno.
      nacidos = [...pidsClaude()].filter((p) => !base.has(p));
      await dormir(1200);
      if (turnoId) paro = await jpost("/v1/turnos/detener", { turno_id: turnoId }, 30000);
    },
  });
  await dormir(2500);
  const sobrevivientes = nacidos.filter(vive);

  if (!turnoId) {
    // Sin `turno_id` no hay a quién pararle nada: eso ES el rojo que F4b vino a matar.
    anotar("cli", "CANCELACIÓN", ROJO,
      "el stream no emitió el evento `turno` — la Sala no tiene qué parar", true);
  } else {
    const res = paro?.json?.resultado;
    // Dos condiciones, y las dos tienen que darse: el server contesta `turno_detenido` Y
    // ningún proceso nacido con este turno sigue vivo. La primera sola sería creerle al
    // server; la segunda sola no distinguiría «murió porque lo mataron» de «murió solo».
    const ok = res === "turno_detenido" && sobrevivientes.length === 0;
    anotar("cli", "CANCELACIÓN", ok ? VERDE : ROJO,
      `turno=${String(turnoId).slice(0, 12)}… → ${res} · ` +
      (nacidos.length
        ? `pid(s) del turno [${nacidos.join(",")}] · vivos tras el stop: ${sobrevivientes.length}`
        : "no se vio nacer ningún proceso (el CLI ya estaba corriendo o murió antes del ps)") +
      ` · el stream cortó a ${s.ms}ms`, true);
  }

  // ── [F6-cierre · obra C] LAS VÍAS HTTP YA SE PUEDEN PARAR ────────────────────────
  // Antes esto era `no_medible` con estas palabras: «no hay proceso local que matar; haría
  // falta un contrato de cancelación para vías HTTP». Ése es el contrato. Acá NO se mide
  // un `ps` —no hay proceso, y buscar uno sería medir otra cosa y llamarla igual— sino lo
  // que de verdad importa: que el turno se corte y que lo diga con el vocabulario de F2d.
  for (const [via, R] of [["local", R_LOCAL], ["api", orCargada ? R_API : null]]) {
    if (!R) {
      anotar("api", "CANCELACIÓN", NO_MEDIBLE, "sin llave no hay turno de API que parar");
      continue;
    }
    let tid = null, res = null, t0 = 0;
    const s = await stream(R, "Contá del 1 al 500, uno por línea, sin parar.", {
      ms: 120000, userId: via === "api" ? UID : null,
      alPrimerToken: async (evs) => {
        tid = evs.find((e) => e.type === "turno")?.turno_id || null;
        t0 = Date.now();
        await dormir(900);
        if (tid) res = await jpost("/v1/turnos/detener", { turno_id: tid }, 30000);
      },
    });
    const cortoRapido = s.ms < 60000;              // no esperó a que el modelo terminara solo
    const err = s.eventos.find((e) => e.type === "error");
    const detenido = err?.causa?.causa === "turno_detenido";
    const ok = res?.json?.resultado === "turno_detenido" && detenido && cortoRapido;
    anotar(via, "CANCELACIÓN", ok ? VERDE : ROJO,
      tid
        ? `turno=${String(tid).slice(0, 14)}… → ${res?.json?.resultado} · el stream cortó a ` +
          `${s.ms}ms · causa en la superficie: ${err?.causa?.causa ?? "(ninguna)"}` +
          `${err?.causa?.reintentable !== undefined ? ` · reintentable=${err.causa.reintentable}` : ""}`
        : "la vía no emitió `turno_id`: no hay qué parar",
      true);
  }
}
log("");

/* ══ 5 · USAGE — medido, o declarado no-medible. JAMÁS un cero inventado ════════════ */
log("5 · USAGE — medido o declarado no-medible (jamás un cero inventado)");
{
  // LA VÍA CLI SÍ MIDE, y hay que ir a buscarlo donde está: el `:8926` que administra el
  // bundle devuelve `usage` en su respuesta no-streaming. Reportarlo «no medible» porque el
  // canal SSE no lo transporta sería culpar a la app de un hueco del transporte y ocultar
  // que la medición existe.
  let uso = null, err = null;
  try {
    const r = await fetch(`${CLI_BRAIN}/chat/completions`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "claude-code-cli", stream: false, max_tokens: 32,
                             messages: [{ role: "user", content: "Decí exactamente: OK" }] }),
      signal: AbortSignal.timeout(180000),
    });
    uso = (await r.json().catch(() => null))?.usage ?? null;
  } catch (e) { err = String(e.message || e); }
  const positivo = uso && Number(uso.total_tokens) > 0;
  const ceroInventado = uso && Number(uso.total_tokens) === 0;
  anotar("cli", "USAGE",
    positivo ? VERDE : (ceroInventado ? ROJO : NO_MEDIBLE),
    positivo ? `el bundle MIDE el uso del turno: ${JSON.stringify(uso)}`
             : (ceroInventado ? `publica total_tokens=0 sobre un turno que corrió — cero inventado`
                              : `no llegó \`usage\` del :8926${err ? ` (${err.slice(0, 60)})` : ""}`),
    true);
}
// ── [F6-cierre · obra B] EL CANAL `usage` DEL SSE ────────────────────────────────
// Antes esto era `no_medible`: «el canal SSE no transporta uso». Ahora sí lo transporta, y
// lo que se mide es el contrato de F2c — `tokens_medidos` explícito y **`None` jamás cero**.
for (const via of ["local", "api"]) {
  const evs = corridas[via]?.eventos || [];
  if (!evs.length) { anotar(via, "USAGE", NO_MEDIBLE, "no hubo turno que medir"); continue; }
  const uso = evs.find((e) => e.type === "usage");
  if (!uso) {
    anotar(via, "USAGE", ROJO,
      "el turno cerró SIN evento `usage` — ni medido ni declarado no-medible", true);
  } else if (uso.tokens_medidos === true) {
    anotar(via, "USAGE", VERDE,
      `uso MEDIDO en el canal: total_tokens=${uso.total_tokens}` +
      `${uso.usd != null ? ` · usd=${uso.usd}` : " · usd=null (el proveedor no lo manda)"}`,
      true);
  } else {
    // No-medible DECLARADO: el proveedor no mandó nada ni pidiéndoselo. Es un resultado
    // legítimo del contrato — lo que NO puede pasar es un cero disfrazado de medición.
    const ceroInventado = uso.total_tokens === 0 || uso.usd === 0;
    anotar(via, "USAGE", ceroInventado ? ROJO : NO_MEDIBLE,
      ceroInventado
        ? `publica ${JSON.stringify(uso)} — un cero inventado sobre un turno que corrió`
        : `no-medible DECLARADO (tokens_medidos=false, todo en null): el proveedor no manda ` +
          `uso ni pidiéndole include_usage. No se calla y no inventa un cero`,
      true);
  }
}
log("");

/* ══ 6 · ERRORES — un fallo llega TIPADO a la superficie, no como string crudo ══════ */
log("6 · ERRORES — el fallo llega TIPADO (con `causa`), no como string crudo");
{
  // local: Ollama vivo pero modelo inexistente → causa del vocabulario de Ollama.
  const rota = receta("local roto", { base_url: `${OLLAMA}/v1`, primary: "modelo-que-no-existe:0b" });
  const s = await stream(rota, "hola", { ms: 60000 });
  const err = s.eventos.find((e) => e.type === "error");
  const c = err?.causa;
  anotar("local", "ERRORES", c?.causa ? VERDE : ROJO,
    c?.causa ? `causa tipada \`${c.causa}\`${c.reintentable !== undefined ? ` · reintentable=${c.reintentable}` : ""}`
             : (err ? `llegó error SIN causa tipada: ${String(err.detail).slice(0, 90)}` : "no llegó evento error"),
    true);

  // api: un fallo REAL del proveedor tiene que salir tipado. Con llave cargada se pide un
  // modelo inexistente (404 de OpenRouter, con la key del usuario); sin llave, el propio
  // 401 sirve de sonda. En los dos casos el fallo es del proveedor, no fabricado por acá.
  const apiRota = orCargada
    ? receta("api rota", { base_url: "https://openrouter.ai/api/v1",
                           primary: "proveedor/modelo-que-no-existe:free",
                           byok_ref: "keys:openrouter" })
    : R_API;
  const s2 = await stream(apiRota, "hola", { ms: 90000, userId: orCargada ? UID : null });
  const e2 = s2.eventos.find((e) => e.type === "error");
  const c2 = e2?.causa;
  anotar("api", "ERRORES", c2?.causa ? VERDE : (e2 ? ROJO : NO_MEDIBLE),
    c2?.causa ? `causa tipada \`${c2.causa}\``
              : (e2 ? `error SIN causa tipada: ${String(e2.detail).slice(0, 90)}`
                    : "no hubo error que tipar (¿la solicitud salió?)"),
    true);

  // cli: puerto del cerebro equivocado → la vía CLI también tiene que tipar.
  const rotaCli = receta("cli roto", { base_url: "http://127.0.0.1:8927/v1",
                                       primary: "claude-code-cli", cli_model: "claude_cli" });
  const s3 = await stream(rotaCli, "hola", { ms: 45000 });
  const e3 = s3.eventos.find((e) => e.type === "error");
  const c3 = e3?.causa;
  anotar("cli", "ERRORES", c3?.causa ? VERDE : ROJO,
    c3?.causa ? `causa tipada \`${c3.causa}\``
              : (e3 ? `error SIN causa tipada: ${String(e3.detail).slice(0, 90)}` : "no llegó evento error"),
    true);
}
log("");

/* ══ 7 · RESTAURACIÓN — cerrar, reabrir, y que el estado VUELVA ═════════════════════ */
log("7 · RESTAURACIÓN — cerrar → reabrir → el modelo elegido y su estado vuelven");
{
  // El contrato REAL: `PUT {default: <slug>}` y el slug tiene que estar CONECTADO (409 si
  // no). Y se elige un default DISTINTO del vigente a propósito: comprobar que un valor que
  // ya estaba sigue estando no prueba que se haya restaurado nada — prueba que nadie lo
  // tocó. Lo que certifica es que una ELECCIÓN NUEVA sobrevive a cerrar y reabrir.
  const pref0 = await jget("/v1/modelos/preferencias", 30000);
  const conectados = pref0.json?.conectados || [];
  const vigente = pref0.json?.default || null;
  const elegido = conectados.find((s) => s !== vigente) || conectados[0] || null;

  let guardo = null;
  if (elegido) {
    try {
      const r = await fetch(`${B}/v1/modelos/preferencias`, {
        method: "PUT", headers: cab(), body: JSON.stringify({ default: elegido }),
        signal: AbortSignal.timeout(30000),
      });
      guardo = { status: r.status, json: await r.json().catch(() => null) };
    } catch (e) { guardo = { status: -1, error: String(e.message || e) }; }
  }

  const antes = await jget("/v1/modelos/preferencias", 30000);
  // Sólo lo PERSISTIDO. `ts` y `default_estado` se derivan vivos en cada lectura: meterlos
  // en la comparación hacía fallar la prueba por un reloj, no por una restauración.
  const persistido = (j) => JSON.stringify({ default: j?.default ?? null,
                                             contextos: j?.contextos ?? null });
  const antesTxt = persistido(antes.json);

  // ── EL REINICIO ES REAL: se baja el proceso y se levanta otro. Releer de memoria no
  //    prueba nada sobre reabrir la app.
  await bajar();
  salud = await levantar("reinicio");
  const s2 = await jpost("/v1/auth/local", {});
  TOKEN = s2.json?.session_token || TOKEN;
  const despues = await jget("/v1/modelos/preferencias", 30000);
  const despuesTxt = persistido(despues.json);

  const guardoOk = guardo?.status === 200 && despues.json?.default === elegido;
  const volvio = guardoOk && antesTxt === despuesTxt;
  anotar("local", "RESTAURACIÓN",
    volvio ? VERDE : (guardo?.status === 200 ? ROJO : NO_MEDIBLE),
    volvio ? `la elección NUEVA (${vigente} → ${elegido}) sobrevivió al REINICIO del proceso`
           : (guardo?.status === 200
              ? `la elección no volvió: antes=${antesTxt} después=${despuesTxt}`
              : `PUT /preferencias devolvió ${guardo?.status ?? "—"}` +
                (elegido ? ` (${JSON.stringify(guardo?.json).slice(0, 90)})`
                         : " — no hay ningún modelo conectado que elegir")),
    true);

  // La sesión CLI resume: F4d arregló el slug que no encontraba sus sesiones (93,5% de
  // ahorro medido EN EL REPO). Acá se mide EN LA INSTALADA: dos turnos del mismo chat
  // tienen que REUSAR el workdir, no fabricar uno nuevo.
  // ⚠️ DÓNDE VIVE EL RESUME, y por qué NO se mide por el chat de la Sala.
  // Medido en el código del bundle: la clave de conversación es el campo `sesion` del body
  // que recibe el `:8926` («la elige quien sabe qué es una conversación: el assembler»), y
  // `stream_chat._stream_openai` NO la manda — su body es model/stream/messages/max_tokens/
  // temperature/cli_model/effort y nada más. O sea que por el chat de texto no hay sesión
  // que resumir, y una prueba que lo intentara por ahí saldría roja acusando a la app de un
  // hueco que está en el transporte. Se mide donde el mecanismo EXISTE: contra el `:8926`
  // que administra el bundle, con dos turnos de la MISMA clave.
  //
  // Lo que F4d arregló es el slug que no encontraba su workdir; eso es lo que se verifica:
  // misma clave ⇒ MISMO workdir, no uno nuevo por turno.
  const dirSes = join(DATADIR, "cli_sesiones");
  const listar = () => { try { return readdirSync(dirSes); } catch { return []; } };
  const clave = `f6-resume-${Date.now()}`;
  const turnoCli = async (texto) => {
    try {
      const r = await fetch(`${CLI_BRAIN}/chat/completions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: "claude-code-cli", stream: false, max_tokens: 32,
                               sesion: clave, messages: [{ role: "user", content: texto }] }),
        signal: AbortSignal.timeout(200000),
      });
      return await r.json().catch(() => null);
    } catch { return null; }
  };
  const antesSes = listar();
  const r1 = await turnoCli("Decí exactamente: UNO");
  const tras1 = listar();
  const r2 = await turnoCli("Decí exactamente: DOS");
  const tras2 = listar();
  const creados1 = tras1.filter((d) => !antesSes.includes(d));
  const nuevos2 = tras2.filter((d) => !tras1.includes(d));

  if (!r1 || !r2) {
    anotar("cli", "RESTAURACIÓN", NO_MEDIBLE,
      "los turnos contra el :8926 del bundle no cerraron — sin dos turnos no hay resume que observar");
  } else if (creados1.length === 0) {
    anotar("cli", "RESTAURACIÓN", ROJO,
      `el 1er turno con clave no creó workdir en ${dirSes}: la sesión no se está persistiendo`, true);
  } else {
    anotar("cli", "RESTAURACIÓN", nuevos2.length === 0 ? VERDE : ROJO,
      nuevos2.length === 0
        ? `misma clave ⇒ MISMO workdir (${creados1[0]}): el 2º turno no fabricó uno nuevo — ` +
          `el slug de F4d encuentra su sesión EN LA INSTALADA`
        : `el 2º turno fabricó ${nuevos2.length} workdir(s) nuevo(s): el slug no encontró su sesión`,
      true);
  }
  // La llave se guardó ANTES de los dos reinicios de esta suite. Que siga estando —y que
  // siga SIRVIENDO para correr un turno— es la restauración de la vía API: no alcanza con
  // que la fila exista, tiene que descifrarse y resolver el byok_ref después de reabrir.
  if (!orCargada) {
    anotar("api", "RESTAURACIÓN", NO_MEDIBLE, "sin llave no hay estado de vía API que restaurar");
  } else {
    const ks = await jget(`/v1/users/${UID}/keys`, 30000);
    const fila = (Array.isArray(ks.json) ? ks.json : ks.json?.keys || [])
      .find((k) => String(k.provider) === "openrouter");
    const s = await stream(R_API, "Decí exactamente: VUELVO", { ms: 150000, userId: UID });
    const texto = (s.eventos.find((e) => e.type === "done")?.answer || "").trim();
    anotar("api", "RESTAURACIÓN", fila && texto ? VERDE : ROJO,
      fila && texto
        ? `tras DOS reinicios la llave sigue guardada (…${fila.last4 ?? "?"}) y el turno corre: ${JSON.stringify(texto.slice(0, 40))}`
        : (!fila ? "la llave no sobrevivió al reinicio" : "la llave está pero el turno no devolvió contenido"),
      true);
  }
}
log("");

/* ══ 8 · ADUANA/LOCAL — el anti-yo-yo, con reinicio real ═══════════════════════════ */
log("8 · ADUANA/LOCAL — el local sólo completas · la incompleta con su trámite · el anti-yo-yo");
{
  const v2 = await jget("/v1/modelos/v2", 60000);
  const filas = v2.json?.filas || [];
  const tieneCampos = filas.length > 0 &&
    filas.every((f) => "origen" in f && "conectado" in f && "estuvo_completa" in f);

  anotar("local", "ADUANA/LOCAL", tieneCampos ? VERDE : ROJO,
    tieneCampos ? `las ${filas.length} filas traen origen/conectado/estuvo_completa (la pieza de F4c viajó)`
                : "el bundle NO expone origen/conectado/estuvo_completa: la obra de F4c no viajó",
    true);

  // ── EL ANTI-YO-YO, MEDIDO CON REINICIO REAL ──────────────────────────────────────
  // Se corona un modelo como probado en la DB (la COPIA), se le pone encima una causa de
  // fallo, se REINICIA el proceso, y se exige que siga en el local con su causa — no que
  // caiga a la aduana. Es exactamente el ciclo que F4c probó con proceso nuevo, ahora
  // contra el binario instalado.
  const db = join(DATADIR, "aleph.db");
  const sql = (q) => {
    try { return execFileSync("sqlite3", [db, q], { encoding: "utf8" }).trim(); }
    catch (e) { return `ERROR:${String(e.message || e).slice(0, 80)}`; }
  };
  const cols = sql("select group_concat(name) from pragma_table_info('modelos_estado');");
  if (!cols || cols.startsWith("ERROR") || cols === "") {
    anotar("local", "ANTI-YO-YO", ROJO,
      "la tabla `modelos_estado` no existe en la DB del bundle — la migración 8 no viajó", true);
  } else {
    // La PK es (user_id, modelo_id) — NO `slug`. El user_id tiene que ser el de la sesión
    // real: la FK a `users` es ON DELETE CASCADE y un id inventado no entra.
    const modeloId = "ollama:qwen3:8b";
    const uid = sesion.json?.id || sql("select id from users order by rowid desc limit 1;");
    // EL ESTADO DE REGRESIÓN, tal como lo define el schema: veredicto 'probado' (MEMORIA:
    // anduvo) CON una causa de fallo encima (MEDICIÓN VIVA: hoy no anda). No es una
    // contradicción: es exactamente la fila que tiene que quedarse en el LOCAL con su causa
    // en vez de caer a la aduana.
    const ins = sql(
      `insert or replace into modelos_estado (user_id, modelo_id, via, ultimo_veredicto, causa) ` +
      `values ('${uid}', '${modeloId}', 'local', 'probado', 'sin_runtime');`);
    const dónde = `user_id='${uid}' and modelo_id='${modeloId}'`;
    const antes = sql(`select ultimo_veredicto from modelos_estado where ${dónde};`);

    await bajar();
    salud = await levantar("anti-yo-yo");
    const s3 = await jpost("/v1/auth/local", {});
    TOKEN = s3.json?.session_token || TOKEN;

    const despues = sql(`select ultimo_veredicto from modelos_estado where ${dónde};`);
    const causa = sql(`select causa from modelos_estado where ${dónde};`);
    const v2b = await jget("/v1/modelos/v2", 60000);
    const fila = (v2b.json?.filas || []).find((f) => String(f.slug).includes("qwen3"));
    const memoria = antes === "probado" && despues === "probado";
    anotar("local", "ANTI-YO-YO",
      (ins.startsWith("ERROR") || antes.startsWith("ERROR")) ? NO_MEDIBLE : (memoria ? VERDE : ROJO),
      (ins.startsWith("ERROR") || antes.startsWith("ERROR"))
        ? `no pude sembrar el estado (${(ins.startsWith("ERROR") ? ins : antes).slice(0, 110)})`
        : (memoria
           ? `tras REINICIAR el proceso el veredicto sigue 'probado' con causa '${causa}' ` +
             `(estuvo_completa=${fila?.estuvo_completa}) — no cayó a la aduana`
           : `el veredicto se degradó en el arranque: antes='${antes}' después='${despues}' — el yo-yo está vivo`),
      true);
  }

  // La superficie (local vs aduana) es de funciones puras que VIAJAN como asset del bundle:
  // se mide el marcado sin levantar un browser, igual que en Gate 1.
  const superficie = join(DATADIR, "_assets_superficie");
  let extraidos = 0;
  try {
    const py = `
import os
from PyInstaller.archive.readers import CArchiveReader
r = CArchiveReader(${JSON.stringify(SIDECAR)})
n = 0
for nombre in r.toc:
    if "design/modelos/" not in nombre:
        continue
    d = r.extract(nombre)
    datos = d[-1] if isinstance(d, tuple) else d
    if datos is None:
        continue
    ruta = os.path.join(${JSON.stringify(superficie)}, os.path.basename(nombre))
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    open(ruta, "wb").write(datos)
    n += 1
print(n)`;
    extraidos = Number(execFileSync(join(RAIZ, "product/backend/.venv/bin/python"), ["-c", py],
                                    { encoding: "utf8" }).trim());
  } catch { extraidos = 0; }
  anotar("local", "SUPERFICIE", extraidos >= 2 ? VERDE : ROJO,
    extraidos >= 2 ? `${extraidos} archivos de design/modelos/ VIAJARON en el bundle (widget + superficie)`
                   : `sólo ${extraidos} archivos de design/modelos/ en el bundle — la pantalla de F4c no viajó`,
    true);
}

await bajar();

/* ══ EL PARTE ═══════════════════════════════════════════════════════════════════════ */
const cuenta = (v) => M.filter((m) => m.veredicto === v).length;
const rojas = M.filter((m) => m.veredicto === ROJO);
const discrim = M.filter((m) => m.discrimina);

log("");
log("═".repeat(100));
log("  MATRIZ VÍA × PRUEBA");
log("═".repeat(100));
const pruebas = [...new Set(M.map((m) => m.prueba))];
const vias = [...new Set(M.map((m) => m.via))];
log("  " + "prueba".padEnd(16) + vias.map((v) => v.padEnd(14)).join(""));
for (const p of pruebas) {
  const celdas = vias.map((v) => {
    const r = M.find((m) => m.via === v && m.prueba === p);
    return (!r ? "—" : r.veredicto === VERDE ? "✅ verde" : r.veredicto === ROJO ? "❌ ROJO" : "⚪ no medible").padEnd(14);
  });
  log("  " + p.padEnd(16) + celdas.join(""));
}
log("");
log(`  VERDE ${cuenta(VERDE)}  ·  ROJO ${cuenta(ROJO)}  ·  NO MEDIBLE ${cuenta(NO_MEDIBLE)}  ·  ${seg()}s`);
log(`  SIDECAR ${HASH}`);
log(`  DISCRIMINANTES (obra de Gate 2): ${discrim.filter((m) => m.veredicto === VERDE).length}/${discrim.length} en verde`);
if (RATE_LIMITS.length) {
  log(`  RATE LIMITS vistos: ${RATE_LIMITS.length} — DATO, no fallo. Llegaron TIPADOS:`);
  for (const r of RATE_LIMITS)
    log(`     · ${r.via}: causa=rate_limit · retry_after_s=${r.retry_after_s} · reintentable=${r.reintentable}`);
} else {
  log("  RATE LIMITS vistos: 0 (la corrida no agotó ninguna cuota)");
}
log("═".repeat(100));
if (rojas.length) {
  log("ROJAS:");
  for (const r of rojas) log(`  ✗ ${r.via} · ${r.prueba}: ${r.detalle}`);
}
log("");
log("JSON " + JSON.stringify({
  app: APP, sidecar: HASH,
  verde: cuenta(VERDE), rojo: cuenta(ROJO), no_medible: cuenta(NO_MEDIBLE),
  discriminantes_verdes: discrim.filter((m) => m.veredicto === VERDE).length,
  discriminantes_total: discrim.length,
  matriz: M,
}));

try { rmSync(DATADIR, { recursive: true, force: true }); } catch { /* da igual */ }
process.exit(rojas.length ? 1 : 0);
