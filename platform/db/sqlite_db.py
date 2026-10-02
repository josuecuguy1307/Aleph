"""sqlite_db.py — conexión SQLite con cara de psycopg2. [Casa 2 · Fase 2 · paso 2.2]

El backend abre conexiones en ~20 archivos y las usa siempre igual: `conn.cursor()`,
`cur.execute(sql, params)`, `cur.fetchone()`, `conn.commit()`. Este módulo devuelve un
objeto que responde a eso mismo pero habla SQLite, traduciendo el SQL al vuelo con
`dialect.traducir`. Así el paso 2.4 (reescribir ~200 statements a mano) se reduce a los
pocos que la traducción mecánica no cubre.

    conn = conectar("/ruta/aleph.db")
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s::uuid", (uid,))
        fila = cur.fetchone()
    conn.commit()

⚠️ `PRAGMA foreign_keys = ON` VA EN CADA CONEXIÓN, Y ES EL MOTIVO DE ESTE ARCHIVO.
En SQLite los foreign keys vienen **apagados por default**, y el pragma es propiedad de
la CONEXIÓN, no del archivo. La asimetría, medida:

    conexión que corrió el schema   foreign_keys=1   journal_mode=wal
    conexión NUEVA al mismo .db     foreign_keys=0   journal_mode=wal   ← el punto

O sea: `executescript()` sí deja el pragma puesto en la conexión que lo ejecutó, pero el
schema se crea UNA vez y el backend abre miles de conexiones después — todas arrancarían
en 0. Tenerlo escrito en `schema_sqlite.sql` no alcanza; WAL sí viaja en el archivo,
`foreign_keys` no.

Sin él, los `ON DELETE CASCADE` del schema son decoración: el `DELETE FROM users` del
borrado de cuenta deja `puppets`, `keys`, `chats`, `instructions` y `account_memories`
huérfanos, en silencio y con la cuenta reportada como borrada. Es el mismo fallo callado
del paso 2.1 (`BIGSERIAL` → `NULL`) corrido un nivel más arriba, y por eso se aplica acá
y no se delega al caller: un caller que se olvida no falla, corrompe.

Diferencias con psycopg2 que el wrapper SÍ cubre:
  - **`with conn.cursor() as cur`**: `sqlite3.Cursor` NO implementa el protocolo de
    context manager (`TypeError` al entrar). El código lo usa así en 30 lugares, así que
    el wrapper agrega `__enter__`/`__exit__`.
  - **filas por nombre**: `sqlite3.Row` responde a `fila["col"]` **y** a `fila[0]`, con lo
    que cubre a la vez los 214 `cursor()` que esperan tuplas y los 10
    `cursor(cursor_factory=RealDictCursor)` que esperan dicts.
  - **`cursor_factory=`**: se acepta y se ignora (ya se devuelven filas por nombre).

  - **columnas JSON decodificadas** (2.4): psycopg2 devuelve `JSONB` ya convertido a
    objeto Python; SQLite las guarda como TEXT y las devolvería como `str`. Sin esto el
    árbol se rompe UN MÓDULO MÁS ALLÁ de la causa: `repo.create_puppet` "funciona" y
    después `p["config"]["meta"]` explota con `TypeError: string indices must be
    integers` (medido — es el mismo fallo del `payload` de la cola en 2.3, y por eso se
    resuelve en un solo lugar en vez de en ~100 `execute()`). Decodificar acá no es
    magia: es lo que psycopg2 ya hace, o sea PARIDAD con el driver que el shim imita.

    ⚠️ `result` NO se decodifica acá, y la excepción está medida: es `JSONB` en
    `job_queue` pero **TEXT libre en `held_actions`** ("motivo del rechazo",
    schema.sql:153). Decodificar por nombre convertiría un rechazo que diga `42` en el
    entero 42, callado. `job_queue.result` lo decodifica `jobs.py`, que sí sabe de qué
    tabla viene. De los 16 nombres JSONB del schema es el ÚNICO que colisiona.

Diferencia que NO cubre, medida y sin consecuencia hoy: `rowcount` tras un `SELECT` da
`-1` en SQLite y el número de filas en psycopg2. En el árbol `rowcount` se lee sólo
después de `DELETE`/`UPDATE` (35 usos, 0 tras `SELECT`), donde ambos coinciden — que es
lo que sostiene las guardas de rowcount de la auditoría H2.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional, Sequence

_AQUI = Path(__file__).resolve().parent


def _ruta_schema() -> Path:
    """`schema_sqlite.sql`, frozen-aware. Bajo PyInstaller este módulo sale del PYZ y
    su `__file__` apunta a `_MEIPASS/sqlite_db.py` — SIN el .sql al lado (el .sql viaja
    como data en `platform/db/`). Medido en el sidecar onefile: `_AQUI/"schema_sqlite.sql"`
    daba FileNotFoundError y el boot del cliente caía a 503 visible. `resource_root()`
    resuelve los dos mundos (dev = raíz del árbol, frozen = _MEIPASS); se prefiere el
    vecino local, que en dev es byte-idéntico a lo histórico."""
    local = _AQUI / "schema_sqlite.sql"
    if local.exists():
        return local
    return _aleph_paths().resource_root() / "platform" / "db" / "schema_sqlite.sql"

#: Columnas `JSONB` del schema Postgres, que en SQLite viven como TEXT. Se decodifican al
#: leer para dar la misma forma que psycopg2 (ver cabecera). Sale de las declaraciones
#: `JSONB` de `schema.sql` + `migrations/*.sql`: son 16 nombres, y `result` queda AFUERA
#: a propósito porque es el único que colisiona (JSONB en `job_queue`, TEXT libre en
#: `held_actions`). Si el schema suma una columna JSONB, va acá.
_COLS_JSON = frozenset({
    "agent_path", "args", "belt", "config", "control", "costo", "detail", "embedding",
    "meta", "payload", "recipe", "senal", "spec", "state", "trayectoria",
    # `conexiones` (21, solo cliente): sus JSON se decodifican acá como los demás. Sin
    # esto, `args` salía decodificado (ya estaba en el set por `held_actions`) y los otros
    # crudos — la misma tabla con dos comportamientos. Verificado: ninguno de estos
    # nombres colisiona con otra tabla del schema.
    "env_template", "env_publico", "scopes", "server_info", "tools_snapshot",
    "headers_template", "headers_publico",   # v4 · receta HTTP
    "conexion", "credencial",                # v5 · las dos mediciones
    "reserva",                                # v7 · aviso medido al traer una pieza
})


class _Fila:
    """Fila que responde por NOMBRE y por ÍNDICE, como `sqlite3.Row` — pero con las
    columnas JSON ya decodificadas.

    Hace falta una clase propia porque `sqlite3.Row` es inmutable: no se le pueden
    reemplazar los valores. Y un `dict` pelado no sirve, porque el árbol usa las dos
    formas — 214 cursores leen por índice (`fila[0]`) y 10 por nombre (`fila["col"]`).
    Implementa `keys()` + `__getitem__` (protocolo de mapping, para que `dict(fila)`
    funcione) y `__iter__` sobre los VALORES (para `tuple(fila)` y el desempaque
    `a, b = fila`), que es exactamente el contrato de `sqlite3.Row`.
    """

    __slots__ = ("_v", "_idx")

    def __init__(self, valores: tuple, idx: dict):
        self._v = valores
        self._idx = idx

    def __getitem__(self, k):
        if isinstance(k, str):
            return self._v[self._idx[k]]
        return self._v[k]           # int y slice

    def keys(self):
        return list(self._idx)

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return len(self._v)

    def __contains__(self, k):
        return k in self._idx if isinstance(k, str) else k in self._v

    def get(self, k, default=None):
        return self._v[self._idx[k]] if k in self._idx else default

    def __eq__(self, otro):
        # Para que `fila == (a, b)` siga andando donde el árbol compara contra tuplas.
        if isinstance(otro, _Fila):
            return self._v == otro._v
        return self._v == otro if isinstance(otro, tuple) else NotImplemented

    def __repr__(self):
        return f"_Fila({dict(zip(self._idx, self._v))!r})"


def _decodificar_fila(fila, idx: dict, cols_json: tuple):
    """`sqlite3.Row` → `_Fila` con las columnas JSON convertidas a objeto Python."""
    if fila is None:
        return None
    vals = list(fila)
    for nombre, i in cols_json:
        v = vals[i]
        if isinstance(v, str):
            try:
                vals[i] = json.loads(v)
            except ValueError as exc:
                # La columna es JSONB del lado PG y sólo la escribe `json.dumps`: si no
                # parsea, la fila está corrupta. Ruidoso y con la columna señalada — un
                # str colado acá reaparece como TypeError a dos módulos de distancia.
                raise ValueError(
                    f"columna JSON '{nombre}' no contiene JSON válido: {exc}") from exc
    return _Fila(tuple(vals), idx)

try:
    from dialect import DialectoNoSoportado, traducir      # cargado por ruta (patrón del repo)
except ImportError:                                         # pragma: no cover
    import sys
    sys.path.insert(0, str(_AQUI))
    from dialect import DialectoNoSoportado, traducir

__all__ = ["conectar", "ruta_db", "crear_schema", "asegurar_schema",
           "SchemaClienteIncompleto", "VERSION_SCHEMA_CLIENTE", "DialectoNoSoportado",
           "DBNoDisponible", "estado_db", "cerrar_almacen", "lock_vfs"]


def _aleph_paths():
    """`platform/aleph_paths.py` (B3), sin asumir el sys.path — mismo patrón que
    `dialect` arriba. Si no aparece ni con platform/ insertado es un bug de
    empaquetado: se propaga el ImportError (FALLO VISIBLE, JAMÁS MUDO)."""
    try:
        import aleph_paths
    except ImportError:
        import sys
        plat = str(_AQUI.parent)
        if plat not in sys.path:
            sys.path.insert(0, plat)
        import aleph_paths
    return aleph_paths


def ruta_db() -> str:
    """Dónde vive el .db del usuario.

    `PUPPET_SQLITE_PATH` manda (override explícito: ruta de ARCHIVO, tests/ops).
    Si no está, `aleph_paths.user_data_dir()/aleph.db` — la MISMA resolución que
    enc.key/vault/espacios (B3): `ALEPH_DATA_DIR` > `XDG_DATA_HOME` > el dir estándar
    del OS, siempre FUERA del árbol de código (bajo PyInstaller es read-only y se
    reemplaza al actualizar). Antes había DOS resoluciones divergentes: con
    `ALEPH_DATA_DIR` apuntando a un datadir aislado, la enc.key aterrizaba ahí y el
    .db se iba igual a `~/Library` (medido, GAP-DEV-DESKTOP §2.2). Una resolución,
    un lugar.
    """
    env = (os.environ.get("PUPPET_SQLITE_PATH") or "").strip()
    if env:
        return env
    return str(_aleph_paths().user_data_dir() / "aleph.db")


class _Cursor:
    """Cursor con cara de psycopg2: traduce el SQL y soporta `with ... as`."""

    def __init__(self, cur: sqlite3.Cursor):
        self._cur = cur
        self._idx: dict = {}
        self._json: tuple = ()

    def _mapa(self) -> None:
        """Recalcula nombre→índice y qué columnas hay que decodificar. Se hace UNA vez
        por `execute()` —no por fila— porque `description` no cambia dentro del cursor."""
        d = self._cur.description
        if not d:
            self._idx, self._json = {}, ()
            return
        nombres = [c[0] for c in d]
        self._idx = {n: i for i, n in enumerate(nombres)}
        self._json = tuple((n, i) for i, n in enumerate(nombres) if n in _COLS_JSON)

    # `with conn.cursor() as cur:` — sqlite3.Cursor no lo soporta; el árbol lo usa así.
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._cur.close()
        return False

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None):
        sql, params = traducir(sql, params)
        self._cur.execute(sql, params)
        self._mapa()
        return self

    def executemany(self, sql: str, seq):
        seq = list(seq)
        if not seq:
            return self
        # Se traduce con la primera fila (la forma del SQL no depende de los valores) y se
        # verifica que ninguna otra cambie la cantidad de marcadores — si `ANY()` expande
        # distinto por fila, executemany no sirve y hay que decirlo, no adivinar.
        sql_t, primeros = traducir(sql, seq[0])
        for fila in seq[1:]:
            _, otros = traducir(sql, fila)
            if len(otros) != len(primeros):
                raise DialectoNoSoportado(
                    "executemany con parámetros de largo variable (¿ANY() adentro?): "
                    "usar execute() en un loop")
        self._cur.executemany(sql_t, [traducir(sql, f)[1] for f in seq])
        return self

    # Los cuatro caminos de lectura pasan por el mismo decodificador: si uno se saltara,
    # la forma de la fila dependería de CÓMO se leyó, que es peor que no decodificar.
    def fetchone(self):
        return _decodificar_fila(self._cur.fetchone(), self._idx, self._json)

    def fetchall(self):
        return [_decodificar_fila(f, self._idx, self._json) for f in self._cur.fetchall()]

    def fetchmany(self, size=None):
        filas = self._cur.fetchmany(size if size is not None else self._cur.arraysize)
        return [_decodificar_fila(f, self._idx, self._json) for f in filas]

    def close(self):
        self._cur.close()

    def __iter__(self):
        for f in self._cur:
            yield _decodificar_fila(f, self._idx, self._json)

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def description(self):
        return self._cur.description

    @property
    def arraysize(self):
        return self._cur.arraysize


class _Conexion:
    """Conexión con cara de psycopg2 sobre `sqlite3.Connection`.

    `close()` DEVUELVE la conexión al almacén (rollback + checkin), no la cierra:
    el `close()` real de SQLite es una de las dos mitades del deadlock del VFS
    (ver §EL DEADLOCK DEL VFS). El wrapper se marca cerrado y se desprende, así
    un uso-después-de-close falla igual que hoy en vez de escribir por una
    conexión que ya es de otro request.
    """

    def __init__(self, sq: sqlite3.Connection, ruta: Optional[str] = None):
        self._c = sq
        self._ruta = ruta

    @property
    def _vivo(self) -> sqlite3.Connection:
        if self._c is None:
            raise sqlite3.ProgrammingError(
                "Cannot operate on a closed database.")   # mismo error que sqlite3
        return self._c

    def cursor(self, *a, **kw):
        # `cursor_factory=RealDictCursor` se acepta y se ignora: `sqlite3.Row` ya responde
        # por nombre y por índice, así que cubre las dos formas de uso del árbol.
        return _Cursor(self._vivo.cursor())

    def commit(self):
        self._vivo.commit()

    def rollback(self):
        self._vivo.rollback()

    def close(self):
        """Devuelve la conexión al almacén. Idempotente (cerrar dos veces no rompe)."""
        c, self._c = self._c, None
        if c is not None:
            _devolver(self._ruta, c)

    def __del__(self):
        """RED para el caller que se olvidó de cerrar (o murió antes de su `finally`).

        Sin esto, una conexión soltada la cierra el GC: un `sqlite3.close()` REAL, en el
        hilo que casualmente corra la recolección y FUERA de `_LOCK_VFS` — o sea, justo la
        mitad del deadlock que este módulo existe para evitar, reintroducida por la puerta
        de atrás. Acá se devuelve al almacén como cualquier `close()`."""
        try:
            self.close()
        except Exception:  # noqa: BLE001 — en el apagado del intérprete no hay nada que salvar
            pass

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *exc):
        # Mismo contrato que psycopg2 y que `with sqlite3.connect(...)`: commit si salió
        # bien, rollback si no. NO cierra la conexión.
        if exc_type is None:
            self._vivo.commit()
        else:
            self._vivo.rollback()
        return False

    @property
    def closed(self):
        if self._c is None:
            return 1
        try:
            self._c.execute("SELECT 1")
            return 0
        except sqlite3.ProgrammingError:
            return 1

    @property
    def autocommit(self):
        return self._vivo.isolation_level is None

    @autocommit.setter
    def autocommit(self, valor: bool):
        self._vivo.isolation_level = None if valor else ""

    @property
    def raw(self) -> sqlite3.Connection:
        """La conexión sqlite3 cruda (para pragmas o `executescript`)."""
        return self._vivo


# ══ EL DEADLOCK DEL VFS — por qué las conexiones se REUSAN ═══════════════════════
#
# El patrón "conexión fresca por operación + close()" (pool.py:_conn_cliente, y los ~30
# `conn = _conn(); try: … finally: conn.close()` de los routers) TRABA EL PROCESO ENTERO,
# para siempre. No es contención de SQLite: es el mutex de la tabla de inodos del VFS unix
# de SQLite, global al proceso, disputado entre el `open()` de un hilo y el `close()` de
# otro. Stacks medidos sobre el sidecar trabado (`sample`, 10 de 15 hilos):
#
#     hilo que ABRE    sqlite3.connect → openDatabase → unixOpen → findReusableFd
#                      → _pthread_mutex_firstfit_lock_wait → __psynch_mutexwait   (×9)
#     hilo que CIERRA  conn.close → sqlite3Close → sqlite3LeaveMutexAndCloseZombie
#                      → sqlite3BtreeClose → sqlite3PagerClose → sqlite3WalClose
#                      → unixLock → __psynch_mutexwait                            (×1)
#
# ⚠️ NINGÚN pragma lo explica ni lo cura: NO es el write-lock del archivo, NO es WAL, NO lo
# cubre `busy_timeout` (por eso el síntoma es "no contesta NUNCA", sin el `database is
# locked` que daría una espera de lock a los 30 s). Y como el bloqueo es un mutex de
# pthread dentro de C, ningún timeout de Python rescata al hilo que ya entró: queda
# perdido hasta que muere el proceso.
#
# Medido con un repro mínimo (5 hilos, sin FastAPI ni app: connect/consulta/close en loop):
#     churn (lo de antes)      🔴 TRABADO a los ~2 s, 314 ciclos
#     churn SÓLO LECTURAS      🔴 TRABADO, 96 ciclos      ← las lecturas mueren igual
#     open/close serializado   ✅ 90 754 ciclos en 30 s
#     conexión reusada         ✅ 89 221 ciclos en 30 s
#
# Corolario que corrige el diagnóstico previo (Casa 2 · 2.3, cerrado como "artefacto del
# test: prod tiene 100× de margen"): el margen nunca fue de ritmo. Es una CARRERA — a menos
# conn/s baja la probabilidad por segundo, no desaparece. Y la propia nota preveía la
# condición que la disparó: "se vuelve urgente … si aparece otro pool de hilos contra el
# mismo .db". Hoy hay tres (workers+reaper, el threadpool de FastAPI, la purga).
#
# EL ARREGLO, en dos capas:
#   1. RAÍZ — se mata el churn: las conexiones se REUSAN (almacén global de checkout/
#      checkin). `close()` = rollback + devolver. En régimen no hay ni un `open()` ni un
#      `close()` real, así que las dos mitades del deadlock ya no existen.
#   2. RED — lo poco que queda (la primera apertura de cada ruta, `:memory:`, el
#      desborde del tope) va SERIALIZADO por `_LOCK_VFS`: abrir y cerrar no se pisan
#      jamás. Y el lock se toma CON PLAZO: si alguien quedara trabado adentro, el resto
#      recibe `DBNoDisponible` (error TIPADO, visible) en vez de colgarse también.
#
# El almacén es global y NO thread-local a propósito: los hilos del threadpool de anyio
# mueren por idle (~10 s) y al morir se llevarían sus conexiones a un `close()` por GC —
# fuera del lock, o sea justo el evento que hay que evitar. `check_same_thread=False` ya
# permitía usarlas desde cualquier hilo, y una conexión sólo está prestada a UN caller a
# la vez (se saca del almacén), así que no hay uso simultáneo.

class DBNoDisponible(RuntimeError):
    """El camino de datos no está disponible AHORA (apertura trabada / plazo vencido).

    Es un error TIPADO a propósito: la ley es FALLO VISIBLE, JAMÁS MUDO. Antes esto era
    un cuelgue infinito y el humano veía la app "muda"; ahora el caller recibe una causa
    que puede mostrar, y `/health` lo reporta (estado degradado con motivo)."""


#: Serializa TODA apertura/cierre REAL de SQLite en el proceso (capa 2 del arreglo).
_LOCK_VFS = threading.RLock()

#: Almacén de conexiones libres por ruta: {ruta: [sqlite3.Connection, …]}.
_LIBRES: dict = {}
_LOCK_ALMACEN = threading.Lock()

#: Tope de conexiones ociosas guardadas por ruta. Al desbordar se cierra de verdad (bajo
#: `_LOCK_VFS`). 64 sobra: el pico real es el threadpool de anyio (40) + workers (5).
_TOPE_LIBRES = int(os.environ.get("PUPPET_SQLITE_POOL_MAX", "64") or "64")

#: Plazo para entrar al lock de apertura/cierre. Vencido ⇒ `DBNoDisponible`.
_PLAZO_VFS = float(os.environ.get("PUPPET_SQLITE_OPEN_TIMEOUT_S", "10") or "10")

#: Operación real en vuelo: (qué, hilo, t0_monotónico). Lo lee el watchdog de `/health`.
_EN_VUELO: Optional[tuple] = None


def _con_lock_vfs(que: str):
    """Toma `_LOCK_VFS` con plazo y deja marcada la operación en vuelo (para el watchdog).

    Si el plazo vence, alguien está trabado adentro del VFS: se levanta `DBNoDisponible`
    en vez de esperar para siempre. El hilo trabado no se puede rescatar (mutex de C),
    pero el resto del proceso deja de acumularse detrás de él."""
    class _Guardia:
        def __enter__(self):
            if not _LOCK_VFS.acquire(timeout=_PLAZO_VFS):
                raise DBNoDisponible(
                    f"la base local no responde: {que} lleva más de {_PLAZO_VFS:.0f}s "
                    f"bloqueada ({_motivo_en_vuelo() or 'apertura previa trabada'})")
            global _EN_VUELO
            _EN_VUELO = (que, threading.current_thread().name, time.monotonic())
            return self

        def __exit__(self, *exc):
            global _EN_VUELO
            _EN_VUELO = None
            _LOCK_VFS.release()
            return False
    return _Guardia()


def lock_vfs(que: str):
    """PÚBLICO — serializa una apertura/cierre REAL de SQLite hecha FUERA de este módulo.

    [Integración #5 · auditoría (a)] El almacén de arriba sólo cubre a quien entra por
    `conectar()`. El mutex que produce el deadlock es el de la tabla de inodos del VFS,
    que es **global al PROCESO y no por archivo**: un `close()` sobre `knowledge.db`
    puede trabarse contra un `open()` sobre `aleph.db` igual que si fueran el mismo
    archivo. O sea que un solo módulo que abra sqlite por su cuenta ANULA la capa 2 del
    arreglo para todos los demás.

    Quien tenga su propio `sqlite3.connect()` (hoy: `knowledge_store.SelfHostedStore`,
    que es el corpus RAG y corre en los hilos worker) envuelve con esto su apertura y su
    cierre, y queda en la misma fila que el resto. Es la capa 2 de W, no la 1: no reusa
    conexiones, pero serializar alcanza para que el deadlock no exista (medido en
    §EL DEADLOCK DEL VFS: «open/close serializado ✅ 90 754 ciclos en 30 s»).
    """
    return _con_lock_vfs(que)


def _motivo_en_vuelo() -> Optional[str]:
    v = _EN_VUELO
    if not v:
        return None
    que, hilo, t0 = v
    return f"{que} en '{hilo}' hace {time.monotonic() - t0:.1f}s"


def estado_db() -> dict:
    """Salud del camino de datos, para `/health`. `trabado` = hay una apertura/cierre real
    en vuelo hace más que el plazo ⇒ el VFS quedó tomado y el proceso NO se recupera solo
    (el mutex es de C y el hilo que lo espera no se puede interrumpir): el supervisor debe
    reiniciar el sidecar. Se REPORTA en vez de decir "ok" mientras la app se muere."""
    v = _EN_VUELO
    libres = sum(len(x) for x in _LIBRES.values())
    out = {"estado": "ok", "conexiones_libres": libres, "plazo_s": _PLAZO_VFS}
    if v:
        que, hilo, t0 = v
        esperando = time.monotonic() - t0
        out["en_vuelo"] = {"op": que, "hilo": hilo, "segundos": round(esperando, 1)}
        if esperando > _PLAZO_VFS:
            out["estado"] = "trabado"
            out["motivo"] = (f"el VFS de SQLite quedó tomado: {que} en '{hilo}' hace "
                             f"{esperando:.0f}s. El proceso no se recupera solo.")
            out["recuperable"] = False
    return out


def sin_acento(s: Any) -> Optional[str]:
    """minúsculas + sin diacríticos. Es la mitad SQLite del `ILIKE` de Postgres.

    El `LIKE` de SQLite es case-insensitive **sólo para ASCII** — así lo dice el propio
    `dialect.py` y así se midió: `LIKE '%año%'` NO encuentra «AÑO FISCAL», y `'%sesión%'`
    no encuentra «SESIÓN». En una casa que busca en castellano eso pierde la mitad de los
    resultados en silencio. `dialect._traducir_codigo` traduce `x ILIKE y` a
    `sin_acento(x) LIKE sin_acento(y)`, y esta es la función que ese SQL invoca — por eso
    se registra en TODA conexión, no en la que busca.

    NFD parte «á» en «a» + acento combinante, y `category(c) != "Mn"` tira el segundo.
    Efecto lateral buscado: `sesion` (sin tilde) también encuentra «sesión» — quien busca
    en un teclado apurado no debería quedarse sin resultados.
    """
    if s is None:
        return None
    return "".join(c for c in unicodedata.normalize("NFD", str(s).lower())
                   if unicodedata.category(c) != "Mn")


def _nueva_conexion(p: str, timeout: float) -> sqlite3.Connection:
    """Apertura REAL, serializada y con plazo. Los tres pragmas van SIEMPRE (ver abajo)."""
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    with _con_lock_vfs(f"abrir {os.path.basename(p)}"):
        sq = sqlite3.connect(p, timeout=timeout, check_same_thread=False)
    sq.row_factory = sqlite3.Row          # filas por nombre Y por índice
    sq.execute("PRAGMA foreign_keys = ON")
    sq.execute("PRAGMA journal_mode = WAL")
    sq.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
    # Va acá y no en el que busca, por el mismo motivo que `foreign_keys`: una función
    # definida por el usuario es propiedad de la CONEXIÓN. Si se registrara sólo donde hoy
    # hay un ILIKE, el próximo ILIKE en otra ruta fallaría con `no such function`.
    # Sin `try`: si esto no se puede registrar, el SQL traducido no corre, y esa rotura
    # tiene que ser ruidosa acá y no un LIKE que devuelve de menos allá.
    sq.create_function("sin_acento", 1, sin_acento, deterministic=True)
    return sq


def _cerrar_real(sq: sqlite3.Connection) -> None:
    """Cierre REAL, serializado con las aperturas — la otra mitad del deadlock del VFS."""
    try:
        with _con_lock_vfs("cerrar"):
            sq.close()
    except DBNoDisponible:
        pass          # ya está trabado: no sumar otro hilo perdido al montón


def _devolver(ruta: Optional[str], sq: sqlite3.Connection) -> None:
    """Checkin: deshace cualquier transacción colgada y guarda la conexión para el próximo.

    El rollback es load-bearing y cubre el requisito de "liberar en TODOS los caminos de
    salida": si el caller salió por una excepción (o el cliente cortó a mitad de un
    stream) con un `BEGIN` abierto, esa transacción NO puede viajar al request siguiente.
    Antes lo tapaba el `close()` real; ahora hay que hacerlo explícito.
    """
    if ruta is None or ruta == ":memory:":
        _cerrar_real(sq)              # `:memory:` es privada por conexión: no se recicla
        return
    try:
        sq.rollback()
    except Exception:                 # noqa: BLE001 — conexión inservible: se descarta
        _cerrar_real(sq)
        return
    with _LOCK_ALMACEN:
        libres = _LIBRES.setdefault(ruta, [])
        if len(libres) < _TOPE_LIBRES:
            libres.append(sq)
            return
    _cerrar_real(sq)


def cerrar_almacen(ruta: Optional[str] = None) -> int:
    """Cierra DE VERDAD las conexiones ociosas (shutdown del proceso, teardown de tests).
    Devuelve cuántas cerró. Sin `ruta`, todas."""
    with _LOCK_ALMACEN:
        rutas = [ruta] if ruta is not None else list(_LIBRES)
        sacadas = [c for r in rutas for c in _LIBRES.pop(r, [])]
    for c in sacadas:
        _cerrar_real(c)
    return len(sacadas)


def conectar(path: Optional[str] = None, *, timeout: float = 30.0) -> _Conexion:
    """Toma una conexión al .db del cliente, con los pragmas puestos.

    Reusa una del almacén si hay (ver §EL DEADLOCK DEL VFS: abrir/cerrar por operación
    traba el proceso). `close()` la devuelve. El contrato para el caller NO cambia:
    sigue siendo "una conexión mía, que cierro al terminar", y dos `conectar()` anidados
    siguen dando dos conexiones DISTINTAS (no se comparte transacción).

    Los tres pragmas van SIEMPRE, en este orden y en cada conexión NUEVA:
      - `foreign_keys=ON`  — sin esto los CASCADE del schema no existen (ver cabecera).
      - `journal_mode=WAL` — lectores y escritor no se bloquean; la cola (2.3) tiene ~9
        hilos escritores. Es persistente en el archivo, pero se emite igual porque es
        barato y no depende de quién creó el .db.
      - `busy_timeout`     — con WAL sigue habiendo un solo escritor: sin timeout, dos
        escrituras simultáneas dan `database is locked` en vez de esperar su turno.
      Se emiten una vez por conexión y son propiedad de la conexión, así que sobreviven
      al reciclado — que es justamente por qué el reciclado es seguro acá.
    """
    p = path or ruta_db()
    if p != ":memory:":
        with _LOCK_ALMACEN:
            libres = _LIBRES.get(p)
            sq = libres.pop() if libres else None
        if sq is not None:
            return _Conexion(sq, p)
    return _Conexion(_nueva_conexion(p, timeout), p)


def crear_schema(conn: _Conexion) -> None:
    """Aplica `schema_sqlite.sql`. Idempotente (`CREATE TABLE IF NOT EXISTS`).

    Se re-emite `foreign_keys` después: `executescript()` hace COMMIT implícito y el
    schema trae sus propios `PRAGMA`, así que el estado de la conexión no se da por
    sentado — se vuelve a fijar.
    """
    conn.raw.executescript(_ruta_schema().read_text(encoding="utf-8"))
    conn.raw.execute("PRAGMA foreign_keys = ON")


# ── Bootstrap del schema en el BOOT del cliente [GAP-DEV-DESKTOP §2.1] ──────────

#: Versión del schema del cliente, estampada en `PRAGMA user_version` del .db.
#: Sube cuando el schema cambie de forma que una DB ya desplegada necesite migrar.
#: v2 (2026-07-28) = idempotencia de turnos + enlace de saltos multiagente.
#: v3 (2026-07-31) = `conexiones`, el registro de CONTRACT-CONEXION-v1 §1.
#: v5 (2026-07-31) = las DOS mediciones separadas en `conexiones` (conexion + credencial).
#: v4 (2026-07-31) = receta del transporte HTTP en `conexiones` (url + headers).
VERSION_SCHEMA_CLIENTE = 11

#: Migraciones INCREMENTALES del cliente: {n: sql} — se aplican EN ORDEN a una DB con
#: `0 < user_version < n`. Cuando el schema cambia: el DDL nuevo va al .sql (lo reciben las
#: DBs vírgenes) Y el ALTER va acá con n = versión nueva (lo reciben las DBs YA DESPLEGADAS),
#: y VERSION_SCHEMA_CLIENTE sube a n. Una DB virgen jamás pasa por acá: recibe el .sql
#: completo actual y se estampa directo en la última versión.
#:
#: ⚠️ SQLite NO tiene `ADD COLUMN IF NOT EXISTS` (Postgres sí). Re-aplicar un ALTER ya
#: aplicado es un `duplicate column name` que aborta el `executescript` ENTERO. La barrera
#: real contra eso es `user_version` (una DB en v2 nunca vuelve a entrar acá), pero el
#: bootstrap también sana DBs en estado raro, así que cada ALTER va envuelto en su propio
#: guard idempotente: es el mismo principio del `IF NOT EXISTS` del resto del schema.
#:
#: ⚠️ Y la columna con REFERENCES tiene que quedar con DEFAULT NULL: con `foreign_keys=ON`,
#: SQLite rechaza un ADD COLUMN con REFERENCES y default no-nulo. Nulable es justo lo que
#: queremos (NULL = run normal), así que la restricción coincide con el diseño.
#:
#: Espejo de las migraciones Postgres 0018/0019 y de `schema_sqlite.sql`.
_MIGRACION_2_TANDA_D = """
ALTER TABLE chat_messages ADD COLUMN client_turn_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_turn_role
  ON chat_messages(chat_id, client_turn_id, role)
  WHERE client_turn_id IS NOT NULL;
