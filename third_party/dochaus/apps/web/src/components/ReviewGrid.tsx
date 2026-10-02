import { useEffect, useMemo, useRef, useState } from "react"
import { utils, write } from "xlsx"
import { wrapReviewWorkbook } from "../api/review-workbook"
import type { Part } from "@opencode-ai/sdk"
import { getGrid, saveGrid, type Document, type Grid, type GridCellData } from "../api/ingest"
import { createSession, waitForTurn, matterClient, sendPrompt, type Citation, type Client } from "../api/opencode"
import { userFacingError } from "../api/user-facing-error"
import { useLanguage } from "../i18n"
import ViewerModal from "./ViewerModal"

// Tabular review: rows are the matter's documents, columns are natural-language
// questions, each cell is an extracted answer with a source citation. The grid is
// the durable diligence work product — columns and cells persist server-side
// (see api/ingest getGrid/saveGrid). Cells compute once and are cached; only
// empty or stale cells recompute, and `reviewed` cells are frozen.

const POOL = 5 // concurrent cell extractions; the engine handles one prompt each

// Stable id for a question column. Editing a question changes its hash, not its
// id, so existing cells stay linked but flag themselves stale.
function hashQuestion(q: string) {
  let h = 5381
  for (let i = 0; i < q.length; i++) h = (h * 33) ^ q.charCodeAt(i)
  return (h >>> 0).toString(36)
}

function cellKey(docName: string, columnId: string) {
  return `${docName}::${columnId}`
}

// Reduce one extraction session's assistant parts to its answer text and the
// source citation. The agent ends with a `Source: §<section>` line naming the
// passage it used; we match that to the search-document result so the cited
// clause is the one the answer came from, not merely the top-ranked hit. A real
// answer without a declared source gets no citation rather than a wrong one.
function readAnswer(parts: Part[]) {
  const raw = parts
    .filter((p): p is Extract<Part, { type: "text" }> => p.type === "text")
    .map((p) => p.text)
    .join("")
    .trim()
  const citations = parts
    .filter((p): p is Extract<Part, { type: "tool" }> => p.type === "tool")
    .filter((p) => p.tool === "search-document" && p.state.status === "completed")
    .flatMap((p) => ((p.state as { metadata?: { citations?: Citation[] } }).metadata?.citations ?? []))
  const source = raw.match(/\n\s*Source:\s*§?\s*(.+?)\s*$/i)
  const text = source ? raw.slice(0, source.index).trim() : raw
  const section = source?.[1]?.trim()
  const citation = section ? (citations.find((c) => c.section === section) ?? citations[0]) : undefined
  return { text, citation }
}

