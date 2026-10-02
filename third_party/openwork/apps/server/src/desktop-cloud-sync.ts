/** Local-only compatibility surface; no account, inventory, or network sync. */
export function normalizeResourceSnapshot(_input: unknown): null {
  return null;
}

export function readDesktopCloudSyncState(_input: unknown): { enabled: false } {
  return { enabled: false };
}

export function readWorkspaceCloudImports(_input: unknown): { providers: unknown[] } {
  return { providers: [] };
}

export function syncDesktopCloudResources(_input: unknown): { changes: unknown[]; state: { enabled: false } } {
  return { changes: [], state: { enabled: false } };
}
