"""test_traductor_errores.py — la tabla de equivalencias, fijada.

Cada regla del traductor tiene acá su test, y la mitad importante no prueba el traductor
solo: lo prueba **contra el clasificador real** (`diagnostico_conectores`) y **contra las
constantes reales** del verificador. Un traductor que se pone de acuerdo consigo mismo no
sirve para nada; lo que hay que fijar es que las dos taxonomías —la del cliente viejo y la
del SDK— entren al MISMO veredicto.

Los strings de entrada no son inventados: son los que cada cliente devuelve de verdad,
copiados de las mediciones de la sesión 1 (`MAPA-ERRORES-SDK.md`).

    python3 -m pytest platform/inspection/test_traductor_errores.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_AQUI = Path(__file__).resolve().parent
_REPO = _AQUI.parents[1]
if str(_AQUI) not in sys.path:
    sys.path.append(str(_AQUI))

import traductor_errores as T  # noqa: E402


def _por_ruta(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, str(ruta))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# El clasificador REAL y el verificador REAL, cargados por ruta (el backend no asume que
# `platform` sea un paquete; es el mismo patrón que usa el propio backend).
DC = _por_ruta("dc_para_traductor",
               _REPO / "product/backend/app/phase1/diagnostico_conectores.py")


# ══════════════════════════════════════════════════════════════════════════════════
# 0 · LAS CONSTANTES NO SE PUEDEN SEPARAR EN SILENCIO
# ══════════════════════════════════════════════════════════════════════════════════

def test_las_causas_no_derivan():
    """El traductor declara las causas por valor para no depender del backend. Si alguien
    renombra una allá, esto se pone rojo acá — que es todo el punto de la copia."""
    ruta = _REPO / "product/backend/app/phase1/conexiones_verificador.py"
    texto = ruta.read_text()
    for nombre, valor in (("C_TIMEOUT", T.C_TIMEOUT),
                          ("C_SIN_RESPUESTA", T.C_SIN_RESPUESTA),
                          ("C_ARRANQUE", T.C_ARRANQUE),
                          ("C_SIN_TOOLS", T.C_SIN_TOOLS)):
        assert f'{nombre} = "{valor}"' in texto, (
            f"{nombre} vale {valor!r} en el traductor pero no en conexiones_verificador.py")


def test_la_frase_del_saludo_sigue_siendo_la_que_el_clasificador_busca():
    """`SALUDO_SIN_RESPUESTA` existe para caer en una rama concreta del clasificador. Si la
    frase se separa, `no_es_mcp` se pierde en silencio y el fallo cae a `desconocido`."""
    ev = {"detail": T.SALUDO_SIN_RESPUESTA, "transport": "stdio"}
    v = DC.producir({"estado": "roto", "tipo": "mcp", "evidencia": ev}, destino="uvx")
    assert v["patron"]["codigo"] == "no_habla_mcp", v["patron"]


# ══════════════════════════════════════════════════════════════════════════════════
# 1 · LEER EL CÓDIGO
# ══════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("texto,esperado", [
    ("[MCP error: {'code': -32001, 'message': \"Request 'tools/call' timed out\"}]", T.TIMEOUT),
    ("[MCP error: {'code': -32000, 'message': 'Connection closed'}]", T.CONEXION_MUERTA),
    ("[MCP error: {'code': -32602, 'message': 'Invalid params', 'data': {'campo': 'x'}}]", -32602),
    ("[MCP error: {'code': -32603, 'message': 'Server returned an error response'}]", T.ERROR_INTERNO),
    # el cliente viejo: no hay código que leer
    ("[MCP error: no response from fetch]", None),
    ("[tool error] la tool falló adentro", None),
    ("Contents of https://example.com/: …", None),
    ("", None),
])
def test_codigo_de(texto, esperado):
    assert T.codigo_de(texto) == esperado


def test_codigo_de_sobrevive_un_mensaje_con_comillas_raras():
    """`literal_eval` falla y tiene que caer a la regex, no tumbar el diagnóstico."""
    roto = "[MCP error: {'code': -32000, 'message': 'no cerró la ' comilla}]"
    assert T.codigo_de(roto) == T.CONEXION_MUERTA


# ══════════════════════════════════════════════════════════════════════════════════
# 2 · LA EQUIVALENCIA — el corazón: las DOS taxonomías, el MISMO veredicto
# ══════════════════════════════════════════════════════════════════════════════════

#: (qué pasó, lo que devolvía el cliente VIEJO, lo que devuelve el PUENTE, ¿contestó?, causa)
EQUIVALENCIAS = [
    ("la tool anduvo",
     "Contents of https://example.com/: This domain is for use in…",
     "Contents of https://example.com/: This domain is for use in…",
     True, None),
    ("la tool falló adentro (isError)",
     "[tool error] la tool falló adentro",
     "[tool error] la tool falló adentro",
     True, None),
    ("el server rechazó la llamada (error JSON-RPC)",
     "[MCP error: {'code': -32602, 'message': 'Invalid params'}]",
     "[MCP error: {'code': -32602, 'message': 'Invalid params', 'data': {'campo': 'x'}}]",
     True, None),
    ("un 401 del servicio",
     "Unauthorized: invalid API key",
     "Unauthorized: invalid API key",
     True, None),
    ("la tool se colgó",
     "[MCP error: no response from fetch]",
     "[MCP error: {'code': -32001, 'message': \"Request 'tools/call' timed out\"}]",
     False, T.C_TIMEOUT),
    ("el server se murió",
     "[MCP error: no response from fetch]",
     "[MCP error: {'code': -32000, 'message': 'Connection closed'}]",
     False, T.C_SIN_RESPUESTA),
]


@pytest.mark.parametrize("caso,viejo,puente,contesto_esperado,causa",
                         [(c, v, p, ct, ca) for c, v, p, ct, ca in EQUIVALENCIAS])
def test_las_dos_taxonomias_dan_el_mismo_contesto(caso, viejo, puente, contesto_esperado, causa):
    assert T.contesto(viejo) is contesto_esperado, f"{caso}: cliente viejo"
    assert T.contesto(puente) is contesto_esperado, f"{caso}: puente"


@pytest.mark.parametrize("caso,viejo,puente,contesto_esperado,causa",
                         [(c, v, p, ct, ca) for c, v, p, ct, ca in EQUIVALENCIAS if ca])
def test_la_causa_tipada_del_puente_es_exacta(caso, viejo, puente, contesto_esperado, causa):
    """El puente da la causa por CÓDIGO. El cliente viejo no podía distinguir un timeout de
    una conexión muerta —los dos decían «no response»— y caía a `sin_respuesta`. La causa
    del puente es más precisa, y eso NO es un cambio de veredicto: `sin_respuesta` y
    `timeout` producen el mismo `estado: rota`."""
    assert T.causa_de_corte(puente) == causa, caso


def test_un_server_muerto_no_se_reporta_vivo():
    """EL ACOPLAMIENTO #1, el que habría sido un desastre silencioso.

    `veredicto_conexion` daba VIVA a cualquier salida no vacía que no matcheara
    `_NO_CONTESTO`. La frase del SDK —«Connection closed»— NO está en esa regex
    («connection reset» sí, «connection closed» no), así que un servidor muerto pasaba por
    vivo. Este test es el que fija que eso no puede volver."""
    muerto = "[MCP error: {'code': -32000, 'message': 'Connection closed'}]"
    import re
    regex_vieja = re.compile(r"(timed out|timeout|no response|sin respuesta|broken pipe"
                             r"|connection reset|no se pudo iniciar)", re.I)
    assert not regex_vieja.search(muerto), (
        "si la regex vieja ya lo caza, este traductor perdió su motivo — revisá el cambio")
    assert T.contesto(muerto) is False
    assert T.causa_de_corte(muerto) == T.C_SIN_RESPUESTA


def test_un_error_de_aplicacion_es_conexion_viva():
    """La regla que separa las dos preguntas del registro: un 401 —o cualquier error que el
    servidor CONTESTÓ— es conexión VIVA. Que la llave no sirva es la otra columna."""
    for texto in ("[MCP error: {'code': -32602, 'message': 'Invalid params'}]",
                  "[tool error] Unauthorized",
                  "Unauthorized: invalid API key"):
        assert T.contesto(texto) is True, texto


def test_el_codigo_gana_sobre_el_texto():
    """Un `Connection closed` cuyo mensaje mencionara «time» por casualidad se habría
    clasificado timeout con la regla vieja. El código se prueba primero."""
    trampa = "[MCP error: {'code': -32000, 'message': 'Connection closed at time 12:00'}]"
    assert T.causa_de_corte(trampa) == T.C_SIN_RESPUESTA


def test_sin_codigo_se_conserva_la_regla_vieja():
    """Un registro persistido por el cliente viejo se sigue leyendo igual."""
    assert T.causa_de_corte("[MCP error: no response from x]") == T.C_SIN_RESPUESTA
    assert T.causa_de_corte("Request timed out") == T.C_TIMEOUT


# ══════════════════════════════════════════════════════════════════════════════════
# 3 · EL PROTOCOLO — la deriva inventada
# ══════════════════════════════════════════════════════════════════════════════════

def _deriva(protocolo: dict) -> bool:
    """Le pregunta al clasificador REAL si esto es una deriva."""
    _c, _s, incompatible = DC._versiones_protocolo({"protocolo": protocolo})
    return incompatible


def test_una_negociacion_exitosa_no_es_deriva():
    """EL ACOPLAMIENTO #3. El SDK pide 2026-07-28 y baja a lo que el server ofrezca
    (medido: exa 2025-11-25, fetch 2025-11-25). Sin esta regla, TODA conexión por el puente
    tenía dos fechas distintas y cualquier fallo posterior salía `deriva_protocolo`."""
    p = T.protocolo_de(negociada="2025-11-25", solicitada="2026-07-28")
    assert p["cliente"] == p["servidor"] == "2025-11-25"
    assert p["solicitada"] == "2026-07-28"     # se conserva como evidencia, no deduce nada
    assert _deriva(p) is False


def test_la_deriva_se_declara_cuando_el_server_la_declara():
    """-32022 trae `requested`/`supported` normativos: ahí sí hay incompatibilidad."""
    p = T.protocolo_de(solicitada="2026-07-28", incompatible=True,
                       soportadas=["2024-11-05"])
    assert p["incompatible"] is True and p["negociacion"] == "fallida"
    assert p["cliente"] == "2026-07-28" and p["servidor"] == "2024-11-05"
    assert _deriva(p) is True


def test_el_veredicto_de_una_deriva_real_no_cambio():
    """La misma incompatibilidad, por el puente, sigue dando el mismo patrón que daba el
    cliente viejo."""
    ev = {"protocolo": T.protocolo_de(solicitada="2026-07-28", incompatible=True,
                                      soportadas=["2024-11-05"]),
          "transport": "stdio"}
    v = DC.producir({"estado": "roto", "tipo": "mcp", "evidencia": ev}, destino="uvx")
    assert v["patron"]["codigo"] == "deriva_protocolo", v["patron"]
    assert v["causa"] == DC.DERIVA_PROTOCOLO


# ══════════════════════════════════════════════════════════════════════════════════
# 4 · LA EVIDENCIA DE ARRANQUE
# ══════════════════════════════════════════════════════════════════════════════════

#: Las tres formas del arranque fallido, medidas en sesión 1: (mensaje crudo del SDK,
#: patrón que el clasificador tiene que seguir dando, causa)
ARRANQUES = [
    ("no pude iniciar el proceso MCP por el SDK: FileNotFoundError: [Errno 2] "
     "No such file or directory: 'comando-que-no-existe-jamas'",
     "runtime_ausente", "cli_no_instalado"),
    ("no pude iniciar el proceso MCP por el SDK: MCPError: Request 'initialize' timed out",
     "no_habla_mcp", DC.NO_ES_MCP),
    ("no pude iniciar el proceso MCP por el SDK: MCPError: Connection closed",
     "no_habla_mcp", DC.NO_ES_MCP),
]


@pytest.mark.parametrize("crudo,patron,causa", ARRANQUES)
def test_el_arranque_fallido_cae_en_el_mismo_escalon_que_antes(crudo, patron, causa):
    """EL ACOPLAMIENTO #2: sin traducir, las dos últimas caían a `desconocido`."""
    ev = T.evidencia_de_arranque({"detail": crudo, "transport": "stdio",
                                  "stderr": "", "command": "uvx"})
    v = DC.producir({"estado": "roto", "tipo": "mcp", "evidencia": ev}, destino="uvx")
    assert v["patron"]["codigo"] == patron, f"{crudo!r} → {v['patron']}"
    assert v["causa"] == causa
    assert v["escalon"] == DC.LOCAL


