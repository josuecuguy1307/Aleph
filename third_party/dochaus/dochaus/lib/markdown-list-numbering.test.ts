import { expect, test } from "bun:test"
import { strFromU8, strToU8, unzipSync, zipSync } from "fflate"
import { restoreMarkdownListNumbering } from "./markdown-list-numbering"

const fixture = (body: string) => zipSync({
  "word/document.xml": strToU8(`<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${body}</w:body></w:document>`),
  "[Content_Types].xml": strToU8('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>'),
  "word/_rels/document.xml.rels": strToU8('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="styles.xml"/></Relationships>'),
})
const p = (text: string, props = "") => `<w:p>${props}<w:r><w:t>${text}</w:t></w:r></w:p>`

test("preserves six native numbered items, bullets, Unicode and paragraph styles", () => {
  const texts = ["Apertura á", "Muestra ñ", "Preparación", "Revisión", "Consolidación", "Cierre →"]
  const original = fixture(p("Título", '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>') + texts.map((text, i) => p(text, i === 0 ? '<w:pPr/>' : "")).join("") + p("Límite ficticio") + p("Texto final completo"))
  const markdown = `# Título\n\n${texts.map((text, i) => `${i + 1}. ${text}`).join("\n")}\n\nOtro bloque\n\n- Límite ficticio\n\nTexto final completo`
  const parts = unzipSync(restoreMarkdownListNumbering(original, markdown))
  const xml = strFromU8(parts["word/document.xml"])
  expect(xml.match(/<w:numPr>/g)?.length).toBe(7)
  expect(xml.match(/w:numId w:val="1"/g)?.length).toBe(6)
  expect(xml).toContain('<w:pStyle w:val="Heading1"/>')
  expect(xml.replace(/<w:pPr>[\s\S]*?<\/w:pPr>/g, "")).toBe(strFromU8(unzipSync(original)["word/document.xml"]).replace(/<w:pPr>[\s\S]*?<\/w:pPr>|<w:pPr\/>/g, ""))
  const numbering = strFromU8(parts["word/numbering.xml"])
  expect(numbering).toContain('w:numFmt w:val="decimal"')
  expect(numbering).toContain('w:numFmt w:val="bullet"')
  expect(numbering).toContain('w:lvlText w:val="•"')
  expect(strFromU8(parts["word/_rels/document.xml.rels"])).toContain('Target="styles.xml"')
  expect(strFromU8(parts["word/_rels/document.xml.rels"])).toContain('Target="numbering.xml"')
  expect(strFromU8(parts["[Content_Types].xml"])).toContain('PartName="/word/numbering.xml"')
  expect(restoreMarkdownListNumbering(zipSync(parts), markdown)).toEqual(zipSync(parts))
})

test("cannot silently certify list items that failed to map to saved paragraphs", () => {
  expect(() => restoreMarkdownListNumbering(fixture(p("Different content")), "1. Expected content")).toThrow("matched 0/1")
})
