import { useCallback, useEffect, useRef, useState } from "react"
import { useParams, useSearchParams } from "react-router-dom"
import { getMatter, listJurisdictions, listPlaybooks, listWorkflows, renameMatter, type CustomWorkflow, type Jurisdiction, type MatterDetail as Detail, type Playbook } from "../api/ingest"
import { disposeInstance, listAgents, matterClient } from "../api/opencode"
import { AUTO, WORKFLOWS } from "../agents"
import DocumentUpload from "../components/DocumentUpload"
import DocumentViewer from "../components/DocumentViewer"
import ChatPanel from "../components/ChatPanel"
import ReviewGrid from "../components/ReviewGrid"
import JurisdictionSelect from "../components/JurisdictionSelect"
import { useLanguage } from "../i18n"

type Agent = { name: string; description?: string; mode?: string; hidden?: boolean }

// One matter, three surfaces, switched by the `view` query param from the
// sidebar: chat | review | documents. The content is a single canvas whose width
// flexes to the surface — the grid and the documents manager run full-width,
// while chat keeps a documents rail for reference. Default surface is chat.
// Workflows are not a surface: they run as seeded chat sessions in the chat view.
export default function MatterDetail({ onSessionsChanged }: { onSessionsChanged: () => void }) {
  const { language } = useLanguage()
  const { id } = useParams<{ id: string }>()
  const [params, setParams] = useSearchParams()
  const view = params.get("view") ?? "chat"
  const session = params.get("session") ?? undefined
  const [matter, setMatter] = useState<Detail>()
  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>([])
  const [custom, setCustom] = useState<CustomWorkflow[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [agent, setAgent] = useState(AUTO)
  const [viewing, setViewing] = useState<string>()
  // The redline proposal to scroll to when the viewer opens, set when the user
  // follows a chat redline preview's "View in document" link (undefined otherwise).
  const [focusRedline, setFocusRedline] = useState<number>()
  const [docsOpen, setDocsOpen] = useState(() => localStorage.getItem("dh.docs") !== "0")
  // The title-area fields are inline-click-editable: clicking one swaps its label
  // for an input (or, for jurisdictions, the shared multi-select) seeded with the
  // current value. Each commit persists the whole matter via the ingest service
  // and updates in place. Reference and title each track their own edit flag/draft.
  const [renaming, setRenaming] = useState(false)
  const [draftTitle, setDraftTitle] = useState("")
  const [editingRef, setEditingRef] = useState(false)
  const [draftRef, setDraftRef] = useState("")
  // The session id the composer just minted. The first send flips the `session`
  // param, remounting ChatPanel under the new id; this lets that remount know it
  // is the same composer (not a rail reopen) so it keeps the cursor seated.
  const createdRef = useRef<string | undefined>(undefined)
  // [rediseño · Legal · la barrita] EL CLIP DEL COMPOSER Y EL RAIL DE DOCUMENTOS COMPARTEN
  // PUERTA. El rail registra acá su `input.current.click()` —el mismo que ya disparan su
  // zona de arrastre y su botón— y el composer lo usa para el clip. Un solo camino de
  // subida: el que ya existía.
  const abrirArchivos = useRef<() => void>(() => {})
  const registrarAbrir = useCallback((abrir: () => void) => {
    abrirArchivos.current = abrir
  }, [])

  useEffect(() => {
    localStorage.setItem("dh.docs", docsOpen ? "1" : "0")
  }, [docsOpen])

  useEffect(() => {
    listPlaybooks().then(setPlaybooks)
    listJurisdictions().then(setJurisdictions)
  }, [])

  function refresh() {
    if (id) getMatter(id).then(setMatter)
  }

  useEffect(refresh, [id])

  useEffect(() => {
    if (!matter) return
    const dir = matter.dir
    let cancelled = false
    // Right after navigating back into a matter the engine can be briefly busy and
    // app.agents() rejects. The assistant and workflow pickers hide when they have
    // no agents to offer (see ModelSelector/WorkflowLauncher), so a single failed
    // call would silently drop the composer controls for the whole mount. Retry
    // until it answers rather than leaving them missing.
    async function load() {
      // Fetch custom workflows here so the self-heal check below has the registry.
      const wfRes = await listWorkflows().catch(() => ({ workflows: [] as CustomWorkflow[] }))
      if (cancelled) return
      setCustom(wfRes.workflows)
      const customNames = new Set(wfRes.workflows.map((w) => w.name))
      // A warm instance only rescans the agent dir after dispose; edits to an
      // existing workflow's .md don't change names, so they're picked up on the
      // instance's natural next rebuild. Only missing names need a dispose.
      let healed = false
      while (!cancelled) {
        const list = await listAgents(matterClient(dir)).catch(() => undefined)
        if (cancelled) return
        if (list) {
          const agentNames = new Set((list as Agent[]).map((a) => a.name))
          // If a workflow's agent is missing from the live instance, the instance
          // predates the workflow — dispose once so it rescans on next wake.
          if (!healed && [...customNames].some((n) => !agentNames.has(n))) {
            healed = true
            await disposeInstance(matterClient(dir))
            continue
          }
          setAgents(list as Agent[])
          // A new chat opens on Auto (a pseudo-assistant always offered, so no
          // availability check); an existing session restores the agent it last
          // used (see ChatPanel's load effect), so don't force Auto here. When a
          // surface deep-links in with an `agent` param (e.g. "Save as template"
          // pinning the drafter), honour it if it is a real assistant — this must
          // live in this effect or the unconditional setAgent(AUTO) clobbers it.
          if (!session) {
            const pinned = params.get("agent")
            setAgent(pinned && (list as Agent[]).some((a) => a.name === pinned) ? pinned : AUTO)
          }
          return
        }
        await new Promise((resolve) => setTimeout(resolve, 1000))
      }
    }
    load()
    return () => {
      cancelled = true
    }
    // Re-run when the deep-linked agent param changes (e.g. "Save as template"
    // pins the drafter while already in the matter) so the pin is honoured even
    // though `matter` is unchanged.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matter, params.get("agent")])

  if (!matter)
    return (
      <div className="skeleton-list">
        <div className="skeleton-line w-40" />
        <div className="skeleton-row" />
      </div>
    )

  const available = new Set(agents.map((a) => a.name))
  const workflows = [...WORKFLOWS, ...custom]

  // One persist path for every title-area field: merge the changed fields over the
  // current matter, write the whole record, and reflect what came back. Sessions
  // refresh too so the sidebar/picker pick up a renamed or re-referenced matter.
  async function patch(fields: Partial<Pick<Detail, "title" | "reference" | "jurisdictions" | "playbook">>) {
    if (!matter) return
    const next = { ...matter, ...fields }
    const updated = await renameMatter(matter.id, next.title, next.reference, next.jurisdictions, next.playbook)
    setMatter((m) => m && { ...m, title: updated.title, reference: updated.reference, jurisdictions: updated.jurisdictions, playbook: updated.playbook })
    onSessionsChanged()
  }

  async function commitRename() {
    setRenaming(false)
    const next = draftTitle.trim()
    if (!matter || !next || next === matter.title) return
    await patch({ title: next })
  }

  async function commitRef() {
    setEditingRef(false)
    const next = draftRef.trim()
    if (!matter || next === (matter.reference ?? "")) return
    await patch({ reference: next || undefined })
  }

  function changePlaybook(next?: string) {
    return patch({ playbook: next })
  }

  return (
    <>
      <header className="page-head">
        <div className="matter-head">
          {editingRef ? (
            <input
              className="matter-ref-input"
              autoFocus
              placeholder="Reference"
              value={draftRef}
              onChange={(e) => setDraftRef(e.target.value)}
              onBlur={commitRef}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitRef()
                if (e.key === "Escape") setEditingRef(false)
              }}
            />
          ) : (
            <button
              type="button"
              className={`matter-ref matter-field${matter.reference ? "" : " empty"}`}
              title="Click to edit reference"
              onClick={() => {
                setDraftRef(matter.reference ?? "")
                setEditingRef(true)
              }}
            >
              {matter.reference || "Add reference"}
            </button>
          )}

          <h1>
            {renaming ? (
              <input
                className="matter-title-input"
                autoFocus
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                onBlur={commitRename}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename()
                  if (e.key === "Escape") setRenaming(false)
                }}
              />
            ) : (
              <span
                className="matter-title"
                title="Click to rename"
                onClick={() => {
                  setDraftTitle(matter.title)
                  setRenaming(true)
                }}
              >
                {matter.title}
              </span>
            )}
          </h1>
        </div>

        <div className="matter-head-jx">
          <JurisdictionSelect
            jurisdictions={jurisdictions}
            selected={matter.jurisdictions ?? []}
            onChange={(codes) => patch({ jurisdictions: codes })}
            align="right"
            trigger={
              (matter.jurisdictions?.length ?? 0) === 0 ? (
                <span className="matter-jx-add">Add jurisdiction</span>
              ) : (
                <span className="matter-jx-badges">
                  {matter.jurisdictions?.map((code) => (
                    <span key={code} className="matter-badge">
                      {jurisdictions.find((j) => j.code === code)?.name ?? code}
                    </span>
                  ))}
                </span>
              )
            }
          />
        </div>
      </header>

      {view === "chat" && (
        <div className={`matter-body${docsOpen ? "" : " docs-collapsed"}`}>
          <div className="workspace">
            <ChatPanel
              key={session ?? "new"}
              directory={matter.dir}
              sessionID={session}
              created={createdRef.current === session}
              initialPrompt={params.get("prompt") ?? undefined}
              agent={agent}
              available={available}
              workflows={workflows}
              playbooks={playbooks}
              playbook={matter.playbook}
              onPlaybookChange={changePlaybook}
              onAgentChange={setAgent}
              onSessionCreated={(sid) => {
                createdRef.current = sid
                setParams({ view: "chat", session: sid }, { replace: true })
              }}
              onSessionStarted={onSessionsChanged}
              onViewDocument={(name, redlineId) => {
                setFocusRedline(redlineId)
                setViewing(name)
              }}
              onDocumentsChanged={refresh}
              onAdjuntar={() => abrirArchivos.current()}
            />
          </div>
          <DocumentUpload
            matterId={matter.id}
            documents={matter.documents}
            onUploaded={refresh}
            onView={(name) => {
              setFocusRedline(undefined)
              setViewing(name)
            }}
            collapsed={!docsOpen}
            onToggle={() => setDocsOpen((o) => !o)}
            onRegistrarAbrir={registrarAbrir}
          />
        </div>
      )}

      {view === "review" && (
        <ReviewGrid matterId={matter.id} title={matter.title} directory={matter.dir} documents={matter.documents} />
      )}

      {view === "documents" && (
        <DocumentUpload
          matterId={matter.id}
          documents={matter.documents}
          onUploaded={refresh}
          onView={(name) => {
            setFocusRedline(undefined)
            setViewing(name)
          }}
        />
      )}

      {viewing && (
        <DocumentViewer
          matterId={matter.id}
          name={viewing}
          focusId={focusRedline}
          onClose={() => setViewing(undefined)}
          onChanged={refresh}
          onConverted={(name) => setViewing(name)}
          onSaveTemplate={
            viewing.toLowerCase().endsWith(".docx")
              ? () => {
                  const doc = viewing
                  setViewing(undefined)
                  setParams({
                    view: "chat",
                    agent: "drafter",
                    prompt: language === "es"
                      ? `Guarda "${doc}" como plantilla reutilizable. Lee el documento y sustituye cada nombre de parte, fecha, importe, dirección y otro dato específico del cliente por un marcador único [insert ...]; después guarda la plantilla en la biblioteca de plantillas.`
                      : `Save "${doc}" as a reusable template. Read the document and replace every party name, date, amount, address, and other client-specific detail with a unique [insert ...] placeholder, then save it to the template library.`,
                  })
                }
              : undefined
          }
        />
      )}
    </>
  )
}
