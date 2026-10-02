import path from "node:path"
import { ulid } from "ulid"
import z from "zod"
import { Instance } from "../project/instance"
import { ProjectLegacy } from "../project/legacy"
import { Provenance } from "../science/provenance/store"
import { Storage } from "../storage/storage"
import { ArtifactFile } from "./artifacts"

export namespace PublicationReview {
  export const Check = z.enum(["citation", "numeric", "figure", "provenance"])
  export type Check = z.infer<typeof Check>

  export const Severity = z.enum(["blocking", "major", "minor", "info"])
  export type Severity = z.infer<typeof Severity>

  export const FindingStatus = z.enum(["open", "resolved", "overridden"])
  export type FindingStatus = z.infer<typeof FindingStatus>

  export const Location = z.object({
    path: z.string(),
    line: z.number().int().positive().optional(),
  })
  export type Location = z.infer<typeof Location>

  export const Resolution = z.object({
    kind: z.enum(["resolved", "overridden"]),
    actor: z.string(),
    reason: z.string(),
    at: z.number(),
  })
  export type Resolution = z.infer<typeof Resolution>

  export const Finding = z.object({
    id: z.string(),
    check: Check,
    severity: Severity,
    status: FindingStatus,
    title: z.string(),
    detail: z.string(),
    evidence: z.string().array(),
    location: Location,
    resolution: Resolution.optional(),
  })
  export type Finding = z.infer<typeof Finding>

  export const Event = z.object({
    version: z.number().int().positive(),
    type: z.enum(["generated", "resolved", "overridden", "finalized"]),
    actor: z.string(),
    at: z.number(),
    findingID: z.string().optional(),
    reason: z.string().optional(),
  })
  export type Event = z.infer<typeof Event>

  export const Finalization = z.object({
    actor: z.string(),
    at: z.number(),
    artifactHash: z.string().regex(/^[a-f0-9]{64}$/),
  })
  export type Finalization = z.infer<typeof Finalization>

  export const Summary = z.object({
    total: z.number().int().nonnegative(),
    open: z.number().int().nonnegative(),
    blocking: z.number().int().nonnegative(),
    major: z.number().int().nonnegative(),
    minor: z.number().int().nonnegative(),
    info: z.number().int().nonnegative(),
    resolved: z.number().int().nonnegative(),
    overridden: z.number().int().nonnegative(),
  })
  export type Summary = z.infer<typeof Summary>

  export const Report = z.object({
    format: z.literal("openscience.publication-review.v1"),
    id: z.string(),
    projectID: z.string(),
    path: z.string(),
    artifactHash: z.string().regex(/^[a-f0-9]{64}$/),
    version: z.number().int().positive(),
    status: z.enum(["blocked", "warnings", "ready"]),
    summary: Summary,
    findings: Finding.array(),
    events: Event.array(),
    finalized: Finalization.optional(),
    createdAt: z.number(),
    updatedAt: z.number(),
  })
  export type Report = z.infer<typeof Report>

  export const State = Report.extend({
    stale: z.boolean(),
  })
  export type State = z.infer<typeof State>

  export const RunInput = z.object({
    path: z.string().trim().min(1).max(10_000),
    actor: z.string().trim().min(1).max(200).default("OpenScience"),
  })
  export type RunInput = z.infer<typeof RunInput>

  export const ResolveInput = z.object({
    status: z.enum(["resolved", "overridden"]),
    actor: z.string().trim().min(1).max(200),
    reason: z.string().trim().min(1).max(20_000),
  })
  export type ResolveInput = z.infer<typeof ResolveInput>

  export const FinalizeInput = z.object({
    actor: z.string().trim().min(1).max(200),
  })
  export type FinalizeInput = z.infer<typeof FinalizeInput>

  const prefix = () => ["publication_review", Instance.project.id]
  const key = (id: string) => [...prefix(), id]

  async function migrate() {
    await ProjectLegacy.adopt("publication_review", Instance.project.id, (value, projectID) => ({
      ...Report.parse(value),
      projectID,
    }))
  }

