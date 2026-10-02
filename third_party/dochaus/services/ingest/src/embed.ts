import { Database } from "bun:sqlite"
import { getMeta, setMeta } from "./db"

// Local embedding model, shared shape with dochaus/tool/search-document.ts.
// Both sides MUST use the same model id and pooling so query and chunk vectors
// are comparable. granite-small-r2 replaces MiniLM-L6: MiniLM's
// 256-token window silently truncated half of every 2000-char chunk; granite
// reads 8192 tokens and scores ~14 points higher on MTEB retrieval at the same
// 384 dims, so stored vectors keep their schema. The model card specifies CLS
// pooling, not mean.

export const MODEL = "onnx-community/granite-embedding-small-english-r2-ONNX"
export const DIM = 384

let extractor: any

export async function embed(text: string): Promise<Float32Array> {
  if (!extractor) {
    const { pipeline } = await import("@huggingface/transformers")
    extractor = await pipeline("feature-extraction", MODEL, { dtype: "q8" })
  }
  const output = await extractor(text, { pooling: "cls", normalize: true })
  return output.data as Float32Array
}

// Chunk-side embedding text: a document › section breadcrumb prepended to the
// chunk body. On matters where dozens of contracts share near-identical
// boilerplate, the breadcrumb is what lets the vector channel keep clauses from
// different documents apart. Queries embed raw — only the document side carries
// context. The breadcrumb exists solely in the vector; stored chunk text stays
// the verbatim document text.
export function embedChunk(docName: string, section: string, text: string) {
  return embed(`${docName} › ${section}\n${text}`)
}

// Re-embed every chunk written by an older embedding model. Vectors from two
// models are not comparable, so a stale matter would silently return garbage
// rankings; this runs at service boot (server.ts walks all matters) and before
// any ingest into an existing db, so a matter is never served mixed vectors.
export async function migrateEmbeddings(db: Database): Promise<number> {
  if (getMeta(db, "embedding_model") === MODEL) return 0
  const rows = db.query("SELECT id, doc_name, section, text FROM chunks").all() as Array<{
    id: number
    doc_name: string
    section: string
    text: string
  }>
  // Embed first, write after: bun:sqlite transactions are synchronous, so all
  // awaits happen before the write. The transaction makes the swap atomic — a
  // crash mid-migration leaves the old vectors and old meta intact rather than
  // a mixed-model db (which search-document would refuse, but never serve).
  const vectors = await Promise.all(rows.map((row) => embedChunk(row.doc_name, row.section, row.text)))
  db.transaction(() => {
    rows.forEach((row, i) => {
      const vector = vectors[i]!
      db.run("UPDATE chunks SET embedding = ? WHERE id = ?", [
        Buffer.from(vector.buffer, vector.byteOffset, vector.byteLength),
        row.id,
      ])
    })
    setMeta(db, "embedding_model", MODEL)
  })()
  return rows.length
}
