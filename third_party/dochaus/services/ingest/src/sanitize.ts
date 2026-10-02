import { inflateRawSync } from "node:zlib"

// Untrusted-document defense (issue #17). Legal documents — above all anything
// received from a counterparty — are adversarial input: their text flows into the
// agent context via retrieval, so a document can carry instructions aimed at the
// model rather than the reader. This module (1) normalizes extracted text so
// invisible Unicode cannot smuggle instructions past a human reviewer, (2) detects
// instruction-like patterns so chunks are flagged before they reach the model, and
// (3) scans the raw DOCX XML for content hidden from the rendered page.
// Detection flags, never blocks or rewrites visible text: a lawyer must always see
// the document exactly as the counterparty wrote it. Full analysis of what this
// does and does not stop lives in docs/threat-model.md.

export type InjectionFinding = {
  rule: string
  detail: string
  snippet?: string
  // Offsets into the normalized extracted text (the same text chunks store), so a
  // finding can be mapped onto the chunks that contain it. Document-level findings
  // (invisible characters, hidden DOCX runs) carry no span.
  charStart?: number
  charEnd?: number
}

const INVISIBLE_CATEGORIES = [
  {
    rule: "bidi-control",
    detail: "Unicode bidirectional controls that can visually reorder or mask text",
    re: /[\u200E\u200F\u202A-\u202E\u2066-\u2069]/gu,
  },
  {
    rule: "invisible-tag",
    detail: "invisible Unicode tag characters (a known instruction-smuggling channel)",
    re: /[\u{E0000}-\u{E007F}]/gu,
  },
  {
    rule: "zero-width",
    detail: "zero-width characters invisible to a human reader",
    re: /[\u200B-\u200D\u2060-\u2064\uFEFF]/gu,
  },
]

// Everything the categories above match, plus soft hyphens and stray C0 controls
// (kept out of the report — they occur in honest documents) but never \t, \n or \r,
// which line-ending normalization handles.
const STRIP_RE =
  /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F\u00AD\u200B-\u200F\u202A-\u202E\u2060-\u2064\u2066-\u2069\uFEFF\u{E0000}-\u{E007F}]/gu

// Normalize text straight off the extractor: report invisible characters that can
// hide instructions from a reviewer, then strip them (and normalize line endings)
// so the indexed text contains only what a human can see. Offsets everywhere
// downstream (sections, chunks, citations) are computed over this normalized text.
// Must stay in lockstep with normalizeExtractedText in dochaus/lib/untrusted.ts,
// which the citation verifier applies to live re-extractions of the same files.
export function normalizeExtractedText(raw: string) {
  const findings: InjectionFinding[] = INVISIBLE_CATEGORIES.flatMap((category) => {
    const count = [...raw.matchAll(category.re)].length
    return count ? [{ rule: category.rule, detail: `${category.detail} (${count} removed)` }] : []
  })
  return { text: raw.replace(/\r\n?/g, "\n").replace(STRIP_RE, ""), findings }
}

