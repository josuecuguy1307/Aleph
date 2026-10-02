"""test_repair_clasificar.py — R2 · LA TABLA DEL §2.2, CONGELADA.

Lo que se fija:

  1. **la tabla, causa por causa** — si alguien cambia una clase o un botón, se pone rojo
     acá y no en producción;
  2. **los grises con su desempate** (§2.3): `timeout` por `murio`, `arranque` por la causa
     refinada, `429` por `retry_after_s`;
  3. **la anti-deriva**: los valores declarados en `repair_clasificar` son los MISMOS que en
     `motor_verdad`, `errores_modelo` y `conexiones_verificador` — la copia existe porque
     `platform/` no puede depender de `product/backend`, no para poder separarse;
  4. **el vocabulario no puede crecer sin la tabla**: si `motor_verdad.CAUSAS` suma una causa
     y `repair_clasificar` no la cubre, esto revienta. Es el mismo molde que
     `test_traductor_errores.py::test_las_causas_no_derivan`;
  5. **CERO clasificación por nombre de excepción** — la lección de R1, congelada: el módulo
     no puede nombrar un tipo de excepción para decidir nada;
  6. **es pura**: mismos argumentos, mismo resultado, y no muta lo que le pasan.

    python3 -m pytest platform/inspection/test_repair_clasificar.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/inspection", _RAIZ / "platform/assembler",
           _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import repair_clasificar as RC                              # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════════
# 1 · LA TABLA DEL §2.2, CAUSA POR CAUSA
# ══════════════════════════════════════════════════════════════════════════════════

#: (causa, clase, accion, boton). Copiada del §2.2 del DISEÑO-REPAIR-v1 a mano y a
#: propósito: si el código y el diseño se separan, esta lista es la que grita.
_ESPERADO = [
    # temporales
    ("sin_red",                 RC.TEMPORAL,   RC.BACKOFF,     None),
    ("rate_limit",              RC.TEMPORAL,   RC.BACKOFF,     None),
    ("proveedor_caido",         RC.TEMPORAL,   RC.BACKOFF,     None),
    ("sin_runtime",             RC.TEMPORAL,   RC.BACKOFF,     None),
    ("sin_respuesta",           RC.TEMPORAL,   RC.BACKOFF,     None),
    ("error_upstream",          RC.TEMPORAL,   RC.UNA_VUELTA,  None),
    # permanentes con botón
    ("key_invalida",            RC.PERMANENTE, RC.BOTON,       RC.B_REVISAR_LLAVE),
    ("sin_credito",             RC.PERMANENTE, RC.BOTON,       RC.B_REVISAR_LLAVE),
    ("falta_key",               RC.PERMANENTE, RC.BOTON,       RC.B_CONECTAR),
    ("sin_sesion",              RC.PERMANENTE, RC.BOTON,       RC.B_RECONECTAR),
    ("oauth_revocado",          RC.PERMANENTE, RC.BOTON,       RC.B_RECONECTAR),
    ("plan_insuficiente",       RC.PERMANENTE, RC.BOTON,       RC.B_REVISAR_PLAN),
    ("modelo_no_disponible",    RC.PERMANENTE, RC.BOTON,       RC.B_REVISAR_LLAVE),
    ("cli_no_instalado",        RC.PERMANENTE, RC.BOTON,       RC.B_DESCARGAR),
    ("cli_version_vieja",       RC.PERMANENTE, RC.BOTON,       RC.B_ACTUALIZAR),
    ("servidor_incompatible",   RC.PERMANENTE, RC.BOTON,       RC.B_FIJAR_VERSION),
    ("falla_de_aleph",          RC.PERMANENTE, RC.BOTON,       RC.B_COPIAR_REPORTE),
    # permanentes sin botón
    ("cli_sin_permisos",        RC.PERMANENTE, RC.MANO_HUMANA, None),
    ("cli_interactivo_colgado", RC.PERMANENTE, RC.MANO_HUMANA, None),
    ("no_es_mcp",               RC.PERMANENTE, RC.ESCALAR,     None),
    ("fallo_desconocido",       RC.PERMANENTE, RC.ESCALAR,     None),
    # extensión declarada más allá del §2.2 (causas del verificador)
    ("sin_tools",               RC.PERMANENTE, RC.ESCALAR,     None),
    ("sin_tool_sondeable",      RC.PERMANENTE, RC.ESCALAR,     None),
    # GATE 2 · F1c — las seis selladas
    ("cli_ocupado",             RC.TEMPORAL,   RC.BACKOFF,     None),
    ("runtime_ocupado",         RC.TEMPORAL,   RC.BACKOFF,     None),
    ("sesion_perdida",          RC.TEMPORAL,   RC.BACKOFF,     None),
    ("contexto_excedido",       RC.PERMANENTE, RC.MANO_HUMANA, None),
    ("politica_de_contenido",   RC.PERMANENTE, RC.MANO_HUMANA, None),
    ("turno_detenido",          RC.PERMANENTE, RC.SIN_ALARMA,  None),
    # GATE 2 · F8 — la llave está y no hay modelo: se elige, no se reintenta
    ("modelo_no_elegido",       RC.PERMANENTE, RC.BOTON,       RC.B_ELEGIR_MODELO),
    # GATE 3 · obra A — las dos de la costura de tools. Cada una sale de lo que su propia
    # vara selló (`verify_costura_obra2.py:202-208`), no de un parecido con otra causa:
    #   argumentos_invalidos  origen=modelo · reintentable=True   → TEMPORAL
    #   gate_bloqueado        origen=aleph  · reintentable=False  → PERMANENTE, y NO es fallo
    ("argumentos_invalidos",    RC.TEMPORAL,   RC.UNA_VUELTA,  None),
    ("gate_bloqueado",          RC.PERMANENTE, RC.SIN_ALARMA,  None),
    # GATE 3 · obra B — el turno SALIÓ, con el modelo de respaldo. No es un fallo.
    ("modelo_sustituido",       RC.PERMANENTE, RC.SIN_ALARMA,  None),
]


#: LAS QUE NO SON FALLOS. La lista blanca de `SIN_ALARMA`, y **es una lista blanca a
#: propósito**: la acción que no hace nada es la más fácil de abusar —cualquier causa
#: incómoda se calla poniéndola acá— así que sumar una tiene que costar tocar este archivo
#: y escribir por qué.
#:
#: [GATE 3 · obra A] Nace la segunda. `turno_detenido` estaba sola desde F1c y el guard la
#: nombraba directo (`causa == "turno_detenido"`); ensancharlo a un conjunto es la decisión
#: que el propio diccionario pedía que fuera explícita («que crezca tiene que ser una
#: decisión, no un descuido», `cuarto.semaforo.js:150`).
#:
#:   turno_detenido  lo paró el usuario: el sistema hizo lo que se le pidió.
#:   gate_bloqueado  el gate hizo su trabajo y está preguntando. **EL GATE ES PROTECCIÓN, NO
#:                   FALLO** — acta de persona usuaria (2026-08-06), la misma que ordena la obra 5.
#:
#: Las dos comparten la forma: el sistema funcionó, y lo que hay en pantalla es una decisión
#: de la persona, no algo roto. Ninguna otra causa del árbol tiene esa forma hoy.
#: [GATE 3 · obra B] Y nace la tercera, con una forma DISTINTA de las dos primeras y por eso
#: vale escribirlo: `turno_detenido` y `gate_bloqueado` son decisiones de LA PERSONA, y
#: `modelo_sustituido` es una decisión de ALEPH. Lo que las tres comparten —y es lo que la
#: lista blanca guarda— es que **el sistema hizo lo correcto y no hay nada que reparar**: en
#: las dos primeras porque se respetó a la persona, en ésta porque la red de seguridad
#: funcionó y el turno salió. Alarmar por cualquiera de las tres sería mentir sobre un
#: resultado que estuvo bien.
_NO_SON_FALLOS = frozenset({"turno_detenido", "gate_bloqueado", "modelo_sustituido"})


@pytest.mark.parametrize("causa,clase,accion,boton", _ESPERADO)
def test_la_tabla_del_diseno(causa, clase, accion, boton):
    v = RC.clasificar(causa)
    assert v.clase == clase, f"{causa}: clase {v.clase!r}, esperada {clase!r}"
    assert v.accion == accion, f"{causa}: acción {v.accion!r}, esperada {accion!r}"
    assert v.boton == boton, f"{causa}: botón {v.boton!r}, esperado {boton!r}"
    assert v.razon, f"{causa}: sin razón — la traza del §5 la necesita"


def test_toda_causa_permanente_termina_en_algo_que_el_usuario_pueda_ver():
    """Un permanente sin botón, sin mano_humana y sin escalada sería un fallo MUDO: la card
    quedaría roja y sin nada que apretar ni nada que leer.

    LA ÚNICA EXCEPCIÓN, declarada (Gate 2 · F1c): `turno_detenido` sale con `SIN_ALARMA`
    porque **no es un fallo**. La invariante de arriba habla de fallos: si algo se rompió,
    el usuario tiene que poder hacer algo o leer algo. Un turno que la persona paró no se
    rompió — el sistema hizo exactamente lo que le pidieron. Ofrecerle un botón, un comando
    o una escalada por su propia decisión es ruido, no honestidad.
    """
    for causa, clase, accion, boton in _ESPERADO:
        if clase != RC.PERMANENTE:
            continue
        if accion == RC.SIN_ALARMA:
            assert causa in _NO_SON_FALLOS, (
                f"{causa}: SIN_ALARMA es SÓLO para lo que no es un fallo. Cualquier otra "
                f"causa con esta acción es un fallo mudo.")
            continue
        assert accion in (RC.BOTON, RC.MANO_HUMANA, RC.ESCALAR), causa
        if accion == RC.BOTON:
            assert boton, f"{causa}: acción BOTON sin botón"


def test_ningun_temporal_manda_a_pedir_credencial():
    """REGLA SELLADA (§3.5): jamás re-pedir credencial por un error temporal. Le pide al
    usuario que vaya a buscar una llave que está perfecta."""
    _DE_CREDENCIAL = {RC.B_RECONECTAR, RC.B_REVISAR_LLAVE, RC.B_CONECTAR}
    for causa, clase, _accion, boton in _ESPERADO:
        if clase == RC.TEMPORAL:
            assert boton not in _DE_CREDENCIAL, f"{causa} es temporal y manda a {boton}"
    for causa in sorted(RC.GRISES):
        for ev in ({}, {"murio_por_eof": True}, {"murio_por_eof": False}):
            v = RC.clasificar(causa, evidencia=ev)
            if v.es_temporal:
                assert v.boton not in _DE_CREDENCIAL, (causa, ev, v.boton)


# ══════════════════════════════════════════════════════════════════════════════════
# 2 · LOS GRISES (§2.3)
# ══════════════════════════════════════════════════════════════════════════════════

def test_gris_timeout_desempata_por_murio_no_por_el_tipo():
    """`murio` sale del EOF del pipe (R1) — es un hecho del SO, no una interpretación."""
    murio = RC.clasificar("timeout", evidencia={"murio_por_eof": True})
    assert murio.desempate == "murio" and murio.es_temporal
    assert "es el server" in murio.razon

    colgado = RC.clasificar("timeout", evidencia={"murio_por_eof": False})
    assert colgado.desempate == "murio" and colgado.es_temporal
    assert "colgado" in colgado.razon
    assert colgado.señales.get("sospecha_de_cuelgue") is True, (
        "un server trabado no merece la misma paciencia que una red que se cae")


def test_gris_timeout_sin_evidencia_lo_DICE_en_vez_de_inventar_un_desempate():
    v = RC.clasificar("timeout", evidencia={})
    assert v.es_temporal
    assert v.desempate is None, "sin evidencia no puede haber desempate"
    assert "sin evidencia" in v.razon


def test_gris_timeout_usa_el_reloj_cuando_no_sabe_si_murio():
    """El reloj es la segunda señal, y también es un hecho medido (R1 lo anota filtrando por
    `transcurrido >= limite*0.9`), no un nombre de excepción."""
    v = RC.clasificar("timeout", evidencia={
        "timeouts": [{"vencio_el_reloj": True, "timeout_s": 30.0, "quien": "x"}]})
    assert v.desempate == "reloj" and v.es_temporal


def test_gris_arranque_usa_la_causa_YA_refinada_por_quien_midio():
    """Repair PREGUNTA, no mide (§2.3): si el diagnóstico ya refinó, se usa eso."""
    v = RC.clasificar("arranque", evidencia={"causa_refinada": "servidor_incompatible"})
    assert v.causa == "servidor_incompatible"
    assert v.clase == RC.PERMANENTE and v.boton == RC.B_FIJAR_VERSION
    assert v.desempate == "causa_refinada"

    v2 = RC.clasificar("arranque", evidencia={"causa_refinada": "cli_no_instalado"})
    assert v2.boton == RC.B_DESCARGAR and v2.clase == RC.PERMANENTE


def test_gris_arranque_sin_refinar_es_TEMPORAL_y_es_una_decision():
    """El error barato es reintentar algo permanente (5 intentos acotados y la escalada lo
    levanta igual). El caro es mandar a una persona a arreglar un hipo."""
    v = RC.clasificar("arranque", evidencia={})
    assert v.es_temporal and v.accion == RC.BACKOFF
    assert v.desempate is None
    assert v.señales.get("sin_refinar") is True


def test_retry_after_manda_sobre_la_curva():
    """§2.3: el proveedor sabe mejor que nuestro backoff."""
    v = RC.clasificar("rate_limit", evidencia={"retry_after_s": 42})
    assert v.retry_after_s == 42.0 and v.es_temporal
    assert "42" in v.razon


def test_retry_after_no_se_aplica_a_un_permanente():
    """Un 401 con `Retry-After` no se vuelve reintentable por traer el header."""
    v = RC.clasificar("key_invalida", evidencia={"retry_after_s": 42})
    assert v.clase == RC.PERMANENTE and v.retry_after_s is None


def test_una_causa_desconocida_escala_y_no_adivina():
    v = RC.clasificar("algo_que_no_existe")
    assert v.clase == RC.PERMANENTE and v.accion == RC.ESCALAR
    assert v.señales.get("no_cubierta") is True
    assert "algo_que_no_existe" in v.razon, "la causa desconocida tiene que ir en la traza"


# ══════════════════════════════════════════════════════════════════════════════════
# 3 · DESDE EL EVENTO DE R1
# ══════════════════════════════════════════════════════════════════════════════════

def test_la_lapida_y_la_ociosidad_NO_son_fallos():
    """El dueño emite SIEMPRE (decisión 6.A del diseño) y quien filtra es repair."""
    for disp in ("LAPIDA", "OCIOSIDAD", "LRU", "CIERRE"):
        v = RC.clasificar_muerte({"disparador": disp})
        assert v.señales.get("no_es_fallo") is True, disp
        assert v.accion == RC.ESCALAR and v.boton is None


def test_una_muerte_con_causa_medida_usa_esa_causa():
    v = RC.clasificar_muerte({"disparador": "EOF", "causa": "key_invalida"})
    assert v.boton == RC.B_REVISAR_LLAVE


def test_una_muerte_sin_causa_no_inventa_una():
    """Una muerte no es, por sí sola, una causa. Se clasifica lo que SÍ se sabe."""
    v = RC.clasificar_muerte({"disparador": "EOF", "murio_por_eof": True})
    assert v.causa == "timeout" and v.desempate == "murio"
    assert v.es_temporal


def test_un_fallo_de_arranque_entra_por_el_gris_de_arranque():
    v = RC.clasificar_muerte({"disparador": "R3", "causa_refinada": "cli_no_instalado"})
    assert v.boton == RC.B_DESCARGAR


# ══════════════════════════════════════════════════════════════════════════════════
# 4 · ANTI-DERIVA (la copia existe para no depender del backend, no para separarse)
# ══════════════════════════════════════════════════════════════════════════════════

def test_las_causas_no_derivan_del_motor():
    texto = (_RAIZ / "product/backend/app/phase1/motor_verdad.py").read_text()
    for nombre in ("SIN_RED", "TIMEOUT", "ERROR_UPSTREAM", "RATE_LIMIT", "PROVEEDOR_CAIDO",
                   "FALTA_KEY", "KEY_INVALIDA", "SIN_CREDITO", "SIN_SESION",
                   "PLAN_INSUFICIENTE", "MODELO_NO_DISPONIBLE", "CLI_NO_INSTALADO",
                   "CLI_VERSION_VIEJA", "CLI_SIN_PERMISOS", "CLI_INTERACTIVO_COLGADO",
                   "FALLA_DE_ALEPH"):
        valor = getattr(RC, nombre)
        assert f'{nombre} = "{valor}"' in texto, (
            f"{nombre} vale {valor!r} en repair_clasificar pero no en motor_verdad.py")


def test_las_causas_no_derivan_del_verificador():
    texto = (_RAIZ / "product/backend/app/phase1/conexiones_verificador.py").read_text()
    for nombre, attr in (("C_ARRANQUE", "C_ARRANQUE"), ("C_SIN_TOOLS", "C_SIN_TOOLS"),
                         ("C_SIN_CANDIDATA", "C_SIN_CANDIDATA"),
                         ("C_SIN_RESPUESTA", "C_SIN_RESPUESTA")):
        valor = getattr(RC, attr)
        assert f'{nombre} = "{valor}"' in texto, (
            f"{nombre} vale {valor!r} acá pero no en conexiones_verificador.py")


def test_reintentables_no_deriva_de_gate2():
    """`_REINTENTABLES_GATE2` es la copia de `errores_modelo._REINTENTABLES`. Si gate2 mueve
    una, esto se entera — que es todo el punto de copiar en vez de divergir."""
    import errores_modelo as EM
    assert RC._REINTENTABLES_GATE2 == EM._REINTENTABLES, (
        f"gate2 dice {sorted(EM._REINTENTABLES)} y repair copió "
        f"{sorted(RC._REINTENTABLES_GATE2)}")


def test_todo_reintentable_de_gate2_es_TEMPORAL_aca():
    """«Temporal ≡ reintentable, extendido» (§2.1). Extendido significa que puede haber MÁS
    temporales acá, nunca menos: una causa que gate2 reintenta y repair diera por permanente
    sería el producto contradiciéndose sobre la misma palabra."""
    for causa in sorted(RC._REINTENTABLES_GATE2):
        v = RC.clasificar(causa, evidencia={})
        assert v.es_temporal, f"gate2 reintenta {causa!r} y repair lo da por {v.clase}"


def test_el_vocabulario_del_motor_no_puede_crecer_sin_esta_tabla():
    """EL TEST QUE EL DISEÑO PIDE. Si `motor_verdad.CAUSAS` suma una causa y
    `repair_clasificar` no la cubre, repair la mandaría a la escalada sin haberla pensado —
    que es un fallo silencioso disfrazado de comportamiento razonable."""
    from app.phase1 import motor_verdad as MV
    faltan = sorted(set(MV.CAUSAS) - RC.CAUSAS_CUBIERTAS)
    assert not faltan, (
        f"causas del motor sin clasificar en repair: {faltan}. Agregalas a `_TABLA` (o a "
        f"`GRISES` si su clase depende de la evidencia) y a `_ESPERADO` de este test.")


def test_la_tabla_no_inventa_causas_que_nadie_emite():
    """Al revés que el anterior: una entrada de la tabla que ningún módulo emite es código
    muerto que aparenta cobertura."""
    from app.phase1 import motor_verdad as MV
    from app.phase1 import conexiones_verificador as CV
    import errores_modelo as EM
    conocidas = set(MV.CAUSAS) | set(EM.CAUSAS) | {
        CV.C_ARRANQUE, CV.C_SIN_TOOLS, CV.C_SIN_CANDIDATA, CV.C_SIN_RESPUESTA, CV.C_TIMEOUT}
    sobran = sorted(RC.CAUSAS_CUBIERTAS - conocidas)
    assert not sobran, f"repair clasifica causas que nadie emite: {sobran}"


# ══════════════════════════════════════════════════════════════════════════════════
# 5 · CERO CLASIFICACIÓN POR NOMBRE DE EXCEPCIÓN (la lección de R1)
# ══════════════════════════════════════════════════════════════════════════════════

#: Tipos de excepción que serían la tentación obvia. R1 midió por qué no sirven: el SDK usa
#: `McpError` TANTO para «el server contestó un error» COMO para «venció el reloj».
_TIPOS_PROHIBIDOS = {
    "TimeoutError", "McpError", "MCPError", "BrokenPipeError", "ConnectionError",
    "ConnectionResetError", "OSError", "RuntimeError", "asyncio", "anyio",
}


def test_el_clasificador_no_nombra_un_tipo_de_excepcion():
    """Congelado: acá se clasifica por CAUSA TIPADA y, en los grises, por el RELOJ o la
    EVIDENCIA. Nunca por el nombre de la excepción — el tipo no distingue quién dijo «se
    acabó el tiempo», y eso está MEDIDO (R1)."""
    fuente = (_AQUI / "repair_clasificar.py").read_text()
    arbol = ast.parse(fuente)
    nombres = {n.id if isinstance(n, ast.Name) else n.attr
               for n in ast.walk(arbol) if isinstance(n, (ast.Name, ast.Attribute))}
    usados = nombres & _TIPOS_PROHIBIDOS
    assert not usados, (
        f"`repair_clasificar` nombra tipos de excepción EN CÓDIGO: {sorted(usados)}. La "
        f"clasificación va por causa tipada, reloj o evidencia — nunca por el tipo.")


def test_el_clasificador_no_captura_excepciones():
    """No tiene qué capturar: es una función pura sobre dicts. Un `try/except` acá sería la
    puerta por la que entra la clasificación por tipo."""
    arbol = ast.parse((_AQUI / "repair_clasificar.py").read_text())
    handlers = [n for n in ast.walk(arbol) if isinstance(n, ast.ExceptHandler)]
    assert not handlers, "un clasificador puro no captura excepciones"


# ══════════════════════════════════════════════════════════════════════════════════
# 6 · ES PURA
# ══════════════════════════════════════════════════════════════════════════════════

def test_es_determinista():
    ev = {"murio_por_eof": False, "timeouts": [{"vencio_el_reloj": True}]}
    a, b = RC.clasificar("timeout", evidencia=ev), RC.clasificar("timeout", evidencia=ev)
    assert a.como_dict() == b.como_dict()


def test_no_muta_la_evidencia_que_le_pasan():
    ev = {"murio_por_eof": True, "retry_after_s": 5}
    copia = dict(ev)
    RC.clasificar("timeout", evidencia=ev)
    assert ev == copia, "el clasificador mutó la evidencia del llamante"


def test_el_veredicto_es_inmutable():
    v = RC.clasificar("sin_red")
    with pytest.raises(Exception):
        v.clase = RC.PERMANENTE           # type: ignore[misc]


def test_el_modulo_no_hace_IO():
    """Pura de verdad: sin red, sin disco, sin subprocess. Si algún día necesita medir algo,
    deja de ser clasificación y pasa a ser otra cosa (§2.3: repair pregunta, no mide)."""
    arbol = ast.parse((_AQUI / "repair_clasificar.py").read_text())
    importados = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            importados |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            importados.add(n.module.split(".")[0])
    prohibidos = importados & {"os", "subprocess", "socket", "urllib", "httpx", "requests",
                               "sqlite3", "pathlib", "time", "threading"}
    assert not prohibidos, f"el clasificador importa {sorted(prohibidos)}: dejó de ser puro"
