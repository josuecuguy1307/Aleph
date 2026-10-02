#!/usr/bin/env node
/*
 * Certificación acotada de la Sala contra un sidecar YA arrancado desde la app
 * instalada. Hace tres turnos reales, cada uno con dos tools dependientes (por lo
 * tanto tres llamadas al cerebro), comprueba el transcript, reintenta un
 * client_turn_id cerrado y retoma el hilo con una pregunta sobre el primer turno.
 */
const PORT = Number(process.env.SALA_REINA_PORT || 8330);
if (PORT === 25374) throw new Error(":25374 está reservado para la app y no se usa en la vara");
const BASE = `http://127.0.0.1:${PORT}`;

let token = "";
let pass = 0;
let fail = 0;
const failures = [];
const check = (condition, name, detail = "") => {
  if (condition) {
    pass += 1;
    console.log(`  PASS  ${name}${detail ? ` — ${detail}` : ""}`);
  } else {
    fail += 1;
    failures.push(name);
    console.log(`  FAIL  ${name}${detail ? ` — ${detail}` : ""}`);
  }
  return Boolean(condition);
};

async function api(method, route, body) {
  const started = performance.now();
  const response = await fetch(BASE + route, {
    method,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const raw = await response.text();
  let json = null;
  try { json = raw ? JSON.parse(raw) : null; } catch {}
  return { status: response.status, json, raw, wall_ms: Math.round(performance.now() - started) };
}

const recipe = {
  schema_version: "v1",
  meta: {
    name: "Sala reina instalada",
    nicho: "general",
    descripcion: "Dos cálculos dependientes, cierre y transcript idempotente",
  },
  model: {
    brain_provider: "claude_cli",
    primary: "claude-code-cli",
    base_url: "http://127.0.0.1:8926/v1",
    temperature: 0,
    max_tokens: 512,
    max_turns: 4,
  },
  belt: {
    belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
    tool_filters: { calc: ["add", "mul"] },
  },
  framing: {
    inline: [
      "Cumplí literalmente el pedido.",
      "Primero llamá add y esperá su resultado.",
      "Sólo después, en otra llamada de herramienta, llamá mul usando aquel resultado.",
      "No llames ambas herramientas en paralelo.",
      "Tras el segundo resultado respondé exactamente RESULTADO: N, sin explicación.",
    ].join(" "),
  },
  rag: { enabled: false },
};

const jobs = [
  { a: 2, b: 3, factor: 4, expected: 20 },
  { a: 5, b: 7, factor: 3, expected: 36 },
  { a: 8, b: 1, factor: 6, expected: 54 },
];
const turnIds = jobs.map((_, index) => `tanda-d-reina-${Date.now()}-${index + 1}`);
const bodies = jobs.map((job, index) => {
  const prompt = [
    `Turno ${index + 1}.`,
    `Llamá calc.add con ${job.a} y ${job.b}.`,
    `Esperá el resultado; recién entonces llamá calc.mul con ese resultado y ${job.factor}.`,
    `Cerrá exactamente con RESULTADO: ${job.expected}.`,
  ].join(" ");
  return {
    recipe,
    prompt,
    turn_text: prompt,
    deadline_s: 240,
    lang: "es",
    client_turn_id: turnIds[index],
  };
});

console.log(`\n═══ SALA · PRUEBA REINA INSTALADA :${PORT} ═══`);
const health = await api("GET", "/health");
if (!check(health.status === 200 && health.json?.proceso?.build === "public",
  "el sidecar instalado responde public", `http ${health.status}`)) process.exit(1);

const session = await api("POST", "/v1/auth/local", { device_id: `sala-reina-${Date.now()}` });
token = session.json?.session_token || "";
const userId = session.json?.id || "";
if (!check(session.status === 200 && token && userId, "sesión local real")) process.exit(1);

const created = await api("POST", "/v1/chats", {});
const chatId = created.json?.id || created.json?.chat?.id || "";
if (!check((created.status === 200 || created.status === 201) && chatId,
  "hilo real creado", `chat=${chatId || "ausente"}`)) process.exit(1);

const runs = [];
for (let index = 0; index < bodies.length; index += 1) {
  const body = { ...bodies[index], user_id: userId, chat_id: chatId };
  const result = await api("POST", "/v1/puppets/run", body);
  const record = result.json?.record || {};
  const models = record.model_route || [];
  const tools = record.tool_calls || [];
  const expected = jobs[index].expected;
  runs.push({ result, record, body });
  check(result.status === 201 && result.json?.ok === true,
    `turno ${index + 1} cierra una sola vez`, `http ${result.status} · ${result.wall_ms} ms`);
  check(models.length === 3,
    `turno ${index + 1}: exactamente 3 llamadas encadenadas`, `model_route=${models.length}`);
  check(tools.length === 2 && tools[0]?.tool === "add" && tools[1]?.tool === "mul",
    `turno ${index + 1}: add → mul, en orden`,
    `tools=${tools.map((tool) => tool.tool).join("→") || "ninguna"}`);
  check(new RegExp(`RESULTADO:\\s*${expected}\\b`).test(String(result.json?.answer || "")),
    `turno ${index + 1}: respuesta no vacía y correcta`, JSON.stringify(result.json?.answer || ""));
}

const transcript = await api("GET", `/v1/chats/${encodeURIComponent(chatId)}`);
const messages = transcript.json?.messages || [];
check(transcript.status === 200 && messages.length === 6,
  "transcript: 3 humanos + 3 agentes", `mensajes=${messages.length}`);
for (let index = 0; index < turnIds.length; index += 1) {
  const own = messages.filter((message) => message.client_turn_id === turnIds[index]);
  check(own.length === 2 && own[0]?.role === "user" && own[1]?.role === "agent"
      && String(own[1]?.content || "").trim(),
    `turno ${index + 1}: un humano y un agente, sin duplicados`,
    `roles=${own.map((message) => message.role).join(",") || "ninguno"}`);
}

const replay = await api("POST", "/v1/puppets/run", {
  ...runs[0].body,
  user_id: userId,
  chat_id: chatId,
});
check(replay.status === 201 && replay.json?.idempotent_replay === true
    && replay.json?.run_id === runs[0].result.json?.run_id
    && replay.json?.answer === runs[0].result.json?.answer,
  "reintento cerrado devuelve replay exacto sin segundo run",
  `http ${replay.status} · replay=${String(replay.json?.idempotent_replay)}`);
const afterReplay = await api("GET", `/v1/chats/${encodeURIComponent(chatId)}`);
check((afterReplay.json?.messages || []).length === 6,
  "el replay no duplica el transcript", `mensajes=${(afterReplay.json?.messages || []).length}`);

const resumeRecipe = {
  ...recipe,
  meta: { ...recipe.meta, name: "Sala reina retoma" },
  belt: {
    belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
    tool_filters: { calc: ["add"] },
  },
  framing: {
    inline: "Usá el historial del hilo. Respondé sólo PRIMERO: N con el resultado del primer turno.",
  },
  model: { ...recipe.model, max_turns: 3 },
};
const resumeTurn = `tanda-d-retoma-${Date.now()}`;
const resumed = await api("POST", "/v1/puppets/run", {
  recipe: resumeRecipe,
  prompt: "Retomá el hilo: ¿cuál fue el RESULTADO del primer turno?",
  turn_text: "Retomá el hilo: ¿cuál fue el RESULTADO del primer turno?",
  user_id: userId,
  chat_id: chatId,
  client_turn_id: resumeTurn,
  deadline_s: 180,
  lang: "es",
});
check(resumed.status === 201 && resumed.json?.ok === true && /PRIMERO:\s*20\b/.test(String(resumed.json?.answer || "")),
  "retoma: el mismo hilo recuerda el primer resultado",
  `http ${resumed.status} · ${JSON.stringify(resumed.json?.answer || resumed.json?.detail || "")}`);
const afterResume = await api("GET", `/v1/chats/${encodeURIComponent(chatId)}`);
const resumeMessages = (afterResume.json?.messages || []).filter(
  (message) => message.client_turn_id === resumeTurn,
);
check(resumeMessages.length === 2 && resumeMessages[0]?.role === "user"
    && resumeMessages[1]?.role === "agent",
  "retoma persistida como un nuevo turno completo", `mensajes=${resumeMessages.length}`);

console.log(`\n═══ ${fail ? "ROJO" : "VERDE"} — ${pass} PASS · ${fail} FAIL ═══`);
if (failures.length) failures.forEach((name) => console.log(`  ✗ ${name}`));
process.exit(fail ? 1 : 0);
