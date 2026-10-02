import { expect, test } from "bun:test"
import type { MessageV2 } from "../../src/session/message-v2"
import { SearchDedupe } from "../../src/session/search-dedupe"

const part: MessageV2.ToolPart = {
  id: "part_search",
  sessionID: "ses_search",
  messageID: "msg_search",
  type: "tool",
  callID: "call_search",
  tool: "websearch",
  state: {
    status: "completed",
    input: { numResults: 4, query: "protein folding" },
    output: "grounded results",
    title: "Web search",
    metadata: {},
    time: { start: 100, end: 150 },
  },
}

const message: MessageV2.WithParts = {
  info: {
    id: "msg_search",
    sessionID: "ses_search",
    role: "assistant",
    time: { created: 90, completed: 160 },
    parentID: "msg_user",
    modelID: "model",
    providerID: "provider",
    mode: "research",
    agent: "research",
    path: { cwd: "/tmp", root: "/tmp" },
    cost: 0,
    tokens: { input: 0, output: 0, reasoning: 0, cache: { read: 0, write: 0 } },
  },
  parts: [part],
}

test("reuses one completed identical search and marks the new call as a dedupe hit", () => {
  expect(SearchDedupe.signature({ query: "x", top: 3 })).toBe(SearchDedupe.signature({ top: 3, query: "x" }))
  const hit = SearchDedupe.find([message], "websearch", { query: "protein folding", numResults: 4 })
  expect(hit?.id).toBe("part_search")
  expect(hit && SearchDedupe.reuse(hit)).toMatchObject({
    output: "grounded results",
    metadata: {
      dedupeHit: true,
      dedupeOf: {
        messageID: "msg_search",
        partID: "part_search",
        callID: "call_search",
      },
    },
  })
  expect(SearchDedupe.find([message], "websearch", { query: "different", numResults: 4 })).toBeUndefined()
  expect(SearchDedupe.find([message], "read", { filePath: "/tmp/file" })).toBeUndefined()
})
