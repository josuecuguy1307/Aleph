import { afterEach, describe, expect, test } from "bun:test";
import { mkdtemp, mkdir, realpath, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { resolveSafeChildPath } from "./routes/files.js";
import { safeReadFile } from "./safe-fs.js";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

describe("workspace path symlink boundary", () => {
  test("rejects symlinked files and directories but allows ordinary descendants", async () => {
    const workspace = await mkdtemp(join(tmpdir(), "openwork-workspace-"));
    const outside = await mkdtemp(join(tmpdir(), "openwork-outside-"));
    roots.push(workspace, outside);
    await mkdir(join(workspace, "safe"));
    await writeFile(join(workspace, "safe", "inside.txt"), "inside");
    await writeFile(join(outside, "secret.txt"), "secret");
    await symlink(outside, join(workspace, "linked-dir"), "dir");
    await symlink(join(outside, "secret.txt"), join(workspace, "linked-file"));
    const workspaceReal = await realpath(workspace);

    const linkedDir = await resolveSafeChildPath(workspaceReal, "linked-dir/secret.txt");
    const linkedFile = await resolveSafeChildPath(workspaceReal, "linked-file");
    await expect(safeReadFile(linkedDir, "utf8")).rejects.toThrow();
    await expect(safeReadFile(linkedFile, "utf8")).rejects.toThrow();
    await expect(resolveSafeChildPath(workspaceReal, "safe/inside.txt")).resolves.toBe(join(workspaceReal, "safe", "inside.txt"));
    await expect(safeReadFile(join(workspaceReal, "safe", "inside.txt"), "utf8")).resolves.toBe("inside");
    await expect(resolveSafeChildPath(workspaceReal, "safe/new.txt")).resolves.toBe(join(workspaceReal, "safe", "new.txt"));
  });
});
