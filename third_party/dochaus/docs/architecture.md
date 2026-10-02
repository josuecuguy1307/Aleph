# Architecture

Everything legal is **additive** — it lives outside upstream packages so merges stay
clean. Three processes at runtime:

1. **`opencode serve`** — the unmodified OpenCode engine. Scopes every session and tool
   to a matter via the `x-opencode-directory` header.
2. **`services/ingest/`** — standalone Bun + Hono service. Creates matters and turns
   uploaded documents into embeddings: extract → sectionize → local MiniLM
   (`@xenova/transformers`, all-MiniLM-L6-v2, 384-dim) → per-matter
   `<matter>/.dochaus/legal.db` (`bun:sqlite`). DOCX extracts via `mammoth`; PDF via
   [markitdown](https://github.com/microsoft/markitdown) (a PATH install or `uvx`,
   whichever the host has) with `unpdf` as the no-Python floor; flat/scanned PDFs
   with no text layer fall through to OCR (`pdftoppm` + `tesseract`, when on PATH).
   Exists because OpenCode has no upload endpoint and plugins cannot add HTTP routes.
3. **`apps/web/`** — React + Vite frontend on the OpenCode SDK + the ingest API.

The legal config layer lives in **`dochaus/`** and is loaded by pointing the server at
it with `OPENCODE_CONFIG_DIR=<repo>/dochaus`, so the upstream `.opencode/` dev config is
never touched. It contains:

- **`opencode.json`** — provider, models, and legal-safe permissions.
- **`agent/`** — the legal agents: `qa` (cited Q&A), `research` (cited Q&A plus U.S.
  case law), `legal-review` (orchestrator) with its subagents `legal-reviewer`,
  `assumption-challenger`, `summarizer`, plus `extract` (tabular review) and `redliner`
  (tracked-change edits). The review pipeline is agent-driven via the built-in Task tool
  — reviewer → challenger → summarizer — not hardcoded in app logic.
- **`tool/`** — the legal tools, all read-only except the redline tools, which propose
  changes for human review:
  - `search-document` — retrieval + citations. Reads the matter's `legal.db`, embeds the
    query locally, cosine-ranks chunks, returns `{ documentName, section, excerpt, score }[]`.
  - `case-law` — searches U.S. case law via [CourtListener](https://www.courtlistener.com)
    and returns real, citable opinions. The one tool that reaches outside the matter;
    public record only, never the matter's documents.
  - `redline`, `tracked-changes`, `word-integration` — propose and bake tracked changes
    into the `.docx` itself via the OOXML engine.
- **`skill/`** — `contract-risk-checklist`, `clause-library`.
- **`command/review.md`** — runs the `legal-review` orchestrator.

**Tabular review.** Beyond chat, the web app has a review grid (`apps/web`'s
`ReviewGrid` over the ingest service's `grid`): define question-columns once and the
`extract` agent answers them for every document in the matter, so you can bulk-review a
set of contracts side by side instead of one conversation at a time.

## Models and providers

doc.haus is **provider-agnostic** — it inherits OpenCode's model abstraction, so any of
the 75+ providers OpenCode supports (Anthropic, OpenAI, Google, OpenRouter, local
models, …) works. Model choice is a config + UI concern, not code — users connect a
provider and choose their model in the UI (Settings) on first launch, then switch per
session or agent via OpenCode's inherited multi-model selector. Nothing is pinned in
code — `opencode.json` ships no default model and the agents inherit whatever you pick.

Pick the provider that matches your priorities:

- **Privacy / security** — run an **open-source / self-hosted model** (e.g. via Ollama
  or vLLM) so document content never leaves your infrastructure. Legal work is
  sensitive; this keeps inference local.
- **Accuracy / intelligence** — use **OpenAI** or **Anthropic** frontier models for the
  strongest reasoning on complex contracts.
- **Affordable / fast** — **Google Vertex (Gemini)**, bundled ready-to-use if the host
  has gcloud ADC.

The bundled Vertex config reads project and location from env, so nothing is hardcoded:

```jsonc
// dochaus/opencode.json (excerpt)
"google-vertex": {
  "options": {
    "project": "{env:GOOGLE_VERTEX_PROJECT}",
    "location": "{env:GOOGLE_VERTEX_LOCATION}"
  }
}
```

To use the bundled Vertex provider, sign in with ADC before launching:

```bash
gcloud auth application-default login
export GOOGLE_VERTEX_PROJECT=<your-project>   # only for the Vertex provider
export GOOGLE_VERTEX_LOCATION=global          # Gemini 3.x models are global-only
```

See [providers.md](providers.md) for copy-pasteable config for a BYO cloud key
(Anthropic, OpenAI) and for a fully local / on-prem endpoint (Ollama, LM Studio, vLLM),
plus a note on what leaves your machine — or the upstream
[OpenCode provider docs](https://opencode.ai/docs/providers) for the full catalog.

## Running the pieces by hand

`./start.sh` launches the engine (pointed at `dochaus/`), the ingest service, and the
web app together, and tears them all down if any one exits. To run them by hand instead
— in three terminals:

```bash
OPENCODE_CONFIG_DIR=$PWD/dochaus bun run packages/opencode/src/index.ts serve
cd services/ingest && bun run dev
cd apps/web && bun run dev
```

Matters live under `WORKSPACE_ROOT`, which defaults to `./workspace` at the repo root
(gitignored) — set it to an absolute path to keep matters outside the repo.

## Tests

The ingest service is tested with `bun test`:

```bash
cd services/ingest && bun test
```

## Mergeability

The fork touches a minimal set of upstream-tracked files, and only documentation and
repo metadata: `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`,
the `.github/` ownership and issue-template files, and `STATS.md` (upstream's download
stats, deleted here). The doc-files keep doc.haus content in a prepended section above
the original OpenCode body, so a merge conflict can only land inside that top section,
never in the upstream text below. All
legal *functionality* lives in new paths upstream does not have (`dochaus/`, `services/`,
`apps/`, `demo/`), so `git merge upstream/dev` cannot conflict there at all. See
`FUTURE.md` for the extension seams (custom tools, plugin hooks, vector scale) the MVP
deliberately leaves open.
