/* latencia-obra.mjs — el primer signo de vida en un turno CON HERRAMIENTAS.
 *
 * Por qué existe este segundo medidor. `latencia.mjs` mide la vía de CHARLA
 * (`/v1/puppets/run/stream`), que streamea token a token y ya cumple la meta. Pero un
 * agente equipado NO va por ahí: va por `/v1/puppets/run`, que es **un POST bloqueante**.
 * Ahí «latencia al primer token» no significa nada, porque no hay tokens hasta el final:
 * lo que importa es CUÁNDO EL USUARIO VE EL PRIMER SIGNO DE VIDA.
 *
 * Y ahí hay una diferencia real y medible entre las dos Salas:
 *
 *   A · SALA VIEJA, camino «charla con el belt» (sala.html:5543-5552). Manda el run
 *       **sin `space_id`**. Sin espacio no hay `events.jsonl`, así que no hay espinazo que
 *       mirar: la pantalla no recibe NADA hasta que el POST vuelve entero.
 *
 *   B · SALA V2. El adaptador **siempre** manda `space_id` y abre
 *       `GET /v1/spaces/{id}/stream` ANTES del POST. El primer evento real
 *       (`belt_ready`, `turn_started`, `tool_call_started`…) llega mientras el run corre.
 *
 * Las dos hacen EL MISMO turno contra EL MISMO backend. Lo único que cambia es si se pide
 * el espacio y se escucha. Cero cambios de backend: `space_id` es un campo que el body ya
 * acepta y `router.py` ya wirea el emisor cuando está presente.
 *
 * Uso:  BASE=http://127.0.0.1:8261 node latencia-obra.mjs [--n 3]
 */
const BASE = process.env.BASE || "http://127.0.0.1:8261";
const args = process.argv.slice(2);
const arg = (k, d) => {
  const i = args.indexOf("--" + k);
  return i === -1 ? d : args[i + 1];
};
const N = Number(arg("n", 3));

// Un turno que OBLIGA a usar una herramienta: sin tool no hay evento temprano que medir, y
// el punto de la comparación se pierde.
const PROMPT = "Sumá 2 más 3 usando la herramienta calc y decime el resultado.";
const RECIPE = {
  schema_version: "v1",
  meta: { name: "medicion-latencia-obra", nicho: "test" },
  model: {
    primary: "claude-code-cli",
    base_url: process.env.BRAIN || "http://127.0.0.1:8927/v1",
    brain_provider: "claude_cli",
    cli_model: "sonnet",
    effort: "low",
    max_tokens: 300,
    temperature: 0,
    max_turns: 4,
  },
  belt: {
    belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
    tool_filters: { calc: ["add"] },
  },
  rag: { enabled: false },
  keys: {},
};

const nuevoSpace = (i) => `lat-obra-${Date.now().toString(36)}-${i}`;

/** A · como la Sala vieja: POST y a esperar. */
async function sinEspinazo() {
  const t0 = performance.now();
  const r = await fetch(BASE + "/v1/puppets/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt: PROMPT, recipe: RECIPE, lang: "es" }),
  });
  const out = await r.json().catch(() => null);
  const t = Math.round(performance.now() - t0);
  return {
    primer_signo_ms: t, // el POST ES el primer signo: no hubo nada antes
    total_ms: t,
    ok: out?.ok ?? null,
    pasos: out?.trajectory_steps ?? null,
    model_final: out?.model_final ?? null,
    degraded: out?.degraded ?? null,
    primer_evento: null,
  };
}

