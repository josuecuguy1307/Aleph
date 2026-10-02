import { describe, expect, it } from 'vitest';
import { currentRunId, withRun } from './runContext';

describe('runContext', () => {
  it('returns undefined outside a run', () => {
    expect(currentRunId()).toBeUndefined();
  });

  it('binds runId within the withRun scope (sync callback)', async () => {
    const result = await withRun('run-sync', () => currentRunId());
    expect(result).toBe('run-sync');
    expect(currentRunId()).toBeUndefined();
  });

  it('binds runId across awaits within an async callback', async () => {
    await withRun('run-async', async () => {
      expect(currentRunId()).toBe('run-async');
      await Promise.resolve();
      expect(currentRunId()).toBe('run-async');
      await new Promise((r) => setTimeout(r, 1));
      expect(currentRunId()).toBe('run-async');
    });
    expect(currentRunId()).toBeUndefined();
  });

  it('isolates concurrent runs', async () => {
    const seen: string[] = [];
    await Promise.all([
      withRun('run-A', async () => {
        await new Promise((r) => setTimeout(r, 10));
        seen.push(currentRunId() ?? 'none');
      }),
      withRun('run-B', async () => {
        seen.push(currentRunId() ?? 'none');
      }),
    ]);
    expect(seen.sort()).toEqual(['run-A', 'run-B']);
  });
});
