import fs from "node:fs/promises"
import path from "node:path"
import { marked, Renderer } from "marked"
import matter from "gray-matter"
import z from "zod"
import { OpenScience } from "../openscience"
import { Filesystem } from "../util/filesystem"
import { escapeHtml } from "../util/html"
import { PublicationReview } from "./review"

export namespace PublicationFile {
  export const Format = z.enum(["html", "pdf", "docx", "latex", "pptx"])
  export type Format = z.infer<typeof Format>

  export const Input = z
    .object({
      path: z.string().trim().min(1).max(4_000),
      format: Format,
      readiness: z.enum(["draft", "reviewed"]).default("draft"),
      review_id: z.string().startsWith("review_").optional(),
    })
    .superRefine((input, context) => {
      if (input.readiness !== "reviewed" || input.review_id) return
      context.addIssue({
        code: "custom",
        path: ["review_id"],
        message: "Exporting preflight-checked bytes requires a finalized publication preflight report",
      })
    })
  export type Input = z.input<typeof Input>

  export const Capabilities = z.object({
    pandoc: z.boolean(),
    pdf_engine: z.string().optional(),
    formats: z.record(Format, z.boolean()),
  })
  export type Capabilities = z.infer<typeof Capabilities>

  export const Result = z.object({
    path: z.string(),
    format: Format,
    size: z.number().int().nonnegative(),
    created_at: z.string(),
    engine: z.string(),
    readiness: z.enum(["draft", "reviewed"]),
    review_id: z.string().optional(),
  })
  export type Result = z.infer<typeof Result>

  const extensions: Record<Format, string> = {
    html: "html",
    pdf: "pdf",
    docx: "docx",
    latex: "tex",
    pptx: "pptx",
  }

  export async function capabilities(): Promise<Capabilities> {
    const options = { PATH: process.env.PATH }
    const pandoc = Boolean(Bun.which("pandoc", options))
    const pdf =
      Bun.which("xelatex", options) ?? Bun.which("pdflatex", options) ?? Bun.which("typst", options) ?? undefined
    return Capabilities.parse({
      pandoc,
      pdf_engine: pdf ? path.basename(pdf) : undefined,
      formats: {
        html: true,
        pdf: pandoc && Boolean(pdf),
        docx: pandoc,
        latex: pandoc,
        pptx: pandoc,
      },
    })
  }

