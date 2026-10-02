"""test_dialect.py — la capa de dialecto. [Casa 2 · Fase 2 · paso 2.2]

Verde = SQLite aceptó el SQL de verdad y devolvió el dato correcto, no que el string se
parezca al esperado. Por eso casi todo se ejerce contra una base real con el schema del
paso 2.1 puesto.

Lo que se prueba, en orden de consecuencia:

  1. **El pragma de FK está en CADA conexión.** Es el requisito que 2.1 arrastró: sin él
     los CASCADE del schema son decoración y el borrado de cuenta deja huérfanos callado.
     Se prueba por efecto (borrar arrastra) y en rojo (sin el pragma, no arrastra).
  2. El traductor no toca lo que está dentro de literales — si lo tocara, corrompería
     contenido del usuario (una memoria que diga "usá ::" o un chat con "%s").
  3. `now()` produce EXACTAMENTE el mismo formato que el DEFAULT del schema. Con
     `CURRENT_TIMESTAMP` no lo produce, y las comparaciones de fecha como texto mienten.
  4. `ANY(%s)` expande SQL *y* parámetros a la vez, y sigue matcheando las filas correctas.
  5. Lo que la capa NO sabe traducir se rechaza ruidoso en vez de emitir SQL plausible.
  6. `with conn.cursor() as cur` funciona (sqlite3.Cursor no lo soporta solo).

Correr:  pytest platform/db/test_dialect.py -v
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

from dialect import AHORA, DialectoNoSoportado, traducir          # noqa: E402
from sqlite_db import conectar, crear_schema                       # noqa: E402


@pytest.fixture()
def conn():
    c = conectar(":memory:")
    crear_schema(c)
    yield c
    c.close()


def sembrar_usuario(conn, email="a@b.c"):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (email) VALUES (%s) RETURNING id", (email,))
        return cur.fetchone()[0]


# ── 1. EL REQUISITO QUE 2.1 ARRASTRÓ ─────────────────────────────────────────────

def test_el_pragma_de_fk_esta_puesto_en_cada_conexion():
    for _ in range(3):
        c = conectar(":memory:")
        assert c.raw.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        c.close()


def test_el_pragma_sobrevive_a_crear_schema():
    """`executescript` hace COMMIT implícito y el schema trae sus propios PRAGMA:
    el estado de la conexión no se da por sentado."""
    c = conectar(":memory:")
    crear_schema(c)
    assert c.raw.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    c.close()


def test_el_pragma_de_fk_no_viaja_en_el_archivo_pero_wal_si(tmp_path):
    """LA ASIMETRÍA QUE JUSTIFICA EL REQUISITO. `journal_mode` es propiedad del ARCHIVO
    (persiste); `foreign_keys` es de la CONEXIÓN (no persiste). Por eso el schema se crea
    una vez pero el pragma va en cada `conectar()`, para siempre."""
    p = str(tmp_path / "aleph.db")
    c1 = conectar(p)
    crear_schema(c1)
    c1.commit()
    c1.close()

    crudo = sqlite3.connect(p)          # una conexión que NO pasa por conectar()
    assert crudo.execute("PRAGMA foreign_keys").fetchone()[0] == 0, (
        "si foreign_keys viniera en 1 solo, este módulo sobraría")
    assert crudo.execute("PRAGMA journal_mode").fetchone()[0] == "wal", (
        "WAL sí debería viajar en el archivo")
    crudo.close()

    c2 = conectar(p)                    # y una que sí
    assert c2.raw.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    c2.close()


def test_el_cascade_borra_de_verdad(conn):
    """El efecto que el pragma habilita: borrar la cuenta arrastra lo del usuario."""
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO puppets (owner_id,name,nicho,config) "
                    "VALUES (%s,'p','quant','{}') RETURNING id", (uid,))
        pid = cur.fetchone()[0]
        cur.execute("INSERT INTO keys (user_id,provider,ciphertext) VALUES (%s,'anthropic',%s)",
                    (uid, b"cifrado"))
        cur.execute("INSERT INTO chats (user_id,puppet_id) VALUES (%s,%s)", (uid, pid))
        cur.execute("DELETE FROM users WHERE id = %s", (uid,))
    for t in ("puppets", "keys", "chats"):
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {t}")
            assert cur.fetchone()[0] == 0, f"{t} quedó huérfana"


def test_rojo_sin_el_pragma_el_borrado_deja_huerfanos():
    """EN ROJO a propósito: el daño exacto que el pragma evita. Si esto se pone verde
    (o sea, si borra igual), es que SQLite cambió el default y hay que revisar todo."""
    c = conectar(":memory:")
    crear_schema(c)
    c.raw.execute("PRAGMA foreign_keys = OFF")          # simula "me olvidé del pragma"
    uid = sembrar_usuario(c)
    with c.cursor() as cur:
        cur.execute("INSERT INTO puppets (owner_id,name,nicho,config) VALUES (%s,'p','q','{}')", (uid,))
        cur.execute("DELETE FROM users WHERE id = %s", (uid,))
        cur.execute("SELECT count(*) FROM puppets")
        assert cur.fetchone()[0] == 1, "sin el pragma DEBERÍA quedar huérfano"
    c.close()


# ── 2. el traductor no corrompe contenido del usuario ────────────────────────────

@pytest.mark.parametrize("adentro", [
    "usá el operador :: para castear",
    "el placeholder %s va acá",
    "corré now() en la consola",
    "mezcla :: y %s y now() junta",
])
def test_no_toca_lo_que_esta_dentro_de_un_literal(adentro):
    sql = f"SELECT * FROM t WHERE nota = '{adentro}' AND id = %s"
    out, _ = traducir(sql, ("x",))
    assert f"'{adentro}'" in out, f"corrompió el literal: {out}"
    assert out.rstrip().endswith("= ?"), f"no tradujo el parámetro de afuera: {out}"


def test_el_contenido_del_usuario_sobrevive_el_viaje_completo(conn):
    """De punta a punta: un texto con PG-ismos adentro se guarda y se lee idéntico."""
    uid = sembrar_usuario(conn)
    veneno = "castea con ::uuid, el param es %s y la hora sale de now()"
    with conn.cursor() as cur:
        cur.execute("INSERT INTO account_memories (owner_id, content) VALUES (%s,%s)", (uid, veneno))
        cur.execute("SELECT content FROM account_memories WHERE owner_id = %s", (uid,))
        assert cur.fetchone()[0] == veneno


def test_no_toca_comentarios():
    out, _ = traducir("SELECT 1 -- ojo con %s y ::uuid\n, %s", ("x",))
    assert "-- ojo con %s y ::uuid" in out
    assert out.count("?") == 1


# ── 3. now(): el formato tiene que coincidir con el DEFAULT del schema ───────────

def test_now_produce_el_mismo_formato_que_el_default_del_schema(conn):
    """Si `now()` y el DEFAULT escriben formatos distintos, ORDER BY miente. El plan
    proponía CURRENT_TIMESTAMP, que da 'YYYY-MM-DD HH:MM:SS' (sin T, sin ms) contra el
    'YYYY-MM-DDTHH:MM:SS.mmm' del schema."""
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        # created_at por DEFAULT; updated_at por now() traducido
        cur.execute("UPDATE users SET updated_at = now() WHERE id = %s", (uid,))
        cur.execute("SELECT created_at, updated_at FROM users WHERE id = %s", (uid,))
        creado, actualizado = cur.fetchone()
    assert creado[10] == "T" and actualizado[10] == "T", (creado, actualizado)
    assert "." in creado and "." in actualizado, "faltan los milisegundos"
    assert len(creado) == len(actualizado), f"formatos distintos: {creado!r} vs {actualizado!r}"


def test_rojo_current_timestamp_ordenaria_mal(conn):
    """EN ROJO: por qué `now()` NO se traduce a CURRENT_TIMESTAMP. La fila escrita con
    CURRENT_TIMESTAMP es POSTERIOR pero ordena ANTES, porque ' ' (0x20) < 'T' (0x54)."""
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO historial (user_id,event) VALUES (%s,'por_default')", (uid,))
        cur.execute("INSERT INTO historial (user_id,event,created_at) "
                    "VALUES (%s,'con_current_timestamp', CURRENT_TIMESTAMP)", (uid,))
        cur.execute("SELECT event FROM historial ORDER BY created_at DESC LIMIT 1")
        primera = cur.fetchone()[0]
    assert primera == "por_default", (
        "si 'con_current_timestamp' saliera primera, CURRENT_TIMESTAMP sería seguro "
        "y este test sobra")


def test_ahora_es_el_mismo_string_que_usa_el_schema():
    schema = open(os.path.join(_AQUI, "schema_sqlite.sql"), encoding="utf-8").read()
    assert AHORA in schema, "dialect.AHORA y el DEFAULT del schema divergieron"


# ── 4. ANY(%s) → IN (?,?,…): toca SQL y parámetros a la vez ─────────────────────

def test_any_expande_sql_y_parametros(conn):
    uid = sembrar_usuario(conn)
    ids = []
    with conn.cursor() as cur:
        for n in ("a", "b", "c"):
            cur.execute("INSERT INTO puppets (owner_id,name,nicho,config) "
                        "VALUES (%s,%s,'quant','{}') RETURNING id", (uid, n))
            ids.append(cur.fetchone()[0])
        cur.execute("DELETE FROM puppets WHERE id = ANY(%s::uuid[])", (ids[:2],))
        assert cur.rowcount == 2
        cur.execute("SELECT name FROM puppets")
        quedan = [r[0] for r in cur.fetchall()]
    assert quedan == ["c"]


def test_any_con_lista_vacia_no_es_error_de_sintaxis(conn):
    """`IN ()` es error de sintaxis en SQLite. La lista vacía tiene que dar 0 filas."""
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO puppets (owner_id,name,nicho,config) VALUES (%s,'x','q','{}')", (uid,))
        cur.execute("DELETE FROM puppets WHERE id = ANY(%s::uuid[])", ([],))
        assert cur.rowcount == 0
        cur.execute("SELECT count(*) FROM puppets")
        assert cur.fetchone()[0] == 1, "una lista vacía no debe borrar nada"


def test_any_respeta_los_parametros_de_antes_y_despues(conn):
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        for n in ("a", "b"):
            cur.execute("INSERT INTO puppets (owner_id,name,nicho,config) VALUES (%s,%s,'q','{}')",
                        (uid, n))
        cur.execute("SELECT count(*) FROM puppets WHERE owner_id = %s AND name = ANY(%s) "
                    "AND nicho = %s", (uid, ["a", "b"], "q"))
        assert cur.fetchone()[0] == 2


# ── 5. lo que no sabe traducir, lo rechaza ───────────────────────────────────────

@pytest.mark.parametrize("sql,aguja", [
    ("SELECT * FROM job_queue FOR UPDATE SKIP LOCKED", "FOR UPDATE"),
    ("UPDATE agent_memories SET meta = jsonb_set(meta,'{k}','1')", "jsonb_set"),
    ("SELECT * FROM puppets WHERE config @> '{}'", "@>"),
])
def test_rechaza_ruidoso_lo_que_no_traduce(sql, aguja):
    with pytest.raises(DialectoNoSoportado) as e:
        traducir(sql, ())
    assert aguja.lower() in str(e.value).lower()


def test_el_rechazo_dice_que_hacer():
    with pytest.raises(DialectoNoSoportado) as e:
        traducir("SELECT 1 FROM job_queue FOR UPDATE", ())
    assert "2.3" in str(e.value), "el mensaje debería apuntar al paso que lo resuelve"


def test_jsonb_set_existe_en_sqlite_pero_devuelve_binario():
    """POR QUÉ se rechaza `jsonb_set` aunque SQLite lo tenga (desde 3.45): devuelve JSONB
    BINARIO donde Postgres devuelve texto. Las columnas del schema son TEXT — dejarlo
    pasar guardaría bytes en una columna de texto sin un solo error. Si algún día SQLite
    devolviera texto acá, este test avisa que el rechazo se puede levantar."""
    crudo = sqlite3.connect(":memory:")
    valor = crudo.execute("SELECT jsonb_set('{\"a\":1}','$.k','x')").fetchone()[0]
    assert isinstance(valor, bytes), (
        f"jsonb_set ya devuelve {type(valor).__name__}: revisar si el rechazo sigue haciendo falta")
    texto = crudo.execute("SELECT json_set('{\"a\":1}','$.k','x')").fetchone()[0]
    assert isinstance(texto, str), "json_set (sin la b) sí devuelve texto: es el reemplazo"
    crudo.close()


# ── 6. la cara de psycopg2 ───────────────────────────────────────────────────────

def test_with_conn_cursor_as_funciona(conn):
    """`sqlite3.Cursor` no soporta el protocolo de context manager; el árbol lo usa así
    en 30 lugares."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1


