import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { deleteWorkflow, listWorkflows, type CustomWorkflow, type Matter } from "../api/ingest"
import { useToast } from "../components/Toast"
import ChatPanel from "../components/ChatPanel"
import MatterPicker from "../components/MatterPicker"
import { DocMarkdown } from "../components/Markdown"
import { WORKFLOW_BUILDER, WORKFLOWS, type WorkflowMeta } from "../agents"

// The firm's workflow library: built-in multi-agent review routines plus custom
// workflows created conversationally by the workflow-builder agent. Built-ins are
// defined in agents.ts (prompt encoded there); custom workflows are persisted by
// the ingest service and returned by GET /workflows. Beside the list the Workflow
// Builder chat composes and maintains custom workflows — it runs in the library
// directory (there is no matter to scope to), pinned to the workflow-builder agent.
// "Use" opens a matter picker; picking a matter navigates to its chat with the
// workflow agent pinned and the launch prompt prefilled — the lawyer reviews and
// sends, nothing auto-runs.
export default function Workflows() {
  const [params, setParams] = useSearchParams()
  const session = params.get("session") ?? undefined
  const [dir, setDir] = useState<string>()
  const [custom, setCustom] = useState<CustomWorkflow[]>([])
  const [loading, setLoading] = useState(true)
  const [confirmName, setConfirmName] = useState<string | null>(null)
  // The workflow being launched — either a built-in WorkflowMeta or a custom one.
  const [using, setUsing] = useState<WorkflowMeta | CustomWorkflow>()
  const [viewing, setViewing] = useState<WorkflowMeta | CustomWorkflow>()
  const navigate = useNavigate()
  const createdRef = useRef<string | undefined>(undefined)
  const toast = useToast()

  function refresh() {
    return listWorkflows().then((res) => {
      setDir(res.dir)
      setCustom(res.workflows)
    })
  }

  useEffect(() => {
    refresh().finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!confirmName) return
    const dismiss = () => setConfirmName(null)
    window.addEventListener("click", dismiss)
    return () => window.removeEventListener("click", dismiss)
  }, [confirmName])

  async function onDelete(wf: CustomWorkflow) {
    setConfirmName(null)
    await deleteWorkflow(wf.name)
    setCustom((prev) => prev.filter((x) => x.name !== wf.name))
    toast("success", `Deleted workflow "${wf.label}".`)
  }

  // Picking a matter lands in its chat with the workflow agent pinned and the
  // launch prompt prefilled — the lawyer reviews and sends; nothing auto-runs.
  function useWorkflow(wf: WorkflowMeta | CustomWorkflow, m: Matter) {
    setUsing(undefined)
    navigate(
      `/matter/${m.id}?view=chat&agent=${encodeURIComponent(wf.name)}&prompt=${encodeURIComponent(wf.prompt)}`,
    )
  }

  const sortedCustom = [...custom].sort((a, b) => a.label.localeCompare(b.label))

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Workflows</h1>
          <p className="page-sub">Repeatable multi-agent review routines.</p>
        </div>
      </header>

      <div className="card">
        {loading ? (
          <div className="skeleton-list">
            <div className="skeleton-row" />
            <div className="skeleton-row" />
            <div className="skeleton-row" />
          </div>
        ) : (
          <ul className="matter-list">
            {WORKFLOWS.map((wf) => (
              <li
                key={wf.name}
                className="list-row list-row-clickable"
                title="View what this workflow does"
                onClick={() => setViewing(wf)}
              >
                <div className="list-row-main">
                  <span className="list-row-title">
                    {wf.label}
                    <span className="badge badge-quiet">Built-in</span>
                  </span>
                  <span className="list-row-meta">
                    <span className="list-row-desc">{wf.description}</span>
                  </span>
                </div>
                <div className="list-row-actions">
                  <button
                    className="icon-btn"
                    title="Launch this workflow in a matter"
                    onClick={(e) => {
                      e.stopPropagation()
                      setUsing(wf)
                    }}
                  >
                    Use
                  </button>
                  <button
                    className="icon-btn"
                    title="View what this workflow does"
                    onClick={(e) => {
                      e.stopPropagation()
                      setViewing(wf)
                    }}
                  >
                    View
                  </button>
                </div>
              </li>
            ))}
            {sortedCustom.map((wf) => {
              const stepSummary = wf.steps.map((s) => s.agent).join(" → ")
              return (
                <li
                  key={wf.name}
                  className="list-row list-row-clickable"
                  title="View what this workflow does"
                  onClick={() => setViewing(wf)}
                >
                  <div className="list-row-main">
                    <span className="list-row-title">{wf.label}</span>
                    <span className="list-row-meta">
                      <span className="list-row-desc">{wf.description}</span>
                      {stepSummary && <span className="list-row-date">{stepSummary}</span>}
                    </span>
                  </div>
                  <div className="list-row-actions">
                    <button
                      className="icon-btn"
                      title="Launch this workflow in a matter"
                      onClick={(e) => {
                        e.stopPropagation()
                        setUsing(wf)
                      }}
                    >
                      Use
                    </button>
                    <button
                      className="icon-btn"
                      title="View what this workflow does"
                      onClick={(e) => {
                        e.stopPropagation()
                        setViewing(wf)
                      }}
                    >
                      View
                    </button>
                    {confirmName === wf.name ? (
                      <button
                        className="icon-btn danger"
                        title="Confirm delete"
                        onClick={(e) => {
                          e.stopPropagation()
                          onDelete(wf)
                        }}
                      >
                        Confirm
                      </button>
                    ) : (
                      <button
                        className="icon-btn"
                        title="Delete workflow"
                        onClick={(e) => {
                          e.stopPropagation()
                          setConfirmName(wf.name)
                        }}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {dir && (
        <ChatPanel
          key={session ?? "new"}
          directory={dir}
          sessionID={session}
          created={createdRef.current === session}
          agent={WORKFLOW_BUILDER.name}
          available={new Set([WORKFLOW_BUILDER.name])}
          pinned={WORKFLOW_BUILDER}
          title="Ask the workflow builder"
          emptyHint="Describe a review process to turn into a repeatable workflow, or ask what already exists. Workflows chain the firm's specialist subagents in order."
          starters={[
            "What workflows do we have?",
            "Create a workflow that checks documents against our playbook, challenges the findings, then summarizes.",
            "Add a final summarize step to an existing workflow.",
          ]}
          composerPlaceholder="e.g. Create a diligence sweep that reviews indemnities then summarizes"
          onAgentChange={() => {}}
          onSessionCreated={(sid) => {
            createdRef.current = sid
            setParams({ session: sid }, { replace: true })
          }}
          onViewDocument={() => {}}
          onDocumentsChanged={refresh}
        />
      )}

      {using && (
        <MatterPicker
          title={`Use "${using.label}" in a matter`}
          onPick={(m) => useWorkflow(using, m)}
          onClose={() => setUsing(undefined)}
        />
      )}

      {viewing && (
        <div className="viewer-overlay" onClick={() => setViewing(undefined)}>
          <div className="picker-panel doc-panel" onClick={(e) => e.stopPropagation()}>
            <div className="viewer-bar">
              <span className="viewer-title">
                {viewing.label}
                {"created_at" in viewing ? "" : " (built-in)"}
              </span>
              <button onClick={() => setViewing(undefined)}>Close</button>
            </div>
            <div className="picker-body">
              <p className="muted">{viewing.description}</p>
              <p className="muted">
                {viewing.scope === "matter"
                  ? "Runs across every document in the matter, as its own conversation."
                  : "Runs on the document conversation you are already in."}
              </p>
              <DocMarkdown>
                {[
                  viewing.steps?.length
                    ? "**Pipeline**\n\n" +
                      viewing.steps.map((s, i) => `${i + 1}. **${s.agent}** — ${s.instructions}`).join("\n")
                    : "",
                  `**Launch prompt**\n\n> ${viewing.prompt}`,
                ]
                  .filter(Boolean)
                  .join("\n\n")}
              </DocMarkdown>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
