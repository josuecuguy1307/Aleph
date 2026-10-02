import assert from "node:assert/strict";
import {
  compatibleRecipeV1SavePayload,
  rawModelUse,
  recipeV1ModelUse,
  recipeV1SavePayload,
} from "../product/app/design/model-use.js";

const recipe = {
  schema_version: "v1",
  model: {
    primary: "client-model",
    base_url: "https://client.invalid/v1",
    alias: "client",
    byok_ref: "keys:client",
    brain_provider: "managed",
    temperature: 0.2,
    max_tokens: 900,
    max_turns: 12,
    workers: { primary: "worker", base_url: "http://worker/v1" },
  },
  belt: { belt_ref: "belt", tool_filters: { calc: ["add"] } },
};

const saved = recipeV1SavePayload(recipe, "api:openai");
assert.equal(saved.model_selection_ref, "api:openai");
for (const key of ["primary", "base_url", "alias", "byok_ref", "brain_provider"])
  assert.equal(saved.config.model[key], undefined, `${key} no debe viajar`);
assert.equal(saved.config.model.temperature, 0.2);
assert.deepEqual(saved.config.model.workers, recipe.model.workers);
assert.equal(recipe.model.primary, "client-model", "el helper no muta la receta en pantalla");

const mixedVersion = await compatibleRecipeV1SavePayload(recipe, "api:openai", {
  fetchImpl: async () => ({ ok: false, status: 404 }),
});
assert.deepEqual(mixedVersion, { config: recipe, model_selection_ref: null });

const currentVersion = await compatibleRecipeV1SavePayload(recipe, "api:openai", {
  fetchImpl: async () => ({ ok: true, status: 200 }),
});
assert.equal(currentVersion.model_selection_ref, "api:openai");
assert.equal(currentVersion.config.model.base_url, undefined);

const raw = rawModelUse({
  workspaceId: "sala", callClass: "chat.raw", selectionRef: "api:openai",
  sessionId: "s", messages: [{ role: "user", content: "hola" }],
});
assert.equal(raw.context.agent_id, null);
assert.equal(raw.policy_ref, null);
assert.equal(raw.selection_scope, "session");

const agent = recipeV1ModelUse({
  recipe, agentId: "a", selectionRef: "api:openai",
  workspaceId: "cuarto", callClass: "agent.recipe.save",
});
assert.equal(agent.context.agent_id, "a");
assert.equal(agent.policy_ref, "recipe:v1:a");
assert.equal(JSON.stringify(agent).includes("client.invalid"), false);
assert.equal(JSON.stringify(agent).includes("keys:client"), false);

console.log("PASS model-use browser: ids-only + RAW + Recipe v1");
