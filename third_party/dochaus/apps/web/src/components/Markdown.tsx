import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

// Subagent results arrive wrapped by the task tool as
// <task id="..." state="completed"><task_result>…markdown…</task_result></task>.
// Strip that envelope so only the model's markdown reaches the renderer.
function unwrapTaskResult(text: string) {
  const match = text.match(/<task_result>([\s\S]*?)<\/task_result>/)
  return (match ? match[1] : text).trim()
}

export default function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{unwrapTaskResult(children)}</ReactMarkdown>
    </div>
  )
}

// Skill bodies and agent instructions carry XML-ish section tags (<task>,
// <rules>, ...) that ReactMarkdown would otherwise swallow as unknown HTML.
// Re-emit each tag as inline code on its own line so the sections stay visible
// and the markdown between them (bold, lists) still renders. Only tags alone on
// a line are rewritten, so inline-code mentions like `<section>` stay untouched.
export function DocMarkdown({ children }: { children: string }) {
  const escaped = children.replace(/^[ \t]*<(\/?[a-z][a-z0-9-]*)>[ \t]*$/gm, "\n\n`<$1>`\n\n")
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{escaped}</ReactMarkdown>
    </div>
  )
}
