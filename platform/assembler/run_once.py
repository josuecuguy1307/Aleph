#!/usr/bin/env python3
"""
run_once.py — One-shot programmatic wrapper around the Puppet AI assembler.

ADDITIVE: this file does NOT modify assembler.py. It imports the assembler's
building blocks (MCPServer, ToolRegistry, framing/RAG loaders, the chat client,
the API-key resolver) and re-runs the same tool-use loop, but:

  • takes a config dict (not a file path) + a single user message,
  • returns a STRUCTURED transcript (final answer + a turn-by-turn record of the
    tool calls, with arguments and results summarized for a UI),
  • enforces a hard wall-clock deadline (generous timeout, default 180s),
  • boots only the MCP servers the config's tool_filters actually need (faster,
    avoids gated servers spawning when not used),
  • never logs, returns, or echoes API keys.

Used by the backend endpoint POST /agents/{id}/try. The transcript is the REAL
output of the REAL agent — nothing is faked or canned.

Public API:
    run_once(config: dict, message: str, *, repo_root, deadline_s=180.0) -> dict
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

# ── Import the assembler module by file path (no package assumptions) ─────────
_THIS_DIR = Path(__file__).resolve().parent
_ASSEMBLER_PATH = _THIS_DIR / "assembler.py"


def _load_assembler():
    spec = importlib.util.spec_from_file_location("puppet_assembler", _ASSEMBLER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar el assembler en {_ASSEMBLER_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_asm = _load_assembler()

_transporte_mod = None


def _servidor_stdio():
    """La clase con la que este runner spawnea sus servers — la elige
    `inspection/transporte.py`, igual que el producto. Si el selector no carga, cae al
    cliente de siempre."""
    global _transporte_mod
    if _transporte_mod is None:
        try:
            ruta = _ASSEMBLER_PATH.parent.parent / "inspection" / "transporte.py"
            spec = importlib.util.spec_from_file_location("puppet_transporte_run_once", ruta)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _transporte_mod = mod
        except Exception:                                   # noqa: BLE001
            _transporte_mod = False
    if not _transporte_mod:
        return _asm.MCPServer
    try:
        return _transporte_mod.servidor_stdio()
    except Exception:                                       # noqa: BLE001
        return _asm.MCPServer


# ── Transcript-recording tool registry ────────────────────────────────────────

class _RecordingRegistry(_asm.ToolRegistry):
    """ToolRegistry that records each tool call for the transcript."""

    def __init__(self, servers, tool_filters):
        super().__init__(servers, tool_filters)
        self.calls: list[dict] = []

    def call(self, tool_name: str, arguments: dict) -> str:
        result = super().call(tool_name, arguments)
        self.calls.append({
            "tool": tool_name,
            "args": _summarize(arguments, limit=400),
            "result": _summarize(result, limit=1200),
        })
        return result


def _summarize(value: Any, limit: int = 1200) -> str:
    """Render a value as a compact string, truncated for the UI."""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    text = text.strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


# ── One-shot tool-use loop (mirrors assembler.run_agent, but records turns) ───

def _run_loop(
    message: str,
    cfg: dict,
    registry: _RecordingRegistry,
    api_key: str,
    deadline: float,
) -> dict:
    """Run the tool-use loop until a final answer, max_turns, or the deadline."""
    framing = _asm._load_framing(
        cfg.get("framing_path"),
        cfg.get("framing_fallback", "Eres un asistente útil."),
    )
    rag_ctx = _asm._load_rag(cfg.get("rag_dir"))
    system_content = framing + rag_ctx

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": message},
    ]

    tools = registry.schema()
    base_url = cfg["base_url"]
    model = cfg["model"]
    max_turns = int(cfg.get("max_turns", 8))
    max_tokens = int(cfg.get("max_tokens", 2048))
    temperature = float(cfg.get("temperature", 0))

    final_answer: Optional[str] = None
    truncated = False

    for turn in range(1, max_turns + 1):
        if time.monotonic() > deadline:
            truncated = True
            break

        resp = _asm._chat(
            messages, tools, base_url, model, api_key, max_tokens, temperature
        )
        choice = resp["choices"][0]
        msg = choice["message"]
        finish = choice.get("finish_reason", "")
        messages.append(msg)

        if finish == "tool_calls" or (msg.get("tool_calls") and finish != "stop"):
            tool_calls = msg.get("tool_calls", [])
            if not tool_calls:
                final_answer = msg.get("content", "") or ""
                break
            for tc in tool_calls:
                tc_id = tc["id"]
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError, TypeError):
                    fn_args = {}
                result_text = registry.call(fn_name, fn_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_text,
                })
        else:
            final_answer = msg.get("content", "") or ""
            break
    else:
        truncated = True

    if final_answer is None:
        last = messages[-1]
        final_answer = (
            last.get("content", "")
            if last.get("role") == "assistant"
            else ""
        ) or "[el agente llegó al límite de pasos sin una respuesta final]"

    return {
        "answer": final_answer,
        "tool_calls": registry.calls,
        "turns_truncated": truncated,
    }


# ── Public entry point ────────────────────────────────────────────────────────

def run_once(
    config: dict,
    message: str,
    *,
    repo_root: Path,
    deadline_s: float = 180.0,
) -> dict:
    """
    Run the agent described by `config` against a single user `message`,
    one-shot, and return a structured transcript.

    Returns:
        {
          "ok": bool,
          "answer": str,                # the agent's final reply
          "tool_calls": [ {tool, args, result}, ... ],  # summarized for UI
          "model": str,                 # the model that ran (declared, no key)
          "tools_available": [str],     # tool names the agent could use
          "turns_truncated": bool,      # hit max_turns / deadline
          "error": str | None,          # human message if something failed
        }

    Never raises for normal failures — packs them into {"ok": False, "error": ...}.
    Never returns or logs API keys.
    """
    deadline = time.monotonic() + max(5.0, float(deadline_s))

    # Resolve belt path (absolute or relative to repo root).
    belt_path_raw = config.get("belt_path", "")
    belt_path = Path(belt_path_raw)
    if not belt_path.is_absolute():
        belt_path = repo_root / belt_path
    if not belt_path.exists():
        return _fail(config, f"No encontramos el equipo del agente ({belt_path_raw}).")

    try:
        mcp_cfg = json.loads(belt_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _fail(config, f"No se pudo leer el equipo del agente: {exc}")

    servers_raw: dict = mcp_cfg.get("mcpServers", {})
    tool_filters: dict = config.get("tool_filters", {}) or {}

    # Boot only the servers this agent actually uses. If tool_filters is empty,
    # boot all servers in the belt (the demo belt has a single, credential-free one).
    if tool_filters:
        wanted = set(tool_filters.keys())
        servers_raw = {k: v for k, v in servers_raw.items() if k in wanted}

    api_key = _asm._resolve_api_key(config)

    started: list = []
    skipped: list[str] = []
    for sname, scfg in servers_raw.items():
        # EL TRANSPORTE LO ELIGE `transporte` (sesión 3). Es un entrypoint de CLI, no
        # del producto, pero correr el runner con un transporte distinto al del
        # backend haría que reproducir un bug con él deje de reproducir el bug.
        srv = _servidor_stdio()(sname, scfg["command"], scfg.get("args", []))
        if srv.start():
            started.append(srv)
        else:
            skipped.append(sname)

    if not started:
        return _fail(
            config,
            "El agente no pudo encender sus herramientas. "
            + (f"No arrancaron: {', '.join(skipped)}." if skipped else ""),
        )

    try:
        registry = _RecordingRegistry(started, tool_filters)
        result = _run_loop(message, config, registry, api_key, deadline)
    except RuntimeError as exc:
        # _chat raises RuntimeError on HTTP errors from the model gateway.
        # Strip anything that could carry a key; keep a human-readable hint.
        return _fail(config, _humanize_model_error(str(exc)))
    except Exception as exc:  # noqa: BLE001 — last-resort guard for the endpoint
        return _fail(config, f"Algo no salió al ejecutar el agente: {exc}")
    finally:
        for srv in started:
            srv.stop()

    return {
        "ok": True,
        "answer": result["answer"],
        "tool_calls": result["tool_calls"],
        "model": config.get("model", "?"),
        "tools_available": registry.tool_names(),
        "turns_truncated": result["turns_truncated"],
        "servers_skipped": skipped,
        "error": None,
    }


def _fail(config: dict, message: str) -> dict:
    return {
        "ok": False,
        "answer": "",
        "tool_calls": [],
        "model": config.get("model", "?"),
        "tools_available": [],
        "turns_truncated": False,
        "servers_skipped": [],
        "error": message,
    }


def _humanize_model_error(raw: str) -> str:
    """Turn a raw gateway error into a user-safe message (no keys, no codes)."""
    low = raw.lower()
    if "timed out" in low or "timeout" in low:
        return "El modelo tardó demasiado en responder. Prueba de nuevo en un momento."
    if "connection refused" in low or "urlopen error" in low or "failed to establish" in low:
        return "No pudimos contactar al modelo. Verifica que el carril de modelo esté arriba."
    if "401" in raw or "403" in raw or "auth" in low:
        return "El carril de modelo rechazó la credencial. Avisa al equipo."
    if "429" in raw or "rate" in low:
        return "El modelo está saturado en este momento. Prueba de nuevo en unos segundos."
    return "El modelo devolvió un error. Prueba de nuevo en un momento."


# Expose tool_names on the base registry for the response (additive helper).
def _tool_names(self) -> list[str]:
    return [t["function"]["name"] for t in self._schema]


_asm.ToolRegistry.tool_names = _tool_names  # type: ignore[attr-defined]


# ── CLI for manual smoke (mirrors assembler's, but prints the JSON transcript) ─

def _main() -> None:
    if len(sys.argv) < 3:
        print('Uso: python run_once.py <config.json> "<mensaje>"', file=sys.stderr)
        sys.exit(1)
    cfg_path = Path(sys.argv[1])
    cfg = json.loads(cfg_path.read_text())
    repo_root = _THIS_DIR.parents[1]  # platform/assembler -> repo root
    out = run_once(cfg, sys.argv[2], repo_root=repo_root)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
