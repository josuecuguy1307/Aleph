import { Plugin } from "../plugin"
import { Format } from "../format"
import { LSP } from "../lsp"
import { FileWatcher } from "../file/watcher"
import { File } from "../file"
import { Skill } from "../skill/skill"
import { Project } from "./project"
import { Bus } from "../bus"
import { Command } from "../command"
import { Instance } from "./instance"
import { Vcs } from "./vcs"
import { Log } from "@/util/log"
import { Snapshot } from "../snapshot"
import { Truncate } from "../tool/truncation"
import { RSILifecycle } from "../session/rsi/lifecycle"
import { RLMArtifacts } from "../session/rlm/artifacts"
import { Session } from "../session"
import { SessionCompaction } from "../session/compaction"
import { SessionFilesystem } from "../session/filesystem"
import { ProjectTrust } from "./trust"
import { Pty } from "../pty"
import { KernelRuntime } from "@/science/kernel/registry"
import { GlobalBus } from "@/bus/global"

async function stopSessions(sessionIDs: string[]) {
  const sessions = [...new Set(sessionIDs)]
  const jobs = import("../compute/jobs").then((module) =>
    Promise.all(sessions.map((sessionID) => module.ComputeJobs.cancelSession(sessionID))),
  )
  await Promise.all([
    ...sessions.map((sessionID) => Pty.releaseSession(sessionID)),
    ...sessions.map((sessionID) => KernelRuntime.releaseSession(sessionID)),
    jobs,
  ])
}

async function affected(sessionID: string, scope: SessionFilesystem.Scope) {
  if (scope === "once" || scope === "session") return [sessionID]
  const sessions = []
  for await (const session of Session.list()) sessions.push(session.id)
  return sessions
}

const filesystemSync = Instance.state(
  () => {
    const directory = Instance.directory
    const projectID = Instance.project.id
    const handler = (event: { directory?: string; payload: unknown }) => {
      const raw = typeof event.payload === "object" && event.payload ? event.payload : {}
      if (!("type" in raw) || raw.type !== SessionFilesystem.Event.Changed.type) return
      const payload = SessionFilesystem.Event.Changed.properties.safeParse(
        "properties" in raw ? raw.properties : undefined,
      )
      if (!payload.success || event.directory === directory) return
      if (payload.data.grant.scope !== "installation" && payload.data.projectID !== projectID) return
      Instance.provide({
        directory,
        fn: async () => stopSessions(await affected(payload.data.sessionID, payload.data.grant.scope)),
      }).catch((error) => Log.Default.error("failed to apply filesystem authority change", { error, directory }))
    }
    GlobalBus.on("event", handler)
    return handler
  },
  async (handler) => {
    GlobalBus.off("event", handler)
  },
)

export async function InstanceBootstrap() {
  Log.Default.info("bootstrapping", { directory: Instance.directory })
  await Plugin.init()
  Format.init()
  await LSP.init()
  FileWatcher.init()
  File.init()
  Vcs.init()
  Snapshot.init()
  Truncate.init()
  filesystemSync()

  // RSI lifecycle: archive unused learned skills, log high performers
  RSILifecycle.startupCheck().catch(() => {})
  // RLM artifacts: remove 7-day old artifacts
  RLMArtifacts.cleanup().catch(() => {})
  // Scratch workspaces: remove orphans whose session record is gone
  SessionFilesystem.sweep().catch(() => {})

  Bus.subscribe(Command.Event.Executed, async (payload) => {
    if (payload.properties.name === Command.Default.INIT) {
      await Project.setInitialized(Instance.project.id)
    }
  })

  // Hot-reload the skill registry when a SKILL.md changes on disk (external
  // edits surface via the watcher when OPENSCIENCE_EXPERIMENTAL_FILEWATCHER=1;
  // in-app authoring self-invalidates through Skill.writeUser).
  Bus.subscribe(FileWatcher.Event.Updated, async (payload) => {
    if (payload.properties.file.endsWith("SKILL.md")) {
      await Skill.invalidate().catch(() => {})
    }
  })

  // Free the per-session compaction circuit-breaker entry when a session is deleted, so a
  // long-running instance handling many sessions doesn't accumulate stale breaker state.
  Bus.subscribe(Session.Event.Deleted, async (payload) => {
    SessionCompaction.resetBreaker(payload.properties.info.id)
    const jobs = import("../compute/jobs").then((module) =>
      module.ComputeJobs.cancelSession(payload.properties.info.id),
    )
    await Promise.all([
      Pty.releaseSession(payload.properties.info.id),
      KernelRuntime.removeSession(Instance.project.id, payload.properties.info.id),
      jobs,
    ])
  })

  // Process authority is revision-bound. Trust revocation stops every live
  // project process. Filesystem changes stop every process covered by their
  // session, project, or installation scope, including other live instances.
  Bus.subscribe(ProjectTrust.Event.Changed, async (payload) => {
    if (payload.properties.status.canExecuteProjectCode) return
    const jobs = import("../compute/jobs").then((module) => module.ComputeJobs.cancelProject(Instance.project.id))
    await Promise.all([Pty.releaseAll(), ...KernelRuntime.list().map((kernel) => KernelRuntime.release(kernel)), jobs])
  })

  Bus.subscribe(SessionFilesystem.Event.Changed, async (payload) => {
    await stopSessions(await affected(payload.properties.sessionID, payload.properties.grant.scope))
  })
}
