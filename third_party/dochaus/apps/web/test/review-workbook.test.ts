import { expect, test } from "bun:test"
import { utils, write, read } from "xlsx"
import { strFromU8, unzipSync } from "fflate"
import { wrapReviewWorkbook } from "../src/api/review-workbook"

test("native wrapping preserves complete answers and Unicode Excel notes", () => {
  const sheet = utils.aoa_to_sheet([["Documento", "Pregunta larga".repeat(20)], ["Convenio ficticio.docx", "siete días"]])
  sheet.B2.c = [{ a: "Aleph Legal", t: "Revisión: estación, Ñ y ü. ".repeat(50) + "CIERRE" }]
  sheet["!cols"] = [{ wch: 48 }, { wch: 80 }]
  sheet["!rows"] = [{ hpt: 98 }, { hpt: 26 }]
  const book = utils.book_new()
  utils.book_append_sheet(book, sheet, "Tabular review")
  const output = wrapReviewWorkbook(new Uint8Array(write(book, {type: "array", bookType: "xlsx"})))
  const parts = unzipSync(output)
  expect(strFromU8(parts["xl/styles.xml"])).toContain('wrapText="1"')
  expect(strFromU8(parts["xl/worksheets/sheet1.xml"])).toContain('s="1"')
  const reopened = read(output, {type: "array"}).Sheets["Tabular review"]
  expect(reopened.B2.v).toBe("siete días")
  expect(reopened.B2.c?.[0].t).toEndWith("CIERRE")
})
