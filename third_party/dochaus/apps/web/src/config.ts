// The two backends apps/web talks to. Vite development can still address their ephemeral
// ports directly; the installed static server proxies these two relative prefixes so its
// already-horneado dist never needs a port baked at build time.
export const OPENCODE_URL = import.meta.env.VITE_OPENCODE_URL ?? "/opencode"
export const INGEST_URL = import.meta.env.VITE_INGEST_URL ?? "/ingest"
