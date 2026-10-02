import fs from "node:fs"
import type { ChildProcess } from "node:child_process"
import type { KernelProcess } from "./types"

const hooks = new Set<() => void>()
let hooked = false

function token(pid: number) {
  if (process.platform === "linux") {
    try {
      const stat = fs.readFileSync(`/proc/${pid}/stat`, "utf8")
      const fields = stat.slice(stat.lastIndexOf(")") + 2).split(" ")
      const start = fields[19]
      return start ? `linux:${start}` : undefined
    } catch {
      return
    }
  }
  if (process.platform !== "darwin") return
  const result = Bun.spawnSync(["ps", "-o", "lstart=", "-p", String(pid)], {
    stdout: "pipe",
    stderr: "ignore",
  })
  const start = result.success ? result.stdout.toString().trim() : ""
  return start ? `darwin:${start}` : undefined
}

export namespace KernelProcessIdentity {
  export function onExit(fn: () => void) {
    hooks.add(fn)
    if (hooked) return
    hooked = true
    process.on("exit", () => {
      for (const hook of hooks) hook()
    })
    process.on("SIGTERM", () => process.exit(128 + 15))
    process.on("SIGINT", () => process.exit(128 + 2))
  }

  export function capture(proc: ChildProcess): KernelProcess | undefined {
    if (!proc.pid) return
    return {
      pid: proc.pid,
      startedAt: Date.now(),
      token: token(proc.pid),
    }
  }

  export function matches(proc: ChildProcess, identity?: KernelProcess) {
    if (!identity || proc.pid !== identity.pid || proc.exitCode !== null) return false
    try {
      process.kill(identity.pid, 0)
    } catch {
      return false
    }
    if (!identity.token) return true
    return token(identity.pid) === identity.token
  }
}
