---
schemaVersion: 1
name: accessibility-states
description: >
  Adds semantic HTML, keyboard access, focus visibility, contrast discipline,
  reduced-motion handling, and real empty/loading/error/disabled states. Use
  before finalizing app surfaces, forms, tables, navigation, drawers, dialogs,
  command palettes, or any interactive prototype.
aliases: [a11y, accessibility, states, keyboard, focus, wcag]
dependencies: [craft-polish]
validationHints:
  - interactive controls have visible focus and keyboard paths
  - final artifact includes appropriate empty loading error or disabled states
trigger:
  providers: ['*']
  scope: system
disable_model_invocation: false
user_invocable: true
---

## Interaction Contract

Every visible control must be either a real button/input/select/link or a
clearly inert visual element. If it looks clickable, it needs behavior or a
truthful destination.

Use semantic elements first:

- Navigation: `<nav>` with button or anchor children.
- Primary content: `<main>`, `<section>`, `<article>`, `<aside>`.
- Forms: `<form>`, `<fieldset>`, `<legend>`, `<label>`, real inputs.
- Dialog-like surfaces: a labelled container, clear close action, and scrim.
- Tables: real `<table>` when comparing rows and columns.

## Keyboard And Focus

- All controls must be reachable by keyboard in source order.
- Use visible focus rings with at least two cues: outline plus color, shadow,
  or background change.
- Do not remove outlines unless replacing them with an equally visible focus
  style.
- For tabs, segmented controls, drawers, and accordions, show selected/open
  state using shape or weight, not color alone.
- Do not rely on hover for core information.

## States

Operational surfaces need non-happy paths:

- Empty: what is missing, why it matters, one next action.
- Loading: geometry-matched skeleton or inline spinner with label.
- Error: plain-language cause plus retry/recovery action.
- Disabled: explain the requirement or next step.
- Success: visible confirmation that does not block continued work.

## Visual Access

- Keep body text at 16px or larger unless the artifact is a fixed-format slide.
- Pair small labels with strong contrast and enough line height.
- Never use color as the only indicator for status, selection, or trend.
- Respect `prefers-reduced-motion` for looping, parallax, large movement, or
  repeated entrance animations.
- Keep click/tap targets at least 44px for touch-oriented surfaces.

## Final Check

Before `done()`, scan the source for:

- `href="#"` links with no real destination.
- Click handlers on non-interactive `<div>` or `<span>` elements.
- Inputs without visible labels.
- Icon-only buttons without accessible text or `aria-label`.
- Gray-on-gray labels, tiny captions, and invisible focus states.
