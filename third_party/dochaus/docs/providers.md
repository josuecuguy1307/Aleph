# Providers and confidentiality

doc.haus runs on the unmodified OpenCode engine, which resolves model providers
entirely from configuration. Swapping the provider is a config change, not a code
change: you edit a provider block (in `dochaus/opencode.json` or the engine's
global config) or use the web app's Settings panel. No part of the codebase pins a
provider or a model.

This document covers the three ways to point doc.haus at a model — the shipped
Google Vertex default, a bring-your-own cloud key (Anthropic, OpenAI), and a
fully local / on-prem endpoint (Ollama, LM Studio, vLLM) — and states plainly
what leaves your machine in each case.

## How provider resolution works

A provider block has the same shape everywhere doc.haus reads config:

```jsonc
"provider": {
  "<provider-id>": {
    "npm": "<ai-sdk-package>",      // which AI SDK adapter to load
    "name": "<display name>",
    "options": {                     // forwarded to the adapter
      "apiKey": "<key>",             // or set via auth, see below
      "baseURL": "<url>"             // for local / custom endpoints
    },
    "models": {
      "<model-id>": { "name": "<display name>" }
    }
  }
}
```

The engine reads `npm`, installs that package at runtime, and lowers `options`
into the adapter's credentials and settings. The package determines the wire
protocol. Built-in lowerers exist for the major adapters, so each of the
following works purely from config:

- `@ai-sdk/google-vertex` — Google Vertex AI (the shipped default)
- `@ai-sdk/anthropic` — Anthropic
- `@ai-sdk/openai` — OpenAI
- `@ai-sdk/openai-compatible` — any OpenAI-compatible server (Ollama, LM Studio,
  vLLM, and similar)

`options.apiKey` and `options.baseURL` are recognized for all of these. For
hosted providers you can keep keys out of the config file and store them in the
engine's auth store instead (see "BYO cloud key" below).

Two places hold provider config, and both use this shape:

- `dochaus/opencode.json` — the checked-in legal config layer, loaded via
  `OPENCODE_CONFIG_DIR`. This is where the Vertex default lives. Edit it to ship a
  different default to every user.
- The engine's global config — written by the web app's Settings panel
  (`/global/config`). Use this for per-machine choices: connecting a cloud key,
  adding a local endpoint, picking the default model. It does not touch the
  checked-in file.

The web Settings panel surfaces all three paths: "Connect a provider" stores a
cloud API key, "Local endpoint" registers an OpenAI-compatible server, and
"Default model" picks the `providerID/modelID` to use. After adding a provider its
models appear in the model picker; restart the engine if they do not show up
immediately.

## Default: Google Vertex via ADC

The shipped configuration in `dochaus/opencode.json`. It authenticates from the
host's Application Default Credentials — there is no API key in the config.

```jsonc
"google-vertex": {
  "npm": "@ai-sdk/google-vertex",
  "name": "Google Vertex AI",
  "options": {
    "project": "{env:GOOGLE_VERTEX_PROJECT}",
    "location": "{env:GOOGLE_VERTEX_LOCATION}"
  },
  "models": {
    "gemini-3.1-pro-preview": { "name": "Gemini 3.1 Pro" },
    "gemini-3.5-flash": { "name": "Gemini 3.5 Flash" }
  }
}
```

Setup:

```bash
gcloud auth application-default login
export GOOGLE_VERTEX_PROJECT=<your-gcp-project>
export GOOGLE_VERTEX_LOCATION=global   # Gemini 3.x is global-only
```

