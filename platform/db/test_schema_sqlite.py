"""test_schema_sqlite.py — verifica el schema del cliente. [Casa 2 · Fase 2 · paso 2.1]

Verde = efecto real sobre un SQLite de verdad, nunca narración. Cada test de acá crea
la base, escribe, y mira lo que quedó guardado.

Lo que se prueba, en orden de consecuencia:

  1. El schema crea EXACTAMENTE las tablas que declara `role.py` — la lista se deriva
     importando el frozenset, no copiándolo. Si alguien agrega una tabla a la frontera
     y no al schema (o al revés), este test se pone rojo.
  2. Las 7 tablas del plano de control NO existen. La frontera del 2.0 tiene que
     sobrevivir la traducción: el cliente no puede tocar lo que no está.
  3. Ningún PG-ismo se coló como nombre de tipo. SQLite ACEPTA `JSONB`/`TIMESTAMPTZ`/
     `BIGSERIAL` sin chistar, así que "no dio error" no prueba nada: hay que mirar el
     tipo declarado tabla por tabla.
  4. NINGÚN id queda en NULL. Se inserta en las 22 tablas omitiendo el id, como hace
     `repo.py`, y se exige que lo guardado no sea NULL.
  5. Las PK sin default (`method_runs.run_id`, `schema_migrations.version`) RECHAZAN
     NULL — en Postgres es gratis (PK implica NOT NULL), en SQLite hay que escribirlo.
  6. EN ROJO: la traducción ingenua (el molde tal cual, o el tipo copiado de Postgres)
     produce ids NULL. Es la prueba de que los guards del schema son portantes y no
     decoración: si alguien los saca, esto es lo que pasa.

Correr:  pytest platform/db/test_schema_sqlite.py -v
    o:   python3 platform/db/test_schema_sqlite.py
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import uuid

_DB_DIR = os.path.dirname(os.path.abspath(__file__))
_PLATFORM_DIR = os.path.dirname(_DB_DIR)
_SCHEMA_PATH = os.path.join(_DB_DIR, "schema_sqlite.sql")

sys.path.insert(0, _PLATFORM_DIR)
import role  # noqa: E402  — la frontera ejecutable del paso 2.0

# Los únicos tipos que SQLite entiende de verdad. Cualquier otro nombre declarado
# (JSONB, TIMESTAMPTZ, UUID, BIGSERIAL, BOOLEAN, BYTEA…) se acepta sin error y sin
# semántica: es exactamente el fallo silencioso que buscamos.
TIPOS_PERMITIDOS = {"TEXT", "INTEGER", "BLOB"}

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def abrir() -> sqlite3.Connection:
    """Una base nueva en memoria con el schema aplicado y los FK encendidos."""
    with open(_SCHEMA_PATH, encoding="utf-8") as fh:
        schema = fh.read()
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema)
    conn.execute("PRAGMA foreign_keys = ON")   # en SQLite viene APAGADO por default
    return conn


def tablas(conn) -> set:
    filas = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {f[0] for f in filas}


# ── 1. la frontera se respeta ────────────────────────────────────────────────────

def test_crea_exactamente_las_tablas_del_frozenset():
    """El schema y `role.py` no pueden divergir: la lista sale del frozenset."""
    conn = abrir()
    esperadas = set(role.tablas_del_cliente())
    reales = tablas(conn)
    assert reales == esperadas, (
        f"faltan={sorted(esperadas - reales)} sobran={sorted(reales - esperadas)}"
    )
    assert len(reales) == 23, f"se esperaban 23 tablas, hay {len(reales)}"


def test_las_tablas_de_control_no_existen():
    """La frontera del 2.0 sobrevive la traducción: plata y plan NO viajan al cliente."""
    conn = abrir()
    reales = tablas(conn)
    filtradas = reales & set(role.TABLAS_CONTROL)
    assert not filtradas, f"tablas de control filtradas al cliente: {sorted(filtradas)}"


# ── 2. el riesgo real: los tipos ─────────────────────────────────────────────────

def test_ningun_pgismo_se_colo_como_tipo():
    """SQLite acepta `JSONB`/`TIMESTAMPTZ`/`BIGSERIAL` sin error. Hay que mirar, no asumir."""
    conn = abrir()
    ofensas = []
    for t in sorted(tablas(conn)):
        for col in conn.execute(f"PRAGMA table_info({t})").fetchall():
            nombre, tipo = col[1], (col[2] or "").upper()
            if tipo not in TIPOS_PERMITIDOS:
                ofensas.append(f"{t}.{nombre} declarada como '{tipo}'")
    assert not ofensas, "tipos que SQLite acepta pero no entiende:\n  " + "\n  ".join(ofensas)


def test_las_tres_bigserial_son_integer_primary_key():
    """BIGSERIAL sólo autoincrementa si el tipo declarado es exactamente INTEGER
    (alias de rowid). `BIGINT PRIMARY KEY` se acepta y NO autoincrementa."""
    conn = abrir()
    for t in ("historial", "chat_messages", "instrumentation_logs"):
        cols = {c[1]: c for c in conn.execute(f"PRAGMA table_info({t})").fetchall()}
        tipo, es_pk = (cols["id"][2] or "").upper(), cols["id"][5]
        assert tipo == "INTEGER", f"{t}.id declarada '{tipo}', debe ser INTEGER para autoincrementar"
        assert es_pk, f"{t}.id no es PRIMARY KEY"


def test_los_gin_no_se_replicaron():
    """D2: los 3 GIN degradarían a full scan sin avisar. No se replican, a propósito."""
    conn = abrir()
    idx = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name IS NOT NULL").fetchall()}
    for gin in ("idx_puppets_config_gin", "idx_instr_belt_gin", "idx_instr_senal_gin"):
        assert gin not in idx, f"{gin} no debería existir en SQLite (D2)"


# ── 3. EL PUNTO: ningún id queda en NULL ─────────────────────────────────────────

def _sembrar(conn) -> dict:
    """Fila mínima por tabla, SIEMPRE omitiendo el id (como hace repo.py).
    Devuelve {tabla: (columna_pk, valor_guardado)}."""
    got = {}

    def ins(tabla, cols, vals, pk="id"):
        ph = ",".join("?" * len(vals))
        cur = conn.execute(f"INSERT INTO {tabla} ({cols}) VALUES ({ph}) RETURNING {pk}", vals)
        got[tabla] = (pk, cur.fetchone()[0])
        return got[tabla][1]

    uid = ins("users", "email", ("a@b.c",))
    pid = ins("puppets", "owner_id,name,nicho,config", (uid, "p", "quant", "{}"))
    rid = ins("runs", "puppet_id,user_id", (pid, uid))
    ins("outputs", "run_id,kind", (rid, "obra"))
    ins("historial", "user_id,event", (uid, "creado"))
    ins("keys", "user_id,provider,ciphertext", (uid, "anthropic", b"\x00cifrado"))
    cid = ins("chats", "user_id,puppet_id", (uid, pid))
    ins("chat_messages", "chat_id,role,content", (cid, "user", "hola"))
    mid = ins("methods", "user_id,name,spec", (uid, "m", "{}"))
    ins("instructions", "user_id,content", (uid, "sé riguroso"))
    ins("agent_memories", "puppet_id,content", (pid, "recuerdo"))
    ins("shared_memories", "composition_id,content", (pid, "compartido"))
    ins("account_memories", "owner_id,content", (uid, "de cuenta"))
    did = ins("knowledge_docs", "composition_id,doc_name", (pid, "apunte.pdf"))
    ins("knowledge_chunks", "composition_id,doc_id,chunk_ix,content", (pid, did, 0, "trozo"))
    ins("job_queue", "kind", ("construir",))
    ins("held_actions", "run_id,recipe,server,tool,args", (rid, "{}", "gmail", "send", "{}"))
    ins("instrumentation_logs", "run_id,belt,trayectoria", (rid, "{}", "[]"))
    ins("conexiones", "user_id,entity_id", (uid, "zotero"))

    # [F4c] `modelos_estado` tiene PK COMPUESTA (user_id, modelo_id): no hay `id` que
    # pueda quedar en NULL, y las dos partes las provee el código. Se siembra igual para
    # que el guard de cobertura la vea.
    conn.execute("INSERT INTO modelos_estado (user_id,modelo_id,via,ultimo_veredicto) "
                 "VALUES (?,?,?,?)", (uid, "qwen3:8b", "local", "probado"))
    got["modelos_estado"] = ("user_id", conn.execute(
        "SELECT user_id FROM modelos_estado").fetchone()[0])

    # Infra shared between processes: lease id is generated by the admission code.
    conn.execute("INSERT INTO inspect_leases(id,owner_id,expires_at) VALUES (?, ?, 9999999999)",
                 (str(uuid.uuid4()), uid))
    got["inspect_leases"] = ("id", conn.execute(
        "SELECT id FROM inspect_leases").fetchone()[0])

    # Las dos PK sin default: el código las provee (no las inventa el schema).
    conn.execute("INSERT INTO method_runs (run_id,method_id,state) VALUES (?,?,?)", (rid, mid, "{}"))
    got["method_runs"] = ("run_id", conn.execute("SELECT run_id FROM method_runs").fetchone()[0])
    conn.execute("INSERT INTO schema_migrations (version,name,checksum) VALUES ('0001','base','x')")
    got["schema_migrations"] = ("version", conn.execute("SELECT version FROM schema_migrations").fetchone()[0])
    return got


def test_ningun_id_queda_en_null():
    """EL TEST QUE IMPORTA. Se escribe en cada tabla; leases use an explicit id."""
    conn = abrir()
    got = _sembrar(conn)
    assert set(got) == set(role.tablas_del_cliente()), "el sembrado no cubrió todas las tablas"
    nulos = [f"{t}.{pk}" for t, (pk, v) in got.items() if v is None]
    assert not nulos, f"ids en NULL tras el INSERT: {nulos}"


def test_los_uuid_generados_son_uuid4_validos():
    """No alcanza con 'no es NULL': tiene que ser un uuid v4 bien formado y único."""
    conn = abrir()
    got = _sembrar(conn)
    autogeneradas = set(got) - {"historial", "chat_messages", "instrumentation_logs",
                                "method_runs", "schema_migrations"}
    for t in sorted(autogeneradas):
        v = got[t][1]
        assert isinstance(v, str) and UUID_RE.match(v), f"{t}.id no es uuid4: {v!r}"
    nuevos = [conn.execute(
        "INSERT INTO users (email) VALUES (?) RETURNING id", (f"u{i}@x.c",)).fetchone()[0]
        for i in range(500)]
    assert all(UUID_RE.match(u) for u in nuevos), "el default generó un uuid mal formado"
    assert len(set(nuevos)) == 500, "el default de uuid produjo colisiones"


def test_los_bigserial_autoincrementan():
    conn = abrir()
    _sembrar(conn)
    rid = conn.execute("SELECT id FROM runs").fetchone()[0]
    a = conn.execute("INSERT INTO instrumentation_logs (run_id,belt,trayectoria) "
                     "VALUES (?,'{}','[]') RETURNING id", (rid,)).fetchone()[0]
    b = conn.execute("INSERT INTO instrumentation_logs (run_id,belt,trayectoria) "
                     "VALUES (?,'{}','[]') RETURNING id", (rid,)).fetchone()[0]
    assert a is not None and b == a + 1, f"no autoincrementa: {a} -> {b}"


def test_las_pk_sin_default_rechazan_null():
    """En Postgres PK implica NOT NULL. En SQLite hay que escribirlo — y acá está escrito."""
    conn = abrir()
    _sembrar(conn)
    for sql, params in (
        ("INSERT INTO method_runs (run_id,state) VALUES (NULL,'{}')", ()),
        ("INSERT INTO schema_migrations (version,name,checksum) VALUES (NULL,'n','c')", ()),
    ):
        try:
            conn.execute(sql, params)
        except sqlite3.IntegrityError:
            continue
        raise AssertionError(f"aceptó una PK en NULL: {sql}")


# ── 4. lo que se pierde si no se enciende el pragma ──────────────────────────────

def test_el_cascade_borra_de_verdad_con_el_pragma():
    """El borrado de cuenta depende de estos CASCADE. Con el pragma, funcionan."""
    conn = abrir()
    _sembrar(conn)
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    for t in ("puppets", "keys", "chats", "instructions", "account_memories"):
        n = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        assert n == 0, f"{t} quedó con {n} filas huérfanas tras borrar el usuario"


def test_sin_el_pragma_el_cascade_es_decorativo():
    """EN ROJO, a propósito: documenta por qué `PRAGMA foreign_keys=ON` no es opcional.
    Sin él, SQLite ignora los FK y el borrado de cuenta deja huérfanos EN SILENCIO."""
    with open(_SCHEMA_PATH, encoding="utf-8") as fh:
        conn = sqlite3.connect(":memory:")
        conn.executescript(fh.read())
    conn.execute("PRAGMA foreign_keys = OFF")
    _sembrar(conn)
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    huerfanos = conn.execute("SELECT count(*) FROM puppets").fetchone()[0]
    assert huerfanos == 1, "sin el pragma deberían quedar huérfanos (si no, cambió el default)"


# ── 5. EN ROJO: la traducción ingenua sí falla ───────────────────────────────────

def test_rojo_la_traduccion_ingenua_deja_ids_en_null():
    """La prueba de que los guards del schema son PORTANTES, no decoración.
    Estos tres DDL no dan error en SQLite. Dan NULL."""
    conn = sqlite3.connect(":memory:")
    casos = {
        "BIGSERIAL PRIMARY KEY": "CREATE TABLE a (id BIGSERIAL PRIMARY KEY, x TEXT)",
        "BIGINT PRIMARY KEY":    "CREATE TABLE b (id BIGINT PRIMARY KEY, x TEXT)",
        "TEXT PRIMARY KEY":      "CREATE TABLE c (id TEXT PRIMARY KEY, x TEXT)",
    }
    for i, (etiqueta, ddl) in enumerate(casos.items()):
        t = "abc"[i]
        conn.execute(ddl)                                   # no falla: SQLite lo acepta
        conn.execute(f"INSERT INTO {t} (x) VALUES ('v')")   # tampoco falla
        got = conn.execute(f"SELECT id FROM {t}").fetchone()[0]
        assert got is None, f"'{etiqueta}' ya no deja NULL — revisar si cambió SQLite"


def test_rojo_el_molde_de_knowledge_store_tal_cual_dejaria_ids_en_null():
    """`knowledge_store._SCHEMA` usa `id TEXT PRIMARY KEY` y anda — pero sólo porque su
    código SIEMPRE pasa el id. `repo.py` lo omite. Copiar el molde tal cual, acá, sería
    el fallo silencioso."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE molde (id TEXT PRIMARY KEY, email TEXT NOT NULL)")
    conn.execute("INSERT INTO molde (email) VALUES ('a@b.c')")   # como repo.py:259
    assert conn.execute("SELECT id FROM molde").fetchone()[0] is None

    # El schema real, con NOT NULL + DEFAULT, no tiene ese agujero.
    real = abrir()
    uid = real.execute("INSERT INTO users (email) VALUES ('a@b.c') RETURNING id").fetchone()[0]
    assert uid is not None and UUID_RE.match(uid)


