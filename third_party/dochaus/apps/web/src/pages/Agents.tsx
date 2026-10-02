import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { deleteAgent, listAgents, setAgentEnabled, type AgentRecord } from "../api/ingest"
import { useToast } from "../components/Toast"
import ChatPanel from "../components/ChatPanel"
import { DocMarkdown } from "../components/Markdown"
import { AGENT_BUILDER } from "../agents"

// The firm's specialist subagents: the repo-shipped reviewers (read-only) plus
// the custom ones composed conversationally by the agent-builder. A custom
// specialist analyzes a matter's documents for one concern and reports cited
// findings; it becomes a workflow pipeline step the moment it is created.
// Beside the list the Agent Builder chat composes and maintains specialists —
// it runs in the agent library directory (there is no matter to scope to),
// pinned to the agent-builder agent. Deleting an agent a workflow still uses is
// refused by the registry, with the workflows named in the error.
export default function Agents() {
  const [params, setParams] = useSearchParams()
  const session = params.get("session") ?? undefined
  const [dir, setDir] = useState<string>()
  const [agents, setAgents] = useState<AgentRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [confirmName, setConfirmName] = useState<string | null>(null)
  const [viewing, setViewing] = useState<AgentRecord>()
  const createdRef = useRef<string | undefined>(undefined)
  const toast = useToast()

  function refresh() {
    return listAgents().then((res) => {
      setDir(res.dir)
      setAgents(res.agents)
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

  async function onDelete(a: AgentRecord) {
    setConfirmName(null)
    try {
      await deleteAgent(a.name)
      setAgents((prev) => prev.filter((x) => x.name !== a.name))
      toast("success", `Deleted agent "${a.label}".`)
    } catch (e) {
      toast("error", e instanceof Error ? e.message : `Could not delete ${a.name}.`)
    }
  }

  // Flip the row straight away so the switch feels instant; revert on failure.
  async function onToggle(a: AgentRecord) {
    const enabled = !a.enabled
    setAgents((prev) => prev.map((x) => (x.name === a.name ? { ...x, enabled } : x)))
    try {
      await setAgentEnabled(a.name, enabled)
    } catch (e) {
      setAgents((prev) => prev.map((x) => (x.name === a.name ? { ...x, enabled: a.enabled } : x)))
      toast("error", e instanceof Error ? e.message : `Could not update ${a.name}.`)
    }
  }

  const visible = [...agents].sort((a, b) => Number(b.builtin) - Number(a.builtin) || a.name.localeCompare(b.name))

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Agents</h1>
          <p className="page-sub">
            Specialist reviewers that analyze a matter's documents for one concern. Compose them into pipelines from
            the Workflows page.
          </p>
        </div>
      </header>

      <div className="card">
        {loading ? (
          <div className="skeleton-list">
            <div className="skeleton-row" />
            <div className="skeleton-row" />
            <div className="skeleton-row" />
          </div>
        ) : visible.length === 0 ? (
          <div className="empty-state">
            <svg className="empty-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="5" y="8" width="14" height="11" rx="2" />
              <path d="M12 8V5" />
              <circle cx="12" cy="4" r="1" />
              <path d="M9 13h.01M15 13h.01" />
              <path d="M5 12H3M21 12h-2" />
            </svg>
            <h3>No agents yet</h3>
            <p>Describe a specialist reviewer to the agent builder to add one.</p>
          </div>
        ) : (
          <ul className="matter-list">
            {visible.map((a) => (
              <li
                key={a.name}
                className="list-row list-row-clickable"
                title="View this agent"
                onClick={() => setViewing(a)}
              >
                <div className="list-row-main">
                  <span className="list-row-title">
                    {a.label}
                    {a.builtin && <span className="badge badge-quiet">Built-in</span>}
                  </span>
                  <span className="list-row-meta">
                    <span className="list-row-desc">{a.description}</span>
                  </span>
                </div>
                <div className="list-row-actions">
                  <button
                    role="switch"
                    aria-checked={a.enabled}
                    aria-label={a.name}
                    className={a.enabled ? "switch on" : "switch"}
                    title={a.enabled ? "Disable agent — it leaves the workflow roster" : "Enable agent"}
                    onClick={(e) => {
                      e.stopPropagation()
                      onToggle(a)
                    }}
                  />
                  <button
                    className="icon-btn"
                    title="View agent instructions"
                    onClick={(e) => {
                      e.stopPropagation()
                      setViewing(a)
                    }}
                  >
                    View
                  </button>
                  {!a.builtin &&
                    (confirmName === a.name ? (
                      <button
                        className="icon-btn danger"
                        title="Confirm delete"
                        onClick={(e) => {
                          e.stopPropagation()
                          onDelete(a)
                        }}
                      >
                        Confirm
                      </button>
                    ) : (
                      <button
                        className="icon-btn"
                        title="Delete agent"
                        onClick={(e) => {
                          e.stopPropagation()
                          setConfirmName(a.name)
                        }}
                      >
                        Delete
                      </button>
                    ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {dir && (
        <ChatPanel
          key={session ?? "new"}
          directory={dir}
          sessionID={session}
          created={createdRef.current === session}
          agent={AGENT_BUILDER.name}
          available={new Set([AGENT_BUILDER.name])}
          pinned={AGENT_BUILDER}
          title="Ask the agent builder"
          emptyHint="Describe a specialist reviewer to add to the firm's agents, or ask what already exists. New specialists become workflow steps immediately."
          starters={[
            "What agents do we have?",
            "Create a specialist that reviews IP ownership and assignment clauses.",
            "Create a specialist that checks data privacy and GDPR exposure.",
          ]}
          composerPlaceholder="e.g. Create a specialist for change-of-control provisions"
          onAgentChange={() => {}}
          onSessionCreated={(sid) => {
            createdRef.current = sid
            setParams({ session: sid }, { replace: true })
          }}
          onViewDocument={() => {}}
          onDocumentsChanged={refresh}
        />
      )}

      {viewing && (
        <div className="viewer-overlay" onClick={() => setViewing(undefined)}>
          <div className="picker-panel doc-panel" onClick={(e) => e.stopPropagation()}>
            <div className="viewer-bar">
              <span className="viewer-title">
                {viewing.label}
                {viewing.builtin ? " (built-in)" : ""}
              </span>
              <button onClick={() => setViewing(undefined)}>Close</button>
            </div>
            <div className="picker-body">
              {viewing.description && <p className="muted">{viewing.description}</p>}
              <DocMarkdown>{viewing.instructions}</DocMarkdown>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
