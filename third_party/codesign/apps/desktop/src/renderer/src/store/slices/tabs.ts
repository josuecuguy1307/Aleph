// Workstream G - canvas tabs.
// 'files' is the pinned tab that hosts the file list + inline preview; 'file'
// tabs wrap a single file preview opened by double-clicking the list. Closing
// a 'file' tab is purely UI state and does not delete anything.
export type CanvasTab = { kind: 'files' } | { kind: 'file'; path: string };

export const FILES_TAB: CanvasTab = { kind: 'files' };
export const DEFAULT_CANVAS_TABS: CanvasTab[] = [FILES_TAB];

// Pure reducers, exported for unit tests so we don't need RTL for slice logic.
export function openFileTab(tabs: CanvasTab[], path: string): { tabs: CanvasTab[]; index: number } {
  const existing = tabs.findIndex((tab) => tab.kind === 'file' && tab.path === path);
  if (existing !== -1) return { tabs, index: existing };
  const next: CanvasTab[] = [...tabs, { kind: 'file', path }];
  return { tabs: next, index: next.length - 1 };
}

export function closeTabAt(
  tabs: CanvasTab[],
  activeIndex: number,
  target: number,
): { tabs: CanvasTab[]; activeIndex: number } {
  const tab = tabs[target];
  if (!tab) return { tabs, activeIndex };
  if (tab.kind !== 'file') return { tabs, activeIndex };
  const next = tabs.filter((_, index) => index !== target);
  let nextActive = activeIndex;
  if (activeIndex === target) {
    nextActive = Math.max(0, target - 1);
  } else if (activeIndex > target) {
    nextActive = activeIndex - 1;
  }
  return { tabs: next, activeIndex: nextActive };
}
