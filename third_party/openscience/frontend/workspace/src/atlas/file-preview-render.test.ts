import { describe, expect, test } from "bun:test"
import { describeFile } from "./file-viewer"

const read = (path: string) => Bun.file(new URL(path, import.meta.url)).text()

describe("file preview markdown images", () => {
  test("markdown previews resolve relative images through the raw-file endpoint", async () => {
    const preview = await read("./FilePreview.tsx")

    expect(preview).toContain('import { assetUrl } from "@/utils/markdown-assets"')
    expect(preview).toContain("base: props.path")
    expect(preview).toContain('url: (path) => sdk.request.url("/file/raw", { path, sessionID: sessionID() })')
    expect(preview).toContain('<Markdown class="atlas-md" text={view.draft} resolveImage={image} />')
  })

  test("chat markdown resolves images against the project root via the shared context", async () => {
    const layout = await read("../pages/directory-layout.tsx")

    expect(layout).toContain('import { MarkdownImages } from "@synsci/ui/markdown"')
    expect(layout).toContain('sdk.request.url("/file/raw"')
    expect(layout).toContain("<MarkdownImages resolve={image}>")
  })

  test("the shared renderer rewrites image sources only after DOMPurify sanitization", async () => {
    const markdown = await read("../../../ui/src/components/markdown.tsx")

    const sanitized = markdown.indexOf("const safe = sanitize(next)")
    const resolved = markdown.indexOf("if (resolve) resolveImages(temp, resolve)")
    expect(sanitized).toBeGreaterThan(-1)
    expect(resolved).toBeGreaterThan(sanitized)
  })
})

describe("file preview sandboxed html", () => {
  test("html files render inside a fully sandboxed iframe with a Source toggle", async () => {
    const preview = await read("./FilePreview.tsx")

    expect(preview).toContain('if (x === "html" || x === "htm") return "html"')
    expect(preview).toContain('sandbox=""')
    expect(preview).toContain("srcdoc={view.draft}")
    expect(preview).toContain('<Match when={kind() === "html" && !view.source}>')
    // sandbox must stay fully locked down — never allow scripts or same-origin
    expect(preview).not.toContain("allow-scripts")
    expect(preview).not.toContain("allow-same-origin")
  })

  test("the iframe fills the pane", async () => {
    const css = await read("./FilePreview.css")

    expect(css).toContain(".atlas-file-html-frame")
    expect(css).toContain("min-height: 480px")
  })

  test("html documents expose the Preview/Source two-state control", () => {
    expect(describeFile({ kind: "html", format: "html" })).toEqual({
      label: "HTML document",
      source: true,
      copy: true,
      download: true,
    })
  })
})
