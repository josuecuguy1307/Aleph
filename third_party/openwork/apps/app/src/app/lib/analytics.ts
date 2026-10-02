/**
 * Aleph Oficina keeps local instrumentation only.  This module intentionally
 * has no vendor key, collector URL, identity linkage, timer or network I/O.
 * Callers retain their inspector events without exporting user activity.
 */
import { recordInspectorEvent } from "./app-inspector";

export type AnalyticsProperties = Record<string, string | number | boolean | null>;

const startedTasks = new Map<string, number>();

export function isAnalyticsEnabled(): boolean {
  return false;
}

export function getAnalyticsDistinctId(): string {
  return "local-only";
}

export function captureAnalyticsEvent(event: string, properties: AnalyticsProperties = {}) {
  try {
    recordInspectorEvent(`local-instrumentation.${event}`, properties);
  } catch {
    // The inspector is optional and never affects the workspace.
  }
}

export async function flushAnalytics(): Promise<void> {}

export function markTaskRunStart(sessionId: string) {
  startedTasks.set(sessionId, Date.now());
}

export function takeTaskRunStart(sessionId: string): number | null {
  const startedAt = startedTasks.get(sessionId);
  startedTasks.delete(sessionId);
  return startedAt ?? null;
}

export function initAnalytics() {}

export function disposeAnalytics() {
  startedTasks.clear();
}
