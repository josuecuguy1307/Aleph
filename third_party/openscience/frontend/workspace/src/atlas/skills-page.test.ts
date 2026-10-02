import { expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { installFromGit } from "./skills-settings"

const source = () => readFileSync(fileURLToPath(new URL("./SkillsPage.tsx", import.meta.url)), "utf8")

test("skills use a compact searchable list instead of a card dashboard", () => {
  const page = source()

  expect(page).toContain('class="skills-workspace"')
  expect(page).toContain('class="skills-workspace__header"')
  expect(page).toContain('class="skills-workspace__list"')
  expect(page).toContain('class="skills-workspace__row"')
  expect(page).not.toContain("SkillCard")
  expect(page).not.toContain('"grid-template-columns": "repeat(auto-fill')
})

test("global skill installation does not select a filesystem project", async () => {
  const calls: Array<{ url: URL; init?: RequestInit }> = []
  const fetchFn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: new URL(String(input)), init })
    return Response.json({ installed: [], rejected: [], warnings: [] })
  }) as typeof fetch

  await installFromGit(fetchFn, "http://127.0.0.1:4096/", "https://github.com/example/science-skills")

  expect(calls).toHaveLength(1)
  expect(calls[0]!.url.pathname).toBe("/settings/skills/install")
  expect([...calls[0]!.url.searchParams]).toEqual([])
  expect(calls[0]!.init?.method).toBe("POST")
  expect(JSON.parse(String(calls[0]!.init?.body))).toEqual({
    url: "https://github.com/example/science-skills",
  })
})
