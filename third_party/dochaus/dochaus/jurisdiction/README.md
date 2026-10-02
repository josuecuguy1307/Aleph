# Jurisdiction packs

Each matter carries a **jurisdiction** that steers how the agents reason and
cite. A jurisdiction is a config-only **pack** in this directory — no code change
and no fork is needed to add one (issue #18).

## Layout

```
dochaus/jurisdiction/<CODE>/
  profile.json   # machine fields, read by the ingest service + engine
  prompt.md      # system-prompt fragment injected for matters in this jurisdiction
```

`<CODE>` is the pack code stored on a matter (e.g. `EW`). Keep it to
`[A-Za-z0-9_-]` — it becomes a directory name and is matched against
`matter.json`'s `jurisdiction` field.

### `profile.json`

```json
{
  "code": "EW",
  "name": "England & Wales",
  "citationStyle": "OSCOLA",
  "preferredModel": null
}
```

- `code` — must equal the directory name.
- `name` — shown in the matter-creation dropdown.
- `citationStyle` — surfaced to the model in the injected `<jurisdiction>` tag.
- `preferredModel` — the model a matter in this jurisdiction should run on once
  sovereign routing (issues #11/#15) lands. Declarative today: recorded, not yet
  enforced. Leave `null` until then.

### `prompt.md`

Plain markdown appended to the system prompt for every turn on a matter in this
jurisdiction. State the governing law, the authority hierarchy (what is binding
versus persuasive), the citation convention, and any house style. See `EW/` for
a worked example. Keep it tight — it rides on every request.

## How it is wired

- The ingest service lists packs (`GET /jurisdictions`) so the web app can offer
  them; it stores the chosen `code` in the matter's `matter.json`.
- The engine's legal plugin (`dochaus/plugin/legal.ts`) reads that code per turn
  and appends the pack's `prompt.md` as a `<jurisdiction>` system block, so the
  matter reasons under its jurisdiction with no per-jurisdiction agent.
