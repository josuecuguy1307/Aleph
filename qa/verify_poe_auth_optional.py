#!/usr/bin/env python3
"""Verify Poe OAuth is omitted while the packaged Aleph runtime still starts."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
OPENCODE_PACKAGE = REPO / "third_party/dochaus/packages/opencode/package.json"
DOCHAUS_LOCK = REPO / "third_party/dochaus/bun.lock"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    app = args.app.resolve()

    package = json.loads(OPENCODE_PACKAGE.read_text(encoding="utf-8"))
    dependencies = package.get("dependencies", {})
    assert "opencode-poe-auth" not in dependencies, "Poe OAuth remains a production dependency"
    assert "opencode-gitlab-auth" in dependencies, "unrelated GitLab auth dependency changed"
    lock = DOCHAUS_LOCK.read_text(encoding="utf-8")
    assert '"opencode-poe-auth"' not in lock, "Poe auth plugin remains in the Bun lock"
    assert '"poe-oauth"' not in lock, "unlicensed exact Poe OAuth package remains in the Bun lock"

    module_roots = (
        app / "Contents/Resources/third_party/dochaus/node_modules",
        app / "Contents/Frameworks/third_party/dochaus/node_modules",
    )
    for modules in module_roots:
        for name in ("opencode-poe-auth", "poe-oauth"):
            path = modules / name
            assert not path.exists() and not path.is_symlink(), f"Poe package remains in app: {path}"

    clean_start = REPO / "qa/verify_clean_user_bundle.py"
    subprocess.run([sys.executable, str(clean_start), "--app", str(app)], check=True)
    print("PASS Poe OAuth excluded; clean Aleph startup and 6/6 workspaces verified")


if __name__ == "__main__":
    main()
