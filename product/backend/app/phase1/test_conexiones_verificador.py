"""test_conexiones_verificador.py — las reglas puras del verificador.

Escritos contra los fallos que importan, con los casos REALES medidos como fixtures:

  1. un 401 es CONEXIÓN VIVA           (si no, «tu llave venció» se ve igual que «no arranca»)
  2. VERDE de credencial SÓLO por doble (necesaria + suficiente, nunca una sola)
  3. no se inventan argumentos          (code/sql/path/id-exacto quedan afuera por SCHEMA)
  4. el hint ORDENA, no habilita        (`coingecko.execute` se anuncia readOnly y ejecuta código)

Correr:  pytest product/backend/app/phase1/test_conexiones_verificador.py -v
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import patch

_RAIZ = Path(__file__).resolve().parents[4]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.phase1 import conexiones_verificador as V  # noqa: E402


def test_verifier_expansion_excludes_ambient_provider_secret():
    from app.phase1 import motor_verdad as MV
    with patch.dict(os.environ, {"FAKE_DB_SECRET": "synthetic-db-sentinel"}):
        entorno = MV._entorno_de_belts()
        assert "FAKE_DB_SECRET" not in entorno
        # A belt reference cannot silently turn the sidecar's ambient secret
        # into a declared variable for this MCP.
        assert MV._expandir("${FAKE_DB_SECRET}", entorno) == "${FAKE_DB_SECRET}"


def test_verifier_spawn_never_expands_ambient_secret_into_mcp():
    import transporte as TP
    captured = {}

    class FakeServer:
        def __init__(self, _name, _command, _args, *, env, rpc_timeout):
            captured.update(env)

        def start(self):
            return False

        def diagnostico(self):
            return {}

        def stop(self):
            pass

    class NoOwner:
        @staticmethod
        def encendido():
            return False

    spec = {"command": "/usr/bin/false", "env": {"X": "${FAKE_DB_SECRET}"}}
    with patch.object(TP, "servidor_stdio", return_value=FakeServer), \
         patch.object(V, "_dueno", return_value=NoOwner):
        V._spawn(spec, {"PUPPET_WORKDIR": "/tmp/aleph-synthetic-run",
                        "FAKE_DB_SECRET": "synthetic-db-sentinel"}, "")
    assert "synthetic-db-sentinel" not in captured.values()
    assert "FAKE_DB_SECRET" not in captured


# ── 1 · LA REGLA QUE SEPARA LAS DOS PREGUNTAS ────────────────────────────────────

def test_un_401_es_CONEXION_VIVA():
    """EL INVARIANTE DE LA SESIÓN. Un rechazo de credencial prueba que TODO el camino
    funciona: el proceso arrancó, habló MCP, el mensaje llegó al servicio y el servicio
    contestó. Marcarlo conexión rota haría que «tu llave venció» —que se arregla pegando
    una llave— se viera igual que «este server no arranca», que no se arregla así."""
    r = V.veredicto_conexion([{"tool": "whoami",
                               "salida": '[tool error] {"status": 403, "detail": "Invalid key"}'}])
    assert r["estado"] == V.VIVA
    assert r["causa"] is None
    assert r["tool_usada"] == "whoami"


def test_un_402_y_un_429_tambien_son_conexion_viva():
    """Medidos: fred devuelve 402 `no_wallet`. El servicio contestó."""
    for cuerpo in ('[tool error] {"status": 402, "error": "payment_required"}',
                   "[tool error] 429 rate limit exceeded",
                   "[tool error] Invalid API key. Please check your API key."):
        assert V.veredicto_conexion([{"tool": "x", "salida": cuerpo}])["estado"] == V.VIVA


def test_un_dato_real_es_conexion_viva():
    r = V.veredicto_conexion([{"tool": "whoami", "salida": '{"ok": true, "userID": 20856542}'}])
    assert r["estado"] == V.VIVA and "20856542" in r["evidencia"]


def test_un_timeout_es_conexion_ROTA_con_causa():
    r = V.veredicto_conexion([{"tool": "x", "salida": "[mcp error] request timed out"}])
    assert r["estado"] == V.ROTA and r["causa"] == V.C_TIMEOUT


def test_sin_candidatas_NO_es_rota_sino_SIN_SONDEAR():
    """No es lo mismo «no contestó» que «no hubo nada que preguntarle». Medido: 14 de 62
    servidores arrancan y publican tools que piden código, rutas, SQL o ids exactos —
    ninguna se puede llamar a ciegas. El canal nunca se ejercitó, así que llamarlos ROTOS
    sería reportar NUESTRA incapacidad de medir como una falla del servidor."""
    r = V.veredicto_conexion([])
    assert r["estado"] == V.SIN_SONDEAR
    assert r["estado"] != V.ROTA
    assert r["causa"] == V.C_SIN_CANDIDATA and "inventar" in r["evidencia"]


# ── 2 · VERDE DE CREDENCIAL SÓLO POR DOBLE COMPLETA ──────────────────────────────

def test_verde_SOLO_si_la_real_da_dato_Y_la_basura_rechaza():
    r = V.veredicto_credencial(pide_llave=True, hay_llave_real=True, tool="whoami",
                               con_real={"ok": True}, con_basura={"rechazada": True})
    assert r["estado"] == V.VERDE and r["tool_prueba"] == "whoami"


def test_si_la_basura_TAMBIEN_pasa_no_hay_verde():
    """El caso `health_check` de fred: devuelve OK con cualquier llave. Declararla movería
    el bug en vez de arreglarlo."""
    r = V.veredicto_credencial(pide_llave=True, hay_llave_real=True, tool="health_check",
                               con_real={"ok": True}, con_basura={"ok": True})
    assert r["estado"] == V.SIN_MEDIR and r["tool_prueba"] is None
    assert "no ejercita" in r["evidencia"]


def test_sin_llave_real_un_rechazo_de_basura_es_CANDIDATA_no_verde():
    """La condición NECESARIA sin la suficiente. Es el caso `context7.resolve-library-id`:
    rechaza la basura, pero no sabemos que responda bien con una llave buena. Declararla
    produciría falsos rojos — decirle a alguien con la llave válida que su llave falló."""
    r = V.veredicto_credencial(pide_llave=True, hay_llave_real=False,
                               tool="resolve-library-id", con_basura={"rechazada": True})
    assert r["estado"] == V.CANDIDATA
    assert r["estado"] != V.VERDE


def test_sin_llave_real_si_la_basura_PASA_queda_descartada():
    """Ésta sí es una conclusión firme sin llave real: `massive.search_endpoints` devolvió
    endpoints con basura. No mira la credencial, y eso se sabe sin comparar con nada."""
    r = V.veredicto_credencial(pide_llave=True, hay_llave_real=False,
                               tool="search_endpoints", con_basura={"ok": True})
    assert r["estado"] == V.SIN_MEDIR and "descartada" in r["evidencia"]


def test_el_que_no_pide_llave_es_NO_APLICA_y_no_bloquea():
    r = V.veredicto_credencial(pide_llave=False, hay_llave_real=False)
    assert r["estado"] == V.NO_APLICA and r["tool_prueba"] is None


def test_llave_real_rechazada_se_reporta_como_rechazada():
    r = V.veredicto_credencial(pide_llave=True, hay_llave_real=True, tool="whoami",
                               con_real={"ok": False, "rechazada": True, "muestra": "403 Invalid key"},
                               con_basura={"rechazada": True})
    assert r["estado"] == V.RECHAZADA and "403" in r["evidencia"]


# ── 3 · NO SE INVENTAN ARGUMENTOS ────────────────────────────────────────────────

def _t(nombre, required=None, props=None, anot=None, desc=""):
    return {"name": nombre, "description": desc,
            "inputSchema": {"required": required or [], "properties": props or {}},
            **({"annotations": anot} if anot else {})}


def test_se_excluye_por_SCHEMA_lo_que_puede_tener_efecto():
    """Los casos reales: `coingecko.execute(code)`, `massive.call_api(path)`,
    `massive.query_data(sql)`, `context7.query-docs(libraryId)`. Ninguna se puede llamar a
    ciegas sin inventar algo que decide qué pasa."""
    tools = [
        _t("execute", ["code"], {"code": {"type": "string"}}, {"readOnlyHint": True}),
        _t("call_api", ["path"], {"path": {"type": "string"}}, {"readOnlyHint": True}),
        _t("query_data", ["sql"], {"sql": {"type": "string"}}, {"readOnlyHint": True}),
        _t("query-docs", ["libraryId"], {"libraryId": {"type": "string"}}),
    ]
    assert V.elegir_tools(tools) == []


def test_el_readOnlyHint_NO_alcanza_para_habilitar():
    """`coingecko.execute` se anuncia `readOnlyHint: true` y su parámetro es
    `code: "Code to execute"`. El hint es una pista del servidor, no un contrato — el
    propio spec lo dice, y acá está medido."""
    solo_hint = [_t("execute", ["code"], {"code": {"type": "string"}},
                    {"readOnlyHint": True}, "Code to execute.")]
    assert V.elegir_tools(solo_hint) == []


def test_un_required_de_busqueda_SI_se_puede_llenar():
    """La regla no es «cero required»: es «required que se pueda llenar con algo obvio y sin
    efecto». Una búsqueda no tiene efecto; un destinatario sí."""
    tools = [_t("search_docs", ["query", "language"],
                {"query": {"type": "string"}, "language": {"type": "string"}})]
    elegidas = V.elegir_tools(tools)
    assert [e["name"] for e in elegidas] == ["search_docs"]
    assert elegidas[0]["args"] == {"query": "aleph", "language": "python"}


def test_lo_que_huele_a_escritura_queda_afuera_aunque_el_schema_este_limpio():
    tools = [_t("send_email", [], {}), _t("create_item", [], {}), _t("delete_file", [], {}),
             _t("whoami", [], {})]
    assert [e["name"] for e in V.elegir_tools(tools)] == ["whoami"]


def test_destructiveHint_true_queda_afuera():
    tools = [_t("limpiar", [], {}, {"destructiveHint": True}), _t("whoami", [], {})]
    assert [e["name"] for e in V.elegir_tools(tools)] == ["whoami"]


# ── 4 · ORDEN Y TOPE ─────────────────────────────────────────────────────────────

def test_la_declarada_gana_y_va_sola():
    """Un conector ya certificado no se re-explora: una llamada a la tool conocida."""
    tools = [_t("whoami", [], {}), _t("list_items", [], {}), _t("otra", [], {})]
    r = V.elegir_tools(tools, declarada={"tool": "whoami", "args": {}})
    assert r == [{"name": "whoami", "args": {}, "origen": "declarada"}]


def test_una_declarada_que_el_server_ya_no_publica_no_se_usa():
    """La declaración quedó vieja: se cae a la selección normal en vez de llamar algo que
    no existe."""
    tools = [_t("whoami", [], {})]
    r = V.elegir_tools(tools, declarada={"tool": "ya_no_existe", "args": {}})
    assert [x["name"] for x in r] == ["whoami"] and r[0]["origen"] == "elegida"


def test_primero_las_que_no_piden_nada_despues_las_anotadas():
    tools = [_t("con_args", ["query"], {"query": {"type": "string"}}),
             _t("sin_args_anotada", [], {}, {"readOnlyHint": True}),
             _t("sin_args", [], {})]
    assert [e["name"] for e in V.elegir_tools(tools)][0] in ("sin_args_anotada", "sin_args")
    assert V.elegir_tools(tools)[0]["args"] == {}


def test_el_tope_es_tres():
    tools = [_t(f"leer_{i}", [], {}) for i in range(10)]
    assert len(V.elegir_tools(tools)) == V.MAX_TOOLS == 3


# ── 5 · LA SONDA DECLARADA (CLAUDE.md · «el guard no inventa; el catálogo declara») ──

def test_la_sonda_declarada_se_usa_y_va_sola():
    """Los casos reales: `git` publica 12 tools y las 12 piden `repo_path`; `fetch` publica
    una y pide `url`. Sin declaración quedaban «sin sondear» para siempre — honesto pero
    inútil. Con declaración se llama UNA, la del catálogo, con SUS argumentos."""
    tools = [_t("git_status", ["repo_path"], {"repo_path": {"type": "string"}}),
             _t("git_log", ["repo_path"], {"repo_path": {"type": "string"}})]
    r = V.elegir_tools(tools, sonda={"tool": "git_status", "args": {"repo_path": "/w"}})
    assert r == [{"name": "git_status", "args": {"repo_path": "/w"},
                  "origen": "sonda_declarada"}]


def test_sin_sonda_declarada_el_guard_SIGUE_sin_inventar():
    """La declaración es la ÚNICA vía. Que exista el mecanismo no ablanda el guard: sin
    catálogo que declare, una tool que pide `repo_path` sigue sin llamarse."""
    tools = [_t("git_status", ["repo_path"], {"repo_path": {"type": "string"}})]
    assert V.elegir_tools(tools) == []
    assert V.elegir_tools(tools, sonda=None) == []
    assert V.elegir_tools(tools, sonda={"tool": "otra_que_no_existe", "args": {}}) == []


def test_la_credencial_declarada_le_gana_a_la_sonda():
    """Si hay las dos, manda la de credencial: mide más (canal Y llave) con una sola
    llamada. Dos llamadas para saber lo mismo es gastar el rate limit del usuario."""
    tools = [_t("whoami", [], {}), _t("git_status", ["repo_path"], {})]
    r = V.elegir_tools(tools, declarada={"tool": "whoami", "args": {}},
                       sonda={"tool": "git_status", "args": {"repo_path": "/w"}})
    assert [x["name"] for x in r] == ["whoami"] and r[0]["origen"] == "declarada"


def test_una_sonda_que_el_server_ya_no_publica_no_se_llama():
    """Declaración vieja: se cae a la selección normal, no se inventa la llamada."""
    tools = [_t("solo_lectura", [], {})]
    r = V.elegir_tools(tools, sonda={"tool": "git_status", "args": {"repo_path": "/w"}})
    assert [x["name"] for x in r] == ["solo_lectura"] and r[0]["origen"] == "elegida"


def test_un_error_tipado_del_servicio_es_conexion_VIVA():
    """MEDIDO con la sonda de `git`: el workdir de Aleph no es un repo, así que
    `git_status` devuelve `[tool error] <path>`. Eso NO es una conexión rota — el proceso
    arrancó, habló MCP, aceptó la llamada y contestó. Es exactamente lo que la sonda mide."""
    r = V.veredicto_conexion([{"tool": "git_status",
                               "salida": "[tool error] /var/folders/x/aleph-probe-workdir"}])
    assert r["estado"] == V.VIVA and r["causa"] is None


# ── 5 · LA MISMA REGLA, POR EL PUENTE (sesión 2 · el recableo) ───────────────────
# `veredicto_conexion` dejó de leer texto y pasó a leer el código JSON-RPC cuando el
# transporte lo tipa. Estos casos son las salidas REALES del puente, medidas: el veredicto
# tiene que ser el MISMO que daba el cliente viejo para la misma situación.

_MUERTO_PUENTE = "[MCP error: {'code': -32000, 'message': 'Connection closed'}]"
_MUERTO_VIEJO = "[MCP error: no response from fetch]"
_COLGADO_PUENTE = "[MCP error: {'code': -32001, 'message': \"Request 'tools/call' timed out\"}]"


def test_un_server_MUERTO_por_el_puente_sigue_siendo_ROTA():
    """EL BUG QUE EL RECABLEO CERRÓ. «Connection closed» no matchea ninguna palabra de la
    regex vieja («connection reset» sí estaba, «connection closed» no), así que el texto no
    vacío caía en la rama VIVA: un servidor muerto se reportaba vivo. Silencioso, y en la
    dirección peor de las dos."""
    r = V.veredicto_conexion([{"tool": "x", "salida": _MUERTO_PUENTE}])
    assert r["estado"] == V.ROTA, "un server muerto NO puede salir vivo"
    assert r["causa"] == V.C_SIN_RESPUESTA


def test_el_muerto_da_el_MISMO_estado_por_los_dos_transportes():
    """La equivalencia que la regla madre exige: mismo servidor, mismo veredicto."""
    viejo = V.veredicto_conexion([{"tool": "x", "salida": _MUERTO_VIEJO}])
    puente = V.veredicto_conexion([{"tool": "x", "salida": _MUERTO_PUENTE}])
    assert viejo["estado"] == puente["estado"] == V.ROTA
    assert viejo["causa"] == puente["causa"] == V.C_SIN_RESPUESTA


def test_un_timeout_por_el_puente_sigue_dando_C_TIMEOUT():
    r = V.veredicto_conexion([{"tool": "x", "salida": _COLGADO_PUENTE}])
    assert r["estado"] == V.ROTA and r["causa"] == V.C_TIMEOUT


def test_un_error_JSON_RPC_del_server_es_conexion_VIVA_por_el_puente():
    """El servidor CONTESTÓ —rechazó la llamada, pero contestó—. Es la misma regla del 401:
    el canal funciona y el problema es otro."""
    r = V.veredicto_conexion([{"tool": "x",
                               "salida": "[MCP error: {'code': -32602, "
                                         "'message': 'Invalid params'}]"}])
    assert r["estado"] == V.VIVA and r["causa"] is None


def test_una_tool_viva_gana_sobre_una_muerta_por_el_puente():
    """El barrido sigue siendo el mismo: la primera que CONTESTA manda, y las que no
    contestaron se saltean sin tumbar el veredicto."""
    r = V.veredicto_conexion([
        {"tool": "muerta", "salida": _MUERTO_PUENTE},
        {"tool": "viva", "salida": '{"ok": true, "userID": 20856542}'},
    ])
    assert r["estado"] == V.VIVA and r["tool_usada"] == "viva"


# ── LA CREDENCIAL ES POR VARIABLE, NO UNA SOLA PARA TODAS ────────────────────────────
# El verificador resolvía UNA credencial (`spec["connector"]`) y la copiaba en TODOS los
# `${VAR}` de la receta. Para una pieza con llave sola alcanzaba; para OAuth es falso:
# `ONSHAPE_OAUTH_META` recibía el ACCESS TOKEN en vez de su JSON de estado, el server no
# reconocía ningún scope y publicaba CERO tools. El barrido lo anotaba `rota/sin_tools` y
# la card lo mostraba rojo con la pieza funcionando (la lectura real: 6 tools, whoami 200).

def test_cada_variable_de_credencial_tiene_SU_provider():
    spec = {"env": {"ONSHAPE_ACCESS_TOKEN": "${ONSHAPE_ACCESS_TOKEN}",
                    "ONSHAPE_OAUTH_META": "${ONSHAPE_OAUTH_META}",
                    "ONSHAPE_API_BASE": "https://cad.onshape.com/api/v16"}}
    m = V._providers_por_var(spec)
    assert m["ONSHAPE_ACCESS_TOKEN"] == "onshape"
    # el companion, que es OTRA fila del vault y OTRO valor
    assert m["ONSHAPE_OAUTH_META"] == "onshape__oauth"
    # un literal no es una credencial y no puede inventar un provider
    assert "ONSHAPE_API_BASE" not in m


def test_es_GENERICO_por_tipo_no_un_if_para_onshape():
    """Un conector que no existe en ningún catálogo tiene que mapear igual. Si esto
    fallara, la regla estaría escrita para un servicio y el conector 29 volvería a
    recibir el token en el lugar del estado."""
    spec = {"env": {"ZZQUENOEXISTE_ACCESS_TOKEN": "${ZZQUENOEXISTE_ACCESS_TOKEN}",
                    "ZZQUENOEXISTE_OAUTH_META": "${ZZQUENOEXISTE_OAUTH_META}",
                    "ZZQUENOEXISTE_API_KEY": "${ZZQUENOEXISTE_API_KEY}"}}
    m = V._providers_por_var(spec)
    assert m["ZZQUENOEXISTE_ACCESS_TOKEN"] == "zzquenoexiste"
    assert m["ZZQUENOEXISTE_OAUTH_META"] == "zzquenoexiste__oauth"
    assert m["ZZQUENOEXISTE_API_KEY"] == "zzquenoexiste"


def test_la_regla_NO_esta_copiada_en_el_verificador():
    """Anti-deriva. La traducción `${VAR}` → provider la define el RUN
    (`recipe_assembler._autofill_recipe_keys`). Dos copias de la misma regla terminan
    disintiendo, y un verificador que mide algo distinto de lo que el run inyecta es el
    bug que esto cerró. Se compara contra la fuente, no contra una constante."""
    RA = V._ra()
    for var in ("FOO_API_KEY", "FOO_ACCESS_TOKEN", "FOO_OAUTH_META"):
        esperado = next(iter(RA._autofill_recipe_keys(
            {}, {"_": {"env": {"_": "${" + var + "}"}}})))
        assert V._providers_por_var({"env": {var: "${" + var + "}"}})[var] == esperado


def test_sin_dueno_no_se_resuelve_nada():
    """Sin `owner` no hay a quién atribuirle una credencial: devuelve vacío y el spawn cae
    al comportamiento de siempre (la basura). Nunca adivina un dueño."""
    spec = {"env": {"X_ACCESS_TOKEN": "${X_ACCESS_TOKEN}"}}
    assert V._credenciales_por_var(spec, None, None) == {}
    assert V._credenciales_por_var(spec, "alguien", None) == {}
