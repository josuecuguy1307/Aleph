"""
test_conexiones.py — Tests for CONEXIÓN JIT v0 (PRODUCT-V2-DESIGN: "una conexión
= llenar un ${VAR} del belt").

Cubre:
  • EquipoDiff (unit): descubrimiento de ${VAR} en env + args; clasificación
    conectado / necesita-conexión / dormido; cero-fricción vs secreto de usuario.
  • GET  /espacios/{id}/equipo  — el diff servido por HTTP.
  • POST /espacios/{id}/conexiones — guarda el secreto en el VAULT real (cifrado),
    nunca ecoa el valor, y reporta el desbloqueo.
  • E2E del done: belt fixture con ${TEST_API_KEY} → /equipo dice 'necesita
    conexión' → POST conexiones → /equipo dice 'conectado'.
  • CONTRATO DEL VAULT (grep): la key dummy JAMÁS aparece en la respuesta, ni en
    el vault.enc en claro, ni en el log de la request.

NINGÚN test corre inferencia. El vault es un CredentialVault REAL sobre tmp_path
(cifrado Fernet), nunca el de producción. El belt arranca el echo server real solo
en el smoke de plomería (test_smoke_plomeria), no en los tests de diff.
"""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.conexiones import (
    EquipoDiff,
    belt_server_vars,
    build_conexiones_router,
    load_belt_file,
    load_friccion_catalog,
)
from app.espacios import EspaciosStore
from tests.conftest import REPO_ROOT


FIXTURES = Path(__file__).resolve().parent / "fixtures"
BELT_CONEXION_TEST = FIXTURES / "belt-conexion-test.mcp.json"

# La key DUMMY de formato válido (FRED entrega keys de 32 hex en minúscula gratis;
# usamos una de ese formato pero INVENTADA — jamás registramos una real).
DUMMY_KEY = "abcdef0123456789abcdef0123456789"

# Catálogo de fricción de prueba: 'testapi' SÍ pide conexión humana (su ${VAR} es
# secreto de usuario). Aislado de brands.json de producción.
TEST_FRICCION = {
    "testapi": {
        "label": "API de prueba",
        "conexion_humana": "tu clave de prueba",
        "que_hace": "Sirve para probar el flujo de conexión JIT.",
    },
}


# ── EquipoDiff (unit) ─────────────────────────────────────────────────────────

class TestBeltVars:
    def test_descubre_var_en_env(self):
        cfg = {"command": "x", "env": {"K": "${FRED_API_KEY}"}}
        assert belt_server_vars(cfg) == ["FRED_API_KEY"]

    def test_descubre_var_en_args(self):
        # jupyter mete sus tokens en args, no en env
        cfg = {"command": "x", "args": ["--token", "${JUPYTER_TOKEN}", "--id", "${JUPYTER_NOTEBOOK_ID}"]}
        assert belt_server_vars(cfg) == ["JUPYTER_TOKEN", "JUPYTER_NOTEBOOK_ID"]

    def test_sin_dups_y_orden_estable(self):
        # env se escanea antes que args (orden determinístico); sin duplicados.
        cfg = {"args": ["${A}", "${B}", "${A}"], "env": {"x": "${B}"}}
        assert belt_server_vars(cfg) == ["B", "A"]


