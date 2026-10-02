#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run default Gitleaks rules, then apply exact, content-bound reviewed matches.

No directory, prefix, detector or changed-file blanket exceptions are permitted.
Reports are temporary, outside the source tree, and never print detected values.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / 'tools/oss-reviewed-secret-matches.json'

def identity(path, finding, file_digest):
    return (path, finding['RuleID'], finding['StartLine'], finding['EndLine'],
            file_digest, hashlib.sha256(finding['Secret'].encode()).hexdigest())

def approved_identities(document):
    return {(e['path'], e['rule'], e['start_line'], e['end_line'],
             e['file_sha256'], e['value_sha256']) for e in document['entries']}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    document = json.loads(REVIEW.read_text())
    approved = approved_identities(document)
    if args.self_test:
        key = next(iter(approved))
        assert key in approved
        for index, change in ((0, key[0] + '.changed'), (1, 'unexpected-detector'),
                              (2, -1), (3, -1), (4, '0' * 64), (5, '0' * 64)):
            altered = list(key)
            altered[index] = change
            assert tuple(altered) not in approved
        print('PASS: changed path/rule/line/file bytes/value revokes review approval')
        return 0
    env = dict(os.environ)
    env.pop('GITLEAKS_CONFIG', None)
    env.pop('GITLEAKS_CONFIG_TOML', None)
    with tempfile.TemporaryDirectory(prefix='aleph-oss-secret-scan-') as temp:
        report = Path(temp) / 'findings.json'
        # Keep full values only inside this temporary report to compare hashes.
        # Scanner stdout/stderr are captured; nothing sensitive is echoed.
        result = subprocess.run(['gitleaks', 'dir', str(ROOT), '--no-banner',
                                 '--report-format', 'json', '--report-path', str(report)],
                                cwd=ROOT, env=env, capture_output=True, text=True)
        if result.returncode not in (0, 1) or not report.exists():
            raise SystemExit('Gitleaks execution failed; no scan PASS is recorded')
        findings = json.loads(report.read_text())
        unknown = []
        digests = {}
        for finding in findings:
            p = Path(finding['File'])
            if not p.is_absolute():
                p = ROOT / p
            rel = p.relative_to(ROOT).as_posix()
            if rel not in digests:
                digests[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
            if identity(rel, finding, digests[rel]) not in approved:
                unknown.append((rel, finding['RuleID'], finding['StartLine']))
        print(f'Gitleaks raw matches={len(findings)}; exact reviewed matches={len(findings)-len(unknown)}; unresolved={len(unknown)}')
        for rel, rule, line in unknown:
            print(f'REVIEW {rel}:{line} [{rule}]')
        return 1 if unknown else 0

if __name__ == '__main__':
    raise SystemExit(main())
