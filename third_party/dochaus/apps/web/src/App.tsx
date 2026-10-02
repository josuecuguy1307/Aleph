import { useEffect, useState } from "react"
import { Route, Routes } from "react-router-dom"
import Matters from "./pages/Matters"
import Templates from "./pages/Templates"
import Workflows from "./pages/Workflows"
import Skills from "./pages/Skills"
import Agents from "./pages/Agents"
import MatterDetail from "./pages/MatterDetail"
import Settings from "./components/Settings"
import Sidebar from "./components/Sidebar"
import BootScreen from "./components/BootScreen"
import { ToastProvider } from "./components/Toast"
import { getConfig } from "./api/opencode"
import { listMatters } from "./api/ingest"
import { applyAppearance } from "./prefs"

export default function App() {
  const [settings, setSettings] = useState(false)
  // Text size lands as a data attribute on <html> the stylesheet keys off.
  useEffect(() => {
    applyAppearance()
  }, [])
  // Both backends ('opencode serve' and the ingest document service) are separate
  // processes that may still be booting when the web app loads, so their probes
  // reject until reachable. Poll each until it answers and hold the app behind a
  // boot screen until both are up — otherwise the list pages fetch a dead socket
  // and fall through to a misleading empty state. Gate onboarding on the real
  // engine config rather than silently skipping it on the first failed call.
  const [engineReady, setEngineReady] = useState(false)
  const [ingestReady, setIngestReady] = useState(false)
  useEffect(() => {
    let cancelled = false
    async function poll<T>(probe: () => Promise<T>, onReady: (value: T) => void) {
      while (!cancelled) {
        try {
          const value = await probe()
          if (!cancelled) onReady(value)
          return
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 1000))
        }
      }
    }
    poll(getConfig, () => {
      setEngineReady(true)
    })
    poll(listMatters, () => setIngestReady(true))
    return () => {
      cancelled = true
    }
  }, [])
  const booted = engineReady && ingestReady
  // Bumped when a matter mints a new conversation, so the sidebar re-lists its
  // chats the instant one starts rather than waiting for the turn to settle.
  const [sessionsVersion, setSessionsVersion] = useState(0)
  if (!booted)
    return (
      <ToastProvider>
        <BootScreen engineReady={engineReady} ingestReady={ingestReady} />
      </ToastProvider>
    )
  return (
    <ToastProvider>
      <div className="shell">
        <Sidebar onOpenSettings={() => setSettings(true)} sessionsVersion={sessionsVersion} />
        <main className="content">
          <div className="container">
            <Routes>
              <Route path="/" element={<Matters />} />
              <Route path="/templates" element={<Templates />} />
              <Route path="/workflows" element={<Workflows />} />
              <Route path="/skills" element={<Skills />} />
              <Route path="/agents" element={<Agents />} />
              <Route
                path="/matter/:id"
                element={<MatterDetail onSessionsChanged={() => setSessionsVersion((v) => v + 1)} />}
              />
            </Routes>
          </div>
        </main>
        {settings && (
          <Settings
            onClose={() => {
              setSettings(false)
            }}
          />
        )}
      </div>
    </ToastProvider>
  )
}
