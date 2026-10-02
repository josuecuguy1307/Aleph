import { AsyncLocalStorage } from 'node:async_hooks';

interface RunStore {
  runId: string;
}

const storage = new AsyncLocalStorage<RunStore>();

export function withRun<T>(runId: string, fn: () => Promise<T> | T): Promise<T> | T {
  return storage.run({ runId }, fn);
}

export function currentRunId(): string | undefined {
  return storage.getStore()?.runId;
}
