import { INGEST_URL } from "../config"

// Matters and documents live in the ingest service: it owns matter directories
// under WORKSPACE_ROOT and turns uploaded DOCX into the per-matter embedding DB.
// OpenCode has no upload endpoint, so all document I/O goes through here.

export type Matter = {
  id: string
  title: string
  reference?: string
  jurisdictions?: string[]
  playbook?: string
  dir: string
  created_at: number
}
// A jurisdiction pack the matter can be steered by (dochaus/jurisdiction/<code>).
export type Jurisdiction = { code: string; name: string; citationStyle: string }
// A playbook the matter can be steered by (dochaus/playbook-<name>). Names start
// with "playbook-"; unlike jurisdictions a matter binds at most one.
export type Playbook = { name: string; description: string }
export type Document = { id: number; name: string; doc_path: string; created_at: number; pending?: number }
// A pending redline proposal: one tracked change awaiting accept/reject.
export type Redline = {
  id: number
  doc_name: string
  scope: "phrase" | "clause"
  find_text: string
  old_text: string
  new_text: string
  author: string
  created_at: number
}
export type MatterDetail = Matter & { documents: Document[] }
// A drafting template in the firm's global library. placeholders are the
// bracketed terms a draft fills in (text, with a kind and an optional hint).
export type TemplatePlaceholder = { text: string; kind: string; hint?: string }
// description is a one-line summary of what the template is for, stored in the
// ingest-owned manifest beside the .docx (empty string when none was set).
export type Template = { name: string; description: string; placeholders: TemplatePlaceholder[] }
// A prompt-injection finding from ingest-time scanning: invisible Unicode, hidden
// DOCX formatting, or instruction-like text (see services/ingest/src/sanitize.ts).
export type InjectionFinding = { rule: string; detail: string; snippet?: string; charStart?: number; charEnd?: number }
export type IngestResult = {
  name: string
  docPath: string
  sections: number
  chunks: number
  // null when the document came up clean.
  injection: { findings: InjectionFinding[]; flaggedChunks: number } | null
}

// Tabular-review grid. Columns are questions; cells are keyed `<docName>::<colId>`.
// Rows are the matter's documents, so they are not stored here.
export type GridColumn = { id: string; question: string }
export type GridCellData = {
  answer: string
  citation?: {
    documentName: string
    docPath: string
    section: string
    excerpt: string
    charStart: number
    charEnd: number
  }
  status: "filled" | "reviewed"
  questionHash: string
  // Reviewer comment thread on the cell; survives recomputes.
  comments?: GridCellComment[]
}
export type GridCellComment = { id: string; text: string; at: number }
export type Grid = { columns: GridColumn[]; cells: Record<string, GridCellData> }

export type WorkflowStep = { agent: string; instructions: string }

export type CustomWorkflow = {
  name: string
  label: string
  description: string
  scope: "matter" | "document"
  prompt: string
  steps: WorkflowStep[]
  created_at: number
}

export async function listMatters(): Promise<Matter[]> {
  const res = await fetch(`${INGEST_URL}/matters`)
  return res.json()
}

// Firm-wide drafting preferences (Settings → Drafting). Stored on the engine
// host and rendered into a standing-instructions file every assistant reads, so
// a save steers the model from its next reply.
export type DraftingPreferences = {
  attorney: string
  firm: string
  posture: "client-favorable" | "balanced" | "conservative"
  formality: "formal" | "plain"
  detail: "concise" | "detailed"
  process: "plan-first" | "standard"
  dateFormat: "month-day-year" | "day-month-year" | "iso"
  numberStyle: "words-and-numerals" | "numerals"
  houseStyle: string
  webResearch: "official" | "open"
  searchApiKey: string
  approvedSources: string[]
}

export async function getPreferences(): Promise<DraftingPreferences> {
  const res = await fetch(`${INGEST_URL}/preferences`)
  return res.json()
}

export async function savePreferences(prefs: DraftingPreferences): Promise<DraftingPreferences> {
  const res = await fetch(`${INGEST_URL}/preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs),
  })
  if (!res.ok) throw new Error(`Failed to save preferences (${res.status})`)
  return res.json()
}

export async function listJurisdictions(): Promise<Jurisdiction[]> {
  const res = await fetch(`${INGEST_URL}/jurisdictions`)
  return res.json()
}

export async function listPlaybooks(): Promise<Playbook[]> {
  const res = await fetch(`${INGEST_URL}/playbooks`)
  return res.json()
}

export async function createMatter(
  title: string,
  reference?: string,
  jurisdictions?: string[],
  playbook?: string,
): Promise<Matter> {
  const res = await fetch(`${INGEST_URL}/matters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, reference, jurisdictions, playbook }),
  })
  return res.json()
}

