import { Hono } from "hono"
import { describeRoute, validator, resolver } from "hono-openapi"
import { Memory } from "@/settings/memory"
import { MemoryIndex } from "@/settings/memory-index"
import { Instance } from "@/project/instance"
import { lazy } from "@/util/lazy"
import z from "zod"

// GET/PUT keep their original request/response contract; responses additively
// gain a `capacity` field (computed on read, never stored — the PUT validator
// strips it before persisting).
const WithCapacity = Memory.Doc.extend({ capacity: Memory.Capacity })

function project() {
  try {
    return Instance.project.id
  } catch {
    return undefined
  }
}

export const MemorySettingsRoutes = lazy(() =>
  new Hono()
    .get(
      "/",
      describeRoute({
        summary: "Get memory",
        description: "Get the saved memory document for a scope (global or project), with its capacity gauge.",
        operationId: "settings.memory.get",
        responses: {
          200: {
            description: "Memory document",
            content: { "application/json": { schema: resolver(WithCapacity) } },
          },
        },
      }),
      validator("query", z.object({ scope: Memory.Scope.default("global") })),
      async (c) => {
        const doc = await Memory.get(c.req.valid("query").scope)
        return c.json({ ...doc, capacity: Memory.measure(doc) })
      },
    )
    .put(
      "/",
      describeRoute({
        summary: "Set memory",
        description: "Replace the saved memory document for a scope (global or project).",
        operationId: "settings.memory.set",
        responses: {
          200: {
            description: "Updated memory document",
            content: { "application/json": { schema: resolver(WithCapacity) } },
          },
        },
      }),
      validator("query", z.object({ scope: Memory.Scope.default("global") })),
      validator("json", Memory.Doc),
      async (c) => {
        const doc = await Memory.set(c.req.valid("query").scope, c.req.valid("json"))
        return c.json({ ...doc, capacity: Memory.measure(doc) })
      },
    )
    .get(
      "/search",
      describeRoute({
        summary: "Search memory",
        description:
          "Full-text search (FTS5 BM25 keyword ranking with a recency tiebreak — not semantic) over saved memory notes and past session messages of the current project.",
        operationId: "settings.memory.search",
        responses: {
          200: {
            description: "Full-text search hits",
            content: { "application/json": { schema: resolver(z.object({ results: MemoryIndex.Hit.array() })) } },
          },
        },
      }),
      validator("query", z.object({ q: z.string().min(1), limit: z.coerce.number().int().min(1).max(50).default(20) })),
      async (c) => {
        const query = c.req.valid("query")
        return c.json({ results: await MemoryIndex.search(query.q, { limit: query.limit, project: project() }) })
      },
    ),
)
