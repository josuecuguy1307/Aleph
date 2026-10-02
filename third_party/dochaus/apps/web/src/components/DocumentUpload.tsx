import { useEffect, useRef, useState } from "react"
import { deleteDocument, uploadDocument, type Document } from "../api/ingest"
import { useLanguage } from "../i18n"
import { useToast } from "./Toast"

// The matter's documents, as a collapsible right rail beside the chat. Chat is
// the primary surface, so documents sit out of its way: expanded the rail shows
// the indexed list plus a dropzone; collapsed it shrinks to a thin tab carrying
// the document count, reclaiming the width for the conversation.
export default function DocumentUpload({
  matterId,
  documents,
  onUploaded,
  onView,
  collapsed,
  onToggle,
  onRegistrarAbrir,
}: {
  matterId: string
  documents: Document[]
  onUploaded: () => void
  onView: (name: string) => void
  // Rail mode (chat surface) is collapsible; the Documents surface omits these
  // and renders the full-width manager with no collapse affordance.
  collapsed?: boolean
  onToggle?: () => void
  // [rediseño · Legal · la barrita] EL CLIP DEL COMPOSER ES ESTA MISMA PUERTA. El artboard
  // 35d fija que el clip «dispara el buscador de archivos del sistema, sin submenú», y en
  // Legal ese buscador ya existe: es el `<input type="file">` de acá, con su `onChange` →
  // `onFiles` → `uploadDocument`. No se reimplementa nada: el rail PRESTA su disparador
  // (`input.current.click()`), que es exactamente el que ya usan la zona de arrastre y el
  // botón del panel. Sin esta prop, el rail se comporta igual que siempre.
  onRegistrarAbrir?: (abrir: () => void) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const { t } = useLanguage()
  const toast = useToast()

  useEffect(() => {
    if (!onRegistrarAbrir) return
    onRegistrarAbrir(() => input.current?.click())
    return () => onRegistrarAbrir(() => {})
  }, [onRegistrarAbrir])

  useEffect(() => {
    if (!confirmId) return
    const dismiss = () => setConfirmId(null)
    window.addEventListener("click", dismiss)
    return () => window.removeEventListener("click", dismiss)
  }, [confirmId])

  async function onFiles(files: File[]) {
    // [Aleph] EL «Working...» QUE NO SE APAGABA NUNCA.
    //
    // Este bloque no tenía `try`. Si `uploadDocument` rechazaba —un 500, un formato que el
    // ingest no puede leer, un corte de red—, la excepción se escapaba de `onFiles`,
    // `setBusy(false)` NO se ejecutaba y el panel quedaba en «Working...» para siempre, sin
    // una palabra de por qué. Visto en pantalla el 2026-08-29 con tres .docx y un .pdf en
    // el panel de un matter.
    //
    // Y un archivo que falla NO cancela a los demás: cada uno dice lo suyo. Antes, el
    // primero que fallara se llevaba puesta la subida entera de la tanda.
    setBusy(true)
    try {
      for (const file of files) {
        let result
        try {
          result = await uploadDocument(matterId, file)
        } catch (error) {
          const detalle = error instanceof Error ? error.message : String(error)
          toast("error", `Could not index ${file.name}: ${detalle}`)
          continue
        }
        onUploaded()
        // A flagged upload is a finding the lawyer needs to see, not a failure: the
        // document is indexed, the assistant treats the flagged text as untrusted,
        // and the warning says what ingest found.
        if (result.injection) {
          toast(
            "warning",
            `Indexed ${result.name} with warnings — possible prompt injection: ${[
              ...new Set(result.injection.findings.map((f) => f.detail)),
            ].join("; ")}. The assistant will treat this content as untrusted.`,
          )
          continue
        }
        toast("success", `Indexed ${result.name}: ${result.sections} sections, ${result.chunks} chunks.`)
      }
    } finally {
      // El `finally` es el punto: pase lo que pase, el panel vuelve a estar usable.
      setBusy(false)
    }
  }

  async function onRemove(name: string) {
    setConfirmId(null)
    setBusy(true)
    try {
      await deleteDocument(matterId, name)
      // ⚠️ EL ÉXITO SE CANTA ADENTRO DEL `try`. Estas dos líneas estaban afuera y corrían
      // igual cuando el borrado fallaba: la lista se refrescaba y el aviso decía «Removed»
      // de un archivo que seguía ahí.
      onUploaded()
      toast("success", `Removed ${name}.`)
    } catch (error) {
      // Mismo agujero que la subida, y la misma cura: se dice y el panel se libera.
      toast("error", `Could not delete ${name}: ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(false)
    }
  }

  const pending = documents.reduce((n, d) => n + (d.pending ?? 0), 0)

  if (collapsed) {
    return (
      <button className="docs-tab" onClick={onToggle} title={pending ? `${pending} pending changes to review` : "Show documents"}>
        <IconDocs />
        <span className="docs-tab-count">{documents.length}</span>
        <span className="docs-tab-label">Documents</span>
        {pending > 0 && <span className="redline-badge">{pending}</span>}
      </button>
    )
  }

  return (
    <aside className={onToggle ? "card docs-rail" : "card docs-surface"}>
      <div className="docs-rail-head">
        <h2>Documents</h2>
        {onToggle && (
          <button className="icon-btn" onClick={onToggle} title="Hide documents">
            <IconChevron />
          </button>
        )}
      </div>
      {documents.length === 0 ? (
        <div className="empty-inline">No documents indexed yet.</div>
      ) : (
        <ul className="matter-list">
          {documents.map((d) => (
            <li key={d.id} className="doc-row">
              <div className="doc-row-main">
                <button className="linklike" onClick={() => onView(d.name)}>
                  {d.name}
                </button>
                {d.pending ? (
                  <span className="redline-badge" title={`${d.pending} pending change${d.pending === 1 ? "" : "s"} to review`}>
                    {d.pending}
                  </span>
                ) : null}
              </div>
              <div className="doc-row-meta">
                <span className="muted">{new Date(d.created_at).toLocaleDateString()}</span>
                {confirmId === d.id ? (
                  <button
                    className="icon-btn danger"
                    title={`Remove ${d.name} — indexed text is deleted and answers can no longer cite it`}
                    onClick={(e) => {
                      e.stopPropagation()
                      onRemove(d.name)
                    }}
                  >
                    Confirm
                  </button>
                ) : (
                  <button
                    className="doc-remove"
                    onClick={(e) => {
                      e.stopPropagation()
                      setConfirmId(d.id)
                    }}
                    title={`Remove ${d.name}`}
                    disabled={busy}
                  >
                    <IconTrash />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <div
        className={`dropzone${dragging ? " dragover" : ""}`}
        style={{ marginTop: 12 }}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          const files = Array.from(e.dataTransfer.files)
          if (files.length) onFiles(files)
        }}
      >
        {busy
          ? t("Working...")
          : t("Drop .docx or .pdf documents here (scans OK), or click to choose files.")}
      </div>
      <input
        ref={input}
        type="file"
        accept=".docx,.pdf"
        multiple
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          if (files.length) onFiles(files)
          e.target.value = ""
        }}
      />
    </aside>
  )
}

function IconDocs() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}

function IconChevron() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  )
}

function IconTrash() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  )
}
