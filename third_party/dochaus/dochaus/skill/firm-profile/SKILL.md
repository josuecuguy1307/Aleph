---
name: firm-profile
description: Defines the practice profile — a plain-English markdown file at .dochaus/profile.md in the matter directory recording the firm's escalation rules, house style, risk calibration, and jurisdiction defaults — and how to create, load, and apply it. Use when setting up a new firm or matter, onboarding, when asked to "use our house style" or record firm preferences, or before any review, draft, or redline that should follow the firm's standing positions.
---

The practice profile is the firm's standing instructions for a matter, written
in plain English with the supervising lawyer. It lives at one fixed location:
`.dochaus/profile.md` inside the matter directory (the session's working
directory). One file, four fixed sections, nothing else.

<loading>
At the start of any review, draft, or redline, `read` `.dochaus/profile.md`.

- **Present** — apply it throughout. Profile positions override the generic
  balanced defaults in the clause-library and drafting skills; they do not
  override a bound playbook's approved language — a playbook is the firm's
  reviewed position for that document type.
- **Conflict** — when an instruction, playbook position, or document term
  conflicts with the profile, flag the conflict explicitly, quoting the profile
  line it crosses. Never silently follow either side; the lawyer resolves it.
- **Anything matching an Escalation Rule** stops with a clear statement of
  which rule was triggered — do not proceed and escalate in the same breath.
- **Absent** — proceed on balanced market-practice defaults, and when the
  moment is natural (new matter, onboarding, "use our preferences") offer to
  create one via the interview in `references/interview.md`.
</loading>

<sections>
The profile has exactly these four `##` sections, in this order.

- **Escalation Rules** — what always goes to a human before it happens: work
  product that may never leave the firm without named sign-off, exposure or
  deal-value thresholds that loop in a partner, topics never handled without
  escalation (privilege calls, regulator contact, conflicts), and who the
  escalation contact is.
- **House Style** — the drafting voice (plain English or traditional, "shall"
  vs "must/will"), defined-term conventions (where terms are defined, how they
  are marked on first use), numbering and heading conventions, date and number
  formats, and boilerplate the firm always includes or never includes.
- **Risk Calibration** — the negotiation posture per contract type, given the
  side the firm usually sits on: **aggressive** (open firm-favorable, concede
  slowly), **balanced** (market-standard two-sided positions), or
  **conservative** (accept reasonable counterparty terms, redline only material
  risk). Plus non-negotiables and standard concessions.
- **Jurisdiction Defaults** — default governing law and venue for new
  documents, dispute-resolution preference (courts or arbitration, and where),
  the jurisdictions the firm advises in, and what happens when a document falls
  outside them (flag as outside scope, never improvise foreign law).
</sections>

<skeleton>
A new profile starts from this skeleton. Keep entries as short plain-English
lines a non-lawyer could follow; write `Not specified` rather than guessing an
answer the lawyer never gave.

```markdown
# Practice Profile

## Escalation Rules
- Nothing leaves the firm to a counterparty, court, or regulator without
  sign-off from [name/role].
- Loop in [name/role] when exposure or deal value exceeds [amount].
- Always escalate: [topics].

## House Style
- Voice: [plain English / traditional]; obligations use ["must" / "shall"].
- Defined terms: [convention, e.g. bold-quoted on first use, Definitions
  section up front].
- Formats: dates as [format]; numbering [convention].
- Always include: [boilerplate]. Never include: [boilerplate].

## Risk Calibration
- [Contract type] (we are usually the [side]): [aggressive / balanced /
  conservative]. Non-negotiable: [terms]. Standard concessions: [terms].

## Jurisdiction Defaults
- Governing law and venue for new documents: [jurisdiction], unless [exception].
- Disputes: [courts / arbitration under [rules], seated in [place]].
- We advise on [jurisdictions] law only; anything else is flagged as outside
  scope.
```
</skeleton>

<creating>
To create or update a profile, run the interview in `references/interview.md`:
pre-fill every answer you can from the matter's existing documents, ask only
the gaps in small batches, confirm a compact summary, then write the file to
`.dochaus/profile.md` (create the `.dochaus/` directory if needed). If you
cannot write files, output the complete file in one fenced block labeled with
that path for the lawyer to save. Updates edit the existing file section by
section — never drop sections the lawyer did not ask to change.
</creating>
