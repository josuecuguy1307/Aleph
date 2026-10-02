#!/usr/bin/env python3
"""repair.py — R3 · EL CAMINO TEMPORAL: backoff, topes y circuit breaker.

Tercera sesión de `DISEÑO-REPAIR-v1.md`. Consume el evento tipado de R1 (`MuerteMCP`) y el
veredicto de R2 (`repair_clasificar`), y decide **cuándo se puede volver a intentar**.

──────────────────────────────────────────────────────────────────────────────────
REPAIR ES LA POLÍTICA. EL DUEÑO ES EL ACTOR. Y no es una preferencia de diseño: es lo
único que el árbol permite, medido.

    `_Conexion` guarda `comando`, `args` y `cwd` — **y NO el `env`** (`dueno.py:442-450`).
    El env lleva las credenciales ya resueltas del usuario, y el dueño deliberadamente no
    se lo queda.

O sea que **nadie puede reconstruir un spec para re-spawnear**, ni el dueño ni repair. Y eso
es exactamente lo correcto:

  · repair NO spawnea ⇒ no aparece un sitio nuevo en `test_frontera_dueno.py`, y el tope,
    la lápida y `apagar_todo()` siguen viendo TODO;
  · repair no toca una credencial ni de lejos — cumple el §3.5 por construcción, no por
    disciplina;
  · el reintento ocurre **cuando alguien de verdad la necesita**, que es cuando importa. Si
    nadie la pide, no hay nada que reparar.

Repair entonces: OBSERVA muertes, CUENTA intentos, ABRE el breaker, y **le contesta al dueño
si el próximo `pedir()` puede pasar**. El dueño pregunta por un hook opcional
(`poner_guardia`), simétrico a `suscribir` de R1: sin guardia, se comporta como hoy.

──────────────────────────────────────────────────────────────────────────────────
QUÉ VE EL USUARIO: **🟡 y nada más** (§3.4). Sin «reintentando 3/5» — eso es decir
«temporal» con números, y le pasa a la persona una decisión que repair existe para tomar
sola. El 🟡 ES el fallo visible; lo que no puede pasar es terminar en 🟢 sin arreglarse, ni
quedarse en 🟡 para siempre — por eso `MAX_TOTAL_S` y el breaker son topes DUROS.

    python3 -m pytest platform/inspection/test_repair.py -q
    product/backend/.venv/bin/python platform/inspection/verify_repair_temporal.py
"""
from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import repair_clasificar as RC


def _limpiar_traza(crudo: dict) -> dict:
    """Pasa la traza por el `OutputScrubber` que ya existe.

    ⚠️ **LA HUELLA SE PUEDE PUBLICAR Y EL STDERR NO.** La huella es un digest de 12 hex del
    que no sale ningún valor (lo sella el diseño del dueño); el stderr, en cambio, es texto
    que el server escribió — y un server que imprime su token al arrancar existe. Esta traza
    va a una card que el usuario ve y probablemente copia.

    Si el scrubber no se puede cargar, el stderr se RECORTA A NADA en vez de publicarse en
    crudo: perder la traza es malo, filtrar una llave es peor.
    """
    fuera = dict(crudo or {})
    txt = str(fuera.get("stderr") or "")
    if not txt:
        return fuera
    try:
        import sys as _sys
        from pathlib import Path as _P
        _g = _P(__file__).resolve().parents[1] / "gates"
        if str(_g) not in _sys.path:
            _sys.path.insert(0, str(_g))
        from scrubber import OutputScrubber                # type: ignore
        # ⚠️ `.scrub()` devuelve un **`ScrubReport`**, no un string: el texto limpio está en
        # `.clean_text`. Guardar el objeto tal cual dejaba en `stderr` un
        # `ScrubReport(blocked=True, ...)` cuyo repr no contiene la llave — o sea que el test
        # «la traza no filtra una llave» pasaba **sin que nada se hubiera redactado**, y la
        # traza quedaba inservible además. Un verde falso en el test de una fuga es lo peor
        # que podía salir de acá.
        rep = OutputScrubber().scrub(txt)
        fuera["stderr"] = getattr(rep, "clean_text", str(rep))
        fuera["scrubber"] = ("ok · neutralizó " + str(len(getattr(rep, "findings", []))))
    except Exception:                                      # noqa: BLE001 — frontera
        fuera["stderr"] = ""
        fuera["scrubber"] = "no disponible: la traza se recortó en vez de publicarse cruda"
    return fuera


# ── 1 · LA PERILLA ──────────────────────────────────────────────────────────────────

