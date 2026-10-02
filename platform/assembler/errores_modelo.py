#!/usr/bin/env python3
"""errores_modelo.py — EL TRADUCTOR DE ERRORES DE INFERENCIA (Gate 2 · F1).

Convierte CUALQUIER fallo de las 4 vías de inferencia en UNA causa del vocabulario
CERRADO que ya declara `product/backend/app/phase1/motor_verdad.py` (ampliado por
`centro_modelos.CAUSAS_MODELO`). Una entrada, una causa tipada, cero texto libre del
proveedor en la salida.

POR QUÉ EXISTE (los tres hallazgos que lo motivan, todos medidos):

  · `assembler._chat` funde 401, 429 y DNS caído en un solo `RuntimeError` con un string
    (auditoría 2 §P1.a). El status vive dentro del mensaje; el llamante tiene que re-parsear.
  · `cli_brain.claude_cli.classify_error` manda DNS-caído Y desconocido al mismo cajón
    `model_error` (auditoría 2 §P1.e). "Estás sin internet" se le muestra al usuario como
    "el modelo falló".
  · LiteLLM entrega un `InternalServerError` con `status_code=500` cuando lo que pasó es
    que no hay red (auditoría 1 §P1.d). Red y servidor quedan fundidos.

LA REGLA DE ORO — LA RED NO ES EL SERVIDOR:
  un fallo de transporte SIN status HTTP jamás se vuelve `proveedor_caido`. Si el host es
  remoto es `sin_red`; si es local es del runtime (`sin_runtime`, ollama) o nuestro
  (`falla_de_aleph`, un servicio de Aleph que debía estar arriba). `proveedor_caido` está
  reservado para lo que su propia definición dice: «5xx/timeout CON internet verificado OK».

ESTADO: siempre `roto`. No es una simplificación: `motor_verdad._resultado` (:120-136)
declara que «`causa` SÓLO tiene sentido con estado=roto» y fuerza `causa=None` en cualquier
otro estado. Un objeto que SIEMPRE lleva causa, por contrato SIEMPRE lleva `roto`.
`no_configurado`/`premium` son pre-estados (no se intentó / hace falta plan), no
traducciones de un fallo, y por eso no salen de acá.

REDACCIÓN (auditoría 2 §P4.c — hoy `assembler._chat` levanta el cuerpo entero del provider
dentro del mensaje de la excepción, y ese mensaje llega a la UI): `detalle` se compone
SIEMPRE de plantillas propias más escalares seguros (status, errno, host, puerto). El texto
del proveedor NUNCA se copia. No es un filtro: es que no hay camino por donde entre.
`evidencia` lleva sólo claves de una lista blanca, y aun así cada valor pasa por el
detector de secretos.

PURO: stdlib only, sin red, sin disco, sin estado global mutable. `ahora` es inyectable
para que las varas no dependan del reloj.

NUNCA LEVANTA. Cualquier entrada — None, bytes, un objeto raro, un string de 10 MB —
devuelve una `CausaModelo` válida. Un traductor de errores que se rompe con un error es
el chiste que no se puede hacer.

Vara:  product/backend/.venv/bin/python platform/assembler/verify_traductor.py
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit

# ══ EL VOCABULARIO ═════════════════════════════════════════════════════════════════
# Copia declarada de las constantes de `motor_verdad` (+ `centro_modelos.CAUSAS_MODELO`).
# NO se importan: `platform/` no depende de `product/`, y esta pieza tiene que poder correr
# en el sidecar congelado sin arrastrar la app. La deriva la caza la vara, que sí importa
# los dos módulos y exige que este conjunto sea SUBCONJUNTO del de ellos.

SIN_RED = "sin_red"
TIMEOUT = "timeout"
ERROR_UPSTREAM = "error_upstream"
FALTA_KEY = "falta_key"
KEY_INVALIDA = "key_invalida"
SIN_CREDITO = "sin_credito"
RATE_LIMIT = "rate_limit"
MODELO_NO_DISPONIBLE = "modelo_no_disponible"
PLAN_INSUFICIENTE = "plan_insuficiente"
PROVEEDOR_CAIDO = "proveedor_caido"
FALLA_DE_ALEPH = "falla_de_aleph"
FALLO_DESCONOCIDO = "fallo_desconocido"
GATE_BLOQUEADO = "gate_bloqueado"
ARGUMENTOS_INVALIDOS = "argumentos_invalidos"
# GATE 3 · obra B · ACTA 2: SUSTITUIR SÍ, EN SILENCIO NO. Cuando el modelo elegido no
# produce nada, el sistema cae al de respaldo para que el trabajo no se caiga —y lo DICE.
# No es un fallo: el turno se completó. Es un aviso sobre EL CAMINO, no sobre el resultado.
MODELO_SUSTITUIDO = "modelo_sustituido"
SIN_SESION = "sin_sesion"
CLI_NO_INSTALADO = "cli_no_instalado"
CLI_SIN_PERMISOS = "cli_sin_permisos"
CLI_VERSION_VIEJA = "cli_version_vieja"
CLI_INTERACTIVO_COLGADO = "cli_interactivo_colgado"
SIN_RUNTIME = "sin_runtime"
# ── F1c · LAS SEIS SELLADAS ────────────────────────────────────────────────────────
# Cada una cierra un HUECO que una fase midió, no pudo nombrar y dejó escrito en su propio
# código. El motivo de admisión y las citas están en `motor_verdad.py` (§F1c); acá va lo
# que este módulo necesita saber: qué las emite y qué cambió de veredicto.
CONTEXTO_EXCEDIDO = "contexto_excedido"
POLITICA_DE_CONTENIDO = "politica_de_contenido"
CLI_OCUPADO = "cli_ocupado"
TURNO_DETENIDO = "turno_detenido"
SESION_PERDIDA = "sesion_perdida"
RUNTIME_OCUPADO = "runtime_ocupado"

#: Todas las causas que este traductor puede emitir. Subconjunto probado del vocabulario.
CAUSAS = frozenset({
    SIN_RED, TIMEOUT, ERROR_UPSTREAM, FALTA_KEY, KEY_INVALIDA, SIN_CREDITO, RATE_LIMIT,
    MODELO_NO_DISPONIBLE, PLAN_INSUFICIENTE, PROVEEDOR_CAIDO, FALLA_DE_ALEPH,
    FALLO_DESCONOCIDO, GATE_BLOQUEADO, ARGUMENTOS_INVALIDOS, SIN_SESION,
    CLI_NO_INSTALADO, CLI_SIN_PERMISOS, CLI_VERSION_VIEJA,
    CLI_INTERACTIVO_COLGADO, SIN_RUNTIME,
    CONTEXTO_EXCEDIDO, POLITICA_DE_CONTENIDO, CLI_OCUPADO, TURNO_DETENIDO,
    SESION_PERDIDA, RUNTIME_OCUPADO,
    MODELO_SUSTITUIDO,
})

#: [Gate 4 · F5 · 5.1] Los dos MOTIVOS con los que un `contexto_excedido` de HTTP 413 se
#: precisa en la evidencia. No son causas —la causa es una sola— sino la diferencia entre
#: «escribiste algo larguísimo» y «te mandamos el cinturón entero», que es la diferencia
#: entre culpar al usuario y hacerse cargo. La superficie elige el copy por acá.
MOTIVO_DEMASIADAS_TOOLS = "demasiadas_tools"      # el pedido llevaba tools: es de la casa
MOTIVO_PEDIDO_GRANDE = "pedido_demasiado_grande"  # sin tools: el texto no entra

ROTO = "roto"

#: Las cuatro vías. `fuente` dice de dónde vino el fallo, no quién tiene la culpa.
FUENTE_URLLIB = "urllib"
FUENTE_CLI = "cli"
FUENTE_LITELLM = "litellm"
FUENTE_OLLAMA = "ollama"
FUENTES = frozenset({FUENTE_URLLIB, FUENTE_CLI, FUENTE_LITELLM, FUENTE_OLLAMA})

# ══ REINTENTABILIDAD (regla del traspaso §18) ══════════════════════════════════════
# Reintentar tiene sentido cuando el mismo pedido, idéntico, puede salir bien más tarde:
# la red vuelve, la ventana se abre, el 5xx pasa. NO lo tiene cuando el pedido está mal o
# la credencial no sirve: repetirlo sólo gasta.
_REINTENTABLES = frozenset({
    SIN_RED, TIMEOUT, RATE_LIMIT, PROVEEDOR_CAIDO, SIN_RUNTIME,
    # F1c · las tres de las seis nuevas que SÍ pueden salir bien repitiendo lo mismo:
    #   `cli_ocupado`    el otro turno termina                (segundos)
    #   `runtime_ocupado` la cola del runtime se vacía         (segundos)
    #   `sesion_perdida` el server rehace el turno con contexto completo y sale
    # Las otras tres NO entran, y cada ausencia es una decisión:
    #   `contexto_excedido`     el mismo texto no va a entrar la próxima vez: repetirlo gasta
    #   `politica_de_contenido` una negativa repetida sigue siendo una negativa
    #   `turno_detenido`        reintentar lo que alguien paró es DESHACER SU DECISIÓN — es
    #                           el único de los seis donde reintentar no sólo gasta: traiciona
    CLI_OCUPADO, RUNTIME_OCUPADO, SESION_PERDIDA,
})

# ══ ESCALABILIDAD (F4a · obra 2) ═══════════════════════════════════════════════════
# REINTENTAR ≠ ESCALAR, y confundirlos es el bug que esta fase mata. Reintentar es «lo
# mismo, otra vez». Escalar es «lo mismo, en OTRO modelo y OTRO endpoint» — el cascade
# `primary → fallback → oss-direct` de `recipe_assembler._route_chat`.
#
# LA PREGUNTA QUE DECIDE, y está redactada así tras haberla redactado mal una vez:
#
#   **¿el endpoint NO PUDO atender, o ATENDIÓ y dijo algo?**
#
#   NO PUDO (no hay red, se cayó, hay cola, hay techo, el servicio no está)  →  ESCALA.
#       Otro endpoint existe y puede andar. Es para esto que existe el cascade.
#   ATENDIÓ y dijo algo sobre la CREDENCIAL, el PLAN o el PEDIDO           →  NO ESCALA.
#       Escalar no arregla nada y además MUDA EL PROBLEMA: un 401 con fallback deja de
#       verse como «tu llave no sirve» y pasa a verse como «un modelo raro respondiendo».
#       Eso es lo que muere hoy — la persona mira una respuesta degradada y nunca se entera
#       de que su llave está mal. (auditoría 2 §P1.a)
#
# ⚠️ EL PRIMER INTENTO DE ESTA LISTA PREGUNTABA «¿DE QUIÉN ES LA CULPA?» Y ESTABA MAL.
# Con ese criterio `falla_de_aleph` quedaba afuera («es nuestro, no lo tapes con un
# fallback») — y `test_reliability_fallback.py` se puso rojo en la primera corrida:
# el gateway muerto de la regresión vive en `127.0.0.1:4000`, o sea que es un host LOCAL,
# o sea que el traductor lo llama `falla_de_aleph`… y el run dejaba de caer al OSS-directo.
# **Eso mata la cura del cuelgue 2026-06-15**, que es literalmente el motivo por el que la
# red de seguridad existe. La culpa y el ruteo son dos preguntas distintas: de quién es la
# culpa decide qué se le MUESTRA a la persona (y ahí `falla_de_aleph` sigue siendo
# [Copiar el reporte]); si el endpoint pudo atender decide POR DÓNDE SIGUE EL RUN.
#
# Por eso están adentro:
#   `falla_de_aleph`  un servicio local nuestro no contestó → el endpoint NO PUDO. Otro sí.
#   `sesion_perdida`  ese CLI ya no tiene la conversación → no puede atender ESTE turno.
#                     El cascade le pasa `messages` COMPLETO a cada tier, así que el que
#                     responda no pierde contexto.
#   `fallo_desconocido` no sabemos qué pasó, y frente a lo que no se entiende la respuesta
#                     conservadora es intentar el otro camino, no rendirse.
#
# Un `RuntimeError` SIN causa tipada (código que todavía no pasó por el traductor) también
# escala — es el comportamiento de antes de F4a, byte por byte, y así el cableo no rompe
# lo que no tocó.
# ⚠️ [2026-08-14 · Ciencia obra 2] `cli_ocupado` SALIÓ DE ACÁ, Y ES LA EXCEPCIÓN QUE
# CONFIRMA EL CRITERIO DE ARRIBA. La pregunta del cascade es «¿el endpoint pudo atender?».
# Para todo lo de esta lista la respuesta es NO. Para `cli_ocupado` la respuesta es
# **«todavía no, y en dos segundos sí»**: el CLI está vivo, autenticado y sano — lo que pasa
# es que está atendiendo OTRA llamada, casi siempre del MISMO TURNO del mismo usuario.
#
# MEDIDO en Ciencia (binario `363d7ceb…`, dos turnos): dentro de UN turno las llamadas al
# cerebro se solapan de a dos —arrancan con 10 ms de diferencia—, así que el turno se pisaba
# a sí mismo sin que hubiera nadie más usando la app. Escalando, eso terminaba con el turno
# del usuario contestado por un `qwen3:8b` local (`degraded`, con aviso, pero contestado por
# otro modelo) o muerto con `HTTP 408: Ollama` a los 64,3 s. Ninguna de las dos cosas es lo
# que pidió alguien que eligió Codex — LEY 12: a un stack no se le consigue modelo.
#
# LO QUE REEMPLAZA AL ESCALADO ES ESPERAR, y va en la capa correcta: `slots.pedir` hace cola
# acotada (`ESPERA_TURNO_S`) antes de rechazar. Cuando `cli_ocupado` igual sale, ya se
# esperó: es un techo de verdad lleno, y ahí el camino del usuario es reintentar o soltar
# uno de los turnos, no que la casa le cambie el cerebro por atrás.
#
# `runtime_ocupado` SE QUEDA, y la diferencia es de dueño: ése es el Ollama local lleno, o
# sea el ÚLTIMO tier. Que escale ahí no cambia de modelo a nadie porque no hay tier
# siguiente; sacarlo sólo apagaría la red donde todavía sirve.
_ESCALABLES = frozenset({
    SIN_RED, TIMEOUT, PROVEEDOR_CAIDO, RATE_LIMIT, SIN_RUNTIME,
    RUNTIME_OCUPADO, FALLA_DE_ALEPH, SESION_PERDIDA, FALLO_DESCONOCIDO,
})


# ══ ¿ESTÁ CAÍDO? (Ciencia · obra 3) ════════════════════════════════════════════════
# `escala()` contesta «¿el endpoint pudo atender?». La RED DE SEGURIDAD —el tier
# `oss-direct`, un modelo local de 8B que NO es el que el usuario eligió— necesita una
# pregunta MÁS ANGOSTA, y ésta es la razón: escalar de un endpoint a otro del mismo
# proveedor conserva la intención del usuario; caer al OSS local la reemplaza. LEY 12: a un
# stack jamás se le consigue modelo.
#
#   ¿ESTÁ CAÍDO? = ¿este endpoint no puede atender NINGÚN pedido ahora, y no va a poder
#                  en el corto plazo sin que alguien intervenga?
#
# CAÍDO (la red dispara):
#   `sin_red`         no hay red que llevar el pedido a ningún lado
#   `proveedor_caido` 5xx: el proveedor se cayó, y es él quien lo dice
#   `sin_runtime`     el runtime no está corriendo (proceso muerto)
#   `falla_de_aleph`  un servicio local NUESTRO no contesta (puerto sin responder). Es el
#                     caso que PARIÓ la red: el cuelgue del 2026-06-15 con el gateway
#                     muerto en `127.0.0.1:4000`. Sacarlo de acá sería apagar la cura.
#
# NO CAÍDO (la red NO dispara — el turno falla con su causa, y se ve):
#   `cli_ocupado`     está atendiendo otro turno. Se libera en segundos (obra 2 le puso cola)
#   `runtime_ocupado` la cola del runtime local. Mismo caso, otro dueño
#   `rate_limit`      la ventana/cuota se agotó. El endpoint está SANO y contestó diciéndolo
#   `sesion_perdida`  el CLI está vivo; perdió el hilo. El server ya rehace el turno
#   `fallo_desconocido` no sabemos qué pasó — y frente a lo que no se entiende, cambiarle el
#                     modelo al usuario en silencio es la peor respuesta posible. Falla con
#                     nombre. (Ojo: para `escala()` sigue escalando, que es lo de siempre;
#                     lo único que se le niega es la RED.)
#
# ⚠️ `timeout` NO ES CAÍDO, Y ES LA DECISIÓN QUE MÁS SE DISCUTIÓ. Cuatro razones:
#   1. Un timeout significa que el endpoint ACEPTÓ la conexión y estuvo trabajando. Está
#      vivo. Lo que falló es que no terminó a tiempo — eso es LENTO, no caído.
#   2. El presupuesto ya se gastó ENTERO. Escalar después significa que la persona espera
#      el presupuesto MÁS la red, y encima recibe un 8B. Es el peor canje de la lista.
#   3. Es justo la falla donde más importa enterarse. Una respuesta degradada la tapa.
#   4. El timeout SÍ cancela el proceso (`cli_brain/base.py:859`, `_terminate_process`), así
#      que el CLI queda libre: reintentar es barato y honesto.
#   EL CONTRA, ANOTADO: si el CLI queda trabado, TODOS los turnos van a dar timeout y la
#   persona no recibe nada. Pero eso es un PATRÓN (timeouts repetidos), no un evento, y
#   merece su propia señal — no taparlo turno a turno con un modelo que no eligió.
#
# ⚠️ `key_invalida` NO ENTRA, Y VA CONTRA LO QUE SE PIDIÓ AL ENCARGAR ESTA OBRA («llave
# inválida → caído»). El motivo es que incluirla iría en la dirección CONTRARIA a la obra:
# hoy `key_invalida` NO escala —a propósito, y está escrito arriba: «un 401 con fallback
# deja de verse como *tu llave no sirve* y pasa a verse como *un modelo raro
# respondiendo*»— así que meterla acá AGREGARÍA degradaciones en vez de quitarlas. Y
# además el endpoint que rechaza una llave está VIVO: contestó. Se deja afuera y se dice.
CAIDO = frozenset({SIN_RED, PROVEEDOR_CAIDO, SIN_RUNTIME, FALLA_DE_ALEPH})


def esta_caido(causa: Optional[str]) -> bool:
    """¿Esta causa dice que el endpoint está CAÍDO (y no sólo ocupado, lento o sin cuota)?

    Es el permiso para la RED DE SEGURIDAD, no para el cascade entero. `None` o una causa
    que no conocemos → **False**: sin saber, no se le cambia el modelo a nadie. Es al revés
    que `escala()` a propósito — ahí lo conservador es intentar otro camino; acá lo
    conservador es NO reemplazar lo que el usuario eligió.
    """
    return causa in CAIDO


def escala(causa: Optional[str]) -> bool:
    """¿Ante esta causa tiene sentido probar el tier siguiente del cascade?

    `None` (o una causa que no conocemos) → True: es el camino de antes de F4a.
    """
    if causa is None:
        return True
    return causa in _ESCALABLES or causa not in CAUSAS


@dataclass(frozen=True)
class CausaModelo:
    """Un fallo de inferencia, tipado. Congelado: los consumidores leen, no mutan."""

    causa: str
    estado: str
    detalle: str
    evidencia: dict = field(default_factory=dict)
    reintentable: bool = False
    retry_after_s: Optional[float] = None
    fuente: str = FUENTE_URLLIB

    def __post_init__(self) -> None:
        if self.causa not in CAUSAS:
            raise ValueError(f"causa fuera del vocabulario: {self.causa!r}")
        if self.estado != ROTO:
            raise ValueError(f"estado inválido: {self.estado!r} (siempre 'roto')")
        if self.fuente not in FUENTES:
            raise ValueError(f"fuente inválida: {self.fuente!r}")

    def como_dict(self) -> dict:
        """Forma serializable, para el canal SSE o el registro."""
        return {
            "causa": self.causa,
            "estado": self.estado,
            "detalle": self.detalle,
            "evidencia": dict(self.evidencia),
            "reintentable": self.reintentable,
            "retry_after_s": self.retry_after_s,
            "fuente": self.fuente,
        }


class ErrorDeModelo(RuntimeError):
    """Un fallo de inferencia que YA VIENE CLASIFICADO. El vehículo de la causa (F4a · P1.a).

    ── POR QUÉ SUBCLASE DE `RuntimeError`, Y NO UNA EXCEPCIÓN NUEVA ────────────────
    `assembler._chat` levanta `RuntimeError` desde siempre, y hay una decena de sitios
    —`_route_chat`, el loop de `assemble_and_run`, el camino de visión, el reporter— que
    hacen `except RuntimeError`. Una excepción con jerarquía propia obligaría a tocarlos
    todos a la vez, y cada uno de esos `except` es un lugar donde un run puede morir sin
    respuesta. Heredando de `RuntimeError`, **todo el que hoy la agarra la sigue agarrando,
    byte por byte**, y el que quiera la causa pregunta por ella. El cableo es aditivo: los
    consumidores se migran de a uno, y ninguno se rompe mientras tanto.

    ── POR QUÉ EL MENSAJE NO CAMBIA ───────────────────────────────────────────────
    `str(exc)` conserva EXACTAMENTE la forma de antes (`"HTTP 429: {…}"` ·
    `"transport: …"`). No es nostalgia: `recipe_assembler._parse_cli_brain_error` **parsea
    ese string** para sacar el body clasificado del server `:8926`, y `route_log` y
    `record["error"]` lo guardan. Cambiar el texto sería romper un contrato de datos por
    un cambio de estética. La causa viaja al lado, en un atributo.

    ⚠️ El mensaje puede llevar el cuerpo crudo del proveedor (lo lleva hoy). **`causa` no**:
    su `detalle` y su `evidencia` salen del traductor, ya redactados. Quien muestre algo al
    usuario tiene que mostrar `causa`, jamás `str(exc)` — que es precisamente el arreglo
    que F4b va a hacer en la Sala.
    """

    def __init__(self, causa: CausaModelo, mensaje: str = ""):
        self.causa = causa
        super().__init__(mensaje or causa.detalle)

    @property
    def nombre_causa(self) -> str:
        return self.causa.causa

    def como_dict(self) -> dict:
        return self.causa.como_dict()


def causa_de_excepcion(exc: Any) -> Optional[CausaModelo]:
    """La `CausaModelo` de una excepción, o `None` si no viene clasificada.

    El único lugar donde se pregunta «¿esto ya está traducido?». Un `RuntimeError` pelado
    —código viejo que todavía no pasó por el traductor— devuelve `None`, y quien llame
    decide qué hacer con eso (en `_route_chat`: exactamente lo de antes de F4a).
    """
    c = getattr(exc, "causa", None)
    return c if isinstance(c, CausaModelo) else None


# ══ REDACCIÓN ══════════════════════════════════════════════════════════════════════
# Patrones de lo que NUNCA puede salir. Es la segunda línea: la primera es que `detalle`
# se compone de plantillas nuestras y `evidencia` de una lista blanca de claves.
_SECRETO_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{6,}"          # OpenAI/Anthropic/Groq
    r"|Bearer\s+\S{8,}"                 # header de autorización
    r"|x-api-key\s*[:=]\s*\S+"
    r"|api[_-]?key\s*[:=]\s*\S+"
    r"|ghp_[A-Za-z0-9]{10,}"            # GitHub
    r"|AKIA[0-9A-Z]{12,}"               # AWS
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"  # JWT
    r"|[A-Za-z0-9_\-]{40,})",           # cualquier token largo sin espacios
    re.I,
)

#: Cabeceras cuyo VALOR puede viajar en `evidencia`. Nada fuera de acá entra.
_CABECERAS_FORENSES = frozenset({
    "retry-after", "request-id", "x-request-id", "x-amzn-requestid",
    "x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens",
    "x-should-retry", "anthropic-ratelimit-requests-reset",
})

_MAX_DETALLE = 200
_MAX_VALOR = 120


def _texto(x: Any) -> str:
    """Cualquier cosa a str, sin levantar. bytes → utf-8 con reemplazo."""
    if x is None:
        return ""
    if isinstance(x, bytes):
        try:
            return x.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — un bytes patológico no rompe el traductor
            return ""
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:  # noqa: BLE001 — un __str__ que explota no rompe el traductor
        return ""


def _sin_secretos(s: str) -> str:
    """Reemplaza cualquier cosa con pinta de credencial. Defensa en profundidad."""
    try:
        return _SECRETO_RE.sub("«redactado»", s)
    except Exception:  # noqa: BLE001
        return "«redactado»"


def _valor_seguro(v: Any) -> Any:
    """Escalar apto para `evidencia`. Los strings se recortan y se redactan."""
    if isinstance(v, bool) or isinstance(v, int) or isinstance(v, float):
        return v
    s = _sin_secretos(_texto(v)).strip()
    return s[:_MAX_VALOR]


def _detalle(plantilla: str, **partes: Any) -> str:
    """`detalle` SIEMPRE sale de acá: plantilla nuestra + escalares seguros."""
    seguras = {k: _valor_seguro(v) for k, v in partes.items()}
    try:
        texto = plantilla.format(**seguras)
    except Exception:  # noqa: BLE001 — una plantilla mal formada no rompe el traductor
        texto = plantilla
    return _sin_secretos(texto)[:_MAX_DETALLE]


def _causa(causa: str, detalle: str, *, fuente: str, evidencia: Optional[dict] = None,
           retry_after_s: Optional[float] = None,
           reintentable: Optional[bool] = None) -> CausaModelo:
    ev = {}
    for k, v in (evidencia or {}).items():
        if v is None:
            continue
        ev[str(k)[:40]] = _valor_seguro(v)
    return CausaModelo(
        causa=causa,
        estado=ROTO,
        detalle=detalle,
        evidencia=ev,
        reintentable=(causa in _REINTENTABLES) if reintentable is None else bool(reintentable),
        retry_after_s=retry_after_s,
        fuente=fuente,
    )


# ══ HOST: remoto vs local, y qué local ═════════════════════════════════════════════
_HOSTS_LOCALES = frozenset({"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"})
_PUERTO_OLLAMA = 11434
#: Puertos de servicios PROPIOS de Aleph. Si uno de éstos rechaza, la culpa es nuestra.
_PUERTOS_ALEPH = frozenset({8926, 8923})

_HOST_EN_TEXTO_RE = re.compile(r"https?://([^/\s'\"]+)", re.I)


def _host_puerto(url: Any, *extra_textos: Any) -> tuple[Optional[str], Optional[int]]:
    """(host, puerto) desde una URL explícita o, si no hay, rastreando el texto."""
    candidatos = [_texto(url)] + [_texto(t) for t in extra_textos]
    for c in candidatos:
        if not c:
            continue
        u = c if "://" in c else ""
        if not u:
            m = _HOST_EN_TEXTO_RE.search(c)
            u = m.group(0) if m else ""
        if not u:
            continue
        try:
            partes = urlsplit(u)
            if partes.hostname:
                return partes.hostname, partes.port
        except Exception:  # noqa: BLE001 — una URL basura no rompe el traductor
            continue
    return None, None


def _es_local(host: Optional[str]) -> bool:
    return bool(host) and host.lower() in _HOSTS_LOCALES


def _transporte_local(host: Optional[str], puerto: Optional[int], fuente: str,
                      *, sintoma: str, evidencia: dict) -> CausaModelo:
    """Un transporte caído contra 127.0.0.1 NO es «sin red»: no hay red de por medio."""
    if puerto == _PUERTO_OLLAMA:
        return _causa(
            SIN_RUNTIME,
            _detalle("Ollama no responde en {host}:{puerto} ({sintoma}). Inícialo y prueba de nuevo.",
                     host=host, puerto=puerto, sintoma=sintoma),
            fuente=fuente, evidencia=evidencia)
    return _causa(
        FALLA_DE_ALEPH,
        _detalle("Un servicio local de Aleph no responde en {host}:{puerto} ({sintoma}). "
                 "No es tu configuración: copia el reporte.",
                 host=host, puerto=puerto or "?", sintoma=sintoma),
        fuente=fuente, evidencia=evidencia)


# ══ RETRY-AFTER ════════════════════════════════════════════════════════════════════
_HORA_RE = re.compile(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*$")
_EPOCH_RE = re.compile(r"\b(1[0-9]{9})\b")
#: «in 2h» y también el «2h» pelado — `_hint_de_blob` ya se comió el «resets in».
_UNIDADES = r"(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)"
_EN_RE = re.compile(r"\bin\s+(\d+)\s*" + _UNIDADES + r"\b", re.I)
_DURACION_RE = re.compile(r"^\s*(\d+)\s*" + _UNIDADES + r"\s*$", re.I)
_UNIDAD_S = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
             "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
             "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600}


def _positivo(v: Optional[float]) -> Optional[float]:
    """None jamás 0: un retry_after de 0 o negativo no informa nada, así que es ausencia."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _retry_after_de_cabecera(valor: Any, ahora: Optional[float] = None) -> Optional[float]:
    """`Retry-After`: segundos (RFC 9110 delta-seconds) o HTTP-date."""
    s = _texto(valor).strip()
    if not s:
        return None
    try:
        return _positivo(float(s))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        fecha = parsedate_to_datetime(s)
        if fecha is None:
            return None
        t = time.time() if ahora is None else float(ahora)
        return _positivo(fecha.timestamp() - t)
    except Exception:  # noqa: BLE001 — una fecha basura es ausencia, no una excepción
        return None


