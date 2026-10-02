#!/usr/bin/env python3
"""Sanitize generated search/research payload before freezing a public macOS app.

This changes generated dependencies, never a user's runtime data. It is idempotent
and deliberately fails when an upstream layout changes instead of shipping paths
or a fallback vendor API credential by accident.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "platform/sala/research"
SEARCH = ROOT / "platform/sala/busqueda/searxng/lib"
RUNTIME_MARKER = "__ALEPH_RUNTIME_ROOT__"
RUNTIME_SUFFIX = "\n# Resolve copied Python build paths at runtime, not on the build machine.\n" \
    "import sys as _aleph_sys\n" \
    "build_time_vars = {k: v.replace('__ALEPH_RUNTIME_ROOT__', _aleph_sys.prefix) " \
    "if isinstance(v, str) else v for k, v in build_time_vars.items()}\n"
LEGACY_LAUNCHER = (b"#!/bin/sh\n"
                   b"'''exec' \"$(dirname \"$0\")/../../runtime/bin/python3\" \"$0\" \"$@\"\n"
                   b"' '''\n")
CONSOLE_LAUNCHER = (b"#!/bin/sh\n"
                    b"'''exec' env PYTHONPATH=\"$(dirname \"$0\")/..:$(dirname \"$0\")/../../../../../third_party/ldr/src\" "
                    b"\"$(dirname \"$0\")/../../runtime/bin/python3\" \"$0\" \"$@\"\n"
                    b"' '''\n")


def sanitize_console_scripts() -> int:
    scripts = RESEARCH / "lib/bin"
    if not scripts.is_dir():
        return 0
    changed = 0
    for path in scripts.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        raw = path.read_bytes()
        if raw.startswith(LEGACY_LAUNCHER):
            path.write_bytes(CONSOLE_LAUNCHER + raw[len(LEGACY_LAUNCHER):])
            changed += 1
            continue
        first, sep, rest = raw.partition(b"\n")
        if not sep or not first.startswith(b"#!") or b"/research/runtime/bin/python" not in first:
            continue
        # The shell trampoline resolves the Python interpreter relative to the
        # shipped script, and the remainder remains ordinary Python source.
        path.write_bytes(CONSOLE_LAUNCHER + rest)
        changed += 1
    return changed


def sanitize_sysconfig() -> int:
    path = RESEARCH / "runtime/lib/python3.13/_sysconfigdata__darwin_darwin.py"
    if not path.is_file():
        raise RuntimeError(f"missing Python sysconfig payload: {path}")
    source = path.read_text()
    if RUNTIME_MARKER in source:
        return 0
    prefixes = set(re.findall(r"/Users/[^\s\"']+/research/runtime/\.uv/cpython-[^/\s\"']+", source))
    if len(prefixes) != 1:
        raise RuntimeError(f"expected one generated Python runtime prefix, got {len(prefixes)}")
    source = source.replace(prefixes.pop(), RUNTIME_MARKER)
    if "/Users/" in source:
        raise RuntimeError("unrecognized personal path in Python sysconfig payload")
    path.write_text(source + RUNTIME_SUFFIX)
    return 1


def sanitize_python_dylib() -> int:
    path = RESEARCH / "runtime/lib/libpython3.13.dylib"
    if not path.is_file():
        raise RuntimeError(f"missing Python runtime dylib: {path}")
    details = subprocess.run(["otool", "-D", str(path)], capture_output=True, text=True, check=True).stdout
    install_names = details.splitlines()[1:]  # first line is the queried file's own path
    if not any("/Users/" in name for name in install_names):
        return 0
    subprocess.run(["install_name_tool", "-id", "@rpath/libpython3.13.dylib", str(path)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(path)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 1


def sanitize_search() -> tuple[int, int]:
    metadata = list(SEARCH.glob("searxng-*.dist-info/direct_url.json"))
    for path in metadata:
        path.unlink()
    pexels = SEARCH / "searx/engines/pexels.py"
    if not pexels.is_file():
        raise RuntimeError(f"missing Pexels engine: {pexels}")
    source = pexels.read_text()
    changed = 0
    if 'api_key = ""' not in source:
        source, n = re.subn(r'^api_key = ["\'][^"\']+["\']$', 'api_key = ""', source, count=1, flags=re.M)
        if n != 1:
            raise RuntimeError("unexpected Pexels fallback key layout")
        changed = 1
    old = "            secret_key = api_key\n"
    replacement = ("            if not api_key:\n"
                   "                raise SearxEngineAPIException('no configured fallback API key') from e\n"
                   "            secret_key = api_key\n")
    if replacement not in source:
        if old not in source:
            raise RuntimeError("unexpected Pexels fallback branch")
        source = source.replace(old, replacement, 1)
        changed = 1
    if changed:
        pexels.write_text(source)
    return len(metadata), changed


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("macOS generated payload sanitizer only")
    scripts = sanitize_console_scripts()
    sysconfig = sanitize_sysconfig()
    dylib = sanitize_python_dylib()
    metadata, pexels = (0, 0) if "--without-search" in sys.argv[1:] else sanitize_search()
    print(f"generated payload sanitized: scripts={scripts}, sysconfig={sysconfig}, "
          f"dylib={dylib}, metadata={metadata}, pexels={pexels}")


if __name__ == "__main__":
    main()
