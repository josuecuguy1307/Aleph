// Shared citation shape and rendering, used by the tools that produce citations
// (search-document's vector hits, cite's anchored quotations) and the legal
// plugin (which re-renders the surviving set after span verification). One
// formatter keeps every output identical — including the untrusted-data framing,
// so no path can hand the model a document excerpt without it.

import { FLAGGED_PASSAGE_NOTE, UNTRUSTED_EXCERPT_NOTICE } from "./untrusted"

export type DocumentCitation = {
  documentName: string
  docPath: string
  section: string
  excerpt: string
  charStart: number
  charEnd: number
  // Vector hits from search-document carry a similarity score; quotations the
  // cite tool anchored do not, so score is optional.
  score?: number
  reason?: string
  confidence?: number
  context?: string
  verified?: boolean
  reanchored?: boolean
  // Set when ingest flagged the chunk as containing instruction-like text
  // (see services/ingest/src/sanitize.ts), so the rendering can warn the model
  // before it reads the excerpt.
  flagged?: boolean
}

export function formatCitations(citations: DocumentCitation[]) {
  if (!citations.length) return ""
  const body = citations
    .map((c, i) => {
      const score = c.score === undefined ? "" : ` (score ${c.score.toFixed(3)})`
      const flag = c.flagged ? `\n${FLAGGED_PASSAGE_NOTE}` : ""
      const reason =
        c.reason === undefined
          ? ""
          : `\n   reason: ${c.reason}${c.confidence === undefined ? "" : ` (confidence ${c.confidence}/5)`}`
      return `${i + 1}. [${c.documentName} § ${c.section}]${score}${flag}\n${c.excerpt}${reason}`
    })
    .join("\n\n")
  return `${UNTRUSTED_EXCERPT_NOTICE}\n\n${body}`
}
