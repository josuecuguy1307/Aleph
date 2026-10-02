import { afterEach, describe, expect, test } from "bun:test"
import fs from "node:fs/promises"
import path from "node:path"
import { Global } from "../../src/global"
import { OpenScience } from "../../src/openscience"
import { Instance } from "../../src/project/instance"
import { KernelRuntime } from "../../src/science/kernel/registry"
import { Provenance } from "../../src/science/provenance/store"
import { RLMArtifacts } from "../../src/session/rlm/artifacts"
import { Session } from "../../src/session"
import { ArtifactTool } from "../../src/tool/artifact"
import type { Tool } from "../../src/tool/tool"
import { tmpdir, trustProject } from "../fixture/fixture"

const sessions = new Set<string>()

function session() {
  const id = `ses_artifact_${crypto.randomUUID()}`
  sessions.add(id)
  return id
}

function context(sessionID: string): Tool.Context {
  return {
    sessionID,
    messageID: "msg_artifact_test",
    callID: "call_artifact_test",
    agent: "research",
    abort: AbortSignal.timeout(30_000),
    extra: {},
    messages: [],
    metadata() {},
    async ask() {},
  }
}

afterEach(async () => {
  await Promise.all(
    [...sessions].map((sessionID) =>
      fs.rm(path.join(Global.Path.data, "artifacts", sessionID), { recursive: true, force: true }),
    ),
  )
  sessions.clear()
})

