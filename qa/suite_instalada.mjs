#!/usr/bin/env node
/**
 * suite_instalada.mjs — LA SUITE CONTRA LA APP INSTALADA, no contra el repo.
 *
 *   node qa/suite_instalada.mjs
 *
 * ⚠️ POR QUÉ EXISTE. Todas las varas leen los archivos del árbol de trabajo, y eso mide el
 * repo — que es lo que uno acaba de escribir, no lo que el usuario acaba de instalar. Entre
 * los dos hay un empaquetador: PyInstaller decide qué viaja, y **pierde callado** lo que no
 * ve. Ya pasó cuatro veces en este repo (`assembler`, `multiagente`, `restaurador`,
 * `repair_clasificar`): el build no se queja, la vara del repo sale verde, y el fallo
 * aparece en la máquina del usuario.
 *
 * Acá el SUJETO es el bundle. Se extraen sus assets —`product/app/design/**` y `catalog/**`
 * tal como viajaron— a un árbol temporal, se copian las varas encima, y se corren ahí. Un
 * archivo que no viajó hace fallar la vara con su nombre, en vez de no notarse.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LO QUE ESTA SUITE **NO** PUEDE MEDIR, dicho de frente:
 *
 * Los guards estructurales que leen código de BACKEND (`centro_conexiones.py`, `main.py`,
 * `conexiones_verificador.py`) no tienen contra qué correr: en el bundle ese código viaja
 * COMPILADO adentro del PYZ, no como fuente. Esas aserciones se marcan `[repo]` en el
 * reporte y su verificación sobre la instalada es otra: que los endpoints respondan, que se
 * comprueba aparte contra el sidecar levantado.
 *
 * Decirlo es el punto. Una suite que corre esas aserciones contra el repo y las reporta como
 * «verificado en la instalada» miente sobre lo único que esta suite existe para saber.
 */
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, cpSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const APP = process.env.ALEPH_APP || "/Applications/Aleph.app";
const SIDECAR = join(APP, "Contents/MacOS/aleph_sidecar");
const PUERTO = Number(process.env.ALEPH_SUITE_PORT || 8397);
const VENV = join(RAIZ, "product/backend/.venv/bin/python");

const t0 = Date.now();
const seg = () => ((Date.now() - t0) / 1000).toFixed(1);
const linea = (c) => console.log(c);

if (!existsSync(SIDECAR)) {
  console.error(`✗ no existe el sidecar instalado: ${SIDECAR}`);
  process.exit(1);
}
const HASH = execFileSync("shasum", ["-a", "256", SIDECAR], { encoding: "utf8" })
  .split(" ")[0];

linea("═".repeat(96));
linea("SUITE CONTRA LA APP INSTALADA");
linea("═".repeat(96));
linea(`  app    : ${APP}`);
linea(`  sidecar: ${HASH}`);
linea(`  repo   : ${execFileSync("git", ["-C", RAIZ, "rev-parse", "--short", "HEAD"],
                                 { encoding: "utf8" }).trim()}`);
linea("");

/* ── 1 · EXTRAER LOS ASSETS DEL BUNDLE ──────────────────────────────────────────────── */
linea("1 · extrayendo los assets del bundle (lo que VIAJÓ, no lo que escribí)");
const ARBOL = mkdtempSync(join(tmpdir(), "aleph-instalada-"));
const py = `
import os, sys
from PyInstaller.archive.readers import CArchiveReader
r = CArchiveReader(${JSON.stringify(SIDECAR)})
destino = ${JSON.stringify(ARBOL)}
n = 0
for nombre in r.toc:
    if not (nombre.startswith("product/app/design/") or nombre.startswith("catalog/")):
        continue
    d = r.extract(nombre)
    datos = d[-1] if isinstance(d, tuple) else d
    if datos is None:
        continue
    ruta = os.path.join(destino, nombre)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "wb") as f:
        f.write(datos)
    n += 1
print(n)
`;
let extraidos = 0;
try {
  extraidos = Number(execFileSync(VENV, ["-c", py], { encoding: "utf8" }).trim());
} catch (e) {
  console.error("✗ no pude extraer el bundle:", String(e.message).split("\n")[0]);
  process.exit(1);
}
linea(`    ${extraidos} archivos extraídos → ${ARBOL}`);

