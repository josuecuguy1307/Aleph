# Security Policy

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Please report security issues privately via GitHub Security Advisories:

1. Go to https://github.com/OpenCoworkAI/open-codesign/security/advisories/new
2. Fill in the form with reproduction steps and impact assessment
3. We will acknowledge within 72 hours and provide an initial response within 7 days

For urgent or sensitive matters, you may also email **security@opencowork.ai** (PGP key TBD).

## Supported Versions

This project is in pre-alpha. Only the latest commit on `main` is supported. Once 1.0 is released, we will support the latest minor version.

## Disclosure Policy

We follow coordinated disclosure: we will work with you on a fix before public disclosure, and credit you in the advisory unless you prefer to remain anonymous.

## What we consider in scope

- Code execution, sandbox escape, or privilege escalation in the Electron app
- API key exfiltration or unsafe credential storage
- Vulnerabilities in our build/release pipeline
- Issues in dependencies that affect us materially

## Out of scope

- Vulnerabilities in third-party LLM APIs (report to those vendors)
- Issues that require physical access to the user's unlocked machine
- Social engineering attacks against users