describe("RLMArtifacts versions", () => {
  test("updates the head without overwriting immutable content or attribution records", async () => {
    const sessionID = session()
    const first = await RLMArtifacts.register(sessionID, "analysis", "first result", "Result table", {
      agent: "biology",
      messageID: "msg_first",
      callID: "call_first",
    })
    const initial = await RLMArtifacts.listVersions(sessionID, first.id)

    expect(initial).toHaveLength(1)
    expect(initial[0]).toMatchObject({
      id: first.versionID,
      artifactID: first.id,
      sessionID,
      version: 1,
      type: "analysis",
      summary: "Result table",
      size: 12,
      source: {
        agent: "biology",
        messageID: "msg_first",
        callID: "call_first",
      },
    })
    expect(initial[0]?.createdAt).toBeGreaterThan(0)
    expect(initial[0]?.sha256).toMatch(/^[a-f0-9]{64}$/)
    expect(initial[0]?.retention).toEqual({
      status: "ephemeral",
      policy: "session_ttl",
      expiresAt: initial[0]!.createdAt + 7 * 24 * 60 * 60 * 1000,
    })
    expect(initial[0]?.provenance).toMatchObject({
      format: "openscience.provenance.v1",
      kind: "artifact_version",
      identity: {
        session_id: { status: "available", value: sessionID },
      },
      outputs: {
        status: "succeeded",
        items: [
          {
            artifact_id: { status: "available", value: first.id },
            version_id: { status: "available", value: first.versionID },
            version: { status: "available", value: 1 },
            sha256: initial[0]?.sha256,
          },
        ],
      },
    })

    const content = await Bun.file(initial[0]!.path).text()
    const metadata = await Bun.file(initial[0]!.path.replace(/\.dat$/, ".json")).text()
    const second = await RLMArtifacts.update(sessionID, first.id, "second result", {
      source: { agent: "research", messageID: "msg_second" },
    })

    expect(second).toMatchObject({
      id: first.id,
      type: "analysis",
      summary: "Result table",
      version: 2,
    })
    expect(second?.versionID).not.toBe(first.versionID)
    expect(await RLMArtifacts.resolve(sessionID, first.id)).toBe("second result")

    const versions = await RLMArtifacts.listVersions(sessionID, first.id)
    expect(versions.map((version) => [version.id, version.version])).toEqual([
      [second!.versionID!, 2],
      [first.versionID!, 1],
    ])
    expect((await RLMArtifacts.listVersions(sessionID, first.id)).map((version) => version.id)).toEqual(
      versions.map((version) => version.id),
    )
    expect(await RLMArtifacts.readVersion(sessionID, first.id, first.versionID!)).toMatchObject({
      info: { id: first.versionID, version: 1 },
      content: "first result",
    })
    expect(await RLMArtifacts.readVersion(sessionID, first.id, second!.versionID!)).toMatchObject({
      info: {
        id: second?.versionID,
        version: 2,
        source: { agent: "research", messageID: "msg_second" },
      },
      content: "second result",
    })
    expect(await Bun.file(initial[0]!.path).text()).toBe(content)
    expect(await Bun.file(initial[0]!.path.replace(/\.dat$/, ".json")).text()).toBe(metadata)

    await Bun.write(initial[0]!.path, "tampered")
    expect(await RLMArtifacts.readVersion(sessionID, first.id, first.versionID!)).toBeNull()
  })

  test("preserves resolve and list behavior for legacy head-only artifacts", async () => {
    const sessionID = session()
    const dir = path.join(Global.Path.data, "artifacts", sessionID)
    await fs.mkdir(dir, { recursive: true })
    await Bun.write(path.join(dir, "art-legacy.dat"), "legacy content")

    expect(await RLMArtifacts.resolve(sessionID, "art-legacy")).toBe("legacy content")
    expect(await RLMArtifacts.list(sessionID)).toEqual([
      {
        id: "art-legacy",
        type: "unknown",
        summary: "Artifact art-legacy.dat",
        path: path.join(dir, "art-legacy.dat"),
      },
    ])
    expect(await RLMArtifacts.listVersions(sessionID, "art-legacy")).toEqual([])

    const updated = await RLMArtifacts.update(sessionID, "art-legacy", "new content", {
      type: "analysis",
      summary: "Migrated artifact",
    })
    const versions = await RLMArtifacts.listVersions(sessionID, "art-legacy")

    expect(updated).toMatchObject({ version: 2, type: "analysis", summary: "Migrated artifact" })
    expect(versions.map((version) => version.version)).toEqual([2, 1])
    expect(await RLMArtifacts.readVersion(sessionID, "art-legacy", versions[1]!.id)).toMatchObject({
      info: {
        artifactID: "art-legacy",
        version: 1,
        type: "unknown",
        summary: "Artifact art-legacy.dat",
        retention: {
          status: "ephemeral",
          policy: "session_ttl",
          expiresAt: expect.any(Number),
        },
        provenance: {
          format: "openscience.provenance.v1",
          kind: "artifact_version",
          identity: {
            session_id: { status: "available", value: sessionID },
          },
        },
      },
      content: "legacy content",
    })
  })

  test("normalizes pre-provenance version records without rewriting historical metadata", async () => {
    const sessionID = session()
    const artifactID = "art-versioned-legacy"
    const versionID = "ver-versioned-legacy"
    const dir = path.join(Global.Path.data, "artifacts", sessionID)
    const history = path.join(dir, ".versions", artifactID)
    const createdAt = Date.now() - 1_000
    const record = {
      id: versionID,
      artifactID,
      sessionID,
      version: 1,
      createdAt,
      type: "analysis",
      summary: "Legacy version",
      size: 14,
      sha256: "a6021b27f58f561ad60c4127e4626d3381800178ae35efdd0c2867d04c404f48",
      path: path.join(history, `${versionID}.dat`),
      source: { agent: "legacy-agent", messageID: "legacy-message" },
    }
    const raw = JSON.stringify(record, null, 2)
    await fs.mkdir(history, { recursive: true })
    await Promise.all([
      Bun.write(path.join(dir, `${artifactID}.dat`), "legacy version"),
      Bun.write(path.join(history, `${versionID}.dat`), "legacy version"),
      Bun.write(path.join(history, `${versionID}.json`), raw),
    ])

    expect(await RLMArtifacts.readVersion(sessionID, artifactID, versionID)).toMatchObject({
      content: "legacy version",
      info: {
        ...record,
        retention: {
          status: "ephemeral",
          policy: "session_ttl",
          expiresAt: createdAt + 7 * 24 * 60 * 60 * 1000,
        },
        provenance: {
          format: "openscience.provenance.v1",
          kind: "artifact_version",
          outputs: {
            items: [
              {
                artifact_id: { status: "available", value: artifactID },
                version_id: { status: "available", value: versionID },
              },
            ],
          },
        },
      },
    })
    expect(await Bun.file(path.join(history, `${versionID}.json`)).text()).toBe(raw)
  })

  test("traces a real kernel execution to an immutable artifact version", async () => {
    await using tmp = await tmpdir({ git: true })
    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        await trustProject()
        const info = await Session.create({})
        sessions.add(info.id)
        const execution = await KernelRuntime.execute(
          {
            projectID: Instance.project.id,
            sessionID: info.id,
            name: "artifact-producer",
            language: "python",
          },
          "40 + 2",
        )
        const run = await Provenance.get(execution.provenanceID!)
        expect(run?.kind).toBe("run")
        const runID =
          run?.kind === "run" && "tool" in run && run.provenance?.identity.run_id.status === "available"
            ? run.provenance.identity.run_id.value
            : undefined
        const tool = await ArtifactTool.init()
        const registered = await tool.execute(
          {
            action: "register",
            type: "analysis",
            content: "42",
            summary: "Kernel result",
            provenance_id: execution.provenanceID,
          },
          {
            ...context(info.id),
            messageID: "msg_trace",
            callID: "call_trace",
          },
        )
        const artifactID = registered.metadata.id as string
        const versionID = registered.metadata.versionID as string
        const version = (await RLMArtifacts.listVersions(info.id, artifactID))[0]!

        expect(version.source).toEqual({
          projectID: Instance.project.id,
          agent: "research",
          messageID: "msg_trace",
          callID: "call_trace",
          runID,
          provenanceID: execution.provenanceID,
        })
        expect(version.provenance).toMatchObject({
          kind: "artifact_version",
          identity: {
            project_id: { status: "available", value: Instance.project.id },
            session_id: { status: "available", value: info.id },
            run_id: { status: "available", value: runID },
          },
          outputs: {
            items: [
              {
                artifact_id: { status: "available", value: artifactID },
                version_id: { status: "available", value: versionID },
                sha256: version.sha256,
              },
            ],
          },
        })
        expect(await Provenance.get(version.id)).toMatchObject({
          id: version.id,
          kind: "artifact",
          contentHash: version.sha256,
          provenance: version.provenance,
        })
        const trace = await Provenance.query(
          {
            projectID: Instance.project.id,
            directory: Instance.directory,
          },
          version.id,
        )
        expect(
          trace.edges.some(
            (edge) => edge.from === execution.provenanceID && edge.to === version.id && edge.relation === "produced",
          ),
        ).toBe(true)
      },
    })
  })

  test("redacts registered secrets before content and provenance metadata are persisted", async () => {
    const sessionID = session()
    const secret = `artifact-secret-${crypto.randomUUID()}`
    OpenScience.registerSecretValues([secret])
    const ref = await RLMArtifacts.register(sessionID, "analysis", `token=${secret}`, `summary ${secret}`, {
      projectID: "project-redaction",
      agent: `agent-${secret}`,
      messageID: "msg_redaction",
      callID: "call_redaction",
    })
    const version = (await RLMArtifacts.listVersions(sessionID, ref.id))[0]!
    const raw = await Bun.file(version.path.replace(/\.dat$/, ".json")).text()

    expect(await RLMArtifacts.resolve(sessionID, ref.id)).toBe("token=[REDACTED]")
    expect(await RLMArtifacts.readVersion(sessionID, ref.id, version.id)).toMatchObject({
      content: "token=[REDACTED]",
      info: {
        summary: "summary [REDACTED]",
        source: { agent: "agent-[REDACTED]" },
      },
    })
    expect(raw).not.toContain(secret)
    expect(raw).toContain("[REDACTED]")
    expect(await Bun.file(Provenance.path_).text()).not.toContain(secret)
  })

  test("exposes update, version listing, and historical reads through the artifact tool", async () => {
    await using tmp = await tmpdir()
    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const sessionID = session()
        const tool = await ArtifactTool.init()
        const registered = await tool.execute(
          { action: "register", type: "dataframe", content: "a,b\n1,2", summary: "Inputs" },
          context(sessionID),
        )
        const artifactID = registered.metadata.id as string
        const firstVersion = registered.metadata.versionID as string

        const updated = await tool.execute(
          { action: "update", artifact_id: artifactID, content: "a,b\n3,4" },
          context(sessionID),
        )
        const versions = await tool.execute({ action: "list_versions", artifact_id: artifactID }, context(sessionID))
        const historical = await tool.execute(
          { action: "read_version", artifact_id: artifactID, version_id: firstVersion },
          context(sessionID),
        )

        expect(updated.metadata).toMatchObject({ id: artifactID, version: 2, type: "dataframe" })
        expect(versions.metadata).toMatchObject({
          count: 2,
          versions: [updated.metadata.versionID, firstVersion],
          retention: [
            {
              versionID: updated.metadata.versionID,
              status: "ephemeral",
              policy: "session_ttl",
              expiresAt: expect.any(Number),
            },
            {
              versionID: firstVersion,
              status: "ephemeral",
              policy: "session_ttl",
              expiresAt: expect.any(Number),
            },
          ],
        })
        expect(historical.output).toBe("a,b\n1,2")
        expect(historical.metadata).toMatchObject({
          id: artifactID,
          versionID: firstVersion,
          version: 1,
          sha256: expect.stringMatching(/^[a-f0-9]{64}$/),
          retention: {
            status: "ephemeral",
            policy: "session_ttl",
            expiresAt: expect.any(Number),
          },
          provenance: {
            format: "openscience.provenance.v1",
            kind: "artifact_version",
          },
          source: {
            projectID: Instance.project.id,
            agent: "research",
            messageID: "msg_artifact_test",
            callID: "call_artifact_test",
            runID: "call_artifact_test",
          },
        })
      },
    })
  })

  test("cleanup keeps a newly updated version when its parent session directory is old", async () => {
    const sessionID = session()
    const first = await RLMArtifacts.register(sessionID, "analysis", "old result")
    const old = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000)
    const dir = path.join(Global.Path.data, "artifacts", sessionID)
    await fs.utimes(dir, old, old)
    const second = await RLMArtifacts.update(sessionID, first.id, "fresh result")
    await fs.utimes(dir, old, old)

    await RLMArtifacts.cleanup()

    expect(await RLMArtifacts.resolve(sessionID, first.id)).toBe("fresh result")
    expect((await RLMArtifacts.listVersions(sessionID, first.id)).map((version) => version.id)).toEqual([
      second!.versionID!,
      first.versionID!,
    ])
  })

  test("cleanup preserves durable versions regardless of session and content activity", async () => {
    const sessionID = session()
    const ref = await RLMArtifacts.register(sessionID, "analysis", "durable result")
    const version = (await RLMArtifacts.listVersions(sessionID, ref.id))[0]!
    const meta = version.path.replace(/\.dat$/, ".json")
    const record = (await Bun.file(meta).json()) as Record<string, unknown>
    const old = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000)
    const dir = path.join(Global.Path.data, "artifacts", sessionID)
    await Bun.write(meta, JSON.stringify({ ...record, retention: { status: "durable", policy: "durable" } }, null, 2))
    await Promise.all([fs.utimes(dir, old, old), fs.utimes(version.path, old, old), fs.utimes(ref.path, old, old)])

    await RLMArtifacts.cleanup()

    expect(await RLMArtifacts.readVersion(sessionID, ref.id, version.id)).toMatchObject({
      content: "durable result",
      info: {
        id: version.id,
        retention: { status: "durable", policy: "durable" },
      },
    })
    expect(await RLMArtifacts.resolve(sessionID, ref.id)).toBe("durable result")
  })

  test("cleanup removes expired ephemeral versions and restores the head to remaining history", async () => {
    const sessionID = session()
    const first = await RLMArtifacts.register(sessionID, "analysis", "first")
    const second = await RLMArtifacts.update(sessionID, first.id, "second")
    const third = await RLMArtifacts.update(sessionID, first.id, "third")
    const versions = await RLMArtifacts.listVersions(sessionID, first.id)
    const expired = [versions[0]!, versions[2]!]
    const oldAt = Date.now() - 10 * 24 * 60 * 60 * 1000
    const old = new Date(oldAt)

    await Promise.all(
      expired.flatMap(async (version) => {
        const meta = version.path.replace(/\.dat$/, ".json")
        const record = (await Bun.file(meta).json()) as Record<string, unknown>
        await Bun.write(
          meta,
          JSON.stringify(
            {
              ...record,
              createdAt: oldAt,
              retention: {
                status: "ephemeral",
                policy: "session_ttl",
                expiresAt: oldAt + 7 * 24 * 60 * 60 * 1000,
              },
            },
            null,
            2,
          ),
        )
        await fs.utimes(version.path, old, old)
      }),
    )

    await RLMArtifacts.cleanup()

    expect(await RLMArtifacts.resolve(sessionID, first.id)).toBe("second")
    expect((await RLMArtifacts.listVersions(sessionID, first.id)).map((version) => version.id)).toEqual([
      second!.versionID!,
    ])
    expect(await RLMArtifacts.readVersion(sessionID, first.id, first.versionID!)).toBeNull()
    expect(await RLMArtifacts.readVersion(sessionID, first.id, third!.versionID!)).toBeNull()
    expect(await RLMArtifacts.readVersion(sessionID, first.id, second!.versionID!)).toMatchObject({
      content: "second",
      info: { id: second!.versionID },
    })
  })
})

