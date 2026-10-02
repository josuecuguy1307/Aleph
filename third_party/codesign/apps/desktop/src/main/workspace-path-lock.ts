interface StableWorkspacePathLeaseState {
  count: number;
  waiters: Set<() => void>;
}

const workspaceRenameQueues = new Map<string, Promise<void>>();
const stableWorkspacePathLeases = new Map<string, StableWorkspacePathLeaseState>();

export async function waitForWorkspaceRename(designId: string): Promise<void> {
  await workspaceRenameQueues.get(designId);
}

function acquireStableWorkspacePath(designId: string): () => void {
  let state = stableWorkspacePathLeases.get(designId);
  if (state === undefined) {
    state = { count: 0, waiters: new Set() };
    stableWorkspacePathLeases.set(designId, state);
  }

  state.count += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const current = stableWorkspacePathLeases.get(designId);
    if (current === undefined) return;
    current.count -= 1;
    if (current.count > 0) return;

    stableWorkspacePathLeases.delete(designId);
    for (const resolve of current.waiters) resolve();
  };
}

async function waitForStableWorkspacePathLeases(designId: string): Promise<void> {
  const state = stableWorkspacePathLeases.get(designId);
  if (state === undefined || state.count === 0) return;
  await new Promise<void>((resolve) => {
    state.waiters.add(resolve);
  });
}

export async function withStableWorkspacePath<T>(
  designId: string,
  operation: () => Promise<T>,
): Promise<T> {
  await waitForWorkspaceRename(designId);
  const release = acquireStableWorkspacePath(designId);
  try {
    return await operation();
  } finally {
    release();
  }
}

export async function runWithWorkspaceRenameQueue<T>(
  designId: string,
  operation: () => Promise<T>,
): Promise<T> {
  const previous = workspaceRenameQueues.get(designId) ?? Promise.resolve();
  let release = (): void => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const queued = previous.catch(() => undefined).then(() => gate);
  workspaceRenameQueues.set(designId, queued);

  await previous.catch(() => undefined);
  try {
    await waitForStableWorkspacePathLeases(designId);
    return await operation();
  } finally {
    release();
    if (workspaceRenameQueues.get(designId) === queued) {
      workspaceRenameQueues.delete(designId);
    }
  }
}