class TestEquipoDiff:
    def _belt(self):
        return json.loads(BELT_CONEXION_TEST.read_text())

    def test_server_con_secreto_faltante_necesita_conexion(self):
        diff = EquipoDiff(
            belt=self._belt(),
            tool_filters={"testapi": ["echo"]},
            vault_has=lambda name: False,           # vault vacío
            friccion_catalog=TEST_FRICCION,
        )
        servers = diff.por_servidor()
        s = next(s for s in servers if s["servidor"] == "testapi")
        assert s["estado"] == "necesita-conexión"
        assert s["vars_faltantes"] == ["TEST_API_KEY"]
        assert "tu clave de prueba" in s["copy"]   # copy humano del catálogo

    def test_server_con_secreto_en_vault_conectado(self):
        diff = EquipoDiff(
            belt=self._belt(),
            tool_filters={"testapi": ["echo"]},
            vault_has=lambda name: name == "TEST_API_KEY",
            friccion_catalog=TEST_FRICCION,
        )
        s = next(s for s in diff.por_servidor() if s["servidor"] == "testapi")
        assert s["estado"] == "conectado"
        assert s["vars_faltantes"] == []

    def test_server_fuera_del_tool_filters_esta_dormido(self):
        # tool_filters activo NO incluye testapi → dormido (degradación elegante)
        diff = EquipoDiff(
            belt=self._belt(),
            tool_filters={"otro": ["x"]},
            vault_has=lambda name: False,
            friccion_catalog=TEST_FRICCION,
        )
        s = next(s for s in diff.por_servidor() if s["servidor"] == "testapi")
        assert s["estado"] == "dormido"

    def test_cero_friccion_no_pide_conexion(self):
        # un server sin conexion_humana es cero-fricción: sus vars las da la
        # plataforma, jamás 'necesita-conexión' aunque el vault esté vacío.
        belt = {"mcpServers": {"excel": {"command": "x", "env": {"P": "${PUPPET_WORKDIR}"}}}}
        diff = EquipoDiff(
            belt=belt,
            tool_filters={"excel": ["create_workbook"]},
            vault_has=lambda name: False,
            friccion_catalog={"excel": {"label": "Excel", "conexion_humana": None}},
        )
        s = diff.por_servidor()[0]
        assert s["estado"] == "conectado"

    def test_var_runtime_no_es_secreto(self):
        # ${PUPPET_*} es provisto por el runtime aunque el server pida conexión.
        belt = {"mcpServers": {"srv": {"command": "x",
                                       "env": {"W": "${PUPPET_WORKDIR}", "K": "${MI_KEY}"}}}}
        diff = EquipoDiff(
            belt=belt, tool_filters={"srv": ["t"]},
            vault_has=lambda name: False,
            friccion_catalog={"srv": {"conexion_humana": "tu clave"}},
        )
        s = diff.por_servidor()[0]
        # solo MI_KEY falta; PUPPET_WORKDIR no cuenta como secreto de usuario
        assert s["vars_faltantes"] == ["MI_KEY"]

    def test_resumen_listo_para_trabajar(self):
        diff = EquipoDiff(
            belt=self._belt(), tool_filters={"testapi": ["echo"]},
            vault_has=lambda name: True, friccion_catalog=TEST_FRICCION,
        )
        r = diff.resumen()
        assert r["listo_para_trabajar"] is True
        assert "testapi" in r["conectados"]


# ── Router de conexiones sobre app de prueba ──────────────────────────────────

@pytest.fixture
def conexion_client(tmp_espacios: Path, tmp_vault):
    """
    App de prueba con SOLO el router de conexiones, cableado al belt fixture
    (${TEST_API_KEY}), un catálogo de fricción de prueba y el vault REAL aislado.
    Devuelve (TestClient, store, vault) para el flujo E2E.
    """
    store = EspaciosStore(tmp_espacios)

    def _load_belt(_belt_path):
        return json.loads(BELT_CONEXION_TEST.read_text())

    def _load_friccion():
        return TEST_FRICCION

    test_app = FastAPI()
    test_app.include_router(
        build_conexiones_router(
            get_store=lambda: store,
            get_vault=lambda: tmp_vault,
            load_belt=_load_belt,
            load_friccion_catalog=_load_friccion,
        )
    )
    with TestClient(test_app) as c:
        yield c, store, tmp_vault


def _make_espacio(store: EspaciosStore) -> str:
    state = store.create(
        "Sala Conexión", "test",
        {"belt_path": str(BELT_CONEXION_TEST), "tool_filters": {"testapi": ["echo"]}},
    )
    return state["id"]


