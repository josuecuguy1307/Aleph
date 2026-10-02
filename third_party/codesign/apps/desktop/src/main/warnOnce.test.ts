import { describe, expect, it, vi } from 'vitest';
import { createWarnOnce } from './warnOnce';

describe('createWarnOnce', () => {
  it('warns once per key; repeated calls are suppressed', () => {
    const warn = vi.fn();
    const warnOnce = createWarnOnce({ warn });
    warnOnce('legacy.a', 'msg A');
    warnOnce('legacy.a', 'msg A');
    warnOnce('legacy.a', 'msg A');
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(
      '[deprecated:legacy.a] msg A',
      expect.objectContaining({ firstOccurrence: true }),
    );
  });

  it('treats different keys independently', () => {
    const warn = vi.fn();
    const warnOnce = createWarnOnce({ warn });
    warnOnce('legacy.a', 'msg');
    warnOnce('legacy.b', 'msg');
    expect(warn).toHaveBeenCalledTimes(2);
  });

  it('merges caller-provided data into the warn payload', () => {
    const warn = vi.fn();
    const warnOnce = createWarnOnce({ warn });
    warnOnce('legacy.c', 'msg', { caller: 'test' });
    expect(warn).toHaveBeenCalledWith(
      '[deprecated:legacy.c] msg',
      expect.objectContaining({ firstOccurrence: true, caller: 'test' }),
    );
  });
});
