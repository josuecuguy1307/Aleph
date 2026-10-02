import type { DocxSession } from "docxodus"

// Docxodus's insertParagraph splits markdown into blocks on blank lines only,
// but in markdown an ATX heading line is its own block even when the body
// starts on the very next line. Without this, "## 1. Term\nThe term is..."
// collapses into ONE heading-styled paragraph carrying the whole clause body —
// which is how the corrupt employment-agreement template happened. Normalize
// before every insert so a heading line always lands as its own block.
export function splitHeadingBlocks(markdown: string) {
  return markdown
    .split("\n")
    .map((line) => (/^ {0,3}#{1,6} /.test(line) ? `\n${line.trim()}\n` : line))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

// A template defect multiplies into every document later drafted from it, so
// agent-authored template bodies are linted before creation. These are the
// defects no model is needed for: a duplicate placeholder collapses two
// different terms into one fill value, a bare [___] cannot be filled by a
// descriptive name, a heading-number gap ships in every draft, and a duplicate
// optional-clause short-name makes omit ambiguous.
export function lintTemplateBody(markdown: string) {
  const brackets = markdown.match(/\[[^\]\n]+\]/g) ?? []
  const markers = brackets.filter((b) => b.startsWith("[optional:"))
  const fills = brackets.filter((b) => !b.startsWith("[optional:"))
  const dupes = (list: string[]) => [...new Set(list.filter((b, i) => list.indexOf(b) !== i))]
  const numbers = markdown
    .split("\n")
    .map((line) => line.match(/^ {0,3}#{2,6} (\d+)\./)?.[1])
    .filter((n): n is string => n !== undefined)
  const numberingBreak = numbers.findIndex((n, i) => n !== `${i + 1}`)
  return [
    ...dupes(fills).map((b) => `placeholder ${b} appears more than once — every placeholder must be unique`),
    ...fills.filter((b) => /^\[_+\]$/.test(b)).map((b) => `bare ${b} — use a descriptive [insert ...] placeholder`),
    ...dupes(markers).map((b) => `optional-clause marker ${b} appears more than once — short-names must be unique`),
    ...(numberingBreak === -1
      ? []
      : [`heading numbering breaks at "${numbers[numberingBreak]}." — expected ${numberingBreak + 1}`]),
  ]
}

// Templates number their clause headings in the heading text itself ("9.
// Non-Solicitation"), so deleting an optional clause leaves a hole in the
// sequence ("8." followed by "10."). Renumber every such heading to its
// position in document order. Body cross-references by section number are not
// rewritten.
export function renumberHeadings(session: DocxSession) {
  session
    .findByKind("h")
    .filter((h) => /^\d+\. /.test(h.textPreview))
    .forEach((h, i) => {
      const current = h.textPreview.match(/^(\d+)\./)![1]
      if (current !== `${i + 1}`) session.replaceTextRange(h.id, `${current}.`, `${i + 1}.`, { maxReplacements: 1 })
    })
}
