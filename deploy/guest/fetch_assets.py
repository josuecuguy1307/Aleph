#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Retrieve exact reviewed guest release assets, never bypassing clearance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent


def verify(path, asset):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or unsafe asset: {path.name}")
    if path.stat().st_size != asset['bytes']:
        raise ValueError(f"Wrong byte size: {path.name}")
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != asset['sha256']:
        raise ValueError(f"SHA-256 mismatch: {path.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--asset-dir', type=Path, default=HERE / 'runtime')
    parser.add_argument('--release-base-url')
    args = parser.parse_args()
    manifest = json.loads((HERE / 'assets.json').read_text())
    if args.verify_only:
        for asset in manifest['assets']:
            verify(args.asset_dir / asset['filename'], asset)
            print(f"PASS {asset['filename']} {asset['sha256']}")
        return 0
    if manifest['redistribution_status'] != 'cleared':
        parser.error('Guest release is NOT CLEARED for redistribution; see ASSETS.md')
    base = urllib.parse.urlsplit(args.release_base_url or '')
    if (base.scheme != 'https' or base.hostname != 'github.com'
            or base.username or base.password or base.query or base.fragment
            or '/releases/download/' not in base.path):
        parser.error('Supply an HTTPS immutable GitHub Release download directory')
    directory = args.asset_dir
    if directory.is_symlink():
        parser.error('Asset directory must not be a symlink')
    directory.mkdir(parents=True, exist_ok=True)
    for asset in manifest['assets']:
        name = asset['filename']
        if Path(name).name != name:
            raise ValueError('Unsafe asset filename in manifest')
        destination = directory / name
        if destination.exists() or destination.is_symlink():
            verify(destination, asset)
            print(f"PASS already present: {name}")
            continue
        with tempfile.TemporaryDirectory(prefix='.guest-download-', dir=directory) as temp:
            temporary = Path(temp) / name
            url = args.release_base_url.rstrip('/') + '/' + urllib.parse.quote(name)
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as output:
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > asset['bytes']:
                        raise ValueError(f"Oversized download: {name}")
                    output.write(block)
            verify(temporary, asset)
            # Same-filesystem hard link publishes the complete verified file
            # atomically and refuses to overwrite a concurrently placed input.
            os.link(temporary, destination)
            print(f"PASS retrieved: {name}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
