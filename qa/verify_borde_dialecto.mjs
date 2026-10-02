/* verify_borde_dialecto.mjs — EL BORDE DE DIALECTO ≡ LA PUERTA DE LA CASA.
 * [Gate 4 · F3-ciencia · ley 0 costura (1)]
 *
 * ENUNCIADO. Un stack heredado con capa de proveedores propia no sabe pedir por la puerta
 * de la casa: sabe pedir `/v1/chat/completions`. `POST /v1/workspaces/brain/openai/chat/
 * completions` es ese borde. Lo único que esta vara tiene que probar es que **el borde no
 * es un segundo camino al cerebro**: que un turno por ahí produce EXACTAMENTE lo mismo que
 * el mismo turno por `brain/complete` — mismo `model_final`, mismo `workspace_step`.
 *
 * POR QUÉ ESO ES LO QUE HAY QUE MEDIR. Un borde que resolviera modelos por su cuenta, o que
 * escribiera su propio evento, sería un enchufe nuevo disfrazado de traductor: el harness
 * volvería a elegir cerebro por la puerta de atrás y la procedencia del anti-grift dejaría
 * de valer. La defensa es de diseño (el borde LLAMA a `workspace_brain_complete`, no lo
 * reimplementa), y esta vara es la que verifica que la defensa sigue siendo cierta.
 *
 * EL PROVEEDOR ES DETERMINISTA, Y ES A PROPÓSITO. Comparar dos turnos exige que el turno
 * sea reproducible; con un modelo real, dos corridas difieren y la comparación no probaría
 * nada. La vara levanta su propio endpoint OpenAI-compatible guionado y apunta la RECETA
 * ahí. O sea: el proveedor es de mentira, pero **el circuito es el de verdad** —
 * `resolve_recipe_model` → `_route_chat` → `_chat` → `_honest_model_final` → `workspace_step`
 * corren enteros, sin stubs. Lo que se afirma es la identidad de las dos puertas, no que
 * un proveedor concreto funcione (eso lo certificó Gate 2).
 *
 * NO ANIDA VARAS (regla sellada): acá adentro sólo vive lo propio.
 *
 * Uso:  node qa/verify_borde_dialecto.mjs
 *       PYBIN=<python del venv>   SIDECAR=<binario>   PUERTO=<n>
 */
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PUERTO = Number(process.env.PUERTO || 8391);
const BASE = `http://127.0.0.1:${PUERTO}`;
const PROV_PUERTO = Number(process.env.PROV_PUERTO || 8392);
const PROV = `http://127.0.0.1:${PROV_PUERTO}/v1`;
const SIDECAR = process.env.SIDECAR || "";
const PYBIN = process.env.PYBIN || fileURLToPath(new URL("../product/backend/.venv/bin/python", import.meta.url));
// El borde es común a todos los stacks; el workspace se hace explícito para que cada
// vertical pueda certificar que su propio espacio recibe el `workspace_step`.
const WORKSPACE = process.env.WORKSPACE || "ciencia";

//: El modelo que el proveedor guionado DICE haber usado.
//:
//: OJO CON LO QUE ESTO **NO** PRUEBA, porque esta vara ya se equivocó una vez acá. La
//: primera versión afirmaba que `model_final` tenía que ser este valor, leyendo el
//: docstring del adaptador («el modelo que reportó el proveedor»). Es falso fuera de
//: BYO-CLI: `_honest_model_final` (recipe_assembler.py:1317) sustituye por el reportado
//: **sólo** cuando el cerebro declarado es un provider CLI y respondió el primary; en
//: cualquier otro camino conserva a propósito la semántica histórica —el id PEDIDO del
//: tier que respondió— y lo dice en su propio comentario. La afirmación estaba mal, no el
//: código. Queda escrito para que nadie la vuelva a poner.
const MODELO_REPORTADO = "modelo-del-proveedor-9000";
//: Lo que el harness ajeno va a PEDIR en el campo `model` de OpenAI. Tiene que ser ignorado.
const MODELO_PEDIDO_POR_EL_HARNESS = "gpt-4-que-nadie-le-dio";