#: Mismo patrón que `ALEPH_DUENO` y `ALEPH_TRANSPORTE`: se lee en UN solo lugar y en cada
#: llamada, para que un test que la mueva la vea y un rollback no exija reiniciar.
_ENV_PERILLA = "ALEPH_REPAIR"


def encendido() -> bool:
    """¿Repair decide algo? `off` por default: reparar es cambiar el mundo."""
    return (os.environ.get(_ENV_PERILLA) or "off").strip().lower() in ("on", "1", "true")


# ── 2 · LA CURVA (§3.1 del diseño — cada número con su medición) ────────────────────

#: 1 s contra un handshake medido de 274-819 ms (`DISEÑO-DUEÑO-v1.md:109`): el primer
#: reintento nunca pisa un arranque que todavía estaba en curso.
BASE_S = float(os.environ.get("ALEPH_REPAIR_BASE_S", "1"))
TOPE_S = float(os.environ.get("ALEPH_REPAIR_TOPE_S", "30"))
#: 25 % porque el cinturón se levanta EN PARALELO: sin jitter, seis piezas que caen juntas
#: por la misma red reintentan juntas para siempre.
JITTER = 0.25
MAX_INTENTOS = int(os.environ.get("ALEPH_REPAIR_MAX_INTENTOS", "5"))
#: 90 s contra `OCIOSIDAD_S = 600` (`dueno.py:78`): la ventana entera de repair cabe seis
#: veces dentro de la vida de una conexión ociosa. Repair no puede tardar más que lo que el
#: dueño tarda en tirar la conexión, o estaría reparando algo que ya no existe.
MAX_TOTAL_S = float(os.environ.get("ALEPH_REPAIR_MAX_TOTAL_S", "90"))

#: VENTANA del disparador R1 (§1.2): dos muertes de la misma clave dentro de esto son un
#: caso de repair. 120 s son ~150 handshakes: un margen donde «volvió a morir» significa que
#: vuelve a morir, no que el reloj era corto.
VENTANA_S = float(os.environ.get("ALEPH_REPAIR_VENTANA_S", "120"))

# ── 3 · EL BREAKER (§3.3) ───────────────────────────────────────────────────────────

CICLOS_PARA_ABRIR = 3
VENTANA_CICLOS_S = 600.0
BREAKER_ABIERTO_S = 300.0
MEDIO_ABIERTO_MAX = 3

#: ⚠️ EL BREAKER CORTO, que R2 dejó marcado con `sospecha_de_cuelgue`. Un server que VIVE y
#: no contesta no se destraba esperando: pagarle tres ciclos completos son 270 s de nada.
#: Una red que se cae, en cambio, vuelve — y por eso ésa sí se lleva la paciencia entera.
#: «Más corto» acá significa **rendirse antes**, no abrir por menos tiempo: lo que se ahorra
#: es el tiempo que el usuario pasa mirando un 🟡 que no va a cambiar.
CICLOS_PARA_ABRIR_CUELGUE = 2
MAX_INTENTOS_CUELGUE = 3

def _u(user_id) -> str:
    """Normaliza el usuario a la MISMA forma que `dueno.clave_de` (`user_id or '-'`).

    ⚠️ Sin esto, `None` y `"-"` son dos inquilinos distintos para el breaker aunque la clave
    del dueño los unifique: el guardia (que el dueño llama con el `user_id` crudo, a veces
    `None`) y cualquier otro llamante que use `"-"` abrirían y consultarían breakers
    DISTINTOS para la misma persona. Lo cazó la vara viva, donde el breaker existía y el
    pedido pasaba igual.
    """
    return user_id or "-"


CERRADO = "cerrado"
ABIERTO = "abierto"
MEDIO_ABIERTO = "medio_abierto"

# ── 4 · EL PERMISO (lo que el dueño recibe) ─────────────────────────────────────────

ADELANTE = "adelante"
ESPERAR = "esperar"
BLOQUEADO = "bloqueado"


@dataclass(frozen=True)
class Permiso:
    """La respuesta al dueño. **Congelado**: se lee, no se muta.

    ⚠️ `ESPERAR` **NO BLOQUEA AL LLAMANTE.** Es un «todavía no, volvé en N s», no un sleep
    dentro de `pedir()`. Dormir ahí tendría un hilo de request colgado hasta 30 s por un
    server roto, y con `MAX_TOTAL_S = 90` el peor caso es peor todavía. El agente recibe su
    `[MCP error: …]` —el mismo string que ya sabe leer— y sigue; el próximo mensaje encuentra
    la ventana abierta. Eso ES «se arregla callado»: nadie le contó nada a nadie.
    """

    decision: str                          # ADELANTE | ESPERAR | BLOQUEADO
    motivo: str = ""
    #: segundos que faltan, cuando `ESPERAR`. Para el mensaje, no para dormir.
    faltan_s: float = 0.0
    intento: int = 0

    @property
    def pasa(self) -> bool:
        return self.decision == ADELANTE


