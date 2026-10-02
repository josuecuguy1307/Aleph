"""
test_espacios.py — Tests for V2-2 núcleo: EL ESPACIO CONECTADO.

Covers:
  • POST /espacios            — crear (de cero, con arrancador del catálogo, override)
  • GET  /espacios/{id}       — leer el espacio
  • POST /espacios/{id}/mensajes — encolar mensaje + crear sesión viva (STUB, sin LLM)
  • GET  /espacios/{id}/stream   — SSE esqueleto real desde un events.jsonl fixture
  • POST /espacios/{id}/aprobaciones/{gate_id} — conecta a .approve()/.reject()

NINGÚN test corre inferencia: la fábrica de sesiones está stubbeada (FakeSession).
La store de espacios vive en tmp_path — la data de producción no se toca.
"""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CATALOG_ROOT


# ── POST /espacios ────────────────────────────────────────────────────────────

class TestCrearEspacio:
    def test_crear_de_cero_returns_201(self, client: TestClient):
        resp = client.post("/espacios", json={"nombre": "Mi Sala", "nicho": "finanzas"})
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["nombre"] == "Mi Sala"
        assert data["nicho"] == "finanzas"
        assert data["estado"] == "vacio"
        assert data["mensajes_encolados"] == 0
        assert len(data["id"]) == 36  # UUID

    def test_crear_con_arrancador_copia_config_del_catalogo(self, client: TestClient):
        """El arrancador (template del catálogo) es el DATA SOURCE: su config.json
        se copia a la config del espacio. Verificamos contra el config real de t01."""
        t01 = json.loads(
            (CATALOG_ROOT / "finanzas" / "t01-cierre-mensual" / "config.json").read_text()
        )
        resp = client.post("/espacios", json={
            "nombre": "Cierre Mensual",
            "nicho": "finanzas",
            "arrancador_id": "t01-cierre-mensual",
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["arrancador_id"] == "t01-cierre-mensual"
        # La config del espacio salió del template, no de un default hardcodeado.
        assert data["config"]["belt_path"] == t01["belt_path"]
        assert data["config"]["model"] == t01["model"]
        assert data["config"]["tool_filters"] == t01["tool_filters"]

    def test_crear_con_arrancador_inexistente_404(self, client: TestClient):
        resp = client.post("/espacios", json={
            "nombre": "X", "nicho": "finanzas", "arrancador_id": "no-existe-99",
        })
        assert resp.status_code == 404

    def test_override_config_sobre_arrancador(self, client: TestClient):
        """config explícita sobreescribe lo del arrancador (armar pieza por pieza)."""
        resp = client.post("/espacios", json={
            "nombre": "Custom",
            "nicho": "finanzas",
            "arrancador_id": "t01-cierre-mensual",
            "config": {"model": "modelo-elegido-por-el-usuario", "temperature": 0.7},
        })
        assert resp.status_code == 201, resp.text
        cfg = resp.json()["config"]
        assert cfg["model"] == "modelo-elegido-por-el-usuario"
        assert cfg["temperature"] == 0.7
        # lo no sobreescrito sigue viniendo del arrancador
        assert "belt_path" in cfg

    def test_crear_persiste_en_jsonl_y_workdir(self, client: TestClient, tmp_espacios: Path):
        resp = client.post("/espacios", json={"nombre": "Durable", "nicho": "finanzas"})
        eid = resp.json()["id"]
        # índice JSONL
        index = tmp_espacios / "espacios.jsonl"
        assert index.exists()
        lines = [l for l in index.read_text().splitlines() if l.strip()]
        assert any(json.loads(l)["id"] == eid for l in lines)
        # workdir durable con state/events/mensajes
        edir = tmp_espacios / eid
        assert (edir / "state.json").exists()
        assert (edir / "events.jsonl").exists()
        assert (edir / "mensajes.jsonl").exists()


# ── GET /espacios/{id} ────────────────────────────────────────────────────────

class TestObtenerEspacio:
    def test_get_existente(self, client: TestClient):
        eid = client.post("/espacios", json={"nombre": "S", "nicho": "finanzas"}).json()["id"]
        resp = client.get(f"/espacios/{eid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == eid

    def test_get_inexistente_404(self, client: TestClient):
        resp = client.get("/espacios/no-existe")
        assert resp.status_code == 404


# ── POST /espacios/{id}/mensajes ──────────────────────────────────────────────

class TestEncolarMensaje:
    def _make(self, client: TestClient) -> str:
        return client.post("/espacios", json={"nombre": "S", "nicho": "finanzas"}).json()["id"]

    def test_encola_y_crea_sesion_viva_sin_llm(self, client: TestClient, fake_session_factory):
        eid = self._make(client)
        resp = client.post(f"/espacios/{eid}/mensajes", json={"texto": "hola Pim"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["encolado"] is True
        assert data["sesion_viva"] is True
        assert data["estado"] == "vivo"
        # la sesión creada es el STUB — nunca corrió un LLM
        sess = fake_session_factory.created[eid]
        assert sess is not None
        assert sess.closed is False

    def test_mensaje_vacio_422(self, client: TestClient):
        eid = self._make(client)
        resp = client.post(f"/espacios/{eid}/mensajes", json={"texto": "   "})
        assert resp.status_code == 422

    def test_mensaje_espacio_inexistente_404(self, client: TestClient):
        resp = client.post("/espacios/no-existe/mensajes", json={"texto": "hola"})
        assert resp.status_code == 404

    def test_mensaje_se_persiste_en_cola_y_evento(self, client: TestClient, tmp_espacios: Path):
        eid = self._make(client)
        client.post(f"/espacios/{eid}/mensajes", json={"texto": "primer mensaje"})
        mensajes = (tmp_espacios / eid / "mensajes.jsonl").read_text().splitlines()
        assert any("primer mensaje" in m for m in mensajes)
        # y dejó un evento 'mensaje_encolado' en el hilo
        events = (tmp_espacios / eid / "events.jsonl").read_text().splitlines()
        types = [json.loads(e)["type"] for e in events if e.strip()]
        assert "mensaje_encolado" in types

    def test_segundo_mensaje_reusa_la_misma_sesion(self, client: TestClient, fake_session_factory):
        eid = self._make(client)
        client.post(f"/espacios/{eid}/mensajes", json={"texto": "uno"})
        sess1 = fake_session_factory.created[eid]
        client.post(f"/espacios/{eid}/mensajes", json={"texto": "dos"})
        sess2 = fake_session_factory.created[eid]
        assert sess1 is sess2  # la sesión viva NO se re-crea


# ── GET /espacios/{id}/stream — SSE esqueleto real desde fixture ──────────────

def _seed_events(store, espacio_id: str, events: list[dict]) -> None:
    for e in events:
        store.append_event(espacio_id, e)


def _parse_sse(text: str) -> list[dict]:
    """Parsea bloques SSE 'id/event/data' de una respuesta de texto. Ignora
    heartbeats (líneas que empiezan con ':') y bloques sin data."""
    blocks = []
    for raw in text.split("\n\n"):
        block = {"id": None, "event": None, "data": None}
        has = False
        for line in raw.splitlines():
            if line.startswith("id:"):
                block["id"] = line[3:].strip(); has = True
            elif line.startswith("event:"):
                block["event"] = line[6:].strip(); has = True
            elif line.startswith("data:"):
                block["data"] = line[5:].strip(); has = True
        if has and block["data"] is not None:
            blocks.append(block)
    return blocks


class TestStreamSSE:
    def test_stream_404_si_no_existe(self, stream_client):
        c, store = stream_client
        resp = c.get("/espacios/no-existe/stream")
        assert resp.status_code == 404

    def test_stream_sirve_eventos_del_fixture(self, stream_client):
        c, store = stream_client
        state = store.create("Sala Stream", "finanzas", {})
        eid = state["id"]
        _seed_events(store, eid, [
            {"ts": 1.0, "type": "turn_started", "turn": 1},
            {"ts": 2.0, "type": "tool_call_started", "tool": "excel"},
            {"ts": 3.0, "type": "tool_call_finished", "tool": "excel", "result": "ok"},
        ])
        resp = c.get(f"/espacios/{eid}/stream")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        blocks = _parse_sse(resp.text)
        types = [json.loads(b["data"])["type"] for b in blocks]
        # el primer bloque es stream_open, luego los 3 eventos del fixture
        assert types[0] == "stream_open"
        assert "turn_started" in types
        assert "tool_call_started" in types
        assert "tool_call_finished" in types

    def test_stream_tiene_ids_incrementales(self, stream_client):
        c, store = stream_client
        eid = store.create("S", "finanzas", {})["id"]
        _seed_events(store, eid, [
            {"ts": 1.0, "type": "a"}, {"ts": 2.0, "type": "b"}, {"ts": 3.0, "type": "c"},
        ])
        resp = c.get(f"/espacios/{eid}/stream")
        # los ids de los eventos del fixture (índices 0,1,2) deben aparecer
        ids = [b["id"] for b in _parse_sse(resp.text) if b["event"] not in ("stream_open", "stream_idle_close")]
        assert ids == ["0", "1", "2"]

    def test_stream_last_event_id_replay_desde_el_siguiente(self, stream_client):
        c, store = stream_client
        eid = store.create("S", "finanzas", {})["id"]
        _seed_events(store, eid, [
            {"ts": 1.0, "type": "a"}, {"ts": 2.0, "type": "b"},
            {"ts": 3.0, "type": "c"}, {"ts": 4.0, "type": "d"},
        ])
        # cliente ya vio hasta el id=1 → debe recibir solo c(2) y d(3)
        resp = c.get(f"/espacios/{eid}/stream?lastEventId=1")
        data_types = [
            json.loads(b["data"])["type"]
            for b in _parse_sse(resp.text)
            if b["event"] not in ("stream_open", "stream_idle_close")
        ]
        assert data_types == ["c", "d"]

    def test_stream_last_event_id_via_header(self, stream_client):
        c, store = stream_client
        eid = store.create("S", "finanzas", {})["id"]
        _seed_events(store, eid, [
            {"ts": 1.0, "type": "a"}, {"ts": 2.0, "type": "b"}, {"ts": 3.0, "type": "c"},
        ])
        resp = c.get(f"/espacios/{eid}/stream", headers={"Last-Event-ID": "0"})
        data_types = [
            json.loads(b["data"])["type"]
            for b in _parse_sse(resp.text)
            if b["event"] not in ("stream_open", "stream_idle_close")
        ]
        assert data_types == ["b", "c"]

    def test_stream_emite_heartbeat(self, stream_client):
        c, store = stream_client
        eid = store.create("S", "finanzas", {})["id"]
        # sin eventos → el stream emite heartbeats hasta cerrar por idle limit
        resp = c.get(f"/espacios/{eid}/stream")
        assert ": heartbeat" in resp.text


# ── POST /espacios/{id}/aprobaciones/{gate_id} ────────────────────────────────

class TestAprobaciones:
    def _make_con_sesion(self, client: TestClient, fake_session_factory):
        eid = client.post("/espacios", json={"nombre": "S", "nicho": "finanzas"}).json()["id"]
        # encolar un mensaje crea la sesión viva (stub)
        client.post(f"/espacios/{eid}/mensajes", json={"texto": "trabajá"})
        return eid, fake_session_factory.created[eid]

    def test_aprobar_llama_approve_de_la_sesion(self, client: TestClient, fake_session_factory):
        eid, sess = self._make_con_sesion(client, fake_session_factory)
        # primá un gate pendiente (el contrato de 0014) sin correr inferencia
        sess.prime_gate({"que_va_a_hacer": "escribir B2", "donde_afecta": "Presupuesto-Q3"})
        resp = client.post(f"/espacios/{eid}/aprobaciones/gate-123", json={"aprueba": True})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["resuelto"] is True
        assert data["aprobado"] is True
        assert sess.approved  # .approve() fue invocado de verdad
        assert sess.pending_approval is None

    def test_rechazar_llama_reject_de_la_sesion(self, client: TestClient, fake_session_factory):
        eid, sess = self._make_con_sesion(client, fake_session_factory)
        sess.prime_gate({"que_va_a_hacer": "borrar rango"})
        resp = client.post(f"/espacios/{eid}/aprobaciones/gate-9", json={"aprueba": False})
        assert resp.status_code == 200
        assert resp.json()["aprobado"] is False
        assert sess.rejected

    def test_aprobacion_sin_sesion_viva_409(self, client: TestClient):
        eid = client.post("/espacios", json={"nombre": "S", "nicho": "finanzas"}).json()["id"]
        resp = client.post(f"/espacios/{eid}/aprobaciones/g1", json={"aprueba": True})
        assert resp.status_code == 409

    def test_aprobacion_sin_gate_pendiente_409(self, client: TestClient, fake_session_factory):
        eid, sess = self._make_con_sesion(client, fake_session_factory)
        # no se primó ningún gate → no hay nada que aprobar
        resp = client.post(f"/espacios/{eid}/aprobaciones/g1", json={"aprueba": True})
        assert resp.status_code == 409

    def test_aprobacion_espacio_inexistente_404(self, client: TestClient):
        resp = client.post("/espacios/no-existe/aprobaciones/g1", json={"aprueba": True})
        assert resp.status_code == 404

    def test_aprobacion_deja_evento_en_el_hilo(self, client: TestClient, fake_session_factory, tmp_espacios: Path):
        eid, sess = self._make_con_sesion(client, fake_session_factory)
        sess.prime_gate({"que_va_a_hacer": "x"})
        client.post(f"/espacios/{eid}/aprobaciones/gate-evt", json={"aprueba": True})
        events = (tmp_espacios / eid / "events.jsonl").read_text().splitlines()
        types = [json.loads(e)["type"] for e in events if e.strip()]
        assert "gate_resolved_by_user" in types


# ── Guardia: producción intocada ──────────────────────────────────────────────

class TestProduccionIntocada:
    def test_data_espacios_produccion_no_se_modifica(self, client: TestClient):
        """La data de producción (product/backend/data/espacios/) no se toca: los
        tests usan tmp_espacios. Si el dir de prod existe, su contenido no cambia."""
        from tests.conftest import REPO_ROOT
        prod = REPO_ROOT / "product" / "backend" / "data" / "espacios"
        before = sorted(p.name for p in prod.iterdir()) if prod.exists() else []

        client.post("/espacios", json={"nombre": "Guard", "nicho": "finanzas"})

        after = sorted(p.name for p in prod.iterdir()) if prod.exists() else []
        assert before == after, "¡La data de producción de espacios fue modificada por un test!"
