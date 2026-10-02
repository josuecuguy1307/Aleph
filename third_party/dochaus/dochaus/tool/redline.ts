import { tool } from "@opencode-ai/plugin"
import { existsSync } from "node:fs"
import path from "node:path"
import { docxodus } from "../lib/docxodus"
import { recordRedline, pendingRedlinesForDoc, conflictingRedlines, supersedeRedlines } from "../lib/redlines"

// doc.haus redline tool. Proposes rewriting a whole clause — the paragraph a
// search-document citation points at — as a tracked change a reviewer accepts or
// rejects in the doc.haus app.
//
// This is the citation-driven, clause-level counterpart to the surgical
// find/replace tools (word-integration, tracked-changes): `clause` locates the
// paragraph and the whole paragraph is rewritten to `replacement`. We match on
// the block's flat text, whitespace-tolerant, because citation excerpts come
// from a different text extraction (mammoth) than Docxodus' own projection and
// their spacing/char offsets don't align — so we only ever LOCATE the block, we
// never offset-index into it.
//
// The proposal is recorded against the matter's index; the canonical .docx stays
// clean (the accepted state) until a reviewer accepts, when ingest bakes the edit
// in. So here we only locate the clause and capture its current text — we never
// modify the file.

export default tool({
  description:
    "Propose rewriting a whole clause as a tracked change, using a passage retrieved from search-document. Locates the paragraph containing `clause` and proposes replacing its entire text with `replacement`, attributed to an author. The change is recorded as a pending redline the user reviews and accepts or rejects in the doc.haus app — the document is not modified until they accept. Use this to redline a clause you found as a citation; use tracked-changes for a surgical word/phrase swap.",
  args: {
    document: tool.schema.string().describe("Document file name within the matter (the docPath from a citation)"),
    clause: tool.schema
      .string()
      .describe("Text from the clause to rewrite — the citation excerpt, or a sentence within it. Used to locate the paragraph."),
    replacement: tool.schema
      .string()
      .describe("The new clause text. Replaces the whole located paragraph; markdown is supported."),
    author: tool.schema.string().optional().describe("Name to attribute the tracked change to (default: doc.haus)"),
  },
  async execute(args, ctx) {
    const file = path.isAbsolute(args.document) ? args.document : path.join(ctx.directory, args.document)
    if (!existsSync(file)) return `Document not found in this matter: ${args.document}`

    const dx = await docxodus()
    const session = dx.openDocxSession(await Bun.file(file).bytes(), {})

    const target = session.findByText(args.clause, { ignoreWhitespace: true })
    if (!target) {
      session.close()
      return `Clause not found in ${path.basename(file)}: ${JSON.stringify(args.clause)}`
    }
    // projectAnchor emits the block's addressing token (`{#p:body:UNID}`) ahead of
    // its text and takes no setting to suppress it — strip every `{#…}` marker so
    // the captured clause is the human-readable text the reviewer sees struck
    // through, not the engine's internal anchor.
    const oldText = session.projectAnchor(target.id).markdown.replace(/\{#[^}]*\}/g, "").trim()
    session.close()

    // A clause rewrite replaces the whole paragraph, so any pending proposal on
    // the same paragraph would be replayed against text this one erases — the
    // collision that 500s the redlined view. The newest edit wins: record this
    // one, retire the ones it supersedes. The model sees what it replaced so it
    // can reason about the running state of the negotiation.
    const conflicts = conflictingRedlines(pendingRedlinesForDoc(ctx.directory, file), {
      anchorId: target.id,
      scope: "clause",
      findText: args.clause,
    })

    const author = args.author ?? "doc.haus"
    // Recording the proposal is gated on the matter owner's approval (permission
    // "redline" in opencode.json) — the redline review queue is itself a work
    // product, so the assistant must not stack proposals into it unasked.
    // ctx.ask blocks until they reply and throws on reject. "Always" approves
    // future proposals against this document only.
    await ctx.ask({
      permission: "redline",
      patterns: [file],
      always: [file],
      metadata: { document: path.basename(file), clause: args.clause, replacement: args.replacement, author },
    })
    const id = recordRedline(ctx.directory, {
      docPath: file,
      docName: path.basename(file),
      scope: "clause",
      findText: args.clause,
      oldText,
      newText: args.replacement,
      author,
      anchorId: target.id,
    })
    supersedeRedlines(ctx.directory, conflicts.map((c) => c.id))

    const superseded = conflicts.length
      ? ` Supersedes pending redline${conflicts.length === 1 ? "" : "s"} ${conflicts.map((c) => `#${c.id}`).join(", ")} on the same clause — only this latest rewrite stays pending.`
      : ""
    return {
      title: `Proposed redline in ${path.basename(file)}`,
      output: `Proposed rewriting the clause matching ${JSON.stringify(args.clause)} in ${path.basename(file)}, attributed to ${author}. Recorded as pending redline #${id} — the user reviews and accepts or rejects it in the doc.haus app.${superseded}`,
      metadata: { document: file, clause: args.clause, oldText, replacement: args.replacement, anchor: target.id, author, redline: id, superseded: conflicts.map((c) => c.id) },
    }
  },
})
