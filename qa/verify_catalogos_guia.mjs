/* Vara aislada · DOS CATÁLOGOS del Guía.
 * Correr:
 *   node qa/verify_catalogos_guia.mjs
 */
import assert from "node:assert/strict";
import {
  routeCatalogIntent, catalogQueryFromRequest, buscarCatalogoLocal, buscarRegistro, CLEAN_CATALOG_KEYS,
} from "../product/app/design/cuarto/cuarto.catalog.tools.js";
import { createGuide } from "../product/app/design/cuarto/cuarto.guide.js";

const limpio = {
  id: "com.acme/mail", nombre: "Correo", tipo: "remoto",
  descripcion_1linea: { es: "Lee correo.", en: "Reads email." },
  official: true, confianza: 0.91,
  checklist: { es: ["Revisá permisos."], en: ["Review permissions."] },
  fuente: "https://registry.modelcontextprotocol.io/v0/servers?search=com.acme%2Fmail",
};

assert.equal(routeCatalogIntent("poneme las que ya tengo"), "local");
assert.equal(routeCatalogIntent("¿qué podría traer del registro?"), "registry");
assert.equal(routeCatalogIntent("mostrame conectores"), "ambiguous");
assert.equal(routeCatalogIntent("catálogo"), "ambiguous");
assert.equal(routeCatalogIntent("conectores"), "ambiguous");
assert.equal(routeCatalogIntent("mové la pieza de Gmail"), null);
assert.equal(routeCatalogIntent("¿qué es un MCP?"), null);
assert.equal(routeCatalogIntent("explicame lo que tenemos que hacer"), null);
assert.equal(routeCatalogIntent("decime lo que tenemos pendiente"), null);
assert.equal(routeCatalogIntent("show me what we have to do next"), null);
assert.equal(catalogQueryFromRequest("Buscá en el registro · mostrame conectores", "registry"), "conectores");

let localCalls = 0;
const localResult = await buscarCatalogoLocal("", {
  fetchImpl: async (url, init) => {
    localCalls++;
    assert.equal(url, "/v1/catalog/local?q=");
    assert.equal(init.method, "GET");
    return new Response(JSON.stringify({ items: [{ ...limpio, basura: "no viaja" }], total: 1 }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  },
});
assert.equal(localResult.ok, true);
assert.equal(localResult.items.length, 1);
assert.deepEqual(Object.keys(localResult.items[0]), CLEAN_CATALOG_KEYS);
const badSchema = await buscarCatalogoLocal("", {
  fetchImpl: async () => new Response(JSON.stringify({
    items: [{ ...limpio, checklist: ["forma vieja"] }],
  }), { status: 200, headers: { "Content-Type": "application/json" } }),
});
assert.deepEqual(badSchema.items, [], "la tool no afloja el schema compartido");

const sse = [
  { etapa: "leyendo" },
  { etapa: "limpiando" },
  { etapa: "clasificando" },
  { etapa: "veredicto", ok: true, agregadas: 1, entradas: [limpio] },
].map((data) => `data: ${JSON.stringify(data)}\n\n`).join("");
const stages = [];
let registryCalls = 0;
const registryResult = await buscarRegistro("correo", {
  locale: "es",
  onStage: (stage) => stages.push(stage),
  fetchImpl: async (url, init) => {
    registryCalls++;
    assert.equal(url, "/v1/catalog/ingest");
    assert.equal(init.method, "POST");
    assert.deepEqual(JSON.parse(init.body), { query: "correo", locale: "es" });
    return new Response(sse, { status: 200, headers: { "Content-Type": "text/event-stream" } });
  },
});
assert.equal(registryResult.ok, true);
assert.deepEqual(stages, ["leyendo", "limpiando", "clasificando", "veredicto"]);
assert.equal(registryResult.agregadas_al_local, 1);
assert.equal(registryResult.items.length, 1);

let localToolCalls = 0;
let registryToolCalls = 0;
let brainCalls = 0;
const host = {
  buscarCatalogoLocal: async (query) => { localToolCalls++; return { ok: true, query, items: [limpio] }; },
  buscarRegistro: async () => { registryToolCalls++; return { ok: true, items: [] }; },
  opciones: () => ({ ok: true }),
};
const guide = createGuide({
  host,
  brainCall: async ({ messages }) => {
    brainCalls++;
    const tool = messages.findLast((m) => m.role === "tool");
    if (brainCalls === 1) {
      assert.equal(tool.name, "buscar_catalogo_local");
      // Cerebro adversarial: intenta saltar de "lo que ya tenés" al registro.
      return { content: "", tool_calls: [{ id: "wrong-source", type: "function",
        function: { name: "buscar_registro", arguments: JSON.stringify({ query: "correo" }) } }] };
    }
    assert.equal(tool.name, "buscar_registro");
    assert.match(tool.content, /catálogo local; no se consulta el registro/);
    return { content: "Encontré lo que ya tenés.", tool_calls: [] };
  },
  toolTimeoutMs: 1000,
});
await guide.send("poneme las que ya tengo");
assert.equal(localToolCalls, 1, "el pedido local llama la tool local");
assert.equal(registryToolCalls, 0, "el pedido local JAMÁS llama la tool de registro");
assert.equal(brainCalls, 2);
assert.equal(guide.snapshotMessages().find((m) => m.role === "tool").name, "buscar_catalogo_local");

let explicitRegistryCalls = 0;
const fromRegistry = createGuide({
  host: {
    ...host,
    buscarRegistro: async (query) => { explicitRegistryCalls++; assert.equal(query, "gmail"); return { ok: true, items: [limpio] }; },
  },
  brainCall: async ({ messages }) => {
    assert.equal(messages.findLast((m) => m.role === "tool").name, "buscar_registro");
    return { content: "Consulté el registro.", tool_calls: [] };
  },
});
await fromRegistry.send("buscá en el registro Gmail");
assert.equal(explicitRegistryCalls, 1, "el pedido de registro llama la tool que dispara ingesta");

let optionArgs = null;
let ambiguousBrainCalls = 0;
const ambiguous = createGuide({
  host: {
    ...host,
    opciones: (name, args) => { assert.equal(name, "preguntar_opciones"); optionArgs = args; return { ok: true }; },
  },
  brainCall: async () => { ambiguousBrainCalls++; return { content: "no debe correr", tool_calls: [] }; },
});
const ambiguousResult = await ambiguous.send("mostrame conectores");
assert.equal(ambiguousResult.catalog_route, "ambiguous");
assert.equal(ambiguousBrainCalls, 0, "la duda termina con opciones; no adivina vía modelo");
assert.deepEqual(optionArgs.preguntas[0].opciones.map((o) => o.label), ["Mi catálogo", "El registro"]);

console.log("✅ DOS CATÁLOGOS · Guía: routing, endpoints, schema y etapas verificados");
console.log(`   pedido local: local tool=${localToolCalls} · registry tool=${registryToolCalls} (jamás)`);
console.log(`   transporte: local=${localCalls} · registro/SSE=${registryCalls} · tool registro explícita=${explicitRegistryCalls}`);
