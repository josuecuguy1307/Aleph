import type { Citation } from "../api/opencode"

export default function CitationView({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null
  // A turn's searches return the same section many times over; the reader needs
  // each distinct source once, not the raw retrieval dump. Keep the best-scoring
  // hit per document+section and tuck them behind a collapsed "Sources" line so
  // the answer stays the focus — the compact source list Harvey and Legora show.
  const best = new Map<string, Citation>()
  for (const c of [...citations].sort((a, b) => a.score - b.score)) best.set(`${c.documentName}§${c.section}`, c)
  const unique = [...best.values()].sort((a, b) => b.score - a.score)
  return (
    <details className="sources">
      <summary>
        Sources ({unique.length})
      </summary>
      {unique.map((c, i) => (
        <div className="citation" key={`${c.docPath}-${c.charStart}-${i}`}>
          <div className="ref">
            [{c.documentName} § {c.section}]
          </div>
          <div className="excerpt">{c.excerpt}</div>
        </div>
      ))}
    </details>
  )
}
