import JSZip from "jszip";
import { DOMParser } from "@xmldom/xmldom";

const W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

/** OfficeCLI's HTML paginator omits Word's keepNext flag. Restore that flag
 * without changing the original package or the rendered paragraph contents. */
export async function restoreDocxKeepNext(html: string, data: Uint8Array): Promise<string> {
  const zip = await JSZip.loadAsync(data);
  const part = zip.file("word/document.xml");
  if (!part) return html;
  const xml = new DOMParser().parseFromString(await part.async("string"), "application/xml");
  const body = xml.getElementsByTagNameNS(W, "body").item(0);
  if (!body) return html;
  const paragraphs = Array.from(body.childNodes).filter(
    (node): node is Element => node.nodeType === 1 && (node as Element).localName === "p",
  );
  let result = html;
  paragraphs.forEach((paragraph, index) => {
    const flag = paragraph.getElementsByTagNameNS(W, "keepNext").item(0);
    if (!flag || /^(0|false|off)$/i.test(flag.getAttributeNS(W, "val") || "")) return;
    const path = `data-path="/body/p[${index + 1}]"`;
    result = result.replace(path, `${path} data-word-keep-next="1"`);
  });
  if (!result.includes('data-word-keep-next="1"')) return html;
  // This runs in the existing sandboxed preview only. On each split, walk back
  // over hidden anchors/markers and any paragraph explicitly linked to its next.
  const marker = "if(splitIdx<0)continue;";
  if (!result.includes(marker)) return html;
  return result.replace(marker, marker + `
      var previousVisible=splitIdx-1;
      while(previousVisible>=0){
        var previous=children[previousVisible];
        if(!previous.offsetHeight||isOutOfFlow(previous)){previousVisible--;continue;}
        if(previous.getAttribute('data-word-keep-next')!=='1')break;
        if(previousVisible===0)break;
        var groupBottom=children[splitIdx].offsetTop+children[splitIdx].offsetHeight;
        if(groupBottom-previous.offsetTop>availH+2)break;
        splitIdx=previousVisible;
        previousVisible--;
      }
  `);
}
