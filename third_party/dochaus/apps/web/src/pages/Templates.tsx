import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import {
  deleteTemplate,
  listTemplates,
  updateTemplateDescription,
  uploadTemplate,
  type Matter,
  type Template,
} from "../api/ingest"
import { useToast } from "../components/Toast"
import TemplateViewer from "../components/TemplateViewer"
import MatterPicker from "../components/MatterPicker"
import ChatPanel from "../components/ChatPanel"
import { TEMPLATE_BUILDER } from "../agents"
import { useLanguage } from "../i18n"
import { listSessions, matterClient } from "../api/opencode"

// The firm's global template library: the drafting bases shared across every
// matter. A card lists the templates with an editable one-line description and a
// placeholder count, a View button that opens the template in a read-only viewer,
// an inline Confirm delete, and a .docx-only dropzone to add one. Beside it the
// Template Builder chat composes and maintains templates conversationally — it
// runs in the library directory (there is no matter to scope to), pinned to the
// template-builder agent. Templates are also created by the matter drafter; this
// page manages the uploaded and seeded ones directly.
export default function Templates() {
  const { language } = useLanguage()
  const [params, setParams] = useSearchParams()
  const session = params.get("session") ?? undefined
  const [dir, setDir] = useState<string>()
  const [sessions, setSessions] = useState<Array<{ id: string; title: string }>>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [confirmName, setConfirmName] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [viewing, setViewing] = useState<Template>()
  // "Use" flow: the template being assembled into a matter the lawyer picks.
  const [using, setUsing] = useState<Template>()
  const navigate = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  // The session id the composer just minted, so the remount that follows the first
  // send keeps the cursor seated (same pattern as MatterDetail).
  const createdRef = useRef<string | undefined>(undefined)
  const toast = useToast()

  function refreshSessions() {
    if (!dir) return
    listSessions(matterClient(dir)).then((items) => {
      setSessions(items.filter((item) => !item.parentID).sort((a, b) => b.time.updated - a.time.updated).slice(0, 20))
    })
  }

  useEffect(refreshSessions, [dir])

  function refresh() {
    return listTemplates().then((res) => {
      setDir(res.dir)
      setTemplates(res.templates)
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
    const docx = files.filter((f) => f.name.toLowerCase().endsWith(".docx"))
    if (!docx.length) {
      toast("error", "Templates must be .docx files.")
      return
    }
    setBusy(true)
    for (const file of docx) {
      const template = await uploadTemplate(file)
      setTemplates((prev) => [...prev.filter((t) => t.name !== template.name), template])
      toast("success", `Added template "${template.name}".`)
    }
    setBusy(false)
  }

  async function onDelete(t: Template) {
    setConfirmName(null)
    await deleteTemplate(t.name)
    setTemplates((prev) => prev.filter((x) => x.name !== t.name))
    toast("success", `Deleted template "${t.name}".`)
  }

  async function saveDescription(t: Template, description: string) {
    setEditing(null)
    if (description === t.description) return
    try {
      const updated = await updateTemplateDescription(t.name, description)
      setTemplates((prev) => prev.map((x) => (x.name === t.name ? { ...x, description: updated.description } : x)))
      toast("success", `Updated description for "${t.name}".`)
    } catch {
      toast("error", `Could not update description for "${t.name}".`)
    }
  }

  // Picking a matter lands in its chat with the drafter pinned and the assembly
  // prompt prefilled — the lawyer reviews and sends; nothing auto-runs.
  function useTemplate(t: Template, m: Matter) {
    setUsing(undefined)
    const prompt = language === "es"
      ? `Redacta un documento nuevo a partir de la plantilla "${t.name}". Recopila primero los datos disponibles en los documentos de este expediente y en nuestra conversación; después pregúntame por las condiciones restantes y las cláusulas opcionales antes de componerlo.`
      : `Draft a new document from the template "${t.name}". Gather what you can from this matter's documents and our conversation first, then interview me for the remaining terms and any optional clauses before assembling it.`
    navigate(`/matter/${m.id}?view=chat&agent=drafter&prompt=${encodeURIComponent(prompt)}`)
  }

  const visible = [...templates].sort((a, b) => a.name.localeCompare(b.name))

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Templates</h1>
          <p className="page-sub">Drafting bases shared across every matter.</p>
        </div>
      </header>

      <div className="card">
        <h2>Add template</h2>
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
          {busy ? "Working..." : "Drop a .docx template here, or click to choose a file."}
        </div>
        <input
          ref={input}
          type="file"
          accept=".docx"
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
        ) : templates.length === 0 ? (
          <div className="empty-state">
            <svg className="empty-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <path d="M8 13h8M8 17h5" />
            </svg>
            <h3>No templates yet</h3>
            <p>Upload a DOCX to use as a drafting base.</p>
          </div>
        ) : (
          <ul className="matter-list">
            {visible.map((t) => {
              const optional = t.placeholders.filter((p) => p.text.startsWith("[optional:")).length
              const fills = t.placeholders.length - optional
              return (
                <li
                  key={t.name}
                  className="list-row list-row-clickable"
                  title="View template"
                  onClick={() => setViewing(t)}
                >
                  <div className="list-row-main">
                    <span className="list-row-title">{t.name}</span>
                    <span className="list-row-meta">
                      {editing === t.name ? (
                        <input
                          className="template-desc-input"
                          autoFocus
                          defaultValue={t.description}
                          placeholder="Add description"
                          onClick={(e) => e.stopPropagation()}
                          onBlur={(e) => saveDescription(t, e.target.value.trim())}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") e.currentTarget.blur()
                            if (e.key === "Escape") setEditing(null)
                          }}
                        />
                      ) : (
                        <span
                          className="list-row-desc template-desc"
                          title="Click to edit description"
                          onClick={(e) => {
                            e.stopPropagation()
                            setEditing(t.name)
                          }}
                        >
                          {t.description || "Add description"}
                        </span>
                      )}
                      <span className="list-row-date">
                        {fills} placeholder{fills === 1 ? "" : "s"}
                        {optional > 0 && `, ${optional} optional clause${optional === 1 ? "" : "s"}`}
                      </span>
                    </span>
                  </div>
                  <div className="list-row-actions">
                    <button
                      className="icon-btn"
                      title="Draft a document from this template into a matter"
                      onClick={(e) => {
                        e.stopPropagation()
                        setUsing(t)
                      }}
                    >
                      Use
                    </button>
                    <button
                      className="icon-btn"
                      title="View template"
                      onClick={(e) => {
                        e.stopPropagation()
                        setViewing(t)
                      }}
                    >
                      View
                    </button>
                    {confirmName === t.name ? (
                      <button
                        className="icon-btn danger"
                        title="Confirm delete"
                        onClick={(e) => {
                          e.stopPropagation()
                          onDelete(t)
                        }}
                      >
                        Confirm
                      </button>
                    ) : (
                      <button
                        className="icon-btn"
                        title="Delete template"
                        onClick={(e) => {
                          e.stopPropagation()
                          setConfirmName(t.name)
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
        <>
        {sessions.length > 0 && <nav aria-label={language === "es" ? "Sesiones de la biblioteca de plantillas" : "Template library sessions"} className="card">
          <h2>{language === "es" ? "Sesiones de la biblioteca" : "Library sessions"}</h2>
          {sessions.map((item) => <div key={item.id}>
            <button style={{ whiteSpace: "normal", textAlign: "left", maxWidth: "100%", marginBottom: 8 }} onClick={() => setParams({ session: item.id })}>{item.title}</button>
          </div>)}
        </nav>}
        <ChatPanel
          key={session ?? "new"}
          directory={dir}
          sessionID={session}
          created={createdRef.current === session}
          agent={TEMPLATE_BUILDER.name}
          available={new Set([TEMPLATE_BUILDER.name])}
          pinned={TEMPLATE_BUILDER}
          title="Ask the template library"
          emptyHint="Describe a template to add to the firm's library, or ask what already exists. Templates carry [insert ...] placeholders instead of client details."
          starters={[
            "What templates do we have?",
            "Create a template for a consulting agreement.",
            "Create a template for an employment offer letter.",
          ]}
          composerPlaceholder="e.g. Create a template for a mutual NDA"
          onAgentChange={() => {}}
          onSessionStarted={refreshSessions}
          onSessionCreated={(sid) => {
            createdRef.current = sid
            setParams({ session: sid }, { replace: true })
          }}
          onViewDocument={() => {}}
          onDocumentsChanged={refresh}
        />
        </>
      )}

      {viewing && (
        <TemplateViewer name={viewing.name} placeholders={viewing.placeholders} onClose={() => setViewing(undefined)} />
      )}

      {using && (
        <MatterPicker
          title={language === "es" ? `Usar "${using.name}" en un expediente` : `Use "${using.name}" in a matter`}
          onPick={(m) => useTemplate(using, m)}
          onClose={() => setUsing(undefined)}
        />
      )}
    </>
  )
}
