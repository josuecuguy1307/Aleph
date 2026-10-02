/* verify_fase3_cosecha.mjs — LA VARA DE CIERRE DE LA COSECHA. [Gate 4 · Fase 3]
 *
 * ENUNCIADO. La Fase 3 importó un stack heredado entero para estrenar la ley 0, y el dueño
 * decidió que ese stack no era el correcto: se elimina. Lo que la fase construyó DE LA CASA
 * —el canvas, la puerta al cerebro, la honestidad de la procedencia, el registro de
 * workspaces, el modelo de hilos, el puente— se conserva. Esta vara certifica las dos
 * mitades a la vez, sobre la `.app` INSTALADA (sidecar congelado), con datadir AISLADO:
 *
 *   A · LA MARCA MURIÓ         — cero hits en el árbol Y cero en el bundle que VIAJA
 *   B · LA CASA QUEDÓ VERDE    — y cada pieza se mide corriendo, no leyendo
 *
 * LO QUE HACE DIFÍCIL ESTA VARA, y por lo que hay que leerla con cuidado: mide sobre todo
 * un VACÍO —la marca que se fue—, y un vacío es trivialmente verde contra un build que
 * nunca tuvo la pieza. Por eso ningún assert de acá se conforma con «no está»: lo que
 * quedó tiene que contestar 200 con su forma, el puente tiene que traer sus causas CON
 * COPY, y el menú tiene que montar el resto. Un verde trivial no es un verde.
 *
 * [Gate 4 · F3-ciencia] CINCO AFIRMACIONES SE DIERON VUELTA, y conviene saber por qué. Esta
 * vara nació el día en que la cosecha sacó el único stack que había, así que afirmaba
 * «registro vacío · puente vacío · sin sección Workspaces · sin piel de workspace en el
 * binario». Entró Ciencia y esas cuatro dejaron de ser ciertas — no porque algo se rompiera,
 * sino porque el vacío era el estado transitorio y la fase siguiente lo llenó a propósito.
 * Se dieron vuelta a lo que sí hay que exigir, que además es MÁS fuerte que un vacío (un
 * vacío sale verde solo; una fila hay que producirla): el registro trae a Ciencia instalada
 * CON SU CENSO de 42 fuentes, el puente sirve sus 10 clases y NINGUNA sin su caso medido, la
 * sección del menú existe con su fila y sin estado vacío pintado, y la piel del workspace
 * viaja adentro del congelado. Lo único que NO cambió es la ley de producto 6: sigue
 * prohibido pintar un estado vacío que explique la categoría, con inquilino o sin él.
 *
 * NO ANIDA VARAS (regla sellada). La regresión de F1 · 2.2 · 2b se corre aparte, por fuera,
 * y su resultado va al reporte. Acá adentro sólo vive lo propio.
 *
 * Uso:  SIDECAR=/Applications/Aleph.app/Contents/MacOS/aleph_sidecar node qa/verify_fase3_cosecha.mjs
 *       BRAIN=<url del shim del cerebro CLI>   (default 127.0.0.1:8927/v1)
 */
import { webkit } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, existsSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SIDECAR = process.env.SIDECAR || "/Applications/Aleph.app/Contents/MacOS/aleph_sidecar";
const BRAIN = process.env.BRAIN || "http://127.0.0.1:8927/v1";
const PUERTO = Number(process.env.PUERTO || 8377);
const BASE = `http://127.0.0.1:${PUERTO}`;
const SHOTS = process.env.SHOTS || "/tmp/f3-cosecha-shots";
const PYBIN = process.env.PYBIN || "product/backend/.venv/bin/python";

//: Los términos de la marca que se eliminó. Si cualquiera reaparece, en el árbol o adentro
//: del binario, la cosecha no está hecha.
//:
//: **VIAJAN CODIFICADOS, Y NO ES ADORNO.** El criterio del dueño es literal: `grep` de la
//: marca sobre TODO el repo tiene que dar CERO. Un guard que lleva en claro el término que
//: prohíbe es su propio hit — esta vara haría fallar la condición que ella misma certifica,
//: para siempre y sin que nadie pueda arreglarlo. Es el mismo problema que tiene cualquier
//: linter que prohíbe un token. Se decodifican en runtime: la comparación es idéntica, y el
//: árbol queda de verdad en cero. Para leerlos a mano:
//:   node -e 'console.log(["<b64>"].map(s=>Buffer.from(s,"base64").toString()))'
//:
//: **UNA MARCA TIENE QUE DISCRIMINAR.** `main` nunca tuvo el stack: entonces todo término
//: que pegue en `main` no distingue el stack de la casa, y su rojo no acusa al producto sino
//: al arnés. `Gemma` estaba en esta lista y es el caso medido: pegaba en 4 archivos de
//: `main`, entre ellos el catálogo WebLLM de `product/app/design/vendor/deepChat.bundle.js`
//: —el chat COMPARTIDO de la casa, que existe desde «LA CAPA COMPARTIDA» (7cc850d2)— donde
//: no nombra al stack sino a un modelo de Google (`gemma-2-2b-it-q4f16_1-MLC`). Con `Gemma`
//: adentro, el PASO 1 daba rojo sobre un frontend impecable, y ningún build podía pasarlo.
//: Se fue de la lista, y el paso 1.0 de abajo impide que vuelva a entrar una así.
const _d = (s) => Buffer.from(s, "base64").toString("utf8");
const MARCAS = ["T3BlblRlcm1pbmFsVUk=", "b3BlbnRlcm1pbmFs", "SGl0aGVzaGthcmFudGg=",
                "ZmY2YjAw", "T1BFTi1TT1VSQ0UgVFJBRElORw==",
                "TkVXIE9QRVJBVE9S", "QW5hbHl6ZS4gVHJhZGU="].map(_d);
