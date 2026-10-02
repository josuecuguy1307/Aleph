import { describe, expect, it } from 'vitest';
import { __test } from './process-registry';

describe('process-registry port regex', () => {
  for (const sample of [
    '  ➜  Local:   http://localhost:5173/',
    'listening on 3000',
    'ready in 1842 ms\nLocal: http://127.0.0.1:4321/',
    'Server running on port 8080',
  ]) {
    it(`matches: ${sample.replace(/\n/g, '\\n').slice(0, 40)}`, () => {
      const m = __test.PORT_RE.exec(sample);
      expect(m?.[1]).toBeTruthy();
      const num = Number(m?.[1]);
      expect(num).toBeGreaterThan(999);
      expect(num).toBeLessThan(65536);
    });
  }

  it('limits are tight enough to prevent runaway', () => {
    expect(__test.GLOBAL_LIMIT).toBeLessThanOrEqual(20);
    expect(__test.PER_DESIGN_LIMIT).toBeLessThanOrEqual(5);
  });
});
