"""Services-layer provider runtime with lazy SDK-backed implementations."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from .base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest

if TYPE_CHECKING:
    from .openai_compat_provider import OpenAICompatProvider

__all__ = [
    "GenerationSettings",
    "LLMProvider",
    "LLMResponse",
    "OpenAICompatProvider",
    "ToolCallRequest",
]


_LAZY_TYPES = {
    "OpenAICompatProvider": ("openai_compat_provider", "OpenAICompatProvider"),
}


def __getattr__(name: str):
    target = _LAZY_TYPES.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, class_name = target
    value = getattr(import_module(f"{__name__}.{module_name}"), class_name)
    globals()[name] = value
    return value
