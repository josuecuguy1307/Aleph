# Local verification

Before pushing to `main` (or opening a PR), run the same gates CI enforces, so a
red build never reaches the default branch.

```bash
bun run typecheck                        # all workspaces (tsgo), matches CI "Typecheck"
bun test --cwd backend/cli               # CLI unit + integration suite, matches CI "Test"
bun run --cwd frontend/workspace build   # workspace build, matches CI "Build (web)"
```

Formatting is a separate required gate:

```bash
bunx prettier --check .                  # CI "Format"
bunx prettier --write .                  # fix in place
```

Notes:

- `.mdx` documentation pages are intentionally excluded from prettier (its MDX
  parser is deprecated and can mangle JSX-in-markdown). Keep them plain-markdown
  and let the docs build validate them.
- The model catalog is fixtured in tests, so the suite is deterministic and runs
  offline; a nightly job checks the live catalog for delistings separately.
- Atlas-dependent code paths degrade gracefully when signed out or offline —
  exercise both states when touching them.
