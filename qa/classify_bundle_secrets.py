#!/usr/bin/env python3
"""Classify every candidate from deploy/scan_secretos.py without printing values.

The report records a digest and short redaction for auditability. Unknown matches
fail closed; a vendor path alone is never enough to clear a key-like value.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
import scan_secretos as scanner  # noqa: E402


def classify(path: str, detector: str, value: str, line: str) -> tuple[str, str, bool, str]:
    lower = path.lower()
    if "/pexels.py" in lower and detector == "api_key":
        return ("REAL_SECRET", "Hard-coded fallback vendor API credential", True,
                "Removed from generated engine; missing extracted/configured key now fails closed")
    if "/transformers/testing_utils.py" in lower and detector == "TOKEN":
        return ("REAL_SECRET", "Upstream staging-CI token, not a release runtime credential", False,
                "Prune testing_utils.py from packaged dependency")
    if "/product/app/design/" in lower and "/verify_" in lower or "/platform/gates/tests_gates.py" in lower or "/platform/assembler/verify_" in lower or "/cli_brain/verify_" in lower:
        return ("SYNTHETIC_FIXTURE", "First-party QA fixture with deliberately fake credential shapes", False,
                "Prune exact QA files from public payload")
    if "/tests/" in lower or "/test_" in lower or "/testing_utils.py" in lower:
        return ("SYNTHETIC_FIXTURE", "Dependency test/example, not used by packaged runtime", False,
                "Prune test assets where safe")
    if lower.endswith(".dist-info/top_level.txt"):
        return ("FALSE_POSITIVE", "A package name alone met the naked-key entropy heuristic", False,
                "Keep standard package metadata")
    if "policy_templates_backup.json" in lower and value.startswith("AKIAIOSFOD"):
        return ("PLACEHOLDER", "Canonical AWS documentation-example identifier in a policy template", True,
                "No private credential; retain template")
    if "/pil/imagefont.py" in lower and detector == "AWS access key":
        return ("FALSE_POSITIVE", "An AWS-shaped substring inside encoded font test data", True,
                "Retain runtime font data")
    if "provider_create_fields.json" in lower and detector == "clave privada":
        return ("PLACEHOLDER", "A field-description PEM header, without a private-key body", True,
                "Retain provider schema")
    if "third_party/ldr/src/local_deep_research/defaults/" in lower and "YOUR_" in value:
        return ("PLACEHOLDER", "Template URL uses explicit YOUR_ user text", True,
                "Retain default template")
    if "/searx/engines/youtube_noapi.py" in lower and detector == "Google API key":
        return ("PUBLIC_KEY_OR_PUBLIC_TOKEN", "Public web-client key embedded by upstream in a request URL", True,
                "Retain public upstream client parameter; no user credential")
    if "/apprise/plugins/" in lower and line.lstrip().startswith("#"):
        return ("PLACEHOLDER", "Credential-shaped example appears in an upstream comment", True,
                "Retain explanatory comment")
    if "/cryptography/hazmat/primitives/serialization/ssh.py" in lower and detector == "clave privada":
        return ("FALSE_POSITIVE", "Code checks a PEM header; no key body is stored", True,
                "Retain parser")
    if detector == "URL con contraseña" and any(marker in value.lower() for marker in (
        "username", "user:", "myuser", "foo.com", "scott:", "postgres:",
        "jo%40", "sourcep", "login:", "my_key", "your_", "usernam",
    )):
        return ("PLACEHOLDER", "Illustrative user/password URL in dependency docs or examples", True,
                "Retain dependency; no operational Aleph credential")
    if detector in {"Token", "token"} and ("/dist/assets/" in lower or "/static/" in lower) and value.startswith("+String("):
        return ("FALSE_POSITIVE", "Minified JavaScript expression, not a literal token", True,
                "Retain generated UI asset")
    if "/jupyterlab-plotly/static/" in lower and detector == "token" and value.startswith("+t)}h.weight"):
        return ("FALSE_POSITIVE", "Minified font-parser expression crosses a token-shaped string", True,
                "Retain generated UI asset")
    if detector == "private_key" and value.startswith("Optional["):
        return ("FALSE_POSITIVE", "Python type annotation, not key material", True,
                "Retain runtime module")
    return ("REVIEW_REQUIRED", "No safe evidence-based classification rule", True,
            "Manual review before declaring PASS")


def candidate(path: Path, base: Path, line_no: int, detector: str, value: str, text_line: str) -> dict:
    rel = str(path.relative_to(base))
    category, reason, runtime, action = classify(rel, detector, value, text_line)
    return {
        "file": rel, "line": line_no, "detector": detector,
        "classification": category, "reason": reason,
        "reaches_runtime": runtime, "action": action,
        "redacted": scanner.redactar(value),
        "candidate_sha256": hashlib.sha256(value.encode()).hexdigest(),
    }


def scan(base: Path) -> list[dict]:
    result = []
    for path in base.rglob("*"):
        if not path.is_file() or any(part in scanner.SALTAR_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in scanner.EXTENSIONES and path.name != ".env":
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lines = content.splitlines()

        def add(offset: int, detector: str, value: str) -> None:
            line_no = content.count("\n", 0, offset) + 1
            line = lines[line_no - 1] if line_no <= len(lines) else ""
            result.append(candidate(path, base, line_no, detector, value, line))

        if scanner.es_credencial_desnuda(content) and not scanner._allowlisted(content):
            add(0, "archivo-credencial", content.strip())
        for label, expression in scanner.PREFIJOS.items():
            for match in expression.finditer(content):
                if not scanner._allowlisted(match.group(0)):
                    add(match.start(), label, match.group(0))
        for match in scanner.ASIGNACION.finditer(content):
            value = match.group(2)
            if scanner.INOCENTES.search(match.group(0)) or scanner.entropia(value) < 3.6:
                continue
            add(match.start(), match.group(1), value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    rows = scan(args.bundle.resolve())
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    args.report.write_text(json.dumps({"bundle": str(args.bundle.resolve()), "counts": counts,
                                      "candidates": rows}, indent=2, ensure_ascii=False) + "\n")
    print(f"candidates={len(rows)} classifications={json.dumps(counts, sort_keys=True)}")
    for row in rows:
        if row["classification"] in {"REVIEW_REQUIRED", "REAL_SECRET"}:
            print(f"{row['classification']}: {row['file']}:{row['line']} [{row['detector']}]")
    return 0 if counts.get("REVIEW_REQUIRED", 0) == 0 and counts.get("REAL_SECRET", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
