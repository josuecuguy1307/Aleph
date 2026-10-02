/** Normalize model-produced math before Markdown consumes backslash escapes. */
export function normalizeMathDelimiters(markdown: string): string {
  const code = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/g
  return markdown.split(code).map((part, index) => index % 2 ? part : part
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, math: string) => `\n\n$$\n${math.trim()}\n$$\n\n`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, math: string) => `$${math.trim()}$`)).join("")
}
