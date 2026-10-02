# Certified Aleph 0.1.2 guest release assets

Source commit: `58121ccb8c9f780641d97ffb467d8d7f3cf88cfc`.
Both unchanged images match the certified commit, source runtime and smoke-tested
.app. No application rebuild or executable behavior/image change was performed.

## GUEST REDISTRIBUTION: CLEARED — publication not performed

The exact binaries and corresponding-source/notices bundle are prepared **outside
Git**, for GitHub Release assets. No Git LFS or large Git blobs are used. The
public repository/tag URL remains unassigned; do not invent one or expose a
private development remote. Explicit publication approval is still required.

| Release filename | Bytes | SHA-256 |
| --- | ---: | --- |
| Image.arm64 | 36241408 | e698a107e4d04117db1a7b0daee99bdae5f0647fba2af50f3cd020a666950ab9 |
| rootfs.arm64.cpio.gz | 279676469 | 7115a4dc8d846e24fa1b3482d504b4f0dce234362323987a6c46b9cd6dcad141 |
| aleph-0.1.2-guest-sources.tar.zst | 1513920651 | 5e6e4b0cb527ddf240ac7ace4bbfc050e2578756bd9c092f355746ad7601f85f |

Ship **all three** at the same immutable tagged Release with equivalent public
source download access and conspicuous source/notice links from the binary release
description. The source bundle's README, LICENSES.md and unchanged original notices
are accompanying binary materials. Do not publish a binary-only release or remove
copyright/attribution/source collateral. `assets.json` records hashes and status;
it does not claim the assets are already public.

## Explicit package/source/notice review

[COMPLIANCE.md](COMPLIANCE.md), [COMPLIANCE.tsv](COMPLIANCE.tsv) and
[COMPLIANCE_AUDIT.json](COMPLIANCE_AUDIT.json) account for **206/206** packages:
16 base-installed plus 190 signed offline APKs, 0 unresolved license classifications,
0 missing required notices and 0 missing corresponding-source obligations.

The source asset includes all 169 rootfs source origins plus the kernel, original
complete archives, 509 pinned SHA-512-verified Alpine packaging inputs,
APKBUILD/patch/config/build/install metadata, original notice/exception texts,
257 exact Haskell dependencies and 303 checksum-pinned Rust crates. The 256 Hackage
revisions match Pandoc's freeze index-state. Original GHC/abuild build support and
the exact Aleph init/runner sources are retained too.

Kernel provenance is complete in [KERNEL_PROVENANCE.json](KERNEL_PROVENANCE.json).
Qhull, HDF5, Digital Equipment and SGI/GLU have specific original-text dispositions,
not generic labels. ICU/GCC/LLVM metadata is distinguished from actual upstream
terms. See [THIRD_PARTY_NOTICES](../../THIRD_PARTY_NOTICES) and
[licenses/](licenses/) for required original collateral. Apache-2.0 covers
**Aleph-owned source only**, never these third-party components generally.

The bundle's INSTALLATION.md and ELF_LINKAGE.json describe shared-library/image
replacement and public manifest generation without private signing secrets.
836 ELF files were inspected; no static .a library is shipped. This preserves
the ability to modify/rebuild LGPL libraries without extra restrictions.

## Verified upstream provenance

Kernel: Alpine 6.18.52-0-virt, aarch64. Official input:
<https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/aarch64/netboot-3.24.2/vmlinuz-virt>
(10387968 bytes, SHA-256
`e45e1f6083d1ed45db6647b422e32b6ae6dc54de7b8190b7b97744fb293412e3`).
Its embedded gzip payload at offset 51832 decompresses to the exact certified
Image.arm64. The bytes were compared over HTTPS; this is not an independent
verification of the netboot release's OpenPGP signature.
The exact Alpine source/patch/config tree is
<https://gitlab.alpinelinux.org/alpine/aports/-/tree/09a165f4c951edf370eddde03b2d1d5fd71805ed/main/linux-lts>.
The bundle includes Linux 6.18 source, the 6.18.52 stable patch, every Alpine patch
and virt.aarch64.config, not merely a generic kernel source URL.

Rootfs base:
<https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/aarch64/alpine-minirootfs-3.24.2-aarch64.tar.gz>,
4028030 bytes, SHA-256
`9bf70a7f18ea44094cbb5f70c58f9af129c8214745743db0e68e5502cc2ce773`.
That digest matches Alpine's official .sha256; all 83 base regular files match
the certified image. All 190 additional APKs have valid Alpine RSA signatures and
matching signed payload digests. [PACKAGES.tsv](PACKAGES.tsv) preserves their exact
declared licenses/source commits as well as the 16 base-installed packages.

Embedded runner.py equals certified guest_runner.py. Embedded init equals
guest_init.sh **plus chmod 600 /dev/hvc1**; both exact variants are retained and
documented rather than falsely claiming equality. Locked/system base accounts
are not personal credentials; no user/session databases or private logs were found.

## Retrieval and use after publication approval

With an assigned immutable public Release URL, use Python 3.11+:

```sh
python3 deploy/guest/fetch_assets.py --release-base-url \
  'https://github.com/OWNER/REPOSITORY/releases/download/REVIEWED_TAG'
```

Those placeholders are not assigned destinations. The helper verifies size and
SHA-256 before placing the two exact images at deploy/guest/runtime/; it never
replaces different existing files. It does not fetch the source bundle automatically.
Download aleph-0.1.2-guest-sources.tar.zst from the **same Release**, verify its
digest above, then extract with zstd -dc ARCHIVE | tar -xf - and check FILES.sha256.
The sources/notices are required collateral for redistribution, even though a
developer using the unmodified images need not recompile those components.

The unchanged build_app.sh public **copies** the precompiled Swift runner and
images; it does not compile GuestRunner.swift itself. It generates an integrity
manifest and rehashes after signing. Git continues to ignore runtime binaries.

Local binary checks need no network or publication:

```sh
python3 deploy/guest/fetch_assets.py --verify-only --asset-dir /path/to/runtime
```

## NOT YET FULLY REPRODUCIBLE

The full recipe to regenerate the Aleph guest image from source remains pending.
Providing matching third-party sources/configuration and verified images means
**source compliance and asset availability**, not a certified clean-host or
bit-for-bit full-image build. No such reproducibility claim is made.
Onshape remains **OPTIONAL / NOT CERTIFIED**.
