// Run from dochaus/: bun test lib/markdown.test.ts
import { describe, expect, test } from "bun:test"
import { lintTemplateBody } from "./markdown"

const CLEAN = `# MUTUAL NDA

Between [insert first party] and [insert second party].

## 1. Purpose

The Parties wish to explore [insert business opportunity].

## 2. Term

[insert term in years] years.

## 3. Non-Solicitation [optional: non-solicitation]

For [insert non-solicit period in months] months.

## 4. Entire Agreement

Whole deal.`

describe("lintTemplateBody", () => {
  test("clean body passes", () => {
    expect(lintTemplateBody(CLEAN)).toEqual([])
  })

  test("duplicate placeholder flagged", () => {
    const problems = lintTemplateBody(CLEAN.replace("[insert second party]", "[insert first party]"))
    expect(problems.some((p) => p.includes("[insert first party]") && p.includes("more than once"))).toBe(true)
  })

  test("bare blank flagged", () => {
    const problems = lintTemplateBody(CLEAN.replace("[insert term in years]", "[___]"))
    expect(problems.some((p) => p.includes("[___]"))).toBe(true)
  })

  test("heading numbering gap flagged", () => {
    const problems = lintTemplateBody(CLEAN.replace("## 4. Entire Agreement", "## 5. Entire Agreement"))
    expect(problems).toEqual(['heading numbering breaks at "5." — expected 4'])
  })

  test("duplicate optional marker flagged", () => {
    const problems = lintTemplateBody(
      CLEAN.replace("## 4. Entire Agreement", "## 4. No Hire [optional: non-solicitation]"),
    )
    expect(problems.some((p) => p.includes("[optional: non-solicitation]") && p.includes("more than once"))).toBe(true)
  })
})