  export async function run(input: RunInput): Promise<Report> {
    await migrate()
    const parsed = RunInput.parse(input)
    const source = await target(parsed.path)
    if (![".md", ".markdown"].includes(path.extname(source.absolute).toLowerCase())) {
      throw new Error("Publication preflight currently requires a Markdown manuscript")
    }
    if (!(await Bun.file(source.absolute).exists())) {
      throw new Error(`Publication manuscript not found: ${parsed.path}`)
    }
    const [text, artifactHash, graph, provenance, audit] = await Promise.all([
      Bun.file(source.absolute).text(),
      digest(source.absolute),
      Provenance.project({
        projectID: Instance.project.id,
        directory: Instance.directory,
      }),
      ArtifactFile.provenance(Instance.worktree, source.relative),
      ArtifactFile.audit(Instance.worktree),
    ])
    const findings = [
      ...(await citations(text, source)),
      ...(await numbers(text, source)),
      ...(await figures(text, source, graph.nodes)),
      ...(await reproducibility(source, provenance, audit)),
    ]
    const now = Date.now()
    const report: Report = {
      format: "openscience.publication-review.v1",
      id: `review_${ulid()}`,
      projectID: Instance.project.id,
      path: source.relative,
      artifactHash,
      version: 1,
      status: status(findings),
      summary: summary(findings),
      findings: findings.toSorted(compare),
      events: [{ version: 1, type: "generated", actor: parsed.actor, at: now }],
      createdAt: now,
      updatedAt: now,
    }
    await Storage.write(key(report.id), report)
    return Report.parse(report)
  }

  export async function latest(filepath: string): Promise<Report | undefined> {
    return (await history(filepath)).at(-1)
  }

  export async function current(filepath: string): Promise<State | undefined> {
    const report = await latest(filepath)
    if (!report) return
    const source = await target(filepath)
    const stale =
      !(await Bun.file(source.absolute).exists()) ||
      (await digest(source.absolute).catch(() => "")) !== report.artifactHash
    return State.parse({ ...report, stale })
  }

  export async function history(filepath: string): Promise<Report[]> {
    await migrate()
    const source = await target(filepath)
    const keys = await Storage.list(prefix())
    const reports = await Promise.all(
      keys.map((item) => Storage.read<unknown>(item).then((value) => Report.parse(value))),
    )
    return reports
      .filter((report) => report.path === source.relative)
      .toSorted((a, b) => a.createdAt - b.createdAt || a.id.localeCompare(b.id))
  }

  export async function get(id: string): Promise<Report> {
    await migrate()
    return Report.parse(await Storage.read<unknown>(key(id)))
  }

  export async function resolve(id: string, findingID: string, input: ResolveInput): Promise<Report> {
    await migrate()
    const parsed = ResolveInput.parse(input)
    return Report.parse(
      await Storage.update<Report>(key(id), (report) => {
        if (report.finalized) throw new Error("A finalized publication preflight cannot be changed")
        const finding = report.findings.find((item) => item.id === findingID)
        if (!finding) throw new Error(`Review finding ${findingID} was not found`)
        const now = Date.now()
        finding.status = parsed.status
        finding.resolution = {
          kind: parsed.status,
          actor: parsed.actor,
          reason: parsed.reason,
          at: now,
        }
        report.version += 1
        report.updatedAt = now
        report.status = status(report.findings)
        report.summary = summary(report.findings)
        report.events.push({
          version: report.version,
          type: parsed.status,
          actor: parsed.actor,
          at: now,
          findingID,
          reason: parsed.reason,
        })
      }),
    )
  }

  export async function finalize(id: string, input: FinalizeInput): Promise<Report> {
    const parsed = FinalizeInput.parse(input)
    const current = await get(id)
    await assertCurrent(current)
    if (current.findings.some((finding) => finding.severity === "blocking" && finding.status === "open")) {
      throw new Error("Resolve or explicitly override all blocking findings before finalization")
    }
    return Report.parse(
      await Storage.update<Report>(key(id), (report) => {
        if (report.finalized) return
        const now = Date.now()
        report.version += 1
        report.updatedAt = now
        report.finalized = {
          actor: parsed.actor,
          at: now,
          artifactHash: report.artifactHash,
        }
        report.events.push({
          version: report.version,
          type: "finalized",
          actor: parsed.actor,
          at: now,
        })
      }),
    )
  }

  export async function assertReady(filepath: string, id: string, artifactHash?: string): Promise<Report> {
    const report = await get(id)
    const source = await target(filepath)
    if (report.path !== source.relative) throw new Error("The publication preflight belongs to a different manuscript")
    await assertCurrent(report, artifactHash)
    if (!report.finalized) throw new Error("The publication preflight has not been finalized")
    if (report.findings.some((finding) => finding.severity === "blocking" && finding.status === "open")) {
      throw new Error("The publication preflight still has open blocking findings")
    }
    return report
  }

