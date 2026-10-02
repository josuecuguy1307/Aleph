import { tool } from "@opencode-ai/plugin"
import { readSearchKey } from "../lib/research"

// doc.haus web-search tool — citation DISCOVERY for legal research. The agent
// uses this to FIND where a law lives (which act, which section, which official
// site) when it does not already know the citation; it then READS the law with
// webfetch against the official source, which stays fenced (lib/research.ts).
// Search results are leads, never authority.
//
// Built as our own tool rather than enabling upstream `websearch` because the
// upstream tool takes its provider/key from process env at boot; ours reads the
// firm's Exa key from WORKSPACE_ROOT/.preferences/preferences.json on every
// call, so a key pasted in Settings works immediately, no engine restart. The
// API shape mirrors upstream packages/core/src/tool/websearch.ts (Exa MCP
// endpoint).

const EXA_URL = "https://mcp.exa.ai/mcp"
const MAX_RESPONSE_BYTES = 256 * 1024

const UNCONFIGURED =
  `Web search is not configured: the firm has not added an Exa search API key. ` +
  `You can still retrieve law you can already cite — fetch it from the official source with webfetch ` +
  `(see the matter's jurisdiction pack <sources> and the legal-research skill). ` +
  `If you need to DISCOVER a citation you do not know, tell the user plainly that web search is not set up ` +
  `and that they can add an Exa API key in Settings > Drafting — it takes effect immediately. ` +
  `Do not guess the citation from memory.`

export default tool({
  description:
    "Search the web to FIND a legal citation or source you do not already know — which statute governs, the act name and section number, or the official page that carries it. Returns search results as leads, not authority: once you have the citation, retrieve the actual text from the official source with webfetch (legal-research skill) before relying on it. Requires the firm's Exa search key from Settings; if unconfigured, the tool says so.",
  args: {
    query: tool.schema.string().describe("Search query, e.g. 'California statute non-compete enforceability section'"),
    numResults: tool.schema.number().min(1).max(20).optional().describe("Number of results (default 8, max 20)"),
  },
  async execute(args) {
    const apiKey = readSearchKey()
    if (!apiKey)
      return {
        title: "Web search not configured",
        output: UNCONFIGURED,
        metadata: { configured: false },
      }

    const text = await callExa(apiKey, {
      query: args.query,
      type: "auto",
      numResults: args.numResults ?? 8,
      livecrawl: "fallback",
    })

    if (!text)
      return {
        title: `No results: ${args.query}`,
        output: "No search results found. Try a different query.",
        metadata: { configured: true, results: false },
      }
    return {
      title: `Web search: ${args.query}`,
      output:
        text +
        `\n\n[legal-research] These results are leads, not authority. Before relying on any law they mention, ` +
        `retrieve its current text from the official source with webfetch and cite what you retrieved.`,
      metadata: { configured: true, results: true },
    }
  },
})

async function callExa(apiKey: string, exaArgs: Record<string, unknown>) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 25_000)
  const res = await fetch(`${EXA_URL}?exaApiKey=${encodeURIComponent(apiKey)}`, {
    method: "POST",
    signal: controller.signal,
    headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name: "web_search_exa", arguments: exaArgs },
    }),
  }).finally(() => clearTimeout(timer))
  if (!res.ok) throw new Error(`Web search failed: ${res.status} ${res.statusText}`)
  const body = await res.text()
  if (Buffer.byteLength(body, "utf8") > MAX_RESPONSE_BYTES)
    throw new Error(`Web search response exceeded ${MAX_RESPONSE_BYTES} bytes`)
  return parseResponse(body)
}

// The MCP response arrives either as a plain JSON-RPC body or as SSE "data:"
// lines; the result text lives at result.content[].text in both cases.
function parseResponse(body: string) {
  const direct = parsePayload(body.trim())
  if (direct) return direct
  for (const line of body.split("\n")) {
    if (!line.startsWith("data: ")) continue
    const data = parsePayload(line.substring(6).trim())
    if (data) return data
  }
  return undefined
}

function parsePayload(payload: string) {
  if (!payload.startsWith("{")) return undefined
  const parsed = JSON.parse(payload) as { result?: { content?: { text?: string }[] } }
  return parsed.result?.content?.find((item) => item.text)?.text
}
