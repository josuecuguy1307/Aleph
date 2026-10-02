import { test, expect } from "bun:test"
import { readFileSync } from "node:fs"
import path from "node:path"
import { pdfToText, looksScanned, ocrPdfText } from "./pdf"
import { sectionize } from "./ingest"

// text-layer.pdf is a born-digital agreement; scanned.pdf is the same document
// rasterized to an image-only PDF (no text layer), i.e. a flat scan.
const textPdf = readFileSync(path.join(import.meta.dir, "fixtures", "text-layer.pdf"))
const scannedPdf = readFileSync(path.join(import.meta.dir, "fixtures", "scanned.pdf"))

test("pdfToText extracts text-layer PDFs", async () => {
  const text = await pdfToText(textPdf)
  expect(text).toContain("MASTER SERVICES AGREEMENT")
  expect(text).toContain("7.2 Termination")
  expect(text).toContain("State of Delaware")
}, 120_000)

test("pdfToText recovers flat scans through OCR", async () => {
  const text = await pdfToText(scannedPdf)
  expect(text).toContain("MASTER SERVICES AGREEMENT")
  expect(text).toContain("thirty (30) days written notice")
}, 120_000)

test("ocrPdfText reads image-only pages", async () => {
  const text = await ocrPdfText(scannedPdf)
  expect(text).toContain("GOVERNING LAW")
}, 120_000)

test("looksScanned flags empty text layers only", () => {
  expect(looksScanned("", 1)).toBe(true)
  expect(looksScanned("Bates No. 000123", 3)).toBe(true)
  expect(looksScanned("x".repeat(5000), 3)).toBe(false)
})

test("sectionize splits on markdown headings from markitdown", () => {
  const sections = sectionize(
    [
      "# MASTER SERVICES AGREEMENT",
      "This Agreement is made between the parties.",
      "## 7.2 Termination",
      "Either party may terminate upon notice.",
    ].join("\n"),
  )
  expect(sections.map((s) => s.label)).toEqual(["MASTER SERVICES AGREEMENT", "7.2"])
  expect(sections[1]!.text).toContain("terminate upon notice")
})