// Las varas y el diseño del Cuarto que ellas importan tienen que estar en el mismo árbol.
mkdirSync(join(ARBOL, "qa"), { recursive: true });
const VARAS = ["verify_widget_unico.mjs", "verify_conocimiento_tipos.mjs",
               "verify_ui_siempre_solucion.mjs", "verify_superficie_montada.mjs"];
//: `censo_widget.mjs` no es una vara pero una de ellas lo LEE (el guard de la deuda
//: retenida comprueba que el censo la reporte). Sin él la vara revienta por un ENOENT que
//: no dice nada sobre la app — un falso rojo del arnés, que es peor que no medir.
const AUXILIARES = ["censo_widget.mjs"];
for (const v of [...VARAS, ...AUXILIARES]) cpSync(join(RAIZ, "qa", v), join(ARBOL, "qa", v));

// ⚠️ EL BACKEND NO VIAJA COMO FUENTE. Se enlaza el del repo para que las aserciones que lo
// leen no revienten — y se REPORTAN aparte, marcadas `[repo]`: sobre esas, esta suite no
// tiene nada que decir.
for (const d of ["product/backend", "platform"]) {
  const destino = join(ARBOL, d);
  mkdirSync(dirname(destino), { recursive: true });
  try { cpSync(join(RAIZ, d), destino, { recursive: true, dereference: false }); }
  catch (_) { /* si no se puede copiar, la vara lo dirá */ }
}

/* ── 2 · LEVANTAR EL SIDECAR INSTALADO ──────────────────────────────────────────────── */
//
// ⚠️ CREDENCIALES REALES, ESCRITURAS EN UNA COPIA. Ésta es la lección que F6 dejó escrita y
// que ESTA suite era la única que no aplicaba: se levantaba con `spawn(SIDECAR, [...])` a
// secas, o sea heredando el datadir REAL del usuario, y sus varas sembraban fixtures ahí.
//
// MEDIDO el 2026-08-06, por corrida: **+25 users · +13 keys · +41 puppets** en el
// `aleph.db` de persona usuaria. Con la misma firma (`openai`/…ings, `gemini`/…line) que las 363 filas
// que F6 ya había reportado como fixtures — o sea que esto venía ensuciando desde antes.
//
// La copia se hace del datadir REAL a propósito: las sesiones y credenciales de verdad
// tienen que viajar (si no, la suite mide una app vacía), pero los turnos de prueba y los
// reinicios caen en la copia y desaparecen con el tmpdir.
const DATOS_REALES = process.env.ALEPH_DATA_DIR ||
  join(process.env.HOME || "", "Library/Application Support/Aleph");
const DATOS = join(ARBOL, "datadir");
mkdirSync(DATOS, { recursive: true });
if (existsSync(DATOS_REALES)) {
  // `dereference:false` + los WAL/SHM: copiar sólo el .db deja fuera lo que todavía no se
  // hizo checkpoint, y la copia arranca con una foto vieja de la DB.
  for (const f of ["aleph.db", "aleph.db-wal", "aleph.db-shm", "motor_estado.json"]) {
    try { cpSync(join(DATOS_REALES, f), join(DATOS, f)); } catch (_) { /* opcional */ }
  }
  for (const d of ["secrets", "modelos", "espacios"]) {
    try { cpSync(join(DATOS_REALES, d), join(DATOS, d), { recursive: true }); }
    catch (_) { /* opcional */ }
  }
}
linea("");
linea("2 · levantando el sidecar instalado");
linea(`    datadir: COPIA en ${DATOS}  (la real no se toca)`);
const proc = spawn(SIDECAR, ["--port", String(PUERTO)],
  { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, ALEPH_DATA_DIR: DATOS } });
