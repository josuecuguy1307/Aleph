#!/usr/bin/env python3
"""pool.py — quién POSEE los procesos vivos del broker.

Mismo patrón que `platform/inspection/dueno.py` (tabla de vivos · refcount · huella ·
cosechador de ociosidad · techo con desalojo LRU · libro en disco escrito ANTES del spawn ·
barrido de arranque), reescrito acá porque el dueño habla MCP y esto habla el protocolo de
cada CLI. **Se copia la disciplina, no el módulo** — y sobre todo se copia LA CLAVE:

    (dueño, CLI, huella de config[, conversación si el harness no multiplexa])

🔴 CONFIG DISTINTA O DUEÑO DISTINTO ⇒ PROCESO DISTINTO. Fail-closed: ante la duda, proceso
nuevo. Indexar de MÁS cuesta un proceso; indexar de MENOS cruza dueños, y con proceso vivo
eso es que la segunda cuenta hereda el historial de la primera.

── LIBRO PROPIO, JAMÁS EL DE OTRO ────────────────────────────────────────────────────
`broker_procesos.jsonl`, al lado de `procesos.jsonl` (dueño, MCP) y `cli_procesos.jsonl`
(registro, un turno = una fila). Tres escritores del mismo archivo son tres verdades sobre
los mismos procesos, y los ciclos de vida no tienen nada que ver: acá una fila es un
PROCESO que sobrevive a muchos turnos.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .vocabulario import Capabilities, Harness, Session, huella_de_config

_log = sys.stderr

# ── LOS NÚMEROS, cada uno con su motivo ───────────────────────────────────────────
#: Cuánto vive un proceso sin que nadie lo use. 60 s es el patrón de `claude_code_bridge`,
#: y acá tiene un motivo medido propio: el arranque que amortiza vale 0,14-1,23 s (paso 1),
#: así que sostener un proceso 10 minutos —lo que hace el dueño de MCP— gastaría memoria por
#: un premio chico. 60 s cubre la pausa entre dos mensajes de la misma charla, que es el
#: caso que importa.
OCIOSIDAD_S = float(os.environ.get("PUPPET_CLI_BROKER_OCIOSIDAD_S", "60"))

#: Techo de procesos vivos. Seis workspaces × tres CLIs × N dueños puede ser mucho, y cada
#: proceso es un CLI entero (node o rust) con su preámbulo cargado. 6 es «los tres CLIs de
#: dos dueños» o «dos CLIs de tres charlas sin multiplexar»; se sube midiendo.
MAX_VIVOS = int(os.environ.get("PUPPET_CLI_BROKER_MAX", "6"))

#: Cada cuánto despierta el cosechador. Derivado de la ociosidad DE ESTA instancia, no de
#: la constante global — la vara del dueño ya cazó por qué: con la global, un pool creado
#: con 0,6 s de ociosidad igual dormía 15 s y la conexión no se cerraba nunca dentro del test.
def _tick_de(ociosidad_s: float) -> float:
    return max(0.05, min(15.0, float(ociosidad_s) / 4.0))


def _ruta_libro() -> Path:
    env = (os.environ.get("PUPPET_CLI_BROKER_LIBRO") or "").strip()
    if env:
        return Path(env)
    try:
        import aleph_paths
        return Path(aleph_paths.data_root()) / "broker_procesos.jsonl"
    except Exception:                                       # noqa: BLE001
        return Path(os.path.expanduser("~/.aleph-broker-procesos.jsonl"))


class BrokerError(RuntimeError):
    """El broker no pudo. **Nunca es el error del turno**: la capa lo caza y cae al camino
    de hoy. Un broker que rompe turnos es peor que no tener broker."""


class _Vivo:
    """Un proceso vivo del pool, con su adaptador y sus conversaciones adentro."""

    __slots__ = ("clave", "harness", "caps", "adaptador", "sesiones", "prestado",
                 "nacido_en", "ultimo_uso", "turnos", "muerto")

    def __init__(self, clave: str, harness: Harness, caps: Capabilities, adaptador):
        self.clave = clave
        self.harness = harness
        self.caps = caps
        self.adaptador = adaptador
        self.sesiones: dict = {}       # clave_conversacion → Session
        self.prestado = 0
        self.nacido_en = time.time()
        self.ultimo_uso = time.time()
        self.turnos = 0
        self.muerto = False

    @property
    def pid(self) -> Optional[int]:
        p = getattr(self.adaptador, "proc", None)
        return getattr(p, "pid", None)

    def vive(self) -> bool:
        if self.muerto:
            return False
        try:
            return bool(self.adaptador.vive())
        except Exception:                                   # noqa: BLE001
            return False

    def fila(self) -> dict:
        return {"clave": self.clave, "provider": self.harness.provider_id,
                "huella": self.harness.huella_config, "pid": self.pid,
                "nacido_en": self.nacido_en, "turnos": self.turnos,
                "sesiones": len(self.sesiones), "prestado": self.prestado}


class Prestamo:
    """Un proceso PRESTADO. Mientras dura, ni la ociosidad ni el techo lo tocan — matar a
    mitad de un turno le devuelve al usuario un error que nosotros causamos."""

    def __init__(self, pool: "Pool", vivo: _Vivo, sesion: Session):
        self._pool, self._vivo, self.sesion = pool, vivo, sesion
        self._suelto = False

    @property
    def adaptador(self):
        return self._vivo.adaptador

    @property
    def caps(self) -> Capabilities:
        return self._vivo.caps

    @property
    def pid(self) -> Optional[int]:
        return self._vivo.pid

    def marcar_muerto(self, motivo: str = "") -> None:
        """El adaptador se dio cuenta de que el proceso ya no sirve. Se saca del pool para
        que el turno SIGUIENTE no lo encuentre; el turno actual ya cayó al respaldo."""
        self._pool._matar(self._vivo, motivo=motivo or "marcado por el adaptador")

    def soltar(self) -> None:
        if self._suelto:
            return
        self._suelto = True
        self._pool._soltar(self._vivo, self.sesion)

    def __enter__(self):
        return self

    def __exit__(self, *_e):
        self.soltar()
        return False


class Pool:
    """La tabla de procesos vivos. Sin estado global: el módulo expone UNA instancia
    (`POOL`) pero las varas construyen la suya con otra ociosidad y otro libro."""

    def __init__(self, *, ociosidad_s: Optional[float] = None,
                 max_vivos: Optional[int] = None, libro: Optional[Path] = None):
        self._vivos: dict = {}
        self._lock = threading.RLock()
        self.ociosidad_s = float(ociosidad_s if ociosidad_s is not None else OCIOSIDAD_S)
        self.max_vivos = int(max_vivos if max_vivos is not None else MAX_VIVOS)
        self._libro = libro
        self._cosechador: Optional[threading.Thread] = None
        self._parar = threading.Event()
        self.eventos = {"spawns": 0, "compartidos": 0, "desalojos_lru": 0,
                        "cerrados_por_ociosidad": 0, "muertes": 0, "sobrecupo": 0,
                        "sesiones_abiertas": 0, "barridos_al_arrancar": 0}

    # ── el libro ──────────────────────────────────────────────────────────────────
    @property
    def libro(self) -> Path:
        if self._libro is None:
            self._libro = _ruta_libro()
        return self._libro

    def _escribir_libro(self) -> None:
        """Entero y atómico, como `_Libro` del dueño: el archivo es chico por construcción
        (tope = `max_vivos`) y un `.jsonl` que sólo crece obliga a un compactado que es
        otra cosa que puede fallar a mitad."""
        try:
            filas = [v.fila() for v in self._vivos.values()]
            self.libro.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.libro.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                for f in filas:
                    fh.write(json.dumps(f, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.libro)
        except Exception as e:                              # noqa: BLE001 — el libro jamás
            print(f"[broker] no pude escribir {self.libro}: {e}",   # tumba un turno
                  file=_log, flush=True)

    def barrer_al_arrancar(self) -> dict:
        """Los huérfanos del arranque anterior. Mata por PID Y comando —jamás por patrón—
        y sólo lo que este libro dice que es nuestro."""
        parte = {"leidas": 0, "muertas": 0, "ya_no_estaban": 0, "ajenas": 0}
        try:
            crudo = self.libro.read_text(encoding="utf-8")
        except FileNotFoundError:
            return parte
        except Exception:                                   # noqa: BLE001
            return parte
        for linea in crudo.splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                f = json.loads(linea)
            except Exception:                               # noqa: BLE001
                continue
            parte["leidas"] += 1
            pid = f.get("pid")
            if not isinstance(pid, int):
                continue
            try:
                cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
            except Exception:                               # noqa: BLE001
                continue
            if not cmd:
                parte["ya_no_estaban"] += 1
                continue
            # el pid pudo reciclarse: sólo matamos si el comando sigue siendo del CLI que
            # anotamos. Un pid reciclado con otro comando NO se toca.
            if (f.get("provider") or "").split("_")[0] not in cmd:
                parte["ajenas"] += 1
                continue
            try:
                os.kill(pid, 15)
                parte["muertas"] += 1
            except Exception:                               # noqa: BLE001
                parte["ya_no_estaban"] += 1
        self.eventos["barridos_al_arrancar"] += parte["muertas"]
        try:
            self.libro.unlink()
        except Exception:                                   # noqa: BLE001
            pass
        return parte

    # ── el cosechador ─────────────────────────────────────────────────────────────
    def _asegurar_cosechador(self) -> None:
        if self._cosechador is not None and self._cosechador.is_alive():
            return
        self._parar.clear()
        t = threading.Thread(target=self._cosechar, name="broker-cosecha", daemon=True)
        self._cosechador = t
        t.start()

    def _cosechar(self) -> None:
        tick = _tick_de(self.ociosidad_s)
        while not self._parar.wait(tick):
            ahora = time.time()
            with self._lock:
                candidatos = [v for v in self._vivos.values()
                              if v.prestado == 0
                              and (ahora - v.ultimo_uso) >= self.ociosidad_s]
                for v in candidatos:
                    self._matar(v, motivo="ociosidad", _con_lock=True)
                    self.eventos["cerrados_por_ociosidad"] += 1
                # y los que se murieron solos: se sacan para que nadie los encuentre
                for v in [x for x in self._vivos.values()
                          if x.prestado == 0 and not x.vive()]:
                    self._matar(v, motivo="murió solo", _con_lock=True)
                    self.eventos["muertes"] += 1

    # ── el préstamo ───────────────────────────────────────────────────────────────
    def pedir(self, *, harness: Harness, caps: Capabilities, clave_conversacion: str,
              fabricar) -> Prestamo:
        """El proceso para (dueño, CLI, config[, charla]), prestado. Lo levanta si hace
        falta y lo comparte si ya está vivo con la MISMA clave.

        `fabricar()` devuelve un adaptador YA saludado. Se llama FUERA del lock: el
        handshake de grok tarda 1,2 s y sostener el lock del pool ese tiempo serializaría
        a todos los dueños contra uno.
        """
        clave = harness.clave_de_pool(clave_conversacion, caps.multiplexa_sesiones)
        self._asegurar_cosechador()
        with self._lock:
            v = self._vivos.get(clave)
            if v is not None and v.vive():
                v.prestado += 1
                v.ultimo_uso = time.time()
                self.eventos["compartidos"] += 1
                ses = self._sesion(v, harness, clave_conversacion)
                return Prestamo(self, v, ses)
            if v is not None:
                self._matar(v, motivo="estaba muerto al pedirlo", _con_lock=True)
                self.eventos["muertes"] += 1
            self._hacer_lugar(clave)

        adaptador = fabricar()                              # ← fuera del lock, a propósito
        with self._lock:
            ya = self._vivos.get(clave)
            if ya is not None and ya.vive():
                # carrera: alguien lo levantó mientras saludábamos. El nuestro se cierra;
                # duplicar sería exactamente el sobrecupo que el techo viene a evitar.
                try:
                    adaptador.cerrar()
                except Exception:                           # noqa: BLE001
                    pass
                ya.prestado += 1
                ya.ultimo_uso = time.time()
                self.eventos["compartidos"] += 1
                return Prestamo(self, ya, self._sesion(ya, harness, clave_conversacion))
            v = _Vivo(clave, harness, caps, adaptador)
            v.prestado = 1
            self._vivos[clave] = v
            self.eventos["spawns"] += 1
            self._escribir_libro()
            return Prestamo(self, v, self._sesion(v, harness, clave_conversacion))

    def _sesion(self, v: _Vivo, harness: Harness, clave_conversacion: str) -> Session:
        ses = v.sesiones.get(clave_conversacion)
        if ses is None:
            ses = Session(clave_conversacion=clave_conversacion, dueno=harness.dueno,
                          provider_id=harness.provider_id, creada_en=time.time())
            v.sesiones[clave_conversacion] = ses
            self.eventos["sesiones_abiertas"] += 1
        # ⚠️ EL CINTURÓN DEL DUEÑO, otra vez y acá adentro. La clave del pool ya separa por
        # dueño, pero una Session que quedara con otro dueño sería un cruce silencioso si
        # alguien cambiara la clave del pool en el futuro. Cuesta una comparación.
        if ses.dueno != harness.dueno:
            raise BrokerError(
                f"la conversación {clave_conversacion!r} tiene dueño {ses.dueno!r} y la "
                f"pidió {harness.dueno!r}")
        ses.ultimo_uso = time.time()
        return ses

    def _soltar(self, v: _Vivo, ses: Session) -> None:
        with self._lock:
            v.prestado = max(0, v.prestado - 1)
            v.turnos += 1
            v.ultimo_uso = time.time()
            ses.turnos += 1
            ses.ultimo_uso = time.time()
            self._escribir_libro()

    def _hacer_lugar(self, clave_nueva: str) -> None:
        """El techo, con desalojo LRU. **Un proceso PRESTADO no se desaloja**: un turno de
        otro dueño no puede matar el turno en vuelo de nadie."""
        while len(self._vivos) >= self.max_vivos:
            libres = [v for v in self._vivos.values() if v.prestado == 0]
            if not libres:
                self.eventos["sobrecupo"] += 1
                raise BrokerError(
                    f"el pool está lleno ({len(self._vivos)}/{self.max_vivos}) y todos los "
                    f"procesos están en uso")
            viejo = min(libres, key=lambda x: x.ultimo_uso)
            self._matar(viejo, motivo="desalojo LRU", _con_lock=True)
            self.eventos["desalojos_lru"] += 1

    def _matar(self, v: _Vivo, *, motivo: str, _con_lock: bool = False) -> None:
        def _hacer():
            if v.clave in self._vivos and self._vivos[v.clave] is v:
                del self._vivos[v.clave]
            v.muerto = True
            self._escribir_libro()
        if _con_lock:
            _hacer()
        else:
            with self._lock:
                _hacer()
        try:
            v.adaptador.cerrar()
        except Exception:                                   # noqa: BLE001
            pass

    # ── lo que se mira desde afuera ───────────────────────────────────────────────
    def estado(self) -> dict:
        with self._lock:
            return {"vivos": [v.fila() for v in self._vivos.values()],
                    "tope": self.max_vivos, "ociosidad_s": self.ociosidad_s,
                    "eventos": dict(self.eventos)}

    def apagar_todo(self, *, motivo: str = "cierre") -> int:
        """Lo que el `finally` del lifespan llama. Devuelve cuántos cerró."""
        self._parar.set()
        with self._lock:
            vivos = list(self._vivos.values())
        for v in vivos:
            self._matar(v, motivo=motivo)
        if vivos:
            print(f"[broker] apagados {len(vivos)} proceso(s) · motivo: {motivo}",
                  file=_log, flush=True)
        return len(vivos)


POOL = Pool()

__all__ = ["Pool", "POOL", "Prestamo", "BrokerError", "OCIOSIDAD_S", "MAX_VIVOS",
           "huella_de_config"]
