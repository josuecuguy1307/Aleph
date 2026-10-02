/* verify_multiagente_f1.mjs — LA VARA DEL MULTIAGENTE F1 (CADENA), contra el FROZEN propio.
 *
 * Spec: docs/multiagente.md. CERO UI: todo por API. El visual es fase 2.
 *
 *   §1 EL PLAN            — 3 alephs en cadena: el orden, los cables efectivos y el NÚCLEO
 *                           DERIVADO (primero ✓ · medio ✗ · último ✓). Sin correr nada.
 *   §2 LA CADENA CORRE    — run REAL: el pedido entra por el primero, cada eslabón entrega y
 *                           suelta, el último ENTREGA. 3 saltos con su LATENCIA MEDIDA.
 *   §3 EL ENLACE POR CAMPO— la DB releída: el padre con `modo`, los 3 saltos con
 *                           parent_run_id/hop_index/hop_latency_ms, EN ORDEN.
 *   §4 ENTREGAR-Y-SUELTA  — la CALIBRACIÓN del verde de §2: el `intent` de cada salto es la
 *                           RESPUESTA del anterior. Si la cadena fuera teatro (cada eslabón
 *                           recibiendo el pedido original), esto sería rojo.
 *   §5 CALIBRACIONES EN ROJO — bucle · bifurcación · el mismo aleph dos veces · cable
 *                           `delegar` · clave de más en el cable · los 3 modos que no corren
 *                           · profundidad excesiva · ciclo de alephs. Todos con CAUSA.
 *   §6 UN ESLABÓN ROTO CORTA — el del medio falla ⇒ la cadena para y el ÚLTIMO NUNCA corre.
 *   §7 CERO REGRESIÓN     — una receta SIN `modo` valida y corre exactamente como antes.
 *   §8 MIGRACIÓN LOS DOS DIALECTOS — delega en platform/db/verify_multiagente_saltos.py.
 *   §9 VERIFIES EXISTENTES DEL MOTOR — verdes.
 *
 * Contra el binario FROZEN de ESTE árbol, datadir aislado, puerto 8310.
 * JAMÁS 25374 (ése es el de la .app de persona usuaria).
 *
 *   node qa/verify_multiagente_f1.mjs
 *   ALEPH_MA_PORT=8310 ALEPH_SIDECAR_BIN=<binario> node qa/verify_multiagente_f1.mjs
 */
import { spawnSync } from "node:child_process";
// GUARD _MEI: TMPDIR privado por sidecar + barrido en TODA salida (el bootloader onefile
// deja ~170 MB en `_MEI*` si el proceso no cierra limpio). Ver qa/lib/frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "./lib/frozen_guard.mjs";
import net from "node:net";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";

const ROOT = new URL("..", import.meta.url).pathname;
const PORT = Number(process.env.ALEPH_MA_PORT || 8310);
if (PORT === 25374) { console.error("✗ 25374 es el puerto de la .app de persona usuaria — usá otro"); process.exit(2); }
const BASE = `http://127.0.0.1:${PORT}`;
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  path.join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
const DATADIR = fs.mkdtempSync(path.join(os.tmpdir(), "aleph-ma-f1-"));
const PY = path.join(ROOT, "product/backend/.venv/bin/python");

const A = "catalog/agents/ma-f1-extractor.config.json";
const B = "catalog/agents/ma-f1-calculo.config.json";
const C = "catalog/agents/ma-f1-informe.config.json";
const ROTO = "catalog/agents/ma-f1-roto.config.json";
const PEDIDO = "Compramos 3 sensores, 10 resistencias y 7 capacitores. ¿Cuántas piezas en total?";

