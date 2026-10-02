"""Exact synthetic-fixture triage; not a general credential scanner."""
from pathlib import Path
import hashlib
import json
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "qa/synthetic-secrets-manifest.json"

def identity(path, kind, value):
    return path, kind, hashlib.sha256(value.encode()).hexdigest()

def approved_keys(manifest):
    return {(e["path"], e["type"], e["sha256"])
            for e in manifest["entries"] if e["approved"]}

def main():
    m = json.loads(MANIFEST.read_text())
    approved = approved_keys(m)
    if "--self-test" in sys.argv:
        e = next(e for e in m["entries"] if e["approved"])
        key = (e["path"], e["type"], e["sha256"])
        assert key in approved
        assert (key[0] + ".changed", key[1], key[2]) not in approved
        assert (key[0], key[1] + ".changed", key[2]) not in approved
        assert (key[0], key[1], "0" * 64) not in approved
        assert identity(key[0], key[1], "TEST_ONLY_changed") not in approved
        print("PASS: path/type/value changes are not waived")
        return 0
    scanner = runpy.run_path(str(ROOT / "deploy/scan_secretos.py"))
    detections = []
    paths = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    for rel in paths:
        p = ROOT / rel
        if not rel or p.is_symlink() or not p.is_file():
            continue
        if any(d in scanner["SALTAR_DIRS"] for d in Path(rel).parts):
            continue
        if p.suffix.lower() not in scanner["EXTENSIONES"] | {".ts", ".tsx", ".cjs", ".rs", ".xml"}:
            continue
        text = p.read_text(errors="ignore")
        for kind, rx in scanner["PREFIJOS"].items():
            for hit in rx.finditer(text):
                if not scanner["_allowlisted"](hit.group()):
                    detections.append(identity(rel, kind, hit.group()))
        for hit in scanner["ASIGNACION"].finditer(text):
            if not scanner["INOCENTES"].search(hit.group()) and scanner["entropia"](hit.group(2)) >= 3.6:
                detections.append(identity(rel, "entropy:" + hit.group(1), hit.group(2)))
    unknown = [k for k in detections if k not in approved]
    print(f"matches={len(detections)} approved={len(detections)-len(unknown)} review={len(unknown)}")
    for path, kind, digest in unknown:
        print(f"REVIEW {path} [{kind}] sha256={digest}")
    return 1 if unknown else 0

if __name__ == "__main__":
    raise SystemExit(main())
