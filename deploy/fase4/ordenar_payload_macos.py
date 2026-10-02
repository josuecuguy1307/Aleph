"""Apply PyInstaller's own macOS BUNDLE layout to the Tauri payload.

COLLECT's mixed onedir layout cannot be sealed inside Contents/Frameworks.
Keep code in Frameworks and data in Resources, with PyInstaller cross-links
preserving the paths used by the bootloader, packages, and relative dylibs.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PyInstaller.building.osx import BUNDLE

MACHO = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}


def _neutral_prefix(match, label):
    """Keep Mach-O string offsets intact while retaining relative diagnostic paths."""
    old = match.group(0)
    base = b"./" + label + b"/"
    if len(base) > len(old):
        raise ValueError("build-path prefix is too short to scrub safely")
    return base[:-1] + b"_" * (len(old) - len(base)) + b"/"


def scrub_binary_build_paths(app):
    """Remove local-machine path prefixes from known compiled payloads before signing.

    Only path prefixes change, without shifting bytes or stripping function names.
    The allowlist prevents rewriting arbitrary application strings or user data.
    """
    root = Path(app).resolve() / "Contents"
    paths = [root / "MacOS/app", root / "Frameworks/third_party/openscience/bin/openscience"]
    paths.extend((root / "Frameworks/litellm/rust_bridge").glob("_native*.so"))
    changed = 0
    for path in paths:
        if not path.is_file():
            continue
        if not is_macho(path):
            raise RuntimeError(f"expected Mach-O binary: {path}")
        original = path.read_bytes()
        clean = re.sub(rb"/Users/[^/\x00\r\n]{1,80}/", lambda m: _neutral_prefix(m, b"src"), original)
        clean = re.sub(rb"Library/Caches/[^/\x00\r\n]{1,80}/", lambda m: _neutral_prefix(m, b"cache"), clean)
        if clean != original:
            if b"/Users/" in clean:
                raise RuntimeError(f"unscrubbed local path in {path}")
            path.write_bytes(clean)
            changed += 1
    print(f"macOS native build paths: {changed} binaries scrubbed before signing")


def scrub_text_build_paths(app):
    """Remove absolute checkout paths emitted by Next standalone build manifests.

    Next records ``outputFileTracingRoot`` and module proxy paths in JSON/JS files.
    Those are build metadata, not runtime data, and must not expose the machine that
    produced the release. Restrict the rewrite to UTF-8 text payloads so executable
    bytes and packaged user content keep their exact representation.
    """
    root = Path(app).resolve() / "Contents"
    extensions = {".js", ".json", ".map", ".html", ".css", ".txt", ".mjs", ".cjs"}
    changed = 0
    for namespace in ("Frameworks", "Resources"):
        base = root / namespace
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in extensions:
                continue
            try:
                original = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            clean = re.sub(r"/Users/[^/\x00\r\n]+/", "/__aleph_build__/", original)
            if clean != original:
                path.write_text(clean, encoding="utf-8")
                changed += 1
    print(f"macOS text build paths: {changed} files scrubbed before signing")


def prune_bytecode_caches(app):
    """Do not ship build-machine paths embedded in disposable Python caches."""
    removed = 0
    for namespace in ("Frameworks", "Resources"):
        root = Path(app).resolve() / "Contents" / namespace
        if not root.is_dir():
            continue
        for parent, directories, files in os.walk(root):
            for name in list(directories):
                if name != "__pycache__":
                    continue
                cache = Path(parent) / name
                directories.remove(name)
                if cache.is_symlink():
                    cache.unlink()
                else:
                    shutil.rmtree(cache)
                removed += 1
            for name in files:
                if name == "__pycache__":
                    cache = Path(parent) / name
                    if cache.is_symlink():
                        cache.unlink()
                        removed += 1
    print(f"macOS payload: {removed} disposable Python cache directories removed")


RELEASE_TEST_FILES = (
    "product/app/design/verify_ux_scrub_front.mjs",
    "product/app/design/sala/verify_acct_toast_6b.mjs",
    "product/app/design/sala/verify_step4_4a.mjs",
    "product/app/design/sala/verify_step4_4b.mjs",
    "product/app/design/sala/verify_ux_b4_front.mjs",
    "platform/gates/tests_gates.py",
    "platform/assembler/verify_traductor.py",
    "platform/assembler/verify_costura_obra2.py",
    "platform/assembler/verify_costura_obra3.py",
    "platform/assembler/cli_brain/verify_cli_streaming.py",
    "platform/sala/research/lib/transformers/testing_utils.py",
)

# These trees were audited against the shipping entry points before release.
# Design runs from its compiled Electron ZIP (not website/); Aleph's frontend
# does not request the visual-QA screenshots or verification harnesses. Keep
# all other source, package metadata, fixtures and source maps by default.
RELEASE_NONRUNTIME_DIRS = (
    "product/app/design/cuarto/screenshots",
    "product/app/design/sala/verify",
    "product/app/design/sala-v2/verify",
    "third_party/codesign/website",
    "third_party/codesign/.Codex",
    "third_party/codesign/.github",
    "third_party/codesign/.changeset",
    "third_party/dochaus/.github",
)


def prune_release_nonruntime(app):
    """Drop only audited QA/build trees from the new, unsigned payload.

    Never follow symlinks or discard a newly added license/notice by accident.
    This runs before the PyInstaller layout is moved into Resources and signed.
    """
    root = Path(app).resolve() / "Contents/Frameworks"
    removed = 0
    for relative in RELEASE_NONRUNTIME_DIRS:
        target = root / relative
        if not target.exists() and not target.is_symlink():
            continue
        cursor = target
        while cursor != root:
            if cursor.is_symlink():
                raise RuntimeError(f"non-runtime prune target crosses a symlink: {relative}")
            cursor = cursor.parent
        if not target.is_dir() or any(path.is_symlink() for path in target.rglob("*")):
            raise RuntimeError(f"non-runtime prune target is not a plain directory: {relative}")
        if any(
            any(word in file.name.lower() for word in ("license", "notice", "copying", "copyright"))
            for file in target.rglob("*") if file.is_file()
        ):
            raise RuntimeError(f"non-runtime prune target gained a license/notice: {relative}")
        shutil.rmtree(target)
        removed += 1
    print(f"macOS payload: {removed} audited QA/build directories excluded")


def prune_release_tests(app):
    """Keep synthetic QA credentials and upstream CI tokens out of the payload."""
    root = Path(app).resolve() / "Contents/Frameworks"
    removed = 0
    for relative in RELEASE_TEST_FILES:
        path = root / relative
        if path.is_file() and not path.is_symlink():
            path.unlink()
            removed += 1
    print(f"macOS payload: {removed} test-only files excluded")


def is_macho(path):
    with path.open("rb") as stream:
        header = stream.read(8)
    if header[:4] not in MACHO:
        return False
    if header[:4] in {b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf", b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca"}:
        endian = "big" if header[0] == 0xca else "little"
        return 0 < int.from_bytes(header[4:8], endian) <= 16
    return True


def crosslink_workspace_packages(app):
    app = Path(app).resolve()
    repaired = 0
    # Use the launcher's actual workspace globs and package manifests. Create the
    # map before signing, rather than letting start.sh mutate the sealed bundle.
    for namespace in ("Frameworks", "Resources"):
        root = app / "Contents" / namespace / "third_party/dochaus"
        candidates = [root / "packages/sdk/js", root / "packages/slack"]
        for glob in ("packages", "packages/console", "packages/stats"):
            base = root / glob
            if base.is_dir():
                candidates.extend(base.iterdir())
        for source in candidates:
            manifest = source / "package.json"
            if not manifest.is_file():
                continue
            name = json.loads(manifest.read_text()).get("name", "")
            if not name or any(part in ("", ".", "..") for part in name.split("/")):
                continue
            destination = root / "node_modules" / name
            target = os.path.relpath(source, destination.parent)
            if destination.is_symlink() and os.readlink(destination) == target:
                continue
            if destination.exists() and not destination.is_symlink():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_symlink():
                destination.unlink()
            destination.symlink_to(target)
            repaired += 1
    print(f"macOS workspace module aliases: {repaired} repaired")


def seal_native(app):
    contents = Path(app).resolve() / "Contents"
    framework = contents / "Frameworks"
    guest_runner = framework / "deploy/guest/runtime/aleph-guest-runner"
    if not guest_runner.is_file():
        raise RuntimeError("guest runner missing from macOS payload")
    # The Mach-O runner is classified into Frameworks; opaque guest data is
    # materialized under Resources, which is the runtime root used by Aleph.
    guest_manifest = contents / "Resources/deploy/guest/runtime/guest-manifest.json"
    if not guest_manifest.is_file() or guest_manifest.is_symlink():
        raise RuntimeError("guest integrity manifest missing from macOS payload")
    guest_entitlements = Path(__file__).resolve().parents[1] / "guest/Virtualization.entitlements"
    if not guest_entitlements.is_file():
        raise RuntimeError("guest virtualization entitlements missing")
    # PyInstaller may rewrite/sign Mach-O datas while freezing. Sign the final
    # post-freeze runner first, then regenerate the manifest from those bytes.
    subprocess.run(["codesign", "--force", "--sign", "-", "--entitlements",
                    str(guest_entitlements), str(guest_runner)], check=True)
    subprocess.run(["codesign", "--verify", "--strict", str(guest_runner)], check=True)
    granted = subprocess.run(["codesign", "-d", "--entitlements", "-", str(guest_runner)],
                             capture_output=True, check=True)
    if b"com.apple.security.virtualization" not in granted.stdout + granted.stderr:
        raise RuntimeError("guest runner lost virtualization entitlement")
    resource_runtime = contents / "Resources/deploy/guest/runtime"
    resource_runner = resource_runtime / "aleph-guest-runner"
    if resource_runner.is_symlink():
        resource_runner.unlink()
    shutil.copy2(guest_runner, resource_runner)
    subprocess.run(["codesign", "--verify", "--strict", str(resource_runner)], check=True)
    import hashlib
    try:
        document = json.loads(guest_manifest.read_text(encoding="utf-8"))
        assets = document["assets"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("guest integrity manifest invalid") from exc
    for name in ("aleph-guest-runner", "Image.arm64", "rootfs.arm64.cpio.gz"):
        path = resource_runtime / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"guest resource missing or unsafe: {name}")
        assets[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    temporary_manifest = guest_manifest.with_name(f".{guest_manifest.name}.tmp")
    temporary_manifest.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, guest_manifest)
    binaries = []
    bundles = []
    for parent, directories, files in os.walk(framework):
        path = Path(parent)
        if path.name.endswith(".framework"):
            bundles.append(path)
        for name in files:
            leaf = path / name
            if not leaf.is_symlink() and is_macho(leaf):
                binaries.append(leaf)
    repaired = 0
    for path in binaries + sorted(bundles, key=lambda p: len(p.parts), reverse=True):
        if path == guest_runner:
            # The runner was signed above after PyInstaller finished rewriting it.
            subprocess.run(["codesign", "--verify", "--strict", str(path)], check=True)
            granted = subprocess.run(["codesign", "-d", "--entitlements", "-", str(path)],
                                     capture_output=True, check=True)
            if b"com.apple.security.virtualization" not in granted.stdout + granted.stderr:
                raise RuntimeError("guest runner lost virtualization entitlement")
            repaired += 1
            continue
        verified = subprocess.run(["codesign", "--verify", "--strict", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if verified.returncode:
            subprocess.run(["codesign", "--force", "--sign", "-", "--preserve-metadata=entitlements", str(path)], check=True)
            subprocess.run(["codesign", "--verify", "--strict", str(path)], check=True)
            repaired += 1
    print(f"macOS native signatures: {len(binaries)} binaries checked; {repaired} repaired")


def arrange(app, *, require_chromium=True):
    app = Path(app).resolve()
    prune_bytecode_caches(app)
    prune_release_tests(app)
    prune_release_nonruntime(app)
    framework = app / "Contents/Frameworks"
    toc = []
    for parent, directories, files in os.walk(framework):
        for name in list(directories):
            path = Path(parent) / name
            if path.is_symlink():
                directories.remove(name)
                toc.append((str(path.relative_to(framework)), os.readlink(path), "SYMLINK"))
        for name in files:
            path = Path(parent) / name
            if path.is_symlink():
                toc.append((str(path.relative_to(framework)), os.readlink(path), "SYMLINK"))
            else:
                kind = "BINARY" if is_macho(path) else "DATA"
                toc.append((str(path.relative_to(framework)), str(path), kind))
    mapped = BUNDLE._process_bundle_toc(BUNDLE, toc)
    temporary = Path(tempfile.mkdtemp(prefix=".aleph-payload-", dir=app.parent))
    source = temporary / "payload"
    moves = []
    links = []
    framework.rename(source)
    framework.mkdir()
    try:
        # Fail before moving files if Tauri already owns a destination resource.
        for name, _, kind in mapped:
            destination = app / name
            if destination.exists() or destination.is_symlink():
                raise RuntimeError(f"Destination already exists: {name}")
        for name, original, kind in mapped:
            if kind == "SYMLINK":
                continue
            destination = app / name
            origin = source / Path(original).relative_to(framework)
            destination.parent.mkdir(parents=True, exist_ok=True)
            origin.rename(destination)
            moves.append((origin, destination))
        for name, target, kind in mapped:
            if kind != "SYMLINK":
                continue
            destination = app / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(target)
            links.append(destination)
    except Exception:
        for link in reversed(links):
            link.unlink()
        for origin, destination in reversed(moves):
            origin.parent.mkdir(parents=True, exist_ok=True)
            destination.rename(origin)
        shutil.rmtree(framework)
        source.rename(framework)
        raise
    finally:
        shutil.rmtree(temporary)
    if require_chromium:
        materialize_chromium_resources(app)
        materialize_guest_runtime(app)
    print(f"macOS payload: {len(toc)} entries arranged with PyInstaller BUNDLE")


def materialize_chromium_resources(app, *, verify_signatures=True):
    """Keep Chromium's executable and sibling data real under Resources.

    PyInstaller puts the Mach-O in Frameworks and DATA in Resources, crossing
    the boundary with symlinks. Chromium's sandboxed child rejects that layout.
    Data cannot instead be copied into Frameworks: codesign interprets it as
    unsigned nested code. Copy only Chromium's four signed Mach-O files into
    Resources, beside the real ICU/pak files, and launch from that directory.
    """
    contents = Path(app).resolve() / "Contents"
    resources = (contents / "Resources").resolve()
    relative = "third_party/vane/.playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64"
    chrome = resources / relative
    framework_chrome = (contents / "Frameworks/third_party/vane/__dot__playwright/"
                        "chromium_headless_shell-1217/chrome-headless-shell-mac-arm64")
    if not chrome.is_dir() or not framework_chrome.is_dir():
        raise RuntimeError("packaged Chromium directory missing")
    if not (framework_chrome / "chrome-headless-shell").is_file():
        raise RuntimeError("packaged Chromium executable missing")
    copied = 0
    for name in ("chrome-headless-shell", "libEGL.dylib", "libGLESv2.dylib", "libvk_swiftshader.dylib"):
        child = chrome / name
        if not child.is_symlink():
            if not child.is_file():
                raise RuntimeError(f"Chromium native component missing: {name}")
            continue
        target = child.resolve(strict=True)
        if not target.is_relative_to(framework_chrome.resolve()) or not is_macho(target):
            raise RuntimeError(f"Chromium native component escaped packaged Frameworks: {child}")
        child.unlink()
        shutil.copy2(target, child)
        if verify_signatures:
            subprocess.run(["codesign", "--verify", "--strict", str(child)], check=True)
        copied += 1
    for required in ("icudtl.dat", "headless_lib_data.pak", "v8_context_snapshot.arm64.bin"):
        if not (chrome / required).is_file() or (chrome / required).is_symlink():
            raise RuntimeError(f"Chromium resource unavailable to sandbox: {required}")
    # Also repair a previous, unsuccessful validation layout idempotently.
    for child in framework_chrome.iterdir():
        if child.name in {"chrome-headless-shell", "libEGL.dylib", "libGLESv2.dylib", "libvk_swiftshader.dylib"}:
            continue
        target = chrome / child.name
        if not target.exists() or target.is_symlink():
            raise RuntimeError(f"Chromium data resource missing: {child.name}")
        if child.is_symlink():
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        child.symlink_to(os.path.relpath(target, child.parent))
    print(f"macOS Chromium: {copied} native files materialized beside sandbox-visible data")


def materialize_guest_runtime(app):
    """Place a real runner beside Resources data before final post-freeze signing."""
    contents = Path(app).resolve() / "Contents"
    source = contents / "Frameworks/deploy/guest/runtime/aleph-guest-runner"
    runtime = contents / "Resources/deploy/guest/runtime"
    destination = runtime / "aleph-guest-runner"
    manifest = runtime / "guest-manifest.json"
    if not source.is_file() or source.is_symlink():
        raise RuntimeError("guest runner missing or unsafe in Frameworks")
    if not manifest.is_file() or manifest.is_symlink():
        raise RuntimeError("guest manifest missing or unsafe in Resources")
    if destination.is_symlink():
        destination.unlink()
    shutil.copy2(source, destination)
    subprocess.run(["codesign", "--verify", "--strict", str(destination)], check=True)
    print("macOS guest runtime: runner materialized; final entitlement signing follows")


def self_test():
    with tempfile.TemporaryDirectory() as directory:
        app = Path(directory) / "Aleph.app"
        framework = app / "Contents/Frameworks"
        samples = {"catalog/exa.json": b'{"title":"Complete data"}', "package.dist-info/METADATA": b"metadata", "mixed/.libs/native.dylib": b"\xcf\xfa\xed\xfe" + b"native", "mixed/values.json": b"all twelve values", "third_party/dochaus/runtime/bun": b"\xcf\xfa\xed\xfe" + b"runtime", "third_party/dochaus/node_modules/native/binary.node": b"\xcf\xfa\xed\xfe" + b"native", "third_party/dochaus/node_modules/native/package.json": b"{}"}
        for name, data in samples.items():
            path = framework / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        workspace = framework / "third_party/dochaus"
        (workspace / "packages/core").mkdir(parents=True)
        (workspace / "packages/core/package.json").write_text('{"name":"@example/core"}')
        scope = workspace / "node_modules/@example"
        scope.mkdir(parents=True)
        (scope / "core").symlink_to("../../packages/core")
        arrange(app, require_chromium=False)
        # Reproduce the observed frozen payload: a scope containing only workspace
        # links exists in Frameworks while Bun resolves source from Resources.
        resource_scope = app / "Contents/Resources/third_party/dochaus/node_modules/@example"
        if resource_scope.is_dir() and not resource_scope.is_symlink():
            if scope.is_symlink():
                scope.unlink()
            resource_scope.rename(scope)
        crosslink_workspace_packages(app)
        for namespace in ("Frameworks", "Resources"):
            assert (app / "Contents" / namespace / "third_party/dochaus/node_modules/@example/core/package.json").read_text() == '{"name":"@example/core"}'
        for name, data in samples.items():
            assert (framework / name).read_bytes() == data
            assert (app / "Contents/Resources" / name).read_bytes() == data
        assert (framework / "catalog").is_symlink()
        assert (framework / "package.dist-info").is_symlink()
        assert (framework / "mixed/.libs/native.dylib").resolve().is_relative_to(framework.resolve())
        assert (framework / "mixed/values.json").resolve().is_relative_to((app / "Contents/Resources").resolve())
        print("PASS: data, native code, dotted directories and cross-links preserved")


if __name__ == "__main__":
    if sys.argv[1] == "--self-test":
        self_test()
    elif sys.argv[1] == "--seal-only":
        seal_native(sys.argv[2])
    elif sys.argv[1] == "--repair-workspace-links":
        crosslink_workspace_packages(sys.argv[2])
    else:
        arrange(sys.argv[1])
        crosslink_workspace_packages(sys.argv[1])
        scrub_binary_build_paths(sys.argv[1])
        scrub_text_build_paths(sys.argv[1])
        seal_native(sys.argv[1])
