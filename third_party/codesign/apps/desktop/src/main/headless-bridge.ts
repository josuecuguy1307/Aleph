import { createReadStream, statSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { extname, normalize, relative, resolve } from 'node:path';
import { ipcMain } from './electron-runtime';
import { resolveWorkspaceUrl, resolveWorkspaceSafePath } from './workspace-protocol';
import { assertWorkspacePathVisible } from './workspace-reader';

type IpcHandler = (event: { sender: HeadlessWebContents }, ...args: unknown[]) => unknown;
type EventListener = (channel: string, payload: unknown) => void;

const handlers = new Map<string, IpcHandler>();
const listeners = new Set<EventListener>();
let captureInstalled = false;

export interface HeadlessWebContents {
  send: (channel: string, payload: unknown) => void;
}

/** Records the existing IPC handlers instead of registering a renderer-only Electron endpoint. */
export function installHeadlessIpcCapture(): void {
  if (captureInstalled) return;
  captureInstalled = true;
  const mutableIpcMain = ipcMain as unknown as { handle: (channel: string, handler: IpcHandler) => void };
  mutableIpcMain.handle = (channel, handler) => {
    handlers.set(channel, handler);
  };
}

export function createHeadlessWindow(): {
  isDestroyed: () => boolean;
  webContents: HeadlessWebContents;
} {
  return {
    isDestroyed: () => false,
    webContents: {
      send(channel, payload) {
        for (const listener of listeners) listener(channel, payload);
      },
    },
  };
}

function json(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  response.end(JSON.stringify(body));
}

function mimeType(path: string): string {
  const types: Record<string, string> = {
    '.css': 'text/css; charset=utf-8',
    '.html': 'text/html; charset=utf-8',
    '.ico': 'image/x-icon',
    '.js': 'text/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2',
  };
  return types[extname(path)] ?? 'application/octet-stream';
}

async function bodyOf(request: IncomingMessage): Promise<unknown[]> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  const value = JSON.parse(Buffer.concat(chunks).toString('utf8')) as { args?: unknown[] };
  if (!Array.isArray(value.args)) throw new Error('El bridge HTTP requiere args[]');
  return value.args;
}

function serveStatic(response: ServerResponse, rendererRoot: string, pathname: string): void {
  const requested = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
  const candidate = resolve(rendererRoot, normalize(requested));
  if (relative(rendererRoot, candidate).startsWith('..')) {
    response.writeHead(403);
    response.end();
    return;
  }
  let file = candidate;
  try {
    if (!statSync(file).isFile()) throw new Error('not a file');
  } catch {
    file = resolve(rendererRoot, 'index.html');
  }
  response.writeHead(200, {
    'Content-Type': mimeType(file),
    'Cache-Control': file.endsWith('index.html') ? 'no-store' : 'public, max-age=31536000, immutable',
  });
  createReadStream(file).pipe(response);
}

/** Starts the loopback surface consumed by Aleph's existing workspace iframe. */
export function startHeadlessBridge(input: {
  port: number;
  rendererRoot: string;
  webContents: HeadlessWebContents;
  resolveWorkspacePath?: (designId: string) => string | null;
}): Server {
  const jobs = new Map<string, { result?: { ok: boolean; value?: unknown; error?: string }; expires: number }>();
  const longChannels = new Set(['codesign:v1:generate', 'codesign:apply-comment', 'codesign:export', 'done:verify:v1']);
  const server = createServer(async (request, response) => {
    const url = new URL(request.url ?? '/', 'http://127.0.0.1');
    if (request.method === 'GET' && url.pathname.startsWith('/.aleph/workspace/')) {
      const resolver = input.resolveWorkspacePath ?? (() => null);
      const resolved = resolveWorkspaceUrl(`workspace://${url.pathname.slice('/.aleph/workspace/'.length)}`, resolver);
      const safe = resolved.ok ? await resolveWorkspaceSafePath(resolved.value) : resolved;
      if (!safe.ok) {
        response.writeHead(safe.error === 'unknown_design' ? 404 : 403);
        response.end();
        return;
      }
      try {
        assertWorkspacePathVisible(safe.value.relPath);
        const fileStat = statSync(safe.value.absPath);
        if (!fileStat.isFile()) throw new Error('not a file');
        const size = fileStat.size;
        response.writeHead(200, { 'Content-Type': safe.value.mime,
          'Content-Length': size, 'Cache-Control': 'no-store',
          'X-Content-Type-Options': 'nosniff' });
        const stream = createReadStream(safe.value.absPath);
        stream.on('error', () => response.destroy());
        stream.pipe(response);
      } catch {
        response.writeHead(404);
        response.end();
      }
      return;
    }
    for (const [id, job] of jobs) {
      if (job.result && job.expires < Date.now()) jobs.delete(id);
    }
    if (request.method === 'GET' && url.pathname.startsWith('/.aleph/jobs/')) {
      const job = jobs.get(url.pathname.slice('/.aleph/jobs/'.length));
      if (!job) {
        json(response, 404, { ok: false, error: 'La operación local ya no está disponible.' });
        return;
      }
      json(response, job.result ? 200 : 202, job.result ?? { pending: true });
      return;
    }
    if (request.method === 'GET' && url.pathname === '/.aleph/health') {
      json(response, 200, { healthy: true, surface: 'webview' });
      return;
    }
    if (request.method === 'GET' && url.pathname === '/.aleph/events') {
      response.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      });
      const listener: EventListener = (channel, payload) => {
        response.write(`data: ${JSON.stringify({ channel, payload })}\n\n`);
      };
      listeners.add(listener);
      request.on('close', () => listeners.delete(listener));
      return;
    }
    if (request.method === 'POST' && url.pathname.startsWith('/.aleph/ipc/')) {
      const channel = decodeURIComponent(url.pathname.slice('/.aleph/ipc/'.length));
      const handler = handlers.get(channel);
      if (!handler) {
        json(response, 404, { ok: false, error: `Canal no expuesto: ${channel}` });
        return;
      }
      try {
        const args = await bodyOf(request);
        if (longChannels.has(channel)) {
          const id = randomUUID();
          const job: { result?: { ok: boolean; value?: unknown; error?: string }; expires: number } = {
            expires: Date.now() + 30 * 60 * 1000,
          };
          jobs.set(id, job);
          void Promise.resolve().then(() => handler({ sender: input.webContents }, ...args)).then(
            (value) => { job.result = { ok: true, value }; job.expires = Date.now() + 30 * 60 * 1000; },
            (error: unknown) => { job.result = { ok: false, error: error instanceof Error ? error.message : String(error) }; },
          );
          json(response, 202, { jobId: id });
          return;
        }
        const value = await handler({ sender: input.webContents }, ...args);
        json(response, 200, { ok: true, value });
      } catch (error) {
        json(response, 400, {
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
      }
      return;
    }
    if (request.method === 'GET' || request.method === 'HEAD') {
      serveStatic(response, input.rendererRoot, url.pathname);
      return;
    }
    response.writeHead(405);
    response.end();
  });
  server.listen(input.port, '127.0.0.1');
  return server;
}