def _retry_after_de_hint(hint: Any, ahora: Optional[float] = None) -> Optional[float]:
    """El `reset_hint` del CLI a segundos.

    Tres formas reales del binario (`claude_cli._reset_hint`): la hora de pared ya formateada
    («02:59»), un epoch («…limit reached|1799999999») y el texto crudo («resets in 2h»).
    La hora de pared se resuelve a la PRÓXIMA ocurrencia desde `ahora`, en hora local.
    """
    s = _texto(hint).strip()
    if not s:
        return None
    t = time.time() if ahora is None else float(ahora)

    m = _EPOCH_RE.search(s)
    if m:
        return _positivo(int(m.group(1)) - t)

    m = _EN_RE.search(s) or _DURACION_RE.match(s)
    if m:
        return _positivo(int(m.group(1)) * _UNIDAD_S.get(m.group(2).lower(), 1))

    m = _HORA_RE.match(s)
    if m:
        try:
            hh, mm = int(m.group(1)), int(m.group(2))
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                return None
            local = time.localtime(t)
            medianoche = t - (local.tm_hour * 3600 + local.tm_min * 60 + local.tm_sec)
            objetivo = medianoche + hh * 3600 + mm * 60
            if objetivo <= t:
                objetivo += 86400          # ya pasó hoy → es mañana
            return _positivo(objetivo - t)
        except Exception:  # noqa: BLE001
            return None
    return None


