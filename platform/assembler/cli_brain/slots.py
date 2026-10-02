#!/usr/bin/env python3
"""slots.py — EL TECHO DE TURNOS SIMULTÁNEOS DEL BYO-CLI (Gate 2 · F2b).

EL AGUJERO QUE CIERRA (auditoría 2 §P1.f, medido): el server `:8926` es un
`ThreadingHTTPServer` sin ningún límite. Dos agentes que piden a la vez spawnean **dos
procesos `claude -p` simultáneos**, cada uno con hasta 180 s de vida, contra la MISMA
suscripción del usuario. Nadie los cuenta y nadie los frena.

TRES CAPAS, no una — el patrón es el `SlotPool` + `inFlight` de emdash
(`apps/emdash-desktop/src/main/core/automations/automation-scheduler.ts`:20-49 y 247-255,
Apache-2.0 © 2026 General Action, Inc.), reescrito acá con nuestro vocabulario:

  1. TECHO GLOBAL — `MAX_TURNOS`. Cuántos turnos de cognición pueden estar en vuelo a la
     vez, sumando todos los providers.
  2. TECHO POR PROVIDER — cuántos turnos del MISMO CLI pueden solaparse. Es **uno** salvo
     que la tabla `_MAX_POR_PROVIDER` diga otra cosa, y un slot global libre no vuelve
     legítimo pedirle N cosas a la vez a la misma cuenta: el número se sube midiendo, por
     provider, con su motivo escrito (ver el bloque de esa tabla).
  3. PAUSA LOCAL — cuando el CLI informa un rate-limit con reset, Aleph deja de lanzar
     turnos de ESE provider hasta el retry indicado. Es evidencia histórica del evento,
     no una consulta de cuota viva; un éxito real posterior la invalida de inmediato.

EL N+1 NO ESPERA MUDO NI REVIENTA. Se le contesta con una causa TIPADA del vocabulario
cerrado, igual que a cualquier otro fallo. `en_pausa` conserva `rate_limit` como causa,
pero `origen: "aleph"` identifica que este rechazo es local; el evento original lleva
`origin: "provider"` por separado. Autenticación, pausa y cuota no se confunden.

    HUECO CERRADO EN F1c. Era: «falta una causa `cli_ocupado` para "tu CLI está atendiendo
    otro turno"; hoy usa `rate_limit` con `origen: "aleph"`, que es honesto en el "hay que
    esperar" pero no distingue nuestro techo de la ventana del proveedor sin mirar la
    evidencia». Desde F1c, `sin_slots` y `provider_ocupado` salen `cli_ocupado`; `en_pausa`
    sigue siendo `rate_limit` porque se deriva de un evento previo del proveedor, aunque no
    confirma su estado actual (ver `causa_de`).

PERILLA: `PUPPET_CLI_PAUSA=0` apaga la capa 3 (la pausa), por si el reset que informa el
CLI viniera mentiroso. Las capas 1 y 2 no se apagan: son el techo de procesos.

Puro salvo el reloj: sin red, sin disco, sin subprocess.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Optional

# ── EL TECHO ──────────────────────────────────────────────────────────────────────
# DOS. No es un número tímido: cada turno es un proceso Node ENTERO (`claude -p` levanta
# el CLI completo, no un cliente HTTP) que vive hasta 180 s, carga el prompt más el
# historial, y se atribuye a la MISMA suscripción del usuario. Tres turnos en paralelo no
# triplican la velocidad: triplican la memoria y queman la ventana tres veces más rápido.
# emdash usa 4 para corridas que además se llevan un worktree y un PTY; acá el trabajo es
# más chico y la cuenta es una sola, así que 2. Se cambia con PUPPET_CLI_SLOTS.
MAX_TURNOS = int(os.environ.get("PUPPET_CLI_SLOTS", "2"))

# ── EL TECHO POR PROVIDER ─────────────────────────────────────────────────────────
# [2026-08-14 · Ciencia obra 1] La capa 2 era `pid in set`, o sea un techo implícito de
# UNO que no se podía mover porque no era un número. Ahora es un número por provider, y
# el default sigue siendo UNO: para todo el que no esté en la tabla, el comportamiento es
# byte por byte el de antes.
#
# POR QUÉ SE MUEVE, Y SÓLO PARA CODEX. Medido en un turno normal de Ciencia (`msg.created
# → completed`, 6,41 s), las llamadas al cerebro salen así:
#
#     llamada 1: t+0,01 → t+2,76
#     llamada 2: t+2,77 → t+4,40   ◀─┐ arrancan en el MISMO instante: el turno se pisa
#     llamada 3: t+2,77 → t+6,40   ◀─┘ a sí mismo, sin que haya nadie más usando la app
#
# La 3 rebotaba con `provider_ocupado` (evidencia medida: `activos:1, limite:2` — o sea el
# techo GLOBAL tenía lugar de sobra y lo que frenó fue la capa 2), y de ahí el cascade la
# mandaba a la red OSS-directo: un `qwen3:8b` local contestando el turno de alguien que
# eligió Codex. El pico REAL de este turno es 2, no 3.
#
# LA SERIALIZACIÓN DE CLAUDE NO SE TOCA, y no es simetría mal hecha: `verify_cli_slots.py`
# §6 certifica con evidencia de `ps` —41 muestras, pico 1— que JAMÁS hay dos `claude -p`
# vivos. Ese invariante tiene vara propia y se queda como está.
#
# Y EL TECHO GLOBAL SIGUE EN 2, así que la concurrencia EFECTIVA de Codex es 2, no 3: el
# 3 es margen para que el turno normal no viva pegado al borde. Subir de verdad a tres
# turnos simultáneos exige mover también `PUPPET_CLI_SLOTS`, que es un acto aparte y con
# su propio costo (el de arriba: memoria y ventana de la MISMA suscripción).
#
# ESTO NO REEMPLAZA LA COLA. Con dos workspaces activos se vuelve al mismo lugar: lo que
# cierra el agujero es que `cli_ocupado` ESPERE en vez de escalar (obra 2). Esto es lo que
# hace que el turno normal, solo en la casa, deje de rebotar contra sí mismo.
_MAX_POR_PROVIDER_DEFECTO = int(os.environ.get("PUPPET_CLI_SLOTS_PROVIDER", "1"))

# ── EL CARRIL AUXILIAR (paso 5 · menos hops) ──────────────────────────────────────
# Un turno SIN CATÁLOGO no compite por el slot del que sí lo tiene.
#
# QUÉ MIDIÓ ESTO, turno por turno y desde la pantalla: los stacks piden su hop de OFICIO
# y sus hops AUXILIARES **a la vez**, y con el techo por provider en 1 el auxiliar se
# lleva el único slot y el oficio espera detrás de un TÍTULO:
#
#     Ciencia   3 hops pedidos en 30 ms · 2 son auxiliares · el oficio esperó 5,69-8,14 s
#     Oficina   el TÍTULO pidió primero · el oficio esperó 2,67 s
#     Diseño    2 auxiliares (preferencias + título) · el oficio esperó 2,73 s
#     Finanzas  el título va DESPUÉS del oficio · esperó 0,00 s
#     La Sala   sin auxiliares · 0,00 s
#
# POR QUÉ ES SEGURO, y es la misma regla que `llamada_repetida` ya declaró para el eco:
# **una llamada sin catálogo es una transformación de texto pura — no tiene efectos.**
# No puede pedir una tool, no puede tocar el disco, no puede cambiar lo que el stack
# entrega. Lo único que cambia es que deja de bloquear al turno de verdad.
#
# ⚠️ LO QUE SÍ CUESTA, dicho con el número: **una llamada corta más en vuelo contra la
# misma cuenta**. Medidas, las auxiliares duran 2,6-5,1 s. Por eso el carril es de UNO por
# provider y no de N: el techo del oficio no se toca, y el auxiliar no puede acumularse.
# Si el dueño prefiere el comportamiento de antes, `PUPPET_CLI_SLOTS_AUX=0` lo apaga y
# todo vuelve a un solo carril.
def _techo_aux() -> int:
    """El techo del carril, leído con la regla de la casa: **ausente ⇒ el default;
    presente-y-vacío ⇒ APAGADO**.

    ⚠️ `int(os.environ.get(VAR, "1"))` a secas NO servía, y lo cazó un mutante: con la
    variable en `""` —que es como se apaga algo desde un `.plist` o un script— revienta con
    `ValueError` en el import en vez de apagarse. Y con `or` habría caído otra vez en el
    default, que es el bug que esta casa ya pagó en otra obra. Un valor basura tampoco
    tumba el arranque: se avisa y se usa el default.
    """
    crudo = os.environ.get("PUPPET_CLI_SLOTS_AUX", "1").strip()
    if crudo == "":
        return 0                                   # explícitamente vacío = apagado
    try:
        return max(0, int(crudo))
    except ValueError:
        print(f"[slots] PUPPET_CLI_SLOTS_AUX={crudo!r} no es un número; uso 1",
              file=sys.stderr, flush=True)
        return 1


_MAX_AUX_POR_PROVIDER = _techo_aux()


def techo_de(provider_id: str) -> int:
    """Cuántos turnos simultáneos admite ESE provider. Uno, salvo que el registro diga otra."""
    try:
        from .registry import techo_de as _reg_techo
        return _reg_techo(provider_id, default=_MAX_POR_PROVIDER_DEFECTO)
    except Exception:
        return max(1, _MAX_POR_PROVIDER_DEFECTO)


# ── LA ESPERA ─────────────────────────────────────────────────────────────────────
# [2026-08-14 · Ciencia obra 2] EL CEREBRO NO ESTÁ CAÍDO: ESTÁ OCUPADO, Y SE LIBERA SOLO.
#
# Hasta acá el N+1 se rechazaba en el acto, y aguas arriba `cli_ocupado` estaba en
# `errores_modelo._ESCALABLES`, así que el cascade lo mandaba al tier siguiente. Medido en
# Ciencia: el turno del usuario terminaba contestado por un `qwen3:8b` local —o muriendo con
# `HTTP 408: Ollama` a los 64,3 s— porque su Codex estaba atendiendo OTRA llamada DEL MISMO
# TURNO. Escalar ahí no arregla nada: el recurso no falló, estaba en uso, y dos segundos
# después estaba libre.
#
# EL PATRÓN ES EL DE `cola_local.ColaLocal.pedir` —la cola de Ollama, F5— y no es
# casualidad: es el mismo problema (un techo propio, un N+1, una espera acotada) y la casa
# ya lo resolvió una vez. Lo que se copia es la forma, incluido el default:
#
#     ESPERA_S = 0  →  NO se espera. El comportamiento de todo llamador que no pida otra
#                      cosa queda byte por byte el de F2b, y las varas de unidad tampoco
#                      cambian de semántica por un default nuevo.
#
# Quien SÍ espera es el camino de producción (`server.py`, al pedir el turno), con
# `ESPERA_TURNO_S`. Que la política viva acá y la decisión de usarla en el call site es lo
# que hace que una vara pueda medir las dos cosas sin variables de entorno.
#
# EL NÚMERO SALE DE MEDIR, no de la intuición. Las llamadas que se pisan dentro de UN turno
# de Ciencia duraron 2,10 · 2,03 · 2,19 · 3,66 · 3,91 · 10,12 s (dos turnos, binario
# `363d7ceb…`). 20 s cubre todas con margen, y el costo de equivocarse por exceso es
# esperar; el de equivocarse por defecto era contestar con otro modelo.
ESPERA_S = float(os.environ.get("PUPPET_CLI_ESPERA", "0"))

#: Lo que espera un turno DE PRODUCCIÓN por su lugar. Ver arriba de dónde sale el 20.
ESPERA_TURNO_S = float(os.environ.get("PUPPET_CLI_ESPERA_TURNO", "20"))


#: Motivos de rechazo. Vocabulario cerrado propio, que se traduce a causa + detalle.
SIN_SLOTS = "sin_slots"                  # el techo global está lleno
PROVIDER_OCUPADO = "provider_ocupado"    # ese CLI ya está atendiendo un turno
EN_PAUSA = "en_pausa"                    # Aleph respeta un cooldown local previo
MOTIVOS = frozenset({SIN_SLOTS, PROVIDER_OCUPADO, EN_PAUSA})


def _pausa_activa() -> bool:
    """La capa 3 se puede apagar. Las otras dos no."""
    return os.environ.get("PUPPET_CLI_PAUSA", "1").strip().lower() not in ("0", "false", "no")


class SinSlot(RuntimeError):
    """No hay turno disponible. Lleva el motivo y, si se sabe, cuándo reintentar."""

    def __init__(self, motivo: str, *, provider: str = "", restante_s: Optional[float] = None,
                 activos: int = 0, limite: int = 0, hasta: Optional[float] = None,
                 evento_previo: Optional[dict] = None):
        self.motivo = motivo
        self.provider = provider
        self.restante_s = restante_s
        self.activos = activos
        self.limite = limite
        self.hasta = hasta
        self.evento_previo = dict(evento_previo) if isinstance(evento_previo, dict) else None
        super().__init__(f"{motivo} (provider={provider}, activos={activos}/{limite})")


class Slots:
    """El contador. Una instancia por proceso; el server usa la global de abajo."""

    def __init__(self, limite: int = MAX_TURNOS):
        self._lock = threading.Lock()
        #: El que espera duerme acá y lo despierta `soltar()`. Es una Condition sobre el
        #: MISMO lock, no un segundo candado: el estado que se consulta al despertar es el
        #: que el lock ya protege.
        self._libre = threading.Condition(self._lock)
        self._limite = max(1, int(limite))
        self._activos = 0
        self._en_vuelo: dict[str, int] = {}       # provider_id → turnos suyos corriendo
        #: EL CARRIL AUXILIAR, aparte y con su propio contador: los turnos SIN catálogo no
        #: entran en `_activos` ni en `_en_vuelo` porque no compiten por ese techo.
        self._aux_en_vuelo: dict[str, int] = {}
        self._pausa: dict[str, tuple[float, str]] = {}   # provider_id → (hasta_epoch, motivo)
        self._secuencia_estado = 0
        self._pausa_secuencia: dict[str, int] = {}
        self._pausa_evento: dict[str, dict] = {}
        self._limite_proveedor: dict[str, dict] = {}
        self._ultima_ejecucion: dict[str, dict] = {}
        self.rechazos: dict[str, int] = {}        # forense: cuántos rechazó cada motivo

    # ── pedir / soltar ────────────────────────────────────────────────────────────
    def pedir(self, provider_id: str, *, espera_s: Optional[float] = None,
              ahora: Optional[float] = None, auxiliar: bool = False) -> None:
        """Reserva un turno o levanta `SinSlot`. El orden importa: primero la pausa (que
        es del proveedor y dura), después el provider (que es inmediato), y al final el
        techo global — así el motivo que se le informa al llamante es el más específico.

        [obra 2] Con `espera_s > 0` el N+1 HACE COLA en vez de rebotar, y sólo se lo rechaza
        si el tope se cumple. La espera es ACOTADA a propósito: el punto es no rebotar por
        dos segundos de solape, no convertir esto en otro lugar donde colgarse.

        **La pausa NO se espera.** `en_pausa` significa que Aleph aún respeta un cooldown
        derivado de un rate-limit anterior; no prueba que el proveedor siga limitado ahora.
        Se espera lo que se libera solo —el techo propio y el del provider—, no el reloj del
        cooldown local.
        """
        t = time.time() if ahora is None else ahora
        pid = str(provider_id or "?")
        # EL CARRIL AUXILIAR. `auxiliar=True` sólo lo pone el llamante cuando el turno cruza
        # SIN catálogo. Con el carril en 0 la perilla lo apaga y todo vuelve a un solo carril.
        aux = bool(auxiliar) and _MAX_AUX_POR_PROVIDER > 0
        # Con reloj inyectado no se espera: una espera contra un reloj congelado no mide
        # nada y volvería no-determinista a la vara que lo inyectó justamente para fijarlo.
        tope = 0.0 if ahora is not None else (ESPERA_S if espera_s is None else float(espera_s))
        vence = time.monotonic() + max(0.0, tope)
        with self._libre:
            while True:
                hasta = self._pausa_vigente(pid, t)
                if hasta is not None:
                    self._contar(EN_PAUSA)
                    raise SinSlot(EN_PAUSA, provider=pid, restante_s=max(0.0, hasta - t),
                                  hasta=hasta, activos=self._activos, limite=self._limite,
                                  evento_previo=self._pausa_evento.get(pid))
                if aux:
                    # El auxiliar NO mira el techo del oficio ni el global: tiene el suyo.
                    # Así un título no puede quedarse con el único slot del turno de verdad.
                    techo_pid = _MAX_AUX_POR_PROVIDER
                    hay_provider = self._aux_en_vuelo.get(pid, 0) < techo_pid
                    if hay_provider:
                        self._aux_en_vuelo[pid] = self._aux_en_vuelo.get(pid, 0) + 1
                        return
                    hay_global = True
                else:
                    techo_pid = techo_de(pid)
                    hay_provider = self._en_vuelo.get(pid, 0) < techo_pid
                    hay_global = self._activos < self._limite
                    if hay_provider and hay_global:
                        self._activos += 1
                        self._en_vuelo[pid] = self._en_vuelo.get(pid, 0) + 1
                        return
                restante = vence - time.monotonic()
                if restante <= 0:
                    # Se agotó la espera (o no la había): el rechazo es EL DE SIEMPRE, con
                    # su motivo y sus números. Esperar cambia cuándo se rechaza, no cómo.
                    if not hay_provider:
                        self._contar(PROVIDER_OCUPADO)
                        # Los números que viajan son los DE ESTE PROVIDER, no los globales:
                        # un rechazo que dice «1/2» cuando lo que se llenó fue el techo del
                        # provider manda a leer el número equivocado. Es el mismo defecto
                        # que el módulo ya evita al separar quién frenó de por qué.
                        raise SinSlot(PROVIDER_OCUPADO, provider=pid,
                                      activos=self._en_vuelo.get(pid, 0), limite=techo_pid)
                    self._contar(SIN_SLOTS)
                    raise SinSlot(SIN_SLOTS, provider=pid,
                                  activos=self._activos, limite=self._limite)
                # A dormir hasta que alguien suelte, o hasta que se acabe el tope. El `while`
                # vuelve a mirar el estado al despertar: entre el notify y el lock puede
                # haberse metido otro, y creerle al despertar sería pasarse el techo.
                self._libre.wait(restante)

    def soltar(self, provider_id: str, *, auxiliar: bool = False) -> None:
        pid = str(provider_id or "?")
        if bool(auxiliar) and _MAX_AUX_POR_PROVIDER > 0:
            with self._libre:
                n = self._aux_en_vuelo.get(pid, 0)
                if n > 0:
                    if n == 1:
                        self._aux_en_vuelo.pop(pid, None)
                    else:
                        self._aux_en_vuelo[pid] = n - 1
                self._libre.notify_all()
            return
        with self._libre:
            n = self._en_vuelo.get(pid, 0)
            if n > 0:
                if n == 1:
                    # Se BORRA la clave en vez de dejarla en cero: `en_vuelo` de `estado()`
                    # son los providers que están corriendo algo, y un cero colgado los
                    # haría figurar como ocupados para siempre.
                    self._en_vuelo.pop(pid, None)
                else:
                    self._en_vuelo[pid] = n - 1
                self._activos = max(0, self._activos - 1)
            # SIEMPRE se avisa, incluso si no había nada que soltar: un `notify_all` de más
            # sólo cuesta que los que esperan vuelvan a mirar el estado (y el `while` de
            # `pedir` está escrito para eso). Uno de menos deja a alguien durmiendo hasta
            # que se le cumpla el tope, con el slot libre al lado.
            self._libre.notify_all()

    def turno(self, provider_id: str, *, espera_s: Optional[float] = None):
        """Context manager: `with SLOTS.turno(pid): ...`. Suelta pase lo que pase."""
        slots = self

        class _Turno:
            def __enter__(self_inner):
                slots.pedir(provider_id, espera_s=espera_s)
                return self_inner

            def __exit__(self_inner, *exc):
                slots.soltar(provider_id)
                return False

        return _Turno()

    # ── pausa ─────────────────────────────────────────────────────────────────────
    def pausar(self, provider_id: str, hasta_epoch: float, *, motivo: str = "rate_limit",
               ahora: Optional[float] = None) -> bool:
        """La ventana de ese CLI se agotó hasta `hasta_epoch`. Devuelve si quedó puesta.

        Un reset en el pasado, en cero o absurdamente lejano NO se acepta: el CLI podría
        informar cualquier cosa y una pausa de tres días sería peor que el problema.
        """
        if not _pausa_activa():
            return False
        t = time.time() if ahora is None else ahora
        try:
            hasta = float(hasta_epoch)
        except (TypeError, ValueError):
            return False
        if hasta <= t:
            return False                      # ya pasó: no hay nada que pausar
        if hasta - t > 24 * 3600:
            return False                      # más de 24 h: el CLI está diciendo cualquier cosa
        with self._libre:
            vigente = self._pausa.get(provider_id)
            if vigente and vigente[0] >= hasta:
                return True                   # ya había una pausa igual o más larga
            pid = str(provider_id or "?")
            self._secuencia_estado += 1
            self._pausa[pid] = (hasta, motivo)
            self._pausa_secuencia[pid] = self._secuencia_estado
            self._pausa_evento.pop(pid, None)
            self._libre.notify_all()
        return True

    def pausar_segundos(self, provider_id: str, segundos: Optional[float], *,
                        motivo: str = "rate_limit", ahora: Optional[float] = None) -> bool:
        """Igual, pero con el `retry_after_s` que ya calcula el traductor F1."""
        if segundos is None:
            return False
        t = time.time() if ahora is None else ahora
        try:
            s = float(segundos)
        except (TypeError, ValueError):
            return False
        return self.pausar(provider_id, t + s, motivo=motivo, ahora=t) if s > 0 else False

    def despausar(self, provider_id: str) -> None:
        with self._libre:
            pid = str(provider_id or "?")
            self._pausa.pop(pid, None)
            self._pausa_secuencia.pop(pid, None)
            self._pausa_evento.pop(pid, None)
            self._libre.notify_all()

    def registrar_rate_limit(self, provider_id: str, *, retry_after_s: Optional[float] = None,
                             reset_hint: str = "", reset_at: Optional[float] = None,
                             motivo: str = "rate_limit", ahora: Optional[float] = None) -> dict:
        """Registra un rate-limit REAL del proveedor y, si informó reset, crea cooldown local.

        El evento histórico no significa que la cuota siga agotada. El cooldown es un
        mecanismo local que respeta el reset informado; la cuota actual queda desconocida
        hasta una ejecución real exitosa.
        """
        pid = str(provider_id or "?")
        t = time.time() if ahora is None else float(ahora)
        retry = None
        try:
            if retry_after_s is not None and float(retry_after_s) > 0:
                retry = float(retry_after_s)
        except (TypeError, ValueError):
            pass
        hasta = None
        try:
            if reset_at is not None:
                candidate = float(reset_at)
                if t < candidate <= t + 24 * 3600:
                    hasta = candidate
        except (TypeError, ValueError):
            pass
        if hasta is None and retry is not None and retry <= 24 * 3600:
            hasta = t + retry

        with self._libre:
            self._secuencia_estado += 1
            evento = {
                "state": "provider_rate_limited",
                "sequence": self._secuencia_estado,
                "occurred_at": t,
                "retry_after_s": retry,
                "reset_hint": str(reset_hint or ""),
                "reset_at": hasta,
                "reason": str(motivo or "rate_limit"),
                "origin": "provider",
            }
            ultima_ejecucion = self._ultima_ejecucion.get(pid)
            limite_previo = self._limite_proveedor.get(pid)
            # Callbacks may arrive after another request has already completed. Their
            # observation timestamp, not callback arrival/lock order, decides precedence.
            exito_mas_nuevo = bool(
                ultima_ejecucion and ultima_ejecucion.get("verified_at", 0) > t
            )
            limite_mas_nuevo = bool(
                limite_previo and limite_previo.get("occurred_at", 0) > t
            )
            if exito_mas_nuevo or limite_mas_nuevo:
                evento["superseded"] = True
                if exito_mas_nuevo:
                    evento["superseded_by_execution_at"] = ultima_ejecucion.get("verified_at")
                if limite_mas_nuevo:
                    evento["superseded_by_provider_event_at"] = limite_previo.get("occurred_at")
                return evento

            self._limite_proveedor[pid] = evento
            if hasta is not None and _pausa_activa():
                vigente = self._pausa.get(pid)
                fin = max(hasta, vigente[0]) if vigente and vigente[0] > t else hasta
                evento_origen = (self._pausa_evento.get(pid)
                                 if vigente and vigente[0] > hasta else evento)
                self._pausa[pid] = (fin, str(motivo or "rate_limit"))
                self._pausa_secuencia[pid] = self._secuencia_estado
                self._pausa_evento[pid] = dict(evento_origen or evento)
                self._libre.notify_all()
            return dict(evento)

    def registrar_ejecucion_exitosa(self, provider_id: str, *, actual_model: str = "",
                                    ahora: Optional[float] = None) -> dict:
        """Registra resultado real exitoso y despeja cualquier cooldown anterior.

        La secuencia bajo el mismo lock resuelve carreras: un rate-limit observado después
        de este éxito vuelve a pausar; uno anterior nunca puede imponerse sobre él.
        """
        pid = str(provider_id or "?")
        t = time.time() if ahora is None else float(ahora)
        with self._libre:
            self._secuencia_estado += 1
            limite = self._limite_proveedor.get(pid)
            ejecucion_previa = self._ultima_ejecucion.get(pid)
            ejecucion_previa_at = (ejecucion_previa or {}).get("verified_at", 0)
            if ejecucion_previa and ejecucion_previa_at > t:
                return dict(ejecucion_previa)

            verificado_tras_limite = bool(limite and limite.get("occurred_at", 0) <= t)
            evento_pausa = self._pausa_evento.get(pid)
            evento_pausa_at = (evento_pausa or {}).get("occurred_at")
            pausa_anterior_al_exito = (evento_pausa_at is None or evento_pausa_at <= t)
            if pid in self._pausa and pausa_anterior_al_exito:
                self._pausa.pop(pid, None)
                self._pausa_secuencia.pop(pid, None)
                self._pausa_evento.pop(pid, None)
            ejecucion = {
                "state": ("execution_verified_after_limit" if verificado_tras_limite
                          else "execution_verified"),
                "sequence": self._secuencia_estado,
                "verified_at": t,
                "actual_model": str(actual_model or ""),
                "after_provider_event_at": limite.get("occurred_at") if verificado_tras_limite else None,
            }
            self._ultima_ejecucion[pid] = ejecucion
            self._libre.notify_all()
            return dict(ejecucion)

    def estado_provider(self, provider_id: str, *, authenticated_ready: Optional[bool] = None,
                        ahora: Optional[float] = None) -> dict:
        """Estado ortogonal: autenticación, eventos, cooldown local y cuota desconocida."""
        pid = str(provider_id or "?")
        t = time.time() if ahora is None else float(ahora)
        with self._lock:
            return self._estado_provider_bajo_lock(pid, t, authenticated_ready)

    def _estado_provider_bajo_lock(self, pid: str, t: float,
                                  authenticated_ready: Optional[bool]) -> dict:
        pausa = self._pausa.get(pid)
        if pausa and pausa[0] <= t:
            self._pausa.pop(pid, None)
            self._pausa_secuencia.pop(pid, None)
            self._pausa_evento.pop(pid, None)
            pausa = None
        activa = bool(pausa and _pausa_activa())
        evento_local = dict(self._pausa_evento[pid]) if activa and pid in self._pausa_evento else None
        evento_proveedor = dict(self._limite_proveedor[pid]) if pid in self._limite_proveedor else None
        ejecucion = dict(self._ultima_ejecucion[pid]) if pid in self._ultima_ejecucion else None
        restante = max(0.0, pausa[0] - t) if activa and pausa else None
        return {
            "authenticated_ready": authenticated_ready,
            "quota_availability": "unknown",
            "last_execution_state": (ejecucion.get("state") if ejecucion else
                                      "provider_rate_limited" if evento_proveedor else "not_verified"),
            "last_execution": ejecucion,
            "last_provider_event": evento_proveedor,
            "local_cooldown": {
                "state": ("local_cooldown_from_previous_limit" if activa else "inactive"),
                "active": activa,
                "remaining_s": restante,
                "originating_provider_event": evento_local,
            },
        }

    def pausa_de(self, provider_id: str, *, ahora: Optional[float] = None):
        """(hasta_epoch, motivo) si hay pausa vigente, o None."""
        t = time.time() if ahora is None else ahora
        with self._lock:
            v = self._pausa.get(str(provider_id or "?"))
            if v and v[0] > t:
                return v
            return None

    # ── estado / forense ──────────────────────────────────────────────────────────
    def estado(self, *, ahora: Optional[float] = None) -> dict:
        t = time.time() if ahora is None else ahora
        with self._lock:
            return {
                "limite": self._limite,
                "activos": self._activos,
                # `en_vuelo` sigue siendo la lista de providers corriendo algo — la forma
                # que ya leen las varas y el forense. El detalle por provider va al lado.
                "en_vuelo": sorted(self._en_vuelo),
                "por_provider": {k: {"activos": v, "techo": techo_de(k)}
                                 for k, v in sorted(self._en_vuelo.items())},
                # EL CARRIL AUXILIAR SE DICE. Un turno que corre por otro carril y no
                # aparece en el estado es exactamente la clase de cosa que deja de decirse.
                "aux_en_vuelo": sorted(self._aux_en_vuelo),
                "aux_por_provider": {k: {"activos": v, "techo": _MAX_AUX_POR_PROVIDER}
                                     for k, v in sorted(self._aux_en_vuelo.items())},
                "aux_techo": _MAX_AUX_POR_PROVIDER,
                "pausados": {k: round(v[0] - t, 1) for k, v in self._pausa.items() if v[0] > t},
                "pausa_activa": _pausa_activa(),
                "por_provider_estado": {
                    pid: self._estado_provider_bajo_lock(pid, t, None)
                    for pid in sorted(set(self._limite_proveedor) | set(self._ultima_ejecucion) |
                                      set(self._pausa))
                },
                "rechazos": dict(self.rechazos),
            }

    def reiniciar(self) -> None:
        """Sólo para varas: deja el contador como recién nacido."""
        with self._libre:
            self._activos = 0
            self._en_vuelo.clear()
            self._aux_en_vuelo.clear()
            self._pausa.clear()
            self._pausa_secuencia.clear()
            self._pausa_evento.clear()
            self._limite_proveedor.clear()
            self._ultima_ejecucion.clear()
            self._secuencia_estado = 0
            self.rechazos.clear()
            # Si una vara reinicia con alguien esperando, ese alguien tiene que despertarse:
            # el estado por el que dormía ya no existe.
            self._libre.notify_all()

    # ── internos (bajo el lock) ───────────────────────────────────────────────────
    def _pausa_vigente(self, pid: str, t: float) -> Optional[float]:
        if not _pausa_activa():
            return None
        v = self._pausa.get(pid)
        if not v:
            return None
        if v[0] <= t:
            self._pausa.pop(pid, None)        # venció: se limpia sola
            self._pausa_secuencia.pop(pid, None)
            self._pausa_evento.pop(pid, None)
            return None
        return v[0]

    def _contar(self, motivo: str) -> None:
        self.rechazos[motivo] = self.rechazos.get(motivo, 0) + 1


#: La instancia del proceso. El server la usa; las varas la reinician.
SLOTS = Slots()


# ── LA CAUSA TIPADA DEL RECHAZO ───────────────────────────────────────────────────
try:
    import errores_modelo as _traductor                # type: ignore
except ImportError:                                     # pragma: no cover - camino de rescate
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        import errores_modelo as _traductor            # type: ignore
    except ImportError:
        _traductor = None                               # type: ignore

_DETALLE = {
    PROVIDER_OCUPADO: "Tu {cli} ya está atendiendo otro turno. Espera a que termine.",
    SIN_SLOTS: "Hay {activos} turnos de cognición en curso (el techo es {limite}). Espera.",
    EN_PAUSA: "{cli} tuvo un límite temporal anteriormente. Aleph sigue respetando la ventana local de reintento.",
}

#: La misma causa, cuando el techo de ESE provider es mayor que uno. No es una causa nueva
#: —`cli_ocupado` sigue siendo una sola— es la MISMA dicha sin mentir: con techo 3, «ya está
#: atendiendo otro turno» le dice a la persona que hay uno cuando hay tres, y el número es
#: justamente lo que le permite entender por qué esperar. La de arriba queda intacta y es la
#: que sigue viendo todo provider serializado en uno, que hoy son todos menos Codex.
_DETALLE_PROVIDER_N = ("Tu {cli} ya está atendiendo {activos} turnos a la vez, que es su "
                       "techo. Espera a que termine uno.")


def _legible(segundos: Optional[float]) -> str:
    if segundos is None or segundos <= 0:
        return "un momento"
    s = int(segundos)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {(s % 3600) // 60} min"


def causa_de(e: SinSlot, *, nombre_cli: str = "CLI") -> Optional[dict]:
    """`SinSlot` → `CausaModelo` serializada, del vocabulario cerrado.

    ── F1c · CAMBIO DE VEREDICTO DECLARADO ────────────────────────────────────────
    ANTES: los TRES motivos salían `rate_limit`, y el `origen` de la evidencia era lo
    único que separaba nuestro techo (`aleph`) de la ventana del proveedor (`cli`).
    AHORA los dos que son NUESTROS —`sin_slots` y `provider_ocupado`— salen `cli_ocupado`,
    la causa que este archivo pidió en F2b y que F1c agregó.

    `en_pausa` is the local rejection state, not a live provider verdict. The actual
    provider rate-limit event is retained separately, including its original reset hint;
    `causa_de` labels this rejection as a local cooldown and reports quota availability as
    unknown.

    El `origen` de la evidencia SE CONSERVA aunque ahora sea redundante con la causa: hay
    consumidores que ya lo leen, y F2b lo dejó escrito con su motivo (fundir quién limitó
    es el defecto que la auditoría 1 le midió a LiteLLM).
    """
    if _traductor is None:
        return None
    try:
        plantilla = _DETALLE.get(e.motivo, "No hay turno disponible ahora.")
        if e.motivo == EN_PAUSA:
            detalle = (f"{nombre_cli} tuvo un límite temporal anteriormente. Aleph sigue "
                       "respetando la ventana local de reintento; no puede confirmar la "
                       "cuota disponible ahora.")
        elif e.motivo == PROVIDER_OCUPADO and e.limite > 1:
            plantilla = _DETALLE_PROVIDER_N
            detalle = plantilla.format(cli=nombre_cli, activos=e.activos,
                                       limite=e.limite, restante=_legible(e.restante_s))
        else:
            detalle = plantilla.format(cli=nombre_cli, activos=e.activos,
                                       limite=e.limite, restante=_legible(e.restante_s))
        ev = {"motivo": e.motivo,
              "origen": "aleph",
              "activos": e.activos, "limite": e.limite}
        if e.motivo == EN_PAUSA:
            ev["runtime_state"] = "local_cooldown_from_previous_limit"
            ev["quota_availability"] = "unknown"
            if e.evento_previo:
                ev["provider_event"] = dict(e.evento_previo)
        if e.provider:
            ev["provider"] = e.provider
        _causa = (_traductor.RATE_LIMIT if e.motivo == EN_PAUSA
                  else getattr(_traductor, "CLI_OCUPADO", _traductor.RATE_LIMIT))
        causa = _traductor.CausaModelo(
            causa=_causa, estado=_traductor.ROTO,
            detalle=detalle, fuente=_traductor.FUENTE_CLI, evidencia=ev,
            reintentable=True,
            # Sólo la pausa sabe CUÁNDO. «ocupado» no lo sabe, y el contrato de F1 dice
            # None jamás 0: inventar un retry_after sería inventar una promesa.
            retry_after_s=(e.restante_s if e.motivo == EN_PAUSA and e.restante_s
                           and e.restante_s > 0 else None),
        ).como_dict()
        if e.motivo == EN_PAUSA:
            causa["runtime_state"] = "local_cooldown_from_previous_limit"
            causa["quota_availability"] = "unknown"
        return causa
    except Exception:                                   # noqa: BLE001 — jamás rompe el server
        return None


__all__ = ["Slots", "SLOTS", "SinSlot", "causa_de", "MAX_TURNOS", "techo_de",
           "ESPERA_S", "ESPERA_TURNO_S",
           "SIN_SLOTS", "PROVIDER_OCUPADO", "EN_PAUSA", "MOTIVOS"]