ALTER TABLE runs ADD COLUMN parent_run_id  TEXT REFERENCES runs(id) ON DELETE SET NULL;
ALTER TABLE runs ADD COLUMN hop_index      INTEGER;
ALTER TABLE runs ADD COLUMN hop_latency_ms INTEGER;
ALTER TABLE runs ADD COLUMN modo           TEXT;
CREATE INDEX IF NOT EXISTS idx_runs_parent ON runs(parent_run_id, hop_index) WHERE parent_run_id IS NOT NULL;
"""

#: v3 — `conexiones`, el REGISTRO (CONTRACT-CONEXION-v1 §1). SOLO CLIENTE: es la primera
#: tabla del cliente SIN contraparte en Postgres, así que esta migración NO espeja ninguna
#: de `platform/db/migrations/*.sql` — la excepción está declarada en
#: `role.TABLAS_SOLO_CLIENTE`.
#:
#: Es un `CREATE TABLE IF NOT EXISTS` puro (cero ALTER), así que es idempotente por
#: construcción y no necesita el guard que sí necesitan los ALTER de la v2.
#:
#: ⚠️ El DDL de acá y el de `schema_sqlite.sql` (tabla 21) tienen que ser IDÉNTICOS: una DB
#: virgen recibe el .sql y una desplegada recibe esto, y las dos tienen que quedar con la
#: misma forma. `test_migracion_3_espeja_el_schema` lo verifica columna por columna.
_MIGRACION_3_REGISTRO_CONEXIONES = """
CREATE TABLE IF NOT EXISTS conexiones (
  id                  TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  entity_id           TEXT NOT NULL,
  nombre_visible      TEXT NOT NULL DEFAULT '',
  transporte          TEXT,
  command             TEXT,
  args                TEXT,
  cwd                 TEXT,
  env_template        TEXT,
  env_publico         TEXT,
  timeout_ms          INTEGER,
  credencial_ref      TEXT,
  scopes              TEXT,
  cuenta              TEXT,
  era                 TEXT,
  version_negociada   TEXT,
  server_info         TEXT,
  tools_snapshot      TEXT,
  fingerprint         TEXT,
  recipe_version      TEXT NOT NULL DEFAULT 'v1',
  habilitado          INTEGER NOT NULL DEFAULT 1,
  ultimo_veredicto    TEXT,
  causa               TEXT,
  ultima_verificacion TEXT,
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  UNIQUE (user_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_conexiones_owner      ON conexiones(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_conexiones_habilitado ON conexiones(user_id) WHERE habilitado = 1;
"""

#: v4 — la receta del transporte HTTP en `conexiones`. El §1 guardaba «cómo reconstruir»
#: pero no tenía dónde poner la mitad de las recetas: un server HTTP no tiene command/args,
#: tiene endpoint y headers. Sin estas columnas, toda entidad `http` caía al fallback.
#:
#: ⚠️ ACÁ SÍ HAY ALTER (a diferencia de la v3, que era un CREATE puro). SQLite no tiene
#: `ADD COLUMN IF NOT EXISTS`, pero la idempotencia NO hace falta escribirla en el SQL: la
#: pone `_aplicar_migracion`, que corre sentencia por sentencia y tolera EXACTAMENTE
#: `duplicate column name` — el resultado que el ALTER buscaba. Cualquier otro error sube.
#: Los tres son nulables y sin REFERENCES, así que `foreign_keys=ON` no los rechaza.
#:
#: ⚠️ Y el DDL de acá tiene que dejar la MISMA forma que `schema_sqlite.sql` (tabla 21), que
#: ya las trae en el CREATE para una DB virgen. `test_migracion_4_espeja_el_schema` lo
#: verifica columna por columna.
_MIGRACION_4_CONEXIONES_HTTP = """
ALTER TABLE conexiones ADD COLUMN url              TEXT;
ALTER TABLE conexiones ADD COLUMN headers_template TEXT;
ALTER TABLE conexiones ADD COLUMN headers_publico  TEXT;
"""

_MIGRACION_5_DOS_MEDICIONES = """
ALTER TABLE conexiones ADD COLUMN conexion   TEXT;
ALTER TABLE conexiones ADD COLUMN credencial TEXT;
"""

#: ⚠️ EL USUARIO JAMÁS VE NUESTRA DEUDA (orden de persona usuaria, 2026-08-04). Una pieza que no se
#: puede traer por un hueco NUESTRO —una receta con un placeholder sin expandir, una ficha
#: que contradice a su belt— no es un servicio a medias: es trabajo nuestro. Se retiene con
#: `estado_interno='pendiente_ingesta'` y NO viaja a ninguna superficie de usuario.
#:
#: Separado de `habilitado` (el permiso del usuario) y de `ultimo_veredicto` (lo que midió el
#: motor) a propósito: son tres cosas que caducan por motivos distintos, y confundirlas haría
#: que despejar una deuda nuestra se viera como si el usuario hubiera desconectado algo.
_MIGRACION_6_ESTADO_INTERNO = """
ALTER TABLE conexiones ADD COLUMN estado_interno  TEXT;
ALTER TABLE conexiones ADD COLUMN bloqueo_interno TEXT;
"""

# v7 · ADUANA PÚBLICA. Es un aviso medido al usuario, no un estado interno ni un
# veredicto: NULL conserva exactamente el comportamiento de una pieza sin reservas.
# JSONB del contrato vive como TEXT en SQLite, igual que `conexion` y `credencial`.
_MIGRACION_7_RESERVA = """
ALTER TABLE conexiones ADD COLUMN reserva TEXT DEFAULT NULL;
"""

#: v8 — `modelos_estado`, EL REGISTRO DE MODELOS (Gate 2 · F4c).
#:
#: POR QUÉ EXISTE, y es el motivo por el que esta obra se cortó de F4b: hoy el estado de un
#: modelo se calcula EN VUELO (`centro_modelos.filas()`) y no se persiste. Sin memoria entre
#: arranques no se puede saber si una pieza **estuvo completa alguna vez**, que es la
#: distinción de la que depende la regla ANTI-YO-YO del acta:
#:
#:     nunca estuvo completa  → onboarding a medias → ADUANA, con su trámite
#:     lo estuvo y hoy falla  → REGRESIÓN           → LOCAL, con su causa operativa
#:
#: Sin esto, un modelo cuyo runtime se apagó dejaría de ser completo en el próximo arranque
#: y se iría a la aduana; al prender Ollama volvería al local. Un yo-yo por cada fallo
#: transitorio: para el usuario, sus modelos se mueven de lugar solos.
#:
#: ⚠️ NO hay columna `estuvo_completa`, y es a propósito. El molde de conectores la DERIVA
#: de `ultimo_veredicto == 'probado'` (`centro_conexiones.py:1999`). Un booleano aparte es
#: un segundo dato que puede desincronizarse del veredicto que lo justifica — y entonces
#: habría dos verdades sobre la misma pieza. El veredicto es la fuente; el booleano, una
#: lectura. `'probado'` significa que el modelo CORRIÓ: no «está instalado», sino «anduvo».
#:
#: ══ LA INVARIANTE QUE SOSTIENE EL ANTI-YO-YO ═══════════════════════════════════════
#: `ultimo_veredicto` es MEMORIA y **NO se degrada cuando un re-verify posterior falla**;
#: la medición viva va a `causa`/`ultima_verificacion`/`evidencia`. Calcado del molde, donde
#: el barrido de arranque escribe SÓLO las mediciones y jamás el veredicto
#: (`centro_conexiones.py:1902-1904`). Una fila `probado` + `causa=sin_runtime` es el estado
#: REGRESIÓN, y es lo que la deja en el LOCAL en vez de mandarla a la aduana.
#: ⚠️ Si algo degradara el veredicto a `roto`, el anti-yo-yo moriría EN SILENCIO: tras el
#: reinicio la pieza volvería a la aduana. `verify_f4c` prueba el ciclo con proceso nuevo.
#:
#: SOLO CLIENTE, como `conexiones`: declarada en `role.TABLAS_SOLO_CLIENTE`.
#: `CREATE TABLE IF NOT EXISTS` puro (cero ALTER) → idempotente por construcción.
#: ⚠️ Este DDL y el de `schema_sqlite.sql` tienen que ser IDÉNTICOS (una DB virgen recibe
#: el .sql, una desplegada recibe esto, y las dos tienen que quedar con la misma forma).
_MIGRACION_8_MODELOS_ESTADO = """
CREATE TABLE IF NOT EXISTS modelos_estado (
  user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  modelo_id           TEXT NOT NULL,
  via                 TEXT,
  ultimo_veredicto    TEXT,
  causa               TEXT,
  ultima_verificacion TEXT,
  evidencia           TEXT,
  PRIMARY KEY (user_id, modelo_id)
);
CREATE INDEX IF NOT EXISTS idx_modelos_estado_user
  ON modelos_estado(user_id, ultima_verificacion);
"""

_MIGRACION_9_INSPECT_LEASES = """
CREATE TABLE IF NOT EXISTS inspect_leases (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inspect_leases_owner ON inspect_leases(owner_id);
CREATE INDEX IF NOT EXISTS idx_inspect_leases_expiry ON inspect_leases(expires_at);
"""

_MIGRACION_10_INSPECT_STATES = """
ALTER TABLE inspect_leases ADD COLUMN status TEXT NOT NULL DEFAULT 'running'
  CHECK(status IN ('start','running','finished','failed','cancelled'));
ALTER TABLE inspect_leases ADD COLUMN finished_at INTEGER;
ALTER TABLE inspect_leases ADD COLUMN pid INTEGER;
"""

_MIGRACION_11_LEGACY_SESSION_VERSION = """
ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0;
"""

_MIGRACIONES_CLIENTE: dict = {
    2: _MIGRACION_2_TANDA_D,
    3: _MIGRACION_3_REGISTRO_CONEXIONES,
    4: _MIGRACION_4_CONEXIONES_HTTP,
    5: _MIGRACION_5_DOS_MEDICIONES,
    6: _MIGRACION_6_ESTADO_INTERNO,
    7: _MIGRACION_7_RESERVA,
    8: _MIGRACION_8_MODELOS_ESTADO,
    9: _MIGRACION_9_INSPECT_LEASES,
    10: _MIGRACION_10_INSPECT_STATES,
    11: _MIGRACION_11_LEGACY_SESSION_VERSION,
}


def _aplicar_migracion(conn, sql: str) -> None:
    """Aplica una migración incremental del cliente, sentencia por sentencia.

    ⚠️ NO es `executescript(sql)` y la diferencia es portante: SQLite no tiene
    `ADD COLUMN IF NOT EXISTS`, así que un ALTER ya aplicado tira `duplicate column name`
    y aborta el script ENTERO — dejando la migración a medias y la DB en un estado que
    ninguna versión describe. Acá cada sentencia va sola, y el ÚNICO error que se tolera es
    exactamente ese: la columna ya está, que es el resultado que la sentencia buscaba.
    Cualquier otro error SUBE — fallo visible, jamás mudo.
    """
    for sentencia in (s.strip() for s in sql.split(";")):
        if not sentencia:
            continue
        try:
            conn.raw.execute(sentencia)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" in str(exc).lower():
                continue
            raise


class SchemaClienteIncompleto(RuntimeError):
    """Tras el bootstrap faltan tablas de la frontera (`role.tablas_del_cliente()`).
    Servir sobre esta DB es exactamente el bug del GAP §2.1 — el caller NO debe."""


def _tablas_esperadas() -> frozenset:
    """La frontera ejecutable del 2.0 (`role.tablas_del_cliente()`), cargada sin
    asumir el sys.path — la MISMA fuente de la que se deriva `schema_sqlite.sql`."""
    try:
        import role
    except ImportError:
        import sys
        plat = str(_AQUI.parent)
        if plat not in sys.path:
            sys.path.insert(0, plat)
        import role
    return role.tablas_del_cliente()


def _sanar_chat_messages_preversionado(conn: _Conexion) -> None:
    """Una DB de campo puede tener tablas pero seguir en user_version=0.

    `CREATE TABLE IF NOT EXISTS` no agrega columnas a esa tabla vieja; el índice v2
    fallaría antes de que el bootstrap pudiera estampar versión. Se agrega la única
    columna incremental ANTES de ejecutar el schema completo. Idempotente por PRAGMA.
    """
    existe = conn.raw.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_messages'"
    ).fetchone()
    if not existe:
        return
    columnas = {
        str(f[1]) for f in conn.raw.execute("PRAGMA table_info(chat_messages)").fetchall()
    }
    if "client_turn_id" not in columnas:
        conn.raw.execute(
            "ALTER TABLE chat_messages ADD COLUMN client_turn_id TEXT"
        )


def asegurar_schema(path: Optional[str] = None) -> dict:
    """Bootstrap IDEMPOTENTE y VERSIONADO del schema del cliente, para el BOOT.

    El agujero que cierra (GAP-DEV-DESKTOP §2.1): `crear_schema()` existía pero solo
    lo llamaban los tests — la .app instalada corría con una DB de CERO tablas y
    servía igual, con cada "no such table" mudo por stderr. Esto corre en cada
    arranque del cliente:

      1. abre (o crea) el .db en `ruta_db()`,
      2. lee `PRAGMA user_version` (0 = virgen, la DB rota de 0 tablas del campo,
         o una DB pre-versionado — los tres casos sanan igual),
      3. si 0 → aplica `schema_sqlite.sql` completo (IF NOT EXISTS: no pisa nada);
         si >0 → aplica sólo las `_MIGRACIONES_CLIENTE` pendientes, en orden,
      4. estampa `user_version = VERSION_SCHEMA_CLIENTE` (nunca hacia atrás: una DB
         de una versión MÁS nueva no se "des-versiona"),
      5. VERIFICA contra `role.tablas_del_cliente()` que TODAS las tablas existen —
         si falta una, `SchemaClienteIncompleto` con la lista.

    Devuelve {"path", "version", "tablas"} para que el boot lo loguee. Cualquier
    fallo LEVANTA — FALLO VISIBLE, JAMÁS MUDO: el caller decide cómo mostrarlo,
    pero nadie sirve como si nada.
    """
    p = path or ruta_db()
    conn = conectar(p)
    try:
        version = conn.raw.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            _sanar_chat_messages_preversionado(conn)
            crear_schema(conn)
            # `CREATE TABLE IF NOT EXISTS` no agrega las columnas nuevas a una tabla
            # `runs` preversionada. La migración es idempotente y completa ese caso.
            _aplicar_migracion(conn, _MIGRACION_2_TANDA_D)
            # Lo mismo para users en una DB pre-versionada: el CREATE actual no altera
            # la tabla existente. Sin esto se estampaba v11 sin session_version y cada
            # sesión Fernet fallaba para siempre con "no such column".
            _aplicar_migracion(conn, _MIGRACION_11_LEGACY_SESSION_VERSION)
        else:
            for n in sorted(_MIGRACIONES_CLIENTE):
                if version < n:
                    _aplicar_migracion(conn, _MIGRACIONES_CLIENTE[n])
                    conn.raw.execute("PRAGMA foreign_keys = ON")
        if version < VERSION_SCHEMA_CLIENTE:
            conn.raw.execute(f"PRAGMA user_version = {int(VERSION_SCHEMA_CLIENTE)}")
        conn.commit()
        existen = {f[0] for f in conn.raw.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        faltan = sorted(_tablas_esperadas() - existen)
        if faltan:
            raise SchemaClienteIncompleto(
                f"schema del cliente incompleto en {p}: faltan {faltan}")
        return {"path": p, "version": max(version, VERSION_SCHEMA_CLIENTE),
                "tablas": len(existen)}
    finally:
        conn.close()
