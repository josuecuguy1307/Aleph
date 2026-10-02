"""pack.py — EL CICLO DE VIDA DEL PACK DE UN WORKSPACE.
[Gate 4 · Fase 4 · obra O1 · ley 8 escalón 2 · deudas D-STACK-PROC · D-ARRANQUE-CEREBRO]

QUÉ RESUELVE
------------
Hasta hoy el proceso de un workspace heredado se levantaba **a mano**. Medido el
2026-08-09, con la evidencia todavía viva en la máquina:

  · `~/Desktop/Ciencia/.servidor.log` → «openscience server listening on http://localhost:4096»,
    escrito por un `bun` que vivía en un prefijo de sesión de un agente. Ese prefijo se
    borró; el proceso quedó **con PPID 1**, escuchando el puerto, sin padre que lo apague.
  · `~/Desktop/Ciencia/openscience.json` tenía el puerto del sidecar **horneado a mano**
    (`8330`), y el sidecar elige puerto libre en cada arranque (`aleph-shell/src-tauri/
    src/lib.rs:48-62`). Al segundo arranque de la app, el cerebro del workspace apuntaba a
    un puerto de nadie.

Este módulo pone las dos puntas del cable en manos del pack: **entrar levanta, salir
apaga**, el puerto lo elige Aleph y la config la escribe Aleph.

POR QUÉ NO HAY UN DUEÑO NUEVO
-----------------------------
`platform/inspection/dueno.py` ya es un supervisor de procesos completo: refcount, techo
LRU, cosechador de ociosidad, `apagar_todo()` en el `finally` del lifespan
(`main.py:341-344`), barrido de arranque (`main.py:173-178`) y —lo que más importa acá—
**huérfanos imposibles por construcción**: la línea del `procesos.jsonl` se escribe ANTES
del spawn, con `fsync`, para que un sidecar que muere en esa ventana igual deje rastro.

Su §5 lo dice sin rodeos: «dos tablas de vivos son dos verdades sobre los mismos
procesos». Así que el pack **no estrena supervisor**: entra al que hay, con su clase
propia declarada en el `spec` (`dueno._cls`). El día que un pack quede huérfano lo barre
el mismo barrido que barre a los MCP, y no un segundo barrido que nadie escribió.

LA PERILLA `ALEPH_DUENO` NO GOBIERNA ESTO — y hay que decirlo fuerte:
`dueno.encendido()` decide si los consumidores **de MCP** usan el dueño o spawnean como
siempre. El pack **no tiene un "como siempre"**: nació acá, con el dueño, en las dos
posiciones de la perilla. Prender o apagar `ALEPH_DUENO` no cambia una línea del ciclo de
vida del pack.

LA GRACIA AL SALIR, Y POR QUÉ NO ES CERO
-----------------------------------------
El mandato dice «salir apaga». Apagar en el instante del `leave` sería literal y **peor**:
`ciencia.html` ya avisa que adentro del lienzo puede haber un kernel de Python corriendo,
y un F5 del usuario emite `pagehide` + `pageshow` en menos de un segundo. Matar el stack
en cada recarga es perder el trabajo de alguien por un refresh.

Por eso el `leave` suelta el préstamo y arma una **gracia corta** (`GRACIA_S`, 20 s por
defecto): si nadie vuelve a entrar, el pack se apaga por el camino de la lápida
(`apagar_entidad`, que manda por encima del refcount). Si el usuario vuelve —o recarga—
dentro de la ventana, se cancela la gracia y **se reusa el proceso vivo**, sin re-pagar el
arranque. Es un número declarado, no medido, y por eso es una variable de entorno:
`ALEPH_PACK_GRACIA_S=0` lo vuelve literal para una vara que quiera medir «salir apaga».

El cosechador del dueño (600 s) queda debajo como red de seguridad, nunca como primer
disparo.

VOCABULARIO (sellado 2026-08-09, para no pisarme con F5)
--------------------------------------------------------
  · **huérfano** — el proceso se murió o quedó sin padre. Es de este archivo.
  · **cancelado** — una persona paró algo. Es de F5; acá no se usa esa palabra.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
import secrets
import socket
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

_AQUI = Path(__file__).resolve().parent
if str(_AQUI.parent) not in sys.path:                      # platform/
    sys.path.insert(0, str(_AQUI.parent))
if str(_AQUI.parent / "inspection") not in sys.path:
    sys.path.insert(0, str(_AQUI.parent / "inspection"))

import aleph_paths as _ap                                   # noqa: E402

#: Cuánto se espera a que el pack conteste su señal de salud antes de declararlo caído.
#: Medido sobre el binario compilado de Ciencia: contesta `/global/health` en **menos de
#: 1 s** desde frío. 25 s es holgura para una máquina cargada, no una estimación del costo.
ARRANQUE_S = float(os.environ.get("ALEPH_PACK_ARRANQUE_S", "25"))

#: La gracia del `leave` (ver el encabezado). 0 = apagar en el acto.
GRACIA_S = float(os.environ.get("ALEPH_PACK_GRACIA_S", "20"))

#: Cada cuánto se le pregunta al pack si ya está sano mientras arranca.
_LATIDO_S = 0.25


class PackError(Exception):
    """El pack no pudo levantarse, con causa legible para la superficie."""

    def __init__(self, causa: str, detalle: str = ""):
        self.causa = causa
        self.detalle = detalle
        super().__init__(f"{causa}: {detalle}" if detalle else causa)


# ── EL PUERTO ───────────────────────────────────────────────────────────────────────

def puerto_libre() -> int:
    """Un puerto TCP libre en loopback, elegido por el SO.

    Hay una carrera inevitable entre soltar este socket y que el pack lo tome; es la misma
    que tiene cualquier `--port 0` de la industria y se cierra del único modo honesto: si
    el arranque falla, `levantar()` reintenta UNA vez con otro puerto (y sólo una: dos
    fallos seguidos ya no son mala suerte, son una causa que hay que mostrar).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def _sano(url: str, ruta: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url + ruta, timeout=timeout) as r:
            return r.status == 200
    except Exception:                                       # noqa: BLE001 — no contestar no es un error
        return False


# ── LA CLASE QUE EL DUEÑO SABE LEVANTAR ─────────────────────────────────────────────

class ServidorDePack:
    """Un proceso largo con señal de salud, **con la forma que `dueno.pedir()` espera**.

    El contrato del dueño (ver `dueno._levantar`) es: se construye con
    `(entity_id, comando, args, env=…, rpc_timeout=…, cwd=…)`, se le llama `start() -> bool`
    y, al morir, `stop()`. `list_tools`/`call_tool` no se usan nunca acá: un pack no es un
    servidor de herramientas, es el proceso que sirve el workspace.

    **`start_new_session=True` y muerte por GRUPO.** El binario del stack lanza hijos (su
    runtime, sus kernels). Matar sólo al padre deja nietos vivos, que es la definición de
    huérfano. Es la misma regla que `platform/assembler/workers.py:460-467` ya aplica.
    """

    #: El copy que `dueno._levantar` usa cuando `start()` devuelve False (regla sellada:
    #: ninguna causa llega a una superficie sin copy).
    FALLO_ARRANQUE = "no llegó a contestar su señal de salud"

    def __init__(self, name, command, args, env=None, rpc_timeout=ARRANQUE_S, cwd=None):
        self.name = name
        self._command = command
        self._args = list(args or [])
        self._env = dict(env or {})
        self._cwd = cwd
        self._plazo = float(rpc_timeout or ARRANQUE_S)
        self._proc: Optional[subprocess.Popen] = None
        self._detalle = ""
        self._exit_code: Optional[int] = None
        self._log_inicio = 0
        #: `url` y `salud` los inyecta `levantar()` — el dueño no sabe de HTTP.
        self.url = ""
        self.salud = "/"
        self.bitacora: Optional[Path] = None

    # -- arranque -------------------------------------------------------------------
    def start(self) -> bool:
        if not self._command or not os.path.isfile(self._command):
            self._detalle = f"el binario del pack no está en {self._command!r}"
            return False
        if not os.access(self._command, os.X_OK):
            self._detalle = f"el binario del pack no es ejecutable: {self._command}"
            return False
        salida = subprocess.DEVNULL
        if self.bitacora is not None:
            try:
                self.bitacora.parent.mkdir(parents=True, exist_ok=True)
                self._log_inicio = self.bitacora.stat().st_size if self.bitacora.exists() else 0
                salida = open(self.bitacora, "ab", buffering=0)                 # noqa: SIM115
            except Exception:                               # noqa: BLE001 — sin bitácora se sigue
                salida = subprocess.DEVNULL
        try:
            child_env = {k: v for k, v in os.environ.items() if k != "ALEPH_LAUNCH_CAP"}
            child_env.update(self._env)
            self._proc = subprocess.Popen(
                [self._command, *self._args],
                cwd=self._cwd, env=child_env,
                stdout=salida, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                start_new_session=True,                     # grupo propio → se mata entero
            )
        except Exception as e:                              # noqa: BLE001 — frontera
            self._detalle = f"{type(e).__name__}: {e}"
            return False

        # ESPERAR LA SALUD, NO EL PROCESO. Que el pid exista no dice nada: el defecto que
        # F3 midió es justamente ése —un 200 en `/` sobre un server que no servía—, y acá
        # se paga al revés: dar por arriba un pack que todavía no atiende deja al lienzo
        # cargando un 404 con la barra diciendo «en vivo».
        limite = time.time() + self._plazo
        while time.time() < limite:
            if self._proc.poll() is not None:
                self._exit_code = self._proc.returncode
                # `exit 0` NO ES UNA MUERTE: es una salida LIMPIA. En un stack con lock de
                # instancia única, la segunda instancia le pasa el trabajo a la que ya
                # corre y se va con 0 — por diseño. Decir «se murió al arrancar» ahí es
                # una causa que MIENTE, y la pantalla la repite tal cual.
                if self._exit_code == 0:
                    self._detalle = (
                        "el proceso salió limpio (exit 0) sin llegar a atender en "
                        f"{self.url}: es lo que hace un binario con candado de instancia "
                        "única cuando ya hay otra corriendo. Si el workspace está vivo, "
                        "es que lo levantó otra sesión y hay que compartirlo, no relanzarlo")
                else:
                    self._detalle = (f"el proceso se murió al arrancar "
                                     f"(exit {self._exit_code})")
                self._adjuntar_log()
                return False
            if _sano(self.url, self.salud):
                return True
            time.sleep(_LATIDO_S)
        self._detalle = (f"no contestó {self.salud} en {self._plazo:g}s")
        self.stop()
        self._adjuntar_log()
        return False

    # -- diagnóstico ----------------------------------------------------------------
    def diagnostico(self) -> dict:
        return {"detail": self._detalle,
                "exit_code": (self._proc.returncode if self._proc else self._exit_code)}

    def _adjuntar_log(self) -> None:
        """Attach only this spawn's recent stdout/stderr to a failed pack.

        `ServidorDePack` deliberately merges child stdout/stderr into the pack log
        so the supervisor has one durable stream.  On a real startup failure the
        last lines are the only useful cause (for example an omitted bundled
        directory); exposing that bounded tail lets the workspace show Retry with
        the actual failure instead of a permanent spinner or a generic 503.
        """
        if self.bitacora is None:
            return
        try:
            raw = self.bitacora.read_bytes()[self._log_inicio:]
            texto = " ".join(line.strip() for line in raw.decode("utf-8", "replace").splitlines()
                              if line.strip())
        except Exception:                               # noqa: BLE001 — evidence never blocks cleanup
            return
        if not texto:
            return
        self._detalle = f"{self._detalle}; stdout/stderr: {texto[-2400:]}"

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc else None

    # -- apagado --------------------------------------------------------------------
    def stop(self) -> None:
        """TERM al grupo, y SIGKILL al que no se va. Idempotente."""
        p, self._proc = self._proc, None
        if p is None:
            return
        try:
            pgid = os.getpgid(p.pid)
        except Exception:                                   # noqa: BLE001 — ya no está
            pgid = None
        try:
            if pgid is not None:
                os.killpg(pgid, 15)
            else:
                p.terminate()
        except Exception:                                   # noqa: BLE001
            pass
        try:
            p.wait(timeout=4)
        except Exception:                                   # noqa: BLE001
            try:
                if pgid is not None:
                    os.killpg(pgid, 9)
                else:
                    p.kill()
            except Exception:                               # noqa: BLE001
                pass
            try:
                p.wait(timeout=2)
            except Exception:                               # noqa: BLE001
                pass


# ── DÓNDE VIVE LO DEL PACK ──────────────────────────────────────────────────────────

def raiz_pack(ws: str) -> Path:
    """El dir del pack de ESTE workspace, fuera del árbol de código.

    Va bajo `aleph_paths.user_data_dir()` por la misma razón que todo lo demás: el árbol
    es de sólo lectura bajo PyInstaller y se reemplaza entero al actualizar. Hoy el stack
    de Ciencia escribe en `~/.openscience/` —fuera del dir de datos de Aleph, donde nadie
    lo respalda ni lo borra al desinstalar—; acá se lo trae adentro **sin tocarle una
    línea**: su propio `global/index.ts:53,59` respeta `OPENSCIENCE_CONFIG_DIR` y
    `OPENSCIENCE_DATA_DIR`.
    """
    d = _ap.user_data_dir() / "workspaces" / ws
    d.mkdir(parents=True, exist_ok=True)
    # OpenWork opens server.json through its no-follow native filesystem boundary.
    # On macOS /tmp is a symlink to /private/tmp: passing the lexical /tmp path
    # makes that read fail even though Aleph has just written the file. Resolve
    # the trusted pack root once, before publishing any config/env paths.
    return d.resolve(strict=True)


def _sub(ws: str, nombre: str) -> Path:
    d = raiz_pack(ws) / nombre
    d.mkdir(parents=True, exist_ok=True)
    return d


def binario_de(meta: dict) -> Optional[str]:
    """La ruta del binario del pack, o `None` si no viajó con esta instalación.

    Se prueban las rutas declaradas EN ORDEN y se devuelve la primera que existe:
    la del `.app` (donde el spec lo deja) y la del árbol de desarrollo (donde lo deja
    `bun run build`). Declarar las dos es lo que hace que la misma línea de código sirva
    para medir en dev y para correr congelado.
    """
    for rel in meta.get("bin", []):
        p = _ap.resource_root() / rel
        if p.is_file():
            return str(p)
    return None


# ── LA CONFIG DEL STACK, ESCRITA POR ALEPH ──────────────────────────────────────────

def _ruta_plugin(meta: dict) -> Optional[Path]:
    """El plugin de Aleph para este stack, si el registro declara uno.

    Vive en el árbol de ALEPH (`platform/workspaces/plugins/`), no adentro de
    `third_party/`: así el stack importado queda byte-idéntico y la pieza que le habla a
    la casa se versiona con la casa. El stack lo carga por `file://` desde su `config.plugin`
    (`backend/cli/src/plugin/index.ts:78-118`), sin `bun add`, sin registry y sin red.
    """
    rel = meta.get("plugin")
    if not rel:
        return None
    p = _ap.resource_root() / rel
    return p if p.is_file() else None


def escribir_ajustes_plugin(ws: str, meta: dict, *, base_aleph: str, token: Optional[str],
                            user_id: Optional[str], chat_id: Optional[str],
                            sid: Optional[str],
                            credenciales: Optional[dict[str, str]] = None) -> Path:
    """Lo que el plugin necesita saber, en UN archivo 0600 que sólo él lee.

    Va aparte del `openscience.json` a propósito: ese archivo es del STACK y su forma es
    del stack; esto es nuestro. Y va en un archivo en vez de en el entorno porque el
    entorno de un proceso es legible con `ps -E`, y acá adentro viaja la sesión.
    """
    destino = _sub(ws, "config") / "aleph-pack.json"
    cuerpo = {
        "workspace": ws,
        "base": base_aleph.rstrip("/"),
        "token": token or "",
        "user_id": user_id,
        "chat_id": chat_id,
        "sid": sid,
        "log": str(_sub(ws, "log") / "pack.log"),
        # [F6-oficina] EL DIRECTORIO DEL PROYECTO. Un stack cuyos artefactos son ARCHIVOS
        # —y no un grafo de procedencia como el de Ciencia— necesita saber dónde mirar
        # para contar qué produjo un turno. Es el mismo dir que el pack le da de `cwd`.
        "proyecto": str(_sub(ws, meta.get("label") or "proyecto")),
        # [Diseño · obra 1 · LEY 12] EL NOMBRE DEL CEREBRO, DECLARADO POR EL REGISTRO.
        # Para los packs cuya config escribe su propio lanzador (`config_format:
        # "launcher"`), este archivo es el ÚNICO canal de la casa a su motor. El lanzador
        # de Diseño tenía «Cerebro de Aleph» escrito a mano en dos lugares mientras la
        # fila del registro declaraba el mismo string un nivel más arriba: dos fuentes
        # para un dato, y la de abajo ganaba. Ahora la fila manda y el lanzador obedece.
        # Es además lo que vuelve al canal DEMOSTRABLE desde afuera: cambiar este valor en
        # el registro se ve en `onboarding:get-state.modelPrimary`, que es lo que la
        # pantalla escribe debajo del cuadro de escribir.
        "cerebro_label": meta.get("cerebro_label", "Cerebro de Aleph"),
    }
    # [F1-CONECTORES] LAS CREDENCIALES DEL USUARIO, PARA EL PACK CUYA CONFIG ESCRIBE SU
    # LANZADOR. Viajan por acá y no por un archivo nuestro porque el `config.toml` de Diseño
    # lo produce `bin/aleph-codesign` y dos escritores para un archivo es una carrera con
    # ganador fijo. Este archivo ya es 0600 y ya es el único canal de la casa a ese motor.
    #
    # El valor va con el prefijo `plain:` que su propio formato define
    # (`keychain.ts:5-6`): `safe:` requiere el Keychain del usuario, que vive del otro lado
    # de Electron, y un valor CRUDO cae en la rama legacy de safeStorage y LEVANTA
    # (`keychain.ts:37`). El prefijo es parte del contrato del stack, no un downgrade nuestro.
    if credenciales:
        cuerpo["credenciales"] = {p: "plain:" + v for p, v in credenciales.items() if v}
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, destino)
    return destino


