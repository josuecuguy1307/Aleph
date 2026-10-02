import { Hono } from "hono"
import { describeRoute, validator, resolver } from "hono-openapi"
import z from "zod"
import { File } from "../../file"
import { Session } from "../../session"
import { lazy } from "../../util/lazy"

// Plain-text project search over session titles, conversation text, and
// artifact files. Honest scope: case-insensitive substring matching over
// recent content, no semantic index — the UI labels it accordingly.
const Result = z.object({
  sessions: z.array(z.object({ id: z.string(), title: z.string() })),
  messages: z.array(z.object({ sessionID: z.string(), messageID: z.string(), role: z.string(), snippet: z.string() })),
  artifacts: z.array(z.object({ path: z.string(), name: z.string(), kind: z.string() })),
})

const SESSION_CAP = 200
const MESSAGE_CAP = 200
const MATCH_CAP = 20

export const SearchRoutes = lazy(() =>
  new Hono().get(
    "/",
    describeRoute({
      summary: "Search sessions, messages, and artifacts",
      description:
        "Case-insensitive plain-text search across session titles, recent conversation text, and artifact files in the project.",
      operationId: "search.query",
      responses: {
        200: {
          description: "Grouped plain-text matches",
          content: { "application/json": { schema: resolver(Result) } },
        },
      },
    }),
    validator("query", z.object({ q: z.string().trim().min(2).max(200) })),
    async (c) => {
      const query = c.req.valid("query").q.toLowerCase()
      const sessions: Array<{ id: string; title: string }> = []
      const messages: Array<{ sessionID: string; messageID: string; role: string; snippet: string }> = []
      const artifacts: Array<{ path: string; name: string; kind: string }> = []

      const snippet = (text: string, index: number) => {
        const start = Math.max(0, index - 60)
        const end = Math.min(text.length, index + query.length + 60)
        return `${start > 0 ? "…" : ""}${text.slice(start, end).trim()}${end < text.length ? "…" : ""}`
      }

      let scanned = 0
      for await (const session of Session.list()) {
        if (scanned >= SESSION_CAP) break
        scanned += 1
        if (session.parentID) continue
        if (sessions.length < MATCH_CAP && session.title.toLowerCase().includes(query)) {
          sessions.push({ id: session.id, title: session.title })
        }
        if (messages.length >= MATCH_CAP) continue
        const items = await Session.messages({ sessionID: session.id, limit: MESSAGE_CAP }).catch(
          () => [] as Awaited<ReturnType<typeof Session.messages>>,
        )
        for (const item of items) {
          if (messages.length >= MATCH_CAP) break
          for (const part of item.parts) {
            if (part.type !== "text") continue
            const index = part.text.toLowerCase().indexOf(query)
            if (index === -1) continue
            messages.push({
              sessionID: session.id,
              messageID: item.info.id,
              role: item.info.role,
              snippet: snippet(part.text, index),
            })
            break
          }
        }
      }

      for (const artifact of await File.artifacts().catch(() => [])) {
        if (artifacts.length >= MATCH_CAP) break
        if (`${artifact.name} ${artifact.path}`.toLowerCase().includes(query)) {
          artifacts.push({ path: artifact.path, name: artifact.name, kind: artifact.kind })
        }
      }

      return c.json({ sessions, messages, artifacts })
    },
  ),
)
