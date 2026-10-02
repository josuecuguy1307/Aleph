import { tool } from "@opencode-ai/plugin"
import { Database } from "bun:sqlite"
import { existsSync } from "node:fs"
import path from "node:path"

// doc.haus amendment-chain lookup. Reads the doc_relations rows that
// services/ingest extracts deterministically from amendment recitals (see
// services/ingest/src/structure.ts) and reports which matter documents amend
// which, so the agent reads the operative version first instead of an amended
// base. Everything returned is verbatim database content plus locations: the
// target name exactly as the amendment states it, and the recital span sliced
// from the stored chunk text at the relation row's offsets. Resolving a stated
// target to an indexed document is a name/defined-term match reported honestly
// — zero or several plausible documents is reported as such, never forced to
// one. This tool is read-only; all writes happen in the ingest service.

type RelationRow = {
  doc_path: string
  doc_name: string
  relation: string
  target_name: string
  char_start: number
  char_end: number
}

type DocRow = { doc_path: string; name: string; created_at: number }

type Resolution =
  | { kind: "resolved"; doc: DocRow }
  | { kind: "ambiguous"; names: string[] }
  | { kind: "unmatched" }

// A document resolves a stated target when its indexed name contains every
// token of the target (NOCASE), or when it defines the target as a term (a
// base agreement is typically defined as e.g. "Original Credit Agreement"
// inside an amendment, so the term-defining definer is the amendment that the
// later amendment is actually pointing back through). The amending document
// itself is excluded, and documents that themselves declare an 'amends'
// relation are dropped whenever a non-amending candidate exists — an
// "Amendment No. 2 to Credit Agreement" contains the tokens of "Credit
// Agreement" but is not it. Anything still unclear is reported, never forced.
function resolveTarget(db: Database, target: RelationRow, docs: DocRow[], relations: RelationRow[]): Resolution {
  const tokens = target.target_name
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => /[\p{L}\p{N}]/u.test(t))
  const definerPaths = new Set(
    (
      db
        .query("SELECT DISTINCT doc_path FROM defined_terms WHERE term = ? COLLATE NOCASE")
        .all(target.target_name) as { doc_path: string }[]
    ).map((r) => r.doc_path),
  )
  const candidates = docs.filter(
    (d) =>
      d.doc_path !== target.doc_path &&
      (tokens.every((t) => d.name.toLowerCase().includes(t)) || definerPaths.has(d.doc_path)),
  )
  const amenderPaths = new Set(relations.map((r) => r.doc_path))
  const nonAmending = candidates.filter((d) => !amenderPaths.has(d.doc_path))
  const pool = nonAmending.length > 0 ? nonAmending : candidates
  if (pool.length === 1) return { kind: "resolved", doc: pool[0] }
  if (pool.length > 1) return { kind: "ambiguous", names: pool.map((d) => d.name) }
  return { kind: "unmatched" }
}

// The verbatim text at start..end of a document's extracted text, rebuilt from
// its stored chunks the same way services/ingest/src/structure.ts
// reconstructText does (chunk offsets index into the original extraction;
// whitespace-only gaps were skipped at ingest and are re-padded). Only stored
// chunk text is returned — never anything synthesized.
function verbatimSpan(db: Database, docPath: string, start: number, end: number) {
  const rows = db
    .query("SELECT text, char_start FROM chunks WHERE doc_path = ? AND char_start < ? ORDER BY char_start")
    .all(docPath, end) as { text: string; char_start: number }[]
  let rebuilt = ""
  for (const row of rows) {
    if (row.char_start > rebuilt.length) rebuilt += " ".repeat(row.char_start - rebuilt.length)
    rebuilt += row.text
  }
  return rebuilt.slice(start, end).trim()
}

