/* Focused Slice D contract: Cuarto and Sala must compile and reopen the same controls. */
import assert from "node:assert/strict";
import {
  applyRecipeControls,
  controlsFromRecipe,
  maxTurnsForSteps,
  splitDetailFraming,
} from "./cuarto.controls.js";

const base = {
  schema_version: "v1",
  meta: { name: "Control fixture", nicho: "test" },
  model: {
    primary: "claude-code-cli",
    fallback: null,
    base_url: "http://127.0.0.1:8926/v1",
    temperature: 0,
    max_tokens: 700,
    max_turns: 16,
    alias: "claude_cli",
    brain_provider: "claude_cli",
    cli_model: "sonnet",
    effort: "high",
  },
  belt: { belt_ref: "fixture", tool_filters: { calc: ["add"] } },
  framing: { inline: "Responde con detalle y pasos explícitos. Mantén citas verificables." },
  rag: { enabled: false },
  keys: {},
  gates: { money_touch: "needs_ok", send: "needs_ok" },
  canvas: { nucleos: [{ model: "claude_cli" }] },
};

const legacy = controlsFromRecipe(base);
assert.deepEqual(legacy, {
  model: "claude_cli",
  cliModel: "sonnet",
  effort: "high",
  detail: "detallado",
  instructions: "Mantén citas verificables.",
  steps: "full",
  maxTurns: 16,
});

assert.deepEqual(
  splitDetailFraming("Responde breve y directo. Conserva el formato."),
  { detail: "breve", instructions: "Conserva el formato." },
);
assert.equal(maxTurnsForSteps("1"), 2);
assert.equal(maxTurnsForSteps("auto"), 8);
assert.equal(maxTurnsForSteps("full"), 16);

const changed = applyRecipeControls(base, {
  model: "codex_cli",
  cliModel: "gpt-5.1-codex-max",
  effort: "max",
  detail: "breve",
  steps: "1",
});
assert.equal(changed.model.primary, "codex-cli");
assert.equal(changed.model.brain_provider, "codex_cli");
assert.equal(changed.model.cli_model, "gpt-5.1-codex-max");
assert.equal(changed.model.effort, "max");
assert.equal(changed.model.max_turns, 2);
assert.equal(changed.framing.inline, "Responde breve y directo. Mantén citas verificables.");
assert.equal(changed.canvas.nucleos[0].detail, "breve");
assert.equal(changed.canvas.nucleos[0].steps, "1");
assert.equal(changed.canvas.nucleos[0].instructions, "Mantén citas verificables.");
assert.deepEqual(controlsFromRecipe(changed), {
  model: "codex_cli",
  cliModel: "gpt-5.1-codex-max",
  effort: "max",
  detail: "breve",
  instructions: "Mantén citas verificables.",
  steps: "1",
  maxTurns: 2,
});

const customTurns = structuredClone(base);
customTurns.model.max_turns = 12;
customTurns.canvas.nucleos[0].steps = "custom";
customTurns.canvas.nucleos[0].detail = "normal";
customTurns.canvas.nucleos[0].instructions = "No cambies esta instrucción.";
customTurns.framing.inline = "No cambies esta instrucción.";
const customRoundTrip = applyRecipeControls(customTurns, controlsFromRecipe(customTurns));
assert.equal(customRoundTrip.model.max_turns, 12);
assert.equal(customRoundTrip.framing.inline, "No cambies esta instrucción.");

const nonCli = applyRecipeControls(changed, { model: "opus", effort: "max", cliModel: "sonnet" });
assert.equal(nonCli.model.alias, "brain");
assert.equal("brain_provider" in nonCli.model, false);
assert.equal("cli_model" in nonCli.model, false);
assert.equal("effort" in nonCli.model, false);

const staleCanvas = structuredClone(base);
staleCanvas.canvas.nucleos[0] = {
  model: "opus", detail: "breve", steps: "1", instructions: "metadata vieja",
};
const runtimeWins = controlsFromRecipe(staleCanvas);
assert.equal(runtimeWins.model, "claude_cli");
assert.equal(runtimeWins.detail, "detallado");
assert.equal(runtimeWins.instructions, "Mantén citas verificables.");
assert.equal(runtimeWins.steps, "full");

const customRuntime = structuredClone(base);
customRuntime.model = { ...customRuntime.model, primary: "vendor/new-model", alias: null, brain_provider: null };
customRuntime.canvas.nucleos[0].model = "opus";
assert.equal(controlsFromRecipe(customRuntime).model, null);

assert.equal(base.model.primary, "claude-code-cli", "the source recipe is never mutated");
console.log("verify_recipe_controls: 29 assertions green");
