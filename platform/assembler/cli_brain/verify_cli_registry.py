#!/usr/bin/env python3
"""verify_cli_registry.py — E1: UNA fuente, los consumidores derivan, la mutación se ve.

No toca Claude/Codex en runtime. Prueba:
  1. detect.PROVIDERS, aliases, /models ids, enum, techo Codex=3 salen del registro
  2. sacar un spec del registro achica provider_ids() y response_model_ids()
  3. las tuplas literales no viven en consumidores de producto (salvo fallbacks rotulados)
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ASM = os.path.dirname(_HERE)
if _ASM not in sys.path:
    sys.path.insert(0, _ASM)

from cli_brain import detect, registry, slots  # noqa: E402
import models as M  # noqa: E402

_fail = 0


def ok(cond, msg, extra=""):
    global _fail
    if cond:
        print("  OK  ", msg)
    else:
        _fail += 1
        print("  FAIL", msg, extra)


def seccion(t):
    print("\n══", t, "══")


def main():
    seccion("1 · el registro es la fuente; los históricos y Grok salen de SPECS")
    ids = registry.provider_ids()
    mids = registry.response_model_ids()
    ok("claude_cli" in ids and "codex_cli" in ids, "históricos presentes", ids)
    ok("grok_cli" in ids and "grok-cli" in mids, "Grok entra por el registro", ids)
    ok(set(detect.PROVIDERS.keys()) == set(ids), "detect.PROVIDERS deriva del registro",
       list(detect.PROVIDERS))
    ok(all(p in M.CLI_BRAIN_PROVIDERS for p in ids),
       "models.CLI_BRAIN_PROVIDERS vive del registro")
    ok(M.ALIASES["claude_cli"]["model"] == "claude-code-cli", "ALIAS claude")
    ok(M.ALIASES["codex_cli"]["model"] == "codex-cli", "ALIAS codex")
    ok(M.ALIASES["grok_cli"]["model"] == "grok-cli", "ALIAS grok")
    ok("claude-code-cli" in M.PRICES and "codex-cli" in M.PRICES and "grok-cli" in M.PRICES,
       "PRICES de CLI")
    ok(slots.techo_de("claude_cli") == 1, "techo Claude = 1")
    ok(slots.techo_de("codex_cli") == 3, "techo Codex = 3 (histórico)")
    ok(slots.techo_de("grok_cli") == 1, "techo Grok = 1 (default)")
    mv = registry.min_versions()
    ok(mv.get("claude_cli") == "2.0.0" and mv.get("codex_cli") == "0.100.0", "min_versions históricos")
    ok(mv.get("grok_cli") == "1.0.5", "min_version Grok")
    ok(registry.spec_by_id("grok_cli").binary == "grok", "binary grok")
    ok(detect.PROVIDERS["grok_cli"]._bin_name() == "grok", "provider._bin_name == spec.binary")
    cat = registry.public_catalog()
    ok(len(cat) == len(ids) and cat[0]["provider_id"] == "claude_cli", "catalog HTTP")
    ok(any(c["provider_id"] == "grok_cli" for c in cat), "catalog incluye Grok")

    seccion("2 · mutación: sacar un spec se ve en los helpers")
    saved = list(registry.SPECS)
    try:
        registry.SPECS[:] = [s for s in saved if s.provider_id != "codex_cli"]
        ok("codex_cli" not in registry.provider_ids(), "tras sacar Codex, ids sin Codex",
           registry.provider_ids())
        ok("codex-cli" not in registry.response_model_ids(), "response_model_ids sin codex-cli")
        ok("codex_cli" not in M.CLI_BRAIN_PROVIDERS, "CLI_BRAIN_PROVIDERS vivo sin Codex")
        ok(not any(c["provider_id"] == "codex_cli" for c in registry.public_catalog()),
           "catalog HTTP sin Codex")
        ok("codex_cli" not in registry.names() and "codex_cli" not in registry.aliases("http://x"),
           "names/aliases sin Codex")
        ok("codex_cli" not in registry.min_versions() and "codex_cli" not in registry.hands(),
           "min_versions/hands sin Codex")
        ok("cli.codex_cli" not in registry.slugs(), "slugs sin Codex")
        registry.SPECS[:] = [s for s in saved if s.provider_id != "grok_cli"]
        ok("grok_cli" not in registry.provider_ids() and "grok-cli" not in registry.response_model_ids(),
           "tras sacar Grok, el registro no lo declara")
        ok("grok_cli" not in M.CLI_BRAIN_PROVIDERS, "CLI_BRAIN_PROVIDERS vivo sin Grok")
        ok(not any(c["provider_id"] == "grok_cli" for c in registry.public_catalog()),
           "catalog HTTP sin Grok")
    finally:
        registry.SPECS[:] = saved
    ok("grok_cli" in registry.provider_ids() and "codex_cli" in registry.provider_ids(),
       "registro restaurado")

    seccion("3 · no quedan tuplas funcionales en consumidores")
    repo = os.path.dirname(_ASM)  # platform/
    repo = os.path.dirname(repo)  # root
    banned = (
        '("claude_cli", "codex_cli")',
        "('claude_cli', 'codex_cli')",
        '{"claude_cli", "codex_cli"}',
        "{'claude_cli', 'codex_cli'}",
        'k in {"claude_cli", "codex_cli"}',
        'k in {\'claude_cli\', \'codex_cli\'}',
        '["claude_cli", "codex_cli"]',
        "['claude_cli', 'codex_cli']",
        'if ref in ("claude_cli", "codex_cli")',
    )
    scan = [
        os.path.join(repo, "platform", "assembler", "models.py"),
        os.path.join(repo, "platform", "assembler", "recipe_assembler.py"),
        os.path.join(repo, "platform", "assembler", "cli_brain", "detect.py"),
        os.path.join(repo, "platform", "assembler", "cli_brain", "server.py"),
        os.path.join(repo, "platform", "assembler", "cli_brain", "slots.py"),
        os.path.join(repo, "product", "backend", "app", "phase1", "recipe_validator.py"),
        os.path.join(repo, "product", "backend", "app", "phase1", "router.py"),
        os.path.join(repo, "product", "backend", "app", "phase1", "motor_verdad.py"),
        os.path.join(repo, "product", "backend", "app", "phase1", "centro_modelos.py"),
        os.path.join(repo, "product", "backend", "app", "phase1", "centro_conexiones.py"),
        os.path.join(repo, "product", "app", "design", "brain-status.js"),
        os.path.join(repo, "product", "app", "design", "brain-setup.html"),
        os.path.join(repo, "product", "app", "design", "cuarto", "cuarto.models.js"),
        os.path.join(repo, "product", "app", "design", "cuarto", "cuarto.controls.js"),
        os.path.join(repo, "product", "app", "design", "cuarto", "cuarto.semaforo.js"),
    ]
    hits = []
    for path in scan:
        if not os.path.isfile(path):
            continue
        lines = []
        for ln in open(path, encoding="utf-8"):
            if "E1-FALLBACK" in ln:
                continue
            lines.append(ln)
        txt = "".join(lines)
        for b in banned:
            if b in txt:
                hits.append(f"{os.path.relpath(path, repo)}: {b}")
    ok(not hits, "tupla literal ausente en consumidores", hits)

    print("\n" + ("VERDE" if _fail == 0 else f"ROJO ×{_fail}"))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
