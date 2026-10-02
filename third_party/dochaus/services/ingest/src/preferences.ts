import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { WORKSPACE_ROOT } from "./matter"

// Firm-wide drafting preferences set in the web settings. They steer every
// assistant, so they live on the engine as a standing instructions file:
// dochaus/opencode.json lists {env:WORKSPACE_ROOT}/.preferences/drafting.md in
// config.instructions, and the engine re-reads that file on every turn — so a
// save here applies from the next reply, no restart. The JSON beside it is the
// structured source the settings form round-trips; the markdown is rendered
// from it and never edited directly.
const PREFS_DIR = () => path.join(WORKSPACE_ROOT, ".preferences")
const JSON_FILE = () => path.join(PREFS_DIR(), "preferences.json")
const INSTRUCTIONS_FILE = () => path.join(PREFS_DIR(), "drafting.md")

export type DraftingPreferences = {
  attorney: string
  firm: string
  posture: "client-favorable" | "balanced" | "conservative"
  formality: "formal" | "plain"
  detail: "concise" | "detailed"
  // "plan-first" makes assistants inventory the source documents, spot issues,
  // research, and write an action plan before producing or revising a document.
  // Slower and costs more model time; catches more.
  process: "plan-first" | "standard"
  dateFormat: "month-day-year" | "day-month-year" | "iso"
  numberStyle: "words-and-numerals" | "numerals"
  houseStyle: string
  // Enforced by the legal plugin's webfetch fence (dochaus/lib/research.ts),
  // not rendered into drafting.md: "official" limits web research to official
  // primary legal sources; "open" allows the whole web.
  webResearch: "official" | "open"
  // Exa web-search key for citation discovery (dochaus/tool/web-search.ts reads
  // it from preferences.json per call). Never rendered into drafting.md — the
  // key must not enter the model's context.
  searchApiKey: string
  // Extra hosts the firm trusts as primary sources, on top of the built-in
  // official list (dochaus/lib/research.ts). Enforced by the webfetch fence,
  // not rendered into drafting.md. Bare hostnames, matched as host or subdomain.
  approvedSources: string[]
}

export const DEFAULT_DRAFTING: DraftingPreferences = {
  attorney: "",
  firm: "",
  posture: "balanced",
  formality: "formal",
  detail: "concise",
  process: "plan-first",
  dateFormat: "month-day-year",
  numberStyle: "words-and-numerals",
  houseStyle: "",
  webResearch: "official",
  searchApiKey: "",
  approvedSources: [],
}

export function readDraftingPreferences(): DraftingPreferences {
  if (!existsSync(JSON_FILE())) return DEFAULT_DRAFTING
  return { ...DEFAULT_DRAFTING, ...(JSON.parse(readFileSync(JSON_FILE(), "utf8")) as Partial<DraftingPreferences>) }
}

export function writeDraftingPreferences(input: DraftingPreferences): DraftingPreferences {
  const prefs = { ...DEFAULT_DRAFTING, ...input }
  mkdirSync(PREFS_DIR(), { recursive: true })
  writeFileSync(JSON_FILE(), JSON.stringify(prefs, null, 2) + "\n")
  writeFileSync(INSTRUCTIONS_FILE(), renderInstructions(prefs))
  return prefs
}

const POSTURE: Record<DraftingPreferences["posture"], string> = {
  "client-favorable":
    "Favor the client's position: protect the client's interests and push obligations, risk, and discretion to the counterparty where reasonably defensible.",
  balanced: "Draft balanced, market-standard positions that a counterparty would recognize as fair.",
  conservative:
    "Draft conservatively: minimize the client's risk exposure and prefer well-tested market-standard language over novel or aggressive positions.",
}

const FORMALITY: Record<DraftingPreferences["formality"], string> = {
  formal: "Use formal legal drafting style throughout.",
  plain:
    "Prefer plain-language drafting: short sentences, minimal legalese, and defined terms only where they add real precision.",
}

const DETAIL: Record<DraftingPreferences["detail"], string> = {
  concise: "Keep explanations concise: lead with the conclusion, then a brief rationale.",
  detailed: "Explain your reasoning in detail, including the risks you considered and the alternatives you rejected.",
}

