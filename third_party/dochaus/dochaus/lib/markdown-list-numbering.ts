import { strFromU8, strToU8, unzipSync, zipSync } from "fflate"

const decode = (text: string) => text
  .replace(/&#x([\da-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
  .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
  .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
  .replace(/&apos;/g, "'").replace(/&amp;/g, "&")
const normalize = (text: string) => text.replace(/\s+/g, " ").trim()

// Docxodus v1 inserts list item text but saves neither numPr nor numbering.xml.
// Recover native Word numbering from the authored Markdown before the sole
// ingest writer receives the document. Do not change paragraph text or styles.
export function restoreMarkdownListNumbering(bytes: Uint8Array, markdown: string) {
  const entries: { text: string; ordered: boolean; start: number; group: number }[] = []
  let group = 0
  let prior: boolean | undefined
  for (const line of markdown.split("\n")) {
    const match = line.match(/^ {0,3}(?:(\d+)[.)]|([-+*]))\s+(.+)$/)
    if (!match) { if (line.trim()) prior = undefined; continue }
    const ordered = Boolean(match[1])
    if (prior !== ordered) group++
    prior = ordered
    entries.push({
      text: normalize(match[3].replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/[*_`]/g, "")),
      ordered, start: Number(match[1] ?? 1), group,
    })
  }
  if (!entries.length) return bytes
  const parts = unzipSync(bytes)
  let xml = strFromU8(parts["word/document.xml"])
  if (/<w:numPr\b/.test(xml)) return bytes
  let index = 0
  xml = xml.replace(/<w:p\b[^>]*>[\s\S]*?<\/w:p>/g, (paragraph) => {
    const text = normalize([...paragraph.matchAll(/<w:t\b[^>]*>([\s\S]*?)<\/w:t>/g)].map((m) => decode(m[1])).join(""))
    const entry = entries[index]
    if (!entry || text !== entry.text) return paragraph
    index++
    const numbering = `<w:numPr><w:ilvl w:val="0"/><w:numId w:val="${entry.group}"/></w:numPr>`
    if (/<w:pPr\b[^>]*\/>/.test(paragraph))
      return paragraph.replace(/<w:pPr\b([^>]*)\/>/, `<w:pPr$1>${numbering}</w:pPr>`)
    return /<w:pPr\b/.test(paragraph)
      ? paragraph.replace(/<\/w:pPr>/, `${numbering}</w:pPr>`)
      : paragraph.replace(/(<w:p\b[^>]*>)/, `$1<w:pPr>${numbering}</w:pPr>`)
  })
  if (index !== entries.length) throw new Error(`Could not preserve Markdown list numbering: matched ${index}/${entries.length} items`)
  const groups = entries.filter((entry, i) => i === 0 || entries[i - 1].group !== entry.group)
  parts["word/document.xml"] = strToU8(xml)
  parts["word/numbering.xml"] = strToU8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">${groups.map((entry) => `<w:abstractNum w:abstractNumId="${entry.group}"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="${entry.start}"/><w:numFmt w:val="${entry.ordered ? "decimal" : "bullet"}"/><w:lvlText w:val="${entry.ordered ? "%1." : "•"}"/><w:lvlJc w:val="left"/><w:pPr><w:tabs><w:tab w:val="num" w:pos="720"/></w:tabs><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum><w:num w:numId="${entry.group}"><w:abstractNumId w:val="${entry.group}"/></w:num>`).join("")}</w:numbering>`)
  const relPath = "word/_rels/document.xml.rels"
  const rels = parts[relPath] ? strFromU8(parts[relPath]) : '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
  const id = `rIdAlephNumbering${groups.length}`
  parts[relPath] = strToU8(rels.replace(/<\/Relationships>/, `<Relationship Id="${id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/></Relationships>`))
  const types = strFromU8(parts["[Content_Types].xml"])
  parts["[Content_Types].xml"] = strToU8(types.includes('PartName="/word/numbering.xml"') ? types : types.replace(/<\/Types>/, '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>'))
  return zipSync(parts)
}
