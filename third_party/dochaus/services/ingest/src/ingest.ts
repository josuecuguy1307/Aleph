import { writeFileSync } from "node:fs"
import path from "node:path"
import mammoth from "mammoth"
import { openDb, upsertDocument, insertChunk } from "./db"
import { embedChunk, migrateEmbeddings } from "./embed"
import { extractStructure, migrateStructure } from "./structure"
import { pdfToText } from "./pdf"
import { detectInjection, normalizeExtractedText, scanDocxHiddenContent } from "./sanitize"

// ~500 tokens at roughly 4 chars/token.
const CHUNK_CHARS = 2000

// A clause line like "7.2 Termination" or "12. Governing Law".
const CLAUSE_RE = /^\s*(\d+(?:\.\d+)*)[.)]?\s+(.+)$/
// A heading line: short, mostly uppercase, no trailing sentence punctuation.
const HEADING_RE = /^[A-Z0-9][A-Z0-9 ,'\-&/]{2,79}$/

type Section = { label: string; text: string; charStart: number; charEnd: number }

export function sectionize(text: string): Section[] {
  const sections: Section[] = []
  let current: Section = { label: "Preamble", text: "", charStart: 0, charEnd: 0 }
  let offset = 0

  for (const line of text.split("\n")) {
    // markitdown emits Markdown headings; strip the hashes so "## 7.2 Termination"
    // sections the same as a plain "7.2 Termination" line.
    const trimmed = line.trim().replace(/^#{1,6}\s+/, "")
    const isMdHeading = trimmed !== line.trim()
    const clause = trimmed.match(CLAUSE_RE)
    const isHeading = clause || isMdHeading || (trimmed.length > 0 && HEADING_RE.test(trimmed))
    if (isHeading && trimmed.length > 0) {
      if (current.text.trim()) {
        current.charEnd = offset
        sections.push(current)
      }
      const label = clause?.[1] ?? trimmed
      current = { label, text: line + "\n", charStart: offset, charEnd: 0 }
    } else {
      current.text += line + "\n"
    }
    offset += line.length + 1
  }
  if (current.text.trim()) {
    current.charEnd = offset
    sections.push(current)
  }
  return sections
}

function chunkSection(section: Section) {
  const chunks: { text: string; charStart: number; charEnd: number }[] = []
  for (let i = 0; i < section.text.length; i += CHUNK_CHARS) {
    const slice = section.text.slice(i, i + CHUNK_CHARS)
    if (!slice.trim()) continue
    chunks.push({ text: slice, charStart: section.charStart + i, charEnd: section.charStart + i + slice.length })
  }
  return chunks
}

export async function ingestDocument(matterDir: string, fileName: string, buffer: Buffer) {
  const docPath = path.join(matterDir, fileName)
  writeFileSync(docPath, buffer)

  // Untrusted-document defense (issue #17): normalize away invisible Unicode, then
  // scan the visible text and the raw DOCX for injected instructions. Findings are
  // stored on the document and flag overlapping chunks — the text itself is never
  // rewritten, so the lawyer always reviews exactly what the counterparty wrote.
  const extraction = normalizeExtractedText(await extractRawText(fileName, buffer))
  const text = extraction.text
  const findings = [
    ...extraction.findings,
    ...detectInjection(text),
    ...(fileName.toLowerCase().endsWith(".docx") ? scanDocxHiddenContent(buffer) : []),
  ]
  const sections = sectionize(text)

  const db = openDb(matterDir)
  // Never mix vectors from two embedding models in one matter — re-embed any
  // stale chunks before this document's are written (no-op on current DBs).
  // Same for structure rows extracted by an older pattern version.
  await migrateEmbeddings(db)
  migrateStructure(db)
  const documentId = upsertDocument(
    db,
    docPath,
    fileName,
    Date.now(),
    findings.length ? JSON.stringify({ findings }) : null,
  )

  let chunkIndex = 0
  let flaggedChunks = 0
  for (const section of sections) {
    for (const chunk of chunkSection(section)) {
      const embedding = await embedChunk(fileName, section.label, chunk.text)
      const flagged = findings.some(
        (f) => f.charStart !== undefined && f.charEnd !== undefined && f.charStart < chunk.charEnd && f.charEnd > chunk.charStart,
      )
      if (flagged) flaggedChunks++
      insertChunk(db, {
        documentId,
        docPath,
        docName: fileName,
        section: section.label,
        chunkIndex: chunkIndex++,
        text: chunk.text,
        charStart: chunk.charStart,
        charEnd: chunk.charEnd,
        embedding,
        flagged,
      })
    }
  }
  extractStructure(db, docPath, fileName, text)
  db.close()

  return {
    name: fileName,
    docPath,
    sections: sections.length,
    chunks: chunkIndex,
    injection: findings.length ? { findings, flaggedChunks } : null,
  }
}

// Pull plain text from a source document. DOCX goes through mammoth; PDF through
// markitdown/unpdf with an OCR fallback for flat scans (see pdf.ts). Always
// normalized (see sanitize.ts) so every consumer — indexing, the document/template
// text routes, and through them the agents' read-document tool — sees the same
// instruction-stripped text that chunk offsets were computed over.
export async function extractDocumentText(fileName: string, buffer: Buffer) {
  return normalizeExtractedText(await extractRawText(fileName, buffer)).text
}

async function extractRawText(fileName: string, buffer: Buffer) {
  if (fileName.toLowerCase().endsWith(".pdf")) return pdfToText(buffer)
  return (await mammoth.extractRawText({ buffer })).value
}
