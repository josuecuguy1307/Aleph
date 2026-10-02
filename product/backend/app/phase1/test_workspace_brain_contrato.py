"""La suite de conformidad del borde común (`/v1/workspaces/brain/*`).

[B0-5] La auditoría de convergencia buscó pruebas que nombraran `workspace_brain`,
`/workspaces/brain` o `repliegue` y no encontró ninguna: cada stack tenía su suite, pero la
COSTURA que se quiere volver obligatoria para los seis no tenía la suya. Esto es esa suite,
y cubre los dos bloqueos que se cerraron con ella:

  · B0-1 — las partes multimodales llegan al proveedor como partes, no como un string que
    las describe, y si el modelo no declara la modalidad la llamada falla ANTES del turno.
  · B0-4 — ninguna ruta operativa contesta sin dueño derivado de la sesión.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.phase1 import workspace_brain as wb
from app.phase1.router import build_phase1_router


class _Conn:
    def close(self):
        pass


def _catalog_con(*capacidades):
    def _leer(*_args, **_kwargs):
        return {
            "default_id": "codex_cli",
            "modelos": [{
                "picker_id": "codex_cli", "label": "Codex", "model": "codex-cli",
                "base_url": "http://canonical.invalid/v1", "brain_provider": "codex_cli",
                "conectado": True, "model_use_capabilities": list(capacidades),
            }],
        }
    return _leer


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(build_phase1_router(
        get_conn=lambda: _Conn(), events_dir=lambda: tmp_path,
    ))
    return TestClient(app, raise_server_exceptions=False)


def _sesion(monkeypatch, *, dueno="owner", capacidades=("text", "streaming", "vision")):
    from app.phase1 import billing, centro_modelos, repo
    monkeypatch.setattr(repo, "session_owner",
                        lambda token: dueno if str(token or "").strip() else None)
    monkeypatch.setattr(centro_modelos, "selector_modelos", _catalog_con(*capacidades))
    monkeypatch.setattr(billing, "preflight", lambda *_a, **_k: {"allowed": True})
    monkeypatch.setattr(billing, "record_run_cost", lambda *_a, **_k: {"ingested": 0})


_IMAGEN = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
_MULTIMODAL = [{"role": "user", "content": [
    {"type": "text", "text": "analiza"},
    {"type": "image_url", "image_url": {"url": _IMAGEN, "detail": "high"}},
]}]


def test_un_marcador_crudo_de_tool_no_sale_como_respuesta_del_usuario():
    texto = 'Listo. <function=bash>{"command":"pandoc ..."}'
    assert wb.texto_para_usuario(texto) == "Listo."
    assert wb.texto_para_usuario('<function=bash>{"command":"x"}') == ""
    assert wb.texto_para_usuario("prosa normal") == "prosa normal"


def _colar(trozos):
    """El texto que la pantalla llega a ver cuando el turno llega partido."""
    filtro = wb.FiltroDeMarcador()
    return "".join(filtro.empujar(t) for t in trozos) + filtro.resto()


def test_el_marcador_partido_entre_dos_pedazos_tampoco_sale():
    """LA QUE EL FILTRO DE UNA PIEZA NO PODÍA ATRAPAR, y por eso existe el incremental.

    En streaming el marcador no respeta el límite del chunk. Mirados de a uno, `<fun` y
    `ction=bash>` son prosa inocente: `texto_para_usuario` los deja pasar a los dos y en
    pantalla se lee el marcador entero. La vara compara las DOS formas a propósito — si
    alguien vuelve a filtrar chunk por chunk, esta línea se pone roja."""
    partido = ["Listo.", "<fun", "ction=bash>{}"]
    assert "".join(wb.texto_para_usuario(t) for t in partido) == "Listo.<function=bash>{}"
    assert _colar(partido) == "Listo."


def test_lo_retenido_que_no_era_un_marcador_se_devuelve():
    """Retener es apostar a que puede ser un marcador. Cuando la apuesta pierde, el texto
    tiene que volver: un turno que termina en `<` no puede comerse ese carácter."""
    assert _colar(["termina en <"]) == "termina en <"
    assert _colar(["dos < tres"]) == "dos < tres"
    assert _colar(["Voy a usar <b>negrita</b>"]) == "Voy a usar <b>negrita</b>"
    assert _colar(["Listo.", " Todo bien."]) == "Listo. Todo bien."


def test_el_corte_no_se_reabre_despues_del_marcador():
    """El cierre del marcador no es estable entre proveedores, así que no hay un punto en el
    que el texto vuelva a ser prosa. Confirmado el marcador, no sale nada más en el turno."""
    filtro = wb.FiltroDeMarcador()
    assert filtro.empujar('Listo. <function=bash>{"a":1}') == "Listo. "
    assert filtro.empujar("} y ahora hablo de nuevo") == ""
    assert filtro.resto() == ""


# ── B0-1 · LA FORMA MULTIMODAL SOBREVIVE ────────────────────────────────────────────

def test_una_imagen_no_se_convierte_en_un_string_que_la_describe():
    saneados = wb.sanitize_messages(_MULTIMODAL)
    contenido = saneados[0]["content"]
    assert isinstance(contenido, list), "el saneo aplanó las partes a texto"
    assert [p["type"] for p in contenido] == ["text", "image_url"], "se perdió el orden"
    assert contenido[1]["image_url"]["url"] == _IMAGEN, "se perdió la data URL"
    assert contenido[1]["image_url"]["detail"] == "high", "se perdió el detail"


def test_el_techo_recorta_el_texto_y_jamas_los_bytes_de_una_imagen():
    largo = "x" * (wb.MAX_CONTENT_CHARS + 5_000)
    saneados = wb.sanitize_messages([{"role": "user", "content": [
        {"type": "text", "text": largo},
        {"type": "image_url", "image_url": {"url": _IMAGEN}},
    ]}])
    partes = saneados[0]["content"]
    assert len(partes[0]["text"]) == wb.MAX_CONTENT_CHARS
    # Media imagen no es media pregunta: los bytes salen enteros o no salen.
    assert partes[1]["image_url"]["url"] == _IMAGEN


def test_una_parte_desconocida_se_rechaza_por_nombre_en_vez_de_aplanarse():
    with pytest.raises(wb.BrainError) as exc:
        wb.sanitize_messages([{"role": "user", "content": [{"type": "holograma"}]}])
    assert exc.value.error == "message_part_unknown"
    assert "holograma" in exc.value.detail


def test_las_modalidades_salen_de_la_forma_no_del_texto():
    assert wb.modalidades_de(_MULTIMODAL) == {"vision"}
    assert wb.modalidades_de([{"role": "user", "content": "una imagen de un gato"}]) == set()
    assert wb.modalidades_de([{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": "..."}},
        {"type": "file", "file": {"file_id": "f-1"}},
    ]}]) == {"audio", "files"}


def test_la_imagen_llega_como_imagen_hasta_el_proveedor(monkeypatch, tmp_path):
    _sesion(monkeypatch)
    visto = {}

    def _fake_complete(_recipe, messages, _tools, **_kw):
        visto["messages"] = messages
        return {"text": "ok", "tool_calls": [], "model": "codex-cli", "usage": None}

    monkeypatch.setattr(wb, "complete", _fake_complete)
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/complete",
        headers={"Authorization": "Bearer s"},
        json={"messages": _MULTIMODAL, "model": "codex_cli", "workspace": "ciencia"},
    )
    assert r.status_code == 200, r.text
    contenido = visto["messages"][0]["content"]
    assert isinstance(contenido, list)
    assert contenido[1]["image_url"]["url"] == _IMAGEN


def test_un_modelo_sin_vision_falla_antes_del_turno_y_no_ve_la_imagen(monkeypatch, tmp_path):
    """La regla del audit: no se convierte la imagen en texto ni se elimina en silencio."""
    _sesion(monkeypatch, capacidades=("text", "streaming"))   # sin `vision`
    monkeypatch.setenv("ALEPH_MODEL_ROUTE_CIENCIA_WORKSPACE_STEP", "aleph_v2")
    llamado = {"n": 0}

    def _no_deberia(*_a, **_k):
        llamado["n"] += 1
        return {"text": "", "tool_calls": [], "model": "x", "usage": None}

    monkeypatch.setattr(wb, "complete", _no_deberia)
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/complete",
        headers={"Authorization": "Bearer s"},
        json={"messages": _MULTIMODAL, "model": "codex_cli", "workspace": "ciencia"},
    )
    assert r.status_code >= 400, r.text
    assert "vision" in r.text
    assert llamado["n"] == 0, "se gastó un turno con un modelo que no puede ver"


# ── B0-2 · EL REPLIEGUE DE TOOLS NO PUEDE SER UN SECRETO ────────────────────────────

_REPLIEGUE = {"de": 40, "a": 18, "demoradas": ["redline", "compute", "order"]}


def _brain_con_repliegue(**extra):
    def _fake(*_a, **_k):
        return {"content": "listo", "tool_calls": [], "model": "codex-cli",
                "usage": None, "repliegue": _REPLIEGUE, "finish_reason": "stop", **extra}
    return _fake


def test_el_dialecto_openai_le_cuenta_al_harness_que_le_recortaron_las_tools(
        monkeypatch, tmp_path):
    """El modelo elige según el conjunto VISIBLE: si cambió, quien decide tiene que saberlo."""
    _sesion(monkeypatch)
    monkeypatch.setattr(wb, "complete", _brain_con_repliegue())
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli"},
        json={"model": "x", "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("aleph", {}).get("repliegue") == _REPLIEGUE, \
        "el sobre OpenAI se comió el repliegue"


def test_un_paso_sin_repliegue_devuelve_un_sobre_openai_puro(monkeypatch, tmp_path):
    """El caso normal no se ensucia: `aleph` sólo aparece cuando hay algo que decir."""
    _sesion(monkeypatch)
    monkeypatch.setattr(wb, "complete", lambda *_a, **_k: {
        "content": "listo", "tool_calls": [], "model": "codex-cli",
        "usage": None, "repliegue": None, "finish_reason": "stop"})
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli"},
        json={"model": "x", "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 200, r.text
    assert "aleph" not in r.json()


def test_el_repliegue_tambien_viaja_por_el_sobre_emulado(monkeypatch, tmp_path):
    """El repliegue en el sobre de la vía `emulado`, que es la que esta vara MIDE.

    Se llamaba «por el stream» y parchea `wb.complete` — la vía BLOQUEANTE. Pasaba porque
    el default era `emulado`, o sea que `stream: True` no llegaba a `complete_stream`: la
    vara decía cubrir el streaming y cubría lo otro, y nadie podía notarlo mientras las dos
    cosas coincidieran. Al mover el default salió a la luz. Ahora fija su modo en vez de
    heredarlo: una vara que depende de un default que no está probando se rompe cuando ese
    default cambia por una razón que no tiene nada que ver con ella.
    """
    _sesion(monkeypatch)
    monkeypatch.setenv("ALEPH_BRAIN_STREAM_DEFAULT", "emulado")
    monkeypatch.setattr(wb, "complete", _brain_con_repliegue())
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli"},
        json={"model": "x", "stream": True,
              "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 200, r.text
    assert "repliegue" in r.text and "redline" in r.text


# ── B0-2 · `tool_choice`: el motor deja de pisar al dueño del loop ──────────────────

def test_obliga_a_tool_reconoce_exactamente_los_dos_que_obligan():
    assert wb._obliga_a_tool("required") is True
    assert wb._obliga_a_tool("REQUIRED") is True
    assert wb._obliga_a_tool({"type": "function", "function": {"name": "redline"}}) is True
    # Éstos NO obligan: el modelo puede contestar texto, y ahí replegar sólo cuesta alcance.
    assert wb._obliga_a_tool("auto") is False
    assert wb._obliga_a_tool("none") is False
    assert wb._obliga_a_tool(None) is False
    assert wb._obliga_a_tool({}) is False


class _MotorFalso:
    """El mínimo de `_asm()` que `complete()` toca, para poder mirar la costura."""

    def __init__(self, *, revienta_con_413=False):
        import types
        self.visto = {}
        self._revienta = revienta_con_413
        self._intentos = 0
        self._models = types.SimpleNamespace(resolve_recipe_model=lambda _cfg: {
            "base_url": "http://x.invalid/v1", "primary": "m", "fallback": None,
            "brain_provider": None, "alias": None})
        self._asm = types.SimpleNamespace(_is_cli_brain_endpoint=lambda _u: False)
        # El doble del presupuesto imita al módulo REAL (`platform/assembler/tool_budget`),
        # así que cuando el borde aprende a pedirle algo nuevo, el doble tiene que
        # aprenderlo también — si no, la que se rompe es la vara y no el contrato.
        # `piso_de_workspace` llegó con el piso de `financial_rigor`: un workspace que no
        # está declarado tiene piso VACÍO, y ése es justo el caso de este test.
        self._budget = types.SimpleNamespace(
            repliegue=lambda tools, piso=(): types.SimpleNamespace(
                enviadas=tools[:1], demoradas=[{"name": "redline"}]),
            piso_de_workspace=lambda _ws: frozenset())

    def _route_chat(self, _msgs, tools, **kw):
        self._intentos += 1
        self.visto.setdefault("tool_choice", kw.get("tool_choice"))
        self.visto["tools_del_ultimo_intento"] = len(tools)
        if self._revienta and self._intentos == 1:
            raise RuntimeError("413 payload too large")
        return ({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                 "usage": None}, "m")

    def _es_413_por_tools(self, _exc):
        return True

    def _honest_model_final(self, _resp, model_used, _record):
        return model_used

    def _emit_model_cost_event(self, *_a, **_k):
        return None


def _con_motor(monkeypatch, motor):
    # Keep the canonical policy real; only the model transport is a double.
    motor._with_idioma_block = wb._asm()._with_idioma_block
    monkeypatch.setattr(wb, "_asm", lambda: motor)
    monkeypatch.setattr(wb, "_resolve_llm_key", lambda *_a, **_k: ("", False))


_DOS_TOOLS = [{"function": {"name": "a"}}, {"function": {"name": "b"}}]


@pytest.mark.parametrize("headers,body_lang,expected", [
    ({"X-Aleph-Lang": "en"}, None, "en"),
    ({"X-Aleph-Lang": "es"}, "en", "en"),
])
def test_el_dialecto_conserva_el_respaldo_de_idioma(monkeypatch, tmp_path, headers, body_lang, expected):
    _sesion(monkeypatch)
    visto = {}
    def complete(_r, _m, _t, **kw):
        visto.update(kw)
        return {"content": "ok", "tool_calls": [], "model": "codex-cli",
                "usage": None, "repliegue": None, "finish_reason": "stop"}
    monkeypatch.setattr(wb, "complete", complete)
    r = _client(tmp_path).post("/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli", **headers},
        json={"messages": [{"role": "user", "content": "hello"}], "lang": body_lang})
    assert r.status_code == 200, r.text
    assert visto["lang"] == expected


def test_sin_tool_choice_el_borde_no_le_pasa_nada_al_motor(monkeypatch):
    """La garantía byte-idéntica: ausente sigue siendo ausente, y el motor pone `auto`."""
    motor = _MotorFalso()
    _con_motor(monkeypatch, motor)
    wb.complete({"model": {}}, [{"role": "user", "content": "h"}], _DOS_TOOLS)
    assert motor.visto["tool_choice"] is None


def test_el_harness_puede_exigir_una_tool_y_el_motor_deja_de_pisarlo(monkeypatch):
    motor = _MotorFalso()
    _con_motor(monkeypatch, motor)
    wb.complete({"model": {}}, [{"role": "user", "content": "h"}], _DOS_TOOLS,
                tool_choice="required")
    assert motor.visto["tool_choice"] == "required"


def test_con_auto_un_413_todavia_repliega(monkeypatch):
    """El trato de siempre se conserva: sin obligación, replegar sólo cuesta alcance."""
    motor = _MotorFalso(revienta_con_413=True)
    _con_motor(monkeypatch, motor)
    out = wb.complete({"model": {}}, [{"role": "user", "content": "h"}], _DOS_TOOLS,
                      tool_choice="auto")
    assert out["repliegue"] is not None
    assert motor.visto["tools_del_ultimo_intento"] == 1


def test_si_el_paso_exige_una_tool_el_repliegue_esta_prohibido(monkeypatch):
    """Recortar el conjunto visible no le acota la opción: le cambia la elección."""
    motor = _MotorFalso(revienta_con_413=True)
    _con_motor(monkeypatch, motor)
    with pytest.raises(wb.BrainError) as exc:
        wb.complete({"model": {}}, [{"role": "user", "content": "h"}], _DOS_TOOLS,
                    tool_choice="required")
    assert exc.value.error == "tools_no_entran"
    assert exc.value.status == 413
    assert motor._intentos == 1, "se reintentó con un subconjunto pese a la obligación"


def test_el_dialecto_openai_traslada_el_tool_choice_del_harness(monkeypatch, tmp_path):
    _sesion(monkeypatch, capacidades=("text", "streaming", "vision", "tool_calling"))
    visto = {}

    def _fake(_r, _m, _t, **kw):
        visto["tool_choice"] = kw.get("tool_choice")
        return {"content": "ok", "tool_calls": [], "model": "codex-cli",
                "usage": None, "repliegue": None, "finish_reason": "stop"}

    monkeypatch.setattr(wb, "complete", _fake)
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli"},
        json={"model": "x", "messages": [{"role": "user", "content": "h"}],
              "tools": _DOS_TOOLS, "tool_choice": "required"},
    )
    assert r.status_code == 200, r.text
    assert visto["tool_choice"] == "required", "el sobre OpenAI se comió el tool_choice"


# ── B0-4 · NINGUNA RUTA OPERATIVA SIN DUEÑO ─────────────────────────────────────────

def test_sin_sesion_el_paso_no_corre_aunque_omita_user_id(monkeypatch, tmp_path):
    """Era `if body.user_id: _authorize(...)`: omitir el campo saltaba el gate entero."""
    _sesion(monkeypatch)
    llamado = {"n": 0}
    monkeypatch.setattr(wb, "complete", lambda *_a, **_k: llamado.update(n=1) or {})
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/complete",
        json={"messages": [{"role": "user", "content": "hola"}], "workspace": "ciencia"},
    )
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["error"] == "no_session"
    assert llamado["n"] == 0


def test_un_user_id_del_cuerpo_no_crea_autoridad(monkeypatch, tmp_path):
    """El id del body sólo se CONTRASTA contra la sesión; nunca la reemplaza."""
    _sesion(monkeypatch, dueno="owner")
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/complete",
        headers={"Authorization": "Bearer s"},
        json={"messages": [{"role": "user", "content": "hola"}],
              "user_id": "otra-persona", "workspace": "ciencia"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "forbidden"


def test_el_dialecto_openai_hereda_el_mismo_gate(monkeypatch, tmp_path):
    """El adaptador delega en el mismo paso: no puede tener una puerta más blanda."""
    _sesion(monkeypatch)
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        json={"model": "lo-que-sea", "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 401, r.text


def test_stream_real_rechaza_antes_de_abrir_el_sse(monkeypatch, tmp_path):
    """Un gate fallido es HTTP, nunca un 200 SSE que se corta sin causa."""
    _stream_real(monkeypatch)
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        json={"model": "x", "stream": True,
              "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 401, r.text


# ── EL SOBRE SE CIERRA CON CAUSA, AUNQUE EL TURNO REVIENTE ──────────────────────────
# [2026-08-14 · Ciencia] EL DEFECTO QUE CIERRAN. Con el streaming REAL prendido, una
# excepción aguas abajo salía del generador con las cabeceras YA enviadas: el cliente
# recibía dos chunks, sin `finish_reason`, sin `usage` y **sin `[DONE]`**, el stack lo leía
# como «No output generated» y el turno volvía VACÍO. La telemetría lo anotaba `status=200`.
# Medido sobre el binario instalado `363d7ceb…`: 3 de cada 4 turnos de Ciencia.
#
# Un fallo que llega como conexión cortada es lo que el contrato del repo llama fallo MUDO,
# y el único que puede cumplir «fallo visible» acá es quien abrió el sobre: aguas abajo ya
# no queda HTTP que devolver.

def _sse(texto: str) -> list:
    """Los `data:` de una respuesta SSE, ya decodificados (el `[DONE]` va como string)."""
    import json as _j
    out = []
    for linea in texto.splitlines():
        if not linea.startswith("data:"):
            continue
        cuerpo = linea[5:].strip()
        out.append(cuerpo if cuerpo == "[DONE]" else _j.loads(cuerpo))
    return out


def _stream_real(monkeypatch):
    """Fija la rama `real`, que hoy YA es el default.

    Se deja puesto igual: una vara que hereda el default mide lo que el default diga hoy,
    y el día que se mueva pasa a medir otra cosa sin decirlo. Declararlo cuesta una línea.
    """
    monkeypatch.setenv("ALEPH_BRAIN_STREAM_DEFAULT", "real")


def test_si_el_turno_revienta_el_stream_igual_cierra_con_causa_y_done(monkeypatch, tmp_path):
    _sesion(monkeypatch)
    _stream_real(monkeypatch)

    def _revienta(*_a, **_k):
        raise RuntimeError("_chat_stream todavía no cubre la vía litellm")
        yield  # pragma: no cover — lo vuelve generador sin llegar a ceder

    monkeypatch.setattr(wb, "complete_stream", _revienta)
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli"},
        json={"model": "x", "stream": True,
              "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 200, r.text
    trozos = _sse(r.text)
    assert trozos and trozos[-1] == "[DONE]", \
        "el stream terminó sin [DONE]: para el cliente eso es una conexión cortada"
    finales = [t for t in trozos if isinstance(t, dict)
               and (t.get("choices") or [{}])[0].get("finish_reason")]
    assert not finales, "un fallo no debe simular un cierre normal o un finish_reason inválido"
    errores = [t.get("error") for t in trozos
               if isinstance(t, dict) and t.get("error")]
    assert errores, "cerró el sobre pero sin la causa adentro"
    assert "litellm" in (errores[0].get("message") or ""), \
        f"la causa no dice qué pasó: {errores[0]}"


def test_lo_que_ya_se_habia_emitido_no_se_pierde_cuando_revienta(monkeypatch, tmp_path):
    """Reventar a mitad no puede costarle a la persona lo que ya había leído."""
    _sesion(monkeypatch)
    _stream_real(monkeypatch)

    def _a_medias(*_a, **_k):
        yield ("texto", "media respuesta")
        raise RuntimeError("se cortó a mitad")

    monkeypatch.setattr(wb, "complete_stream", _a_medias)
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli"},
        json={"model": "x", "stream": True,
              "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 200, r.text
    trozos = _sse(r.text)
    textos = [(t.get("choices") or [{}])[0].get("delta", {}).get("content")
              for t in trozos if isinstance(t, dict)]
    assert "media respuesta" in [x for x in textos if x], "se perdió lo ya emitido"
    assert trozos[-1] == "[DONE]", "y tampoco cerró el sobre"


def test_el_turno_sano_no_se_ensucia_con_el_sobre_de_error(monkeypatch, tmp_path):
    """El caso normal queda igual: `error` sólo aparece cuando hay algo que decir."""
    _sesion(monkeypatch)
    _stream_real(monkeypatch)

    def _sano(*_a, **_k):
        yield ("texto", "391")
        yield ("paso", {"finish_reason": "stop", "model": "codex-cli",
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    monkeypatch.setattr(wb, "complete_stream", _sano)
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli"},
        json={"model": "x", "stream": True,
              "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 200, r.text
    trozos = _sse(r.text)
    assert not [t for t in trozos if isinstance(t, dict) and t.get("aleph", {}).get("error")]
    fr = [(t.get("choices") or [{}])[0].get("finish_reason") for t in trozos
          if isinstance(t, dict)]
    assert "stop" in [x for x in fr if x], f"el turno sano no cerró con stop: {fr}"


# ── LA VÍA litellm CEDE EN VEZ DE REVENTAR ──────────────────────────────────────────

def test_chat_stream_cubre_la_via_litellm_y_lo_declara(monkeypatch):
    """El tier `oss-direct` ES una vía litellm y es el ÚLTIMO del cascade: que ahí se
    levantara `RuntimeError` era lo que mataba el turno entero."""
    asm = pytest.importorskip("assembler")
    monkeypatch.setattr(asm, "_usa_litellm", lambda _u: True)
    monkeypatch.setattr(asm, "_chat", lambda *_a, **_k: {
        "model": "qwen3:8b",
        "choices": [{"message": {"content": "391", "tool_calls": [
            {"id": "t1", "type": "function",
             "function": {"name": "calc", "arguments": "{}"}}]},
            "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    })
    cedido = list(asm._chat_stream([], [], "http://127.0.0.1:11434/v1", "qwen3:8b", "", 10, 0))
    clases = [c for c, _ in cedido]
    assert "no_streameado" in clases, \
        "cedió sin declarar que este tier NO streamea: eso sí sería fingir"
    assert ("texto", "391") in cedido
    assert ("fin", "stop") in cedido
    assert ("model_final", "qwen3:8b") in cedido
    # El `index` no viene en el sobre no-stream y aguas abajo se usa para saber a cuál de
    # varias tools pertenece cada trozo: sin él, dos tool_calls se pisan en el índice 0.
    tools = [carga for clase, carga in cedido if clase == "tool_delta"]
    assert tools and tools[0].get("index") == 0, f"tool_delta sin índice: {tools}"


# ── [obra 3] EL ANUNCIO QUE CORTA ───────────────────────────────────────────────────
# Cuando la red de seguridad dispara, el turno lo contesta un modelo que el usuario NO
# eligió. Eso ya se anunciaba en `aleph.degraded` y en el `notice` del espacio, y está
# MEDIDO que no lo ve nadie: son campos JSON que cada harness ajeno decide si mirar, y
# ninguno de los seis los mira. El texto es el único canal que atraviesa los seis sin
# pedirles que cambien una línea (LEY 0).

_DEGRADADO = {"intended_model": "codex-cli", "intended_alias": "codex_cli",
              "actual_model": "qwen3:8b", "tier": "oss-direct"}


def test_cuando_contesta_otro_modelo_la_persona_lo_ve_en_el_texto(monkeypatch, tmp_path):
    _sesion(monkeypatch)
    monkeypatch.setattr(wb, "complete", lambda *_a, **_k: {
        "content": "391", "tool_calls": [], "model": "qwen3:8b", "usage": None,
        "finish_reason": "stop", "degraded": _DEGRADADO})
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli"},
        json={"model": "x", "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 200, r.text
    contenido = r.json()["choices"][0]["message"]["content"]
    assert "qwen3:8b" in contenido, f"el aviso no nombra al modelo que contestó: {contenido!r}"
    assert "codex-cli" in contenido, f"el aviso no nombra al que se eligió: {contenido!r}"
    assert contenido.rstrip().endswith("391"), \
        "el aviso se comió la respuesta en vez de anteponerse"
    # Y el sobre estructurado NO se toca: el aviso es para los ojos, `degraded` es para la
    # máquina, y quitar uno para poner el otro sería cambiar un agujero por otro.
    assert r.json()["aleph"]["degraded"] == _DEGRADADO


def test_un_turno_sano_no_lleva_aviso(monkeypatch, tmp_path):
    _sesion(monkeypatch)
    monkeypatch.setattr(wb, "complete", lambda *_a, **_k: {
        "content": "391", "tool_calls": [], "model": "codex-cli", "usage": None,
        "finish_reason": "stop", "degraded": None})
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli"},
        json={"model": "x", "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "391"
    assert "aleph" not in r.json()


def test_el_aviso_tambien_viaja_por_el_stream_real(monkeypatch, tmp_path):
    """En la rama que streamea de verdad el `degraded` llega con el `paso`, o sea al final.
    Se anuncia ahí — al final se ve; callado no."""
    _sesion(monkeypatch)
    _stream_real(monkeypatch)

    def _degradado(*_a, **_k):
        yield ("texto", "391")
        yield ("paso", {"finish_reason": "stop", "model": "qwen3:8b",
                        "degraded": _DEGRADADO})

    monkeypatch.setattr(wb, "complete_stream", _degradado)
    r = _client(tmp_path).post(
        "/v1/workspaces/brain/openai/chat/completions",
        headers={"Authorization": "Bearer s", "X-Aleph-Model": "codex_cli"},
        json={"model": "x", "stream": True,
              "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 200, r.text
    trozos = _sse(r.text)
    texto = "".join((t.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
                    for t in trozos if isinstance(t, dict) and t.get("choices"))
    assert "391" in texto and "qwen3:8b" in texto, \
        f"el stream no anunció que contestó otro modelo: {texto!r}"