def test_sin_traducir_el_saludo_se_perdia():
    """La contracara del test de arriba: se prueba que el problema EXISTÍA. Si esto se pone
    verde, el clasificador aprendió la frase del SDK por su cuenta y el traductor sobra."""
    crudo = "no pude iniciar el proceso MCP por el SDK: MCPError: Request 'initialize' timed out"
    v = DC.producir({"estado": "roto", "tipo": "mcp",
                     "evidencia": {"detail": crudo, "transport": "stdio"}}, destino="uvx")
    assert v["patron"]["codigo"] == "desconocido"
    assert v["causa"] == DC.FALLO_DESCONOCIDO


def test_el_crudo_del_sdk_se_conserva_dentro_de_la_frase():
    """La frase canónica dice la CATEGORÍA; el crudo dice qué pasó. Perder el segundo sería
    cambiar un diagnóstico por una etiqueta."""
    d = T.detalle_de_arranque("MCPError: Request 'initialize' timed out")
    assert T.SALUDO_SIN_RESPUESTA in d and "timed out" in d


def test_el_exit_code_no_se_inventa_ni_se_tira():
    """Las dos mitades del contrato de `MCPServer.diagnostico()`.

    Por el PUENTE no hay exit code: `None` + el porqué, jamás un cero. Por el CLIENTE VIEJO
    sí lo hay, y el traductor no se lo borra — durante la migración los dos transportes
    conviven y degradar al que sí mide sería perder evidencia por prolijidad."""
    puente = T.evidencia_de_arranque({
        "detail": "x", "murio": True, "exit_code": None,
        "exit_code_fuente": "no expuesto por el transporte del SDK"})
    assert puente["exit_code"] is None
    assert puente["murio"] is True
    assert "no expuesto" in puente["exit_code_fuente"]

    viejo = T.evidencia_de_arranque({"detail": "x", "exit_code": 3})
    assert viejo["exit_code"] == 3, "el exit code MEDIDO no se descarta"
    assert "murio" not in viejo, "no se inventa `murio` para quien no lo mide"

    # un 0 REAL es un dato, no un invento: se conserva
    assert T.evidencia_de_arranque({"detail": "x", "exit_code": 0})["exit_code"] == 0
    # lo que no se acepta es un no-entero disfrazado de código
    assert T.evidencia_de_arranque({"detail": "x", "exit_code": "0"})["exit_code"] is None