const fails = [];
const oks = [];
const ok = (n, d) => { oks.push(n); console.log(`  ✅ ${n}${d ? " — " + d : ""}`); };
const bad = (n, d) => { fails.push(`${n}${d ? " — " + d : ""}`); console.log(`  ❌ ${n}${d ? " — " + d : ""}`); };
const sec = (t) => console.log(`\n── ${t} ${"─".repeat(Math.max(0, 74 - t.length))}`);

const DATA = mkdtempSync(join(tmpdir(), "borde-vara-"));
let backend = null;
let proveedor = null;

// ── EL PROVEEDOR GUIONADO ─────────────────────────────────────────────────────────────
// OpenAI-compatible, no streamea (la casa pide sin stream) y contesta siempre lo mismo:
// una jugada con tool_call. Cuenta cuántas veces la llamaron, que es cómo se comprueba que
// las DOS puertas salieron a pedir de verdad y ninguna contestó de un caché.
let llamadasAlProveedor = 0;
function arrancarProveedor() {
  return new Promise((resolve) => {
    proveedor = createServer((req, res) => {
      let cuerpo = "";
      req.on("data", (c) => (cuerpo += c));
      req.on("end", () => {
        if (req.url.includes("/models")) {
          res.writeHead(200, { "Content-Type": "application/json" });
          return res.end(JSON.stringify({ object: "list", data: [{ id: MODELO_REPORTADO }] }));
        }
        llamadasAlProveedor += 1;
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
          id: "cmpl-guionado",
          object: "chat.completion",
          created: 1754769600,
          model: MODELO_REPORTADO,
          choices: [{
            index: 0,
            message: {
              role: "assistant",
              content: "",
              tool_calls: [{
                id: "call_1", type: "function",
                function: { name: "add", arguments: JSON.stringify({ a: 21, b: 21 }) },
              }],
            },
            finish_reason: "tool_calls",
          }],
          usage: { prompt_tokens: 111, completion_tokens: 22, total_tokens: 133 },
        }));
      });
    });
    proveedor.listen(PROV_PUERTO, "127.0.0.1", resolve);
  });
}

// ── EL RODEO DE LOS TRES `models.py` ──────────────────────────────────────────────────
// DEFECTO PRE-EXISTENTE, DEV-ONLY, AJENO A ESTA OBRA. Medido acá con su mecanismo entero:
//
//   `platform/inspection/dueno.py:59-62` hace `sys.path.insert(0, platform/inspection)`, y
//   `dueno` se importa en el ARRANQUE (`product/backend/app/main.py:173`). Desde ese
//   instante un `import models` a secas resuelve a `platform/inspection/models.py` en vez
//   de `platform/assembler/models.py`, que es el que tiene `resolve_recipe_model`. El
//   assembler pide su `models` mucho después, ya envenenado: TODO turno con receta muere
//   con `module 'models' has no attribute 'resolve_recipe_model'`.
//
// SE VE SÓLO BAJO UVICORN, y por eso puede sobrevivir sin que nadie lo note: un
// `TestClient` sin `with` no dispara el lifespan, así que `dueno` nunca se importa y el
// mismo turno da 200. Medido lado a lado en esta obra.
//
// NO SE ARREGLA ACÁ. Tocar el orden de imports de la casa es cirugía de OTRA OBRA, en su
// propia rama y con su vara propia (que un turno con receta bajo uvicorn dé 200 SIN rodeo).
// Lo que hace esta vara es lo único honesto que puede hacer mientras tanto: **declararlo y
// rodearlo en su propio arnés**, jamás en el producto. El rodeo pre-importa el `models`
// correcto ANTES de que nadie más pida uno; nadie en `platform/inspection/` importa
// `models` a secas (medido), así que ganar esa carrera no le cambia el módulo a nadie.
//
// ⚠️ CONTRA LA `.app` EL RODEO VA **APAGADO**, Y NO ES UN DETALLE DEL ARNÉS.
// El congelado empaqueta los módulos de otra manera y Gate 2/2.5 certificaron ese camino
// sobre la `.app`: si el binario instalado necesitara este rodeo, la premisa «es dev-only»
// sería falsa y el veredicto de la fase cambiaría —querría decir que el defecto viaja al
// producto—. Por eso la vara no se limita a apagarlo: **lo afirma**. Contra el congelado,
// un 502 con `resolve_recipe_model` no se rodea, se reporta en rojo y a gritos.
//: `true` sólo cuando el sujeto es el binario congelado. Decide si el rodeo se escribe.
const CONGELADO = Boolean(SIDECAR);

