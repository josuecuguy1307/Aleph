"""test_prueba_credencial.py — el cuarto requisito: que el verde MIDA la credencial.

EL BUG QUE CIERRA, medido en la app instalada: `REQUISITOS_MCP` tenía tres requisitos
—spec · handshake · tools— y ninguno tocaba la llave. Con `clave-falsa-de-prueba-0000`
SIETE conectores quedaban 🟢 «Conectado» con tools completas. El server arranca y publica
su catálogo igual: la llave recién viaja cuando se LLAMA una tool, así que el fallo
aparecía en medio de una tarea del usuario.

Los tests están escritos contra los fallos que importan, no contra la implementación:

  1. una llave rechazada NO puede dar ok            (si da, el verde no mide nada)
  2. sin tool declarada NO se inventa una           (amarillo, jamás verde y jamás rojo)
  3. sólo se llama lo DECLARADO                     (nada del usuario llega a un call_tool)
  4. una declaración vieja se reporta como del CATÁLOGO, no como culpa de la llave
  5. un 402/500 no se confunde con un rechazo de credencial

Correr:  pytest platform/inspection/test_prueba_credencial.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inspection import byo_mcp as B  # noqa: E402


class ClienteDoble:
    """Doble del cliente MCP: registra QUÉ se le llamó y devuelve lo que se le diga."""

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.llamadas = []

    def call_tool(self, name, args):
        self.llamadas.append((name, args))
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        return self.respuesta


TOOLS = [{"name": "whoami"}, {"name": "create_item"}, {"name": "list_items"}]


# ── 1 · el rechazo se detecta ────────────────────────────────────────────────────

@pytest.mark.parametrize("cuerpo", [
    '[tool error] {"ok": false, "status": 403, "detail": "Invalid key"}',   # zotero real
    "[tool error] web_search_exa error (401): Invalid API key",             # exa real
    "[tool error] Unauthorized",
    "[tool error] authentication failed",
    "[tool error] bad credentials",
])
def test_una_llave_RECHAZADA_nunca_da_ok(cuerpo):
    """EL TEST QUE DECIDE TODO. Si esto pasa a verde, el requisito no mide nada y la
    sorpresa vuelve al medio de la tarea del usuario. Los dos primeros cuerpos son las
    respuestas REALES medidas contra zotero y exa con `clave-falsa-de-prueba-0000`."""
    r = B._ejercitar_credencial(ClienteDoble(cuerpo), TOOLS, {"tool": "whoami", "args": {}})
    assert r["ok"] is False
    assert r["rechazada"] is True


def test_una_llave_BUENA_da_ok_con_la_muestra():
    """La respuesta real de zotero con la llave verdadera."""
    r = B._ejercitar_credencial(
        ClienteDoble('{"ok": true, "userID": 20856542, "username": "demo-user_12345"}'),
        TOOLS, {"tool": "whoami", "args": {}})
    assert r["ok"] is True and r["tool"] == "whoami"
    assert "20856542" in r["muestra"], "la evidencia viaja: sin muestra no hay cómo auditar"


# ── 2 · sin declaración NO se inventa ────────────────────────────────────────────

@pytest.mark.parametrize("prueba", [None, {}, {"tool": ""}, {"tool": "   "}, "whoami", 42])
def test_sin_tool_declarada_devuelve_None_y_NO_llama_nada(prueba):
    """`None` significa «no lo medí», y el caller lo traduce a AMARILLO. Inventar una tool
    —la primera de la lista, una que empiece con get_— es exactamente cómo se vuelve a
    afirmar sin medir: algunas escriben, algunas cuestan, algunas piden argumentos que no
    se pueden adivinar."""
    doble = ClienteDoble("lo que sea")
    assert B._ejercitar_credencial(doble, TOOLS, prueba) is None
    assert doble.llamadas == [], "no se puede llamar NADA sin declaración"


# ── 3 · sólo se llama lo declarado ───────────────────────────────────────────────

def test_llama_EXACTAMENTE_la_tool_y_los_args_declarados():
    """La garantía que este código SÍ puede dar: nada que venga del usuario llega a un
    `call_tool`. Que la tool sea de LECTURA es responsabilidad del catálogo — desde acá
    `whoami` y `create_item` son indistinguibles."""
    doble = ClienteDoble("ok")
    B._ejercitar_credencial(doble, TOOLS, {"tool": "list_items", "args": {"limit": 1}})
    assert doble.llamadas == [("list_items", {"limit": 1})]


def test_una_tool_que_el_server_NO_publica_no_se_invoca():
    """Y el mensaje dice que el problema es del CATÁLOGO, no de la llave del usuario:
    mandarlo a re-pegar una credencial que está bien es hacerle perder el tiempo con algo
    que no puede arreglar."""
    doble = ClienteDoble("ok")
    r = B._ejercitar_credencial(doble, TOOLS, {"tool": "ya_no_existe", "args": {}})
    assert doble.llamadas == []
    assert r["ok"] is False and r["declarada_no_existe"] is True
    assert "catálogo" in r["detalle"] and "no de tu llave" in r["detalle"]


def test_los_args_declarados_se_copian_y_no_se_comparten():
    declarados = {"query": "x"}
    doble = ClienteDoble("ok")
    B._ejercitar_credencial(doble, [{"name": "buscar"}], {"tool": "buscar", "args": declarados})
    doble.llamadas[0][1]["query"] = "mutado"
    assert declarados == {"query": "x"}, "el dict del catálogo no se muta"


# ── 4 · un fallo que NO es la credencial no se disfraza de rechazo ───────────────

def test_un_402_no_es_un_rechazo_de_credencial():
    """MEDIDO en fred: sus tools de datos devuelven 402 `no_wallet` con CUALQUIER llave.
    Marcarlo «credencial inválida» mandaría al usuario a re-pegar una llave que está bien;
    el problema es que la cuenta no tiene saldo."""
    r = B._ejercitar_credencial(
        ClienteDoble('[tool error] {"status": 402, "error": "payment_required"}'),
        [{"name": "fed_rates"}], {"tool": "fed_rates", "args": {}})
    assert r["ok"] is False
    assert not r.get("rechazada"), "402 no es 401"
    assert "no es la credencial" in r["detalle"]


def test_si_el_call_explota_se_reporta_sin_tumbar_la_sonda():
    r = B._ejercitar_credencial(ClienteDoble(RuntimeError("se cayó el pipe")),
                                TOOLS, {"tool": "whoami", "args": {}})
    assert r["ok"] is False and "se cayó el pipe" in r["detalle"]
    assert not r.get("rechazada")


# ── 5 · el cliente HTTP devuelve dict, no str ────────────────────────────────────

def test_el_isError_del_cliente_HTTP_no_pasa_por_bueno():
    """`MCPServer` (stdio) devuelve str con «[tool error]»; `MCPHttpClient` devuelve el
    dict crudo con `isError`. Tratar los dos como texto suelto dejaba pasar el segundo."""
    r = B._ejercitar_credencial(
        ClienteDoble({"isError": True, "content": [{"type": "text", "text": "algo falló"}]}),
        TOOLS, {"tool": "whoami", "args": {}})
    assert r["ok"] is False


def test_el_dict_HTTP_con_401_se_marca_rechazado():
    r = B._ejercitar_credencial(
        ClienteDoble({"isError": True, "content": [{"type": "text", "text": "401 Unauthorized"}]}),
        TOOLS, {"tool": "whoami", "args": {}})
    assert r["ok"] is False and r["rechazada"] is True


def test_el_dict_HTTP_bueno_da_ok():
    r = B._ejercitar_credencial(
        ClienteDoble({"content": [{"type": "text", "text": "todo bien"}]}),
        TOOLS, {"tool": "whoami", "args": {}})
    assert r["ok"] is True and "todo bien" in r["muestra"]


# ── 6 · una respuesta EXITOSA que HABLA de 401 no es un rechazo ──────────────────

def test_una_respuesta_exitosa_que_menciona_401_NO_es_un_rechazo():
    """MEDIDO con `coingecko.search_docs`: devolvió 5349 caracteres de documentación —una
    respuesta correcta— que incluyen la tabla de errores de la API:

        | 400 | BadRequestError | | 401 | AuthenticationError | | 403 | PermissionDenied |

    Buscar las marcas en cualquier texto leía esa documentación como un rechazo de
    credencial. Una tool que respondió CON DATOS no rechazó nada, diga lo que diga su
    texto: las marcas sólo cuentan cuando la llamada falló."""
    # La forma REAL: 5349 chars que ABREN con un ejemplo de código y traen la tabla de
    # errores enterrada más abajo. Que la mención esté lejos del arranque es el dato.
    docs = ("```python\nclient.with_options(max_retries=5).simple.price.get(\n"
            "    vs_currencies=\"usd\", ids=\"bitcoin\",\n)\n```\n"
            + "Documentación del SDK. " * 120 +
            "\nCódigos de error de la API:\n"
            "| 400 | BadRequestError |\n| 401 | AuthenticationError |\n"
            "| 403 | PermissionDeniedError |\n| 404 | NotFoundError |\n")
    r = B._ejercitar_credencial(ClienteDoble(docs), [{"name": "search_docs"}],
                                {"tool": "search_docs", "args": {"query": "bitcoin"}})
    assert r["ok"] is True, "una respuesta con datos es un éxito"
    assert not r.get("rechazada")


def test_un_rechazo_que_llega_como_respuesta_EXITOSA_igual_se_detecta():
    """EL CASO CONTRARIO, y también medido: `context7.resolve-library-id` devuelve
    «Invalid API key. Please check your API key…» SIN marcar error — el rechazo viaja en
    el contenido de una respuesta exitosa. Exigir que la llamada hubiera fallado lo dejaba
    pasar como verde, que es el fallo peor de los dos.

    Lo que separa este caso del de arriba no es el éxito ni el largo: es que el rechazo va
    AL PRINCIPIO —es el mensaje— y la mención incidental va enterrada."""
    r = B._ejercitar_credencial(
        ClienteDoble("Invalid API key. Please check your API key. "
                     "API keys should start with 'ctx7sk' prefix."),
        [{"name": "resolve-library-id"}], {"tool": "resolve-library-id", "args": {}})
    assert r["ok"] is False and r["rechazada"] is True


def test_el_mismo_texto_SI_es_rechazo_cuando_la_llamada_falló():
    """El contraste: la marca vale, pero sólo sobre un fallo."""
    r = B._ejercitar_credencial(
        ClienteDoble("[tool error] 401 AuthenticationError"), [{"name": "x"}],
        {"tool": "x", "args": {}})
    assert r["ok"] is False and r["rechazada"] is True


def test_el_dict_HTTP_exitoso_que_menciona_401_tampoco_es_rechazo():
    r = B._ejercitar_credencial(
        ClienteDoble({"content": [{"type": "text",
                                   "text": "Guía de uso. " * 40 + " tabla: 401 = unauthorized"}]}),
        [{"name": "x"}], {"tool": "x", "args": {}})
    assert r["ok"] is True and not r.get("rechazada")
