/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_OPENCODE_URL?: string
  readonly VITE_INGEST_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