//: La firma del defecto ajeno, para poder distinguirlo de cualquier otro 502.
const esDefectoDeDueno = (j) => /resolve_recipe_model/.test(JSON.stringify(j || {}));

function escribirRodeo() {
  const dir = mkdtempSync(join(tmpdir(), "borde-rodeo-"));
  writeFileSync(join(dir, "sitecustomize.py"), [
    "# rodeo del arnés de verify_borde_dialecto.mjs — ver el comentario de la vara.",
    "import importlib.util as _u, sys as _s",
    `_p = ${JSON.stringify(join(process.cwd(), "platform", "assembler", "models.py"))}`,
    "_spec = _u.spec_from_file_location('models', _p)",
    "_m = _u.module_from_spec(_spec)",
    "_s.modules['models'] = _m",
    "_spec.loader.exec_module(_m)",
    "",
  ].join("\n"));
  return dir;
}
//: Contra la `.app`: null. Contra fuente: el directorio con el `sitecustomize`.
const RODEO = CONGELADO ? null : escribirRodeo();

function arrancarBackend() {
  const env = {
    ...process.env,
    ALEPH_DATA_DIR: DATA, ALEPH_ENV: "dev",
    PUPPET_ALLOW_PASSWORD_AUTH: "1", PUPPET_ALLOW_ANON_V1: "1",
  };
  // El rodeo entra al entorno SÓLO en dev-desde-fuente. Contra el congelado, `PYTHONPATH`
  // queda como venía: si el binario necesitara el rodeo, tiene que verse.
  if (RODEO) env.PYTHONPATH = [RODEO, process.env.PYTHONPATH].filter(Boolean).join(":");
  if (SIDECAR) {
    const p = spawn(SIDECAR, ["--port", String(PUERTO)], { env, detached: true, stdio: ["ignore", "pipe", "pipe"] });
    p.unref();
    return p;
  }
  const p = spawn(PYBIN, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(PUERTO)],
                  { env, cwd: "product/backend", detached: true, stdio: ["ignore", "pipe", "pipe"] });
  p._log = [];
  p.stdout.on("data", (b) => p._log.push(String(b)));
  p.stderr.on("data", (b) => p._log.push(String(b)));
  p.unref();
  return p;
}
function matarBackend(p) {
  if (!p) return;
  try { process.kill(-p.pid, "SIGKILL"); } catch (_) { try { p.kill("SIGKILL"); } catch (__) {} }
  spawnSync("pkill", ["-f", `ALEPH_DATA_DIR=${DATA}`]);
}
async function esperar(url, ms = 60000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try { const r = await fetch(url, { signal: AbortSignal.timeout(2500) }); if (r.ok) return true; } catch (_) {}
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

//: La vara no puede morir muda (lección sellada): el cierre se registra ANTES de lo que
//: tiene que cubrir, o no existe todavía en el instante del crash que debería atrapar.
let cerrado = false;
function cerrar(motivo) {
  if (cerrado) return;
  cerrado = true;
  matarBackend(backend);
  try { proveedor?.close(); } catch (_) {}
  rmSync(DATA, { recursive: true, force: true });
  try { if (RODEO) rmSync(RODEO, { recursive: true, force: true }); } catch (_) {}
  console.log(`\n${"═".repeat(78)}`);
  if (motivo) console.log(`  ⛔ LA VARA NO LLEGÓ AL FINAL — ${motivo}`);
  console.log(`  ${oks.length} verdes · ${fails.length} rojas${motivo ? "  (PARCIAL: lo que sigue no se midió)" : ""}`);
  if (fails.length) { console.log("\n  ROJAS:"); fails.forEach((f) => console.log("   ✗ " + f)); }
  console.log(`  llamadas al proveedor guionado: ${llamadasAlProveedor}`);
  console.log(`${"═".repeat(78)}\n`);
  process.exit(motivo || fails.length ? 1 : 0);
}
process.on("uncaughtException", (e) => cerrar(`EXCEPCIÓN: ${e?.message || e}`));
process.on("unhandledRejection", (e) => cerrar(`RECHAZO: ${e?.message || e}`));

const J = (r) => r.json();
let U = null;
const H = () => ({ "Content-Type": "application/json", Authorization: "Bearer " + U.session_token });

// ═══════════════════════════════════════════════════════════════════════════════════════
console.log(`\n· sujeto      ${SIDECAR || `${PYBIN} -m uvicorn (fuente)`}`);
console.log(`· datadir     ${DATA}   (aislado)`);
console.log(`· proveedor   ${PROV}   (guionado, determinista)`);
console.log(`· rodeo dueno ${RODEO ? "ACTIVO (dev desde fuente — defecto ajeno, declarado)" : "APAGADO (congelado: no debe necesitarlo)"}`);

await arrancarProveedor();
backend = arrancarBackend();
if (!(await esperar(`${BASE}/health`))) {
  console.log((backend?._log || []).join("").slice(-2000));
  cerrar("el backend no levantó");
}

const cuenta = { email: `borde-${Date.now()}@aleph.local`, password: "vara-del-borde-1307" };
for (const ruta of ["/v1/auth/register", "/v1/auth/login"]) {
  const r = await fetch(BASE + ruta, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuenta) });
  if (!r.ok) continue;
  const j = await J(r).catch(() => null);
  if (j?.session_token) { U = j; break; }
}
if (!U) cerrar("sin sesión");
console.log(`· cuenta      ${U.id}\n`);

