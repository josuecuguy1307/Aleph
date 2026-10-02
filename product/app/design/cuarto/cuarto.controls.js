/* cuarto.controls.js - shared run-control contract for El Cuarto and La Sala.
 *
 * The recipe remains the execution source of truth. Canvas metadata stores the human
 * control choices so a saved recipe can be reopened without reverse-engineering or
 * overwriting custom framing.
 */
import { compileModel, modelIdForRecipe } from "./cuarto.models.js";

export const DETAIL_FRAMING = Object.freeze({
  breve: "Responde breve y directo.",
  detallado: "Responde con detalle y pasos explícitos.",
});

export const DETAIL_OPTIONS = Object.freeze([
  { id: "breve", label: "Breve" },
  { id: "normal", label: "Normal" },
  { id: "detallado", label: "Detallado" },
]);

export const STEP_OPTIONS = Object.freeze([
  { id: "1", label: "Corto", maxTurns: 2 },
  { id: "auto", label: "Normal", maxTurns: 8 },
  { id: "full", label: "Exhaustivo", maxTurns: 16 },
]);

export const EFFORT_OPTIONS = Object.freeze([
  { id: "", label: "Default del CLI" },
  { id: "low", label: "Bajo" },
  { id: "medium", label: "Medio" },
  { id: "high", label: "Alto" },
  { id: "max", label: "Máximo" },
  { id: "auto", label: "Auto" },
]);

const clone = (value) => JSON.parse(JSON.stringify(value || {}));

export function maxTurnsForSteps(steps, fallback = 8) {
  const hit = STEP_OPTIONS.find((item) => item.id === steps);
  return hit ? hit.maxTurns : (Number.isInteger(fallback) && fallback > 0 ? fallback : 8);
}

export function stepsForMaxTurns(maxTurns) {
  const n = Number(maxTurns);
  const hit = STEP_OPTIONS.find((item) => item.maxTurns === n);
  return hit ? hit.id : "custom";
}

export function splitDetailFraming(inline) {
  let rest = String(inline || "").trim();
  let detail = "normal";
  for (const [id, prefix] of Object.entries(DETAIL_FRAMING)) {
    if (rest === prefix || rest.startsWith(prefix + " ")) {
      detail = id;
      rest = rest.slice(prefix.length).trim();
      break;
    }
  }
  return { detail, instructions: rest };
}

export function composeFraming(detail, instructions) {
  return [DETAIL_FRAMING[detail] || "", String(instructions || "").trim()]
    .filter(Boolean).join(" ");
}

function nucleusOf(recipe) {
  return recipe && recipe.canvas && Array.isArray(recipe.canvas.nucleos)
    ? (recipe.canvas.nucleos[0] || {}) : {};
}

export function controlsFromRecipe(recipe) {
  recipe = recipe || {};
  const model = recipe.model || {};
  const nucleus = nucleusOf(recipe);
  const inline = String((recipe.framing || {}).inline || "").trim();
  const parsed = splitDetailFraming(inline);
  const maxTurns = Number.isInteger(model.max_turns) && model.max_turns > 0 ? model.max_turns : 8;
  const storedDetail = ["breve", "normal", "detallado"].includes(nucleus.detail)
    ? nucleus.detail : null;
  const storedInstructions = nucleus.instructions != null ? String(nucleus.instructions) : null;
  // Canvas metadata disambiguates custom text that starts like a generated Detail prefix,
  // but executable framing wins whenever the two disagree.
  const metadataMatchesFraming = storedDetail && storedInstructions != null
    && composeFraming(storedDetail, storedInstructions) === inline;
  const detail = metadataMatchesFraming ? storedDetail : parsed.detail;
  const instructions = metadataMatchesFraming ? storedInstructions : parsed.instructions;
  const inferredSteps = stepsForMaxTurns(maxTurns);
  const storedSteps = ["1", "auto", "full", "custom"].includes(nucleus.steps)
    ? nucleus.steps : null;
  const steps = storedSteps === "custom"
    ? storedSteps
    : (storedSteps && maxTurnsForSteps(storedSteps) === maxTurns ? storedSteps : inferredSteps);
  const byokProvider = String(model.byok_ref || "").replace(/^keys:/, "");
  const byok = byokProvider && model.primary && model.base_url
    ? { provider: byokProvider, model: String(model.primary), baseUrl: String(model.base_url) }
    : null;
  const modelId = byok ? "byok" : modelIdForRecipe(recipe);
  const isCli = (window.AlephBrain && window.AlephBrain.isCliId)
    ? window.AlephBrain.isCliId(model.brain_provider)
    : (model.brain_provider === "claude_cli" || model.brain_provider === "codex_cli"); /* E1-FALLBACK */
  return {
    model: modelId,
    byok,
    cliModel: isCli ? String(model.cli_model || "") : "",
    effort: isCli ? String(model.effort || "") : "",
    detail,
    instructions,
    steps,
    maxTurns,
  };
}

function writeNucleusControls(recipe, controls) {
  recipe.canvas = recipe.canvas || {};
  recipe.canvas.nucleos = Array.isArray(recipe.canvas.nucleos) ? recipe.canvas.nucleos : [];
  const nucleus = { ...(recipe.canvas.nucleos[0] || {}) };
  if (controls.model) nucleus.model = controls.model;
  nucleus.detail = controls.detail || "normal";
  nucleus.steps = controls.steps || stepsForMaxTurns(controls.maxTurns);
  nucleus.instructions = String(controls.instructions || "");
  recipe.canvas.nucleos[0] = nucleus;
}

/** Return a cloned recipe with the shared controls folded into the real runtime fields. */
export function applyRecipeControls(recipe, controls = {}) {
  const out = clone(recipe);
  const current = controlsFromRecipe(out);
  const next = { ...current, ...controls };
  next.maxTurns = maxTurnsForSteps(next.steps, next.maxTurns);
  next.detail = ["breve", "normal", "detallado"].includes(next.detail) ? next.detail : "normal";
  next.instructions = String(next.instructions || "");

  const oldModel = { ...(out.model || {}) };
  if (next.model) {
    const compiled = compileModel(next.model, {
      temperature: oldModel.temperature,
      max_tokens: oldModel.max_tokens,
      max_turns: next.maxTurns,
      cli_model: next.cliModel,
      effort: next.effort,
      byok: next.byok,
    });
    out.model = { ...oldModel, ...compiled };
    if (!compiled.byok_ref) delete out.model.byok_ref;
    if (!compiled.brain_provider) {
      delete out.model.brain_provider;
      delete out.model.cli_model;
      delete out.model.effort;
    }
  } else {
    out.model = { ...oldModel, max_turns: next.maxTurns };
  }

  out.framing = { ...(out.framing || {}), inline: composeFraming(next.detail, next.instructions) };
  writeNucleusControls(out, next);
  return out;
}