def test_sqlite3_cursor_crudo_no_lo_soporta():
    """El motivo de que el wrapper exista. Si esto empieza a pasar, el wrapper sobra."""
    crudo = sqlite3.connect(":memory:")
    with pytest.raises(TypeError):
        with crudo.cursor():
            pass
    crudo.close()


def test_las_filas_responden_por_nombre_y_por_indice(conn):
    """Cubre a la vez los 214 `cursor()` (tuplas) y los 10 RealDictCursor (dicts)."""
    uid = sembrar_usuario(conn, "x@y.z")
    with conn.cursor() as cur:
        cur.execute("SELECT id, email FROM users WHERE id = %s", (uid,))
        f = cur.fetchone()
    assert f[0] == uid and f["id"] == uid
    assert f[1] == "x@y.z" and f["email"] == "x@y.z"
    assert dict(f)["email"] == "x@y.z"


def test_cursor_factory_se_acepta_y_se_ignora(conn):
    with conn.cursor(cursor_factory=object) as cur:
        cur.execute("SELECT 1 AS uno")
        assert cur.fetchone()["uno"] == 1


def test_rowcount_tras_update_y_delete(conn):
    """Las guardas de rowcount (auditoría H2) dependen de esto."""
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET tier='premium' WHERE id=%s", (uid,))
        assert cur.rowcount == 1
        cur.execute("UPDATE users SET tier='premium' WHERE id=%s", ("no-existe",))
        assert cur.rowcount == 0
        cur.execute("DELETE FROM users WHERE id=%s", (uid,))
        assert cur.rowcount == 1


