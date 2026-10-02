import { describe, expect, test } from "bun:test"
import { sanitizeNotebookHtml } from "./notebook-cell"

describe("NotebookCell", () => {
  test("sanitizes text/html outputs before rendering", () => {
    const html = sanitizeNotebookHtml('<img src="x" onerror="alert(1)"><script>alert(2)</script><strong>ok</strong>')

    expect(html).toContain("<strong>ok</strong>")
    expect(html).not.toContain("onerror")
    expect(html).not.toContain("<script")
  })
})
