"""
dueno.py — EL DUEÑO DEL CICLO DE VIDA · D1 + D2.

Supervisor de conexiones MCP en el sidecar. **POSEE los procesos**: quien necesita una
conexión se la PIDE, no la spawnea. Implementa `DISEÑO-DUEÑO-v1.md`, sesiones D1 y D2.

  D1  tabla de vivos · refcount · huella de spawn · préstamo como context manager ·
      `estado()` · `procesos.jsonl` escrito ANTES del spawn · barrido de arranque
  D2  reloj de ociosidad (cosechador) · techo con desalojo LRU · `apagar_todo()`, que es lo
      que el `finally` del lifespan llama para que `main.py` por fin sepa qué matar

**DESDE D2 EL DUEÑO SOSTIENE.** `OCIOSIDAD_S = 600`: al soltar el último préstamo la
conexión NO se cierra — queda viva y el reloj empieza a correr. Eso es lo que mata el
arranque doble del §6: hoy el usuario paga el spawn al abrir (el calentador mide y apaga) y
otra vez en el primer mensaje. Quien cierra es el cosechador, no el que suelta.

⚠️ NADA DE ESTO PUEDE INTERRUMPIR UNA LLAMADA EN CURSO. Una conexión PRESTADA no envejece
(su reloj arranca cuando el refcount llega a 0) y no la desaloja el techo. Matar a mitad de
un `tool_call` le devuelve al usuario un `-32000` que el diagnóstico lee como «el server se
murió» — mentira, lo matamos nosotros.

── LA CLAVE NO ES LA ENTIDAD (§2 del diseño) ────────────────────────────────────────
`(user_id, entity_id, huella)`, donde la huella es un hash de `(command, args, env, cwd)`
YA EXPANDIDOS. No es prolijidad:

  · compartir por `entity_id` a secas cruzaría la credencial de un usuario con el proceso
    de otro — la fuga BYOK cross-user que `recipe_assembler.py:844-850` documenta como
    incidente REAL, reintroducida con otro mecanismo;
  · y la huella hace que `filesystem` y `memory` NO compartan **solos**, sin una lista de
    excepciones: su `${PUPPET_WORKDIR}` es un temp por run que hornean como allow-list al
    arrancar (`recipe_assembler.py:786-787`, `:802-805`), así que su huella cambia por run.

── HUÉRFANOS IMPOSIBLES POR CONSTRUCCIÓN (§3.2) ─────────────────────────────────────
La línea del `procesos.jsonl` se escribe **antes** del spawn, con `fsync`, en estado
`naciendo` y sin pid —porque todavía no existe—. Si el sidecar muere en esa ventana, el
próximo arranque ve `comando` + `nacido_en` y puede barrer igual. Escribir DESPUÉS del
spawn es la ventana por la que se escaparon 9 GB de `_MEI`.

⚠️ LOS PIDS NO LOS DA EL TRANSPORTE. Medido en la sesión 1 del SDK: `stdio_client` hace
`yield read_stream, write_stream` y se queda el `Process` en su closure. El dueño los
descubre mirando SUS PROPIOS HIJOS (`ppid == os.getpid()`) antes y después del spawn — el
diff es exacto, y no depende de parsear una línea de comando.

    python3 platform/inspection/verify_dueno.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

_AQUI = Path(__file__).resolve().parent
# ⚠️ `append`, JAMÁS `insert(0)`. Anteponer este directorio al `sys.path` tapa cualquier
# módulo del mismo nombre que viva en otro lado, para TODO el proceso y para siempre —
# `sys.modules` gana sobre `sys.path`, así que el import equivocado no se corrige después.
#
# MEDIDO el 2026-08-12: hay un `models.py` acá y otro en `assembler/`. Este archivo se carga
# en el arranque (el barrido del dueño), y con `insert(0)` el suyo ganaba; a partir de ahí
# `recipe_assembler` hacía `import models` y recibía el de inspección. Resultado: el borde de
# los SEIS workspaces devolvía `502 «module 'models' has no attribute
# 'resolve_recipe_model'»`. Intermitente, porque dependía de qué se importó primero.
#
# `models` es la ÚNICA colisión medida entre los dos paquetes (57 vs 68 módulos), y con
# `append` se resuelve bien igual: lo que este paquete necesita del path propio
# (`transporte_sdk`, `grabador`) existe SÓLO acá.
if str(_AQUI) not in sys.path:
    sys.path.append(str(_AQUI))
if str(_AQUI.parent) not in sys.path:
    sys.path.insert(0, str(_AQUI.parent))

#: La perilla, con el mismo patrón que `ALEPH_TRANSPORTE`: se lee en UN solo lugar y en cada
#: llamada, para que un test que la mueva la vea y un rollback no exija reiniciar.
#: `off` (default en D1) = los consumidores spawnean como siempre.
_ENV_PERILLA = "ALEPH_DUENO"

#: OCIOSIDAD (§1.2) — cuánto sobrevive una conexión con refcount 0. **D2 la sube a 600 s:
#: acá el dueño empieza a SOSTENER**, que es lo que mata el arranque doble del §6.
#:
#: ⚠️ NO ES UN NÚMERO MEDIDO: es una apuesta declarada, y el diseño lo dice así. Los dos
#: lados de la balanza sí están medidos: sostener ahorra 274-819 ms de handshake por server
#: (~3 s por agente de 6 piezas) y cuesta ~113 MB por conexión, lineal. 10 minutos es la
#: ventana en la que una conversación sigue siendo la misma conversación. Por eso es
#: configurable y por eso `estado()["eventos"]` cuenta los cierres por ociosidad: la sesión
#: que quiera corregirlo lo hace con datos, no con opinión.
OCIOSIDAD_S = float(os.environ.get("ALEPH_DUENO_OCIOSIDAD_S", "600"))
#: Alias histórico (D1 lo llamaba así). Se mantiene porque es lo que mide la vara de D1.
RETENCION_S = OCIOSIDAD_S

#: TECHO (§4.1) — cuántas conexiones vivas a la vez.
#:
#: ERA 8, Y 8 ES EXACTAMENTE EL TAMAÑO DEL KIT. Desde que el workdir es del hilo, cada
#: conversación necesita SUS 4 piezas atadas al workdir (`filesystem`, `sqlite`,
#: `pysandbox`, `officecli`) más las 4 que comparte con todas (`duckduckgo`, `fetch`,
#: `markitdown`, `skills`). Con techo 8, UN hilo llenaba el techo entero y el segundo
#: desalojaba al primero: medido, volver a la conversación anterior costaba ~4 s de
#: re-spawn. Con 24 la vuelta cuesta 87,8 ms — sale como un turno caliente cualquiera.
#:
#: LA CUENTA VIEJA ESTABA 6× PESIMISTA. Decía «8 × ~113 MB ≈ 0,9 GB»; medido con RSS sobre
#: 20 conexiones vivas de verdad (4 hilos calientes): **379 MB, o sea ~19 MB por
#: conexión** — son `uv`, `npm` y pythons chicos, no procesos gordos. 24 conexiones son
#: ~455 MB, que sí es defendible para una `.app` con su sidecar y su webview.
#:
#: 24 = 4 compartidas + 4 × 5, o sea CINCO conversaciones calientes a la vez. Es el número
#: que se eligió, no el que salió: pasado eso el LRU desaloja, que es lo correcto.
MAX_VIVAS = int(os.environ.get("ALEPH_DUENO_MAX_VIVAS", "24"))

def _tick_de(ociosidad_s: float) -> float:
    """Cada cuánto despierta el cosechador, derivado de la ociosidad DE ESA INSTANCIA.

    ⚠️ De la instancia, no de la constante del módulo — la vara cazó por qué: leyendo
    `OCIOSIDAD_S` global, un dueño construido con 0,6 s de ociosidad igual dormía 15 s, así
    que la conexión se cerraba mucho después de vencer (o nunca, dentro de la ventana de un
    test). Derivarlo también evita el otro extremo: en producción, con 600 s, nadie quiere
    un hilo despertándose cada segundo sin motivo.
    """
    return max(0.1, min(15.0, float(ociosidad_s) / 4.0))

#: VENTANA (no umbral) alrededor de `nacido_en` para aceptar que un pid es el que anotamos.
#: `ps` tiene resolución de segundo y entre que anotamos y el hijo existe pasan milisegundos.
#:
#: ⚠️ ES UNA VENTANA, `abs(arranque - nacido_en) <= T`, y la vara cazó por qué: la primera
#: versión pedía `arranque >= nacido_en - T`, que acepta **todo lo que arrancó después** —
#: o sea, exactamente el pid reciclado que este chequeo existe para descartar. Un pid
#: reciclado siempre arranca MÁS TARDE que nuestro registro; la hora es el discriminador
#: fuerte y el comando el corroborante.
_TOLERANCIA_S = 5.0

#: [Obra 1] Cuánto de más espera el que NO spawnea, por encima del plazo del que sí. No es
#: una estimación del arranque: es el colchón entre «el otro agotó su plazo» y «me cuelgo
#: para siempre». Un pedido que espera un nacimiento ajeno tiene que morir DESPUÉS que el
#: nacimiento, nunca antes, o se despertaría a decidir sobre una tabla a medio escribir.
_MARGEN_NACIMIENTO_S = 5.0

#: [Obra 1] El lock del descubrimiento de pids POR DIFF. No es el lock del dueño: sólo se
#: toman entre sí los spawns que necesitan comparar `_hijos_directos()` antes y después,
#: porque su servidor no expone el pid. Dos diffs simultáneos se roban los hijos; un diff
#: y un pack con pid propio no se estorban, y por eso los packs no lo tocan.
_LOCK_DIFF_PIDS = threading.Lock()


def encendido() -> bool:
    """¿Los consumidores tienen que pedirle al dueño? Se lee en cada llamada.

    PRENDIDO POR DEFAULT. Estuvo en `off` mientras el workdir cambiaba en cada turno: el
    dueño sostenía procesos que nadie podía reusar (4 de 8 piezas con huella nueva por
    turno, medido) y eso era gasto puro. Con la carpeta estable por hilo el reuso existe y
    está medido: `asm.restaurar` 2.529 ms en el t1 → 26-32 ms de t2 en adelante.
    `ALEPH_DUENO=off` lo apaga y devuelve el spawn por turno de siempre."""
    return (os.environ.get(_ENV_PERILLA) or "on").strip().lower() in ("on", "1", "true")


class DuenoError(Exception):
    """Falla del dueño (no de la conexión). Se levanta; no se traga."""


# ── 1 · LA HUELLA ───────────────────────────────────────────────────────────────────

class EnvDelHijo(dict):
    """El entorno del hijo, sabiendo CUÁLES de sus claves declaró la receta (§9.2).

    Es un `dict` de verdad: quien lo recibe lo pasa a `Popen`, le hace `dict(...)` o lo
    compara con otro dict y no nota nada. Lo único que agrega es `declaradas`, y sólo lo
    mira `huella()`.

    **Por qué un atributo y no un parámetro.** Entre quien SABE qué declaró la receta
    (`_expand_server_cfg`, que tiene el `scfg` crudo en la mano) y quien calcula la huella
    hay tres saltos —`restaurar_servers` → `mcp_server_cls(...)` → `pedir(spec=...)`— y dos
    de ellos son puntos de extensión con firma pública, uno de ellos inyectable en tests.
    Agregarles un parámetro es justamente la trampa 9 del acta: *un guard no se ata a una
    firma literal*. Viajando pegado al valor que YA cruza esos tres saltos, no hay firma que
    cambiar ni clase que sepa de esto.

    ⚠️ **Y SI SE PIERDE, SE PIERDE HACIA EL LADO BARATO.** Cualquier `dict(env)` en el
    camino devuelve un dict pelado y `declaradas` desaparece; `huella()` entonces hashea el
    env COMPLETO, que es el comportamiento de antes de §9.2: **se comparte de menos, nunca
    de más.** Un proceso extra cuesta 113 MB; compartir dos que no debían compartirse cuesta
    la fuga BYOK del §2.1. El modo de fallo tenía que ser ése y es ése.
    """

    __slots__ = ("declaradas",)

    def __init__(self, base=None, *, declaradas=()):
        super().__init__(base or {})
        self.declaradas = frozenset(declaradas)


def huella(command: str, args: Optional[list], env: Optional[dict],
           cwd: Optional[str]) -> str:
    """Hash de lo que se va a hornear en el proceso al arrancar.

    §9.2 · **ENTRA EL ENV QUE LA RECETA DECLARA, NO EL ENV COMPLETO DEL PROCESO** — cuando
    el llamante lo marcó con `EnvDelHijo` (los dos que ejecutan: el run vía
    `_expand_server_cfg` y la sonda vía `_spawn`). Sin marca, entra todo, como antes.

    No es «elegir qué claves cuentan» a dedo —esa lista de excepciones es justamente lo que
    este diseño evita—: cuentan las que la RECETA declara, que es un dato del catálogo, con
    autor, auditable y versionado como cualquier otro. La lista no la escribe este archivo.

    Por qué hizo falta: la huella sobre el env completo hashea `PUPPET_WORKDIR`, que el
    calentador fija (`…/T/aleph-probe-workdir`) y cada run inventa (`mkdtemp`). Esa sola
    variable partía la huella de TODAS las piezas —incluso las que jamás la leen— así que
    ninguna pieza calentada se reusaba nunca, y dos runs tampoco compartían entre sí (§6).

    **La condición que lo hace seguro no vive acá.** Si un server LEE algo que su receta no
    declara, dos conexiones que difieren SÓLO en eso comparten proceso, y compartir de más
    ES la fuga BYOK del §2.1. Quien sostiene esa condición es
    `platform/inspection/verify_env_declarado.py`, vara PERMANENTE y bloqueante. Esta línea
    se apoya en ella: si vuelve a ponerse roja, esto vuelve atrás.

    **Del hash NO sale ningún valor.** Es un digest: no se puede leer una llave desde acá,
    y por eso la huella puede viajar a `estado()` y a los logs sin violar «llaves jamás en
    logs». Lo que se publica son 12 hex, suficiente para distinguir y inútil para revertir.

    ⚠️ **EL MODO DE FALLO SIGUE SIENDO EL BARATO.** Una variable declarada que cambie entre
    dos pedidos parte la huella y levanta un segundo proceso; y si la marca `EnvDelHijo` se
    pierde en el camino (cualquier `dict(env)` la borra), se vuelve a hashear el env
    completo — más particiones, nunca menos. Medido en su momento: el primer spawn importa
    `sidecar_serve`, que hace `os.environ.setdefault("ALEPH_ROLE", "client")`
    (`sidecar_serve.py:28`), así que un llamante que tome `dict(os.environ)` antes y después
    del primer spawn obtiene dos dicts distintos. El error va SIEMPRE en la misma dirección:
    **se comparte de menos, nunca de más.** Un proceso extra cuesta 113 MB; compartir dos que
    no debían compartirse cuesta la fuga del §2.1.
    """
    # ⚠️ SOBRE EL ENTORNO QUE EL HIJO RECIBE DE VERDAD, no sobre el que pasó el llamante.
    # `transporte.entorno_del_hijo()` aplica lo que el transporte vaya a aplicar (el puente
    # pisa el PATH con el de Aleph; el cliente viejo no toca nada). Sin esto, dos pedidos
    # IDÉNTICOS daban huellas distintas: `ensure_user_path()` muta `os.environ["PATH"]` la
    # primera vez que corre, así que el `dict(os.environ)` de antes del primer spawn y el
    # de después no son iguales. Lo cazó la vara.
    # §9.2 · LA HUELLA SE CALCULA SOBRE EL ENV **DECLARADO EN LA RECETA**. Se lee ACÁ,
    # antes de `entorno_del_hijo`, porque ése devuelve un dict pelado y el atributo no
    # sobrevive el viaje. `None` (nadie marcó nada) = env completo, como siempre.
    declaradas = getattr(env, "declaradas", None)
    try:
        import transporte as _TP
        efectivo = _TP.entorno_del_hijo(env)
    except Exception:                                      # noqa: BLE001
        efectivo = dict(env or {})
    if declaradas is not None:
        # Lo que la receta NO declara no puede distinguir dos conexiones: si un server LEE
        # algo no declarado, esto las haría compartir de más — que es la fuga del §2.1. Por
        # eso `verify_env_declarado.py` es una vara PERMANENTE y bloqueante: es la que
        # sostiene esta línea. No se relaja sin volver a ponerla verde.
        efectivo = {k: v for k, v in efectivo.items() if k in declaradas}
    material = json.dumps({
        "command": str(command or ""),
        "args": [str(a) for a in (args or [])],
        "env": {str(k): str(v) for k, v in sorted(efectivo.items())},
        "cwd": str(cwd or ""),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def clave_de(user_id: Optional[str], entity_id: str, h: str) -> str:
    return f"{user_id or '-'}|{entity_id}|{h}"


# ── 2 · EL ARCHIVO DE PROCESOS ──────────────────────────────────────────────────────

def _ruta_procesos() -> Path:
    import aleph_paths
    return aleph_paths.procesos_path()


class _Libro:
    """El `procesos.jsonl`. Una línea por conexión, reescrito entero en cada cambio.

    Reescribir entero y no anexar es deliberado: el archivo es CHICO (tope de vivas del §4)
    y un `.jsonl` que sólo crece obliga a un compactado que es otra cosa que puede fallar a
    mitad. Se escribe a un temporal y se renombra —`os.replace` es atómico— así que un corte
    de luz deja el archivo anterior entero, nunca uno a medias.
    """

    def __init__(self, ruta: Optional[Path] = None):
        self._ruta = ruta
        self._lock = threading.Lock()

    @property
    def ruta(self) -> Path:
        if self._ruta is None:
            self._ruta = _ruta_procesos()
        return self._ruta

    def leer(self) -> list:
        try:
            crudo = self.ruta.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except Exception as e:                             # noqa: BLE001
            raise DuenoError(f"no pude leer {self.ruta}: {e}") from e
        filas, rotas = [], 0
        for linea in crudo.splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                filas.append(json.loads(linea))
            except json.JSONDecodeError:
                rotas += 1                                 # §9.8: se saltea y se reporta
        if rotas:
            print(f"[dueño] {rotas} línea(s) ilegibles en {self.ruta.name}: se saltean. "
                  f"Si dejaron un proceso vivo, este arranque NO lo va a barrer.",
                  file=sys.stderr, flush=True)
        return filas

    def escribir(self, filas: list) -> None:
        """Atómico y con `fsync`. Sin el fsync, el `naciendo` puede no estar en disco cuando
        el proceso hijo ya existe — o sea, la ventana que este archivo viene a cerrar."""
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
            except Exception as e:                         # noqa: BLE001
                raise DuenoError(f"no pude escribir {self.ruta}: {e}") from e


# ── 3 · LOS PROCESOS DEL SISTEMA ────────────────────────────────────────────────────

def _hijos_directos() -> set:
    """Los PID cuyo padre somos nosotros. Base del descubrimiento del §3 del diseño.

    ⚠️ SE EXCLUYE A SÍ MISMO, y no es paranoia — es un bug que esta función tuvo y que la
    vara cazó: `ps` es un hijo directo NUESTRO y aparece en su propia salida. El diff
    antes/después metía el pid de ese `ps` en la lista de la conexión, y como muere al
    instante, la conexión se veía muerta un segundo después de nacer. Por eso `Popen` en
    vez de `run`: para saber qué pid descartar.
    """
    try:
        p = subprocess.Popen(["ps", "-eo", "pid=,ppid="], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True)
        salida, _ = p.communicate(timeout=5)
    except Exception:                                      # noqa: BLE001
        return set()
    yo, fuera = os.getpid(), set()
    for linea in (salida or "").splitlines():
        partes = linea.split()
        if len(partes) == 2:
            try:
                pid, ppid = int(partes[0]), int(partes[1])
            except ValueError:                             # pragma: no cover
                continue
            if ppid == yo and pid != p.pid:
                fuera.add(pid)
    return fuera


def _descendientes(raices: set) -> set:
    """Los raíces MÁS todo lo que cuelga de ellos. Un server son DOS procesos (medido:
    `uv tool uvx` / `npm exec` no se van), así que anotar sólo el hijo directo describiría
    la mitad del árbol."""
    if not raices:
        return set()
    try:
        r = subprocess.run(["ps", "-eo", "pid=,ppid="], capture_output=True, text=True,
                           timeout=5)
    except Exception:                                      # noqa: BLE001
        return set(raices)
    hijos: dict = {}
    for linea in r.stdout.splitlines():
        partes = linea.split()
        if len(partes) != 2:
            continue
        try:
            hijos.setdefault(int(partes[1]), []).append(int(partes[0]))
        except ValueError:                                 # pragma: no cover
            continue
    fuera, cola = set(), list(raices)
    while cola:
        pid = cola.pop()
        if pid in fuera:
            continue
        fuera.add(pid)
        cola.extend(hijos.get(pid, []))
    return fuera


def _vive(pid: int) -> bool:
    """¿Ese pid es un proceso VIVO?

    ⚠️ UN ZOMBIE NO ESTÁ VIVO, y `os.kill(pid, 0)` dice que sí. Es el caso normal, no un
    borde: los MCP son hijos NUESTROS, así que entre que mueren y alguien los cosecha
    quedan en estado `Z` — con su pid todavía en la tabla del kernel. Sin este chequeo, el
    dueño reportaría viva una conexión muerta y el barrido creería que no logró matar lo
    que sí mató. Lo cazó la vara.
    """
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True                                        # existe y no es nuestro
    except Exception:                                      # noqa: BLE001
        return False
    try:
        r = subprocess.run(["ps", "-o", "state=", "-p", str(pid)],
                           capture_output=True, text=True, timeout=5)
        estado = (r.stdout or "").strip()
        if estado and estado[0].upper() == "Z":
            return False
    except Exception:                                      # noqa: BLE001
        pass                                               # sin `ps`, vale el `kill(0)`
    return True


def _comando_y_arranque(pid: int) -> tuple:
    """`(command, epoch_de_arranque)` de un pid, o `("", None)`."""
    try:
        r = subprocess.run(["ps", "-o", "lstart=,command=", "-p", str(pid)],
                           capture_output=True, text=True, timeout=5)
    except Exception:                                      # noqa: BLE001
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
        # «pid reciclado» a un proceso nuestro y NO barrerlo. La vara lo cazó.
        ts = time.mktime(time.strptime(fecha, "%a %b %d %H:%M:%S %Y"))
    except Exception:                                      # noqa: BLE001
        ts = None
    return comando, ts


def _mismo_comando(esperado: str, args: list, comando_ps: str) -> bool:
    """¿La línea de `ps` corresponde a lo que anotamos?

    Se compara por **basename y sin distinguir mayúsculas**, no por ruta, y es la misma
    doctrina que ya tiene el barrido de `_MEI` (`sidecar_serve.py:257-262`): *«matchear por
    ruta pierde la mitad»*. Acá el motivo es aún más concreto y está medido: `ps` reporta el
    binario RESUELTO, así que un `command` de `<venv>/bin/python` aparece como
    `/opt/homebrew/.../Python.app/Contents/MacOS/Python` — ni la ruta ni la caja coinciden.

    Y los ARGS también corroboran, porque los lanzadores no sobreviven al resolvedor: `uvx`
    se convierte en otro binario, pero `mcp-server-fetch` sigue estando en la línea.
    """
    bajo = (comando_ps or "").lower()
    if not bajo:
        return False
    base = os.path.basename(str(esperado or "")).lower()
    if base and base in bajo:
        return True
    for a in (args or []):
        texto = str(a).lower()
        if len(texto) >= 4 and texto in bajo:              # 4 = no matchear "-m" ni "."
            return True
    return False


def _rss_kb(pids) -> Optional[int]:
    """RSS sumado del árbol, best-effort. `None` si no se pudo medir — jamás 0 inventado."""
    if not pids:
        return None
    try:
        r = subprocess.run(["ps", "-o", "rss=", "-p", ",".join(str(p) for p in pids)],
                           capture_output=True, text=True, timeout=5)
        vals = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        return sum(vals) if vals else None
    except Exception:                                      # noqa: BLE001
        return None


# ── 4 · LA TABLA DE VIVOS ───────────────────────────────────────────────────────────

class _Conexion:
    """Una entrada de la tabla. No la construye nadie de afuera."""

    def __init__(self, clave: str, *, entity_id: str, user_id: Optional[str], h: str,
                 comando: str, args: list, cwd: Optional[str]):
        self.clave = clave
        self.entity_id = entity_id
        self.user_id = user_id
        self.huella = h
        self.comando = comando
        self.args = list(args or [])
        self.cwd = cwd
        self.servidor: Any = None
        self.pids: list = []
        self.nacida_en = time.time()
        self.ultimo_uso = self.nacida_en
        self.refcount = 0
        self.prestada_a: list = []
        self.muerta = False
        #: R1 · ¿ya se emitió el evento de muerte de ESTA conexión? El push (EOF), el vigía
        #: y el `_cerrar` pueden llegar a la misma muerte por caminos distintos; el evento
        #: sale UNA vez. `muerta` no alcanza: se pone al cerrar, y el aviso es ANTES.
        self.aviso_emitido = False
        #: EFÍMERA: se cierra al soltar el último préstamo, sin importar la ociosidad.
        #: Para conexiones que por construcción NO se van a reusar — la sonda de credencial
        #: con basura es el caso: su `env` lleva `clave-falsa-de-prueba-0000`, así que
        #: ningún run va a pedir jamás esa huella. Sostenerla son 113 MB de puro desperdicio,
        #: y con dos entidades con llave ya son 226 MB.
        self.efimera = False
        self.lock_llamada = threading.Lock()   # §2.4: v1 serializa por conexión
        #: [Obra 1 · el lock no cubre la espera de salud] NACIENDO: la entrada existe en la
        #: tabla pero su proceso todavía no contestó su señal. El lock del dueño se suelta
        #: durante esa espera —que es lo caro (medido: 5,89 s el pack más lento)— así que
        #: hay una ventana en la que OTRO llamante puede ver esta entrada a medio hacer.
        #:
        #: Sin este estado, ese otro llamante cae al `_cerrar(…, "entrada muerta")` de
        #: `pedir` —porque `servidor` todavía es `None`— y spawnea un DUPLICADO, dejando al
        #: primero fuera de la tabla: un huérfano que ni el barrido de arranque ve. La
        #: exclusión mutua que se pierde al soltar el lock se recupera acá, POR ENTIDAD:
        #: quien encuentra una entrada naciendo espera este pestillo en vez de spawnear.
        self.naciendo = False
        #: Se abre cuando el nacimiento terminó, salga bien o mal. Nace ABIERTO para que una
        #: entrada que nunca pasó por `_levantar` no haga esperar a nadie.
        self.listo = threading.Event()
        self.listo.set()
        #: La causa del nacimiento fallido, para que el que esperaba reciba el MISMO error
        #: que el que spawneó —con su copy— en vez de un timeout mudo o un duplicado.
        self.fallo_nacimiento = ""

    def fila(self, estado: str) -> dict:
        return {"clave": self.clave, "entity_id": self.entity_id, "user_id": self.user_id,
                "huella": self.huella, "comando": self.comando, "args": self.args,
                "cwd": self.cwd, "nacido_en": self.nacida_en, "pids": list(self.pids),
                "estado": estado}


class Prestamo:
    """Una conexión PRESTADA. Expone lo mismo que un server —`list_tools`, `call_tool`,
    `diagnostico`— y **no expone `stop()`**: quien pide una conexión no la mata.

    Es un context manager a propósito (§6.1): un `soltar()` que no se llama es una fuga, y
    el árbol ya tiene siete `finally: srv.stop()` justamente por eso. El `with` hace el
    `finally` obligatorio.
    """

    def __init__(self, dueno: "Dueno", con: _Conexion, motivo: str):
        self._dueno = dueno
        self._con = con
        self._motivo = motivo
        self._soltado = False

    # -- identidad --
    @property
    def clave(self) -> str:
        return self._con.clave

    @property
    def entity_id(self) -> str:
        return self._con.entity_id

    @property
    def pids(self) -> list:
        return list(self._con.pids)

    # -- operaciones, con el mismo contrato sync de siempre --
    def list_tools(self) -> list:
        return self._op("list_tools")

    def call_tool(self, tool_name: str, arguments: dict):
        return self._op("call_tool", tool_name, arguments)

    def diagnostico(self) -> dict:
        srv = self._con.servidor
        return (srv.diagnostico() if srv is not None else {}) or {}

    def _op(self, nombre: str, *a):
        if self._soltado:
            raise DuenoError(f"préstamo de «{self._con.entity_id}» ya soltado")
        srv = self._con.servidor
        if srv is None:
            raise DuenoError(f"la conexión de «{self._con.entity_id}» no está viva")
        # §2.4 · v1 SERIALIZA. El cliente viejo ya lo hacía (`assembler.py:289`); el puente
        # NO, y compartir proceso estrenaría una concurrencia que nunca ejercitamos. Se
        # suelta cuando se mida, no en el mismo commit que estrena el proceso compartido.
        with self._con.lock_llamada:
            self._con.ultimo_uso = time.time()
            try:
                return getattr(srv, nombre)(*a)
            finally:
                self._con.ultimo_uso = time.time()

    # -- ciclo --
    def soltar(self) -> None:
        """Baja el refcount. Idempotente. Normalmente lo llama el `with`."""
        if self._soltado:
            return
        self._soltado = True
        self._dueno._soltar(self._con, self._motivo)

    def __enter__(self) -> "Prestamo":
        return self

    def __exit__(self, *_exc) -> bool:
        self.soltar()
        return False


#: R1 · el `motivo` de `_cerrar` → el disparador de §1.2. El motivo es un string que ya
#: existía y viaja a los logs; el disparador es el vocabulario CERRADO que repair clasifica.
#: Se deduce de uno para no tener que tocar los siete `_cerrar(...)` que ya hay.
_DISPARADORES = (
    ("murió y se pidió de nuevo", "R1"),   # la muerte que el reconnect-once encontró
    ("no arrancó",                "R3"),   # nunca llegó a estar vivo
    ("lápida",                    "LAPIDA"),
    ("ociosidad",                 "OCIOSIDAD"),
    ("techo",                     "LRU"),
    ("cierre",                    "CIERRE"),
    ("fin de la vara",            "CIERRE"),
)


def _disparador_de(motivo: str) -> str:
    """Clasifica el `motivo` textual. Lo desconocido es `OTRO`, no una suposición.

    ⚠️ `LAPIDA`, `OCIOSIDAD`, `LRU` y `CIERRE` **no son casos de repair** — son el dueño
    haciendo su trabajo o el usuario decidiendo. Viajan igual porque el evento se emite
    SIEMPRE (decisión 6.A del diseño: el fantasma es un caso de UNA muerte, y filtrar en el
    origen lo dejaría fuera). Quien filtra es repair, no el dueño.
    """
    m = (motivo or "").lower()
    for aguja, disp in _DISPARADORES:
        if aguja in m:
            return disp
    return "OTRO"


class ServidorPrestado:
    """Un préstamo del dueño **con la forma de `MCPServer`**: `start` · `list_tools` ·
    `call_tool` · `diagnostico` · `stop`. Es el único adaptador, y vive acá a propósito.

    Lo estrenó el run (D4) y lo reusa la Sesión VIVA (D5). Empezó viviendo en
    `recipe_assembler`; se movió cuando apareció el segundo consumidor, porque **dos
    adaptadores al mismo dueño se desincronizan sin que nadie se entere** — y no en algo
    cosmético: el `call_tool` de acá tiene una regla (no dejar escapar la excepción de la
    lápida) que costó una vara descubrir, y una copia sin esa regla habría tumbado el loop
    de la Sesión con el mismo bug ya pagado. El adaptador es del DUEÑO, no de su llamante.

    Quien construye llama `Clase(...)` y DESPUÉS `start()`; el dueño hace las dos cosas en
    `pedir()`. El adaptador difiere el pedido hasta el `start()`, así ni el `restaurador` ni
    el `_boot` de la Sesión cambian una línea.

    `stop()` es `soltar()`. **El proceso NO muere ahí**: queda sostenido por la ociosidad,
    que es todo el punto de D2 — el próximo run o la próxima Sesión lo encuentran caliente.
    Quien lo cierra es el cosechador, la lápida, o el cierre del sidecar.
    """

    def __init__(self, name, command, args, env=None, rpc_timeout=30.0, cwd=None,
                 *, user_id=None, motivo="run"):
        self.name = name
        self._spec = {"command": command, "args": list(args or []), "env": env, "cwd": cwd,
                      "rpc_timeout": rpc_timeout}
        self._user_id = user_id
        self._motivo = motivo
        self._prestamo = None
        self._error = ""

    def _es_efimera(self) -> bool:
        """¿Esta conexión es IRREUSABLE POR CONSTRUCCIÓN? [T1]

        Sí cuando el server depende del workdir que el run inventó para ESTE turno. Su
        huella entonces cambia en cada turno (el workdir entra por `args` —la allow-list de
        `filesystem`, el `--db-path` de `sqlite`— o por el env que la receta declara, como
        `pysandbox`), así que sostenerla es gasto puro: ~113 MB durante `OCIOSIDAD_S` para
        una conexión que NADIE va a poder reusar, y que además ocupa un lugar del techo.

        MEDIDO sobre el kit (3 chats raw del mismo usuario, con el dueño encendido): 3 de
        los 6 daban 3 claves distintas en 3 chats —filesystem · sqlite · pysandbox— y las
        otras 3 —markitdown · duckduckgo · fetch— una sola. Los desalojos LRU fueron 4 con
        apenas 3 conversaciones, y lo que se desalojaba era justamente esta basura.

        LAS DOS CONDICIONES SON NECESARIAS, y por eso no alcanza con mirar sólo una:
          · que el workdir sea EFÍMERO — lo marca `_puppet_run_env`, el único que sabe si
            lo generó (`mkdtemp`) o si lo exportó el llamante. Un workdir estable da huella
            estable y ahí la conexión SÍ se reusa: marcarla efímera la tiraría de gusto.
          · que el spec lo REFERENCIE — `markitdown`/`duckduckgo`/`fetch` corren con el
            mismo env y no lo tocan; marcarlas cerraría justo las 3 que sí se comparten.

        Fail-safe: ante cualquier duda devuelve False (sostener de más cuesta memoria;
        cerrar de más cuesta el arranque de una conexión que se iba a reusar).
        """
        env = self._spec.get("env") or {}
        try:
            if str(env.get("_ALEPH_WORKDIR_EFIMERO") or "") != "1":
                return False
            wd = str(env.get("PUPPET_WORKDIR") or "")
            if not wd:
                return False
            if any(wd in str(a) for a in (self._spec.get("args") or [])):
                return True
            if wd in str(self._spec.get("command") or ""):
                return True
            # El env DECLARADO por la receta es lo único que entra en la huella (§9.2);
            # si el workdir viaja por ahí, la huella se parte igual (caso `pysandbox`).
            declaradas = getattr(env, "declaradas", None)
            if declaradas:
                return any(wd in str(env.get(k) or "") for k in declaradas)
            return False
        except Exception:                                   # noqa: BLE001 — nunca tumba el run
            return False

    def start(self) -> bool:
        try:
            self._prestamo = actual().pedir(self.name, spec=self._spec,
                                            user_id=self._user_id, motivo=self._motivo,
                                            efimero=self._es_efimera())
            return True
        except Exception as e:                              # noqa: BLE001 — frontera del run
            self._error = f"{type(e).__name__}: {e}"
            return False

    def list_tools(self) -> list:
        if self._prestamo is None:
            return []
        try:
            return self._prestamo.list_tools()
        except Exception:                                   # noqa: BLE001 — igual que MCPServer
            return []

    def call_tool(self, tool_name, arguments):
        """El MISMO string que devuelve `MCPServer.call_tool`, error por error.

        ⚠️ NO SE DEJA ESCAPAR UNA EXCEPCIÓN. El dueño levanta `DuenoError` cuando la conexión
        ya no está viva —el caso normal es la LÁPIDA: el usuario desconectó la pieza con el
        run o la Sesión andando— y el `ToolRegistry` espera un STRING con el prefijo
        `[MCP error: …]`, que es lo que el cliente viejo devolvía cuando el proceso estaba
        muerto. Dejar salir la excepción cambia un error tipado que el llamante sabe leer por
        una que tumba el loop. Lo cazó `verify_run_dueno.py` §4.

        **Y ES ACÁ DONDE LA SESIÓN SE ENTERA DE LA LÁPIDA**: no hay aviso ni callback: el
        usuario desconecta, el proceso muere aunque esté prestado, y el siguiente `call_tool`
        devuelve el string de error. Enterarse en la llamada es lo correcto — un préstamo que
        nadie usa no necesita que le avisen nada.
        """
        if self._prestamo is None:
            return f"[MCP error: no response from {self.name}]"
        try:
            return self._prestamo.call_tool(tool_name, arguments)
        except Exception as e:                              # noqa: BLE001 — frontera del run
            return f"[MCP error: {type(e).__name__}: {e}]"

    def diagnostico(self) -> dict:
        if self._prestamo is None:
            return {"detail": self._error or "no se pidió la conexión", "exit_code": None}
        d = dict(self._prestamo.diagnostico() or {})
        if self._error and not d.get("detail"):
            d["detail"] = self._error
        return d

    def stop(self) -> None:
        """Devuelve el préstamo. Idempotente: llamarlo dos veces no rompe ni descuenta dos
        veces el refcount (lo garantiza `Prestamo.soltar`)."""
        if self._prestamo is not None:
            self._prestamo.soltar()


class Dueno:
    """El supervisor. Uno por proceso del sidecar (ver `actual()`)."""

    def __init__(self, *, libro: Optional[_Libro] = None, servidor_cls=None,
                 retencion_s: Optional[float] = None, max_vivas: Optional[int] = None):
        self._tabla: dict = {}
        self._lock = threading.RLock()
        self._libro = libro if libro is not None else _Libro()
        self._servidor_cls = servidor_cls
        self._retencion_s = OCIOSIDAD_S if retencion_s is None else float(retencion_s)
        self._max_vivas = MAX_VIVAS if max_vivas is None else int(max_vivas)
        self._contadores = {"reconnect_once": 0, "muertes": 0, "spawns": 0,
                            "compartidas": 0, "barridas_al_arrancar": 0,
                            "cerradas_por_ociosidad": 0, "desalojos_lru": 0,
                            "sobrecupo": 0, "efimeras_cerradas": 0,
                            "muertes_avisadas": 0}
        self._cosechador: Optional[threading.Thread] = None
        self._parar = threading.Event()
        #: R1 · los suscriptores del evento de muerte, y la cola de lo pendiente de entregar.
        self._suscriptores: list = []
        #: R3 · el guardia opcional (ver `poner_guardia`). `None` = levantar como siempre.
        self._guardia = None
        self._pendientes: list = []
        #: ⚠️ **RLock, y no un Lock.** `pedir()` entrega en su `finally`; si un suscriptor
        #: llama a `pedir()` —que es lo primero que va a hacer repair para reintentar—, ese
        #: `pedir` interno vuelve a entregar EN EL MISMO HILO. Con un `Lock` pelado eso es un
        #: deadlock liso: el hilo se espera a sí mismo y el dueño queda tomado para siempre.
        #: Lo cazó la §6 de `verify_evento_muerte.py` antes de que existiera repair.
        self._lock_entrega = threading.RLock()

    # ── R1 · EL EVENTO DE MUERTE (§1 del DISEÑO-REPAIR-v1) ──────────────────────────
    def suscribir(self, fn) -> None:
        """Registra un suscriptor del evento de muerte. **Es opcional a propósito**: sin
        suscriptores el dueño se comporta EXACTAMENTE como antes de R1, y eso es lo que
        mantiene verde a `verify_dueno.py` sin tocarlo.

        `fn(MuerteMCP) -> None`. Se llama **FUERA del lock** (ver `_entregar`).
        """
        with self._lock:
            if fn not in self._suscriptores:
                self._suscriptores.append(fn)

    def poner_guardia(self, fn) -> None:
        """R3 · Registra el guardia que decide si un spawn puede pasar. **Opcional**: sin
        guardia el dueño levanta como siempre, y eso es lo que mantiene verde a
        `verify_dueno.py` sin tocarlo.

        `fn(user_id, entity_id, clave) -> objeto con .pasa (bool) y .motivo (str)`. El dueño
        NO sabe qué es repair ni qué política aplica: sólo pregunta. Es la misma frontera que
        `suscribir` en la otra dirección — si el dueño importara repair, el módulo que POSEE
        los procesos pasaría a saber de reintentos, que es el verbo del otro lado.

        ⚠️ Se consulta **antes de spawnear y sólo cuando hay que spawnear**: reusar una
        conexión viva no pasa por acá. Repair frena procesos NUEVOS; nunca le corta la mano a
        alguien que está usando una que ya anda.
        """
        with self._lock:
            self._guardia = fn

    def _encolar(self, ev: dict) -> None:
        """Encola un evento. Se llama CON el lock tomado; no entrega nada."""
        if self._suscriptores:
            self._pendientes.append(ev)

    def _entregar(self) -> None:
        """Entrega lo encolado. Se llama SIN el lock, después de soltarlo.

        ⚠️ **POR QUÉ NO SE ENTREGA ADENTRO.** `_cerrar` corre con `self._lock` tomado, y el
        lock es un `RLock`: un suscriptor que llamara a `pedir()` para reintentar
        RE-ENTRARÍA el lock en el mismo hilo y seguiría adelante como si nada, mutando la
        tabla en medio de un cierre. No se vería como un deadlock — se vería como
        corrupción intermitente, que es peor. Con otro hilo esperando el lock, sí es un
        deadlock liso. Encolar adentro y entregar afuera cierra los dos casos.

        Un suscriptor que levanta NO puede tumbar al dueño ni comerse los eventos de los
        otros: cerrar un proceso no puede fallar porque alguien quiso escuchar.
        """
        with self._lock_entrega:                           # un solo entregador por vez
            with self._lock:
                pendientes, self._pendientes = self._pendientes, []
                suscriptores = list(self._suscriptores)
            for ev in pendientes:
                for fn in suscriptores:
                    try:
                        fn(ev)
                    except Exception as e:                 # noqa: BLE001 — frontera
                        print(f"[dueño] suscriptor falló con {ev.get('entity_id')}: "
                              f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def _evento_muerte(self, con: "_Conexion", *, disparador: str, motivo: str,
                       t_eof: Optional[float] = None) -> dict:
        """El contrato de §1.3. Se arma CON el lock y CON el `srv` todavía en la mano — que
        es el único momento en que existen a la vez la clave, el motivo y el diagnóstico.
        Un observador externo no puede reconstruirlo: `_cerrar` ya sacó la fila de la tabla.
        """
        diag = {}
        srv = con.servidor
        if srv is not None:
            try:
                diag = dict(srv.diagnostico() or {})
            except Exception:                              # noqa: BLE001 — nunca por evidencia
                diag = {}
        ahora = time.time()
        eof = t_eof if t_eof is not None else diag.get("t_eof")
        return {
            # QUIÉN
            "clave": con.clave, "user_id": con.user_id, "entity_id": con.entity_id,
            "huella": con.huella,
            # CÓMO
            "disparador": disparador,
            "motivo": motivo,
            "stderr": diag.get("stderr") or "",
            "stderr_lineas": diag.get("stderr_lineas") or 0,
            "stderr_bytes": diag.get("stderr_bytes") or 0,
            # `exit_code` es None SIEMPRE y viaja con su motivo: `stdio_client` no expone el
            # proceso (transporte_sdk). Inventar un cero acá sería el pecado que el contrato
            # de `MCPServer` prohíbe.
            "exit_code": diag.get("exit_code"),
            "exit_code_fuente": diag.get("exit_code_fuente"),
            "murio_por_eof": bool(diag.get("murio")),
            "t_eof": eof,
            "senal": None,                                 # hueco declarado (§9.2 del diseño)
            "pids": list(con.pids),
            # LA TRAMPA DEL FANTASMA (§6): los disparos de timeout de este server y cuál era
            # su reloj. Con `t_eof` y esto se puede decir si la muerte siguió a un timeout y
            # a CUÁL de los dos (30 s del run · 45 s de la sonda).
            "timeouts": diag.get("timeouts") or [],
            "rpc_timeout_s": diag.get("rpc_timeout_s"),
            # CUÁNTAS VECES
            "nacida_en": con.nacida_en,
            "vivio_s": round((eof or ahora) - con.nacida_en, 3),
            "ts": ahora,
        }

    # ── EL COSECHADOR (§1.2) ────────────────────────────────────────────────────────
    def _arrancar_cosechador(self) -> None:
        """Un hilo que barre las ociosas. **Tiene que ser un hilo y no un chequeo perezoso
        en `pedir()`**: una conexión ociosa muere porque pasó el tiempo, no porque alguien
        haya vuelto a pedir algo. Con el chequeo perezoso, el usuario que se va y no vuelve
        deja 113 MB colgados para siempre — que es exactamente el caso que la ociosidad
        existe para cerrar.

        Perezoso al arrancar: un proceso que nunca le pide nada al dueño no paga un hilo.
        """
        if self._retencion_s <= 0:
            return                                         # sin ociosidad no hay qué cosechar
        with self._lock:
            if self._cosechador is not None and self._cosechador.is_alive():
                return
            self._parar.clear()
            self._cosechador = threading.Thread(target=self._cosechar_siempre,
                                                name="dueno-cosechador", daemon=True)
            self._cosechador.start()

    def _cosechar_siempre(self) -> None:
        while not self._parar.wait(_tick_de(self._retencion_s)):
            try:
                self.cosechar()
            except Exception as e:                         # noqa: BLE001
                # FALLO VISIBLE: un cosechador que muere callado deja de cerrar conexiones y
                # nadie se entera hasta que la máquina se queda sin memoria.
                print(f"[dueño] el cosechador falló y sigue vivo: {type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)

    # ── R1 · LAS DOS FORMAS DE ENTERARSE SIN QUE NADIE PIDA ─────────────────────────
    def _muerte_push(self, clave: str, t_eof: Optional[float] = None) -> None:
        """El hijo murió y el transporte avisó. Corre en el HILO DRENADOR del transporte.

        ⚠️ **NO CIERRA LA CONEXIÓN.** Sólo anota que murió y emite. Cerrar desde el hilo del
        transporte significaría llamar a `srv.stop()` —que es stdin → 2 s → SIGTERM → 2 s →
        SIGKILL— desde adentro del propio drenador de ese server: el `stop()` cierra el pipe
        que ese mismo hilo está leyendo. Quien cierra sigue siendo el `pedir()` que la
        encuentra muerta, el cosechador o la lápida. Acá sólo se AVISA, que es todo lo que
        R1 promete.
        """
        with self._lock:
            con = self._tabla.get(clave)
            if con is None or con.muerta or not self._suscriptores:
                return                                     # ya la cerró otro: no se duplica
            if con.aviso_emitido:
                return                                     # el EOF llega UNA vez, pero por
            con.aviso_emitido = True                       # las dudas: un solo evento
            self._contadores["muertes_avisadas"] += 1
            self._encolar(self._evento_muerte(
                con, disparador="EOF", motivo="el hijo murió (EOF del stderr)", t_eof=t_eof))
        self._entregar()

    def _vigilar(self) -> int:
        """RED DE SEGURIDAD del push: barre por `ps` las que murieron y nadie avisó.

        Existe porque el push sólo lo da el puente al SDK. El cliente viejo
        (`ALEPH_TRANSPORTE=viejo`) no tiene `al_morir`, y un `on_muerte` puede fallar. Sin
        esto, esos caminos volverían al agujero de antes de R1: enterarse recién cuando
        alguien vuelve a pedir.

        Corre en el tick del cosechador. **Tampoco cierra** — misma razón que el push: el
        cierre tiene dueño y no es la vigilancia.
        """
        avisadas = 0
        with self._lock:
            if not self._suscriptores:
                return 0
            for con in list(self._tabla.values()):
                if con.muerta or con.aviso_emitido or con.servidor is None:
                    continue
                if self._parece_muerta(con):
                    con.aviso_emitido = True
                    self._contadores["muertes_avisadas"] += 1
                    self._encolar(self._evento_muerte(
                        con, disparador="VIGIA",
                        motivo="murió y lo vio el vigía (nadie estaba pidiendo)"))
                    avisadas += 1
        self._entregar()
        return avisadas

    def cosechar(self) -> int:
        """Cierra las ociosas. Devuelve cuántas. Idempotente y llamable a mano (las varas
        lo usan para no depender del reloj)."""
        self._vigilar()                                    # R1 · antes de cosechar
        ahora = time.time()
        with self._lock:
            # [Obra 1 · punto 7, aprobado] Misma razón que en `_hacer_lugar`: una reserva
            # naciendo tiene `refcount == 0` y un `ultimo_uso` que es su hora de nacimiento.
            # Con un `OCIOSIDAD_S` chico (las varas lo bajan a menos de un segundo) el
            # cosechador la cerraría MIENTRAS arranca.
            candidatas = [c for c in list(self._tabla.values())
                          if c.refcount == 0 and not c.naciendo
                          and (ahora - c.ultimo_uso) >= self._retencion_s]
            for con in candidatas:
                self._cerrar(con, motivo="ociosidad")
                self._contadores["cerradas_por_ociosidad"] += 1
        self._entregar()                                   # R1 · SIEMPRE fuera del lock
        return len(candidatas)

    # -- el transporte lo elige `transporte.py`, no este módulo --
    def _cls(self, spec: Optional[dict] = None):
        # [Gate 4 · F4 · O1] UNA CLASE POR SPEC, y NO un segundo dueño.
        #
        # El pack de un workspace es un proceso largo con salud HTTP, no un MCP stdio: su
        # `start()` espera un `/health`, su `stop()` mata el grupo. Lo obvio habría sido
        # instanciar un `Dueno(servidor_cls=…)` aparte para packs — y es exactamente lo que
        # el §5 de este archivo prohíbe: «dos tablas de vivos son dos verdades sobre los
        # mismos procesos». El barrido de arranque, el `apagar_todo()` del lifespan y el
        # `procesos.jsonl` son UNO, y el pack tiene que estar adentro de ese uno o el día
        # que quede huérfano no lo barre nadie.
        #
        # Por eso la clase viaja EN EL SPEC, junto al comando que ya viaja ahí. No entra a
        # la `huella` (que hashea command/args/env/cwd) y no puede: dos pedidos con el mismo
        # comando y distinta clase serían la misma conexión, que es lo correcto — el proceso
        # es el mismo, cambia quién lo sabe hablar.
        clase = (spec or {}).get("clase")
        if clase is not None:
            return clase
        if self._servidor_cls is not None:
            return self._servidor_cls
        import transporte as TP
        return TP.servidor_stdio()

    # ── PEDIR ───────────────────────────────────────────────────────────────────────
    def pedir(self, entity_id: str, *, spec: dict, user_id: Optional[str] = None,
              motivo: str = "", efimero: bool = False) -> Prestamo:
        """La conexión de esa entidad, prestada. La levanta si hace falta; la comparte si
        ya está viva con la MISMA huella.

        `spec` es `{command, args, env, cwd, rpc_timeout}` **ya expandido** — el dueño no
        expande ni resuelve credenciales: eso es del llamante, que es quien sabe de qué
        usuario y de qué run se trata. El dueño sólo compara y spawnea.

        `efimero=True` para lo que por construcción NO se va a reusar: la conexión se cierra
        al soltarla, sin pasar por la ociosidad. Lo pide el llamante porque es el único que
        sabe — el dueño no puede deducir que una `env` lleva una llave basura.
        """
        comando = str(spec.get("command") or "")
        args = list(spec.get("args") or [])
        env = spec.get("env")
        cwd = spec.get("cwd")
        h = huella(comando, args, env, cwd)
        clave = clave_de(user_id, entity_id, h)

        plazo = float(spec.get("rpc_timeout") or 30.0)

        # R1 · el `finally` entrega los eventos DESPUÉS de soltar el lock, y cubre los dos
        # `return` de adentro y también el `DuenoError` de `_levantar`. Sin él, la única
        # forma de no entregar bajo lock sería repetir la llamada en cada salida.
        try:
          # [Obra 1] EL BUCLE EXISTE PORQUE EL LOCK SE SUELTA. Quien encuentra una entrada
          # NACIENDO no puede decidir nada con lo que ve: espera el pestillo y vuelve a
          # mirar la tabla bajo el lock. Sin re-evaluar, decidiría con una foto vieja.
          while True:
            reserva = pestillo = naciente = None
            with self._lock:
                con = self._tabla.get(clave)
                if con is not None and con.naciendo:
                    # NO se cierra y NO se spawnea: otro la está levantando AHORA. Antes de
                    # esta obra este caso era inalcanzable (el lock cubría el arranque
                    # entero) y el código de abajo lo habría tratado como «entrada muerta»,
                    # que es la receta del duplicado + huérfano.
                    pestillo, naciente = con.listo, con
                elif con is not None and not con.muerta and con.servidor is not None:
                    # RECONNECT-ONCE (§5.3) — el dueño haciendo su trabajo, no repair.
                    if self._parece_muerta(con):
                        self._contadores["muertes"] += 1
                        self._cerrar(con, motivo="murió y se pidió de nuevo")
                        con = None
                    else:
                        con.refcount += 1
                        con.prestada_a.append(motivo)
                        con.ultimo_uso = time.time()
                        if not efimero:
                            # Un pedido NO efímero PROMUEVE la conexión: si alguien la va a
                            # reusar, ya no es descartable. Al revés no: un pedido efímero no
                            # degrada una conexión que otro está sosteniendo.
                            con.efimera = False
                        self._contadores["compartidas"] += 1
                        return Prestamo(self, con, motivo)
                if pestillo is None:
                    if con is not None:
                        self._cerrar(con, motivo="entrada muerta")

                    # ── R3 · EL GUARDIA, JUSTO ANTES DE GASTAR ─────────────────────
                    # Acá y no antes: si la conexión estaba viva se reusó más arriba y no se
                    # pregunta nada. Repair frena procesos NUEVOS, no llamadas en curso.
                    if self._guardia is not None:
                        try:
                            permiso = self._guardia(user_id, entity_id, clave)
                        except Exception as e:             # noqa: BLE001 — frontera
                            # Un guardia roto NO puede dejar al producto sin conexiones: se
                            # sigue como si no hubiera guardia. Falla hacia el lado conocido.
                            print(f"[dueño] guardia falló, se levanta igual: "
                                  f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)
                            permiso = None
                        if permiso is not None and not getattr(permiso, "pasa", True):
                            raise DuenoError(
                                f"«{entity_id}» no se levanta ahora: "
                                f"{getattr(permiso, 'motivo', '') or 'lo frenó repair'}")

                    self._hacer_lugar(clave)               # §4.3 · el techo, antes de spawnear
                    # LA RESERVA VA A LA TABLA Y AL DISCO ANTES DE SOLTAR EL LOCK: es lo que
                    # hace que el de al lado vea «naciendo» en vez de «no hay nada».
                    reserva = self._reservar(clave, entity_id, user_id, h, comando, args, cwd)

            if pestillo is not None:
                # Esperar el nacimiento ajeno. El tope es el plazo del que spawnea más un
                # margen: si ni con eso terminó, algo peor pasó y colgarse para siempre
                # sería el peor de los finales.
                if not pestillo.wait(plazo + _MARGEN_NACIMIENTO_S):
                    raise DuenoError(
                        f"«{entity_id}» no terminó de arrancar en {plazo:g}s "
                        f"(lo estaba levantando otro pedido)")
                # EL FALLO SE PROPAGA, NO SE REINTENTA. Dos pedidos concurrentes contra un
                # binario roto no son dos oportunidades: son la misma causa dos veces, y
                # reintentar acá le cobra al segundo otro plazo completo para llegar al
                # mismo error. Si el nacimiento salió bien, el `continue` la comparte.
                with self._lock:
                    fallo = naciente.fallo_nacimiento
                if fallo:
                    raise DuenoError(fallo)
                continue

            # ── FUERA DEL LOCK: EL SPAWN Y LA ESPERA DE SALUD ──────────────────────
            # Esto es toda la obra. Acá adentro se van 5,89 s del pack más lento (medido) y
            # el lock del dueño ya no los cubre, así que otro workspace puede arrancar en
            # paralelo en vez de hacer fila.
            con = self._nacer(reserva, env, plazo, clase=spec.get("clase"))
            with self._lock:
                con.efimera = bool(efimero)
                con.refcount += 1
                con.prestada_a.append(motivo)
            self._arrancar_cosechador()
            return Prestamo(self, con, motivo)
        finally:
            self._entregar()

    # ── EL TECHO (§4.3) ─────────────────────────────────────────────────────────────
    def _hacer_lugar(self, clave_entrante: str) -> None:
        """Desaloja por LRU hasta que quepa una más. Se llama ANTES del spawn: sumar y
        después restar tendría al usuario en el pico de memoria justo cuando el techo
        existía para evitarlo.

        DOS EXCLUSIONES DURAS:
          · las PRESTADAS (refcount > 0) — nunca. Es la misma regla del §1.3: desalojar una
            conexión en uso interrumpe una llamada en curso y le devuelve al usuario un
            `-32000` que el diagnóstico va a leer como «el server se murió», que es mentira.
          · la que se está pidiendo — obvio, pero hay que escribirlo: con un tope de 1, el
            dueño no puede matarse a sí mismo.

        Y SI TODAS ESTÁN PRESTADAS, EL TOPE CEDE. Se levanta igual, con un evento de
        sobrecupo. La alternativa —hacer esperar al usuario a que otro agente suelte—
        convierte un techo de memoria en un deadlock de producto, que es peor que 113 MB.
        """
        if self._max_vivas <= 0:
            return
        while len(self._tabla) >= self._max_vivas:
            # [Obra 1 · punto 7, aprobado] LO QUE ESTÁ NACIENDO NO SE DESALOJA. Una reserva
            # tiene `refcount == 0` hasta que su `pedir` vuelve —el préstamo se suma al
            # final— así que sin esta cláusula sería la PRIMERA víctima del LRU: el proceso
            # de al lado desalojaría, a mitad del arranque, a alguien que todavía no llegó a
            # existir. Es corrección, no política: el número del techo y la regla del
            # sobrecupo quedan intactos; sólo deja de contarse como desalojable algo que
            # nadie pudo usar todavía.
            candidatas = [c for c in self._tabla.values()
                          if c.refcount == 0 and not c.naciendo
                          and c.clave != clave_entrante]
            if not candidatas:
                self._contadores["sobrecupo"] += 1
                print(f"[dueño] SOBRECUPO: {len(self._tabla)} vivas y todas prestadas; "
                      f"se levanta igual (tope {self._max_vivas}). El techo cede antes que "
                      f"hacer esperar a alguien.", file=sys.stderr, flush=True)
                return
            victima = min(candidatas, key=lambda c: c.ultimo_uso)
            self._cerrar(victima, motivo="desalojo por techo (LRU)")
            self._contadores["desalojos_lru"] += 1

    def _parece_muerta(self, con: _Conexion) -> bool:
        """Barato: ¿el árbol anotado sigue vivo? No habla MCP — eso lo dice la llamada."""
        if not con.pids:
            return False                                   # no se pudo anotar: no se acusa
        return not any(_vive(p) for p in con.pids)

    def _reservar(self, clave, entity_id, user_id, h, comando, args, cwd) -> _Conexion:
        """La entrada NACIENDO en la tabla y en el disco. **Se llama con el lock puesto.**

        ── EL ORDEN ES LA GARANTÍA (§3.2) ──────────────────────────────────────────
        La línea `naciendo` va al disco ANTES de que exista un proceso. Si el sidecar
        muere en esta ventana, el próximo arranque tiene `comando` + `nacido_en` y puede
        barrer aunque nunca hayamos sabido el pid. Esa garantía es la de siempre; lo que
        agrega esta obra es que la reserva ADEMÁS sirve de señal para los concurrentes.
        """
        con = _Conexion(clave, entity_id=entity_id, user_id=user_id, h=h,
                        comando=comando, args=args, cwd=cwd)
        con.naciendo = True
        con.listo = threading.Event()                      # cerrado: hay que esperarlo
        self._tabla[clave] = con
        self._volcar()
        return con

    def _nacer(self, con: _Conexion, env, rpc_timeout, *, clase=None) -> _Conexion:
        """Spawnea y espera la salud. **Se llama SIN el lock**, y ése es todo el punto.

        Cierra el pestillo pase lo que pase (el `finally`): un nacimiento que no despierta
        a los que esperan los deja colgados hasta el timeout, que es la fuga que esta
        estructura tiene que hacer imposible.
        """
        clave, entity_id = con.clave, con.entity_id
        comando, args, cwd = con.comando, con.args, con.cwd
        try:
            return self._nacer_de_veras(con, clave, entity_id, comando, args, env, cwd,
                                        rpc_timeout, clase=clase)
        except BaseException as e:
            with self._lock:
                con.naciendo = False
                con.fallo_nacimiento = str(e) or f"{type(e).__name__}"
            raise
        finally:
            con.naciendo = False
            con.listo.set()

    def _nacer_de_veras(self, con, clave, entity_id, comando, args, env, cwd,
                        rpc_timeout, *, clase=None) -> _Conexion:
        Servidor = self._cls({"clase": clase} if clase is not None else None)
        srv = Servidor(entity_id, comando, args, env=env, rpc_timeout=rpc_timeout, cwd=cwd)

        # ── QUIÉN ES HIJO DE QUIÉN, CON DOS SPAWNS A LA VEZ ─────────────────────────
        # El descubrimiento de pids por DIFF de `_hijos_directos()` (antes/después) es
        # correcto sólo si nadie más spawnea en el medio: con dos arranques en paralelo, el
        # diff de A se lleva puestos los hijos de B. Y los pids no son un adorno — de ahí
        # salen `_parece_muerta`, el barrido de arranque y la lápida.
        #
        # Un servidor que EXPONE su pid no necesita el diff: se le pregunta y se cuelga de
        # ahí el árbol. Es el caso del pack (`ServidorDePack.pid`), que es justamente el que
        # esta obra deja correr en paralelo. El transporte MCP no lo expone (medido, sesión
        # 1 del SDK), así que conserva el diff — y para conservarlo con el lock suelto, los
        # spawns por diff se serializan ENTRE ELLOS con su propio lock. Un MCP no espera a
        # un pack ni un pack a un MCP; sólo diff con diff.
        sabe_su_pid = hasattr(srv, "pid")
        # ── R1 · EL AVISO PUSH, ANTES DE `start()` ──────────────────────────────────
        # Es LO QUE HOY NO PASA: sin esto, una conexión que muere mientras nadie pide no la
        # ve nadie —`_parece_muerta` sólo se consulta dentro de `pedir()`— y el fantasma
        # del §6, que es exactamente una muerte con nadie mirando, queda fuera de toda
        # traza. El transporte ya sabía el instante (EOF del pipe de stderr) y lo tiraba.
        #
        # Antes de `start()` porque el `_CapturaStderr` que ve el EOF se construye ahí
        # dentro. Y con `hasattr` y no con un `isinstance`: el cliente viejo no lo tiene y
        # eso NO es un error — degrada a la red de seguridad del cosechador (`_vigilar`).
        if hasattr(srv, "al_morir"):
            srv.al_morir(lambda t_eof, _c=clave: self._muerte_push(_c, t_eof))

        if sabe_su_pid:
            arrancado = self._arrancar(srv, con, entity_id)
            # Se anotan aunque el arranque haya fallado — un proceso que quedó a medias
            # también hay que poder barrerlo.
            pid = getattr(srv, "pid", None)
            con.pids = sorted(_descendientes({int(pid)})) if pid else []
        else:
            # ── EL DIFF, SIN EL HANDSHAKE ADENTRO (paso 6 · el cinturón) ───────────
            # El lock global existe porque dos diffs simultáneos se roban los hijos. Lo que
            # NO hacía falta era sostenerlo durante el `initialize`, que es lo caro: el
            # diff se cierra en cuanto el proceso existe.
            #
            # MEDIDO desde la pantalla, primer turno de la Sala con el cinturón frío:
            #   con el lock sobre `start()` entero → los 8 lanzadores nacen de +4,38 s a
            #     +38,39 s (34,0 s de spread) y el primer modelo arranca a los +39,56 s
            #   con el dueño APAGADO (control)     → spread 1,19 s, primer modelo +5,25 s
            # O sea: el `ThreadPoolExecutor(8)` del restaurador estaba, y este lock lo
            # anulaba. El dueño le cobraba al primer turno 34 s para ahorrarle 21,7 s al
            # segundo.
            #
            # `al_spawnear` es la costura del transporte: dispara con el hijo YA nacido y
            # el handshake sin empezar. Si el servidor no la tiene —el cliente viejo no—,
            # el `finally` cierra el diff como siempre: degrada al comportamiento de antes,
            # no a uno sin diff.
            _diff = {"antes": None, "pids": None, "tomado": False}

            def _cerrar_diff() -> None:
                if _diff["pids"] is not None:
                    return
                _diff["pids"] = sorted(_descendientes(_hijos_directos() - _diff["antes"]))
                if _diff["tomado"]:
                    _diff["tomado"] = False
                    _LOCK_DIFF_PIDS.release()

            if hasattr(srv, "al_spawnear"):
                srv.al_spawnear(_cerrar_diff)
            _LOCK_DIFF_PIDS.acquire()
            _diff["tomado"] = True
            try:
                _diff["antes"] = _hijos_directos()
                arrancado = self._arrancar(srv, con, entity_id)
            finally:
                # Si el aviso no llegó (servidor sin la costura, o un fallo antes del
                # spawn), el diff se cierra acá y el lock se suelta igual.
                _cerrar_diff()
            con.pids = _diff["pids"] or []
        return self._cerrar_el_nacimiento(con, srv, entity_id, arrancado, clase=clase)

    def _arrancar(self, srv, con, entity_id) -> bool:
        try:
            return bool(srv.start())
        except Exception as e:                             # noqa: BLE001 — frontera
            with self._lock:
                self._tabla.pop(con.clave, None)
                self._volcar()
            raise DuenoError(
                f"no pude levantar «{entity_id}»: {type(e).__name__}: {e}") from e

    def _cerrar_el_nacimiento(self, con, srv, entity_id, arrancado, *, clase=None):
        Servidor = self._cls({"clase": clase} if clase is not None else None)
        with self._lock:
            # ALGUIEN PUDO CERRAR LA RESERVA MIENTRAS NACÍA — `apagar_todo()` del lifespan o
            # una lápida. Con el lock suelto eso ya es posible, y adoptar el proceso acá lo
            # dejaría corriendo fuera de la tabla: un huérfano que ni el barrido ve. Si la
            # reserva ya no está, el proceso recién nacido se mata en el acto.
            if self._tabla.get(con.clave) is not con:
                try:
                    srv.stop()
                except Exception:                          # noqa: BLE001 — cerrar no falla
                    pass
                raise DuenoError(
                    f"«{entity_id}» se cerró mientras arrancaba; no se adopta el proceso")
            con.servidor = srv
            self._contadores["spawns"] += 1
            self._volcar()
        if not arrancado:
            diag = {}
            try:
                diag = srv.diagnostico() or {}
            except Exception:                              # noqa: BLE001
                pass
            with self._lock:
                self._cerrar(con, motivo="no arrancó")
            # [Gate 4 · F4 · O1] El texto nombra lo que ESTA clase no logró, no un protocolo
            # que quizá no habla. Un pack no da un saludo MCP: da (o no da) su señal de salud,
            # y decirle «no completó el saludo MCP» a un binario que murió por un puerto
            # ocupado manda a leer el lugar equivocado. La clase declara su copy en
            # `FALLO_ARRANQUE`; sin él, se conserva el texto histórico intacto.
            que = getattr(Servidor, "FALLO_ARRANQUE", "no completó el saludo MCP")
            raise DuenoError(
                f"«{entity_id}» {que}: "
                f"{diag.get('detail') or diag.get('stderr') or 'sin detalle'}")
        return con

    # ── SOLTAR ──────────────────────────────────────────────────────────────────────
    def _soltar(self, con: _Conexion, motivo: str) -> None:
        with self._lock:
            con.refcount = max(0, con.refcount - 1)
            try:
                con.prestada_a.remove(motivo)
            except ValueError:
                pass
            con.ultimo_uso = time.time()
            # D1 corría con ociosidad 0 y cerraba acá mismo — el ciclo de vida quedaba
            # idéntico al de siempre. **D2 sostiene**: con `OCIOSIDAD_S > 0` la conexión
            # queda viva y el reloj empieza a correr desde este `ultimo_uso`. Quien la
            # cierra es el cosechador, no el que suelta.
            if con.refcount == 0 and (self._retencion_s <= 0 or con.efimera):
                self._cerrar(con, motivo="efímera soltada" if con.efimera
                             else "último préstamo soltado")
                if con.efimera:
                    self._contadores["efimeras_cerradas"] += 1
        self._entregar()                                   # R1

    # ── APAGAR ──────────────────────────────────────────────────────────────────────
    def apagar(self, clave: str, *, motivo: str = "") -> bool:
        """Mata una conexión por clave. **Éste es el camino de la lápida** (§1.1): manda
        siempre, por encima del refcount. Un usuario que desconecta una pieza no puede
        quedar esperando a que otro agente la suelte."""
        with self._lock:
            con = self._tabla.get(clave)
            if con is None:
                return False
            self._cerrar(con, motivo=motivo or "apagado explícito")
        self._entregar()                                   # R1
        return True

    def apagar_todo(self, *, motivo: str = "cierre") -> int:
        """Mata TODAS las conexiones. Lo llama el `finally` del lifespan (§1.4) — el momento
        en que `main.py` por fin sabe qué matar al cerrar.

        **EN PARALELO, y no es micro-optimización.** El cierre del SDK es stdin → 2 s →
        SIGTERM al grupo → 2 s → SIGKILL. Ocho conexiones en serie serían hasta 32 s de
        cierre, y un usuario que le da ⌘Q a una app que tarda medio minuto en irse la mata
        a la fuerza — dejando exactamente los huérfanos que esto viene a evitar. Se copia el
        `ThreadPoolExecutor` que `restaurador.py:360-370` ya usa para levantar en paralelo.
        """
        with self._lock:
            self._parar.set()                              # el cosechador deja de dar vueltas
            cons = list(self._tabla.values())
            for con in cons:                               # se sacan de la tabla YA: nadie
                con.muerta = True                          # puede pedirlas a mitad del cierre
                # R1 · este camino NO pasa por `_cerrar` (mata en paralelo más abajo), así
                # que el evento se arma acá o el cierre del sidecar sería el único que no
                # deja rastro — justo el que más importa para saber qué había vivo al final.
                if self._suscriptores and not con.aviso_emitido:
                    con.aviso_emitido = True
                    self._encolar(self._evento_muerte(
                        con, disparador="CIERRE", motivo=motivo))
                self._tabla.pop(con.clave, None)
            self._volcar()
        self._entregar()                                   # R1 · fuera del lock
        if not cons:
            return 0
        import concurrent.futures

        def _matar(con: _Conexion) -> None:
            srv, con.servidor = con.servidor, None
            if srv is not None:
                try:
                    srv.stop()
                except Exception:                          # noqa: BLE001 — cerrar no falla
                    pass

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(8, len(cons)), thread_name_prefix="dueno-apagar") as ex:
            list(ex.map(_matar, cons))
        print(f"[dueño] apagadas {len(cons)} conexión(es) MCP · motivo: {motivo}",
              flush=True)
        return len(cons)

    def apagar_entidad(self, entity_id: str, *, user_id: Optional[str] = None,
                       motivo: str = "") -> int:
        """Todas las conexiones de una entidad (todas sus huellas). Lo que necesita la
        lápida, que apaga una ENTIDAD, no una huella."""
        with self._lock:
            claves = [k for k, c in self._tabla.items()
                      if c.entity_id == entity_id and (user_id is None or c.user_id == user_id)]
            for k in claves:
                self._cerrar(self._tabla[k], motivo=motivo or "lápida")
        self._entregar()                                   # R1
        return len(claves)

    def _cerrar(self, con: _Conexion, *, motivo: str, disparador: str = "",
                t_eof: Optional[float] = None) -> None:
        # R1 · EL EVENTO SE ARMA ACÁ Y NO DESPUÉS. Es el único punto donde coexisten la
        # clave, el motivo y el `srv` con su diagnóstico; tres líneas más abajo la fila ya
        # no está en la tabla y el `srv` ya es None. Se ARMA con el lock y se ENTREGA fuera.
        if self._suscriptores and not con.aviso_emitido:
            con.aviso_emitido = True
            self._encolar(self._evento_muerte(
                con, disparador=disparador or _disparador_de(motivo), motivo=motivo,
                t_eof=t_eof))
        con.muerta = True
        srv = con.servidor
        con.servidor = None
        self._tabla.pop(con.clave, None)
        self._volcar()
        if srv is not None:
            try:
                srv.stop()
            except Exception:                              # noqa: BLE001 — cerrar no falla
                pass

    # ── ESTADO ──────────────────────────────────────────────────────────────────────
    def estado(self) -> dict:
        with self._lock:
            vivas = []
            for con in self._tabla.values():
                vivas.append({
                    "clave": con.clave, "entity_id": con.entity_id, "user_id": con.user_id,
                    "huella": con.huella, "pids": list(con.pids),
                    "nacida_en": con.nacida_en, "ultimo_uso": con.ultimo_uso,
                    "refcount": con.refcount, "prestada_a": list(con.prestada_a),
                    "efimera": con.efimera,
                    "viva": con.servidor is not None,
                    "rss_kb": _rss_kb(con.pids),
                })
            return {"vivas": sorted(vivas, key=lambda v: v["clave"]),
                    "tope": self._max_vivas,
                    "ociosidad_s": self._retencion_s,
                    "retencion_s": self._retencion_s,          # alias histórico (D1)
                    "sostiene": self._retencion_s > 0,
                    "cosechador_vivo": bool(self._cosechador and self._cosechador.is_alive()),
                    "eventos": dict(self._contadores)}

    # ── EL LIBRO ────────────────────────────────────────────────────────────────────
    def _volcar(self) -> None:
        filas = [c.fila("vivo" if c.servidor is not None else "naciendo")
                 for c in self._tabla.values()]
        self._libro.escribir(filas)

    # ── BARRIDO DE ARRANQUE (§3.3) ──────────────────────────────────────────────────
    def barrer_al_arrancar(self) -> dict:
        """Mata lo que dejó un sidecar anterior. **NO readopta** — y es una decisión, no una
        omisión: los pipes stdin/stdout murieron con el padre, así que a un MCP stdio
        heredado no se le puede volver a hablar. Readoptar de verdad exige otro transporte
        (§3.3 del diseño). Lo que sí se gana: hoy esos procesos sobreviven al reinicio y
        sólo los caza, si acaso, el barrido de `_MEI` — que mira directorios, no procesos.

        La verificación de identidad es la del barrido de `_MEI`
        (`sidecar_serve.py:237-256`): un pid que no coincide en comando y hora **no se
        toca**. Un pid reciclado es el pid de otro, y matarlo sería matar a un tercero.
        """
        parte = {"anotadas": 0, "muertas_ya": 0, "recicladas": 0, "matadas": 0,
                 "sin_pid": 0}
        #: SÓLO los que NOSOTROS señalamos. La escalada a SIGKILL se hace sobre esta lista
        #: y nunca sobre las filas — la primera versión recorría `filas` entera y le mandaba
        #: un -9 a los pids que acababa de descartar por reciclados. Matar a un tercero es
        #: el peor fallo posible de este barrido, y lo cazó la vara.
        señalados: list = []
        filas = self._libro.leer()
        parte["anotadas"] = len(filas)
        for fila in filas:
            pids = [p for p in (fila.get("pids") or []) if isinstance(p, int)]
            nacido = fila.get("nacido_en")
            if not pids:
                # Entrada `naciendo`: nunca supimos el pid. No se puede matar por comando
                # sin arriesgar a un tercero, así que se REPORTA y no se inventa.
                parte["sin_pid"] += 1
                print(f"[dueño] entrada sin pid: «{fila.get('entity_id')}» "
                      f"(comando {fila.get('comando')!r}). Si dejó un proceso, no lo barro: "
                      f"matar por nombre podría matar a un tercero.",
                      file=sys.stderr, flush=True)
                continue
            for pid in pids:
                if not _vive(pid):
                    parte["muertas_ya"] += 1
                    continue
                comando, arranque = _comando_y_arranque(pid)
                mismo_comando = _mismo_comando(str(fila.get("comando") or ""),
                                               fila.get("args") or [], comando)
                # VENTANA, no umbral: un pid reciclado arrancó DESPUÉS. Si no se pudo leer
                # la hora, el chequeo fuerte no está disponible y no se mata — «no sé» es
                # una respuesta, y del lado seguro (misma regla que `_mei_vivos`).
                a_tiempo = (arranque is not None and nacido is not None
                            and abs(arranque - float(nacido)) <= _TOLERANCIA_S)
                if not (mismo_comando and a_tiempo):
                    parte["recicladas"] += 1               # es de otro: no se toca
                    continue
                try:
                    os.kill(pid, 15)
                    señalados.append(pid)
                    parte["matadas"] += 1
                except Exception:                          # noqa: BLE001
                    pass
        if señalados:
            time.sleep(1.0)
            for pid in señalados:                          # SÓLO los señalados, jamás `filas`
                if _vive(pid):
                    try:
                        os.kill(pid, 9)
                    except Exception:                      # noqa: BLE001
                        pass
        self._libro.escribir([])
        self._contadores["barridas_al_arrancar"] = parte["matadas"]
        return parte


# ── 5 · EL SINGLETON ────────────────────────────────────────────────────────────────
_dueno: Optional[Dueno] = None
_dueno_lock = threading.Lock()


def actual() -> Dueno:
    """El dueño de este proceso. Uno solo: dos tablas de vivos son dos verdades sobre los
    mismos procesos, que es el fallo que este árbol viene cerrando en todos lados."""
    global _dueno
    with _dueno_lock:
        if _dueno is None:
            _dueno = Dueno()
        return _dueno


def _reset_para_tests() -> None:
    """Sólo para varas: suelta el singleton. No lo llama el producto."""
    global _dueno
    with _dueno_lock:
        if _dueno is not None:
            for clave in list(_dueno._tabla):
                _dueno.apagar(clave, motivo="reset de vara")
        _dueno = None


# ── UN SOLO MÓDULO, SE LO IMPORTE COMO SE LO IMPORTE ────────────────────────────────
# El árbol tiene los dos estilos vivos: `main.py` hace `from inspection import dueno` y
# `conexiones_verificador` hace `import dueno` (con `platform/inspection` en `sys.path`).
# Python los trata como DOS módulos distintos, cada uno con su `_dueno` — o sea DOS tablas
# de vivos, DOS cosechadores y DOS escritores del mismo `procesos.jsonl`.
#
# NO ES TEÓRICO: la vara del lifespan lo cazó. `apagar_todo()` corría sobre la tabla del
# módulo de `main.py` y dejaba viva la conexión de la tabla del otro. Un supervisor de
# procesos duplicado es peor que ninguno: cada mitad cree que barrió todo.
#
# Se registra el mismo objeto bajo los dos nombres. El primero que se importe gana y el
# segundo lo encuentra hecho; `setdefault` hace que el orden no importe. Es el mismo
# patrón que `motor_verdad._models()` documenta para `models`.
for _alias in ("dueno", "inspection.dueno"):
    sys.modules.setdefault(_alias, sys.modules[__name__])
try:                                                       # que `from inspection import dueno`
    _paquete = sys.modules.get("inspection")               # también lo vea como atributo
    if _paquete is not None and not hasattr(_paquete, "dueno"):
        setattr(_paquete, "dueno", sys.modules[__name__])
except Exception:                                          # noqa: BLE001
    pass


__all__ = ["Dueno", "Prestamo", "DuenoError", "actual", "encendido", "huella", "clave_de",
           "OCIOSIDAD_S", "MAX_VIVAS", "RETENCION_S"]
