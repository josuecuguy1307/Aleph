import { For, Show, createMemo, createSignal, type JSX } from "solid-js"
import { FONT_CODE, FONT_MONO, FONT_SANS } from "@/styles/tokens"
import { exportDelimited, parseTable, summarizeColumn, type DataTable, type TableFormat } from "./table"

const PAGE_SIZE = 100

export function DataTableView(props: { text: string; format: TableFormat; name: string }): JSX.Element {
  const [query, setQuery] = createSignal("")
  const [sort, setSort] = createSignal<{ index: number; direction: "asc" | "desc" }>()
  const [page, setPage] = createSignal(0)
  const [schema, setSchema] = createSignal(false)
  const [plot, setPlot] = createSignal(false)
  const [column, setColumn] = createSignal(0)

  const parsed = createMemo(() => {
    try {
      return { table: parseTable(props.format, props.text), error: "" }
    } catch (cause) {
      return {
        table: undefined,
        error: cause instanceof Error ? cause.message : "Could not parse table",
      }
    }
  })
  const table = () => parsed().table
  const numeric = createMemo(
    () =>
      table()
        ?.schema.map((value, index) => ({ ...value, index }))
        .filter((value) => value.type === "number") ?? [],
  )
  const plottedColumn = () =>
    numeric().some((value) => value.index === column()) ? column() : (numeric()[0]?.index ?? 0)
  const filtered = createMemo(() => {
    const data = table()
    if (!data) return []
    const term = query().trim().toLowerCase()
    const rows = term ? data.rows.filter((row) => row.some((value) => value.toLowerCase().includes(term))) : data.rows
    const order = sort()
    if (!order) return rows
    const type = data.schema[order.index]?.type ?? "string"
    return rows
      .map((row, index) => ({ row, index }))
      .sort((a, b) => {
        const left = a.row[order.index] ?? ""
        const right = b.row[order.index] ?? ""
        const result = compare(left, right, type)
        return (result || a.index - b.index) * (order.direction === "asc" ? 1 : -1)
      })
      .map((value) => value.row)
  })
  const pages = () => Math.max(1, Math.ceil(filtered().length / PAGE_SIZE))
  const visible = () => filtered().slice(page() * PAGE_SIZE, (page() + 1) * PAGE_SIZE)

  const sortBy = (index: number) => {
    setPage(0)
    setSort((current) => {
      if (!current || current.index !== index) return { index, direction: "asc" }
      if (current.direction === "asc") return { index, direction: "desc" }
      return undefined
    })
  }

  const download = () => {
    const data = table()
    if (!data) return
    const text = exportDelimited({ columns: data.columns, rows: filtered() })
    const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }))
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `${props.name.replace(/\.[^.]+$/, "")}.filtered.csv`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div
      data-component="data-table"
      style={{
        height: "100%",
        "min-height": "100%",
        display: "flex",
        "flex-direction": "column",
        background: "var(--color-bg-subtle)",
      }}
    >
      <Show
        when={table()}
        fallback={
          <div style={empty()}>
            <strong style={{ "font-family": FONT_SANS, "font-size": "14px" }}>Could not read this table</strong>
            <span style={{ "font-family": FONT_MONO, "font-size": "11px", color: "var(--color-text-faint)" }}>
              {parsed().error}
            </span>
          </div>
        }
      >
        {(data) => (
          <>
            <div
              style={{
                display: "flex",
                "align-items": "center",
                gap: "8px",
                padding: "10px 12px",
                border: "0",
                "border-bottom": "1px solid var(--color-border)",
                background: "var(--color-bg)",
                "flex-wrap": "wrap",
              }}
            >
              <div style={{ display: "flex", "align-items": "baseline", gap: "6px", "margin-right": "4px" }}>
                <strong style={{ "font-family": FONT_SANS, "font-size": "12px", color: "var(--color-text)" }}>
                  {data().totalRows.toLocaleString()} rows
                </strong>
                <span style={{ "font-family": FONT_MONO, "font-size": "9px", color: "var(--color-text-faint)" }}>
                  × {data().columns.length} columns
                </span>
              </div>
              <input
                data-action="table-filter"
                aria-label="Filter rows"
                placeholder="filter every column…"
                value={query()}
                onInput={(event) => {
                  setQuery(event.currentTarget.value)
                  setPage(0)
                }}
                style={input()}
              />
              <Show when={query()}>
                <span style={{ "font-family": FONT_MONO, "font-size": "9px", color: "var(--color-text-faint)" }}>
                  {filtered().length.toLocaleString()} matches
                </span>
              </Show>
              <div style={{ flex: 1 }} />
              <button
                type="button"
                data-action="table-schema"
                style={button(schema())}
                onClick={() => setSchema((value) => !value)}
              >
                schema
              </button>
              <select
                aria-label="Plot column"
                value={String(plottedColumn())}
                disabled={!numeric().length}
                onChange={(event) => setColumn(Number(event.currentTarget.value))}
                style={select()}
              >
                <For each={numeric()}>{(value) => <option value={value.index}>{value.name}</option>}</For>
              </select>
              <button
                type="button"
                data-action="table-plot"
                disabled={!numeric().length}
                style={button(plot())}
                onClick={() => setPlot((value) => !value)}
              >
                distribution
              </button>
              <button type="button" data-action="table-export" style={button()} onClick={download}>
                export filtered
              </button>
            </div>

            <Show when={schema()}>
              <div
                class="atlas-scroll"
                style={{
                  display: "flex",
                  gap: "8px",
                  padding: "10px 12px",
                  overflow: "auto hidden",
                  border: "0",
                  "border-bottom": "1px solid var(--color-border)",
                  background: "color-mix(in srgb, var(--color-bg-subtle) 70%, var(--color-bg))",
                }}
              >
                <For each={data().schema}>
                  {(value) => (
                    <div
                      style={{
                        width: "170px",
                        "flex-shrink": 0,
                        padding: "9px 10px",
                        border: "1px solid var(--color-border)",
                        "border-radius": "6px",
                        background: "var(--color-bg)",
                      }}
                    >
                      <div
                        title={value.name}
                        style={{
                          "font-family": FONT_CODE,
                          "font-size": "10px",
                          color: "var(--color-text)",
                          overflow: "hidden",
                          "text-overflow": "ellipsis",
                          "white-space": "nowrap",
                        }}
                      >
                        {value.name}
                      </div>
                      <div
                        style={{
                          display: "flex",
                          gap: "8px",
                          "margin-top": "5px",
                          "font-family": FONT_MONO,
                          "font-size": "9px",
                          color: "var(--color-text-faint)",
                        }}
                      >
                        <span>{value.type}</span>
                        <span>{value.unique.toLocaleString()} unique</span>
                        <span>{value.missing.toLocaleString()} missing</span>
                      </div>
                      <div
                        title={`${value.missing} missing values`}
                        style={{
                          height: "3px",
                          "margin-top": "8px",
                          "border-radius": "2px",
                          background: `linear-gradient(90deg, var(--color-warning, #8a5d0c) ${(value.missing / Math.max(1, data().totalRows)) * 100}%, var(--color-border) 0)`,
                        }}
                      />
                    </div>
                  )}
                </For>
              </div>
            </Show>

            <Show when={plot() && numeric().length}>
              <Histogram table={data()} index={plottedColumn()} onClose={() => setPlot(false)} />
            </Show>

            <div class="atlas-scroll" style={{ flex: 1, "min-height": 0, overflow: "auto" }}>
              <table
                style={{
                  width: "max-content",
                  "min-width": "100%",
                  "border-collapse": "separate",
                  "border-spacing": 0,
                  "font-family": FONT_CODE,
                  "font-size": "10px",
                  "font-variant-numeric": "tabular-nums",
                }}
              >
                <thead>
                  <tr>
                    <th style={{ ...head(), left: 0, "z-index": 3, width: "48px", "min-width": "48px" }}>#</th>
                    <For each={data().columns}>
                      {(name, index) => (
                        <th style={head()}>
                          <button
                            type="button"
                            title={`Sort by ${name}`}
                            onClick={() => sortBy(index())}
                            style={{
                              all: "unset",
                              cursor: "pointer",
                              width: "100%",
                              display: "flex",
                              "align-items": "center",
                              gap: "6px",
                            }}
                          >
                            <span
                              style={{
                                overflow: "hidden",
                                "text-overflow": "ellipsis",
                                "white-space": "nowrap",
                              }}
                            >
                              {name}
                            </span>
                            <span style={{ color: "var(--color-text-faint)" }}>
                              {sort()?.index === index() ? (sort()?.direction === "asc" ? "↑" : "↓") : ""}
                            </span>
                          </button>
                        </th>
                      )}
                    </For>
                  </tr>
                </thead>
                <tbody>
                  <For each={visible()}>
                    {(row, index) => (
                      <tr>
                        <td style={{ ...cell(), position: "sticky", left: 0, background: "var(--color-bg-subtle)" }}>
                          <span style={{ color: "var(--color-text-faint)" }}>
                            {(page() * PAGE_SIZE + index() + 1).toLocaleString()}
                          </span>
                        </td>
                        <For each={data().columns}>
                          {(_, column) => (
                            <td title={row[column()] ?? ""} style={cell()}>
                              <Show
                                when={(row[column()] ?? "") !== ""}
                                fallback={<span style={{ color: "var(--color-text-faint)" }}>—</span>}
                              >
                                {row[column()]}
                              </Show>
                            </td>
                          )}
                        </For>
                      </tr>
                    )}
                  </For>
                </tbody>
              </table>
            </div>

            <div
              style={{
                height: "38px",
                display: "flex",
                "align-items": "center",
                "justify-content": "center",
                gap: "10px",
                padding: "0 12px",
                border: "0",
                "border-top": "1px solid var(--color-border)",
                background: "var(--color-bg)",
              }}
            >
              <button
                type="button"
                disabled={page() === 0}
                style={pager()}
                onClick={() => setPage((value) => value - 1)}
              >
                ← previous
              </button>
              <span style={{ "font-family": FONT_MONO, "font-size": "9px", color: "var(--color-text-faint)" }}>
                page {page() + 1} / {pages()}
                {data().truncated ? " · preview capped at 5,000 rows" : ""}
              </span>
              <button
                type="button"
                disabled={page() + 1 >= pages()}
                style={pager()}
                onClick={() => setPage((value) => value + 1)}
              >
                next →
              </button>
            </div>
          </>
        )}
      </Show>
    </div>
  )
}