let salida = "";
proc.stdout.on("data", (b) => { salida += b; });
proc.stderr.on("data", (b) => { salida += b; });
const esperar = async () => {
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      const r = await fetch(`http://127.0.0.1:${PUERTO}/health`);
      if (r.ok) return await r.json();
    } catch (_) { /* todavía no */ }
  }
  return null;
};
const salud = await esperar();
if (!salud) { proc.kill(); console.error("✗ el sidecar instalado no levantó"); process.exit(1); }
linea(`    vivo · build=${salud.proceso?.build} · ${seg()}s`);

/* ── 3 · LAS VARAS, CONTRA LOS ASSETS DEL BUNDLE ────────────────────────────────────── */
linea("");
linea("3 · las varas, contra los assets del BUNDLE");
const resultados = [];
for (const v of VARAS) {
  const t = Date.now();
  let ok = true, out = "";
  try { out = execFileSync("node", [join(ARBOL, "qa", v)], { encoding: "utf8" }); }
  catch (e) { ok = false; out = String(e.stdout || "") + String(e.stderr || ""); }
  const fallos = (out.match(/^ {2}❌ .*/gm) || []).map((l) => l.replace(/^ {2}❌ /, "").trim());
  resultados.push({ vara: v, ok, fallos, ms: Date.now() - t });
  linea(`    ${ok ? "✅" : "❌"} ${v.padEnd(34)} ${((Date.now() - t) / 1000).toFixed(1)}s` +
        (fallos.length ? `  · ${fallos.length} rojas` : ""));
  for (const f of fallos) linea(`         ✗ ${f}`);
}

/* ── 3.b · LA PANTALLA DE MODELOS, POR CLICKS, CONTRA EL BUNDLE ─────────────────────
 *
 * [F7] Las varas de arriba miden ARCHIVOS extraídos. Ésta levanta un browser contra el
 * sidecar INSTALADO y camina la pantalla: es la única forma de ver si el camino de clicks
 * existe. La auditoría del 2026-08-06 midió justo eso — dos capas que viajaban en el
 * bundle y ningún click de la app llegaba a ellas.
 *
 * Habla con el sidecar de esta suite (`ALEPH_SUITE_PORT`) usando su modo frozen: los
 * ASSETS salen del bundle, la API la sirve su fixture.
 */
linea("");
linea("3.b · la pantalla de Modelos, por CLICKS, contra el bundle");
let modelosOk = true, modelosResumen = "";
try {
  const salida = execFileSync("node", [join(RAIZ, "qa", "verify_modelos_v2.mjs")], {
    encoding: "utf8",
    env: { ...process.env,
           MODELOS_V2_FROZEN_URL: `http://127.0.0.1:${PUERTO}`,
           // la vara exige que el frozen viva exactamente en su puerto declarado: se le
           // dice cuál es el de esta suite en vez de pedirle que adivine.
           MODELOS_V2_PORT: String(PUERTO),
           MODELOS_V2_LOCK_HELD: "1" },
  });
  modelosResumen = (salida.trim().split("\n").pop() || "").trim();
} catch (e) {
  modelosOk = false;
  const out = String(e.stdout || "") + String(e.stderr || "");
  modelosResumen = (out.trim().split("\n").pop() || "").trim();
  for (const l of (out.match(/^✗ .*/gm) || [])) linea(`         ${l}`);
}
resultados.push({ vara: "verify_modelos_v2.mjs", ok: modelosOk, fallos: modelosOk ? [] : [modelosResumen], ms: 0 });
linea(`    ${modelosOk ? "✅" : "❌"} ${"verify_modelos_v2.mjs".padEnd(34)} ${modelosResumen}`);

