/* latencia.mjs — ¿cuánto tarda el primer token VISIBLE?
 *
 * La meta de la obra 1.3 es ≤5 s percibido al primer token. «Percibido» significa desde que
 * la persona suelta Enter hasta que ve la primera letra en pantalla — no desde que el
 * modelo empieza a generar, que es otra cosa y siempre da mejor.
 *
 * Por eso el reloj arranca ANTES del `fetch` y para en el primer frame `token` con texto
 * no vacío. Todo lo que hay en el medio (preflight de presupuesto, carga de receta,
 * validación, rehidratación del hilo, arranque del CLI, primer byte del modelo) cuenta,
 * porque para el usuario todo eso es «no pasa nada todavía».
 *
 * MISMO TURNO SIEMPRE. El prompt está fijo y es corto a propósito: mide el arranque, no la
 * generación. Cambiarlo invalida la comparación antes/después.
 *
 * Uso:
 *   BASE=http://127.0.0.1:8261 node latencia.mjs [--n 5] [--etiqueta antes]
 */
const BASE = process.env.BASE || "http://127.0.0.1:8261";
const args = process.argv.slice(2);
const arg = (k, d) => {
  const i = args.indexOf("--" + k);
  return i === -1 ? d : args[i + 1];
};
const N = Number(arg("n", 5));
const ETIQUETA = arg("etiqueta", "sin-etiqueta");

// El turno canónico. Corto, determinista en forma, y sin tools: lo que se mide es el
// arranque del stack, no cuánto piensa el modelo.
const PROMPT = "Decí solamente: listo.";
const RECIPE = {
  schema_version: "v1",
  meta: { name: "medicion-latencia", nicho: "test" },
  model: {
    primary: "claude-code-cli",
    base_url: process.env.BRAIN || "http://127.0.0.1:8927/v1",
    brain_provider: "claude_cli",
    cli_model: "sonnet",
    effort: "low",
    max_tokens: 64,
    temperature: 0,
    max_turns: 1,
  },
  belt: { belt_ref: 'platform/assembler/fixtures/belt-inline-rich.mcp.json', tool_filters: { calc: ['add'] } },
  rag: { enabled: false },
  keys: {},
};

async function unTurno() {
  const t0 = performance.now();
  let tPrimerToken = null;
  let tDone = null;
  let texto = "";
  let frames = 0;

  const r = await fetch(BASE + "/v1/puppets/run/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ prompt: PROMPT, recipe: RECIPE, lang: "es" }),
  });
  if (!r.ok) {
    const cuerpo = await r.text().catch(() => "");
    throw new Error(`HTTP ${r.status} — ${cuerpo.slice(0, 300)}`);
  }

  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let corte;
    while ((corte = buf.indexOf("\n\n")) !== -1) {
      const bloque = buf.slice(0, corte);
      buf = buf.slice(corte + 2);
      for (const linea of bloque.split("\n")) {
        if (!linea.startsWith("data:")) continue;
        let f;
        try {
          f = JSON.parse(linea.slice(5).trim());
        } catch {
          continue;
        }
        frames++;
        if (f.type === "token" && f.text && tPrimerToken === null) {
          tPrimerToken = performance.now();
        }
        if (f.type === "token") texto += f.text || "";
        if (f.type === "done") {
          tDone = performance.now();
          if (tPrimerToken === null && f.answer) {
            // Sin un solo `token` y con `answer` en el `done`: el turno NO streameó.
            // Se anota como tal — decir que el primer token llegó al final sería mentir
            // sobre la naturaleza del número.
            tPrimerToken = tDone;
            texto = f.answer;
          }
        }
        if (f.type === "error") throw new Error("error del turno: " + (f.detail || "?"));
      }
    }
  }

  return {
    ttft_ms: tPrimerToken === null ? null : Math.round(tPrimerToken - t0),
    total_ms: tDone === null ? null : Math.round(tDone - t0),
    frames,
    streameo: frames > 2,
    texto: texto.trim().slice(0, 80),
  };
}

const mediana = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : Math.round((s[s.length / 2 - 1] + s[s.length / 2]) / 2);
};

console.log(`\n· latencia · etiqueta="${ETIQUETA}" · ${N} turnos · ${BASE}`);
console.log(`  turno: "${PROMPT}"  ·  cerebro: ${RECIPE.model.primary} @ ${RECIPE.model.base_url}\n`);

const filas = [];
for (let i = 0; i < N; i++) {
  try {
    const r = await unTurno();
    filas.push(r);
    console.log(
      `  ${String(i + 1).padStart(2)} · primer token ${String(r.ttft_ms).padStart(6)} ms` +
        ` · total ${String(r.total_ms).padStart(6)} ms · ${r.frames} frames` +
        ` · ${r.streameo ? "streameó" : "NO streameó"} · “${r.texto}”`,
    );
  } catch (e) {
    console.log(`  ${String(i + 1).padStart(2)} · ✗ ${String(e.message).slice(0, 200)}`);
  }
}

const ok = filas.filter((f) => f.ttft_ms != null);
if (!ok.length) {
  console.log("\n  sin una sola medición válida — no hay número que reportar.");
  process.exit(1);
}
const ttfts = ok.map((f) => f.ttft_ms);
const med = mediana(ttfts);
console.log("\n" + "─".repeat(64));
console.log(`  ETIQUETA        ${ETIQUETA}`);
console.log(`  turnos válidos  ${ok.length}/${N}`);
console.log(`  primer token    mediana ${med} ms · min ${Math.min(...ttfts)} · max ${Math.max(...ttfts)}`);
console.log(`  total           mediana ${mediana(ok.map((f) => f.total_ms))} ms`);
console.log(`  streaming real  ${ok.filter((f) => f.streameo).length}/${ok.length} turnos`);
console.log(`  META ≤5000 ms   ${med <= 5000 ? "✅ cumple" : "❌ NO cumple"}`);
console.log("─".repeat(64));
