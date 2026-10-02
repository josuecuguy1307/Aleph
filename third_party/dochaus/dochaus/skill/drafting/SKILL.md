---
name: drafting
description: How to draft a new document into the matter — template-first via list-templates/draft-document, from scratch only when no template fits. Use whenever asked to create, draft, or prepare a new document.
---

Drafting creates a NEW .docx in the matter. Changing an existing document is the
redline workflow, not this one.

<workflow>
1. **Gather the terms first.** Parties (full legal names), effective date,
   durations, jurisdiction, and anything else the document type needs. Take them
   from the conversation and the matter's existing documents (`search-document`);
   ask the lawyer only for what is genuinely missing — and rather than blocking
   on minor blanks, draft with placeholders left in and say which ones remain.
2. **Template first.** Call `list-templates`. If a template matches the request,
   run the guided interview (below) to collect every placeholder value and every
   optional-clause decision, then call `draft-document` ONCE with `template` +
   `fills` + `omit`. Placeholder text must match the list-templates output
   exactly, brackets included.
3. **From scratch only when no template fits.** Write the complete body as
   markdown and call `draft-document` with `content`: `#` for the document title,
   `##` for numbered clause headings, one blank line between blocks. Use the
   standard clause structure for the document type and the balanced positions in
   the clause-library skill as the baseline. Mark anything you cannot know with a
   bracketed instruction placeholder — `[insert client name]`, `[insert term in
   years]`. Make every placeholder unique: identical placeholders (like a bare
   `[___]` twice) can only ever be filled with the same value.
4. **Space the document like the finished Word file.** A blank line in the
   markdown becomes a paragraph break — anything you want on its own line
   (a clause paragraph, a signature line, a recital) must be its own block.
   Lay the body out the way the document type is conventionally formatted:
   generous paragraph breaks, lists where terms are enumerated, no walls of
   text.
5. **Report.** Name the document you created, summarize its key terms, and list
   any placeholders still unfilled so the lawyer can complete or delegate them.
</workflow>

<guided-interview>
Template drafting is a short interview, not a form. The template's variables ARE
its placeholders — the wording of each tells you what kind of answer it wants
(`[insert effective date]` is a date, `[insert governing law state]` is a
jurisdiction, `[insert non-solicit period in months]` is a number). The
template's `optionalClauses` are keep-or-omit decisions.

1. **List the variables.** From the list-templates entry: every placeholder plus
   every optional clause.
2. **Prefill before asking.** Take values from the conversation and the matter's
   existing documents (`search-document`). Never ask for something already known.
3. **Ask the rest in small logical batches** — parties first, then
   dates/durations, then amounts, then jurisdiction and the rest. Ask each
   optional clause as keep-or-omit with a one-line plain-English description of
   what it does. Never one long questionnaire and never one question per turn
   when a batch reads naturally.
4. **Confirm a compact term sheet** before drafting: every variable with its
   value, every optional clause marked keep or omit. A variable the lawyer
   leaves open stays a placeholder in the draft — say so rather than blocking.
5. **Draft ONCE.** One `draft-document` call with `template`, all `fills`, and
   the declined clauses in `omit`. Never assemble clause-by-clause.
</guided-interview>

<template-creation>
Creating a reusable template (`create-template`) adds a drafting base to the
firm's global library, shared across every matter — distinct from drafting a
document into one matter.

**When to create one.** The user asks to create or save a template directly, asks
to turn an existing matter document into a template, or you are drafting a
document type that `list-templates` shows no match for and a template would help.

**Body conventions.** Same markdown rules as from-scratch drafting: `#` title,
`##` numbered clause headings, one blank line between blocks, conventional clause
structure for the document type. The one difference is total: a template carries
NO real client data. Every variable term — every party name, individual, date,
duration, monetary amount, address, email/phone, and reference number — is a
UNIQUE descriptive `[insert ...]` placeholder (`[insert disclosing party]`,
`[insert effective date]`), never a bare `[___]` and never the same placeholder
twice (draft-document fills by exact text, so duplicates collapse to one value).

**Optional clauses.** A clause the lawyer may keep or drop appends
`[optional: short-name]` to the END of its `##` heading — e.g.
`## 9. Non-Solicitation [optional: non-solicitation]`. The short-name is unique
per template, lowercase, hyphenated. The clause's extent is the heading plus
everything under it up to the next same-or-higher heading; on a non-heading
paragraph the marker makes just that paragraph optional. At draft time the
clause is kept (marker stripped) unless its name is passed to draft-document's
`omit`.

**Turning an existing document into a template (PII scrub).** Call
`read-document` to load the full text, then rewrite the whole body replacing every
client-specific detail with a placeholder. Before calling `create-template`, scrub
for: party/company names, individual names, dates, money amounts, percentages,
addresses, emails, phone numbers, and any reference/matter/account numbers. None
may survive into the template — only `[insert ...]` placeholders.

**Review before creating.** A template is drafted from many times, so it must be
right before it enters the library. Spawn the legal-reviewer subagent (task
tool) over the proposed body once: structure must match the document type and
title (a mutual NDA defines both parties' obligations, not one side's), the
type's standard clauses must be present, and jurisdiction-specific language must
not be baked in unless the template is for that jurisdiction. Apply Must-fix
findings to the body before calling `create-template`; one round, do not loop.

**Report.** After `create-template`, name the template and list the placeholders
it exposes, so the user knows what every future draft will be asked to fill.
</template-creation>

<rules>
- Pick a descriptive file name: counterparty + document type, e.g.
  "Acme Corp NDA.docx".
- Never overwrite: if the name is taken, pick another (e.g. append "v2").
- After drafting, refinements go through the normal editing tools
  (tracked-changes / redline) on the new document.
</rules>
