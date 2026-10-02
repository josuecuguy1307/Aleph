/* _env.mjs — constantes del harness e2e de La Sala.
 * El stack NO se spawnea desde acá (ver _stack.mjs: preflight honesto, falla por pieza).
 * Puertos canónicos del stack dev: backend :8080 · front proxy :8091 · brain shim :8923. */

export const FRONT = process.env.SALA_FRONT || "http://127.0.0.1:8091";
export const BACK  = process.env.SALA_BACK  || "http://127.0.0.1:8080";
export const SHIM  = process.env.SALA_SHIM  || "http://127.0.0.1:8923";

export const SALA_URL = FRONT + "/sala/sala.html";

// token dummy del stub de Gmail (N2): el stub exige ESTE bearer → prueba la inyección BYOK.
// Debe ser el MISMO valor en: el upsert de la key (seed) y el argv de _gmail_stub_run.py.
export const GMAIL_DUMMY = "ya29.DUMMY_sala_n2_inyeccion_verificada";

// usuario QA dedicado (se registra idempotente vía /v1/auth)
export const QA_EMAIL = process.env.SALA_QA_EMAIL || "sala-e2e@puppet.local";
export const QA_PASS  = process.env.SALA_QA_PASS  || "sala-e2e-2026";

// presupuestos por caso (ms). El shim (Opus vía claude -p) corre ~55-65s por turno.
export const BUDGET = {
  live:  240_000,   // caso vivo con brain shim (1-2 turnos + tools)
  stub:  30_000,    // caso con /run stubeado (contrato frontend puro)
  gate:  240_000,
};

// dónde caen evidencias
export const SCREEN_DIR  = new URL("./screenshots/", import.meta.url).pathname;
export const RESULTS_DIR = new URL("./results/", import.meta.url).pathname;
export const STATE_FILE  = new URL("./.state.json", import.meta.url).pathname;