/* ── 4 · LO QUE SÓLO SE PUEDE MEDIR CONTRA EL SIDECAR VIVO ──────────────────────────── */
linea("");
linea("4 · lo compilado: los endpoints del bundle responden");
const B = `http://127.0.0.1:${PUERTO}`;
const endpoints = [
  ["GET", "/v1/conexiones/fuentes", 200],   // sin sesión → leido:false, pero la ruta vive
  ["POST", "/v1/conexiones/barrer", 401],
  ["POST", "/v1/conexiones/x/reintentar", 401],
  // 401 es el ACIERTO, no un fallo: el checklist corre sobre las conexiones de ALGUIEN y
  // sin sesión no hay a quién. Esperar 200 acá era un error de esta suite — una ruta que
  // contestara 200 sin sesión sería el bug.
  ["POST", "/v1/conexiones/checklist", 401],
  // [F7] el checklist vivo de Modelos (F4c · obra 4). Existía en el backend con CERO
  // llamadores; ahora tiene cliente, y acá se comprueba que además VIAJÓ en el bundle.
  ["POST", "/v1/modelos/checklist", 401],
  ["GET", "/v1/modelos/v2", 200],
];
const rutas = [];
for (const [metodo, ruta, esperado] of endpoints) {
  let code = 0;
  try {
    const r = await fetch(B + ruta, metodo === "POST"
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }
      : {});
    code = r.status;
  } catch (_) { code = -1; }
  const bien = code === esperado;
  rutas.push({ ruta, code, esperado, bien });
  linea(`    ${bien ? "✅" : "❌"} ${metodo.padEnd(4)} ${ruta.padEnd(34)} HTTP ${code}` +
        (bien ? "" : `  (esperaba ${esperado})`));
}

linea("");
linea("5 · los assets que la pantalla carga, servidos por el bundle");
const assets = ["Conectores.dc.html", "conectores/montaje.js", "conectores/superficie.js",
                "conectores/widget.js", "conectores/conocimiento.js", "conectores/fuentes.js",
                // [F7] LA PANTALLA DE MODELOS. Sus dos capas de F4c viajaban en el bundle
                // desde el 2026-08-04 SIN que nadie las importara: pedirlas acá no alcanza
                // —viajar no es estar montado— y por eso la vara de abajo mide los clicks.
                "Modelos.dc.html", "modelos/modelos.ui.js", "modelos/modelos.superficie.js",
                "modelos/modelos.widget.js", "modelos/modelos.api.js"];
const muertos = ["conectores/conectores.ui.js", "diagnostico/wizard.js"];
const servidos = [];
for (const a of assets) {
  const r = await fetch(`${B}/${a}`).catch(() => null);
  const bien = !!r && r.status === 200;
  servidos.push({ a, bien });
  linea(`    ${bien ? "✅" : "❌"} ${a.padEnd(34)} HTTP ${r ? r.status : "—"}`);
}
for (const a of muertos) {
  const r = await fetch(`${B}/${a}`).catch(() => null);
  const bien = !!r && r.status === 404;
  servidos.push({ a, bien });
  linea(`    ${bien ? "✅" : "❌"} ${a.padEnd(34)} HTTP ${r ? r.status : "—"} (demolido: 404)`);
}

proc.kill();

/* ── EL PARTE ───────────────────────────────────────────────────────────────────────── */
const verdes = resultados.filter((r) => r.ok).length;
const rutasOk = rutas.filter((r) => r.bien).length;
const assetsOk = servidos.filter((s) => s.bien).length;
const todo = verdes === resultados.length && rutasOk === rutas.length &&
             assetsOk === servidos.length;
linea("");
linea("═".repeat(96));
linea(`  VARAS      ${verdes}/${resultados.length} verdes`);
linea(`  ENDPOINTS  ${rutasOk}/${rutas.length}`);
linea(`  ASSETS     ${assetsOk}/${servidos.length}`);
linea(`  DURACIÓN   ${seg()}s`);
linea(`  SIDECAR    ${HASH}`);
linea("═".repeat(96));
if (!todo) {
  linea("DIVERGENCIAS instalada-vs-repo:");
  for (const r of resultados.filter((x) => !x.ok))
    for (const f of r.fallos) linea(`  ✗ ${r.vara} · ${f}`);
  for (const r of rutas.filter((x) => !x.bien))
    linea(`  ✗ ruta ${r.ruta}: HTTP ${r.code}, esperaba ${r.esperado}`);
  for (const s of servidos.filter((x) => !x.bien)) linea(`  ✗ asset ${s.a}`);
}
process.exit(todo ? 0 : 1);
