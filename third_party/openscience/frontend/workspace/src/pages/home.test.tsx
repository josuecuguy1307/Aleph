import { afterAll, afterEach, describe, expect, test } from "bun:test"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import type { JSX } from "solid-js"

const file = fileURLToPath(new URL("./home-launcher.tsx", import.meta.url))
const cleanups: Array<() => void> = []
const server = fileURLToPath(import.meta.resolve("solid-js/web"))
const browser = server.replace(/server\.js$/, "web.js")
const hyper = fileURLToPath(import.meta.resolve("solid-js/h"))
const source = (await Bun.file(hyper).text()).replace("from 'solid-js/web';", `from '${pathToFileURL(browser).href}';`)
const temp = await mkdtemp(join(tmpdir(), "openscience-solid-h-"))
const module = join(temp, "h.mjs")
await Bun.write(module, source)
const h = (await import(pathToFileURL(module).href)).default
const render = (await import(browser)).render
Object.assign(globalThis, { React: { createElement: h, Fragment: h.Fragment } })

afterAll(() => rm(temp, { recursive: true, force: true }))

afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup())
  document.body.replaceChildren()
})

const load = async () => {
  const exists = await Bun.file(file).exists()
  expect(exists).toBe(true)
  if (!exists) return
  return import("./home-launcher")
}

const mount = (view: () => JSX.Element) => {
  const host = document.createElement("div")
  document.body.append(host)
  cleanups.push(render(view, host))
  return host
}

const props = {
  projects: [],
  query: "",
  home: "/Users/aayam",
  onQuery: (_value: string) => {},
  onOpen: (_project: { id: string }) => {},
  onCreate: (_event?: Event) => {},
  onImport: (_event?: Event) => {},
  onRetry: (_event?: Event) => {},
}

describe("HomeLauncher", () => {
  test("announces loading and exposes retry when the local server fails", async () => {
    const subject = await load()
    if (!subject) return

    const loading = mount(() => <subject.HomeLauncher {...props} state="loading" />)
    expect(loading.querySelector('[role="status"]')?.textContent).toContain("Loading")

    const retries: string[] = []
    const error = mount(() => (
      <subject.HomeLauncher {...props} state="error" onRetry={(_event?: Event) => retries.push("retry")} />
    ))
    expect(error.querySelector('[role="alert"]')?.textContent).toContain("couldn’t reach")
    const retry = Array.from(error.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Try again"),
    )
    retry?.click()
    expect(retries).toEqual(["retry"])
  })

  test("makes project creation primary while preserving folder import", async () => {
    const subject = await load()
    if (!subject) return

    const actions: string[] = []
    const host = mount(() => (
      <subject.HomeLauncher
        {...props}
        state="empty"
        onCreate={(_event?: Event) => actions.push("create")}
        onImport={(_event?: Event) => actions.push("import")}
      />
    ))
    const create = Array.from(host.querySelectorAll("button")).find((item) =>
      item.textContent?.includes("Create project"),
    )
    const importFolder = Array.from(host.querySelectorAll("button")).find((item) =>
      item.textContent?.includes("Import existing folder"),
    )

    create?.click()
    importFolder?.click()
    expect(actions).toEqual(["create", "import"])
  })

  test("renders recent projects as native buttons and opens the selected project ID", async () => {
    const subject = await load()
    if (!subject) return

    const opened: string[] = []
    const host = mount(() => (
      <subject.HomeLauncher
        {...props}
        state="recent"
        projects={[
          {
            id: "prj_atlas",
            name: "Atlas",
            worktree: "/Users/aayam/Research/atlas",
            time: { created: 10 },
            updatedAt: 10,
            pinned: false,
          },
        ]}
        onOpen={(project) => opened.push(project.id)}
      />
    ))
    const row = host.querySelector<HTMLButtonElement>('[data-project="prj_atlas"]')

    expect(row?.tagName).toBe("BUTTON")
    expect(row?.tabIndex).toBe(0)
    row?.click()
    expect(host.textContent).not.toContain("/Users/aayam")
    expect(opened).toEqual(["prj_atlas"])
  })

  test("makes no-results recovery explicit and clears search with Escape", async () => {
    const subject = await load()
    if (!subject) return

    const queries: string[] = []
    const creations: string[] = []
    const host = mount(() => (
      <subject.HomeLauncher
        {...props}
        state="recent"
        query="missing"
        onQuery={(query) => queries.push(query)}
        onCreate={(_event?: Event) => creations.push("create")}
      />
    ))
    const input = host.querySelector<HTMLInputElement>('input[type="search"]')
    input?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    const clear = Array.from(host.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Clear search"),
    )
    const create = Array.from(host.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Create project"),
    )
    clear?.click()
    create?.click()

    expect(queries).toEqual(["", ""])
    expect(creations).toEqual(["create"])
  })
})
