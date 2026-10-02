import { expect, test } from "bun:test";
import JSZip from "jszip";
import { restoreXlsxNotes } from "./xlsx-preview.js";

test("native long note remains complete, escaped, and attached to its sheet", async () => {
  const zip = new JSZip();
  zip.file("xl/workbook.xml", '<workbook><sheets><sheet name="Revisión" r:id="rId1" xmlns:r="urn:rel"/></sheets></workbook>');
  zip.file("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>');
  zip.file("xl/worksheets/_rels/sheet1.xml.rels", '<Relationships><Relationship Type="urn:rel/comments" Target="../comments1.xml"/></Relationships>');
  const text = "estación, Ñ y ü. ".repeat(100) + "&lt;script&gt; CIERRE";
  zip.file("xl/comments1.xml", `<comments><authors><author>Mesa ficticia</author></authors><commentList><comment ref="B2" authorId="0"><text><r><t>${text}</t></r></text></comment></commentList></comments>`);
  const original = '<html><head></head><body><table><caption class="sr-only">Revisión</caption><tr><td>siete días</td></tr></table><svg>gráfico original</svg></body></html>';
  const result = await restoreXlsxNotes(original, await zip.generateAsync({type: "uint8array"}));
  expect(result).toContain("Nota de B2 · Mesa ficticia");
  expect(result).toContain("&lt;script&gt; CIERRE");
  expect(result).not.toContain("<script>");
  expect(result).toContain("<svg>gráfico original</svg>");
  expect(result).toContain("<td>siete días</td>");
  expect(result).toContain("estación, Ñ y ü. ".repeat(100));
});
