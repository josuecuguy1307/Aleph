#!/usr/bin/env python3
"""test_centro_conexiones.py — TESTS REALES del motor de requisitos (Centro · Terminal B).

Cero mocks de lo que está bajo prueba:
- carril API: un `http.server` local que habla OpenAI-compat DE VERDAD y que puede
  devolver 200 / 401 / 402 / 429 / lista de modelos / stream SSE. La distinción
  «llave mala ≠ sin crédito ≠ rate limit» se mide contra respuestas HTTP reales.
- carril CLI: el detector D2 REAL. Con el binario forzado a una ruta inexistente sale
  `cli_no_instalado` + el COMANDO de instalación; con el CLI del humano instalado sale
  el checklist verde de verdad (se saltea si no está).
- BYOK: SQLite REAL del cliente (repo.upsert_key/get_key) — la persistencia se verifica
  leyendo el almacén, no confiando en una variable.

    /opt/miniconda3/bin/pytest product/backend/app/phase1/test_centro_conexiones.py -q
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]          # product/backend
_PLATFORM = Path(__file__).resolve().parents[4] / "platform"
for _p in (str(_BACKEND), str(_PLATFORM)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.phase1 import centro_conexiones as CX   # noqa: E402
from app.phase1 import motor_verdad as MV        # noqa: E402


# ── peer HTTP real (OpenAI-compat, con status y catálogo configurables) ────────────
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj, ctype="application/json"):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _tiene_credencial(self):
        return bool(self.headers.get("Authorization") or self.headers.get("x-api-key"))

    def do_GET(self):
        if self.path.endswith("/models"):
            # [F7] EL PEER PIDE CREDENCIAL, como un proveedor de verdad. Antes contestaba
            # 200 con y sin `Authorization`, o sea que era un validador NO DISCRIMINANTE —
            # y por eso ninguna prueba de este archivo podía cazar el verde falso que la
            # auditoría del 2026-08-06 midió contra OpenRouter. `catalogo_publico=True`
            # reproduce ESE caso a propósito, y tiene su propia prueba.
            if not self.server.catalogo_publico and not self._tiene_credencial():
                self._send(401, {"error": {"message": "missing api key"}})
                return
            code = self.server.models_status
            if code == 200:
                self._send(200, {"data": [{"id": m} for m in self.server.modelos]})
            else:
                self._send(code, {"error": {"message": self.server.mensaje}})
        else:
            self._send(404, {"error": "nope"})

    def do_POST(self):
        ln = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(ln)
        if self.path.endswith("/chat/completions"):
            # ── [F9] EL PEER APRENDE A CONTESTAR LA SONDA ────────────────────────────
            # Reproduce lo MEDIDO contra groq y openrouter el 2026-08-07: sin credencial
            # 401; con credencial y un parámetro basura, 400 nombrando el parámetro. Un
            # fixture que no supiera esto mediría un proveedor que no existe.
            try:
                cuerpo_json = json.loads(crudo or b"{}")
            except Exception:                      # noqa: BLE001
                cuerpo_json = {}
            if not isinstance(cuerpo_json.get("temperature", 0), (int, float)):
                if not self._tiene_credencial():
                    self._send(401, {"error": {"message": "missing api key"}})
                    return
                if self.server.sonda_400:
                    self._send(400, {"error": {"message": "'temperature' : value must be a number",
                                               "type": "invalid_request_error"}})
                else:
                    self._send(self.server.sonda_status,
                               {"error": {"message": self.server.mensaje}})
                return
            code = self.server.stream_status
            if code != 200:
                self._send(code, {"error": {"message": self.server.mensaje}})
                return
            if self.server.stream_sse:
                cuerpo = (b'data: {"choices":[{"delta":{"content":"p"}}]}\n\n'
                          b'data: [DONE]\n\n')
                self._send(200, cuerpo, ctype="text/event-stream")
            else:
                self._send(200, {"model": "x", "choices": [{"message": {"content": "p"}}]})
        else:
            self._send(404, {"error": "nope"})


def _peer(models_status=200, modelos=("openai/gpt-oss-120b", "otro"),
          stream_status=200, stream_sse=True, mensaje="invalid api key",
          catalogo_publico=False, sonda_400=True, sonda_status=500):
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    srv.models_status = models_status
    srv.modelos = list(modelos)
    srv.stream_status = stream_status
    srv.stream_sse = stream_sse
    srv.mensaje = mensaje
    srv.catalogo_publico = catalogo_publico
    srv.sonda_400 = sonda_400
    srv.sonda_status = sonda_status
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/v1"


@pytest.fixture
def peer():
    hechos = []

    def mk(**kw):
        srv, url = _peer(**kw)
        hechos.append(srv)
        return url

    yield mk
    for s in hechos:
        s.shutdown()


@pytest.fixture(autouse=True)
def _limpiar():
    MV.invalidar_cache()
    yield
    MV.invalidar_cache()


@pytest.mark.parametrize("base", [
    "http://127.0.0.1:6379/v1",
    "http://169.254.169.254/latest/meta-data",
    "http://[::ffff:127.0.0.1]/v1",
    "http://2130706433/v1",
])
def test_agregar_key_bloquea_destinos_internos_sin_abrir(base, cliente_db, monkeypatch):
    monkeypatch.setenv("ALEPH_ROLE", "control")
    monkeypatch.setattr(MV._url_guard.config, "ALLOW_PRIVATE_TARGETS", False)

    def no_debe_abrir(*_args, **_kwargs):
        raise AssertionError("el transporte no debe recibir el destino bloqueado")

    monkeypatch.setattr(MV._url_guard._PUBLIC_OPENER, "open", no_debe_abrir)
    out = CX.agregar_key("miendpoint", "secreto-1234", owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=base)
    assert out["ok"] is False and out["guardada"] is False, out
    assert out["causa"] == MV.FALLO_DESCONOCIDO


def test_base_no_validadora_privada_se_guarda_sin_contactarla(cliente_db, monkeypatch):
    """Canvas/Moodle/Jupyter guardan su dominio, pero esta ruta no lo sondea."""
    monkeypatch.setattr(MV._url_guard.config, "ALLOW_PRIVATE_TARGETS", False)

    def no_debe_abrir(*_args, **_kwargs):
        raise AssertionError("base_es_validador=False no debe abrir la dirección")

    monkeypatch.setattr(MV._url_guard._PUBLIC_OPENER, "open", no_debe_abrir)
    base = "http://192.168.1.20/canvas"
    out = CX.agregar_key("canvas", "token-1234", owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=base,
                         base_es_validador=False)
    assert out["ok"] is True and out["guardada"] is True, out
    from app.phase1 import repo
    conn = cliente_db["get_conn"]()
    try:
        assert repo.get_key(conn, cliente_db["uid"], "canvas" + CX.SUFIJO_BASE) == base
    finally:
        conn.close()


def test_cliente_conserva_validadores_self_hosted(monkeypatch):
    monkeypatch.setenv("ALEPH_ROLE", "client")
    sentinel = object()
    seen = []

    def fake_urlopen(req, *, timeout):
        seen.append((req.full_url, timeout))
        return sentinel

    monkeypatch.setattr(MV.urllib.request, "urlopen", fake_urlopen)
    req = MV.urllib.request.Request("http://127.0.0.1:11434/v1/models")
    assert MV._urlopen_connector(req, timeout=3) is sentinel
    assert seen == [("http://127.0.0.1:11434/v1/models", 3)]


@pytest.fixture
def cliente_db(tmp_path):
    """SQLite REAL del cliente (rol client) con schema y un user."""
    previo = {k: os.environ.get(k) for k in ("ALEPH_ROLE", "PUPPET_SQLITE_PATH")}
    ruta = str(tmp_path / "conex.db")
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
    u = repo.register_user(conn, "centro@test.local", "pw-centro-1234")
    conn.close()

    yield {"uid": str(u["id"]), "get_conn": repo.get_conn}

    for k, v in previo.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    repo._db = None


def _por_id(reqs):
    return {r["id"]: r for r in reqs}


def _guardar(cliente_db, provider, secret):
    from app.phase1 import repo
    conn = cliente_db["get_conn"]()
    try:
        repo.upsert_key(conn, user_id=cliente_db["uid"], provider=provider, secret=secret)
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════════
# CARRIL API — la distinción que pedía la caminata: 401 ≠ 402 ≠ 429
# ══════════════════════════════════════════════════════════════════════════════════
def test_api_todo_verde_contra_peer_real(peer, cliente_db):
    url = peer()
    _guardar(cliente_db, "groq", "gsk_" + "x" * 40)
    reqs = list(CX._checklist_api("groq", owner=cliente_db["uid"],
                                  get_conn=cliente_db["get_conn"], base_url=url))
    r = _por_id(reqs)
    assert len(reqs) == 7, [x["id"] for x in reqs]
    assert r["formato"]["estado"] == CX.HECHO
    assert r["viva"]["estado"] == CX.HECHO
    assert r["diagnostico"]["estado"] == CX.HECHO
    assert r["modelo"]["estado"] == CX.HECHO           # el peer lista el modelo por defecto
    assert r["base_url"]["estado"] == CX.HECHO
    assert r["streaming"]["estado"] == CX.HECHO
    assert r["persistencia"]["estado"] == CX.HECHO
    # persistencia REAL: last4 leído del almacén cifrado, no de una variable
    assert r["persistencia"]["evidencia"]["last4"]
    assert CX._estado_fila(reqs) == (MV.PROBADO, None)


@pytest.mark.parametrize("status,causa,palabra", [
    (401, MV.KEY_INVALIDA, "no sirve"),
    (402, MV.SIN_CREDITO, "saldo"),
    (429, MV.RATE_LIMIT, "techo"),
])
def test_api_401_402_429_son_TRES_causas_distintas(peer, cliente_db, status, causa, palabra):
    url = peer(models_status=status)
    _guardar(cliente_db, "groq", "gsk_" + "x" * 40)
    r = _por_id(list(CX._checklist_api("groq", owner=cliente_db["uid"],
                                       get_conn=cliente_db["get_conn"], base_url=url)))
    assert r["viva"]["estado"] == CX.ROTO
    assert r["viva"]["causa"] == causa
    assert r["diagnostico"]["estado"] == CX.ROTO
    assert r["diagnostico"]["causa"] == causa
    assert palabra in r["diagnostico"]["detalle"], r["diagnostico"]["detalle"]
    # la causa viaja al nivel 1
    assert CX._estado_fila(list(CX._checklist_api(
        "groq", owner=cliente_db["uid"], get_conn=cliente_db["get_conn"],
        base_url=url)))[1] == causa


def test_api_sin_llave_es_sin_configurar_no_roto(cliente_db):
    reqs = list(CX._checklist_api("groq", owner=cliente_db["uid"],
                                  get_conn=cliente_db["get_conn"]))
    r = _por_id(reqs)
    assert r["formato"]["estado"] == CX.ROTO
    assert r["formato"]["causa"] == MV.KEY_AUSENTE
    assert r["viva"]["estado"] == CX.PENDIENTE      # no se inventa un rojo de red
    assert CX._estado_fila(reqs)[0] == MV.NO_CONFIGURADO


def test_api_formato_equivocado_se_caza_antes_de_la_red(cliente_db):
    _guardar(cliente_db, "groq", "sk-ant-esto-es-de-otro-proveedor")
    r = _por_id(list(CX._checklist_api("groq", owner=cliente_db["uid"],
                                       get_conn=cliente_db["get_conn"],
                                       base_url="http://127.0.0.1:1/v1")))
    assert r["formato"]["estado"] == CX.ROTO
    assert r["formato"]["causa"] == MV.KEY_INVALIDA
    assert "gsk_" in r["formato"]["detalle"]


def test_api_modelo_no_disponible(peer, cliente_db):
    url = peer(modelos=("otro-modelo",))
    _guardar(cliente_db, "groq", "gsk_" + "x" * 40)
    r = _por_id(list(CX._checklist_api("groq", owner=cliente_db["uid"],
                                       get_conn=cliente_db["get_conn"], base_url=url)))
    assert r["viva"]["estado"] == CX.HECHO           # la llave SÍ sirve
    assert r["modelo"]["estado"] == CX.ROTO
    assert r["modelo"]["causa"] == MV.MODELO_NO_DISPONIBLE


def test_api_streaming_no_sse_es_na_no_rojo(peer, cliente_db):
    url = peer(stream_sse=False)
    _guardar(cliente_db, "groq", "gsk_" + "x" * 40)
    r = _por_id(list(CX._checklist_api("groq", owner=cliente_db["uid"],
                                       get_conn=cliente_db["get_conn"], base_url=url)))
    assert r["streaming"]["estado"] == CX.NA          # respondió, pero no en stream


def test_api_sin_sesion_la_persistencia_lo_dice(peer):
    url = peer()
    r = _por_id(list(CX._checklist_api("groq", owner=None, get_conn=None, base_url=url)))
    assert r["persistencia"]["estado"] == CX.ROTO
    assert r["persistencia"]["causa"] == MV.SIN_SESION


# ══════════════════════════════════════════════════════════════════════════════════
# AGREGAR KEY (§E) — valida ANTES de guardar; nunca guarda una llave que no sirve
# ══════════════════════════════════════════════════════════════════════════════════
def test_agregar_key_valida_y_persiste(peer, cliente_db):
    url = peer()
    out = CX.agregar_key("groq", "gsk_" + "y" * 40, owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=url)
    assert out["ok"] is True and out["guardada"] is True
    assert out["estado"] == MV.PROBADO
    from app.phase1 import repo
    conn = cliente_db["get_conn"]()
    try:
        assert repo.get_key(conn, cliente_db["uid"], "groq") == "gsk_" + "y" * 40
    finally:
        conn.close()
    # queda PROBADA en el motor → la UI muestra "verificado hace X" sin re-pegar
    assert MV.estado(MV.KEY, "groq", owner=cliente_db["uid"])["estado"] == MV.PROBADO


def test_agregar_key_invalida_NO_se_guarda(peer, cliente_db):
    url = peer(models_status=401)
    out = CX.agregar_key("groq", "gsk_" + "z" * 40, owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=url)
    assert out["ok"] is False and out["guardada"] is False
    assert out["causa"] == MV.KEY_INVALIDA
    from app.phase1 import repo
    conn = cliente_db["get_conn"]()
    try:
        assert repo.get_key(conn, cliente_db["uid"], "groq") is None
    finally:
        conn.close()


def test_agregar_key_sin_credito_se_puede_guardar_igual(peer, cliente_db):
    url = peer(models_status=402)
    out = CX.agregar_key("groq", "gsk_" + "w" * 40, owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=url)
    assert out["causa"] == MV.SIN_CREDITO and out["guardada"] is False
    assert out["puede_guardar_igual"] is True
    out2 = CX.agregar_key("groq", "gsk_" + "w" * 40, owner=cliente_db["uid"],
                          get_conn=cliente_db["get_conn"], base_url=url, guardar_igual=True)
    assert out2["guardada"] is True                    # la llave no está mal: falta saldo


# ══════════════════════════════════════════════════════════════════════════════════
# [F7 · obra 1a] EL VALIDADOR DISCRIMINANTE
#
# EL BUG QUE ESTAS PRUEBAS EXISTEN PARA IMPEDIR (medido 2026-08-06 contra OpenRouter):
# su `GET /models` contesta 200 SIN credencial, y el veredicto salía de ese 200. Cualquier
# llave inventada con forma `sk-or-…` salía «probado» y se guardaba. Ninguna prueba de
# este archivo podía cazarlo porque el peer tampoco pedía credencial.
# ══════════════════════════════════════════════════════════════════════════════════
def test_validador_que_contesta_sin_llave_se_declara_no_discriminante(peer):
    publico = peer(catalogo_publico=True)
    privado = peer()
    assert MV.discriminante(publico)["discrimina"] is False
    assert MV.discriminante(privado)["discrimina"] is True
    # y el motivo se DICE, para que la evidencia del [?] no sea un booleano pelado
    assert "200 SIN credencial" in MV.discriminante(publico)["motivo"]


def test_catalogo_publico_NO_corona_verde_con_una_llave_que_el_stream_rechaza(peer, cliente_db):
    """EL CASO ÍNDICE, y sigue en pie con la sonda de F9: catálogo público (200 a todo) +
    la ruta de GENERACIÓN que rechaza la credencial. Antes: `probado` + guardada.

    Lo único que cambió es QUIÉN la rechaza: antes el POST de generación (que cobraba),
    ahora la sonda del 400 (que no). La puerta es la misma y el veredicto también."""
    url = peer(catalogo_publico=True, sonda_400=False, sonda_status=401)
    out = CX.agregar_key("groq", "gsk_" + "q" * 40, owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=url)
    assert out["ok"] is False, out
    assert out["estado"] == MV.ROTO and out["causa"] == MV.KEY_INVALIDA
    assert out["guardada"] is False
    from app.phase1 import repo
    conn = cliente_db["get_conn"]()
    try:
        assert repo.get_key(conn, cliente_db["uid"], "groq") is None
    finally:
        conn.close()


def test_el_verde_sale_de_la_SONDA_no_del_catalogo(peer, cliente_db):
    """★★ [F9] LAS DOS VARAS DE F7 SE DAN VUELTA, y el motivo es que su regla quedó atrás.

    Decían que el verde salía de `catalogo_autenticado` (cuando el `/models` discrimina) o
    de `generacion` (cuando no). Las dos coronaban por la puerta EQUIVOCADA o pagando
    tokens:

      · «el catálogo pide credencial» prueba que tu llave abre EL CATÁLOGO. No es lo que el
        usuario va a hacer con ella, y era el hueco: 7 de 8 proveedores coronaban verdes sin
        generar un token ni tocar la ruta de generación (medido 2026-08-07).
      · la `generacion` sí probaba la ruta correcta, pero cobraba — y contra el default de
        groq (`openai/gpt-oss-120b`, RAZONADOR) devolvía **string vacío** con
        `finish_reason: length` para max_tokens 1..32. Coronar con eso certifica algo que
        nadie vio.

    La sonda del 400 prueba lo mismo que la generación —la credencial cruza la puerta de
    GENERACIÓN— sin gastar un token y más rápido que el `/models` que reemplaza."""
    url = peer(catalogo_publico=True)              # el peor caso: catálogo público
    out = CX.agregar_key("groq", "gsk_" + "b" * 40, owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=url)
    assert out["ok"] is True and out["guardada"] is True
    assert out["estado"] == MV.PROBADO
    assert out["prueba"] == "auth_generacion", out
    ev = MV.estado(MV.KEY, "groq", owner=cliente_db["uid"])["evidencia"]
    assert ev["prueba"] == "auth_generacion"
    # ★ EVIDENCIA Y FECHA (ley de F7): el verde guarda QUÉ devolvió y CUÁNDO.
    assert ev["sonda"]["http_status"] == 400 and ev["sonda"]["veredicto"] == "auth_ok"
    assert isinstance(ev["sonda"]["latencia_ms"], int)
    assert MV.estado(MV.KEY, "groq", owner=cliente_db["uid"])["ts"]


def test_con_catalogo_que_discrimina_el_verde_TAMBIEN_lo_da_la_sonda(peer, cliente_db):
    """No hay dos caminos al verde según cómo sea el catálogo del proveedor. La sonda
    reemplaza a `catalogo_autenticado`, no lo complementa: un solo criterio para los 8."""
    url = peer()                                   # este catálogo SÍ pide credencial
    out = CX.agregar_key("groq", "gsk_" + "c" * 40, owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=url)
    assert out["estado"] == MV.PROBADO and out["prueba"] == "auth_generacion"


def test_si_la_sonda_no_se_entiende_el_techo_es_AMARILLO(peer, cliente_db):
    """Un 400 genérico, un 500, un 2xx a un parámetro basura: hubo respuesta y NO se sabe
    leerla. Jamás verde por defecto — «no pude probarlo» y «anda» son cosas distintas."""
    url = peer(sonda_400=False, sonda_status=500)
    out = CX.agregar_key("groq", "gsk_" + "d" * 40, owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=url)
    assert out["estado"] == MV.DETECTADO, out
    ev = MV.estado(MV.KEY, "groq", owner=cliente_db["uid"])["evidencia"]
    assert ev["prueba"] == "sonda_ambigua"


def test_sin_prueba_dura_posible_el_techo_es_AMARILLO_jamas_verde(peer, cliente_db, monkeypatch):
    """Catálogo público y ningún modelo declarado con el que hacer la prueba dura:
    «no pude probarlo» NO es «anda». El techo es 🟡 detectado."""
    monkeypatch.delitem(MV.MODELO_PRUEBA, "groq", raising=False)
    url = peer(catalogo_publico=True)
    out = CX.agregar_key("groq", "gsk_" + "d" * 40, owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=url)
    assert out["ok"] is True and out["guardada"] is True   # la llave existe: se guarda
    assert out["estado"] == MV.DETECTADO                   # pero NO se afirma que ande
    assert MV.estado(MV.KEY, "groq", owner=cliente_db["uid"])["estado"] == MV.DETECTADO


def test_checklist_no_afirma_sobre_la_llave_si_el_catalogo_es_publico(peer, cliente_db):
    """Los 5 pasos que salían verdes con basura. Los tres que hablan DE LA LLAVE pasan a
    NA con su motivo; el que decide es `streaming`, que es un POST real."""
    # ⚠️ [F9] EL PEER SE VUELVE COHERENTE, y la vara sube de exigencia. Antes decía
    # `stream_status=401` con la sonda contestando 400: un proveedor que rechaza la llave en
    # la generación pero la acepta en la validación de parámetros no existe. Con el peer
    # coherente (rechaza en las dos), la respuesta ya no es «no puedo afirmar nada» (NA):
    # es **ROTO con su causa**, que es estrictamente mejor — nombra el problema en vez de
    # encogerse de hombros.
    url = peer(catalogo_publico=True, stream_status=401, sonda_400=False, sonda_status=401)
    _guardar(cliente_db, "groq", "gsk_" + "e" * 40)
    r = _por_id(list(CX._checklist_api("groq", owner=cliente_db["uid"],
                                       get_conn=cliente_db["get_conn"], base_url=url)))
    assert r["viva"]["estado"] == CX.ROTO and r["viva"]["causa"] == MV.KEY_INVALIDA, r["viva"]
    # ★ y el DETALLE que se dibuja es copy sellado, jamás el cuerpo crudo del proveedor
    assert r["viva"]["detalle"] == "Credencial inválida", r["viva"]["detalle"]
    assert r["diagnostico"]["estado"] == CX.NA
    assert r["modelo"]["estado"] == CX.NA
    assert r["streaming"]["estado"] == CX.ROTO
    assert r["streaming"]["causa"] == MV.KEY_INVALIDA
    estado, causa = CX._estado_fila(list(r.values()))
    assert (estado, causa) == (MV.ROTO, MV.KEY_INVALIDA)


def test_una_sola_tabla_de_modelo_de_prueba(peer):
    """`centro_conexiones.MODELO_DEFECTO` es un ALIAS de `motor_verdad.MODELO_PRUEBA`.
    Dos tablas se desincronizan y entonces el checklist prueba un modelo y el motor otro."""
    assert CX.MODELO_DEFECTO is MV.MODELO_PRUEBA


def test_agregar_key_recuerda_la_direccion_propia(peer, cliente_db):
    """Endpoint OpenAI-compat propio: se guarda con la llave y se relee en cada checklist
    (sin esto habría que re-tipear la dirección en cada prueba)."""
    url = peer()
    out = CX.agregar_key("miendpoint", "loquesea-1234", owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"], base_url=url)
    assert out["ok"] is True and out["guardada"] is True
    # el checklist SIN base_url explícito la encuentra sola
    r = _por_id(list(CX._checklist_api("miendpoint", owner=cliente_db["uid"],
                                       get_conn=cliente_db["get_conn"])))
    assert r["viva"]["estado"] == CX.HECHO
    assert r["base_url"]["estado"] == CX.HECHO
    # …y el marcador hermano NO ensucia la lista de filas
    filas = CX.listar(cliente_db["uid"], cliente_db["get_conn"])["filas"]
    assert not any(f["ref"].endswith(CX.SUFIJO_BASE) for f in filas)
    assert any(f["ref"] == "miendpoint" for f in filas)


def test_agregar_key_de_otro_proveedor_se_rechaza_por_forma(cliente_db):
    out = CX.agregar_key("groq", "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx", owner=cliente_db["uid"],
                         get_conn=cliente_db["get_conn"])
    assert out["ok"] is False and out["causa"] == MV.KEY_INVALIDA and out["guardada"] is False


# ══════════════════════════════════════════════════════════════════════════════════
# CARRIL CLI — detector REAL
# ══════════════════════════════════════════════════════════════════════════════════
def test_cli_ausente_da_causa_y_EL_COMANDO(monkeypatch):
    monkeypatch.setenv("PUPPET_CLAUDE_BIN", "/no/existe/claude-de-mentira")
    from cli_brain import detect
    detect.invalidate_cache()
    reqs = list(CX.correr_checklist("cli", "claude_cli"))
    detect.invalidate_cache()
    r = _por_id(reqs)
    assert len(reqs) == 8, [x["id"] for x in reqs]
    assert r["binario"]["estado"] == CX.ROTO
    assert r["binario"]["causa"] == MV.CLI_NO_INSTALADO
    # el arreglo es del humano → comando EXACTO + doc oficial
    assert r["binario"]["mano_humana"]["comando"].startswith("npm install")
    assert r["binario"]["mano_humana"]["doc"].startswith("https://")
    # sin binario no se inventa un rojo de versión ni de sesión
    assert r["version"]["estado"] == CX.PENDIENTE
    assert r["sesion"]["estado"] == CX.PENDIENTE
    assert CX._estado_fila(reqs)[0] == MV.ROTO


def test_cli_familia_desconocida_no_finge():
    reqs = list(CX.correr_checklist("cli", "no_existe_cli"))
    assert all(r["estado"] == CX.NA for r in reqs)


@pytest.mark.parametrize("pid", ["claude_cli", "codex_cli"])
def test_cli_real_del_humano_si_esta_instalado(pid):
    """Contra el CLI REAL de esta máquina. Si no está instalado, se saltea (no miente)."""
    from cli_brain import detect
    prov = detect.PROVIDERS[pid]
    if not prov.binary():
        pytest.skip(f"{pid} no está instalado en esta máquina")
    r = _por_id(list(CX.correr_checklist("cli", pid)))
    assert r["binario"]["estado"] == CX.HECHO
    assert r["version"]["estado"] in (CX.HECHO, CX.PENDIENTE)
    # los requisitos que dependen de NOSOTROS (no del humano) tienen que estar verdes
    assert r["no_interactivo"]["estado"] == CX.HECHO, r["no_interactivo"]["detalle"]
    assert r["permisos"]["estado"] == CX.HECHO, r["permisos"]["detalle"]
    assert r["cwd"]["estado"] == CX.HECHO


def test_requisitos_cli_son_los_ocho_del_mandato():
    assert [r[0] for r in CX.REQUISITOS_CLI] == [
        "binario", "version", "sesion", "no_interactivo",
        "permisos", "cwd", "plan", "concurrencia"]


def test_requisitos_api_son_los_siete_del_mandato():
    assert [r[0] for r in CX.REQUISITOS_API] == [
        "formato", "viva", "diagnostico", "modelo", "base_url", "streaming", "persistencia"]


# ══════════════════════════════════════════════════════════════════════════════════
# CONTRATO — vocabulario CERRADO, sin causas inventadas
# ══════════════════════════════════════════════════════════════════════════════════
def test_causa_fuera_del_vocabulario_del_motor_revienta():
    with pytest.raises(ValueError):
        CX._req("x", "X", CX.ROTO, causa="me_lo_invente")


def test_todo_requisito_no_verde_trae_causa_o_es_pendiente(peer, cliente_db):
    url = peer(models_status=401)
    _guardar(cliente_db, "groq", "gsk_" + "x" * 40)
    for r in CX._checklist_api("groq", owner=cliente_db["uid"],
                               get_conn=cliente_db["get_conn"], base_url=url):
        if r["estado"] == CX.ROTO:
            assert r["causa"] in MV.CAUSAS, r
            assert r["detalle"], r          # ningún rojo mudo
        else:
            assert r["causa"] is None


def test_slug_ida_y_vuelta():
    assert CX.slug_de("api", "groq") == "api.groq"
    assert CX.resolver_slug("api.groq") == ("api", "groq")
    assert CX.resolver_slug("groq") == ("api", "groq")
    assert CX.resolver_slug("claude_cli") == ("cli", "claude_cli")
    assert CX.resolver_slug("context7") == ("cuenta", "context7")
    assert CX.resolver_slug("belts/x.mcp.json#srv") == ("mcp", "belts/x.mcp.json#srv")


# ══════════════════════════════════════════════════════════════════════════════════
# STREAM SSE — batch en paralelo, latido y cierre SIEMPRE
# ══════════════════════════════════════════════════════════════════════════════════
def _eventos(gen):
    out = []
    for chunk in gen:
        for linea in chunk.strip().splitlines():
            if linea.startswith("data: "):
                out.append(json.loads(linea[6:]))
    return out


def test_stream_batch_paralelo_cierra_todas_las_filas(peer, cliente_db, monkeypatch):
    monkeypatch.setenv("PUPPET_CLAUDE_BIN", "/no/existe/claude-de-mentira")
    from cli_brain import detect
    detect.invalidate_cache()
    evs = _eventos(CX.stream_checklist(["cli.claude_cli", "api.groq"],
                                       owner=cliente_db["uid"],
                                       get_conn=cliente_db["get_conn"]))
    detect.invalidate_cache()
    tipos = [e["type"] for e in evs]
    assert tipos[0] == "inicio" and evs[0]["total"] == 2
    assert evs[0]["paralelo"] >= 2                       # de verdad en paralelo
    cerradas = {e["slug"]: e for e in evs if e["type"] == "fila.cerrada"}
    assert set(cerradas) == {"cli.claude_cli", "api.groq"}
    assert tipos[-1] == "cerrado" and evs[-1]["ok"] is True
    # cada fila emitió TODOS sus requisitos
    por_fila = {}
    for e in evs:
        if e["type"] == "requisito.resultado":
            por_fila.setdefault(e["slug"], []).append(e["id"])
    assert len(por_fila["cli.claude_cli"]) == 8
    assert len(por_fila["api.groq"]) == 7
    # y anunció cuál estaba probando (el latido con nombre propio)
    assert any(e["type"] == "requisito.probando" for e in evs)


def test_stream_sin_filas_cierra_igual():
    evs = _eventos(CX.stream_checklist([], owner=None))
    assert evs[-1]["type"] == "cerrado" and evs[-1]["ok"] is False


# ══════════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════════
def _app(get_conn=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(CX.build_conexiones_router(get_conn=get_conn))
    return TestClient(app)


def test_router_lista_y_conteo(cliente_db):
    c = _app(cliente_db["get_conn"])
    d = c.get("/v1/conexiones").json()
    assert d["conteo"]["total"] == len(d["filas"])
    slugs = {f["slug"] for f in d["filas"]}
    assert "cli.claude_cli" in slugs and "api.groq" in slugs
    # sin sesión (sin Bearer) las de API salen ⚪ sin configurar, no verdes
    api = next(f for f in d["filas"] if f["slug"] == "api.groq")
    assert api["estado"] in (MV.NO_CONFIGURADO, MV.DETECTADO)


def test_router_requisitos_por_familia():
    c = _app()
    d = c.get("/v1/conexiones/requisitos/api").json()
    assert [r["id"] for r in d["requisitos"]] == [r[0] for r in CX.REQUISITOS_API]
    assert all(r["ayuda"] for r in d["requisitos"])     # el "?" de cada requisito
    assert c.get("/v1/conexiones/requisitos/no_existe").status_code == 422


def test_router_key_sin_sesion_lo_dice(cliente_db):
    c = _app(cliente_db["get_conn"])
    d = c.post("/v1/conexiones/key", json={"provider": "groq", "secret": "gsk_x"}).json()
    assert d["ok"] is False and d["causa"] == MV.SIN_SESION


def test_router_key_control_bloquea_ssrf_y_no_persiste(cliente_db, monkeypatch):
    monkeypatch.setenv("ALEPH_ROLE", "control")
    monkeypatch.setattr(MV._url_guard.config, "ALLOW_PRIVATE_TARGETS", False)
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: cliente_db["uid"])

    def no_debe_abrir(*_args, **_kwargs):
        raise AssertionError("el control plane no debe abrir loopback")

    monkeypatch.setattr(MV._url_guard._PUBLIC_OPENER, "open", no_debe_abrir)
    c = _app(cliente_db["get_conn"])
    r = c.post("/v1/conexiones/key", headers={"Authorization": "Bearer test"}, json={
        "provider": "miendpoint", "secret": "secreto-1234",
        "base_url": "http://127.0.0.1:6379/v1",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["guardada"] is False
    from app.phase1 import repo
    # La fixture de persistencia es SQLite de cliente; volver al rol de la fixture sólo
    # para leerla después de haber ejercitado el request en rol control.
    monkeypatch.setenv("ALEPH_ROLE", "client")
    conn = cliente_db["get_conn"]()
    try:
        assert repo.get_key(conn, cliente_db["uid"], "miendpoint") is None
        assert repo.get_key(conn, cliente_db["uid"],
                            "miendpoint" + CX.SUFIJO_BASE) is None
    finally:
        conn.close()


def test_router_checklist_sse(cliente_db):
    c = _app(cliente_db["get_conn"])
    r = c.post("/v1/conexiones/checklist", json={"slugs": ["api.groq"]})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    evs = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    assert evs[0]["type"] == "inicio"
    assert evs[-1]["type"] == "cerrado"


# ══════════════════════════════════════════════════════════════════════════════════
# LA LÁPIDA (CONTRACT-CONEXION-v1 §4) — DOS ACCIONES, NO UNA
# ══════════════════════════════════════════════════════════════════════════════════
def _con_sesion(cliente_db, monkeypatch):
    """El router saca el owner de la sesión (anti-IDOR), nunca del body. Acá se fija."""
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: cliente_db["uid"])
    return _app(cliente_db["get_conn"])


def test_desconectar_apaga_y_NO_TOCA_LA_LLAVE(cliente_db, monkeypatch):
    from app.phase1 import conexiones_repo as CR
    conn = cliente_db["get_conn"]()
    CR.upsert_entidad(conn, user_id=cliente_db["uid"], entity_id="exa",
                      credencial_ref="exa", command="uvx")
    conn.close()

    c = _con_sesion(cliente_db, monkeypatch)
    d = c.post("/v1/conexiones/exa/desconectar").json()
    assert d["ok"] is True and d["habilitado"] is False
    assert d["credencial_ref"] == "exa", "desconectar NO es borrar la llave"

    assert c.get("/v1/conexiones/apagadas").json()["apagadas"] == ["exa"]


def test_reconectar_es_un_click(cliente_db, monkeypatch):
    from app.phase1 import conexiones_repo as CR
    conn = cliente_db["get_conn"]()
    CR.upsert_entidad(conn, user_id=cliente_db["uid"], entity_id="exa", command="uvx")
    conn.close()

    c = _con_sesion(cliente_db, monkeypatch)
    c.post("/v1/conexiones/exa/desconectar")
    assert c.post("/v1/conexiones/exa/reconectar").json()["habilitado"] is True
    assert c.get("/v1/conexiones/apagadas").json()["apagadas"] == []


def test_desconectar_lo_no_registrado_da_404_CON_MOTIVO(cliente_db, monkeypatch):
    """FALLO VISIBLE, JAMÁS MUDO. Pasa si el belt se equipó DESPUÉS del backfill.
    Inventarle una fila sería fabricar una lápida para algo que el registro no conoce."""
    c = _con_sesion(cliente_db, monkeypatch)
    r = c.post("/v1/conexiones/fantasma/desconectar")
    assert r.status_code == 404
    assert "registro" in r.json()["detail"]


def test_la_lapida_exige_sesion(cliente_db):
    c = _app(cliente_db["get_conn"])          # sin _owner_from_session parcheado
    assert c.post("/v1/conexiones/exa/desconectar").status_code == 401
    assert c.get("/v1/conexiones/apagadas").json()["apagadas"] == []


def test_apagadas_falla_ABIERTO_si_el_registro_no_se_puede_leer(cliente_db, monkeypatch):
    """Equivocarse hacia «todo conectado» es cosmético; hacia «apagada» mandaría al
    usuario a reconectar algo que ya andaba."""
    def revienta():
        raise RuntimeError("la DB no está")
    c = _app(revienta)
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: cliente_db["uid"])
    assert c.get("/v1/conexiones/apagadas").json()["apagadas"] == []


def test_la_fila_MCP_del_listado_trae_el_flag_apagada(cliente_db, monkeypatch):
    """El front pinta GRIS con esto. Sin el flag no hay forma de distinguir «apagada» de
    «nunca probada», y las dos son ⚪ — pero sólo una tiene botón de reconectar."""
    from app.phase1 import conexiones_repo as CR
    conn = cliente_db["get_conn"]()
    CR.upsert_entidad(conn, user_id=cliente_db["uid"], entity_id="loquesea")
    CR.desconectar(conn, cliente_db["uid"], "loquesea")
    conn.close()
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: cliente_db["uid"])
    c = _app(cliente_db["get_conn"])
    filas = c.get("/v1/conexiones?mcp=b.mcp.json%23loquesea").json()["filas"]
    fila = next(f for f in filas if f["ref"].endswith("#loquesea"))
    assert fila["apagada"] is True


def test_desconectar_NO_BORRA_LOS_VEREDICTOS_DE_NADIE(cliente_db, monkeypatch):
    """EL BUG QUE SE ESCAPÓ A PRODUCCIÓN, ahora atajado.

    La primera versión llamaba `MV.invalidar_cache()` después de apagar. Esa función hace
    `_CACHE.clear()` — borra el veredicto de TODAS las piezas y lo persiste. Resultado
    medido en la vara: un click en [Desconectar] dejó las 48 conexiones en gris, sin
    evidencia y sin manera de recuperarla; hubo que volver a probarlas a mano.

    Desconectar cambia el PERMISO, no si el servidor anda. El veredicto sigue siendo el
    registro fiel de la última medición (§5: caduca por causa, no por acciones que no
    tocan la config).
    """
    from app.phase1 import conexiones_repo as CR
    conn = cliente_db["get_conn"]()
    CR.upsert_entidad(conn, user_id=cliente_db["uid"], entity_id="exa", command="uvx")
    conn.close()

    # dos veredictos guardados: el de la que vamos a apagar y el de una TERCERA sin relación
    MV._cache_put("mcp\x1fb.mcp.json#exa\x1fnadie", {"estado": MV.PROBADO, "ts": 1.0})
    MV._cache_put("cli\x1fclaude_cli\x1fnadie", {"estado": MV.PROBADO, "ts": 1.0})
    antes = len(MV._CACHE)
    assert antes >= 2

    c = _con_sesion(cliente_db, monkeypatch)
    assert c.post("/v1/conexiones/exa/desconectar").json()["ok"] is True

    assert len(MV._CACHE) == antes, (
        f"desconectar borró veredictos: quedaban {antes}, quedan {len(MV._CACHE)}")
    assert MV._CACHE.get("cli\x1fclaude_cli\x1fnadie"), (
        "borró el veredicto de una pieza que no tiene NADA que ver con la que se apagó")


def test_reconectar_tampoco_borra_veredictos(cliente_db, monkeypatch):
    from app.phase1 import conexiones_repo as CR
    conn = cliente_db["get_conn"]()
    CR.upsert_entidad(conn, user_id=cliente_db["uid"], entity_id="exa", command="uvx")
    conn.close()
    MV._cache_put("cli\x1fclaude_cli\x1fnadie", {"estado": MV.PROBADO, "ts": 1.0})
    antes = len(MV._CACHE)
    c = _con_sesion(cliente_db, monkeypatch)
    c.post("/v1/conexiones/exa/desconectar")
    c.post("/v1/conexiones/exa/reconectar")
    assert len(MV._CACHE) == antes


def test_borrar_la_llave_olvida_SOLO_lo_de_esa_credencial(cliente_db, monkeypatch):
    """La misma familia de bug que el de arriba, en la acción de al lado. Borrar una llave
    SÍ cambia si ese servicio anda —a diferencia de desconectar— pero afecta a las piezas
    de ESE provider y a ninguna otra."""
    uid = cliente_db["uid"]
    MV._cache_put(f"api\x1fexa\x1f{uid}", {"estado": MV.PROBADO, "ts": 1.0})
    MV._cache_put(f"mcp\x1fb.mcp.json#exa\x1f{uid}", {"estado": MV.PROBADO, "ts": 1.0})
    MV._cache_put(f"mcp\x1fb.mcp.json#zotero\x1f{uid}", {"estado": MV.PROBADO, "ts": 1.0})
    MV._cache_put(f"cli\x1fclaude_cli\x1f{uid}", {"estado": MV.PROBADO, "ts": 1.0})

    c = _con_sesion(cliente_db, monkeypatch)
    d = c.request("DELETE", "/v1/conexiones/key/exa").json()
    assert d["veredictos_olvidados"] == 2, "los dos de exa: el api y el mcp"

    assert MV._CACHE.get(f"mcp\x1fb.mcp.json#zotero\x1f{uid}"), "zotero no tenía nada que ver"
    assert MV._CACHE.get(f"cli\x1fclaude_cli\x1f{uid}"), "el CLI menos todavía"
    assert not MV._CACHE.get(f"api\x1fexa\x1f{uid}")
    assert not MV._CACHE.get(f"mcp\x1fb.mcp.json#exa\x1f{uid}")


def test_olvidar_por_credencial_no_cruza_usuarios(cliente_db):
    MV._cache_put("api\x1fexa\x1fyo", {"estado": MV.PROBADO, "ts": 1.0})
    MV._cache_put("api\x1fexa\x1fotro", {"estado": MV.PROBADO, "ts": 1.0})
    assert MV.olvidar_por_credencial("exa", owner="yo") == 1
    assert MV._CACHE.get("api\x1fexa\x1fotro"), "la llave de uno no toca el veredicto de otro"


def test_guardar_una_llave_levanta_la_lapida_END_TO_END(cliente_db, monkeypatch):
    """§4 · el punto único visto desde el endpoint: `agregar_key` -> `_guardar` ->
    `_espejar_en_el_registro` -> lápida levantada. Vale para TODO servicio con credencial,
    hoy y el que se agregue mañana, porque la regla vive en el lugar donde se registra la
    intención y no en cada conector."""
    from app.phase1 import conexiones_repo as CR
    uid = cliente_db["uid"]
    conn = cliente_db["get_conn"]()
    CR.upsert_entidad(conn, user_id=uid, entity_id="maritime",
                      credencial_ref="globalfishingwatch")
    CR.desconectar(conn, uid, "maritime")
    conn.close()

    c = _con_sesion(cliente_db, monkeypatch)
    assert c.get("/v1/conexiones/apagadas").json()["apagadas"] == ["maritime"]

    d = c.post("/v1/conexiones/key",
               json={"provider": "globalfishingwatch", "secret": "una-llave"}).json()
    assert d["guardada"] is True

    assert c.get("/v1/conexiones/apagadas").json()["apagadas"] == [], (
        "guardar la llave tenía que levantar la lápida de maritime")


def test_el_espejo_sigue_siendo_NO_FATAL_aunque_falle_la_lapida(cliente_db, monkeypatch):
    """La condición que hace verdadera la convivencia: si el registro falla, la llave del
    usuario se guarda IGUAL. Un observador que puede tumbar lo que observa no es un
    observador."""
    from app.phase1 import conexiones_repo as CR
    monkeypatch.setattr(CR, "reconectar_por_credencial",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("registro roto")))
    c = _con_sesion(cliente_db, monkeypatch)
    d = c.post("/v1/conexiones/key", json={"provider": "exa", "secret": "x"}).json()
    assert d["guardada"] is True, "la llave se guarda aunque el registro explote"


def test_medicion_devuelve_las_dos_columnas_sin_interpretarlas(cliente_db, monkeypatch):
    """v5 · el backend entrega `conexion` y `credencial` tal cual. NO las traduce: el
    vocabulario del semáforo vive en un solo lugar (el front), y partirlo entre dos capas
    es cómo se termina con dos textos para el mismo estado."""
    from app.phase1 import conexiones_repo as CR
    uid = cliente_db["uid"]
    conn = cliente_db["get_conn"]()
    CR.upsert_entidad(conn, user_id=uid, entity_id="exa",
                      conexion={"estado": "viva", "causa": None, "tool_usada": "web_search_exa"},
                      credencial={"estado": "verde", "tool_prueba": "web_search_exa"})
    CR.upsert_entidad(conn, user_id=uid, entity_id="sin_medir_todavia")
    conn.close()

    c = _con_sesion(cliente_db, monkeypatch)
    m = c.get("/v1/conexiones/medicion").json()["mediciones"]
    assert m["exa"]["conexion"]["estado"] == "viva"
    assert m["exa"]["credencial"]["tool_prueba"] == "web_search_exa"
    assert "sin_medir_todavia" not in m, "sin medición no viaja: la card queda como hoy"


# ══════════════════════════════════════════════════════════════════════════════════
# LAS FUENTES DEL ADAPTADOR · las cinco juntas, sin un solo valor adentro
# ══════════════════════════════════════════════════════════════════════════════════

def test_fuentes_junta_las_cinco_en_una_sola_lectura(cliente_db, monkeypatch):
    """La superficie de conectores no decide: DERIVA. Y deriva de cinco fuentes que tienen
    que verse en el MISMO instante — cruzarlas es lo que delata que un belt pide una llave
    que la ficha no declara, y cruzar lecturas de momentos distintos inventa contradicciones
    que no existen."""
    from app.phase1 import conexiones_repo as CR
    from app.phase1 import repo as _repo
    uid = cliente_db["uid"]
    conn = cliente_db["get_conn"]()
    CR.upsert_entidad(conn, user_id=uid, entity_id="exa",
                      conexion={"estado": "viva", "causa": None, "tool_usada": "web_search_exa"},
                      credencial={"estado": "verde", "tool_prueba": "web_search_exa"},
                      env_template={"EXA_API_KEY": "${EXA_API_KEY}"},
                      credencial_ref="exa")
    _repo.upsert_key(conn, user_id=uid, provider="exa",
                     secret="una-llave-que-no-puede-salir-de-la-base")
    conn.close()

    c = _con_sesion(cliente_db, monkeypatch)
    d = c.get("/v1/conexiones/fuentes").json()
    assert d["leido"] is True, "FALLO VISIBLE: la superficie tiene que saber si leyó o no"

    e = d["entidades"]["exa"]
    assert e["medicion"]["conexion"]["estado"] == "viva", "1 · el registro"
    assert e["ficha"] and e["ficha"]["auth_method"], "2 · la ficha del catálogo"
    assert e["belt"] and "EXA_API_KEY" in e["belt"]["env"], "3 · el belt, con sus variables"
    assert "exa" in d["vault"], "4 · el vault: qué llaves entregó ya"
    assert d["alias"], "5 · los alias del catálogo, para resolver variable → provider"
    assert e["env_declarado"] == {"EXA_API_KEY": ""}, "el env declarado, sólo nombres"
    assert e["tuvo_verde_previo"] is True, "y si anduvo alguna vez (primer boot frío ≠ roto)"


def test_fuentes_NO_FILTRA_UN_SOLO_VALOR(cliente_db, monkeypatch):
    """⚠️ NOMBRES Y REFERENCIAS, JAMÁS VALORES — §2 del registro, extendida al catálogo.

    Y el matiz que hace que sirva: un valor literal en el manifest NO se omite, se REEMPLAZA
    por un marcador. Así el adaptador puede delatar «acá hay un secreto en claro» sin que el
    secreto salga de acá — que es exactamente lo que hay que poder hacer con uno filtrado.
    """
    from app.phase1 import repo as _repo
    uid = cliente_db["uid"]
    conn = cliente_db["get_conn"]()
    _repo.upsert_key(conn, user_id=uid, provider="exa",
                     secret="SECRETO-QUE-NO-PUEDE-VIAJAR-JAMAS")
    conn.close()

    c = _con_sesion(cliente_db, monkeypatch)
    crudo = c.get("/v1/conexiones/fuentes").text
    assert "SECRETO-QUE-NO-PUEDE-VIAJAR-JAMAS" not in crudo, "la llave NO viaja"
    d = c.get("/v1/conexiones/fuentes").json()
    assert set(d["vault"]["exa"].keys()) == {"desde"}, \
        "del vault viaja el provider y la FECHA (insumo de `medicionRancia`), nada más"

    # Y la mitad del marcador, sobre datos propios: una referencia pasa, un literal no.
    assert CX._sin_valores({"A": "${A}", "B": "Bearer abc123"}) == \
        {"A": "${A}", "B": CX._LITERAL}, \
        "una referencia viaja tal cual; un literal se marca sin viajar"


def test_fuentes_el_residuo_VIAJA_para_que_el_adaptador_lo_nombre(cliente_db, monkeypatch):
    """Una fila que nadie midió nunca es RESIDUO —basura de una prueba—, y el adaptador
    tiene una regla que la nombra y ofrece limpiarla. Filtrarla acá dejaría esa regla sin a
    quién aplicarse y el residuo seguiría contando como una conexión caída."""
    from app.phase1 import conexiones_repo as CR
    conn = cliente_db["get_conn"]()
    CR.upsert_entidad(conn, user_id=cliente_db["uid"], entity_id="basura-de-prueba")
    conn.close()
    d = _con_sesion(cliente_db, monkeypatch).get("/v1/conexiones/fuentes").json()
    assert "basura-de-prueba" in d["entidades"], "la fila sin medición viaja igual"
    assert d["entidades"]["basura-de-prueba"]["medicion"] == {"conexion": None, "credencial": None}


def test_fuentes_los_alias_son_LOS_MISMOS_que_inyecta_el_assembler():
    """Si la superficie usara otra tabla, podría decir «falta tu llave» sobre una credencial
    que el assembler sí encuentra: la contradicción entre fuentes, pero adentro de casa."""
    import importlib.util
    ruta = CX._raiz_de_recursos() / "platform" / "assembler" / "recipe_assembler.py"
    spec = importlib.util.spec_from_file_location("_ra_alias", ruta)
    ra = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ruta.parent))
    spec.loader.exec_module(ra)

    del_endpoint = CX._alias_de_env()
    for variable, provider in del_endpoint.items():
        assert ra._ENV_VAR_TO_PROVIDER.get(variable) == provider, \
            f"{variable} resuelve distinto en la superficie y en la inyección"
    assert ra._ALIAS_ORIGEN == "catalogo", \
        "el assembler tiene que estar leyendo el catálogo, no su respaldo literal"


def test_fuentes_falla_ABIERTO(cliente_db, monkeypatch):
    """Igual que sus hermanas, y con una diferencia que importa: `leido: False`. Sin datos la
    superficie muestra lo que ya sabe, pero SABE que no leyó — no pinta 42 piezas sin ficha
    como si el catálogo no existiera (FALLO VISIBLE, JAMÁS MUDO)."""
    def revienta():
        raise RuntimeError("la DB no está")
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: cliente_db["uid"])
    d = _app(revienta).get("/v1/conexiones/fuentes").json()
    assert d["entidades"] == {} and d["leido"] is False

    # Sin sesión tampoco filtra nada — y ojo con la diferencia: `leido: False` acá no
    # significa «la DB explotó», significa «no hay a quién leerle». Las dos son honestas y
    # las dos dejan a la superficie sin inventar.
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: None)
    sin_sesion = _app(cliente_db["get_conn"]).get("/v1/conexiones/fuentes").json()
    assert sin_sesion["entidades"] == {} and sin_sesion["leido"] is False
    assert sin_sesion["vault"] == {}, "y el vault de nadie está vacío, no es el de otro"


def test_medicion_falla_ABIERTO(cliente_db, monkeypatch):
    """Igual que `/apagadas`: sin datos la card queda como está. El error de no mostrar una
    medición es cosmético; el de inventarla, no."""
    def revienta():
        raise RuntimeError("la DB no está")
    monkeypatch.setattr(MV, "_owner_from_session", lambda _h: cliente_db["uid"])
    assert _app(revienta).get("/v1/conexiones/medicion").json() == {"mediciones": {}}
    assert _app(cliente_db["get_conn"]).get("/v1/conexiones/medicion").json() == {"mediciones": {}}, \
        "sin sesión tampoco filtra nada"


# ══════════════════════════════════════════════════════════════════════════════════
# EL RECABLEO AL PUENTE (sesión 2) · `_checklist_mcp` no puede notar el transporte
# ══════════════════════════════════════════════════════════════════════════════════
# `_checklist_mcp` no toca el cliente: lee la EVIDENCIA que `MV.probar` le devuelve. Por eso
# el recableo se prueba acá donde importa —en las filas que el usuario ve—, alimentando el
# checklist con la evidencia que produce cada transporte para LA MISMA falla y exigiendo que
# las cuatro filas salgan idénticas. Si el puente cambia una sola, es un bug del recableo.

def _filas(monkeypatch, evidencia: dict, estado=MV.ROTO, causa=MV.ERROR_UPSTREAM):
    """Corre `_checklist_mcp` con un `MV.probar` sustituido por un resultado fijo."""
    def _falso(*_a, **_k):
        return {"tipo": MV.MCP, "ref": "belt#srv", "estado": estado,
                "causa": causa if estado == MV.ROTO else None, "evidencia": evidencia}
    monkeypatch.setattr(CX.MV, "probar", _falso)
    return list(CX._checklist_mcp("belt-x.mcp.json#srv", owner="u1"))


#: La MISMA falla —el proceso arranca y no completa el saludo— vista por cada transporte.
#: Los dos textos son los medidos, no inventados.
_EV_VIEJO = {
    "detail": "el proceso arrancó pero no respondió al saludo initialize de MCP",
    "stderr": "ModuleNotFoundError: No module named 'pandas'",
    "exit_code": 1, "transport": "stdio", "command": "python3", "latencia_ms": 120,
}
_EV_PUENTE = {
    "detail": "el proceso arrancó pero no respondió al saludo initialize de MCP "
              "(no pude iniciar el proceso MCP por el SDK: MCPError: Connection closed)",
    "stderr": "ModuleNotFoundError: No module named 'pandas'",
    "exit_code": None,
    "exit_code_fuente": "no expuesto por el transporte del SDK",
    "murio": True, "transporte": "sdk-stdio",
    "transport": "stdio", "command": "python3", "latencia_ms": 120,
}


def test_checklist_mcp_da_las_mismas_filas_por_los_dos_transportes(monkeypatch):
    viejo = _filas(monkeypatch, _EV_VIEJO)
    puente = _filas(monkeypatch, _EV_PUENTE)
    assert len(viejo) == len(puente) == 4
    for a, b in zip(viejo, puente):
        assert a["id"] == b["id"], "cambió el orden o el id de un requisito"
        assert a["estado"] == b["estado"], f"{a['id']}: {a['estado']} vs {b['estado']}"
        assert a.get("causa") == b.get("causa"), a["id"]


def test_el_stderr_del_hijo_llega_hasta_la_fila(monkeypatch):
    """Los diagnósticos viven del stderr: si el puente lo perdiera en el camino, la fila
    quedaría sin el único texto que dice QUÉ se rompió adentro del server."""
    filas = _filas(monkeypatch, _EV_PUENTE)
    saludo = next(f for f in filas if f["estado"] == CX.ROTO)
    ev = saludo.get("evidencia") or {}
    assert "ModuleNotFoundError" in json.dumps(ev), "el stderr no llegó a la fila"


def test_el_exit_code_ausente_no_degrada_ninguna_fila(monkeypatch):
    """`exit_code=None` es «no medible», no «éxito» ni «exit 0». Ninguna fila puede
    ponerse verde ni cambiar de causa por su ausencia."""
    sin_code = {k: v for k, v in _EV_PUENTE.items() if k != "exit_code"}
    filas = _filas(monkeypatch, {**sin_code, "exit_code": None})
    con_code = _filas(monkeypatch, {**sin_code, "exit_code": 1})
    assert [f["estado"] for f in filas] == [f["estado"] for f in con_code]
    assert not any(f["estado"] == CX.HECHO for f in filas[1:3]), (
        "una fila se puso verde sin evidencia de saludo")


# ══════════════════════════════════════════════════════════════════════════════════
# [F7 · A · EL TAPÓN] LA PUERTA QUE SALTEABA LA VALIDACIÓN, Y EL «CONECTADO» QUE MENTÍA
#
# MEDIDO el 2026-08-06 contra la app instalada: `POST /v1/keys` guardaba una llave basura
# con HTTP 200 —sin forma, sin validador, sin prueba dura, sin sembrar el motor— y esa
# llave aparecía en Modelos con `hay_llave:true`, el selector la OFRECÍA como cerebro en el
# Cuarto y en la Sala, y el llavero la marcaba `verified:true`. Cuatro superficies mintiendo
# por una puerta.
# ══════════════════════════════════════════════════════════════════════════════════
def test_conectado_exige_veredicto_no_solo_llave_guardada(peer, cliente_db, monkeypatch):
    """Una llave guardada y NUNCA probada no es un modelo conectado — y por eso el selector
    no la puede ofrecer como cerebro."""
    from app.phase1 import centro_modelos as CM

    def _fila(estado, hay_llave):
        base = {"filas": [{"slug": "api.groq", "familia": "api", "ref": "groq",
                           "label": "Groq", "estado": estado, "hay_llave": hay_llave,
                           "local": False}]}
        return CM._anotar_conectados(base, {"providers": {}, "service": {}, "actual": False})

    probada = _fila(MV.PROBADO, True)["filas"][0]
    guardada = _fila(MV.DETECTADO, True)["filas"][0]
    sin_llave = _fila(MV.NO_CONFIGURADO, False)["filas"][0]

    assert probada["conectado"] is True, "probado + llave = conectado"
    assert guardada["conectado"] is False, \
        "★ una llave guardada y sin veredicto NO es 'conectado': ése es el verde falso"
    assert sin_llave["conectado"] is False
    # y `hay_llave` sigue viajando intacto: la ADUANA de F4c deriva de ÉL, no de `conectado`,
    # así que un modelo con llave y sin veredicto queda en «Tus modelos» 🟡, no pidiendo una
    # llave que ya está.
    assert guardada["hay_llave"] is True


def test_v1_keys_delega_en_agregar_key_y_rechaza_la_basura(peer, cliente_db):
    """La puerta de Ajustes y brain-setup pasa por el MISMO validador que Modelos."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1.router import build_phase1_router

    app = FastAPI()
    app.include_router(build_phase1_router(get_conn=cliente_db["get_conn"],
                                           events_dir=lambda: Path(".")))
    c = TestClient(app, raise_server_exceptions=False)
    from app.phase1 import repo
    tok = repo.mint_session(cliente_db["uid"])
    H = {"Authorization": "Bearer " + tok}

    # forma equivocada → 422, y NO se guarda
    r = c.post("/v1/keys", headers=H, json={"user_id": cliente_db["uid"],
                                            "provider": "groq", "secret": "basura-total"})
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["causa"] == MV.KEY_INVALIDA and d["error"] == "key_rechazada"
    conn = cliente_db["get_conn"]()
    try:
        assert repo.get_key(conn, cliente_db["uid"], "groq") is None, \
            "★ una llave rechazada NO puede quedar en el vault"
    finally:
        conn.close()


