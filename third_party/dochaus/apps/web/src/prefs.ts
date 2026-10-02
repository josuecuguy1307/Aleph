// Per-browser UI preferences (Settings → Approvals / Appearance / Matter
// defaults). localStorage, not engine config, because these shape how THIS
// browser presents and gates the engine — the engine has no notion of them.
// Drafting preferences are different: they steer the model, so they live on the
// engine as an instructions file (see api/ingest.ts getPreferences).
export type Prefs = {
  textSize: "compact" | "standard" | "large"
  // Auto-approve the engine's permission asks for redline/tracked-change
  // proposals. Safe to automate: the tools only record pending tracked changes
  // the lawyer still accepts or rejects in the document viewer.
  autoApproveRedlines: boolean
  // Auto-approve creating new documents and templates (never edits to existing
  // ones — those keep asking).
  autoApproveDrafting: boolean
  // Jurisdiction codes prefilled on the new-matter form.
  defaultJurisdictions: string[]
}

export const DEFAULT_PREFS: Prefs = {
  textSize: "standard",
  autoApproveRedlines: false,
  autoApproveDrafting: false,
  defaultJurisdictions: [],
}

const KEY = "dochaus.prefs"

export function loadPrefs(): Prefs {
  try {
    return { ...DEFAULT_PREFS, ...(JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Prefs>) }
  } catch {
    return DEFAULT_PREFS
  }
}

export function savePrefs(patch: Partial<Prefs>): Prefs {
  const next = { ...loadPrefs(), ...patch }
  localStorage.setItem(KEY, JSON.stringify(next))
  applyAppearance(next)
  return next
}

// Reflect text size onto <html> as the data attribute the stylesheet keys off
// ([data-text] scales the UI).
export function applyAppearance(prefs: Prefs = loadPrefs()) {
  document.documentElement.dataset.text = prefs.textSize
}

// Which permission asks each auto-approve toggle covers. word-integration
// (direct document edits) is deliberately absent — it always asks.
const REDLINE_PERMISSIONS = new Set(["tracked-changes", "redline"])
const DRAFT_PERMISSIONS = new Set(["draft-document", "create-template"])

export function autoApproved(permission: string): boolean {
  const prefs = loadPrefs()
  if (REDLINE_PERMISSIONS.has(permission)) return prefs.autoApproveRedlines
  if (DRAFT_PERMISSIONS.has(permission)) return prefs.autoApproveDrafting
  return false
}