def _escribir_json_0600(destino: Path, cuerpo: dict[str, Any]) -> Path:
    """Escribe configuración sensible de un pack sin dejar medias versiones."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    tmp.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, destino)
def _espacio_de_visita(ws: str, sid: Optional[str]) -> str:
    """El id del espacio donde se anotan los pasos de ESTA visita al workspace.

    [Gate 4 · F6-FINANZAS · D8] Mismo formato que el que fabrica el plugin de Ciencia
    (`plugins/openscience.js:80 nuevoEspacio`) para que S8 y la Biblioteca lean lo mismo
    venga de donde venga. La diferencia de GRANULARIDAD está declarada en el escritor de
    abajo y en el acta: el plugin abre un espacio por TURNO; acá, sin plugin, se abre uno
    por VISITA (por `enter`).
    """
    limpio = re.sub(r"[^A-Za-z0-9._:-]", "", str(sid or ws))[-24:] or ws
    return f"space-ws-{limpio}-{int(time.time() * 1000):x}"


def _escribir_config_dotenv(ws: str, meta: dict, *, base_aleph: str,
                            token: Optional[str], user_id: Optional[str] = None,
                            puppet_id: Optional[str] = None, chat_id: Optional[str] = None,
                            sid: Optional[str] = None) -> Path:
    """La config del pack para un stack que se configura por **variables de entorno**.

    [Gate 4 · F6-FINANZAS] **El segundo inquilino habla otro dialecto de config.** El
    escritor de arriba nació con Ciencia y quedó horneado a SU forma (`provider.aleph.npm`,
    `models`, `model: "aleph/cerebro"`) — que es la de un stack de TypeScript con SDK de
    Vercel. Vibe-Trading es Python/LangChain y se configura con un `.env` de cuatro líneas.

    Esto **no toca el ciclo del pack**: es una rama más de escritura, elegida por el campo
    `config_format` del registro. El ciclo (levantar · gracia · préstamo · salir) queda
    exactamente como F4 lo dejó.

    Las cuatro variables son las que el estudio de F6 midió con el lazo cerrado
    modelo→tool→modelo contra un borde OpenAI-compatible: **cero corte de código en el
    stack** (`agent/src/providers/llm.py:1134` es su único constructor y no valida el host).

    El modelo se llama literalmente «Cerebro de Aleph»: el harness no elige cerebro
    (LEY DEL CEREBRO ÚNICO), y el selector del workspace muestra UNO.
    """
    # Va al dir de DATOS, no al de config, y no es un descuido: este stack tiene UNA sola
    # raíz de runtime (`VIBE_TRADING_HOME`, `src/config/paths.py:11`) para config y datos.
    # El registro declara esa misma variable en `config_env` y en `data_env`, así que el
    # `env` del spec colapsa a una clave y gana el valor de `data_env`. El `.env` tiene que
    # aterrizar donde el stack lo va a buscar.
    destino = _sub(ws, "data") / meta.get("config_file", ".env")
    label = meta.get("cerebro_label", "Cerebro de Aleph")
    # ── [F6 · D8] LAS CABECERAS `X-Aleph-*`, SIN PLUGIN Y SIN TOCAR EL STACK ──────────
    # Este stack no tiene el punto de extensión `config.plugin` que tiene el de Ciencia, y
    # durante un rato eso se declaró como deuda («Finanzas no tiene plugin ⇒ S8 ciego»).
    # **Era falso**: no tener plugin no exime del header. El SDK de OpenAI lee
    # `OPENAI_CUSTOM_HEADERS` (formato `Nombre: valor`, una por línea) y el stack lo
    # respeta — `providers/llm.py:110-135` las captura, y `_provider_scoped_extra_headers`
    # (`:137`) sólo las poda cuando el proveedor NO es `openai`, que es justo el nuestro.
    # O sea: la costura que ya escribimos puede llevar las cabeceras. Cero líneas del stack.
    #
    # LA GRANULARIDAD, DICHA: el plugin de Ciencia abre un espacio por TURNO
    # (`openscience.js:266 "chat.headers"`), porque corre adentro del harness y ve cada
    # paso. Un `.env` se escribe UNA vez por `enter`, así que acá el espacio es **por
    # visita**: todos los pasos de esta entrada al workspace se anotan en el mismo espacio,
    # y `X-Aleph-Turn` no puede incrementarse desde acá. **S8 deja de estar ciego**, que es
    # lo que D8 pedía; la granularidad fina queda anotada en el acta como deuda menor.
    espacio = _espacio_de_visita(ws, sid)
    cabeceras = [f"X-Aleph-Workspace: {ws}", f"X-Aleph-Space: {espacio}"]
    if user_id:
        cabeceras.append(f"X-Aleph-User: {user_id}")
    if chat_id:
        cabeceras.append(f"X-Aleph-Chat: {chat_id}")
    if puppet_id:
        # [LEY 15 · MODO RAW] Opcional a propósito: sin agente el borde resuelve el modelo
        # que el usuario tiene elegido en el selector y el turno corre igual.
        cabeceras.append(f"X-Aleph-Puppet: {puppet_id}")
    # ⚠️ CADA CLAVE QUE SE AGREGUE ACÁ VA TAMBIÉN AL `case` DEL LAUNCHER, EN EL MISMO COMMIT.
    #
    # Medido 2026-08-17: `ServidorDePack.start` spawnea con `env={**os.environ, **self._env}`
    # (`pack.py:186`), o sea que el hijo hereda el entorno ENTERO del sidecar. Y el stack carga
    # su `.env` con `load_dotenv(override=False)` / `setdefault`
    # (`vibetrading/agent/src/providers/llm.py:777-786`): **una variable ya presente en el
    # entorno le gana al archivo, sin una señal**.
    #
    # Lo que hoy lo impide es que `launchers/finanzas-serve:50-58` lee ESTE archivo y exporta
    # sus claves antes de exec-utar el stack, así que cuando el `setdefault` corre la variable
    # ya tiene nuestro valor. Las dos listas coinciden clave por clave, y ése es todo el
    # mecanismo. Comprobado envenenando el entorno del sidecar con `OPENAI_BASE_URL` y
    # `LANGCHAIN_MODEL_NAME` de otro destino: el turno salió igual por el borde de Aleph
    # (`configured_model="Cerebro de Aleph"`, `model="claude-opus-5"`).
    #
    # El `case` es LISTA CERRADA («se leen SÓLO las claves que Aleph escribe»), así que una
    # clave nueva NO queda cubierta por arrastre: nace con la sombra puesta y sin señal. Vale
    # especialmente para credenciales de terceros —hoy no viaja ninguna por acá— porque ahí el
    # daño no es un turno perdido sino un secreto ajeno usado en su lugar.
    lineas = [
        "# Generado por Aleph en cada `enter` — NO editar a mano.",
        "# El baseURL sale del sidecar que está corriendo AHORA; la apiKey es la sesión.",
        "LANGCHAIN_PROVIDER=openai",
        f"LANGCHAIN_MODEL_NAME={label}",
        f"OPENAI_BASE_URL={base_aleph.rstrip('/') + meta['brain_path']}",
        f"OPENAI_API_KEY={token or ''}",
        # El SDK acepta varias cabeceras separadas por `\n` dentro de la misma variable.
        "OPENAI_CUSTOM_HEADERS=" + "\n".join(cabeceras).replace("\n", "\\n"),
        "",
    ]
    tmp = destino.with_suffix(".env.tmp")
    tmp.write_text("\n".join(lineas), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, destino)                                # atómico: nunca media config
    return destino


# ══ [F1-CONECTORES] LA CREDENCIAL DEL USUARIO, DESDE EL VAULT AL LUGAR DONDE SU STACK LEE ══
#
# LA FASE 0 MIDIÓ LOS SEIS Y NO HAY UN PUNTO ÚNICO como con el cerebro: cada stack lee su
# credencial de donde su código la espera, y son cinco archivos de cuatro formas distintas
# más una llamada HTTP. Lo que SÍ hay es un mecanismo único —éste— y el precedente ya estaba
# escrito: `_escribir_config_dotenv` arriba es exactamente esto para el cerebro de Finanzas.
# Por eso acá no nace un escritor nuevo: nace una RAMA MÁS del mismo despachador.
#
# ── POR QUÉ UN CAMPO PROPIO (`cred_format`) Y NO `config_format` ────────────────────────
# `config_format` despacha el dialecto del CEREBRO. El destino de la credencial es otro
# artefacto y, en cuatro de los seis, otro archivo: Legal escribe su cerebro en
# `config/opencode.json` y su credencial en `data/.preferences/preferences.json`. Colgar los
# dos del mismo campo obligaría a Legal —que hoy no declara `config_format`— a declarar uno
# sólo para recibir credenciales, y ataría dos decisiones que se mueven por separado.
#
# ── POR QUÉ EL MAPA LO DECLARA LA FILA ─────────────────────────────────────────────────
# «EL GUARD NO INVENTA; EL CATÁLOGO DECLARA» (CLAUDE.md §1). Qué proveedor del vault
# corresponde a qué campo del archivo de qué stack es una decisión de catálogo con autor:
# la toma quien conoce el conector y queda persistida en la fila con su motivo. Derivarla
# de un parecido de nombres sería inventar el destino de un secreto.
#
# ── LO QUE ESTA PIEZA NO HACE ──────────────────────────────────────────────────────────
# No pisa una canónica heredada del entorno (ver `sombra_de_credenciales`), no confía en un
# 200 ni en un `connected` (ver `verificar_credenciales`), y no imprime un valor: de un
# secreto sólo salen NOMBRE y LARGO.

#: Los formatos de destino que sabe escribir esta casa, uno por forma REAL medida en Fase 0.
#: No son seis: son cinco, porque Finanzas y Oficina comparten «archivo de variables» sólo
#: en apariencia —uno es dotenv y el otro un JSON con esquema— y Diseño no recibe archivo
#: nuestro sino una declaración en el puntero que su lanzador traduce.
_CRED_FORMATOS = ("preferences_json", "mcp_secrets", "env_json", "dotenv_extra",
                  "puntero_launcher", "http_credentials")


def _cred_entradas(meta: dict) -> list[dict]:
    """Las declaraciones de credencial de la fila, ya validadas en forma.

    Una entrada mal formada se DESCARTA con su nombre a la vista en el resultado, en vez de
    reventar el `enter`: quedarse afuera del workspace por una fila mal escrita es peor que
    entrar sin una credencial y que la casa lo diga.
    """
    salida = []
    for e in (meta.get("cred_map") or []):
        if isinstance(e, dict) and e.get("vault"):
            salida.append(e)
    return salida


def _canonicas_de(slug: str) -> tuple[list[str], str]:
    """Los nombres de env var de un provider del vault. Devuelve `(nombres, origen)`.

    ⚠️ ESTA TABLA NO SE ESCRIBE ACÁ, Y LA PRIMERA VERSIÓN DE ESTA OBRA LA ESTABA ESCRIBIENDO.
    Iba a declarar las canónicas entrada por entrada en la fila del registro, hasta que el
    propio catálogo me lo desmintió: `catalog/connectors/env-alias.json` ya es esa tabla, su
    `_meta` nombra a sus dos lectores, y dice textualmente que dos copias son «la
    contradicción entre fuentes que el adaptador existe para delatar». La mía habría sido la
    tercera.

    Se reusa `recipe_assembler._provider_env_vars`, que es quien ya la lee: da los alias del
    catálogo MÁS el canónico `<PROVIDER>_API_KEY` MÁS `<PROVIDER>_ACCESS_TOKEN`, y resuelve
    el companion `<p>__oauth → <P>_OAUTH_META`. Medido: importa en ~0,1 s y reporta
    `origen: catalogo`.

    Es una función privada de otro módulo y eso es una deuda declarada, no un descuido: la
    alternativa era reimplementar la convención acá, que es la copia que el `_meta` prohíbe.
    Queda propuesto —UNO, no dos— promoverla a un hogar compartido cuando algún tercero la
    necesite.

    ⚠️ Y HAY UNA SEGUNDA VÍA, PORQUE LA PRIMERA NO SOBREVIVE AL CONGELADO. La vara contra la
    `.app` instalada (`19cddb35…`) la encontró: adentro del binario esta función devolvía
    `sin_tabla`, y con eso la lista de `github` se quedaba en `GITHUB_API_KEY` —el canónico de
    la convención— sin `GITHUB_TOKEN`, que es un ALIAS. Consecuencia medida: la sonda de
    Ciencia no tenía ningún nombre cruzado y no podía verificar, y una sombra sobre
    `GITHUB_TOKEN` no se habría detectado. Los 14 alias del catálogo se perdían; sólo
    funcionaban los providers a los que la convención les acierta (por eso `exa` daba verde).

    LA CAUSA, medida preguntándole al binario y no al spec: adentro del `_MEI` **todo viaja**
    —`catalog/connectors/env-alias.json`, y `platform/assembler/recipe_assembler.py`— pero
    `recipe_assembler.py` viaja como **archivo de DATOS**, mientras el módulo importable vive
    en el PYZ. Mi `sys.path.insert(0, …/assembler)` ponía el dir de datos ANTES del PYZ, así
    que el `import` levantaba la copia-dato en vez del módulo, y esa copia no tiene a su lado
    las dependencias que resuelve el PYZ. El `sys.path` que arreglaba el import en dev era
    justamente lo que lo rompía congelado.

    ⇒ Si el import falla, se lee **el mismo archivo del catálogo** con `resource_root()`, que
    es el resolvedor frozen-safe de la casa (el que arregló «el curado no se encuentra en el
    PYZ»). **La tabla sigue teniendo una sola copia**: las dos vías leen
    `catalog/connectors/env-alias.json`. Lo único que se repite es la CONVENCIÓN —cuatro
    líneas de regla de nombres— y eso es lo que el `_meta` no prohíbe: prohíbe copiar la
    tabla. El campo `tabla` dice por cuál de las dos vías se resolvió.
    """
    causa = ""
    try:
        _asm = _AQUI.parent / "assembler"
        if str(_asm) not in sys.path:
            sys.path.insert(0, str(_asm))
        import recipe_assembler as _ra                  # noqa: PLC0415 — perezoso a propósito
        return list(_ra._provider_env_vars(slug)), getattr(_ra, "_ALIAS_ORIGEN", "?")
    except Exception as e:                              # noqa: BLE001 — frontera de import
        causa = f"{type(e).__name__}"

    directo = _canonicas_del_catalogo(slug)
    if directo is not None:
        return directo, "catalogo-directo"

    # FALLO VISIBLE, JAMÁS MUDO. Sin la tabla, la sombra se quedaría CIEGA y daría
    # «0 heredadas» sobre un entorno que nadie miró — el instrumento equivocado no da rojo,
    # da silencio. Se devuelve el canónico de la convención y se DICE que la tabla no se pudo
    # cargar, para que la salida del `enter` no parezca una medición limpia.
    #
    # ⚠️ Y SE DICE **POR QUÉ**, con el nombre de la excepción. La primera versión devolvía
    # `"sin_tabla"` pelado y la vara contra la `.app` lo encontró rojo SIN CAUSA: adentro del
    # binario todo lo necesario viaja, así que un rojo mudo no dejaba diagnosticar nada. Un
    # rojo mudo es mejor que un verde falso y peor que un rojo que habla.
    return [slug.upper() + "_API_KEY"], f"sin_tabla:{causa or 'catalogo ilegible'}"[:120]


def _canonicas_del_catalogo(slug: str) -> Optional[list[str]]:
    """La MISMA tabla del catálogo, leída sin pasar por el assembler. `None` si no se pudo.

    Existe sólo porque el import del assembler no sobrevive al congelado (ver arriba). Lee
    `catalog/connectors/env-alias.json` por `resource_root()`, que es cómo la casa resuelve sus
    recursos adentro del `.app` **y** en el árbol. La tabla no se copia: es el mismo archivo.

    La CONVENCIÓN sí se repite, y es a propósito: son las tres reglas de nombre que
    `recipe_assembler._provider_env_vars` aplica sobre la tabla —el canónico
    `<PROVIDER>_API_KEY`, el `<PROVIDER>_ACCESS_TOKEN` de OAuth público, y el companion
    `<p>__oauth → <P>_OAUTH_META`—. Duplicar cuatro líneas de regla para no depender de un
    import frágil es un trato distinto que duplicar los 14 alias, que es lo que el `_meta` del
    catálogo prohíbe.
    """
    if slug.lower().endswith("__oauth"):
        return [slug[: -len("__oauth")].upper() + "_OAUTH_META"]
    try:
        ruta = _ap.resource_root() / "catalog" / "connectors" / "env-alias.json"
        tabla = (json.loads(ruta.read_text(encoding="utf-8")) or {}).get("alias") or {}
        if not tabla:
            return None                                 # archivo presente y vacío: no se finge
    except Exception:                                   # noqa: BLE001 — frontera de disco
        return None
    fuera = [str(v) for v in (tabla.get(slug.lower()) or [])]
    for extra in (slug.upper() + "_API_KEY", slug.upper() + "_ACCESS_TOKEN"):
        if extra not in fuera:
            fuera.append(extra)
    return fuera


def canonicas_declaradas(meta: dict) -> tuple[list[str], str]:
    """Las env vars que las credenciales de esta fila van a ocupar, y de dónde salió la tabla."""
    nombres: list[str] = []
    # «sin_entradas» y «sin_tabla» son estados DISTINTOS y por eso no comparten el vacío:
    # el primero dice «esta fila no pidió ninguna credencial» y el segundo «no pude cargar la
    # tabla, así que mi lista puede estar corta». Un solo `""` para los dos volvería a mezclar
    # una medición con un silencio, que es el defecto que este campo existe para evitar.
    origen = "sin_entradas"
    for e in _cred_entradas(meta):
        propias, origen = _canonicas_de(e["vault"])
        for n in propias:
            if n not in nombres:
                nombres.append(n)
    return nombres, origen


def sombra_de_credenciales(meta: dict, entorno_hijo: dict) -> dict[str, Any]:
    """[F1 · C] ¿Hay una canónica de credencial YA en el entorno que el hijo va a heredar?

    EL MECANISMO, MEDIDO EN FASE 0 Y ACORDADO ENTRE CIENCIA Y FINANZAS:
    `pack.py:186` hace `env={**os.environ, **self._env}`, así que el hijo hereda el entorno
    ENTERO del sidecar. Y varios stacks PREFIEREN lo heredado por encima de lo que la casa
    les escribe: Ciencia lo dice en una línea —`if (process.env[key] && !ownedKeys.has(key))
    continue` (`credentials.ts:378`)— y Finanzas por `override=False` / `os.environ.setdefault`
    (`providers/llm.py:777-786`). O sea: una variable heredada le GANA al vault, sin señal.

    CLASIFICACIÓN ACORDADA: **mecanismo armado · ocupación cero · gatillo EXTERNO.** Medido:
    0 de las 29 canónicas de Ciencia presentes en el entorno de una sesión de Claude Code,
    con control positivo en la misma corrida (16 `CLAUDE_CODE_*`/`ANTHROPIC_*` sí estaban, o
    sea que el vacío era un resultado y no un instrumento mudo). No lo enciende un cambio en
    el árbol: lo enciende el entorno de quien lanza Aleph.

    ⚠️ SE DETECTA Y SE ANUNCIA; NO SE PISA. Es la misma decisión que
    `exclusividad_del_cerebro` tomó para Legal —«detectado y anunciado, no reparado»— y acá
    es más fuerte todavía: limpiar la variable sería pisar algo que el usuario exportó a
    propósito en SU shell. La casa no sabe si esa key es un descuido o una decisión, y
    borrarla en silencio sería el mismo defecto mudo que esta obra viene a matar.

    El mitigante existe para UN stack: `finanzas-serve:50-58` exporta sus cinco claves antes
    del exec, así que cuando el `setdefault` del stack corre ya tiene el valor de la casa.
    Es de un script y vale para uno; el mecanismo es del `Popen` y vale para los seis.
    Ciencia no tiene launcher donde poner esa lista.
    """
    declaradas, origen = canonicas_declaradas(meta)
    heredadas = [n for n in declaradas if (entorno_hijo.get(n) or "").strip()]
    return {"canonicas_declaradas": declaradas,
            # De dónde salió la tabla. Va en la salida porque un «0 heredadas» con
            # `tabla: sin_tabla` NO es la misma afirmación que con `tabla: catalogo`: el
            # primero es silencio y el segundo es una medición.
            "tabla": origen,
            "heredadas": heredadas,
            # El vocabulario es el de `exclusividad_del_cerebro` a propósito: quien ya leyó
            # ese campo en la salida del `enter` no tiene que aprender otro.
            "reparadas": [],
            "sin_reparar": heredadas}


def causa_de_credenciales(cred: dict) -> tuple[str, str]:
    """De lo que pasó en el `enter` a UNA causa con su detalle. `("", "")` si no hay nada.

    Vive acá y no en el endpoint por una razón de medición: adentro de la función de HTTP
    esta decisión no se puede llamar, y una vara que no puede llamar a lo que elige la causa
    no mide la elección — mide que el diccionario de copys tenga entradas, que es otra cosa.
    El COPY sigue del lado del router, con los otros copys; acá se elige, allá se redacta.

    La prioridad es la sombra primero: es la única de las tres donde el stack va a usar OTRA
    credencial, y el único que puede deshacerlo es el usuario.
    """
    escr = cred.get("escritura") or {}
    verif = cred.get("verificacion") or escr           # Ciencia verifica en su escritura
    sombra = cred.get("sombra") or {}
    if sombra.get("heredadas"):
        return "credencial_sombreada", "heredadas del entorno: " + ", ".join(sombra["heredadas"])
    if verif.get("no_coinciden"):
        return "credencial_no_coincide", "no coinciden: " + ", ".join(map(str, verif["no_coinciden"]))
    # ⚠️ SE AVISA CUANDO NO SE PUDO CONFIRMAR **NADA**, NO CUANDO QUEDÓ ALGO SIN CONFIRMAR.
    # La diferencia la destapó el `enter` real de Ciencia: su `sin_verificar` sano trae los
    # nombres que su `mapServiceEnv` deriva y que NO están en `env-alias.json` —`GH_TOKEN`,
    # `HUGGING_FACE_HUB_TOKEN`— porque sobre ésos la sonda no afirma. O sea que en una
    # corrida PERFECTA la lista viene con dos nombres, y mi primera condición avisaba igual.
    # Un aviso que salta en un `enter` sano no se lee, que es lo que yo mismo había escrito
    # tres líneas más arriba y no había aplicado acá.
    #
    # `sin_verificar` sigue viajando en el dato para quien audite; lo que no hace es disparar
    # el aviso por sí solo.
    if escr.get("escritas") and not verif.get("verificadas"):
        detalle = "sin confirmar ninguna de: " + ", ".join(map(str, escr["escritas"]))
        if verif.get("causa"):
            detalle += f" · {verif['causa']}"
        return "credencial_sin_verificar", detalle
    return "", ""


def resolver_credenciales(meta: dict, resolver) -> tuple[dict[str, str], list[str]]:
    """Del vault de la casa a `{vault_slug: cleartext}`. Devuelve además los que faltan.

    NO SE ESCRIBE UN LECTOR DE VAULT ACÁ. El que existe es
    `credential_broker.make_user_resolver(user_id)` y hace las cinco cosas que el destino
    pide: descifra Fernet, está LIGADO al `user_id` del run, RECHAZA un `byok_ref` que
    nombre otro usuario (`credential_broker.py:249`), refresca OAuth si hace falta, y el
    cleartext nunca toca un log ni una respuesta HTTP. Acá se lo invoca, nada más.

    `resolver` se recibe por parámetro y no se construye adentro para que la vara pueda
    pasar uno sintético sin una DB — el mismo patrón que usa el assembler con
    `byok_resolver`.
    """
    valores: dict[str, str] = {}
    faltantes: list[str] = []
    for e in _cred_entradas(meta):
        slug = e["vault"]
        if slug in valores or slug in faltantes:
            continue
        try:
            secreto = (resolver(slug) or "").strip() if resolver else ""
        except Exception:                               # noqa: BLE001 — frontera del vault
            secreto = ""
        if secreto:
            valores[slug] = secreto
        else:
            # SIN VALOR NO ES UN ERROR: es el caso normal de un usuario que todavía no
            # cargó esa llave. Se nombra y se sigue; lo que no puede pasar es escribir una
            # cadena vacía en el archivo del stack y que el stack la lea como «configurada».
            faltantes.append(slug)
    return valores, faltantes


def _fusionar_json(destino: Path) -> tuple[dict, Optional[str]]:
    """Lee un JSON de destino para MERGEAR encima. Devuelve `(cuerpo, causa_si_ilegible)`.

    ⚠️ MERGEAR Y NO REEMPLAZAR, y no es una preferencia de estilo: los dos destinos que usan
    esta función guardan cosas del usuario al lado de la credencial. El
    `preferences.json` de Legal lleva las once preferencias de redacción del estudio
    (`services/ingest/src/preferences.ts:16-41`) y el store de MCP de Educación mergea a
    propósito «so a partial edit (rotating one key of three)» funcione
    (`services/mcp/secrets.py:69-71`). Reemplazar sería borrarle trabajo al usuario para
    entregarle una llave.

    ⚠️ Y UN DESTINO ILEGIBLE NO SE PISA. Se devuelve la causa y el llamador NO escribe. El
    lector de Legal hace `JSON.parse(readFileSync(...))` sin `try` (`lib/research.ts:84`):
    si el archivo está roto, su stack ya está roto, y sobrescribirlo lo «arreglaría»
    borrando las preferencias — cambiar un fallo visible por una pérdida muda.
    """
    if not destino.exists():
        return {}, None
    try:
        cuerpo = json.loads(destino.read_text(encoding="utf-8"))
    except Exception as e:                              # noqa: BLE001 — frontera de disco
        return {}, f"{type(e).__name__}"
    if not isinstance(cuerpo, dict):
        return {}, "no_es_objeto"
    return cuerpo, None


def escribir_credenciales(ws: str, meta: dict, valores: dict[str, str]) -> dict[str, Any]:
    """[F1 · A] Escribe las credenciales del vault donde el stack de ESTA fila ya lee.

    Una rama por forma real. Devuelve qué se escribió —por NOMBRE, nunca por valor— para que
    el `enter` lo publique y la vara lo lea.

    La rama de Ciencia NO está acá y es a propósito: su destino no es un archivo sino
    `PUT /settings/credentials/:id`, y una llamada HTTP no se puede hacer antes de que el
    proceso exista. Vive en `enchufar_credenciales`, junto a `enchufar_cerebro`, que es el
    otro que se configura por HTTP y por el mismo motivo.
    """
    formato = meta.get("cred_format")
    parte: dict[str, Any] = {"formato": formato, "escritas": [], "sin_valor": [],
                             "descartadas": [], "destino": "", "causa": ""}
    if not formato:
        return parte
    if formato not in _CRED_FORMATOS:
        # FALLO VISIBLE, JAMÁS MUDO (CLAUDE.md §1): una fila con un formato que este archivo
        # no sabe escribir se dice por nombre. Callarlo daría un `enter` verde con el
        # workspace sin credenciales y sin una pista de por qué.
        parte["causa"] = f"cred_format_desconocido:{formato}"
        return parte

    entradas = _cred_entradas(meta)

    # ── LEGAL · el JSON plano del estudio ───────────────────────────────────────────────
    # `$WORKSPACE_ROOT/.preferences/preferences.json`, releído por LLAMADA
    # (`lib/research.ts:78-84`), así que una escritura del `enter` aplica en el turno
    # siguiente sin reiniciar el motor. Y se escribe 0600: hoy su propio escritor lo deja
    # en 0644 (`preferences.ts:66`, `writeFileSync` sin `mode`) con la key de Exa adentro.
    if formato == "preferences_json":
        destino = _sub(ws, "data") / ".preferences" / "preferences.json"
        parte["destino"] = str(destino)
        cuerpo, ilegible = _fusionar_json(destino)
        if ilegible:
            parte["causa"] = f"destino_ilegible:{ilegible}"
            return parte
        for e in entradas:
            campo = e.get("campo")
            if not campo:
                parte["descartadas"].append(e["vault"]); continue
            if e["vault"] not in valores:
                parte["sin_valor"].append(e["vault"]); continue
            cuerpo[campo] = valores[e["vault"]]
            parte["escritas"].append(campo)
        _escribir_json_0600(destino, cuerpo)
        return parte

    # ── EDUCACIÓN · un archivo por servidor MCP, indexado por DUEÑO ─────────────────────
    # `<runtime>/data/system/user-secrets/<owner>/private/mcp/<server>.json`
    # (`multi_user/paths.py:220-238` + `services/mcp/secrets.py:38-64`). Es el destino más
    # parecido al vault de los seis: ya está por dueño, ya es 0600, y su lector resuelve
    # `${secret:<server>/<field>}` desde disco EN CADA referencia (`secrets.py:113`), sin
    # caché que invalidar.
    #
    # ⚠️ EL DUEÑO LO DECLARA LA FILA. El espacio de ids de dueño de Educación es SUYO
    # (`LOCAL_ADMIN_ID = "local-admin"`, `multi_user/models.py:82`), no el `user_id` de
    # Aleph: pasarle el nuestro escribiría en un dir que su lector no mira.
    if formato == "mcp_secrets":
        raiz = (raiz_pack(ws) / "runtime" / "data" / "system" / "user-secrets"
                / str(meta.get("cred_owner") or "local-admin") / "private" / "mcp")
        parte["destino"] = str(raiz)
        raiz.mkdir(parents=True, exist_ok=True)
        # 0700 EN TODA LA CADENA, no sólo en la punta. Su propio código re-afirma el modo de
        # `user-secrets` Y del dir del dueño en cada lectura, «rather than assumed […] the cost
        # of being wrong is a world-readable refresh token» (`multi_user/paths.py:232-237`).
        # Mi primera versión chmodeaba dos de los cuatro y dejaba `private` y `user-secrets`
        # con lo que hubiera puesto el `mkdir`.
        for d in (raiz.parent.parent.parent, raiz.parent.parent, raiz.parent, raiz):
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass                                    # un dir ajeno no se fuerza; se sigue
        por_server: dict[str, list[dict]] = {}
        for e in entradas:
            if not e.get("server") or not e.get("campo"):
                parte["descartadas"].append(e["vault"]); continue
            por_server.setdefault(e["server"], []).append(e)
        for server, es in por_server.items():
            destino = raiz / f"{server}.json"
            cuerpo, ilegible = _fusionar_json(destino)
            if ilegible:
                # Su propio lector trata un archivo ilegible como vacío con un warning
                # (`secrets.py:164`), así que acá tampoco se revienta: se nombra y se salta
                # ESE server, no los otros.
                parte["descartadas"].append(server); continue
            escribio = False
            for e in es:
                if e["vault"] not in valores:
                    parte["sin_valor"].append(e["vault"]); continue
                cuerpo[e["campo"]] = valores[e["vault"]]
                parte["escritas"].append(f"{server}/{e['campo']}")
                escribio = True
            if escribio:
                _escribir_json_0600(destino, cuerpo)
        return parte

    # ── OFICINA · el JSON con esquema que su shell inyecta a cada hijo ──────────────────
    # ⚠️ DOS TRAMPAS MEDIDAS EN FASE 0, LAS DOS PAGADAS ACÁ:
    #   1. `EnvService` CACHEA y no reinvalida: `ensureLoaded()` pone `loaded = true` y no
    #      vuelve al disco nunca (`env-file.ts:167-180`). La carga es PEREZOSA, así que
    #      escribir en el `enter` —antes de que exista el proceso— llega; escribir después
    #      del primer `list()` no se ve hasta reiniciar. Por eso esta rama corre ANTES del
    #      spawn y no después de la salud.
    #   2. El store se ESCAPABA del pack: `openworkEnvStorePath` sólo honra
    #      `OPENWORK_ENV_STORE` (`packages/paths/index.mjs:73-79`) y la fila declaraba las
    #      otras cuatro variables de `paths.mjs` pero no ésa, así que `env.json` aterrizaba
    #      en `~/.config/openwork/`. La fila ahora la declara y el destino se lee de ahí.
    if formato == "env_json":
        destino = Path(_ruta_env_store(ws, meta))
        parte["destino"] = str(destino)
        cuerpo, ilegible = _fusionar_json(destino)
        if ilegible:
            parte["causa"] = f"destino_ilegible:{ilegible}"
            return parte
        previas = {v.get("key"): v for v in (cuerpo.get("variables") or [])
                   if isinstance(v, dict) and v.get("key")}
        ahora = int(time.time() * 1000)
        for e in entradas:
            clave = e.get("clave")
            if not clave:
                parte["descartadas"].append(e["vault"]); continue
            if e["vault"] not in valores:
                parte["sin_valor"].append(e["vault"]); continue
            previas[clave] = {"key": clave, "value": valores[e["vault"]], "updatedAt": ahora}
            parte["escritas"].append(clave)
        _escribir_json_0600(destino, {
            "schemaVersion": 1, "updatedAt": ahora,
            # Ordenado por clave como hace su propio escritor (`env-file.ts:210`), para que
            # dos `enter` seguidos con lo mismo produzcan el mismo archivo.
            "variables": [previas[k] for k in sorted(previas)]})
        return parte

    # ── FINANZAS · las líneas de más en el `.env` que ya escribimos ─────────────────────
    # El precedente de esta obra entera. Se AGREGAN al archivo que `_escribir_config_dotenv`
    # acaba de escribir (lo reemplaza entero en cada `enter`), así que esta rama tiene que
    # correr DESPUÉS de `escribir_config` — si corriera antes, el escritor del cerebro se
    # llevaría las credenciales puestas.
    #
    # ⚠️ Y LA CLAVE VA AL `case` DEL LANZADOR EN EL MISMO COMMIT. El launcher lee SÓLO las
    # claves que nombra (`finanzas-serve:45`, «Se leen SÓLO las claves que Aleph escribe»):
    # una clave nueva en el archivo y ausente del `case` no llega al stack, y el `.env`
    # seguiría siendo el nuestro, así que la comparación del cerebro daría verde igual.
    if formato == "dotenv_extra":
        destino = _sub(ws, "data") / meta.get("config_file", ".env")
        parte["destino"] = str(destino)
        if not destino.exists():
            parte["causa"] = "dotenv_ausente"           # el escritor del cerebro no corrió
            return parte
        lineas = []
        for e in entradas:
            clave = e.get("clave")
            if not clave:
                parte["descartadas"].append(e["vault"]); continue
            if e["vault"] not in valores:
                parte["sin_valor"].append(e["vault"]); continue
            lineas.append(f"{clave}={valores[e['vault']]}")
            parte["escritas"].append(clave)
        if lineas:
            previo = destino.read_text(encoding="utf-8").rstrip("\n")
            tmp = destino.with_suffix(".env.tmp")
            tmp.write_text("\n".join([previo, *lineas]) + "\n", encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, destino)
        return parte

    # ── DISEÑO · por el puntero, porque su config la escribe SU lanzador ────────────────
    # No hay archivo nuestro que escribir: el `config.toml` lo produce `bin/aleph-codesign`
    # justo antes de levantar Electron, y dos escritores para un archivo es una carrera con
    # ganador fijo (ver el comentario de `config_format == "launcher"`). El único canal es
    # `aleph-pack.json`, que ya es 0600 y ya lo lee el lanzador por `ALEPH_PACK_CONFIG`.
    #
    # ⚠️ EL VALOR VIAJA CON PREFIJO. `decryptSecret` acepta tres formas y sólo tres:
    # `safe:<base64>` (Electron safeStorage), `plain:<texto>`, o crudo — y el crudo cae en la
    # rama legacy de safeStorage y LEVANTA (`keychain.ts:29-41`). La casa no puede producir
    # `safe:` porque esa llave es del Keychain del usuario y vive del otro lado de Electron,
    # así que manda `plain:` y el lanzador lo pasa tal cual: el archivo de destino es 0600
    # y el prefijo es parte del contrato del stack, no un downgrade que inventamos.
    if formato == "puntero_launcher":
        parte["destino"] = str(_sub(ws, "config") / "aleph-pack.json")
        for e in entradas:
            if not e.get("proveedor"):
                parte["descartadas"].append(e["vault"]); continue
            if e["vault"] not in valores:
                parte["sin_valor"].append(e["vault"]); continue
            parte["escritas"].append(e["proveedor"])
        # El cuerpo lo arma `escribir_ajustes_plugin`, que es el dueño de ese archivo; acá
        # sólo se declara QUÉ se le pidió escribir. Un segundo escritor sobre el mismo
        # archivo sería la carrera que este formato existe para evitar.
        return parte

    # ── CIENCIA · no es un archivo ─────────────────────────────────────────────────────
    parte["causa"] = "se_configura_por_http"            # ver `enchufar_credenciales`
    return parte


def _ruta_env_store(ws: str, meta: dict) -> str:
    """El `env.json` de Oficina, resuelto igual que lo resuelve su propio código.

    Se lee de la MISMA declaración que recibe el stack (`OPENWORK_ENV_STORE` en el `env` de
    la fila) en vez de recomponer la ruta acá: dos fuentes para una ruta es el defecto que
    dejó el `env.json` afuera del pack en primer lugar.
    """
    plantilla = (meta.get("env") or {}).get("OPENWORK_ENV_STORE")
    if plantilla:
        return str(plantilla).format(config=str(_sub(ws, "config")),
                                     data=str(_sub(ws, "data")),
                                     log=str(_sub(ws, "log")),
                                     proyecto=str(_sub(ws, meta.get("label") or "proyecto")),
                                     recursos=str(_ap.resource_root()),
                                     raiz=str(raiz_pack(ws)))
    return str(_sub(ws, "config") / "env.json")


def _igual(a: str, b: str) -> bool:
    """Compara dos secretos sin filtrar por tiempo y sin imprimir ninguno."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def verificar_credenciales(ws: str, meta: dict, valores: dict[str, str]) -> dict[str, Any]:
    """[F1 · B] Releer lo que el stack va a recibir DE VERDAD. Nunca creerle a la escritura.

    LA DECISIÓN DEL DUEÑO, Y POR QUÉ NO ALCANZA NADA MÁS BARATO. Medido en Ciencia contra el
    binario que ship-ea: con un campo que el stack no puede descifrar,
    `GET /settings/credentials` devuelve `connected: True`, `set_fields` INCLUYE el campo, el
    env del hijo está vacío y el log tiene **0 líneas**. Y un `PUT` con un nombre de campo
    que su spec no conoce devuelve **200** y descarta el valor en silencio
    (`credentials.ts:512`). O sea: ni el 200 ni el `connected` son evidencia. La única
    evidencia es volver a leer.

    Acá se verifica lo que se puede verificar SIN levantar el stack —el archivo escrito— y se
    dice por nombre qué quedó sin verificar. Lo que exige un proceso vivo (el env del hijo de
    Ciencia) lo hace `enchufar_credenciales` después de la salud.
    """
    parte: dict[str, Any] = {"verificadas": [], "no_coinciden": [], "sin_verificar": [],
                             "causa": ""}
    formato = meta.get("cred_format")
    entradas = _cred_entradas(meta)
    if not formato or formato == "http_credentials":
        # No es un archivo: la verificación de Ciencia es la sonda, y vive con su escritura.
        parte["sin_verificar"] = [e["vault"] for e in entradas]
        parte["causa"] = "verifica_por_sonda" if formato else ""
        return parte
    if formato == "puntero_launcher":
        # LO QUE SE PUEDE PROBAR Y LO QUE NO, DICHO. Se relee el puntero —que es lo que la
        # casa escribe— y ahí termina nuestra evidencia: que el lanzador lo traduzca a su
        # `config.toml` y que Electron lo cargue son dos eslabones del otro lado, y afirmar
        # que llegaron sin medirlos sería el verde falso que esta obra combate.
        destino = _sub(ws, "config") / "aleph-pack.json"
        cuerpo, ilegible = _fusionar_json(destino)
        if ilegible:
            parte["causa"] = f"puntero_ilegible:{ilegible}"
            parte["sin_verificar"] = [e["vault"] for e in entradas]
            return parte
        puestas = (cuerpo.get("credenciales") or {})
        for e in entradas:
            prov = e.get("proveedor")
            if e["vault"] not in valores or not prov:
                continue
            # El puntero lleva el valor con prefijo: se compara contra lo que se pidió poner.
            if _igual(str(puestas.get(prov, "")), "plain:" + valores[e["vault"]]):
                parte["verificadas"].append(prov)
            else:
                parte["no_coinciden"].append(prov)
        parte["sin_verificar"] = ["launcher→config.toml", "electron→AuthStorage"]
        return parte

    if formato == "preferences_json":
        destino = _sub(ws, "data") / ".preferences" / "preferences.json"
        cuerpo, ilegible = _fusionar_json(destino)
        campos = {e.get("campo"): e["vault"] for e in entradas if e.get("campo")}
        leidos = cuerpo
    elif formato == "mcp_secrets":
        raiz = (raiz_pack(ws) / "runtime" / "data" / "system" / "user-secrets"
                / str(meta.get("cred_owner") or "local-admin") / "private" / "mcp")
        ilegible = None
        leidos, campos = {}, {}
        for e in entradas:
            if not e.get("server") or not e.get("campo"):
                continue
            cuerpo, malo = _fusionar_json(raiz / f"{e['server']}.json")
            if malo:
                parte["sin_verificar"].append(e["vault"]); continue
            etiqueta = f"{e['server']}/{e['campo']}"
            leidos[etiqueta] = cuerpo.get(e["campo"], "")
            campos[etiqueta] = e["vault"]
    elif formato == "env_json":
        cuerpo, ilegible = _fusionar_json(Path(_ruta_env_store(ws, meta)))
        leidos = {v.get("key"): v.get("value", "") for v in (cuerpo.get("variables") or [])
                  if isinstance(v, dict)}
        campos = {e.get("clave"): e["vault"] for e in entradas if e.get("clave")}
    else:                                               # dotenv_extra
        destino = _sub(ws, "data") / meta.get("config_file", ".env")
        ilegible = None if destino.exists() else "ausente"
        leidos = {}
        if not ilegible:
            for linea in destino.read_text(encoding="utf-8").splitlines():
                if "=" in linea:
                    k, _, v = linea.partition("=")
                    leidos[k] = v
        campos = {e.get("clave"): e["vault"] for e in entradas if e.get("clave")}

    if ilegible:
        parte["causa"] = f"destino_ilegible:{ilegible}"
        parte["sin_verificar"] = [e["vault"] for e in entradas]
        return parte
    for campo, slug in campos.items():
        if slug not in valores:
            continue                                    # sin valor no se verifica: no se pidió
        if _igual(str(leidos.get(campo, "")), valores[slug]):
            parte["verificadas"].append(campo)
        else:
            parte["no_coinciden"].append(campo)
    return parte


