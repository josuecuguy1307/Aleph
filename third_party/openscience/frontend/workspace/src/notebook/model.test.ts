import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import {
  clearOutputs,
  createCell,
  exportHtml,
  exportMarkdown,
  exportScript,
  insertCell,
  moveCell,
  parseNotebook,
  removeCell,
  serializeNotebook,
  sourceText,
  updateSource,
} from "./model"

const read = (path: string) => readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf8")

describe("notebook document model", () => {
  test("normalizes nbformat cells while preserving unknown fields", () => {
    const notebook = parseNotebook(
      JSON.stringify({
        cells: [
          {
            cell_type: "code",
            execution_count: null,
            metadata: { tags: ["analysis"] },
            outputs: [],
            source: "value = 41\nvalue + 1",
            vendor: { retained: true },
          },
        ],
        metadata: {
          kernelspec: { display_name: "Python 3", language: "python", name: "python3" },
          custom: { retained: true },
        },
        nbformat: 4,
        nbformat_minor: 5,
        vendor_root: "retained",
      }),
    )

    expect(notebook.cells).toHaveLength(1)
    expect(notebook.cells[0]?.cell_type).toBe("code")
    expect(notebook.cells[0]?.id).toMatch(/^cell-[a-z0-9]+$/)
    expect(notebook.cells[0]?.source).toEqual(["value = 41\n", "value + 1"])
    expect(notebook.cells[0]?.metadata).toEqual({ tags: ["analysis"] })
    expect(notebook.cells[0]?.vendor).toEqual({ retained: true })
    expect(notebook.metadata.custom).toEqual({ retained: true })
    expect(notebook.vendor_root).toBe("retained")
  })

  test("serializes normalized notebooks as valid nbformat JSON", () => {
    const notebook = parseNotebook(
      JSON.stringify({
        cells: [{ cell_type: "markdown", metadata: {}, source: ["# Result\n", "Useful text"] }],
        metadata: {},
        nbformat: 4,
        nbformat_minor: 5,
      }),
    )

    const serialized = serializeNotebook(notebook)
    const saved = JSON.parse(serialized) as Record<string, unknown>

    expect(serialized.endsWith("\n")).toBe(true)
    expect(saved.nbformat).toBe(4)
    expect(saved.nbformat_minor).toBe(5)
    expect(saved.cells).toEqual(notebook.cells)
  })

  test("rejects malformed notebook JSON without discarding the source", () => {
    expect(() => parseNotebook('{"cells": [}')).toThrow("Invalid notebook JSON")
  })

  test("creates editable code and markdown cells with stable ids", () => {
    const code = createCell("code", "answer = 42")
    const markdown = createCell("markdown", "## Notes")

    expect(code).toMatchObject({
      cell_type: "code",
      execution_count: null,
      metadata: {},
      outputs: [],
      source: ["answer = 42"],
    })
    expect(markdown).toMatchObject({
      cell_type: "markdown",
      metadata: {},
      source: ["## Notes"],
    })
    expect(code.id).toMatch(/^cell-[a-z0-9]+$/)
    expect(markdown.id).toMatch(/^cell-[a-z0-9]+$/)
    expect(code.id).not.toBe(markdown.id)
  })

  test("round-trips source text without losing line breaks", () => {
    const cell = createCell("code", "first()\nsecond()\n")
    const updated = updateSource(cell, "alpha\n\nomega")

    expect(sourceText(cell)).toBe("first()\nsecond()\n")
    expect(updated.source).toEqual(["alpha\n", "\n", "omega"])
    expect(sourceText(updated)).toBe("alpha\n\nomega")
  })

  test("inserts, moves, and removes cells without mutating the notebook", () => {
    const notebook = parseNotebook(
      JSON.stringify({
        cells: [
          { cell_type: "markdown", id: "intro", metadata: {}, source: ["Intro"] },
          { cell_type: "code", id: "analysis", metadata: {}, source: ["run()"], outputs: [], execution_count: null },
        ],
        metadata: {},
        nbformat: 4,
        nbformat_minor: 5,
      }),
    )
    const inserted = insertCell(notebook, 1, createCell("code", "setup()"))
    const moved = moveCell(inserted, 2, 0)
    const removed = removeCell(moved, 1)

    expect(notebook.cells.map((value) => value.id)).toEqual(["intro", "analysis"])
    expect(inserted.cells.map((value) => value.id)).toEqual(["intro", inserted.cells[1]?.id, "analysis"])
    expect(moved.cells.map((value) => value.id)).toEqual(["analysis", "intro", inserted.cells[1]?.id])
    expect(removed.cells.map((value) => value.id)).toEqual(["analysis", inserted.cells[1]?.id])
  })

  test("clears code outputs and execution counts while retaining other cells", () => {
    const notebook = parseNotebook(
      JSON.stringify({
        cells: [
          {
            cell_type: "code",
            id: "executed",
            metadata: {},
            source: ["1 + 1"],
            execution_count: 7,
            outputs: [{ output_type: "execute_result", data: { "text/plain": ["2"] }, execution_count: 7 }],
          },
          { cell_type: "markdown", id: "notes", metadata: {}, source: ["Result"] },
        ],
        metadata: {},
        nbformat: 4,
        nbformat_minor: 5,
      }),
    )

    const cleared = clearOutputs(notebook)

    expect(cleared.cells[0]?.outputs).toEqual([])
    expect(cleared.cells[0]?.execution_count).toBeNull()
    expect(cleared.cells[1]).toEqual(notebook.cells[1])
    expect(notebook.cells[0]?.outputs).toHaveLength(1)
  })

  test("exports a notebook as an executable percent-format script", () => {
    const notebook = parseNotebook(
      JSON.stringify({
        cells: [
          { cell_type: "markdown", id: "intro", metadata: {}, source: ["# Analysis\n", "Important context"] },
          {
            cell_type: "code",
            id: "code",
            metadata: {},
            source: ["answer = 42\n", "answer"],
            execution_count: 1,
            outputs: [],
          },
        ],
        metadata: {},
        nbformat: 4,
        nbformat_minor: 5,
      }),
    )

    expect(exportScript(notebook, "python")).toBe(
      "# %% [markdown]\n# # Analysis\n# Important context\n\n# %%\nanswer = 42\nanswer\n",
    )
    expect(exportScript(notebook, "r")).toContain("# %%\nanswer = 42")
  })

  test("exports Markdown with code fences and readable outputs", () => {
    const notebook = parseNotebook(
      JSON.stringify({
        cells: [
          { cell_type: "markdown", id: "intro", metadata: {}, source: ["# Analysis"] },
          {
            cell_type: "code",
            id: "code",
            metadata: {},
            source: ["print(42)"],
            execution_count: 1,
            outputs: [{ output_type: "stream", name: "stdout", text: ["42\n"] }],
          },
        ],
        metadata: {},
        nbformat: 4,
        nbformat_minor: 5,
      }),
    )

    expect(exportMarkdown(notebook, "python")).toBe("# Analysis\n\n```python\nprint(42)\n```\n\n```text\n42\n\n```\n")
  })

  test("exports a standalone escaped HTML report", () => {
    const notebook = parseNotebook(
      JSON.stringify({
        cells: [{ cell_type: "code", id: "code", metadata: {}, source: ["value < 4"], outputs: [] }],
        metadata: {},
        nbformat: 4,
        nbformat_minor: 5,
      }),
    )

    const html = exportHtml(notebook, "Analysis")

    expect(html).toContain("<!doctype html>")
    expect(html).toContain("<title>Analysis</title>")
    expect(html).toContain("value &lt; 4")
    expect(html).not.toContain("value < 4")
  })
})

describe("notebook file integration", () => {
  test("routes ipynb files through the native notebook editor", () => {
    const preview = read("../atlas/FilePreview.tsx")

    expect(preview).toContain('import { NotebookView } from "@/notebook/NotebookView"')
    expect(preview).toContain('"notebook"')
    expect(preview).toContain("<NotebookView")
  })

  test("notebook editor exposes cell and kernel controls", () => {
    const view = read("./NotebookView.tsx")

    expect(view).toContain('data-component="notebook"')
    expect(view).toContain('data-action="run-cell"')
    expect(view).toContain('data-action="run-all"')
    expect(view).toContain('data-action="restart-kernel"')
    expect(view).toContain('data-action="interrupt-kernel"')
    expect(view).toContain("All in-memory variables and queued cells will be lost.")
    expect(view).toContain('data-action="notebook-diff"')
    expect(view).toContain('data-action="notebook-export"')
    expect(view).toContain('data-slot="notebook-output"')
    expect(view).toContain('event.key.toLowerCase() === "s"')
  })
})
