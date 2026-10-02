import { Hono } from "hono"
import { describeRoute, resolver } from "hono-openapi"
import z from "zod"
import { Installation } from "../../../installation"
import { lazy } from "../../../util/lazy"

const RELEASES = "https://github.com/synthetic-sciences/openscience/releases"
const RELEASES_API = "https://api.github.com/repos/synthetic-sciences/openscience/releases?per_page=20"

export function isNewerVersion(current: string, latest: string) {
  if (current === "local" || current === latest) return false
  try {
    return Bun.semver.order(current, latest) < 0
  } catch {
    return false
  }
}

const Result = z.object({
  current: z.string(),
  latest: z.string(),
  channel: z.string(),
  method: z.string(),
  updateAvailable: z.boolean(),
  releaseNotes: z.string().url(),
})

export const UpdatesSettingsRoutes = lazy(() =>
  new Hono()
    .get(
      "/",
      describeRoute({
        summary: "Check for an OpenScience update",
        operationId: "settings.updates.check",
        responses: {
          200: {
            description: "Current and latest package versions",
            content: { "application/json": { schema: resolver(Result) } },
          },
        },
      }),
      async (c) => {
        const method = await Installation.method()
        const latest = await Installation.latest(method)
        return c.json(
          Result.parse({
            current: Installation.VERSION,
            latest,
            channel: Installation.CHANNEL,
            method,
            updateAvailable: isNewerVersion(Installation.VERSION, latest),
            releaseNotes: RELEASES,
          }),
        )
      },
    )
    .get("/releases", async (c) => {
      const response = await fetch(RELEASES_API, {
        headers: {
          Accept: "application/vnd.github+json",
          "User-Agent": Installation.USER_AGENT,
        },
      })
      if (!response.ok) return c.json({ error: `Release history unavailable (${response.status})` }, 502)
      return c.json(await response.json())
    }),
)
