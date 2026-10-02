import { describe, expect, test } from "bun:test"
import { isNewerVersion } from "../../src/server/routes/settings/updates"

describe("update version ordering", () => {
  test("only reports a genuinely newer release", () => {
    expect(isNewerVersion("2.0.1", "2.0.2")).toBe(true)
    expect(isNewerVersion("2.0.2", "2.0.2")).toBe(false)
    expect(isNewerVersion("2.0.2-test.58.1", "2.0.1")).toBe(false)
    expect(isNewerVersion("local", "2.0.2")).toBe(false)
  })
})
