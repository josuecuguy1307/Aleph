import { afterEach, describe, expect, it, vi } from 'vitest';
import { recordAction, resetTimeline, snapshotTimeline } from './action-timeline';

describe('action-timeline', () => {
  afterEach(() => {
    vi.useRealTimers();
    resetTimeline();
  });

  it('records entries with a ts', () => {
    recordAction({ type: 'prompt.submit', data: { promptLen: 10 } });
    const snap = snapshotTimeline();
    expect(snap).toHaveLength(1);
    expect(snap[0]?.type).toBe('prompt.submit');
    expect(typeof snap[0]?.ts).toBe('number');
  });

  it('trims to capacity of 40', () => {
    for (let i = 0; i < 50; i++) {
      recordAction({ type: 'prompt.submit', data: { i } });
    }
    expect(snapshotTimeline()).toHaveLength(40);
    // Keeps the newest 40
    expect(snapshotTimeline()[0]?.data?.['i']).toBe(10);
  });

  it('drops entries older than 60 s', () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    recordAction({ type: 'prompt.submit' });
    vi.setSystemTime(61_000);
    recordAction({ type: 'prompt.cancel' });
    const snap = snapshotTimeline();
    expect(snap).toHaveLength(1);
    expect(snap[0]?.type).toBe('prompt.cancel');
  });

  it('snapshot returns a defensive copy', () => {
    recordAction({ type: 'prompt.submit' });
    const snap = snapshotTimeline();
    snap.push({ ts: Date.now(), type: 'prompt.cancel' });
    expect(snapshotTimeline()).toHaveLength(1);
  });

  it('reset clears the buffer', () => {
    recordAction({ type: 'prompt.submit' });
    resetTimeline();
    expect(snapshotTimeline()).toHaveLength(0);
  });
});
