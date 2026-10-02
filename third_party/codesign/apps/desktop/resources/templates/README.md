# Open CoDesign Built-In Resources

This directory is copied into the user's app data as an editable templates tree.
Treat every file here as shippable product surface.

## Resource Types

- `skills/*.md` are markdown method skills loaded with `skill(name)`. They
  describe how to work: layout, accessibility, charts, forms, responsive
  behavior, craft checks, and `DESIGN.md` baton rules.
- `brand-refs/*/DESIGN.md` are reference-only brand design systems loaded with
  `skill("brand:<slug>")`. They are not project files. When a brand is adopted,
  translate the relevant choices into the workspace `DESIGN.md`.
- `scaffolds/**` are concrete starter/source assets copied with
  `scaffold(kind, destPath)`. They may be `.jsx`, `.html`, `.css`, `.md`, or
  another text format, but the extension must match the content.
- `design-skills/*.jsx` are copyable JSX component snippets. The host exposes
  them in the agent virtual filesystem as `skills/<file>.jsx`; despite that
  virtual path, they are source snippets, not markdown method skills.
- `frames/*.jsx` are copyable device/browser frame snippets exposed as
  `frames/<file>.jsx` in the virtual filesystem.

## Workspace DESIGN.md

Workspace `DESIGN.md` is the project-specific design-system baton. It is not a
built-in preset once copied or authored in a workspace. Generated multi-screen,
brand-driven, or reusable work should preserve, repair, and update it as the
source of visual truth.

## Maintenance Checklist

- Keep manifest metadata truthful: category, path, source, license, aliases.
- Keep source format and extension aligned.
- Avoid CDN scripts, external hotlinked assets, and non-MIT-compatible bundled
  code or assets.
- Avoid weak placeholder copy such as "Replace this", "Page content", or
  "Point one".
- Add focused tests when a resource affects loader behavior, manifest output,
  preview classification, or `DESIGN.md` validation.
