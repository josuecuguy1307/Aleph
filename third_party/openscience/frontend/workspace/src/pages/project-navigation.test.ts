import { describe, expect, test } from "bun:test"

const read = (path: string) => Bun.file(new URL(path, import.meta.url)).text()

describe("project-ID navigation wiring", () => {
  test("configures the project SDK with the opaque capability", async () => {
    const [layout, sdk, global, request] = await Promise.all([
      read("./directory-layout.tsx"),
      read("../context/sdk.tsx"),
      read("../context/global-sync.tsx"),
      read("../utils/openscience-fetch.ts"),
    ])

    expect(layout).toContain("<SDKProvider directory={directory()} projectID={projectID()} scope={scope()}>")
    expect(layout).toContain("global.project.resolveID(projectID)")
    expect(sdk).toContain("projectID: projectID()")
    expect(sdk).toContain("createProjectRequest")
    expect(global).toContain('sdkFor("", projectID).project.current()')
    expect(request).toContain('headers.set("x-openscience-project"')
    expect(request).toContain('headers.set("x-openscience-directory"')
  })

  test("initializes the global model catalog without requiring a project SDK provider", async () => {
    const [providers, directory] = await Promise.all([read("../hooks/use-providers.ts"), read("../utils/base64.ts")])

    expect(providers).not.toContain("useSDK")
    expect(providers).toContain("if (!directory) return globalSync.data.provider")
    expect(providers).toContain("globalSync.child(directory, { projectID: currentProjectID() })")
    expect(directory).toContain("export function currentProjectID()")
    expect(directory).toContain("setActive({ directory, projectID })")
  })

  test("uses project scope for session tabs, drafts, context, and file-view caches", async () => {
    const [session, prompt, comments, file, terminal] = await Promise.all([
      read("./session.tsx"),
      read("../context/prompt.tsx"),
      read("../context/comments.tsx"),
      read("../context/file.tsx"),
      read("../context/terminal.tsx"),
    ])

    expect(session).toContain("sessionTabs.activateProject(project)")
    expect(session).toContain("() => [sdk.scope, params.id] as const")
    expect(prompt).toContain("load(sdk.scope, params.id)")
    expect(comments).toContain("load(sdk.scope, params.id)")
    expect(file).toContain("loadView(storage(), params.id)")
    expect(terminal).toContain("load(sdk.scope, params.id)")
    expect(terminal).toContain("sdk.client.pty")
    expect(await read("../components/terminal.tsx")).toContain("sdk.request.url(`/pty/${local.pty.id}/connect`)")
  })

  test("does not create new base64-directory navigation links", async () => {
    const [home, palette, prompt, notification] = await Promise.all([
      read("./home.tsx"),
      read("../atlas/CommandPalette.tsx"),
      read("../components/prompt-input.tsx"),
      read("../context/notification.tsx"),
    ])

    for (const source of [home, palette, prompt, notification]) {
      expect(source).not.toContain("base64Encode(directory)")
    }
  })

  test("keeps linked-worktree sessions and file surfaces on the selected directory", async () => {
    const [explorer, tree, preview] = await Promise.all([
      read("../atlas/FileExplorer.tsx"),
      read("../atlas/OpenScienceFileTree.tsx"),
      read("../atlas/FilePreview.tsx"),
    ])

    expect(explorer).toContain(
      'const projectRoot = () => sdk.directory || sync.data.path.directory || sync.project?.worktree || ""',
    )
    expect(tree).toContain(
      'const directory = () => sdk.directory || sync.data.path.directory || sync.project?.worktree || ""',
    )
    expect(preview).toContain(
      'props.directory || sdk.directory || sync.data.path.directory || sync.project?.worktree || ""',
    )
  })
})
