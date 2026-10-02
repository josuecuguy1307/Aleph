"""Lifecycle desktop del server BYO-CLI.

Casa 3 levantaba :8926 como un proceso de desarrollo separado. En Casa 2 el único
proceso poseído por Tauri es `aleph_sidecar`; por eso el server se administra como un
hilo dentro de ese sidecar. Comparte muerte con el backend, pero conserva el endpoint
OpenAI-compatible y las fronteras anti-CSRF/sanitización ya certificadas.

Una segunda instancia de Aleph nunca crea un listener duplicado: si :8926 ya responde
como `cli_brain`, lo reutiliza sin reclamar propiedad; si el puerto pertenece a otra
cosa, falla de forma explícita y no la toca.

═══ F2d · LO QUE ESTA FASE NO CABLEA, Y DÓNDE VA ═══════════════════════════════════
Tres cables quedan PROPUESTOS y no puestos, porque los tres viven fuera de `cli_brain/`.
Están acá y no en un documento aparte para que el que abra este módulo los vea:

  1. BARRIDO AL ARRANCAR — `product/backend/app/main.py::_lifespan`, justo después del
     bloque del dueño (`dueno.actual().barrer_al_arrancar()`) y antes de `purge_task=`.
     El código exacto está en el docstring de `registro.barrer_cli_al_arrancar`.

  2. CIERRE EN EL BACKEND SUELTO — el `finally` de `_lifespan` apaga el dueño y cierra la
     DB, pero **no llama a `stop_managed_service()`**. Bajo `sidecar_serve` no hace falta
     (ese sí lo llama, dos veces: en `_request_shutdown` y en su `finally`), pero cuando
     el backend corre solo —dev, `start_caso3_stack.sh`— el que muere es el backend y los
     `claude -p` en vuelo quedan huérfanos. Va junto al `apagar_todo` del dueño:

         try:
             from cli_brain.lifecycle import stop_managed_service
             stop_managed_service()
         except Exception as exc:  # noqa: BLE001 — el shutdown no se cae por esto
             print(f"[cli_brain] cierre NO corrió: {exc}", flush=True)

     (Con `start_caso3_stack.sh` el :8926 es un proceso aparte y esto es no-op sano: el
     lifecycle de ese backend no posee el listener y `stop()` sólo mata lo suyo.)

  3. FORCE-EXIT — la mitad de afuera del esquema de emdash. `stop_detallado()` acota la
     fase crítica y NOMBRA el paso colgado, pero no mata el proceso: esto es una
     biblioteca y el proceso es de otro. El dueño del proceso es
     `deploy/fase4/sidecar_serve.py`, y el punto es su `finally` (hoy
     `killed = stop_managed_service()`):

         parte = stop_managed_service_detallado()
         print(f"[sidecar] cli_brain detenido; procesos CLI terminados={parte['matados']}",
               flush=True)
         if parte.get("colgado"):
             print(f"[sidecar] cierre colgado en «{parte['colgado']}» — salida forzada",
                   flush=True)
             os._exit(0)

     `os._exit` y no `sys.exit` a propósito: si un paso quedó colgado, hay un hilo no-daemon
     o un handler bloqueado, y una salida limpia esperaría por ellos — que es exactamente
     lo que este cable viene a impedir.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

from .base import terminate_active_processes
from .registro import barrer_cli_al_arrancar
from . import credencial as _credencial
from .server import PORT, create_server

_log = sys.stderr

#: F2d · techo de la FASE CRÍTICA del cierre (emdash: `CRITICAL_DEADLINE_MS = 5_000`).
CIERRE_CRITICO_S = float(os.environ.get("PUPPET_CLI_CIERRE_DEADLINE", "5"))


def probe_service(port: int = PORT, *, timeout: float = 0.4) -> bool:
    """True solo si el listener es inequívocamente el cli_brain de Aleph."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{int(port)}/health",
            headers={"User-Agent": "aleph-sidecar-lifecycle/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return bool(resp.status == 200 and data.get("ok") is True
                    and data.get("service") == "cli_brain")
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return False


