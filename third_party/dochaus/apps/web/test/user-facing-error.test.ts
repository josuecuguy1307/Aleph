import { expect, test } from "bun:test"
import { userFacingError } from "../src/api/user-facing-error"

test("unwraps a persisted Codex quota envelope without leaking JSON or routing fields", () => {
  const raw = JSON.stringify(`HTTP 429: ${JSON.stringify({ error: { message: "[Codex] You've hit your usage limit.", error_kind: "rate_limit", brain_provider: "codex_cli", turno_id: "internal-id" } })}`)
  const text = userFacingError(raw)
  expect(text).toContain("Codex alcanzó su límite de uso")
  expect(text).not.toMatch(/[{}]|error_kind|brain_provider|internal-id/)
})
test("preserves useful ordinary errors and extracts provider message", () => {
  expect(userFacingError("Draft failed: Tables cannot be inserted")).toBe("Draft failed: Tables cannot be inserted")
  expect(userFacingError('HTTP 400: {"error":{"message":"Input is too long"}}')).toBe("Input is too long")
  expect(userFacingError("Load failed")).toContain("comprobar el estado")
})