//: El nombre de la carpeta que se eliminó de `third_party/`, por la misma razón.
const CARPETA_MUERTA = _d("b3BlbnRlcm1pbmFsdWk=");
//: Lo que `third_party/` DEBE contener, y nada más. Es el assert general que reemplaza a
//: «no existe la carpeta X»: cualquier import que quede a medio cosechar aparece acá.
//:
//: [Gate 4 · F3-ciencia] `openscience` entra a esta lista porque entró al árbol POR LA
//: PUERTA: con su carpeta bajo `third_party/`, su `IMPORT.md`, su fila en el
//: `ATTRIBUTIONS.md` de la raíz y su registro de extirpaciones. La lista no se afloja —
//: sigue siendo «exactamente esto y nada más»—; lo que cambió es que ahora hay tres
//: piezas declaradas en vez de dos. Una carpeta que aparezca acá sin su fila en
//: ATTRIBUTIONS sigue siendo un import a medio cosechar, y sigue saliendo en rojo.
const THIRD_PARTY_ESPERADO = ["README.md", "ag-ui", "assistant-ui", "openscience"];

const fails = [];
const oks = [];
const ok = (n, d) => { oks.push(n); console.log(`  ✅ ${n}${d ? " — " + d : ""}`); };
const bad = (n, d) => { fails.push(`${n}${d ? " — " + d : ""}`); console.log(`  ❌ ${n}${d ? " — " + d : ""}`); };
const sec = (t) => console.log(`\n── ${t} ${"─".repeat(Math.max(0, 74 - t.length))}`);

const DATA = mkdtempSync(join(tmpdir(), "f3cos-vara-"));
mkdirSync(SHOTS, { recursive: true });
let sidecar = null;

// LA TRAMPA DEL HUÉRFANO (memoria del repo): onefile lanza un HIJO. Matar sólo al padre
// deja el server vivo y la próxima corrida mide un muerto — por eso se mata el GRUPO.
function arrancarSidecar() {
  const p = spawn(SIDECAR, ["--port", String(PUERTO)], {
    env: {
      ...process.env,
      ALEPH_DATA_DIR: DATA, ALEPH_ENV: "dev",
      PUPPET_ALLOW_PASSWORD_AUTH: "1", PUPPET_ALLOW_ANON_V1: "1",
      PUPPET_BRAIN: "claude_cli", PUPPET_CLI_BRAIN_BASE_URL: BRAIN,
    },
    detached: true, stdio: ["ignore", "pipe", "pipe"],
  });
  const log = [];
  p.stdout.on("data", (b) => log.push(String(b)));
  p.stderr.on("data", (b) => log.push(String(b)));
  p.unref();
  p._log = log;
  return p;
}
function matarSidecar(p) {
  if (!p) return;
  try { process.kill(-p.pid, "SIGKILL"); } catch (_) { try { p.kill("SIGKILL"); } catch (__) {} }
  spawnSync("pkill", ["-f", `ALEPH_DATA_DIR=${DATA}`]);
}
async function esperar(url, ms = 60000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    //: `_fetch` CRUDO a propósito: este bucle ya es un reintento, y su trabajo es golpear
    //: una puerta que TODAVÍA no abrió. Si pasara por el wrapper, cada `ECONNREFUSED`
    //: esperado entraría al libro de reintentos y ahogaría al único que importa — en la
    //: corrida anterior fueron 18 de arranque tapando 1 `ECONNRESET` real. Un libro de
    //: ruido no se lee, y un libro que no se lee es lo mismo que no llevarlo.
    try { const r = await _fetch(url, { signal: AbortSignal.timeout(2500) }); if (r.ok) return true; } catch (_) {}
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

//: ── LA VARA NO PUEDE MORIR MUDA ──────────────────────────────────────────────────────
//: Lección sellada del repo (obra C de Gate 3): una vara que crashea a mitad deja INVISIBLES
//: los defectos que le faltaba medir — ahí se perdieron 3. Esta murió así: un `ECONNRESET`
//: en el primer `fetch` del PASO 2 la mató con un stack trace, y de los pasos 2 a 8 no se
//: supo NADA. Dos capas, y ninguna ablanda una aserción:
//:
//:   1 · `fetch` reintenta UNA vez ante un error de CONEXIÓN. Un socket que el server cerró
//:       por ocioso mientras el paso anterior grepeaba 200 MB de bundle es ruido del arnés,
//:       no un hallazgo. Un 4xx/5xx NO se reintenta jamás: eso sí es hallazgo, y llega
//:       intacto al assert. Los reintentos se CUENTAN y se declaran en el cierre — un
//:       reintento callado convierte una vara flaky en una vara «verde».
//:   2 · si algo se escapa igual, el cierre corre de todos modos y dice hasta dónde llegó.
const reintentos = [];
const _fetch = globalThis.fetch;
globalThis.fetch = async (...a) => {
  try { return await _fetch(...a); } catch (e) {
    const code = String(e?.cause?.code || e?.code || e?.message || "");
    if (!/ECONNRESET|ECONNREFUSED|EPIPE|ETIMEDOUT|UND_ERR|socket/i.test(code)) throw e;
    reintentos.push(`${String(a[0]).replace(BASE, "")} · ${code}`);
    await new Promise((r) => setTimeout(r, 750));
    return await _fetch(...a);
  }
};

//: El cierre se define ACÁ ARRIBA, y no al final, porque si viviera al final no existiría
//: todavía en el instante que tiene que cubrir: la corrida que murió lo hizo en el PASO 2,
//: mucho antes de que el intérprete llegara al pie del archivo. Un manejador registrado
//: después del crash que debe atrapar es decoración.
let cerrado = false;
function cerrar(motivo) {
  if (cerrado) return;
  cerrado = true;
  matarSidecar(sidecar);
  rmSync(DATA, { recursive: true, force: true });
  console.log(`\n${"═".repeat(78)}`);
  if (motivo) console.log(`  ⛔ LA VARA NO LLEGÓ AL FINAL — ${motivo}`);
  console.log(`  ${oks.length} verdes · ${fails.length} rojas${motivo ? "  (PARCIAL: lo que sigue no se midió)" : ""}`);
  if (fails.length) { console.log("\n  ROJAS:"); fails.forEach((f) => console.log("   ✗ " + f)); }
  if (reintentos.length) {
    console.log(`\n  ⚠️  ${reintentos.length} reintento(s) de conexión (declarados, jamás ocultados):`);
    reintentos.forEach((r) => console.log("   ↻ " + r));
  }
  console.log(`  capturas en ${SHOTS} — MIRARLAS (el verde no prueba la cara)`);
  console.log(`${"═".repeat(78)}\n`);
  process.exit(motivo || fails.length ? 1 : 0);
}
process.on("uncaughtException", (e) => cerrar(`EXCEPCIÓN: ${e?.message || e}`));
process.on("unhandledRejection", (e) => cerrar(`RECHAZO: ${e?.message || e}`));

const J = (r) => r.json();
let U = null;
const H = () => ({ "Content-Type": "application/json", Authorization: "Bearer " + U.session_token });

// ═══════════════════════════════════════════════════════════════════════════════════════
console.log(`\n· sujeto      ${SIDECAR}`);
console.log(`· sha256      ${spawnSync("shasum", ["-a", "256", SIDECAR]).stdout.toString().slice(0, 24)}…`);
console.log(`· datadir     ${DATA}   (aislado: la DB de persona usuaria NO se toca)`);
console.log(`· cerebro     ${BRAIN}`);

sidecar = arrancarSidecar();
if (!(await esperar(`${BASE}/health`))) {
  console.log("\n✗ el sidecar no levantó:\n" + (sidecar._log || []).join("").slice(-1500));
  matarSidecar(sidecar); rmSync(DATA, { recursive: true, force: true }); process.exit(1);
}
const cuenta = { email: `vara-cos-${Date.now()}@example.com`, password: "vara-cosecha-2026" };
for (const ruta of ["/v1/auth/register", "/v1/auth/login"]) {
  const r = await fetch(BASE + ruta, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuenta) });
  if (!r.ok) continue;
  const j = await J(r).catch(() => null);
  if (j?.session_token) { U = j; break; }
}
console.log(`· cuenta      ${U ? U.id : "SIN SESIÓN"}\n`);