# ── CIENCIA · LA CREDENCIAL POR HTTP, Y LA SONDA QUE LA PRUEBA ──────────────────────────
#
# Su destino no es un archivo: es `PUT /settings/credentials/:id`, y el stack cifra con SU
# llave (`credentials.key`, 32 bytes, local a la máquina y al dir de datos). Por eso la casa
# no le escribe el store: se lo pide. Medido contra el binario que ship-ea:
#   · el PUT acepta un `curl` pelado (sin auth de ninguna clase)  → 200
#   · el stack cifra: 0 coincidencias del valor en claro en `credentials.json`, 0600
#   · `applyCredentialEnv()` corre en el save Y en el delete, EN VIVO
#   · sobrevive al reinicio y hasta a un cambio de binario (la llave vive en el data dir)
#
# ⚠️ UN SERVICIO POR LLAMADA. La ruta es `/:id`; varios CAMPOS en un PUT sí, varios servicios
# no. Y el nombre de campo tiene que ser exacto: uno que su spec no conozca devuelve 200 y se
# descarta en silencio (`credentials.ts:512`).

#: El sobre de la sonda: un «servidor MCP» local que volca su entorno y SALE.
#:
#: ⚠️ SALE, NO BLOQUEA — Y LA PRIMERA VERSIÓN DE ESTO HACÍA `sleep 20` POR UN DIAGNÓSTICO
#: FALSO. En la medición de Fase 0 un `openscience serve` se murió sin dejar rastro y le eché
#: la culpa a mi sonda («un `exit 0` le deja un EOF al cliente MCP»). No fue la sonda: otra
#: sesión lo había matado por PID. Pero el `sleep` quedó, y costaba caro — medido acá, las
#: tres variantes contra el pack vivo:
#:
#:     sleep 20  → PUT /mcp/<n>/config  TimeoutError tras 8 s   · volcó 4273 b
#:     sleep 2   → PUT                  TimeoutError tras 8 s   · volcó 4273 b
#:     exit 0    → PUT                  HTTP 200 en 0,2 s       · volcó 4273 b
#:
#: O sea: el PUT espera el handshake MCP y un proceso que no habla MCP lo hace esperar hasta
#: SU timeout, dure lo que dure el sleep. Con `exit 0` el EOF cierra el handshake enseguida y
#: el PUT contesta. El volcado ocurre en los tres, porque lo que la medición necesita es el
#: SPAWN, no la conversación.
#:
#: El spawn pasa por `mcp/index.ts:459 → OpenScience.subprocessEnv(process.env)`, la MISMA
#: función que usa `tool/bash.ts:280`, así que lo que la sonda ve es lo que verá una tool.
_SONDA_SH = "#!/bin/sh\nenv > \"$SONDA_OUT\"\nexit 0\n"


