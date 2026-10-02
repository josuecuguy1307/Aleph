from __future__ import annotations

import pytest

from app.phase1.model_use_contract import ModelUse
from app.phase1.model_use_resolver import ResolutionFailure, public_choices, resolve_model_use


def _request(**overrides):
    data = {
        "call_id": "call-1",
        "idempotency_key": "idem-1",
        "workspace_id": "ciencia",
        "call_class": "science.main",
        "context": {"session_id": "s-1", "agent_id": None},
        "selection_ref": "codex_cli",
        "selection_scope": "session",
        "capabilities": {"required": ["streaming", "tool_calling"]},
        "input": {"messages": []},
        "tools": {"definitions": [{"type": "function"}], "required": True},
    }
    data.update(overrides)
    return ModelUse.model_validate(data)


def _catalog(_owner):
    return {
        "default_id": "codex_cli",
        "modelos": [{
            "picker_id": "codex_cli", "label": "Codex", "marca": "OpenAI",
            "familia": "cli", "model": "codex-cli", "brain_provider": "codex_cli",
            "conectado": True,
            "model_use_capabilities": ["streaming", "tool_calling", "reasoning"],
            "default": True,
        }, {
            "picker_id": "api:groq", "label": "Groq", "familia": "api",
            "model": "openai/gpt-oss-120b", "byok_ref": "keys:groq",
            "conectado": False, "causa": "falta_key",
            "model_use_capabilities": ["streaming"],
        }],
    }


def test_resuelve_raw_con_owner_scope_y_referencia_secretless():
    snapshot = resolve_model_use(_request(), owner_id="user-1", read_catalog=_catalog,
                                 now=lambda: 123.0)
    assert snapshot.owner_id == "user-1"
    assert snapshot.selection_scope == "session"
    assert snapshot.connection_ref == "cli:codex_cli"
    assert snapshot.resolved_model == "codex-cli"
    assert snapshot.admitted_at == 123.0
    assert snapshot.requirements_hash.startswith("sha256:")


def test_sin_selection_ref_usa_default_sin_contexto_sala():
    request = _request(selection_ref=None, selection_scope="default")
    snapshot = resolve_model_use(request, owner_id="u", read_catalog=_catalog)
    assert snapshot.selection_ref == "codex_cli"
    assert snapshot.selection_scope == "default"


def test_owner_es_obligatorio():
    with pytest.raises(ResolutionFailure) as exc:
        resolve_model_use(_request(), owner_id=None, read_catalog=_catalog)
    assert exc.value.code == "no_session"
    assert exc.value.status_code == 401


def test_par_inexistente_cae_al_default_del_proveedor():
    """⚠️ ESTE TEST CAMBIÓ DE CONTRATO, no de expectativa — y por decisión del dueño.

    Antes se llamaba `test_par_inexistente_falla_fuerte` y exigía que una selección que no
    existe TIRARA el turno. Desde el default por proveedor, no lo tira: lo atiende otro y
    **lo declara** en `fallback_chain`. Lo que se conserva —y es lo que el test viejo
    protegía de verdad— es que no se resuelve en silencio: si no hay con qué reemplazar,
    la causa vuelve igual (ver el test de abajo).
    """
    snap = resolve_model_use(_request(selection_ref="no-existe"), owner_id="u",
                             read_catalog=_catalog)
    assert snap.fallback_chain == ["no-existe"], "la sustitución tiene que quedar anotada"
    assert snap.selection_ref != "no-existe", "el snapshot dice quién atendió de verdad"
    assert snap.resolved_model


def test_par_inexistente_sigue_fallando_si_no_hay_reemplazo():
    """La otra mitad: sin candidato, la causa original vuelve con su status."""
    vacio = lambda _o: {"modelos": [], "default_id": ""}          # noqa: E731
    with pytest.raises(ResolutionFailure) as exc:
        resolve_model_use(_request(selection_ref="no-existe"), owner_id="u",
                          read_catalog=vacio)
    assert exc.value.code == "selection_not_found"


def test_modelo_no_conectado_falla_antes_de_ejecutar():
    with pytest.raises(ResolutionFailure) as exc:
        resolve_model_use(_request(selection_ref="api:groq",
                                   capabilities={"required": ["streaming"]}),
                          owner_id="u", read_catalog=_catalog)
    assert exc.value.code == "model_not_connected"
    assert exc.value.status_code == 424


def test_capacidad_obligatoria_no_se_degrada_en_silencio():
    with pytest.raises(ResolutionFailure) as exc:
        resolve_model_use(_request(capabilities={"required": ["vision"]}),
                          owner_id="u", read_catalog=_catalog)
    assert exc.value.code == "capability_unavailable"
    assert exc.value.extra["missing"] == ["vision"]


