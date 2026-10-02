import { tool } from "@opencode-ai/plugin"
import { existsSync, readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"
import { docxodus } from "../lib/docxodus"
import { renumberHeadings, splitHeadingBlocks } from "../lib/markdown"
import { restoreMarkdownListNumbering } from "../lib/markdown-list-numbering"

// doc.haus draft-document tool. Creates a NEW Word (.docx) document in the
// current matter — either by filling a template from dochaus/templates, or from
// scratch by composing markdown onto the styled blank seed (_base.docx). Docxodus
// can edit a .docx but not create one from nothing, so every draft starts from
// seed bytes that carry the house style set (Title, Heading 1-3), which is what
// makes markdown headings land as real Word styles.
//
// The finished bytes are handed to the ingest service's upload route, which is
// the single writer for matter documents: it writes the .docx into the matter
// directory AND indexes it (sectionize, chunk, embed), so search-document and the
// web viewer see the new draft immediately.

const templatesDir = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "templates")
const ingestUrl = process.env.INGEST_URL ?? "http://127.0.0.1:0"

export default tool({
  description:
    'Create a new Word (.docx) document in this matter. Two modes: pass "template" (a name from list-templates) plus "fills" — and "omit" for any optional clauses to leave out — to draft from a template, or pass "content" (full document body as markdown — headings, paragraphs, lists, one blank line between blocks) to draft from scratch. Template clauses that are wrong for this matter (unenforceable in the jurisdiction, contradicted by a controlling source document, below market) should be rewritten in this one call via "replaces" — never ship template language you know is wrong just because it is in the template. Call this tool at most ONCE per requested document: anything to change after the draft exists goes through the redline/tracked-changes editing tools on that document, never a second draft-document call producing another version. Returns any placeholders still unfilled so they can be completed with the editing tools.',
  args: {
    name: tool.schema
      .string()
      .describe('File name for the new document, e.g. "Acme NDA.docx" (".docx" is appended if missing)'),
    template: tool.schema.string().optional().describe('Template file name from list-templates, e.g. "nda.docx"'),
    fills: tool.schema
      .array(
        tool.schema.object({
          placeholder: tool.schema
            .string()
            .describe('Exact placeholder text from list-templates, e.g. "[insert state]"'),
          value: tool.schema
            .string()
            .describe(
              "Replacement text (replaces the whole bracketed placeholder). Must be final document text: never put a bracketed placeholder inside a value — a part you cannot fill stays as its own unfilled placeholder.",
            ),
        }),
      )
      .optional()
      .describe("For template mode: the placeholder values to fill in"),
    omit: tool.schema
      .array(tool.schema.string())
      .optional()
      .describe(
        'For template mode: optional clause names to leave OUT of the draft, exactly as listed by list-templates (e.g. "non-solicitation"). Each named clause is removed whole; every other optional clause is kept with its marker stripped.',
      ),
    replaces: tool.schema
      .array(
        tool.schema.object({
          clause: tool.schema
            .string()
            .describe("Text from the template clause to rewrite — a distinctive sentence or phrase within it. Used to locate the paragraph."),
          replacement: tool.schema
            .string()
            .describe("The new clause text. Replaces the whole located paragraph; markdown is supported."),
        }),
      )
      .optional()
      .describe(
        "For template mode: clauses to rewrite in the new draft as clean text (not tracked changes). Each entry locates the paragraph containing `clause` and replaces its entire text with `replacement`. Use for template language that must change for this matter — jurisdiction-invalid clauses, terms the source documents override, missing standard definitions.",
      ),
    content: tool.schema.string().optional().describe("For from-scratch mode: the complete document body as markdown"),
  },
  async execute(args, ctx) {
    if (args.replaces?.some((r) => typeof r.clause !== "string" || !r.clause.trim() || typeof r.replacement !== "string"))
      return 'Draft not created: every replaces entry requires clause and replacement. These replace the entire located paragraph; find/replace sentence edits are not this tool contract. Read the full paragraph and retry with the correct fields.'
    const name = path.basename(args.name.endsWith(".docx") ? args.name : `${args.name}.docx`)
    const target = path.join(ctx.directory, name)
    if (existsSync(target)) return `A document named ${name} already exists in this matter. Pick a different name.`
    if (!args.template && !args.content) return 'Pass either "template" (with "fills") or "content".'

    // Template mode pulls the base bytes from the global library over HTTP (ingest
    // is the single writer over WORKSPACE_ROOT); from-scratch mode uses the repo's
    // styled blank seed (_base.docx), which is never user-visible.
    const templateRes = args.template
      ? await fetch(`${ingestUrl}/templates/content?name=${encodeURIComponent(args.template)}`)
      : undefined
    if (templateRes && !templateRes.ok)
      return `Unknown template: ${args.template}. Call list-templates for the available ones.`
    const sourceBytes = templateRes
      ? new Uint8Array(await templateRes.arrayBuffer())
      : await Bun.file(path.join(templatesDir, "_base.docx")).bytes()

    // Creating a document in the matter is gated on the matter owner's approval,
    // like every other tool that changes matter files. Asked before any Docxodus
    // work so a rejection costs nothing.
    await ctx.ask({
      permission: "draft-document",
      patterns: [target],
      metadata: { document: name, template: args.template, mode: args.template ? "template" : "scratch" },
    })

    const dx = await docxodus()
    const session = dx.openDocxSession(sourceBytes, {})

    if (args.content) {
      // The seed's single empty paragraph is the insertion anchor; the whole
      // markdown body goes in as one multi-block insert, then the seed is dropped.
      const seed = Object.keys(session.project().anchorIndex).find((id) => id.startsWith("p:"))!
      const inserted = session.insertParagraph(seed, "after", splitHeadingBlocks(args.content))
      if (!inserted.success) {
        session.close()
        return `Draft failed: ${inserted.error?.message ?? JSON.stringify(inserted.error)}`
      }
      session.deleteBlock(seed)
    }

    // Omitted optional clauses go first: a clause is its `[optional: name]`-marked
    // heading plus everything under it (deleteSection), or just the marked block
    // when the marker sits on a plain paragraph.
    const missingOmits: string[] = []
    for (const clause of args.omit ?? []) {
      const anchor = session.findByText(`[optional: ${clause}]`, { ignoreWhitespace: true })
      if (!anchor) {
        missingOmits.push(clause)
        continue
      }
      if (anchor.kind === "h") session.deleteSection(anchor.id)
      if (anchor.kind !== "h") session.deleteBlock(anchor.id)
    }

    if (args.fills?.length) {
      const fills = Object.fromEntries(args.fills.map((f) => [f.placeholder, f.value]))
      session.fillPlaceholders((p) => fills[p.match.text] ?? null)
    }

    // Clause rewrites run after fills so a `clause` anchor can include filled-in
    // text, and before the optional-marker strip so a rewrite may target a kept
    // optional clause by its visible text. Same locate semantics as the redline
    // tool: match the block's flat text whitespace-tolerantly, then swap the
    // whole paragraph (insert the replacement after it, delete the original).
    const missedReplaces: string[] = []
    for (const r of args.replaces ?? []) {
      const anchor = session.findByText(r.clause, { ignoreWhitespace: true })
      if (!anchor) {
        missedReplaces.push(r.clause)
        continue
      }
      const inserted = session.insertParagraph(anchor.id, "after", splitHeadingBlocks(r.replacement))
      if (!inserted.success) {
        missedReplaces.push(r.clause)
        continue
      }
      session.deleteBlock(anchor.id)
    }

    // Kept optional clauses lose their marker so it never reaches the draft.
    session.fillPlaceholders((p) => (p.match.text.startsWith("[optional:") ? "" : null), {
      kinds: dx.PlaceholderKinds.AlternativeClause,
      coalesceWhitespaceAroundEmptyFill: true,
    })

    // An omitted clause leaves a hole in the manually numbered headings ("8."
    // followed by "10."); close the sequence up.
    if ((args.omit?.length ?? 0) > missingOmits.length) renumberHeadings(session)

    const remaining = session.findPlaceholders().map((p) => p.match.text)
    const saved = session.save()
    session.close()
    const bytes = args.content ? restoreMarkdownListNumbering(saved, args.content) : saved

    // Upload through ingest rather than writing the file directly: its upload
    // route both writes the canonical .docx and indexes it for search.
    const matter = JSON.parse(readFileSync(path.join(ctx.directory, "matter.json"), "utf8")) as { id: string }
    const form = new FormData()
    form.append("file", new File([bytes], name))
    const res = await fetch(`${ingestUrl}/matters/${matter.id}/documents`, { method: "POST", body: form })
    if (!res.ok) return `Draft composed but ingest upload failed (${res.status}): ${await res.text()}`

    return {
      title: `Drafted ${name}`,
      output: [
        `Created ${name} in this matter${args.template ? ` from template ${args.template}` : " from scratch"}.`,
        remaining.length
          ? `Placeholders still unfilled: ${remaining.join(", ")}. Fill them with the editing tools or leave them for the lawyer.`
          : "No placeholders remain.",
        missingOmits.length
          ? `Optional clauses not found (left as-is): ${missingOmits.join(", ")}. Check the names against list-templates.`
          : "",
        missedReplaces.length
          ? `Clause rewrites whose anchor text was not found (template language kept as-is): ${missedReplaces.map((c) => JSON.stringify(c)).join(", ")}. Locate the exact clause text with read-document and retry, or fix the draft with the editing tools.`
          : "",
      ]
        .filter(Boolean)
        .join(" "),
      metadata: {
        document: target,
        template: args.template,
        remainingPlaceholders: remaining,
        omitted: args.omit,
        replaced: (args.replaces ?? []).filter((r) => !missedReplaces.includes(r.clause)).map((r) => r.clause),
        missedReplaces,
      },
    }
  },
})
