import type { Agent } from "@synsci/sdk/v2/client"

const SYSTEM_AGENTS = new Set(["title", "compaction"])

export function isVisibleSpecialist(agent: Pick<Agent, "name" | "hidden">) {
  return !SYSTEM_AGENTS.has(agent.name) && agent.name !== "plan" && !agent.hidden
}
