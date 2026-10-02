#!/usr/bin/env python3
"""test_motor_verdad.py — TESTS REALES del Motor de Verdad (CUARTO HONESTO · T1 · §2).

Cero mocks de la lógica bajo prueba: cada prober se ejerce contra un PEER REAL.
- cerebro / key: un `http.server` local que habla OpenAI-compat DE VERDAD (POST
  /chat/completions con un `model` real en la respuesta, GET /models con status real). El
  ping, el parseo, el model_final honesto y la clasificación de errores son el código de
  prod corriendo sobre HTTP real — no un stub de la función.
- CLI ausente: se fuerza el binario del CLI a una ruta inexistente → el detector D2 REAL
  reporta not_installed → ROTO cli_no_instalado.
- key inválida: el peer devuelve 401 → ROTO falta_key.
- MCP sin red: un comando stdio inexistente → probe_mcp REAL no arranca → ROTO sin_red.
- SQLite REAL del cliente (rol client) para la BYOK: repo.upsert_key/get_key.

    /opt/miniconda3/bin/pytest product/backend/app/phase1/test_motor_verdad.py -q
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]  # product/backend
_PLATFORM = Path(__file__).resolve().parents[4] / "platform"  # aleph_paths / db viven acá
for _p in (str(_BACKEND), str(_PLATFORM)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.phase1 import motor_verdad as motor  # noqa: E402


# ── peer HTTP real (OpenAI-compat) ─────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencio
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        ln = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(ln)
        if self.path.endswith("/chat/completions"):
            self._send(200, {"model": self.server.served_model,
                             "choices": [{"message": {"content": "pong"}}],
                             "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
        else:
            self._send(404, {"error": "nope"})

    def do_GET(self):
        if self.path.endswith("/models"):
            code = self.server.models_status
            self._send(code, {"data": [{"id": "x"}]} if code == 200
                       else {"error": {"message": "invalid api key"}})
        else:
            self._send(404, {"error": "nope"})


def _start_server(served_model="served-model-x", models_status=200):
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    srv.served_model = served_model
    srv.models_status = models_status
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


@pytest.fixture
def servers():
    made = []

    def mk(served_model="served-model-x", models_status=200):
        srv, url = _start_server(served_model, models_status)
        made.append(srv)
        return url

    yield mk
    for s in made:
        s.shutdown()


@pytest.fixture(autouse=True)
def _clean_cache():
    motor.invalidar_cache()
    yield
    motor.invalidar_cache()


@pytest.fixture
def alias_local():
    """Registra un alias de prueba en el registro de models (models.ALIASES) apuntando a un
    endpoint local, y lo saca al terminar. Ejerce el path COMPLETO de prueba_cerebro (resolve
    registry-only → ping → model_final) contra un peer real, sin violar la regla anti-SSRF
    (el alias vive en el registro, no es un endpoint crudo del cliente)."""
    added = []
    M = motor._models()

    def add(name, base_url, model="served-model-x", key_env=None):
        M.ALIASES[name] = {"model": model, "base_url": base_url + "/v1",
                           "key_env": key_env, "fallback": None}
        added.append(name)
        return name

    yield add
    for n in added:
        M.ALIASES.pop(n, None)
    motor.invalidar_cache()


@pytest.fixture
def cliente_db(tmp_path):
    """SQLite REAL del cliente (rol client) con schema y un user. Devuelve get_conn + uid."""
    previo = {k: os.environ.get(k) for k in ("ALEPH_ROLE", "PUPPET_SQLITE_PATH")}
    ruta = str(tmp_path / "motor.db")
    os.environ["ALEPH_ROLE"] = "client"
    os.environ["PUPPET_SQLITE_PATH"] = ruta

    from app.phase1 import repo
    repo._db = None
    sq = repo._dbmod()._sqlite()
    c = sq.conectar(ruta)
    sq.crear_schema(c)
    c.commit()
    c.close()

    conn = repo.get_conn()
    u = repo.register_user(conn, "motor@test.local", "pw-motor-1234")
    conn.close()

    yield {"uid": str(u["id"]), "get_conn": repo.get_conn}

    for k, v in previo.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    repo._db = None


# ══════════════════════════════════════════════════════════════════════════════════
# CONTRATO tipado (§1/§2)
# ══════════════════════════════════════════════════════════════════════════════════
def test_resultado_valida_estado_y_causa():
    r = motor._resultado(motor.CLI, "x", motor.ROTO, causa=motor.CLI_NO_INSTALADO,
                         evidencia={"a": 1})
    assert set(r) == {"tipo", "ref", "estado", "causa", "evidencia", "ts", "veredicto"}
    assert r["veredicto"]["estado"] == r["estado"]
    assert r["veredicto"]["causa"] == r["causa"]
    assert r["estado"] == "roto" and r["causa"] == "cli_no_instalado"
    assert isinstance(r["ts"], float)
    with pytest.raises(ValueError):
        motor._resultado(motor.CLI, "x", "verde")           # estado inexistente
    with pytest.raises(ValueError):
        motor._resultado(motor.CLI, "x", motor.ROTO, causa="explotó")  # causa inexistente


def test_causa_nula_si_no_es_roto():
    # una causa sólo tiene sentido con rojo; en cualquier otro estado se anula.
    r = motor._resultado(motor.KEY, "x", motor.PROBADO, causa=motor.FALTA_KEY)
    assert r["causa"] is None


# ══════════════════════════════════════════════════════════════════════════════════
# CEREBRO · ping real + model_final honesto (anti-grift)  [ESCENARIO: cerebro vivo → PROBADO]
# ══════════════════════════════════════════════════════════════════════════════════
def test_ping_chat_real_devuelve_model_final(servers):
    url = servers(served_model="served-model-x")
    r = motor._ping_chat(url + "/v1", "served-model-x", None)
    assert r["ok"] is True
    assert r["model_final"] == "served-model-x"
    assert isinstance(r["latencia_ms"], int)


def test_cerebro_vivo_probado_con_evidencia(servers, alias_local):
    url = servers(served_model="cerebro-real-42")
    name = alias_local("motor-test-vivo", url, model="cerebro-real-42")
    r = motor.prueba_cerebro(name)
    assert r["estado"] == motor.PROBADO, r
    ev = r["evidencia"]
    assert ev["model_final"] == "cerebro-real-42"   # evidencia HONESTA: lo que respondió
    assert ev["coincide"] is True and ev["degradado"] is False
    assert "latencia_ms" in ev


def test_cerebro_degradado_sigue_probado_pero_honesto(servers, alias_local):
    # free-tier degrada POR DISEÑO: model_final != requested NO es roto; se reporta honesto.
    url = servers(served_model="modelo-chico-degradado")
    name = alias_local("motor-test-deg", url, model="modelo-grande-pedido")
    r = motor.prueba_cerebro(name)
    assert r["estado"] == motor.PROBADO
    assert r["evidencia"]["degradado"] is True
    assert r["evidencia"]["coincide"] is False


def test_cerebro_alias_desconocido_no_configurado():
    # anti-SSRF: sólo aliases del registro; un endpoint arbitrario → NO_CONFIGURADO, no ping.
    r = motor.prueba_cerebro("http://evil.example/v1")
    assert r["estado"] == motor.NO_CONFIGURADO
    assert r["causa"] is None


def test_cerebro_falta_key(servers, alias_local, monkeypatch):
    # key_env declarada pero ni env ni cognición la tienen → ROTO falta_key (sin pinguear).
    monkeypatch.setattr(motor, "_cognition_key", lambda: "")
    url = servers()
    name = alias_local("motor-test-nokey", url, key_env="MOTOR_TEST_KEY_INEXISTENTE")
    monkeypatch.delenv("MOTOR_TEST_KEY_INEXISTENTE", raising=False)
    r = motor.prueba_cerebro(name)
    assert r["estado"] == motor.ROTO and r["causa"] == motor.FALTA_KEY, r


def test_cerebro_sin_red(alias_local):
    # peer inexistente (puerto cerrado que pasa el guard porque es host, no probe MCP): red caída.
    # usamos un alias a un host que no escucha → connection refused → SIN_RED o TIMEOUT.
    name = alias_local("motor-test-down", "http://127.0.0.1:1", model="x")
    r = motor.prueba_cerebro(name)
    assert r["estado"] == motor.ROTO
    assert r["causa"] in (
        motor.SIN_RED, motor.TIMEOUT, motor.ERROR_UPSTREAM, motor.FALLO_DESCONOCIDO,
    )
    if r["evidencia"].get("red", {}).get("consultada") is False:
        assert r["veredicto"]["escalon"] not in ("red", "proveedor")


# ══════════════════════════════════════════════════════════════════════════════════
# CLI · detector D2 real  [ESCENARIO: CLI ausente → ROTO cli_no_instalado]
# ══════════════════════════════════════════════════════════════════════════════════
def test_cli_ausente_roto_cli_no_instalado(monkeypatch):
    monkeypatch.setenv("PUPPET_CLAUDE_BIN", "/nonexistent/claude-motor-test")
    _invalida_detect_cache()
    r = motor.prueba_cli("claude_cli")
    assert r["estado"] == motor.ROTO and r["causa"] == motor.CLI_NO_INSTALADO, r
    assert r["evidencia"]["installed"] is False


def test_cli_provider_desconocido_no_configurado():
    r = motor.prueba_cli("mistral_cli")
    assert r["estado"] == motor.NO_CONFIGURADO


def _invalida_detect_cache():
    try:
        if str(motor._ASM) not in sys.path:
            sys.path.insert(0, str(motor._ASM))
        from cli_brain import detect
        detect.invalidate_cache()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════════
# KEY · BYOK real + validación mínima  [ESCENARIO: key inválida → ROTO falta_key]
# ══════════════════════════════════════════════════════════════════════════════════
def test_key_invalida_roto_key_invalida(servers, cliente_db):
    # [FIX-P1B · §6d §7] El test se llamaba `..._roto_falta_key` y exigía `FALTA_KEY` para un
    # 401 sobre una llave QUE SÍ ESTABA GUARDADA. Ese colapso era el bug: la UI ofrecía
    # [Poner la llave] a alguien que ya la había puesto, y el botón lo devolvía al mismo
    # formulario con la misma llave mala. Son dos estados distintos y dos botones distintos:
    #   no la pusiste  → falta_key    → [Poner la llave]
    #   la pusiste mal → key_invalida → [Cambiar la llave]
    # La aserción es MÁS estricta que la vieja, no más laxa: exige la causa exacta.
    url = servers(models_status=401)   # el proveedor RECHAZA la credencial
    from app.phase1 import repo
    conn = cliente_db["get_conn"]()
    repo.upsert_key(conn, user_id=cliente_db["uid"], provider="groq", secret="sk-bogus-xxxx")
    conn.close()
    r = motor.prueba_key("groq", owner=cliente_db["uid"], get_conn=cliente_db["get_conn"],
                         _validator_base_override=url + "/v1")
    assert r["estado"] == motor.ROTO and r["causa"] == motor.KEY_INVALIDA, r


def test_key_valida_probado(servers, cliente_db):
    url = servers(models_status=200)
    from app.phase1 import repo
    conn = cliente_db["get_conn"]()
    repo.upsert_key(conn, user_id=cliente_db["uid"], provider="groq", secret="sk-ok-yyyy")
    conn.close()
    r = motor.prueba_key("groq", owner=cliente_db["uid"], get_conn=cliente_db["get_conn"],
                         _validator_base_override=url + "/v1")
    assert r["estado"] == motor.PROBADO, r
    assert r["evidencia"]["http_status"] == 200


def test_key_sin_configurar_no_configurado(cliente_db):
    r = motor.prueba_key("nunca-conectado", owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"])
    assert r["estado"] == motor.NO_CONFIGURADO


def test_key_sin_validador_detectado(cliente_db):
    # key presente + proveedor sin validador conocido → DETECTADO (existe, sin verde falso).
    from app.phase1 import repo
    conn = cliente_db["get_conn"]()
    repo.upsert_key(conn, user_id=cliente_db["uid"], provider="serviciox", secret="tok-123")
    conn.close()
    r = motor.prueba_key("serviciox", owner=cliente_db["uid"], get_conn=cliente_db["get_conn"])
    assert r["estado"] == motor.DETECTADO


# ══════════════════════════════════════════════════════════════════════════════════
# MCP · handshake real  [ESCENARIO: MCP sin red → ROTO sin_red]
# ══════════════════════════════════════════════════════════════════════════════════
def test_causa_mcp_error_NO_inventa_sin_red(monkeypatch):
    # [FIX-P1B · §6c] Este test se llamaba `..._mapea_no_arranco_a_sin_red` y exigía
    # exactamente la mentira que este trabajo vino a matar: «el servidor local no arrancó»
    # traducido a «no tenés internet». Un stdio que no levanta jamás tocó la red; mandar a
    # esa persona a revisar su WiFi es apuntar al lado equivocado.
    #
    # La regla nueva: `sin_red` SÓLO se escribe si la sonda dice que no. Y para un destino
    # LOCAL la sonda ni se consulta — no hay red que culpar.
    monkeypatch.setenv("PUPPET_RED_FORZAR", "offline")   # aun con la red caída de verdad…
    from app.phase1 import red
    red.invalidar()
    ev: dict = {}
    assert motor._causa_mcp_error("el MCP local no arrancó (revisá el comando)",
                                  "/usr/local/bin/algo", ev) != motor.SIN_RED
    assert ev["red"]["consultada"] is False, ev
    assert motor._causa_mcp_error("connection refused", "http://127.0.0.1:9999", {}) != motor.SIN_RED
    # …y un destino REMOTO con la sonda diciendo que no, sí es sin_red.
    assert motor._causa_mcp_error("connection refused", "https://mcp.example.com", {}) == motor.SIN_RED
    # con internet OK, el mismo fallo remoto es del proveedor, no de la persona.
    monkeypatch.setenv("PUPPET_RED_FORZAR", "online")
    red.invalidar()
    assert motor._causa_mcp_error("connection refused", "https://mcp.example.com", {}) == motor.PROVEEDOR_CAIDO
    assert motor._causa_mcp_error("timed out", "https://mcp.example.com", {}) == motor.TIMEOUT
    monkeypatch.delenv("PUPPET_RED_FORZAR", raising=False)
    red.invalidar()


def test_mcp_binario_ausente_es_cli_no_instalado(tmp_path):
    # [FIX-P1B · §6b] Antes esto caía en sin_red/error_upstream tras pagar un spawn de 45 s.
    # Ahora el peldaño barato lo caza ANTES: el binario no está, y eso tiene un camino
    # propio ([Instalarlo]) que ninguna de las causas viejas ofrecía.
    spec = {"transport": "stdio", "command": "/nonexistent/mcp-server-motor-test",
            "args": [], "needs_auth": False}
    r = motor.prueba_mcp(spec=spec)
    assert r["estado"] == motor.ROTO, r
    assert r["causa"] == motor.CLI_NO_INSTALADO, r
    assert r["evidencia"]["escalon"] == "dependencia", r


def test_mcp_falta_key_sin_conectar():
    # spec que declara auth, sin secreto ni owner → FALTA_KEY antes de intentar conectar.
    spec = {"transport": "http", "url": "https://mcp.example.com", "needs_auth": True,
            "connector": "acme", "header_name": "Authorization"}
    r = motor.prueba_mcp(spec=spec)
    assert r["estado"] == motor.ROTO and r["causa"] == motor.FALTA_KEY


# ══════════════════════════════════════════════════════════════════════════════════
# DISPATCHER · cache TTL + "se prueba solo" + estado no bloqueante
# ══════════════════════════════════════════════════════════════════════════════════
def test_cache_y_force():
    a = motor.probar(motor.CLI, "mistral_cli")            # NO_CONFIGURADO, barato
    assert a["cacheado"] is False
    b = motor.probar(motor.CLI, "mistral_cli")            # segunda vez → cache
    assert b["cacheado"] is True
    c = motor.probar(motor.CLI, "mistral_cli", force=True)  # re-probar siempre disponible
    assert c["cacheado"] is False


def test_al_conectar_cachea_con_motivo():
    r = motor.al_conectar(motor.CLI, "mistral_cli")
    assert r["evidencia"].get("motivo") == "conexion"
    # y queda leíble por el semáforo sin re-probar:
    e = motor.estado(motor.CLI, "mistral_cli")
    assert e["fresco"] is True and e["evidencia"].get("motivo") == "conexion"


def test_estado_no_bloqueante_devuelve_detectado():
    e = motor.estado(motor.CEREBRO, "algo-no-probado-aun")
    assert e["estado"] == motor.DETECTADO and e["fresco"] is False


def test_tipo_invalido_422():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        motor.probar("banana", "x")


# ══════════════════════════════════════════════════════════════════════════════════
# ROUTER · el motor montado, vía TestClient
# ══════════════════════════════════════════════════════════════════════════════════
def test_router_probar_y_estado(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    monkeypatch.setenv("PUPPET_CLAUDE_BIN", "/nonexistent/claude-motor-router")
    _invalida_detect_cache()

    app = FastAPI()
    app.include_router(motor.build_motor_router(get_conn=None))
    client = TestClient(app, raise_server_exceptions=False)

    r = client.post("/v1/motor/probar", json={"tipo": "cli", "ref": "claude_cli"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estado"] == "roto" and body["causa"] == "cli_no_instalado", body

    e = client.get("/v1/motor/estado", params={"tipo": "cli", "ref": "zzz-inexistente"})
    assert e.status_code == 200
    assert e.json()["estado"] == "detectado"