const RECIPE = {
  schema_version: "v1",
  meta: { name: "borde-vara", nicho: "general", output_type: "informe" },
  model: { alias: "guionado", primary: "primary-de-la-receta", base_url: PROV,
           temperature: 0, max_tokens: 200, max_turns: 2 },
  belt: { belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
          tool_filters: { calc: ["add"] } },
  framing: { inline: "" }, rag: { enabled: false }, keys: {}, gates: {},
};

const MENSAJES = [{ role: "user", content: "Sumá 21 más 21 con la herramienta add." }];
const TOOLS = [{ type: "function", function: {
  name: "add", description: "Suma dos números",
  parameters: { type: "object", properties: { a: { type: "number" }, b: { type: "number" } },
                required: ["a", "b"] } } }];

// ── PASO 0 · UN AGENTE GUARDADO, para que las dos puertas resuelvan LA MISMA receta ────
sec("PASO 0 · el agente guardado (las dos puertas tienen que salir de la misma receta)");
let PUPPET = null;
{
  const r = await fetch(`${BASE}/v1/puppets`, { method: "POST", headers: H(),
    body: JSON.stringify({ name: "borde-vara", nicho: "general", owner_id: U.id, config: RECIPE }) });
  const j = await J(r).catch(() => null);
  PUPPET = j?.id || j?.puppet_id || null;
  if (PUPPET) ok("el agente se guarda y su receta es la de las dos puertas", `puppet=${PUPPET}`);
  else bad("el agente se guarda", `HTTP ${r.status} · ${JSON.stringify(j).slice(0, 200)}`);
}
if (!PUPPET) cerrar("sin agente guardado no hay comparación posible");