def enchufar_credenciales(ws: str, meta: dict, valores: dict[str, str], *,
                          url: str) -> dict[str, Any]:
    """[F1 · A+B para Ciencia] Le PIDE al stack que guarde, y después lo comprueba midiendo.

    La verificación es una sonda-subproceso y no una relectura de la API, porque la API
    miente por diseño: `connected` mira si hay claves en el store, no si se pueden descifrar
    (`credentials.ts:432`). Se levanta la sonda, se lee el entorno REAL que recibiría una
    tool, y se borra la sonda del config del stack — no se le deja al usuario un servidor MCP
    de mentira en su pantalla.
    """
    parte: dict[str, Any] = {"formato": "http_credentials", "escritas": [], "sin_valor": [],
                             "descartadas": [], "verificadas": [], "no_coinciden": [],
                             "sin_verificar": [], "causa": ""}
    por_servicio: dict[str, dict[str, str]] = {}
    for e in _cred_entradas(meta):
        if not e.get("servicio") or not e.get("campo"):
            parte["descartadas"].append(e["vault"]); continue
        if e["vault"] not in valores:
            parte["sin_valor"].append(e["vault"]); continue
        por_servicio.setdefault(e["servicio"], {})[e["campo"]] = valores[e["vault"]]
    if not por_servicio:
        return parte

    for servicio, campos in por_servicio.items():
        # `_pedir_json` devuelve `(status, cuerpo)` y LEVANTA si no hay con quién hablar
        # (`URLError`/timeout no los atrapa). Se envuelve acá: un stack que no contesta deja
        # esa credencial nombrada en `descartadas`, no tira el `enter`.
        try:
            estado, _ = _pedir_json(f"{url}/settings/credentials/{servicio}", metodo="PUT",
                                    cuerpo={"fields": campos})
        except Exception:                               # noqa: BLE001 — frontera HTTP
            estado = 0
        # Y EL 200 NO SE TOMA COMO PRUEBA: sólo dice que se pidió. Lo que prueba es la sonda.
        if estado != 200:
            parte["descartadas"].append(servicio); continue
        parte["escritas"].extend(f"{servicio}/{c}" for c in campos)

    # ── LA SONDA. Es lo único que prueba que la credencial LLEGÓ. ───────────────────────
    # QUÉ NOMBRE ESPERAR EN EL ENV DEL HIJO. Ciencia no usa el canónico del catálogo: lo
    # DERIVA su propio `mapServiceEnv` (`credentials.ts:232-309`) del id de servicio. Las dos
    # tablas coinciden en varios (`github → GITHUB_TOKEN`, `huggingface → HF_TOKEN`) y no en
    # todos, así que se cruzan: se espera el nombre que esté en LAS DOS. Un nombre que sólo
    # existe en una de las dos tablas no se afirma ni se niega — va a `sin_verificar`.
    canon, origen_tabla = canonicas_declaradas(meta)
    parte["tabla"] = origen_tabla
    esperado: dict[str, str] = {}
    sin_cruce: list[str] = []
    for e in _cred_entradas(meta):
        valor = valores.get(e["vault"], "")
        if not valor:
            continue
        propias = [n for n in (e.get("env_del_stack") or []) if n]
        if not propias:
            sin_cruce.append(e["vault"])
            continue
        for n in propias:
            if n in canon:
                esperado[n] = valor
            else:
                sin_cruce.append(n)
    parte["sin_verificar"] = sorted(set(sin_cruce))
    if not esperado:
        parte["causa"] = "sin nombre cruzado entre las dos tablas"
        return parte
    vista = _entorno_de_una_sonda(ws, url)
    if vista is None:
        # LA AUSENCIA DE UNA SEÑAL NO ES UNA MEDICIÓN. Si la sonda no escribió, no se
        # concluye «no llegó»: se dice que no se pudo medir y por qué.
        parte["causa"] = "sonda_sin_salida"
        parte["sin_verificar"] = sorted(set(parte["sin_verificar"]) | set(esperado))
        return parte
    # EL CONTROL POSITIVO, ADENTRO DE LA MEDICIÓN. Una sonda que no volcó nada útil daría
    # «0 coincidencias» idéntico a «la credencial no llegó»: son dos cosas distintas y hay
    # que poder distinguirlas. Si la sonda no vio ni una variable que el pack le puso, la
    # sonda no midió — es la lección de la Fase 0, donde tres «SE FUE» sobre un archivo
    # inexistente parecían justo el resultado que yo esperaba.
    if not any(k.startswith("ALEPH_PACK_") or k == "OPENSCIENCE_DATA_DIR" for k in vista):
        parte["causa"] = "sonda_sin_control_positivo"
        parte["sin_verificar"] = sorted(set(parte["sin_verificar"]) | set(esperado))
        return parte
    for nombre, valor in esperado.items():
        if _igual(vista.get(nombre, ""), valor):
            parte["verificadas"].append(nombre)
        else:
            parte["no_coinciden"].append(nombre)
    return parte


def _entorno_de_una_sonda(ws: str, url: str) -> Optional[dict[str, str]]:
    """Levanta la sonda MCP, devuelve el entorno que vio un subproceso, y se limpia sola."""
    dir_sonda = _sub(ws, "log") / "cred-sonda"
    dir_sonda.mkdir(parents=True, exist_ok=True)
    os.chmod(dir_sonda, 0o700)
    script = dir_sonda / "sonda.sh"
    salida = dir_sonda / "env.txt"
    nombre = f"aleph-cred-sonda-{int(time.time() * 1000):x}"
    try:
        script.write_text(_SONDA_SH, encoding="utf-8")
        os.chmod(script, 0o700)
        salida.unlink(missing_ok=True)
        # ⚠️ NO SE CORTA POR EL ESTADO DEL PUT, Y ESO ES LA OTRA MITAD DE UNA REGLA QUE YA
        # TENÍA A MEDIAS. «Un 200 no prueba que el estado cambió» — y su recíproca, que me
        # faltaba: **un NO-200 no prueba que no cambió.** Medido: con la sonda que bloqueaba,
        # el PUT daba TimeoutError y el volcado estaba en disco igual, porque el spawn ya
        # había ocurrido. Mi versión anterior devolvía `None` ahí y reportaba
        # `sonda_sin_salida` teniendo la evidencia al lado. Ahora se pide, y después se
        # mira el disco pase lo que pase con la respuesta.
        #
        # No hay `connect`: medido, el PUT de config **solo** ya spawnea el servidor. Una
        # llamada de más que no cambia el resultado es una llamada que puede fallar sola.
        try:
            _pedir_json(f"{url}/mcp/{nombre}/config", metodo="PUT", cuerpo={
                "config": {"type": "local", "command": [str(script)], "enabled": True,
                           "environment": {"SONDA_OUT": str(salida)}},
                "scope": "global"}, timeout=8.0)
        except Exception:                               # noqa: BLE001 — el spawn puede haber ocurrido
            pass
        for _ in range(60):                             # hasta ~6 s; el spawn es local
            if salida.exists() and salida.stat().st_size:
                break
            time.sleep(0.1)
        if not (salida.exists() and salida.stat().st_size):
            return None
        visto: dict[str, str] = {}
        for linea in salida.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in linea:
                k, _, v = linea.partition("=")
                visto[k] = v
        return visto
    except Exception:                                   # noqa: BLE001 — la sonda no rompe el enter
        return None
    finally:
        # NO SE LE DEJA AL USUARIO UN SERVIDOR MCP DE MENTIRA. Y el archivo con el entorno
        # volcado lleva secretos: se borra siempre, incluso si la medición falló.
        try:
            _pedir_json(f"{url}/mcp/{nombre}/config", metodo="DELETE", cuerpo=None)
        except Exception:                               # noqa: BLE001 — la limpieza no rompe
            pass
        for f in (salida, script):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass


#: [Gate 4 · F6-oficina] LAS DOS FORMAS DE CONFIG QUE SABE ESCRIBIR ESTA CASA, y por qué
#: son dos y no una. Ciencia enchufa su cerebro **por archivo**: su config declara el
#: provider y el stack lo lee al arrancar. OpenWork enchufa el suyo **por HTTP**, con un
#: PATCH que además recarga el motor; su archivo sirve para otra cosa (puerto, tokens,
#: workspaces). Meter las dos en un único cuerpo daría un archivo que ninguno de los dos
#: stacks entiende del todo, así que la fila declara su forma y acá se despacha.
_FORMA_POR_DEFECTO = "opencode_provider"


def _exclusividad_del_cerebro(meta: dict) -> dict[str, Any]:
    """[LEY 12] «DEJÁ VIVO SÓLO EL CEREBRO» — la declaración, en una sola pieza.

    Reemplaza a la lista negra por una lista blanca, y el motivo es aritmético: apagar por
    nombre obliga a nombrar a todos. Medido contra el motor de Legal con la lista negra
    puesta —`disabled_providers: ["opencode"]`, lo que hay hoy— el stack seguía ofreciendo
    **185 proveedores y 6.273 modelos**, porque el catálogo lo baja de `models.dev` en cada
    arranque y crece solo. Enumerar 184 para dejar uno no es una lista: es una carrera.

    El motor ya trae la palanca correcta y nadie la usaba: `enabled_providers` — *«When set,
    ONLY these providers will be enabled. All other providers will be ignored»*
    (`core/src/v1/config/config.ts:68`, y el de Ciencia la tiene igual en
    `backend/cli/src/config/config.ts:1135`). Se aplica en `provider.ts:1471-1475`, o sea
    **DESPUÉS** de fundir los proveedores declarados en config.

    Y eso último es lo que la vuelve un mecanismo y no una comprobación. MEDIDO con el
    ataque real —la capa legal declarando `provider: google-vertex`, que es exactamente lo
    que un `git merge upstream/dev` puede devolver:

        sin lista blanca  → /provider: 185 proveedores · 6.273 modelos
        con lista blanca  → /provider: 1 proveedor · 1 modelo · ids: ['aleph']
                            /config/providers: ['aleph']   ← google-vertex INVISIBLE

    No hace falta que la extirpación siga en pie para que el cerebro sea único: aunque el
    proveedor ajeno esté declarado, el motor no lo ve. Error imposible, no error detectado.

    ⚠️ LO QUE **NO** CIERRA, Y HAY QUE DECIRLO: las puertas de credencial. Medido en la
    misma corrida, `GET /provider/auth` sigue devolviendo **9 proveedores con método de
    auth** (openai/Codex, github-copilot, xai, poe, azure, digitalocean, las dos de
    cloudflare y gitlab). La lista blanca gobierna el CATÁLOGO; las puertas son la
    extirpación de Codex, que es obra aparte y sigue abierta.
    """
    if not meta.get("brain_exclusivo"):
        return {}
    return {"enabled_providers": [meta.get("brain_provider_id", "aleph")]}


def _cabeceras_aleph(ws: str, *, user_id: Optional[str], puppet_id: Optional[str]) -> dict:
    """Lo que viaja en cada llamada del stack al borde de dialecto.

    [LEY 15 · MODO RAW] `X-Aleph-Puppet` es OPCIONAL, y que lo sea es la mitad de la ley:
    sin agente, el borde resuelve el modelo del selector y el turno corre igual.
    `X-Aleph-Workspace` va SIEMPRE: es lo que hace que el paso caiga en el espacio de este
    workspace y no en el de al lado.
    """
    cabeceras: dict[str, str] = {"X-Aleph-Workspace": ws}
    if puppet_id:
        cabeceras["X-Aleph-Puppet"] = puppet_id
    if user_id:
        cabeceras["X-Aleph-User"] = user_id
    return cabeceras


def cuerpo_provider_aleph(ws: str, meta: dict, *, base_aleph: str, token: Optional[str],
                          user_id: Optional[str], puppet_id: Optional[str]) -> dict:
    """La entrada de proveedor que enchufa el cerebro de la casa, en el dialecto opencode.

    Es la MISMA pieza para las dos formas: Ciencia la escribe en su archivo y Oficina la
    manda por `PATCH /runtime-config/providers`. Que sea una sola función es lo que hace
    que «a un stack se le enchufa el nuestro» (ley 12) signifique lo mismo en los dos.
    """
    return {
        "name": meta.get("cerebro_label", "Aleph"),
        "npm": "@ai-sdk/openai-compatible",
        "options": {
            "baseURL": base_aleph.rstrip("/") + meta["brain_path"],
            # Sin sesión el borde contesta lo que corresponda; se manda vacío en vez
            # de omitirlo para que el cliente no invente su propia cabecera.
            "apiKey": token or "",
            "headers": _cabeceras_aleph(ws, user_id=user_id, puppet_id=puppet_id),
        },
        "models": {"cerebro": {"name": meta.get("cerebro_label", "Cerebro de Aleph")}},
    }


def _cuerpo_openwork_server(ws: str, meta: dict, *, puerto: int,
                            token: str, host_token: str) -> dict:
    """El `server.json` de OpenWork — **el vehículo de los secretos, y por eso archivo**.

    Los tokens NO viajan por `argv` ni por entorno aunque su CLI acepte `--token`: `ps` y
    `ps -E` los muestran, y es la misma razón por la que `escribir_ajustes_plugin` manda
    sólo el PUNTERO al archivo 0600. Acá el archivo ES la costura oficial del stack
    (`config.ts:251`: `fileConfig.token`), así que no hay nada que forzar.

    El `token` de cliente es además el que el propio server le inyecta a su `index.html`
    como `window.__OPENWORK_BOOTSTRAP__` (`static-ui.ts:129`), o sea que la UI queda
    autenticada sola: cero pantalla de login, cero token que el usuario pegue.
    """
    return {
        "host": "127.0.0.1",
        "port": puerto,
        "token": token,
        "hostToken": host_token,
        # El proyecto del workspace es el mismo dir que el pack ya le da de `cwd`: el
        # usuario entra a «Oficina» y sus archivos viven donde dice la etiqueta.
        "workspaces": [{"path": str(_sub(ws, meta.get("label") or "proyecto")),
                        "name": meta.get("label") or ws}],
    }


def _tender_enlaces(destino_dir: Path, mapa: dict) -> Path:
    """El cuerpo compartido de los dos puentes por enlace: `nombre → ruta en los recursos`.

    Se extrajo de `preparar_manos` cuando Legal necesitó exactamente lo mismo apuntando a
    otro sitio (ver `preparar_config_del_motor`). Es UN mecanismo con dos usos, no dos:
    enlazar es barato, no copia bytes y no toca el árbol importado.

    Lo que NO viajó no se finge: un origen ausente se saltea en silencio y el consumidor
    verá su ausencia como lo que es. Y un destino que ya existe **y no es un enlace nuestro**
    se respeta: puede ser algo del usuario, y borrarlo sería destruir dato ajeno para
    resolver un problema de plomería.
    """
    destino_dir.mkdir(parents=True, exist_ok=True)
    for nombre, rel in mapa.items():
        origen = _ap.resource_root() / rel
        destino = destino_dir / nombre
        # El nombre puede llevar subdirs (`.opencode/agent`): esos dirs intermedios son
        # NUESTROS y tienen que existir de verdad — es lo que evita que un consumidor que
        # escribe al lado del enlace termine escribiendo adentro del árbol importado.
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not origen.exists():
            continue                                        # lo que no viajó no se finge
        try:
            if destino.is_symlink():
                destino.unlink()                            # el nuestro de la visita anterior
            elif destino.exists():
                continue                                    # algo real y ajeno: no se toca
            destino.symlink_to(origen)
        except Exception:                                   # noqa: BLE001 — frontera
            continue
    return destino_dir


def preparar_manos(ws: str, meta: dict) -> Optional[Path]:
    """Deja las manos del workspace donde el motor las va a buscar: **en el PATH, con su
    nombre de pila**.

    Las skills de un stack llaman a su herramienta por el nombre corto (`gws gmail …`,
    `officecli …`), pero los binarios viajan con el sufijo de su release
    (`gws-macos-arm64`). Sin este puente el agente no encuentra la mano — y peor: la puerta
    de Ó11, que casa contra la ORDEN, tampoco reconocería un `…/gws-macos-arm64 gmail send`
    como un envío.

    Se resuelve con un dir de enlaces por pack, delante del PATH. No se copia el binario
    (son decenas de MiB) ni se toca el árbol importado.
    """
    manos = meta.get("hands") or {}
    if not manos:
        return None
    return _tender_enlaces(_sub(ws, "bin"), manos)


#: Lo que un kernel de ciencia necesita poder importar para no ser un adorno. `matplotlib`
#: es el que decide: es el que produce la imagen, y el que más veces falta.
_IMPORTS_DEL_KERNEL = ("matplotlib", "numpy", "scipy")

#: Candidatos de intérprete, de lo más DECLARADO a lo más encontrado. Mismo orden y mismo
#: criterio que el launcher de Educación (`platform/workspaces/launchers/deeptutor`), que
#: ya lo tenía resuelto y medido; acá se replica porque Ciencia no tiene launcher donde
#: ponerlo.
_CANDIDATOS_PYTHON = (
    "{stack}/bin/python3",
    "/opt/miniconda3/bin/python3",
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
)


def _importa_todo(binario: str) -> bool:
    """¿Este intérprete importa DE VERDAD lo que el kernel necesita?

    Se prueba, no se supone: en esta Mac hay cinco `python3` alcanzables y uno solo tiene
    matplotlib. Preguntarle a `PATH` habría funcionado en la máquina del que lo escribió y
    en ninguna otra.
    """
    prueba = "import " + ", ".join(_IMPORTS_DEL_KERNEL)
    try:
        return subprocess.run([binario, "-c", prueba], capture_output=True,
                              timeout=25).returncode == 0
    except Exception:  # noqa: BLE001 — un candidato que revienta es un candidato menos
        return False


def interprete_del_kernel(stack_dir: str) -> tuple[str, bool]:
    """Resuelve QUÉ intérprete va a usar el kernel, sin escribir nada.

    Está separado de `preparar_interprete` para que el gate del build y el runtime
    resuelvan con EL MISMO mecanismo: dos listas de candidatos que se van de gira por
    separado terminan diciendo cosas distintas el día que importa.

    Args:
        stack_dir: Ruta relativa del árbol del stack, para el candidato horneado.

    Returns:
        `(ruta, completo)` — la ruta elegida (vacía si no hay ninguna) y si ese intérprete
        importa TODO lo que el kernel necesita. Un `(ruta, False)` es un intérprete que
        sirve para calcular y no para graficar: se devuelve igual, para que el error que
        vea el usuario sea el REAL de Python y no un stack inventando que no puede.
    """
    stack = str(_ap.resource_root() / stack_dir)
    elegido = ""
    respaldo = ""
    for plantilla in _CANDIDATOS_PYTHON:
        cand = os.environ.get("ALEPH_CIENCIA_PYTHON") or plantilla.format(stack=stack)
        if not os.access(cand, os.X_OK):
            continue
        respaldo = respaldo or cand
        if _importa_todo(cand):
            elegido = cand
            break
    return (elegido or respaldo), bool(elegido)


