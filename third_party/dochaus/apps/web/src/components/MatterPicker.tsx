import { useEffect, useState } from "react"
import { listJurisdictions, listMatters, type Jurisdiction, type Matter } from "../api/ingest"
import ViewerModal from "./ViewerModal"

// The "Use in a matter" picker shared by the Templates and Workflows libraries:
// pick a matter to drop a template draft or workflow run into. Loads its own
// matters and jurisdictions; lists newest first with the open date and any
// jurisdiction names so the lawyer can tell similar matters apart. onPick fires
// with the chosen matter; the caller handles navigation.
export default function MatterPicker({
  title,
  onPick,
  onClose,
}: {
  title: string
  onPick: (matter: Matter) => void
  onClose: () => void
}) {
  const [matters, setMatters] = useState<Matter[]>()
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>([])

  useEffect(() => {
    listMatters().then(setMatters)
    listJurisdictions().then(setJurisdictions)
  }, [])

  const sorted = matters && [...matters].sort((a, b) => b.created_at - a.created_at)

  return (
    <ViewerModal onClose={onClose}>
      <div className="picker-panel" onClick={(e) => e.stopPropagation()}>
        <div className="viewer-bar">
          <span className="viewer-title">{title}</span>
          <button onClick={onClose}>Close</button>
        </div>
        <div className="picker-body">
          {!sorted ? null : sorted.length === 0 ? (
            <p className="muted">No matters yet. Create one from the sidebar first.</p>
          ) : (
            sorted.map((m) => (
              <button key={m.id} className="assistant-option" onClick={() => onPick(m)}>
                <span className="assistant-name">
                  {m.reference ? `${m.reference} — ` : ""}
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
              </button>
            ))
          )}
        </div>
      </div>
    </ViewerModal>
  )
}
