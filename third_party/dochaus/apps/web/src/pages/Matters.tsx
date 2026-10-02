import { useEffect, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import {
  createMatter,
  deleteMatter,
  listMatters,
  listJurisdictions,
  renameMatter,
  type Matter,
  type Jurisdiction,
} from "../api/ingest"
import JurisdictionSelect from "../components/JurisdictionSelect"
import { useToast } from "../components/Toast"
import { loadPrefs } from "../prefs"

export default function Matters() {
  const [matters, setMatters] = useState<Matter[]>([])
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>([])
  const [loading, setLoading] = useState(true)
  const [title, setTitle] = useState("")
  const [reference, setReference] = useState("")
  // New matters start from the firm's default jurisdictions (Settings → Matter
  // defaults) instead of empty.
  const [newJurisdictions, setNewJurisdictions] = useState<string[]>(() => loadPrefs().defaultJurisdictions)
  const [filter, setFilter] = useState("")
  const [busy, setBusy] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  // The matter being edited in the modal, plus its draft fields. null when closed.
  const [editing, setEditing] = useState<Matter | null>(null)
  const [draftTitle, setDraftTitle] = useState("")
  const [draftReference, setDraftReference] = useState("")
  const [draftJurisdictions, setDraftJurisdictions] = useState<string[]>([])
  const toast = useToast()

  // [rediseño · Legal · el frame] LA FILA `Search` DE LA BARRA ENTRA POR ACÁ. El artboard
  // 38a pone `Search ⌘⇧F` en el bloque estándar; buscado por FUNCIÓN, el control que ya
  // hace eso en Legal es este filtro —busca por título y por ID—, así que la fila es una
  // segunda ENTRADA al mismo campo y no un buscador nuevo. `?buscar=1` sólo le pide el
  // foco, y se limpia enseguida para que un refresh no vuelva a robárselo.
  const [params, setParams] = useSearchParams()
  const filtro = useRef<HTMLInputElement>(null)
  // ⚠️ EL FOCO NO PUEDE CORRER ANTES QUE LA LISTA. El campo sólo se monta con
  // `matters.length > 0`, así que en el primer render —con la lista todavía viajando— el
  // ref es `null` y el foco se perdía en silencio: medido con el atajo, el foco quedaba en
  // el `<button>` que lo disparó. Por eso `matters` está en las dependencias y el parámetro
  // se limpia DESPUÉS de que el foco ocurrió; si no hay lista que filtrar (cero matters,
  // ya cargada) se limpia igual para no dejarlo pegado en la URL.
  useEffect(() => {
    if (!params.get("buscar") || loading) return
    if (filtro.current) {
      filtro.current.focus()
      filtro.current.select()
    }
    setParams({}, { replace: true })
  }, [params, setParams, matters, loading])

  useEffect(() => {
    listMatters()
      .then(setMatters)
      .finally(() => setLoading(false))
    listJurisdictions().then(setJurisdictions)
  }, [])

  useEffect(() => {
    if (!confirmId) return
    const dismiss = () => setConfirmId(null)
    window.addEventListener("click", dismiss)
    return () => window.removeEventListener("click", dismiss)
  }, [confirmId])

  async function onCreate() {
    if (!title.trim()) return
    setBusy(true)
    const matter = await createMatter(
      title.trim(),
      reference.trim() || undefined,
      newJurisdictions.length ? newJurisdictions : undefined,
    )
    setMatters((prev) => [...prev, matter])
    setTitle("")
    setReference("")
    setNewJurisdictions(loadPrefs().defaultJurisdictions)
    setBusy(false)
    toast("success", `Created matter "${matter.title}".`)
  }

  async function onDelete(m: Matter) {
    setConfirmId(null)
    await deleteMatter(m.id)
    setMatters((prev) => prev.filter((x) => x.id !== m.id))
    toast("success", `Deleted matter "${m.title}".`)
  }

  function openEdit(m: Matter) {
    setEditing(m)
    setDraftTitle(m.title)
    setDraftReference(m.reference ?? "")
    setDraftJurisdictions(m.jurisdictions ?? [])
  }

  async function onSaveEdit() {
    if (!editing || !draftTitle.trim()) return
    setBusy(true)
    const updated = await renameMatter(
      editing.id,
      draftTitle.trim(),
      draftReference.trim() || undefined,
      draftJurisdictions.length ? draftJurisdictions : undefined,
      editing.playbook,
    )
    setMatters((prev) => prev.map((m) => (m.id === updated.id ? updated : m)))
    setEditing(null)
    setBusy(false)
    toast("success", `Updated matter "${updated.title}".`)
  }

  const term = filter.trim().toLowerCase()
  const visible = [...matters]
    .sort((a, b) => b.created_at - a.created_at)
    .filter((m) => !term || m.title.toLowerCase().includes(term) || (m.reference ?? "").toLowerCase().includes(term))

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Matters</h1>
          <p className="page-sub">Every engagement, its documents, and its conversations.</p>
        </div>
        <div className="page-head-actions">
          {matters.length > 0 && (
            <input
              ref={filtro}
              placeholder="Filter by title or ID"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              style={{ width: 220 }}
            />
          )}
        </div>
      </header>

      <div className="card">
        <h2>New matter</h2>
        <div className="row">
          <input
            placeholder="Matter title, e.g. Acme MSA review"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onCreate()}
            style={{ flex: 1 }}
          />
          <input
            placeholder="Matter ID (optional)"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onCreate()}
            style={{ width: 160 }}
          />
          <JurisdictionSelect
            jurisdictions={jurisdictions}
            selected={newJurisdictions}
            onChange={setNewJurisdictions}
          />
          <button className="primary" onClick={onCreate} disabled={busy || !title.trim()}>
            Create matter
          </button>
        </div>
      </div>

      <div className="card">
        {loading ? (
          <div className="skeleton-list">
            <div className="skeleton-row" />
            <div className="skeleton-row" />
            <div className="skeleton-row" />
          </div>
        ) : matters.length === 0 ? (
          <div className="empty-state">
            <svg className="empty-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
            </svg>
            <h3>No matters yet</h3>
            <p>A matter holds an engagement&apos;s documents, reviews, and conversations.</p>
          </div>
        ) : visible.length === 0 ? (
          <p className="muted">No matters match "{filter}".</p>
        ) : (
          <ul className="matter-list">
            {visible.map((m) => (
              <li key={m.id} className="list-row">
                <Link to={`/matter/${m.id}`} className="list-row-main">
                  <span className="list-row-title">
                    {m.reference && <span className="matter-ref">{m.reference}</span>}
                    {m.title}
                  </span>
                  <span className="list-row-meta">
                    <span className="list-row-date">Opened {new Date(m.created_at).toLocaleDateString()}</span>
                    {m.jurisdictions?.map((code) => (
                      <span key={code} className="matter-jurisdiction">
                        {jurisdictions.find((j) => j.code === code)?.name ?? code}
                      </span>
                    ))}
                  </span>
                </Link>
                <div className="list-row-actions">
                  <button className="icon-btn" title="Edit matter" onClick={() => openEdit(m)}>
                    Edit
                  </button>
                  {confirmId === m.id ? (
                    <button
                      className="icon-btn danger"
                      title="Confirm delete"
                      onClick={(e) => {
                        e.stopPropagation()
                        onDelete(m)
                      }}
                    >
                      Confirm
                    </button>
                  ) : (
                    <button
                      className="icon-btn"
                      title="Delete matter"
                      onClick={(e) => {
                        e.stopPropagation()
                        setConfirmId(m.id)
                      }}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {editing && (
        <div className="viewer-overlay" onClick={() => setEditing(null)}>
          <div className="picker-panel matter-edit" onClick={(e) => e.stopPropagation()}>
            <div className="viewer-bar">
              <span className="viewer-title">Edit matter</span>
              <button onClick={() => setEditing(null)}>Close</button>
            </div>
            <div className="matter-edit-body">
              <label className="matter-edit-field">
                <span>Title</span>
                <input
                  autoFocus
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && onSaveEdit()}
                />
              </label>
              <label className="matter-edit-field">
                <span>Matter ID</span>
                <input
                  value={draftReference}
                  onChange={(e) => setDraftReference(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && onSaveEdit()}
                />
              </label>
              <div className="matter-edit-field">
                <span>Jurisdictions</span>
                <JurisdictionSelect
                  jurisdictions={jurisdictions}
                  selected={draftJurisdictions}
                  onChange={setDraftJurisdictions}
                />
              </div>
            </div>
            <div className="viewer-bar matter-edit-foot">
              <button onClick={() => setEditing(null)}>Cancel</button>
              <button className="primary" onClick={onSaveEdit} disabled={busy || !draftTitle.trim()}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
