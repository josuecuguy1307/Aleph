import { Database } from "bun:sqlite"
import { existsSync, mkdirSync } from "node:fs"
import path from "node:path"

// Record and read redline proposals in the matter's index DB. The redline tools
// propose changes here instead of writing tracked changes into the .docx; the
// ingest service reads these rows to render the redlined view and to accept
// (bake) or reject them. The canonical .docx stays clean until a reviewer accepts.
//
// Ingest owns this database and creates the same `redlines` table in its openDb;
// keep this DDL in sync with services/ingest/src/db.ts. We create-if-not-exists
// here too so a tool can propose before the document is ever (re-)ingested.

export function recordRedline(
  matterDir: string,
  row: {
    docPath: string
    docName: string
    scope: "phrase" | "clause"
    findText: string
    oldText: string
    newText: string
    author: string
    anchorId: string
  },
) {
  const dir = path.join(matterDir, ".dochaus")
  mkdirSync(dir, { recursive: true })
  const db = new Database(path.join(dir, "legal.db"))
  db.run("PRAGMA journal_mode = WAL")
  db.run(`
    CREATE TABLE IF NOT EXISTS redlines (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      doc_path TEXT NOT NULL,
      doc_name TEXT NOT NULL,
      scope TEXT NOT NULL,
      find_text TEXT NOT NULL,
      old_text TEXT NOT NULL,
      new_text TEXT NOT NULL,
      author TEXT NOT NULL,
      anchor_id TEXT,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at INTEGER NOT NULL
    )
  `)
  const result = db.run(
    "INSERT INTO redlines (doc_path, doc_name, scope, find_text, old_text, new_text, author, anchor_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    [row.docPath, row.docName, row.scope, row.findText, row.oldText, row.newText, row.author, row.anchorId, Date.now()],
  )
  db.close()
  return Number(result.lastInsertRowid)
}

// A pending proposal, as the propose-time conflict check sees it. anchor_id is the
// Docxodus block token the proposal targets; the canonical .docx stays clean while
// proposals are pending, so two proposals carrying the same anchor_id address the
// same paragraph and the replay would collide.
export type PendingRedline = {
  id: number
  scope: "phrase" | "clause"
  find_text: string
  new_text: string
  author: string
  anchor_id: string | null
}

export function pendingRedlinesForDoc(matterDir: string, docPath: string): PendingRedline[] {
  const dbFile = path.join(matterDir, ".dochaus", "legal.db")
  if (!existsSync(dbFile)) return []
  const db = new Database(dbFile, { readonly: true })
  const rows = db
    .query(
      "SELECT id, scope, find_text, new_text, author, anchor_id FROM redlines WHERE doc_path = ? AND status = 'pending' ORDER BY created_at, id",
    )
    .all(docPath) as PendingRedline[]
  db.close()
  return rows
}

// Pending proposals that collide with the one about to be recorded. Two proposals
// collide when they target the same paragraph (same anchor_id) AND either rewrites
// the whole clause — a clause rewrite replaces the entire paragraph, so it voids
// every other edit on it — or their find texts overlap (one contains the other),
// so the replay of one erases the text the other anchors to. Independent phrase
// edits in the same paragraph do not collide and coexist.
export function conflictingRedlines(
  pending: PendingRedline[],
  next: { anchorId: string; scope: "phrase" | "clause"; findText: string },
) {
  return pending.filter((p) => {
    if (p.anchor_id !== next.anchorId) return false
    if (p.scope === "clause" || next.scope === "clause") return true
    const existing = p.find_text.trim()
    const incoming = next.findText.trim()
    return existing.includes(incoming) || incoming.includes(existing)
  })
}

// Retire superseded proposals so only the newest edit on a paragraph stays pending.
// A separate 'superseded' status (not 'rejected') records that the reviewer never
// declined the edit — a later proposal replaced it — without surfacing it in the
// pending queue or the redlined view.
export function supersedeRedlines(matterDir: string, ids: number[]) {
  if (!ids.length) return
  const db = new Database(path.join(matterDir, ".dochaus", "legal.db"))
  for (const id of ids) db.run("UPDATE redlines SET status = 'superseded' WHERE id = ?", [id])
  db.close()
}
