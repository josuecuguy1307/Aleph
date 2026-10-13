# Local Ollama source workflow

This example runs ALEPH's real recipe assembler with `qwen3:8b`, the existing
credential-free calculator MCP server, and a tiny synthetic CSV. The runner saves
the model's answer to `report.md` alongside `evidence.json`. It does not exercise
the desktop UI, workspace persistence API or packaged application.

From the repository root, create a separate environment for this narrow source
profile (do not replace the full backend environment or its requirements):

```sh
python3 -m venv .venv-ollama-example
.venv-ollama-example/bin/python -m pip install mcp==2.0.0 jsonschema==4.26.0
```

Install/start [Ollama](https://ollama.com/download) separately, then install the
model if needed with `ollama pull qwen3:8b` (approximately 5.2 GB download).
Confirm `ollama list` contains that exact tag. Run:

```sh
.venv-ollama-example/bin/python examples/ollama-local/run.py --output /tmp/aleph-ollama-evidence
.venv-ollama-example/bin/python examples/ollama-local/test_run.py
```

Choose a fresh output directory for each run. The script records runtime version,
model digest, source commit, selected transport, actual model identity, tool
execution and the final answer. A pass requires an executed `mul(7,8)` returning
56, the measured model `qwen3:8b`, a completed answer and no fallback. A guessed
answer or a held tool is a failure. The runner uses the assembler's approval
callback to approve only multiplication on the fixed calculator fixture; every other
server or tool remains denied. The evidence validator separately checks the
actual arguments are 7 and 8.
It does not disable the product gate. The source commit identifies the checkout;
the example files must also be preserved when comparing results before a merge.

The profile deliberately selects ALEPH's supported `urllib` inference path
(`PUPPET_LITELLM=0`) and SDK MCP transport (`ALEPH_TRANSPORTE=sdk`). It is not a test
of LiteLLM. It disables the inference cascade and refuses non-loopback socket
connections in the runner process. The calculator is the existing stdlib child
process with no network tools; this audit hook is not a sandbox for arbitrary
third-party servers or a new product-wide local-only policy.

The HTTP timeout is 180 seconds and run deadline 300 seconds to allow cold starts.
If Ollama is absent, the model is missing, the SDK pin differs, or the tool/model
checks fail, the command fails visibly. Evidence from an unsuccessful assembler
run is retained; a preflight failure occurs before output creation. Model tags can
change: compare the recorded digest, not just the name. A successful small task
is not a benchmark or a claim that every ALEPH workflow runs offline.

Ollama's [tool-calling documentation](https://docs.ollama.com/capabilities/tool-calling)
explains the request/tool-result cycle. Its [model-list API](https://docs.ollama.com/api/tags)
provides the digest recorded here. Model downloads and installation happen before
the measured run. No credentials or private sample data are required.