def preparar_interprete(ws: str, meta: dict) -> Optional[Path]:
    """Deja un `python3` USABLE en el PATH del stack, para el que lo declare.

    POR QUÉ EXISTE. El kernel de Ciencia arranca su intérprete por PATH
    (`backend/cli/src/tool/notebook.ts:202`: `["python3", "python"]`), y una `.app` de macOS
    lanzada desde el Finder NO hereda el PATH del shell: ahí `python3` es `/usr/bin/python3`,
    que no tiene matplotlib. El tiro parabólico no producía su PNG por eso.

    LA COSTURA ES NUESTRA: el dir de «las manos» ya se antepone al PATH de cada pack, así que
    alcanza con dejar el shim adentro. Cero líneas del motor del stack.

    ES UN SHIM, NO UN ENLACE, y el motivo es `MPLBACKEND`: sin ella matplotlib elige en macOS
    el backend `MacOSX`, que quiere sesión gráfica; en un subproceso de un servicio eso es un
    cuelgue o una ventana robándole el foco al usuario. Mismo motivo que en Educación.

    Args:
        ws: El workspace.
        meta: Su fila declarada.

    Returns:
        El dir donde quedó el shim, o `None` si el pack no declara kernel.
    """
    if not meta.get("python_kernel"):
        return None

    elegido, _completo = interprete_del_kernel(meta.get("stack_dir") or "")
    if not elegido:
        return None

    destino_dir = _sub(ws, "bin")
    shim = destino_dir / "python3"
    shim.write_text(
        "#!/bin/sh\n"
        "# Shim de Aleph: el intérprete del kernel se DECLARA, no se hereda del PATH.\n"
        "export MPLBACKEND=\"${MPLBACKEND:-Agg}\"\n"
        f'exec "{elegido}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return destino_dir


def preparar_config_del_motor(ws: str, meta: dict) -> Optional[Path]:
    """Deja la CAPA DE CONFIG DEL STACK donde el motor la va a buscar. Misma idea que
    `preparar_manos`, otro destino.

    EL DEFECTO QUE TAPA, MEDIDO. doc.haus declara su oficio entero en `<repo>/dochaus` y lo
    carga apuntando ahí su `OPENCODE_CONFIG_DIR` (su `CLAUDE.md`, y su `start.sh` de
    upstream). Aleph le da a esa variable un dir POR DUEÑO —que es lo correcto: es donde va
    la sesión y el cerebro— y con eso `<repo>/dochaus` deja de estar en
    `config.directories()` (`packages/opencode/src/config/paths.ts:23-42`). Consecuencia
    medida contra la `.app`: **14 tools genéricas y CERO agentes**, contra 52 y 19 corriendo
    el mismo motor byte-idéntico como upstream lo declara. Todo turno de usuario moría en
    `Agent not found` con 500.

    LA COSTURA ES DEL PROPIO MOTOR, no una que haya que inventarle: además del dir de
    config, `directories()` incluye cada `.opencode` que encuentra SUBIENDO desde el
    directorio del turno. Los matters viven en `<data>/<matter>`, así que un `.opencode` en
    `<data>` está exactamente un nivel arriba de todos ellos.

    Medido sobre el árbol upstream con el motor byte-idéntico, cambiando SÓLO esto:
        sin el enlace  → 14 tools ·  0 agentes visibles   (el cuadro de la `.app` de hoy)
        con el enlace  → 52 tools · 19 agentes visibles
        y el `model` del pack GANA: `aleph/cerebro`, no el de la capa.

    ⚠️ SE ENLAZAN LAS CARPETAS DE CONTENIDO, JAMÁS EL DIRECTORIO ENTERO — y esto lo destapó
    la medición de esta misma obra, no una sospecha. Con `.opencode` apuntando al dir
    completo, el motor lo trata como config dir suyo y **escribe adentro del árbol
    importado**: le agregó `"$schema"` a `dochaus/opencode.json`, le puso un `.gitignore` y
    le corrió un `npm install` (92 paquetes + `package-lock.json` de 73 KB). Eso rompe la
    promesa de `start.sh:40` («Nothing is written into this imported tree»), ensucia el
    `git status` de cualquier máquina y, congelado, esas escrituras caen en la extracción
    `_MEI` de sólo lectura — el mismo modo de fallo que `env_dirs` documenta para Oficina.
    Enlazando `agent`, `skill`, `command` y `tool` por separado, el dir `.opencode` es
    NUESTRO y ahí caen sus escrituras.

    **`opencode.json` de la capa NO se enlaza, a propósito**, por dos razones que se
    refuerzan: el motor lo reescribiría a través del enlace, y su contenido ya viaja —
    permisos, `skills.paths`, `instructions`, `disabled_providers` y los cuatro agentes
    upstream apagados— en el archivo que `script/aleph-legal-config.ts` escribe sobre la
    config del pack. Enlazarlo sería tener la misma declaración en dos lugares.

    ⚠️ LA PRECEDENCIA NO ES LIBRE, Y ESTÁ MEDIDA. Aun sin enlazar su `opencode.json`, un
    config dir que declarara `provider` se FUNDIRÍA con el del pack (el `model` lo gana el
    pack; la clave `provider` se une). Hoy no hay nada que fundir porque la extirpación ya
    le sacó a `dochaus/opencode.json` su `provider`, su `model` y sus `mcp`. El día que un
    `git merge upstream/dev` los devuelva, la lista blanca de proveedores —la obra
    siguiente— es lo que tiene que hacer imposible el error, no una comprobación acá.
    """
    enlaces = meta.get("engine_config_links") or {}
    if not enlaces:
        return None
    return _tender_enlaces(_sub(ws, "data"), enlaces)


def _declarar_plugin_al_motor(ws: str, meta: dict,
                              user_id: Optional[str] = None) -> Optional[Path]:
    """Le declara al MOTOR el plugin de la casa, por su propio `OPENCODE_CONFIG_DIR`.

    Un stack que se configura por HTTP igual necesita que su motor cargue el plugin ANTES
    del primer turno, y el plugin no puede viajar en el `PATCH` de proveedores: ese endpoint
    sólo funde la clave `provider`.

    Se eligió esta vía —un `opencode.json` en el dir de config del motor— y no
    `POST /workspace/:id/plugins` porque esa ruta pasa por `requireApproval`
    (`server.ts:2379`), y una aprobación manual en medio del `enter` sería un workspace que
    no abre hasta que alguien diga que sí.

    Medido el 2026-08-10 contra el binario del motor: un plugin declarado acá **se carga
    aunque `OPENCODE_CONFIG` apunte a otro archivo** — las dos fuentes se funden.
    """
    plugin = _ruta_plugin(meta)
    if plugin is None:
        return None
    dir_motor = meta.get("engine_config_dir_env")
    if not dir_motor:
        return None
    destino = Path(entorno_de(ws, meta)[dir_motor]) / "opencode.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    cuerpo: dict[str, Any] = {"plugin": [plugin.as_uri()]}
    # [Ó11] LA PUERTA VIVE DONDE OCURRE LA ACCIÓN. Los envíos y borrados de las manos cloud
    # los ejecuta el MOTOR con su tool de bash, no el ToolRegistry de Aleph: `approval_gate`
    # no los ve y —lo que importa— tampoco podría frenarlos. Así que la retención la hace el
    # motor con SU sistema de permisos (`ask`/`allow`/`deny`, medido en el binario y
    # reflejado por su `/config`), y la casa audita por el plugin. Enforcement donde pasa la
    # cosa; auditoría en la casa.
    permisos = meta.get("engine_permissions")
    if permisos:
        cuerpo["permission"] = permisos
    # [LEY 12] EL SEGUNDO TRANSPORTE de la misma declaración. Un stack que enchufa su cerebro
    # por HTTP no puede mandar la exclusividad por ahí —el PATCH sólo funde `provider`— pero
    # su motor lee ESTE archivo igual que el de Ciencia lee el suyo. Por eso la lista blanca
    # no necesita dos mecanismos: necesita el mismo, escrito donde cada motor lo busca.
    cuerpo.update(_exclusividad_del_cerebro(meta))
    # [Ajustes por espacio] EL AJUSTE DEL DUEÑO VIAJA ACÁ, y no por el `PATCH` del server del
    # stack. Dos razones medidas, no de gusto:
    #
    #   1. Este archivo se REGENERA en cada `enter`. Escribirle encima desde afuera —que era
    #      la vía obvia— lo borraba en el siguiente arranque, sin una señal.
    #   2. El `PATCH /workspace/:id/config` del stack pide un token que vive DENTRO del
    #      iframe (`readOpenworkServerSettings`). Aleph no lo tiene, y fabricarle uno sería
    #      abrirle una puerta a la casa para escribir su propio ajuste.
    #
    # LO QUE ESTO NO HACE, y su copy lo dice en la cara: no toca un motor YA levantado. El
    # propio OpenWork lo admite en su texto —«Reload the engine after changing it»—, así que
    # el cambio agarra al abrir el espacio, no en el acto.
    cuerpo.update(_compactacion_del_dueno(ws, user_id))
    destino.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino


def _compactacion_del_dueno(ws: str, user_id: Optional[str]) -> dict:
    """`{"compaction": {"auto": bool}}` según el ajuste del dueño para ESTE espacio.

    Sin dueño devuelve `{}` en vez del default: un `enter` anónimo no tiene ajustes de
    nadie, y escribir el default igual sería pisar con «si» la elección de la persona que
    sí entró antes. Que el almacén no conteste tampoco puede tumbar un `enter` — el espacio
    abre con la conducta que ya tenía."""
    if not user_id:
        return {}
    try:
        from workspaces import memoria as _mem
        valor = _mem.ajustes(user_id, ws).get("compactacion")
    except Exception:
        return {}
    if valor not in ("si", "no"):
        return {}
    return {"compaction": {"auto": valor == "si"}}


def escribir_config(ws: str, meta: dict, *, base_aleph: str, token: Optional[str],
                    user_id: Optional[str], puppet_id: Optional[str],
                    space_id: Optional[str] = None, puerto: Optional[int] = None,
                    chat_id: Optional[str] = None, sid: Optional[str] = None,
                    tokens_stack: Optional[dict] = None) -> Path:
    """El archivo de config del pack — **generado, jamás a mano**.

    Es la costura de la ley 2 en su forma más barata: apuntar el stack al cerebro de Aleph
    es config pura, cero corte de código (probado en F3). Lo que esta función arregla es
    que esa config **la escribía una persona**, con el puerto del sidecar de ESA sesión
    adentro. Acá el `baseURL` sale del sidecar que está corriendo AHORA.

    Se reescribe en cada `enter` a propósito: el `apiKey` es la sesión de Aleph y las
    sesiones vencen. Refrescarla cuesta un `write` y evita el modo de fallo peor —el stack
    hablando con un cerebro que ya no lo reconoce, y el usuario leyendo «credencial
    inválida» adentro de un workspace que él nunca configuró.

    ⚠️ El secreto queda en un archivo del dir de datos del usuario, con permisos 0600. Es
    la misma clase de custodia que el resto de la casa (FileVault + 0600, ver la decisión
    de F5/keyring en Gate 2), y queda anotada como tal: no es el llavero Fernet.
    """
    # DeepTutor no consume el JSON de OpenCode de Ciencia: su contrato es el catálogo
    # `data/user/settings/model_catalog.json`. La rama vive acá —en la casa— para que
    # el árbol importado conserve su forma y para que la sesión nunca quede horneada en
    # un ejemplo dentro de third_party.
    if meta.get("config_format") == "deeptutor":
        runtime = raiz_pack(ws) / "runtime"
        settings = runtime / "data" / "user" / "settings"
        cabeceras: dict[str, str] = {"X-Aleph-Workspace": ws}
        if puppet_id:
            cabeceras["X-Aleph-Puppet"] = puppet_id
        if user_id:
            cabeceras["X-Aleph-User"] = user_id
        if space_id:
            cabeceras["X-Aleph-Space"] = space_id
        # [convergencia · superficie 1] EL HILO. `chat_id` ya era parámetro de esta función
        # y este dialecto era el único de los tres que no lo bajaba: la pantalla de
        # Educación creaba su hilo, lo bautizaba «Educación» y el borde no tenía con qué
        # anotarle un solo turno. Medido en la DB real antes de esta línea: 0 mensajes.
        if chat_id:
            cabeceras["X-Aleph-Chat"] = chat_id

        catalogo = {
            "version": 1,
            "services": {
                "llm": {
                    "active_profile_id": "aleph",
                    "active_model_id": "brain",
                    "profiles": [{
                        "id": "aleph",
                        "name": meta.get("cerebro_label", "Cerebro de Aleph"),
                        "binding": "custom",
                        "base_url": base_aleph.rstrip("/") + meta["brain_path"],
                        # Es el token de sesión del pack, nunca una key de proveedor.
                        "api_key": token or "",
                        "extra_headers": cabeceras,
                        "models": [{
                            "id": "brain",
                            "name": meta.get("cerebro_label", "Cerebro de Aleph"),
                            "model": "aleph/brain",
                        }],
                    }],
                },
                # LA OTRA MITAD DEL BORDE. Sin esta casilla el stack tiene cerebro y no
                # tiene memoria: su Knowledge Center queda muerto porque los cuatro
                # pipelines de RAG piden un «Active embedding model», y el único local
                # —`llamaindex`— fallaba su preflight por ese solo check.
                #
                # OJO CON LA URL: para `binding: custom` el stack guarda el ENDPOINT
                # COMPLETO y lo pega verbatim (`adapters/openai_compatible.py`: «URL
                # transparency: hit base_url verbatim»), a diferencia del `llm`, donde
                # guarda la base y el cliente le agrega `/chat/completions`. Por eso acá
                # va con `/embeddings` y allá no.
                "embedding": {
                    "active_profile_id": "aleph",
                    "active_model_id": "brain-embed",
                    "profiles": [{
                        "id": "aleph",
                        "name": meta.get("cerebro_label", "Cerebro de Aleph"),
                        "binding": "custom",
                        "base_url": (base_aleph.rstrip("/") + meta["brain_path"]
                                     + "/embeddings"),
                        "api_key": token or "",
                        "extra_headers": cabeceras,
                        "models": [{
                            "id": "brain-embed",
                            "name": meta.get("cerebro_label", "Cerebro de Aleph"),
                            "model": "aleph/embed",
                            # Vacío A PROPÓSITO: el propio stack lo completa con el largo
                            # REAL que devuelva la primera llamada. Fijarlo acá sería
                            # afirmar un número que la casa puede cambiar al cambiar de
                            # proveedor de embeddings, y un corpus queda sellado al largo.
                            "dimension": "",
                        }],
                    }],
                },
            },
        }
        _escribir_json_0600(settings / "model_catalog.json", catalogo)
        # El launcher de Educación lee el puerto desde el mismo runtime por dueño. El
        # frontend ocupa el puerto del pack; el API queda en el vecino y nunca se expone
        # como una segunda pantalla del producto.
        frontal = int(puerto or 0)
        sistema = {
            "version": 1,
            "backend_port": frontal + int(meta.get("backend_port_offset", 1)),
            "frontend_port": frontal,
            "next_public_api_base_external": f"http://127.0.0.1:{frontal + int(meta.get('backend_port_offset', 1))}" if frontal else "",
            "next_public_api_base": "",
            "cors_origin": "",
            "cors_origins": [f"http://127.0.0.1:{frontal}"] if frontal else [],
            "sandbox_allow_subprocess": False,
        }
        _escribir_json_0600(settings / "system.json", sistema)
        return settings / "model_catalog.json"

    # [F6] El registro elige el dialecto. Sin campo, el de Ciencia (el que ya existía).
    if meta.get("config_format") == "dotenv":
        return _escribir_config_dotenv(ws, meta, base_aleph=base_aleph, token=token,
                                       user_id=user_id, puppet_id=puppet_id,
                                       chat_id=chat_id, sid=sid)

    # [Diseño · obra 1] EL PACK CUYA CONFIG LA ESCRIBE SU PROPIO LANZADOR.
    #
    # Diseño no tiene un dialecto que esta función pueda escribir: su motor lee
    # `$XDG_CONFIG_HOME/open-codesign/config.toml`, un TOML `version = 3` que produce
    # `bin/aleph-codesign` justo antes de levantar Electron. Y tiene que producirlo ÉL,
    # porque la config depende de cosas que sólo el lanzador sabe (el dir del runtime
    # expandido, el espacio derivado de la sesión) y porque se escribe DESPUÉS de que el
    # puntero llega y ANTES de que el motor arranque. Dos escritores para un archivo sería
    # una carrera con ganador fijo: el que escribe último.
    #
    # Hasta acá esta función escribía IGUAL, en el dialecto de opencode, dentro de
    # `config/config.toml` — un archivo con nombre de TOML y contenido JSON, en una ruta
    # que el motor no abre nunca. MEDIDO en runtime (no leído en el código), con línea de
    # base y un `enter` limpio en medio:
    #
    #     config/config.toml               mtime=21:42:49  atime=21:42:49   ← sólo la escritura
    #     config/open-codesign/config.toml mtime=21:42:49  atime=21:42:50   ← el motor lo ABRE
    #
    # `atime == mtime` es la prueba: nadie lo leyó nunca. Y no era inofensivo, por dos
    # razones. La primera es que copiaba el token de sesión a un segundo archivo que no
    # cumple ninguna función: menos secreto en disco es mejor custodia. La segunda es la
    # que importa: `_exclusividad_del_cerebro` inyecta `enabled_providers` EN ESTE CUERPO.
    # Declararle `brain_exclusivo: True` a Diseño habría escrito la lista blanca en el
    # archivo muerto — el commit correcto, la clave presente, y cero efecto. Un mecanismo
    # que se ve adoptado y no hace nada es peor que uno que falta, porque nadie lo vuelve
    # a mirar.
    #
    # EL CANAL DE ESTA FUNCIÓN AL MOTOR DE DISEÑO NO DESAPARECE: es el puntero
    # `aleph-pack.json` (`escribir_ajustes_plugin`), que el lanzador lee por
    # `ALEPH_PACK_CONFIG` y traduce al dialecto de su motor. Lo que la casa quiera
    # declararle a Diseño viaja por ahí — ver `cerebro_label` en `bin/aleph-codesign`,
    # que es la primera declaración que cruza y la que deja el canal probado.
    if meta.get("config_format") == "launcher":
        # Y SE LLEVA EL MUERTO QUE DEJÓ LA VERSIÓN ANTERIOR. Dejar de escribirlo no lo
        # borra: en una máquina que ya entró a Diseño antes de esta obra, el
        # `config/config.toml` sigue en disco con un `apiKey` de sesión VENCIDA adentro.
        # Medido: 164 caracteres de token viejo sobreviviendo a la actualización.
        #
        # Se borra acá porque es el único lugar que ya decide sobre esos archivos, y sólo
        # si es NUESTRO: se comprueba la forma —JSON con `provider`, el dialecto de
        # opencode que escribía `escribir_config`— y no el nombre. Un `config.toml` que
        # sea TOML de verdad, o cualquier cosa que no reconozcamos, se respeta: es el
        # mismo criterio de `_tender_enlaces`, donde lo ajeno no se toca.
        muerto = _sub(ws, "config") / "config.toml"
        try:
            if muerto.is_file():
                cuerpo = json.loads(muerto.read_text(encoding="utf-8"))
                if isinstance(cuerpo, dict) and "provider" in cuerpo:
                    muerto.unlink()
        except Exception:                                   # noqa: BLE001 — frontera
            pass                                            # no es nuestro, o no se pudo leer
        return _sub(ws, "config") / "aleph-pack.json"
    cfg_dir = _sub(ws, "config")
    destino = cfg_dir / meta.get("config_file", "openscience.json")
    forma = meta.get("config_shape", _FORMA_POR_DEFECTO)

    if forma == "openwork_server":
        # El cerebro de ESTE stack NO entra por acá: entra por `enchufar_cerebro()`,
        # DESPUÉS de que el motor conteste. Este archivo es sólo puerto + secretos +
        # proyecto. Separarlos es lo que mata el «escribe y después falla».
        tk = dict(tokens_stack or {})
        cuerpo: dict[str, Any] = _cuerpo_openwork_server(
            ws, meta, puerto=int(puerto or 0),
            token=tk.get("token", ""), host_token=tk.get("host_token", ""))
        _declarar_plugin_al_motor(ws, meta, user_id)
    else:
        cuerpo = {
            "provider": {
                meta.get("brain_provider_id", "aleph"): cuerpo_provider_aleph(
                    ws, meta, base_aleph=base_aleph, token=token,
                    user_id=user_id, puppet_id=puppet_id),
            },
            "model": f"{meta.get('brain_provider_id', 'aleph')}/cerebro",
            # [LEY 12] La exclusividad viaja por el MISMO archivo que el cerebro, que es la
            # vía de este dialecto. La otra vía —la del motor que se configura por HTTP—
            # está en `_declarar_plugin_al_motor`. Una declaración, dos transportes.
            **_exclusividad_del_cerebro(meta),
        }
        # [O2] EL PLUGIN, declarado por `file://`. Es lo que le da espacio al turno
        # (`X-Aleph-Space`) y lo que cruza al puente lo que el stack produjo. Si el archivo
        # no está, no se declara: un `config.plugin` apuntando a la nada haría ruido en cada
        # arranque del stack y no arreglaría nada.
        plugin = _ruta_plugin(meta)
        if plugin is not None:
            cuerpo["plugin"] = [plugin.as_uri()]
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, destino)                                # atómico: nunca media config
    return destino


# ── EL ENTORNO DEL PACK, DECLARADO POR LA FILA ──────────────────────────────────────

