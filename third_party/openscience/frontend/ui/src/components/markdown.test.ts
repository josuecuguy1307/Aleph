import { describe, test, expect } from "bun:test"
import katex from "katex"
import { fileLinkPath, openFileLink, resolveImages, sanitize } from "./markdown"

describe("local file links", () => {
  test("opens encoded absolute notebook links without navigating away from the transcript", () => {
    const root = document.createElement("div")
    root.innerHTML = '<a href="/Users/test/Library/Application%20Support/Aleph/analisis.ipynb"><span>Notebook</span></a>'
    root.addEventListener("click", openFileLink)
    let path = ""
    const receive = (event: Event) => { path = (event as CustomEvent).detail.path }
    document.addEventListener("openscience:open-file", receive)
    const click = new MouseEvent("click", { bubbles: true, cancelable: true })
    root.querySelector("span")!.dispatchEvent(click)
    document.removeEventListener("openscience:open-file", receive)
    expect(click.defaultPrevented).toBe(true)
    expect(path).toBe("/Users/test/Library/Application Support/Aleph/analisis.ipynb")
  })

  test("preserves remote references and rejects schemes, malformed encodings and controls", () => {
    for (const href of ["https://example.com/paper.pdf", "//example.com/paper.pdf", "javascript:bad.pdf", "file:///tmp/a.pdf", "#part.md", "%ZZ.md", "/tmp/%00.md"]) {
      expect(fileLinkPath(href)).toBeUndefined()
    }
    expect(fileLinkPath("cert-e2e/informe.md")).toBe("cert-e2e/informe.md")
  })
})

const tex = "\\delta\\omega/\\omega < 10^{-6}"

describe("sanitize (KaTeX MathML annotation)", () => {
  test("keeps the <annotation> wrapper so raw TeX doesn't leak as visible text", () => {
    const katexHtml = katex.renderToString(tex, { throwOnError: false })
    const safe = sanitize(katexHtml)
    expect(safe).toContain("<annotation")
  })

  test("the TeX source appears only inside <annotation>, not as a bare child of <math>", () => {
    const katexHtml = katex.renderToString(tex, { throwOnError: false })
    const safe = sanitize(katexHtml)

    const doc = new DOMParser().parseFromString(safe, "text/html")
    const math = doc.querySelector("math")
    expect(math).not.toBeNull()

    // No direct text-node child of <math> should carry the raw TeX source.
    const bareLeak = Array.from(math?.childNodes ?? []).some(
      (node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").includes(tex),
    )
    expect(bareLeak).toBe(false)

    // The TeX source must actually be present, but only inside <annotation>.
    const annotation = doc.querySelector("annotation")
    expect(annotation).not.toBeNull()
    expect(annotation?.textContent).toContain(tex)
  })

  test("regression guard: still strips script-injection attributes across every node (sanitizer stays active)", () => {
    const safe = sanitize("<img src=x onerror=alert(1)><img src=y onerror=alert(2)><script>evil()</script>")
    expect(safe).not.toContain("onerror")
    expect(safe).not.toContain("<script")
  })

  test("regression guard: neutralizes payloads nested in the annotation-xml HTML integration point (#194)", () => {
    const safe = sanitize(
      '<math><semantics><annotation-xml encoding="text/html"><img src=x onerror=alert(1)><script>evil()</script></annotation-xml></semantics></math>',
    )
    expect(safe).not.toContain("onerror")
    expect(safe).not.toContain("<script")
  })
})

describe("resolveImages (relative image rewriting)", () => {
  const resolve = (src: string) =>
    /^(?:[a-z][a-z0-9+.-]*:|\/\/|#|\/)/i.test(src)
      ? src
      : `http://127.0.0.1:4096/file/raw?path=${encodeURIComponent(src)}`

  test("rewrites relative sources on already-sanitized markup", () => {
    const root = document.createElement("div")
    root.innerHTML = sanitize('<p>fig</p><img src="figures/plot.png" onerror="alert(1)" alt="plot">')

    resolveImages(root, resolve)

    const img = root.querySelector("img")
    expect(img?.getAttribute("src")).toBe("http://127.0.0.1:4096/file/raw?path=figures%2Fplot.png")
    expect(img?.getAttribute("alt")).toBe("plot")
    // sanitization already ran — script-injection attributes stay stripped
    expect(img?.getAttribute("onerror")).toBeNull()
  })

  test("leaves absolute and data URLs untouched", () => {
    const root = document.createElement("div")
    root.innerHTML = sanitize('<img src="https://example.com/a.png"><img src="data:image/png;base64,AAAA">')

    resolveImages(root, resolve)

    const sources = Array.from(root.querySelectorAll("img")).map((img) => img.getAttribute("src"))
    expect(sources).toEqual(["https://example.com/a.png", "data:image/png;base64,AAAA"])
  })
})