def _catalog_sin_matriz(_owner):
    """Una fila CONECTADA que sólo trae los rasgos de la UI, sin matriz técnica.

    Es el estado real que deja `_modelo_de_api` cuando el catálogo del proveedor no llegó:
    modelo resuelto por el id declarado, fila conectada, ficha técnica ausente.
    """
    return {
        "default_id": "api:anthropic",
        "modelos": [{
            "picker_id": "api:anthropic", "label": "Anthropic", "familia": "api",
            "model": "claude-opus-4-8", "byok_ref": "keys:anthropic", "conectado": True,
            "capacidades": ["razonamiento", "codigo", "rapido", "vision"],
            "default": True,
        }],
    }


def test_los_rasgos_de_la_ui_no_se_cuelan_como_matriz_tecnica():
    """`capacidades` es vocabulario de marketing; no acredita `text` ni `vision`."""
    with pytest.raises(ResolutionFailure) as exc:
        resolve_model_use(_request(selection_ref="api:anthropic",
                                   capabilities={"required": ["text"]}),
                          owner_id="u", read_catalog=_catalog_sin_matriz)
    assert exc.value.code == "capability_unknown"
    assert exc.value.extra["required"] == ["text"]

    # Y el exceso tampoco pasa: el rasgo `vision` es de la MARCA, no del modelo elegido.
    with pytest.raises(ResolutionFailure) as exc:
        resolve_model_use(_request(selection_ref="api:anthropic",
                                   capabilities={"required": ["vision"]}),
                          owner_id="u", read_catalog=_catalog_sin_matriz)
    assert exc.value.code == "capability_unknown"


def test_sin_requisitos_una_charla_no_necesita_matriz():
    """La invariante 4 habla de una capacidad `required`. Sin ninguna, no hay qué verificar."""
    snapshot = resolve_model_use(_request(selection_ref="api:anthropic",
                                          capabilities={"required": []},
                                          tools={"definitions": [], "required": False}),
                                 owner_id="u", read_catalog=_catalog_sin_matriz)
    assert snapshot.resolved_model == "claude-opus-4-8"
    assert snapshot.connection_ref == "keys:anthropic"


def test_matriz_ausente_no_es_matriz_vacia():
    """«No sabemos qué soporta» y «declara que no soporta nada» son dos causas distintas."""
    def _catalog_vacia(_owner):
        cat = _catalog_sin_matriz(_owner)
        cat["modelos"][0]["model_use_capabilities"] = []
        return cat

    with pytest.raises(ResolutionFailure) as exc:
        resolve_model_use(_request(selection_ref="api:anthropic",
                                   capabilities={"required": ["text"]}),
                          owner_id="u", read_catalog=_catalog_vacia)
    assert exc.value.code == "capability_unavailable"
    assert exc.value.extra["missing"] == ["text"]


def test_choices_no_filtra_modelo_url_alias_ni_credencial():
    choices = public_choices(_catalog("u"))
    assert len(choices) == 1
    assert choices[0]["selection_ref"] == "codex_cli"
    rendered = repr(choices)
    assert "codex-cli" not in rendered
    assert "brain_provider" not in rendered
    assert "base_url" not in rendered
    assert "byok_ref" not in rendered


# ── LA VERIFICACIÓN VISUAL, CONTRA LAS FILAS REALES ──────────────────────────────────
#
# El gate SIEMPRE tuvo razón: mientras el puente del CLI pegaba el base64 como texto,
# `cli.claude_cli` no declaraba `vision` y un pedido con imagen se rechazaba. Arreglado el
# transporte (`cli_brain/claude_cli.build_stdin` → `--input-format stream-json`), la fila
# lo declara y el mismo pedido pasa. Estas dos pruebas leen la matriz del CATÁLOGO REAL,
# no una copia: si alguien declara `vision` sin transporte, o lo quita teniéndolo, caen.


def _catalogo_real(_owner):
    from app.phase1.centro_modelos import _PICKER_HOSTEADO

    def _fila(slug, picker):
        cfg = _PICKER_HOSTEADO[slug]
        return {"picker_id": picker, "label": slug, "familia": "cli",
                "model": cfg["model"], "brain_provider": cfg["brain_provider"],
                "conectado": True,
                "model_use_capabilities": list(cfg["model_use_capabilities"])}

    return {"default_id": "claude_cli",
            "modelos": [_fila("cli.claude_cli", "claude_cli"),
                        _fila("cli.codex_cli", "codex_cli")]}


def test_el_cli_de_claude_admite_vision_porque_su_puente_la_transporta():
    snapshot = resolve_model_use(
        _request(selection_ref="claude_cli", capabilities={"required": ["vision"]}),
        owner_id="u", read_catalog=_catalogo_real)
    assert snapshot.connection_ref == "cli:claude_cli"
    assert snapshot.resolved_model == "claude-code-cli"


def test_el_cli_que_no_transporta_imagenes_sigue_rechazando_con_causa():
    """Y ESTE rechazo es lo correcto, no un bug: el puente de Codex es de sólo texto."""
    with pytest.raises(ResolutionFailure) as exc:
        resolve_model_use(
            _request(selection_ref="codex_cli", capabilities={"required": ["vision"]}),
            owner_id="u", read_catalog=_catalogo_real)
    assert exc.value.code == "capability_unavailable"
    assert exc.value.extra["missing"] == ["vision"]