export default function ReviewGrid({ matterId, title, directory, documents }: { matterId: string; title: string; directory: string; documents: Document[] }) {
  const { t } = useLanguage()
  const client = useMemo<Client>(() => matterClient(directory), [directory])
  const [grid, setGrid] = useState<Grid>({ columns: [], cells: {} })
  const gridRef = useRef<Grid>(grid)
  const [running, setRunning] = useState(0) // cells currently extracting
  const [extractionError, setExtractionError] = useState<string>()
  const [columnEditor, setColumnEditor] = useState<{ id?: string; question: string }>()
  // The detail overlay identifies its cell by key and reads it live from `grid`,
  // so the comment thread updates in place as comments are added or removed.
  const [detail, setDetail] = useState<{ docName: string; columnId: string; question: string }>()
  const [draft, setDraft] = useState("") // comment being composed in the overlay
  const detailCell = detail ? grid.cells[cellKey(detail.docName, detail.columnId)] : undefined

  useEffect(() => {
    getGrid(matterId).then((g) => commit(g))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matterId])

  // One writer for both state and the server, so concurrent cell completions
  // merge against the latest grid (each call reads+writes gridRef synchronously).
  function commit(next: Grid) {
    gridRef.current = next
    setGrid(next)
    saveGrid(matterId, next)
  }

  function commitCell(key: string, data: GridCellData) {
    commit({ ...gridRef.current, cells: { ...gridRef.current.cells, [key]: data } })
  }

  function addColumn() {
    setColumnEditor({ question: "" })
  }

  function renameColumn(id: string) {
    const col = gridRef.current.columns.find((c) => c.id === id)
    setColumnEditor({ id, question: col?.question ?? "" })
  }

  function saveColumn() {
    const question = columnEditor?.question.trim()
    if (!question) return
    const id = columnEditor?.id
    commit({ ...gridRef.current, columns: id
      ? gridRef.current.columns.map((c) => c.id === id ? { ...c, question } : c)
      : [...gridRef.current.columns, { id: crypto.randomUUID().slice(0, 6), question }] })
    setColumnEditor(undefined)
  }

  function deleteColumn(id: string) {
    const cells = { ...gridRef.current.cells }
    for (const doc of documents) delete cells[cellKey(doc.name, id)]
    commit({ columns: gridRef.current.columns.filter((c) => c.id !== id), cells })
  }

  function toggleReviewed(key: string) {
    const cell = gridRef.current.cells[key]
    if (!cell) return
    commitCell(key, { ...cell, status: cell.status === "reviewed" ? "filled" : "reviewed" })
  }

  function addComment() {
    const text = draft.trim()
    if (!detail || !text) return
    const key = cellKey(detail.docName, detail.columnId)
    const cell = gridRef.current.cells[key]
    commitCell(key, {
      ...cell,
      comments: [...(cell.comments ?? []), { id: crypto.randomUUID().slice(0, 6), text, at: Date.now() }],
    })
    setDraft("")
  }

  function deleteComment(id: string) {
    if (!detail) return
    const key = cellKey(detail.docName, detail.columnId)
    const cell = gridRef.current.cells[key]
    commitCell(key, { ...cell, comments: (cell.comments ?? []).filter((c) => c.id !== id) })
  }

  // Extract one cell: a scoped, throwaway session titled so it stays out of the
  // sidebar's conversation list (which filters system-titled sessions).
  async function extract(docName: string, question: string): Promise<GridCellData> {
    const session = await createSession(client, `Legal grid: ${docName}`)
    await sendPrompt(client, session.id, "extract", `Document: "${docName}". Question: ${question}`)
    const messages = await waitForTurn(client, session.id)
    // A tool-using turn emits several assistant messages (one per model step): the
    // search-document call lands on an earlier one, the final answer text on the
    // last. Read every assistant part so the citation is not dropped.
    const { text, citation } = readAnswer(messages.filter((m) => m.info.role === "assistant").flatMap((m) => m.parts))
    return {
      answer: text || "Not addressed",
      citation: citation && {
        documentName: citation.documentName,
        docPath: citation.docPath,
        section: citation.section,
        excerpt: citation.excerpt,
        charStart: citation.charStart,
        charEnd: citation.charEnd,
      },
      status: "filled",
      questionHash: hashQuestion(question),
    }
  }

  // Run a set of (document, column) targets through a small concurrency pool so a
  // large grid does not open hundreds of sessions at once.
  async function fill(targets: Array<{ docName: string; column: { id: string; question: string } }>) {
    if (targets.length === 0) return
    setExtractionError(undefined)
    setRunning((n) => n + targets.length)
    let next = 0
    const worker = async () => {
      while (next < targets.length) {
        const t = targets[next++]
        try {
          const data = await extract(t.docName, t.column.question)
          const key = cellKey(t.docName, t.column.id)
          // Recomputing preserves existing comments and never stores an error as an answer.
          commitCell(key, { ...data, comments: gridRef.current.cells[key]?.comments })
        } catch (error) {
          setExtractionError(userFacingError(error instanceof Error ? error.message : String(error)))
        } finally {
          setRunning((n) => n - 1)
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(POOL, targets.length) }, worker))
  }

  function fillEmpty() {
    const targets = documents.flatMap((doc) =>
      grid.columns
        .filter((col) => {
          const cell = grid.cells[cellKey(doc.name, col.id)]
          // Compute blanks and stale cells; never touch a reviewed (locked) cell.
          return !cell || (cell.status !== "reviewed" && cell.questionHash !== hashQuestion(col.question))
        })
        .map((column) => ({ docName: doc.name, column })),
    )
    fill(targets)
  }

  function exportXlsx() {
    const header = ["Document", ...grid.columns.map((c) => c.question)]
    const rows = documents.map((doc) => [
      doc.name,
      ...grid.columns.map((c) => grid.cells[cellKey(doc.name, c.id)]?.answer ?? ""),
    ])
    const sheet = utils.aoa_to_sheet([header, ...rows])
    sheet["!cols"] = [{ wch: 48 }, ...grid.columns.map(() => ({ wch: 80 }))]
    sheet["!rows"] = [header, ...rows].map((row) => ({
      hpt: Math.max(24, ...row.map((text, c) =>
        String(text).split("\n").reduce((lines, line) => lines + Math.max(1, Math.ceil(line.length / (c === 0 ? 42 : 70))), 0) * 18 + 8)),
    }))
    // Citation and reviewer comment travel as a native Excel note on the answer
    // cell, so the export carries everything the grid shows without extra columns.
    documents.forEach((doc, r) =>
      grid.columns.forEach((col, c) => {
        const cell = grid.cells[cellKey(doc.name, col.id)]
        const note = [
          cell?.citation && `Source: ${cell.citation.documentName} § ${cell.citation.section}`,
          ...(cell?.comments ?? []).map((m) => `Comment (${new Date(m.at).toLocaleDateString()}): ${m.text}`),
        ]
          .filter((line): line is string => Boolean(line))
          .join("\n")
        if (note) sheet[utils.encode_cell({ r: r + 1, c: c + 1 })].c = Object.assign([{ a: "Aleph Legal", t: note }], { hidden: true })
      }),
    )
    const book = utils.book_new()
    utils.book_append_sheet(book, sheet, "Tabular review")
    const slug = title.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "matter"
    const buf = wrapReviewWorkbook(new Uint8Array(write(book, { type: "array", bookType: "xlsx" })))
    const url = URL.createObjectURL(
      new Blob([new Uint8Array(buf).buffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
    )
    const a = document.createElement("a")
    a.href = url
    a.download = `${slug}-tabular-review.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (documents.length === 0)
    return <div className="empty-inline">Add documents to this matter to build a review grid.</div>

  return (
    <div className="card review">
      <div className="row review-toolbar">
        <div>
          <h2>Tabular review</h2>
          <span className="review-summary">
            {documents.length} document{documents.length === 1 ? "" : "s"} · {grid.columns.length} question{grid.columns.length === 1 ? "" : "s"}
          </span>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {running > 0 && <span className="review-running">Extracting {running}</span>}
          <button onClick={addColumn}>Add column</button>
          <button onClick={fillEmpty} disabled={grid.columns.length === 0 || running > 0}>
            Fill empty
          </button>
          <button onClick={exportXlsx} disabled={grid.columns.length === 0}>
            Export Excel
          </button>
        </div>
      </div>

      {extractionError && <p role="alert">{extractionError}</p>}

      {columnEditor && (
        <form className="row" style={{ gap: 8, marginBottom: 16, alignItems: "flex-end" }} onSubmit={(e) => { e.preventDefault(); saveColumn() }}>
          <label style={{ flex: 1 }}>
            {t(columnEditor.id ? "Edit column question" : "New column question (e.g. What is the governing law?)")}
            <input autoFocus value={columnEditor.question} style={{ width: "100%" }}
              onChange={(e) => setColumnEditor({ ...columnEditor, question: e.target.value })}
              onKeyDown={(e) => { if (e.key === "Escape") setColumnEditor(undefined) }} />
          </label>
          <button type="submit" disabled={!columnEditor.question.trim()}>{t("Save")}</button>
          <button type="button" onClick={() => setColumnEditor(undefined)}>{t("Cancel")}</button>
        </form>
      )}

      {grid.columns.length === 0 ? (
        <div className="empty-inline">Add a column — a question asked of every document, e.g. "What is the governing law?"</div>
      ) : (
        <div className="review-scroll">
          <table className="review-table">
            <thead>
              <tr>
                <th className="review-doc-col">Document</th>
                {grid.columns.map((col) => (
                  <th key={col.id}>
                    <div className="review-col-head">
                      <button className="review-col-q" onClick={() => renameColumn(col.id)} title="Edit question">
                        {col.question}
                      </button>
                      <button className="icon-btn review-col-x" onClick={() => deleteColumn(col.id)} title="Delete column">
                        ×
                      </button>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td className="review-doc-col">{doc.name}</td>
                  {grid.columns.map((col) => {
                    const key = cellKey(doc.name, col.id)
                    const cell = grid.cells[key]
                    const stale = cell && cell.status !== "reviewed" && cell.questionHash !== hashQuestion(col.question)
                    return (
                      <td key={col.id} className={`review-cell${cell?.status === "reviewed" ? " reviewed" : ""}`}>
                        {!cell ? (
                          <button
                            className="review-cell-fill"
                            disabled={running > 0}
                            onClick={() => fill([{ docName: doc.name, column: col }])}
                          >
                            Fill
                          </button>
                        ) : (
                          <div className="review-cell-body">
                            <button
                              className="review-answer"
                              onClick={() => {
                                setDraft("")
                                setDetail({ docName: doc.name, columnId: col.id, question: col.question })
                              }}
                            >
                              {cell.answer}
                              {cell.citation && <span className="review-cite"> [{cell.citation.documentName} § {cell.citation.section}]</span>}
                            </button>
                            <div className="review-cell-actions">
                              <button
                                className={`icon-btn review-note${cell.comments?.length ? " has-comments" : ""}`}
                                title={cell.comments?.map((c) => c.text).join("\n") || "Add a comment"}
                                onClick={() => {
                                  setDraft("")
                                  setDetail({ docName: doc.name, columnId: col.id, question: col.question })
                                }}
                              >
                                <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true">
                                  <path
                                    d="M3 2.5h10A1.5 1.5 0 0 1 14.5 4v6a1.5 1.5 0 0 1-1.5 1.5H8.5L5 14.5v-3H3A1.5 1.5 0 0 1 1.5 10V4A1.5 1.5 0 0 1 3 2.5Z"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="1.4"
                                    strokeLinejoin="round"
                                  />
                                </svg>
                                {cell.comments?.length ?? 0}
                              </button>
                              {stale && <span className="review-stale" title="Question changed since this answer">stale</span>}
                              <button className={`icon-btn review-lock${cell.status === "reviewed" ? " locked" : ""}`} title={cell.status === "reviewed" ? "Unlock" : "Mark reviewed"} onClick={() => toggleReviewed(key)}>
                                {cell.status === "reviewed" ? "Locked" : "Lock"}
                              </button>
                              {cell.status !== "reviewed" && (
                                <button className="icon-btn" title="Re-run this cell" disabled={running > 0} onClick={() => fill([{ docName: doc.name, column: col }])}>
                                  Refresh
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail && detailCell && (
        <ViewerModal onClose={() => setDetail(undefined)}>
          <div className="picker-panel" onClick={(e) => e.stopPropagation()}>
            <div className="viewer-bar">
              <span className="viewer-title">{detail.question}</span>
              <button onClick={() => setDetail(undefined)}>Close</button>
            </div>
            <div className="picker-body">
              <p className="review-detail-answer">{detailCell.answer}</p>
              {detailCell.citation && (
                <div className="citation">
                  <div className="ref">[{detailCell.citation.documentName} § {detailCell.citation.section}]</div>
                  <div className="excerpt">{detailCell.citation.excerpt}</div>
                </div>
              )}
              <div className="review-comments">
                {(detailCell.comments ?? []).map((c) => (
                  <div key={c.id} className="review-comment">
                    <div className="review-comment-meta">
                      <span className="muted">{new Date(c.at).toLocaleString()}</span>
                      <button className="icon-btn" title="Delete comment" onClick={() => deleteComment(c.id)}>
                        ×
                      </button>
                    </div>
                    <div className="review-comment-text">{c.text}</div>
                  </div>
                ))}
                <div className="review-comment-compose">
                  <textarea
                    value={draft}
                    placeholder="Add a comment..."
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault()
                        addComment()
                      }
                    }}
                  />
                  <button onClick={addComment} disabled={!draft.trim()}>
                    Send
                  </button>
                </div>
              </div>
            </div>
          </div>
        </ViewerModal>
      )}
    </div>
  )
}
