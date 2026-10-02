import { expect, test } from "bun:test"
import path from "path"
import { SystemPrompt } from "../../src/session/system"
import { Instance } from "../../src/project/instance"
import { ProjectTrust } from "../../src/project/trust"
import { tmpdir } from "../fixture/fixture"

async function trust() {
  const status = await ProjectTrust.status(Instance.project)
  await ProjectTrust.update(Instance.project, {
    trusted: true,
    root: status.root,
  })
}

async function writeSkill(dir: string, name: string, category: string) {
  await Bun.write(
    path.join(dir, ".openscience", "skill", name, "SKILL.md"),
    `---
name: ${name}
description: ${name} test skill.
category: ${category}
---

# ${name}
`,
  )
}

test("availableSkills lists loaded skills instead of static prompt entries", async () => {
  await using tmp = await tmpdir({
    git: true,
    init: async (dir) => {
      await writeSkill(dir, "scanpy", "biology")
    },
  })

  await Instance.provide({
    directory: tmp.path,
    fn: async () => {
      await trust()
      const section = await SystemPrompt.availableSkills([])
      expect(section).toContain("<available-skills>")
      expect(section).toContain("### biology")
      expect(section).toContain("- scanpy")
      expect(section).not.toContain("peft")
    },
  })
})

test("availableSkills excludes permission-denied skills", async () => {
  await using tmp = await tmpdir({
    git: true,
    init: async (dir) => {
      await writeSkill(dir, "scanpy", "biology")
      await writeSkill(dir, "private-analysis", "biology")
    },
  })

  await Instance.provide({
    directory: tmp.path,
    fn: async () => {
      await trust()
      const section = await SystemPrompt.availableSkills([
        {
          permission: "skill",
          pattern: "private-analysis",
          action: "deny",
        },
      ])
      expect(section).toContain("- scanpy")
      expect(section).not.toContain("private-analysis")
    },
  })
})

test("availableSkills blocks skill calls when the registry is empty", async () => {
  await using tmp = await tmpdir({ git: true })

  await Instance.provide({
    directory: tmp.path,
    fn: async () => {
      const section = await SystemPrompt.availableSkills([])
      expect(section).toContain("No skills are currently available")
      expect(section).toContain("Do not call the skill tool")
    },
  })
})
