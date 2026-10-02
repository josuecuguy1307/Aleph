"""
isolated_runner.py — T10's in-process, isolated e2e runner.

Runs ONE agent task end-to-end through the REAL assembler (platform/assembler/
recipe_assembler.assemble_and_run) with a model override, WITHOUT touching Postgres,
:8080, or any prod puppet. This is the "copia la receta read-only, override solo el
modelo, corre en-proceso" pattern of the 2026-06-19 coupling eval, reconstructed and
committed (the /tmp original was lost).

Verify-from-environment: the returned record is the REAL run evidence (tool_calls with
real results, model_route, gate_decisions, answer). Nothing is fabricated; a run that
cannot execute returns ok=False with the real error.

It exercises the live environment (installed belts/MCP servers, ollama, the gateway),
so ALEPH_REPO must point at the tree where those services live (the main checkout),
defaulting to the root derived from this file. The harness CODE lives in this tree;
the ENVIRONMENT it drives is the running one.
"""
from __future__ import annotations

import copy
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

ALEPH_REPO = Path(os.environ.get("ALEPH_REPO") or Path(__file__).resolve().parents[1]).resolve()

# import the REAL assembler from the running tree
for p in (ALEPH_REPO / "product" / "backend", ALEPH_REPO / "platform" / "assembler"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

import recipe_assembler as _asm  # noqa: E402

# Local OSS endpoint (ollama). The assembler also has an OSS-DIRECT safety net to this
# same endpoint, so even a gateway/cloud model that fails falls back here.
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
OLLAMA_MODEL = os.environ.get("PUPPET_OSS_DIRECT_MODEL", "qwen3:8b")


def model_override(name: str) -> dict:
    """Map a logical model name to a concrete {base_url, primary, fallback} override.

    Honest about what the environment actually serves:
      - 'ollama' / 'qwen3:8b'        -> local OSS direct (always available if ollama up)
      - 'gpt-4o-mini' / 'deepseek'   -> OpenRouter (subject to credits/free-tier limits)
      - 'groq:<m>'                   -> Groq (subject to TPM limits on free tier)
    The CALLER decides whether the endpoint is reachable (see preflight); this only
    builds the recipe.model patch.
    """
    n = name.lower()
    if n in ("claude-code", "shim", "claude-code-opus", "opus-shim", "claude-code-opus-4.8"):
        # OPCIÓN C: cerebro = claude -p (Opus) detrás del shim local OpenAI-compat (pura
        # cognición, tools de Claude Code OFF). EVAL-LOCAL: NO toca models.py congelado.
        # key dummy (el shim no la usa). model_final = primary → ruta Claude-Code-Opus visible.
        shim = os.environ.get("SHIM_BASE_URL", "http://127.0.0.1:8923/v1")
        return {"base_url": shim, "primary": "claude-code-opus-4.8", "fallback": None,
                "api_key": "shim-dummy-key"}
    if n in ("opus", "brain", "claude-opus-4.8", "claude-opus-4-8", "opus-4.8"):
        # CEREBRO premium e2e: Opus 4.8 vía OpenRouter (espejo de models.py alias 'brain').
        # Verificado live: responde OPUS_OK. fallback=None → si Opus falla, cae al OSS-direct
        # ollama (safety net del assembler), NO a otro cloud, para no enmascarar el resultado.
        return {"base_url": "https://openrouter.ai/api/v1",
                "primary": "anthropic/claude-opus-4.8", "fallback": None}
    if n in ("ollama", "qwen3:8b", "qwen", "specialist", "oss", "prod-cheap"):
        return {"base_url": OLLAMA_BASE_URL, "primary": OLLAMA_MODEL, "fallback": None}
    if n in ("gpt-4o-mini", "gpt4omini"):
        return {"base_url": "https://openrouter.ai/api/v1",
                "primary": "openai/gpt-4o-mini", "fallback": None}
    if n in ("deepseek",):
        return {"base_url": "https://openrouter.ai/api/v1",
                "primary": "deepseek/deepseek-chat", "fallback": None}
    if n.startswith("groq:"):
        return {"base_url": "https://api.groq.com/openai/v1",
                "primary": n.split(":", 1)[1], "fallback": None}
    # default: leave to the recipe + OSS-direct safety net
    return {}


def _normalize_tool_calls(record: dict) -> list[dict]:
    out = []
    for tc in record.get("tool_calls", []) or []:
        result = tc.get("result")
        ga = tc.get("gate_action")
        executed = ga == "execute" and isinstance(result, str) and not result.startswith("[gate:")
        out.append({
            "tool": tc.get("tool"),
            "args": tc.get("args"),
            "result": result,
            "gate_action": ga,
            "executed": executed,
            "is_error": bool(tc.get("error")) or (isinstance(result, str) and result.lower().startswith(("error", "[error"))),
        })
    return out


def run(
    recipe: dict,
    prompt: str,
    *,
    model: Optional[str] = None,
    deadline_s: float = 150.0,
    byok_resolver: Optional[Callable[[str], str]] = None,
    auto_approve: bool = True,
) -> dict:
    """Run one task. Returns a normalized, JSON-serializable result with the real
    evidence. Never raises for a model/tool failure — captures it as ok=False + error."""
    rec_in = copy.deepcopy(recipe)
    if model:
        patch = model_override(model)
        if patch:
            rec_in.setdefault("model", {})
            rec_in["model"].update(patch)

    # auto-approve all tools so the tool EXECUTES and grounding can be measured. The gate
    # ENFORCEMENT itself (money/send held->approved) is a separate track (T6/Security);
    # here we measure model<->tool coupling, which requires the tool to run.
    approve = (lambda server, tool, payload: True) if auto_approve else None
    resolver = byok_resolver or (lambda ref: "")

    t0 = time.monotonic()
    err = None
    record: dict[str, Any] = {}
    try:
        record = _asm.assemble_and_run(
            rec_in, prompt,
            repo_root=ALEPH_REPO,
            byok_resolver=resolver,
            deadline_s=deadline_s,
            approve=approve,
        )
    except Exception as e:  # a crash IS a real, honest failure of the cell
        err = f"{type(e).__name__}: {e}"
    dt = time.monotonic() - t0

    if err is not None:
        return {
            "ok": False, "model_requested": model, "model_final": None,
            "tools_cabled": [], "tool_calls": [], "gate_enforced": False,
            "answer": "", "error": err, "latency_s": round(dt, 1), "usage": {},
        }

    usage = record.get("usage") or {}
    return {
        "ok": bool(record.get("ok")),
        "model_requested": model,
        "model_final": record.get("model_final"),
        "tools_cabled": record.get("tools_cabled", []),
        "tools_dropped": record.get("tools_dropped", []),
        "tool_calls": _normalize_tool_calls(record),
        "gate_enforced": bool(record.get("gate_enforced")),
        "answer": record.get("answer", "") or "",
        "error": record.get("error"),
        "latency_s": round(dt, 1),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "calls_measured": usage.get("calls", 0),
        },
        "turns": record.get("turns"),
    }


if __name__ == "__main__":
    # tiny self-check against the keyless calc fixture
    r = run(
        {
            "schema_version": "v1",
            "meta": {"name": "selfcheck", "nicho": "demo"},
            "model": {"primary": OLLAMA_MODEL, "base_url": OLLAMA_BASE_URL,
                      "temperature": 0, "max_tokens": 512, "max_turns": 4, "fallback": None},
            "belt": {"belt_ref": "platform/assembler/fixtures/belt-calc.mcp.json",
                     "tool_filters": {"calc": ["add", "sub", "mul"]}},
            "framing": {"ref": None, "inline": "Usá la tool calc para todo cálculo."},
            "rag": {"enabled": False, "mode": "manual", "dir": None},
            "keys": {}, "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
        },
        "Cuánto es 4321 * 8765? Usá la tool.",
        model="ollama",
    )
    import json
    print(json.dumps(r, ensure_ascii=False, indent=2)[:1200])
