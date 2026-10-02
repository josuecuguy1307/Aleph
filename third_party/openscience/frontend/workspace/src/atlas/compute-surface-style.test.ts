import { describe, expect, test } from "bun:test"

const css = await Bun.file(new URL("../styles/atlas.css", import.meta.url)).text()

describe("compute surface styling", () => {
  test("uses a soft, readable segmented control for compute views", () => {
    expect(css).toContain(".compute-surface__tabs")
    expect(css).toContain("border-radius: 16px")
    expect(css).toContain("min-height: 44px")
    expect(css).toContain("font-size: 14px")
    expect(css).toContain('.compute-surface__tab[data-active="true"]')
  })

  test("keeps the selected compute view as the only scrolling content area", () => {
    expect(css).toContain(".compute-surface__panel")
    expect(css).toContain("min-height: 0")
    expect(css).toContain("overflow: hidden")
  })
})