# ── 5 · EL ESTADO (memoria, §7.2) ───────────────────────────────────────────────────

@dataclass
class _Ciclo:
    """Los intentos de UNA conexión (clave = user_id|entity_id|huella)."""
    intentos: int = 0
    primer_intento_t: float = 0.0
    proximo_t: float = 0.0
    agotado: bool = False
    ultima_muerte_t: float = 0.0
    muertes: int = 0
    sospecha_de_cuelgue: bool = False
    causa: str = ""


@dataclass
class _Ajuste:
    """El auto-ajuste de versión de UNA (user_id, entity_id). **Un intento, sin loops.**

    Sin este registro, cada muerte volvería a disparar el ajuste: la primera lo pinea, la
    segunda propondría otro pin sobre el ya pineado (que `proponer` rechaza), y el ciclo
    quedaría girando sobre una decisión ya tomada. Una corrección automática que se repite
    deja de ser una corrección y pasa a ser un bucle con permisos de escritura.
    """
    intentado: bool = False
    aplicado: bool = False
    de: Optional[str] = None
    a: Optional[str] = None
    ts: float = 0.0
    motivo: str = ""


@dataclass
class _Breaker:
    """El breaker de UNA (user_id, entity_id). Nunca por entidad sola: eso dejaría que la
    llave vencida de un usuario le abra el breaker a todos los demás — la fuga del §2.1 con
    otra ropa."""
    estado: str = CERRADO
    ciclos_agotados: list = field(default_factory=list)   # timestamps
    abierto_hasta: float = 0.0
    #: ¿ya pasó el ÚNICO intento de prueba del medio-abierto? Sin esto, medio-abierto
    #: dejaría pasar todo y el breaker no volvería a cerrarse ni a escalar nunca.
    probe_usado: bool = False
    reaperturas: int = 0
    escalado: bool = False
    motivo: str = ""


