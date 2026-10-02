import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync, statSync, rmSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"
import type { ContentfulStatusCode } from "hono/utils/http-status"

// A matter is a directory under WORKSPACE_ROOT holding a matter.json plus the
// uploaded documents. This is the same directory the opencode server scopes a
// session to via the x-opencode-directory header.

export const WORKSPACE_ROOT = process.env.WORKSPACE_ROOT ?? path.join(process.cwd(), "workspace")

// reference is the firm's own client-matter number (e.g. "2026-0042"), shown in
// the UI. It is display metadata only — the directory id stays the auto slug+uuid.
// jurisdictions are pack codes (e.g. ["EW", "US-NY"]) the engine reads from
// matter.json to steer reasoning and citation style; a matter can span several
// (cross-border deal), so it is a list — see dochaus/jurisdiction/ (issue #18).
// playbook is the single playbook skill name (e.g. "playbook-nda") the matter is
// reviewed against; one matter binds at most one playbook, so it is a string.
export type Matter = {
  id: string
  title: string
  reference?: string
  jurisdictions?: string[]
  playbook?: string
  dir: string
  created_at: number
}

function matterFile(dir: string) {
  return path.join(dir, "matter.json")
}

// A matter id is the auto-generated slug+uuid from createMatter, so it is always
// [a-z0-9-]. Reject anything else before it reaches a filesystem path: the id
// arrives straight from a URL param, and matterDir is the single chokepoint every
// route resolves through, so guarding here blocks path traversal (../, absolute
// paths) out of WORKSPACE_ROOT across the whole service.
export function matterDir(id: string) {
  if (!/^[a-z0-9][a-z0-9-]*$/.test(id)) throw new Error(`invalid matter id: ${id}`)
  return path.join(WORKSPACE_ROOT, id)
}

export function listMatters(): Matter[] {
  mkdirSync(WORKSPACE_ROOT, { recursive: true })
  return readdirSync(WORKSPACE_ROOT)
    .map((name) => path.join(WORKSPACE_ROOT, name))
    .filter((dir) => statSync(dir).isDirectory() && existsSync(matterFile(dir)))
    .map((dir) => JSON.parse(readFileSync(matterFile(dir), "utf8")) as Matter)
    .sort((a, b) => a.created_at - b.created_at)
}

export function createMatter(title: string, reference?: string, jurisdictions?: string[], playbook?: string): Matter {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
  const id = `${slug}-${crypto.randomUUID().slice(0, 6)}`
  const dir = matterDir(id)
  mkdirSync(dir, { recursive: true })
  const matter: Matter = { id, title, reference, jurisdictions, playbook, dir, created_at: Date.now() }
  writeFileSync(matterFile(dir), JSON.stringify(matter, null, 2))
  return matter
}

// Rename keeps the directory id stable (it backs every session and document
// path); only the display title/reference/jurisdictions/playbook in matter.json change.
export function renameMatter(id: string, title: string, reference?: string, jurisdictions?: string[], playbook?: string): Matter {
  const dir = matterDir(id)
  const matter = { ...getMatter(id), title, reference, jurisdictions, playbook }
  writeFileSync(matterFile(dir), JSON.stringify(matter, null, 2))
  return matter
}

export function deleteMatter(id: string) {
  rmSync(matterDir(id), { recursive: true, force: true })
}

export function getMatter(id: string): Matter {
  return JSON.parse(readFileSync(matterFile(matterDir(id)), "utf8")) as Matter
}

// The jurisdiction packs available to assign to a matter, read from the dochaus
// config layer (dochaus/jurisdiction/<code>/profile.json). The web app fetches
// this to offer the choices; the engine consumes the full pack (issue #18).
// Resolved relative to this module like the template seed, so it does not depend
// on the ingest process cwd.
const JURISDICTION_DIR = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "dochaus",
  "jurisdiction",
)

export function listJurisdictions() {
  if (!existsSync(JURISDICTION_DIR)) return []
  return readdirSync(JURISDICTION_DIR)
    .map((code) => path.join(JURISDICTION_DIR, code, "profile.json"))
    .filter((file) => existsSync(file))
    .map((file) => JSON.parse(readFileSync(file, "utf8")) as { code: string; name: string; citationStyle: string })
    .sort((a, b) => a.name.localeCompare(b.name))
}

// Playbooks are opencode skills named playbook-*. Two sources feed the list: the
// repo-shipped skills under dochaus/skill/ (resolved relative to this module like
// the jurisdiction packs, so it is cwd-independent; read-only), and the imported
// ones the ingest service writes under WORKSPACE_ROOT/.playbooks. Each SKILL.md
// carries the name and description (plus optional version/last-reviewed) in its
// leading frontmatter block. The web app reads this to offer the playbook choices
// for a matter; the engine binds one via matter.json.
const SKILL_DIR = path.join(path.dirname(JURISDICTION_DIR), "skill")
const PLAYBOOK_DIR = path.join(WORKSPACE_ROOT, ".playbooks")

export type Playbook = {
  name: string
  description: string
  content: string
  version: string
  last_reviewed: string
  builtin: boolean
  updated_at: number
  matters: string[]
}

export class PlaybookError extends Error {
  status: ContentfulStatusCode
  constructor(message: string, status: ContentfulStatusCode) {
    super(message)
    this.status = status
  }
}

