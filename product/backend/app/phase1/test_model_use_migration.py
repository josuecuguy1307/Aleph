import pytest

from app.phase1.model_route_flags import RouteMode
from app.phase1.model_use_adapters import adapt_workspace_raw
from app.phase1.model_use_migration import admit_for_mode
from app.phase1.model_use_resolver import ResolutionFailure


def _request(selection_ref="codex_cli"):
    return adapt_workspace_raw(
        call_id="c", idempotency_key="i", workspace_id="ciencia",
        call_class="science.main", selection_ref=selection_ref,
        selection_scope="session", session_id="s",
        required_capabilities=["tool_calling"],
    )


def _catalog(_owner):
    return {"default_id": "codex_cli", "modelos": [{
        "picker_id": "codex_cli", "model": "codex-cli", "conectado": True,
        "brain_provider": "codex_cli", "model_use_capabilities": ["tool_calling"],
    }]}


def test_legacy_no_consulta_catalogo():
    calls = []
    decision = admit_for_mode(
        _request(), mode=RouteMode.LEGACY, owner_id=None,
        read_catalog=lambda owner: calls.append(owner),
    )
    assert not decision.use_aleph_v2
    assert decision.snapshot is None
    assert calls == []


def test_shadow_mide_exito_sin_desviar():
    decision = admit_for_mode(
        _request(), mode=RouteMode.SHADOW, owner_id="u", read_catalog=_catalog
    )
    assert not decision.use_aleph_v2
    assert decision.snapshot.selection_ref == "codex_cli"
    assert decision.shadow_error is None


def _catalog_vacio(_owner):
    """Un catálogo sin nada con qué reemplazar: es donde el fallo TIENE que seguir siendo
    fuerte, y es lo que estos dos tests protegen desde que existe el default por proveedor."""
    return {"default_id": "", "modelos": []}


def test_una_seleccion_rota_ya_no_tira_el_turno():
    """[default por proveedor] El contrato cambió por decisión del dueño: una selección que
    no existe la atiende otro modelo del catálogo y **se declara** en `fallback_chain`."""
    decision = admit_for_mode(
        _request("missing"), mode=RouteMode.ALEPH_V2, owner_id="u", read_catalog=_catalog
    )
    assert decision.use_aleph_v2
    assert decision.snapshot.fallback_chain == ["missing"]
    assert decision.snapshot.selection_ref == "codex_cli"


def test_shadow_registra_fallo_y_deja_viva_la_ruta_anterior():
    # Con un catálogo que SÍ tiene reemplazo ya no hay fallo que registrar (ver el test de
    # arriba); lo que este test protege es el caso en que no lo hay.
    decision = admit_for_mode(
        _request("missing"), mode=RouteMode.SHADOW, owner_id="u",
        read_catalog=_catalog_vacio,
    )
    assert not decision.use_aleph_v2
    assert decision.snapshot is None
    assert decision.shadow_error["error"] == "selection_not_found"


def test_aleph_v2_falla_fuerte_o_entrega_snapshot():
    ok = admit_for_mode(
        _request(), mode=RouteMode.ALEPH_V2, owner_id="u", read_catalog=_catalog
    )
    assert ok.use_aleph_v2
    assert ok.snapshot.connection_ref == "cli:codex_cli"

    # Falla fuerte SÓLO cuando no hay con qué reemplazar. Con reemplazo disponible, el
    # turno sale y lo dice — eso lo mide `test_una_seleccion_rota_ya_no_tira_el_turno`.
    with pytest.raises(ResolutionFailure):
        admit_for_mode(
            _request("missing"), mode=RouteMode.ALEPH_V2,
            owner_id="u", read_catalog=_catalog_vacio,
        )
