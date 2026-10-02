import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { rotateLogFile } from './logger';

// Use path.join so expectations match native separators on Windows CI.
const LOGS = join('/tmp', 'logs');
const ACTIVE = join(LOGS, 'main.log');
const OLD = join(LOGS, 'main.old.log');
const OLDEST = join(LOGS, 'main.old.1.log');

describe('rotateLogFile', () => {
  it('shifts main.log -> main.old.log when no old exists', () => {
    const fs = {
      existsSync: vi.fn((p: string) => p === ACTIVE),
      renameSync: vi.fn(),
      unlinkSync: vi.fn(),
    };
    rotateLogFile(ACTIVE, fs);
    expect(fs.renameSync).toHaveBeenCalledWith(ACTIVE, OLD);
    expect(fs.unlinkSync).not.toHaveBeenCalled();
  });

  it('shifts both slots when main.log and main.old.log exist', () => {
    const exists = new Set([ACTIVE, OLD]);
    const fs = {
      existsSync: vi.fn((p: string) => exists.has(p)),
      renameSync: vi.fn(),
      unlinkSync: vi.fn(),
    };
    rotateLogFile(ACTIVE, fs);
    expect(fs.renameSync).toHaveBeenNthCalledWith(1, OLD, OLDEST);
    expect(fs.renameSync).toHaveBeenNthCalledWith(2, ACTIVE, OLD);
    expect(fs.unlinkSync).not.toHaveBeenCalled();
  });

  it('drops oldest when all three slots exist', () => {
    const exists = new Set([ACTIVE, OLD, OLDEST]);
    const fs = {
      existsSync: vi.fn((p: string) => exists.has(p)),
      renameSync: vi.fn(),
      unlinkSync: vi.fn(),
    };
    rotateLogFile(ACTIVE, fs);
    expect(fs.unlinkSync).toHaveBeenCalledWith(OLDEST);
    expect(fs.renameSync).toHaveBeenCalledTimes(2);
  });

  it('is a no-op when the active file does not yet exist', () => {
    const fs = {
      existsSync: vi.fn(() => false),
      renameSync: vi.fn(),
      unlinkSync: vi.fn(),
    };
    rotateLogFile(ACTIVE, fs);
    expect(fs.renameSync).not.toHaveBeenCalled();
    expect(fs.unlinkSync).not.toHaveBeenCalled();
  });

  it('reports rename failure via onError and still attempts remaining steps', () => {
    const fs = {
      existsSync: vi.fn(() => true),
      renameSync: vi.fn((_a: string, _b: string) => {
        throw new Error('EBUSY: resource busy or locked');
      }),
      unlinkSync: vi.fn(),
    };
    const errors: Array<{ step: string; message: string }> = [];
    const onError = (step: string, err: unknown) => {
      errors.push({ step, message: err instanceof Error ? err.message : String(err) });
    };
    expect(() => rotateLogFile(ACTIVE, fs, onError)).not.toThrow();
    expect(errors.map((e) => e.step)).toEqual(['rename_old_to_oldest', 'rename_active_to_old']);
    expect(errors[0]?.message).toContain('EBUSY');
    expect(fs.renameSync).toHaveBeenCalledTimes(2);
  });

  it('continues when unlinkSync throws on the oldest slot', () => {
    const fs = {
      existsSync: vi.fn(() => true),
      renameSync: vi.fn(),
      unlinkSync: vi.fn(() => {
        throw new Error('EPERM');
      }),
    };
    const errors: Array<{ step: string; message: string }> = [];
    const onError = (step: string, err: unknown) => {
      errors.push({ step, message: err instanceof Error ? err.message : String(err) });
    };
    rotateLogFile(ACTIVE, fs, onError);
    expect(errors[0]?.step).toBe('unlink_oldest');
    expect(fs.renameSync).toHaveBeenCalledTimes(2);
  });
});
