# Multi-screen consistency

Use `DESIGN.md` as the multi-screen baton.

- Before a second screen, read it; if absent, create one from resolved tokens.
- Treat workspace `DESIGN.md` as project authority, not as a starter preset or scratchpad.
- Update stable colors, type, radius, spacing, components, and TWEAK_DEFAULTS values; reuse names unless asked for a variant.
- If a built-in brand ref is used, translate the adopted project-specific choices into workspace `DESIGN.md` rather than editing or copying the reference wholesale.
- New `DESIGN.md` starts with Google-compatible frontmatter: `---\nversion: alpha\nname: Project Design System\n---`; add `## Overview`. Keys: `version`, `name`, `colors`, `typography`, `rounded`, `spacing`, `components`.
