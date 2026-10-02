/**
 * RLM Artifacts — Object-level referencing for sparse context.
 *
 * Large data (DataFrames, analysis results, raw outputs) is stored on disk
 * and passed by reference. The LLM context holds only metadata + summary,
 * with actual data accessed via lazy loading in notebook/bash execution.
 */

import path from "path"
import fs from "fs/promises"
import { Global } from "@/global"
import { OpenScience } from "@/openscience"
import { ProvenanceEnvelope } from "@/science/provenance/envelope"
import { Provenance } from "@/science/provenance/store"
import { Log } from "@/util/log"
import { Lock } from "@/util/lock"
import type { RLMState } from "./state"

export namespace RLMArtifacts {
  const log = Log.create({ service: "rlm-artifacts" })
  const ARTIFACTS_DIR = path.join(Global.Path.data, "artifacts")
  const VERSIONS_DIR = ".versions"
  const TTL_MS = 7 * 24 * 60 * 60 * 1000 // 7 days

  function segment(value: string, label: string) {
    if (
      !value ||
      value === "." ||
      value === ".." ||
      value.includes("/") ||
      value.includes("\\") ||
      value.includes("\0")
    ) {
      throw new Error(`Invalid artifact ${label}: ${value}`)
    }
    return value
  }

  function session(sessionID: string) {
    return path.join(ARTIFACTS_DIR, segment(sessionID, "session ID"))
  }

  function current(sessionID: string, artifactID: string) {
    return path.join(session(sessionID), `${segment(artifactID, "ID")}.dat`)
  }

  function directory(sessionID: string, artifactID: string) {
    return path.join(session(sessionID), VERSIONS_DIR, segment(artifactID, "ID"))
  }

  function content(sessionID: string, artifactID: string, versionID: string) {
    return path.join(directory(sessionID, artifactID), `${segment(versionID, "version ID")}.dat`)
  }

  function metadata(sessionID: string, artifactID: string, versionID: string) {
    return path.join(directory(sessionID, artifactID), `${segment(versionID, "version ID")}.json`)
  }

  function digest(value: Uint8Array) {
    const hasher = new Bun.CryptoHasher("sha256")
    hasher.update(value)
    return hasher.digest("hex")
  }

  async function touch(filepath: string) {
    const stat = await fs.stat(filepath).catch(() => undefined)
    if (!stat) return
    await fs.utimes(filepath, new Date(), stat.mtime).catch(() => undefined)
  }

  function clean<T>(value: T): T {
    return JSON.parse(OpenScience.redactSecrets(JSON.stringify(value))) as T
  }

  function retention(createdAt: number): RLMState.ArtifactRetention {
    return {
      status: "ephemeral",
      policy: "session_ttl",
      expiresAt: createdAt + TTL_MS,
    }
  }

  function source(value: unknown): RLMState.ArtifactSource | undefined {
    if (!value || typeof value !== "object") return
    const record = value as Record<string, unknown>
    const result = {
      ...(typeof record.projectID === "string" ? { projectID: record.projectID } : {}),
      ...(typeof record.agent === "string" ? { agent: record.agent } : {}),
      ...(typeof record.messageID === "string" ? { messageID: record.messageID } : {}),
      ...(typeof record.callID === "string" ? { callID: record.callID } : {}),
      ...(typeof record.runID === "string" ? { runID: record.runID } : {}),
      ...(typeof record.provenanceID === "string" ? { provenanceID: record.provenanceID } : {}),
    }
    return Object.keys(result).length ? clean(result) : undefined
  }

  function envelope(record: Omit<RLMState.ArtifactVersion, "provenance">): RLMState.ArtifactVersion["provenance"] {
    return ProvenanceEnvelope.create({
      kind: "artifact_version",
      projectID: record.source?.projectID,
      sessionID: record.sessionID,
      runID: record.source?.runID ?? record.source?.callID,
      status: "succeeded",
      outputs: [
        ProvenanceEnvelope.output({
          kind: "artifact",
          label: record.summary,
          sha256: record.sha256,
          size: record.size,
          artifactID: record.artifactID,
          path: record.path,
          versionID: record.id,
          version: record.version,
          createdAt: record.createdAt,
        }),
      ],
      createdAt: record.createdAt,
      completedAt: record.createdAt,
    })
  }

