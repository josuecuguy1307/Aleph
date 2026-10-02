import { describe, expect, test } from "bun:test"
import { artifactActions, filterArtifacts, groupArtifacts, normalizeArtifacts, sortArtifacts } from "./model"

const rows = normalizeArtifacts([
  { name: "analysis.ipynb", path: "analysis.ipynb", kind: "notebook", format: "ipynb", size: 20, modified: 10 },
  { name: "figure.png", path: "results/figure.png", kind: "figure", format: "png", size: 30, modified: 30 },
  { name: "counts.csv", path: "results/counts.csv", kind: "dataset", format: "csv", size: 10, modified: 20 },
])

describe("artifact gallery model", () => {
  test("normalizes only valid artifact rows", () => {
    expect(normalizeArtifacts([{ kind: "nope" }, null, ...rows])).toHaveLength(3)
  })

  test("filters by kind and searches names, paths, and formats", () => {
    expect(filterArtifacts(rows, "figure", "result")).toEqual([rows[1]])
    expect(filterArtifacts(rows, "all", "IPYNB")).toEqual([rows[0]])
    expect(filterArtifacts(rows, "dataset", "")).toEqual([rows[2]])
  })

  test("groups artifact counts by kind", () => {
    expect(groupArtifacts(rows)).toEqual([
      { kind: "dataset", count: 1 },
      { kind: "figure", count: 1 },
      { kind: "notebook", count: 1 },
    ])
  })

  test("sorts by recency, size, and name without mutating input", () => {
    expect(sortArtifacts(rows, "recent").map((row) => row.name)).toEqual(["figure.png", "counts.csv", "analysis.ipynb"])
    expect(sortArtifacts(rows, "size").map((row) => row.name)).toEqual(["figure.png", "analysis.ipynb", "counts.csv"])
    expect(sortArtifacts(rows, "name").map((row) => row.name)).toEqual(["analysis.ipynb", "counts.csv", "figure.png"])
    expect(rows[0]?.name).toBe("analysis.ipynb")
  })

  test("offers scientific actions tailored to each artifact kind", () => {
    expect(artifactActions(rows[2]!).map((action) => action.id)).toEqual(["inspect-quality", "visualize", "analyze"])
    // Reviewing is a direct route action, never a chat prompt — the notebook
    // catalog must not reintroduce a "spawn the reviewer" prefill.
    expect(artifactActions(rows[0]!).map((action) => action.id)).toEqual(["run-notebook", "export-notebook"])
    expect(
      artifactActions({
        name: "protein.pdb",
        path: "protein.pdb",
        kind: "structure",
        format: "pdb",
        size: 100,
        modified: 1,
      }).map((action) => action.id),
    ).toEqual(["inspect-structure", "prepare-docking", "design"])
    expect(artifactActions(rows[2]!)[0]?.prompt).toContain("results/counts.csv")
  })
})
