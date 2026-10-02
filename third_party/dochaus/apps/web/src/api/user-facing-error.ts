// Keep provider envelopes and internal routing metadata out of the conversation.
// Preserve ordinary diagnostic messages; unwrap structured errors to their text.
export function userFacingError(value: string) {
  let message = value
  let structured = false
  for (let i = 0; i < 4; i++) {
    try {
      const input = message.trim()
      const start = input.indexOf("{")
      const parsed: unknown = JSON.parse(input.startsWith('"') ? input : start >= 0 ? input.slice(start) : input)
      if (typeof parsed === "string") { message = parsed; structured = true; continue }
      if (parsed && typeof parsed === "object") {
        const envelope = parsed as { error?: { message?: unknown }; message?: unknown }
        const next = envelope.error?.message ?? envelope.message
        structured = true
        if (typeof next === "string") { message = next; continue }
      }
    } catch { break }
    break
  }
  if (/usage limit|hit your.*limit|rate_limit|throttled|HTTP\s*429/i.test(message))
    return /Codex/i.test(message)
      ? "Codex alcanzó su límite de uso. Revisa su cuota o vuelve a intentarlo cuando esté disponible."
      : "El proveedor alcanzó su límite de uso. Revisa su cuota o vuelve a intentarlo cuando esté disponible."
  if (/^Load failed$|^Failed to fetch$/i.test(message.trim()))
    return "No se pudo conectar con el motor. Vuelve a abrir la conversación para comprobar el estado de la solicitud."
  if (structured && /[{}]|error_kind|brain_provider|turno_id/.test(message))
    return "El modelo no pudo completar la solicitud. Revisa su estado y vuelve a intentarlo."
  return message
}