# ── 4. el registro (21) — los DOS caminos tienen que dar la MISMA forma ──────────

def _forma(conn, tabla: str) -> tuple:
    """(columnas, índices) de una tabla — lo único que importa comparar entre caminos."""
    cols = tuple(sorted(
        (c[1], (c[2] or "").upper(), c[3], c[4], c[5])          # nombre, tipo, notnull, default, pk
        for c in conn.execute(f"PRAGMA table_info({tabla})").fetchall()
    ))
    idx = tuple(sorted(
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? AND name IS NOT NULL",
            (tabla,)).fetchall()
        if not r[0].startswith("sqlite_")
    ))
    return cols, idx


def test_la_cadena_de_migraciones_espeja_el_schema():
    """EL INVARIANTE DURABLE. Una DB VIRGEN recibe `schema_sqlite.sql`; una DESPLEGADA
    recibe la CADENA de migraciones pendientes. Los dos caminos tienen que dejar la misma
    forma.

    Se compara contra la cadena ENTERA (`_MIGRACIONES_CLIENTE` en orden), no contra una
    migración suelta: la v3 sola ya no espeja al `.sql` desde que la v4 agregó la receta
    HTTP, y eso es correcto — lo que tiene que espejar es la suma. Escrito así, el test
    sigue valiendo cuando aparezca la v5 sin que haya que tocarlo.
    """
    sys.path.insert(0, _DB_DIR)
    import sqlite_db

    virgen = abrir()                                    # camino .sql

    migrada = sqlite3.connect(":memory:")               # camino migración, en orden
    migrada.execute("CREATE TABLE users (id TEXT PRIMARY KEY NOT NULL, email TEXT)")
    for n in sorted(sqlite_db._MIGRACIONES_CLIENTE):
        for s in (x.strip() for x in sqlite_db._MIGRACIONES_CLIENTE[n].split(";")):
            if not s:
                continue
            try:
                migrada.execute(s)
            except sqlite3.OperationalError as e:
                # la v2 toca tablas que este test no crea (chat_messages/runs): no es su tema
                if "no such table" not in str(e).lower():
                    raise

    assert _forma(virgen, "conexiones") == _forma(migrada, "conexiones"), (
        "schema_sqlite.sql y la cadena de migraciones divergieron"
    )