class Repair:
    """La política. Sin hilos propios: el trabajo entra por `observar()` (que el dueño llama
    desde su entrega de eventos) y sale por `permitir()` (que el dueño consulta antes de
    spawnear). Un hilo más sería un reloj más que sincronizar, y no hace falta: no hay nada
    que hacer *entre* una muerte y el próximo pedido.

    `reloj` y `jitter` son inyectables **para que la vara mida hechos y no relojes**: con un
    reloj falso, los conteos de intentos y las aperturas del breaker son deterministas y no
    hay un solo `sleep` en los tests.
    """

    def __init__(self, *, reloj: Callable[[], float] = time.monotonic,
                 jitter: Optional[Callable[[float, float], float]] = None):
        self._reloj = reloj
        self._jitter = jitter if jitter is not None else random.uniform
        self._lock = threading.RLock()
        self._ciclos: dict = {}
        self._breakers: dict = {}
        self._ajustes: dict = {}
        #: Ganchos al registro, INYECTADOS. `platform/` no puede importar `product/backend`
        #: (misma frontera que el traductor), así que quien cablea pasa las dos funciones:
        #: `leer_fila(user_id, entity_id) -> fila | None` y
        #: `escribir_args(user_id, entity_id, args, nota) -> None`.
        #: Sin ganchos, el auto-ajuste simplemente no ocurre — y se REPORTA, no se traga.
        self._leer_fila = None
        self._escribir_args = None
        self._contadores = {
            "observadas": 0, "temporales": 0, "permanentes": 0, "no_fallos": 0,
            "intentos_permitidos": 0, "esperas": 0, "bloqueos": 0,
            "ciclos_agotados": 0, "breakers_abiertos": 0, "medio_abiertos": 0,
            "breakers_cerrados": 0, "escalados": 0,
            "ajustes_intentados": 0, "ajustes_aplicados": 0, "ajustes_sin_datos": 0,
        }
        self._escalaciones: list = []

    # ── 5.1 · OBSERVAR (entra el evento de R1) ──────────────────────────────────────
    def observar(self, evento: dict) -> Optional[RC.Veredicto]:
        """Consume un `MuerteMCP`. Devuelve el veredicto de R2, o `None` si no era un fallo.

        **No reintenta**: eso pasa cuando alguien vuelve a pedir, que es lo único que se puede
        hacer sin el `env`. Lo que SÍ hace acá es el auto-ajuste de versión (R5), que es la
        única reparación que no necesita al usuario porque no toca nada suyo.
        """
        ev = dict(evento or {})
        clave = ev.get("clave") or ""
        user_id, entity_id = ev.get("user_id"), ev.get("entity_id")

        with self._lock:
            self._contadores["observadas"] += 1
            v = RC.clasificar_muerte(ev)

            if v.señales.get("no_es_fallo"):
                # LÁPIDA / OCIOSIDAD / LRU / CIERRE: el dueño haciendo su trabajo o el
                # usuario decidiendo. Además LIMPIA: una entidad que el usuario desconectó no
                # puede quedar con un breaker abierto —ni con un ajuste pendiente— esperándola.
                self._contadores["no_fallos"] += 1
                if (ev.get("disparador") or "") == "LAPIDA":
                    self._cerrar_breaker(user_id, entity_id, motivo="lápida del usuario")
                    self._ajustes.pop((_u(user_id), entity_id), None)
                self._ciclos.pop(clave, None)
                return None

            if not v.es_temporal:
                # Un permanente no se reintenta ni una vez: reintentar un 401 sólo gasta.
                self._contadores["permanentes"] += 1
                self._ciclos.pop(clave, None)
            else:
                self._contadores["temporales"] += 1
                ahora = self._reloj()
                c = self._ciclos.get(clave)
                if c is None or (ahora - c.ultima_muerte_t) > VENTANA_S:
                    # Primera muerte, o una tan vieja que ya no cuenta: el contador se
                    # resetea y la muerte vuelve a ser GRATIS — el reconnect-once del dueño.
                    c = _Ciclo()
                    self._ciclos[clave] = c
                c.muertes += 1
                c.ultima_muerte_t = ahora
                c.causa = v.causa
                c.sospecha_de_cuelgue = bool(v.señales.get("sospecha_de_cuelgue"))
                return v

        # ── R5 · EL AUTO-AJUSTE VA FUERA DEL LOCK ────────────────────────────────────
        # Toca la DB, y hacerlo con el lock de la política tomado es la misma trampa que R1
        # pagó con la entrega de eventos.
        #
        # `servidor_incompatible` es lo ÚNICO que repair puede arreglar solo, porque la
        # receta es territorio de Aleph. Todo lo demás permanente es territorio del usuario
        # —una llave, un programa— y va al botón que ya existe.
        if v.causa == RC.SERVIDOR_INCOMPATIBLE and entity_id:
            parte = self.ajustar_version(user_id, entity_id, evidencia=ev)
            if not parte.get("ajustado"):
                # El ajuste no alcanzó (o ya se había intentado): recién AHORA es del humano.
                self._escalar_permanente(user_id, entity_id, v, ev,
                                         parte.get("motivo") or "")
        return v

    # ── 5.1b · EL AUTO-AJUSTE DE VERSIÓN (R5, sellado) ──────────────────────────────
    def poner_ganchos_de_receta(self, leer_fila, escribir_args) -> None:
        """Los dos accesos al registro que el auto-ajuste necesita. Inyectados: `platform/`
        no importa `product/backend`."""
        with self._lock:
            self._leer_fila, self._escribir_args = leer_fila, escribir_args

    def ajustar_version(self, user_id, entity_id: str, *,
                        evidencia: Optional[dict] = None) -> dict:
        """**LA RECETA ES TERRITORIO DE ALEPH.** Cuando un paquete publica una versión
        incompatible, repair vuelve solo a la última que anduvo. No hay botón ni
        confirmación: pedirle permiso al usuario para arreglar algo nuestro sería mandarle un
        trámite por un problema que no creó.

        **UN INTENTO, SIN LOOPS.** Si el ajuste no alcanza, la segunda vuelta NO propone otro
        pin a ciegas: escala (§5). Lo garantiza `_Ajuste.intentado`, que no se limpia con la
        muerte siguiente — sólo con un cambio de receta o con la lápida.

        Devuelve un parte SIEMPRE, incluso cuando no hace nada: un ajuste que no ocurrió y no
        se cuenta es indistinguible de uno que ocurrió y falló.
        """
        import repair_fijar_version as FV
        k = (_u(user_id), entity_id)
        with self._lock:
            a = self._ajustes.setdefault(k, _Ajuste())
            if a.intentado:
                return {"ajustado": False, "motivo": "ya se intentó una vez: no hay segundo "
                                                     "ajuste automático", "repetido": True}
            if self._leer_fila is None or self._escribir_args is None:
                self._contadores["ajustes_sin_datos"] += 1
                a.intentado, a.motivo = True, "sin ganchos al registro"
                return {"ajustado": False, "motivo": a.motivo}
            leer, escribir = self._leer_fila, self._escribir_args

        # FUERA DEL LOCK: tocar la DB con el lock del dueño-de-la-política tomado es la misma
        # trampa que R1 pagó con la entrega de eventos.
        parte = {"ajustado": False, "motivo": ""}
        try:
            fila = leer(user_id, entity_id) or {}
            version_buena = FV.version_de(fila.get("server_info"))
            prop = FV.proponer({"entity_id": entity_id,
                                "command": fila.get("command"),
                                "args": fila.get("args") or []},
                               version_buena=version_buena, evidencia=evidencia)
            parte["propuesta"] = prop.como_dict()
            if not prop.posible:
                parte["motivo"] = prop.motivo
            else:
                escribir(user_id, entity_id, list(prop.args_despues),
                         {"de": prop.version_corriendo, "a": prop.version_propuesta,
                          "ts": time.time()})
                parte.update(ajustado=True, motivo=prop.motivo,
                             de=prop.version_corriendo, a=prop.version_propuesta)
        except Exception as e:                             # noqa: BLE001 — frontera
            parte["motivo"] = f"el ajuste falló: {type(e).__name__}: {e}"

        with self._lock:
            a = self._ajustes.setdefault(k, _Ajuste())
            a.intentado = True
            a.aplicado = bool(parte.get("ajustado"))
            a.de, a.a = parte.get("de"), parte.get("a")
            a.ts, a.motivo = time.time(), parte.get("motivo") or ""
            self._contadores["ajustes_intentados"] += 1
            if a.aplicado:
                self._contadores["ajustes_aplicados"] += 1
                # La receta cambió ⇒ huella nueva ⇒ el ciclo y el breaker viejos quedan
                # inertes (§3.3(d)). Si no se limpian, el proceso nuevo nace bloqueado por el
                # estado del viejo: «se ajustó y sigue sin andar».
                self._cerrar_breaker(user_id, entity_id, motivo="receta ajustada")
            else:
                self._contadores["ajustes_sin_datos"] += 1
        return parte

    # ── 5.2 · PERMITIR (el dueño pregunta antes de spawnear) ────────────────────────
    def permitir(self, user_id: Optional[str], entity_id: str,
                 clave: str) -> Permiso:
        """¿Puede el dueño levantar esta conexión ahora?

        El orden importa: **el breaker manda sobre el ciclo**. Un breaker abierto corta aunque
        el ciclo tuviera intentos de sobra — para eso existe.
        """
        with self._lock:
            ahora = self._reloj()
            b = self._breakers.get((_u(user_id), entity_id))

            if b is not None and b.estado == ABIERTO:
                if ahora < b.abierto_hasta:
                    self._contadores["bloqueos"] += 1
                    return Permiso(BLOQUEADO,
                                   f"breaker abierto para «{entity_id}»: {b.motivo}",
                                   faltan_s=round(b.abierto_hasta - ahora, 3))
                # venció: UN intento de prueba
                b.estado = MEDIO_ABIERTO
                b.probe_usado = False
                self._contadores["medio_abiertos"] += 1

            if b is not None and b.estado == MEDIO_ABIERTO and not b.probe_usado:
                # ⚠️ **EL MEDIO-ABIERTO DEJA PASAR UNO. UNO.** La primera versión devolvía
                # ADELANTE mientras el breaker estuviera medio-abierto, sin consumir intento
                # — o sea que pasaban TODOS, para siempre: el ciclo no se agotaba nunca, el
                # breaker no volvía a abrir y la escalada era inalcanzable. Un breaker que en
                # medio-abierto deja pasar todo no es un breaker, es un breaker apagado. Lo
                # cazó `test_tres_medio_abiertos_en_ROJO_escalan`.
                b.probe_usado = True
                c0 = self._ciclos.get(clave)
                if c0 is not None:
                    c0.intentos += 1
                    if not c0.primer_intento_t:
                        c0.primer_intento_t = ahora
                self._contadores["intentos_permitidos"] += 1
                return Permiso(ADELANTE, "breaker medio-abierto: un intento de prueba",
                               intento=(c0.intentos if c0 else 1))

            c = self._ciclos.get(clave)
            if c is None or c.muertes == 0:
                self._contadores["intentos_permitidos"] += 1
                return Permiso(ADELANTE, "sin ciclo de repair abierto")

            tope_intentos = MAX_INTENTOS_CUELGUE if c.sospecha_de_cuelgue else MAX_INTENTOS
            if c.agotado:
                self._contadores["bloqueos"] += 1
                return Permiso(BLOQUEADO, f"ciclo agotado para «{entity_id}»")

            if c.intentos >= tope_intentos:
                return self._agotar(user_id, entity_id, c,
                                    f"{c.intentos} intentos sin verde")
            if c.primer_intento_t and (ahora - c.primer_intento_t) >= MAX_TOTAL_S:
                return self._agotar(user_id, entity_id, c,
                                    f"{MAX_TOTAL_S:.0f}s de reintentos sin verde")

            if c.proximo_t and ahora < c.proximo_t:
                self._contadores["esperas"] += 1
                return Permiso(ESPERAR, "backoff en curso",
                               faltan_s=round(c.proximo_t - ahora, 3),
                               intento=c.intentos + 1)

            # ADELANTE: se consume un intento y se programa el siguiente hueco.
            c.intentos += 1
            if not c.primer_intento_t:
                c.primer_intento_t = ahora
            c.proximo_t = ahora + self.espera(c.intentos)
            self._contadores["intentos_permitidos"] += 1
            return Permiso(ADELANTE, f"intento {c.intentos}/{tope_intentos}",
                           intento=c.intentos)

    def espera(self, intento: int) -> float:
        """`min(BASE * 2**(n-1), TOPE)` con jitter de ±25 %. Nunca negativa."""
        crudo = min(BASE_S * (2 ** max(0, intento - 1)), TOPE_S)
        return max(0.0, crudo * (1.0 + self._jitter(-JITTER, JITTER)))

    # ── 5.3 · EL BREAKER ────────────────────────────────────────────────────────────
    def _agotar(self, user_id, entity_id, c: _Ciclo, motivo: str) -> Permiso:
        """Un ciclo se agotó. Puede abrir el breaker; si el breaker ya se reabrió demasiado,
        ESCALA (§5) y queda abierto hasta que haya acción humana."""
        ahora = self._reloj()
        c.agotado = True
        self._contadores["ciclos_agotados"] += 1
        b = self._breakers.setdefault((_u(user_id), entity_id), _Breaker())
        b.ciclos_agotados = [t for t in b.ciclos_agotados
                             if (ahora - t) <= VENTANA_CICLOS_S] + [ahora]

        if b.estado == MEDIO_ABIERTO:
            b.reaperturas += 1
            if b.reaperturas >= MEDIO_ABIERTO_MAX:
                b.estado, b.escalado = ABIERTO, True
                b.abierto_hasta = float("inf")
                b.motivo = f"{motivo} · {b.reaperturas} medio-abiertos en rojo"
                self._escalar(user_id, entity_id, b.motivo, c)
                self._contadores["bloqueos"] += 1
                return Permiso(BLOQUEADO, b.motivo)
            b.estado, b.abierto_hasta = ABIERTO, ahora + BREAKER_ABIERTO_S
            b.motivo = motivo
            self._contadores["breakers_abiertos"] += 1
            self._contadores["bloqueos"] += 1
            return Permiso(BLOQUEADO, f"breaker reabierto: {motivo}")

        tope_ciclos = (CICLOS_PARA_ABRIR_CUELGUE if c.sospecha_de_cuelgue
                       else CICLOS_PARA_ABRIR)
        if len(b.ciclos_agotados) >= tope_ciclos:
            b.estado, b.abierto_hasta = ABIERTO, ahora + BREAKER_ABIERTO_S
            b.motivo = (f"{len(b.ciclos_agotados)} ciclos agotados"
                        + (" (server colgado)" if c.sospecha_de_cuelgue else ""))
            self._contadores["breakers_abiertos"] += 1
            self._contadores["bloqueos"] += 1
            return Permiso(BLOQUEADO, f"breaker abierto: {b.motivo}")

        self._contadores["bloqueos"] += 1
        return Permiso(BLOQUEADO, f"ciclo agotado: {motivo}")

    def cerrar_breaker(self, user_id: Optional[str], entity_id: str, *,
                       motivo: str = "") -> bool:
        """Lo llama el botón del usuario, la lápida, o un cambio de huella (§3.3)."""
        with self._lock:
            return self._cerrar_breaker(user_id, entity_id, motivo=motivo)

    def _cerrar_breaker(self, user_id, entity_id, *, motivo: str) -> bool:
        b = self._breakers.pop((_u(user_id), entity_id), None)
        # y también el ciclo, o el próximo pedido chocaría con un ciclo agotado viejo
        for k in [k for k, c in self._ciclos.items()
                  if k.split("|")[1:2] == [entity_id]
                  and k.split("|")[0] == _u(user_id)]:
            self._ciclos.pop(k, None)
        if b is not None:
            self._contadores["breakers_cerrados"] += 1
            return True
        return False

    def olvidar_huella(self, clave: str) -> None:
        """§3.3(d) · una receta nueva ⇒ huella nueva ⇒ ciclo nuevo. Un breaker sobre la
        huella vieja no puede bloquear la nueva, o «arreglé la llave y sigue sin andar»."""
        with self._lock:
            self._ciclos.pop(clave, None)

    # ── 5.4 · LA ESCALADA (§5) — con la traza de QUÉ SE INTENTÓ ─────────────────────
    def _escalar(self, user_id, entity_id, motivo: str, c: _Ciclo) -> None:
        """Escalada de un TEMPORAL que agotó todo (§5.1 a/b)."""
        self._anotar_escalacion({
            "user_id": _u(user_id), "entity_id": entity_id, "motivo": motivo,
            "causa": c.causa, "clase": RC.TEMPORAL, "boton": None,
            "por_que_empezo": f"{c.muertes} muerte(s) de la misma conexión",
            "intentos": c.intentos, "por_que_paro": motivo,
            "sospecha_de_cuelgue": c.sospecha_de_cuelgue,
            "t": self._reloj(), "ts": time.time(),
        })

    def _escalar_permanente(self, user_id, entity_id, v, ev: dict, motivo: str) -> None:
        """La escalada de un PERMANENTE sin botón, o cuyo auto-ajuste no alcanzó (§5.1 c).

        Lleva la traza completa del §5.3 —por qué empezó, qué se intentó, por qué paró, y lo
        crudo— **pasada por el scrubber**: el stderr puede traer una llave si el server la
        imprime, y esta traza va a una card que el usuario ve y probablemente copia.
        """
        with self._lock:
            a = self._ajustes.get((_u(user_id), entity_id))
            self._anotar_escalacion({
                "user_id": _u(user_id), "entity_id": entity_id, "motivo": motivo,
                "causa": v.causa, "clase": RC.PERMANENTE, "boton": v.boton,
                "por_que_empezo": v.razon,
                "intentos": 0,
                "por_que_paro": motivo or "permanente sin acción automática posible",
                "ajuste_automatico": ({"intentado": a.intentado, "aplicado": a.aplicado,
                                       "de": a.de, "a": a.a, "motivo": a.motivo}
                                      if a is not None else None),
                "crudo": _limpiar_traza({
                    "stderr": ev.get("stderr") or "",
                    "exit_code": ev.get("exit_code"),
                    "exit_code_fuente": ev.get("exit_code_fuente"),
                    "murio_por_eof": ev.get("murio_por_eof"),
                    "vivio_s": ev.get("vivio_s"),
                    "timeouts": ev.get("timeouts") or [],
                    "rpc_timeout_s": ev.get("rpc_timeout_s"),
                }),
                "t": self._reloj(), "ts": time.time(),
            })

    def _anotar_escalacion(self, esc: dict) -> None:
        """UNA escalada por (usuario, entidad): la card muestra una, no una pila. La última
        gana, porque es la que describe el estado de ahora."""
        self._contadores["escalados"] += 1
        k = (esc["user_id"], esc["entity_id"])
        self._escalaciones = [e for e in self._escalaciones
                              if (e.get("user_id"), e.get("entity_id")) != k]
        self._escalaciones.append(esc)

    def escalacion_de(self, user_id, entity_id: str):
        """La escalada vigente de una entidad, para que la card la muestre."""
        with self._lock:
            for e in reversed(self._escalaciones):
                if e.get("user_id") == _u(user_id) and e.get("entity_id") == entity_id:
                    return dict(e)
        return None

    def nota_de_ajuste(self, user_id, entity_id: str):
        """Lo que va en el [?]: «se ajustó automáticamente el <fecha>». `None` si no se ajustó
        nada — el usuario no tiene por qué enterarse de lo que no pasó."""
        with self._lock:
            a = self._ajustes.get((_u(user_id), entity_id))
            if a is None or not a.aplicado:
                return None
            return {"de": a.de, "a": a.a, "ts": a.ts, "motivo": a.motivo}

    # ── 5.5 · ESTADO (hechos deterministas, para la vara) ───────────────────────────
    def estado(self) -> dict:
        with self._lock:
            return {
                "eventos": dict(self._contadores),
                "ciclos": {k: {"intentos": c.intentos, "muertes": c.muertes,
                               "agotado": c.agotado, "causa": c.causa,
                               "sospecha_de_cuelgue": c.sospecha_de_cuelgue}
                           for k, c in self._ciclos.items()},
                "breakers": {f"{u}|{e}": {"estado": b.estado,
                                                 "reaperturas": b.reaperturas,
                                                 "escalado": b.escalado,
                                                 "motivo": b.motivo}
                             for (u, e), b in self._breakers.items()},
                "escalaciones": list(self._escalaciones),
                "ajustes": {f"{u}|{e}": {"intentado": a.intentado, "aplicado": a.aplicado,
                                         "de": a.de, "a": a.a, "motivo": a.motivo}
                            for (u, e), a in self._ajustes.items()},
            }