function Histogram(props: { table: DataTable; index: number; onClose: () => void }): JSX.Element {
  const values = () => props.table.rows.map((row) => Number(row[props.index])).filter(Number.isFinite)
  const stats = () => summarizeColumn(props.table, props.index)
  const bars = createMemo(() => {
    const items = values()
    if (!items.length) return []
    const min = Math.min(...items)
    const max = Math.max(...items)
    const width = max - min || 1
    const count = Math.min(24, Math.max(6, Math.ceil(Math.sqrt(items.length))))
    const bins = Array.from({ length: count }, (_, index) => ({
      index,
      count: 0,
      low: min + (index / count) * width,
      high: max === min ? min : min + ((index + 1) / count) * width,
    }))
    for (const value of items) {
      const index = Math.min(count - 1, Math.floor(((value - min) / width) * count))
      const bin = bins[index]
      if (bin) bin.count += 1
    }
    return bins
  })
  const peak = () => Math.max(1, ...bars().map((value) => value.count))

  return (
    <div
      data-slot="table-plot"
      style={{
        padding: "12px 16px 14px",
        border: "0",
        "border-bottom": "1px solid var(--color-border)",
        background: "var(--color-bg)",
      }}
    >
      <div style={{ display: "flex", "align-items": "center", gap: "12px", "margin-bottom": "10px" }}>
        <strong style={{ "font-family": FONT_SANS, "font-size": "11px" }}>
          {props.table.columns[props.index]} distribution
        </strong>
        <span style={metric()}>n {stats().count.toLocaleString()}</span>
        <span style={metric()}>min {number(stats().min)}</span>
        <span style={metric()}>mean {number(stats().mean)}</span>
        <span style={metric()}>max {number(stats().max)}</span>
        <div style={{ flex: 1 }} />
        <button type="button" style={pager()} onClick={props.onClose}>
          close
        </button>
      </div>
      <svg
        viewBox="0 0 720 180"
        role="img"
        aria-label={`${props.table.columns[props.index]} histogram`}
        style={{ width: "100%", height: "180px" }}
      >
        <text x="24" y="12" font-size="10" fill="var(--color-text-muted)">rows</text>
        <text x="22" y="25" text-anchor="end" font-size="10" fill="var(--color-text-muted)">{peak()}</text>
        <text x="22" y="132" text-anchor="end" font-size="10" fill="var(--color-text-muted)">0</text>
        <line x1="24" y1="20" x2="24" y2="132" stroke="var(--color-border-strong)" />
        <line x1="24" y1="132" x2="710" y2="132" stroke="var(--color-border-strong)" />
        <text x="28" y="151" font-size="10" fill="var(--color-text-muted)">{number(stats().min)}</text>
        <text x="702" y="151" text-anchor="end" font-size="10" fill="var(--color-text-muted)">{number(stats().max)}</text>
        <text x="365" y="173" text-anchor="middle" font-size="11" fill="var(--color-text-muted)">{props.table.columns[props.index]}</text>
        <For each={bars()}>
          {(bar, index) => {
            const width = 674 / Math.max(1, bars().length)
            const height = (bar.count / peak()) * 112
            return (
              <rect
                x={28 + index() * width}
                y={132 - height}
                width={Math.max(2, width - 3)}
                height={height}
                rx="2"
                fill="var(--color-text-muted)"
                opacity="0.82"
              >
                <title>{number(bar.low)}–{number(bar.high)}: {bar.count} rows</title>
              </rect>
            )
          }}
        </For>
      </svg>
    </div>
  )
}