def test_commit_y_rollback(conn):
    uid = sembrar_usuario(conn)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET tier='premium' WHERE id=%s", (uid,))
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT tier FROM users WHERE id=%s", (uid,))
        assert cur.fetchone()[0] == "free", "el rollback no revirtió"


# ── 7. intervalos: el signo importa ──────────────────────────────────────────────

def test_intervalo_hacia_adelante_y_hacia_atras(conn):
    """`+` es una fecha futura (available_at); `-` un umbral hacia atrás (el reaper).
    Traducir `-` como `+` dejaría al reaper mirando el futuro: no reclamaría nunca."""
    with conn.cursor() as cur:
        cur.execute("SELECT now() + (%s || ' seconds')::interval, "
                    "       now() - (%s || ' seconds')::interval, now()", (60, 60))
        futuro, pasado, ahora = cur.fetchone()
    assert futuro > ahora, f"el '+' no fue hacia adelante: {futuro} vs {ahora}"
    assert pasado < ahora, f"el '-' no fue hacia atrás: {pasado} vs {ahora}"


def test_make_interval(conn):
    """`make_interval(secs => %s)` — el `=>` de PG hacía fallar al parser con `near ">"`."""
    with conn.cursor() as cur:
        cur.execute("SELECT now() - make_interval(secs => %s), now()", (60,))
        pasado, ahora = cur.fetchone()
    assert pasado < ahora


