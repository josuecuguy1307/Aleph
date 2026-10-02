import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { deleteSkill, importSkill, listSkills, setSkillEnabled, type Skill } from "../api/ingest"
import { useToast } from "../components/Toast"
import ChatPanel from "../components/ChatPanel"
import { DocMarkdown } from "../components/Markdown"
import { SKILL_BUILDER } from "../agents"

// The firm's skill library: reference knowledge (clause standards, checklists,
// drafting guidance) the specialist agents load on demand. Repo-shipped skills
// are listed read-only; custom ones live in WORKSPACE_ROOT/.skills, owned by the
// ingest service. Beside the list the Skill Builder chat composes and maintains
// skills conversationally — it runs in the library directory (there is no matter
// to scope to), pinned to the skill-builder agent. A dropzone imports an existing
// firm document (.md keeps its frontmatter; .docx/.pdf/.txt arrive as raw text
// for the builder to refine).
export default function Skills() {
  const [params, setParams] = useSearchParams()
  const session = params.get("session") ?? undefined
  const [dir, setDir] = useState<string>()
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [confirmName, setConfirmName] = useState<string | null>(null)
  const [viewing, setViewing] = useState<Skill>()
  const input = useRef<HTMLInputElement>(null)
  const createdRef = useRef<string | undefined>(undefined)
  const toast = useToast()

  function refresh() {
    return listSkills().then((res) => {
      setDir(res.dir)
      setSkills(res.skills)
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

  async function onFiles(files: File[]) {
    const importable = files.filter((f) => /\.(md|txt|docx|pdf)$/i.test(f.name))
    if (!importable.length) {
      toast("error", "Skills import .md, .txt, .docx, or .pdf files.")
      return
    }
    setBusy(true)
    for (const file of importable) {
      try {
        const skill = await importSkill(file)
        setSkills((prev) => [...prev.filter((s) => s.name !== skill.name), skill])
        toast("success", `Imported skill "${skill.name}". Ask the skill builder to refine it.`)
      } catch (e) {
        toast("error", e instanceof Error ? e.message : `Could not import ${file.name}.`)
      }
    }
    setBusy(false)
  }

  async function onDelete(s: Skill) {
    setConfirmName(null)
    try {
      await deleteSkill(s.name)
      setSkills((prev) => prev.filter((x) => x.name !== s.name))
      toast("success", `Deleted skill "${s.name}".`)
    } catch (e) {
      toast("error", e instanceof Error ? e.message : `Could not delete ${s.name}.`)
    }
  }

  // Flip the row straight away so the switch feels instant; revert on failure.
  async function onToggle(s: Skill) {
    const enabled = !s.enabled
    setSkills((prev) => prev.map((x) => (x.name === s.name ? { ...x, enabled } : x)))
    try {
      await setSkillEnabled(s.name, enabled)
    } catch (e) {
      setSkills((prev) => prev.map((x) => (x.name === s.name ? { ...x, enabled: s.enabled } : x)))
      toast("error", e instanceof Error ? e.message : `Could not update ${s.name}.`)
    }
  }

  const visible = [...skills].sort((a, b) => Number(b.builtin) - Number(a.builtin) || a.name.localeCompare(b.name))

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Skills</h1>
          <p className="page-sub">Reference playbooks the assistants can load.</p>
        </div>
      </header>

      <div className="card">
        <h2>Import skill</h2>
        <div
          className="dropzone"
          onClick={() => input.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            const files = Array.from(e.dataTransfer.files)
            if (files.length) onFiles(files)
          }}
        >
          {busy
            ? "Working..."
            : "Drop a firm checklist or guide here (.md, .txt, .docx, .pdf), or click to choose a file."}
        </div>
        <input
          ref={input}
          type="file"
          accept=".md,.txt,.docx,.pdf"
          multiple
          hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? [])
            if (files.length) onFiles(files)
            e.target.value = ""
          }}
        />
      </div>

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
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
            <h3>No skills yet</h3>
            <p>Import one above, or describe one to the skill builder.</p>
          </div>
        ) : (
          <ul className="matter-list">
            {visible.map((s) => (
              <li
                key={s.name}
                className="list-row list-row-clickable"
                title="View this skill"
                onClick={() => setViewing(s)}
              >
                <div className="list-row-main">
                  <span className="list-row-title">
                    {s.name}
                    {s.builtin && <span className="badge badge-quiet">Built-in</span>}
                  </span>
                  <span className="list-row-meta">
                    <span className="list-row-desc">{s.description || "No description yet"}</span>
                  </span>
                </div>
                <div className="list-row-actions">
                  <button
                    role="switch"
                    aria-checked={s.enabled}
                    aria-label={s.name}
                    className={s.enabled ? "switch on" : "switch"}
                    title={s.enabled ? "Disable skill — agents stop loading it" : "Enable skill"}
                    onClick={(e) => {
                      e.stopPropagation()
                      onToggle(s)
                    }}
                  />
                  <button
                    className="icon-btn"
                    title="View skill"
                    onClick={(e) => {
                      e.stopPropagation()
                      setViewing(s)
                    }}
                  >
                    View
                  </button>
                  {!s.builtin &&
                    (confirmName === s.name ? (
                      <button
                        className="icon-btn danger"
                        title="Confirm delete"
                        onClick={(e) => {
                          e.stopPropagation()
                          onDelete(s)
                        }}
                      >
                        Confirm
                      </button>
                    ) : (
                      <button
                        className="icon-btn"
                        title="Delete skill"
                        onClick={(e) => {
                          e.stopPropagation()
                          setConfirmName(s.name)
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
          agent={SKILL_BUILDER.name}
          available={new Set([SKILL_BUILDER.name])}
          pinned={SKILL_BUILDER}
          title="Ask the skill builder"
          emptyHint="Describe firm knowledge to turn into a skill, or ask what already exists. The specialist agents load skills automatically when relevant."
          starters={[
            "What skills do we have?",
            "Create a skill with our positions on limitation of liability.",
            "Refine the skill I just imported.",
          ]}
          composerPlaceholder="e.g. Create a skill for our standard confidentiality positions"
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
                {viewing.name}
                {viewing.builtin ? " (built-in)" : ""}
              </span>
              <button onClick={() => setViewing(undefined)}>Close</button>
            </div>
            <div className="picker-body">
              {viewing.description && <p className="muted">{viewing.description}</p>}
              <DocMarkdown>{viewing.content}</DocMarkdown>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