const RECIPE = {
  schema_version: "v1",
  meta: { name: "cosecha-vara", nicho: "general", output_type: "informe" },
  model: { alias: "claude_cli", primary: "claude-code-cli", base_url: BRAIN,
           temperature: 0, max_tokens: 500, max_turns: 4 },
  belt: { belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
          tool_filters: { calc: ["add"] } },
  framing: { inline: "" }, rag: { enabled: false }, keys: {}, gates: {},
};

// ── PASO 1 · LA MARCA, MUERTA ─────────────────────────────────────────────────────────
sec("PASO 1 · la marca, muerta — en el árbol Y en el bundle que viaja");
{
  // (0) LAS MARCAS SE POLICÍAN SOLAS, ANTES DE MEDIR CON ELLAS. Una marca sirve si separa
  // el stack de la casa; si además pega en `main` —que nunca tuvo el stack— lo único que
  // prueba su rojo es que la lista está mal. Este assert corre PRIMERO a propósito: sin él,
  // el rojo de una marca contaminada se lee como «la cosecha no está hecha» y manda a
  // buscar un fantasma al árbol. Es el caso `Gemma`, documentado arriba de MARCAS.
  const noDiscrimina = MARCAS.filter((t) =>
    (spawnSync("git", ["grep", "-IilF", "-e", t, "main"], { encoding: "utf8" }).stdout || "").trim().length > 0);
  if (!noDiscrimina.length)
    ok(`las ${MARCAS.length} marcas DISCRIMINAN`, "cero hits en main, que nunca tuvo el stack");
  else bad("toda marca tiene que dar cero en main", `no discriminan: ${noDiscrimina.join(", ")}`);

  // (a) el árbol trackeado — CERO, sin excepciones ni exclusiones (por eso van codificadas)
  const g = spawnSync("git", ["grep", "-rIil", "--", MARCAS[1]], { encoding: "utf8" });
  const hits = (g.stdout || "").trim().split("\n").filter(Boolean);
  if (!hits.length) ok("grep de la marca en el árbol trackeado", "cero hits, esta vara incluida");
  else bad("grep de la marca en el árbol trackeado", `${hits.length}: ${hits.slice(0, 5).join(", ")}`);

  // (b) el disco, incluyendo lo no trackeado (una carpeta olvidada no la ve `git grep`)
  const d = spawnSync("grep", ["-rIil", "--exclude-dir=.git", "--exclude-dir=node_modules",
                               "--exclude-dir=.venv", "--exclude-dir=target",
                               "--exclude-dir=__pycache__", MARCAS[1], "."],
                      { encoding: "utf8" });
  const hd = (d.stdout || "").trim().split("\n").filter(Boolean);
  if (!hd.length) ok("grep de la marca en el disco (incluye lo no trackeado)", "cero hits");
  else bad("grep de la marca en el disco", `${hd.length}: ${hd.slice(0, 5).join(", ")}`);

  // (c) `third_party/` tiene EXACTAMENTE lo que debe. Se mide así, y no «no existe la
  // carpeta X», porque lo que hay que certificar es que no quedó NINGÚN import a medio
  // cosechar — no sólo que se fue el que sabemos.
  const dentro = readdirSync("third_party").filter((n) => !n.startsWith("."));
  const sobra = dentro.filter((n) => !THIRD_PARTY_ESPERADO.includes(n));
  if (!sobra.length) ok("third_party/ tiene sólo lo declarado", dentro.join(" · "));
  else bad("third_party/ tiene sólo lo declarado", `sobra: ${sobra.join(", ")}`);
  if (!existsSync(join("third_party", CARPETA_MUERTA))) ok("la carpeta del stack no existe");
  else bad("la carpeta del stack no existe", "sigue en el disco");

  // (c) EL BUNDLE QUE VIAJA. Le preguntamos al BINARIO dónde extrajo su frontend, no al
  // TOC — la lección de `bundle_datos.py`: el TOC dice lo que se pidió empaquetar; el
  // `_MEI…` dice lo que de verdad viajó.
  const log = (sidecar._log || []).join("");
  const m = log.match(/\[serving\] frontend montado desde (\S+?)\/product\/app\/design/);
  const raiz = m ? m[1] : null;
  if (!raiz) bad("se ubica el bundle extraído del binario", "el sidecar no lo dijo en su log");
  else {
    if (!existsSync(join(raiz, "third_party", CARPETA_MUERTA)))
      ok("el stack NO viaja dentro del binario", "no está en el _MEI…");
    else bad("el stack no viaja dentro del binario", "sigue empaquetado");
    const sucias = MARCAS.filter((t) => {
      const v = spawnSync("grep", ["-rli", t, join(raiz, "product", "app", "design")], { encoding: "utf8" });
      return (v.stdout || "").trim().length > 0;
    });
    if (!sucias.length) ok("el frontend QUE VIAJA no tiene marca ajena", `${MARCAS.length} términos, cero hits`);
    else bad("el frontend que viaja no tiene marca ajena", `hits: ${sucias.join(", ")}`);
    // …y la piel del workspace: [F3-ciencia] AHORA SÍ VIAJA, y tiene que viajar. Esta
    // afirmación estaba al revés porque la escribió una cosecha que acababa de sacar el
    // único stack que había. Entró Ciencia y la piel es suya: sin `ciencia.html` adentro
    // del congelado, la sección del menú lleva a una pantalla que no existe.
    const pielWs = join(raiz, "product", "app", "design", "workspaces");
    const pielOk = existsSync(join(pielWs, "ciencia.html")) && existsSync(join(pielWs, "workspace.css"));
    if (pielOk) ok("la piel del workspace VIAJA", "ciencia.html + workspace.css en el congelado");
    else bad("la piel del workspace viaja", `falta ciencia.html o workspace.css en ${pielWs}`);
  }
}

