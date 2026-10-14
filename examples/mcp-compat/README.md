# MCP transport reference checks

These fixtures test ALEPH's existing `inspection.transporte` selector with the
repository's exact MCP SDK pin. They are deterministic, credential-free reference
checks, not certification of packaged ALEPH or arbitrary MCP servers.

From the repository root:

```sh
python3 -m venv .venv-mcp-example
.venv-mcp-example/bin/python -m pip install mcp==2.0.0
.venv-mcp-example/bin/python examples/mcp-compat/run.py --output /tmp/aleph-mcp-reference.json
```

Choose a new output file for each run. The runner requires SDK mode; legacy
fallback cannot pass. It starts a stdio child and a loopback stateless Streamable
HTTP fixture on an ephemeral port. Both perform initialization, tool discovery,
a public-text echo, and a simulated tool error. HTTP additionally measures a
request timeout. It then closes both clients and the HTTP listener, and checks
stdio EOF. The output records SDK/source versions and negotiated protocols.

The HTTP fixture uses JSON responses and no session ID. SSE, OAuth, resources,
prompts, real server integrations and desktop configuration are outside its
coverage. The simulated tool error does not prove ALEPH's authorization gates.
The child fixture spawns no descendants; its successful closure does not prove
arbitrary process-tree cleanup.

The existing `platform/inspection/verify_transporte_sdk.py` provides broader
stdio/environment/process-tree tests and must be run separately in a source
checkout with `platform` on `PYTHONPATH`. It documents that a cooperative parent
can leave a descendant behind. The reference runner preserves that limitation;
it does not change the process owner, transport selector or product security.

## Optional Context7 documentation lookup

An independent real-server probe uses the same source SDK client. It contacts
`https://mcp.context7.com/mcp`, discovers tools, resolves Ollama's library and
queries public tool-calling documentation. It sends only the fixed public queries
in the script, without credentials or user files. This is an online workflow and
runs only when explicitly invoked:

```sh
.venv-mcp-example/bin/python examples/mcp-compat/context7.py --output /tmp/aleph-context7.json
```

The output records server/protocol versions, library resolution and a length/hash
of returned documentation rather than republishing it. Context7 recommends an API
key for higher rate limits; an unauthenticated run may fail because of quota or
future server policy. That is a failed probe, not proof of broken ALEPH support.
See [Context7's official configuration guide](https://github.com/upstash/context7#installation).
This checks the source HTTP client, not ALEPH's UI, BYO registry persistence,
agent dispatch or the packaged app. It does not validate GitHub or Playwright MCP.