def test_la_migracion_4_es_idempotente():
    """`_aplicar_migracion` corre sentencia por sentencia y tolera `duplicate column name`
    — que es el resultado que el ALTER buscaba. Sin eso, re-aplicarla abortaría el script
    entero y dejaría la DB en un estado que ninguna versión describe."""
    sys.path.insert(0, _DB_DIR)
    import sqlite_db

    class _Wrap:
        def __init__(self, raw): self.raw = raw

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY NOT NULL, email TEXT)")
    conn.executescript(sqlite_db._MIGRACION_3_REGISTRO_CONEXIONES)
    w = _Wrap(conn)
    sqlite_db._aplicar_migracion(w, sqlite_db._MIGRACION_4_CONEXIONES_HTTP)
    sqlite_db._aplicar_migracion(w, sqlite_db._MIGRACION_4_CONEXIONES_HTTP)   # otra vez
    cols = {c[1] for c in conn.execute("PRAGMA table_info(conexiones)")}
    assert {"url", "headers_template", "headers_publico"} <= cols


def test_la_migracion_3_es_idempotente():
    """El bootstrap sana DBs en estado raro: re-aplicarla no puede abortar el script."""
    sys.path.insert(0, _DB_DIR)
    import sqlite_db

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY NOT NULL, email TEXT)")
    conn.executescript(sqlite_db._MIGRACION_3_REGISTRO_CONEXIONES)
    conn.executescript(sqlite_db._MIGRACION_3_REGISTRO_CONEXIONES)   # otra vez: no explota
    assert "conexiones" in tablas(conn)