const pasos = async (space) => {
  const r = await fetch(`${BASE}/v1/spaces/${space}/events`, { headers: H() });
  const j = await J(r).catch(() => null);
  const evts = Array.isArray(j) ? j : (j?.events || []);
  return evts.filter((e) => (e?.type || e?.event) === "workspace_step");
};

// ── PASO 1 · LA PUERTA DE LA CASA (el testigo) ────────────────────────────────────────
sec("PASO 1 · POST /v1/workspaces/brain/complete — el testigo");
const ESPACIO_A = `borde-a-${Date.now().toString(36)}`;
let CASA = null, PASO_CASA = null;
{
  const r = await fetch(`${BASE}/v1/workspaces/brain/complete`, { method: "POST", headers: H(),
    body: JSON.stringify({ puppet_id: PUPPET, user_id: U.id, space_id: ESPACIO_A,
                           workspace: WORKSPACE, turn: 7, messages: MENSAJES, tools: TOOLS }) });
  CASA = await J(r).catch(() => null);
  if (r.status === 200 && CASA) ok("la puerta de la casa contesta la jugada", `model=${CASA.model} · tool_calls=${(CASA.tool_calls || []).length}`);
  else bad("la puerta de la casa contesta la jugada", `HTTP ${r.status} · ${JSON.stringify(CASA).slice(0, 240)}`);
  const p = await pasos(ESPACIO_A);
  PASO_CASA = p[p.length - 1] || null;
  if (PASO_CASA) ok("y deja su `workspace_step` en el espacio", `model=${PASO_CASA.model}`);
  else bad("deja su `workspace_step` en el espacio", "no apareció ninguno");

  // EL VEREDICTO SOBRE EL DEFECTO AJENO, dicho explícitamente y no por omisión.
  if (CONGELADO) {
    if (esDefectoDeDueno(CASA))
      bad("EL CONGELADO NO DEBE NECESITAR EL RODEO DE dueno.py",
          "la `.app` instalada murió con `resolve_recipe_model` SIN rodeo — el defecto NO es dev-only y el veredicto de la fase cambia");
    else
      ok("el congelado NO necesita el rodeo de dueno.py", "corrió con PYTHONPATH limpio — el defecto es dev-only, como se declaró");
  } else {
    console.log("     · nota: dev desde fuente, con el rodeo del defecto ajeno ACTIVO. La afirmación");
    console.log("       «el congelado no lo necesita» sólo la puede dar una corrida con SIDECAR=…");
  }
}

// ── PASO 2 · EL BORDE, con el MISMO turno ─────────────────────────────────────────────
sec("PASO 2 · POST /v1/workspaces/brain/openai/chat/completions — el mismo turno");
const ESPACIO_B = `borde-b-${Date.now().toString(36)}`;
let BORDE = null, PASO_BORDE = null;
const CAB = () => ({
  "Content-Type": "application/json",
  Authorization: "Bearer " + U.session_token,
  "X-Aleph-Puppet": PUPPET, "X-Aleph-User": U.id, "X-Aleph-Space": ESPACIO_B,
  "X-Aleph-Workspace": WORKSPACE, "X-Aleph-Turn": "7",
});
{
  const r = await fetch(`${BASE}/v1/workspaces/brain/openai/chat/completions`, { method: "POST", headers: CAB(),
    body: JSON.stringify({ model: MODELO_PEDIDO_POR_EL_HARNESS, messages: MENSAJES, tools: TOOLS, stream: false }) });
  BORDE = await J(r).catch(() => null);
  const ch = BORDE?.choices?.[0];
  if (r.status === 200 && ch?.message) ok("el borde contesta en forma OpenAI", `object=${BORDE.object} · finish=${ch.finish_reason}`);
  else bad("el borde contesta en forma OpenAI", `HTTP ${r.status} · ${JSON.stringify(BORDE).slice(0, 240)}`);
  const p = await pasos(ESPACIO_B);
  PASO_BORDE = p[p.length - 1] || null;
  if (PASO_BORDE) ok("y deja su `workspace_step` en el espacio", `model=${PASO_BORDE.model}`);
  else bad("deja su `workspace_step` en el espacio", "no apareció ninguno");
}

