# EDITMODE protocol

When useful, declare user-tweakable visual parameters near the top of the design source:

```js
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accentColor": "oklch(0.78 0.16 200)",
  "density": 1,
  "darkMode": false
}/*EDITMODE-END*/;
```

Rules:

- The marker content must be valid JSON: no comments, JS expressions, trailing commas, arrays, or nested objects.
- Values may be string, number, or boolean.
- Use camelCase keys and reference them from source through `TWEAK_DEFAULTS`.
- The preview runtime exposes each key as `--ocd-tweak-<kebab-key>` on `:root` before the design renders, for example `accentColor` becomes `--ocd-tweak-accent-color`.
- Consume tweakable visual values through those CSS custom properties in styles, such as `background: "var(--ocd-tweak-accent-color)"` or `padding: "calc(var(--ocd-tweak-density) * 1rem)"`, so the tweak panel can update the rendered design instantly without re-running React or Babel.
- Do not wire tweakable colors, spacing, radius, opacity, or typography directly from `TWEAK_DEFAULTS` into one-time rendered inline values when a CSS custom property can represent the same value.
- Pick 2-5 values that materially change the design.
- Do not invent controls just to fill the panel. Empty `{}` is valid when no useful controls exist yet or when the user did not want tweak controls for this turn.
- In revise mode, preserve an existing EDITMODE block unless the user explicitly asks to change it.
