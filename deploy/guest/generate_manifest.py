#!/usr/bin/env python3
"""Generate the integrity manifest for the exact signed guest payload.

The build signs the runner first, then invokes this script, then freezes the
result.  No runner digest is maintained by hand or copied from a previous
build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

ASSETS = ("aleph-guest-runner", "Image.arm64", "rootfs.arm64.cpio.gz")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def generate(runtime: Path, output: Path) -> dict:
    values = {}
    for name in ASSETS:
        path = runtime / name
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"guest manifest: missing or unsafe asset: {path}")
        values[name] = digest(path)
    document = {"version": 1, "assets": values}
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.runtime / "guest-manifest.json"
    document = generate(args.runtime.resolve(), output.resolve())
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
