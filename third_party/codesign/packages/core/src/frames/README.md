# Device Frame Snippets

Device frames are JSX runtime snippets that the desktop host seeds into the
agent virtual filesystem as `frames/<name>.jsx`.

They are different from scaffold presets:

- Frames are read with `view("frames/iphone.jsx")` and adapted into `App.jsx`.
- Scaffolds are copied into the workspace with `scaffold(kind, destPath)`.
- Workspace `DESIGN.md` remains the design-system baton; frames are only visual
  chrome helpers.

## Available Frames

- `iphone.jsx` - iPhone frame.
- `ipad.jsx` - iPad frame.
- `watch.jsx` - watch frame.
- `android.jsx` - Android phone frame.
- `macos-safari.jsx` - macOS Safari window frame.

## How The Agent Uses Them

The host loads files from `<userData>/templates/frames/` and exposes them under
`frames/` in the virtual filesystem. The agent may view a frame when the brief
explicitly benefits from device or browser chrome, then copy the relevant
component structure into `App.jsx`.

Frames should not be final artifacts by themselves. The agent still needs to
adapt the screen content, tokens, interactions, accessibility, and any
`DESIGN.md` baton.

## Adding A New Frame

1. Drop `<name>.jsx` in `apps/desktop/resources/templates/frames/`.
2. Append the filename to `FRAME_FILES` in `packages/core/src/frames/index.ts`.
3. Keep `TWEAK_DEFAULTS` valid JSON when the frame has tweakable values.
4. Add focused tests if the loader contract or virtual path changes.

Conventions:

- JSX source compatible with the preview runtime.
- No external network assets or CDN scripts.
- Stable outer dimensions and clear inner screen/content region.
- Tunable values exposed through `TWEAK_DEFAULTS` only when useful.
