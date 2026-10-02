# Changelog

All notable changes to OpenScience are recorded here. The project follows
[semantic versioning](https://semver.org). Releases are cut from `main` via the
`publish` workflow and published to npm as
[`@synsci/openscience`](https://www.npmjs.com/package/@synsci/openscience); each
tagged release also ships native binaries for Linux, macOS, and Windows.

## v1.2.8 — 2026-07-06

### Fixed

- Managed models (e.g. GPT-5.5, Gemini) failed with "isn't connected to your
  Atlas wallet" or a proxy 401 ("thk\_\* token not found") when a provider key
  such as `OPENAI_API_KEY` was exported in the shell. Managed-proxy calls now
  always authorize with the Atlas session token, so an ambient shell key can't
  shadow it — for OpenAI, Anthropic, Gemini, and OpenRouter.
- OAuth subscriptions (Sign in with ChatGPT/Codex, Claude Pro/Max, Copilot) are
  no longer blocked when managed LLM spend is on — they run on your own account,
  free of the wallet.

## v1.2.7 — 2026-07-06

### Fixed

- The `initialize-atlas-graph` system skill — invoked by the canvas and the
  research agent — now resolves in every install. Released builds load skills
  from the Atlas catalog, which omitted it, so it failed with "Skill not found"
  outside a source checkout; it is now embedded and materialized locally when the
  catalog lacks it.

### Changed

- In-project workspace polish: on-scale typography (hero heading, chat-markdown,
  tabs), a tighter header, unified sidebar and tab alignment, and corrected
  muted-text tokens that had rendered at full strength.
- Landing page: structured data (JSON-LD) for search engines and async image
  decoding.
- Docs: a changelog, release-process and verification notes, a skills reference,
  and a supported-versions security policy.

## v1.2.6 — 2026-07-06

Atlas experience polish.

### Added

- Unified `openscience status`: connection, plan, wallet balance + lifetime
  spend, recent usage, managed-compute availability, and the bundled `atlas`
  companion version — all in one view, degrading gracefully when signed out.
- Wallet settings panel and a `/settings/wallet` route surfacing the Atlas
  credits balance, billing mode, and recent transaction ledger.
- Browser Atlas login (`/account/login-key` + a first-run setup dialog) and a
  first-run flow that no longer dead-ends when no model is configured.
- Opt-in reviewer gate (`experimental.reviewGate`) that runs a blind review pass
  on a primary agent's final answer and annotates it with the verdict.

### Changed

- Bundled `@synsci/atlas` companion bumped to `^0.13.2` so managed compute
  resolves.
- arXiv retrieval hardened: per-host throttling, honest content negotiation,
  PDF-link and error-response parsing, and graceful degradation when a source
  fails.
- Model-catalog tests are deterministic (fixtured) with a nightly delisting
  tripwire.

### Fixed

- Every Atlas network call is timeout-bounded, fixing a hang where
  `project init` could run indefinitely.
- Credential sync no longer flips managed billing when a user's own exported key
  is present; synced files are written atomically.
- Codex OAuth recovers from refresh-token rotation and distinguishes a
  reconnect-required error from a transient one.

## v1.2.5 — 2026-07-05

- Seamless first-run onboarding with a clear managed vs. BYOK choice.
- Centralized catalog model pins with a delisting tripwire.
- OpenScience docs site at openscience.sh/docs.
- Spend controls in the workspace; compute keys actually applied.

## v1.2.4 — 2026-07-04

- Codex recovers from refresh-token rotation races.
- Release and npm-provenance fixes so packages publish reliably.

## v1.2.3 — 2026-07-04

- First tagged release of the `1.2.x` line.
