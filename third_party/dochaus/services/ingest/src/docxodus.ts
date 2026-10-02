import { fileURLToPath } from "node:url"
import path from "node:path"

// Docxodus engine bootstrap for the ingest service — the same .NET 8 OOXML engine
// (compiled to WASM) the dochaus tools use, loaded headless under Bun. Ingest owns
// all document I/O, so it owns baking accepted redlines into the canonical .docx and
// building the redlined comparison the viewer renders.
//
// Docxodus ships its WASM runtime alongside its entrypoint (dist/index.js →
// dist/wasm). The package's exports map hides package.json, so resolve the main
// entry with import.meta.resolve and walk to its sibling wasm dir.
const wasmBase = path.join(path.dirname(fileURLToPath(import.meta.resolve("docxodus"))), "wasm")

let engine: Promise<typeof import("docxodus")> | undefined

export function docxodus() {
  if (!engine)
    engine = import("docxodus").then(async (dx) => {
      if (!dx.isInitialized()) await dx.initialize(wasmBase)
      return dx
    })
  return engine
}
