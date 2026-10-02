import { describe, expect, it } from 'vitest';
import { type CoreLogger, NOOP_LOGGER } from './logger';

describe('CoreLogger', () => {
  it('NOOP_LOGGER exposes info/warn/error as no-ops', () => {
    const logger: CoreLogger = NOOP_LOGGER;
    expect(() => logger.info('evt')).not.toThrow();
    expect(() => logger.warn('evt')).not.toThrow();
    expect(() => logger.error('evt')).not.toThrow();
  });
});
