import { existsSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { DOCHAUS_DIR } from "./workflow"

// Enable/disable state for skills and agents lives in dochaus/opencode.json —
// the only place the engine honors it without core edits: `agent.<name>.disable`
// removes an agent from the runtime map, and a permission rule
// `skill: { "<name>": "deny" }` hides a skill from every agent (Skill.available
// filters on the merged permission ruleset) and blocks loading it. Ingest is the
// single writer, same as for agents.json and dochaus/agent/*.md. Running engine
// instances cache config per directory, so a toggle applies to new sessions.
const CONFIG_FILE = () => path.join(DOCHAUS_DIR(), "opencode.json")

type EngineConfig = {
  permission?: Record<string, unknown>
  agent?: Record<string, Record<string, unknown> | undefined>
  [key: string]: unknown
}

function readConfig(): EngineConfig {
  if (!existsSync(CONFIG_FILE())) return {}
  return JSON.parse(readFileSync(CONFIG_FILE(), "utf8")) as EngineConfig
}

function writeConfig(config: EngineConfig) {
  writeFileSync(CONFIG_FILE(), JSON.stringify(config, null, 2) + "\n")
}

// The engine accepts `skill` as a bare action or a pattern→action object; a bare
// action means `{ "*": action }`. Rules are evaluated last-match-wins, so the
// "*" entry stays first and per-name denies appended after it always win.
function skillRules(config: EngineConfig): Record<string, unknown> {
  const existing = (config.permission ??= {})["skill"]
  if (typeof existing === "object" && existing !== null) return existing as Record<string, unknown>
  return { "*": typeof existing === "string" ? existing : "allow" }
}

export function disabledSkills(): Set<string> {
  return new Set(
    Object.entries(skillRules(readConfig()))
      .filter(([name, action]) => name !== "*" && action === "deny")
      .map(([name]) => name),
  )
}

export function setSkillDisabled(name: string, disabled: boolean) {
  const config = readConfig()
  const rules = skillRules(config)
  if (disabled) rules[name] = "deny"
  if (!disabled) delete rules[name]
  config.permission!["skill"] = rules
  writeConfig(config)
}

export function disabledAgents(): Set<string> {
  const agent = readConfig().agent ?? {}
  return new Set(Object.keys(agent).filter((name) => agent[name]?.["disable"] === true))
}

export function setAgentDisabled(name: string, disabled: boolean) {
  const config = readConfig()
  const agent = (config.agent ??= {})
  if (disabled) agent[name] = { ...agent[name], disable: true }
  if (!disabled) {
    const entry = agent[name]
    if (entry) {
      delete entry["disable"]
      if (Object.keys(entry).length === 0) delete agent[name]
    }
  }
  writeConfig(config)
}