// ── PASO 2 · EL REGISTRO CON SU INQUILINO ─────────────────────────────────────────────
// [F3-ciencia] Este paso medía «vacío y sano», que era lo correcto mientras no hubiera
// ningún stack adentro. Entró Ciencia. La intención NO cambia —la puerta tiene que
// contestar 200 con su FORMA, no romperse— pero lo que se afirma sí: ahora es «tiene
// exactamente el inquilino declarado, con su censo y su puente», que es una afirmación
// más fuerte que un vacío (un vacío es trivialmente verde; una fila hay que producirla).
sec("PASO 2 · el registro de workspaces: con su inquilino, y sano");
{
  const r = await fetch(`${BASE}/v1/workspaces`, { headers: H() });
  const j = await J(r).catch(() => null);
  const ws = (j?.workspaces || []).find((w) => w.id === "ciencia");
  if (r.status === 200 && ws && ws.stack?.installed && (ws.sources || []).length === 42)
    ok("GET /v1/workspaces trae Ciencia, instalada y con su censo", `${ws.label} · ${ws.sources.length} fuentes`);
  else bad("GET /v1/workspaces trae Ciencia con su censo", `HTTP ${r.status} · ${JSON.stringify(j).slice(0, 140)}`);

  const b = await fetch(`${BASE}/v1/workspaces/bridge`);
  const bj = await J(b).catch(() => null);
  const causas = Object.keys(bj?.causes || {});
  const kinds = Object.keys(bj?.workspaces?.ciencia?.kinds || {});
  // Y ninguna fila sin su caso MEDIDO: es la regla del puente, y se comprueba por HTTP.
  const sinCaso = Object.entries(bj?.workspaces?.ciencia?.kinds || {})
    .filter(([, f]) => !String(f?.caso || "").trim()).map(([k]) => k);
  if (b.status === 200 && kinds.length === 10 && !sinCaso.length && causas.length >= 4)
    ok("el puente sirve las 10 clases de Ciencia, cada una con su caso", `${causas.length} causas con copy`);
  else bad("el puente sirve las clases de Ciencia con su caso", `HTTP ${b.status} · kinds=${kinds.length} · sin caso: ${sinCaso.join(",") || "—"}`);
  // Cada causa tiene COPY (regla sellada: ninguna causa llega a una superficie sin copy).
  const sinCopy = Object.entries(bj?.causes || {}).filter(([, v]) => !String(v || "").trim());
  if (bj && !sinCopy.length) ok("todas las causas del puente tienen copy", causas.join(", "));
  else bad("todas las causas del puente tienen copy", `sin copy: ${sinCopy.map(([k]) => k).join(",")}`);
}

// ── PASO 3 · EL PUENTE RECHAZA CON CAUSA (el mecanismo, probado en su borde) ──────────
sec("PASO 3 · el puente sin ningún stack registrado: RECHAZA CON CAUSA Y COPY");
const SID = `vara-cos-${Date.now().toString(36)}`;
{
  const r = await fetch(`${BASE}/v1/workspaces/artifacts`, {
    method: "POST", headers: H(),
    body: JSON.stringify({ sid: SID, workspace: "fantasma", kind: "snapshot_card",
                           data: { ticker: "AAPL" }, user_id: U.id }),
  });
  const j = await J(r).catch(() => null);
  //: El puente levanta `BridgeError(code=…)` y el router la serializa como
  //: `detail.error` (router.py, `except bridge.BridgeError`) — el mismo nombre de campo que
  //: usa el resto de la casa para su causa (p. ej. `chat_not_found`). Esta vara buscaba
  //: `causa`/`code` y jamás `error`: leía en un campo que el producto no emite y daba rojo
  //: contra un rechazo IMPECABLE (traía error + detail + kind + copy).
  const causa = j?.detail?.error || j?.detail?.causa || j?.causa || j?.detail?.code || null;
  const copy = j?.detail?.copy || j?.copy || null;
  if (r.status === 422 && causa === "workspace_kind_unknown" && copy)
    ok("un artefacto de un stack no registrado se rechaza con causa Y copy", `${causa} · «${String(copy).slice(0, 60)}»`);
  else bad("el puente rechaza con causa y copy", `HTTP ${r.status} · ${JSON.stringify(j).slice(0, 200)}`);
  // Y NO deja basura: un rechazo no puede haber escrito media obra.
  const arch = join(DATA, "artifacts", `${SID}.json`);
  if (!existsSync(arch)) ok("el rechazo no escribió nada en el almacén");
  else bad("el rechazo no escribió nada", `apareció ${arch}`);
}