// Instruction-shaped text inside a document body. Heuristic by design: each rule
// targets phrasing that has no business in a legal document but is the bread and
// butter of prompt injection. Phrases that are routine in legal drafting ("act as
// agent for", "per your instructions", "the model clause") are deliberately not
// matched — false positives erode a lawyer's trust in the flag.
const PATTERN_RULES = [
  {
    rule: "instruction-override",
    detail: "text that tries to override the assistant's instructions",
    re: /\b(ignore|disregard|forget|override)\b[^.\n]{0,60}\b(previous|prior|above|earlier|all|any|system)\b[^.\n]{0,60}\b(instructions?|prompts?|rules?|context|directives?)\b/gi,
  },
  {
    rule: "role-reassignment",
    detail: "text that tries to reassign the assistant's role",
    re: /\byou (are now|must now|will now|should now)\b|\b(act|pose|masquerade) as (an? |the )?(ai|assistant|model|chatbot|llm|system)\b/gi,
  },
  {
    rule: "prompt-probe",
    detail: "text that references the assistant's hidden prompt",
    re: /\b(system prompt|developer message|hidden instructions?)\b/gi,
  },
  {
    rule: "ai-directive",
    detail: "instructions addressed to an AI assistant",
    re: /\b(ai (assistant|model|agent|system|reviewer)|language model|llm|chatbot|claude|gpt|gemini|copilot)\b[^.\n]{0,60}\b(must|should|shall|will|do not|don't|never|always|please)\b/gi,
  },
  {
    rule: "chat-markup",
    detail: "chat or prompt markup that has no place in a legal document",
    re: /<\|im_(start|end)\|>|\[\/?(INST|SYS)\]|<\/?(system|assistant|user|instructions?|untrusted-document)>|```(system|assistant)/gi,
  },
  {
    rule: "tool-coercion",
    detail: "references to the assistant's internal tool names",
    re: /\b(draft-document|tracked-changes|search-document|read-document|case-law)\b/gi,
  },
  {
    rule: "exfiltration",
    detail: "text that asks for conversation or credential exfiltration",
    re: /\b(send|forward|email|post|transmit|upload)\b[^.\n]{0,60}\b(system prompt|conversation|chat history|api key|credentials?)\b/gi,
  },
  {
    rule: "concealment",
    detail: "text that asks the assistant to hide something from the user",
    re: /\b(do not|don't|never) (mention|reveal|tell|disclose|inform|alert|warn)\b[^.\n]{0,60}\b(user|lawyer|attorney|counsel|reviewer|reader|human)\b/gi,
  },
]

export function detectInjection(text: string): InjectionFinding[] {
  return PATTERN_RULES.flatMap((pattern) =>
    [...text.matchAll(pattern.re)].map((m) => ({
      rule: pattern.rule,
      detail: pattern.detail,
      snippet: m[0].length > 120 ? m[0].slice(0, 120) + "..." : m[0],
      charStart: m.index,
      charEnd: m.index + m[0].length,
    })),
  )
}

// Formatting tricks that hide text from the rendered page while leaving it in the
// extracted (and therefore indexed) text: vanish ("hidden") runs, white-on-white
// runs, and near-invisible font sizes (w:sz is half-points, so 4 = 2pt). Counts
// only — the hidden text itself is already in the normalized body, where the
// pattern rules above see it.
export function scanDocxHiddenContent(buffer: Buffer): InjectionFinding[] {
  const xml = readZipEntry(buffer, "word/document.xml")?.toString("utf8")
  if (!xml) return []
  const hidden = [...xml.matchAll(/<w:vanish\b(?![^>]*w:val="(?:false|0)")[^>]*\/?>/g)].length
  const white = [...xml.matchAll(/<w:color\b[^>]*w:val="FFFFFF"/gi)].length
  const tiny = [...xml.matchAll(/<w:sz\b[^>]*w:val="(\d+)"/g)].filter((m) => Number(m[1]) <= 4).length
  return [
    ...(hidden
      ? [
          {
            rule: "hidden-text",
            detail: `${hidden} run(s) of hidden ("vanish") text — invisible in Word but present in the indexed text`,
          },
        ]
      : []),
    ...(white ? [{ rule: "white-text", detail: `${white} run(s) of white-on-white text` }] : []),
    ...(tiny ? [{ rule: "tiny-text", detail: `${tiny} run(s) of near-invisible text (2pt or smaller)` }] : []),
  ]
}

// Minimal ZIP reader for one named entry: walk the central directory (whose sizes
// are reliable even when a local header deferred them to a data descriptor) to the
// entry's local header, then inflate. Enough for word/document.xml in any real
// DOCX; avoids pulling in a zip dependency for a single read.
function readZipEntry(buffer: Buffer, name: string) {
  const eocd = buffer.lastIndexOf(Buffer.from("PK\x05\x06"))
  if (eocd < 0) return undefined
  const count = buffer.readUInt16LE(eocd + 10)
  let offset = buffer.readUInt32LE(eocd + 16)
  for (let i = 0; i < count; i++) {
    if (buffer.readUInt32LE(offset) !== 0x02014b50) return undefined
    const method = buffer.readUInt16LE(offset + 10)
    const compressedSize = buffer.readUInt32LE(offset + 20)
    const nameLength = buffer.readUInt16LE(offset + 28)
    const extraLength = buffer.readUInt16LE(offset + 30)
    const commentLength = buffer.readUInt16LE(offset + 32)
    const localOffset = buffer.readUInt32LE(offset + 42)
    if (buffer.toString("utf8", offset + 46, offset + 46 + nameLength) === name) {
      const dataStart =
        localOffset + 30 + buffer.readUInt16LE(localOffset + 26) + buffer.readUInt16LE(localOffset + 28)
      const data = buffer.subarray(dataStart, dataStart + compressedSize)
      return method === 0 ? data : inflateRawSync(data)
    }
    offset += 46 + nameLength + extraLength + commentLength
  }
  return undefined
}
