"""
test_conexiones_repo.py — unit del DUEÑO del registro (CONTRACT-CONEXION-v1 §1).

Verde = efecto real sobre un SQLite de verdad (el schema del cliente, aplicado), nunca
narración. Cubre lo que el contrato promete y lo que la sesión promete NO hacer:

  1. upsert crea, y el segundo upsert ACTUALIZA sin duplicar (una fila por entidad).
  2. un update parcial NO pisa lo que escribió otro caller.
  3. anti-IDOR: la entidad de otro usuario es inexistente, no ajena.
  4. §2 — un VALOR donde va un placeholder LEVANTA en vez de persistirse.
  5. §1 — `recipe_version` desconocida se devuelve MARCADA, ni se levanta ni se descarta.
  6. los JSON round-trippean; un JSON corrupto devuelve el crudo en vez de tumbar la
     lectura (perder la fila entera por un campo ilegible es peor).
  7. §4 — LA LÁPIDA. `desconectar` apaga y DEJA LA LLAVE (borrarla es la otra acción);
     `reconectar` la levanta; apagar lo inexistente LEVANTA en vez de crear la fila; y una
     entidad apagada SIGUE en la lista, porque mostrar y levantar son preguntas distintas.
  8. §2 — el entorno vive en DOS columnas: `repartir_env` manda `${VAR}` a `env_template`
     y los literales a `env_publico`; `env_efectivo` las junta y la referencia al llavero
     gana. El caso índice es `secedgar` (el único literal de los 16 .mcp.json del
     catálogo), y el guard de `env_template` NO se ablandó por tenerla.

Correr:
    PYTHONPATH=platform:platform/db:product/backend pytest \\
        product/backend/app/phase1/test_conexiones_repo.py -q
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[4]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.phase1 import conexiones_repo as CR  # noqa: E402


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """Un cliente REAL: el schema del cliente aplicado sobre un .db propio."""
    monkeypatch.setenv("ALEPH_ROLE", "client")
    monkeypatch.setenv("PUPPET_SQLITE_PATH", str(tmp_path / "t.db"))
    import sqlite_db
    sqlite_db.asegurar_schema()
    from app.phase1 import repo
    c = repo.get_conn()
    with c.cursor() as cur:
        cur.execute("INSERT INTO users (email) VALUES (%s) RETURNING id", ("a@b.c",))
        c.uid = cur.fetchone()[0]
    c.commit()
    yield c
    c.close()


def test_upsert_crea_y_actualiza_sin_duplicar(conn):
    """Una fila por ENTIDAD: el segundo upsert es UPDATE, no un segundo INSERT."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa", nombre_visible="Exa")
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa", nombre_visible="Exa Search")
    filas = CR.listar_entidades(conn, conn.uid)
    assert len(filas) == 1
    assert filas[0]["nombre_visible"] == "Exa Search"


def test_update_parcial_no_pisa_lo_que_escribio_otro(conn):
    """El que sabe del transporte no puede borrar el veredicto que escribió el motor."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa",
                      command="npx", args=["-y", "exa-mcp-server"], transporte="stdio")
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa", ultimo_veredicto="probado")
    e = CR.leer_entidad(conn, conn.uid, "exa")
    assert e["command"] == "npx"
    assert e["args"] == ["-y", "exa-mcp-server"]
    assert e["ultimo_veredicto"] == "probado"


def test_ajeno_es_inexistente(conn):
    """Anti-IDOR: la entidad de otro usuario no se lee, y tampoco se filtra en la lista."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa")
    assert CR.leer_entidad(conn, "otro-usuario", "exa") is None
    assert CR.listar_entidades(conn, "otro-usuario") == []


def test_un_secreto_en_env_template_levanta(conn):
    """§2: el registro guarda NOMBRES. Un valor en claro no llega al disco."""
    with pytest.raises(CR.SecretoEnElRegistro):
        CR.upsert_entidad(conn, user_id=conn.uid, entity_id="fuga",
                          env_template={"FRED_API_KEY": "fo_55cd8f5bd71a9b83"})
    assert CR.leer_entidad(conn, conn.uid, "fuga") is None, "no puede haber quedado la fila"


