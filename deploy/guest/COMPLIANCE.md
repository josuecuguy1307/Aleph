# Guest redistribution disposition — Aleph 0.1.2

**GUEST REDISTRIBUTION: CLEARED for the prepared assets and accompanying source
and notice materials. Nothing has been published.** Release approval must ship
all three assets together with equivalent public access to corresponding source.

The explicit 206-row [COMPLIANCE.tsv](COMPLIANCE.tsv) preserves exact package
version, original declared license, reviewed license disposition, source origin,
pinned Alpine commit, source-obligation classification and source/notice mapping.
The complete machine-readable per-package requirements and original notice paths
are in `PACKAGE_COMPLIANCE.json` inside
`aleph-0.1.2-guest-sources.tar.zst`. [COMPLIANCE_AUDIT.json](COMPLIANCE_AUDIT.json)
records the final checked counters; [KERNEL_PROVENANCE.json](KERNEL_PROVENANCE.json)
records the exact kernel source/config/patch inputs and hashes.

## Corresponding source and original notices

The source bundle retains 169 rootfs source origins plus the kernel, all **509**
APKBUILD inputs checked against their pinned SHA-512 values, and complete Alpine
packaging trees, preparation/build/install scripts, patches and configs. All
206 binary/package versions match the retained recipes. Original archives remain
byte-for-byte intact, preserving file-level copyrights in addition to **4,371**
extracted original notice files and **200** unchanged source files with inline
notices. **47** canonical SPDX license/exception texts are supplemental only.

Pandoc's exact freeze is covered by **257** Haskell sources (GHC 9.10.3 source
contains RTS 1.0.2), with **256** Hackage revisions selected and verified at the
freeze's index-state. Libglycin's Alpine-patched Cargo.lock is covered by **303**
exact source crates checked against its checksums. Original workspace notices
omitted from crate tarballs were retained from their exact VCS commits; explicit
MIT declarations without standalone files are identified individually, not
silently replaced by invented copyrights. GHC Alpine packaging and abuild source
are also included as build support.

## Non-generic license reviews

- **Qhull:** [original COPYING.txt](licenses/qhull/COPYING.txt) must accompany
  Qhull and products containing it. Preserve copyrights; original source is at
  **www.qhull.org**. Changes require person/date/reason. Its Alpine recipe contains
  no Qhull source patch.
- **HDF5:** retain [COPYING](licenses/hdf5/COPYING),
  [COPYING_LBNL_HDF5](licenses/hdf5/COPYING_LBNL_HDF5), and the examples notices in
  the source bundle. Preserve THG/UIUC/UC/LBNL/DOE statements and disclaimers in
  binary materials; no endorsement. Retain voluntary-enhancement grant conditions
  and dated-change requirements. The exact Alpine version patch is preserved.
  The recipe uses BSD **libaec**, not an unlicensed SZIP binary.
- **GLU/SGI:** both original licenses and all Exhibit A/OpenGL notices are retained.
  SGI-B-1.1 Section 8 permits later SGI versions: SGI-B-2.0 is elected for original
  SGI code, avoiding incompatible old SGI-1.1 restrictions on GPL-linked use.
  No SGI endorsement or unverified OpenGL compliance is claimed.
- **Digital Equipment/libxkbcommon:** the complete
  [original LICENSE](licenses/libxkbcommon/LICENSE) retains DEC's copyright,
  permission and warranty disclaimer in copies/supporting docs, and its prohibition
  on using Digital's name in publicity without permission. All other MIT/Open
  Group/HPND and source-only test-data notices remain intact.
- **ICU:** retain the [complete original LICENSE](licenses/icu/LICENSE), not merely
  old `ICU` metadata. It includes Unicode V3, original IBM and dictionary/data
  notices, NAIST/IPADIC/ICOT disclaimers, BSD/MIT material and Autoconf exceptions.
- **GCC/LLVM:** preserve actual original runtime/compiler exceptions. GCC's
  source confirms GPLv3 plus Runtime Library Exception 3.1 despite broader/older
  APK metadata; LLVM's source confirms its Apache/LLVM exceptions.
- **Qt, Python, fonts, FreeType and IJG:** complete original per-file license,
  attribution/exception material is supplied, not replaced by a single umbrella
  label. Required acknowledgements and restrictions are in the bundle's LICENSES.md.

## Installation/relinking and scope

`ELF_LINKAGE.json` records read-only inspection of **836** ELF files; there are
**zero** shipped static `.a` libraries. Shared LGPL libraries can be replaced;
Pandoc's embedded Haskell code has corresponding source. `INSTALLATION.md` supplies
the replacement/rebuild procedure and public manifest-generation path. No private
signing secret is required, and no extra restriction on modifying or debugging
third-party components is imposed.

GPL/LGPL/MPL and other source obligations are met by actual matching source
delivery alongside the binaries, not generic upstream links. The planned release
is downloadable software, not a transfer of a locked hardware device.

Apache-2.0 covers Aleph-owned source only. Third-party terms remain authoritative.
**Full Aleph guest-image regeneration is still pending and is not claimed**;
package source delivery does not establish a clean-host or bit-for-bit image build.
Onshape remains **OPTIONAL / NOT CERTIFIED**.
