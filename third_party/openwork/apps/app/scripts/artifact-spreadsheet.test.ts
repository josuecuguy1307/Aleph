import { describe, expect, it } from "bun:test";
import JSZip from "jszip";
import { readFile } from "node:fs/promises";

import {
  parseSpreadsheet,
  serializeSpreadsheet,
} from "../src/react-app/domains/session/artifacts/artifact-spreadsheet-model";

describe("artifact spreadsheet model", () => {
  it("preserves every untouched XLSX part, formulas, two sheets and chart when editing a cell", async () => {
    const bytes = await readFile(new URL("./fixtures/bibliotecas.xlsx", import.meta.url));
    const content = { kind: "binary" as const, data: new Uint8Array(bytes).buffer };
    const before = await parseSpreadsheet({ name: "bibliotecas.xlsx", content });
    const rows = before.map((row) => [...row]);
    rows[1][1] = "Minibús acondicionado · revisión E2E";
    const output = await serializeSpreadsheet("bibliotecas.xlsx", rows, { content, before });
    if (output.kind !== "binary") throw new Error("Expected a workbook");
    const a = await JSZip.loadAsync(content.data);
    const b = await JSZip.loadAsync(output.data);
    expect(Object.keys(b.files).filter((p) => !b.files[p].dir).sort()).toEqual(Object.keys(a.files).filter((p) => !a.files[p].dir).sort());
    for (const path of Object.keys(a.files)) {
      if (a.files[path].dir || path === "xl/worksheets/sheet1.xml") continue;
      expect(await b.file(path)!.async("uint8array")).toEqual(await a.file(path)!.async("uint8array"));
    }
    const result = await parseSpreadsheet({ name: "bibliotecas.xlsx", content: output });
    expect(result[1][1]).toBe(rows[1][1]);
    const xml = await b.file("xl/worksheets/sheet1.xml")!.async("string");
    expect(xml.match(/<x:f>/g)?.length).toBe(25);
    const summary = await parseSpreadsheet({ name: "bibliotecas.xlsx", content: output, sheetName: "Resumen" });
    expect(summary.length).toBeGreaterThan(5);
  });
  it("round-trips CSV edits", async () => {
    const rows = await parseSpreadsheet({ name: "artifact-eval.csv", content: { kind: "text", data: "name,revenue\nAda,10\n" } });
    rows[1]![1] = "11";
    const output = await serializeSpreadsheet("artifact-eval.csv", rows);
    expect(output).toEqual({ kind: "text", data: "name,revenue\nAda,11\n" });
  });

  it("round-trips XLSX edits", async () => {
    const output = await serializeSpreadsheet("artifact-eval.xlsx", [["name", "revenue"], ["Ada", "10"]]);
    expect(output.kind).toBe("binary");
    if (output.kind !== "binary") throw new Error("expected binary");
    const parsed = await parseSpreadsheet({ name: "artifact-eval.xlsx", content: output });
    expect(parsed.slice(0, 2)).toEqual([["name", "revenue"], ["Ada", "10"]]);
  });
});