def entorno_de(ws: str, meta: dict) -> dict:
    """Las variables con las que arranca el pack, resueltas contra SUS dirs.

    La fila las declara como plantillas (`{config}`, `{data}`, `{log}`, `{proyecto}`,
    `{recursos}`) porque un stack no necesita una variable: necesita las que necesita.
    Ciencia tiene dos (`config_env`/`data_env`) y le alcanzan; OpenWork tiene cuatro, y
    una de ellas —`OPENWORK_SERVER_CONFIG`— apunta a un ARCHIVO, no a un dir, así que el
    par fijo de Ciencia no podía expresarla sin mentirle al stack.

    Nada secreto viaja acá: `ps -E` muestra el entorno de los procesos propios. Lo que
    viaja son RUTAS; los secretos viven en los 0600 que esas rutas señalan.
    """
    valores = {
        "config": str(_sub(ws, "config")),
        "data": str(_sub(ws, "data")),
        "log": str(_sub(ws, "log")),
        "proyecto": str(_sub(ws, meta.get("label") or "proyecto")),
        "recursos": str(_ap.resource_root()),
        # LA RAÍZ DEL PACK. Hace falta para lo que no es ni config ni datos del usuario:
        # el almacén PRIVADO del motor de un stack. Ver `XDG_*` en la fila de Legal — sin un
        # sitio propio, esos stores caen en el home del usuario y dejan de ser por-instalación.
        "raiz": str(raiz_pack(ws)),
    }
    entorno: dict[str, str] = {}
    # Las dos de Ciencia siguen siendo válidas: la fila vieja no se reescribe para que
    # una fila nueva pueda declarar más.
    if meta.get("config_env"):
        entorno[meta["config_env"]] = valores["config"]
    if meta.get("data_env"):
        entorno[meta["data_env"]] = valores["data"]
    for clave, plantilla in (meta.get("env") or {}).items():
        entorno[clave] = str(plantilla).format(**valores)

    # LOS DIRECTORIOS SE CREAN, NO SE SUPONEN — y CUÁLES lo son lo DECLARA la fila, no lo
    # adivina esta función: entre estos valores hay rutas de archivo (el `server.json`) y
    # rutas de directorio, y distinguirlas por la extensión sería inventar.
    #
    # Se paga caro si falta: el motor de Oficina escribe un `.gitignore` adentro de su
    # `OPENCODE_CONFIG_DIR` al arrancar su instancia, y si el dir no existe muere con
    # ENOENT... que sale a la superficie como un 500 `UnknownError` sin una palabra sobre
    # el directorio. Medido el 2026-08-10; el rastro estaba en el log del motor, no en la
    # respuesta.
    for clave in (meta.get("env_dirs") or []):
        ruta = entorno.get(clave)
        if ruta:
            Path(ruta).mkdir(parents=True, exist_ok=True)

    # LAS MANOS, DELANTE DEL PATH. Se antepone —no se reemplaza— porque el stack sigue
    # necesitando las herramientas del sistema; lo que este dir garantiza es que `gws` sea
    # NUESTRO `gws` y no uno que el usuario tenga instalado por su cuenta, que sería otro
    # binario, otra versión y otra superficie de la que nadie respondió.
    manos = preparar_manos(ws, meta)
    # EL INTÉRPRETE VA AL MISMO DIR, y por eso se pide después: los dos escriben en
    # `<pack>/bin` y basta con anteponerlo una vez.
    interprete = preparar_interprete(ws, meta)
    delante = manos or interprete
    if delante is not None:
        entorno["PATH"] = f"{delante}:{os.environ.get('PATH', '')}"
    return entorno


# ── EL CEREBRO, ENCHUFADO DESPUÉS DE QUE EL MOTOR CONTESTE ──────────────────────────

