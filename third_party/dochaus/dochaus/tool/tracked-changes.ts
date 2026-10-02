import { tool } from "@opencode-ai/plugin"
import { existsSync } from "node:fs"
import path from "node:path"
import { docxodus } from "../lib/docxodus"
import { recordRedline, pendingRedlinesForDoc, conflictingRedlines, supersedeRedlines } from "../lib/redlines"

// doc.haus tracked-changes tool. Proposes a surgical find/replace edit to the
// matter's canonical Word (.docx) document as a tracked change, attributed to an
// author, that a reviewer accepts or rejects in the doc.haus app.
//
// The proposal is recorded against the matter's index; the canonical .docx stays
// clean (the accepted state) until a reviewer accepts, when ingest bakes the edit
// in. So here we only confirm the text exists — we never modify the file.

export default tool({
  description:
    "Propose a surgical edit to the matter's canonical Word (.docx) document as a tracked change. Finds exact text and proposes replacing it, attributed to an author. The change is recorded as a pending redline the user reviews and accepts or rejects in the doc.haus app — the document is not modified until they accept. Use this for a word/phrase swap; use redline for a whole-clause rewrite, and word-integration for silent (non-tracked) edits.",
  args: {
    document: tool.schema.string().describe("Document file name within the matter (the docPath from a citation)"),
    find: tool.schema.string().describe("The exact text to find"),
    replace: tool.schema.string().describe("The replacement text"),
    author: tool.schema.string().optional().describe("Name to attribute the tracked change to (default: doc.haus)"),
  },
  async execute(args, ctx) {
    const file = path.isAbsolute(args.document) ? args.document : path.join(ctx.directory, args.document)
    if (!existsSync(file)) return `Document not found in this matter: ${args.document}`

    const dx = await docxodus()
    const session = dx.openDocxSession(await Bun.file(file).bytes(), {})

    const targets = session.findAllByText(args.find)
    if (!targets.length) {
      session.close()
      return `Text not found in ${path.basename(file)}: ${JSON.stringify(args.find)}`
    }
    const anchor = targets[0].id
    session.close()

    // Retire any pending proposal this edit collides with — a clause rewrite on the
    // same paragraph, or another phrase edit whose text overlaps — so the replay
    // that builds the redlined view never anchors to text an earlier proposal
    // already erased. Independent phrase edits in the paragraph are left untouched.
    const conflicts = conflictingRedlines(pendingRedlinesForDoc(ctx.directory, file), {
      anchorId: anchor,
      scope: "phrase",
      findText: args.find,
    })

    const author = args.author ?? "doc.haus"
    // Recording the proposal is gated on the matter owner's approval (permission
    // "tracked-changes" in opencode.json) — the redline review queue is itself a
    // work product, so the assistant must not stack proposals into it unasked.
    // ctx.ask blocks until they reply and throws on reject. "Always" approves
    // future proposals against this document only.
    await ctx.ask({
      permission: "tracked-changes",
      patterns: [file],
      always: [file],
      metadata: { document: path.basename(file), find: args.find, replace: args.replace, author },
    })
    const id = recordRedline(ctx.directory, {
      docPath: file,
      docName: path.basename(file),
      scope: "phrase",
      findText: args.find,
      oldText: args.find,
      newText: args.replace,
      author,
      anchorId: anchor,
    })
    supersedeRedlines(ctx.directory, conflicts.map((c) => c.id))

    const superseded = conflicts.length
      ? ` Supersedes pending redline${conflicts.length === 1 ? "" : "s"} ${conflicts.map((c) => `#${c.id}`).join(", ")} on the same passage — only this latest edit stays pending.`
      : ""
    return {
      title: `Proposed tracked change in ${path.basename(file)}`,
      output: `Proposed replacing ${JSON.stringify(args.find)} with ${JSON.stringify(args.replace)} in ${path.basename(file)} (${targets.length} occurrence(s)), attributed to ${author}. Recorded as pending redline #${id} — the user reviews and accepts or rejects it in the doc.haus app.${superseded}`,
      metadata: { document: file, find: args.find, replace: args.replace, matches: targets.length, author, redline: id, superseded: conflicts.map((c) => c.id) },
    }
  },
})
