import { Database } from "bun:sqlite"
import { getMeta, setMeta } from "./db"

// Deterministic contract-structure extraction. Contracts are self-describing
// graphs: defined terms are typographically marked, cross-references are
// numbered, parties sit in the preamble, and amendments name their base
// agreement in formulaic recitals. Everything here is regex over the document's
// extracted text — no model in the loop — so every row carries verbatim text
// plus offsets and a miss is an absent row, never a wrong fact. Bump VERSION
// whenever a pattern changes so existing matters re-extract at next boot
// (server.ts) or ingest (ingest.ts).

export const VERSION = "2"

// Quoted defined term: starts uppercase, single line, sane length. Straight or
// curly quotes — extracted text carries both.
const TERM = `[“"]([A-Z][^”"\\n]{0,60}?)[”"]`
// (the "Term") / (each a "Term") / (collectively, the "Terms") parentheticals.
const PAREN_TERM_RE = new RegExp(
  `\\(\\s*(?:the\\s+|this\\s+|each\\s+an?\\s+|an?\\s+|(?:together|collectively),?\\s+(?:the\\s+)?)?${TERM}\\s*\\)`,
  "g",
)
// "Term" means / shall mean / has the meaning ... definitional sentences.
const MEANS_TERM_RE = new RegExp(`${TERM}\\s+(?:shall\\s+)?(?:means?\\b|shall\\s+have\\s+the\\s+meaning|has\\s+the\\s+meaning)`, "g")

// Numbered cross-references: "Section 8.3", "Sections 2.1(a)", "Article IV",
// "Exhibit A", "Schedule 3". Label shapes: dotted numerics with optional
// letter parentheticals, a bare capital letter, or roman numerals.
const REF_RE =
  /\b(Section|Sections|Article|Articles|Clause|Clauses|Exhibit|Exhibits|Schedule|Schedules|Annex|Appendix)\s+(\d+(?:\.\d+)*(?:\([a-z]+\))*|[A-Z](?![A-Za-z])|[IVXLC]+(?![A-Za-z]))/g

// Corporate-suffix party names, preamble only. Same family as the eval gold
// derivation, widened with common suffixes. Name words carry no internal
// periods — a period would let a match run across a sentence boundary
// ("...Marcus Webb. The Company") — so dotted lead-ins like "U.S." drop off the
// front of a name rather than corrupt it. "Holdings" terminates a name only
// when no real suffix follows ("Cascade Holdings LLC" stays whole), a leading
// article never glues onto a name ("The Company Castellan ..."), and a
// standalone ampersand is a valid connector ("Solara Health & Wellness LLC").
const PARTY_RE =
  /\b((?!The\b)[A-Z][A-Za-z&'\-]+(?: (?:[A-Z][A-Za-z&'\-]+|&)){0,4},? (?:(?:Holdings\s+)?(?:LLC|LLP|L\.P\.|Inc\.|Ltd\.|Limited|Corporation|Corp\.|Company|GmbH|N\.A\.|plc|S\.A\.)|Holdings))(?=[\s,.;)])/g
// A short-name parenthetical following the entity: ... Inc. (the "Borrower").
const ROLE_RE = new RegExp(`^[^\\n]{0,120}?\\(\\s*(?:the\\s+|an?\\s+)?${TERM}\\s*\\)`)