class CliBrainLifecycle:
    """Dueño idempotente de como máximo un listener cli_brain."""

    def __init__(self, port: int = PORT):
        self.port = int(port)
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._mode = "not_started"
        self._detail = "el servicio CLI todavía no fue iniciado por este runtime"
        self._checked_at = 0.0
        self._lock = threading.RLock()

    def _serve(self, server) -> None:
        try:
            server.serve_forever(poll_interval=0.1)
        except Exception as exc:  # el status lo surfacea; no mata el backend principal
            with self._lock:
                if self._server is server:
                    self._mode = "failed"
                    self._detail = f"el listener CLI terminó: {exc.__class__.__name__}"

    def start(self) -> dict:
        with self._lock:
            reusable = self._mode in ("managed", "shared") and probe_service(self.port)
            if reusable and (self._mode == "shared" or
                             (self._thread is not None and self._thread.is_alive())):
                return self.status()
            stale_owned = self._server is not None
        if stale_owned:
            # A dead/unhealthy owned listener must be closed before rebinding. Do
            # this outside the lock: shutdown waits for the serving thread.
            self.stop_detallado()
        with self._lock:
            if self._mode == "shared" and not probe_service(self.port):
                self._mode = "not_started"
            # La llave de instancia, ANTES de que el listener acepte nada. Es idempotente:
            # si ya había —de otra instancia que arrancó primero— devuelve ESA, que es lo
            # que hace que el modo `shared` siga funcionando (ver `credencial.py`).
            try:
                _llave = _credencial.asegurar()
            except Exception as exc:             # noqa: BLE001 — nunca degradar auth
                _llave = ""
                _key_failure = type(exc).__name__
            else:
                _key_failure = "empty"
            if not _llave:
                self._mode = "failed"
                self._detail = ("no pude preparar la llave de instancia del servicio CLI "
                                f"({_key_failure}); revisa permisos del directorio de datos")
                self._checked_at = time.time()
                return self.status()
            try:
                self._server = create_server(self.port, llave=_llave)
            except OSError:
                self._server = None
                if probe_service(self.port):
                    self._mode = "shared"
                    self._detail = "servicio CLI local ya activo; esta instancia lo reutiliza"
                else:
                    self._mode = "failed"
                    self._detail = (f"no pude iniciar el servicio CLI en 127.0.0.1:{self.port}: "
                                    "el puerto está ocupado por otro proceso")
                self._checked_at = time.time()
                return self.status()

            self._thread = threading.Thread(
                target=self._serve, args=(self._server,), name="aleph-cli-brain", daemon=True)
            self._thread.start()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not probe_service(self.port):
                if not self._thread.is_alive():
                    break
                time.sleep(0.025)
            if probe_service(self.port):
                self._mode = "managed"
                self._detail = "servicio CLI administrado por Aleph"
            else:
                self._mode = "failed"
                self._detail = "el servicio CLI no respondió después de iniciar"
                try:
                    self._server.shutdown()
                    self._server.server_close()
                except Exception:
                    pass
                if self._thread and self._thread.is_alive():
                    self._thread.join(timeout=1.0)
                self._server = None
                self._thread = None
            self._checked_at = time.time()
            return self.status()

    def status(self) -> dict:
        with self._lock:
            healthy = probe_service(self.port)
            mode = self._mode
            detail = self._detail
            if mode == "managed" and self._thread and not self._thread.is_alive():
                healthy = False
                mode = "failed"
                detail = "el hilo del servicio CLI terminó inesperadamente"
            state = "ready" if healthy and mode != "failed" else "unavailable"
            if healthy and mode not in ("managed", "shared", "failed"):
                mode = "shared"
                detail = "servicio CLI local detectado"
            return {
                "state": state,
                "mode": mode,
                "detail": detail,
                "managed": bool(mode == "managed"),
                "checked_at": time.time(),
            }

    def stop(self) -> int:
        """Cierra lo que esta instancia posee y mata sus CLIs activos.

        Devuelve cuántos procesos CLI encontró vivos (contrato de siempre; `sidecar_serve`
        lo imprime). El parte completo está en `stop_detallado()`.
        """
        return self.stop_detallado()["matados"]

    def stop_detallado(self) -> dict:
        """El cierre, con FASE CRÍTICA ACOTADA — esquema de emdash
        (`apps/emdash-desktop/src/main/app/shutdown.ts`:18-99, Apache-2.0 © 2026 General
        Action, Inc.), reescrito acá con nuestras piezas.

        EL AGUJERO QUE CIERRA. Este `stop` era una secuencia de pasos **sin techo de
        tiempo**: `server.shutdown()` espera a que el loop de `serve_forever` salga —y si
        un handler está bloqueado leyendo un CLI que se colgó, ese loop no sale—; después
        `terminate_active_processes()` hace `proc.wait()`; después `server_close()`. Cada
        uno puede tardar lo que quiera, y el cierre de la app se cuelga con ellos. En una
        `.app` eso es el usuario mirando un ⌘Q que no hace nada.

        Lo de emdash, que es lo que se copia: **una fase crítica que corre en su propio
        hilo con un deadline**, y si el deadline vence, se sigue igual **diciendo cuál era
        el paso colgado**. La diferencia con emdash es dónde termina: allá hay un
        `app.exit(0)` porque quien cierra es Electron y es dueño del proceso; acá esto es
        una biblioteca dentro del sidecar y matar el proceso ajeno no le corresponde. Por
        eso el paso colgado se REPORTA (`colgado`) y quien sí es dueño del proceso —
        `deploy/fase4/sidecar_serve.py`— decide si fuerza la salida. Va como propuesta en
        las notas de la fase: acá el force-exit no se toma solo.

        `{"matados", "colgado": nombre|None, "duracion_s", "pasos": {...}}`
        """
        with self._lock:
            server = self._server
            thread = self._thread
            owned = server is not None
            self._server = None
            self._thread = None
            self._mode = "stopped"
            self._detail = "servicio CLI detenido con Aleph"
            self._checked_at = time.time()

        # Los pasos, EN ORDEN, y nombrados: el nombre es lo que se loguea si uno se cuelga.
        # `terminate_active_processes` va en el medio a propósito — antes que `server_close`
        # porque un handler bloqueado en un CLI no suelta el hilo hasta que ese CLI muera,
        # y después de `shutdown` porque primero se corta el listener (que no entren turnos
        # nuevos) y recién ahí se matan los que hay.
        parte = {"matados": 0, "colgado": None, "duracion_s": 0.0, "pasos": {}}

        def _matar():
            parte["matados"] = terminate_active_processes()

        pasos = []
        if owned:
            pasos.append(("server.shutdown", server.shutdown))
        pasos.append(("terminate_active_processes", _matar))
        if owned:
            pasos.append(("server.server_close", server.server_close))
            if thread is not None:
                pasos.append(("thread.join", lambda: thread.join(timeout=2.0)))

        en_curso = {"paso": None}
        t0 = time.monotonic()

        def _fase_critica():
            for nombre, fn in pasos:
                en_curso["paso"] = nombre
                p0 = time.monotonic()
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001 — un paso que falla no frena el cierre
                    print(f"[cli_brain] cierre: el paso {nombre} falló: "
                          f"{exc.__class__.__name__}: {exc}", file=_log, flush=True)
                parte["pasos"][nombre] = round(time.monotonic() - p0, 3)
                en_curso["paso"] = None

        h = threading.Thread(target=_fase_critica, name="aleph-cli-brain-stop", daemon=True)
        h.start()
        h.join(timeout=CIERRE_CRITICO_S)
        if h.is_alive():
            # El deadline venció. NO se espera más: se dice QUÉ quedó colgado —sin eso, el
            # que depura un cierre eterno no tiene por dónde empezar— y se sigue. El hilo
            # es daemon, así que no le impide al proceso terminar.
            colgado = en_curso["paso"] or "(desconocido)"
            parte["colgado"] = colgado
            print(f"[cli_brain] ⚠ cierre: la fase crítica pasó los {CIERRE_CRITICO_S:.0f}s "
                  f"y sigue en «{colgado}». Se continúa sin esperarla; los pasos que "
                  f"faltaban NO corrieron.", file=_log, flush=True)
        parte["duracion_s"] = round(time.monotonic() - t0, 3)
        return parte


_DESKTOP_SERVICE = CliBrainLifecycle()


def start_managed_service() -> dict:
    return _DESKTOP_SERVICE.start()


def service_status() -> dict:
    return _DESKTOP_SERVICE.status()


def stop_managed_service() -> int:
    return _DESKTOP_SERVICE.stop()


def stop_managed_service_detallado() -> dict:
    """El cierre con su parte: cuántos CLI murieron, cuánto tardó, y qué paso quedó
    colgado si la fase crítica pasó su deadline. Quien es dueño del proceso (el sidecar)
    puede usar `colgado` para decidir si fuerza la salida."""
    return _DESKTOP_SERVICE.stop_detallado()


__all__ = [
    "CliBrainLifecycle", "probe_service", "start_managed_service",
    "service_status", "stop_managed_service", "stop_managed_service_detallado",
    # F2d · exportado, NO cableado al arranque: cablearlo es del backend (ver notas).
    "barrer_cli_al_arrancar", "CIERRE_CRITICO_S",
]
