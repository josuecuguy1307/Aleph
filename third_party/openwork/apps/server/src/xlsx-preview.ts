import JSZip from "jszip";
import { DOMParser } from "@xmldom/xmldom";
import { posix } from "node:path";

const escapeHtml = (value: string) => value.replace(/[&<>"']/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]!));

/** OfficeCLI renders the original workbook but omits native Excel notes.
 * Restore them alongside their sheet, without replacing cells or charts. */
export async function restoreXlsxNotes(html: string, data: Uint8Array): Promise<string> {
  const zip = await JSZip.loadAsync(data);
  async function xml(name: string) {
    const part = zip.file(name);
    if (!part) return null;
    const text = await part.async("string");
    if (text.length > 2 * 1024 * 1024) throw new Error("Workbook notes part is too large");
    return new DOMParser().parseFromString(text, "application/xml");
  }
  const book = await xml("xl/workbook.xml");
  const rels = await xml("xl/_rels/workbook.xml.rels");
  if (!book || !rels) return html;
  let result = html;
  for (const sheet of Array.from(book.getElementsByTagName("sheet"))) {
    const relation = Array.from(rels.getElementsByTagName("Relationship")).find((r) => r.getAttribute("Id") === sheet.getAttribute("r:id"));
    if (!relation || relation.getAttribute("TargetMode") === "External") continue;
    const target = relation.getAttribute("Target") || "";
    const sheetPath = target.startsWith("/") ? target.slice(1) : posix.normalize(posix.join("xl", target));
    if (!sheetPath.startsWith("xl/worksheets/")) continue;
    const sheetRels = await xml(posix.join(posix.dirname(sheetPath), "_rels", posix.basename(sheetPath) + ".rels"));
    if (!sheetRels) continue;
    const commentRel = Array.from(sheetRels.getElementsByTagName("Relationship")).find((r) => r.getAttribute("Type")?.endsWith("/comments") && r.getAttribute("TargetMode") !== "External");
    if (!commentRel) continue;
    const commentTarget = commentRel.getAttribute("Target") || "";
    const commentPath = commentTarget.startsWith("/") ? commentTarget.slice(1) : posix.normalize(posix.join(posix.dirname(sheetPath), commentTarget));
    if (!commentPath.startsWith("xl/")) continue;
    const comments = await xml(commentPath);
    if (!comments) continue;
    const authors = Array.from(comments.getElementsByTagName("author")).map((a) => a.textContent || "");
    const notes = Array.from(comments.getElementsByTagName("comment")).map((comment) => {
      const ref = comment.getAttribute("ref") || "";
      if (!/^[A-Z]+[1-9]\d*$/.test(ref)) return "";
      const text = Array.from(comment.getElementsByTagName("t")).map((t) => t.textContent || "").join("");
      const author = authors[Number(comment.getAttribute("authorId"))] || "";
      return `<details class="aleph-cell-note"><summary>Nota de ${escapeHtml(ref)} · ${escapeHtml(author)}</summary><div>${escapeHtml(text)}</div></details>`;
    }).join("");
    if (!notes) continue;
    const name = escapeHtml(sheet.getAttribute("name") || "");
    result = result.replace(/<table\b[\s\S]*?<\/table>/g, (table) => table.includes(`>${name}</caption>`) ? table + `<section class="aleph-sheet-notes" aria-label="Notas de celdas"><h2>Notas de celdas</h2>${notes}</section>` : table);
  }
  if (result === html) return html;
  return result.replace("</head>", `<style>.aleph-sheet-notes{max-width:900px;margin:20px 12px;font:14px/1.5 system-ui;color:#222}.aleph-sheet-notes h2{font-size:18px}.aleph-cell-note{border:1px solid #ddd;padding:10px;margin:8px 0}.aleph-cell-note summary{cursor:pointer;font-weight:600}.aleph-cell-note div{white-space:pre-wrap;overflow-wrap:anywhere;margin-top:10px}</style></head>`);
}
