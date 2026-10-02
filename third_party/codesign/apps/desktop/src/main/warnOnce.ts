interface WarnLike {
  warn: (event: string, data?: Record<string, unknown>) => void;
}

/**
 * Create a dedup'd warn emitter. The first call for a given `key` emits a
 * `warn` through the injected logger; subsequent calls with the same key are
 * silent. The dedup state lives for the lifetime of the returned function
 * (typically a process singleton), so **`key` must be a string literal** — a
 * dynamic key (URL, UUID, timestamp) would leak memory one entry at a time.
 * Use it only for deprecated channels, unreachable-branch warnings, and
 * similar small closed sets.
 */
export function createWarnOnce(logger: WarnLike) {
  const seen = new Set<string>();
  return function warnOnce(key: string, message: string, data?: Record<string, unknown>): void {
    if (seen.has(key)) return;
    seen.add(key);
    logger.warn(`[deprecated:${key}] ${message}`, { firstOccurrence: true, ...(data ?? {}) });
  };
}
