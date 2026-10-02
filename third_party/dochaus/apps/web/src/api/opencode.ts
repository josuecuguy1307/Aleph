import { createOpencodeClient } from "@opencode-ai/sdk"
import type { Event, Part } from "@opencode-ai/sdk"
import { OPENCODE_URL } from "../config"

// One OpenCode client per matter. The matter's directory is sent as the
// x-opencode-directory header on every request, so every session and every
// tool (including search-document) is scoped to that matter's files + DB.
export function matterClient(directory: string) {
  return createOpencodeClient({ baseUrl: OPENCODE_URL, directory })
}

export type Client = ReturnType<typeof matterClient>

// The generated pack config is the only source of model configuration. The web
// reads it solely as a health probe and for the engine's fixed Auto router.
export async function getConfig() {
  const res = await fetch(`${OPENCODE_URL}/global/config`)
  if (!res.ok) throw new Error(`Failed to load config (${res.status})`)
  return (await res.json()) as { model?: string; small_model?: string }
}

// A pending permission request from the engine. The edit tools (word-integration,
// tracked-changes, redline) call ctx.ask before mutating or proposing against a
// document; the engine parks the tool call and emits a permission.asked event,
// then resumes (or fails) it when we reply. metadata carries what the tool is
// about to do (document, find/replace or clause/replacement) for display.
export type PermissionRequest = {
  id: string
  sessionID: string
  permission: string
  patterns: string[]
  metadata: Record<string, unknown>
  always: string[]
  tool?: { messageID: string; callID: string }
}

export type PermissionReply = "once" | "always" | "reject"

// The permission events the engine emits on the same SSE stream as everything
// else. The v1 SDK's Event union does not model them, so the subscriber narrows
// raw events through this type (see ChatPanel.onEvent).
export type PermissionEvent =
  | { type: "permission.asked"; properties: PermissionRequest }
  | { type: "permission.replied"; properties: { sessionID: string; requestID: string; reply: PermissionReply } }

// Permission state is instance-scoped, so both calls must carry the matter's
// x-opencode-directory header. The v1 SDK exposes no permission methods — its
// generated client predates the /permission routes — so these hit them directly.
export async function listPermissions(directory: string) {
  const res = await fetch(`${OPENCODE_URL}/permission`, {
    headers: { "x-opencode-directory": directory },
  })
  if (!res.ok) throw new Error(`Failed to list permissions (${res.status})`)
  return (await res.json()) as PermissionRequest[]
}

export async function replyPermission(directory: string, requestID: string, reply: PermissionReply) {
  const res = await fetch(`${OPENCODE_URL}/permission/${requestID}/reply`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-opencode-directory": directory },
    body: JSON.stringify({ reply }),
  })
  if (!res.ok) throw new Error(`Failed to reply to permission (${res.status})`)
}

// Shape returned by the search-document tool in its part metadata.citations.
export type Citation = {
  documentName: string
  docPath: string
  section: string
  excerpt: string
  charStart: number
  charEnd: number
  score: number
}

export async function listAgents(client: Client) {
  const res = await client.app.agents()
  return res.data ?? []
}

export async function disposeInstance(client: Client) {
  await client.instance.dispose()
}

export async function createSession(client: Client, title: string) {
  const res = await client.session.create({ body: { title } })
  if (!res.data) throw new Error("Failed to create session")
  return res.data
}

// Every session the engine holds for this matter (scoped by the client's
// directory header). Subagent runs carry a parentID; top-level chats do not.
export async function listSessions(client: Client) {
  const res = await client.session.list()
  return res.data ?? []
}

// Delete a session and its messages from the engine. Irreversible.
export async function deleteSession(client: Client, sessionID: string) {
  return client.session.delete({ path: { id: sessionID } })
}

// Settled messages for one session, each as { info, parts }, used to replay a
// past conversation back into the chat panel.
export async function getMessages(client: Client, sessionID: string) {
  const res = await client.session.messages({ path: { id: sessionID } })
  return res.data ?? []
}

// Admit the prompt immediately; completion and permission requests arrive on
// the session event stream and are recovered by ChatPanel's resync poll.
// Waiting for the entire turn here exceeds the server's HTTP idle timeout for
// long document drafts and incorrectly reports a failed run while it continues.
export async function sendPrompt(client: Client, sessionID: string, agent: string, text: string) {
  return client.session.promptAsync({
    path: { id: sessionID },
    body: { agent, parts: [{ type: "text", text }] },
    throwOnError: true,
  })
}

