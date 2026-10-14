# Models, tools and MCP in Aleph

Aleph is a macOS workspace for using and composing agents with models, tools and
files. Start with [Getting Started](GETTING_STARTED.md) for installation and the
product workflow. This page maps integration capabilities to the public source
so contributors can inspect them before building an adapter or reporting a bug.

## Model access

API credentials, CLI authentication and connector authorization are separate.
Connecting a model does not authorize access to a service or a user's files.

| Path | Public source evidence | Prerequisites and scope |
| --- | --- | --- |
| API providers | [Model routing](../platform/assembler/models.py), [LiteLLM adapter](../platform/assembler/adaptador_litellm.py) and [model catalog](../catalog/modelos.json) | Bring provider credentials and a model available to your account. Catalog entries do not prove that every model was tested. |
| Installed coding CLIs | [CLI provider registry](../platform/assembler/cli_brain/registry.py) and [CLI bridge](../platform/assembler/cli_brain/server.py) | Install and authenticate the CLI separately. See the registry for provider paths; availability and execution limits remain provider dependent. |
| Local inference | The `oss-direct` alias in [models.py](../platform/assembler/models.py) targets an Ollama-compatible endpoint, defaulting to `http://127.0.0.1:11434/v1` | Supply a running local runtime and an installed, tool-capable model. This source route does not imply that Aleph bundles a model or that every workspace runs offline. |

The local route reads `PUPPET_OSS_DIRECT_BASE_URL` and
`PUPPET_OSS_DIRECT_MODEL`; the model default in the source is `qwen3:8b`.
These are developer/runtime settings, not a promise that launching the packaged
app from Finder inherits terminal environment variables. Inspect the recipe and
run's selected model before relying on local-only inference.

## MCP client capabilities

The source implements client connections to external MCP servers. Aleph does not
need to be advertised as an MCP server to use these integrations.

| Transport | Implementation | Connection information |
| --- | --- | --- |
| Local stdio | [Transport selector](../platform/inspection/transporte.py), [SDK bridge](../platform/inspection/transporte_sdk.py) | A server command, arguments and explicitly supplied environment values. Install the server's runtime separately. |
| Remote Streamable HTTP | The same [SDK bridge](../platform/inspection/transporte_sdk.py), used by [BYO-MCP](../platform/inspection/byo_mcp.py) | A public HTTP endpoint and any required headers. The BYO URL validator rejects internal addresses. |

The [backend BYO request](../product/backend/app/phase1/inspect_router.py) accepts
`transport`, `url`, `headers`, `command`, `args`, `env` and `allowed_tools`.
Its probe connects and discovers tools before producing a tool-belt configuration.
Equipping an existing agent requires an authenticated session and ownership of
that agent. A discovered tool is not automatically permission to use every tool
on the server.

The transport selector uses the SDK when available in its default `auto` mode;
it reports a legacy fallback when the SDK is unavailable. An explicit `sdk` mode
fails instead of silently falling back. This matters when reporting compatibility:
include the actual selected transport and dependency version.

These are source-backed capabilities, not a certification of every server,
authentication flow, MCP protocol feature or packaged-app configuration. In
particular, do not infer legacy HTTP+SSE support, full OAuth interoperability,
resources or prompts support solely from a successful tool discovery.

## Reporting an integration result

Include the Aleph release or commit, macOS version, server/runtime version,
transport, model/provider path and a small public-data reproduction. Record
whether initialization, tool discovery, a tool call, error handling and cleanup
each succeeded. Remove credentials and private document contents from reports.

Use [BUILDING.md](../BUILDING.md) for source prerequisites. The current macOS
release targets Apple silicon, and the source build has documented
reproducibility limitations. Onshape remains optional and not certified.