// ── PASO 3 · LA IDENTIDAD — que es todo el punto de la vara ───────────────────────────
sec("PASO 3 · el borde NO es un segundo camino: los dos turnos son el mismo");
{
  const mCasa = CASA?.model, mBorde = BORDE?.model;
  if (mCasa && mBorde && mCasa === mBorde) ok("`model_final` idéntico por las dos puertas", mCasa);
  else bad("`model_final` idéntico por las dos puertas", `casa=${mCasa} · borde=${mBorde}`);

  // Lo que hace honesta a la tarjeta no es «el modelo del proveedor» (ver la nota de
  // MODELO_REPORTADO): es que el modelo salga de la RECETA y no del harness. Eso es lo que
  // se afirma acá, y el PASO 4 lo cierra por el otro lado.
  if (mBorde && mBorde !== MODELO_PEDIDO_POR_EL_HARNESS && mBorde === mCasa)
    ok("y sale de la receta, exactamente como por la puerta de la casa", mBorde);
  else bad("el modelo sale de la receta", `casa=${mCasa} · borde=${mBorde}`);

  // El `workspace_step`: mismos campos, mismos valores, salvo el espacio (que es otro a
  // propósito, para poder leerlos por separado).
  const norm = (e) => e ? {
    type: e.type ?? e.event, kind: e.kind, workspace: e.workspace, turn: e.turn,
    model: e.model, tools_declared: e.tools_declared,
    tool_calls_requested: e.tool_calls_requested, byok: e.byok,
  } : null;
  const a = norm(PASO_CASA), b = norm(PASO_BORDE);
  if (a && b && JSON.stringify(a) === JSON.stringify(b))
    ok("`workspace_step` IDÉNTICO por las dos puertas", JSON.stringify(b));
  else bad("`workspace_step` idéntico por las dos puertas", `casa=${JSON.stringify(a)} · borde=${JSON.stringify(b)}`);

  // La jugada misma: mismas tool_calls, mismo nombre y mismos argumentos.
  const callsCasa = (CASA?.tool_calls || []).map((c) => `${c.name}:${c.arguments}`);
  const callsBorde = (BORDE?.choices?.[0]?.message?.tool_calls || []).map((c) => `${c.function?.name}:${c.function?.arguments}`);
  if (callsCasa.length && JSON.stringify(callsCasa) === JSON.stringify(callsBorde))
    ok("las tool_calls cruzan sin perder nada", callsBorde.join(" · "));
  else bad("las tool_calls cruzan sin perder nada", `casa=${JSON.stringify(callsCasa)} · borde=${JSON.stringify(callsBorde)}`);

  // Las dos puertas SALIERON A PEDIR de verdad: dos turnos, dos llamadas al proveedor.
  if (llamadasAlProveedor >= 2) ok("las dos puertas salieron al proveedor (ninguna contestó de un caché)", `${llamadasAlProveedor} llamadas`);
  else bad("las dos puertas salieron al proveedor", `${llamadasAlProveedor} llamada(s)`);
}

// ── PASO 4 · EL `model` DEL HARNESS SE IGNORA ─────────────────────────────────────────
sec("PASO 4 · el harness no elige cerebro (su `model` entra y se ignora)");
{
  const m = BORDE?.model || "";
  if (m && m !== MODELO_PEDIDO_POR_EL_HARNESS)
    ok("pidió un modelo y la casa devolvió el suyo", `pidió ${MODELO_PEDIDO_POR_EL_HARNESS} · sirvió ${m}`);
  else bad("el `model` del harness se ignora", `pidió ${MODELO_PEDIDO_POR_EL_HARNESS} · devolvió ${m}`);
  // Y el paso anotado en el espacio dice el modelo de la casa, no el pedido: si el evento
  // dijera lo que pidió el harness, la procedencia del anti-grift estaría mintiendo.
  if (PASO_BORDE?.model && PASO_BORDE.model !== MODELO_PEDIDO_POR_EL_HARNESS)
    ok("y el `workspace_step` anota el modelo de la casa", PASO_BORDE.model);
  else bad("el `workspace_step` anota el modelo de la casa", `model=${PASO_BORDE?.model}`);
}

