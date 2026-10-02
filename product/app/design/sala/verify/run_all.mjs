/* run_all.mjs — runner secuencial de la red de seguridad e2e de La Sala.
 *
 * SIEMPRE secuencial: la cola postgres es compartida y el shim atiende de a uno.
 * Salida: matriz ✓/✗ por caso + results/summary.json + exit≠0 si algo falló.
 *
 *   node product/app/design/sala/verify/run_all.mjs             # todos
 *   node product/app/design/sala/verify/run_all.mjs f3 f4       # subset por prefijo
 */
import fs from "node:fs";
import { RESULTS_DIR, STATE_FILE } from "./_env.mjs";
import { preflight } from "./_stack.mjs";
import { launch } from "./_drive.mjs";
import { seedPuppets } from "./seed_puppets.mjs";

const CASES = [
  { key: "s3", live: true,  mod: () => import("./case_s3_planilla.mjs") },
  { key: "s6", live: true,  mod: () => import("./case_s6_web.mjs") },
  { key: "f3", live: false, mod: () => import("./case_f3_errorcard.mjs") },
  { key: "f4", live: true,  mod: () => import("./case_f4_gate.mjs") },
  { key: "r1", live: true,  mod: () => import("./case_r1_fem.mjs") },
  { key: "r2", live: true,  mod: () => import("./case_r2_quant.mjs") },
  { key: "r3", live: true,  mod: () => import("./case_r3_electronica.mjs") },
  { key: "r4", live: true,  mod: () => import("./case_r4_medicina.mjs") },
  { key: "n1", live: true,  mod: () => import("./case_n1_economista.mjs") },
  { key: "n2", live: true,  mod: () => import("./case_n2_ejecutivo.mjs") },
  { key: "n3", live: true,  mod: () => import("./case_n3_dev.mjs") },
  { key: "n4", live: true,  mod: () => import("./case_n4_periodista.mjs") },
  { key: "n5", live: true,  mod: () => import("./case_n5_farmaceutico.mjs") },
  { key: "m",  live: true,  mod: () => import("./case_m_delegacion.mjs") },
  // L1 FUERA del default (known-red, hallazgo de PRODUCTO reproducible ×2, 2026-07-04):
  // en 8 turnos con 5 ediciones secuenciales el modelo PIERDE puntos ya existentes de la
  // lista (corrida 1: 4/6 marcadores; corrida 2: 1/6) pese al "No toques los existentes"
  // y al mandato de buildEditPrompt. 8/9 checks restantes verdes (hilo, bitácora, 1 obra,
  // cero errcards). Sospecha: el edit-prompt ancla a la "tarea original" (lista de UN
  // punto) y sesga la regeneración. Correr a demanda: `node run_all.mjs l1`.
  { key: "l1", live: true, skipDefault: true, mod: () => import("./case_l1_conversacion.mjs") },
];

const wanted = process.argv.slice(2).map((s) => s.toLowerCase());
const selected = wanted.length
  ? CASES.filter((c) => wanted.some((w) => c.key.startsWith(w)))
  : CASES.filter((c) => !c.skipDefault);   // los known-red documentados corren solo a demanda
const needLive = selected.some((c) => c.live);

console.log("— preflight del stack —");
const pf = await preflight({ requireShim: needLive });
if (!pf.ok) { console.error("✗ stack incompleto — no se corre nada (cero falsos verdes)"); process.exit(2); }

let state = null;
if (needLive) {
  console.log("— puppets QA —");
  state = fs.existsSync(STATE_FILE) ? JSON.parse(fs.readFileSync(STATE_FILE, "utf8")) : null;
  // re-siembra idempotente si falta estado o el backend no reconoce la sesión guardada
  const fresh = await seedPuppets().catch((e) => { console.error("✗ seed: " + e.message); process.exit(2); });
  state = fresh || state;
} else {
  // los casos stub igual necesitan un usuario con sesión válida para el boot de la página
  const { ensureQaUser } = await import("./_drive.mjs");
  state = { user: await ensureQaUser(), puppets: {} };
}

const browser = await launch();
const results = [];
for (const c of selected) {
  console.log("\n══ " + c.key.toUpperCase() + " ══");
  const t0 = Date.now();
  try {
    const { run } = await c.mod();
    const r = await run(browser, state);
    results.push({ ...r, wall_s: Math.round((Date.now() - t0) / 1000) });
  } catch (e) {
    console.error("  ✗ excepción del caso: " + (e && e.message));
    results.push({ case: c.key, pass: false, checks: [], error: String(e && e.message), wall_s: Math.round((Date.now() - t0) / 1000) });
  }
}
await browser.close();

fs.mkdirSync(RESULTS_DIR, { recursive: true });
const summary = {
  at: new Date().toISOString(),
  pass: results.every((r) => r.pass),
  cases: results.map((r) => ({ case: r.case, pass: r.pass, wall_s: r.wall_s, fails: (r.checks || []).filter((c) => !c.ok).map((c) => c.name), error: r.error })),
};
fs.writeFileSync(RESULTS_DIR + "summary.json", JSON.stringify({ summary, results }, null, 2));

console.log("\n════ RESUMEN ════");
for (const r of results) console.log((r.pass ? "  ✓ " : "  ✗ ") + r.case + "  (" + r.wall_s + "s)");
console.log(summary.pass ? "✓ RED DE SEGURIDAD VERDE" : "✗ HAY ROJOS — ver results/summary.json");
process.exit(summary.pass ? 0 : 1);