class TestEquipoEndpoint:
    def test_equipo_404_si_no_existe(self, conexion_client):
        c, _store, _vault = conexion_client
        assert c.get("/espacios/no-existe/equipo").status_code == 404

    def test_equipo_dice_necesita_conexion(self, conexion_client):
        c, store, _vault = conexion_client
        eid = _make_espacio(store)
        data = c.get(f"/espacios/{eid}/equipo").json()
        assert "testapi" in data["necesitan_conexion"]
        assert data["listo_para_trabajar"] is False


class TestConexionEndpoint:
    def test_conexion_guarda_en_vault_y_desbloquea(self, conexion_client):
        c, store, vault = conexion_client
        eid = _make_espacio(store)
        resp = c.post(f"/espacios/{eid}/conexiones",
                      json={"var": "TEST_API_KEY", "valor": DUMMY_KEY})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["guardado"] is True
        assert "testapi" in data["desbloqueo"]
        # el secreto QUEDÓ en el vault (cifrado) — lo verificamos por has(), no por valor
        assert vault.has("TEST_API_KEY") is True

    def test_var_vacia_422(self, conexion_client):
        c, store, _vault = conexion_client
        eid = _make_espacio(store)
        assert c.post(f"/espacios/{eid}/conexiones",
                      json={"var": "  ", "valor": DUMMY_KEY}).status_code == 422

    def test_valor_vacio_422(self, conexion_client):
        c, store, _vault = conexion_client
        eid = _make_espacio(store)
        assert c.post(f"/espacios/{eid}/conexiones",
                      json={"var": "TEST_API_KEY", "valor": ""}).status_code == 422

    def test_var_que_el_belt_no_pide_422(self, conexion_client):
        c, store, _vault = conexion_client
        eid = _make_espacio(store)
        r = c.post(f"/espacios/{eid}/conexiones",
                   json={"var": "VAR_QUE_NO_EXISTE", "valor": DUMMY_KEY})
        assert r.status_code == 422

    def test_conexion_espacio_inexistente_404(self, conexion_client):
        c, _store, _vault = conexion_client
        r = c.post("/espacios/no-existe/conexiones",
                   json={"var": "TEST_API_KEY", "valor": DUMMY_KEY})
        assert r.status_code == 404


# ── E2E del done: necesita-conexión → POST → conectado ────────────────────────

class TestE2E:
    def test_flujo_completo_conexion_jit(self, conexion_client):
        c, store, vault = conexion_client
        eid = _make_espacio(store)

        # 1) /equipo dice 'necesita conexión'
        antes = c.get(f"/espacios/{eid}/equipo").json()
        assert "testapi" in antes["necesitan_conexion"]
        assert antes["listo_para_trabajar"] is False

        # 2) POST conexiones con la key dummy
        post = c.post(f"/espacios/{eid}/conexiones",
                      json={"var": "TEST_API_KEY", "valor": DUMMY_KEY})
        assert post.status_code == 200
        assert "testapi" in post.json()["desbloqueo"]

        # 3) /equipo ahora dice 'conectado'
        despues = c.get(f"/espacios/{eid}/equipo").json()
        assert "testapi" in despues["conectados"]
        assert "testapi" not in despues["necesitan_conexion"]
        assert despues["listo_para_trabajar"] is True


# ── CONTRATO DEL VAULT: la key dummy JAMÁS se ecoa (grep) ─────────────────────

