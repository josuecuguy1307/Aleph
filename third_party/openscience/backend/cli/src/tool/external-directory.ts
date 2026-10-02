import path from "path"
import type { Tool } from "./tool"
import { Instance } from "../project/instance"
import { Filesystem } from "../util/filesystem"
import { SessionFilesystem } from "../session/filesystem"

type Kind = "file" | "directory"

type Options = {
  bypass?: boolean
  kind?: Kind
  access?: SessionFilesystem.Access
}

export async function assertExternalDirectory(ctx: Tool.Context, target?: string, options?: Options) {
  if (!target) return

  const canonical = await Filesystem.canonical(target)
  if (!canonical) throw new SessionFilesystem.InvalidPathError({ path: path.resolve(target) })
  if (options?.bypass) return { path: canonical }

  const internal = await Instance.containsCanonicalPath(canonical)
  const access = options?.access ?? "read"

  if (!internal) {
    const kind = options?.kind ?? "file"
    const parentDir = kind === "directory" ? canonical : path.dirname(canonical)
    const glob = path.join(parentDir, "*")

    await ctx.ask({
      permission: "external_directory",
      patterns: [glob],
      always: [glob],
      metadata: {
        filepath: canonical,
        parentDir,
        filesystem: {
          path: parentDir,
          access,
        },
      },
    })
  }

  // Direct unit tests use a deliberately synthetic context. Production tool
  // contexts always carry a real session id and therefore fail closed here.
  if (!ctx.sessionID.startsWith("ses_")) return { path: canonical }
  return SessionFilesystem.authorize({
    sessionID: ctx.sessionID,
    path: canonical,
    access,
  })
}
