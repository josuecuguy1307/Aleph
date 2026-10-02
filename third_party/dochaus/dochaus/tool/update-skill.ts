import { tool } from "@opencode-ai/plugin"

// doc.haus update-skill tool. Rewrites a custom firm skill in
// WORKSPACE_ROOT/.skills. Built-in skills are read-only.

const ingestUrl = process.env.INGEST_URL ?? "http://127.0.0.1:0"

export default tool({
  description:
    "Update an existing custom firm skill: replaces its description and full markdown body. Built-in skills cannot be updated. Use list-skills first to read the current body — supply the complete revised body, not a diff.",
  args: {
    name: tool.schema.string().describe("Exact name of the custom skill to update"),
    description: tool.schema.string().describe("Revised one-line summary including when to use it"),
    content: tool.schema.string().describe("The complete revised skill body as markdown"),
  },
  async execute(args, ctx) {
    await ctx.ask({ permission: "update-skill", patterns: [args.name], metadata: { skill: args.name } })
    const res = await fetch(`${ingestUrl}/skills/${encodeURIComponent(args.name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: args.description, content: args.content }),
    })
    if (!res.ok) return `Update failed (${res.status}): ${((await res.json()) as { error: string }).error}`
    return {
      title: `Updated skill ${args.name}`,
      output: `Updated "${args.name}".`,
      metadata: { skill: args.name },
    }
  },
})