def test_un_placeholder_si_pasa(conn):
    """La forma legítima: `${VAR}`. El guard no puede ser tan duro que rompa el caso real."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa",
                      env_template={"EXA_API_KEY": "${EXA_API_KEY}"})
    assert CR.leer_entidad(conn, conn.uid, "exa")["env_template"] == {"EXA_API_KEY": "${EXA_API_KEY}"}


# ── §2 · el entorno vive en DOS columnas ─────────────────────────────────────────

#: EL CASO ÍNDICE. `secedgar` es hoy el ÚNICO literal de los 16 `.mcp.json` del catálogo,
#: y el que hizo falta esta columna: SEC EDGAR exige identificarse y rechaza el request
#: sin el User-Agent. No es un secreto — es público por diseño.
SECEDGAR_ENV = {"SEC_EDGAR_USER_AGENT": "Aleph (contact@aleph.app)"}


def test_repartir_env_manda_el_literal_a_publico():
    """El caso índice: el User-Agent de SEC EDGAR NO puede terminar en env_template."""
    template, publico = CR.repartir_env(SECEDGAR_ENV)
    assert template == {}
    assert publico == SECEDGAR_ENV


def test_repartir_env_manda_el_placeholder_a_template():
    template, publico = CR.repartir_env({"EXA_API_KEY": "${EXA_API_KEY}"})
    assert template == {"EXA_API_KEY": "${EXA_API_KEY}"}
    assert publico == {}


def test_repartir_env_mezclado(conn):
    """Un server puede tener las dos cosas a la vez y cada una va a su columna."""
    template, publico = CR.repartir_env({**SECEDGAR_ENV, "TOK": "${TOK}"})
    assert template == {"TOK": "${TOK}"}
    assert publico == SECEDGAR_ENV


def test_secedgar_persiste_su_user_agent_con_el_valor_real(conn):
    """LA REGRESIÓN QUE ESTA COLUMNA EVITA. Antes el guard tiraba el campo entero y
    `secedgar` se reconstruía SIN User-Agent → SEC EDGAR rechaza el request."""
    template, publico = CR.repartir_env(SECEDGAR_ENV)
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="secedgar",
                      command="uvx", args=["sec-edgar-mcp"],
                      env_template=template or None, env_publico=publico or None)
    e = CR.leer_entidad(conn, conn.uid, "secedgar")
    assert e["env_publico"] == SECEDGAR_ENV, "el valor real tiene que estar, tal cual"
    assert e["env_template"] is None
    assert CR.env_efectivo(e)["SEC_EDGAR_USER_AGENT"] == "Aleph (contact@aleph.app)"


def test_el_guard_de_env_template_NO_se_ablando(conn):
    """La columna nueva no es una puerta trasera: un literal puesto a mano en
    env_template sigue levantando. Lo público se DECLARA, no se cuela."""
    with pytest.raises(CR.SecretoEnElRegistro):
        CR.upsert_entidad(conn, user_id=conn.uid, entity_id="secedgar",
                          env_template=SECEDGAR_ENV)
    assert CR.leer_entidad(conn, conn.uid, "secedgar") is None


def test_los_headers_usan_EL_MISMO_guard_que_el_entorno(conn):
    """§2 (v4): un token en un header es tan secreto como en una env var. No tiene guard
    propio — tiene EL guard, y levanta igual."""
    with pytest.raises(CR.SecretoEnElRegistro, match="headers_template"):
        CR.upsert_entidad(conn, user_id=conn.uid, entity_id="remoto", transporte="http",
                          url="https://mcp.example.test/mcp",
                          headers_template={"Authorization": "Bearer sk-secreto-en-claro"})
    assert CR.leer_entidad(conn, conn.uid, "remoto") is None


def test_un_header_con_placeholder_EMBEBIDO_pasa(conn):
    """La forma real de un manifest: `Bearer ${TOKEN}` — el placeholder va DENTRO del
    valor, no es el valor entero. Si el guard exigiera `${VAR}` exacto, rompería el caso
    legítimo de todos los MCP remotos con token."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="remoto", transporte="http",
                      url="https://mcp.example.test/mcp",
                      headers_template={"Authorization": "Bearer ${MI_TOKEN}"},
                      headers_publico={"Accept": "application/json"})
    e = CR.leer_entidad(conn, conn.uid, "remoto")
    assert e["url"] == "https://mcp.example.test/mcp"
    assert e["headers_template"] == {"Authorization": "Bearer ${MI_TOKEN}"}
    assert CR.headers_efectivo(e) == {"Accept": "application/json",
                                      "Authorization": "Bearer ${MI_TOKEN}"}


def test_repartir_env_sirve_igual_para_headers():
    """Un solo criterio para «¿esto es una referencia?»: contiene `${VAR}`."""
    template, publico = CR.repartir_env({"Authorization": "Bearer ${TOK}",
                                         "Accept": "application/json"})
    assert template == {"Authorization": "Bearer ${TOK}"}
    assert publico == {"Accept": "application/json"}