def _pedir_json(url: str, *, metodo: str = "GET", cuerpo: Optional[dict] = None,
                cabeceras: Optional[dict] = None, timeout: float = 20.0) -> tuple[int, Any]:
    datos = None if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(url, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json")
    for k, v in (cabeceras or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            crudo = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(crudo)
            except Exception:                               # noqa: BLE001 — cuerpo no-JSON
                return r.status, crudo
    except urllib.error.HTTPError as e:
        crudo = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(crudo)
        except Exception:                                   # noqa: BLE001
            return e.code, crudo


def _proveedores_del_motor(url: str, token_cliente: str) -> list:
    """Qué proveedores ve EL MOTOR — no los que nosotros escribimos.

    Es la diferencia entre creerle a la config y preguntarle al que la usa. El server
    proxea al motor bajo `/opencode/*` (`server.ts:955-962`), y el motor contesta
    `GET /config/providers` con la lista efectiva.

    **SIRVE PARA LOS DOS MOTORES opencode DE LA CASA, y eso está medido** (2026-08-14,
    los dos packs levantados en frío desde el congelado `363d7ceb…`):

        Oficina  GET /opencode/config/providers  Bearer <token de cliente>  → 200 ['aleph']
        Legal    GET /opencode/config/providers  sin cabecera               → 200 ['aleph']
        Legal    GET /opencode/config/providers  Bearer inventado           → 200 ['aleph']

    Legal ignora la cabecera —su motor no pide credencial— así que la MISMA función
    contesta por los dos. Lo único que se le agrega acá es no mandar un `Bearer ` vacío
    cuando no hay token: un stack sin sesión de cliente no tiene por qué recibir una
    cabecera hueca, y hay servidores que la rechazan en vez de ignorarla.
    """
    cabeceras = {"Authorization": f"Bearer {token_cliente}"} if token_cliente else {}
    estado, resp = _pedir_json(url.rstrip("/") + "/opencode/config/providers",
                               cabeceras=cabeceras)
    if estado != 200:
        return []
    provs = resp.get("providers") if isinstance(resp, dict) else resp
    if isinstance(provs, dict):
        return list(provs)
    if isinstance(provs, list):
        return [p.get("id") for p in provs if isinstance(p, dict)]
    return []


def _apagar_catalogo_ajeno(url: str, token_cliente: str, apagar: list) -> list:
    """[LEY 12] El selector del workspace muestra UN cerebro, no una tienda.

    El motor trae embebido su catálogo gratuito (`opencode/big-pickle` y compañía —
    medido: `OPENCODE_DISABLE_MODELS_FETCH=1` NO lo saca, viene horneado). Dejarlo sería
    ofrecerle al usuario que le busque proveedor a un stack, que es justo la pregunta que
    esta casa no tiene. Se apaga por la costura del propio server
    (`POST /workspace/:id/runtime-config/disabled-providers`, `server.ts:2029`).
    """
    estado, resp = _pedir_json(url.rstrip("/") + "/workspaces",
                               cabeceras={"Authorization": f"Bearer {token_cliente}"})
    if estado != 200 or not isinstance(resp, dict):
        return []
    items = resp.get("items") or resp.get("workspaces") or []
    wid = (items[0] or {}).get("id") if items else None
    if not wid:
        return []
    estado, resp = _pedir_json(
        f"{url.rstrip('/')}/workspace/{wid}/runtime-config/disabled-providers",
        metodo="POST", cuerpo={"providers": list(apagar)},
        cabeceras={"Authorization": f"Bearer {token_cliente}"})
    if estado != 200 or not isinstance(resp, dict):
        return []
    return list(resp.get("disabledProviders") or [])


def enchufar_cerebro(ws: str, meta: dict, *, url: str, base_aleph: str,
                     token: Optional[str], user_id: Optional[str],
                     puppet_id: Optional[str], host_token: str,
                     token_cliente: str = "") -> dict:
    """Le enchufa a un stack de dialecto HTTP el cerebro de la casa — **en este orden**.

    EL ORDEN ES LA OBRA. El estudio de F6 midió el modo de fallo de OpenWork y lo anotó
    como «el PATCH escribe y DESPUÉS falla»: su handler
    (`apps/server/src/server.ts:2082-2105`) persiste la config con
    `writeGlobalRuntimeOpencodeConfig` y RECIÉN ahí llama a `reloadOpencodeEngine`. Si el
    motor no está arriba, el reload revienta, la llamada devuelve error… y la config ya
    quedó escrita. El usuario ve un fallo y el disco dice que salió bien.

    Acá ese modo **no existe por construcción**, porque esta función se llama únicamente
    DESPUÉS de que `ServidorDePack.start()` haya visto la señal de salud. O sea: entrar →
    motor arriba → PATCH → verificar. No hay una rama donde se parchee un motor caído.

    Y no alcanza con que el PATCH devuelva 200: se LEE su veredicto. `reload` puede volver
    `reloaded` (se aplicó), `deferred` (había sesiones vivas; el stack lo aplica al ociar)
    o `skipped` (no cambió nada, que en una segunda entrada es lo correcto). Cualquier otra
    cosa —o un provider que no volvió en la respuesta— es un cerebro que no quedó
    enchufado, y eso se dice, no se supone.
    """
    pid = meta.get("brain_provider_id", "aleph")
    ruta = meta.get("brain_patch_path", "/runtime-config/providers")
    cuerpo = {"provider": {pid: cuerpo_provider_aleph(
        ws, meta, base_aleph=base_aleph, token=token,
        user_id=user_id, puppet_id=puppet_id)}}
    # El PATCH es de `host-token`, no del token de cliente: es config del motor, no una
    # llamada de la UI. Los dos los escribió Aleph en el `server.json`. Y va en su cabecera
    # propia, NO en `Authorization`: `requireHostToken` (`server.ts:1248-1253`) sólo mira
    # `x-openwork-host-token`, y un Bearer con el token correcto igual da 401.
    estado, resp = _pedir_json(url.rstrip("/") + ruta, metodo="PATCH", cuerpo=cuerpo,
                               cabeceras={"x-openwork-host-token": host_token})

    # EL RECICLAJE PUEDE NO HACER FALTA, Y ESO NO ES UN FALLO. El reload postea
    # `/instance/dispose` al motor (`server.ts:3375-3389`) para que una instancia VIVA
    # relea la config. En el `enter` todavía no hay ninguna —el usuario no abrió nada—, y
    # el motor contesta 500 a un dispose sin instancia. La config, en cambio, ya quedó
    # escrita y la instancia la lee al construirse. Se tolera ESA causa y sólo ésa; y aun
    # tolerándola, nada se da por bueno hasta el paso de verificación de abajo.
    recarga: Any = None
    if estado == 200 and isinstance(resp, dict):
        recarga = resp.get("reload")
        if recarga not in ("reloaded", "deferred", "skipped"):
            raise PackError("cerebro_no_enchufado",
                            f"el motor no confirmó la recarga: reload={recarga!r}")
    elif isinstance(resp, dict) and resp.get("code") == "opencode_reload_failed":
        recarga = "sin_instancia_viva"
    else:
        raise PackError("cerebro_no_enchufado",
                        f"el motor rechazó la config del cerebro (HTTP {estado}): {resp!r}"[:400])

    apagados = _apagar_catalogo_ajeno(url, token_cliente,
                                      list(meta.get("brain_disable_providers") or []))

    # ── LA VERIFICACIÓN QUE MANDA ────────────────────────────────────────────────
    # No se le cree ni al `reload` ni a lo que escribimos: se le pregunta AL MOTOR qué
    # proveedores tiene. Es el único paso que distingue «la config quedó en disco» de «el
    # cerebro está enchufado», y es exactamente la distinción que el «escribe y después
    # falla» borraba.
    vistos = _proveedores_del_motor(url, token_cliente)
    if pid not in vistos:
        raise PackError("cerebro_no_enchufado",
                        f"el motor no declara el proveedor {pid!r}; ve {vistos!r}")
    return {"reload": recarga, "provider": pid, "proveedores_del_motor": vistos,
            "catalogo_apagado": apagados,
            "runtime_config": (resp or {}).get("runtimeConfigPath", "")
            if isinstance(resp, dict) else ""}


def _reciclar_instancia(url: str, token_cliente: str) -> bool:
    """Que el motor RECONSTRUYA su instancia y relea su config.

    Es la costura del propio motor (`POST /instance/dispose`, proxeada bajo
    `/opencode/*`), la misma que la cara de OpenWork dispara con
    `refreshProviders({dispose: true})` cada vez que toca credenciales. Un 500 acá no es
    un fallo: el motor contesta así cuando no hay instancia viva que tirar —que en una
    entrada limpia es lo normal— y la config se lee igual al construir la siguiente.
    """
    estado, _ = _pedir_json(
        url.rstrip("/") + "/opencode/instance/dispose", metodo="POST", cuerpo={},
        cabeceras={"Authorization": f"Bearer {token_cliente}"} if token_cliente else {})
    return estado == 200


def exclusividad_del_cerebro(ws: str, meta: dict, *, url: str,
                             token_cliente: str = "") -> dict:
    """[LEY 12] Que el nuestro ESTÉ no es lo mismo que que esté SOLO.

    LA MITAD QUE FALTABA, Y POR QUÉ FALTABA. `enchufar_cerebro` termina preguntándole al
    motor qué proveedores ve y exigiendo `if pid not in vistos`. Eso alcanza para «la
    config quedó enchufada» y **no alcanza para la ley**: a un stack con selector propio
    se le puede agregar otro proveedor DESDE SU PROPIA CARA, y la verificación de
    presencia le da verde igual.

    MEDIDO contra la `.app` instalada (`363d7ceb…`, 2026-08-14), haciendo exactamente lo
    que hace el botón «Connect provider» de Oficina (`c.auth.set`, un `PUT /auth/<id>`):

        antes                        [('aleph','config', 1 modelo)]   default {'aleph':'cerebro'}
        PUT /auth/openai  → 200
        después                      [('openai','api', 48), ('aleph','config', 1)]
                                     default {'openai':'gpt-5.3-chat-latest', 'aleph':'cerebro'}
        después del próximo `enter`  IGUAL — el proveedor ajeno sobrevivió a la entrada

    48 modelos que hablan directo con su API: sin `X-Aleph-Space`, sin `workspace_step`,
    sin `cost`, sin ledger, sin S8. Y el `enter` daba verde porque `aleph` seguía ahí.

    REPARAR Y ANUNCIAR, NO CERRAR LA PUERTA. Un `PackError` acá dejaría al usuario
    afuera de su trabajo por algo que apretó él, y encima sin poder entrar a deshacerlo.
    Se apaga el intruso con el mecanismo que ya existe y **se dice** — un arreglo mudo
    sería la misma clase de defecto que esta obra viene a matar.

    LO QUE SE REPARA Y LO QUE SÓLO SE DICE. La detección sirve para los dos motores
    opencode (ver `_proveedores_del_motor`). El apagado, no: `_apagar_catalogo_ajeno`
    habla por `POST /workspace/:id/runtime-config/disabled-providers`, que es una ruta
    del server de OpenWork y Legal no tiene. Así que Legal queda **detectado y anunciado,
    no reparado**, y eso se declara en la respuesta en vez de fingir que se arregló.
    Hoy no es teórico ni urgente en Legal —medido: `connected=['aleph']` sobre 185
    proveedores disponibles, y su cara no pinta selector de modelo— pero el día que
    aparezca uno, la casa lo va a decir en vez de callarlo.
    """
    pid = meta.get("brain_provider_id", "aleph")
    vistos = _proveedores_del_motor(url, token_cliente)
    intrusos = [p for p in vistos if p and p != pid]
    parte: dict[str, Any] = {"provider": pid, "proveedores_del_motor": vistos,
                             "intrusos": intrusos, "apagados": [], "sin_apagar": []}
    if not intrusos:
        return parte

    # EL APAGADO REEMPLAZA LA LISTA ENTERA, así que hay que volver a mandar la del
    # registro: pasar sólo los intrusos dejaría al catálogo gratuito del motor prendido.
    if meta.get("brain_wiring") == "patch_providers":
        apagados = _apagar_catalogo_ajeno(
            url, token_cliente,
            list(meta.get("brain_disable_providers") or []) + intrusos)
        # ── Y EL MOTOR TIENE QUE RELEER, O EL APAGADO NO EXISTE ──────────────────
        # MEDIDO por la vara de esta obra, que salió roja la primera vez: el POST a
        # `disabled-providers` devolvió 200 con la lista nueva y el motor **seguía
        # declarando al intruso**. La lista vive en la DB de runtime y el motor la lee
        # al CONSTRUIR su instancia, no al recibir el POST. En `enchufar_cerebro` esto
        # no se veía porque el `PATCH /runtime-config/providers` recicla él solo
        # (`server.ts:3361 reloadOpencodeEngine`); acá no hay PATCH que lo dispare.
        #
        # Se usa la misma costura que usa la cara de OpenWork cuando toca credenciales
        # (`refreshProviders({dispose: true})`): el `dispose` del propio motor. Nada
        # nuevo — la que faltaba era ésta.
        _reciclar_instancia(url, token_cliente)
        # No se le cree al 200: se vuelve a preguntar QUIÉN QUEDÓ.
        vistos = _proveedores_del_motor(url, token_cliente)
        parte["proveedores_del_motor"] = vistos
        parte["apagados"] = [p for p in intrusos
                             if p in apagados and p not in vistos]
    parte["sin_apagar"] = [p for p in intrusos if p not in parte["apagados"]]
    return parte


# ── [LEY 12] LA OTRA FORMA DE EXCLUSIVIDAD: LA TERNA DE UN STACK QUE SE AJUSTA SOLO ──
#
# La de arriba sirve para los dos motores opencode, que declaran una LISTA de proveedores.
# Finanzas no tiene lista: tiene UNA configuración de LLM y una pantalla de ajustes que la
# reescribe entera (`PUT /settings/llm`). Ahí «otro cerebro» no aparece como un proveedor de
# más — aparece como los MISMOS tres campos apuntando a otro lado.
#
# ⚠️ POR QUÉ SE COMPARA LA TERNA COMPLETA Y NO EL ID DEL PROVEEDOR. Medido: el desvío
# mantuvo `provider = openai` y cambió `model_name` y `base_url`. Comparar sólo el id
# habría dado verde con el turno saliendo por la puerta de al lado.

#: Los tres campos que el borde de Aleph necesita para ser el cerebro, y sus nombres en el
#: `.env` del stack. Cambiar uno solo alcanza para sacar el turno de la casa.
#:
#: ⚠️ **ESTA LISTA ES PARA COMPARAR, NO ES LO QUE SE ESCRIBE.** El escritor
#: (`_escribir_config_dotenv`, más arriba) pone CINCO claves: estas tres más `OPENAI_API_KEY`
#: —que acá es la sesión de Aleph— y `OPENAI_CUSTOM_HEADERS`. Las dos que faltan quedan afuera
#: a propósito: la sesión se renueva en cada `enter`, así que compararla daría desvío falso
#: siempre. Otra sesión leyó esta lista creyendo que era la del escritor y concluyó que el
#: launcher no protegía ninguna credencial — lo dijo, lo verifiqué, y era al revés. Dos listas
#: parecidas en el mismo archivo se confunden solas; queda dicho para que no vuelva a pasar.
_ENV_TERNA = ("LANGCHAIN_PROVIDER", "LANGCHAIN_MODEL_NAME", "OPENAI_BASE_URL")


def terna_esperada(meta: dict, base_aleph: str) -> dict:
    """La terna que el pack escribe, en la forma en que el stack la devuelve."""
    return {"provider": "openai",
            "model_name": meta.get("cerebro_label", "Cerebro de Aleph"),
            "base_url": base_aleph.rstrip("/") + meta["brain_path"]}


def _terna_igual(a: dict, b: dict) -> bool:
    def _n(d, k):
        return str(d.get(k) or "").strip().rstrip("/")
    return (_n(a, "provider").lower() == _n(b, "provider").lower()
            and _n(a, "model_name") == _n(b, "model_name")
            and _n(a, "base_url") == _n(b, "base_url"))


def terna_en_disco(ws: str, meta: dict) -> Optional[dict]:
    """La terna que hay AHORA en el `.env`, antes de que la pisemos. `None` si no hay.

    ⚠️ ESTO SE LEE ANTES DEL LAUNCHER Y NO ES UN DETALLE DE ORDEN. `PUT /settings/llm`
    persiste en ESTE archivo además de mutar el proceso, así que el archivo previo es la
    única huella de un desvío. Si lo leyéramos después de escribir nuestra config, el
    readback vería todo limpio y no habría manera de anunciar que reparamos algo: un
    arreglo mudo, que es la clase de defecto que esta obra viene a matar.
    """
    ruta = _sub(ws, "data") / meta.get("config_file", ".env")
    if not ruta.is_file():
        return None
    vals: dict[str, str] = {}
    try:
        for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                k, _, v = linea.partition("=")
                if k.strip() in _ENV_TERNA:
                    vals[k.strip()] = v.strip()
    except OSError:
        return None
    if not vals:
        return None
    return {"provider": vals.get("LANGCHAIN_PROVIDER", ""),
            "model_name": vals.get("LANGCHAIN_MODEL_NAME", ""),
            "base_url": vals.get("OPENAI_BASE_URL", "")}


def _ajustes_llm(url: str, cabeceras: dict) -> Optional[dict]:
    estado, resp = _pedir_json(url.rstrip("/") + "/settings/llm", cabeceras=cabeceras)
    return resp if estado == 200 and isinstance(resp, dict) else None


def exclusividad_por_terna(ws: str, meta: dict, *, url: str, base_aleph: str,
                           previa: Optional[dict], proceso_vivo: bool,
                           token_cliente: str = "") -> dict:
    """[LEY 12] Que la terna del stack sea la nuestra, y si no lo es, repararla y decirlo.

    LAS DOS SITUACIONES, QUE NO SE REPARAN IGUAL:

    · **proceso nuevo** — nació leyendo el `.env` que acabamos de escribir, así que su
      runtime YA es el nuestro. No hay nada que reparar; sí hay algo que ANUNCIAR, porque
      el usuario tenía puesto otro cerebro y se lo cambiamos.
    · **proceso vivo** (el préstamo devolvió el de antes) — ese proceso no relee el
      archivo: `PUT /settings/llm` escribe el `.env` *y* muta su `os.environ` y le tira el
      cache de config (`reset_env_config`). Reescribir el archivo no lo mueve. La única
      reparación efectiva es el PUT del propio motor.

    Y NO SE LE CREE AL 200: después del PUT se vuelve a preguntar. Oficina ya pagó esa
    lección con `disabled-providers`, que devolvía 200 con la lista nueva y el motor seguía
    declarando al intruso.
    """
    esperada = terna_esperada(meta, base_aleph)
    parte: dict[str, Any] = {"forma": "settings_llm", "esperada": esperada,
                             "previa": previa, "desviada": False,
                             "reparada": False, "sin_reparar": False,
                             "proceso_vivo": bool(proceso_vivo)}
    if previa is None or _terna_igual(previa, esperada):
        return parte
    parte["desviada"] = True

    if not proceso_vivo:
        # El proceso nació con la nuestra: reparado por construcción, y se dice.
        parte["reparada"] = True
        parte["como"] = "config_al_nacer"
        return parte

    cab = {"Authorization": f"Bearer {token_cliente}"} if token_cliente else {}
    ajustes = _ajustes_llm(url, cab) or {}
    # El PUT reemplaza la configuración ENTERA: lo que no se manda vuelve al default del
    # proveedor. Se conservan los ajustes de generación que el usuario haya tocado —son
    # suyos y no son el cerebro— y se pisa sólo la terna.
    cuerpo = {
        "provider": esperada["provider"],
        "model_name": esperada["model_name"],
        "base_url": esperada["base_url"],
        "temperature": ajustes.get("temperature", 0.0),
        "timeout_seconds": ajustes.get("timeout_seconds", 120),
        "max_retries": ajustes.get("max_retries", 2),
        "reasoning_effort": ajustes.get("reasoning_effort", ""),
    }
    estado, _resp = _pedir_json(url.rstrip("/") + "/settings/llm", metodo="PUT",
                                cuerpo=cuerpo, cabeceras=cab)
    parte["put_estado"] = estado
    # LA RELECTURA ES EL VEREDICTO, no el código del PUT.
    despues = _ajustes_llm(url, cab)
    parte["despues"] = ({k: despues.get(k) for k in ("provider", "model_name", "base_url")}
                        if despues else None)
    parte["reparada"] = bool(despues and _terna_igual(despues, esperada))
    parte["sin_reparar"] = not parte["reparada"]
    parte["como"] = "put_settings_llm"
    return parte


# ── EL REGISTRO DE PACKS VIVOS ──────────────────────────────────────────────────────

#: [Obra 1] EL LOCK CHICO. Protege los TRES DICCIONARIOS de abajo y nada más — son
#: operaciones de microsegundos. Hasta esta obra cubría también el spawn y la espera de
#: salud del pack (medido: 5,89 s el más lento), y eso ponía a TODOS los workspaces en
#: fila india: seis arranques en paralelo tardaban lo mismo que seis en serie
#: (medido 2026-08-11: 9,10 s en paralelo contra 12,66 s en serie).
_LOCK = threading.RLock()
#: [Obra 1] UN PESTILLO POR `clave`, que es `(dueño, workspace)`. Lo que el lock grande sí
#: protegía y hay que conservar es que **dos entradas al MISMO workspace no se pisen**:
#: escriben la misma config y pedirían el mismo proceso. Con esto se siguen serializando
#: entre sí —y con nadie más—, que es la granularidad que el producto pide: entrar a
#: Ciencia no tiene por qué esperar a que termine de arrancar Finanzas.
_PESTILLOS: dict[str, threading.Lock] = {}
#: `clave → puerto`. El puerto SE RECUERDA para que la huella del dueño no cambie entre
#: entradas: con el mismo comando y los mismos args, volver a entrar **comparte el proceso
#: vivo** en vez de levantar otro. Un puerto nuevo por entrada haría que cada `enter`
#: pareciera una conexión distinta y el dueño levantaría un pack por visita.
_PUERTOS: dict[str, int] = {}
#: `clave → Prestamo` (el préstamo abierto mientras el workspace está adentro).
_PRESTAMOS: dict[str, Any] = {}
#: `clave → (pids, tokens_stack)`: los secretos con los que arrancó el proceso QUE ESTÁ
#: VIVO. Se guardan junto a sus pids porque los pids son el único hecho que distingue
#: «el mismo proceso de antes» de «uno nuevo»: si son los mismos, ese proceso ya leyó su
#: config al nacer y no la va a releer, así que los tokens vigentes son los suyos y no
#: los que acabamos de sortear. Ver `entrar()`.
_TOKENS_STACK: dict[str, tuple[tuple, dict]] = {}
#: `clave → Timer` de la gracia del `leave`.
_GRACIAS: dict[str, threading.Timer] = {}


def _write_internal_capability(path: Path, value: str) -> None:
    """Publica una capability 0600 por clave de proceso, sin ventana de truncado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        tmp.write_text(value + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _same_pack_process_still_alive(active: Optional[tuple[tuple, dict]]) -> bool:
    """Sólo conserva tokens si todos los pids registrados siguen siendo ese proceso vivo."""
    if not active or not active[0]:
        return False
    for pid in active[0]:
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError, TypeError):
            return False
    return True

# ── QUIÉN LLAMA, CUANDO LA CABECERA NO LO DICE ──────────────────────────────────────
#
# EL PROBLEMA, MEDIDO. Diseño cruza el borde 5 veces por turno **sin
# `X-Aleph-Workspace`**: llega `X-Aleph-Space`, `X-Aleph-User`, `X-Aleph-Chat` y la sesión,
# y el workspace no. Consecuencias medidas contra la pantalla el 2026-08-22: el grabador
# del borde lo anota como `'?'`, `equiv.workspace` queda en `""`, y con eso
#   · NINGUNA perilla por stack lo alcanza (`encendido_para("")` es siempre False), y
#   · `le_toca_al_borde(_WORKSPACE_STACKS.get(""))` es False, así que su hilo de la casa
#     tenía **0 mensajes** mientras ciencia/legal/oficina tenían 24/5/18.
#
# POR QUÉ SE RECUPERA ACÁ Y NO SE PIDE ALLÁ. La cabecera la pone el lanzador del pack y su
# ausencia es del otro lado del límite sagrado. Pero la identidad **no hace falta pedirla**:
# Aleph ya la sabe, porque es Aleph quien reparte en el `enter` los identificadores que el
# stack después devuelve. El `chat_id` que viaja en `X-Aleph-Chat` es, byte por byte, el que
# esta casa le escribió al pack en su puntero. Entonces no se adivina nada: se recuerda.
#
# LO QUE **NO** SIRVE DE LLAVE, y está medido, no supuesto:
#   · el TOKEN (`aleph-pack.json.token`) — es la sesión del DUEÑO, no del workspace. Los
#     cuatro packs en disco tenían el MISMO token (mismo sha256) el 2026-08-22.
#   · el `sid` — los seis comparten Biblioteca a propósito, así que también es el mismo.
#   · el PUERTO DE ORIGEN del socket — es efímero y cambia en cada paso del mismo turno
#     (medido: 51794 · 51797 · 51956 · 52033 para un turno de Diseño, con el pack
#     escuchando en 51555). No es el puerto del pack y no identifica nada.
#
# FAIL-CLOSED ANTE AMBIGÜEDAD. Si dos workspaces llegaran a reclamar la misma marca, la
# marca deja de resolver — devolver "cualquiera de los dos" sería fabricar la identidad que
# esta pieza existe para no fabricar. Vale más un `''` honesto que un `diseno` inventado.
_IDENTIDAD: dict[tuple[str, str], str] = {}

#: Las marcas demasiado cortas no se registran: una llave de 3 caracteres no identifica a
#: nadie y sí puede chocar. El umbral es el largo de un uuid recortado, no un número lindo.
_MARCA_MINIMA = 8


def registrar_identidad(ws: str, *, chat_id: Optional[str] = None,
                        space_id: Optional[str] = None) -> list[str]:
    """Aleph recuerda QUÉ le repartió a este pack, para reconocerlo cuando vuelva.

    Devuelve las marcas que quedaron registradas — la vara mide eso y no el efecto.
    """
    ws = (ws or "").strip().lower()
    if not ws:
        return []
    puestas: list[str] = []
    with _LOCK:
        for clase, valor in (("chat", chat_id), ("space", space_id)):
            v = (valor or "").strip()
            if len(v) < _MARCA_MINIMA:
                continue
            k = (clase, v)
            previo = _IDENTIDAD.get(k)
            if previo is not None and previo != ws:
                # Dos dueños para una marca: se apaga, no se elige.
                _IDENTIDAD[k] = ""
                continue
            _IDENTIDAD[k] = ws
            puestas.append(f"{clase}:{v}")
    return puestas


def workspace_de(*, chat_id: Optional[str] = None,
                 space_id: Optional[str] = None) -> str:
    """El workspace que repartió estos identificadores, o `''` si no se sabe.

    El orden no es estético: el `chat_id` es **por workspace por construcción** (lo crea
    `asegurarHilo()` contra `/v1/workspaces/<ws>/memoria`, que es del workspace y del
    dueño), mientras que el espacio puede ser derivado por el lanzador del pack a partir
    del `sid`, que los seis comparten. Se pregunta primero por el que no puede confundirse.
    """
    with _LOCK:
        for clase, valor in (("chat", chat_id), ("space", space_id)):
            v = (valor or "").strip()
            if len(v) < _MARCA_MINIMA:
                continue
            ws = _IDENTIDAD.get((clase, v))
            if ws:
                return ws
    return ""


def _clave_existente(ws: str, user_id: Optional[str]) -> str:
    """La clave con la que ESTE pack está registrado ahora mismo.

    `salir()` y `apagar()` no reciben `meta`, así que no pueden preguntar si el pack es
    único por máquina. Y no hace falta: la clave que importa es la que EXISTE. Se prueba
    la del usuario y, si no está, la única (`-::ws`) — que es la que usa un pack único.
    Sin esto, apagar un pack único dejaría el proceso vivo y el puerto tomado.
    """
    propia = f"{user_id or '-'}::{ws}"
    with _LOCK:
        registradas = set(_PRESTAMOS) | set(_PUERTOS) | set(_GRACIAS)
    if propia in registradas:
        return propia
    unica = f"-::{ws}"
    return unica if unica in registradas else propia


def _clave(ws: str, user_id: Optional[str], *, unico: bool = False) -> str:
    """La clave con la que este pack se reutiliza: puerto, préstamo y gracia cuelgan de acá.

    ⚠️ `unico=True` SACA AL USUARIO DE LA CLAVE, y eso no es una comodidad: es la única
    forma de no mentir sobre un pack cuyo PROCESO es uno solo por máquina.

    MEDIDO (2026-08-22, contra la `.app` INSTALADA, no contra el banco):

      · `enter` con la MISMA clave que levantó el pack → **200 en 16-29 ms** (lo comparte)
      · `enter` con OTRA clave                          → **503 · exit 0** en 1.103 ms,
        con el pack VIVO y contestando

    La cadena: otra clave → `_PUERTOS` elige otro puerto → el `spec` cambia (`--port N`) →
    cambia el hash de `dueno.clave_de` → el dueño presta un proceso NUEVO → el lock de
    instancia única del stack lo hace salir **exit 0** (salida limpia, por diseño) →
    `ServidorDePack.start` lee cualquier salida como muerte y devuelve
    «no llegó a levantarse» **sobre un workspace que está corriendo**.

    Y la separación por usuario que la clave prometía era ILUSORIA de todos modos: la
    config de estos packs se escribe en `<ws>/config/`, que es POR WORKSPACE, no por
    usuario. No se pierde aislamiento — nunca lo hubo.

    ALCANZABLE POR UN USUARIO REAL: `diseno.html:105-111` devuelve `null` cuando la sesión
    todavía no hidrató, y la línea 171 manda `user_id: (u && u.id) || null`. Primera
    corrida tras instalar, después de cerrar sesión, o una carrera de hidratación.
    """
    return f"{'-' if unico else (user_id or '-')}::{ws}"


def entidad(ws: str) -> str:
    """El `entity_id` con el que este pack vive en la tabla del dueño. El prefijo `pack:`
    es lo que hace legible un `procesos.jsonl` con MCPs y packs mezclados."""
    return f"pack:{ws}"


def _dueno():
    from inspection import dueno as _d
    return _d


def _cancelar_gracia(clave: str) -> bool:
    t = _GRACIAS.pop(clave, None)
    if t is None:
        return False
    t.cancel()
    return True


def _pestillo(clave: str) -> threading.Lock:
    """El pestillo de ESTA clave. Se crea bajo `_LOCK` y se toma FUERA de él.

    Crearlo bajo el lock chico es lo que evita que dos hilos fabriquen dos pestillos
    distintos para la misma clave y crean los dos que la tienen — que sería no tener
    ninguno.
    """
    with _LOCK:
        p = _PESTILLOS.get(clave)
        if p is None:
            p = _PESTILLOS[clave] = threading.Lock()
        return p


# ── ENTRAR ──────────────────────────────────────────────────────────────────────────

def levantar(ws: str, meta: dict, *, base_aleph: str, user_id: Optional[str] = None,
             token: Optional[str] = None, puppet_id: Optional[str] = None,
             chat_id: Optional[str] = None, sid: Optional[str] = None,
             space_id: Optional[str] = None, cred_resolver=None) -> dict:
    """Deja el pack de `ws` corriendo y devuelve dónde encontrarlo.

    Idempotente: si ya está vivo con la misma huella, el dueño comparte el proceso y esto
    devuelve la misma URL sin arrancar nada.

    [F1-CONECTORES] `cred_resolver` se INYECTA y no se construye acá. El que sirve es
    `credential_broker.make_user_resolver(user_id)`, que vive en `product/backend/`: que
    `platform/` lo importara sería invertir las capas. Es el mismo patrón con el que el
    assembler recibe su `byok_resolver`, y tiene el beneficio de que la vara puede pasar un
    resolver sintético sin una DB.
    """
    binario = binario_de(meta)
    if not binario:
        raise PackError("pack_no_instalado",
                        "el binario del workspace no viajó con esta instalación")
    d = _dueno()
    clave = _clave(ws, user_id, unico=bool(meta.get("proceso_unico_por_maquina")))
    # [Obra 1] EL PESTILLO DE ESTE WORKSPACE, no el lock de todos. Adentro pasa lo caro:
    # elegir puerto, escribir la config y pedirle el proceso al dueño. Dos entradas al mismo
    # workspace se turnan acá (la segunda encuentra el proceso vivo y lo comparte); dos
    # workspaces distintos no se ven.
    with _pestillo(clave):
        with _LOCK:
            _cancelar_gracia(clave)
        # LA IDENTIDAD, ANOTADA DONDE SE REPARTE. Va acá —antes de escribir nada y antes de
        # levantar el proceso— porque éste es el único punto de la casa donde el workspace y
        # los identificadores que el stack va a devolver están juntos y son ciertos. Se
        # anota para los SEIS, no sólo para el que hoy pierde su cabecera: la ambigüedad
        # sólo se puede detectar si están todos, y el que mañana pierda la suya ya va a
        # estar cubierto. Ver `registrar_identidad`.
        # ⚠️ EL `sid` NO ENTRA ACÁ, Y NO ES UN OLVIDO: la Biblioteca es UNA SOLA y los seis
        # workspaces comparten el mismo `sid` a propósito (medido: los cuatro packs en disco
        # tenían `gen-msm2klh9x4sodh`). Registrarlo haría que la marca la reclamen seis
        # dueños y el fail-closed la apagaría — trabajo para llegar a `''`. Sólo se anota lo
        # que es de ESTE workspace: su hilo, y el espacio cuando la casa reparte uno propio.
        registrar_identidad(ws, chat_id=chat_id, space_id=space_id)
        # Sólo los packs que cargan un plugin propio —o un launcher que consume el
        # contrato genérico de ajustes— necesitan este segundo archivo.
        # Educación consume directamente su catálogo 0600; duplicar ahí la sesión no
        # agrega capacidad y aumenta innecesariamente su superficie de custodia.
        # [F1-CONECTORES] EL VAULT SE LEE UNA VEZ POR `enter`, ANTES DE TODO LO DEMÁS.
        # Acá, y no adentro de cada escritor, porque tres de las seis ramas necesitan los
        # valores en momentos distintos del arranque: Diseño en el puntero (dos líneas más
        # abajo), los de archivo después de `escribir_config`, y Ciencia después de la salud.
        # Leer el vault tres veces sería descifrar tres veces el mismo secreto.
        cred_valores, cred_faltantes = resolver_credenciales(meta, cred_resolver)
        credenciales: dict[str, Any] = {"faltantes": cred_faltantes}
        if meta.get("plugin") or meta.get("pack_config"):
            escribir_ajustes_plugin(
                ws, meta, base_aleph=base_aleph, token=token,
                user_id=user_id, chat_id=chat_id, sid=sid,
                # Sólo el pack cuya config escribe su lanzador recibe las credenciales por
                # este canal; para los demás el puntero no es el destino y meter un secreto
                # de más en un archivo es empeorar la custodia sin ganar nada.
                credenciales=({e["proveedor"]: cred_valores[e["vault"]]
                               for e in _cred_entradas(meta)
                               if e.get("proveedor") and e["vault"] in cred_valores}
                              if meta.get("cred_format") == "puntero_launcher" else None))
        # La capa de config del stack, enlazada donde su motor la busca. Va ACÁ —antes del
        # spawn y fuera del reintento— porque no depende del puerto y el motor la lee al
        # construir su instancia: si llegara después, el primer turno ya salió sin oficio.
        preparar_config_del_motor(ws, meta)
        # [LEY 12] LA TERNA PREVIA, LEÍDA ANTES DE PISARLA. Es la única huella de que el
        # usuario apuntó su stack a otro cerebro (`PUT /settings/llm` persiste acá), y hay
        # exactamente una oportunidad de verla: antes de que `escribir_config` la reemplace.
        terna_previa = (terna_en_disco(ws, meta)
                        if meta.get("brain_lectura") == "settings_llm" else None)
        ultimo = ""
        for intento in (1, 2):
            with _LOCK:
                puerto = _PUERTOS.get(clave) or puerto_libre()
                _PUERTOS[clave] = puerto
            url = f"http://127.0.0.1:{puerto}"
            # Los secretos del stack se sortean ACÁ y se escriben en su config 0600 —
            # nunca en `argv`. Se renuevan en cada arranque; la UI no se entera porque el
            # server le inyecta el vigente en su `index.html` en cada carga, y su cliente
            # prefiere el del bootstrap por encima del que tenga guardado
            # (`openwork-server.ts:1096-1099`). Una sesión vieja en `localStorage` deja de
            # ser un 401: ése fue el defecto que la medición de A.6.a destapó.
            #
            # ⚠️ «EN CADA ARRANQUE» ES LA PALABRA, Y NO ERA LO QUE PASABA. Sortearlos acá
            # es correcto SÓLO si abajo nace un proceso; si el préstamo devuelve uno vivo,
            # estos secretos no los conoce nadie. El de CLIENTE sobrevivía igual porque el
            # server inyecta el suyo en cada carga (arriba), pero el de HOST no tiene ese
            # rescate: viaja en `x-openwork-host-token` hacia el PATCH y el motor lo compara
            # contra el que leyó al nacer. Por eso la segunda entrada daba 401 y el arreglo
            # está DESPUÉS del préstamo, que es el único punto donde se sabe si hubo
            # proceso nuevo.
            with _LOCK:
                _known_tokens = _TOKENS_STACK.get(clave)
            tokens_stack = (dict(_known_tokens[1]) if _same_pack_process_still_alive(_known_tokens) else {
                "token": secrets.token_urlsafe(24),
                "host_token": secrets.token_urlsafe(24),
                "internal_cap": secrets.token_urlsafe(32),
            })
            # La config se escribe DENTRO del reintento porque lleva el puerto adentro.
            escribir_config(ws, meta, base_aleph=base_aleph, token=token,
                            user_id=user_id, puppet_id=puppet_id,
                            space_id=space_id or sid, puerto=puerto,
                            chat_id=chat_id, sid=sid, tokens_stack=tokens_stack)
            # ── [F1-CONECTORES] LAS CREDENCIALES DE ARCHIVO, DESPUÉS DEL CEREBRO Y ANTES
            # DEL SPAWN. Las dos mitades del sándwich son medidas, no estéticas:
            #   · DESPUÉS de `escribir_config`, porque el `.env` de Finanzas lo reemplaza
            #     ENTERO ese escritor: al revés, el cerebro se llevaría las credenciales.
            #   · ANTES del spawn, porque el `EnvService` de Oficina cachea y no reinvalida
            #     (`env-file.ts:167-180`): su carga es perezosa, así que escribir antes de
            #     que el proceso exista llega, y escribir después del primer `list()` no se
            #     ve hasta reiniciar.
            # ⚠️ EL QUE SE CONFIGURA POR HTTP NO PASA POR ACÁ. Medido corriendo el `enter` de
            # Ciencia: esta pasada le dejaba un `verificacion` de relleno
            # (`causa: verifica_por_sonda`) que después TAPABA la causa real en el aviso —
            # `causa_de_credenciales` prefiere `verificacion` cuando existe, y la de verdad
            # estaba en `escritura`, que se escribe recién después de la salud. El aviso decía
            # «verifica_por_sonda» cuando el hecho era `sonda_sin_salida`. Dos pasadas para un
            # stack que sólo tiene una es trabajo muerto que además miente.
            if meta.get("cred_format") and meta["cred_format"] != "http_credentials":
                credenciales["escritura"] = escribir_credenciales(ws, meta, cred_valores)
                # NUNCA SE LE CREE A LA ESCRITURA: se relee. Es la decisión del dueño y la
                # razón está medida en Ciencia (un 200 y un `connected` verdes sobre un
                # campo que el stack no podía descifrar, con 0 líneas de log).
                credenciales["verificacion"] = verificar_credenciales(ws, meta, cred_valores)

            class _Clase(ServidorDePack):
                """La clase, cerrada sobre la URL y la señal de salud de ESTE pack.

                El dueño construye el servidor con la firma que él conoce
                (`entity_id, comando, args, …`) y no tiene por qué saber de HTTP; la URL y
                el `health` se le atan acá, que es donde se saben."""

                def __init__(self, name, command, args, env=None,
                             rpc_timeout=ARRANQUE_S, cwd=None):
                    super().__init__(name, command, args, env=env,
                                     rpc_timeout=rpc_timeout, cwd=cwd)
                    self.url = url
                    self.salud = meta.get("health", "/")
                    self.bitacora = _sub(ws, "log") / "pack.log"

            entorno_stack = {**entorno_de(ws, meta)}
            if meta.get("config_shape") == "openwork_server":
                # The 0600 server.json is authoritative for this launch. Do not let
                # an inherited shell token override the capability Aleph just wrote.
                entorno_stack.update({"OPENWORK_TOKEN": "", "OPENWORK_HOST_TOKEN": ""})
            # Algunas filas declaran las variables de config/datos y otras (por ejemplo
            # Oficina) sólo necesitan las plantillas de `env`. No indexar las dos claves
            # opcionales evita convertir un registro válido en un 500 al entrar.
            if meta.get("config_env"):
                entorno_stack[meta["config_env"]] = str(
                    raiz_pack(ws) / "runtime"
                    if meta.get("config_format") == "deeptutor" else _sub(ws, "config")
                )
            if meta.get("data_env"):
                entorno_stack[meta["data_env"]] = str(_sub(ws, "data"))
            entorno_stack.update({
                # Sólo el PUNTERO al archivo de ajustes viaja por entorno; el secreto
                # se queda en el 0600. `ps -E` muestra el entorno de los procesos
                # propios, así que una sesión ahí sería un secreto a la vista.
                "ALEPH_PACK_CONFIG": str(_sub(ws, "config") / "aleph-pack.json"),
                "ALEPH_PACK_PORT": str(puerto),
                "ALEPH_PACK_INTERNAL_CAP_FILE": str(
                    _sub(ws, "config") /
                    (".internal-capability-" + hashlib.sha256(clave.encode("utf-8")).hexdigest()[:16])),
                **dict(meta.get("pack_env") or {}),
            })
            _cap_path = Path(entorno_stack["ALEPH_PACK_INTERNAL_CAP_FILE"])
            _write_internal_capability(_cap_path, tokens_stack["internal_cap"])
            # ── [F1-CONECTORES · C] LA SOMBRA, MIRADA SOBRE EL ENTORNO REAL DEL HIJO ────
            # Se calcula ACÁ y no antes porque el entorno del hijo es
            # `{**os.environ, **entorno_stack}` (ver el `Popen` de `ServidorDePack.start`), y
            # antes de armar `entorno_stack` no existe. Se DICE y no se pisa: limpiar la
            # variable sería pisar algo que el usuario exportó en SU shell, y la casa no sabe
            # si es un descuido o una decisión.
            if meta.get("cred_format"):
                credenciales["sombra"] = sombra_de_credenciales(
                    meta, {**os.environ, **entorno_stack})
            # ── [LEY 12] EL CEREBRO, CLAVADO POR ENTORNO ────────────────────────────
            # Va por ENTORNO y no por el `.env` a propósito: el `.env` es justamente lo que
            # `PUT /settings/llm` reescribe, así que un pin guardado ahí lo pisa el mismo
            # pedido del que hay que defenderse. El entorno del proceso sólo lo pone quien
            # lo spawnea —nosotros— y el PUT no toca estas tres claves (no están en su
            # `updates`). Sin ellas, el stack se comporta EXACTAMENTE como upstream.
            if meta.get("brain_lectura") == "settings_llm":
                _pin = terna_esperada(meta, base_aleph)
                entorno_stack.update({
                    "ALEPH_BRAIN_PROVIDER": _pin["provider"],
                    "ALEPH_BRAIN_MODEL_NAME": _pin["model_name"],
                    "ALEPH_BRAIN_BASE_URL": _pin["base_url"],
                })
            spec = {
                "command": binario,
                "args": [*meta.get("serve_args", []), *(["--port", str(puerto)]
                         if meta.get("port_arg", True) else [])],
                "env": entorno_stack,
                # EL DIRECTORIO DE TRABAJO ES EL PROYECTO, y su NOMBRE se ve: los stacks
                # llaman al proyecto como a la carpeta. Con `proyectos` el usuario entraba a
                # algo llamado «proyectos»; con la etiqueta del workspace entra a «Ciencia»,
                # que es donde creía estar entrando.
                "cwd": str(_sub(ws, meta.get("label") or "proyecto")),
                "rpc_timeout": ARRANQUE_S,
                "clase": _Clase,
            }
            try:
                prestamo = d.actual().pedir(entidad(ws), spec=spec, user_id=user_id,
                                            motivo=f"workspace:{ws}")
            except Exception as e:                          # noqa: BLE001 — frontera
                ultimo = f"{type(e).__name__}: {e}"
                # Un solo reintento, y con puerto nuevo: el modo de fallo que justifica
                # reintentar es que un tercero se haya quedado con el puerto entre que lo
                # elegimos y lo usamos. Dos fallos seguidos no son mala suerte.
                with _LOCK:
                    _PUERTOS.pop(clave, None)
                if intento == 2:
                    raise PackError("pack_no_arranco", ultimo) from e
                continue
            with _LOCK:
                _PRESTAMOS[clave] = prestamo
            # ── LOS SECRETOS SON DEL PROCESO, NO DE LA VISITA ────────────────────────
            # Los de arriba se sortearon ANTES de pedir el préstamo, porque la config
            # tiene que existir cuando el proceso nace. Pero `pedir()` puede devolver un
            # proceso YA VIVO —eso es lo que hace que entrar dos veces no levante dos
            # packs— y ese proceso leyó su config al nacer y no la relee. Sus secretos
            # siguen siendo los de ENTONCES; los recién sorteados no los conoce nadie.
            # Los pids son el discriminante: mismos pids ⇒ mismo proceso ⇒ mandan los
            # suyos, y se reescribe la config con ellos para que el disco no contradiga
            # a la memoria del stack.
            pids_ahora = tuple(prestamo.pids or ())
            with _LOCK:
                previos = _TOKENS_STACK.get(clave)
                if pids_ahora and previos and previos[0] == pids_ahora:
                    tokens_stack = previos[1]
                    reusados = True
                else:
                    _TOKENS_STACK[clave] = (pids_ahora, tokens_stack)
                    reusados = False
            if reusados:
                _write_internal_capability(_cap_path, tokens_stack["internal_cap"])
                escribir_config(ws, meta, base_aleph=base_aleph, token=token,
                                user_id=user_id, puppet_id=puppet_id,
                                space_id=space_id or sid, puerto=puerto,
                                chat_id=chat_id, sid=sid, tokens_stack=tokens_stack)
            salida = {"url": url, "pids": list(prestamo.pids or []),
                      "entity_id": entidad(ws), "puerto": puerto}
            # ── EL ORDEN ────────────────────────────────────────────────────────────
            # Llegar hasta acá SIGNIFICA que el motor contestó su señal de salud: el
            # dueño sólo devuelve préstamo si `start()` dio True, y `start()` espera la
            # salud, no el pid. Recién ahora se le enchufa el cerebro. Un stack que se
            # configura por HTTP no puede configurarse antes de existir, y ésa es toda
            # la diferencia entre esto y el «escribe y después falla» que el estudio
            # midió: no hay orden posible en el que el PATCH le llegue a un motor caído.
            # ── [F1-CONECTORES] EL STACK QUE RECIBE SU CREDENCIAL POR HTTP ─────────────
            # Va acá por lo mismo que el cerebro de Oficina: no hay orden posible en el que
            # un PUT le llegue a un motor que todavía no existe. Y la verificación es una
            # sonda-subproceso, no una relectura de su API — medido: `connected` es verde
            # falso sobre un campo indescifrable.
            if meta.get("cred_format") == "http_credentials":
                credenciales["escritura"] = enchufar_credenciales(
                    ws, meta, cred_valores, url=url)
            if meta.get("cred_format"):
                salida["credenciales"] = credenciales
            if meta.get("brain_wiring") == "patch_providers":
                salida["cerebro"] = enchufar_cerebro(
                    ws, meta, url=url, base_aleph=base_aleph, token=token,
                    user_id=user_id, puppet_id=puppet_id,
                    host_token=tokens_stack["host_token"],
                    token_cliente=tokens_stack["token"])
            # ── [LEY 12] Y ADEMÁS, QUE ESTÉ SOLO ────────────────────────────────────
            # Va acá y no adentro de `enchufar_cerebro` justamente para que alcance a los
            # DOS motores opencode: el de Oficina se configura por HTTP y el de Legal por
            # archivo, pero los dos contestan `GET /opencode/config/providers`. La fila
            # declara `engine` porque ese path es de opencode, no de cualquier stack.
            if meta.get("engine") == "opencode":
                # El token de cliente es de la forma `openwork_server` y sólo ella lo
                # entiende. A un stack que no lo emitió no se le manda un secreto que él
                # nunca vio: `_proveedores_del_motor` sabe preguntar sin cabecera.
                _tk = (tokens_stack.get("token", "")
                       if meta.get("config_shape") == "openwork_server" else "")
                salida["exclusividad"] = exclusividad_del_cerebro(
                    ws, meta, url=url, token_cliente=_tk)
            # ── Y LA MISMA LEY PARA EL QUE NO TIENE LISTA, SINO TERNA ───────────────
            # DESPACHA LA FILA, NO EL MOTOR. Atarlo a `engine == "opencode"` fue correcto
            # mientras los únicos con selector propio eran esos dos; el tercero se
            # configura por `.env` + `PUT /settings/llm` y por ese camino la ley no
            # llegaba. La fila declara CÓMO se lee su cerebro y acá se despacha.
            elif meta.get("brain_exclusivo") and meta.get("brain_lectura") == "settings_llm":
                salida["exclusividad"] = exclusividad_por_terna(
                    ws, meta, url=url, base_aleph=base_aleph, previa=terna_previa,
                    # `reusados` es el único hecho que distingue «este proceso ya estaba»
                    # de «acaba de nacer», y las dos situaciones se reparan distinto.
                    proceso_vivo=reusados)
            return salida
        raise PackError("pack_no_arranco", ultimo)          # pragma: no cover — el for sale antes


# ── SALIR ───────────────────────────────────────────────────────────────────────────

def salir(ws: str, *, user_id: Optional[str] = None, gracia_s: Optional[float] = None) -> dict:
    """Suelta el pack y arma la gracia. Devuelve qué se hizo, para que la vara lo lea."""
    clave = _clave_existente(ws, user_id)
    gracia = GRACIA_S if gracia_s is None else float(gracia_s)
    with _LOCK:
        # ⚠️ UN `leave` DE ALGO QUE NUNCA SE TOMÓ NO ARMA NADA — y esto no es prolijidad:
        # sin la guarda, mata el pack del `enter` que viene UN SEGUNDO DESPUÉS.
        #
        # MEDIDO el 2026-08-23 con la pantalla de Diseño sobre un sidecar recién levantado:
        #   ts …143  POST /v1/workspaces/diseno/leave   200   ← la pantalla limpia al entrar
        #   ts …144  POST /v1/workspaces/diseno/enter   200   ← el pack arranca, Electron vivo
        #   ts …164  (20 s de gracia)                         ← el pack MUERTO, «Failed to fetch»
        #
        # La cadena: con el registro vacío, `_clave_existente` cae a `usuario::ws`, y ahí
        # arma la gracia. El `enter` de después registra el pack en `-::ws` —porque es único
        # por máquina— y cancela la gracia de ESA clave, no la de la otra. Veinte segundos
        # más tarde `_apagar_por_gracia` corre sobre la clave huérfana, no encuentra préstamo
        # y llama a `apagar()`, que **vuelve a resolver la clave** y ahora sí encuentra la
        # del pack vivo. La gracia de un pack que no existía se lleva puesto al que sí.
        #
        # No alcanza con arreglar `_apagar_por_gracia`: la clave huérfana nace acá.
        if (clave not in _PRESTAMOS and clave not in _PUERTOS
                and clave not in _GRACIAS):
            return {"apagado": False, "gracia_s": 0, "causa": "no_estaba_tomado"}
        prestamo = _PRESTAMOS.pop(clave, None)
        if prestamo is not None:
            try:
                prestamo.soltar()
            except Exception:                               # noqa: BLE001 — soltar no falla
                pass
        _cancelar_gracia(clave)
        if gracia <= 0:
            apagar(ws, user_id=user_id, motivo="salió del workspace")
            return {"apagado": True, "gracia_s": 0}
        t = threading.Timer(gracia, _apagar_por_gracia, args=(ws, user_id))
        t.daemon = True
        _GRACIAS[clave] = t
        t.start()
        return {"apagado": False, "gracia_s": gracia}


def _apagar_por_gracia(ws: str, user_id: Optional[str]) -> None:
    with _LOCK:
        # La MISMA clave que registró `salir()`. Con `_clave(ws, user_id)` a secas, un pack
        # único quedaba registrado en `-::ws` y acá se buscaba en `usuario::ws`: la gracia
        # no encontraba nada, el préstamo se leía como vacío y se apagaba un pack que
        # alguien acababa de volver a tomar. (`_LOCK` es RLock: reentrar es seguro.)
        clave = _clave_existente(ws, user_id)
        _GRACIAS.pop(clave, None)
        if _PRESTAMOS.get(clave) is not None:
            return                                          # alguien volvió a entrar: no se toca
    apagar(ws, user_id=user_id, motivo="gracia vencida")


def apagar(ws: str, *, user_id: Optional[str] = None, motivo: str = "") -> int:
    """Mata el pack YA, por el camino de la lápida (manda por encima del refcount)."""
    clave = _clave_existente(ws, user_id)
    with _LOCK:
        _cancelar_gracia(clave)
        _PRESTAMOS.pop(clave, None)
        _PUERTOS.pop(clave, None)
        _TOKENS_STACK.pop(clave, None)
    return _dueno().actual().apagar_entidad(
        entidad(ws), user_id=user_id, motivo=motivo or "apagado del pack")


# ── ESTADO ──────────────────────────────────────────────────────────────────────────

def vivo(ws: str, meta: dict, *, user_id: Optional[str] = None) -> Optional[dict]:
    """Qué sabe la casa del pack de `ws` AHORA, o `None` si no hay proceso.

    El hecho lo da la tabla del dueño (quién está vivo) y la señal de salud del stack
    (si además atiende). Los dos, porque son dos hechos distintos: un proceso vivo que
    todavía no atiende no es un workspace usable, y decir lo contrario es el defecto que
    F3 pagó con una captura.
    """
    ent = entidad(ws)
    for fila in _dueno().actual().estado().get("vivas", []):
        if fila.get("entity_id") != ent:
            continue
        if user_id is not None and fila.get("user_id") not in (None, user_id):
            continue
        puerto = _PUERTOS.get(_clave(
            ws, user_id, unico=bool(meta.get("proceso_unico_por_maquina"))))
        url = f"http://127.0.0.1:{puerto}" if puerto else ""
        return {"url": url, "pids": list(fila.get("pids") or []),
                "atiende": bool(url) and _sano(url, meta.get("health", "/")),
                "refcount": fila.get("refcount", 0)}
    return None


def capacidad_interna(ws: str, meta: dict, *, user_id: Optional[str]) -> str:
    """Capability del proceso vivo; nunca se incluye en la respuesta pública de `levantar`."""
    clave = _clave(ws, user_id, unico=bool(meta.get("proceso_unico_por_maquina")))
    with _LOCK:
        active = _TOKENS_STACK.get(clave)
    if not active or not active[1].get("internal_cap"):
        raise PackError("pack_no_propio", "La identidad interna del pack no está disponible.")
    return str(active[1]["internal_cap"])


def aprobaciones_oficina(meta: dict, *, user_id: str, solicitud: Optional[str] = None,
                         permitir: Optional[bool] = None) -> dict:
    """The authenticated pack owner decides pending file writes; host secrets stay here.

    Never use the on-disk config (it can outlive its process), accept a caller URL,
    or grant the embedded client general host authority.
    """
    ws = "oficina"
    owned = [row for row in _dueno().actual().estado().get("vivas", [])
             if row.get("entity_id") == entidad(ws) and row.get("user_id") == user_id]
    if not owned:
        raise PackError("pack_no_propio", "No hay una Oficina activa de esta sesión.")
    clave = _clave(ws, user_id, unico=bool(meta.get("proceso_unico_por_maquina")))
    with _LOCK:
        active = _TOKENS_STACK.get(clave)
        port = _PUERTOS.get(clave)
    if not active or not port or not any(tuple(row.get("pids") or ()) == active[0] for row in owned):
        raise PackError("pack_no_propio", "La identidad del proceso cambió.")
    host_token = active[1].get("host_token")
    if not host_token:
        raise PackError("aprobacion_no_disponible", "El proceso no ofrece aprobación local.")
    url = f"http://127.0.0.1:{port}"
    headers = {"x-openwork-host-token": host_token}
    status, payload = _pedir_json(url + "/approvals", cabeceras=headers, timeout=5)
    if status != 200 or not isinstance(payload, dict):
        raise PackError("aprobacion_no_disponible", "No se pudieron consultar las solicitudes.")
    items = [item for item in payload.get("items", [])
             if item.get("action") == "workspace.file.write"]
    if solicitud is None:
        return {"items": [{key: item.get(key) for key in ("id", "summary", "paths", "createdAt")}
                          for item in items]}
    if not any(item.get("id") == solicitud for item in items):
        raise PackError("aprobacion_vencida", "La solicitud ya no está pendiente.")
    status, result = _pedir_json(url + "/approvals/" + urllib.parse.quote(solicitud, safe=""),
                                 metodo="POST", cuerpo={"reply": "allow" if permitir else "deny"},
                                 cabeceras=headers, timeout=5)
    if status != 200:
        raise PackError("aprobacion_vencida", "No se pudo registrar la decisión.")
    return {"ok": True, "allowed": bool(result.get("allowed"))}


def apagar_todos(*, motivo: str = "cierre") -> int:
    """Todos los packs de este proceso. El `apagar_todo()` del dueño ya los alcanza (están
    en su tabla); esto existe para que una vara pueda dejar la máquina limpia sin tumbar
    también las conexiones MCP de otra vara que esté corriendo al lado."""
    with _LOCK:
        claves = list(set(list(_PRESTAMOS) + list(_PUERTOS) + list(_GRACIAS)))
    n = 0
    for clave in claves:
        user_id, _, ws = clave.partition("::")
        n += apagar(ws, user_id=(None if user_id == "-" else user_id), motivo=motivo)
    return n