# ══ HTTP → CAUSA (compartido por urllib, cli y litellm) ════════════════════════════
def _por_status(status: int, fuente: str, *, es_cli: bool = False,
                tenia_key: bool = True, cuerpo: str = "") -> tuple[str, str]:
    """(causa, plantilla). Los comentarios del vocabulario mandan: 401 «la key no sirve»,
    402 «la key sirve, no hay saldo», 429 «hay que esperar», 5xx «proveedor caído»."""
    if status == 401:
        # En BYO-CLI la credencial es la SESIÓN del usuario, no una key: un 401 ahí es
        # `sin_sesion` (lo mismo que ERR_NO_AUTH de cli_brain), no `key_invalida`.
        if es_cli:
            return SIN_SESION, "Tu sesión del CLI caducó (HTTP {status}). Vuelve a entrar."
        # ⚠️ [F7·A] 401 SIN HABER MANDADO CREDENCIAL NO ES «te la rechazaron».
        #
        # EL BUG MEDIDO (2026-08-06): un turno con llave basura y un turno SIN NINGUNA llave
        # daban la MISMA causa —`key_invalida`, «El proveedor rechazó la credencial»—. Con
        # el vault vacío eso es literalmente falso: no había credencial que rechazar. Y el
        # botón que sale de cada causa es distinto: `falta_key` → **[Poner la llave]**,
        # `key_invalida` → **[Cambiar la llave]**. Mandar a alguien a cambiar una llave que
        # nunca puso es hacerle perder la tarde.
        #
        # Es la MISMA distinción que el motor ya hace (`motor_verdad._causa_de_http`, con su
        # `tenia_key`); acá faltaba el dato, no el criterio. Default `True` = el
        # comportamiento de siempre para todo llamador que todavía no lo sepa.
        return (KEY_INVALIDA, "El proveedor rechazó la credencial (HTTP {status}).") if tenia_key else \
               (FALTA_KEY, "No mandamos ninguna credencial y el proveedor pidió una "
                           "(HTTP {status}): falta tu llave.")
    if status == 402:
        return SIN_CREDITO, "La credencial sirve pero no hay saldo (HTTP {status})."
    if status == 403:
        # ⚠️ LEY SELLADA (persona usuaria, 2026-08-07): UN 403 NO ES AUTOMÁTICAMENTE LA CREDENCIAL.
        # Mandar a rotar una llave perfecta es de los peores errores posibles: la persona
        # borra algo que funciona, lo vuelve a pegar, y sigue sin andar.
        #
        # MEDIDO: sin `User-Agent`, groq contesta **403 «error code: 1010»** — eso es el WAF
        # de Cloudflare bloqueando por firma de cliente, y la firma es NUESTRA. No hay
        # credencial en juego: la misma llave, con el header puesto, contesta 400.
        # Es culpa de Aleph, y la causa lo dice.
        if bloqueo_de_infra(cuerpo):
            return FALLA_DE_ALEPH, ("El proveedor bloqueó nuestro cliente antes de mirar la "
                                    "credencial (HTTP {status}). Tu llave no está en juego.")
        if ritmo_de_infra(cuerpo):
            return RATE_LIMIT, ("El proveedor nos frenó por ritmo antes de mirar la "
                                "credencial (HTTP {status}). Hay que esperar.")
        return PLAN_INSUFICIENTE, "Autenticó, pero el plan no cubre este pedido (HTTP {status})."
    if status == 404:
        return MODELO_NO_DISPONIBLE, "El proveedor no conoce ese modelo o esa ruta (HTTP {status})."
    if status in (408, 504):
        return TIMEOUT, "El proveedor tardó demasiado (HTTP {status})."
    if status == 413:
        # ── [Gate 4 · F5 · 5.1] EL 413 TIENE CAUSA PROPIA ─────────────────────────
        # MEDIDO (certificación 2026-08-08, ESTADO-CERT §12.2): 5 piezas equipadas = 49
        # tools, y Groq contesta **413 con `x-ratelimit-remaining-requests: 1000`**. La
        # cuota estaba intacta: lo que no entraba era el pedido.
        #
        # Hasta acá el 413 caía en el 4xx genérico → `error_upstream` («el proveedor
        # rechazó el pedido»), que es verdad y no sirve: manda a revisar un pedido que
        # está perfecto. Es EXACTAMENTE el cambio de veredicto que F1c ya había hecho
        # para el 400 de Ollama, y por el mismo motivo: **el camino del usuario es otro**
        # (acortar, no revisar) y no es reintentable tal cual.
        #
        # `contexto_excedido` es la causa correcta y **ya existe sellada, con copy en las
        # dos superficies** — no se inventa vocabulario para decir lo que el vocabulario
        # ya sabe decir. Lo que distingue este 413 de un pedido largo escrito por la
        # persona es el `motivo` de la evidencia (`demasiadas_tools`), que la superficie
        # usa para no culpar a nadie de algo que hizo la casa.
        return CONTEXTO_EXCEDIDO, ("El pedido no entra en el tamaño que acepta ese "
                                   "proveedor (HTTP {status}).")
    if status == 429:
        return RATE_LIMIT, "Llegaste al límite de uso (HTTP {status}). Hay que esperar."
    if 500 <= status <= 599:
        return PROVEEDOR_CAIDO, "El proveedor devolvió un error suyo (HTTP {status})."
    if 400 <= status <= 499:
        return ERROR_UPSTREAM, "El proveedor rechazó el pedido (HTTP {status})."
    return ERROR_UPSTREAM, "Respuesta inesperada del proveedor (HTTP {status})."


