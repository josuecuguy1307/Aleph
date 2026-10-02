#!/usr/bin/env python3
"""Ejecuta una vara bajo un flock exclusivo (macOS no trae el binario `flock`)."""
from __future__ import annotations

import fcntl
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("uso: with_flock.py LOCK COMANDO [ARG...]", file=sys.stderr)
        return 2
    lock_path = Path(sys.argv[1])
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return subprocess.run(sys.argv[2:], check=False).returncode
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    raise SystemExit(main())