// ── PASO 5 · SSE — que es como el stack pide SIEMPRE ──────────────────────────────────
sec("PASO 5 · streaming: el stack manda `stream:true` en cada turno");
{
  const ESPACIO_C = `borde-c-${Date.now().toString(36)}`;
  const r = await fetch(`${BASE}/v1/workspaces/brain/openai/chat/completions`, { method: "POST",
    headers: { ...CAB(), "X-Aleph-Space": ESPACIO_C },
    body: JSON.stringify({ model: MODELO_PEDIDO_POR_EL_HARNESS, messages: MENSAJES, tools: TOOLS, stream: true }) });
  const ct = r.headers.get("content-type") || "";
  const texto = await r.text();
  if (r.status === 200 && ct.includes("text/event-stream")) ok("contesta SSE", ct);
  else bad("contesta SSE", `HTTP ${r.status} · ${ct}`);

  const lineas = texto.split("\n").filter((l) => l.startsWith("data: "));
  const trozos = lineas.filter((l) => l !== "data: [DONE]").map((l) => { try { return JSON.parse(l.slice(6)); } catch { return null; } }).filter(Boolean);
  if (lineas[lineas.length - 1] === "data: [DONE]") ok("y cierra con [DONE]", `${lineas.length} líneas`);
  else bad("cierra con [DONE]", JSON.stringify(lineas.slice(-2)));

  const conTools = trozos.find((t) => t.choices?.[0]?.delta?.tool_calls);
  const tc = conTools?.choices?.[0]?.delta?.tool_calls?.[0];
  if (tc?.function?.name === "add" && tc?.index === 0) ok("la tool_call viaja en el delta, con su índice", `${tc.function.name}(${tc.function.arguments})`);
  else bad("la tool_call viaja en el delta", JSON.stringify(tc));

  const cierre = trozos.find((t) => t.choices?.[0]?.finish_reason);
  if (cierre?.choices?.[0]?.finish_reason === "tool_calls") ok("y el finish_reason es el del proveedor", "tool_calls");
  else bad("el finish_reason es el del proveedor", JSON.stringify(cierre?.choices?.[0]));

  // Un solo modelo en todos los chunks, y el MISMO que dio la puerta de la casa: un chunk
  // que dijera otra cosa a mitad del stream sería una tarjeta que cambia de sujeto.
  const modelos = new Set(trozos.map((t) => t.model));
  if (modelos.size === 1 && modelos.has(CASA?.model)) ok("todos los chunks dicen el mismo modelo que la casa", CASA?.model);
  else bad("todos los chunks dicen el mismo modelo que la casa", `casa=${CASA?.model} · chunks=${[...modelos].join(", ")}`);

  // El streaming NO puede saltearse el espacio: un turno es un turno, lo pida como lo pida.
  const p = await pasos(ESPACIO_C);
  if (p.length === 1) ok("el turno por SSE también deja su `workspace_step`", `model=${p[0].model}`);
  else bad("el turno por SSE deja su `workspace_step`", `${p.length} eventos`);
}

// ── PASO 6 · `usage`: se propaga medido, jamás se inventa ─────────────────────────────
sec("PASO 6 · usage — se propaga lo medido, y nada más");
{
  const u = BORDE?.usage;
  if (u && u.prompt_tokens === 111 && u.completion_tokens === 22)
    ok("el `usage` del proveedor cruza intacto", JSON.stringify(u));
  else bad("el `usage` del proveedor cruza intacto", JSON.stringify(u));
  // La casa omite `usage` cuando no hubo medición; el borde tiene que omitirlo igual, jamás
  // rellenar con ceros (un dict de ceros contaría como llamada medida).
  const casaU = CASA?.usage;
  const mismos = JSON.stringify(casaU || null) === JSON.stringify(u || null);
  if (mismos) ok("y es el MISMO que reporta la puerta de la casa", "sin ceros fabricados");
  else bad("el usage del borde es el de la casa", `casa=${JSON.stringify(casaU)} · borde=${JSON.stringify(u)}`);
}

