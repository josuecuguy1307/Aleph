# doc.haus — Future Seams (DEPRECATED)

> **Deprecated 2026-06-07.** The seams once tracked here now live as GitHub
> issues in [`sure-scale/doc-haus`](https://github.com/sure-scale/doc-haus/issues).
> Track and discuss the work there; this file is kept only as a redirect.
> The MVP rule still holds: build additively, keep upstream packages untouched.

The DOCX redline track (word-integration / tracked-changes / redline / viewer)
standardizes on **[Docxodus](https://github.com/JSv4/Docxodus)** (MIT;
TypeScript/WASM; edits addressable by char offset *and* anchor ID, which lines up
with our citation `doc_path` + `char_start`/`char_end`). Validate it under Bun and
confirm offset alignment first — see the spike issue.

## Seam → issue

| Former section | Issue |
|---|---|
| Docxodus validation (new gate) | [#1 spike: validate Docxodus under Bun + align offsets](https://github.com/sure-scale/doc-haus/issues/1) |
| Custom tools / word-integration | [#2 word-integration tool](https://github.com/sure-scale/doc-haus/issues/2) |
| Custom tools / tracked-changes | [#3 tracked-changes tool](https://github.com/sure-scale/doc-haus/issues/3) |
| Custom tools / redline | [#4 redline tool](https://github.com/sure-scale/doc-haus/issues/4) |
| Redline review surface (new) | [#5 web DOCX redline viewer](https://github.com/sure-scale/doc-haus/issues/5) |
| Plugin hooks / tool.execute.after | [#6 citation-verification hook](https://github.com/sure-scale/doc-haus/issues/6) |
| Plugin hooks / permission.ask | [#7 edit gating](https://github.com/sure-scale/doc-haus/issues/7) |
| Skills / privilege-review | [#8 privilege-review skill](https://github.com/sure-scale/doc-haus/issues/8) |
| Skills / precedent-search | [#9 precedent-search skill](https://github.com/sure-scale/doc-haus/issues/9) |
| Retrieval at scale | [#10 sqlite-vec/ANN behind search-document](https://github.com/sure-scale/doc-haus/issues/10) |
| Confidentiality / data residency | [#11 on-prem inference swap](https://github.com/sure-scale/doc-haus/issues/11) |
| Single-user → multi-tenant | [#12 multi-tenant](https://github.com/sure-scale/doc-haus/issues/12) |

## Mergeability (unchanged, not an issue)

The fork touches exactly one upstream-tracked file (`AGENTS.md`, a prepended
section). All legal functionality lives in new paths upstream does not have
(`dochaus/`, `services/`, `apps/`), so `git merge upstream/dev` cannot conflict
outside `AGENTS.md`. Keep it that way: default to building in those paths, and
isolate any unavoidable core edit in one clearly-marked commit.
