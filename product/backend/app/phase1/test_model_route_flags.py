from app.phase1.model_route_flags import ModoStream, RouteMode, modo_stream, route_mode


def test_default_es_legacy():
    assert route_mode("ciencia", "science.main", environ={}) is RouteMode.LEGACY


def test_precedencia_clase_workspace_default():
    env = {
        "ALEPH_MODEL_ROUTE_DEFAULT": "aleph_v2",
        "ALEPH_MODEL_ROUTE_CIENCIA": "shadow",
        "ALEPH_MODEL_ROUTE_CIENCIA_SCIENCE_MAIN": "legacy",
    }
    assert route_mode("ciencia", "science.main", environ=env) is RouteMode.LEGACY
    assert route_mode("ciencia", "science.summary", environ=env) is RouteMode.SHADOW
    assert route_mode("legal", "legal.main", environ=env) is RouteMode.ALEPH_V2


def test_valor_invalido_no_activa_trafico():
    env = {"ALEPH_MODEL_ROUTE_CIENCIA": "on"}
    assert route_mode("ciencia", "science.main", environ=env) is RouteMode.LEGACY


# ── modo_stream ───────────────────────────────────────────────────────────────────
# El default de esta bandera se movió una vez SIN una vara que lo fijara, y el movimiento
# le costó a Ciencia el turno entero (turno vacío, `finish: "unknown"`, cero tokens; ver el
# bloque de `_DEFAULT_STREAM`). Estas tres no prueban que el streaming ande —para eso hace
# falta un turno completo contra la `.app`— pero sí que el default no se mueva sin que
# alguien lo escriba.


def test_default_stream_es_real():
    """El que no declara nada streamea de verdad.

    Era `EMULADO`. Cambió con la medición del 2026-08-29: con `emulado` los cuatro relojes
    del turno caen en el mismo instante (10/10, Δ 0,00 s) — o sea que el default entregaba
    el turno entero de golpe. La vara se mueve con el default a propósito: es la vara DEL
    default, y dejarla afirmando el anterior la volvería una que falla por tener razón.
    """
    assert modo_stream("ciencia", environ={}) is ModoStream.REAL


def test_precedencia_stream_workspace_sobre_default():
    env = {"ALEPH_BRAIN_STREAM_DEFAULT": "emulado", "ALEPH_BRAIN_STREAM_CIENCIA": "real"}
    assert modo_stream("ciencia", environ=env) is ModoStream.REAL
    assert modo_stream("legal", environ=env) is ModoStream.EMULADO


def test_stream_invalido_cae_al_default():
    assert modo_stream("ciencia", environ={"ALEPH_BRAIN_STREAM_CIENCIA": "chirimbolo"}) is ModoStream.REAL
