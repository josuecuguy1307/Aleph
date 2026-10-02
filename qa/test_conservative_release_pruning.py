"""The macOS release prune list removes QA/build trees, not runtime closures."""

from pathlib import Path

import pytest

from deploy.fase4.ordenar_payload_macos import (
    RELEASE_NONRUNTIME_DIRS,
    prune_release_nonruntime,
)


def test_prunes_only_audited_trees(tmp_path: Path):
    app = tmp_path / "Aleph.app"
    root = app / "Contents/Frameworks"
    for relative in RELEASE_NONRUNTIME_DIRS:
        leaf = root / relative / "qa.txt"
        leaf.parent.mkdir(parents=True)
        leaf.write_text("build-only")

    retained = (
        "product/app/design/Home.dc.html",
        "platform/gates/recipe_enforcer.py",
        "third_party/codesign/apps/desktop/release/aleph-diseno-mac-arm64.zip",
        "third_party/dochaus/packages/opencode/src/index.ts",
        "third_party/dochaus/node_modules/example/package.json",
        "third_party/dochaus/node_modules/example/index.js.map",
        "third_party/dochaus/LICENSE",
        "third_party/vane/.playwright/chromium/chrome-headless-shell",
    )
    for relative in retained:
        leaf = root / relative
        leaf.parent.mkdir(parents=True, exist_ok=True)
        leaf.write_text("runtime or license")

    prune_release_nonruntime(app)
    for relative in RELEASE_NONRUNTIME_DIRS:
        assert not (root / relative).exists()
    for relative in retained:
        assert (root / relative).is_file()


def test_new_license_notice_blocks_pruning(tmp_path: Path):
    app = tmp_path / "Aleph.app"
    target = app / "Contents/Frameworks" / RELEASE_NONRUNTIME_DIRS[0]
    target.mkdir(parents=True)
    (target / "LICENSE.txt").write_text("new notice")

    with pytest.raises(RuntimeError, match="gained a license/notice"):
        prune_release_nonruntime(app)
    assert (target / "LICENSE.txt").is_file()


def test_symlink_blocks_pruning(tmp_path: Path):
    app = tmp_path / "Aleph.app"
    root = app / "Contents/Frameworks"
    elsewhere = tmp_path / "retain"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("keep")
    target = root / RELEASE_NONRUNTIME_DIRS[0]
    target.parent.mkdir(parents=True)
    target.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(RuntimeError, match="crosses a symlink"):
        prune_release_nonruntime(app)
    assert (elsewhere / "keep.txt").is_file()