def _cabeceras_forenses(headers: Any) -> dict:
    """Sólo las de la lista blanca. Nada de Set-Cookie, Authorization ni cuerpo."""
    ev: dict = {}
    if headers is None:
        return ev
    try:
        items = headers.items() if hasattr(headers, "items") else list(headers)
    except Exception:  # noqa: BLE001
        return ev
    for par in items:
        try:
            k, v = par
        except Exception:  # noqa: BLE001
            continue
        nombre = _texto(k).lower().strip()
        if nombre in _CABECERAS_FORENSES:
            ev[nombre] = _valor_seguro(v)
    return ev


# ══ SÍNTOMAS DE TRANSPORTE (texto) ═════════════════════════════════════════════════
_DNS_RE = re.compile(
    r"(getaddrinfo|nodename nor servname|name or service not known|ENOTFOUND"
    r"|temporary failure in name resolution|EAI_AGAIN|no address associated"
    r"|failed to resolve|dns)", re.I)
_REFUSED_RE = re.compile(r"(connection refused|ECONNREFUSED|errno 61|errno 111)", re.I)
_INALCANZABLE_RE = re.compile(
    r"(network is unreachable|no route to host|ENETUNREACH|EHOSTUNREACH|errno 51|errno 65"
    r"|connection reset|ECONNRESET|broken pipe|EPIPE|ssl|certificate)", re.I)
_TIMEOUT_RE = re.compile(r"(timed out|timeout|ETIMEDOUT|deadline exceeded)", re.I)


def _sintoma_transporte(texto: str) -> Optional[str]:
    """Qué clase de fallo de transporte es, o None si el texto no habla de transporte."""
    if _TIMEOUT_RE.search(texto):
        return "timeout"
    if _DNS_RE.search(texto):
        return "dns"
    if _REFUSED_RE.search(texto):
        return "refused"
    if _INALCANZABLE_RE.search(texto):
        return "inalcanzable"
    return None


def _por_transporte(sintoma: str, host: Optional[str], puerto: Optional[int], fuente: str,
                    *, evidencia: dict) -> CausaModelo:
    """LA REGLA DE ORO. Sin status HTTP no hay `proveedor_caido`: hay red, o hay local."""
    if sintoma == "timeout":
        if _es_local(host):
            return _transporte_local(host, puerto, fuente, sintoma="no contestó a tiempo",
                                     evidencia=evidencia)
        return _causa(TIMEOUT, _detalle("El pedido a {host} venció sin respuesta.",
                                        host=host or "el proveedor"),
                      fuente=fuente, evidencia=evidencia)
    if _es_local(host):
        legible = {"dns": "no resuelve", "refused": "conexión rechazada",
                   "inalcanzable": "inalcanzable"}.get(sintoma, sintoma)
        return _transporte_local(host, puerto, fuente, sintoma=legible, evidencia=evidencia)
    if sintoma == "dns":
        return _causa(SIN_RED, _detalle("No se pudo resolver {host}: parece que no hay internet.",
                                        host=host or "el proveedor"),
                      fuente=fuente, evidencia=evidencia)
    if sintoma == "refused":
        return _causa(SIN_RED, _detalle("La conexión a {host} fue rechazada: no se llegó al proveedor.",
                                        host=host or "el proveedor"),
                      fuente=fuente, evidencia=evidencia)
    return _causa(SIN_RED, _detalle("No se pudo llegar a {host} por la red.",
                                    host=host or "el proveedor"),
                  fuente=fuente, evidencia=evidencia)


def _desconocido(fuente: str, *, pista: str = "", evidencia: Optional[dict] = None) -> CausaModelo:
    """El cajón HONESTO. Existe para que nada caiga en una causa que miente."""
    ev = dict(evidencia or {})
    if pista:
        ev.setdefault("clase", pista)
    return _causa(FALLO_DESCONOCIDO,
                  _detalle("Falló y no se pudo clasificar la causa ({pista}).",
                           pista=pista or "sin pista"),
                  fuente=fuente, evidencia=ev)


# ══ 1 · urllib ═════════════════════════════════════════════════════════════════════
def desde_urllib(exc: Any, *, url: Any = None, ahora: Optional[float] = None,
                 tenia_key: bool = True, con_tools: bool = False) -> CausaModelo:
    """`HTTPError` / `URLError` / `TimeoutError` / `OSError` del camino actual.

    Los cuatro casos medidos en la auditoría 2 §P1.b dan CUATRO causas distintas:
    401 con cabeceras → `key_invalida` · 429 con retry-after → `rate_limit` ·
    Errno 8 (DNS) → `sin_red` · Errno 61 (refused) → `sin_red` si el host es remoto,
    `sin_runtime`/`falla_de_aleph` si es local.

    `url` es la que se estaba pidiendo. Sin ella el host se rastrea en el texto y, si no
    aparece, se asume remoto (la respuesta conservadora de cara al usuario).

    `con_tools` sólo lo lee el 413 (F5 · 5.1): dice si el cuerpo que rebotó llevaba
    schemas de tools, que es lo que separa «tu texto no entra» de «te mandamos el
    cinturón entero». Default `False` = el comportamiento de todo llamador que todavía no
    lo sepa, y en ese caso el motivo queda del lado que no acusa a nadie.
    """
    try:
        return _desde_urllib(exc, url, ahora, tenia_key, con_tools)
    except Exception as e:  # noqa: BLE001 — el traductor nunca levanta
        return _desconocido(FUENTE_URLLIB, pista=type(e).__name__)


def _desde_urllib(exc: Any, url: Any, ahora: Optional[float],
                  tenia_key: bool = True, con_tools: bool = False) -> CausaModelo:
    nombre = type(exc).__name__
    crudo = _texto(exc)
    razon = _texto(getattr(exc, "reason", None))
    host, puerto = _host_puerto(url, getattr(exc, "url", None), getattr(exc, "filename", None), crudo)

    # [F9] EL CUERPO DEL `HTTPError` NO ESTÁ EN SU `str()`. `_texto(exc)` da «HTTP Error
    # 403: err» y nada más — el cuerpo vive en el file-like y hay que LEERLO. Sin esto, la
    # ley del 403 no podría distinguir un WAF de un plan: los dos se ven idénticos.
    # Se lee UNA vez, acotado, y sin romper si ya lo consumieron.
    cuerpo_http = ""
    try:
        _leer = getattr(exc, "read", None)
        if callable(_leer):
            _b = _leer()
            cuerpo_http = _b.decode("utf-8", "replace")[:400] if isinstance(_b, bytes) else str(_b)[:400]
    except Exception:                              # noqa: BLE001 — sin cuerpo se sigue igual
        cuerpo_http = ""

    # HTTPError: hay status, así que hay servidor del otro lado.
    status = getattr(exc, "code", None)
    if status is None:
        status = getattr(exc, "status", None)
    if isinstance(status, int) and 100 <= status <= 599 and nombre != "URLError":
        cabeceras = _cabeceras_forenses(getattr(exc, "headers", None))
        ev = {"http_status": status, "host": host, **cabeceras}
        causa, plantilla = _por_status(status, FUENTE_URLLIB, tenia_key=tenia_key,
                                       cuerpo=cuerpo_http or crudo)
        ev["tenia_credencial"] = bool(tenia_key)   # la evidencia dice de dónde sale la causa
        if status == 413:
            # [F5 · 5.1] La causa es una; el motivo dice de quién es la culpa.
            ev["motivo"] = MOTIVO_DEMASIADAS_TOOLS if con_tools else MOTIVO_PEDIDO_GRANDE
        ra = _retry_after_de_cabecera(cabeceras.get("retry-after"), ahora) if causa == RATE_LIMIT else None
        return _causa(causa, _detalle(plantilla, status=status), fuente=FUENTE_URLLIB,
                      evidencia=ev, retry_after_s=ra)

    # Sin status: transporte. Acá vive la regla de oro.
    errno = getattr(exc, "errno", None)
    if errno is None:
        errno = getattr(getattr(exc, "reason", None), "errno", None)
    ev = {"errno": errno, "host": host, "puerto": puerto, "excepcion": nombre}

    sintoma = _sintoma_transporte(razon or crudo)
    if sintoma is None and nombre in ("TimeoutError", "socket.timeout"):
        sintoma = "timeout"
    if sintoma is None and isinstance(errno, int):
        sintoma = {61: "refused", 111: "refused", 8: "dns", -2: "dns", -3: "dns",
                   51: "inalcanzable", 65: "inalcanzable", 60: "timeout",
                   110: "timeout", 104: "inalcanzable", 32: "inalcanzable"}.get(errno)
    if sintoma is None and nombre in ("URLError", "ConnectionRefusedError", "ConnectionError",
                                      "ConnectionResetError", "OSError", "socket.gaierror",
                                      "gaierror"):
        sintoma = "inalcanzable"          # es transporte aunque no sepamos cuál
    if sintoma is not None:
        return _por_transporte(sintoma, host, puerto, FUENTE_URLLIB, evidencia=ev)

    return _desconocido(FUENTE_URLLIB, pista=nombre, evidencia=ev)


