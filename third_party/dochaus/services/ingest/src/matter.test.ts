import { test, expect, afterAll } from "bun:test"
import { mkdtempSync, rmSync, existsSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

// Point WORKSPACE_ROOT at a throwaway dir before matter.ts captures it at module
// eval, so the CRUD tests never touch a real workspace. The import is dynamic for
// exactly this reason — a static import would hoist above the env assignment.
const root = mkdtempSync(path.join(tmpdir(), "dochaus-matter-"))
process.env.WORKSPACE_ROOT = root
const matter = await import("./matter")

afterAll(() => rmSync(root, { recursive: true, force: true }))

test("matterDir rejects path traversal and escaping ids", () => {
  // The fix for the traversal hole: ids arrive from a URL param, so anything that
  // could climb out of WORKSPACE_ROOT must throw before it reaches a filesystem path.
  for (const bad of ["..", "../evil", "a/b", "/etc/passwd", "foo/../bar", ".dochaus", "", "Foo", "a b"]) {
    expect(() => matter.matterDir(bad)).toThrow(/invalid matter id/)
  }
})

test("matterDir accepts the generated slug+uuid shape and stays under the root", () => {
  const id = "acme-merger-a1b2c3"
  expect(matter.matterDir(id)).toBe(path.join(root, id))
})

test("create, list, get, rename, delete round-trip", () => {
  const created = matter.createMatter("Acme / Merger 2026", "2026-0042", ["EW"])
  expect(created.id).toMatch(/^acme-merger-2026-[a-z0-9]{6}$/)
  expect(created.reference).toBe("2026-0042")
  expect(created.jurisdictions).toEqual(["EW"])
  expect(existsSync(path.join(root, created.id, "matter.json"))).toBe(true)

  expect(matter.listMatters().map((m) => m.id)).toContain(created.id)
  expect(matter.getMatter(created.id).title).toBe("Acme / Merger 2026")
  expect(matter.getMatter(created.id).jurisdictions).toEqual(["EW"])

  // Jurisdictions move on their own through the rename endpoint while title/ref hold.
  const renamed = matter.renameMatter(created.id, "Acme Acquisition", "2026-0099", ["US-NY", "EW"])
  expect(renamed.id).toBe(created.id) // id is stable across rename
  expect(renamed.title).toBe("Acme Acquisition")
  expect(matter.getMatter(created.id).reference).toBe("2026-0099")
  expect(matter.getMatter(created.id).jurisdictions).toEqual(["US-NY", "EW"])

  matter.deleteMatter(created.id)
  expect(existsSync(path.join(root, created.id))).toBe(false)
  expect(matter.listMatters().map((m) => m.id)).not.toContain(created.id)
})

test("listJurisdictions surfaces the bundled EW pack from the dochaus config layer", () => {
  const ew = matter.listJurisdictions().find((j) => j.code === "EW")
  expect(ew).toBeDefined()
  expect(ew!.name).toBe("England & Wales")
  expect(ew!.citationStyle).toBe("OSCOLA")
})
