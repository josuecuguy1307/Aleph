#!/usr/bin/env python3
"""adaptador.py — el contrato común de los tres, y el caño de stdio que comparten.

Cada adaptador traduce TRES cosas y ninguna más: su protocolo, sus banderas y su campo de
caché. Todo lo demás (pool, dueño, ciclo de vida, ledger) es de la capa.

⚠️ EL CAMPO DE CACHÉ NO SE FUNDE. `cache_read_input_tokens` en Claude,
`cached_input_tokens` en Codex, `cache_read_input_tokens` en Grok. Fundirlos en un nombre
propio fue el defecto que el hop del ledger vino a cerrar: el borde veía `prompt` y
`completion` pero no distinguía cacheado de no cacheado, **y son precios distintos**.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .vocabulario import Capabilities, Session

_log = sys.stderr


@dataclass
class ResultadoTurno:
    """Lo que un turno del broker devuelve. Deliberadamente parecido a `BrainResult` para
    que la capa traduzca en una línea y no invente campos por el camino."""
    ok: bool
    texto: str = ""
    model_final: Optional[str] = None
    #: EL USAGE **CRUDO** DEL CLI, tal como vino. No normalizado.
    #: ⚠️ La tabla de nombres YA EXISTE: `base.usage_del_cli` conoce
    #: `cache_creation_input_tokens`/`cache_read_input_tokens` de Claude,
    #: `cached_input_tokens` de Codex y el respaldo `prompt_tokens_details.cached_tokens`.
    #: La primera versión de estos adaptadores normalizaba a `prompt_tokens`/
    #: `completion_tokens` ANTES de dársela, y el resultado fue `tokens_medidos=False` en
    #: los tres: la función buscaba `input_tokens` y no lo encontraba. Un ledger ciego por
    #: traducir dos veces lo que ya estaba traducido.
    usage_bruto: dict = field(default_factory=dict)
    cache_lectura: Optional[int] = None
    cache_escritura: Optional[int] = None
    razonamiento: Optional[int] = None
    tokens_medidos: bool = False
    exec_events: int = 0
    error_detalle: str = ""
    #: `True` cuando el fallo es DEL PROCESO (murió, se colgó, protocolo roto). La capa lo
    #: lee para caer al camino de hoy en vez de devolverle un error al usuario.
    proceso_perdido: bool = False
    meta: dict = field(default_factory=dict)


class _Caño:
    """Un proceso con stdio y lectura por líneas en hilos. Lo comparten los tres porque los
    tres hablan JSON por línea — ACP, JSON-RPC de codex y stream-json de claude.

    ⚠️ El techo de línea existe por lo mismo que en `base._BufferDeLineas`: un CLI que
    emite una línea de 500 MB se come la RAM del sidecar antes de que nadie note nada.
    """
    MAX_LINEA = 8 * 1024 * 1024

    def __init__(self, argv: list, cwd: str, env: dict):
        self.argv, self.cwd, self.env = argv, cwd, env
        self.proc: Optional[subprocess.Popen] = None
        self.cola: "queue.Queue" = queue.Queue()
        self.stderr_reciente: list = []
        self._hilos: list = []
        self._lock = threading.Lock()

    def abrir(self) -> None:
        kw = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                  cwd=self.cwd, env=self.env, bufsize=0)
        if os.name == "posix":
            kw["start_new_session"] = True
        self.proc = subprocess.Popen(self.argv, **kw)
        for canal, pipe in (("stdout", self.proc.stdout), ("stderr", self.proc.stderr)):
            h = threading.Thread(target=self._bombear, args=(pipe, canal), daemon=True)
            h.start()
            self._hilos.append(h)

    def _bombear(self, pipe, canal: str) -> None:
        buf = bytearray()
        try:
            while True:
                trozo = pipe.read(65536)
                if not trozo:
                    break
                buf.extend(trozo)
                while True:
                    i = buf.find(b"\n")
                    if i < 0:
                        break
                    linea = bytes(buf[:i]); del buf[:i + 1]
                    s = linea.decode("utf-8", "replace")
                    if canal == "stdout":
                        self.cola.put(s)
                    else:
                        with self._lock:
                            self.stderr_reciente.append(s)
                            del self.stderr_reciente[:-40]
                if len(buf) > self.MAX_LINEA:
                    del buf[:]
        except Exception:                                   # noqa: BLE001 — la tubería murió
            pass
        finally:
            if canal == "stdout":
                self.cola.put(None)                         # centinela
            try:
                pipe.close()
            except Exception:                               # noqa: BLE001
                pass

    def escribir(self, obj: dict) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise BrokenPipeError("el proceso no está abierto")
        self.proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
        self.proc.stdin.flush()

    def leer(self, timeout: float):
        """Una línea de stdout, o `None` si cerró, o `_VACIO` si venció el plazo."""
        try:
            return self.cola.get(timeout=timeout)
        except queue.Empty:
            return _VACIO

    def vive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stderr(self) -> str:
        with self._lock:
            return "\n".join(self.stderr_reciente)[-2000:]

    def cerrar(self) -> None:
        p = self.proc
        if p is None:
            return
        try:
            if p.stdin:
                p.stdin.close()
        except Exception:                                   # noqa: BLE001
            pass
        try:
            p.wait(timeout=3.0)
            return
        except Exception:                                   # noqa: BLE001
            pass
        # cortesía primero, y al GRUPO — el CLI puede tener hijos propios
        for sig in (15, 9):
            try:
                if os.name == "posix":
                    os.killpg(p.pid, sig)
                else:
                    p.kill()
                p.wait(timeout=2.0)
                return
            except Exception:                               # noqa: BLE001
                continue


class _Vacio:
    __slots__ = ()


_VACIO = _Vacio()


class Adaptador:
    """El contrato. Un adaptador NO sabe de pool, ni de dueños, ni del ledger."""

    provider_id: str = ""
    CAPS: Capabilities

    def __init__(self, cfg: dict, binario: str, env: dict, cwd: str):
        self.cfg, self.binario, self.env, self.cwd = cfg, binario, env, cwd
        self.cano = _Caño(self.argv_de_arranque(), cwd, env)

    # ── lo que cada uno implementa ────────────────────────────────────────────────
    def argv_de_arranque(self) -> list: raise NotImplementedError
    def saludar(self, plazo: float = 60.0) -> None: raise NotImplementedError
    def abrir_sesion(self, ses: Session, plazo: float = 90.0) -> None: raise NotImplementedError
    def turno(self, ses: Session, prompt: str, on_evento=None,
              plazo: float = 180.0) -> ResultadoTurno: raise NotImplementedError

    # ── lo que sale gratis ────────────────────────────────────────────────────────
    @property
    def proc(self):
        return self.cano.proc

    def vive(self) -> bool:
        return self.cano.vive()

    def cerrar(self) -> None:
        self.cano.cerrar()

    # ── el caño con plazo, compartido ─────────────────────────────────────────────
    def _esperar(self, pred, plazo: float, on_linea=None):
        """Líneas hasta que `pred(obj)` diga que sí. Devuelve `(obj, muerto)`.

        ⚠️ `muerto=True` NO es un error del turno: es que el proceso cerró stdout. La capa
        lo traduce a `proceso_perdido` y cae al camino de hoy.
        """
        fin = time.monotonic() + plazo
        while True:
            restante = fin - time.monotonic()
            if restante <= 0:
                return None, False
            s = self.cano.leer(min(1.0, restante))
            if s is _VACIO:
                if not self.cano.vive():
                    return None, True
                continue
            if s is None:
                return None, True
            s = s.strip()
            if not s or s[0] not in "{[":
                continue
            try:
                obj = json.loads(s)
            except Exception:                               # noqa: BLE001
                continue
            if not isinstance(obj, dict):
                continue
            if on_linea is not None:
                try:
                    on_linea(obj)
                except Exception:                           # noqa: BLE001
                    pass
            if pred(obj):
                return obj, False


__all__ = ["Adaptador", "ResultadoTurno", "_Caño"]
