---
schemaVersion: 1
name: responsive-layout
description: >
  Designs layouts that hold across mobile, tablet, desktop, and fixed-format
  preview sizes. Use for landing pages, dashboards, reports, app shells,
  tables, card grids, browser/device mocks, and any artifact that should not
  overlap, clip, or collapse when resized.
aliases: [responsive, layout, breakpoints, mobile-desktop, resize]
dependencies: []
validationHints:
  - layout uses stable constraints instead of viewport-scaled type
  - mobile and desktop arrangements avoid overlap and horizontal clipping
trigger:
  providers: ['*']
  scope: system
disable_model_invocation: false
user_invocable: true
---

## Layout Contract

Start with the artifact's format:

- Fixed slide/report: preserve the intended aspect ratio and scale the whole
  canvas predictably.
- App/tool surface: adapt layout structure across viewport widths.
- Mobile mock: design for the phone viewport without adding fake device chrome
  unless requested.
- Browser/device frame: keep chrome stable and let only the screen content adapt.

## Responsive Rules

- Use `box-sizing: border-box` globally.
- Set stable dimensions with `minmax()`, `clamp()` for container sizes, `aspect-ratio`,
  and `max-width`; do not let hover labels resize grids.
- Do not scale font size directly with viewport width. Use discrete type sizes
  or `clamp()` with conservative bounds for display type only.
- Never use negative letter-spacing on small text. Use `letter-spacing: 0` for
  normal UI text.
- Prefer CSS grid for large layout changes and flex for local alignment.
- Tables on small screens need one of: horizontal scroll with sticky first
  column, card rows, or a reduced-column summary.

## Breakpoints

Use content-driven breakpoints, but these defaults are safe:

- `<= 640px`: single column, compact nav, full-width primary actions.
- `641-1024px`: two-column or split layout when content has enough width.
- `> 1024px`: full shell, sidebar, wider data grids, secondary panels.

## Fixed-Format Artifacts

For slides, decks, and report pages:

- Use one outer canvas with `aspect-ratio`.
- Keep all content inside the canvas; no fixed viewport-positioned elements
  unless they are controls outside the exported artifact.
- Match page counters to actual slide/page count.
- Use responsive scaling on the canvas, not scattered viewport math.

## Anti-Overlap Check

Before preview or `done()`:

- Longest button label fits its container.
- Cards do not change size on hover.
- Fixed headers/footers do not cover content.
- Mobile nav does not overlap safe-area or bottom actions.
- Wide charts, tables, and code blocks have deliberate overflow handling.
