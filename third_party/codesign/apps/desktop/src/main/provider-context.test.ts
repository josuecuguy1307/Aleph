import { describe, expect, it } from 'vitest';
import { createProviderContextStore } from './provider-context';

describe('createProviderContextStore', () => {
  it('remember then consume returns the context and deletes it', () => {
    const store = createProviderContextStore();
    const ctx = { upstream_status: 504, upstream_request_id: 'req_1' };
    store.remember('run-a', ctx);
    expect(store.size()).toBe(1);
    expect(store.consume('run-a')).toEqual(ctx);
    expect(store.size()).toBe(0);
    // Second consume returns undefined — the entry was removed.
    expect(store.consume('run-a')).toBeUndefined();
  });

  it('consume of an unknown runId returns undefined', () => {
    const store = createProviderContextStore();
    expect(store.consume('never-stashed')).toBeUndefined();
  });

  it('evicts the oldest entry when maxEntries is reached', () => {
    const store = createProviderContextStore(3);
    store.remember('a', { v: 1 });
    store.remember('b', { v: 2 });
    store.remember('c', { v: 3 });
    // Inserting past the cap should evict 'a' (oldest by insertion).
    store.remember('d', { v: 4 });
    expect(store.size()).toBe(3);
    expect(store.consume('a')).toBeUndefined();
    expect(store.consume('b')).toEqual({ v: 2 });
    expect(store.consume('c')).toEqual({ v: 3 });
    expect(store.consume('d')).toEqual({ v: 4 });
  });

  it('overwriting an existing key does not grow size past the cap', () => {
    const store = createProviderContextStore(2);
    store.remember('a', { v: 1 });
    store.remember('a', { v: 2 });
    expect(store.size()).toBe(1);
    expect(store.consume('a')).toEqual({ v: 2 });
  });

  it('does NOT evict when overwriting an existing key even at capacity', () => {
    const store = createProviderContextStore(3);
    store.remember('a', { v: 1 });
    store.remember('b', { v: 2 });
    store.remember('c', { v: 3 });
    // Overwrite 'a' — a second `provider.error` for the same runId should
    // refresh the stash in place, not silently evict 'b' (the oldest by
    // insertion) and lose an unrelated run's upstream_request_id.
    store.remember('a', { v: 99 });
    expect(store.size()).toBe(3);
    expect(store.consume('b')).toEqual({ v: 2 });
    expect(store.consume('a')).toEqual({ v: 99 });
    expect(store.consume('c')).toEqual({ v: 3 });
  });
});
