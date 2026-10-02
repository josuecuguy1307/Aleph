import { Database } from "bun:sqlite"
import { mkdirSync } from "node:fs"
import path from "node:path"

// Per-matter retrieval index. Lives inside the matter directory so it is scoped
// to that matter and rebuildable from the source .docx files at any time.

export function openDb(matterDir: string): Database {
  const dir = path.join(matterDir, ".dochaus")
  mkdirSync(dir, { recursive: true })
  const db = new Database(path.join(dir, "legal.db"))
  db.run("PRAGMA journal_mode = WAL")
  // injection_report: JSON-encoded prompt-injection findings from ingest-time
  // scanning (see sanitize.ts), NULL when the document came up clean.
  db.run(`
    CREATE TABLE IF NOT EXISTS documents (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      doc_path TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      injection_report TEXT
    )
  `)
  // flagged: 1 when the chunk overlaps an ingest-time injection finding, so the
  // search-document tool can mark the passage as adversarial when handing it to
  // the model.
  db.run(`
    CREATE TABLE IF NOT EXISTS chunks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      document_id INTEGER NOT NULL,
      doc_path TEXT NOT NULL,
      doc_name TEXT NOT NULL,
      section TEXT NOT NULL,
      chunk_index INTEGER NOT NULL,
      text TEXT NOT NULL,
      char_start INTEGER NOT NULL,
      char_end INTEGER NOT NULL,
      embedding BLOB NOT NULL,
      flagged INTEGER NOT NULL DEFAULT 0
    )
  `)
  // Databases created before the injection-defense columns existed (issue #17)
  // gain them here; their documents read as clean until re-ingested.
  if (!hasColumn(db, "documents", "injection_report")) db.run("ALTER TABLE documents ADD COLUMN injection_report TEXT")
  if (!hasColumn(db, "chunks", "flagged")) db.run("ALTER TABLE chunks ADD COLUMN flagged INTEGER NOT NULL DEFAULT 0")
  // Small key-value table for index-level facts that aren't rows — currently
  // which embedding model wrote the chunk vectors (see embed.ts migration).
  db.run("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
  // Lexical channel for hybrid retrieval (issue #67): a BM25-ranked FTS5 index
  // over the same chunks the vector channel scans. external-content mode stores
  // only the index and reads row text back from chunks, so chunk text is never
  // duplicated. The section label and document name are indexed alongside the
  // body so a query naming a clause ("Section 8.3") or a document matches that
  // clause's or document's own chunks directly.
  // Databases indexed before doc_name was added carry a two-column chunks_fts;
  // FTS5 has no ALTER, so drop and recreate (the rebuild below repopulates).
  const ftsSql = (db.query("SELECT sql FROM sqlite_master WHERE name = 'chunks_fts'").get() as { sql: string } | null)
    ?.sql
  if (ftsSql && !ftsSql.includes("doc_name")) {
    for (const trigger of ["chunks_fts_ai", "chunks_fts_ad", "chunks_fts_au"]) db.run(`DROP TRIGGER IF EXISTS ${trigger}`)
    db.run("DROP TABLE chunks_fts")
  }
  db.run(`
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
      text, section, doc_name,
      content='chunks', content_rowid='id',
      tokenize='unicode61 remove_diacritics 2'
    )
  `)
  // Triggers keep the index in sync with every write path (insertChunk,
  // upsertDocument's delete-then-reinsert, deleteDocument). External-content
  // FTS5 requires the special 'delete' insert form to unindex a row.
  db.run(`
    CREATE TRIGGER IF NOT EXISTS chunks_fts_ai AFTER INSERT ON chunks BEGIN
      INSERT INTO chunks_fts(rowid, text, section, doc_name) VALUES (new.id, new.text, new.section, new.doc_name);
    END
  `)
  db.run(`
    CREATE TRIGGER IF NOT EXISTS chunks_fts_ad AFTER DELETE ON chunks BEGIN
      INSERT INTO chunks_fts(chunks_fts, rowid, text, section, doc_name) VALUES ('delete', old.id, old.text, old.section, old.doc_name);
    END
  `)
  db.run(`
    CREATE TRIGGER IF NOT EXISTS chunks_fts_au AFTER UPDATE ON chunks BEGIN
      INSERT INTO chunks_fts(chunks_fts, rowid, text, section, doc_name) VALUES ('delete', old.id, old.text, old.section, old.doc_name);
      INSERT INTO chunks_fts(rowid, text, section, doc_name) VALUES (new.id, new.text, new.section, new.doc_name);
    END
  `)
  // Backfill databases that predate the FTS table, and self-heal any drift (a
  // crash between table creation and indexing, or chunks written or updated
  // while the triggers did not exist or did not match the index). Drift is not
  // always a row-count mismatch: a desynced external-content index can hold the
  // right number of rows with the wrong tokens, and then any trigger-driven
  // 'delete' (e.g. the embedding-migration UPDATE) throws SQLITE_CORRUPT
  // ("database disk image is malformed") even though the file is intact. FTS5's
  // own 'integrity-check' command compares the index against the chunks table
  // and is the only complete drift probe; 'rebuild' atomically reindexes.
  if (!ftsInSync(db)) db.run("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
  // Contract-structure tables: deterministic, regex-extracted facts about each
  // document (see structure.ts). Every row is a pointer (offsets) into the
  // document's extracted text plus the verbatim text at that pointer — nothing
  // here is generated, so the lookup tools built on these tables cannot
  // fabricate. A parse miss means a missing row, and the tools say "not found"
  // and fall back to search; it never means a wrong fact.
  db.run(`
    CREATE TABLE IF NOT EXISTS defined_terms (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      doc_path TEXT NOT NULL,
      doc_name TEXT NOT NULL,
      term TEXT NOT NULL,
      definition TEXT NOT NULL,
      char_start INTEGER NOT NULL,
      char_end INTEGER NOT NULL
    )
  `)
  db.run(`
    CREATE TABLE IF NOT EXISTS section_refs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      doc_path TEXT NOT NULL,
      doc_name TEXT NOT NULL,
      ref_kind TEXT NOT NULL,
      ref_label TEXT NOT NULL,
      char_start INTEGER NOT NULL,
      char_end INTEGER NOT NULL
    )
  `)
  db.run(`
    CREATE TABLE IF NOT EXISTS parties (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      doc_path TEXT NOT NULL,
      doc_name TEXT NOT NULL,
      name TEXT NOT NULL,
      role TEXT,
      char_start INTEGER NOT NULL,
      char_end INTEGER NOT NULL
    )
  `)
  // relation: currently only 'amends'. target_name is the verbatim title of the
  // referenced document as this document states it; resolution to an actual
  // matter document happens at lookup time by name match, never by guess.
  db.run(`
    CREATE TABLE IF NOT EXISTS doc_relations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      doc_path TEXT NOT NULL,
      doc_name TEXT NOT NULL,
      relation TEXT NOT NULL,
      target_name TEXT NOT NULL,
      char_start INTEGER NOT NULL,
      char_end INTEGER NOT NULL
    )
  `)
  db.run("CREATE INDEX IF NOT EXISTS defined_terms_term ON defined_terms(term)")
  db.run("CREATE INDEX IF NOT EXISTS section_refs_doc ON section_refs(doc_path)")
  // Pending redline proposals. The canonical .docx stays clean (the accepted
  // state); each redline a tool proposes is a row here until a reviewer accepts
  // it (baked into the doc) or rejects it. scope drives how the edit is replayed:
  // 'phrase' is a surgical find/replace, 'clause' rewrites a located paragraph.
  // The redline tools (dochaus/tool/{redline,tracked-changes}.ts) create the same
  // table independently, so keep this DDL in sync with them.
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
  return db
}

// FTS5 reports an index/content mismatch only by throwing SQLITE_CORRUPT from
// its 'integrity-check' command (rank=1 verifies against the content table);
// there is no boolean API, so the catch is the result.
function ftsInSync(db: Database) {
  try {
    db.run("INSERT INTO chunks_fts(chunks_fts, rank) VALUES ('integrity-check', 1)")
    return true
  } catch {
    return false
  }
}

function hasColumn(db: Database, table: string, column: string) {
  return (db.query(`PRAGMA table_info(${table})`).all() as { name: string }[]).some((c) => c.name === column)
}

export function getMeta(db: Database, key: string): string | null {
  return (db.query("SELECT value FROM meta WHERE key = ?").get(key) as { value: string } | null)?.value ?? null
}

export function setMeta(db: Database, key: string, value: string) {
  db.run("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", [
    key,
    value,
  ])
}

export type RedlineRow = {
  id: number
  doc_path: string
  doc_name: string
  scope: "phrase" | "clause"
  find_text: string
  old_text: string
  new_text: string
  author: string
  anchor_id: string | null
  // 'superseded': a later proposal on the same paragraph replaced this one before
  // review (set by the redline tools), so it never reaches the pending queue.
  status: "pending" | "accepted" | "rejected" | "superseded"
  created_at: number
}

// Pending redlines for one document, oldest first — the order they are replayed
// when building the redlined view and when accepting in bulk.
export function listPendingRedlines(db: Database, docPath: string): RedlineRow[] {
  return db
    .query("SELECT * FROM redlines WHERE doc_path = ? AND status = 'pending' ORDER BY created_at, id")
    .all(docPath) as RedlineRow[]
}

export function getRedline(db: Database, id: number): RedlineRow | null {
  return (db.query("SELECT * FROM redlines WHERE id = ?").get(id) as RedlineRow) ?? null
}

export function setRedlineStatus(db: Database, id: number, status: "accepted" | "rejected") {
  db.run("UPDATE redlines SET status = ? WHERE id = ?", [status, id])
}

// Per-document pending counts, keyed by absolute doc_path, for the docs-rail badge.
export function pendingRedlineCounts(db: Database): Record<string, number> {
  const rows = db
    .query("SELECT doc_path, COUNT(*) AS n FROM redlines WHERE status = 'pending' GROUP BY doc_path")
    .all() as { doc_path: string; n: number }[]
  return Object.fromEntries(rows.map((r) => [r.doc_path, r.n]))
}

export function listDocuments(db: Database) {
  return db.query("SELECT id, doc_path, name, created_at FROM documents ORDER BY created_at").all()
}

// Drop a document and its chunks from the index. Pairs with removing the source
// .docx so the matter holds no orphaned embeddings.
export function deleteDocument(db: Database, docPath: string) {
  db.run("DELETE FROM chunks WHERE doc_path = ?", [docPath])
  db.run("DELETE FROM documents WHERE doc_path = ?", [docPath])
  for (const table of ["defined_terms", "section_refs", "parties", "doc_relations"])
    db.run(`DELETE FROM ${table} WHERE doc_path = ?`, [docPath])
}

// Re-ingesting a document replaces its rows so the index never holds stale chunks.
export function upsertDocument(
  db: Database,
  docPath: string,
  name: string,
  createdAt: number,
  injectionReport: string | null,
): number {
  db.run("DELETE FROM chunks WHERE doc_path = ?", [docPath])
  db.run("DELETE FROM documents WHERE doc_path = ?", [docPath])
  const result = db.run("INSERT INTO documents (doc_path, name, created_at, injection_report) VALUES (?, ?, ?, ?)", [
    docPath,
    name,
    createdAt,
    injectionReport,
  ])
  return Number(result.lastInsertRowid)
}

// The ingest-time injection findings for one document, for the document text route
// (so read-document can warn the model alongside the full text). NULL means clean.
export function getInjectionReport(db: Database, docPath: string) {
  const row = db.query("SELECT injection_report FROM documents WHERE doc_path = ?").get(docPath) as {
    injection_report: string | null
  } | null
  return row?.injection_report ? (JSON.parse(row.injection_report) as { findings: unknown[] }) : null
}

export function insertChunk(
  db: Database,
  chunk: {
    documentId: number
    docPath: string
    docName: string
    section: string
    chunkIndex: number
    text: string
    charStart: number
    charEnd: number
    embedding: Float32Array
    flagged: boolean
  },
) {
  db.run(
    "INSERT INTO chunks (document_id, doc_path, doc_name, section, chunk_index, text, char_start, char_end, embedding, flagged) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    [
      chunk.documentId,
      chunk.docPath,
      chunk.docName,
      chunk.section,
      chunk.chunkIndex,
      chunk.text,
      chunk.charStart,
      chunk.charEnd,
      Buffer.from(chunk.embedding.buffer, chunk.embedding.byteOffset, chunk.embedding.byteLength),
      chunk.flagged ? 1 : 0,
    ],
  )
}
