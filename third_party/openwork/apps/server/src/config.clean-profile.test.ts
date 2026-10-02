import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveServerConfig } from "./config.js";

const roots: string[] = [];
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

test("clean-profile explicit server.json is the sole token source", async () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "openwork-clean-")));
  roots.push(root);
  const configPath = join(root, "server.json");
  writeFileSync(configPath, JSON.stringify({
    host: "127.0.0.1", port: 0,
    token: "first-launch-client-capability",
    hostToken: "first-launch-host-capability",
    workspaces: [{ path: root }],
  }));
  const cli = { configPath, workspaces: [] };
  const first = await resolveServerConfig(cli);
  expect(first.token).toBe("first-launch-client-capability");
  expect(first.hostToken).toBe("first-launch-host-capability");

  writeFileSync(configPath, JSON.stringify({
    host: "127.0.0.1", port: 0,
    token: "relaunch-client-capability",
    hostToken: "relaunch-host-capability",
    workspaces: [{ path: root }],
  }));
  const second = await resolveServerConfig(cli);
  expect(second.token).toBe("relaunch-client-capability");
  expect(second.hostToken).toBe("relaunch-host-capability");
});

test("explicit unreadable config fails closed instead of generating mismatched tokens", async () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "openwork-clean-")));
  roots.push(root);
  const configPath = join(root, "server.json");
  await expect(resolveServerConfig({ configPath, workspaces: [] })).rejects.toThrow();
  writeFileSync(configPath, "{bad-json");
  await expect(resolveServerConfig({ configPath, workspaces: [] })).rejects.toThrow();
  writeFileSync(configPath, JSON.stringify({ token: "only-client-token", workspaces: [] }));
  await expect(resolveServerConfig({ configPath, workspaces: [] })).rejects.toThrow();
});

test("explicit file rejects a stale token inherited through the environment", async () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "openwork-clean-")));
  roots.push(root);
  const configPath = join(root, "server.json");
  writeFileSync(configPath, JSON.stringify({
    token: "fresh-client-capability", hostToken: "fresh-host-capability", workspaces: [],
  }));
  const previous = process.env.OPENWORK_HOST_TOKEN;
  process.env.OPENWORK_HOST_TOKEN = "stale-host-capability";
  try {
    await expect(resolveServerConfig({ configPath, workspaces: [] })).rejects.toThrow(
      "cannot be combined with token overrides",
    );
  } finally {
    if (previous === undefined) delete process.env.OPENWORK_HOST_TOKEN;
    else process.env.OPENWORK_HOST_TOKEN = previous;
  }
});