// ── PASO 4 · LA PUERTA AL CEREBRO (genérica) SIGUE VIVA ───────────────────────────────
sec("PASO 4 · POST /v1/workspaces/brain/complete — un paso, con schemas de función");
let SPACE = null, CHAT_WS = null, CHAT_SALA = null;
{
  // Los dos hilos del MISMO agente: el del workspace y el de La Sala (modelo de hilos 3.6).
  // Se crean acá porque el paso 6 mide que sus HISTORIALES no se mezclan.
  const c1 = await fetch(`${BASE}/v1/chats`, { method: "POST", headers: H(), body: "{}" }).then(J).catch(() => null);
  const c2 = await fetch(`${BASE}/v1/chats`, { method: "POST", headers: H(), body: "{}" }).then(J).catch(() => null);
  CHAT_WS = c1?.id || null; CHAT_SALA = c2?.id || null;
  // El nombre va ANTES del primer mensaje: `append_message` bautiza un hilo sin título con
  // el contenido del primer turno, así que renombrar después no alcanzaría (3.6).
  const pr = CHAT_WS ? await fetch(`${BASE}/v1/chats/${CHAT_WS}`, {
    method: "PATCH", headers: H(), body: JSON.stringify({ title: "Espacio de trabajo" }) }) : null;
  if (pr?.ok) ok("el hilo se bautiza ANTES del primer mensaje (3.6)", "PATCH /v1/chats/{id} 200");
  else bad("el hilo se bautiza antes del primer mensaje", `HTTP ${pr?.status ?? "?"}`);

  SPACE = `cos-${Date.now().toString(36)}`;
  const r = await fetch(`${BASE}/v1/workspaces/brain/complete`, {
    method: "POST", headers: H(),
    body: JSON.stringify({
      workspace: "fantasma", space_id: SPACE, user_id: U.id, recipe: RECIPE, turn: 1,
      chat_id: CHAT_WS,
      messages: [{ role: "user", content: "Sumá 21 más 21 usando la herramienta sumar." }],
      tools: [{ type: "function", function: {
        name: "sumar", description: "Suma dos números",
        parameters: { type: "object", properties: { a: { type: "number" }, b: { type: "number" } },
                      required: ["a", "b"] } } }],
    }),
  });
  const j = await J(r).catch(() => null);
  if (r.status === 200 && j) ok("la puerta contesta la jugada del modelo", `model=${j.model} · tool_calls=${(j.tool_calls || []).length}`);
  else bad("la puerta contesta la jugada del modelo", `HTTP ${r.status} · ${JSON.stringify(j).slice(0, 200)}`);

  // El modelo lo elige ALEPH. Lo que se rechaza son los ids DEL ENCHUFE MUERTO que la
  // cirugía de 3.2 cortó; una degradación a la red de seguridad de la casa es la cirugía
  // FUNCIONANDO y se anota, no se reprueba.
  const ENCHUFE = /:free|openai\/gpt-oss|gemini-2\.0-flash-exp|meta-llama\/llama-3\.3|qwen\/qwen3-coder/i;
  if (j?.model && !ENCHUFE.test(j.model)) ok("el modelo del turno lo eligió Aleph", j.model);
  else bad("el modelo del turno lo eligió Aleph", `model=${j?.model || "(ninguno)"}`);
  if (/qwen3:8b|ollama/i.test(j?.model || ""))
    console.log("     · nota: corrió por la red de seguridad de Aleph (OSS-directo), no por el primary");

  // `provider` y `model` NO se aceptan en el body, A PROPÓSITO: un harness que pudiera
  // pedir su proveedor seguiría enchufado, con otro cable. Se rechaza en vez de ignorar.
  const r2 = await fetch(`${BASE}/v1/workspaces/brain/complete`, {
    method: "POST", headers: H(),
    body: JSON.stringify({ workspace: "fantasma", space_id: SPACE + "-x", user_id: U.id,
                           recipe: RECIPE, turn: 1, provider: "openai", model: "gpt-4",
                           messages: [{ role: "user", content: "hola" }] }),
  });
  const j2 = await J(r2).catch(() => null);
  const cuerpo = JSON.stringify(j2 || {});
  if (r2.status >= 400 || /provider|model/i.test(String(j2?.detail?.causa || "")))
    ok("el harness NO puede pedir su proveedor (se rechaza, no se ignora)", `HTTP ${r2.status}`);
  else if (j2?.model && !/gpt-4/i.test(j2.model))
    ok("el harness no puede pedir su modelo (el body no lo gobierna)", `pidió gpt-4 · respondió ${j2.model}`);
  else bad("el harness no puede pedir su proveedor", `HTTP ${r2.status} · ${cuerpo.slice(0, 160)}`);

  // El cierre RE-DERIVA `model_final` de los `workspace_step` que el propio borde escribió.
  const rc = await fetch(`${BASE}/v1/workspaces/brain/close`, {
    method: "POST", headers: H(),
    body: JSON.stringify({ space_id: SPACE, workspace: "fantasma", user_id: U.id,
                           answer: "42", ok: true, turns: 1, chat_id: CHAT_WS,
                           prompt: "Sumá 21 más 21 usando la herramienta sumar." }),
  });
  const jc = await J(rc).catch(() => null);
  if (rc.status === 200 && jc?.model_final) ok("el cierre RE-DERIVA model_final (no lo declara el harness)", `${jc.model_final} · ok=${jc.ok}`);
  else bad("el cierre re-deriva model_final", `HTTP ${rc.status} · ${JSON.stringify(jc).slice(0, 160)}`);
}

