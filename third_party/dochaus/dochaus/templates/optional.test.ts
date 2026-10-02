// Optional-clause mechanics against the built nda.docx — exactly the operations
// draft-document runs (omit via deleteSection, keep via the marker-strip fill),
// exercised directly on a Docxodus session so no tool ctx is needed.
// Run from dochaus/: bun test templates/optional.test.ts
import { describe, expect, test } from "bun:test"
import { fileURLToPath } from "node:url"
import path from "node:path"
import { docxodus } from "../lib/docxodus"
import { renumberHeadings } from "../lib/markdown"

const ndaBytes = await Bun.file(
  path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "demo", "templates", "nda.docx"),
).bytes()
const dx = await docxodus()

describe("optional clause markers", () => {
  test("nda exposes the marker as an alternative_clause placeholder and its fill as an instruction", () => {
    const session = dx.openDocxSession(ndaBytes, {})
    const placeholders = session.findPlaceholders()
    session.close()
    expect(
      placeholders.some((p) => p.kind === "alternative_clause" && p.match.text === "[optional: non-solicitation]"),
    ).toBe(true)
    expect(
      placeholders.some((p) => p.kind === "instruction" && p.match.text === "[insert non-solicit period in months]"),
    ).toBe(true)
  })

  test("omit removes the whole clause and leaves the rest intact", () => {
    const session = dx.openDocxSession(ndaBytes, {})
    const anchor = session.findByText("[optional: non-solicitation]", { ignoreWhitespace: true })!
    expect(anchor.kind).toBe("h")
    session.deleteSection(anchor.id)
    // The markdown projection escapes punctuation ("Non\-Solicitation");
    // normalize so the assertions match the readable text.
    const text = session.project().markdown.replaceAll("\\", "")
    const placeholders = session.findPlaceholders().map((p) => p.match.text)
    session.close()
    expect(text).not.toContain("Non-Solicitation")
    expect(text).not.toContain("solicit for employment")
    expect(text).toContain("Entire Agreement")
    expect(placeholders).not.toContain("[insert non-solicit period in months]")
  })

  test("omit then renumber closes the heading-number hole", () => {
    const session = dx.openDocxSession(ndaBytes, {})
    const anchor = session.findByText("[optional: non-solicitation]", { ignoreWhitespace: true })!
    session.deleteSection(anchor.id)
    renumberHeadings(session)
    const text = session.project().markdown.replaceAll("\\", "")
    session.close()
    expect(text).toContain("9. Entire Agreement")
    expect(text).not.toContain("10. Entire Agreement")
    expect(text).toContain("8. Governing Law")
  })

  test("keep strips the marker but leaves the clause", () => {
    const session = dx.openDocxSession(ndaBytes, {})
    session.fillPlaceholders((p) => (p.match.text.startsWith("[optional:") ? "" : null), {
      kinds: dx.PlaceholderKinds.AlternativeClause,
      coalesceWhitespaceAroundEmptyFill: true,
    })
    const text = session.project().markdown.replaceAll("\\", "")
    const placeholders = session.findPlaceholders().map((p) => p.match.text)
    session.close()
    expect(text).toContain("Non-Solicitation")
    expect(text).not.toContain("[optional:")
    expect(placeholders.filter((t) => t.startsWith("[optional:"))).toEqual([])
    expect(placeholders).toContain("[insert non-solicit period in months]")
  })
})
