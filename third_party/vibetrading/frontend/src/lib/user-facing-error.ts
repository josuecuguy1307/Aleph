/** Keep transport envelopes out of the message reading surface. */
export function userFacingError(raw: string, fallback: string): string {
  let value = raw.trim();
  const status = value.match(/HTTP\s+(\d{3})/i)?.[1];
  for (let depth = 0; depth < 5; depth++) {
    const start = value.indexOf("{");
    if (start < 0) return value || fallback;
    let message: string | undefined;
    for (const candidate of [value.slice(start), value.slice(start).split("\n")[0]]) {
      try {
        const data = JSON.parse(candidate);
        const next = data?.error?.message ?? data?.message ?? data?.detail;
        if (typeof next === "string") { message = next; break; }
      } catch { /* A truncated envelope is not a user-facing explanation. */ }
    }
    if (!message || message === value) return status ? `${fallback} (HTTP ${status})` : fallback;
    value = message.trim();
  }
  return fallback;
}