// ── PASO 5 · LA HONESTIDAD DE 3.4 ─────────────────────────────────────────────────────
sec("PASO 5 · la honestidad de 3.4: workspace_step ≠ tool_call_finished · declared ≠ exact");
const EVENTS = join(DATA, "espacios", SPACE || "", "events.jsonl");
{
  const lineas = existsSync(EVENTS) ? readFileSync(EVENTS, "utf8").trim().split("\n").map((l) => { try { return JSON.parse(l); } catch (_) { return {}; } }) : [];
  const tipos = lineas.map((e) => e.type);
  if (tipos.includes("workspace_step")) ok("el paso del harness quedó como workspace_step", `${tipos.filter((t) => t === "workspace_step").length} ×`);
  else bad("el paso del harness quedó como workspace_step", `tipos=${[...new Set(tipos)].join(",") || "(espacio vacío)"}`);
  // LA DECISIÓN CENTRAL: Aleph NO escribe el hecho que otro proceso declara.
  if (!tipos.includes("tool_call_finished")) ok("Aleph NO fabricó tool_call_finished por lo que el harness declaró");
  else bad("Aleph no fabricó tool_call_finished", "apareció uno que Aleph no ejecutó");
  const cerrado = lineas.find((e) => e.type === "closed");
  if (cerrado?.model_final) ok("el espacio cerró con model_final en el registro firmado", cerrado.model_final);
  else bad("el espacio cerró con model_final", JSON.stringify(cerrado || null).slice(0, 120));
}

// El borde TOPA la calidad: se pide `exact` y sale `declared`. Se mide pidiendo lo
// prohibido — si sólo mandáramos `declared`, el verde no probaría que el tope existe.
let AID = null;
{
  const r = await fetch(`${BASE}/v1/sessions/${SID}/artifacts`, {
    method: "POST", headers: H(),
    body: JSON.stringify({ title: "Informe del turno", type: "informe",
                           content: JSON.stringify({ type: "informe", content: "## Turno\n\n21 + 21 = 42\n" }),
                           user_id: U.id, produced_by: "workspace", workspace: "fantasma",
                           space_id: SPACE, chat_id: CHAT_WS, capture_quality: "exact",
                           intent: "informe del turno" }),
  });
  const j = await J(r).catch(() => null);
  const p = j?.artifact?.provenance || {};
  AID = j?.artifact?.id || null;
  if (r.status === 201 && p.produced_by === "workspace" && p.capture_quality === "declared")
    ok("se pidió `exact` y el borde lo topó en `declared`", `produced_by=${p.produced_by} · quality=${p.capture_quality}`);
  else bad("el borde topa la calidad del workspace", `HTTP ${r.status} · produced_by=${p.produced_by} · quality=${p.capture_quality}`);
  if (p.model_final) ok("el modelo del turno viaja adentro del artefacto", p.model_final);
  else bad("el modelo del turno viaja en el artefacto", "model_final null");
}

// ── PASO 5.bis · S8, PROBADA CAYENDO ──────────────────────────────────────────────────
sec("PASO 5.bis · S8 probada CAYENDO (un `exact` que el borde no pudo producir)");
const ARTFILE = join(DATA, "artifacts", `${SID}.json`);
{
  const v = spawnSync(PYBIN, ["qa/anti-fake-suite/check_provenance.py", EVENTS, "--artifact", ARTFILE],
    { cwd: process.cwd(), encoding: "utf8" });
  const s8 = (v.stdout || "") + (v.stderr || "");
  if (/AUT[ÉE]NTICO/i.test(s8) && v.status === 0) ok("anti-grift sobre lo real: AUTÉNTICO", `exit=${v.status}`);
  else bad("anti-grift sobre lo real", `exit=${v.status} · ${s8.split("\n").filter((l) => /S8|SOSPECHOSO/.test(l)).join(" | ").slice(0, 240)}`);

  if (!existsSync(ARTFILE)) bad("hay archivo de artefactos para falsificar", ARTFILE);
  else {
    const orig = readFileSync(ARTFILE, "utf8");
    const j = JSON.parse(orig);
    const a = (j.artifacts || []).find((x) => x.provenance?.produced_by === "workspace");
    if (!a) bad("hay un artefacto de workspace para falsificar", "ninguno");
    else {
      a.provenance.capture_quality = "exact";     // la falsificación exacta que 3.4 hizo detectable
      writeFileSync(ARTFILE, JSON.stringify(j));
      const v2 = spawnSync(PYBIN, ["qa/anti-fake-suite/check_provenance.py", EVENTS, "--artifact", ARTFILE],
        { cwd: process.cwd(), encoding: "utf8" });
      const s = (v2.stdout || "") + (v2.stderr || "");
      if (v2.status !== 0 && /SOSPECHOSO/.test(s) && /workspace/i.test(s))
        ok("S8 detecta el `exact` falsificado y NOMBRA el workspace", `exit=${v2.status}`);
      else bad("S8 detecta el `exact` falsificado", `exit=${v2.status} · ${s.slice(-260)}`);
      writeFileSync(ARTFILE, orig);                // se restaura: la vara no deja basura
    }
  }
}