  function normalize(
    value: Partial<RLMState.ArtifactVersion>,
    sessionID: string,
    artifactID: string,
    versionID: string,
  ): RLMState.ArtifactVersion {
    const attribution = source(value.source)
    const base = {
      id: versionID,
      artifactID,
      sessionID,
      version: value.version!,
      createdAt: value.createdAt!,
      type: value.type!,
      summary: value.summary!,
      size: value.size!,
      sha256: value.sha256!,
      path: content(sessionID, artifactID, versionID),
      retention:
        value.retention?.status === "durable" && value.retention.policy === "durable"
          ? { status: "durable" as const, policy: "durable" as const }
          : value.retention?.status === "ephemeral" &&
              value.retention.policy === "session_ttl" &&
              typeof value.retention.expiresAt === "number"
            ? value.retention
            : retention(value.createdAt!),
      ...(attribution ? { source: attribution } : {}),
    }
    const parsed = ProvenanceEnvelope.Schema.safeParse(value.provenance)
    return {
      ...base,
      provenance: parsed.success ? clean(parsed.data) : envelope(base),
    }
  }

  async function info(sessionID: string, artifactID: string, versionID: string) {
    const record = await Bun.file(metadata(sessionID, artifactID, versionID))
      .json()
      .catch(() => null)
    if (!record || typeof record !== "object") return null
    const value = record as Partial<RLMState.ArtifactVersion>
    if (
      value.id !== versionID ||
      value.artifactID !== artifactID ||
      value.sessionID !== sessionID ||
      typeof value.version !== "number" ||
      typeof value.createdAt !== "number" ||
      typeof value.type !== "string" ||
      typeof value.summary !== "string" ||
      typeof value.size !== "number" ||
      typeof value.sha256 !== "string"
    ) {
      return null
    }
    return normalize(value, sessionID, artifactID, versionID)
  }

  async function append(record: RLMState.ArtifactVersion, bytes: Uint8Array) {
    const dir = directory(record.sessionID, record.artifactID)
    const metadataPath = metadata(record.sessionID, record.artifactID, record.id)
    await fs.mkdir(dir, { recursive: true })
    await fs.writeFile(record.path, bytes, { flag: "wx" })
    await fs
      .writeFile(metadataPath, JSON.stringify(record, null, 2), { encoding: "utf8", flag: "wx" })
      .catch(async (error) => {
        await fs.unlink(record.path).catch(() => undefined)
        throw error
      })
  }

  async function trace(record: RLMState.ArtifactVersion) {
    const node = await Provenance.record({
      id: record.id,
      kind: "artifact",
      label: record.summary,
      artifactType: record.type,
      path: record.path,
      contentHash: record.sha256,
      size: record.size,
      provenance: record.provenance,
      meta: {
        projectID: record.source?.projectID,
        sessionID: record.sessionID,
        artifactID: record.artifactID,
        versionID: record.id,
        version: record.version,
        retention: record.retention,
        ...(record.source?.messageID !== undefined ? { messageID: record.source.messageID } : {}),
        ...(record.source?.callID !== undefined ? { callID: record.source.callID } : {}),
      },
    } as Parameters<typeof Provenance.record>[0])
    const parent = record.source?.provenanceID
    if (!parent || !(await Provenance.get(parent))) return
    await Provenance.link({ from: parent, to: node.id, relation: "produced" })
  }

  async function save(
    sessionID: string,
    artifactID: string,
    body: string,
    input: {
      type?: string
      summary?: string
      source?: RLMState.ArtifactSource
      create?: boolean
      durable?: boolean
    },
  ): Promise<RLMState.ArtifactRef | null> {
    const filepath = current(sessionID, artifactID)
    await fs.mkdir(path.dirname(filepath), { recursive: true })
    using _ = await Lock.write(filepath)
    await OpenScience.refreshByokSecrets()
    const exists = await Bun.file(filepath).exists()
    if (input.create && exists) throw new Error(`Artifact already exists: ${artifactID}`)
    if (!input.create && !exists) return null

    const history = await listVersions(sessionID, artifactID)
    const prior = await (async () => {
      if (history.length || input.create) return history
      const raw = await Bun.file(filepath).text()
      const bytes = new TextEncoder().encode(OpenScience.redactSecrets(raw))
      const stat = await fs.stat(filepath)
      const createdAt = Math.trunc(stat.mtimeMs)
      const id = `ver-${createdAt}-${crypto.randomUUID().slice(0, 12)}`
      const base = {
        id,
        artifactID,
        sessionID,
        version: 1,
        createdAt,
        type: "unknown",
        summary: `Artifact ${artifactID}.dat`,
        size: bytes.byteLength,
        sha256: digest(bytes),
        path: content(sessionID, artifactID, id),
        retention: retention(createdAt),
      }
      const record: RLMState.ArtifactVersion = {
        ...base,
        provenance: envelope(base),
      }
      await append(record, bytes)
      await trace(record)
      return [record]
    })()
    const version = (prior[0]?.version ?? 0) + 1
    const now = Date.now()
    const versionID = `ver-${now}-${crypto.randomUUID().slice(0, 12)}`
    const versionPath = content(sessionID, artifactID, versionID)
    const bytes = new TextEncoder().encode(OpenScience.redactSecrets(body))
    const type = OpenScience.redactSecrets(input.type ?? prior[0]?.type ?? "unknown")
    const summary = OpenScience.redactSecrets(input.summary ?? prior[0]?.summary ?? `Artifact ${artifactID}`)
    const attribution = source(input.source)
    const base = {
      id: versionID,
      artifactID,
      sessionID,
      version,
      createdAt: now,
      type,
      summary,
      size: bytes.byteLength,
      sha256: digest(bytes),
      path: versionPath,
      retention: input.durable ? ({ status: "durable", policy: "durable" } as const) : retention(now),
      ...(attribution ? { source: attribution } : {}),
    }
    const record: RLMState.ArtifactVersion = {
      ...base,
      provenance: envelope(base),
    }

    await append(record, bytes)
    await trace(record)
    await Bun.write(filepath, bytes)
    log.info(input.create ? "artifact registered" : "artifact updated", {
      sessionID,
      id: artifactID,
      versionID,
      version,
      type,
      size: bytes.byteLength,
    })
    return {
      id: artifactID,
      type,
      summary,
      path: filepath,
      versionID,
      version,
      createdAt: now,
    }
  }