# ══ 2 · CLI ════════════════════════════════════════════════════════════════════════
# Absorbe y SUPERA a `cli_brain.claude_cli.classify_error`. Lo que agrega:
#   · DNS caído → `sin_red`            (hoy cae en `model_error`)
#   · binario ausente → `cli_no_instalado`  ·  permiso denegado → `cli_sin_permisos`
#   · desconocido → `fallo_desconocido`  (hoy cae en `model_error`, que MIENTE)
#   · el `reset_hint` se conserva como `retry_after_s` en segundos
# Los regex de throttle/auth/transitorio son los mismos que ya probó cli_brain.
_CLI_THROTTLE_RE = re.compile(r"(usage limit|rate.?limit|\b429\b|too many requests|quota)", re.I)
_CLI_AUTH_RE = re.compile(
    r"(\"loggedIn\"\s*:\s*false|not logged in|please run /login|invalid api key"
    r"|authentication_error|oauth token has expired|unauthorized|\b401\b)", re.I)
_CLI_TRANSITORIO_RE = re.compile(
    r"(overloaded|\b529\b|capacity|temporarily unavailable|service unavailable|\b503\b"
    r"|internal server error|\b500\b|bad gateway|\b502\b)", re.I)
_CLI_NO_INSTALADO_RE = re.compile(
    r"(command not found|no such file or directory|ENOENT|is not recognized as an internal"
    r"|executable file not found)", re.I)
_CLI_PERMISOS_RE = re.compile(r"(permission denied|EACCES|EPERM|operation not permitted)", re.I)
_CLI_PLAN_RE = re.compile(
    r"(does not have access|not entitled|upgrade your plan|insufficient plan|plan does not"
    r"|requires a .{0,20}plan|\b403\b|forbidden)", re.I)
_CLI_MODELO_RE = re.compile(
    r"(model not found|unknown model|no such model|model_not_found|invalid model)", re.I)
_CLI_CREDITO_RE = re.compile(r"(insufficient (credit|funds|balance)|\b402\b|payment required)", re.I)
_CLI_VERSION_RE = re.compile(r"(please update|version .{0,20}(too old|no longer supported)|outdated version)", re.I)
_CLI_COLGADO_RE = re.compile(r"(waiting for input|stdin is not a tty|interactive prompt)", re.I)


def desde_cli(stderr: Any = "", rc: Any = None, result_event: Any = None, *,
              stdout: Any = "", url: Any = None,
              ahora: Optional[float] = None) -> CausaModelo:
    """Fallo de un CLI spawneado (`claude -p`, `codex exec`).

    Si hay `result_event` del `stream-json`, MANDA: su `is_error` / `api_error_status` /
    `terminal_reason` son el contrato medido del binario (auditoría 3 §0.3). Si no lo hay,
    se clasifica por texto — con `fallo_desconocido` como cajón honesto, jamás `model_error`.
    """
    try:
        return _desde_cli(stderr, rc, result_event, stdout, url, ahora)
    except Exception as e:  # noqa: BLE001 — el traductor nunca levanta
        return _desconocido(FUENTE_CLI, pista=type(e).__name__)


def _desde_cli(stderr: Any, rc: Any, result_event: Any, stdout: Any,
               url: Any, ahora: Optional[float]) -> CausaModelo:
    blob = (_texto(stderr) + "\n" + _texto(stdout)).strip()
    hint_reset = _hint_de_blob(blob)

    # ── el result event manda ─────────────────────────────────────────────────────
    if isinstance(result_event, dict):
        ev: dict = {}
        for k in ("api_error_status", "terminal_reason", "subtype", "num_turns",
                  "duration_ms", "session_id", "uuid"):
            if result_event.get(k) is not None:
                ev[k] = _valor_seguro(result_event.get(k))
        if rc is not None:
            ev["returncode"] = _valor_seguro(rc)

        status = result_event.get("api_error_status")
        if isinstance(status, int) and 100 <= status <= 599:
            causa, plantilla = _por_status(status, FUENTE_CLI, es_cli=True)
            ra = _retry_after_de_hint(hint_reset, ahora) if causa == RATE_LIMIT else None
            return _causa(causa, _detalle(plantilla, status=status), fuente=FUENTE_CLI,
                          evidencia=ev, retry_after_s=ra)

        terminal = _texto(result_event.get("terminal_reason")).lower()
        if terminal in ("timeout", "max_turns_exceeded", "deadline"):
            return _causa(TIMEOUT, _detalle("El CLI se cortó por límite: {r}.", r=terminal),
                          fuente=FUENTE_CLI, evidencia=ev)
        if result_event.get("is_error"):
            # Hay fallo declarado pero sin status: se cae al texto, que puede saber más.
            porTexto = _cli_por_texto(blob, rc, ev, hint_reset, ahora)
            if porTexto is not None:
                return porTexto
            return _causa(ERROR_UPSTREAM,
                          _detalle("El CLI reportó un error sin status ({r}).",
                                   r=terminal or "sin terminal_reason"),
                          fuente=FUENTE_CLI, evidencia=ev)

    # ── sin result event: el texto ────────────────────────────────────────────────
    ev = {"returncode": rc} if rc is not None else {}
    porTexto = _cli_por_texto(blob, rc, ev, hint_reset, ahora)
    if porTexto is not None:
        return porTexto
    return _desconocido(FUENTE_CLI, pista=f"rc={rc}" if rc is not None else "sin señal",
                        evidencia=ev)


_HINT_RESETS_RE = re.compile(r"resets?(?:\s+(?:at|in))?\s+([^\n\"\.]{1,60})", re.I)
_HINT_EPOCH_RE = re.compile(r"limit reached\|(\d{9,12})")


def _hint_de_blob(blob: str) -> str:
    """El `reset_hint` crudo, con las tres formas del binario."""
    m = _HINT_EPOCH_RE.search(blob)
    if m:
        return m.group(0)
    m = _HINT_RESETS_RE.search(blob)
    if m:
        return m.group(1).strip()
    return ""


def _cli_por_texto(blob: str, rc: Any, ev: dict, hint_reset: str,
                   ahora: Optional[float]) -> Optional[CausaModelo]:
    """Clasificación por texto. `None` = no se reconoció (el llamante decide el cajón)."""
    if not blob:
        return None

    # 1 · LA RED PRIMERO. Éste es el arreglo del §P1.e: hoy un DNS caído sale `model_error`.
    sintoma = _sintoma_transporte(blob)
    if sintoma in ("dns", "inalcanzable"):
        host, puerto = _host_puerto(None, blob)
        return _por_transporte(sintoma, host, puerto, FUENTE_CLI, evidencia=ev)
    if sintoma == "refused":
        host, puerto = _host_puerto(None, blob)
        return _por_transporte("refused", host, puerto, FUENTE_CLI, evidencia=ev)

    # 2 · el binario, antes que nada del proveedor
    if _CLI_NO_INSTALADO_RE.search(blob):
        return _causa(CLI_NO_INSTALADO,
                      _detalle("No se encontró el binario del CLI en esta máquina."),
                      fuente=FUENTE_CLI, evidencia=ev)
    if _CLI_PERMISOS_RE.search(blob):
        return _causa(CLI_SIN_PERMISOS,
                      _detalle("El CLI no tiene permisos para correr aquí."),
                      fuente=FUENTE_CLI, evidencia=ev)
    if _CLI_VERSION_RE.search(blob):
        return _causa(CLI_VERSION_VIEJA,
                      _detalle("La versión del CLI quedó por debajo de la mínima."),
                      fuente=FUENTE_CLI, evidencia=ev)
    if _CLI_COLGADO_RE.search(blob):
        return _causa(CLI_INTERACTIVO_COLGADO,
                      _detalle("El CLI se quedó esperando una respuesta interactiva."),
                      fuente=FUENTE_CLI, evidencia=ev)

    # 3 · el proveedor / la cuenta
    if _CLI_THROTTLE_RE.search(blob):
        ra = _retry_after_de_hint(hint_reset, ahora)
        ev2 = dict(ev)
        if hint_reset:
            ev2["reset_hint"] = hint_reset
        return _causa(RATE_LIMIT,
                      _detalle("Se agotó tu ventana de uso del CLI."),
                      fuente=FUENTE_CLI, evidencia=ev2, retry_after_s=ra)
    if _CLI_CREDITO_RE.search(blob):
        return _causa(SIN_CREDITO, _detalle("La cuenta del CLI no tiene saldo."),
                      fuente=FUENTE_CLI, evidencia=ev)
    if _CLI_AUTH_RE.search(blob):
        return _causa(SIN_SESION,
                      _detalle("La sesión del CLI no está activa. Vuelve a entrar."),
                      fuente=FUENTE_CLI, evidencia=ev)
    if _CLI_PLAN_RE.search(blob):
        return _causa(PLAN_INSUFICIENTE,
                      _detalle("Tu plan del CLI no cubre este pedido."),
                      fuente=FUENTE_CLI, evidencia=ev)
    if _CLI_MODELO_RE.search(blob):
        return _causa(MODELO_NO_DISPONIBLE,
                      _detalle("El CLI no conoce ese modelo."),
                      fuente=FUENTE_CLI, evidencia=ev)
    if _CLI_TRANSITORIO_RE.search(blob):
        return _causa(PROVEEDOR_CAIDO,
                      _detalle("El proveedor del CLI está sobrecargado. Es transitorio."),
                      fuente=FUENTE_CLI, evidencia=ev)
    if sintoma == "timeout":
        return _causa(TIMEOUT, _detalle("El CLI no respondió a tiempo."),
                      fuente=FUENTE_CLI, evidencia=ev)
    return None