export async function renameMatter(
  id: string,
  title: string,
  reference?: string,
  jurisdictions?: string[],
  playbook?: string,
): Promise<Matter> {
  const res = await fetch(`${INGEST_URL}/matters/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, reference, jurisdictions, playbook }),
  })
  return res.json()
}

export async function deleteMatter(id: string): Promise<void> {
  await fetch(`${INGEST_URL}/matters/${id}`, { method: "DELETE" })
}

export async function getMatter(id: string): Promise<MatterDetail> {
  const res = await fetch(`${INGEST_URL}/matters/${id}`)
  return res.json()
}

export async function uploadDocument(id: string, file: File): Promise<IngestResult> {
  const form = new FormData()
  form.append("file", file)
  const res = await fetch(`${INGEST_URL}/matters/${id}/documents`, { method: "POST", body: form })
  return res.json()
}

export async function deleteDocument(id: string, name: string): Promise<void> {
  await fetch(`${INGEST_URL}/matters/${id}/documents?name=${encodeURIComponent(name)}`, { method: "DELETE" })
}

// Convert a matter's uploaded .pdf into an editable .docx sibling and index it, so
// the PDF can enter the DOCX redline pipeline. Returns the new .docx document.
export async function convertPdfToDocx(id: string, name: string): Promise<IngestResult & { conversionMode: "layout" | "text" }> {
  const res = await fetch(`${INGEST_URL}/matters/${id}/documents/convert?name=${encodeURIComponent(name)}`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`Could not convert ${name} (${res.status})`)
  return res.json()
}

// URL the PDF viewer points an <iframe> at — the browser renders the PDF natively
// from our own ingest service, so the file never leaves for a third-party service.
export function documentContentUrl(id: string, name: string): string {
  return `${INGEST_URL}/matters/${id}/documents/content?name=${encodeURIComponent(name)}`
}

export async function getGrid(id: string): Promise<Grid> {
  const res = await fetch(`${INGEST_URL}/matters/${id}/grid`)
  return res.json()
}

export async function saveGrid(id: string, grid: Grid): Promise<void> {
  await fetch(`${INGEST_URL}/matters/${id}/grid`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grid),
  })
}

// Raw .docx bytes for a matter document. The viewer renders these client-side
// via WASM, so the file is fetched from our own ingest service and converted in
// the browser — it never leaves for any third-party service.
export async function fetchDocumentBytes(id: string, name: string): Promise<Uint8Array> {
  const res = await fetch(`${INGEST_URL}/matters/${id}/documents/content?name=${encodeURIComponent(name)}`)
  if (!res.ok) throw new Error(`Could not load ${name} (${res.status})`)
  return new Uint8Array(await res.arrayBuffer())
}

// The redlined view: the clean .docx compared against itself with every pending
// proposal applied, so the bytes carry native tracked changes the viewer paints
// green/red. Identical to the clean bytes when nothing is pending.
export async function fetchRedlinedBytes(id: string, name: string): Promise<Uint8Array> {
  const res = await fetch(`${INGEST_URL}/matters/${id}/documents/redlined?name=${encodeURIComponent(name)}`)
  if (!res.ok) throw new Error(`Could not load ${name} (${res.status})`)
  return new Uint8Array(await res.arrayBuffer())
}

export async function fetchRedlines(id: string, name: string): Promise<Redline[]> {
  const res = await fetch(`${INGEST_URL}/matters/${id}/redlines?name=${encodeURIComponent(name)}`)
  if (!res.ok) throw new Error(`Could not load changes for ${name} (${res.status})`)
  return res.json()
}

export async function acceptRedline(id: string, redlineId: number): Promise<void> {
  await fetch(`${INGEST_URL}/matters/${id}/redlines/${redlineId}/accept`, { method: "POST" })
}

export async function rejectRedline(id: string, redlineId: number): Promise<void> {
  await fetch(`${INGEST_URL}/matters/${id}/redlines/${redlineId}/reject`, { method: "POST" })
}

export async function acceptAllRedlines(id: string, name: string): Promise<void> {
  await fetch(`${INGEST_URL}/matters/${id}/redlines/accept-all?name=${encodeURIComponent(name)}`, { method: "POST" })
}

export async function rejectAllRedlines(id: string, name: string): Promise<void> {
  await fetch(`${INGEST_URL}/matters/${id}/redlines/reject-all?name=${encodeURIComponent(name)}`, { method: "POST" })
}

// The firm's global template library, owned by the ingest service. Templates are
// shared across every matter, so unlike documents they are not scoped to a matter.
// The response carries the library directory alongside the list — the templates
// chat scopes its engine sessions to that directory (there is no matter to scope
// to), so the page needs it from the same call.
export async function listTemplates(): Promise<{ dir: string; templates: Template[] }> {
  const res = await fetch(`${INGEST_URL}/templates`)
  return res.json()
}

export async function uploadTemplate(file: File): Promise<Template> {
  const form = new FormData()
  form.append("file", file)
  const res = await fetch(`${INGEST_URL}/templates`, { method: "POST", body: form })
  return res.json()
}

export async function updateTemplateDescription(name: string, description: string): Promise<Template> {
  const res = await fetch(`${INGEST_URL}/templates?name=${encodeURIComponent(name)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description }),
  })
  if (!res.ok) throw new Error(`Could not update ${name} (${res.status})`)
  return res.json()
}

