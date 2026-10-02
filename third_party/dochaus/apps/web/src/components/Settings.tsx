import { useEffect, useState } from "react"
import { dentroDeAleph } from "../aleph"
import { getPreferences, listJurisdictions, savePreferences, type DraftingPreferences, type Jurisdiction } from "../api/ingest"
import { loadPrefs, savePrefs, type Prefs } from "../prefs"
import JurisdictionSelect from "./JurisdictionSelect"
import { useToast } from "./Toast"
import { useLanguage } from "../i18n"

type Tab = "drafting" | "research" | "matters" | "approvals" | "appearance"
// [Aleph · un solo Ajustes] `Appearance` es tema e idioma de interfaz, y de eso es dueña la
// casa —que además le manda el suyo por `aleph_scheme`—. Adentro de Aleph no se ofrece: era
// una segunda pantalla para la misma decisión, y encima una que la casa vuelve a pisar. Las
// otras cuatro se quedan enteras: redacción, investigación, defaults de expediente y
// aprobaciones son oficio jurídico y Aleph no tiene dónde ponerlas. Suelto, se ven las cinco.
const TABS: { id: Tab; label: string }[] = [
  { id: "drafting", label: "Drafting" }, { id: "research", label: "Research" },
  { id: "matters", label: "Matter defaults" }, { id: "approvals", label: "Approvals" },
  ...(dentroDeAleph ? [] : [{ id: "appearance" as Tab, label: "Appearance" }]),
]

