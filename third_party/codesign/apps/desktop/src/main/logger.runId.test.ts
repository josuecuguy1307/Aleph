import { describe, expect, it, vi } from 'vitest';

type Captured = { level: string; scope: string; event: string; data?: unknown };

vi.mock('electron-log/main', () => {
  const capture: Captured[] = [];
  const makeScope = (scope: string) => ({
    info: (event: string, data?: unknown) => capture.push({ level: 'info', scope, event, data }),
    warn: (event: string, data?: unknown) => capture.push({ level: 'warn', scope, event, data }),
    error: (event: string, data?: unknown) => capture.push({ level: 'error', scope, event, data }),
  });
  return {
    default: {
      scope: makeScope,
      capture,
    },
  };
});

vi.mock('./electron-runtime', () => ({
  app: { getPath: () => '/tmp', isPackaged: false, getVersion: () => '0.0.0' },
}));

vi.mock('./storage-settings', () => ({
  getActiveStorageLocations: () => ({ logsDir: '/tmp' }),
}));

import log from 'electron-log/main';
import { getLogger } from './logger';
import { withRun } from './runContext';

const captured = (log as unknown as { capture: Captured[] }).capture;

describe('getLogger + runContext', () => {
  it('includes runId in data when inside withRun', async () => {
    captured.length = 0;
    const logger = getLogger('test');
    await withRun('r-42', () => {
      logger.info('evt', { foo: 1 });
    });
    expect(captured).toEqual([
      { level: 'info', scope: 'test', event: 'evt', data: { runId: 'r-42', foo: 1 } },
    ]);
  });

  it('omits runId outside withRun', () => {
    captured.length = 0;
    getLogger('test').warn('evt');
    expect(captured[0]?.data).toBeUndefined();
  });

  it('does not overwrite a caller-provided runId', async () => {
    captured.length = 0;
    await withRun('outer', () => {
      getLogger('test').info('evt', { runId: 'explicit' });
    });
    expect(captured[0]?.data).toEqual({ runId: 'explicit' });
  });
});
