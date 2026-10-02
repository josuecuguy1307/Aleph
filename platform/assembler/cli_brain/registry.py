#!/usr/bin/env python3
"""registry.py — UNA fuente para los cerebros CLI (E1).

Agregar un CLI futuro = 1 clase CliBrainProvider + 1 `CliSpec` acá.
Los consumidores (detect, /models, aliases, validator, selector, UI) LEEN este
módulo. No se copia la lista de ids en el producto.

Agregar un CLI = 1 clase + 1 CliSpec. El argv real vive en la clase.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class CliSpec:
    """Contrato de un CLI. Todo lo que el producto necesita saber sin abrir la clase."""

    provider_id: str
    response_model_id: str
    display_name: str
    picker_label: str
    picker_hint: str
    glyph: str
    brand: str
    kind: str                          # completion_cli | agent_cli
    capabilities: tuple[str, ...]
    session: str                       # claude_jsonl | ignore | grok_dir
    tools_off: dict[str, Any]
    slots: Optional[int]               # None → default 1; Codex declara 3
    slots_env: Optional[str]           # override (PUPPET_CLI_SLOTS_CODEX)
    binary: str                        # nombre PATH (`claude`, `codex`)
    bin_env: str                       # override de path (PUPPET_CLAUDE_BIN)
    detect_argv: tuple[str, ...]       # args de estado, después del binario
    min_version: str
    min_version_env: Optional[str]
    aliases: tuple[str, ...]           # extra keys de ALIASES además de provider_id
    install: str
    update: str
    login: str
    doc: str
    login_no_auth: str
    login_not_installed: str
    submodels: tuple[tuple[str, str], ...]
    cls_path: str                      # "cli_brain.claude_cli.ClaudeCliProvider"
    centro_sub: str                    # copy de HOSTEADOS


# Orden = histórico (Claude, Codex) y Grok al final. Un CLI nuevo se appendea.

SPECS: list[CliSpec] = [
    CliSpec(
        provider_id="claude_cli",
        response_model_id="claude-code-cli",
        display_name="Claude Code",
        picker_label="Mi Claude Code",
        picker_hint="tu Claude Code local piensa por tu suscripción · $0 API",
        glyph="◈",
        brand="claude_code",
        kind="completion_cli",
        # `vision` SE DECLARA PORQUE EL PUENTE LA TRANSPORTA, y no antes. La matriz de acá
        # es lo que `model-use/v1` admite (`centro_modelos._picker_cli` la copia tal cual a
        # `cli.claude_cli.model_use_capabilities`), así que declararla mientras el prompt
        # pegaba el base64 como texto habría cambiado un 409 honesto por un turno que corre
        # y no ve nada. El carril está medido vivo: `claude_cli.soporta_imagenes` lo cuenta.
        # Codex y Grok NO la declaran: sus puentes siguen siendo de sólo texto.
        capabilities=("text", "streaming", "tool_calling", "vision", "reasoning", "code"),
        session="claude_jsonl",
        tools_off={"flags": ("--tools", "", "--strict-mcp-config")},
        slots=1,
        slots_env=None,
        binary="claude",
        bin_env="PUPPET_CLAUDE_BIN",
        detect_argv=("auth", "status"),
        min_version="2.0.0",
        min_version_env="PUPPET_MIN_CLAUDE_CLI",
        aliases=(),
        install="npm install -g @anthropic-ai/claude-code",
        update="npm install -g @anthropic-ai/claude-code@latest",
        login="claude   # y sigue el login en el navegador",
        doc="https://docs.claude.com/en/docs/claude-code/overview",
        login_no_auth="Abre una terminal y corre `claude` para loguearte.",
        login_not_installed="Instala Claude Code (claude.com/code) e inicia sesión.",
        submodels=(
            ("", "Default del plan (Opus)"),
            ("sonnet", "Sonnet"),
            ("opus", "Opus"),
            ("haiku", "Haiku"),
        ),
        cls_path="cli_brain.claude_cli.ClaudeCliProvider",
        centro_sub="Tu suscripción de Claude Code piensa por ti, sin API.",
    ),
    CliSpec(
        provider_id="codex_cli",
        response_model_id="codex-cli",
        display_name="Codex",
        picker_label="Mi Codex",
        picker_hint="tu Codex local piensa por tu suscripción · $0 API",
        glyph="⌘",
        brand="codex",
        kind="completion_cli",
        capabilities=("text", "streaming", "tool_calling", "reasoning", "code"),
        session="ignore",
        tools_off={"mcp_off": True, "sandbox": "read-only"},
        slots=3,
        slots_env="PUPPET_CLI_SLOTS_CODEX",
        binary="codex",
        bin_env="PUPPET_CODEX_BIN",
        detect_argv=("login", "status"),
        min_version="0.100.0",
        min_version_env="PUPPET_MIN_CODEX_CLI",
        aliases=(),
        install="npm install -g @openai/codex",
        update="npm install -g @openai/codex@latest",
        login="codex login",
        doc="https://github.com/openai/codex",
        login_no_auth="Abre una terminal y corre `codex login`.",
        login_not_installed="Instala Codex (npm i -g @openai/codex) y corre `codex login`.",
        submodels=(("", "Default de la cuenta"),),
        cls_path="cli_brain.codex_cli.CodexCliProvider",
        centro_sub="Tu suscripción de Codex piensa por ti, sin API.",
    ),
    CliSpec(
        provider_id="grok_cli",
        response_model_id="grok-cli",
        display_name="Grok",
        picker_label="Mi Grok",
        picker_hint="tu Grok local piensa por tu suscripción · $0 API",
        glyph="✱",
        brand="grok",
        kind="agent_cli",
        capabilities=("text", "streaming", "tool_calling", "reasoning", "code"),
        session="grok_dir",
        tools_off={
            "agent": "aleph-zero",
            "permission_mode": "default",
            "no_subagents": True,
            "allow": ("ask_user_question",),
            "deny": (
                "ask_user_question", "run_terminal_command", "read_file",
                "search_tool", "use_tool", "Agent",
            ),
        },
        slots=1,
        slots_env=None,
        binary="grok",
        bin_env="PUPPET_GROK_BIN",
        detect_argv=("models",),
        min_version="1.0.5",
        min_version_env="PUPPET_MIN_GROK_CLI",
        aliases=(),
        install="Instala Grok CLI (grok.com) — el binario vive en ~/.grok/bin/grok",
        update="grok  # el CLI se actualiza solo; o reinstala desde grok.com",
        login="grok   # y sigue el login en el navegador",
        doc="https://grok.com",
        login_no_auth="Abre una terminal y corre `grok` para loguearte.",
        login_not_installed="Instala Grok CLI (grok.com) e inicia sesión.",
        submodels=(
            ("", "Default del plan (Grok 4.6)"),
            ("grok-4.6", "Grok 4.6"),
            ("grok-4.5", "Grok 4.5"),
        ),
        cls_path="cli_brain.grok_cli.GrokCliProvider",
        centro_sub="Tu suscripción de Grok piensa por ti, sin API.",
    ),
]


def specs() -> tuple[CliSpec, ...]:
    return tuple(SPECS)


def spec_by_id(provider_id: str) -> Optional[CliSpec]:
    pid = str(provider_id or "")
    for s in SPECS:
        if s.provider_id == pid or s.response_model_id == pid:
            return s
    return None


def provider_ids() -> tuple[str, ...]:
    return tuple(s.provider_id for s in SPECS)


def response_model_ids() -> tuple[str, ...]:
    return tuple(s.response_model_id for s in SPECS)


def slugs() -> tuple[str, ...]:
    return tuple("cli." + s.provider_id for s in SPECS)


def brain_provider_enum() -> frozenset[str]:
    """Ids válidos en recipe.model.brain_provider, más byok/managed."""
    return frozenset(provider_ids()) | frozenset(("byok", "managed"))


def hands() -> dict[str, dict[str, str]]:
    """Forma histórica de CLI_MANO."""
    return {
        s.provider_id: {
            "nombre": s.display_name,
            "instalar": s.install,
            "actualizar": s.update,
            "login": s.login,
            "doc": s.doc,
        }
        for s in SPECS
    }


def marcas() -> dict[str, str]:
    return {s.provider_id: s.brand for s in SPECS}


def names() -> dict[str, str]:
    """provider_id → display_name (recipe_assembler, logs)."""
    return {s.provider_id: s.display_name for s in SPECS}


def aliases(base_url: str) -> dict[str, dict]:
    """Entradas de models.ALIASES: provider_id + aliases extra del spec."""
    out: dict[str, dict] = {}
    for s in SPECS:
        entry = {
            "model": s.response_model_id,
            "base_url": base_url,
            "key_env": None,
            "fallback": None,
        }
        out[s.provider_id] = entry
        for a in s.aliases:
            if a and a not in out:
                out[a] = entry
    return out


def min_versions() -> dict[str, str]:
    """Piso de versión por provider. Respeta el env histórico (PUPPET_MIN_*)."""
    import os
    out = {}
    for s in SPECS:
        v = s.min_version
        if s.min_version_env:
            raw = os.environ.get(s.min_version_env)
            if raw not in (None, ""):
                v = raw
        out[s.provider_id] = v
    return out


def prices() -> dict[str, tuple[float, float, str]]:
    note = "BYO-CLI: suscripción del usuario (sin costo API metered)"
    return {s.response_model_id: (0.0, 0.0, note) for s in SPECS}


def techo_de(provider_id: str, *, default: int = 1) -> int:
    """Slots simultáneos. Respeta el env histórico de Codex."""
    import os
    s = spec_by_id(provider_id)
    if s is None:
        return max(1, int(default))
    n = s.slots if s.slots is not None else default
    if s.slots_env:
        raw = os.environ.get(s.slots_env)
        if raw not in (None, ""):
            try:
                n = int(raw)
            except ValueError:
                pass
    return max(1, int(n))


def public_catalog() -> list[dict[str, Any]]:
    """Lo que sale por HTTP para que la UI no copie la lista."""
    out = []
    for i, s in enumerate(SPECS):
        submodels = [{"id": a, "label": b} for a, b in s.submodels]
        if s.provider_id == "codex_cli":
            try:
                from .codex_cli import CodexCliProvider
                from .codex_models import catalog
                binary = CodexCliProvider().binary()
                if binary:
                    ids, _default = catalog(binary)
                    submodels += [{"id": model_id, "label": model_id} for model_id in ids]
            except (OSError, ValueError):
                pass
        out.append({
            "provider_id": s.provider_id,
            "response_model_id": s.response_model_id,
            "display_name": s.display_name,
            "picker_label": s.picker_label,
            "picker_hint": s.picker_hint,
            "glyph": s.glyph,
            "brand": s.brand,
            "kind": s.kind,
            "capabilities": list(s.capabilities),
            "session": s.session,
            "slug": "cli." + s.provider_id,
            "tier": "Tu suscripción",
            "need": "cli",
            "login_no_auth": s.login_no_auth,
            "login_not_installed": s.login_not_installed,
            "submodels": submodels,
            "order": i,
        })
    return out


def instantiate_providers() -> dict[str, Any]:
    """{provider_id: CliBrainProvider()} — única fábrica de detect.PROVIDERS."""
    import importlib
    out = {}
    for s in SPECS:
        mod_name, cls_name = s.cls_path.rsplit(".", 1)
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, cls_name)
        inst = cls()
        if inst.provider_id != s.provider_id:
            raise RuntimeError(
                f"cli registry: {s.cls_path} declara provider_id={inst.provider_id!r}, "
                f"el spec dice {s.provider_id!r}"
            )
        if inst.response_model_id != s.response_model_id:
            raise RuntimeError(
                f"cli registry: {s.cls_path} declara response_model_id="
                f"{inst.response_model_id!r}, el spec dice {s.response_model_id!r}"
            )
        bin_name = getattr(inst, "_bin_name", None)
        if callable(bin_name) and bin_name() != s.binary:
            raise RuntimeError(
                f"cli registry: {s.cls_path}._bin_name()={bin_name()!r}, "
                f"el spec dice {s.binary!r}"
            )
        out[s.provider_id] = inst
    return out


def served_label() -> str:
    """Línea de arranque del server :8926."""
    parts = [f"{s.response_model_id} ({s.picker_label})" for s in SPECS]
    return " · ".join(parts)


__all__ = [
    "CliSpec", "SPECS", "specs", "spec_by_id", "provider_ids",
    "response_model_ids", "slugs", "brain_provider_enum", "hands", "marcas",
    "names", "aliases", "prices", "techo_de", "min_versions", "public_catalog",
    "instantiate_providers", "served_label",
]