# ══ 3 · LiteLLM ════════════════════════════════════════════════════════════════════
# SIN importar litellm: se clasifica por NOMBRE DE CLASE y atributos. Así esta pieza no
# ata el árbol a una dependencia que todavía no está, y sigue funcionando si nunca entra.
#
# El arreglo central (auditoría 1 §P1.d): LiteLLM entrega `InternalServerError` con
# `status_code=500` cuando lo que pasó es que NO HAY RED. Antes de creerle al 500 se mira
# el `__context__`; si abajo hay un ConnectError/getaddrinfo, la causa es `sin_red`.
#
# El SEGUNDO arreglo (medido en F3, `_STATUS_MANDA` más abajo): esta tabla no es la última
# palabra. Cuando el nombre de clase y el `status_code` se contradicen en uno de los cinco
# códigos accionables, gana el status — litellm 1.93.0 emite `BadRequestError` con
# `status_code=401`, y mandar al usuario a revisar su pedido cuando lo que pasa es que su
# key no sirve es exactamente la clase de mentira que este módulo existe para borrar.
_CLASE_A_CAUSA = {
    "AuthenticationError": KEY_INVALIDA,
    "PermissionDeniedError": PLAN_INSUFICIENTE,
    "NotFoundError": MODELO_NO_DISPONIBLE,
    "RateLimitError": RATE_LIMIT,
    "Timeout": TIMEOUT,
    "APITimeoutError": TIMEOUT,
    "APIConnectionError": SIN_RED,
    "BudgetExceededError": SIN_CREDITO,
    # ── F1c · CAMBIO DE VEREDICTO DECLARADO (las dos filas que F1 dejó esperando) ──
    # ANTES: las dos salían `error_upstream` («el proveedor rechazó el pedido»), con el
    # hueco escrito al lado. AHORA cada una dice lo suyo, y el cambio no es cosmético:
    # `error_upstream` es TEMPORAL/una-vuelta en repair (`DISEÑO-REPAIR-v1.md` §2.2), o sea
    # que un pedido demasiado largo se REINTENTABA una vez — gastando una llamada entera
    # para que el mismo texto no entre en la misma ventana. Las dos nuevas son permanentes.
    "ContextWindowExceededError": CONTEXTO_EXCEDIDO,
    "ContentPolicyViolationError": POLITICA_DE_CONTENIDO,
    # `RejectedRequestError` NO se mueve: litellm lo levanta desde sus guardrails y desde
    # `prompt_injection`, que no son la política de contenido del PROVEEDOR. Meterlo en
    # `politica_de_contenido` sería decirle al usuario «el proveedor se negó» cuando quien
    # se negó fue una capa intermedia. Se queda donde estaba, y esta línea dice por qué.
    "RejectedRequestError": ERROR_UPSTREAM,
    "UnprocessableEntityError": ERROR_UPSTREAM,
    "BadRequestError": ERROR_UPSTREAM,
    "UnsupportedParamsError": ERROR_UPSTREAM,
    "JSONSchemaValidationError": ERROR_UPSTREAM,
    "APIResponseValidationError": ERROR_UPSTREAM,
    "InternalServerError": PROVEEDOR_CAIDO,
    "ServiceUnavailableError": PROVEEDOR_CAIDO,
    "BadGatewayError": PROVEEDOR_CAIDO,
    "MidStreamFallbackError": PROVEEDOR_CAIDO,
}

# ── PRECEDENCIA: CUANDO LA CLASE Y EL STATUS SE CONTRADICEN, MANDA EL STATUS ──────
# MEDIDO EN F3 (litellm 1.93.0, vara `verify_adaptador_litellm`): un 401 de un endpoint
# OpenAI-compat sale como `BadRequestError` **con `status_code=401`**. La clase dice «el
# pedido está mal» y el status dice «la credencial no sirve», y son cosas distintas: con
# la clase mandando, ese 401 salía `error_upstream` (no reintentable, «revisá el pedido»)
# cuando la acción correcta es «revisá tu key».
#
# El status gana SÓLO en estos cinco, y no es una preferencia estética:
#   · son los códigos donde el status tiene un significado ÚNICO y accionable
#     (401 la key no sirve · 402 no hay saldo · 403 el plan no cubre · 404 no existe ese
#     modelo · 429 hay que esperar) — cada uno manda al usuario a un lugar distinto;
#   · y son los que la auditoría 1 midió que LiteLLM rotula mal: sus nombres de clase
#     salen de un `except` por proveedor, no de la respuesta HTTP.
# Fuera de esos cinco la clase sigue mandando: un `BadRequestError` con 500, o un 400 de
# `ContextWindowExceededError`, dicen más que su número.
#
# NO se toca lo de arriba: el síntoma de TRANSPORTE sigue ganándole a los dos (la regla
# de oro — sin llegar al proveedor no hay status del proveedor que valga).
#: [F9] FIRMAS DE UN BLOQUEO DE INFRAESTRUCTURA — no de una credencial.
#:
#: Un WAF que nos bloquea contesta 403 igual que un plan insuficiente, y el número solo no
#: alcanza para distinguirlos. Estas firmas son DECLARADAS y salen de lo medido, no de
#: imaginar: `error code: 1010` es Cloudflare rechazando por firma de cliente (groq, medido
#: el 2026-08-07 al omitir el `User-Agent`).
#:
#: ⚠️ `1015` NO ESTÁ ACÁ, y es a propósito: ése es el RITMO de Cloudflare y su causa es
#: `rate_limit`, no una falla nuestra. Meter toda la familia 10xx en la misma bolsa sería
#: cambiar un diagnóstico equivocado por otro — pero dejarlo salir como `key_invalida`
#: sería el MISMO error que esta ley prohíbe. Va abajo, en `_INFRA_RITMO`.
#:
#: ⚠️ DECLARADO-NO-VERIFICADO: `1010` está MEDIDO (groq, 2026-08-07, sin `User-Agent`). El
#: resto sale de la documentación de Cloudflare, no de una medición nuestra. Se marcan como
#: lo que son para que nadie lea esta tabla como ocho hechos comprobados.
_INFRA_403 = (
    "error code: 1010",      # firma de cliente rechazada (medido en groq sin User-Agent)
    "error code: 1020",      # regla de firewall del proveedor
    "attention required! | cloudflare",
    "cloudflare to restrict access",
)


#: El WAF frenándonos por RITMO. Un 403 con esta firma no es la llave ni una falla nuestra:
#: es esperar. (Cloudflare suele mandarlo como 429, pero 403 está documentado.)
_INFRA_RITMO = ("error code: 1015",)


def bloqueo_de_infra(cuerpo: str) -> bool:
    """¿Este cuerpo es un WAF bloqueándonos, y no el proveedor juzgando la credencial?"""
    txt = (cuerpo or "").lower()
    return any(f in txt for f in _INFRA_403)


def ritmo_de_infra(cuerpo: str) -> bool:
    """¿El WAF nos frenó por ritmo? Tampoco es la credencial — pero se resuelve esperando."""
    txt = (cuerpo or "").lower()
    return any(f in txt for f in _INFRA_RITMO)


_STATUS_MANDA = frozenset({401, 402, 403, 404, 429})

_PLANTILLA_LITELLM = {
    KEY_INVALIDA: "El proveedor rechazó la credencial (HTTP {status}).",
    # [F7·A·bis] La MISMA distinción que la vía urllib, con el MISMO copy. Que la causa
    # exista sin plantilla es peor que no tenerla: caería en «El proveedor falló ({clase})»
    # —el nombre técnico en la cara de la persona— y rompe la regla sellada de que ninguna
    # causa llega a una superficie sin copy.
    FALTA_KEY: "No mandamos ninguna credencial y el proveedor pidió una "
               "(HTTP {status}): falta tu llave.",
    PLAN_INSUFICIENTE: "Autenticó, pero el plan no cubre este pedido (HTTP {status}).",
    MODELO_NO_DISPONIBLE: "El proveedor no conoce ese modelo (HTTP {status}).",
    RATE_LIMIT: "Llegaste al límite de uso (HTTP {status}). Hay que esperar.",
    TIMEOUT: "El proveedor tardó demasiado.",
    SIN_CREDITO: "La credencial sirve pero no hay saldo (HTTP {status}).",
    ERROR_UPSTREAM: "El proveedor rechazó el pedido ({clase}).",
    PROVEEDOR_CAIDO: "El proveedor devolvió un error suyo (HTTP {status}).",
    # F1c · el detalle LLEVA LA ACCIÓN, que es para lo que existen estas dos causas.
    CONTEXTO_EXCEDIDO: "El pedido no entra en la ventana de ese modelo. Acórtalo y prueba de nuevo.",
    POLITICA_DE_CONTENIDO: "El proveedor no acepta este contenido. Reformúlalo y prueba de nuevo.",
}


def desde_litellm(exc: Any, *, url: Any = None, ahora: Optional[float] = None,
                  tenia_key: bool = True) -> CausaModelo:
    """Excepción de LiteLLM, clasificada SIN importar litellm.

    Lee: nombre de clase · `status_code` · `litellm_response_headers` (donde LiteLLM deja
    el `retry-after` y el `request-id` reales, fuera del contrato de `openai`) · y
    `__context__`, que es lo único que separa un 500 de verdad de una red caída.

    Orden de precedencia: transporte > status accionable (`_STATUS_MANDA`) > clase >
    status cualquiera > `fallo_desconocido`.

    `tenia_key` es el mismo parámetro que `desde_urllib`, y por el mismo motivo: un 401
    sin haber mandado credencial es `falta_key`, no `key_invalida`. El default `True`
    conserva el comportamiento para todo llamador que todavía no sepa el dato.
    """
    try:
        return _desde_litellm(exc, url, ahora, tenia_key)
    except Exception as e:  # noqa: BLE001 — el traductor nunca levanta
        return _desconocido(FUENTE_LITELLM, pista=type(e).__name__)


def _contexto_es_transporte(exc: Any) -> tuple[Optional[str], str]:
    """Recorre `__cause__`/`__context__` buscando un fallo de transporte. (síntoma, texto)."""
    visto = set()
    actual = exc
    for _ in range(8):                      # cadena acotada: nunca un ciclo infinito
        if actual is None or id(actual) in visto:
            break
        visto.add(id(actual))
        for attr in ("__cause__", "__context__"):
            hijo = getattr(actual, attr, None)
            if hijo is None or id(hijo) in visto:
                continue
            texto = _texto(hijo) + " " + type(hijo).__name__
            s = _sintoma_transporte(texto)
            if s:
                return s, texto
            actual = hijo
            break
        else:
            break
    return None, ""