export default tool({
  description:
    "Show amendment relationships between this matter's documents: which document amends which, the verbatim recital stating it, and which document to read first. Use this before relying on any agreement that may have been amended. Returns only extracted facts; if a relationship is not listed, verify with search-document.",
  args: {
    document: tool.schema
      .string()
      .optional()
      .describe(
        "Exact name of an indexed document to trace from (as amender or as amended target). Omit to list every amendment relationship in the matter.",
      ),
  },
  async execute(args, ctx) {
    const dbPath = path.join(ctx.directory, ".dochaus", "legal.db")
    if (!existsSync(dbPath)) {
      return "No documents have been indexed for this matter yet."
    }

    const db = new Database(dbPath, { readonly: true })
    const relations = db
      .query("SELECT doc_path, doc_name, relation, target_name, char_start, char_end FROM doc_relations")
      .all() as RelationRow[]
    if (relations.length === 0) {
      db.close()
      return (
        "No amendment relationships were extracted for this matter. " +
        "Extraction only covers formulaic amendment recitals (\"Amendment No. _ to ...\", \"amends and restates ...\"); " +
        "if you suspect an amendment phrased differently, use the search-document tool to look for it."
      )
    }

    const docs = db.query("SELECT doc_path, name, created_at FROM documents").all() as DocRow[]
    const resolved = relations.map((rel) => ({
      rel,
      resolution: resolveTarget(db, rel, docs, relations),
      recital: verbatimSpan(db, rel.doc_path, rel.char_start, rel.char_end),
    }))

    // Group relations by target (the resolved document, or the stated name
    // when unresolved), then merge transitively from root targets: a target
    // that is itself an amender continues another document's chain, so an
    // amendment-of-an-amendment lands in the base document's chain rather than
    // starting a second one. The seen set terminates a degenerate cycle.
    const groups = new Map<string, typeof resolved>()
    for (const entry of resolved) {
      const key =
        entry.resolution.kind === "resolved"
          ? entry.resolution.doc.doc_path
          : `unresolved:${entry.rel.target_name.toLowerCase()}`
      groups.set(key, [...(groups.get(key) ?? []), entry])
    }
    const amenderPaths = new Set(resolved.map((entry) => entry.rel.doc_path))
    const flatten = (key: string, seen: Set<string>): typeof resolved => {
      if (seen.has(key)) return []
      seen.add(key)
      return (groups.get(key) ?? []).flatMap((entry) => [entry, ...flatten(entry.rel.doc_path, seen)])
    }
    const createdAt = new Map(docs.map((d) => [d.doc_path, d.created_at]))
    const chains = [...groups.keys()]
      .filter((key) => !amenderPaths.has(key))
      .map((key) => ({
        key,
        entries: flatten(key, new Set()).sort(
          (a, b) => (createdAt.get(a.rel.doc_path) ?? 0) - (createdAt.get(b.rel.doc_path) ?? 0),
        ),
      }))

    const matchesArg = (entry: (typeof resolved)[number]) =>
      !args.document ||
      entry.rel.doc_name.toLowerCase() === args.document.toLowerCase() ||
      entry.rel.target_name.toLowerCase() === args.document.toLowerCase() ||
      (entry.resolution.kind === "resolved" && entry.resolution.doc.name.toLowerCase() === args.document.toLowerCase())
    const selected = chains.filter((chain) => chain.entries.some(matchesArg))
    if (selected.length === 0) {
      db.close()
      return args.document
        ? `No extracted amendment relationship involves "${args.document}" ` +
            `(the matter has ${relations.length} extracted amendment relationship(s) on other documents). ` +
            "Extraction only covers formulaic amendment recitals; use the search-document tool to check for amendment language phrased differently."
        : `${relations.length} amendment relationship(s) were extracted for this matter, but no chain root could be derived from them (every amended target is itself an amending document). ` +
            "Use the search-document tool to inspect the amendment recitals directly."
    }

    const blocks = selected.map((chain) => {
      const ordered = chain.entries
      const base = chain.key.startsWith("unresolved:")
        ? `"${(groups.get(chain.key) ?? ordered)[0].rel.target_name}" (as stated; not matched to any indexed document)`
        : (docs.find((d) => d.doc_path === chain.key)?.name ?? chain.key)
      const lines = ordered.map((entry) => {
        const target =
          entry.resolution.kind === "resolved"
            ? `resolved to ${entry.resolution.doc.name}`
            : entry.resolution.kind === "ambiguous"
              ? `not matched to any indexed document (ambiguous between: ${entry.resolution.names.join(", ")})`
              : "not matched to any indexed document"
        const recital = entry.recital
          ? `"${entry.recital}"`
          : "recital text not recoverable from the index at these offsets"
        return (
          `- ${entry.rel.doc_name} ${entry.rel.relation} "${entry.rel.target_name}" — ${target}\n` +
          `  Recital (chars ${entry.rel.char_start}..${entry.rel.char_end} of ${entry.rel.doc_name}): ${recital}`
        )
      })
      const latest = ordered[ordered.length - 1]
      return (
        `Chain: ${base} is amended (and possibly superseded) by:\n` +
        lines.join("\n") +
        `\nRead ${latest.rel.doc_name} first — it is the most recently indexed amending document. ` +
        "Whether each amendment restates the base in its entirety or merely modifies specific provisions must be confirmed in its recitals, quoted verbatim above."
      )
    })
    db.close()

    return blocks.join("\n\n")
  },
})
