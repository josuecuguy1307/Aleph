type MessageInfo = { role: string; time?: { created?: number; completed?: number }; finish?: string; error?: unknown }

export function turnInFlight(last: MessageInfo | undefined, status: { type: string } | undefined) {
  if (status?.type === "busy" || status?.type === "retry") return true
  return last?.role === "assistant" && !last.error && !last.time?.completed
}

export function splitSessionHistory<T extends { info: MessageInfo }>(messages: T[], active: boolean) {
  if (!active) return { settled: messages, live: [] as T[] }
  let user = -1
  for (let i = 0; i < messages.length; i++) if (messages[i].info.role === "user") user = i
  // Keep the current user bubble in history; all model/tool steps answering it
  // belong to the live bubble, even when individual tool messages completed.
  return { settled: messages.slice(0, user + 1), live: messages.slice(user + 1) }
}
