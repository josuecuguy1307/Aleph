import { useEffect, useState } from "react"
import { AlephFrameHeader, AlephFrameFooter, AlephFrameGrupo, useAlephFrame } from "./aleph-frame"
import { Link, NavLink, useMatch, useNavigate, useSearchParams } from "react-router-dom"
import { getMatter } from "../api/ingest"
import { deleteSession, listSessions, matterClient } from "../api/opencode"
import { useToast } from "./Toast"
import { Tooltip } from "./Tooltip"

type Convo = { id: string; title: string; updated: number }

// The open matter's surfaces, switched by the `view` query param. This rail is
// the single navigation plane: the content area is one canvas per surface.
const SURFACES = [
  { view: "chat", label: "Chat", Icon: IconChat },
  { view: "review", label: "Review", Icon: IconReview },
  { view: "documents", label: "Documents", Icon: IconDocsNav },
] as const

// Left rail. Holds the brand, primary nav, the open matter's conversation
// history, and Settings. Collapses to an icons-only strip; the choice persists
// per browser in localStorage (a single UI preference — no datastore needed).
export default function Sidebar({
  onOpenSettings,
  sessionsVersion,
}: {
  onOpenSettings: () => void
  sessionsVersion: number
}) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("dh.sidebar") === "1")
  const matterId = useMatch("/matter/:id")?.params.id
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const notify = useToast()
  const activeSession = params.get("session")
  const view = params.get("view") ?? "chat"
  const [convos, setConvos] = useState<Convo[]>([])
  const [matterTitle, setMatterTitle] = useState("")
  const [matterDir, setMatterDir] = useState("")
  // The conversation whose delete is armed. Clicking the trash slides out an
  // inline Confirm pill instead of blocking on window.confirm; any click
  // elsewhere disarms it.
  const [confirmId, setConfirmId] = useState<string | null>(null)

  useEffect(() => {
    localStorage.setItem("dh.sidebar", collapsed ? "1" : "0")
  }, [collapsed])

  useEffect(() => {
    if (!confirmId) return
    const dismiss = () => setConfirmId(null)
    window.addEventListener("click", dismiss)
    return () => window.removeEventListener("click", dismiss)
  }, [confirmId])

  // When a matter is open, list its top-level chats (engine-persisted; we only
  // read them). Refetch when the active session changes so a new chat shows up.
  useEffect(() => {
    if (!matterId) return setConvos([])
    let live = true
    getMatter(matterId)
      .then((m) => {
        setMatterTitle(m.title)
        setMatterDir(m.dir)
        return listSessions(matterClient(m.dir))
      })
      .then((list) => {
        if (!live) return
        setConvos(
          list
            // Chats only: drop subagent runs (parentID) and our system-titled
            // sessions — workflow runs carry a system title;
            // real chats are titled from the user's first message.
            .filter((s) => !s.parentID && s.title.trim() && !/^legal (grid|router)/i.test(s.title))
            .map((s) => ({ id: s.id, title: s.title, updated: s.time.updated }))
            .sort((a, b) => b.updated - a.updated),
        )
      })
    return () => {
      live = false
    }
  }, [matterId, activeSession, sessionsVersion])

  // Delete a conversation from the engine, then drop it from the list. If it was
  // the open one, fall back to a fresh chat so the canvas isn't left on a dead id.
  async function removeConvo(c: Convo) {
    if (!matterDir) return
    setConfirmId(null)
    try {
      await deleteSession(matterClient(matterDir), c.id)
      setConvos((list) => list.filter((x) => x.id !== c.id))
      if (c.id === activeSession) navigate(`/matter/${matterId}?view=chat`)
      notify("success", "Conversation deleted")
    } catch {
      notify("error", "Could not delete conversation")
    }
  }

  // [rediseño · fase 6] Con el flag apagado, todo lo de abajo queda EXACTAMENTE como hoy.
  const alephFrame = useAlephFrame()

  // [rediseño · Legal · el frame] EL ATAJO DEL BLOQUE ESTÁNDAR. El artboard 38a dibuja
  // `Search ⌘⇧F` y este stack no declaraba UN SOLO atajo de teclado (grep de `metaKey`
  // fuera del Enter del composer: cero). El atajo y la fila llevan al MISMO sitio, que es
  // el filtro que ya existe en Matters — ver `abrirBusqueda`.
  useEffect(() => {
    if (!alephFrame.activo) return
    const alTecla = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== "f" || !e.shiftKey || !(e.metaKey || e.ctrlKey)) return
      e.preventDefault()
      navigate("/?buscar=1")
    }
    window.addEventListener("keydown", alTecla)
    return () => window.removeEventListener("keydown", alTecla)
  }, [alephFrame.activo, navigate])

  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}${alephFrame.activo ? " aleph-frame" : ""}`}>
      {/* La marca de la casa reemplaza al wordmark del stack: el diseño pone «🔵 Aleph ·
          Legal» con la mascota. El `<Link to="/">` de abajo no se pierde —sigue existiendo
          para el modo colapsado y para el flag apagado—.
          EL PLEGAR SUBE A LA CABECERA: el artboard lo dibuja ahí, a la derecha del nombre
          del espacio. Es el MISMO botón —mismo `setCollapsed`, mismo título— movido de
          lugar; el del pie se va para que no queden dos. */}
      {alephFrame.activo ? (
        <AlephFrameHeader
          accion={
            <button
              type="button"
              className="aleph-frame-plegar"
              onClick={() => setCollapsed((c) => !c)}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              <IconPanel />
            </button>
          }
        />
      ) : null}
      <div className="sidebar-brand" hidden={alephFrame.activo}>
        <Link to="/" title="Aleph Legal">
          <span className="app-logo" aria-hidden="true">§</span>
          {!collapsed && <span className="wordmark">Aleph Legal</span>}
        </Link>
      </div>

      {/* ══ EL BLOQUE ESTÁNDAR — `New chat · Search`, y NADA MÁS ═══════════════════════
          El artboard 38a de Legal dibuja exactamente dos filas acá y NO dibuja `Library`:
          la hoja del estándar lo dice («Library solo donde existe»). Buscadas por FUNCIÓN,
          no por nombre —la lección de Finanzas—, las dos que sí existen:

          · New chat  — es el `+ New` que ya vivía adentro de «Conversations»
            (`Link to /matter/:id?view=chat`, que suelta el `session` y abre un chat
            fresco). Se MUEVE con su destino intacto. Sin matter abierto no hay dónde
            colgar un chat en este oficio: la fila lleva a Matters, que es donde se elige
            o se crea el expediente al que un chat pertenece.
          · Search    — el filtro «Filter by title or ID» de Matters, que ya existe y ya
            busca por título y por ID. La fila es una segunda ENTRADA al mismo control, no
            un control nuevo: `?buscar=1` sólo le pide el foco.

          Lo que NO existe en Legal y por eso no se pinta: `Library`. El artboard tampoco
          la dibuja, así que el hueco es del diseño, no un olvido. */}
      {alephFrame.activo && (
        <nav className="sidebar-nav sidebar-estandar">
          <Link
            to={matterId ? `/matter/${matterId}?view=chat` : "/"}
            className="nav-item"
            title="New chat"
          >
            <IconNuevoChat />
            {!collapsed && <span>New chat</span>}
          </Link>
          <Link to="/?buscar=1" className="nav-item" title="Search">
            <IconBuscar />
            {!collapsed && (
              <>
                <span className="nav-item-txt">Search</span>
                <span className="nav-item-atajo">⌘⇧F</span>
              </>
            )}
          </Link>
        </nav>
      )}

      {/* El diseño titula la sección con el NOMBRE DEL ESPACIO en mono, no con «Workspace». */}
      {alephFrame.activo
        ? <AlephFrameGrupo texto={(alephFrame.etiqueta || "Legal").toUpperCase()} />
        : <div className="sidebar-label">Workspace</div>}
      <nav className="sidebar-nav">
        <NavLink
          to="/"
          end
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          title="Matters"
          aria-label="Matters"
        >
          <IconMatters />
          {!collapsed && <span>Matters</span>}
        </NavLink>
        <NavLink
          to="/templates"
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          title="Templates"
          aria-label="Templates"
        >
          <IconTemplates />
          {!collapsed && <span>Templates</span>}
        </NavLink>
        <NavLink
          to="/workflows"
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          title="Workflows"
          aria-label="Workflows"
        >
          <IconWorkflows />
          {!collapsed && <span>Workflows</span>}
        </NavLink>
        <NavLink
          to="/skills"
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          title="Skills"
          aria-label="Skills"
        >
          <IconSkills />
          {!collapsed && <span>Skills</span>}
        </NavLink>
        <NavLink
          to="/agents"
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          title="Agents"
          aria-label="Agents"
        >
          <IconAgents />
          {!collapsed && <span>Agents</span>}
        </NavLink>
      </nav>

      {matterId && (
        <div className="sidebar-surfaces">
          {!collapsed && matterTitle && (
            <Tooltip label={matterTitle}>
              <div className="sidebar-matter">{matterTitle}</div>
            </Tooltip>
          )}
          {SURFACES.map((s) => (
            <Link
              key={s.view}
              to={`/matter/${matterId}?view=${s.view}`}
              className={`nav-item${view === s.view ? " active" : ""}`}
              title={s.label}
            >
              <s.Icon />
              {!collapsed && <span>{s.label}</span>}
            </Link>
          ))}
        </div>
      )}

      {matterId && !collapsed && view === "chat" && (
        <div className="sidebar-convos">
          {/* El artboard 38a no dibuja esta sección —lo suyo es la pantalla de Matters, sin
              expediente abierto— pero la hoja del estándar sí la nombra: `RECENT SESSIONS`,
              etiqueta en mono con su contador. Es la MISMA lista de siempre; cambia el
              rótulo y el formato, no lo que lista.
              El `+ New` de esta cabecera se fue al bloque estándar de arriba con su destino
              intacto: dos entradas al mismo chat fresco serían dos, y el diseño pone una. */}
          {alephFrame.activo ? (
            <AlephFrameGrupo texto="RECENT SESSIONS" cuenta={convos.length} />
          ) : (
            <div className="sidebar-section-head">
              <span>Conversations</span>
              <Link to={`/matter/${matterId}?view=chat`} className="sidebar-new" title="New chat">
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                >
                  <path d="M12 5v14M5 12h14" />
                </svg>
                New
              </Link>
            </div>
          )}
          {convos.length === 0 ? (
            <p className="muted sidebar-empty">No conversations yet.</p>
          ) : (
            <ul className="convo-list">
              {convos.map((c) => (
                <li key={c.id} className="convo-row">
                  <Tooltip label={c.title}>
                    <Link
                      to={`/matter/${matterId}?session=${c.id}`}
                      className={`convo-item${c.id === activeSession ? " active" : ""}`}
                    >
                      {c.title}
                    </Link>
                  </Tooltip>
                  {confirmId === c.id ? (
                    <button
                      className="convo-confirm"
                      title="Confirm delete"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeConvo(c)
                      }}
                    >
                      Confirm
                    </button>
                  ) : (
                    <button
                      className="convo-del"
                      title="Delete conversation"
                      onClick={(e) => {
                        e.stopPropagation()
                        setConfirmId(c.id)
                      }}
                    >
                      <IconTrash />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="sidebar-foot">
        {/* ⚠️ [integración] EL HUECO DECLARADO ACÁ ABAJO SE CIERRA, Y CON EL COMPONENTE
            COMPARTIDO. El comentario que vivía en este lugar decía: «el artboard pone debajo
            de Settings la fila de la cuenta … el contrato que lo resuelve (`aleph-identidad?`)
            lo está tendiendo la rama de Oficina; escribirlo también acá serían dos
            implementaciones del mismo mensaje. ENTRA CUANDO ESA RAMA MERGEE». Mergeó.

            Pero el hueco era más grande de lo que ese comentario creía, y sólo se vio en
            pantalla: este pie dibujaba su PROPIO botón de Settings y nunca montaba
            `AlephFrameFooter`. Medido sobre el bundle horneado de Legal: `aleph-frame-nativo`
            y `aleph-go-home` presentes (o sea, la CABECERA sí se monta), `aleph-frame-pie`,
            `aleph-frame-cuenta` y `aleph-pie-censo` en CERO. El pie del frame era código
            muerto: Legal era el único de los seis que importaba el Header y no el Footer.
            Consecuencia en la barra: sin fila de cuenta, y sin `Ir a…` ni `Conectores` —los
            dos botones de la casa que se quedaron sin riel—, aunque del lado de la cáscara
            los dos módulos estaban montados y respondiendo.

            Con el frame puesto va el pie compartido, que trae las tres cosas de una: el ⚙
            Settings (mismo `aleph-open-settings`, mismo destino), los ítems que el censo
            conteste, y la cuenta de ALEPH —nunca la de este stack, que es lo que el
            comentario viejo defendía y sigue valiendo—. Con el flag apagado, el botón propio
            se queda donde siempre estuvo y no cambia nada. */}
        {alephFrame.activo ? (
          <AlephFrameFooter />
        ) : (
          <button className="nav-item" onClick={() => onOpenSettings()} title="Settings">
            <IconSettings />
            {!collapsed && <span>Settings</span>}
          </button>
        )}
        {/* EL PLEGAR: con el frame puesto no está acá, subió a la cabecera, que es donde lo
            dibuja el artboard. Con el flag apagado se queda donde siempre estuvo. */}
        {!alephFrame.activo && (
          <button
            className="nav-item"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <IconChevron right={collapsed} />
            {!collapsed && <span>Collapse</span>}
          </button>
        )}
      </div>
    </aside>
  )
}

/* Los tres glifos que suma el frame. Los `d` salen del artboard 38a tal cual: mismo trazo
 * de 1.5 y mismo viewBox de 20 que los demás de esa barra. */
function IconPanel() {
  return (
    <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="4" width="14" height="12" rx="2" />
      <path d="M8 4v12" />
    </svg>
  )
}

function IconNuevoChat() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10 4v12M4 10h12" />
    </svg>
  )
}

function IconBuscar() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="9" cy="9" r="5.5" />
      <path d="M13.2 13.2 17 17" />
    </svg>
  )
}

function IconChat() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  )
}

function IconReview() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M3 15h18M9 3v18" />
    </svg>
  )
}

function IconDocsNav() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}

function IconMatters() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  )
}

function IconTemplates() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 7h8M8 11h8M8 15h5" />
    </svg>
  )
}

function IconWorkflows() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="5" cy="12" r="2" />
      <circle cx="19" cy="5" r="2" />
      <circle cx="19" cy="19" r="2" />
      <path d="M7 12h4l3-5" />
      <path d="M11 12l3 5" />
    </svg>
  )
}

function IconSkills() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  )
}

function IconAgents() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="5" y="8" width="14" height="11" rx="2" />
      <path d="M12 8V5" />
      <circle cx="12" cy="4" r="1" />
      <path d="M9 13h.01M15 13h.01" />
      <path d="M5 12H3M21 12h-2" />
    </svg>
  )
}

function IconSettings() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
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

function IconChevron({ right }: { right: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points={right ? "9 18 15 12 9 6" : "15 18 9 12 15 6"} />
    </svg>
  )
}