let PASS = 0, FAIL = 0; const FALLADAS = [];
function ok(cond, nombre, detalle = "") {
  if (cond) { PASS++; console.log(`  PASS  ${nombre}`); }
  else { FAIL++; FALLADAS.push(nombre); console.log(`  FAIL  ${nombre}${detalle ? " — " + detalle : ""}`); }
  return !!cond;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── receta del globo: cero entidades nuevas, sólo `modo` + agent_refs (+ cables) ────
function globo(refs, { modo = "cadena", cables = null } = {}) {
  const belt = { agent_refs: refs, tool_filters: {} };
  if (cables) belt.agent_links = cables;
  const r = {
    schema_version: "v1",
    meta: { name: "F1 · Globo", nicho: "general", descripcion: "cadena de alephs" },
    model: { primary: "openai/gpt-oss-120b", base_url: "https://api.groq.com/openai/v1",
             temperature: 0, max_tokens: 256, max_turns: 3 },
    belt, rag: { enabled: false },
  };
  if (modo !== null) r.modo = modo;
  return r;
}

let TOKEN = null;
async function api(metodo, ruta, cuerpo) {
  const res = await fetch(BASE + ruta, {
    method: metodo,
    headers: { "content-type": "application/json",
               ...(TOKEN ? { authorization: `Bearer ${TOKEN}` } : {}) },
    body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
  });
  let json = null;
  try { json = await res.json(); } catch { json = null; }
  return { status: res.status, json };
}
/** La causa de un rechazo, venga del MOTOR (`detail.causa`) o del VALIDADOR
 *  (`detail.errors[i]` con prefijo `[causa]`) — los dos rechazan con el mismo código. */
function causaDe(r) {
  const d = r.json?.detail;
  if (!d) return null;
  if (d.causa) return d.causa;
  const e = (d.errors || [])[0] || "";
  const m = /^\[([a-z_]+)\]/.exec(e);
  return m ? m[1] : e.slice(0, 60);
}

function waitReady(ms) {
  const t0 = Date.now();
  return new Promise((res) => {
    (function tick() {
      const s = net.connect(PORT, "127.0.0.1");
      s.on("connect", () => { s.destroy(); res(true); });
      s.on("error", () => { s.destroy(); if (Date.now() - t0 > ms) return res(false); setTimeout(tick, 250); });
    })();
  });
}
function puertoOcupado() {
  return new Promise((res) => {
    const s = net.connect(PORT, "127.0.0.1");
    s.on("connect", () => { s.destroy(); res(true); });
    s.on("error", () => { s.destroy(); res(false); });
  });
}

/** La bearer key de cognición sale de infra/.env. El frozen NO la lleva adentro (y no
 *  debe): se la pasamos por env, que es la 1ª fuente de `_resolve_cognition_key`. Sin
 *  esto los saltos fallarían por falta de key y el rojo diría cualquier otra cosa. */
function claveCognicion() {
  const env = path.join(ROOT, "infra/.env");
  if (!fs.existsSync(env)) return "";
  for (const ln of fs.readFileSync(env, "utf8").split("\n")) {
    const m = /^\s*(LITELLM_KEY|GROQ_API_KEY)\s*=\s*(.+?)\s*$/.exec(ln);
    if (m) return m[2].replace(/^["']|["']$/g, "");
  }
  return "";
}

function correrPy(rel, args = [], env = {}) {
  const r = spawnSync(PY, [path.join(ROOT, rel), ...args],
    { cwd: ROOT, encoding: "utf8", env: { ...process.env, ...env }, maxBuffer: 32 * 1024 * 1024 });
  return { code: r.status, out: (r.stdout || "") + (r.stderr || "") };
}

async function main() {
  if (!fs.existsSync(SIDECAR)) {
    console.error(`✗ no existe el sidecar frozen: ${SIDECAR}\n` +
      `  construílo:  ALEPH_SIDECAR_ONEFILE=1 ALEPH_BUILD=public \\\n` +
      `    python3 qa/lib/con_lock.py /tmp/aleph-frozen.lock -- \\\n` +
      `    product/backend/.venv/bin/pyinstaller --clean --noconfirm \\\n` +
      `    --distpath <dist> --workpath <work> deploy/fase4/aleph_sidecar.spec`);
    process.exit(2);
  }
  if (await puertoOcupado()) {
    console.error(`✗ :${PORT} ocupado — esta vara mide SU frozen o no mide nada`);
    process.exit(2);
  }

  console.log(`\n═══ MULTIAGENTE F1 · CADENA — frozen :${PORT} ═══`);
  console.log(`  sidecar : ${SIDECAR}`);
  console.log(`  datadir : ${DATADIR}\n`);

  const proc = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ALEPH_DATA_DIR: DATADIR, ALEPH_ROLE: "client",
           ALEPH_BUILD: "public", LITELLM_KEY: claveCognicion() },
  });
  let log = "";
  proc.stdout?.on("data", (d) => { log += d; });
  proc.stderr?.on("data", (d) => { log += d; });

  try {
    if (!ok(await waitReady(180000), "§0 el frozen levanta", log.slice(-500))) return;

    // sesión LOCAL (el camino del cliente: /v1/auth/local mintea sin sesión previa)
    const sesion = await api("POST", "/v1/auth/local", {});
    TOKEN = sesion.json?.session_token || null;
    const USER = sesion.json?.id || null;
    if (!ok(!!TOKEN, "§0 sesión local minteada")) return;

    // ── §1 · EL PLAN ────────────────────────────────────────────────────────────
    console.log("\n§1 · EL PLAN — orden, cables y el NÚCLEO DERIVADO");
    const p = await api("POST", "/v1/multiagente/plan", { recipe: globo([A, B, C]) });
    ok(p.status === 200, "§1.1 el plan de 3 alephs se acepta", JSON.stringify(p.json).slice(0, 200));
    const plan = p.json?.plan || {};
    const eslabones = plan.eslabones || [];
    ok(plan.modo === "cadena", "§1.2 modo = cadena");
    ok(eslabones.length === 3, `§1.3 la cadena tiene 3 eslabones (${eslabones.length})`);
    ok(JSON.stringify(eslabones.map((e) => e.slug)) ===
       JSON.stringify(["ma-f1-extractor", "ma-f1-calculo", "ma-f1-informe"]),
       "§1.4 el orden es el de declaración (sin cables ⇒ derivados)");
    ok(JSON.stringify(eslabones.map((e) => e.nucleo)) === JSON.stringify([true, false, true]),
       "§1.5 NÚCLEO DERIVADO: primero ✓ · el del MEDIO ✗ · último ✓",
       JSON.stringify(eslabones.map((e) => e.nucleo)));
    ok(JSON.stringify(eslabones.map((e) => e.entrega)) === JSON.stringify([false, false, true]),
       "§1.6 sólo el ÚLTIMO entrega");
    ok(plan.cables_derivados === true && (plan.cables || []).length === 2 &&
       (plan.cables || []).every((c) => c.tipo === "entregar"),
       "§1.7 los cables efectivos se reportan (2, todos `entregar`)");
    ok((p.json?.piezas_aleph || []).length === 3 &&
       (p.json?.piezas_aleph || []).every((x) => x.type === "aleph"),
       "§1.8 la PROYECCIÓN da 3 piezas tipo `aleph` (lo que la fase 2 va a dibujar)");

    // cables DECLARADOS mandan sobre el orden de declaración
    const pc = await api("POST", "/v1/multiagente/plan", {
      recipe: globo([A, B, C], { cables: [
        { from: "ma-f1-informe", to: "ma-f1-extractor", tipo: "entregar" },
        { from: "ma-f1-extractor", to: "ma-f1-calculo", tipo: "entregar" }] }),
    });
    ok(pc.status === 200 && JSON.stringify((pc.json?.plan?.eslabones || []).map((e) => e.slug)) ===
       JSON.stringify(["ma-f1-informe", "ma-f1-extractor", "ma-f1-calculo"]),
       "§1.9 los cables DECLARADOS mandan sobre el orden de declaración");

    // ── §2 · LA CADENA CORRE ────────────────────────────────────────────────────
    console.log("\n§2 · LA CADENA CORRE — 3 saltos reales con LATENCIA MEDIDA");
    const t0 = Date.now();
    const r = await api("POST", "/v1/multiagente/run",
      { recipe: globo([A, B, C]), prompt: PEDIDO, user_id: USER, deadline_s: 300 });
    const wall = Date.now() - t0;
    ok(r.status === 201, "§2.1 el run responde 201", JSON.stringify(r.json).slice(0, 300));
    const run = r.json || {};
    const saltos = run.saltos || [];
    ok(run.ok === true, "§2.2 la cadena completa OK", JSON.stringify(run.error || {}).slice(0, 200));
    ok(saltos.length === 3, `§2.3 se registran los 3 saltos (${saltos.length})`);
    ok(saltos.every((s) => !!s.run_id), "§2.4 CADA salto tiene su propio run_id (run NORMAL)");
    ok(new Set(saltos.map((s) => s.run_id)).size === saltos.length,
       "§2.5 los run_id de los saltos son distintos entre sí");
    ok(saltos.every((s) => Number.isInteger(s.latencia_ms) && s.latencia_ms > 0),
       "§2.6 LATENCIA POR SALTO medida (> 0 ms)", JSON.stringify(saltos.map((s) => s.latencia_ms)));
    ok(Number.isInteger(run.latencia_total_ms) && run.latencia_total_ms > 0,
       "§2.7 la latencia TOTAL de la cadena está sellada");
    ok(JSON.stringify(saltos.map((s) => s.nucleo)) === JSON.stringify([true, false, true]),
       "§2.8 el núcleo derivado viaja en el transcript del run");
    // 3 + 10 + 7 = 20 — que el total llegue prueba que el dato ATRAVESÓ los tres eslabones
    ok(/20/.test(run.respuesta || ""), "§2.9 la respuesta ENTREGADA trae el total real (20)",
       JSON.stringify(run.respuesta || "").slice(0, 160));
    console.log(`        · latencias por salto: ${saltos.map((s) => s.latencia_ms + "ms").join(" · ")}` +
                `  → total ${run.latencia_total_ms}ms (wall ${wall}ms)`);
    console.log(`        · respuesta: ${JSON.stringify(run.respuesta)}`);

    // ── §3 · EL ENLACE POR CAMPO, releído de la DB ──────────────────────────────
    console.log("\n§3 · EL ENLACE POR CAMPO — la DB releída");
    const t = await api("GET", `/v1/multiagente/runs/${run.run_id}`);
    ok(t.status === 200, "§3.1 el transcript del padre se lee de la DB");
    const padre = t.json || {};
    ok(padre.modo === "cadena", "§3.2 el PADRE lleva `modo` (lo hace identificable)");
    const dbSaltos = padre.saltos || [];
    ok(dbSaltos.length === 3, `§3.3 la DB tiene los 3 saltos enlazados (${dbSaltos.length})`);
    ok(JSON.stringify(dbSaltos.map((s) => s.hop_index)) === JSON.stringify([0, 1, 2]),
       "§3.4 hop_index 0·1·2 EN ORDEN");
    ok(dbSaltos.every((s) => Number.isInteger(s.hop_latency_ms) && s.hop_latency_ms > 0),
       "§3.5 hop_latency_ms persistido por salto",
       JSON.stringify(dbSaltos.map((s) => s.hop_latency_ms)));
    ok(dbSaltos.every((s) => s.status === "done"),
       "§3.6 cada salto cerró por el ciclo de vida de SIEMPRE (status done)");
    ok(JSON.stringify(dbSaltos.map((s) => s.id)) === JSON.stringify(saltos.map((s) => s.run_id)),
       "§3.7 los run_id de la DB son los del transcript (misma verdad, dos lecturas)");

    // ── §4 · ENTREGAR-Y-SUELTA (la calibración del verde de §2) ─────────────────
    console.log("\n§4 · ENTREGAR-Y-SUELTA — el intent de cada salto ES la salida del anterior");
    ok(dbSaltos[0]?.intent === PEDIDO, "§4.1 el pedido entra por el PRIMERO, verbatim");
    ok(dbSaltos[1]?.intent && dbSaltos[1].intent !== PEDIDO,
       "§4.2 el 2º salto NO recibe el pedido original (si lo recibiera, la cadena sería teatro)",
       JSON.stringify(dbSaltos[1]?.intent || "").slice(0, 120));
    ok(/^[\d,\s]+$/.test(dbSaltos[1]?.intent || "x"),
       "§4.3 el 2º salto recibe lo que ENTREGÓ el 1º (los números extraídos)",
       JSON.stringify(dbSaltos[1]?.intent || "").slice(0, 120));
    ok(/20/.test(dbSaltos[2]?.intent || ""),
       "§4.4 el 3º salto recibe lo que ENTREGÓ el 2º (el total computado)",
       JSON.stringify(dbSaltos[2]?.intent || "").slice(0, 120));
    console.log(`        · el relevo: ${dbSaltos.map((s) => JSON.stringify((s.intent || "").slice(0, 34))).join("  →  ")}`);

    // ── §5 · CALIBRACIONES EN ROJO ──────────────────────────────────────────────
    console.log("\n§5 · CALIBRACIONES EN ROJO — cada rechazo con su CAUSA");
    const rojos = [
      ["§5.1 bucle plantado", globo([A, B], { cables: [
        { from: "ma-f1-extractor", to: "ma-f1-calculo", tipo: "entregar" },
        { from: "ma-f1-calculo", to: "ma-f1-extractor", tipo: "entregar" }] }), "cadena_ciclo"],
      ["§5.2 bifurcación", globo([A, B, C], { cables: [
        { from: "ma-f1-extractor", to: "ma-f1-calculo", tipo: "entregar" },
        { from: "ma-f1-extractor", to: "ma-f1-informe", tipo: "entregar" }] }), "cadena_bifurcacion"],
      ["§5.3 el MISMO aleph dos veces", globo([A, B, A]), "cadena_aleph_repetido"],
      ["§5.4 cable `delegar` dentro de una cadena", globo([A, B], { cables: [
        { from: "ma-f1-extractor", to: "ma-f1-calculo", tipo: "delegar" }] }), "cadena_tipo_invalido"],
      ["§5.5 clave de más en el cable (el cierre es PORTANTE)", globo([A, B], { cables: [
        { from: "ma-f1-extractor", to: "ma-f1-calculo", tipo: "entregar", nucleo: false }] }),
        "cable_clave_no_permitida"],
      ["§5.6 modo «oficina»", globo([A, B], { modo: "oficina" }), "modo_no_implementado"],
      ["§5.7 modo «orquesta»", globo([A, B], { modo: "orquesta" }), "modo_no_implementado"],
      ["§5.8 modo «abanico»", globo([A, B], { modo: "abanico" }), "modo_no_implementado"],
      ["§5.9 modo fuera del enum", globo([A, B], { modo: "turbo" }), "modo_invalido"],
      ["§5.10 PROFUNDIDAD excesiva (guard fractal)",
        globo(["catalog/agents/ma-f1-nido1.config.json"]), "multiagente_profundidad"],
      ["§5.11 CICLO de alephs (un globo no se contiene a sí mismo)",
        globo(["catalog/agents/ma-f1-ciclo-a.config.json"]), "multiagente_ciclo_de_alephs"],
    ];
    for (const [nombre, receta, causaEsperada] of rojos) {
      const res = await api("POST", "/v1/multiagente/plan", { recipe: receta });
      const causa = causaDe(res);
      ok(res.status === 422 && causa === causaEsperada,
         `${nombre} → ${causaEsperada}`, `HTTP ${res.status} causa=${causa}`);
    }
    // el rechazo del modo no implementado tiene que ser LEGIBLE, no un código pelado
    // (el rechazo puede venir del VALIDADOR o del MOTOR — los dos dicen la misma frase,
    //  que es justamente el punto de que la implementación sea una sola)
    const ofi = await api("POST", "/v1/multiagente/plan", { recipe: globo([A, B], { modo: "oficina" }) });
    ok(/todavía no corre/.test(JSON.stringify(ofi.json?.detail || {})),
       "§5.12 «oficina» lo dice con todas las letras: «todavía no corre»",
       JSON.stringify(ofi.json?.detail || {}).slice(0, 160));
    // y el modo no implementado tampoco CORRE (no sólo no planifica)
    const ofiRun = await api("POST", "/v1/multiagente/run",
      { recipe: globo([A, B], { modo: "oficina" }), prompt: "hola", user_id: USER });
    ok(ofiRun.status === 422 && causaDe(ofiRun) === "modo_no_implementado",
       "§5.13 «oficina» tampoco CORRE (el rechazo está en el path del run, no sólo en el plan)");

    // ── §6 · UN ESLABÓN ROTO CORTA LA CADENA ────────────────────────────────────
    console.log("\n§6 · UN ESLABÓN ROTO CORTA — el siguiente NUNCA corre");
    const rr = await api("POST", "/v1/multiagente/run",
      { recipe: globo([A, ROTO, C]), prompt: PEDIDO, user_id: USER, deadline_s: 300 });
    const rota = rr.json || {};
    ok(rota.ok === false, "§6.1 la cadena reporta FALLO (no un verde falso)");
    ok(rota.error?.causa === "cadena_eslabon_fallido",
       "§6.2 la causa nombra el eslabón fallido", JSON.stringify(rota.error || {}).slice(0, 200));
    ok(rota.error?.slug === "ma-f1-roto", "§6.3 dice CUÁL eslabón se rompió");
    ok((rota.saltos || []).length === 2,
       `§6.4 se corrieron 2 saltos: el 3º NUNCA corrió (${(rota.saltos || []).length})`);
    ok(rota.respuesta === "", "§6.5 no se entrega una respuesta que nadie produjo");
    // El salto roto TAMBIÉN queda enlazado, y así tiene que ser: corrió, falló, y su fila
    // lo dice. Un salto fallido que desapareciera del registro sería el registro mintiendo.
    const tr = await api("GET", `/v1/multiagente/runs/${rota.run_id}`);
    const dbRota = tr.json?.saltos || [];
    ok(dbRota.length === 2,
       `§6.6 la DB enlaza los 2 saltos que CORRIERON — el 3º no dejó fila (${dbRota.length})`);
    ok(dbRota[0]?.status === "done" && dbRota[1]?.status === "error",
       "§6.7 el salto roto queda registrado como 'error', no borrado",
       JSON.stringify(dbRota.map((s) => s.status)));
    ok(tr.json?.status === "error", "§6.8 el run PADRE cierra en 'error' (no queda 'running')");

    // ── §7 · CERO REGRESIÓN ─────────────────────────────────────────────────────
    console.log("\n§7 · CERO REGRESIÓN — una receta SIN `modo` corre como siempre");
    const sinModo = {
      schema_version: "v1", meta: { name: "aleph normal", nicho: "general" },
      model: { primary: "openai/gpt-oss-120b", base_url: "https://api.groq.com/openai/v1",
               temperature: 0, max_tokens: 128, max_turns: 3 },
      belt: { belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
              tool_filters: { calc: ["add"] } },
      rag: { enabled: false },
    };
    const v = await api("POST", "/v1/recipes/validate", { recipe: sinModo });
    ok(v.status === 200, "§7.1 una receta v1 sin `modo` sigue validando", JSON.stringify(v.json).slice(0, 200));
    const normal = await api("POST", "/v1/puppets/run",
      { recipe: sinModo, prompt: "Decí exactamente: LISTO", user_id: USER, deadline_s: 180 });
    ok(normal.status === 201 && normal.json?.ok === true,
       "§7.2 /v1/puppets/run (el camino de siempre) sigue corriendo intacto",
       JSON.stringify(normal.json?.error || "").slice(0, 200));
    const nf = await api("GET", `/v1/multiagente/runs/${normal.json?.run_id}`);
    ok(nf.status === 404, "§7.3 un run NORMAL no es un run multiagente (modo NULL ⇒ 404)");

    // ── §8 · MIGRACIÓN EN LOS DOS DIALECTOS ─────────────────────────────────────
    console.log("\n§8 · MIGRACIÓN EN LOS DOS DIALECTOS");
    const mig = correrPy("platform/db/verify_multiagente_saltos.py");
    const lineasMig = mig.out.trim().split("\n");
    ok(mig.code === 0, "§8.1 la migración corre y asierta en Postgres Y en SQLite",
       lineasMig.slice(-6).join(" | "));
    console.log(`        · ${lineasMig.filter((l) => l.includes("✓")).length} asserts verdes ` +
                `(${lineasMig.filter((l) => l.includes("✗")).length} rojos)`);

    // ── §9 · VERIFIES EXISTENTES DEL MOTOR ──────────────────────────────────────
    console.log("\n§9 · VERIFIES EXISTENTES DEL MOTOR");
    for (const [rel, nombre] of [
      ["platform/assembler/test_multiagente.py", "§9.1 contrato CADENA (unidad)"],
      ["platform/assembler/test_models.py", "§9.2 test_models (cerebro/aliases)"],
      ["platform/assembler/test_recipe_assembler.py", "§9.3 test_recipe_assembler"],
      ["platform/assembler/verify_agent_refs_amendment.py", "§9.4 amendment agent_refs (§6)"],
    ]) {
      const res = correrPy(rel);
      ok(res.code === 0, `${nombre} verde`, res.out.trim().split("\n").slice(-3).join(" | "));
    }
    for (const [args, nombre] of [
      [["tests/phase1/test_recipe_validator.py"], "§9.5 test_recipe_validator"],
      [["platform/db/test_schema_sqlite.py"], "§9.6 test_schema_sqlite"],
      [["platform/db/test_dialect.py"], "§9.7 test_dialect"],
    ]) {
      const cwd = args[0].startsWith("tests/") ? path.join(ROOT, "product/backend") : ROOT;
      const res = spawnSync(PY, ["-m", "pytest", "-q", ...args],
        { cwd, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
      ok(res.status === 0, `${nombre} verde`,
         ((res.stdout || "") + (res.stderr || "")).trim().split("\n").slice(-2).join(" | "));
    }
  } finally {
    matarFrozen(proc);
    await sleep(500);
    try { fs.rmSync(DATADIR, { recursive: true, force: true }); } catch {}
  }

  console.log(`\n═══ ${FAIL === 0 ? "✓ VERDE" : "✗ ROJO"} — ${PASS} PASS · ${FAIL} FAIL ═══`);
  if (FAIL) console.log("  falladas:\n" + FALLADAS.map((f) => "   · " + f).join("\n"));
  process.exit(FAIL ? 1 : 0);
}

main().catch((e) => { console.error("✗ la vara explotó:", e); process.exit(1); });
