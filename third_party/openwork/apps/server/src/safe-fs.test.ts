import { test, expect } from "bun:test";
import { mkdtemp, mkdir, readFile, realpath, rm, symlink, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveSafeChildPath } from "./routes/files.js";
import { safeReadFile, safeWriteFile, safeRename, safeRm, safeEnsureDir,
  safeReaddir, safeCreateReadStream } from "./safe-fs.js";

test("workspace file paths are reopened descriptor-relative after approval", async () => {
  const fixture = await realpath(await mkdtemp(join(tmpdir(), "aleph-fs-boundary-")));
  const workspace = join(fixture, "workspace");
  const outside = join(fixture, "outside.txt");
  try {
    await mkdir(join(workspace, "docs"), { recursive: true });
    await writeFile(outside, "SENTINEL");
    const label = await resolveSafeChildPath(workspace, "docs/a.txt");
    await safeWriteFile(label, Buffer.from("inside"));
    expect((await safeReadFile(label)).toString()).toBe("inside");
    expect((await safeReaddir(join(workspace, "docs"))).map((e) => e.name)).toContain("a.txt");
    const stream = safeCreateReadStream(label);
    let streamed = "";
    for await (const chunk of stream) streamed += chunk.toString();
    expect(streamed).toBe("inside");

    await safeRename(label, join(workspace, "docs", "moved.txt"));
    await safeRm(join(workspace, "docs", "moved.txt"));
    await symlink(outside, label);
    await expect(safeReadFile(label)).rejects.toThrow();
    await unlink(label);
    await rm(join(workspace, "docs"), { recursive: true });
    await symlink(fixture, join(workspace, "docs"));
    await expect(safeWriteFile(label, Buffer.from("ESCAPE"))).rejects.toThrow();
    await expect(safeEnsureDir(join(workspace, "docs", "new"))).rejects.toThrow();
    await expect(safeRm(join(workspace, "docs", "outside.txt"))).rejects.toThrow();
    expect(await readFile(outside, "utf8")).toBe("SENTINEL");
  } finally {
    await rm(fixture, { recursive: true, force: true });
  }
});
