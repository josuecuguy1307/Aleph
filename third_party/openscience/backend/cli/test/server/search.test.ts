import { expect, test } from "bun:test"
import { Instance } from "../../src/project/instance"
import { Session } from "../../src/session"
import { Storage } from "../../src/storage/storage"
import { SearchRoutes } from "../../src/server/routes/search"
import { tmpdir } from "../fixture/fixture"

test("search matches session titles, message text, and artifact files", async () => {
  await using tmp = await tmpdir({ git: true })
  await Instance.provide({
    directory: tmp.path,
    fn: async () => {
      const session = await Session.create({ title: "Dose response fits" })
      const messageID = "msg_search_test1"
      await Storage.write(["message", session.id, messageID], {
        id: messageID,
        role: "user",
        sessionID: session.id,
        agent: "research",
        time: { created: Date.now() },
      })
      await Storage.write(["part", messageID, "prt_search_test1"], {
        id: "prt_search_test1",
        messageID,
        sessionID: session.id,
        type: "text",
        text: "Fit a four-parameter logistic curve to the dose response plate data.",
      })
      await Bun.write(`${tmp.path}/results/dose_response.csv`, "dose,response\n1,2\n")

      const app = SearchRoutes()
      const response = await app.request("/?q=dose")
      const hits = (await response.json()) as Record<string, unknown[]>

      expect(hits.sessions).toContainEqual({ id: session.id, title: "Dose response fits" })
      expect(hits.messages?.[0]).toMatchObject({ sessionID: session.id, messageID, role: "user" })
      expect(String((hits.messages?.[0] as { snippet?: string })?.snippet)).toContain("dose response")
      expect(hits.artifacts).toContainEqual({
        path: "results/dose_response.csv",
        name: "dose_response.csv",
        kind: "dataset",
      })

      const missing = await app.request("/?q=zzznotfound")
      const empty = (await missing.json()) as Record<string, unknown[]>
      expect(empty.sessions).toHaveLength(0)
      expect(empty.messages).toHaveLength(0)
      expect(empty.artifacts).toHaveLength(0)

      await Session.remove(session.id)
    },
  })
})