def test_left_se_vuelve_substr(conn):
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO chats (user_id,title) VALUES (%s,%s)", (uid, "x" * 200))
        cur.execute("SELECT LEFT(title, 80) FROM chats WHERE user_id = %s", (uid,))
        assert len(cur.fetchone()[0]) == 80


# ── 8. casts e ILIKE ─────────────────────────────────────────────────────────────

def test_los_casts_se_borran_sin_romper(conn):
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE id = %s::uuid", (uid,))
        assert cur.fetchone()[0] == uid


def test_ilike_se_vuelve_like(conn):
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO chats (user_id,title) VALUES (%s,'Hola Mundo')", (uid,))
        cur.execute("SELECT count(*) FROM chats WHERE title ILIKE %s", ("hola%",))
        assert cur.fetchone()[0] == 1, "ILIKE debería seguir siendo insensible a mayúsculas"


def test_pct_literal_no_se_confunde_con_parametro(conn):
    """`%%` es un `%` literal en psycopg2. Si se tradujera como parámetro, el LIKE se rompe."""
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO chats (user_id,title) VALUES (%s,'100%% seguro')", (uid,))
        cur.execute("SELECT title FROM chats WHERE user_id = %s", (uid,))
        assert cur.fetchone()[0] == "100% seguro"


def test_true_false_se_vuelven_1_0(conn):
    """El schema guarda 0/1; `WHERE pinned = TRUE` no matchearía filas escritas con 1."""
    uid = sembrar_usuario(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO account_memories (owner_id,content,pinned) VALUES (%s,'x',%s)",
                    (uid, 1))
        cur.execute("SELECT count(*) FROM account_memories WHERE pinned = TRUE")
        assert cur.fetchone()[0] == 1
