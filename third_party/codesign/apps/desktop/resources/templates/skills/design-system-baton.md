---
schemaVersion: 1
name: design-system-baton
description: >
  Clarifies when and how to create, repair, or update workspace DESIGN.md.
  Use for multi-screen work, brand adoption, reusable visual systems,
  componentized artifacts, or any task where colors, typography, spacing,
  radius, and component tokens must remain stable across outputs.
aliases: [design-md, design-system, baton, tokens, multi-screen-system]
dependencies: []
validationHints:
  - workspace DESIGN.md contains Google-compatible frontmatter and Overview
  - repeated visual choices are promoted to tokens instead of duplicated prose
trigger:
  providers: ['*']
  scope: system
disable_model_invocation: false
user_invocable: true
---

## Boundary

`DESIGN.md` is the workspace design-system baton. It is not a prompt, not a
scratchpad, not a starter preset, and not a copy of a built-in brand reference.

Use it to store stable design decisions that later artifacts should inherit:
palette, typography, radius, spacing, component tokens, layout principles, tone,
and do/don't rules. Keep transient task notes in chat or source comments, not in
`DESIGN.md`.

## When To Create Or Update

Create or update `DESIGN.md` when any of these are true:

- The user asks for more than one screen, slide, route, or artifact.
- A brand reference or user-provided design system is adopted.
- You introduce reusable components, shared tokens, or a named visual direction.
- Existing source already uses stable tokens that should guide the next pass.
- `done()` requires `DESIGN.md` because multiple design sources exist.

Do not create one for a tiny throwaway single-state mock unless stable tokens
are already clear.

## Minimum Google-Compatible Shape

Start with valid YAML frontmatter:

```md
---
version: alpha
name: Project Design System
description: Short description of the artifact family
colors:
  background: "#F7F3EC"
  surface: "#FFFAF2"
  text: "#10172B"
  muted: "#5D6680"
  accent: "#E0522D"
typography:
  display:
    fontFamily: Georgia
    fontSize: 56px
    fontWeight: 700
    lineHeight: 1.05
rounded:
  sm: 4px
  md: 8px
  lg: 16px
spacing:
  sm: 8px
  md: 16px
  lg: 32px
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#FFFFFF"
    rounded: "{rounded.md}"
    padding: 12px
---
```

Then add known body sections in this order: Overview, Colors, Typography,
Layout, Elevation & Depth, Shapes, Components, Do's and Don'ts.

## Rules

- Store tokens as canonical values, not long narrative.
- Use sRGB hex colors in frontmatter; keep expressive `oklch()` or CSS-only
  variants in source files unless the validator supports them.
- Prefer semantic token names: background, surface, text, muted, border,
  accent, success, warning, danger.
- If a built-in `brand:<slug>` reference is used, translate it into a
  project-specific `DESIGN.md` rather than editing the built-in reference.
- When revising an existing design, read `DESIGN.md` before changing colors,
  type, spacing, radius, or repeated components.
- If `DESIGN.md` is invalid, repair the schema before `done()`.

## Don't

- Do not paste full source files, long meeting notes, or tool logs into
  `DESIGN.md`.
- Do not copy brand hex values from memory.
- Do not invent fields outside the Google-compatible top-level keys.
- Do not overwrite user-authored sections just to reformat them.