def test_la_receta_http_se_guarda_entera(conn):
    """El §1 prometía «cómo reconstruir» y no tenía dónde poner la mitad de las recetas.
    Ahora un server HTTP entra completo: endpoint + headers repartidos."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="remoto", transporte="http",
                      url="https://mcp.example.test/mcp",
                      headers_template={"Authorization": "Bearer ${TOK}"},
                      credencial_ref="remoto")
    e = CR.leer_entidad(conn, conn.uid, "remoto")
    assert e["transporte"] == "http" and e["url"] and e["headers_template"]
    assert e["command"] is None, "un server HTTP no tiene command"


def test_env_efectivo_junta_las_dos_y_el_llavero_gana(conn):
    """Al spawnear se juntan. Si un nombre estuviera en las dos, gana la REFERENCIA:
    nunca un literal por encima del llavero."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="mixto",
                      env_template={"TOK": "${TOK}"},
                      env_publico={"UA": "Aleph", "TOK": "literal-que-no-debe-ganar"})
    e = CR.leer_entidad(conn, conn.uid, "mixto")
    assert CR.env_efectivo(e) == {"UA": "Aleph", "TOK": "${TOK}"}


def test_recipe_version_desconocida_se_marca_ni_se_levanta_ni_se_descarta(conn):
    """§1: la creó un Aleph más nuevo. Se devuelve MARCADA — jamás se borra sola."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="del-futuro", recipe_version="v9")
    e = CR.leer_entidad(conn, conn.uid, "del-futuro")
    assert e is not None, "no se descarta"
    assert e["_desconocida"] is True
    assert e["_causa_lectura"] == CR.CAUSA_RECIPE_VERSION_DESCONOCIDA
    assert "del-futuro" in [x["entity_id"] for x in CR.listar_entidades(conn, conn.uid)]


def test_recipe_version_conocida_no_se_marca(conn):
    """El control positivo del test de arriba: v1 no puede salir marcada."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa", recipe_version="v1")
    e = CR.leer_entidad(conn, conn.uid, "exa")
    assert e["_desconocida"] is False
    assert "_causa_lectura" not in e


def test_transporte_invalido_levanta(conn):
    """§1: el transporte es EXPLÍCITO y de un conjunto cerrado."""
    with pytest.raises(ValueError):
        CR.upsert_entidad(conn, user_id=conn.uid, entity_id="x", transporte="carrier-pigeon")


def test_campo_desconocido_levanta(conn):
    """Un typo en el nombre de un campo no puede irse en silencio."""
    with pytest.raises(ValueError):
        CR.upsert_entidad(conn, user_id=conn.uid, entity_id="x", comando="npx")


def test_los_json_roundtrippean(conn):
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa",
                      args=["-y", "exa"], scopes=["read"],
                      tools_snapshot=["search"], server_info={"name": "exa", "version": "1"})
    e = CR.leer_entidad(conn, conn.uid, "exa")
    assert e["args"] == ["-y", "exa"]
    assert e["scopes"] == ["read"]
    assert e["tools_snapshot"] == ["search"]
    assert e["server_info"] == {"name": "exa", "version": "1"}


def test_un_json_corrupto_levanta_con_la_columna_nombrada(conn):
    """Una columna JSON corrupta la caza `sqlite_db._decodificar_fila` ANTES que este
    módulo, y levanta nombrando la columna. Es el comportamiento correcto y el que ya
    tenía el árbol: un str colado reaparecería como TypeError a dos módulos de distancia.
    Se fija acá para que el registro no lo relaje por accidente."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa")
    with conn.cursor() as cur:
        cur.execute("UPDATE conexiones SET tools_snapshot = %s WHERE entity_id = %s",
                    ("{esto no es json", "exa"))
    conn.commit()
    with pytest.raises(ValueError, match="tools_snapshot"):
        CR.leer_entidad(conn, conn.uid, "exa")


def test_las_cinco_columnas_json_estan_registradas_abajo(conn):
    """`sqlite_db._COLS_JSON` decide qué se decodifica. Si el registro suma un campo JSON
    y nadie lo agrega ahí, esa columna sale CRUDA mientras las otras salen decodificadas:
    la misma tabla con dos comportamientos. Este test lo impide."""
    import sqlite_db
    faltan = sorted(CR._CAMPOS_JSON - sqlite_db._COLS_JSON)
    assert not faltan, f"campos JSON del registro que sqlite_db no decodifica: {faltan}"


# ── LA LÁPIDA (§4) ───────────────────────────────────────────────────────────────

def test_desconectar_apaga_y_DEJA_LA_LLAVE(conn):
    """LA MITAD QUE SE PIERDE DE VISTA. Si desconectar tocara la credencial, volver a
    conectar exigiría conseguir y pegar la llave de nuevo — el costo de la acción de
    seguridad cobrado por la acción operativa."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa",
                      credencial_ref="exa", command="uvx", args=["exa-mcp"])
    e = CR.desconectar(conn, conn.uid, "exa")
    assert e["habilitado"] is False
    assert e["credencial_ref"] == "exa", "la llave NO se toca"
    assert e["command"] == "uvx" and e["args"] == ["exa-mcp"], "la receta queda entera"