// Consumers such as the review grid need the completed result, rather than
// admission. A completed tool step is insufficient while the session is busy.
export async function waitForTurn(client: Client, sessionID: string) {
  const deadline = Date.now() + 10 * 60 * 1000
  while (Date.now() < deadline) {
    const [snapshot, statuses] = await Promise.all([
      client.session.messages({ path: { id: sessionID }, throwOnError: true }),
      client.session.status({ throwOnError: true }),
    ])
    const messages = snapshot.data ?? []
    const last = messages.at(-1)?.info
    if (last?.role === "assistant" && last.error) throw new Error(JSON.stringify(last.error))
    const status = statuses.data?.[sessionID]
    if (last?.role === "assistant" && last.time.completed && last.finish !== "tool-calls"
      && (!status || status.type === "idle")) return messages
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error("La extracción sigue sin completar. Vuelve a actualizar la celda cuando el turno termine.")
}

// Pick the chat's "Auto" assistant through the fixed Cerebro de Aleph. Routing
// stays inside the engine; Legal never selects or configures a provider itself.
// has no tools and a neutral prompt, so it just returns one candidate name. It
// runs on the matter's own client (passed in) — NOT a directory-less client. A
// header-less prompt routes to the server's cwd, a different directory than the
// matter, which forces the engine to cold-boot a whole second instance for cwd
// (git detection, plugin boot, provider state, models.dev fetch) on first touch,
// awaited with no timeout — the exact stall that wedged the composer on
// "Thinking...". The matter's instance is already warm (upload, agents, history
// all hit it), so routing there reuses it and never boots a second instance.
// The throwaway session is titled "Legal router" so the conversation rail's
// system-title filter drops it (see Sidebar), and it is deleted once read.
// smallModel is the pack-provided model identifier.
export async function routeAgent(input: {
  client: Client
  smallModel: string
  primaryModel?: string
  candidates: { name: string; description: string }[]
  history: string[]
  text: string
}): Promise<string> {
  const names = input.candidates.map((c) => c.name)
  const fallback = names[0] ?? "qa"
  const prompt = routePrompt(input)
  // Try the cheap small model first. Weak small models (Flash Lite, Haiku) can
  // return an off-list name; on that miss, escalate the same route to the primary
  // model before defaulting to Q&A. Primary is only paid for on a miss (and never
  // when it equals small), so the common case stays one cheap call.
  const small = await routeOnce(input.client, input.smallModel, prompt, names)
  if (small) return small
  if (input.primaryModel && input.primaryModel !== input.smallModel) {
    const primary = await routeOnce(input.client, input.primaryModel, prompt, names)
    if (primary) return primary
  }
  return fallback
}

// One routing attempt on a "provider/model" spec: spin up the throwaway router
// session, prompt it, and return the matched candidate name — or null on a bad
// spec, timeout, or off-list reply so the caller can escalate or fall back.
async function routeOnce(client: Client, spec: string, prompt: string, names: string[]): Promise<string | null> {
  const slash = spec.indexOf("/")
  if (slash < 1) return null
  const model = { providerID: spec.slice(0, slash), modelID: spec.slice(slash + 1) }
  const id = (await createSession(client, "Legal router").catch(() => null))?.id
  if (!id) return null
  try {
    // Routing is a best-effort pre-step that must never block the user's turn. The
    // ephemeral router turn has been seen to never complete, which would hang the
    // caller on this await (wedging the composer on "Thinking...") and — since the
    // finally would then never run — leak the throwaway session. Cap it: on overrun
    // return null and let the finally delete the session.
    const turn = client.session
      .prompt({ path: { id }, body: { agent: "router", model, parts: [{ type: "text", text: prompt }] } })
      .catch(() => null)
    const res = await Promise.race([turn, new Promise<null>((resolve) => setTimeout(() => resolve(null), 8000))])
    if (!res) return null
    const reply = (res.data?.parts ?? [])
      .filter((p) => p.type === "text")
      .map((p) => p.text)
      .join("")
      .trim()
    // The model is told to reply with exactly one name; tolerate stray wrapping by
    // also accepting a name embedded in the reply. Off-list => null.
    return names.find((n) => reply === n) ?? names.find((n) => reply.toLowerCase().includes(n.toLowerCase())) ?? null
  } finally {
    await deleteSession(client, id).catch(() => {})
  }
}

function routePrompt(input: { candidates: { name: string; description: string }[]; history: string[]; text: string }) {
  return [
    "<candidates>",
    input.candidates.map((c) => `- ${c.name}: ${c.description}`).join("\n"),
    "</candidates>",
    "<history>",
    input.history.length ? input.history.map((h) => `- ${h}`).join("\n") : "(none)",
    "</history>",
    "<message>",
    input.text,
    "</message>",
  ].join("\n")
}

// Revert a user message and everything after it, rolling the session back to
// just before that turn. Used by edit/retry: revert, then send the new prompt
// so the assistant answer is regenerated from the edited question.
export async function revertMessage(client: Client, sessionID: string, messageID: string) {
  return client.session.revert({ path: { id: sessionID }, body: { messageID } })
}

// Subscribe to the server event stream and invoke onEvent for each event.
// Caller passes an AbortSignal to stop. Errors after abort are swallowed.
//
// The stream is a single long-lived SSE connection. A network blip or a long
// idle gap (a heavy model thinking phase emits no parts for a while) can end it,
// and without reconnecting the live view would silently stop updating — missing
// the rest of the turn and its session.idle, so the turn appears stuck until a
// manual reload. So loop: resubscribe whenever the stream ends, and fire
// onReconnect on each re-subscribe so the caller can resync the state it missed.
export async function subscribeEvents(
  client: Client,
  onEvent: (e: Event) => void,
  signal: AbortSignal,
  onReconnect?: () => void,
) {
  let first = true
  while (!signal.aborted) {
    try {
      // The signal must reach the fetch itself: without it, abort only flips the
      // loop flag and the idle SSE socket stays open until the next event — each
      // panel remount then leaks a connection until the browser's per-origin cap
      // starves every other request to the engine.
      const res = await client.event.subscribe({ signal })
      if (!first) onReconnect?.()
      first = false
      for await (const event of res.stream) {
        if (signal.aborted) return
        onEvent(event as Event)
      }
    } catch {
      if (signal.aborted) return
    }
    if (signal.aborted) return
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
}

export function isToolPart(part: Part): part is Extract<Part, { type: "tool" }> {
  return part.type === "tool"
}

export function isTextPart(part: Part): part is Extract<Part, { type: "text" }> {
  return part.type === "text"
}
