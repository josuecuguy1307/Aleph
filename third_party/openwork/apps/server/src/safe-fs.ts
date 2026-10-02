/** Descriptor-relative macOS workspace I/O. Absence of the signed native addon
 * is a hard failure; there is deliberately no pathname-based fallback. */
import { closeSync, createReadStream as nodeStream, fstatSync, readFileSync, readSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

type Native = {
  openFile(root: string, rel: string): number;
  pathKind(root: string, rel: string): "missing" | "regular" | "directory" | "symlink" | "other";
  openDirectory(root: string, rel: string): number;
  list(root: string, rel: string): Array<{ name: string; directory: boolean }>;
  mkdir(root: string, rel: string): void;
  writeFile(root: string, rel: string, data: Buffer): number;
  createFile(root: string, rel: string, data: Buffer): void;
  appendFile(root: string, rel: string, data: Buffer): void;
  rename(root: string, from: string, to: string): void;
  remove(root: string, rel: string, recursive: boolean): void;
};
let native: Native | undefined;
function addon(): Native {
  if (process.platform !== "darwin") throw new Error("safe filesystem requires macOS native boundary");
  // Bun's single-file compiler embeds only a direct static .node require.
  if (!native) native = require("./safe-fs-darwin.node") as Native;
  return native;
}

const roots = new Set<string>();
export function registerWorkspaceRoot(root: string): void {
  if (!isAbsolute(root)) throw new Error("workspace root must be absolute");
  roots.add(resolve(root));
  // Native traversal checks every component; registration alone is not trust.
  try { addon().list(resolve(root), "."); }
  catch (error) { roots.delete(resolve(root)); throw error; }
}

function locate(path: string): { root: string; rel: string } {
  const absolute = resolve(path);
  const candidates = [...roots].filter((root) => absolute === root || absolute.startsWith(root + sep));
  candidates.sort((a, b) => b.length - a.length);
  const root = candidates[0];
  if (!root) throw new Error("unregistered workspace path");
  const rel = relative(root, absolute);
  if (rel === ".." || rel.startsWith(".." + sep) || isAbsolute(rel)) throw new Error("path escapes workspace");
  return { root, rel: rel || "." };
}

function anchorAbsolute(path: string): { root: string; rel: string } {
  if (!isAbsolute(path)) throw new Error("absolute safe path required");
  const absolute = resolve(path);
  let parent = dirname(absolute);
  while (parent !== dirname(parent)) {
    try {
      const fd = addon().openDirectory(parent, ".");
      closeSync(fd);
      return { root: parent, rel: relative(parent, absolute) };
    } catch {
      // A nonexistent ancestor may be created descriptor-relative by the
      // native operation. A symlink ancestor remains rejected during traversal.
      parent = dirname(parent);
    }
  }
  throw new Error("no safe filesystem anchor");
}

/** For explicitly authorized config/workspace paths outside a registered file root. */
export async function safeReadAbsoluteFile(path: string, encoding: BufferEncoding = "utf8"): Promise<string> {
  const fd = safeOpenAbsoluteFile(path);
  try { return readFileSync(fd, { encoding }); }
  finally { closeSync(fd); }
}

export async function safeReadAbsoluteBuffer(path: string): Promise<Buffer> {
  const fd = safeOpenAbsoluteFile(path);
  try { return readFileSync(fd); }
  finally { closeSync(fd); }
}

/** Open and bound the bytes through one no-follow descriptor, including files
 * that grow after fstat. Never re-open a previously checked pathname. */
export async function safeReadAbsoluteBoundedBuffer(path: string, maxBytes: number): Promise<Buffer> {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 0) throw new RangeError("invalid read limit");
  const fd = safeOpenAbsoluteFile(path);
  try {
    const info = fstatSync(fd);
    if (!info.isFile()) throw new Error("not a regular file");
    if (info.size > maxBytes) throw new Error("file exceeds read limit");
    const chunks: Buffer[] = [];
    let total = 0;
    while (true) {
      const chunk = Buffer.allocUnsafe(Math.min(64 * 1024, maxBytes - total + 1));
      const read = readSync(fd, chunk, 0, chunk.length, null);
      if (read === 0) return Buffer.concat(chunks, total);
      total += read;
      if (total > maxBytes) throw new Error("file exceeds read limit");
      chunks.push(chunk.subarray(0, read));
    }
  } finally { closeSync(fd); }
}

export function safeOpenAbsoluteFile(path: string): number {
  const { root, rel } = anchorAbsolute(path);
  return addon().openFile(root, rel);
}