// Amendment recitals are formulaic and live at the top of the document.
const AMENDS_RES = [
  /\bAmendment\s+(?:No\.\s*\d+\s+|Number\s+\d+\s+)?to\s+(?:the\s+|that\s+certain\s+)?([A-Z][^\n,(;]{4,100}?)(?=\s*[,(;\n]|\s+dated\b|\s+entered\b|\s+by\b)/g,
  /\bamends?\s+and\s+restates?\s+(?:in\s+its\s+entirety\s+)?(?:the\s+|that\s+certain\s+)?([A-Z][^\n,(;]{4,100}?)(?=\s*[,(;\n]|\s+dated\b)/g,
]

const PREAMBLE_CHARS = 4000
const RECITAL_CHARS = 2000
const DEFINITION_CAP = 1500

// The paragraph (line, in extracted text) containing an offset — the verbatim
// context stored as a term's definition.
function paragraphAt(text: string, offset: number) {
  const start = text.lastIndexOf("\n", offset) + 1
  const endIndex = text.indexOf("\n", offset)
  const end = endIndex === -1 ? text.length : endIndex
  return { start, end: Math.min(end, start + DEFINITION_CAP) }
}

export function extractDefinedTerms(text: string) {
  const seen = new Map<string, { term: string; definition: string; charStart: number; charEnd: number }>()
  for (const re of [MEANS_TERM_RE, PAREN_TERM_RE]) {
    re.lastIndex = 0
    for (const m of text.matchAll(re)) {
      const span = paragraphAt(text, m.index)
      // Capture group 1 always participates in these patterns; TS cannot see that.
      const term = m[1]!
      const key = `${term}|${span.start}`
      if (seen.has(key)) continue
      seen.set(key, {
        term,
        definition: text.slice(span.start, span.end).trim(),
        charStart: span.start,
        charEnd: span.end,
      })
    }
  }
  return [...seen.values()]
}

export function extractSectionRefs(text: string) {
  return [...text.matchAll(REF_RE)].map((m) => ({
    refKind: m[1]!.replace(/s$/, ""),
    refLabel: m[2]!,
    charStart: m.index,
    charEnd: m.index + m[0].length,
  }))
}

export function extractParties(text: string) {
  const preamble = text.slice(0, PREAMBLE_CHARS)
  const byName = new Map<string, { name: string; role: string | null; charStart: number; charEnd: number }>()
  for (const m of preamble.matchAll(PARTY_RE)) {
    const name = m[1]!.replace(/,$/, "")
    const role = preamble.slice(m.index + m[0].length).match(ROLE_RE)?.[1] ?? null
    const existing = byName.get(name)
    // First mention wins for position; a later mention may still supply the role.
    if (existing) {
      if (!existing.role && role) existing.role = role
      continue
    }
    byName.set(name, { name, role, charStart: m.index, charEnd: m.index + m[0].length })
  }
  return [...byName.values()]
}

export function extractAmendments(text: string) {
  const recitals = text.slice(0, RECITAL_CHARS)
  const seen = new Map<string, { targetName: string; charStart: number; charEnd: number }>()
  for (const re of AMENDS_RES) {
    re.lastIndex = 0
    for (const m of recitals.matchAll(re)) {
      const targetName = m[1]!.trim()
      if (seen.has(targetName)) continue
      seen.set(targetName, { targetName, charStart: m.index, charEnd: m.index + m[0].length })
    }
  }
  return [...seen.values()]
}

export function clearStructure(db: Database, docPath: string) {
  for (const table of ["defined_terms", "section_refs", "parties", "doc_relations"])
    db.run(`DELETE FROM ${table} WHERE doc_path = ?`, [docPath])
}

export function extractStructure(db: Database, docPath: string, docName: string, text: string) {
  clearStructure(db, docPath)
  for (const t of extractDefinedTerms(text))
    db.run(
      "INSERT INTO defined_terms (doc_path, doc_name, term, definition, char_start, char_end) VALUES (?, ?, ?, ?, ?, ?)",
      [docPath, docName, t.term, t.definition, t.charStart, t.charEnd],
    )
  for (const r of extractSectionRefs(text))
    db.run(
      "INSERT INTO section_refs (doc_path, doc_name, ref_kind, ref_label, char_start, char_end) VALUES (?, ?, ?, ?, ?, ?)",
      [docPath, docName, r.refKind, r.refLabel, r.charStart, r.charEnd],
    )
  for (const p of extractParties(text))
    db.run("INSERT INTO parties (doc_path, doc_name, name, role, char_start, char_end) VALUES (?, ?, ?, ?, ?, ?)", [
      docPath,
      docName,
      p.name,
      p.role,
      p.charStart,
      p.charEnd,
    ])
  for (const a of extractAmendments(text))
    db.run(
      "INSERT INTO doc_relations (doc_path, doc_name, relation, target_name, char_start, char_end) VALUES (?, ?, 'amends', ?, ?, ?)",
      [docPath, docName, a.targetName, a.charStart, a.charEnd],
    )
}

// Rebuild a document's extracted text from its chunks. Chunk offsets index into
// the original extraction; whitespace-only slices were skipped at ingest, so pad
// any gaps to keep every stored offset valid against the rebuilt string.
export function reconstructText(db: Database, docPath: string) {
  const rows = db
    .query("SELECT text, char_start FROM chunks WHERE doc_path = ? ORDER BY char_start")
    .all(docPath) as Array<{ text: string; char_start: number }>
  let out = ""
  for (const row of rows) {
    if (row.char_start > out.length) out += " ".repeat(row.char_start - out.length)
    out += row.text
  }
  return out
}

// Backfill matters indexed before structure extraction existed (or before the
// current pattern VERSION). Text comes back out of the chunks themselves, so no
// re-parse of the source file is needed.
export function migrateStructure(db: Database) {
  if (getMeta(db, "structure_version") === VERSION) return 0
  const docs = db.query("SELECT doc_path, name FROM documents").all() as Array<{ doc_path: string; name: string }>
  for (const doc of docs) extractStructure(db, doc.doc_path, doc.name, reconstructText(db, doc.doc_path))
  setMeta(db, "structure_version", VERSION)
  return docs.length
}
