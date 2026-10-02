#!/usr/bin/env python3
"""Fail-closed gate for the guest bytes and hash used by the packaged path."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ASSETS = ("aleph-guest-runner", "Image.arm64", "rootfs.arm64.cpio.gz")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify(app: Path) -> dict[str, str]:
    runtime = app / "Contents/Resources/deploy/guest/runtime"
    framework_runner = app / "Contents/Frameworks/deploy/guest/runtime/aleph-guest-runner"
    manifest_path = runtime / "guest-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise RuntimeError(f"missing packaged guest manifest: {manifest_path}")
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = document["assets"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("invalid packaged guest manifest") from exc
    if not isinstance(expected, dict):
        raise RuntimeError("invalid packaged guest manifest")
    actual: dict[str, str] = {}
    for name in ASSETS:
        path = runtime / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing packaged guest asset: {path}")
        actual[name] = digest(path)
        if expected.get(name) != actual[name]:
            raise RuntimeError(
                f"packaged guest hash mismatch: {name}: "
                f"actual={actual[name]} expected={expected.get(name)}"
            )
    if not framework_runner.is_file() or framework_runner.is_symlink():
        raise RuntimeError("missing real guest runner under Frameworks")
    framework_hash = digest(framework_runner)
    if framework_hash != actual["aleph-guest-runner"]:
        raise RuntimeError(
            "Frameworks and Resources guest runners differ: "
            f"frameworks={framework_hash} resources={actual['aleph-guest-runner']}"
        )
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    actual = verify(args.app.resolve())
    print("PASS packaged guest hashes: " + json.dumps(actual, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