export function safePathKindAbsolute(path: string) {
  const { root, rel } = anchorAbsolute(path);
  return addon().pathKind(root, rel);
}

export async function safeWriteAbsoluteFile(path: string, content: string | Buffer): Promise<void> {
  const { root, rel } = anchorAbsolute(path);
  addon().writeFile(root, rel, Buffer.isBuffer(content) ? content : Buffer.from(content));
}

export async function safeCreateAbsoluteFile(path: string, content: string | Buffer): Promise<void> {
  const { root, rel } = anchorAbsolute(path);
  addon().createFile(root, rel, Buffer.isBuffer(content) ? content : Buffer.from(content));
}

export async function safeAppendAbsoluteFile(path: string, content: string | Buffer): Promise<void> {
  const { root, rel } = anchorAbsolute(path);
  addon().appendFile(root, rel, Buffer.isBuffer(content) ? content : Buffer.from(content));
}

export async function safeEnsureAbsoluteDir(path: string): Promise<void> {
  const { root, rel } = anchorAbsolute(path);
  if (rel !== ".") addon().mkdir(root, rel);
}

export async function safeRemoveAbsoluteFile(path: string): Promise<void> {
  const { root, rel } = anchorAbsolute(path);
  if (addon().pathKind(root, rel) === "missing") return;
  addon().remove(root, rel, false);
}

export async function safeExistsAbsolute(path: string): Promise<boolean> {
  try {
    const { root, rel } = anchorAbsolute(path);
    let fd: number;
    try { fd = addon().openFile(root, rel); }
    catch { fd = addon().openDirectory(root, rel); }
    closeSync(fd);
    return true;
  } catch { return false; }
}

export async function safeStatAbsolute(path: string) {
  const { root, rel } = anchorAbsolute(path);
  let fd: number;
  try { fd = addon().openFile(root, rel); }
  catch { fd = addon().openDirectory(root, rel); }
  try { return fstatSync(fd); }
  finally { closeSync(fd); }
}

export async function safeListAbsolute(path: string) {
  const { root, rel } = anchorAbsolute(path);
  return addon().list(root, rel).map((item) => ({
    name: item.name, isDirectory: () => item.directory, isFile: () => !item.directory,
  }));
}

export async function safeStat(path: string) {
  const { root, rel } = locate(path);
  let fd: number;
  try { fd = addon().openFile(root, rel); }
  catch { fd = addon().openDirectory(root, rel); }
  try { return fstatSync(fd); }
  finally { closeSync(fd); }
}

export async function safeExists(path: string): Promise<boolean> {
  try { await safeStat(path); return true; }
  catch { return false; }
}

export function safeReadFile(path: string): Promise<Buffer>;
export function safeReadFile(path: string, encoding: BufferEncoding): Promise<string>;
export async function safeReadFile(path: string, encoding?: BufferEncoding): Promise<Buffer | string> {
  const { root, rel } = locate(path);
  const fd = addon().openFile(root, rel);
  try { return readFileSync(fd, encoding ? { encoding } : undefined); }
  finally { closeSync(fd); }
}

export function safeCreateReadStream(path: string) {
  const { root, rel } = locate(path);
  const fd = addon().openFile(root, rel);
  return nodeStream("", { fd, autoClose: true });
}

export async function safeWriteFile(path: string, data: Buffer | string,
                                    options?: { flag?: string; encoding?: BufferEncoding }): Promise<void> {
  const { root, rel } = locate(path);
  if (rel === "." || (options?.flag && options.flag !== "wx")) throw new Error("invalid safe write");
  addon().writeFile(root, rel, Buffer.isBuffer(data) ? data : Buffer.from(data, options?.encoding || "utf8"));
}

export async function safeEnsureDir(path: string): Promise<void> {
  const { root, rel } = locate(path);
  if (rel !== ".") addon().mkdir(root, rel);
}

export async function safeRename(from: string, to: string): Promise<void> {
  const a = locate(from), b = locate(to);
  if (a.root !== b.root || a.rel === "." || b.rel === ".") throw new Error("cross-root rename rejected");
  addon().rename(a.root, a.rel, b.rel);
}

export async function safeRm(path: string, options?: { recursive?: boolean; force?: boolean }): Promise<void> {
  const { root, rel } = locate(path);
  if (rel === ".") throw new Error("workspace root deletion rejected");
  addon().remove(root, rel, options?.recursive === true);
}

export async function safeReaddir(path: string, _options?: { withFileTypes?: boolean }) {
  const { root, rel } = locate(path);
  return addon().list(root, rel).map((item) => ({
    name: item.name, isDirectory: () => item.directory, isFile: () => !item.directory,
  }));
}