function compare(left: string, right: string, type: string) {
  if (!left && right) return 1
  if (left && !right) return -1
  if (type === "number") return Number(left) - Number(right)
  if (type === "date") return Date.parse(left) - Date.parse(right)
  if (type === "boolean") return Number(/^true$/i.test(left)) - Number(/^true$/i.test(right))
  return left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" })
}

const number = (value: number | undefined) =>
  value === undefined ? "—" : new Intl.NumberFormat(undefined, { maximumSignificantDigits: 5 }).format(value)

function input(): JSX.CSSProperties {
  return {
    width: "min(280px, 32vw)",
    height: "28px",
    padding: "0 9px",
    border: "1px solid var(--color-border)",
    "border-radius": "5px",
    outline: "none",
    background: "var(--color-bg-subtle)",
    color: "var(--color-text)",
    "font-family": FONT_SANS,
    "font-size": "11px",
  }
}

function button(active = false): JSX.CSSProperties {
  return {
    cursor: "pointer",
    height: "28px",
    padding: "0 9px",
    border: "1px solid var(--color-border)",
    "border-radius": "5px",
    background: active ? "var(--color-text)" : "var(--color-bg)",
    color: active ? "var(--color-bg)" : "var(--color-text-muted)",
    "font-family": FONT_MONO,
    "font-size": "9px",
    "font-weight": 600,
  }
}