def test_el_llavero_marca_verified_solo_con_veredicto_del_motor(peer, cliente_db):
    """MEDIDO: una llave basura salía `verified: True` en el llavero de Ajustes. El flag
    salía de si el conector es validable EN PRINCIPIO (`validate.soft` de su ficha), que
    responde «¿se podría validar?» y no «¿se validó?»."""
    from pathlib import Path
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1.router import build_phase1_router
    from app.phase1 import repo

    app = FastAPI()
    app.include_router(build_phase1_router(get_conn=cliente_db["get_conn"],
                                           events_dir=lambda: Path(".")))
    c = TestClient(app, raise_server_exceptions=False)
    H = {"Authorization": "Bearer " + repo.mint_session(cliente_db["uid"])}

    # llave metida POR ATRÁS (sin veredicto): es lo que dejaba la puerta vieja
    _guardar(cliente_db, "groq", "gsk_" + "n" * 40)
    fila = [k for k in c.get(f"/v1/users/{cliente_db['uid']}/keys", headers=H).json()["keys"]
            if k["provider"] == "groq"][0]
    assert fila["verified"] is False, "★ sin veredicto NO hay verde, aunque la fila exista"
    assert fila["medido_en"] is None and fila["estado"] != MV.PROBADO

    # ahora con una prueba REAL contra el peer → el motor corona y el llavero lo refleja
    url = peer()
    CX.agregar_key("groq", "gsk_" + "v" * 40, owner=cliente_db["uid"],
                   get_conn=cliente_db["get_conn"], base_url=url)
    fila = [k for k in c.get(f"/v1/users/{cliente_db['uid']}/keys", headers=H).json()["keys"]
            if k["provider"] == "groq"][0]
    assert fila["verified"] is True and fila["medido_en"], \
        "★ y con veredicto sí — y la fila dice CUÁNDO se midió"
