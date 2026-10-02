# Building from this source snapshot

The certified 0.1.2 application was built from
`58121ccb8c9f780641d97ffb467d8d7f3cf88cfc`. This snapshot preserves exported
source blobs; see SOURCE_PROVENANCE.json for its narrowly scoped publication changes.
It is not a claim of bit-for-bit reproducibility or a clean-host build certification.

## Existing application build entry point

Use `./deploy/fase4/build_app.sh public`. Do not bypass its 40 GiB safety gate.
The entry point produces an isolated .app; it rejects ALEPH_DMG=1. No Developer ID
signing or notarization is required for the local ad-hoc build flow.

The build needs macOS/Apple Silicon with Xcode Command Line Tools and Swift,
Rust/Cargo, Node/npm, Bun, the pnpm/Yarn versions used by the vendored lockfiles,
Python and uv. The certified local build used Node 24.5.0, Bun 1.3.14 and
PyInstaller 6.21.0. Consult the existing package manifests and scripts rather than
updating dependency pins to make a build pass.

Prepare the backend environment in this checkout:

```sh
python3 -m venv product/backend/.venv
product/backend/.venv/bin/python -m pip install -r product/backend/requirements.txt
product/backend/.venv/bin/python -m pip install pyinstaller==6.21.0
```

First run the existing prebuild scripts in order, in an isolated development
environment with your own HOME, temporary directory and caches:

```sh
bash deploy/fase6/producir_busqueda.sh
bash deploy/fase6/producir_research.sh
bash deploy/fase6/producir_browser.sh
```

These download/install the search/browser runtimes and their dependencies; the
application build does not invoke them automatically. The official application
build then materializes and checks the vendored workspaces and Tauri shell
dependencies. Source, lockfiles, specifications and existing build scripts are
included; generated outputs are not. Backend requirements contain version ranges,
so dependency resolution is not fully reproducible.

## External binary prerequisites kept outside ordinary Git

The existing build also expects these inputs, which are deliberately not included
in ordinary Git history. The two guest images and matching source/notices bundle
are prepared release assets, locally compliance-cleared but not uploaded:

| Input location | Version/provenance |
| --- | --- |
| `third_party/officecli/bin/officecli-macos-arm64` | Official OfficeCLI v1.0.145; asset URL and digest in `third_party/officecli/UPSTREAM-IDENTITY.json` |
| `third_party/gws/bin/gws-macos-arm64` | gws v0.22.5; provenance in `third_party/gws/IMPORT.md` |
| `third_party/opencode/bin/opencode-darwin-arm64` | OpenCode v1.17.11; release ZIP and executable digests in `third_party/opencode/IMPORT.md` |
| `deploy/guest/runtime/aleph-guest-runner` | Runner source is `deploy/guest/GuestRunner.swift`; entitlements and manifest generator are included |
| `deploy/guest/runtime/Image.arm64` | Exact certified Alpine 6.18.52-0-virt kernel; GPL-2.0-only, corresponding source/config/patches supplied separately |
| `deploy/guest/runtime/rootfs.arm64.cpio.gz` | Exact certified Alpine 3.24.2 + offline APK payload; all 206 package licenses/sources/notices accounted for |

The certified-source hashes of the omitted inputs are recorded in
`SOURCE_PROVENANCE.json`; no private filesystem paths or their contents are
embedded there. Obtain/recreate inputs independently and verify their provenance,
licenses and digests before building. The guest release plan and verified hashes
are in `deploy/guest/ASSETS.md` and `deploy/guest/assets.json`.
`deploy/guest/fetch_assets.py` (Python 3.11+) retrieves the exact two binary assets
from an assigned immutable public Release into the locations already consumed by
the official build. It does not download the 1.41 GiB source bundle automatically.
Download `aleph-0.1.2-guest-sources.tar.zst` from that **same Release** for sources,
Alpine build metadata and original notices; verify its recorded SHA-256, then use
`zstd -dc aleph-0.1.2-guest-sources.tar.zst | tar -xf -`. All three must accompany
redistribution, with equivalent public source access. No Release URL is assigned
or published by this task. Do not silently reuse an installed app or replace a
canonical historical release.

The official build **copies** the precompiled Swift guest runner and supplied
images; it does not compile GuestRunner.swift automatically. It generates their
integrity manifest and rehashes final bytes after signing. Public runner source,
entitlements and manifest generator are included. The source bundle's
INSTALLATION.md documents compatible library/image replacement for your own
modified build without private signing keys; this is not full image regeneration.

**Outstanding build-readiness limitation:** the certified source has no complete
recipe for regenerating the exact guest kernel/root filesystem from a clean
checkout. `resolve_apks.py` alone is not that recipe. This snapshot therefore is
not yet certified as a turnkey public .app build. Exact certified images exist
locally and their upstream provenance is verified. Their corresponding-source
and notice materials are now assembled, version/hash-verified and locally cleared
in `deploy/guest/COMPLIANCE.md`. Publication still requires explicit release
approval and all three assets together. Availability of those images, once
released, will not resolve source reproducibility.

Once verified prerequisites are present, the unchanged official command is:

```sh
env -u ALEPH_DMG CSC_IDENTITY_AUTO_DISCOVERY=false ./deploy/fase4/build_app.sh public
```

Onshape remains **optional / not certified**. Configure only your own credentials
outside Git; no provider secrets or user/session state are included in this snapshot.
