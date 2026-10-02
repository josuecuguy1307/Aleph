"""Subagent driver layer — drive a user's local agent CLI as a subagent.

DeepTutor runs on the same machine as the user's configured agent CLIs — Claude
Code, Codex, Gemini CLI, Kimi CLI, opencode, MiMo Code — so the backend can
drive them directly (spawned in print mode, or via a managed local server for
the opencode family) and stream back every native event. This package is the
decoupled core of that: backends that know one CLI each, a shared
streaming-subprocess primitive, and the value types that cross into the chat
capability. It knows nothing about the chat loop, KBs, or HTTP — those wire in
through the consult tool and the API.
"""

from __future__ import annotations

from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import (
    CONSULT_BUDGET_MAX,
    CONSULT_BUDGET_MIN,
    DEFAULT_CONSULT_BUDGET,
    BackendConfig,
    SubagentSettings,
    get_consult_budget,
    load_subagent_settings,
    save_subagent_settings,
    settings_from_dict,
)
# [Aleph] `from deeptutor.services.subagent.partner import PARTNER_BACKEND_KIND` — el módulo
# `partner.py` (10 KB de backend de Partners) se fue con el corte de EXTIRPACIONES.md, pero
# este `__init__` seguía importándolo, y con él caía TODO `services.subagent`: por eso no
# montaba el router `subagents`, que sirve `/subagents/settings` y `/subagents/connections`
# —dos endpoints que el frontend sí usa y que no tienen nada que ver con Partners—.
# De ese módulo acá sólo se necesita la constante, que es el discriminante de tipo de backend
# (`is_partner = kind == PARTNER_BACKEND_KIND`). Se conserva su valor literal del upstream
# 456f9c2 (`partner.py:44`) para que la comparación siga dando lo mismo: sin backend de
# Partners registrado, ningún subagente declara ese tipo y la rama nunca se toma.
PARTNER_BACKEND_KIND = "partner"
from deeptutor.services.subagent.registry import detect_all, get_backend, list_backend_kinds
from deeptutor.services.subagent.types import (
    ConsultResult,
    DetectResult,
    SubagentEvent,
)

__all__ = [
    "OnEvent",
    "SubagentBackend",
    "BackendConfig",
    "SubagentSettings",
    "DEFAULT_CONSULT_BUDGET",
    "CONSULT_BUDGET_MIN",
    "CONSULT_BUDGET_MAX",
    "PARTNER_BACKEND_KIND",
    "get_consult_budget",
    "load_subagent_settings",
    "save_subagent_settings",
    "settings_from_dict",
    "detect_all",
    "get_backend",
    "list_backend_kinds",
    "ConsultResult",
    "DetectResult",
    "SubagentEvent",
]
