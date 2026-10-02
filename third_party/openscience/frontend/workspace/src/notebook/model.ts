export type NotebookOutput = Record<string, unknown> & {
  output_type: string
}

export type NotebookCell = Record<string, unknown> & {
  cell_type: "code" | "markdown" | "raw"
  id: string
  metadata: Record<string, unknown>
  source: string[]
  execution_count?: number | null
  outputs?: NotebookOutput[]
}

export type NotebookDocument = Record<string, unknown> & {
  cells: NotebookCell[]
  metadata: Record<string, unknown>
  nbformat: number
  nbformat_minor: number
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)

const lines = (source: string) => source.match(/[^\n]*\n|[^\n]+$/g) ?? []

const id = () => `cell-${globalThis.crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`

const source = (value: unknown) => {
  if (typeof value === "string") return lines(value)
  if (Array.isArray(value) && value.every((part) => typeof part === "string")) return value
  return []
}

const cell = (value: unknown): NotebookCell => {
  if (!record(value)) throw new Error("cells must contain objects")
  const kind = value.cell_type
  if (kind !== "code" && kind !== "markdown" && kind !== "raw") {
    throw new Error("cells must have a supported cell_type")
  }

  const base: NotebookCell = {
    ...value,
    cell_type: kind,
    id: typeof value.id === "string" && value.id ? value.id : id(),
    metadata: record(value.metadata) ? value.metadata : {},
    source: source(value.source),
  }
  if (kind !== "code") return base

  return {
    ...base,
    execution_count: typeof value.execution_count === "number" ? value.execution_count : null,
    outputs: Array.isArray(value.outputs)
      ? value.outputs.filter(
          (output): output is NotebookOutput => record(output) && typeof output.output_type === "string",
        )
      : [],
  }
}

export function parseNotebook(text: string): NotebookDocument {
  try {
    const value: unknown = JSON.parse(text)
    if (!record(value) || !Array.isArray(value.cells)) throw new Error("missing cells")

    return {
      ...value,
      cells: value.cells.map(cell),
      metadata: record(value.metadata) ? value.metadata : {},
      nbformat: typeof value.nbformat === "number" ? value.nbformat : 4,
      nbformat_minor: typeof value.nbformat_minor === "number" ? value.nbformat_minor : 5,
    }
  } catch (error) {
    const reason = error instanceof Error ? error.message : "unknown error"
    throw new Error(`Invalid notebook JSON: ${reason}`)
  }
}

export function serializeNotebook(notebook: NotebookDocument) {
  return `${JSON.stringify(notebook, null, 2)}\n`
}

export function createCell(kind: "code" | "markdown" | "raw", text = ""): NotebookCell {
  const base: NotebookCell = {
    cell_type: kind,
    id: id(),
    metadata: {},
    source: lines(text),
  }
  if (kind !== "code") return base

  return {
    ...base,
    execution_count: null,
    outputs: [],
  }
}

export function sourceText(value: NotebookCell) {
  return value.source.join("")
}

export function updateSource(value: NotebookCell, text: string): NotebookCell {
  return {
    ...value,
    source: lines(text),
  }
}

export function insertCell(notebook: NotebookDocument, index: number, value: NotebookCell): NotebookDocument {
  const cells = notebook.cells.slice()
  cells.splice(Math.max(0, Math.min(index, cells.length)), 0, value)
  return { ...notebook, cells }
}

export function removeCell(notebook: NotebookDocument, index: number): NotebookDocument {
  if (index < 0 || index >= notebook.cells.length) return notebook
  return {
    ...notebook,
    cells: notebook.cells.filter((_, position) => position !== index),
  }
}

export function moveCell(notebook: NotebookDocument, from: number, to: number): NotebookDocument {
  if (from < 0 || from >= notebook.cells.length || from === to) return notebook
  const cells = notebook.cells.slice()
  const value = cells.splice(from, 1)[0]
  if (!value) return notebook
  cells.splice(Math.max(0, Math.min(to, cells.length)), 0, value)
  return { ...notebook, cells }
}

export function clearOutputs(notebook: NotebookDocument): NotebookDocument {
  return {
    ...notebook,
    cells: notebook.cells.map((value) => {
      if (value.cell_type !== "code") return value
      return {
        ...value,
        execution_count: null,
        outputs: [],
      }
    }),
  }
}

const outputText = (value: NotebookOutput) => {
  if (value.output_type === "stream") {
    if (Array.isArray(value.text)) return value.text.map(String).join("")
    return typeof value.text === "string" ? value.text : ""
  }
  if (value.output_type === "error") {
    if (Array.isArray(value.traceback)) return value.traceback.map(String).join("\n")
    return `${String(value.ename ?? "Error")}: ${String(value.evalue ?? "")}`
  }
  if (!record(value.data)) return ""
  const plain = value.data["text/plain"]
  if (Array.isArray(plain)) return plain.map(String).join("")
  return typeof plain === "string" ? plain : ""
}

export function exportScript(notebook: NotebookDocument, language: "python" | "r") {
  const comment = language === "r" ? "# " : "# "
  const cells = notebook.cells.map((value) => {
    const text = sourceText(value)
    if (value.cell_type === "code") return `# %%\n${text}`
    const body = text
      .split("\n")
      .map((line) => `${comment}${line}`)
      .join("\n")
    return `# %% [${value.cell_type}]\n${body}`
  })
  return `${cells.join("\n\n")}\n`
}

export function exportMarkdown(notebook: NotebookDocument, language: "python" | "r") {
  const cells = notebook.cells.flatMap((value) => {
    const text = sourceText(value)
    if (value.cell_type === "markdown") return [text]
    if (value.cell_type === "raw") return [`\`\`\`text\n${text}\n\`\`\``]

    const code = `\`\`\`${language}\n${text}\n\`\`\``
    const outputs = (value.outputs ?? [])
      .map(outputText)
      .filter(Boolean)
      .map((output) => `\`\`\`text\n${output}\n\`\`\``)
    return [code, ...outputs]
  })
  return `${cells.join("\n\n")}\n`
}

const escapeHtml = (value: string) =>
  value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;")

export function exportHtml(notebook: NotebookDocument, title: string) {
  const cells = notebook.cells
    .map((value) => {
      const text = escapeHtml(sourceText(value))
      if (value.cell_type === "markdown") return `<section class="markdown"><pre>${text}</pre></section>`
      if (value.cell_type === "raw") return `<section class="raw"><pre>${text}</pre></section>`
      const outputs = (value.outputs ?? [])
        .map(outputText)
        .filter(Boolean)
        .map((output) => `<pre class="output">${escapeHtml(output)}</pre>`)
        .join("")
      return `<section class="cell"><pre class="code"><code>${text}</code></pre>${outputs}</section>`
    })
    .join("\n")

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <style>
    :root { color-scheme: light dark; font: 15px/1.6 ui-sans-serif, system-ui, sans-serif; }
    body { max-width: 920px; margin: 0 auto; padding: 48px 24px 96px; background: Canvas; color: CanvasText; }
    section { margin: 0 0 18px; }
    pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
    .markdown pre { font: inherit; }
    .code, .output { padding: 16px 18px; border: 1px solid color-mix(in srgb, CanvasText 14%, Canvas); border-radius: 8px; font: 13px/1.6 ui-monospace, monospace; }
    .code { background: color-mix(in srgb, CanvasText 4%, Canvas); }
    .output { margin-top: 8px; border-color: color-mix(in srgb, CanvasText 9%, Canvas); }
  </style>
</head>
<body>
${cells}
</body>
</html>
`
}