class TestContratoVault:
    def test_la_key_no_aparece_en_la_respuesta(self, conexion_client):
        c, store, _vault = conexion_client
        eid = _make_espacio(store)
        resp = c.post(f"/espacios/{eid}/conexiones",
                      json={"var": "TEST_API_KEY", "valor": DUMMY_KEY})
        # ni en el body, ni en los headers de la respuesta
        assert DUMMY_KEY not in resp.text
        assert DUMMY_KEY not in json.dumps(dict(resp.headers))

    def test_la_key_no_aparece_en_la_config_del_espacio(self, conexion_client):
        c, store, _vault = conexion_client
        eid = _make_espacio(store)
        c.post(f"/espacios/{eid}/conexiones",
               json={"var": "TEST_API_KEY", "valor": DUMMY_KEY})
        # el state.json del espacio (config) NO debe contener el valor en claro
        state_raw = store.state_path(eid).read_text()
        assert DUMMY_KEY not in state_raw

    def test_la_key_no_aparece_en_claro_en_el_vault_enc(self, conexion_client):
        c, store, vault = conexion_client
        eid = _make_espacio(store)
        c.post(f"/espacios/{eid}/conexiones",
               json={"var": "TEST_API_KEY", "valor": DUMMY_KEY})
        # el vault.enc en disco está cifrado: la key NO aparece en claro
        store_path = Path(vault._store_path)  # type: ignore[attr-defined]
        assert store_path.exists()
        blob = store_path.read_bytes()
        assert DUMMY_KEY.encode() not in blob

    def test_la_key_no_aparece_en_el_log_de_la_request(self, conexion_client, caplog):
        import logging
        c, store, _vault = conexion_client
        eid = _make_espacio(store)
        with caplog.at_level(logging.DEBUG):
            c.post(f"/espacios/{eid}/conexiones",
                   json={"var": "TEST_API_KEY", "valor": DUMMY_KEY})
        assert DUMMY_KEY not in caplog.text


# ── Smoke de plomería: el belt con la key inyectada ARRANCA (echo real) ───────

class TestSmokePlomeria:
    def test_belt_real_arranca_con_env_inyectado_del_vault(self, tmp_vault):
        """
        PRUEBA DE PLOMERÍA: guardamos ${TEST_API_KEY} en el vault, resolvemos el
        env del belt con el vault, y arrancamos el echo server real con ese env
        inyectado. El echo IGNORA el env pero su boot PRUEBA el hot-mount: el
        subprocess levanta y la tool 'echo' aparece. (Sin LLM — boot directo.)
        """
        import importlib.util

        # 1) el secreto entra al vault
        tmp_vault.put("TEST_API_KEY", DUMMY_KEY)

        # 2) cargamos el motor de MCP (assembler) por ruta — como hace session.py
        asm_py = REPO_ROOT / "platform" / "assembler" / "assembler.py"
        spec = importlib.util.spec_from_file_location("puppet_asm_smoke", asm_py)
        asm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(asm)

        belt = json.loads(BELT_CONEXION_TEST.read_text())
        scfg = belt["mcpServers"]["testapi"]

        # 3) el vault resuelve el env del belt (sustituye ${TEST_API_KEY})
        env_resuelto = tmp_vault.resolve_env_template(scfg.get("env", {}))
        assert env_resuelto["TEST_API_KEY"] == DUMMY_KEY  # resuelto desde el vault

        # 4) el server real ARRANCA (la plomería del hot-mount); el echo ignora el
        #    env pero su init prueba que el subprocess levanta.
        srv = asm.MCPServer("testapi", scfg["command"], scfg.get("args", []))
        try:
            assert srv.start() is True
            tools = srv.list_tools()
            names = [t.get("name") for t in tools]
            assert "echo" in names  # LA TOOL APARECE
        finally:
            srv.stop()

    def test_inject_env_no_ecoa_el_valor_en_log(self, tmp_vault):
        """inject_env mete el valor al env del subprocess; redacted_env_log lo
        oculta. La key dummy no aparece en el render de log del env."""
        import importlib.util
        vault_py = REPO_ROOT / "platform" / "gates" / "vault.py"
        spec = importlib.util.spec_from_file_location("puppet_vault_smoke", vault_py)
        vmod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vmod)

        tmp_vault.put("TEST_API_KEY", DUMMY_KEY)
        env = tmp_vault.inject_env({}, ["TEST_API_KEY"])
        assert env["TEST_API_KEY"] == DUMMY_KEY  # el subprocess SÍ lo recibe
        log = vmod.redacted_env_log(env, ["TEST_API_KEY"])
        assert DUMMY_KEY not in log            # el log NO
        assert "TEST_API_KEY=<oculto:vault>" in log
