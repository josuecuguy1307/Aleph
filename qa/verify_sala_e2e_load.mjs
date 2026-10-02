/**
 * Vara determinista de carga del fixture de Sala.
 *
 * Cada turno se acepta antes del I/O y luego fuerza tres llamadas encadenadas; debe
 * cerrar con exactamente un `done`, texto no vacío y un client_turn_id único.
 *
 * ══ [H6 · 2026-08-08] LA PRECONDICIÓN ERA UN ROJO MUDO ═════════════════════════════
 * Decía «Precondición: `SALA_PORT=8304 node qa/sala_e2e_stub_server.mjs`» y nada más.
 * Sin el stub vivo, el primer `fetch` tiraba `ECONNREFUSED` y la vara moría con un stack
 * de Node — indistinguible de una regresión de la Sala. Medido en main @ 1242dba: roja.
 *
 * El stub está en el árbol y no depende de nada externo, así que **la vara lo levanta**:
 * si :8304 ya responde, se usa el que está (otra sesión lo puso, no se lo pisa ni se lo
 * mata); si no, se lo lanza y se lo baja al terminar.
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const PORT = Number(process.env.SALA_PORT || 8304);
if (PORT === 25374) throw new Error("25374 está prohibido para la vara");
const BASE = `http://127.0.0.1:${PORT}`;
const N = Number(process.env.SALA_LOAD_N || 24);
const AQUI = dirname(fileURLToPath(import.meta.url));

async function responde() {
  try {
    await fetch(`${BASE}/__qa/reset`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "ready" }),
    });
    return true;
  } catch { return false; }
}

/** Devuelve el proceso que hay que bajar al final, o null si el stub ya estaba vivo. */
async function asegurarStub() {
  if (await responde()) {
    console.log(`  · stub ya vivo en :${PORT} — se usa el que está (no se lo toca)`);
    return null;
  }
  const hijo = spawn(process.execPath, [join(AQUI, "sala_e2e_stub_server.mjs")], {
    env: { ...process.env, SALA_PORT: String(PORT) }, stdio: "ignore", detached: false,
  });
  // `unref` o la vara NO TERMINA NUNCA: un hijo vivo mantiene el event loop del padre
  // abierto aunque ya haya impreso su veredicto (medido: colgada de 3 min). El `exit`
  // handler de abajo es el que garantiza que igual se lo baja.
  hijo.unref();
  for (let intento = 0; intento < 60; intento++) {
    await new Promise((r) => setTimeout(r, 100));
    if (await responde()) {
      console.log(`  · stub levantado por la vara en :${PORT} (pid ${hijo.pid})`);
      return hijo;
    }
  }
  hijo.kill("SIGKILL");
  throw new Error(`el stub no levantó en :${PORT} tras 6 s — qa/sala_e2e_stub_server.mjs`);
}

const STUB = await asegurarStub();
process.on("exit", () => { if (STUB) STUB.kill("SIGKILL"); });

async function reset(mode = "ready") {
  const response = await fetch(`${BASE}/__qa/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!response.ok) throw new Error(`reset HTTP ${response.status}`);
}

async function turn(ix) {
  const id = `load-${Date.now()}-${ix}`;
  const started = performance.now();
  const response = await fetch(`${BASE}/v1/puppets/run/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt: `Carga pesada ${ix}`,
      client_turn_id: id,
      recipe: { schema_version: "v1" },
    }),
  });
  const accepted_ms = performance.now() - started;
  if (!response.ok) throw new Error(`turno ${ix}: HTTP ${response.status}`);
  const raw = await response.text();
  const frames = raw.split("\n")
    .filter((line) => line.startsWith("data: "))
    .map((line) => JSON.parse(line.slice(6)));
  const done = frames.filter((frame) => frame.type === "done");
  if (done.length !== 1) throw new Error(`turno ${ix}: done=${done.length}`);
  if (!String(done[0].answer || "").trim()) {
    throw new Error(`turno ${ix}: respuesta vacía`);
  }
  return { id, accepted_ms, answer: done[0].answer };
}

await reset();
const results = [];
for (let start = 0; start < N; start += 6) {
  results.push(...await Promise.all(
    Array.from({ length: Math.min(6, N - start) }, (_, offset) => turn(start + offset)),
  ));
}

const stateResponse = await fetch(`${BASE}/__qa/state`);
const state = await stateResponse.json();
if (state.seen.length !== N) {
  throw new Error(`requests vistos=${state.seen.length}, esperado=${N}`);
}
const ids = new Set(state.seen.map((item) => item.client_turn_id));
if (ids.size !== N) throw new Error(`client_turn_id únicos=${ids.size}, esperado=${N}`);
for (const item of state.seen) {
  if (!Array.isArray(item.model_calls) || item.model_calls.length !== 3) {
    throw new Error(`turno ${item.seq}: no ejecutó tres llamadas`);
  }
  if (!item.model_calls.every((call, ix) => call.step === ix + 1 &&
      call.finished_at >= call.started_at)) {
    throw new Error(`turno ${item.seq}: cadena fuera de orden`);
  }
}

const latencies = results.map((item) => item.accepted_ms);
const ordered = [...latencies].sort((a, b) => a - b);
const percentile = (p) => ordered[Math.min(
  ordered.length - 1, Math.floor((ordered.length - 1) * p),
)];
console.log(JSON.stringify({
  ok: true,
  turns: N,
  model_calls: N * 3,
  empty_answers: 0,
  duplicate_turn_ids: 0,
  accepted_ms: {
    min: Math.min(...latencies),
    p50: percentile(0.50),
    p95: percentile(0.95),
    max: Math.max(...latencies),
  },
}, null, 2));
// [H3] La última línea es el veredicto. El JSON de arriba es para la máquina; ésta es
// para el humano y para el `tail -1` que decide si un merge pasa.
console.log(`VERDE · ${N} turnos · ${N * 3} llamadas encadenadas · 0 vacías · 0 ids repetidos`);