def _desde_litellm(exc: Any, url: Any, ahora: Optional[float],
                   tenia_key: bool = True) -> CausaModelo:
    clase = type(exc).__name__
    crudo = _texto(exc)
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = None

    cabeceras = _cabeceras_forenses(getattr(exc, "litellm_response_headers", None)) or \
        _cabeceras_forenses(getattr(getattr(exc, "response", None), "headers", None))
    ev = {"clase": clase, "http_status": status, "tenia_credencial": bool(tenia_key),
          **cabeceras}
    prov = getattr(exc, "llm_provider", None)
    if prov:
        ev["llm_provider"] = prov

    # ── EL ARREGLO P1.d: antes de creerle al status, mirar qué hay abajo ──────────
    sintoma, _ = _contexto_es_transporte(exc)
    if sintoma is None and status is None:
        sintoma = _sintoma_transporte(crudo)
    if sintoma is not None:
        host, puerto = _host_puerto(url, crudo)
        ev["motivo_transporte"] = sintoma
        return _por_transporte(sintoma, host, puerto, FUENTE_LITELLM, evidencia=ev)

    # ── PRECEDENCIA CLASE vs STATUS (ver `_STATUS_MANDA`) ────────────────────────
    # El orden es: transporte (arriba) > status accionable > clase > status cualquiera.
    # La contradicción se DEJA ANOTADA en la evidencia (`precedencia` + `clase_decia`):
    # el día que litellm arregle sus clases, la evidencia dice si esto todavía se usa.
    por_clase = _CLASE_A_CAUSA.get(clase)
    por_status = None
    if status is not None:
        por_status, _ = _por_status(status, FUENTE_LITELLM, tenia_key=tenia_key,
                                    cuerpo=crudo)

    causa = por_clase
    if status in _STATUS_MANDA and por_status is not None and por_status != por_clase:
        causa = por_status
        # [F7·A·bis] SON DOS MOTIVOS DISTINTOS PARA QUE EL STATUS GANE, y no se mezclan.
        # Cuando la divergencia la produjo `tenia_key` (401 → `falta_key`), la clase de
        # litellm NO se equivocó: `AuthenticationError` era correcta para el status. Anotar
        # eso como «contradicción de clase» ensuciaría la ÚNICA evidencia que dice si
        # `_STATUS_MANDA` todavía hace falta el día que litellm arregle sus clases.
        if por_status == FALTA_KEY and not tenia_key:
            ev["precedencia"] = "sin_credencial"
        else:
            ev["precedencia"] = "status"
            if por_clase is not None:
                ev["clase_decia"] = por_clase
    if causa is None:
        causa = por_status
    if causa is None:
        return _desconocido(FUENTE_LITELLM, pista=clase, evidencia=ev)

    plantilla = _PLANTILLA_LITELLM.get(causa, "El proveedor falló ({clase}).")
    ra = _retry_after_de_cabecera(cabeceras.get("retry-after"), ahora) if causa == RATE_LIMIT else None
    return _causa(causa, _detalle(plantilla, status=status if status is not None else "?", clase=clase),
                  fuente=FUENTE_LITELLM, evidencia=ev, retry_after_s=ra)


# ══ 4 · Ollama ═════════════════════════════════════════════════════════════════════
# ANTES (F1): TODO caía en `sin_runtime`. Era honesto mientras no hubiera con qué separar,
# pero le decía «el runtime no está» a un runtime que había contestado perfectamente.
#
# LA TABLA MEDIDA (auditoría 4 §3.2, sonda S2 contra el Ollama vivo del usuario, 0.24.0):
# los seis casos de error **son distinguibles por status code** y no hay un 500 genérico
# en ninguno. Los tipos OpenAI que Ollama emite son sólo tres (`openai/openai.go:218-229`):
# `invalid_request_error` (400) · `not_found_error` (404) · `api_error` (todo lo demás).
#
#   | señal medida                                       | causa (vocabulario sellado)   |
#   |----------------------------------------------------|-------------------------------|
#   | conexión rechazada / no responde                    | sin_runtime                   |
#   | 404 + "not found"                                   | modelo_no_disponible   ← NUEVO|
#   | 400 + "the input length exceeds the context length" | contexto_excedido  ← F1c    |
#   | 400 (otro)                                          | error_upstream         ← NUEVO|
#   | 503 + "server busy … maximum pending requests"      | rate_limit             ← NUEVO|
#   | 500 + substring de `llm/status.go:85-95` (OOM)      | sin_runtime (heurística)      |
#   | 500 (otro)                                          | sin_runtime                   |
#
# TRES DECISIONES DE VOCABULARIO, porque el reporte propone nombres que NO existen en
# `motor_verdad` y este módulo no inventa causas:
#
#   · `peticion_invalida` sigue siendo `error_upstream`, cuya definición es «el proveedor
#     rechazó el pedido». Es exactamente lo que pasó, y el `motivo` de la evidencia lo
#     precisa sin mentir la causa.
#     `contexto_excedido` ERA lo mismo y en F1c dejó de serlo: tiene causa propia, porque
#     el camino del usuario es otro (acortar, no revisar) y porque no es reintentable.
#   · `runtime_saturado` → `rate_limit`, cuya definición es «hay que esperar». Un 503 con
#     «maximum pending requests exceeded» es literalmente eso. La evidencia dice
#     `origen: "runtime"` para no confundirlo con la ventana de un proveedor remoto —
#     misma disciplina que F2b con `origen: "aleph"`.
#   · `memoria_insuficiente` → `sin_runtime`. No es un compromiso: la definición de
#     `sin_runtime` en `centro_modelos.py:82` es literal, «está descargado pero **no hay
#     con qué correrlo**», y un OOM es exactamente eso. Lo que sí es hueco es no poder
#     decir POR QUÉ no hay con qué; eso va en el detalle y en la evidencia.
#
# LO QUE **CAMBIA** RESPECTO DE F1, declarado: el modelo ausente (404 o su texto) deja de
# ser `sin_runtime` y pasa a `modelo_no_disponible`. La nota de alineación con
# `probar_local` se estrecha en vez de romperse: `probar_local` pregunta «¿quedó registrado
# lo que bajé?» y ahí un «no» SÍ es `sin_runtime` (no hay con qué correrlo). Acá la
# pregunta es otra —el runtime contestó 404 a una inferencia— y decirle al usuario «no hay
# runtime» cuando el runtime respondió manda a prender algo que ya está prendido. El
# detalle («bajá el modelo») ya era el correcto desde F1; lo que estaba mal era el rótulo.
_OLLAMA_AUSENTE_RE = re.compile(
    r"(model .{0,60}not found|no such model|pull the model|try pulling it first"
    r"|model .{0,40}does not exist|not found, try pulling)", re.I)
#: El string CONSTANTE con el que Ollama aplana el error rico de llama.cpp
#: (`llm/llama_server.go:2369-2381` · `server/routes.go:927`).
_OLLAMA_CONTEXTO_RE = re.compile(
    r"(input length exceeds the context length|exceed(s)? context size"
    r"|larger than the max context size|context length exceeded)", re.I)
#: 503 del scheduler cuando el canal de 512 se llenó (`sched.go:88,207` → `routes.go:3083`).
_OLLAMA_SATURADO_RE = re.compile(
    r"(server busy|maximum pending requests|max queue|too many pending)", re.I)
#: ⚠️ HEURÍSTICA FRÁGIL, Y POR ESO SE MARCA. Ollama NO expone el OOM como tipo: lo detecta
#: haciendo grep sobre el stderr del runtime (`llm/status.go:85-95`, `IsOutOfMemory()` en
#: `:101`) y al cliente le llega un 500 con texto. Replicar esa lista es replicar CÓDIGO
#: INTERNO de Ollama, no su API: cualquier versión puede cambiarla sin avisar. Cuando esto
#: dispara, la evidencia lleva `fuente: "heuristica"` para que quien lea la causa sepa que
#: no está mirando un contrato sino una coincidencia de texto.
_OLLAMA_OOM_RE = re.compile(
    r"(out of memory|cudamalloc failed|failed to allocate|not enough memory"
    r"|insufficient memory|vk_error_out_of_device_memory|unable to allocate)", re.I)
#: El mensaje RICO de llama-server (`server-context.cpp:3178-3196`), con los dos números.
#: Ollama lo aplana antes de que llegue al cliente, así que esto sólo dispara contra
#: llama-server directo. Está igual: el día que se embeba, los números ya se leen.
_CTX_RICO_RE = re.compile(
    r"input\s*\((\d+)\s*tokens?\)\s*is larger than the max context size\s*\((\d+)\s*tokens?\)",
    re.I)


def desde_ollama(exc_o_respuesta: Any, *, url: Any = None,
                 ahora: Optional[float] = None,
                 runtime_vivo: Optional[bool] = None) -> CausaModelo:
    """Fallo del runtime local. Acepta una excepción o un dict de respuesta de ollama.

    Ollama es LOCAL: **nada de acá es `sin_red`**, y ésa es la regla de oro, que no se
    toca. Si no responde, el runtime está apagado (`sin_runtime`). Si SÍ responde, lo que
    dijo se lee: ver la tabla medida de arriba.

    ── `runtime_vivo` (F5) · APAGADO NO ES LO MISMO QUE OCUPADO ────────────────────
    Un timeout contra `:11434` era SIEMPRE `sin_runtime`, y eso es correcto **mientras no
    se sepa nada más**: sin respuesta, lo único honesto es «el runtime no está». Pero la
    auditoría 4 §3.1 midió que Ollama **encola y contesta 200** — 3 requests simultáneos
    dieron 3× HTTP 200 con latencia 7,9 → 15 → 23 s, cero errores, cero 503. O sea: el
    timeout que veíamos era **nuestro cliente rindiéndose mientras el request seguía en
    cola**, con el runtime perfectamente vivo. Decirle a esa persona «prendé Ollama»
    cuando Ollama está corriendo es mandarla a arreglar lo que no está roto.

    Quien llama puede saberlo (`/api/version` contesta en 3 s aunque el modelo esté
    ocupado, porque no pasa por el semáforo del runner) y lo pasa acá:

        None  → no se sabe. **Comportamiento de F1b, byte por byte.**
        True  → el runtime CONTESTA. Un timeout entonces es `timeout` + «está ocupado».
        False → confirmado apagado. `sin_runtime`, y ahora dicho con evidencia.

    Sólo cambia el síntoma TIMEOUT. Un `refused` con `runtime_vivo=True` es una
    contradicción —contesta y no contesta— y ahí gana lo que se midió en el intento, no
    lo que dijo un chequeo anterior: sigue siendo `sin_runtime`.

        HUECO #6 · CERRADO EN F1c. Era: «falta `runtime_ocupado`; hoy sale `timeout` con
        `motivo` en la evidencia, que es honesto —el pedido venció— pero no distingue
        “tardó porque hay cola” de “tardó porque se colgó”, y el consejo al usuario es
        distinto: esperar vs. reiniciar». Ahora la causa es `runtime_ocupado` y el
        `motivo` sigue en la evidencia para quien ya lo leía.
    """
    try:
        return _desde_ollama(exc_o_respuesta, url, ahora, runtime_vivo)
    except Exception as e:  # noqa: BLE001 — el traductor nunca levanta
        return _desconocido(FUENTE_OLLAMA, pista=type(e).__name__)


def _mensaje_ollama(obj: dict) -> tuple[str, Optional[str]]:
    """(texto del error, tipo OpenAI si lo hay). Las DOS formas medidas:

        nativo        {"error": "model 'x' not found"}
        OpenAI-compat {"error": {"message": "…", "type": "not_found_error", …}}

    El middleware de traducción (`server/routes.go:1898-1908`) sirve las dos según el
    endpoint, así que las dos entran acá.
    """
    err = obj.get("error")
    if isinstance(err, dict):
        return _texto(err.get("message") or err.get("error") or ""), \
            (_texto(err.get("type")) or None)
    if err is not None:
        return _texto(err), None
    return _texto(obj.get("message") or ""), None


