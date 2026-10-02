import path from "path"
import fs from "fs/promises"
import { Database } from "bun:sqlite"
import z from "zod"
import { Global } from "../global"
import { Instance } from "../project/instance"
import { Storage } from "../storage/storage"
import { Memory } from "./memory"
import { Log } from "../util/log"

// Disposable full-text index (SQLite FTS5 via bun:sqlite, zero new deps) over
// memory notes and past session message text. The JSON memory docs and the
// message files under Storage remain the source of truth: deleting index.db
// simply triggers a rebuild on the next search.
//
// Search is honest full-text retrieval — BM25 keyword ranking with a recency
// tiebreak. There are no embeddings and nothing "semantic" here.
//
// Freshness model:
// - notes_fts is rebuilt from the (tiny) JSON docs on every search, so panel
//   PUTs and tool writes are always reflected without any write-path coupling.
// - messages_fts is swept incrementally: message files not yet recorded in the
//   `swept` table are read and indexed. Assistant messages still streaming
//   (no time.completed) are skipped until complete so partial text is never
//   frozen into the index.
export namespace MemoryIndex {
  const log = Log.create({ service: "settings.memory-index" })

  export const Hit = z.object({
    kind: z.enum(["note", "session"]),
    text: z.string(),
    score: z.number(),
    created: z.number(),
    scope: Memory.Scope.optional(),
    category: z.string().optional(),
    sessionID: z.string().optional(),
    messageID: z.string().optional(),
    role: z.string().optional(),
  })
  export type Hit = z.infer<typeof Hit>

  const state = { db: undefined as Database | undefined }

  function file() {
    return path.join(Global.Path.data, "settings", "memory", "index.db")
  }

  function create() {
    const db = new Database(file(), { create: true })
    db.exec("pragma journal_mode = WAL")
    db.exec(
      "create virtual table if not exists notes_fts using fts5(scope unindexed, category, text, created unindexed)",
    )
    db.exec(
      "create virtual table if not exists messages_fts using fts5(project unindexed, session unindexed, message unindexed, role unindexed, text, created unindexed)",
    )
    db.exec("create table if not exists swept (message text primary key, created integer)")
    return db
  }

  async function open() {
    if (state.db) return state.db
    await fs.mkdir(path.dirname(file()), { recursive: true })
    try {
      state.db = create()
    } catch (e) {
      // The index is disposable; a corrupt file is deleted and rebuilt.
      log.error("memory index unreadable, rebuilding", { error: e })
      await fs.rm(file(), { force: true })
      state.db = create()
    }
    return state.db
  }

  // Close and delete the index. The next search rebuilds it from the JSON
  // sources — this is the "disposable index" guarantee.
  export async function reset() {
    state.db?.close()
    state.db = undefined
    await fs.rm(file(), { force: true })
    await fs.rm(file() + "-wal", { force: true })
    await fs.rm(file() + "-shm", { force: true })
  }

  async function refresh(db: Database) {
    db.exec("delete from notes_fts")
    const insert = db.prepare("insert into notes_fts (scope, category, text, created) values (?, ?, ?, ?)")
    for (const scope of Memory.Scope.options) {
      const doc = await Memory.get(scope).catch(() => undefined)
      if (!doc || !doc.enabled) continue
      for (const category of doc.categories)
        for (const note of category.notes)
          if (note.text.trim()) insert.run(scope, category.name, note.text, String(note.createdAt))
    }
  }

  // Minimal structural views of stored messages/parts; avoids importing the
  // full MessageV2 module (and its provider dependency chain) into settings.
  type Message = { role?: string; time?: { created?: number; completed?: number } }
  type Part = { type?: string; text?: string; synthetic?: boolean }

  async function sweep(db: Database) {
    const projects = new Map<string, string>()
    for (const key of await Storage.list(["session"])) {
      if (key.length === 3) projects.set(key[2]!, key[1]!)
    }
    const swept = new Set(
      (db.query("select message from swept").all() as { message: string }[]).map((row) => row.message),
    )
    const insert = db.prepare(
      "insert into messages_fts (project, session, message, role, text, created) values (?, ?, ?, ?, ?, ?)",
    )
    const mark = db.prepare("insert or replace into swept (message, created) values (?, ?)")
    for (const key of await Storage.list(["message"])) {
      if (key.length !== 3) continue
      const session = key[1]!
      const id = key[2]!
      if (swept.has(id)) continue
      const message = await Storage.read<Message>(key).catch(() => undefined)
      if (!message?.role || !message.time?.created) continue
      // Skip assistant turns that are still streaming; they get indexed on a
      // later sweep once complete, so partial text is never frozen in.
      if (message.role === "assistant" && !message.time.completed) continue
      const parts: string[] = []
      for (const pkey of await Storage.list(["part", id])) {
        const part = await Storage.read<Part>(pkey).catch(() => undefined)
        if (!part || part.type !== "text" || part.synthetic || !part.text?.trim()) continue
        parts.push(part.text)
      }
      const text = parts.join("\n").trim()
      if (text) insert.run(projects.get(session) ?? "", session, id, message.role, text, String(message.time.created))
      mark.run(id, message.time.created)
    }
  }

  // FTS5 query syntax errors on raw user input; reduce the query to bare
  // terms OR-ed together and let BM25 rank multi-term matches higher.
  function expression(query: string) {
    const terms = query.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? []
    if (terms.length === 0) return undefined
    return terms.map((term) => `"${term}"`).join(" OR ")
  }

  // BM25 rank from FTS5 is smaller-is-better; negate it and subtract a gentle
  // age penalty so equally relevant recent hits win.
  function score(rank: number, created: number, now: number) {
    const age = Math.max(0, now - created) / 86_400_000
    return -rank - age * 0.01
  }

  function snippet(text: string) {
    const flat = text.replace(/\s+/g, " ").trim()
    return flat.length > 240 ? flat.slice(0, 240) + "…" : flat
  }

  export async function search(query: string, options?: { limit?: number; project?: string }): Promise<Hit[]> {
    const match = expression(query)
    if (!match) return []
    const limit = options?.limit ?? 8
    const db = await open()
    await refresh(db)
    await sweep(db).catch((e) => log.error("session sweep failed", { error: e }))
    const now = Date.now()
    const hits: Hit[] = []
    const notes = db
      .query(
        "select scope, category, text, created, bm25(notes_fts) as rank from notes_fts where notes_fts match ?1 order by rank limit ?2",
      )
      .all(match, limit) as { scope: string; category: string; text: string; created: string; rank: number }[]
    for (const row of notes) {
      const created = Number(row.created)
      hits.push({
        kind: "note",
        scope: Memory.Scope.parse(row.scope),
        category: row.category,
        text: snippet(row.text),
        created,
        score: score(row.rank, created, now),
      })
    }
    const sql =
      "select project, session, message, role, text, created, bm25(messages_fts) as rank from messages_fts where messages_fts match ?1"
    const rows = (
      options?.project
        ? db.query(sql + " and project = ?3 order by rank limit ?2").all(match, limit, options.project)
        : db.query(sql + " order by rank limit ?2").all(match, limit)
    ) as { session: string; message: string; role: string; text: string; created: string; rank: number }[]
    for (const row of rows) {
      const created = Number(row.created)
      hits.push({
        kind: "session",
        sessionID: row.session,
        messageID: row.message,
        role: row.role,
        text: snippet(row.text),
        created,
        score: score(row.rank, created, now),
      })
    }
    hits.sort((a, b) => b.score - a.score)
    return hits.slice(0, limit)
  }
}