// ── PASO 6 · EL MODELO DE HILOS (3.6) ─────────────────────────────────────────────────
sec("PASO 6 · el modelo de hilos: una identidad, DOS historiales");
{
  //: `GET /v1/chats/{id}/messages` NO EXISTE. El historial viene DENTRO del chat, por
  //: `GET /v1/chats/{id}` («el chat + sus mensajes», chats_router). Esta vara pegaba en la
  //: ruta inventada, comía el 404 y `.length` sobre el cuerpo de error daba `undefined` —
  //: por eso el rojo decía `workspace=undefined · sala=undefined` y no `0`. Un `undefined`
  //: donde se esperaba un número es la firma de que se midió OTRA COSA, no de que falle.
  const l1 = CHAT_WS ? await fetch(`${BASE}/v1/chats/${CHAT_WS}`, { headers: H() }).then(J).catch(() => null) : null;
  const l2 = CHAT_SALA ? await fetch(`${BASE}/v1/chats/${CHAT_SALA}`, { headers: H() }).then(J).catch(() => null) : null;
  const n1 = (l1?.messages || []).length;
  const n2 = (l2?.messages || []).length;
  if (n1 > 0 && n2 === 0) ok("el turno quedó en SU hilo y el otro sigue vacío", `workspace=${n1} mensajes · sala=${n2}`);
  else bad("los historiales no se comparten", `workspace=${n1} · sala=${n2}`);
  const hilos = await fetch(`${BASE}/v1/chats`, { headers: H() }).then(J).catch(() => null);
  const lista = hilos?.chats || hilos || [];
  const elNuestro = lista.find((c) => c.id === CHAT_WS);
  if (elNuestro && /Espacio de trabajo/i.test(elNuestro.title || ""))
    ok("el hilo conserva el nombre que le pusimos (no lo pisó el primer turno)", elNuestro.title);
  else bad("el hilo conserva su nombre", `title=${elNuestro?.title ?? "(no está)"}`);
}

// ── PASO 7 · LA SALA MODERNA, EL CANVAS Y EL MENÚ ─────────────────────────────────────
sec("PASO 7 · la Sala moderna: canvas con la obra · menú SIN sección Workspaces");
{
  const browser = await webkit.launch();
  const page = await browser.newPage({ viewport: { width: 1480, height: 940 } });
  const errores = [];
  const consola = [];
  page.on("pageerror", (e) => errores.push(String(e).slice(0, 160)));
  page.on("console", (m) => { if (m.type() === "error") consola.push(m.text().slice(0, 140)); });
  await page.addInitScript((u) => {
    try { localStorage.setItem("puppet_user", JSON.stringify(u)); sessionStorage.setItem("puppet_user", JSON.stringify(u)); } catch (_) {}
  }, U);
  await page.addInitScript((sid) => { try { localStorage.setItem("puppet_sala_sid_general", sid); } catch (_) {} }, SID);

  await page.goto(`${BASE}/sala-v2/sala-v2.html?v2=1`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3500);

  const v = await page.evaluate(() => {
    const px = (el) => !!el && getComputedStyle(el).display !== "none" && el.getBoundingClientRect().height > 0;
    const lib = document.querySelector('[data-testid="sv-biblioteca"]');
    const r = lib ? lib.getBoundingClientRect() : null;
    return {
      monto: !!document.querySelector(".sv-spine") && !!document.querySelector(".sv-main") && !!document.querySelector(".sv-composer"),
      canvas: !!document.querySelector('[data-testid="sv-canvas"]'),
      titulo: (document.querySelector(".sv-canvas-tit") || {}).textContent || null,
      tipo: (document.querySelector(".sv-canvas-tipo") || {}).textContent || null,
      prov: (document.querySelector(".sv-canvas-prov") || {}).textContent || null,
      dibujo: ((document.querySelector(".sv-canvas-host") || {}).textContent || "").trim().slice(0, 60),
      items: document.querySelectorAll(".sv-lib-item").length,
      libEnPantalla: !!(r && r.top < window.innerHeight && r.bottom > 0 && r.height > 0),
      libTop: r ? Math.round(r.top) : null,
      alto: window.innerHeight,
      cols: getComputedStyle(document.getElementById("sv-root")).gridTemplateColumns,
      // el menú, entero: los rótulos de sección y los destinos
      secciones: [...document.querySelectorAll(".sv-spine .sv-sect")].map((e) => e.textContent.trim()),
      destinos: [...document.querySelectorAll(".sv-spine .sv-link")].map((a) => a.textContent.trim()),
      hrefsWs: [...document.querySelectorAll(".sv-spine a[href*='workspace']")].length,
      vaciaWs: px(document.querySelector(".sv-ws-vacia")),
    };
  });

  // (a) la Sala moderna montó — el ancla que hace no-trivial todo lo que sigue
  if (v.monto) ok("la Sala moderna monta (menú · hilo · composer)", `columnas: ${v.cols}`);
  else bad("la Sala moderna monta", JSON.stringify(v).slice(0, 200));

  // (b) el canvas con la obra REAL del turno
  if (v.canvas && v.dibujo) ok("el CANVAS muestra la obra del turno", `${v.titulo} · ${v.tipo} · «${v.dibujo}»`);
  else bad("el canvas muestra la obra del turno", `canvas=${v.canvas} · dibujo=«${v.dibujo}»`);
  if ((v.prov || "").trim()) ok("el canvas dice la PROCEDENCIA de la obra", v.prov.trim());
  else bad("el canvas dice la procedencia", `prov=${v.prov}`);
  if (v.items >= 1) ok("la Biblioteca lista la obra", `${v.items} fila(s)`);
  else bad("la Biblioteca lista la obra", `${v.items} filas`);
  if (v.libEnPantalla) ok("…y la Biblioteca está DENTRO de la pantalla", `top=${v.libTop}px de ${v.alto}px`);
  else bad("la Biblioteca está dentro de la pantalla", `top=${v.libTop}px de ${v.alto}px — se cayó abajo`);

  // (c) EL MENÚ CON SU SECCIÓN WORKSPACES — [F3-ciencia] la afirmación se dio vuelta con
  // el registro: con un elegible, la sección EXISTE y tiene su fila. Lo que sigue valiendo
  // igual es que no se pinte un ESTADO VACÍO explicando la categoría: eso es catálogo, y
  // la ley de producto 6 lo prohíbe con o sin inquilino.
  const hayRotulo = v.secciones.some((s) => /workspace/i.test(s));
  if (hayRotulo && v.hrefsWs >= 1 && !v.vaciaWs)
    ok("un elegible ⇒ la sección Workspaces EXISTE, con su fila y sin estado vacío", `filas=${v.hrefsWs}`);
  else bad("la sección Workspaces existe con su fila", `rótulo=${hayRotulo} · filas=${v.hrefsWs} · vacía pintada=${v.vaciaWs}`);
  // …y el resto del menú SÍ está: si no, «no hay sección» sería cierto porque no hay menú.
  if (v.destinos.length >= 3) ok("el resto del menú está entero (el vacío no es un menú roto)", v.destinos.join(" · "));
  else bad("el resto del menú está entero", `destinos=${v.destinos.join(" · ")}`);

  await page.screenshot({ path: join(SHOTS, "1-sala-canvas.png") });

  // (d) cambiar de obra desmonta y monta — CON PUNTERO REAL (lección de la obra E)
  {
    const r2 = await fetch(`${BASE}/v1/sessions/${SID}/artifacts`, {
      method: "POST", headers: H(),
      body: JSON.stringify({ title: "Segunda obra", type: "informe",
                             content: JSON.stringify({ type: "informe", content: "## Otra\n\nsegunda\n" }),
                             user_id: U.id, produced_by: "manual" }),
    });
    if (r2.status === 201) {
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3000);
      const antes = await page.evaluate(() => (document.querySelector(".sv-canvas-tit") || {}).textContent);
      const otra = page.locator('.sv-lib-item:not([aria-current="true"])').first();
      if (await otra.count()) {
        await otra.scrollIntoViewIfNeeded();
        await otra.click();
        await page.waitForTimeout(1500);
        const desp = await page.evaluate(() => (document.querySelector(".sv-canvas-tit") || {}).textContent);
        if (desp && desp !== antes) ok("cambiar de obra en la Biblioteca desmonta y monta", `${antes} → ${desp}`);
        else bad("cambiar de obra", `antes=${antes} después=${desp}`);
      } else bad("hay otra obra para cambiar", "la Biblioteca tiene una sola");
    } else bad("se pudo crear la segunda obra", `HTTP ${r2.status}`);
  }

  // (e) la consola limpia — un vacío con errores no es un estado limpio
  if (!errores.length) ok("cero pageerror en la Sala"); else bad("cero pageerror", errores.join(" | ").slice(0, 200));
  const ruido = consola.filter((t) => !/favicon/i.test(t));
  if (!ruido.length) ok("cero errores de consola en la Sala"); else bad("cero errores de consola", ruido.slice(0, 3).join(" | "));

  // (f) LA PIEL MUERTA NO SE SIRVE — y lo dice con un 404, no con una pantalla a medias
  const resp = await page.goto(`${BASE}/workspaces/finanzas.html`, { waitUntil: "domcontentloaded" }).catch(() => null);
  const st = resp?.status() ?? 0;
  const hayFrame = await page.evaluate(() => !!document.getElementById("ws-frame"));
  if (st >= 400 && !hayFrame) ok("la piel del workspace ya no se sirve", `HTTP ${st}`);
  else bad("la piel del workspace ya no se sirve", `HTTP ${st} · #ws-frame=${hayFrame}`);

  await page.screenshot({ path: join(SHOTS, "2-piel-muerta.png") });
  await browser.close();
}

