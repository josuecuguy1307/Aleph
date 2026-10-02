import { expect, test } from "bun:test"
import { splitSessionHistory, turnInFlight } from "../src/api/session-recovery"

test("reopening during a completed tool step retains old history and resumes the current turn", () => {
  const oldUser = { info: { role: "user" } }
  const oldAnswer = { info: { role: "assistant", time: { completed: 1 }, finish: "stop" } }
  const currentUser = { info: { role: "user" } }
  const tool = { info: { role: "assistant", time: { completed: 2 }, finish: "tool-calls" } }
  const active = turnInFlight(tool.info, { type: "busy" })
  expect(active).toBe(true)
  expect(splitSessionHistory([oldUser, oldAnswer, currentUser, tool], active)).toEqual({
    settled: [oldUser, oldAnswer, currentUser], live: [tool],
  })
})

test("final response and incomplete response recover distinct states without resubmitting", () => {
  const user = { info: { role: "user" } }
  const final = { info: { role: "assistant", time: { completed: 3 }, finish: "stop" } }
  expect(turnInFlight(final.info, undefined)).toBe(false)
  expect(splitSessionHistory([user, final], false)).toEqual({ settled: [user, final], live: [] })
  expect(turnInFlight({ role: "assistant", time: {} }, undefined)).toBe(true)
  expect(turnInFlight(final.info, { type: "retry" })).toBe(true)
  expect(turnInFlight({ role: "assistant", error: { message: "Rejected" } }, undefined)).toBe(false)
})
