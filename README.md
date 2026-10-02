# Aleph 0.1.2

Aleph is a local-first desktop application for assembling agents in El Cuarto / The
Workshop and using them in La Sala. The macOS application combines a Tauri shell,
a Python backend, and vendored workspace integrations.

This is a clean source snapshot derived from certified source commit
`58121ccb8c9f780641d97ffb467d8d7f3cf88cfc`. It has a new Git history; the private
development history and local release evidence are not included. See
[SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json) for the source-tree/inventory hashes,
exclusions, and snapshot-only changes.

## Source layout

- `product/`: application UI, backend, recipes and tools.
- `platform/`: agent execution, integrations, storage and safety components.
- `catalog/`, `i18n/`, `onboarding/`: checked-in catalogs, translations and templates.
- `deploy/`: existing build specifications, deployment source and native shell.
- `third_party/`: vendored source with its original licenses and attribution notices.
- `qa/`, `eval/`, `tools/`: test and build-support source, without captured release evidence.
- `docs/guia/`: user-facing guides; `docs/licencias/`: required license texts.

## Build

Start with [BUILDING.md](BUILDING.md). The existing official application entry point
is `./deploy/fase4/build_app.sh public`; its 40 GiB disk safety gate is unchanged.
This source-only snapshot excludes compiled runtimes, virtual environments and
dependency caches. Some required external build inputs must be materialized first;
the missing guest-image regeneration procedure is documented rather than hidden.
No binary rebuild or clean-checkout build certification was performed for this snapshot.

Onshape is **optional / not certified**. No live Onshape verification is claimed.

The checked-in client Supabase anonymous key is public client configuration, not a
service-role credential. It does not grant administrative access. A self-hosted fork
should configure its own backend and authentication deployment. Never commit real
API keys, OAuth state, session data or private database contents.

## License and branding

Aleph-owned source code is licensed under the [Apache License 2.0](LICENSE).
Third-party code and assets retain their own licenses; see
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES) and [ATTRIBUTIONS.md](ATTRIBUTIONS.md).

The Aleph name, logo, mascot and official branding are **not licensed under
Apache-2.0**. See [TRADEMARKS.md](TRADEMARKS.md). Forks may identify their origin
factually, but must not imply an official release or endorsement.

Contributions are welcome under Apache-2.0; see [CONTRIBUTING.md](CONTRIBUTING.md).
