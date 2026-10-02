#!/usr/bin/env python3
"""registro.py — EL REGISTRO PERSISTENTE DE PROCESOS CLI (Gate 2 · F2d).

EL AGUJERO QUE CIERRA. `base._ACTIVE_PROCESSES` es un dict EN MEMORIA: sirve para que el
lifecycle mate a sus hijos cuando el sidecar se cierra ordenadamente, y no sirve para nada
cuando el sidecar **muere**. Un `kill -9` al sidecar, un crash, un cierre forzado de la
`.app` — y el `claude -p` que estaba corriendo queda vivo, huérfano, comiéndose la ventana
de la suscripción del usuario hasta que su propio timeout lo termine (180 s) o para siempre
si se colgó. Nadie lo sabe, porque el único que lo sabía era el proceso que ya no existe.

La forma correcta la tiene el árbol desde el dueño de MCP: **un archivo**. Este es el mismo
patrón de `platform/inspection/dueno.py::_Libro` + `barrer_al_arrancar` (§3.1/§3.3 del
DISEÑO-DUEÑO-v1), reescrito acá:

    ARCHIVO PROPIO, JAMÁS EL DEL DUEÑO. `cli_procesos.jsonl`, al lado de `procesos.jsonl`
    pero separado. Dos escritores del mismo archivo son dos verdades sobre los mismos
    procesos —el defecto que el propio dueño documenta— y además los ciclos de vida no
    tienen nada que ver: el dueño maneja conexiones MCP reutilizables con tabla de vivos y
    cosechador; acá cada fila es UN turno de cognición que nace y muere en un `invoke`.

    (El path se compone con `aleph_paths.data_root()` en vez de agregarle un
    `cli_procesos_path()` al módulo: esta fase no toca archivos fuera de `cli_brain/`. Si
    el equipo lo prefiere como hermano de `procesos_path()`, es una función de tres líneas
    — va como propuesta en las notas de la fase.)

CÓMO SE ESCRIBE (patrón `_Libro`): el archivo se reescribe ENTERO en cada cambio, a un
temporal + `os.replace` + `fsync`. Es chico por construcción (tope = `MAX_TURNOS`, hoy 2),
un `.jsonl` que sólo crece obliga a un compactado que es otra cosa que puede fallar a
mitad, y el rename atómico garantiza que un corte deje el archivo anterior entero.

DOS FASES POR TURNO, y es la ventana lo que las justifica: la fila `naciendo` se escribe
ANTES del `Popen` (todavía no hay pid) y se completa con el pid DESPUÉS. Si el sidecar
muere entre las dos, queda una fila sin pid: el barrido la REPORTA y **no la mata** — matar
por nombre podría matar a un tercero.

QUÉ **NO** SE ESCRIBE: el prompt. Nunca. Del argv sólo viajan el binario y los flags de una
ALLOWLIST nuestra (`_HUELLA_FLAGS`), así que ni una palabra del usuario puede terminar en
disco por esta vía — no porque se filtre bien, sino porque lo único que se escribe son
constantes que pusimos nosotros.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Optional

#: Nombre del archivo. Hermano de `procesos.jsonl`, y explícitamente NO él.
NOMBRE = "cli_procesos.jsonl"

#: Historial append-only de la vida de cada pedido. A diferencia de ``NOMBRE``, que es
#: una tabla de procesos vivos y por eso se reescribe, este archivo es evidencia: una
#: fila que ya ocurrió no se borra cuando termina el turno.
NOMBRE_EVENTOS = "cli_eventos.jsonl"

#: VENTANA (no umbral) alrededor de `nacido_en` para aceptar que un pid es el que anotamos.
#:
#: ⚠️ ES UNA VENTANA — `abs(arranque - nacido_en) <= T` — y la razón está medida en el
#: barrido del dueño: pedir `arranque >= nacido_en - T` acepta **todo lo que arrancó
#: después**, o sea exactamente el pid reciclado que este chequeo existe para descartar. Un
#: pid reciclado siempre arranca MÁS TARDE que nuestro registro.
TOLERANCIA_S = 5.0

#: Gracia entre el SIGTERM y el SIGKILL del barrido.
GRACIA_BARRIDO_S = 1.0

#: LA HUELLA. Flags que ponemos NOSOTROS en el argv y que un `claude`/`codex` lanzado por
#: la persona no tiene. Son la mitad "comando" de la identidad; la otra mitad es la hora.
#:
#: Curada a propósito: `--verbose`, `--json`, `--color` también están en nuestro argv y
#: NO están acá, porque son flags que cualquiera usa — sumarlos no agrega identidad y sí
#: agrega la chance de matar la sesión que el usuario tiene abierta en otra terminal.
#: Los de acá son de nuestro contrato de pureza del wrapper: nadie los tipea a mano.
_HUELLA_FLAGS = frozenset({
    # claude_cli
    "--strict-mcp-config", "--setting-sources", "--no-session-persistence",
    "--disallowedTools", "--include-partial-messages",
    # codex_cli
    "--skip-git-repo-check", "--ephemeral",
})


def _ruta_por_defecto():
    """`<data_root>/cli_procesos.jsonl`, o lo que diga `PUPPET_CLI_PROCESOS`.

    El override existe para las varas: escribir en el registro real de la máquina que corre
    los tests sería tocar el estado de la app del operador. Import perezoso de
    `aleph_paths` porque vive en `platform/` y el server puede correr suelto con otro
    sys.path.
    """
    from pathlib import Path
    env = (os.environ.get("PUPPET_CLI_PROCESOS") or "").strip()
    if env:
        return Path(env)
    try:
        import aleph_paths                                  # type: ignore
    except ImportError:                                     # pragma: no cover - rescate
        _plat = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if _plat not in sys.path:
            sys.path.insert(0, _plat)
        import aleph_paths                                  # type: ignore
    return Path(aleph_paths.data_root()) / NOMBRE


def _ruta_eventos_por_defecto():
    """``<data_root>/cli_eventos.jsonl`` o el override de una vara.

    Nunca comparte archivo con la tabla de vivos: una tiene semántica de estado actual y
    la otra de historial durable. Separarlas evita que la limpieza normal de un proceso
    borre la cronología que explica quién esperó, quién obtuvo slot y quién lo mató.
    """
    from pathlib import Path
    env = (os.environ.get("PUPPET_CLI_EVENTOS") or "").strip()
    if env:
        return Path(env)
    try:
        import aleph_paths                                  # type: ignore
    except ImportError:                                     # pragma: no cover - rescate
        _plat = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if _plat not in sys.path:
            sys.path.insert(0, _plat)
        import aleph_paths                                  # type: ignore
    return Path(aleph_paths.data_root()) / NOMBRE_EVENTOS


def huella_de(argv) -> list:
    """argv completo → SÓLO los flags de la allowlist, en orden y sin repetir.

    Es una INTERSECCIÓN contra un conjunto de constantes nuestras, no un filtro sobre el
    argv: por construcción no existe un prompt que pueda colarse acá.
    """
    vistos: list = []
    for a in (argv or []):
        try:
            t = str(a)
        except Exception:                                   # noqa: BLE001
            continue
        if t in _HUELLA_FLAGS and t not in vistos:
            vistos.append(t)
    return vistos


class RegistroCli:
    """El `cli_procesos.jsonl`. Una fila por turno; el archivo se reescribe entero."""

    def __init__(self, ruta=None):
        self._ruta = ruta
        self._ruta_eventos = None
        self._lock = threading.RLock()

    @property
    def ruta(self):
        if self._ruta is None:
            self._ruta = _ruta_por_defecto()
        return self._ruta

    @property
    def ruta_eventos(self):
        if self._ruta_eventos is None:
            # Una vara que inyecta la tabla de vivos debe quedar completamente aislada
            # del estado real aunque no recuerde inyectar un segundo path.
            self._ruta_eventos = (
                _ruta_eventos_por_defecto()
                if (os.environ.get("PUPPET_CLI_EVENTOS") or "").strip()
                else self._ruta.with_name("cli_eventos.jsonl")
                if self._ruta is not None
                else _ruta_eventos_por_defecto()
            )
        return self._ruta_eventos

    def anotar_evento(self, evento: str, *, turno_id: str, **datos) -> bool:
        """Agrega un evento durable, sin prompt ni argv, y fuerza su escritura a disco."""
        fila = {
            "evento": str(evento),
            "turno_id": str(turno_id),
            "ts": time.time(),
            "mono": time.monotonic(),
        }
        for clave, valor in datos.items():
            if valor is not None:
                fila[str(clave)] = valor
        with self._lock:
            try:
                self.ruta_eventos.parent.mkdir(parents=True, exist_ok=True)
                with open(self.ruta_eventos, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                return True
            except OSError as e:
                print(f"[cli_brain] no pude anotar evento en {self.ruta_eventos}: {e}",
                      file=sys.stderr, flush=True)
                return False

    # ── lectura / escritura ───────────────────────────────────────────────────────
    def leer(self) -> list:
        """Las filas. Una línea ilegible se saltea CONTÁNDOLA y avisando: si dejó un
        proceso vivo, este arranque no lo va a barrer, y eso hay que decirlo."""
        try:
            crudo = self.ruta.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as e:
            print(f"[cli_brain] no pude leer {self.ruta}: {e}", file=sys.stderr, flush=True)
            return []
        filas, rotas = [], 0
        for linea in crudo.splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                fila = json.loads(linea)
            except (json.JSONDecodeError, ValueError):
                rotas += 1
                continue
            if isinstance(fila, dict):
                filas.append(fila)
            else:
                rotas += 1
        if rotas:
            print(f"[cli_brain] {rotas} línea(s) ilegibles en {self.ruta.name}: se saltean. "
                  f"Si dejaron un proceso vivo, este arranque NO lo va a barrer.",
                  file=sys.stderr, flush=True)
        return filas

    def escribir(self, filas: list) -> bool:
        """Atómico y con `fsync`. Sin el fsync, el `naciendo` puede no estar en disco cuando
        el proceso hijo ya existe — o sea, la ventana que este archivo viene a cerrar.

        Devuelve si se pudo. **Jamás levanta**: el registro es una red de seguridad, y una
        red de seguridad que tira abajo el turno que venía a proteger no sirve de nada.
        """
        with self._lock:
            try:
                self.ruta.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.ruta.with_suffix(".jsonl.tmp")
                cuerpo = "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas)
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(cuerpo)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.ruta)
                return True
            except OSError as e:
                print(f"[cli_brain] no pude escribir {self.ruta}: {e}",
                      file=sys.stderr, flush=True)
                return False

    # ── el ciclo de vida de una fila ──────────────────────────────────────────────
    def anotar_naciendo(self, *, turno_id: str, provider: str, binario: str,
                        argv=None, nacido_en: Optional[float] = None) -> bool:
        """ANTES del spawn. Todavía no hay pid: la fila queda `naciendo`."""
        fila = {
            "turno_id": str(turno_id),
            "provider": str(provider or "?"),
            "estado": "naciendo",
            "binario": str(binario or ""),
            "huella": huella_de(argv),
            "pids": [],
            "nacido_en": float(time.time() if nacido_en is None else nacido_en),
        }
        with self._lock:
            filas = [f for f in self.leer() if f.get("turno_id") != fila["turno_id"]]
            filas.append(fila)
            return self.escribir(filas)

    def anotar_pid(self, turno_id: str, pid: int, *, pgid: Optional[int] = None) -> bool:
        """DESPUÉS del spawn. Cierra la fila `naciendo` con el pid real y su grupo."""
        with self._lock:
            filas = self.leer()
            tocada = False
            for f in filas:
                if f.get("turno_id") == str(turno_id):
                    f["pids"] = [int(pid)]
                    f["pgid"] = int(pgid) if pgid is not None else None
                    f["estado"] = "vivo"
                    tocada = True
            if not tocada:
                return False
            return self.escribir(filas)

    def borrar(self, turno_id: str) -> bool:
        """La muerte LIMPIA. El turno terminó y el sidecar sigue vivo: la fila se va."""
        with self._lock:
            filas = self.leer()
            quedan = [f for f in filas if f.get("turno_id") != str(turno_id)]
            if len(quedan) == len(filas):
                return False
            return self.escribir(quedan)

    def vaciar(self) -> bool:
        return self.escribir([])


#: El registro del proceso. Uno solo, por el mismo motivo que el dueño tiene un solo libro.
REGISTRO = RegistroCli()


# ── LOS PROCESOS DEL SISTEMA (mismo instrumental que el barrido del dueño) ──────────
def _vive(pid: int) -> bool:
    """¿Ese pid es un proceso VIVO?

    ⚠️ UN ZOMBIE NO ESTÁ VIVO, y `os.kill(pid, 0)` dice que sí. Acá es el caso normal, no
    un borde: los CLI son hijos nuestros, así que entre que mueren y alguien los cosecha
    quedan en `Z` con su pid todavía en la tabla del kernel.
    """
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True                                        # existe y no es nuestro
    except OSError:
        return False
    try:
        r = subprocess.run(["ps", "-o", "state=", "-p", str(int(pid))],
                           capture_output=True, text=True, timeout=5)
        estado = (r.stdout or "").strip()
        if estado and estado[0].upper() == "Z":
            return False
    except (OSError, subprocess.SubprocessError):
        pass                                               # sin `ps`, vale el `kill(0)`
    return True


def _comando_y_arranque(pid: int) -> tuple:
    """`(command, epoch_de_arranque)` de un pid, o `("", None)`.

    `-ww` para que `ps` no trunque: nuestro argv lleva el prompt y la línea puede ser
    larguísima, y una huella cortada haría fallar la identidad de un proceso NUESTRO.
    """
    try:
        r = subprocess.run(["ps", "-ww", "-o", "lstart=,command=", "-p", str(int(pid))],
                           capture_output=True, text=True, timeout=5)
    except (OSError, ValueError, subprocess.SubprocessError):
        return "", None
    linea = (r.stdout or "").strip()
    if not linea:
        return "", None
    partes = linea.split(None, 5)
    if len(partes) < 6:
        return linea, None
    fecha, comando = " ".join(partes[:5]), partes[5]
    try:
        # `ps lstart` da hora LOCAL. `mktime` es la conversión local→epoch y ya resuelve el
        # horario de verano; hacerla a mano con `timegm` + `time.timezone` da una hora de
        # diferencia media parte del año — y una hora de diferencia acá significa declarar
        # «pid reciclado» a un proceso nuestro y NO barrerlo (lección del barrido D1).
        ts = time.mktime(time.strptime(fecha, "%a %b %d %H:%M:%S %Y"))
    except (ValueError, OverflowError, OSError):
        ts = None
    return comando, ts


def identidad_ok(fila: dict, comando_ps: str, arranque: Optional[float]) -> tuple:
    """¿La línea de `ps` es EL proceso que anotamos? `(bool, motivo_si_no)`.

    TRES condiciones, y las tres son obligatorias. Es más estricto que el barrido del
    dueño a propósito: el dueño mata servidores MCP, que nadie más lanza; acá el binario
    se llama `claude` y **la persona lo tiene abierto en otra terminal**. Un chequeo que
    dijera «el basename coincide» mataría la sesión del usuario.

      1. el BINARIO — su basename aparece en la línea de `ps`;
      2. la HUELLA — TODOS los flags que anotamos están en la línea (nadie los tipea);
      3. la HORA — ventana de ±`TOLERANCIA_S` contra `nacido_en`.

    Si la hora no se pudo leer, el chequeo fuerte no está disponible y la respuesta es que
    NO — «no sé» es una respuesta, y del lado seguro.
    """
    bajo = (comando_ps or "").lower()
    if not bajo:
        return False, "sin_comando"
    base = os.path.basename(str(fila.get("binario") or "")).lower()
    if not base or base not in bajo:
        return False, "otro_binario"
    huella = [str(h) for h in (fila.get("huella") or [])]
    if not huella:
        # Sin huella no hay identidad de comando, y el basename solo no alcanza: podría
        # ser el `claude` de la persona. Se reporta y no se toca.
        return False, "sin_huella"
    faltan = [h for h in huella if h.lower() not in bajo]
    if faltan:
        return False, "otra_huella"
    nacido = fila.get("nacido_en")
    try:
        nacido = float(nacido)
    except (TypeError, ValueError):
        return False, "sin_hora_anotada"
    if arranque is None:
        return False, "sin_hora_de_ps"
    if abs(float(arranque) - nacido) > TOLERANCIA_S:
        return False, "pid_reciclado"
    return True, ""


def _senal(pid: int, sig: int) -> bool:
    """SIGTERM/SIGKILL al GRUPO si el pid es líder de su propia sesión, si no al pid solo.

    Todos nuestros spawns usan `start_new_session=True`, así que el pid ES su pgid y matar
    el grupo se lleva también a los nietos (el `claude` lanza node/hijos). Si el pid resulta
    NO ser líder de grupo, el grupo es de otro y mandarle una señal sería un desastre: se
    degrada a matar el pid solo.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        if os.name == "posix" and os.getpgid(pid) == pid:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def barrer_cli_al_arrancar(*, registro: Optional[RegistroCli] = None) -> dict:
    """Mata los CLI que dejó vivos un sidecar anterior. Devuelve el parte.

    **NO readopta**, igual que el barrido del dueño: los pipes stdout/stderr murieron con
    el padre, así que a ese `claude -p` no se le puede volver a leer la respuesta. Lo único
    honesto es terminarlo — sigue quemando la ventana de la suscripción por una respuesta
    que ya nadie va a recibir.

    NO ESTÁ CABLEADA AL ARRANQUE, a propósito: el arranque es de `main.py::_lifespan`, que
    es del backend y está fuera de `cli_brain/`. PROPUESTA, con el punto exacto — en
    `product/backend/app/main.py`, en la zona que va desde el `try` del barrido del dueño
    (`dueno.actual().barrer_al_arrancar()`) hasta la línea `purge_task = ...`; el lugar
    natural es **inmediatamente antes de `purge_task = ...`**, después del enganche de
    repair que R3 dejó ahí. Misma forma que sus vecinos: fuera del `if db_ok` (un CLI
    huérfano no depende de que la base esté sana, y dejarlo vivo porque la DB está rota
    sería sumar una fuga a un fallo) y dentro de un `try/except` que jamás tumba el boot:

        try:
            from cli_brain.registro import barrer_cli_al_arrancar
            _p = barrer_cli_al_arrancar()
            if _p.get("matados") or _p.get("ajenos") or _p.get("sin_pid"):
                print(f"[cli_brain] barrido de arranque: {_p}", flush=True)
        except Exception as exc:  # noqa: BLE001 — el boot no se cae por esto
            print(f"[cli_brain] barrido de arranque NO corrió: {exc}", flush=True)

    `{"anotados", "muertos_ya", "ajenos", "sin_pid", "matados", "motivos": {...}}`
    """
    reg = registro if registro is not None else REGISTRO
    parte = {"anotados": 0, "muertos_ya": 0, "ajenos": 0, "sin_pid": 0, "matados": 0,
             "motivos": {}}
    #: SÓLO los que NOSOTROS señalamos. La escalada a SIGKILL se hace sobre esta lista y
    #: JAMÁS sobre las filas: el peor fallo posible de un barrido es mandarle un -9 al pid
    #: que se acaba de descartar por ajeno.
    señalados: list = []
    filas = reg.leer()
    parte["anotados"] = len(filas)
    for fila in filas:
        pids = [p for p in (fila.get("pids") or []) if isinstance(p, int)]
        if not pids:
            parte["sin_pid"] += 1
            print(f"[cli_brain] entrada sin pid: turno «{fila.get('turno_id')}» "
                  f"({fila.get('provider')}). Si dejó un proceso, NO lo barro: matar por "
                  f"nombre podría matar a un tercero.", file=sys.stderr, flush=True)
            continue
        for pid in pids:
            if not _vive(pid):
                parte["muertos_ya"] += 1
                continue
            comando, arranque = _comando_y_arranque(pid)
            ok, motivo = identidad_ok(fila, comando, arranque)
            if not ok:
                parte["ajenos"] += 1
                parte["motivos"][motivo] = parte["motivos"].get(motivo, 0) + 1
                continue
            if _senal(pid, signal.SIGTERM):
                señalados.append(pid)
                parte["matados"] += 1
    if señalados:
        time.sleep(GRACIA_BARRIDO_S)
        for pid in señalados:                              # SÓLO los señalados
            if _vive(pid):
                _senal(pid, signal.SIGKILL)
    # El archivo es del arranque anterior: después del barrido no describe nada. Se vacía
    # aunque haya filas ajenas — dejarlas haría que el PRÓXIMO arranque las volviera a
    # evaluar contra un pid que para entonces puede ser de un tercero más.
    reg.vaciar()
    return parte


__all__ = ["RegistroCli", "REGISTRO", "NOMBRE", "TOLERANCIA_S",
           "huella_de", "identidad_ok", "barrer_cli_al_arrancar"]
