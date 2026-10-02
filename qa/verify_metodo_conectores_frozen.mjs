#!/usr/bin/env node
/* Vara del producto FROZEN. El caller levanta SU sidecar bajo lockf y pasa
 * METODO_FROZEN_URL. :8320 es integración; :8312 reproduce la rama dueña.
 * Este archivo jamás spawnea :25374. */
import vm from "node:vm";
const BASE = process.env.METODO_FROZEN_URL || "http://127.0.0.1:8312";
const port = Number(new URL(BASE).port);
if (![8312, 8320].includes(port) || port === 25374) {
  console.error(`FAIL · esta vara exige :8312 o :8320; recibió :${port}`);
  process.exit(2);
}

let pass = 0, fail = 0;
function check(name, cond, detail = "") {
  if (cond) { pass++; console.log(`  PASS · ${name}`); }
  else { fail++; console.log(`  FAIL · ${name}${detail ? ` — ${detail}` : ""}`); }
}
async function api(method, route, body, token) {
  const r = await fetch(BASE + route, {
    method, headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  let data = null; try { data = await r.json(); } catch {}
  if (!r.ok) throw new Error(`${method} ${route} → ${r.status} ${JSON.stringify(data)}`);
  return data;
}

const health = await fetch(BASE + "/health");
check(`sidecar frozen propio responde en :${port}`, health.ok);
const user = await api("POST", "/v1/auth/local");
const token = user.session_token;
const recipe = {
  schema_version: "v1",
  meta: { name: "Vara Método", nicho: "general" },
  model: { primary: "openai/gpt-oss-120b",
    base_url: "https://api.groq.com/openai/v1", temperature: 0,
    max_tokens: 1024, max_turns: 6 },
  belt: { belt_refs: ["platform/assembler/fixtures/belt-calc.mcp.json"],
    tool_filters: { calc: ["add"] } },
  framing: { inline: "vara" }, rag: { enabled: false },
  gates: { money_touch: "needs_ok", send: "needs_ok" },
};
const puppet = await api("POST", "/v1/puppets", {
  owner_id: user.id, name: "Vara Método", nicho: "general", config: recipe,
}, token);
const green = await api("POST", "/v1/methods", {
  name: "Cierre mensual verde",
  steps: [{ text: "Cerrar el mes con evidencia" }], requires: [],
}, token);
const yellow = await api("POST", "/v1/methods", {
  name: "Investigación cuántica amarilla",
  steps: [{ text: "Investigar teletransportación" }],
  requires: ["teletransportación cuántica"],
}, token);
// Remate de integración E1×5a: no usa `capabilities` de una fixture.
// Requiere cuatro permissions[] canónicas de 5a y equipa sólo la card Gmail
// declarada por el belt productivo, que cubre exactamente las primeras dos.
const fourByTwoRecipe = {
  ...recipe,
  meta: { name: "Vara 5a cuatro por dos", nicho: "general" },
  belt: {
    belt_refs: ["catalog/templates/ingenieria/belt-ingenieria.mcp.json"],
    tool_filters: { gmail: ["create_draft"] },
  },
};
const fourByTwoPuppet = await api("POST", "/v1/puppets", {
  owner_id: user.id, name: "Vara 5a cuatro por dos", nicho: "general",
  config: fourByTwoRecipe,
}, token);
check("frozen conserva el belt productivo del caso 4→2",
  fourByTwoPuppet?.config?.belt?.tool_filters?.gmail?.includes("create_draft"),
  JSON.stringify(fourByTwoPuppet));
const fourByTwo = await api("POST", "/v1/methods", {
  name: "Documentos y correo 5a",
  steps: [{ text: "Preparar documentos y borradores" }],
  requires: ["leer correo", "crear borradores", "leer archivos", "crear archivos"],
}, token);
await api("POST", `/v1/puppets/${fourByTwoPuppet.id}/methods`,
  { method_id: fourByTwo.id }, token);
const fourByTwoEquipped = await api(
  "GET", `/v1/puppets/${fourByTwoPuppet.id}/methods`, undefined, token
);
const fourByTwoState = fourByTwoEquipped.methods.find((m) => m.id === fourByTwo.id);
check("frozen 5a: método pide 4 / belt cubre 2 → 🟡",
  fourByTwoState?.equipment?.estado === "huecos"
  && fourByTwoState.equipment.cubiertas.length === 2,
  JSON.stringify(fourByTwoState?.equipment));
check("frozen 5a nombra LOS 2 faltantes correctos",
  JSON.stringify(fourByTwoState?.equipment?.faltantes)
    === JSON.stringify(["leer archivos", "crear archivos"]),
  JSON.stringify(fourByTwoState?.equipment));
check("frozen 5a da [Traer] para ambos faltantes",
  fourByTwoState?.equipment?.resoluciones?.length === 2
  && fourByTwoState.equipment.resoluciones.every((r) => r.camino === "registro"),
  JSON.stringify(fourByTwoState?.equipment));
await api("POST", `/v1/puppets/${puppet.id}/methods`, { method_id: green.id }, token);
await api("POST", `/v1/puppets/${puppet.id}/methods`, { method_id: yellow.id }, token);
const equipped = await api("GET", `/v1/puppets/${puppet.id}/methods`, undefined, token);
const eg = equipped.methods.find((m) => m.id === green.id);
const ey = equipped.methods.find((m) => m.id === yellow.id);
check("frozen persiste semáforo 🟢", eg?.equipment?.estado === "completo",
  JSON.stringify(eg?.equipment));
check("frozen deja capacidad inventada 🟡", ey?.equipment?.estado === "huecos"
  && ey.equipment.faltantes[0] === "teletransportación cuántica",
  JSON.stringify(ey?.equipment));
const mg = await api("POST", "/v1/methods/match",
  { puppet_id: puppet.id, prompt: "cierre mensual verde" }, token);
const my = await api("POST", "/v1/methods/match",
  { puppet_id: puppet.id, prompt: "investigación cuántica amarilla" }, token);
check("frozen propone el 🟢", mg.match?.method_id === green.id, JSON.stringify(mg));
check("frozen gatea el 🟡", my.match === null, JSON.stringify(my));

const sala = await (await fetch(BASE + "/sala/sala.html")).text();
const eqStart = sala.indexOf("async function metodoEquipped()");
const eqEnd = sala.indexOf("// §4·modo 2", eqStart);
const maybeStart = sala.indexOf("function metodoMaybePropose", eqEnd);
const maybeEnd = sala.indexOf("function metodoContinue", maybeStart);
check("frozen sirve metodoEquipped async", eqStart > 0 && eqEnd > eqStart);
check("frozen sirve metodoMaybePropose con await",
  sala.slice(maybeStart, maybeEnd).includes("var eq=await metodoEquipped();"));

async function runSalaFunctions(equipment, match, delayMs = 0) {
  const cards = [], continued = [];
  const sandbox = {
    ST: { puppetId: "p-frozen", busy: false, metodo: {
      equipped: undefined, pending: null, offered: {}, bypass: false,
      lastDecision: null,
    } },
    authHeaders: (h) => h || {},
    fetch: async (url) => {
      if (String(url).includes("/puppets/")) {
        await new Promise((resolve) => setTimeout(resolve, delayMs));
        return { ok: true, json: async () => ({ methods: equipment }) };
      }
      return { ok: true, json: async () => ({ match }) };
    },
    metodoContinue: (text) => continued.push(text),
    metodoCard: (text, value) => cards.push({ text, value }),
    metodoNeutralize: () => {},
    metodoNote: () => {},
    setTimeout, clearTimeout, encodeURIComponent, JSON, Promise,
  };
  vm.createContext(sandbox);
  vm.runInContext(sala.slice(eqStart, eqEnd) + "\n"
    + sala.slice(maybeStart, maybeEnd), sandbox);
  const deferred = sandbox.metodoMaybePropose("cierre mensual verde");
  await new Promise((resolve) => setTimeout(resolve, delayMs + 100));
  return { deferred, cards, continued };
}

const firstTurn = await runSalaFunctions([{
  id: green.id, name: green.name, equipment: { estado: "completo" },
}], { method_id: green.id, name: green.name }, 350);
check("primer turno queda diferido durante fetch demorado", firstTurn.deferred === true);
check("PRIMER turno tras reload limpio → card aparece",
  firstTurn.cards[0]?.value?.method_id === green.id, JSON.stringify(firstTurn));
const gatedJs = await runSalaFunctions([{
  id: yellow.id, name: yellow.name, equipment: { estado: "huecos" },
}], { method_id: yellow.id, name: yellow.name });
check("gate JS: método 🟡 no pinta card", gatedJs.cards.length === 0);
// Calibración roja: neutralizar SU knob al vuelo (estado completo), mismo método/match.
const neutralizedJs = await runSalaFunctions([{
  id: yellow.id, name: yellow.name, equipment: { estado: "completo" },
}], { method_id: yellow.id, name: yellow.name });
check("ROJO: gate JS neutralizado → card del 🟡 aparece",
  neutralizedJs.cards[0]?.value?.method_id === yellow.id);

const metodoSource = await (await fetch(BASE + "/metodo/metodo.html")).text();
check("redirección frozen aterriza en Métodos para ese agente",
  metodoSource.includes("Métodos de este agente")
  && metodoSource.includes('puppetId: Q.get("puppet")'));
check("landing frozen ofrece equipar/quitar desde la biblioteca",
  metodoSource.includes("toggleEquip(m)") && metodoSource.includes("met-equip"));

const cuartoSource = await (await fetch(BASE + "/cuarto/cuarto.pixi.html")).text();
check("frozen contiene widget anidado vacío opt-in",
  cuartoSource.includes("Este agente no usa métodos todavía")
  && cuartoSource.includes("Ver la biblioteca")
  && cuartoSource.includes("Traer otro de la biblioteca"));
check("frozen sólo carga el widget al abrir su osec",
  cuartoSource.includes('if (!closed && sec.querySelector("[data-methodpanel]"))'));

console.log(`\n${pass} PASS / ${fail} FAIL`);
process.exit(fail ? 1 : 0);