export async function deleteTemplate(name: string): Promise<void> {
  await fetch(`${INGEST_URL}/templates?name=${encodeURIComponent(name)}`, { method: "DELETE" })
}

// Raw .docx bytes for a template, rendered client-side by the template viewer via
// WASM — the file is fetched from our own ingest service and converted in the
// browser, so it never leaves for any third-party service.
export async function fetchTemplateBytes(name: string): Promise<Uint8Array> {
  const res = await fetch(`${INGEST_URL}/templates/content?name=${encodeURIComponent(name)}`)
  if (!res.ok) throw new Error(`Could not load ${name} (${res.status})`)
  return new Uint8Array(await res.arrayBuffer())
}

// The firm's custom workflow library, owned by the ingest service. The response
// carries the library directory alongside the list — the workflow builder chat
// scopes its engine sessions to that directory (there is no matter to scope to),
// so the page needs it from the same call.
export async function listWorkflows(): Promise<{ dir: string; workflows: CustomWorkflow[] }> {
  const res = await fetch(`${INGEST_URL}/workflows`)
  if (!res.ok) throw new Error(`${(await res.json()).error}`)
  return res.json()
}

export async function deleteWorkflow(name: string): Promise<void> {
  const res = await fetch(`${INGEST_URL}/workflows/${encodeURIComponent(name)}`, { method: "DELETE" })
  if (!res.ok) throw new Error(`${(await res.json()).error}`)
}

// The firm's skill library, owned by the ingest service: repo-shipped reference
// skills (read-only) plus the custom ones under WORKSPACE_ROOT/.skills. The
// response carries the library directory alongside the list — the skill builder
// chat scopes its engine sessions to that directory (there is no matter to scope
// to), so the page needs it from the same call.
export type Skill = { name: string; description: string; content: string; builtin: boolean; enabled: boolean }

export async function listSkills(): Promise<{ dir: string; skills: Skill[] }> {
  const res = await fetch(`${INGEST_URL}/skills`)
  if (!res.ok) throw new Error(`${(await res.json()).error}`)
  return res.json()
}

// Import an uploaded file as a skill: .md keeps its own frontmatter, .docx/.pdf/.txt
// are text-extracted raw for the skill builder chat to refine afterwards.
export async function importSkill(file: File): Promise<Skill> {
  const form = new FormData()
  form.append("file", file)
  const res = await fetch(`${INGEST_URL}/skills/import`, { method: "POST", body: form })
  if (!res.ok) throw new Error(`${(await res.json()).error}`)
  return res.json()
}

export async function deleteSkill(name: string): Promise<void> {
  const res = await fetch(`${INGEST_URL}/skills/${encodeURIComponent(name)}`, { method: "DELETE" })
  if (!res.ok) throw new Error(`${(await res.json()).error}`)
}

// Flip a skill on or off — builtin and custom alike. A disabled skill stays in
// the library but the engine hides it from every agent.
export async function setSkillEnabled(name: string, enabled: boolean): Promise<Skill> {
  const res = await fetch(`${INGEST_URL}/skills/${encodeURIComponent(name)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  })
  if (!res.ok) throw new Error(`${(await res.json()).error}`)
  return res.json()
}

// The firm's specialist subagents, owned by the ingest service: repo-shipped
// specialists (read-only) plus the custom ones the agent builder composed.
// Custom agents are workflow building blocks — deletion is refused while a
// workflow references one.
export type AgentRecord = {
  name: string
  label: string
  description: string
  instructions: string
  builtin: boolean
  enabled: boolean
  created_at: number
}

export async function listAgents(): Promise<{ dir: string; agents: AgentRecord[] }> {
  const res = await fetch(`${INGEST_URL}/agents`)
  if (!res.ok) throw new Error(`${(await res.json()).error}`)
  return res.json()
}

export async function deleteAgent(name: string): Promise<void> {
  const res = await fetch(`${INGEST_URL}/agents/${encodeURIComponent(name)}`, { method: "DELETE" })
  if (!res.ok) throw new Error(`${(await res.json()).error}`)
}

// Flip an agent on or off — builtin and custom alike. A disabled agent stays in
// the library but the engine drops it from the task/workflow roster.
export async function setAgentEnabled(name: string, enabled: boolean): Promise<AgentRecord> {
  const res = await fetch(`${INGEST_URL}/agents/${encodeURIComponent(name)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  })
  if (!res.ok) throw new Error(`${(await res.json()).error}`)
  return res.json()
}
