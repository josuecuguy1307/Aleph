# Security — doc.haus

doc.haus is a **self-hosted, local-first** legal-document agent. Its security posture is
a deliberate privacy choice: there is **no built-in multi-tenant auth by design**, and
your data never leaves infrastructure you control. Run it on trusted infra; if you expose
it beyond localhost, front it with your own reverse proxy / SSO. This is a posture, not a
gap — the alternative (a shared, internet-facing service) is exactly what doc.haus avoids
so sensitive legal content stays on your own machine.

<posture>
- **Loopback by default.** Both the engine and the ingest service bind `127.0.0.1`.
  Override the ingest bind with `INGEST_HOST` / `INGEST_PORT` only when you have placed it
  behind a reverse proxy.
- **CORS is an allowlist, not a wildcard.** The ingest service accepts browser origins
  only from `localhost` / `127.0.0.1` on any port, mirroring the engine's CORS rules.
- **Matter ids are validated** against their generated `[a-z0-9-]` shape before they
  touch the filesystem, so a request id cannot traverse out of `WORKSPACE_ROOT`.
- **Engine auth.** OpenCode's `OPENCODE_SERVER_PASSWORD` enables HTTP Basic Auth on the
  engine; set it whenever the engine is reachable beyond localhost.
</posture>

<data-handling>
Document content and embeddings stay in a **per-matter local SQLite database**
(`<matter>/.dochaus/legal.db`) under `WORKSPACE_ROOT`. Nothing is sent to a central
service. The only outbound data flow is model inference, which goes solely to the model
provider the operator configures in `dochaus/opencode.json` and is governed by that
provider's policies.
</data-handling>

<reporting>
Report suspected vulnerabilities in doc.haus **privately**, via
[GitHub Security Advisories on the doc.haus repository](https://github.com/sure-scale/doc-haus/security/advisories/new),
rather than opening a public issue.
We will acknowledge your report and keep you informed of progress toward a fix. Issues that
concern upstream OpenCode itself should follow the upstream disclosure process documented
below.
</reporting>

---

## Upstream (OpenCode) guide

> The section below is inherited from upstream OpenCode and describes OpenCode's own threat
> model and disclosure process. It applies when working inside upstream packages
> (`packages/*`). For doc.haus-specific posture and reporting, see the section above.

# Security

## IMPORTANT

We do not accept AI generated security reports. We receive a large number of
these and we absolutely do not have the resources to review them all. If you
submit one that will be an automatic ban from the project.

## Threat Model

### Overview

OpenCode is an AI-powered coding assistant that runs locally on your machine. It provides an agent system with access to powerful tools including shell execution, file operations, and web access.

### No Sandbox

OpenCode does **not** sandbox the agent. The permission system exists as a UX feature to help users stay aware of what actions the agent is taking - it prompts for confirmation before executing commands, writing files, etc. However, it is not designed to provide security isolation.

If you need true isolation, run OpenCode inside a Docker container or VM.

### Server Mode

Server mode is opt-in only. When enabled, set `OPENCODE_SERVER_PASSWORD` to require HTTP Basic Auth. Without this, the server runs unauthenticated (with a warning). It is the end user's responsibility to secure the server - any functionality it provides is not a vulnerability.

### Out of Scope

| Category                        | Rationale                                                               |
| ------------------------------- | ----------------------------------------------------------------------- |
| **Server access when opted-in** | If you enable server mode, API access is expected behavior              |
| **Sandbox escapes**             | The permission system is not a sandbox (see above)                      |
| **LLM provider data handling**  | Data sent to your configured LLM provider is governed by their policies |
| **MCP server behavior**         | External MCP servers you configure are outside our trust boundary       |
| **Malicious config files**      | Users control their own config; modifying it is not an attack vector    |

---

# Reporting Security Issues

We appreciate your efforts to responsibly disclose your findings, and will make every effort to acknowledge your contributions.

To report a security issue, please use the GitHub Security Advisory ["Report a Vulnerability"](https://github.com/anomalyco/opencode/security/advisories/new) tab.

The team will send a response indicating the next steps in handling your report. After the initial reply to your report, the security team will keep you informed of the progress towards a fix and full announcement, and may ask for additional information or guidance.

## Escalation

If you do not receive an acknowledgement of your report within 6 business days, you may send an email to security@anoma.ly
