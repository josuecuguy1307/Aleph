#!/usr/bin/env python3
"""Fail a release build if the SearXNG server or its distribution files shipped.

Client references to the optional external provider are allowed; the server
implementation, Python distribution, and vendored settings are not.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def verify(app: Path) -> list[Path]:
    if not (app / "Contents/Info.plist").is_file():
        raise ValueError(f"not a macOS app bundle: {app}")
    forbidden = []
    for path in app.rglob("*"):
        rel = path.relative_to(app)
        parts = tuple(part.lower() for part in rel.parts)
        name = path.name.lower()
        if ("searxng" in parts or name.startswith("searxng-") and name.endswith(".dist-info")
                or name == "searx" and path.is_dir() and any(p == "site-packages" for p in parts)):
            forbidden.append(rel)
    return forbidden


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    hits = verify(args.app)
    for path in hits[:25]:
        print(f"SEARXNG_BUNDLE_BLOCKER: {path}")
    print(f"SEARXNG_CODE_IN_ALEPH_BUNDLE={'NO' if not hits else 'YES'}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
