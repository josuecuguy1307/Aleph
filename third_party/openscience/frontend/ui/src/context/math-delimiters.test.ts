import { describe, expect, test } from "bun:test"
import { normalizeMathDelimiters } from "./math-delimiters"

describe("model math delimiters", () => {
  test("preserves display and inline formulas before Markdown unescapes them", () => {
    expect(normalizeMathDelimiters(String.raw`Media: \[\bar{x}=\frac{1}{36}\sum x_i\] y \(n=36\).`))
      .toBe("Media: \n\n$$\n\\bar{x}=\\frac{1}{36}\\sum x_i\n$$\n\n y $n=36$.")
  })
  test("preserves code examples, unfinished streaming fences and existing dollar math", () => {
    const markdown = 'Texto $x$ y $$y$$. `\\(literal\\)`\n```python\nvalue = "\\[literal\\]"\n```\n~~~\n\\(sin cerrar\\)'
    expect(normalizeMathDelimiters(markdown)).toBe(markdown)
  })
})