  export async function render(root: string, input: Input): Promise<Result> {
    const parsed = Input.parse(input)
    const source = resolve(root, parsed.path)
    if (![".md", ".markdown"].includes(path.extname(source).toLowerCase())) {
      throw new Error("Publication export currently requires a Markdown report")
    }
    if (!(await Filesystem.containsCanonical(root, source))) {
      throw new Error("Publication path escapes the project directory")
    }
    if (!(await Bun.file(source).exists())) throw new Error(`Report not found: ${parsed.path}`)
    const snapshot = await Bun.file(source).arrayBuffer()
    const markdown = new TextDecoder().decode(snapshot)
    const report = matter(markdown)
    const artifactHash = await hash(snapshot)
    const review =
      parsed.readiness === "reviewed"
        ? await PublicationReview.assertReady(parsed.path, parsed.review_id!, artifactHash)
        : undefined
    const support = await capabilities()
    const declared = typeof report.data.bibliography === "string"
      ? [report.data.bibliography]
      : Array.isArray(report.data.bibliography) ? report.data.bibliography.filter((value): value is string => typeof value === "string") : []
    const bibliographies = await Promise.all(declared.map(async (reference) => {
      const file = path.resolve(path.dirname(source), reference)
      if (!(await Filesystem.containsCanonical(root, file))) throw new Error("Bibliography path escapes the project directory")
      if (!(await Bun.file(file).exists())) throw new Error(`Bibliography not found: ${reference}`)
      return file
    }))
    const citationArgs = bibliographies.length ? ["--citeproc", ...bibliographies.map((file) => `--bibliography=${file}`)] : []
    if (!support.formats[parsed.format]) {
      throw new Error(
        parsed.format === "pdf"
          ? "PDF export requires Pandoc and a local TeX or Typst engine"
          : `${parsed.format.toUpperCase()} export requires Pandoc`,
      )
    }
    const folder = path.join(root, "exports")
    await fs.mkdir(folder, { recursive: true })
    const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 17)
    const nonce = crypto.randomUUID().slice(0, 8)
    const stem =
      path
        .basename(source, path.extname(source))
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, "-")
        .replace(/^-+|-+$/g, "") || "report"
    const relative = path.join(
      "exports",
      `${stem}-${stamp.slice(0, 8)}-${stamp.slice(8)}-${nonce}.${extensions[parsed.format]}`,
    )
    const target = path.join(root, relative)
    if (parsed.format === "html") {
      let content = report.content
      if (citationArgs.length) {
        if (!support.pandoc) throw new Error("Publication citation rendering requires Pandoc")
        const proc = Bun.spawn(["pandoc", "--from=markdown", "--to=markdown_strict+pipe_tables+fenced_code_blocks+tex_math_dollars", ...citationArgs], {
          cwd: root,
          env: await OpenScience.subprocessEnv(process.env),
          stdin: new Blob([snapshot]),
          stdout: "pipe",
          stderr: "pipe",
        })
        const [code, output, error] = await Promise.all([proc.exited, new Response(proc.stdout).text(), new Response(proc.stderr).text()])
        if (code !== 0) throw new Error(error.trim() || `Pandoc exited with code ${code}`)
        content = output
      }
      const renderer = new Renderer()
      renderer.html = ({ text }) => escapeHtml(text)
      renderer.link = ({ href, title, tokens }) => {
        const content = renderer.parser.parseInline(tokens)
        const target = safe(href, false)
        if (!target) return content
        const hint = title ? ` title="${escapeHtml(title)}"` : ""
        return `<a href="${escapeHtml(target)}"${hint}>${content}</a>`
      }
      renderer.image = ({ href, title, text }) => {
        const target = safe(href, true)
        if (!target) return escapeHtml(text)
        const hint = title ? ` title="${escapeHtml(title)}"` : ""
        return `<img src="${escapeHtml(target)}" alt="${escapeHtml(text)}"${hint}>`
      }
      const body = await marked.parse(content, { gfm: true, renderer })
      const base = `${path.relative(folder, path.dirname(source)).split(path.sep).join("/") || "."}/`
      const title = typeof report.data.title === "string" ? report.data.title : path.basename(source, path.extname(source))
      const language = typeof report.data.lang === "string" ? report.data.lang : "en"
      const document = `<!doctype html>
<html lang="${escapeHtml(language)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data: https: http:; style-src 'unsafe-inline'; font-src 'self' data:">
  <base href="${escapeHtml(base)}">
  <title>${escapeHtml(title)}</title>
  <style>
    :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; line-height: 1.65; }
    body { max-width: 860px; margin: 0 auto; padding: 48px 28px 80px; color: #20211f; background: #fbfbf8; }
    h1, h2, h3 { line-height: 1.2; letter-spacing: -0.02em; }
    h1 { font-size: 2.25rem; margin-bottom: 1.5rem; }
    h2 { margin-top: 2.5rem; border-bottom: 1px solid #d8d8d0; padding-bottom: .35rem; }
    a { color: #315f8c; }
    img { display: block; max-width: 100%; height: auto; margin: 1.5rem auto; }
    table { width: 100%; border-collapse: collapse; margin: 1.5rem 0; }
    th, td { border: 1px solid #d8d8d0; padding: .55rem .7rem; text-align: left; }
    pre, code { font-family: ui-monospace, SFMono-Regular, monospace; background: #efefe9; border-radius: 4px; }
    pre { overflow: auto; padding: 1rem; }
    code { padding: .12rem .28rem; }
    pre code { padding: 0; }
    blockquote { margin-left: 0; padding-left: 1rem; border-left: 3px solid #a8aaa2; color: #555750; }
    @media print { body { max-width: none; padding: 0; background: #fff; } a { color: inherit; } }
    @media (prefers-color-scheme: dark) {
      body { color: #e6e6df; background: #191a18; }
      h2, th, td { border-color: #41433e; }
      pre, code { background: #292b27; }
      a { color: #8bb8e3; }
    }
  </style>
</head>
<body>
${body}
</body>
</html>
`
      await Bun.write(target, document)
      const stat = await fs.stat(target)
      return Result.parse({
        path: relative.split(path.sep).join("/"),
        format: parsed.format,
        size: stat.size,
        created_at: new Date().toISOString(),
        engine: "OpenScience Markdown",
        readiness: parsed.readiness,
        ...(review ? { review_id: review.id } : {}),
      })
    }
    const snapshotFile = path.join(folder, `.openscience-publication-${nonce}.md`)
    await Bun.write(snapshotFile, snapshot)
    const args = [
      "pandoc",
      snapshotFile,
      "--standalone",
      `--resource-path=${path.dirname(source)}${path.delimiter}${root}`,
      "--output",
      target,
      ...citationArgs,
      ...(parsed.format === "pdf" && support.pdf_engine ? [`--pdf-engine=${support.pdf_engine}`] : []),
    ]
    const proc = Bun.spawn(args, {
      cwd: root,
      env: await OpenScience.subprocessEnv(process.env),
      stdin: "ignore",
      stdout: "pipe",
      stderr: "pipe",
    })
    const [code, stdout, stderr] = await Promise.all([
      proc.exited,
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
    ]).finally(() => fs.rm(snapshotFile, { force: true }))
    if (code !== 0) {
      await fs.rm(target, { force: true })
      throw new Error(stderr.trim() || stdout.trim() || `Pandoc exited with code ${code}`)
    }
    const stat = await fs.stat(target)
    return Result.parse({
      path: relative.split(path.sep).join("/"),
      format: parsed.format,
      size: stat.size,
      created_at: new Date().toISOString(),
      engine: parsed.format === "pdf" ? `pandoc + ${support.pdf_engine}` : "pandoc",
      readiness: parsed.readiness,
      ...(review ? { review_id: review.id } : {}),
    })
  }

  function resolve(root: string, file: string): string {
    const target = path.resolve(root, file)
    const relative = path.relative(root, target)
    if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
      throw new Error("Publication path escapes the project directory")
    }
    return target
  }

  function safe(value: string, image: boolean): string | undefined {
    const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(value)?.[1]?.toLowerCase()
    if (!scheme) return value
    if (scheme === "http" || scheme === "https") return value
    if (!image && scheme === "mailto") return value
    if (image && scheme === "data" && /^data:image\//i.test(value)) return value
    return undefined
  }

  async function hash(value: ArrayBuffer) {
    const digest = await crypto.subtle.digest("SHA-256", value)
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("")
  }
}
