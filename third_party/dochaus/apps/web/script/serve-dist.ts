import path from "node:path"

const args = process.argv.slice(2)
const portIndex = args.indexOf("--port")
const port = Number(portIndex >= 0 ? args[portIndex + 1] : 0)
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("Aleph Legal web: falta --port válido")
}

const dist = path.resolve(import.meta.dir, "..", "dist")
const index = Bun.file(path.join(dist, "index.html"))
if (!(await index.exists())) {
  throw new Error("Aleph Legal web: falta apps/web/dist; el build debe hornear la UI")
}
const opencode = process.env.OPENCODE_URL
const ingest = process.env.INGEST_URL
if (!opencode || !ingest) {
  throw new Error("Aleph Legal web: faltan OPENCODE_URL e INGEST_URL del launcher")
}

Bun.serve({
  hostname: "127.0.0.1",
  port,
  async fetch(request) {
    const incoming = new URL(request.url)
    const pathname = decodeURIComponent(incoming.pathname)
    const proxy = pathname.startsWith("/opencode/") || pathname === "/opencode"
      ? opencode
      : pathname.startsWith("/ingest/") || pathname === "/ingest"
        ? ingest
        : undefined
    if (proxy) {
      const suffix = pathname.replace(/^\/(opencode|ingest)/, "") || "/"
      // [ALEPH · PARCHE DE INSTRUMENTO — NO ES PARTE DE NINGUNA OBRA, SE REVIERTE]
      // `fetch` de Bun YA descomprime el cuerpo del upstream, pero la Response conserva
      // su `content-encoding: gzip`. Devolverla tal cual le miente al navegador: Chromium
      // le cree la cabecera, intenta descomprimir un JSON plano y tira
      // ERR_CONTENT_DECODING_FAILED en /opencode/session y /opencode/agent — con eso la
      // lista de conversaciones queda vacía y el composer se traba después de un turno.
      const upstream = await fetch(new Request(proxy + suffix + incoming.search, request))
      const headers = new Headers(upstream.headers)
      headers.delete("content-encoding")
      headers.delete("content-length")
      return new Response(upstream.body, { status: upstream.status,
                                           statusText: upstream.statusText, headers })
    }
    const candidate = path.resolve(dist, "." + (pathname === "/" ? "/index.html" : pathname))
    if (!candidate.startsWith(dist + path.sep) && candidate !== path.join(dist, "index.html")) {
      return new Response("Not found", { status: 404 })
    }
    const asset = Bun.file(candidate)
    if (await asset.exists()) return new Response(asset)
    if (!path.extname(pathname)) return new Response(index)
    return new Response("Not found", { status: 404 })
  },
})

await new Promise(() => {})
