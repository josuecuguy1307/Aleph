import path from "path"
import fs from "fs/promises"
import z from "zod"
import { Global } from "../global"
import { Log } from "../util/log"

// Outbound domain allow-list. A catalog of curated science-connector domain
// sets (each toggleable as a group) plus a free-form list of custom domains.
// Persisted as a single JSON document under the ~/.openscience data dir and readable
// by the backend via `Network.allowlist()`.
export namespace Network {
  const log = Log.create({ service: "settings.network" })

  export const Group = z.object({
    id: z.string(),
    label: z.string(),
    description: z.string(),
    domains: z.array(z.string()),
  })
  export type Group = z.infer<typeof Group>

  // Curated groups wired to the science connectors the agents actually reach.
  export const CATALOG: Group[] = [
    {
      id: "package-management",
      label: "Package management",
      description: "Python, R, JS, Rust package indexes and source hosting.",
      domains: [
        "pypi.org",
        "files.pythonhosted.org",
        "registry.npmjs.org",
        "conda.anaconda.org",
        "cran.r-project.org",
        "crates.io",
        "github.com",
        "raw.githubusercontent.com",
        "objects.githubusercontent.com",
      ],
    },
    {
      id: "ncbi-nih",
      label: "NCBI / NIH",
      description: "PubMed, Entrez E-utilities, and NIH data services.",
      domains: [
        "ncbi.nlm.nih.gov",
        "www.ncbi.nlm.nih.gov",
        "eutils.ncbi.nlm.nih.gov",
        "pubmed.ncbi.nlm.nih.gov",
        "ftp.ncbi.nlm.nih.gov",
        "nih.gov",
      ],
    },
    {
      id: "genomics-biology",
      label: "Genomics & biology",
      description: "Ensembl, UCSC Genome Browser, and EBI resources.",
      domains: [
        "ensembl.org",
        "rest.ensembl.org",
        "ucsc.edu",
        "genome.ucsc.edu",
        "genome-euro.ucsc.edu",
        "ebi.ac.uk",
        "www.ebi.ac.uk",
      ],
    },
    {
      id: "proteomics",
      label: "Proteomics",
      description: "UniProt, RCSB PDB, and AlphaFold structure services.",
      domains: [
        "uniprot.org",
        "rest.uniprot.org",
        "rcsb.org",
        "files.rcsb.org",
        "alphafold.ebi.ac.uk",
        "www.ebi.ac.uk",
      ],
    },
    {
      id: "literature-citations",
      label: "Literature & citations",
      description: "Preprint servers, Semantic Scholar, Crossref, and DOIs.",
      domains: [
        "arxiv.org",
        "biorxiv.org",
        "medrxiv.org",
        "semanticscholar.org",
        "api.semanticscholar.org",
        "crossref.org",
        "api.crossref.org",
        "doi.org",
        "europepmc.org",
      ],
    },
    {
      id: "clinical-pharma",
      label: "Clinical & pharma",
      description: "Clinical trials, drug databases, and regulatory agencies.",
      domains: ["clinicaltrials.gov", "go.drugbank.com", "fda.gov", "api.fda.gov", "who.int", "ema.europa.eu"],
    },
  ]

  export const State = z.object({
    // When false the allow-list is advisory only (agent may reach any domain).
    allowlistEnabled: z.boolean(),
    // Enabled catalog group ids.
    enabled: z.array(z.string()),
    // Custom user-added domains.
    custom: z.array(z.string()),
  })
  export type State = z.infer<typeof State>

  const file = path.join(Global.Path.data, "settings", "network.json")

  function defaultState(): State {
    return { allowlistEnabled: false, enabled: ["package-management"], custom: [] }
  }

  function normalize(domain: string): string {
    return domain.trim().toLowerCase().replace(/^\*\./, "").replace(/\.$/, "")
  }

  function domains(state: State): string[] {
    const result = new Set<string>(state.custom.map(normalize).filter(Boolean))
    for (const group of CATALOG) {
      if (!state.enabled.includes(group.id)) continue
      for (const domain of group.domains) result.add(normalize(domain))
    }
    return [...result].sort()
  }

  export function domainAllowed(hostname: string, allowlist: string[]): boolean {
    const host = normalize(hostname)
    return allowlist.map(normalize).some((domain) => host === domain || host.endsWith(`.${domain}`))
  }

  export async function get(): Promise<State> {
    const text = await Bun.file(file)
      .text()
      .catch(() => undefined)
    if (!text) return defaultState()
    try {
      const parsed = State.safeParse(JSON.parse(text))
      if (parsed.success) return parsed.data
    } catch (e) {
      log.error("failed to parse network state", { error: e })
    }
    return defaultState()
  }

  export async function set(state: State): Promise<State> {
    await fs.mkdir(path.dirname(file), { recursive: true })
    await Bun.write(file, JSON.stringify(state, null, 2))
    return state
  }

  // Effective flat list of allowed domains (enabled groups ∪ custom). Readable
  // by any backend caller that wants to gate outbound access.
  export async function allowlist(): Promise<string[]> {
    return domains(await get())
  }

  export async function assertAllowed(raw: string): Promise<void> {
    const state = await get()
    if (!state.allowlistEnabled) return
    let url: URL
    try {
      url = new URL(raw)
    } catch {
      throw new Error(`Invalid network URL: ${raw}`)
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new Error(`Network URL must use http or https: ${raw}`)
    }
    const allowed = domains(state)
    if (domainAllowed(url.hostname, allowed)) return
    throw new Error(`Network access to ${url.hostname} is not in the configured allow-list`)
  }

  /** The hostname the allow-list would block for this URL, or undefined when
   *  the URL is allowed (or enforcement is off). Still throws on invalid URLs
   *  so callers cannot smuggle malformed input past the gate. */
  export async function blocked(raw: string): Promise<string | undefined> {
    const state = await get()
    let url: URL
    try {
      url = new URL(raw)
    } catch {
      throw new Error(`Invalid network URL: ${raw}`)
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new Error(`Network URL must use http or https: ${raw}`)
    }
    if (!state.allowlistEnabled) return undefined
    if (domainAllowed(url.hostname, domains(state))) return undefined
    return normalize(url.hostname)
  }

  /** Add one domain to the persisted custom allow-list — the durable half of
   *  an "always allow" answer to a blocked-domain prompt, so the Network
   *  settings panel reflects exactly what was granted. */
  export async function allow(domain: string): Promise<State> {
    const state = await get()
    const host = normalize(domain)
    if (!host) return state
    if (domains(state).includes(host)) return state
    return set({ ...state, custom: [...state.custom, host] })
  }
}