export function listPlaybooks(): Playbook[] {
  // Bound matters are surfaced per playbook so the library shows where each one
  // is in use and deletePlaybook can refuse to orphan a binding.
  const matters = listMatters()
  return [
    { dir: SKILL_DIR, builtin: true },
    { dir: PLAYBOOK_DIR, builtin: false },
  ]
    .filter((source) => existsSync(source.dir))
    .flatMap((source) =>
      readdirSync(source.dir)
        .map((entry) => path.join(source.dir, entry, "SKILL.md"))
        .filter((file) => existsSync(file))
        .map((file) => ({
          ...parsePlaybookMarkdown(readFileSync(file, "utf8")),
          builtin: source.builtin,
          updated_at: statSync(file).mtimeMs,
        })),
    )
    .filter((p) => p.name.startsWith("playbook-"))
    .map((p) => ({ ...p, matters: matters.filter((m) => m.playbook === p.name).map((m) => m.title) }))
    .sort((a, b) => a.name.localeCompare(b.name))
}

// SKILL.md = frontmatter + markdown body, same shape skill.ts owns for skills.
// Descriptions are JSON-quoted on write, so a quoted value is JSON-parsed back.
function parsePlaybookMarkdown(source: string) {
  const lines = source.split("\n")
  const end = lines[0]?.trim() === "---" ? lines.findIndex((l, i) => i > 0 && l.trim() === "---") : -1
  const read = (key: string) => {
    const line = lines.slice(1, end === -1 ? 0 : end).find((l) => l.startsWith(`${key}:`))
    if (!line) return ""
    const raw = line.slice(key.length + 1).trim()
    // Quoted values are JSON-parsed back; a legacy or hand-edited file may carry
    // a quote-prefixed value that is not valid JSON, so fall back to the raw
    // value (outer quotes stripped) rather than failing the whole playbook list.
    if (raw.startsWith('"')) {
      try {
        return JSON.parse(raw) as string
      } catch {
        return raw.replace(/^"|"$/g, "")
      }
    }
    return raw
  }
  return {
    name: read("name"),
    description: read("description"),
    version: read("version"),
    last_reviewed: read("last-reviewed"),
    content: end === -1 ? source.trim() : lines.slice(end + 1).join("\n").trim(),
  }
}

function renderPlaybookMarkdown(playbook: { name: string; description: string; version: string; last_reviewed: string; content: string }) {
  // Description is JSON-quoted so a colon or newline cannot inject YAML keys
  // (same posture as skill.ts renderSkillMarkdown). version/last-reviewed are
  // carried through when present so an update never strips them.
  const frontmatter = [
    `name: ${playbook.name}`,
    `description: ${JSON.stringify(playbook.description)}`,
    playbook.version && `version: ${JSON.stringify(playbook.version)}`,
    playbook.last_reviewed && `last-reviewed: ${JSON.stringify(playbook.last_reviewed)}`,
  ].filter((line): line is string => Boolean(line))
  return `---\n${frontmatter.join("\n")}\n---\n\n${playbook.content.trim()}\n`
}

// True keep-semantics: omitted fields retain their current values — the server
// owns the file, so it backfills from the existing SKILL.md rather than trusting
// callers to re-send everything. Only imported playbooks in WORKSPACE_ROOT/
// .playbooks are writable; repo-shipped ones are read-only.
export function updatePlaybook(name: string, input: { description?: string; content?: string }): Playbook {
  // basename() once, used for both the lookup and the filesystem path, so a
  // URL-decoded ../ in the name can never write outside PLAYBOOK_DIR (same
  // posture as the POST /playbooks handler).
  const safe = path.basename(name)
  const current = requireImportedPlaybook(safe)
  if (input.description === undefined && input.content === undefined)
    throw new PlaybookError("Nothing to update — supply description, content, or both", 400)
  if (input.content !== undefined && !input.content.trim()) throw new PlaybookError("content must be non-empty", 400)
  const updated = {
    ...current,
    description: input.description ?? current.description,
    content: input.content?.trim() ?? current.content,
  }
  const file = path.join(PLAYBOOK_DIR, safe, "SKILL.md")
  writeFileSync(file, renderPlaybookMarkdown(updated))
  return { ...updated, updated_at: statSync(file).mtimeMs }
}

// Deleting a playbook a matter is still bound to would leave that matter's
// playbook setting dangling, so it is refused until the bindings are cleared.
export function deletePlaybook(name: string) {
  // basename() once for both the guard and the rmSync path — see updatePlaybook.
  const safe = path.basename(name)
  const current = requireImportedPlaybook(safe)
  if (current.matters.length)
    throw new PlaybookError(
      `playbook "${safe}" is bound to ${current.matters.length} matter(s): ${current.matters.join(", ")}. Unbind it from each matter before deleting.`,
      409,
    )
  rmSync(path.join(PLAYBOOK_DIR, safe), { recursive: true, force: true })
}

function requireImportedPlaybook(name: string) {
  const playbook = listPlaybooks().find((p) => p.name === name)
  if (!playbook) throw new PlaybookError(`playbook "${name}" not found`, 404)
  if (playbook.builtin) throw new PlaybookError(`playbook "${name}" is repo-shipped and read-only`, 403)
  return playbook
}
