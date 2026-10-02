import { statSync } from "node:fs"
import { normalizeExtractedText } from "./untrusted"

// Live-document extraction shared by the citation plugin (which re-checks every
// citation's span against the current file) and the `cite` tool (which anchors a
// quotation the model intends to use). Both need the exact same text the ingest
// service indexed, so the logic lives here once.

const CACHE_LIMIT = 64
// Extraction is per-document, not per-citation: cache by path, invalidate on
// mtime so an accepted redline or re-upload is picked up immediately.
const textCache = new Map<string, { mtimeMs: number; text: string }>()

export async function liveText(docPath: string) {
  const mtimeMs = statSync(docPath).mtimeMs
  const hit = textCache.get(docPath)
  if (hit && hit.mtimeMs === mtimeMs) return hit.text
  const buffer = Buffer.from(await Bun.file(docPath).arrayBuffer())
  // Ingest computes offsets by accumulating `line + "\n"` over the normalized
  // extracted text, which equals the normalized raw extraction plus exactly one
  // trailing newline — mirror both steps here or every chunk fails verification.
  const text = normalizeExtractedText(await extract(docPath, buffer)) + "\n"
  if (!textCache.has(docPath) && textCache.size >= CACHE_LIMIT) {
    const oldest = textCache.keys().next().value
    if (oldest !== undefined) textCache.delete(oldest)
  }
  textCache.set(docPath, { mtimeMs, text })
  return text
}

// Locate a quotation in the live text. Exact match first; if that fails, fall
// back to a whitespace-tolerant search so a quote that only differs in run-length
// of spaces/newlines (mammoth and pdf.js normalize whitespace differently than a
// human copying text) still anchors. The returned `excerpt` is always the RAW
// matched span from the live text, never the caller's input — downstream span
// checks compare against the live document, so the stored excerpt must be what
// the document actually contains. When `near` is given (the plugin re-anchoring a
// span an edit shifted), the occurrence nearest that offset wins, since it is
// almost certainly the same passage; otherwise the first match wins.
export function findQuote(text: string, quote: string, near?: number) {
  const matches = [...text.matchAll(quoteRegExp(quote))]
  if (!matches.length) return undefined
  const best =
    near === undefined
      ? matches[0]
      : matches.reduce((a, b) => (Math.abs(b.index - near) < Math.abs(a.index - near) ? b : a))
  return { start: best.index, end: best.index + best[0].length, excerpt: best[0] }
}

// Match the quote exactly where possible, but tolerate differing whitespace runs.
// Escape every regex metacharacter, then let any whitespace run stand in for any
// other so a copied quote anchors despite extractor-specific line breaks.
function quoteRegExp(quote: string) {
  return new RegExp(quote.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+"), "g")
}

// Must stay in lockstep with extractDocumentText in services/ingest/src/ingest.ts:
// same extractors, same options, or offsets stop lining up.
async function extract(docPath: string, buffer: Buffer) {
  if (docPath.toLowerCase().endsWith(".pdf")) {
    const { extractText, getDocumentProxy } = await import("unpdf")
    const { text } = await extractText(await getDocumentProxy(new Uint8Array(buffer)), { mergePages: true })
    return text
  }
  const { default: mammoth } = await import("mammoth")
  return (await mammoth.extractRawText({ buffer })).value
}
