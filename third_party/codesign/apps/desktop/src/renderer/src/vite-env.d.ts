/// <reference types="vite/client" />

// Injected by electron.vite.config.ts `define` at build time.
declare const __APP_VERSION__: string;

// @fontsource-variable/* ship CSS only — no types. TS 6 requires ambient
// declarations for side-effect imports. Declared globally here so consumers
// of packages/ui (which imports these) don't need their own .d.ts.
declare module '@fontsource-variable/fraunces';
declare module '@fontsource-variable/geist';
declare module '@fontsource-variable/jetbrains-mono';
