from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.phase1.model_use_adapters import adapt_recipe_v1, adapt_workspace_raw
from app.phase1.model_use_contract import ModelEvent, ModelUse


def _raw(**overrides):
    data = {
        "schema_version": "model-use/v1",
        "call_id": "call-1",
        "idempotency_key": "idem-1",
        "workspace_id": "ciencia",
        "call_class": "science.main_agent",
        "context": {"session_id": "s-1", "agent_id": None},
        "selection_ref": "codex_cli",
        "selection_scope": "session",
        "policy_ref": None,
        "capabilities": {"required": ["streaming"], "preferred": ["reasoning"]},
        "input": {"messages": [{"role": "user", "content": "hola"}]},
        "tools": {"definitions": [{"type": "function", "function": {"name": "read"}}],
                  "required": True},
        "generation": {},
        "stream": True,
    }
    data.update(overrides)
    return data


def test_raw_es_primera_clase_sin_agente_ni_policy():
    request = ModelUse.model_validate(_raw())
    assert request.context.agent_id is None
    assert request.policy_ref is None
    assert request.selection_scope == "session"


@pytest.mark.parametrize("forbidden", ["owner_id", "provider", "base_url", "api_key", "fallback"])
def test_infraestructura_y_owner_no_entran_en_el_payload(forbidden):
    with pytest.raises(ValidationError):
        ModelUse.model_validate(_raw(**{forbidden: "secreto-o-infra"}))


def test_scope_explicito_exige_su_sujeto():
    with pytest.raises(ValidationError, match="context.session_id"):
        ModelUse.model_validate(_raw(context={"agent_id": None}))


def test_tools_requeridas_no_pueden_quedar_sin_schema_ni_manifest():
    with pytest.raises(ValidationError, match="manifest_ref o definitions"):
        ModelUse.model_validate(_raw(tools={"required": True, "definitions": []}))


def test_adaptador_raw_no_fabrica_recipe():
    request = adapt_workspace_raw(
        call_id="c", idempotency_key="i", workspace_id="finanzas",
        call_class="finance.agent", selection_ref="api:openai",
        selection_scope="session", session_id="s", messages=[], tools=[],
    )
    assert request.context.agent_id is None
    assert request.policy_ref is None


def test_adaptador_recipe_referencia_policy_sin_copiar_modelo_ejecutable():
    request = adapt_recipe_v1(
        recipe={"schema_version": "v1", "model": {
            "primary": "provider/model", "base_url": "https://provider.invalid/v1",
            "temperature": 0.3, "max_tokens": 123,
        }},
        agent_id="agent-1", selection_ref="sel-canonico", call_id="c",
        idempotency_key="i", workspace_id="legal", call_class="legal.agent",
    )
    dumped = request.model_dump()
    assert request.policy_ref == "recipe:v1:agent-1"
    assert request.selection_scope == "agent"
    assert "primary" not in repr(dumped)
    assert "base_url" not in repr(dumped)
    assert request.generation.max_output_tokens == 123


def test_evento_canónico_conserva_secuencia_y_tipo():
    event = ModelEvent.model_validate({
        "event_id": "e1", "call_id": "c1", "owner_id": "u1",
        "workspace_id": "ciencia", "sequence": 4, "timestamp": 1.5,
        "type": "model.final", "payload": {"model_final": "provider/model"},
    })
    assert event.schema_version == "model-event/v1"
    assert event.sequence == 4
