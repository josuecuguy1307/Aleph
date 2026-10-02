#!/usr/bin/env python3
"""repair_clasificar.py — R2 · LA CLASIFICACIÓN, PURA.

Segunda sesión de `DISEÑO-REPAIR-v1.md`. Una causa tipada entra; sale un veredicto que dice
si repair la arregla callado (temporal) o la manda al botón correcto (permanente), con qué
acción y **por qué**. Sin efectos: no spawnea, no mide, no toca la DB, no toca la red.

**REPAIR NO INVENTA TAXONOMÍA** (§2.1 del diseño). Consume las tres que ya existen:

  · las causas del motor            `motor_verdad.CAUSAS` — el vocabulario CERRADO de la UI
  · el traductor del SDK            `traductor_errores.py` — error crudo → causa nuestra
  · la reintentabilidad de gate2    `errores_modelo._REINTENTABLES` + `retry_after_s`

«Temporal» **es** `reintentable`, extendido a las causas de conexión que aquel módulo no
cubre. Una sola definición de retryability en el producto, no dos listas que dicen lo mismo
sobre `TIMEOUT` y se separan el día que alguien toque una.

⚠️ **LOS VALORES SE DECLARAN, NO SE IMPORTAN.** Mismo motivo que el traductor
(`traductor_errores.py:59-62`): esta capa vive en `platform/` y no puede depender de
`product/backend`, porque entonces no se podría probar ni usar desde acá. Que las dos copias
no se separen lo sostiene `test_repair_clasificar.py`, que compara contra los archivos
reales — y que además REVIENTA si el vocabulario del motor crece y esta tabla no.

⚠️ **CERO CLASIFICACIÓN POR NOMBRE DE EXCEPCIÓN.** Es la lección que R1 pagó: el SDK
sintetiza el vencimiento de `read_timeout_seconds` como un `McpError` —el MISMO tipo con el
que un server contesta un error real— así que el tipo no distingue quién dijo «se acabó el
tiempo». Acá se clasifica por la CAUSA TIPADA (que ya es una clasificación con autor) y, en
los grises, por **el reloj o la evidencia**. Hay un test que se pone rojo si este archivo
llega a nombrar un tipo de excepción.

    python3 -m pytest platform/inspection/test_repair_clasificar.py -q
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ── 1 · LAS DOS CLASES (internas: el usuario JAMÁS ve estas palabras) ───────────────

TEMPORAL = "temporal"
PERMANENTE = "permanente"

# ── 2 · LAS ACCIONES ────────────────────────────────────────────────────────────────

#: repair reintenta con backoff y el usuario ve 🟡 y nada más (§3.4).
BACKOFF = "backoff"
#: un solo reintento; si repite, escala. Para lo que "puede salir bien otra vez" pero no
#: tiene por qué salir bien cinco veces.
UNA_VUELTA = "una_vuelta"
#: la card muestra un botón. Cuál, lo dice `boton`.
BOTON = "boton"
#: no hay arreglo que podamos ejecutar: va `mano_humana = {comando, doc, por_que}`.
MANO_HUMANA = "mano_humana"
#: derecho a la escalada del §5, sin botón: no hay acción del usuario que sirva.
ESCALAR = "escalar"
#: NADA. Ni reintento, ni botón, ni escalada, ni alarma. (Gate 2 · F1c)
#: EXTENSIÓN DECLARADA de las cinco acciones del §2.2, y la única que el diseño no
#: contempló porque su tabla salió de un vocabulario donde TODA causa era un fallo.
#: `turno_detenido` no lo es: alguien apretó «parar» y el sistema hizo lo que se le pidió.
#: Las cinco acciones existentes MIENTEN acá, cada una a su manera — BACKOFF y UNA_VUELTA
#: reintentan lo que el usuario paró (deshacen su decisión), BOTON le ofrece arreglar algo
#: que no está roto, MANO_HUMANA le pide un comando por su propia acción, y ESCALAR levanta
#: una alarma por un funcionamiento correcto. La sexta acción es no hacer nada, y hay que
#: poder decirla.
SIN_ALARMA = "sin_alarma"

# ── 3 · LOS BOTONES (§4.2 — los pinta la card que YA existe, repair sólo nombra) ────

B_RECONECTAR = "reconectar"
B_REVISAR_LLAVE = "revisar_llave"
B_CONECTAR = "conectar"
B_REVISAR_PLAN = "revisar_plan"
B_DESCARGAR = "descargar"
B_ACTUALIZAR = "actualizar"
B_FIJAR_VERSION = "fijar_version"          # §4.2.1 — el que nace con R4
B_COPIAR_REPORTE = "copiar_reporte"
B_ELEGIR_MODELO = "elegir_modelo"          # §4.2.1 — el que nace con F8

# ── 4 · LAS CAUSAS, DECLARADAS POR VALOR ────────────────────────────────────────────
# Del motor (`motor_verdad.py`, el vocabulario CERRADO de la UI):
SIN_RED = "sin_red"
TIMEOUT = "timeout"
ERROR_UPSTREAM = "error_upstream"
RATE_LIMIT = "rate_limit"
PROVEEDOR_CAIDO = "proveedor_caido"
FALTA_KEY = "falta_key"
KEY_INVALIDA = "key_invalida"
OAUTH_REVOCADO = "oauth_revocado"
SIN_CREDITO = "sin_credito"
SIN_SESION = "sin_sesion"
PLAN_INSUFICIENTE = "plan_insuficiente"
MODELO_NO_DISPONIBLE = "modelo_no_disponible"
MODELO_NO_ELEGIDO = "modelo_no_elegido"        # [F8] hay llave, no hay modelo elegido
CLI_NO_INSTALADO = "cli_no_instalado"
CLI_VERSION_VIEJA = "cli_version_vieja"
CLI_SIN_PERMISOS = "cli_sin_permisos"
CLI_INTERACTIVO_COLGADO = "cli_interactivo_colgado"
SERVIDOR_INCOMPATIBLE = "servidor_incompatible"
NO_ES_MCP = "no_es_mcp"
FALLA_DE_ALEPH = "falla_de_aleph"
FALLO_DESCONOCIDO = "fallo_desconocido"
# De `errores_modelo` (gate2) y que el motor no tiene:
SIN_RUNTIME = "sin_runtime"
# Las SEIS de gate2 · F1c (ya viven también en `motor_verdad.CAUSAS`):
CONTEXTO_EXCEDIDO = "contexto_excedido"
POLITICA_DE_CONTENIDO = "politica_de_contenido"
CLI_OCUPADO = "cli_ocupado"
TURNO_DETENIDO = "turno_detenido"
SESION_PERDIDA = "sesion_perdida"
RUNTIME_OCUPADO = "runtime_ocupado"
# Las DOS de la COSTURA DE TOOLS, selladas por gate3 · D7 (`motor_verdad.py:139-140`,
# `errores_modelo.py:73-74`, `tool_result.py:51-52`). No son fallos de CONEXIÓN como el
# resto de esta tabla —una nace del modelo y la otra de una decisión de Aleph— y por eso
# valía la pena pensarlas y no meterlas al molde del conector. Ver `_TABLA`.
GATE_BLOQUEADO = "gate_bloqueado"
ARGUMENTOS_INVALIDOS = "argumentos_invalidos"
# GATE 3 · obra B — el turno salió, pero no con el modelo que se pidió. Ver `_TABLA`.
MODELO_SUSTITUIDO = "modelo_sustituido"
# Del verificador de conexiones (`conexiones_verificador.py`):
C_ARRANQUE = "arranque"
C_SIN_TOOLS = "sin_tools"
C_SIN_CANDIDATA = "sin_tool_sondeable"
C_SIN_RESPUESTA = "sin_respuesta"

#: LO QUE GATE2 YA DECLARÓ REINTENTABLE (`errores_modelo._REINTENTABLES`). Se copia tal cual
#: y el test verifica que siga siendo la misma lista: si gate2 mueve una, esto se entera.
_REINTENTABLES_GATE2 = frozenset({SIN_RED, TIMEOUT, RATE_LIMIT, PROVEEDOR_CAIDO, SIN_RUNTIME,
                                  CLI_OCUPADO, RUNTIME_OCUPADO, SESION_PERDIDA})

#: LA EXTENSIÓN (§2.1: «extendido a las causas de conexión que ese módulo no cubre»).
#: `errores_modelo` habla de INFERENCIA; estas cuatro son de CONEXIÓN y no existen allá.
_EXTENSION_CONEXION = frozenset({ERROR_UPSTREAM, C_SIN_RESPUESTA, C_ARRANQUE})


@dataclass(frozen=True)
class Veredicto:
    """Qué hacer con una causa. **Congelado**: los consumidores leen, no mutan — mismo
    contrato que `errores_modelo.CausaModelo`."""

    causa: str
    clase: str                                  # TEMPORAL | PERMANENTE
    accion: str                                 # BACKOFF | UNA_VUELTA | BOTON | …
    razon: str                                  # una línea, para la traza del §5
    boton: Optional[str] = None
    #: qué SEÑAL resolvió un gris: "murio" · "reloj" · "retry_after" · "causa_refinada".
    #: `None` cuando la causa no era gris, o cuando era gris y **no se pudo desempatar** —
    #: y en ese caso `razon` lo dice. No se inventa un desempate que no hubo.
    desempate: Optional[str] = None
    #: del proveedor, cuando vino (`errores_modelo.retry_after_s`). MANDA sobre la curva de
    #: §3.1: el que pone el límite sabe mejor que nuestro backoff.
    retry_after_s: Optional[float] = None
    #: pistas para R3, no decisiones: un server colgado no merece la misma paciencia que
    #: una red que se cayó.
    señales: dict = field(default_factory=dict)

    @property
    def es_temporal(self) -> bool:
        return self.clase == TEMPORAL

    def como_dict(self) -> dict:
        return {"causa": self.causa, "clase": self.clase, "accion": self.accion,
                "razon": self.razon, "boton": self.boton, "desempate": self.desempate,
                "retry_after_s": self.retry_after_s, "señales": dict(self.señales)}


# ── 5 · LA TABLA DEL §2.2 ───────────────────────────────────────────────────────────
# `causa -> (clase, accion, boton, razon)`. Los GRISES no están acá: los resuelve
# `_desempatar_*`, porque su clase depende de la evidencia y no de la causa sola.

_TABLA: dict = {
    # ── temporales: se arreglan callados ────────────────────────────────────────────
    SIN_RED:        (TEMPORAL, BACKOFF, None, "la red vuelve sola"),
    RATE_LIMIT:     (TEMPORAL, BACKOFF, None, "hay que esperar la ventana"),
    PROVEEDOR_CAIDO: (TEMPORAL, BACKOFF, None,
                      "5xx/timeout con internet verificado OK: es del otro lado"),
    SIN_RUNTIME:    (TEMPORAL, BACKOFF, None, "el runtime local puede levantar"),
    C_SIN_RESPUESTA: (TEMPORAL, BACKOFF, None, "no contestó; puede contestar al reintentar"),
    ERROR_UPSTREAM: (TEMPORAL, UNA_VUELTA, None,
                     "puede salir bien otra vez, pero no tiene por qué salir bien cinco"),
    # ── permanentes con botón ───────────────────────────────────────────────────────
    KEY_INVALIDA:   (PERMANENTE, BOTON, B_REVISAR_LLAVE, "401: la llave no sirve"),
    SIN_CREDITO:    (PERMANENTE, BOTON, B_REVISAR_LLAVE, "402: la llave sirve, no hay saldo"),
    FALTA_KEY:      (PERMANENTE, BOTON, B_CONECTAR, "no hay credencial"),
    SIN_SESION:     (PERMANENTE, BOTON, B_RECONECTAR,
                     "la sesión venció: el camino funciona y la llave no está en juego"),
    # RECONECTAR, jamás REVISAR_LLAVE. Es la regla que trae el conector OAuth: el grant lo
    # revocó el usuario en el proveedor, así que no hay ninguna llave que revisar — mandarlo
    # a mirar una credencial que está perfecta es el mismo error que §3.5 prohíbe para los
    # temporales. Tampoco es TEMPORAL: reintentar contra un grant revocado no lo resucita,
    # sólo gasta. El refresh ya devolvió `invalid_grant`, que es la señal inequívoca.
    OAUTH_REVOCADO: (PERMANENTE, BOTON, B_RECONECTAR,
                     "el usuario revocó el grant en el proveedor: se vuelve a consentir, "
                     "no se revisa una llave"),
    PLAN_INSUFICIENTE: (PERMANENTE, BOTON, B_REVISAR_PLAN, "la suscripción no lo cubre"),
    MODELO_NO_DISPONIBLE: (PERMANENTE, BOTON, B_REVISAR_LLAVE, "la llave no alcanza ese modelo"),
    CLI_NO_INSTALADO: (PERMANENTE, BOTON, B_DESCARGAR, "falta el programa"),
    CLI_VERSION_VIEJA: (PERMANENTE, BOTON, B_ACTUALIZAR, "versión por debajo del mínimo"),
    SERVIDOR_INCOMPATIBLE: (PERMANENTE, BOTON, B_FIJAR_VERSION,
                            "el server está roto o es incompatible: no es su configuración"),
    FALLA_DE_ALEPH: (PERMANENTE, BOTON, B_COPIAR_REPORTE,
                     "es culpa NUESTRA: el único camino no es un arreglo del usuario"),
    # ── permanentes sin botón ───────────────────────────────────────────────────────
    CLI_SIN_PERMISOS: (PERMANENTE, MANO_HUMANA, None, "permiso denegado: no lo resolvemos solos"),
    CLI_INTERACTIVO_COLGADO: (PERMANENTE, MANO_HUMANA, None,
                              "esperó un prompt que nadie puede contestar"),
    NO_ES_MCP:      (PERMANENTE, ESCALAR, None, "no habla MCP: no hay acción del usuario que sirva"),
    FALLO_DESCONOCIDO: (PERMANENTE, ESCALAR, None, "sin causa tipada: va con la traza cruda"),
    # ── EXTENSIÓN más allá del §2.2, declarada ──────────────────────────────────────
    # El diseño no las lista porque su tabla salió del vocabulario del motor y éstas son del
    # verificador. Un server que arranca y no publica nada usable no se arregla esperando:
    # reintentar sólo gasta. Van a la escalada, que es lo que el §5 hace con lo que no tiene
    # botón.
    C_SIN_TOOLS:    (PERMANENTE, ESCALAR, None,
                     "arrancó y no publica tools usables: reintentar no cambia eso"),
    C_SIN_CANDIDATA: (PERMANENTE, ESCALAR, None,
                      "publica tools pero ninguna se puede llamar a ciegas"),
    # ── GATE 2 · F1c · LAS SEIS SELLADAS ────────────────────────────────────────────
    # Las tres temporales van con la misma disciplina que `rate_limit`: se esperan, el
    # usuario ve 🟡 y nada más (§3.5 — a un temporal no se le pide nada a nadie).
    CLI_OCUPADO:    (TEMPORAL, BACKOFF, None,
                     "tu CLI está atendiendo otro turno: termina en segundos"),
    RUNTIME_OCUPADO: (TEMPORAL, BACKOFF, None,
                      "el runtime local está vivo y con cola: se vacía sola"),
    SESION_PERDIDA: (TEMPORAL, BACKOFF, None,
                     "el server ya rehace el turno con contexto completo"),
    # Las dos del PEDIDO son PERMANENTES, y ahí está el arreglo que trae F1c: las dos
    # caían en `error_upstream`, que es TEMPORAL/UNA_VUELTA — o sea que un pedido
    # demasiado largo y un contenido rechazado se REINTENTABAN una vez, gastando una
    # llamada entera para obtener exactamente la misma negativa. No hay botón: lo que hay
    # que cambiar es el pedido, y eso no lo puede hacer repair.
    CONTEXTO_EXCEDIDO: (PERMANENTE, MANO_HUMANA, None,
                        "el pedido no entra en la ventana: hay que acortarlo, y eso no lo "
                        "hacemos nosotros"),
    POLITICA_DE_CONTENIDO: (PERMANENTE, MANO_HUMANA, None,
                            "el proveedor se negó: hay que reformular, y repetir la misma "
                            "negativa no la cambia"),
    # Y la sexta, que no es un fallo. Ver `SIN_ALARMA`, arriba.
    TURNO_DETENIDO: (PERMANENTE, SIN_ALARMA, None,
                     "lo paró el usuario: el sistema hizo lo que se le pidió"),
    # ── GATE 2 · F8 ─────────────────────────────────────────────────────────────────
    # PERMANENTE porque reintentar no elige un modelo: el catálogo vuelve igual y la fila
    # sigue sin elección. Y BOTON —no SIN_ALARMA— aunque tampoco sea un fallo: la diferencia
    # con `turno_detenido` es que acá SÍ hay algo que hacer y el botón ES la resolución, no
    # un arreglo de algo roto. Repair no la va a ver nunca (mide conexiones, y ésta la deriva
    # el selector); la entrada existe para que el vocabulario esté completo y para que, si
    # algún día llega, nadie la reintente.
    MODELO_NO_ELEGIDO: (PERMANENTE, BOTON, B_ELEGIR_MODELO,
                        "la llave está y el proveedor contesta: lo que falta es elegir de "
                        "una lista, y eso no lo puede hacer repair"),
    # ── GATE 3 · obra A · LAS DOS DE LA COSTURA DE TOOLS ────────────────────────────
    # No se clasifican por parecido con un fallo de conector: **cada una sale de lo que su
    # propia vara ya dejó sellado** (`verify_costura_obra2.py:202-208`), que es la única
    # fuente con autor sobre estas dos.
    #
    # `argumentos_invalidos` viaja con `origen=modelo` y **`reintentable=True`**. Como
    # «temporal ≡ reintentable, extendido» (§2.1), es TEMPORAL — y darlo por permanente
    # sería el producto contradiciéndose sobre la misma palabra. Pero NO va con BACKOFF:
    # esperar no arregla una llamada mal armada, porque el tiempo no es lo que falta. Va con
    # UNA_VUELTA, por el mismo motivo exacto que `error_upstream`: el modelo puede rearmar
    # bien la llamada al re-muestrear, y puede que no — insistir cinco veces con un modelo
    # que no acierta la firma sólo gasta llamadas. Y el que se equivocó fue el MODELO, no la
    # persona: no hay botón que ofrecerle a nadie.
    ARGUMENTOS_INVALIDOS: (TEMPORAL, UNA_VUELTA, None,
                           "el modelo armó mal la llamada: puede salir bien al re-muestrear, "
                           "pero esperar no lo arregla y repetirlo cinco veces tampoco"),
    # `gate_bloqueado` viaja con `origen=aleph` y **`reintentable=False`**, y sobre todo:
    # **NO ES UN FALLO.** Acta de persona usuaria (2026-08-06), la misma que ordena la obra 5: *el gate
    # es PROTECCIÓN, no fallo.* El gate hizo su trabajo y está preguntando.
    #
    # Por eso SIN_ALARMA, la sexta acción, y es la SEGUNDA causa que la usa —la primera
    # decisión de ensancharla desde que nació con `turno_detenido`, y va declarada acá y en
    # el test. Las otras cinco mienten, cada una a su manera: BACKOFF y UNA_VUELTA
    # reintentarían una acción que el usuario todavía no autorizó (que es peor que gastar:
    # es ejecutar lo que el gate frenó), MANO_HUMANA le pediría un comando por una pregunta
    # que ya tiene su [OK] en pantalla, y ESCALAR levantaría una alarma por un
    # funcionamiento correcto.
    #
    # Y BOTON tampoco, aunque acá SÍ haya algo que hacer —a diferencia de `turno_detenido` y
    # como en `modelo_no_elegido`—: la diferencia es que **el botón YA EXISTE y no es de
    # repair**. Es la tarjeta del gate con su [OK], que la obra 5 dejó pintada aparte
    # (`sala.html:3316`), y agregar un segundo botón es la lección que ya dejó el segundo
    # [Reintentar]. Repair no tiene que resolver esto: tiene que NO estorbarlo.
    GATE_BLOQUEADO: (PERMANENTE, SIN_ALARMA, None,
                     "el gate hizo su trabajo y está preguntando: no es un fallo, y su [OK] "
                     "ya está en la tarjeta del gate"),
    # ── GATE 3 · obra B · LA SUSTITUCIÓN DE MODELO ──────────────────────────────────
    # ACTA 2 DE PERSONA USUARIA (2026-08-07): **SUSTITUIR SÍ, EN SILENCIO NO.** El modelo elegido no
    # produjo nada, entró el de respaldo y **el turno SALIÓ**. Esa última parte decide todo
    # lo demás: no es un fallo, es un aviso sobre EL CAMINO, no sobre el resultado.
    #
    # PERMANENTE porque reintentar no des-sustituye nada: la respuesta ya se entregó, y
    # volver a mandar el mismo turno contra el mismo primario caído gasta dos llamadas para
    # llegar al mismo lugar. Y SIN_ALARMA porque las otras cinco mienten sobre un turno que
    # funcionó — BACKOFF/UNA_VUELTA reintentarían algo ya resuelto, MANO_HUMANA pediría un
    # comando por algo que no está roto, ESCALAR levantaría una alarma por una red de
    # seguridad que hizo exactamente su trabajo.
    #
    # Y BOTON tampoco, aunque `B_ELEGIR_MODELO` exista y la tentación sea obvia: ofrecerlo
    # convierte «tu modelo se cayó una vez y te cubrimos» en «andá a arreglar tu setup», por
    # un turno que salió bien. Si el primario está caído de verdad, quien lo dice es el
    # semáforo del modelo (`MV.probar`), que para eso es la puerta única — no un botón
    # colgado de un aviso.
    #
    # ⚠️ Igual que `modelo_no_elegido`: **repair no la va a ver nunca** (mide CONEXIONES y
    # ésta la emite el streaming). La entrada existe para que el vocabulario esté completo y
    # para que, si algún día llega, nadie la reintente.
    MODELO_SUSTITUIDO: (PERMANENTE, SIN_ALARMA, None,
                        "el turno salió con el modelo de respaldo: no falló nada que "
                        "reparar, pero el camino no fue el que se pidió y hay que decirlo"),
}

#: Las que NO están en `_TABLA` porque su clase depende de la evidencia (§2.3).
GRISES = frozenset({TIMEOUT, C_ARRANQUE})

#: Todo lo que este módulo sabe clasificar.
CAUSAS_CUBIERTAS = frozenset(_TABLA) | GRISES


# ── 6 · LOS GRISES ──────────────────────────────────────────────────────────────────

def _desempatar_timeout(ev: dict) -> Veredicto:
    """`timeout` — ¿red caída o server colgado?

    **La pregunta correcta no es cuál de los dos, sino si hay alguien vivo del otro lado**, y
    eso ya se puede medir sin inventar nada: `murio` sale del EOF del pipe de stderr
    (R1/`transporte_sdk`), y es un hecho del sistema operativo, no una interpretación.

      · murió              → no es la red: es el server. Reintentar lo vuelve a levantar.
      · vive y no contesta → colgado. También temporal, pero **no merece la misma paciencia**:
                             una red que vuelve vuelve; un server trabado sigue trabado. Se
                             marca `sospecha_de_cuelgue` para que R3 use un breaker más corto.
      · sin evidencia      → temporal, y `desempate=None` lo DICE. No se inventa un
                             desempate que no hubo.

    ⚠️ Nunca por el tipo de excepción: R1 midió que el SDK usa `McpError` tanto para «el
    server contestó un error» como para «venció el reloj».
    """
    murio = ev.get("murio_por_eof")
    if murio is None:
        murio = ev.get("murio")
    reloj = _reloj_vencido(ev)
    if murio is True:
        return Veredicto(TIMEOUT, TEMPORAL, BACKOFF,
                         "el proceso murió: no es la red, es el server",
                         desempate="murio",
                         señales={"murio": True, "reloj_vencido": reloj})
    if murio is False:
        return Veredicto(TIMEOUT, TEMPORAL, BACKOFF,
                         "el proceso vive y no contesta: colgado",
                         desempate="murio",
                         señales={"murio": False, "reloj_vencido": reloj,
                                  "sospecha_de_cuelgue": True})
    if reloj:
        return Veredicto(TIMEOUT, TEMPORAL, BACKOFF,
                         "venció el reloj y no hay evidencia de si el proceso vive",
                         desempate="reloj", señales={"reloj_vencido": True})
    return Veredicto(TIMEOUT, TEMPORAL, BACKOFF,
                     "timeout sin evidencia para desempatar red vs. server",
                     desempate=None, señales={})


def _reloj_vencido(ev: dict) -> bool:
    """¿Alguno de los disparos anotados venció de verdad? Lee lo que R1 dejó
    (`transporte_sdk._anotar_timeout`), que ya filtró por el reloj y no por el tipo."""
    for t in (ev.get("timeouts") or []):
        if t.get("vencio_el_reloj"):
            return True
    return False


def _desempatar_arranque(ev: dict) -> Veredicto:
    """`arranque` — ¿el server está roto, o falta un programa?

    **Ya está clasificado y repair sólo LEE** (§2.3 del diseño): `diagnostico_conectores`
    mapea un traceback con `ModuleNotFoundError/ImportError/AttributeError` a
    `servidor_incompatible`, y un `ENOENT/command not found` a `cli_no_instalado`. Los dos
    son permanentes y cada uno tiene su botón. Repair **pregunta, no mide** — hacer acá su
    propio análisis del stderr sería una segunda verdad sobre la misma pieza, que es
    justamente lo que el motor existe para evitar.

    Si nadie refinó la causa: **TEMPORAL**, y es una decisión, no un descuido. El error
    barato es reintentar algo permanente (cuesta 5 intentos y 90 s acotados, y si repite la
    escalada del §5 lo levanta igual). El error caro es declarar permanente algo que fue un
    hipo: manda a una persona a arreglar un problema que no existe.
    """
    refinada = ev.get("causa_refinada")
    if refinada and refinada in _TABLA:
        clase, accion, boton, razon = _TABLA[refinada]
        return Veredicto(refinada, clase, accion,
                         f"{razon} (refinada desde `arranque` por quien sí midió)",
                         boton=boton, desempate="causa_refinada")
    return Veredicto(C_ARRANQUE, TEMPORAL, BACKOFF,
                     "no llegó a hablar MCP y nadie refinó la causa: se reintenta acotado "
                     "antes de mandar a nadie a arreglar nada",
                     desempate=None, señales={"sin_refinar": True})


# ── 7 · LA ENTRADA ──────────────────────────────────────────────────────────────────

def clasificar(causa: Optional[str], *, evidencia: Optional[dict] = None) -> Veredicto:
    """Causa tipada → veredicto. **Pura**: mismos argumentos, mismo resultado, sin efectos.

    `evidencia` es opcional y sólo la miran los grises. Acepta directamente el evento
    `MuerteMCP` de R1 (`murio_por_eof`, `timeouts`, `retry_after_s`, `causa_refinada`).
    """
    ev = dict(evidencia or {})
    c = (causa or "").strip()

    if c == TIMEOUT:
        v = _desempatar_timeout(ev)
    elif c == C_ARRANQUE:
        v = _desempatar_arranque(ev)
    elif c in _TABLA:
        clase, accion, boton, razon = _TABLA[c]
        v = Veredicto(c, clase, accion, razon, boton=boton)
    else:
        # ⚠️ LO DESCONOCIDO NO SE ADIVINA. Una causa que este módulo no conoce va a la
        # escalada con su nombre adentro — nunca a un backoff «por las dudas», que gastaría
        # 90 s en algo de lo que no sabemos nada, ni a un botón inventado.
        v = Veredicto(c or FALLO_DESCONOCIDO, PERMANENTE, ESCALAR,
                      f"causa no cubierta por la tabla ({c or 'sin causa'}): escala con traza",
                      señales={"no_cubierta": True})

    # `retry_after_s` MANDA sobre la curva (§2.3): si el proveedor dijo cuánto esperar, es
    # el dato más confiable que hay. Sólo tiene sentido en lo temporal.
    ra = ev.get("retry_after_s")
    if v.es_temporal and isinstance(ra, (int, float)) and ra > 0:
        return Veredicto(v.causa, v.clase, v.accion,
                         v.razon + f" · el proveedor pidió esperar {ra}s",
                         boton=v.boton, desempate=v.desempate or "retry_after",
                         retry_after_s=float(ra), señales=dict(v.señales))
    return v


def clasificar_muerte(evento: dict) -> Veredicto:
    """El evento `MuerteMCP` de R1 → veredicto.

    ⚠️ **UNA MUERTE NO ES, POR SÍ SOLA, UNA CAUSA.** El evento trae el `disparador` (§1.2) y
    la evidencia, pero la CAUSA la pone quien midió: el verificador o el traductor. Cuando el
    evento no la trae, esto clasifica lo que sí sabe —el disparador— y no inventa una.
    """
    ev = dict(evento or {})
    causa = ev.get("causa")
    if causa:
        return clasificar(causa, evidencia=ev)

    disp = ev.get("disparador") or ""
    # LAPIDA/OCIOSIDAD/LRU/CIERRE no son fallos: son el dueño haciendo su trabajo o el
    # usuario decidiendo. El dueño los emite igual (decisión 6.A) y quien filtra es repair.
    if disp in ("LAPIDA", "OCIOSIDAD", "LRU", "CIERRE"):
        return Veredicto(disp.lower(), PERMANENTE, ESCALAR,
                         "no es un fallo: es una decisión (lápida/ociosidad/techo/cierre)",
                         señales={"no_es_fallo": True})
    if disp == "R3":
        return clasificar(C_ARRANQUE, evidencia=ev)
    # murió estando viva: sin causa medida, el gris del timeout es el que más se le parece —
    # y su desempate (`murio`) es justamente el dato que el evento SÍ trae.
    return _desempatar_timeout(ev)


__all__ = ["TEMPORAL", "PERMANENTE", "BACKOFF", "UNA_VUELTA", "BOTON", "MANO_HUMANA",
           "ESCALAR", "Veredicto", "clasificar", "clasificar_muerte", "GRISES",
           "CAUSAS_CUBIERTAS", "B_RECONECTAR", "B_REVISAR_LLAVE", "B_CONECTAR",
           "B_REVISAR_PLAN", "B_DESCARGAR", "B_ACTUALIZAR", "B_FIJAR_VERSION",
           "B_COPIAR_REPORTE"]
