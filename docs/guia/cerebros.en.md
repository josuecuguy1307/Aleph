# Models — the cognition {#cerebros}

The model is what reasons for your agent. Cognition is **rented** and
changes every month; what matters —and what's yours— is the environment: your
data, your tools, your rules. Even your own key, if you want.

## Where the model comes from {#origen}

- **Included lane (Aleph-hosted):** available without setup. The included lane
  doesn't always expose a health signal in the runtime; it is **confirmed at run
  time**.
- **Your own API (BYOK):** this model uses your own access. You paste your key and
  it's ready — we don't ask for it before you choose. The key is stored encrypted.
- **Your CLI by subscription:** a model you already pay for (a frontier CLI, for
  example) applies its own effort and the run records it.

## The workers' economical model {#economico}

Workers can run on a **different model** from the main one. The idea: **reading
and extracting** goes to an economical model; **deciding** stays with the main
model. It's your choice and optional — if you don't pick one, workers **inherit
the main model**.

## The truth about the model comes from execution {#verdad-del-modelo}

The **active model is confirmed at run time**. If it degrades to a fallback
model, the Workroom shows it instead of hiding it. A model is never marked
"green" because "the binary exists": the signal comes from the real run. In a
sub-agent, the model is **confirmed at run time** too (the delegation records the
real model, with a per-child gate and propagated deadline).

## Frontier-only for demanding tasks {#frontier-only}

Some tasks require a **capable model**: Inspection (building and validating
pieces) and the **Guide** itself. There the selector requires a verified frontier
model —opus-4.8 family, your own API, or your CLI by subscription— and blocks
small models with an honest explanation, rather than letting them fail halfway.
Green here means: real tools + a verified frontier model. If your subscription
window runs out mid-run, you are told.

## The Guide and its model {#guia-cerebro}

The Guide needs a frontier model because it acts as a hands-on copilot. Its
powers: **KNOWS** (reads these documents as context), **SHOWS** (takes you: opens
closets, points at pieces, navigates surfaces), and **DOES** (control of the
Room), always asking "shall I do it, or you?". The line it **never crosses**: it
proposes and opens, never completes an action that reaches the world — that goes
through you in the Workroom. (See `cuarto.en.md`.)
