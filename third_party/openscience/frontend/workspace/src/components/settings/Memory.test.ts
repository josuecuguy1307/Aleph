import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { searchEndpoint, usage } from "./Memory"

const source = readFileSync(fileURLToPath(new URL("./Memory.tsx", import.meta.url)), "utf8")

describe("memory settings panel", () => {
  test("searchEndpoint targets the memory search route with query and directory", () => {
    const endpoint = new URL(searchEndpoint("http://127.0.0.1:4096", "dark plots", "L2hvbWU"))
    expect(endpoint.pathname).toBe("/settings/memory/search")
    expect(endpoint.searchParams.get("q")).toBe("dark plots")
    expect(endpoint.searchParams.get("directory")).toBe("L2hvbWU")
  })

  test("usage is a clamped percentage of the backend capacity", () => {
    expect(usage(undefined)).toBe(0)
    expect(usage({ used: 0, max: 2000, gauge: "" })).toBe(0)
    expect(usage({ used: 500, max: 2000, gauge: "" })).toBe(25)
    expect(usage({ used: 9999, max: 2000, gauge: "" })).toBe(100)
  })

  test("search is labeled full-text and never claims to be semantic", () => {
    expect(source).toContain("Full-text keyword search")
    expect(source).not.toMatch(/semantic/i)
  })

  test("the capacity gauge renders the backend value", () => {
    expect(source).toContain("doc().capacity")
    expect(source).toContain("characters used")
  })

  test("agent-written notes carry a visible badge", () => {
    expect(source).toContain('note.source === "agent"')
    expect(source).toContain("Saved by the agent via the memory tool")
  })

  test("search results come from the real backend route", () => {
    expect(source).toContain("searchEndpoint(sdk.url")
  })
})