const DATES: Record<DraftingPreferences["dateFormat"], string> = {
  "month-day-year": 'Write dates in the form "June 11, 2026".',
  "day-month-year": 'Write dates in the form "11 June 2026".',
  iso: 'Write dates in ISO form, "2026-06-11".',
}

const NUMBERS: Record<DraftingPreferences["numberStyle"], string> = {
  "words-and-numerals": 'In operative contract text, write numbers as words followed by numerals: "thirty (30) days".',
  numerals: 'Write numbers as plain numerals: "30 days".',
}

const PLAN_FIRST = [
  "<plan_first_drafting>",
  "The lawyer has enabled plan-first drafting. It applies whenever you produce or revise a document (drafting, redlining, marking up); it does not apply to questions, summaries, or review-only work. Work in four explicit phases, each shown in the conversation:",
  "1. Inventory. Read every source document in full, not just search snippets. Produce a facts table (every party, individual, amount, percentage, date, duration, plan name, classification) and a provision inventory (every section and term of the controlling documents).",
  "2. Issue spotting and research. Assess EVERY provision in the inventory against the governing jurisdiction's law and the controlling documents — not only the provisions that look unusual; a defect you already fixed in one clause often recurs in another. Verify that every named institution, statute, and benefit plan actually exists. Check the controlling rules against current official sources — fetch the statute or regulation text with the web research tools rather than citing it from memory; where you can spawn subagents, use the legal-reviewer (which has web access) for this research.",
  "3. Action plan. For each provision, decide: keep, modify (state how), remove, or flag. Every modify, remove, and flag decision must also appear in the cover memo or report — including issues you spotted but deliberately left for the client. List the open items.",
  "4. Execute and verify. Produce the document from the plan. Then read the result back and walk the action plan item by item, confirming each decision landed; fix anything that did not before reporting.",
  "An empty matter does not skip the phases: the facts table comes from the conversation, and the issue spotting covers the standard provisions of the document type under the governing law.",
  "When drafting from a template whose body you cannot read before the draft call, the phases still come first: research the governing jurisdiction's constraints on the document type before drafting, plan every placeholder and optional-clause decision, then draft — and phase 4's read-back is where each template clause you could not see gets the phase-2 assessment, with defects fixed by redline before you report.",
  "Do not skip or merge phases, and do not start the document until the action plan is complete.",
  "Scale the phases to the task. New work product and revisions that touch several clauses get all four phases. A bounded edit the lawyer has fully specified — one clause, stated change — needs only the relevant slice: confirm the governing law's constraint on that clause, make the change, read it back. When in doubt, run the full phases.",
  "Plan once per conversation. When an action plan already exists in this conversation, a follow-up refinement updates that plan's decisions and runs the read-back on what changed; it does not restart the inventory.",
  "</plan_first_drafting>",
].join("\n")

function renderInstructions(prefs: DraftingPreferences) {
  const who = prefs.attorney
    ? [`Documents are prepared by ${prefs.attorney}${prefs.firm ? ` of ${prefs.firm}` : ""}.`]
    : prefs.firm
      ? [`Documents are prepared by ${prefs.firm}.`]
      : []
  const house = prefs.houseStyle.trim()
  return [
    "# Drafting preferences",
    "",
    "<drafting_preferences>",
    "The lawyer using doc.haus has set these firm-wide preferences. Apply them whenever you draft, edit, or propose changes to a document, and when you explain your work.",
    ...who,
    `- ${POSTURE[prefs.posture]}`,
    `- ${FORMALITY[prefs.formality]}`,
    `- ${DETAIL[prefs.detail]}`,
    `- ${DATES[prefs.dateFormat]}`,
    `- ${NUMBERS[prefs.numberStyle]}`,
    "</drafting_preferences>",
    ...(prefs.process === "plan-first" ? ["", PLAN_FIRST] : []),
    ...(house ? ["", "<house_style>", house, "</house_style>"] : []),
    "",
  ].join("\n")
}