// ── PASO 8 · MATAR Y REABRIR ──────────────────────────────────────────────────────────
sec("PASO 8 · matar la app y reabrir: la obra sobrevive");
{
  matarSidecar(sidecar);
  await new Promise((r) => setTimeout(r, 1500));
  sidecar = arrancarSidecar();
  if (!(await esperar(`${BASE}/health`))) bad("el binario reabre", "no levantó tras el kill");
  else {
    const b2 = await webkit.launch();
    const p2 = await b2.newPage({ viewport: { width: 1480, height: 940 } });
    const err2 = [];
    p2.on("pageerror", (e) => err2.push(String(e).slice(0, 160)));
    await p2.addInitScript((u) => { try { localStorage.setItem("puppet_user", JSON.stringify(u)); } catch (_) {} }, U);
    await p2.addInitScript((sid) => { try { localStorage.setItem("puppet_sala_sid_general", sid); } catch (_) {} }, SID);
    await p2.goto(`${BASE}/sala-v2/sala-v2.html?v2=1`, { waitUntil: "domcontentloaded" });
    await p2.waitForTimeout(3500);
    const tras = await p2.evaluate(() => ({
      items: document.querySelectorAll(".sv-lib-item").length,
      titulo: (document.querySelector(".sv-canvas-tit") || {}).textContent || null,
      dibujo: ((document.querySelector(".sv-canvas-host") || {}).textContent || "").trim().length,
      secciones: [...document.querySelectorAll(".sv-spine .sv-sect")].map((e) => e.textContent.trim()),
    }));
    if (tras.items >= 2 && tras.dibujo > 0) ok("tras MATAR la app y reabrir: la Biblioteca y la obra siguen", `${tras.items} filas · «${tras.titulo}»`);
    else bad("tras matar la app y reabrir", JSON.stringify(tras));
    if (tras.secciones.some((s) => /workspace/i.test(s))) ok("tras reabrir, la sección Workspaces sigue ahí");
    else bad("tras reabrir la sección Workspaces sigue ahí", tras.secciones.join(" · "));
    await p2.screenshot({ path: join(SHOTS, "3-tras-reabrir.png") });
    if (!err2.length) ok("cero pageerror tras reabrir"); else bad("cero pageerror tras reabrir", err2.join(" | ").slice(0, 200));
    await b2.close();
  }
}

// ── cierre ────────────────────────────────────────────────────────────────────────────
cerrar(null);
