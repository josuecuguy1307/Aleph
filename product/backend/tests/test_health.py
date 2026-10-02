from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

#: Lo que /health decía antes de sumarle identidad de proceso y watchdog de datos. Se
#: conserva literal: cualquier cambio acá rompe monitoreo de terceros.
NUCLEO = {"status": "ok", "service": "puppet-ai-core", "version": "0.2.0"}


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_conserva_el_nucleo_historico():
    cuerpo = client.get("/health").json()
    assert {k: cuerpo.get(k) for k in NUCLEO} == NUCLEO


def test_health_identifica_el_proceso_que_contesta():
    """Para no volver a hablarle a un proceso fantasma: /health dice de qué build es."""
    proceso = client.get("/health").json()["proceso"]
    assert proceso["build"] in ("public", "founder", "dev")
    assert isinstance(proceso["started_at"], float)
    # `commit` sólo existe si el árbol es un repo git — no se exige, pero si está, es un sha.
    if "commit" in proceso:
        assert len(proceso["commit"]) == 12


def test_health_reporta_el_camino_de_datos(monkeypatch):
    """El watchdog del deadlock del VFS: /health NO puede decir 'ok' mientras la base
    está trabada. En un proceso sano el estado es 'ok' y trae el tamaño del almacén.

    ⚠️ POR QUÉ ESTE TEST MIRA EL ROL [Integración #5 · auditoría (e)]. `datos` es
    client-only A PROPÓSITO: en el plano de control la base es Postgres y el watchdog del
    VFS de SQLite no aplica, así que `_estado_datos()` devuelve None y la clave no sale.
    Escrito como estaba (`cuerpo["datos"]` a secas) el test asumía que el proceso es
    client, y eso NO se cumple corriendo la suite entera: `tests/phase1/test_payments_*`
    fijan `ALEPH_ROLE=control` en tiempo de IMPORT —tienen que hacerlo, `main.py` monta
    los routers al importarse—, así que el `app` compartido del proceso ya es el de
    control y ninguna clave client-only puede aparecer. Aislado pasaba, en la suite daba
    KeyError: era orden, no producto.

    Se prueban las DOS mitades para no perder cobertura por el arreglo:
      1. el contrato POR ROL de la respuesta real (client la trae, control no);
      2. la FORMA del payload de cliente, siempre — forzando el rol sobre `_estado_datos`,
         que es donde vive la decisión.
    """
    import app.main as main

    # 1 · el contrato por rol, contra la respuesta REAL de este proceso
    cuerpo = client.get("/health").json()
    if main._rol.is_client():
        datos = cuerpo["datos"]
        assert datos["estado"] == "ok", datos
        assert "conexiones_libres" in datos
    else:
        assert "datos" not in cuerpo, "el plano de control no reporta el camino de datos"
    assert cuerpo["status"] != "degraded"

    # 2 · el payload de cliente, corra la suite en el rol que corra
    monkeypatch.setattr(main._rol, "is_client", lambda: True)
    datos = main._estado_datos()
    assert datos["estado"] == "ok", datos
    assert "conexiones_libres" in datos


def test_health_degrada_cuando_la_base_esta_trabada(monkeypatch):
    """Con el camino de datos trabado, /health lo DICE (status=degraded + motivo).
    Antes decía 'ok' mientras la app se moría muda — un ok así hace que el supervisor
    NO reinicie, que es lo peor de los dos mundos."""
    import app.main as main

    monkeypatch.setattr(main, "_estado_datos", lambda: {
        "estado": "trabado", "motivo": "el VFS de SQLite quedó tomado", "recuperable": False})
    cuerpo = client.get("/health").json()
    assert cuerpo["status"] == "degraded"
    assert cuerpo["datos"]["motivo"]
    assert cuerpo["datos"]["recuperable"] is False
