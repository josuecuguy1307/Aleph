import { expect, test } from "bun:test"
import { SystemPrompt } from "../../src/session/system"
import { MAX_CHILD_AGENTS } from "../../src/tool/task"

const root = new URL("../../src/", import.meta.url)
const read = (path: string) => Bun.file(new URL(path, root)).text()

test("every provider receives one compact product operating contract", () => {
  const instructions = SystemPrompt.instructions()
  expect(SystemPrompt.provider(undefined as never)[0]?.trim()).toBe(instructions)
  expect(instructions.length).toBeLessThan(4_000)
  expect(instructions).toContain("Keep a simple question simple")
  expect(instructions).toContain("Atlas is optional")
  expect(instructions).toContain("Default to zero child agents")
  expect(instructions).not.toContain("shared keys")
  expect(instructions).not.toContain("project init")
})

test("the primary and domain prompts stay adaptive instead of procedural", async () => {
  const [research, ml, biology, physics] = await Promise.all([
    read("agent/prompt/research.txt"),
    read("agent/prompt/ml.txt"),
    read("agent/prompt/biology.txt"),
    read("agent/prompt/physics.txt"),
  ])
  for (const prompt of [research, ml, biology, physics]) {
    expect(prompt.length).toBeLessThan(4_000)
    expect(prompt).not.toContain("literature-review.md")
    expect(prompt).not.toContain("reasoning.md")
    expect(prompt).not.toContain("methodology.md")
    expect(prompt).not.toContain("Create/link the graph")
  }
  expect(research).toContain("A direct question should receive a direct answer")
  expect(research).toContain("Default to no child agents")
  expect(research).toContain("Atlas is optional")
  expect(ml).toContain("simplest method")
  expect(biology).toContain("multiple testing")
  expect(physics).toContain("dimensional consistency")
})

test("delegation is rare, bounded, and observable", async () => {
  const [prompt, source] = await Promise.all([read("tool/task.txt"), read("tool/task.ts")])
  expect(MAX_CHILD_AGENTS).toBe(2)
  expect(prompt).toContain("Default to zero child agents")
  expect(prompt).toContain("At most two child agents")
  expect(prompt).toContain("failed child must not block")
  expect(prompt).not.toContain("trusted")
  expect(source).toContain("durationMs")
  expect(source).toContain("failedToolCalls")
  expect(source).toContain("usage")
})

test("Plan and Review use the observable record without mandatory delegation", async () => {
  const [plan, reviewer] = await Promise.all([read("session/prompt/plan.txt"), read("agent/prompt/reviewer.txt")])
  expect(plan).toContain("Default to no child")
  expect(plan).not.toContain("Launch up to 3")
  expect(plan).not.toContain("mandatory")
  expect(reviewer).toContain("INCOMPLETE RECORD")
  expect(reviewer).toContain("METHOD/CONCLUSION MISMATCH")
  expect(reviewer).toContain("Environment or dependency gaps")
})
