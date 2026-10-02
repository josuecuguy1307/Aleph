import JSZip from "jszip";
import { DOMParser, XMLSerializer } from "@xmldom/xmldom";

const NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

/** Patch only edited cells in the original package. SheetJS's workbook writer
 * cannot preserve drawings/charts, so it must not round-trip an existing XLSX. */
export async function preserveXlsx(original: ArrayBuffer, before: string[][], after: string[][], sheetName?: string): Promise<ArrayBuffer> {
  const zip = await JSZip.loadAsync(original);
  const parser = new DOMParser();
  const xml = async (path: string) => {
    const entry = zip.file(path);
    if (!entry) throw new Error(`Falta una parte del libro: ${path}`);
    return parser.parseFromString(await entry.async("string"), "application/xml");
  };
  const workbook = await xml("xl/workbook.xml");
  const sheets = Array.from(workbook.getElementsByTagNameNS(NS, "sheet"));
  const sheet = sheetName ? sheets.find((s) => s.getAttribute("name") === sheetName) : sheets[0];
  if (!sheet) throw new Error("No se encontró la hoja solicitada");
  const rels = await xml("xl/_rels/workbook.xml.rels");
  const relation = Array.from(rels.getElementsByTagName("Relationship")).find((r) => r.getAttribute("Id") === sheet.getAttributeNS(REL, "id"));
  const target = relation?.getAttribute("Target");
  if (!target) throw new Error("La hoja no tiene una relación válida");
  const path = target.startsWith("/") ? target.slice(1) : `xl/${target.replace(/^\.\//, "")}`;
  const doc = await xml(path);
  const sheetData = doc.getElementsByTagNameNS(NS, "sheetData")[0];
  if (!sheetData) throw new Error("La hoja no contiene celdas editables");
  const prefix = sheetData.prefix ? `${sheetData.prefix}:` : "";
  const element = (tag: string) => doc.createElementNS(NS, `${prefix}${tag}`);
  const columnName = (index: number) => {
    let result = "";
    for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) result = String.fromCharCode(65 + (n - 1) % 26) + result;
    return result;
  };
  for (let r = 0; r < after.length; r++) {
    for (let c = 0; c < after[r].length; c++) {
      const value = after[r][c] ?? "";
      if (value === (before[r]?.[c] ?? "")) continue;
      let row = Array.from(sheetData.getElementsByTagNameNS(NS, "row")).find((e) => e.getAttribute("r") === String(r + 1));
      if (!row) {
        row = element("row"); row.setAttribute("r", String(r + 1));
        const next = Array.from(sheetData.childNodes).find((e) => e.nodeType === 1 && Number((e as Element).getAttribute("r")) > r + 1);
        sheetData.insertBefore(row, next ?? null);
      }
      const address = `${columnName(c)}${r + 1}`;
      let cell = Array.from(row.getElementsByTagNameNS(NS, "c")).find((e) => e.getAttribute("r") === address);
      if (!cell) {
        cell = element("c"); cell.setAttribute("r", address);
        const indexOf = (ref: string) => [...ref.replace(/\d/g, "")].reduce((n, char) => n * 26 + char.charCodeAt(0) - 64, 0) - 1;
        const next = Array.from(row.getElementsByTagNameNS(NS, "c")).find((e) => indexOf(e.getAttribute("r") ?? "") > c);
        row.insertBefore(cell, next ?? null);
      }
      while (cell.firstChild) cell.removeChild(cell.firstChild);
      cell.removeAttribute("t");
      const numeric = value.trim() !== "" && /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[Ee][-+]?\d+)?$/.test(value.trim());
      if (value.startsWith("=")) {
        const f = element("f"); f.appendChild(doc.createTextNode(value.slice(1))); cell.appendChild(f);
      } else if (numeric) {
        const v = element("v"); v.appendChild(doc.createTextNode(value.trim())); cell.appendChild(v);
      } else {
        cell.setAttribute("t", "inlineStr");
        const inline = element("is"); const t = element("t");
        t.setAttribute("xml:space", "preserve"); t.appendChild(doc.createTextNode(value)); inline.appendChild(t); cell.appendChild(inline);
      }
    }
  }
  const dimension = doc.getElementsByTagNameNS(NS, "dimension")[0];
  if (dimension && (after.length > before.length || Math.max(0, ...after.map((r) => r.length)) > Math.max(0, ...before.map((r) => r.length)))) {
    const width = Math.max(1, ...after.map((r) => r.length));
    dimension.setAttribute("ref", `A1:${columnName(width - 1)}${Math.max(1, after.length)}`);
  }
  const serializer = new XMLSerializer();
  zip.file(path, serializer.serializeToString(doc));
  return zip.generateAsync({ type: "arraybuffer", compression: "DEFLATE" });
}