def test_session_version_espeja_schema_y_migracion_sin_perder_usuarios():
    """Una DB nueva y una desplegada reciben la misma generación revocable."""
    sys.path.insert(0, _DB_DIR)
    import sqlite_db

    nueva = abrir()
    nueva_col = {c[1]: c for c in nueva.execute("PRAGMA table_info(users)")}
    assert nueva_col["session_version"][2].upper() == "INTEGER"
    assert nueva_col["session_version"][3] == 1
    assert str(nueva_col["session_version"][4]).strip("'\"") == "0"

    desplegada = sqlite3.connect(":memory:")
    desplegada.execute("CREATE TABLE users (id TEXT PRIMARY KEY NOT NULL, email TEXT)")
    desplegada.execute("INSERT INTO users VALUES ('u1', 'a@b.c')")
    desplegada.executescript(sqlite_db._MIGRACION_11_LEGACY_SESSION_VERSION)
    assert desplegada.execute(
        "SELECT email, session_version FROM users WHERE id='u1'"
    ).fetchone() == ("a@b.c", 0)


def test_boot_preversionado_agrega_session_version_antes_de_estampar_v11(tmp_path):
    """El camino real user_version=0 no puede saltarse la migración de sesiones."""
    sys.path.insert(0, _DB_DIR)
    import sqlite_db

    path = tmp_path / "preversionada.sqlite"
    conn = sqlite3.connect(path)
    with open(_SCHEMA_PATH, encoding="utf-8") as fh:
        preversionado = fh.read().replace(
            "  session_version INTEGER NOT NULL DEFAULT 0,\n", "")
    conn.executescript(preversionado)
    conn.execute("INSERT INTO users (id, email) VALUES ('u1', 'a@b.c')")
    conn.commit()
    conn.close()

    info = sqlite_db.asegurar_schema(str(path))
    checked = sqlite3.connect(path)
    try:
        cols = {c[1] for c in checked.execute("PRAGMA table_info(users)")}
        assert info["version"] == sqlite_db.VERSION_SCHEMA_CLIENTE == 11
        assert "session_version" in cols
        assert checked.execute(
            "SELECT email, session_version FROM users WHERE id='u1'"
        ).fetchone() == ("a@b.c", 0)
    finally:
        checked.close()


