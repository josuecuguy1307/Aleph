import { strFromU8, strToU8, unzipSync, zipSync } from "fflate"

// SheetJS Community writes widths/heights, but does not write cell alignment.
// This exporter creates text-only cells with the default style. Give those
// cells native wrapping, so the original XLSX is readable in other viewers too.
export function wrapReviewWorkbook(data: Uint8Array): Uint8Array {
  const parts = unzipSync(data)
  const styles = strFromU8(parts["xl/styles.xml"])
  const match = styles.match(/<cellXfs count="(\d+)">([\s\S]*?)<\/cellXfs>/)
  if (!match) throw new Error("No se pudo preparar el formato del Excel")
  const index = Number(match[1])
  const wrap = '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
  parts["xl/styles.xml"] = strToU8(styles.replace(match[0], `<cellXfs count="${index + 1}">${match[2]}${wrap}</cellXfs>`))
  const sheet = strFromU8(parts["xl/worksheets/sheet1.xml"])
  parts["xl/worksheets/sheet1.xml"] = strToU8(sheet.replace(/<c\b([^>]*)>/g, (_, attrs: string) => `<c${attrs.replace(/\s+s="\d+"/g, "")} s="${index}">`))
  return zipSync(parts)
}
