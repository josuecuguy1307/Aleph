---
name: cite-check
description: A procedure for auditing every legal citation in a brief, memo, motion, or opinion letter against the CourtListener database — hallucination detection for legal writing. Use when asked to cite-check, verify citations, validate authorities, confirm cases are real, or review a draft before filing or sending.
---

Fabricated and mischaracterized citations are the signature failure of
AI-assisted legal writing, and courts sanction filers for them. Treat every
citation in the document as unverified until a database lookup confirms it.
Never mark a citation verified from memory — verification means a live lookup
returned the case.

<procedure>
1. **Extract every citation.** Read the full document and list each legal
   authority it cites: case citations (full and short-form, including *id.*
   and *supra* references resolved back to their antecedent), statutes,
   regulations, and rules. For each, record the exact anchor where it appears
   as `[<Document> § <section>]` and the proposition the document uses it for
   (quote the sentence it supports).
2. **Verify each case against CourtListener.** Use the CourtListener MCP
   server when available; otherwise use the `case-law` tool. Search by case
   name and by reporter citation. Both sources cover U.S. opinions only — for
   non-U.S. authorities, and for statutes and regulations, do not guess:
   classify them as unverifiable here and list them for manual confirmation.
3. **Compare the holding.** For each case found, read the returned snippet and
   metadata. Confirm the case stands for the proposition the document cites it
   for — a real case cited for something it does not say is as dangerous as a
   fake one. Check the cited court and year against the database record.
4. **Classify each citation** into exactly one status:
   - **verified** — the case exists, the reporter citation, court, and year
     match, and the retrieved content is consistent with the cited proposition.
   - **not found** — no matching case by name or citation; presumptively
     fabricated until the author produces the source.
   - **ambiguous** — a case by that name exists but the citation, court, year,
     or party names do not match, or multiple candidates exist, or the source
     could not verify it (non-U.S. authority, statute, regulation).
   - **supports-different-proposition** — the case is real but the retrieved
     content does not support, or contradicts, the proposition cited.
5. **Output a findings table** with one row per citation:
   | Anchor | Citation as written | Proposition cited for | Status | Evidence |
   The Evidence column carries the CourtListener URL and matched citation for
   verified entries, and the specific mismatch for everything else.
</procedure>

Close with a summary count by status and a clear verdict: a document is safe
to file or send only when every citation is **verified** or independently
confirmed by the supervising attorney. Never soften a **not found** into
"likely correct" — report it as unverified and stop there. Do not invent a
replacement citation for a bad one; flag it and let counsel decide.