describe("RLMArtifacts durable retention", () => {
  test("register can create a durable version and retain promotes the head", async () => {
    const sessionID = session()

    const saved = await RLMArtifacts.register(sessionID, "report", "final numbers", "Final report", undefined, {
      durable: true,
    })
    const savedVersions = await RLMArtifacts.listVersions(sessionID, saved.id)
    expect(savedVersions[0]?.retention).toEqual({ status: "durable", policy: "durable" })

    const scratch = await RLMArtifacts.register(sessionID, "analysis", "intermediate", "Working table")
    const before = await RLMArtifacts.listVersions(sessionID, scratch.id)
    expect(before[0]?.retention.status).toBe("ephemeral")

    const retained = await RLMArtifacts.retain(sessionID, scratch.id)
    expect(retained?.retention).toEqual({ status: "durable", policy: "durable" })
    const after = await RLMArtifacts.listVersions(sessionID, scratch.id)
    expect(after[0]?.retention).toEqual({ status: "durable", policy: "durable" })

    // Retaining an already durable version is a no-op, unknown targets return null.
    expect((await RLMArtifacts.retain(sessionID, scratch.id))?.id).toBe(retained!.id)
    expect(await RLMArtifacts.retain(sessionID, "art-missing")).toBeNull()
  })

  test("update keeps prior versions ephemeral and only marks the requested one durable", async () => {
    const sessionID = session()
    const first = await RLMArtifacts.register(sessionID, "analysis", "draft")
    const second = await RLMArtifacts.update(sessionID, first.id, "final", { durable: true })

    const versions = await RLMArtifacts.listVersions(sessionID, first.id)
    expect(versions).toHaveLength(2)
    expect(versions.find((v) => v.id === second!.versionID)?.retention.status).toBe("durable")
    expect(versions.find((v) => v.id === first.versionID)?.retention.status).toBe("ephemeral")
  })
})
