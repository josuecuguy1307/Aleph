import { expect, test } from "bun:test";
import JSZip from "jszip";
import { restoreDocxKeepNext } from "./docx-preview.js";

async function documentXml(xml: string) {
  const zip = new JSZip();
  zip.file("word/document.xml", xml);
  return zip.generateAsync({ type: "uint8array" });
}

test("Word keepNext reaches the paginator without changing content or original", async () => {
  const data = await documentXml(`<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
    <w:p><w:pPr><w:keepNext/></w:pPr><w:r><w:t>Conclusion</w:t></w:r></w:p>
    <w:p><w:r><w:t>Final</w:t></w:r></w:p>
  </w:body></w:document>`);
  const original = Uint8Array.from(data);
  const html = '<p data-path="/body/p[1]">Conclusion</p><p data-path="/body/p[2]">Final</p><script>if(splitIdx<0)continue;</script>';
  const result = await restoreDocxKeepNext(html, data);
  expect(result).toContain('data-path="/body/p[1]" data-word-keep-next="1"');
  expect(result).toContain('data-path="/body/p[2]">Final</p>');
  expect(result).toContain("splitIdx=previousVisible");
  expect(data).toEqual(original);
});

test("Explicit false keepNext and unsupported paginator are left unchanged", async () => {
  const data = await documentXml(`<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:keepNext w:val="false"/></w:pPr></w:p></w:body></w:document>`);
  const html = '<p data-path="/body/p[1]">Complete</p><script>if(splitIdx<0)continue;</script>';
  expect(await restoreDocxKeepNext(html, data)).toBe(html);
  const trueData = await documentXml(`<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:keepNext/></w:pPr></w:p></w:body></w:document>`);
  expect(await restoreDocxKeepNext("<p>Complete</p>", trueData)).toBe("<p>Complete</p>");
});
