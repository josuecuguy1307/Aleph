import "@testing-library/jest-dom/vitest";
import type {} from "vitest/jsdom";

// Vitest preserves pre-existing Node globals, including Node 25+'s native
// Web Storage. Browser tests must use jsdom's per-window Storage instead of
// Node's file-backed (or unavailable) implementation. Use the real DOM Storage
// so prototype spies, storage events and blocked-storage tests still work.
// Source-only tests opt into the Node environment and have no jsdom window.
if (typeof jsdom !== "undefined") {
  for (const name of ["localStorage", "sessionStorage"] as const) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      writable: true,
      value: jsdom.window[name],
    });
  }
}

// ── Global mocks for jsdom ───────────────────────────────────

// jsdom doesn't implement ResizeObserver (ECharts + layout components need it)
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

// jsdom doesn't implement matchMedia
if (typeof window !== "undefined") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// Initialize only after the browser globals are ready: the language detector
// reads and caches localStorage during module evaluation.
await import("../i18n");
