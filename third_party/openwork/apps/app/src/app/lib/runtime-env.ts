// Runtime detection primitives. Leaf module by design: keep it import-free so
// low-level clients (opencode, openwork-server, den) can use it without
// dragging in the utils barrel (which pulls i18n and app constants).
export function isElectronRuntime() {
  return typeof window !== "undefined" && (window as Window).__OPENWORK_ELECTRON__ != null;
}

/** Aleph usa Tauri en vez del shell Electron de Openwork. */
export function isTauriRuntime() {
  return typeof window !== "undefined" && (window as Window).__TAURI__?.core?.invoke != null;
}

export function isDesktopRuntime() {
  return isElectronRuntime() || isTauriRuntime();
}