  async function citations(text: string, source: Awaited<ReturnType<typeof target>>): Promise<Finding[]> {
    const lines = text.split(/\r?\n/)
    const definitions = new Set(
      lines.map((line) => /^\s*\[\^([^\]]+)\]:/.exec(line)?.[1]).filter((value): value is string => Boolean(value)),
    )
    const references = new Set<string>()
    for (const [index, line] of lines.entries()) {
      for (const match of line.matchAll(/\[\^([^\]]+)\](?!:)/g)) {
        if (definitions.has(match[1]!)) continue
        references.add(`${match[1]}\0${index + 1}`)
      }
    }
    const bib = await bibliography(text, source)
    const keys = new Set<string>()
    for (const file of bib) {
      const value = await Bun.file(file)
        .text()
        .catch(() => "")
      for (const match of value.matchAll(/@\w+\s*\{\s*([^,\s]+)\s*,/g)) keys.add(match[1]!)
    }
    const cites = new Map<string, number>()
    for (const [index, line] of lines.entries()) {
      for (const match of line.matchAll(/@([A-Za-z][A-Za-z0-9_.:+/-]*)/g)) {
        if (!cites.has(match[1]!)) cites.set(match[1]!, index + 1)
      }
    }
    const missing = await Promise.all(
      [...cites]
        .filter(([key]) => !keys.has(key))
        .map(([key, line]) =>
          finding({
            check: "citation",
            severity: "blocking",
            title: `Bibliography key @${key} is unresolved`,
            detail: "The manuscript cites a key that is absent from its local bibliography files.",
            evidence: bib.length
              ? bib.map((file) => path.relative(Instance.worktree, file).replaceAll("\\", "/"))
              : ["No local bibliography file was found."],
            location: { path: source.relative, line },
          }),
        ),
    )
    const footnotes = await Promise.all(
      [...references].map((value) => {
        const [label, line] = value.split("\0")
        return finding({
          check: "citation",
          severity: "blocking",
          title: `Footnote [^${label}] has no definition`,
          detail: "Add a matching footnote definition or remove the unresolved reference.",
          evidence: [`Referenced at ${source.relative}:${line}`],
          location: { path: source.relative, line: Number(line) },
        })
      }),
    )
    const placeholders = await Promise.all(
      lines.flatMap((line, index) => {
        if (!/\[(?:citation needed|cite|reference needed)\]|\bTODO\s*:?\s*cite\b/i.test(line)) return []
        return [
          finding({
            check: "citation",
            severity: "blocking",
            title: "Citation placeholder remains in the manuscript",
            detail: "Replace the placeholder with a resolvable source before publication.",
            evidence: [line.trim()],
            location: { path: source.relative, line: index + 1 },
          }),
        ]
      }),
    )
    return [...missing, ...footnotes, ...placeholders]
  }

  async function numbers(text: string, source: Awaited<ReturnType<typeof target>>): Promise<Finding[]> {
    const lines = text.split(/\r?\n/)
    return Promise.all(
      lines.flatMap((line, index) => {
        const claim =
          /\b\d+(?:\.\d+)?\s*%/.test(line) ||
          /\bp\s*(?:<|>|=|≤|≥)\s*0?\.\d+/i.test(line) ||
          /\b(?:confidence interval|CI)\b/i.test(line) ||
          /\b\d+(?:\.\d+)?\s*(?:mg|µg|μg|ng|kg|mL|µL|μL|mm|cm|nm|µm|μm|Hz|kDa)\b/.test(line)
        if (!claim) return []
        const traced =
          /@[A-Za-z][A-Za-z0-9_.:+/-]*/.test(line) ||
          /\b(?:figure|fig\.?|table|supplement(?:ary)?)\s*[A-Za-z0-9]/i.test(line) ||
          /\[[^\]]+\]\([^)]*\.(?:csv|tsv|json|jsonl|parquet|arrow|xlsx?|ipynb)(?:[?#][^)]*)?\)/i.test(line)
        if (traced) return []
        return [
          finding({
            check: "numeric",
            severity: "major",
            title: "Numeric claim has no inline evidence trace",
            detail:
              "Link this reported value to a citation, table, figure, notebook, or local data artifact so it can be independently checked.",
            evidence: [line.trim()],
            location: { path: source.relative, line: index + 1 },
          }),
        ]
      }),
    )
  }

  async function figures(
    text: string,
    source: Awaited<ReturnType<typeof target>>,
    nodes: Awaited<ReturnType<typeof Provenance.project>>["nodes"],
  ): Promise<Finding[]> {
    const lines = text.split(/\r?\n/)
    const output: Finding[] = []
    for (const [index, line] of lines.entries()) {
      for (const match of line.matchAll(/!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["'][^"']*["'])?\s*\)/g)) {
        const alt = match[1]!.trim()
        const value = (match[2] ?? match[3]!).trim()
        if (/^(?:https?:|data:)/i.test(value)) continue
        const absolute = path.resolve(path.dirname(source.absolute), decodeURIComponent(value.split(/[?#]/)[0]!))
        const relative = path.relative(Instance.worktree, absolute).replaceAll("\\", "/")
        const inside = await Instance.containsCanonicalPath(absolute)
        const exists = inside && (await Bun.file(absolute).exists())
        if (!exists) {
          output.push(
            await finding({
              check: "figure",
              severity: "blocking",
              title: `Figure ${value} is missing`,
              detail: inside
                ? "The local figure referenced by this manuscript does not exist."
                : "The figure reference resolves outside the opened project.",
              evidence: [relative],
              location: { path: source.relative, line: index + 1 },
            }),
          )
          continue
        }
        if (!alt) {
          output.push(
            await finding({
              check: "figure",
              severity: "minor",
              title: `Figure ${value} has no alternative text`,
              detail: "Add concise alternative text describing the scientific content of the figure.",
              evidence: [relative],
              location: { path: source.relative, line: index + 1 },
            }),
          )
        }
        const recorded = nodes.some((node) => {
          if (node.kind !== "artifact" || !("path" in node) || !node.path) return false
          const owner = typeof node.meta?.directory === "string" ? node.meta.directory : Instance.worktree
          const nodePath = path.isAbsolute(node.path) ? node.path : path.resolve(owner, node.path)
          return path.resolve(nodePath) === path.resolve(absolute)
        })
        if (recorded) continue
        output.push(
          await finding({
            check: "figure",
            severity: "major",
            title: `Figure ${value} has no recorded provenance`,
            detail: "Record the generating run, code, and source inputs for this local figure.",
            evidence: [relative, "No matching artifact node exists in the project provenance graph."],
            location: { path: source.relative, line: index + 1 },
          }),
        )
      }
    }
    return output
  }

  async function reproducibility(
    source: Awaited<ReturnType<typeof target>>,
    provenance: ArtifactFile.Provenance,
    audit: ArtifactFile.Audit,
  ): Promise<Finding[]> {
    const output: Finding[] = []
    if (!provenance.tracked || !provenance.commit) {
      output.push(
        await finding({
          check: "provenance",
          severity: "blocking",
          title: "Manuscript has no reachable Git snapshot",
          detail: "Track and commit the manuscript so the reviewed source can be recovered.",
          evidence: [`Git status: ${provenance.status}`],
          location: { path: source.relative },
        }),
      )
    } else if (provenance.dirty) {
      output.push(
        await finding({
          check: "provenance",
          severity: "blocking",
          title: "Manuscript differs from its recorded Git snapshot",
          detail: "Commit the preflight-checked manuscript bytes before marking the publication ready.",
          evidence: [`Git status: ${provenance.status}`, `Latest commit: ${provenance.commit.sha}`],
          location: { path: source.relative },
        }),
      )
    }
    const failures = audit.checks.filter((check) => check.status === "fail")
    for (const check of failures) {
      if (check.id === "git-repository" || check.id === "git-commit") continue
      output.push(
        await finding({
          check: "provenance",
          severity: "blocking",
          title: check.label,
          detail: check.detail,
          evidence: [`Project reproducibility check: ${check.id}`],
          location: { path: source.relative },
        }),
      )
    }
    const warnings = audit.checks.filter((check) => check.status === "warn")
    for (const check of warnings) {
      if (check.id === "git-clean" && provenance.dirty) continue
      output.push(
        await finding({
          check: "provenance",
          severity: "minor",
          title: check.label,
          detail: check.detail,
          evidence: [`Project reproducibility check: ${check.id}`],
          location: { path: source.relative },
        }),
      )
    }
    return output
  }

  async function bibliography(text: string, source: Awaited<ReturnType<typeof target>>): Promise<string[]> {
    const frontmatter = /^---\s*\n([\s\S]*?)\n---/m.exec(text)?.[1] ?? ""
    const declared = frontmatter.split(/\r?\n/).flatMap((line) => {
      const value = /^\s*bibliography\s*:\s*(.+)\s*$/i.exec(line)?.[1]
      if (!value) return []
      return value
        .replace(/^\[|\]$/g, "")
        .split(",")
        .map((item) => item.trim().replace(/^["']|["']$/g, ""))
        .filter(Boolean)
    })
    const candidates = [
      ...declared.map((file) => path.resolve(path.dirname(source.absolute), file)),
      path.join(path.dirname(source.absolute), "references.bib"),
      path.join(path.dirname(source.absolute), "bibliography.bib"),
      path.join(path.dirname(source.absolute), "refs.bib"),
      path.join(Instance.directory, "references.bib"),
      path.join(Instance.directory, "bibliography.bib"),
      path.join(Instance.directory, "refs.bib"),
      path.join(Instance.worktree, "references.bib"),
      path.join(Instance.worktree, "bibliography.bib"),
      path.join(Instance.worktree, "refs.bib"),
    ]
    const unique = [...new Set(candidates)]
    const safe = await Promise.all(
      unique.map(async (file) =>
        (await Instance.containsCanonicalPath(file)) && (await Bun.file(file).exists()) ? file : undefined,
      ),
    )
    return safe.filter((file): file is string => Boolean(file))
  }

  async function target(value: string) {
    const absolute = path.resolve(Instance.directory, value)
    if (!(await Instance.containsCanonicalPath(absolute))) {
      throw new Error(`Publication preflight target is outside the project: ${value}`)
    }
    return {
      absolute,
      relative: path.relative(Instance.worktree, absolute).replaceAll("\\", "/"),
    }
  }

  async function assertCurrent(report: Report, artifactHash?: string) {
    const absolute = path.resolve(Instance.worktree, report.path)
    if (!(await Instance.containsCanonicalPath(absolute))) {
      throw new Error("The preflight-checked manuscript is outside the current project")
    }
    if (!(await Bun.file(absolute).exists())) throw new Error("The preflight-checked manuscript no longer exists")
    if ((artifactHash ?? (await digest(absolute))) !== report.artifactHash) {
      throw new Error("The manuscript changed after this publication preflight was generated")
    }
  }

  async function finding(input: Omit<Finding, "id" | "status">): Promise<Finding> {
    return {
      ...input,
      id: `finding_${(await hash(JSON.stringify(stable(input)))).slice(0, 20)}`,
      status: "open",
    }
  }

  function summary(findings: Finding[]): Summary {
    return {
      total: findings.length,
      open: findings.filter((finding) => finding.status === "open").length,
      blocking: findings.filter((finding) => finding.severity === "blocking").length,
      major: findings.filter((finding) => finding.severity === "major").length,
      minor: findings.filter((finding) => finding.severity === "minor").length,
      info: findings.filter((finding) => finding.severity === "info").length,
      resolved: findings.filter((finding) => finding.status === "resolved").length,
      overridden: findings.filter((finding) => finding.status === "overridden").length,
    }
  }

  function status(findings: Finding[]): Report["status"] {
    if (findings.some((finding) => finding.severity === "blocking" && finding.status === "open")) return "blocked"
    if (findings.some((finding) => finding.status === "open")) return "warnings"
    return "ready"
  }

  function compare(a: Finding, b: Finding) {
    const rank: Record<Severity, number> = { blocking: 0, major: 1, minor: 2, info: 3 }
    return (
      rank[a.severity] - rank[b.severity] || (a.location.line ?? 0) - (b.location.line ?? 0) || a.id.localeCompare(b.id)
    )
  }

  function stable(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(stable)
    if (!value || typeof value !== "object") return value
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .toSorted(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, stable(item)]),
    )
  }

  async function digest(file: string) {
    const hasher = new Bun.CryptoHasher("sha256")
    const reader = Bun.file(file).stream().getReader()
    const feed = async (): Promise<void> => {
      const chunk = await reader.read()
      if (chunk.done) return
      hasher.update(chunk.value)
      return feed()
    }
    await feed()
    return hasher.digest("hex")
  }

  async function hash(value: string) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("")
  }
}
