import { once } from 'node:events';
import { mkdtemp, writeFile, symlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ipcMain } from './electron-runtime';
import { createHeadlessWindow, installHeadlessIpcCapture, startHeadlessBridge } from './headless-bridge';
import { invokeHttpIpc } from '../renderer/src/http-ipc';

vi.mock('./electron-runtime', () => ({ ipcMain: { handle: vi.fn() } }));
afterEach(() => vi.unstubAllGlobals());

it('serves real workspace binary bytes over HTTP and preserves path boundaries', async () => {
  const root = await mkdtemp(join(tmpdir(), 'aleph-http-workspace-'));
  const bytes = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j7xkAAAAASUVORK5CYII=', 'base64');
  await writeFile(join(root, 'figura.png'), bytes);
  await symlink(join(root, 'figura.png'), join(root, 'linked.png'));
  const server = startHeadlessBridge({ port: 0, rendererRoot: '.',
    webContents: createHeadlessWindow().webContents,
    resolveWorkspacePath: (id) => id === 'own-design' ? root : null });
  await once(server, 'listening');
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Missing test port');
  const base = `http://127.0.0.1:${address.port}/.aleph/workspace/`;
  try {
    const response = await fetch(base + 'own-design/figura.png');
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toBe('image/png');
    expect(Buffer.from(await response.arrayBuffer())).toEqual(bytes);
    expect((await fetch(base + 'unknown/figura.png')).status).toBe(404);
    expect((await fetch(base + 'own-design/linked.png')).status).toBe(403);
    expect((await fetch(base + 'own-design/%2e%2e%2ffigura.png')).status).toBe(403);
  } finally {
    server.close();
    await once(server, 'close');
    await rm(root, { recursive: true, force: true });
  }
});

describe('headless long operation transport', () => {
  it('admits once, remains pending, and returns the complete result over real HTTP', async () => {
    installHeadlessIpcCapture();
    let finish: (value: unknown) => void = () => {};
    let calls = 0;
    ipcMain.handle('codesign:v1:generate', () => {
      calls++;
      return new Promise((resolve) => { finish = resolve; });
    });
    const server = startHeadlessBridge({ port: 0, rendererRoot: '.', webContents: createHeadlessWindow().webContents });
    await once(server, 'listening');
    const address = server.address();
    if (!address || typeof address === 'string') throw new Error('Missing test port');
    const base = `http://127.0.0.1:${address.port}`;
    const realFetch = globalThis.fetch;
    vi.stubGlobal('fetch', (input: string, init?: RequestInit) => realFetch(`${base}${input}`, init));
    try {
      const admitted = await fetch('/.aleph/ipc/codesign%3Av1%3Agenerate', {
        method: 'POST', body: JSON.stringify({ args: [{ prompt: 'long report' }] }),
      });
      expect(admitted.status).toBe(202);
      const job = await admitted.json() as { jobId: string };
      expect((await fetch(`/.aleph/jobs/${job.jobId}`)).status).toBe(202);
      finish({ source: 'Informe completo · estación y precipitación', bytes: 12000 });
      const completed = await fetch(`/.aleph/jobs/${job.jobId}`);
      expect(await completed.json()).toEqual({ ok: true, value: { source: 'Informe completo · estación y precipitación', bytes: 12000 } });
      expect(calls).toBe(1);
      expect((await fetch('/.aleph/jobs/not-a-job')).status).toBe(404);

      ipcMain.handle('codesign:export', () => new Promise((resolve) => setTimeout(() => resolve('render complete'), 1200)));
      expect(await invokeHttpIpc('codesign:export', [])).toBe('render complete');
      ipcMain.handle('done:verify:v1', () => { throw new Error('Concrete local failure'); });
      await expect(invokeHttpIpc('done:verify:v1', [])).rejects.toThrow('Concrete local failure');
      await expect(invokeHttpIpc('missing-channel', [])).rejects.toThrow('Canal no expuesto: missing-channel');
    } finally {
      server.close();
      await once(server, 'close');
    }
  }, 10000);
});
