import { describe, expect, mock, test } from "bun:test"

mock.module("../src/config", () => ({ OPENCODE_URL: "/opencode", INGEST_URL: "/ingest" }))
const { sendPrompt } = await import("../src/api/opencode")
import type { Client } from "../src/api/opencode"

describe("long document prompt admission", () => {
  test("does not await the long-running synchronous HTTP request", async () => {
    const calls: unknown[] = []
    const client = {
      session: {
        prompt: () => { throw new Error("Synchronous request would exceed HTTP idle timeout") },
        promptAsync: async (options: unknown) => {
          calls.push(options)
          return { response: new Response(null, { status: 204 }) }
        },
      },
    } as unknown as Client
    const result = await sendPrompt(client, "own-session", "drafter", "Complete long fictional document")
    expect(result.response.status).toBe(204)
    expect(calls).toEqual([{
      path: { id: "own-session" },
      body: { agent: "drafter", parts: [{ type: "text", text: "Complete long fictional document" }] },
      throwOnError: true,
    }])
  })

  test("surfaces admission rejection instead of treating it as a running turn", async () => {
    const client = { session: { promptAsync: async () => { throw new Error("HTTP 404 session missing") } } } as unknown as Client
    await expect(sendPrompt(client, "missing-session", "drafter", "Draft")).rejects.toThrow("HTTP 404 session missing")
  })
})
