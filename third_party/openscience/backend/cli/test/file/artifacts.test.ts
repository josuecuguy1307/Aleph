import { describe, expect, test } from "bun:test"
import { $ } from "bun"
import path from "node:path"
import { ArtifactFile } from "../../src/file/artifacts"
import { File } from "../../src/file"
import { Instance } from "../../src/project/instance"
import { tmpdir } from "../fixture/fixture"

describe("ArtifactFile.classify", () => {
  test.each([
    ["analysis.ipynb", "notebook"],
    ["cells.h5ad", "dataset"],
    ["counts.parquet", "dataset"],
    ["figure.svg", "figure"],
    ["manuscript.pdf", "report"],
    ["protein.cif", "structure"],
    ["reads.fastq", "sequence"],
    ["cohort.vcf", "genomics"],
    ["run.mzML", "spectrum"],
    ["weights.safetensors", "model"],
    ["bundle.zip", "archive"],
  ])("classifies %s as %s", (file, kind) => {
    expect(ArtifactFile.classify(file)?.kind).toBe(ArtifactFile.Kind.parse(kind))
  })

  test("does not treat source code as a research artifact", () => {
    expect(ArtifactFile.classify("pipeline.py")).toBeUndefined()
  })
})

describe("File.artifacts", () => {
  test("discovers local artifacts recursively with metadata and skips dependency trees", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        await Bun.write(path.join(directory, "analysis.ipynb"), "{}")
        await Bun.write(path.join(directory, "results", "figure.png"), Uint8Array.from([1, 2, 3]))
        await Bun.write(path.join(directory, "results", "table.csv"), "x,y\n1,2\n")
        await Bun.write(path.join(directory, "src", "pipeline.py"), "print('not an artifact')")
        await Bun.write(path.join(directory, "node_modules", "package", "paper.pdf"), "skip")
      },
    })
    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const result = await File.artifacts()
        expect(result.map((item) => item.path).toSorted()).toEqual([
          "analysis.ipynb",
          "results/figure.png",
          "results/table.csv",
        ])
        expect(result.find((item) => item.path === "analysis.ipynb")).toMatchObject({
          kind: "notebook",
          format: "ipynb",
          size: 2,
        })
        expect(result.find((item) => item.path === "results/figure.png")).toMatchObject({
          kind: "figure",
          format: "png",
          size: 3,
        })
      },
    })
  })
})

describe("File.provenance", () => {
  test("reports branch, latest commit, and dirty state for a tracked artifact", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (directory) => {
        await Bun.write(path.join(directory, "results.csv"), "metric,value\naccuracy,0.9\n")
        await $`git add results.csv`.cwd(directory).quiet()
        await $`git -c user.name=OpenScience -c user.email=test@openscience.local commit -m "record baseline"`
          .cwd(directory)
          .quiet()
        await Bun.write(path.join(directory, "results.csv"), "metric,value\naccuracy,0.95\n")
      },
    })
    const branch = (await $`git branch --show-current`.cwd(tmp.path).quiet().text()).trim()

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const result = await File.provenance("results.csv")
        expect(result).toMatchObject({
          path: "results.csv",
          tracked: true,
          dirty: true,
          status: "modified",
          branch,
          commit: {
            author: "OpenScience",
            email: "test@openscience.local",
            message: "record baseline",
          },
        })
        expect(result.commit?.sha).toHaveLength(40)
      },
    })
  })

  test("reports a clean local-only state outside git", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        await Bun.write(path.join(directory, "report.pdf"), "pdf")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        expect(await File.provenance("report.pdf")).toMatchObject({
          tracked: false,
          dirty: false,
          status: "local",
        })
      },
    })
  })
})