// The model is intentionally absent: Legal always uses the Cerebro de Aleph from
// the pack config. These settings preserve the domain controls, not BYOK.
export default function Settings({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("drafting")
  const toast = useToast()
  return <div className="viewer-overlay" onClick={onClose}>
    <div className="picker-panel settings-panel" onClick={(e) => e.stopPropagation()}>
      <div className="viewer-bar"><span>Legal settings</span><button onClick={onClose}>Close</button></div>
      <div className="settings-body">
        <nav className="settings-nav">{TABS.map((t) => <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>{t.label}</button>)}</nav>
        <div className="settings-content">
          {tab === "drafting" && <Drafting onSaved={(m) => toast("success", m)} />}
          {tab === "research" && <Research onSaved={(m) => toast("success", m)} />}
          {tab === "matters" && <Matters />}
          {tab === "approvals" && <Approvals />}
          {tab === "appearance" && <Appearance />}
        </div>
      </div>
    </div>
  </div>
}

function Drafting({ onSaved }: { onSaved: (m: string) => void }) {
  const [prefs, setPrefs] = useState<DraftingPreferences | null>(null)
  useEffect(() => { getPreferences().then(setPrefs) }, [])
  if (!prefs) return <p className="muted">Loading preferences...</p>
  const set = (p: Partial<DraftingPreferences>) => setPrefs({ ...prefs, ...p })
  return <section className="settings-section"><h3>Drafting</h3><p className="settings-hint muted">Standing instructions for the Legal workspace.</p>
    <label className="settings-label">Attorney<input value={prefs.attorney} onChange={(e) => set({ attorney: e.target.value })} /></label>
    <label className="settings-label">Firm<input value={prefs.firm} onChange={(e) => set({ firm: e.target.value })} /></label>
    <Choice label="Posture" value={prefs.posture} options={["client-favorable", "balanced", "conservative"]} onChange={(posture) => set({ posture: posture as DraftingPreferences["posture"] })} />
    <Choice label="Formality" value={prefs.formality} options={["formal", "plain"]} onChange={(formality) => set({ formality: formality as DraftingPreferences["formality"] })} />
    <Choice label="Detail" value={prefs.detail} options={["concise", "detailed"]} onChange={(detail) => set({ detail: detail as DraftingPreferences["detail"] })} />
    <label className="settings-label">House style<textarea className="settings-textarea" rows={4} value={prefs.houseStyle} onChange={(e) => set({ houseStyle: e.target.value })} /></label>
    <button className="primary" onClick={async () => { setPrefs(await savePreferences(prefs)); onSaved("Drafting preferences saved.") }}>Save</button>
  </section>
}

function Research({ onSaved }: { onSaved: (m: string) => void }) {
  const [prefs, setPrefs] = useState<DraftingPreferences | null>(null)
  useEffect(() => { getPreferences().then(setPrefs) }, [])
  if (!prefs) return <p className="muted">Loading preferences...</p>
  const set = (p: Partial<DraftingPreferences>) => setPrefs({ ...prefs, ...p })
  return <section className="settings-section"><h3>Research</h3><p className="settings-hint muted">Official sources remain the default; discovery never becomes authority.</p>
    <Choice label="Web research" value={prefs.webResearch} options={["official", "open"]} onChange={(webResearch) => set({ webResearch: webResearch as DraftingPreferences["webResearch"] })} />
    <label className="settings-label">Approved sources<textarea className="settings-textarea" rows={3} value={prefs.approvedSources.join("\n")} onChange={(e) => set({ approvedSources: e.target.value.split("\n") })} /></label>
    <label className="settings-label">Exa discovery key (optional)<input type="password" value={prefs.searchApiKey} onChange={(e) => set({ searchApiKey: e.target.value })} /></label>
    <button className="primary" onClick={async () => { const approvedSources = [...new Set(prefs.approvedSources.map((s) => s.trim().replace(/^https?:\/\//i, "").replace(/\/.*$/, "").toLowerCase()).filter(Boolean))]; setPrefs(await savePreferences({ ...prefs, approvedSources })); onSaved("Research preferences saved.") }}>Save</button>
  </section>
}

function Matters() {
  const [all, setAll] = useState<Jurisdiction[]>([]); const [selected, setSelected] = useState(() => loadPrefs().defaultJurisdictions)
  useEffect(() => { listJurisdictions().then(setAll) }, [])
  return <section className="settings-section"><h3>Matter defaults</h3><p className="settings-hint muted">Jurisdictions preselected for a new matter; each matter can override them.</p><JurisdictionSelect jurisdictions={all} selected={selected} onChange={(codes) => { setSelected(codes); savePrefs({ defaultJurisdictions: codes }) }} /></section>
}

function Approvals() {
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs); const set = (p: Partial<Prefs>) => setPrefs(savePrefs(p))
  return <section className="settings-section"><h3>Approvals</h3><p className="settings-hint muted">A redline is only a proposal. The canonical .docx changes only after a human accepts it.</p><Toggle title="Redlines & tracked changes" on={prefs.autoApproveRedlines} change={(on) => set({ autoApproveRedlines: on })} /><Toggle title="New documents & templates" on={prefs.autoApproveDrafting} change={(on) => set({ autoApproveDrafting: on })} /></section>
}

function Appearance() { const [prefs, setPrefs] = useState<Prefs>(loadPrefs); const { language, setLanguage } = useLanguage(); return <section className="settings-section"><h3>Appearance</h3><Choice label="Language" value={language} options={["en", "es"]} onChange={(value) => setLanguage(value as "en" | "es")} /><Choice label="Text size" value={prefs.textSize} options={["compact", "standard", "large"]} onChange={(textSize) => setPrefs(savePrefs({ textSize: textSize as Prefs["textSize"] }))} /></section> }
function Choice({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (v: string) => void }) { const { t } = useLanguage(); return <label className="settings-label">{t(label)}<select value={value} onChange={(e) => onChange(e.target.value)}>{options.map((x) => <option key={x} value={x}>{t(x)}</option>)}</select></label> }
function Toggle({ title, on, change }: { title: string; on: boolean; change: (on: boolean) => void }) { return <div className="settings-conn"><span className="settings-conn-name">{title}</span><button role="switch" aria-checked={on} className={`switch${on ? " on" : ""}`} onClick={() => change(!on)} /></div> }