function select(): JSX.CSSProperties {
  return {
    height: "28px",
    "max-width": "150px",
    padding: "0 24px 0 8px",
    border: "1px solid var(--color-border)",
    "border-radius": "5px",
    background: "var(--color-bg)",
    color: "var(--color-text-muted)",
    "font-family": FONT_MONO,
    "font-size": "9px",
  }
}

function head(): JSX.CSSProperties {
  return {
    position: "sticky",
    top: 0,
    "z-index": 2,
    height: "34px",
    "min-width": "130px",
    "max-width": "260px",
    padding: "0 10px",
    "text-align": "left",
    "font-weight": 600,
    color: "var(--color-text-muted)",
    background: "var(--color-bg)",
    "border-right": "1px solid var(--color-border)",
    "border-bottom": "1px solid var(--color-border-strong)",
  }
}

function cell(): JSX.CSSProperties {
  return {
    height: "31px",
    "max-width": "320px",
    padding: "0 10px",
    overflow: "hidden",
    "text-overflow": "ellipsis",
    "white-space": "nowrap",
    color: "var(--color-text-muted)",
    background: "var(--color-bg)",
    "border-right": "1px solid var(--color-border)",
    "border-bottom": "1px solid var(--color-border)",
  }
}

function pager(): JSX.CSSProperties {
  return {
    all: "unset",
    cursor: "pointer",
    padding: "4px 7px",
    "border-radius": "4px",
    "font-family": FONT_MONO,
    "font-size": "9px",
    color: "var(--color-text-faint)",
  }
}

function metric(): JSX.CSSProperties {
  return {
    "font-family": FONT_MONO,
    "font-size": "9px",
    color: "var(--color-text-faint)",
  }
}

function empty(): JSX.CSSProperties {
  return {
    flex: 1,
    display: "flex",
    "flex-direction": "column",
    "align-items": "center",
    "justify-content": "center",
    gap: "9px",
    padding: "32px",
    color: "var(--color-text)",
  }
}

export default DataTableView
