import { docxodus } from "./docxodus"
import type { RedlineRow } from "./db"

// Replay and bake pending redline proposals against a clean .docx.
//
// The canonical document on disk is always the accepted ("clean") state. A
// proposal records how to reproduce one edit — a surgical find/replace ('phrase')
// or a whole-paragraph rewrite ('clause') — located the same way the dochaus tools
// located it originally. We never store offsets: text is re-resolved against the
// live document every time, so edits stay valid as the document changes underneath.

type Session = ReturnType<Awaited<ReturnType<typeof docxodus>>["openDocxSession"]>

// Reproduce one proposal's edit on an open session. Returns an error message
// (rather than throwing) when the anchor text can no longer be found — e.g. an
// earlier proposal in the same replay already rewrote the passage this one
// anchors to. Callers decide whether that is fatal: the redlined view skips the
// row and renders the rest; accept must fail loudly rather than bake a partial set.
function applyProposal(session: Session, row: RedlineRow): { ok: true } | { ok: false; error: string } {
  if (row.scope === "clause") {
    const target = session.findByText(row.find_text, { ignoreWhitespace: true })
    if (!target) return { ok: false, error: `Clause no longer found for redline #${row.id}: ${JSON.stringify(row.find_text)}` }
    const result = session.replaceText(target.id, row.new_text)
    if (!result.success) return { ok: false, error: `Redline #${row.id} failed: ${result.error?.message ?? "unknown error"}` }
    return { ok: true }
  }

  const targets = session.findAllByText(row.find_text)
  if (!targets.length) return { ok: false, error: `Text no longer found for redline #${row.id}: ${JSON.stringify(row.find_text)}` }
  const results = targets.flatMap((t) => session.replaceTextRange(t.id, row.find_text, row.new_text))
  const failed = results.find((r) => !r.success)
  if (failed) return { ok: false, error: `Redline #${row.id} failed: ${failed.error?.message ?? "unknown error"}` }
  return { ok: true }
}

// The redlined view the viewer renders: clean document compared against the same
// document with every pending proposal applied, so Docxodus emits native w:ins/w:del
// the browser paints green/red. With no pending rows the compare is a no-op and the
// clean document round-trips unchanged.
//
// A proposal that no longer resolves (a leftover collision the propose-time check
// did not retire) is skipped, not fatal: the view must render the proposals that
// do apply rather than 500 the whole document. Skips are logged for the operator.
export async function buildRedlined(original: Uint8Array, rows: RedlineRow[]): Promise<Uint8Array> {
  const dx = await docxodus()
  if (!rows.length) return original
  const session = dx.openDocxSession(original, {})
  const applied = rows.filter((row) => {
    const result = applyProposal(session, row)
    if (!result.ok) console.warn(`[redline] skipping in redlined view — ${result.error}`)
    return result.ok
  })
  const modified = session.save()
  session.close()
  if (!applied.length) return original
  const authors = [...new Set(applied.map((r) => r.author))]
  return dx.compareDocuments(original, modified, { authorName: authors.length === 1 ? authors[0] : "doc.haus" })
}

// Bake the given proposals into the clean document, returning new canonical bytes
// with the edits applied and no tracked changes — the new accepted state. Accept
// fails loudly: a proposal that no longer resolves throws rather than silently
// baking a partial set into the canonical document.
export async function bake(original: Uint8Array, rows: RedlineRow[]): Promise<Uint8Array> {
  const dx = await docxodus()
  const session = dx.openDocxSession(original, {})
  try {
    for (const row of rows) {
      const result = applyProposal(session, row)
      if (!result.ok) throw new Error(result.error)
    }
    return session.save()
  } finally {
    session.close()
  }
}