  /** Register an artifact — writes content to disk, returns a reference. */
  export async function register(
    sessionID: string,
    type: string,
    body: string,
    summary?: string,
    source?: RLMState.ArtifactSource,
    options: { durable?: boolean } = {},
  ): Promise<RLMState.ArtifactRef> {
    const id = `art-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    return (await save(sessionID, id, body, {
      type,
      summary: summary ?? `${type} artifact (${body.length} bytes)`,
      source,
      create: true,
      durable: options.durable,
    }))!
  }

  /** Update an artifact head while retaining every prior immutable version. */
  export async function update(
    sessionID: string,
    artifactID: string,
    body: string,
    input: {
      type?: string
      summary?: string
      source?: RLMState.ArtifactSource
      durable?: boolean
    } = {},
  ): Promise<RLMState.ArtifactRef | null> {
    return save(sessionID, artifactID, body, input)
  }

  /** Promote one immutable version (default: the head) to durable retention so
   *  cleanup never expires it. This is what an explicit "save" means. */
  export async function retain(
    sessionID: string,
    artifactID: string,
    versionID?: string,
  ): Promise<RLMState.ArtifactVersion | null> {
    const target = versionID ?? (await listVersions(sessionID, artifactID))[0]?.id
    if (!target) return null
    const record = await info(sessionID, artifactID, target)
    if (!record) return null
    if (record.retention.status === "durable") return record
    const next: RLMState.ArtifactVersion = { ...record, retention: { status: "durable", policy: "durable" } }
    await fs.writeFile(metadata(sessionID, artifactID, target), JSON.stringify(next, null, 2), "utf8")
    log.info("artifact version retained", { sessionID, id: artifactID, versionID: target })
    return next
  }

  /** Resolve an artifact — reads full content from disk (lazy loading). */
  export async function resolve(sessionID: string, artifactID: string): Promise<string | null> {
    const filepath = current(sessionID, artifactID)
    const body = await Bun.file(filepath)
      .text()
      .catch(() => {
        log.warn("artifact not found", { sessionID, id: artifactID })
        return null
      })
    if (body === null) return null
    const version = (await listVersions(sessionID, artifactID))[0]
    await touch(version?.path ?? filepath)
    return body
  }

  /** List immutable versions, newest first. */
  export async function listVersions(sessionID: string, artifactID: string): Promise<RLMState.ArtifactVersion[]> {
    const dir = directory(sessionID, artifactID)
    const files = await fs.readdir(dir).catch(() => [])
    const records = await Promise.all(
      files
        .filter((file) => file.endsWith(".json"))
        .map((file) => info(sessionID, artifactID, file.slice(0, -".json".length))),
    )
    return records
      .filter((record): record is RLMState.ArtifactVersion => record !== null)
      .toSorted((a, b) => b.version - a.version)
  }

  /** Read one immutable version and its persisted attribution metadata. */
  export async function readVersion(
    sessionID: string,
    artifactID: string,
    versionID: string,
  ): Promise<{ info: RLMState.ArtifactVersion; content: string } | null> {
    const record = await info(sessionID, artifactID, versionID)
    if (!record) return null
    const bytes = await Bun.file(record.path)
      .bytes()
      .catch(() => null)
    if (bytes === null) return null
    if (digest(bytes) !== record.sha256) {
      log.warn("artifact version hash mismatch", { sessionID, artifactID, versionID })
      return null
    }
    await touch(record.path)
    return { info: record, content: new TextDecoder().decode(bytes) }
  }

  /** List all artifacts for a session. */
  export async function list(sessionID: string): Promise<RLMState.ArtifactRef[]> {
    const dir = session(sessionID)
    const files = await fs.readdir(dir).catch(() => [])
    return Promise.all(
      files
        .filter((file) => file.endsWith(".dat"))
        .map(async (file) => {
          const artifactID = file.slice(0, -".dat".length)
          const version = (await listVersions(sessionID, artifactID))[0]
          if (!version) {
            return {
              id: artifactID,
              type: "unknown",
              summary: `Artifact ${file}`,
              path: path.join(dir, file),
            }
          }
          return {
            id: artifactID,
            type: version.type,
            summary: version.summary,
            path: path.join(dir, file),
            versionID: version.id,
            version: version.version,
            createdAt: version.createdAt,
          }
        }),
    )
  }

  /** Cleanup expired ephemeral versions while preserving durable and recently active history. */
  export async function cleanup(): Promise<void> {
    try {
      const exists = await fs.stat(ARTIFACTS_DIR).catch(() => null)
      if (!exists) return

      const sessions = await fs.readdir(ARTIFACTS_DIR)
      const now = Date.now()
      const cleaned: string[] = []

      for (const sessionID of sessions) {
        const dir = path.join(ARTIFACTS_DIR, sessionID)
        const stat = await fs.stat(dir).catch(() => null)
        if (!stat?.isDirectory()) continue

        const files = await fs.readdir(dir).catch(() => [])
        const histories = await fs.readdir(path.join(dir, VERSIONS_DIR), { withFileTypes: true }).catch(() => [])
        const artifacts = new Set([
          ...files.filter((file) => file.endsWith(".dat")).map((file) => file.slice(0, -".dat".length)),
          ...histories.filter((entry) => entry.isDirectory()).map((entry) => entry.name),
        ])

        for (const artifactID of artifacts) {
          const filepath = current(sessionID, artifactID)
          using _ = await Lock.write(filepath)
          const versions = await listVersions(sessionID, artifactID)
          if (!versions.length) {
            const head = await fs.stat(filepath).catch(() => undefined)
            if (!head) {
              await fs.rm(directory(sessionID, artifactID), { recursive: true, force: true })
              continue
            }
            const active = Math.max(head.atimeMs, head.mtimeMs)
            if (active + TTL_MS > now) continue
            await fs.rm(filepath, { force: true })
            cleaned.push(`${sessionID}/${artifactID}`)
            continue
          }

          const states = await Promise.all(
            versions.map(async (version) => {
              if (version.retention.status === "durable") return { version, expired: false }
              const file = await fs.stat(version.path).catch(() => undefined)
              const active = Math.max(version.createdAt, file?.atimeMs ?? 0, file?.mtimeMs ?? 0)
              const expiresAt = Math.max(version.retention.expiresAt ?? 0, active + TTL_MS)
              return { version, expired: expiresAt <= now }
            }),
          )
          const expired = states.filter((state) => state.expired).map((state) => state.version)
          const remaining = states.filter((state) => !state.expired).map((state) => state.version)
          await Promise.all(
            expired.flatMap((version) => [
              fs.rm(version.path, { force: true }),
              fs.rm(metadata(sessionID, artifactID, version.id), { force: true }),
            ]),
          )
          cleaned.push(...expired.map((version) => `${sessionID}/${artifactID}/${version.id}`))

          if (!remaining.length) {
            await Promise.all([
              fs.rm(filepath, { force: true }),
              fs.rm(directory(sessionID, artifactID), { recursive: true, force: true }),
            ])
            continue
          }

          const head = await Bun.file(filepath).exists()
          if (head && remaining[0]!.id === versions[0]!.id) continue
          const activity = await fs.stat(remaining[0]!.path).catch(() => undefined)
          const bytes = await Bun.file(remaining[0]!.path)
            .bytes()
            .catch(() => undefined)
          if (activity) {
            await fs.utimes(remaining[0]!.path, activity.atime, activity.mtime).catch(() => undefined)
          }
          if (!bytes || digest(bytes) !== remaining[0]!.sha256) {
            await fs.rm(filepath, { force: true })
            log.warn("could not restore artifact head from retained version", {
              sessionID,
              artifactID,
              versionID: remaining[0]!.id,
            })
            continue
          }
          await Bun.write(filepath, bytes)
        }

        const root = path.join(dir, VERSIONS_DIR)
        const history = await fs.readdir(root).catch(() => [])
        if (!history.length) await fs.rm(root, { recursive: true, force: true })
        const empty = (await fs.readdir(dir).catch(() => [])).length === 0
        if (empty) await fs.rm(dir, { recursive: true, force: true })
      }

      if (cleaned.length > 0) {
        log.info("cleaned expired artifacts", { count: cleaned.length })
      }
    } catch (e) {
      log.warn("artifact cleanup error", { error: e instanceof Error ? e.message : String(e) })
    }
  }
}
