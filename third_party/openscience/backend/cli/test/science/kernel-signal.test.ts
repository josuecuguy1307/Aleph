import { expect, test } from "bun:test"
import path from "node:path"
import { pathToFileURL } from "node:url"

test("kernel cleanup handlers terminate the host process after SIGTERM", async () => {
  if (process.platform === "win32") return
  const module = pathToFileURL(path.resolve(import.meta.dir, "../../src/science/kernel/process.ts")).href
  const proc = Bun.spawn(
    [
      process.execPath,
      "-e",
      `const { KernelProcessIdentity } = await import(${JSON.stringify(module)}); KernelProcessIdentity.onExit(() => {}); console.log("ready"); await new Promise(() => {})`,
    ],
    {
      cwd: path.resolve(import.meta.dir, "../.."),
      stdout: "pipe",
      stderr: "pipe",
    },
  )
  const reader = proc.stdout.getReader()
  const chunk = await reader.read()
  reader.releaseLock()
  expect(new TextDecoder().decode(chunk.value).trim()).toBe("ready")

  proc.kill("SIGTERM")
  const code = await Promise.race([proc.exited, Bun.sleep(2_000).then(() => undefined)])
  if (code === undefined) {
    proc.kill("SIGKILL")
    await proc.exited
  }
  expect(code).toBe(143)
})
