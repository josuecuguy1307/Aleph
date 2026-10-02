/** Extract the provider's explanation without rendering its transport envelope. */
export function userFacingError(raw: string | undefined, fallback: string): string {
  let value = (raw || "").trim();
  const status = value.match(/HTTP\s+(\d{3})/i)?.[1];
  for (let depth = 0; depth < 5; depth++) {
    const start = value.indexOf("{");
    if (start < 0) return value || fallback;
    const candidates = [value.slice(start), value.slice(start).split("\n")[0]];
    let message: string | undefined;
    for (const candidate of candidates) {
      try {
        const data = JSON.parse(candidate);
        const next = data?.error?.message ?? data?.message ?? data?.detail;
        if (typeof next === "string") { message = next; break; }
      } catch { /* Truncated envelopes must not leak into the reading surface. */ }
    }
    if (!message || message === value) return status ? `${fallback} (HTTP ${status})` : fallback;
    value = message.trim();
  }
  return fallback;
}