# ── 6 · EL SINGLETON Y EL CABLEADO ──────────────────────────────────────────────────

_actual: Optional[Repair] = None
_lock_actual = threading.Lock()


def actual() -> Repair:
    global _actual
    with _lock_actual:
        if _actual is None:
            _actual = Repair()
        return _actual


def _reset_para_tests(**kw) -> Repair:
    global _actual
    with _lock_actual:
        _actual = Repair(**kw)
        return _actual


def cablear(dueno_mod) -> bool:
    """Engancha repair al dueño: suscriptor (R1) + guardia (R3).

    Devuelve `False` sin hacer nada si la perilla está apagada o si el dueño no tiene los
    hooks — que es el caso de un árbol viejo, y es un no-op, no un error.
    """
    if not encendido():
        return False
    r = actual()
    if not (hasattr(dueno_mod, "actual") and hasattr(dueno_mod.Dueno, "suscribir")
            and hasattr(dueno_mod.Dueno, "poner_guardia")):
        return False
    d = dueno_mod.actual()
    d.suscribir(r.observar)
    d.poner_guardia(r.permitir)
    _poner_ganchos_de_receta(r)
    return True


def _poner_ganchos_de_receta(r: "Repair") -> bool:
    """Le da a repair los dos accesos al registro que el auto-ajuste necesita.

    Se arma acá y no dentro de `repair.py` porque `platform/` no importa `product/backend`
    (misma frontera que el traductor). Si el backend no está —una vara de plataforma, un
    árbol parcial— el auto-ajuste simplemente no ocurre y se REPORTA en
    `estado()['eventos']['ajustes_sin_datos']`. Nunca revienta el cableado por esto.
    """
    try:
        from app.phase1 import conexiones_repo as CR
        from app.phase1 import repo as REPO
    except Exception:                                      # noqa: BLE001
        return False

    def _leer(user_id, entity_id):
        conn = REPO.get_conn()
        try:
            for e in CR.listar_entidades(conn, user_id):
                if e.get("entity_id") == entity_id:
                    return e
        finally:
            conn.close()
        return None

    def _escribir(user_id, entity_id, args, nota):
        conn = REPO.get_conn()
        try:
            # UPDATE, JAMÁS UPSERT: la fila existe (repair sólo actúa sobre algo que estuvo
            # conectado) y `upsert_entidad` sólo pisa los campos que se le pasan.
            fila = None
            for e in CR.listar_entidades(conn, user_id):
                if e.get("entity_id") == entity_id:
                    fila = e
                    break
            if fila is None:
                raise RuntimeError(f"«{entity_id}» no está en el registro de ese usuario")
            campos = {"args": list(args)}
            # LA NOTA DEL [?] va DENTRO del veredicto de conexión, que es lo que la card ya
            # lee. Es aditiva: no pisa el veredicto, le agrega de dónde salió el ajuste.
            con = dict(fila.get("conexion") or {})
            con["ajuste_automatico"] = dict(nota)
            campos["conexion"] = con
            CR.upsert_entidad(conn, user_id=user_id, entity_id=entity_id, commit=True,
                              **campos)
        finally:
            conn.close()

    r.poner_ganchos_de_receta(_leer, _escribir)
    return True


__all__ = ["Repair", "Permiso", "ADELANTE", "ESPERAR", "BLOQUEADO", "CERRADO", "ABIERTO",
           "MEDIO_ABIERTO", "actual", "cablear", "encendido", "BASE_S", "TOPE_S", "JITTER",
           "MAX_INTENTOS", "MAX_TOTAL_S", "VENTANA_S", "CICLOS_PARA_ABRIR",
           "CICLOS_PARA_ABRIR_CUELGUE", "MAX_INTENTOS_CUELGUE", "BREAKER_ABIERTO_S"]
