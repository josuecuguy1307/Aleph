import { tool } from "@opencode-ai/plugin"
import { Database } from "bun:sqlite"
import { existsSync } from "node:fs"
import path from "node:path"

// doc.haus quote-verification tool. Before the agent presents any text as a
// quotation from a matter document, this tool checks the exact wording against
// the per-matter legal.db that `services/ingest` populates
// (`<matter>/.dochaus/legal.db`), so verification never crosses into another
// matter's privileged material. It answers only from what is stored: a hit
// returns the stored verbatim chunk text and its location so the agent can
// re-quote exactly from storage, and a miss is reported as NOT FOUND — never a
// near match or best guess. This tool is read-only; all writes happen in the
// ingest service.

const SHORT_QUOTE = 20
// Cap how many hits render their full stored chunk: a short or boilerplate
// quote can match one chunk per document across the whole matter, and each
// stored chunk is ~2-4k chars. The chunk text itself is never truncated —
// the verbatim region is the point of the tool.
const MAX_RENDERED_HITS = 5

// The one normalization both sides get before comparing: collapse whitespace
// runs to single spaces, trim, and map curly quotes/apostrophes to straight —
// extracted text mixes both. No case folding: a quote must match case exactly.
function normalize(text: string) {
  return text
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/\s+/g, " ")
    .trim()
}

// Same normalization, plus a map from each normalized index back to the raw
// offset it came from, so a match found in normalized space can be located
// among the chunks' raw char offsets.
function normalizeWithMap(raw: string) {
  let out = ""
  const map: number[] = []
  let spaceAt = -1
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i]
    if (/\s/.test(ch)) {
      if (out.length > 0 && spaceAt === -1) spaceAt = i
      continue
    }
    if (spaceAt !== -1) {
      out += " "
      map.push(spaceAt)
      spaceAt = -1
    }
    out += ch === "“" || ch === "”" ? '"' : ch === "‘" || ch === "’" ? "'" : ch
    map.push(i)
  }
  return { text: out, map }
}

type Chunk = { section: string; text: string; char_start: number; char_end: number }

export default tool({
  description:
    "Verify that a quote appears verbatim in the matter's indexed documents before presenting it. Returns VERIFIED with the stored text and its location (document, section, char offsets) when the exact wording exists, or NOT FOUND when it does not — never a near match. Use this before quoting any document text in an answer or a draft.",
  args: {
    quote: tool.schema.string().describe("The exact text you intend to quote, verbatim"),
    document: tool.schema
      .string()
      .optional()
      .describe("Restrict verification to a single document by its exact name. Omit to check the whole matter."),
  },
  async execute(args, ctx) {
    const dbPath = path.join(ctx.directory, ".dochaus", "legal.db")
    if (!existsSync(dbPath)) {
      return "No documents have been indexed for this matter yet."
    }

    const needle = normalize(args.quote)
    if (!needle) return "The quote is empty after normalization. Pass the exact text you intend to quote."
    const scope = args.document ? `"${args.document}"` : "the matter"
    const shortNote =
      needle.length < SHORT_QUOTE
        ? `\n\nNote: this quote is under ${SHORT_QUOTE} characters — very short quotes match trivially, so a section-level citation is more useful than quote verification.`
        : ""

    const db = new Database(dbPath, { readonly: true })
    const docNames = (
      args.document
        ? db.query("SELECT DISTINCT doc_name FROM chunks WHERE doc_name = ?").all(args.document)
        : db.query("SELECT DISTINCT doc_name FROM chunks ORDER BY doc_name").all()
    ) as { doc_name: string }[]
    if (docNames.length === 0) {
      db.close()
      if (args.document)
        return `No document named "${args.document}" is indexed in this matter. Check the exact name, or omit the document argument to verify against the whole matter.`
      return "No documents have been indexed for this matter yet."
    }

    const hits = docNames.flatMap(({ doc_name }) => {
      const chunks = db
        .query("SELECT section, text, char_start, char_end FROM chunks WHERE doc_name = ? ORDER BY char_start")
        .all(doc_name) as Chunk[]
      const single = chunks.find((c) => normalize(c.text).includes(needle))
      if (single)
        return [
          {
            doc: doc_name,
            section: single.section,
            charStart: single.char_start,
            charEnd: single.char_end,
            verbatim: single.text,
          },
        ]
      // The quote may straddle a chunk boundary: rebuild the document text
      // (skipped gaps were whitespace-only at ingest, so pad with spaces to
      // keep stored offsets valid — see reconstructText in
      // services/ingest/src/structure.ts), search the normalized whole, and
      // map the match back to raw offsets to find the covering chunks.
      const raw = chunks.reduce(
        (acc, c) => (c.char_start > acc.length ? acc + " ".repeat(c.char_start - acc.length) : acc) + c.text,
        "",
      )
      const normalized = normalizeWithMap(raw)
      const at = normalized.text.indexOf(needle)
      if (at === -1) return []
      const rawStart = normalized.map[at]
      const rawEnd = normalized.map[at + needle.length - 1] + 1
      const covering = chunks.filter((c) => c.char_start < rawEnd && c.char_end > rawStart)
      return [
        {
          doc: doc_name,
          section: covering[0].section,
          charStart: covering[0].char_start,
          charEnd: covering[covering.length - 1].char_end,
          verbatim: raw.slice(covering[0].char_start, covering[covering.length - 1].char_end),
        },
      ]
    })
    db.close()

    if (hits.length === 0)
      return (
        `NOT FOUND — this exact text does not appear in ${scope}. Do not present it as a quote. Use search-document to locate the correct wording.` +
        shortNote
      )

    const overflow =
      hits.length > MAX_RENDERED_HITS
        ? `\n\n---\n\n...and ${hits.length - MAX_RENDERED_HITS} more document(s) contain this text — narrow with the document argument.`
        : ""
    return (
      `VERIFIED — the quote appears verbatim in ${hits.length} document(s). Re-quote exactly from the stored text below, never from memory.\n\n` +
      hits
        .slice(0, MAX_RENDERED_HITS)
        .map(
          (h) =>
            `${h.doc} — ${h.section} (chars ${h.charStart}-${h.charEnd})\nStored text of the containing region:\n${h.verbatim}`,
        )
        .join("\n\n---\n\n") +
      overflow +
      shortNote
    )
  },
})
