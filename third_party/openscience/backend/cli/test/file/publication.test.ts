import { $ } from "bun"
import { describe, expect, test } from "bun:test"
import fs from "node:fs/promises"
import path from "node:path"
import { PublicationFile } from "../../src/file/publication"
import { PublicationReview } from "../../src/file/review"
import { Instance } from "../../src/project/instance"
import { tmpdir } from "../fixture/fixture"

describe("PublicationFile", () => {
  test("detects real local publication export capabilities", async () => {
    const capabilities = await PublicationFile.capabilities()
    expect(capabilities.formats.html).toBe(true)
    expect(capabilities.formats.docx).toBe(capabilities.pandoc)
    expect(capabilities.formats.pptx).toBe(capabilities.pandoc)
    expect(capabilities.formats.pdf).toBe(capabilities.pandoc && Boolean(capabilities.pdf_engine))
  })

  test("exports a secure standalone HTML publication without external tooling", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        await Bun.write(
          path.join(directory, "report.md"),
          "# Treatment response\n\nThe observed response was **42%**.\n\n<script>alert('unsafe')</script>\n",
        )
      },
    })
    const result = await PublicationFile.render(tmp.path, { path: "report.md", format: "html" })
    expect(result.path).toMatch(/^exports\/report-\d{8}-\d{9}-[a-f0-9]{8}\.html$/)
    expect(result.size).toBeGreaterThan(100)
    expect(result.engine).toBe("OpenScience Markdown")
    expect(result.readiness).toBe("draft")
    const html = await Bun.file(path.join(tmp.path, result.path)).text()
    expect(html).toContain("Treatment response")
    expect(html).toContain("Content-Security-Policy")
    expect(html).not.toContain("<script>alert")
  })

  test("keeps manuscript frontmatter out of the visible HTML body", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        await Bun.write(path.join(directory, "manuscript.md"), '---\ntitle: "Precipitación ficticia"\nlang: es\nbibliography: []\n---\n\n# Precipitación ficticia\n\nContenido completo con acentos.\n')
      },
    })
    const result = await PublicationFile.render(tmp.path, { path: "manuscript.md", format: "html" })
    const html = await Bun.file(path.join(tmp.path, result.path)).text()
    expect(html).toContain('<html lang="es">')
    expect(html).toContain('<title>Precipitación ficticia</title>')
    expect(html).toContain('<h1>Precipitación ficticia</h1>')
    expect(html).toContain('Contenido completo con acentos.')
    expect(html).not.toContain('bibliography:')
    expect(html).not.toContain('title:')
    expect(await Bun.file(path.join(tmp.path, "manuscript.md")).text()).toContain('bibliography: []')
  })

  test.skipIf(!Bun.which("pandoc"))("resolves local manuscript citations without exposing CSL markup", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        await Bun.write(path.join(directory, "report.md"), '---\nbibliography: refs.bib\n---\n\n# Synthetic study\n\nEvidence [@example].\n\n| Month | Value |\n|---|---|\n| January | 42 |\n')
        await Bun.write(path.join(directory, "refs.bib"), '@article{example, title={Complete synthetic reference}, author={Author, Alex}, year={2025}}')
      },
    })
    const result = await PublicationFile.render(tmp.path, { path: "report.md", format: "html" })
    const html = await Bun.file(path.join(tmp.path, result.path)).text()
    expect(html).not.toContain('[@example]')
    expect(html).not.toContain('csl-entry')
    expect(html).toContain('Author 2025')
    expect(html).toMatch(/Complete Synthetic Reference/i)
    expect(html).toContain('<table>')
  })

  test("rejects bibliography paths outside the project", async () => {
    await using tmp = await tmpdir({init: async (directory) => {
      await Bun.write(path.join(directory, "report.md"), '---\nbibliography: ../outside.bib\n---\n\n# Report\n')
    }})
    await expect(PublicationFile.render(tmp.path, {path: "report.md", format: "html"})).rejects.toThrow('Bibliography path escapes')
  })

  test("never overwrites a rapid repeated export", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        await Bun.write(path.join(directory, "report.md"), "# Stable export\n")
      },
    })

    const [first, second] = await Promise.all([
      PublicationFile.render(tmp.path, { path: "report.md", format: "html" }),
      PublicationFile.render(tmp.path, { path: "report.md", format: "html" }),
    ])
    expect(first.path).not.toBe(second.path)
    expect(await Bun.file(path.join(tmp.path, first.path)).exists()).toBe(true)
    expect(await Bun.file(path.join(tmp.path, second.path)).exists()).toBe(true)
  })

  test("rejects non-report inputs and project traversal", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        await Bun.write(path.join(directory, "data.csv"), "a,b\n1,2\n")
      },
    })
    await expect(PublicationFile.render(tmp.path, { path: "data.csv", format: "html" })).rejects.toThrow("Markdown")
    await expect(PublicationFile.render(tmp.path, { path: "../report.md", format: "html" })).rejects.toThrow("escapes")
  })

  test("rejects a Markdown source symlink that escapes the project", async () => {
    await using outside = await tmpdir({
      init: async (directory) => {
        await Bun.write(path.join(directory, "secret.md"), "# External secret\n")
      },
    })
    await using tmp = await tmpdir({
      init: async (directory) => {
        await fs.symlink(path.join(outside.path, "secret.md"), path.join(directory, "report.md"))
      },
    })

    await expect(PublicationFile.render(tmp.path, { path: "report.md", format: "html" })).rejects.toThrow("escapes")
  })

  test("gates reviewed exports on a finalized report for the exact source bytes", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (directory) => {
        await Bun.write(path.join(directory, "README.md"), "# Publication fixture\n")
        await Bun.write(path.join(directory, "uv.lock"), "version = 1\n")
        await Bun.write(path.join(directory, "pyproject.toml"), '[project]\nname = "publication-fixture"\n')
        await Bun.write(path.join(directory, "report.md"), "# Stable result\n\nAll structural checks pass.\n")
        await $`git add README.md uv.lock pyproject.toml report.md`.cwd(directory).quiet()
        await $`git -c user.name=OpenScience -c user.email=test@openscience.local commit -m "publication fixture"`
          .cwd(directory)
          .quiet()
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const review = await PublicationReview.run({ path: "report.md", actor: "Reviewer" })
        await expect(
          PublicationFile.render(tmp.path, {
            path: "report.md",
            format: "html",
            readiness: "reviewed",
            review_id: review.id,
          }),
        ).rejects.toThrow("finalized")

        const finalized = await PublicationReview.finalize(review.id, { actor: "Aayam Bansal" })
        const result = await PublicationFile.render(tmp.path, {
          path: "report.md",
          format: "html",
          readiness: "reviewed",
          review_id: finalized.id,
        })
        expect(result).toMatchObject({
          readiness: "reviewed",
          review_id: finalized.id,
        })

        await Bun.write(path.join(tmp.path, "report.md"), "# Changed after review\n")
        await expect(
          PublicationFile.render(tmp.path, {
            path: "report.md",
            format: "html",
            readiness: "reviewed",
            review_id: finalized.id,
          }),
        ).rejects.toThrow("changed")
        expect(
          (
            await PublicationFile.render(tmp.path, {
              path: "report.md",
              format: "html",
              readiness: "draft",
            })
          ).readiness,
        ).toBe("draft")
      },
    })
  })

  test("a reviewed Pandoc export renders the finalized snapshot when the source changes mid-export", async () => {
    await using tmp = await tmpdir({
      git: true,
      init: async (directory) => {
        await Bun.write(path.join(directory, "README.md"), "# Publication snapshot fixture\n")
        await Bun.write(path.join(directory, "uv.lock"), "version = 1\n")
        await Bun.write(path.join(directory, "pyproject.toml"), '[project]\nname = "publication-snapshot-fixture"\n')
        await Bun.write(path.join(directory, "report.md"), "# Reviewed result\n\nThe finalized value is 42%.\n")
        await $`git add README.md uv.lock pyproject.toml report.md`.cwd(directory).quiet()
        await $`git -c user.name=OpenScience -c user.email=test@openscience.local commit -m "snapshot fixture"`
          .cwd(directory)
          .quiet()
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const review = await PublicationReview.run({ path: "report.md", actor: "Reviewer" })
        const finalized = await PublicationReview.finalize(review.id, { actor: "Aayam Bansal" })
        const original = await Bun.file(path.join(tmp.path, "report.md")).text()
        const bin = path.join(tmp.path, "bin")
        const ready = path.join(tmp.path, "pandoc-ready")
        const resume = path.join(tmp.path, "pandoc-resume")
        const pandoc = path.join(bin, "pandoc")
        await fs.mkdir(bin, { recursive: true })
        await Bun.write(
          pandoc,
          `#!/bin/sh
source="$1"
shift
output=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output" ]; then
    shift
    output="$1"
  fi
  shift
done
printf ready > ${JSON.stringify(ready)}
while [ ! -f ${JSON.stringify(resume)} ]; do sleep 0.01; done
cp "$source" "$output"
`,
        )
        await fs.chmod(pandoc, 0o755)
        const prior = process.env.PATH
        process.env.PATH = `${bin}${path.delimiter}${prior ?? ""}`
        const pending = PublicationFile.render(tmp.path, {
          path: "report.md",
          format: "docx",
          readiness: "reviewed",
          review_id: finalized.id,
        })
        try {
          await (async () => {
            for (const _ of Array.from({ length: 200 })) {
              if (await Bun.file(ready).exists()) return
              await Bun.sleep(10)
            }
            throw new Error("Timed out waiting for the controlled Pandoc process")
          })()
          await Bun.write(path.join(tmp.path, "report.md"), "# Changed after validation\n")
          await Bun.write(resume, "resume")
          const result = await pending
          expect(await Bun.file(path.join(tmp.path, result.path)).text()).toBe(original)
        } finally {
          process.env.PATH = prior
          await Bun.write(resume, "resume")
        }
      },
    })
  })
})