// ── PASO 7 · FALLO VISIBLE: el sobre se traduce, la causa NO se pierde ────────────────
sec("PASO 7 · un error sale en sobre OpenAI, con la causa de la casa adentro");
{
  const r = await fetch(`${BASE}/v1/workspaces/brain/openai/chat/completions`, { method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + U.session_token },
    body: JSON.stringify({ model: "x", messages: MENSAJES, stream: false }) });   // sin X-Aleph-Puppet
  const j = await J(r).catch(() => null);
  // ── [LEY 15 · MODO RAW] ESTA ASERCIÓN SE DIO VUELTA, Y ES CORRECTO ────────────────
  // Decía «sin receta ni agente, RECHAZA» y era verdad cuando se escribió (F3-Ciencia).
  // La ley 15 la volvió falsa a propósito: **el agente jamás es requisito** — sin receta y
  // sin agente el borde tiene que ATENDER con el modelo del selector (`agent: null` es un
  // estado válido del camino). Dejarla como estaba sería exigirle al código que
  // contradiga una ley sellada.
  //
  // Se acepta CUALQUIERA de los dos finales legítimos, porque los dos son ley 15 y cuál
  // sale depende de la instalación, no del código: si hay un modelo elegido en el
  // selector, ATIENDE (200); si no hay ninguno, el 422 dice qué falta — «elegí un modelo»,
  // que es lo que el usuario puede hacer— y NO «te falta un agente», que es lo que la ley
  // prohíbe pedir.
  if (r.status === 200) {
    ok("[ley 15] sin receta ni agente, el borde ATIENDE con el modelo del selector",
       `HTTP 200 · model=${j?.model || "?"}`);
  } else if (r.status === 422 && (j?.detail?.error === "missing_recipe" || j?.error?.type === "missing_recipe")
             && /selector/i.test(JSON.stringify(j))) {
    ok("[ley 15] sin modelo elegido, pide ELEGIR MODELO (jamás crear un agente)",
       `HTTP 422 · ${JSON.stringify(j).slice(0, 90)}`);
  } else {
    bad("[ley 15] sin receta ni agente el borde atiende, o pide elegir modelo",
        `HTTP ${r.status} · ${JSON.stringify(j).slice(0, 140)}`);
  }
}

// El SOBRE DE ERROR se mide aparte, con un error de verdad. Antes se medía de rebote sobre
// el rechazo del paso 7 — y cuando la ley 15 dejó de rechazar, esta aserción se quedó sin
// error que mirar y caía de arrastre. Un `messages` vacío es inválido por contrato del
// borde (`sanitize_messages`) con o sin agente, así que el error existe siempre.
{
  const r = await fetch(`${BASE}/v1/workspaces/brain/openai/chat/completions`, { method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + U.session_token },
    body: JSON.stringify({ model: "x", messages: [], stream: false }) });
  const j = await J(r).catch(() => null);
  const err = j?.detail?.error || j?.error;
  if (r.status >= 400) ok("un pedido inválido SÍ se rechaza", `HTTP ${r.status}`);
  else bad("un pedido inválido SÍ se rechaza", `HTTP ${r.status}`);
  if (err && typeof err.message === "string" && err.type) ok("el sobre es el de OpenAI", `type=${err.type}`);
  else bad("el sobre es el de OpenAI", JSON.stringify(j).slice(0, 200));
  if (err?.aleph && (err.aleph.error || err.aleph.detail)) ok("y el detalle tipado de la casa viaja adentro", JSON.stringify(err.aleph).slice(0, 120));
  else bad("el detalle tipado de la casa viaja adentro", JSON.stringify(err).slice(0, 200));
}

cerrar(null);
