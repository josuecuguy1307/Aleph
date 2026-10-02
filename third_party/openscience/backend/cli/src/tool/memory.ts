import z from "zod"
import { Tool } from "./tool"
import { Memory } from "@/settings/memory"
import { MemoryIndex } from "@/settings/memory-index"
import { Instance } from "@/project/instance"
import DESCRIPTION from "./memory.txt"

function result(title: string, output: string, metadata: Record<string, unknown> = {}) {
  return { title, output, metadata }
}

function disabled(scope: string) {
  return result(
    "Memory disabled",
    [
      `Memory is disabled in Settings → Memory for the ${scope} scope, so nothing was changed.`,
      "Ask the user to enable it there if memory should be used.",
    ].join("\n"),
  )
}

function project() {
  try {
    return Instance.project.id
  } catch {
    return undefined
  }
}

export const MemoryTool = Tool.define("memory", {
  description: DESCRIPTION,
  parameters: z.object({
    action: z.enum(["add", "replace", "remove", "search"]).describe("The action"),
    text: z.string().optional().describe("For add: the note to save. For replace: the replacement text"),
    old_text: z
      .string()
      .optional()
      .describe("For replace/remove: exact case-sensitive substring identifying one existing note"),
    category: z.string().optional().describe('For add: category name (created if missing; default "General")'),
    scope: Memory.Scope.optional().describe('Memory scope: "project" (default) or "global"'),
    query: z.string().optional().describe("For search: full-text query over notes and past sessions"),
    limit: z.number().int().min(1).max(20).optional().describe("For search: max results (default 8)"),
  }),
  async execute(params) {
    const scope = params.scope ?? "project"

    if (params.action === "search") {
      if (!params.query) return result("Error", "search requires the `query` parameter")
      const docs = await Promise.all(Memory.Scope.options.map((s) => Memory.get(s).catch(() => undefined)))
      if (docs.every((doc) => !doc?.enabled))
        return result(
          "Memory disabled",
          "Memory is disabled in Settings → Memory, so there is nothing to search. Ask the user to enable it there if memory should be used.",
        )
      const hits = await MemoryIndex.search(params.query, { limit: params.limit, project: project() })
      const gauges = Memory.Scope.options
        .map((s, i) => `${s} ${docs[i]?.enabled ? Memory.measure(docs[i]!).gauge : "(disabled)"}`)
        .join(", ")
      if (hits.length === 0)
        return result(
          "No matches",
          [
            `No full-text matches for "${params.query}" in memory notes or past sessions of this project.`,
            `Capacity: ${gauges}`,
          ].join("\n"),
          { count: 0 },
        )
      const lines = hits.map((hit) => {
        const when = new Date(hit.created).toISOString().slice(0, 10)
        if (hit.kind === "note") return `- [note ${hit.scope}/${hit.category} ${when}] ${hit.text}`
        return `- [session ${hit.sessionID} ${hit.role} ${when}] ${hit.text}`
      })
      return result(`${hits.length} match(es)`, [...lines, "", `Capacity: ${gauges}`].join("\n"), {
        count: hits.length,
      })
    }

    const doc = await Memory.get(scope)
    if (!doc.enabled) return disabled(scope)

    if (params.action === "add") {
      if (!params.text) return result("Error", "add requires the `text` parameter")
      const saved = await Memory.append(scope, { text: params.text, category: params.category, source: "agent" })
      return result(
        "Memory saved",
        [`Saved to ${scope} memory:`, `  ${saved.note.text}`, "", `Capacity ${saved.capacity.gauge}`].join("\n"),
        { id: saved.note.id, scope },
      )
    }

    if (params.action === "replace") {
      if (!params.old_text || !params.text) return result("Error", "replace requires `old_text` and `text` parameters")
      const edited = await Memory.replace(scope, params.old_text, params.text)
      return result(
        "Memory updated",
        [`Updated ${scope} note:`, `  ${edited.note.text}`, "", `Capacity ${edited.capacity.gauge}`].join("\n"),
        { id: edited.note.id, scope },
      )
    }

    if (!params.old_text) return result("Error", "remove requires the `old_text` parameter")
    const removed = await Memory.remove(scope, params.old_text)
    return result(
      "Memory removed",
      [`Removed ${scope} note:`, `  ${removed.note.text}`, "", `Capacity ${removed.capacity.gauge}`].join("\n"),
      { id: removed.note.id, scope },
    )
  },
})
