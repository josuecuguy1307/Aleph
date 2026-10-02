"""
transporte_sdk.py — EL PUENTE sync↔async al SDK oficial de MCP.

    PIN EXACTO (sesión 1, 2026-08-02) — `==`, jamás `>=`:
        mcp==2.0.0
        mcp-2.0.0-py3-none-any.whl · 349.980 bytes
        sha256 1cb4c75d2d2c7b8c1d756355e5d82a39f2822cc7f13e22a2051d7ca3592349d6

    2.0.0 es la ÚNICA versión publicada de la línea 2.x. Desde la SESIÓN 2 está en
    `product/backend/requirements.txt`, porque este módulo pasó a ser el camino real.

QUÉ ES. El SDK oficial es **async-only**. Nuestro cliente MCP no tiene un solo `async def`
—hilos, `select`, `Popen`— y sus consumidores (verificador, motor de verdad, remedios,
restauración) son todos sync. Este módulo es la ÚNICA frontera entre los dos mundos: expone
hacia afuera la MISMA interfaz sync que hoy ofrecen `assembler.MCPServer` (stdio) y
`mcp_http_client.MCPHttpClient` (HTTP), y corre el SDK async adentro.

**EL ASYNC NO SALE DE ACÁ.** Ni un `await` cruza la frontera. Si algún día un consumidor
tiene que escribir `async def` para hablar con un MCP, este puente falló y hay que arreglar
el puente, no propagar el color de la función por 79 llamadas del backend.

ES EL CAMINO REAL DESDE LA SESIÓN 2, y el viejo NO se borró. `assembler.MCPServer` y
`MCPHttpClient` quedan en el árbol, sin consumidores de producto, como **rollback**: quién
habla lo decide `transporte.py` con `ALEPH_TRANSPORTE` (`auto` · `sdk` · `viejo`). Borrarlos
es otra sesión, después de una regresión total.

── LA DECISIÓN: PORTAL DE ANYIO, UNO POR CONEXIÓN ───────────────────────────────────
Las dos formas de meter un loop async debajo de una interfaz sync son un **portal**
(`anyio.from_thread.start_blocking_portal`) o un **loop propio por conexión**
(`asyncio.new_event_loop()` en un hilo + `run_coroutine_threadsafe`). Se eligió el portal:

1. **Los cancel scopes de anyio son POR TAREA.** El `__aexit__` de `stdio_client` y de
   `ClientSession` TIENE que correr en la misma tarea que hizo el `__aenter__`; si no,
   anyio levanta «Attempted to exit cancel scope in a different task». Una conexión MCP
   vive abierta entre muchas llamadas sync (initialize · list_tools · N × call_tool ·
   close), así que enter y exit caen en llamadas distintas del hilo llamante. El portal
   resuelve esto de fábrica —`wrap_async_context_manager` sostiene TODO el context manager
   en UNA tarea del portal—; con `run_coroutine_threadsafe` sobre un loop crudo hay que
   escribir a mano la tarea-guardiana que sostiene el `__aenter__` y coordinar el
   `__aexit__` desde otro hilo. **Ese es exactamente el paso donde un puente a mano deja
   procesos huérfanos**, y huérfanos es el problema que veníamos a cerrar.
2. **anyio ya es dependencia NUESTRA** (`product/backend/requirements.txt`) y del SDK.
   Cero peso nuevo por elegir el portal; escribir el loop a mano no ahorra ni un byte.
3. **Un portal POR CONEXIÓN** conserva el aislamiento que hoy da un `Popen` por server: un
   server que cuelga no puede bloquear a otro, y cerrar uno no toca a los demás. Un portal
   global compartido convertiría un `call_tool` colgado en una parada de todo el pool.

Costo: un hilo por conexión viva. Es el MISMO orden que hoy — `MCPServer` ya levanta un
hilo por server para drenar stderr.

── LO QUE EL SDK HACE MEJOR QUE NOSOTROS: EL CIERRE ─────────────────────────────────
`_stop_server_process` cierra stdin, espera 2 s, y si el hijo sigue vivo manda **SIGTERM al
GRUPO de procesos** (el hijo se spawnea con `start_new_session=True`, o sea que es líder de
su propio grupo) y SIGKILL 2 s después. Nuestro `MCPServer.stop()` hace `proc.terminate()`
al hijo DIRECTO nada más: un `uvx` que a su vez levanta un `python` deja el nieto huérfano.
Ésa es la razón principal para mirar el SDK, y está verificada contra un server real
(ver `verify_transporte_sdk.py`, caso «árbol muerto»).

── LO QUE NOSOTROS HACEMOS MEJOR Y NO SE ENTREGA ────────────────────────────────────
`get_default_environment()` del SDK copia SEIS variables (`HOME LOGNAME PATH SHELL TERM
USER`) y `stdio_client` las funde con las nuestras como `default | env`. Nuestro entorno
de spawn es otra cosa: el PATH REAL del usuario resuelto en el boot del sidecar
(`deploy/fase4/sidecar_serve.py::ensure_user_path`, que une el PATH del login-shell con
homebrew/nvm/pyenv) más `PUPPET_BELTS`/`PUPPET_REPO`/`PUPPET_WORKDIR` y la credencial
expandida. **El PATH del hijo sale de Aleph SIEMPRE**: se pisa DESPUÉS de armar el entorno,
nunca antes, así el merge del SDK no puede devolvernos el PATH mínimo de launchd —que es
justo el bug que `ensure_user_path` vino a cerrar (la vitrina vaciada en Finder).

── EL HUECO DEL SDK QUE HAY QUE SABER: `exit_code` ──────────────────────────────────
`stdio_client` **no expone el proceso**: hace `yield read_stream, write_stream` y se queda
el `Process` en el closure. No hay `.returncode` ni `.pid` públicos. Nuestro
`diagnostico()` publica `exit_code`, y el contrato de `MCPServer` es explícito en que
`None` significa «seguía vivo» y JAMÁS se convierte en un cero inventado. Acá `exit_code`
es `None` SIEMPRE, con `exit_code_fuente` diciendo por qué, y en su lugar se publica lo que
sí se puede medir: `murio`, que sale del EOF del pipe de stderr (el pipe se cierra cuando
muere el último proceso que lo tiene abierto). Es un dato distinto y se llama distinto.

Correr las pruebas:  python3 platform/inspection/verify_transporte_sdk.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from collections import deque
from typing import Any, Optional

# ── FALLO VISIBLE, JAMÁS MUDO (CLAUDE.md §1) ────────────────────────────────────────
# El SDK es una dependencia nueva y todavía no viaja en todos los entornos. Un
# `except ImportError: pass` acá haría que el puente "exista" y devuelva vacío, que es
# la forma exacta de un fake-live. Se registra la ausencia y se levanta al construir.
try:
    import anyio
    from anyio.from_thread import BlockingPortal, start_blocking_portal
    from mcp import ClientSession, StdioServerParameters, stdio_client
    from mcp.client.stdio import get_default_environment
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.exceptions import MCPError
    # ⚠️ `LATEST_HANDSHAKE_VERSION`, NO `LATEST_PROTOCOL_VERSION`. Son distintas y la
    # diferencia es la que se publica como evidencia: `initialize()` manda la PRIMERA
    # (`session.py:619`, medido: 2025-11-25); la segunda es la revisión más nueva que el
    # SDK conoce (2026-07-28) y sólo se usa en el camino de `server/discover`. Poner la
    # equivocada en `protocolo.solicitada` era anotar que pedimos algo que nunca pedimos.
    from mcp.client.session import LATEST_HANDSHAKE_VERSION as _VERSION_SOLICITADA
    _SDK_ERROR = ""
except Exception as _e:                                   # noqa: BLE001 — frontera de import
    anyio = None                                          # type: ignore[assignment]
    BlockingPortal = object                               # type: ignore[misc,assignment]
    ClientSession = StdioServerParameters = None          # type: ignore[assignment]
    stdio_client = streamable_http_client = None          # type: ignore[assignment]
    get_default_environment = None                        # type: ignore[assignment]
    MCPError = RuntimeError                               # type: ignore[misc,assignment]
    _VERSION_SOLICITADA = ""                              # type: ignore[assignment]
    _SDK_ERROR = f"{type(_e).__name__}: {_e}"


def sdk_disponible() -> tuple[bool, str]:
    """`(hay_sdk, motivo)`. El motivo se muestra; no se traga."""
    return (not _SDK_ERROR), _SDK_ERROR


_traductor_mod = None


def _traductor():
    """`traductor_errores` — perezoso y cacheado. Es PURO (no importa `mcp`), así que
    cargarlo nunca puede ser lo que rompa el puente."""
    global _traductor_mod
    if _traductor_mod is None:
        _aqui = os.path.dirname(os.path.abspath(__file__))
        if _aqui not in sys.path:
            sys.path.append(_aqui)
        import traductor_errores as _t                      # noqa: E402
        _traductor_mod = _t
    return _traductor_mod


class TransporteSdkError(Exception):
    """Falla de transporte/protocolo hablando por el SDK. Misma forma que `MCPHttpError`:
    mensaje legible + `evidencia` acotada, porque los diagnósticos viven de eso."""

    def __init__(self, message: str, *, evidencia: Optional[dict] = None):
        super().__init__(message)
        self.evidencia = dict(evidencia or {})


# ── 1 · EL ENTORNO DEL HIJO ES NUESTRO ──────────────────────────────────────────────

def path_de_aleph() -> str:
    """El PATH que Aleph resolvió para el usuario, no el que heredó el proceso.

    `ensure_user_path()` corre en el boot del sidecar y funde el PATH real en
    `os.environ` — o sea que leer `os.environ["PATH"]` YA da el bueno cuando corremos
    dentro de la app. Se lo llama igual (es idempotente y cacheado) para que el puente
    también acierte fuera del sidecar: en un test, en un script, en el verificador suelto.
    Si el módulo no está importable —no es la app—, se cae al PATH heredado.

    Sólo AGREGA directorios: `resolve_user_path` nunca saca `/usr/bin:/bin`. Por eso
    pisar el PATH del llamante no puede angostarle nada.
    """
    try:
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # …/platform → repo
        fase4 = os.path.join(os.path.dirname(raiz), "deploy", "fase4")
        if os.path.isdir(fase4) and fase4 not in sys.path:
            sys.path.insert(0, fase4)
        import sidecar_serve as _ss                        # noqa: E402
        return _ss.ensure_user_path() or os.environ.get("PATH", "")
    except Exception:                                      # noqa: BLE001 — best-effort
        return os.environ.get("PATH", "")


class _ScopedChildEnv(dict):
    """Keep an undeclared private scratch directory alive with this child env."""

    def __init__(self, *args, scratch_owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._scratch_owner = scratch_owner


def entorno_hijo(env: Optional[dict] = None) -> dict:
    """Build from a small runtime baseline plus only caller-declared MCP variables.

    `None` never means inherit host credentials. Recipe callers already pass their
    filtered per-server env; SDK default keys are explicitly overridden below so
    its own merge cannot reintroduce the sidecar's identity or HOME.
    """
    run_scratch = (env or {}).get("PUPPET_WORKDIR")
    scratch_owner = None
    if run_scratch:
        scratch = str(run_scratch)
    else:
        scratch_owner = tempfile.TemporaryDirectory(prefix="aleph-mcp-runtime-")
        scratch = scratch_owner.name
    base = {"HOME": scratch, "TMPDIR": scratch, "XDG_CACHE_HOME": scratch,
            "USER": "aleph-mcp", "LOGNAME": "aleph-mcp", "SHELL": "/bin/sh",
            "TERM": "dumb", "LANG": "C.UTF-8"}
    if env is not None:
        base.update({str(k): str(v) for k, v in env.items()})
        declared = getattr(env, "declaradas", None)
        if declared is not None:
            for key in ("HOME", "TMPDIR", "XDG_CACHE_HOME"):
                if key not in declared:
                    base[key] = scratch
    base["PATH"] = path_de_aleph()
    return _ScopedChildEnv(base, scratch_owner=scratch_owner)


def fugas_del_sdk(env_final: dict) -> list:
    """Las claves que `get_default_environment()` le INYECTARÍA al hijo por encima del
    entorno que le dimos.

    `stdio_client` arma el env como `get_default_environment() | (server.env or {})`: el
    nuestro gana en las claves que comparte, pero las que NO están en el nuestro se cuelan
    con el valor que tengan en `os.environ`. No hay forma de expresar «esta variable NO va»
    a través de un merge, así que en vez de fingir que el control es total, se MIDE y se
    publica en `diagnostico()`. Los entornos de producto fijan explícitamente
    todas las claves default conocidas del SDK; cualquier clave nueva debe
    verse como fuga en vez de quedar oculta.
    """
    if get_default_environment is None:
        return []
    try:
        return sorted(set(get_default_environment()) - set(env_final))
    except Exception:                                      # noqa: BLE001
        return []


# ── 2 · STDERR DEL HIJO: EL PIPE ES NUESTRO ─────────────────────────────────────────

class _CapturaStderr:
    """Drena el stderr del hijo a una cola acotada, con los MISMOS caps que `MCPServer`.

    `stdio_client(server, errlog=...)` le pasa `errlog` a `anyio.open_process` como
    `stderr=`, o sea que necesita un **descriptor de archivo real**, no un objeto con
    `.write()`. Por eso el puente abre su propio `os.pipe()`: el extremo de escritura se lo
    damos al SDK, del de lectura drena un hilo nuestro. Sin esto el stderr del hijo se iría
    al stderr del sidecar (el default del SDK) y los diagnósticos —que viven de ese
    texto— se quedarían mudos.

    El drenaje es concurrente a propósito: un pipe sin lector llena el buffer del kernel y
    cuelga al propio MCP. Es la misma razón por la que `MCPServer` usa un hilo y no lee al
    final.
    """

    MAX_BYTES = 32 * 1024        # idénticos a MCPServer.STDERR_MAX_BYTES
    MAX_LINEAS = 80              # idénticos a MCPServer.STDERR_MAX_LINES

    def __init__(self, nombre: str, on_muerte=None):
        self._lineas: deque = deque()
        self._bytes = 0
        self._lock = threading.Lock()
        self._murio = threading.Event()
        #: R1 · el INSTANTE del EOF. `murio` decía QUE murió; esto dice CUÁNDO, y sin el
        #: cuándo no se puede correlacionar una muerte con el timeout que la precedió — que
        #: es toda la trampa del fantasma (§6 del DISEÑO-REPAIR-v1).
        self._t_eof: Optional[float] = None
        #: R1 · el aviso PUSH. Lo pone el dueño antes de `start()`. Sin suscriptor, `None` y
        #: esto se comporta exactamente como antes.
        self._on_muerte = on_muerte
        r, w = os.pipe()
        self._r = r
        self._errlog = os.fdopen(w, "w", buffering=1, errors="replace")
        self._hilo = threading.Thread(target=self._drenar, name=f"sdk-stderr-{nombre}",
                                      daemon=True)
        self._hilo.start()

    @property
    def errlog(self):
        """El extremo de ESCRITURA, que es lo que el SDK quiere."""
        return self._errlog

    @property
    def murio(self) -> bool:
        """EOF en el pipe = ya no queda nadie del árbol con el stderr abierto.

        No es el exit code y no se disfraza de uno. Es lo único observable sobre la muerte
        del hijo cuando el transporte no expone el proceso.
        """
        return self._murio.is_set()

    @property
    def t_eof(self) -> Optional[float]:
        """El instante del EOF, o `None` si todavía no pasó. R1."""
        return self._t_eof

    def soltar_escritura(self) -> None:
        """Cierra NUESTRA copia del extremo de escritura, apenas el hijo tiene la suya.

        Un pipe da EOF cuando se cierra el ÚLTIMO descriptor de escritura. Mientras el
        puente conservara el suyo, `murio` no podía dispararse hasta el `stop()` — o sea
        que un server que se cayó a mitad de sesión se veía exactamente igual que uno vivo,
        que es justo el dato que el diagnóstico necesita. Medido: `os._exit(7)` en el hijo
        dejaba `murio=False`. Se llama DESPUÉS del spawn: para entonces el hijo ya tiene su
        propio duplicado del fd y cerrar el nuestro no lo deja sin stderr.
        """
        try:
            self._errlog.close()
        except Exception:                                  # noqa: BLE001
            pass

    def _drenar(self) -> None:
        try:
            with os.fdopen(self._r, "rb") as f:
                for raw in f:
                    linea = raw.decode("utf-8", "replace").rstrip("\r\n")
                    size = len(linea.encode("utf-8", "replace")) + 1
                    with self._lock:
                        self._lineas.append((linea, size))
                        self._bytes += size
                        while (len(self._lineas) > self.MAX_LINEAS
                               or self._bytes > self.MAX_BYTES):
                            _v, viejo = self._lineas.popleft()
                            self._bytes -= viejo
        except Exception:                                  # noqa: BLE001 — el pipe se cerró
            pass
        finally:
            self._t_eof = time.time()
            self._murio.set()
            # R1 · EL AVISO SALE ACÁ, en el instante del EOF — que es lo más cerca de «el
            # hijo murió» que este transporte puede estar (`stdio_client` no expone el
            # proceso). Antes de R1 este dato existía y no lo consumía nadie: el dueño se
            # enteraba recién cuando ALGUIEN VOLVÍA A PEDIR (`dueno.py`, `_parece_muerta`
            # dentro de `pedir()`), o sea que una muerte con nadie pidiendo no se enteraba
            # nadie. Ese es el hueco que R1 cierra.
            #
            # Va envuelto porque esto corre en un HILO DAEMON: una excepción del suscriptor
            # acá se perdería sin traza y, peor, dejaría el hilo muerto sin drenar el pipe.
            if self._on_muerte is not None:
                try:
                    self._on_muerte(self._t_eof)
                except Exception:                          # noqa: BLE001 — frontera del aviso
                    pass

    def texto(self) -> tuple:
        with self._lock:
            return ("\n".join(l for l, _s in self._lineas), len(self._lineas), self._bytes)

    def cerrar(self) -> None:
        """Se cierra NUESTRO extremo de escritura. El del hijo lo cierra el kernel al morir;
        mientras uno de los dos siga abierto el lector no ve EOF."""
        try:
            self._errlog.close()
        except Exception:                                  # noqa: BLE001
            pass
        self._hilo.join(timeout=0.5)


# ── 3 · EL PUENTE ───────────────────────────────────────────────────────────────────

class _Puente:
    """Portal + sesión. Todo lo async de este archivo vive acá adentro."""

    def __init__(self) -> None:
        hay, motivo = sdk_disponible()
        if not hay:
            raise TransporteSdkError(
                f"el SDK de MCP no está disponible en este entorno: {motivo}",
                evidencia={"dependencia": "mcp==2.0.0", "detalle": motivo})
        self._portal_cm = None
        self._portal: Optional[BlockingPortal] = None
        self._cm = None
        self._sesion = None

    # -- ciclo de vida --------------------------------------------------------------
    def _abrir_portal(self) -> BlockingPortal:
        self._portal_cm = start_blocking_portal(backend="asyncio")
        self._portal = self._portal_cm.__enter__()
        return self._portal

    def _entrar(self, cm_async) -> Any:
        """Sostiene un context manager async COMPLETO dentro de UNA tarea del portal y
        devuelve lo que produce. Éste es el motivo de existir del portal: el `__aexit__`
        va a correr en la misma tarea que el `__aenter__`."""
        self._cm = self._portal.wrap_async_context_manager(cm_async)
        self._sesion = self._cm.__enter__()
        return self._sesion

    def _cerrar(self) -> None:
        """Se desarma en orden inverso y NADA puede quedar a medias: si el `__exit__` del
        CM explota (un server que ya no responde), el portal se cierra igual — un portal
        colgado es un hilo colgado por cada conexión rota."""
        try:
            if self._cm is not None:
                self._cm.__exit__(None, None, None)
        except Exception:                                  # noqa: BLE001
            pass
        finally:
            self._cm = None
            self._sesion = None
            try:
                if self._portal_cm is not None:
                    self._portal_cm.__exit__(None, None, None)
            except Exception:                              # noqa: BLE001
                pass
            finally:
                self._portal_cm = None
                self._portal = None

    def _llamar(self, func, *args, **kwargs):
        """Una corrutina del SDK, ejecutada desde el hilo llamante. Bloquea, como todo lo
        demás en el camino sync."""
        if self._portal is None:
            raise TransporteSdkError("el puente no está abierto")
        import functools
        return self._portal.call(functools.partial(func, *args, **kwargs))


# ── 4 · STDIO — espeja `assembler.MCPServer` ────────────────────────────────────────

class ServidorSDK:
    """Un server MCP por stdio, con la interfaz de `MCPServer`.

    Mismos nombres, mismos tipos de retorno, mismas cadenas de error: los consumidores no
    pueden notar la diferencia. `call_tool` devuelve un STRING con los prefijos
    `[MCP error: …]` / `[tool error] …` porque eso es lo que `_llamar()` del verificador
    guarda como evidencia y lo que `_clasificar()` después lee.
    """

    STDERR_MAX_BYTES = _CapturaStderr.MAX_BYTES
    STDERR_MAX_LINES = _CapturaStderr.MAX_LINEAS

    def __init__(self, name: str, command: str, args: list, env: Optional[dict] = None,
                 rpc_timeout: float = 30.0, cwd: Optional[str] = None):
        self.name = name
        # MISMA REGLA QUE EL EJECUTOR VIEJO (`assembler.MCPServer`), y tiene que ser la
        # misma: los dos transportes lanzan las mismas recetas, y `ALEPH_TRANSPORTE` no
        # puede cambiar si una pieza HTTP del usuario arranca o no. Ver `puente_sidecar`.
        import puente_sidecar
        self._cmd = puente_sidecar.normalizar_cmd([command] + list(args or []))
        self._env_pedido = env
        self._cwd = cwd
        self._rpc_timeout = max(0.1, float(rpc_timeout))
        self._puente = _Puente()
        self._cap: Optional[_CapturaStderr] = None
        self._start_error = ""
        #: aviso de UN disparo: «el hijo ya nació, el handshake todavía no». Ver `al_spawnear`.
        self._al_spawnear = None
        self._protocolo: dict = {}
        self._env_final: dict = {}
        self._fugas: list = []
        self._server_info: dict = {}
        self._respuesta: Optional[dict] = None
        self._vivo = False
        self._on_muerte = None
        #: R1 · LA TRAMPA DEL FANTASMA (§6). Los disparos de timeout de ESTE server, en
        #: orden. Acotada: un server que timeoutea en loop no puede comerse la memoria.
        self._timeouts: deque = deque(maxlen=self.TIMEOUTS_MAX)

    #: Cuántos disparos de timeout se recuerdan por server.
    TIMEOUTS_MAX = 20

    def al_morir(self, fn) -> None:
        """Registra el aviso PUSH de muerte. **Hay que llamarlo ANTES de `start()`**: el
        `_CapturaStderr` —que es quien ve el EOF— se construye ahí dentro.

        Existe para que el dueño se entere de una muerte SIN QUE NADIE PIDA (R1). Es
        opcional: sin llamarlo, este server se comporta exactamente como antes de R1.
        """
        self._on_muerte = fn

    def _anotar_timeout(self, operacion: str, transcurrido: float, exc: BaseException) -> None:
        """R1 · anota un disparo de timeout: CUÁNDO, QUIÉN, CUÁL de los dos y CUÁNTO tardó.

        ⚠️ **SE CLASIFICA POR EL RELOJ, NO POR EL TIPO DE EXCEPCIÓN**, y la vara mostró por
        qué no es una preferencia de estilo: el SDK sintetiza el vencimiento de
        `read_timeout_seconds` como un **`McpError`** —el mismo tipo con el que un server
        contesta un error de verdad—. Una primera versión de esto anotaba sólo la rama
        `except Exception` «porque un `MCPError` significa que el server contestó», y el
        resultado fue medido: con un server dormido y un reloj de 1,5 s, la llamada tardó
        1,50 s y **no se anotó nada**. El tipo no distingue quién dijo «se acabó el tiempo».
        El reloj sí.

        Por eso sólo se anota cuando el reloj EFECTIVAMENTE venció: un `McpError` contestado
        en 200 ms es el server hablando y no ensucia la señal; uno a los 1,5 s de un reloj de
        1,5 s es el reloj. El 10 % de tolerancia es holgura de scheduler, no un umbral fino:
        lo que se separa es «venció» de «falló rápido», y esos dos no se tocan.
        """
        limite = self._rpc_timeout
        if transcurrido < limite * 0.9:
            return                        # falló por otra cosa: no es un disparo de reloj
        self._timeouts.append({
            "ts": time.time(),
            "quien": self.name,
            "operacion": operacion,
            "timeout_s": limite,          # 30 = el del run · 45 = el de la sonda
            "transcurrido_s": round(transcurrido, 3),
            "vencio_el_reloj": True,
            "excepcion": _forma(exc)[:200],
        })

    @property
    def timeouts(self) -> list:
        """Los disparos anotados. Los lee `diagnostico()` y, por ahí, el evento de muerte."""
        return list(self._timeouts)

    # -- arranque -------------------------------------------------------------------
    def al_spawnear(self, fn) -> None:
        """Callback de UN disparo: el hijo ya existe, el `initialize` todavía no corrió.

        Lo usa el dueño para cerrar su diff de pids sin sostener el lock global durante el
        handshake. Mismo patrón que `al_morir`, y por el mismo motivo: el transporte sabe
        el instante y sin avisarlo lo tira."""
        self._al_spawnear = fn

    def start(self) -> bool:
        """`True` si el handshake completo salió bien. Nunca levanta: el contrato de
        `MCPServer.start()` es devolver un bool y dejar el porqué en `diagnostico()`."""
        try:
            self._env_final = entorno_hijo(self._env_pedido)
            self._fugas = fugas_del_sdk(self._env_final)
            if self._fugas:
                raise TransporteSdkError(
                    "SDK MCP introduciría variables ambientales no autorizadas",
                    evidencia={"variables": self._fugas},
                )
            self._cap = _CapturaStderr(self.name, on_muerte=self._on_muerte)
            params = StdioServerParameters(
                command=self._cmd[0], args=self._cmd[1:],
                env=self._env_final, cwd=self._cwd,
            )
            self._puente._abrir_portal()

            # El CM completo —transporte + sesión— en UNA tarea del portal.
            import contextlib

            @contextlib.asynccontextmanager
            async def _conexion():
                async with stdio_client(params, errlog=self._cap.errlog) as (read, write):
                    async with ClientSession(read, write,
                                             read_timeout_seconds=self._rpc_timeout) as s:
                        yield s

            self._puente._entrar(_conexion())
            # El hijo ya está spawneado y tiene su propio duplicado del fd: soltamos el
            # nuestro para que `murio` pueda dispararse EN VIVO, no recién al cerrar.
            self._cap.soltar_escritura()
            # ── EL AVISO DE NACIMIENTO (paso 6 · el cinturón) ─────────────────────
            # Acá —y sólo acá— el proceso hijo YA EXISTE y el `initialize` todavía no
            # empezó. Es la costura que el dueño necesita para cerrar su diff de pids y
            # soltar su lock ANTES de esperar el handshake, que es lo caro.
            #
            # MEDIDO: sin esto, `dueno._LOCK_DIFF_PIDS` cubría `start()` ENTERO y los ocho
            # servers del cinturón arrancaban EN FILA — sus lanzadores nacían de +4,38 s a
            # +38,39 s (34 s de spread) contra 1,19 s con el dueño apagado. El
            # `ThreadPoolExecutor(8)` del restaurador estaba, y este lock lo anulaba.
            #
            # Nunca levanta: un avisador roto no puede tumbar un arranque que salió bien.
            if self._al_spawnear is not None:
                try:
                    self._al_spawnear()
                except Exception:                          # noqa: BLE001 — frontera
                    pass
            init = self._puente._llamar(self._puente._sesion.initialize)
            # El bloque `protocolo` lo arma el traductor, NO este módulo. Motivo medido:
            # `diagnostico_conectores` deduce incompatibilidad de `cliente != servidor`, y
            # el SDK pide siempre la última revisión y baja a la que el server ofrezca —
            # así que reportar «pedí X, me dieron Y» sobre un handshake EXITOSO etiquetaba
            # `deriva_protocolo` cualquier fallo posterior. Ver `traductor_errores.protocolo_de`.
            self._protocolo = _traductor().protocolo_de(
                negociada=init.protocol_version, solicitada=_VERSION_SOLICITADA)
            self._server_info = init.server_info.model_dump(by_alias=True, exclude_none=True)
            self._vivo = True
            return True
        except Exception as e:                             # noqa: BLE001 — frontera del puente
            self._start_error = f"no pude iniciar el proceso MCP por el SDK: {_forma(e)}"
            self._registrar_rechazo(e)
            self.stop()
            return False

    def _registrar_rechazo(self, e: BaseException) -> None:
        """La evidencia de protocolo cuando el saludo se RECHAZA.

        MEDIDO como regresión del recableo: sin esto, un servidor que contesta
        `-32022 UnsupportedProtocolVersion` perdía el diagnóstico `deriva_protocolo` y caía
        a `no_habla_mcp`. El cliente viejo sí lo capturaba (`_record_protocol_response`), o
        sea que el puente estaba DEGRADANDO un veredicto — exactamente lo que la regla
        madre prohíbe. `data.requested`/`data.supported` son normativos desde la revisión
        2026-07-28 y es el único caso en que hablar de deriva es honesto.
        """
        raiz = e
        visto = 0
        while isinstance(raiz, BaseExceptionGroup) and raiz.exceptions and visto < 8:
            raiz = raiz.exceptions[0]
            visto += 1
        if not isinstance(raiz, MCPError):
            return
        self._respuesta = {"error": raiz.error.model_dump(exclude_none=True)}
        if raiz.error.code != _traductor().PROTOCOLO_NO_SOPORTADO:
            return
        data = raiz.error.data if isinstance(raiz.error.data, dict) else {}
        self._protocolo = _traductor().protocolo_de(
            solicitada=data.get("requested") or _VERSION_SOLICITADA,
            incompatible=True, soportadas=data.get("supported") or [])

    # -- operaciones ----------------------------------------------------------------
    def list_tools(self) -> list:
        if not self._vivo:
            return []
        _t0 = time.monotonic()
        try:
            res = self._puente._llamar(self._puente._sesion.list_tools)
            return [t.model_dump(by_alias=True, exclude_none=True) for t in res.tools]
        except Exception as e:                             # noqa: BLE001 — igual que MCPServer
            self._anotar_timeout("list_tools", time.monotonic() - _t0, e)
            return []

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """El MISMO string que devuelve `MCPServer.call_tool`, error por error."""
        if not self._vivo:
            return f"[MCP error: no response from {self.name}]"
        _t0 = time.monotonic()
        try:
            res = self._puente._llamar(self._puente._sesion.call_tool, tool_name,
                                       arguments or {})
        except MCPError as e:                              # el server contestó… ¿o venció?
            # ⚠️ ACÁ TAMBIÉN SE ANOTA, y es lo que la vara corrigió: el SDK sintetiza el
            # vencimiento de `read_timeout_seconds` como un `McpError`, o sea con el MISMO
            # tipo que usa un server para contestar un error real. `_anotar_timeout` filtra
            # por el reloj: si contestó rápido no anota nada, si tardó lo que dura el
            # timeout lo anota. El tipo no distingue; el reloj sí.
            self._anotar_timeout(f"call_tool:{tool_name}", time.monotonic() - _t0, e)
            return f"[MCP error: {e.error.model_dump(exclude_none=True)}]"
        except Exception as e:                             # noqa: BLE001 — transporte/timeout
            self._anotar_timeout(f"call_tool:{tool_name}", time.monotonic() - _t0, e)
            return f"[MCP error: {_forma(e)}]"
        textos = [c.text for c in (res.content or []) if getattr(c, "type", "") == "text"]
        crudo = "\n".join(textos) if textos else _json(res)
        return f"[tool error] {crudo}" if getattr(res, "is_error", False) else crudo

    def stop(self) -> None:
        """Cierre del SDK: stdin → 2 s → SIGTERM AL GRUPO → 2 s → SIGKILL → reap."""
        self._vivo = False
        self._puente._cerrar()
        if self._cap is not None:
            self._cap.cerrar()

    # -- evidencia ------------------------------------------------------------------
    def diagnostico(self) -> dict:
        """La MISMA forma que `MCPServer.diagnostico()`, con las diferencias declaradas.

        `exit_code` es `None` SIEMPRE y dice por qué: `stdio_client` no expone el proceso.
        Inventar un cero acá sería exactamente el pecado que el contrato de `MCPServer`
        prohíbe. Lo que sí se puede medir se publica aparte, con otro nombre.
        """
        stderr, lineas, size = self._cap.texto() if self._cap else ("", 0, 0)
        if os.environ.get("ALEPH_DIAGNOSTICO_DESCARTAR_STDERR", "").strip() == "1":
            stderr = ""                                    # mismo knob de calibración negativa
        out = {
            "stderr": stderr,
            "exit_code": None,
            "exit_code_fuente": "no expuesto: stdio_client (mcp 2.0.0) hace "
                                "`yield read_stream, write_stream` y se queda el Process",
            "murio": bool(self._cap and self._cap.murio),
            # R1 · el CUÁNDO del EOF y los disparos de timeout de este server. Los dos son
            # para la trampa del fantasma (§6): sin el instante no se puede decir si la
            # muerte siguió a un timeout, y sin los disparos no se puede decir CUÁL de los
            # dos relojes (30 s del run · 45 s de la sonda) fue.
            "t_eof": (self._cap.t_eof if self._cap else None),
            "timeouts": self.timeouts,
            "rpc_timeout_s": self._rpc_timeout,
            "stderr_lineas": lineas,
            "stderr_bytes": size,
            "stderr_cap_bytes": self.STDERR_MAX_BYTES,
            "stderr_cap_lineas": self.STDERR_MAX_LINES,
            "command": self._cmd[0] if self._cmd else "",
            "transporte": "sdk-stdio",
            "entorno": {"path_de_aleph": self._env_final.get("PATH", ""),
                        "claves": len(self._env_final),
                        "inyectadas_por_el_sdk": self._fugas},
        }
        if self._server_info:
            out["server_info"] = self._server_info
        if self._respuesta is not None:
            # La respuesta CRUDA del rechazo: `diagnostico_conectores` la lee para
            # sacar `requested`/`supported` por su cuenta, igual que con el viejo.
            out["respuesta"] = self._respuesta
        if self._start_error:
            out["detail"] = self._start_error
        if self._protocolo:
            out["protocolo"] = dict(self._protocolo)
        # TRADUCIDO EN LA FUENTE (sesión 2). El puente MIDE y `traductor_errores` TRADUCE,
        # pero la traducción se aplica acá y no en cada consumidor: `restaurador`,
        # `byo_mcp` y cualquier lector futuro leen `diagnostico()` sin saber qué transporte
        # les tocó, y olvidarse de traducir en UNO de ellos sería un diagnóstico degradado
        # que nadie ve. Es idempotente: aplicarla otra vez río abajo no cambia nada
        # (`test_traductor_errores.py::test_el_detalle_ya_canonico_no_se_envuelve_dos_veces`).
        return _traductor().evidencia_de_arranque(out)


# ── 5 · HTTP — espeja `mcp_http_client.MCPHttpClient` ───────────────────────────────

def _transporte_que_recuerda():
    """Un transporte de httpx2 que anota el último status y la última falla de red.

    Existe porque el SDK **aplasta la capa HTTP**: `streamable_http_client` levanta
    `MCPError` y el status y el motivo de red se pierden en el camino. Medido:

        DNS que no resuelve   →  -32000 Connection closed
        puerto cerrado        →  -32000 Connection closed
        HTTP 405 con HTML     →  -32603 Server returned an error response

    Los tres primeros son el MISMO error para el SDK y TRES remedios distintos para el
    usuario. El cliente viejo daba `[Errno 8] nodename nor servname` y `[Errno 61]
    Connection refused` textuales, y `http_status` en la evidencia. Como el `AsyncClient`
    se lo pasamos nosotros (`http_client=`), el transporte también es nuestro y ahí sí se
    puede mirar. **No se toca el cuerpo**: la respuesta es un stream que el SDK todavía
    tiene que leer, y consumirlo acá rompería la sesión. El cuerpo del error sigue siendo
    lo único que no se recupera — está anotado en el mapa de errores.

    Se construye por función (no por `class` a nivel de módulo) porque `httpx2` sólo se
    importa si hay SDK, y este archivo tiene que poder importarse sin él.
    """
    import httpx2

    class _TQR(httpx2.AsyncHTTPTransport):
        def __init__(self):
            super().__init__()
            self.ultimo_status = None
            self.ultima_falla = ""

        async def handle_async_request(self, request):
            try:
                r = await super().handle_async_request(request)
            except Exception as e:                         # noqa: BLE001 — se re-levanta
                self.ultima_falla = f"{type(e).__name__}: {e}"
                raise
            self.ultimo_status = r.status_code
            return r

    return _TQR()


def _TransporteQueRecuerda():                              # noqa: N802 — se usa como clase
    return _transporte_que_recuerda()



class ClienteSdkHttp:
    """Streamable HTTP por el SDK, con la interfaz de `MCPHttpClient`.

    Diferencia MEDIDA y esperada: nuestro cliente a mano pide `2024-11-05` clavado en una
    constante; el SDK negocia la revisión que el server ofrezca (contra `mcp.exa.ai`:
    `2025-11-25`). Las tools y el resultado son los mismos — está verificado lado a lado —,
    pero la versión negociada NO es la misma y el registro la persiste (`era`,
    `version_negociada`). Eso se decide al migrar, no acá.
    """

    def __init__(self, url: str, headers: Optional[dict] = None, *,
                 timeout: float = 45.0, user_agent: str = "puppet-byo-mcp/1.0"):
        if not url or not isinstance(url, str):
            raise TransporteSdkError("URL del MCP vacía o inválida")
        self.url = url.strip()
        self.extra_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self.timeout = float(timeout)
        self.user_agent = user_agent
        self.session_id: Optional[str] = None
        self.protocol_version: str = ""
        self.server_info: dict = {}
        self._puente = _Puente()
        self._http = None
        self._transporte = None
        self._abierto = False

    def _evidencia(self, e: BaseException) -> dict:
        """La evidencia con la MISMA forma que da `MCPHttpError`, reconstruida.

        MEDIDO: el SDK aplasta todo lo que pasa por debajo de JSON-RPC. Un DNS que no
        resuelve, un puerto cerrado y un server que corta la conexión llegan los tres como
        `-32000 Connection closed`; un HTTP 405 con un HTML adentro llega como `-32603
        Server returned an error response`. El cliente viejo daba `http_status: 405` y el
        `[Errno 8] nodename nor servname` textual — y de eso viven `diagnostico_conectores`
        (401 ⇒ credencial · 404 ⇒ URL mala · 5xx ⇒ server caído) y los remedios. Perder el
        status sería cambiar un diagnóstico tipado por «algo salió mal».
        Se recupera del transporte HTTP, que es NUESTRO: ver `_TransporteQueRecuerda`.
        """
        ev: dict = {}
        if isinstance(e, MCPError):
            ev["respuesta"] = e.error.model_dump(exclude_none=True)
            if e.error.code == _traductor().PROTOCOLO_NO_SOPORTADO:
                # El ÚNICO caso en que hablar de deriva es honesto: el servidor la declaró
                # con `requested`/`supported` normativos.
                data = e.error.data if isinstance(e.error.data, dict) else {}
                ev["protocolo"] = _traductor().protocolo_de(
                    solicitada=data.get("requested") or _VERSION_SOLICITADA,
                    incompatible=True, soportadas=data.get("supported") or [])
        if self.protocol_version and "protocolo" not in ev:
            ev["protocolo"] = _traductor().protocolo_de(
                negociada=self.protocol_version, solicitada=_VERSION_SOLICITADA)
        t = self._transporte
        status = getattr(t, "ultimo_status", None)
        if status is not None:
            ev["http_status"] = status
        falla = getattr(t, "ultima_falla", "")
        if falla:
            ev["red_detalle"] = falla
        # `online` sólo se declara cuando el server CONTESTÓ algo. Decir «online» porque
        # llegó un `Connection closed` sería afirmar lo contrario de lo que pasó.
        ev["red"] = {"consultada": True, "online": True} if status is not None \
            else {"consultada": True}
        return ev

    def initialize(self) -> dict:
        """El `result` de initialize, en la MISMA forma camelCase que devolvía el cliente
        viejo (`model_dump(by_alias=True)`), para que quien lee `protocolVersion` o
        `serverInfo` no tenga que cambiar una línea."""
        import contextlib
        import httpx2

        cabeceras = {"User-Agent": self.user_agent, **self.extra_headers}
        self._transporte = _TransporteQueRecuerda()
        self._http = httpx2.AsyncClient(headers=cabeceras, timeout=self.timeout,
                                        follow_redirects=True, transport=self._transporte)
        self._puente._abrir_portal()

        @contextlib.asynccontextmanager
        async def _conexion():
            async with streamable_http_client(self.url, http_client=self._http) as (r, w):
                async with ClientSession(r, w, read_timeout_seconds=self.timeout) as s:
                    yield s

        try:
            self._puente._entrar(_conexion())
            init = self._puente._llamar(self._puente._sesion.initialize)
        except MCPError as e:
            ev = self._evidencia(e)
            self.close()
            raise TransporteSdkError(
                f"error del MCP remoto en initialize: {e.message}", evidencia=ev) from e
        except Exception as e:                             # noqa: BLE001
            ev = self._evidencia(e)
            self.close()
            raise TransporteSdkError(
                f"no se pudo conectar al MCP remoto: {_forma(e)}", evidencia=ev) from e

        self._abierto = True
        self.protocol_version = init.protocol_version
        self.server_info = init.server_info.model_dump(by_alias=True, exclude_none=True)
        return init.model_dump(by_alias=True, exclude_none=True)

    def list_tools(self) -> list:
        try:
            res = self._puente._llamar(self._puente._sesion.list_tools)
        except MCPError as e:
            raise TransporteSdkError(f"error del MCP remoto en tools/list: {e.message}",
                                     evidencia=self._evidencia(e)) from e
        except Exception as e:                             # noqa: BLE001
            raise TransporteSdkError(f"sin respuesta del MCP remoto a tools/list: "
                                     f"{_forma(e)}", evidencia=self._evidencia(e)) from e
        return [t.model_dump(by_alias=True, exclude_none=True) for t in res.tools]

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> dict:
        """El `result` crudo de `tools/call` —`{content:[…], isError:bool}`— igual que el
        cliente viejo, que devuelve el dict y deja que el llamante lo interprete."""
        try:
            res = self._puente._llamar(self._puente._sesion.call_tool, name, arguments or {})
        except MCPError as e:
            raise TransporteSdkError(f"error del MCP remoto en tools/call: {e.message}",
                                     evidencia=self._evidencia(e)) from e
        except Exception as e:                             # noqa: BLE001
            raise TransporteSdkError(f"sin respuesta del MCP remoto a tools/call: "
                                     f"{_forma(e)}", evidencia=self._evidencia(e)) from e
        return res.model_dump(by_alias=True, exclude_none=True)

    def close(self) -> None:
        """Best-effort, como el viejo: el SDK manda el DELETE de fin de sesión
        (`terminate_on_close=True`) al salir del context manager."""
        self._abierto = False
        self._puente._cerrar()
        self._http = None
        self.session_id = None


# ── utilidades ──────────────────────────────────────────────────────────────────────

def _forma(e: BaseException) -> str:
    """El texto de una excepción del SDK, desenvolviendo los `ExceptionGroup`.

    anyio corre el transporte en un task group, así que casi todo llega envuelto —a veces
    dos veces— en `BaseExceptionGroup`. Un diagnóstico que dijera «unhandled errors in a
    TaskGroup» no le sirve a nadie: hay que bajar hasta la hoja. Ver el mapa de errores del
    reporte de esta sesión.
    """
    visto = 0
    while isinstance(e, BaseExceptionGroup) and e.exceptions and visto < 8:
        e = e.exceptions[0]
        visto += 1
    return f"{type(e).__name__}: {e}"


def _json(obj: Any) -> str:
    import json
    try:
        return json.dumps(obj.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False)
    except Exception:                                      # noqa: BLE001
        return str(obj)


__all__ = ["ServidorSDK", "ClienteSdkHttp", "TransporteSdkError",
           "entorno_hijo", "fugas_del_sdk", "path_de_aleph", "sdk_disponible"]
