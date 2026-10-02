// Markdown asset resolution. Relative image references inside previewed
// markdown or chat output would otherwise resolve against the SPA origin and
// 404 — rewrite them to the backend /file/raw endpoint instead. Absolute
// http(s)/data:/blob: URLs, protocol-relative URLs, anchors, and root paths
// pass through untouched.

const absolute = /^(?:[a-z][a-z0-9+.-]*:|\/\/|#|\/)/i

function clean(path: string): string {
  return path
    .replaceAll("\\", "/")
    .replace(/^(?:\.\/)+/, "")
    .replace(/\/+/g, "/")
}

function decode(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

/** Resolve a reference against the directory containing `base`, collapsing `.` and `..`. */
export function resolvePath(base: string, reference: string): string {
  const parts = [...clean(base).split("/").slice(0, -1), ...clean(reference).split("/")]
  return parts
    .reduce<string[]>((result, part) => {
      if (!part || part === ".") return result
      if (part === "..") {
        result.pop()
        return result
      }
      result.push(part)
      return result
    }, [])
    .join("/")
}

/**
 * Rewrite one image reference to a served file URL. Relative paths resolve
 * against the directory of `base` (the previewed file; omit `base` to resolve
 * against the workspace root) and run through `url` — typically
 * `(path) => sdk.request.url("/file/raw", { path, sessionID })`.
 */
export function assetUrl(src: string, input: { base?: string; url: (path: string) => string }): string {
  if (absolute.test(src)) return src
  return input.url(resolvePath(input.base ?? "", decode(src)))
}
