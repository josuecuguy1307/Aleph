"""Resolve pinned Alpine main/aarch64 Python dependency closure for offline guest boot."""
from __future__ import annotations

import re
import sys
import tarfile
import urllib.request
from pathlib import Path

entries = {}
providers = {}
for index_name, repository in (("APKINDEX.tar.gz", "main"),
                               ("APKINDEX-community.tar.gz", "community")):
    index_path = Path(__file__).with_name(index_name)
    with tarfile.open(index_path) as archive:
        records = archive.extractfile("APKINDEX").read().decode().split("\n\n")
    for record in records:
        fields = dict(line.split(":", 1) for line in record.splitlines() if ":" in line)
        if "P" not in fields:
            continue
        fields["repository"] = repository
        entries[fields["P"]] = fields
        for token in fields.get("p", "").split():
            providers.setdefault(token.split("=", 1)[0], fields["P"])

installed = set()
installed_file = Path(__file__).with_name("root") / "lib/apk/db/installed"
for record in installed_file.read_text().split("\n\n"):
    fields = dict(line.split(":", 1) for line in record.splitlines() if ":" in line)
    if "P" in fields:
        installed.add(fields["P"])
    for token in fields.get("p", "").split():
        installed.add(token.split("=", 1)[0])

selected = {}
def resolve(token: str):
    name = re.split(r"[<>=~]", token, 1)[0]
    if name.startswith("!") or name in installed:
        return
    package = name if name in entries else providers.get(name)
    if not package:
        raise RuntimeError(f"no package for dependency {token}")
    if package in installed or package in selected:
        return
    fields = entries[package]
    selected[package] = fields
    for dep in fields.get("D", "").split():
        resolve(dep)

for package in (a for a in sys.argv[1:] if not a.startswith("--")) or ("python3",):
    resolve(package)
total = sum(int(f["S"]) for f in selected.values())
print(f"packages={len(selected)} download_bytes={total}")
for name, fields in sorted(selected.items()):
    print(f"{name}-{fields['V']}.apk {fields['S']}")

if "--download" in sys.argv:
    dest = Path(__file__).with_name("packages")
    for name, fields in sorted(selected.items()):
        filename = f"{name}-{fields['V']}.apk"
        path = dest / filename
        url = f"https://dl-cdn.alpinelinux.org/alpine/v3.24/{fields['repository']}/aarch64/{filename}"
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read(int(fields["S"]) + 1)
        if len(content) != int(fields["S"]):
            raise RuntimeError(f"package size mismatch: {filename}")
        path.write_bytes(content)
