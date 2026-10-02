"""The host-pinned brain triple: routing is not editable, everything else is.

WHAT THIS GUARDS, MEASURED 2026-08-15 AGAINST THE INSTALLED APP
---------------------------------------------------------------
`PUT /settings/llm` accepts any loopback client when `API_AUTH_KEY` is empty
(`security.py: require_settings_write_auth`), and it rewrites the routing triple that
decides where every turn goes. Any local process could take the workspace's turns out of
Aleph's edge — and the desvío that was actually measured kept `provider = openai` and
changed only `model_name` and `base_url`, so nothing looked wrong from the outside.

WHY PIN AND NOT CLOSE THE DOOR
-------------------------------
The same endpoint carries the generation knobs (temperature, timeout, retries, reasoning
effort). Rejecting the write would take those down with it: the user could no longer change
a timeout because the model field is not theirs to change. `test_generation_knobs_still_...`
below is that arm, and it is the one that makes this file able to fail.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from src.api.settings_routes import UpdateLLMSettingsRequest, _pin_brain_if_hosted

PIN = {
    "ALEPH_BRAIN_PROVIDER": "openai",
    "ALEPH_BRAIN_MODEL_NAME": "Cerebro de Aleph",
    "ALEPH_BRAIN_BASE_URL": "http://127.0.0.1:8330/v1/workspaces/brain/openai",
}


def _pedido(**kw) -> UpdateLLMSettingsRequest:
    base = {
        "provider": "openai",
        "model_name": "Cerebro de Aleph",
        "base_url": "http://127.0.0.1:8330/v1/workspaces/brain/openai",
        "temperature": 0.0,
        "timeout_seconds": 120,
        "max_retries": 2,
        "reasoning_effort": "",
    }
    base.update(kw)
    return UpdateLLMSettingsRequest(**base)


def test_routing_triple_is_forced_back_to_the_host_values() -> None:
    """The measured desvío: provider untouched, model and base_url moved."""
    with patch.dict(os.environ, PIN, clear=False):
        salida = _pin_brain_if_hosted(_pedido(
            model_name="gpt-5.3-chat-latest", base_url="https://api.openai.com/v1"))

    assert salida.provider == "openai"
    assert salida.model_name == "Cerebro de Aleph"
    assert salida.base_url == PIN["ALEPH_BRAIN_BASE_URL"]


def test_generation_knobs_still_go_through_untouched() -> None:
    """The arm that makes this test able to fail: pinning must not eat the rest.

    If the pin were implemented by rejecting the request, this is what would break — the
    settings screen sends the whole payload at once, so a user changing a timeout would be
    refused because of a field they did not touch."""
    with patch.dict(os.environ, PIN, clear=False):
        salida = _pin_brain_if_hosted(_pedido(
            model_name="otro-modelo", temperature=0.7, timeout_seconds=300,
            max_retries=5, reasoning_effort="high"))

    assert (salida.temperature, salida.timeout_seconds, salida.max_retries,
            salida.reasoning_effort) == (0.7, 300, 5, "high")


def test_standalone_is_byte_identical_to_upstream() -> None:
    """No pin in the environment → the payload passes through untouched."""
    limpio = {k: "" for k in PIN}
    with patch.dict(os.environ, limpio, clear=False):
        pedido = _pedido(provider="ollama", model_name="qwen3:8b",
                         base_url="http://127.0.0.1:11434/v1")
        salida = _pin_brain_if_hosted(pedido)

    assert salida is pedido
    assert salida.model_name == "qwen3:8b"


def test_the_pin_is_actually_wired_into_the_endpoint() -> None:
    """A guard nobody calls is not a guard.

    The four tests above exercise the FUNCTION. This one is about the WIRING: it reads the
    source of the module and demands that `update_llm_settings` apply the pin before it
    starts reading `payload.provider`. It is a structural check and it says so — it proves
    the call is there and in the right place, not that the endpoint behaves correctly end
    to end. That last mile needs the running stack, and is declared as such in the report.
    """
    import inspect

    import src.api.settings_routes as mod

    fuente = inspect.getsource(mod)
    cuerpo = fuente[fuente.index("async def update_llm_settings"):]
    cuerpo = cuerpo[:cuerpo.index("provider_name = payload.provider")]

    assert "_pin_brain_if_hosted(payload)" in cuerpo


def test_a_partial_pin_is_not_a_pin() -> None:
    """Two of the three variables is a broken host config, not a licence to pin.

    Half a triple would pin routing to something nobody declared — worse than not pinning,
    because the user could not fix it from the screen either."""
    parcial = dict(PIN, ALEPH_BRAIN_BASE_URL="")
    with patch.dict(os.environ, parcial, clear=False):
        pedido = _pedido(model_name="qwen3:8b")
        assert _pin_brain_if_hosted(pedido) is pedido