def _ctx_numeros(obj: Any, texto: str) -> dict:
    """`n_prompt_tokens`/`n_ctx` SI EXISTEN. Jamás inventados.

    Ollama los TIRA (`llama_server.go:2369-2381` reemplaza el error rico por una constante),
    así que por la vía Ollama esto devuelve `{}` casi siempre — y ese vacío es el dato:
    significa «no se puede saber cuánto te pasaste», no «cero».
    """
    ev: dict = {}
    if isinstance(obj, dict):
        # Los dos lugares donde pueden estar: anidados en `error` (forma de llama-server,
        # `server-task.cpp:1529-1534`) o al tope del cuerpo. Se miran los DOS porque quién
        # los pone depende de si habla llama-server directo o un envoltorio.
        candidatos = [obj]
        if isinstance(obj.get("error"), dict):
            candidatos.insert(0, obj["error"])
        for clave in ("n_prompt_tokens", "n_ctx"):
            for fuente in candidatos:
                v = fuente.get(clave)
                if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                    ev[clave] = v
                    break
    if not ev:
        m = _CTX_RICO_RE.search(texto or "")
        if m:
            try:
                ev["n_prompt_tokens"] = int(m.group(1))
                ev["n_ctx"] = int(m.group(2))
            except (TypeError, ValueError):
                ev = {}
    return ev


def _ollama_por_senal(status: Optional[int], texto: str, ev: dict,
                      obj: Any = None) -> Optional[CausaModelo]:
    """La tabla medida, en un solo lugar. `None` si esta señal no dice nada.

    El TEXTO se mira antes que el status a propósito: el status dice la familia, el texto
    dice cuál de la familia. Un 500 puede ser un OOM o el runner muriéndose, y son dos
    consejos distintos para el usuario.
    """
    # 1 · OOM — heurística sobre el stderr del runtime, marcada como tal.
    if _OLLAMA_OOM_RE.search(texto):
        return _causa(SIN_RUNTIME,
                      _detalle("No hay memoria suficiente en esta máquina para correr ese "
                               "modelo. Cierra algo, o prueba uno más chico."),
                      fuente=FUENTE_OLLAMA,
                      evidencia={**ev, "motivo": "memoria_insuficiente",
                                 "fuente": "heuristica",
                                 "origen_heuristica": "ollama llm/status.go:85-95"})
    # 2 · contexto excedido — con los números SI el body los trae (Ollama los aplana).
    #     F1c · CAMBIO DE VEREDICTO DECLARADO: era `error_upstream` + `motivo` en la
    #     evidencia. El `motivo` se CONSERVA (nadie que ya lo lea se rompe) pero la causa
    #     ahora lo dice sin que haya que abrir la evidencia, y el detalle trae la acción.
    if _OLLAMA_CONTEXTO_RE.search(texto):
        return _causa(CONTEXTO_EXCEDIDO,
                      _detalle("El texto es más largo que la ventana de contexto del modelo. "
                               "Acórtalo y prueba de nuevo."),
                      fuente=FUENTE_OLLAMA,
                      evidencia={**ev, "motivo": "contexto_excedido",
                                 **_ctx_numeros(obj, texto)})
    # 3 · modelo ausente — 404 medido, o el texto de ollama por la vía nativa.
    if status == 404 or _OLLAMA_AUSENTE_RE.search(texto):
        return _causa(MODELO_NO_DISPONIBLE,
                      _detalle("Ollama no tiene ese modelo descargado. Bájalo y prueba de nuevo."),
                      fuente=FUENTE_OLLAMA, evidencia={**ev, "motivo": "modelo_ausente"})
    # 4 · cola llena — el runtime está vivo y hay que esperarlo.
    if _OLLAMA_SATURADO_RE.search(texto) or status == 503:
        return _causa(RATE_LIMIT,
                      _detalle("Ollama está ocupado con otros pedidos. Hay que esperar."),
                      fuente=FUENTE_OLLAMA,
                      # `origen: runtime` para no confundirlo con la ventana de un proveedor
                      # remoto ni con nuestro propio techo (F2b usa `aleph`/`cli`).
                      evidencia={**ev, "motivo": "runtime_saturado", "origen": "runtime"})
    # 5 · 4xx cualquiera — el pedido está mal armado (JSON roto, campos faltantes).
    if isinstance(status, int) and 400 <= status <= 499:
        return _causa(ERROR_UPSTREAM,
                      _detalle("Ollama rechazó el pedido (HTTP {status}).", status=status),
                      fuente=FUENTE_OLLAMA,
                      evidencia={**ev, "motivo": "peticion_invalida"})
    # 6 · 5xx cualquiera — el runtime local se cayó atendiendo. Sigue siendo `sin_runtime`:
    #     no hay con qué correr esto ahora mismo.
    if isinstance(status, int) and 500 <= status <= 599:
        return _causa(SIN_RUNTIME,
                      _detalle("Ollama respondió con un error suyo (HTTP {status}).",
                               status=status),
                      fuente=FUENTE_OLLAMA,
                      evidencia={**ev, "motivo": "fallo_del_runtime"})
    return None


def _desde_ollama(obj: Any, url: Any, ahora: Optional[float],
                  runtime_vivo: Optional[bool] = None) -> CausaModelo:
    host, puerto = _host_puerto(url, getattr(obj, "url", None), _texto(obj))
    if host is None:
        host, puerto = "127.0.0.1", _PUERTO_OLLAMA     # el default del centro de modelos
    if puerto is None:
        puerto = _PUERTO_OLLAMA

    # dict: es una respuesta de la API, no una excepción
    if isinstance(obj, dict):
        texto, tipo = _mensaje_ollama(obj)
        ev = {"host": host, "puerto": puerto}
        st = obj.get("status") or obj.get("status_code")
        if isinstance(st, int) and not isinstance(st, bool):
            ev["http_status"] = st
        else:
            st = None
        if tipo:
            ev["tipo_openai"] = tipo          # de los tres que Ollama emite
        c = _ollama_por_senal(st, texto, ev, obj)
        if c is not None:
            return c
        if texto:
            # Contestó algo que no sabemos leer. `sin_runtime` sería inventar un
            # diagnóstico; el cajón honesto dice la verdad y deja el texto en la evidencia.
            return _desconocido(FUENTE_OLLAMA, pista="error de ollama sin clasificar",
                                evidencia={**ev, "error": _valor_seguro(texto)})
        return _desconocido(FUENTE_OLLAMA, pista="respuesta sin error", evidencia=ev)

    crudo = _texto(obj)
    nombre = type(obj).__name__
    ev = {"host": host, "puerto": puerto, "excepcion": nombre}

    status = getattr(obj, "code", None)
    if not isinstance(status, int) or isinstance(status, bool):
        status = getattr(obj, "status", None)
    if isinstance(status, int) and not isinstance(status, bool) \
            and 100 <= status <= 599 and nombre != "URLError":
        ev["http_status"] = status
        c = _ollama_por_senal(status, crudo, ev, obj)
        if c is not None:
            return c
        return _causa(SIN_RUNTIME,
                      _detalle("Ollama respondió con un error suyo (HTTP {status}).",
                               status=status),
                      fuente=FUENTE_OLLAMA, evidencia=ev)

    # Sin status: puede venir texto igual (una excepción del cliente que trae el cuerpo).
    c = _ollama_por_senal(None, crudo, ev, obj)
    if c is not None:
        return c

    sintoma = _sintoma_transporte(_texto(getattr(obj, "reason", None)) or crudo) or "refused"
    if runtime_vivo is not None:
        ev["runtime_vivo"] = bool(runtime_vivo)
    # F5 · APAGADO NO ES OCUPADO. Sólo el TIMEOUT cambia, y sólo con la liveness CONFIRMADA
    # por quien llama: el runtime contestó `/api/version` mientras el pedido se moría en la
    # cola (medido, auditoría 4 §3.1). Un `refused` con `runtime_vivo=True` es una
    # contradicción y ahí manda lo que se midió en ESTE intento, no un chequeo anterior.
    # F1c · CAMBIO DE VEREDICTO DECLARADO: era `timeout` + `motivo: runtime_ocupado` en la
    # evidencia (el hueco #6, escrito arriba en el docstring de `desde_ollama`). El `motivo`
    # se CONSERVA. Lo que cambia es lo que se lee sin abrir la evidencia: `timeout` en
    # repair es un GRIS que se desempata por `murio` (¿red caída o server colgado?), y acá
    # no hay ningún gris — se MIDIÓ que el runtime está vivo y encolando. La causa nueva
    # entra a repair como temporal-con-backoff, sin desempate y sin sospecha de cuelgue.
    if runtime_vivo and sintoma == "timeout":
        return _causa(RUNTIME_OCUPADO,
                      _detalle("El runtime local está corriendo pero no llegó a contestar "
                               "a tiempo: hay otro pedido ocupándolo. Espera."),
                      fuente=FUENTE_OLLAMA,
                      evidencia={**ev, "motivo": "runtime_ocupado", "origen": "runtime"})
    # Forzado local a propósito: ollama vive en la máquina. Un fallo suyo jamás es "sin red".
    # ESTA ES LA REGLA DE ORO Y NO SE TOCA: refused/timeout en :11434 → `sin_runtime`.
    return _transporte_local(host, puerto, FUENTE_OLLAMA,
                             sintoma={"dns": "no resuelve", "refused": "conexión rechazada",
                                      "timeout": "no contestó a tiempo"}.get(sintoma, sintoma),
                             evidencia=ev)


__all__ = [
    "CausaModelo", "CAUSAS", "FUENTES", "ROTO", "escala",
    "ErrorDeModelo", "causa_de_excepcion",
    "desde_urllib", "desde_cli", "desde_litellm", "desde_ollama",
    "CONTEXTO_EXCEDIDO", "POLITICA_DE_CONTENIDO", "CLI_OCUPADO", "TURNO_DETENIDO",
    "MOTIVO_DEMASIADAS_TOOLS", "MOTIVO_PEDIDO_GRANDE",
    "SESION_PERDIDA", "RUNTIME_OCUPADO",
    "SIN_RED", "TIMEOUT", "ERROR_UPSTREAM", "FALTA_KEY", "KEY_INVALIDA", "SIN_CREDITO",
    "RATE_LIMIT", "MODELO_NO_DISPONIBLE", "PLAN_INSUFICIENTE", "PROVEEDOR_CAIDO",
    "FALLA_DE_ALEPH", "FALLO_DESCONOCIDO", "GATE_BLOQUEADO", "ARGUMENTOS_INVALIDOS",
    "SIN_SESION", "CLI_NO_INSTALADO",
    "CLI_SIN_PERMISOS", "CLI_VERSION_VIEJA", "CLI_INTERACTIVO_COLGADO", "SIN_RUNTIME",
    "FUENTE_URLLIB", "FUENTE_CLI", "FUENTE_LITELLM", "FUENTE_OLLAMA",
]