def test_reconectar_es_un_click_sin_reconfigurar(conn):
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa",
                      credencial_ref="exa", command="uvx", args=["exa-mcp"])
    CR.desconectar(conn, conn.uid, "exa")
    e = CR.reconectar(conn, conn.uid, "exa")
    assert e["habilitado"] is True
    assert e["command"] == "uvx" and e["credencial_ref"] == "exa"


def test_desconectar_es_idempotente(conn):
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa")
    CR.desconectar(conn, conn.uid, "exa")
    assert CR.desconectar(conn, conn.uid, "exa")["habilitado"] is False


def test_desconectar_lo_que_no_existe_NO_LO_CREA(conn):
    """Con un upsert, apagar una entidad fantasma le fabricaría una lápida a algo que
    nunca estuvo. Un UPDATE que no toca nada levanta, que es la respuesta honesta."""
    with pytest.raises(CR.EntidadInexistente):
        CR.desconectar(conn, conn.uid, "no-existe")
    assert CR.listar_entidades(conn, conn.uid) == []


def test_anti_IDOR_no_se_puede_apagar_la_conexion_de_otro(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (email) VALUES (%s) RETURNING id", ("otro@b.c",))
        otro = cur.fetchone()[0]
    CR.upsert_entidad(conn, user_id=otro, entity_id="exa")
    with pytest.raises(CR.EntidadInexistente):
        CR.desconectar(conn, conn.uid, "exa")
    assert CR.leer_entidad(conn, otro, "exa")["habilitado"] is True, "intacta"


def test_una_entidad_apagada_SIGUE_EN_LA_LISTA(conn):
    """§4: la pieza no desaparece del diorama — sigue ahí, apagada, con su botón. Una
    pieza que se evapora porque el usuario la apagó es el mismo fallo mudo que el §1
    prohíbe para `recipe_version` desconocida."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="apagada")
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="prendida")
    CR.desconectar(conn, conn.uid, "apagada")
    ids = {x["entity_id"] for x in CR.listar_entidades(conn, conn.uid)}
    assert ids == {"apagada", "prendida"}, "mostrar y levantar no son la misma pregunta"
    solo_on = {x["entity_id"] for x in CR.listar_entidades(conn, conn.uid,
                                                           incluir_deshabilitadas=False)}
    assert solo_on == {"prendida"}, "el filtro es para el restaurador, no para la lista"


def test_guardar_la_llave_LEVANTA_la_lapida(conn):
    """§4 · EL PUNTO ÚNICO. Nadie pega una credencial para dejar el servicio apagado:
    pegar la llave ES conectar. Antes, la única forma de levantar la lápida era
    `/reconectar`, así que se podía conectar por el flujo normal, verlo andar, y que la
    fila siguiera «Desconectado» con el restaurador salteándola."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="exa", credencial_ref="exa")
    CR.desconectar(conn, conn.uid, "exa")
    assert CR.leer_entidad(conn, conn.uid, "exa")["habilitado"] is False

    assert CR.reconectar_por_credencial(conn, conn.uid, "exa") == ["exa"]
    assert CR.leer_entidad(conn, conn.uid, "exa")["habilitado"] is True


def test_levanta_las_entidades_que_USAN_esa_credencial_aunque_se_llamen_distinto(conn):
    """`maritime` usa la credencial `globalfishingwatch`: el entity_id y el provider NO
    coinciden. Se busca por `credencial_ref` justamente para cubrir las dos formas sin
    una tabla de equivalencias que mantener."""
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="maritime",
                      credencial_ref="globalfishingwatch")
    CR.upsert_entidad(conn, user_id=conn.uid, entity_id="otra", credencial_ref="otra_cosa")
    CR.desconectar(conn, conn.uid, "maritime")
    CR.desconectar(conn, conn.uid, "otra")

    assert CR.reconectar_por_credencial(conn, conn.uid, "globalfishingwatch") == ["maritime"]
    assert CR.leer_entidad(conn, conn.uid, "maritime")["habilitado"] is True
    assert CR.leer_entidad(conn, conn.uid, "otra")["habilitado"] is False, "no toca lo ajeno"


def test_reconectar_por_credencial_no_levanta_si_no_hay_nada(conn):
    """Que una credencial no tenga entidades apagadas es lo NORMAL, no un error."""
    assert CR.reconectar_por_credencial(conn, conn.uid, "no-existe") == []
    assert CR.reconectar_por_credencial(conn, conn.uid, "") == []


def test_no_cruza_usuarios(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (email) VALUES (%s) RETURNING id", ("otro@b.c",))
        otro = cur.fetchone()[0]
    CR.upsert_entidad(conn, user_id=otro, entity_id="exa", credencial_ref="exa")
    CR.desconectar(conn, otro, "exa")
    assert CR.reconectar_por_credencial(conn, conn.uid, "exa") == []
    assert CR.leer_entidad(conn, otro, "exa")["habilitado"] is False, "la del otro sigue apagada"