Project and location can also be set from the web Settings panel ("Cloud project
& region") instead of environment variables. Inference requests, including
document content placed in the prompt, are sent to Google Cloud.

## BYO cloud key: Anthropic and OpenAI

Both adapters take a key from `options.apiKey`. Add the provider block alongside —
or instead of — the Vertex block.

Anthropic:

```jsonc
"anthropic": {
  "npm": "@ai-sdk/anthropic",
  "name": "Anthropic",
  "options": { "apiKey": "{env:ANTHROPIC_API_KEY}" },
  "models": {
    "claude-sonnet-4-5": { "name": "Claude Sonnet 4.5" }
  }
}
```

OpenAI:

```jsonc
"openai": {
  "npm": "@ai-sdk/openai",
  "name": "OpenAI",
  "options": { "apiKey": "{env:OPENAI_API_KEY}" },
  "models": {
    "gpt-4o": { "name": "GPT-4o" }
  }
}
```

You do not have to put the key in a file. The cleaner path is the web Settings
panel: pick the provider under "Connect a provider" and paste the key. It is
written to the engine's auth store (`auth.json`, mode `0600`) rather than to
config, and the provider block needs no `apiKey`. Equivalently, set the
`{env:...}` variable in the engine's environment. Inference requests are sent to
Anthropic or OpenAI respectively.

## Fully local / on-prem: Ollama (and other OpenAI-compatible endpoints)

Local servers that expose an OpenAI-compatible API — Ollama, LM Studio, vLLM —
all use the `@ai-sdk/openai-compatible` adapter. The only required option is
`baseURL`, pointing at the server's `/v1` endpoint. Most local servers ignore the
API key; pass a placeholder if the adapter requires one.

Ollama (default endpoint `http://localhost:11434/v1`):

```jsonc
"ollama": {
  "npm": "@ai-sdk/openai-compatible",
  "name": "Ollama (local)",
  "options": { "baseURL": "http://localhost:11434/v1" },
  "models": {
    "llama3.2:latest": {
      "name": "Llama 3.2 (local)",
      "tool_call": true,
      "limit": { "context": 131072, "output": 8192 }
    }
  }
}
```

Setup:

```bash
ollama serve            # if not already running
ollama pull llama3.2    # pull a model that supports tool calls
```

LM Studio is identical except for the default port — set
`"baseURL": "http://localhost:1234/v1"` and use the model id LM Studio reports.
vLLM is the same pattern at whatever host and port you serve on
(`"baseURL": "http://<host>:8000/v1"`). For an on-prem deployment, the engine and
the model server run on your own infrastructure and the `baseURL` is an internal
address.

The web Settings panel's "Local endpoint" section writes exactly this block for
you: enter a name, the base URL, and a model id. The base URL must be reachable
from the machine running the engine, not from the browser.

When the model server runs on hardware you control, no document content leaves
your infrastructure at any point.

## What leaves your machine

- Embeddings are computed locally. doc.haus embeds documents with a local model
  (`Xenova/all-MiniLM-L6-v2`) in `services/ingest`. Document text is never sent to
  a cloud service for embedding, regardless of which inference provider you pick.
- Inference goes to whichever provider you configure. The prompt for a turn —
  which includes the document excerpts the agent retrieves and any text you type —
  is sent to that provider's endpoint. With Vertex, Anthropic, or OpenAI, that
  content goes to that cloud. Choose accordingly for privileged work.
- On-prem keeps everything local. With Ollama / LM Studio / vLLM on your own
  hardware, both embedding and inference stay inside your infrastructure. Nothing
  about a document leaves the machine or network you run it on.

## Validation status

- Validated end-to-end on this machine (2026-06-11): the Ollama config-only swap.
  A scratch config dir held only the `ollama` provider block above; the engine was
  pointed at it with `OPENCODE_CONFIG_DIR` and nothing else changed. `opencode
  models ollama` resolved `ollama/llama3.2:latest` from config alone, and `opencode
  run --model ollama/llama3.2:latest` routed the turn to the local endpoint at
  `http://localhost:11434/v1` and streamed model-generated tokens back. Inference
  stayed on the machine; no code was modified and the default Vertex config was not
  touched. (The 3B model's output quality is beside the point — the validated fact
  is that the engine served the turn from the local endpoint purely from config.)
- Validated structurally: the engine's provider lowerers natively support
  `@ai-sdk/openai-compatible`, `@ai-sdk/anthropic`, and `@ai-sdk/openai`, all
  recognizing `options.apiKey` and `options.baseURL` from config. The web Settings
  panel already writes the local-endpoint and cloud-key blocks shown here.
- Documented only (not exercised here): the Anthropic and OpenAI cloud blocks,
  which need a real API key to run. The config shape and credential handling are
  validated by the shared adapter path; only the live key is the remaining manual
  step.
