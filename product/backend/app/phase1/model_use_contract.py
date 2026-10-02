"""Contratos canónicos para usar modelos sin filtrar infraestructura al cliente.

``model-use/v1`` describe lo que una superficie necesita. No contiene proveedor,
base URL, credenciales ni fallbacks ejecutables. ``model-event/v1`` es el sobre
estable que permite conservar streaming, tools, costo y modelo final entre dialectos.

LEY 0: el workspace conserva su harness y ejecuta sus tools.
LEY 15: ``agent_id=None`` es RAW de primera clase; no se fabrica una Recipe v1.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


MODEL_USE_VERSION = "model-use/v1"
MODEL_EVENT_VERSION = "model-event/v1"

SelectionScope = Literal[
    "default", "workspace", "agent", "partner", "session", "task", "service"
]

ModelEventType = Literal[
    "call.admitted", "call.started", "call.completed", "call.failed", "call.cancelled",
    "model.selected", "model.routed", "model.fallback", "model.final",
    "model.output.delta", "model.reasoning.delta", "model.usage",
    "tool.request.delta", "tool.request.completed",
    "retry.scheduled", "retry.started", "retry.exhausted",
    "capability.degraded", "cost.observed", "cost.unmeasured",
    "media.progress", "media.completed", "media.failed",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CallContext(_Strict):
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
    task_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
    agent_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
    partner_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
    entity_id: Optional[str] = Field(default=None, min_length=1, max_length=256)


class CapabilityRequirements(_Strict):
    required: list[str] = Field(default_factory=list, max_length=64)
    preferred: list[str] = Field(default_factory=list, max_length=64)
    optional: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def _unique_and_disjoint(self) -> "CapabilityRequirements":
        groups = (self.required, self.preferred, self.optional)
        normalized = [[str(x).strip().casefold() for x in group] for group in groups]
        if any(not item for group in normalized for item in group):
            raise ValueError("las capacidades no pueden estar vacías")
        if any(len(group) != len(set(group)) for group in normalized):
            raise ValueError("una capacidad no puede repetirse dentro del mismo nivel")
        if len(set().union(*map(set, normalized))) != sum(map(len, normalized)):
            raise ValueError("una capacidad sólo puede pertenecer a un nivel")
        self.required, self.preferred, self.optional = normalized
        return self


class ModelInput(_Strict):
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=400)
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=128)


class ToolContract(_Strict):
    manifest_ref: Optional[str] = Field(default=None, min_length=1, max_length=512)
    definitions: list[dict[str, Any]] = Field(default_factory=list, max_length=96)
    required: bool = False

    @model_validator(mode="after")
    def _required_has_source(self) -> "ToolContract":
        if self.required and not (self.manifest_ref or self.definitions):
            raise ValueError("tools.required exige manifest_ref o definitions")
        return self


class GenerationConfig(_Strict):
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_output_tokens: Optional[int] = Field(default=None, gt=0, le=2_000_000)
    reasoning_effort: Optional[str] = Field(default=None, min_length=1, max_length=64)
    response_schema: Optional[dict[str, Any]] = None


class ModelUse(_Strict):
    schema_version: Literal[MODEL_USE_VERSION] = MODEL_USE_VERSION
    call_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=512)
    workspace_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    call_class: str = Field(min_length=1, max_length=256, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    context: CallContext = Field(default_factory=CallContext)
    selection_ref: Optional[str] = Field(default=None, min_length=1, max_length=256)
    selection_scope: SelectionScope
    policy_ref: Optional[str] = Field(default=None, min_length=1, max_length=512)
    capabilities: CapabilityRequirements = Field(default_factory=CapabilityRequirements)
    input: ModelInput = Field(default_factory=ModelInput)
    tools: ToolContract = Field(default_factory=ToolContract)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    stream: bool = True

    @model_validator(mode="after")
    def _scope_has_subject(self) -> "ModelUse":
        required_context = {
            "agent": ("agent_id", self.context.agent_id),
            "partner": ("partner_id", self.context.partner_id),
            "session": ("session_id", self.context.session_id),
            "task": ("task_id", self.context.task_id),
        }
        field_and_value = required_context.get(self.selection_scope)
        if field_and_value and not field_and_value[1]:
            raise ValueError(
                f"selection_scope={self.selection_scope} exige context.{field_and_value[0]}"
            )
        return self


class RouteSnapshot(_Strict):
    owner_id: str = Field(min_length=1, max_length=256)
    workspace_id: str
    call_id: str
    selection_ref: str
    selection_scope: SelectionScope
    policy_ref: Optional[str] = None
    requirements_hash: str
    resolved_model: str
    connection_ref: str
    fallback_chain: list[str] = Field(default_factory=list)
    admitted_at: float


class AdmissionReceipt(_Strict):
    """Respuesta pública del preflight; el routing ejecutable nunca sale del backend."""
    schema_version: Literal[MODEL_USE_VERSION] = MODEL_USE_VERSION
    admitted: Literal[True] = True
    call_id: str
    selection_ref: str
    selection_scope: SelectionScope
    policy_ref: Optional[str] = None
    requirements_hash: str


class ModelEvent(_Strict):
    schema_version: Literal[MODEL_EVENT_VERSION] = MODEL_EVENT_VERSION
    event_id: str = Field(min_length=1, max_length=256)
    call_id: str = Field(min_length=1, max_length=256)
    owner_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=128)
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    sequence: int = Field(ge=0)
    timestamp: float
    type: ModelEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    native: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "MODEL_EVENT_VERSION", "MODEL_USE_VERSION", "AdmissionReceipt", "CallContext",
    "CapabilityRequirements", "GenerationConfig", "ModelEvent", "ModelInput",
    "ModelUse", "RouteSnapshot", "SelectionScope", "ToolContract",
]
