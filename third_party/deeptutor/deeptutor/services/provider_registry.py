"""The sole model connection inherited by Aleph Educación.

No vendor, OAuth, local-model or gateway preset is retained here.  Aleph owns
model routing and supplies one OpenAI-compatible border through ``custom``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    keywords: tuple[str, ...] = ()
    env_key: str = ""
    display_name: str = "Aleph"
    backend: str = "openai_compat"
    env_extras: tuple[tuple[str, str], ...] = ()
    is_gateway: bool = False
    is_local: bool = False
    detect_by_key_prefix: str = ""
    detect_by_base_keyword: str = ""
    default_api_base: str = ""
    strip_model_prefix: bool = False
    supports_max_completion_tokens: bool = False
    supports_prompt_caching: bool = False
    supports_stream_options: bool = True
    model_overrides: tuple[tuple[str, dict[str, Any]], ...] = ()
    is_oauth: bool = False
    is_direct: bool = True
    thinking_style: str = ""
    reasoning_model_patterns: tuple[str, ...] = ()

    @property
    def mode(self) -> str:
        return "direct"

    @property
    def auth_mode(self) -> str:
        return "api_key"

    @property
    def label(self) -> str:
        return self.display_name


PROVIDER_ALIASES = {"openai_compatible": "custom", "openai-compatible": "custom"}
PROVIDERS = (ProviderSpec(name="custom", display_name="Aleph (cerebro único)"),)
NANOBOT_LLM_PROVIDERS = ("custom",)


def canonical_provider_name(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower().replace("-", "_")
    return PROVIDER_ALIASES.get(key, key)


def find_by_name(name: str | None) -> ProviderSpec | None:
    return PROVIDERS[0] if canonical_provider_name(name) == "custom" else None


def find_by_model(_model: str | None) -> ProviderSpec | None:
    return None


def find_gateway(
    provider_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> ProviderSpec | None:
    del api_key, api_base
    return find_by_name(provider_name)


def strip_provider_prefix(model: str, _spec: ProviderSpec | None) -> str:
    return model


__all__ = [
    "ProviderSpec", "PROVIDERS", "NANOBOT_LLM_PROVIDERS", "PROVIDER_ALIASES",
    "canonical_provider_name", "find_by_name", "find_by_model", "find_gateway",
    "strip_provider_prefix",
]