/** B · como sala-v2: espinazo abierto ANTES del POST. */
async function conEspinazo(i) {
  const spaceId = nuevoSpace(i);
  const t0 = performance.now();
  let tPrimerEvento = null;
  let primerTipo = null;
  let eventos = 0;

  const abort = new AbortController();
  const espinazo = (async () => {
    // MISMO reintento que el adaptador (`agui/aleph-agent.js`): el espacio devuelve 404
    // hasta que el run lo crea, así que un 404 acá es «todavía no», no un fallo. Sin esto
    // el medidor mediría un espinazo que nunca conectó — que es exactamente lo que pasó en
    // la primera corrida (0 eventos) y lo que destapó el bug.
    let r = null;
    const t0r = Date.now();
    for (;;) {
      if (abort.signal.aborted) return;
      try {
        r = await fetch(`${BASE}/v1/spaces/${encodeURIComponent(spaceId)}/stream`, {
          headers: { Accept: "text/event-stream" },
          signal: abort.signal,
        });
      } catch {
        r = null;
      }
      if (r && r.ok) break;
      if (r && r.status !== 404) return;
      if (Date.now() - t0r > 20000) return;
      await new Promise((res) => setTimeout(res, 120));
    }
    if (!r.body) return;
    const rd = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    try {
      for (;;) {
        const { done, value } = await rd.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let c;
        while ((c = buf.indexOf("\n\n")) !== -1) {
          const bloque = buf.slice(0, c);
          buf = buf.slice(c + 2);
          for (const l of bloque.split("\n")) {
            if (!l.startsWith("data:")) continue;
            let e;
            try {
              e = JSON.parse(l.slice(5).trim());
            } catch {
              continue;
            }
            eventos++;
            if (tPrimerEvento === null) {
              tPrimerEvento = performance.now();
              primerTipo = e.type || (e.payload && e.payload.type) || "?";
            }
          }
        }
      }
    } catch {
      /* abortado al cerrar el turno */
    }
  })();

  const r = await fetch(BASE + "/v1/puppets/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt: PROMPT, recipe: RECIPE, space_id: spaceId, lang: "es" }),
  });
  const out = await r.json().catch(() => null);
  const total = Math.round(performance.now() - t0);
  abort.abort();
  await espinazo;

  return {
    primer_signo_ms: tPrimerEvento === null ? total : Math.round(tPrimerEvento - t0),
    total_ms: total,
    ok: out?.ok ?? null,
    pasos: out?.trajectory_steps ?? null,
    model_final: out?.model_final ?? null,
    degraded: out?.degraded ?? null,
    primer_evento: primerTipo,
    eventos,
  };
}

const mediana = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : Math.round((s[s.length / 2 - 1] + s[s.length / 2]) / 2);
};

console.log(`\n· latencia de OBRA (turno con herramienta) · ${N}×2 turnos · ${BASE}`);
console.log(`  turno: "${PROMPT}"\n`);

const A = [];
const B = [];
for (let i = 0; i < N; i++) {
  try {
    const a = await sinEspinazo();
    A.push(a);
    console.log(
      `  A${i + 1} · SIN espinazo (Sala vieja) · primer signo ${String(a.primer_signo_ms).padStart(6)} ms` +
        ` · ok=${a.ok} · pasos=${a.pasos} · model_final=${a.model_final}`,
    );
  } catch (e) {
    console.log(`  A${i + 1} · ✗ ${String(e.message).slice(0, 160)}`);
  }
  try {
    const b = await conEspinazo(i);
    B.push(b);
    console.log(
      `  B${i + 1} · CON espinazo (sala-v2)   · primer signo ${String(b.primer_signo_ms).padStart(6)} ms` +
        ` (${b.primer_evento}) · total ${b.total_ms} ms · ${b.eventos} eventos` +
        ` · ok=${b.ok} · pasos=${b.pasos} · model_final=${b.model_final}`,
    );
  } catch (e) {
    console.log(`  B${i + 1} · ✗ ${String(e.message).slice(0, 160)}`);
  }
}

console.log("\n" + "─".repeat(72));
if (A.length) {
  const m = mediana(A.map((x) => x.primer_signo_ms));
  console.log(`  A · Sala vieja  — primer signo de vida: mediana ${m} ms  ${m <= 5000 ? "" : "❌ >5 s"}`);
}
if (B.length) {
  const m = mediana(B.map((x) => x.primer_signo_ms));
  const t = mediana(B.map((x) => x.total_ms));
  console.log(`  B · sala-v2     — primer signo de vida: mediana ${m} ms  (turno completo ${t} ms)`);
  console.log(`  META ≤5000 ms   ${m <= 5000 ? "✅ cumple" : "❌ NO cumple"}`);
}
if (A.length && B.length) {
  const a = mediana(A.map((x) => x.primer_signo_ms));
  const b = mediana(B.map((x) => x.primer_signo_ms));
  console.log(`\n  mejora: ${a} ms → ${b} ms  (${a > 0 ? Math.round((1 - b / a) * 100) : 0}% menos de espera muda)`);
}
console.log("─".repeat(72));
