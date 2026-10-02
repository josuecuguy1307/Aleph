// Thin JSON helper for settings panels that call NEW local-server routes not
// yet in the generated SDK (settings/credentials, settings/storage). Targets
// the same loopback base URL the SDK uses; the app origin is allow-listed by
// the server's host/origin guard, so a direct fetch is accepted.
export async function settingsApi<T>(
  base: string,
  fetchFn: typeof fetch,
  path: string,
  init?: RequestInit,
): Promise<T> {
  // Hono's mounted settings routes are strict: `/settings/local` exists while
  // `/settings/local/` falls through to the SPA shell. Canonicalize route
  // roots here so callers can never turn an HTML fallback into a JSON error.
  const normalizedPath = path === "/" ? "" : path.replace(/\/+$/, "")
  const res = await fetchFn(`${base.replace(/\/+$/, "")}${normalizedPath}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "")
    throw new Error(text || `${res.status} ${res.statusText}`)
  }
  if (res.status === 204) return undefined as T
  const contentType = res.headers.get("content-type") ?? ""
  if (!contentType.includes("application/json")) {
    throw new Error(`Expected JSON from ${path}, but got ${res.status} (${contentType || "no content-type"})`)
  }
  return (await res.json()) as T
}
