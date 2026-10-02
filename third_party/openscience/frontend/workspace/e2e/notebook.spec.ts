import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { test, expect } from "./fixtures"
import { openConnectedFile } from "./utils"

test("opens, executes, edits, and saves a native Jupyter notebook", async ({ page, sdk, openSession }) => {
  const directory = realpathSync(mkdtempSync(path.join(tmpdir(), "openscience-notebook-e2e-")))
  const filename = "analysis.ipynb"
  const filepath = path.join(directory, filename)
  writeFileSync(
    filepath,
    JSON.stringify(
      {
        cells: [
          { cell_type: "markdown", id: "intro", metadata: {}, source: ["# Experiment\n", "Persistent kernel"] },
          {
            cell_type: "code",
            id: "setup",
            metadata: {},
            source: ["value = 41"],
            execution_count: null,
            outputs: [],
          },
          {
            cell_type: "code",
            id: "result",
            metadata: {},
            source: ["value + 1"],
            execution_count: null,
            outputs: [],
          },
        ],
        metadata: { kernelspec: { display_name: "Python 3", language: "python", name: "python3" } },
        nbformat: 4,
        nbformat_minor: 5,
      },
      null,
      2,
    ),
  )

  try {
    const sessionID = await openSession()
    await sdk.session.filesystem.grant({ sessionID, path: directory, access: "write", scope: "session" })
    await openConnectedFile(page, directory, filename)

    const notebook = page.locator('[data-component="notebook"]')
    await expect(notebook).toBeVisible()
    await expect(notebook.getByText("Experiment", { exact: true })).toBeVisible()
    await expect(notebook.locator('[data-cell-type="code"]')).toHaveCount(2)

    await notebook.locator('[data-action="run-all"]').click()
    await expect(notebook.getByText("42", { exact: true })).toBeVisible({ timeout: 20_000 })
    // The kernel-ready state is a 6px status dot; assert it exists rather than
    // its pixel visibility, since the "42" output already proves execution.
    await expect(notebook.getByLabel("Kernel ready")).toBeAttached()

    const result = notebook.getByLabel("code cell 3")
    await result.fill("value + 2")
    await notebook.locator('[data-action="notebook-diff"]').click()
    await expect(page.getByRole("dialog", { name: "Notebook changes" })).toBeVisible()
    await page.getByRole("dialog", { name: "Notebook changes" }).getByRole("button", { name: "close" }).click()

    await notebook.locator('[data-action="notebook-export"]').click()
    const download = page.waitForEvent("download")
    await page.getByRole("menuitem", { name: "Python script (.py)" }).click()
    expect((await download).suggestedFilename()).toBe("analysis.py")

    await notebook.locator('[data-cell-id="result"] [data-action="run-cell"]').click()
    await expect(notebook.getByText("43", { exact: true })).toBeVisible()

    await page.keyboard.press("Control+s")
    await expect.poll(() => JSON.parse(readFileSync(filepath, "utf8")).cells[2].source).toEqual(["value + 2"])
    await expect
      .poll(() => JSON.parse(readFileSync(filepath, "utf8")).cells[2].outputs[0].data["text/plain"])
      .toBe("43")
    await expect
      .poll(() => JSON.parse(readFileSync(filepath, "utf8")).cells[2].metadata.openscience.provenance_id)
      .toMatch(/^[a-f0-9]{16}$/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