def test_el_detalle_ya_canonico_no_se_envuelve_dos_veces():
    """Lo que ya viene del cliente viejo pasa intacto: envolverlo otra vez metería la
    frase adentro de sí misma y el texto que lee el usuario quedaría duplicado."""
    for frase in (T.SALUDO_SIN_RESPUESTA,
                  f"{T.SALUDO_RECHAZADO}: {{'code': -32602}}",
                  # la cadena literal que devuelve `MCPServer.start()` cuando el comando
                  # no existe, copiada de la medición
                  "no pude iniciar el proceso MCP: FileNotFoundError: [Errno 2] "
                  "No such file or directory: 'comando-que-no-existe-jamas'"):
        assert T.detalle_de_arranque(frase) == frase
        assert T.detalle_de_arranque(frase).count(T.SALUDO_SIN_RESPUESTA) <= 1


def test_el_exit_code_ausente_no_cambia_ningun_veredicto():
    """Lo que la sesión 1 no sabía: `exit_code` sólo alimenta el TEXTO humano
    (`crudo_de`), ninguna regla del clasificador se bifurca por él. Se prueba comparando
    el veredicto con y sin el campo."""
    base = {"detail": "no pude iniciar el proceso MCP: FileNotFoundError: [Errno 2] "
                      "No such file or directory: 'x'", "transport": "stdio", "stderr": ""}
    con = DC.producir({"estado": "roto", "tipo": "mcp",
                       "evidencia": {**base, "exit_code": 127}}, destino="uvx")
    sin = DC.producir({"estado": "roto", "tipo": "mcp",
                       "evidencia": {**base, "exit_code": None}}, destino="uvx")
    for campo in ("estado", "causa", "escalon", "corrio"):
        assert con[campo] == sin[campo], campo
    assert con["patron"] == sin["patron"]
    # lo ÚNICO que cambia es el texto, y cambia declarando el número que sí se midió
    assert "exit code: 127" in con["presentacion"]["detalle"]
    assert "exit code" not in sin["presentacion"]["detalle"]


def test_el_stderr_sobrevive_entero_con_sus_caps():
    """Los diagnósticos viven del stderr: el traductor no lo toca."""
    diag = {"stderr": "Traceback…\nModuleNotFoundError: No module named 'pandas'",
            "stderr_lineas": 2, "stderr_bytes": 60,
            "stderr_cap_bytes": 32768, "stderr_cap_lineas": 80,
            "detail": "no pude iniciar el proceso MCP por el SDK: MCPError: Connection closed",
            "transport": "stdio", "command": "python3"}
    ev = T.evidencia_de_arranque(diag)
    for k in ("stderr", "stderr_lineas", "stderr_bytes", "stderr_cap_bytes", "stderr_cap_lineas"):
        assert ev[k] == diag[k], k
    # y con ese stderr el clasificador sigue dando `servidor_incompatible`, que es la
    # regla que mira la traza del hijo ANTES que el texto del transporte
    v = DC.producir({"estado": "roto", "tipo": "mcp", "evidencia": ev}, destino="python3")
    assert v["patron"]["codigo"] == "server_roto_o_incompatible"
    assert v["causa"] == DC.SERVIDOR_INCOMPATIBLE
