import { describe, expect, test } from "bun:test"

const css = await Bun.file(new URL("./FilePreview.css", import.meta.url)).text()

describe("file preview surface", () => {
  test("uses one compact operational toolbar", () => {
    expect(css).toContain("min-height: 48px")
    expect(css).toContain("font-size: 14px")
    expect(css).toContain("font-size: 11px")
    expect(css).toContain("min-height: 32px")
    expect(css).toContain("border-radius: 9px")
  })

  test("keeps documents readable without presentation-scale spacing", () => {
    expect(css).toContain("width: min(100%, 820px)")
    expect(css).toContain("font-size: 15px")
    expect(css).toContain("font-size: 13px")
    expect(css).toContain("padding: clamp(30px, 5vw, 52px)")
  })
})
