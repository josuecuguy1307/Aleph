import { existsSync, readFileSync } from "node:fs"
import path from "node:path"

// Web-research fence shared by the legal plugin. webfetch exists so agents can
// retrieve CURRENT statute and regulation text (the legal-research skill);
// by default it is fenced to official primary sources — every jurisdiction
// pack's <sources> site must be reachable through this list. The firm can
// widen the fence to the open web in Settings (webResearch: "open"), traded
// off knowingly: commentary is not authority, and every fetched page is one
// more injection surface.

// Official-source hosts, matched exactly or as any subdomain. Covers every
// jurisdiction pack doc.haus ships (dochaus/jurisdiction/*/prompt.md sources).
const HOSTS = [
  "law.cornell.edu", // US federal fallback (Cornell LII)
  "courtlistener.com", // US case law
  "legislation.gov.uk", // EW / SCT / NIR
  "eur-lex.europa.eu", // EU
  "gesetze-im-internet.de", // DE
  "wetten.overheid.nl", // NL
  "fedlex.admin.ch", // CH
  "irishstatutebook.ie", // IE
  "indiacode.nic.in", // IN
  "ontario.ca", // CA-ON (ontario.ca/laws)
  "leg.state.fl.us", // US-FL (Online Sunshine)
  "gov.za", // ZA
  "difc.ae", // AE (DIFC publishes its own laws)
]

// Official public suffixes — any host under these is government-operated.
const SUFFIXES = [
  ".gov", // US federal and state legislatures
  ".gov.uk",
  ".europa.eu",
  ".gc.ca", // Canada federal (laws-lois.justice.gc.ca)
  ".gov.bc.ca", // CA-BC (bclaws.gov.bc.ca)
  ".gouv.qc.ca", // CA-QC (legisquebec.gouv.qc.ca)
  ".gov.au", // AU federal and states
  ".govt.nz",
  ".gouv.fr", // FR (legifrance.gouv.fr)
  ".admin.ch",
  ".gov.sg", // SG (sso.agc.gov.sg)
  ".gov.hk", // HK (elegislation.gov.hk)
  ".gov.za",
  ".gov.ae",
  ".nic.in",
]

export function isOfficialSource(url: string) {
  const host = new URL(url).hostname
  if (HOSTS.some((h) => host === h || host.endsWith("." + h)) || SUFFIXES.some((s) => host.endsWith(s))) return true
  // Firm-added approved hosts (Settings > Research) extend the built-in list,
  // matched the same way. Read from preferences.json per call so a settings save
  // applies on the next fetch, no restart.
  return approvedSources().some((h) => host === h || host.endsWith("." + h))
}

function approvedSources(): string[] {
  const list = readPreferences().approvedSources
  return Array.isArray(list) ? list.filter((h): h is string => typeof h === "string" && h.trim().length > 0) : []
}

// The firm-wide web-research scope set in the web settings. Lives in the same
// preferences.json the ingest service writes for drafting preferences; read
// from disk on every fetch so a settings save applies immediately, no restart.
export function researchScope(): "official" | "open" {
  return readPreferences().webResearch === "open" ? "open" : "official"
}

// The firm's Exa web-search key (Settings > Drafting). Same per-call disk read
// as researchScope, so pasting a key in Settings makes the web-search tool work
// on the very next turn. Undefined until the firm configures one — the tool
// degrades to an instructive message, never a fake result.
export function readSearchKey(): string | undefined {
  const key = readPreferences().searchApiKey
  return typeof key === "string" && key.trim() ? key.trim() : undefined
}

function readPreferences(): Record<string, unknown> {
  const root = process.env.WORKSPACE_ROOT
  if (!root) return {}
  const file = path.join(root, ".preferences", "preferences.json")
  if (!existsSync(file)) return {}
  return JSON.parse(readFileSync(file, "utf8"))
}