def test_el_registro_no_acepta_dos_filas_para_la_misma_entidad():
    """§1: una fila por ENTIDAD, con alcance por usuario (la forma de `keys`)."""
    conn = abrir()
    uid = conn.execute("INSERT INTO users (email) VALUES ('a@b.c') RETURNING id").fetchone()[0]
    conn.execute("INSERT INTO conexiones (user_id, entity_id) VALUES (?,?)", (uid, "zotero"))
    try:
        conn.execute("INSERT INTO conexiones (user_id, entity_id) VALUES (?,?)", (uid, "zotero"))
        assert False, "UNIQUE(user_id, entity_id) no se está aplicando"
    except sqlite3.IntegrityError:
        pass


def test_el_registro_hereda_el_borrado_de_cuenta():
    """La conexión es data del usuario: se va con él (mismo CASCADE que `keys`)."""
    conn = abrir()
    conn.execute("PRAGMA foreign_keys = ON")
    uid = conn.execute("INSERT INTO users (email) VALUES ('a@b.c') RETURNING id").fetchone()[0]
    conn.execute("INSERT INTO conexiones (user_id, entity_id) VALUES (?,?)", (uid, "zotero"))
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    assert conn.execute("SELECT COUNT(*) FROM conexiones").fetchone()[0] == 0


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if not nombre.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok   {nombre}")
        except AssertionError as e:
            fallos += 1
            print(f"  FALLA {nombre}\n        {e}")
    print(f"\n{'TODO VERDE' if not fallos else f'{fallos} EN ROJO'}")
    sys.exit(1 if fallos else 0)
