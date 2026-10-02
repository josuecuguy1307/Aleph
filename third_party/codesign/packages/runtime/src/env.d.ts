// Build-time string imports for vendored UMD bundles + JSX frame snippets.
// Vite (in the renderer) inlines these as plain strings at build time, so
// the iframe srcdoc can embed them with no runtime fetches.
declare module '*.js?raw' {
  const content: string;
  export default content;
}
declare module '*.jsx?raw' {
  const content: string;
  export default content;
}
