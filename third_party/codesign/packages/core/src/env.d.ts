// Build-time string imports for HTML/Markdown frame & skill templates.
// electron-vite (Vite) inlines these as plain strings at build time, so
// the bundled main process has no runtime fs dependency.
declare module '*.html?raw' {
  const content: string;
  export default content;
}

declare module '*.md?raw' {
  const content: string;
  export default content;
}

declare module '*.jsx?raw' {
  const content: string;
  export default content;
}
