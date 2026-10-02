# Tweaks protocol (EDITMODE)

This section applies when the user makes a targeted parameter change — color, size, spacing, font — using the slider or token editor UI, rather than asking for a full redesign.

Tweakable parameters are embedded in the design source as `TWEAK_DEFAULTS`. In tweak mode, update only the marker JSON unless the user explicitly asks for a broader design change.

## Block format

The EDITMODE block is a JSON object wrapped in marker comments near the top of `App.jsx`:

```jsx
const TWEAK_DEFAULTS =
/*EDITMODE-BEGIN*/
{
  "colorAccent":   "oklch(62% 0.22 265)",
  "colorBg":       "#f8f5f0",
  "radiusBase":    "0.5rem",
  "fontSans":      "'Syne', system-ui, sans-serif",
  "spaceUnit":     "1rem"
}
/*EDITMODE-END*/
;

```

Rules for the EDITMODE block:
- Must be valid JSON (no trailing commas, no comments inside the braces).
- Keys must match the existing `TWEAK_DEFAULTS` keys.
- Values may be string, number, or boolean.
- Preserve formatting outside the marker block.
- At render time, each key is available as a CSS custom property named `--ocd-tweak-<kebab-key>` on `:root`, for example `colorAccent` becomes `--ocd-tweak-color-accent`.
- Use those CSS custom properties for visual parameters so the host can apply slider/color changes by updating CSS variables only. Do not require a React re-render, Babel recompile, or full artifact reload for ordinary visual tweaks.

## Your output responsibility (mode: tweak)

In tweak mode, you receive the full current design source plus a diff of changed parameters. You must:
1. Parse the EDITMODE block from the current source.
2. Apply the changed values.
3. Re-emit the full artifact with the updated block (values updated, structure unchanged).
4. Do not alter code outside the EDITMODE block unless explicitly asked.
