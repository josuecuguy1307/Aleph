# Cold-start interview

The interview populates a new `.dochaus/profile.md` (or fills the gaps in an
existing one). It is a short guided conversation, not a questionnaire: ask one
section's batch per turn, in the order below, and never re-ask anything already
answered or pre-filled.

<prefill>
Before asking anything, mine what the matter already holds:

1. Read `matter.json` for the matter's jurisdiction packs — these are the
   starting candidates for Jurisdiction Defaults.
2. `search-document` across the uploaded documents for governing-law and venue
   clauses, dispute-resolution clauses, limitation-of-liability figures, and
   signature blocks — these reveal the firm's actual positions and who signs.
3. Skim one or two documents (`read-document`) for style: plain English or
   traditional drafting, "shall" vs "must", how defined terms are introduced,
   date and numbering formats.

Turn every solid finding into a confirmable default rather than an open
question — "Your engagement letter is governed by the law of England and Wales;
use that as the default for new documents?" — and cite where it came from as
`[<Document> § <section>]`. Ask cold only where the documents are silent.
Pre-filled answers are still answers the lawyer must confirm; nothing enters
the profile unconfirmed.
</prefill>

<script>
Ask in these four batches, one batch per turn, leading each with whatever you
pre-filled.

**1. Escalation Rules**
- What must never leave the firm — to a counterparty, court, or regulator —
  without a named person's sign-off, and who is that person?
- Is there a money threshold (exposure, deal value, settlement figure) above
  which a partner is looped in before work continues?
- Which topics are always escalated rather than handled — for example
  privilege or waiver questions, regulator contact, conflicts of interest,
  anything touching litigation strategy?

**2. House Style**
- Drafting voice: plain English or traditional? Obligations as "must"/"will"
  or "shall"?
- Defined terms: defined where (a Definitions section up front, or inline at
  first use), and marked how on first use?
- Date format, numbering and heading conventions, any cross-reference style?
- Boilerplate the firm always includes, and anything it never includes?

**3. Risk Calibration**
- Which contract types does this matter (or the firm) regularly handle, and
  which side of the table is the firm usually on (customer or vendor,
  discloser or recipient, employer or employee)?
- For each type: aggressive, balanced, or conservative posture?
- Any non-negotiables — terms the firm walks away over — and any standard
  concessions it gives without a fight?

**4. Jurisdiction Defaults**
- Default governing law and venue for new documents, and any exceptions (for
  example, by counterparty location)?
- Disputes to courts or arbitration? If arbitration: which rules and seat?
- Which jurisdictions does the firm advise on? Confirm these against the
  matter's jurisdiction packs from `matter.json`, and flag any mismatch. For
  anything outside them, the profile default is to flag the document as
  outside scope.
</script>

<writing>
1. Confirm a compact summary: every section, every answer, in the words that
   will go into the file. An unanswered question is recorded as `Not
   specified`, never guessed.
2. Write the confirmed profile to `.dochaus/profile.md` in the matter
   directory, using the skeleton in SKILL.md, creating `.dochaus/` if needed.
   If you cannot write files, output the complete file in one fenced block
   labeled with that path for the lawyer to save.
3. Report: name the path, list anything left `Not specified`, and remind the
   lawyer the profile is plain markdown they can edit directly at any time.
</writing>
