import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, mkdir, readFile, realpath, rename, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const serverDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const addon = join(serverDir, "src/safe-fs-darwin.node");
const held = `${addon}.verification-held`;
const binary = join(serverDir, "dist/bin/openwork-server");
assert.ok(existsSync(binary) && existsSync(addon) && !existsSync(held));
const fixture = await realpath(await mkdtemp(join(tmpdir(), "aleph-compiled-fs-")));
const root = join(fixture, "workspace");
let child;
let hidden = false;
try {
  await mkdir(root);
  await writeFile(join(root, "inside.txt"), "BUNDLED_NATIVE_BOUNDARY");
  const configPath = join(fixture, "server.json");
  await writeFile(configPath, JSON.stringify({
    token: "synthetic-client-token",
    hostToken: "synthetic-host-token",
    workspaces: [{ id: "ws_test", path: root }],
    authorizedRoots: [root],
  }));
  const port = await new Promise((done, reject) => {
    const socket = net.createServer();
    socket.once("error", reject);
    socket.listen(0, "127.0.0.1", () => {
      const chosen = socket.address().port;
      socket.close(() => done(chosen));
    });
  });
  // If the compiled executable still reaches into the source checkout for the
  // native addon, this request fails. The restore is unconditional below.
  await rename(addon, held);
  hidden = true;
  child = spawn(binary, ["--config", configPath, "--host", "127.0.0.1", "--port", String(port),
                         "--read-only", "--no-log-requests"],
                { cwd: fixture, stdio: ["ignore", "pipe", "pipe"], detached: true });
  let diagnostics = "";
  child.stdout.on("data", (chunk) => { diagnostics = (diagnostics + chunk).slice(-3000); });
  child.stderr.on("data", (chunk) => { diagnostics = (diagnostics + chunk).slice(-3000); });
  let response;
  for (let attempt = 0; attempt < 50; attempt++) {
    try {
      response = await fetch(`http://127.0.0.1:${port}/workspace/ws_test/files/content?path=inside.txt`,
                             { headers: { Authorization: "Bearer synthetic-client-token" } });
      break;
    } catch { await new Promise((done) => setTimeout(done, 100)); }
  }
  assert.ok(response, "compiled server failed to start");
  if (response.status !== 200) {
    throw new Error(`compiled native route status ${response.status}: ${await response.text()} ${diagnostics}`);
  }
  const result = await response.json();
  assert.equal(result.content, "BUNDLED_NATIVE_BOUNDARY");
  assert.equal(await readFile(join(root, "inside.txt"), "utf8"), "BUNDLED_NATIVE_BOUNDARY");
  console.log("PASS compiled OpenWork server contains and invokes native safe-fs without source addon");
} finally {
  if (child?.pid) {
    try { process.kill(-child.pid, "SIGTERM"); } catch {}
    await new Promise((done) => setTimeout(done, 100));
  }
  if (hidden) await rename(held, addon);
  await rm(fixture, { recursive: true, force: true });
}
