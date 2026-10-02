"""No external tool catalogue is inherited by Aleph Educación."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deeptutor.core.tool_protocol import ToolLookup
from deeptutor.runtime.providers.scope import ToolScope


@dataclass(frozen=True)
class ProviderToolView:
    registry: ToolLookup
    loader: None = None
    pool: tuple[Any, ...] = ()
    manifest: str = ""

    @classmethod
    def empty(cls, registry: ToolLookup) -> "ProviderToolView":
        return cls(registry=registry)

    def attach(self, _tool_schemas: list[dict[str, Any]]) -> None:
        return None


async def build_tool_view(
    *,
    base_registry: ToolLookup,
    scope: ToolScope,
    language: str = "en",
    refusal_message: str = "",
) -> ProviderToolView:
    del scope, language, refusal_message
    return ProviderToolView.empty(base_registry)


__all__ = ["ProviderToolView", "build_tool_view"]
